"""CSV writing: BOM for Excel, quoting, append, rewrite with backup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import CsvFile, ORDER_HISTORY_COLUMNS, RECEIPT_INDEX_COLUMNS


def test_header_and_bom(tmp_path):
    f = CsvFile(tmp_path / "t.csv", ORDER_HISTORY_COLUMNS)
    f.append_rows([{"Purchase Date": "2024-01-01", "Purchase Type": "Online"}])
    raw = (tmp_path / "t.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    text = raw.decode("utf-8-sig")
    assert text.splitlines()[0].split(",")[0] == "Account Holder"


def test_quoting_of_commas_and_quotes(tmp_path):
    f = CsvFile(tmp_path / "t.csv", ORDER_HISTORY_COLUMNS)
    f.append_rows([{"Item Name": 'Widget, 12" deluxe, "special"', "Notes": "a,b"}])
    rows = f.read_all()
    assert rows[0]["Item Name"] == 'Widget, 12" deluxe, "special"'
    assert rows[0]["Notes"] == "a,b"


def test_append_preserves_existing(tmp_path):
    f = CsvFile(tmp_path / "t.csv", RECEIPT_INDEX_COLUMNS)
    f.append_rows([{"Order or Receipt Number": "1"}])
    f.append_rows([{"Order or Receipt Number": "2"}])
    rows = f.read_all()
    assert [r["Order or Receipt Number"] for r in rows] == ["1", "2"]


def test_missing_columns_blank_not_invented(tmp_path):
    f = CsvFile(tmp_path / "t.csv", ORDER_HISTORY_COLUMNS)
    f.append_rows([{"Purchase Date": "2024-01-01"}])
    row = f.read_all()[0]
    assert row["Unit Price"] == ""
    assert row["Order Total"] == ""


def test_rewrite_backs_up_and_replaces(tmp_path):
    backups = tmp_path / "Backups"
    f = CsvFile(tmp_path / "t.csv", RECEIPT_INDEX_COLUMNS, backups)
    f.append_rows([{"Order or Receipt Number": "1", "Purchase Summary": "Old"}])
    rows = f.read_all()
    rows[0]["Purchase Summary"] = "New"
    f.rewrite(rows)
    assert f.read_all()[0]["Purchase Summary"] == "New"
    assert list(backups.glob("t.*.bak"))
    # BOM survives rewrite
    assert (tmp_path / "t.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_unicode_roundtrip(tmp_path):
    f = CsvFile(tmp_path / "t.csv", ORDER_HISTORY_COLUMNS)
    f.append_rows([{"Item Name": "Café Crème – 12oz ☕"}])
    assert f.read_all()[0]["Item Name"] == "Café Crème – 12oz ☕"
