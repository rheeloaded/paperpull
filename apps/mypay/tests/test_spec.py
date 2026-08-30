"""Locks in the facts that must not drift when this app moves onto the core.

Every expected value here was taken from the app's own code as it was BEFORE
the shared-core migration. If any of them changed, an existing archive would
be stranded: a renamed CSV orphans the index, a moved folder hides the
documents, and a different provider string renames every new PDF.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") ==         "2026-01-02 DFAS myPay Thing Statement.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "DFAS myPay Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Logs', 'Manual Review', 'Statements', 'Tax Documents']


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
