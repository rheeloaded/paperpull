"""The sign-in offers to bring PaperPull's own Chromium up to date (#132).

After the first download nothing updated it. Sign-in starts the newest build
on disk, and an upgrade that brings a newer Playwright does not download that
Playwright's Chromium, so a copy taken months ago kept signing in with that
build while each release carried a newer one with its security fixes.

The one promise that matters most is that a failed update never costs a person
the browser they had. Playwright's install removes builds nothing else uses
before it downloads, so the download holds that back, and the old build stays
until the new one has opened.

The builds on disk are real folders in a folder of the test's own, read by the
real code. The download is a stand-in that leaves what the test says it left,
and the sign-in's own launch is replaced by one that notes which browser and
profile it was given. The end of this file runs Playwright's real install
against a stand-in for the download server, since that order is Playwright's
and no stand-in here can hold it.
"""
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser  # noqa: E402

OLD, WANTED = 1228, 1248
INSTALL = ["/pkg/python3", "-m", "playwright", "install", "chromium"]
INNER = ("chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
         "Google Chrome for Testing")


def _lay(root, build, finished=True, inner=INNER):
    """A build in root as an install leaves it, with Playwright's mark when
    it finished. Returns its executable."""
    exe = root / ("chromium-%d" % build) / inner
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"chromium %d" % build)
    if finished:
        (root / ("chromium-%d" % build) / browser.INSTALLED_MARK).write_text("")
    return str(exe)


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """A Mac with only Chromium build OLD, whose Playwright wants WANTED, and
    where nothing else is installed. A Mac since the bundled copy goes first
    there whatever folder it is in, and nothing here turns on that."""
    m = type("Machine", (), {})()
    m.root = tmp_path / "ms-playwright"
    m.old = _lay(m.root, OLD)
    m.new = str(m.root / ("chromium-%d" % WANTED) / INNER)
    m.real = []
    m.opened = []
    m.refused = set()
    m.downloads = []
    m.cleared = []
    m.answers = []
    m.asked = []
    m.exit_code = 0
    m.stopped_by = None
    m.arrives = "finished"      # or "partway", or None
    m.tty = True

    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.delenv(browser.KEEP_OLD_BUILDS, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(m.root))
    monkeypatch.setattr(browser, "_real_browsers", lambda: list(m.real))
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: WANTED)
    monkeypatch.setattr(browser, "_install_takes_no_remove", lambda: True)
    monkeypatch.setattr(browser, "browser_install_command", lambda: list(INSTALL))
    monkeypatch.setattr(browser, "can_ask", lambda: m.tty)
    monkeypatch.setattr(browser, "_say_shared_port", lambda port: None)

    def download(cmd, env=None, **kw):
        m.downloads.append((list(cmd), (env or {}).get(browser.KEEP_OLD_BUILDS)))
        if m.arrives:
            _lay(m.root, WANTED, finished=m.arrives == "finished")
        if m.stopped_by:
            raise m.stopped_by
        return m.exit_code

    class Clearing:
        """The run that clears the old build, noting what was so as it began."""

        def __init__(self, cmd, **kw):
            m.cleared.append({"cmd": list(cmd), "kw": kw, "opened": list(m.opened),
                              "old on disk": os.path.exists(m.old)})

    def answer(prompt):
        m.asked.append(prompt)
        if not m.answers:
            raise AssertionError("asked a question nobody planned for: %r" % prompt)
        return m.answers.pop(0)

    def launch(exe, name, profile_dir, port, url, explain_failure=True, mode=browser.AUTO):
        m.opened.append((exe, Path(profile_dir).name))
        return None if exe in m.refused else name

    monkeypatch.setattr(browser.subprocess, "call", download)
    monkeypatch.setattr(browser.subprocess, "Popen", Clearing)
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(browser, "_launch", launch)
    return m


def _sign_in(tmp_path, **kw):
    return browser.open_signin_browser(tmp_path / "profile", "9222", "https://x.test", **kw)


# -- reading what Playwright wants ------------------------------------------------

def _package(tmp_path, listed):
    folder = tmp_path / "playwright" / "driver" / "package"
    folder.mkdir(parents=True)
    (folder / "browsers.json").write_text(json.dumps(listed), encoding="utf-8")
    return tmp_path / "playwright"


def test_the_build_playwright_wants_is_read_from_its_browsers_json(monkeypatch, tmp_path):
    pkg = _package(tmp_path, {"browsers": [
        {"name": "chromium-headless-shell", "revision": "1248"},
        {"name": "firefox", "revision": "1500"},
        {"name": "chromium", "revision": "1248"}]})
    monkeypatch.setattr(browser, "_playwright_package", lambda: pkg)
    assert browser._wanted_chromium_build() == 1248


@pytest.mark.parametrize("listed", [{}, {"browsers": []}, {"browsers": [{"name": "firefox"}]},
                                    {"browsers": [{"name": "chromium", "revision": "next"}]}, []])
def test_a_browsers_json_that_cannot_say_gives_none(monkeypatch, tmp_path, listed):
    monkeypatch.setattr(browser, "_playwright_package", lambda: _package(tmp_path, listed))
    assert browser._wanted_chromium_build() is None


def test_no_playwright_gives_none(monkeypatch):
    monkeypatch.setattr(browser, "_playwright_package", lambda: None)
    assert browser._wanted_chromium_build() is None


def test_a_copy_is_due_only_when_older_than_what_playwright_wants(machine):
    assert browser.chromium_update_due(machine.old) == (OLD, WANTED)
    assert browser.chromium_update_due(machine.new) is None
    assert browser.chromium_update_due(machine.new.replace(str(WANTED), str(WANTED + 5))) is None
    assert browser.chromium_update_due("/somewhere/else/chrome") is None


def test_with_no_wanted_build_nothing_is_due(machine, monkeypatch):
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: None)
    assert browser.chromium_update_due(machine.old) is None


# -- at sign-in, with someone to ask -----------------------------------------------

def test_agreeing_downloads_the_build_and_signs_in_with_it(machine, tmp_path, capsys):
    machine.answers = ["y"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert [cmd for cmd, _kept in machine.downloads] == [INSTALL]
    assert machine.opened == [(machine.new, "profile")]
    said = capsys.readouterr().out
    assert "build %d" % OLD in said and "build %d" % WANTED in said
    assert "400 MB" in said and "about the same" in said
    assert "Close any other sign-in windows first" in said
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


def test_the_download_holds_playwrights_removal_back(machine, tmp_path):
    """Playwright's install removes builds nothing else uses before it
    downloads, so without this a download that fails takes the old build."""
    machine.answers = ["y"]
    _sign_in(tmp_path)
    assert machine.downloads == [(INSTALL, "1")]


def test_the_old_build_is_cleared_only_after_the_new_one_has_opened(machine, tmp_path):
    machine.answers = ["y"]
    _sign_in(tmp_path)
    assert len(machine.cleared) == 1
    clearing = machine.cleared[0]
    assert clearing["opened"] == [(machine.new, "profile")]
    assert clearing["old on disk"]
    # The same command with nothing held back, which is what removes the
    # build. An env handed to it would have to leave the variable out.
    assert clearing["cmd"] == INSTALL and "env" not in clearing["kw"]


def test_the_clearing_is_left_to_itself(machine, tmp_path):
    """Playwright's removal waited 745 seconds on a file a window left open
    held, so nothing here waits for it, and nothing it writes reaches a
    panel reading this process's output."""
    machine.answers = ["y"]
    _sign_in(tmp_path)
    assert len(machine.downloads) == 1      # not run through call, which waits
    kw = machine.cleared[0]["kw"]
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
    assert kw["start_new_session"] is True


def test_a_clearing_that_cannot_start_costs_only_the_space(machine, monkeypatch, tmp_path):
    def cannot(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(browser.subprocess, "Popen", cannot)
    machine.answers = ["y"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert os.path.exists(machine.old)


def test_saying_no_signs_in_with_the_old_build_and_is_not_asked_again(machine, tmp_path, capsys):
    machine.answers = ["n"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.downloads == []
    assert machine.opened == [(machine.old, "profile")]
    assert (machine.root / browser.DECLINED_UPDATE).read_text().strip() == str(WANTED)
    assert "Nothing was downloaded" in capsys.readouterr().out

    # The next sign-in, in this app or another, asks nothing
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert len(machine.asked) == 1
    assert machine.opened[-1] == (machine.old, "profile")


def test_a_newer_wanted_build_asks_again_after_a_no(machine, monkeypatch, tmp_path):
    machine.answers = ["n", "n"]
    _sign_in(tmp_path)
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: WANTED + 12)
    _sign_in(tmp_path)
    assert len(machine.asked) == 2


def test_an_empty_answer_is_a_no(machine, tmp_path):
    machine.answers = [""]
    _sign_in(tmp_path)
    assert machine.downloads == []


def test_a_download_that_fails_leaves_the_old_build_in_use_and_asks_again_next_time(
        machine, tmp_path, capsys):
    machine.answers = ["y"]
    machine.exit_code = 1
    machine.arrives = None
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []
    assert "did not finish" in capsys.readouterr().out
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


def test_a_download_that_leaves_no_newer_build_is_not_a_success(machine, tmp_path, capsys):
    machine.answers = ["y"]
    machine.arrives = None              # exits 0 and puts nothing on disk
    _sign_in(tmp_path)
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []
    assert "did not finish" in capsys.readouterr().out


def test_a_finished_build_is_started_though_the_install_ended_with_an_error(
        machine, tmp_path, capsys):
    """Playwright fetches Chromium first, so with its headless shell refused
    the install exits 1 with a finished build on disk. That build is the one
    that starts, and the install is not called finished, so nothing is
    cleared."""
    machine.answers = ["y"]
    machine.exit_code = 1
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.new, "profile")]
    assert machine.cleared == []
    assert "did not finish" in capsys.readouterr().out


def test_an_install_killed_partway_leaves_the_finished_build_in_charge(machine, tmp_path):
    """The folder of the new build holds the executable and no mark, as a real
    install killed while it unpacked left it. The finished build is what
    starts, the update is still due, and it is offered again."""
    machine.answers = ["y"]
    machine.exit_code = 1
    machine.arrives = "partway"
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert os.path.exists(machine.new)
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []
    assert browser.browser_candidates(mode=browser.BUNDLED) == [(browser.CHROMIUM, machine.old)]
    assert browser.chromium_update_due(machine.old) == (OLD, WANTED)
    assert browser.bundled_chromium_present()

    machine.answers = ["n"]
    _sign_in(tmp_path)
    assert len(machine.asked) == 2
    assert machine.opened[-1] == (machine.old, "profile")


@pytest.mark.parametrize("arrives", [None, "partway"], ids=["downloading", "unpacking"])
def test_ctrl_c_during_the_download_goes_on_to_the_old_build(machine, tmp_path, capsys, arrives):
    """Somebody tired of a slow download lands on the build they had, and it
    took the whole sign-in with it until this was caught."""
    machine.answers = ["y"]
    machine.arrives = arrives
    machine.stopped_by = KeyboardInterrupt()
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []
    assert "The download was stopped" in capsys.readouterr().out
    # Nobody said no, so it is offered at the next sign-in
    assert not (machine.root / browser.DECLINED_UPDATE).exists()
    assert browser.chromium_update_due(machine.old) == (OLD, WANTED)


def test_ctrl_c_is_answered_by_the_offer_itself(machine, monkeypatch):
    """The offer says the download stopped, so it stops here and not in
    whatever stands around it."""
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    machine.arrives = None
    machine.stopped_by = KeyboardInterrupt()
    assert browser.offer_chromium_update(OLD, WANTED) is False


# -- a new build that will not open ---------------------------------------------------
#
# A download can finish and leave a build this computer will not start, one
# made for a newer system or one a security program holds. That is a failed
# update like any other.

def test_a_new_build_that_will_not_open_hands_the_sign_in_back_to_the_old_one(
        machine, tmp_path, capsys):
    machine.answers = ["y"]
    machine.refused = {machine.new}
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.new, "profile"), (machine.old, "profile")]
    assert machine.cleared == []
    assert "Build %d did not open on this computer" % WANTED in capsys.readouterr().out


def test_the_person_keeps_their_profile_ahead_of_a_browser_of_their_own(machine, tmp_path):
    """The old build is tried first and on their own profile, the sign-ins
    they already have, and their Edge is what comes after it."""
    machine.answers = ["y"]
    machine.real = [(browser.EDGE, "/x/edge")]
    machine.refused = {machine.new, machine.old}
    _sign_in(tmp_path)
    assert machine.opened == [(machine.new, "profile"), (machine.old, "profile"),
                              ("/x/edge", "profile-microsoftedge")]


def test_a_new_build_that_would_not_open_is_not_the_newest_at_the_next_sign_in(machine, tmp_path):
    """Left as it was it would be the build every later sign-in starts, with
    the one that works on disk and never tried, and asked about for nothing."""
    machine.answers = ["y"]
    machine.refused = {machine.new}
    _sign_in(tmp_path)
    assert browser._bundled_chromium() == [machine.old]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert len(machine.asked) == 1
    assert machine.opened[-1] == (machine.old, "profile")
    assert len(machine.downloads) == 1


def test_a_build_that_cannot_download_says_so(machine, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(browser, "browser_install_command", lambda: None)
    machine.answers = ["y"]
    _sign_in(tmp_path)
    assert machine.downloads == []
    assert "cannot download" in capsys.readouterr().out


# -- at sign-in, with no one to ask (the control panel) -----------------------------

def test_with_no_one_to_ask_it_says_so_and_gives_the_command(machine, tmp_path, capsys):
    machine.tty = False
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.downloads == [] and machine.asked == []
    assert machine.opened == [(machine.old, "profile")]
    said = capsys.readouterr().out
    assert "/pkg/python3 -m playwright install chromium --no-remove" in said
    assert "sign in again" in said
    assert "stays beside it" in said and "cleared away" not in said
    # Nobody said no, so the next sign-in says it again
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


@pytest.mark.parametrize("platform,line", [
    ("darwin", "PLAYWRIGHT_SKIP_BROWSER_GC=1 /pkg/python3 -m playwright install chromium"),
    ("linux", "PLAYWRIGHT_SKIP_BROWSER_GC=1 /pkg/python3 -m playwright install chromium"),
    ("win32", "set PLAYWRIGHT_SKIP_BROWSER_GC=1&& /pkg/python3 -m playwright install chromium"),
])
def test_a_playwright_without_the_flag_is_given_the_variable_instead(
        machine, monkeypatch, tmp_path, capsys, platform, line):
    """1.62, which checkouts still have, stops at --no-remove. Pasted with
    nothing at all, the line would remove the old build first."""
    monkeypatch.setattr(browser, "_install_takes_no_remove", lambda: False)
    monkeypatch.setattr(sys, "platform", platform)
    assert browser._update_line(INSTALL) == line


@pytest.mark.parametrize("version,takes_it", [
    ("1.62.0", False), ("1.61.1", False), ("1.63.0", True), ("1.64.1", True),
    # What the driver of Playwright 1.64.1 gives as its own version
    ("1.64.0-beta-1791568591000", True), ("2.0.0", True),
    ("", False), ("next", False), (None, False)])
def test_which_playwright_takes_the_flag_is_read_from_its_driver(
        monkeypatch, tmp_path, version, takes_it):
    package = tmp_path / "playwright"
    (package / "driver" / "package").mkdir(parents=True)
    (package / "driver" / "package" / "package.json").write_text(
        json.dumps({"version": version}), encoding="utf-8")
    monkeypatch.setattr(browser, "_playwright_package", lambda: package)
    assert browser._install_takes_no_remove() is takes_it


def test_with_no_driver_to_read_the_flag_is_not_used(monkeypatch, tmp_path):
    monkeypatch.setattr(browser, "_playwright_package", lambda: None)
    assert browser._install_takes_no_remove() is False
    monkeypatch.setattr(browser, "_playwright_package", lambda: tmp_path)
    assert browser._install_takes_no_remove() is False


# -- where it is not offered ---------------------------------------------------------

def test_an_up_to_date_copy_is_not_offered_anything(machine, tmp_path, capsys):
    _lay(machine.root, WANTED)
    _sign_in(tmp_path)
    assert machine.asked == [] and machine.downloads == []
    assert "security fixes" not in capsys.readouterr().out


def test_nothing_is_offered_about_a_copy_that_would_not_be_started(machine, monkeypatch, tmp_path):
    """Their own Edge or Chrome goes first for an app that asks for it, so a
    stale private copy they do not use is none of their business."""
    machine.real = [(browser.EDGE, "/x/edge")]
    _sign_in(tmp_path, prefer_real=True)
    assert machine.opened[0][0] == "/x/edge"
    assert machine.asked == [] and machine.downloads == []


def test_an_app_set_to_use_only_their_own_browser_is_not_asked(machine, tmp_path):
    _sign_in(tmp_path, mode=browser.INSTALLED)
    assert machine.asked == [] and machine.downloads == []


def test_a_sign_in_that_may_not_download_is_not_asked(machine, tmp_path):
    _sign_in(tmp_path, allow_fetch=False)
    assert machine.asked == [] and machine.downloads == []


def test_paperpull_server_is_not_asked(machine, monkeypatch, tmp_path):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    _sign_in(tmp_path)
    assert machine.asked == [] and machine.downloads == []


def test_an_unwritable_folder_for_the_answer_costs_only_a_second_question(machine, monkeypatch, tmp_path):
    monkeypatch.setattr(browser, "_declined_file", lambda: tmp_path / "no" / "such" / "folder" / "x")
    monkeypatch.setattr(Path, "write_text",
                        lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("read-only")))
    machine.answers = ["n", "n"]
    _sign_in(tmp_path)
    _sign_in(tmp_path)
    assert len(machine.asked) == 2


# -- Playwright's real install ---------------------------------------------------------
#
# What the promise rests on is Playwright's, the order of its removal and its
# download and the variable that holds the removal back. So this runs the real
# `playwright install` in a folder of the test's own, against a stand-in for
# the download server on this computer. Nothing is fetched from anywhere and no
# browser starts. Windows only, since the stand-in's archive holds the Windows
# names, and a Playwright on any system runs the same removal.

class _DownloadServer(http.server.BaseHTTPRequestHandler):
    refusing = False
    got = []

    def do_GET(self):
        type(self).got.append(self.path)
        if type(self).refusing:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(_ARCHIVE)))
        self.end_headers()
        self.wfile.write(_ARCHIVE)

    def log_message(self, *a):
        pass


def _archive():
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as z:
        for name in ("chrome-win64/chrome.exe",
                     "chrome-headless-shell-win64/chrome-headless-shell.exe",
                     "ffmpeg-win64.exe", "PrintDeps.exe"):
            z.writestr(name, b"MZ the new build")
    return packed.getvalue()


_ARCHIVE = _archive()


def _bytes_of(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture
def real_install(monkeypatch, tmp_path):
    """Build 1000 on disk, Playwright's real install, a server of the test's
    own, and the sign-in's launch noting what it was handed and what was on
    disk at that moment."""
    pytest.importorskip("playwright")
    if sys.platform != "win32":
        pytest.skip("the stand-in's archive holds the Windows names")
    m = type("RealInstall", (), {})()
    m.root = tmp_path / "ms-playwright"
    m.old = m.root / "chromium-1000"
    (m.old / "chrome-win64").mkdir(parents=True)
    (m.old / "chrome-win64" / "chrome.exe").write_bytes(b"MZ the old build" * 500)
    (m.old / "chrome-win64" / "chrome.dll").write_bytes(b"the rest of it" * 500)
    (m.old / browser.INSTALLED_MARK).write_text("")
    m.opened = []
    _DownloadServer.refusing = False
    _DownloadServer.got = []
    m.server = _DownloadServer
    served = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _DownloadServer)
    threading.Thread(target=served.serve_forever, daemon=True).start()

    def launch(exe, name, profile_dir, port, url, explain_failure=True, mode=browser.AUTO):
        m.opened.append((Path(exe).parents[1].name, m.old.is_dir()))
        return name

    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.delenv(browser.KEEP_OLD_BUILDS, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(m.root))
    monkeypatch.setenv("PLAYWRIGHT_DOWNLOAD_HOST", "http://127.0.0.1:%d" % served.server_address[1])
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser, "can_ask", lambda: True)
    monkeypatch.setattr(browser, "_say_shared_port", lambda port: None)
    monkeypatch.setattr(browser, "_launch", launch)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    yield m
    served.shutdown()
    served.server_close()


def test_a_refused_download_costs_no_byte_of_the_old_build(real_install, tmp_path):
    before = _bytes_of(real_install.old)
    real_install.server.refusing = True
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert real_install.server.got, "the install never asked for the download"
    assert _bytes_of(real_install.old) == before
    assert real_install.opened == [("chromium-1000", True)]


def test_a_finished_download_clears_the_old_build_only_once_the_new_one_opened(
        real_install, tmp_path):
    wanted = browser._wanted_chromium_build()
    (real_install.root / browser.DECLINED_UPDATE).write_text("999\n", encoding="utf-8")
    assert _sign_in(tmp_path) == browser.CHROMIUM
    # Still there as the new build opened, and fetched only the once
    assert real_install.opened == [("chromium-%d" % wanted, True)]
    fetched = len(real_install.server.got)
    assert fetched
    deadline = time.time() + 90
    while real_install.old.exists() and time.time() < deadline:
        time.sleep(0.25)
    assert not real_install.old.exists()
    while (real_install.root / "__dirlock").exists() and time.time() < deadline:
        time.sleep(0.25)
    assert len(real_install.server.got) == fetched
    assert browser._bundled_chromium() == [str(real_install.root / ("chromium-%d" % wanted)
                                               / "chrome-win64" / "chrome.exe")]
    assert (real_install.root / browser.DECLINED_UPDATE).read_text(encoding="utf-8") == "999\n"
