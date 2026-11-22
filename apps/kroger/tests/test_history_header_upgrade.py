"""Kroger's order history gains Pricing Quantity and Pricing Unit (#247), and
a history with the 0.70.0 header is upgraded before anything goes into it,
with the repairs of the review. Invented rows only.

Each case is one a history meets on a real machine. Rows kept beside the
file while Excel held it, a write of them that stopped part way, Excel
holding the file during the upgrade, a file saved again from Excel in the
code page of Windows or with empty columns on the end, and Rename, which
reads the history and writes it again.
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import storage  # noqa: E402

NEW = storage.ORDER_HISTORY_COLUMNS
OLD = [c for c in NEW if c not in storage.PRICING_COLUMNS]


def _old_row(n, item="Example item"):
    return {c: "" for c in OLD} | {"Order or Receipt Number": "k%d" % n, "Item Name": item,
                                   "Quantity": "1", "Unit Price": "$2.00"}


def _write_old(path, rows, encoding="utf-8-sig", header=OLD):
    with path.open("w", encoding=encoding, newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(c, "") for c in OLD])


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == NEW
        return list(reader)


def _ledger(tmp_path):
    return storage.PricingCsvFile(tmp_path / "Kroger Order History.csv", NEW, tmp_path / "Backups")


def test_the_upgrade_keeps_every_value_and_backs_up_the_file_once(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1, "=Example, with a comma"), _old_row(2)])
    original = ledger.path.read_bytes()
    ledger.append_rows([{"Order or Receipt Number": "k3", "Quantity": "1",
                         "Pricing Quantity": "1.75", "Pricing Unit": "lb"}])
    ledger.append_rows([{"Order or Receipt Number": "k4", "Quantity": "2"}])
    rows = _rows(ledger.path)
    assert [r["Order or Receipt Number"] for r in rows] == ["k1", "k2", "k3", "k4"]
    assert rows[0]["Item Name"] == "'=Example, with a comma" or rows[0]["Item Name"].endswith(
        "=Example, with a comma")
    assert rows[0]["Unit Price"] == "$2.00" and rows[0]["Pricing Quantity"] == ""
    assert (rows[2]["Pricing Quantity"], rows[2]["Pricing Unit"]) == ("1.75", "lb")
    backups = list((tmp_path / "Backups").iterdir())
    assert [b.read_bytes() for b in backups] == [original]


def test_rows_kept_from_a_write_that_stopped_part_way_go_in_once(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)])
    began = ledger.path.stat().st_size
    b, c = _old_row(2), _old_row(3)
    with ledger.path.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow([b[k] for k in OLD])
    ledger._keep([{"id": "b" * 16, "row": b}, {"id": "c" * 16, "row": c}], writing_from=began)
    ledger.append_rows([{"Order or Receipt Number": "k4", "Quantity": "1"}])
    assert [r["Order or Receipt Number"] for r in _rows(ledger.path)] == ["k1", "k2", "k3", "k4"]
    assert not ledger.waiting_path.exists()


def test_excel_holding_the_file_keeps_the_row_and_the_next_run_upgrades(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)])
    original = ledger.path.read_bytes()

    def held(*args, **kwargs):
        raise PermissionError(13, "held by another program")
    monkeypatch.setattr(storage, "atomic_write_text", held)
    ledger.append_rows([{"Order or Receipt Number": "k2", "Quantity": "1",
                         "Pricing Quantity": "0.62", "Pricing Unit": "lb"}])
    assert ledger.path.read_bytes() == original, "never a row under the earlier header"
    assert ledger.waiting_path.exists()
    assert ledger.read_all()[-1]["Pricing Quantity"] == "0.62"
    assert ledger.path.read_bytes() == original
    monkeypatch.undo()
    ledger = _ledger(tmp_path)  # the next run
    ledger.append_rows([{"Order or Receipt Number": "k3", "Quantity": "1"}])
    rows = _rows(ledger.path)
    assert [(r["Order or Receipt Number"], r["Pricing Quantity"]) for r in rows] == [
        ("k1", ""), ("k2", "0.62"), ("k3", "")]


def test_a_file_saved_from_excel_in_the_windows_code_page_keeps_its_letters(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1, "Jalapeño Example")], encoding="cp1252")
    ledger.append_rows([{"Order or Receipt Number": "k2", "Quantity": "1"}])
    assert _rows(ledger.path)[0]["Item Name"] == "Jalapeño Example"


def test_empty_columns_excel_added_on_the_end_are_still_the_earlier_header(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)], header=OLD + ["", ""])
    ledger.append_rows([{"Order or Receipt Number": "k2", "Quantity": "1"}])
    assert [r["Order or Receipt Number"] for r in _rows(ledger.path)] == ["k1", "k2"]


def test_rename_reads_and_writes_the_history_under_the_new_header(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)])
    ledger._keep([{"id": "d" * 16, "row": _old_row(2)}])
    rows = ledger.read_all()
    assert [r["Order or Receipt Number"] for r in rows] == ["k1", "k2"]
    ledger.rewrite([dict(r, **{"PDF Filename": "renamed.pdf"}) for r in rows])
    assert [(r["Order or Receipt Number"], r["PDF Filename"]) for r in _rows(ledger.path)] == [
        ("k1", "renamed.pdf"), ("k2", "renamed.pdf")]


def test_a_new_history_is_written_with_the_new_header(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.append_rows([{"Order or Receipt Number": "k1", "Quantity": "1"}])
    assert [r["Order or Receipt Number"] for r in _rows(ledger.path)] == ["k1"]
    assert not (tmp_path / "Backups").exists()


@pytest.mark.parametrize("header", [NEW[:-1], list(reversed(OLD)), OLD + ["Extra"]])
def test_a_header_this_app_never_wrote_is_left_as_it_is(tmp_path, header, capsys):
    ledger = _ledger(tmp_path)
    with ledger.path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(header)
    original = ledger.path.read_bytes()
    ledger.append_rows([{"Order or Receipt Number": "k1", "Quantity": "1"}])
    assert ledger.path.read_bytes() == original
    assert ledger.waiting_path.exists()
    assert "never wrote" in capsys.readouterr().out


def test_excel_holding_the_file_costs_one_try_and_one_copy_a_run(tmp_path, monkeypatch, capsys):
    """Review M1. Every receipt of a run waited a minute and made a copy."""
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)])
    tries = []

    def held(*args, **kwargs):
        tries.append(1)
        raise PermissionError(13, "held by another program")
    monkeypatch.setattr(storage, "atomic_write_text", held)
    for n in (2, 3, 4):
        ledger.append_rows([{"Order or Receipt Number": "k%d" % n, "Quantity": "1"}])
    assert len(tries) == 1
    assert len(list((tmp_path / "Backups").iterdir())) == 1
    said = capsys.readouterr().out
    assert ledger.waiting_path.name in said.splitlines()[0]
    assert [r["Order or Receipt Number"] for r in ledger.read_all()] == ["k1", "k2", "k3", "k4"]


def test_a_file_of_both_encodings_keeps_every_letter(tmp_path):
    """Review m3. A file Excel saved in the code page of Windows, then rows
    0.70.0 appended in UTF-8, and a write cut short in half a character."""
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1, "Jalapeño Example")], encoding="cp1252")
    with ledger.path.open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow([_old_row(2, "Häagen Example").get(c, "") for c in OLD])
    with ledger.path.open("ab") as fh:
        fh.write(b"k3,\xc3")
    ledger.append_rows([{"Order or Receipt Number": "k4", "Quantity": "1"}])
    rows = _rows(ledger.path)
    assert [r["Item Name"] for r in rows[:2]] == ["Jalapeño Example", "Häagen Example"]
    assert rows[-1]["Order or Receipt Number"] == "k4"


def test_a_utf8_file_cut_in_half_a_character_is_still_upgraded(tmp_path):
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1, "Häagen Example")])
    with ledger.path.open("ab") as fh:
        fh.write(b"k2,\xc3")
    ledger.append_rows([{"Order or Receipt Number": "k3", "Quantity": "1"}])
    rows = _rows(ledger.path)
    assert rows[0]["Item Name"] == "Häagen Example" and rows[-1]["Order or Receipt Number"] == "k3"
    assert len(list((tmp_path / "Backups").iterdir())) == 1


def test_a_field_past_the_csv_limit_never_raises_into_the_download(tmp_path):
    """Review m4. The upgrade reads every row, which appending never did."""
    ledger = _ledger(tmp_path)
    _write_old(ledger.path, [_old_row(1)])
    original_size = ledger.path.stat().st_size
    with ledger.path.open("a", encoding="utf-8", newline="") as fh:
        fh.write('k2,"' + "x" * 200000 + "\r\n")
    original = ledger.path.read_bytes()
    ledger.append_rows([{"Order or Receipt Number": "k3", "Quantity": "1"}])
    assert ledger.path.read_bytes() == original and original_size < len(original)
    assert ledger.waiting_path.exists()
