"""Resume with no tab of the person's open on Report a Problem, in a real
browser.

A Discover that read both stores' lists to their end leaves Resume nothing
to read again, so Resume goes straight to the purchases found. An App Store
receipt is asked for from inside a tab on Report a Problem, and a call from
a tab anywhere else is refused before it is sent, since its path is
relative. Discovery opens Report a Problem in its tab, and processing did
not. At home the person usually still has the tab they signed in with,
which the app reuses, so it went unseen. With no such tab the app opened a
new blank one, every call was refused, and every purchase was recorded
failed with "No receipt came back", to be tried again by a next run that
met the same.

Processing opens Report a Problem in a tab that is not on it, as discovery
does, and when the page asks for a sign-in there the App Store side stops,
as it does in discovery. The person's own tab is still the one used when it
is open, and it is never loaded again or closed. The Apple Store's orders
are read in tabs the app opens for itself, at home as here, so they are
not part of this.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Apple's two sites are two made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches Apple. Every member, order, name and amount is
invented.
"""
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_receipts as app_mod
import apple_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

REPORT_HOST = "reportaproblem.apple.test"
STORE_HOST = "www.apple.test"

# Apple's two hosts are found on this machine, and every other name fails
# to resolve, this machine's own address aside, so a page the test forgot to
# point here goes nowhere.
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (REPORT_HOST, STORE_HOST))

TOKEN = "TESTTOKEN"
ORGANIZER, CHILD = "10000001", "10000002"

# Report a Problem signed in, whose own script keeps its session token as
# the page loads.
HOME = ("<!doctype html><html><head><title>Report a Problem</title></head><body>"
        "<h1>Report a Problem</h1><p>Found 4 results.</p>"
        "<script>sessionStorage.setItem('x-apple-xsrf-token', '%s')</script>"
        "</body></html>" % TOKEN)
# The same page, signed in, without the token.
NO_TOKEN = ("<!doctype html><html><head><title>Report a Problem</title></head><body>"
            "<h1>Report a Problem</h1><p>Found 4 results.</p></body></html>")
# Report a Problem signed out.
SIGN_IN = ("<!doctype html><html><head><title>Sign In</title></head><body>"
           "<h1>Sign in with your Apple Account</h1><input type='password'></body></html>")

FAMILY = {"members": [
    {"dsid": ORGANIZER, "givenName": "Dana", "familyName": "Example", "isHeadOfHousehold": True},
    {"dsid": CHILD, "givenName": "Quill", "familyName": "Example", "isHeadOfHousehold": False}]}


def bought(weborder, dsid, name, detail, paid, when, free=False):
    return {"purchaseId": "80000000000001", "dsid": dsid,
            "invoiceAmount": None if free else paid,
            "plis": [{"amountPaid": "$0.00" if free else paid, "isFreePurchase": free,
                      "quantity": 0 if free else 1,
                      "lineItemType": "IOSApp" if free else "BaseLineItem",
                      "localizedContent": {"nameForDisplay": name, "detailForDisplay": detail,
                                           "mediaType": "iOS App" if free else "In-App Purchase"}}],
            "weborder": weborder, "invoiceDate": None, "purchaseDate": when,
            "isPendingPurchase": False, "estimatedTotalAmount": paid}


# Three paid purchases and a free download, newest first as the search
# gives them, two batches of them.
GEMS = bought("MLF0TEST21", ORGANIZER, "Gem Pack 3", "Crystal Quarry", "$4.99",
              "2026-05-14T12:00:00Z")
FREE = bought("R00TEST0000021", ORGANIZER, "Lantern Notes", "Example Dev LLC", "$0.00",
              "2026-05-06T12:00:00Z", free=True)
BRICKS = bought("MLF0TEST22", CHILD, "400 Bricks", "Blockville", "$4.37",
                "2026-04-02T12:00:00Z")
PREMIER = bought("MLF0TEST23", ORGANIZER, "Premier", "Apple One", "$21.43",
                 "2025-11-20T12:00:00Z")
PAID = {p["weborder"]: p for p in (GEMS, BRICKS, PREMIER)}
BATCHES = {None: ([GEMS, FREE, BRICKS], "BATCH0002"), "BATCH0002": ([PREMIER], None)}

ALL_KEYS = ["App Store:MLF0TEST21", "App Store:MLF0TEST22", "App Store:MLF0TEST23"]

# Who is signed in, as the page's own call answers it.
LOGIN = {"dsid": ORGANIZER, "name": "Dana Example", "enableFamilyUI": True,
         "enableFamilyAPI": True}

# The Apple Store's order list, for an account with no orders there.
NO_ORDERS = ("<!doctype html><html><head><title>Your Orders</title></head><body>"
             "<h1>Your Orders</h1><script id='init_data' type='application/json'>%s</script>"
             "</body></html>" % json.dumps({"orderList": {"d": {"moreOrdersAvailable": False},
                                                          "c": []}}))


def receipt_html(weborder):
    """Apple's emailed receipt, as the invoice call hands it over."""
    raw = PAID[weborder]
    line = raw["plis"][0]["localizedContent"]
    return ("<html><head><style>body { font-family: sans-serif }</style></head><body>"
            "<h1>Receipt</h1><p>%s</p><p>Order ID: %s</p>"
            "<p>Document: 000000000001</p><p>Apple Account: dana@example.com</p>"
            "<table><tr><td>%s</td><td>%s</td><td>%s</td></tr></table>"
            "<p>Billing and Payment</p><p>Dana Example</p><p>Subtotal %s</p>"
            "</body></html>" % (raw["purchaseDate"][:10], weborder, line["detailForDisplay"],
                                line["nameForDisplay"], raw["invoiceAmount"], raw["invoiceAmount"]))


class FakeApple:
    """What the made-up sites answer, set by each test. Signed in, with the
    whole search, unless a test says otherwise."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.signed_in = True
        self.home = HOME
        # Every request, with the address of the page that made it, as the
        # browser said it in Referer.
        self.seen = []


SITE = FakeApple()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value, status=200):
        self._send(json.dumps(value).encode("utf-8"), "application/json", status)

    def _html(self, text):
        self._send(text.encode("utf-8"), "text/html; charset=utf-8")

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def _note(self, method, path):
        SITE.seen.append((self._host(), method, path, self.headers.get("Referer") or ""))

    def do_GET(self):
        host, path = self._host(), urlsplit(self.path).path
        self._note("GET", path)
        parts = path.strip("/").split("/")
        if host == REPORT_HOST and path == "/":
            self._html(SITE.home if SITE.signed_in else SIGN_IN)
        elif host == REPORT_HOST and path.startswith("/api/") and not SITE.signed_in:
            self._json({"errors": [{"message": "unauthorized"}]}, 401)
        elif host == REPORT_HOST and path == site.FAMILY_PATH:
            self._json(FAMILY)
        elif host == REPORT_HOST and path == site.LOGIN_PATH:
            self._json(LOGIN)
        elif host == REPORT_HOST and len(parts) == 4 and parts[:2] == ["api", "order"] \
                and parts[2] in PAID:
            self._json({"email": "dana@example.com", "invoice": receipt_html(parts[2]),
                        "refund": None, "vat": None})
        elif host == STORE_HOST and path == "/shop/order/list":
            self._html(NO_ORDERS)
        else:
            self.send_error(404)

    def do_POST(self):
        host, path = self._host(), urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self._note("POST", path)
        if host == REPORT_HOST and path == site.SEARCH_PATH and SITE.signed_in:
            purchases, following = BATCHES.get(body.get("batchId"), ([], None))
            self._json({"batchId": body.get("batchId"), "nextBatchId": following,
                        "query": body, "purchases": purchases})
        elif host == REPORT_HOST and path == site.SEARCH_PATH:
            self._json({"errors": [{"message": "unauthorized"}]}, 401)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    """Playwright's own Chromium, found the way the app finds it in its
    bundled mode, so it is never the person's everyday browser."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation. That tab is on a page of the
    helper's own, not on either of Apple's sites, so no tab of the person's
    is open there unless a test opens one."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def tabs(cdp_url):
    """Every tab the browser has, as its own debugging port lists them."""
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read()) if t.get("type") == "page"]


def on_the_sites(cdp_url):
    """The tabs on either of Apple's made-up sites."""
    return [t for t in tabs(cdp_url)
            if urlsplit(t.get("url") or "").hostname in (REPORT_HOST, STORE_HOST)]


def close_tab(cdp_url, tab_id):
    urllib.request.urlopen("%s/json/close/%s" % (cdp_url, tab_id), timeout=10).read()


def open_their_tab(cdp_url, address, title):
    """A tab the person signed in with at home, opened by the browser
    itself the way login.bat's is, once it has drawn its page. Its id."""
    made = json.loads(urllib.request.urlopen(urllib.request.Request(
        cdp_url + "/json/new?" + address, method="PUT"), timeout=15).read())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any(t.get("id") == made.get("id") and t.get("title") == title
               for t in tabs(cdp_url)):
            return made["id"]
        time.sleep(0.2)
    pytest.fail("the tab for %s never drew" % address)


@pytest.fixture(autouse=True)
def no_tab_on_the_sites(attached):
    """Each test starts with no tab on either site, and a tab a run left open
    for the person to sign in is closed after its test."""
    for tab in on_the_sites(attached):
        close_tab(attached, tab["id"])
    yield
    for tab in on_the_sites(attached):
        close_tab(attached, tab["id"])


@pytest.fixture(autouse=True)
def fake_apple(server, monkeypatch):
    """Both of Apple's sites are the made-up ones, and every pause and wait
    is short."""
    SITE.reset()
    report = "http://%s:%d/" % (REPORT_HOST, server)
    store = "http://%s:%d/shop/order/list" % (STORE_HOST, server)
    monkeypatch.setattr(site, "REPORT_HOST", REPORT_HOST)
    monkeypatch.setattr(site, "REPORT_URL", report)
    monkeypatch.setattr(site, "STORE_LIST_URL", store)
    for name in ("home", "login", "orders"):
        monkeypatch.setitem(site.URLS, name, report)
    monkeypatch.setitem(site.URLS, "store_orders", store)
    # Every call is only made from a tab on one of Apple's own hosts. Here
    # those hosts are the made-up ones.
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (REPORT_HOST, STORE_HOST))
    monkeypatch.setattr(site, "STORE_PAUSE_MS", 0)
    real_walk = site.walk_purchases
    monkeypatch.setattr(site, "walk_purchases",
                        lambda page, dsids, **kw: real_walk(page, dsids, **dict(kw, pause_ms=0)))
    real_list = site.goto_store_list
    monkeypatch.setattr(site, "goto_store_list",
                        lambda page, wait_ms=20000: real_list(page, wait_ms=min(wait_ms, 1500)))
    real_open = site.open_report_page
    monkeypatch.setattr(site, "open_report_page",
                        lambda page, wait_ms=30000: real_open(page, wait_ms=min(wait_ms, 1500)))
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def folded(out):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(out.split())


def stopped_run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to stop rather than finish. Leaving on SystemExit
    with the exception in flight is what the core reports to the panel as
    stopped. What it printed, unfolded."""
    cfg = config_for(tmp_path, cdp_url)
    with pytest.raises(SystemExit) as stopped:
        app_mod.main([*flags, "--config", str(cfg)])
    out = capsys.readouterr().out
    assert stopped.value.code == 0, out
    return out


def finished_run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to finish. What it printed, unfolded."""
    cfg = config_for(tmp_path, cdp_url)
    assert app_mod.main([*flags, "--config", str(cfg)]) == 0
    return capsys.readouterr().out


def panel_reads(out):
    """The counts the panel reads, off the line the core prints for it."""
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def progress(tmp_path):
    path = tmp_path / "out" / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def downloaded(tmp_path):
    """The purchases whose receipt was saved and passed its check."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("downloaded_ok")
                  and Path(r.get("pdf_path") or "").is_file())


def failed(tmp_path):
    """The purchases recorded as failed."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("state") == State.FAILED.value)


def receipt_calls():
    """The address of the page that asked for each receipt."""
    return [referer for host, method, path, referer in SITE.seen
            if host == REPORT_HOST and path.endswith("/invoice.html")]


def report_pages_loaded():
    return [path for host, method, path, _referer in SITE.seen
            if host == REPORT_HOST and method == "GET" and path == "/"]


# -- Resume after a Discover that read both lists whole ------------------------------

def test_resume_with_no_tab_of_theirs_open_downloads_every_receipt(attached, server, tmp_path,
                                                                    capsys):
    """Discover read both lists to their end and closed the tabs it opened.
    Resume asked every receipt from a new blank tab, each call was refused
    before it was sent, and every purchase was recorded failed with no
    receipt, run after run. Report a Problem is opened first now, and every
    receipt is asked for from it."""
    finished_run(tmp_path, attached, capsys, "--discover")
    assert not on_the_sites(attached), "discovery closed the tabs it opened"

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == ALL_KEYS, folded(out)
    assert not failed(tmp_path)
    assert panel_reads(out)["failed"] == 0 and panel_reads(out)["stopped"] == 0
    assert set(receipt_calls()) == {"http://%s:%d/" % (REPORT_HOST, server)}, \
        "every receipt was asked for from Report a Problem's own page"
    assert not on_the_sites(attached), "and the run closed the tab it opened"


def test_a_pilot_with_no_tab_of_theirs_open_downloads_as_it_always_did(attached, tmp_path,
                                                                       capsys):
    """Pilot reads the lists first, in the same run, so Report a Problem
    was already open when its receipts were asked for."""
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    assert downloaded(tmp_path) == ALL_KEYS, folded(out)
    assert len(report_pages_loaded()) == 1, "Report a Problem opened once"
    assert not on_the_sites(attached)


def test_their_own_tab_is_used_never_loaded_again_and_left_open(attached, server, tmp_path,
                                                                capsys):
    """At home the tab the person signed in with is still open. Resume asks
    every receipt from it, does not load it again, and leaves it open where
    it was, with no tab of its own left beside it."""
    address = "http://%s:%d/?tab=theirs" % (REPORT_HOST, server)
    theirs = open_their_tab(attached, address, "Report a Problem")
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == ALL_KEYS, folded(out)
    assert not report_pages_loaded(), "their tab was not loaded again"
    assert set(receipt_calls()) == {address}, "every receipt was asked for from their tab"
    assert {t["id"]: t["url"] for t in on_the_sites(attached)} == {theirs: address}, \
        "their tab is still open where it was, and nothing else is"


def test_a_sign_in_asked_when_report_a_problem_is_opened_stops_the_app_store_side(
        attached, tmp_path, capsys):
    """Report a Problem asked for a sign-in when Resume opened it. The App
    Store side stops there, as it does in discovery, its tab left open for
    the person and no purchase counted as failed. Each purchase was asked
    for from a blank tab and recorded failed, and the run finished clean."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.signed_in = False
    SITE.seen.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume")

    assert "Report a Problem asked you to sign in again" in folded(out), out
    assert panel_reads(out)["stopped"] == 1
    assert not downloaded(tmp_path)
    assert not failed(tmp_path), "the purchases are looked for again next run, not counted failed"
    assert not receipt_calls(), "no receipt was asked for"
    assert [urlsplit(t["url"]).path for t in on_the_sites(attached)] == ["/"], \
        "the tab is left open for the person"


def test_a_page_that_never_holds_its_token_is_asked_when_report_a_problem_answers(
        attached, tmp_path, capsys):
    """Discovery goes on when the page it opened never held its session
    token but Report a Problem answers its family list, a GUESS of its own,
    since a new tab was never seen being given the token. Resume opens the
    page the same way and goes on the same way."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.home = NO_TOKEN
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == ALL_KEYS, folded(out)


def test_a_tab_that_leaves_the_site_partway_is_opened_on_it_again(attached, tmp_path, capsys,
                                                                 monkeypatch):
    """The tab was taken off Report a Problem after the first receipt. The
    next purchase opens Report a Problem in it again before anything is
    asked, rather than asking from a tab that every call is refused from."""
    finished_run(tmp_path, attached, capsys, "--discover")

    real_fetch = site.fetch_invoice
    left = []

    def fetch_then_leave(page, weborder, dsid):
        got = real_fetch(page, weborder, dsid)
        if not left:
            left.append(weborder)
            page.goto("about:blank")
        return got

    monkeypatch.setattr(site, "fetch_invoice", fetch_then_leave)
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert left, "the tab left Report a Problem after the first receipt"
    assert downloaded(tmp_path) == ALL_KEYS, folded(out)
    assert len(report_pages_loaded()) == 2, "Report a Problem was opened again for the second"


def test_a_tab_of_theirs_that_leaves_the_site_is_let_go_of(attached, server, tmp_path, capsys,
                                                          monkeypatch):
    """The person took their Report a Problem tab to another page after the
    first receipt. The tab is theirs, so it is let go of where they took it,
    never loaded back, and the next purchase opens Report a Problem in a tab
    of the run's own. Report a Problem was loaded into their tab."""
    address = "http://%s:%d/?tab=theirs" % (REPORT_HOST, server)
    theirs = open_their_tab(attached, address, "Report a Problem")
    finished_run(tmp_path, attached, capsys, "--discover")

    real_fetch = site.fetch_invoice
    left = []

    def fetch_then_leave(page, weborder, dsid):
        got = real_fetch(page, weborder, dsid)
        if not left:
            left.append(weborder)
            page.goto("about:blank")
        return got

    monkeypatch.setattr(site, "fetch_invoice", fetch_then_leave)
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert left, "their tab left Report a Problem after the first receipt"
    assert downloaded(tmp_path) == ALL_KEYS, folded(out)
    assert [t["url"] for t in tabs(attached) if t["id"] == theirs] == ["about:blank"], \
        "their tab is still open where they took it, never loaded back"
    asked_from = receipt_calls()
    assert asked_from[0] == address and "tab=theirs" not in "".join(asked_from[1:]), \
        "the first receipt was asked from their tab and the rest from the run's own"


def test_a_dry_run_resume_opens_no_page(attached, tmp_path, capsys):
    """A dry run asks Apple for nothing, and that holds for the pages too."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--dry-run")

    assert "DRY RUN, would save" in folded(out), out
    assert not SITE.seen, "nothing was asked of either site"
    assert not downloaded(tmp_path)
