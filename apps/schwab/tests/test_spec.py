"""Synthetic fixtures for provider parsing, filing and control checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-07-31", "Brokerage Statement - Example IRA (...1234)", "") == \
        "2026-07-31 Charles Schwab Brokerage Statement - Example IRA (...1234).pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "Charles Schwab Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Letters', 'Logs', 'Manual Review',
                    'Statements', 'Tax Documents', 'Trade Confirmations']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()


def test_trade_confirmations_are_filed_apart_from_statements(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.folder_for(storage.CONFIRM) != paths.folder_for(storage.STATEMENT)
    assert paths.folder_for(storage.CONFIRM).name == "Trade Confirmations"


def test_the_orchestrator_imports():
    import importlib
    here = Path(__file__).resolve().parents[1]
    entry = next(p for p in list(here.glob("*_docs.py")) + list(here.glob("*_receipts.py")))
    module = importlib.import_module(entry.stem)
    assert hasattr(module, "main")
    assert hasattr(module, "App")
