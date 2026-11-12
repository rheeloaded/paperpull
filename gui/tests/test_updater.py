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


def _setup_asset(version="0.61.0", **over):
    name = "PaperPull-%s-setup.exe" % version
    asset = {"name": name, "size": 10, "digest": "sha256:" + "b" * 64,
             "browser_download_url": updater.DOWNLOAD_PREFIX + "v%s/%s" % (version, name)}
    asset.update(over)
    return asset


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
    monkeypatch.setattr(updater, "install_location", lambda *a: None)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(updater, "offered", lambda *a: True)
    calls = []

    def fetch(url):
        calls.append(url)
        data = release("0.61.0", updater.architecture())
        data["assets"].append(_setup_asset("0.61.0"))
        return data
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


def test_the_server_checks_but_never_installs(panel, monkeypatch):
    """A container cannot replace its own image and is never given the
    Docker socket, so PaperPull Server asks the same way and the page gives
    the steps that take the new image. It is never offered a release file."""
    _, calls = panel
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    app_module._updates_offered()                        # offered, not a 404
    state = _setting(True)
    assert state["edition"] == "server" and calls == []
    state = _check()
    assert len(calls) == 1 and state["newer"] and state["latest"] == "0.61.0"
    assert not state["can_install"] and state["why"] == ""
    saved = app_module._read_settings()
    assert saved["update_latest"] == {"version": "0.61.0", "installable": False}
    for route in ("/api/update/install", "/api/update/restart"):
        r = next(r for r in app_module.app.routes if getattr(r, "path", "") == route)
        assert app_module._desktop_only in [d.call for d in r.dependant.dependencies], route
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._desktop_only()
    assert e.value.status_code == 404


def test_the_server_is_never_handed_an_asset():
    data = release()
    data["assets"].append(_setup_asset())
    assert updater.read_release(data, "arm64", kind="")["asset"] is None


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


# -- Windows ----------------------------------------------------------------
#
# A copy installed by setup.exe runs the new setup.exe over itself, once it
# is proved to be the release's own and signed by PaperPull's publisher. The
# portable zip, the Store edition and a checkout install nothing.

def _windows_copy(where):
    """A folder shaped as the installer and the portable zip leave it."""
    (where / "gui").mkdir(parents=True)
    (where / "python").mkdir()
    (where / "PaperPull.exe").write_bytes(b"MZ")
    (where / "python" / "python.exe").write_bytes(b"MZ")
    return where


def test_the_installer_is_picked_for_windows_with_its_checksum():
    data = release()
    data["assets"].append(_setup_asset())
    rel = updater.read_release(data, "x86_64", kind="windows")
    assert rel["asset"]["name"] == "PaperPull-0.61.0-setup.exe"
    assert rel["asset"]["sha256"] == "b" * 64
    # The disk image is the Mac's, never Windows'.
    assert updater.read_release(release(), "x86_64", kind="windows")["asset"] is None


@pytest.mark.parametrize("change", [
    {"digest": None},
    {"digest": "sha256:" + "B" * 64},
    {"browser_download_url": "https://github.com/someone/else/releases/download/v0.61.0/PaperPull-0.61.0-setup.exe"},
    {"browser_download_url": updater.DOWNLOAD_PREFIX + "v0.60.0/PaperPull-0.61.0-setup.exe"},
    {"name": "PaperPull-0.61.0.zip"},
    {"size": 0},
])
def test_an_installer_that_cannot_be_proved_is_not_offered(change):
    data = release()
    data["assets"].append(_setup_asset(**change))
    assert updater.read_release(data, "x86_64", kind="windows")["asset"] is None


def test_only_the_folder_the_installer_recorded_is_an_installed_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    installed = _windows_copy(tmp_path / "PaperPull")
    portable = _windows_copy(tmp_path / "PaperPull-0.64.0")
    monkeypatch.setattr(updater, "offered", lambda *a: True)
    monkeypatch.setattr(updater, "_installer_folder", lambda: str(installed) + "\\")
    assert updater.installed_folder(installed / "gui") == installed
    assert updater.edition(installed / "gui") == "windows"
    # Unzipped beside it, the same shape, but not where the next installer goes.
    assert updater.installed_folder(portable / "gui") is None
    assert updater.edition(portable / "gui") == "portable"
    monkeypatch.setattr(updater, "_installer_folder", lambda: "")
    assert updater.edition(installed / "gui") == "portable"
    # A checkout has no PaperPull.exe beside gui.
    (tmp_path / "repo" / "gui").mkdir(parents=True)
    assert updater.edition(tmp_path / "repo" / "gui") == "other"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows folders ignore case")
def test_the_recorded_folder_matches_in_any_case(tmp_path, monkeypatch):
    installed = _windows_copy(tmp_path / "PaperPull")
    monkeypatch.setattr(updater, "_installer_folder", lambda: str(installed).upper())
    assert updater.installed_folder(installed / "gui") == installed


@pytest.mark.skipif(sys.platform != "win32", reason="the installer's record is in the registry")
def test_the_installers_record_is_read_from_the_registry(monkeypatch):
    import uuid
    import winreg
    key = r"Software\PaperPull-tests\%s" % uuid.uuid4().hex
    monkeypatch.setattr(updater, "UNINSTALL_KEY", key)
    assert updater._installer_folder() == ""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, "C:\\Elsewhere\\")
            assert updater._installer_folder() == "C:\\Elsewhere\\"
            winreg.SetValueEx(k, "Inno Setup: App Path", 0, winreg.REG_SZ,
                              "C:\\Users\\x\\AppData\\Local\\PaperPull")
        assert updater._installer_folder() == "C:\\Users\\x\\AppData\\Local\\PaperPull"
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\PaperPull-tests")
        except OSError:
            pass


def test_a_windows_copy_that_cannot_replace_itself_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "windows_folder", lambda *a: tmp_path)
    ok, why = updater.can_install(None, "windows")
    assert not ok and why == updater.PORTABLE_SAYS and "zip" in why
    monkeypatch.setattr(updater, "windows_folder", lambda *a: None)
    ok, why = updater.can_install(None, "windows")
    assert not ok and "setup.exe" in why
    assert updater.can_install(tmp_path, "windows") == (True, "")


PUBLISHER = {"status": "Valid", "type": "Authenticode",
             "subject": "CN=Bryan Rhee, O=Bryan Rhee, L=Town, S=State, C=US",
             "issuer": "CN=Microsoft ID Verified CS AOC CA 04, O=Microsoft Corporation, C=US",
             "version": "0.61.0                    "}


def test_the_publishers_signature_is_recognized():
    assert updater.signed_by_publisher(PUBLISHER)
    for issuer in ("CN=Microsoft ID Verified CS EOC CA 01, O=Microsoft Corporation, C=US",
                   "CN=Microsoft ID Verified CS AOC CA 03, O=Microsoft Corporation, C=US"):
        assert updater.signed_by_publisher(dict(PUBLISHER, issuer=issuer))


@pytest.mark.parametrize("change", [
    {"status": "NotSigned"}, {"status": "HashMismatch"}, {"status": "NotTrusted"},
    {"type": "Catalog"},
    {"subject": "CN=Someone Else, O=Someone Else, L=Town, S=State, C=US"},
    {"subject": "CN=Bryan Rhee, O=Evil Corp, C=US"},
    {"subject": "CN=Bryan Rhee, O=Bryan Rhee, L=Town, S=State, C=GB"},
    {"issuer": "CN=DigiCert Trusted G4 Code Signing RSA4096 SHA384 2021 CA1, O=DigiCert, Inc., C=US"},
    {"issuer": "CN=Microsoft ID Verified CS AOC CA 04, O=Evil, C=US"},
    {"subject": ""}, {"issuer": None},
])
def test_any_other_signature_is_not_the_publishers(change):
    assert not updater.signed_by_publisher(dict(PUBLISHER, **change))


def _installer(where, body=b"installer"):
    setup = where / "PaperPull-0.61.0-setup.exe"
    setup.write_bytes(body)
    return setup, hashlib.sha256(body).hexdigest()


def test_the_installer_must_match_and_be_the_publishers_and_the_version(tmp_path, monkeypatch):
    setup, sha = _installer(tmp_path)
    sig = dict(PUBLISHER)
    monkeypatch.setattr(updater, "windows_signature", lambda path: sig)
    updater.verify_installer(setup, sha, "0.61.0")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.verify_installer(setup, "c" * 64, "0.61.0")
    with pytest.raises(updater.UpdateError, match="not 0.62.0"):
        updater.verify_installer(setup, sha, "0.62.0")
    sig["subject"] = "CN=Someone Else, O=Someone Else, C=US"
    with pytest.raises(updater.UpdateError, match="publisher"):
        updater.verify_installer(setup, sha, "0.61.0")
    with pytest.raises(updater.UpdateError, match="could not be read"):
        updater.verify_installer(tmp_path / "gone.exe", sha, "0.61.0")
    # PowerShell that would not start, or said nothing, is not a yes.
    sig.clear()
    with pytest.raises(updater.UpdateError, match="could not say who signed the installer"):
        updater.verify_installer(setup, sha, "0.61.0")


def test_a_copy_windows_cannot_read_the_signature_of_asks_github_nothing(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(updater, "windows_signature", lambda path: {})
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: asked.append(a))
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    snap = _finish(inst)
    assert snap["phase"] == "error" and "could not say who signed this copy" in snap["error"]
    assert asked == []
    monkeypatch.setattr(updater, "windows_signature", lambda path: dict(PUBLISHER, status="NotSigned"))
    inst.start("0.60.1", tmp_path, kind="windows")
    snap = _finish(inst)
    assert snap["phase"] == "error" and "not signed" in snap["error"] and asked == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reads Authenticode")
def test_windows_reads_a_signature_for_real(tmp_path):
    """The PowerShell the panel starts, run for real. A file with no
    signature and one of Windows' own are both read, and neither is the
    publisher's."""
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"MZ not really a program")
    sig = updater.windows_signature(plain)
    assert sig.get("status") and sig["status"] != "Valid"
    assert not updater.signed_by_publisher(sig)
    notepad = Path(updater.os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    if notepad.is_file():
        sig = updater.windows_signature(notepad)
        assert sig.get("status") == "Valid" and sig.get("subject")
        assert not updater.signed_by_publisher(sig)


def _windows_rel(version="0.61.0", body=b"installer"):
    data = release(version)
    data["assets"].append(_setup_asset(version, size=len(body),
                                       digest="sha256:" + hashlib.sha256(body).hexdigest()))
    return updater.read_release(data, "x86_64", kind="windows")


def _finish(inst):
    deadline = time.time() + 5
    while inst.busy() and time.time() < deadline:
        time.sleep(0.02)
    return inst.snapshot()


def test_an_unsigned_windows_copy_asks_github_nothing(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(updater, "this_copy_is_signed", lambda folder: False)
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: asked.append(a))
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    snap = _finish(inst)
    assert snap["phase"] == "error" and "not signed" in snap["error"] and asked == []


def test_a_windows_download_is_checked_and_kept_ready(tmp_path, monkeypatch):
    body = b"installer"
    monkeypatch.setattr(updater, "this_copy_is_signed", lambda folder: True)
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: dict(_windows_rel(body=body), newer=True))
    monkeypatch.setattr(updater, "_open", lambda url, timeout=20: _Resp(body))
    checked = []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: checked.append(a))
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    assert _finish(inst)["phase"] == "ready"
    assert inst.kind == "windows" and inst.staged.read_bytes() == body
    assert inst.sha256 == hashlib.sha256(body).hexdigest()
    assert checked == [(inst.staged, inst.sha256, "0.61.0")]
    assert inst.work.name.startswith("paperpull-update-") and inst.staged.parent == inst.work
    updater.shutil.rmtree(inst.work)


def test_a_windows_download_that_fails_its_check_leaves_nothing(tmp_path, monkeypatch):
    body = b"installer"
    monkeypatch.setattr(updater, "this_copy_is_signed", lambda folder: True)
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: dict(_windows_rel(body=body), newer=True))
    monkeypatch.setattr(updater, "_open", lambda url, timeout=20: _Resp(body))
    made = []
    real = updater.tempfile.mkdtemp

    def mkdtemp(**k):
        made.append(real(**k))
        return made[-1]
    monkeypatch.setattr(updater.tempfile, "mkdtemp", mkdtemp)

    def refuse(*a):
        raise updater.UpdateError("the installer is not signed by PaperPull's publisher")
    monkeypatch.setattr(updater, "verify_installer", refuse)
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    snap = _finish(inst)
    assert snap["phase"] == "error" and "publisher" in snap["error"]
    # The error is said a moment before the folder is removed.
    deadline = time.time() + 5
    while made and Path(made[0]).exists() and time.time() < deadline:
        time.sleep(0.02)
    assert made and not Path(made[0]).exists()


def _windows_ready(tmp_path, inst=None):
    work = tmp_path / "paperpull-update-x"
    work.mkdir()
    setup, sha = _installer(work)
    inst = inst or updater.Install()
    inst.phase, inst.kind, inst.app, inst.work = "ready", "windows", tmp_path / "PaperPull", work
    inst.staged, inst.sha256, inst.version = setup, sha, "0.61.0"
    return inst, setup, sha


def test_restart_on_windows_checks_the_installer_again_then_hands_over(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    checked, started = [], []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: checked.append(a))
    monkeypatch.setattr(updater, "start_installer", lambda *a: started.append(a))
    monkeypatch.setattr(updater, "start_swap", lambda *a: pytest.fail("the Mac's swap ran on Windows"))
    inst.restart()
    assert checked == [(setup, sha, "0.61.0")]
    assert started == [(tmp_path / "PaperPull", setup, sha, "0.61.0")]
    assert inst.phase == "restarting"


def test_an_installer_changed_while_it_waited_is_thrown_away(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    started = []
    monkeypatch.setattr(updater, "start_installer", lambda *a: started.append(a))

    def changed(*a):
        raise updater.UpdateError("the installer does not match the checksum GitHub recorded")
    monkeypatch.setattr(updater, "verify_installer", changed)
    with pytest.raises(updater.UpdateError):
        inst.restart()
    assert started == [] and inst.phase == "idle" and not setup.parent.exists()


def test_a_run_started_meanwhile_keeps_the_windows_installer_ready(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    started = []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)
    monkeypatch.setattr(updater, "start_installer", lambda *a: started.append(a))
    with pytest.raises(updater.UpdateError):
        inst.restart(lambda: "A Rename is going on.")
    assert started == [] and inst.phase == "ready" and setup.is_file()


def test_the_panel_stays_open_when_the_installer_never_starts(panel, tmp_path, monkeypatch):
    """The script never said it was waiting, so nothing would install the
    update or open PaperPull again. The press is refused and nothing is held."""
    inst, setup, sha = _windows_ready(tmp_path, updater.INSTALL)
    exits = []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)
    monkeypatch.setattr(app_module, "_exit_soon", lambda: exits.append(1))
    monkeypatch.setattr(app_module, "_UPDATE_RESTARTING", False)

    def never(*a):
        raise updater.UpdateError("the installer could not be started")
    monkeypatch.setattr(updater, "start_installer", never)
    with pytest.raises(fastapi.HTTPException) as e:
        app_module.api_update_restart()
    assert e.value.status_code == 409 and "could not be started" in e.value.detail
    assert exits == [] and app_module._UPDATE_RESTARTING is False and inst.phase == "ready"


def test_the_install_route_starts_the_windows_kind_on_windows(panel, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(updater, "install_location", lambda *a: tmp_path)
    monkeypatch.setattr(updater, "install_kind", lambda: "windows")
    monkeypatch.setattr(updater.INSTALL, "start", lambda *a, **k: started.append((a, k)))
    _setting(True)
    state = _check()
    assert state["can_install"]
    app_module.api_update_install()
    assert started == [(("0.60.1", tmp_path), {"kind": "windows"})]


def test_on_windows_the_panel_ends_with_0(monkeypatch):
    """os.kill on Windows ends a process with the signal's number as its
    exit code, which a terminal can keep the window open for."""
    calls = []

    class Now:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    class Ended(Exception):
        pass

    def end(code):
        calls.append(("exit", code))
        raise Ended
    monkeypatch.setattr(app_module.threading, "Thread", Now)
    monkeypatch.setattr(app_module, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    monkeypatch.setattr(app_module.os, "kill", lambda *a: calls.append(("kill",) + a))
    monkeypatch.setattr(app_module.os, "_exit", end)
    with pytest.raises(Ended):
        app_module._exit_soon()
    assert calls == [("exit", 0)]


def test_the_page_ends_the_reason_with_a_full_stop():
    """The panel's reasons end without one, and the page says them inside a
    sentence of its own."""
    js = (Path(app_module.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert ("'The update did not install: ' + (inst.error || 'something went wrong')"
            ".replace(/\\.?$/, '.') + ' Nothing was changed.'") in js


def test_the_page_gives_the_server_the_steps_that_take_the_new_image():
    js = (Path(app_module.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    load = js[js.index("async function updLoad()"):]
    load = load[:load.index("\n}\n")]
    assert "SERVER" not in load                    # the server asks /api/update too
    render = js[js.index("function updRender()"):]
    render = render[:render.index("\n}\n")]
    assert "updServerSteps(UPD.latest)" in render and "SERVER ||" not in render
    steps = js[js.index("function updServerSteps(v)"):]
    steps = steps[:steps.index("\n}\n")]
    for step in ("<code>image:</code>", "<code>compose.yaml</code>", "<code>docker compose pull</code>",
                 "<code>docker compose up -d</code>", "SERVER_IMAGE + ':' + esc(v)"):
        assert step in steps, step
    assert "const SERVER_IMAGE = 'ghcr.io/rheeloaded/paperpull-server';" in js
    compose = (Path(app_module.__file__).resolve().parents[1] / "server" / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+image: ghcr\.io/rheeloaded/paperpull-server:\d+\.\d+\.\d+$", compose, re.M)


# -- the script that runs the installer, for real ----------------------------
#
# Stub programs stand in for setup.exe and PaperPull.exe. Each writes the
# arguments it was given to a file of its own and ends with the code it is
# told, so the script is run exactly as the panel runs it, by PowerShell, with
# a process to wait for.

_STUB = r'''
using System; using System.IO; using System.Threading;
static class Stub { static int Main(string[] a) {
  string me = System.Reflection.Assembly.GetEntryAssembly().Location;
  File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("STUB_DIR"),
                                 Path.GetFileName(me) + ".ran"), string.Join("\n", a));
  string ms = Environment.GetEnvironmentVariable("STUB_SLEEP_MS");
  if (!string.IsNullOrEmpty(ms)) Thread.Sleep(int.Parse(ms));
  string code = Environment.GetEnvironmentVariable("STUB_EXIT");
  return string.IsNullOrEmpty(code) ? 0 : int.Parse(code);
} }
'''


@pytest.fixture(scope="module")
def stub_exe(tmp_path_factory):
    if sys.platform != "win32":
        pytest.skip("the installer is for Windows")
    sys.path.insert(0, str(Path(app_module.__file__).resolve().parents[1] / "packaging"))
    import msix
    csc = msix.find_csc()
    if csc is None:
        pytest.skip("no C# compiler to build the stub programs")
    where = tmp_path_factory.mktemp("stub")
    (where / "stub.cs").write_text(_STUB, encoding="utf-8")
    subprocess.run([str(csc), "/nologo", "/target:exe", "/out:" + str(where / "stub.exe"),
                    str(where / "stub.cs")], check=True, capture_output=True)
    return (where / "stub.exe").read_bytes()


def _install_box(tmp_path, monkeypatch, stub_exe, **env):
    seen = tmp_path / "seen"
    seen.mkdir()
    app = tmp_path / "Install Folder"
    app.mkdir()
    (app / "PaperPull.exe").write_bytes(stub_exe)
    work = tmp_path / "paperpull-update-abc"
    work.mkdir()
    setup = work / "PaperPull-0.61.0-setup.exe"
    setup.write_bytes(stub_exe)
    monkeypatch.setenv("STUB_DIR", str(seen))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return seen, app, setup, hashlib.sha256(stub_exe).hexdigest()


def _after(proc, seen, *names):
    proc.wait(timeout=90)
    deadline = time.time() + 20
    while time.time() < deadline and not all((seen / n).exists() for n in names):
        time.sleep(0.1)
    log = Path(updater.os.environ["APPDATA"]) / "PaperPull" / "update.log"
    return log.read_text(encoding="utf-8-sig") if log.exists() else ""


def _panel_for(seconds):
    """A process standing in for the panel, ending on its own."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%s)" % seconds])
    threading.Thread(target=p.wait, daemon=True).start()
    return p


def test_the_script_waits_installs_and_opens_paperpull_again(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    panel_proc = _panel_for(1.5)
    t = time.time()
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=panel_proc.pid)
    log = _after(proc, seen, "PaperPull-0.61.0-setup.exe.ran", "PaperPull.exe.ran")
    assert panel_proc.poll() is not None and time.time() - t >= 1.0
    args = (seen / "PaperPull-0.61.0-setup.exe.ran").read_text().split("\n")
    assert args[:4] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL"]
    assert args[4] == "/LOG=" + str(tmp_path / "Roaming" / "PaperPull" / "setup.log")
    assert (seen / "PaperPull.exe.ran").exists()
    assert "installed" in log and "opened PaperPull again" in log
    assert not setup.parent.exists()              # it cleans up after itself


def test_the_script_never_runs_an_installer_that_changed(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    proc = updater.start_installer(app, setup, "0" * 64, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, "PaperPull.exe.ran")
    assert not (seen / "PaperPull-0.61.0-setup.exe.ran").exists()
    assert "not the one the panel checked" in log and (seen / "PaperPull.exe.ran").exists()


def test_the_script_installs_nothing_while_the_panel_stays(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    stays = _panel_for(30)
    try:
        proc = updater.start_installer(app, setup, sha, "0.61.0", pid=stays.pid, wait_s=1)
        log = _after(proc, seen)
    finally:
        stays.kill()
    assert list(seen.iterdir()) == []             # neither the installer nor a second PaperPull
    assert "did not exit" in log


def test_a_failed_install_still_opens_paperpull_again(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe, STUB_EXIT="4")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, "PaperPull-0.61.0-setup.exe.ran", "PaperPull.exe.ran")
    assert "ended with 4" in log and (seen / "PaperPull.exe.ran").exists()


_HANDS_OVER = r'''
import os, sys, time
sys.path[:0] = [sys.argv[1]] + sys.argv[5].split(os.pathsep)
import updater
from pathlib import Path
updater.start_installer(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], "0.61.0")
time.sleep(1.0)
os._exit(0)
'''


def test_the_script_outlives_the_panel_that_started_it(tmp_path, monkeypatch, stub_exe):
    """As Restart and update does it. The panel starts the script, waits for
    it to say it is waiting, and ends, and the script goes on."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe, STUB_SLEEP_MS="1000")
    gui = str(Path(updater.__file__).resolve().parent)
    done = subprocess.run([sys.executable, "-c", _HANDS_OVER, gui, str(app), str(setup), sha,
                           updater.os.pathsep.join(sys.path)],
                          capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2000:]
    deadline = time.time() + 60
    while time.time() < deadline and not (seen / "PaperPull.exe.ran").exists():
        time.sleep(0.2)
    assert (seen / "PaperPull-0.61.0-setup.exe.ran").exists() and (seen / "PaperPull.exe.ran").exists()


def test_a_script_that_never_says_it_waits_keeps_the_panel_open(tmp_path, monkeypatch, stub_exe):
    """PowerShell stopped by a policy, or anything else that ends it before
    it writes that it is waiting, refuses the restart."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    quiet = tmp_path / "quiet.exe"
    quiet.write_bytes(stub_exe)
    monkeypatch.setattr(updater, "_powershell", lambda: str(quiet))
    with pytest.raises(updater.UpdateError, match="could not be started"):
        updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid, within=10)
    assert (seen / "quiet.exe.ran").exists() and setup.is_file()


class _Started:
    """subprocess.Popen as start_installer uses it, a script that says at
    once that it is waiting, with the environment it was given kept."""
    seen = []

    def __init__(self, cmd, env=None, **kw):
        _Started.seen.append(env)
        Path(env["PAPERPULL_STARTED"]).write_text("waiting")

    def poll(self):
        return None


def test_the_script_waits_for_paperpull_exe_too(tmp_path, monkeypatch):
    """PaperPull.exe started the panel and is in the folder the installer
    replaces, so the script waits for it as well. A panel started some other
    way waits for itself alone."""
    folder = tmp_path / "PaperPull"
    folder.mkdir()
    setup, sha = _installer(tmp_path)
    monkeypatch.setattr(updater.subprocess, "Popen", _Started)
    monkeypatch.setattr(updater.os, "getppid", lambda: 4242)
    monkeypatch.setattr(updater, "_image_of", lambda pid: str(folder / "PaperPull.exe") if pid == 4242 else "")
    _Started.seen.clear()
    updater.start_installer(folder, setup, sha, "0.61.0")
    env = _Started.seen[-1]
    assert env["PAPERPULL_WAIT"] == "%d 4242" % updater.os.getpid()
    assert env["PAPERPULL_SETUP"] == str(setup) and env["PAPERPULL_SHA256"] == sha
    assert env["PAPERPULL_APP"] == str(folder) and env["PAPERPULL_VERSION"] == "0.61.0"
    monkeypatch.setattr(updater, "_image_of", lambda pid: r"C:\Windows\explorer.exe")
    updater.start_installer(folder, setup, sha, "0.61.0")
    assert _Started.seen[-1]["PAPERPULL_WAIT"] == str(updater.os.getpid())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows names a process's program")
def test_the_program_a_process_runs_is_read(tmp_path):
    image = updater._image_of(updater.os.getpid())
    assert image.lower().endswith("python.exe") and Path(image).is_file()
    assert updater._image_of(0) == ""
