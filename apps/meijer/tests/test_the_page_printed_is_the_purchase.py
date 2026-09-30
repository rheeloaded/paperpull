"""The page Meijer prints for an order has to be that order's receipt.

A row's link that answers with a page rather than a PDF is opened and
printed. The orders page shows each order's own date and total, and those
together are what the check on the saved file accepts for Meijer, so the
orders page, printed in an order's place, passed it and was kept as the
order's receipt.

So the page is checked before anything is taken from it, the way Best Buy
reads the number on its details page. Nobody has seen an online order's
receipt page, so what decides is where the page is. It has to be the
address the order's row linked to, and that address must not be one of
the order lists.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Meijer. Every order,
item and amount is invented.
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
import meijer_receipts as app_mod
import meijer_site as site
from paperpull_core import browser as browser_launcher

ORDERS = "/shopping/orders.html"
DETAILS = "/shopping/order-details/"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

PICKUPS = [("2026000031", "Jun 1, 2026", "Invented Honeycrisp Apples, 3 lb", "$4.99", "$5.29"),
           ("2026000047", "May 18, 2026", "Invented Rolled Oats, 42 oz", "$3.79", "$4.02")]


def orders_page(rows):
    body = "".join(
        "<li><p>%s</p><p>Pickup order</p><p>%s</p>"
        '<a href="%s">View order details</a></li>' % (when, total, link)
        for link, when, total in rows)
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>"
            "<header><a href='/'>Meijer</a></header>"
            "<main><h1>Orders and Receipts</h1><ul>%s</ul></main></body></html>" % body)


def receipt_page(oid):
    for o, when, item, price, total in PICKUPS:
        if o == oid:
            return ("<!doctype html><html><head><title>Order details</title></head><body>"
                    "<header><a href='/'>Meijer</a></header><main><div class='order'>"
                    "<h1>Order details</h1><p>Order %s</p><p>Placed %s</p>"
                    "<p>%s %s</p><p>Subtotal %s</p><p>Total %s</p>"
                    "</div></main></body></html>" % (o, when, item, price, price, total))
    return None


class FakeMeijer:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}          # order id -> where its link sends the browser
        self.row_links = {}      # order id -> the link its row carries instead
        self.seen = []

    def rows(self):
        return [(self.row_links.get(o, DETAILS + o), when, total)
                for o, when, _item, _price, total in PICKUPS]


SITE = FakeMeijer()


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
        SITE.seen.append(self.path)
        oid = path[len(DETAILS):] if path.startswith(DETAILS) else ""
        if path == ORDERS:
            self._answer(orders_page(SITE.rows()))
        elif oid in SITE.moved:
            self.send_response(302)
            self.send_header("Location", SITE.moved[oid])
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        elif oid and receipt_page(oid):
            self._answer(receipt_page(oid))
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
def fake_meijer(server, monkeypatch):
    """Every address the app opens points at the made-up site. A row's link
    is read against Meijer's own host, and only an address on it is
    followed. Here that host is this machine."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + ORDERS)
    monkeypatch.setattr(site, "ORDER_CANDIDATES", [server + ORDERS])
    monkeypatch.setitem(site.URLS, "orders", server + ORDERS)
    monkeypatch.setitem(site.URLS, "home", server + ORDERS)
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


def pilot(tmp_path, cdp_url):
    assert app_mod.main(["--pilot", "--config", str(config_for(tmp_path, cdp_url))]) == 0


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


def test_every_receipt_is_printed_from_its_own_page(attached, tmp_path, capsys):
    """What worked before still works, and nothing right is refused."""
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert sorted(records) == sorted("Online:" + p[0] for p in PICKUPS), records
    for oid, _when, item, _price, _total in PICKUPS:
        rec = records["Online:" + oid]
        assert rec.get("downloaded_ok") is True, rec
        assert "Order " + oid in pdf_text(rec["pdf_path"])
    assert "nothing was saved" not in out, out


def test_the_orders_page_is_not_printed_as_a_receipt(attached, tmp_path, capsys):
    """The row's link sends the browser back to the orders page, which
    shows the order's date and total."""
    SITE.moved["2026000031"] = ORDERS
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:2026000031"], out)
    assert "is not at this purchase's address" in out, out
    assert all("Orders and Receipts" not in pdf_text(p) for p in saved(tmp_path)), \
        "the orders page was saved as a receipt"
    assert records["Online:2026000047"].get("downloaded_ok") is True


def test_a_row_whose_link_is_the_orders_page_is_not_printed(attached, tmp_path, capsys):
    """A row's link can itself be the orders page. What it opens is the
    list, whatever the link was called."""
    SITE.row_links["2026000031"] = ORDERS
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert "is the order list" in out, out
    assert all("Orders and Receipts" not in pdf_text(p) for p in saved(tmp_path)), \
        "the orders page was saved as a receipt"
    linked = [rec for rec in progress(tmp_path).values()
              if urlsplit(rec.get("receipt_url") or "").path == ORDERS]
    assert len(linked) == 1 and not linked[0].get("downloaded_ok"), linked


def test_a_refused_order_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with the link opening the
    receipt again, saves it."""
    SITE.moved["2026000031"] = ORDERS
    pilot(tmp_path, attached)
    assert not progress(tmp_path)["Online:2026000031"].get("downloaded_ok")

    SITE.moved.clear()
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:2026000031"]
    assert rec.get("downloaded_ok") is True, rec
    assert "Order 2026000031" in pdf_text(rec["pdf_path"])
