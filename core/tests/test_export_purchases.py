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
    assert r["sources"] == [] and r["purchases"] == 0
    assert xp.main(["--root", str(tmp_path), "--csv"]) == 1


def test_the_cli_writes_beside_the_installs(root, capsys):
    assert xp.main(["--root", str(root), "--csv"]) == 0
    out = capsys.readouterr().out
    assert "6 purchases across 5 orders" in out
    assert (root / "All Purchases.csv").is_file()


def test_the_panel_does_not_send_a_path_to_reveal():
    """Reveal opens only the file the server itself wrote."""
    gui = Path(__file__).resolve().parents[2] / "gui" / "app.py"
    src = gui.read_text(encoding="utf-8")
    assert "def api_export_reveal():" in src
    assert "fetch('/api/export/reveal', {method: 'POST'})" in src


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
