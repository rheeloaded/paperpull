"""Every invoice of an online order is saved, in a real browser.

An online order Target has no store receipt for is filed as its invoice.
Target splits an order into invoices, one for each shipment and one for a
delivery driver's tip, and lists them on a page of their own, one invoice
to a page. The app pressed the first control it found and nothing else,
so an order's other invoices were never saved, and the order was marked
done and never asked for again. In a real archive orders kept "Invoice 1
of 2" alone, and for one of them the first was the tip while the item
bought was on the second.

The way through Target's pages is the one real runs took, read from the
history of the app's own browser profile with every number masked. The
order's details page, its receipts page, "View detailed invoices" to the
list at /orders/<order>/invoices, then each invoice at its own address
below it, opened by pressing its control on the list. Some orders went
from the details page straight to their invoice, and that way is here
too.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP as it
does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Target. The pages carry
no word of Target's own, so the check a saved PDF passes sees only what
names the order, whichever version of that check is installed. Every
order number, invoice number, item and amount is invented.
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
from urllib.parse import quote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts as app_mod
import target_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import receipt_pdf, renaming, run_reporting, testkit
from paperpull_core.models import ONLINE, Item, Purchase

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"


class Order:
    """One made-up online order and the invoices Target split it into.

    `direct` is the way some real orders went, each invoice offered on
    the details page itself rather than on a list."""

    def __init__(self, number, iso, day, items, invoices, direct=False):
        self.number = number
        self.iso = iso            # the date the app files it under
        self.day = day            # as the invoice prints it
        self.placed = day.split(", ", 1)[1]   # as the list and details page print it
        self.items = items        # (name, price)
        self.invoices = invoices  # (invoice number, lines of its items, total)
        self.direct = direct

    @property
    def total(self):
        return "$%.2f" % sum(float(price[1:]) for _, price in self.items)


# An order in two shipments, an invoice for each.
SPLIT = Order("902000000000011", "2026-02-02", "Mon, Feb 2, 2026",
              [("Invented Garden Hose, 50 ft", "$12.34"),
               ("Invented Brass Hose Nozzle", "$5.67")],
              [("10000000000000011", ["10000011 - Invented Garden Hose, 50 ft"], "$12.34"),
               ("10000000000000012", ["10000012 - Invented Brass Hose Nozzle"], "$5.67")])

# An order with one invoice, which is named as it always was.
SINGLE = Order("902000000000021", "2026-02-03", "Tue, Feb 3, 2026",
               [("Invented Dish Soap, 24 oz", "$8.90")],
               [("10000000000000021", ["10000021 - Invented Dish Soap, 24 oz"], "$8.90")])

# Two invoices offered on the details page, with no list between.
DIRECT = Order("902000000000031", "2026-02-04", "Wed, Feb 4, 2026",
               [("Invented Phone Case, Clear", "$10.11"),
                ("Invented Screen Protector 2-Pack", "$12.13")],
               [("10000000000000031", ["10000031 - Invented Phone Case, Clear"], "$10.11"),
                ("10000000000000032", ["10000032 - Invented Screen Protector 2-Pack"], "$12.13")],
               direct=True)

# The shape that showed the bug. The first invoice is the driver's tip and
# names nothing of the order, and the item is on the second.
TIPPED = Order("902000000000041", "2026-02-05", "Thu, Feb 5, 2026",
               [("Invented Wooden Puzzle Box", "$34.56")],
               [("10000000000000042", ["10000042 - shipt_tip"], "$4.32"),
                ("10000000000000041", ["10000041 - Invented Wooden Puzzle Box"], "$34.56")])

# An item the category rules know nothing of, so the name the order is filed
# under is a guess, and the order is written down as needing review.
UNSURE = Order("902000000000051", "2026-02-09", "Mon, Feb 9, 2026",
               [("Invented Frobnicator", "$4.71")],
               [("10000000000000051", ["10000051 - Invented Frobnicator"], "$4.71")])

# An order whose every invoice is put aside. The tip names nothing of the
# order, and the item's invoice words the item as a till does, not as the
# order's page does, so neither passes the check.
ASIDE = Order("902000000000061", "2026-02-10", "Tue, Feb 10, 2026",
              [("Invented Ceramic Planter, Large", "$21.43")],
              [("10000000000000062", ["10000062 - shipt_tip"], "$3.21"),
               ("10000000000000061", ["10000061 - INV CERAMIC PLNTR LG"], "$21.43")])

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Orders : %s</title></head>
<body><header><p>Ship to 00000</p><a href="/">Home</a></header>
<main>%s</main><footer><p>Help</p><p>Returns</p></footer></body></html>"""

# Controls the app must never press. Each leads somewhere the server
# remembers, and every test ends by asking whether anything went there.
TRIPWIRES = ('<a href="/tripwire/return">Start a return</a>'
             '<a href="/tripwire/again">Buy it again</a>'
             '<a href="/tripwire/gift">Print gift receipt</a>')

SIGN_IN = """<!doctype html><html><head><title>Sign in</title></head><body>
<h1>Sign in</h1><form><label>Password <input type="password"></label>
<button type="button">Sign in</button></form></body></html>"""

BROKEN = PAGE % ("Invoice Details", "<h1>Something went wrong</h1>"
                 "<p>This invoice could not be shown.</p>")

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
    rows = "".join('<div data-test="package-card-item-row"><div>%s</div><div>%s</div>'
                   "<div>Qty 1</div></div>" % item for item in o.items)
    if o.direct:
        way = "".join('<p><a href="/orders/%s/invoices/%s">View invoice</a></p>'
                      % (o.number, inv) for inv, _, _ in o.invoices)
    else:
        way = '<p><a href="/orders/%s/receipts">Receipts &amp; invoices</a></p>' % o.number
    return PAGE % ("Order details", "<h1>Order #%s</h1><p>Placed %s</p><p>Delivered</p>"
                   "%s<p>Total %s</p>%s%s" % (o.number, o.placed, rows, o.total, way,
                                                 TRIPWIRES))


def receipts_page(o):
    return PAGE % ("Receipts", "<h1>Receipts and invoices</h1>"
                   '<p><a href="/orders/%s/invoices">View detailed invoices</a></p>%s'
                   % (o.number, TRIPWIRES))


def invoice_list(o):
    n = len(o.invoices)
    entries = "".join(
        "<section><h2>Invoice %d of %d</h2><p>Invoice date: %s</p>"
        '<a href="/orders/%s/invoices/%s">View invoice</a></section>'
        % (i, n, o.day, o.number, inv) for i, (inv, _, _) in enumerate(o.invoices, 1))
    return PAGE % ("Invoices", "<h1>Invoices</h1>%s%s" % (entries, TRIPWIRES))


def invoice_page(o, inv):
    n = len(o.invoices)
    i, (number, lines, total) = next((i, v) for i, v in enumerate(o.invoices, 1)
                                     if v[0] == inv)
    items = "".join("<div>%s</div><div>Qty. 1</div>" % line for line in lines)
    return PAGE % ("Invoice Details",
                   "<h1>Invoice %d of %d</h1><p>Invoice date: %s</p>"
                   "<p>Invoice number: %s</p><div>Item</div>%s<div>Item total %s</div>"
                   "<div>Invoice total %s</div><div>Credit card ending 0000</div>"
                   % (i, n, o.day, number, items, total, total))


class FakeTarget:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = {}
        self.seen = []
        self.signed_in = True
        self.lapse_at = set()    # paths whose opening ends the session
        self.broken = set()      # paths that answer an error page
        self.moved = {}          # paths sent on to another path

    def show(self, *orders):
        self.orders = {o.number: o for o in orders}


SITE = FakeTarget()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _to_sign_in(self):
        self.send_response(302)
        self.send_header("Location", "/login?back=" + quote(self.path, safe=""))
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        # The fixture's own page, answered signed in or not, and never
        # counted as anything the app opened.
        if path.startswith("/beacon/"):
            DRAWN_TABS.add(path[len("/beacon/"):])
            return self._answer("ok")
        if path.startswith("/drawn/"):
            return self._answer(DRAWN % {"tab": path[len("/drawn/"):]})
        SITE.seen.append(path)
        if path == "/login":
            return self._answer(SIGN_IN)
        if path == "/" or path.startswith("/tripwire/"):
            return self._answer(PAGE % ("Home", "<h1>Nothing here</h1>"))
        if path in SITE.lapse_at:
            SITE.lapse_at.discard(path)
            SITE.signed_in = False
        if not SITE.signed_in:
            return self._to_sign_in()
        if path in SITE.broken:
            return self._answer(BROKEN, status=500)
        if path in SITE.moved:
            self.send_response(302)
            self.send_header("Location", SITE.moved[path])
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
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
        if (o is not None and len(parts) == 4 and parts[2] == "invoices"
                and parts[3] in [inv for inv, _, _ in o.invoices]):
            return self._answer(invoice_page(o, parts[3]))
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


def _start_browser(exe, profile):
    """The browser as a program of its own with a debugging port, and its
    address, or None for the address when it opened no port.

    It starts with no window of its own, so its only tabs are the ones
    opened here. The app used to work in the blank tab a browser starts
    with, and a fresh browser sometimes never listed that tab at all, or
    never closed it."""
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
    with browser_launcher.open_local(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def _addresses(cdp_url):
    return [t.get("url") for t in _page_targets(cdp_url)]


def _close_tab(cdp_url, target_id):
    browser_launcher.open_local(cdp_url + "/json/close/" + target_id, timeout=10).read()


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
    that page has drawn, as its id and address, or None.

    The first tab a fresh browser opens sometimes never sends a single
    request, for a minute and more, and a second tab always drew. So a tab
    that has not drawn in 10 seconds is closed, and another opened once it
    is gone, three at most."""
    for _attempt in range(3):
        name = "tab%d" % next(_TAB_NAMES)
        address = "%s/drawn/%s" % (server, name)
        request = urllib.request.Request(cdp_url + "/json/new?" + address, method="PUT")
        with browser_launcher.open_local(request, timeout=10) as r:
            tab = json.loads(r.read().decode("utf-8"))
        if _drawn(name, 10):
            return {"id": tab["id"], "address": address}
        _close_tab(cdp_url, tab["id"])
        _gone(cdp_url, tab["id"])
    return None


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.

    It is handed over with one tab, on a page of this server's that has
    drawn, and the app works in that tab, as it works in the person's own
    at home. A browser that cannot get there is closed and another started,
    three at most, and a failure says what each one did."""
    tried = []
    for _start in range(3):
        proc, url = _start_browser(browser_exe, tmp_path_factory.mktemp("attached-profile"))
        if url is None:
            proc.kill()
            proc.wait(timeout=15)
            pytest.skip("the browser opened no debugging port")
        ready = _open_drawn(url, server)
        if ready is not None and _only_tab_left(url, ready["id"], 10):
            break
        tried.append("%s, tabs %r" % ("no tab drew its page" if ready is None else
                                      "a tab never closed", _addresses(url)))
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
    """Every address the app opens points at the made-up site, the two
    waits that only ever run out on these pages are short, and nothing
    the app must never press is pressed."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    # Neither page here has a store receipt or a print frame, so these two
    # always wait out their whole time, fifteen seconds and three.
    real_content = site.wait_for_receipt_content
    monkeypatch.setattr(site, "wait_for_receipt_content",
                        lambda page, timeout_ms=15000: real_content(page, timeout_ms=1000))
    real_frame = site.find_printing_frame
    monkeypatch.setattr(site, "find_printing_frame",
                        lambda page, wait_ms=6000: real_frame(page, wait_ms=min(wait_ms, 500)))
    # A page from this machine has finished drawing by the time the network
    # is quiet. Absent before the fix, and the old code runs these too.
    monkeypatch.setattr(site, "INVOICE_SETTLE_MS", 200, raising=False)
    yield SITE
    pressed = [p for p in SITE.seen if p.startswith("/tripwire/")]
    assert not pressed, "pressed a control it must never press, %s" % pressed


def config_for(tmp_path, cdp_url, **settings):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "include_invoices": True, "delay_min_seconds": 0, "delay_max_seconds": 0,
        **settings}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, *command):
    return app_mod.main([*command, "--config", str(config_for(tmp_path, cdp_url))])


def record(tmp_path, order):
    progress = json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))
    return progress["Online:" + order.number]


def pdfs(tmp_path, folder, order):
    """The PDFs in one of the app's folders for this order's day, by name."""
    where = tmp_path / "out" / folder
    return sorted(p for p in where.glob("*.pdf") if p.name.startswith(order.iso + " ")) \
        if where.exists() else []


def text_of(path):
    return " ".join(receipt_pdf.pdf_text(Path(path)).split())


def same_file(recorded, path):
    """The record names this file, however the path to it is spelled."""
    return bool(recorded) and Path(recorded).resolve() == Path(path).resolve()


def invoice_numbers(paths):
    return sorted(n for p in paths for n, _, _ in ALL_INVOICES if n in text_of(p))


ALL_INVOICES = [v for o in (SPLIT, SINGLE, DIRECT, TIPPED, UNSURE, ASIDE) for v in o.invoices]


def opened(path):
    return SITE.seen.count(path)


def new_this_run(tmp_path):
    lines = (tmp_path / "out" / "new-this-run.txt").read_text(encoding="utf-8").splitlines()
    return sorted(Path(ln).name for ln in lines if ln and not ln.startswith("#"))


INDEX, HISTORY = "Target Receipt Index.csv", "Target Order History.csv"


def rows_of(tmp_path, name, order):
    """This order's rows in one of the app's two CSVs, in the order written."""
    columns = storage.RECEIPT_INDEX_COLUMNS if name == INDEX else storage.ORDER_HISTORY_COLUMNS
    return [r for r in storage.CsvFile(tmp_path / "out" / name, columns).read_all()
            if r["Order or Receipt Number"] == order.number]


def counted(tmp_path):
    """What the run summary counted, by the label it gives each count."""
    text = (tmp_path / "out" / "run-summary.txt").read_text(encoding="utf-8")
    return {k.strip(): v.strip() for k, v in
            (ln.split(":", 1) for ln in text.splitlines() if ":" in ln)}


def test_every_invoice_of_every_order_is_saved(attached, tmp_path):
    """An order in two shipments, one with a single invoice, which keeps
    the name it always had, and one whose invoices are offered on its
    details page. Every invoice is saved once, each opened once, and each
    is in the list of files the run downloaded."""
    SITE.show(SPLIT, SINGLE, DIRECT)
    assert run(tmp_path, attached, "--pilot-online") == 0

    split = pdfs(tmp_path, "Invoices", SPLIT)
    assert [p.name.endswith(" Invoice (%d of 2).pdf" % i) for i, p in enumerate(split, 1)] \
        == [True, True], split
    assert "Invoice 1 of 2" in text_of(split[0]) and "Garden Hose" in text_of(split[0])
    assert "Invoice 2 of 2" in text_of(split[1]) and "Brass Hose Nozzle" in text_of(split[1])
    rec = record(tmp_path, SPLIT)
    assert rec["downloaded_ok"] is True, rec
    assert rec["receipt_count"] == 2, rec
    assert same_file(rec["pdf_path"], split[0]), rec
    assert split[1].name in rec["notes"], "the second is named in the record, %s" % rec["notes"]
    for inv, _, _ in SPLIT.invoices:
        assert opened("/orders/%s/invoices/%s" % (SPLIT.number, inv)) == 1, SITE.seen

    single = pdfs(tmp_path, "Invoices", SINGLE)
    assert len(single) == 1 and single[0].name.endswith(" Invoice.pdf"), single
    assert record(tmp_path, SINGLE)["downloaded_ok"] is True

    direct = pdfs(tmp_path, "Invoices", DIRECT)
    assert [p.name.endswith(" Invoice (%d of 2).pdf" % i) for i, p in enumerate(direct, 1)] \
        == [True, True], direct
    assert "Phone Case" in text_of(direct[0]) and "Screen Protector" in text_of(direct[1])
    assert record(tmp_path, DIRECT)["downloaded_ok"] is True

    assert new_this_run(tmp_path) == sorted(p.name for p in split + single + direct)
    assert not pdfs(tmp_path, "Manual Review", SPLIT) + pdfs(tmp_path, "Manual Review", DIRECT)


def test_the_invoice_naming_the_item_is_kept_and_a_tip_is_put_aside(attached, tmp_path):
    """The tip names nothing of the order, so it is put aside for a person
    to look at rather than filed as the order's invoice, and never thrown
    away. The item's invoice is kept, and it is the one the order's record
    points at."""
    SITE.show(TIPPED)
    assert run(tmp_path, attached, "--pilot-online") == 0

    kept = pdfs(tmp_path, "Invoices", TIPPED)
    assert len(kept) == 1 and kept[0].name.endswith(" Invoice (2 of 2).pdf"), kept
    assert "Wooden Puzzle Box" in text_of(kept[0])
    aside = pdfs(tmp_path, "Manual Review", TIPPED)
    assert len(aside) == 1 and "shipt_tip" in text_of(aside[0]), aside
    rec = record(tmp_path, TIPPED)
    assert rec["downloaded_ok"] is True, rec
    assert same_file(rec["pdf_path"], kept[0]), rec
    assert aside[0].name in rec["notes"], rec["notes"]


def test_an_invoice_that_did_not_open_is_asked_for_on_the_next_run(attached, tmp_path):
    """The order is not marked done while one of its invoices is missing,
    and the next run saves that one without saving the first again."""
    SITE.show(SPLIT)
    second = "/orders/%s/invoices/%s" % (SPLIT.number, SPLIT.invoices[1][0])
    SITE.broken.add(second)
    assert run(tmp_path, attached, "--pilot-online") == 0

    rec = record(tmp_path, SPLIT)
    assert not rec.get("downloaded_ok"), rec
    assert rec["state"] not in ("No Receipt Available", "Completed", "PDF Verified"), rec
    assert invoice_numbers(pdfs(tmp_path, "Invoices", SPLIT)) == [SPLIT.invoices[0][0]]
    assert not pdfs(tmp_path, "Manual Review", SPLIT), "an error page is not an invoice"

    SITE.broken.clear()
    assert run(tmp_path, attached, "--resume") == 0
    saved = pdfs(tmp_path, "Invoices", SPLIT)
    assert invoice_numbers(saved) == sorted(inv for inv, _, _ in SPLIT.invoices), saved
    assert len(saved) == 2, "the first invoice is on file once, %s" % saved
    assert record(tmp_path, SPLIT)["downloaded_ok"] is True


def test_another_orders_invoice_page_is_never_printed_for_this_order(attached, tmp_path):
    """A press of this order's second invoice landed on another order's
    invoice page. Its address names that order, so it is turned away before
    it is printed, nothing of it is filed under this order, in Invoices or
    in Manual Review, and this order is asked for again on the next run.
    The invoice pages are reached by presses from the order's own page,
    which was checked, and nothing looked at them before (page_check)."""
    SITE.show(SPLIT, SINGLE)
    second = "/orders/%s/invoices/%s" % (SPLIT.number, SPLIT.invoices[1][0])
    SITE.moved[second] = "/orders/%s/invoices/%s" % (SINGLE.number, SINGLE.invoices[0][0])
    assert run(tmp_path, attached, "--pilot-online") == 0

    assert opened(second) == 1, SITE.seen
    filed = pdfs(tmp_path, "Invoices", SPLIT) + pdfs(tmp_path, "Manual Review", SPLIT)
    assert invoice_numbers(filed) == [SPLIT.invoices[0][0]], filed
    rec = record(tmp_path, SPLIT)
    assert not rec.get("downloaded_ok"), rec


def test_signed_out_between_two_invoices_the_run_stops_and_resumes(attached, tmp_path,
                                                                    monkeypatch):
    """Under the panel there is nobody to ask, so the run stops. The
    invoice already saved stays saved and on the record, the order is not
    marked done, and Resume takes it up without saving the first again."""
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: None)
    SITE.show(SPLIT)
    SITE.lapse_at.add("/orders/%s/invoices/%s" % (SPLIT.number, SPLIT.invoices[1][0]))
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, attached, "--pilot-online")
    assert stopped.value.code == 0

    rec = record(tmp_path, SPLIT)
    assert not rec.get("downloaded_ok"), rec
    first = pdfs(tmp_path, "Invoices", SPLIT)
    assert invoice_numbers(first) == [SPLIT.invoices[0][0]], first
    assert not list((tmp_path / "out" / "Invoices").glob("*.delivering")), \
        "nothing half made is left behind"

    SITE.signed_in = True
    assert run(tmp_path, attached, "--resume") == 0
    saved = pdfs(tmp_path, "Invoices", SPLIT)
    assert invoice_numbers(saved) == sorted(inv for inv, _, _ in SPLIT.invoices), saved
    assert len(saved) == 2, saved
    assert record(tmp_path, SPLIT)["downloaded_ok"] is True


def test_an_invoice_order_is_written_down_once_as_it_ends(attached, tmp_path, monkeypatch,
                                                           capsys):
    """The invoice step wrote each order into both CSVs as Review Needed and
    counted it, then process_one wrote it again as Completed and counted it
    again, as it does a receipt. In the owner's archive 22 of 23 invoice
    orders had two index rows for their one file and every item of them
    twice in the order history, every one was counted as needing review, and
    review_names offered every one for renaming. Now each is written once,
    the way it ends, and counted once. The order whose name is a guess is
    the only one needing review, and the tip put aside is still reported,
    as a file that did not pass its check."""
    SITE.show(SINGLE, SPLIT, TIPPED, UNSURE)
    assert run(tmp_path, attached, "--pilot-online") == 0
    said = capsys.readouterr().out

    for order, status, state in ((SINGLE, "Completed", "Completed"),
                                 (SPLIT, "Completed", "Completed"),
                                 (TIPPED, "Completed", "Completed"),
                                 (UNSURE, "Review Needed", "Needs Manual Review")):
        rec = record(tmp_path, order)
        assert rec["state"] == state, rec
        index = rows_of(tmp_path, INDEX, order)
        assert [(r["Receipt Status"], r["Processing Status"], r["Document Type"])
                for r in index] == [("Downloaded", status, "Invoice")], (order.number, index)
        assert same_file(index[0]["PDF Full Path"], rec["pdf_path"]), index
        history = rows_of(tmp_path, HISTORY, order)
        assert sorted(r["Item Name"] for r in history) == sorted(n for n, _ in order.items), \
            (order.number, history)
        assert {r["Processing Status"] for r in history} == {status}, history
    assert "Also saved" in rows_of(tmp_path, INDEX, SPLIT)[0]["Notes"], \
        "the order's other invoice is named on its one row"

    counts = counted(tmp_path)
    assert counts["Invoices downloaded"] == "4", counts
    assert counts["Needs manual review"] == "1", "only the order whose name is a guess, %s" % counts
    assert counts["PDF validation failures"] == "1", "the tip put aside, %s" % counts
    # What the panel is told, which it shows as "1 need review".
    line = next(ln for ln in said.splitlines() if ln.startswith(run_reporting.PREFIX))
    result = json.loads(line[len(run_reporting.PREFIX):])
    assert (result["manual_review"], result["validation_failures"]) == (1, 1), result

    asked = []
    monkeypatch.setattr(app_mod, "ask", lambda prompt: asked.append(prompt) or "")
    assert run(tmp_path, attached, "--review-names") == 0
    assert len(asked) == 1, "only the name it was unsure of is offered for renaming, %s" % asked


def print_to(cdp_url, url, out):
    """A page printed the way the app prints one, in a Playwright of the
    test's own that is stopped before the app starts its own."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.connect_over_cdp(cdp_url).contexts[0].new_page()
        page.goto(url)
        receipt_pdf.print_page_to_pdf(page, out)
        page.close()


def test_a_redownload_saves_the_missing_invoice_and_not_the_first_again(
        attached, server, tmp_path):
    """An order as the old code left it, done, with its first invoice
    filed as the order's invoice. Fetching it again with --order-number
    and --redownload saves the invoice that was missing and leaves the one
    on file alone rather than saving it a second time."""
    SITE.show(TIPPED)
    out = tmp_path / "out"
    (out / "Invoices").mkdir(parents=True)
    old = out / "Invoices" / ("%s Target Games Invoice.pdf" % TIPPED.iso)
    tip = TIPPED.invoices[0][0]
    print_to(attached, "%s/orders/%s/invoices/%s" % (server, TIPPED.number, tip), old)
    before = old.read_bytes()
    done = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso,
                    order_number=TIPPED.number, total=TIPPED.total, status="Delivered",
                    details_url="%s/orders/%s" % (server, TIPPED.number),
                    items=[Item(name=TIPPED.items[0][0])], summary="Games",
                    document_type="Invoice", pdf_path=str(old), pdf_filename=old.name,
                    state="Completed", notes="Invoice saved; no printable receipt exists")
    (out / "progress.json").write_text(json.dumps({done.key: dict(
        done.to_dict(), downloaded_ok=True)}), encoding="utf-8")
    (out / "discovery.json").write_text(json.dumps({done.key: done.to_dict()}),
                                        encoding="utf-8")
    # The receipt index as the old code wrote it, twice over for one order.
    index = storage.CsvFile(out / "Target Receipt Index.csv", storage.RECEIPT_INDEX_COLUMNS)
    index.append_rows([{
        "Purchase Date": done.purchase_date, "Purchase Type": done.purchase_type,
        "Order or Receipt Number": done.order_number, "PDF Filename": old.name,
        "PDF Full Path": str(old), "Document Type": "Invoice", "Receipt Status": status,
        "Processing Status": processing} for status, processing in (
            ("No printable receipt available", "Review Needed"), ("Downloaded", "Completed"))])

    assert run(tmp_path, attached, "--online", "--order-number", TIPPED.number,
               "--redownload") == 0

    assert old.read_bytes() == before, "the invoice on file is left as it was"
    everywhere = [p for folder in ("Invoices", "Manual Review")
                  for p in pdfs(tmp_path, folder, TIPPED)]
    assert sorted(invoice_numbers(everywhere)) == sorted(inv for inv, _, _ in TIPPED.invoices), \
        everywhere
    assert len(everywhere) == 2, "the tip's invoice is not saved a second time, %s" % everywhere
    item = [p for p in everywhere if "Wooden Puzzle Box" in text_of(p)]
    assert item and item[0].name.endswith(" Invoice (2 of 2).pdf"), item
    rec = record(tmp_path, TIPPED)
    assert rec["downloaded_ok"] is True, rec
    assert same_file(rec["pdf_path"], item[0]), rec
    # The two rows the old code left are left as they were, and this run
    # adds one, for the invoice the record now points at.
    index = rows_of(tmp_path, INDEX, TIPPED)
    assert [(r["Receipt Status"], r["Processing Status"]) for r in index] == [
        ("No printable receipt available", "Review Needed"), ("Downloaded", "Completed"),
        ("Downloaded", "Completed")], index
    assert same_file(index[-1]["PDF Full Path"], item[0]), index


def test_a_deleted_copy_of_an_invoice_put_aside_is_fetched_again_once(attached, tmp_path):
    """Every invoice of the order was put aside, so it waits for a person,
    and its copies are left alone while they are there. Deleting the copy
    its record names asks for the order again, as it does a receipt put
    aside. The next run walked the order's invoices on Target and saved
    nothing, since it counted the deleted copy as on file. It wrote the
    order down as needing review again, naming the deleted file, so every
    run after walked the order again and added an index row. Now the
    deleted invoice is fetched once and checked again, the other is not
    saved a second time, and later runs leave the order alone."""
    SITE.show(ASIDE)
    pages = ["/orders/%s/invoices/%s" % (ASIDE.number, inv) for inv, _, _ in ASIDE.invoices]
    assert run(tmp_path, attached, "--pilot-online") == 0
    aside = pdfs(tmp_path, "Manual Review", ASIDE)
    assert invoice_numbers(aside) == sorted(inv for inv, _, _ in ASIDE.invoices), aside
    assert len(aside) == 2 and not pdfs(tmp_path, "Invoices", ASIDE), aside
    rec = record(tmp_path, ASIDE)
    assert rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok"), rec
    assert len(rows_of(tmp_path, INDEX, ASIDE)) == 1

    assert run(tmp_path, attached, "--resume") == 0
    assert [opened(p) for p in pages] == [1, 1], "left alone while its copies are there"
    assert len(rows_of(tmp_path, INDEX, ASIDE)) == 1

    named = Path(rec["pdf_path"])
    deleted = invoice_numbers([named])
    named.unlink()
    assert run(tmp_path, attached, "--resume") == 0
    aside = pdfs(tmp_path, "Manual Review", ASIDE)
    assert invoice_numbers(aside) == sorted(inv for inv, _, _ in ASIDE.invoices), \
        "the deleted invoice %s is fetched again, %s" % (deleted, aside)
    assert len(aside) == 2, "the other is not saved a second time, %s" % aside
    rec = record(tmp_path, ASIDE)
    assert rec["state"] == "Needs Manual Review" and Path(rec["pdf_path"]).exists(), rec
    assert len(rows_of(tmp_path, INDEX, ASIDE)) == 2

    walked = [opened(p) for p in pages]
    assert run(tmp_path, attached, "--resume") == 0
    assert [opened(p) for p in pages] == walked, "left alone again, %s" % SITE.seen
    assert len(rows_of(tmp_path, INDEX, ASIDE)) == 2


def test_an_invoice_renamed_by_review_names_is_not_saved_again_by_download_again(
        attached, tmp_path, monkeypatch):
    """Review Names gives the file the order's record names a new name, and
    the record's list of the order's invoices kept the old one. Download
    again (--redownload) fetches each invoice whose file is gone, so it took
    the renamed invoice for missing and saved it a second time, though the
    panel says Target leaves an invoice still on file as it is."""
    SITE.show(UNSURE)
    assert run(tmp_path, attached, "--pilot-online") == 0
    monkeypatch.setattr(app_mod, "ask", lambda prompt: "Frobnicators")
    assert run(tmp_path, attached, "--review-names") == 0
    renamed = pdfs(tmp_path, "Invoices", UNSURE)
    assert len(renamed) == 1 and "Frobnicators" in renamed[0].name, renamed
    before = renamed[0].read_bytes()

    assert run(tmp_path, attached, "--online", "--order-number", UNSURE.number,
               "--redownload") == 0
    assert pdfs(tmp_path, "Invoices", UNSURE) == renamed, "not saved a second time"
    assert renamed[0].read_bytes() == before
    assert not pdfs(tmp_path, "Manual Review", UNSURE)
    rec = record(tmp_path, UNSURE)
    assert rec["downloaded_ok"] is True and same_file(rec["pdf_path"], renamed[0]), rec
    assert [same_file(e["file"], renamed[0]) for e in rec["invoices"]] == [True], rec


# -- the rules, each on its own -------------------------------------------------

def test_an_invoice_page_says_which_of_the_order_it_is():
    page = ("Invoice 2 of 2 Invoice date: Thu, Feb 5, 2026 Invoice number: 10000000000000041 "
            "Item 10000041 - Invented Wooden Puzzle Box Invoice total $34.56")
    assert site.invoice_identity(page) == ((2, 2), "10000000000000041")
    listing = "Invoices Invoice 1 of 2 View invoice Invoice 2 of 2 View invoice"
    assert site.invoice_identity(listing) == (None, ""), "a list is not one of them"
    assert site.invoice_identity("Something went wrong") == (None, "")


def an_app(tmp_path, *args, **settings):
    return app_mod.App(app_mod.build_parser().parse_args(
        ["--config", str(config_for(tmp_path, "http://127.0.0.1:9", **settings)), *args]))


def tipped_purchase():
    return Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso,
                    order_number=TIPPED.number, total=TIPPED.total, status="Delivered",
                    items=[Item(name=TIPPED.items[0][0])], summary="Games")


def test_the_record_points_at_the_invoice_naming_the_items_when_a_tip_passes(tmp_path):
    """A real tip invoice carries Target's own name, which the check on a
    saved PDF took as enough until it learned otherwise, so a tip can be
    kept too. The order's record still points at the invoice naming the
    item, not at the tip that came first."""
    app = an_app(tmp_path)
    purchase = tipped_purchase()
    tip, item = (app.paths.invoices / "tip.pdf"), (app.paths.invoices / "item.pdf")
    walk = {"tokens": [], "held": [], "missed": [], "count": 2, "list_page": None, "saved": [
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000042", "kept": True,
         "names": False, "size": 4000, "pages": 1},
        {"file": str(item), "part": "2 of 2", "number": "10000000000000041", "kept": True,
         "names": True, "size": 5000, "pages": 1}]}
    assert app._file_invoices(purchase, walk) is True
    rec = app.progress.get(purchase.key)
    assert rec["pdf_path"] == str(item) and rec["pdf_size"] == 5000, rec
    assert rec["downloaded_ok"] is True and rec["receipt_count"] == 2, rec
    assert "Also saved tip.pdf" in rec["notes"], rec["notes"]
    # Writing the order down and counting it is process_one's, once.
    assert app.index_csv.read_all() == [] and app.order_csv.read_all() == []
    assert (app.stats["invoices_downloaded"], app.stats["manual_review"]) == (0, 0), app.stats


def test_an_invoice_saved_before_counts_after_its_file_is_deleted(tmp_path):
    """The promise every download here makes. Files are deleted once they
    are imported elsewhere, and a deleted one is not fetched again, unless
    --redownload asks for missing files again."""
    app = an_app(tmp_path)
    purchase = tipped_purchase()
    gone = app.paths.invoices / "imported and deleted.pdf"
    app.progress.update(purchase.key, {"invoices": [
        {"file": str(gone), "part": "2 of 2", "number": "10000000000000041", "kept": True,
         "names": True}]})
    assert [e["number"] for e in app._invoices_on_file(purchase)] == ["10000000000000041"]
    assert an_app(tmp_path, "--redownload")._invoices_on_file(purchase) == []


def invoice_pdf(path, part, number, line):
    """A saved invoice reading the way Target prints one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(testkit.text_pdf(["Invoice %s" % part, "Invoice number: %s" % number,
                                       line, "Invoice total $4.32"]))
    return path


def test_an_invoice_put_aside_counts_only_while_its_copy_is_there_and_opens(tmp_path):
    """An order whose every invoice was put aside is tried again once the
    copy its record names is deleted, or no longer passes the check
    _already_done gives a copy put aside. The walk then counted that
    invoice as on file all the same, so it saved nothing and wrote the
    order down as needing review again, naming the same copy, and the next
    run did the same. Such an invoice is not on file, so it is fetched
    again, with or without --redownload."""
    app = an_app(tmp_path)
    purchase = tipped_purchase()
    tip = invoice_pdf(app.paths.manual_review / "tip (1 of 1).pdf", "1 of 1",
                      "10000000000000042", "10000042 - shipt_tip")
    entry = {"file": str(tip), "part": "1 of 1", "number": "10000000000000042",
             "kept": False, "names": False, "size": tip.stat().st_size, "pages": 1}
    walk = {"tokens": [], "held": [], "missed": [], "count": 1, "list_page": None,
            "saved": [dict(entry)]}
    assert app._file_invoices(purchase, walk) is False
    rec = app.progress.get(purchase.key)
    assert rec["state"] == "Needs Manual Review" and same_file(rec["pdf_path"], tip), rec
    assert app._already_done(purchase), "left alone while its copy is there"
    assert app._invoices_on_file(purchase) == [entry]
    assert an_app(tmp_path, "--redownload")._invoices_on_file(purchase) == [entry]

    good = tip.read_bytes()
    tip.write_bytes(good[:400])
    assert not app._already_done(purchase), "a copy cut short is tried again"
    assert app._invoices_on_file(purchase) == [], "and its invoice fetched again"

    tip.unlink()
    assert not app._already_done(purchase), "a copy deleted is tried again"
    assert app._invoices_on_file(purchase) == [], "and its invoice fetched again"
    assert an_app(tmp_path, "--redownload")._invoices_on_file(purchase) == []


def test_an_invoice_renamed_since_is_on_file_under_its_new_name(tmp_path):
    """Review Names and Rename give the file an index row names a new name
    and correct the row, and the record's list of invoices kept the old
    name. The entry is known by what the renamed file says, as an invoice
    saved before the walk is, so --redownload does not save it a second
    time. One whose file is gone is still missing, and a file that is not
    that invoice is never taken for it."""
    app = an_app(tmp_path, "--redownload")
    purchase = tipped_purchase()
    renamed = invoice_pdf(app.paths.invoices / "renamed (2 of 2).pdf", "2 of 2",
                          "10000000000000041", "10000041 - Invented Wooden Puzzle Box")
    tip = app.paths.invoices / "imported and deleted (1 of 2).pdf"
    old = app.paths.invoices / "old name (2 of 2).pdf"
    app.progress.update(purchase.key, {"pdf_path": "", "invoices": [
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000042", "kept": True,
         "names": False},
        {"file": str(old), "part": "2 of 2", "number": "10000000000000041", "kept": True,
         "names": True}]})
    app.index_csv.append_rows([{
        "Purchase Date": purchase.purchase_date, "Purchase Type": purchase.purchase_type,
        "Order or Receipt Number": purchase.order_number, "PDF Filename": renamed.name,
        "PDF Full Path": str(renamed), "Document Type": "Invoice",
        "Receipt Status": "Downloaded", "Processing Status": "Completed"}])
    on_file = app._invoices_on_file(purchase)
    assert [(e["number"], e["file"]) for e in on_file] == [
        ("10000000000000041", str(renamed))], on_file
    # Without --redownload every invoice saved counts, under the name it has.
    assert [e["file"] for e in an_app(tmp_path)._invoices_on_file(purchase)] == [
        str(tip), str(renamed)]

    # An entry whose file is there keeps it, though a row names another copy.
    invoice_pdf(old, "2 of 2", "10000000000000041", "10000041 - Invented Wooden Puzzle Box")
    assert [e["file"] for e in app._invoices_on_file(purchase)] == [str(old)]
    old.unlink()

    # The row's file is another invoice, so the renamed one is missing.
    invoice_pdf(renamed, "1 of 1", "10000000000000099", "10000099 - Invented Other Thing")
    assert app._invoices_on_file(purchase) == []

    # Nor is a kept invoice taken for a copy of it put aside, since a
    # rename never moves a file to another folder.
    aside = invoice_pdf(app.paths.manual_review / "put aside (2 of 2).pdf", "2 of 2",
                        "10000000000000041", "10000041 - Invented Wooden Puzzle Box")
    app.index_csv.append_rows([{
        "Purchase Date": purchase.purchase_date, "Purchase Type": purchase.purchase_type,
        "Order or Receipt Number": purchase.order_number, "PDF Filename": aside.name,
        "PDF Full Path": str(aside), "Document Type": "Invoice",
        "Receipt Status": "Validation Failed", "Processing Status": "Needs Manual Review"}])
    assert app._invoices_on_file(purchase) == []


def test_an_invoice_put_aside_and_renamed_by_rename_is_on_file_under_its_new_name(tmp_path):
    """Rename, after a new naming pattern, renames the copy an order whose
    every invoice was put aside names in its index row, as it renames any
    file, and corrects the row. That copy's entry is followed to its new
    name, so Download again counts the invoice rather than fetching it
    again, and the other copy, which Rename leaves alone, counts as it
    is."""
    app = an_app(tmp_path, max_path_length=1000)
    purchase = tipped_purchase()
    purchase.document_type = "Invoice"      # as _save_invoices marks it
    folder = app.paths.manual_review
    tip = invoice_pdf(folder / ("%s Target Games Invoice (1 of 2).pdf" % TIPPED.iso), "1 of 2",
                      "10000000000000042", "10000042 - shipt_tip")
    item = invoice_pdf(folder / ("%s Target Games Invoice (2 of 2).pdf" % TIPPED.iso),
                       "2 of 2", "10000000000000041", "10000041 - WOODEN PZL BX")
    walk = {"tokens": [], "held": [], "missed": [], "count": 2, "list_page": None, "saved": [
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000042", "kept": False,
         "names": False, "size": tip.stat().st_size, "pages": 1},
        {"file": str(item), "part": "2 of 2", "number": "10000000000000041", "kept": False,
         "names": False, "size": item.stat().st_size, "pages": 1}]}
    assert app._file_invoices(purchase, walk) is False

    pattern = "{date:yyyy-mm-dd} {summary}[ {kind}][ ({part})]"
    renamer = an_app(tmp_path, max_path_length=1000, filename_pattern=pattern)
    assert renaming.run_for(renamer, apply_changes=True, say=lambda *a: None).renamed == 1
    renamed = folder / ("%s Games Invoice (1 of 2).pdf" % TIPPED.iso)
    assert sorted(p.name for p in folder.glob("*.pdf")) == sorted([renamed.name, item.name])

    again = an_app(tmp_path, "--redownload", max_path_length=1000)
    assert [(e["number"], e["file"]) for e in again._invoices_on_file(purchase)] == [
        ("10000000000000042", str(renamed)), ("10000000000000041", str(item))]


def test_an_invoice_control_that_does_something_else_is_never_pressed(attached):
    """Every invoice on the list is pressed now, not only the first, so each
    passes the guard the Print receipts controls pass."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.connect_over_cdp(attached).contexts[0].new_page()
        page.set_content('<main><a href="#one">View invoice</a>'
                         '<a href="#two">View invoice and start a return</a>'
                         '<button>Print invoice with gift receipt</button></main>')
        names = [(c.inner_text() or "").strip() for c in site.find_invoice_controls(page)]
        page.close()
    assert names == ["View invoice"], names


# -- a list an earlier rename left naming the old files ------------------------

OTHER = "902000000000099"


def index_rows(app, number, *paths, confidence="High", status="Completed"):
    app.index_csv.append_rows([{
        "Purchase Date": TIPPED.iso, "Purchase Type": ONLINE, "Order or Receipt Number": number,
        "PDF Filename": f.name, "PDF Full Path": str(f), "Document Type": "Invoice",
        "Classification Confidence": confidence, "Receipt Status": "Downloaded",
        "Processing Status": status} for f in paths])


def left_stale(app, taken: bool):
    """TIPPED's two invoices as an earlier Review Names or Rename left them.
    The second was renamed, its index row and pdf_path follow it, and the
    record's list still names the old file. With `taken`, a later order of
    the same day was saved under that freed name, and its record and its
    row, which the review is unsure of, name it, beside a copy of its
    invoice that Download again left."""
    purchase = tipped_purchase()
    tip = invoice_pdf(app.paths.invoices / "Games (1 of 2).pdf", "1 of 2",
                      "10000000000000042", "10000042 - shipt_tip")
    renamed = invoice_pdf(app.paths.invoices / "Wooden Puzzle Box (2 of 2).pdf", "2 of 2",
                          "10000000000000041", "10000041 - Invented Wooden Puzzle Box")
    old = app.paths.invoices / "Games (2 of 2).pdf"
    entries = [
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000042", "kept": True,
         "names": False},
        {"file": str(old), "part": "2 of 2", "number": "10000000000000041", "kept": True,
         "names": True}]
    app.progress.update(purchase.key, dict(purchase.to_dict(), state="Completed",
                                           downloaded_ok=True, pdf_path=str(renamed),
                                           pdf_filename=renamed.name, invoices=entries))
    index_rows(app, purchase.order_number, renamed)
    other = None
    if taken:
        invoice_pdf(old, "1 of 1", "10000000000000099", "10000099 - Invented Other Thing")
        copy = invoice_pdf(app.paths.invoices / "Games (2 of 2) (2).pdf", "1 of 1",
                           "10000000000000099", "10000099 - Invented Other Thing")
        other = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER,
                         summary="Games")
        app.progress.update(other.key, dict(other.to_dict(), state="Completed",
                                            downloaded_ok=True, pdf_path=str(old),
                                            pdf_filename=old.name, invoices=[
            {"file": str(old), "part": "1 of 1", "number": "10000000000000099",
             "kept": True, "names": True}]))
        index_rows(app, OTHER, old, confidence="Low", status="Review Needed")
        index_rows(app, OTHER, copy)
    return purchase, other, renamed, entries


def saved_record(app, purchase):
    return json.loads(app.paths.progress_json.read_text(encoding="utf-8"))[purchase.key]


def holding(folder, number):
    """The one file in `folder` that is this invoice, by what it says."""
    found = [f for f in Path(folder).glob("*.pdf")
             if number in " ".join(receipt_pdf.pdf_text(f).split())]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("taken", [False, True], ids=["name left free", "name taken since"])
@pytest.mark.parametrize("command", ["review names", "rename"])
def test_a_list_an_earlier_rename_left_stale_is_mended(command, taken, tmp_path, monkeypatch,
                                                       capsys):
    """Review Names and Rename left the record's list naming the old file
    of each invoice they renamed, until the list followed its files. Such a
    list is mended before either reads it, to the file of the order's index
    rows that says it is that invoice, and written down. With the old name
    taken since by another order's invoice, the stale entry named that file,
    so Review Names left the other order's row out as a file two purchases
    name, and Download again counted the other file as this order's. The
    other order's own entry, whose file says it is that invoice, stays where
    it is, though a copy of it is on file as well. Rename gives the order's
    tip the name the rest of the order has, and its entry follows it."""
    app = an_app(tmp_path)
    purchase, other, renamed, entries = left_stale(app, taken)
    asked = []
    monkeypatch.setattr(app_mod, "ask", lambda prompt: asked.append(prompt) or "")
    capsys.readouterr()
    if command == "review names":
        app.cmd_review_names()
    else:
        app.args.apply = True
        app.cmd_rename()

    said = " ".join(capsys.readouterr().out.split())
    assert ("1 invoice(s) in the order records named a file an earlier rename moved, "
            "and now name it as it is.") in said, said
    now = holding(app.paths.invoices, "10000000000000041")
    tip = holding(app.paths.invoices, "10000000000000042")
    record = saved_record(app, purchase)
    assert record["invoices"] == [dict(entries[0], file=str(tip)),
                                  dict(entries[1], file=str(now))], record
    if command == "rename":
        assert Path(entries[0]["file"]).name != tip.name, "the tip takes the order's name"
    if taken:
        theirs = saved_record(app, other)
        assert theirs["invoices"][0]["file"] == theirs["pdf_path"], theirs
        assert Path(theirs["pdf_path"]).exists(), theirs
        if command == "review names":
            assert len(asked) == 1, "the other order's row is offered, %s" % said
            assert "another purchase's rows or record also name" not in said, said


def test_a_rename_preview_mends_nothing_on_disk(tmp_path, capsys):
    """A preview changes nothing. It reads the list as it would be mended,
    so it says what Rename will do, and says the list would be mended. It
    runs through main(), as the panel's Rename preview does, since main()
    saves progress.json after every command, and that save wrote the
    preview's mend down."""
    app = an_app(tmp_path)
    left_stale(app, taken=True)
    before = json.loads(app.paths.progress_json.read_text(encoding="utf-8"))
    capsys.readouterr()
    assert run(tmp_path, "http://127.0.0.1:9", "--rename") == 0
    said = " ".join(capsys.readouterr().out.split())
    assert json.loads(app.paths.progress_json.read_text(encoding="utf-8")) == before
    assert ("1 invoice(s) in the order records name a file an earlier rename moved, and "
            "Rename with --apply writes down where each is now.") in said, said
    assert "Nothing has been changed." in said, said


def test_the_mend_reads_the_index_once(tmp_path, monkeypatch):
    """An archive whose invoices were deleted once they were imported
    elsewhere keeps every entry lost, since none is followed. Each such
    order read the whole index again, so a mend took about a minute at
    three thousand orders, before every Review Names and Rename."""
    app = an_app(tmp_path)
    for k in range(40):
        number = "9020000000%05d" % k
        gone = app.paths.invoices / ("deleted %d (1 of 1).pdf" % k)
        order = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=number)
        app.progress.update(order.key, dict(order.to_dict(), invoices=[
            {"file": str(gone), "part": "1 of 1", "number": "1%016d" % k, "kept": True}]),
            save=False)
        index_rows(app, number, gone)
    app.progress.save()
    reads = []
    real = type(app.index_csv).read_all
    monkeypatch.setattr(type(app.index_csv), "read_all",
                        lambda self: reads.append(self.path) or real(self))
    mended = app._mend_invoice_lists(save=True)
    assert reads.count(app.index_csv.path) == 1, len(reads)
    assert mended == 0, "a deleted invoice is not followed anywhere"


def test_an_invoice_deleted_after_import_keeps_its_entry(tmp_path, monkeypatch):
    """The promise every download here makes. A file deleted once it was
    imported elsewhere is not looked for under another name, and its entry
    is left as it was, so it is not downloaded again."""
    app = an_app(tmp_path)
    purchase, _, renamed, entries = left_stale(app, taken=False)
    renamed.unlink()
    before = app.paths.progress_json.read_bytes()
    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    app.cmd_review_names()
    assert app.paths.progress_json.read_bytes() == before
    assert [e["number"] for e in app._invoices_on_file(purchase)] == [
        "10000000000000042", "10000000000000041"]


def test_download_again_does_not_count_another_orders_file_as_this_ones(tmp_path):
    """With the old name taken by another order's invoice, the stale entry
    named a file that was there, so Download again counted that file as
    this order's invoice. The walk now follows such an entry to the file
    that says it is this invoice, as it follows one whose file is gone."""
    app = an_app(tmp_path, "--redownload")
    purchase, other, renamed, entries = left_stale(app, taken=True)
    assert [e["file"] for e in app._invoices_on_file(purchase)] == [entries[0]["file"],
                                                                    str(renamed)]
    assert [e["file"] for e in app._invoices_on_file(other)] == [
        saved_record(app, other)["invoices"][0]["file"]], "the other order keeps its own"


def test_download_again_fetches_an_invoice_whose_own_file_is_gone_too(tmp_path):
    """The old name was taken by another order's invoice, and this order's
    renamed file was deleted once it was imported elsewhere. The entry has
    no file of its own to follow to, and it named the other order's file,
    which is there, so Download again counted that file as this order's
    invoice and never fetched it. It is missing now, and fetched. Without
    --redownload it still counts, as every invoice saved once does."""
    app = an_app(tmp_path, "--redownload")
    purchase, other, renamed, entries = left_stale(app, taken=True)
    renamed.unlink()
    assert [e["file"] for e in app._invoices_on_file(purchase)] == [entries[0]["file"]]
    assert [e["number"] for e in an_app(tmp_path)._invoices_on_file(purchase)] == [
        "10000000000000042", "10000000000000041"]
    # The stale entry carries its own invoice's number, not the one the
    # other order's file carries, so it is no claim on that file, and the
    # other order's invoice is on file, not fetched a second time.
    assert [e["file"] for e in app._invoices_on_file(other)] == [entries[1]["file"]]


def test_an_entry_that_cannot_be_asked_about_stops_nothing(tmp_path, monkeypatch, capsys):
    """An entry naming a file in a folder the person may not read made
    asking whether it is there raise, which stopped Review Names and Rename
    before they did anything, on every try, and a preview stopped that way
    left what it had mended so far to be saved. Such an entry is left as it
    is, the stale entry before it is mended, and a preview writes nothing."""
    app = an_app(tmp_path)
    purchase, _, renamed, entries = left_stale(app, taken=False)
    locked = app.paths.invoices / "locked" / "Toys (1 of 1).pdf"
    later = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER)
    app.progress.update(later.key, dict(later.to_dict(), invoices=[
        {"file": str(locked), "part": "1 of 1", "number": "10000000000000099", "kept": True}]))
    real = Path.exists

    def exists(self, *args, **kwargs):
        if self.name == locked.name:
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "exists", exists)
    before = json.loads(app.paths.progress_json.read_text(encoding="utf-8"))

    assert run(tmp_path, "http://127.0.0.1:9", "--rename") == 0
    assert json.loads(app.paths.progress_json.read_text(encoding="utf-8")) == before

    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    capsys.readouterr()
    app.cmd_review_names()
    said = " ".join(capsys.readouterr().out.split())
    assert "1 invoice(s) in the order records named a file" in said, said
    assert saved_record(app, purchase)["invoices"] == [
        entries[0], dict(entries[1], file=str(renamed))]
    assert saved_record(app, later)["invoices"][0]["file"] == str(locked)



def unnumbered_invoice(path, line):
    """A saved invoice whose number did not read, so it says only its place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(testkit.text_pdf(["Invoice 1 of 1", line, "Invoice total $4.32"]))
    return path


def left_stale_unnumbered(app, kept: bool):
    """left_stale with the name taken, for invoices that carry no number,
    kept or put aside. TIPPED's one invoice was renamed and its list names
    the old file, which a later order's one invoice took since, and both
    say only "1 of 1". The later order also has a copy of its invoice that
    Download again left, beside the one its record names."""
    folder = app.paths.invoices if kept else app.paths.manual_review
    purchase = tipped_purchase()
    renamed = unnumbered_invoice(folder / "Wooden Puzzle Box.pdf", "Invented Wooden Puzzle Box")
    old = unnumbered_invoice(folder / "Games.pdf", "Invented Other Thing")
    copy = unnumbered_invoice(folder / "Games (2).pdf", "Invented Other Thing")
    entry = {"part": "1 of 1", "number": "", "kept": kept, "names": True}
    app.progress.update(purchase.key, dict(purchase.to_dict(), state="Completed",
                                           downloaded_ok=True, pdf_path=str(renamed),
                                           pdf_filename=renamed.name,
                                           invoices=[dict(entry, file=str(old))]))
    index_rows(app, purchase.order_number, renamed)
    other = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER,
                     summary="Games", items=[Item(name="Invented Other Thing")])
    app.progress.update(other.key, dict(other.to_dict(), state="Completed",
                                        downloaded_ok=True, pdf_path=str(old),
                                        pdf_filename=old.name,
                                        invoices=[dict(entry, file=str(old))]))
    index_rows(app, OTHER, old, confidence="Low", status="Review Needed")
    index_rows(app, OTHER, copy)
    return purchase, other, renamed, old


@pytest.mark.parametrize("kept", [True, False], ids=["kept", "put aside"])
def test_an_unnumbered_invoice_is_not_taken_for_another_orders_of_its_place(
        kept, tmp_path, monkeypatch):
    """Two orders' invoices of one place, "1 of 1", read alike where
    neither carries a number, so the stale entry was taken to name its own
    invoice in the later order's file, and was never mended. A file another
    order claims is this order's only by a number both carry, so the
    stale entry is followed to the order's own file, and Download again
    counts that file, not the other order's. The mend follows the stale
    entry first, by the claims of rows and pdf_path, which follow every
    rename, so the later order keeps its file. Its entry does not move to
    its own copy, Download again counts it, and a copy put aside counts.
    Until that mend, neither order's entry can be told to be the file's, so
    Download again may fetch the later order's invoice once more, a second
    copy and never one written over."""
    app = an_app(tmp_path)
    purchase, other, renamed, old = left_stale_unnumbered(app, kept)
    again = an_app(tmp_path, "--redownload")
    assert [e["file"] for e in again._invoices_on_file(purchase)] == [str(renamed)]

    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    app.cmd_review_names()
    assert [e["file"] for e in saved_record(app, purchase)["invoices"]] == [str(renamed)]
    assert [e["file"] for e in saved_record(app, other)["invoices"]] == [str(old)], \
        "not moved to its own copy"
    for args in ((), ("--redownload",)):
        assert [e["file"] for e in an_app(tmp_path, *args)._invoices_on_file(other)] \
            == [str(old)], args



def tips_taken_since(app, kept: bool):
    """TIPPED's two invoices, its tip named only in its list as Target
    writes one index row per order, were deleted once they were imported
    elsewhere. A later order of the same day and summary took both freed
    names, its own tip again named only in its list."""
    folder = app.paths.invoices if kept else app.paths.manual_review
    tip, doc = folder / "Games (1 of 2).pdf", folder / "Games (2 of 2).pdf"
    purchase = tipped_purchase()
    app.progress.update(purchase.key, dict(purchase.to_dict(), state="Completed",
                                           downloaded_ok=kept, pdf_path=str(doc),
                                           pdf_filename=doc.name, invoices=[
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000042", "kept": kept},
        {"file": str(doc), "part": "2 of 2", "number": "10000000000000041", "kept": kept}]))
    index_rows(app, purchase.order_number, doc)
    invoice_pdf(tip, "1 of 2", "10000000000000098", "10000098 - shipt_tip")
    invoice_pdf(doc, "2 of 2", "10000000000000099", "10000099 - Invented Other Thing")
    other = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER,
                     summary="Games")
    app.progress.update(other.key, dict(other.to_dict(), state="Completed",
                                        downloaded_ok=kept, pdf_path=str(doc),
                                        pdf_filename=doc.name, invoices=[
        {"file": str(tip), "part": "1 of 2", "number": "10000000000000098", "kept": kept},
        {"file": str(doc), "part": "2 of 2", "number": "10000000000000099", "kept": kept}]))
    index_rows(app, OTHER, doc)
    return purchase, other, tip, doc


@pytest.mark.parametrize("kept", [True, False], ids=["kept", "put aside"])
def test_a_later_orders_tip_named_only_in_its_list_is_its_own(kept, tmp_path, monkeypatch):
    """Another order's tip, named only in its list, is a claim on its file.
    Counted as none, the earlier order's stale entry took that tip for its
    own, so Download again never fetched the earlier order's tip, and a
    copy put aside was never fetched again. Another order's list entry
    claims its file by the number the file carries."""
    app = an_app(tmp_path)
    purchase, other, tip, doc = tips_taken_since(app, kept)
    args = ("--redownload",) if kept else ()
    assert an_app(tmp_path, *args)._invoices_on_file(purchase) == [], \
        "both of the earlier order's invoices are missing and fetched again"
    assert [e["file"] for e in an_app(tmp_path, *args)._invoices_on_file(other)] \
        == [str(tip), str(doc)], "the later order's are on file"

    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    before = {f: f.read_bytes() for f in (tip, doc)}
    app.cmd_review_names()
    assert {f: f.read_bytes() for f in (tip, doc)} == before
    assert [e["file"] for e in saved_record(app, other)["invoices"]] == [str(tip), str(doc)]


@pytest.mark.parametrize("kept", [True, False], ids=["kept", "put aside"])
def test_a_stale_tip_is_mended_off_a_later_orders_tip(kept, tmp_path, monkeypatch):
    """The earlier order's tip was renamed, not deleted, and an index row
    names it under its new name, as an archive from when Target wrote a row
    for every invoice does. Its list still names the old name, which the
    later order's tip took, named only in that order's list. The mend
    follows the stale entry to the earlier order's own renamed tip once the
    later order's list is read as a claim, which its rows and pdf_path alone
    never make."""
    app = an_app(tmp_path)
    purchase, other, tip, doc = tips_taken_since(app, kept)
    folder = app.paths.invoices if kept else app.paths.manual_review
    renamed = invoice_pdf(folder / "Shipt Tip (1 of 2).pdf", "1 of 2", "10000000000000042",
                          "10000042 - shipt_tip")
    index_rows(app, purchase.order_number, renamed)
    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    app.cmd_review_names()
    assert [e["file"] for e in saved_record(app, purchase)["invoices"]] == [str(renamed),
                                                                           str(doc)]
    assert [e["file"] for e in saved_record(app, other)["invoices"]] == [str(tip), str(doc)]


def test_a_numbered_stale_entry_is_no_claim_on_an_unnumbered_invoice(tmp_path):
    """The earlier order's stale entry carries its own invoice's number, and
    its renamed file was deleted once it was imported elsewhere, so no mend
    moves it. The later order's invoice under the freed name carries no
    number. The stale entry's number is not the one that file carries, so
    it is no claim on it, and Download again counts the later order's
    invoice as on file rather than fetching it a second time."""
    app = an_app(tmp_path)
    purchase, other, renamed, old = left_stale_unnumbered(app, kept=True)
    record = app.progress.get(purchase.key)
    app.progress.update(purchase.key, {"invoices": [
        dict(record["invoices"][0], number="10000000000000041")]})
    renamed.unlink()
    again = an_app(tmp_path, "--redownload")
    assert again._invoices_on_file(purchase) == []
    assert [e["file"] for e in again._invoices_on_file(other)] == [str(old)]


def numbered_or_not(path, number, line):
    if number:
        return invoice_pdf(path, "1 of 1", number, line)
    return unnumbered_invoice(path, line)


@pytest.mark.parametrize("kept", [True, False], ids=["kept", "put aside"])
@pytest.mark.parametrize("mine, theirs", [("", ""), ("10000000000000041", ""),
                                          ("", "10000000000000099"),
                                          ("10000000000000041", "10000000000000099")],
                         ids=["neither numbered", "mine numbered", "theirs numbered", "both"])
def test_an_entry_is_not_followed_onto_another_orders_file(mine, theirs, kept, tmp_path,
                                                           monkeypatch):
    """Rename gave the earlier order's one invoice a new name, its row and
    pdf_path followed and its list kept the old one, and the renamed file
    was deleted once it was imported elsewhere. A later order's invoice was
    saved under that freed name, which its own row, pdf_path and list name.
    The stale entry's file is gone, so it was followed to the earlier
    order's row, which still names the freed name, and so to the later
    order's file, taken for this order's invoice. That invoice was then
    never fetched again, under --redownload or, put aside, at all. A file
    another order claims is followed to only by a number both carry."""
    app = an_app(tmp_path)
    folder = app.paths.invoices if kept else app.paths.manual_review
    purchase = tipped_purchase()
    freed, old = folder / "Games.pdf", folder / "Old Games.pdf"
    entry = {"part": "1 of 1", "number": mine, "kept": kept, "names": True}
    app.progress.update(purchase.key, dict(purchase.to_dict(), state="Completed",
                                           downloaded_ok=kept, pdf_path=str(freed),
                                           pdf_filename=freed.name,
                                           invoices=[dict(entry, file=str(old))]))
    index_rows(app, purchase.order_number, freed)
    numbered_or_not(freed, theirs, "10000099 - Invented Other Thing")
    other = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER,
                     summary="Games")
    app.progress.update(other.key, dict(other.to_dict(), state="Completed",
                                        downloaded_ok=kept, pdf_path=str(freed),
                                        pdf_filename=freed.name, invoices=[
        dict(entry, file=str(freed), number=theirs)]))
    index_rows(app, OTHER, freed)

    args = ("--redownload",) if kept else ()
    assert an_app(tmp_path, *args)._invoices_on_file(purchase) == [], \
        "the earlier order's invoice is missing and fetched again"
    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    app.cmd_review_names()
    assert [e["file"] for e in saved_record(app, purchase)["invoices"]] == [str(old)]
    assert [e["file"] for e in saved_record(app, other)["invoices"]] == [str(freed)]


def test_an_index_row_that_cannot_be_asked_about_stops_nothing(tmp_path, monkeypatch):
    """One of the order's index rows names a file in a folder the person
    may not read, and asking whether it is there raised, which stopped
    Review Names on every try whenever an entry of that order was lost.
    Such a row is left out of what an entry may be followed to."""
    app = an_app(tmp_path)
    purchase, _, renamed, entries = left_stale(app, taken=False)
    locked = app.paths.invoices / "locked" / "Games (2 of 2).pdf"
    index_rows(app, purchase.order_number, locked)
    real = Path.exists

    def exists(self, *args, **kwargs):
        if self.name == locked.name and self.parent.name == "locked":
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(app_mod, "ask", lambda prompt: "")
    app.cmd_review_names()
    assert saved_record(app, purchase)["invoices"] == [
        entries[0], dict(entries[1], file=str(renamed))]


def test_an_unnumbered_entry_claims_only_a_file_of_its_place(tmp_path):
    """Another order's list entry with no number is a claim on its file,
    since whose the file is cannot be told, but only where the file says
    the entry's place or says none. An entry of "1 of 2" naming a file that
    says "2 of 2" names another invoice than its own, so it claims nothing,
    and the order that file is the invoice of keeps it."""
    app = an_app(tmp_path)
    second = unnumbered_invoice(app.paths.invoices / "Games (2 of 2).pdf", "Invented Thing")
    second.write_bytes(testkit.text_pdf(["Invoice 2 of 2", "Invented Thing"]))
    plain = app.paths.invoices / "Plain.pdf"
    plain.write_bytes(testkit.text_pdf(["Invented Thing"]))
    stale = Purchase(purchase_type=ONLINE, purchase_date=TIPPED.iso, order_number=OTHER)
    app.progress.update(stale.key, dict(stale.to_dict(), invoices=[
        {"file": str(second), "part": "1 of 2", "number": "", "kept": True},
        {"file": str(plain), "part": "1 of 2", "number": "", "kept": True}]))
    another = app._another(app.index_csv.read_all(), app.progress.data)
    assert another(str(second), TIPPED.number) is False, "a file of another place"
    assert another(str(plain), TIPPED.number) is True, "a file that says no place"
