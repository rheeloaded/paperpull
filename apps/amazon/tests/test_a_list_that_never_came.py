"""--login, and the discovery a run starts with, against made-up Amazon
pages in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check itself. This app
asked the same way, one look at a page its list never came to, so here the
list never comes, or the page turns into Amazon's own check the moment
after the app first looks at it. Neither may be called a success, and
discovery may not read either one as a year with no orders.

A year with no orders is real, and discovery meets one at the end of every
unscoped run. Amazon's page for it has no order cards and says "0 orders",
which is what tells it apart from a page that never drew its list.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from a
server on this machine and the browser resolves no host name, so nothing
reaches Amazon. Every order number and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
import amazon_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

THIS_YEAR = date.today().year
LAST_YEAR = THIS_YEAR - 1
FIRST_ORDER = "111-0000000-0000001"
SECOND_ORDER = "111-0000000-0000002"
HISTORY = "/gp/css/order-history"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history while a bot check decides. Nothing on it but the check's own
# script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<div id="a-page"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'decided') location.replace('/errors/validateCaptcha');
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>"""

# Amazon's own check, in its own words.
CHECK = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<h4>Enter the characters you see below</h4>
<p>Sorry, we just need to make sure you're not a robot. For best results,
please make sure your browser is accepting cookies.</p>
<form action="/errors/validateCaptcha"><input id="captchacharacters"></form>
</body></html>"""

CARD = """<div class="order-card js-order-card">
<div>Order placed</div><div>January 2, %d</div>
<div>Total</div><div>$%s</div>
<div>Order # %s</div>
<a href="/gp/your-account/order-details?orderID=%s">View order details</a>
</div>"""


def orders_page(count: int, cards: str = "") -> str:
    """The Your Orders page as Amazon draws it, its own count in the period
    menu's label and the orders under it."""
    return """<!doctype html><html><head><title>Your Orders</title></head><body>
<section class="your-orders-content-container js-yo-container">
<h1>Your Orders</h1>
<form class="js-time-filter-form" action="/your-orders/orders">
<label class="a-form-label time-filter__label" for="time-filter">
<span class="num-orders">%d orders</span> placed in</label>
<select id="time-filter" name="timeFilter"><option>past 3 months</option></select>
</form>
%s
</section></body></html>""" % (count, cards)


LISTED = orders_page(2, CARD % (THIS_YEAR, "23.41", FIRST_ORDER, FIRST_ORDER)
                     + CARD % (THIS_YEAR, "58.20", SECOND_ORDER, SECOND_ORDER))
EMPTY = orders_page(0)

HOME = """<!doctype html><html><head><title>Amazon.com</title></head>
<body><h1>Amazon.com</h1></body></html>"""


class FakeAmazon:
    """What the made-up site shows, set by each test. The order history with
    no year is what --login opens, and each year's page is what discovery
    opens, one at a time."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.front = DECIDING
        self.years = {}
        self.other_years = DECIDING
        self.decided = threading.Event()
        self.seen = []

    def history(self, query: dict) -> str:
        spec = (query.get("timeFilter") or [""])[0]
        if not spec.startswith("year-"):
            return self.front
        return self.years.get(int(spec[5:]), self.other_years)


SITE = FakeAmazon()


def orders_this_year_and_none_before():
    SITE.front = LISTED
    SITE.years = {THIS_YEAR: LISTED}
    SITE.other_years = EMPTY


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(parts.path + ("?" + parts.query if parts.query else ""))
        if parts.path == HISTORY:
            body, kind = SITE.history(parse_qs(parts.query)), "text/html; charset=utf-8"
        elif parts.path == "/errors/validateCaptcha":
            body, kind = CHECK, "text/html; charset=utf-8"
        elif parts.path == "/":
            body, kind = HOME, "text/html; charset=utf-8"
        elif parts.path == "/decision":
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
    started can abort its first navigation, which is how the GitHub and
    Walmart copies of this test failed on CI."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_amazon(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the list's thirty seconds included."""
    SITE.reset()
    real = site.set_marketplace

    def here(domain=None):
        # The app chooses its store as it starts, and every address it
        # builds after that starts from BASE, so BASE is moved after it.
        said = real(domain)
        monkeypatch.setattr(site, "BASE", server)
        monkeypatch.setitem(site.URLS, "home", server + "/")
        monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
        return said

    monkeypatch.setattr(site, "set_marketplace", here)
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "YEAR_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "YEAR_SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The page turns into the check the moment after the app first looks
    at the blank history, which is when Walmart's moved in the report. Tied
    to the app's look rather than to a clock, so it happens after that look
    however long the app waited for the list."""
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

def test_an_order_list_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "orders did not load" in out and "Look at the browser window" in out, out


def test_a_page_that_turns_into_the_check_is_reported(mode, decides_after_the_first_look,
                                                      tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'enter the characters you see'" in out, out
    assert "/errors/validateCaptcha" in SITE.seen, "the page really did turn into the check"


def test_an_order_list_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The list is there, so it says so."""
    orders_this_year_and_none_before()
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in Amazon session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
    assert "did not load" not in out


def test_a_period_with_no_orders_is_still_a_signed_in_list(mode, tmp_path, capsys):
    """Nobody has ordered in the last three months, which is what the order
    history opens on. Amazon says "0 orders", and that is its list."""
    SITE.front = EMPTY
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


def test_a_pilot_stops_rather_than_find_nothing_on_a_list_that_never_comes(attached, tmp_path,
                                                                           capsys):
    """It used to find no orders on the blank page, take the year as empty
    and go on, and with nothing to do the run finished, and the panel read
    it as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot", "--year", str(THIS_YEAR))

    assert "orders did not load" in out and "run this again" in out, out
    assert not known(tmp_path), "nothing is recorded from a page with no list on it"
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    """One year. A walk over several met the check when it looked again at
    the next year's page, so it did stop, one year too late. A walk over
    one never looked again, and finished as though there were none."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot", "--year", str(THIS_YEAR))

    assert "Security challenge detected: 'enter the characters you see'" in out, out
    assert "I will NOT attempt to bypass it" in out
    assert "/errors/validateCaptcha" in SITE.seen
    assert not known(tmp_path)


def test_a_year_that_never_comes_is_not_where_the_history_ends(attached, tmp_path, capsys):
    """This year's orders come and last year's page never draws. The walk
    used to take last year as empty, which is where an Amazon history
    starts, so it stopped there and finished clean with every order before
    it missed."""
    SITE.years = {THIS_YEAR: LISTED}
    SITE.other_years = DECIDING
    out = stopped_run(tmp_path, attached, capsys, "--discover",
                      "--start-date", "%d-01-01" % LAST_YEAR)

    assert "orders did not load" in out, out
    assert sorted(known(tmp_path)) == ["Online:" + FIRST_ORDER, "Online:" + SECOND_ORDER], \
        "what was read before the page that never came is kept"


def test_discovery_still_reads_a_list_that_comes(attached, tmp_path, capsys):
    """What worked before still works. This year's orders are read, and last
    year's "0 orders" is where the history starts, so the walk ends there."""
    orders_this_year_and_none_before()
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    records = known(tmp_path)
    assert sorted(records) == ["Online:" + FIRST_ORDER, "Online:" + SECOND_ORDER], records
    assert records["Online:" + FIRST_ORDER]["purchase_date"] == "%d-01-02" % THIS_YEAR
    assert "did not load" not in printed(capsys)
    assert HISTORY + "?timeFilter=year-%d" % LAST_YEAR in SITE.seen


def test_years_with_no_orders_are_read_as_empty_not_as_failed(attached, tmp_path, capsys):
    """Every year in scope says "0 orders". That is an account with nothing
    there to find, and the run finishes rather than stopping."""
    SITE.front = SITE.other_years = EMPTY
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--start-date", "%d-01-01" % LAST_YEAR,
                         "--config", str(cfg)]) == 0

    out = printed(capsys)
    assert "Discovery complete" in out and "did not load" not in out, out
    assert not known(tmp_path)


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
    once they say the page shows their orders it opens the year again."""
    asked = answering(monkeypatch, then=orders_this_year_and_none_before)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your orders" in asked[0], asked
    assert sorted(known(tmp_path)) == ["Online:" + FIRST_ORDER, "Online:" + SECOND_ORDER]
