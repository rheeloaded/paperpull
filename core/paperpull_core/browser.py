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
        ]
    elif sys.platform == "darwin":
        candidates = [
            (EDGE, "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            (EDGE, str(Path.home() / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
            (CHROME, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            (CHROME, str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
        ]
    else:
        candidates = [
            (EDGE, "/usr/bin/microsoft-edge"), (EDGE, "/usr/bin/microsoft-edge-stable"),
            (CHROME, "/usr/bin/google-chrome"), (CHROME, "/usr/bin/google-chrome-stable"),
            (CHROME, "/usr/bin/chromium-browser"),
        ]
    return [(name, path) for name, path in candidates if path and os.path.exists(path)]


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


def open_signin_browser(profile_dir, port: str, url: str,
                        prefer_real: bool = False) -> Optional[str]:
    """Open a sign-in window and return the browser's name, or None.

    The window belongs to the user: they sign in, leave it open, and the tool
    attaches to it afterwards.
    """
    name, exe = find_browser(prefer_real=prefer_real)
    if not exe:
        wanted = "Microsoft Edge, Google Chrome, or the Playwright Chromium" \
            if prefer_real else "the Playwright Chromium"
        print(f"Could not find {wanted}.")
        if prefer_real:
            print("Install Edge or Chrome, or run "
                  f"{setup_hint()} to fetch the bundled browser.")
        else:
            print(f"Run {setup_hint()} first.")
        return None

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
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
    subprocess.Popen([exe, f"--user-data-dir={profile_dir}",
                      f"--remote-debugging-port={port}", "--no-first-run",
                      "--no-default-browser-check", url],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True,
                     **detach)
    return name
