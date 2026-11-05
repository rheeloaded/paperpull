"""Finding and launching the sign-in browser, on whichever OS you are using.

Every app opens the same kind of window: an ordinary browser, on this app's
own debugging port, using this app's own profile directory, which *you* then
sign into. The tool later attaches to it over the DevTools protocol. Nothing
here automates a login.

Two flavors:

* Most providers are happy with the Chromium that Playwright installs.
* A few (Walmart, Verizon) do not work in that build, where their sites show
  a "robot or human" wall on loop. Those work far more reliably in the
  person's own installed browser, so they ask for Edge or Chrome first and
  fall back to Chromium.

Windows, macOS and Linux are all supported. The only real difference is where
the browsers live, which is what BROWSERS below records.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

CHROMIUM = "Chromium"
EDGE = "Microsoft Edge"
CHROME = "Google Chrome"
# Also Chromium underneath, so all of them speak the DevTools protocol and can
# be driven exactly like Chrome. They are listed because the alternative for
# somebody who runs one of these is a 400 MB download of a browser they
# effectively already have.
BRAVE = "Brave"
VIVALDI = "Vivaldi"
OPERA = "Opera"


def _from_env(name: str) -> Optional[str]:
    """A setting read the way Playwright reads one, the variable itself and
    then the two names npm gives it. A variable that is set, even to
    nothing, is the answer, and npm's names are not read then."""
    for key in (name, "npm_config_" + name.lower(), "npm_package_config_" + name.lower()):
        value = os.environ.get(key)
        if value is not None:
            return value
    return None


def _playwright_package() -> Optional[Path]:
    """The folder of the Playwright this Python would import, found without
    importing it, or None when there is none."""
    try:
        spec = importlib.util.find_spec("playwright")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(spec.submodule_search_locations[0])


def _playwright_root() -> Optional[Path]:
    """Where Playwright keeps the browsers it downloads, by Playwright's own
    rules, which have not changed since 1.9 (registryDirectory and
    computeDefaultCacheDirectory in its driver). None when they name the
    folder of a Playwright this Python does not have.

    PLAYWRIGHT_BROWSERS_PATH=0 is a folder inside Playwright's own package,
    driver/package/.local-browsers in its Python package. Any other value is
    the folder itself, 1 included, since no release of Playwright ever read
    1 another way. Without it, Linux keeps them under XDG_CACHE_HOME when
    that is set, and Windows under AppData/Local in the home folder when
    LOCALAPPDATA is not. A relative folder is found from INIT_CWD, or else
    from the folder this runs in, as Playwright finds it.

    Until 2026-10-05 XDG_CACHE_HOME went unread, and 0 and 1 counted as no
    setting at all, so on such a machine the Chromium Playwright had
    downloaded was never found, and the download offered in its place went
    where it would not be found either. browsers_folder in
    tools/run_all_tests.py has the same rules, and
    core/tests/test_run_all_tests_tool.py holds the two together.
    """
    override = _from_env("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        package = _playwright_package()
        if package is None:
            return None
        root = package / "driver" / "package" / ".local-browsers"
    elif override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ms-playwright"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"
    if not root.is_absolute():
        root = Path(os.path.abspath(os.path.join(_from_env("INIT_CWD") or os.getcwd(), root)))
    return root


def _build_number(path: str) -> int:
    """The build in a path to a Chromium or a headless shell of
    Playwright's, the last chromium-1248 or chromium_headless_shell-1248 in
    it, so a folder of that name above Playwright's own is not read, or -1."""
    found = re.findall(r"chromium(?:_headless_shell)?-(\d+)", path)
    return int(found[-1]) if found else -1


# The file Playwright writes into a build's folder last of all, once every
# file of the build is unpacked. A folder without it is an install that
# stopped partway, a closed window or a power cut at the wrong moment. That
# folder can hold the executable and most of the build, so looking for the
# executable alone took it for the newest build. The sign-in then started it
# with the finished build beside it never tried, nothing was due because the
# number was not behind, and a browser counted as being there, so no repair
# was offered either (#132). Playwright's own removal reads it the same way,
# and chromium_builds in tools/run_all_tests.py does too.
INSTALLED_MARK = "INSTALLATION_COMPLETE"


def _finished(found: List[str], above: int) -> List[str]:
    """The executables in `found` whose build finished installing, the folder
    of the build being `above` folders over each one. Counted from the
    executable, so a folder of any name, chromium-1248 - Copy included, is
    read as Playwright's own is. isfile, which never raises, since a folder
    that cannot be read must not stop a sign-in."""
    return [path for path in found
            if os.path.isfile(Path(path).parents[above] / INSTALLED_MARK)]


def _bundled_chromium(root: Optional[Path] = None) -> List[str]:
    """Every full Chromium build of Playwright's on disk, newest first, in
    root or else in the folder Playwright keeps its browsers in. A build that
    never finished installing is not there (_finished)."""
    root = root or _playwright_root()
    if root is None:
        return []
    if sys.platform == "win32":
        patterns = ["chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-win/chrome.exe"]
    elif sys.platform == "darwin":
        # Playwright renamed the macOS bundle: builds up to ~1200 shipped
        # "Chromium.app/Contents/MacOS/Chromium", newer ones ship "Google
        # Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing".
        # Only the old name was matched here, so on an up-to-date install NO
        # bundled Chromium was found and every app silently fell back to
        # Edge/Chrome - or reported no browser at all when neither was
        # installed. Both layouts are matched now.
        patterns = ["chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
                    "chromium-*/chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium",
                    "chromium-*/chrome-mac*/Google Chrome for Testing.app"
                    "/Contents/MacOS/Google Chrome for Testing"]
    else:
        # Playwright 1.57 moved Linux on x64 to Chrome for Testing, which
        # unpacks into chrome-linux64, and 1.63 moved ARM from Playwright's
        # own build in chrome-linux to chrome-linux-arm64. Only chrome-linux
        # was matched here, so no bundled Chromium was found on x64 from
        # 1.57 or on ARM from 1.63. BUNDLED had nothing to offer there, and
        # an older build still on disk was handed over instead of the new.
        patterns = ["chromium-*/chrome-linux64/chrome",
                    "chromium-*/chrome-linux-arm64/chrome",
                    "chromium-*/chrome-linux/chrome"]
    found: List[str] = []
    for pattern in patterns:
        found += _finished(glob.glob(str(root / pattern)), pattern.count("/") - 1)

    # Newest build first. Playwright pins a build per release, and an older
    # build stays on disk while another installation still uses it (an app
    # venv on an older Playwright, for example), so "whatever glob returned
    # first" can hand back a build older than the installed playwright
    # expects. Sort on the build NUMBER, not the string, since
    # "chromium-1000" sorts before "chromium-999" as text. This order is the
    # sign-in's, and so is left as it was (_on_disk).
    def build_number(path: str) -> int:
        m = re.search(r"chromium-(\d+)", path)
        return int(m.group(1)) if m else -1

    return sorted(found, key=build_number, reverse=True)


# Where the headless shell sits inside chromium_headless_shell-<build>,
# as Playwright's EXECUTABLE_PATHS names it for "chromium-headless-shell".
# Up to 1.56 it was a headless_shell beside Chromium's own files, from 1.57
# Chrome for Testing's chrome-headless-shell in a folder of its own.
# core/tests/test_browser.py reads the installed Playwright's table, so a
# folder it renames fails there.
_HEADLESS_SHELLS = {
    "win32": ("chrome-headless-shell-win64/chrome-headless-shell.exe",
              "chrome-win/headless_shell.exe"),
    "darwin": ("chrome-headless-shell-mac-x64/chrome-headless-shell",
               "chrome-headless-shell-mac-arm64/chrome-headless-shell",
               "chrome-mac/headless_shell"),
    "linux": ("chrome-headless-shell-linux64/chrome-headless-shell",
              "chrome-headless-shell-linux-arm64/chrome-headless-shell",
              "chrome-linux/headless_shell"),
}


def _headless_shells(root: Path) -> List[str]:
    """Every headless shell build of Playwright's in root, newest first.
    Each has no window, so it is only ever handed to a headless launch. A
    shell that never finished installing is not there (_finished)."""
    inner = _HEADLESS_SHELLS.get(sys.platform, _HEADLESS_SHELLS["linux"])
    found: List[str] = []
    for pattern in inner:
        found += _finished(sorted(glob.glob(str(root / "chromium_headless_shell-*" / pattern))),
                           pattern.count("/"))
    return sorted(found, key=_build_number, reverse=True)


# Where each brand registers its executable under App Paths, and the
# folder it installs to under a Program Files or LOCALAPPDATA root. The
# registry is consulted first because it is the browser's own statement of
# where it is, and the folders are the fallback for an install that did not
# register (a portable copy, or a per-user install on a locked-down machine).
_WINDOWS_BROWSERS = [
    (EDGE, "msedge.exe", ("Microsoft", "Edge", "Application", "msedge.exe")),
    (CHROME, "chrome.exe", ("Google", "Chrome", "Application", "chrome.exe")),
    (BRAVE, "brave.exe", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
    (VIVALDI, "vivaldi.exe", ("Vivaldi", "Application", "vivaldi.exe")),
    (OPERA, "opera.exe", ("Programs", "Opera", "opera.exe")),
]
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"


def _registry_browsers() -> List[Tuple[str, str]]:
    """Every browser Windows knows about, from App Paths, in preference order.

    Read from the 64-bit registry view on purpose. This process can be an
    x64 build running under emulation on an ARM64 machine, where the
    default view is the emulated one and a native ARM64 Chrome would be
    invisible from it. HKCU first, since a per-user install is the one the
    person chose most recently, then HKLM.
    """
    try:
        import winreg
    except ImportError:
        return []
    out: List[Tuple[str, str]] = []
    for name, exe, _ in _WINDOWS_BROWSERS:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, _APP_PATHS + "\\" + exe, 0,
                                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                    value, _kind = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            path = os.path.expandvars(str(value or "")).strip().strip('"')
            if path:
                out.append((name, path))
    return out


def _windows_roots() -> List[str]:
    """The folders a browser installs under, most authoritative first.

    ProgramW6432 is the real 64-bit Program Files even when this process is
    32-bit or emulated, which is when PROGRAMFILES quietly points at the
    (x86) folder instead. Empty and repeated values are dropped.
    """
    roots = []
    for var in ("ProgramW6432", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(var, "")
        if value and value not in roots:
            roots.append(value)
    return roots


def _real_browsers() -> List[Tuple[str, str]]:
    """Installed Edge/Chrome, most-preferred first, as (name, path)."""
    if sys.platform == "win32":
        candidates = list(_registry_browsers())
        for root in _windows_roots():
            for name, _exe, parts in _WINDOWS_BROWSERS:
                candidates.append((name, os.path.join(root, *parts)))
        # Preference order is by brand, not by where it was found, so a
        # Brave in the registry does not outrank an Edge found by folder.
        rank = {name: i for i, (name, _e, _p) in enumerate(_WINDOWS_BROWSERS)}
        candidates.sort(key=lambda c: rank.get(c[0], len(rank)))
    elif sys.platform == "darwin":
        home = Path.home()
        candidates = [
            (EDGE, "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            (EDGE, str(home / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
            (CHROME, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            (CHROME, str(home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
            (BRAVE, "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            (BRAVE, str(home / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser")),
            (VIVALDI, "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"),
            (OPERA, "/Applications/Opera.app/Contents/MacOS/Opera"),
        ]
    else:
        candidates = [
            (EDGE, "/usr/bin/microsoft-edge"), (EDGE, "/usr/bin/microsoft-edge-stable"),
            (CHROME, "/usr/bin/google-chrome"), (CHROME, "/usr/bin/google-chrome-stable"),
            (CHROME, "/usr/bin/chromium-browser"), (CHROME, "/usr/bin/chromium"),
            (BRAVE, "/usr/bin/brave-browser"), (BRAVE, "/usr/bin/brave"),
            (VIVALDI, "/usr/bin/vivaldi"), (VIVALDI, "/usr/bin/vivaldi-stable"),
            (OPERA, "/usr/bin/opera"),
        ]
    # Deduplicated by resolved path. Several of these entries can point at the
    # same install, and offering the same browser twice would launch a second
    # window to fail in exactly the same way.
    out, seen = [], set()
    for name, path in candidates:
        if not path or not os.path.exists(path):
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append((name, path))
    return out


def _real_first(prefer_real: bool, bundled: List[str]) -> bool:
    """Whether a browser of the person's own goes ahead of the bundled
    Chromium, given what _bundled_chromium found.

    An app asks for that when its provider's bot protection turns the
    Playwright build away. On Linux it is also so unless a build sits in
    chrome-linux, the one folder looked in there before October 2026.
    Builds in chrome-linux64 (x64 since Playwright 1.57) and
    chrome-linux-arm64 (ARM since 1.63) were never found, so where only
    those are on disk the person has been signing in through a browser of
    their own, and putting the bundled copy first would move them and cost
    them a sign-in. So finding those folders moves nobody. Ubuntu 23.10
    and later also keep a downloaded Chrome for Testing from the user
    namespaces its sandbox needs, so there it stops with "No usable
    sandbox!" (Puppeteer's troubleshooting guide says so), and a window for
    signing in to a bank is never started without its sandbox.
    """
    if prefer_real or sys.platform in ("win32", "darwin"):
        return prefer_real
    return not any(Path(path).parent.name == "chrome-linux" for path in bundled)


def find_browser(prefer_real: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Return (name, executable path) for the browser to sign in with.

    With prefer_real, an installed Edge/Chrome wins over the bundled
    Chromium, which is what gets past the providers whose bot protection
    rejects the Playwright build. On Linux one also does unless a build sits
    in chrome-linux (_real_first).
    """
    real = _real_browsers()
    bundled = _bundled_chromium()
    if _real_first(prefer_real, bundled) and real:
        return real[0]
    if bundled:
        return CHROMIUM, bundled[0]
    if real:
        return real[0]
    return None, None


def port_from_cdp_url(cdp_url: str, default: str = "9222") -> str:
    m = re.search(r":(\d+)", cdp_url or "")
    return m.group(1) if m else default


def setup_hint() -> str:
    return "setup.bat" if sys.platform == "win32" else "./setup.command"


# -- choosing a browser, and fetching one only if there is no choice ---------
#
# The bundled Chromium is by far the largest thing this project would ever ask
# anyone to download. Measured on a real install it is 416 MB on disk and 184 MB
# compressed, against roughly 60 MB for everything else put together.
#
# Almost nobody needs it. Any Chromium-family browser can be driven the same
# way, and on Windows Edge is always present. The case it genuinely exists for
# is a Mac with only Safari, because Safari does not speak the DevTools
# protocol at all and neither does Firefox.
#
# So the download is not part of setup. It is offered at the moment somebody
# tries to sign in and nothing suitable answers, which is the first point where
# it is actually needed and where the person is present to agree to it.

AUTO = "auto"           # use what is installed, fall back to bundled
INSTALLED = "installed"  # only a browser they already have
BUNDLED = "bundled"     # only the Playwright build, never touch their own


def browser_candidates(prefer_real: bool = False, mode: str = AUTO):
    """Browsers to try, best first, as (name, path).

    Ordered rather than singular because "installed" is not the same as
    "usable". Edge can be present and still refuse to open a debugging port,
    which is only discoverable by launching it, so the caller works down this
    list until one actually answers.
    """
    found = _bundled_chromium()
    # Only the newest bundled build. Playwright leaves older ones behind, and
    # retrying the same browser at a different revision opens a second window
    # to fail the same way, since the usual cause is the port rather than the
    # build.
    bundled = [(CHROMIUM, p) for p in found[:1]]
    if mode == BUNDLED:
        # Their own browsers are not even looked for. Until 2026-10-06 they
        # were looked up first and the answer thrown away, so every launch of
        # the bundled copy searched the machine for the browsers installed on
        # it (on Windows the registry, Program Files and the person's own
        # AppData), and so did every test that takes its Chromium from here.
        return bundled
    real = _real_browsers()
    if mode == INSTALLED:
        return real
    # With a bundled copy already present it stays first unless an app asks for
    # a real browser. Reordering that would move existing users onto a
    # different browser, and a profile built by one is not guaranteed to open
    # cleanly in another, which would cost them a sign-in for no benefit.
    # For the same reason a Linux machine that never found its bundled copy
    # keeps the person's own browser first (_real_first).
    return (real + bundled) if _real_first(prefer_real, found) else (bundled + real)


def bundled_chromium_present() -> bool:
    """Whether a Chromium of Playwright's is on disk. Any finished build will
    do, an older one than the installed Playwright's included, since a launch
    takes the newest one there when Playwright's own is missing (_on_disk)."""
    return bool(_bundled_chromium())


def bundled_chromium_first() -> bool:
    """Whether the bundled Chromium is there and goes ahead of a browser of
    the person's own for an app that does not ask for a real one. Off Linux
    that is whenever it is there (_real_first)."""
    found = _bundled_chromium()
    return bool(found) and not _real_first(False, found)


def profile_note(name: str) -> str:
    """What to tell someone whose own browser is about to open.

    This wording matters and is easy to get wrong. The tool launches their
    browser with its OWN --user-data-dir, so their everyday profile, history,
    extensions and existing logins are untouched and unreadable by it. The flip
    side is the one people get caught by: they are NOT already signed in, and
    a window that looks like their browser but knows none of their accounts is
    alarming if nobody warned them.

    On PaperPull Server the window opens on the container's virtual screen,
    which the person sees through the panel, so it says where to look
    instead. That browser is the server's own, never theirs.
    """
    if os.environ.get("PAPERPULL_SERVER") == "1":
        note = (
            "The %s window is open on PaperPull Server's Browser Screen. Open\n"
            "it with the Browser Screen button at the top of the panel.\n"
            "\n"
            "It is a browser of the server's own, so you are NOT signed in there\n"
            "yet. Sign in as you would on a new computer, and leave the window open." % name
        )
        if server_graphics() == "software":
            note += (
                "\n\n"
                "This server's browser has no graphics card, so some sites, Best Buy\n"
                "among them, may refuse your sign-in. If the machine has Intel or AMD\n"
                "graphics, pass them to the container, see Graphics in SERVER.md.")
        return note
    return (
        "This is the copy of %s already on this computer, opened with a\n"
        "separate profile of its own. Your normal browsing is untouched, and\n"
        "this tool cannot see your usual history, extensions or saved logins.\n"
        "\n"
        "It also means you are NOT signed in here yet. Sign in as you would on\n"
        "a new computer, and leave the window open." % name
    )


def can_ask() -> bool:
    """Whether there is a person on the other end of stdin.

    The control panel runs these as subprocesses with stdin closed, precisely
    so a stray prompt cannot hang a run. Asking a question nobody can answer
    would reintroduce that, so when there is no console the answer is to
    explain instead of prompt.
    """
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (ValueError, AttributeError):
        return False


def ask_or_none(prompt: str):
    """The answer to a question, or None when there is nobody to ask.

    `can_ask` is the right test under the control panel, which closes a
    pipe so that stdin reports itself as not a terminal. It is not enough
    on its own, because a Windows process handed DEVNULL reports
    `isatty()` as True and then raises at the first read. Both are
    handled here so that no caller has to remember either.
    """
    if not can_ask():
        return None
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt, OSError):
        return None


def pause_for_sign_in(say=print, next_step: str = "Discover or Pilot") -> bool:
    """Hold while the person signs in, when there is somebody to hold for.

    Returns True if it waited, False if there was nobody to ask.

    An app that opens its own browser used to call input() here. Under the
    control panel, which closes an app's stdin so a stray prompt cannot
    hang a run, that read end-of-file and took the whole process down with
    it, which closed the browser window the person was about to sign in
    to. A tester saw the window open and vanish, and the output said "No
    interactive console available", which is true and is about the wrong
    thing (#48).

    Nothing is granted by not waiting. The browser stays open and the
    person is told what to press next.
    """
    if ask_or_none("Press Enter here AFTER you have finished signing in... ") is not None:
        return True
    say("")
    say("Sign in to the browser window that just opened, and leave it open.")
    say("Then come back to the panel and press %s." % next_step)
    say("Your sign-in is kept in this app's own browser profile, so it is")
    say("only asked for again when the provider expires it.")
    return False


def _in_a_store_package(program) -> bool:
    """Whether `program` sits in a Microsoft Store package's own folder, a
    folder named WindowsApps holding one with the package's full name, which
    has two underscores before its publisher. A program in there that the
    package does not declare will not start from a person's Command Prompt.
    The folder of that name where Windows keeps its app aliases, which the
    Python the Store installs runs from, holds no such name, and neither does
    a checkout somebody keeps in a folder called WindowsApps."""
    parts = [part.lower() for part in re.split(r"[\\/]+", str(program))]
    return any(part == "windowsapps" and "__" in following
               for part, following in zip(parts, parts[1:]))


def browser_install_command():
    """The command that downloads a browser, or None if this build cannot.

    "sys.executable -m playwright" is right when running from a normal Python
    install, and WRONG in a packaged build, where sys.executable is the
    application itself. That would re-launch the app rather than install
    anything. Playwright ships its own Node driver, whose path does not depend
    on how this process was started, so a frozen build uses that instead.

    The Store edition has no terminal to run this in, and its Python will not
    start from a person's Command Prompt, so it answers None. In the Mac app
    this line can be pasted into Terminal, which has neither setting the
    app's own scripts export, so -B and -s stand in for them and keep bytecode
    out of the signed bundle. Only there, since -s would hide a Playwright
    that a checkout on a plain Python keeps in the person's own site folder.
    """
    if _in_a_store_package(sys.executable):
        return None
    if not getattr(sys, "frozen", False):
        flags = ["-B", "-s"] if ".app/Contents/Resources/python/" in sys.executable else []
        return [sys.executable, *flags, "-m", "playwright", "install", "chromium"]
    try:
        # Private API, hence the guard. If it moves, saying so plainly beats
        # running a command that silently does the wrong thing.
        from playwright._impl._driver import compute_driver_executable
        node, cli = compute_driver_executable()
        return [str(node), str(cli), "install", "chromium"]
    except Exception:
        return None


def fetch_bundled_chromium(assume_yes: bool = False) -> bool:
    """Offer to download Playwright's Chromium, and do it if agreed.

    Returns True only if a browser is present afterwards.
    """
    if bundled_chromium_present():
        return True

    print()
    print("No browser this tool can drive was found on this computer.")
    print()
    print("It can drive Chrome, Edge, Brave or any other Chromium-based")
    print("browser. Safari and Firefox cannot be driven this way, so having")
    print("those does not help.")
    print()
    print("The alternative is to download a private copy of Chromium, about")
    print("400 MB. It is used only by this tool and does not become your")
    print("default browser or touch anything else.")
    print()
    print("Installing Chrome or Edge yourself and running this again works")
    print("just as well, and downloads far less.")
    print()

    if not assume_yes:
        if not can_ask():
            print("Run this from a terminal to be offered the download, or")
            print("install Chrome or Edge and try again.")
            return False
        try:
            answer = input("Download the private copy now? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer not in ("y", "yes"):
            print("Nothing was downloaded.")
            return False

    cmd = browser_install_command()
    if cmd is None:
        print("This build cannot download a browser for you.")
        print("Install Chrome or Edge and run this again.")
        return False

    print()
    print("Downloading. This takes a few minutes on a slow connection.")
    try:
        rc = subprocess.call(cmd)
    except OSError as e:
        print("Could not start the download (%s)." % e)
        return False
    if rc != 0 or not bundled_chromium_present():
        print()
        print("The download did not finish. You can retry, or install Chrome")
        print("or Edge instead, which this tool will then use.")
        return False
    print()
    print("Done.")
    return True


# -- keeping the private Chromium from falling behind (#132) ------------------------
#
# After the first download nothing updated PaperPull's own Chromium. Sign-in
# always starts the newest build on disk, and a PaperPull upgrade that brings
# a newer Playwright does not download that Playwright's Chromium, so a
# computer that took the download months ago kept signing in with that build.
# Each Playwright release carries a newer Chromium with its security fixes,
# so the copy fell further behind with every release. Nothing broke, since
# Playwright 1.64.1 drove builds 1234 and 1228 without trouble, it only got
# old (_on_disk keeps every launch working on whatever build is there).
#
# So the sign-in offers the update, in the place and the way it offers the
# first download, when the copy it is about to start is older than the build
# the installed Playwright was made for. It is offered only when that copy is
# the one that would start. Someone who signs in through their own Edge or
# Chrome is never asked about a copy they do not use. Under the control panel
# nobody can be asked, so the panel's log says so and gives the command.
#
# A failed update must never cost a person the browser they had. Playwright's
# install removes builds nothing else uses BEFORE it downloads
# (registry.install in its coreBundle.js, from 1.62 to 1.64.1 alike), and after
# an upgrade the old build counts as unused. Measured on 2026-11-04 with the
# download refused, the install removed the build and exited 1, and the sign-in
# then had nothing to start, or fell through to Edge on an empty profile. So
# the download runs with KEEP_OLD_BUILDS set, and the old build stays until the
# new one has opened a window on the person's own profile. Only then is the
# same command run again without it, which downloads nothing and removes what
# nothing else uses, so the disk use ends up about the same.
#
# That second run is started and left to itself. Playwright's removal keeps
# trying a file a running program holds, and it waited 745 seconds on one left
# open from the old build's folder. Each app has its own port, so a sign-in
# cannot see another app's window, and the offer says to close them first. A
# window left open on a Mac or Linux should lose its files as the removal runs,
# which could not be run here.
#
# A person who says no is not asked again until the Playwright wants a newer
# build still. The answer is a file beside the builds, so every app shares it
# and it goes with them.

DECLINED_UPDATE = "paperpull-chromium-update-declined"

# With this set, Playwright's install leaves builds nothing else uses alone.
# 1.62 reads it as well as 1.64.1. Its --no-remove came in with 1.63, and
# checkouts still have 1.62.
KEEP_OLD_BUILDS = "PLAYWRIGHT_SKIP_BROWSER_GC"


def _wanted_chromium_build() -> Optional[int]:
    """The Chromium build the installed Playwright was made for, from its
    browsers.json, or None when it cannot be read."""
    package = _playwright_package()
    if package is None:
        return None
    try:
        with open(package / "driver" / "package" / "browsers.json", encoding="utf-8") as f:
            for entry in json.load(f)["browsers"]:
                if entry.get("name") == "chromium":
                    return int(entry["revision"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def chromium_update_due(path: str) -> Optional[Tuple[int, int]]:
    """(the build `path` is, the build Playwright wants) when the Chromium at
    `path`, a build of Playwright's, is older than the one the installed
    Playwright was made for. None when it is as new, or newer, or either
    cannot be told."""
    have, want = _build_number(path), _wanted_chromium_build()
    if have < 0 or want is None or have >= want:
        return None
    return have, want


def _declined_file() -> Optional[Path]:
    root = _playwright_root()
    return root / DECLINED_UPDATE if root else None


def _update_declined(want: int) -> bool:
    """Whether somebody said no to `want` or a build at least as new. Apps on
    two Playwrights can share one folder of builds, and were an exact match
    asked for, each would overwrite the other's answer and ask again."""
    marker = _declined_file()
    try:
        return bool(marker) and int(marker.read_text(encoding="utf-8").strip()) >= want
    except (OSError, ValueError):
        return False


def _remember_declined(want: int) -> None:
    marker = _declined_file()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("%d\n" % want, encoding="utf-8")
    except (OSError, AttributeError):
        pass    # asked again next time, which is all that costs


def _install_takes_no_remove() -> bool:
    """Whether the installed Playwright's install takes --no-remove, which
    came in with 1.63, by the version its driver gives. 1.62 stops at a flag
    it does not know, and downloads nothing."""
    package = _playwright_package()
    if package is None:
        return False
    try:
        with open(package / "driver" / "package" / "package.json", encoding="utf-8") as f:
            major, minor = str(json.load(f)["version"]).split(".")[:2]
        return (int(major), int(minor)) >= (1, 63)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _update_line(cmd) -> str:
    """The line somebody pastes to update, which keeps the old build as the
    sign-in's own download does. Pasted without that, it removes the build
    first, and a download that fails then leaves them nothing."""
    if _install_takes_no_remove():
        return _command_line([*cmd, "--no-remove"])
    if sys.platform == "win32":
        return "set %s=1&& %s" % (KEEP_OLD_BUILDS, _command_line(cmd))
    return "%s=1 %s" % (KEEP_OLD_BUILDS, _command_line(cmd))


def offer_chromium_update(have: int, want: int, assume_yes: bool = False) -> Optional[bool]:
    """Offer to download the Chromium build Playwright wants, beside the
    older one on disk, and do it if agreed. None when nothing was tried. True
    when the install ended well with a finished build at least that new on
    disk. False when it was tried and did not, which can still have left a
    finished build, so the caller reads the folder again either way."""
    if _update_declined(want):
        return None
    cmd = browser_install_command()
    shown = _update_line(cmd) if cmd is not None else ""

    print()
    print("The private copy of Chromium on this computer is build %d. This PaperPull's" % have)
    print("Playwright was made for build %d. Newer builds carry newer security fixes," % want)
    print("and the copy falls further behind with every release. Signing in works")
    print("with the old one, so nothing is wrong, but it is better kept up to date.")
    print()
    if not assume_yes and not can_ask():
        # The control panel, which cannot ask, or anything else with no one
        # at the keyboard. Nothing is remembered, since nobody said no.
        if shown:
            print("Updating downloads about 400 MB, and the build you have stays beside it.")
            print("To update it, open %s, run the line below, and sign in again:" % _terminal_name())
            print(shown)
        else:
            print("This build cannot download it for you.")
        print("Signing in goes on with the build that is here.")
        return None

    print("Updating downloads about 400 MB. The build you have stays until the new one")
    print("has opened, and is then cleared away, so the space used stays about the same.")
    print("Close any other sign-in windows first, since they run from that build.")
    print()
    if not assume_yes:
        try:
            answer = input("Update it now? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if answer not in ("y", "yes"):
            _remember_declined(want)
            print("Nothing was downloaded. You will be asked again when PaperPull wants")
            print("a newer build than %d." % want)
            return None

    if cmd is None:
        print("This build cannot download a browser for you.")
        return None
    print()
    print("Downloading. This takes a few minutes on a slow connection.")
    try:
        rc = subprocess.call(cmd, env=dict(os.environ, **{KEEP_OLD_BUILDS: "1"}))
    except KeyboardInterrupt:
        print()
        print("The download was stopped. Signing in goes on with the build that is here,")
        print("and you will be asked again at the next sign-in.")
        return False
    except OSError as e:
        print("Could not start the download (%s)." % e)
        return False
    newest = _bundled_chromium()
    if rc != 0 or not newest or _build_number(newest[0]) < want:
        print()
        print("The download did not finish. Signing in goes on with the build that")
        print("is here, and you can try again at the next sign-in.")
        return False
    print()
    print("Done. Now signing in with build %d." % _build_number(newest[0]))
    return True


def _clear_old_builds() -> None:
    """Run the install again with nothing held back, now that the new build
    has opened, so Playwright removes what nothing else uses, and do not wait
    for it. It downloads nothing. Playwright's removal can spend minutes on a
    file another window holds, and nobody signing in should wait on that. It
    outlives this process and writes nowhere, as a sign-in window does
    (_launch). On Windows it gets a console nobody sees, since a process with
    none would open a new window for the Node driver Playwright's Python
    starts. A run that cannot start costs only the space the old build takes."""
    try:
        cmd = browser_install_command()
        if cmd is None:
            return
        hidden = {}
        if sys.platform == "win32":
            hidden["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, **hidden)
    except Exception:
        pass


def _set_aside_new_build(path: str, old: str) -> None:
    """The build an update brought would not open, so the old one signs in
    and goes on being the one that does. Left as it was, the new build would
    be the newest at every sign-in from now on, so its mark is taken away,
    which makes it a build that is not there (_finished), and the update is
    not offered again until Playwright wants a newer build still. Should the
    new build only have been slow, this costs an update and nothing else."""
    build = _build_number(path)
    try:
        print()
        print("Build %d did not open on this computer, so signing in goes on with build"
              " %d," % (build, _build_number(old)))
        print("which stays where it is. You will be asked again when PaperPull wants a")
        print("newer build than %d." % build)
        _remember_declined(build)
        for folder in Path(path).parents:
            if os.path.isfile(folder / INSTALLED_MARK):
                os.remove(folder / INSTALLED_MARK)
                break
    except Exception:
        pass


def _offer_update_at_sign_in(had: Tuple[str, str], allow_fetch: bool) -> Optional[bool]:
    """Offer the update when `had`, the browser about to start, is the
    private copy and has fallen behind. Answers as offer_chromium_update, and
    None when there was nothing to offer. All of this is optional, so nothing
    it meets, a Ctrl-C or a browsers.json no one could read included, keeps
    the sign-in from going on (_say_shared_port). An offer that ended that way
    answers False, since a download may have left something.

    Never for a build in chrome-linux. Every new build lands in chrome-linux64
    or chrome-linux-arm64, so with that one gone _real_first would turn and
    move the person onto a browser of their own with Chromium's profile,
    which browser_candidates warns against, and on Ubuntu 23.10 and later the
    new build may not even start its sandbox."""
    tried = None
    try:
        if (allow_fetch and had[0] == CHROMIUM and os.environ.get("PAPERPULL_SERVER") != "1"
                and Path(had[1]).parent.name != "chrome-linux"):
            due = chromium_update_due(had[1])
            if due:
                tried = False
                tried = offer_chromium_update(*due)
    except (Exception, KeyboardInterrupt):
        pass
    return tried


def launch_own_browser(chromium, user_data_dir, **kwargs):
    """A browser of the app's own, for settings that name no cdp_url, said
    out loud. Every app opens one that way when its config has no cdp_url,
    while its sign-in opens the person's own browser on the app's port, so
    the run and the sign-in used different browsers with nothing said, and
    the run's window looked signed out (#90). `chromium` is Playwright's
    browser type, and the rest goes to sandboxed_persistent_context, so the
    browser always starts inside its sandbox. One whose sandbox cannot
    start ends the run and says why."""
    print("This app's settings name no cdp_url, so this run opens a browser of its")
    print("own, with the profile in %s," % user_data_dir)
    print("instead of attaching to the window you signed in with, and it is signed in")
    print("only if you sign in there. To use your sign-in window, copy the cdp_url")
    print("line from config.example.json into this app's config.json.")
    try:
        return sandboxed_persistent_context(chromium, user_data_dir, **kwargs)
    except SandboxRefused as e:
        raise SystemExit(str(e)) from None


# -- every browser Playwright starts, inside its sandbox ------------------------
#
# Playwright's driver starts Chromium with --no-sandbox unless it is handed
# chromium_sandbox=True, exactly True (1.63's coreBundle.js pushes the flag
# whenever `options.chromiumSandbox !== true`). Every app's own browser and
# the receipt renderer's were started that way, so a page in them ran with
# nothing between it and this computer but the renderer itself. Every
# launch now goes through the two functions below, which always ask for the
# sandbox and refuse any way of asking for less, and
# core/tests/test_every_browser_starts_in_its_sandbox.py holds every other
# file to them, the apps' own included.

SANDBOX_REFUSED = (
    "The browser could not start its sandbox, so it was not started. This tool "
    "never starts a browser without its sandbox. Chromium will not start its "
    "sandbox when it runs as the root user, and on Ubuntu 23.10 and later the "
    "Chromium that Playwright downloads is kept from the user namespaces its "
    "sandbox needs, as it is in a container that does not allow them. Run this "
    "as an ordinary user, or install Google Chrome or Microsoft Edge and copy "
    "the cdp_url line from config.example.json into this app's config.json, so "
    "the run uses the window you sign in with instead of a browser of its own.")

# What Playwright's error says when Chromium could not start its sandbox.
# It rewrites Chromium's own words (No usable sandbox!, and crbug.com/357670
# or 638180 for a sandbox refused to root) into the first line here, and an
# older driver passed Chromium's words through. Chrome's own words when its
# setuid helper is there but not set up are passed through as they are,
# measured in a Linux container under Docker's default seccomp profile.
_SANDBOX_FAILED = ("chromium sandboxing failed", "no usable sandbox",
                   "crbug.com/357670", "crbug.com/638180",
                   "sandbox helper binary was found, but is not configured",
                   "rather than run without sandboxing")


class SandboxRefused(RuntimeError):
    """The browser could not start its sandbox, and so was not started."""


# -- PaperPull's own Chromium, where a step cannot do without it ------------------
#
# Sign-in and almost every app use the Edge or Chrome already on the computer,
# so most installs never download Playwright's Chromium, and nothing asks for
# it. The receipt renderer is the exception. It prints a page in a headless
# browser of its own, always Playwright's, so on such an install it met
# Playwright's "Executable doesn't exist ... playwright install" and that went
# into the purchase's notes as it stood. `playwright install` means nothing
# in the packaged app, where there is no `playwright` command, and the words
# did not say the account and the receipt were fine (#131).
#
# What is said instead names the one thing that is missing, says nothing is
# wrong with anything of the person's, and gives the command that downloads
# it, the same one fetch_bundled_chromium runs and, in a package, spelled with
# the package's own Python (browser_install_command).

class NoOwnChromium(RuntimeError):
    """PaperPull's own Chromium is needed for a step and is not on this
    computer. The message says what to do about it, in plain words."""


def is_missing_chromium(error) -> bool:
    """Whether `error` is Playwright saying the Chromium it was asked to
    start is not on this computer. Playwright's words, as of 1.64."""
    return "executable doesn't exist" in str(error).lower()


def _command_line(cmd) -> str:
    """`cmd` as one line that can be pasted into a terminal, each part
    quoted the way this system's shell reads it."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(cmd)
    return " ".join(shlex.quote(part) for part in cmd)


def _terminal_name() -> str:
    return {"darwin": "Terminal", "win32": "Command Prompt"}.get(sys.platform, "a terminal")


def missing_chromium_words() -> str:
    """What to tell somebody whose step needed PaperPull's own Chromium and
    found none: what it is, that nothing of theirs is wrong, and how to get it.
    PaperPull Server's Chrome is its own and a download there would not last,
    so neither a download nor the person's own browser fits (#110)."""
    if os.environ.get("PAPERPULL_SERVER") == "1":
        return ("This step prints the page in a copy of Chromium that this PaperPull Server "
                "container does not hold. Nothing is wrong with your account or with this "
                "document, but the document was not saved. Ask at "
                "https://github.com/rheeloaded/paperpull/issues.")
    head = ("This step prints the page in PaperPull's own copy of Chromium, and it has "
            "not been downloaded on this computer. Nothing is wrong with your account or "
            "with this document. Sign-in does not need it, since it uses the Chrome or "
            "Edge you already have.")
    cmd = browser_install_command()
    if cmd is None:
        return (head + " This build cannot download it for you, so the document was "
                "not saved. Ask at https://github.com/rheeloaded/paperpull/issues.")
    shown = _command_line(cmd)
    return (head + " To download it, about 400 MB, kept for PaperPull alone, open "
            + _terminal_name() + ", run this line, and then run this step again: "
            + shown)


def turns_sandbox_off(arg) -> bool:
    """Whether a Chromium switch would start the browser with less than its
    whole sandbox. Any switch whose name says sandbox, which covers
    --no-sandbox, --disable-setuid-sandbox and --disable-gpu-sandbox in any
    case and with one dash or two, a feature switch naming one, such as
    --disable-features=NetworkServiceSandbox, and the two that run the
    browser's parts in one process or without their own start,
    --single-process and --no-zygote. Any other switch's value is not
    read, so a host named sandbox.example.com in a list of hosts is not one."""
    name = _switch_name(arg)
    if name in ("--disable-features", "--enable-features", "--disable-blink-features",
                "--enable-blink-features", "--force-fieldtrials"):
        return "sandbox" in str(arg).lower()
    return "sandbox" in name or name in ("--single-process", "--no-zygote")


def _switch_name(arg) -> str:
    return "--" + str(arg).strip().lower().lstrip("-").split("=", 1)[0]


# The only switches a caller may add to a launch here. Many switches weaken
# the browser's isolation without naming a sandbox (--in-process-gpu,
# --renderer-cmd-prefix, --disable-site-isolation-trials and others), so a
# switch is let through only once it has been read and named here.
# --host-resolver-rules is the receipt renderer's, which leaves the browser
# no address for any host but the provider's.
SAFE_SWITCHES = frozenset(("--host-resolver-rules", "--lang", "--window-size",
                           "--disable-extensions", "--disable-sync",
                           "--disable-background-networking",
                           "--disable-component-update", "--no-first-run",
                           "--no-default-browser-check"))


def _sandboxed(kwargs: dict) -> dict:
    """A launch's keywords with the sandbox asked for, or ValueError for a
    caller that asked to turn it off or added a switch not known to be
    safe."""
    if "chromium_sandbox" in kwargs and kwargs["chromium_sandbox"] is not True:
        raise ValueError("refusing to start a browser without its sandbox, "
                         "chromium_sandbox=%r" % (kwargs["chromium_sandbox"],))
    args = kwargs.get("args") or []
    if isinstance(args, str):
        args = [args]
    off = [str(a) for a in args if turns_sandbox_off(a)]
    if off:
        raise ValueError("refusing to start a browser without its sandbox, %s"
                         % ", ".join(off))
    unknown = [str(a) for a in args if _switch_name(a) not in SAFE_SWITCHES]
    if unknown:
        raise ValueError("refusing to start a browser with %s, which is not a switch "
                         "known to keep its sandbox whole" % ", ".join(unknown))
    return dict(kwargs, chromium_sandbox=True)


def _started(launch, *args, **kwargs):
    """`launch` called, with a sandbox that could not start said in plain
    words. Playwright's own words for it advise turning the sandbox off,
    which this tool never does, so they are not passed on. On PaperPull
    Server a host without the seccomp-bpf filter is refused before
    `launch` is called, since Chrome would start there with half its
    sandbox (server_refusal)."""
    refusal = server_refusal()
    if refusal:
        raise SandboxRefused(refusal)
    try:
        return launch(*args, **kwargs)
    except Exception as e:
        said = str(e).lower()
        if any(mark in said for mark in _SANDBOX_FAILED):
            raise SandboxRefused(SANDBOX_REFUSED) from None
        raise


def sandboxed_launch(chromium, **kwargs):
    """Playwright's chromium.launch, always inside the browser's sandbox.
    Raises ValueError for keywords that ask for less, and SandboxRefused,
    never a browser without it, when the sandbox cannot start. It starts
    a Chromium that is on disk (_on_disk)."""
    return _started(chromium.launch, **_on_disk(chromium, _sandboxed(kwargs)))


def sandboxed_persistent_context(chromium, user_data_dir, **kwargs):
    """Playwright's chromium.launch_persistent_context, always inside the
    browser's sandbox, as sandboxed_launch."""
    return _started(chromium.launch_persistent_context, user_data_dir,
                    **_on_disk(chromium, _sandboxed(kwargs)))


# -- the Chromium build a launch starts -----------------------------------------
#
# A launch that names no executable_path starts the build the installed
# Playwright was made for, chromium-<build> for a window and
# chromium_headless_shell-<build> headless, and fails with "Executable
# doesn't exist" when that one is not on disk. Each Playwright upgrade
# brings a new build, and an install upgraded from 0.59.1 (Playwright
# 1.63.0, build 1243) to 0.59.2 (1.64.1, build 1248) can hold only the old
# one, since the packages carry no Chromium and nothing downloads the new
# build. So every app's own browser (a config with no cdp_url) and the
# receipt renderer failed there, while the download was never offered,
# because some build was on disk. The sign-in was not hurt, since it starts
# the newest build on disk itself.
#
# Such a launch is now handed the newest Chromium on disk, the build the
# sign-in starts whenever it starts Playwright's Chromium, in the sign-in's
# own order (_bundled_chromium). Measured on 2026-10-30, Playwright 1.64.1
# drove the older builds 1234 and 1228 (Chrome 151 and 149), and
# Playwright 1.62.0 the newer build 1248 (Chrome 156), each in a window,
# headless and printing a PDF, through the headless shell and the full
# build alike. Where Playwright's own build is on disk nothing is handed
# over and nothing changes, and no browser of the person's own is ever
# taken here, so nobody is moved off the browser they had.
#
# The headless shell's folder is named for its own revision in
# Playwright's browsers.json, the same as Chromium's in every release so
# far, which core/tests/test_browser.py holds.

# The builds already said, so a renderer started for each receipt says it once
_SAID_ON_DISK = set()


def _playwrights_own(chromium) -> Optional[Path]:
    """The Chromium executable the Playwright that `chromium` belongs to
    starts in a window, by its own answer, or None when it gives none."""
    try:
        own = chromium.executable_path
    except Exception:
        return None
    return Path(own) if isinstance(own, str) and own else None


def _on_disk(chromium, kwargs: dict) -> dict:
    """A launch's keywords, with the newest Chromium on disk named when the
    build Playwright would start is not there. A launch that names its own
    executable_path or channel is left as it is, and so is one whose
    Playwright's own build is on disk, or with nothing at all on disk, so
    Playwright says what is missing as it always did. A headless launch
    takes the newest build, its headless shell ahead of the full build of
    the same number, and a launch with a window takes only a full build.
    Playwright looks for the executable and never for INSTALLED_MARK, so a
    build of its own that stopped partway counts as missing here, or it
    would be started as it is."""
    if kwargs.get("executable_path") or kwargs.get("channel"):
        return kwargs
    own = _playwrights_own(chromium)
    # chromium-<build> in the folder Playwright keeps its browsers in
    folder = next((p for p in (own.parents if own else ())
                   if re.fullmatch(r"chromium-\d+", p.name)), None)
    if folder is None:
        return kwargs
    root, build = folder.parent, int(folder.name.split("-")[1])
    headless = kwargs.get("headless")
    headless = True if headless is None else bool(headless)
    if headless:
        shells = _headless_shells(root)
        own_shell = "chromium_headless_shell-%d" % build
        if any(Path(s).relative_to(root).parts[0] == own_shell for s in shells):
            return kwargs
        found = sorted([(_build_number(s), 1, s) for s in shells]
                       + [(_build_number(c), 0, c) for c in _bundled_chromium(root)],
                       reverse=True)
        found = [path for _b, _shell, path in found]
    else:
        if own.is_file() and os.path.isfile(folder / INSTALLED_MARK):
            return kwargs
        found = _bundled_chromium(root)
    if not found:
        return kwargs
    if found[0] not in _SAID_ON_DISK:
        _SAID_ON_DISK.add(found[0])
        if headless and _build_number(found[0]) == build:
            print("The headless shell of Chromium build %d is not on this computer, so its "
                  "full build is started headless instead." % build)
        else:
            print("Chromium build %d, the one this Playwright starts, is not on this computer, "
                  "so build %d, the newest one here, is started instead."
                  % (build, _build_number(found[0])))
    return dict(kwargs, executable_path=found[0])


def debug_port_holder(port: str, timeout: float = 1.5) -> Optional[str]:
    """What answers as a browser on the debugging port right now, by the
    name it gives itself ("Chrome/141.0.7390.54"), or None when nothing
    does."""
    import json
    try:
        url = "http://127.0.0.1:%d/json/version" % int(port)
    except (TypeError, ValueError):
        return None
    try:
        with open_local(url, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not info.get("webSocketDebuggerUrl"):
        return None
    return str(info.get("Browser") or "a browser")


def _port_taken(port: str) -> bool:
    """Whether something already holds the port on 127.0.0.1, browser or
    not. A browser that has hung still holds its port and answers nothing,
    so debug_port_holder hears no one there and calls it free.

    Asked by binding the port, the way a browser started there would, and
    letting it go at once. Connecting to it was asked first, and a holder
    that takes no more connections answers no connection at all. Every
    look leaves one waiting in its queue, and once the queue was full the
    port looked free on Windows and Linux alike, a few sign-ins in, so
    browser after browser was launched there again. A connection to a free
    port is also refused only after two seconds on Windows, which made
    every sign-in wait a second. A bind answers at once either way.

    Only "address in use" is taken. A bind refused for any other reason,
    an address this computer does not have or a permission, says nothing
    about a browser, and the sign-in carries on as it did before."""
    import errno
    import socket
    try:
        number = int(port)
    except (TypeError, ValueError):
        return False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Bound as Chromium binds its own debugging port, for itself alone
        # on Windows and with SO_REUSEADDR elsewhere, so the answer is the
        # one a browser started there would get. A port that only has
        # connections closing on it is free to both.
        if sys.platform == "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", number))
    except OverflowError:
        return False
    except OSError as e:
        return e.errno in (errno.EADDRINUSE,
                           getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE))
    finally:
        s.close()
    return False


# How long a port that is taken but silent is given to answer as a browser,
# since one still starting opens its listener before it answers.
_SLOW_START_SECONDS = 5.0


def _open_tab_in(port: str, url: str) -> bool:
    """Ask the browser already on the port to open `url` in a new tab,
    through its own debugging endpoint. False when it would not."""
    import urllib.parse
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/json/new?%s" % (int(port), urllib.parse.quote(url, safe=":/?=&%")),
            method="PUT")
        with open_local(req, timeout=3) as r:
            return 200 <= r.status < 300
    except (OSError, ValueError, TypeError):
        return False


# What open_signin_browser answers with when the port was already held, in
# place of the name of a browser it opened.
ALREADY_ON_PORT = "the browser already on this port"


def open_signin_browser(profile_dir, port: str, url: str,
                        prefer_real: bool = False, mode: str = AUTO,
                        allow_fetch: bool = True) -> Optional[str]:
    """Open a sign-in window and return the browser's name, or None.

    The window belongs to the user: they sign in, leave it open, and the tool
    attaches to it afterwards.

    Each candidate is tried in turn, because a launch is the only honest test.
    A browser can be installed and still fail to open a debugging port, and
    checking for the file on disk cannot tell the difference. Only when nothing
    answers, and only then, is the 400 MB download offered.

    A port another browser already holds is said and used, never launched
    over. A browser started there cannot take the port, so it opened as a
    window the run could never reach, while the wait for the port heard the
    old browser and called the sign-in done, and the person signed in to
    the one window the run would not use (#90). The sign-in page is opened
    in the browser that holds the port instead, which is the one a run
    attaches to.

    A port that is taken and answers nothing is said too, and nothing is
    launched. Every browser tried there failed to take it, so a Brave
    window and then a Chrome for Testing one opened on profiles of their
    own and closed again, while a Chrome from an earlier sign-in that had
    hung went on holding the port (#90).

    Another config beside this one that names the same port is said
    first, since a sign-in there joins whichever browser holds the port,
    the other person's included (ports.say_at_sign_in).
    """
    _say_shared_port(port)
    held = debug_port_holder(port)
    if not held and _port_taken(port):
        held = debug_port_holder(port, timeout=_SLOW_START_SECONDS)
        if not held:
            _say_port_silent(port)
            return None
    if held:
        print("A browser is already listening on port %s (%s)." % (port, held))
        print("Runs attach to that browser, so it is the one to sign in with. It is")
        print("usually the window from an earlier sign-in. If it is not one you")
        print("recognize, close it and sign in again.")
        if _open_tab_in(port, url):
            print("The sign-in page is open in a new tab there.")
        return ALREADY_ON_PORT
    candidates = browser_candidates(prefer_real=prefer_real, mode=mode)

    if not candidates and allow_fetch and mode != INSTALLED:
        if fetch_bundled_chromium():
            candidates = browser_candidates(prefer_real=prefer_real, mode=mode)
    if not candidates:
        if mode == INSTALLED:
            print("No Chrome, Edge or other Chromium-based browser was found,")
            print("and this app is set to use only a browser you already have.")
        else:
            print("No browser this tool can drive is available.")
        return None

    # The private copy of Chromium that is about to be started may be older
    # than the one this Playwright was made for (#132). Asked only when it is
    # the browser that would start, and never on PaperPull Server.
    had = candidates[0]
    update = _offer_update_at_sign_in(had, allow_fetch)
    if update is not None:
        # Read again whatever came of it, since Playwright fetches Chromium
        # first and an install can end with an error and a finished build.
        candidates = browser_candidates(prefer_real=prefer_real, mode=mode) or candidates
        if candidates[0] != had:
            name, exe = candidates[0]
            opened = _launch(exe, name, profile_dir, port, url, explain_failure=False, mode=mode)
            if opened:
                if update:
                    _clear_old_builds()
                return opened
            _set_aside_new_build(exe, had[1])
            candidates = [had] + candidates[1:]

    opened = _try_each(candidates, profile_dir, port, url, mode=mode)
    if opened:
        return opened

    # Nothing ANSWERED, which is not the same as nothing being installed. A
    # browser can be present and refuse a debugging port every time, and until
    # this point that ended the run with no way forward even though a download
    # would have fixed it. PaperPull Server's Chrome comes with the
    # container, so a download there, or advice to install Chrome or Edge,
    # never fits, and the launch has said what went wrong (#110).
    if os.environ.get("PAPERPULL_SERVER") == "1":
        return None
    if allow_fetch and mode != INSTALLED and not bundled_chromium_present():
        print()
        print("None of the browsers on this computer would open a debugging")
        print("port, which is what this tool needs to attach to.")
        if fetch_bundled_chromium():
            fresh = [c for c in browser_candidates(prefer_real=prefer_real, mode=mode)
                     if c not in candidates]
            if fresh:
                return _try_each(fresh, profile_dir, port, url, fallback=True, mode=mode)
    return None


def _say_shared_port(port) -> None:
    """Say which other configs beside the one this run read name the port
    a sign-in is opened on. Only ever said. Nothing it meets, a folder or
    file it cannot read included, keeps the sign-in from going on."""
    try:
        from . import ports, storage
        ports.say_at_sign_in(storage.config_read(), port)
    except Exception:
        pass


def _say_port_silent(port: str) -> None:
    """What to tell somebody whose port is held by something that does not
    answer, and how to find it."""
    print("Something holds port %s, and it does not answer as a browser." % port)
    print("It is usually a browser left from an earlier sign-in that stopped")
    print("responding, sometimes another program using the same port. No")
    print("browser can open its debugging port there while it is held, so none")
    print("was opened.")
    print()
    print("This command shows what holds it.")
    if sys.platform == "win32":
        print("    netstat -ano | findstr :%s" % port)
        print("The last number on the LISTENING line is its process ID (PID). If it")
        print("is a browser, end it in Task Manager. On the Details tab, select the")
        print("line with that PID and press End task. Or run this command, putting")
        print("the PID in place of <PID>.")
        print("    taskkill /PID <PID> /F")
    else:
        print("    lsof -nP -iTCP:%s -sTCP:LISTEN" % port)
        if sys.platform == "darwin":
            print("Its process ID (PID) is in the PID column.")
        else:
            print("Its process ID (PID) is in the PID column. Where lsof is not")
            print("installed, this one shows it too, after pid=.")
            print("    ss -ltnp 'sport = :%s'" % port)
        print("If it is a browser, end it with this command, putting the PID in")
        print("place of <PID>.")
        print("    kill -9 <PID>")
    print("Then sign in again.")


def _try_each(candidates, profile_dir, port, url, fallback: bool = False, mode: str = AUTO):
    """Launch each in turn until a debugging port answers. mode is the app's
    browser setting, which the last one tried needs to say what to do."""
    for index, (name, exe) in enumerate(candidates):
        last = index == len(candidates) - 1
        # The FIRST candidate keeps the configured profile folder, so an
        # existing install carries on using the profile it is already signed
        # into. A fallback gets its own, because a profile written by one
        # browser brand is not guaranteed to open cleanly in another, and two
        # brands sharing one folder can leave it locked or damaged.
        target = Path(profile_dir)
        if fallback or index > 0:
            target = target.with_name(
                target.name + "-" + re.sub(r"[^a-z0-9]+", "", name.lower()))
        opened = _launch(exe, name, target, port, url, explain_failure=last, mode=mode)
        if opened:
            return opened
        if not last:
            print("Trying %s instead." % candidates[index + 1][0])
    return None


# PaperPull Server's sign-in window draws on a virtual screen, which has no
# graphics of its own, so Chrome drew every page in software and turned
# WebGL off altogether. A page with no WebGL is one of the plainest signs of
# an automated browser, and Best Buy's bot check refused every sign-in there
# while the desktop signed in at once. With the machine's GPU passed to the
# container (/dev/dri), Chrome draws through Vulkan on it instead, as the NAS
# round of 2026-10-01 measured ("ANGLE (Intel, Vulkan 1.3 ... Intel(R)
# Graphics)") and Best Buy then stayed signed in. Mesa's software Vulkan
# driver (lavapipe) is installed beside the real one, and Chrome may pick it
# over the chip, so it is left out of the drivers Chrome is shown. With no
# GPU, or PAPERPULL_GPU=off, the window starts as it always did. None of
# these switches touches the sandbox (turns_sandbox_off).
SERVER_GPU_SWITCHES = ("--use-angle=vulkan",
                       "--enable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE",
                       "--ignore-gpu-blocklist", "--disable-gpu-compositing")
_VULKAN_DRIVERS = Path("/usr/share/vulkan/icd.d")
_RENDER_NODES = Path("/dev/dri")


def server_gpu() -> tuple:
    """(switches, environment) for the sign-in window on PaperPull Server
    with a GPU it can use, or ((), None) for the window as it always was."""
    if os.environ.get("PAPERPULL_SERVER") != "1" \
            or os.environ.get("PAPERPULL_GPU", "auto").strip().lower() == "off":
        return (), None
    try:
        nodes = [n for n in sorted(_RENDER_NODES.glob("renderD*"))
                 if os.access(n, os.R_OK | os.W_OK)]
        drivers = [str(p) for p in sorted(_VULKAN_DRIVERS.glob("*.json"))
                   if not p.name.startswith("lvp")]
    except OSError:
        return (), None
    if not nodes or not drivers:
        return (), None
    env = dict(os.environ)
    env["VK_ICD_FILENAMES"] = env["VK_DRIVER_FILES"] = ":".join(drivers)
    return SERVER_GPU_SWITCHES, env


def server_graphics() -> str:
    """How PaperPull Server's sign-in window draws, "gpu" on a graphics chip
    it can use, "software" without one, and "" off the server."""
    if os.environ.get("PAPERPULL_SERVER") != "1":
        return ""
    return "gpu" if server_gpu()[0] else "software"


def _launch(exe: str, name: str, profile_dir, port: str,
            url: str, explain_failure: bool = True, mode: str = AUTO) -> Optional[str]:
    """One attempt. Returns the browser name if its debugging port answered."""
    # Resolved to an ABSOLUTE path before the browser ever sees it. A config
    # carries this as "./x-browser-profile", and a relative --user-data-dir is
    # resolved by the BROWSER, from wherever the browser thinks it is, which is
    # not necessarily where Python just created the folder. That split produced
    # two profiles from one setting, and left four of them holding live signed-in
    # session cookies inside the shared Playwright browser cache, where an app
    # update would have deleted them without warning.
    profile_path = Path(profile_dir).expanduser().resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    # The browser must not inherit our stdio. It outlives this process by
    # design (the user keeps it open), so if it holds our stdout, whoever is
    # reading that pipe - the control panel's Login action - waits for the
    # window to close before it considers the login step finished, with every
    # button disabled meanwhile. It also spares the console the browser's own
    # updater/crash-handler chatter.
    # start_new_session detaches it on POSIX; on Windows it is a no-op, so
    # detach explicitly there - otherwise the browser stays in the launcher's
    # process group and closing that console can take the sign-in window down.
    detach = {}
    if sys.platform == "win32":
        detach["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.DETACHED_PROCESS)
    # The bundled Chromium on Linux writes why it would not start, and on
    # Ubuntu 23.10 and later that is the one place that says its sandbox was
    # refused. So what it writes goes to a file with no name that only this
    # process reads, and only to look for that line (_say_sandbox_refused).
    # Nothing of it is shown or kept. A Chromium that starts goes on writing
    # there until it closes, and the file goes with it. Their own browsers,
    # and the bundled one on every other system, still write to nowhere.
    # PaperPull Server's Chrome is stopped the same way by a host that cannot
    # give it its sandbox (#110), but its sign-in windows stay open for days,
    # so what it writes is kept to its start (_KeptStart).
    on_server = os.environ.get("PAPERPULL_SERVER") == "1"
    # A host without the seccomp-bpf filter would let it start with half its
    # sandbox, so it is not started there at all.
    refusal = server_refusal() if on_server else ""
    if refusal:
        _say_server_refused(name, refusal)
        return None
    said = None
    if on_server:
        said = _KeptStart.begin()
    elif name == CHROMIUM and sys.platform not in ("win32", "darwin"):
        said = _startup_log()
    gpu, gpu_env = server_gpu()
    try:
        proc = subprocess.Popen([exe, f"--user-data-dir={profile_path}",
                                 f"--remote-debugging-port={port}", "--no-first-run",
                                 "--no-default-browser-check", *gpu, url],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=_handed(said), start_new_session=True,
                                env=gpu_env, **detach)
    except OSError as e:
        _close_quietly(said)
        # This function's answer is a browser name or None, and the caller
        # tries the next candidate on None. Letting the launch raise instead
        # ended the whole sign-in step with a traceback while another browser
        # sat there ready. The file was checked for before this, so a failure
        # here is the interesting kind: security software holding an unsigned
        # binary, a permission, an update swapping the executable out.
        print("\n%s would not start (%s)." % (name, e))
        return None

    # Launching is not the same as listening, and the difference used to be
    # invisible. When Edge or Chrome is ALREADY running, a new launch can hand
    # the URL to the existing session and drop these flags entirely. A window
    # opens, the user signs in, and only the next command reveals that no
    # debugging port was ever opened - by which point the sign-in was spent on
    # the wrong browser. So the port is confirmed here, where it can still be
    # explained.
    try:
        if said is None:
            answered = wait_for_debug_port(port)
        else:
            # Only a bundled Chromium that has ended saying its sandbox was
            # refused is given up on before the wait is out. Until 2026-10-06
            # it was waited for the whole twenty seconds and then said to have
            # opened a window. A first process that ends for any other reason
            # can still lead to the port, since it may have handed the address
            # to a copy already running. Chromium 138 and later started as
            # administrator on Windows even relaunch themselves and open the
            # port from the relaunched copy a second later (crbug 435410220),
            # so no other browser and no other system ends the wait early.
            # PaperPull Server's Chrome is ended early the same way, by any of
            # the lines a Chrome without its sandbox writes there.
            marks = SERVER_NO_SANDBOX if on_server else (_NO_SANDBOX,)

            def refused():
                if proc.poll() is None:
                    return False
                wrote = _read_quietly(said)
                return any(mark in wrote for mark in marks)
            answered = wait_for_debug_port(port, alive=lambda: not refused())
            if not answered and refused():
                if on_server:
                    _say_server_sandbox(name, port)
                else:
                    _say_sandbox_refused(port, explain_failure, mode)
                return None
    finally:
        _close_quietly(said)

    if not answered and on_server and _server_sandbox_stops_chrome():
        # Chrome said nothing known, but this host cannot give it its
        # sandbox, which is the likelier reason than another Chrome running.
        ended = proc.poll() is not None
        if not ended:
            try:
                proc.terminate()
            except OSError:
                pass
        _say_server_sandbox(name, port, ended=ended)
        return None

    if not answered:
        print(f"\nThe window opened, but no debugging port answered on {port}.")
        # A window left open here was a browser no run could reach, and the
        # next candidate opened beside it on the same port (#90). A first
        # process that handed the address to a copy already running has
        # ended by now, so only a browser this call started is closed.
        if proc.poll() is None:
            try:
                proc.terminate()
                print("That window was closed, since a run could not use it.")
            except OSError:
                pass
        if name in (EDGE, CHROME):
            print(f"That usually means {name} was already running, so it handed")
            print("the address to the existing window and ignored the settings")
            print("this tool needs.")
            if explain_failure:
                print(f"\nClose every {name} window, then run this again. Signing")
                print("in before that will not help, because the tool cannot see")
                print("that window at all.")
        elif explain_failure:
            print("Try closing any other copy of the browser and running again.")
        return None

    # Said once the window is actually up, because that is when somebody is
    # looking at a browser they recognize which knows none of their accounts.
    print()
    print(profile_note(name))
    return name


# What Chromium writes before it stops when it cannot start its sandbox, the
# words Playwright's own driver looks for in a failed start.
_NO_SANDBOX = "No usable sandbox"


def _say_sandbox_refused(port: str, explain_failure: bool, mode: str) -> None:
    """What to tell somebody whose bundled Chromium ended, before any window,
    saying its sandbox was refused. Until 2026-10-06 they waited twenty
    seconds and were told a window had opened and to close other copies of
    the browser."""
    print("\nChromium closed right after it started, before a debugging port")
    print("answered on %s." % port)
    print("It could not start its sandbox, as happens on Ubuntu 23.10 and later,")
    print("which keep the Chromium that Playwright downloads from the user")
    print("namespaces its sandbox needs. This tool never starts a browser")
    print("without its sandbox.")
    if not explain_failure:
        return
    print()
    if mode == BUNDLED:
        # Their own browsers are never looked for in this mode, so the advice
        # does not look for them either.
        print('This app\'s settings have "browser": "bundled", which allows only')
        print('that Chromium. Set it to "auto", install Google Chrome or Microsoft')
        print("Edge if neither is on this computer, and run this again.")
        return
    theirs = _real_browsers()
    if theirs:
        # The bundled one is tried last only after their own, so their own
        # was tried first and opened no port.
        print("Close every %s window, then run this again," % theirs[0][0])
        print("so that this tool can use %s instead." % theirs[0][0])
    else:
        print("Install Google Chrome or Microsoft Edge and run this again. This")
        print("tool then uses it, in a profile of its own.")


# What PaperPull Server's Chrome writes before it stops without its sandbox.
# Chrome 154 in the server image, run as pp with no user namespace to be
# had, ended within a second saying its SUID sandbox helper "is not
# configured correctly", since chrome.sh leaves the helper unset. That was
# measured under Docker's own profile and under a profile answering as a
# kernel built without user namespaces answers, as DSM's is. The namespace
# line is what it writes when its namespaces are refused later on, and "No
# usable sandbox" is Chromium's own for the rest.
SERVER_NO_SANDBOX = (_NO_SANDBOX, "SUID sandbox helper", "Failed to move to new namespace")


def _server_sandbox_problem() -> str:
    """Why this host cannot give Chrome its sandbox, from the check run
    before Chrome is (paperpull_core.host_sandbox), or ""."""
    try:
        from .host_sandbox import check, problem
        return problem(check())
    except Exception:
        return ""


def _server_sandbox_stops_chrome() -> bool:
    """Whether that check found what stops Chrome before it opens a window,
    no user namespace to be had. Without seccomp-bpf alone Chrome still
    starts (measured), so that is no reason for a port that did not open."""
    try:
        from .host_sandbox import check, stops_chrome
        return stops_chrome(check())
    except Exception:
        return False


def server_refusal() -> str:
    """Why PaperPull Server will not start Chrome on this host, or "" when
    it may, and always "" off the server. A kernel without the seccomp-bpf
    filter lets Chrome start with the namespace half of its sandbox only,
    as a host with user namespaces does once the container's profile is
    removed by hand, and until then nothing refused it (#110 said so and
    went on). Every Chrome the server starts asks this first, the sign-in
    window, a browser of an app's own and the receipt renderer, and the
    self-test asks the same check (paperpull_core.host_sandbox)."""
    if os.environ.get("PAPERPULL_SERVER") != "1":
        return ""
    try:
        from .host_sandbox import check, problem, refuses_chrome
        found = check()
        if not refuses_chrome(found):
            return ""
        return problem(found) or SERVER_REFUSED
    except Exception:
        return ""


# Said when the check refuses Chrome and has no sentence of its own, which
# problem() always has today.
SERVER_REFUSED = ("This host cannot give Chrome its whole sandbox, and PaperPull will not "
                  "start Chrome without it. See \"Chrome does not start\" in SERVER.md.")


def _say_server_refused(name: str, why: str) -> None:
    """What a sign-in says when the server would not start its Chrome."""
    import textwrap
    print("\n%s was not started." % name)
    print(textwrap.fill(why, width=72))


def _say_server_sandbox(name: str, port: str, ended: bool = True) -> None:
    """What PaperPull Server says when its Chrome could not start its
    sandbox. Until #110 it waited twenty seconds, said a window had opened,
    to close every Chrome window, and then to install Chrome or Edge, none
    of which a person at the server's panel can do anything with."""
    import textwrap
    if ended:
        print("\n%s closed right after it started, before a debugging port" % name)
        print("answered on %s." % port)
    else:
        print("\n%s did not open a debugging port on %s, and was closed." % (name, port))
    why = _server_sandbox_problem() or (
        "It could not start its sandbox, and PaperPull never starts a browser "
        "without its sandbox. The self-test says why, see \"Chrome does not "
        "start\" in SERVER.md.")
    print(textwrap.fill(why, width=72))


def _startup_log():
    """A file with no name for what a browser writes while it starts, or None
    when none can be made. On Linux the name is gone as soon as the file
    exists, so the file is gone once this process and the browser have both
    closed it."""
    import tempfile
    try:
        return tempfile.TemporaryFile()
    except OSError:
        return None


# The helper of _KeptStart, run by this same Python. Its first line is what
# a process list shows of it. It reads into one buffer made once, which held
# its memory at 3 MB with more than 120 GB of lines of every length read
# through it, where a new bytes object for each read settled at 9 MB.
_KEEP_START = r"""# PaperPull keeps the start of what Chrome writes, and reads the rest into nothing
import io, os, sys
keep = int(sys.argv[1])
buf = bytearray(65536)
view = memoryview(buf)
source = io.FileIO(0, closefd=False)
while True:
    got = source.readinto(buf)
    if not got:
        break
    if keep > 0:
        try:
            keep -= os.write(1, view[:min(got, keep)])
        except OSError:
            keep = 0
"""


class _KeptStart:
    """What PaperPull Server's Chrome writes, of which only the first KEEP
    bytes are kept, in a file with no name that _launch reads for the lines
    of a Chrome without its sandbox.

    Chrome writes into a pipe, and a small helper holds the other end for as
    long as any process holding Chrome's end does. It copies the start into
    the file and reads the rest into nothing, so the file never grows past
    KEEP, and every write Chrome makes goes through, as it did into nowhere
    before #110. Its sign-in windows stay open for days, and the file they
    wrote straight into grew for as long as they did.

    Measured with Chrome 154 in the server image. The sign-in step ends
    seconds after its window opens, so a pipe it read itself would have no
    reader for the rest of the window's life. Chrome's own processes ignore
    the SIGPIPE that brings, but its two crashpad handlers catch it and ended
    at the first crash, which they write about. Truncating the file once the
    start is judged does not help either, since every later write takes disk
    again, with or without O_APPEND.
    """

    KEEP = 1 << 16

    def __init__(self, log, write_end: int, helper):
        self.log = log
        self.write_end = write_end
        self.helper = helper

    @classmethod
    def begin(cls):
        """One with its helper running, or None when none can be started.
        Chrome then writes to nowhere, as before #110, and the host check
        alone says why it could not start its sandbox."""
        if getattr(sys, "frozen", False):
            return None     # sys.executable would be the app itself
        log = _startup_log()
        if log is None:
            return None
        try:
            read_end, write_end = os.pipe()
        except OSError:
            _close_quietly(log)
            return None
        try:
            # A session of its own, so that whatever ends the sign-in step
            # does not end it while Chrome still writes.
            helper = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", _KEEP_START, str(cls.KEEP)],
                stdin=read_end, stdout=log, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            os.close(write_end)
            _close_quietly(log)
            return None
        finally:
            os.close(read_end)
        return cls(log, write_end, helper)

    def read(self) -> str:
        """The start of what Chrome wrote. Read at an offset, which moves
        nothing, since the helper writes through the same open file."""
        try:
            if hasattr(os, "pread"):
                got = os.pread(self.log.fileno(), self.KEEP, 0)
            else:   # Windows, where only the server's tests run
                self.log.seek(0)
                got = self.log.read(self.KEEP)
        except (OSError, ValueError):
            return ""
        return got.decode("utf-8", "replace")

    def close(self) -> None:
        """Closes this process's ends of both. The helper goes on until
        every process holding Chrome's end has closed it."""
        if self.write_end is not None:
            try:
                os.close(self.write_end)
            except OSError:
                pass
            self.write_end = None
        _close_quietly(self.log)


def _handed(said):
    """The stderr a browser is started with."""
    if said is None:
        return subprocess.DEVNULL
    if isinstance(said, _KeptStart):
        return said.write_end
    return said


def _read_quietly(said) -> str:
    """The start of what was written to a _startup_log file, or nothing."""
    if said is None:
        return ""
    if isinstance(said, _KeptStart):
        return said.read()
    try:
        said.seek(0)
        return said.read(1 << 16).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def _close_quietly(said) -> None:
    if said is not None:
        try:
            said.close()
        except OSError:
            pass


def open_local(request, timeout: float):
    """Open a request to an address on this computer, never through a proxy.

    urllib's own urlopen sends every request through the proxy the computer
    names, HTTP_PROXY in the environment or, when that is empty, the proxy
    in the system settings of Windows or macOS, and nothing exempts
    127.0.0.1 unless the person listed it. The Windows box for local
    addresses ("<local>") covers only names without a dot. A proxy cannot
    reach a browser's debugging port on this computer, so with one set the
    sign-in step said no debugging port answered, for a browser that was
    fine. A request to this computer has no reason to leave it, so no proxy
    is asked at all.
    """
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def wait_for_debug_port(port: str, timeout: float = 20.0, alive=None) -> bool:
    """True once DevTools answers on the browser's debugging port.

    Checked on 127.0.0.1 rather than "localhost": the browser binds IPv4 only,
    while "localhost" can resolve to ::1 first and be refused.

    A port that accepts a connection is not the same as DevTools being ready.
    The browser opens the listener early and answers /json/version only once
    the protocol is up, and an attach in that gap fails with a message that
    blames the wrong thing. So readiness is the endpoint the attach itself
    will use, answering with the websocket address it will connect to.

    alive, when given, is asked between looks, and the wait ends as soon as
    it says the browser has ended, since a browser that ended opens no port.
    """
    import json
    import time
    try:
        url = "http://127.0.0.1:%d/json/version" % int(port)
    except (TypeError, ValueError):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open_local(url, timeout=2) as r:
                info = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(info, dict) and info.get("webSocketDebuggerUrl"):
                return True
        except (OSError, ValueError):
            pass
        if alive is not None and not alive():
            return False
        time.sleep(0.5)
    return False
