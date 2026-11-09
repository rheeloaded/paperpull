"""The core's own tests: the spec contract and the folder/routing behavior
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


def test_missing_config_explains_itself(tmp_path):
    """A first run with no config.json used to die inside pathlib with
    FileNotFoundError, which told the user nothing."""
    spec = document_spec(tmp_path)
    (tmp_path / "config.example.json").write_text("{}", encoding="utf-8")
    storage.bind(spec)
    with pytest.raises(SystemExit) as e:
        storage.load_config(tmp_path / "config.json")
    message = str(e.value)
    assert "No config file at" in message
    assert "config.example.json config.json" in message


def test_malformed_config_explains_itself(tmp_path):
    storage.bind(document_spec(tmp_path))
    bad = tmp_path / "config.json"
    bad.write_text('{"owner": "Sam",}', encoding="utf-8")   # trailing comma
    with pytest.raises(SystemExit) as e:
        storage.load_config(bad)
    assert "not valid JSON" in str(e.value)


def test_config_saved_with_a_bom_still_loads(tmp_path):
    """Notepad writes UTF-8 with a BOM; that used to break json.load."""
    storage.bind(document_spec(tmp_path))
    cfg = tmp_path / "config.json"
    cfg.write_text('{"owner": "Sam"}', encoding="utf-8-sig")
    assert storage.load_config(cfg)["owner"] == "Sam"


def test_relative_output_dir_resolves_to_app_folder_when_cwd_is_outside(tmp_path, monkeypatch):
    """When a script is run from the parent/root folder, output_dir='.' must resolve
    to the app's own directory, not the parent/cwd."""
    app_dir = tmp_path / "Discover Statements"
    app_dir.mkdir()
    spec = document_spec(app_dir)
    storage.bind(spec)
    (app_dir / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = storage.load_config(app_dir / "config.json")
    paths = storage.Paths(Path(cfg["output_dir"]))

    assert paths.root == app_dir.resolve()
    paths.ensure()
    assert (app_dir / "Backups").is_dir()
    assert (app_dir / "Statements").is_dir()
    assert not (tmp_path / "Backups").exists()
    assert not (tmp_path / "Statements").exists()


def test_relative_output_dir_sibling_resolves_relative_to_app_folder(tmp_path, monkeypatch):
    """Multi-account configs like config.biz.json often specify '../App - biz'."""
    app_dir = tmp_path / "American Express Statements"
    app_dir.mkdir()
    biz_dir = tmp_path / "American Express Statements - biz"
    spec = document_spec(app_dir)
    storage.bind(spec)
    (app_dir / "config.biz.json").write_text(
        '{"output_dir": "../American Express Statements - biz"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = storage.load_config(app_dir / "config.biz.json")
    paths = storage.Paths(Path(cfg["output_dir"]))

    assert paths.root == biz_dir.resolve()


def test_documents_dir_for_matches_relative_output_dir_when_run_from_outside(tmp_path, monkeypatch):
    """documents_dir mapping works correctly even when output_dir='.' is loaded from outside."""
    app_dir = tmp_path / "Discover Statements"
    app_dir.mkdir()
    docs = tmp_path / "0GDrive" / "Discover Statements"
    spec = document_spec(app_dir)
    storage.bind(spec)
    (app_dir / "config.json").write_text(
        f'{{"output_dir": ".", "documents_dir": "{docs.as_posix()}"}}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = storage.load_config(app_dir / "config.json")
    paths = storage.Paths(Path(cfg["output_dir"]))

    assert paths.root == app_dir.resolve()
    assert paths.documents == docs.resolve()



def test_relative_profile_dir_resolves_to_the_config_folder(tmp_path, monkeypatch):
    """--open-browser from the repo root must open the same signed-in profile
    as a run from the app folder."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    storage.bind(document_spec(app_dir))
    (app_dir / "config.json").write_text(
        '{"output_dir": ".", "profile_dir": "./browser-profile"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = storage.load_config(app_dir / "config.json")

    assert Path(cfg["profile_dir"]) == app_dir / "browser-profile"


def test_the_server_checks_the_folder_that_is_written_to(tmp_path, monkeypatch):
    """On PaperPull Server the output_dir checked for links out is the one
    Paths writes to, read from the config's folder, not from the cwd."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    storage.bind(document_spec(app_dir))
    (app_dir / "config.json").write_text('{"output_dir": "../out"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path / "app")
    seen = []
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setattr(storage, "hold_to_the_server", lambda cfg, path: None)
    monkeypatch.setattr(storage, "refuse_links_out", lambda out, path: seen.append(out))
    monkeypatch.chdir(tmp_path.parent)  # somewhere else entirely

    cfg = storage.load_config(app_dir / "config.json")

    assert seen == [str(tmp_path / "out")]
    assert storage.Paths(Path(cfg["output_dir"])).root == tmp_path / "out"


def test_a_folder_reached_through_a_link_keeps_one_documents_key(tmp_path, monkeypatch):
    """A config under a linked folder (macOS /tmp, a Drive alias) maps its
    documents folder by the same key whether output_dir was "." or absolute."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    docs = tmp_path / "docs"
    storage.bind(document_spec(link))
    (link / "config.json").write_text(
        f'{{"output_dir": ".", "documents_dir": "{docs.as_posix()}"}}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    storage.load_config(link / "config.json")

    assert storage.documents_dir_for(str(link)) == str(docs)
    assert storage.Paths(link).documents == docs


def test_a_relative_documents_dir_is_still_refused(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    storage.bind(document_spec(app_dir))
    (app_dir / "config.json").write_text(
        '{"output_dir": ".", "documents_dir": "docs"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    storage.load_config(app_dir / "config.json")

    assert storage.documents_dir_for(str(app_dir)) == ""
