"""Compare standalone installs against this repo, and report drift.

The apps used to be thirteen independent copies of the same support code, and
the copies quietly drifted apart — some predated features others had. The
shared core removed the duplication, and this script is what keeps it removed:
run it against a folder of installs to see, at a glance, whether any of them
has fallen behind the repo or is running a stale core.

    python tools/check_installs.py "D:\\path\\to\\your\\installs"

Only code is compared. Nothing that IS an install — config.json, progress and
discovery state, the CSVs, the PDFs, the browser profile — is read or
reported, so this is safe to run against a private archive and safe to paste
the output of.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APPS = REPO / "apps"

# an install's own data, never compared and never reported
PRIVATE = re.compile(
    r"(config\.json|config\..*\.json|progress\.json|discovery\.json|"
    r"run-summary\.txt|new-this-run\.txt|.*\.csv|.*\.pdf)$", re.I)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def app_for(install: Path) -> Path | None:
    """Match an install to its repo app by the orchestrator's filename."""
    for entry in list(install.glob("*_docs.py")) + list(install.glob("*_receipts.py")):
        candidate = APPS / entry.stem.rsplit("_", 1)[0]
        if candidate.is_dir():
            return candidate
    return None


def core_version(install: Path) -> str:
    # Windows: .venv\Lib\site-packages, posix: .venv/lib/pythonX.Y/site-packages
    for site in (install / ".venv").rglob("paperpull_core/__init__.py"):
        m = re.search(r'__version__ = "([^"]+)"', site.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    return "not installed"


def repo_core_version() -> str:
    m = re.search(r'__version__ = "([^"]+)"',
                  (REPO / "core" / "paperpull_core" / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def compare(install: Path) -> dict:
    app = app_for(install)
    if app is None:
        return {"install": install.name, "status": "unrecognised", "app": None}
    differing, missing = [], []
    for f in sorted(app.glob("*.py")) + sorted(app.glob("*.bat")):
        if PRIVATE.search(f.name):
            continue
        theirs = install / f.name
        if not theirs.exists():
            missing.append(f.name)
        elif digest(theirs) != digest(f):
            differing.append(f.name)
    return {
        "install": install.name,
        "app": app.name,
        "status": "in sync" if not (differing or missing) else "DRIFTED",
        "differs": differing,
        "missing": missing,
        "core": core_version(install),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="folder containing your installs")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"Not a folder: {root}")
        return 2

    want_core = repo_core_version()
    results = [compare(d) for d in sorted(root.iterdir())
               if d.is_dir() and any(d.glob("*.py"))]
    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    drifted = 0
    print(f"repo core: {want_core}\n")
    for r in results:
        if r["status"] == "unrecognised":
            print(f"  {r['install']:34} (not a PaperPull install - skipped)")
            continue
        core = r["core"]
        note = "" if core == want_core else f"  [core {core}]"
        print(f"  {r['install']:34} {r['status']}{note}")
        for f in r["differs"]:
            print(f"        differs: {f}")
        for f in r["missing"]:
            print(f"        missing: {f}")
        if r["status"] != "in sync" or core != want_core:
            drifted += 1
    print(f"\n{len(results) - drifted} in sync, {drifted} needing attention.")
    if drifted:
        print("To bring one back in line, copy the app's .py/.bat files over it and\n"
              "re-run its setup.bat (your config, state, PDFs and profile are untouched).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
