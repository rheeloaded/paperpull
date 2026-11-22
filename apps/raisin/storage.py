"""Storage layout for locally archived Raisin (Weltsparen) deposit documents."""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# One row per downloaded Raisin document. Deliberately records NO customer
# number, deposit number, balance or rate, only what is needed to find and
# verify a file locally.
DOCUMENT_INDEX_COLUMNS = [
    "Account Holder",
    "Document Date", "Category", "Document Summary", "Document Title",
    "Period", "PDF Filename", "PDF Full Path", "PDF File Size",
    "PDF Page Count", "Source URL", "Classification Confidence",
    "Downloaded At", "Verified At", "Processing Status", "Notes",
]

# The kinds a savings marketplace's deposit documents are likeliest to be.
# Which titles Raisin really gives waits on a tester's first Diagnose, so
# every kind is in from the first build, since an install keeps the
# document_types it was set up with. The folders carry German names, as
# the other German apps' do.
STATEMENT = "Statement"
TAX = "Tax Document"
CONTRACT = "Contract Information"
OTHER = "Other Document"
ALL_CATEGORIES = [STATEMENT, TAX, CONTRACT, OTHER]

SPEC = AppSpec(
    provider="Raisin",
    countries=("DE",),
    project_dir=Path(__file__).resolve().parent,
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Kontoauszuege"),
        Folder("tax_documents", "Steuerbescheinigungen"),
        Folder("contract_information", "Vertragsunterlagen"),
        Folder("other_documents", "Sonstige Dokumente", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        STATEMENT: "statements",
        TAX: "tax_documents",
        CONTRACT: "contract_information",
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
        "pilot_count": 3,
        "document_types": list(ALL_CATEGORIES),
        # A PDF that does not show its own row is never filed under it.
        "refuse_wrong_documents": True,
    },
    base_url="https://www.raisin.com/",
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
    "STATEMENT", "TAX", "CONTRACT", "OTHER", "ALL_CATEGORIES",
    "CsvFile", "JsonStore", "Paths", "atomic_write_json", "atomic_write_text",
    "backup_file", "build_pdf_filename", "ensure_owner", "load_config",
    "now_iso", "sanitize_component", "set_filename_owner", "title_case",
    "unique_path",
]
