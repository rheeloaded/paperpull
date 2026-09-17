"""paperpull.py, one command for every app.

Each app is one script and one flag. The dispatcher's whole job is to find
the right folder, the right interpreter and the right flag, and get out of
the way. These pin each of those, and that the panel and the terminal offer
the same commands, since the point of #23 was to stop having two answers.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import paperpull  # noqa: E402


def _app(root: Path, slug: str, provider: str, folder: str | None = None,
         login_flag: str = "--open-browser", venv: bool = False) -> Path:
    d = root / (folder or slug)
    d.mkdir(parents=True)
    (d / ("%s_docs.py" % slug)).write_text(
        'ap.add_argument("%s")\n' % login_flag, encoding="utf-8")
    (d / "storage.py").write_text('SPEC = AppSpec(\n    provider="%s",\n)\n' % provider,
                                  encoding="utf-8")
    if venv:
        py = d / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"")
        (d / ".venv" / "bin").mkdir()
        (d / ".venv" / "bin" / "python").write_bytes(b"")
    return d


@pytest.fixture
def root(tmp_path):
    _app(tmp_path, "pge", "PG&E", folder="PG&E Statements", venv=True)
    _app(tmp_path, "chase", "Chase")
    _app(tmp_path, "target", "Target", login_flag="--login")
    (tmp_path / "Removed").mkdir()
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    return tmp_path


# -- which app -----------------------------------------------------------------

def test_only_folders_with_an_entry_script_count(root):
    assert [d.name for d in paperpull.list_apps(root)] == \
        ["chase", "PG&E Statements", "target"]


def test_an_app_is_found_by_folder_slug_or_provider_in_any_case(root):
    for wanted in ("PG&E Statements", "pg&e statements", "pge", "PGE", "PG&E"):
        assert paperpull.find_app(root, wanted).name == "PG&E Statements", wanted
    assert paperpull.find_app(root, "Chase").name == "chase"


def test_an_unknown_app_says_so_and_points_at_list(root):
    with pytest.raises(SystemExit, match="No app called 'wells'.*list"):
        paperpull.find_app(root, "wells")


def test_an_ambiguous_name_lists_the_candidates_rather_than_guessing(root):
    _app(root, "chasebank", "Chase Bank")
    with pytest.raises(SystemExit, match="more than one app: chase, chasebank"):
        paperpull.find_app(root, "chas")


def test_an_empty_root_is_reported_not_searched(tmp_path):
    with pytest.raises(SystemExit, match="No apps under"):
        paperpull.find_app(tmp_path, "pge")


# -- how it runs ---------------------------------------------------------------

def test_the_apps_own_venv_is_preferred_and_this_python_is_the_fallback(root):
    assert paperpull.interpreter(root / "PG&E Statements").name == "python.exe"
    assert paperpull.interpreter(root / "chase") == Path(sys.executable)


def test_each_command_becomes_its_flag_and_extras_pass_through(root):
    argv = paperpull.build_argv(root / "chase", "all", None, ["--year", "2025", "--yes"])
    assert argv[1:] == ["chase_docs.py", "--all", "--year", "2025", "--yes"]
    assert paperpull.build_argv(root / "chase", "dry-run", None, [])[2:] == ["--dry-run"]


def test_login_opens_a_browser_for_cdp_apps_and_checks_for_the_other(root):
    assert paperpull.build_argv(root / "chase", "login", None, [])[2:] == ["--open-browser"]
    assert paperpull.build_argv(root / "target", "login", None, [])[2:] == ["--login"]


def test_a_second_account_maps_to_its_config_file(root):
    (root / "chase" / "config.spouse.json").write_text("{}", encoding="utf-8")
    argv = paperpull.build_argv(root / "chase", "pilot", "spouse", [])
    assert argv[2:] == ["--pilot", "--config", "config.spouse.json"]
    assert paperpull.build_argv(root / "chase", "pilot", "primary", [])[2:] == ["--pilot"]


def test_a_missing_account_is_refused_before_anything_runs(root):
    with pytest.raises(SystemExit, match="No config.spouse.json in chase"):
        paperpull.build_argv(root / "chase", "pilot", "spouse", [])


def test_main_runs_in_the_apps_folder_and_returns_its_exit_code(root, monkeypatch):
    seen = {}

    def fake_run(app_dir, argv):
        seen["cwd"], seen["argv"] = app_dir, argv
        return 7

    monkeypatch.setattr(paperpull, "run", fake_run)
    monkeypatch.setattr(paperpull, "has_core", lambda: True)
    rc = paperpull.main(["--root", str(root), "chase", "resume", "--max-docs", "3"])
    assert rc == 7
    assert seen["cwd"] == root / "chase"
    assert seen["argv"][1:] == ["chase_docs.py", "--resume", "--max-docs", "3"]


def test_no_venv_and_no_core_stops_with_the_setup_command(root, monkeypatch):
    monkeypatch.setattr(paperpull, "has_core", lambda: False)
    with pytest.raises(SystemExit, match="paperpull.py chase setup"):
        paperpull.main(["--root", str(root), "chase", "verify"])


def test_setup_makes_a_venv_installs_requirements_then_the_core(root, monkeypatch):
    calls = []
    monkeypatch.setattr(paperpull.subprocess, "call",
                        lambda argv, **kw: (calls.append(argv), 0)[1])
    monkeypatch.setattr(paperpull, "core_source", lambda: ["-e", "CORE"])
    (root / "chase" / "requirements.txt").write_text("playwright\n", encoding="utf-8")
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 0
    assert calls[0][1:] == ["-m", "venv", str(root / "chase" / ".venv")]
    assert calls[-1][-2:] == ["-e", "CORE"]
    assert any("requirements.txt" in " ".join(c) for c in calls)


def test_setup_stops_at_the_first_failed_step(root, monkeypatch):
    calls = []

    def fail_second(argv, **kw):
        calls.append(argv)
        return 0 if len(calls) < 2 else 1

    monkeypatch.setattr(paperpull.subprocess, "call", fail_second)
    monkeypatch.setattr(paperpull, "core_source", lambda: ["-e", "CORE"])
    assert paperpull.main(["--root", str(root), "chase", "setup"]) == 1
    assert len(calls) == 2


# -- where the apps are --------------------------------------------------------

def test_root_precedence_is_flag_then_environment_then_panel_then_checkout(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"apps_root": "%s"}' % (tmp_path / "panel").as_posix(),
                        encoding="utf-8")
    monkeypatch.setattr(paperpull, "settings_path", lambda: settings)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    assert paperpull.apps_root(None) == tmp_path / "panel"
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "env"))
    assert paperpull.apps_root(None) == tmp_path / "env"
    assert paperpull.apps_root(str(tmp_path / "flag")) == tmp_path / "flag"
    monkeypatch.delenv("APPS_ROOT")
    settings.unlink()
    assert paperpull.apps_root(None) == REPO / "apps"


# -- the panel and the terminal agree -------------------------------------------

def test_the_terminal_offers_every_command_the_panel_does():
    src = (REPO / "gui" / "app.py").read_text(encoding="utf-8")
    block = src[src.index("ACTIONS = {"):src.index("}", src.index("ACTIONS = {"))]
    panel = set(re.findall(r'^\s*"(\w+)":', block, re.M))
    assert panel, "could not read the panel's ACTIONS"
    assert panel <= set(paperpull.COMMANDS), panel - set(paperpull.COMMANDS)


def test_every_real_app_resolves_and_builds_a_command():
    """Against the checkout itself, so a new provider that breaks the naming
    convention is caught here rather than by the first person to type it."""
    apps = paperpull.list_apps(REPO / "apps")
    assert len(apps) >= 26
    for d in apps:
        assert paperpull.find_app(REPO / "apps", d.name) == d
        argv = paperpull.build_argv(d, "pilot", None, [])
        assert argv[1].endswith((".py",)) and argv[2] == "--pilot"
        assert paperpull.build_argv(d, "login", None, [])[2] in ("--open-browser", "--login")


# -- the launchers that are gone stay gone -------------------------------------

def test_an_app_ships_only_setup_and_login_as_double_click_files():
    """Two hundred and forty-four files that each called one script with one
    flag were deleted for #23. The dispatcher does that job. A new provider
    cloned from an old checkout would bring them back."""
    allowed = {"setup.bat", "setup.command", "login.bat", "login.command"}
    stray = []
    for app in sorted(d for d in (REPO / "apps").iterdir() if d.is_dir()):
        for f in app.iterdir():
            if f.suffix in (".bat", ".command") and f.name not in allowed:
                stray.append(str(f.relative_to(REPO)))
    assert not stray, "launchers that paperpull.py replaced: " + ", ".join(stray)


def test_no_app_doc_still_points_at_a_deleted_launcher():
    gone = re.compile(r"\b(run_pilot|run_all|resume|verify_documents|diagnose)\.(bat|command)\b")
    stale = []
    for f in (REPO / "apps").glob("*/*.md"):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if gone.search(line):
                stale.append("%s:%d" % (f.relative_to(REPO), i))
    for f in (REPO / "apps").glob("*/COMMANDS.txt"):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if gone.search(line):
                stale.append("%s:%d" % (f.relative_to(REPO), i))
    assert not stale, "docs still name a deleted launcher: " + ", ".join(stale)


def test_the_packaged_app_defaults_to_documents_not_its_templates(tmp_path, monkeypatch):
    here = tmp_path / "PaperPull.app" / "Contents" / "Resources"
    (here / "templates" / "apps").mkdir(parents=True)
    monkeypatch.setattr(paperpull, "HERE", here)
    monkeypatch.setattr(paperpull, "settings_path", lambda: tmp_path / "none.json")
    monkeypatch.delenv("APPS_ROOT", raising=False)
    assert paperpull.apps_root(None) == Path.home() / "Documents" / "PaperPull"


def test_on_windows_the_terminal_reads_the_panels_settings_from_roaming_first(tmp_path, monkeypatch):
    monkeypatch.setattr(paperpull.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    new = tmp_path / "Roaming" / "PaperPull" / "settings.json"
    old = tmp_path / "Local" / "PaperPull" / "settings.json"
    # nothing anywhere: the new location, so a later write lands there
    assert paperpull.settings_path() == new
    # only the old file, the panel has not run yet to move it: read it
    old.parent.mkdir(parents=True)
    old.write_text("{}", encoding="utf-8")
    assert paperpull.settings_path() == old
    # both: the new one wins
    new.parent.mkdir(parents=True)
    new.write_text("{}", encoding="utf-8")
    assert paperpull.settings_path() == new
