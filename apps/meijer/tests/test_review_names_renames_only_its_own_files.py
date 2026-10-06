"""Review Names renames only receipts the app holds (review of 0.43.0).

It offered every row of the index marked Low or Review, and a row written
for a purchase with no receipt file has an empty path. An empty path reads
as the folder the app runs in, which exists, so a new summary typed for
such a row had the app rename its own folder. On Windows that stopped with
a traceback, after the renames before it were on disk and in progress.json,
while the CSVs, written only at the end, were left as they were. Every run
of 0.43.0 that could not press a purchase's row wrote a row like that, and
one path still writes them.

Here the app runs Review Names from its own command, on an index made the
way those runs made it, with the typing stood in for. Every date, store and
amount is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import meijer_receipts as app_mod
from paperpull_core import storage as core_storage

GROCERIES = "2026-05-20 Meijer Groceries Receipt.pdf"


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield


def config_for(folder, output_dir=None):
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": output_dir or str(folder / "out"),
        "profile_dir": str(folder / "profile"), "cdp_url": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def index_row(number, date, path, status="Review Needed", receipt="Downloaded"):
    return {"Purchase Date": date, "Purchase Type": "In-Store",
            "Order or Receipt Number": number, "Order Total": "$12.34",
            "Purchase Summary": "Mixed Purchases",
            "PDF Filename": Path(path).name if path else "",
            "PDF Full Path": str(path) if path else "", "Document Type": "Receipt",
            "Receipt Status": receipt, "Classification Confidence": "Low",
            "Processing Status": status, "Notes": ""}


def order_row(number, date, pdf_name):
    return {"Purchase Date": date, "Purchase Type": "In-Store",
            "Order or Receipt Number": number, "Item Name": "400 Example Avenue",
            "Order Total": "$12.34", "Purchase Summary": "Mixed Purchases",
            "PDF Filename": pdf_name, "Processing Status": "Review Needed"}


def receipt_at(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.4\n% invented receipt\n%%EOF\n")
    return path


def books(folder):
    out = folder / "out"
    out.mkdir(parents=True, exist_ok=True)
    return (storage.CsvFile(out / "Meijer Receipt Index.csv", storage.RECEIPT_INDEX_COLUMNS),
            storage.CsvFile(out / "Meijer Order History.csv", storage.ORDER_HISTORY_COLUMNS))


def review(folder, monkeypatch, answers, output_dir=None):
    """Review Names, answering each question in turn, as the app's own
    command, with its config in `folder`."""
    said = iter(answers)

    def answer(prompt):
        reply = next(said)
        if isinstance(reply, BaseException):
            raise reply
        return reply
    monkeypatch.setattr(app_mod, "ask", answer)
    cfg = config_for(folder, output_dir)
    assert app_mod.main(["--review-names", "--config", str(cfg)]) == 0


def test_a_row_with_no_file_of_its_own_is_never_offered(tmp_path, monkeypatch, capsys):
    """One row as 0.43.0 wrote it for a purchase whose row it could not
    press, with no path at all, and one naming a file outside the app's
    folder. Neither is offered, and nothing is renamed, the folder the app
    runs in least of all."""
    here = tmp_path / "here"
    here.mkdir()
    monkeypatch.chdir(here)
    elsewhere = receipt_at(tmp_path / "elsewhere", "2026-05-04 Meijer Mixed Purchases Receipt.pdf")
    index, history = books(tmp_path)
    index.append_rows([
        index_row("pexample0512", "2026-05-12", "", status="Needs Manual Review",
                  receipt="No receipt link on the row"),
        index_row("pexample0504", "2026-05-04", elsewhere)])
    history.append_rows([order_row("pexample0512", "2026-05-12", "")])
    before = index.read_all()

    review(tmp_path, monkeypatch, ["Groceries"] * 4)

    assert "No receipts need name review." in " ".join(capsys.readouterr().out.split())
    assert here.is_dir() and elsewhere.is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json", "elsewhere", "here", "out"]
    assert index.read_all() == before


def test_with_the_output_folder_where_it_runs_only_its_own_receipts_are_offered(
        tmp_path, monkeypatch, capsys):
    """With the output folder set to ".", the folder the app runs in is the
    output folder. Rows a damaged index might hold name the app's own
    config.json, a PDF in Diagnostics, one loose in the folder, and the
    desktop.ini Windows can leave in a folder of receipts. None of them is a
    PDF the app filed in Online, In-Store or Manual Review, so none is
    offered and each keeps its name. A receipt in In-Store still is
    (review)."""
    monkeypatch.chdir(tmp_path)
    cfg = config_for(tmp_path, ".")
    diagnosed = receipt_at(tmp_path / "Diagnostics", "2026-05-12 Meijer Mixed Purchases Receipt.pdf")
    loose = receipt_at(tmp_path, "2026-05-04 Meijer Mixed Purchases Receipt.pdf")
    held = receipt_at(tmp_path / "In-Store", "2026-05-20 Meijer Mixed Purchases Receipt.pdf")
    ini = tmp_path / "In-Store" / "desktop.ini"
    ini.write_text("[.ShellClassInfo]\n", encoding="utf-8")
    index = storage.CsvFile(tmp_path / "Meijer Receipt Index.csv", storage.RECEIPT_INDEX_COLUMNS)
    index.append_rows([index_row("pexample0601", "2026-06-01", cfg),
                       index_row("pexample0512", "2026-05-12", diagnosed),
                       index_row("pexample0504", "2026-05-04", loose),
                       index_row("pexample0527", "2026-05-27", ini),
                       index_row("pexample0520", "2026-05-20", held)])

    review(tmp_path, monkeypatch, ["Groceries"] * 5, output_dir=".")

    out = " ".join(capsys.readouterr().out.split())
    assert "1 receipt(s) need review." in out, out
    assert cfg.is_file() and diagnosed.is_file() and loose.is_file() and ini.is_file()
    assert (tmp_path / "In-Store" / GROCERIES).is_file() and not held.exists()
    assert [r["PDF Filename"] for r in index.read_all()] == [
        "config.json", diagnosed.name, loose.name, "desktop.ini", GROCERIES]


def test_a_rename_that_fails_leaves_the_csvs_as_the_files_are(tmp_path, monkeypatch, capsys):
    """The second file cannot be renamed. The first is renamed on disk and
    in both CSVs, the second keeps its name in both, and the review says
    so rather than stopping with a traceback."""
    store = tmp_path / "out" / "In-Store"
    first = receipt_at(store, "2026-05-20 Meijer Mixed Purchases Receipt.pdf")
    second = receipt_at(store, "2026-05-04 Meijer Mixed Purchases Receipt.pdf")
    index, history = books(tmp_path)
    index.append_rows([index_row("pexample0520", "2026-05-20", first),
                       index_row("pexample0504", "2026-05-04", second)])
    history.append_rows([order_row("pexample0520", "2026-05-20", first.name),
                         order_row("pexample0504", "2026-05-04", second.name)])
    real = Path.rename

    def rename(self, target):
        if self.name == second.name:
            raise PermissionError(13, "The file is open in another program")
        return real(self, target)
    monkeypatch.setattr(Path, "rename", rename)

    review(tmp_path, monkeypatch, ["Groceries", "Hardware"])

    out = " ".join(capsys.readouterr().out.split())
    assert "It could not be renamed (PermissionError), so it keeps its name." in out, out
    assert (store / GROCERIES).is_file() and second.is_file() and not first.exists()
    assert [r["PDF Filename"] for r in index.read_all()] == [GROCERIES, second.name]
    assert [r["PDF Filename"] for r in history.read_all()] == [GROCERIES, second.name]


def test_a_review_cut_short_still_writes_down_what_it_renamed(tmp_path, monkeypatch):
    """The console goes away after the first rename. The CSVs name the
    first file as it now is."""
    store = tmp_path / "out" / "In-Store"
    first = receipt_at(store, "2026-05-20 Meijer Mixed Purchases Receipt.pdf")
    second = receipt_at(store, "2026-05-04 Meijer Mixed Purchases Receipt.pdf")
    index, history = books(tmp_path)
    index.append_rows([index_row("pexample0520", "2026-05-20", first),
                       index_row("pexample0504", "2026-05-04", second)])
    history.append_rows([order_row("pexample0520", "2026-05-20", first.name)])

    with pytest.raises(SystemExit):
        review(tmp_path, monkeypatch, ["Groceries", SystemExit(3)])

    assert (store / GROCERIES).is_file()
    assert [r["PDF Filename"] for r in index.read_all()] == [GROCERIES, second.name]
    assert [r["PDF Filename"] for r in history.read_all()] == [GROCERIES]
