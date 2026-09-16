"""Upgrading an existing install in place.

The bar is simple and absolute. Whatever else changes, the record of what has
already been downloaded must come through untouched, because that is the only
thing standing between an upgrade and re-downloading a decade of statements.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
upgrade = pytest.importorskip("upgrade")

HISTORY = {
    "id:1": {"state": "Completed", "downloaded_ok": True, "pdf_path": ""},
    "id:2": {"state": "Failed", "downloaded_ok": False, "pdf_path": ""},
}


def _install(root: Path, name: str, config: dict, history=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    if history is not None:
        (d / "progress.json").write_text(json.dumps(history, indent=2),
                                         encoding="utf-8")
    return d


def _old_config(port=9222):
    """What an install written by an older version actually looks like."""
    return {"owner": "", "output_dir": ".", "profile_dir": "./x-browser-profile",
            "cdp_url": "http://localhost:%d" % port, "min_pdf_bytes": 3000,
            "max_path_length": 240}


# -- the thing that must never break -----------------------------------------

def test_the_download_history_is_never_touched(tmp_path):
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    before = (d / "progress.json").read_bytes()
    upgrade.main(["--root", str(tmp_path), "--apply"])
    assert (d / "progress.json").read_bytes() == before


def test_a_check_writes_nothing_at_all(tmp_path):
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    cfg_before = (d / "config.json").read_bytes()
    hist_before = (d / "progress.json").read_bytes()
    upgrade.main(["--root", str(tmp_path)])
    assert (d / "config.json").read_bytes() == cfg_before
    assert (d / "progress.json").read_bytes() == hist_before


def test_an_unreadable_history_blocks_the_upgrade(tmp_path):
    """Better to stop than to upgrade around a file nobody can read, because
    the failure mode is re-downloading everything."""
    d = _install(tmp_path, "Bank", _old_config())
    (d / "progress.json").write_text("{ this is not json", encoding="utf-8")
    rc = upgrade.main(["--root", str(tmp_path), "--apply"])
    assert rc == 1
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert "localhost" in cfg["cdp_url"], "it changed something despite refusing"


# -- what it actually fixes ---------------------------------------------------

def test_localhost_is_replaced_because_it_can_resolve_to_ipv6_first(tmp_path):
    """A browser opened with --remote-debugging-port binds IPv4 only, while
    localhost resolves to ::1 first on a normal Windows machine. The attach
    then fails with connection-refused while the browser sits there
    listening."""
    d = _install(tmp_path, "Bank", _old_config(9231), HISTORY)
    upgrade.main(["--root", str(tmp_path), "--apply"])
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert cfg["cdp_url"] == "http://127.0.0.1:9231"


def test_settings_added_since_the_old_version_are_written_in(tmp_path):
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    upgrade.main(["--root", str(tmp_path), "--apply"])
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert cfg["browser"] == "auto"


def test_settings_the_user_chose_are_left_alone(tmp_path):
    """An upgrade that resets somebody's preferences is not an upgrade."""
    conf = _old_config()
    conf.update({"browser": "installed", "owner": "Someone",
                 "max_path_length": 180, "min_pdf_bytes": 9999})
    d = _install(tmp_path, "Bank", conf, HISTORY)
    upgrade.main(["--root", str(tmp_path), "--apply"])
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    assert cfg["browser"] == "installed"
    assert cfg["owner"] == "Someone"
    assert cfg["max_path_length"] == 180
    assert cfg["min_pdf_bytes"] == 9999


# -- safety -------------------------------------------------------------------

def test_the_previous_config_is_backed_up_before_anything_is_written(tmp_path):
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    upgrade.main(["--root", str(tmp_path), "--apply"])
    assert list((d / "Backups").glob("config.*.before-upgrade.bak"))


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    upgrade.main(["--root", str(tmp_path), "--apply"])
    once = (d / "config.json").read_bytes()
    upgrade.main(["--root", str(tmp_path), "--apply"])
    assert (d / "config.json").read_bytes() == once


def test_a_config_saved_from_notepad_still_loads(tmp_path):
    """Notepad writes a byte order mark, and json.loads rejects it. Somebody
    who edited a port by hand must not be told their install is broken."""
    d = _install(tmp_path, "Bank", _old_config(), HISTORY)
    raw = (d / "config.json").read_text(encoding="utf-8")
    (d / "config.json").write_text("﻿" + raw, encoding="utf-8")
    assert upgrade.main(["--root", str(tmp_path), "--apply"]) == 0
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8-sig"))
    assert cfg["cdp_url"].startswith("http://127.0.0.1")


def test_a_folder_that_is_not_an_install_is_ignored(tmp_path):
    (tmp_path / "Some Other Folder").mkdir()
    (tmp_path / "Some Other Folder" / "notes.txt").write_text("x", encoding="utf-8")
    _install(tmp_path, "Bank", _old_config(), HISTORY)
    assert upgrade.main(["--root", str(tmp_path), "--apply"]) == 0


def test_it_reports_what_can_be_resumed(tmp_path, capsys):
    """The number somebody actually wants to see before upgrading is how much
    history is about to carry over."""
    _install(tmp_path, "Bank", _old_config(), HISTORY)
    upgrade.main(["--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert "2 documents" in out
    assert "1 already downloaded" in out


# -- the core copy inside the venv --------------------------------------------
#
# Every install carries its own copy of paperpull_core. Nineteen of them once
# had a fresh entry script on top of a stale copy, and Login crashed in all of
# them over a keyword the copy had never heard of. The version string had not
# moved, so a check that read only the string called them current.

def _fake_repo_core(tmp_path, monkeypatch, files):
    repo = tmp_path / "repo-core" / "paperpull_core"
    repo.mkdir(parents=True)
    for name, body in files.items():
        (repo / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(upgrade, "REPO_CORE", repo)
    return repo


def _venv_core(install, files):
    pkg = install / ".venv" / "Lib" / "site-packages" / "paperpull_core"
    pkg.mkdir(parents=True)
    for name, body in files.items():
        (pkg / name).write_text(body, encoding="utf-8")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "browser.cpython-312.pyc").write_bytes(b"x")
    return pkg


def test_a_stale_core_copy_is_found_by_content_not_by_version(tmp_path, monkeypatch):
    _fake_repo_core(tmp_path, monkeypatch, {
        "__init__.py": '__version__ = "0.1.5"\n',
        "browser.py": "def open_signin_browser(profile, port, url, mode='auto'): ...\n"})
    d = _install(tmp_path, "Bank", {"cdp_url": "http://127.0.0.1:9222", "browser": "auto"}, HISTORY)
    _venv_core(d, {"__init__.py": '__version__ = "0.1.5"\n',
                   "browser.py": "def open_signin_browser(profile, port, url): ...\n"})
    report = upgrade.inspect(d)
    assert report["core"]["differs"] == ["browser.py"]
    assert report["core"]["have"] == "0.1.5" and report["core"]["want"] == "0.1.5"


def test_a_stale_core_copy_is_refreshed_and_the_old_one_kept(tmp_path, monkeypatch):
    new_browser = "def open_signin_browser(profile, port, url, mode='auto'): ...\n"
    _fake_repo_core(tmp_path, monkeypatch, {
        "__init__.py": '__version__ = "0.1.6"\n', "browser.py": new_browser})
    d = _install(tmp_path, "Bank", {"cdp_url": "http://127.0.0.1:9222", "browser": "auto"}, HISTORY)
    pkg = _venv_core(d, {"__init__.py": '__version__ = "0.1.5"\n',
                         "browser.py": "def open_signin_browser(profile, port, url): ...\n"})
    cfg_before = (d / "config.json").read_bytes()
    assert upgrade.main(["--root", str(tmp_path), "--apply"]) == 0
    assert (pkg / "browser.py").read_text(encoding="utf-8") == new_browser
    assert '"0.1.6"' in (pkg / "__init__.py").read_text(encoding="utf-8")
    assert not (pkg / "__pycache__").exists(), "stale bytecode would shadow the refresh"
    kept = list((d / "Backups").glob("core.*.before-upgrade"))
    assert len(kept) == 1
    assert "mode" not in (kept[0] / "browser.py").read_text(encoding="utf-8")
    assert not (kept[0] / "__pycache__").exists()
    # a core-only upgrade leaves the config exactly as it was
    assert (d / "config.json").read_bytes() == cfg_before
    assert (d / "progress.json").exists()


def test_a_current_core_copy_is_left_alone(tmp_path, monkeypatch):
    files = {"__init__.py": '__version__ = "0.1.6"\n', "browser.py": "x = 1\n"}
    _fake_repo_core(tmp_path, monkeypatch, files)
    d = _install(tmp_path, "Bank", {"cdp_url": "http://127.0.0.1:9222", "browser": "auto"}, HISTORY)
    _venv_core(d, files)
    assert upgrade.inspect(d)["core"] is None
    assert upgrade.main(["--root", str(tmp_path), "--apply"]) == 0
    assert not (d / "Backups").exists()


def test_an_install_without_a_venv_is_not_a_core_problem(tmp_path, monkeypatch):
    _fake_repo_core(tmp_path, monkeypatch, {"__init__.py": '__version__ = "0.1.6"\n'})
    d = _install(tmp_path, "Bank", {"cdp_url": "http://127.0.0.1:9222", "browser": "auto"}, HISTORY)
    assert upgrade.inspect(d)["core"] is None


def test_a_check_does_not_touch_the_core_copy(tmp_path, monkeypatch):
    _fake_repo_core(tmp_path, monkeypatch, {"__init__.py": '__version__ = "0.1.6"\n'})
    d = _install(tmp_path, "Bank", {"cdp_url": "http://127.0.0.1:9222", "browser": "auto"}, HISTORY)
    pkg = _venv_core(d, {"__init__.py": '__version__ = "0.1.5"\n'})
    upgrade.main(["--root", str(tmp_path)])
    assert '"0.1.5"' in (pkg / "__init__.py").read_text(encoding="utf-8")
