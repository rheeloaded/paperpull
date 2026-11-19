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
# A purchase made after both, listed only once a test lists it.
NEWER_KEY = "705~00331~2026-05-25~016~3104"
NEWER = "In-Store:" + NEWER_KEY


def record(key, when, total):
    return {"receiptKey": key, "purchaseType": "IN_STORE", "status": "COMPLETED",
            "createdDateTime": {"value": when}, "total": total,
            "lineItems": [{"upc": "0000000004011", "quantity": 1}]}


RECORDS = [record(STORE_KEY, "2026-05-22T15:20:00Z", "USD 31.62"),
           record(OTHER_KEY, "2026-05-18T12:41:00Z", "USD 12.09")]

RECEIPTS = {
    STORE_KEY: ("May 22, 2026", "$31.62", "Invented Rolled Oats, 42 oz"),
    OTHER_KEY: ("May 18, 2026", "$12.09", "Invented Honeycrisp Apples"),
    NEWER_KEY: ("May 25, 2026", "$8.47", "Invented Baby Spinach"),
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
        self.newer = []             # purchases listed besides RECORDS


SITE = FakeKroger()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        url = urlsplit(self.path)
        SITE.seen.append(url.path)
        route = url.path[len(site.RECEIPT_PATH):] if url.path.startswith(site.RECEIPT_PATH) else ""
        key = next((k for k in RECEIPTS if site.page_key(k) == route), "")
        if url.path == HISTORY:
            body, kind = LISTED, "text/html; charset=utf-8"
        elif url.path == site.SEARCH_API:
            body = json.dumps({"data": {"postOrderSearch": {
                "data": RECORDS + SITE.newer, "pageNo": 1, "pageSize": site.PAGE_SIZE, "isLastPage": True}}})
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


def run_all(tmp_path, cdp_url, capsys, day=None, monkeypatch=None):
    """A Run All, which has to finish. What it printed, with its line breaks
    read as spaces, and the counts the panel reads off the line the core
    prints for it. With a day, the run starts on that day of April 2031,
    since a receipt that did not show is counted by the day."""
    SITE.seen.clear()
    if day is not None:
        monkeypatch.setattr(app_mod, "now_iso", lambda: "2031-04-%02dT12:00:00" % day)
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
    return sorted({k for k in RECEIPTS if site.RECEIPT_PATH + site.page_key(k) in SITE.seen})


@pytest.mark.parametrize("shown, why", list(FAILING.values()), ids=list(FAILING))
def test_a_receipt_that_did_not_show_is_fetched_on_the_next_run(attached, shown, why, tmp_path,
                                                                capsys):
    SITE.failing = {OTHER_KEY: shown}
    said, panel = run_all(tmp_path, attached, capsys)

    assert downloaded(tmp_path) == [STORE], "the receipt that showed is saved"
    assert "%s, on 1 of 3 separate days. It is tried again next run." % why in said, said
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


def test_a_receipt_that_never_shows_is_set_aside_after_three_days(attached, tmp_path, capsys,
                                                                    monkeypatch):
    """Each run asks for it, and on the third day that finds nothing it is
    set aside, written down once and counted for review. The next run skips
    it and says why, rather than calling it completed. That third day's run
    saved a newer purchase's receipt before it, as a run must before it
    sets one aside (#225)."""
    SITE.failing = {OTHER_KEY: COULD_NOT_LOAD}
    for n in (1, 2):
        said, panel = run_all(tmp_path, attached, capsys, day=n, monkeypatch=monkeypatch)
        assert "on %d of 3 separate days. It is tried again next run." % n in said, said
        assert receipts_opened() == ([OTHER_KEY, STORE_KEY] if n == 1 else [OTHER_KEY])
    SITE.newer = [record(NEWER_KEY, "2026-05-25T09:05:00Z", "USD 8.47")]
    said, panel = run_all(tmp_path, attached, capsys, day=3, monkeypatch=monkeypatch)
    assert ("on 3 of 3 separate days. It is set aside for review and not asked for "
            "again.") in said, said
    assert panel["failed"] == 0 and panel["manual_review"] >= 1, panel
    assert progress(tmp_path)[OTHER]["state"] == "No Receipt Available"
    assert rows_naming(tmp_path, OTHER) == {"receipt_index_csv": 1, "order_history_csv": 1}
    assert receipts_opened() == sorted([NEWER_KEY, OTHER_KEY]), said

    said, panel = run_all(tmp_path, attached, capsys, day=4, monkeypatch=monkeypatch)
    assert receipts_opened() == [], said
    assert ("Its receipt did not show on 3 separate days, so it is set aside for review "
            "and skipped.") in said, said
    assert rows_naming(tmp_path, OTHER) == {"receipt_index_csv": 1, "order_history_csv": 1}
    assert downloaded(tmp_path) == sorted([STORE, NEWER])


NOT_SET_ASIDE = ("Kroger could not load this receipt, on 3 separate days. It is not set aside, "
                 "because no in-store receipt was saved before it in this run, and it is tried "
                 "again next run.")


def test_a_run_that_saved_no_receipt_sets_none_aside(attached, tmp_path, capsys, monkeypatch):
    """Kroger stopped showing a tester's receipts, every one of 244, and the
    third day of runs set each aside for good, written into both CSVs, on
    PaperPull Server, which has no Download again (#225). A page that shows
    nothing for every purchase says Kroger's pages are broken, not that
    there is no receipt. So a run that saved no receipt sets none aside,
    each is tried again next run with its days kept, and the next day asks
    for both."""
    SITE.failing = {STORE_KEY: COULD_NOT_LOAD, OTHER_KEY: COULD_NOT_LOAD}
    for n in (1, 2):
        said, panel = run_all(tmp_path, attached, capsys, day=n, monkeypatch=monkeypatch)
        assert said.count("on %d of 3 separate days. It is tried again next run." % n) == 2, said

    said, panel = run_all(tmp_path, attached, capsys, day=3, monkeypatch=monkeypatch)
    for key in (STORE, OTHER):
        rec = progress(tmp_path)[key]
        assert rec["state"] == "Failed", (key, rec["state"], said)
        assert len(rec["not_shown_days"]) == 3, rec
        assert rows_naming(tmp_path, key) == {"receipt_index_csv": 0, "order_history_csv": 0}
    assert "set aside for review" not in said, said
    assert said.count(NOT_SET_ASIDE) == 2, said
    assert panel["failed"] == 2 and panel["manual_review"] == 0, panel
    summary = " ".join(storage.Paths(tmp_path / "out").run_summary.read_text(
        encoding="utf-8").split())
    assert "Failed: 2" in summary and "No printable receipt: 0" in summary, summary

    said, panel = run_all(tmp_path, attached, capsys, day=4, monkeypatch=monkeypatch)
    assert receipts_opened() == sorted([OTHER_KEY, STORE_KEY]), said
    assert all(progress(tmp_path)[k]["state"] == "Failed" for k in (STORE, OTHER))
    assert panel["failed"] == 2, panel


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


# Two purchases at one store on one day, the second's transaction the first's
# with a digit more, so one route starts with the other (#235).
SAME_DAY_KEY = "705~00331~2026-05-24~016~310"
SAME_DAY_LONGER_KEY = "705~00331~2026-05-24~016~3104"
SAME_DAY = "In-Store:" + SAME_DAY_KEY
SAME_DAY_LONGER = "In-Store:" + SAME_DAY_LONGER_KEY
# A receipt key in a shape this version does not know, its date without
# dashes.
ODD_KEY = "705~00331~20260520~012~5510"
ODD = "In-Store:" + ODD_KEY
RECEIPTS.update({
    SAME_DAY_KEY: ("May 24, 2026", "$5.13", "Invented Sourdough Loaf"),
    SAME_DAY_LONGER_KEY: ("May 24, 2026", "$62.40", "Invented Laundry Detergent"),
    ODD_KEY: ("May 20, 2026", "$9.99", "Invented Green Tea"),
})


def test_two_receipts_of_one_day_at_one_store_each_save_their_own(attached, tmp_path, capsys):
    from paperpull_core.receipt_pdf import pdf_text
    SITE.newer = [record(SAME_DAY_KEY, "2026-05-24T10:00:00Z", "USD 5.13"),
                  record(SAME_DAY_LONGER_KEY, "2026-05-24T18:00:00Z", "USD 62.40")]
    said, panel = run_all(tmp_path, attached, capsys)
    assert downloaded(tmp_path) == sorted([STORE, OTHER, SAME_DAY, SAME_DAY_LONGER]), said
    assert sorted(set(receipts_opened())) == sorted([STORE_KEY, OTHER_KEY, SAME_DAY_KEY,
                                                     SAME_DAY_LONGER_KEY])
    for key, total, item in ((SAME_DAY, "$5.13", "Sourdough"), (SAME_DAY_LONGER, "$62.40", "Detergent")):
        text = pdf_text(Path(progress(tmp_path)[key]["pdf_path"]))
        assert total in text and item in text, (key, text[:300])
    for key in (SAME_DAY, SAME_DAY_LONGER):
        assert key in progress(tmp_path), "the purchase keeps the API's key"
    assert not any(k.startswith("In-Store:2026-") for k in progress(tmp_path)), "no route form key"


def test_resume_opens_the_new_route_in_place_of_an_old_saved_address(attached, server, tmp_path,
                                                                     capsys):
    """A run before the route change saved its receipt addresses in the
    API's form. Resume reads them from discovery without the history, and
    the receipt opens at the new route, built from the purchase's own key.
    The made-up site is plain http, which the app never follows as a saved
    address, so this checks the address Resume builds. A saved https
    address on Kroger in the old form is checked without a browser, in
    test_current_receipt_routes and test_a_route_opens_its_own_purchase."""
    SITE.failing = {OTHER_KEY: COULD_NOT_LOAD}
    run_all(tmp_path, attached, capsys)
    path = tmp_path / "out" / "discovery.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[OTHER]["receipt_url"] = server + site.RECEIPT_PATH + OTHER_KEY
    path.write_text(json.dumps(data), encoding="utf-8")

    SITE.failing = {}
    SITE.seen.clear()
    assert app_mod.main(["--resume", "--yes", "--config", str(config_for(tmp_path, attached))]) == 0
    said = " ".join(capsys.readouterr().out.split())
    assert downloaded(tmp_path) == sorted([STORE, OTHER]), said
    assert receipts_opened() == [OTHER_KEY]
    assert site.RECEIPT_PATH + OTHER_KEY not in SITE.seen, "the old route is not asked for"


def test_a_key_of_a_shape_not_known_is_never_set_aside(attached, tmp_path, capsys, monkeypatch):
    """Opened at a route that cannot show it, its empty page would count
    toward a set-aside, and the third day, after a save of its kind, would
    set it aside for good. It is not opened, and stays Failed, tried again
    next run, with the purchase's key kept."""
    SITE.newer = [record(ODD_KEY, "2026-05-20T11:00:00Z", "USD 9.99")]
    for n in (1, 2, 3):
        if n == 3:
            SITE.newer.append(record(NEWER_KEY, "2026-05-25T09:05:00Z", "USD 8.47"))
        said, panel = run_all(tmp_path, attached, capsys, day=n, monkeypatch=monkeypatch)
        rec = progress(tmp_path)[ODD]
        assert not any("20260520" in p for p in SITE.seen), SITE.seen
        assert "not_shown_days" not in rec, rec
        assert "set aside" not in said, said
        assert rec["state"] == "Failed", (n, rec, said)
        assert app_mod.UNKNOWN_KEY in rec["notes"], rec
        assert panel["failed"] == 1, panel
    assert NEWER in downloaded(tmp_path)
    assert rows_naming(tmp_path, ODD) == {"receipt_index_csv": 0, "order_history_csv": 0}
