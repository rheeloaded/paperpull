"""Build a self-contained PaperPull for Windows.

    python packaging\\build_windows.py                 portable folder + zip
    python packaging\\build_windows.py --installer     also compile the Inno installer

WHAT IT PRODUCES

    dist\\PaperPull\\            a folder that runs with nothing else installed
    dist\\PaperPull-<ver>.zip   the same, zipped, for anyone who would rather not run an installer
    dist\\PaperPull-<ver>-setup.exe   only with --installer and Inno Setup present

HOW IT IS BUILT, AND WHY THIS WAY

Nothing is frozen. The folder carries a relocatable CPython from
python-build-standalone, the same release the Mac bundle carries, with the
packages every app needs installed into it once from a lock that names each
file's hash. That was chosen over PyInstaller for three reasons.

Every app needs the same few packages, so one shared
environment serves all of them, and there is nothing to gain from per-app
bundles.

The control panel already runs each app as a subprocess, using the app's own
.venv if it has one and sys.executable if it does not. With a real interpreter
as sys.executable that works unchanged. An install that already has venvs keeps
using them, which is the upgrade path, and a fresh install uses the shared one.

A real interpreter means sys.frozen is False, so "python -m playwright install"
works as documented and the frozen-build fallback in browser.py stays a safety
net rather than the main path.

WHY NOT PYTHON.ORG'S EMBEDDABLE BUILD

It was used until 0.55.0. python.org publishes Windows binaries for a Python
only while that version takes bug fixes, and 3.12.10 was the last for 3.12,
so every later 3.12 security fix would have stayed out of this package.
python-build-standalone builds each release from source, and its archive is
checked against the SHA-256 written below before anything is built from it.

WHAT IS NOT IN IT

The 400 MB Chromium. Any Chromium-based browser already on the machine is used,
and the download is offered at sign-in only if none is found.

Anything untracked. Only files git knows about go in, which is what guarantees
no config.json, browser profile, PDF or download history from this machine can
end up in the package.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist"
STAGE = DIST / "PaperPull"

sys.path.insert(0, str(REPO / "packaging"))
import msix  # noqa: E402
from icons import ico_largest_png  # noqa: E402

# python-build-standalone, the install_only_stripped flavor, which unpacks to
# a folder called python/ holding a complete CPython with pip. Stripped
# leaves out only its debugging symbols. The same release and Python as
# packaging/build_macos.py, and core/tests holds the two to each other.
PBS_TAG = "20261026"
PY_VERSION = "3.12.16"

# The architecture being built, x64, the only one. It runs on ARM64 Windows
# too, under emulation, and nobody would measure the difference in a program
# that waits on a browser. A native arm64 build behind a switch, never
# shipped, was taken out after 0.56.2. cryptography published its last
# win_arm64 wheel in 46.0.3, so that build could only ever carry a
# cryptography and an OpenSSL with known holes, and its lock kept GitHub's
# security alerts open for a package nobody downloads. Only run on an x64
# machine, since the packages are installed by running the staged Python.
ARCHES = {"x64": "x86_64"}     # ours -> python-build-standalone's name
ARCH = "x64"

# Each architecture's archive as python-build-standalone's SHA256SUMS for
# PBS_TAG lists it, which is also the digest GitHub shows for the asset. The
# download must match before anything is built from it. A new PBS_TAG or
# PY_VERSION takes both lines again from that release's SHA256SUMS, and the
# Mac's in packaging/build_macos.py with them. The Windows workflow signs the
# interpreter's programs and libraries by name, so the new archive's python\
# and python\DLLs are compared with that list too, which core/tests holds to
# PBS_TAG.
PBS_SHA256 = {
    "x64": "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149",
}


def triple(arch: str | None = None) -> str:
    """The platform as python-build-standalone names it, and uv in
    packaging/lock.py."""
    return "%s-pc-windows-msvc" % ARCHES[arch or ARCH]


def pbs_asset() -> str:
    return "cpython-%s+%s-%s-install_only_stripped.tar.gz" % (PY_VERSION, PBS_TAG, triple())


def pbs_url() -> str:
    return "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s" % (
        PBS_TAG, pbs_asset())


def lock_file(arch: str | None = None) -> Path:
    """What the package installs, every package the panel and the apps need
    at one version with the hash of each of its files, written by
    packaging/lock.py from packaging/requirements.in. One for each
    architecture, since a package can have a built wheel for one and not
    the other."""
    return REPO / "packaging" / ("requirements-windows-%s.txt" % (arch or ARCH))

# What python-build-standalone carries that the package has no use for, none
# of which the embeddable build from python.org had either. Tk and IDLE, with
# the zlib1.dll that only tcl86t.dll loads (20260924 on), the C headers and
# import libraries for compiling extensions, CPython's own test extensions,
# and venv with ensurepip, whose bundled pip is older than the one the build
# uses and then removes. Each is a glob under python/.
PRUNE = ("tcl", "include", "libs", "Lib/tkinter", "Lib/idlelib", "Lib/turtledemo",
         "Lib/turtle.py", "Lib/__pycache__/turtle.*", "Lib/ensurepip", "Lib/venv",
         "DLLs/_tkinter.pyd", "DLLs/tcl*.dll", "DLLs/tk*.dll", "DLLs/zlib1.dll",
         "DLLs/_test*.pyd", "DLLs/_ctypes_test.pyd")

# Top-level paths from the repo that belong in the package. apps/ is filtered
# further below so only code goes, never a venv or data folder that happens to
# be sitting in a checkout.
INCLUDE_TOP = ("gui", "core", "apps", "tools", "paperpull.py", "paperpull.bat",
               "VERSION", "LICENSE", "LICENSE-MIT", "NOTICE.md", "TRADEMARK.md",
               "PRIVACY.md", "TERMS.md",
               "README.md", "PROVIDERS.md", "SECURITY.md", "CHANGELOG.md")
EXCLUDE_PARTS = {".venv", "__pycache__", ".pytest_cache", "tests",
                 "Backups", "Logs", "Diagnostics", "Manual Review"}


def host_arch() -> str:
    """The machine's real architecture, seen through any emulation. An x64
    Python on an ARM64 machine reports AMD64 in PROCESSOR_ARCHITECTURE and
    the truth in PROCESSOR_ARCHITEW6432."""
    raw = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    return "arm64" if raw == "ARM64" else "x64"


def say(msg=""):
    print(msg, flush=True)


def version() -> str:
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


def fetch(url: str, dest: Path, sha256: str = "") -> None:
    """url saved as dest, unless dest is already there. With sha256, the
    file, cached or new, must have that digest, and one that does not is
    deleted and the build stops, so a changed or damaged download never
    reaches a package."""
    if dest.exists():
        say("  using cached %s" % dest.name)
    else:
        say("  downloading %s" % url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    if sha256:
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != sha256.lower():
            dest.unlink()
            raise SystemExit("%s has SHA-256 %s, and %s was expected. It was deleted, and"
                             " nothing was built from it." % (dest.name, h.hexdigest(), sha256))


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
        name = parts[-1].lower()
        if name in ("progress.json", "discovery.json"):
            return False
        # Any config but the example. config.json was named here, and a
        # second person's account is config.<label>.json, which this did
        # not know about. Nothing of that shape is ever part of the app.
        if name.startswith("config.") and name.endswith(".json")                 and name != "config.example.json":
            return False
    return True


# Each of the interpreter's programs and libraries with its SHA-256 as the
# checked archive held it, written beside the stage and never into it. The
# Windows workflow signs those files with the project's certificate, and
# between the archive's check and the signing the packages are installed
# into the same folder and run, so it signs a file only while it still
# matches this record.
PYTHON_RECORD = "python-files.sha256"


def interpreter_files() -> list[Path]:
    """The .exe, .dll and .pyd files directly in python\\ and python\\DLLs."""
    pydir = STAGE / "python"
    return sorted(p for d in (pydir, pydir / "DLLs") if d.is_dir() for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".exe", ".dll", ".pyd"))


def record_interpreter() -> Path:
    out = DIST / PYTHON_RECORD
    out.write_text("".join(
        "%s  %s\n" % (hashlib.sha256(p.read_bytes()).hexdigest(),
                      p.relative_to(STAGE).as_posix().replace("/", "\\"))
        for p in interpreter_files()), encoding="ascii")
    return out


def stage_python() -> Path:
    say("Python %s, python-build-standalone %s, %s" % (PY_VERSION, PBS_TAG, ARCH))
    cache = DIST / "cache"
    fetch(pbs_url(), cache / pbs_asset(), sha256=PBS_SHA256[ARCH])
    with tarfile.open(cache / pbs_asset()) as t:
        t.extractall(STAGE, filter="data")
    pydir = STAGE / "python"
    py = pydir / "python.exe"
    if not py.is_file():
        raise SystemExit("the Python archive did not unpack to python\\python.exe")
    for pattern in PRUNE:
        for p in pydir.glob(pattern):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    record_interpreter()

    # On its own this Python is set up like an installed one. It reads
    # PYTHONPATH and PYTHONHOME, puts the script's folder or the current one
    # first on sys.path, and would behave differently on every machine. A
    # ._pth file beside its DLL ends that, as the embeddable build's own did.
    # The file IS sys.path, and its presence puts Python in isolated mode,
    # where the environment is ignored and no folder is added for the script.
    #
    # Two things about that matter here. Every app relies on the directory of
    # the script being run to import its sibling *_site.py. And the usual fix,
    # "import site", also switches on the user's Roaming site-packages, so the
    # package would quietly pick up whatever that machine happened to have
    # installed.
    #
    # The ._pth format accepts exactly one import line, "import site", so that
    # is used, and site's own hook does the rest. site runs sitecustomize.py
    # from site-packages if one exists, and that module strips every path
    # outside the package and puts the script directory back. No app and no
    # part of the panel has to know it is running packaged.
    dll = next(p for p in pydir.glob("python3*.dll") if p.name.lower() != "python3.dll")
    (pydir / (dll.stem + "._pth")).write_text("DLLs\nLib\nLib\\site-packages\nimport site\n",
                                             encoding="utf-8")
    sp = pydir / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "sitecustomize.py").write_text(
        '"""Run by site at every startup of the packaged Python.\n'
        '\n'
        'Two corrections to what the ._pth file beside python.exe leaves.\n'
        '\n'
        'It drops every sys.path entry outside this package. "import site"\n'
        'also switches on the user\'s Roaming site-packages, so without this\n'
        'the package would pick up whatever that machine happened to have\n'
        'installed and behave differently on each one.\n'
        '\n'
        'It puts the directory of the script being run at the front, which a\n'
        'normal Python does by itself and isolated mode does not. Every app\n'
        'imports its sibling *_site.py that way.\n'
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
        '        sys.path.insert(0, _d)\n'
        '\n'
        '# Bytecode goes to the user\'s temp folder, never into the package.\n'
        '# A Store install is read-only, and even here the program folder\n'
        '# should hold only what the installer put there.\n'
        'if not os.environ.get("PYTHONPYCACHEPREFIX") and sys.pycache_prefix is None:\n'
        '    _tmp = os.environ.get("LOCALAPPDATA")\n'
        '    _tmp = os.path.join(_tmp, "Temp") if _tmp else None\n'
        '    if _tmp is None:\n'
        '        import tempfile\n'
        '        _tmp = tempfile.gettempdir()\n'
        '    sys.pycache_prefix = os.path.join(_tmp, "PaperPull", "pycache")\n',
        encoding="utf-8")
    return py


def install_locked(py: Path, lock: Path, env: dict | None = None) -> None:
    """Every package in lock, then the shared core, into the staged Python,
    with the pip that came in its own checked archive. The Mac build uses
    this too.

    pip refuses a file whose hash the lock does not hold and a package the
    lock does not name, and takes built wheels only, so nothing is compiled
    on the build machine and nothing comes in unchecked. The core is built
    by the staged Python itself with the setuptools the lock just put there,
    rather than in an isolated build that fetches a build backend of its own,
    and goes in with nothing else, since its one dependency is in the lock."""
    say("Packages, from %s" % lock.name)
    pip = [str(py), "-m", "pip", "--disable-pip-version-check", "--no-input"]
    subprocess.run([*pip, "install", "-q", "--no-warn-script-location", "--require-hashes",
                    "--only-binary", ":all:", "-r", str(lock)], check=True, env=env)
    say("  shared core")
    wheels = DIST / "cache" / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    for old in wheels.glob("paperpull_core-*.whl"):
        old.unlink()
    subprocess.run([*pip, "wheel", "-q", "--no-deps", "--no-build-isolation",
                    "-w", str(wheels), str(REPO / "core")], check=True, env=env)
    wheel = next(wheels.glob("paperpull_core-*.whl"))
    subprocess.run([*pip, "install", "-q", "--no-warn-script-location", "--no-deps",
                    "--no-index", str(wheel)], check=True, env=env)
    r = subprocess.run([*pip, "check"], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise SystemExit("the packages in the package do not fit together:\n"
                         + r.stdout + r.stderr)
    # pip itself is not needed at runtime and is not small, and setuptools
    # was only there to build the core. Only what is actually present is
    # removed, and quietly, because pip prints a full traceback when asked
    # to uninstall something that was never installed.
    have = subprocess.run([*pip, "list", "--format=freeze"],
                          capture_output=True, text=True, env=env).stdout.lower()
    gone = [n for n in ("pip", "setuptools", "wheel") if n + "==" in have]
    if gone:
        subprocess.run([*pip, "uninstall", "-q", "-y", *gone],
                       check=False, capture_output=True, env=env)


def install_packages(py: Path) -> None:
    install_locked(py, lock_file())


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
        # root is apps/ beside it, and a folder of apps with no config and
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
    icon = REPO / "packaging" / "paperpull.ico"
    if icon.is_file():
        shutil.copy2(icon, STAGE / "paperpull.ico")
        say("  icon")
    # PaperPull.exe opens the control panel. The installer's shortcuts start
    # it, and so does the MSIX, whose manifest cannot name a batch file.
    #
    # There used to be a PaperPull.bat for the panel as well. Windows does
    # not tell PaperPull.bat from paperpull.bat, the terminal command staged
    # from the repo, so writing the one replaced the other, and from 0.19.0
    # on no Windows package had a terminal command at all. Nothing written
    # here may share a name with anything staged, whatever the case.
    if not msix.compile_launcher(STAGE, icon if icon.is_file() else None, say):
        raise SystemExit("PaperPull.exe was not built, and it is what opens the panel")

    (STAGE / "README-FIRST.txt").write_text(
        "PaperPull %s\r\n"
        "\r\n"
        "Double-click PaperPull.exe. A window opens running the control panel and\r\n"
        "a browser tab opens to it. Close the window to stop it.\r\n"
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
        "Your existing setup keeps working alongside this one, so there is no\r\n"
        "need to remove anything until you are happy with it.\r\n"
        "\r\n"
        "From a terminal, the same panel's commands are\r\n"
        "  paperpull.bat <app> <command>\r\n"
        "run in this folder.\r\n"
        % version(), encoding="utf-8")
    check_terminal_command()


def check_terminal_command() -> None:
    """The terminal command must reach the package as the repo has it. A
    launcher written over it under another case of the same name is the
    one way it has gone missing before."""
    staged, source = STAGE / "paperpull.bat", REPO / "paperpull.bat"
    if not staged.is_file() or staged.read_bytes() != source.read_bytes():
        raise SystemExit("the staged paperpull.bat is not the terminal command from the repo")
    say("  paperpull.bat is the terminal command")


def write_inno_script() -> Path:
    """The installer definition. Compiled only when Inno Setup is present."""
    iss = DIST / "PaperPull.iss"
    iss.write_text(r"""; PaperPull installer. Compile with Inno Setup 6.
; The release workflow signs this installer and PaperPull.exe inside it with
; Azure Artifact Signing. A local build is unsigned.

#define AppVersion "%(ver)s"

[Setup]
AppName=PaperPull
AppVersion={#AppVersion}
AppPublisher=TNE Enterprises LLC
AppPublisherURL=https://github.com/rheeloaded/paperpull
AppCopyright=Copyright (c) 2026 PaperPull, a trade name of TNE Enterprises LLC
DefaultDirName={localappdata}\PaperPull
DefaultGroupName=PaperPull
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=.
OutputBaseFilename=PaperPull-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=%(arch_allowed)s
ArchitecturesInstallIn64BitMode=%(arch_allowed)s
SetupIconFile=PaperPull\paperpull.ico
UninstallDisplayIcon={app}\paperpull.ico

[InstallDelete]
; The bundled Python is replaced whole, so an upgrade keeps no file the new
; one does not carry, neither an older version of a package nor the old
; interpreter's own files. Nothing of the user's is ever kept in it.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "PaperPull\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PaperPull"; Filename: "{app}\PaperPull.exe"; WorkingDir: "{app}"; IconFilename: "{app}\paperpull.ico"
Name: "{autodesktop}\PaperPull"; Filename: "{app}\PaperPull.exe"; WorkingDir: "{app}"; IconFilename: "{app}\paperpull.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\PaperPull.exe"; Description: "Open PaperPull now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; The program only. The user's downloaders, history and browser profiles are
; wherever they chose to keep them and are never touched by an uninstall.
Type: filesandordirs; Name: "{app}\python"
""" % {"ver": version(),
       # x64compatible lets the x64 installer run on ARM64 Windows too, under
       # emulation.
       "arch_allowed": "x64compatible"},
        encoding="utf-8")
    say("  wrote %s" % iss)
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


def check_python_version(py: Path, expected: str, env: dict | None = None) -> str:
    """The packaged Python's own answer to which version it is, which must
    be the one the build names. The Mac build asks the same question of its
    bundle, and each package's workflow asks it again of what it installed."""
    r = subprocess.run([str(py), "-c", "import platform; print(platform.python_version())"],
                       capture_output=True, text=True, env=env)
    have = r.stdout.strip()
    if r.returncode != 0 or have != expected:
        raise SystemExit("the packaged Python says it is %r, and the build names %s:\n%s"
                         % (have, expected, r.stderr[-800:]))
    say("  packaged Python is %s" % have)
    return have


def smoke_test(py: Path) -> None:
    say("Smoke test")
    check_python_version(py, PY_VERSION)
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
    ap.add_argument("--msix", action="store_true",
                    help="also build the unsigned MSIX for the Microsoft Store")
    # Signing sits between the two halves. PaperPull.exe has to be signed
    # before it is zipped, packed into the MSIX and wrapped by the
    # installer, so a signed build stages first, signs the stage, then
    # packages what was signed. With neither flag it does both, as before.
    ap.add_argument("--stage-only", action="store_true",
                    help="build and test dist\\PaperPull, then stop before any packaging")
    ap.add_argument("--package-only", action="store_true",
                    help="package the dist\\PaperPull already staged, without staging again")
    args = ap.parse_args(argv)
    if args.stage_only and args.package_only:
        say("--stage-only and --package-only are the two halves of one build, pick one.")
        return 2

    if sys.platform != "win32":
        say("This builds the Windows package and runs on Windows.")
        return 1
    host = host_arch()
    if host != ARCH:
        say("This is a %s machine and cannot build the %s package, because the"
            " packages are installed by running the staged Python." % (host, ARCH))
        return 1

    say("PaperPull %s, %s" % (version(), ARCH))
    if args.package_only:
        if not (STAGE / "PaperPull.exe").is_file():
            say("Nothing is staged at %s, run with --stage-only first." % STAGE)
            return 1
    else:
        if STAGE.exists():
            shutil.rmtree(STAGE)
        STAGE.mkdir(parents=True)

        py = stage_python()
        install_packages(py)
        stage_code()
        write_launchers()
        audit()
        smoke_test(py)
        if args.stage_only:
            say()
            say("Staged at dist\\PaperPull. Sign it, then run again with --package-only.")
            return 0
    zip_it()
    if args.msix:
        icon = REPO / "packaging" / "paperpull.ico"
        msix.pack(STAGE, DIST, version(), ico_largest_png(icon), say, arch=ARCH)
    iss = write_inno_script()

    if args.installer:
        # Any major version, wherever it landed. A hardcoded "Inno Setup 6"
        # missed a fresh install of 7 on the very first try.
        iscc = None
        for base in (*msix.program_files(),
                     str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")):
            for c in sorted(Path(base).glob("Inno Setup */ISCC.exe"), reverse=True):
                iscc = str(c)
                break
            if iscc:
                break
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
