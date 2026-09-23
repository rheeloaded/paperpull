"""Run every test in the repository, and say plainly what did not run.

    python tools/run_all_tests.py
    python tools/run_all_tests.py --quick     core and gui only

Fifty suites live here: the shared core, the control panel, and one per
app. Nothing gathered them, so "the tests pass" meant whichever ones the
person happened to run, with whichever interpreter they happened to use.

A SKIPPED TEST IS THE POINT OF THIS SCRIPT

Several suites skip themselves when a library is missing, and the skip is
a quiet line in a summary nobody reads. Two of them are the spreadsheet
exporters. One of them is the privacy canary, which is the only thing
holding the promise that a failure file carries no page content, and it
skips when Playwright is absent. A green run with the canary skipped says
nothing at all about that promise.

So this refuses to report success while the canary has not run, and it
prints every other skip at the end where it can be seen.

WHICH INTERPRETER RUNS WHAT

On a development machine there is rarely one environment that can run
everything. Each app is installed in its own, which is where its copy of
the core lives, while the spreadsheet libraries are only in the panel's.
So each suite is run with the first environment that can actually import
what it needs, and any suite with nothing to run it is reported rather
than skipped quietly. On CI one environment has the lot and all of this
collapses to a single answer.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# What a suite has to be able to import before it is worth running.
NEEDS = {
    "core": ("pypdf", "playwright", "openpyxl", "pdfplumber"),
    "gui": ("fastapi",),
    "app": ("paperpull_core", "pypdf", "playwright"),
}
WHY = {
    "paperpull_core": "every app suite",
    "playwright": "the privacy canary and every browser test",
    "pypdf": "PDF validation",
    "openpyxl": "the purchases and transactions workbooks",
    "pdfplumber": "reading transactions out of statement PDFs",
    "fastapi": "the control panel",
}
CANARY = "test_failure_canary"
_HAS: dict = {}


def venv_python(d: Path):
    for rel in ("Scripts/python.exe", "bin/python"):
        p = d / ".venv" / rel
        if p.is_file():
            return p
    return None


def has(py: Path, modules) -> set:
    """Which of `modules` this interpreter can import. Asked once each."""
    key = str(py)
    if key not in _HAS:
        code = ("import importlib.util,sys;"
                "print(' '.join(m for m in sys.argv[1:] "
                "if importlib.util.find_spec(m) is not None))")
        r = subprocess.run([str(py), "-c", code, *WHY], capture_output=True, text=True)
        _HAS[key] = set(r.stdout.split())
    return _HAS[key] & set(modules)


def candidates() -> list:
    """Every interpreter worth trying, best guess first."""
    out = []
    for c in [venv_python(REPO / "gui"),
              venv_python(REPO / "apps" / "mypay"),
              Path(sys.executable)]:
        if c and Path(c).is_file() and str(c) not in [str(x) for x in out]:
            out.append(Path(c))
    for d in sorted((REPO / "apps").glob("*")):
        p = venv_python(d) if d.is_dir() else None
        if p and str(p) not in [str(x) for x in out]:
            out.append(p)
    return out


def suites(quick: bool) -> list:
    out = [("core", REPO / "core", "core"), ("gui", REPO / "gui", "gui")]
    if not quick:
        out += [(d.name, d, "app") for d in sorted((REPO / "apps").iterdir())
                if d.is_dir() and not d.name.startswith(".") and (d / "tests").is_dir()]
    return out


def python_for(d: Path, kind: str, spares: list):
    """The suite's own environment if it can do the job, else the first
    spare that can. None when nothing here can run it."""
    need = NEEDS[kind]
    own = venv_python(d)
    for py in ([own] if own else []) + spares:
        if len(has(py, need)) == len(need):
            return py, []
    best, lack = None, None
    for py in ([own] if own else []) + spares:
        missing = sorted(set(need) - has(py, need))
        if lack is None or len(missing) < len(lack):
            best, lack = py, missing
    return best, (lack or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="core and gui only")
    args = ap.parse_args()

    spares = candidates()
    passed = failed = skipped = 0
    broken, under_equipped, skip_lines = [], [], []
    t0 = time.time()

    for name, d, kind in suites(args.quick):
        py, lack = python_for(d, kind, spares)
        if py is None:
            print("%-4s %-16s no interpreter at all" % ("FAIL", name))
            broken.append((name, "no interpreter"))
            continue
        if lack:
            under_equipped.append((name, lack))
        r = subprocess.run([str(py), "-m", "pytest", "-q", "--no-header",
                            "-rs", "-p", "no:cacheprovider"],
                           cwd=d, capture_output=True, text=True, timeout=1800)
        out = (r.stdout or "") + (r.stderr or "")
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        summary = lines[-1] if lines else "no output"
        for n, kindword in re.findall(r"(\d+) (passed|failed|skipped|error)", summary):
            if kindword == "passed":
                passed += int(n)
            elif kindword == "skipped":
                skipped += int(n)
            else:
                failed += int(n)
        skip_lines += [ln for ln in out.splitlines() if ln.startswith("SKIPPED")]
        ok = r.returncode in (0, 5)
        if not ok:
            broken.append((name, summary))
        print("%-4s %-16s %s" % ("ok" if ok else "FAIL", name, summary[:92]), flush=True)

    print("\n" + "=" * 72)
    print("%d passed, %d failed, %d skipped, in %.0fs"
          % (passed, failed, skipped, time.time() - t0))

    if skip_lines:
        print("\nwhat did not run:")
        for ln in sorted(set(skip_lines)):
            print("   " + ln.strip()[:110])

    if under_equipped:
        print("\nsuites run by an environment missing something they wanted:")
        for name, lack in under_equipped:
            print("   %-16s %s" % (name, ", ".join("%s (%s)" % (m, WHY[m]) for m in lack)))

    for name, summary in broken:
        print("FAILING SUITE  %-14s %s" % (name, summary))

    if any(CANARY in ln for ln in skip_lines):
        print("\nTHE PRIVACY CANARY DID NOT RUN.")
        print("It is the only test holding the promise that a failure file")
        print("carries no page content, so this run proves nothing about it.")
        print("   pip install playwright && python -m playwright install chromium")
        return 1
    if broken:
        return 1
    print("\nall suites passed, privacy canary included")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
