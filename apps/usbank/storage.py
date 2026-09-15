"""U.S. Bank credit-card statements."""
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
    provider="U.S. Bank",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),



        Folder("tax_documents", "Tax Documents", precreate=False),



        Folder("insurance_documents", "Insurance Documents", precreate=False),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Tax Document": "tax_documents",
        "Insurance Document": "insurance_documents",
        "Statement": "statements",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "U.S. Bank Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={



        "pilot_count": 5,






        "account_labels": {},
    },
    base_url="https://onlinebanking.usbank.com/",
    rules_filename="document_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir


from paperpull_core.storage import (
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)
