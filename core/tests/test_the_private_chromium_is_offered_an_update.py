"""The sign-in offers to bring PaperPull's own Chromium up to date (#132).

After the first download nothing updated it. Sign-in starts the newest build
on disk, and an upgrade that brings a newer Playwright does not download that
Playwright's Chromium, so a copy taken months ago kept signing in with that
build while each release carried a newer one with its security fixes.

No browser is started and nothing is downloaded here. The builds on disk are
a list the test owns, the download is a stand-in that adds a newer one to it,
and the sign-in's own launch is replaced by one that notes which browser it
was given.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser  # noqa: E402

OLD, WANTED = 1228, 1248


def _build(n):
    return "/cache/ms-playwright/chromium-%d/chrome-linux64/chrome" % n


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """A computer with only Chromium build OLD, whose Playwright wants WANTED,
    and where nothing else is installed."""
    m = type("Machine", (), {})()
    m.builds = [_build(OLD)]
    m.root = tmp_path / "ms-playwright"
    m.opened = []
    m.downloads = []
    m.answers = []
    m.asked = []
    m.download_result = 0
    m.new_build = WANTED
    m.tty = True

    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: list(m.builds))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser, "_playwright_root", lambda: m.root)
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: WANTED)
    monkeypatch.setattr(browser, "browser_install_command",
                        lambda: ["/pkg/python3", "-m", "playwright", "install", "chromium"])
    monkeypatch.setattr(browser, "can_ask", lambda: m.tty)
    monkeypatch.setattr(browser, "debug_port_holder", lambda port, timeout=1.5: None)
    monkeypatch.setattr(browser, "_port_taken", lambda port: False)
    monkeypatch.setattr(browser, "_say_shared_port", lambda port: None)
    # On Linux the bundled copy goes first only where it sits in chrome-linux,
    # so the stand-in builds are named for it.
    monkeypatch.setattr(browser, "_real_first", lambda prefer_real, bundled: prefer_real)

    def download(cmd, **kw):
        m.downloads.append(list(cmd))
        if m.download_result == 0 and m.new_build:
            m.builds.insert(0, _build(m.new_build))
        return m.download_result

    def answer(prompt):
        m.asked.append(prompt)
        if not m.answers:
            raise AssertionError("asked a question nobody planned for: %r" % prompt)
        return m.answers.pop(0)

    def try_each(candidates, profile_dir, port, url, fallback=False, mode=browser.AUTO):
        m.opened.append(candidates[0])
        return candidates[0][0]

    monkeypatch.setattr(browser.subprocess, "call", download)
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(browser, "_try_each", try_each)
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
    assert browser.chromium_update_due(_build(OLD)) == (OLD, WANTED)
    assert browser.chromium_update_due(_build(WANTED)) is None
    assert browser.chromium_update_due(_build(WANTED + 5)) is None
    assert browser.chromium_update_due("/somewhere/else/chrome") is None


def test_with_no_wanted_build_nothing_is_due(machine, monkeypatch):
    monkeypatch.setattr(browser, "_wanted_chromium_build", lambda: None)
    assert browser.chromium_update_due(_build(OLD)) is None


# -- at sign-in, with someone to ask -----------------------------------------------

def test_agreeing_downloads_the_build_and_signs_in_with_it(machine, tmp_path, capsys):
    machine.answers = ["y"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.downloads == [["/pkg/python3", "-m", "playwright", "install", "chromium"]]
    assert machine.opened == [(browser.CHROMIUM, _build(WANTED))]
    said = capsys.readouterr().out
    assert "build %d" % OLD in said and "build %d" % WANTED in said
    assert "400 MB" in said and "stays about the same" in said
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


def test_saying_no_signs_in_with_the_old_build_and_is_not_asked_again(machine, tmp_path, capsys):
    machine.answers = ["n"]
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.downloads == []
    assert machine.opened == [(browser.CHROMIUM, _build(OLD))]
    assert (machine.root / browser.DECLINED_UPDATE).read_text().strip() == str(WANTED)
    assert "Nothing was downloaded" in capsys.readouterr().out

    # The next sign-in, in this app or another, asks nothing
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert len(machine.asked) == 1
    assert machine.opened[-1] == (browser.CHROMIUM, _build(OLD))


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
    machine.download_result = 1
    assert _sign_in(tmp_path) == browser.CHROMIUM
    assert machine.opened == [(browser.CHROMIUM, _build(OLD))]
    assert "did not finish" in capsys.readouterr().out
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


def test_a_download_that_leaves_no_newer_build_is_not_a_success(machine, tmp_path, capsys):
    machine.answers = ["y"]
    machine.new_build = None            # exits 0 and puts nothing on disk
    _sign_in(tmp_path)
    assert machine.opened == [(browser.CHROMIUM, _build(OLD))]
    assert "did not finish" in capsys.readouterr().out


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
    assert machine.opened == [(browser.CHROMIUM, _build(OLD))]
    said = capsys.readouterr().out
    assert "/pkg/python3 -m playwright install chromium" in said
    assert "sign in again" in said
    # Nobody said no, so the next sign-in says it again
    assert not (machine.root / browser.DECLINED_UPDATE).exists()


# -- where it is not offered ---------------------------------------------------------

def test_an_up_to_date_copy_is_not_offered_anything(machine, tmp_path, capsys):
    machine.builds = [_build(WANTED)]
    _sign_in(tmp_path)
    assert machine.asked == [] and machine.downloads == []
    assert "security fixes" not in capsys.readouterr().out


def test_nothing_is_offered_about_a_copy_that_would_not_be_started(machine, monkeypatch, tmp_path):
    """Their own Edge or Chrome goes first for an app that asks for it, so a
    stale private copy they do not use is none of their business."""
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "/x/edge")])
    _sign_in(tmp_path, prefer_real=True)
    assert machine.opened[0][0] == browser.EDGE
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
