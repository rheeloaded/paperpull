"""Storage layout for locally archived Sonic bills."""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per Sonic document, with only the metadata used to locate and
# verify the file locally.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Sonic",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        # Statement PDFs are routed under Bills.
        Folder("bills", "Bills"),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Statement": "bills",
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
        "document_types": ["Statement"],
    },
    base_url="https://members.sonic.net/",
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
