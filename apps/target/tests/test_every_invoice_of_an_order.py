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
from paperpull_core import receipt_pdf
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
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def _addresses(cdp_url):
    return [t.get("url") for t in _page_targets(cdp_url)]


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
    that page has drawn, as its id and address, or None.

    The first tab a fresh browser opens sometimes never sends a single
    request, for a minute and more, and a second tab always drew. So a tab
    that has not drawn in 10 seconds is closed, and another opened once it
    is gone, three at most."""
    for _attempt in range(3):
        name = "tab%d" % next(_TAB_NAMES)
        address = "%s/drawn/%s" % (server, name)
        request = urllib.request.Request(cdp_url + "/json/new?" + address, method="PUT")
        with urllib.request.urlopen(request, timeout=10) as r:
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


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "include_invoices": True, "delay_min_seconds": 0, "delay_max_seconds": 0}),
        encoding="utf-8")
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


ALL_INVOICES = [v for o in (SPLIT, SINGLE, DIRECT, TIPPED) for v in o.invoices]


def opened(path):
    return SITE.seen.count(path)


def new_this_run(tmp_path):
    lines = (tmp_path / "out" / "new-this-run.txt").read_text(encoding="utf-8").splitlines()
    return sorted(Path(ln).name for ln in lines if ln and not ln.startswith("#"))


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


# -- the rules, each on its own -------------------------------------------------

def test_an_invoice_page_says_which_of_the_order_it_is():
    page = ("Invoice 2 of 2 Invoice date: Thu, Feb 5, 2026 Invoice number: 10000000000000041 "
            "Item 10000041 - Invented Wooden Puzzle Box Invoice total $34.56")
    assert site.invoice_identity(page) == ((2, 2), "10000000000000041")
    listing = "Invoices Invoice 1 of 2 View invoice Invoice 2 of 2 View invoice"
    assert site.invoice_identity(listing) == (None, ""), "a list is not one of them"
    assert site.invoice_identity("Something went wrong") == (None, "")


def an_app(tmp_path, *args):
    return app_mod.App(app_mod.build_parser().parse_args(
        ["--config", str(config_for(tmp_path, "http://127.0.0.1:9")), *args]))


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
