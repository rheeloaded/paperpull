"""--login, and the discovery a run starts with, against made-up Best Buy
pages in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check, titled "Robot or
human?". This app asked the same way, one look at a page its range menu
never came to, so here the menu never comes, or the page turns into a check
the moment after the app first looks at it. Neither may be called a
success, and discovery may not read either one as a history with nothing
new in it.

Best Buy's own list of checks does not know Walmart's words, so a "Robot or
human?" page is reported as a history that did not load, which claims
nothing and sends the person to the window. "Access Denied", which is what
Best Buy's bot protection shows, is reported by name.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from a
server on this machine and the browser resolves no host name, so nothing
reaches Best Buy. Every order number and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_receipts as app_mod
import bestbuy_site as site
from paperpull_core import browser as browser_launcher

HISTORY = "/purchasehistory/purchases"
ONLINE_ORDER = "BBY01-800000000007"
STORE_PURCHASE = "100 2 3000 052026"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history while a bot check decides. Nothing on it but the check's own
# script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>Best Buy</title></head><body>
<div id="root"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'decided') location.replace('/check');
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>"""

CHECKS = {
    # The words Walmart's tab showed, which this app's list does not know.
    "robot or human": """<!doctype html><html><head><title>Robot or human?</title></head>
<body><h1>Robot or human?</h1>
<p>Activate and hold the button to confirm that you're human. Thank you!</p></body></html>""",
    # What Best Buy's bot protection shows.
    "access denied": """<!doctype html><html><head><title>Access Denied</title></head>
<body><h1>Access Denied</h1>
<p>You don't have permission to access this page on this server.</p>
<p>Reference #18.00000000.0000000000.00000000</p></body></html>""",
}

# The history with its range menu. Choosing a year asks for that year's
# purchases the way the page's own code does.
LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<h1>Purchases</h1>
<button data-testid="YearDate-Filter-TestID"
        onclick="document.getElementById('years').hidden = false">Past 3 Years</button>
<ul id="years" hidden><li onclick="pick(THIS_YEAR)">THIS_YEAR</li>
<li onclick="pick(LAST_YEAR)">LAST_YEAR</li></ul>
<script>
function pick(year) {
  document.getElementById('years').hidden = true;
  fetch('/gateway/graphql', {method: 'POST',
    headers: {'content-type': 'application/json', 'x-client-id': 'purchase-history'},
    body: JSON.stringify({operationName: 'consolidatedQuery',
      variables: {year: year, orderOffset: 0, purchaseOffset: 0, orderLimit: 3, purchaseLimit: 3}})});
}
</script></body></html>""".replace("THIS_YEAR", str(date.today().year)).replace(
    "LAST_YEAR", str(date.today().year - 1))

HOME = """<!doctype html><html><head><title>Best Buy</title></head>
<body><h1>Shop Deals</h1></body></html>"""


def history_answer(year):
    """This year holds one online order and one store purchase, every other
    year nothing, in the shape the history query answers."""
    entries = []
    if year == date.today().year:
        entries = [
            {"id": ONLINE_ORDER, "orderType": "online", "created": "2026-04-19T15:04:00-05:00",
             "orderTotal": 593.09, "orderStatusTitle": "Delivered"},
            {"id": STORE_PURCHASE, "orderType": "store", "created": "2026-05-20T18:10:00Z",
             "orderTotal": 23.41, "orderStatusTitle": "Purchased"},
        ]
    return {"data": {"customer": {"purchaseHistoryOrdersExperience": {
        "closedOrdersAndTransactions": {"entries": entries, "pageInfo": {"hasNext": False}},
        "openOrders": {"entries": [], "pageInfo": {"hasNext": False}}}}}}


class FakeBestBuy:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.history = DECIDING
        self.check = CHECKS["robot or human"]
        self.decided = threading.Event()
        self.seen = []


SITE = FakeBestBuy()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == HISTORY:
            self._answer(SITE.history, "text/html; charset=utf-8")
        elif path == "/check":
            self._answer(SITE.check, "text/html; charset=utf-8")
        elif path == "/":
            self._answer(HOME, "text/html; charset=utf-8")
        elif path == "/decision":
            self._answer("decided" if SITE.decided.is_set() else "wait", "text/plain")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path != "/gateway/graphql":
            self.send_error(404)
            return
        year = (json.loads(body or b"{}").get("variables") or {}).get("year")
        self._answer(json.dumps(history_answer(year)), "application/json")

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


def _start_browser(exe, profile):
    """The browser as a program of its own with a debugging port, and its
    address, or None for the address when it opened no port."""
    proc = subprocess.Popen(
        [exe, "--headless=new", "--remote-debugging-port=0",
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
        return proc, None
    return proc, "http://127.0.0.1:%s" % port


def _draws_the_home_page(url, address):
    """Whether a tab opened the way the app opens one, over CDP in the
    browser's own context, draws the home page, and what each try did. A
    tab that has not drawn it is left where it is, since closing a fresh
    browser's tab has hung before, and another is opened, three at most.
    The one that drew stays open on it."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    did = []
    with sync_playwright() as p:
        try:
            context = p.chromium.connect_over_cdp(url).contexts[0]
        except (PlaywrightError, IndexError) as e:
            return False, ["could not attach, %s" % str(e).splitlines()[0]]
        for _try in range(3):
            try:
                page = context.new_page()
                page.goto(address, wait_until="domcontentloaded", timeout=15000)
                if page.title() == "Best Buy":
                    return True, did
                did.append("drew %r instead" % page.title())
            except PlaywrightError as e:
                did.append(str(e).splitlines()[0])
    return False, did


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.

    At home login.bat opened it and the person signed in there, well before
    the app attached. A browser that has only just started is not that. On
    CI the GitHub app's very first goto in a fresh browser twice came back
    net::ERR_ABORTED after about five seconds, which is how a browser
    answers a navigation when its network service is restarted under it.
    This app's first goto is the same unguarded goto, and that fault fails
    this file the same way.

    So it is handed over once a tab opened the way the app opens one has
    drawn the home page, tried again in a new tab when it has not. Not the
    history, which here is a page a bot check decides on. A tab left there
    would ask for /decision all through the module and follow the check to
    /check, which the tests take as the app's own tab turning into the
    check. A browser that never draws the home page is closed and another
    started, three at most, and a failure says what each one did."""
    tried = []
    for _start in range(3):
        proc, url = _start_browser(browser_exe, tmp_path_factory.mktemp("attached-profile"))
        if url is None:
            proc.kill()
            proc.wait(timeout=15)
            pytest.skip("the browser opened no debugging port")
        ready, did = _draws_the_home_page(url, server + "/")
        if ready:
            break
        tried.append(", then ".join(did))
        proc.kill()
        proc.wait(timeout=15)
    else:
        pytest.fail("three fresh browsers in a row never drew the home page. %s"
                    % " / ".join(tried))
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
def fake_bestbuy(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the history's thirty seconds included."""
    SITE.reset()
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    # The history query is only kept, and asked again, on Best Buy's own
    # host. Here that host is this machine.
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800)
    monkeypatch.setattr(site, "SETTLE_MS", 0)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The page turns into the check the moment after the app first looks
    at the blank history, which is when Walmart's moved in the report.
    Tied to the app's look rather than to a clock, so it happens after that
    look however long the app waited for the menu."""
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

def test_a_history_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "purchase history did not load" in out and "Look at the browser window" in out, out


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_a_page_that_turns_into_a_check_is_not_called_a_success(
        mode, check, decides_after_the_first_look, tmp_path, capsys, monkeypatch):
    SITE.check = CHECKS[check]
    if check == "robot or human":
        # Nothing on it is known here, so the look runs its full length.
        # The move itself comes well inside this.
        monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 2500)
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "/check" in SITE.seen, "the page really did turn into the check"
    if check == "access denied":
        assert "Security challenge detected: 'access denied'" in out, out
    else:
        assert "purchase history did not load" in out and "Look at the browser window" in out, out


def test_a_history_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The menu is there, so it says so."""
    SITE.history = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in Best Buy session." if how == "attached"
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


def asked_for_history():
    return [p for p in SITE.seen if p == "/gateway/graphql"]


def test_a_pilot_stops_rather_than_find_nothing_on_a_history_that_never_comes(attached, tmp_path,
                                                                              capsys):
    """It used to find no history query on the blank page, write a failure
    file and carry on, and with nothing new to do the run finished, and the
    panel read it as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "purchase history did not load" in out and "run this again" in out, out
    assert not known(tmp_path) and not asked_for_history()
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    SITE.check = CHECKS["access denied"]
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "Security challenge detected: 'access denied'" in out, out
    assert "I will NOT attempt to bypass it" in out
    assert "/check" in SITE.seen
    assert not known(tmp_path) and not asked_for_history()


def test_discovery_still_reads_a_history_that_comes(attached, tmp_path, capsys):
    """What worked before still works. The menu is there, a year is chosen,
    the page's own query is kept and asked again for each year, and both
    kinds of purchase are found."""
    SITE.history = LISTED
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    records = known(tmp_path)
    assert sorted(records) == ["In-Store:" + STORE_PURCHASE, "Online:" + ONLINE_ORDER], records
    assert "did not load" not in printed(capsys)


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
        SITE.history = LISTED
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your purchases" in asked[0], asked
    assert sorted(known(tmp_path)) == ["In-Store:" + STORE_PURCHASE, "Online:" + ONLINE_ORDER]
