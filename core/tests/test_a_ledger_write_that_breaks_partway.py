"""A ledger's write that fails after the file opened writes no row twice,
and a Mac, Linux or PaperPull Server is not told a file it may not write is
open in Excel.

An append that failed was taken as a file another program holds, and its
rows were kept beside the ledger and written in at the next chance. A write
that broke after the file opened, a disk that filled or a shared folder that
dropped, could have put some of them in already, and an order history, which
holds no row once, then held them twice. On a Mac, Linux and the Server a
PermissionError is a file or folder the run may not write, which the run
waited a minute for and said was open in another program, perhaps Excel (a
review of 2026-11-15). Every value is invented.
"""
import csv

import pytest

from paperpull_core import shared_folder, storage

COLUMNS = ["Order", "Item"]


def items(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r["Item"] for r in csv.DictReader(f)]


def row(item):
    return {"Order": "111-2223334", "Item": item}


@pytest.mark.parametrize("once", [False, True], ids=["order history", "index"])
def test_a_write_that_breaks_after_a_row_writes_no_row_twice(tmp_path, monkeypatch, once):
    ledger = storage.CsvFile(tmp_path / "Testco Order History.csv", COLUMNS, once=once)
    ledger.append_rows([row("Garden Hose")])
    real = csv.DictWriter.writerow
    broke = []

    def writerow(self, stored):
        if stored.get("Item") == "Paint" and not broke:
            broke.append(True)
            raise OSError(28, "No space left on device")
        return real(self, stored)

    monkeypatch.setattr(csv.DictWriter, "writerow", writerow)
    ledger.append_rows([row("Rake"), row("Paint")])
    assert broke
    assert items(ledger.path) == ["Garden Hose", "Rake"], "the row before the break is in"
    assert ledger.waiting_path.exists()
    ledger.append_rows([row("Shovel")])
    assert items(ledger.path) == ["Garden Hose", "Rake", "Paint", "Shovel"]
    assert not ledger.waiting_path.exists()


def test_a_write_that_breaks_before_any_row_writes_each_once(tmp_path, monkeypatch):
    ledger = storage.CsvFile(tmp_path / "Testco Order History.csv", COLUMNS)
    ledger.append_rows([row("Garden Hose")])
    real = csv.DictWriter.writerow
    broke = []

    def writerow(self, stored):
        if not broke and stored.get("Item") == "Rake":
            broke.append(True)
            raise OSError(28, "No space left on device")
        return real(self, stored)

    monkeypatch.setattr(csv.DictWriter, "writerow", writerow)
    ledger.append_rows([row("Rake"), row("Paint")])
    assert items(ledger.path) == ["Garden Hose"]
    ledger.append_rows([])
    assert items(ledger.path) == ["Garden Hose", "Rake", "Paint"]


def refusing_appends(monkeypatch, error):
    real = shared_folder.open_to_write
    refused = []

    def open_to_write(path, mode="w", *a, **k):
        if mode == "a":
            refused.append(path)
            raise error
        return real(path, mode, *a, **k)

    monkeypatch.setattr(storage.shared_folder, "open_to_write", open_to_write)
    return real, refused


def test_on_a_mac_or_linux_a_permission_is_not_said_to_be_excel(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "_PERMISSION_IS_HELD", False, raising=False)
    slept = []
    monkeypatch.setattr(storage.time, "sleep", slept.append)
    ledger = storage.CsvFile(tmp_path / "Testco Document Index.csv", COLUMNS)
    ledger.append_rows([row("Garden Hose")])
    real, refused = refusing_appends(
        monkeypatch, PermissionError(13, "Permission denied", str(ledger.path)))
    ledger.append_rows([row("Rake")])
    said = capsys.readouterr().out
    assert refused and slept == [], "a permission no wait mends was waited for"
    assert "Excel" not in said and "another program" not in said, said
    assert "could not be written (PermissionError)" in said and "once it can be written" in said
    monkeypatch.setattr(storage.shared_folder, "open_to_write", real)
    ledger.append_rows([])
    assert items(ledger.path) == ["Garden Hose", "Rake"]


def test_on_windows_a_permission_is_still_a_file_held(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(storage, "_PERMISSION_IS_HELD", True, raising=False)
    slept = []
    monkeypatch.setattr(storage.time, "sleep", slept.append)
    ledger = storage.CsvFile(tmp_path / "Testco Document Index 2.csv", COLUMNS)
    ledger.append_rows([row("Garden Hose")])
    refusing_appends(monkeypatch, PermissionError(13, "Permission denied", str(ledger.path)))
    ledger.append_rows([row("Rake")])
    said = capsys.readouterr().out
    assert slept, "a file Excel holds is waited for"
    assert "perhaps Excel" in said and "once that file is closed" in said, said
