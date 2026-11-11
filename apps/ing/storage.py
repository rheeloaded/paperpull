"""ING storage configuration, laid out as DKB's is.

Which Postbox document types fall into each category is ing_site.classify's.
It has been checked on one account, not for every document type. Shared
storage logic lives in paperpull_core; page behavior lives in ing_site.py.
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

# Categories and folder names. Which Postbox document types fall into each
# is ing_site.classify's.
STATEMENT = "Statement"
CARD = "Credit Card Statement"
SECURITIES = "Securities Document"
TAX = "Tax Document"
CONTRACT = "Contract Information"
MESSAGE = "Message"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT, CARD, SECURITIES, TAX, CONTRACT, MESSAGE]

# The words a file name carries when document_rules.json has no better
# ones for a title.
FALLBACK_SUMMARY = {
    STATEMENT: "Kontoauszug",
    CARD: "Kreditkartenabrechnung",
    SECURITIES: "Wertpapierdokument",
    TAX: "Steuerbescheinigung",
    CONTRACT: "Vertragsinformation",
    MESSAGE: "Mitteilung",
}

SPEC = AppSpec(
    provider="ING",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Kontoauszuege"),
        Folder("card_statements", "Kreditkartenabrechnungen"),
        Folder("securities_documents", "Wertpapierdokumente"),
        Folder("tax_documents", "Steuerbescheinigungen"),
        Folder("contract_information", "Vertragsinformationen", precreate=False),
        Folder("messages", "Mitteilungen", precreate=False),
        Folder("other_documents", "Sonstige Dokumente", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
        CARD: "card_statements",
        SECURITIES: "securities_documents",
        TAX: "tax_documents",
        CONTRACT: "contract_information",
        MESSAGE: "messages",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "ING Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Document types to keep; a person can select a subset.
        "document_types": list(ALL_CATEGORIES) + [OTHER],
        # Rows the Postbox marks unread are downloaded too; whether a
        # download marks them read in ING is not known.
        "include_unread": True,
        # The Postbox archive is read as well as the Postbox.
        "read_archive": True,
    },
    base_url="https://banking.ing.de/",
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
