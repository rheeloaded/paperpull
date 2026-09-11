"""Build a self-contained PaperPull for Windows.

    python build\\build_windows.py            portable folder + zip
    python build\\build_windows.py --installer  also compile the Inno installer

WHAT IT PRODUCES

    dist\\PaperPull\\            a folder that runs with nothing else installed
    dist\\PaperPull-<ver>.zip   the same, zipped, which is the beta deliverable
    dist\\PaperPull-<ver>-setup.exe   only with --installer and Inno Setup present

HOW IT IS BUILT, AND WHY THIS WAY

Nothing is frozen. The folder carries the official embeddable CPython from
python.org, with the packages every app needs installed into it once. That was
chosen over PyInstaller for three reasons.

Every one of the 22 apps needs exactly the same three packages, so one shared
environment serves all of them, and there is nothing to gain from per-app
bundles.

The control panel already runs each app as a subprocess, using the app's own
.venv if it has one and sys.executable if it does not. With a real interpreter
as sys.executable that works unchanged. An install that already has venvs keeps
using them, which is the upgrade path, and a fresh install uses the shared one.

A real interpreter means sys.frozen is False, so "python -m playwright install"
works as documented and the frozen-build fallback in browser.py stays a safety
net rather than the main path.

WHAT IS NOT IN IT

The 400 MB Chromium. Any Chromium-based browser already on the machine is used,
and the download is offered at sign-in only if none is found.

Anything untracked. Only files git knows about go in, which is what guarantees
no config.json, browser profile, PDF or download history from this machine can
end up in the package.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
STAGE = DIST / "PaperPull"

PY_VERSION = "3.12.10"
PY_ZIP = "python-%s-embed-amd64.zip" % PY_VERSION
PY_URL = "https://www.python.org/ftp/python/%s/%s" % (PY_VERSION, PY_ZIP)
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

# What the panel and every app need. pytest is left out of the package because
# a user does not run the test suite, and it is the one thing on every app's
# requirements list that is not needed to run.
PACKAGES = ["playwright>=1.44", "pypdf>=4.2", "fastapi>=0.110",
            "uvicorn>=0.27", "anyio>=4"]

# Top-level paths from the repo that belong in the package. apps/ is filtered
# further below so only code goes, never a venv or data folder that happens to
# be sitting in a checkout.
INCLUDE_TOP = ("gui", "core", "apps", "tools", "VERSION", "LICENSE",
               "README.md", "PROVIDERS.md", "SECURITY.md", "CHANGELOG.md")
EXCLUDE_PARTS = {".venv", "__pycache__", ".pytest_cache", "tests",
                 "Backups", "Logs", "Diagnostics", "Manual Review"}


def say(msg=""):
    print(msg, flush=True)


def version() -> str:
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def fetch(url: str, dest: Path) -> None:
    if dest.exists():
        say("  using cached %s" % dest.name)
        return
    say("  downloading %s" % url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def tracked_files() -> list[str]:
    """Everything git knows about. Untracked files never reach the package,
    which is how a real config, profile, PDF or history is kept out."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                         capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def wanted(rel: str) -> bool:
    parts = Path(rel).parts
    if parts[0] not in INCLUDE_TOP:
        return False
    if any(p in EXCLUDE_PARTS for p in parts):
        return False
    if parts[0] == "apps":
        # code, rules and launchers only. The example config is the only
        # config that ships, and it is the only one git tracks anyway.
        name = parts[-1]
        if name in ("config.json", "progress.json", "discovery.json"):
            return False
    return True


def stage_python() -> Path:
    say("Python %s, embeddable build" % PY_VERSION)
    cache = DIST / "cache"
    fetch(PY_URL, cache / PY_ZIP)
    fetch(GET_PIP, cache / "get-pip.py")

    pydir = STAGE / "python"
    pydir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache / PY_ZIP) as z:
        z.extractall(pydir)

    # The ._pth file IS sys.path for the embeddable build, and two things about
    # that matter here.
    #
    # It does not add the directory of the script being run, which every app
    # relies on to import its sibling *_site.py. And the usual fix, "import
    # site", also switches on the user's Roaming site-packages, so the package
    # would quietly pick up whatever that machine happened to have installed
    # and behave differently on each one.
    #
    # The ._pth format accepts exactly one import line, "import site", so that
    # is used, and site's own hook does the rest. site runs sitecustomize.py
    # from site-packages if one exists, and that module strips every path
    # outside the package and puts the script directory back. No app and no
    # part of the panel has to know it is running packaged.
    pth = next(pydir.glob("python*._pth"))
    pth.write_text("python312.zip\n.\nLib\\site-packages\nimport site\n",
                   encoding="utf-8")
    sp = pydir / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "sitecustomize.py").write_text(
        '"""Run by site at every startup of the packaged Python.\n'
        '\n'
        'Two corrections to what the embeddable build does on its own.\n'
        '\n'
        'It drops every sys.path entry outside this package. "import site"\n'
        'also switches on the user\'s Roaming site-packages, so without this\n'
        'the package would pick up whatever that machine happened to have\n'
        'installed and behave differently on each one.\n'
        '\n'
        'It puts the directory of the script being run at the front, which a\n'
        'normal Python does by itself and the embeddable build does not. Every\n'
        'app imports its sibling *_site.py that way.\n'
        '"""\n'
        'import os\n'
        'import sys\n'
        '\n'
        '_pkg = os.path.dirname(os.path.dirname(os.path.dirname(\n'
        '    os.path.abspath(__file__)))).lower()\n'
        'sys.path[:] = [p for p in sys.path\n'
        '               if p == "" or os.path.abspath(p).lower().startswith(_pkg)]\n'
        '\n'
        'if sys.argv and sys.argv[0] and os.path.isfile(sys.argv[0]):\n'
        '    _d = os.path.dirname(os.path.abspath(sys.argv[0]))\n'
        '    if _d not in sys.path:\n'
        '        sys.path.insert(0, _d)\n',
        encoding="utf-8")

    py = pydir / "python.exe"
    say("  bootstrapping pip")
    subprocess.run([str(py), str(cache / "get-pip.py"), "--no-warn-script-location",
                    "-q"], check=True)
    return py


def install_packages(py: Path) -> None:
    say("Packages")
    subprocess.run([str(py), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", *PACKAGES], check=True)
    say("  shared core")
    # Built as a wheel by the Python running this script, which has a build
    # backend, then installed into the package. The embeddable build has no
    # setuptools and cannot install from a source tree.
    wheels = DIST / "cache" / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    for old in wheels.glob("paperpull_core-*.whl"):
        old.unlink()
    subprocess.run([sys.executable, "-m", "pip", "wheel", "-q", "--no-deps",
                    "-w", str(wheels), str(REPO / "core")], check=True)
    wheel = next(wheels.glob("paperpull_core-*.whl"))
    subprocess.run([str(py), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", str(wheel)], check=True)
    # pip itself is not needed at runtime and is not small. Only what is
    # actually present is removed, and quietly, because pip prints a full
    # traceback when asked to uninstall something that was never installed.
    have = subprocess.run([str(py), "-m", "pip", "list", "--format=freeze"],
                          capture_output=True, text=True).stdout.lower()
    gone = [n for n in ("pip", "setuptools", "wheel") if n + "==" in have]
    if gone:
        subprocess.run([str(py), "-m", "pip", "uninstall", "-q", "-y", *gone],
                       check=False, capture_output=True)


def stage_code() -> int:
    say("Code, tracked files only")
    n = 0
    for rel in tracked_files():
        if not wanted(rel):
            continue
        src = REPO / rel
        if not src.is_file():
            continue
        # App code ships as a TEMPLATE, not as installs. The panel's default
        # root is apps/ beside it, and a folder of 22 apps with no config and
        # no history is exactly what a fresh install must not list. Under
        # templates/ it is out of the way until a "create a new install"
        # feature needs it, and the panel asks where the real ones are.
        if rel.startswith("apps/"):
            rel = "templates/" + rel
        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    say("  %d files" % n)
    return n


def write_launchers() -> None:
    say("Launchers")
    (STAGE / "PaperPull.bat").write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "rem The panel binds 127.0.0.1 only. Nothing is reachable from the network.\r\n"
        "start \"\" http://127.0.0.1:8765\r\n"
        "python\\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765 --app-dir gui\r\n",
        encoding="utf-8")

    (STAGE / "README-FIRST.txt").write_text(
        "PaperPull %s, beta\r\n"
        "\r\n"
        "Double-click PaperPull.bat. A browser tab opens with the control panel.\r\n"
        "\r\n"
        "The first time, it asks where your downloaders are. If you already have\r\n"
        "them, paste that folder's full path and it uses them exactly as they\r\n"
        "are. Nothing is moved, copied or changed, and the old way of running\r\n"
        "them keeps working alongside this.\r\n"
        "\r\n"
        "It uses the copy of Chrome or Edge already on this computer, opened in\r\n"
        "a separate profile, so your normal browsing is untouched and you sign\r\n"
        "in fresh. If there is no such browser it offers to download one.\r\n"
        "\r\n"
        "Everything runs on this computer. Nothing is sent anywhere.\r\n"
        "\r\n"
        "Beta. Keep your existing setup until you are happy with this one.\r\n"
        % version(), encoding="utf-8")


def write_inno_script() -> Path:
    """The installer definition. Compiled only when Inno Setup is present."""
    iss = DIST / "PaperPull.iss"
    iss.write_text(r"""; PaperPull installer. Compile with Inno Setup 6.
; Beta: not signed. Windows will show a SmartScreen warning on first run.

#define AppVersion "%(ver)s"

[Setup]
AppName=PaperPull
AppVersion={#AppVersion}
AppPublisher=rheeloaded
AppPublisherURL=https://github.com/rheeloaded/paperpull
DefaultDirName={localappdata}\PaperPull
DefaultGroupName=PaperPull
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=PaperPull-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\PaperPull.bat

[Files]
Source: "PaperPull\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PaperPull"; Filename: "{app}\PaperPull.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\PaperPull"; Filename: "{app}\PaperPull.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\PaperPull.bat"; Description: "Open PaperPull now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; The program only. The user's downloaders, history and browser profiles are
; wherever they chose to keep them and are never touched by an uninstall.
Type: filesandordirs; Name: "{app}\python"
""" % {"ver": version()}, encoding="utf-8")
    say("  wrote %s" % iss.relative_to(REPO))
    return iss


def zip_it() -> Path:
    out = DIST / ("PaperPull-%s.zip" % version())
    say("Zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(DIST))
    mb = out.stat().st_size / 1048576
    say("  %s  %.1f MB" % (out.name, mb))
    return out


def audit() -> None:
    """The one check that must never be skipped. Nothing personal in it."""
    say("Audit")
    bad = []
    for p in STAGE.rglob("*"):
        n = p.name.lower()
        if n in ("config.json", "progress.json", "discovery.json") \
                or n.endswith(".pdf") or "browser-profile" in n \
                or n in ("cookies", "login data", "local state"):
            bad.append(str(p.relative_to(STAGE)))
    if bad:
        raise SystemExit("REFUSING TO PACKAGE, personal files found:\n  " +
                         "\n  ".join(bad))
    say("  no config, history, profile or PDF in the package")


def smoke_test(py: Path) -> None:
    say("Smoke test")
    r = subprocess.run([str(py), "-c",
                        "import playwright, pypdf, fastapi, uvicorn, paperpull_core; "
                        "print('ok')"], capture_output=True, text=True)
    if r.returncode != 0 or "ok" not in r.stdout:
        raise SystemExit("packaged python cannot import its packages:\n" + r.stderr)
    say("  packaged python imports playwright, pypdf, fastapi, uvicorn, paperpull_core")
    chase = STAGE / "templates" / "apps" / "chase"
    r = subprocess.run([str(py), str(chase / "chase_docs.py"), "--help"],
                       capture_output=True, text=True, cwd=str(chase))
    if r.returncode != 0:
        raise SystemExit("an app does not run under the packaged python:\n" + r.stderr[-800:])
    say("  an app runs under it")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true",
                    help="also compile the Inno Setup installer")
    args = ap.parse_args(argv)

    if sys.platform != "win32":
        say("This builds the Windows package and runs on Windows.")
        return 1

    say("PaperPull %s" % version())
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    py = stage_python()
    install_packages(py)
    stage_code()
    write_launchers()
    audit()
    smoke_test(py)
    zip_it()
    iss = write_inno_script()

    if args.installer:
        iscc = None
        for c in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                  r"C:\Program Files\Inno Setup 6\ISCC.exe"):
            if Path(c).exists():
                iscc = c
        if not iscc:
            say("Inno Setup is not installed, so no .exe installer was built.")
            say("Install it from https://jrsoftware.org/isinfo.php and re-run with --installer.")
        else:
            say("Installer")
            subprocess.run([iscc, "/Q", str(iss)], check=True, cwd=str(DIST))
            say("  built")

    say()
    say("Done. Portable folder at dist\\PaperPull, zip beside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
