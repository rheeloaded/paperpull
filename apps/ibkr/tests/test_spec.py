"""What the Interactive Brokers app files, and where. Everything here is synthetic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_in_the_file_name():
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-07-31", "Activity Statement - Account U1234567", "") == \
        "2026-07-31 Interactive Brokers Activity Statement - Account U1234567.pdf"


def test_the_index_file_name_is_the_providers():
    assert storage.Paths(Path("x")).document_index_csv.name == "Interactive Brokers Document Index.csv"


def test_only_the_statements_folder_and_the_infrastructure_are_made_on_day_one(tmp_path):
    # Only the monthly Activity Statement is read, so a folder for anything else is not made on install (adding-a-provider.md).
    paths = storage.Paths(tmp_path)
    paths.ensure()
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == ["Backups", "Diagnostics", "Logs", "Manual Review", "Statements"]


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()
    assert paths.folder_for(storage.STATEMENT).name == "Statements"


def test_the_orchestrator_imports():
    import importlib
    module = importlib.import_module("ibkr_docs")
    assert hasattr(module, "main") and hasattr(module, "App")
