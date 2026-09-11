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
