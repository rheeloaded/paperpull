"""On PaperPull Server a run and the panel hold an install's config to the
server's own places.

The config sits in /data, often a shared folder other people can write.
The run's own side is paperpull_core.storage.hold_to_the_server, tested in
core/tests/test_server_config_trust.py. Here a stand-in provider that
loads its config with the real core is started exactly the way the panel
starts a run, its interpreter, flags, environment and working folder, so
what the core sees is what a real run sees. The panel's own side is
server_mode.output_root, which keeps the run log and the records it reads
inside the data folder.

Every folder is a throwaway one under tmp_path, and the one program run is
the stand-in below.
"""
import functools
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app = pytest.importorskip("app")
import server_mode  # noqa: E402
from paperpull_core import storage as core_storage  # noqa: E402

ENTRY = "testco_docs.py"
CORE = str(Path(core_storage.__file__).resolve().parents[1])

# A provider that only loads its config, with the core this test imported,
# and writes down what it was given.
STAND_IN = """\
import json, sys
sys.path.insert(0, %r)
from pathlib import Path
from paperpull_core import storage
from paperpull_core.spec import AppSpec, DOCUMENT
spec = AppSpec(provider="Testco", project_dir=Path(__file__).resolve().parent, kind=DOCUMENT,
               url_settings={"base_url": ("testco.example",)})
storage.bind(spec)
args = sys.argv[1:]
path = Path(args[args.index("--config") + 1]) if "--config" in args else spec.project_dir / "config.json"
cfg = storage.load_config(path)
Path("loaded.json").write_text(json.dumps(
    {key: cfg.get(key) for key in ("output_dir", "profile_dir", "cdp_url", "base_url")}),
    encoding="utf-8")
print("loaded " + path.name)
# shipped --open-browser
""" % CORE


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    """An image-like tree with the stand-in as a shipped template, a data
    folder with one install of it, and a profiles volume. Returns the data
    folder and the install."""
    opt = tmp_path / "opt" / "paperpull"
    (opt / "gui").mkdir(parents=True)
    tmpl = opt / "templates" / "apps" / "testco"
    tmpl.mkdir(parents=True)
    (tmpl / ENTRY).write_text(STAND_IN, encoding="utf-8")
    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    (install / ENTRY).write_text("raise SystemExit('the /data copy never runs')\n", encoding="utf-8")
    (tmp_path / "profiles").mkdir()
    monkeypatch.setattr(app, "HERE", opt / "gui")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.delenv("PAPERPULL_DATA_DIR", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    return data, install


def configure(install: Path, name: str = "config.json", **changed) -> None:
    """A config as the panel writes it, with these settings changed."""
    account = "primary" if name == "config.json" else name[len("config."):-len(".json")]
    settings = {"owner": "", "output_dir": ".", "cdp_url": "http://127.0.0.1:9299",
                "profile_dir": server_mode.profile_for(install.name, account),
                "base_url": "https://name.testco.example"}
    settings.update(changed)
    (install / name).write_text(json.dumps(settings), encoding="utf-8")


def run(account: str = "primary") -> str:
    """Start a Discover the panel's way, and return everything it said,
    with the exit code at the end."""
    response = app._start_run("Testco Statements", account, "discover", ())
    chunks = []

    async def pump():
        async for part in response.body_iterator:
            chunks.append(part if isinstance(part, str) else part.decode("utf-8", "replace"))

    import anyio
    anyio.run(pump)
    return "".join(chunks)


def link_folder(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


# -- the profile a run signs in with -----------------------------------------------------

@pytest.mark.parametrize("account, name", [("primary", "config.json"),
                                           ("spouse", "config.spouse.json")])
def test_a_run_and_the_panel_name_an_accounts_profile_alike(tmp_path, monkeypatch, account, name):
    """Built in two places, the panel's profile_for and the core's
    server_profile_dir, so held to one answer here."""
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    install = tmp_path / "data" / "Testco Statements"
    assert core_storage.server_profile_dir(install / name) == server_mode.profile_for(
        install.name, account)


def test_a_config_as_the_panel_wrote_it_runs(layout):
    data, install = layout
    configure(install)
    said = run()
    assert "loaded config.json" in said
    loaded = json.loads((install / "loaded.json").read_text(encoding="utf-8"))
    assert loaded == {"output_dir": ".", "cdp_url": "http://127.0.0.1:9299",
                      "profile_dir": server_mode.profile_for("Testco Statements"),
                      "base_url": "https://name.testco.example"}
    assert (install / app.RUN_LOG).is_file()


def test_a_profile_moved_into_the_share_is_not_signed_in_with(layout):
    data, install = layout
    configure(install, profile_dir="./browser-profile")
    configure(install, "config.spouse.json", output_dir="../Testco Statements - spouse",
              profile_dir=str(data / "spouse-profile"))
    (data / "Testco Statements - spouse").mkdir()

    said = run()
    assert "profiles volume" in said
    loaded = json.loads((install / "loaded.json").read_text(encoding="utf-8"))
    assert loaded["profile_dir"] == server_mode.profile_for("Testco Statements")

    run("spouse")
    loaded = json.loads((install / "loaded.json").read_text(encoding="utf-8"))
    assert loaded["profile_dir"] == server_mode.profile_for("Testco Statements", "spouse")


# -- the browser a run drives and where it saves -------------------------------------------

@pytest.mark.parametrize("tampered", ["another machine's browser", "a name read two ways",
                                      "two folders up", "a folder elsewhere",
                                      "a site of somebody else's"])
def test_a_tampered_config_stops_the_run_before_it_does_anything(layout, tmp_path, tampered):
    data, install = layout
    changed = {"another machine's browser": {"cdp_url": "http://192.168.1.50:9222"},
               "a name read two ways": {"cdp_url": "http://evil.example\\@127.0.0.1:9222"},
               "two folders up": {"output_dir": "../.."},
               "a folder elsewhere": {"output_dir": str(tmp_path / "outside")},
               "a site of somebody else's": {"base_url": "https://name.testco.example.evil.example"}}[
        tampered]
    configure(install, **changed)
    said = run()
    assert "this run stopped" in said, said
    assert not (install / "loaded.json").exists()
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / app.RUN_LOG).exists()


def test_an_install_folder_linked_out_of_the_data_folder_stops_the_run(layout, tmp_path):
    """Somebody with the share put a link where the install was, to a folder
    outside the data folder. Its config says ".", as a fresh install's does,
    which leads through the link."""
    data, install = layout
    away = tmp_path / "away"
    away.mkdir()
    (away / ENTRY).write_text("raise SystemExit('never runs')\n", encoding="utf-8")
    configure(away)
    for item in install.iterdir():
        item.unlink()
    install.rmdir()
    link_folder(away, install)

    said = run()
    assert "outside" in said and "this run stopped" in said, said
    assert not (away / "loaded.json").exists()
    # The panel kept no run log through the link either.
    assert not (away / app.RUN_LOG).exists()
    with pytest.raises(ValueError):
        server_mode.output_root(install, "primary")


# -- the panel's own side ----------------------------------------------------------------

def test_the_panel_reads_and_writes_nothing_outside_the_data_folder(layout, tmp_path):
    data, install = layout
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "progress.json").write_text(json.dumps(
        {"a": {"pdf_filename": "x.pdf", "date": "2026-01-02"}}), encoding="utf-8")
    configure(install, output_dir=str(outside))
    with pytest.raises(ValueError):
        server_mode.output_root(install, "primary")
    assert app._naming_records(install) == []
    configure(install, output_dir="../Testco Statements - spouse")
    assert server_mode.output_root(install, "primary") == (data / "Testco Statements - spouse").resolve()


def test_on_the_desktop_the_panel_follows_the_config_as_before(layout, tmp_path, monkeypatch):
    data, install = layout
    monkeypatch.delenv("PAPERPULL_SERVER")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "progress.json").write_text(json.dumps(
        {"a": {"pdf_filename": "x.pdf", "date": "2026-01-02"}}), encoding="utf-8")
    configure(install, output_dir=str(outside))
    assert server_mode.output_root(install, "primary") == outside.resolve()
    assert [r["pdf_filename"] for r in app._naming_records(install)] == ["x.pdf"]


# -- a folder under the home folder (#166) ---------------------------------------------------
#
# A config written by hand can start a folder with "~", the home folder of
# whoever runs it. The panel reads each folder setting as a run does, so it
# finds the records, the profile and the documents where the run puts them.
# USERPROFILE is the home folder on Windows and HOME elsewhere, and every
# panel test has both pointed at a folder of its own (conftest _own_home).

@pytest.fixture()
def home_folder(tmp_path):
    home = tmp_path / "home"
    assert Path(os.environ["USERPROFILE"]) == Path(os.environ["HOME"]) == home
    return home


def no_tilde_folder(tmp_path) -> bool:
    return [p for p in tmp_path.rglob("*") if p.name.startswith("~")] == []


def test_on_the_desktop_the_panel_reads_a_home_folder_as_a_run_does(layout, home_folder,
                                                                     tmp_path, monkeypatch):
    data, install = layout
    monkeypatch.delenv("PAPERPULL_SERVER")
    configure(install, output_dir="~/Example Statements", profile_dir="~/Example Profile",
              documents_dir="~/Watched")
    # What binding and loading a config set in the core, put back after.
    for name in ("_SPEC", "_CONFIG_READ", "_CONFIG_GIVEN", "_FILENAME_PATTERN",
                 "_PATTERN_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    monkeypatch.setattr(core_storage, "_DOCUMENTS", dict(core_storage._DOCUMENTS))
    from paperpull_core.spec import AppSpec, DOCUMENT
    core_storage.bind(AppSpec(provider="Testco", project_dir=install, kind=DOCUMENT))
    monkeypatch.chdir(install)
    ran = core_storage.load_config(install / "config.json")
    out = home_folder / "Example Statements"
    assert Path(ran["output_dir"]) == out
    assert Path(ran["profile_dir"]) == home_folder / "Example Profile"
    assert Path(ran["documents_dir"]) == home_folder / "Watched"

    assert server_mode.output_root(install, "primary") == out.resolve()
    assert app._naming_output(install) == out
    meta = {"name": "Testco Statements", "dir": str(install), "accounts": ["primary"]}
    assert home_folder / "Example Profile" in app._profiles_known({"Testco Statements": meta})
    assert home_folder / "Example Profile" in app._not_for_documents(meta, "primary")
    assert app._documents_in_use(meta, "primary", out) == str(home_folder / "Watched")
    assert no_tilde_folder(tmp_path)


def test_on_the_server_a_home_folder_is_outside_the_data_folder_for_a_run_and_the_panel(
        layout, home_folder, tmp_path):
    data, install = layout
    configure(install, output_dir="~/Statements")
    said = run()
    assert "outside" in said and "this run stopped" in said, said
    assert not (install / "loaded.json").exists()
    with pytest.raises(ValueError):
        server_mode.output_root(install, "primary")
    assert no_tilde_folder(tmp_path)


@pytest.mark.parametrize("written", ["~", "~/Example", "~\\Example", "~archive", "x/~",
                                     "", ".", "./~", "../Example - biz", 7, None])
def test_the_panel_and_a_run_read_a_home_folder_alike(home_folder, written, monkeypatch):
    """Read in four places, the core's storage.with_home, the panel's
    server_mode.with_home, and add_account's and upgrade's, which run where
    no core is beside them, so held to one answer here. Windows takes
    "~name" for the folder beside the home folder named name when the home
    folder is named for USERNAME, so that is set to match, and only "~name"
    read as a folder of that name gives one answer for each."""
    monkeypatch.setenv("USERNAME", home_folder.name)
    expected = core_storage.with_home(written)
    if written == "~archive":
        assert expected == "~archive"
    assert server_mode.with_home(written) == expected
    assert tool("add_account").with_home(written) == expected
    assert tool("upgrade").with_home(written) == expected


@functools.lru_cache(maxsize=None)
def tool(name: str):
    """tools/<name>.py, loaded once as the panel loads it."""
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "tools" / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("paperpull_%s_home_folder" % name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_second_person_beside_a_folder_under_the_home_folder_gets_theirs_there(
        tmp_path, home_folder, monkeypatch):
    """Add a person makes the new person's folder beside the first one's,
    which is under the home folder, and never a folder named "~" in the
    install."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    install = tmp_path / "installs" / "Example Statements"
    install.mkdir(parents=True)
    (install / "config.json").write_text(json.dumps({
        "output_dir": "~/Example Statements",
        "profile_dir": "~/Example Statements/browser-profile"}), encoding="utf-8")
    made = tool("add_account").make_config(install, "spouse")
    written = json.loads(made.read_text(encoding="utf-8"))
    theirs = home_folder / "Example Statements - spouse"
    assert theirs.is_dir()
    assert Path(core_storage.with_home(written["output_dir"])) == theirs
    assert server_mode.output_root(install, "spouse") == theirs.resolve()
    assert no_tilde_folder(tmp_path)


@pytest.mark.parametrize("written", ["~/Example Statements", "~archive", ".",
                                     "../Example Statements - biz"])
def test_a_history_move_reads_an_output_folder_as_a_run_does(tmp_path, home_folder, written):
    install = tmp_path / "Example Statements"
    as_a_run = Path(os.path.normpath(install / core_storage.with_home(written)))
    assert tool("migrate").output_dir_of(install, {"output_dir": written}, "Testco") == as_a_run


def test_an_upgrade_finds_a_browser_profile_under_the_home_folder(tmp_path, home_folder):
    install = tmp_path / "Example Statements"
    install.mkdir()
    (home_folder / "Example Profile").mkdir()
    (install / "config.json").write_text(json.dumps({"profile_dir": "~/Example Profile"}),
                                         encoding="utf-8")
    said = tool("upgrade").inspect(install)["warnings"]
    assert not [w for w in said if "browser profile" in w], said
