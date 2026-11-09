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


# --- where a relative folder is read from (#165) ----------------------------
#
# Every launcher starts a run in the app's own folder (the control panel,
# paperpull, login.bat, login.command and the server's panel), and the paths
# a run records are relative to it. Those runs keep each folder as written.

def an_install(tmp_path, name="Example Statements"):
    """An install as the control panel makes one, with a second person's
    config beside its own, as tools/add_account.py writes it."""
    install = tmp_path / name
    install.mkdir(parents=True)
    storage.bind(document_spec(install))
    (install / "config.json").write_text(
        '{"output_dir": ".", "profile_dir": "./browser-profile"}', encoding="utf-8")
    (install / "config.biz.json").write_text(
        '{"output_dir": "../%s - biz", "profile_dir": "../%s - biz/browser-profile"}'
        % (name, name), encoding="utf-8")
    return install


def link_to(folder, link):
    """Another name for a folder, a junction on Windows and a link elsewhere."""
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(folder), str(link))
    else:
        link.symlink_to(folder, target_is_directory=True)
    return link


@pytest.mark.parametrize("named,output,profile", [
    (None, ".", "./browser-profile"),
    ("config.biz.json", "../Example Statements - biz", "../Example Statements - biz/browser-profile"),
])
def test_a_run_started_in_its_own_folder_keeps_its_folders_as_written(
        tmp_path, monkeypatch, named, output, profile):
    """So every path it records reads as the ones runs before it recorded,
    relative to the install, which lets the install be moved."""
    install = an_install(tmp_path)
    monkeypatch.chdir(install)
    cfg = storage.load_config(named)
    assert (cfg["output_dir"], cfg["profile_dir"]) == (output, profile)
    paths = storage.Paths(Path(cfg["output_dir"]))
    assert paths.root == Path(output)
    assert not (paths.statements / "x.pdf").is_absolute()


def test_a_run_started_through_a_junction_to_its_folder_keeps_its_folders_as_written(
        tmp_path, monkeypatch):
    """An app's own folder is its file's folder with every link followed, and
    a launcher can start the run through a junction or a link to it."""
    install = an_install(tmp_path)
    storage.bind(document_spec(install.resolve()))
    monkeypatch.chdir(link_to(install, tmp_path / "Linked"))
    cfg = storage.load_config(None)
    assert (cfg["output_dir"], cfg["profile_dir"]) == (".", "./browser-profile")


def test_a_config_kept_in_another_folder_still_reads_its_folders_from_the_install(
        tmp_path, monkeypatch):
    """A config named by its full path from somewhere else, run in the app's
    folder, has always had its relative folders read from there, and its
    documents and records stay where they are."""
    install = an_install(tmp_path / "data")
    kept = tmp_path / "configs"
    kept.mkdir()
    (kept / "config.sam.json").write_text(
        '{"output_dir": "../Example Statements - sam"}', encoding="utf-8")
    monkeypatch.chdir(install)
    cfg = storage.load_config(kept / "config.sam.json")
    assert cfg["output_dir"] == "../Example Statements - sam"
    assert storage.Paths(Path(cfg["output_dir"])).root.resolve() == \
        (tmp_path / "data" / "Example Statements - sam").resolve()


def test_a_run_started_in_its_configs_folder_still_reads_its_folders_from_there(
        tmp_path, monkeypatch):
    """A config kept outside the app, run in its own folder, has always had
    "." read as that folder, and keeps it."""
    an_install(tmp_path / "installs")
    kept = tmp_path / "configs"
    kept.mkdir()
    (kept / "config.sam.json").write_text('{"output_dir": "."}', encoding="utf-8")
    monkeypatch.chdir(kept)
    cfg = storage.load_config(Path("config.sam.json"))
    assert cfg["output_dir"] == "."


def test_a_download_again_still_knows_the_copy_a_run_before_saved(tmp_path, monkeypatch):
    """A record saved before names its file relative to the install. An
    attempt that saves under that very name has its copy taken for the
    record's own only when the two paths read alike (saved_copy), and a
    copy that failed its check is then no longer vouched for as saved."""
    from types import SimpleNamespace
    from paperpull_core import saved_copy
    install = an_install(tmp_path)
    monkeypatch.chdir(install)
    cfg = storage.load_config(None)
    paths = storage.Paths(Path(cfg["output_dir"]))
    paths.ensure()
    progress = storage.JsonStore(paths.progress_json, paths.backups)
    name = "2026-01-31 Example Statement.pdf"
    progress.update("k", {"downloaded_ok": True, "state": "Completed",
                          "pdf_path": str(Path("Statements") / name)})
    attempt = {"state": "Needs Manual Review", "pdf_path": str(paths.statements / name)}
    assert saved_copy.holds(SimpleNamespace(progress=progress), "k", attempt) is False
    assert attempt["downloaded_ok"] is False


def test_a_run_started_elsewhere_reads_its_folders_from_the_config_folder(
        tmp_path, monkeypatch):
    """Its browser profile too, and its documents folder is judged against
    the output folder it uses, so one inside that folder's Logs is refused."""
    install = an_install(tmp_path)
    (install / "config.json").write_text(
        '{"output_dir": ".", "profile_dir": "./browser-profile", "documents_dir": "%s"}'
        % (install / "Logs" / "Documents").as_posix(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = storage.load_config(None)
    assert Path(cfg["output_dir"]) == install
    assert Path(cfg["profile_dir"]) == install / "browser-profile"
    assert cfg["documents_dir"] == ""
    storage.Paths(Path(cfg["output_dir"])).ensure()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Example Statements"]


def test_a_bare_config_name_is_the_one_where_the_run_starts_before_the_apps(
        tmp_path, monkeypatch):
    install = an_install(tmp_path / "installs")
    here = tmp_path / "here"
    here.mkdir()
    (here / "config.biz.json").write_text('{"output_dir": "."}', encoding="utf-8")
    monkeypatch.chdir(here)
    storage.load_config("config.biz.json")
    assert storage.config_read() == here / "config.biz.json"
    monkeypatch.chdir(tmp_path)
    cfg = storage.load_config("config.biz.json")
    assert storage.config_read() == install / "config.biz.json"
    assert Path(cfg["output_dir"]) == tmp_path / "installs" / "Example Statements - biz"


def test_a_config_named_with_a_folder_is_never_looked_for_in_the_apps_folder(
        tmp_path, monkeypatch):
    """Only the file named is read, so a name with a folder in it that is
    not where the run starts stops the run as before, though the app's own
    folder holds a file by that name."""
    install = an_install(tmp_path)
    (install / "people").mkdir()
    (install / "people" / "config.biz.json").write_text('{"output_dir": "."}',
                                                        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="No config file at"):
        storage.load_config(Path("people") / "config.biz.json")


def test_the_owner_asked_for_by_a_run_started_elsewhere_is_saved_in_the_config_it_read(
        tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    install = an_install(tmp_path)
    monkeypatch.chdir(tmp_path)
    cfg = storage.load_config(Path("config.biz.json"))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda *_a: "Dana Example")
    storage.ensure_owner(cfg, Path("config.biz.json"))
    saved = json.loads((install / "config.biz.json").read_text(encoding="utf-8"))
    assert saved["owner"] == "Dana Example"
    assert not (tmp_path / "config.biz.json").exists()

