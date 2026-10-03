"""The page Gap prints for a purchase has to be that purchase's page.

The details page is the receipt, and the check on a saved file asks
whether the file names the purchase. Another purchase's page, read first,
writes its own date and items into the purchase and then passes that
check, so it was kept as the receipt. The order history fails the question
of whether a receipt is there at all, and the purchase was then recorded
as having none, which is final.

So the page is checked before anything is taken from it, the way Best Buy
reads the number on its details page. Its address has to be
order-details/<the purchase's id>, and a Purchase # it prints of that
purchase's kind has to be this one. A store purchase's page was never
measured, so one that prints no number of its kind stands on its address,
and it is shown here that such a page is still saved.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Gap. Every id, store,
item and amount is invented.
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
import gap_receipts as app_mod
import gap_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

SHIRT = "7Q2WX5A"
SHORTS = "7R3YZ8B"
STORE = "100000000000000000000031"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"


def details_page(number_line, when, item, attrs, paid, total):
    """A hydrated order-details page, laid out the way the app reads it."""
    return ("<!doctype html><html><head><title>Order Details | Gap</title></head><body>"
            "<header><a href='/'>Gap</a> Free shipping on $50+</header><main><section>"
            "<h2>PURCHASE SUMMARY</h2><p>Purchased:</p><p>%s (10:06PM EDT)</p>%s"
            "<p>Total cost:</p><p>%s (1 items)</p><p>Payment:</p><p>Example Card</p>"
            "<h3>DELIVERY</h3><p>%s</p><p>%s</p><p>%s</p>"
            "<h3>SUMMARY OF CHARGES</h3><p>Subtotal %s</p><p>Total %s</p>"
            "</section></main><footer>Need help? Contact us</footer></body></html>"
            % (when, number_line, total, item, attrs, paid, paid, total))


PAGES = {
    SHIRT: details_page("<p>Purchase #:</p><p>%s</p>" % SHIRT, "June 24, 2026",
                        "Invented Linen Shirt for Men", "M | Sand", "$45.00", "$48.15"),
    SHORTS: details_page("<p>Purchase #:</p><p>%s</p>" % SHORTS, "June 2, 2026",
                         "Invented Cargo Shorts for Men", "32 | Olive", "$30.00", "$32.10"),
    # A store purchase's page, which nobody has seen. It prints a number of
    # another kind, and none of the purchase's own.
    STORE: details_page("<p>Purchase #:</p><p>0417-2206-31</p>", "June 12, 2026",
                        "Invented Canvas Tote Bag", "One Size | Natural", "$19.50", "$20.87"),
}

LISTED = """<!doctype html><html><head><title>Order History | Gap</title></head><body>
<header><a href="/">Gap</a></header><h1>Order History</h1>
<div class="card"><p>Order placed Jun 24, 2026</p><p>Total $48.15</p>
  <a href="/my-account/order-details/%(a)s">Order #%(a)s</a>
  <p>Invented Linen Shirt for Men</p>
  <a href="/my-account/order-details/%(a)s">Details</a></div>
<div class="card"><p>Order placed Jun 2, 2026</p><p>Total $32.10</p>
  <a href="/my-account/order-details/%(b)s">Order #%(b)s</a>
  <p>Invented Cargo Shorts for Men</p>
  <a href="/my-account/order-details/%(b)s">Details</a></div>
<div class="card"><p>Purchased In Store - 1 Items</p><p>EXAMPLE PLAZA</p>
  <p>Purchased Jun 12, 2026</p><p>$20.87</p>
  <a href="/my-account/order-details/%(s)s">Details</a></div>
</body></html>""" % {"a": SHIRT, "b": SHORTS, "s": STORE}


class FakeGap:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.moved = {}      # id -> where its page sends the browser
        self.shown = {}      # id -> another id whose page it shows
        self.seen = []


SITE = FakeGap()


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
        order = path.rsplit("/", 1)[-1]
        if path == "/my-account/order-history":
            self._answer(LISTED)
        elif path.startswith("/my-account/order-details/") and order in PAGES:
            if order in SITE.moved:
                self.send_response(302)
                self.send_header("Location", SITE.moved[order])
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self._answer(PAGES[SITE.shown.get(order, order)])
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
def fake_gap(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setitem(site.URLS, "orders", server + "/my-account/order-history")
    monkeypatch.setitem(site.URLS, "home", server + "/my-account/order-history")
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    real_scroll_all = site.scroll_all_orders
    monkeypatch.setattr(site, "scroll_all_orders",
                        lambda page, **kw: real_scroll_all(page, max_rounds=1, delay_ms=0,
                                                           stable_rounds=1))
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    real_hydrated = site.wait_for_hydration
    monkeypatch.setattr(site, "wait_for_hydration",
                        lambda page, timeout_ms=3000: real_hydrated(page, min(timeout_ms, 3000)))
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


def test_every_purchase_is_printed_from_its_own_page(attached, tmp_path, capsys):
    """What worked before still works, and nothing right is refused, the
    store purchase whose page prints no number of its kind included."""
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert sorted(records) == sorted(["Online:" + SHIRT, "Online:" + SHORTS,
                                      "In-Store:" + STORE]), records
    for key, words in (("Online:" + SHIRT, "Linen Shirt"), ("Online:" + SHORTS, "Cargo Shorts"),
                       ("In-Store:" + STORE, "Canvas Tote")):
        rec = records[key]
        assert rec.get("downloaded_ok") is True, rec
        assert words in pdf_text(rec["pdf_path"]), key
    assert "nothing was saved" not in out, out


def test_the_order_history_is_refused_not_taken_for_a_missing_receipt(attached, tmp_path,
                                                                     capsys):
    """Gap sends the purchase's page back to the order history, which
    names it. It is not the purchase's page, and not a sign it has none."""
    SITE.moved[SHIRT] = "/my-account/order-history"
    pilot(tmp_path, attached)
    out = printed(capsys)

    records = progress(tmp_path)
    assert_refused(records["Online:" + SHIRT], out)
    assert "is not at this purchase's address" in out, out
    assert all("Order History" not in pdf_text(p) for p in saved(tmp_path))
    assert records["Online:" + SHORTS].get("downloaded_ok") is True


def test_another_purchases_page_is_not_printed_as_this_one(attached, tmp_path, capsys):
    """The purchase's address leads to another purchase's page."""
    SITE.moved[SHIRT] = "/my-account/order-details/" + SHORTS
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + SHIRT], out)
    assert sum("Cargo Shorts" in pdf_text(p) for p in saved(tmp_path)) == 1, \
        "the shorts' page was saved twice, once as the shirt's"


def test_another_purchases_page_at_this_address_is_refused(attached, tmp_path, capsys):
    """The address is right and the page is not. Only the Purchase # it
    prints tells them apart."""
    SITE.shown[SHIRT] = SHORTS
    pilot(tmp_path, attached)
    out = printed(capsys)

    assert_refused(progress(tmp_path)["Online:" + SHIRT], out)
    assert "names a different purchase" in out, out


def test_a_refused_purchase_is_asked_for_again_and_saved(attached, tmp_path, capsys):
    """Refusing is not losing it. The next run, with Gap showing the
    purchase's page again, saves it."""
    SITE.moved[SHIRT] = "/my-account/order-history"
    pilot(tmp_path, attached)
    assert not progress(tmp_path)["Online:" + SHIRT].get("downloaded_ok")

    SITE.moved.clear()
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:" + SHIRT]
    assert rec.get("downloaded_ok") is True, rec
    assert "Linen Shirt" in pdf_text(rec["pdf_path"])


def test_a_purchase_number_is_read_from_the_line_after_its_label():
    read = site.PURCHASE_NUMBER_RE.findall
    assert read("PURCHASE SUMMARY\nPurchased:\nJune 24, 2026\nPurchase #:\n7Q2WX5A\nTotal cost:") \
        == ["7Q2WX5A"]
    assert read("Purchase #:\nTotal cost:\n$48.15") == [], \
        "a label with its value missing never reads the next word as one"


def test_only_a_number_of_the_purchases_kind_counts_against_it():
    assert site._same_kind("7R3YZ8B", SHIRT)
    assert site._same_kind("100000000000000000000047", STORE)
    assert not site._same_kind("0417-2206-31", STORE)
    assert not site._same_kind("7R3YZ8B", STORE)
