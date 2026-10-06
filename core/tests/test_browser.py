"""Browser discovery across platforms.

The paths are faked so the same assertions run on any OS, this checks the
lookup logic and the ordering, which is what actually differs between
Windows, macOS and Linux.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser


# -- where Playwright keeps its browsers ---------------------------------------
#
# By Playwright's own rules, unchanged since 1.9 (registryDirectory and
# computeDefaultCacheDirectory in its driver). Every row that Windows can
# show is what Playwright 1.63's own install --dry-run printed there on
# 2026-10-05, and the Linux rows follow its driver, checked against this
# module in WSL. Until then XDG_CACHE_HOME went unread and
# PLAYWRIGHT_BROWSERS_PATH=0 and =1 counted as no setting, so on such a
# machine the Chromium Playwright had downloaded was never found.

SETTINGS = ("PLAYWRIGHT_BROWSERS_PATH", "npm_config_playwright_browsers_path",
            "npm_package_config_playwright_browsers_path", "INIT_CWD", "npm_config_init_cwd",
            "npm_package_config_init_cwd", "XDG_CACHE_HOME", "LOCALAPPDATA")


@pytest.fixture
def nothing_set(monkeypatch, tmp_path):
    """None of the settings Playwright reads, a home folder of the test's
    own and a folder of its own to run in, so no folder found is one of the
    machine's. Hands back the home folder."""
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(tmp_path)
    return home


@pytest.mark.parametrize("platform, settings, expected", [
    ("linux", {}, "{home}/.cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": "{tmp}/cache"}, "{tmp}/cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": ""}, "{home}/.cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": "cache"}, "{tmp}/cache/ms-playwright"),
    ("darwin", {"XDG_CACHE_HOME": "{tmp}/cache"}, "{home}/Library/Caches/ms-playwright"),
    ("win32", {"LOCALAPPDATA": "{tmp}/local", "XDG_CACHE_HOME": "{tmp}/cache"}, "{tmp}/local/ms-playwright"),
    ("win32", {}, "{home}/AppData/Local/ms-playwright"),
    ("win32", {"LOCALAPPDATA": ""}, "{home}/AppData/Local/ms-playwright"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "{tmp}/own"}, "{tmp}/own"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "1"}, "{tmp}/1"),
    ("win32", {"PLAYWRIGHT_BROWSERS_PATH": "1", "LOCALAPPDATA": "{tmp}/local"}, "{tmp}/1"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "rel/browsers"}, "{tmp}/rel/browsers"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "rel", "INIT_CWD": "{tmp}/project"}, "{tmp}/project/rel"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "1", "npm_config_init_cwd": "{tmp}/project"}, "{tmp}/project/1"),
    ("linux", {"npm_config_playwright_browsers_path": "{tmp}/npm"}, "{tmp}/npm"),
    ("linux", {"npm_package_config_playwright_browsers_path": "{tmp}/package"}, "{tmp}/package"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "", "npm_config_playwright_browsers_path": "{tmp}/npm"},
     "{home}/.cache/ms-playwright"),
], ids=["linux", "linux under XDG_CACHE_HOME", "linux with XDG_CACHE_HOME empty",
        "linux with XDG_CACHE_HOME relative", "macos never reads XDG_CACHE_HOME",
        "windows never reads XDG_CACHE_HOME", "windows without LOCALAPPDATA",
        "windows with LOCALAPPDATA empty", "a folder", "1 is a folder", "1 is a folder on windows",
        "a relative folder", "a relative folder from INIT_CWD", "a relative folder from npm's INIT_CWD",
        "npm's name for it", "npm's package name for it", "set to nothing is set"])
def test_the_browsers_folder_is_the_one_playwright_uses(platform, settings, expected, nothing_set,
                                                       tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    for name, value in settings.items():
        monkeypatch.setenv(name, value.format(tmp=tmp_path, home=nothing_set))
    assert browser._playwright_root() == Path(expected.format(tmp=tmp_path, home=nothing_set))


def test_linux_finds_the_chromium_kept_under_xdg_cache_home(nothing_set, tmp_path, monkeypatch):
    """XDG_CACHE_HOME moves the whole cache, and what Playwright downloads
    moves with it. The build is laid out as Playwright 1.62 lays out its
    own on an ARM machine, in chrome-linux, a folder name looked for here."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    exe = tmp_path / "cache" / "ms-playwright" / "chromium-1234" / "chrome-linux" / "chrome"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert browser._bundled_chromium() == [str(exe)]


def _a_playwright_package(tmp_path, monkeypatch) -> Path:
    """A Playwright package of the test's own, a folder with an empty
    __init__.py, and the one this Python would import."""
    site = tmp_path / "site"
    (site / "playwright").mkdir(parents=True)
    (site / "playwright" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.delitem(sys.modules, "playwright", raising=False)
    monkeypatch.syspath_prepend(str(site))
    return site / "playwright"


def test_0_is_the_folder_inside_playwrights_own_package(nothing_set, tmp_path, monkeypatch):
    """Playwright's driver keeps them beside its package.json, at
    driver/package in its Python package, and a Chromium there is found,
    here laid out as Playwright 1.63 lays out its own on Windows."""
    package = _a_playwright_package(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    own = package / "driver" / "package" / ".local-browsers"
    exe = own / "chromium-1243" / "chrome-win64" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert browser._playwright_root() == own
    assert browser._bundled_chromium() == [str(exe)]


def test_0_without_playwright_names_no_folder(nothing_set, monkeypatch):
    """There is no package to keep them in, so there is nothing to find,
    and the usual folder is not looked in instead."""
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    assert browser._playwright_root() is None
    assert browser._bundled_chromium() == []


def test_playwright_browsers_path_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert browser._playwright_root() == tmp_path


def test_mac_chromium_is_found_inside_the_app_bundle(monkeypatch, tmp_path):
    """macOS ships Chromium inside a .app, not as a bare executable."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    # find_browser looks for the browsers installed as well, and with nothing
    # standing in for them it looked in the Applications folders of whichever
    # machine ran this.
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
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
    # The launcher asks browser_candidates, not find_browser, so the stand-in
    # has to go there. Patching find_browser alone left the test reading the
    # browsers installed on whoever's machine ran it, and it failed on a
    # machine with none (a contributor hit this, #25).
    monkeypatch.setattr(browser, "browser_candidates",
                        lambda prefer_real=False, mode=browser.AUTO: [("Chromium", "/x/c")])
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


# -- every folder Playwright has unpacked its Chromium into -----------------
#
# Playwright's registry (EXECUTABLE_PATHS in playwright-core) names the
# folder inside chromium-<build> for each platform. Up to 1.56 it built
# Chromium itself, in chrome-linux, chrome-mac and chrome-win. From 1.57 it
# unpacks Chrome for Testing, in chrome-linux64, chrome-mac-x64,
# chrome-mac-arm64 and chrome-win64, while Linux on ARM kept Playwright's
# own build in chrome-linux until 1.63 moved it to chrome-linux-arm64. Only
# chrome-linux was looked for on Linux, so no bundled Chromium was found on
# x64 from 1.57 or on ARM from 1.63, and there the browser tests that attach
# to one skipped themselves.

_CFT_APP = "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"

# (platform, the Playwright releases, a build of theirs, where Chromium is
# inside chromium-<build>, where the headless shell installed beside it is
# inside chromium_headless_shell-<build>). The headless shell has no window
# to sign in to, so it must never be offered.
PLAYWRIGHT_LAYOUTS = [
    ("linux", "up to 1.56, and ARM up to 1.62", "1194",
     "chrome-linux/chrome", "chrome-linux/headless_shell"),
    ("linux", "1.57 on, x64", "1243",
     "chrome-linux64/chrome", "chrome-headless-shell-linux64/chrome-headless-shell"),
    ("linux", "1.63 on, ARM", "1243",
     "chrome-linux-arm64/chrome", "chrome-headless-shell-linux-arm64/chrome-headless-shell"),
    ("darwin", "up to 1.56", "1194",
     "chrome-mac/Chromium.app/Contents/MacOS/Chromium", "chrome-mac/headless_shell"),
    ("darwin", "1.57 on, Intel", "1243",
     "chrome-mac-x64/" + _CFT_APP, "chrome-headless-shell-mac-x64/chrome-headless-shell"),
    ("darwin", "1.57 on, Apple silicon", "1243",
     "chrome-mac-arm64/" + _CFT_APP, "chrome-headless-shell-mac-arm64/chrome-headless-shell"),
    ("win32", "up to 1.56", "1194",
     "chrome-win/chrome.exe", "chrome-win/headless_shell.exe"),
    ("win32", "1.57 on", "1243",
     "chrome-win64/chrome.exe", "chrome-headless-shell-win64/chrome-headless-shell.exe"),
]


def _layout_id(layout):
    return "%s %s" % (layout[0], layout[1].replace(",", ""))


# Files a real install keeps beside the executable, named so that a pattern
# ending in a wildcard would take them too (the Windows ones as
# chromium-1243/chrome-win64 holds them here). The macOS folder holds only
# the executable.
_BESIDE = {
    "chrome": ("chrome-wrapper", "chrome_crashpad_handler", "chrome_sandbox",
               "chrome_100_percent.pak"),
    "chrome.exe": ("chrome.dll", "chrome_proxy.exe", "chrome_pwa_launcher.exe",
                   "chrome_100_percent.pak"),
}


def _install(root, build, chromium, shell):
    """What "playwright install chromium" leaves for one build, Chromium with
    the files beside it and the headless shell, each marked complete, and
    the Chrome Canary for Testing that Playwright installs only on request,
    in Chromium's layout. Only Chromium may be offered. Returns it."""
    for folder, inner in (("chromium-" + build, chromium),
                          ("chromium_headless_shell-" + build, shell),
                          ("chromium_tip_of_tree-1433", chromium)):
        exe = root / folder / inner
        exe.parent.mkdir(parents=True, exist_ok=True)
        for name in (exe.name, *_BESIDE.get(exe.name, ())):
            (exe.parent / name).write_text("")
        (root / folder / "INSTALLATION_COMPLETE").write_text("")
    return root / ("chromium-" + build) / chromium


@pytest.mark.parametrize("platform,releases,build,chromium,shell", PLAYWRIGHT_LAYOUTS,
                         ids=[_layout_id(layout) for layout in PLAYWRIGHT_LAYOUTS])
def test_every_folder_playwright_unpacks_chromium_into_is_found(
        monkeypatch, tmp_path, platform, releases, build, chromium, shell):
    monkeypatch.setattr(browser.sys, "platform", platform)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.CHROME, "/x/chrome")])
    exe = str(_install(tmp_path, build, chromium, shell))
    assert browser._bundled_chromium() == [exe]
    assert browser.bundled_chromium_present()
    assert browser.browser_candidates(mode=browser.BUNDLED) == [(browser.CHROMIUM, exe)]
    # AUTO offers it beside their own browser, ahead or behind
    # (test_auto_keeps_the_order_each_machine_had).
    bundled, real = (browser.CHROMIUM, exe), (browser.CHROME, "/x/chrome")
    assert sorted(browser.browser_candidates(mode=browser.AUTO)) == sorted([bundled, real])


# (platform, the builds on disk as (build, where Chromium is inside
# chromium-<build>), whether AUTO puts the bundled copy ahead of a browser of
# their own). A build in chrome-linux was found and went first, and builds
# only in chrome-linux64 or chrome-linux-arm64 were never found, so the
# person has been signing in through their own browser. Finding those
# folders moves nobody.
_ORDERS = [
    ("win32", [("1243", "chrome-win64/chrome.exe")], True),
    ("darwin", [("1243", "chrome-mac-arm64/" + _CFT_APP)], True),
    ("linux", [("1243", "chrome-linux64/chrome")], False),
    ("linux", [("1243", "chrome-linux-arm64/chrome")], False),
    ("linux", [("1234", "chrome-linux/chrome")], True),
    ("linux", [("1234", "chrome-linux/chrome"), ("1243", "chrome-linux-arm64/chrome")], True),
    ("linux", [("1194", "chrome-linux/chrome"), ("1243", "chrome-linux64/chrome")], True),
]


@pytest.mark.parametrize("platform,builds,bundled_first", _ORDERS,
                         ids=["%s %s" % (p, " and ".join(inner.split("/")[0] for _b, inner in b))
                              for p, b, _f in _ORDERS])
def test_auto_keeps_the_order_each_machine_had(monkeypatch, tmp_path, platform, builds,
                                               bundled_first):
    """Moving someone to another browser costs them a sign-in, and on
    Ubuntu 23.10 and later the Chrome for Testing that Playwright downloads
    could not even start with its sandbox. So on Linux the bundled copy goes
    first only where it already did. The newest build is offered either way,
    an app that asks for a real browser gets theirs first, and with no
    browser of their own the bundled copy is used."""
    monkeypatch.setattr(browser.sys, "platform", platform)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    for build, inner in builds:
        exe = tmp_path / ("chromium-" + build) / inner
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    newest_build, newest_inner = max(builds, key=lambda b: int(b[0]))
    bundled = (browser.CHROMIUM, str(tmp_path / ("chromium-" + newest_build) / newest_inner))
    real = (browser.CHROME, "/x/chrome")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [real])
    expected = [bundled, real] if bundled_first else [real, bundled]
    assert browser.browser_candidates() == expected
    assert browser.find_browser() == expected[0]
    assert browser.bundled_chromium_first() is bundled_first
    assert browser.browser_candidates(prefer_real=True) == [real, bundled]
    assert browser.find_browser(prefer_real=True) == real
    assert browser.browser_candidates(mode=browser.BUNDLED) == [bundled]
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    assert browser.browser_candidates() == [bundled]
    assert browser.find_browser() == bundled
    assert browser.find_browser(prefer_real=True) == bundled


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_with_no_bundled_copy_none_goes_first(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(browser.sys, "platform", platform)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert browser.bundled_chromium_first() is False


_UPGRADES = [(old, new) for old in PLAYWRIGHT_LAYOUTS for new in PLAYWRIGHT_LAYOUTS
             if old[0] == new[0] and int(old[2]) < int(new[2])]


@pytest.mark.parametrize("old,new", _UPGRADES,
                         ids=["%s to %s" % (_layout_id(o), n[1].replace(",", ""))
                              for o, n in _UPGRADES])
def test_the_newer_build_comes_first_when_its_folder_was_renamed(monkeypatch, tmp_path, old, new):
    """An older build stays on disk while another installation still uses
    it, as an app venv on an older Playwright does here, and it is older
    than the Playwright now installed expects. Linux used to find only the
    older one."""
    monkeypatch.setattr(browser.sys, "platform", new[0])
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    older = str(_install(tmp_path, *old[2:]))
    newer = str(_install(tmp_path, *new[2:]))
    assert browser._bundled_chromium() == [newer, older]
    assert browser.browser_candidates(mode=browser.BUNDLED) == [(browser.CHROMIUM, newer)]


# Playwright's names for the platforms, and the sys.platform of each
_PLAYWRIGHT_PLATFORMS = (("linux", "linux"), ("mac", "darwin"), ("win", "win32"))


def _installed_chromium_folders():
    """Where the installed Playwright unpacks Chromium on each platform it
    names, read from its own EXECUTABLE_PATHS, for example "linux-x64" and
    "chrome-linux64/chrome". Returns (its version, that table)."""
    playwright = pytest.importorskip("playwright")
    from importlib.metadata import version
    lib = Path(playwright.__file__).parent / "driver" / "package" / "lib"
    start = re.compile(r"EXECUTABLE_PATHS\s*=\s*\{")
    for js in sorted(lib.rglob("*.js")):
        text = js.read_text(encoding="utf-8", errors="replace")
        at = start.search(text)
        if not at:
            continue
        # Its comments go first, since a brace in one would end the table early
        region = re.sub(r"/\*.*?\*/|//[^\n]*", "", text[at.end():at.end() + 20000], flags=re.S)
        table = re.search(r"[\"']chromium[\"']\s*:\s*\{([^}]*)\}", region)
        if table:
            entries = re.findall(r"[\"']([\w.-]+)[\"']\s*:\s*\[([^\]]*)\]", table.group(1))
            return version("playwright"), {
                key: "/".join(re.findall(r"[\"']([^\"']+)[\"']", parts))
                for key, parts in entries}
    pytest.fail("Playwright %s names no chromium folders in an EXECUTABLE_PATHS table "
                "under %s. Find where it says where Chromium goes inside "
                "chromium-<build> and read it from there." % (version("playwright"), lib))


def test_the_installed_playwright_puts_chromium_where_it_is_looked_for(monkeypatch, tmp_path):
    """The table above is what Playwright has done. This asks the Playwright
    installed here what it does now, for every platform it names, so a folder
    it renames fails here as soon as that release is installed. CI installs
    the newest Playwright on every run, so its first run after the release
    catches it."""
    release, folders = _installed_chromium_folders()
    named = {prefix for key in folders for prefix, _p in _PLAYWRIGHT_PLATFORMS
             if key.startswith(prefix)}
    assert named == {"linux", "mac", "win"}, (
        "Playwright %s's table was not read whole, it names only %s" % (
            release, ", ".join(sorted(folders)) or "nothing"))
    missed = []
    for key, inner in sorted(folders.items()):
        platform = next((p for prefix, p in _PLAYWRIGHT_PLATFORMS if key.startswith(prefix)), None)
        assert platform, "Playwright %s names a platform this test does not know, %s" % (
            release, key)
        root = tmp_path / key
        exe = root / "chromium-1243" / inner
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        monkeypatch.setattr(browser.sys, "platform", platform)
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
        if browser._bundled_chromium() != [str(exe)]:
            missed.append("%s %s" % (key, inner))
    assert not missed, "Playwright %s puts Chromium where it is not looked for, %s" % (
        release, ", ".join(missed))


def test_a_window_that_opens_without_a_debugging_port_is_reported(monkeypatch, tmp_path, capsys):
    """Launching is not the same as listening. When Edge or Chrome is already
    running, a new launch can hand the address to the existing session and drop
    the flags, so a window opens, the user signs in, and only the NEXT command
    reveals that no port was ever opened. By then the sign-in was spent on a
    browser the tool cannot see."""
    # The launcher asks browser_candidates, not find_browser, and that reads
    # the machine through _real_browsers and _bundled_chromium, so the
    # stand-ins go there. Patching find_browser left this test reading the
    # browsers on whoever's machine ran it, and on one with none it said no
    # browser was found and launched nothing. Edge is the only browser here,
    # so the download offered after it fails is stood in for as well.
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "/x/edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: [])
    monkeypatch.setattr(browser, "fetch_bundled_chromium", lambda *a, **k: False)
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
    # browser_candidates is what the launcher asks, as in
    # test_launch_passes_the_profile_and_port. With find_browser patched
    # instead, a machine with no browser never reached Popen.
    monkeypatch.setattr(browser, "browser_candidates",
                        lambda prefer_real=False, mode=browser.AUTO: [("Chromium", "chrome")])
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
    and somebody else may not want a 400 MB download. Both are honored."""
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.EDGE, "edge")])
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
    assert browser.browser_candidates(mode=browser.INSTALLED) == [(browser.EDGE, "edge")]
    assert browser.browser_candidates(mode=browser.BUNDLED) == [(browser.CHROMIUM, "bundled")]


def test_bundled_mode_never_looks_for_their_own_browsers(monkeypatch):
    """Only the Playwright build is wanted, so nothing of the person's own is
    looked up. It used to be, and the answer thrown away, which read the
    registry and the folders browsers install into on every launch of the
    bundled copy and in every test that starts its browser from
    browser_candidates(mode=BUNDLED), 46 test files on 2026-10-06."""
    def looked(*a, **k):
        raise AssertionError("their own browsers were looked for")
    monkeypatch.setattr(browser, "_real_browsers", looked)
    monkeypatch.setattr(browser, "_registry_browsers", looked)
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["bundled"])
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


def test_the_wording_says_their_own_profile_is_not_used(monkeypatch):
    """Someone is about to look at a browser they recognize which knows none of
    their accounts. Both halves have to be said, that their real profile is
    untouched AND that they are therefore not signed in."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    note = browser.profile_note("Microsoft Edge")
    # Whitespace-normalized, because the note is hard-wrapped for a console and
    # a phrase can straddle a line break.
    flat = " ".join(note.split()).lower()
    assert "separate profile" in flat
    assert "untouched" in flat
    assert "not signed in" in flat
    assert "microsoft edge" in flat


def test_on_the_server_it_says_where_the_window_is(monkeypatch):
    """On PaperPull Server the window opens on the container's own screen,
    so "the copy already on this computer" would be wrong and send the
    person looking on their own desktop."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    flat = " ".join(browser.profile_note("Google Chrome").split()).lower()
    assert "browser screen" in flat and "not signed in" in flat
    assert "this computer" not in flat


# -- bugs found in review, before 1.0 ---------------------------------------

def test_other_chromium_browsers_are_recognized(monkeypatch):
    """The message offered to drive "Chrome, Edge, Brave or any other
    Chromium-based browser" while the detector only ever looked for Chrome and
    Edge. Somebody running Brave was pushed into a 400 MB download of a browser
    they effectively already had."""
    known = " ".join(exe for _n, exe, _p in browser._WINDOWS_BROWSERS).lower()
    for family in ("brave", "vivaldi", "opera"):
        assert family in known, family


def test_the_same_install_is_never_offered_twice(monkeypatch, tmp_path):
    """Several candidate paths can point at one install. Trying it again opens
    a second window to fail in exactly the same way.

    Forced by pointing both Program Files variables at one folder, which makes
    two of Edge's candidate paths identical. An earlier version of this test
    asserted against an empty list and so proved nothing.
    """
    monkeypatch.setattr(browser.sys, "platform", "win32")
    monkeypatch.setenv("ProgramW6432", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    # The registry names the same file, with different casing, which is the
    # commonest way one install turns up twice.
    monkeypatch.setattr(browser, "_registry_browsers",
                        lambda: [(browser.EDGE, str(edge).upper())])

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


# -- Windows on ARM, and every other machine where Program Files lies -------

class _FakeWinreg:
    """Just enough of winreg to see which keys were asked for and how."""
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100

    def __init__(self, values):
        self.values = values      # (hive, subkey) -> default value
        self.opened = []

    def OpenKey(self, hive, sub, reserved, access):
        self.opened.append((hive, sub, access))
        if (hive, sub) not in self.values:
            raise OSError(2, "not found")

        class _Key:
            def __enter__(self_):
                return (hive, sub)

            def __exit__(self_, *a):
                return False
        return _Key()

    def QueryValueEx(self, key, name):
        return self.values[key], 1


# The registry is read only on Windows. Elsewhere os.path.expandvars leaves
# %FAKEROOT% as it is, so the Edge value below is never expanded.
@pytest.mark.skipif(sys.platform != "win32", reason="the registry is read only on Windows")
def test_the_registry_is_asked_first_in_the_64_bit_view(monkeypatch, tmp_path):
    """An x64 build running under emulation on an ARM64 machine sees the
    emulated registry view by default, where a native ARM64 Chrome is not
    registered. App Paths in the 64-bit view is the browser's own statement
    of where it is, whatever this process happens to be."""
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    reg = _FakeWinreg({
        ("HKLM", browser._APP_PATHS + "\\chrome.exe"): '"%s"' % chrome,
        ("HKCU", browser._APP_PATHS + "\\msedge.exe"): "%FAKEROOT%\\msedge.exe",
    })
    monkeypatch.setitem(sys.modules, "winreg", reg)
    monkeypatch.setenv("FAKEROOT", str(tmp_path))
    found = browser._registry_browsers()
    assert (browser.EDGE, str(tmp_path / "msedge.exe")) in found     # expanded, HKCU honored
    assert (browser.CHROME, str(chrome)) in found                     # quotes stripped
    assert all(access & reg.KEY_WOW64_64KEY for _h, _s, access in reg.opened)
    hives = [h for h, s, _a in reg.opened if s.endswith("chrome.exe")]
    assert hives == ["HKCU", "HKLM"], "the per-user install must be asked first"


def test_no_winreg_means_no_registry_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert browser._registry_browsers() == []


def test_the_real_64_bit_program_files_is_searched_even_when_program_files_lies(monkeypatch, tmp_path):
    """Under emulation, or from a 32-bit process, PROGRAMFILES points at
    "Program Files (x86)". ProgramW6432 always points at the real one, and a
    Chrome that lives only there was invisible before."""
    monkeypatch.setattr(browser.sys, "platform", "win32")
    real = tmp_path / "Program Files"
    x86 = tmp_path / "Program Files (x86)"
    chrome = real / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")
    x86.mkdir()
    monkeypatch.setenv("ProgramW6432", str(real))
    monkeypatch.setenv("PROGRAMFILES", str(x86))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(x86))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr(browser, "_registry_browsers", lambda: [])
    assert browser._real_browsers() == [(browser.CHROME, str(chrome))]
    assert browser._windows_roots()[0] == str(real)


def test_brand_preference_beats_where_a_browser_was_found(monkeypatch, tmp_path):
    """The registry can list Brave when Edge is only on disk. Edge is still
    offered first, since the order is by brand, the thing the user is told."""
    monkeypatch.setattr(browser.sys, "platform", "win32")
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    brave = tmp_path / "brave.exe"
    brave.write_bytes(b"")
    for var in ("ProgramW6432", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path))
    monkeypatch.setattr(browser, "_registry_browsers", lambda: [(browser.BRAVE, str(brave))])
    assert [n for n, _p in browser._real_browsers()] == [browser.EDGE, browser.BRAVE]


def _serve(handler_body, status=200):
    """A one-shot local HTTP server on a free port, for the readiness check."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = handler_body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_readiness_means_devtools_answered_not_just_the_port():
    """The listener opens before the protocol is up. Attaching in that gap
    fails and blames the wrong thing, so ready means /json/version answers
    with the websocket address the attach will use."""
    srv = _serve('{"Browser": "Chrome/1", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/x"}')
    try:
        assert browser.wait_for_debug_port(str(srv.server_port), timeout=3) is True
    finally:
        srv.shutdown()
    srv = _serve("not devtools", status=404)
    try:
        assert browser.wait_for_debug_port(str(srv.server_port), timeout=1) is False
    finally:
        srv.shutdown()
    srv = _serve('{"Browser": "Chrome/1"}')        # answers, but no websocket yet
    try:
        assert browser.wait_for_debug_port(str(srv.server_port), timeout=1) is False
    finally:
        srv.shutdown()


# -- a prompt nobody can answer (#48) ----------------------------------------

def test_a_question_with_nobody_to_ask_comes_back_as_none(monkeypatch):
    """The panel closes an app's stdin so a stray prompt cannot hang a
    run. An app that asked anyway read end-of-file and took the process
    down, which closed the browser window the person was signing in to."""
    monkeypatch.setattr(browser, "can_ask", lambda: False)
    assert browser.ask_or_none("anything? ") is None


def test_a_windows_null_stdin_claims_to_be_a_terminal_and_is_still_handled(monkeypatch):
    """A process handed DEVNULL on Windows reports isatty() as True and
    then raises at the first read, so can_ask alone is not enough."""
    monkeypatch.setattr(browser, "can_ask", lambda: True)

    def boom(prompt=""):
        raise EOFError()
    monkeypatch.setattr("builtins.input", boom)
    assert browser.ask_or_none("anything? ") is None


def test_an_answer_comes_back_when_there_is_somebody(monkeypatch):
    monkeypatch.setattr(browser, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "  yes  ")
    assert browser.ask_or_none("anything? ") == "  yes  "


def test_signing_in_without_a_console_says_what_to_press_and_does_not_wait(monkeypatch):
    monkeypatch.setattr(browser, "can_ask", lambda: False)
    said = []
    assert browser.pause_for_sign_in(say=said.append, next_step="Pilot") is False
    text = " ".join(said)
    assert "leave it open" in text
    assert "Pilot" in text


def test_signing_in_with_a_console_waits(monkeypatch):
    monkeypatch.setattr(browser, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    said = []
    assert browser.pause_for_sign_in(say=said.append) is True
    assert said == [], "nothing is explained when somebody was there to ask"
