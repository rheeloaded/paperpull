"""--login, and the discovery a run starts with, against made-up Kroger pages
in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check itself. This app
asked the same way, one look at a page its purchases never came to, so here
they never come, or the page turns into a press and hold check the moment
after the app first looks at it. Neither may be called a success, and
discovery may not ask the purchase history API from either one and read
what comes back as a history with nothing new in it.

A history with nothing in it is real, and is read as empty only when the
page says so, in the words a signed-in account with no purchases was seen
to show on the live site.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page and the
history API come from a server on this machine and the browser resolves no
host name, so nothing reaches Kroger. Every key, store, date and amount is
invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import kroger_receipts as app_mod
import kroger_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

STORE_KEY = "701~00456~2026-06-11~014~7721"
PICKUP_KEY = "701~00456~2026-06-03~090~3305"
HISTORY = "/mypurchases"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history while a bot check decides. Nothing on it but the check's own
# script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>Kroger</title></head><body>
<div id="root"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'decided') location.replace('/check');
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>"""

CHECK = """<!doctype html><html><head><title>Access to this page has been denied</title></head>
<body><h1>Access to this page has been denied</h1>
<p>Press &amp; Hold to confirm you are a human (and not a bot).</p></body></html>"""

LISTED = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1>
<div data-testid="PO-NonPendingPurchase"><p>In-Store</p><p>Jun 11, 2026</p><p>$23.41</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
<div data-testid="PO-NonPendingPurchase"><p>Pickup</p><p>Jun 3, 2026</p><p>$58.07</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
</main></body></html>""" % (STORE_KEY, PICKUP_KEY)

EMPTY = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1><h2>No Orders Yet</h2>
<p>Looks like there aren't any orders to show.</p></main></body></html>"""

NO_LOYALTY = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1><p>Missing Loyalty ID</p>
<p>Add a Shopper's Card to your account to see your purchases.</p></main></body></html>"""

HOME = """<!doctype html><html><head><title>Kroger</title></head>
<body><h1>Kroger</h1></body></html>"""

RECORDS = [
    {"receiptKey": STORE_KEY, "purchaseType": "IN_STORE", "status": "COMPLETED",
     "createdDateTime": {"value": "2026-06-11T14:02:00Z"}, "total": "USD 23.41",
     "lineItems": [{"upc": "0000000004011", "quantity": 2}]},
    {"receiptKey": PICKUP_KEY, "purchaseType": "SELF_SERVE_PICKUP", "status": "COMPLETED",
     "createdDateTime": {"value": "2026-06-03T18:40:00Z"}, "total": "USD 58.07",
     "lineItems": [{"upc": "0000000004022", "quantity": 1}]},
]


class FakeKroger:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = DECIDING
        self.records = []
        self.decided = threading.Event()
        self.seen = []


SITE = FakeKroger()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == HISTORY:
            body, kind = SITE.orders, "text/html; charset=utf-8"
        elif path == site.SEARCH_API:
            body = json.dumps({"data": {"postOrderSearch": {
                "data": SITE.records, "pageNo": 1, "pageTotal": 1, "isLastPage": True}}})
            kind = "application/json"
        elif path == "/check":
            body, kind = CHECK, "text/html; charset=utf-8"
        elif path == "/":
            body, kind = HOME, "text/html; charset=utf-8"
        elif path == "/decision":
            body, kind = ("decided" if SITE.decided.is_set() else "wait"), "text/plain"
        else:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
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
def attached(browser_exe, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation. The app works in a tab it opens
    for itself, so the tab that drew can stay where it is."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_kroger(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the history's thirty seconds included."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The page turns into the check the moment after the app first looks
    at the blank history, which is when Walmart's moved in the report. Tied
    to the app's look rather than to a clock, so it happens after that look
    however long the app waited for the history."""
    real = site.detect_security_challenge

    def look(page):
        said = real(page)
        SITE.decided.set()
        return said

    monkeypatch.setattr(site, "detect_security_challenge", look)
    # Long enough for the move to arrive. It stops looking when it does.
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 5000, raising=False)


@pytest.fixture(params=["attached", "launched here"])
def mode(request, monkeypatch):
    """How the app has its browser. Attached is login.bat's window over
    CDP. Launched here is the older setting with no cdp_url, where the app
    starts its own and waits for Enter, forced headless for the test."""
    if request.param == "attached":
        return request.param, request.getfixturevalue("attached")
    pw = pytest.importorskip("playwright.sync_api")
    real = pw.BrowserType.launch_persistent_context

    def headless(self, user_data_dir, **kw):
        kw["headless"] = True
        kw["args"] = list(kw.get("args") or []) + [NO_HOSTS]
        return real(self, user_data_dir, **kw)

    monkeypatch.setattr(pw.BrowserType, "launch_persistent_context", headless)
    # The person pressed Enter after signing in.
    monkeypatch.setattr(browser_launcher, "pause_for_sign_in", lambda *a, **k: True)
    return request.param, ""


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def login(tmp_path, cdp_url, capsys):
    assert app_mod.main(["--login", "--config", str(config_for(tmp_path, cdp_url))]) == 0
    return printed(capsys)


def claims_a_session(out):
    return "Success" in out or "Signed-in session detected" in out


# -- --login ----------------------------------------------------------------------

def test_a_purchase_history_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "purchase history did not load" in out and "Look at the browser window" in out, out


def test_a_page_that_turns_into_press_and_hold_is_reported(mode, decides_after_the_first_look,
                                                           tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'press & hold'" in out, out
    assert "/check" in SITE.seen, "the page really did turn into the check"


def test_a_purchase_history_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The purchases are there, so it says so."""
    SITE.orders = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in Kroger session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
    assert "did not load" not in out


def test_a_history_that_says_it_is_empty_is_a_signed_in_one(mode, tmp_path, capsys):
    SITE.orders = EMPTY
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert claims_a_session(out), out
    assert "did not load" not in out


# -- discovery ----------------------------------------------------------------------

def stopped_run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to stop rather than finish. Leaving on SystemExit
    with the exception in flight is what the core reports to the panel as
    stopped, rather than as a clean finish, and core/tests/test_run_reporting.py
    holds every app's main to that."""
    cfg = config_for(tmp_path, cdp_url)
    with pytest.raises(SystemExit) as stopped:
        app_mod.main([*flags, "--config", str(cfg)])
    out = printed(capsys)
    assert stopped.value.code == 0, out
    return out


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def test_a_pilot_stops_rather_than_find_nothing_on_a_history_that_never_comes(attached, tmp_path,
                                                                              capsys):
    """It used to ask the history API from the blank page, and with nothing
    to do it finished, and the panel read the run as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "purchase history did not load" in out and "run this again" in out, out
    assert site.SEARCH_API not in SITE.seen, "nothing is asked of the history API from that page"
    assert not known(tmp_path), "nothing is recorded from a page with no purchases on it"
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "Security challenge detected: 'press & hold'" in out, out
    assert "I will NOT attempt to bypass it" in out
    assert "/check" in SITE.seen
    assert not known(tmp_path)


def test_discovery_still_reads_a_history_that_comes(attached, tmp_path, capsys):
    """What worked before still works, store purchases and pickup orders
    together, from the history API asked from inside the page."""
    SITE.orders, SITE.records = LISTED, RECORDS
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    records = known(tmp_path)
    assert sorted(records) == ["In-Store:" + STORE_KEY, "Online:" + PICKUP_KEY], records
    assert records["In-Store:" + STORE_KEY]["purchase_date"] == "2026-06-11"
    assert "did not load" not in printed(capsys)


def test_a_history_that_says_it_is_empty_finishes_with_nothing_found(attached, tmp_path,
                                                                     capsys):
    SITE.orders = EMPTY
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    out = printed(capsys)
    assert "Discovery complete" in out and "did not load" not in out, out
    assert not known(tmp_path)


def test_an_account_with_no_loyalty_card_is_told_so(attached, tmp_path, capsys):
    """Kroger's own words that it has no card to look purchases up by are
    the signed-in page answering, so the run says what they mean rather
    than that the history did not load."""
    SITE.orders = NO_LOYALTY
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    out = printed(capsys)
    assert "no loyalty card" in out and "did not load" not in out, out
    assert not known(tmp_path)


def test_with_somebody_there_it_asks_them_to_look_and_then_goes_on(attached, tmp_path,
                                                                   capsys, monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say the page shows their purchases it opens the history
    again. Past a few questions they give up with Ctrl+C, so a loop that
    asks forever fails here rather than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.orders, SITE.records = LISTED, RECORDS
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your purchases" in asked[0], asked
    assert sorted(known(tmp_path)) == ["In-Store:" + STORE_KEY, "Online:" + PICKUP_KEY]
