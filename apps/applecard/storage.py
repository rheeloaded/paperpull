"""What makes the Apple Card app different, everything else is paperpull_core.

What remains here is the declaration of Apple Card's own facts: the folders
it files into, how a document routes to one, its CSV columns, and its config
defaults. The provider is "Apple Card" rather than "Apple" because Apple
calls the savings account "Savings from Apple Card", and a file named
"Apple Savings Statement" would read like something from the App Store.

To repair Apple Card's *page* behavior, edit `applecard_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per downloaded Apple Card document. Deliberately records NO account
# numbers, SSN, balances, or other sensitive values from inside the documents,
# only what is needed to find and verify a file locally.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Apple Card",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        # Card statements and Savings statements share one folder, told
        # apart by their filenames, the way other banks' checking and card
        # statements do.
        Folder("statements", "Statements"),
        # A Savings account earns interest, so a 1099-INT comes every year
        # there was any. The folder is made up front.
        Folder("tax_documents", "Tax Documents"),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Statement": "statements",
        "Tax Document": "tax_documents",
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
        "pilot_count": 5,
        "document_types": ["Statement", "Tax Document"],
    },
    base_url="https://card.apple.com/",
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
