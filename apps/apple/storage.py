"""What makes the Apple app different. Everything else is paperpull_core.

Apple's own facts live here, the two folders it files into and how a
purchase routes to one, its CSV columns, and its config defaults. The
columns are the same ones every receipt app writes, so the purchase
exporter reads this app like any other.

To repair Apple's *page* behavior, edit `apple_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, RECEIPT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# The two kinds of purchase, each with its own folder. Apple's own names for
# its two stores, the App Store for what is downloaded or subscribed to and
# the Apple Store for what is shipped or picked up.
APP_STORE = "App Store"
APPLE_STORE = "Apple Store"
PURCHASE_TYPES = (APP_STORE, APPLE_STORE)

ORDER_HISTORY_COLUMNS = [
    "Account Holder",
    "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Status",
    "Item Name", "Quantity", "Unit Price", "Line Item Total", "Order Total",
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
    provider="Apple",
    project_dir=Path(__file__).resolve().parent,
    kind=RECEIPT,
    folders=[
        Folder("app_store", APP_STORE),
        Folder("apple_store", APPLE_STORE),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        APP_STORE: "app_store",
        APPLE_STORE: "apple_store",
    },
    default_route="app_store",
    csv_files=[
        CsvSpec("order_history_csv", "Apple Order History.csv", ORDER_HISTORY_COLUMNS),
        CsvSpec("receipt_index_csv", "Apple Receipt Index.csv", RECEIPT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_app_store": 3,
        "pilot_apple_store": 2,
    },
    # An App Store receipt is rendered from HTML Report a Problem handed
    # over, so a relative address in it belongs to that host.
    base_url="https://reportaproblem.apple.com/",
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
