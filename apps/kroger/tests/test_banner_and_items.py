"""Kroger #41, from the tester's Diagnose file of 2026-09-22.

His receipt page names the store in its header, Metro Market, one of the
banners Kroger trades under, and he asked for that in his file names. The
app had put the purchase type there instead, "In-Store", so a {store} part
of a name pattern said nothing. And the Order Summary's "Original Item
Total" and "Order Total" were read as items, since they print the way an
item does, a label and then its amount on the next line.

The receipt below has his receipt's shape. Every item, number and address
in it is invented."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import kroger_receipts as kr
import kroger_site as site
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, Purchase, State

HEADER = ["Print", "Order Type: In Store", "Order Date: Sep. 20, 2026",
          "Order Number: 540~00123~2026-09-20~101~1234567", "Loyalty Card (last 4): 12345"]
STORE = ["Metro Market", "100 Example Rd", "Anytown, WI 53000 USA"]
BODY = ["Rewards", "Total Savings: $2.50", "Order Summary",
        "Original Item Total", "$23.46", "Item Coupons/Sales", "-$2.50",
        "Sales Tax", "+$0.52", "Order Total", "$21.48",
        "Item Details", "6 Items",
        "Kroger Tortilla Chips, 13 oz", "$2.49", "1 x $2.49 each", "UPC: 0001111000111",
        "Invented Cold Brew Coffee, 32 oz", "$6.49", "1 x $6.49 $8.99 each",
        "Item Coupon/Sale: -$2.50", "UPC: 0001111000222",
        "Deli Potato Salad", "$5.49", "0.62 lbs x $8.85 each (approx.)", "UPC: 0001111000333",
        "Invented Sparkling Water, 12 pk", "$6.99", "3 x $2.33 each", "UPC: 0001111000444",
        "Payment Details", "TERMINAL ID 101", "AMEX 1234", "$21.48",
        "Alcoholic beverages fulfilled from:", "Metro Market", "100 Example Rd",
        "Anytown, WI 53000 USA", "www.kroger.com"]
LINES = HEADER + STORE + BODY


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


# -- the items -------------------------------------------------------------------

def test_the_items_are_the_item_details_and_nothing_above_them():
    names = [i.name for i in site.items_from_lines(LINES)]
    assert names == ["Kroger Tortilla Chips, 13 oz", "Invented Cold Brew Coffee, 32 oz",
                     "Deli Potato Salad", "Invented Sparkling Water, 12 pk"]


def test_how_many_is_read_from_the_line_under_the_price():
    items = site.items_from_lines(LINES)
    assert [i.quantity for i in items] == ["1", "1", "1", "3"], "something weighed is one item"
    assert [i.unit_price for i in items] == ["$2.49", "$6.49", "$8.85", "$2.33"]
    assert [i.line_total for i in items] == ["$2.49", "$6.49", "$5.49", "$6.99"]


def test_a_receipt_without_an_item_details_heading_is_read_as_before():
    items = site.items_from_lines(["Bananas", "$1.29", "Milk 1 gal $3.49"])
    assert [i.name for i in items] == ["Bananas", "Milk 1 gal"]


# -- the store ---------------------------------------------------------------------

def test_the_store_is_the_banner_the_header_names():
    assert site.banner_from_lines(LINES) == "Metro Market"


def test_kroger_brand_items_are_never_taken_for_the_store():
    """Kroger's own brand is on the items, below the header."""
    lines = HEADER + ["100 Example Rd", "Anytown, WI 53000 USA"] + BODY
    assert site.banner_from_lines(lines) == ""


def test_a_store_this_app_does_not_list_is_taken_from_where_the_name_sits():
    lines = HEADER + ["Northside Grocers", "100 Example Rd", "Anytown, WI 53000 USA"] + BODY
    assert site.banner_from_lines(lines) == "Northside Grocers"


def test_a_banner_is_spelled_its_own_way():
    assert site.banner_of("KING SOOPERS") == "King Soopers"
    assert site.banner_of("Pick n Save") == "Pick 'n Save"
    assert site.banner_of("Kroger #123") == "Kroger"
    assert site.banner_of("Smith's Food & Drug") == "Smith's"
    assert site.banner_of("Fry's Food Stores") == "Fry's"
    assert site.banner_of("Anytown, WI 53000 USA") == ""
    assert site.banner_of("Kroger Tortilla Chips, 13 oz") == ""


def test_the_record_no_longer_calls_the_purchase_type_a_store():
    rec = {"createdDateTime": {"value": "2026-09-20T15:04:05Z"}, "handoffStoreId": "54000123",
           "total": "USD 21.48", "purchaseType": "IN_STORE",
           "receiptKey": "540~00123~2026-09-20~101~1234567",
           "lineItems": [{"upc": "0001111000111"}], "status": "COMPLETED"}
    p = site.record_to_purchase(rec)
    assert p.store_info == ""
    assert p.fulfillment == "In-Store"


# -- on a page, in a real browser ----------------------------------------------------

def _receipt_html():
    def rows(lines):
        return "".join("<div>%s</div>" % ln for ln in lines)
    labels = "".join("<span class='font-bold'>%s</span><br>" % ln for ln in HEADER[1:])
    return ("<!doctype html><html><head><meta charset='utf-8'></head><body>"
            "<div id='receipt-print-area' data-testid='POT-original-receipt'>"
            "<div data-testid='PO-invoice-header'><div><button>Print</button></div>"
            "<div><span>%s</span></div><div><span>%s</span></div></div>"
            "%s</div></body></html>" % (labels, "<br>".join(STORE), rows(BODY)))


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def test_a_receipt_page_gives_its_store_and_its_items(page):
    page.set_content(_receipt_html())
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20",
                 order_number="540~00123~2026-09-20~101~1234567", total="$21.48")
    p = site.extract_details(page, p)
    assert p.store_info == "Metro Market"
    assert [i.name for i in p.items][0] == "Kroger Tortilla Chips, 13 oz"
    assert len(p.items) == 4


# -- in a name, and for receipts already saved ------------------------------------------

PATTERN = "{date:yyyy-mm-dd} {store|provider} {summary}[ {kind}]"


def test_a_name_pattern_with_store_names_the_banner():
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20",
                 order_number="540~00123~2026-09-20~101~1234567", store_info="Metro Market")
    assert storage.build_pdf_filename("2026-09-20", "Groceries", "Receipt", record=p) == \
        "2026-09-20 Metro Market Groceries Receipt.pdf"
    p.store_info = ""
    assert storage.build_pdf_filename("2026-09-20", "Groceries", "Receipt", record=p) == \
        "2026-09-20 Kroger Groceries Receipt.pdf"


def _text_pdf(path: Path, lines) -> None:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (760 - 14 * i, line)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b" " * 4000)


def _app(tmp_path):
    app = object.__new__(kr.App)
    app.args = SimpleNamespace(apply=True, redownload=False)
    app.config = {"max_path_length": 240, "owner": "", "min_pdf_bytes": 1000}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.progress.data, app.progress._loaded = {}, True
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.discovery.data, app.discovery._loaded = {}, True
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.stats = {"mode": ""}
    return app


def test_receipts_saved_before_take_their_banner_at_rename(tmp_path, capsys):
    """His receipts were saved before the banner was read. Rename reads it
    off each saved PDF, asking nothing of Kroger, and a pattern with {store}
    then names them for it."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    old = folder / "2026-09-20 Kroger Groceries Receipt.pdf"
    _text_pdf(old, HEADER[1:] + ["Fred Meyer", "100 Example Rd"] + BODY[:3])
    number = "540~00123~2026-09-20~101~1234567"
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=number,
                 summary="Groceries", store_info="In-Store", pdf_filename=old.name,
                 pdf_path=str(old), state=State.COMPLETED.value)
    app.progress.update(p.key, dict(p.to_dict(), downloaded_ok=True))
    app.discovery.update(p.key, dict(p.to_dict()))
    app.index_csv.append_rows([{
        "Purchase Date": "2026-09-20", "Purchase Type": IN_STORE,
        "Order or Receipt Number": number, "Purchase Summary": "Groceries",
        "Document Type": "Receipt", "PDF Filename": old.name, "PDF Full Path": str(old),
        "Processing Status": "Completed"}])
    app.cmd_rename()
    assert "Read the store from 1 receipt" in capsys.readouterr().out
    assert sorted(f.name for f in folder.glob("*.pdf")) == ["2026-09-20 Fred Meyer Groceries Receipt.pdf"]
    assert app.progress.get(p.key)["store_info"] == "Fred Meyer"
    assert app.discovery.get(p.key)["store_info"] == "Fred Meyer"


def test_rename_reads_no_store_off_a_receipt_the_app_does_not_hold(tmp_path, capsys):
    """An index copied from another folder names a receipt there. Rename
    leaves its row alone and reads no store off it into its record."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path / "out")
    outside = tmp_path / "elsewhere" / "2026-09-20 Kroger Groceries Receipt.pdf"
    _text_pdf(outside, HEADER[1:] + ["Fred Meyer", "100 Example Rd"] + BODY[:3])
    number = "540~00123~2026-09-20~101~1234567"
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=number,
                 summary="Groceries", pdf_filename=outside.name, pdf_path=str(outside),
                 state=State.COMPLETED.value)
    app.progress.update(p.key, dict(p.to_dict(), downloaded_ok=True))
    app.index_csv.append_rows([{
        "Purchase Date": "2026-09-20", "Purchase Type": IN_STORE,
        "Order or Receipt Number": number, "Purchase Summary": "Groceries",
        "Document Type": "Receipt", "PDF Filename": outside.name,
        "PDF Full Path": str(outside), "Processing Status": "Completed"}])
    before = dict(app.progress.get(p.key))
    app.cmd_rename()
    out = " ".join(capsys.readouterr().out.split())
    assert "Read the store" not in out
    assert "1 row(s) of the index name something other than a PDF" in out
    assert app.progress.get(p.key) == before
    assert outside.is_file()


def test_the_purchase_list_never_brings_the_type_back_as_the_store(tmp_path):
    app = _app(tmp_path)
    app.progress.update("In-Store:a", {"store_info": "Fred Meyer", "store_read": True})
    app.discovery.update("In-Store:a", {"store_info": "In-Store"})
    assert app._store_kept("In-Store:a") == "Fred Meyer"
    app.discovery.update("In-Store:b", {"store_info": "Fuel Center"})
    assert app._store_kept("In-Store:b") == ""
    # and what 0.40 wrote with no purchase type, or a type title-cased, is not a store
    app.progress.update("In-Store:c", {"store_info": "Kroger"})
    app.discovery.update("In-Store:d", {"store_info": "Ship To Store"})
    assert app._store_kept("In-Store:c") == "" and app._store_kept("In-Store:d") == ""


def test_a_product_whose_name_begins_like_a_summary_line_is_still_an_item():
    """Inside Item Details only a bare label is refused. A cereal called
    Total is something bought."""
    lines = ["Item Details", "2 Items", "Total Whole Grain Cereal, 16 oz", "$4.99",
             "1 x $4.99 each", "Balance Bar Chocolate, 1.76 oz", "$1.25", "1 x $1.25 each",
             "Payment Details"]
    assert [i.name for i in site.items_from_lines(lines)] == [
        "Total Whole Grain Cereal, 16 oz", "Balance Bar Chocolate, 1.76 oz"]


def test_rename_takes_the_summary_lines_out_of_the_order_history(tmp_path, capsys):
    """Earlier runs wrote Original Item Total and Order Total into the order
    history as items, and the Purchases workbook is rebuilt from it."""
    app = _app(tmp_path)
    number = "540~00123~2026-09-20~101~1234567"
    app.order_csv.append_rows([
        {"Purchase Date": "2026-09-20", "Order or Receipt Number": number, "Item Name": name}
        for name in ("Original Item Total", "Order Total", "Kroger Tortilla Chips, 13 oz",
                     "Total Whole Grain Cereal, 16 oz")])
    app.cmd_rename()
    assert "Took 2 Order Summary line" in capsys.readouterr().out
    assert [r["Item Name"] for r in app.order_csv.read_all()] == [
        "Kroger Tortilla Chips, 13 oz", "Total Whole Grain Cereal, 16 oz"]
    app.cmd_rename()
    assert "Order Summary" not in capsys.readouterr().out, "nothing left to take out"


def test_a_rename_preview_changes_nothing(tmp_path, capsys):
    """Preview first, then apply. The preview shows the banner names and
    leaves the files, the records and the order history as they were."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    app.args.apply = False
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    old = folder / "2026-09-20 Kroger Groceries Receipt.pdf"
    _text_pdf(old, HEADER[1:] + ["Fred Meyer", "100 Example Rd"] + BODY[:3])
    number = "540~00123~2026-09-20~101~1234567"
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=number,
                 summary="Groceries", store_info="In-Store", pdf_filename=old.name,
                 pdf_path=str(old), state=State.COMPLETED.value)
    app.progress.update(p.key, dict(p.to_dict(), downloaded_ok=True))
    app.discovery.update(p.key, dict(p.to_dict()))
    app.index_csv.append_rows([{
        "Purchase Date": "2026-09-20", "Purchase Type": IN_STORE,
        "Order or Receipt Number": number, "Purchase Summary": "Groceries",
        "Document Type": "Receipt", "PDF Filename": old.name, "PDF Full Path": str(old),
        "Processing Status": "Completed"}])
    app.order_csv.append_rows([{"Order or Receipt Number": number, "Item Name": name}
                               for name in ("Order Total", "Kroger Tortilla Chips, 13 oz")])
    app.cmd_rename()
    out = capsys.readouterr().out
    assert "2026-09-20 Fred Meyer Groceries Receipt.pdf" in out
    assert "would be taken out" in out
    assert sorted(f.name for f in folder.glob("*.pdf")) == [old.name]
    assert app.progress.get(p.key)["store_info"] == "In-Store"
    assert app.discovery.get(p.key)["store_info"] == "In-Store"
    assert len(app.order_csv.read_all()) == 2


def test_a_banner_run_together_with_the_order_lines_is_still_found():
    """A printed receipt lays the order's lines and the store side by side,
    and a PDF's text can run them onto one line."""
    lines = ["Order Type: In Store Metro Market", "Order Date: Sep. 20, 2026 100 Example Rd",
             "Loyalty Card (last 4): 12345 Anytown, WI 53000 USA"] + BODY
    assert site.banner_from_lines(lines) == "Metro Market"
    lines = ["Order Type: In Store Fry's Food Stores", "Order Number: 1"] + BODY
    assert site.banner_from_lines(lines) == "Fry's"
    # and never from the items below the header
    assert site.banner_from_lines(["Order Type: In Store"] + BODY) == ""
