"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only."""
import ast
import io
import json
import re
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import firsthorizon_site as site  # noqa: E402
import firsthorizon_docs as docs  # noqa: E402
from paperpull_core.testkit import sample_pdf  # noqa: E402

HOST = "digital.firsthorizon.com"
API = f"https://{HOST}/d3rest"
PDF = sample_pdf()
# Invented account details, which must never leave through a log, the
# console, the index, a diagnostic, a trace or a file name.
#
# A run writes its clock into names and lines ("failure-run-20261021-234810.json",
# a log line's ",549"), so every number here is one no clock can write. A
# masked tail is four digits no date or time of day holds, and the balance
# is looked for as "86,975" and "86975", never as a part of three digits,
# which a log line's milliseconds or 23:4x spells (it failed CI at 23:48).
ACCT1, ACCT2, ACCT3 = "Qa7Zx91004", "Qa7Zx92008", "Qa7Zx93012"
NICK1, NICK2, NICK3 = "WOMBATFUND", "QUOKKAJAR", "NUMBATPOT"
TITLE1 = f"{NICK1} (Express Checking) (*8642) $86,975.31"
TITLE2 = f"{NICK2} (Statement Savings) (*9753) $77.10"
TITLE3 = f"{NICK3} (Express Checking) (*3197) $5.00"
DOC1, DOC2, DOC3, DOC4, DOC5 = "Dk4401ab", "Dk4402ab", "Dk4403ab", "Dk4404ab", "Dk4405ab"
PRIVATE = [ACCT1, ACCT2, ACCT3, NICK1, NICK2, NICK3, "8642", "9753", "3197", "86,975", "86975",
           DOC1, DOC2, DOC3, DOC4, DOC5]


def file_of(acct, date, doc):
    return f"/v4/edocs/accounts/{acct}/statement/{date}/{doc}"


def entry(acct, date, doc, **more):
    return dict({"documentName": "Statement", "documentDate": date, "type": "STATEMENT",
                 "userAccountId": acct,
                 "endpoints": {"file": file_of(acct, date, doc), "html": file_of(acct, date, doc) + "/html"}},
                **more)


def mdy(iso):
    return f"{iso[5:7]}/{iso[8:10]}/{iso[:4]}"


# ---------------------------------------------------------------------------
# The made-up bank
# ---------------------------------------------------------------------------

class Frame:
    def __init__(self, page):
        self.page, self.parent_frame = page, None


class Req:
    def __init__(self, nav):
        self.nav = nav

    def is_navigation_request(self):
        return self.nav


class Resp:
    def __init__(self, url, status=200, ctype="application/json", body=b"{}", location="",
                 page=None, nav=False):
        self.url, self.status = url, status
        self.headers = {"content-type": ctype, **({"location": location} if location else {})}
        self._body = body
        self._frame, self.request = Frame(page), Req(nav)
        self.frameless = False

    @property
    def frame(self):
        if self.frameless:
            raise AttributeError("a popup's frame Playwright does not know yet")
        return self._frame

    @frame.setter
    def frame(self, value):
        self._frame = value

    def body(self):
        return self._body

    def dispose(self):
        pass


def links_resp(acct, statements, **kw):
    body = json.dumps({"accountDocumentLinks": {"STATEMENT": [entry(acct, d, doc) for d, doc in statements]}})
    return Resp(f"{API}/v4/edocs/accounts/{acct}/links", body=body.encode(), **kw)


def links_err(acct, status, **kw):
    return Resp(f"{API}/v4/edocs/accounts/{acct}/links", status, **kw)


class Request:
    """The request client: only the session probe is ever asked."""

    def __init__(self, bank):
        self.bank, self.asked = bank, []

    def get(self, url, **kw):
        self.asked.append((url, kw.get("max_redirects")))
        assert url == site.SESSION_URL, "the app asked the bank something other than the probe"
        r = self.bank.probe
        r.url = url
        return r

    def post(self, *a, **k):
        raise AssertionError("POST")

    def fetch(self, *a, **k):
        raise AssertionError("fetch")


class Download:
    def __init__(self, url, body=PDF):
        self.url, self.body = url, body
        self.suggested_filename = "EStatement-2026-09-16-00000.pdf"
        self.canceled = False

    def save_as(self, path):
        Path(path).write_bytes(self.body)

    def cancel(self):
        self.canceled = True


class Popup:
    """A page the Download PDF button opens. As in Chromium, its one answer
    reaches the context before its page is known, with a frame that cannot
    be read, unless `known` says its page is known."""

    def __init__(self, opener, context, known=False):
        self._url, self.closed, self.listeners = "about:blank", False, {"download": []}
        self._opener, self.context, self.known = opener, context, known
        self.stuck = False        # close() does not close it
        self.unreadable = False   # its url cannot be read

    @property
    def url(self):
        if self.unreadable:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._url

    @url.setter
    def url(self, value):
        self._url = value

    def opener(self):
        return self._opener

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def go(self, url, status=200, ctype="application/pdf", body=PDF):
        self.url = url
        resp = Resp(url, status, ctype, body, page=self, nav=True)
        resp.frameless = not self.known
        self.context.emit("response", resp)

    def is_closed(self):
        return self.closed

    def close(self):
        if not self.stuck:
            self.closed = True


class Context:
    def __init__(self, bank):
        self.listeners = {"response": [], "page": []}
        self.request = Request(bank)
        self.pages = []

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def remove_listener(self, ev, f):
        self.listeners[ev].remove(f)

    def emit(self, ev, x):
        for f in list(self.listeners[ev]):
            f(x)


class Loc:
    def __init__(self, page, kind, **at):
        self.page, self.kind, self.at = page, kind, at

    def nth(self, n):
        return Loc(self.page, self.kind, **dict(self.at, n=n))

    def locator(self, css):
        assert css == site.DOWNLOAD_BUTTON and self.kind == "cards"
        return Loc(self.page, "button", **self.at)

    def _labels(self):
        return self.page.labels_of(self)

    def count(self):
        if self.kind == "password":
            return 1 if self.page.password else 0
        if self.kind == "other":
            return 0
        return 1 if self._labels() is not None else 0

    def is_visible(self):
        return self._labels() is not None

    def evaluate(self, js):
        assert js == site._LABELS_JS
        return list(self._labels() or [])

    def inner_text(self, **kw):
        return ""


class Bank:
    """Accounts: dicts of id, title, statements [(date, docId)], open
    (expanded when the page loads), appear_at (ms after load before the
    panel is drawn, in its place among the others, so every panel after it
    moves one place on once it is), title_at (ms after load
    before the title's balance is drawn) and hidden_at (ms after load from
    which the page hides the panel). `download` says what the Download
    PDF button does. `single_open` makes the accordion keep one panel open."""

    def __init__(self, accounts, download="popup", single_open=False):
        self.accounts = accounts
        self.download = download
        self.single_open = single_open
        self.loaded_at = 0
        self.url = f"https://{HOST}/#accounts"
        self.context = Context(self)
        self.context.pages.append(self)
        self.probe = Resp(site.SESSION_URL, body=json.dumps({"profiles": [{"x": 1}]}).encode())
        self.password = self.dialog = False
        self.presses, self.downloads, self.popups, self.gotos = [], [], [], []
        self.listeners = {"download": [], "response": []}
        self.time, self.later = 0, []
        self.clock = None             # a Clock the waits move, when set
        self.waits = []
        self.links_override = {}      # account id -> list of Resp to answer with
        self.load_delay = 0           # ms after load before the open panels' answers come
        self.extra_on_load = []       # Resp emitted at load besides the panels'
        self.cards_override = None    # account id -> list of dates drawn
        self.on_goto = None
        self.download_url = None
        self.pdf_status = 200
        self.reset()

    # -- the page's own behavior -------------------------------------------
    def reset(self):
        self.open = [bool(a.get("open")) for a in self.accounts]
        self.answered = [bool(a.get("open")) for a in self.accounts]

    def schedule(self, ms, fn):
        self.later.append((self.time + ms, fn))

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        if self.clock is not None:
            self.clock.t += ms / 1000
        self.time += ms
        due = [x for x in self.later if x[0] <= self.time]
        self.later = [x for x in self.later if x[0] > self.time]
        for _t, fn in sorted(due, key=lambda x: x[0]):
            fn()

    def answer(self, i):
        a = self.accounts[i]
        over = self.links_override.get(a["id"])
        if over:
            for r in over:
                r.frame = Frame(self)
                self.context.emit("response", r)
            return
        self.context.emit("response", links_resp(a["id"], a["statements"], page=self))

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.url = url
        self.loaded_at = self.time
        self.reset()
        if self.on_goto:
            self.on_goto(self)
        for r in self.extra_on_load:
            if r.frame.page is None:
                r.frame = Frame(self)
            self.context.emit("response", r)
        for i, a in enumerate(self.accounts):
            if a.get("open"):
                if self.load_delay:
                    self.schedule(self.load_delay, lambda i=i: self.answer(i))
                else:
                    self.answer(i)
        return object()

    def reload(self, **kw):
        return self.goto(self.url)

    def click(self, loc):
        if loc.kind == "panel":
            i = self.drawn_now()[loc.at["n"]]
            self.presses.append(("panel", i))
            if self.single_open:
                self.open = [False] * len(self.open)
            self.open[i] = True
            self.answer(i)
        elif loc.kind == "button":
            i = self.region_index(loc.at["region"])
            date = self.cards(i)[loc.at["n"]]
            self.presses.append(("download", i, date))
            a = self.accounts[i]
            doc = [d for dd, d in a["statements"] if dd == date][0]
            url = self.download_url or API + file_of(a["id"], date, doc)
            self.do_download(url)
        else:
            raise AssertionError("pressed something else")

    def do_download(self, url):
        how = self.download
        if how == "none":
            return
        dl = Download(url)
        self.downloads.append(dl)
        if how == "opener":
            self.context.emit("response", Resp(url, self.pdf_status, "application/pdf", PDF, page=self,
                                               nav=True))
            for f in list(self.listeners["download"]):
                f(dl)
            return
        if how.startswith("chromium"):
            # As measured in headless Chromium: the popup's answer first, with
            # no frame to read, then the download on the opener, then the
            # page, which stays open with its url reading "".
            pop = Popup(self, self.context)
            self.popups.append(pop)
            pop.go(url)
            pop.url = ""
            for f in list(self.listeners["download"]):
                f(dl)
            self.context.emit("page", pop)
            if how == "chromium":
                pop.closed = True
            elif how == "chromium-stuck":
                pop.stuck = True
            elif how == "chromium-unreadable":
                pop.unreadable = True
            elif how == "chromium-two":
                second = Popup(self, self.context)
                self.popups.append(second)
                self.context.emit("page", second)
            return
        pop = Popup(self, self.context)
        self.popups.append(pop)
        self.context.emit("page", pop)
        if how == "signin":
            pop.go("https://security.firsthorizon.com/fhnsso/login", ctype="text/html", body=b"<html>")
            self.downloads.pop()
            return
        if how == "popup-elsewhere":
            pop.go(API + file_of(ACCT2, "2026-09-16", DOC3))
            for f in list(pop.listeners["download"]):
                f(dl)
            pop.closed = True
            return
        pop.go(url, self.pdf_status, "application/pdf" if self.pdf_status == 200 else "text/html",
               PDF if self.pdf_status == 200 else b"")
        if how == "popup":
            for f in list(pop.listeners["download"]):
                f(dl)
            pop.closed = True
        elif how == "popup-late":
            def later():
                for f in list(pop.listeners["download"]):
                    f(dl)
                pop.closed = True
            self.schedule(500, later)
        elif how == "popup-stays":
            for f in list(pop.listeners["download"]):
                f(dl)
        elif how == "two":
            for f in list(pop.listeners["download"]):
                f(dl)
                f(Download(url))
            pop.closed = True

    # -- what the site layer reads ------------------------------------------
    def region_index(self, region):
        return int(region.split("-")[1])

    def cards(self, i):
        if not self.open[i]:
            return []
        a = self.accounts[i]
        if self.cards_override and a["id"] in self.cards_override:
            return self.cards_override[a["id"]]
        if a.get("open") and self.load_delay and not self.answered_now(i):
            return []
        return [d for d, _doc in a["statements"]]

    def answered_now(self, i):
        return self.time >= self.load_delay

    def drawn(self, a, key):
        return self.time - self.loaded_at >= a.get(key, 0)

    def drawn_now(self):
        """The accounts whose panels are drawn now, in the page's order. The
        page's index of a panel is its place in this list."""
        return [i for i, a in enumerate(self.accounts) if self.drawn(a, "appear_at")]

    def state(self):
        panels = []
        for n, i in enumerate(self.drawn_now()):
            a = self.accounts[i]
            title = a["title"] if self.drawn(a, "title_at") else a["title"].rsplit(" $", 1)[0]
            panels.append({"index": n, "title": title, "labels": [title],
                           "expanded": "true" if self.open[i] else "false",
                           "region": a.get("region", "accordion-%d" % i),
                           "cards": [{"label": "Monthly statement for " + mdy(d), "shown": True,
                                      "buttons": 1} for d in self.cards(i)],
                           "shown": "hidden_at" not in a or not self.drawn(a, "hidden_at")})
        return {"heading": True, "tab": True, "panels": panels, "password": self.password}

    def labels_of(self, loc):
        if loc.kind == "panel":
            drawn = self.drawn_now()
            n = loc.at["n"]
            return [self.accounts[drawn[n]]["title"]] if n < len(drawn) else None
        if loc.kind == "button":
            i = self.region_index(loc.at["region"])
            cards = self.cards(i)
            if loc.at["n"] >= len(cards):
                return None
            return ["Download PDF", "Open New Tab to Download PDF for %s statement" % mdy(cards[loc.at["n"]])]
        return None

    # -- the Playwright surface ----------------------------------------------
    def evaluate(self, js, arg=None):
        if js == site._STATE_JS:
            return self.state()
        if js == site._TIMEOUT_JS:
            return self.dialog
        raise AssertionError("unknown script")

    def locator(self, css):
        if css == site.PANEL:
            return Loc(self, "panel")
        if css.endswith(" " + site.CARD):
            return Loc(self, "cards", region=css[1:].split(" ")[0])
        if css == "input[type='password']":
            return Loc(self, "password")
        return Loc(self, "other")

    def on(self, ev, f):
        self.listeners[ev].append(f)

    def remove_listener(self, ev, f):
        self.listeners[ev].remove(f)

    def title(self):
        return "First Horizon Bank | E-Statements"

    def is_closed(self):
        return False


@pytest.fixture(autouse=True)
def fake_press(monkeypatch):
    """The core's press, replaced by the made-up bank's. The press is the
    core's own to test; this only says which control was pressed."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert css in (site.PANEL, site.DOWNLOAD_BUTTON)
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    site.set_private_words([])
    yield


def acct1(**kw):
    return dict({"id": ACCT1, "title": TITLE1,
                 "statements": [("2026-09-16", DOC1), ("2026-08-15", DOC2)]}, **kw)


def acct2(**kw):
    return dict({"id": ACCT2, "title": TITLE2,
                 "statements": [("2026-09-16", DOC3), ("2026-07-17", DOC4)]}, **kw)


def acct3(**kw):
    return dict({"id": ACCT3, "title": TITLE3, "statements": [("2026-09-16", DOC5)]}, **kw)


def run_on(bank, clock=None):
    r = site.Run(clock=clock) if clock else site.Run()
    r.attach(bank.context)
    return r


# ---------------------------------------------------------------------------
# Addresses and guards
# ---------------------------------------------------------------------------

def test_only_the_bank_host_over_https():
    for u in [f"https://{HOST}/", site.DOCUMENTS_URL, site.SESSION_URL]:
        assert site.is_safe_url(u), u
    for u in ["https://banner.digital.firsthorizon.com/x", "https://security.firsthorizon.com/fhnsso/",
              "https://www.firsthorizon.com/", f"http://{HOST}/", f"https://user@{HOST}/",
              f"https://{HOST}.evil.test/", f"https://{HOST}:8443/", "https://collect.riskid.security/x",
              "", None]:
        assert not site.is_safe_url(u), u


def test_address_shapes():
    pdf = API + file_of(ACCT1, "2026-09-16", DOC1)
    assert site.is_download_url(pdf)
    for u in [pdf + "?x=1", pdf + "#x", pdf + "/html", API + file_of(ACCT1, "2026-09-16", ".."),
              pdf.replace("https:", "http:"), pdf.replace(HOST, "banner." + HOST),
              f"https://{HOST}" + file_of(ACCT1, "2026-09-16", DOC1), f"{API}/v3/login/ping"]:
        assert not site.is_download_url(u), u
    links = f"{API}/v4/edocs/accounts/{ACCT1}/links"
    assert site.is_links_url(links) and site.links_account_id(links) == ACCT1
    assert site.links_account_id(f"{API}/v4/edocs/accounts/a%20b/links") == "a b"
    for u in [links + "?x", links + "/", f"{API}/v4/accounts", links.replace(HOST, "banner." + HOST)]:
        assert not site.is_links_url(u), u
    assert site.is_documents_url(site.DOCUMENTS_URL)
    assert not site.is_documents_url(f"https://{HOST}/#accounts")
    assert site.download_url(file_of(ACCT1, "2026-09-16", DOC1)) == pdf
    assert site.download_url("/v3/login/ping") == ""


def test_the_two_shapes_and_nothing_else():
    assert site.is_account_panel(TITLE1)
    assert site.is_account_panel("JOINT (ONE) (Platinum Checking) (*0001) -$12.00")
    assert site.is_download_button("Download PDF")
    assert site.is_download_button("Open New Tab to Download PDF for 09/16/2026 statement", "2026-09-16")
    assert not site.is_download_button("Open New Tab to Download PDF for 09/16/2026 statement", "2026-08-15")
    refused = ["View Online", "Manage Statement Delivery", "STATEMENTS", "Statements",
               "Enroll In Online Tax Statements", "Stay Logged In", "Continue", "Log Out", "Logout",
               "Send Money with Zelle", "Make a Quick Payment", "Pay Bills", "Transfer Money",
               "Account Options", "Download PDF and Enroll", "Download PDF Now", "", None,
               "PRIMARY (Express Checking) (*12345) $1.00", "PRIMARY (Express Checking) $1.00",
               "BILL PAY FUND (Express Checking) (*1234) $1.00",
               "PRIMARY (Express Checking) (*1234) $1.00 Collapse"]
    for label in refused:
        assert not site.is_account_panel(label), label
        assert not site.is_download_button(label), label
    assert {g.__name__ for g in site.PRESS_GUARDS} == {"is_account_panel", "is_download_button"}
    assert site.is_safe_control("Download PDF") and not site.is_safe_control("View Online")


def test_the_product_is_the_group_before_the_mask():
    assert site.product_of(TITLE1) == "Express Checking"
    assert site.product_of("MY (OLD) ACCT (Statement Savings) (*1234) $0.00") == "Statement Savings"
    for bad in ["PRIMARY (Express Checking) (*1234)", "PRIMARY (Express Checking) (*123) $1.00",
                "(Express Checking) (*1234) $1.00", "PRIMARY (Express (Gold) Checking) (*1234) $1.00", ""]:
        assert site.product_of(bad) == "", bad


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def test_statements_of_validates_every_entry():
    good = entry(ACCT1, "2026-09-16", DOC1)
    assert site.statements_of({"accountDocumentLinks": {"STATEMENT": [good]}}, ACCT1) == \
        [site.Statement("2026-09-16", DOC1, file_of(ACCT1, "2026-09-16", DOC1))]
    assert site.statements_of({"accountDocumentLinks": {}}, ACCT1) == []
    for bad in [entry(ACCT1, "2026-02-30", DOC3), entry(ACCT1, "09/16/2026", DOC3),
                entry(ACCT2, "2026-07-17", DOC3), dict(entry(ACCT1, "2026-07-17", DOC3), userAccountId=ACCT2),
                dict(entry(ACCT1, "2026-07-17", DOC3), type="NOTICE"),
                dict(entry(ACCT1, "2026-07-17", DOC3), endpoints={"file": file_of(ACCT1, "2026-07-18", DOC3)}),
                dict(entry(ACCT1, "2026-07-17", DOC3), endpoints={"file": file_of(ACCT1, "2026-07-17", DOC3) + "?x"}),
                dict(entry(ACCT1, "2026-07-17", DOC3), endpoints={"file": file_of(ACCT1, "2026-07-17", "..")}),
                entry(ACCT1, "2026-09-16", DOC3), "x"]:
        with pytest.raises(site.ListStopped) as stop:
            site.statements_of({"accountDocumentLinks": {"STATEMENT": [good, bad]}}, ACCT1)
        assert ACCT1 not in str(stop.value) and DOC1 not in str(stop.value)
    for bad in ({}, [], {"accountDocumentLinks": []}, None):
        with pytest.raises(site.SessionExpired):
            site.statements_of(bad, ACCT1)


def test_one_account_listing_one_id_twice_stops_the_list():
    """One id under two dates in one account's answer is one record's key
    for two statements, so the second would be taken for the first."""
    twice = {"accountDocumentLinks": {"STATEMENT": [entry(ACCT1, "2026-09-16", DOC1),
                                                    entry(ACCT1, "2026-08-15", DOC1)]}}
    with pytest.raises(site.ListStopped) as stop:
        site.statements_of(twice, ACCT1)
    assert "carry one id" in str(stop.value)
    assert ACCT1 not in str(stop.value) and DOC1 not in str(stop.value)


@pytest.mark.parametrize("resp", [
    Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 302, "text/html", b"", "https://security.firsthorizon.com/"),
    Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 401),
    Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 403, "text/plain", b"Invalid CSRF Token"),
    Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 200, "text/html", b"<html>Sign in</html>"),
    Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 200, "application/json", b"not json"),
], ids=["302", "401", "403", "html", "malformed json"])
def test_a_signed_out_links_answer_is_session_expired(resp):
    with pytest.raises(site.SessionExpired):
        site.read_links(resp)


@pytest.mark.parametrize("probe,ok", [
    (Resp(site.SESSION_URL, body=b'{"profiles": []}'), True),
    (Resp(site.SESSION_URL, body=b'{}'), False),
    (Resp(site.SESSION_URL, body=b'{"profiles": {}}'), False),
    (Resp(site.SESSION_URL, 302, "text/html", b"", "https://www.firsthorizon.com/SSO/Logout-Digital-Banking/"), False),
    (Resp(site.SESSION_URL, 401), False),
    (Resp(site.SESSION_URL, 200, "text/html", b"<html></html>"), False),
    (Resp(site.SESSION_URL, 200, "application/json", b"nope"), False),
])
def test_the_session_probe_wants_the_profiles_shape(probe, ok):
    bank = Bank([acct1()])
    bank.probe = probe
    assert site.signed_in(bank) is ok
    assert bank.context.request.asked == [(site.SESSION_URL, 0)]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_closed_panels_are_pressed_open_once_each_and_read_from_their_answers():
    bank = Bank([acct1(), acct2()])
    run = run_on(bank)
    got = site.collect_download_docs(bank, run)
    assert [(d.account, d.account_id, d.date_text, d.document_id, d.href) for d in got] == [
        ("Express Checking", ACCT1, "2026-09-16", DOC1, ""), ("Express Checking", ACCT1, "2026-08-15", DOC2, ""),
        ("Statement Savings", ACCT2, "2026-09-16", DOC3, ""), ("Statement Savings", ACCT2, "2026-07-17", DOC4, "")]
    assert bank.presses == [("panel", 0), ("panel", 1)]
    assert bank.context.request.asked == [(site.SESSION_URL, 0)], "only the probe is asked"
    for w in (NICK1, "8642", "975", ACCT1, DOC1):
        assert w in site.private_words(), w


def test_panels_open_on_load_are_bound_by_their_dates_and_never_pressed():
    bank = Bank([acct1(open=True), acct2(open=True), acct3()])
    got = site.collect_download_docs(bank, run_on(bank))
    assert {d.account_id for d in got} == {ACCT1, ACCT2, ACCT3}
    assert bank.presses == [("panel", 2)]


def test_an_answer_that_comes_after_the_page_is_ready_is_still_bound():
    bank = Bank([acct1(open=True), acct2()])
    bank.load_delay = 1000
    got = site.collect_download_docs(bank, run_on(bank))
    assert {d.account_id for d in got} == {ACCT1, ACCT2}


def test_a_panel_drawn_after_the_panels_were_read_stops_the_list():
    bank = Bank([acct1(), acct2(appear_at=2500)])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in stop.value.docs] == [ACCT1, ACCT1], "what was read is kept"
    assert bank.presses == [("panel", 0)]


# The walk ends with two reads of the panels, each after SETTLE_MS, so a
# panel drawn up to 3 s after the walk ends is seen. This fake bank answers
# at once, so for one account open on load that is 4.5 s after load, and
# for one pressed open, 6 s.
@pytest.mark.parametrize("open_on_load,appear_at", [
    (True, 3000), (True, 3500), (True, 4500), (False, 4000), (False, 5000), (False, 6000)])
def test_a_panel_drawn_late_within_the_two_reads_stops_the_list(open_on_load, appear_at):
    bank = Bank([acct1(open=open_on_load), acct2(appear_at=appear_at)])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in stop.value.docs] == [ACCT1, ACCT1], "what was read is kept"
    assert NICK2 in site.private_words()


@pytest.mark.parametrize("open_on_load,appear_at", [(True, 4750), (False, 6250)])
def test_a_panel_drawn_after_the_two_reads_is_not_seen(open_on_load, appear_at):
    """The ceiling in KNOWN CEILINGS. A panel drawn after the second read is
    not seen, and the list read before it is returned."""
    bank = Bank([acct1(open=open_on_load), acct2(appear_at=appear_at)])
    got = site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in got] == [ACCT1, ACCT1]


def test_the_two_reads_wait_no_longer_than_twice_the_settle():
    """With one account open on load the walk presses nothing, and after the
    load is bound the page is waited on for the settled titles and then for
    exactly the two reads, no more."""
    bank = Bank([acct1(open=True)])
    got = site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in got] == [ACCT1, ACCT1]
    assert bank.presses == []
    assert bank.waits == [site.SETTLE_MS] * 3


def test_a_panel_open_on_load_takes_the_product_of_its_settled_title():
    bank = Bank([acct1(open=True, title_at=1000), acct2()])
    got = site.collect_download_docs(bank, run_on(bank))
    assert {(d.account, d.account_id) for d in got} == {
        ("Express Checking", ACCT1), ("Statement Savings", ACCT2)}
    assert bank.presses == [("panel", 1)]


@pytest.mark.parametrize("hidden_at", [0, 2000], ids=["on load", "after the walk"])
def test_a_hidden_panel_stops_the_list(hidden_at):
    bank = Bank([acct1(open=True, hidden_at=hidden_at), acct2(open=True)])
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == []


def test_a_panel_drawn_late_is_private_before_it_is_pressed(monkeypatch):
    bank = Bank([acct1(), acct2(appear_at=1000)])
    asked = []

    def click(page, locator, *, css, what, words, step="press a control", **kw):
        asked.append(NICK2 in site.private_words() and "9753" in site.private_words())
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    got = site.collect_download_docs(bank, run_on(bank))
    assert {d.account_id for d in got} == {ACCT1, ACCT2}
    assert asked == [True, True]


def every_drawn_title_private(asked, monkeypatch):
    """The core's press, as the made-up bank's, noting at each press whether
    the nickname of every panel drawn then is a private word."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        nicks = [page.accounts[i]["title"].split(" (", 1)[0] for i in page.drawn_now()]
        asked.append(all(n in site.private_words() for n in nicks))
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)


def test_a_panel_drawn_late_ahead_of_one_not_walked_is_never_pressed(monkeypatch):
    """A panel drawn after the panels were read, ahead of one not walked
    yet, moves that one a place on, so the panel at its index is the late
    one. The list stops there, the late panel is not pressed, and its title
    is private."""
    bank = Bank([acct1(), acct2(appear_at=2500), acct3()])
    asked = []
    every_drawn_title_private(asked, monkeypatch)
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == [("panel", 0)], "the late panel is never pressed"
    assert asked == [True]
    assert [d.account_id for d in stop.value.docs] == [ACCT1, ACCT1], "what was read is kept"
    for w in (NICK2, "9753"):
        assert w in site.private_words(), w


def test_two_open_panels_that_cannot_be_told_apart_stop_the_list():
    same = [("2026-09-16", DOC5)]
    bank = Bank([acct1(open=True, statements=[("2026-09-16", DOC1)]), acct3(open=True, statements=same)])
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == []


def test_an_unclaimed_answer_on_load_stops_the_list():
    bank = Bank([acct1()])
    bank.extra_on_load = [links_resp(ACCT2, [("2026-09-16", DOC3)])]
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == []


def test_two_answers_for_one_press_stop_the_list():
    bank = Bank([acct1()])
    bank.links_override[ACCT1] = [links_resp(ACCT1, [("2026-09-16", DOC1)])] * 2
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(bank, run_on(bank))


def test_cards_that_differ_from_the_answer_stop_the_list():
    bank = Bank([acct1()])
    bank.cards_override = {ACCT1: ["2026-09-16"]}
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(bank, run_on(bank))


def test_an_unreadable_title_is_skipped_and_the_list_is_not_called_whole():
    bank = Bank([acct1(title=f"{NICK1} Express Checking 8642"), acct2()])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in stop.value.docs] == [ACCT2, ACCT2]
    assert bank.presses == [("panel", 1)]
    assert NICK1 in site.private_words(), "an unreadable title is still private"


def test_a_signed_out_answer_dialog_or_page_is_session_expired():
    bank = Bank([acct1()])
    bank.links_override[ACCT1] = [Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 401)]
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(bank, run_on(bank))
    bank = Bank([acct1()])
    bank.on_goto = lambda b: setattr(b, "dialog", True)
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == []
    bank = Bank([acct1()])
    bank.on_goto = lambda b: setattr(b, "url", "https://security.firsthorizon.com/fhnsso/login")
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(bank, run_on(bank))
    bank = Bank([acct1()])
    bank.probe = Resp(site.SESSION_URL, 302, "text/html", b"", "https://www.firsthorizon.com/")
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(bank, run_on(bank))
    assert bank.presses == [], "nothing is pressed after a signed-out probe"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_the_deadline_counts_from_the_probe_and_stops_discovery():
    clock = Clock()
    bank = Bank([acct1(), acct2()])
    run = run_on(bank, clock)
    original = bank.click

    def slow(loc):
        clock.t += site.DEADLINE_S
        original(loc)
    bank.click = slow
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert bank.presses == [("panel", 0)], "nothing is pressed past the deadline"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def take(bank, tmp_path, run=None, acct=ACCT1, product="Express Checking", doc=DOC1, date="2026-09-16"):
    out = tmp_path / "o.pdf"
    dl_dir = tmp_path / "dl"
    dl_dir.mkdir(exist_ok=True)
    trace = []
    ok = site.download_statement(bank, run or run_on(bank), dl_dir, out, account_id=acct, product=product,
                                 document_id=doc, iso_date=date, trace=trace)
    return ok, out, trace


@pytest.mark.parametrize("how", ["popup", "popup-late", "opener", "chromium", "chromium-blank",
                                 "popup-stays"])
def test_the_bound_card_is_pressed_once_and_its_download_taken(tmp_path, how):
    bank = Bank([acct1(), acct2()], download=how)
    ok, out, _ = take(bank, tmp_path)
    assert ok and out.read_bytes() == PDF
    assert bank.presses == [("panel", 0), ("download", 0, "2026-09-16")]


def test_same_product_and_date_in_two_accounts_takes_the_recorded_one(tmp_path):
    bank = Bank([acct1(), acct3()])
    ok, _out, _ = take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert ok
    assert bank.presses == [("panel", 0), ("panel", 1), ("download", 1, "2026-09-16")]


def test_same_document_id_in_two_accounts_is_two_records(tmp_path):
    bank = Bank([acct1(statements=[("2026-09-16", DOC1)]), acct3(statements=[("2026-09-16", DOC1)])])
    got = site.collect_download_docs(bank, run_on(bank))
    assert {(d.account_id, d.document_id) for d in got} == {(ACCT1, DOC1), (ACCT3, DOC1)}
    tmp = tmp_path / "app"
    tmp.mkdir()
    app = make_app(tmp, "--discover")
    for r in got:
        app._record_rawdoc(r, site.BILLING_URL)
    assert len(app.discovery.data) == 2
    ok, _out, _ = take(Bank([acct1(statements=[("2026-09-16", DOC1)]),
                             acct3(statements=[("2026-09-16", DOC1)])]), tmp_path, acct=ACCT3)
    assert ok


@pytest.mark.parametrize("change", ["account gone", "statement gone", "other date",
                                    "bad record", "other product"])
def test_no_single_match_means_no_card_is_pressed(tmp_path, change):
    kw = {}
    accounts = [acct1(), acct2()]
    bank = Bank(accounts)
    if change == "account gone":
        bank = Bank([acct2()])
    elif change == "statement gone":
        bank = Bank([acct1(statements=[("2026-08-15", DOC2)])])
    elif change == "other date":
        kw = {"date": "2026-09-15"}
    elif change == "bad record":
        kw = {"doc": ".."}
    elif change == "other product":
        kw = {"product": "Statement Savings"}
    ok, out, _ = take(bank, tmp_path, **kw)
    assert not ok
    assert not [p for p in bank.presses if p[0] == "download"]
    assert not out.exists()


@pytest.mark.parametrize("change", ["two cards", "panel off", "page off address"])
def test_a_page_that_stops_the_list_stops_the_run_while_a_statement_is_sought(monkeypatch, tmp_path,
                                                                            change):
    bank = Bank([acct1(), acct2()])
    if change == "two cards":
        bank.cards_override = {ACCT1: ["2026-09-16", "2026-09-16", "2026-08-15"]}
    elif change == "panel off":
        turned_off(monkeypatch, site.PANEL)
    else:
        bank.on_goto = lambda b: setattr(b, "url", f"https://{HOST}/#accounts")
    with pytest.raises(site.pressing.Stop) as stop:
        take(bank, tmp_path)
    assert stop.value.reason == "the statements page stopped"
    # A Resume would open the same page for its first statement (#124).
    assert stop.value.list_unread
    assert not [p for p in bank.presses if p[0] == "download"]
    assert not (tmp_path / "o.pdf").exists()


def test_one_product_on_a_single_open_accordion_opens_only_up_to_the_account(tmp_path):
    bank = Bank([acct1(), acct3()], single_open=True)
    ok, _out, _ = take(bank, tmp_path)
    assert ok
    assert bank.presses == [("panel", 0), ("download", 0, "2026-09-16")]
    bank = Bank([acct1(), acct3()], single_open=True)
    ok, _out, _ = take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert ok
    assert bank.presses == [("panel", 0), ("panel", 1), ("download", 1, "2026-09-16")]


def test_a_panel_open_on_load_is_looked_at_before_any_panel_is_pressed(tmp_path):
    bank = Bank([acct1(), acct3(open=True)], single_open=True)
    ok, _out, _ = take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert ok
    assert bank.presses == [("download", 1, "2026-09-16")]


def test_a_panel_drawn_late_ahead_of_the_account_stops_the_run_rather_than_review(monkeypatch, tmp_path):
    """The late panel takes the index of the account's own panel, which is
    not pressed yet. Pressing it would find another account there and send
    the statement to review. The run stops instead, with the late panel
    never pressed."""
    bank = Bank([acct1(), acct2(appear_at=2500), acct3()])
    asked = []
    every_drawn_title_private(asked, monkeypatch)
    with pytest.raises(site.pressing.Stop) as stop:
        take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert stop.value.reason == "the statements page stopped"
    assert bank.presses == [("panel", 0)], "the late panel is never pressed"
    assert asked == [True]
    assert not (tmp_path / "o.pdf").exists()


def test_a_panel_drawn_late_after_the_account_is_found_is_private_before_the_card_is_pressed(
        monkeypatch, tmp_path):
    bank = Bank([acct1(), acct2(appear_at=2500)])
    asked = []
    every_drawn_title_private(asked, monkeypatch)
    ok, _out, _ = take(bank, tmp_path)
    assert ok
    assert bank.presses == [("panel", 0), ("download", 0, "2026-09-16")]
    assert asked == [True, True]


def test_an_account_drawn_late_is_never_called_gone(tmp_path):
    """The account's own panel drawn only after the panels were read is not
    walked, so the account is not found. The panels did not hold still, so
    the run stops rather than send the statement to review."""
    bank = Bank([acct1(), acct3(appear_at=2500)])
    with pytest.raises(site.pressing.Stop) as stop:
        take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert stop.value.reason == "the statements page stopped"
    assert bank.presses == [("panel", 0)]
    assert NICK3 in site.private_words()


@pytest.mark.parametrize("appear_at", [3500, 5000])
def test_an_account_drawn_late_within_the_two_reads_is_never_called_gone(tmp_path, appear_at):
    bank = Bank([acct1(), acct3(appear_at=appear_at)])
    with pytest.raises(site.pressing.Stop) as stop:
        take(bank, tmp_path, acct=ACCT3, doc=DOC5)
    assert stop.value.reason == "the statements page stopped"
    assert bank.presses == [("panel", 0)]


@pytest.mark.parametrize("how,reason", [("two", "more than one"), ("none", "no download"),
                                        ("chromium-stuck", "would not close"),
                                        ("chromium-unreadable", "url unreadable"),
                                        ("chromium-two", "two popups")])
def test_a_download_that_is_not_exactly_one_stops_the_run(tmp_path, how, reason):
    bank = Bank([acct1()], download=how)
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert not (tmp_path / "o.pdf").exists()
    assert all(p.closed or p.stuck for p in bank.popups), "every page the press made is closed"


def test_a_download_from_another_statement_address_stops_the_run(tmp_path):
    bank = Bank([acct1()], download="popup")
    bank.download_url = API + file_of(ACCT1, "2026-08-15", DOC2)
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert bank.downloads[0].canceled
    assert not (tmp_path / "o.pdf").exists()


def test_a_pdf_answer_or_popup_that_is_signed_out_is_session_expired(tmp_path):
    bank = Bank([acct1()], download="popup")
    bank.pdf_status = 302
    with pytest.raises(site.SessionExpired):
        take(bank, tmp_path)
    bank = Bank([acct1()], download="signin")
    with pytest.raises(site.SessionExpired):
        take(bank, tmp_path)


def test_a_download_pending_before_the_press_stops_the_run(tmp_path):
    bank = Bank([acct1()])
    (tmp_path / "dl").mkdir()
    (tmp_path / "dl" / "x.crdownload").write_bytes(b"")
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert not [p for p in bank.presses if p[0] == "download"]


def test_the_deadline_stops_before_the_download_press(tmp_path):
    clock = Clock()
    bank = Bank([acct1()])
    run = run_on(bank, clock)
    original = bank.click

    def slow(loc):
        original(loc)
        clock.t += site.DEADLINE_S
    bank.click = slow
    with pytest.raises(site.DeadlineReached):
        take(bank, tmp_path, run=run)
    assert bank.presses == [("panel", 0)]


# ---------------------------------------------------------------------------
# The site layer presses nothing itself
# ---------------------------------------------------------------------------

SITE = ast.parse((HERE / "firsthorizon_site.py").read_text(encoding="utf-8"))


def test_the_site_layer_presses_posts_and_pings_nothing_itself():
    called = {n.func.attr for n in ast.walk(SITE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for verb in ("dblclick", "tap", "fill", "type", "press", "select_option", "check", "uncheck",
                 "set_input_files", "dispatch_event", "press_sequentially", "hover", "focus",
                 "set_checked", "drag_to", "press_once", "post", "put", "patch", "fetch"):
        assert verb not in called, verb
    attrs = {n.attr for n in ast.walk(SITE) if isinstance(n, ast.Attribute)}
    assert not attrs & {"mouse", "keyboard", "touchscreen"}
    assert not [k for k in ast.walk(SITE) if isinstance(k, ast.keyword) and k.arg == "force"]
    strings = [n.value for n in ast.walk(SITE) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if "login/ping" in s and "\n" not in s]


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
    assert sorted(guards) == ["is_account_panel", "is_download_button"]
    for js in (site._STATE_JS, site._LABELS_JS, site._TIMEOUT_JS):
        assert ".click" not in js and "dispatchEvent" not in js and ".submit" not in js


def turned_off(monkeypatch, off_css):
    """The core's press, as it answers a control the page has turned off:
    nothing is pressed and TurnedOff is raised, for `off_css` only."""
    def click(page, locator, *, css, what, words, step="press a control", **kw):
        assert css in (site.PANEL, site.DOWNLOAD_BUTTON)
        if css == off_css:
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)


def test_a_turned_off_panel_stops_the_list_with_nothing_pressed(monkeypatch):
    turned_off(monkeypatch, site.PANEL)
    bank = Bank([acct1(), acct2()])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert "turned off" in str(stop.value)
    assert bank.presses == []
    assert stop.value.docs == []


def test_a_turned_off_download_pdf_is_left_for_the_next_run(monkeypatch, tmp_path):
    turned_off(monkeypatch, site.DOWNLOAD_BUTTON)
    bank = Bank([acct1(), acct2()])
    got, out, trace = take(bank, tmp_path)
    assert got is None
    assert bank.presses == [("panel", 0)], "nothing was pressed on the card"
    assert bank.downloads == [] and bank.popups == []
    assert not out.exists() and not list((tmp_path / "dl").iterdir())
    assert {"note": "the statement's control was turned off"} in trace
    assert not bank.listeners["download"], "the press's listeners are removed"


@pytest.mark.parametrize("off_css", [site.PANEL, site.DOWNLOAD_BUTTON], ids=["panel", "card"])
def test_a_turned_off_press_that_used_up_the_deadline_stops_at_once(monkeypatch, tmp_path, off_css):
    clock = Clock()
    bank = Bank([acct1()])
    run = run_on(bank, clock)
    run.start()

    def click(page, locator, *, css, what, words, step="press a control", **kw):
        if css == off_css:
            clock.t += site.DEADLINE_S + 1   # the press's wait ran out the budget
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    with pytest.raises(site.DeadlineReached):
        take(bank, tmp_path, run=run)
    assert not [p for p in bank.presses if p[0] == "download"]
    assert not (tmp_path / "o.pdf").exists()
    assert not bank.listeners["download"], "the press's listeners are removed"


def test_a_turned_off_statement_records_nothing_and_the_run_goes_on(monkeypatch, tmp_path):
    app = make_app(tmp_path, "--all")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    app.check_session = lambda page: None
    turned_off(monkeypatch, site.DOWNLOAD_BUTTON)
    with redirect_stdout(io.StringIO()) as said:
        app.process(app._select())
    assert "left for the next run" in said.getvalue()
    assert app.progress.data == {}, "no record, so the next run asks again"
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert not (app.paths.diagnostics / "download-attempt.json").exists()
    assert not list(app.paths.root.rglob("*.pdf"))
    assert not [p for p in bank.presses if p[0] == "download"]


def test_a_turned_off_panel_while_a_statement_is_sought_stops_the_run(monkeypatch, tmp_path):
    app = make_app(tmp_path, "--all")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    app.check_session = lambda page: None
    turned_off(monkeypatch, site.PANEL)
    with redirect_stdout(io.StringIO()), pytest.raises(site.pressing.Stop):
        app.process(app._select())
    assert app.progress.data == {}, "nothing is marked for review"
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert bank.presses == [("panel", 0)], "the panel pressed in discovery only"


def test_the_record_key_is_the_hash_alone():
    one = docs.Document(title="Bank Statement", account="Express Checking", account_id=ACCT1,
                        document_id=DOC1, date="2026-09-16")
    renamed = docs.Document(title="Bank Statement", account="Everyday Checking", account_id=ACCT1,
                            document_id=DOC1, date="2026-09-16")
    other = docs.Document(title="Bank Statement", account="Express Checking", account_id=ACCT3,
                          document_id=DOC1, date="2026-09-16")
    assert one.key == renamed.key == "id:" + site.record_hash(ACCT1, DOC1)[:20]
    assert one.key != other.key
    for w in (ACCT1, DOC1, "Checking"):
        assert w not in one.key


def test_a_panel_already_open_is_never_pressed():
    bank = Bank([acct1(open=True)])
    run = run_on(bank)
    site._open(bank, run)
    with pytest.raises(site.ListStopped):
        site._expand(bank, run, 0, "accordion-0")
    assert bank.presses == []


@pytest.mark.parametrize("region", ["accordion-1", ""], ids=["another region", "no region"])
def test_a_panel_is_pressed_only_in_the_region_it_was_read_in(region):
    bank = Bank([acct1(), acct2()])
    run = run_on(bank)
    site._open(bank, run)
    with pytest.raises(site.ListStopped):
        site._expand(bank, run, 0, region)
    assert bank.presses == []


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------

def make_app(tmp, *args):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


def wire(app, bank, tmp_path):
    app.page = lambda: bank
    app._on_its_site = lambda: bank
    app._dl_dir = tmp_path / "dl"
    app._dl_dir.mkdir(exist_ok=True)
    app.run.attach(bank.context)


def test_records_carry_the_product_and_no_address(tmp_path):
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1(), acct2()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    text = app.paths.discovery_json.read_text()
    assert "?" not in text and "/statement/" not in text
    for word in (NICK1, NICK2, "8642", "9753", TITLE1):
        assert word not in text
    for key, rec in app.discovery.data.items():
        assert ACCT1 not in key and DOC1 not in key
    rec = [r for r in app.discovery.data.values() if r["document_id"] == DOC1][0]
    assert (rec["account"], rec["account_id"], rec["href"], rec["summary"]) == \
        ("Express Checking", ACCT1, "", "Bank Statement")
    assert docs.told_apart_by(rec) == site.record_hash(ACCT1, DOC1)[:6]
    assert DOC1 not in docs.told_apart_by(rec)
    from paperpull_core import listing
    assert listing.last(app) == listing.COMPLETE


def test_two_accounts_of_one_date_save_two_files(tmp_path):
    app = make_app(tmp_path, "--all")
    bank = Bank([acct1(), acct3()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
        app.check_session = lambda page: None
        app.process([d for d in app._select() if d.date == "2026-09-16"])
    names = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
    assert len(names) == 2, names
    assert "2026-09-16 First Horizon Bank Statement.pdf" in names
    for n in names:
        for w in PRIVATE:
            assert w not in n


def test_a_product_the_bank_renames_leaves_no_statement_behind(tmp_path):
    """A product the bank renames between a listing and the run keeps every
    record's key, and the next listing gives the records the new product,
    which is what the run looks for, so no statement is sent to review."""
    from paperpull_core.models import State
    app = make_app(tmp_path, "--all")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    keys = set(app.discovery.data)
    bank.accounts[0]["title"] = f"{NICK1} (Everyday Checking) (*8642) $86,975.31"
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    assert set(app.discovery.data) == keys, "the key scheme is unchanged"
    assert {r["account"] for r in app.discovery.data.values()} == {"Everyday Checking"}
    app.check_session = lambda page: None
    app.write_failure = lambda *a, **k: None
    with redirect_stdout(io.StringIO()):
        app.process(app._select())
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert len([p for p in bank.presses if p[0] == "download"]) == 2
    assert {r["state"] for r in app.progress.data.values()} == {State.COMPLETED.value}


def test_an_expired_session_stops_the_run_and_records_nothing(tmp_path):
    app = make_app(tmp_path, "--all")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    app.check_session = lambda page: None
    bank.probe = Resp(site.SESSION_URL, 401)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.process(app._select())
    assert "signed out" in said.getvalue()
    assert app.progress.data == {}
    assert app.stats["manual_review"] + app.stats["failed"] == 0


def test_an_expired_session_during_discovery_stops_the_run(tmp_path):
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1()])
    bank.links_override[ACCT1] = [Resp(f"{API}/v4/edocs/accounts/{ACCT1}/links", 403)]
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert app.discovery.data == {}
    assert "signed out" in said.getvalue() and "Press Enter" not in said.getvalue()


def test_a_list_that_stopped_partway_is_kept_and_never_called_whole(tmp_path):
    from paperpull_core import listing
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1(), acct2()])
    bank.cards_override = {ACCT2: ["2026-09-16"]}
    wire(app, bank, tmp_path)
    app.write_failure = lambda *a, **k: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as stop:
        app.cmd_discover()
    assert stop.value.code == 1
    assert len(app.discovery.data) == 2
    assert listing.last(app) != listing.COMPLETE
    assert "First Horizon statement list stopped partway" in said.getvalue()


def key_of(app, doc_id):
    return [k for k, r in app.discovery.data.items() if r["document_id"] == doc_id][0]


def without_times(records):
    return {k: {f: v for f, v in r.items() if f != "updated_at"} for k, r in records.items()}


@pytest.mark.parametrize("held_by", ["discovery", "progress"])
def test_an_id_seen_again_under_another_date_stops_the_list_and_keeps_its_record(tmp_path, held_by):
    """The record's key holds no date. Were the bank's statement id a place
    in its list rather than the statement's own, a new statement would come
    with an old one's id and be skipped as done. The list stops instead,
    and the record stands as it was."""
    import copy
    from paperpull_core import listing
    from paperpull_core.models import State
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    key = key_of(app, DOC1)
    app.progress.update(key, dict(app.discovery.get(key), state=State.COMPLETED.value,
                                  downloaded_ok=True))
    if held_by == "progress":
        # A discovery.json lost since, with the saved statement's record left.
        del app.discovery.data[key]
    before = copy.deepcopy((app.discovery.data, app.progress.data))
    # The id moves on to a new statement, and the one it named is gone.
    bank.accounts[0]["statements"] = [("2026-10-16", DOC1), ("2026-08-15", DOC2)]
    app.write_failure = lambda *a, **k: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as stop:
        app.cmd_discover()
    assert stop.value.code == 1
    assert "one statement id under two dates" in said.getvalue()
    assert (app.discovery.data, app.progress.data) == before
    assert listing.last(app) != listing.COMPLETE
    for w in (ACCT1, DOC1):
        assert w not in said.getvalue()


def test_an_id_seen_again_under_its_own_date_changes_nothing(tmp_path):
    from paperpull_core import listing
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1(), acct2()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    before = without_times(app.discovery.data)
    with redirect_stdout(io.StringIO()):
        assert app.cmd_discover() == 0
    assert without_times(app.discovery.data) == before
    assert listing.last(app) == listing.COMPLETE


def test_a_record_kept_with_no_date_is_given_the_listed_one(tmp_path):
    """An older record with no date is filled in, never taken for a
    statement of another date."""
    from paperpull_core import listing
    from paperpull_core.models import State
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct1()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    key = key_of(app, DOC1)
    app.discovery.data[key]["date"] = ""
    app.progress.update(key, dict(app.discovery.get(key), state=State.COMPLETED.value))
    with redirect_stdout(io.StringIO()):
        assert app.cmd_discover() == 0
    assert app.discovery.get(key)["date"] == "2026-09-16"
    assert listing.last(app) == listing.COMPLETE


def test_an_account_listing_one_id_twice_stops_discovery(tmp_path):
    """What the accounts walked before it listed is kept."""
    from paperpull_core import listing
    app = make_app(tmp_path, "--discover")
    bank = Bank([acct2(), acct1(statements=[("2026-09-16", DOC1), ("2026-08-15", DOC1)])])
    wire(app, bank, tmp_path)
    app.write_failure = lambda *a, **k: None
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as stop:
        app.cmd_discover()
    assert stop.value.code == 1
    assert "carry one id" in said.getvalue()
    assert {r["document_id"] for r in app.discovery.data.values()} == {DOC3, DOC4}
    assert listing.last(app) != listing.COMPLETE


def test_the_run_stops_itself_before_the_bank_session_runs_out(tmp_path):
    clock = Clock()
    app = make_app(tmp_path, "--all")
    app.run = site.Run(clock=clock)
    bank = Bank([acct1(), acct2()])
    wire(app, bank, tmp_path)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    app.check_session = lambda page: None
    original = bank.click

    def slow(loc):
        original(loc)
        if loc.kind == "button":
            clock.t += 150
    bank.click = slow
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as stop:
        app.process(app._select())
    assert stop.value.code == 0
    # Pressed at 150, 300, 450 and 600 s of clock: the fourth lands on the
    # deadline, so its download is cancelled in the first wait.
    assert len([p for p in bank.presses if p[0] == "download"]) == 4
    assert "10-minute" in said.getvalue() and "Resume" in said.getvalue()
    assert app.stats["failed"] + app.stats["manual_review"] == 0
    assert len(app.progress.data) == 3


def test_the_deadline_during_discovery_stops_the_run(tmp_path):
    clock = Clock()
    app = make_app(tmp_path, "--discover")
    app.run = site.Run(clock=clock)
    bank = Bank([acct1(), acct2()])
    wire(app, bank, tmp_path)
    original = bank.click

    def slow(loc):
        original(loc)
        clock.t += site.DEADLINE_S
    bank.click = slow
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit) as stop:
        app.cmd_discover()
    assert stop.value.code == 0 and "10-minute" in said.getvalue()
    from paperpull_core import listing
    assert listing.last(app) != listing.COMPLETE


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
    assert json.loads((HERE / "config.example.json").read_text())["pilot_count"] == 1


def test_a_browser_of_its_own_opens_through_the_core_and_signs_in_on_the_example_port(
        tmp_path, monkeypatch):
    """With no cdp_url a run opens its own browser through the core, which
    says so, never straight through Playwright (#90), and the sign-in falls
    back to the port config.example.json names."""
    import playwright.sync_api
    app = make_app(tmp_path, "--discover")
    app.config.update({"cdp_url": "", "profile_dir": str(tmp_path / "profile")})
    seen = []

    class Ctx:
        def set_default_timeout(self, ms):
            pass

        def on(self, ev, f):
            pass

    class Chromium:
        def launch_persistent_context(self, user_data_dir, **kw):
            seen.append("playwright")
            return Ctx()

    class PW:
        chromium = Chromium()

        def start(self):
            return self

        def stop(self):
            pass

    def own(chromium, user_data_dir, **kw):
        seen.append("core")
        return chromium.launch_persistent_context(user_data_dir, **kw)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: PW())
    monkeypatch.setattr(docs.browser_launcher, "launch_own_browser", own)
    app.browser()
    assert seen == ["core", "playwright"]
    ports = []
    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser",
                        lambda profile, port, url, **kw: ports.append(port) or "Chrome")
    with redirect_stdout(io.StringIO()):
        app.cmd_open_browser()
    example = json.loads((HERE / "config.example.json").read_text())["cdp_url"]
    assert ports == [example.rsplit(":", 1)[1]]


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

def _ours(text, folder):
    """text without the two numbers a run makes that are not the
    account's. The test's folder is one pytest numbers ("pytest-48642"
    holds a masked tail), so it is taken out however it is written, and a
    journal entry's milliseconds since it began can be any number. The
    clock's stamps stay, since no number in PRIVATE is one a clock writes."""
    for written in (str(folder), json.dumps(str(folder))[1:-1], folder.as_posix()):
        text = text.replace(written, "<folder>")
    return re.sub(r'"(at_ms|elapsed_ms)": \d+', r'"\1": 0', text)


def _everything(app, said, folder):
    outside = [said]
    for p in app.paths.root.rglob("*"):
        outside.append(p.name)
        if p.is_file() and p.name not in ("discovery.json", "progress.json") and p.suffix != ".pdf" \
                and "backup" not in str(p).lower():
            outside.append(p.read_text(encoding="utf-8", errors="replace"))
    return _ours("\n".join(outside), folder)


def _capture_logs():
    seen = io.StringIO()
    handler = logging.StreamHandler(seen)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s %(args)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.DEBUG)
    return seen, handler, old


def test_nothing_private_leaves_on_a_run_that_works_or_reviews(tmp_path):
    app = make_app(tmp_path, "--pilot")
    bank = Bank([acct1(), acct2(open=True)])
    wire(app, bank, tmp_path)
    seen, handler, old = _capture_logs()
    try:
        with redirect_stdout(seen):
            app.cmd_discover()
            app.check_session = lambda p: None
            chosen = app._select()
            # The first saves; the second's account has gone from the page,
            # so nothing is pressed and it is left for review with a trace.
            first, second = chosen[0], [d for d in chosen if d.account_id != chosen[0].account_id][0]
            app.process([first])
            bank.accounts = [a for a in bank.accounts if a["id"] != second.account_id]
            bank.reset()
            app.process([second])
            app._pilot_report([first, second])
            app.write_run_summary()
    finally:
        logging.getLogger().removeHandler(handler)
        logging.getLogger().setLevel(old)
    said = seen.getvalue()
    assert "Saved:" in said
    assert any("download-attempt" in p.name for p in app.paths.root.rglob("*")), "a trace was written"
    everything = _everything(app, said, tmp_path)
    for word in PRIVATE + [TITLE1, TITLE2]:
        assert word not in everything, word
    records = _ours(app.paths.discovery_json.read_text() + app.paths.progress_json.read_text(), tmp_path)
    for word in (NICK1, NICK2, "8642", "9753", TITLE1):
        assert word not in records, word
    assert "Express" not in site.private_words() and "Checking" not in site.private_words(), \
        "the product is not private"


def test_nothing_private_leaves_on_runs_that_stop(tmp_path):
    for how in ("two", "chromium-two"):
        app = make_app(tmp_path / how, "--all") if (tmp_path / how).mkdir() is None else None
        bank = Bank([acct1(), acct2()], download=how)
        wire(app, bank, tmp_path / how)
        seen, handler, old = _capture_logs()
        try:
            with redirect_stdout(seen):
                app.cmd_discover()
                app.check_session = lambda p: None
                try:
                    app.process(app._select()[:1])
                except site.pressing.Stop as stop:
                    try:
                        site.pressing.stop_run(app, stop)
                    except SystemExit:
                        pass
        finally:
            logging.getLogger().removeHandler(handler)
            logging.getLogger().setLevel(old)
        everything = _everything(app, seen.getvalue(), tmp_path)
        for word in PRIVATE + [TITLE1, TITLE2]:
            assert word not in everything, (how, word)


# ---------------------------------------------------------------------------
# Review fixes: another tab, a popup that went elsewhere, waits past the
# deadline
# ---------------------------------------------------------------------------

class OtherTab:
    """A second First Horizon tab of the person's in the same context. Its
    answers and its popups are heard on the context and must be left alone."""

    def __init__(self, bank):
        self.bank, self.popups = bank, []

    def answer(self, acct, statements):
        self.bank.context.emit("response", links_resp(acct, statements, page=self))

    def signed_out(self, acct):
        self.bank.context.emit("response", links_err(acct, 401, page=self))

    def open_popup(self):
        pop = Popup(self, self.bank.context, known=True)
        self.popups.append(pop)
        self.bank.context.emit("page", pop)
        pop.go(API + file_of(ACCT2, "2026-07-17", DOC4))
        return pop


def test_another_tabs_answers_never_bind_a_panel_or_expire_the_run():
    bank = Bank([acct1(open=True), acct2()])
    other = OtherTab(bank)

    def noise(b):
        # Same dates as the open panel, a stray answer, and a sign-out, all
        # from the other tab.
        other.answer(ACCT3, [("2026-09-16", DOC5), ("2026-08-15", DOC2)])
        other.answer(ACCT2, [("2026-09-16", DOC3), ("2026-07-17", DOC4)])
        other.signed_out(ACCT3)
    bank.on_goto = noise
    original = bank.click

    def press(loc):
        original(loc)
        other.answer(ACCT3, [("2026-09-16", DOC5)])
    bank.click = press
    got = site.collect_download_docs(bank, run_on(bank))
    assert sorted({d.account_id for d in got}) == [ACCT1, ACCT2]
    assert bank.presses == [("panel", 1)]


def test_another_tabs_popup_is_neither_heard_nor_closed(tmp_path):
    bank = Bank([acct1()], download="popup")
    other = OtherTab(bank)
    original = bank.do_download

    def with_noise(url):
        theirs = other.open_popup()
        original(url)
        theirs.listeners["download"] and None
    bank.do_download = with_noise
    ok, out, _ = take(bank, tmp_path)
    assert ok and out.read_bytes() == PDF
    assert not other.popups[0].closed, "the other tab's popup is the person's"


def test_a_popup_that_went_elsewhere_and_closed_stops_the_run(tmp_path):
    bank = Bank([acct1()], download="popup-elsewhere")
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert bank.downloads[0].canceled
    assert not (tmp_path / "o.pdf").exists()


def test_a_download_with_no_answer_from_its_address_stops_the_run(tmp_path):
    bank = Bank([acct1()], download="popup")
    original = Popup.go

    def silent(self, url, *a, **k):
        self.url = url
    Popup.go = silent
    try:
        with pytest.raises(site.pressing.Stop):
            take(bank, tmp_path)
    finally:
        Popup.go = original
    assert not (tmp_path / "o.pdf").exists()


def test_a_wait_during_discovery_never_runs_past_the_deadline():
    clock = Clock()
    bank = Bank([acct1(open=True)])
    bank.load_delay = 60000
    bank.clock = clock
    run = run_on(bank, clock)
    run.start()
    clock.t += site.DEADLINE_S - 0.4      # 400 ms left
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert sum(bank.waits) <= 400.001, bank.waits
    assert bank.presses == []


def test_a_deadline_that_runs_out_in_the_second_read_cuts_its_wait():
    """One account open on load waits three SETTLE_MS in all, the last for
    the second read. With 3.5 s left that wait is cut to the 500 ms left,
    and the run stops at the deadline with nothing pressed."""
    clock = Clock()
    bank = Bank([acct1(open=True)])
    bank.clock = clock
    run = run_on(bank, clock)
    run.start()
    clock.t += site.DEADLINE_S - 3.5      # 3.5 s left
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert bank.waits[:2] == [site.SETTLE_MS] * 2, bank.waits
    assert bank.waits[2:] == [pytest.approx(500)], bank.waits
    assert bank.presses == []


def test_a_wait_for_the_download_never_runs_past_the_deadline(tmp_path):
    clock = Clock()
    bank = Bank([acct1()], download="none")
    run = run_on(bank, clock)
    original = bank.click

    def press(loc):
        original(loc)
        if loc.kind == "button":
            # The press lands with 600 ms left; the download would come later.
            clock.t = run.started + site.DEADLINE_S - 0.6
            bank.clock = clock
            bank.waits.clear()
    bank.click = press
    with pytest.raises(site.DeadlineReached):
        take(bank, tmp_path, run=run)
    assert sum(bank.waits) <= 600.001, bank.waits
    assert not (tmp_path / "o.pdf").exists()


def test_an_answer_another_tab_made_that_cannot_be_told_apart_stops_and_takes_nothing(tmp_path):
    bank = Bank([acct1()], download="chromium")
    other = OtherTab(bank)
    original = bank.do_download

    def with_noise(url):
        theirs = Popup(other, bank.context, known=False)
        other.popups.append(theirs)
        theirs.go(API + file_of(ACCT2, "2026-07-17", DOC4))
        bank.context.emit("page", theirs)
        original(url)
    bank.do_download = with_noise
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert not (tmp_path / "o.pdf").exists()
    assert not other.popups[0].closed


def test_the_real_chromium_ordering_with_the_blank_popup_left_open_saves_and_closes_it(tmp_path):
    """Measured 2026-10-12: the popup's answer comes first with no frame, the
    download is raised on the opener, and the popup is then left open with
    its url reading "". It is the one page the press made, it went to the
    statement's own address only, and it is closed and seen closed."""
    bank = Bank([acct1()], download="chromium-blank")
    ok, out, _ = take(bank, tmp_path)
    assert ok and out.read_bytes() == PDF
    assert len(bank.popups) == 1 and bank.popups[0].closed


def test_a_blank_popup_that_went_elsewhere_stops(tmp_path):
    bank = Bank([acct1()], download="chromium-blank")
    bank.download_url = API + file_of(ACCT1, "2026-08-15", DOC2)
    with pytest.raises(site.pressing.Stop):
        take(bank, tmp_path)
    assert bank.popups[0].closed
    assert not (tmp_path / "o.pdf").exists()


# -- every blocking call is held to the deadline ------------------------------

class Slow(Bank):
    """A bank whose blocking calls take time on the run's clock."""

    def __init__(self, *a, clock, cost, **kw):
        super().__init__(*a, **kw)
        self.clock_, self.cost, self.timeouts = clock, cost, []

    def goto(self, url, **kw):
        self.timeouts.append(("goto", kw.get("timeout")))
        self.clock_.t += self.cost.get("goto", 0)
        return super().goto(url, **kw)


def near_deadline(clock, run, left_s):
    run.start()
    clock.t = run.started + site.DEADLINE_S - left_s


def test_navigation_is_capped_and_a_crossing_stops():
    clock = Clock()
    bank = Slow([acct1()], clock=clock, cost={"goto": 5})
    run = run_on(bank, clock)
    near_deadline(clock, run, 3)
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert bank.timeouts == [("goto", 3000)]
    assert bank.presses == []


def test_the_probe_is_capped_and_a_crossing_stops():
    clock = Clock()
    bank = Bank([acct1()])
    run = run_on(bank, clock)
    near_deadline(clock, run, 2)
    asked = []
    real = bank.context.request.get

    def get(url, **kw):
        asked.append(kw.get("timeout"))
        clock.t += 4
        return real(url, **kw)
    bank.context.request.get = get
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert asked == [2000]
    assert bank.presses == []


def test_a_press_is_capped_and_a_crossing_stops(monkeypatch):
    clock = Clock()
    bank = Bank([acct1(), acct2()])
    run = run_on(bank, clock)
    timeouts = []

    def click(page, locator, *, css, what, words, step="press a control", timeout=None, **kw):
        timeouts.append(timeout)
        clock.t += 10
        page.click(locator)
    monkeypatch.setattr(site.pressing, "click", click)
    run.start()
    clock.t = run.started + site.DEADLINE_S - 5
    with pytest.raises(site.DeadlineReached):
        site.collect_download_docs(bank, run)
    assert timeouts == [5000], "the press got only the time left"
    assert bank.presses == [("panel", 0)], "nothing more after the press crossed the deadline"


def test_a_save_that_crosses_the_deadline_keeps_nothing(tmp_path):
    clock = Clock()
    bank = Bank([acct1()], download="chromium-blank")
    run = run_on(bank, clock)
    real_save = Download.save_as

    def slow_save(self, path):
        real_save(self, path)
        clock.t = run.started + site.DEADLINE_S + 1
    Download.save_as = slow_save
    try:
        with pytest.raises(site.DeadlineReached):
            take(bank, tmp_path, run=run)
    finally:
        Download.save_as = real_save
    assert not (tmp_path / "o.pdf").exists()


def test_a_statement_account_id_is_text_or_a_number_only():
    """The JSON may carry userAccountId as a number; the same digits are the
    same account. A bool, list or object never is, whatever it prints as."""
    good = {"documentName": "Statement 1/16/26", "documentDate": "2026-01-16", "type": "STATEMENT",
            "userAccountId": 1234, "endpoints": {"file": "/v4/edocs/accounts/1234/statement/2026-01-16/doc1"}}
    assert site.statements_of({"accountDocumentLinks": {"STATEMENT": [good]}}, "1234")
    for bad in (True, [1234], {"id": 1234}, None):
        import pytest
        with pytest.raises(site.ListStopped):
            site.statements_of({"accountDocumentLinks": {"STATEMENT": [dict(good, userAccountId=bad)]}}, "1234")


def test_a_title_that_finishes_drawing_during_the_wait_is_kept_beside_one_that_never_does():
    """One panel's title never reaches the shape; another's arrives late,
    after a few reads. The late one is listed, the other skipped, and the
    list is not called whole."""
    class LateBank(Bank):
        def __init__(self, accounts, late_title):
            super().__init__(accounts)
            self.reads = 0
            self.late_title = late_title

        def state(self):
            self.reads += 1
            st = super().state()
            if self.reads < 4:
                # The balance has not drawn yet: the title is cut short.
                st["panels"][1]["title"] = self.late_title.rsplit(" ", 1)[0]
                st["panels"][1]["labels"] = [st["panels"][1]["title"]]
            return st
    a2 = acct2()
    bank = LateBank([acct1(title=f"{NICK1} Express Checking 8642"), a2], a2["title"])
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(bank, run_on(bank))
    assert [d.account_id for d in stop.value.docs] == [ACCT2, ACCT2], "the late title was read once it drew"
    assert bank.presses == [("panel", 1)]
    assert bank.reads >= 4


def the_panel_reads_it_all_taken(monkeypatch, tmp_path, app):
    """What the control panel makes of this run's real records, by its own
    code. A run says nothing of a document it leaves, so these are what stop
    it settling a gap (#149)."""
    monkeypatch.syspath_prepend(str(HERE.parents[1] / "gui"))
    panel = pytest.importorskip("app")
    return panel._took_everything({"script_name": "firsthorizon_docs.py", "dir": str(tmp_path)},
                                  "primary", app.paths.root, {})


def test_a_statement_turned_off_is_left_for_the_panel_too(tmp_path, monkeypatch):
    """Its Run All lists the statement, leaves no record of it, finishes
    clean, and the next run takes it. Each of the two reads as it is."""
    bank = Bank([acct1(), acct2()])
    app = make_app(tmp_path, "--all")
    wire(app, bank, tmp_path)
    app.check_session = lambda page: None
    asked = []
    real = site.download_statement

    def noted(page, run, dl_dir, out_path, **kw):
        asked.append(kw["iso_date"])
        return real(page, run, dl_dir, out_path, **kw)

    def click(page, locator, *, css, what, words, step="press a control", **kw):
        if css == site.DOWNLOAD_BUTTON and len(asked) == 1:
            raise site.pressing.TurnedOff(step, "the control is turned off", ["turned off"])
        page.click(locator)

    with monkeypatch.context() as off:
        off.setattr(site, "download_statement", noted)
        off.setattr(site.pressing, "click", click)
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_discover()
            app.process(app._select())
    assert "left for the next run" in said.getvalue()
    assert app.stats["manual_review"] + app.stats["failed"] + app.stats["validation_failures"] == 0
    assert len(app.discovery.data) == len(app.progress.data) + 1
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is False
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
        app.process(app._select())
    assert len(app.discovery.data) == len(app.progress.data)
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is True
