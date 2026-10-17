"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only: a made-up document center
drawn the way the owner's survey found Chase's, driven through the site
layer's own code with the core's press replaced by the fake's."""
import ast
import io
import json
import logging
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from urllib.parse import urlencode

import pytest

HERE = Path(__file__).resolve().parent.parent
# This checkout's own core, ahead of any installed copy, so its capture is
# the one tested.
sys.path.insert(0, str(HERE.parents[1] / "core"))
sys.path.insert(0, str(HERE))
import chasebusiness_site as site  # noqa: E402
import chasebusiness_docs as docs  # noqa: E402

BASE = "https://secure.chase.com"
DOCREF = BASE + site.DOCREF_PATH
PDF_URL = BASE + "/svc/rr/documents/secure/idal/v5/pdfdoc/star/list?docKey=KEYZZ&csrftoken=TOKZZ"
DASHBOARD = BASE + "/web/auth/dashboard#/dashboard/index/index"
CUR = 2026
EIGHT_YEARS = tuple(range(CUR, CUR - 8, -1))

# Invented accounts, which must never leave through a log, the console, a
# trace or a file name.
CHK = {"id": "bottom-7700112233", "label": "BUS COMPLETE CHK (...4321)"}
CARD = {"id": "bottom-7700445566", "label": "BUSINESS CARD (...8765)"}
DEBIT = {"id": "bottom-7700778899", "label": "BUS TOTAL DEBIT (...5555)"}
# The cardholder, as the live menu draws one: an initial, a surname and a
# last four of its own.
HOLDER = {"id": "bottom-7700990011", "label": "Z. QUILLFEATHER (...2468)"}
SECRETS = ["BUS COMPLETE CHK", "BUSINESS CARD (...8765)", "BUS TOTAL DEBIT", "2468",
           "QUILLFEATHER", "4321", "8765", "5555", "7700112233", "7700445566",
           "7700778899", "7700990011", "DOCQX", "KEYZZ", "TOKZZ"]


def _pdf(tail: str = "") -> bytes:
    """A statement PDF whose text prints an account number ending in
    `tail`, the way Chase prints it in full."""
    from paperpull_core import testkit
    return testkit.text_pdf(["Business Complete Checking", "Account Number: 000000%s" % tail])


PDF = _pdf("4321")


def _card_pdf(tail: str, iso: str) -> bytes:
    """A card statement PDF, its number masked and its closing date in the
    two-digit year form a card statement prints."""
    from paperpull_core import testkit
    d = site._date.fromisoformat(iso)
    return testkit.text_pdf(["Ink Business Unlimited", "Account Number: XXXX XXXX XXXX %s" % tail,
                             "Opening/Closing Date 09/14/26 - %02d/%02d/%02d"
                             % (d.month, d.day, d.year % 100)])


def anchor_css(n):
    return ("#accountsTable-STATEMENTS-row%d a#accountsTable-STATEMENTS-row%d"
            "-cell3-requestThisDocumentAnchor-download" % (n, n))


def item(doc_id, iso, pages=2, kind="Statement"):
    return {"documentId": doc_id, "documentDate": iso.replace("-", ""), "pageCount": pages,
            "documentTypeDesc": kind, "inserts": [], "adaVersionAvailable": True}


def label_date(iso):
    return site._row_label_date(iso)


# ---------------------------------------------------------------------------
# The made-up document center
# ---------------------------------------------------------------------------

class Request:
    def __init__(self, body, method="POST"):
        self.post_data, self.method = body, method


class Response:
    def __init__(self, account_id, filt, data, status=200, url=DOCREF, method="POST", raw=None):
        self.url, self.status = url, status
        self.request = Request(urlencode({"accountFilter": account_id,
                                          "dateFilter.idalDateFilterType": filt}), method)
        self._data, self._raw = data, raw

    def json(self):
        if self._raw is not None:
            return json.loads(self._raw)
        return self._data


class Download:
    def __init__(self, url, body):
        self.url, self.body = url, body
        self.suggested_filename = "20260930-STATEMENTS-4321-.pdf"
        self.canceled = False

    def save_as(self, path):
        Path(path).write_bytes(self.body)

    def cancel(self):
        self.canceled = True


class Info:
    value = None


class Locator:
    def __init__(self, page, css):
        self.page, self.css = page, css

    def _labels(self):
        return self.page.labels_for(self.css)

    def count(self):
        if self.css == "input[type='password']":
            return 1 if self.page.password else 0
        if self.css == site.FALLBACK["doc_row"]:
            return len(self.page.state()["rows"])
        return 1 if self._labels() is not None else 0

    def is_visible(self):
        return self._labels() is not None

    def evaluate(self, js):
        assert js == site._LABELS_JS
        return list(self._labels() or [])

    def inner_text(self, timeout=None):
        return ""


class Center:
    """Accounts: dicts of id, label, years ({year: [items]}) or None for an
    account with no Statements accordion."""

    def __init__(self, accounts, selected=0, years=EIGHT_YEARS):
        self.accounts = accounts
        self.years = list(years)
        self.initial = selected
        self.url = DASHBOARD
        self.listeners = {"response": [], "download": [], "popup": []}
        self.emitted, self.downloads, self.presses = [], [], []
        self.dialog = self.password = False
        self.duplicate_answers = False
        self.answer_override = {}     # (account_id, filter) -> Response factory
        self.rows_override = None
        # None: a statement printing the current account's own last four.
        self.download_body = None
        self.download_url = PDF_URL
        self.downloads_per_save = 1
        self.on_goto = None
        self.on_wait = None
        self.option_place = "row"     # "row", "menu", "detached", "other_row"
        self.late_download = False
        self.folder_copy = None       # a folder to drop the browser's own file in
        self.state_hook = None
        self.closed = False
        # The card row's Saves document link: its labels when not its own
        # date and words, and whether its press opens a new tab too.
        self.anchor_labels = None
        self.popup_on_save = False
        self.saving = None
        self.reset()

    # -- the page's own behavior -------------------------------------------
    def reset(self):
        self.selected = self.initial
        self.expanded = True
        self.year = CUR
        self.picker_open = False
        self.menu_open = None

    def acct(self):
        return self.accounts[self.selected]

    def account_id(self, a=None):
        return (a or self.acct())["id"][len("bottom-"):]

    def items(self):
        years = self.acct().get("years")
        return list((years or {}).get(self.year, []))

    def answer(self):
        aid = self.account_id()
        filt = site.filter_for(CUR, self.year)
        if (aid, filt) in self.answer_override:
            return self.answer_override[(aid, filt)]()
        data = {"code": "SUCCESS", "payeeId": "x", "paperless": True}
        its = self.items()
        if its:
            data["idaldocRefs"] = its
        return Response(aid, filt, data)

    def emit_list(self):
        if self.acct().get("years") is None or not self.expanded:
            return
        self._emit(self.answer())
        if self.duplicate_answers:
            self._emit(self.answer())

    def shape(self):
        """How the current account's rows save: "menu" (checking),
        "anchor" (a business card's Saves document link), "both" or
        "neither"."""
        return self.acct().get("shape", "menu")

    def _download(self):
        body = self.download_body
        if body is None and self.saving is not None:
            iso = site.answer_date(self.items()[self.saving]["documentDate"])
            body = _card_pdf(site.label_tail(self.acct()["label"]), iso)
        if body is None:
            body = _pdf(site.label_tail(self.acct()["label"]))
        dl = Download(self.download_url, body)
        if self.folder_copy is not None:
            (Path(self.folder_copy) / dl.suggested_filename).write_bytes(body)
        self.downloads.append(dl)
        for f in list(self.listeners["download"]):
            f(dl)

    def _emit(self, resp):
        self.emitted.append(resp)
        for f in list(self.listeners["response"]):
            f(resp)

    def goto(self, url, **kw):
        self.url = url
        if self.late_download and self.downloads:
            self.late_download = False
            self._download()
        self.reset()
        if self.on_goto:
            self.on_goto(self)
        self.emit_list()

    def click(self, css):
        self.presses.append(css)
        if css.startswith("#bottom-"):
            self.selected = [a["id"] for a in self.accounts].index(css[1:])
            self.year, self.picker_open, self.menu_open = CUR, False, None
            self.emit_list()
        elif css == "#" + site.STATEMENTS_ACCORDION_ID:
            self.expanded = True
            self.emit_list()
        elif css == "#" + site.YEAR_PICKER_ID:
            self.picker_open = True
        elif css.startswith("#container-"):
            self.year = self.years[int(css.split("-")[1])]
            self.picker_open = False
            self.emit_list()
        elif "downloadDocumentDropdown" in css:
            self.menu_open = int(css.rsplit("-row", 1)[1].split("-")[0])
        elif css.endswith("-downloadPDFOption"):
            for _ in range(self.downloads_per_save):
                self._download()
        elif css.endswith("-requestThisDocumentAnchor-download"):
            self.saving = int(css.rsplit("-row", 1)[1].split("-")[0])
            if self.popup_on_save:
                for f in list(self.listeners["popup"]):
                    f(object())
            for _ in range(self.downloads_per_save):
                self._download()
            self.saving = None
        else:
            raise AssertionError("pressed something else: " + css)

    # -- what the site layer reads ------------------------------------------
    def rows(self):
        if self.rows_override is not None:
            return self.rows_override
        if self.acct().get("years") is None or not self.expanded:
            return []
        out = []
        for n, it in enumerate(self.items()):
            iso = site.answer_date(it["documentDate"])
            save = "%s Opens menu to save document" % label_date(iso)
            if self.shape() == "anchor":
                save = "%s , opens document %s Saves document" % (label_date(iso), label_date(iso))
            out.append({"id": "accountsTable-STATEMENTS-row%d" % n, "shown": True,
                        "cells": [label_date(iso), it["documentTypeDesc"],
                                  "%d pages" % it["pageCount"], save]})
        return out

    def state(self):
        menu = [{"id": a["id"], "labels": [a["label"]], "shown": True,
                 "all": a["label"] + (", current selection" if i == self.selected else "")}
                for i, a in enumerate(self.accounts)]
        acc = [{"id": "button-accountsAccordian-NOTICES", "expanded": "false",
                "labels": ["Notices and letters"], "shown": True}]
        if self.acct().get("years") is not None:
            acc.insert(0, {"id": site.STATEMENTS_ACCORDION_ID,
                           "expanded": "true" if self.expanded else "false",
                           "labels": ["Statements"], "shown": True})
        options = []
        if self.picker_open:
            for i, y in enumerate(self.years):
                text = str(y)
                if y == self.year:
                    text += ", current selection"
                if i == len(self.years) - 1:
                    text += ", you've reached the end of the list"
                options.append({"id": "container-%d-filterstyledselect-0" % i,
                                "labels": [text], "shown": True})
        out = {"menu": menu, "accordions": acc,
                "picker": {"labels": ["View:"], "value": str(self.year), "shown": True},
                "options": options, "rows": self.rows(), "dialog": self.dialog,
                "password": self.password}
        if self.state_hook:
            self.state_hook(out)
        return out

    def labels_for(self, css):
        st = self.state()
        if css.startswith("#bottom-"):
            hits = [a for a in self.accounts if a["id"] == css[1:]]
            return [hits[0]["label"]] if hits else None
        if css == "#" + site.STATEMENTS_ACCORDION_ID:
            return ["Statements"] if any(a["id"] == css[1:] for a in st["accordions"]) else None
        if css == "#" + site.YEAR_PICKER_ID:
            return ["View:"]
        if css.startswith("#container-"):
            hits = [o for o in st["options"] if "#" + o["id"] == css]
            return hits[0]["labels"] if hits else None
        if "downloadDocumentDropdown" in css:
            n = int(css.rsplit("-row", 1)[1].split("-")[0])
            hits = [r for r in st["rows"] if r["id"] == "accountsTable-STATEMENTS-row%d" % n]
            if not hits or self.shape() not in ("menu", "both"):
                return None
            return ["%s Opens menu to save document" % hits[0]["cells"][0]]
        if css.endswith("-requestThisDocumentAnchor-download"):
            n = int(css.rsplit("-row", 1)[1].split("-")[0])
            hits = [r for r in st["rows"] if r["id"] == "accountsTable-STATEMENTS-row%d" % n]
            if not hits or self.shape() not in ("anchor", "both"):
                return None
            if self.anchor_labels is not None:
                return list(self.anchor_labels)
            return ["%s Saves document" % hits[0]["cells"][0]]
        if css.endswith("-downloadPDFOption"):
            n = int(css.rsplit("item-0-", 1)[1].split("-")[0])
            return ["Save as PDF"] if self.menu_open == n else None
        return None

    # -- the Playwright surface ----------------------------------------------
    def evaluate(self, js, arg=None):
        if js == site._DIALOG_OPEN_JS:
            return bool(self.dialog)
        if js == site._MENU_JS:
            n = int(arg["row"].rsplit("row", 1)[1])
            has_row = any(r["id"] == arg["row"] for r in self.rows())
            shown = self.menu_open == n
            menu = self.option_place in ("menu", "shared_two_expanded", "menu_not_expanded")
            return {"controls": 1 if has_row else 0, "option": shown,
                    "shownOptions": (1 if shown else 0) + (1 if self.option_place == "other_row" else 0),
                    "inRow": self.option_place in ("row", "other_row", "wrong_trigger", "row_collapsed"),
                    "menuId": "menu-shared" if menu else "",
                    "triggerId": ("header-accountsTable-STATEMENTS-row%d-cell3-downloadDocumentDropdown"
                                  % (n + 1 if self.option_place == "wrong_trigger" else n)),
                    "expandedSelf": shown and self.option_place not in ("menu_not_expanded", "row_collapsed"),
                    "expandedOthers": 1 if self.option_place == "shared_two_expanded" else 0}
        assert js == site._STATE_JS
        return self.state()

    def locator(self, css):
        return Locator(self, css)

    def on(self, event, f):
        self.listeners[event].append(f)

    def remove_listener(self, event, f):
        self.listeners[event].remove(f)

    def wait_for_timeout(self, ms):
        if self.on_wait:
            self.on_wait(self, ms)

    def title(self):
        return ""

    def is_closed(self):
        return self.closed

    @contextmanager
    def expect_response(self, pred, timeout=None):
        start = len(self.emitted)
        yield
        if not any(pred(r) for r in self.emitted[start:]):
            raise TimeoutError("no response")

    @contextmanager
    def expect_download(self, timeout=None):
        info, start = Info(), len(self.downloads)
        yield info
        if len(self.downloads) == start:
            raise TimeoutError("no download")
        info.value = self.downloads[start]


@pytest.fixture(autouse=True)
def fake_press(monkeypatch):
    """The core's press, replaced by the made-up center's. The press is the
    core's own to test; this only says which control was pressed."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert locator.css == css
        page.click(css)
    monkeypatch.setattr(site.pressing, "click", click)
    site.set_private_words([])
    yield


def chk_years():
    return {2026: [item("DOCQX0926", "2026-09-30"), item("DOCQX0826", "2026-08-31", 3)],
            2025: [item("DOCQX1225", "2025-12-31")],
            2024: []}


def center(**kw):
    return Center([dict(CHK, years=chk_years()),
                   dict(CARD, years={2026: [item("DOCQXC0926", "2026-09-28", 4)]}, shape="anchor"),
                   dict(DEBIT, years=None), dict(HOLDER, years=None)],
                  years=[2026, 2025, 2024], **kw)


def run():
    return site.Run(today=lambda: site._date(CUR, 10, 12))


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

BUSINESS_WORDS = [
    "Add employee card", "Send money with Zelle", "Wires & global transfers", "ACH Payment Services",
    "ACH Collections", "Deposit Checks", "Merchant Services", "Accept Card Payments", "QuickAccept",
    "Catalog", "Pending approvals", "Payment center", "Access & Security Manager",
    "Show or hide accounts", "Stay signed in", "Chase Offers", "Paperless", "Pay card",
    "Open an account", "Profile & settings", "Continue", "Sign out", "Pay bills", "Transfer money",
    "Collect & deposit center", "Save as accessible PDF", "Sep 30, 2026 Opens document menu",
    "Tax documents", "Notices and letters", "ATM and branch receipts", "",
]


@pytest.mark.parametrize("label", BUSINESS_WORDS)
def test_business_words_are_refused_by_every_guard(label):
    assert not site.is_safe_control(label)
    for guard in site.PRESS_GUARDS:
        assert not guard(label), (guard.__name__, label)


def test_the_seven_shapes_are_taken_each_by_its_own_predicate():
    assert site.is_account_entry("BUS COMPLETE CHK (...4321)")
    assert site.is_account_entry("BUSINESS CARD (...8765), current selection")
    assert site.is_statements_accordion("Statements")
    assert site.is_year_picker("View:") and site.is_year_picker("2026") and site.is_year_picker("View: 2026")
    assert site.is_year_option("2025") and site.is_year_option("2019, you've reached the end of the list")
    assert site.is_save_menu("Sep 30, 2026 Opens menu to save document", "Sep 30, 2026")
    assert site.is_save_as_pdf("Save as PDF")
    assert site.is_saves_document("Oct 13, 2026 Saves document", "Oct 13, 2026")
    for good in ("Statements", "Save as PDF", "2025", "Sep 30, 2026 Opens menu to save document",
                 "Oct 13, 2026 Saves document",
                 "Bank Statement", "View Bank Statement", "Download statement"):
        assert site.is_safe_control(good), good


def test_each_predicate_takes_only_its_own_shape():
    assert not site.is_save_menu("Sep 30, 2026 Opens menu to save document", "Aug 31, 2026")
    assert not site.is_year_option("2026, current selection")
    assert not site.is_account_entry("Statements")
    assert not site.is_account_entry("PAY CARD (...4321)")
    assert not site.is_account_entry("BUS COMPLETE CHK (...4321) Transfer")
    assert not site.is_statements_accordion("Statements and Tax documents")
    assert not site.is_save_as_pdf("Save as PDF document")
    assert site.is_save_as_pdf("Save as PDF 1 of 2 items"), "live, the menu names the item's place"
    assert not site.is_save_as_pdf("Save as PDF 1 of 2 items Sign out")
    assert not site.is_save_as_pdf("Print 2 of 2 items")
    assert site.is_account_entry("INK BUSINESS REWARDS CARD (...4321)"), "a product word is no verb"


@pytest.mark.parametrize("bad", ["Sign out", "Stay signed in", "Pay card", "Wires & global transfers"])
@pytest.mark.parametrize("good", ["Save as PDF", "Statements", "2025",
                                  "Sep 30, 2026 Opens menu to save document"])
def test_mixed_labels_are_refused(good, bad):
    for joined in ("%s | %s" % (good, bad), "%s | %s" % (bad, good), "%s %s" % (good, bad)):
        assert not site.is_safe_control(joined)
        assert not any(g(joined) for g in site.PRESS_GUARDS)


def test_a_control_with_one_refused_label_is_not_pressed():
    page = center()
    page.labels_for = lambda css: ["Save as PDF", "Sign out"]
    with pytest.raises(site.ListStopped):
        site._press(page, page.locator("#item-0-0-downloadPDFOption"), css="#item-0-0-downloadPDFOption",
                    what="x", guard=site.is_save_as_pdf, step="save the statement", run=run())
    assert page.presses == []


def test_a_press_with_a_guard_not_of_the_six_is_refused():
    page = center()
    with pytest.raises(site.ListStopped):
        site._press(page, page.locator("#" + site.YEAR_PICKER_ID), css="#" + site.YEAR_PICKER_ID,
                    what="x", guard=site.is_safe_control, step="open the year picker", run=run())
    assert page.presses == []


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def test_url_guards():
    assert site.is_safe_url(BASE + "/web/auth/dashboard")
    for bad in ("http://secure.chase.com/x", "https://www.chase.com/", "https://chase.com/",
                "https://analytics.chase.com/x", "https://secure.chase.com.evil.test/",
                "https://reco.chase.com/x", "https://sites.chase.com/x", ""):
        assert not site.is_safe_url(bad), bad
    assert site.is_docref_url(DOCREF)
    assert not site.is_docref_url(BASE + "/svc/rr/documents/secure/tax/v2/docref/list")
    assert not site.is_docref_url(BASE + "/svc/rr/documents/secure/idal/v4/docref/list")
    assert site.is_download_url(PDF_URL)
    assert not site.is_download_url(BASE + "/svc/rr/documents/secure/idal/v2/dockey/list")
    assert not site.is_download_url("https://www.chase.com/svc/rr/documents/secure/idal/v5/pdfdoc/star/list")
    assert site.is_documents_url(site.DOCUMENTS_URL)
    assert site.is_documents_url(site.DOCUMENTS_URL + ";accountId=1;mode=accounts")
    assert not site.is_documents_url(DASHBOARD)


# ---------------------------------------------------------------------------
# The account menu
# ---------------------------------------------------------------------------

def test_label_classification():
    assert site.account_class("BUS COMPLETE CHK (...4321)") == "Business Checking"
    assert site.account_class("PREMIER CHECKING (...4321), current selection") == "Business Checking"
    assert site.account_class("BUSINESS CARD (...8765)") == "Business Card"
    assert site.account_class("BUS TOTAL DEBIT (...5555)") == "Business Debit"
    assert site.account_class("ZEPHYRINA QUILLFEATHER (...8765)") == ""
    assert site.account_class("ZEPHYRINA CARDONA (...8765)") == "", "a surname is no product noun"
    assert site.account_class("BUS DEBIT CARD (...5555)") == "", "two nouns are not read"


def test_cardholder_entries_are_skipped_and_shared_tails_kept_apart():
    """The cardholder, an initial and a surname under a last four of its
    own as the live menu draws it, is passed over beside a Business Card."""
    st = center().state()
    accts = site.accounts_of(st)
    assert [a.klass for a in accts] == ["Business Checking", "Business Card", "Business Debit"]
    assert [a.tail for a in accts] == ["4321", "8765", "5555"]
    assert len({a.ref for a in accts}) == 3


@pytest.mark.parametrize("label", ["INK BUSINESS CASH (...9876)", "ZEPHYRINA QUILLFEATHER (...9876)",
                                   "BUS DEBIT CARD (...1357)", "Z. QUILLFEATHER",
                                   "Z. QUILLFEATHER (...1357), INK", "ZQ. QUILLFEATHER (...1357)",
                                   "J. A- (...1357)", "J. O' (...1357)", "J. -SMITH (...1357)",
                                   "J. SMITH- JONES (...1357)"])
def test_an_entry_that_names_no_class_and_is_no_cardholder_stops_the_list(label):
    """A card whose name carries no product word, a name not in the
    cardholder's shape, one naming two classes, or one with no last four
    is not passed over, since the list would then be called whole
    without it."""
    page = center()
    page.accounts.append({"id": "bottom-7700123123", "label": label, "years": None})
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert page.presses == []


@pytest.mark.parametrize("label", ["Z. QUILLFEATHER (...2468)", "J. O'NEIL-SMITH (...1357)",
                                   "J. VAN DER BERG (...1357) , current selection"])
def test_a_cardholder_beside_a_business_card_is_passed_over(label):
    st = {"menu": [{"id": CARD["id"], "labels": [CARD["label"]], "shown": True},
                   {"id": "bottom-7700123123", "labels": [label], "shown": True}]}
    assert [a.klass for a in site.accounts_of(st)] == ["Business Card"]


def test_a_cardholder_with_no_business_card_in_the_menu_stops_the_list():
    st = {"menu": [{"id": CHK["id"], "labels": [CHK["label"]], "shown": True},
                   {"id": HOLDER["id"], "labels": [HOLDER["label"]], "shown": True}]}
    with pytest.raises(site.ListStopped):
        site.accounts_of(st)


def test_the_current_selection_may_have_a_space_before_its_comma():
    label = "BUS COMPLETE CHK (...4321) , current selection"
    assert site.is_account_entry(label) and site.account_class(label) == "Business Checking"


def test_a_menu_that_reads_differently_twice_over_stops_the_list():
    """The menu is read again once the page settles, and an account drawn
    late is never left out of a list called whole."""
    page = center()
    reads = []

    def late_entry(st):
        reads.append(1)
        if len(reads) >= 2:
            st["menu"].append({"id": "bottom-7700123123", "labels": ["BUS SAVINGS CHK (...1212)"],
                               "all": "BUS SAVINGS CHK (...1212)", "shown": True})
    page.state_hook = late_entry
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "differently" in str(stop.value)
    assert page.presses == []


def test_a_menu_that_changes_between_accounts_stops_the_list():
    page = center()

    def drop_debit(p):
        if p.presses:
            p.accounts = [a for a in p.accounts if a["id"] != DEBIT["id"]]
    page.on_goto = drop_debit
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "changed during the listing" in str(stop.value)


def test_duplicate_labels_are_two_accounts_and_one_id_twice_stops():
    twin = {"menu": [{"id": "bottom-1001", "labels": [CHK["label"]], "shown": True},
                     {"id": "bottom-1002", "labels": ["BUS COMPLETE CHK (...1357)"], "shown": True}]}
    assert [a.ref for a in site.accounts_of(twin)] == ["bottom-1001", "bottom-1002"]
    # One class and one last four twice: nothing across sign-ins tells them apart.
    with pytest.raises(site.ListStopped):
        site.accounts_of({"menu": [{"id": "bottom-1001", "labels": [CHK["label"]], "shown": True},
                                   {"id": "bottom-1002", "labels": [CHK["label"]], "shown": True}]})
    with pytest.raises(site.ListStopped):
        site.accounts_of({"menu": [{"id": "bottom-1001", "labels": [CHK["label"]], "shown": True},
                                   {"id": "bottom-1001", "labels": [CARD["label"]], "shown": True}]})
    with pytest.raises(site.ListStopped):
        site.accounts_of({"menu": [{"id": "bottom-10 01", "labels": [CHK["label"]], "shown": True}]})


def test_every_menu_label_and_id_is_private_once_read():
    site.guard_menu(center().state())
    words = " ".join(site.private_words())
    for secret in ("QUILLFEATHER", "2468", "7700112233", "bottom-7700990011", "4321"):
        assert secret in words
    assert "4321" not in site.redact("BUS COMPLETE CHK (...4321)")


# ---------------------------------------------------------------------------
# The page's own answers
# ---------------------------------------------------------------------------

def test_the_response_predicate():
    good = Response("7700112233", "CURRENT_YEAR", {})
    assert site.answers(good, "7700112233", "CURRENT_YEAR")
    assert not site.answers(good, "7700445566", "CURRENT_YEAR"), "another account"
    assert not site.answers(good, "770011", "CURRENT_YEAR"), "a prefix of the account"
    assert not site.answers(good, "7700112233", "CURRENT_YEAR_MINUS_1"), "another year"
    other = Response("7700112233", "CURRENT_YEAR", {}, url=BASE + "/svc/rr/documents/secure/idal/v4/docref/list")
    assert not site.answers(other, "7700112233", "CURRENT_YEAR"), "another path"
    got = Response("7700112233", "CURRENT_YEAR", {}, method="GET")
    assert not site.answers(got, "7700112233", "CURRENT_YEAR"), "not a POST"
    twice = Response("7700112233", "CURRENT_YEAR", {})
    twice.request.post_data += "&accountFilter=7700445566"
    assert not site.answers(twice, "7700112233", "CURRENT_YEAR"), "two accounts named"
    assert site.filter_for(2026, 2026) == "CURRENT_YEAR"
    assert site.filter_for(2026, 2019) == "CURRENT_YEAR_MINUS_7"


def test_two_answers_for_one_transition_stop_the_list():
    page = center()
    page.duplicate_answers = True
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "2 list answers" in str(stop.value)


def test_an_answer_for_another_account_is_not_taken():
    page = center()
    page.answer_override[("7700445566", "CURRENT_YEAR")] = \
        lambda: Response("7700112233", "CURRENT_YEAR", {"code": "SUCCESS",
                                                        "idaldocRefs": [item("DOCQXZ", "2026-01-31")]})
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "0 list answers" in str(stop.value)


def test_the_empty_year_baseline():
    r = run()
    empty = Response("1", "CURRENT_YEAR_MINUS_7", {"code": "SUCCESS"})
    # Held, not stopped, before any list has shown what success looks like.
    assert site.read_answer(empty, r, 2019) == []
    assert r.unproven()
    full = Response("1", "CURRENT_YEAR", {"code": "SUCCESS", "idaldocRefs": [item("DOCQX1", "2026-01-31")]})
    assert [i.date for i in site.read_answer(full, r, 2026)] == ["2026-01-31"]
    assert not r.unproven()
    assert site.read_answer(empty, r, 2019) == []
    with pytest.raises(site.ListStopped):
        site.read_answer(Response("1", "X", {"code": "ERROR"}), r, 2019)
    with pytest.raises(site.ListStopped):
        site.read_answer(Response("1", "X", {"message": "no code"}), r, 2019)
    with pytest.raises(site.ListStopped):
        site.read_answer(Response("1", "X", None, raw="<html>not json"), r, 2019)
    with pytest.raises(site.ListStopped):
        site.read_answer(Response("1", "X", {"code": "SUCCESS"}, status=500), r, 2019)
    with pytest.raises(site.ListStopped):
        site.read_answer(Response("1", "X", {"code": "SUCCESS", "idaldocRefs": []}), r, 2019)
    with pytest.raises(site.SessionExpired):
        site.read_answer(Response("1", "X", {"code": "SUCCESS"}, status=401), r, 2019)


def test_an_answer_is_validated_whole():
    r = run()
    for bad in ([item("DOCQX1", "2025-12-31")],            # outside the year asked for
                [item("DOCQX1", "2026-02-30")],            # no such day
                [item("DOCQX1", "2026-01-31", pages=0)],
                [item("DOCQX1", "2026-01-31", kind="Notice")],
                [item("DOCQX1", "2026-01-31"), item("DOCQX1", "2026-02-28")],
                [dict(item("DOCQX1", "2026-01-31"), documentId="")]):
        with pytest.raises(site.ListStopped):
            site.read_answer(Response("1", "CURRENT_YEAR", {"code": "SUCCESS", "idaldocRefs": bad}), r, 2026)


def test_an_empty_current_year_is_held_until_a_list_shows_success():
    """In January every account's current year is empty, and it is the first
    list read. It is held until the next year's statements show the code."""
    page = Center([dict(CHK, years={2026: [], 2025: [item("DOCQX1225", "2025-12-31")]}),
                   dict(CARD, years={2026: [], 2025: []})],
                  years=[2026, 2025])
    docs_ = site.collect_download_docs(page, run())
    assert [(d.account, d.date_text) for d in docs_] == [("Business Checking", "2025-12-31")]


def test_a_held_empty_year_with_another_code_stops_the_list():
    r = run()
    assert site.read_answer(Response("1", "CURRENT_YEAR", {"code": "PARTIAL"}), r, 2026) == []
    full = Response("1", "CURRENT_YEAR_MINUS_1",
                    {"code": "SUCCESS", "idaldocRefs": [item("DOCQX1", "2025-01-31")]})
    with pytest.raises(site.ListStopped) as stop:
        site.read_answer(full, r, 2025)
    assert "another code" in str(stop.value)


def test_a_listing_where_every_year_is_empty_stops():
    page = Center([dict(CHK, years={2026: [], 2025: []})], years=[2026, 2025])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "every year read was empty" in str(stop.value)


# ---------------------------------------------------------------------------
# The rows, checked against the answer
# ---------------------------------------------------------------------------

def test_the_multiset_cross_check():
    items = [site.Item("A", "2026-09-30", "Statement", 2), site.Item("B", "2026-09-30", "Statement", 2)]
    row = {"cells": ["Sep 30, 2026", "Statement", "2 pages"]}
    assert site.rows_match(items, [row, row])
    assert not site.rows_match(items, [row])
    assert not site.rows_match(items[:1], [row, row])
    assert not site.rows_match(items[:1], [{"cells": ["Sep 30, 2026", "Statement", "3 pages"]}])
    assert not site.rows_match(items[:1], [{"cells": ["Sep 31, 2026", "Statement", "2 pages"]}])
    assert not site.rows_match(items[:1], [{"cells": ["Sept 30 2026", "Statement", "2 pages"]}])
    assert site.rows_match([], [])
    assert site.row_shape(["Feb 29, 2024", "Statement", "1 page"]) == ("2024-02-29", "Statement", 1)
    assert site.row_shape(["Feb 29, 2025", "Statement", "1 page"]) is None


def test_rows_that_differ_from_the_answer_stop_the_list():
    page = center()
    page.rows_override = [{"id": "accountsTable-STATEMENTS-row0", "shown": True,
                           "cells": ["Sep 30, 2026", "Statement", "2 pages"]}]
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "rows" in str(stop.value)


# ---------------------------------------------------------------------------
# Listing, whole
# ---------------------------------------------------------------------------

def test_discovery_lists_every_business_account_and_year():
    page = center()
    docs_ = site.collect_download_docs(page, run())
    got = sorted((d.account, d.date_text, d.page_count) for d in docs_)
    assert got == [("Business Card", "2026-09-28", 4),
                   ("Business Checking", "2025-12-31", 2),
                   ("Business Checking", "2026-08-31", 3),
                   ("Business Checking", "2026-09-30", 2)]
    # Chase mints a statement's documentId anew each session, so none is kept.
    assert all(d.document_id == "" for d in docs_)
    assert {d.title for d in docs_} == {"Business Checking Statement", "Business Card Statement"}
    assert all(d.href == "" for d in docs_)
    # The current year is never chosen again, the cardholder's entry is
    # chosen once to show it has no Statements, and nothing but the six
    # controls is ever pressed.
    assert page.presses.count("#" + HOLDER["id"]) == 1
    assert page.presses[-1] == "#" + HOLDER["id"], "nothing is pressed past it"
    assert not any(p == "#container-0-filterstyledselect-0" for p in page.presses)
    assert {p.split("-")[0] for p in page.presses} <= {"#bottom", "#header", "#container"}


def test_a_cardholder_the_center_opens_on_is_passed_over_unpressed():
    """The owner's live case, with the document center opening on the
    cardholder's entry, which shows only notices. Nothing is pressed to
    choose it, and the list is whole without it."""
    page = center(selected=3)
    assert page.accounts[3]["id"] == HOLDER["id"]
    docs_ = site.collect_download_docs(page, run())
    assert len(docs_) == 4
    assert "#" + HOLDER["id"] not in page.presses


@pytest.mark.parametrize("label", ["Q. ZEPHYRWOOD (...1357)", "R. O'QUILLAN-VARGO TRUST (...1357)"])
@pytest.mark.parametrize("years", [{2026: [item("DOCQXH0926", "2026-09-29")]}, {}],
                         ids=["a statement", "none yet"])
def test_an_entry_that_reads_as_a_cardholder_and_shows_statements_stops_the_list(label, years):
    """A second card, or an account nicknamed like a person, reads as a
    cardholder. Chosen with the account press, it shows Statements, so
    the list stops rather than be called whole without it, and what was
    listed before is kept."""
    page = center()
    page.accounts.append({"id": "bottom-7700123123", "label": label, "years": years})
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, run())
    assert "Statements" in str(stop.value)
    assert page.presses.count("#bottom-7700123123") == 1
    assert len(stop.value.docs) == 4


def test_a_cardholder_entry_the_account_press_would_refuse_stops_the_list():
    """A cardholder's entry is chosen to show it has no Statements, so one
    whose label the account press refuses stops the list, with nothing
    pressed."""
    page = center()
    page.accounts.append({"id": "bottom-7700123123", "label": "K. CLOSE (...1357)", "years": None})
    assert site.CARDHOLDER_RE.fullmatch("K. CLOSE (...1357)")
    assert not site.is_account_entry("K. CLOSE (...1357)")
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_closed_accordion_is_opened_and_its_answer_taken():
    page = center()
    original = page.reset

    def closed():
        original()
        page.expanded = False
    page.reset = closed
    page.reset()
    docs_ = site.collect_download_docs(page, run())
    assert len(docs_) == 4
    assert page.presses.count("#" + site.STATEMENTS_ACCORDION_ID) >= 2


def test_a_document_center_that_never_draws_stops():
    page = center()
    page.on_goto = lambda p: setattr(p, "accounts", [])
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())


def test_a_picker_year_that_is_not_this_year_stops():
    r = site.Run(today=lambda: site._date(2027, 1, 2))
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(center(), r)


# ---------------------------------------------------------------------------
# Signed out
# ---------------------------------------------------------------------------

def test_the_timeout_dialog_is_session_expired_and_never_pressed():
    page = center()
    page.dialog = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_the_sign_in_page_is_session_expired():
    page = center()

    def to_logon(p):
        p.url = BASE + "/web/auth/#/logon/logon/chaseOnline"
    page.goto = lambda url, **kw: to_logon(page)
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


def test_a_401_on_the_list_call_is_session_expired():
    page = center()
    page.answer_override[("7700445566", "CURRENT_YEAR")] = \
        lambda: Response("7700445566", "CURRENT_YEAR", {}, status=401)
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


def test_a_dialog_that_opens_during_the_listing_is_session_expired():
    page = center()
    original = page.click

    def click(css):
        original(css)
        if css.startswith("#container-"):
            page.dialog = True
    page.click = click
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

CHK_DIGEST = site.account_digest("Business Checking", "4321")


def take(page, tmp_path, doc_id="DOCQX1225", iso="2025-12-31", pages=2, digest=CHK_DIGEST, trace=None,
         r=None, name="out.pdf"):
    out = tmp_path / name
    dl = tmp_path / "dl"
    dl.mkdir(exist_ok=True)
    got = site.download_statement(page, r or run(), dl, out, account_digest=digest, document_id=doc_id,
                                  iso_date=iso, doc_type="Statement", page_count=pages,
                                  trace=trace if trace is not None else [])
    return got, out


def test_a_statement_is_taken_through_its_own_row(tmp_path):
    page = center()
    got, out = take(page, tmp_path)
    assert got and out.read_bytes()[:5] == b"%PDF-"
    assert page.presses[-2:] == ['#accountsTable-STATEMENTS-row0 a#header-accountsTable-STATEMENTS-row0-cell3-downloadDocumentDropdown',
                                 "#accountsTable-STATEMENTS-row0 #item-0-0-downloadPDFOption"]
    assert "#container-1-filterstyledselect-0" in page.presses


def test_binding_refuses_duplicates_and_missing_rows():
    items = [site.Item("A", "2026-09-30", "Statement", 2), site.Item("B", "2026-09-30", "Statement", 2)]
    row = {"id": "accountsTable-STATEMENTS-row0", "shown": True, "cells": ["Sep 30, 2026", "Statement", "2 pages"]}
    row1 = dict(row, id="accountsTable-STATEMENTS-row1")
    assert site.bind(items, [row, row1], "A", "2026-09-30", "Statement", 2) == -1, "two answered"
    assert site.bind(items[:1], [row, row1], "A", "2026-09-30", "Statement", 2) == -1, "two rows"
    assert site.bind(items[:1], [], "A", "2026-09-30", "Statement", 2) == -1, "no row"
    assert site.bind(items[:1], [dict(row, shown=False)], "A", "2026-09-30", "Statement", 2) == -1
    # The id is not compared: Chase mints it anew each session, so a
    # record's id from an earlier run names nothing now.
    assert site.bind(items[:1], [row], "Z", "2026-09-30", "Statement", 2) == 0, "another session's id"
    assert site.bind(items[:1], [row1], "A", "2026-09-30", "Statement", 2) == 1


def test_no_row_press_without_one_bound_row(tmp_path):
    years = chk_years()
    years[2026] = [item("DOCQX0926", "2026-09-30"), item("DOCQX0927", "2026-09-30")]
    page = Center([dict(CHK, years=years)], years=[2026, 2025])
    got, out = take(page, tmp_path, doc_id="DOCQX0926", iso="2026-09-30")
    assert not got and not out.exists()
    assert not any("download" in p for p in page.presses)


def test_an_account_gone_from_the_menu_presses_nothing(tmp_path):
    page = center()
    got, _out = take(page, tmp_path, digest=site.account_digest("Business Checking", "1357"))
    assert not got and page.presses == []


@pytest.mark.parametrize("change, reason", [
    ({"downloads_per_save": 2}, "more than one download came"),
    ({"download_url": "https://www.chase.com/x.pdf"}, "the download came from elsewhere"),
    ({"download_body": b"<html>signed out</html>"}, "the download was not a pdf"),
    ({"downloads_per_save": 0}, "no download came"),
])
def test_a_download_that_is_not_one_pdf_from_chase_stops_the_run(tmp_path, change, reason):
    page = center()
    for k, v in change.items():
        setattr(page, k, v)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == reason
    assert not (tmp_path / "out.pdf").exists()


def test_a_download_pending_before_the_press_stops_the_run(tmp_path):
    page = center()
    (tmp_path / "dl").mkdir()
    (tmp_path / "dl" / "x.pdf.crdownload").write_bytes(b"")
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == "a download was pending"
    assert not any("download" in p for p in page.presses)


# ---------------------------------------------------------------------------
# The run's deadline
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_the_deadline_counts_from_the_first_press():
    clock = Clock()
    r = site.Run(clock=clock, today=lambda: site._date(CUR, 10, 12))
    assert not r.past_deadline()
    clock.t += 10 * 60
    assert not r.past_deadline(), "nothing pressed yet"
    r.pressed()
    clock.t += site.DEADLINE_S - 1
    r.pressed()
    assert not r.past_deadline()
    clock.t += 1
    assert r.past_deadline()


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------

def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "min_pdf_bytes": 100, "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    app = docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))
    app.run = run()
    app._dl_dir = Path(tmp) / "out" / ".chasebusiness-downloads"
    app._dl_dir.mkdir(parents=True, exist_ok=True)
    return app


def attach(app, page):
    page.url = site.DOCUMENTS_URL
    app.page = lambda: page
    app._delay = lambda *a, **k: None


def test_records_carry_the_class_and_never_a_query(tmp_path):
    app = make_app(tmp_path, "--discover")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    recs = list(app.discovery.data.values())
    assert len(recs) == 4
    for rec in recs:
        assert rec["account"] in ("Business Checking", "Business Card")
        assert rec["summary"] == "Bank Statement " + rec["account"]
        assert rec["href"] == "" and "?" not in rec["source_url"]
    told = docs.told_apart_by(recs[0])
    assert len(told) == 6 and all(rec["account_ref"] == "" for rec in recs)
    assert len({docs.told_apart_by(rec) for rec in recs}) == 2, "two accounts, two digests"
    assert all(rec["document_id"] == "" for rec in recs)


def test_an_expired_session_stops_the_run_and_records_nothing(tmp_path):
    app = make_app(tmp_path, "--all")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    page = center()
    page.dialog = True
    attach(app, page)
    app.check_session = lambda p: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.process(app._select())
    assert "signed out" in said.getvalue()
    assert app.progress.data == {}
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_an_expired_session_during_discovery_stops_the_run(tmp_path):
    app = make_app(tmp_path, "--discover")
    page = center()
    page.dialog = True
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert app.discovery.data == {}
    assert "signed out" in said.getvalue() and "Press Enter" not in said.getvalue()
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_the_deadline_stops_the_run_before_the_next_document(tmp_path):
    app = make_app(tmp_path, "--all")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    clock = Clock()
    app.run = site.Run(clock=clock, today=lambda: site._date(CUR, 10, 12))
    app.run.pressed()
    clock.t += site.DEADLINE_S
    taken = []
    original = site.download_statement
    site.download_statement = lambda *a, **k: taken.append(1)
    try:
        with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
            app.process(app._select())
    finally:
        site.download_statement = original
    assert taken == [] and app.progress.data == {}
    assert "minutes" in said.getvalue()


def test_pilot_gate():
    from paperpull_core.models import State

    class D:
        def __init__(self, k):
            self.key = k
    done = {"a": {"state": State.COMPLETED.value}}
    assert not docs.pilot_failed(done, [D("a")])
    assert docs.pilot_failed({"a": {"state": State.FAILED.value}}, [D("a")])
    assert docs.pilot_failed({}, [D("a")])
    assert docs.pilot_failed(done, [])


# ---------------------------------------------------------------------------
# Privacy, on the way that works and the ways that do not
# ---------------------------------------------------------------------------

@contextmanager
def everything_said():
    seen = io.StringIO()
    handler = logging.StreamHandler(seen)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.DEBUG)
    try:
        with redirect_stdout(seen):
            yield seen
    finally:
        root.removeHandler(handler)
        root.setLevel(old)


def written(app) -> str:
    """Every file the run wrote but its two record stores, and every name."""
    out = []
    for p in app.paths.root.rglob("*"):
        out.append(p.name)
        if p.is_file() and p.suffix.lower() in (".log", ".json", ".csv", ".txt") \
                and p.name not in ("discovery.json", "progress.json") and "backup" not in str(p).lower():
            out.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(out)


def assert_private(text):
    for secret in SECRETS:
        assert secret.lower() not in text.lower(), secret


def test_nothing_private_leaves_on_a_run_that_works(tmp_path):
    app = make_app(tmp_path, "--all")
    with everything_said() as seen:
        attach(app, center())
        app.cmd_discover()
        app.check_session = lambda p: None
        app.process(app._select())
    assert app.stats["statements"] == 4, seen.getvalue()
    names = [p.name for p in app.paths.root.rglob("*.pdf")]
    assert len(names) == 4 and any("Business Checking" in n for n in names)
    assert_private(seen.getvalue() + written(app))


def test_nothing_private_leaves_on_runs_that_stop(tmp_path):
    app = make_app(tmp_path, "--all")
    traces = []
    with everything_said() as seen:
        attach(app, center())
        app.cmd_discover()
        app.check_session = lambda p: None
        # A list that stops on the way to the statement.
        bad = center()
        bad.rows_override = []
        attach(app, bad)
        app.process(app._select(limit=1))
        # A download that is not a PDF stops the run.
        worse = center()
        worse.download_body = b"<html>BUS COMPLETE CHK (...4321)</html>"
        attach(app, worse)
        try:
            app.process(app._select(limit=2))
        except site.pressing.Stop as stop:
            traces.append(" ".join(stop.lines) + str(stop.facts))
            try:
                site.pressing.stop_run(app, stop)
            except SystemExit:
                pass
        # A discovery that stops partway.
        third = center()
        third.answer_override[("7700445566", "CURRENT_YEAR")] = \
            lambda: Response("7700445566", "CURRENT_YEAR", None, raw="{not json")
        attach(app, third)
        try:
            app.cmd_discover()
        except SystemExit:
            pass
        trace = []
        take(center(), tmp_path, doc_id="DOCQXNOPE", trace=trace)
        traces.append(json.dumps(trace))
    assert app.stats["manual_review"] >= 1
    assert_private(seen.getvalue() + written(app) + " ".join(traces))


# ---------------------------------------------------------------------------
# What the site layer presses, read from its source
# ---------------------------------------------------------------------------

SITE = ast.parse((HERE / "chasebusiness_site.py").read_text(encoding="utf-8"))
SEVEN = {"is_account_entry", "is_statements_accordion", "is_year_picker", "is_year_option",
         "is_save_menu", "is_save_as_pdf", "is_saves_document"}


def test_the_site_layer_presses_nothing_itself():
    called = {n.func.attr for n in ast.walk(SITE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for verb in ("click", "dblclick", "tap", "fill", "type", "press", "select_option", "check",
                 "uncheck", "set_input_files", "dispatch_event", "press_sequentially", "hover",
                 "focus", "set_checked", "drag_to", "press_once"):
        if verb == "click":
            continue
        assert verb not in called, verb
    attrs = {n.attr for n in ast.walk(SITE) if isinstance(n, ast.Attribute)}
    assert not attrs & {"mouse", "keyboard", "touchscreen"}
    assert not [k for k in ast.walk(SITE) if isinstance(k, ast.keyword) and k.arg == "force"]
    assert "dismiss_timeout" not in {f.name for f in ast.walk(SITE) if isinstance(f, ast.FunctionDef)}


def test_the_one_press_is_the_cores_inside_press_and_every_press_names_one_of_seven():
    clicks = []
    for fn in [n for n in ast.walk(SITE) if isinstance(n, ast.FunctionDef)]:
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "click":
                clicks.append((fn.name, ast.unparse(c.func.value)))
    assert clicks == [("_press", "pressing"), ("_press_row", "pressing")]
    guards = {"_press": [], "_press_row": []}
    for c in ast.walk(SITE):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in guards:
            g = [k.value for k in c.keywords if k.arg == "guard"]
            assert len(g) == 1 and isinstance(g[0], ast.Name), ast.unparse(c)
            guards[c.func.id].append(g[0].id)
    # The four that reach a list stop the run when turned off, and the three
    # a statement's own row carries leave that statement.
    assert sorted(guards["_press"]) == sorted(SEVEN - {"is_save_menu", "is_save_as_pdf",
                                                       "is_saves_document"})
    assert sorted(guards["_press_row"]) == ["is_save_as_pdf", "is_save_menu", "is_saves_document"]
    assert {g.__name__ for g in site.PRESS_GUARDS} == SEVEN
    # The JavaScript handed to the page reads; it presses nothing.
    for js in (site._STATE_JS, site._LABELS_JS):
        assert ".click" not in js and "dispatchEvent" not in js and ".submit" not in js


# ---------------------------------------------------------------------------
# After review: the menu's own option, late downloads, hidden nodes, waits
# ---------------------------------------------------------------------------

def test_the_option_inside_the_menu_the_row_owns_is_taken(tmp_path):
    page = center()
    page.option_place = "menu"
    got, _out = take(page, tmp_path)
    assert got and page.presses[-1] == '[id="menu-shared"] #item-0-0-downloadPDFOption'


@pytest.mark.parametrize("place", ["detached", "other_row", "shared_two_expanded",
                                   "menu_not_expanded", "wrong_trigger", "row_collapsed"])
def test_a_save_as_pdf_not_the_bound_menus_own_is_never_pressed(tmp_path, place):
    page = center()
    page.option_place = place
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == "the save menu showed no save as pdf of its own"
    assert not any(p.endswith("downloadPDFOption") for p in page.presses)
    assert page.downloads == []


def test_a_second_download_that_comes_late_stops_the_next_statement(tmp_path):
    page = center()
    page.late_download = True
    r = run()
    got, _out = take(page, tmp_path, r=r)
    assert got and r.untied() == 0
    before = list(page.presses)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, doc_id="DOCQX0926", iso="2026-09-30", r=r, name="next.pdf")
    assert stop.value.reason == "a download came that no press took"
    assert not any("download" in p for p in page.presses[len(before):])
    assert not (tmp_path / "next.pdf").exists()


def test_a_failed_capture_says_no_file_name(tmp_path, monkeypatch, caplog):
    """The core's capture names the exception's kind only: a filesystem
    error carries the browser's suggested name, with the account's tail."""
    import paperpull_core.capture as capture

    def no_save(self, path):
        raise OSError("cannot write %s" % self.suggested_filename)

    def no_move(src, dst):
        raise OSError("cannot move %s" % src)
    monkeypatch.setattr(Download, "save_as", no_save)
    monkeypatch.setattr(capture.shutil, "move", no_move)
    page = center()
    page.folder_copy = tmp_path / "dl"
    (tmp_path / "dl").mkdir()
    caplog.set_level(logging.DEBUG)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == "the download was not a pdf"
    assert "OSError" in caplog.text
    assert "4321" not in caplog.text and "STATEMENTS-4321" not in caplog.text


def _hide(kind):
    def hook(st):
        if kind == "hidden statements":
            for a in st["accordions"]:
                if a["id"] == site.STATEMENTS_ACCORDION_ID:
                    a["shown"] = False
        elif kind == "two statements":
            st["accordions"].append(dict(st["accordions"][0]))
        elif kind == "hidden entry":
            for e in st["menu"]:
                e["shown"] = False
        elif kind == "two entries":
            st["menu"].append(dict(st["menu"][0]))
    return hook


@pytest.mark.parametrize("kind", ["hidden statements", "two statements", "hidden entry", "two entries"])
def test_hidden_or_doubled_nodes_never_stand_for_the_page(kind):
    page = center()
    page.state_hook = _hide(kind)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_hidden_entry_is_never_the_current_account():
    page = center()
    st = page.state()
    st["menu"][0]["shown"] = False
    assert site._entry(st, CHK["id"]) is None
    with pytest.raises(site.ListStopped):
        site.accounts_of(st)


def test_the_timeout_dialog_during_the_download_settle_is_session_expired(tmp_path):
    page = center()

    def dialog_on_settle(p, ms):
        if ms == site.SECOND_DOWNLOAD_WAIT_MS and p.downloads:
            p.dialog = True
    page.on_wait = dialog_on_settle
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path)
    assert not (tmp_path / "out.pdf").exists()


def test_the_timeout_dialog_during_the_load_settle_is_session_expired():
    page = center()

    def dialog_on_settle(p, ms):
        if ms == site.SETTLE_MS:
            p.dialog = True
    page.on_wait = dialog_on_settle
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_record_key_never_holds_the_statement_id(tmp_path):
    app = make_app(tmp_path, "--discover")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    for key, rec in app.discovery.data.items():
        assert rec["document_id"] == "" and rec["account_ref"] == ""
        assert "DOCQX" not in key and "DOCQX" not in json.dumps(rec)
        assert key.startswith("id:" + rec["account"] + ":")


def _reminted(years):
    """The same statements with the documentIds another session mints."""
    return {y: [dict(i, documentId="NEW" + i["documentId"]) for i in items]
            for y, items in years.items()} if years else years


def test_a_second_discover_with_new_statement_ids_keeps_one_record_each(tmp_path):
    """Live, Chase gave every statement a new documentId on the next
    session, and keying records by it doubled every one. The same
    statements under new ids are the same records."""
    app = make_app(tmp_path, "--discover")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    first = dict(app.discovery.data)
    assert len(first) == 4
    again = Center([dict(CHK, years=_reminted(chk_years())),
                    dict(CARD, years=_reminted({2026: [item("DOCQXC0926", "2026-09-28", 4)]})),
                    dict(DEBIT, years=None), dict(HOLDER, years=None)],
                   years=[2026, 2025, 2024])
    attach(app, again)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    assert sorted(app.discovery.data) == sorted(first)


def test_a_new_sign_in_with_new_account_ids_keeps_one_record_each_and_finds_its_account(tmp_path):
    """Live, every account in the menu carried a new id after a fresh
    sign-in. Records are known by class and last four, so the same
    statements under new account ids are the same records, and a record
    from the first sign-in is taken from the second."""
    app = make_app(tmp_path, "--discover")
    attach(app, center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    first = dict(app.discovery.data)

    def renamed(a):
        return dict(a, id=a["id"].replace("bottom-7700", "bottom-8800"))
    again = Center([dict(renamed(CHK), years=_reminted(chk_years())),
                    dict(renamed(CARD), years=_reminted({2026: [item("DOCQXC0926", "2026-09-28", 4)]})),
                    dict(renamed(DEBIT), years=None), dict(renamed(HOLDER), years=None)],
                   years=[2026, 2025, 2024])
    attach(app, again)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    assert sorted(app.discovery.data) == sorted(first)
    rec = next(v for v in first.values() if v["date"] == "2025-12-31")
    got, out = take(again, tmp_path, digest=rec["account_digest"])
    assert got and out.exists()


def test_the_second_of_two_checking_accounts_is_found_after_its_id_changes(tmp_path):
    """Two Checking accounts, told apart only by their last fours, each
    under a new id after a sign-in: a record of the second one reaches the
    second one, and its PDF prints that account's last four."""
    other = {"id": "bottom-7700121212", "label": "BUS SELECT CHK (...1357)"}
    years = {2026: [item("DOCQXS0926", "2026-09-30", 5)], 2025: []}
    app = make_app(tmp_path, "--discover")
    attach(app, Center([dict(CHK, years=chk_years()), dict(other, years=years),
                        dict(CARD, years={2026: [item("DOCQXC0926", "2026-09-28", 4)]})],
                       years=[2026, 2025, 2024]))
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    rec = next(v for v in app.discovery.data.values() if v["page_count"] == 5)
    assert rec["account_digest"] == site.account_digest("Business Checking", "1357")
    again = Center([dict(CHK, id="bottom-8800112233", years=chk_years()),
                    dict(other, id="bottom-8800121212", years=years),
                    dict(CARD, id="bottom-8800445566", years={2026: []})],
                   years=[2026, 2025, 2024])
    got, out = take(again, tmp_path, digest=rec["account_digest"], iso="2026-09-30", pages=5)
    assert got and out.exists()
    assert "#bottom-8800121212" in again.presses


# ---------------------------------------------------------------------------
# The timeout dialog as Chase draws it: always in the page, open only when
# shown. Read in a real browser, since what decides is the page's own box.
# ---------------------------------------------------------------------------

# A web component like Chase's mds-dialog: its host draws no box of its own
# (display: contents) and its panel, in an open shadow root, is fixed on
# screen while the host carries open. Every word here is made up.
MDS_DIALOG = ("<script>customElements.define('mds-dialog', class extends HTMLElement {"
              " constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML ="
              " '<style>:host { display: contents } #panel { display: none; position: fixed;"
              " top: 10px; left: 10px; width: 300px; height: 200px }"
              " :host([open]) #panel, :host([data-drawn]) #panel { display: block }"
              " :host([data-see-through]) #panel { opacity: 0 }"
              " :host([data-hidden]) #panel { visibility: hidden }</style>"
              "<div id=\\'panel\\'>Your session is about to end</div>'; } });</script>")


def _dialog(attrs: str) -> str:
    return "<mds-dialog id='octagonSessionTimeoutDialogue' %s></mds-dialog>" % attrs


DIALOG_PAGES = {
    "closed": (_dialog(""), False),
    "closed though its panel is drawn": (_dialog("data-drawn"), False),
    "open is false": (_dialog("open='false' data-drawn"), False),
    "open with a see-through panel": (_dialog("open data-see-through"), False),
    "open with a hidden panel": (_dialog("open data-hidden"), False),
    "open with its panel drawn in the shadow root": (_dialog("open"), True),
}


@pytest.mark.parametrize("shape", sorted(DIALOG_PAGES))
def test_only_a_timeout_dialog_drawn_open_is_session_expired(shape):
    sync_api = pytest.importorskip("playwright.sync_api")
    html, expired = DIALOG_PAGES[shape]
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content("<!doctype html><meta charset='utf-8'><title>Statements and Documents</title>"
                                 "<a id='bottom-1001' href='javascript:void(0)'>BUS COMPLETE CHK (...4321)</a>"
                                 + MDS_DIALOG + html)
                assert page.evaluate("() => !!document.getElementById("
                                     "'octagonSessionTimeoutDialogue').shadowRoot")
                assert site._timeout_dialog_open(page) is expired
                assert bool(page.evaluate(site._STATE_JS)["dialog"]) is expired
                if expired:
                    with pytest.raises(site.SessionExpired):
                        site.check_signed_in(page)
                else:
                    site.check_signed_in(page)
            finally:
                browser.close()
    except sync_api.Error as e:
        pytest.skip("no browser here (%s)" % type(e).__name__)


def test_the_ready_check_takes_the_live_page_shape():
    """The document center as the live probe found it: four menu entries,
    one of them current, and the Statements accordion shown."""
    page = center()
    page.goto(site.DOCUMENTS_URL)
    assert site._ready(page.state())
    assert len(page.state()["menu"]) == 4


def test_the_year_picker_is_known_by_its_live_label():
    """Live, the picker's aria-label reads " View:: 2026", two colons."""
    assert site.is_year_picker(" View:: 2026")
    assert site.is_year_picker("View: 2026") and site.is_year_picker("2026")
    assert not site.is_year_picker("View:: Pay card")


def test_the_pickers_inner_parts_are_not_read_as_years():
    """Live, every year option has primary and secondary inner nodes with
    ids of their own; the secondary one has no words. Only the option's own
    node counts."""
    state = {"options": [
        {"id": "container-0-filterstyledselect-0", "shown": True, "labels": ["2026, current selection"]},
        {"id": "container-primary-0-filterstyledselect-0", "shown": True, "labels": ["2026"]},
        {"id": "container-secondary-0-filterstyledselect-0", "shown": True, "labels": []},
        {"id": "container-1-filterstyledselect-0", "shown": True, "labels": ["2025 , you've reached the end of the menu"]},
        {"id": "container-primary-1-filterstyledselect-0", "shown": True, "labels": ["2025"]},
        {"id": "container-secondary-1-filterstyledselect-0", "shown": True, "labels": []},
    ]}
    got = site._options(state)
    assert [(y, cur) for y, _css, cur in got] == [(2026, True), (2025, False)]


def test_the_last_year_in_the_menu_reads_with_its_end_of_menu_words():
    assert site.is_year_option("2019 , you've reached the end of the menu")
    assert site.is_year_option("2019, you\u2019ve reached the end of the list")
    assert site.is_year_option("2025")
    assert not site.is_year_option("2025, current selection")
    state = {"options": [{"id": "container-7-filterstyledselect-0", "shown": True,
                          "labels": ["2019 , you've reached the end of the menu"]}]}
    assert site._options(state) == [(2019, "#container-7-filterstyledselect-0", False)]


def test_the_current_year_reads_with_a_space_before_its_comma_too():
    state = {"options": [{"id": "container-0-filterstyledselect-0", "shown": True, "labels": ["2026 , current selection"]},
                         {"id": "container-1-filterstyledselect-0", "shown": True, "labels": ["2025, you've reached the end of the list"]}]}
    assert site._options(state) == [(2026, "#container-0-filterstyledselect-0", True), (2025, "#container-1-filterstyledselect-0", False)]


def test_the_center_is_ready_without_a_statements_accordion_when_another_shows():
    state = {"menu": [{"id": "bottom-1", "shown": True, "labels": ["BUS TOTAL DEBIT (...1234)"]}],
             "accordions": [{"id": "ATM_RECEIPTS", "shown": True, "expanded": "false"}]}
    assert site._ready(state)
    assert not site._ready({"menu": state["menu"], "accordions": []})
    assert not site._ready({"menu": [], "accordions": state["accordions"]})


def test_a_closed_menus_option_with_a_box_but_no_words_is_not_shown():
    """Live, every row's Save as PDF exists and has a box even while its menu
    is closed; only the open menu's option carries words."""
    assert "innerText" in site._MENU_JS and "getBoundingClientRect" in site._MENU_JS


def test_the_words_span_inside_a_save_as_pdf_is_not_counted_as_a_second_option():
    """Live, the option anchor item-0-N-downloadPDFOption holds a span
    itemLink-0-N-downloadPDFOption; both end alike, one option is shown."""
    assert """a[id^="item-"][id$="-downloadPDFOption"]""" in site._MENU_JS


def test_the_save_menu_is_named_by_its_exact_id_before_any_press():
    """A lookalike anchor, header-legacy-…-row0-cell3-downloadDocumentDropdown
    with the same words, must never be pressed: the selector names the one
    exact id up front, not a suffix."""
    import inspect
    src = inspect.getsource(site._catch_statement)
    assert 'a#header-accountsTable-STATEMENTS-row%d-cell3-downloadDocumentDropdown' in src
    assert 'a[id^="header-"][id$="-row%d-cell3-downloadDocumentDropdown"]' not in src


# ---------------------------------------------------------------------------
# After the maintainer's review: turned off row controls, the PDF's last
# four, the picker's end, the account digest
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["downloadDocumentDropdown", "downloadPDFOption"])
def test_a_turned_off_row_control_leaves_its_statement_and_the_run_goes_on(tmp_path, monkeypatch,
                                                                          which):
    page = center()

    def click(pg, locator, *, css, what, words, step="press a control", **kw):
        if which in css:
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        pg.click(css)
    monkeypatch.setattr(site.pressing, "click", click)
    trace: list = []
    got, out = take(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert page.downloads == []
    assert any("turned off" in str(t.get("note")) for t in trace)


def test_a_turned_off_list_control_stops_the_run(monkeypatch):
    page = center()

    def click(pg, locator, *, css, what, words, step="press a control", **kw):
        if css.startswith("#container-"):
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        pg.click(css)
    monkeypatch.setattr(site.pressing, "click", click)
    with pytest.raises(site.pressing.TurnedOff):
        site.collect_download_docs(page, run())


def test_a_pdf_that_does_not_print_the_accounts_last_four_is_not_kept(tmp_path):
    page = center()
    page.download_body = _pdf("9999")
    trace: list = []
    got, out = take(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the account's last four"} in trace
    page = center()
    page.download_body = _pdf("4321")
    got, out = take(page, tmp_path, name="kept.pdf")
    assert got is True and out.exists()


def test_the_last_four_must_end_an_account_number():
    assert site.names_tail("Account Number: 000000004321", "4321")
    assert site.names_tail("Account Number:\n \n 000000004321\nPAGE", "4321")
    assert site.names_tail("Card ending XXXX XXXX XXXX 4321.", "4321")
    assert site.names_tail("Account ****-****-4321", "4321")
    assert not site.names_tail("Account Number: 000043210", "4321")
    # The same four digits ending something that is not an account number.
    for other in ("Call 1-800-555-4321", "Check 4321 paid", "Ref 1234321", "BUS COMPLETE CHK (...4321)",
                  "Total 12,344,321.00", "ID A1234321"):
        assert not site.names_tail(other, "4321"), other
    assert not site.names_tail("", "4321")
    assert not site.names_tail("Account Number: 4321", "")


def test_a_long_run_that_names_no_tail_is_read_in_one_pass():
    """A long run of marks ending in other digits once took a second for
    fifty-two marks, and each mark more doubled it. It is read in one pass
    now, so runs a hundred times longer answer, and answer no, well inside
    a second of the processor's own time."""
    import time as _time
    started = _time.process_time()
    assert not site.names_tail("X" * 5000 + "4320", "4321")
    assert not site.names_tail(("XXXX " * 2000) + "4320", "4321")
    assert _time.process_time() - started < 1.0


@pytest.mark.parametrize("text", [
    "Account Number: 000000998877\nBook Transfer Credit A/C 000000987654321 Ref 77",
    "Account Number: 000000998877\nOnline Transfer From Chk ...1111 Transaction#: 9876544321",
    "Card ending XXXX XXXX XXXX 8877 01/31/26\nPayment Ref 000000554321",
])
def test_only_the_header_account_number_is_judged(text):
    """Another account's statement can print this account's number in a
    transfer line, and a long transaction number can end in the same
    four. Only the first account number, the header's, is judged."""
    assert not site.names_tail(text, "4321")


@pytest.mark.parametrize("text", [
    "XXXX XXXX XXXX 4321 01/31/26",
    "Account Number: 000000123454321 1",
    "Primary Account 000 000123454321",
    "********\nAccount Number: 000000123454321\nTransaction#: 9876500001",
])
def test_a_short_group_beside_the_number_does_not_hide_it(text):
    """A date or a page number on the number's own line is a short group
    beside it, not part of it, and a row of marks with no digits is no
    number, so the header's number is still read."""
    assert site.names_tail(text, "4321")


def test_another_accounts_statement_naming_this_account_is_not_kept(tmp_path):
    from paperpull_core import testkit
    page = center()
    page.download_body = testkit.text_pdf(["Business Complete Checking", "Account Number: 000000998877",
                                           "Book Transfer Debit A/C 000000554321 Ref 1"])
    trace: list = []
    got, out = take(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the account's last four"} in trace


def test_the_header_number_is_read_in_one_pass_whatever_comes_after_it():
    import time as _time
    started = _time.process_time()
    assert not site.names_tail("1 " * 200000 + "12-" * 100000 + "X" * 200000 + "4320", "4321")
    assert site.names_tail(("1234 " * 100000) + "4321 01" + " 9" * 100000, "4321")
    assert _time.process_time() - started < 1.0


# The top of a business checking statement, in the order its header
# prints. Every name, address and number is invented. The bank's return
# address ends in a ZIP+4, and the mailing line under it starts with an
# eight digit sort number and holds a run of zeros.
_RETURN_ADDRESS = ["January 01, 2026 through January 31, 2026", "P O Box 900417",
                   "Columbus, OH 43299-0417"]
_MAIL_SORT = "00012345 DRE 802 219 30425 NNNNNNNNNNN 1 000000000 64 0000"
_ADDRESSEE = ["QUILLFEATHER WIDGETS LLC", "77 INVENTED WAY", "SPRINGFIELD ZZ 99999-0001"]
_SERVICE = ["CUSTOMER SERVICE INFORMATION", "Web site: Chase.com", "Service Center: 1-800-555-0199"]
_TRANSFER = ["Online Transfer To Chk ...1111 Transaction#: 9876500002"]


def _header(account_lines, before=(), after=()):
    return "\n".join(list(before) + list(account_lines) + list(after))


@pytest.mark.parametrize("account_lines", [
    ["Account Number: 000000123454321"],
    ["Account Number 0000 0001 2345 4321"],
    ["Account  Number :", "000000123454321"],
])
def test_a_zip_plus_four_before_the_labeled_number_does_not_hide_it(account_lines):
    """The bank's return address can print before the account number, and
    its ZIP+4 is not an account number. The number after the label is the
    one judged."""
    text = _header(account_lines, before=_RETURN_ADDRESS, after=_SERVICE + [_MAIL_SORT] + _ADDRESSEE)
    assert site.names_tail(text, "4321")


def test_a_mail_sort_line_before_the_labeled_number_does_not_hide_it():
    text = _header(["Account Number:", "000000123454321"], before=[_MAIL_SORT] + _ADDRESSEE,
                   after=_SERVICE + _TRANSFER)
    assert site.names_tail(text, "4321")


@pytest.mark.parametrize("before", [
    ["P O Box 900417", "Columbus, OH 43299-4321"],
    ["00004321 DRE 802 219 30425 NNNNNNNNNNN 1 000000000 64 0000"],
    ["Ref 000000554321"],
])
def test_a_labeled_number_of_another_account_is_refused(before):
    """Four digits that happen to match, in a ZIP+4, a sort number or any
    number printed before the label, do not stand for the labeled number
    of another account."""
    text = _header(["Account Number: 000000998877"], before=before,
                   after=_SERVICE + ["Book Transfer Credit A/C 000000554321 Ref 77"])
    assert not site.names_tail(text, "4321")


@pytest.mark.parametrize("before", [
    _RETURN_ADDRESS,
    [_MAIL_SORT],
    _RETURN_ADDRESS + [_MAIL_SORT] + _ADDRESSEE,
])
def test_with_no_label_the_first_account_number_is_still_found(before):
    """With no label the first account number is judged, and a ZIP+4, a
    sort number or a run of zeros printed before it is no account number."""
    text = _header(["Business Complete Checking 000000123454321"], before=before, after=_TRANSFER)
    assert site.names_tail(text, "4321")
    text = _header(["Business Complete Checking 000000998877"], before=before,
                   after=["Book Transfer Credit A/C 000000554321 Ref 77"])
    assert not site.names_tail(text, "4321")


def test_a_statement_whose_header_prints_a_zip_plus_four_first_is_kept(tmp_path):
    from paperpull_core import testkit
    page = center()
    page.download_body = testkit.text_pdf(_RETURN_ADDRESS + ["Account Number: 000000123454321"] + _SERVICE
                                          + [_MAIL_SORT] + _ADDRESSEE)
    got, out = take(page, tmp_path)
    assert got is True and out.exists()


def test_another_accounts_statement_is_not_kept_for_four_digits_before_its_label(tmp_path):
    from paperpull_core import testkit
    page = center()
    page.download_body = testkit.text_pdf(["P O Box 900417", "Columbus, OH 43299-4321",
                                           "Account Number: 000000998877"] + _SERVICE)
    trace: list = []
    got, out = take(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the account's last four"} in trace


def _options_state(labels):
    return {"options": [{"id": "container-%d-filterstyledselect-0" % i, "labels": [t], "shown": True}
                        for i, t in enumerate(labels)]}


def test_the_oldest_year_must_carry_the_end_of_menu_words():
    end = ", you've reached the end of the menu"
    good = site._options(_options_state(["2026 , current selection", "2025", "2024" + end]))
    assert [y for y, _c, _cur in good] == [2026, 2025, 2024]
    assert site._options(_options_state(["2026", "2025 , current selection" + end]))[1][2] is True
    for labels in (["2026 , current selection", "2025", "2024"],            # no end words
                   ["2026 , current selection", "2025" + end, "2024"],      # on another year
                   ["2026" + end, "2025", "2024" + end]):                   # on two
        with pytest.raises(site.ListStopped):
            site._options(_options_state(labels))


def test_the_account_digest_is_its_own_field_and_survives_without_the_ref():
    digest = site.account_digest("Business Checking", "4321")
    d = docs.Document(title="Business Checking Statement", account="Business Checking",
                      date="2026-09-30", account_ref=CHK["id"], doc_type="Statement",
                      account_digest=digest)
    assert len(digest) == 12 and "4321" not in digest
    assert d.key == "id:Business Checking:2026-09-30:Statement:" + digest
    assert site.account_digest("Business Checking", "") == ""
    assert site.account_digest("Business Card", "4321") != digest
    rec = d.to_dict()
    moved = {k: v for k, v in rec.items() if k not in ("account_ref", "document_id")}
    assert docs.Document.from_dict(moved).key == d.key
    assert docs.told_apart_by(moved) == docs.told_apart_by(rec) == d.account_digest[:6]


# ---------------------------------------------------------------------------
# The business card's row: no save menu, a "<date> Saves document" link
# (live survey 2026-10-17)
# ---------------------------------------------------------------------------

CARD_DIGEST = site.account_digest("Business Card", "8765")


def take_card(page, tmp_path, **kw):
    kw.setdefault("doc_id", "DOCQXC0926")
    kw.setdefault("iso", "2026-09-28")
    kw.setdefault("pages", 4)
    return take(page, tmp_path, digest=CARD_DIGEST, **kw)


def test_the_saves_document_guard_takes_its_own_row_and_words_only():
    assert site.is_saves_document("Oct 13, 2026 Saves document")
    assert site.is_saves_document("Oct 13, 2026 Saves document", "Oct 13, 2026")
    assert site.is_saves_document("Oct 03, 2026 Saves document", "Oct 3, 2026")
    assert not site.is_saves_document("Oct 13, 2026 Saves document", "Sep 13, 2026")
    for bad in ("Oct 13, 2026 , opens document", "Oct 13, 2026 opens document", "Saves document",
                "Oct 13, 2026 Saves document Sign out", "Oct 13, 2026 Opens menu to save document",
                "Save as PDF", "Oct 13, 2026 Saves document menu", ""):
        assert not site.is_saves_document(bad, "Oct 13, 2026"), bad
    assert not site.is_save_menu("Oct 13, 2026 Saves document")
    assert not site.is_save_as_pdf("Oct 13, 2026 Saves document")


def test_a_card_statement_is_taken_through_its_saves_document_link(tmp_path):
    page = center()
    trace: list = []
    got, out = take_card(page, tmp_path, trace=trace)
    assert got and out.read_bytes()[:5] == b"%PDF-"
    assert "#" + CARD["id"] in page.presses
    assert page.presses[-1] == anchor_css(0)
    assert not any("downloadDocumentDropdown" in p or "downloadPDFOption" in p for p in page.presses)
    assert not any(p.endswith("-requestThisDocumentAnchor-pdf") for p in page.presses)
    assert len(page.downloads) == 1


def test_a_checking_statement_is_still_taken_through_its_save_menu(tmp_path):
    page = center()
    got, _out = take(page, tmp_path)
    assert got
    assert not any("requestThisDocumentAnchor" in p for p in page.presses)


@pytest.mark.parametrize("shape, why", [("both", "both a save menu and a Saves document link"),
                                        ("neither", "neither a save menu nor a Saves document link")])
@pytest.mark.parametrize("which", ["checking", "card"])
def test_a_row_with_both_shapes_or_neither_presses_nothing_on_the_row(tmp_path, shape, why, which):
    page = center()
    page.accounts[0 if which == "checking" else 1]["shape"] = shape
    trace: list = []
    if which == "checking":
        got, out = take(page, tmp_path, trace=trace)
    else:
        got, out = take_card(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert not any("cell3" in p or "downloadPDFOption" in p for p in page.presses)
    assert page.downloads == []
    assert any(why in str(t.get("why")) for t in trace), trace


@pytest.mark.parametrize("labels", [["Sep 28, 2026 , opens document"],
                                    ["Sep 30, 2026 Saves document"],
                                    ["Sep 28, 2026 Saves document", "Sign out"],
                                    ["Sep 28, 2026 Saves document", "Oct 13, 2026 Saves document"],
                                    []])
def test_a_saves_document_link_that_is_not_the_rows_own_is_never_pressed(tmp_path, labels):
    page = center()
    page.anchor_labels = labels
    got, out = take_card(page, tmp_path)
    assert got is False and not out.exists()
    assert not any("requestThisDocumentAnchor" in p for p in page.presses)
    assert page.downloads == []


def test_the_saves_document_link_is_named_by_its_exact_id_before_any_press():
    import inspect
    src = inspect.getsource(site._catch_statement)
    assert 'a#accountsTable-STATEMENTS-row%d-cell3-requestThisDocumentAnchor-download' in src
    for fn in (site._catch_statement, site._catch_by_anchor, site._row_shape_of):
        assert "requestThisDocumentAnchor-pdf" not in inspect.getsource(fn)


def test_the_card_download_is_bound_to_its_own_row(tmp_path):
    page = center()
    page.accounts[1]["years"] = {2026: [item("DOCQXC0926", "2026-09-28", 4),
                                        item("DOCQXC0826", "2026-08-28", 3)]}
    got, out = take_card(page, tmp_path, doc_id="DOCQXC0826", iso="2026-08-28", pages=3)
    assert got and out.exists()
    assert page.presses[-1] == anchor_css(1)
    assert anchor_css(0) not in page.presses


@pytest.mark.parametrize("change, reason", [
    ({"downloads_per_save": 2}, "more than one download came"),
    ({"download_url": "https://www.chase.com/svc/rr/documents/secure/idal/v5/pdfdoc/star/list"},
     "the download came from elsewhere"),
    ({"download_url": BASE + "/svc/rr/documents/secure/idal/v2/dockey/list"},
     "the download came from elsewhere"),
    ({"download_body": b"<html>signed out</html>"}, "the download was not a pdf"),
    ({"downloads_per_save": 0}, "no download came"),
    ({"popup_on_save": True}, "a new tab opened"),
])
def test_a_card_download_that_is_not_one_pdf_from_chase_stops_the_run(tmp_path, change, reason):
    page = center()
    for k, v in change.items():
        setattr(page, k, v)
    with pytest.raises(site.pressing.Stop) as stop:
        take_card(page, tmp_path)
    assert stop.value.reason == reason
    assert not (tmp_path / "out.pdf").exists()
    assert [p for p in page.presses if "requestThisDocumentAnchor" in p] == [anchor_css(0)]


def test_a_card_pdf_that_does_not_print_its_date_is_not_kept(tmp_path):
    page = center()
    page.download_body = _pdf("8765")
    trace: list = []
    got, out = take_card(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the statement's date"} in trace


def test_a_card_pdf_that_does_not_print_the_cards_last_four_is_not_kept(tmp_path):
    page = center()
    page.download_body = _card_pdf("9999", "2026-09-28")
    trace: list = []
    got, out = take_card(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the account's last four"} in trace


def test_a_turned_off_saves_document_leaves_its_statement(tmp_path, monkeypatch):
    page = center()

    def click(pg, locator, *, css, what, words, step="press a control", **kw):
        if "requestThisDocumentAnchor" in css:
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        pg.click(css)
    monkeypatch.setattr(site.pressing, "click", click)
    trace: list = []
    got, out = take_card(page, tmp_path, trace=trace)
    assert got is False and not out.exists() and page.downloads == []
    assert {"note": "saves document is turned off"} in trace


def test_a_late_second_card_download_stops_the_next_statement(tmp_path):
    page = center()
    page.late_download = True
    r = run()
    got, _out = take_card(page, tmp_path, r=r)
    assert got
    before = list(page.presses)
    with pytest.raises(site.pressing.Stop) as stop:
        take_card(page, tmp_path, r=r, name="next.pdf")
    assert stop.value.reason == "a download came that no press took"
    assert not any("cell3" in p for p in page.presses[len(before):])


@pytest.mark.parametrize("text, ok", [
    ("Opening/Closing Date 09/14/26 - 10/13/26", True),
    ("Opening/Closing Date\n09/14/2026 - 10/13/2026", True),
    ("Opening / Closing Date: Sep 14, 2026 - Oct 13, 2026", True),
    ("Statement Date 10/13/2026", True),
    ("Statement date: Oct 13, 2026", True),
    ("Closing Date October 13, 2026", True),
    ("Statement Date 2026-10-13", True),
    # The date printed anywhere else, a purchase's say, is not the statement's.
    ("Opening/Closing Date 08/14/26 - 09/13/26 10/13 COFFEE 10/13/26 4.50", False),
    ("10/13/26 OFFICE SUPPLIES 12.00", False),
    ("October 13, 2026", False),
    ("Payment Due Date 10/13/26", False),
    # The opening date is not the statement's.
    ("Opening/Closing Date 10/13/26 - 11/12/26", False),
    ("Opening/Closing Date 09/14/26 - 10/12/26", False),
    ("Statement Date 110/13/26", False),
    ("Statement Date 10/13/261", False),
    ("Statement Date Oct 13, 20261", False),
    ("Statement Date Octopus 13, 2026", False),
    ("Statement Date Octobe 13, 2026", False),
    ("Statement Date Octo 13, 2026", False),
    ("Statement Date 02/30/26", False),
    ("", False),
])
def test_a_card_statement_names_its_date(text, ok):
    assert site.names_date(text, "2026-10-13") is ok
    assert site.names_date(text, "not a date") is False


def test_another_statement_of_the_card_that_lists_a_purchase_on_this_date_is_not_kept(tmp_path):
    from paperpull_core import testkit
    page = center()
    page.download_body = testkit.text_pdf([
        "Ink Business Unlimited", "Account Number: XXXX XXXX XXXX 8765",
        "Opening/Closing Date 09/29/26 - 10/28/26", "09/28/26 OFFICE SUPPLIES 12.00"])
    trace: list = []
    got, out = take_card(page, tmp_path, trace=trace)
    assert got is False and not out.exists()
    assert {"note": "the pdf does not print the statement's date"} in trace


def test_a_new_tab_that_opens_late_stops_the_next_statement(tmp_path):
    page = center()
    page.accounts[1]["years"] = {2026: [item("DOCQXC0926", "2026-09-28", 4),
                                        item("DOCQXC0826", "2026-08-28", 3)]}
    r = run()
    got, _out = take_card(page, tmp_path, r=r)
    assert got
    for f in list(page.listeners["popup"]):
        f(object())
    before = list(page.presses)
    with pytest.raises(site.pressing.Stop) as stop:
        take_card(page, tmp_path, r=r, doc_id="DOCQXC0826", iso="2026-08-28", pages=3,
                  name="next.pdf")
    assert stop.value.reason == "a new tab opened"
    assert not any("cell3" in p for p in page.presses[len(before):])
    assert not (tmp_path / "next.pdf").exists()
    # A checking statement after it is not pressed either.
    with pytest.raises(site.pressing.Stop):
        take(page, tmp_path, r=r, name="chk.pdf")
    assert not any("cell3" in p or "downloadPDFOption" in p for p in page.presses[len(before):])


def test_a_run_of_checking_statements_alone_watches_no_new_tabs(tmp_path):
    page = center()
    got, _out = take(page, tmp_path)
    assert got and page.listeners["popup"] == []


def test_the_failure_file_counts_the_card_rows_saves_document_links():
    sel = site.FALLBACK["card_download"]
    assert 'id$="-cell3-requestThisDocumentAnchor-download"' in sel
    assert "requestThisDocumentAnchor-pdf" not in sel


def test_a_september_statement_reads_with_sept_too():
    assert site.names_date("Statement Date Sept 28, 2026", "2026-09-28")
    assert site.names_date("Statement Date September 28, 2026", "2026-09-28")
    assert not site.names_date("Statement Date Septe 28, 2026", "2026-09-28")


@pytest.mark.parametrize("when", ["after the save menu", "after save as pdf"])
def test_a_checking_row_after_a_card_is_held_to_new_tabs_too(tmp_path, monkeypatch, when):
    page = center()
    r = run()
    got, _out = take_card(page, tmp_path, r=r)
    assert got and page.listeners["popup"]
    real = page.click

    def click(css):
        if when == "after save as pdf" and css.endswith("-downloadPDFOption"):
            real(css)
            for f in list(page.listeners["popup"]):
                f(object())
            return
        real(css)
        if when == "after the save menu" and "downloadDocumentDropdown" in css:
            for f in list(page.listeners["popup"]):
                f(object())
    monkeypatch.setattr(page, "click", click)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, r=r, name="chk.pdf")
    assert stop.value.reason == "a new tab opened"
    assert not (tmp_path / "chk.pdf").exists()
    if when == "after the save menu":
        assert not any(p.endswith("-downloadPDFOption") for p in page.presses)
