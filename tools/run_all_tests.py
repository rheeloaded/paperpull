"""Run every test in the repository, and say plainly what did not run.

    python tools/run_all_tests.py
    python tools/run_all_tests.py --quick     core and gui only
    python tools/run_all_tests.py --jobs 4    four suites at a time
    python tools/run_all_tests.py --shard 2/4 the second of four parts, for CI
    python tools/run_all_tests.py --stop      stop this checkout's run
    python tools/run_all_tests.py --replace   stop it, then run again

Sixty-odd suites live here: the shared core, the control panel, the server
image's own checks, and one per app. Nothing gathered them, so "the tests
pass" meant whichever ones the person happened to run, with whichever
interpreter they happened to use.

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

Each suite runs with the environment holding the newest Playwright that
can import what the suite needs, and of two holding the same, the earlier
in the list, the panel's first. An environment is asked with this
checkout's core on its path, as its suite will have it, so one that has
no core installed can still run an app suite. A run uses one environment
wherever it can, as CI does, and any suite with nothing to run it is
reported rather than skipped quietly.

Until 2026-10-05 a suite ran in its app's own environment, or else the
first that could run it. CI and the packaged app install the newest
Playwright, 1.63 then, and so did the panel's environment here, while the
app environments held 1.62, so 60 of the 61 app suites ran on 1.62. The
two differ in what a page hands over. When Chromium gave back an empty
body for an answer that had a length, 1.62 asked the address again
whatever the answer was, and 1.63 does that only for fonts, images,
scripts, stylesheets and the like, so a document, a fetch or an xhr now
reads empty. AAFMAA's capture failed on CI because of it and passed every
time here. So a suite that still has to run on an older Playwright than
another suite of the same run makes the run fail, and the summary names
the version every suite ran on.

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

SIDE BY SIDE

Sixty-three suites one after another took an hour and a half on this
machine by October 2026, and the rule is the whole suite before every
push. So suites run several at a time, longest first, which brings a run
down to about the length of the longest suite. --jobs says how many, and
the default is a quarter of the processors, at most six, or
PAPERPULL_TEST_JOBS when it is set. Each suite is still its own pytest
process with its own interpreter, and no test binds a fixed port, so they
do not meet. A suite that runs past its time limit is a failing suite,
never the end of the whole run.

On macOS and Linux every suite is in the runner's process group, so Ctrl+C,
a closed terminal or a kill of the run's group reaches every suite as it
reaches the runner. Ending one suite that ran out of time follows the
processes that suite started instead. Until 2026-10-03 it ended the
suite's process group, which is the runner's, so the first suite out of
time ended the runner and every suite with it.

ONE RUN AT A TIME

Several sessions run the suites on this machine, and two runs at once made
both slow. A run takes a lock first, and a second run waits for it,
saying whose run it is waiting for. The lock is the operating system's,
held by an open file, so it goes with the process however that ends. A run
of the same checkout is not waited for, because its answer would be about
an older tree. This run stops and names it instead, --replace stops the
earlier one and goes ahead, and --stop only stops it, with every process
it started. A run started inside a test does not take the lock.

PARTS ON CI

On CI the suites are split by --shard K/N, balanced by how long each took
on a full run (tools/suite_times.json, refreshed by --write-times), so
several runners together finish in about the time of the longest part.
Each part refuses to pass on what it ran, and the privacy canary runs in
the part that holds the core.

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
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The plugin that writes down where each failure happened. Its folder holds
# nothing else, so putting it on a suite's path cannot shadow a module.
PLUGINS = REPO / "tools" / "pytest_plugins"
WHERE = "where_it_failed"
WHERE_FILE = "PAPERPULL_WHERE_IT_FAILED"
# A failing suite's whole output, one file per suite, from the latest run.
OUTPUT = REPO / "test-output"
# How long each suite took on a full run. The longest start first, and the
# parts on CI are balanced by it. A suite not listed counts as a middling one.
TIMES = REPO / "tools" / "suite_times.json"
# Set for every suite this runs, so a run started inside one never waits
# for the lock its own run holds.
IN_RUN = "PAPERPULL_IN_TEST_RUN"
LOCK_DIR = Path(os.environ.get("PAPERPULL_TEST_LOCK_DIR")
                or Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "PaperPull-dev")

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
    "server": (),
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
_ASKED: dict = {}

# What an interpreter is asked, once. The modules it can import, and the
# version of the Playwright it holds, None when it holds none.
ASK = """
import importlib.metadata, importlib.util, json, sys
found = [m for m in sys.argv[1:] if importlib.util.find_spec(m) is not None]
version = None
if "playwright" in found:
    try:
        version = importlib.metadata.version("playwright")
    except Exception:
        version = "unknown"
print(json.dumps({"found": found, "playwright": version}))
"""


def venv_python(d: Path):
    for rel in ("Scripts/python.exe", "bin/python"):
        p = d / ".venv" / rel
        if p.is_file():
            return p
    return None


def asked(py: Path) -> dict:
    """What this interpreter can import and which Playwright it holds,
    asked once each, with this checkout's core on its path as its suite
    will have it. Nothing at all when it cannot say."""
    key = str(py)
    if key not in _ASKED:
        answer = {"found": [], "playwright": None}
        try:
            r = subprocess.run([str(py), "-c", ASK, *WHY], capture_output=True, text=True,
                               env=with_this_core(PLUGINS), timeout=300)
            said = json.loads(r.stdout.strip().splitlines()[-1])
            version = said.get("playwright")
            answer = {"found": [str(m) for m in said.get("found") or []],
                      "playwright": None if version is None else str(version)}
        except (OSError, subprocess.SubprocessError, ValueError, IndexError, AttributeError, TypeError):
            pass
        _ASKED[key] = answer
    return _ASKED[key]


def has(py: Path, modules) -> set:
    """Which of `modules` this interpreter can import."""
    return set(asked(py)["found"]) & set(modules)


def playwright_of(py: Path):
    """The version of the Playwright this interpreter holds, None when it
    holds none."""
    return asked(py)["playwright"]


def version_key(version) -> tuple:
    """A version as numbers, so 1.100 comes after 1.63. Empty when there is
    none to read."""
    m = re.match(r"\d+(?:\.\d+)*", str(version or ""))
    return tuple(int(n) for n in m.group(0).split(".")) if m else ()


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
    out = [("core", REPO / "core", "core"), ("gui", REPO / "gui", "gui"),
           ("server", REPO / "server", "server")]
    if not quick:
        out += [(d.name, d, "app") for d in sorted((REPO / "apps").iterdir())
                if d.is_dir() and not d.name.startswith(".") and (d / "tests").is_dir()]
    return out


def python_for(d: Path, kind: str, spares: list):
    """The environment holding the newest Playwright that can import what
    the suite needs, and of two holding the same, the earlier in the list.
    The suite's own environment is one of them, with no turn of its own.
    When none can, the one missing least. None when there is nothing here
    at all."""
    need = NEEDS[kind]
    pool = list(spares)
    own = venv_python(d)
    if own and str(own) not in [str(p) for p in pool]:
        pool.append(own)
    able = [py for py in pool if len(has(py, need)) == len(need)]
    if able:
        # max keeps the first of several equal, the earlier in the list.
        return max(able, key=lambda py: version_key(playwright_of(py))), []
    best, lack = None, None
    for py in pool:
        missing = sorted(set(need) - has(py, need))
        if lack is None or len(missing) < len(lack):
            best, lack = py, missing
    return best, (lack or [])


def older_playwright(work: list):
    """The newest Playwright among the environments a run uses, and each
    suite run on another one, as (name, version, interpreter). A suite
    whose environment holds no Playwright is not counted here. One that
    needed it is named among those missing something."""
    held = [(name, playwright_of(py), py) for name, _d, py in work]
    known = [v for _name, v, _py in held if version_key(v)]
    if not known:
        return None, []
    newest = max(known, key=version_key)
    return newest, [(name, v, py) for name, v, py in held
                    if v is not None and version_key(v) != version_key(newest)]


# Every pytest this run has started and not yet seen end, so an interrupted
# run can end them too rather than leave them running on their own.
_RUNNING: set = set()
_RUNNING_LOCK = threading.Lock()


def stop_tree(pid: int) -> None:
    """End a process and everything it started. On Windows a process's
    children outlive it, so the whole tree is ended by its root.

    On POSIX this used to end the process group the process was in. Every
    suite is in the runner's group (see run_suite), so a suite out of time
    ended the runner and every suite beside it, and a test ending a process
    it had started ended its own pytest. Now the root is paused, so it
    starts nothing more, the tree below it is read, and each process in it
    is ended, along with each process group one of them leads, such as a
    browser started in a session of its own. The group the caller is in is
    never ended whole. A process whose parent had already gone is out of
    reach, as it is for taskkill /T."""
    if not pid or pid <= 1 or pid == os.getpid():
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGSTOP)
    except OSError:
        pass
    try:
        mine = os.getpgrp()
        for p in [pid] + descendants(pid):
            if p == os.getpid():
                continue
            try:
                if p != mine and os.getpgid(p) == p:
                    os.killpg(p, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
    finally:
        # Never left paused, however the loop ended. A second Ctrl+C while
        # the tree was read left a suite frozen and the runner waiting on it.
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def descendants(pid: int) -> list:
    """Every process below pid, its children first, as the system lists them
    now. Read from /proc on Linux, which needs no ps, and from ps elsewhere.
    Empty when neither can say."""
    parent_of = {}
    if sys.platform.startswith("linux"):
        try:
            entries = [e for e in os.listdir("/proc") if e.isdigit()]
        except OSError:
            entries = []
        for e in entries:
            try:
                # Bytes, since the kernel cuts a program's name at 15 bytes,
                # which can split a letter. The name follows the pid in
                # parentheses and may hold one itself, so the fields after it
                # are found from the last.
                with open("/proc/%s/stat" % e, "rb") as f:
                    stat = f.read()
                parent_of[int(e)] = int(stat[stat.rindex(b")") + 2:].split()[1])
            except (OSError, ValueError, IndexError):
                pass
    else:
        try:
            listing = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="],
                                     capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            listing = ""
        for line in listing.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
                parent_of[int(fields[0])] = int(fields[1])
    children = {}
    for child, parent in parent_of.items():
        children.setdefault(parent, []).append(child)
    found, seen, todo = [], {pid}, [pid]
    while todo:
        for child in children.get(todo.pop(0), []):
            if child not in seen:
                seen.add(child)
                found.append(child)
                todo.append(child)
    return found


def run_suite(d: Path, py: Path, timeout: int = 1800):
    """Run one suite. Its whole output, its exit code, and each failure as
    the plugin wrote it down. A suite that runs out of time is ended with
    everything it started and comes back as a failure that says so."""
    fd, record = tempfile.mkstemp(prefix="paperpull-where-", suffix=".jsonl")
    os.close(fd)
    env = with_this_core(PLUGINS)
    env[WHERE_FILE] = record
    env[IN_RUN] = "1"
    try:
        # Left in the runner's process group, so Ctrl+C, a closed terminal or
        # a kill of the run's group reaches the suite as it reaches the
        # runner. Tried on 2026-10-03, a session of its own heard none of
        # them, and the runner passing them on still lost suites. So
        # stop_tree follows what the suite started instead of ending a group.
        proc = subprocess.Popen([str(py), "-m", "pytest", "-q", "--no-header",
                                 "-rsfE", "-p", "no:cacheprovider", "-p", WHERE],
                                cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace", env=env)
        with _RUNNING_LOCK:
            _RUNNING.add(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            stop_tree(proc.pid)
            out, err = proc.communicate()
            err = (err or "") + "\ntimed out after %ds, the suite was stopped\n" % timeout
            code = -1
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(proc)
        failures = read_failures(record)
    finally:
        try:
            os.remove(record)
        except OSError:
            pass
    return (out or "") + (err or ""), code, failures


def stop_everything() -> None:
    with _RUNNING_LOCK:
        running = list(_RUNNING)
    for proc in running:
        stop_tree(proc.pid)


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


# -- how many at once, in which order, which part ----------------------------

def default_jobs() -> int:
    try:
        return max(1, int(os.environ.get("PAPERPULL_TEST_JOBS", "")))
    except ValueError:
        return max(1, min(6, (os.cpu_count() or 4) // 4))


def load_times(path=None) -> dict:
    try:
        data = json.loads(Path(path or TIMES).read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def expected(name: str, times: dict) -> float:
    if name in times:
        return times[name]
    known = sorted(times.values())
    return known[len(known) // 2] if known else 60.0


def longest_first(names: list, times: dict) -> list:
    return sorted(names, key=lambda n: (-expected(n, times), n))


def shard_of(names: list, times: dict, k: int, n: int) -> list:
    """The suites of part k of n. Each suite, longest first, goes to the
    part with the least time so far, so every runner works out the same
    parts and they finish close together."""
    parts = [[0.0, []] for _ in range(n)]
    for name in longest_first(names, times):
        i = min(range(n), key=lambda p: (parts[p][0], p))
        parts[i][0] += expected(name, times)
        parts[i][1].append(name)
    return parts[k - 1][1]


def parse_shard(text: str):
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", text or "")
    if not m or not 1 <= int(m.group(1)) <= int(m.group(2)):
        raise SystemExit("--shard takes K/N with 1 <= K <= N, such as 2/4")
    return int(m.group(1)), int(m.group(2))


# -- one run at a time on this machine ---------------------------------------

def same_checkout(a, b) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


class RunLock:
    """The machine's one run at a time. Held by an open file, so it is let
    go however the process that holds it ends, and never needs clearing."""

    def __init__(self, folder=None):
        self.folder = Path(folder or LOCK_DIR)
        self.file = None

    @property
    def info(self) -> Path:
        return self.folder / "test-run.json"

    def holder(self) -> dict:
        try:
            data = json.loads(self.info.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def try_take(self) -> bool:
        self.folder.mkdir(parents=True, exist_ok=True)
        f = open(self.folder / "test-run.lock", "a+")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.file = f
        self.info.write_text(json.dumps({"pid": os.getpid(), "checkout": str(REPO),
                                         "started": time.strftime("%Y-%m-%d %H:%M:%S")}),
                             encoding="utf-8")
        return True

    def release(self) -> None:
        if self.file is None:
            return
        try:
            self.info.unlink()
        except OSError:
            pass
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.file.close()
        self.file = None


def take_turn(lock: RunLock, replace: bool):
    """Wait for another checkout's run on this machine to end. None when
    this run may go ahead, else the exit code to stop with."""
    said = 0.0
    while not lock.try_take():
        who = lock.holder()
        if same_checkout(who.get("checkout", ""), REPO):
            if replace:
                print("stopping the earlier run of this checkout, pid %s, started %s"
                      % (who.get("pid"), who.get("started")), flush=True)
                stop_tree(int(who.get("pid") or 0))
                time.sleep(2)
                continue
            print("An earlier run of this same checkout is still going, pid %s, started %s, "
                  "and its answer would be about an older tree. Stop it with --stop, or stop "
                  "it and run this one with --replace." % (who.get("pid"), who.get("started")),
                  flush=True)
            return 3
        if time.time() - said >= 60:
            print("waiting for the run of %s, pid %s, started %s"
                  % (who.get("checkout") or "another checkout", who.get("pid"), who.get("started")),
                  flush=True)
            said = time.time()
        time.sleep(5)
    return None


def stop_earlier(lock: RunLock) -> int:
    if lock.try_take():
        lock.release()
        print("no run is going on this machine")
        return 0
    who = lock.holder()
    if not same_checkout(who.get("checkout", ""), REPO):
        print("the run going is the one of %s, pid %s, so it was left alone"
              % (who.get("checkout") or "another checkout", who.get("pid")))
        return 1
    stop_tree(int(who.get("pid") or 0))
    print("stopped the run of this checkout, pid %s, started %s, and what it started"
          % (who.get("pid"), who.get("started")))
    return 0


# -- the run -----------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="core and gui only")
    ap.add_argument("--jobs", type=int, default=None,
                    help="suites run at once, %d here by default" % default_jobs())
    ap.add_argument("--shard", default=None, metavar="K/N",
                    help="only part K of N, balanced by tools/suite_times.json")
    ap.add_argument("--stop", action="store_true",
                    help="stop a run of this checkout that is still going")
    ap.add_argument("--replace", action="store_true",
                    help="stop a run of this checkout that is still going, then run")
    ap.add_argument("--write-times", action="store_true",
                    help="keep this run's suite times in tools/suite_times.json")
    args = ap.parse_args(argv)

    try:
        # A character the console cannot show is written escaped, not
        # allowed to stop the run halfway through a failing suite's output.
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    lock = RunLock()
    if args.stop:
        return stop_earlier(lock)
    if not (os.environ.get(IN_RUN) or os.environ.get("PYTEST_CURRENT_TEST")):
        code = take_turn(lock, args.replace)
        if code is not None:
            return code
    try:
        return run(args)
    finally:
        lock.release()


def run(args) -> int:
    jobs = max(1, args.jobs or default_jobs())
    times = load_times()
    plan = suites(args.quick)
    if args.shard:
        k, n = parse_shard(args.shard)
        mine = set(shard_of([name for name, _, _ in plan], times, k, n))
        plan = [s for s in plan if s[0] in mine]
        print("part %d of %d, %d suites" % (k, n, len(plan)), flush=True)
    if jobs > 1:
        order = longest_first([name for name, _, _ in plan], times)
        plan = sorted(plan, key=lambda s: order.index(s[0]))

    spares = candidates()
    passed = failed = skipped = 0
    broken, under_equipped, skip_lines = [], [], []
    took = {}
    t0 = time.time()
    clear_old_output()

    # Every environment is asked before any suite is given one, since the
    # newest Playwright is found by asking them all, and all at once, since
    # each start of an interpreter here can take seconds.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(asked, spares))
    work = []
    for name, d, kind in plan:
        py, lack = python_for(d, kind, spares)
        if py is None:
            print("%-4s %-16s no interpreter at all" % ("FAIL", name))
            broken.append((name, "no interpreter"))
            continue
        if lack:
            under_equipped.append((name, lack))
        work.append((name, d, py))
    newest, older = older_playwright(work)
    if jobs > 1 and len(work) > 1:
        print("%d suites, %d at a time, longest first" % (len(work), min(jobs, len(work))), flush=True)

    def one(item):
        name, d, py = item
        started = time.time()
        out, returncode, failures = run_suite(d, py)
        return name, out, returncode, failures, time.time() - started

    def report(name, out, returncode, failures, seconds):
        nonlocal passed, failed, skipped
        took[name] = round(seconds)
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        summary = lines[-1] if lines else "no output"
        for n, kindword in re.findall(r"(\d+) (passed|failed|skipped|error)", summary):
            if kindword == "passed":
                passed += int(n)
            elif kindword == "skipped":
                skipped += int(n)
            else:
                failed += int(n)
        skip_lines.extend(ln for ln in out.splitlines() if ln.startswith("SKIPPED"))
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

    # Suites run in worker threads and are reported here, one at a time, as
    # each ends, so the lines of two suites never mix.
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(one, item) for item in work]
        try:
            for fut in as_completed(futures):
                report(*fut.result())
        except BaseException:
            for fut in futures:
                fut.cancel()
            stop_everything()
            raise

    print("\n" + "=" * 72)
    print("%d passed, %d failed, %d skipped, in %.0fs"
          % (passed, failed, skipped, time.time() - t0))
    if newest:
        without = sum(1 for _name, _d, py in work if playwright_of(py) is None)
        if older:
            on_newest = len(work) - without - len(older)
            print("%d suite%s ran on Playwright %s and %d on an older one, named below"
                  % (on_newest, "" if on_newest == 1 else "s", newest, len(older)))
        elif without:
            print("every suite ran on Playwright %s, apart from %d whose environment has none"
                  % (newest, without))
        else:
            print("every suite ran on Playwright %s" % newest)

    if skip_lines:
        print("\nwhat did not run:")
        for ln in sorted(set(skip_lines)):
            print("   " + ln.strip()[:110])

    if under_equipped:
        print("\nsuites run by an environment missing something they wanted:")
        for name, lack in under_equipped:
            print("   %-16s %s" % (name, ", ".join("%s (%s)" % (m, WHY[m]) for m in lack)))

    if older:
        print("\nsuites run on an older Playwright than %s, the newest this run used" % newest)
        for name, version, py in older:
            print("   %-16s %s, in %s" % (name, version, printable_place(py, REPO, [])))

    for name, summary in broken:
        print("FAILING SUITE  %-14s %s" % (name, summary))

    keep_times(took, write=args.write_times and not args.quick and not args.shard)

    refused = False
    if any(CANARY in ln for ln in skip_lines):
        print("\nTHE PRIVACY CANARY DID NOT RUN.")
        print("It is the only test holding the promise that a failure file")
        print("carries no page content, so this run proves nothing about it.")
        print("   pip install playwright && python -m playwright install chromium")
        refused = True
    if older:
        print("\nNOT EVERY SUITE RAN ON PLAYWRIGHT %s." % newest)
        print("CI and the packaged app install the newest Playwright, and two versions")
        print("can differ in what a page hands over, so a pass on an older one says")
        print("nothing about them. Upgrade Playwright in each environment named above,")
        print("or give the one holding the newest what those suites need.")
        refused = True
    if refused or broken:
        return 1
    print("\nall suites passed, privacy canary included")
    return 0


def keep_times(took: dict, write: bool) -> None:
    """This run's times beside its output, and in tools/suite_times.json
    when asked, which is what orders the next run and splits CI."""
    if not took:
        return
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "times.json").write_text(json.dumps(dict(sorted(took.items())), indent=1) + "\n",
                                           encoding="utf-8")
        if write:
            merged = {**load_times(), **took}
            TIMES.write_text(json.dumps({k: round(v) for k, v in sorted(merged.items())}, indent=1) + "\n",
                             encoding="utf-8")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
