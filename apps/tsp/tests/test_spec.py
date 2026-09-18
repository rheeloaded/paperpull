"""Locks in the facts that must not drift once an archive exists."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") == \
        "2026-01-02 TSP Thing Statement.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "TSP Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ["Backups", "Diagnostics", "Logs", "Manual Review",
                    "Statements", "Tax Documents"]


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()


def test_the_orchestrator_imports():
    import importlib
    module = importlib.import_module("tsp_docs")
    assert hasattr(module, "main") and hasattr(module, "App")
