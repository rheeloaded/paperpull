"""What makes the Scalable Capital app different. Everything else is paperpull_core.

This file holds Scalable Capital's own facts, the folders it files into, how a
document routes to one, its CSV columns, and its config defaults.

To repair Scalable Capital's *page* behavior, edit `scalable_site.py` instead.
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

# The kinds DKB's Postfach sorts its documents into, which a German bank's
# or broker's mailbox is likeliest to hold too. Which kinds this one holds
# waits on the recording (#170). They are all here from the first
# build because an install keeps the document_types it was set up with,
# and a kind added later would be left out of every run. The core knows
# "Statement" and "Tax Document". The folders carry German names, as
# DKB's do.
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
    provider="Scalable Capital",
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
        CsvSpec("document_index_csv", "Scalable Capital Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Which kinds a run downloads, once it can download anything. A
        # person who only wants Kontoauszuege and Wertpapierdokumente drops
        # the rest.
        "document_types": list(ALL_CATEGORIES) + [OTHER],
    },
    base_url="https://de.scalable.capital/",
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
