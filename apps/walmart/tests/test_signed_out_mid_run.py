"""A run that Walmart signs out halfway through, at a console, in a real browser.

When Walmart signs the person out, a run started from a terminal asks them
to sign in again and then opens the order list. process_one had just
opened a purchase's details page, and after that question it went on to
read whatever page was in front of it, which was now the order list. The
purchase took the first date on the list, another order's, its details
address became the list's, and the list itself was printed and filed
under the purchase's name. The provider's name is on the list, so the
check on the saved file found a word it expected and passed it.

Here the run reaches its first purchase just as the session runs out, so
the details page shows Walmart's sign-in page until the person at the
console has signed in again. The purchase has to come out with its own
date, its own address and its own receipt. Under the panel there is
nobody to ask, and the run stops rather than go on, as it did before.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Walmart. Every order
number, store, item and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core.models import IN_STORE, ONLINE

# Fifteen digits, as an online order's key is, and printed on its own page
# as seven, a dash and eight.
ONLINE_ORDER = "100000000000003"
STORE_ORDER = "100000000000004"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The order list, with the header every Walmart page carries. The store
# purchase above the online order has a date on its card, as store
# purchases do, and the online order's card has none, as online orders do.
LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<header><a href="/">Walmart</a> Save money. Live better.</header>
<h1>Purchase history</h1>
<div data-testid="order-0">
  <p>Store purchase</p><p>Purchased at Example Supercenter</p>
  <p>Jun 12, 2026</p><p>$23.41</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
<div data-testid="order-1">
  <p>Delivered</p><p>$57.68</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
</body></html>""" % (STORE_ORDER, ONLINE_ORDER)

# The online order's own page, which is the only place its date is shown.
DETAILS = """<!doctype html><html><head><title>Order details</title></head><body>
<header><a href="/">Walmart</a></header>
<main>
<h1>Jun 3, 2026 order</h1>
<p>Order# 1000000-00000003</p>
<p>Delivered</p>
<div data-testid="itemtile-stack">
  <span data-testid="productName">Invented Garden Hose, 50 ft</span>
  <p>Qty 1</p><span data-testid="line-price">$41.97</span>
</div>
<div data-testid="itemtile-stack">
  <span data-testid="productName">Invented Brass Hose Nozzle</span>
  <p>Qty 1</p><span data-testid="line-price">$9.46</span>
</div>
<p>Subtotal $51.43</p><p>Tax $6.25</p><p>Total $57.68</p>
</main></body></html>"""

SIGN_IN = """<!doctype html><html><head><title>Sign in or create your account</title></head>
<body><h1>Sign in or create your account</h1>
<form><label>Email address <input type="email"></label>
<label>Password <input type="password"></label>
<button type="button">Sign in</button></form></body></html>"""


class FakeWalmart:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.signed_in = True
        self.seen = []


SITE = FakeWalmart()


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

    def _to_sign_in(self):
        # Where Walmart sends a signed-out visitor, with the way back.
        self.send_response(302)
        self.send_header("Location", "/account/login?returnUrl=" + quote(self.path, safe=""))
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == "/account/login":
            self._answer(SIGN_IN)
        elif path in ("/orders", "/orders/" + ONLINE_ORDER):
            if not SITE.signed_in:
                self._to_sign_in()
            else:
                self._answer(LISTED if path == "/orders" else DETAILS)
        else:
            self.send_error(404)

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
    # A details address is built on Walmart's own host, and only an address
    # on it is opened. Here that host is this machine.
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    return SITE


@pytest.fixture()
def lapses_at_the_first_purchase(monkeypatch):
    """The session runs out just as the run opens its first purchase, after
    the order list was read signed in. Tied to the app opening the page
    rather than to a clock."""
    real = site.goto_details
    lapsed = []

    def opened(page, purchase):
        if not lapsed:
            lapsed.append(purchase.order_number)
            SITE.signed_in = False
        return real(page, purchase)

    monkeypatch.setattr(site, "goto_details", opened)
    return lapsed


def answering(monkeypatch, signs_in_at=1, limit=5):
    """Somebody at the console, who presses Enter at every question and has
    signed in again by the `signs_in_at`th. Past `limit` questions they give
    up with Ctrl+C, so a loop that asks forever fails here rather than
    hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > limit:
            raise KeyboardInterrupt
        if len(asked) >= signs_in_at:
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


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def online_pilot(tmp_path, cdp_url):
    assert app_mod.main(["--pilot-online", "--config", str(config_for(tmp_path, cdp_url))]) == 0


def record(tmp_path):
    progress = json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))
    return progress["Online:" + ONLINE_ORDER]


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def assert_its_own(rec, server):
    """The purchase as its own page shows it, in the record and in the file."""
    assert rec["purchase_date"] == "2026-06-03", rec
    assert rec["details_url"] == server + "/orders/" + ONLINE_ORDER, rec
    assert rec["total"] == "$57.68", rec
    assert [i["name"] for i in rec["items"]] == ["Invented Garden Hose, 50 ft",
                                                 "Invented Brass Hose Nozzle"], rec
    assert rec.get("downloaded_ok") is True, rec
    assert rec["pdf_filename"].startswith("2026-06-03 "), rec
    text = pdf_text(rec["pdf_path"])
    assert "Invented Garden Hose" in text, text
    assert "Example Supercenter" not in text, "the order list was saved as the receipt"


def test_after_signing_in_again_the_purchase_is_read_from_its_own_page(
        attached, server, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    asked = answering(monkeypatch)
    online_pilot(tmp_path, attached)
    out = printed(capsys)

    assert lapses_at_the_first_purchase == [ONLINE_ORDER]
    assert len(asked) == 1 and "signed in again" in asked[0], asked
    assert "appears to have signed you out" in out, out
    assert_its_own(record(tmp_path), server)
    assert SITE.seen.count("/orders/" + ONLINE_ORDER) == 2, \
        "the purchase is opened once, and once more after the sign-in"


def test_a_person_who_answers_before_signing_in_is_asked_again(
        attached, server, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    """Enter pressed while the sign-in page is still up. Nothing may be read
    from that page as this purchase, and nothing is, the question is put
    again, and the purchase is read once they really have signed in."""
    asked = answering(monkeypatch, signs_in_at=2)
    online_pilot(tmp_path, attached)

    assert len(asked) == 2 and all("signed in again" in q for q in asked), asked
    assert_its_own(record(tmp_path), server)


def test_a_purchase_opened_signed_in_is_read_as_before(attached, server, tmp_path, capsys,
                                                       monkeypatch):
    """What worked before still works. Nothing asked, the page read once."""
    asked = answering(monkeypatch)
    online_pilot(tmp_path, attached)

    assert asked == []
    assert_its_own(record(tmp_path), server)
    assert SITE.seen.count("/orders/" + ONLINE_ORDER) == 1


def test_under_the_panel_the_run_stops_and_the_purchase_waits(
        attached, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    """Nobody to ask. The run stops as it did before, with the exception in
    flight so the panel reports it as stopped, and the purchase is not
    recorded as done, so Resume takes it up again."""
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: None)
    cfg = config_for(tmp_path, attached)
    with pytest.raises(SystemExit) as stopped:
        app_mod.main(["--pilot-online", "--config", str(cfg)])
    out = printed(capsys)

    assert stopped.value.code == 0, out
    assert "press Resume" in out, out
    progress = tmp_path / "out" / "progress.json"
    rec = (json.loads(progress.read_text(encoding="utf-8")).get("Online:" + ONLINE_ORDER)
           if progress.exists() else None)
    assert not (rec or {}).get("downloaded_ok"), rec
