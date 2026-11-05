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
import shutil
import socket
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
REAL_INSTALL_COMMAND = browser.browser_install_command
REAL_WANTED_BUILD = browser._wanted_chromium_build
INSTALL = ["/pkg/python3", "-m", "playwright", "install", "chromium"]
INNER = ("chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
         "Google Chrome for Testing")
SHELL = "chrome-headless-shell-mac-arm64/chrome-headless-shell"


def _lay(root, build, finished=True, inner=INNER, folder="chromium-%d"):
    """A build in root as an install leaves it, with Playwright's mark when
    it finished. Returns its executable."""
    exe = root / (folder % build) / inner
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"chromium %d" % build)
    if finished:
        (root / (folder % build) / browser.INSTALLED_MARK).write_text("")
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
    try:
        return browser.open_signin_browser(tmp_path / "profile", "9222", "https://x.test", **kw)
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C ended the sign-in")     # and not this whole test run


def _offer():
    try:
        return browser.offer_chromium_update(OLD, WANTED)
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C got out of the offer")


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


def test_two_playwrights_in_one_checkout_share_a_no(machine, monkeypatch, tmp_path):
    """Apps on 1.63 and 1.64.1 want different builds of one folder. A no for
    the newer one holds for the older, so alternating sign-ins stop asking."""
    machine.answers = ["n"]
    for want in (WANTED, WANTED - 5, WANTED, WANTED - 5):
        monkeypatch.setattr(browser, "_wanted_chromium_build", lambda want=want: want)
        _sign_in(tmp_path)
    assert len(machine.asked) == 1


def test_a_no_to_the_older_build_does_not_answer_for_the_newer(machine, monkeypatch, tmp_path):
    machine.answers = ["n", "n"]
    for want in (WANTED - 5, WANTED, WANTED - 5, WANTED):
        monkeypatch.setattr(browser, "_wanted_chromium_build", lambda want=want: want)
        _sign_in(tmp_path)
    assert len(machine.asked) == 2


@pytest.mark.parametrize("held", [b"\xff\xfe\x00bad", b"", b"not a build", b"1248.5"],
                         ids=["bad bytes", "empty", "words", "not a whole number"])
def test_an_answer_that_cannot_be_read_is_no_answer(machine, tmp_path, held):
    (machine.root / browser.DECLINED_UPDATE).write_bytes(held)
    assert browser._update_declined(WANTED) is False
    machine.answers = ["n"]
    _sign_in(tmp_path)
    assert len(machine.asked) == 1


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
    assert _offer() is False


# -- nothing in the offer can end a sign-in -----------------------------------------
#
# The sign-in needs none of this, and the shapes below are not likely, but
# each one got out of the sign-in and took it along.

def _a_driver_folder(tmp_path, browsers_json):
    package = tmp_path / "playwright"
    (package / "driver" / "package").mkdir(parents=True)
    (package / "driver" / "package" / "browsers.json").write_bytes(browsers_json)
    return package


@pytest.mark.parametrize("browsers_json", [
    b'{"browsers": [{"name": "chromium", "revision": 1e400}]}',
    b"[" * 200000,
], ids=["a revision too big for a number", "nested too deep"])
def test_a_browsers_json_that_raises_does_not_end_the_sign_in(
        machine, monkeypatch, tmp_path, browsers_json):
    """json reads 1e400 as infinity, which int() answers with OverflowError,
    and it answers nesting that deep with RecursionError."""
    monkeypatch.setattr(browser, "_wanted_chromium_build", REAL_WANTED_BUILD)
    package = _a_driver_folder(tmp_path, browsers_json)
    monkeypatch.setattr(browser, "_playwright_package", lambda: package)
    with pytest.raises((OverflowError, RecursionError)):
        browser._wanted_chromium_build()
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]


def _raises(error):
    def offer(*a, **k):
        raise error
    return offer


@pytest.mark.parametrize("error", [
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    OverflowError("cannot convert float infinity to integer"),
    RecursionError("maximum recursion depth exceeded"),
    OSError("the console went away"),
    KeyboardInterrupt()], ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("where", ["chromium_update_due", "offer_chromium_update"])
def test_nothing_the_offer_meets_ends_the_sign_in(machine, monkeypatch, tmp_path, error, where):
    monkeypatch.setattr(browser, where, _raises(error))
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []


def test_an_offer_that_raises_after_a_build_arrived_still_starts_it(machine, monkeypatch, tmp_path):
    """The folder is read again, or the sign-in would go on with what it read
    before the download, and the build that arrived would wait for the next."""
    def offer(have, want):
        _lay(machine.root, WANTED)
        raise OSError("the console went away")
    monkeypatch.setattr(browser, "offer_chromium_update", offer)
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.new, "profile")]
    assert machine.cleared == []


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


def test_a_new_build_set_aside_takes_its_headless_shell_with_it(machine, monkeypatch, tmp_path):
    """Or a headless launch, the receipt renderer's, would go on picking a
    shell of the build that would not open."""
    monkeypatch.setattr(browser, "_SAID_ON_DISK", set(), raising=False)
    old_shell = _lay(machine.root, OLD, inner=SHELL, folder="chromium_headless_shell-%d")
    new_shell = _lay(machine.root, WANTED, inner=SHELL, folder="chromium_headless_shell-%d")
    assert browser._headless_shells(machine.root) == [new_shell, old_shell]
    machine.answers = ["y"]
    machine.refused = {machine.new}
    _sign_in(tmp_path)
    assert browser._headless_shells(machine.root) == [old_shell]
    chromium = type("Chromium", (), {"executable_path": machine.new})()
    assert browser._on_disk(chromium, {"headless": True})["executable_path"] == old_shell
    assert browser._on_disk(chromium, {"headless": False})["executable_path"] == machine.old
    assert os.path.exists(new_shell), "only the mark goes, and a later install replaces the rest"


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


@pytest.mark.parametrize("tty", [True, False], ids=["from a terminal", "under the panel"])
def test_the_store_edition_is_told_it_cannot_and_goes_on_with_the_build_it_has(
        machine, monkeypatch, tmp_path, capsys, tty):
    """browser_install_command's own answer for a Python inside a Store
    package, which will not start from a person's Command Prompt. A yes could
    do nothing there, so nobody is asked, and nothing is printed to paste."""
    monkeypatch.setattr(browser, "browser_install_command", REAL_INSTALL_COMMAND)
    monkeypatch.setattr(sys, "executable", "C:\\Program Files\\WindowsApps\\"
                                           "PaperPull_0.61.0.0_x64__abcdefghijklm\\python\\python.exe")
    assert browser.browser_install_command() is None
    machine.tty = tty
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.asked == [] and machine.downloads == [] and machine.cleared == []
    said = capsys.readouterr().out
    assert "cannot download it for you" in said
    assert "Signing in goes on with the build that is here" in said
    assert "playwright install" not in said and "400 MB" not in said
    # Nobody said no, so nothing is remembered
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


@pytest.mark.parametrize("nobody", [EOFError(), KeyboardInterrupt()], ids=lambda e: type(e).__name__)
def test_a_question_nobody_answers_is_no_answer(machine, monkeypatch, tmp_path, nobody):
    """A console that reads end of file, which is what NUL gives where
    isatty says yes on Windows, or a Ctrl-C at the question. Nothing is
    downloaded, and nothing is remembered, since nobody said no."""
    def answer(prompt):
        raise nobody
    monkeypatch.setattr("builtins.input", answer)
    assert _offer() is None
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.downloads == []
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


def test_a_download_that_cannot_start_goes_on_with_the_old_build(machine, monkeypatch, tmp_path, capsys):
    def cannot(cmd, **kw):
        raise OSError("no such file")
    monkeypatch.setattr(browser.subprocess, "call", cannot)
    machine.answers = ["y", "y"]
    assert _offer() is False
    assert "Could not start the download (no such file)" in capsys.readouterr().out
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.cleared == []


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


def _on_linux(machine, monkeypatch, inner):
    """The machine with its old build laid out in a Linux folder, and the
    real _real_first, which is what the skip is there for."""
    shutil.rmtree(machine.root / ("chromium-%d" % OLD))
    monkeypatch.setattr(sys, "platform", "linux")
    machine.old = _lay(machine.root, OLD, inner=inner)


@pytest.mark.parametrize("real", [[(browser.CHROME, "/usr/bin/google-chrome")], []],
                         ids=["with a browser of their own", "with none"])
def test_a_build_in_chrome_linux_is_not_offered_an_update(machine, monkeypatch, tmp_path, real):
    """The bundled copy goes first on Linux only where a build sits in
    chrome-linux, and a new build never does. Saying yes would turn that and
    start their own browser on Chromium's profile."""
    _on_linux(machine, monkeypatch, "chrome-linux/chrome")
    machine.real = real
    assert browser.bundled_chromium_first()
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(machine.old, "profile")]
    assert machine.asked == [] and machine.downloads == []


def test_a_new_build_beside_chrome_linux_would_have_moved_them(machine, monkeypatch):
    """What the skip keeps from happening, read from the real order."""
    _on_linux(machine, monkeypatch, "chrome-linux/chrome")
    machine.real = [(browser.CHROME, "/usr/bin/google-chrome")]
    assert browser.browser_candidates()[0][0] == browser.CHROMIUM
    shutil.rmtree(machine.root / ("chromium-%d" % OLD))
    _lay(machine.root, WANTED, inner="chrome-linux64/chrome")
    assert browser.browser_candidates()[0][0] == browser.CHROME


def test_a_build_in_chrome_linux64_is_offered_it_with_no_browser_of_their_own(
        machine, monkeypatch, tmp_path):
    """Where the new build lands in the folder the old one has, nothing turns."""
    _on_linux(machine, monkeypatch, "chrome-linux64/chrome")
    machine.answers = ["n"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert len(machine.asked) == 1


# -- where it is not offered ---------------------------------------------------------

# Their own browser, in a folder whose name reads as an old build of
# Playwright's, so only the browser's own name keeps it from being offered.
OWN_CHROME = (browser.CHROME, "/opt/chromium-1200/chrome")


def test_an_up_to_date_copy_is_not_offered_anything(machine, tmp_path, capsys):
    _lay(machine.root, WANTED)
    _sign_in(tmp_path)
    assert machine.asked == [] and machine.downloads == []
    assert "security fixes" not in capsys.readouterr().out


def test_nothing_is_offered_about_a_copy_that_would_not_be_started(machine, monkeypatch, tmp_path):
    """Their own Edge or Chrome goes first for an app that asks for it, so a
    stale private copy they do not use is none of their business."""
    machine.real = [OWN_CHROME]
    _sign_in(tmp_path, prefer_real=True)
    assert machine.opened[0][0] == OWN_CHROME[1]
    assert machine.asked == [] and machine.downloads == []


def test_an_app_set_to_use_only_their_own_browser_is_not_asked(machine, tmp_path):
    machine.real = [OWN_CHROME]
    _sign_in(tmp_path, mode=browser.INSTALLED)
    assert machine.opened == [(OWN_CHROME[1], "profile")]
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


# -- a newest build that will not open, however it got there ---------------------------
#
# The panel's line can finish a build this computer cannot start with no
# sign-in there to see it. It is the newest from then on, and browser_candidates
# hands over only the newest, so the older build beside it, which the words
# promised stays, was never tried. A probe with a bogus finished 1248 beside a
# working 1228 got None at every sign-in, and with Edge installed went on to an
# empty profile.
#
# What a browser does here matters, so these launches are real, of a program
# that stands in for one. It notes the profile it was given, and answers on its
# debugging port as a browser does, or does not.

_PROGRAM = """
import http.server, json, os, sys, threading, time
args = sys.argv[1:]
port = int(next(a for a in args if a.startswith("--remote-debugging-port=")).split("=")[1])
profile = next(a for a in args if a.startswith("--user-data-dir=")).split("=", 1)[1]
with open({note!r}, "a", encoding="utf-8") as f:
    f.write("%d %s\\n" % (os.getpid(), profile))
threading.Timer(60, os._exit, [0]).start()
if not {answers!r}:
    time.sleep(60)
class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({{"Browser": "Chrome/0", "webSocketDebuggerUrl": "ws://127.0.0.1/x"}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
http.server.HTTPServer(("127.0.0.1", port), Answer).serve_forever()
"""
OWN_INNER = {"win32": "chrome-win64/chrome.exe", "darwin": INNER}.get(sys.platform, "chrome-linux64/chrome")


def _program(path, note, answers=True):
    """A real program at `path`. On Windows that has to be an executable, so
    it is the launcher pip makes its own commands with, with this script
    behind it, and no window of its own, as _launch starts a browser with no
    console."""
    script = _PROGRAM.format(note=str(note), answers=answers)
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        path.write_text("#!%s\n%s" % (sys.executable, script), encoding="utf-8")
        path.chmod(0o755)
        return
    distlib = pytest.importorskip("pip._vendor.distlib")
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as z:
        z.writestr("__main__.py", script)
    python = Path(sys.executable).with_name("pythonw.exe")
    path.write_bytes((Path(distlib.__file__).parent / "w64.exe").read_bytes()
                     + b'#!"%s"\r\n' % str(python).encode() + packed.getvalue())


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


@pytest.fixture
def real_launches(monkeypatch, tmp_path):
    """Builds that are real programs in a folder of the test's own, with no
    update due, so the sign-in goes straight to starting them."""
    m = type("RealLaunches", (), {})()
    m.root = tmp_path / "ms-playwright"
    m.profile = tmp_path / "profile"
    m.own_profile = str(m.profile.resolve())
    m.notes = {}
    m.real = []
    m.waits = []
    m.port = _free_port()

    def lay(build, answers=True, program=True):
        exe = m.root / ("chromium-%d" % build) / OWN_INNER
        m.notes[build] = tmp_path / ("started-%d.txt" % build)
        if program:
            _program(exe, m.notes[build], answers)
        else:
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"this is no program")
        (m.root / ("chromium-%d" % build) / browser.INSTALLED_MARK).write_text("")
        return str(exe)

    def started(key):
        note = m.notes[key]
        if not note.exists():
            return []
        return [line.split(" ", 1)[1] for line in note.read_text(encoding="utf-8").splitlines()]

    def sign_in(**kw):
        return browser.open_signin_browser(m.profile, m.port, "https://x.test", **kw)

    real_wait = browser.wait_for_debug_port

    def wait(port, timeout=20.0, alive=None):
        return real_wait(port, m.waits.pop(0) if m.waits else timeout, alive)

    m.lay, m.started, m.sign_in = lay, started, sign_in
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(m.root))
    monkeypatch.setattr(browser, "_real_browsers", lambda: list(m.real))
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: None)
    monkeypatch.setattr(browser, "_say_shared_port", lambda port: None)
    monkeypatch.setattr(browser, "wait_for_debug_port", wait)
    yield m
    for note in m.notes.values():
        if note.exists():
            for line in note.read_text(encoding="utf-8").splitlines():
                try:
                    os.kill(int(line.split(" ", 1)[0]), 9)
                except OSError:
                    pass


def _what_is_on_disk(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_a_newest_build_that_is_no_program_hands_the_sign_in_to_the_older_one(real_launches, capsys):
    r = real_launches
    r.lay(1248, program=False)
    r.lay(1228)
    before = _what_is_on_disk(r.root)
    assert r.sign_in() == browser.CHROMIUM
    assert r.started(1228) == [r.own_profile]
    said = capsys.readouterr().out
    assert "Chromium build 1248 did not open, so build 1228" in said
    assert "is being tried on the same profile" in said
    assert _what_is_on_disk(r.root) == before, "this path can tell nothing, so it changes nothing"


def test_a_newest_build_whose_port_never_answers_hands_it_on_too(real_launches, capsys):
    """A build that starts and answers nothing, which from here looks the
    same as a port another program spoiled. So its window is closed, the older
    build opens on the same profile, and the newest keeps its mark."""
    r = real_launches
    r.lay(1248, answers=False)
    r.lay(1228)
    r.waits = [4.0]
    before = _what_is_on_disk(r.root)
    assert r.sign_in() == browser.CHROMIUM
    assert r.started(1248) == [r.own_profile]
    assert r.started(1228) == [r.own_profile]
    said = capsys.readouterr().out
    assert "no debugging port answered" in said and "That window was closed" in said
    assert "Chromium build 1248 did not open, so build 1228" in said
    assert _what_is_on_disk(r.root) == before


def test_every_sign_in_finds_the_older_build_again(real_launches):
    """Nothing is remembered, so the newest goes first each time, as it must
    while the cause may have been the port."""
    r = real_launches
    r.lay(1248, program=False)
    r.lay(1228)
    assert r.sign_in() == browser.CHROMIUM
    r.port = _free_port()
    assert r.sign_in() == browser.CHROMIUM
    assert r.started(1228) == [r.own_profile, r.own_profile]


def test_the_older_build_goes_ahead_of_a_browser_of_their_own(real_launches, tmp_path):
    """Their sign-ins are on this profile, and Edge would open on an empty
    one."""
    r = real_launches
    r.lay(1248, program=False)
    r.lay(1228)
    r.notes["edge"] = tmp_path / "started-edge.txt"
    _program(tmp_path / "edge" / "msedge.exe", r.notes["edge"])
    r.real = [(browser.EDGE, str(tmp_path / "edge" / "msedge.exe"))]
    assert r.sign_in() == browser.CHROMIUM
    assert r.started(1228) == [r.own_profile]
    assert r.started("edge") == []


def test_only_one_older_build_is_tried(real_launches, tmp_path):
    """The next browser comes after that, on a profile of its own, as it
    always did. A third build is not started."""
    r = real_launches
    r.lay(1248, program=False)
    r.lay(1234, program=False)
    r.lay(1228)
    r.notes["edge"] = tmp_path / "started-edge.txt"
    _program(tmp_path / "edge" / "msedge.exe", r.notes["edge"])
    r.real = [(browser.EDGE, str(tmp_path / "edge" / "msedge.exe"))]
    assert r.sign_in() == browser.EDGE
    assert r.started(1228) == []
    assert r.started("edge") == [r.own_profile + "-microsoftedge"]


@pytest.mark.parametrize("program", [False, True], ids=["no program", "a port that never answers"])
def test_a_computer_with_one_build_goes_on_exactly_as_it_did(real_launches, capsys, program):
    r = real_launches
    r.lay(1228, answers=False, program=program)
    r.waits = [4.0]
    before = _what_is_on_disk(r.root)
    assert r.sign_in() is None
    said = capsys.readouterr().out
    assert "being tried" not in said and "did not open" not in said
    if program:
        assert "Try closing any other copy of the browser" in said
    assert _what_is_on_disk(r.root) == before


def test_a_copy_of_the_same_build_is_not_an_older_build(machine, tmp_path):
    """It would fail the same way, and the real older build would go untried."""
    _lay(machine.root, WANTED)
    shutil.copytree(machine.root / ("chromium-%d" % WANTED),
                    machine.root / ("chromium-%d - Copy" % WANTED))
    copy = machine.new.replace("chromium-%d" % WANTED, "chromium-%d - Copy" % WANTED)
    machine.refused = {machine.new, copy}
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert len(machine.opened) == 2
    assert machine.opened[0][0] in machine.refused
    assert machine.opened[1] == (machine.old, "profile")


def test_two_copies_of_one_build_are_one_build(machine, tmp_path):
    shutil.copytree(machine.root / ("chromium-%d" % OLD), machine.root / ("chromium-%d - Copy" % OLD))
    copy = machine.old.replace("chromium-%d" % OLD, "chromium-%d - Copy" % OLD)
    machine.refused = {machine.old, copy}
    machine.tty = False
    assert _sign_in(tmp_path) is None
    assert len(machine.opened) == 1


def test_a_browser_of_their_own_at_the_head_has_no_older_build(machine, tmp_path):
    """Only the private copy steps back. Their own browser goes on to the
    private copy as it always did, on that copy's own profile."""
    _lay(machine.root, WANTED)
    own = "/opt/chromium-1300/chrome"       # reads as a build newer than both
    machine.real = [(browser.CHROME, own)]
    machine.refused = {own, machine.new}
    assert _sign_in(tmp_path, prefer_real=True) is None
    assert machine.opened == [(own, "profile"), (machine.new, "profile-chromium")]


def test_a_folder_with_no_build_number_is_not_an_older_build(machine, tmp_path):
    """Nobody can say what it is, so it is not started on their profile."""
    shutil.copytree(machine.root / ("chromium-%d" % OLD), machine.root / "chromium-backup")
    machine.refused = {machine.old}
    machine.tty = False
    assert _sign_in(tmp_path) is None
    assert machine.opened == [(machine.old, "profile")]


def test_a_step_back_after_an_update_is_the_one_step_back(machine, tmp_path):
    """With the new build set aside the build they had is the one older
    build, so nothing older than that is started as well."""
    _lay(machine.root, OLD - 28)
    machine.answers = ["y"]
    machine.refused = {machine.new, machine.old}
    assert _sign_in(tmp_path) is None
    assert machine.opened == [(machine.new, "profile"), (machine.old, "profile")]


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
    deadline = time.time() + 180
    while real_install.old.exists() and time.time() < deadline:
        time.sleep(0.25)
    assert not real_install.old.exists()
    while (real_install.root / "__dirlock").exists() and time.time() < deadline:
        time.sleep(0.25)
    assert len(real_install.server.got) == fetched
    assert browser._bundled_chromium() == [str(real_install.root / ("chromium-%d" % wanted)
                                               / "chrome-win64" / "chrome.exe")]
    assert (real_install.root / browser.DECLINED_UPDATE).read_text(encoding="utf-8") == "999\n"
