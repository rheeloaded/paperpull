"""What makes the Paylocity app different - everything else is paperpull_core.

Paylocity has one fixed address (access.paylocity.com), unlike UKG's
per-employer tenant. The employer is identified by the Company ID typed at
sign-in, which this app never handles or stores, so nothing here is per-tenant.

To repair Paylocity's *page* behaviour, edit `paylocity_site.py` instead.
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
    provider="Paylocity",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("pay_statements", "Pay Statements"),
        # Routed and ready, but NOT pre-created: this app does not fetch
        # tax forms yet (see paylocity_site.py), so the folder would only sit
        # there empty. It appears the moment something lands in it.
        Folder("tax_documents", "Tax Documents", precreate=False),
        # Reachable but not pre-created, so an install never grows an empty
        # folder for something this provider may never issue.
        Folder("year_end_summaries", "Year-End Summaries", precreate=False),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    # The shared classifier speaks in categories: Statement / Tax Document /
    # Year-End Summary. At Paylocity a "statement" IS a pay statement, so the
    # category stays the core's and the FOLDER carries the payroll wording.
    routes={
        "Statement": "pay_statements",
        "Tax Document": "tax_documents",
        "Year-End Summary": "year_end_summaries",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Paylocity Document Index.csv",
                DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "min_pdf_bytes": 2000,
        "delay_min_seconds": 2.5,
        "delay_max_seconds": 5.0,
        "pilot_count": 3,
        "document_types": ["Statement"],
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
