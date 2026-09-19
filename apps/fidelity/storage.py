"""What makes the Fidelity app different. Everything else is paperpull_core.

This file used to be a full copy of the storage logic every other app carried.
That logic now lives in `paperpull_core`; what remains here is Fidelity's own
facts: the folders it files into, how a document routes to one, its CSV
columns, and its config defaults.

To repair Fidelity's *page* behavior, edit `fidelity_site.py` instead.
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

# Fidelity's documents page sorts documents into kinds of its own. These are
# the categories this app files by. The core knows the first two, the rest
# are this app's, as they are Schwab's.
STATEMENT = "Statement"
TAX = "Tax Document"
LETTER = "Letter"
CONFIRM = "Trade Confirmation"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT, TAX, CONFIRM, LETTER]

SPEC = AppSpec(
    provider="Fidelity",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("tax_documents", "Tax Documents"),
        Folder("trade_confirmations", "Trade Confirmations"),
        Folder("letters", "Letters", precreate=False),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
        TAX: "tax_documents",
        CONFIRM: "trade_confirmations",
        LETTER: "letters",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Fidelity Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Which kinds a run downloads. Trade confirmations can run to
        # hundreds, and a person who only wants statements can drop them.
        "document_types": list(ALL_CATEGORIES),
    },
    base_url="https://digital.fidelity.com/",
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
