"""The page Walmart prints for a purchase has to be that purchase's page.

The check on a saved file asks whether the file names the purchase. The
order list names every purchase on it, by date, total and the items in its
pictures, and a wrong page read first writes its own facts into the
purchase, so the list, or another order's page, printed in a purchase's
place passed that check and was kept as its receipt, marked downloaded,
and the real one was never asked for again.

So the page is checked before it is printed, the way Best Buy reads the
number on its details page. It has to be at /orders/<the order's id>, and
the page as it prints has to name this order by its "Order#" or "TC#" and
no other. Walmart prints that number only on the printed page, so it is
read there, and a run's second purchase is read in print media left over
from the first, so a run of three is shown to come out whole.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Walmart. Every order
number, store, item and amount is invented.
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
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit
from paperpull_core.models import IN_STORE, ONLINE

# Online ids print as seven digits, a dash and eight, store ids as five
# groups of four, and in both the digits are the id the app keys on.
HOSE = "100000000000031"
LAMP = "100000000000047"
STORE = "10000000000000000004"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

PRINT_ONLY = """<style>
@media screen { .print-only { display: none } }
@media print { .screen-only { display: none } }
</style>"""


def order_page(printed, when, items, total, kind="order"):
    """A details page as Walmart draws it. The page on screen, and the
    receipt, with its number, only on the printed page."""
    tiles = "".join(
        '<div data-testid="itemtile-stack"><span data-testid="productName">%s</span>'
        '<p>Qty 1</p><span data-testid="line-price">%s</span></div>' % (name, price)
        for name, price in items)
    lines = "".join("<p>%s Qty 1 %s</p>" % (name, price) for name, price in items)
    return ("<!doctype html><html><head><title>Order details</title>%s</head><body>"
            '<header class="screen-only"><a href="/">Walmart</a> Save money. Live better.</header>'
            '<main class="screen-only"><h1>%s %s</h1><p>Delivered</p>%s<p>Total %s</p></main>'
            '<section class="print-only"><h2>Invoice</h2><p>%s %s</p><p>%s</p>%s'
            "<p>Total %s</p><p>%s</p></section></body></html>"
            % (PRINT_ONLY, when, kind, tiles, total, when, kind, printed, lines, total, printed))


PAGES = {
    "/orders/" + HOSE: order_page("Order# 1000000-00000031", "Jun 3, 2026",
                                  [("Invented Garden Hose, 50 ft", "$41.97")], "$45.02"),
    "/orders/" + LAMP: order_page("Order# 1000000-00000047", "May 20, 2026",
                                  [("Invented Reading Lamp, Brass", "$27.88")], "$29.95"),
    "/orders/" + STORE: order_page("TC# 1000-0000-0000-0000-0004", "Jun 12, 2026",
                                   [("Invented Whole Milk, 1 gal", "$3.48")], "$3.83",
                                   kind="purchase"),
}

# The order list, with each order's items under their pictures.
# Online cards carry no date and store cards do.
LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<header><a href="/">Walmart</a> Save money. Live better.</header>
<h1>Purchase history</h1>
<div data-testid="order-0">
  <p>Delivered</p><p>$45.02</p><img alt="Invented Garden Hose, 50 ft" src="data:,"><p>Invented Garden Hose, 50 ft</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
<div data-testid="order-1">
  <p>Delivered</p><p>$29.95</p><img alt="Invented Reading Lamp, Brass" src="data:,"><p>Invented Reading Lamp, Brass</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
<div data-testid="order-2">
  <p>Store purchase</p><p>Purchased at Example Supercenter</p>
  <p>Jun 12, 2026</p><p>$3.83</p><img alt="Invented Whole Milk, 1 gal" src="data:,"><p>Invented Whole Milk, 1 gal</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
</body></html>""" % (HOSE, LAMP, STORE)


class FakeWalmart:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}      # path -> where Walmart sends it instead
        self.shown = {}      # path -> another path whose page it shows
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
            self._answer(LISTED)
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
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation, which is how Target's copy of
    this test failed on CI (run 37123796050). The app works in a tab it
    opens for itself, so the tab that drew can stay where it is."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_walmart(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short."""
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setitem(site.FILTER_URL, ONLINE, server + "/orders?filterIds=online")
    monkeypatch.setitem(site.FILTER_URL, IN_STORE, server + "/orders?filterIds=in-store")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 3000, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    # These pages are laid out the way they were before Walmart's own
    # invoice block came, so it is looked for once rather than waited for.
    monkeypatch.setattr(site, "INVOICE_WAIT_MS", 0, raising=False)
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    # A details address is built on Walmart's own host, and only an address
    # on it is opened. Here that host is this machine.
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
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
    online orders and a store purchase, each printed with its own number,
    the second and third read after the first left the tab printing."""
    run(tmp_path, attached, "--pilot")
    out = printed(capsys)

    records = progress(tmp_path)
    assert sorted(records) == sorted(["Online:" + HOSE, "Online:" + LAMP,
                                      "In-Store:" + STORE]), records
    for key, number in (("Online:" + HOSE, "1000000-00000031"),
                        ("Online:" + LAMP, "1000000-00000047"),
                        ("In-Store:" + STORE, "1000-0000-0000-0000-0004")):
        rec = records[key]
        assert rec.get("downloaded_ok") is True, rec
        assert number in pdf_text(rec["pdf_path"]), key
    assert "nothing was saved" not in out, out


def test_the_order_list_is_not_printed_as_an_order(attached, tmp_path, capsys):
    """Walmart sends the order's page back to the list, which names the
    order by its total and its item's picture."""
    SITE.moved["/orders/" + HOSE] = "/orders"
    run(tmp_path, attached, "--pilot-online")
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:" + HOSE], out)
    assert "is not at this purchase's address" in out, out
    assert all("Purchase history" not in pdf_text(p) for p in saved(tmp_path)), \
        "the order list was saved"
    assert records["Online:" + LAMP].get("downloaded_ok") is True, "the next order is unaffected"


def test_another_orders_page_is_not_printed_as_this_one(attached, tmp_path, capsys):
    """The order's address leads to another order's page."""
    SITE.moved["/orders/" + HOSE] = "/orders/" + LAMP
    run(tmp_path, attached, "--pilot-online")
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:" + HOSE], out)
    for path in saved(tmp_path):
        assert pdf_text(path).count("Reading Lamp") and "Garden Hose" not in pdf_text(path)
    assert len(saved(tmp_path)) == 1, "only the lamp's own invoice is kept"


def test_another_orders_page_at_this_orders_address_is_refused(attached, tmp_path, capsys):
    """The address is right and the page is not. Only the number it prints
    tells them apart."""
    SITE.shown["/orders/" + HOSE] = "/orders/" + LAMP
    run(tmp_path, attached, "--pilot-online")
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + HOSE], out)
    assert "names a different purchase" in out, out


def test_a_refused_order_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with Walmart showing the
    right page again, saves the order's own invoice."""
    SITE.moved["/orders/" + HOSE] = "/orders"
    run(tmp_path, attached, "--pilot-online")
    assert not progress(tmp_path)["Online:" + HOSE].get("downloaded_ok")

    SITE.moved.clear()
    run(tmp_path, attached, "--pilot-online")
    rec = progress(tmp_path)["Online:" + HOSE]
    assert rec.get("downloaded_ok") is True, rec
    assert "1000000-00000031" in pdf_text(rec["pdf_path"])


def test_the_printed_number_is_read_to_the_end_of_its_line_and_no_further():
    """Its digits are compared whole, so a count or a total after it on the
    same line, or a digit on the next, must not become part of it."""
    read = site.PAGE_NUMBER_RE.findall
    assert read("Invoice\nJun 3, 2026 order\nOrder# 1000000-00000031\nBuyer") == ["1000000-00000031"]
    assert read("TC# 1000-0000-0000-0000-0004\n9") == ["1000-0000-0000-0000-0004"]
    assert read("TC# 1000-0000-0000-0000-0004 12 items") == ["1000-0000-0000-0000-0004"]
    assert read("TC#\n1000-0000-0000-0000-0004") == ["1000-0000-0000-0000-0004"]
    assert read("Reorder# 1000000-00000031") == [], "a word ending in order is not the label"
