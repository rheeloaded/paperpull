"""Locks in the facts that must not drift once somebody has an archive.

If any of them changed, an existing archive would be stranded. A renamed
CSV orphans the index, a moved folder hides the documents, and a different
provider string renames every new PDF.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage

HERE = Path(__file__).resolve().parents[1]


def test_provider_string_is_unchanged():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Receipt", record={}) == \
        "2026-01-02 Uber Thing Receipt.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.order_history_csv.name == "Uber Order History.csv"
    assert paths.receipt_index_csv.name == "Uber Receipt Index.csv"


def test_the_columns_are_the_ones_every_receipt_app_writes():
    """The purchase exporter reads every receipt app's CSVs the same way,
    so these are the same columns Apple and Costco write, in order."""
    assert storage.ORDER_HISTORY_COLUMNS == [
        "Account Holder",
        "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Status",
        "Item Name", "Quantity", "Unit Price", "Line Item Total", "Order Total",
        "Fulfillment Method", "Return Status", "Purchase Summary", "PDF Filename",
        "Purchase Details URL", "Receipt URL", "Processing Status", "Notes",
    ]
    assert storage.RECEIPT_INDEX_COLUMNS == [
        "Account Holder",
        "Purchase Date", "Purchase Type", "Order or Receipt Number", "Order Total",
        "Purchase Summary", "PDF Filename", "PDF Full Path", "Document Type",
        "Receipt Status", "Receipt Count", "Classification Confidence", "Receipt URL",
        "PDF File Size", "PDF Page Count", "Downloaded At", "Verified At",
        "Processing Status", "Notes",
    ]


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Logs', 'Manual Review', 'Rides', 'Uber Eats']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()


def test_each_kind_of_purchase_files_into_its_own_folder(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.folder_for(storage.RIDES).name == "Rides"
    assert paths.folder_for(storage.EATS).name == "Uber Eats"
    assert paths.folder_for(storage.EATS, "Receipt").name == "Uber Eats"


def test_the_site_module_names_the_two_kinds_the_way_storage_routes_them():
    """The site module keeps its own copy, because the core's census tests
    load it beside other apps' storage, and the two must never drift."""
    import uber_site
    assert (uber_site.RIDES, uber_site.EATS) == storage.PURCHASE_TYPES
    assert set(storage.SPEC.routes) == set(storage.PURCHASE_TYPES)


def test_the_template_points_at_this_apps_own_browser():
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    assert cfg["cdp_url"] == "http://127.0.0.1:9281"
    assert cfg["output_dir"] == "."
    assert cfg["profile_dir"] == "./browser-profile"
    assert cfg["refuse_wrong_documents"] is True


def test_the_orchestrator_imports():
    """Catches a core that is installed but too old for this app.

    The unit tests exercise storage and the site layer directly, so a missing
    module in the orchestrator's own imports slipped past them once, and
    every command died on startup while the tests stayed green.
    """
    import importlib
    entry = next(p for p in list(HERE.glob("*_docs.py")) + list(HERE.glob("*_receipts.py")))
    module = importlib.import_module(entry.stem)
    assert hasattr(module, "main")
    assert hasattr(module, "App")
