"""A receipt Kroger could not load is fetched on the next run, in a real
browser (#70).

A tester's Run All on PaperPull Server met Kroger's own "There was a
problem loading the receipt. Please try again." on a number of his
receipts. The app printed "Kroger could not load this receipt - marked for
manual review." and recorded each as No Receipt Available, which is final,
so his next run said "Already completed and PDF verified - skipping." for
every one of them, and the file was in neither In-Store nor Manual Review.
A page that did not show the receipt says nothing about whether there is
one, and here Kroger itself asked for another try.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page and the history API come from a server on
this machine and the browser resolves no host name, so nothing reaches
Kroger. Kroger's message is in the words of the tester's screenshot. Every
key, store, date, amount and item is invented.
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
import kroger_receipts as app_mod
import kroger_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HISTORY = "/mypurchases"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

STORE_KEY = "705~00331~2026-05-22~014~6620"
OTHER_KEY = "705~00331~2026-05-18~011~2087"
STORE = "In-Store:" + STORE_KEY
OTHER = "In-Store:" + OTHER_KEY


def record(key, when, total):
    return {"receiptKey": key, "purchaseType": "IN_STORE", "status": "COMPLETED",
            "createdDateTime": {"value": when}, "total": total,
            "lineItems": [{"upc": "0000000004011", "quantity": 1}]}


RECORDS = [record(STORE_KEY, "2026-05-22T15:20:00Z", "USD 31.62"),
           record(OTHER_KEY, "2026-05-18T12:41:00Z", "USD 12.09")]

RECEIPTS = {
    STORE_KEY: ("May 22, 2026", "$31.62", "Invented Rolled Oats, 42 oz"),
    OTHER_KEY: ("May 18, 2026", "$12.09", "Invented Honeycrisp Apples"),
}


def receipt_page(key):
    """The receipt in the shape a tester's was recorded in (#41)."""
    date, total, item = RECEIPTS[key]
    return """<!doctype html><html><head><title>Receipt</title></head><body>
<nav>Kroger  My Purchases  Weekly Ad  Digital Coupons</nav>
<main><div class="max-receipt-content">
<button id="receipt-print-button">Print</button>
<div id="receipt-print-area" data-testid="POT-original-receipt">
<div data-testid="PO-invoice-header"><p>Order Type: In Store</p><p>Order Date: %s</p>
<p>Order Number: %s</p><p>Metro Market</p></div>
<h3>Order Summary</h3><p>Order Total</p><p>%s</p>
<h3>Item Details</h3><p>1 Items</p><p>%s</p><p>%s</p><p>1 x %s each</p>
<h3>Payment Details</h3><p>%s</p>
</div></div></main></body></html>""" % (date, key, total, item, total, total, total)


# What Kroger showed the tester in place of his receipt, under the page's
# own trail of links (#70).
COULD_NOT_LOAD = """<!doctype html><html><head><title>Receipt</title></head><body>
<nav>Kroger  Shop  Save  Pickup &amp; Delivery  Services</nav>
<main><nav aria-label="breadcrumb"><a href="/">Home</a> &gt;
<a href="/mypurchases">Purchase History</a> &gt; <a href="#">Purchase Details</a> &gt;
<span>Receipt</span></nav>
<div role="alert">There was a problem loading the receipt. Please try again.</div>
</main></body></html>"""

# A receipt page whose receipt never drew, the shell and nothing in it.
NEVER_DREW = """<!doctype html><html><head><title>Receipt</title></head><body>
<nav>Kroger  Shop  Save  Pickup &amp; Delivery  Services</nav>
<main><div class="max-receipt-content"></div></main></body></html>"""

FAILING = {"Kroger could not load it": (COULD_NOT_LOAD, "Kroger could not load this receipt"),
           "it never drew": (NEVER_DREW, "Receipt page did not render")}

LISTED = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1>
<div data-testid="PO-NonPendingPurchase"><p>In-Store</p><p>May 22, 2026</p><p>$31.62</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
<div data-testid="PO-NonPendingPurchase"><p>In-Store</p><p>May 18, 2026</p><p>$12.09</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
</main></body></html>""" % (STORE_KEY, OTHER_KEY)

HOME = """<!doctype html><html><head><title>Kroger</title></head>
<body><h1>Kroger</h1></body></html>"""


class FakeKroger:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.failing = {}           # key -> the page shown in place of its receipt
        self.seen = []


SITE = FakeKroger()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        url = urlsplit(self.path)
        SITE.seen.append(url.path)
        key = url.path[len(site.RECEIPT_PATH):] if url.path.startswith(site.RECEIPT_PATH) else ""
        if url.path == HISTORY:
            body, kind = LISTED, "text/html; charset=utf-8"
        elif url.path == site.SEARCH_API:
            body = json.dumps({"data": {"postOrderSearch": {
                "data": RECORDS, "pageNo": 1, "pageSize": site.PAGE_SIZE, "isLastPage": True}}})
            kind = "application/json"
        elif key in SITE.failing:
            body, kind = SITE.failing[key], "text/html; charset=utf-8"
        elif key in RECEIPTS:
            body, kind = receipt_page(key), "text/html; charset=utf-8"
        elif url.path == "/":
            body, kind = HOME, "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
    started can abort its first navigation."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_kroger(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the receipt's thirty seconds included."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    waits = site.wait_for_receipt
    monkeypatch.setattr(site, "wait_for_receipt",
                        lambda page, timeout_ms=30000: waits(page, min(timeout_ms, 2000)))
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run_all(tmp_path, cdp_url, capsys):
    """A Run All, which has to finish. What it printed, with its line breaks
    read as spaces, and the counts the panel reads off the line the core
    prints for it."""
    SITE.seen.clear()
    assert app_mod.main(["--all", "--yes", "--config", str(config_for(tmp_path, cdp_url))]) == 0
    out = capsys.readouterr().out
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return " ".join(out.split()), json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def progress(tmp_path):
    path = tmp_path / "out" / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def downloaded(tmp_path):
    """The purchases whose receipt was saved and passed its check."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("downloaded_ok")
                  and Path(r.get("pdf_path") or "").is_file())


def rows_naming(tmp_path, key):
    """How many rows each CSV holds for this purchase."""
    number = key.split(":", 1)[1]
    counts = {}
    for name in ("receipt_index_csv", "order_history_csv"):
        path = getattr(storage.Paths(tmp_path / "out"), name)
        rows = []
        if path.exists():
            import csv
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows = [r for r in csv.DictReader(fh) if r.get("Order or Receipt Number") == number]
        counts[name] = len(rows)
    return counts


def receipts_opened():
    return sorted({p[len(site.RECEIPT_PATH):] for p in SITE.seen if p.startswith(site.RECEIPT_PATH)})


@pytest.mark.parametrize("shown, why", list(FAILING.values()), ids=list(FAILING))
def test_a_receipt_that_did_not_show_is_fetched_on_the_next_run(attached, shown, why, tmp_path,
                                                                capsys):
    SITE.failing = {OTHER_KEY: shown}
    said, panel = run_all(tmp_path, attached, capsys)

    assert downloaded(tmp_path) == [STORE], "the receipt that showed is saved"
    assert "%s, on 1 of 3 separate runs. It is tried again next run." % why in said, said
    assert "marked for manual review" not in said, said
    assert panel["failed"] == 1, "the panel says one receipt was not saved"
    rec = progress(tmp_path)[OTHER]
    assert rec["state"] == "Failed" and rec["notes"].endswith(why + ", tried again next run"), rec
    assert rows_naming(tmp_path, OTHER) == {"receipt_index_csv": 0, "order_history_csv": 0}, \
        "nothing is written down for a receipt that was not saved"

    # Kroger gives it this time.
    SITE.failing = {}
    said, panel = run_all(tmp_path, attached, capsys)

    assert downloaded(tmp_path) == sorted([STORE, OTHER]), said
    assert receipts_opened() == [OTHER_KEY], "only the one not saved is asked for"
    assert "Already completed and PDF verified - skipping." in said
    assert panel["failed"] == 0 and panel["new_files"] == 1, panel
    assert rows_naming(tmp_path, OTHER)["receipt_index_csv"] == 1, "written down once, when saved"


def test_a_receipt_that_never_shows_is_set_aside_after_three_runs(attached, tmp_path, capsys):
    """Each run asks for it, and on the third that finds nothing it is set
    aside, written down once and counted for review. The next run skips it
    and says why, rather than calling it completed."""
    SITE.failing = {OTHER_KEY: COULD_NOT_LOAD}
    for n in (1, 2):
        said, panel = run_all(tmp_path, attached, capsys)
        assert "on %d of 3 separate runs. It is tried again next run." % n in said, said
        assert receipts_opened() == ([OTHER_KEY, STORE_KEY] if n == 1 else [OTHER_KEY])
    said, panel = run_all(tmp_path, attached, capsys)
    assert "on 3 of 3 separate runs. It is not asked for again, and Download again still "            "asks for it." in said, said
    assert panel["failed"] == 0 and panel["manual_review"] >= 1, panel
    assert progress(tmp_path)[OTHER]["state"] == "No Receipt Available"
    assert rows_naming(tmp_path, OTHER) == {"receipt_index_csv": 1, "order_history_csv": 1}

    said, panel = run_all(tmp_path, attached, capsys)
    assert receipts_opened() == [], said
    assert "Its receipt did not show on 3 separate runs, so it is skipped. Download again "            "asks for it." in said, said
    assert rows_naming(tmp_path, OTHER) == {"receipt_index_csv": 1, "order_history_csv": 1}
    assert downloaded(tmp_path) == [STORE]


@pytest.mark.parametrize("why", [w for _, w in FAILING.values()])
def test_a_receipt_an_older_version_gave_up_on_is_fetched(attached, why, tmp_path, capsys):
    """His records from 0.44.0 say No Receipt Available, in the words that
    version wrote, and the next run fetches each."""
    SITE.failing = {OTHER_KEY: COULD_NOT_LOAD}
    run_all(tmp_path, attached, capsys)
    for name in ("progress.json", "discovery.json"):
        path = tmp_path / "out" / name
        data = json.loads(path.read_text(encoding="utf-8"))
        data[OTHER]["state"] = "No Receipt Available"
        if name == "progress.json":
            data[OTHER]["notes"] = why
        path.write_text(json.dumps(data), encoding="utf-8")

    SITE.failing = {}
    said, panel = run_all(tmp_path, attached, capsys)

    assert downloaded(tmp_path) == sorted([STORE, OTHER]), said
    assert receipts_opened() == [OTHER_KEY]


def test_a_purchase_left_without_a_receipt_for_another_reason_stays_so(attached, tmp_path, capsys):
    """What worked before still works. No Receipt Available is still final
    when its note is not one of those words."""
    SITE.failing = {OTHER_KEY: COULD_NOT_LOAD}
    run_all(tmp_path, attached, capsys)
    path = tmp_path / "out" / "progress.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[OTHER].update(state="No Receipt Available", notes="No printable receipt available")
    path.write_text(json.dumps(data), encoding="utf-8")

    SITE.failing = {}
    said, panel = run_all(tmp_path, attached, capsys)

    assert downloaded(tmp_path) == [STORE]
    assert receipts_opened() == [], said
