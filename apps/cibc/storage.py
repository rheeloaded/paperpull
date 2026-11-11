"""What makes the CIBC app different. Everything else is paperpull_core.

This file holds CIBC's own facts, the folders it files into, how a
document routes to one, its CSV columns, and its config defaults.

To repair CIBC's *page* behavior, edit `cibc_site.py` instead.
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

# The kinds the request asks for, bank account, credit card and line of
# credit statements, and the tax slips a Canadian bank may post beside
# them. Which kinds CIBC Online Banking holds, and where, waits on the
# recording (#204). They are all here from the first build because an
# install keeps the document_types it was set up with, and a kind added
# later would be left out of every run. The core knows "Statement" and
# "Tax Document".
STATEMENT = "Statement"
CARD = "Credit Card Statement"
CREDIT_LINE = "Line of Credit Statement"
TAX = "Tax Document"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT, CARD, CREDIT_LINE, TAX]

# The words a file name carries when document_rules.json has no better
# ones for a title.
FALLBACK_SUMMARY = {
    STATEMENT: "Account Statement",
    CARD: "Credit Card Statement",
    CREDIT_LINE: "Line of Credit Statement",
    TAX: "Tax Document",
}

SPEC = AppSpec(
    provider="CIBC",
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("card_statements", "Credit Card Statements"),
        Folder("line_of_credit_statements", "Line of Credit Statements"),
        # Not asked for, so made only if a document ever routes there.
        Folder("tax_documents", "Tax Documents", precreate=False),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
        CARD: "card_statements",
        CREDIT_LINE: "line_of_credit_statements",
        TAX: "tax_documents",
    },
    default_route="other_documents",
    csv_files=[
        CsvSpec("document_index_csv", "CIBC Document Index.csv", DOCUMENT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_count": 5,
        # Which kinds a run downloads, once it can download anything. A
        # person who only wants their bank account statements drops the
        # rest.
        "document_types": list(ALL_CATEGORIES) + [OTHER],
    },
    base_url="https://www.cibconline.cibc.com/",
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
