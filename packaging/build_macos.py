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

The bundle's main executable opens a Terminal window running the panel and
then opens the browser to it, the same shape as PaperPull.bat on Windows.
Closing the Terminal window stops it. The executable itself is a dozen lines
of C, compiled on the build machine, because notarization requires a Mach-O
main executable with the hardened runtime. It finds its own bundle and hands
the panel script to Terminal, and that is all it does.

WHAT IS NOT IN IT

The 400 MB Chromium. Chrome, Edge, Brave, Vivaldi or Opera already on the Mac
is used, and the download is offered at sign-in only if none is found. Safari
cannot be driven this way.

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
    # log is visible and there is an obvious way to quit. It is a few lines
    # of C rather than a shell script because notarization requires the main
    # executable to be a Mach-O binary carrying the hardened runtime, and a
    # script cannot carry that. It does nothing but find its own bundle and
    # hand the script to Terminal.
    launcher_c = DIST / "cache" / "launcher.c"
    launcher_c.parent.mkdir(parents=True, exist_ok=True)
    launcher_c.write_text(
        '#include <mach-o/dyld.h>\n'
        '#include <libgen.h>\n'
        '#include <stdio.h>\n'
        '#include <stdlib.h>\n'
        '#include <string.h>\n'
        '#include <unistd.h>\n'
        'int main(void) {\n'
        '    char exe[4096]; uint32_t n = sizeof exe;\n'
        '    if (_NSGetExecutablePath(exe, &n) != 0) return 1;\n'
        '    char real[4096];\n'
        '    if (!realpath(exe, real)) return 1;\n'
        '    char script[4096];\n'
        '    snprintf(script, sizeof script, "%s/../Resources/paperpull-panel.sh", dirname(real));\n'
        '    execl("/usr/bin/open", "open", "-a", "Terminal", script, (char *)0);\n'
        '    perror("open"); return 1;\n'
        '}\n', encoding="utf-8")
    subprocess.run(["clang", "-arch", "arm64", "-O2", "-mmacosx-version-min=11.0",
                    "-o", str(MACOS / "PaperPull"), str(launcher_c)], check=True)

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
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
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
    base = ["codesign", "--force", "--timestamp", "--options", "runtime",
            "--entitlements", str(ent), "--sign", identity]
    binaries = sorted((p for p in APP.rglob("*") if _is_macho(p)),
                      key=lambda p: (-len(p.parts), str(p)))
    # The main executable is signed with the bundle, not on its own.
    binaries = [b for b in binaries if b != MACOS / "PaperPull"]
    for i in range(0, len(binaries), 50):
        subprocess.run([*base, *map(str, binaries[i:i + 50])], check=True,
                       capture_output=True)
    say("  %d binaries" % len(binaries))
    subprocess.run([*base, str(APP)], check=True)
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
    subprocess.run(["xcrun", "stapler", "staple", str(APP)], check=True)
    say("  accepted and stapled")


def notarize(path: Path) -> None:
    _submit(path, path.name)
    subprocess.run(["xcrun", "stapler", "staple", str(path)], check=True)
    say("  accepted and stapled")


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
    out = DIST / ("PaperPull-%s-arm64.dmg" % version())
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
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "") if args.sign else ""
    if args.sign:
        sign(identity)
        notarize_app()
    make_dmg(identity)
    say("\nDone. Bundle at dist/PaperPull.app, dmg beside it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
