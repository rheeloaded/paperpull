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
    # The intent is unchanged, that it returns rather than raising and explains
    # itself. The wording moved when the download became something offered at
    # sign-in rather than done during setup.
    out = capsys.readouterr().out
    assert "No browser this tool can drive" in out
    assert "Chrome, Edge" in out


def test_setup_hint_matches_the_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert browser.setup_hint() == "setup.bat"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert browser.setup_hint() == "./setup.command"   # the file that exists


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
    # no real browser starts here, so stand in for the port coming up
    monkeypatch.setattr(browser, "wait_for_debug_port", lambda port, timeout=20.0: True)
    profile = tmp_path / "profile"
    assert browser.open_signin_browser(profile, "9231", "https://example.test") == "Chromium"
    assert profile.is_dir()          # created for the user
    assert f"--user-data-dir={profile}" in seen["args"]
    assert "--remote-debugging-port=9231" in seen["args"]
    assert seen["args"][-1] == "https://example.test"


def test_newest_chromium_build_wins(monkeypatch, tmp_path):
    """Playwright leaves old builds behind; picking one older than the
    installed playwright expects causes confusing launch failures."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    for build in ("chromium-999", "chromium-1000", "chromium-1228"):
        exe = tmp_path / build / "chrome-mac/Chromium.app/Contents/MacOS/Chromium"
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
    found = browser._bundled_chromium()
    assert "chromium-1228" in found[0], found
    # a plain text sort would have put chromium-1000 ahead of chromium-999
    assert [b for b in ("chromium-1228", "chromium-1000", "chromium-999")] == \
        [next(b for b in ("chromium-1228", "chromium-1000", "chromium-999") if b in p)
         for p in found]


# -- the macOS bundle rename ----------------------------------------------
#
# Playwright used to ship "Chromium.app/Contents/MacOS/Chromium" and now ships
# "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing".
# Only the old name was matched, so on an up-to-date install _bundled_chromium()
# found NOTHING and every app quietly launched Edge instead - or refused to open
# a browser at all where Edge and Chrome were absent. The tests missed it
# because they only ever built the old layout.

_NEW_MAC_BUNDLE = ("chrome-mac-arm64/Google Chrome for Testing.app"
                   "/Contents/MacOS/Google Chrome for Testing")


def test_mac_chromium_is_found_under_the_new_bundle_name(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = tmp_path / f"chromium-1234/{_NEW_MAC_BUNDLE}"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert browser._bundled_chromium() == [str(exe)]


def test_new_bundle_name_also_found_on_intel_macs(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = tmp_path / ("chromium-1234/chrome-mac/Google Chrome for Testing.app"
                      "/Contents/MacOS/Google Chrome for Testing")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert browser._bundled_chromium() == [str(exe)]


def test_bundled_chromium_wins_when_prefer_real_is_off(monkeypatch, tmp_path):
    """The regression that mattered: with an Edge installed and a CURRENT
    Playwright, an app that asked for Chromium was handed Edge."""
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = tmp_path / f"chromium-1234/{_NEW_MAC_BUNDLE}"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    edge = tmp_path / "Microsoft Edge"
    edge.write_text("")
    monkeypatch.setattr(browser, "_real_browsers",
                        lambda: [(browser.EDGE, str(edge))])
    assert browser.find_browser(prefer_real=False)[0] == browser.CHROMIUM
    assert browser.find_browser(prefer_real=True)[0] == browser.EDGE


def test_a_window_that_opens_without_a_debugging_port_is_reported(monkeypatch, tmp_path, capsys):
    """Launching is not the same as listening. When Edge or Chrome is already
    running, a new launch can hand the address to the existing session and drop
    the flags, so a window opens, the user signs in, and only the NEXT command
    reveals that no port was ever opened. By then the sign-in was spent on a
    browser the tool cannot see."""
    monkeypatch.setattr(browser, "find_browser", lambda prefer_real=False: (browser.EDGE, "/x/edge"))
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kw: None)
    monkeypatch.setattr(browser, "wait_for_debug_port", lambda port, timeout=20.0: False)
    assert browser.open_signin_browser(tmp_path / "p", "9231", "https://example.test") is None
    said = capsys.readouterr().out.lower()
    assert "no debugging port" in said
    assert "already running" in said and "close every" in said


def test_the_port_check_uses_ipv4_not_localhost():
    """The browser binds 127.0.0.1 only, while "localhost" can resolve to ::1
    first and be refused, which is how this failure first presented."""
    import inspect
    src = inspect.getsource(browser.wait_for_debug_port)
    assert "127.0.0.1" in src and "localhost" not in src.split('"""')[2]


def test_the_port_check_survives_a_nonsense_port():
    assert browser.wait_for_debug_port("not-a-port", timeout=0.5) is False


# -- the profile the browser opens must be the one Python created -----------

def test_a_relative_profile_dir_reaches_the_browser_as_an_absolute_path(tmp_path, monkeypatch):
    """Configs carry this as "./x-browser-profile". A relative --user-data-dir
    is resolved by the BROWSER, from wherever the browser thinks it is, not
    from where Python just created the folder. That split made two profiles out
    of one setting and left four of them holding live signed-in session cookies
    inside the shared Playwright browser cache."""
    

    seen = {}

    class FakePopen:
        def __init__(self, argv, *a, **kw):
            seen["argv"] = argv

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(browser.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(browser, "find_browser", lambda prefer_real=False: ("Chromium", "chrome"))
    monkeypatch.setattr(browser, "wait_for_debug_port", lambda port, timeout=20.0: True)

    browser.open_signin_browser("./demo-browser-profile", "9222", "https://example.test")

    flag = [a for a in seen["argv"] if a.startswith("--user-data-dir=")][0]
    got = Path(flag.split("=", 1)[1])
    assert got.is_absolute(), "the browser was handed a relative profile path: %s" % got
    assert got == (tmp_path / "demo-browser-profile").resolve()
    assert got.is_dir(), "the folder Python created is not the one the browser was given"


# -- the 400 MB download is a last resort, not part of setup ----------------

def test_an_installed_browser_is_preferred_so_nothing_is_downloaded(monkeypatch):
    """The bundled Chromium is 416 MB on disk against roughly 60 MB for
    everything else. Almost nobody needs it, because any Chromium-based
    browser can be driven the same way and Windows always has Edge."""
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
    names = [n for n, _ in browser.browser_candidates(prefer_real=True)]
    assert names[0] == browser.EDGE


def test_installed_mode_never_reaches_for_the_bundled_copy(monkeypatch):
    """Somebody on a managed machine may not want this near their own browser,
    and somebody else may not want a 400 MB download. Both are honoured."""
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
    assert browser.browser_candidates(mode=browser.INSTALLED) == [(browser.EDGE, "edge")]
    assert browser.browser_candidates(mode=browser.BUNDLED) == [(browser.CHROMIUM, "bundled")]


def test_a_browser_that_will_not_open_a_port_is_passed_over(monkeypatch, tmp_path):
    """Installed is not the same as usable. Edge can be present and still
    refuse a debugging port, and only launching it can tell the difference, so
    the next candidate is tried rather than giving up."""
    tried = []

    def fake_launch(exe, name, profile_dir, port, url, explain_failure=True):
        tried.append(name)
        return name if name == browser.CHROMIUM else None

    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
    monkeypatch.setattr(browser, "_launch", fake_launch)

    got = browser.open_signin_browser(tmp_path / "p", "9222", "https://x.test",
                                      prefer_real=True)
    assert tried == [browser.EDGE, browser.CHROMIUM]
    assert got == browser.CHROMIUM


def test_the_download_is_only_offered_when_there_is_nothing_at_all(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: [])
    monkeypatch.setattr(browser, "fetch_bundled_chromium",
                        lambda *a, **k: asked.append(1) or True)
    monkeypatch.setattr(browser, "_launch",
                        lambda *a, **k: browser.EDGE)
    browser.open_signin_browser(tmp_path / "p", "9222", "https://x.test")
    assert asked == [], "a download was offered while a usable browser existed"


def test_nothing_is_downloaded_behind_a_closed_stdin(monkeypatch, capsys):
    """The control panel runs apps with stdin closed so a stray prompt cannot
    hang a run. A question nobody can answer must not start a 400 MB download
    or block waiting for a reply."""
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: [])
    monkeypatch.setattr(browser, "can_ask", lambda: False)
    called = []
    monkeypatch.setattr(browser.subprocess, "call", lambda *a, **k: called.append(1) or 0)
    assert browser.fetch_bundled_chromium() is False
    assert called == []
    assert "install Chrome or Edge" in capsys.readouterr().out


def test_the_wording_says_their_own_profile_is_not_used():
    """Someone is about to look at a browser they recognise which knows none of
    their accounts. Both halves have to be said, that their real profile is
    untouched AND that they are therefore not signed in."""
    note = browser.profile_note("Microsoft Edge")
    # Whitespace-normalised, because the note is hard-wrapped for a console and
    # a phrase can straddle a line break.
    flat = " ".join(note.split()).lower()
    assert "separate profile" in flat
    assert "untouched" in flat
    assert "not signed in" in flat
    assert "microsoft edge" in flat


# -- bugs found in review, before 1.0 ---------------------------------------

def test_other_chromium_browsers_are_recognised(monkeypatch):
    """The message offered to drive "Chrome, Edge, Brave or any other
    Chromium-based browser" while the detector only ever looked for Chrome and
    Edge. Somebody running Brave was pushed into a 400 MB download of a browser
    they effectively already had."""
    import inspect
    src = inspect.getsource(browser._real_browsers)
    for family in ("brave", "vivaldi", "opera"):
        assert family in src.lower(), family


def test_the_same_install_is_never_offered_twice(monkeypatch, tmp_path):
    """Several candidate paths can point at one install. Trying it again opens
    a second window to fail in exactly the same way.

    Forced by pointing both Program Files variables at one folder, which makes
    two of Edge's candidate paths identical. An earlier version of this test
    asserted against an empty list and so proved nothing.
    """
    monkeypatch.setattr(browser.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")

    found = browser._real_browsers()
    assert found, "the fixture browser was not detected at all"
    assert len(found) == 1, "the same install was offered %d times: %s" % (
        len(found), found)


def test_a_fallback_browser_gets_its_own_profile_folder(monkeypatch, tmp_path):
    """Two browser brands sharing one profile folder can leave it locked or
    damaged, and a profile written by one is not guaranteed to open in another.
    The first candidate keeps the configured folder so existing installs stay
    signed in."""
    seen = []
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
    monkeypatch.setattr(browser, "_launch",
                        lambda exe, name, prof, port, url, explain_failure=True:
                        seen.append((name, str(prof))) or None)
    browser.open_signin_browser(tmp_path / "app-browser-profile", "9222",
                                "https://x.test", prefer_real=True)
    assert len({p for _, p in seen}) == len(seen), seen
    assert seen[0][1] == str(tmp_path / "app-browser-profile"), \
        "the first candidate must keep the configured folder"


def test_the_download_is_offered_when_a_browser_exists_but_never_answers(monkeypatch, tmp_path):
    """Installed is not the same as usable. A browser that refuses a debugging
    port every time left the run with no way forward, even though downloading
    one would have fixed it."""
    offered = []
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: [])
    monkeypatch.setattr(browser, "_launch", lambda *a, **k: None)
    monkeypatch.setattr(browser, "fetch_bundled_chromium",
                        lambda *a, **k: offered.append(1) or False)
    browser.open_signin_browser(tmp_path / "p", "9222", "https://x.test")
    assert offered == [1]


def test_a_packaged_build_does_not_try_to_run_itself(monkeypatch):
    """sys.executable is the application in a frozen build, so
    "sys.executable -m playwright install" would re-launch the app instead of
    installing anything. This is the one that would have broken the installer."""
    monkeypatch.setattr(browser.sys, "frozen", True, raising=False)
    cmd = browser.browser_install_command()
    if cmd is not None:
        assert "-m" not in cmd
        assert cmd[0] != browser.sys.executable
        assert any("cli.js" in str(c) for c in cmd)


def test_a_normal_build_uses_the_documented_command(monkeypatch):
    monkeypatch.delattr(browser.sys, "frozen", raising=False)
    assert browser.browser_install_command()[1:] == \
        ["-m", "playwright", "install", "chromium"]
