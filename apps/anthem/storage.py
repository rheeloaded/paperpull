"""What makes the Anthem BCBS app different - everything else is paperpull_core.

This app files the member's Explanation of Benefits (EOB) documents. The shared
core routes a document to a folder by its CATEGORY, and the fixed category set
has no "EOB" of its own, so an EOB is classified as an Insurance Document (it is
an explanation of health-insurance benefits) and that category is routed to the
`EOBs` folder below. The 1095 health-coverage tax form routes to Tax Documents.

To repair Anthem's *page* behaviour, edit `anthem_site.py` instead.
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

SPEC = AppSpec(
    provider="Anthem",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        # The bulk: Medical, Pharmacy and Chiropractic EOBs (and EOB Checks) all
        # land here. They are told apart by their filename summary, not by
        # living in separate folders, because the core routes by category.
        Folder("eobs", "EOBs"),
        # Plan / benefit documents from the member documents page (proof of
        # insurance, plan confirmations). Created on demand.
        Folder("plan_documents", "Plan Documents", precreate=False),
        # Authorization / referral letters. Created on demand.
        Folder("authorizations", "Authorizations", precreate=False),
        # 1095-B health-coverage form, if the account exposes one. Rare, so it
        # is created only when one actually arrives.
        Folder("tax_documents", "Tax Documents", precreate=False),
        # Digital insurance / ID cards (front + back), one PDF per member's card.
        # Created on demand.
        Folder("id_cards", "ID Cards", precreate=False),
        # Secure Message Center letters, one PDF per message. Created on demand.
        Folder("letters", "Letters", precreate=False),
        # Anything recognised but unrouted. Created on demand.
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Insurance Document": "eobs",
        "Tax Document": "tax_documents",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Anthem Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
    },
    base_url="https://membersecure.anthem.com/",
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
