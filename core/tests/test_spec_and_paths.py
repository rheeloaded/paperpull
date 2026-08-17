"""The core's own tests: the spec contract and the folder/routing behaviour
every app now depends on."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import storage
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS, RECEIPT)


def document_spec(tmp_path):
    return AppSpec(
        provider="T-Mobile",
        project_dir=tmp_path,
        kind=DOCUMENT,
        folders=[Folder("statements", "Statements"),
                 Folder("tax_documents", "Tax Documents"),
                 Folder("insurance_documents", "Insurance Documents", precreate=False),
                 Folder("other_documents", "Other Documents", precreate=False),
                 *INFRASTRUCTURE_FOLDERS],
        routes={"Statement": "statements", "Tax Document": "tax_documents",
                "Insurance Document": "insurance_documents"},
        default_route="other_documents",
        csv_files=[CsvSpec("document_index_csv", "{provider} Document Index.csv",
                           ["Account Holder", "Document Date", "Notes"])],
        config_defaults={"pilot_count": 5},
    )


def receipt_spec(tmp_path):
    return AppSpec(
        provider="Gap", project_dir=tmp_path, kind=RECEIPT,
        folders=[Folder("online", "Online"), Folder("instore", "In-Store"),
                 *INFRASTRUCTURE_FOLDERS],
        routes={"Online": "online", "In-Store": "instore"},
        csv_files=[CsvSpec("receipt_index_csv", "{provider} Receipt Index.csv", ["A"])],
    )


# --- the spec contract ----------------------------------------------------

def test_spec_rejects_a_route_to_an_undeclared_folder(tmp_path):
    with pytest.raises(ValueError, match="unknown folder"):
        AppSpec(provider="X", project_dir=tmp_path,
                folders=[Folder("statements", "Statements")],
                routes={"Statement": "nope"})


def test_spec_rejects_an_undeclared_default_route(tmp_path):
    with pytest.raises(ValueError, match="not a declared folder"):
        AppSpec(provider="X", project_dir=tmp_path,
                folders=[Folder("statements", "Statements")],
                default_route="missing")


def test_slug_strips_punctuation():
    spec = AppSpec(provider="T-Mobile", project_dir=Path("."))
    assert spec.slug == "tmobile"
    assert AppSpec(provider="American Express", project_dir=Path(".")).slug == "americanexpress"


# --- folders --------------------------------------------------------------

def test_ensure_creates_only_precreate_folders(tmp_path):
    paths = storage.Paths(tmp_path / "out", document_spec(tmp_path))
    paths.ensure()
    made = sorted(d.name for d in (tmp_path / "out").iterdir() if d.is_dir())
    assert made == ["Backups", "Diagnostics", "Logs", "Manual Review",
                    "Statements", "Tax Documents"]
    # the two unfillable-by-default folders are absent, not empty
    assert "Insurance Documents" not in made
    assert "Other Documents" not in made


def test_routing_creates_a_rare_folder_on_demand(tmp_path):
    paths = storage.Paths(tmp_path / "out", document_spec(tmp_path))
    paths.ensure()
    assert not (tmp_path / "out" / "Insurance Documents").exists()
    got = paths.folder_for("Insurance Document")
    assert got.name == "Insurance Documents" and got.is_dir()


def test_unrouted_category_falls_back_to_the_default(tmp_path):
    paths = storage.Paths(tmp_path / "out", document_spec(tmp_path))
    assert paths.folder_for("Something New").name == "Other Documents"


def test_receipt_app_routes_by_purchase_type(tmp_path):
    paths = storage.Paths(tmp_path / "out", receipt_spec(tmp_path))
    assert paths.folder_for("Online").name == "Online"
    assert paths.folder_for("In-Store").name == "In-Store"


def test_receipt_app_refuses_to_guess_when_nothing_routes(tmp_path):
    """A receipt app declares no default, so an unknown purchase type is a
    bug to surface, not a document to file somewhere arbitrary."""
    paths = storage.Paths(tmp_path / "out", receipt_spec(tmp_path))
    with pytest.raises(KeyError, match="nothing routes"):
        paths.folder_for("Teleportation")


# --- csv + config ---------------------------------------------------------

def test_csv_filename_carries_the_provider_name(tmp_path):
    paths = storage.Paths(tmp_path / "out", document_spec(tmp_path))
    assert paths.document_index_csv.name == "T-Mobile Document Index.csv"
    assert paths.columns_for("document_index_csv")[0] == "Account Holder"


def test_load_config_applies_provider_defaults(tmp_path):
    spec = document_spec(tmp_path)
    storage.bind(spec)
    (tmp_path / "config.json").write_text('{"owner": "Sam"}', encoding="utf-8")
    cfg = storage.load_config(tmp_path / "config.json")
    assert cfg["owner"] == "Sam"           # explicit setting wins
    assert cfg["pilot_count"] == 5         # provider default
    assert cfg["min_pdf_bytes"] == 3000    # shared default
    assert cfg["profile_dir"].endswith("tmobile-browser-profile")


def test_using_the_core_unbound_is_a_clear_error():
    storage._SPEC = None
    with pytest.raises(RuntimeError, match="No AppSpec bound"):
        storage.spec()


def test_filename_uses_the_bound_provider(tmp_path):
    storage.bind(document_spec(tmp_path))
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-08-17", "august bill", "Statement") == \
        "2026-08-17 T-Mobile August Bill Statement.pdf"
    storage.set_filename_owner("Sam")
    assert storage.build_pdf_filename("2026-08-17", "august bill", "Statement") == \
        "2026-08-17 Sam T-Mobile August Bill Statement.pdf"
    storage.set_filename_owner("")
