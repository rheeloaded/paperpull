"""What makes the Uber app different. Everything else is paperpull_core.

Uber's own facts live here, the two folders it files into and how a
purchase routes to one, its CSV columns, and its config defaults. The
columns are the same ones every receipt app writes, so the purchase
exporter reads this app like any other.

To repair Uber's *page* behavior, edit `uber_site.py` instead.
"""
from __future__ import annotations

from pathlib import Path

from paperpull_core import storage as _core
from paperpull_core.spec import (AppSpec, CsvSpec, RECEIPT, Folder,
                                 INFRASTRUCTURE_FOLDERS)

# The two kinds of purchase, each with its own folder. Rides are every trip
# on riders.uber.com, and Uber Eats is every food or grocery order on
# ubereats.com, a separate site with a sign-in of its own.
RIDES = "Rides"
EATS = "Uber Eats"
PURCHASE_TYPES = (RIDES, EATS)

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
    provider="Uber",
    project_dir=Path(__file__).resolve().parent,
    kind=RECEIPT,
    folders=[
        Folder("rides", RIDES),
        Folder("eats", EATS),
        *INFRASTRUCTURE_FOLDERS,
    ],
    routes={
        RIDES: "rides",
        EATS: "eats",
    },
    default_route="rides",
    csv_files=[
        CsvSpec("order_history_csv", "Uber Order History.csv", ORDER_HISTORY_COLUMNS),
        CsvSpec("receipt_index_csv", "Uber Receipt Index.csv", RECEIPT_INDEX_COLUMNS),
    ],
    config_defaults={
        "pilot_rides": 3,
        "pilot_eats": 3,
    },
    base_url="https://riders.uber.com/",
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
