"""--login, and the discovery a run starts with, against made-up GitHub
pages in a real browser.

Walmart's --login said Success while its own log said the purchase history
never appeared. The tab was still on the history with nothing on it, while
a bot check decided, and a moment later it was the check itself. This app
asked the same way, one look at a page the payment history never came to,
so here it never comes, or the page turns into GitHub's Confirm access the
moment after the app first looks at it. Neither may be called a success,
and discovery may not read either one as a history with nothing new in it.

A history with no payments is real, and GitHub draws it in the same frame
as one with payments, saying "You have not made any payments."

The browser for the attached runs is started here as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from a
server on this machine and the browser resolves no host name, so nothing
reaches GitHub. Every payment id and amount is invented.
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
import github_receipts as app_mod
import github_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

HISTORY = "/account/billing/history"
FIRST_PAYMENT = "ABCD1234"
SECOND_PAYMENT = "EFGH5678"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history while a check decides. Nothing on it but the check's own
# script, which asks the server what it decided.
DECIDING = """<!doctype html><html><head><title>GitHub</title></head><body>
<div id="root"></div>
<script>
(function wait() {
  fetch('/decision', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'decided') location.replace('/check');
    else setTimeout(wait, 150);
  }, () => setTimeout(wait, 150));
})();
</script></body></html>"""

CHECK = """<!doctype html><html><head><title>Confirm access</title></head><body>
<h1>Confirm access</h1><p>Signed in as @example</p>
<button>Use passkey</button></body></html>"""


def frame(inner: str) -> str:
    return """<!doctype html><html><head><title>Payment history</title></head><body>
<main><turbo-frame id="settings-frame">
<h2>Payment history</h2>
%s
</turbo-frame></main></body></html>""" % inner


ROW = """<tr><td>%s</td><td>%s</td><td>Visa ending in 0000</td><td>$%s</td><td>Paid</td>
<td><a href="/account/receipt/%s">Receipt</a></td><td></td></tr>"""

LISTED = frame("""<table><thead><tr><th>Date</th><th>ID</th><th>Payment Method</th>
<th>Amount</th><th>Status</th><th>Receipt</th><th>Invoice</th></tr></thead>
<tbody>%s%s</tbody></table>""" % (ROW % ("2026-09-13", FIRST_PAYMENT, "4.00", FIRST_PAYMENT),
                                  ROW % ("2026-08-13", SECOND_PAYMENT, "4.00", SECOND_PAYMENT)))

# Past the last page, or an account that has never paid.
EMPTY = frame("<p>You have not made any payments.</p>")

HOME = """<!doctype html><html><head><title>GitHub</title></head>
<body><h1>GitHub</h1></body></html>"""


class FakeGitHub:
    """What the made-up site shows, set by each test. The first page of the
    history, then any page after it."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.first = DECIDING
        self.later = EMPTY
        self.decided = threading.Event()
        self.seen = []


SITE = FakeGitHub()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(parts.path + ("?" + parts.query if parts.query else ""))
        if parts.path == HISTORY:
            page = SITE.later if "page=" in parts.query else SITE.first
            body, kind = page, "text/html; charset=utf-8"
        elif parts.path == "/check":
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
def fake_github(server, monkeypatch):
    """Every page the app opens comes from the made-up site, and every wait
    is short, the frame's twenty seconds included. BASE stays GitHub's, so
    a receipt link reads as GitHub's own, and nothing here opens one."""
    SITE.reset()
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
    however long the app waited for the frame."""
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

def test_a_payment_history_that_never_comes_is_not_called_a_success(mode, tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "payment history did not load" in out and "Look at the browser window" in out, out


def test_a_page_that_turns_into_confirm_access_is_reported(mode, decides_after_the_first_look,
                                                           tmp_path, capsys):
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert not claims_a_session(out), out
    assert "Security challenge detected: 'confirm access'" in out, out
    assert "/check" in SITE.seen, "the page really did turn into the check"


def test_a_payment_history_that_comes_is_still_a_success(mode, tmp_path, capsys):
    """What worked before still works. The history is there, so it says so."""
    SITE.first = LISTED
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    said = ("Success: connected to your signed-in GitHub session." if how == "attached"
            else "Signed-in session detected.")
    assert said in out, out
    assert "did not load" not in out


def test_an_account_that_never_paid_is_still_a_signed_in_one(mode, tmp_path, capsys):
    SITE.first = EMPTY
    how, cdp_url = mode
    out = login(tmp_path, cdp_url, capsys)

    assert claims_a_session(out), out


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
    """It used to find no payments on the blank page, and with nothing to
    do it finished, and the panel read the run as clean."""
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "payment history did not load" in out and "run this again" in out, out
    assert not known(tmp_path), "nothing is recorded from a page with no history on it"
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_a_pilot_stops_on_the_check_that_arrives_a_moment_later(attached,
                                                                decides_after_the_first_look,
                                                                tmp_path, capsys):
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "Security challenge detected: 'confirm access'" in out, out
    assert "I will NOT attempt to bypass it" in out
    assert "/check" in SITE.seen
    assert not known(tmp_path)


def test_discovery_still_reads_a_history_that_comes(attached, tmp_path, capsys):
    """What worked before still works. Both payments on the first page, and
    the page after it adds nothing, so the walk ends there."""
    SITE.first = LISTED
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    records = known(tmp_path)
    assert sorted(records) == ["Online:" + FIRST_PAYMENT, "Online:" + SECOND_PAYMENT], records
    assert records["Online:" + FIRST_PAYMENT]["purchase_date"] == "2026-09-13"
    assert "did not load" not in printed(capsys)


def test_an_account_that_never_paid_finishes_with_nothing_found(attached, tmp_path, capsys):
    SITE.first = EMPTY
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    out = printed(capsys)
    assert "has not made any payments" in out and "did not load" not in out, out
    assert not known(tmp_path)


def test_with_somebody_there_it_asks_them_to_look_and_then_goes_on(attached, tmp_path,
                                                                   capsys, monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say the page shows their payments it opens it again. Past a
    few questions they give up with Ctrl+C, so a loop that asks forever
    fails here rather than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.first = LISTED
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    cfg = config_for(tmp_path, attached)
    assert app_mod.main(["--discover", "--config", str(cfg)]) == 0

    assert len(asked) == 1 and "shows your payments" in asked[0], asked
    assert sorted(known(tmp_path)) == ["Online:" + FIRST_PAYMENT, "Online:" + SECOND_PAYMENT]
