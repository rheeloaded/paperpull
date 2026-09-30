"""A run that GitHub signs out halfway through, at a console, in a real browser.

When GitHub signs the person out, a run started from a terminal asks them
to sign in again and then opens the payment history's first page, because
that is a page it knows how to open. Two places read whatever was in front
of them after that question.

Discovery walks the history a page at a time and stops at the first page
that holds nothing new. Asked for the second page and handed the first,
it found nothing new there and stopped, so every payment from the second
page on was never found, and the run finished as though there were none.

A receipt that is a page rather than a PDF is opened and printed. Handed
the history instead, which has amounts and the word receipt on it, it
printed the history, filed it under the payment's name and marked the
payment downloaded, so the real receipt was never asked for again.

Here the session runs out at those two moments, and the person at the
console signs in again. The browser is started as a program of its own
with a debugging port, the way login.bat leaves one open, and the app
attaches to it over CDP exactly as it does at home. Every page comes from
a server on this machine and the browser resolves no host name, so
nothing reaches GitHub. Every payment, id and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import github_receipts as app_mod
import github_site as site
from paperpull_core import browser as browser_launcher

HISTORY = "/account/billing/history"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The history, two payments to a page, newest first. Each row links to its
# receipt, which is a page of its own.
PAYMENTS = {
    1: [("20000001", "Jun 1, 2026", "GitHub Copilot Pro (monthly)", "$10.00"),
        ("20000002", "May 1, 2026", "GitHub Pro (monthly)", "$4.00")],
    2: [("20000003", "Apr 1, 2026", "GitHub Team (monthly)", "$8.00")],
}


def history_page(page_no):
    rows = "".join(
        '<li><div>%s</div><div>%s</div><div>Visa ending in 4242</div><div>%s</div>'
        '<a href="%s/%s/receipt" aria-label="View receipt">Receipt</a></li>'
        % (when, what, amount, HISTORY, pid)
        for pid, when, what, amount in PAYMENTS.get(page_no, [])) \
        or "<li>No more payments to show.</li>"
    return ("<!doctype html><html><head><title>Payment history</title></head><body>"
            "<h1>Payment history</h1>"
            '<turbo-frame id="settings-frame"><ul>%s</ul></turbo-frame>'
            "</body></html>" % rows)


def receipt_page(pid):
    for payments in PAYMENTS.values():
        for p, when, what, amount in payments:
            if p == pid:
                return ("<!doctype html><html><head><title>Receipt</title></head><body>"
                        "<main><div class=\"receipt\"><h1>GitHub receipt</h1>"
                        "<p>Paid on %s</p><p>Receipt number %s</p>"
                        "<p>%s %s</p><p>Total %s</p>"
                        "<p>Thank you for your payment to GitHub, Inc.</p></div></main>"
                        "</body></html>" % (when, pid, what, amount, amount))
    return None


SIGN_IN = """<!doctype html><html><head><title>Sign in to GitHub</title></head>
<body><h1>Sign in to GitHub</h1>
<form><label>Username or email address <input type="text"></label>
<label>Password <input type="password"></label>
<button type="button">Sign in</button></form></body></html>"""


class FakeGitHub:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.signed_in = True
        self.seen = []


SITE = FakeGitHub()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        SITE.seen.append(self.path)
        if path == "/login":
            self._answer(SIGN_IN)
            return
        page_no = int((parse_qs(parts.query).get("page") or ["1"])[0])
        receipt = None
        if path.startswith(HISTORY + "/") and path.endswith("/receipt"):
            receipt = receipt_page(path[len(HISTORY) + 1:-len("/receipt")])
        if path != HISTORY and receipt is None:
            self.send_error(404)
            return
        if not SITE.signed_in:
            # Where GitHub sends a signed-out visitor, with the way back.
            self.send_response(302)
            self.send_header("Location", "/login?return_to=" + quote(self.path, safe=""))
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._answer(receipt if receipt is not None else history_page(page_no))

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
def fake_github(server, monkeypatch):
    """Every address the app opens points at the made-up site. A receipt
    link is read against GitHub's own host, and only an address on it is
    followed. Here that host is this machine."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + HISTORY)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    return SITE


def lapses(monkeypatch, name, when):
    """The session runs out as the run makes a particular call of the
    site's, tied to the app's own step rather than to a clock. Only once."""
    real = getattr(site, name)
    lapsed = []

    def call(page, *args, **kwargs):
        if not lapsed and when(*args, **kwargs):
            lapsed.append(args)
            SITE.signed_in = False
        return real(page, *args, **kwargs)

    monkeypatch.setattr(site, name, call)
    return lapsed


def answering(monkeypatch, limit=5):
    """Somebody at the console, who signs in again and presses Enter. Past
    `limit` questions they give up with Ctrl+C, so a loop that asks forever
    fails here rather than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > limit:
            raise KeyboardInterrupt
        SITE.signed_in = True
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    return asked


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, *flags):
    assert app_mod.main([*flags, "--config", str(config_for(tmp_path, cdp_url))]) == 0


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def progress(tmp_path):
    return json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


EVERY_PAYMENT = sorted("Online:" + p[0] for ps in PAYMENTS.values() for p in ps)


def test_the_walk_goes_on_from_the_page_it_asked_for(attached, tmp_path, monkeypatch):
    lapsed = lapses(monkeypatch, "goto_orders", lambda page_no=1: page_no == 2)
    asked = answering(monkeypatch)
    run(tmp_path, attached, "--discover")

    assert lapsed == [(2,)], "the session ran out as the second page was asked for"
    assert len(asked) == 1 and "signed in again" in asked[0], asked
    assert sorted(known(tmp_path)) == EVERY_PAYMENT, "a payment past the first page was lost"


def test_a_receipt_page_is_printed_rather_than_the_history(attached, tmp_path, monkeypatch):
    lapsed = lapses(monkeypatch, "goto_receipt_page", lambda url: True)
    asked = answering(monkeypatch)
    run(tmp_path, attached, "--pilot")

    assert len(lapsed) == 1 and len(asked) == 1, (lapsed, asked)
    records = progress(tmp_path)
    assert sorted(records) == EVERY_PAYMENT
    for key, rec in records.items():
        pid = key.split(":", 1)[1]
        assert rec.get("downloaded_ok") is True, rec
        text = pdf_text(rec["pdf_path"])
        assert "Receipt number %s" % pid in text, (key, text[:300])
        assert "Visa ending in" not in text, "the history was printed as %s" % key


def test_a_run_signed_in_throughout_is_as_before(attached, tmp_path, monkeypatch):
    """What worked before still works. Nothing asked, every payment found
    and every receipt printed from its own page."""
    asked = answering(monkeypatch)
    run(tmp_path, attached, "--pilot")

    assert asked == []
    records = progress(tmp_path)
    assert sorted(records) == EVERY_PAYMENT
    for key, rec in records.items():
        pid = key.split(":", 1)[1]
        assert rec.get("downloaded_ok") is True, rec
        assert "Receipt number %s" % pid in pdf_text(rec["pdf_path"]), key
