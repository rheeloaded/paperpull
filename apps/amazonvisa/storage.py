"""What makes the Amazon Visa app different. Everything else is paperpull_core.

This file holds Amazon Visa's own facts, the folders it files into, how a
document routes to one, its CSV columns, and its config defaults.

To repair Amazon Visa's *page* behavior, edit `amazonvisa_site.py` instead.
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

CARD = "Credit Card Statement"
CONTRACT = "Contract Information"
TAX = "Tax Document"
MESSAGE = "Message"
OTHER = "Other Document"
ALL_CATEGORIES = [CARD, CONTRACT, TAX, MESSAGE, OTHER]
FALLBACK_SUMMARY = {
    CARD: "Kreditkartenabrechnung",
    CONTRACT: "Vertragsinformation",
    TAX: "Steuerbescheinigung",
    MESSAGE: "Mitteilung",
    OTHER: "Dokument",
}

SPEC = AppSpec(
    provider="Amazon Visa",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("card_statements", "Kreditkartenabrechnungen"),
        Folder("tax_documents", "Steuerbescheinigungen"),
        Folder("contract_information", "Vertragsinformationen", precreate=False),
        Folder("messages", "Mitteilungen", precreate=False),
        Folder("other_documents", "Sonstige Dokumente", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        CARD: "card_statements",
        TAX: "tax_documents",
        CONTRACT: "contract_information",
        MESSAGE: "messages",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "Amazon Visa Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        "document_types": list(ALL_CATEGORIES),
    },
    base_url="https://kunden.openbankpay.com/amazon/",
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
