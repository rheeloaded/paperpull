"""The panel's update check, and installing an update on a Mac.

Nothing here reaches the network or touches a real app. GitHub's answer is
written out by hand, the download is a few bytes, and the swap script is run
for real on folders in tmp_path.
"""
import asyncio
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
updater = pytest.importorskip("updater")
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")


def release(version="0.61.0", arch="arm64", **over):
    name = "PaperPull-%s-%s.dmg" % (version, arch)
    data = {
        "tag_name": "v" + version, "draft": False, "prerelease": False,
        "published_at": "2026-11-05T10:00:00Z", "body": "Fixes things.",
        "assets": [{"name": name, "size": 10, "digest": "sha256:" + "a" * 64,
                    "browser_download_url": updater.DOWNLOAD_PREFIX + "v%s/%s" % (version, name)}],
    }
    data.update(over)
    return data


# -- versions ---------------------------------------------------------------

def test_versions_compare_as_numbers_not_text():
    assert updater.is_newer("0.61.0", "0.60.1")
    assert updater.is_newer("0.100.0", "0.60.1")
    assert updater.is_newer("1.0.0", "0.99.99")
    assert not updater.is_newer("0.60.1", "0.60.1")
    assert not updater.is_newer("0.60.0", "0.60.1")


def test_a_version_that_is_not_one_is_never_newer():
    for bad in ("", None, "latest", "0.61", "0.61.0-rc1", "../0.61.0"):
        assert not updater.is_newer(bad, "0.60.1")


# -- reading a release ------------------------------------------------------

def test_the_release_for_this_mac_is_picked_with_its_checksum():
    rel = updater.read_release(release(), "arm64")
    assert rel["version"] == "0.61.0"
    assert rel["page"] == updater.RELEASE_PAGE + "v0.61.0"
    assert rel["asset"]["sha256"] == "a" * 64
    assert rel["asset"]["name"] == "PaperPull-0.61.0-arm64.dmg"


def test_the_other_architecture_is_not_offered():
    assert updater.read_release(release(arch="x86_64"), "arm64")["asset"] is None


@pytest.mark.parametrize("change", [
    {"digest": None},                                  # GitHub recorded none
    {"digest": "sha1:" + "a" * 40},
    {"digest": "sha256:xyz"},
    {"browser_download_url": "https://evil.example/PaperPull-0.61.0-arm64.dmg"},
    {"browser_download_url": "https://github.com/someone/else/releases/download/v0.61.0/PaperPull-0.61.0-arm64.dmg"},
    {"size": 0},
    {"size": 5 * 1024 ** 3},
])
def test_an_asset_that_cannot_be_proved_is_not_installable(change):
    data = release()
    data["assets"][0].update(change)
    assert updater.read_release(data, "arm64")["asset"] is None


@pytest.mark.parametrize("over", [
    {"tag_name": "nightly"}, {"tag_name": "v1.2"}, {"draft": True}, {"prerelease": True}])
def test_a_release_that_is_not_a_plain_version_is_refused(over):
    with pytest.raises(updater.UpdateError):
        updater.read_release(release(**over), "arm64")


# -- who may be talked to ---------------------------------------------------

def test_only_github_hosts_are_allowed():
    ok = updater._host_ok
    assert ok("https://api.github.com/repos/x/y")
    assert ok("https://github.com/x/y/releases/download/v1/a.dmg")
    assert ok("https://objects.githubusercontent.com/abc")
    assert ok("https://release-assets.githubusercontent.com/abc")
    assert not ok("https://raw.githubusercontent.com/someone/x/main/PaperPull.dmg")
    assert not ok("https://gist.githubusercontent.com/x")
    assert not ok("https://evil.example\\.github.com/x")     # a browser goes to evil.example
    assert not ok("https://user@github.com/x")
    assert not ok("https://github.com:8443/x")
    assert not ok("http://github.com/x")                     # not TLS
    assert not ok("https://github.com.evil.example/x")
    assert not ok("https://evilgithubusercontent.com/x")    # no dot before the suffix
    assert not ok("file:///etc/passwd")


# -- downloading ------------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, body):
    monkeypatch.setattr(updater, "_open", lambda url, timeout=20: _Resp(body))


def test_a_download_that_matches_is_kept(tmp_path, monkeypatch):
    body = b"disk image"
    _serve(monkeypatch, body)
    asset = {"url": "u", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    seen = []
    updater.download(asset, tmp_path / "a.dmg", lambda d, t: seen.append((d, t)))
    assert (tmp_path / "a.dmg").read_bytes() == body
    assert seen[-1] == (len(body), len(body))
    assert not (tmp_path / "a.dmg.part").exists()


@pytest.mark.parametrize("body, size, sha_of", [
    (b"disk image", 10, b"something else"),    # the right size, the wrong bytes
    (b"disk image", 5, b"disk image"),         # more than GitHub said
    (b"disk", 10, b"disk image"),              # stopped early
])
def test_a_download_that_does_not_match_leaves_nothing(tmp_path, monkeypatch, body, size, sha_of):
    _serve(monkeypatch, body)
    asset = {"url": "u", "size": size, "sha256": hashlib.sha256(sha_of).hexdigest()}
    # A folder of its own, as the panel's tests keep their home in tmp_path.
    where = tmp_path / "download"
    where.mkdir()
    with pytest.raises(updater.UpdateError):
        updater.download(asset, where / "a.dmg")
    assert list(where.iterdir()) == []


# -- where the copy lives ---------------------------------------------------

def test_a_bundle_is_recognised_by_its_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    app = tmp_path / "PaperPull.app"
    (app / "Contents" / "Resources" / "gui").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text("x")
    assert updater.bundle_path(app / "Contents" / "Resources" / "gui") == app


def test_a_checkout_is_not_a_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    (tmp_path / "repo" / "gui").mkdir(parents=True)
    assert updater.bundle_path(tmp_path / "repo" / "gui") is None
    ok, why = updater.can_install(None)
    assert not ok and why


def test_an_unsigned_copy_never_replaces_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_team_id", lambda app: "")
    ok, why = updater.can_install(tmp_path)
    assert not ok and "not signed" in why


# -- proving the new app ----------------------------------------------------

def _fake_app(path, version):
    (path / "Contents" / "Resources").mkdir(parents=True)
    (path / "Contents" / "Resources" / "VERSION").write_text(version + "\n")
    return path


def _ok(*a, **k):
    return subprocess.CompletedProcess(a, 0, "", "")


def test_the_new_app_must_be_the_version_and_the_same_publisher(tmp_path, monkeypatch):
    old = _fake_app(tmp_path / "old.app", "0.60.1")
    new = _fake_app(tmp_path / "new.app", "0.61.0")
    monkeypatch.setattr(updater, "_run", _ok)
    teams = {str(old): "TEAM1", str(new): "TEAM1"}
    monkeypatch.setattr(updater, "_team_id", lambda app: teams[str(app)])
    updater.verify_app(new, old, "0.61.0")

    with pytest.raises(updater.UpdateError, match="not 0.62.0"):
        updater.verify_app(new, old, "0.62.0")

    teams[str(new)] = "TEAM2"
    with pytest.raises(updater.UpdateError, match="same publisher"):
        updater.verify_app(new, old, "0.61.0")

    teams[str(new)] = ""
    with pytest.raises(updater.UpdateError, match="same publisher"):
        updater.verify_app(new, old, "0.61.0")


def test_a_bad_signature_or_gatekeeper_refusal_stops_it(tmp_path, monkeypatch):
    old = _fake_app(tmp_path / "old.app", "0.60.1")
    new = _fake_app(tmp_path / "new.app", "0.61.0")
    monkeypatch.setattr(updater, "_team_id", lambda app: "TEAM1")
    for failing in ("codesign", "spctl"):
        def run(cmd, timeout=300, failing=failing):
            return subprocess.CompletedProcess(cmd, 1 if failing in cmd[0] else 0, "", "")
        monkeypatch.setattr(updater, "_run", run)
        with pytest.raises(updater.UpdateError):
            updater.verify_app(new, old, "0.61.0")


# -- the swap, for real -----------------------------------------------------

def _swap(tmp_path, pid, *, old_exists=True, staged=True):
    parent = tmp_path / "Applications"
    parent.mkdir(exist_ok=True)
    old = parent / "PaperPull.app"
    if old_exists:
        old.mkdir()
        (old / "v").write_text("old")
    new = parent / ".PaperPull.new.app"
    if staged:
        new.mkdir()
        (new / "v").write_text("new")
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    script = work / "swap.sh"
    # `open` is stubbed so the test opens nothing.
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "open").write_text('#!/bin/bash\necho "$@" >> "%s"\n' % (tmp_path / "opened"))
    (bindir / "open").chmod(0o755)
    script.write_text(updater.SWAP_SCRIPT)
    script.chmod(0o700)
    log = tmp_path / "update.log"
    env = {"PATH": "%s:/usr/bin:/bin" % bindir}
    subprocess.run(["/bin/bash", str(script), str(pid), str(old), str(new),
                    str(parent / ".PaperPull.old.app"), str(log)], env=env, timeout=30)
    return parent, old, new, work, log


def _gone_pid():
    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()
    return p.pid


@pytest.mark.skipif(sys.platform == "win32", reason="the swap script is for the Mac")
def test_the_swap_puts_the_new_app_in_place_and_opens_it(tmp_path):
    parent, old, new, work, log = _swap(tmp_path, _gone_pid())
    assert (old / "v").read_text() == "new"
    assert not new.exists() and not (parent / ".PaperPull.old.app").exists()
    assert str(old) in (tmp_path / "opened").read_text()
    assert not work.exists()          # it cleans up after itself
    assert "replaced" in log.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="the swap script is for the Mac")
def test_if_the_new_app_cannot_be_placed_the_old_one_comes_back(tmp_path):
    parent, old, new, work, log = _swap(tmp_path, _gone_pid(), staged=False)
    assert (old / "v").read_text() == "old"
    assert not (parent / ".PaperPull.old.app").exists()
    assert "old one is back" in log.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="the swap script is for the Mac")
def test_it_waits_for_the_panel_to_exit_before_touching_anything(tmp_path):
    waiter = subprocess.Popen(["/bin/sleep", "1.5"])
    # A child nobody collects stays a zombie, which still answers kill -0.
    # The panel's parent collects it the moment it exits.
    threading.Thread(target=waiter.wait, daemon=True).start()
    t = time.time()
    parent, old, new, work, log = _swap(tmp_path, waiter.pid)
    assert time.time() - t >= 1.0
    assert (old / "v").read_text() == "new"


# -- the panel's answers ----------------------------------------------------

@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(app_module, "VERSION", "0.60.1")
    monkeypatch.setattr(app_module, "_update_ability", {})
    monkeypatch.setattr(updater, "bundle_path", lambda *a: None)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(updater, "offered", lambda *a: True)
    calls = []

    def fetch(url):
        calls.append(url)
        return release("0.61.0", updater.architecture())
    monkeypatch.setattr(updater, "fetch_json", fetch)
    updater.INSTALL.reset()
    return tmp_path, calls


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _check():
    return asyncio.run(app_module.api_update_check())


def _setting(on):
    return asyncio.run(app_module.api_update_setting(_Req({"check": on})))


def test_it_is_off_and_asks_nobody_until_the_person_presses_the_button(panel):
    _, calls = panel
    state = app_module.api_update()
    assert calls == [] and state["enabled"] is False and not state["newer"]
    with pytest.raises(fastapi.HTTPException) as e:
        _check()
    assert e.value.status_code == 409 and calls == []


def test_turning_it_on_asks_nobody(panel):
    _, calls = panel
    state = _setting(True)
    assert state["enabled"] is True and calls == []
    app_module.api_update()
    assert calls == []


def test_each_press_asks_once_and_nothing_else_does(panel):
    tmp, calls = panel
    _setting(True)
    state = _check()
    assert len(calls) == 1
    assert state["newer"] and state["latest"] == "0.61.0"
    assert state["page"] == updater.RELEASE_PAGE + "v0.61.0"
    for _ in range(3):
        app_module.api_update()                 # what the page does when it opens
    assert len(calls) == 1
    _check()
    assert len(calls) == 2
    saved = json.loads((tmp / "settings.json").read_text())
    assert saved["update_check"] is True


def test_turning_it_off_forgets_what_it_learned(panel):
    tmp, _ = panel
    _setting(True)
    _check()
    state = _setting(False)
    assert not state["newer"] and not state["enabled"]
    saved = json.loads((tmp / "settings.json").read_text())
    assert "update_latest" not in saved and saved["update_check"] is False


def test_a_kept_answer_is_not_shown_once_the_check_is_off(panel):
    tmp, _ = panel
    (tmp / "settings.json").write_text(json.dumps(
        {"update_check": False, "update_latest": {"version": "9.0.0", "installable": True}}))
    assert not app_module.api_update()["newer"]


def test_a_failed_check_says_so(panel, monkeypatch):
    def down(url):
        raise updater.UpdateError("could not reach GitHub: offline")
    monkeypatch.setattr(updater, "fetch_json", down)
    _setting(True)
    with pytest.raises(fastapi.HTTPException) as e:
        _check()
    assert e.value.status_code == 502 and "offline" in e.value.detail


def test_the_page_asks_github_only_from_the_button():
    """Opening the page reads /api/update, which asks nobody. The one call
    that reaches GitHub is the button's, and its label names github.com."""
    js = (Path(app_module.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    html = (Path(app_module.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert js.count("'/api/update/check'") == 1
    check = js[js.index("async function updCheck()"):]
    check = check[:check.index("\n}\n")]
    assert "'/api/update/check'" in check
    assert "'upd-check': () => updCheck()," in js
    assert re.search(r'data-do="upd-check"[^>]*>Check github\.com for an update<', html)
    assert "once a day" not in js + html


def test_the_store_edition_is_told_to_use_the_store(panel, monkeypatch):
    monkeypatch.setattr(updater, "offered", lambda *a: False)
    for route in ("/api/update", "/api/update/setting", "/api/update/check",
                  "/api/update/install", "/api/update/restart"):
        r = next(r for r in app_module.app.routes if getattr(r, "path", "") == route)
        assert app_module._updates_offered in [d.call for d in r.dependant.dependencies], route
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._updates_offered()
    assert e.value.status_code == 404 and "Store" in e.value.detail


def test_a_store_package_is_recognised():
    store = r"C:\Program Files\WindowsApps\PaperPull_1.0.0.0_x64__abc123\PaperPull.exe"
    assert updater.offered(store) is False
    assert updater.offered("/Applications/PaperPull.app/Contents/MacOS/python3") is True


def test_restart_checks_the_staged_app_again_and_refuses_a_changed_one(tmp_path, monkeypatch):
    app, staged = tmp_path / "PaperPull.app", tmp_path / ".PaperPull.new.app"
    app.mkdir(); staged.mkdir()
    inst = updater.Install()
    inst.phase, inst.app, inst.staged, inst.work, inst.version = "ready", app, staged, tmp_path, "0.61.0"
    swapped = []
    monkeypatch.setattr(updater, "start_swap", lambda *a: swapped.append(a))

    def changed(new, cur, version):
        raise updater.UpdateError("the new app was not signed by the same publisher")
    monkeypatch.setattr(updater, "verify_app", changed)
    with pytest.raises(updater.UpdateError):
        inst.restart()
    assert swapped == [] and not staged.exists() and inst.phase == "idle"
    assert app.is_dir()                         # the running app is untouched


def test_the_setting_must_be_a_real_yes_or_no(panel):
    for bad in ({}, {"check": "yes"}, {"check": 1}, []):
        with pytest.raises(fastapi.HTTPException):
            asyncio.run(app_module.api_update_setting(_Req(bad)))


def test_a_copy_that_cannot_replace_itself_says_why_and_refuses(panel):
    _setting(True)
    state = _check()
    assert state["newer"] and not state["can_install"] and state["why"]
    with pytest.raises(fastapi.HTTPException) as e:
        app_module.api_update_install()
    assert e.value.status_code == 409


def test_nothing_restarts_while_a_download_runs(panel, monkeypatch):
    monkeypatch.setitem(app_module._RUNS, ("x", "primary"), {"action": "pilot"})
    with pytest.raises(fastapi.HTTPException) as e:
        app_module.api_update_restart()
    assert e.value.status_code == 409 and "download" in e.value.detail


def test_restart_without_a_ready_update_is_refused(panel):
    with pytest.raises(fastapi.HTTPException) as e:
        app_module.api_update_restart()
    assert e.value.status_code == 409


def test_the_server_edition_has_no_update_endpoints(panel, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    for route in ("/api/update", "/api/update/check", "/api/update/install", "/api/update/restart"):
        r = next(r for r in app_module.app.routes if getattr(r, "path", "") == route)
        guards = [d.call for d in r.dependant.dependencies]
        assert app_module._updates_offered in guards
        with pytest.raises(fastapi.HTTPException) as e:
            app_module._updates_offered()
        assert e.value.status_code == 404
        with pytest.raises(fastapi.HTTPException) as e:
            app_module._desktop_only()
        assert e.value.status_code == 404


# -- what the review of #206 found -----------------------------------------

def test_the_macs_own_root_certificates_are_added(monkeypatch):
    """The app's Python is python-build-standalone's, which is not sure to
    find the Mac's roots by itself, and every request goes to github.com."""
    loaded = []

    class Ctx:
        def load_verify_locations(self, cafile=None):
            loaded.append(cafile)
    monkeypatch.setattr(updater.ssl, "create_default_context", lambda: Ctx())
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater.os.path, "isfile", lambda p: p == updater._MAC_ROOTS)
    updater._tls()
    assert loaded == [updater._MAC_ROOTS]
    loaded.clear()
    monkeypatch.setattr(updater.sys, "platform", "win32")
    updater._tls()
    assert loaded == []


def test_an_answer_cut_short_is_a_failed_check(monkeypatch):
    import http.client

    class Cut(_Resp):
        def read(self, *a):
            raise http.client.IncompleteRead(b"{")
    monkeypatch.setattr(updater, "_open", lambda url, timeout=20: Cut(b""))
    with pytest.raises(updater.UpdateError):
        updater.fetch_json(updater.API_LATEST)


def test_a_failed_install_never_leaves_the_page_waiting(tmp_path, monkeypatch):
    """Anything at all going wrong ends as an error the page can show, and
    Try again starts over."""
    calls = []

    def broken(*a, **k):
        calls.append(1)
        raise ValueError("assets was not a list")
    monkeypatch.setattr(updater, "check_latest", broken)
    inst = updater.Install()
    for _ in range(2):
        inst.start("0.60.1", tmp_path / "PaperPull.app")
        deadline = time.time() + 5
        while inst.busy() and time.time() < deadline:
            time.sleep(0.02)
        assert inst.snapshot()["phase"] == "error"
    assert len(calls) == 2


def test_a_half_copied_app_is_not_left_behind(tmp_path, monkeypatch):
    dmg, work, target = tmp_path / "a.dmg", tmp_path / "work", tmp_path / ".PaperPull.new.app"

    def run(cmd, timeout=300):
        if cmd[0].endswith("hdiutil") and cmd[1] == "attach":
            (work / "mnt" / "PaperPull.app").mkdir(parents=True)
        if cmd[0].endswith("ditto"):
            (target / "Contents").mkdir(parents=True)      # a disk that filled up
            return subprocess.CompletedProcess(cmd, 1, "", "No space left on device")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(updater, "_run", run)
    with pytest.raises(updater.UpdateError):
        updater.stage_app(dmg, work, target)
    assert not target.exists()


def test_the_store_check_fails_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "paperpull_core.browser", None)
    assert updater.offered("/Applications/PaperPull.app/Contents/MacOS/python3") is False


def test_a_check_turned_off_while_it_waited_keeps_nothing(panel, monkeypatch):
    """The answer takes seconds, and settings saved meanwhile are not undone."""
    _setting(True)

    def slow(url):
        data = app_module._read_settings()
        data["update_check"] = False
        data["apps_root"] = "kept"
        app_module._write_settings(data)
        return release("0.61.0", updater.architecture())
    monkeypatch.setattr(updater, "fetch_json", slow)
    with pytest.raises(fastapi.HTTPException) as e:
        _check()
    assert e.value.status_code == 409
    saved = app_module._read_settings()
    assert saved["update_check"] is False and saved["apps_root"] == "kept"
    assert "update_latest" not in saved


def test_nothing_restarts_during_a_history_import(panel):
    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        with pytest.raises(fastapi.HTTPException) as e:
            app_module.api_update_restart()
    finally:
        app_module._IMPORTING.release()
    assert e.value.status_code == 409 and "import" in e.value.detail


def _ready(tmp_path):
    app, staged = tmp_path / "PaperPull.app", tmp_path / ".PaperPull.new.app"
    app.mkdir()
    staged.mkdir()
    inst = updater.Install()
    inst.phase, inst.app, inst.staged, inst.work, inst.version = "ready", app, staged, tmp_path, "0.61.0"
    return inst, app, staged


def test_a_run_started_while_the_staged_app_was_checked_stops_the_restart(tmp_path, monkeypatch):
    inst, app, staged = _ready(tmp_path)
    swapped = []
    monkeypatch.setattr(updater, "start_swap", lambda *a: swapped.append(a))
    monkeypatch.setattr(updater, "verify_app", lambda *a: None)
    with pytest.raises(updater.UpdateError) as e:
        inst.restart(lambda: "A Rename is going on.")
    assert "Rename" in str(e.value)
    assert swapped == [] and inst.phase == "ready" and staged.is_dir() and app.is_dir()


def test_a_second_press_of_restart_is_refused(tmp_path, monkeypatch):
    inst, app, staged = _ready(tmp_path)
    swapped, second = [], []
    monkeypatch.setattr(updater, "start_swap", lambda *a: swapped.append(a))

    def verify(*a):
        # The second press arrives while the first is still checking.
        try:
            inst.restart()
        except updater.UpdateError as e:
            second.append(str(e))
    monkeypatch.setattr(updater, "verify_app", verify)
    inst.restart()
    assert len(swapped) == 1 and second == ["no update is ready"]
    assert inst.phase == "restarting"


def test_the_swap_waits_for_the_host_and_the_window_too(tmp_path, monkeypatch):
    app = tmp_path / "PaperPull.app"
    ancestors = {100: 50, 50: 1}
    monkeypatch.setattr(updater.os, "getppid", lambda: 100)
    monkeypatch.setattr(updater, "_is_inside", lambda pid, a: pid in ancestors)
    monkeypatch.setattr(updater, "_parent_of", lambda pid: ancestors.get(pid, 0))
    started = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **k: started.append(args))
    updater.start_swap(app, tmp_path / ".PaperPull.new.app", tmp_path)
    assert started[0][2].split() == [str(updater.os.getpid()), "100", "50"]


def _ready_to_restart(tmp_path, monkeypatch):
    """The panel's one install, ready, with the swap and the exit stubbed."""
    app, staged = tmp_path / "PaperPull.app", tmp_path / ".PaperPull.new.app"
    app.mkdir()
    staged.mkdir()
    inst = updater.INSTALL
    inst.phase, inst.app, inst.staged, inst.work, inst.version = "ready", app, staged, tmp_path, "0.61.0"
    swapped, exits = [], []
    monkeypatch.setattr(updater, "verify_app", lambda *a: None)
    monkeypatch.setattr(updater, "start_swap", lambda *a: swapped.append(a))
    monkeypatch.setattr(app_module, "_exit_soon", lambda: exits.append(1))
    monkeypatch.setattr(app_module, "_UPDATE_RESTARTING", False)
    return swapped, exits


def test_a_second_press_never_lifts_the_hold_of_the_first(panel, tmp_path, monkeypatch):
    """Two tabs on one panel. The first press is about to stop it, so the
    second is refused, and runs stay held off until it stops."""
    swapped, exits = _ready_to_restart(tmp_path, monkeypatch)
    assert app_module.api_update_restart() == {"restarting": True}
    assert app_module._UPDATE_RESTARTING is True and len(swapped) == 1 and exits == [1]
    with pytest.raises(fastapi.HTTPException) as e:
        app_module.api_update_restart()
    assert e.value.status_code == 409
    assert app_module._UPDATE_RESTARTING is True and len(swapped) == 1


def test_the_last_look_is_taken_on_the_event_loop(panel, tmp_path, monkeypatch):
    """As the server runs it, from a worker thread, the last look and the
    hold happen on the event loop, where a run checks and claims itself."""
    import anyio
    swapped, exits = _ready_to_restart(tmp_path, monkeypatch)
    loop_threads, look_threads = [], []
    real_hold = app_module._what_an_exit_would_cut

    def watched():
        look_threads.append(threading.get_ident())
        return real_hold()
    monkeypatch.setattr(app_module, "_what_an_exit_would_cut", watched)

    async def main():
        loop_threads.append(threading.get_ident())
        return await anyio.to_thread.run_sync(app_module.api_update_restart)
    assert asyncio.run(main()) == {"restarting": True}
    # The first look is the route's own, in the worker; the last, the loop's.
    assert look_threads[0] != loop_threads[0] and look_threads[-1] == loop_threads[0]
    assert app_module._UPDATE_RESTARTING is True and len(swapped) == 1


def test_the_update_routes_that_change_anything_are_refused_in_the_sample():
    for route in ("/api/update/setting", "/api/update/check", "/api/update/install",
                  "/api/update/restart"):
        r = next(r for r in app_module.app.routes if getattr(r, "path", "") == route)
        assert app_module._not_in_sample in [d.call for d in r.dependant.dependencies], route
