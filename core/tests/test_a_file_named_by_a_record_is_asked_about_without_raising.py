"""Files a record, an index row or a listing names are asked about without
raising, beyond each app's _already_done.

Python 3.12's Path.is_file() and exists() raise for a file in a folder the
run may not search. Robinhood asked its records' tax forms and statements,
Amazon's Reparse items asked its index rows, and the transactions export
asked every statement it lists, each outside any try, so the run or the
export ended there (a bug hunt of 2026-11-14). Each asks
shared_folder.file_there now, which counts such a file as not there. The
refusal is stood in for at os.stat, as in
test_every_app_asks_of_a_review_copy_without_raising.py.
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import shared_folder, testkit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402
from test_every_app_asks_of_a_review_copy_without_raising import refuse_under  # noqa: E402


@pytest.fixture
def refused(tmp_path, monkeypatch):
    folder = tmp_path / "refused"
    folder.mkdir()
    pdf = folder / "2025-12-31 Robinhood 1099.pdf"
    pdf.write_bytes(testkit.sample_pdf())
    refuse_under(monkeypatch, folder)
    return pdf


def _home(name, tmp_path, monkeypatch, capsys):
    app_dir = next(d for d in census.APPS if d.name == name)
    return census.Home(app_dir, tmp_path, monkeypatch, capsys)


def test_a_file_that_cannot_be_asked_about_is_not_there(refused, tmp_path):
    assert shared_folder.file_there(refused) is False
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(b"%PDF-1.4")
    assert shared_folder.file_there(plain) is True and shared_folder.file_there(str(plain))
    for named in ("", None, 5, ["x"], tmp_path, "a\0b"):
        assert shared_folder.file_there(named) is False, named


def test_robinhood_asks_of_its_saved_forms_without_raising(refused, tmp_path, monkeypatch, capsys):
    home = _home("robinhood", tmp_path, monkeypatch, capsys)
    app = home.build()
    mod = home.mod
    rec = {"category": "Tax Document", "date": "2025-12-31", "title": "1099", "account": "",
           "state": "Completed", "downloaded_ok": True, "pdf_path": str(refused)}
    listed = [("Tax Document:2025-12-31:1099", {"date": "2025-12-31"})]
    assert mod.App._which_listed_form(rec, listed) is None
    for odd in (5, ["x"]):
        assert mod.App._which_listed_form(dict(rec, pdf_path=odd), listed) is None
    monkeypatch.setattr(app.progress, "data", {"k": rec}, raising=False)
    doc = SimpleNamespace(title="1099", account="", category="Tax Document", date="2025-12-31",
                          key="other")
    app._saved_form_of_year(doc, "2025")
    statement = dict(rec, category="Statement", account="...9999")
    monkeypatch.setattr(app.progress, "data", {"k": statement}, raising=False)
    app._other_accounts_statement(SimpleNamespace(date="2025-12-31", account="...1111",
                                                  key="mine", category="Statement"), "abc")


def test_rename_leaves_a_file_it_cannot_look_at(refused, tmp_path):
    """Rename and Move plan from the index's rows. A row naming a file in a
    folder Rename may not search ended the plan, and so every Rename and
    Move. The file is left as it is now and the others are planned."""
    from paperpull_core import renaming
    plain = tmp_path / "Statements" / "2025-11-30 Statement.pdf"
    plain.parent.mkdir()
    plain.write_bytes(testkit.sample_pdf())
    rows = [{"PDF Full Path": str(refused), "PDF Filename": refused.name},
            {"PDF Full Path": str(plain), "PDF Filename": plain.name}]
    changes = renaming.plan(rows, lambda r: "Renamed " + r["PDF Filename"], folders=[tmp_path])
    by = {c.row["PDF Filename"]: c for c in changes}
    assert not by[refused.name].renaming
    assert "could not be looked at" in by[refused.name].reason
    assert by[plain.name].renaming and by[plain.name].new_name == "Renamed " + plain.name


RECEIPT_APPS = [d for d in census.APPS if (d / ("%s_receipts.py" % d.name)).exists()]


@pytest.mark.parametrize("app_dir", RECEIPT_APPS, ids=[d.name for d in RECEIPT_APPS])
def test_a_pilot_report_reads_a_path_that_is_not_text_as_none(app_dir, tmp_path, monkeypatch,
                                                              capsys):
    """A receipt app's pilot report says whether each receipt's PDF is
    there. A path a hand edit left as a number raised TypeError there."""
    from test_every_app_asks_of_a_review_copy_without_raising import _Any
    app = census.Home(app_dir, tmp_path, monkeypatch, capsys).build()
    rec = {"state": "Completed", "pdf_filename": "x.pdf", "pdf_path": 5}
    monkeypatch.setattr(app.progress, "get", lambda key: rec)
    app._pilot_report([_Any()])
    assert re.search(r"PDF exists:?\s+False", capsys.readouterr().out)


def test_there_are_receipt_apps_to_ask():
    assert len(RECEIPT_APPS) == 14


def test_the_transactions_export_counts_a_statement_it_cannot_ask_about_as_missing(
        refused, tmp_path):
    import export_transactions
    root = tmp_path / "apps"
    install = root / "Testco Statements"
    install.mkdir(parents=True)
    (install / "Testco Document Index.csv").write_text(
        "Date,Document Type,Account,Filename,PDF Full Path\n"
        "2025-12-31,Statement,...1111,x.pdf,%s\n" % refused, encoding="utf-8")
    assert export_transactions.providers(root) == []
