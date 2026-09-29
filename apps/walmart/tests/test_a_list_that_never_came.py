"""--login, and the discovery a run starts with, against made-up Walmart
pages in a real browser.

A container Chrome was told Success by --login, connected to a signed-in
Walmart session, while the app's own log said the purchase history never
appeared. The tab was still on /orders with nothing on it, while
Walmart's bot check decided, and a moment later it was on /blocked, titled
"Robot or human?". Here the order list never comes, or the page turns into
that check the moment after the app first looks at it. Neither may be
called a success, and discovery may not read either one as a history with
nothing new in it.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from a
server on this machine and the browser resolves no host name, so nothing
reaches Walmart. Every order number, store and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core.models import IN_STORE, ONLINE

ONLINE_ORDER = "10000000000000000001"
STORE_ORDER = "10000000000000000002"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The orders page while the bot check decides. Nothing on it but the
# check's own script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>Walmart.com</title></head><body>
<div id="root"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'blocked') location.replace('/blocked?url=L29yZGVycw==');
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>"""

# What the tab showed a moment later, in the words the report quoted.
BLOCKED = """<!doctype html><html><head><title>Robot or human?</title></head><body>
<h1>Robot or human?</h1>
<p>Activate and hold the button to confirm that you're human. Thank you!</p>
</body></html>"""

LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<h1>Purchase history</h1>
<div data-testid="order-0">
  <p>Store purchase</p><p>Purchased at Example Supercenter</p>
  <p>Jun 12, 2026</p><p>$23.41</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
<div data-testid="order-1">
  <p>Delivered</p><p>Jun 3, 2026</p><p>$58.20</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
</body></html>""" % (STORE_ORDER, ONLINE_ORDER)

HOME = """<!doctype html><html><head><title>Walmart.com</title></head>
<body><h1>Save money. Live better.</h1></body></html>"""


class FakeWalmart:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = DECIDING
        self.decided = threading.Event()
        self.seen = []


SITE = FakeWalmart()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == "/orders":
            body, kind = SITE.orders, "text/html; charset=utf-8"
        elif path == "/blocked":
            body, kind = BLOCKED, "text/html; charset=utf-8"
        elif path == "/":
            body, kind = HOME, "text/html; charset=utf-8"
        elif path == "/decision":
            body, kind = ("blocked" if SITE.decided.is_set() else "wait"), "text/plain"
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
    which is what the app attaches to at home. Its address, for cdp_url."""
    profile = tmp_path_factory.mktemp("attached-profile")
    proc = subprocess.Popen(
        [browser_exe, "--headless=new", "--remote-debugging-port=0",
         "--user-data-dir=%s" % profile, "--no-first-run", "--no-default-browser-check",
         NO_HOSTS, "about:blank"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port, deadline = "", time.monotonic() + 30
    while not port and time.monotonic() < deadline and proc.poll() is None:
        try:
            port = (profile / "DevToolsActivePort").read_text().split()[0]
        except (OSError, IndexError):
            time.sleep(0.1)
    if not port or not browser_launcher.wait_for_debug_port(port):
        proc.kill()
        pytest.skip("the browser opened no debugging port")
    url = "http://127.0.0.1:%s" % port
    yield url
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.connect_over_cdp(url).new_browser_cdp_session().send("Browser.close")
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)


@pytest.fixture(autouse=True)
def fake_walmart(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the list's thirty seconds included."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setitem(site.FILTER_URL, ONLINE, server + "/orders?filterIds=online")
    monkeypatch.setitem(site.FILTER_URL, IN_STORE, server + "/orders?filterIds=in-store")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800)
    monkeypatch.setattr(site, "SETTLE_MS", 0)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The bot check sends the tab to /blocked the moment after the app
    first looks at the blank page, which is when it moved in the report.
    Tied to the app's look rather than to a clock, so it happens after that
    look however long the app waited for the list."""
    real = site.detect_security_challenge

    def look(page):
        said = real(page)
        SITE.decided.set()
        return said

    monkeypatch.setattr(site, "detect_security_challenge", look)
    # Long enough for the move to arrive. It stops looking when it does.
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 5000)


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

def test_an_order_list_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "orders did not load" in out and "Look at the browser window" in out, out


def test_a_page_that_turns_into_robot_or_human_is_reported(mode, decides_after_the_first_look,
                                                          tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'robot or human'" in out, out
    assert "/blocked" in SITE.seen, "the page really did turn into the check"


def test_an_order_list_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The list is there, so it says so."""
    SITE.orders = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in Walmart session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
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


def test_a_pilot_stops_rather_than_find_nothing_on_a_list_that_never_comes(attached, tmp_path,
                                                                           capsys):
    """It used to find no orders on the blank page, and with nothing to do
    it finished, and the panel read the run as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "orders did not load" in out and "run this again" in out, out
    assert not known(tmp_path), "nothing is recorded from a page with no list on it"
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    """One kind of purchase. A run over both used to find no online orders
    on the blocked page and then meet the check when it looked again before
    the in-store list, so it did stop, one list too late. A run over one
    kind never looked again, and finished as though there were none."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot-online")

    assert "Security challenge detected: 'robot or human'" in out, out
    assert "I will NOT attempt to bypass it" in out
    assert "/blocked" in SITE.seen
    assert not known(tmp_path)


def test_discovery_still_reads_a_list_that_comes(attached, tmp_path, capsys):
    """What worked before still works, both kinds of purchase, through the
    filtered lists that come after the check."""
    SITE.orders = LISTED
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    records = known(tmp_path)
    assert sorted(records) == ["In-Store:" + STORE_ORDER, "Online:" + ONLINE_ORDER], records
    assert records["In-Store:" + STORE_ORDER]["purchase_date"] == "2026-06-12"
    assert "did not load" not in printed(capsys)


def answering(monkeypatch, then=None, limit=5):
    """Somebody at the console, who presses Enter at every question. Past
    `limit` questions they give up with Ctrl+C, so a loop that asks forever
    fails here rather than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > limit:
            raise KeyboardInterrupt
        if then:
            then()
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    return asked


def test_with_somebody_there_it_asks_them_to_look_and_then_goes_on(attached, tmp_path,
                                                                   capsys, monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say the page shows their orders it opens the list again."""
    def dealt_with_it():
        SITE.orders = LISTED
    asked = answering(monkeypatch, then=dealt_with_it)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your orders" in asked[0], asked
    assert sorted(known(tmp_path)) == ["In-Store:" + STORE_ORDER, "Online:" + ONLINE_ORDER]


LISTED_WITH_A_WORD = LISTED.replace("<p>Delivered</p>",
                                    "<p>Delivered</p><p>Home Security Check Kit</p>")


def test_a_challenge_word_on_a_listed_page_is_asked_about_once_as_before(attached, tmp_path,
                                                                        capsys, monkeypatch):
    """An item named like a bot check, on a page whose list is there. It
    was asked about once for each kind of purchase before this change, and
    still is, rather than again every time the list is opened."""
    SITE.orders = LISTED_WITH_A_WORD
    asked = answering(monkeypatch)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 2, asked
    assert sorted(known(tmp_path)) == ["In-Store:" + STORE_ORDER, "Online:" + ONLINE_ORDER]
