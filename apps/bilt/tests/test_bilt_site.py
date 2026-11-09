"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only. The made-up wallet below is
a spy: it records every press, every request and every tab, and the tests
read what it recorded."""
import io
import json
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import bilt_site as site  # noqa: E402
import bilt_docs as docs  # noqa: E402
from paperpull_core import pressing  # noqa: E402
from paperpull_core.testkit import sample_pdf, text_pdf  # noqa: E402

API = "https://api.biltrewards.com"
# Invented details, which must never leave through a log, the console, the
# index, a diagnostic, a trace, an exception or a file name.
CARD = "0a1b2c3d-1111-4222-8333-944455556666"
OTHER_CARD = "0a1b2c3d-1111-4222-8333-944455557777"
# Four digits no date or time of day holds, since a run writes its clock
# into names and lines and 00:48:21 would have spelled the old "4821".
LAST4 = "8697"
NAME = "Quentin Wombatson"
MERCHANT = "Zorblax Hardware"
SID1, SID2, SID3 = "stm-90011a", "stm-90012b", "stm-90013c"
TOKEN = "Tq9ZkW77xyzAB"
STATEMENTS = [("2026-10-06", SID1), ("2026-09-06", SID2), ("2026-08-06", SID3)]
PRIVATE = [CARD, OTHER_CARD, LAST4, "Quentin", "Wombatson", SID1, SID2, SID3, TOKEN]


def mdy(iso):
    return f"{iso[5:7]}/{iso[8:10]}/{iso[:4]}"


def statement_pdf(iso, last4=LAST4, extra=()):
    lines = ["Bilt Card Statement", "Statement Closing Date %s" % mdy(iso),
             "Account number ending in %s" % last4, *extra]
    lines += ["Transactions and fees for the period, line %d" % n for n in range(12)]
    return text_pdf(lines)


def pdf_url(iso, token=TOKEN):
    return "https://statements.cardless.com/%s_%s_Bilt.pdf" % (token, iso)


def list_url(card=CARD):
    return f"{API}/bilt-card/cards/{card}/account/statements"


def details_url(sid, card=CARD):
    return f"{API}/bilt-card/cards/{card}/account/statements/{sid}/details"


def words(iso):
    return site.words_date(iso)


# ---------------------------------------------------------------------------
# The made-up wallet
# ---------------------------------------------------------------------------

class Frame:
    def __init__(self, page):
        self.page, self.parent_frame = page, None


class Req:
    def __init__(self, nav=False, method="GET"):
        self.nav, self.method = nav, method

    def is_navigation_request(self):
        return self.nav


class Resp:
    def __init__(self, url, status=200, ctype="application/json", body=b"{}", page=None,
                 nav=False, readable=True):
        self.url, self.status = url, status
        self.headers = {"content-type": ctype}
        self._body, self.readable = body, readable
        self.request = Req(nav)
        self._frame = Frame(page)
        self.frameless = False

    @property
    def frame(self):
        if self.frameless:
            raise AttributeError("a popup's frame Playwright does not know yet")
        return self._frame

    def body(self):
        if not self.readable:
            raise RuntimeError("Network.getResponseBody: No resource with given identifier")
        return self._body

    def dispose(self):
        pass


def list_resp(statements, card=CARD, count=None, page=None, **kw):
    body = {"statements": [{"statementId": sid, "date": d, "downloadUrl": None}
                           for d, sid in statements],
            "count": len(statements) if count is None else count}
    return Resp(list_url(card), body=json.dumps(body).encode(), page=page, **kw)


def paged_resp(**more):
    """The good answer for STATEMENTS, its count its own list, with keys
    that may say there is more of it."""
    body = {"statements": [{"statementId": sid, "date": d, "downloadUrl": None}
                           for d, sid in STATEMENTS], "count": len(STATEMENTS), **more}
    return Resp(list_url(), body=json.dumps(body).encode())


def details_resp(sid, iso, url, card=CARD, page=None, **kw):
    body = {"statementId": sid, "date": iso, "downloadUrl": url}
    return Resp(details_url(sid, card), body=json.dumps(body).encode(), page=page, **kw)


class Request:
    """The browser's request client: only a statement's own PDF address is
    ever asked, and only when its tab's answer could not be read."""

    def __init__(self, wallet):
        self.wallet, self.asked = wallet, []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_redirects")))
        assert url.startswith("https://statements.cardless.com/"), "asked something else"
        return Resp(url, ctype="application/pdf", body=self.wallet.asked_body)

    def post(self, *a, **k):
        raise AssertionError("POST")

    def fetch(self, *a, **k):
        raise AssertionError("fetch")


class Download:
    def __init__(self):
        self.canceled = self.deleted = False

    def cancel(self):
        self.canceled = True

    def delete(self):
        self.deleted = True


class Popup:
    """A tab the statement's button opens. As in Chromium, its navigation
    answer can reach the context before its page is known."""

    def __init__(self, opener, context):
        self._opener, self.context = opener, context
        self.url, self.closed, self.stuck = "about:blank", False, False
        self.listeners = {"download": []}

    def opener(self):
        return self._opener

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def wait_for_load_state(self, *a, **k):
        pass

    def go(self, url, body=None, status=200, readable=True, known=False):
        self.url = url
        r = Resp(url, status, "application/pdf", body or b"", page=self, nav=True, readable=readable)
        r.frameless = not known
        self.context.emit("response", r)

    def is_closed(self):
        return self.closed

    def close(self):
        if not self.stuck:
            self.closed = True


class Context:
    def __init__(self, wallet):
        self.listeners = {"response": [], "page": []}
        self.request = Request(wallet)
        self.pages = [wallet]

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def remove_listener(self, ev, f):
        self.listeners[ev].remove(f)

    def emit(self, ev, x):
        for f in list(self.listeners[ev]):
            f(x)


class Loc:
    def __init__(self, wallet, kind, label=""):
        self.wallet, self.kind, self.label = wallet, kind, label

    def _labels(self):
        return self.wallet.labels_of(self)

    def count(self):
        if self.kind == "password":
            return 1 if self.wallet.password else 0
        if self.kind == "other":
            return 0
        labels = self._labels()
        return 0 if labels is None else self.wallet.copies.get(self.label, 1)

    def is_visible(self):
        return self._labels() is not None

    def filter(self, **kw):
        return self

    def evaluate(self, js):
        assert js == site._LABELS_JS
        return list(self._labels() or [])

    def inner_text(self, **kw):
        return "Recent activity %s $4,321.09 Welcome, %s" % (MERCHANT, NAME)


class Wallet:
    """The wallet page. `statements` are (date, statementId), newest first.
    `popup` says what a statement's button does: "pdf" (a tab holding the
    PDF), "none", "two" (two tabs), "child" (the tab opens one of its own),
    "elsewhere" (a tab on another host), "wrongdate", "download" (a browser
    download as well), "stuck" (a tab that will not close), "late" (a second
    tab after the first is read), "notpdf", "signin"."""

    def __init__(self, statements=STATEMENTS, popup="pdf"):
        self.statements = list(statements)
        self.popup = popup
        self.url = "https://www.bilt.com/rewards/neighborhood"
        self.context = Context(self)
        self.listeners = {"download": []}
        self.time, self.later = 0, []
        self.presses, self.gotos, self.popups, self.downloads, self.waits = [], [], [], [], []
        self.summary_open = self.list_open = False
        self.password = False
        self.copies = {}                 # label -> how many controls carry it
        self.turned_off = set()          # labels the page has turned off
        self.list_answers = None         # callable() -> [Resp], instead of the one good answer
        self.sheet = None                # the dates the sheet draws, instead of the answer's
        self.state_override = {}         # keys of the wallet state replaced
        self.details_for = None          # callable(sid, iso) -> [Resp]
        self.tab_url = None              # callable(iso) -> the tab's address
        self.download_url = None         # callable(iso) -> the details answer's downloadUrl
        self.pdf_for = statement_pdf
        self.tab_readable = True
        self.asked_body = None
        self.list_delay = 0
        self.on_goto = None
        self.pager = False               # the sheet shows a control for more statements
        self.sign_in_drawn = False       # the page draws Bilt's sign-in in place

    # -- the page's own behavior -------------------------------------------
    def schedule(self, ms, fn):
        self.later.append((self.time + ms, fn))

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        self.time += ms
        due = [x for x in self.later if x[0] <= self.time]
        self.later = [x for x in self.later if x[0] > self.time]
        for _t, fn in sorted(due, key=lambda x: x[0]):
            fn()

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = url
        self.summary_open = self.list_open = False
        if self.on_goto:
            self.on_goto(self)
        return object()

    def emit(self, r):
        r._frame = Frame(self)
        self.context.emit("response", r)

    def answer_list(self):
        rs = self.list_answers() if self.list_answers else [list_resp(self.statements)]
        for r in rs:
            self.emit(r)

    def dates(self):
        if not self.list_open:
            return []
        return list(self.sheet) if self.sheet is not None else [d for d, _ in self.statements]

    def click(self, loc):
        self.presses.append(loc.label)
        if loc.label == site.SUMMARY_LABEL:
            self.summary_open = True
        elif loc.label == site.STATEMENTS_LABEL:
            assert self.summary_open
            self.list_open = True
            if self.list_delay:
                self.schedule(self.list_delay, self.answer_list)
            else:
                self.answer_list()
        elif loc.label.startswith("Download statement for "):
            assert self.list_open
            iso = site.button_date(loc.label)
            sid = [s for d, s in self.statements if d == iso][0]
            self.press_statement(sid, iso)
        else:
            raise AssertionError("pressed something else: %r" % loc.label)

    def press_statement(self, sid, iso):
        url = self.tab_url(iso) if self.tab_url else pdf_url(iso)
        dl_url = self.download_url(iso) if self.download_url else url
        for r in (self.details_for(sid, iso) if self.details_for else [details_resp(sid, iso, dl_url)]):
            self.emit(r)
        how = self.popup
        if how == "none":
            return
        pop = self.open_tab(self)
        if how == "elsewhere":
            pop.go("https://www.example-cdn.test/%s_%s_Bilt.pdf" % (TOKEN, iso), self.pdf_for(iso))
            return
        if how == "signin":
            pop.go("https://www.bilt.com/login")
            return
        if how == "wrongdate":
            pop.go(pdf_url("2026-09-06"), self.pdf_for("2026-09-06"))
            return
        body = sample_pdf() if how == "nottext" else (b"<html>no</html>" if how == "notpdf"
                                                       else self.pdf_for(iso))
        pop.go(url, body, readable=self.tab_readable)
        if how == "two":
            self.open_tab(self)
        elif how == "child":
            self.open_tab(pop)
        elif how == "download":
            dl = Download()
            self.downloads.append(dl)
            for f in list(self.listeners["download"]):
                f(dl)
        elif how == "stuck":
            pop.stuck = True
        elif how == "redirected":
            pop.go("https://www.example-cdn.test/hop")
            pop.go(url, body)

    def open_tab(self, opener):
        pop = Popup(opener, self.context)
        self.popups.append(pop)
        self.context.emit("page", pop)
        return pop

    # -- what the site layer reads ------------------------------------------
    def state(self):
        link = {"href": "/wallet/transactions?cardId=%s" % CARD, "shown": True}
        out = {
            "path": site.urlsplit(self.url).path,
            "password": self.password,
            "summary": [{"shown": True, "tag": "BUTTON"}],
            "openers": [{"shown": True, "tag": "DIV"}] if self.summary_open else [],
            "statements": [{"aria": "Download statement for " + words(d), "text": words(d),
                            "title": "", "shown": True, "tag": "BUTTON"} for d in self.dates()],
            "links": [link],
            "cards": [{"last4": LAST4}],
            "summary_card": [LAST4],
            "summary_link": [link["href"]],
            "profile": ["User profile. " + NAME],
            "welcome": [NAME],
            "pagers": [1] if self.pager and self.list_open else [],
            "signin": self.sign_in_drawn,
        }
        out.update(self.state_override)
        return out

    def labels_of(self, loc):
        if loc.kind != "button":
            return None
        if loc.label == site.SUMMARY_LABEL:
            return [site.SUMMARY_LABEL]
        if loc.label == site.STATEMENTS_LABEL:
            return [site.STATEMENTS_LABEL] if self.summary_open else None
        iso = site.button_date(loc.label)
        if iso and iso in self.dates():
            return [words(iso), loc.label]
        return None

    # -- the Playwright surface ----------------------------------------------
    def evaluate(self, js, arg=None):
        if js == site._STATE_JS:
            return self.state()
        if js == site._SIGNIN_JS:
            state = self.state()
            return {"signin": state["signin"], "summary": state["summary"]}
        raise AssertionError("unknown script")

    def get_by_role(self, role, name="", exact=False):
        assert role == "button" and exact
        return Loc(self, "button", name)

    def locator(self, css):
        if css == "input[type='password']":
            return Loc(self, "password")
        if css == "body":
            return Loc(self, "body")
        if css == site.OPENER_CSS:
            return Loc(self, "button", site.STATEMENTS_LABEL)
        return Loc(self, "other")

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def remove_listener(self, ev, f):
        self.listeners[ev].remove(f)

    def title(self):
        return "Wallet - Bilt Rewards"

    def is_closed(self):
        return False


@pytest.fixture(autouse=True)
def fake_press(monkeypatch):
    """The core's press, replaced by the made-up wallet's. The press is the
    core's own to test; this only says which control was pressed, or that
    the page has it turned off."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert css == pressing.BUTTONS
        if locator.label in page.turned_off:
            raise pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    site.set_private_words([])
    site._KEPT.clear()
    yield


def run_on(wallet):
    r = site.Run(staged=True)
    r.attach(wallet.context)
    return r


def take(wallet, tmp_path, iso="2026-10-06", sid=SID1, trace=None):
    out = tmp_path / "statements" / ("%s Bilt Card Statement.pdf" % iso)
    got = site.download_statement(wallet, run_on(wallet), out, card_id=CARD, statement_id=sid,
                                  iso_date=iso, trace=trace if trace is not None else [])
    return got, out


def no_tab_open(wallet):
    return all(p.closed for p in wallet.popups)


# ---------------------------------------------------------------------------
# Addresses and guards
# ---------------------------------------------------------------------------

def test_only_the_wallet_host_over_https():
    for u in ["https://www.bilt.com/", site.WALLET_URL]:
        assert site.is_safe_url(u), u
    for u in ["https://bilt.com/wallet", "https://api.biltrewards.com/x", pdf_url("2026-10-06"),
              "http://www.bilt.com/", "https://user@www.bilt.com/", "https://www.bilt.com.evil.test/",
              "https://www.bilt.com:8443/", "", None]:
        assert not site.is_safe_url(u), u
    assert site.is_wallet_url(site.WALLET_URL) and site.is_wallet_url(site.WALLET_URL + "/")
    for u in [site.WALLET_URL + "?x=1", site.WALLET_URL + "/transactions", "https://www.bilt.com/"]:
        assert not site.is_wallet_url(u), u


def test_the_answer_and_pdf_addresses_are_read_exactly():
    assert site.list_card_id(list_url()) == CARD
    assert site.details_ids(details_url(SID1)) == (CARD, SID1)
    for u in [list_url() + "/history", list_url() + "?x=1", list_url().replace("api.", "www."),
              f"{API}/bilt-card/cards/not-a-uuid/account/statements",
              f"{API}/bilt-card/cards/{CARD}/account/statements/current/spend-summary",
              list_url().replace("https:", "http:")]:
        assert not site.list_card_id(u), u
    assert site.details_ids(details_url("..")) == ("", "")
    assert site.details_ids(details_url(SID1) + "?x") == ("", "")
    assert site.pdf_url_date(pdf_url("2026-10-06")) == "2026-10-06"
    for u in [pdf_url("2026-10-06") + "?sig=1", pdf_url("2026-10-06") + "#x", pdf_url("2026-02-30"),
              pdf_url("2026-10-06").replace("statements.", "evil."),
              pdf_url("2026-10-06").replace("_Bilt.pdf", "_Other.pdf"),
              pdf_url("2026-10-06").replace("https:", "http:"),
              "https://statements.cardless.com/a/b_2026-10-06_Bilt.pdf",
              "https://statements.cardless.com.evil.test/%s_2026-10-06_Bilt.pdf" % TOKEN]:
        assert site.pdf_url_date(u) is None, u
    assert site.transactions_card_id("/wallet/transactions?cardId=%s" % CARD) == CARD
    for h in ["/wallet/transactions?cardId=x", "/wallet/transactions?cardId=%s&a=1" % CARD,
              "https://evil.test/wallet/transactions?cardId=%s" % CARD, None, ""]:
        assert site.transactions_card_id(h) == "", h


def test_the_three_presses_and_nothing_else():
    assert site.is_balance_summary("View balance summary")
    assert site.is_view_statements("View statements")
    assert site.is_statement_button("Download statement for October 06, 2026", "2026-10-06")
    assert site.is_statement_button("October 06, 2026", "2026-10-06")
    assert not site.is_statement_button("Download statement for October 06, 2026", "2026-09-06")
    assert not site.is_statement_button("Download statement for October 06, 2026")
    assert not site.is_statement_button("Download statement for February 30, 2026", "2026-02-30")
    refused = ["Pay card", "Pay with points", "Make payment", "Scheduled payments 1",
               "Transfer a balance to Bilt Transfer balances to your card.", "Lock card",
               "Manage card", "Authorized users", "Add", "Add to wallet", "Refer a friend",
               "Earn 2,500 Bilt Points Refer a friend", "Rewards", "Navigate to Neighborhood",
               "Open fullscreen chat", "Conversation history", "User profile. A B", "View all",
               "View all (4)", "Previous card", "Next card", "Close", "View", "Preferences",
               "Sign out", "Log out", "View statements and pay", "View balance summary and pay",
               "Download statement for October 06, 2026 | Make payment", "Statements", "", None,
               "October 06, 2026 Pay card", "Download statement for Oct 06, 2026"]
    for label in refused:
        assert not site.is_balance_summary(label), label
        assert not site.is_view_statements(label), label
        assert not site.is_statement_button(label, "2026-10-06"), label
        assert not site.is_safe_control(label), label
    assert {g.__name__ for g in site.PRESS_GUARDS} == {
        "is_balance_summary", "is_view_statements", "is_statement_button"}
    for label in ("View Card Statement", "Download Card Statement", "Download statement",
                  "View balance summary", "View statements", "Download statement for May 06, 2026"):
        assert site.is_safe_control(label), label


def test_the_file_name_is_the_bilt_card_statement_of_its_date():
    assert docs.build_pdf_filename("2026-10-06", "Card Statement", "") == \
        "2026-10-06 Bilt Card Statement.pdf"
    rules = json.loads((HERE / "document_rules.json").read_text(encoding="utf-8"))
    assert [r["summary"] for r in rules["statement_rules"]] == ["Card Statement"]
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    assert cfg["cdp_url"] == "http://127.0.0.1:9297" and cfg["pilot_count"] == 1
    assert cfg["owner"] == "" and cfg["output_dir"] == "."


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def test_the_list_is_read_by_the_three_presses_heard_whole():
    w = Wallet()
    got = site.collect_download_docs(w, run_on(w))
    assert [(d.date_text, d.document_id, d.card_id) for d in got] == \
        [(d, s, CARD) for d, s in STATEMENTS]
    assert {d.title for d in got} == {"Card Statement"} and {d.account for d in got} == {"Bilt Card"}
    assert w.presses == [site.SUMMARY_LABEL, site.STATEMENTS_LABEL]
    assert w.gotos == [site.WALLET_URL]
    assert w.context.request.asked == []


def test_an_empty_list_is_a_whole_empty_list():
    w = Wallet(statements=[])
    assert site.collect_download_docs(w, run_on(w)) == []


def test_an_answer_that_comes_late_is_waited_for():
    w = Wallet()
    w.list_delay = 1000
    assert len(site.collect_download_docs(w, run_on(w))) == 3


@pytest.mark.parametrize("why,setup", [
    ("count mismatch", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS, count=4)])),
    ("count true", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS[:1], count=True)])),
    ("count float", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS, count=3.0)])),
    ("count text", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS, count="3")])),
    ("sheet has one less", lambda w: setattr(w, "sheet", ["2026-10-06", "2026-09-06"])),
    ("sheet has one more", lambda w: setattr(w, "sheet", ["2026-10-06", "2026-09-06", "2026-08-06",
                                                          "2026-07-06"])),
    ("sheet other date", lambda w: setattr(w, "sheet", ["2026-10-06", "2026-09-06", "2026-08-07"])),
    ("duplicate date", lambda w: setattr(w, "list_answers", lambda: [list_resp(
        [("2026-10-06", SID1), ("2026-10-06", SID2)])])),
    ("duplicate id", lambda w: setattr(w, "list_answers", lambda: [list_resp(
        [("2026-10-06", SID1), ("2026-09-06", SID1)])])),
    ("bad date", lambda w: setattr(w, "list_answers", lambda: [list_resp([("2026-02-30", SID1)])])),
    ("bad id", lambda w: setattr(w, "list_answers", lambda: [list_resp([("2026-10-06", "a/b")])])),
    ("other card", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS, card=OTHER_CARD)])),
    ("two answers", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS),
                                                                    list_resp(STATEMENTS)])),
    ("no answer", lambda w: setattr(w, "list_answers", lambda: [])),
    ("not 200", lambda w: setattr(w, "list_answers", lambda: [list_resp(STATEMENTS, status=500)])),
    ("not json", lambda w: setattr(w, "list_answers", lambda: [Resp(list_url(), body=b"nope")])),
    ("not the shape", lambda w: setattr(w, "list_answers", lambda: [Resp(list_url(), body=b"[]")])),
    ("no card", lambda w: w.state_override.update(cards=[], summary_card=[])),
    ("two cards", lambda w: w.state_override.update(cards=[{"last4": LAST4}, {"last4": "9999"}])),
    ("two links", lambda w: w.state_override.update(links=[
        {"href": "/wallet/transactions?cardId=%s" % CARD, "shown": True},
        {"href": "/wallet/transactions?cardId=%s" % OTHER_CARD, "shown": True}])),
    ("crossed card", lambda w: w.state_override.update(summary_link=[
        "/wallet/transactions?cardId=%s" % OTHER_CARD])),
    ("crossed label", lambda w: w.state_override.update(summary_card=["9999"])),
    ("no summary", lambda w: w.state_override.update(summary=[])),
    ("two summaries", lambda w: w.state_override.update(summary=[{"shown": True, "tag": "BUTTON"}] * 2)),
    ("off the wallet", lambda w: setattr(w, "on_goto", lambda w: setattr(w, "url", "https://www.bilt.com/rewards/home"))),
    ("hidden button", lambda w: w.state_override.update(statements=[{
        "aria": "Download statement for October 06, 2026", "text": "October 06, 2026", "title": "",
        "shown": False, "tag": "BUTTON"}])),
    ("more to come", lambda w: setattr(w, "list_answers", lambda: [paged_resp(hasMore=True)])),
    ("a cursor", lambda w: setattr(w, "list_answers", lambda: [paged_resp(nextCursor="c2")])),
    ("both", lambda w: setattr(w, "list_answers", lambda: [paged_resp(hasMore=True,
                                                                      nextCursor="c2")])),
    ("a total", lambda w: setattr(w, "list_answers", lambda: [paged_resp(total=12)])),
    ("a page", lambda w: setattr(w, "list_answers", lambda: [paged_resp(page=1, pageSize=3)])),
    ("a pager on the sheet", lambda w: setattr(w, "pager", True)),
])
def test_a_list_that_is_not_whole_stops(why, setup):
    w = Wallet()
    setup(w)
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(w, run_on(w))
    assert stop.value.docs == []
    for word in PRIVATE:
        assert word not in str(stop.value), (why, word)
    assert [p for p in w.presses if p.startswith("Download statement")] == []


def test_an_answer_that_may_say_there_is_more_stops_with_its_reason():
    """The live answer held its list and its count and nothing else. Its
    count is its own list's length, so a cut answer would pass that check,
    and a key beyond the two may be how Bilt says there is more."""
    w = Wallet()
    w.list_answers = lambda: [paged_resp(hasMore=True, nextCursor="c2")]
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(w, run_on(w))
    said = str(stop.value)
    assert "more than its list and its count" in said
    assert "hasMore" not in said and "nextCursor" not in said, "the page's own words"
    assert [p for p in w.presses if p.startswith("Download statement")] == []


def test_a_sheet_that_offers_more_statements_stops_with_its_reason():
    w = Wallet()
    w.pager = True
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(w, run_on(w))
    assert "a control for more or older statements" in str(stop.value)


def test_a_statement_sought_on_a_sheet_that_offers_more_stops_the_run(tmp_path):
    w = Wallet()
    w.pager = True
    with pytest.raises(pressing.Stop):
        take(w, tmp_path)
    assert [p for p in w.presses if p.startswith("Download statement")] == []


def test_the_controls_that_bring_more_of_the_list_are_read_whole():
    for label in ["Load more", "Show more", "See more statements", "View older statements",
                  "Load older", "Show earlier statements", "More", "Older", "Older statements",
                  "Previous statements", "View all statements", "Next page", "load  MORE"]:
        assert site.PAGER_RE.match(label), label
    for label in ["View all", "View all (4)", "Learn more", "Learn more about rewards",
                  "More ways to earn", "Previous card", "Next card", "View statements",
                  "Download statement for October 06, 2026", "October 06, 2026", "Show balance",
                  "Load more rewards", ""]:
        assert not site.PAGER_RE.match(label), label


@pytest.mark.parametrize("answer", [
    lambda: [list_resp(STATEMENTS, status=401)],
    lambda: [list_resp(STATEMENTS, status=302)],
    lambda: [Resp(list_url(), ctype="text/html", body=b"<html>sign in</html>")],
])
def test_a_signed_out_answer_stops_for_the_holder(answer):
    w = Wallet()
    w.list_answers = answer
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(w, run_on(w))


def test_the_sign_in_page_is_signed_out():
    w = Wallet()
    w.on_goto = lambda w: setattr(w, "url", "https://www.bilt.com/login")
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(w, run_on(w))
    w = Wallet()
    w.password = True
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(w, run_on(w))
    assert w.presses == []


def signed_out_wallet():
    """The wallet as a signed-out Discover found it on 2026-10-15. The visit
    stays on /wallet, there is no password field, the page draws its
    sign-in in place ("Complete login to continue", "Log in or sign up",
    the nav's "Sign up / Log in"), and no card or balance summary shows."""
    w = Wallet()
    w.sign_in_drawn = True
    w.state_override.update(summary=[], links=[], cards=[], summary_card=[], summary_link=[],
                            profile=[], welcome=[])
    return w


def test_the_sign_in_drawn_on_the_wallet_is_signed_out():
    w = signed_out_wallet()
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(w, run_on(w))
    assert w.gotos == [site.WALLET_URL] and w.presses == []
    assert w.password is False, "the live sign-in had no password field"
    assert site.looks_signed_out(w)


def test_a_signed_out_discover_asks_to_sign_in_again(tmp_path, monkeypatch):
    w = signed_out_wallet()
    app = wallet_app(tmp_path, monkeypatch, w)
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    said = out.getvalue()
    assert "Bilt answered as signed out" in said and "Sign in again" in said
    assert "one Bilt Card" not in said
    assert w.presses == []


def test_a_sign_in_drawn_for_a_moment_while_the_wallet_loads_is_not_signed_out():
    """A page that draws its sign-in in place can draw it while a signed-in
    wallet is still finding its session. Only a sign-in that stays is a
    sign-out (#105)."""
    w = signed_out_wallet()

    def found_its_session():
        w.sign_in_drawn = False
        w.state_override.clear()
    w.schedule(site.SIGN_IN_HOLD_MS // 2, found_its_session)
    assert len(site.collect_download_docs(w, run_on(w))) == 3


def test_a_sign_in_that_stays_is_signed_out_after_its_hold():
    w = signed_out_wallet()
    start = w.time
    assert site.looks_signed_out(w)
    assert w.time - start >= site.SIGN_IN_HOLD_MS


def test_a_wallet_that_shows_its_card_and_no_sign_in_is_read():
    w = Wallet()
    assert not site.looks_signed_out(w)
    assert len(site.collect_download_docs(w, run_on(w))) == 3


def test_a_wallet_with_neither_its_card_nor_the_sign_in_stops_at_one_card():
    w = Wallet()
    w.state_override.update(summary=[], cards=[], summary_card=[])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(w, run_on(w))
    assert "one Bilt Card with its balance summary" in str(stop.value)
    assert not site.looks_signed_out(w)


def test_a_balance_summary_label_on_no_button_does_not_hide_the_sign_in():
    w = signed_out_wallet()
    w.state_override.update(summary=[{"shown": True, "tag": "DIV"}])
    assert site.looks_signed_out(w)
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(w, run_on(w))


def test_the_sign_in_words_beside_the_balance_summary_are_not_signed_out():
    """The words are read as the sign-in only where the card's balance
    summary button is not shown."""
    w = Wallet()
    w.sign_in_drawn = True
    assert not site.looks_signed_out(w)
    assert len(site.collect_download_docs(w, run_on(w))) == 3


def test_an_answer_from_another_tab_is_not_this_runs():
    w = Wallet()
    other = SimpleNamespace()

    def answers():
        r = list_resp(STATEMENTS[:1])
        w.context.emit("response", r)   # heard first, from another tab
        r._frame = Frame(other)
        return [list_resp(STATEMENTS)]
    w.list_answers = answers
    assert len(site.collect_download_docs(w, run_on(w))) == 3


@pytest.mark.parametrize("label", [site.SUMMARY_LABEL, site.STATEMENTS_LABEL])
def test_a_turned_off_opener_stops_the_list(label):
    w = Wallet()
    w.turned_off = {label}
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(w, run_on(w))


def test_a_control_that_is_not_one_stops_and_nothing_is_pressed():
    w = Wallet()
    w.copies = {site.SUMMARY_LABEL: 2}
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(w, run_on(w))
    assert w.presses == []


def test_nothing_is_pressed_when_downloads_are_not_staged():
    w = Wallet()
    r = site.Run()
    r.attach(w.context)
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(w, r)
    assert "download folder" in str(stop.value)
    assert w.presses == []


def test_a_press_with_a_guard_not_its_own_is_refused():
    w = Wallet()
    with pytest.raises(site.ListStopped):
        site._press(w, w.get_by_role("button", name="Pay card", exact=True), what="x",
                    guard=lambda label: True, step="x", run=run_on(w))
    assert w.presses == []


# ---------------------------------------------------------------------------
# One statement
# ---------------------------------------------------------------------------

def test_a_statement_is_taken_from_its_tab_and_the_tab_closed(tmp_path):
    w = Wallet()
    trace = []
    got, out = take(w, tmp_path, trace=trace)
    assert got is True and out.read_bytes()[:5] == b"%PDF-"
    assert w.presses == [site.SUMMARY_LABEL, site.STATEMENTS_LABEL,
                         "Download statement for October 06, 2026"]
    assert len(w.popups) == 1 and no_tab_open(w)
    assert w.context.request.asked == []
    assert {"note": "the popup's own answer was read", "how": "heard"} in trace
    for word in PRIVATE:
        assert word not in json.dumps(trace), word
    # Every listener the capture added is gone again.
    assert w.listeners["download"] == [] and w.context.listeners["page"] == []
    assert len(w.context.listeners["response"]) == 1


def test_an_older_statement_is_bound_by_its_own_date(tmp_path):
    w = Wallet()
    got, out = take(w, tmp_path, iso="2026-09-06", sid=SID2)
    assert got is True and w.presses[-1] == "Download statement for September 06, 2026"


def test_a_tab_whose_answer_cannot_be_read_is_asked_once_by_its_exact_address(tmp_path):
    w = Wallet()
    w.tab_readable = False
    w.asked_body = statement_pdf("2026-10-06")
    trace = []
    got, out = take(w, tmp_path, trace=trace)
    assert got is True
    assert w.context.request.asked == [(pdf_url("2026-10-06"), 0)]
    assert {"note": "the popup's address was asked again", "how": "asked"} in trace


def test_an_asked_address_that_holds_no_pdf_stops(tmp_path):
    w = Wallet()
    w.tab_readable = False
    w.asked_body = b"<html>expired</html>"
    with pytest.raises(pressing.NoAnswer):
        take(w, tmp_path)
    assert no_tab_open(w)


@pytest.mark.parametrize("how,reason", [
    ("none", "no statement tab came"),
    ("two", "the press did not open one tab"),
    ("child", "the press did not open one tab"),
    ("elsewhere", "the tab is on another host"),
    ("wrongdate", "the tab's address is not this statement's"),
    ("download", "a download began"),
    ("stuck", "the tab stayed open"),
    ("notpdf", "the tab held no pdf"),
    ("redirected", "the tab went elsewhere"),
])
def test_anything_but_one_tab_holding_this_pdf_stops_the_run(tmp_path, how, reason):
    w = Wallet(popup=how)
    with pytest.raises(pressing.NoAnswer) as stop:
        take(w, tmp_path)
    assert stop.value.reason == reason
    assert not (tmp_path / "statements").exists() or not any((tmp_path / "statements").iterdir())
    if how != "stuck":
        assert no_tab_open(w)
    for dl in w.downloads:
        assert dl.canceled and dl.deleted
    for word in PRIVATE:
        assert word not in " ".join(stop.value.lines), word


def test_a_wallet_tab_sent_off_bilt_by_the_press_stops_and_keeps_nothing(tmp_path):
    w = Wallet()
    real = w.press_statement

    def press(sid, iso):
        real(sid, iso)
        w.url = "https://www.example.test/elsewhere"
    w.press_statement = press
    with pytest.raises(pressing.NoAnswer) as stop:
        take(w, tmp_path)
    assert stop.value.reason == "the wallet left bilt"
    assert no_tab_open(w) and not (tmp_path / "statements").exists()


def test_a_tab_on_the_sign_in_page_is_signed_out(tmp_path):
    w = Wallet(popup="signin")
    with pytest.raises(site.SessionExpired):
        take(w, tmp_path)
    assert no_tab_open(w)


def test_a_tab_opened_by_another_tab_is_left_alone(tmp_path):
    w = Wallet()
    other = SimpleNamespace()
    real = w.press_statement

    def press(sid, iso):
        w.open_tab(other)       # another tab's own popup, at the same moment
        real(sid, iso)
    w.press_statement = press
    got, _ = take(w, tmp_path)
    assert got is True
    assert w.popups[0].closed is False and w.popups[1].closed is True


@pytest.mark.parametrize("details", [
    lambda sid, iso: [],
    lambda sid, iso: [details_resp(sid, iso, pdf_url(iso)), details_resp(sid, iso, pdf_url(iso))],
    lambda sid, iso: [details_resp(SID2, iso, pdf_url(iso))],
    lambda sid, iso: [details_resp(sid, "2026-09-06", pdf_url(iso))],
    lambda sid, iso: [details_resp(sid, iso, pdf_url(iso), card=OTHER_CARD)],
    lambda sid, iso: [details_resp(sid, iso, pdf_url(iso, token="Other99"))],
    lambda sid, iso: [details_resp(sid, iso, "")],
])
def test_a_details_answer_that_does_not_name_this_statement_stops(tmp_path, details):
    w = Wallet()
    w.details_for = details
    with pytest.raises(pressing.NoAnswer):
        take(w, tmp_path)
    assert no_tab_open(w)


def test_a_download_address_on_another_host_is_only_noted(tmp_path):
    w = Wallet()
    w.download_url = lambda iso: "https://files.example.test/signed?x=%s" % TOKEN
    trace = []
    got, _ = take(w, tmp_path, trace=trace)
    assert got is True
    assert {"note": "details answer", "same_host": False, "same_address": False} in trace


def test_a_signed_out_details_answer_stops_for_the_holder(tmp_path):
    w = Wallet()
    w.details_for = lambda sid, iso: [details_resp(sid, iso, pdf_url(iso), status=401)]
    with pytest.raises(site.SessionExpired):
        take(w, tmp_path)
    assert no_tab_open(w)


@pytest.mark.parametrize("pdf,why", [
    (lambda iso: statement_pdf("2026-09-06"), "does not print the statement's date"),
    (lambda iso: statement_pdf(iso, last4="7777"), "another card's number"),
    (lambda iso: text_pdf(["Statement Closing Date %s" % mdy(iso), "Card XXXX XXXX XXXX 7777"]
                          + ["Line %d" % n for n in range(12)]), "another card's number"),
    (lambda iso: sample_pdf(), "does not print the statement's date"),
])
def test_a_pdf_that_is_not_this_statement_is_not_kept(tmp_path, pdf, why):
    w = Wallet()
    w.pdf_for = pdf
    with pytest.raises(pressing.NoAnswer) as stop:
        take(w, tmp_path)
    assert why in " ".join(stop.value.lines)
    assert not (tmp_path / "statements" / "2026-10-06 Bilt Card Statement.pdf").exists()
    assert no_tab_open(w)


def test_a_pdf_that_also_names_the_paying_account_is_kept(tmp_path):
    w = Wallet()
    w.pdf_for = lambda iso: statement_pdf(iso, extra=["AutoPay from account ending in 7777"])
    assert take(w, tmp_path)[0] is True


def test_the_run_s_own_lines_keep_their_dates_once_an_address_is_private(tmp_path):
    w = Wallet()
    take(w, tmp_path)
    said = site.redact("the statement dated 2026-10-06 from statements.cardless.com")
    assert "2026-10-06" in said and "statements" in said
    assert TOKEN not in site.redact("tab %s" % pdf_url("2026-10-06"))


def test_a_pdf_that_prints_no_card_number_is_kept(tmp_path):
    w = Wallet()
    w.pdf_for = lambda iso: text_pdf(["Statement Closing Date %s" % mdy(iso)]
                                     + ["Line of the statement %d" % n for n in range(12)])
    assert take(w, tmp_path)[0] is True


def test_the_same_bytes_are_never_kept_for_two_statements(tmp_path):
    w = Wallet()
    same = statement_pdf("2026-10-06", extra=["Previous closing 09/06/2026"])
    w.pdf_for = lambda iso: same
    assert take(w, tmp_path)[0] is True
    with pytest.raises(pressing.NoAnswer) as stop:
        take(w, tmp_path / "again", iso="2026-09-06", sid=SID2)
    assert "same file" in " ".join(stop.value.lines)


def test_a_download_again_still_refuses_another_statement_s_file(tmp_path):
    """The record's own copy is left out of the same-bytes check, and only
    that. A PDF that is the very file of another statement saved in an
    earlier run is still never kept."""
    same = statement_pdf("2026-10-06", extra=["Previous closing 09/06/2026"])
    w = Wallet()
    w.pdf_for = lambda iso: same
    assert take(w, tmp_path)[0] is True          # October's, saved in an earlier run
    site._KEPT.clear()                          # the next run is a new process
    folder = tmp_path / "statements"
    own = folder / "2026-09-06 Bilt Card Statement.pdf"
    own.write_bytes(statement_pdf("2026-09-06"))  # September's own copy, other bytes
    w2 = Wallet()
    w2.pdf_for = lambda iso: same
    out = folder / "2026-09-06 Bilt Card Statement 0a1b2c.pdf"
    with pytest.raises(pressing.NoAnswer) as stop:
        site.download_statement(w2, run_on(w2), out, card_id=CARD, statement_id=SID2,
                                iso_date="2026-09-06", trace=[], own_files=[own])
    assert "the same file as one already saved" in " ".join(stop.value.lines)
    assert not out.exists()


def test_a_download_again_may_get_the_bytes_of_its_own_copy(tmp_path):
    w = Wallet()
    assert take(w, tmp_path)[0] is True
    site._KEPT.clear()
    folder = tmp_path / "statements"
    own = folder / "2026-10-06 Bilt Card Statement.pdf"
    w2 = Wallet()
    out = folder / "2026-10-06 Bilt Card Statement 0a1b2c.pdf"
    assert site.download_statement(w2, run_on(w2), out, card_id=CARD, statement_id=SID1,
                                   iso_date="2026-10-06", trace=[], own_files=[own]) is True
    assert out.read_bytes() == own.read_bytes()


def test_a_turned_off_statement_is_left_and_nothing_taken(tmp_path):
    w = Wallet()
    w.turned_off = {"Download statement for October 06, 2026"}
    got, out = take(w, tmp_path)
    assert got is None and not out.exists() and w.popups == []


def test_a_statement_no_longer_listed_is_not_pressed(tmp_path):
    w = Wallet(statements=STATEMENTS[1:])
    got, out = take(w, tmp_path)
    assert got is False and not out.exists()
    assert w.presses == [site.SUMMARY_LABEL, site.STATEMENTS_LABEL]
    w = Wallet()
    got, _ = take(w, tmp_path, sid=SID2)       # the id under another date
    assert got is False


@pytest.mark.parametrize("card,sid,iso", [("", SID1, "2026-10-06"), (CARD, "", "2026-10-06"),
                                          (CARD, "a/b", "2026-10-06"), (CARD, SID1, "2026-02-30"),
                                          ("not-a-uuid", SID1, "2026-10-06")])
def test_a_record_that_names_no_statement_presses_nothing(tmp_path, card, sid, iso):
    w = Wallet()
    out = tmp_path / "x.pdf"
    assert site.download_statement(w, run_on(w), out, card_id=card, statement_id=sid,
                                   iso_date=iso) is False
    assert w.presses == [] and w.gotos == []


def test_a_list_that_stops_while_a_statement_is_sought_stops_the_run(tmp_path):
    w = Wallet()
    w.sheet = ["2026-10-06"]
    with pytest.raises(pressing.Stop) as stop:
        take(w, tmp_path)
    assert [p for p in w.presses if p.startswith("Download")] == []
    # A Resume would read the same list for its first statement (#124).
    assert stop.value.list_unread


# ---------------------------------------------------------------------------
# The run: records, names and privacy
# ---------------------------------------------------------------------------

class FakeSite:
    """The site layer as the orchestrator calls it, a spy."""

    def __init__(self, statements=STATEMENTS):
        self.statements = list(statements)
        self.asked = []

    def collect_download_docs(self, page, run=None):
        return [site.RawDoc(title=site.TITLE, account=site.ACCOUNT, date_text=d, text=site.TITLE,
                            kind="statement", document_id=s, card_id=CARD)
                for d, s in self.statements]

    def download_statement(self, page, run, out_path, *, card_id, statement_id, iso_date, trace=None,
                           own_files=()):
        self.asked.append((card_id, statement_id, iso_date))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(statement_pdf(iso_date))
        return True


def make_app(tmp_path, monkeypatch, fake):
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    cfg.update(output_dir=str(tmp_path / "out"), owner="Example Owner", delay_min_seconds=0,
               delay_max_seconds=0)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    args = docs.build_parser().parse_args(["--config", str(path), "--all", "--yes"])
    app = docs.App(args)
    for name in ("collect_download_docs", "download_statement"):
        monkeypatch.setattr(docs.site, name, getattr(fake, name))
    page = SimpleNamespace(url=site.WALLET_URL, is_closed=lambda: False)
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    return app


def test_a_run_saves_every_statement_under_its_own_name(tmp_path, monkeypatch, caplog):
    fake = FakeSite()
    app = make_app(tmp_path, monkeypatch, fake)
    caplog.set_level(logging.INFO)
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.cmd_run("all")
        app.write_run_summary()
    names = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert names == ["2026-08-06 Bilt Card Statement.pdf", "2026-09-06 Bilt Card Statement.pdf",
                     "2026-10-06 Bilt Card Statement.pdf"]
    assert sorted(fake.asked) == sorted((CARD, s, d) for d, s in STATEMENTS)
    seen = buf.getvalue() + caplog.text + "".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (tmp_path / "out").rglob("*")
        if p.is_file() and p.suffix in (".csv", ".txt", ".log"))
    # The index names each file by its whole path, inside a folder pytest
    # numbers, and pytest-48697 would hold the tail.
    seen = seen.replace(str(tmp_path), "<folder>")
    for word in PRIVATE:
        assert word not in seen, word
    for key in app.discovery.data:
        assert not any(word in key for word in PRIVATE)
    # A second run takes nothing again.
    fake.asked.clear()
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert fake.asked == []


def wallet_app(tmp_path, monkeypatch, wallet, *more):
    """The app on the made-up wallet, the site layer its own."""
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    cfg.update(output_dir=str(tmp_path / "out"), owner="Example Owner", delay_min_seconds=0,
               delay_max_seconds=0)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    args = docs.build_parser().parse_args(["--config", str(path), "--all", "--yes", *more])
    app = docs.App(args)
    app.run = run_on(wallet)
    monkeypatch.setattr(app, "page", lambda: wallet)
    monkeypatch.setattr(app, "_on_its_site", lambda: wallet)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    return app


def test_a_download_again_saves_a_second_copy_beside_the_one_still_there(tmp_path, monkeypatch):
    """The panel's Download again runs Run All with --redownload. Bilt gives
    a statement's PDF again byte for byte, and the copy saved before is
    still in the folder, so the new copy takes the told-apart name and has
    the very bytes of the old one. That is no copy of another statement,
    and the run saves every statement again rather than stop at the first."""
    with redirect_stdout(io.StringIO()):
        wallet_app(tmp_path, monkeypatch, Wallet()).cmd_run("all")
    first = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert len(first) == 3
    site._KEPT.clear()                          # the next run is a new process
    w = Wallet()
    app = wallet_app(tmp_path, monkeypatch, w, "--redownload")
    try:
        with redirect_stdout(io.StringIO()):
            app.cmd_run("all")
    except pressing.Stop as stop:
        pytest.fail("Download again stopped the run: %s" % " ".join(stop.lines))
    names = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert len(names) == 6 and set(first) < set(names)
    assert len([p for p in w.presses if p.startswith("Download statement")]) == 3
    assert {r.get("state") for r in app.progress.data.values()} == {docs.State.COMPLETED.value}


def test_one_id_under_two_dates_stops_the_list_and_keeps_the_record(tmp_path, monkeypatch):
    fake = FakeSite()
    app = make_app(tmp_path, monkeypatch, fake)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover(quiet=True)
    before = dict(app.discovery.data)
    fake.statements = [("2026-07-06", SID1)]
    with redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.discovery.data == before


def test_the_key_and_the_tie_breaker_hold_no_id():
    d = docs.Document(title="Card Statement", category="Statement", date="2026-10-06",
                      document_id=SID1, card_id=CARD)
    assert d.key.startswith("id:") and SID1 not in d.key and CARD not in d.key
    other = docs.Document(title="Card Statement", category="Statement", date="2026-10-06",
                          document_id=SID1, card_id=OTHER_CARD)
    assert other.key == d.key, "a reissued card is the same statement"
    tie = docs.told_apart_by(d.to_dict())
    assert len(tie) == 6 and tie not in SID1 and tie == docs.told_apart_by(other.to_dict())
    assert docs.told_apart_by({}) == ""


def test_the_private_words_are_redacted_once_the_wallet_is_read():
    w = Wallet()
    site.collect_download_docs(w, run_on(w))
    text = "card %s ending %s for %s, statement %s" % (CARD, LAST4, NAME, SID1)
    out = site.redact(text)
    for word in [CARD, LAST4, "Quentin", "Wombatson", SID1]:
        assert word not in out, word


def test_diagnose_reads_counts_only(tmp_path):
    w = Wallet()
    w.list_open = True
    info = site.survey(w, dwell_ms=0)
    page = info["pages"][0]
    assert page["one_card_read"] is True and page["statement_buttons"] == 3
    blob = json.dumps(info) + json.dumps([d.__dict__ for d in site.collect_documents(w)])
    for word in PRIVATE + [MERCHANT, "4,321.09"]:
        assert word not in blob, word
    assert w.presses == []


def test_the_failure_file_names_its_provider():
    src = (HERE / "bilt_docs.py").read_text(encoding="utf-8")
    assert "provider='Bilt'" in src and "First Horizon" not in src
    assert "firsthorizon" not in (HERE / "bilt_site.py").read_text(encoding="utf-8")


def test_the_view_statements_control_is_found_by_its_own_text():
    """On the live sheet its accessible name is "View statements
    action-right", an icon button's name nested in it, so a role query by
    the exact name finds nothing. It is looked for among the shown buttons
    by its own exact text instead."""
    calls = []

    class Spy:
        def __init__(self, path):
            self.path = path

        def filter(self, **kw):
            calls.append(kw)
            return Spy(self.path + ["filter"])

    class Page:
        def locator(self, css):
            calls.append(("locator", css))
            return Spy(["locator"])

        def get_by_role(self, *a, **kw):
            raise AssertionError("a role query would miss the control")

    found = site._view_statements(Page())
    assert found.path == ["locator", "filter", "filter"]
    assert calls[0] == ("locator", 'button, [role="button"]')
    assert calls[1]["has_text"].pattern == site.STATEMENTS_TEXT_RE.pattern
    assert site.STATEMENTS_TEXT_RE.fullmatch(" View statements ")
    assert not site.STATEMENTS_TEXT_RE.fullmatch("View statements and pay")
    assert not site.STATEMENTS_TEXT_RE.fullmatch("action-right")
    assert calls[2] == {"visible": True}


def test_the_pdf_address_may_carry_its_signing_query_and_nothing_else():
    """The live tab opens on the PDF's signed address, Expires, Signature
    and Key-Pair-Id once each. That form is this statement's address too.
    Any other query, a repeated key, an empty value or a fragment is not,
    and every query value is a private word once the address is seen."""
    signed = pdf_url("2026-10-06") + "?Expires=1760000000&Signature=MEUCIQabc~def_ghi&Key-Pair-Id=K2EXAMPLEID"
    assert site.pdf_url_date(signed) == "2026-10-06"
    assert site.pdf_token(signed) == TOKEN
    for u in [signed + "&x=1",
              signed.replace("&Key-Pair-Id=K2EXAMPLEID", ""),
              signed + "&Expires=1",
              signed.replace("Signature=MEUCIQabc~def_ghi", "Signature="),
              signed + "#page=2",
              pdf_url("2026-10-06") + "?Expires=1&Signature=s&Key-Pair-Id=k&Policy=p",
              pdf_url("2026-10-06") + "?",
              pdf_url("2026-10-06") + "?Expires"]:
        assert site.pdf_url_date(u) is None, u
        assert site.pdf_token(u) == "", u
    site._guard_address(signed)
    for word in [TOKEN, "MEUCIQabc~def_ghi", "K2EXAMPLEID", "1760000000"]:
        assert word not in site.redact("tab %s" % signed), word


def test_the_card_label_may_end_in_its_own_view_button_and_nothing_else():
    """Live the smallest element holding the card's label also holds the
    card's own "View" button, so that one word may follow the last four.
    Any other suffix, or a view-like word, is not the card's label. The
    page script reads the same pattern."""
    ok = site.CARD_LABEL_RE.fullmatch
    assert ok("Bilt Blue Card •••• 4821").group(1) == "4821"
    assert ok("Bilt Blue Card •••• 4821 View").group(1) == "4821"
    assert ok("Bilt Card **** 4821")
    for label in ("Bilt Blue Card •••• 4821 View Pay card", "Bilt Blue Card •••• 4821 Viewer",
                  "Bilt Blue Card •••• 4821 View View", "Bilt Blue Card •••• 482", "Card •••• 4821",
                  "Bilt Blue Card 4821 View", "Bilt Blue Card •••• 4821\nCurrent balance"):
        assert ok(label) is None, label
    assert json.dumps(site.CARD_LABEL_RE.pattern) in site._STATE_JS
    assert "new RegExp(CARD_LABEL_PATTERN)" in site._STATE_JS


def the_panel_reads_it_all_taken(monkeypatch, tmp_path, app):
    """What the control panel makes of this run's real records, by its own
    code. A run says nothing of a document it leaves, so these are what stop
    it settling a gap (#149)."""
    monkeypatch.syspath_prepend(str(HERE.parents[1] / "gui"))
    panel = pytest.importorskip("app")
    return panel._took_everything({"script_name": "bilt_docs.py", "dir": str(tmp_path)},
                                  "primary", app.paths.root, {})


def test_a_statement_turned_off_is_left_for_the_panel_too(tmp_path, monkeypatch):
    """Its Run All lists the statement, leaves no record of it, finishes
    clean, and the next run takes it. Each of the two reads as it is."""
    fake = FakeSite()
    app = make_app(tmp_path, monkeypatch, fake)

    def off(page, run, out_path, *, iso_date, **kw):
        if iso_date == STATEMENTS[0][0]:
            return None
        return fake.download_statement(page, run, out_path, iso_date=iso_date, **kw)

    with monkeypatch.context() as turned_off:
        turned_off.setattr(docs.site, "download_statement", off)
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_run("all")
    assert "left for the next run" in said.getvalue()
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is False
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is True
