"""The page Target prints for a purchase has to be that purchase's page.

The check on a saved file asks whether the file names the purchase.
Another purchase's page, read first, writes its own date and items into
the purchase and then passes that check, so its receipt was kept as this
one's. The order list has no receipt on it, and the purchase was then
recorded as having none, which is final.

So the page is checked before anything is taken from it, the way Best Buy
reads the number on its details page. Its address has to name the
purchase, and a number the page heads itself with, "Order details" or
"Purchase details" over "#" and the number, or the receipts page's trail,
has to be this one. Target's own bot check is still left to stop the run.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Target. Every number,
store, item and amount is invented.
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

PILLOW = "102000000000031"
BLANKET = "102000000000047"
SOAP = "1000-0000-0000-0031"
SPONGE = "1000-0000-0000-0047"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

ONLINE = {
    PILLOW: ("Jun 3, 2026", "Invented Throw Pillow, Gray", "$18.37", "$20.51"),
    BLANKET: ("May 20, 2026", "Invented Fleece Blanket, Navy", "$24.13", "$26.99"),
}
IN_STORE = {
    SOAP: ("June 12, 2026", "Invented Dish Soap, Lemon", "$5.53", "$6.02"),
    SPONGE: ("June 2, 2026", "Invented Kitchen Sponges, 6 Pack", "$4.61", "$4.85"),
}


def trail(number, last=""):
    return '<nav><a href="/orders">Orders/</a><span>%s%s</span></nav>' % (number, last)


def online_details(number):
    when, item, price, total = ONLINE[number]
    return ("<!doctype html><html><head><title>Orders : Order Details</title></head><body>"
            "<header><a href='/'>Target</a></header>%s<main>"
            "<h1>Order details</h1><p>#%s</p><p>Placed at 10:02 am on %s</p>"
            '<div data-test="package-card-item-row"><p>%s</p><p>%s</p><p>Qty 1</p></div>'
            "<p>Subtotal</p><p>%s</p><p>Total</p><p>%s</p>"
            '<a href="/orders/%s/receipts">Receipts &amp; invoices</a>'
            "</main></body></html>"
            % (trail(number), number, when, item, price, price, total, number))


def online_receipts(number):
    when, item, price, total = ONLINE[number]
    return ("<!doctype html><html><head><title>Orders : Receipts</title></head><body>"
            "<header><a href='/'>Target</a></header>%s<main><h1>Receipts</h1>"
            "<section><h2>Receipts and invoices</h2>"
            '<button type="button" onclick="window.print()">Print receipts</button>'
            "<div><h3>Store Receipt</h3><p>1 of 1</p><p>Return receipt</p>"
            "<p>Order number: %s</p><p>Receipt ID: 9-1000-0000-0000-0031-1</p>"
            "<p>%s</p><p>Qty: 1</p><p>%s</p></div></section></main></body></html>"
            % (trail(number, "/"), number, item, price))


def store_details(number):
    when, item, price, total = IN_STORE[number]
    receipt = ("<p>EXAMPLE STORE</p><p>%s 4:10 PM</p><p>%s %s</p><p>TOTAL %s</p>"
               "<p>REC#2-%s-0</p>" % (when, item.upper(), price, total, number))
    return ("<!doctype html><html><head><title>Orders : Order Details</title></head><body>"
            "<header><a href='/'>Target</a></header>%s<main>"
            "<h1>Purchase details</h1><p>#%s</p><p>1 items</p><p>Purchased on %s 4:10 pm</p>"
            '<button type="button" onclick="document.getElementById(\'r\').hidden=false">'
            "View your receipt</button>"
            '<div data-test="package-card-item-row"><p>%s</p><p>%s</p><p>Qty 1</p></div>'
            "<p>Store trip at Example Store</p><p>Total</p><p>%s</p>"
            '<div id="r" hidden data-test="store-pos-order-receipt-container">%s</div>'
            "</main></body></html>"
            % (trail(number), number, when, item, price, total, receipt))


PAGES = {"/orders/%s" % n: online_details(n) for n in ONLINE}
PAGES.update({"/orders/%s/receipts" % n: online_receipts(n) for n in ONLINE})
PAGES.update({"/orders/stores/%s" % n: store_details(n) for n in IN_STORE})


def listed():
    online = "".join(
        '<a data-test="order-details-link" href="/orders/%s"><p>%s</p><p>View purchase</p>'
        "<p>%s</p><p>#%s</p><p>Delivered</p><p>%s</p></a>"
        % (n, when, total, n, item) for n, (when, item, _p, total) in ONLINE.items())
    store = "".join(
        '<a data-test="store-order-details-link" href="/orders/stores/%s"><p>%s</p>'
        "<p>View purchase</p><p>%s</p><p>Purchased</p><p>Store trip at Example Store</p></a>"
        % (n, when, total) for n, (when, _i, _p, total) in IN_STORE.items())
    return ("<!doctype html><html><head><title>Orders : Target</title></head><body>"
            "<header><a href='/'>Target</a></header><h1>Purchase history</h1>"
            '<div role="tablist"><button role="tab" data-test="tabOnline">Online</button>'
            '<button role="tab" data-test="tabInstore">In-store</button></div>'
            "%s%s</body></html>" % (online, store))


class FakeTarget:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}      # path -> where Target sends it instead
        self.shown = {}      # path -> another path whose page it shows
        self.seen = []


SITE = FakeTarget()


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
        if path in SITE.moved:
            self.send_response(302)
            self.send_header("Location", SITE.moved[path])
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        elif path == "/orders":
            self._answer(listed())
        elif path in PAGES:
            self._answer(PAGES[SITE.shown.get(path, path)])
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
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab has drawn a page,
    since a browser that has only just started can abort its first
    navigation, and this test's first goto came back net::ERR_ABORTED on
    CI that way (run 37123796050). Target works in the first tab it finds,
    the one the person signed in with at home, so the tab that drew is the
    browser's only tab."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,), only_tab=True) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_target(server, monkeypatch):
    """Every address the app opens points at the made-up site, and the
    wait for a print that never comes is short."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    real_trigger = site.trigger_print_receipt
    monkeypatch.setattr(site, "trigger_print_receipt",
                        lambda page, control, timeout_ms=1000: real_trigger(page, control, 1000))
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, *flags):
    assert app_mod.main([*flags, "--config", str(config_for(tmp_path, cdp_url))]) == 0


def progress(tmp_path):
    return json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def saved(tmp_path):
    """Every PDF the run left anywhere under its folder."""
    return sorted((tmp_path / "out").rglob("*.pdf"))


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def assert_refused(rec, out):
    assert not rec.get("downloaded_ok"), "kept as the receipt: %r" % rec
    assert rec["state"] == "Needs Manual Review", rec
    assert "nothing was saved" in out, out
    assert "refused because they were not the one asked for" in out, out


def test_every_purchase_is_printed_from_its_own_page(attached, tmp_path, capsys):
    """What worked before still works, and nothing right is refused. Two
    online orders and two store purchases, the later ones read after the
    first left the tab printing."""
    run(tmp_path, attached, "--pilot")
    out = printed(capsys)

    records = progress(tmp_path)
    keys = ["Online:" + n for n in ONLINE] + ["In-Store:" + n for n in IN_STORE]
    assert sorted(records) == sorted(keys), records
    for key in keys:
        rec = records[key]
        number = key.split(":", 1)[1]
        item = (ONLINE.get(number) or IN_STORE.get(number))[1]
        assert rec.get("downloaded_ok") is True, rec
        assert item.split(",")[0].upper() in pdf_text(rec["pdf_path"]).upper(), key
    assert "nothing was saved" not in out, out


def test_the_order_list_is_refused_not_taken_for_a_missing_receipt(attached, tmp_path,
                                                                  capsys):
    """Target sends the order's page back to the list. It is not the
    order's page, and not a sign the order has no receipt."""
    SITE.moved["/orders/" + PILLOW] = "/orders"
    run(tmp_path, attached, "--pilot-online")
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:" + PILLOW], out)
    assert "is not at this purchase's address" in out, out
    assert records["Online:" + BLANKET].get("downloaded_ok") is True


def test_another_orders_page_is_not_printed_as_this_one(attached, tmp_path, capsys):
    """The order's address leads to another order's page, and on to that
    order's receipts."""
    SITE.moved["/orders/" + PILLOW] = "/orders/" + BLANKET
    run(tmp_path, attached, "--pilot-online")
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + PILLOW], out)
    assert sum("Fleece Blanket" in pdf_text(p) for p in saved(tmp_path)) == 1, \
        "the blanket's receipt was saved twice, once as the pillow's"


def test_another_purchase_at_this_purchases_address_is_refused(attached, tmp_path, capsys):
    """The address is right and the page is not. Only the number the page
    heads itself with tells them apart, and the receipt opens on it."""
    SITE.shown["/orders/stores/" + SOAP] = "/orders/stores/" + SPONGE
    run(tmp_path, attached, "--pilot-instore")
    out = printed(capsys)

    assert_refused(progress(tmp_path)["In-Store:" + SOAP], out)
    assert "names a different purchase" in out, out
    assert sum("SPONGES" in pdf_text(p).upper() for p in saved(tmp_path)) == 1


def test_a_refused_order_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with Target showing the
    order's page again, saves its receipt."""
    SITE.moved["/orders/" + PILLOW] = "/orders"
    run(tmp_path, attached, "--pilot-online")
    assert not progress(tmp_path)["Online:" + PILLOW].get("downloaded_ok")

    SITE.moved.clear()
    run(tmp_path, attached, "--pilot-online")
    rec = progress(tmp_path)["Online:" + PILLOW]
    assert rec.get("downloaded_ok") is True, rec
    assert "Throw Pillow" in pdf_text(rec["pdf_path"])


def test_the_number_a_page_heads_itself_with_is_read_and_a_card_is_not():
    def read(text):
        return [n for rx in site._PAGE_NUMBER_RES for n in rx.findall(text)]
    assert read("Orders/\n%s\nOrder details\n#%s\nPlaced at" % (PILLOW, PILLOW)) == [PILLOW]
    assert read("Purchase details #%s\n1 items" % SOAP) == [SOAP]
    assert read("Orders/\n%s/\nReceipts\nReceipts and invoices" % PILLOW) == [PILLOW]
    assert read("Purchase history\nJun 3, 2026\nView purchase\n$20.51\n#%s\nDelivered"
                % PILLOW) == [], "the list's cards head nothing"
