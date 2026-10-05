"""A control naming the receipt that could not be read is never taken to
mean there is no receipt, in a real browser.

open_receipt_section read the name of each control that names the receipt
section, waiting a second and a half, inside one try for each kind of
control. One that did not answer in time abandoned its whole kind, and
when nothing else opened, the details page had no Print receipts control
either. The purchase was then marked No Receipt Available, which is never
asked about again. Target's details page also offers "View invoice", so
with include_invoices on, which is how a new install comes, the invoice
was filed in the receipt's place and the order sealed. Either way the
receipt was never saved. On the stalled CI runner of run 36792330947 every
read like it timed out on E*TRADE's page, so a slow page is enough.

find_print_receipt_controls and find_invoice_controls kept a control whose
name could not be read, as if it had passed the check its name is read
for, so one that prints a gift receipt or starts a return could be
pressed. Target's own gift receipt control is named "Print gift receipt",
which the Print receipts pattern never matches. The check on the words is
there for a control labeled Print receipts whose words say gift receipt,
and that is the one made here.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP as it
does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Target. A read is made
to fail the way it failed on the stalled runner, with Playwright's own
TimeoutError, for the controls a test names and no other. Every order
number, item and amount is invented.
"""
import itertools
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts as app_mod
import target_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import receipt_pdf
from paperpull_core.models import State

APP_DIR = Path(__file__).resolve().parents[1]

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The wait itself, before the fixture below shortens it for the made-up site.
REAL_WAIT_FOR_RECEIPT = site.wait_for_receipt_content


class Order:
    """One made-up online order. `receipt` says whether Target has a store
    receipt for it, or only its invoice."""

    def __init__(self, number, iso, placed, items, invoice, receipt=True):
        self.number = number
        self.iso = iso            # the date the app files it under
        self.placed = placed      # as the list and the details page print it
        self.items = items        # (name, price)
        self.invoice = invoice    # its invoice's number
        self.receipt = receipt

    @property
    def total(self):
        return "$%.2f" % sum(float(price[1:]) for _, price in self.items)


# An order with a store receipt.
RECEIPTED = Order("902000000000061", "2026-03-03", "Mar 3, 2026",
                  [("Invented Ceramic Planter, 6 in", "$14.25"),
                   ("Invented Potting Soil, 8 qt", "$6.18")],
                  "10000000000000061")

# An order Target has only an invoice for.
INVOICED = Order("902000000000071", "2026-03-04", "Mar 4, 2026",
                 [("Invented Bamboo Cutting Board", "$11.47")],
                 "10000000000000071", receipt=False)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Orders : %s</title></head>
<body><header><p>Ship to 00000</p><a href="/">Home</a></header>
<main>%s</main><footer><p>Help</p><p>Returns</p></footer></body></html>"""

# Controls the app must never press. Each leads somewhere the server
# remembers.
TRIPWIRES = ('<a href="/tripwire/return">Start a return</a>'
             '<a href="/tripwire/again">Buy it again</a>')

# Labeled for printing receipts, and its words say what it prints. Its
# words are the only thing that tells it from the real Print receipts.
GIFTISH = ('<button type="button" data-guid="giftish" aria-label="Print receipts" '
           'onclick="printGift()">Print gift receipt</button>')

# Labeled as an invoice, and its words say it starts a return.
RETURNISH = ('<a data-guid="returnish" aria-label="View invoice" '
             'href="/tripwire/return">Start a return</a>')

# The page a tab of the attached browser is first opened on. Once it has
# drawn it tells the server so, by the name its tab was opened with, never
# through the debugging port.
DRAWN = """<!doctype html><html><head><title>Ready</title></head><body><script>
fetch('/beacon/%(tab)s', {cache: 'no-store'}).catch(() => {});
</script></body></html>"""

# The names of the tabs whose page has drawn.
DRAWN_TABS = set()


def orders_page():
    cards = "".join(
        '<a data-test="order-details-link" href="/orders/%s"><p>Delivered</p>'
        "<p>%s</p><p>%s</p><p>#%s</p></a>" % (o.number, o.placed, o.total, o.number)
        for o in SITE.orders.values())
    return PAGE % ("Orders", '<h1>Orders</h1><div role="tablist">'
                   '<button role="tab" data-test="tabOnline">Online</button>'
                   '<button role="tab" data-test="tabInstore">In-store</button></div>'
                   + cards)


def details_page(o):
    """The way Target's details page is, a link to the order's receipts
    and one straight to its invoice."""
    rows = "".join('<div data-test="package-card-item-row"><div>%s</div><div>%s</div>'
                   "<div>Qty 1</div></div>" % item for item in o.items)
    return PAGE % ("Order details",
                   "<h1>Order #%s</h1><p>Placed %s</p><p>Delivered</p>%s<p>Total %s</p>"
                   '<p><a data-guid="section" href="/orders/%s/receipts">Receipts &amp; invoices'
                   '</a></p><p><a href="/orders/%s/invoices/%s">View invoice</a></p>%s'
                   % (o.number, o.placed, rows, o.total, o.number, o.number, o.invoice,
                      TRIPWIRES))


def _document(heading, o, prices):
    """A receipt as the frame that prints it holds it, a whole document.
    A gift receipt shows no prices. The core keeps what was printed only
    when it is more than a few lines, as a real receipt is."""
    rows = "".join("<tr><td>%s</td><td>Qty 1</td><td>%s</td></tr>"
                   % (name, price if prices else "") for name, price in o.items)
    total = ("<p>Subtotal %s</p><p>Tax $0.00</p><p>Total %s</p>"
             "<p>Paid with a card ending 0000</p>" % (o.total, o.total)) if prices else ""
    return ("<!doctype html><html><head><title>Receipt</title></head><body>"
            "<h1>%s</h1><p>Order #%s</p><p>Placed %s</p>"
            "<p>Example Store, 0000 Example Way, Example Town</p>"
            "<table><tr><th>Item</th><th>Quantity</th><th>Price</th></tr>%s</table>%s"
            "<p>Keep this receipt with your purchase. Returns and exchanges are taken "
            "at any store with the card the purchase was made with.</p></body></html>"
            % (heading, o.number, o.placed, rows, total))


def _as_script(html):
    return json.dumps(html).replace("</", "<\\/")


def receipts_page(o):
    """Print receipts builds the receipt in a frame of its own and prints
    it from there, the way Target's does, and each press tells the server."""
    controls = ""
    if o.receipt:
        controls = ((GIFTISH if SITE.giftish else "")
                    + '<button type="button" data-guid="print" onclick="printReceipt()">'
                    "Print receipts</button>"
                    '<button type="button" onclick="printGift()">Print gift receipt</button>')
    script = """<script>
function printDocument(html) {
  const f = document.createElement('iframe');
  f.style.display = 'none';
  document.body.appendChild(f);
  f.contentDocument.open();
  f.contentDocument.write(html);
  f.contentDocument.close();
  f.contentWindow.print();
  f.remove();
}
function printReceipt() {
  fetch('/pressed/print', {cache: 'no-store'}).catch(() => {});
  printDocument(%s);
}
function printGift() {
  fetch('/tripwire/gift', {cache: 'no-store'}).catch(() => {});
  printDocument(%s);
}
</script>""" % (_as_script(_document("Store receipt", o, True)),
                _as_script(_document("Gift receipt", o, False)))
    return PAGE % ("Receipts", "<h1>Receipts and invoices</h1>%s"
                   '<p><a href="/orders/%s/invoices">View detailed invoices</a></p>%s%s'
                   % (controls, o.number, TRIPWIRES, script))


def invoice_list(o):
    return PAGE % ("Invoices", "<h1>Invoices</h1>%s<section><h2>Invoice 1 of 1</h2>"
                   '<a data-guid="invoice" href="/orders/%s/invoices/%s">View invoice</a>'
                   "</section>%s" % (RETURNISH if SITE.returnish else "", o.number, o.invoice,
                                     TRIPWIRES))


def invoice_page(o):
    items = "".join("<div>%s</div><div>Qty. 1</div>" % name for name, _ in o.items)
    return PAGE % ("Invoice Details",
                   "<h1>Invoice 1 of 1</h1><p>Invoice date: %s</p><p>Invoice number: %s</p>"
                   "<div>Item</div>%s<div>Invoice total %s</div>"
                   % (o.placed, o.invoice, items, o.total))


class FakeTarget:
    """What the made-up site shows, set by each test, and what it saw."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = {}
        self.seen = []
        self.giftish = False
        self.returnish = False

    def show(self, *orders):
        self.orders = {o.number: o for o in orders}

    def opened(self, path) -> int:
        return self.seen.count(path)


SITE = FakeTarget()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, and every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        # The fixture's own page, never counted as anything the app opened.
        if path.startswith("/beacon/"):
            DRAWN_TABS.add(path[len("/beacon/"):])
            return self._answer("ok")
        if path.startswith("/drawn/"):
            return self._answer(DRAWN % {"tab": path[len("/drawn/"):]})
        SITE.seen.append(path)
        if path == "/" or path.startswith(("/tripwire/", "/pressed/")):
            return self._answer(PAGE % ("Home", "<h1>Nothing here</h1>"))
        parts = path.strip("/").split("/")
        o = SITE.orders.get(parts[1]) if len(parts) > 1 and parts[0] == "orders" else None
        if parts == ["orders"]:
            return self._answer(orders_page())
        if o is not None and len(parts) == 2:
            return self._answer(details_page(o))
        if o is not None and parts[2:] == ["receipts"]:
            return self._answer(receipts_page(o))
        if o is not None and parts[2:] == ["invoices"]:
            return self._answer(invoice_list(o))
        if o is not None and parts[2:] == ["invoices", o.invoice]:
            return self._answer(invoice_page(o))
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


# -- the browser the app attaches to --------------------------------------------

def _start_browser(exe, profile):
    """The browser as a program of its own with a debugging port, and its
    address, or None for the address when it opened no port.

    It starts with no window of its own, so its only tab is the one opened
    here. The blank tab a fresh browser starts with sometimes never closed,
    or was never listed, and the app worked in the first tab it found."""
    proc = subprocess.Popen(
        [exe, "--headless=new", "--remote-debugging-port=0",
         "--user-data-dir=%s" % profile, "--disable-extensions", "--disable-sync",
         "--no-first-run", "--no-default-browser-check", "--no-startup-window", NO_HOSTS],
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


def _page_targets(cdp_url):
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def _close_tab(cdp_url, target_id):
    urllib.request.urlopen(cdp_url + "/json/close/" + target_id, timeout=10).read()


def _gone(cdp_url, target_id, seconds=10):
    """Until the tab is off the browser's list."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if all(t["id"] != target_id for t in _page_targets(cdp_url)):
            return
        time.sleep(0.1)


def _drawn(name, seconds) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if name in DRAWN_TABS:
            return True
        time.sleep(0.05)
    return False


def _only_tab_left(cdp_url, target_id, seconds) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if [t["id"] for t in _page_targets(cdp_url)] == [target_id]:
            return True
        time.sleep(0.1)
    return False


_TAB_NAMES = itertools.count(1)


def _open_drawn(cdp_url, server):
    """A tab the browser itself opens on a page of this file's server, once
    that page has drawn, as its id, or None.

    The first tab a fresh browser opens sometimes never sends a single
    request, for a minute and more, and a second tab always drew. So a tab
    that has not drawn in 10 seconds is closed, and another opened once it
    is gone, three at most."""
    for _attempt in range(3):
        name = "tab%d" % next(_TAB_NAMES)
        request = urllib.request.Request(
            "%s/json/new?%s/drawn/%s" % (cdp_url, server, name), method="PUT")
        with urllib.request.urlopen(request, timeout=10) as r:
            tab = json.loads(r.read().decode("utf-8"))
        if _drawn(name, 10):
            return tab["id"]
        _close_tab(cdp_url, tab["id"])
        _gone(cdp_url, tab["id"])
    return None


@pytest.fixture(scope="module")
def attached(server, tmp_path_factory):
    """Playwright's own Chromium, never the person's everyday browser,
    started as a program of its own with a debugging port, which is what
    the app attaches to at home. Its address, for cdp_url.

    It is handed over with one tab, on a page of this server's that has
    drawn, and the app works in that tab. A browser that cannot get there
    is closed and another started, three at most, and a failure says what
    each one did."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    tried = []
    for _start in range(3):
        proc, url = _start_browser(found[0][1], tmp_path_factory.mktemp("attached-profile"))
        if url is None:
            proc.kill()
            proc.wait(timeout=15)
            pytest.skip("the browser opened no debugging port")
        ready = _open_drawn(url, server)
        if ready is not None and _only_tab_left(url, ready, 10):
            break
        tried.append("%s, tabs %r" % ("never drew a page" if ready is None else
                                      "a tab never closed",
                                      [t.get("url") for t in _page_targets(url)]))
        proc.kill()
        proc.wait(timeout=15)
    else:
        pytest.fail("three fresh browsers in a row were not ready, %s" % "; ".join(tried))
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
def fake_target(server, monkeypatch):
    """Every address the app opens points at the made-up site, and the
    waits that only ever run out on these pages are short."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    # An order with only an invoice has neither a store receipt nor a print
    # frame, so these two always wait out their whole time.
    monkeypatch.setattr(site, "wait_for_receipt_content",
                        lambda page, timeout_ms=15000: REAL_WAIT_FOR_RECEIPT(page, 1000))
    real_frame = site.find_printing_frame
    monkeypatch.setattr(site, "find_printing_frame",
                        lambda page, wait_ms=6000: real_frame(page, wait_ms=min(wait_ms, 500)))
    monkeypatch.setattr(site, "INVOICE_SETTLE_MS", 200, raising=False)
    return SITE


# -- a read that does not answer ------------------------------------------------------

# The data-guid of each control whose name cannot be read, set by a test.
STALLED = set()


@pytest.fixture()
def stalled(monkeypatch):
    """Reading the words of a control whose data-guid is in STALLED waits
    out the time the read was given, two seconds at most, and raises
    Playwright's TimeoutError, the way reads failed on the stalled CI runner
    of run 36792330947. Every other read answers as it would. The control
    is known by its own data-guid, asked of the page before the read that
    fails. A test empties the set to let the reads answer again."""
    from playwright.sync_api import Locator
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    real_text, guid_of = Locator.inner_text, Locator.get_attribute

    def inner_text(self, *args, **kwargs):
        if STALLED:
            try:
                guid = guid_of(self, "data-guid", timeout=500) if self.count() == 1 else None
            except Exception:
                guid = None
            if guid in STALLED:
                time.sleep(min(kwargs.get("timeout") or 0, 2000) / 1000)
                raise PlaywrightTimeout("Timeout exceeded, a read stalled by this test.")
        return real_text(self, *args, **kwargs)

    STALLED.clear()
    monkeypatch.setattr(Locator, "inner_text", inner_text)
    yield STALLED
    STALLED.clear()


def config_for(tmp_path, cdp_url, include_invoices=True):
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                "profile_dir": str(tmp_path / "unused-profile"), "cdp_url": cdp_url,
                "include_invoices": include_invoices,
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def run(tmp_path, cdp_url, command, include_invoices=True):
    return app_mod.main([command, "--config", config_for(tmp_path, cdp_url, include_invoices)])


def record(tmp_path, order):
    progress = json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))
    return progress["Online:" + order.number]


def pdfs(tmp_path, folder, order):
    """The PDFs in one of the app's folders for this order's day."""
    where = tmp_path / "out" / folder
    return sorted(p for p in where.glob("*.pdf") if p.name.startswith(order.iso + " ")) \
        if where.exists() else []


def text_of(path):
    return " ".join(receipt_pdf.pdf_text(Path(path)).split())


def left_for_the_next_run(rec):
    """The purchase is neither done nor concluded, and says why."""
    assert rec["state"] == State.FAILED.value, rec
    assert not rec.get("downloaded_ok"), rec
    assert "could not be read" in rec["notes"], rec["notes"]
    assert "tried again next run" in rec["notes"], rec["notes"]


def the_receipt_is_saved(tmp_path, order):
    rec = record(tmp_path, order)
    assert rec["state"] == State.COMPLETED.value, rec
    assert rec["downloaded_ok"] is True, rec
    saved = pdfs(tmp_path, "Online", order)
    assert len(saved) == 1, saved
    assert "Store receipt" in text_of(saved[0]) and order.number in text_of(saved[0])
    assert not pdfs(tmp_path, "Invoices", order), "the invoice was filed as well"


# -- whole runs, the app attached as at home ----------------------------------------------

@pytest.mark.parametrize("include_invoices", [False, True],
                         ids=["invoices off", "invoices on"])
def test_a_receipt_link_it_could_not_read_leaves_the_order_for_the_next_run(
        attached, stalled, tmp_path, include_invoices):
    """Off, the order was marked No Receipt Available. On, its invoice was
    filed in the receipt's place and the order sealed. Either way it was
    never asked about again, and its receipt was never saved."""
    SITE.show(RECEIPTED)
    invoice = "/orders/%s/invoices/%s" % (RECEIPTED.number, RECEIPTED.invoice)
    stalled.add("section")
    assert run(tmp_path, attached, "--pilot-online", include_invoices) == 0

    left_for_the_next_run(record(tmp_path, RECEIPTED))
    assert SITE.opened(invoice) == 0, "the invoice was opened in the receipt's place"
    assert not pdfs(tmp_path, "Invoices", RECEIPTED) + pdfs(tmp_path, "Online", RECEIPTED)

    stalled.clear()
    assert run(tmp_path, attached, "--resume", include_invoices) == 0
    the_receipt_is_saved(tmp_path, RECEIPTED)
    assert SITE.opened(invoice) == 0
    assert SITE.opened("/pressed/print") == 1


def test_a_print_control_it_could_not_read_is_never_pressed(attached, stalled, tmp_path):
    """It was kept as though its words had passed the check, so it was
    pressed, and the gift receipt it printed was kept as the order's
    receipt. Now it is never pressed, and neither is the Print receipts
    after it, since the one that could not be read may be the one to press."""
    SITE.show(RECEIPTED)
    SITE.giftish = True
    stalled.add("giftish")
    assert run(tmp_path, attached, "--pilot-online") == 0

    assert SITE.opened("/tripwire/gift") == 0, "pressed a gift receipt control it never read"
    left_for_the_next_run(record(tmp_path, RECEIPTED))
    assert SITE.opened("/pressed/print") == 0, "pressed past a control it could not read"
    assert not pdfs(tmp_path, "Online", RECEIPTED)

    stalled.clear()
    assert run(tmp_path, attached, "--resume") == 0
    assert SITE.opened("/tripwire/gift") == 0, "a gift receipt control read in full is passed over"
    the_receipt_is_saved(tmp_path, RECEIPTED)
    assert "Gift receipt" not in text_of(pdfs(tmp_path, "Online", RECEIPTED)[0])


def test_an_invoice_control_it_could_not_read_is_never_pressed(attached, stalled, tmp_path):
    """Every invoice on the order's list is pressed, so a control there that
    could not be read was pressed as an invoice. Now the order is left for
    the next run, and nothing on the list is pressed."""
    SITE.show(INVOICED)
    SITE.returnish = True
    invoice = "/orders/%s/invoices/%s" % (INVOICED.number, INVOICED.invoice)
    stalled.add("returnish")
    assert run(tmp_path, attached, "--pilot-online") == 0

    assert SITE.opened("/tripwire/return") == 0, "pressed a control it never read"
    left_for_the_next_run(record(tmp_path, INVOICED))
    assert SITE.opened(invoice) == 0, "pressed past a control it could not read"
    assert not pdfs(tmp_path, "Invoices", INVOICED)

    stalled.clear()
    assert run(tmp_path, attached, "--resume") == 0
    assert SITE.opened("/tripwire/return") == 0
    rec = record(tmp_path, INVOICED)
    assert rec["downloaded_ok"] is True, rec
    saved = pdfs(tmp_path, "Invoices", INVOICED)
    assert len(saved) == 1 and INVOICED.invoice in text_of(saved[0]), saved


# -- each step on its own -------------------------------------------------------------------

@pytest.fixture()
def page():
    """A page of a browser of its own, started for each test and stopped
    after it, so it never shares the thread with the app's Playwright."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True, args=[NO_HOSTS])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield browser.new_page()
    browser.close()
    driver.stop()


def test_nothing_past_a_receipt_control_it_could_not_read_is_pressed(page, stalled):
    """The button may be the one to press. The link after it used to be
    pressed, since a kind of control was passed over at its first that did
    not answer."""
    page.set_content('<main><button data-guid="first" type="button">View your receipt</button>'
                     '<a href="#pressed">Receipts &amp; invoices</a></main>')
    stalled.add("first")
    assert site.open_receipt_section(page) is None
    assert "#pressed" not in page.url


def test_a_receipt_control_it_could_not_press_is_not_taken_for_none_either(page):
    """Something covers it, so the press never lands."""
    page.set_content('<main><a href="#pressed">Receipts &amp; invoices</a></main>'
                     '<div style="position:fixed;inset:0;background:#fff;z-index:9"></div>')
    page.set_default_timeout(1000)
    assert site.open_receipt_section(page) is None
    assert "#pressed" not in page.url


def guids(controls):
    return [c.get_attribute("data-guid") for c in controls]


def test_a_control_it_could_not_read_is_left_out_and_said(page, stalled):
    page.set_content("<main>%s<button data-guid=\"print\">Print receipts</button>"
                     "<button>Print gift receipt</button>%s"
                     '<a data-guid="invoice" href="#one">View invoice</a></main>'
                     % (GIFTISH, RETURNISH))
    stalled.update({"giftish", "returnish"})
    found = site.find_print_receipt_controls(page)
    assert guids(found) == ["print"], "the control that could not be read was kept"
    assert found.unread
    found = site.find_invoice_controls(page)
    assert guids(found) == ["invoice"], "the control that could not be read was kept"
    assert found.unread

    stalled.clear()
    found = site.find_print_receipt_controls(page)
    assert guids(found) == ["print"], "a gift receipt control read in full is passed over"
    assert not found.unread, "everything on the page was read"
    found = site.find_invoice_controls(page)
    assert guids(found) == ["invoice"], "a control that starts a return is passed over"
    assert not found.unread


def test_the_wait_for_a_receipt_reads_again_and_keeps_to_its_time(page, stalled):
    """A control that could not be read is not taken for receipt content,
    and it is read again on each look until the time is up. Each read that
    fails takes its second and a half, so counted in looks rather than by
    the clock, the wait would run four times as long."""
    page.set_content('<main><button data-guid="print">Print receipts</button></main>')
    stalled.add("print")
    started = time.monotonic()
    assert REAL_WAIT_FOR_RECEIPT(page, timeout_ms=3000) == "", \
        "a control it could not read was taken for the receipt"
    # About four seconds. Counted in looks it would be twelve and more.
    assert time.monotonic() - started < 8

    # The page answers again a moment into the next wait.
    threading.Timer(1.0, stalled.clear).start()
    assert REAL_WAIT_FOR_RECEIPT(page, timeout_ms=10000) == "print-controls", \
        "a control that answers on a later look is found"
