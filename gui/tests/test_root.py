"""Where the control panel looks for the downloaders.

An installed copy has no apps/ beside it, so the folder has to come from
somewhere else, and it has to survive an upgrade that replaces the program.
These pin down the order of precedence, what is remembered, and what the page
is allowed to set.

The endpoints are called directly rather than through a test client, so the
GUI's test suite needs nothing beyond what the GUI itself already needs.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A private settings file, so tests never touch the real one."""
    p = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: p)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    return p


def _installs(root: Path, n: int):
    """n folders that look like apps, because they hold an entry script."""
    for i in range(n):
        d = root / ("App %d" % i)
        d.mkdir(parents=True)
        (d / ("app%d_docs.py" % i)).write_text("", encoding="utf-8")
    return root


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _post(body):
    return asyncio.run(app_module.api_root_set(_Req(body)))


# -- precedence --------------------------------------------------------------

def test_the_default_is_the_repo_layout(settings):
    assert app_module.apps_root() == app_module._DEFAULT_ROOT
    assert app_module.root_source() == "default"


def test_a_saved_choice_beats_the_default(settings, tmp_path):
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"apps_root": str(tmp_path)}), encoding="utf-8")
    assert app_module.apps_root() == tmp_path
    assert app_module.root_source() == "settings"


def test_the_environment_beats_a_saved_choice(settings, tmp_path, monkeypatch):
    """The override exists for running from the repo, and it must win, or
    setting it would silently do nothing on a machine with a saved choice."""
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"apps_root": str(tmp_path / "saved")}), encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "env"))
    assert app_module.apps_root() == tmp_path / "env"
    assert app_module.root_source() == "environment"


def test_a_corrupt_settings_file_falls_back_rather_than_crashing(settings):
    settings.parent.mkdir(parents=True)
    settings.write_text("{ not json", encoding="utf-8")
    assert app_module.apps_root() == app_module._DEFAULT_ROOT


def test_settings_live_outside_the_install_folder(monkeypatch):
    """So an upgrade that replaces the program keeps the choice."""
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(app_module.sys, "platform", platform)
        p = app_module._settings_path()
        assert app_module.HERE not in p.parents, (platform, p)
        assert p.name == "settings.json"


# -- the page setting it ---------------------------------------------------

def test_a_real_folder_is_saved_and_counted(settings, tmp_path):
    root = _installs(tmp_path / "downloaders", 3)
    got = _post({"root": str(root)})
    assert got["apps"] == 3
    assert got["source"] == "settings"
    assert json.loads(settings.read_text(encoding="utf-8"))["apps_root"] == str(root.resolve())
    assert app_module.apps_root() == root.resolve()


def test_an_empty_folder_is_accepted_but_reported_as_empty(settings, tmp_path):
    """Pointing at a folder before moving the installs into it is a
    reasonable order of operations, so it is allowed and made obvious."""
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    assert _post({"root": str(empty)})["apps"] == 0


def test_a_folder_that_does_not_exist_is_refused(settings, tmp_path):
    with pytest.raises(fastapi.HTTPException) as e:
        _post({"root": str(tmp_path / "missing")})
    assert e.value.status_code == 400
    assert not settings.exists(), "it was saved despite being refused"


def test_a_relative_path_is_refused(settings):
    with pytest.raises(fastapi.HTTPException) as e:
        _post({"root": "Documents/downloaders"})
    assert e.value.status_code == 400


def test_an_empty_path_is_refused(settings):
    with pytest.raises(fastapi.HTTPException) as e:
        _post({"root": "   "})
    assert e.value.status_code == 400


def test_a_body_that_is_not_json_is_refused(settings):
    with pytest.raises(fastapi.HTTPException) as e:
        _post(ValueError("bad body"))
    assert e.value.status_code == 400


def test_surrounding_quotes_are_tolerated(settings, tmp_path):
    """Windows Explorer's "Copy as path" wraps the path in quotes, and pasting
    that is exactly what somebody will do."""
    root = _installs(tmp_path / "downloaders", 1)
    got = _post({"root": '"%s"' % root})
    assert got["apps"] == 1


def test_the_page_cannot_override_the_environment(settings, tmp_path, monkeypatch):
    """When APPS_ROOT is set, a saved choice would be ignored anyway. Refusing
    is better than saving something that appears to do nothing."""
    monkeypatch.setenv("APPS_ROOT", str(tmp_path))
    with pytest.raises(fastapi.HTTPException) as e:
        _post({"root": str(tmp_path)})
    assert e.value.status_code == 409


def test_changing_the_folder_forgets_the_cached_status_module(settings, tmp_path):
    """The status report is looked for relative to the root, so a cached
    answer for the old root would be wrong for the new one."""
    _installs(tmp_path / "a", 1)
    app_module._STATUS_MOD = False
    _post({"root": str(tmp_path / "a")})
    assert app_module._STATUS_MOD is None


# -- what counts as an install ---------------------------------------------

def test_only_folders_with_an_entry_script_count(tmp_path):
    root = _installs(tmp_path, 2)
    (root / "Not An App").mkdir()
    (root / "Not An App" / "notes.txt").write_text("", encoding="utf-8")
    (root / "loose_file.py").write_text("", encoding="utf-8")
    assert app_module._looks_like_installs(root) == 2


def test_a_missing_root_counts_as_zero(tmp_path):
    assert app_module._looks_like_installs(tmp_path / "nope") == 0


def test_the_packaged_app_never_defaults_inside_its_own_bundle(settings, monkeypatch):
    """On macOS the bundle sits under /Applications, where the system blocks
    writes, and on either platform an upgrade replaces it. The first-run
    screen offered ~/Documents/PaperPull while the header said the bundle."""
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    assert app_module.apps_root() == Path.home() / "Documents" / "PaperPull"
    assert app_module.root_source() == "default"


def test_a_packaged_install_is_not_told_to_run_setup(settings, tmp_path, monkeypatch):
    """No per-app venv is the normal state in the package, the bundled
    interpreter carries everything. The checkout-era hint about setup.bat
    showed on every app of a packaged install."""
    root = tmp_path / "installs"
    _installs(root, 1)
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"apps_root": str(root)}), encoding="utf-8")
    monkeypatch.setattr(app_module, "_is_packaged", lambda: False)
    checkout = app_module.discover_apps()
    assert all(a["needs_setup"] for a in checkout.values())
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    packaged = app_module.discover_apps()
    assert not any(a["needs_setup"] for a in packaged.values())


def test_on_windows_settings_live_in_roaming_appdata_not_beside_the_program(tmp_path, monkeypatch):
    """The installer puts the program in Local AppData. The settings file sat
    in the same folder for two releases and survived only because nothing
    happened to delete it. A Store install makes that folder read-only."""
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    p = app_module._settings_path()
    assert p == tmp_path / "Roaming" / "PaperPull" / "settings.json"


def test_a_settings_file_from_an_earlier_version_is_moved_once(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    old = tmp_path / "Local" / "PaperPull" / "settings.json"
    old.parent.mkdir(parents=True)
    old.write_text('{"apps_root": "D:/mine"}', encoding="utf-8")
    p = app_module._settings_path()
    assert p == tmp_path / "Roaming" / "PaperPull" / "settings.json"
    assert p.read_text(encoding="utf-8") == '{"apps_root": "D:/mine"}'
    assert not old.exists(), "the old copy must not linger to be read by mistake"
    # the program folder beside it is untouched
    assert (tmp_path / "Local" / "PaperPull").is_dir()
    # and the choice survives
    monkeypatch.delenv("APPS_ROOT", raising=False)
    assert app_module.apps_root() == Path("D:/mine")


def test_stopping_a_recording_writes_the_file_the_app_waits_for(settings, tmp_path, monkeypatch):
    """A recording has no natural end. Started from the panel the app's
    input is closed, so this file is the only way to say when to stop."""
    root = tmp_path / "installs"
    d = root / "Bank Statements"
    d.mkdir(parents=True)
    (d / "bank_docs.py").write_text("# entry\n", encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"apps_root": str(root)}), encoding="utf-8")
    out = asyncio.run(app_module.api_record_stop(_Req({"app": "Bank Statements"})))
    assert out["stopping"] is True
    assert (d / "Diagnostics" / ".stop-recording").is_file()


def test_a_recording_stop_follows_the_config_to_another_drive(settings, tmp_path, monkeypatch):
    root = tmp_path / "installs"
    d = root / "Bank Statements"
    d.mkdir(parents=True)
    (d / "bank_docs.py").write_text("# entry\n", encoding="utf-8")
    elsewhere = tmp_path / "D" / "Bank"
    elsewhere.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"output_dir": str(elsewhere)}),
                                   encoding="utf-8")
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"apps_root": str(root)}), encoding="utf-8")
    asyncio.run(app_module.api_record_stop(_Req({"app": "Bank Statements"})))
    assert (elsewhere / "Diagnostics" / ".stop-recording").is_file()


def test_an_unknown_app_cannot_be_told_to_stop(settings, tmp_path):
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"apps_root": str(tmp_path)}), encoding="utf-8")
    with pytest.raises(app_module.HTTPException) as e:
        asyncio.run(app_module.api_record_stop(_Req({"app": "../etc"})))
    assert e.value.status_code == 404


def test_stop_uses_the_app_the_recording_started_on():
    """The App list is not disabled during a run. Reading it back when Stop
    is pressed would write the sentinel into whichever provider happened to
    be selected, and the recording, watching its own folder, would never
    end."""
    js = app_module.HTML
    assert "body: JSON.stringify({ app: recordingApp })" in js
    assert "body: JSON.stringify({ app: $('app').value })" not in js
    assert "recordingApp = (action === 'record') ? app : null;" in js
    # And it is cleared both ways a run can finish, so the button cannot
    # fire against a recording that is already over.
    assert js.count("recordingApp = null;") >= 3


def test_the_panel_offers_record_and_tucks_it_behind_more():
    assert "record" in app_module.ACTIONS
    assert app_module.ACTIONS["record"]["flags"] == ["--record"]
    assert "record" in app_module.MORE_ACTIONS
