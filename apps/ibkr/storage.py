"""What makes the Interactive Brokers app different: the folders it files into, how a
document routes to one, its CSV columns and its config defaults. Everything else is
paperpull_core. To repair Interactive Brokers' page behavior, edit ibkr_site.py."""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

STATEMENT = "Statement"
TAX = "Tax Document"
LETTER = "Letter"
CONFIRM = "Trade Confirmation"
REPORT = "Report"
ALL_CATEGORIES = [STATEMENT, TAX, LETTER, CONFIRM, REPORT]

DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Account", "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Interactive Brokers",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        # precreate=False: only the monthly Activity Statement is read, so this
        # is made only if something ever routes to it.
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Interactive Brokers Document Index.csv",
                DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        "document_types": [STATEMENT],
        "account_labels": {},
    },
    base_url="https://www.interactivebrokers.com/",
    rules_filename="document_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

from paperpull_core.storage import (
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)
