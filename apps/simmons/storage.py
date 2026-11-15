"""What makes the Simmons Bank app different, everything else is paperpull_core.

This file declares Simmons Bank's own facts: the folders it files into, how
a document routes to one, its CSV columns, and its config defaults. All the
storage logic itself lives in `paperpull_core`.

To repair Simmons Bank's *page* behavior, edit `simmons_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per downloaded Simmons Bank document. Deliberately records NO
# account numbers, account or document ids, balances, or other sensitive
# values from inside the documents, only what is needed to find and verify a
# file locally.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Simmons Bank",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        # The loan's monthly statements.
        Folder("statements", "Statements"),
        # The yearly tax reporting forms.
        Folder("tax_documents", "Tax Documents"),
        Folder("insurance_documents", "Insurance Documents", precreate=False),
        # The loan's notices, a prime rate change or a change of address.
        Folder("other_documents", "Notices"),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Statement": "statements",
        "Tax Document": "tax_documents",
        "Insurance Document": "insurance_documents",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "{provider} Document Index.csv",
                DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "min_pdf_bytes": 2000,
        "delay_min_seconds": 2.5,
        "delay_max_seconds": 5.0,
        "pilot_count": 1,
        "document_types": ["Statement", "Tax Document", "Other Document"],
    },
    base_url="https://login.simmonsbank.com/documents",
    rules_filename="document_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

# The shared API, re-exported so the orchestrator's imports read the same as
# they always have.
from paperpull_core.storage import (  # noqa: E402  (must follow bind)
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)

__all__ = [
    "SPEC", "PROJECT_DIR", "DOCUMENT_INDEX_COLUMNS",
    "CsvFile", "JsonStore", "Paths", "atomic_write_json", "atomic_write_text",
    "backup_file", "build_pdf_filename", "ensure_owner", "load_config",
    "now_iso", "sanitize_component", "set_filename_owner", "title_case",
    "unique_path",
]
