"""--login, and the discovery a run starts with, against made-up Target pages
in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check itself. This app's
Login asked even less, one look for a sign-in page and none for a check, so
here the history never comes, or Target's own check comes up on the page the
moment after the app first looks at it, or is drawn over the list. None of
those may be called signed in, and discovery may not read a history that
never came as one with nothing new in it.

Target's check is the person's to answer, with the app gone, since it can
refuse a hold given under automation however long it is held (#48). So in
the person's own browser a history that never came lets go of the browser
and stops, at a console too, rather than waiting attached for an answer.

The browser for the attached runs is started here as a program of its own
with a debugging port, the way Login leaves one open, and the app attaches
to it over CDP exactly as it does at home, working in the browser's only
tab, as it does there. Every page comes from a server on this machine and
the browser resolves no host name, so nothing reaches Target. Every order
number, store, date and amount is invented.
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
import target_receipts as app_mod
import target_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit
from paperpull_core.models import IN_STORE, ONLINE

APP_DIR = Path(__file__).resolve().parents[1]

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# Target's own check, the way a tester met it on /orders, its words in the
# page and its button in a frame of its own (#48).
CHECK = ("<div id='check'><h1>Quick verification</h1>"
         "<p>Press &amp; hold to confirm you're not a bot.</p>"
         "<iframe srcdoc=\"<button>Press &amp; Hold</button>\"></iframe></div>")

# The history while the check decides. Nothing on it but the check's own
# script, which asks the server what it decided and then draws the check on
# the page, as Target's does.
DECIDING = """<!doctype html><html><head><title>Target</title></head><body>
<div id="root"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'decided') document.getElementById('root').innerHTML = %s;
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>""" % json.dumps(CHECK)

ONLINE_ORDERS = [("2026000101", "Jun 9, 2026", "$31.62"), ("2026000102", "May 28, 2026", "$9.48")]
STORE_TRIPS = [("0000-1111-2222-5555", "Jun 12, 2026", "$14.07")]


def history(check=""):
    """The history, open on Online with its purchases drawn, the In-store
    purchases drawn when that tab is pressed. Both tabs keep the address
    /orders, as Target's own do."""
    return """<!doctype html><html><head><title>Orders</title></head><body><main>
<div role="tablist">
  <button role="tab" data-test="tabOnline">Online</button>
  <button role="tab" data-test="tabInstore">In-store</button>
</div>
<div id="cards"></div>
</main>%s
<script>
const ONLINE = %s;
const INSTORE = %s;
function show(kind) {
  const list = document.getElementById('cards');
  list.innerHTML = '';
  for (const [id, day, total] of (kind === 'online' ? ONLINE : INSTORE)) {
    const a = document.createElement('a');
    if (kind === 'online') {
      a.setAttribute('data-test', 'order-details-link');
      a.href = '/orders/' + id;
      a.innerHTML = '<div>Order #' + id + '</div><div>Placed ' + day + '</div><div>' + total +
                    '</div><div>Delivered</div>';
    } else {
      a.setAttribute('data-test', 'store-order-details-link');
      a.href = '/orders/stores/' + id;
      a.innerHTML = '<div>Store trip at Example Town</div><div>' + day + '</div><div>' + total +
                    '</div>';
    }
    list.appendChild(a);
  }
}
document.querySelector('[data-test=tabOnline]').onclick = () => show('online');
document.querySelector('[data-test=tabInstore]').onclick = () => show('instore');
show('online');
</script></body></html>""" % (check, json.dumps(ONLINE_ORDERS), json.dumps(STORE_TRIPS))


# A sign-in step-up, which is answered at the console, unlike the check.
STEP_UP = ("<div id='step-up'><h1>Let's make sure it's you</h1>"
           "<p>Enter the verification code we sent.</p></div>")
STEP_UP_PAGE = ("<!doctype html><html><head><title>Target</title></head><body>%s</body></html>"
                % STEP_UP)

LISTED = history()
LISTED_UNDER_THE_CHECK = history(CHECK)
LISTED_UNDER_A_STEP_UP = history(STEP_UP)
# Only the history's tabs, nothing under either of them.
TABS_ONLY = """<!doctype html><html><head><title>Orders</title></head><body><main>
<div role="tablist">
  <button role="tab" data-test="tabOnline">Online</button>
  <button role="tab" data-test="tabInstore">In-store</button>
</div></main></body></html>"""

HOME = """<!doctype html><html><head><title>Target</title></head>
<body><h1>Target</h1></body></html>"""


class FakeTarget:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = DECIDING
        self.plan = []
        self.decided = threading.Event()
        self.seen = []

    def orders_page(self):
        """The next page of the plan, and its last page again once it has
        run out, or else the one page the test set."""
        if self.plan:
            return self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        return self.orders


SITE = FakeTarget()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == "/orders":
            body, kind = SITE.orders_page(), "text/html; charset=utf-8"
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
    testkit.drawn_browser hands it over only once a tab has drawn a page,
    since a browser that has only just started can abort its first
    navigation. The tab that drew is handed over as the browser's only one,
    as it was while Target worked in the first tab it found. Target now works
    in a tab on its own site, or else in a tab of its own."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,), only_tab=True) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_target(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the history's thirty seconds included. The one tab is
    left wherever the test before left it, so no list is ever read where it
    stands, which the list Login opened is (#48), and every run loads it."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "FRESH_LIST_MS", 0, raising=False)
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    return SITE


@pytest.fixture()
def decides_after_the_first_look(monkeypatch):
    """The check comes up the moment after the app first looks at the blank
    history, which is when Walmart's moved in the report. Tied to the app's
    look rather than to a clock, so it happens after that look however long
    the app waited for the history."""
    real = site.detect_security_challenge

    def look(page):
        said = real(page)
        SITE.decided.set()
        return said

    monkeypatch.setattr(site, "detect_security_challenge", look)
    # Long enough for the check to arrive. It stops looking when it does.
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 5000, raising=False)


def _launched_here(monkeypatch):
    """The older setting with no cdp_url, where the app starts its own
    browser and waits for Enter. Playwright's own Chromium, forced headless,
    never a browser of the person's."""
    pw = pytest.importorskip("playwright.sync_api")
    real = pw.BrowserType.launch_persistent_context

    def headless(self, user_data_dir, **kw):
        kw["headless"] = True
        kw["args"] = list(kw.get("args") or []) + [NO_HOSTS]
        return real(self, user_data_dir, **kw)

    monkeypatch.setattr(pw.BrowserType, "launch_persistent_context", headless)
    monkeypatch.setattr(browser_launcher, "bundled_chromium_present", lambda: True)
    # The person pressed Enter after signing in.
    monkeypatch.setattr(browser_launcher, "pause_for_sign_in", lambda *a, **k: True)


@pytest.fixture(params=["attached", "launched here"])
def mode(request, monkeypatch):
    """How the app has its browser. Attached is Login's window over CDP."""
    if request.param == "attached":
        return request.param, request.getfixturevalue("attached")
    _launched_here(monkeypatch)
    return request.param, ""


def config_for(tmp_path, cdp_url):
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def login(tmp_path, cdp_url, capsys):
    assert app_mod.main(["--login", "--config", config_for(tmp_path, cdp_url)]) == 0
    return printed(capsys)


def claims_a_session(out):
    return "Connected to your signed-in Target session" in out or \
        "Signed-in session detected" in out


# -- --login ----------------------------------------------------------------------

def test_a_history_that_never_comes_is_not_called_signed_in(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "orders did not load" in out and "window" in out, out


def test_the_check_that_comes_a_moment_later_is_named(mode, decides_after_the_first_look,
                                                      tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'quick verification'" in out, out


def test_a_check_drawn_over_the_list_is_named(mode, tmp_path, capsys):
    """The list came, and so did the check over it. Login never looked for
    a check at all."""
    SITE.orders = LISTED_UNDER_THE_CHECK
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'quick verification'" in out, out
    if how == "attached":
        assert "reload the page first" in out, out


def test_a_history_that_comes_is_still_signed_in(mode, tmp_path, capsys):
    """What worked before still works. The history is there, so it says so."""
    SITE.orders = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Connected to your signed-in Target session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
    assert "did not load" not in out


def test_a_history_with_its_tabs_and_nothing_under_them_is_signed_in(mode, tmp_path, capsys):
    """The tabs are drawn by the history itself, so they are the history
    there, whatever is under them."""
    SITE.orders = TABS_ONLY
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
    with pytest.raises(SystemExit) as stopped:
        app_mod.main([*flags, "--config", config_for(tmp_path, cdp_url)])
    out = printed(capsys)
    assert stopped.value.code == 0, out
    return out


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def kinds(tmp_path):
    found = [r.get("purchase_type") for r in known(tmp_path).values() if isinstance(r, dict)]
    return found.count(ONLINE), found.count(IN_STORE)


def test_a_pilot_stops_rather_than_find_nothing_on_a_history_that_never_comes(attached, tmp_path,
                                                                              capsys):
    """It used to find no purchases on the blank page, and with nothing to
    do it finished, and the panel read the run as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "orders did not load" in out and "let go of the browser" in out, out
    assert "press Resume" in out, out
    assert not known(tmp_path), "nothing is recorded from a page with no purchases on it"
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_at_a_console_too_it_lets_go_rather_than_wait_attached(attached, tmp_path, capsys,
                                                               monkeypatch):
    """Whatever the window shows is the person's to answer with the app
    gone, since it may be Target's check in a form the app cannot read
    (#48). Nobody is asked to answer it while the app waits."""
    asked = []
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: asked.append(prompt) or "")
    out = stopped_run(tmp_path, attached, capsys, "--discover")

    assert asked == [], asked
    assert "let go of the browser" in out, out
    assert kinds(tmp_path) == (0, 0)


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "Security challenge detected: 'quick verification'" in out, out
    assert "reload the page first" in out, out
    assert not known(tmp_path)


def test_discovery_still_reads_a_history_that_comes(attached, tmp_path, capsys):
    """What worked before still works, online orders and store trips, each
    behind its own tab."""
    SITE.orders = LISTED
    assert app_mod.main(["--discover", "--config", config_for(tmp_path, attached)]) == 0

    assert kinds(tmp_path) == (2, 1)
    assert "did not load" not in printed(capsys)


def _answered_at_the_console(monkeypatch):
    asked = []
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: asked.append(prompt) or "")
    return asked


def test_a_step_up_answered_at_the_console_loads_the_history_once_more_not_twice(
        attached, tmp_path, capsys, monkeypatch):
    """The answer opens the orders page again, and that page is the one
    read. Loading it a second time straight after was one more of the page
    loads a tester counted before Target's check came (#48)."""
    SITE.plan = [STEP_UP_PAGE, LISTED]
    asked = _answered_at_the_console(monkeypatch)
    assert app_mod.main(["--discover", "--config", config_for(tmp_path, attached)]) == 0

    assert len(asked) == 1, asked
    assert SITE.seen.count("/orders") == 3, "twice for the online half, once for the in-store half"
    assert kinds(tmp_path) == (2, 1)


def test_a_history_that_never_comes_after_an_answer_is_not_read_as_empty(
        attached, tmp_path, capsys, monkeypatch):
    """The step-up was over a list, and once it was answered the orders page
    opened again and drew nothing. With only the online half to read, that
    blank page was read as no online orders and the run finished clean."""
    SITE.plan = [LISTED_UNDER_A_STEP_UP, DECIDING]
    asked = _answered_at_the_console(monkeypatch)
    out = stopped_run(tmp_path, attached, capsys, "--pilot-online")

    assert len(asked) == 1, asked
    assert "orders did not load" in out and "let go of the browser" in out, out
    assert kinds(tmp_path) == (0, 0)


def test_an_install_that_owns_its_window_asks_and_then_goes_on(tmp_path, capsys, monkeypatch):
    """Without cdp_url the app launched the window itself, and letting go
    of it would close it, so at a console the run waits for the person, and
    once they say the page shows their orders it opens the history again.
    Past a few questions they give up with Ctrl+C, so a loop that asks
    forever fails here rather than hanging the suite."""
    _launched_here(monkeypatch)
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.orders = LISTED
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    assert app_mod.main(["--discover", "--config", config_for(tmp_path, "")]) == 0

    assert len(asked) == 1 and "shows your orders" in asked[0], asked
    assert kinds(tmp_path) == (2, 1)
