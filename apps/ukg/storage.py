"""What makes the UKG app different - everything else is paperpull_core.

UKG is the first provider whose address is not a fixed domain. Every employer
gets its own UKG tenant, and the product varies too (UKG Pro / UltiPro, UKG
Ready, Workforce Central), so the base URL lives in `config.json` as
`base_url` rather than being baked in here. That also keeps it out of the
repo: the tenant address identifies your employer.

To repair UKG's *page* behaviour, edit `ukg_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per downloaded pay document. Deliberately records NO pay amounts,
# SSN, bank details, or anything else from inside the document - only what is
# needed to find and verify a file locally. Pay stubs are among the most
# sensitive documents this project touches.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="UKG",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("pay_statements", "Pay Statements"),
        Folder("tax_documents", "Tax Documents"),
        # Reachable but not pre-created, so an install never grows an empty
        # folder for something this provider may never issue.
        Folder("year_end_summaries", "Year-End Summaries", precreate=False),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    # The shared classifier speaks in categories: Statement / Tax Document /
    # Year-End Summary. At UKG a "statement" IS a pay statement, so the
    # category stays the core's and the FOLDER carries the payroll wording.
    routes={
        "Statement": "pay_statements",
        "Tax Document": "tax_documents",
        "Year-End Summary": "year_end_summaries",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "UKG Document Index.csv",
                DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "min_pdf_bytes": 2000,
        "delay_min_seconds": 2.5,
        "delay_max_seconds": 5.0,
        "pilot_count": 3,
        "document_types": ["Statement", "Tax Document"],
        # No default: there is no such thing as a generic UKG address.
        "base_url": "",
    },
    rules_filename="document_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

from paperpull_core.storage import (  # noqa: E402  (must follow bind)
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)
