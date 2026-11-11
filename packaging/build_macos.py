"""Build a self-contained PaperPull for macOS.

    python packaging/build_macos.py                  PaperPull.app + a .dmg, unsigned
    python packaging/build_macos.py --sign           also sign, notarize and staple
    python packaging/build_macos.py --arch x86_64    the Intel build

WHAT IT PRODUCES

    dist/PaperPull.app                      the application bundle
    dist/PaperPull-<ver>-<arch>.dmg         the disk image people download,
                                            arm64 or x86_64

HOW IT IS BUILT, AND WHY THIS WAY

The same idea as the Windows package. Nothing is frozen. The bundle carries a
relocatable CPython (python-build-standalone, the build that uv ships) with
the packages every app needs installed into it once, from a lock that names
each file's hash, and the repo's own code beside it. The panel and every app run under that interpreter exactly as they
do in a checkout, so nothing has to know it is packaged.

One architecture per build, arm64 for Apple Silicon or x86_64 for Intel, and
one download each (#88). A universal bundle would need a universal Python and
a universal wheel of every package with compiled code, and pip installs only
the running interpreter's own, so each build is made by running a Python of
its architecture. arm64 is built on Apple Silicon. x86_64 is built on an Intel
Mac, or on Apple Silicon through Rosetta, which runs the staged Intel Python
and so has pip choose Intel wheels. The release workflow builds each on a
runner of its own architecture, so each is smoke-tested on its own hardware.

The bundle's main executable is a small native window, in Objective-C
(packaging/macos/launcher.m), compiled on the build machine because
notarization requires a Mach-O main executable with the hardened runtime.
It starts gui/mac_host.py with the bundled Python, which runs the panel and
stops it, and shows the panel in a WKWebView, with a Dock icon and a menu
bar. There is no Terminal window and no browser tab, and quitting stops the
panel. Its output goes to ~/Library/Logs/PaperPull/panel.log.

PAPERPULL_LAUNCHER_SELFTEST=ready or =window runs the executable as the
release workflow does, see launcher.m. Resources/paperpull-panel.sh still
ships, for anyone who wants the panel in a terminal.

WHAT IS NOT IN IT

The 400 MB Chromium. Chrome, Edge, Brave, Vivaldi or Opera already on the Mac
is used, and the first download is offered at sign-in only if none is found. A
private copy somebody took that way is offered its update at sign-in when it
falls behind. Safari cannot be driven this way.

Anything untracked. Only files git knows about go in.

SIGNING

--sign needs a Developer ID Application certificate in the keychain, its
name in MACOS_SIGN_IDENTITY, and the notarytool credentials in
NOTARY_KEY_PATH, NOTARY_KEY_ID and NOTARY_ISSUER_ID. Every Mach-O in the
bundle is signed with the hardened runtime, the bundle is notarized and
stapled, then the disk image is signed, notarized and stapled in turn.
Without --sign the bundle and dmg are unsigned and macOS 15 will refuse to
open them without a trip through System Settings, which is fine for checking
a build and useless for handing to anyone else.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
APP = DIST / "PaperPull.app"
CONTENTS = APP / "Contents"
RES = CONTENTS / "Resources"
MACOS = CONTENTS / "MacOS"

# python-build-standalone, the install_only_stripped flavor. It unpacks to a
# folder called python/ that is a complete, relocatable CPython with pip. The
# same release and Python as packaging/build_windows.py, and core/tests holds
# the two to each other.
PBS_TAG = "20261026"
PY_VERSION = "3.12.16"

# The oldest macOS the bundle opens on. Info.plist and the launcher say so,
# and packaging/lock.py takes only wheels that run on it.
MACOS_MIN = "11.0"

# The window saves the page's downloads with WKDownload, new in 11.3.
WINDOW_MACOS_MIN = "11.3"

# The launcher's source. It is compiled straight from the checkout into
# Contents/MacOS and is not copied into the bundle, so it is not subject to
# the tracked-files rule that stage_code() applies to what ships.
LAUNCHER_SRC = REPO / "packaging" / "macos" / "launcher.m"

# The architecture being built, set from --arch in main(). Ours is Apple's
# name, which clang, Info.plist and the dmg's name use, and the other is
# python-build-standalone's.
ARCHES = {"arm64": "aarch64", "x86_64": "x86_64"}
ARCH = "arm64"

# Each architecture's tarball as python-build-standalone's SHA256SUMS for
# PBS_TAG lists it, which is also the digest GitHub shows for the asset. The
# download must match before anything is built from it. A new PBS_TAG or
# PY_VERSION takes both lines again from that release's SHA256SUMS.
PBS_SHA256 = {
    "arm64": "353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e",
    "x86_64": "37c38fda76fec1fbf310adcbafb7f0d96af13b5511bf8ea954c3aa8eec185734",
}

# stapler fetches the ticket from Apple's ticket server, which dropped the
# connection twice on the Intel runner as 0.56.0 was built (exit 68,
# NSURLErrorDomain -1005, "The network connection was lost"). A staple that
# fails is tried again after each of these pauses, four tries in all, and
# the build still stops when the last one fails, so a ticket that is really
# missing stops it as before. The workflow's stapler validate waits the same.
STAPLE_WAITS = (15, 30, 60)


def triple(arch: str | None = None) -> str:
    """The platform as python-build-standalone names it, and uv in
    packaging/lock.py."""
    return "%s-apple-darwin" % ARCHES[arch or ARCH]


def pbs_asset() -> str:
    return "cpython-%s+%s-%s-install_only_stripped.tar.gz" % (PY_VERSION, PBS_TAG, triple())


def pbs_url() -> str:
    return "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s" % (
        PBS_TAG, pbs_asset())


def lock_file(arch: str | None = None) -> Path:
    """What the bundle installs, written by packaging/lock.py from the same
    packaging/requirements.in as the Windows locks. One for each
    architecture, since a package can have a built wheel for one and not
    the other, or only for a newer macOS than MACOS_MIN."""
    return REPO / "packaging" / ("requirements-macos-%s.txt" % (arch or ARCH))

BUNDLE_ID = "io.github.rheeloaded.paperpull"

# Imported from the Windows build so the two packages cannot drift apart on
# what they carry or how they install it.
sys.path.insert(0, str(REPO / "packaging"))
from build_windows import (EXCLUDE_PARTS, INCLUDE_TOP, check_python_version,  # noqa: E402
                           install_locked, tracked_files, version, fetch, say)
from icons import ico_largest_png  # noqa: E402


def wanted(rel: str) -> bool:
    parts = Path(rel).parts
    if parts[0] not in INCLUDE_TOP or parts[0] == "paperpull.bat":
        return False
    if any(p in EXCLUDE_PARTS for p in parts):
        return False
    if parts[0] == "apps" and parts[-1] in ("config.json", "progress.json", "discovery.json"):
        return False
    return True


# -- python --------------------------------------------------------------------

def host_arch() -> str:
    """The Mac's real architecture. A Python running under Rosetta reports
    x86_64 on Apple Silicon, and hw.optional.arm64 still says the truth."""
    r = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True)
    return "arm64" if r.stdout.strip() == "1" else "x86_64"


def stage_python() -> Path:
    say("Python %s, python-build-standalone %s, %s" % (PY_VERSION, PBS_TAG, ARCH))
    cache = DIST / "cache"
    fetch(pbs_url(), cache / pbs_asset(), sha256=PBS_SHA256[ARCH])
    with tarfile.open(cache / pbs_asset()) as t:
        t.extractall(RES, filter="data")
    py = RES / "python" / "bin" / "python3"
    if not py.exists():
        raise SystemExit("the Python tarball did not unpack to python/bin/python3")
    return py


def install_packages(py: Path) -> None:
    install_locked(py, lock_file(), env=dict(os.environ, PYTHONNOUSERSITE="1"))
    # Byte-compiled files and pip's leftovers are not needed and every extra
    # file is one more thing to sign.
    for p in RES.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)


# -- code ----------------------------------------------------------------------

def stage_code() -> int:
    say("Code, tracked files only")
    n = 0
    for rel in tracked_files():
        if not wanted(rel):
            continue
        src = REPO / rel
        if not src.is_file():
            continue
        if rel.startswith("apps/"):
            rel = "templates/" + rel
        dst = RES / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    say("  %d files" % n)
    return n


# -- the bundle ----------------------------------------------------------------

def write_icon() -> str | None:
    ico = REPO / "packaging" / "paperpull.ico"
    if not ico.is_file() or sys.platform != "darwin":
        return None
    say("  icon")
    iconset = DIST / "cache" / "PaperPull.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    src = DIST / "cache" / "paperpull-256.png"
    src.write_bytes(ico_largest_png(ico))
    for size in (16, 32, 64, 128, 256):
        subprocess.run(["sips", "-z", str(size), str(size), str(src), "--out",
                        str(iconset / ("icon_%dx%d.png" % (size, size)))],
                       check=True, capture_output=True)
        if size >= 32:
            shutil.copy2(iconset / ("icon_%dx%d.png" % (size, size)),
                         iconset / ("icon_%dx%d@2x.png" % (size // 2, size // 2)))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o",
                    str(RES / "PaperPull.icns")], check=True)
    # The panel shows the same icon on its browser tab, and reads the .ico
    # from beside its own folder, which is Resources here (gui/app.py).
    shutil.copy2(ico, RES / "paperpull.ico")
    return "PaperPull.icns"


def compile_launcher() -> None:
    """The bundle's main executable, compiled from packaging/macos/launcher.m.

    It is Objective-C rather than a script because notarization requires the
    main executable to be a Mach-O binary carrying the hardened runtime, and
    a script cannot carry that. ARC, Cocoa for the window and menu bar, and
    WebKit for the web view the panel is shown in. The architecture and the
    minimum macOS are the build's own, so an Intel bundle never gets an arm64
    launcher."""
    if not LAUNCHER_SRC.is_file():
        raise SystemExit("the launcher's source is missing: %s" % LAUNCHER_SRC)
    say("  launcher")
    subprocess.run(["clang", "-fobjc-arc", "-O2", "-arch", ARCH,
                    "-mmacosx-version-min=" + WINDOW_MACOS_MIN,
                    "-framework", "Cocoa", "-framework", "WebKit",
                    "-o", str(MACOS / "PaperPull"), str(LAUNCHER_SRC)], check=True)


def write_bundle() -> None:
    say("Bundle")
    MACOS.mkdir(parents=True, exist_ok=True)
    icon = write_icon()

    # The panel in a terminal, for anyone who wants it there. The app itself
    # runs gui/mac_host.py. Same shape as PaperPull.exe on Windows.
    (RES / "paperpull-panel.sh").write_text(
        '#!/bin/bash\n'
        '# The PaperPull control panel. Close this window to stop it.\n'
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'export PYTHONNOUSERSITE=1\n'
        '# Bytecode goes to the user cache, never into the bundle. macOS blocks\n'
        '# writes into an app under /Applications, and a signed bundle that\n'
        '# grows files after signing reads as damaged.\n'
        'export PYTHONPYCACHEPREFIX="$HOME/Library/Caches/PaperPull/pycache"\n'
        'echo "PaperPull %s"\n'
        'echo "The panel binds 127.0.0.1 only. Nothing is reachable from the network."\n'
        'echo "Close this window to stop it."\n'
        'echo\n'
        '(sleep 2; open http://127.0.0.1:8765) &\n'
        'cd "$DIR"\n'
        'exec "$DIR/python/bin/python3" -m uvicorn app:app --host 127.0.0.1 --port 8765 --app-dir "$DIR/gui"\n'
        % version(), encoding="utf-8")
    os.chmod(RES / "paperpull-panel.sh", 0o755)

    compile_launcher()

    # The terminal command, preferring the bundled Python.
    shim = RES / "paperpull"
    shim.write_text(
        '#!/usr/bin/env bash\n'
        '# One command for every app. See paperpull.py for the details.\n'
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'export PYTHONNOUSERSITE=1\n'
        'export PYTHONPYCACHEPREFIX="$HOME/Library/Caches/PaperPull/pycache"\n'
        'exec "$DIR/python/bin/python3" "$DIR/paperpull.py" "$@"\n',
        encoding="utf-8")
    os.chmod(shim, 0o755)

    (RES / "README-FIRST.txt").write_text(
        "PaperPull %s\n"
        "\n"
        "Double-click PaperPull. A window opens with the control panel in it, and\n"
        "PaperPull shows in the Dock and the menu bar. Quit it with Cmd-Q, which\n"
        "also stops the panel once any Rename or Move under way has finished. If\n"
        "something goes wrong, the panel's log is at\n"
        "  ~/Library/Logs/PaperPull/panel.log\n"
        "\n"
        "The first time, it asks where your downloaders are. If you already have\n"
        "them, paste that folder's full path and it uses them exactly as they\n"
        "are. Nothing is moved, copied or changed.\n"
        "\n"
        "It uses the copy of Chrome, Edge or Brave already on this Mac, opened in\n"
        "a separate profile, so your normal browsing is untouched and you sign\n"
        "in fresh. Safari cannot be driven this way. If there is no such browser\n"
        "it offers to download one.\n"
        "\n"
        "From a terminal, the same panel's commands are\n"
        "  /Applications/PaperPull.app/Contents/Resources/paperpull <app> <command>\n"
        "\n"
        "Everything runs on this Mac. Nothing is sent anywhere, unless you turn on\n"
        "the check for a newer version in Settings.\n"
        "\n"
        "Your existing setup keeps working alongside this one, so there is no\n"
        "need to remove anything until you are happy with it.\n"
        % version(), encoding="utf-8")

    plist = {
        "CFBundleName": "PaperPull",
        "CFBundleDisplayName": "PaperPull",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": version(),
        "CFBundleShortVersionString": version(),
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "PaperPull",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": WINDOW_MACOS_MIN,
        "LSArchitecturePriority": [ARCH],
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSApplicationCategoryType": "public.app-category.productivity",
        # The window shows the panel at http://127.0.0.1:<port>, which App
        # Transport Security refuses as plain http unless local networking is
        # allowed. This opens loopback and local addresses only, not the web.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "Copyright (c) 2026 PaperPull, a trade name of TNE Enterprises LLC. AGPL-3.0. https://github.com/rheeloaded/paperpull",
    }
    if icon:
        plist["CFBundleIconFile"] = icon
    with open(CONTENTS / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    (CONTENTS / "PkgInfo").write_text("APPL????", encoding="ascii")


# -- checks --------------------------------------------------------------------

def audit() -> None:
    say("Audit")
    bad = []
    for p in APP.rglob("*"):
        n = p.name.lower()
        if n in ("config.json", "progress.json", "discovery.json") \
                or n.endswith(".pdf") or "browser-profile" in n \
                or n in ("cookies", "login data", "local state"):
            bad.append(str(p.relative_to(APP)))
    if bad:
        raise SystemExit("REFUSING TO PACKAGE, personal files found:\n  " + "\n  ".join(bad))
    say("  no config, history, profile or PDF in the bundle")
    # The main executable is the one file the stage and the signer both treat
    # specially, so check it is what notarization needs: a Mach-O, of the
    # architecture being built, that is the native launcher and not a stub.
    exe = MACOS / "PaperPull"
    if not _is_macho(exe):
        raise SystemExit("Contents/MacOS/PaperPull is not a Mach-O binary")
    archs = subprocess.run(["lipo", "-archs", str(exe)], capture_output=True, text=True)
    if archs.returncode != 0 or archs.stdout.split() != [ARCH]:
        raise SystemExit("the launcher is %r, not %s:\n%s"
                         % (archs.stdout.strip(), ARCH, archs.stderr))
    libs = subprocess.run(["otool", "-L", str(exe)], capture_output=True, text=True).stdout
    if "WebKit.framework" not in libs or "Cocoa.framework" not in libs:
        raise SystemExit("the launcher does not link Cocoa and WebKit:\n" + libs)
    say("  the main executable is a %s Mach-O linking Cocoa and WebKit" % ARCH)


def smoke_test(py: Path) -> None:
    say("Smoke test")
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    check_python_version(py, PY_VERSION, env=env)
    r = subprocess.run([str(py), "-c",
                        "import playwright, pypdf, fastapi, uvicorn, paperpull_core; print('ok')"],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 or "ok" not in r.stdout:
        raise SystemExit("bundled python cannot import its packages:\n" + r.stderr)
    say("  bundled python imports playwright, pypdf, fastapi, uvicorn, paperpull_core")
    chase = RES / "templates" / "apps" / "chase"
    r = subprocess.run([str(py), str(chase / "chase_docs.py"), "--help"],
                       capture_output=True, text=True, cwd=str(chase), env=env)
    if r.returncode != 0:
        raise SystemExit("an app does not run under the bundled python:\n" + r.stderr[-800:])
    say("  an app runs under it")
    r = subprocess.run([str(py), str(RES / "paperpull.py"), "--root",
                        str(RES / "templates" / "apps"), "list"],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 or "chase" not in r.stdout:
        raise SystemExit("paperpull list does not run under the bundled python:\n" + r.stderr[-800:])
    say("  paperpull list runs under it")


# -- signing -------------------------------------------------------------------

ENTITLEMENTS = {
    # What a Python interpreter needs under the hardened runtime. ctypes and
    # a few extension modules map memory they then execute, and the
    # interpreter loads extension modules that are signed by us but not by
    # Apple. Both are the standard pair for packaged Python (briefcase and
    # py2app set the same two). Nothing else is opened up.
    "com.apple.security.cs.allow-unsigned-executable-memory": True,
    "com.apple.security.cs.disable-library-validation": True,
}


def _is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    return magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
                     b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce")


def sign(identity: str) -> None:
    """Every Mach-O in the bundle, deepest first, then the bundle itself.

    codesign --deep is not used. It is deprecated, it skips anything not in a
    place it expects a binary, and a Python tree is nothing but such places.
    Walking the files and signing each one is what Apple recommends and what
    every packaged-Python tool ends up doing."""
    if not identity:
        raise SystemExit("--sign needs MACOS_SIGN_IDENTITY in the environment")
    say("Signing as %s" % identity)
    for cache in APP.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    ent = DIST / "cache" / "entitlements.plist"
    with open(ent, "wb") as f:
        plistlib.dump(ENTITLEMENTS, f)
    plain = ["codesign", "--force", "--timestamp", "--options", "runtime"]
    # The Python tree gets the two entitlements above. Nothing else does.
    base = [*plain, "--entitlements", str(ent), "--sign", identity]
    plain = [*plain, "--sign", identity]
    launcher = MACOS / "PaperPull"
    binaries = sorted((p for p in APP.rglob("*") if _is_macho(p) and p != launcher),
                      key=lambda p: (-len(p.parts), str(p)))
    for i in range(0, len(binaries), 50):
        subprocess.run([*base, *map(str, binaries[i:i + 50])], check=True,
                       capture_output=True)
    say("  %d binaries" % len(binaries))
    # The main executable, the native launcher, hosts the web view and loads
    # only Apple's frameworks. It needs neither entitlement above, so it gets
    # the hardened runtime and no entitlements at all, and is signed on its
    # own, before the bundle. The bundle's own signature is made without
    # --entitlements too: codesign applies a bundle-level --entitlements to
    # the bundle's main executable, so passing them there would put the
    # Python pair back on the launcher. The WebKit processes it starts are
    # Apple's own and carry their own entitlements.
    subprocess.run([*plain, str(launcher)], check=True, capture_output=True)
    subprocess.run([*plain, str(APP)], check=True)
    subprocess.run(["codesign", "--verify", "--strict", "--verbose=1", str(APP)], check=True)
    say("  bundle signed and verifies")


def _notary_args() -> list[str]:
    key = os.environ.get("NOTARY_KEY_PATH", "")
    key_id = os.environ.get("NOTARY_KEY_ID", "")
    issuer = os.environ.get("NOTARY_ISSUER_ID", "")
    if not (key and key_id and issuer):
        raise SystemExit("notarization needs NOTARY_KEY_PATH, NOTARY_KEY_ID and "
                         "NOTARY_ISSUER_ID in the environment")
    return ["--key", key, "--key-id", key_id, "--issuer", issuer]


def _submit(path: Path, label: str) -> None:
    """Upload and wait for Apple's verdict. A rejection prints Apple's log,
    which names the file and the reason, then stops the build."""
    import json
    say("Notarizing %s" % label)
    r = subprocess.run(["xcrun", "notarytool", "submit", str(path), *_notary_args(),
                        "--wait", "--timeout", "30m", "--output-format", "json"],
                       capture_output=True, text=True)
    try:
        result = json.loads(r.stdout)
    except ValueError:
        result = {}
    say("  status: %s (id %s)" % (result.get("status", "?"), result.get("id", "?")))
    if r.returncode != 0 or result.get("status") != "Accepted":
        if result.get("id"):
            log = subprocess.run(["xcrun", "notarytool", "log", result["id"], *_notary_args()],
                                 capture_output=True, text=True)
            say(log.stdout[-4000:])
        else:
            say(r.stderr[-2000:])
        raise SystemExit("notarization was not accepted for %s" % label)


def notarize_app() -> None:
    """The bundle goes up as a zip, comes back accepted, and the ticket is
    stapled to the bundle before it is copied into the disk image, so the
    app works offline once dragged out of the dmg."""
    z = DIST / "PaperPull-notarize.zip"
    if z.exists():
        z.unlink()
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(APP), str(z)], check=True)
    try:
        _submit(z, APP.name)
    finally:
        z.unlink()
    staple(APP)
    say("  accepted and stapled")


def notarize(path: Path) -> None:
    _submit(path, path.name)
    staple(path)
    say("  accepted and stapled")


def staple(path: Path) -> None:
    """Staple the notarization ticket to `path`, tried again after each of
    STAPLE_WAITS while stapler fails. The last try's failure stops the
    build as CalledProcessError, as one try's did before."""
    cmd = ["xcrun", "stapler", "staple", str(path)]
    for wait in STAPLE_WAITS:
        r = subprocess.run(cmd)
        if r.returncode == 0:
            return
        say("  stapler exited %d, trying again in %d s" % (r.returncode, wait))
        time.sleep(wait)
    subprocess.run(cmd, check=True)


# -- dmg -----------------------------------------------------------------------

def make_dmg(identity: str = "") -> Path:
    say("Disk image")
    root = DIST / "dmg-root"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    shutil.copytree(APP, root / "PaperPull.app", symlinks=True)
    os.symlink("/Applications", root / "Applications")
    shutil.copy2(RES / "README-FIRST.txt", root / "README-FIRST.txt")
    out = DIST / ("PaperPull-%s-%s.dmg" % (version(), ARCH))
    if out.exists():
        out.unlink()
    subprocess.run(["hdiutil", "create", "-volname", "PaperPull", "-srcfolder", str(root),
                    "-ov", "-format", "UDZO", "-quiet", str(out)], check=True)
    shutil.rmtree(root)
    say("  %s  %.1f MB" % (out.name, out.stat().st_size / 1048576))
    if identity:
        subprocess.run(["codesign", "--force", "--timestamp", "--sign", identity, str(out)],
                       check=True)
        notarize(out)
        subprocess.run(["spctl", "--assess", "--type", "open", "--context",
                        "context:primary-signature", "-vv", str(out)], check=True)
        say("  Gatekeeper accepts the disk image")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sign", action="store_true", help="sign, notarize and staple")
    ap.add_argument("--arch", choices=sorted(ARCHES),
                    help="arm64 or x86_64, this Mac's own when left out")
    args = ap.parse_args(argv)

    if sys.platform != "darwin":
        say("This builds the macOS bundle and runs on macOS.")
        return 1
    global ARCH
    host = host_arch()
    ARCH = args.arch or host
    # An Intel Mac cannot run an arm64 Python, and the packages are installed
    # by running the staged one. Apple Silicon runs an Intel one through
    # Rosetta, so the other way round works.
    if ARCH == "arm64" and host != "arm64":
        say("This is an Intel Mac and cannot build the arm64 package, because the"
            " packages are installed by running the staged Python.")
        return 1

    say("PaperPull %s, %s" % (version(), ARCH))
    if APP.exists():
        shutil.rmtree(APP)
    RES.mkdir(parents=True)

    py = stage_python()
    install_packages(py)
    stage_code()
    write_bundle()
    audit()
    smoke_test(py)
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "") if args.sign else ""
    if args.sign:
        sign(identity)
        notarize_app()
    make_dmg(identity)
    say("\nDone. Bundle at dist/PaperPull.app, dmg beside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
