"""The page Amazon prints for an order has to be that order's summary.

The check on a saved file asks whether the file names the order. The order
list prints every order's id, and another order's summary read first
writes its own date and items into the order, so either one, printed in an
order's place, passed that check. The list also fails the question of
whether a summary is there at all, and an order was then recorded as having
no receipt, which is final, so its summary was never asked for again.

So the page is checked before anything is taken from it, the way Best Buy
reads the number on its details page. Its address has to name the order in
orderID, and every order id the page prints has to be this one.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Amazon. Every order id,
seller, item and amount is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
import amazon_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

GLOVES = "112-1000000-1000031"
STAND = "112-1000000-1000047"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

ORDERS = {
    GLOVES: ("June 3, 2026", "Invented Work Gloves, Leather, Large", "$18.37", "$20.51"),
    STAND: ("May 20, 2026", "Invented Pour Over Stand, Walnut", "$34.21", "$37.79"),
}


def summary_page(order_id):
    """The printable summary, laid out the way the app reads it."""
    when, item, price, total = ORDERS[order_id]
    return ("<!doctype html><html><head><title>Amazon.com - Order %s</title></head><body>"
            "<h1>Details for Order #%s</h1>"
            "<p>Order Placed: %s</p><p>Amazon.com order number: %s</p>"
            "<p>Order Total: %s</p><h2>Items Ordered</h2>"
            "<p>%s</p><p>Sold by: Example Seller Co</p><p>%s</p>"
            "<p>Item(s) Subtotal: %s</p><p>Grand Total: %s</p>"
            "</body></html>" % (order_id, order_id, when, order_id, total, item,
                                price, price, total))


def order_card(order_id):
    when, item, _price, total = ORDERS[order_id]
    return ('<div class="order-card js-order-card"><p>Order placed</p><p>%s</p>'
            "<p>Total</p><p>%s</p><p>Order # %s</p>"
            '<a href="/dp/B000000001">%s</a>'
            '<a href="/gp/your-account/order-details?orderID=%s">View order details</a>'
            "</div>" % (when, total, order_id, item, order_id))


LISTED = ("<!doctype html><html><head><title>Your Orders</title></head><body>"
          "<h1>Your Orders</h1>%s</body></html>"
          % "".join(order_card(o) for o in ORDERS))


class FakeAmazon:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}      # order id -> where its summary sends the browser
        self.shown = {}      # order id -> another order whose summary it shows
        self.seen = []


SITE = FakeAmazon()


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
        SITE.seen.append(self.path)
        order = (parse_qs(parts.query).get("orderID") or [""])[0]
        if parts.path == "/gp/css/order-history":
            self._answer(LISTED)
        elif parts.path == "/gp/css/summary/print.html" and order in ORDERS:
            if order in SITE.moved:
                self.send_response(302)
                self.send_header("Location", SITE.moved[order])
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self._answer(summary_page(SITE.shown.get(order, order)))
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
def fake_amazon(server, monkeypatch):
    """Every address the app opens points at the made-up site. The app
    points itself at its store when it starts, so the store it is pointed
    at is this machine."""
    SITE.reset()
    real_set = site.set_marketplace

    def pointed(domain):
        out = real_set(domain)
        monkeypatch.setattr(site, "BASE", server)
        monkeypatch.setattr(site, "URLS", {"home": server + "/",
                                           "orders": server + "/gp/css/order-history"})
        return out

    monkeypatch.setattr(site, "set_marketplace", pointed)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    yield SITE
    real_set(site.DEFAULT_MARKETPLACE)


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def pilot(tmp_path, cdp_url):
    assert app_mod.main(["--pilot", "--year", "2026",
                         "--config", str(config_for(tmp_path, cdp_url))]) == 0


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


def test_every_order_is_printed_from_its_own_summary(attached, tmp_path, capsys):
    """What worked before still works, and nothing right is refused."""
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert sorted(records) == sorted("Online:" + o for o in ORDERS), records
    for order in ORDERS:
        rec = records["Online:" + order]
        assert rec.get("downloaded_ok") is True, rec
        assert "Amazon.com order number: " + order in pdf_text(rec["pdf_path"])
    assert "nothing was saved" not in out, out


def test_the_order_list_is_refused_not_taken_for_a_missing_summary(attached, tmp_path, capsys):
    """Amazon sends the order's summary back to the list, which prints the
    order's id. It is not this order's summary, and not a sign it has none."""
    SITE.moved[GLOVES] = "/gp/css/order-history"
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:" + GLOVES], out)
    assert "is not at this purchase's address" in out, out
    assert all("Your Orders" not in pdf_text(p) for p in saved(tmp_path))
    assert records["Online:" + STAND].get("downloaded_ok") is True


def test_another_orders_summary_is_not_printed_as_this_one(attached, tmp_path, capsys):
    """The order's address leads to another order's summary."""
    SITE.moved[GLOVES] = "/gp/css/summary/print.html?orderID=" + STAND
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + GLOVES], out)
    assert len(saved(tmp_path)) == 1, "only the stand's own summary is kept"


def test_another_orders_summary_at_this_orders_address_is_refused(attached, tmp_path, capsys):
    """The address is right and the summary is not. Only the ids it prints
    tell them apart."""
    SITE.shown[GLOVES] = STAND
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + GLOVES], out)
    assert "names a different purchase" in out, out


def test_a_refused_order_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with Amazon showing the
    order's summary again, saves it."""
    SITE.moved[GLOVES] = "/gp/css/order-history"
    pilot(tmp_path, attached)
    assert not progress(tmp_path)["Online:" + GLOVES].get("downloaded_ok")

    SITE.moved.clear()
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:" + GLOVES]
    assert rec.get("downloaded_ok") is True, rec
    assert "Amazon.com order number: " + GLOVES in pdf_text(rec["pdf_path"])
