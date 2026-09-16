"""Build a self-contained PaperPull for macOS on Apple Silicon.

    python packaging/build_macos.py            PaperPull.app + a .dmg, unsigned
    python packaging/build_macos.py --sign     also sign, notarize and staple

WHAT IT PRODUCES

    dist/PaperPull.app                      the application bundle
    dist/PaperPull-<ver>-arm64.dmg          the disk image people download

HOW IT IS BUILT, AND WHY THIS WAY

The same idea as the Windows package. Nothing is frozen. The bundle carries a
relocatable CPython (python-build-standalone, the build that uv ships) with
the packages every app needs installed into it once, and the repo's own code
beside it. The panel and every app run under that interpreter exactly as they
do in a checkout, so nothing has to know it is packaged.

Apple Silicon only. The build is one architecture and one download, which is
the machine every Mac sold since 2020 is, and an Intel build would double the
matrix for a shrinking audience.

The bundle's main executable is a shell script that opens a Terminal window
running the panel and then opens the browser to it, the same shape as
PaperPull.bat on Windows. Closing the Terminal window stops it. That was
chosen over a native wrapper because it keeps the whole package free of
compiled code of our own, so what gets signed is Python, the packages and
scripts, all of it readable.

WHAT IS NOT IN IT

The 400 MB Chromium. Chrome, Edge, Brave, Vivaldi or Opera already on the Mac
is used, and the download is offered at sign-in only if none is found. Safari
cannot be driven this way.

Anything untracked. Only files git knows about go in.

SIGNING

--sign needs a Developer ID Application certificate in the keychain and the
notarytool credentials in the environment. See the workflow for the names.
Without --sign the bundle and dmg are unsigned and macOS will refuse to open
them without a right-click, which is fine for checking a build and useless
for handing to anyone else.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
APP = DIST / "PaperPull.app"
CONTENTS = APP / "Contents"
RES = CONTENTS / "Resources"
MACOS = CONTENTS / "MacOS"

# python-build-standalone, the install_only_stripped flavour. It unpacks to a
# folder called python/ that is a complete, relocatable CPython with pip.
PBS_TAG = "20260901"
PY_VERSION = "3.12.14"
PBS_ASSET = "cpython-%s+%s-aarch64-apple-darwin-install_only_stripped.tar.gz" % (PY_VERSION, PBS_TAG)
PBS_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s" % (PBS_TAG, PBS_ASSET)

BUNDLE_ID = "io.github.rheeloaded.paperpull"

# Imported from the Windows build so the two packages cannot drift apart on
# what they carry.
sys.path.insert(0, str(REPO / "packaging"))
from build_windows import (PACKAGES, EXCLUDE_PARTS, INCLUDE_TOP,  # noqa: E402
                           tracked_files, version, fetch, say)


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

def stage_python() -> Path:
    say("Python %s, python-build-standalone %s, arm64" % (PY_VERSION, PBS_TAG))
    cache = DIST / "cache"
    fetch(PBS_URL, cache / PBS_ASSET)
    with tarfile.open(cache / PBS_ASSET) as t:
        t.extractall(RES, filter="data")
    py = RES / "python" / "bin" / "python3"
    if not py.exists():
        raise SystemExit("the Python tarball did not unpack to python/bin/python3")
    return py


def install_packages(py: Path) -> None:
    say("Packages")
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-warn-script-location",
                    *PACKAGES], check=True, env=env)
    say("  shared core")
    wheels = DIST / "cache" / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    for old in wheels.glob("paperpull_core-*.whl"):
        old.unlink()
    subprocess.run([sys.executable, "-m", "pip", "wheel", "-q", "--no-deps",
                    "-w", str(wheels), str(REPO / "core")], check=True)
    wheel = next(wheels.glob("paperpull_core-*.whl"))
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-warn-script-location",
                    str(wheel)], check=True, env=env)
    have = subprocess.run([str(py), "-m", "pip", "list", "--format=freeze"],
                          capture_output=True, text=True, env=env).stdout.lower()
    gone = [n for n in ("pip", "setuptools", "wheel") if n + "==" in have]
    if gone:
        subprocess.run([str(py), "-m", "pip", "uninstall", "-q", "-y", *gone],
                       check=False, capture_output=True, env=env)
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

def _ico_largest_png(ico: Path) -> bytes:
    """The largest image in a .ico, as PNG bytes. The entries are plain DIBs
    (32-bit BGRA, bottom-up, followed by a mask that is ignored), so this
    reads the pixels and writes a PNG by hand rather than needing Pillow in
    the build environment."""
    d = ico.read_bytes()
    count = struct.unpack("<H", d[4:6])[0]
    best = None
    for i in range(count):
        w, h, _cc, _r, _pl, bpp, size, off = struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i])
        w, h = w or 256, h or 256
        if best is None or w > best[0]:
            best = (w, h, bpp, size, off)
    w, h, bpp, size, off = best
    blob = d[off:off + size]
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return blob
    hdr = struct.unpack("<IiiHHII", blob[:24])
    if hdr[3] != 1 or hdr[4] != 32:
        raise SystemExit("icon entry is not 32-bit, cannot convert without Pillow")
    px = blob[hdr[0]:]
    row = w * 4
    raw = bytearray()
    for y in range(h - 1, -1, -1):
        raw.append(0)
        line = px[y * row:(y + 1) * row]
        for x in range(0, row, 4):
            b, g, r, a = line[x:x + 4]
            raw += bytes((r, g, b, a))

    def chunk(kind, body):
        c = struct.pack(">I", len(body)) + kind + body
        return c + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


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
    src.write_bytes(_ico_largest_png(ico))
    for size in (16, 32, 64, 128, 256):
        subprocess.run(["sips", "-z", str(size), str(size), str(src), "--out",
                        str(iconset / ("icon_%dx%d.png" % (size, size)))],
                       check=True, capture_output=True)
        if size >= 32:
            shutil.copy2(iconset / ("icon_%dx%d.png" % (size, size)),
                         iconset / ("icon_%dx%d@2x.png" % (size // 2, size // 2)))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o",
                    str(RES / "PaperPull.icns")], check=True)
    return "PaperPull.icns"


def write_bundle() -> None:
    say("Bundle")
    MACOS.mkdir(parents=True, exist_ok=True)
    icon = write_icon()

    # What the Terminal window runs. Same shape as PaperPull.bat.
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

    # The bundle's executable. Opens Terminal on the script above, so the
    # log is visible and there is an obvious way to quit.
    (MACOS / "PaperPull").write_text(
        '#!/bin/bash\n'
        'DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"\n'
        'exec open -a Terminal "$DIR/paperpull-panel.sh"\n',
        encoding="utf-8")
    os.chmod(MACOS / "PaperPull", 0o755)

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
        "PaperPull %s, beta\n"
        "\n"
        "Double-click PaperPull. A Terminal window opens running the control panel\n"
        "and a browser tab opens to it. Close the Terminal window to stop.\n"
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
        "Everything runs on this Mac. Nothing is sent anywhere.\n"
        "\n"
        "Beta. Keep your existing setup until you are happy with this one.\n"
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
        "LSMinimumSystemVersion": "11.0",
        "LSArchitecturePriority": ["arm64"],
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "MIT license. https://github.com/rheeloaded/paperpull",
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


def smoke_test(py: Path) -> None:
    say("Smoke test")
    env = dict(os.environ, PYTHONNOUSERSITE="1")
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

def sign(identity: str) -> None:
    """Every Mach-O in the bundle, inside out, then the bundle. Placeholder
    until the certificate is in place; see the second half of this work."""
    raise SystemExit("--sign is not wired up yet")


# -- dmg -----------------------------------------------------------------------

def make_dmg() -> Path:
    say("Disk image")
    root = DIST / "dmg-root"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    shutil.copytree(APP, root / "PaperPull.app", symlinks=True)
    os.symlink("/Applications", root / "Applications")
    shutil.copy2(RES / "README-FIRST.txt", root / "README-FIRST.txt")
    out = DIST / ("PaperPull-%s-arm64.dmg" % version())
    if out.exists():
        out.unlink()
    subprocess.run(["hdiutil", "create", "-volname", "PaperPull", "-srcfolder", str(root),
                    "-ov", "-format", "UDZO", "-quiet", str(out)], check=True)
    shutil.rmtree(root)
    say("  %s  %.1f MB" % (out.name, out.stat().st_size / 1048576))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sign", action="store_true", help="sign, notarize and staple")
    args = ap.parse_args(argv)

    if sys.platform != "darwin":
        say("This builds the macOS bundle and runs on macOS.")
        return 1

    say("PaperPull %s" % version())
    if APP.exists():
        shutil.rmtree(APP)
    RES.mkdir(parents=True)

    py = stage_python()
    install_packages(py)
    stage_code()
    write_bundle()
    audit()
    smoke_test(py)
    if args.sign:
        sign(os.environ.get("MACOS_SIGN_IDENTITY", ""))
    make_dmg()
    say("\nDone. Bundle at dist/PaperPull.app, dmg beside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
