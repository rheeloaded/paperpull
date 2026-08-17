"""Locks in the facts that must not drift, plus a startup smoke check."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") ==         "2026-01-02 T-Mobile Thing Statement.pdf"


def test_csv_filename_is_unchanged(tmp_path):
    assert storage.Paths(tmp_path).document_index_csv.name == "T-Mobile Document Index.csv"


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
