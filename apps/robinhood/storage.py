"""What makes the Robinhood app different - everything else is paperpull_core.

This file used to be a full copy of the storage logic every other app carried.
That logic now lives in `paperpull_core`; what remains here is Robinhood's own
facts: the folders it files into, how a document routes to one, its CSV
columns, and its config defaults.

To repair Robinhood's *page* behaviour, edit `robinhood_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Robinhood",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("tax_documents", "Tax Documents"),
        Folder("insurance_documents", "Insurance Documents", precreate=False),  # created on demand
        Folder("other_documents", "Other Documents", precreate=False),  # created on demand
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Tax Document": "tax_documents",
        "Insurance Document": "insurance_documents",
        "Statement": "statements",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Robinhood Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        # How many documents --pilot fetches. The online/in-store split and
        # include_invoices that used to sit here are receipt-app concepts and
        # were never read by a statement app.
        "pilot_count": 5,
    },
    base_url="https://robinhood.com/",
    rules_filename="document_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

# The shared API, re-exported so the orchestrator's imports read as they always did.
from paperpull_core.storage import (  # noqa: E402  (must follow bind)
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)
