"""What a run says of a purchase whose list showed and whose row gave no
receipt (#42).

It used to say the same of every one of them, that its row carried no
receipt or details link, and to mark it for manual review and write it into
both CSVs, on every run that looked for it again. Not one of them had ever
lacked a link that way. The row was not on the page, or more than one row
fitted it, or nothing on it read as its receipt, or the press brought no
PDF. Each is now said as what happened, as a failure the next run looks for
again, and none goes into the CSVs.

The press runs in Playwright's own Chromium on pages served on
https://www.meijer.com, and every other request is refused, so nothing
leaves this machine. Every date, store and amount is invented.
"""
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import meijer_receipts as mr
import meijer_site as site
from paperpull_core import classification
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase

ORDERS = "https://www.meijer.com/shopping/orders.html"

SAVE_JS = ("function saveReceipt() { const pdf = '%PDF-1.4 invented receipt ' + 'x'.repeat(300);"
           " const a = document.createElement('a');"
           " a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));"
           " a.download = 'receipt.pdf'; document.body.appendChild(a); a.click(); }")

RECEIPT_LINK = ("<a href='javascript:void(0)' onclick=\"saveReceipt(); return false\">"
                "view receipt pdf</a>")
NOTHING_LINK = "<a href='javascript:void(0)' onclick=\"return false\">view receipt pdf</a>"
EMAIL_ONLY = "<button onclick=\"return false\">Email receipt</button>"


def row(date, controls, amount="$31.23"):
    return ("<li class='order-card'><div class='date'>In-Store: %s</div><div>1600 Invented Road</div>"
            "<div class='totals'><span>%s</span>&nbsp;&nbsp;6 items</div>%s</li>"
            % (date, amount, controls))


def page_of(rows):
    return ("<!doctype html><html><body><main><div id='store'><ul>%s</ul></div>"
            "<script>%s</script></main></body></html>" % ("".join(rows), SAVE_JS))


@pytest.fixture
def browser_ctx():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    try:
        yield ctx
    finally:
        browser.close()
        driver.stop()


def pressed_on(ctx, rows, date):
    """Press the row of the purchase listed on `date`, on a page holding
    `rows`, and say what came of it, as (its bytes, what the press said)."""
    ctx.route(ORDERS, lambda r: r.fulfill(status=200, content_type="text/html", body=page_of(rows)))
    pg = ctx.new_page()
    pg.goto(ORDERS)
    listed = [p for p in map(site.card_to_purchase, site.collect_cards(pg)) if p]
    purchase = next((p for p in listed if p.purchase_date == date), None) or listed[0]
    purchase.purchase_type = IN_STORE
    purchase.purchase_date = date
    facts: dict = {}
    body = site.press_row_receipt(pg, purchase, [], facts=facts)
    return body, facts


@pytest.mark.parametrize("rows,date,outcome", [
    ([row("09/19/2026", RECEIPT_LINK)], "2026-09-12", "its row is not on the page"),
    ([row("09/19/2026", RECEIPT_LINK), row("09/19/2026", RECEIPT_LINK)], "2026-09-19",
     "more than one row fits it"),
    ([row("09/19/2026", EMAIL_ONLY)], "2026-09-19", "no receipt control on its row"),
    ([row("09/19/2026", NOTHING_LINK)], "2026-09-19", "the press gave no pdf"),
], ids=["not on the page", "more than one row", "no receipt control", "no pdf"])
def test_the_press_says_why_it_took_nothing(browser_ctx, monkeypatch, rows, date, outcome):
    monkeypatch.setattr(site, "ROW_LOOKS", 1, raising=False)
    body, facts = pressed_on(browser_ctx, rows, date)
    assert body is None
    assert facts.get("outcome") == outcome, facts
    if outcome in ("its row is not on the page", "more than one row fits it"):
        # and how many rows its last look counted, for the wait that follows
        assert facts.get("rows") == len(rows) and facts.get("since"), facts


def test_a_press_that_took_its_receipt_says_nothing_of_the_kind(browser_ctx):
    body, facts = pressed_on(browser_ctx, [row("09/19/2026", RECEIPT_LINK)], "2026-09-19")
    assert body and b"invented receipt" in body
    assert facts == {}


# -- what the run says of each -----------------------------------------------------------

@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield


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


class _Page:
    """The orders page, as far as the steps around the press are concerned.
    Its rows are never read here, so a row that is not on it is not said to
    have dropped off the list."""
    url = ORDERS

    def title(self):
        return "Your Orders"

    def locator(self, sel):
        class _L:
            first = property(lambda s: s)

            def count(s):
                return 1

            def inner_text(s, timeout=0):
                return "Orders and Receipts"
        return _L()


@pytest.mark.parametrize("outcome,said", [
    ("its row is not on the page",
     "Its row is not on Meijer's In-Store Receipts tab, so nothing was pressed."),
    ("more than one row fits it",
     "More than one row on Meijer's In-Store Receipts tab fits this purchase, so none was pressed."),
    ("no receipt control on its row",
     "Its row on Meijer's In-Store Receipts tab has nothing that reads as its receipt, "
     "so nothing was pressed."),
    ("the press gave no pdf", "Pressing the receipt link on its row brought no PDF."),
], ids=["not on the page", "more than one row", "no receipt control", "no pdf"])
def test_each_is_said_as_what_happened(tmp_path, monkeypatch, capsys, outcome, said):
    monkeypatch.setattr(site, "goto_orders", lambda pg, page_no=1: None)
    monkeypatch.setattr(site, "show_list_for", lambda pg, t, wait_ms=None, or_none=False:
                        {"opened": True, "rows": 3})

    def press(pg, purchase, trace=None, facts=None):
        if facts is not None:
            facts["outcome"] = outcome
    monkeypatch.setattr(site, "press_row_receipt", press)
    app = _app(tmp_path)
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-08-21", order_number="pexample0821",
                 total="$47.18", items=[Item(name="400 Example Avenue")])
    assert app._save_receipt(_Page(), p) is False
    out = " ".join(capsys.readouterr().out.split())

    assert "%s The next run looks for it again." % said in out, out
    assert "No receipt or details link" not in out
    rec = app.progress.get(p.key)
    assert rec["state"] == "Failed" and said in rec["notes"], rec
    assert app._already_done(p) is False
    assert app.failures == [("find the receipt", outcome)]
    assert app.stats["failed"] == 1 and app.stats["manual_review"] == 0, app.stats
    assert app.order_csv.read_all() == [] and app.index_csv.read_all() == []
    attempts = json.loads((app.paths.diagnostics / "download-attempt.json")
                          .read_text(encoding="utf-8"))["attempts"]
    assert [a["outcome"] for a in attempts] == [outcome]


def drops_off(monkeypatch):
    """Every look finds the purchase's row missing from a list seen whole,
    on a page the browser shows, with no control but the tabs and the rows'
    own links, whose oldest row is from 2026-06-01, long enough before
    today. This run's discovery read the In-Store rows (_app)."""
    monkeypatch.setattr(site, "goto_orders", lambda pg, page_no=1: None)
    monkeypatch.setattr(site, "show_list_for", lambda pg, t, wait_ms=None, or_none=False:
                        {"opened": True, "rows": 3})

    def press(pg, purchase, trace=None, facts=None):
        if facts is not None:
            facts["outcome"] = "its row is not on the page"
    monkeypatch.setattr(site, "press_row_receipt", press)
    steady = {"rows": 3, "changed": False, "settled": True}
    monkeypatch.setattr(site, "settle_rows", lambda pg, t, wait_ms=None, seen=None: steady,
                        raising=False)
    monkeypatch.setattr(site, "scroll_to_end", lambda pg, t: steady, raising=False)
    monkeypatch.setattr(site, "page_visible", lambda pg: True, raising=False)
    monkeypatch.setattr(site, "listed_rows", lambda pg, t: {"rows": 3, "oldest": "2026-06-01"},
                        raising=False)
    monkeypatch.setattr(site, "more_controls", lambda pg: 0, raising=False)
    monkeypatch.setattr(mr, "_today", lambda: date(2028, 6, 1), raising=False)


def older_than_the_list(kind=IN_STORE):
    return Purchase(purchase_type=kind, purchase_date="2026-05-01", order_number="pexample0501",
                    total="$5.00", items=[Item(name="400 Example Avenue")])


def runs(app):
    """`app`, ready to run its purchases on the page _Page stands for."""
    app._kinds_read = frozenset({IN_STORE})
    app.page = lambda: _Page()
    app._journal = SimpleNamespace(op=lambda *a, **k: None, checkpoint=lambda *a, **k: None)
    return app


@pytest.mark.parametrize("kind,state", [(IN_STORE, "No Longer Listed"), (ONLINE, "Failed")],
                         ids=["a store receipt", "an online order"])
def test_only_a_store_receipt_is_said_to_have_dropped_off(tmp_path, monkeypatch, kind, state):
    """Both are older than every row their tab shows, once its rows have
    stopped changing. The Online tab may go on over later pages, which
    discovery reads and a row is never looked for on, so an online order
    older than every row of the first page can be on the next one. Its
    missing row stays a failure."""
    drops_off(monkeypatch)
    app = runs(_app(tmp_path))
    p = older_than_the_list(kind)
    assert app._save_receipt(_Page(), p) is False
    assert app.progress.get(p.key)["state"] == state


def test_rows_a_csv_refused_go_in_when_it_is_said_again(tmp_path, monkeypatch):
    """The Order History is open in another program, so it refuses the rows
    of a purchase said to have dropped off, and the run counts the purchase
    as failed. The next run says so again and writes its rows, once. The mark
    that says they are in used to be set before they went in, so after a
    refusal they never did (review)."""
    drops_off(monkeypatch)
    app = runs(_app(tmp_path))
    p = older_than_the_list()
    append = storage.CsvFile.append_rows
    refused = []

    def open_elsewhere_once(book, rows):
        if not refused:
            refused.append(book.path.name)
            raise PermissionError(13, "The file is open in another program")
        return append(book, rows)
    monkeypatch.setattr(storage.CsvFile, "append_rows", open_elsewhere_once)

    app.process_purchases([p])
    assert refused == ["Meijer Order History.csv"]
    assert app.progress.get(p.key)["state"] == "Failed"
    assert not app.progress.get(p.key).get(mr.UNLISTED_ROWS)
    assert app.order_csv.read_all() == [] and app.index_csv.read_all() == []

    app.process_purchases([p])
    assert app.progress.get(p.key)["state"] == "No Longer Listed"
    for book in (app.order_csv, app.index_csv):
        assert [r["Order or Receipt Number"] for r in book.read_all()] == [p.order_number]


def test_a_receipt_saved_before_is_never_said_to_have_dropped_off(tmp_path, monkeypatch):
    """Download again, --redownload to the app, looks again for a purchase
    whose receipt was saved. Its row has gone from the list, which says
    nothing about the receipt saved, so the purchase is not written down as
    no longer listed and no rows go into the CSVs, and the rows it has stay
    as they are (review)."""
    drops_off(monkeypatch)
    app = runs(_app(tmp_path))
    app.args.redownload = True
    p = older_than_the_list()
    app.progress.update(p.key, {"state": "Completed", "downloaded_ok": True})
    saved = {"Purchase Date": p.purchase_date, "Purchase Type": IN_STORE,
             "Order or Receipt Number": p.order_number,
             "PDF Filename": "2026-05-01 Meijer Mixed Purchases Receipt.pdf",
             "Receipt Status": "Downloaded", "Processing Status": "Completed"}
    app.order_csv.append_rows([saved])
    app.index_csv.append_rows([saved])
    before = (app.order_csv.read_all(), app.index_csv.read_all())

    app.process_purchases([p])
    rec = app.progress.get(p.key)
    assert rec["state"] == "Failed" and rec["downloaded_ok"] is True, rec
    assert not rec.get(mr.UNLISTED_ROWS)
    assert (app.order_csv.read_all(), app.index_csv.read_all()) == before
    app.args.redownload = False
    assert app._already_done(p) is True
