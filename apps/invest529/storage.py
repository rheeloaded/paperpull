"""What makes the Invest529 app different. Everything else is paperpull_core.

This file holds Invest529's own facts: the folders it files into, how a
document routes to one, its CSV columns, and its config defaults.

To repair Invest529's *API / page* behavior, edit `invest529_site.py` instead.
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

# The categories this app files by. The core knows the first two; the rest
# are named so the shared orchestrator's references resolve, though Invest529
# only ever produces statements and tax forms.
STATEMENT = "Statement"
TAX = "Tax Document"
CONFIRM = "Trade Confirmation"
LETTER = "Letter"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT, TAX]

SPEC = AppSpec(
    provider="Invest529",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("tax_documents", "Tax Documents"),
        Folder("other_documents", "Other Documents", precreate=False),  # created on demand
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
        TAX: "tax_documents",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Invest529 Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Which kinds a run downloads: official quarterly statements and
        # 1099-Q tax forms.
        "document_types": list(ALL_CATEGORIES),
    },
    base_url="https://myaccount.invest529.com/",
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
