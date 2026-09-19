"""What makes the Fairfax Water app different. Everything else is paperpull_core.

This file used to be a full copy of the storage logic every other app carried.
That logic now lives in `paperpull_core`; what remains here is Fairfax Water's own
facts: the folders it files into, how a document routes to one, its CSV
columns, and its config defaults.

To repair Fairfax Water's *page* behavior, edit `fairfaxwater_site.py` instead.
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

STATEMENT = "Statement"
OTHER = "Other Document"

SPEC = AppSpec(
    provider="Fairfax Water",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Fairfax Water Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        "document_types": [STATEMENT],
    },
    base_url="https://www.fwcustomer.org/",
    pdf_token="fairfax",
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
