"""Finding and launching the sign-in browser, on whichever OS you are using.

Every app opens the same kind of window: an ordinary browser, on this app's
own debugging port, using this app's own profile directory, which *you* then
sign into. The tool later attaches to it over the DevTools protocol. Nothing
here automates a login.

Two flavours:

* Most providers are happy with the Chromium that Playwright installs.
* A few (Walmart, Verizon) run bot protection that fingerprints that build as
  automation and shows a "robot or human" wall on loop. Those pass far more
  reliably in a real, branded browser, so they ask for Edge or Chrome first
  and fall back to Chromium.

Windows, macOS and Linux are all supported. The only real difference is where
the browsers live, which is what BROWSERS below records.
"""
from __future__ import annotations

import glob
import os
import re
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


def _playwright_root() -> Path:
    """Where Playwright keeps its downloaded browsers."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override and override not in ("0", "1"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _bundled_chromium() -> List[str]:
    root = _playwright_root()
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
        patterns = ["chromium-*/chrome-linux/chrome"]
    found: List[str] = []
    for pattern in patterns:
        found += glob.glob(str(root / pattern))

    # Newest build first. Playwright pins a build per release and leaves older
    # ones behind, so "whatever glob returned first" can hand back a build
    # older than the installed playwright expects. Sort on the build NUMBER,
    # not the string - "chromium-1000" sorts before "chromium-999" as text.
    def build_number(path: str) -> int:
        m = re.search(r"chromium-(\d+)", path)
        return int(m.group(1)) if m else -1

    return sorted(found, key=build_number, reverse=True)


def _real_browsers() -> List[Tuple[str, str]]:
    """Installed Edge/Chrome, most-preferred first, as (name, path)."""
    if sys.platform == "win32":
        pf = os.environ.get("PROGRAMFILES", "")
        pfx = os.environ.get("PROGRAMFILES(X86)", "")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            (EDGE, os.path.join(pfx, "Microsoft", "Edge", "Application", "msedge.exe")),
            (EDGE, os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe")),
            (CHROME, os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe")),
            (CHROME, os.path.join(pfx, "Google", "Chrome", "Application", "chrome.exe")),
            (CHROME, os.path.join(local, "Google", "Chrome", "Application", "chrome.exe")),
            (BRAVE, os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
            (BRAVE, os.path.join(pfx, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
            (BRAVE, os.path.join(local, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
            (VIVALDI, os.path.join(local, "Vivaldi", "Application", "vivaldi.exe")),
            (VIVALDI, os.path.join(pf, "Vivaldi", "Application", "vivaldi.exe")),
            (OPERA, os.path.join(local, "Programs", "Opera", "opera.exe")),
        ]
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


def find_browser(prefer_real: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Return (name, executable path) for the browser to sign in with.

    With prefer_real, an installed Edge/Chrome wins over the bundled Chromium
    — that is what gets past the providers whose bot protection rejects the
    Playwright build.
    """
    real = _real_browsers()
    bundled = _bundled_chromium()
    if prefer_real and real:
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
    real = _real_browsers()
    # Only the newest bundled build. Playwright leaves older ones behind, and
    # retrying the same browser at a different revision opens a second window
    # to fail the same way, since the usual cause is the port rather than the
    # build.
    bundled = [(CHROMIUM, p) for p in _bundled_chromium()[:1]]
    if mode == INSTALLED:
        return real
    if mode == BUNDLED:
        return bundled
    # With a bundled copy already present it stays first unless an app asks for
    # a real browser. Reordering that would move existing users onto a
    # different browser, and a profile built by one is not guaranteed to open
    # cleanly in another, which would cost them a sign-in for no benefit.
    return (real + bundled) if prefer_real else (bundled + real)


def bundled_chromium_present() -> bool:
    return bool(_bundled_chromium())


def profile_note(name: str) -> str:
    """What to tell someone whose own browser is about to open.

    This wording matters and is easy to get wrong. The tool launches their
    browser with its OWN --user-data-dir, so their everyday profile, history,
    extensions and existing logins are untouched and unreadable by it. The flip
    side is the one people get caught by: they are NOT already signed in, and
    a window that looks like their browser but knows none of their accounts is
    alarming if nobody warned them.
    """
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


def browser_install_command():
    """The command that downloads a browser, or None if this build cannot.

    "sys.executable -m playwright" is right when running from a normal Python
    install, and WRONG in a packaged build, where sys.executable is the
    application itself. That would re-launch the app rather than install
    anything. Playwright ships its own Node driver, whose path does not depend
    on how this process was started, so a frozen build uses that instead.
    """
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "playwright", "install", "chromium"]
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
    """
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

    opened = _try_each(candidates, profile_dir, port, url)
    if opened:
        return opened

    # Nothing ANSWERED, which is not the same as nothing being installed. A
    # browser can be present and refuse a debugging port every time, and until
    # this point that ended the run with no way forward even though a download
    # would have fixed it.
    if allow_fetch and mode != INSTALLED and not bundled_chromium_present():
        print()
        print("None of the browsers on this computer would open a debugging")
        print("port, which is what this tool needs to attach to.")
        if fetch_bundled_chromium():
            fresh = [c for c in browser_candidates(prefer_real=prefer_real, mode=mode)
                     if c not in candidates]
            if fresh:
                return _try_each(fresh, profile_dir, port, url, fallback=True)
    return None


def _try_each(candidates, profile_dir, port, url, fallback: bool = False):
    """Launch each in turn until a debugging port answers."""
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
        opened = _launch(exe, name, target, port, url, explain_failure=last)
        if opened:
            return opened
        if not last:
            print("Trying %s instead." % candidates[index + 1][0])
    return None


def _launch(exe: str, name: str, profile_dir, port: str,
            url: str, explain_failure: bool = True) -> Optional[str]:
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
    subprocess.Popen([exe, f"--user-data-dir={profile_path}",
                      f"--remote-debugging-port={port}", "--no-first-run",
                      "--no-default-browser-check", url],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True,
                     **detach)

    # Launching is not the same as listening, and the difference used to be
    # invisible. When Edge or Chrome is ALREADY running, a new launch can hand
    # the URL to the existing session and drop these flags entirely. A window
    # opens, the user signs in, and only the next command reveals that no
    # debugging port was ever opened - by which point the sign-in was spent on
    # the wrong browser. So the port is confirmed here, where it can still be
    # explained.
    if not wait_for_debug_port(port):
        print(f"\nThe window opened, but no debugging port answered on {port}.")
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
    # looking at a browser they recognise which knows none of their accounts.
    print()
    print(profile_note(name))
    return name


def wait_for_debug_port(port: str, timeout: float = 20.0) -> bool:
    """True once the browser's debugging port accepts a connection.

    Checked on 127.0.0.1 rather than "localhost": the browser binds IPv4 only,
    while "localhost" can resolve to ::1 first and be refused.
    """
    import socket
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=1):
                return True
        except (OSError, ValueError):
            time.sleep(0.5)
    return False
