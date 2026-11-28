"""What makes the Poppins Payroll app different - everything else is paperpull_core.

Poppins runs payroll for household employers, so the person signing in is
the employer and the documents are of three kinds: the employee's pay
stubs, the year's tax forms, and the record of the quarterly tax
withdrawals, which Poppins keeps only as a table and this app saves as a
PDF of its own.

To repair Poppins' *page* behavior, edit `poppins_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per downloaded document. Deliberately records NO pay amounts,
# SSN, bank details, or anything else from inside the document - only what
# is needed to find and verify a file locally.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Poppins",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("pay_stubs", "Pay Stubs"),
        Folder("tax_forms", "Tax Forms"),
        Folder("tax_payment_history", "Tax Payment History"),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    # The shared classifier speaks in categories. At Poppins a "statement"
    # is a pay stub, and the core has no category for a record of tax
    # payments, so those travel as Year-End Summary, the nearest, and the
    # FOLDER carries what they are.
    routes={
        "Statement": "pay_stubs",
        "Tax Document": "tax_forms",
        "Year-End Summary": "tax_payment_history",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Poppins Document Index.csv",
                DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "min_pdf_bytes": 2000,
        "delay_min_seconds": 2.0,
        "delay_max_seconds": 4.0,
        "pilot_count": 3,
        "document_types": ["Statement", "Tax Document", "Year-End Summary"],
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
