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

WHICH CORE IT TESTS

This checkout's own, whichever environment runs the suite. An
environment's installed copy was what an app suite imported before, and
that was not always this core. apps/walmart/.venv and apps/target/.venv
hold a plain copy from 2026-09-23 that shadows their editable install,
so those two suites tested a core six days old, and in a worktree every
other app suite tested the main checkout's core rather than the
worktree's, so a change to the core never met the apps at all. Found
2026-09-29, when a new Walmart test could not import what the core it
was written against provides.

WHERE A SUITE FAILED

For a failing suite this used to print pytest's assertion lines and throw
the rest of its output away. On 2026-09-30 a GitHub test failed on CI with
"Page.goto: net::ERR_ABORTED" and nothing else, and since the app visits
that page twice, the log could not say which visit it was. So each failure
is now printed with every frame of its traceback, file, line and function,
and the exception it ended with. tools/pytest_plugins/where_it_failed.py
writes them down as pytest holds them. The whole output of a failing suite
is kept in test-output/<suite>.log, and on CI it is printed as well, in a
group that opens with a click, because a CI run cannot be asked again.

WHAT IT PRINTS

Somebody may paste the summary into a public issue, so it is built from
what may leave rather than cleaned afterwards. A frame's file is printed
relative to the checkout or to the library that holds it, never as a path
on the machine, so no home folder or user name appears. Line numbers,
function names and exception types come from source code. pytest's own
wrapper around an import error is named without its message, which holds
the module's full path.

The exception's message is the one piece of free text, and it can hold
only what the test held. So no test may read anything of the person
running it, an install, a config, the panel's settings or a browser it
did not start itself. A census of a full run on 2026-10-01, an audit hook
in every Python process the run started, recorded each file opened,
listed or even looked for outside a test's own temp folder, the
interpreter and the files git tracks, and found none of those. What it did
find was programs being looked for, VERSION files, and one check that the
panel's settings file exists, which was never read. The whole output can
carry more than the summary, which is why it stays in a file on this
machine and is printed in full only on CI, where there is nothing of
anybody's to carry.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The plugin that writes down where each failure happened. Its folder holds
# nothing else, so putting it on a suite's path cannot shadow a module.
PLUGINS = REPO / "tools" / "pytest_plugins"
WHERE = "where_it_failed"
WHERE_FILE = "PAPERPULL_WHERE_IT_FAILED"
# A failing suite's whole output, one file per suite, from the latest run.
OUTPUT = REPO / "test-output"

DETAILED = 5          # failures per suite printed with their frames
NAMED = 20            # failures named after those, one line each
FRAMES_HEAD = 10      # a deeper traceback keeps its two ends
FRAMES_TAIL = 20
MESSAGE_LINES = 6
WIDTH = 160
ANNOUNCE = {"call": "FAILED", "setup": "ERROR at setup of",
            "teardown": "ERROR at teardown of", "collect": "ERROR collecting"}


def with_this_core(*after) -> dict:
    """The environment a suite runs in, this checkout's core first."""
    env = dict(os.environ)
    rest = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "core")] + [str(p) for p in after] + rest)
    return env

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


def run_suite(d: Path, py: Path, timeout: int = 1800):
    """Run one suite. Its whole output, its exit code, and each failure as
    the plugin wrote it down."""
    fd, record = tempfile.mkstemp(prefix="paperpull-where-", suffix=".jsonl")
    os.close(fd)
    env = with_this_core(PLUGINS)
    env[WHERE_FILE] = record
    try:
        r = subprocess.run([str(py), "-m", "pytest", "-q", "--no-header",
                            "-rsfE", "-p", "no:cacheprovider", "-p", WHERE],
                           cwd=d, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=env)
        failures = read_failures(record)
    finally:
        try:
            os.remove(record)
        except OSError:
            pass
    return (r.stdout or "") + (r.stderr or ""), r.returncode, failures


def read_failures(path) -> list:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return [r for r in out if isinstance(r, dict)]


def printable_place(filename, root: Path, libraries) -> str:
    """A frame's file in a form that may be printed. Relative to the
    checkout or to the library that holds it, never a path on the machine
    that ran it, so a home folder or a user name cannot appear."""
    filename = str(filename)
    if filename.startswith("<"):
        known = re.fullmatch(r"<string>|<stdin>|<frozen [\w.]{1,60}>", filename)
        return filename if known else "<generated>"
    full = os.path.abspath(filename)
    key = os.path.normcase(full)
    bases = [str(p) for p in libraries if p] + [str(root)]
    for base in sorted(bases, key=len, reverse=True):
        b = os.path.normcase(os.path.abspath(base)).rstrip("\\/") + os.sep
        if key.startswith(b):
            return full[len(b):].replace(os.sep, "/")
    return "<elsewhere>/" + os.path.basename(full)


def _frame_lines(exc: dict, root: Path, libraries) -> list:
    frames = [f for f in (exc.get("frames") or []) if isinstance(f, list) and len(f) == 3]
    left_out = int(exc.get("left_out") or 0)
    head, tail = frames, []
    if len(frames) > FRAMES_HEAD + FRAMES_TAIL:
        head, tail = frames[:FRAMES_HEAD], frames[-FRAMES_TAIL:]
        left_out += len(frames) - FRAMES_HEAD - FRAMES_TAIL
    elif left_out:
        at = int(exc.get("after") or 0)
        head, tail = frames[:at], frames[at:]

    def line(f):
        name, number, func = f
        return "  %s:%d in %s" % (printable_place(name, root, libraries), int(number), str(func)[:60])

    return ([line(f) for f in head]
            + (["  ... %d frames left out" % left_out] if left_out else [])
            + [line(f) for f in tail])


def _exception_lines(exc: dict) -> list:
    kind = str(exc.get("type") or "an exception")[:WIDTH]
    if kind.startswith("_pytest.") and not exc.get("frames"):
        # pytest's own wrapper, raised around something shown above it.
        # Its message restates that, with the machine's paths in it.
        return ["  " + kind]
    said = [ln.rstrip() for ln in str(exc.get("message") or "").splitlines() if ln.strip()]
    out = ["  " + (kind + ": " + said[0] if said else kind)[:WIDTH]]
    out += ["    " + ln[:WIDTH] for ln in said[1:MESSAGE_LINES]]
    if len(said) > MESSAGE_LINES:
        out.append("    ... %d more lines" % (len(said) - MESSAGE_LINES))
    return out


def where_it_failed(output: str, failures: list, root: Path = REPO) -> list:
    """What to print about a failing suite. Each failure with every frame
    of its traceback and the exception that ended it, as the plugin wrote
    them down, then any failure that raised nothing, from pytest's own
    summary. With no record at all, pytest's failure lines, as before."""
    lines = output.splitlines()
    if not failures:
        said = [ln.rstrip()[:WIDTH] for ln in lines if ln.startswith(("FAILED ", "ERROR ", "E   "))]
        return said[:40] or [ln.rstrip()[:WIDTH] for ln in lines if ln.strip()][-10:]

    out = []
    for n, rec in enumerate(failures):
        head = "%s %s" % (ANNOUNCE.get(rec.get("when"), "FAILED"), rec.get("nodeid") or "")
        if n >= DETAILED + NAMED:
            out.append("... and %d more" % (len(failures) - n))
            break
        out.append(head[:WIDTH * 2])
        if n >= DETAILED:
            continue
        detail = []
        try:
            libraries = rec.get("libraries") or []
            for i, chain in enumerate(rec.get("errors") or []):
                if i:
                    detail.append("  and inside that group")
                for j, exc in enumerate(chain if isinstance(chain, list) else []):
                    if not isinstance(exc, dict):
                        continue
                    if j:
                        detail.append("  which led to")
                    detail += _frame_lines(exc, root, libraries) + _exception_lines(exc)
        except (TypeError, ValueError, AttributeError):
            detail = ["  (what the plugin wrote about this failure could not be read)"]
        out += detail

    # pytest's summary names a test relative to the folder the suite ran in,
    # so a failure is matched by that form, and a param id may hold " - ".
    starts = [i for i, ln in enumerate(lines) if "short test summary info" in ln]
    known = {str(k) for rec in failures for k in (rec.get("nodeid"), rec.get("as_summarized")) if k}
    for ln in (lines[starts[-1] + 1:] if starts else []):
        if ln.startswith(("FAILED ", "ERROR ")):
            said = ln.split(" ", 1)[1].rstrip()
            if not any(said == k or said.startswith(k + " - ") for k in known):
                out.append(ln.rstrip()[:WIDTH])
    return out


def keep_whole_output(name: str, output: str, ci=None, folder=None, stream=None) -> None:
    """Keep a failing suite's whole pytest output where it can be read in
    full. A file on this machine, and on CI a group in the log that opens
    with a click, since a CI run cannot be asked again."""
    stream = stream or sys.stdout
    if ci is None:
        ci = os.environ.get("GITHUB_ACTIONS") == "true"
    path = Path(folder or OUTPUT) / (name + ".log")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    except OSError:
        path = None
    if ci:
        # Commands stay off while the output goes by, so a line of test
        # output that happens to start with two colons is shown, not run.
        token = uuid.uuid4().hex
        stream.write("::group::%s, the whole pytest output\n" % name)
        stream.write("::stop-commands::%s\n" % token)
        stream.write(output.rstrip("\n") + "\n")
        stream.write("::%s::\n" % token)
        stream.write("::endgroup::\n")
    elif path is not None:
        try:
            shown = path.resolve().relative_to(REPO).as_posix()
        except ValueError:
            shown = str(path)
        stream.write("       whole output in %s\n" % shown)
    stream.flush()


def clear_old_output(folder=None) -> None:
    """The folder holds the latest run only, so a file in it never
    describes a suite that has since passed."""
    for p in Path(folder or OUTPUT).glob("*.log"):
        try:
            p.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="core and gui only")
    args = ap.parse_args()

    try:
        # A character the console cannot show is written escaped, not
        # allowed to stop the run halfway through a failing suite's output.
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    spares = candidates()
    passed = failed = skipped = 0
    broken, under_equipped, skip_lines = [], [], []
    t0 = time.time()
    clear_old_output()

    for name, d, kind in suites(args.quick):
        py, lack = python_for(d, kind, spares)
        if py is None:
            print("%-4s %-16s no interpreter at all" % ("FAIL", name))
            broken.append((name, "no interpreter"))
            continue
        if lack:
            under_equipped.append((name, lack))
        out, returncode, failures = run_suite(d, py)
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
        ok = returncode in (0, 5)
        if not ok:
            broken.append((name, summary))
        print("%-4s %-16s %s" % ("ok" if ok else "FAIL", name, summary[:92]), flush=True)
        if not ok:
            # Which test, where, and what it raised. A run in CI that said
            # only "1 failed" in core could not be told apart from a flaky
            # timing test or a real break without rerunning it by hand, and
            # one that gave only the assertion could not say which of two
            # visits to the same page had failed.
            for ln in where_it_failed(out, failures):
                print("       " + ln, flush=True)
            keep_whole_output(name, out)

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
