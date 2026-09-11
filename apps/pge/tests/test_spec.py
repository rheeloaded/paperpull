"""Locks in facts for the PG&E app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") == \
        "2026-01-02 PG&E Thing Statement.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "PG&E Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Logs', 'Manual Review', 'Statements']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()


def test_the_orchestrator_imports():
    import importlib
    here = Path(__file__).resolve().parents[1]
    entry = next(p for p in list(here.glob("*_docs.py")) + list(here.glob("*_receipts.py")))
    module = importlib.import_module(entry.stem)
    assert hasattr(module, "main")
    assert hasattr(module, "App")


def test_cli_parser_supports_year_and_date_filters():
    import pge_docs
    parser = pge_docs.build_parser()
    args = parser.parse_args(["--year", "2025", "--start-date", "2025-01-01", "--end-date", "2025-12-31"])
    assert args.year == 2025
    assert args.start_date == "2025-01-01"
    assert args.end_date == "2025-12-31"


def test_document_page_number_roundtrip():
    import pge_docs
    doc = pge_docs.Document(
        title="Energy Statement - 2025-12-09",
        category="Statement",
        date="2025-12-09",
        page_number=2,
        row_index=3,
    )
    assert doc.page_number == 2
    d = doc.to_dict()
    assert d["page_number"] == 2
    doc2 = pge_docs.Document.from_dict(d)
    assert doc2.page_number == 2


def test_in_scope_year_filtering():
    import pge_docs
    parser = pge_docs.build_parser()
    args = parser.parse_args(["--year", "2025"])
    app = pge_docs.App(args)
    
    doc_2025 = pge_docs.Document(title="Statement", category="Statement", date="2025-06-01")
    doc_2026 = pge_docs.Document(title="Statement", category="Statement", date="2026-06-01")
    
    assert app._in_scope(doc_2025) is True
    assert app._in_scope(doc_2026) is False
