"""The Purchases export reads a Meijer placeholder row again from its saved
receipt (#246), with the repairs of its review. Invented purchases only.

A placeholder is the order list's words priced at the receipt's total,
"In-Store:" or "Meijer order" before 0.70.0, and on 0.70.0 the store's
address line (#236). A row with no item is not one, and the receipt read is
a plain file in the history's own folder, asked about so it never raises.
"""
import csv
import importlib.util
import os
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "export_purchases.py"
spec = importlib.util.spec_from_file_location("export_meijer_recovery_tool", TOOL)
xp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xp)

from paperpull_core import meijer_items  # noqa: E402
from paperpull_core.models import Item  # noqa: E402

HEADER = ["Account Holder", "Purchase Date", "Purchase Type", "Order or Receipt Number",
          "Order Status", "Item Name", "Quantity", "Unit Price", "Line Item Total",
          "Order Total", "Fulfillment Method", "Return Status", "Purchase Summary",
          "PDF Filename", "Purchase Details URL", "Receipt URL", "Processing Status", "Notes"]


def _row(order, item, qty="1", unit="", line="$12.34", total="$12.34", ptype="In-Store",
         pdf="r.pdf", proc="Completed", notes="", date="2026-09-19", url=""):
    return ["", date, ptype, order, "Paid", item, qty, unit, line, total, "", "",
            "Groceries", pdf, "", url, proc, notes]


def _history(folder, rows):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "Meijer Order History.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    return p


def _receipt(folder, name="r.pdf", sub="In-Store"):
    where = folder / sub if sub else folder
    where.mkdir(parents=True, exist_ok=True)
    (where / name).write_bytes(b"%PDF-1.4 invented")
    return where / name


@pytest.fixture
def reads(monkeypatch):
    """Every receipt the export reads, answered with two invented products."""
    calls = []

    def read(path, date, total):
        calls.append(Path(path))
        return [Item(name="EXAMPLE BREAD", quantity="1", unit_price="$4.34", line_total="$4.34"),
                Item(name="EXAMPLE APPLES (2.00 lb)", quantity="", unit_price="$4.00",
                     line_total="$8.00", pricing_quantity="2.00", pricing_unit="lb")]
    monkeypatch.setattr(meijer_items, "read_items", read)
    return calls


def test_the_0_70_0_address_row_is_read_again_from_its_receipt(tmp_path, reads):
    folder = tmp_path / "Meijer Receipts"
    history = _history(folder, [_row("p1", "4400 Invented Avenue")])
    pdf = _receipt(folder)
    rows = xp.load_purchases("Meijer", history)
    assert [r["Item"] for r in rows] == ["EXAMPLE BREAD", "EXAMPLE APPLES (2.00 lb)"]
    assert reads == [pdf.resolve()]
    assert (rows[1]["Pricing Quantity"], rows[1]["Pricing Unit"], rows[1]["Unit Price"]) == (2, "lb", 4.0)
    assert all(r["Processing"] == "Review Needed" for r in rows)


def test_a_canceled_row_with_no_item_keeps_its_status_and_notes(tmp_path, reads):
    history = _history(tmp_path / "Meijer Receipts", [
        _row("p2", "", qty="", line="", pdf="", proc="Canceled",
             notes="Order canceled; no receipt downloaded")])
    rows = xp.load_purchases("Meijer", history)
    assert (rows[0]["Processing"], rows[0]["Notes"]) == (
        "Canceled", "Order canceled; no receipt downloaded")
    assert reads == []


def test_real_products_are_left_as_they_are(tmp_path, reads):
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [
        _row("p3", "EXAMPLE MILK", unit="$3.00", line="$3.00", total="$5.00"),
        _row("p3", "EXAMPLE EGGS", unit="$2.00", line="$2.00", total="$5.00"),
        _row("p4", "EXAMPLE ONE THING", unit="$5.00", line="$5.00", total="$5.00"),
        _row("p5", "EXAMPLE BUNDLE", qty="2", line="$5.00", total="$5.00"),
        _row("p6", "Example online order", ptype="Online"),
    ])
    rows = xp.load_purchases("Meijer", history)
    assert [r["Item"] for r in rows] == ["EXAMPLE MILK", "EXAMPLE EGGS", "EXAMPLE ONE THING",
                                         "EXAMPLE BUNDLE", "Example online order"]
    assert reads == []


def test_an_order_with_products_does_not_list_them_twice(tmp_path, reads):
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [
        _row("p7", "In-Store:"),
        _row("p7", "EXAMPLE BREAD", unit="$4.34", line="$4.34"),
        _row("p8", "Meijer order"),
        _row("p8", "Meijer order"),
    ])
    rows = xp.load_purchases("Meijer", history)
    assert reads == [(folder / "In-Store" / "r.pdf").resolve()], "p8 read once, p7 not at all"
    p7 = [r["Item"] for r in rows if r["Order Number"] == "p7"]
    p8 = [r["Item"] for r in rows if r["Order Number"] == "p8"]
    assert p7 == ["EXAMPLE BREAD"]
    assert p8 == ["EXAMPLE BREAD", "EXAMPLE APPLES (2.00 lb)"]


def test_a_0_70_0_address_row_beside_products_or_twice_is_no_product(tmp_path, reads):
    """Download again on this version writes products after the address row,
    and a redownload on 0.70.0 wrote the address row twice (review M2)."""
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [
        _row("p20", "4400 Invented Avenue", total="$5.00", line="$5.00"),
        _row("p20", "EXAMPLE BREAD", unit="$2.00", line="$2.00", total="$5.00"),
        _row("p20", "EXAMPLE MILK", unit="$3.00", line="$3.00", total="$5.00"),
        _row("p21", "4400 Invented Avenue"),
        _row("p21", "4400 Invented Avenue"),
    ])
    rows = xp.load_purchases("Meijer", history)
    p20 = [r["Item"] for r in rows if r["Order Number"] == "p20"]
    p21 = [r["Item"] for r in rows if r["Order Number"] == "p21"]
    assert p20 == ["EXAMPLE BREAD", "EXAMPLE MILK"]
    assert p21 == ["EXAMPLE BREAD", "EXAMPLE APPLES (2.00 lb)"]
    orders = {o["Order Number"]: o["Items"] for o in xp.orders_from(rows)}
    assert orders == {"p20": 2, "p21": 2}


def test_a_one_product_row_read_from_a_receipt_page_is_kept(tmp_path, reads):
    """A purchase with a receipt link was read from its page, whose one
    product looks like the address row (review m5)."""
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [_row("p22", "EXAMPLE WHOLE MILK GAL",
                                     url="https://www.meijer.com/receipt/p22")])
    rows = xp.load_purchases("Meijer", history)
    assert [(r["Item"], r["Line Total"], r["Processing"]) for r in rows] == [
        ("EXAMPLE WHOLE MILK GAL", 12.34, "Completed")]
    assert reads == []


def test_a_row_with_no_order_total_is_not_read(tmp_path, reads):
    """The reader checks the total only when it is given one."""
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [_row("p23", "In-Store:", total="")])
    rows = xp.load_purchases("Meijer", history)
    assert reads == []
    assert rows[0]["Item"] == ""


@pytest.mark.parametrize("name", ["../r.pdf", "In-Store/r.pdf", "..", "C:r.pdf", "/r.pdf",
                                  "\\\\server\\share\\r.pdf", "r\x00.pdf"])
def test_a_name_that_is_not_a_file_name_reads_nothing(tmp_path, reads, name):
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    _receipt(tmp_path, sub="")
    history = _history(folder, [_row("p9", "In-Store:", pdf=name)])
    rows = xp.load_purchases("Meijer", history)
    assert reads == []
    assert (rows[0]["Item"], rows[0]["Line Total"], rows[0]["Processing"]) == ("", None, "Review Needed")


def test_a_link_out_of_the_folder_is_never_read(tmp_path, reads):
    folder = tmp_path / "Meijer Receipts"
    outside = _receipt(tmp_path / "elsewhere", sub="")
    (folder / "In-Store").mkdir(parents=True)
    try:
        os.symlink(outside, folder / "In-Store" / "r.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("this machine makes no symbolic links")
    history = _history(folder, [_row("p10", "In-Store:")])
    rows = xp.load_purchases("Meijer", history)
    assert reads == []
    assert rows[0]["Item"] == ""


def test_a_folder_that_cannot_be_asked_about_counts_as_no_receipt(tmp_path, reads, monkeypatch):
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [_row("p11", "In-Store:")])

    def refused(self, *a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(Path, "is_file", refused)
    rows = xp.load_purchases("Meijer", history)
    assert reads == []
    assert rows[0]["Item"] == "" and rows[0]["Processing"] == "Review Needed"


def test_failed_recovery_keeps_the_row_s_own_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(meijer_items, "read_items", lambda *a: [])
    folder = tmp_path / "Meijer Receipts"
    _receipt(folder)
    history = _history(folder, [_row("p12", "In-Store:", notes="Validation: invented")])
    before = history.read_bytes()
    rows = xp.load_purchases("Meijer", history)
    assert rows[0]["Notes"].startswith("Validation: invented; ")
    assert rows[0]["Line Total"] is None and rows[0]["Order Total"] == 12.34
    assert history.read_bytes() == before


def test_other_providers_are_never_read_again(tmp_path, reads):
    folder = tmp_path / "Kroger Receipts"
    _receipt(folder)
    p = folder / "Kroger Order History.csv"
    _history(folder, [_row("k1", "In-Store:")]).rename(p)
    rows = xp.load_purchases("Kroger", p)
    assert rows[0]["Item"] == "In-Store:" and reads == []


def test_a_real_receipt_reads_end_to_end(tmp_path):
    """The real reader on a real PDF, no stand-in."""
    helper = Path(__file__).resolve().parents[2] / "apps" / "meijer" / "tests" / "test_round_five.py"
    text_pdf = _text_pdf_from(helper)
    folder = tmp_path / "Meijer Receipts"
    (folder / "In-Store").mkdir(parents=True)
    (folder / "In-Store" / "r.pdf").write_bytes(text_pdf([
        "09/19/26 Fastlane1", "GROCERY", "12345678901 EXAMPLE MILK 12.34 F",
        "mPerks # -- ********00", "TOTAL TOTAL TAX .00", "TOTAL 12.34",
        "PAYMENTS", "Tx:1 Op:2 Tm:3 St:4 12:00:00"]))
    history = _history(folder, [_row("p13", "4400 Invented Avenue")])
    rows = xp.load_purchases("Meijer", history)
    assert [(r["Item"], r["Line Total"]) for r in rows] == [("EXAMPLE MILK", 12.34)]


def _text_pdf_from(helper: Path):
    """test_round_five's PDF maker, without importing the Meijer app."""
    import ast
    tree = ast.parse(helper.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_text_pdf")
    space: dict = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(helper), "exec"), space)
    return space["_text_pdf"]


def test_a_junction_out_of_the_folder_is_never_read(tmp_path, reads):
    """Windows makes a junction with no privilege, so this one runs there."""
    winapi = pytest.importorskip("_winapi")
    folder = tmp_path / "Meijer Receipts"
    folder.mkdir()
    outside = _receipt(tmp_path / "elsewhere", sub="")
    winapi.CreateJunction(str(outside.parent), str(folder / "In-Store"))
    history = _history(folder, [_row("p14", "In-Store:")])
    rows = xp.load_purchases("Meijer", history)
    assert reads == []
    assert rows[0]["Item"] == ""
