"""Round six (#42), from his 0.41.0 Run All and Pilot.

Run All went down the In-Store Receipts list newest first and saved one
receipt after another from the same orders page, until the page it opened
for the next purchase drew only the list's heading and a line under it. No
tabs, no rows. The app looked for the tab once, for the purchase's row for
ten seconds, and wrote the purchase down as a row with no receipt. The
failure file it left says "when the run gave up", which every app's failure
file says of the first failure of a run, and the run goes on from there to
the next purchase, with nothing done about a page like that one.

Now a purchase's list is waited for, the page is opened once more when it
did not come, a purchase whose list never came is left for the next run
rather than written down as having no receipt, and only three of those in
a row stop the run.

His Pilot also printed "? bytes, ? pages" for the receipt put aside in
Manual Review, which was on disk the whole time, and skipped it saying it
was "Already completed and PDF verified", which it never was.

Pages are served on https://www.meijer.com in Playwright's own Chromium and
every other request is refused, so nothing leaves this machine. Every date,
store, amount and word is invented.
"""
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import meijer_receipts as mr
import meijer_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import classification
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase, State


def _text_pdf(lines) -> bytes:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out) + b" " * 4000


def _till(date_us: str, total: str) -> bytes:
    """A till receipt printing its date the way a till does and its total."""
    return _text_pdf(["MEIJER STORE 000", "%s 10:15" % date_us, "TOTAL %s" % total, "THANK YOU"])


RECEIPT = _till("08/21/26", "47.18")
OTHER_RECEIPT = _till("08/14/26", "19.05")
NOT_A_RECEIPT = _text_pdf(["ZEBRAFISH QUARTERLY", "Page 1 of 1", "Terms and conditions apply"])


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield


def _purchase(date="2026-08-21", total="$47.18", key="pexample0821"):
    return Purchase(purchase_type=IN_STORE, purchase_date=date, order_number=key,
                    total=total, status="Paid", summary="Mixed Purchases", confidence="Low",
                    items=[Item(name="400 Example Avenue", quantity="1", line_total=total)])


def _app(tmp_path):
    app = object.__new__(mr.App)
    app.args = SimpleNamespace(redownload=False, dry_run=False)
    app.config = {"min_pdf_bytes": 3000, "max_path_length": 240, "owner": "",
                  "delay_min_seconds": 0, "delay_max_seconds": 0}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.progress.data, app.progress._loaded = {}, True
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.discovery.data, app.discovery._loaded = {}, True
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.rules = classification.load_rules()
    app.stats = {"validation_failures": 0, "manual_review": 0, "new_files": [],
                 "receipts_downloaded": 0, "no_receipt": 0, "failed": 0,
                 "duplicate_filenames": 0, "skipped_completed": 0, "canceled": 0,
                 "dates_processed": []}
    app.failures = []
    app.write_failure = lambda step, reason, **k: app.failures.append((step, reason))
    return app


def _saved(app, purchase):
    return app.paths.folder_for(IN_STORE, "Receipt") / \
        ("%s Meijer Mixed Purchases Receipt.pdf" % purchase.purchase_date)


# -- the pages -------------------------------------------------------------------

ORDERS = site.ORDERS_URL
PDF_URL = "https://www.meijer.com/shopping/receipt/example-0821.pdf"
OTHER_PDF_URL = "https://www.meijer.com/shopping/receipt/example-0814.pdf"

# The site's own header carries an amount and the heading says Orders, so the
# orders page reads as one whatever its list is doing.
HEADER = ("<header><a href='/shopping/account.html'>Account</a>"
          "<span>You saved $12.34 this year</span></header>")


def _row(date, amount, pdf_url):
    return ("<li class='order-card'><div class='date'>In-Store: %s</div><div>400 Example Avenue</div>"
            "<div class='totals'><span>%s</span>&nbsp;&nbsp;7 items</div>"
            "<a href='javascript:void(0)' onclick=\"window.open('%s', '_blank');return false\">"
            "view receipt pdf</a></li>" % (date, amount, pdf_url))


ROWS = _row("08/21/2026", "$47.18", PDF_URL) + _row("08/14/2026", "$19.05", OTHER_PDF_URL)
TABS = ("<div role='tablist'>"
        "<a role='tab' href='#' onclick=\"show('online');return false\">Online Orders</a>"
        "<a role='tab' href='#' onclick=\"show('store');return false\">In-Store Receipts</a></div>"
        "<div id='online'><p>You haven't placed any orders yet</p></div>"
        "<div id='store' style='display:none'><ul id='rows'>%s</ul></div>")

SHOW = ("<script>function show(which) {"
        " document.getElementById('online').style.display = which === 'online' ? '' : 'none';"
        " document.getElementById('store').style.display = which === 'store' ? '' : 'none'; }</script>")

PAGES = {
    # What the page drew in place of the list, a heading and a line.
    "broken": ("<!doctype html><html><body>%s<main><div class='orders-page'>"
               "<div class='orders-head'><h1>Orders and Receipts</h1></div>"
               "<p>Something went wrong.</p></div></main></body></html>" % HEADER),
    "good": ("<!doctype html><html><body>%s<main><h1>Orders and Receipts</h1>%s%s</main></body></html>"
             % (HEADER, TABS % ROWS, SHOW)),
    # The heading first, and the tabs and the list four seconds later.
    "late": ("<!doctype html><html><body>%s<main><h1>Orders and Receipts</h1>"
             "<div id='orders'><p>One moment</p></div>%s<script>setTimeout(() => {"
             " document.getElementById('orders').innerHTML = %r; }, 4000);</script></main></body></html>"
             % (HEADER, SHOW, TABS % ROWS)),
    # The tabs at once, and the list fourteen seconds after its tab is
    # pressed, longer than the tab's own pause and the row's ten seconds.
    "slow": ("<!doctype html><html><body>%s<main><h1>Orders and Receipts</h1>%s%s<script>"
             "let asked = false; const shown = show; show = (which) => { shown(which);"
             " if (which === 'store' && !asked) { asked = true; setTimeout(() => {"
             " document.getElementById('rows').innerHTML = %r; }, 14000); } };</script></main></body></html>"
             % (HEADER, TABS % "", SHOW, ROWS)),
}


@contextmanager
def orders_browser(plan):
    """A page on www.meijer.com whose orders page answers each load with the
    next page named in `plan`, and the last one again after that. The names
    of the pages served are listed, in order, as they are served."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        browser = driver.chromium.launch(
            headless=True, args=["--disable-extensions", "--disable-sync", "--no-first-run"])
    except Exception as e:
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    served = []

    def serve(route):
        name = plan[min(len(served), len(plan) - 1)]
        served.append(name)
        route.fulfill(status=200, content_type="text/html", body=PAGES[name])
    try:
        ctx = browser.new_context(accept_downloads=True)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route(ORDERS, serve)
        ctx.route(PDF_URL, lambda r: r.fulfill(status=200, content_type="application/pdf", body=RECEIPT))
        ctx.route(OTHER_PDF_URL, lambda r: r.fulfill(status=200, content_type="application/pdf",
                                                     body=OTHER_RECEIPT))
        yield ctx.new_page(), served
    finally:
        browser.close()
        driver.stop()


# -- the list, in a browser -------------------------------------------------------

def test_a_list_that_did_not_come_is_opened_once_more_and_its_receipt_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "LIST_WAIT_MS", 3000, raising=False)
    with orders_browser(["broken", "good"]) as (pg, served):
        app = _app(tmp_path)
        p = _purchase()
        assert app._save_receipt(pg, p) is True
        assert served == ["broken", "good"]
    assert _saved(app, p).read_bytes() == RECEIPT, "this purchase's receipt, not the row below it"
    assert (app.progress.get(p.key) or {}).get("downloaded_ok") is True


def test_a_tab_the_page_draws_late_is_waited_for(tmp_path):
    with orders_browser(["late"]) as (pg, served):
        app = _app(tmp_path)
        p = _purchase()
        assert app._save_receipt(pg, p) is True
        assert served == ["late"], "found on the first look"
    assert _saved(app, p).read_bytes() == RECEIPT


def test_a_list_that_comes_slowly_after_its_tab_is_waited_for(tmp_path):
    with orders_browser(["slow"]) as (pg, served):
        app = _app(tmp_path)
        p = _purchase()
        assert app._save_receipt(pg, p) is True
        assert served == ["slow"], "found on the first look"
    assert _saved(app, p).read_bytes() == RECEIPT


def test_a_list_that_never_came_is_not_written_down_as_a_row_without_a_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(site, "LIST_WAIT_MS", 2000, raising=False)
    with orders_browser(["broken"]) as (pg, served):
        app = _app(tmp_path)
        p = _purchase()
        assert app._save_receipt(pg, p) is False
        assert served == ["broken", "broken"], "looked at twice, never more"
    rec = app.progress.get(p.key) or {}
    assert rec.get("state") == State.FAILED.value, rec
    assert "list did not load" in rec.get("notes", "")
    assert app._already_done(_purchase()) is False, "the next run looks for it again"
    assert app.index_csv.read_all() == [], "no row saying its row has no receipt"
    assert app.failures == [("open the purchase list", "the list did not load")]
    assert "The In-Store list did not load" in capsys.readouterr().out
    import json
    attempt = json.loads((app.paths.diagnostics / "download-attempt.json").read_text(encoding="utf-8"))
    looks = [t for t in attempt["responses"] if t.get("note") == "the purchase's tab"]
    assert looks == [{"note": "the purchase's tab", "opened": False, "rows": 0}] * 2, attempt


def test_only_rows_that_show_on_the_purchases_tab_are_counted():
    with orders_browser(["good"]) as (pg, served):
        pg.goto(ORDERS)
        assert site.rows_showing(pg, IN_STORE) == 0, "the In-Store tab is not open yet"
        assert site.show_tab_for(pg, IN_STORE)
        assert site.rows_showing(pg, IN_STORE) == 2
        assert site.rows_showing(pg, ONLINE) == 0, "an in-store row is not an online one"


# -- the run, with the page played here -------------------------------------------
#
# Each load of the orders page is the next of `loads`, "good" when it shows
# the purchase's list and "broken" when it does not. The row's receipt is the
# purchase's own till receipt, whenever its list shows.

class _Page:
    url = ORDERS

    def __init__(self, loads, text="Orders and Receipts"):
        self.loads = list(loads)
        self.state = ""
        self.opened = 0
        self.text = text

    def load(self):
        self.state = self.loads[min(self.opened, len(self.loads) - 1)]
        self.opened += 1

    def title(self):
        return "Your Orders"

    def locator(self, sel):
        page = self

        class _L:
            first = property(lambda s: s)

            def count(s):
                return 1

            def inner_text(s, timeout=0):
                return page.text
        return _L()


def _playing(monkeypatch, page):
    """The site's page steps, answering from `page`."""
    pressed = []

    def press(pg, purchase, trace=None):
        pressed.append(purchase.purchase_date)
        if pg.state != "good":
            return None
        return _till("%s/%s/%s" % (purchase.purchase_date[5:7], purchase.purchase_date[8:10],
                                   purchase.purchase_date[2:4]), purchase.total.lstrip("$"))
    monkeypatch.setattr(site, "goto_orders", lambda pg, page_no=1: pg.load())
    monkeypatch.setattr(site, "show_tab_for", lambda pg, t: pg.state == "good")
    monkeypatch.setattr(site, "show_list_for",
                        lambda pg, t, wait_ms=None: {"opened": pg.state == "good",
                                                     "rows": 3 if pg.state == "good" else 0},
                        raising=False)
    monkeypatch.setattr(site, "press_row_receipt", press)
    return pressed


def _four():
    return [_purchase("2026-08-%02d" % d, "$%d.25" % (10 + d), "pexample08%02d" % d)
            for d in (28, 21, 14, 7)]


def test_the_run_goes_on_past_a_purchase_whose_list_did_not_come(tmp_path, monkeypatch):
    page = _Page(["broken", "broken", "good"])
    _playing(monkeypatch, page)
    app = _app(tmp_path)
    app.page = lambda: page
    first, second = _four()[:2]
    app.process_purchases([first, second])
    assert (app.progress.get(first.key) or {}).get("state") == State.FAILED.value
    assert app._already_done(first) is False
    assert (app.progress.get(second.key) or {}).get("downloaded_ok") is True, \
        "the next purchase is looked for on a list that came"
    assert _saved(app, second).exists()


def test_three_purchases_in_a_row_without_a_list_stop_the_run(tmp_path, monkeypatch, capsys):
    page = _Page(["broken"])
    _playing(monkeypatch, page)
    app = _app(tmp_path)
    app.page = lambda: page
    purchases = _four()
    with pytest.raises(SystemExit) as stopped:
        app.process_purchases(purchases)
    assert stopped.value.code == 0
    assert page.opened == 6, "two looks each for three purchases, and the fourth never asked for"
    on_disk = storage.JsonStore(app.paths.progress_json)
    on_disk.load()
    assert [(on_disk.get(p.key) or {}).get("state") for p in purchases] == \
        [State.FAILED.value] * 3 + [None]
    assert "press Resume" in capsys.readouterr().out


def test_misses_that_are_not_in_a_row_never_stop_the_run(tmp_path, monkeypatch):
    page = _Page(["broken"] * 4 + ["good"] + ["broken"] * 4)
    _playing(monkeypatch, page)
    app = _app(tmp_path)
    app.page = lambda: page
    purchases = _four() + [_purchase("2026-07-31", "$9.99", "pexample0731")]
    app.process_purchases(purchases)
    assert [(app.progress.get(p.key) or {}).get("state") for p in purchases] == [
        State.FAILED.value, State.FAILED.value, State.NEEDS_MANUAL_REVIEW.value,
        State.FAILED.value, State.FAILED.value]
    assert (app.progress.get(purchases[2].key) or {}).get("downloaded_ok") is True


def test_a_list_that_shows_without_the_row_is_recorded_as_before(tmp_path, monkeypatch):
    """Looked at twice all the same, and written down as it always was, since
    the list came and the row was not on it. It never counts toward a stop."""
    page = _Page(["good"])
    _playing(monkeypatch, page)
    monkeypatch.setattr(site, "press_row_receipt", lambda pg, purchase, trace=None: None)
    app = _app(tmp_path)
    p = _purchase()
    assert app._save_receipt(page, p) is False
    assert page.opened == 2
    assert (app.progress.get(p.key) or {}).get("state") == State.NO_RECEIPT_AVAILABLE.value
    assert app._lists_missed == 0


def test_the_page_just_opened_is_the_one_checked_for_a_challenge(tmp_path, monkeypatch):
    """Meijer answering "Too many requests" on the page the row is looked for
    on stops the run there, before the purchase is written down as a row with
    no receipt. It was checked only on the page the purchase before had left,
    so it was seen, if at all, one purchase late."""
    page = _Page(["broken"])
    _playing(monkeypatch, page)

    def goto(pg, page_no=1):
        pg.load()
        pg.text = "Orders and Receipts\nToo many requests. Please try again later."
    monkeypatch.setattr(site, "goto_orders", goto)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: None)
    app = _app(tmp_path)
    p = _purchase()
    with pytest.raises(SystemExit):
        app._save_receipt(page, p)
    assert (app.progress.get(p.key) or {}).get("state") != State.NO_RECEIPT_AVAILABLE.value


# -- the pilot report --------------------------------------------------------------

def test_a_receipt_put_aside_is_not_called_verified_when_it_is_skipped(tmp_path, capsys):
    """His Pilot said "Already completed and PDF verified" of the receipt it
    had put aside for failing its check."""
    app = _app(tmp_path)
    app.page = lambda: None
    p = _purchase()
    aside = app.paths.manual_review / "2026-08-21 Meijer Mixed Purchases Receipt.pdf"
    aside.write_bytes(NOT_A_RECEIPT)
    app.progress.data[p.key] = {"state": State.NEEDS_MANUAL_REVIEW.value, "pdf_path": str(aside),
                                "pdf_filename": aside.name}
    app.process_purchases([p])
    out = capsys.readouterr().out
    assert "Put aside in Manual Review" in out and "Delete it there" in out, out
    assert "PDF verified" not in out
    assert aside.read_bytes() == NOT_A_RECEIPT, "left where it is"


def test_a_saved_receipt_marked_for_its_name_is_still_called_verified(tmp_path, capsys):
    app = _app(tmp_path)
    app.page = lambda: None
    p = _purchase()
    app.progress.data[p.key] = {"state": State.NEEDS_MANUAL_REVIEW.value, "downloaded_ok": True,
                                "notes": "Low classification confidence"}
    app.process_purchases([p])
    assert "Already completed and PDF verified" in capsys.readouterr().out

def test_the_pilot_report_measures_a_receipt_put_aside(tmp_path, capsys):
    app = _app(tmp_path)
    p = _purchase()
    aside = app.paths.manual_review / "2026-08-21 Meijer Mixed Purchases Receipt.pdf"
    aside.write_bytes(NOT_A_RECEIPT)
    app.progress.data[p.key] = {
        "state": State.NEEDS_MANUAL_REVIEW.value, "purchase_date": p.purchase_date,
        "order_number": p.order_number, "pdf_path": str(aside), "pdf_filename": aside.name,
        "notes": "PDF validation failed: Extractable text does not mention the purchase"}
    app._pilot_report([p])
    out = capsys.readouterr().out
    assert "PDF exists: True  (%d bytes, 1 pages)" % len(NOT_A_RECEIPT) in out, out
    assert "? bytes" not in out


def test_the_pilot_report_keeps_what_a_verified_receipt_recorded(tmp_path, capsys):
    app = _app(tmp_path)
    p = _purchase()
    saved = app.paths.folder_for(IN_STORE, "Receipt") / "x.pdf"
    saved.write_bytes(RECEIPT)
    app.progress.data[p.key] = {"state": State.PDF_VERIFIED.value, "downloaded_ok": True,
                                "pdf_path": str(saved), "pdf_filename": saved.name,
                                "pdf_size": 12345, "pdf_pages": 2}
    app._pilot_report([p])
    assert "PDF exists: True  (12345 bytes, 2 pages)" in capsys.readouterr().out


def test_the_pilot_report_of_a_file_that_is_gone(tmp_path, capsys):
    app = _app(tmp_path)
    p = _purchase()
    app.progress.data[p.key] = {"state": State.NEEDS_MANUAL_REVIEW.value,
                                "pdf_path": str(tmp_path / "gone.pdf"), "pdf_filename": "gone.pdf"}
    app._pilot_report([p])
    assert "PDF exists: False  (? bytes, ? pages)" in capsys.readouterr().out
