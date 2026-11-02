"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only: a made-up Alpaca documents
page drawn the way the owner's survey found it, driven through the site
layer's own code with the core's press replaced by the fake's."""
import ast
import io
import json
import logging
import re
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import alpaca_site as site  # noqa: E402
import alpaca_docs as docs  # noqa: E402

BASE = "https://app.alpaca.markets"
ACCT = "acc0ffee-1234-4abc-8def-0123456789ab"
LIST_URL = BASE + "/api/v1/accounts/%s/documents?start=2023-10-12&end=2026-10-12" % ACCT
NUMBER = "7QX40031"
TODAY = date(2026, 10, 13)
LIVE = "QUILLFEATHER VENTURES LLC - %s" % NUMBER
PAPER = "QUILLFEATHER VENTURES LLC Paper - PA3QX40031"
SIGNATURE = "SIGQXQX0042"
CREDENTIAL = "AKIAQXQX"


def link_for(doc_id, number=NUMBER, bucket="prod.alpaca.markets", **change):
    fields = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256",
              "X-Amz-Credential": CREDENTIAL + "%2F20261012%2Fus-east-1%2Fs3%2Faws4_request",
              "X-Amz-Date": "20261012T000000Z", "X-Amz-Expires": "300",
              "X-Amz-Signature": SIGNATURE, "X-Amz-SignedHeaders": "host"}
    fields.update(change)
    query = "&".join("%s=%s" % (k, v) for k, v in fields.items() if v is not None)
    return "https://s3.amazonaws.com/%s/LEDGIE_US_SEC/accounts/%s/trade_confirms/%s.pdf?%s" % (
        bucket, number, number, query)


def uid(n):
    return "5eed%04x-0000-4000-8000-%012x" % (n, n)


def _pdf() -> bytes:
    from pypdf import PdfWriter
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(buf)
    return buf.getvalue()


PDF = _pdf()


def item(n, day, kind):
    return {"id": uid(n), "name": "", "type": kind, "sub_type": None, "date": day}


def survey_items():
    """The survey's shape, smaller: two brokerage statements, one crypto
    statement, an application and twelve trade confirmations, each with
    its JSON twin on the same day. 28 documents, three pages of ten."""
    out = [item(1, "2026-08-31", "account_statement"), item(2, "2026-09-30", "account_statement"),
           item(3, "2026-09-30", "crypto_account_statement"),
           item(4, "2026-08-17", "account_application")]
    for k in range(12):
        day = "2026-09-%02d" % (k + 1)
        out.append(item(100 + k, day, "trade_confirmation"))
        out.append(item(200 + k, day, "trade_confirmation_json"))
    return out


SECRETS = ["QUILLFEATHER", "VENTURES", NUMBER, "PA3QX40031", ACCT, SIGNATURE, CREDENTIAL,
           "LEDGIE", "s3.amazonaws.com"] + [uid(n) for n in (1, 2, 3, 4, 100, 105, 200)]


# ---------------------------------------------------------------------------
# The made-up documents page
# ---------------------------------------------------------------------------

class Request:
    def __init__(self, method="GET"):
        self.method = method


class Response:
    def __init__(self, url, data, status=200, method="GET", raw=None):
        self.url, self.status, self._data, self._raw = url, status, data, raw
        self.request = Request(method)

    def json(self):
        if self._raw is not None:
            return json.loads(self._raw)
        return self._data


class Download:
    def __init__(self, url, body):
        self.url, self.body = url, body
        self.suggested_filename = NUMBER + ".pdf"
        self.canceled = False
        self.deleted = False

    def save_as(self, path):
        Path(path).write_bytes(self.body)

    def cancel(self):
        self.canceled = True

    def delete(self):
        self.deleted = True


class Info:
    value = None


class Locator:
    def __init__(self, page, css, nth=None):
        self.page, self.css, self.index = page, css, nth

    def nth(self, i):
        return Locator(self.page, self.css, i)

    def _labels(self):
        return self.page.labels_for(self.css, self.index)

    def count(self):
        if self.css == "input[type='password']":
            return 1 if self.page.password else 0
        if self.css == site.FALLBACK["doc_row"]:
            return len(self.page.page_rows())
        return 1 if self._labels() is not None else 0

    def is_visible(self):
        return self._labels() is not None

    def evaluate(self, js):
        assert js == site._LABELS_JS
        return list(self._labels() or [])

    def inner_text(self, timeout=None):
        return ""


OTHER_BUTTONS = [["Filters"], ["Add Funds"], [LIVE]]


class Center:
    """The documents page. `items` is what the list answers, `rows` (date,
    type, id) what the table draws, in order, ten a page."""

    def __init__(self, items=None, rows=None):
        self.items = survey_items() if items is None else items
        self.rows = rows
        self.list_url = LIST_URL
        self.url = BASE + "/dashboard/overview"
        self.switcher = [{"text": LIVE, "shown": True}]
        self.banner = self.password = False
        self.paper_redirect = self.login_on_goto = False
        self.list_status, self.list_raw, self.list_data = 200, None, None
        self.list_answers = 1
        self.link_status, self.link_override = 200, None
        self.link_answers = 1
        self.downloads_per_press = 1
        self.download_body = PDF
        self.download_url = None
        self.next_turns = True
        self.next_disabled_always = False
        self.on_press = None
        self.listeners = {"response": [], "download": []}
        self.emitted, self.downloads, self.presses = [], [], []
        self.page = 0
        self.closed = False

    # -- the page's own behavior -------------------------------------------
    def drawn(self):
        if self.rows is not None:
            return list(self.rows)
        return [(i["date"], i["type"], i["id"]) for i in self.items]

    def pages(self):
        rows = self.drawn()
        return max(1, (len(rows) + 9) // 10)

    def page_rows(self):
        if not site.is_documents_url(self.url):
            return []
        return self.drawn()[self.page * 10:(self.page + 1) * 10]

    def buttons(self):
        out = [list(b) for b in OTHER_BUTTONS] + [["Previous"]]
        out += [[str(k + 1)] for k in range(self.pages())]
        out += [["Next"]]
        return out

    def _emit(self, resp):
        self.emitted.append(resp)
        for f in list(self.listeners["response"]):
            f(resp)

    def goto(self, url, **kw):
        if self.login_on_goto:
            self.url = BASE + "/account/login"
            return
        if self.paper_redirect:
            self.url = BASE + "/dashboard/overview"
            return
        self.url = url
        self.page = 0
        data = self.items if self.list_data is None else self.list_data
        for _ in range(self.list_answers):
            self._emit(Response(self.list_url, data, status=self.list_status, raw=self.list_raw))

    def click(self, loc):
        self.presses.append((loc.css, loc.index))
        if self.on_press:
            self.on_press(self, loc)
        if loc.css == "button":
            label = self.buttons()[loc.index][0]
            assert label == "Next", "pressed something else: %s" % label
            if self.next_turns and self.page + 1 < self.pages():
                self.page += 1
            return
        m = re.fullmatch(r"table tbody tr:nth-of-type\((\d+)\) > td:last-child p", loc.css)
        assert m, "pressed something else: " + loc.css
        row = self.page_rows()[int(m.group(1)) - 1]
        doc_id = row[2]
        link = link_for(doc_id)
        for _ in range(self.link_answers):
            if self.link_override:
                self._emit(self.link_override(doc_id))
            else:
                self._emit(Response(BASE + "/api/v1/accounts/%s/documents/%s/url" % (ACCT, doc_id),
                                    {"id": doc_id, "url": link}, status=self.link_status))
        for _ in range(self.downloads_per_press):
            dl = Download(self.download_url or link, self.download_body)
            self.downloads.append(dl)
            for f in list(self.listeners["download"]):
                f(dl)

    # -- what the site layer reads ------------------------------------------
    def state(self):
        on = site.is_documents_url(self.url)
        rows = [{"n": k + 1, "shown": True, "cells": [d, t, "Download"], "controls": 1,
                 "control": ["Download"]} for k, (d, t, _i) in enumerate(self.page_rows())]
        buttons = []
        if on:
            for i, labels in enumerate(self.buttons()):
                if labels[0] in ("Next", "Previous") or labels[0].isdigit():
                    last = self.page + 1 >= self.pages()
                    buttons.append({"i": i, "labels": labels, "shown": True,
                                    "disabled": labels[0] == "Next" and (last or self.next_disabled_always)})
        return {"switcher": self.switcher, "banner": self.banner, "tables": 1 if on else 0,
                "bodies": 1 if on else 0, "rows": rows, "buttons": buttons,
                "password": self.password}

    def labels_for(self, css, index=None):
        if css == "button" and index is not None:
            b = self.buttons()
            return b[index] if 0 <= index < len(b) else None
        m = re.fullmatch(r"table tbody tr:nth-of-type\((\d+)\) > td:last-child p", css)
        if m:
            n = int(m.group(1))
            return ["Download"] if 1 <= n <= len(self.page_rows()) else None
        return None

    # -- the Playwright surface ----------------------------------------------
    def evaluate(self, js):
        assert js == site._STATE_JS
        return self.state()

    def locator(self, css):
        return Locator(self, css)

    def on(self, event, f):
        self.listeners[event].append(f)

    def remove_listener(self, event, f):
        self.listeners[event].remove(f)

    def wait_for_timeout(self, ms):
        pass

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
    """The core's press, replaced by the made-up page's. The press is the
    core's own to test, and this only says which control was pressed."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert locator.css == css
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    # The day after the made-up list's window ends, so its window reaches
    # yesterday whatever day the tests run on.
    monkeypatch.setattr(site, "_today", lambda: TODAY)
    site.set_private_words([])
    yield


def run(floor="2023-10-12"):
    """A run whose own start date is the made-up list's first day, so a list
    of the site layer's tests is whole without an application in it."""
    r = site.Run()
    r.floor = floor
    return r


def pressed_downloads(page):
    return [p for p in page.presses if p[0] != "button"]


def pressed_next(page):
    return [p for p in page.presses if p[0] == "button"]


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

REFUSED = [
    "Buy", "Sell", "Cancel 0 selected", "Cancel order", "Place Order", "Trade", "Transfer",
    "Deposit", "Withdraw", "Add Funds", "Funds & Wallet", "Wallet", "Configure", "Regenerate",
    "Delete Account", "API Key", "View API Keys", "Alpaca Connect", "Plans & Features",
    "Upgrade", "Subscribe", "Switch account", LIVE, PAPER, "User profile options",
    "Profile", "Settings", "Save", "Edit", "Accept", "Agree", "Enable", "Disable", "Sign out",
    "Log out", "Chat with us", "Filters", "Interest Products", "Documents", "",
    "Download statement", "Download PDF", "Next page", "Previous page", "1000", "Download all",
    "Brokerage Statement", "Trade Confirmation", "Liquidate", "Close position",
]


@pytest.mark.parametrize("label", REFUSED)
def test_every_other_label_is_refused_by_every_guard(label):
    assert not site.is_safe_control(label)
    for guard in site.PRESS_GUARDS:
        assert not guard(label), (guard.__name__, label)


def test_only_the_four_whole_labels_are_taken():
    for good in ("Download", "download", "Next", "Previous", "1", "2", "12", "999", " Next "):
        assert site.is_safe_control(good), good
    assert site.is_download_control("Download") and not site.is_download_control("Next")
    assert site.is_next_control("Next") and not site.is_next_control("Download")
    assert not site.is_next_control("Previous") and not site.is_next_control("2")


@pytest.mark.parametrize("bad", ["Sign out", "Buy", "Add Funds", PAPER])
@pytest.mark.parametrize("good", ["Download", "Next", "2"])
def test_mixed_labels_are_refused(good, bad):
    for joined in ("%s | %s" % (good, bad), "%s | %s" % (bad, good), "%s %s" % (good, bad)):
        assert not site.is_safe_control(joined)
        assert not any(g(joined) for g in site.PRESS_GUARDS)


def test_a_control_with_one_refused_label_is_not_pressed():
    page = Center()
    site._open(page, run())
    page.labels_for = lambda css, index=None: ["Next", "Sign out"]
    with pytest.raises(site.ListStopped):
        site._press(page, run(), page.locator("button").nth(5), css="button", what="x",
                    guard=site.is_next_control, step="turn the list's page",
                    off=site.STOPS_THE_LIST)
    assert page.presses == []


def test_a_press_with_a_guard_not_of_the_two_is_refused():
    page = Center()
    site._open(page, run())
    with pytest.raises(site.ListStopped):
        site._press(page, run(), page.locator("button").nth(5), css="button", what="x",
                    guard=site.is_safe_control, step="turn the list's page",
                    off=site.STOPS_THE_LIST)
    assert page.presses == []


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def test_url_guards():
    assert site.is_safe_url(BASE + "/account/documents")
    for bad in ("http://app.alpaca.markets/x", "https://alpaca.markets/", "https://api.alpaca.markets/x",
                "https://authx.alpaca.markets/v1/oauth2/token", "https://app.alpaca.markets.evil.test/",
                "https://app.alpaca.markets:8443/x", "https://user@app.alpaca.markets/x",
                "https://unleash.alpaca.markets/x", "https://s3.amazonaws.com/prod.alpaca.markets/x", ""):
        assert not site.is_safe_url(bad), bad
    assert site.is_documents_url(site.DOCUMENTS_URL)
    assert not site.is_documents_url(BASE + "/dashboard/overview")
    assert not site.is_documents_url(BASE + "/account/documents/x")
    for extra in ("?tab=1", "?x", "#top", "?a=1#b"):
        assert not site.is_documents_url(site.DOCUMENTS_URL + extra), extra


def test_the_list_and_link_predicates_are_exact():
    assert site.is_list_url(LIST_URL)
    for bad in (LIST_URL.replace("&end=2026-10-12", ""),
                LIST_URL + "&type=account_statement",
                LIST_URL + "&start=2020-01-01",
                LIST_URL.replace("2026-10-12", "2026-02-30"),
                LIST_URL.replace("https://", "http://"),
                LIST_URL.replace("app.alpaca", "paper-api.alpaca"),
                LIST_URL.replace("/documents?", "/documents/x?"),
                LIST_URL.replace(ACCT, "not-a-uuid"),
                BASE + "/api/v1/accounts/%s/details" % ACCT,
                BASE + "/documents/accounts/%s" % ACCT):
        assert not site.is_list_url(bad), bad
    assert not site.is_list_response(Response(LIST_URL, [], method="POST"))
    assert site.is_list_response(Response(LIST_URL, []))
    link = BASE + "/api/v1/accounts/%s/documents/%s/url" % (ACCT, uid(1))
    assert site.is_link_url(link) and site.is_link_url(link, uid(1))
    assert not site.is_link_url(link, uid(2)), "another document"
    assert not site.is_link_url(link + "?x=1") and not site.is_link_url(link.replace("/url", "/urls"))
    for private in ("/details", "/owners"):
        assert not site.is_census_url(BASE + "/api/v1/accounts/%s%s" % (ACCT, private))
    assert not site.is_census_url(BASE + "/api/v1/billing/overview")
    assert site.is_census_url(LIST_URL) and site.is_census_url(link)


def test_the_download_link_is_checked_field_by_field():
    good = link_for(uid(1))
    assert site.is_download_url(good)
    bad = [
        link_for(uid(1), bucket="other.bucket"),
        link_for(uid(1), bucket="prod.alpaca.markets.evil"),
        good.replace("https://", "http://"),
        good.replace("s3.amazonaws.com", "s3.us-east-1.amazonaws.com"),
        good.replace("s3.amazonaws.com", "evil.test"),
        good.replace("https://s3.amazonaws.com", "https://user:pw@s3.amazonaws.com"),
        good.replace("https://s3.amazonaws.com", "https://s3.amazonaws.com:8443"),
        good + "#x",
        good + "&X-Amz-Signature=OTHER",
        link_for(uid(1), **{"X-Amz-Signature": ""}),
        "https://s3.amazonaws.com/prod.alpaca.markets/", "", None,
    ]
    for field in site.AMZ_FIELDS:
        bad.append(link_for(uid(1), **{field: None}))
    for b in bad:
        assert not site.is_download_url(b), b


# ---------------------------------------------------------------------------
# Live only
# ---------------------------------------------------------------------------

def test_the_account_check():
    site.check_account({"switcher": [{"text": LIVE, "shown": True}]})
    for state in ({"switcher": [{"text": PAPER, "shown": True}]},
                  {"switcher": [{"text": "Paper - PA3QX40031", "shown": True}]},
                  {"switcher": [{"text": "QUILLFEATHER LLC  paper   -  PA3", "shown": True}]},
                  {"switcher": [{"text": "QUILLFEATHER LLC Paper Trading - PA3", "shown": True}]},
                  {"switcher": [{"text": "PAPER-PA3QX40031", "shown": True}]},
                  {"switcher": [{"text": "QUILLFEATHER PaperTrading - PA3", "shown": True}]},
                  {"switcher": [{"text": "QUILLFEATHER paper_account - PA3", "shown": True}]},
                  {"switcher": [{"text": "QUILLFEATHER LLC - PA3 (PAPER)", "shown": True}]},
                  {"switcher": [{"text": "", "shown": True}]},
                  {"switcher": [{"text": LIVE, "shown": False}]},
                  {"switcher": []},
                  {"switcher": [{"text": LIVE, "shown": True}, {"text": LIVE, "shown": True}]},
                  {"switcher": [{"text": LIVE, "shown": True}], "banner": True}):
        with pytest.raises(site.NotLive):
            site.check_account(state)


def test_a_paper_account_is_refused_before_anything_is_read():
    page = Center()
    page.switcher = [{"text": PAPER, "shown": True}]
    with pytest.raises(site.NotLive):
        site.collect_download_docs(page, run())
    assert page.presses == [] and page.emitted == []


def test_an_unreadable_switcher_is_refused():
    page = Center()
    page.switcher = [{"text": "", "shown": True}]
    with pytest.raises(site.NotLive):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_the_paper_redirect_to_the_dashboard_is_refused():
    page = Center()
    page.paper_redirect = True
    with pytest.raises(site.NotLive):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_switch_to_paper_between_pages_stops_before_the_next_press():
    page = Center()
    site._open(page, run())

    def flip(p, loc):
        p.switcher = [{"text": PAPER, "shown": True}]
    page.on_press = flip
    with pytest.raises(site.NotLive):
        site.collect_download_docs(page, run())
    assert len(pressed_next(page)) == 1 and pressed_downloads(page) == []


def test_the_switcher_text_is_private_once_read():
    site._read(Center())
    words = " ".join(site.private_words())
    for secret in ("QUILLFEATHER", NUMBER):
        assert secret in words
    assert NUMBER not in site.redact("account " + NUMBER)


# ---------------------------------------------------------------------------
# The list answer
# ---------------------------------------------------------------------------

def test_the_list_is_read_whole_and_sorted_into_kinds():
    listed = site.read_list(Response(LIST_URL, survey_items()))
    assert len(listed.items) == 28 and len(listed.kept) == 15
    assert listed.counts == {"twins": 12, "applications": 1, "tax": 0, "other": 0, "alike": 0}
    assert (listed.start, listed.end) == ("2023-10-12", "2026-10-12")
    more = survey_items() + [item(900, "2026-01-31", "tax_1099_b"), item(901, "2026-02-01", "fee_notice")]
    listed = site.read_list(Response(LIST_URL, more))
    assert listed.counts["tax"] == 1 and listed.counts["other"] == 1 and len(listed.kept) == 15
    assert ACCT in site.private_words() and uid(105) in site.private_words()


@pytest.mark.parametrize("change", [
    lambda d: d.append(dict(d[0])),                                    # one id twice
    lambda d: d[0].update(id="not-a-uuid"),
    lambda d: d[0].update(date="2026-02-30"),
    lambda d: d[0].update(date="09/30/2026"),
    lambda d: d[0].update(type="Account Statement"),
    lambda d: d[0].update(name=5),
    lambda d: d.append("x"),
])
def test_a_list_this_cannot_read_whole_stops(change):
    data = survey_items()
    change(data)
    with pytest.raises(site.ListStopped):
        site.read_list(Response(LIST_URL, data))


@pytest.mark.parametrize("extra, gone", [
    (item(999, "2026-09-30", "account_statement"), uid(2)),   # two statements, one date
    (item(998, "2026-09-01", "trade_confirmation"), uid(100)),  # two confirmations, one date
])
def test_two_kept_documents_alike_are_counted_and_the_rest_kept(extra, gone):
    """A pair of one type and one date, equity and crypto confirmations of
    one day, say, is counted and not kept, and the rest of the list goes
    on. The pair stays in the list's items, so its rows are still checked."""
    listed = site.read_list(Response(LIST_URL, survey_items() + [extra]))
    assert listed.counts["alike"] == 2 and len(listed.kept) == 14
    kept = {i.document_id for i in listed.kept}
    assert gone not in kept and extra["id"] not in kept
    assert extra["id"] in {i.document_id for i in listed.items}


def test_a_pair_alike_is_counted_in_the_run_summary_and_the_panels_result(tmp_path, capsys):
    """The pair left unsaved is said in the run summary and in the result
    the panel reads, not only on the console."""
    app = make_app(tmp_path, "--all")
    page = Center()
    page.items.append(item(998, "2026-09-06", "trade_confirmation"))
    attach(app, page)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover(quiet=True)
    assert app.stats["alike"] == 2
    app.stats["mode"] = "all"
    app.write_run_summary()
    summary = app.paths.run_summary.read_text(encoding="utf-8")
    assert re.search(r"Left unsaved, alike: +2$", summary, re.M)
    (result,) = [json.loads(x.split(" ", 1)[1]) for x in capsys.readouterr().out.splitlines()
                 if x.startswith("PAPERPULL_RUN_RESULT ")]
    assert result["alike"] == 2


def test_a_pair_alike_leaves_the_rest_of_discovery_flowing():
    page = Center()
    page.items.append(item(998, "2026-09-06", "trade_confirmation"))
    r = run()
    got = site.collect_download_docs(page, r)
    assert len(got) == 14 and r.counts["alike"] == 2
    assert uid(105) not in {d.document_id for d in got} and pressed_downloads(page) == []


# ---------------------------------------------------------------------------
# The list's window
# ---------------------------------------------------------------------------

def listed_with(items, url=LIST_URL):
    return site.read_list(Response(url, items))


def test_a_list_holding_the_application_in_its_window_is_whole():
    assert site.reaches_back(listed_with(survey_items()), None, TODAY)


@pytest.mark.parametrize("floor, whole", [
    ("2023-10-12", True), ("2024-01-01", True), ("2023-10-11", False), (None, False),
    ("", False), ("2024", False), ("2024-02-30", False),
])
def test_a_list_without_the_application_is_whole_only_back_to_the_runs_start(floor, whole):
    items = [i for i in survey_items() if i["type"] != "account_application"]
    assert site.reaches_back(listed_with(items), floor, TODAY) is whole


def test_an_application_outside_the_window_does_not_count():
    items = [i for i in survey_items() if i["type"] != "account_application"]
    items.append(item(4, "2023-10-11", "account_application"))
    assert not site.reaches_back(listed_with(items), None, TODAY)


WINDOW = "start=2023-10-12&end=2026-10-12"


@pytest.mark.parametrize("window, whole", [
    ("start=2023-10-12&end=2026-10-12", True),    # ends yesterday
    ("start=2023-10-12&end=2026-10-13", True),    # ends today
    ("start=2023-10-12&end=2026-10-11", False),   # ended the day before yesterday
    ("start=2023-10-12&end=2025-01-01", False),   # ended well before today
    ("start=2026-10-13&end=2026-10-12", False),   # starts after it ends
    ("start=2026-10-12&end=2026-10-12", True),    # one day, yesterday
])
def test_a_window_is_whole_only_from_its_start_to_yesterday_or_later(window, whole):
    """With the application in it, and again with only a start date of the
    run's own, a window that starts after it ends or ended before
    yesterday is never called whole."""
    url = LIST_URL.replace(WINDOW, window)
    holds = [i for i in survey_items() if i["date"] >= window[6:16] and i["type"] != "account_application"]
    holds.append(item(4, window[6:16], "account_application"))
    assert site.reaches_back(listed_with(holds, url), None, TODAY) is whole
    items = [i for i in holds if i["type"] != "account_application"]
    assert site.reaches_back(listed_with(items, url), window[6:16], TODAY) is whole


def test_a_window_that_is_not_whole_stops_discovery_in_its_own_words(tmp_path):
    """The list holds the application, so the stop says the window is wrong,
    never that the application is missing or that a start date would help."""
    app = make_app(tmp_path, "--discover")
    page = Center()
    page.list_url = LIST_URL.replace("end=2026-10-12", "end=2026-10-01")
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    out = said.getvalue()
    assert "window" in out and "application" not in out and "start-date" not in out
    assert app.discovery.data == {} and page.presses == []


def test_a_document_older_than_the_earliest_application_is_not_whole():
    """An application reissued inside the window would let older
    statements pass, so nothing listed may be dated before the earliest
    application. A start date of the run's own still reaches back."""
    items = survey_items() + [item(5, "2026-08-01", "account_statement")]
    assert not site.reaches_back(listed_with(items), None, TODAY)
    assert site.reaches_back(listed_with(items), "2023-10-12", TODAY)
    items.append(item(6, "2026-07-01", "account_application"))
    assert site.reaches_back(listed_with(items), None, TODAY)
    items.append(item(7, "2026-08-01", "account_statement"))   # a second, same day as the first
    items.append(item(8, "2026-06-30", "trade_confirmation"))
    assert not site.reaches_back(listed_with(items), None, TODAY)


def test_a_list_too_short_stops_discovery_before_any_press():
    page = Center()
    page.items = [i for i in page.items if i["type"] != "account_application"]
    with pytest.raises(site.ListTooShort) as stop:
        site.collect_download_docs(page, run(floor=None))
    assert stop.value.start == "2023-10-12" and page.presses == []
    assert len(site.collect_download_docs(Center(items=page.items), run("2024-01-01"))) == 15


def test_a_list_answer_that_is_not_the_lists_json_is_a_signed_out_session():
    for resp in (Response(LIST_URL, None, status=401), Response(LIST_URL, None, status=403),
                 Response(LIST_URL, None, raw="<html>sign in</html>"),
                 Response(LIST_URL, {"message": "unauthorized"})):
        with pytest.raises(site.SessionExpired):
            site.read_list(resp)
    with pytest.raises(site.ListStopped):
        site.read_list(Response(LIST_URL, [], status=500))


@pytest.mark.parametrize("answers", [0, 2])
def test_not_one_list_answer_stops_the_list(answers):
    page = Center()
    page.list_answers = answers
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert page.presses == []


# ---------------------------------------------------------------------------
# The rows, across pages
# ---------------------------------------------------------------------------

def test_discovery_reads_every_page_and_keeps_three_kinds():
    page = Center()
    got = site.collect_download_docs(page, run())
    assert len(got) == 15
    assert {d.title for d in got} == {"Brokerage Statement", "Crypto Statement", "Trade Confirmation"}
    assert all(d.href == "" and site.UUID_RE.fullmatch(d.document_id) for d in got)
    assert len(pressed_next(page)) == 2 and pressed_downloads(page) == []
    assert {page.buttons()[i][0] for _c, i in pressed_next(page)} == {"Next"}


def test_rows_the_list_does_not_hold_after_its_last_row_stop_the_list():
    """Ten listed documents fill the first page, and an eleventh row the
    list does not hold sits on a second page. The list is read to the page
    with no Next on, so that row is seen."""
    items = [item(100 + k, "2026-09-%02d" % (k + 1), "trade_confirmation") for k in range(10)]
    page = Center(items=items)
    page.rows = [(i["date"], i["type"], i["id"]) for i in items] + [
        ("2026-09-20", "trade_confirmation", uid(150))]
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert len(pressed_next(page)) == 1


def test_ten_listed_rows_on_one_page_with_next_off_are_the_whole_list():
    items = [item(100 + k, "2026-09-%02d" % (k + 1), "trade_confirmation") for k in range(10)]
    page = Center(items=items)
    assert len(site.collect_download_docs(page, run())) == 10
    assert pressed_next(page) == []


def a_late_list_answer(page, loc):
    """The page answers its list a second time, after the settle, while the
    rows are being paged."""
    if loc.css == "button":
        page._emit(Response(LIST_URL, page.items))


def test_a_list_answer_that_comes_late_while_paging_stops_the_list():
    page = Center()
    page.on_press = a_late_list_answer
    with pytest.raises(site.ListStopped, match="list answers came"):
        site.collect_download_docs(page, run())
    assert page.listeners["response"] == []


def test_a_list_answer_that_comes_late_on_the_way_to_a_row_presses_no_download(tmp_path):
    """The list read again on the way to a row is the list every later
    document reads, so a list that stops there stops the run."""
    page = Center()
    page.on_press = a_late_list_answer
    out = tmp_path / "out.pdf"
    with pytest.raises(site.ListStopped, match="list answers came"):
        take(page, tmp_path)
    assert not out.exists() and pressed_downloads(page) == []
    assert page.listeners == {"response": [], "download": []}


def test_rows_in_another_order_than_the_list_are_fine():
    page = Center()
    page.rows = list(reversed(page.drawn()))
    assert len(site.collect_download_docs(page, run())) == 15


def test_a_twin_drawn_with_its_pdfs_label_stops_the_list():
    """A JSON twin drawn with the same type as its PDF would leave two
    rows that read alike, so the drawn rows are not the list's."""
    page = Center()
    rows = page.drawn()
    rows[5] = (rows[5][0], "trade_confirmation", rows[5][2])
    page.rows = rows
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())


@pytest.mark.parametrize("edit", [
    lambda rows: rows.append(rows[0]),             # one row twice
    lambda rows: rows.pop(7),                      # one row missing
    lambda rows: rows.__setitem__(3, ("2026-08-16", rows[3][1], rows[3][2])),  # another date
])
def test_rows_that_differ_from_the_list_stop_it(edit):
    page = Center()
    rows = page.drawn()
    edit(rows)
    page.rows = rows
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert pressed_downloads(page) == []


def test_a_next_that_does_not_turn_the_page_stops():
    page = Center()
    page.next_turns = False
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert len(pressed_next(page)) == 1


def test_a_next_turned_off_while_rows_are_missing_stops():
    page = Center()
    page.next_disabled_always = True
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_page_seen_twice_stops():
    page = Center()
    original = page.click

    def back_to_first(loc):
        original(loc)
        if page.page == 2:
            page.page = 0
    page.click = back_to_first
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page, run())


def turned_off(which):
    """A press the core finds turned off on the page: `which` is "button"
    for the list's Next, anything else for a row's Download."""
    def press(page, loc):
        if (loc.css == "button") == (which == "button"):
            page.presses.pop()
            raise site.pressing.TurnedOff("press a control", "the control is turned off",
                                          ["The control is turned off, so it was not pressed."])
    return press


def test_a_next_the_page_turned_off_stops_the_list():
    page = Center()
    page.on_press = turned_off("button")
    with pytest.raises(site.ListStopped, match="turned off"):
        site.collect_download_docs(page, run())
    assert page.presses == []


def test_a_next_turned_off_on_the_way_to_a_row_presses_no_download(tmp_path):
    page = Center()
    page.on_press = turned_off("button")
    with pytest.raises(site.ListStopped, match="turned off"):
        take(page, tmp_path)
    assert not (tmp_path / "out.pdf").exists() and page.presses == []


def test_a_download_the_page_turned_off_leaves_the_document(tmp_path):
    page = Center()
    page.on_press = turned_off("download")
    trace = []
    r = run()
    with pytest.raises(site.DocumentTurnedOff):
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", trace=trace, r=r)
    assert pressed_downloads(page) == [] and page.downloads == []
    assert not (tmp_path / "out.pdf").exists() and list((tmp_path / "dl").iterdir()) == []
    assert page.listeners["response"] == []
    r.close()
    assert page.listeners == {"response": [], "download": []}
    assert any("left for the next run" in t.get("note", "") for t in trace)


def test_a_press_with_no_word_on_a_turned_off_control_is_refused():
    page = Center()
    site._open(page, run())
    with pytest.raises(site.ListStopped, match="no word"):
        site._press(page, run(), page.locator("button").nth(5), css="button", what="x",
                    guard=site.is_next_control, step="turn the list's page", off="")
    assert page.presses == []


def test_an_empty_list_reads_as_no_documents():
    page = Center(items=[])
    assert site.collect_download_docs(page, run()) == []
    assert page.presses == []


def test_an_empty_list_with_a_next_to_press_stops_the_list():
    """An empty first page whose Next is on may hide rows on later pages,
    so an empty list is whole only when there is no Next to press."""
    page = Center(items=[])
    page.pages = lambda: 2
    with pytest.raises(site.ListStopped, match="empty list"):
        site.collect_download_docs(page, run())
    assert page.presses == []


# ---------------------------------------------------------------------------
# Signed out
# ---------------------------------------------------------------------------

def test_the_sign_in_page_is_session_expired():
    page = Center()
    page.login_on_goto = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


def test_a_password_field_is_session_expired():
    page = Center()
    page.password = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_list_is_session_expired(status):
    page = Center()
    page.list_status = status
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())


def test_a_sign_out_after_a_press_is_session_expired():
    page = Center()

    def out(p, loc):
        p.url = BASE + "/account/login"
    page.on_press = out
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page, run())
    assert len(page.presses) == 1


def test_listeners_are_taken_off_whatever_happens():
    for setup in (lambda p: setattr(p, "list_status", 401), lambda p: setattr(p, "list_answers", 2),
                  lambda p: None):
        page = Center()
        setup(page)
        try:
            site.collect_download_docs(page, run())
        except (site.SessionExpired, site.ListStopped):
            pass
        assert page.listeners["response"] == [] and page.listeners["download"] == []


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def take(page, tmp_path, n=105, day="2026-09-06", kind="trade_confirmation", trace=None, r=None):
    out = tmp_path / "out.pdf"
    dl = tmp_path / "dl"
    dl.mkdir(exist_ok=True)
    got = site.download_document(page, r or run(), dl, out, document_id=uid(n), iso_date=day,
                                 doc_type=kind, trace=trace if trace is not None else [])
    return got, out


def test_a_document_is_taken_through_its_own_row_on_its_own_page(tmp_path):
    page = Center()
    r = run()
    got, out = take(page, tmp_path, r=r)
    assert got and out.read_bytes()[:5] == b"%PDF-"
    assert len(pressed_next(page)) == 1, "the row is on the second page"
    (css, _i), = pressed_downloads(page)
    n = int(re.search(r"nth-of-type\((\d+)\)", css).group(1))
    assert page.page_rows()[n - 1][2] == uid(105)
    assert list((tmp_path / "dl").iterdir()) == []
    assert page.listeners["response"] == []
    # The run hears the tab's downloads until it closes, and the one taken
    # is no stray.
    assert len(page.listeners["download"]) == 1 and r.unbound == 0
    assert r.close() == 0 and page.listeners["download"] == []
    assert not page.downloads[0].canceled


def test_a_statement_on_the_first_page_presses_no_next(tmp_path):
    page = Center()
    got, _out = take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement")
    assert got and pressed_next(page) == [] and len(pressed_downloads(page)) == 1


def test_binding_needs_one_listed_document_with_the_records_id():
    items = [site.Item(uid(1), "2026-09-30", "account_statement"),
             site.Item(uid(2), "2026-09-30", "crypto_account_statement")]
    assert site.bind(items, uid(1), "2026-09-30", "account_statement")
    assert not site.bind(items, uid(9), "2026-09-30", "account_statement"), "another id"
    assert not site.bind(items + [site.Item(uid(3), "2026-09-30", "account_statement")],
                         uid(1), "2026-09-30", "account_statement"), "two of one date and type"


def test_two_rows_that_read_alike_press_nothing(tmp_path):
    page = Center()
    rows = page.drawn()
    rows.insert(1, rows[0])
    page.rows = rows
    got, out = take(page, tmp_path, n=1, day="2026-08-31", kind="account_statement")
    assert not got and not out.exists() and pressed_downloads(page) == []


def test_a_missing_row_presses_nothing(tmp_path):
    page = Center()
    page.rows = [r for r in page.drawn() if r[2] != uid(105)]
    got, out = take(page, tmp_path)
    assert not got and not out.exists() and pressed_downloads(page) == []


def test_a_document_gone_from_the_list_presses_nothing(tmp_path):
    page = Center()
    page.items = [i for i in page.items if i["id"] != uid(105)]
    got, _out = take(page, tmp_path)
    assert not got and page.presses == []


def test_two_confirmations_on_one_date_press_nothing(tmp_path):
    page = Center()
    page.items.append(item(998, "2026-09-06", "trade_confirmation"))
    got, _out = take(page, tmp_path)
    assert not got and page.presses == []


def test_a_record_that_names_no_document_presses_nothing(tmp_path):
    page = Center()
    for kw in ({"n": 105, "kind": "trade_confirmation_json"}, {"n": 105, "day": "2026-09-31"},
               {"n": 105, "kind": "account_application"}):
        got, _out = take(page, tmp_path, **kw)
        assert not got
    assert page.presses == [] and page.emitted == []


def bad_link(body, status=200, path_id=None):
    def make(doc_id):
        return Response(BASE + "/api/v1/accounts/%s/documents/%s/url" % (ACCT, path_id or doc_id),
                        body(doc_id), status=status)
    return make


@pytest.mark.parametrize("change, reason", [
    ({"downloads_per_press": 2}, "more than one download came"),
    ({"downloads_per_press": 0}, "no download came"),
    ({"download_body": b"<html>%s</html>" % NUMBER.encode()}, "the download was not a pdf"),
    ({"download_url": "https://evil.test/x.pdf"}, "the download came from elsewhere"),
    ({"link_answers": 2}, "not one document link was asked for"),
    ({"link_override": bad_link(lambda i: {"id": uid(1), "url": link_for(i)})},
     "the link answer named another document"),
    ({"link_override": bad_link(lambda i: {"id": i, "url": link_for(i, bucket="other.bucket")})},
     "the link was not alpaca's bucket"),
    ({"link_override": bad_link(lambda i: {"id": i, "url": link_for(i).replace("https", "http", 1)})},
     "the link was not alpaca's bucket"),
    ({"link_override": bad_link(lambda i: {"id": i, "url": link_for(i)}, status=500)},
     "the link was not handed over"),
])
def test_a_download_that_is_not_one_pdf_from_its_link_stops_the_run(tmp_path, change, reason):
    page = Center()
    for k, v in change.items():
        setattr(page, k, v)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == reason
    assert not (tmp_path / "out.pdf").exists()
    assert len(pressed_downloads(page)) == 1, "pressed once, never again"


def test_a_link_for_another_document_never_answers_the_press(tmp_path):
    page = Center()
    page.link_override = bad_link(lambda i: {"id": i, "url": link_for(i)}, path_id=uid(1))
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason in ("no download came", "not one document link was asked for",
                                 "the link was for another document")


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_link_is_session_expired(tmp_path, status):
    page = Center()
    page.link_status = status
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path)


def test_a_link_answer_that_is_not_json_is_session_expired(tmp_path):
    page = Center()
    page.link_override = lambda i: Response(
        BASE + "/api/v1/accounts/%s/documents/%s/url" % (ACCT, i), None, raw="<html>")
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path)


def test_a_download_pending_before_the_press_stops_the_run(tmp_path):
    page = Center()
    (tmp_path / "dl").mkdir()
    (tmp_path / "dl" / "x.pdf.crdownload").write_bytes(b"")
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path)
    assert stop.value.reason == "a download was pending"
    assert pressed_downloads(page) == []


def test_a_download_from_a_blob_the_page_made_is_never_taken(tmp_path):
    """A blob is not the link Alpaca handed over, so it is not the press's
    download: nothing is saved, the run stops, and it is left as it is."""
    page = Center()
    page.download_url = "blob:%s/0f0f0f0f" % BASE
    r = run()
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, r=r)
    assert stop.value.reason == "the download came from elsewhere"
    assert not (tmp_path / "out.pdf").exists()
    assert not any(d.canceled or d.deleted for d in page.downloads) and r.unbound == 1


def test_a_list_answer_between_finding_the_row_and_its_press_presses_nothing(tmp_path,
                                                                             monkeypatch):
    """The list's listener stays armed from the opening to the press, so a
    replacement list answer that comes after the row was found, and could
    make the row another document's, stops it before Download."""
    page = Center()
    real = site._snapshot

    def answer_again(dl_dir):
        page._emit(Response(LIST_URL, page.items))
        return real(dl_dir)
    monkeypatch.setattr(site, "_snapshot", answer_again)
    with pytest.raises(site.ListStopped):
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement")
    assert not (tmp_path / "out.pdf").exists() and pressed_downloads(page) == []
    assert page.listeners["response"] == []


def unrelated(tmp_path):
    return tmp_path / "dl" / "someone else's download.pdf"


def test_a_refusal_before_any_press_leaves_an_unrelated_file_alone(tmp_path, monkeypatch):
    """Nothing was pressed, so a file that reached the folder meanwhile is
    not this document's and stays."""
    page = Center()
    (tmp_path / "dl").mkdir()

    def labels(locator):
        unrelated(tmp_path).write_bytes(b"%PDF-1.4 not alpaca's")
        return ["Sign out"]
    monkeypatch.setattr(site, "_labels_of", labels)
    with pytest.raises(site.ListStopped, match="guard refused"):
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement")
    assert pressed_downloads(page) == []
    assert unrelated(tmp_path).exists()


def test_a_turned_off_download_leaves_an_unrelated_file_alone(tmp_path):
    page = Center()
    (tmp_path / "dl").mkdir()
    off = turned_off("download")

    def write_then_off(p, loc):
        unrelated(tmp_path).write_bytes(b"%PDF-1.4 not alpaca's")
        off(p, loc)
    page.on_press = write_then_off
    with pytest.raises(site.DocumentTurnedOff):
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement")
    assert unrelated(tmp_path).exists()


def test_the_only_download_from_another_address_is_left_and_the_run_stops(tmp_path):
    """The one download in the press's window did not come from the link
    Alpaca handed the press, so it is not the press's own: it is counted,
    never canceled, discarded or deleted, the file it wrote stays, nothing
    is saved, and the run stops."""
    page = Center()
    page.download_url = "https://downloads.example.test/their-own.pdf"
    (tmp_path / "dl").mkdir()

    def lands(p, loc):
        if loc.css != "button":
            (tmp_path / "dl" / ("%s.pdf" % NUMBER)).write_bytes(PDF)
    page.on_press = lands
    r = run()
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", r=r)
    assert stop.value.reason == "the download came from elsewhere"
    assert not (tmp_path / "out.pdf").exists()
    (theirs,) = page.downloads
    assert not theirs.canceled and not theirs.deleted and r.unbound == 1
    assert [p.name for p in (tmp_path / "dl").iterdir()] == ["%s.pdf" % NUMBER]
    assert r.close() == 0 and (tmp_path / "dl" / ("%s.pdf" % NUMBER)).exists()


def test_a_download_from_the_handed_over_link_that_is_refused_is_discarded(tmp_path):
    """From exactly the link Alpaca handed the press, so it is the press's
    own. It is not a PDF, so it is refused, canceled and its copy deleted."""
    page = Center()
    page.download_body = b"<html>not a pdf</html>"
    r = run()
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", r=r)
    assert stop.value.reason == "the download was not a pdf"
    (ours,) = page.downloads
    assert ours.canceled and ours.deleted and r.unbound == 0
    assert not (tmp_path / "out.pdf").exists()


def emit_download(page, dl):
    for f in list(page.listeners["download"]):
        f(dl)


def test_a_download_outside_every_press_window_is_left_as_it_is(tmp_path):
    """A download on the run's tab that no press of the run's made, the
    person's own say, is counted and never canceled, discarded or deleted,
    even with Alpaca's name and a statement's bytes, and the run's end
    touches nothing."""
    page = Center()
    r = run()
    dl = tmp_path / ".alpaca-downloads"
    dl.mkdir()
    r.watch(page, dl)
    r.before = site._snapshot(dl)
    theirs = Download(link_for(uid(2)), PDF)
    emit_download(page, theirs)
    (dl / ("%s.pdf" % NUMBER)).write_bytes(PDF)
    assert r.unbound == 1
    assert r.close() == 0
    assert not theirs.canceled and not theirs.deleted
    assert [p.name for p in dl.iterdir()] == ["%s.pdf" % NUMBER]
    assert page.listeners["download"] == []


def test_a_download_between_captures_is_left_as_it_is(tmp_path):
    page = Center()
    r = run()
    got, _out = take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", r=r)
    assert got
    theirs = Download(link_for(uid(1)), PDF)
    emit_download(page, theirs)
    (tmp_path / "dl" / "their own.pdf").write_bytes(PDF)
    got, _out = take(page, tmp_path, n=1, day="2026-08-31", kind="account_statement", r=r)
    assert got and r.unbound == 1 and not theirs.canceled and not theirs.deleted
    assert (tmp_path / "dl" / "their own.pdf").exists()


def test_two_downloads_in_one_press_window_stop_the_run_and_touch_neither(tmp_path):
    page = Center()
    page.downloads_per_press = 2
    (tmp_path / "dl").mkdir()

    def lands(p, loc):
        if loc.css != "button":
            (tmp_path / "dl" / ("%s.pdf" % NUMBER)).write_bytes(PDF)
    page.on_press = lands
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement")
    assert stop.value.reason == "more than one download came"
    assert not (tmp_path / "out.pdf").exists()
    assert len(page.downloads) == 2
    assert not any(d.canceled or d.deleted for d in page.downloads)
    assert (tmp_path / "dl" / ("%s.pdf" % NUMBER)).exists()


def test_a_late_download_from_the_owed_link_is_discarded_at_the_run_end(tmp_path):
    """The press got no download in its window, and Alpaca had handed it
    its link. A download from exactly that link by the run's end is that
    press's, and is discarded. One from anywhere else is left as it is."""
    page = Center()
    page.downloads_per_press = 0
    r = run()
    waits = []
    page.wait_for_timeout = lambda ms: waits.append(ms)
    with pytest.raises(site.pressing.Stop) as stop:
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", r=r)
    assert stop.value.reason == "no download came"
    assert r.owed_link == link_for(uid(2))
    theirs = Download("https://downloads.example.test/their-own.pdf", PDF)
    late = Download(link_for(uid(2)), PDF)

    def both_come_while_the_end_waits(ms):
        waits.append(ms)
        emit_download(page, theirs)
        emit_download(page, late)
        (tmp_path / "dl" / ("%s.pdf" % NUMBER)).write_bytes(PDF)
        (tmp_path / "dl" / "their own.pdf").write_bytes(b"%PDF-1.4 not a statement")
    waits.clear()
    page.wait_for_timeout = both_come_while_the_end_waits
    assert r.close() == 1
    assert waits == [site.LATE_DOWNLOAD_WAIT_MS]
    assert late.canceled and late.deleted
    assert not theirs.canceled and not theirs.deleted and r.unbound == 1
    assert [p.name for p in (tmp_path / "dl").iterdir()] == ["their own.pdf"]


def test_a_press_that_got_no_link_owes_nothing_and_the_run_end_does_not_wait(tmp_path):
    page = Center()
    page.downloads_per_press = 0
    page.link_answers = 0
    r = run()
    waits = []
    page.wait_for_timeout = lambda ms: waits.append(ms)
    with pytest.raises(site.pressing.Stop):
        take(page, tmp_path, n=2, day="2026-09-30", kind="account_statement", r=r)
    assert r.owed_link is None
    waits.clear()
    r.close()
    assert waits == []


def test_the_link_and_the_downloads_name_are_private_once_seen(tmp_path):
    page = Center()
    take(page, tmp_path)
    words = site.private_words()
    assert NUMBER in words and NUMBER + ".pdf" in words


# ---------------------------------------------------------------------------
# The run's deadline
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_the_deadline_counts_from_the_first_navigation():
    clock = Clock()
    r = site.Run(clock=clock)
    assert not r.past_deadline()
    clock.t += 60 * 60
    assert not r.past_deadline(), "nothing opened yet"
    r.navigated()
    clock.t += site.DEADLINE_S - 1
    r.navigated()
    assert not r.past_deadline()
    clock.t += 1
    assert r.past_deadline()


def test_nothing_is_pressed_past_the_deadline():
    clock = Clock()
    r = site.Run(clock=clock)
    page = Center()
    original = page.goto

    def late(url, **kw):
        original(url, **kw)
        clock.t += site.DEADLINE_S
    page.goto = late
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(page, r)
    assert page.presses == []


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------

def make_app(tmp, *args, **extra):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "min_pdf_bytes": 100, "delay_min_seconds": 0, "delay_max_seconds": 0})
    config.update(extra)
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    app = docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))
    app.run = run()
    app._dl_dir = Path(tmp) / "out" / ".alpaca-downloads"
    app._dl_dir.mkdir(parents=True, exist_ok=True)
    return app


def attach(app, page):
    page.url = site.DOCUMENTS_URL
    app.page = lambda: page
    app._delay = lambda *a, **k: None


def test_the_tab_is_let_go_even_when_saving_the_run_fails(monkeypatch):
    """main() closes the app, which sweeps the run's downloads and stops
    its listener, whatever saving the records or the summary does."""
    closed = []

    class Store:
        def save(self, leaving=False):
            pass

    class Stub:
        def __init__(self, args):
            self.stats = {"mode": "all"}
            self.progress = self.discovery = Store()

        def cmd_run(self, mode):
            pass

        def write_run_summary(self):
            raise OSError("the disk is full")

        def close(self):
            closed.append(True)
    monkeypatch.setattr(docs, "App", Stub)
    with pytest.raises(OSError):
        docs.main(["--all"])
    assert closed == [True]


def test_config_example():
    config = json.loads((HERE / "config.example.json").read_text())
    assert config["cdp_url"].endswith(":9292") and config["pilot_count"] == 1
    assert config["owner"] == "" and config["output_dir"] == "."


def test_records_name_the_kind_and_never_an_id(tmp_path):
    app = make_app(tmp_path, "--discover")
    attach(app, Center())
    with redirect_stdout(io.StringIO()) as said:
        app.cmd_discover()
    recs = list(app.discovery.data.values())
    assert len(recs) == 15
    assert {r["summary"] for r in recs} == {"Brokerage Statement", "Crypto Statement", "Trade Confirmation"}
    for rec in recs:
        assert rec["href"] == "" and "?" not in rec["source_url"]
        name = docs.build_pdf_filename(rec["date"], rec["summary"], "", record=rec)
        assert rec["document_id"] not in name
    assert "JSON copies of trade confirmations: 12" in said.getvalue()
    assert "account applications: 1" in said.getvalue()


def test_the_pilot_takes_one_brokerage_statement(tmp_path):
    app = make_app(tmp_path, "--pilot")
    attach(app, Center())
    app.check_session = lambda p: None
    with redirect_stdout(io.StringIO()):
        app.cmd_pilot()
    from paperpull_core.models import State
    done = [r for r in app.progress.data.values() if r.get("state") == State.COMPLETED.value]
    assert len(done) == 1 and done[0]["doc_type"] == "account_statement"
    assert done[0]["date"] == "2026-09-30"


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


def discovered(tmp_path, *args):
    app = make_app(tmp_path, *args)
    attach(app, Center())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    return app


@pytest.mark.parametrize("trouble", [
    lambda p: setattr(p, "login_on_goto", True),
    lambda p: setattr(p, "list_status", 401),
    lambda p: setattr(p, "link_status", 403),
    lambda p: setattr(p, "password", True),
])
def test_an_expired_session_stops_the_run_and_records_nothing(tmp_path, trouble):
    app = discovered(tmp_path, "--all")
    page = Center()
    trouble(page)
    attach(app, page)
    app.check_session = lambda p: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.process(app._select())
    assert "signed out" in said.getvalue()
    assert app.progress.data == {}
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_a_turned_off_download_is_left_for_the_next_run_and_the_run_goes_on(tmp_path):
    app = discovered(tmp_path, "--all")
    page = Center()
    first = []

    def off_once(p, loc):
        if loc.css != "button" and not first:
            first.append(loc.css)
            turned_off("download")(p, loc)
    page.on_press = off_once
    attach(app, page)
    app.check_session = lambda p: None
    with everything_said() as seen:
        app.process(app._select())
    from paperpull_core.models import State
    states = [r.get("state") for r in app.progress.data.values()]
    assert app.stats["left_for_next_run"] == 1
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert states.count(State.COMPLETED.value) == 14 and len(states) == 14
    assert "left for the next run" in seen.getvalue()
    assert not list(app.paths.diagnostics.glob("*failure*"))
    assert not list(app.paths.diagnostics.glob("download-attempt*"))
    assert_private(seen.getvalue() + written(app))


def test_an_expired_session_during_discovery_stops_the_run(tmp_path):
    app = make_app(tmp_path, "--discover")
    page = Center()
    page.list_status = 401
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert app.discovery.data == {}
    assert "signed out" in said.getvalue() and "Press Enter" not in said.getvalue()
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_a_sign_out_while_paging_stops_discovery_with_no_failure_file(tmp_path):
    app = make_app(tmp_path, "--discover")
    page = Center()
    page.on_press = lambda p, loc: setattr(p, "url", BASE + "/account/login")
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "signed out" in said.getvalue()
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_a_paper_account_stops_the_run_and_records_nothing(tmp_path):
    app = discovered(tmp_path, "--all")
    page = Center()
    page.switcher = [{"text": PAPER, "shown": True}]
    attach(app, page)
    app.check_session = lambda p: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.process(app._select())
    assert "Live account" in said.getvalue()
    assert app.progress.data == {} and page.presses == []
    assert not list(app.paths.diagnostics.glob("*failure*"))


def test_a_paper_account_stops_discovery(tmp_path):
    app = make_app(tmp_path, "--discover")
    page = Center()
    page.paper_redirect = True
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "Live account" in said.getvalue() and app.discovery.data == {}


@pytest.mark.parametrize("args, extra", [
    (("--discover", "--start-date", "2024-02-30"), {}),
    (("--discover", "--end-date", "2024-13-01"), {}),
    (("--discover",), {"default_start_date": "2024-02-30"}),
    (("--discover",), {"default_start_date": "2024"}),
    (("--discover",), {"default_start_date": 20240101}),
])
def test_a_start_date_that_is_not_a_day_is_refused_before_anything(tmp_path, args, extra):
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as end:
        make_app(tmp_path, *args, **extra)
    assert end.value.code == 2 and "YYYY-MM-DD" in said.getvalue()


def test_main_refuses_a_day_that_does_not_exist():
    with redirect_stdout(io.StringIO()):
        assert docs.main(["--discover", "--start-date", "2024-02-30"]) == 2


def no_application():
    page = Center()
    page.items = [i for i in page.items if i["type"] != "account_application"]
    return page


def test_a_list_too_short_stops_discovery_and_says_how_to_go_on(tmp_path):
    app = make_app(tmp_path, "--discover")
    attach(app, no_application())
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "2023-10-12" in said.getvalue() and "default_start_date" in said.getvalue()
    assert app.discovery.data == {} and app.page().presses == []


@pytest.mark.parametrize("args, extra", [
    (("--discover", "--start-date", "2024-01-01"), {}),
    (("--discover",), {"default_start_date": "2023-10-12"}),
])
def test_a_start_date_the_list_reaches_lets_discovery_finish(tmp_path, args, extra):
    app = make_app(tmp_path, *args, **extra)
    attach(app, no_application())
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    assert len(app.discovery.data) == 15


def test_the_deadline_stops_the_run_before_the_next_document(tmp_path):
    app = discovered(tmp_path, "--all")
    clock = Clock()
    app.run = site.Run(clock=clock)
    app.run.navigated()
    clock.t += site.DEADLINE_S
    taken = []
    original = site.download_document
    site.download_document = lambda *a, **k: taken.append(1)
    try:
        with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
            app.process(app._select())
    finally:
        site.download_document = original
    assert taken == [] and app.progress.data == {}
    assert "minutes" in said.getvalue()


def test_the_deadline_reached_while_paging_stops_discovery(tmp_path):
    app = make_app(tmp_path, "--discover")
    clock = Clock()
    app.run = site.Run(clock=clock)
    page = Center()
    original = page.goto

    def late(url, **kw):
        original(url, **kw)
        clock.t += site.DEADLINE_S
    page.goto = late
    attach(app, page)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "minutes" in said.getvalue() and page.presses == []
    assert not list(app.paths.diagnostics.glob("*failure*"))


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
        attach(app, Center())
        app.cmd_discover()
        app.check_session = lambda p: None
        app.process(app._select())
    assert app.stats["statements"] == 15, seen.getvalue()
    names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
    assert len(names) == 15
    assert any("2026-09-30" in n and "Crypto Statement" in n for n in names)
    assert any("2026-09-30" in n and "Brokerage Statement" in n for n in names)
    assert_private(seen.getvalue() + written(app))


LLC = "BRAMBLEWICK HOLDINGS LLC"


@pytest.mark.parametrize("naming", [
    {"owner_in_filename": True},
    {"filename_pattern": "{date:yyyy-mm-dd} {owner} {summary}"},
    {"filename_pattern_statements": "{date:yyyy-mm-dd}[ {owner|provider}] {summary}"},
    {"owner_in_filename": True, "filename_pattern": "[{owner} ]{date:yyyy-mm-dd} {summary}"},
], ids=["owner_in_filename", "pattern", "statements pattern", "both"])
def test_the_account_holders_name_is_in_no_file_name_index_or_log(tmp_path, naming):
    """The holder is often a company, and its name is as private here as
    the account number. Whatever config.json asks, no file name carries it
    and the index's Account Holder column is left blank."""
    with everything_said() as seen:
        app = make_app(tmp_path, "--all", owner=LLC, **naming)
        attach(app, Center())
        app.cmd_discover()
        app.check_session = lambda p: None
        app.process(app._select())
        app.write_run_summary()
    assert app.stats["statements"] == 15
    names = [p.name for p in app.paths.root.rglob("*")]
    assert len([n for n in names if n.endswith(".pdf")]) == 15
    everything = seen.getvalue() + written(app)
    for part in (LLC, "BRAMBLEWICK", "HOLDINGS", "Bramblewick"):
        assert part.lower() not in everything.lower(), part
    rows = app.paths.document_index_csv.read_text(encoding="utf-8-sig").splitlines()
    assert rows and all(r.split(",")[0] in ("Account Holder", "") for r in rows)
    assert "not used" in seen.getvalue()
    assert_private(everything)


def test_the_holders_name_is_found_in_every_spelling_of_a_pattern():
    for pattern in ("{owner}", "[ {owner}] {date}", "{summary|owner}", "[x[ {owner}]] {date}"):
        assert docs._names_owner(pattern), pattern
    for pattern in ("{date} {summary}", "", None, "{owner", "\\{owner\\} {date}"):
        assert not docs._names_owner(pattern), pattern


def test_nothing_private_leaves_on_runs_that_stop(tmp_path):
    app = make_app(tmp_path, "--all")
    traces = []
    with everything_said() as seen:
        attach(app, Center())
        app.cmd_discover()
        app.check_session = lambda p: None
        # A row that is missing: marked for review, nothing pressed.
        bad = Center()
        bad.rows = [r for r in bad.drawn() if r[2] != uid(2)]
        attach(app, bad)
        app.process(app._select(limit=1))
        # A link for another document stops the run.
        worse = Center()
        worse.link_override = bad_link(lambda i: {"id": uid(1), "url": link_for(i)})
        attach(app, worse)
        try:
            app.process(app._select(limit=2))
        except site.pressing.Stop as stop:
            traces.append(" ".join(stop.lines) + str(stop.facts))
            try:
                site.pressing.stop_run(app, stop)
            except SystemExit:
                pass
        # A download that is not a PDF stops the run.
        worst = Center()
        worst.download_body = b"<html>%s %s</html>" % (LIVE.encode(), ACCT.encode())
        attach(app, worst)
        try:
            app.process(app._select(limit=2))
        except site.pressing.Stop as stop:
            traces.append(" ".join(stop.lines) + str(stop.facts))
        # A discovery that stops partway.
        third = Center()
        third.rows = third.drawn()[:-1]
        attach(app, third)
        try:
            app.cmd_discover()
        except SystemExit:
            pass
        trace = []
        take(Center(), tmp_path, n=105, day="2026-09-07", trace=trace)
        traces.append(json.dumps(trace))
    assert app.stats["manual_review"] >= 1
    assert_private(seen.getvalue() + written(app) + " ".join(traces))


# ---------------------------------------------------------------------------
# What the site layer presses, read from its source
# ---------------------------------------------------------------------------

SITE = ast.parse((HERE / "alpaca_site.py").read_text(encoding="utf-8"))
TWO = {"is_download_control", "is_next_control"}


def test_the_site_layer_presses_nothing_itself():
    called = {n.func.attr for n in ast.walk(SITE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for verb in ("dblclick", "tap", "fill", "type", "press", "select_option", "check",
                 "uncheck", "set_input_files", "dispatch_event", "press_sequentially", "hover",
                 "focus", "set_checked", "drag_to", "press_once", "fetch"):
        assert verb not in called, verb
    attrs = {n.attr for n in ast.walk(SITE) if isinstance(n, ast.Attribute)}
    assert not attrs & {"mouse", "keyboard", "touchscreen"}
    # Nothing is asked of Alpaca or the bucket by this app itself: no
    # request client, no fetch. The page asks and this listens.
    asks = [ast.unparse(n) for n in ast.walk(SITE) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr in ("get", "post", "fetch")
            and ast.unparse(n.func.value).endswith(("request", "page", "context"))]
    assert asks == []
    assert not [k for k in ast.walk(SITE) if isinstance(k, ast.keyword) and k.arg == "force"]


def test_the_one_press_is_the_cores_inside_press_and_every_press_names_one_of_two():
    clicks = []
    for fn in [n for n in ast.walk(SITE) if isinstance(n, ast.FunctionDef)]:
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "click":
                clicks.append((fn.name, ast.unparse(c.func.value)))
    assert clicks == [("_press", "pressing")]
    guards = []
    for c in ast.walk(SITE):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_press":
            g = [k.value for k in c.keywords if k.arg == "guard"]
            assert len(g) == 1 and isinstance(g[0], ast.Name), ast.unparse(c)
            guards.append(g[0].id)
    assert sorted(guards) == sorted(TWO)
    assert {g.__name__ for g in site.PRESS_GUARDS} == TWO
    for js in (site._STATE_JS, site._LABELS_JS):
        assert ".click" not in js and "dispatchEvent" not in js and ".submit" not in js
        assert "fetch(" not in js and "localStorage" not in js


def test_the_page_is_only_ever_loaded_at_the_documents_address():
    gotos = [c for c in ast.walk(SITE) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute) and c.func.attr == "goto"]
    assert len(gotos) == 1 and ast.unparse(gotos[0].args[0]) == "DOCUMENTS_URL"
