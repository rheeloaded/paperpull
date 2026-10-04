"""--login, and the discovery a run starts with, against made-up Meijer pages
in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check itself. This app
asked the same way, one look at a page its orders never came to, so here
they never come, or the page turns into a press and hold check the moment
after the app first looks at it, or the page draws only the list's heading,
which is what a tester's Run All met (#42). None of those may be called a
success, and discovery may not read any of them as a history with nothing
new in it.

The orders page has two tabs, Online Orders, which it opens on, and
In-Store Receipts, whose rows come when that tab is pressed. A history
with nothing in it is real, and a page that says so is a signed-in one.
Discovery reads a tab as empty only when that tab says so, and only the
Online tab has been seen saying it.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from a
server on this machine and the browser resolves no host name, so nothing
reaches Meijer. Every store, date and amount is invented.
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
import meijer_receipts as app_mod
import meijer_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

ORDERS = "/shopping/orders.html"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The site's own header, with an amount in it, on every page it draws.
HEADER = ("<header><a href='/shopping/account.html'>Account</a>"
          "<span>mPerks savings this year $8.15</span></header>")

# The orders page while a bot check decides. Nothing on it but the check's
# own script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>Meijer</title></head><body>
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

# What a tester's Run All met in place of the list, its heading and a line
# under it.
HEADING_ONLY = ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
                "<h1>Orders and Receipts</h1><p>Something went wrong.</p></main></body></html>"
                % HEADER)

# A footer of the kind a grocery site carries on every page, with words that
# say there is nothing, about something other than the orders.
FOOTER = ("<footer><p>Weekly sweepstakes. No purchase necessary. Nothing to show for "
          "this offer yet.</p></footer>")


def _row(date, amount, items):
    return ("<li class='order-card'><div class='date'>In-Store: %s</div><div>18 Example Road</div>"
            "<div class='totals'><span>%s</span>&nbsp;&nbsp;%d items</div>"
            "<a href='javascript:void(0)'>view receipt pdf</a></li>" % (date, amount, items))


STORE_ROWS = _row("06/11/2026", "$23.41", 7) + _row("06/03/2026", "$58.07", 12)


def tabbed(store_rows):
    """The orders page, open on Online Orders, its In-Store rows drawn when
    that tab is pressed and taken away when the other one is. A tab hidden
    rather than emptied, and rows that come late or never, are played in
    test_both_tabs_in_a_browser.py."""
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
            "<h1>Orders and Receipts</h1><div role='tablist'>"
            "<a role='tab' href='#' onclick=\"show('online');return false\">Online Orders</a>"
            "<a role='tab' href='#' onclick=\"show('store');return false\">In-Store Receipts</a></div>"
            "<div id='online'><p>You haven't placed any orders yet</p></div>"
            "<div id='store' style='display:none'><ul id='rows'></ul></div>"
            "<script>function show(which) {"
            " document.getElementById('online').style.display = which === 'online' ? '' : 'none';"
            " document.getElementById('store').style.display = which === 'store' ? '' : 'none';"
            " document.getElementById('rows').innerHTML = which === 'store' ? %s : ''; }</script>"
            "</main></body></html>" % (HEADER, json.dumps(store_rows)))


LISTED = tabbed(STORE_ROWS)
EMPTY = tabbed("<li><p>You don't have any receipts yet</p></li>")

HOME = """<!doctype html><html><head><title>Meijer</title></head>
<body><h1>Meijer</h1></body></html>"""


class FakeMeijer:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = DECIDING
        self.decided = threading.Event()
        self.seen = []


SITE = FakeMeijer()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == ORDERS:
            body, kind = SITE.orders, "text/html; charset=utf-8"
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
def fake_meijer(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short. The orders page is the one route tried, as it is the
    one a tester's pages showed (#42)."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + ORDERS)
    monkeypatch.setattr(site, "ORDER_CANDIDATES", [server + ORDERS])
    monkeypatch.setitem(site.URLS, "orders", server + ORDERS)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    monkeypatch.setattr(site, "LIST_WAIT_MS", 3000, raising=False)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The page turns into the check the moment after the app first looks
    at the blank page, which is when Walmart's moved in the report. Tied to
    the app's look rather than to a clock, so it happens after that look
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

def test_an_orders_page_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "orders did not load" in out and "Look at the browser window" in out, out


@pytest.mark.parametrize("footer", ["", FOOTER], ids=["as it came", "under the site's footer"])
def test_a_page_that_drew_only_the_lists_heading_is_not_called_a_success(mode, tmp_path,
                                                                        capsys, footer):
    """The heading says Orders and the header carries an amount, which is
    all the old check on the page asked for. No tabs and no rows came, and
    words of the site's own elsewhere on the page that say there is nothing
    are not the list saying so."""
    SITE.orders = HEADING_ONLY.replace("</body>", footer + "</body>")
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "orders did not load" in out, out


def test_a_page_that_turns_into_press_and_hold_is_reported(mode, decides_after_the_first_look,
                                                           tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'press & hold'" in out, out
    assert "/check" in SITE.seen, "the page really did turn into the check"


def test_an_orders_page_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The list is there, so it says so."""
    SITE.orders = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in Meijer session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
    assert "did not load" not in out


def test_an_orders_page_with_nothing_on_it_is_a_signed_in_one(mode, tmp_path, capsys):
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


def found(tmp_path):
    """Each purchase discovery recorded, by its date and total."""
    return sorted((r["purchase_date"], r["total"]) for r in known(tmp_path).values())


@pytest.mark.parametrize("page", ["never comes", "draws only its heading"])
def test_a_pilot_stops_rather_than_find_nothing_on_a_list_that_never_comes(attached, tmp_path,
                                                                           capsys, page):
    """It used to find no rows on the page, and with nothing to do it
    finished, and the panel read the run as clean."""
    if page == "draws only its heading":
        SITE.orders = HEADING_ONLY
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "orders did not load" in out and "run this again" in out, out
    assert not known(tmp_path), "nothing is recorded from a page with no list on it"
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


def test_discovery_still_reads_a_list_that_comes(attached, tmp_path, capsys):
    """What worked before still works, the store receipts read from behind
    the tab they live on."""
    SITE.orders = LISTED
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert found(tmp_path) == [("2026-06-03", "$58.07"), ("2026-06-11", "$23.41")]
    assert "did not load" not in printed(capsys)


def test_an_orders_page_with_nothing_on_it_claims_nothing(attached, tmp_path, capsys):
    """The Online tab says it has no orders, and the In-Store tab shows a
    line and no receipts. What that tab says when there are none has not
    been seen (#42), and this line is made up, so the run stops rather than
    say the account has nothing, and nothing is recorded. The list itself
    came, so it is not said to have not loaded."""
    SITE.orders = EMPTY
    out = stopped_run(tmp_path, attached, capsys, "--discover")

    assert "Nothing showed on Meijer's In-Store Receipts tab" in out, out
    assert "Discovery complete" not in out and "orders did not load" not in out, out
    assert not known(tmp_path)


def test_with_somebody_there_it_asks_them_to_look_and_then_goes_on(attached, tmp_path,
                                                                   capsys, monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say the page shows their orders it opens the orders page
    again. Past a few questions they give up with Ctrl+C, so a loop that
    asks forever fails here rather than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.orders = LISTED
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your orders" in asked[0], asked
    assert found(tmp_path) == [("2026-06-03", "$58.07"), ("2026-06-11", "$23.41")]


# -- what counts as the list ----------------------------------------------------------

@pytest.fixture()
def page():
    """A page in Playwright's own Chromium, started and stopped by the test
    itself, since no app runs here."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def _tab(label):
    """A tab laid out the way a template lays one out, its label between
    lines of spacing and a count beside it that is not shown."""
    return ("<a role='tab' href='#'>\n%s%s\n%s<span style='display:none'>0</span>\n%s</a>"
            % (" " * 60, label, " " * 60, " " * 40))


def test_tabs_laid_out_with_spacing_and_a_hidden_count_are_the_list(page):
    """open_tab reads a tab by the words it shows, and so is the list read.
    Nothing else on this page says what it is."""
    page.set_content("<main><h1>Orders and Receipts</h1><div role='tablist'>%s%s</div>"
                     "<div><p>Your online orders will show here.</p></div></main>"
                     % (_tab("Online Orders"), _tab("In-Store Receipts")))
    assert site.orders_listed(page)


@pytest.mark.parametrize("words", ["You haven't placed any orders yet",
                                   "You haven’t placed any orders yet"])
def test_the_online_tabs_own_sentence_is_the_list_saying_it_is_empty(page, words):
    page.set_content("<main><h1>Orders and Receipts</h1><p>%s</p></main>" % words)
    assert site.orders_listed(page)


def test_words_that_say_nothing_elsewhere_on_the_page_are_not_the_list(page):
    page.set_content("<body>%s<main><h1>Orders and Receipts</h1><p>Something went wrong.</p>"
                     "</main>%s</body>" % (HEADER, FOOTER))
    assert not site.orders_listed(page)
