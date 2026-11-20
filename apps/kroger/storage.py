"""What makes the Kroger app different - everything else is paperpull_core.

This file used to be a full copy of the storage logic every other app carried.
That logic now lives in `paperpull_core`; what remains here is Kroger's own
facts: the folders it files into, how a document routes to one, its CSV
columns, and its config defaults.

To repair Kroger's *page* behavior, edit `kroger_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, RECEIPT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

ORDER_HISTORY_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Status",
    "Item Name", "Quantity", "Pricing Quantity", "Pricing Unit", "Unit Price", "Line Item Total", "Order Total",
    "Fulfillment Method", "Return Status", "Purchase Summary", "PDF Filename",
    "Purchase Details URL", "Receipt URL", "Processing Status", "Notes",
]

RECEIPT_INDEX_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Total",
    "Purchase Summary", "PDF Filename", "PDF Full Path", "Document Type",
    "Receipt Status", "Receipt Count", "Classification Confidence", "Receipt URL",
    "PDF File Size", "PDF Page Count", "Downloaded At", "Verified At",
    "Processing Status", "Notes",
]

SPEC = AppSpec(
    provider="Kroger",
    countries=("US",),
    project_dir=Path(__file__).resolve().parent,
    kind=RECEIPT,
    folders=[
        Folder("online", "Online"),
        Folder("instore", "In-Store"),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        "Online": "online",
        "In-Store": "instore",
    },
    default_route="online",
    csv_files=[
        CsvSpec("order_history_csv", "Kroger Order History.csv", ORDER_HISTORY_COLUMNS),
        CsvSpec("receipt_index_csv", "Kroger Receipt Index.csv", RECEIPT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_online": 5,
        "pilot_instore": 3,
    },
    base_url="https://www.kroger.com/",
    rules_filename="category_rules.json",
)

_core.bind(SPEC)

PROJECT_DIR = SPEC.project_dir

# The shared API, re-exported so the orchestrator's imports read as they always did.
from paperpull_core.storage import (  # noqa: E402  (must follow bind)
    CsvFile, JsonStore, Paths, atomic_write_json, atomic_write_text,
    backup_file, build_pdf_filename, ensure_owner, load_config, now_iso,
    sanitize_component, set_filename_owner, title_case, unique_path,
)


class PricingCsvFile(CsvFile):
    """Upgrade Kroger's old header before appending rows with a pricing basis."""
    def _ensure_header(self):
        if self.path.exists() and self.path.stat().st_size:
            import csv
            from paperpull_core import shared_folder
            from paperpull_core.sheets import read_stored_row
            with shared_folder.open_to_read(self.path, 'r', encoding='utf-8-sig', newline='') as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames
                if header == self.columns:
                    return
                legacy = [c for c in self.columns if c not in ('Pricing Quantity', 'Pricing Unit')]
                if header != legacy:
                    raise ValueError('Kroger history has an unknown header; refusing to append mismatched columns')
                if self.waiting_path.exists():
                    raise ValueError('Flush queued Kroger CSV writes with the previous version before upgrading the history header')
                rows = [read_stored_row(row) for row in reader]
            # Existing values survive, new fields stay unknown, and rewrite backs up first.
            self.rewrite(rows, backup=True)
            return
        super()._ensure_header()
