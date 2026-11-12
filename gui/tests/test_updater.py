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


@pytest.fixture(autouse=True)
def _a_temp_folder_of_its_own(tmp_path_factory, monkeypatch):
    """Each test's temp folder is its own, so a download's folder lands
    there and the removal of installers earlier updates kept never looks
    at this computer's own temp folder."""
    monkeypatch.setattr(updater.tempfile, "tempdir", str(tmp_path_factory.mktemp("temp")))


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


# -- who may sign an installer ------------------------------------------------
#
# Signing may move from Bryan Rhee to TNE Enterprises LLC, the company behind
# PaperPull. A copy already installed accepts only the names its own release
# holds, so the release that accepts both has to come before any move.

SIGNER_NAMES = ("Bryan Rhee", "TNE Enterprises LLC")


def _subject(cn, o=None, rest="L=Town, S=State, C=US"):
    return "CN=%s, O=%s, %s" % (cn, cn if o is None else o, rest)


@pytest.mark.parametrize("name", SIGNER_NAMES)
def test_each_accepted_signer_is_recognized(name):
    for subject in (_subject(name), _subject(name, rest="L=Another Town, S=State, PostalCode=00000, C=US"),
                    _subject(name, rest="OU=Signing, C=US")):
        assert updater.signed_by_publisher(dict(PUBLISHER, subject=subject)), subject


def _near_misses(name):
    other = next(n for n in SIGNER_NAMES if n != name)
    return [
        _subject("Someone Else"),                                   # another CN
        _subject(name, "Someone Else"), _subject("Someone Else", name),
        _subject(name, other), _subject(other, name),              # CN and O that differ
        _subject(name, rest="L=Town, S=State, C=GB"),             # not C=US
        _subject(name, rest="L=Town, S=State"),                   # no C at all
        "CN=%s, O=%s, C=US" % (name, name),                       # nothing between
        _subject(name + "."), _subject(name + " Holdings"),       # names that look alike
        _subject(name.lower()), _subject(name.upper()),
        _subject(" " + name), _subject(name.replace(" ", "  ")),
        _subject(name.replace("e", "\u0435")),               # a Cyrillic e
        _subject(name.replace(" ", ", ")),
        "O=%s, CN=%s, L=Town, S=State, C=US" % (name, name),
        "CN=Someone Else, O=Someone Else, L=%s, S=State, C=US" % name,
        "CN=%s, O=%s, L=Town, S=State, C=US, O=Someone Else" % (name, name),
    ]


@pytest.mark.parametrize("name", SIGNER_NAMES)
def test_near_misses_of_each_accepted_signer_are_refused(name):
    for subject in _near_misses(name):
        assert not updater.signed_by_publisher(dict(PUBLISHER, subject=subject)), subject


def test_the_accepted_signers_are_held_in_one_place():
    assert sorted(re.match(r"^\^CN=(.+?), O=", p.pattern).group(1) for p in updater._SIGNERS) == sorted(SIGNER_NAMES)
    for name, pattern in zip(SIGNER_NAMES, updater._SIGNERS):
        assert pattern.pattern == r"^CN=%s, O=%s, .*, C=US$" % (name, name)


REPO_ROOT = Path(__file__).resolve().parents[2]
# A certificate subject spelled out in a file, its CN and its O.
_PINNED = re.compile(r"CN=([^,=\r\n'\"]+), O=([^,=\r\n'\"]+)")


def _tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=str(REPO_ROOT), capture_output=True,
                             timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git cannot list the repository's files")
    for rel in out.decode("utf-8").split("\0"):
        if rel and "tests" not in Path(rel).parts:
            yield rel


def test_every_place_that_checks_the_signer_accepts_the_same_two():
    """A census of the repository, tests left out. Every file that spells
    out a publisher's certificate subject, or reads a signer at all, names
    either no publisher or exactly the two this check accepts. The scripts
    the panel starts name none, and the one that runs the installer is
    handed the panel's own list."""
    pinned, readers = {}, {}
    for rel in _tracked_files():
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        names = {cn.strip() for cn, o in _PINNED.findall(text) if o.strip() != "Microsoft Corporation"}
        if names:
            pinned[rel] = names
        if "SignerCertificate" in text or "Get-AuthenticodeSignature" in text:
            readers[rel] = {n for n in SIGNER_NAMES if n in text} | names
    assert pinned == {"gui/updater.py": set(SIGNER_NAMES)}
    for rel, names in readers.items():
        assert names in (set(), set(SIGNER_NAMES)), (rel, names)
    for script in (updater.INSTALL_PS, updater._SIGNATURE_PS):
        assert "CN=" not in script and not [n for n in SIGNER_NAMES if n in script]
    assert updater._signer_env() == {
        "PAPERPULL_UPDATE_SIGNERS": "\n".join(p.pattern for p in updater._SIGNERS),
        "PAPERPULL_UPDATE_ISSUER": updater._ISSUER.pattern}


def test_the_install_script_is_handed_the_panels_own_signers(tmp_path, monkeypatch):
    folder = tmp_path / "PaperPull"
    folder.mkdir()
    setup, sha = _installer(tmp_path)
    monkeypatch.setattr(updater.subprocess, "Popen", _Started)
    _Started.seen.clear()
    updater.start_installer(folder, setup, sha, "0.61.0", pid=4242)
    env = _Started.seen[-1]
    assert env["PAPERPULL_UPDATE_SIGNERS"].split("\n") == [p.pattern for p in updater._SIGNERS]
    assert env["PAPERPULL_UPDATE_ISSUER"] == updater._ISSUER.pattern
    assert "'SIGNERS', 'ISSUER'" in updater.INSTALL_PS     # read, then removed like the rest


_JUDGE = r"""
function Get-AuthenticodeSignature([string]$LiteralPath) {
  [pscustomobject]@{ Status = $case.status; SignatureType = $case.type;
    SignerCertificate = [pscustomobject]@{ Subject = $case.subject; Issuer = $case.issuer } }
}
%(read)s
%(publisher)s
$cases = ConvertFrom-Json $env:CASES
foreach ($case in $cases) {
  $version = [string]$case.want
  [string](Publisher $env:CHECKED)
}
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the install script runs in Windows PowerShell")
def test_the_install_script_judges_a_signature_as_the_panel_does(tmp_path):
    """The script's own check, run by Windows PowerShell with the panel's
    signers, answers as signed_by_publisher and the version check do, for
    each accepted signer, each near miss, and each other way a signature
    can fail. The file it reads says no version, as a plain file does."""
    read = "\n".join(re.findall(r"^\$(?:signers|issuer) = .*$", updater.INSTALL_PS, re.M))
    publisher = re.search(r"^function Publisher\b.*?^}$", updater.INSTALL_PS, re.M | re.S)
    assert read.count("\n") == 1 and publisher
    cases = []
    for name in SIGNER_NAMES:
        for subject in [_subject(name)] + _near_misses(name):
            cases.append(dict(PUBLISHER, subject=subject, want=""))
    for change in ({"status": "NotSigned"}, {"status": "HashMismatch"}, {"type": "Catalog"},
                   {"issuer": "CN=Microsoft ID Verified CS AOC CA 04, O=Evil, C=US"},
                   {"issuer": "CN=Microsoft ID Verified CS EOC CA 01, O=Microsoft Corporation, C=US"},
                   {"issuer": "cn=microsoft id verified cs eoc ca 01, o=microsoft corporation, c=us"},
                   {"want": "0.61.0"}):
        cases.append(dict(dict(PUBLISHER, want=""), **change))
    for case in cases:
        case["version"] = ""
    checked = tmp_path / "checked.exe"
    checked.write_bytes(b"says no version")
    env = dict(updater._powershell_env(CASES=json.dumps(cases), CHECKED=str(checked)), **updater._signer_env())
    script = _JUDGE % {"read": read, "publisher": publisher.group(0)}
    done = subprocess.run([updater._powershell(), "-NoLogo", "-NoProfile", "-NonInteractive",
                           "-Command", script], capture_output=True, text=True, timeout=120, env=env,
                          stdin=subprocess.DEVNULL)
    said = done.stdout.split()
    assert len(said) == len(cases), done.stderr[-2000:]
    for case, answer in zip(cases, said):
        panel = updater.signed_by_publisher(case) and str(case["version"]).strip() == case["want"]
        assert answer == str(panel), case
    assert said.count("True") == len(SIGNER_NAMES) + 1


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


def _unloadable_security_module(tmp_path) -> Path:
    """A module folder whose Microsoft.PowerShell.Security cannot load in
    Windows PowerShell, as PowerShell 7's own cannot."""
    mods = tmp_path / "Modules"
    sec = mods / "Microsoft.PowerShell.Security"
    sec.mkdir(parents=True)
    (sec / "Microsoft.PowerShell.Security.psd1").write_text(
        "@{ ModuleVersion = '7.0.0.0'; RootModule = 'not-here.dll'; "
        "CmdletsToExport = @('Get-AuthenticodeSignature') }\n", encoding="utf-8")
    return mods


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reads Authenticode")
def test_a_panel_opened_from_powershell_7_still_reads_signatures(tmp_path, monkeypatch):
    """PowerShell 7 gives every program it starts its own module folders.
    Windows PowerShell then finds PowerShell 7's Security module before its
    own and cannot load it, so Get-AuthenticodeSignature is missing. Found in
    the real run of a 0.64.0 install, where a PaperPull.exe opened from a
    PowerShell 7 window read its own signature as empty and refused every
    update as unsigned."""
    notepad = Path(updater.os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "notepad.exe"
    if not notepad.is_file():
        pytest.skip("no notepad.exe to read")
    mods = _unloadable_security_module(tmp_path)
    monkeypatch.setenv("PSModulePath", str(mods) + ";" + updater.os.environ.get("PSModulePath", ""))
    assert updater.windows_signature(notepad).get("status") == "Valid"


def test_powershell_is_never_handed_the_panels_module_folders(tmp_path, monkeypatch):
    """Both scripts start Windows PowerShell with no PSModulePath of the
    panel's, so it finds its own modules, whatever started the panel."""
    monkeypatch.setenv("PSModulePath", str(tmp_path / "Modules"))
    given = []

    class _Ran:
        stdout = "{}"

    def run(cmd, env=None, **kw):
        given.append(env)
        return _Ran()

    monkeypatch.setattr(updater.subprocess, "run", run)
    updater.windows_signature(tmp_path / "x.exe")
    folder = tmp_path / "PaperPull"
    folder.mkdir()
    setup, sha = _installer(tmp_path)
    _Started.seen.clear()
    monkeypatch.setattr(updater.subprocess, "Popen", _Started)
    updater.start_installer(folder, setup, sha, "0.61.0", pid=4321)
    given += _Started.seen
    assert len(given) == 2
    for env in given:
        assert env.get("PATH")
        assert not [k for k in env if k.upper() == "PSMODULEPATH"]


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


def test_the_page_says_the_reason_as_sentences_of_its_own():
    """The panel's reasons start in lower case and end without a full stop,
    and some are two sentences."""
    js = (Path(app_module.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "const why = (inst.error || 'something went wrong').replace(/\\.$/, '');" in js
    assert ("text = 'The update did not install. ' + why.charAt(0).toUpperCase() + why.slice(1)"
            " + '. Nothing was changed.';") in js


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
                 "<code>docker compose up -d</code>", "SERVER_IMAGE + ':' + esc(v)",
                 "names <code>paperpull-server</code>", "try again later"):
        assert step in steps, step
    assert "const SERVER_IMAGE = 'ghcr.io/rheeloaded/paperpull-server';" in js
    compose = (Path(app_module.__file__).resolve().parents[1] / "server" / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+image: ghcr\.io/rheeloaded/paperpull-server:\d+\.\d+\.\d+$", compose, re.M)


def test_both_scripts_are_one_argument_with_no_double_quote():
    """Each script is all of one argument on PowerShell's command line, and a
    double quote there would end it early."""
    for script in (updater.INSTALL_PS, updater._SIGNATURE_PS):
        assert '"' not in script


# -- the script that runs the installer, for real ----------------------------
#
# Stub programs stand in for setup.exe, PaperPull.exe and the folder's
# python.exe. Each writes where it ran from, whether it was handed the
# script's own variables, and its arguments to a file named after it, and
# ends with the code in a file beside it, so the script is run exactly as the
# panel runs it, by PowerShell, with a process to wait for. A file holding
# several codes gives them one run at a time, and each stub says it is
# version 0.61.0, as the release's installer does.

_STUB = r'''
using System; using System.IO; using System.Threading;
[assembly: System.Reflection.AssemblyInformationalVersion("0.61.0")]
static class Stub { static int Main(string[] a) {
  string me = System.Reflection.Assembly.GetEntryAssembly().Location;
  string handed = Environment.GetEnvironmentVariable("PAPERPULL_UPDATE_SETUP") ?? "";
  File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("STUB_DIR"), Path.GetFileName(me) + ".ran"),
                    me + "\n" + handed + "\n" + string.Join("\n", a));
  string ms = Environment.GetEnvironmentVariable("STUB_SLEEP_MS");
  if (!string.IsNullOrEmpty(ms)) Thread.Sleep(int.Parse(ms));
  string code = me + ".exit";
  if (!File.Exists(code)) return 0;
  string[] codes = File.ReadAllText(code).Trim().Split(' ');
  if (codes.Length > 1) File.WriteAllText(code, string.Join(" ", codes, 1, codes.Length - 1));
  return int.Parse(codes[0]);
} }
'''


def _signed(subject="CN=TNE Enterprises LLC, O=TNE Enterprises LLC, L=Town, S=State, C=US",
            issuer="CN=Microsoft ID Verified CS EOC CA 04, O=Microsoft Corporation, C=US",
            status="Valid"):
    """Get-AuthenticodeSignature as the script would find it on a release's
    installer, since no stub here carries the publisher's signature. In
    PowerShell a function comes before a command of the same name. It notes
    each file it was asked about."""
    return ("function Get-AuthenticodeSignature([string]$LiteralPath) {\n"
            "  Add-Content -LiteralPath (Join-Path $env:STUB_DIR 'signature.asked') -Value $LiteralPath\n"
            "  [pscustomobject]@{ Status = '%s'; SignatureType = 'Authenticode'; "
            "SignerCertificate = [pscustomobject]@{ Subject = '%s'; Issuer = '%s' } }\n"
            "}\n" % (status, subject, issuer))


def _as_signed(monkeypatch, **kw):
    """The script, with the stub installer read as signed by PaperPull's
    publisher, or by whatever `kw` names."""
    monkeypatch.setattr(updater, "INSTALL_PS", _signed(**kw) + updater.INSTALL_PS)


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


def _install_box(tmp_path, monkeypatch, stub_exe, app_name="Install Folder", work_name="paperpull-update-abc"):
    seen = tmp_path / "seen"
    seen.mkdir()
    app = tmp_path / app_name
    (app / "python").mkdir(parents=True)
    (app / "PaperPull.exe").write_bytes(stub_exe)
    (app / "python" / "python.exe").write_bytes(stub_exe)
    work = tmp_path / work_name
    work.mkdir()
    setup = work / "PaperPull-0.61.0-setup.exe"
    setup.write_bytes(stub_exe)
    monkeypatch.setenv("STUB_DIR", str(seen))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    return seen, app, setup, hashlib.sha256(stub_exe).hexdigest()


def _ran(seen, name):
    """Where the stub of that name ran from, the script variable it was
    handed, and its arguments."""
    deadline = time.time() + 10
    while True:
        # A stub that runs again writes its file again, and a read in
        # between can find it empty.
        lines = (seen / (name + ".ran")).read_text().split("\n")
        if len(lines) >= 3 or time.time() > deadline:
            return lines[0], lines[1], lines[2:]
        time.sleep(0.05)


def _after(proc, seen, *names):
    proc.wait(timeout=120)
    deadline = time.time() + 30
    while time.time() < deadline and not all((seen / (n + ".ran")).exists() for n in names):
        time.sleep(0.1)
    log = Path(updater.os.environ["APPDATA"]) / "PaperPull" / "update.log"
    return log.read_text(encoding="utf-8-sig") if log.exists() else ""


def _panel_for(seconds):
    """A process standing in for the panel, ending on its own."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(%s)" % seconds])
    threading.Thread(target=p.wait, daemon=True).start()
    return p


SETUP = "PaperPull-0.61.0-setup.exe"


def test_the_script_waits_installs_and_opens_paperpull_again(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    panel_proc = _panel_for(1.5)
    t = time.time()
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=panel_proc.pid)
    log = _after(proc, seen, SETUP, "PaperPull.exe")
    assert panel_proc.poll() is not None and time.time() - t >= 1.0
    where, handed, args = _ran(seen, SETUP)
    assert args[:4] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL"]
    assert args[4] == "/LOG=" + str(tmp_path / "Roaming" / "PaperPull" / "setup.log")
    assert handed == ""                           # its variables go no further
    assert not (seen / "python.exe.ran").exists()  # a whole copy is opened, not asked first
    where, handed, args = _ran(seen, "PaperPull.exe")
    assert where == str(app / "PaperPull.exe") and handed == "" and args == [""]
    assert "installed" in log and "opened PaperPull again" in log
    assert not setup.parent.exists()              # it cleans up after itself


def test_brackets_in_a_path_never_start_another_file(tmp_path, monkeypatch, stub_exe):
    """PowerShell's Start-Process reads [x] as a pattern, which matches a
    folder named with x alone. The script starts exactly the files it was
    given, from beside the very files that were checked."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe, app_name="Apps [x]",
                                         work_name="paperpull-update-[a]")
    for decoy in (tmp_path / "Apps x", tmp_path / "paperpull-update-a"):
        (decoy / "python").mkdir(parents=True)
        for name in ("PaperPull.exe", SETUP, "python/python.exe"):
            (decoy / name).write_bytes(stub_exe)
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, SETUP, "PaperPull.exe")
    assert _ran(seen, SETUP)[0] == str(setup)
    assert _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert "installed" in log and not setup.parent.exists()
    # The copy's own Python, asked when the installer never ran.
    for ran in seen.iterdir():
        ran.unlink()
    setup.parent.mkdir()
    setup.write_bytes(stub_exe)
    proc = updater.start_installer(app, setup, "0" * 64, "0.61.0", pid=_panel_for(0.2).pid)
    _after(proc, seen, "PaperPull.exe")
    assert _ran(seen, "python.exe")[0] == str(app / "python" / "python.exe")
    assert _ran(seen, "python.exe")[2] == ["-m", "uvicorn", "--version"]
    assert _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")


def test_the_script_never_runs_an_installer_that_changed(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    proc = updater.start_installer(app, setup, "0" * 64, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, "PaperPull.exe")
    assert not (seen / (SETUP + ".ran")).exists()
    assert "not the one the panel checked" in log and (seen / "PaperPull.exe.ran").exists()
    assert not setup.parent.exists()


def test_the_script_installs_nothing_while_the_panel_stays(tmp_path, monkeypatch, stub_exe):
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    stays = _panel_for(30)
    try:
        proc = updater.start_installer(app, setup, sha, "0.61.0", pid=stays.pid, wait_s=1)
        log = _after(proc, seen)
    finally:
        stays.kill()
    assert list(seen.iterdir()) == []             # neither the installer nor a second PaperPull
    assert "did not exit" in log and setup.is_file()


def _second_run(proc, seen):
    """The update log once the installer has run a second time."""
    proc.wait(timeout=120)
    deadline = time.time() + 30
    while time.time() < deadline and _ran(seen, SETUP)[2][:1] == ["/SILENT"]:
        time.sleep(0.1)
    log = _after(proc, seen)
    time.sleep(1.0)
    return log


@pytest.mark.parametrize("python_starts", [True, False])
def test_a_failed_install_opens_the_kept_installer_to_finish(tmp_path, monkeypatch, stub_exe, python_starts):
    """An installer that ran and failed can leave some new files and some
    old in the folder, and a Python that starts says nothing of the rest.
    So the kept installer opens again with its usual window, the very file
    that was checked, brackets and all, and never PaperPull over a copy it
    may have left half replaced."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe, work_name="paperpull-update-[f]")
    _as_signed(monkeypatch)
    decoy = tmp_path / "paperpull-update-f"
    decoy.mkdir()
    (decoy / SETUP).write_bytes(stub_exe)
    Path(str(setup) + ".exit").write_text("4")
    if not python_starts:
        Path(str(app / "python" / "python.exe") + ".exit").write_text("1")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _second_run(proc, seen)
    where, handed, args = _ran(seen, SETUP)
    assert where == str(setup) and args == [""]   # the second time, the usual window
    assert not (seen / "PaperPull.exe.ran").exists()
    assert "ended with 4" in log and "opened with its usual window to finish the update" in log
    assert setup.is_file()


def test_a_successful_install_opens_paperpull_whatever_its_first_start_does(tmp_path, monkeypatch, stub_exe):
    """The installer succeeded, so the copy is whole. The first start of the
    new files can be slow while they are scanned, or fail, and PaperPull.exe
    opens all the same, with a window of its own that says so, instead of
    nothing at all after the page said PaperPull opens again."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    Path(str(app / "python" / "python.exe") + ".exit").write_text("1")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, SETUP, "PaperPull.exe")
    assert _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert "installed" in log and "opened PaperPull again" in log and "does not start" not in log
    assert not setup.parent.exists()


def test_an_error_before_the_installer_ran_opens_it_for_a_copy_that_does_not_start(
        tmp_path, monkeypatch, stub_exe):
    """Something goes wrong before the installer ran, here a panel it cannot
    read the number of. The copy is the one the person had, and it does not
    start, so the kept installer opens with its usual window to put it right."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    Path(str(app / "python" / "python.exe") + ".exit").write_text("1")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid="not-a-number")
    log = _after(proc, seen, SETUP)
    time.sleep(1.0)
    assert _ran(seen, SETUP)[2] == [""] and not (seen / "PaperPull.exe.ran").exists()
    assert "stopped" in log and "installer was opened to finish the update" in log


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
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    monkeypatch.setenv("STUB_SLEEP_MS", "1000")
    gui = str(Path(updater.__file__).resolve().parent)
    done = subprocess.run([sys.executable, "-c", _HANDS_OVER, gui, str(app), str(setup), sha,
                           updater.os.pathsep.join(sys.path)],
                          capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2000:]
    deadline = time.time() + 60
    while time.time() < deadline and not (seen / "PaperPull.exe.ran").exists():
        time.sleep(0.2)
    assert (seen / (SETUP + ".ran")).exists() and (seen / "PaperPull.exe.ran").exists()


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


def test_a_program_running_from_the_folder_is_found(tmp_path, monkeypatch, stub_exe):
    folder = tmp_path / "PaperPull"
    (folder / "python").mkdir(parents=True)
    (folder / "python" / "python.exe").write_bytes(stub_exe)
    (tmp_path / "PaperPull-old").mkdir()
    (tmp_path / "PaperPull-old" / "python.exe").write_bytes(stub_exe)
    monkeypatch.setenv("STUB_DIR", str(tmp_path))
    monkeypatch.setenv("STUB_SLEEP_MS", "30000")
    inside = subprocess.Popen([str(folder / "python" / "python.exe")])
    beside = subprocess.Popen([str(tmp_path / "PaperPull-old" / "python.exe")])
    try:
        deadline = time.time() + 20
        found = []
        while time.time() < deadline and not found:
            found = updater.programs_running_from(folder)
            time.sleep(0.1)
        assert [Path(f).resolve() for f in found] == [(folder / "python" / "python.exe").resolve()]
        assert updater.programs_running_from(folder, {inside.pid}) == []
    finally:
        inside.kill()
        beside.kill()


class _Started:
    """subprocess.Popen as start_installer uses it, a script that says at
    once that it is waiting, with the environment it was given kept."""
    seen = []

    flags = []

    def __init__(self, cmd, env=None, **kw):
        _Started.seen.append(env)
        _Started.flags.append(kw.get("creationflags", 0))
        Path(env["PAPERPULL_UPDATE_STARTED"]).write_text("waiting")

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
    assert env["PAPERPULL_UPDATE_WAIT"] == "%d 4242" % updater.os.getpid()
    assert env["PAPERPULL_UPDATE_SETUP"] == str(setup) and env["PAPERPULL_UPDATE_SHA256"] == sha
    assert env["PAPERPULL_UPDATE_APP"] == str(folder) and env["PAPERPULL_UPDATE_VERSION"] == "0.61.0"
    assert "PAPERPULL_VERSION" not in env or env["PAPERPULL_VERSION"] == updater.os.environ.get("PAPERPULL_VERSION")
    monkeypatch.setattr(updater, "_image_of", lambda pid: r"C:\Windows\explorer.exe")
    updater.start_installer(folder, setup, sha, "0.61.0")
    assert _Started.seen[-1]["PAPERPULL_UPDATE_WAIT"] == str(updater.os.getpid())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows names a process's program")
def test_the_program_a_process_runs_is_read(tmp_path):
    image = updater._image_of(updater.os.getpid())
    assert image.lower().endswith("python.exe") and Path(image).is_file()
    assert updater._image_of(0) == ""


# -- what the review of the Windows install found ---------------------------

def test_a_pc_that_allows_only_restricted_powershell_is_told_so(tmp_path, monkeypatch):
    """Where an organization locks PowerShell to its restricted language,
    neither script can run, so the copy says so before it downloads."""
    class Ran:
        stdout = "restricted\r\n"
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: Ran())
    assert updater.windows_signature(tmp_path / "x.exe") == {"restricted": True}
    with pytest.raises(updater.UpdateError, match="restricted commands"):
        updater.this_copy_is_signed(tmp_path)
    setup, sha = _installer(tmp_path)
    with pytest.raises(updater.UpdateError, match="restricted commands"):
        updater.verify_installer(setup, sha, "0.61.0")
    assert "LanguageMode -ne 'FullLanguage') { 'restricted'; exit }" in updater._SIGNATURE_PS


def test_a_folder_this_account_cannot_write_is_found_by_writing(tmp_path, monkeypatch):
    folder = tmp_path / "PaperPull"
    folder.mkdir()
    assert updater.can_write(folder) and list(folder.iterdir()) == []
    assert not updater.can_write(tmp_path / "not there")
    asked = []
    monkeypatch.setattr(updater, "this_copy_is_signed", lambda folder: True)
    monkeypatch.setattr(updater, "can_write", lambda folder: False)
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: asked.append(a))
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    snap = _finish(inst)
    assert snap["phase"] == "error" and "cannot change" in snap["error"] and asked == []


def test_a_ready_update_is_kept_from_a_second_download(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    started = []
    monkeypatch.setattr(updater.threading, "Thread", lambda *a, **k: started.append(k) or pytest.fail("started"))
    inst.start("0.60.1", tmp_path / "PaperPull", kind="windows")
    assert inst.phase == "ready" and inst.staged == setup and setup.is_file() and started == []


def test_restart_waits_while_another_paperpull_program_runs_from_the_folder(tmp_path, monkeypatch):
    """The installer would close it, a download started in a terminal with
    paperpull.bat among them, or fail on a file it holds."""
    inst, setup, sha = _windows_ready(tmp_path)
    started, looked = [], []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)
    monkeypatch.setattr(updater, "start_installer", lambda *a: started.append(a))
    seen_but = []

    def running(folder, but=()):
        seen_but.append(set(but))
        return [str(folder / "python" / "python.exe")]
    monkeypatch.setattr(updater, "programs_running_from", running)
    with pytest.raises(updater.UpdateError, match="running from its folder"):
        inst.restart(lambda: looked.append(1) or "")
    assert started == [] and looked == [] and inst.phase == "ready" and setup.is_file()
    assert seen_but == [{updater.os.getpid(), updater.os.getppid()}]


def test_an_installer_the_script_took_with_it_leaves_nothing_ready(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)

    def gone(*a):
        setup.unlink()
        raise updater.UpdateError("the installer could not be started")
    monkeypatch.setattr(updater, "start_installer", gone)
    with pytest.raises(updater.UpdateError):
        inst.restart()
    assert inst.phase == "idle"


def test_a_copy_off_the_mac_and_windows_gets_no_mac_words(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    ok, why = updater.can_install(None)
    assert not ok and "Mac" not in why and "git pull" in why


# -- what the review of those repairs found ---------------------------------

def test_an_installer_that_was_not_the_one_checked_is_never_opened(tmp_path, monkeypatch, stub_exe):
    """Even when PaperPull would not start, a changed installer is not the
    way to finish anything."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    Path(str(app / "python" / "python.exe") + ".exit").write_text("1")
    proc = updater.start_installer(app, setup, "0" * 64, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, "python.exe")
    time.sleep(1.0)
    assert not (seen / (SETUP + ".ran")).exists() and not (seen / "PaperPull.exe.ran").exists()
    assert "not the one the panel checked" in log and "Download the installer from the release page" in log
    assert not setup.parent.exists()


def test_a_python_that_cannot_even_be_started_counts_as_a_no(tmp_path, monkeypatch, stub_exe):
    """A file of no bytes where the Python was. Windows will not start it,
    and that is a no like any other. Here the installer was not the one
    checked, so nothing opens and the log says where to get the installer."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    (app / "python" / "python.exe").write_bytes(b"")
    # A panel that is still there when the script says it is waiting, as a
    # real one is. This script is over so soon after that, with nothing to
    # start, that it could end between two of the panel's looks.
    proc = updater.start_installer(app, setup, "0" * 64, "0.61.0", pid=_panel_for(2.0).pid)
    log = _after(proc, seen)
    time.sleep(1.0)
    assert list(seen.iterdir()) == []
    assert "would not start" in log and "Download the installer from the release page" in log


def test_the_script_is_not_put_in_a_process_group_of_its_own(tmp_path, monkeypatch):
    """A group of its own turns Ctrl+C off, for the script and for the
    PaperPull it opens again, whose window says Ctrl+C stops it."""
    folder = tmp_path / "PaperPull"
    folder.mkdir()
    setup, sha = _installer(tmp_path)
    monkeypatch.setattr(updater.subprocess, "Popen", _Started)
    _Started.flags.clear()
    updater.start_installer(folder, setup, sha, "0.61.0", pid=4242)
    group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    assert _Started.flags and not _Started.flags[-1] & group


def test_a_ready_update_whose_file_went_starts_over(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    updater.shutil.rmtree(setup.parent)
    with pytest.raises(updater.UpdateError, match="no update is ready"):
        inst.restart()
    assert inst.phase == "idle"


def test_a_process_list_windows_will_not_give_does_not_stop_the_update(tmp_path, monkeypatch):
    inst, setup, sha = _windows_ready(tmp_path)
    started = []
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)
    monkeypatch.setattr(updater, "start_installer", lambda *a: started.append(a))

    def broken(*a):
        raise OSError("access denied")
    monkeypatch.setattr(updater, "programs_running_from", broken)
    inst.restart(lambda: "")
    assert len(started) == 1 and inst.phase == "restarting"


# -- what the review of the 0.65.0 install left ------------------------------

def _while_the_installer_runs(seen, setup, then):
    """Once the installer's silent run has started, moves its file aside as
    another program of the person's could, then does `then`. The stub sleeps
    for STUB_SLEEP_MS, so this happens before it ends with its code."""
    deadline = time.time() + 30
    while not (seen / (SETUP + ".ran")).exists():
        assert time.time() < deadline, "the installer never ran"
        time.sleep(0.05)
    aside = setup.parent.parent / "aside.exe"
    while True:
        try:
            # A running program can be renamed, once the script lets go of it.
            updater.os.replace(setup, aside)
            break
        except PermissionError:
            assert time.time() < deadline, "the installer stayed held"
            time.sleep(0.05)
    return then()


def _ran_once_silently(seen):
    return _ran(seen, SETUP)[2][:1] == ["/SILENT"]


@pytest.mark.parametrize("python_starts", [True, False])
def test_a_kept_installer_that_went_ends_plainly_and_opens_paperpull(tmp_path, monkeypatch, stub_exe,
                                                                     python_starts):
    """The installer ran and failed, and by the time it ended its file was
    gone. The log says so plainly, and the PaperPull that was running opens
    again, with nothing else run first, so the person is not left with
    nothing when its Python does not start either."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    monkeypatch.setenv("STUB_SLEEP_MS", "1500")
    Path(str(setup) + ".exit").write_text("4")
    if not python_starts:
        Path(str(app / "python" / "python.exe") + ".exit").write_text("1")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    _while_the_installer_runs(seen, setup, lambda: None)
    log = _after(proc, seen, "PaperPull.exe")
    assert _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert not (seen / "python.exe.ran").exists() and _ran_once_silently(seen)
    assert "ended with 4" in log and "no longer where it was kept" in log
    assert "Download the installer from the release page" in log and "opened PaperPull again" in log
    assert not setup.parent.exists()


def test_a_kept_installer_that_cannot_be_started_ends_plainly_and_opens_paperpull(
        tmp_path, monkeypatch, stub_exe):
    """The kept installer is there, the very file that was checked, but
    another program holds it open to write, as a scanner can, so it cannot
    start. The log says so, PaperPull opens again, and nothing else runs."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    monkeypatch.setenv("STUB_SLEEP_MS", "1500")
    Path(str(setup) + ".exit").write_text("4")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)

    def hold():
        setup.write_bytes(stub_exe)
        return open(setup, "r+b")
    held = _while_the_installer_runs(seen, setup, hold)
    try:
        log = _after(proc, seen, "PaperPull.exe")
    finally:
        held.close()
    assert _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert not (seen / "python.exe.ran").exists() and _ran_once_silently(seen)
    assert "could not be opened again" in log and "Download the installer from the release page" in log


def test_an_installer_that_cannot_start_at_all_opens_paperpull_and_nothing_else(tmp_path, monkeypatch, stub_exe):
    """The checked file is not a program Windows will start. Nothing was
    installed, so the copy is the one the person had, and it opens again
    without a check of its Python or a second try of the installer."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    setup.write_bytes(b"not a program")
    sha = hashlib.sha256(b"not a program").hexdigest()
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, "PaperPull.exe")
    time.sleep(1.0)
    assert sorted(p.name for p in seen.iterdir()) == ["PaperPull.exe.ran"]
    assert "the installer could not be started, so nothing was installed" in log
    assert "opened PaperPull again" in log and not setup.parent.exists()


def test_a_kept_installer_that_changed_is_never_opened_again(tmp_path, monkeypatch, stub_exe):
    """%TEMP% can be written by the person's other programs. A kept
    installer whose bytes changed while it ran is refused before it would
    open again, plainly, and PaperPull opens instead."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    monkeypatch.setenv("STUB_SLEEP_MS", "1500")
    Path(str(setup) + ".exit").write_text("4")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    _while_the_installer_runs(seen, setup, lambda: setup.write_bytes(stub_exe + b"changed"))
    log = _after(proc, seen, "PaperPull.exe")
    time.sleep(1.0)
    assert _ran_once_silently(seen) and _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert "changed after it was checked, so it was not opened again" in log
    assert not setup.parent.exists()


@pytest.mark.parametrize("signature", ["none", "someone else"])
def test_a_kept_installer_not_signed_by_the_publisher_is_never_opened_again(tmp_path, monkeypatch, stub_exe,
                                                                            signature):
    """The same bytes, read again just before the installer would open, and
    its signature checked as the panel checks it. The stub carries none,
    read by Windows itself, or one by somebody else."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    if signature == "someone else":
        _as_signed(monkeypatch, subject="CN=Someone Else, O=Someone Else, L=Town, S=State, C=US")
    Path(str(setup) + ".exit").write_text("4")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _after(proc, seen, SETUP, "PaperPull.exe")
    time.sleep(1.0)
    assert _ran_once_silently(seen) and _ran(seen, "PaperPull.exe")[0] == str(app / "PaperPull.exe")
    assert "no longer signed by the publisher of PaperPull, so it was not opened again" in log
    assert not setup.parent.exists()
    if signature == "someone else":
        assert (seen / "signature.asked").read_text().split("\n")[0] == str(setup)


def test_a_kept_installer_that_finishes_the_update_is_removed(tmp_path, monkeypatch, stub_exe):
    """The installer failed once and opened again, and this time it
    installed. It is no longer needed, so its folder goes."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    _as_signed(monkeypatch)
    Path(str(setup) + ".exit").write_text("4 0")
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid=_panel_for(0.2).pid)
    log = _second_run(proc, seen)
    assert _ran(seen, SETUP)[2] == [""] and not (seen / "PaperPull.exe.ran").exists()
    assert "opened with its usual window to finish the update" in log and "finished the update" in log
    assert not setup.parent.exists()


def test_a_kept_installer_paperpull_opened_instead_of_is_removed(tmp_path, monkeypatch, stub_exe):
    """Something went wrong before the installer ran, and the copy the
    person had starts, so it opens again and the installer is not needed."""
    seen, app, setup, sha = _install_box(tmp_path, monkeypatch, stub_exe)
    proc = updater.start_installer(app, setup, sha, "0.61.0", pid="not-a-number")
    log = _after(proc, seen, "python.exe", "PaperPull.exe")
    time.sleep(1.0)
    assert not (seen / (SETUP + ".ran")).exists() and (seen / "PaperPull.exe.ran").exists()
    assert "stopped" in log and "opened PaperPull again" in log
    assert not setup.parent.exists()


def _made(where, name, *files):
    folder = where / name
    folder.mkdir()
    for f in files:
        (folder / f).write_bytes(b"x")
    return folder


def test_a_new_update_removes_the_installers_earlier_updates_kept(tmp_path, monkeypatch):
    """Only the folders the updater made, named as tempfile.mkdtemp names
    them, holding nothing but the files the updater writes there. Anything
    else in the temp folder is left as it is, a link of the same name too."""
    temp = Path(updater.tempfile.gettempdir())
    gone = [_made(temp, "paperpull-update-abc12_yz", "PaperPull-0.60.0-setup.exe", "started"),
            _made(temp, "paperpull-update-k9m2p0qr", "PaperPull-0.61.0-setup.exe.part"),
            _made(temp, "paperpull-update-zzzzzzzz")]
    kept = [_made(temp, "paperpull-update-q1w2e3r4", "PaperPull-0.60.0-setup.exe", "notes.txt"),
            _made(temp, "paperpull-update-a1b2c3d4", "PaperPull-0.60.0-setup.exe.bak"),
            _made(temp, "paperpull-update-b1b2c3d4", "PaperPull-0.60.0-arm64.dmg"),
            _made(temp, "paperpull-update-c1b2c3d4", "swap.sh"),
            _made(temp, "paperpull-update-mine", "PaperPull-0.60.0-setup.exe"),
            _made(temp, "paperpull-update-abcdefghi", "PaperPull-0.60.0-setup.exe"),
            _made(temp, "Paperpull-Update-d1b2c3d4", "PaperPull-0.60.0-setup.exe"),
            _made(temp, "someone-elses", "PaperPull-0.60.0-setup.exe", "started")]
    deeper = _made(temp, "paperpull-update-e1b2c3d4", "PaperPull-0.60.0-setup.exe")
    _made(deeper, "mnt", "PaperPull.app")
    kept.append(deeper)
    loose = temp / "PaperPull-0.60.0-setup.exe"
    loose.write_bytes(b"x")
    files_before = sorted(str(p) for k in kept for p in k.rglob("*"))
    link = temp / "paperpull-update-f1b2c3d4"
    target = _made(tmp_path, "elsewhere", "PaperPull-0.60.0-setup.exe")
    linked = False
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        linked = True
    try:
        updater.remove_kept_installers()
        assert [g for g in gone if g.exists()] == []
        assert sorted(str(p) for k in kept for p in k.rglob("*")) == files_before
        assert loose.is_file() and (target / "PaperPull-0.60.0-setup.exe").is_file()
        if linked:
            assert updater.os.path.lexists(link)
    finally:
        if linked:
            updater.os.rmdir(link)


def test_a_new_update_on_windows_starts_by_removing_what_earlier_ones_kept(tmp_path, monkeypatch):
    temp = Path(updater.tempfile.gettempdir())
    old = _made(temp, "paperpull-update-old00000", "PaperPull-0.60.0-setup.exe")
    body = b"installer"
    monkeypatch.setattr(updater, "this_copy_is_signed", lambda folder: True)
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: dict(_windows_rel(body=body), newer=True))
    monkeypatch.setattr(updater, "_open", lambda url, timeout=20: _Resp(body))
    monkeypatch.setattr(updater, "verify_installer", lambda *a: None)
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="windows")
    assert _finish(inst)["phase"] == "ready"
    assert not old.exists() and inst.staged.is_file() and inst.staged.parent.parent == temp


def test_a_mac_update_leaves_the_temp_folder_alone(tmp_path, monkeypatch):
    """A Mac's work folder holds a disk image's mount point, and the swap
    script removes its own, so a Mac update removes nothing there."""
    temp = Path(updater.tempfile.gettempdir())
    old = _made(temp, "paperpull-update-old00000", "PaperPull-0.60.0-setup.exe")
    monkeypatch.setattr(updater, "check_latest", lambda *a, **k: {"newer": False})
    inst = updater.Install()
    inst.start("0.60.1", tmp_path, kind="mac")
    assert _finish(inst)["phase"] == "error" and old.is_dir()
