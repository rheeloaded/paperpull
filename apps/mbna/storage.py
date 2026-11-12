"""What makes the MBNA app different. Everything else is paperpull_core.

This file holds MBNA's own facts, the folders it files into, how a
document routes to one, its CSV columns, and its config defaults.

To repair MBNA's *page* behavior, edit `mbna_site.py` instead.
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

# The kind the request asks for, the card's monthly statements. Whatever
# else MBNA's pages hold waits on the recording (#205) and files under Other
# Documents. Both are here from the first build because an install keeps the
# document_types it was set up with, and a kind added later would be left
# out of every run. A credit card issues no tax slips. The core knows
# "Statement".
STATEMENT = "Statement"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT]

# The words a file name carries when document_rules.json has no better
# ones for a title.
FALLBACK_SUMMARY = {
    STATEMENT: "Credit Card Statement",
}

SPEC = AppSpec(
    provider="MBNA",
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
        CsvSpec("document_index_csv", "MBNA Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Which kinds a run downloads, once it can download anything.
        "document_types": list(ALL_CATEGORIES) + [OTHER],
    },
    base_url="https://service.mbna.ca/",
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
