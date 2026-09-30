"""A run that Best Buy signs out halfway through, at a console, in a real browser.

When Best Buy signs the person out, a run started from a terminal asks
them to sign in again and then opens the purchase history. process_one had
just opened a purchase's details page, and after that question it read the
page in front of it, which was now the history. The receipt itself came
out right, because saving it opens the details page again when it is not
the one on screen, but what was read before that did not. There is no
item on the history page, so the purchase kept no items, its name fell
back to "Mixed Purchases" with low confidence, and a receipt that was
perfectly good was filed for manual review under that name.

Here the run reaches its first purchase just as the session runs out, so
the details page shows the sign-in page until the person at the console
has signed in again, and the purchase has to be read from its own page.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Best Buy. Every order
number, item and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_receipts as app_mod
import bestbuy_site as site
from paperpull_core import browser as browser_launcher

HISTORY = "/purchasehistory/purchases"
ONLINE_ORDER = "BBY01-800000000008"
DETAILS_PATH = "/profile/ss/orders/order-details/%s/view" % ONLINE_ORDER

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

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

# The order's own page, which is the receipt and the only place its items are.
DETAILS = """<!doctype html><html><head><title>Order Details</title></head><body>
<header>Shop Deals Support &amp; Services Top Deals</header>
<main><div class="order-details-page__column-wrapper">
  <h1>Order Details</h1>
  <p>Purchase Date: Mar 14, 2026</p><p>Order Number: %s</p><p>Total: $437.12</p>
  <h2>Order Summary</h2><p>Sales Tax, Fees &amp; Surcharges: $23.18</p>
  <div><p>Invented Air Fryer XL</p><p>Model: INV-00002</p><p>SKU: 7654321</p><p>Quantity: 1</p>
       <p>Item Total: $413.94</p></div>
</div></main>
<footer>Corporate Information | Careers</footer></body></html>""" % ONLINE_ORDER

SIGN_IN = """<!doctype html><html><head><title>Sign In to Best Buy</title></head>
<body><h1>Sign In to Best Buy</h1>
<form><label>Email Address <input type="email"></label>
<label>Password <input type="password"></label>
<button type="button">Sign In</button></form></body></html>"""


def history_answer(year):
    """This year holds the one online order, every other year nothing, in
    the shape the history query answers."""
    entries = []
    if year == date.today().year:
        entries = [{"id": ONLINE_ORDER, "orderType": "online",
                    "created": "2026-03-14T15:04:00-05:00",
                    "orderTotal": 437.12, "orderStatusTitle": "Delivered"}]
    return {"data": {"customer": {"purchaseHistoryOrdersExperience": {
        "closedOrdersAndTransactions": {"entries": entries, "pageInfo": {"hasNext": False}},
        "openOrders": {"entries": [], "pageInfo": {"hasNext": False}}}}}}


class FakeBestBuy:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.signed_in = True
        self.seen = []


SITE = FakeBestBuy()


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
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        if path == "/identity/signin":
            self._answer(SIGN_IN)
        elif path in (HISTORY, DETAILS_PATH):
            if SITE.signed_in:
                self._answer(LISTED if path == HISTORY else DETAILS)
                return
            # Where Best Buy sends a signed-out visitor, with the way back.
            self.send_response(302)
            self.send_header("Location", "/identity/signin?token=" + quote(self.path, safe=""))
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
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
def fake_bestbuy(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the details page's thirty seconds included."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    # The history query is only kept, and asked again, on Best Buy's own
    # host, and only a details address on it is opened. Here that host is
    # this machine.
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800)
    monkeypatch.setattr(site, "SETTLE_MS", 0)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500)
    real_wait = site.wait_for_details
    monkeypatch.setattr(site, "wait_for_details",
                        lambda page, timeout_ms=30000, names_ms=10000:
                        real_wait(page, timeout_ms=min(timeout_ms, 2000),
                                  names_ms=min(names_ms, 2000)))
    return SITE


@pytest.fixture()
def lapses_at_the_first_purchase(monkeypatch):
    """The session runs out just as the run opens its first purchase, after
    the history was read signed in. Tied to the app opening the page rather
    than to a clock."""
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


def pilot(tmp_path, cdp_url):
    assert app_mod.main(["--pilot", "--config", str(config_for(tmp_path, cdp_url))]) == 0


def record(tmp_path):
    progress = json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))
    return progress["Online:" + ONLINE_ORDER]


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def assert_its_own(rec):
    """The purchase as its own page shows it, in the record and in the name
    of its file."""
    assert [i["name"] for i in rec["items"]] == ["Invented Air Fryer XL"], rec
    assert rec["summary"] == "Air Fryer" and rec["confidence"] == "High", rec
    assert rec["state"] == "Completed", rec
    assert rec["purchase_date"] == "2026-03-14" and rec["total"] == "$437.12", rec
    assert rec.get("downloaded_ok") is True, rec
    assert rec["pdf_filename"] == "2026-03-14 Best Buy Air Fryer Receipt.pdf", rec
    assert "Order Number: %s" % ONLINE_ORDER in pdf_text(rec["pdf_path"])


def test_after_signing_in_again_the_purchase_is_read_from_its_own_page(
        attached, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    asked = answering(monkeypatch)
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert lapses_at_the_first_purchase == [ONLINE_ORDER]
    assert len(asked) == 1 and "signed in again" in asked[0], asked
    assert "appears to have signed you out" in out, out
    assert_its_own(record(tmp_path))


def test_a_person_who_answers_before_signing_in_is_asked_again(
        attached, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    """Enter pressed while the sign-in page is still up. Nothing may be read
    from that page as this purchase, the question is put again, and the
    purchase is read once they really have signed in."""
    asked = answering(monkeypatch, signs_in_at=2)
    pilot(tmp_path, attached)

    assert len(asked) == 2 and all("signed in again" in q for q in asked), asked
    assert_its_own(record(tmp_path))


def test_a_purchase_opened_signed_in_is_read_as_before(attached, tmp_path, capsys, monkeypatch):
    """What worked before still works. Nothing asked, the page read once."""
    asked = answering(monkeypatch)
    pilot(tmp_path, attached)

    assert asked == []
    assert_its_own(record(tmp_path))
    assert SITE.seen.count(DETAILS_PATH) == 1


def test_under_the_panel_the_run_stops_and_the_purchase_waits(
        attached, lapses_at_the_first_purchase, tmp_path, capsys, monkeypatch):
    """Nobody to ask. The run stops as it did before, with the exception in
    flight so the panel reports it as stopped, and the purchase is not
    recorded as done, so Resume takes it up again."""
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: None)
    cfg = config_for(tmp_path, attached)
    with pytest.raises(SystemExit) as stopped:
        app_mod.main(["--pilot", "--config", str(cfg)])
    out = printed(capsys)

    assert stopped.value.code == 0, out
    assert "press Resume" in out, out
    progress = tmp_path / "out" / "progress.json"
    rec = (json.loads(progress.read_text(encoding="utf-8")).get("Online:" + ONLINE_ORDER)
           if progress.exists() else None)
    assert not (rec or {}).get("downloaded_ok"), rec
