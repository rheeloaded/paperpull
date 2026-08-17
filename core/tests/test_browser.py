"""Browser discovery across platforms.

The paths are faked so the same assertions run on any OS — this checks the
lookup logic and the ordering, which is what actually differs between
Windows, macOS and Linux.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser


def test_playwright_root_per_platform(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert browser._playwright_root() == Path.home() / "Library/Caches/ms-playwright"
    monkeypatch.setattr(sys, "platform", "linux")
    assert browser._playwright_root() == Path.home() / ".cache/ms-playwright"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))
    assert browser._playwright_root().name == "ms-playwright"


def test_playwright_browsers_path_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert browser._playwright_root() == tmp_path


def test_mac_chromium_is_found_inside_the_app_bundle(monkeypatch, tmp_path):
    """macOS ships Chromium inside a .app, not as a bare executable."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = tmp_path / "chromium-1234/chrome-mac/Chromium.app/Contents/MacOS/Chromium"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    assert browser._bundled_chromium() == [str(exe)]
    name, path = browser.find_browser()
    assert (name, path) == (browser.CHROMIUM, str(exe))


def test_mac_arm_build_is_found_too(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = tmp_path / "chromium-1234/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    assert browser._bundled_chromium() == [str(exe)]


def test_prefer_real_picks_edge_over_bundled_chromium(monkeypatch, tmp_path):
    """Walmart and Verizon need a branded browser to get past bot protection."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    chromium = tmp_path / "chromium-1/chrome-mac/Chromium.app/Contents/MacOS/Chromium"
    chromium.parent.mkdir(parents=True)
    chromium.write_text("x")
    edge = tmp_path / "Edge"
    edge.write_text("x")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, str(edge))])

    assert browser.find_browser(prefer_real=True) == (browser.EDGE, str(edge))
    assert browser.find_browser(prefer_real=False) == (browser.CHROMIUM, str(chromium))


def test_falls_back_to_a_real_browser_when_chromium_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.CHROME, "/x/chrome")])
    assert browser.find_browser() == (browser.CHROME, "/x/chrome")


def test_reports_nothing_when_no_browser_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    assert browser.find_browser() == (None, None)


def test_open_signin_browser_reports_failure_instead_of_raising(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    assert browser.open_signin_browser(tmp_path / "profile", "9222", "https://x") is None
    assert "Could not find" in capsys.readouterr().out


def test_setup_hint_matches_the_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert browser.setup_hint() == "setup.bat"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert browser.setup_hint() == "./setup.sh"


@pytest.mark.parametrize("url,expected", [
    ("http://localhost:9231", "9231"),
    ("http://127.0.0.1:9243/", "9243"),
    ("", "9222"),
    (None, "9222"),
])
def test_port_is_read_from_the_cdp_url(url, expected):
    assert browser.port_from_cdp_url(url) == expected


def test_launch_passes_the_profile_and_port(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(browser, "find_browser", lambda prefer_real=False: ("Chromium", "/x/c"))
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kw: seen.update(args=args))
    profile = tmp_path / "profile"
    assert browser.open_signin_browser(profile, "9231", "https://example.test") == "Chromium"
    assert profile.is_dir()          # created for the user
    assert f"--user-data-dir={profile}" in seen["args"]
    assert "--remote-debugging-port=9231" in seen["args"]
    assert seen["args"][-1] == "https://example.test"
