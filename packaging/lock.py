"""Write the locks the Windows and macOS packages install from, one for each
system and architecture they are built for, every package at one version
with the hashes of its files, from the direct pins in packaging/requirements.in.

    python packaging/lock.py            write every lock
    python packaging/lock.py --check    write nothing, and say whether each
                                        lock is still what this would write

The builders install with --require-hashes, so pip refuses a file whose hash
is not written in the lock and a package not written there at all.

Each lock is resolved for the Python the packages carry (PY_VERSION in
packaging/build_windows.py and build_macos.py) on that system and
architecture, whatever computer runs this, by uv, which can resolve for a
platform other than its own. pip-compile, which server/lock.py runs inside
the server image's base, resolves only for the Python running it. Only
versions with built wheels for the platform are chosen, as the builders
install them, and a Mac lock takes only wheels that run on MACOS_MIN, the
oldest macOS the bundle opens on. That is why there are three, Windows x64
and the two Macs. cryptography has no wheel for Intel Macs after 48.0.1
(49.0.0 dropped x86_64 macOS), and pypdfium2's newest needs a newer macOS
than the bundle promises.

Nothing published after AS_OF is considered, so running this again gives
the same files, and --check shows the committed locks are what
requirements.in gives. Raise a version in requirements.in on purpose, with
a test run, move AS_OF to the day you run this when that version came out
after it, then run this and commit every file it changed.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent
REPO = PACKAGING.parent
sys.path.insert(0, str(PACKAGING))
import build_macos  # noqa: E402
import build_windows  # noqa: E402

UV = "uv==0.12.24"
AS_OF = "2026-10-23T00:00:00Z"
INDEX = "https://pypi.org/simple"
# As the builders' repo-relative name, which uv writes into each "# via" line,
# so a lock reads the same from any checkout.
REQUIREMENTS = "packaging/requirements.in"


def targets() -> list[dict]:
    """Every architecture each builder can build, with the lock it installs."""
    out = []
    for arch in build_windows.ARCHES:
        out.append({"label": "Windows %s" % arch, "platform": build_windows.triple(arch),
                    "python": build_windows.PY_VERSION, "lock": build_windows.lock_file(arch),
                    "macos": None})
    for arch in build_macos.ARCHES:
        out.append({"label": "macOS %s" % arch, "platform": build_macos.triple(arch),
                    "python": build_macos.PY_VERSION, "lock": build_macos.lock_file(arch),
                    "macos": build_macos.MACOS_MIN})
    return out


def header(target: dict) -> str:
    oldest = " on macOS %s and later" % target["macos"] if target["macos"] else ""
    return ("# Every package the %s package installs, with the hashes of its files.\n"
            "# Written by packaging/lock.py from requirements.in, resolved for Python %s\n"
            "# on %s%s, from what PyPI held at %s.\n"
            "# Do not edit by hand. Change requirements.in and run the script.\n"
            % (target["label"], target["python"], target["platform"], oldest, AS_OF))


def command(uv: list[str], target: dict) -> list[str]:
    return [*uv, "pip", "compile", REQUIREMENTS,
            "--python-platform", target["platform"], "--python-version", target["python"],
            "--generate-hashes", "--only-binary", ":all:", "--exclude-newer", AS_OF,
            "--index-url", INDEX, "--custom-compile-command", "python packaging/lock.py",
            "--no-progress", "--quiet"]


def environment(target: dict) -> dict:
    """This machine's environment without anything that would steer uv, so
    every computer resolves the same, and the oldest macOS for a Mac lock."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("UV_") and k != "MACOSX_DEPLOYMENT_TARGET"}
    env["UV_NO_CONFIG"] = "1"
    if target["macos"]:
        env["MACOSX_DEPLOYMENT_TARGET"] = target["macos"]
    return env


def install_uv(folder: Path) -> list[str]:
    """uv at the version UV names, in a virtual environment of its own."""
    subprocess.run([sys.executable, "-m", "venv", str(folder)], check=True)
    py = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", UV],
                   check=True)
    return [str(py), "-m", "uv"]


def resolve(uv: list[str], target: dict) -> str | None:
    done = subprocess.run(command(uv, target), cwd=str(REPO), env=environment(target),
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0 or "--hash=sha256:" not in done.stdout:
        sys.stderr.write(done.stderr[-4000:])
        return None
    return header(target) + done.stdout.replace("\r\n", "\n")


def pins(lock: str) -> int:
    return len(re.findall(r"^[A-Za-z0-9_.-]+==", lock, flags=re.M))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv not in ([], ["--check"]):
        print("usage: python packaging/lock.py [--check]", file=sys.stderr)
        return 2
    check = argv == ["--check"]
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        uv = install_uv(Path(tmp) / "uv")
        for target in targets():
            text = resolve(uv, target)
            if text is None:
                print("The %s lock could not be resolved, and no lock was written. A version in"
                      " requirements.in that came out after %s needs AS_OF in packaging/lock.py"
                      " moved to today." % (target["label"], AS_OF), file=sys.stderr)
                return 1
            written.append((target, text))
    # Every lock or none, so the packages never install from two different days.
    stale = []
    for target, text in written:
        lock = target["lock"]
        rel = lock.relative_to(REPO).as_posix() if lock.is_relative_to(REPO) else str(lock)
        if check:
            same = lock.is_file() and lock.read_text(encoding="utf-8") == text
            print("%s %s" % (rel, "is what requirements.in gives" if same
                             else "is NOT what requirements.in gives"))
            if not same:
                stale.append(rel)
        else:
            lock.write_text(text, encoding="utf-8", newline="\n")
            print("%s holds %d packages for %s." % (rel, pins(text), target["platform"]))
    if stale:
        print("Run python packaging/lock.py and commit what it writes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
