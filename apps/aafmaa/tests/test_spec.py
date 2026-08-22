"""Locks in the facts that must not drift once an archive exists.

A renamed CSV orphans the index, a moved folder hides the documents, and a
different provider string renames every new PDF. None of these may change
quietly after the first real run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") ==         "2026-01-02 AAFMAA Thing Statement.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "AAFMAA Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    # No Year-End Summaries: routed, but not precreated until an annual
    # statement has actually been seen.
    assert made == ['Backups', 'Diagnostics', 'Insurance Documents', 'Logs', 'Manual Review', 'Statements', 'Tax Documents']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()

def test_the_orchestrator_imports():
    """Catches a core that is installed but too old for this app.

    The unit tests exercise storage and the site layer directly, so a missing
    module in the orchestrator's own imports slipped past them once - the
    install had a core predating paperpull_core.browser and every command
    died on startup while the tests stayed green.
    """
    import importlib
    here = Path(__file__).resolve().parents[1]
    entry = next(p for p in list(here.glob("*_docs.py")) + list(here.glob("*_receipts.py")))
    module = importlib.import_module(entry.stem)
    assert hasattr(module, "main")
    assert hasattr(module, "App")
