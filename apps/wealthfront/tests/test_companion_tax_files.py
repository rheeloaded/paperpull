"""Companion tax files (.xls, .pdf) are saved beside the primary file,
recorded in notes and invoices, and tracked in new_files.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from paperpull_core import doc_types, receipt_pdf, storage
from paperpull_core.models import State
import wealthfront_docs as app_mod


@pytest.fixture(autouse=True)
def reset_patterns():
    yield
    storage.set_filename_owner("")
    storage.set_filename_patterns({})


def test_companion_files_save_beside_primary_and_record_invoices(tmp_path, monkeypatch):
    out = tmp_path / "out"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "output_dir": str(out),
        "filename_pattern_statements": "{provider}/[ {account}]/[ {year}]/{date:yyyy-mm-dd}[ {kind}][ ({part})]",
        "min_pdf_bytes": 10,
        "max_path_length": 240,
    }), encoding="utf-8")

    args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes"])
    app = app_mod.App(args)
    app.paths.ensure()
    app.stats = {
        "new_files": [], "tax_documents": 0, "statements": 0, "other": 0,
        "duplicate_filenames": 0, "manual_review": 0, "failed": 0,
        "validation_failures": 0, "dates": [],
    }
    app.index_csv = MagicMock()
    app.progress = MagicMock()
    app.discovery = MagicMock()
    app._journal = MagicMock()

    doc = app_mod.Document(
        title="Consolidated Form 1099",
        category=doc_types.TAX,
        summary="Consolidated 1099 Tax Form",
        date="2024-12-31",
        account="Investing",
        href="http://example.com/form.pdf",
    )

    fake_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    fake_xls = b"fake xls content"

    # Mock page and downloads
    dl_pdf = SimpleNamespace(value=SimpleNamespace(suggested_filename="1099.pdf"))
    dl_xls = SimpleNamespace(value=SimpleNamespace(suggested_filename="1099_gain_loss.xls"))

    # Mock save_download
    def fake_save(download, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".pdf":
            path.write_bytes(fake_pdf)
        else:
            path.write_bytes(fake_xls)

    monkeypatch.setattr(receipt_pdf, "save_download", fake_save)
    monkeypatch.setattr(receipt_pdf, "validate_pdf",
                        lambda path, min_bytes: SimpleNamespace(ok=True, size_bytes=100, page_count=1))
    monkeypatch.setattr(app_mod.site, "is_safe_url", lambda url: True)
    monkeypatch.setattr(app, "check_session", lambda page: None)

    # Mock site.resolve_tax_file_links to return 2 links (1 primary, 1 extra)
    doc.href = ""  # trigger tax link resolution
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links",
                        lambda page, account, title: ["http://example.com/1099.pdf",
                                                      "http://example.com/1099_gain_loss.xls"])

    page = MagicMock()
    # Mock expect_download context manager
    class ExpectDl:
        def __init__(self, dl):
            self.value = dl.value
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    page.expect_download = MagicMock(side_effect=[ExpectDl(dl_pdf), ExpectDl(dl_xls)])
    page.locator().count.return_value = 1

    filename = storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    app.download_one(page, doc, filename)

    # 1. Primary file and companion file must both be in the pattern's folder (Wealthfront/Investing/2024/)
    primary = Path(doc.pdf_path)
    expected_parent = app.paths.tax_documents / "Wealthfront" / "Investing" / "2024"
    assert primary.parent == expected_parent
    assert primary.name == "2024-12-31 Tax Document.pdf"

    # Companion file
    companion = expected_parent / "2024-12-31 Tax Document (2 of 2).xls"
    assert companion.is_file(), f"Companion file should be in {expected_parent}, but was not found"

    # 2. Both files must be in new_files stats
    assert str(primary) in app.stats["new_files"]
    assert str(companion) in app.stats["new_files"]

    # 3. doc.notes must have "Also saved: <companion.name>"
    assert f"Also saved: {companion.name}" in doc.notes

    # 4. doc.invoices must track both files
    assert doc.invoices == [
        {"file": str(primary), "kept": True},
        {"file": str(companion), "kept": True},
    ]


def test_no_empty_directory_created_when_no_download_control(tmp_path, monkeypatch):
    out = tmp_path / "out"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "output_dir": str(out),
        "filename_pattern_statements": "{provider}/[ {account}]/[ {year}]/{date:yyyy-mm-dd}[ {kind}][ ({part})]",
        "min_pdf_bytes": 10,
        "max_path_length": 240,
    }), encoding="utf-8")

    args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes"])
    app = app_mod.App(args)
    app.paths.ensure()
    app.stats = {"duplicate_filenames": 0, "manual_review": 0, "failed": 0}
    app.index_csv = MagicMock()
    app.discovery = MagicMock()

    doc = app_mod.Document(
        title="Consolidated Form 1099",
        category=doc_types.TAX,
        summary="Consolidated 1099 Tax Form",
        date="2017-12-31",
        account="Investing",
        href="",
    )

    page = MagicMock()
    page.locator().count.return_value = 1
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links", lambda *a: [])
    monkeypatch.setattr(app_mod.site, "find_row_download", lambda *a: None)

    filename = storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    app.download_one(page, doc, filename)

    year_dir = app.paths.tax_documents / "Wealthfront" / "Investing" / "2017"
    assert not year_dir.exists(), f"Directory {year_dir} should not have been created"
