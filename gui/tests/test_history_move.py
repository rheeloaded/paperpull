"""Moving to another computer, from the control panel (#67).

Somebody who ran the desktop app and moved to PaperPull Server asked for
their providers and history to come along, so the server would not download
every document they already had, and hand each one to Paperless a second
time. Export history writes a file, and Import history on the other machine
sets up each provider and person it names, with their settings, and marks
what each already downloaded.

The panel's own handlers are called here as the page calls them, on a
throwaway folder for each computer.
"""
import asyncio
import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")
import server_mode  # noqa: E402

EXAMPLE = {"owner": "", "owner_in_filename": False, "output_dir": ".",
           "profile_dir": "./browser-profile", "browser": "auto",
           "cdp_url": "http://127.0.0.1:9299", "default_start_date": "",
           "min_pdf_bytes": 2000, "document_types": ["Statement"]}


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """The desktop panel, with its settings and two fake provider templates
    under tmp_path, and the history tool and add_account from this checkout."""
    settings = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: settings)
    for name in ("APPS_ROOT", "PAPERPULL_SERVER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    root = tmp_path / "templates" / "apps"
    for slug, provider, kind in (("bank", "Bank", "DOCUMENT"), ("shop", "Shop", "RECEIPT")):
        d = root / slug
        d.mkdir(parents=True)
        (d / ("%s_docs.py" % slug)).write_text("# the app\n", encoding="utf-8")
        (d / "storage.py").write_text(
            'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind),
            encoding="utf-8")
        (d / "config.example.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: root)
    monkeypatch.setattr(app_module, "_provider_notes", lambda: {})
    for name, value in (("_SAMPLE", None), ("_RUNNING", set()), ("_STATUS_MOD", None)):
        monkeypatch.setattr(app_module, name, value)
    return settings


def _use(root: Path):
    app_module._write_settings({"apps_root": str(root)})


def _config(install: Path, name="config.json") -> dict:
    return json.loads((install / name).read_text(encoding="utf-8"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _done(n=1, prefix="id"):
    return {"%s:%d" % (prefix, i): {"state": "Completed", "downloaded_ok": True,
                                    "pdf_path": "", "summary": "Statement"}
            for i in range(n)}


def old_computer(tmp_path) -> Path:
    """Bank with a pattern and a start date, Shop with a second person, each
    with a history, as the desktop app leaves them."""
    old = tmp_path / "old"
    app_module.create_install(old, "bank", owner="Pat Example")
    app_module.create_install(old, "shop", owner="Pat Example")
    bank = old / "Bank Statements"
    cfg = _config(bank)
    cfg.update(default_start_date="2021-01-01", cdp_url="http://127.0.0.1:9555",
               profile_dir=r"D:\Profiles\Bank", browser="installed",
               filename_pattern_statements="{date} {provider}")
    _write(bank / "config.json", cfg)
    _write(bank / "progress.json", _done(3))
    _use(old)
    _account({"app": "Shop Receipts", "label": "spouse", "owner": "Jamie Example"})
    _write(old / "Shop Receipts" / "progress.json", _done(2, "s"))
    _write(old / "Shop Receipts - spouse" / "progress.json", _done(4, "j"))
    return old


def _account(body):
    class Req:
        async def json(self):
            return body
    return asyncio.run(app_module.api_account(Req()))


class Upload:
    """A request carrying a history file, as the page sends it."""

    def __init__(self, data: bytes, root: str = "", length=None):
        self._raw = json.dumps({"file": base64.b64encode(data).decode("ascii"),
                                "root": root}).encode()
        self.headers = {"content-length": str(len(self._raw) if length is None else length)}

    async def stream(self):
        yield self._raw


def export() -> bytes:
    answer = app_module.api_history_export()
    assert answer.media_type == "application/zip"
    assert "attachment" in answer.headers["content-disposition"]
    return answer.body


def plan(data: bytes, root: str = "") -> dict:
    return asyncio.run(app_module.api_history_plan(Upload(data, root)))


def bring(data: bytes, root: str = "") -> dict:
    return asyncio.run(app_module.api_history_import(Upload(data, root)))


def _rows(answer: dict) -> list:
    return [(r["provider"], r["account"], r.get("action"), r.get("new"), r.get("marked"))
            for r in answer["rows"]]


# -- the whole point ---------------------------------------------------------------

def test_a_new_computer_gets_every_provider_person_setting_and_history(panel, tmp_path):
    old_computer(tmp_path)
    data = export()

    new = tmp_path / "new"
    _use(tmp_path / "nothing yet")
    got = bring(data, root=str(new))
    assert _rows(got) == [("Bank", "primary", "set up", 3, 0),
                          ("Shop", "primary", "set up", 2, 0),
                          ("Shop", "spouse", "add person", 4, 0)], got

    bank = new / "Bank Statements"
    cfg = _config(bank)
    assert cfg["owner"] == "Pat Example"
    assert cfg["default_start_date"] == "2021-01-01"
    assert cfg["filename_pattern_statements"] == "{date} {provider}"
    # This computer's own, from the template, never the other machine's.
    assert cfg["cdp_url"] == EXAMPLE["cdp_url"]
    assert cfg["profile_dir"] == EXAMPLE["profile_dir"]
    assert cfg["browser"] == "auto" and cfg["output_dir"] == "."
    # Both templates name 9299, and Bank was set up first.
    assert _config(new / "Shop Receipts")["cdp_url"] == "http://127.0.0.1:9300"
    spouse = _config(new / "Shop Receipts", "config.spouse.json")
    assert spouse["owner"] == "Jamie Example"
    assert spouse["cdp_url"] == "http://127.0.0.1:9310"     # its own port, as add_account gives

    for folder, n in (("Bank Statements", 3), ("Shop Receipts", 2), ("Shop Receipts - spouse", 4)):
        recs = json.loads((new / folder / "progress.json").read_text(encoding="utf-8"))
        assert len(recs) == n and all(r["downloaded_ok"] for r in recs.values()), folder
    assert app_module._read_settings()["apps_root"] == str(new.resolve()), \
        "the folder chosen on the welcome page is remembered, as Set up does"
    assert set(app_module.discover_apps()) == {"Bank Statements", "Shop Receipts"}


def test_the_plan_writes_nothing_and_says_what_the_import_then_does(panel, tmp_path):
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    _use(new)
    new.mkdir()
    before = app_module._read_settings()

    planned = plan(data)
    assert list(new.iterdir()) == []
    assert app_module._read_settings() == before
    assert _rows(planned) == _rows(bring(data))


def test_importing_twice_changes_nothing_the_second_time(panel, tmp_path):
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    _use(new)
    bring(data)
    first = {p: p.read_bytes() for p in new.rglob("*.json")}
    again = bring(data)
    assert {r["action"] for r in again["rows"]} == {"fill in"}
    assert all(r["new"] == 0 and r["marked"] == 0 for r in again["rows"])
    assert {p: p.read_bytes() for p in new.rglob("*.json")} == first


# -- what is already here ------------------------------------------------------------

def test_settings_are_never_written_over_a_provider_already_here(panel, tmp_path):
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    app_module.create_install(new, "bank", owner="Someone Here")
    _write(new / "Bank Statements" / "progress.json", _done(1, "here"))
    before = (new / "Bank Statements" / "config.json").read_bytes()
    _use(new)

    got = bring(data)
    assert got["rows"][0]["action"] == "fill in"
    assert (new / "Bank Statements" / "config.json").read_bytes() == before
    recs = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert set(recs) == {"here:0", "id:0", "id:1", "id:2"}, "nothing taken out, all added"
    assert list((new / "Bank Statements" / "Backups").glob("progress.*.before-import.bak"))


def test_a_person_whose_config_is_here_is_never_written_over(panel, tmp_path):
    """Their config is there and their history could not be read, so the
    tool did not list them. Setting them up again would write over
    somebody's account."""
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    app_module.create_install(new, "shop")
    (new / "Shop Receipts" / "config.spouse.json").write_text("{ not json", encoding="utf-8")
    _use(new)

    got = bring(data)
    spouse = [r for r in got["rows"] if r["account"] == "spouse"][0]
    assert spouse["action"] == "skipped" and "already has a person" in spouse["why"]
    assert (new / "Shop Receipts" / "config.spouse.json").read_text(encoding="utf-8") == "{ not json"


def test_a_persons_history_left_in_their_folder_is_added_to_never_written_over(panel, tmp_path):
    """Remove moves only the install, so a second person's folder can stay
    behind with their history. Adding the person on import found the folder
    and wrote the file's records over what it held."""
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    app_module.create_install(new, "shop")
    (new / "Shop Receipts - spouse").mkdir()
    _write(new / "Shop Receipts - spouse" / "progress.json", _done(1, "here"))
    _use(new)

    planned = plan(data)
    spouse = [r for r in planned["rows"] if r["account"] == "spouse"][0]
    assert (spouse["action"], spouse["new"], spouse["known"]) == ("add person", 4, 1)
    assert _rows(bring(data)) == _rows(planned)
    recs = json.loads((new / "Shop Receipts - spouse" / "progress.json").read_text(encoding="utf-8"))
    assert set(recs) == {"here:0", "j:0", "j:1", "j:2", "j:3"}
    assert (new / "Shop Receipts" / "config.spouse.json").is_file()


def test_a_folder_chosen_on_the_welcome_page_is_remembered_when_it_already_holds_them(
        panel, tmp_path):
    """The folder chosen already held the providers, synced from another
    computer, so every line was "already here". It was not remembered, and
    the panel stayed on its old folder, an empty welcome page."""
    old_computer(tmp_path)
    data = export()
    synced = tmp_path / "synced"
    for slug in ("bank", "shop"):
        app_module.create_install(synced, slug)
    _account_in(synced / "Shop Receipts", "spouse")
    _use(tmp_path / "somewhere empty")
    got = bring(data, root=str(synced))
    assert {r["action"] for r in got["rows"]} == {"fill in"}
    assert app_module._read_settings()["apps_root"] == str(synced.resolve())


def _account_in(install: Path, label: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "aa", Path(app_module.__file__).resolve().parents[1] / "tools" / "add_account.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.make_config(install, label)


def test_no_run_starts_while_an_import_writes_the_histories(panel, tmp_path, monkeypatch):
    """A run reads progress.json when it starts and writes it as it goes,
    so one started during an import wrote over what the import added."""
    old = old_computer(tmp_path)
    _use(old)
    monkeypatch.setattr(app_module, "setup_needed", lambda meta: "")

    def never(*a, **k):
        raise AssertionError("a run was started during an import")
    monkeypatch.setattr(app_module.subprocess, "Popen", never)

    async def said(answer):
        return "".join([c if isinstance(c, str) else c.decode() async for c in answer.body_iterator])

    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        answer = app_module._start_run("Bank Statements", "primary", "pilot", [])
        text = asyncio.run(said(answer))
    finally:
        app_module._IMPORTING.release()
    assert "being imported" in text and "event: done" in text
    assert app_module._RUNNING == set()


def test_no_import_starts_while_another_import_runs(panel, tmp_path):
    old_computer(tmp_path)
    data = export()
    _use(tmp_path / "new")
    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        with pytest.raises(fastapi.HTTPException) as e:
            bring(data)
    finally:
        app_module._IMPORTING.release()
    assert e.value.status_code == 409


def test_a_provider_this_version_lacks_is_skipped_and_says_why(panel, tmp_path):
    data = _hand_made([{"provider": "Nope", "kind": "DOCUMENT", "account": "primary",
                        "folder": "Nope Statements", "file": "apps/0/progress.json"}],
                      {"apps/0/progress.json": _done(1)})
    new = tmp_path / "new"
    new.mkdir()
    _use(new)
    got = bring(data)
    assert got["rows"][0]["action"] == "skipped"
    assert "has no Nope" in got["rows"][0]["why"]
    assert list(new.iterdir()) == []


# -- a file is somebody's, and may have been edited ------------------------------------

def _hand_made(apps: list, files: dict, schema=2) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"schema": schema, "source_root": "/x",
                                                "apps": apps}))
        for name, data in files.items():
            z.writestr(name, json.dumps(data))
    return buf.getvalue()


def test_a_file_cannot_choose_this_computers_folders_profile_browser_or_port(panel, tmp_path):
    data = _hand_made([{"provider": "Bank", "kind": "DOCUMENT", "account": "primary",
                        "folder": "Bank Statements", "file": "apps/0/progress.json",
                        "settings": {"owner": "Pat Example", "output_dir": r"C:\Windows",
                                     "profile_dir": "/etc", "cdp_url": "http://evil.example:1",
                                     "browser": "bundled", "min_pdf_bytes": [1]}},
                       {"provider": "Bank", "kind": "DOCUMENT", "account": "../../x",
                        "folder": "x", "file": "apps/1/progress.json"}],
                      {"apps/0/progress.json": _done(1), "apps/1/progress.json": _done(1)})
    new = tmp_path / "new"
    _use(new)
    got = bring(data)
    cfg = _config(new / "Bank Statements")
    assert cfg == dict(EXAMPLE, owner="Pat Example"), cfg
    assert got["rows"][1]["action"] == "skipped", "a label that is no label"
    assert [p.name for p in new.iterdir()] == ["Bank Statements"]


def test_something_that_is_not_a_history_file_is_refused_with_a_sentence(panel, tmp_path):
    _use(tmp_path / "new")
    with pytest.raises(fastapi.HTTPException) as e:
        bring(b"hello")
    assert e.value.status_code == 400 and "not a readable export" in e.value.detail


def test_a_file_far_larger_than_any_history_is_refused_before_it_is_read(panel, tmp_path):
    _use(tmp_path / "new")
    with pytest.raises(fastapi.HTTPException) as e:
        asyncio.run(app_module.api_history_import(
            Upload(b"x", length=app_module.HISTORY_MAX_BYTES + 1)))
    assert e.value.status_code == 413


def test_nothing_is_imported_while_a_provider_runs(panel, tmp_path, monkeypatch):
    old_computer(tmp_path)
    data = export()
    new = tmp_path / "new"
    _use(new)
    monkeypatch.setattr(app_module, "_RUNNING", {"Bank Statements"})
    with pytest.raises(fastapi.HTTPException) as e:
        bring(data)
    assert e.value.status_code == 409
    assert not new.exists()


def test_the_sample_is_neither_exported_nor_imported_into(panel, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_SAMPLE", tmp_path / "sample")
    route = {r.path: r for r in app_module.app.routes if getattr(r, "path", "").startswith("/api/history")}
    for path in ("/api/history/export", "/api/history/plan", "/api/history/import"):
        calls = {d.call for d in route[path].dependant.dependencies}
        assert app_module._not_in_sample in calls, path


# -- PaperPull Server ----------------------------------------------------------------

def test_on_the_server_it_goes_into_the_data_folder_and_profiles_into_their_volume(
        panel, tmp_path, monkeypatch):
    old_computer(tmp_path)
    data = export()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "data"))
    profiles = tmp_path / "profiles"

    got = bring(data, root=r"C:\anything the page sent")
    assert got["root"] == str(tmp_path / "data")
    shop = tmp_path / "data" / "Shop Receipts"
    assert Path(_config(shop)["profile_dir"]) == profiles / "Shop Receipts"
    assert Path(_config(shop, "config.spouse.json")["profile_dir"]) == \
        profiles / "Shop Receipts - spouse"
    assert (tmp_path / "data" / "Shop Receipts - spouse" / "progress.json").is_file()
    assert not (tmp_path / "anything the page sent").exists()


def test_on_the_server_no_history_is_read_or_written_outside_the_data_folder(
        panel, tmp_path, monkeypatch):
    """A config in the shared folder can name any folder. On the server an
    export reads no history from one outside the data folder, and an import
    writes none there."""
    old_computer(tmp_path)
    data = export()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    root = tmp_path / "data"
    monkeypatch.setenv("APPS_ROOT", str(root))
    bring(data)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "progress.json", _done(7, "x"))
    before = (outside / "progress.json").read_bytes()
    bank = root / "Bank Statements"
    _write(bank / "config.json", dict(_config(bank), output_dir=str(outside)))

    with zipfile.ZipFile(io.BytesIO(export())) as z:
        exported = json.loads(z.read("manifest.json"))
    assert [a["provider"] for a in exported["apps"] if a["provider"] == "Bank"] == []
    got = bring(data)
    assert [r["action"] for r in got["rows"] if r["provider"] == "Bank"] == ["skipped"]
    assert (outside / "progress.json").read_bytes() == before
    assert sorted(p.name for p in outside.iterdir()) == ["progress.json"]


def test_on_the_server_an_import_never_writes_a_history_through_a_link(
        panel, tmp_path, monkeypatch):
    """The history was written to progress.json.tmp, a fixed name, then
    moved into place, so on the server a link left at that name in the
    shared folder had the import write the records wherever it led."""
    old = old_computer(tmp_path)
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    root = tmp_path / "data"
    monkeypatch.setenv("APPS_ROOT", str(root))
    bring(export_from(old, monkeypatch))
    canary = tmp_path / "server.json"
    canary.write_text('{"password": "kept"}', encoding="utf-8")
    bank = root / "Bank Statements"
    import os
    os.link(canary, bank / "progress.json.tmp")

    _write(old / "Bank Statements" / "progress.json", _done(6))
    got = bring(export_from(old, monkeypatch))
    assert [r.get("new") for r in got["rows"] if r["provider"] == "Bank"] == [3]
    assert canary.read_text(encoding="utf-8") == '{"password": "kept"}'
    assert len(json.loads((bank / "progress.json").read_text(encoding="utf-8"))) == 6


def export_from(old: Path, monkeypatch) -> bytes:
    """An export of the old computer, made as the desktop makes it."""
    with monkeypatch.context() as m:
        m.delenv("PAPERPULL_SERVER", raising=False)
        m.delenv("APPS_ROOT", raising=False)
        _use(old)
        return export()


def test_the_export_leaves_no_copy_behind(panel, tmp_path):
    """On the server the root is a shared folder, so the file is made in
    memory and handed to the browser, never written beside the documents."""
    old = old_computer(tmp_path)
    before = sorted(p for p in old.rglob("*"))
    data = export()
    assert sorted(p for p in old.rglob("*")) == before
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    assert [(a["provider"], a["account"]) for a in manifest["apps"]] == [
        ("Bank", "primary"), ("Shop", "primary"), ("Shop", "spouse")]


# -- every real provider -------------------------------------------------------------

def test_every_provider_comes_across_with_its_history_and_this_computers_settings(
        tmp_path, monkeypatch):
    """Each provider this checkout ships, set up on one computer with a
    history and moved to another. Each arrives set up, with its history
    marked as downloaded, the name that was given, and its own template's
    folders, profile, browser and port."""
    settings = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: settings)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_RUNNING", set())
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    providers = app_module.list_providers()
    assert len(providers) > 60
    old, new = tmp_path / "old", tmp_path / "new"
    for p in providers:
        app_module.create_install(old, p["slug"], owner="Pat Example")
        inst = old / p["folder"]
        cfg = _config(inst)
        cfg.update(cdp_url="http://127.0.0.1:1", profile_dir="/elsewhere", browser="bundled")
        _write(inst / "config.json", cfg)
        _write(inst / "progress.json", _done(2, p["slug"]))
    _use(old)
    data = export()

    got = bring(data, root=str(new))
    assert [r["action"] for r in got["rows"]] == ["set up"] * len(providers), \
        [r for r in got["rows"] if r["action"] != "set up"]
    templates = app_module._templates_root()
    for p in providers:
        inst = new / p["folder"]
        example = json.loads((templates / p["slug"] / "config.example.json").read_text(encoding="utf-8"))
        cfg = _config(inst)
        for key in ("output_dir", "profile_dir", "cdp_url", "browser"):
            assert cfg.get(key) == example.get(key), (p["slug"], key)
        assert cfg["owner"] == "Pat Example", p["slug"]
        recs = json.loads((inst / "progress.json").read_text(encoding="utf-8"))
        assert len(recs) == 2 and all(r["downloaded_ok"] for r in recs.values()), p["slug"]


def test_no_setting_that_names_a_computer_travels_for_any_provider():
    """A setting is carried when its provider's config.example.json lists it.
    A new one that names a folder, a file, a profile or an address would
    then go to another computer where it means nothing, so each is either
    kept home in MACHINE_KEYS or known here to belong to the account."""
    migrate = app_module._migrate_module()
    belongs_to_the_account = {"base_url"}       # UKG's employer address
    templates = app_module._templates_root()
    seen = []
    for d in sorted(templates.iterdir()):
        if not (d / "config.example.json").is_file():
            continue
        for key in migrate.settings_allowed(d):
            if key in belongs_to_the_account:
                continue
            if key.endswith(("_dir", "_folder", "_path", "_file", "_profile", "_url", "_port")):
                seen.append((d.name, key))
    assert not seen, seen
