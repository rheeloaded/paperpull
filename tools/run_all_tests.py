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

Not being skipped is not the same as having run. Until 2026-10-07 a run
refused only a skip that named the canary, and said "privacy canary
included" whenever it passed. On 2026-10-06 all four parts of the CI run
of 290b9f74 ended with that line while only the part holding the core
suite had run the canary, and a canary deleted, renamed or deselected, or
a core suite that collected nothing, would have read the same. pytest
runs each suite quietly, so its output names no test that passed. So the
plugin now writes down how each test of core/tests/test_failure_canary.py
ended, a run that holds the core suite passes only when every test
collected there ran and passed, and a part on CI without the core suite
says which part runs the canary.

WHICH INTERPRETER RUNS WHAT

Each suite runs with the environment holding the newest Playwright that
can import what the suite needs, pytest included, and of two holding the
same, the earlier in the list, the panel's first. An environment is asked
from the checkout's root with this checkout's core on its path, as its
suite will have it, so one that has no core installed can still run an
app suite. A run uses one environment wherever it can, as CI does, and
any suite with nothing to run it is reported rather than skipped quietly,
as is any environment that could not say what it holds.

Until 2026-10-05 a suite ran in its app's own environment, or else the
first that could run it. CI and the packaged app install the newest
Playwright, 1.63 then, and so did the panel's environment here, while the
app environments held 1.62, so 60 of the 61 app suites ran on 1.62. The
two differ in what a page hands over. When Chromium gave back an empty
body for an answer that had a length, 1.62 asked the address again
whatever the answer was, and 1.63 does that only for fonts, images,
scripts, stylesheets and the like, so a document, a fetch or an xhr now
reads empty. AAFMAA's capture failed on CI because of it and passed
here. So a suite that uses Playwright and still has to run on an older
one than another such suite of the same run makes the run fail, and the
summary names the version they ran on. The server's suite never starts
a browser and is not held to it. Nor is the panel's, which starts
Playwright's own Chromium only to drive the panel's own page
(gui/tests/test_download_again_in_a_browser.py).

Each Playwright is made for one Chromium build and downloads that one,
while a test that starts Chromium itself, with a debugging port as
login.bat does, takes the newest full build installed. On 2026-10-05 the
newest Playwright's own build was not installed here, so those tests ran
Chromium 151 while CI and the packaged app ran 153. A run now refuses to
pass while the newest Playwright's own build is missing.

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
never the end of the whole run. The limit is twice what the suite took on
a full run (tools/suite_times.json), and never less than half an hour.

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
the module's full path. What it says about the canary is counts and
words of its own.

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
# The test file whose every test the plugin writes down, passed or not.
OUTCOMES_OF = "PAPERPULL_OUTCOMES_OF"
# A failing suite's whole output, one file per suite, from the latest run.
OUTPUT = REPO / "test-output"
# How long each suite took on a full run. The longest start first, and the
# parts on CI are balanced by it. A suite not listed counts as a middling one.
TIMES = REPO / "tools" / "suite_times.json"
# How long a suite may run before it is stopped as hung, LIMIT_TIMES as
# long as it took on a full run, as tools/suite_times.json has it, and never
# less than SUITE_LIMIT_S. Every suite once had the same 1800 seconds, and
# core took 1655 to 1718 of them in full runs on 2026-10-06. Two lands that
# day had it stopped at 99% with nothing failed while other sessions ran
# tests beside them. An hour for every suite, which came next, let a small
# suite that hung hold a run up for that hour.
SUITE_LIMIT_S = 1800
LIMIT_TIMES = 2
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

# What a suite has to be able to import before it is worth running. pytest
# runs every suite, so an environment without it runs none, however new
# its Playwright.
NEEDS = {
    "core": ("pytest", "pypdf", "playwright", "openpyxl", "pdfplumber"),
    "gui": ("pytest", "fastapi"),
    "server": ("pytest",),
    "app": ("pytest", "paperpull_core", "pypdf", "playwright"),
}
WHY = {
    "pytest": "running the suite at all",
    "paperpull_core": "every app suite",
    "playwright": "the privacy canary and every browser test",
    "pypdf": "PDF validation",
    "openpyxl": "the purchases and transactions workbooks",
    "pdfplumber": "reading transactions out of statement PDFs",
    "fastapi": "the control panel",
}
CANARY = "test_failure_canary"
# The suite that runs the canary, and the canary's file in that suite's
# folder. A run that holds the suite passes only when every test collected
# there ran and passed. Should the canary move to another suite, as a split
# of the core suite once planned, this names that suite.
CANARY_SUITE = "core"
CANARY_FILE = "tests/%s.py" % CANARY
_ASKED: dict = {}
ASK_WITHIN = 300

# What an interpreter is asked, once. The modules it can import, the
# version of the Playwright it holds, the Chromium build that Playwright
# was made for, and the folder that Playwright is in, each None when there
# is none to say.
ASK = """
import importlib.metadata, importlib.util, json, os, sys
found = [m for m in sys.argv[1:] if importlib.util.find_spec(m) is not None]
version = chromium = package = None
if "playwright" in found:
    try:
        version = importlib.metadata.version("playwright")
    except Exception:
        version = "unknown"
    try:
        package = importlib.util.find_spec("playwright").submodule_search_locations[0]
        with open(os.path.join(package, "driver", "package", "browsers.json"), encoding="utf-8") as f:
            chromium = next(str(b["revision"]) for b in json.load(f)["browsers"] if b["name"] == "chromium")
    except Exception:
        chromium = None
print(json.dumps({"found": found, "playwright": version, "chromium": chromium, "package": package}))
"""


def venv_python(d: Path):
    for rel in ("Scripts/python.exe", "bin/python"):
        p = d / ".venv" / rel
        if p.is_file():
            return p
    return None


def asked(py: Path) -> dict:
    """What this interpreter can import, which Playwright it holds, the
    Chromium build that was made for and the folder that Playwright is in,
    asked once each, with this checkout's core on its path as its suite
    will have it. Asked from the checkout's root, so the folder a run was
    started from adds nothing. When it cannot say, nothing at all, and why,
    in words that name no place."""
    key = str(py)
    if key not in _ASKED:
        answer = {"found": [], "playwright": None, "chromium": None, "package": None, "failed": None}
        try:
            r = subprocess.run([str(py), "-c", ASK, *WHY], capture_output=True, text=True,
                               cwd=str(REPO), env=with_this_core(PLUGINS), timeout=ASK_WITHIN)
        except subprocess.TimeoutExpired:
            answer["failed"] = "did not answer within %ds" % ASK_WITHIN
        except (OSError, subprocess.SubprocessError):
            answer["failed"] = "could not be started"
        else:
            try:
                said = json.loads(r.stdout.strip().splitlines()[-1])
                version, chromium = said.get("playwright"), said.get("chromium")
                package = said.get("package")
                answer.update(found=[str(m) for m in said.get("found") or []],
                              playwright=None if version is None else str(version),
                              chromium=None if chromium is None else str(chromium),
                              package=None if package is None else str(package))
            except (ValueError, IndexError, AttributeError, TypeError):
                answer["failed"] = "gave no answer that could be read, and ended with code %s" % r.returncode
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
    """The newest Playwright among the environments the suites handed in
    run in, and each of them run on another one, as (name, version,
    interpreter). A suite whose environment holds no Playwright is not
    counted here. One that needed it is named among those missing
    something."""
    held = [(name, playwright_of(py), py) for name, _d, py in work]
    known = [v for _name, v, _py in held if version_key(v)]
    if not known:
        return None, []
    newest = max(known, key=version_key)
    return newest, [(name, v, py) for name, v, py in held
                    if v is not None and version_key(v) != version_key(newest)]


def from_env(name: str):
    """A setting read the way Playwright reads one, the variable itself and
    then the two names npm gives it. A variable that is set, even to
    nothing, is the answer, and npm's names are not read then."""
    for key in (name, "npm_config_" + name.lower(), "npm_package_config_" + name.lower()):
        value = os.environ.get(key)
        if value is not None:
            return value
    return None


def browsers_folder(package=None, cwd=None):
    """Where the Playwright in the folder `package` keeps the browsers it
    downloads, when it is used from the folder `cwd`, by Playwright's own
    rules. They are the rules the core's browser module follows to find
    Chromium for a test that starts one itself (_playwright_root), and a
    test holds the two together. None when PLAYWRIGHT_BROWSERS_PATH is 0,
    a folder inside Playwright's own package, and there is no package."""
    override = from_env("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        if not package:
            return None
        folder = Path(package) / "driver" / "package" / ".local-browsers"
    elif override:
        folder = Path(override)
    elif sys.platform == "win32":
        folder = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ms-playwright"
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        folder = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"
    if not folder.is_absolute():
        folder = Path(os.path.abspath(os.path.join(from_env("INIT_CWD") or cwd or os.getcwd(), folder)))
    return folder


def chromium_builds(folder) -> list:
    """The full Chromium builds Playwright finished installing in folder,
    newest first. A test that starts Chromium itself takes the first."""
    out = []
    for p in (Path(folder).glob("chromium-*") if folder else []):
        m = re.fullmatch(r"chromium-(\d+)", p.name)
        if m and (p / "INSTALLATION_COMPLETE").is_file():
            out.append(int(m.group(1)))
    return sorted(out, reverse=True)


def own_chromium(newest, work: list):
    """The Chromium build the newest Playwright of a run was made for, None
    when no environment holding it could say."""
    for _name, _d, py in work:
        build = asked(py)["chromium"]
        if newest and version_key(playwright_of(py)) == version_key(newest) and build and build.isdigit():
            return build
    return None


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


def run_suite(d: Path, py: Path, timeout: int = SUITE_LIMIT_S):
    """Run one suite. Its whole output, its exit code, and what the plugin
    wrote down, each failure and how each test of the suite's own canary
    file ended, which only the core suite has. A suite that runs out of
    time is ended with everything it started and comes back as a failure
    that says so."""
    fd, record = tempfile.mkstemp(prefix="paperpull-where-", suffix=".jsonl")
    os.close(fd)
    env = with_this_core(PLUGINS)
    env[WHERE_FILE] = record
    env[OUTCOMES_OF] = str(d / CANARY_FILE)
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
        records = read_records(record)
    finally:
        try:
            os.remove(record)
        except OSError:
            pass
    return (out or "") + (err or ""), code, records


def stop_everything() -> None:
    with _RUNNING_LOCK:
        running = list(_RUNNING)
    for proc in running:
        stop_tree(proc.pid)


def read_records(path) -> list:
    """Each line the plugin wrote that can be read, a failure or a line
    about how a test of the canary's file ended."""
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
    summary. With no record at all, pytest's failure lines, as before.
    What the plugin wrote about how each canary test ended is no failure
    and is left out here."""
    failures = [rec for rec in failures if "outcome_of" not in rec]
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


# -- the privacy canary ------------------------------------------------------

def canary_counts(records: list) -> dict:
    """How the canary's tests ended, as the plugin wrote it down, in counts.
    Every test collected, and of those, how many passed their setup, the
    test itself and their teardown, how many failed one of them, how many
    were skipped, how many never ran, as a deselected one does, and how
    many started and did not finish."""
    phases = {}
    for rec in records:
        name = rec.get("outcome_of") if isinstance(rec, dict) else None
        if not isinstance(name, str):
            continue
        ended = phases.setdefault(name, {})
        if rec.get("when") != "collected":
            ended[str(rec.get("when"))] = rec.get("outcome")
    counts = {"tests": len(phases), "passed": 0, "failed": 0, "skipped": 0,
              "never ran": 0, "did not finish": 0}
    for ended in phases.values():
        outcomes = set(ended.values())
        if "failed" in outcomes:
            counts["failed"] += 1
        elif "skipped" in outcomes:
            counts["skipped"] += 1
        elif not ended:
            counts["never ran"] += 1
        elif outcomes == {"passed"} and set(ended) == {"setup", "call", "teardown"}:
            counts["passed"] += 1
        else:
            counts["did not finish"] += 1
    return counts


def canary_refusal(folder, counts, skipped: bool) -> list:
    """What to print when a run that holds the canary's suite, whose folder
    is folder, did not see every test of the canary pass, or when a skip
    names the canary anywhere. folder is None when the run does not hold
    that suite. Nothing when neither is so. Counts and words of this file
    only, since somebody may paste it into a public issue."""
    counts = counts or canary_counts([])
    ran = 0 < counts["passed"] == counts["tests"]
    if not skipped and (ran or folder is None):
        return []
    lines = ["THE PRIVACY CANARY DID NOT PASS." if counts["failed"]
             else "ONLY PART OF THE PRIVACY CANARY RAN." if 0 < counts["passed"] < counts["tests"]
             else "THE PRIVACY CANARY DID NOT RUN."]
    place = "%s/%s" % (Path(folder).name, CANARY_FILE) if folder is not None else ""
    if folder is not None and not counts["tests"]:
        lines.append("The %s suite ran none of the tests in %s." % (CANARY_SUITE, place)
                     if (Path(folder) / CANARY_FILE).is_file()
                     else "%s is missing, so none of its tests ran." % place)
    elif folder is not None and not ran:
        said = ["%d passed" % counts["passed"]] + [
            "%d %s" % (counts[k], k if k != "skipped" else "was skipped" if counts[k] == 1 else "were skipped")
            for k in ("failed", "skipped", "never ran", "did not finish") if counts[k]]
        lines.append("Of the %d test%s in %s, %s." % (
            counts["tests"], "" if counts["tests"] == 1 else "s", place,
            said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]))
    lines += ["It is the only test holding the promise that a failure file",
              "carries no page content, so this run proves nothing about it."]
    if skipped:
        lines.append("   pip install playwright && python -m playwright install chromium")
    return lines


def canary_part(names: list, times: dict, n: int):
    """Which of n parts of a run holds the canary's suite. None when no
    part does."""
    return next((k for k in range(1, n + 1) if CANARY_SUITE in shard_of(names, times, k, n)), None)


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


def limit_of(name: str, times: dict) -> int:
    """How long the suite may run before it is stopped as hung. A suite not
    listed gets SUITE_LIMIT_S, as every suite once did."""
    return int(max(SUITE_LIMIT_S, LIMIT_TIMES * times.get(name, 0)))


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
    """Whether two paths are one checkout. An empty one is none, where
    os.path.abspath would take it for the current folder."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


class RunLock:
    """The machine's one run at a time. Held by an open file, so it is let
    go however the process that holds it ends, and never needs clearing.

    test-run.json beside it says whose run holds it. For a moment each time
    the lock changes hands, the lock is held while that file is missing or
    half written, since release() removes it before letting go, try_take()
    writes it after taking hold, and writing it empties it first. A holder
    read then names no checkout, and is another run until it says so."""

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
        # The file goes first. Removed after letting go, it could be the
        # next holder's.
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
    this run may go ahead, else the exit code to stop with.

    A run whose checkout is not known yet is waited for and read again.
    Taken for this checkout's, it stopped a run waiting from the checkout's
    root, as land starts one, with 3 the moment the lock changed hands."""
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
            if who.get("checkout"):
                print("waiting for the run of %s, pid %s, started %s"
                      % (who["checkout"], who.get("pid"), who.get("started")), flush=True)
            else:
                print("waiting for a run whose checkout is not known yet", flush=True)
            said = time.time()
        time.sleep(5)
    return None


def stop_earlier(lock: RunLock) -> int:
    if lock.try_take():
        lock.release()
        print("no run is going on this machine")
        return 0
    who = lock.holder()
    if not who.get("checkout"):
        # Read the moment the lock changed hands. Taken for this checkout's
        # run, it was said to be stopped and nothing was.
        print("the checkout of the run going is not known yet, so it was left alone. "
              "Try again in a moment.")
        return 1
    if not same_checkout(who["checkout"], REPO):
        print("the run going is the one of %s, pid %s, so it was left alone"
              % (who["checkout"], who.get("pid")))
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
    canary = None       # how the canary's tests ended, once the core suite has
    t0 = time.time()
    clear_old_output()

    # Every environment is asked before any suite is given one, since the
    # newest Playwright is found by asking them all, and all at once, since
    # each start of an interpreter here can take seconds.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(asked, spares))
    unasked = [(py, asked(py)["failed"]) for py in spares if asked(py)["failed"]]
    work, counted = [], []
    for name, d, kind in plan:
        py, lack = python_for(d, kind, spares)
        if py is None:
            print("%-4s %-16s no interpreter at all" % ("FAIL", name))
            broken.append((name, "no interpreter"))
            continue
        if lack:
            under_equipped.append((name, lack))
        work.append((name, d, py))
        # Only a suite that needs Playwright is held to the newest one. The
        # server's suite never starts a browser, and the panel's starts one
        # only to drive its own page.
        if "playwright" in NEEDS[kind]:
            counted.append((name, d, py))
    newest, older = older_playwright(counted)
    build = own_chromium(newest, counted)
    builds, lacking, own_folders = [], [], False
    if build:
        # A suite's tests look where the Playwright it runs on keeps browsers,
        # from the folder the suite runs in. That is one folder for the whole
        # run, unless PLAYWRIGHT_BROWSERS_PATH is 0, when every Playwright
        # keeps its own, or a relative folder, which each suite finds from
        # where it runs. A folder without the build speaks for the run, and
        # when the folder changes with the suite, each suite missing it is
        # named, since no one install then serves them all.
        folder_of = {name: browsers_folder(asked(py)["package"], d)
                     for name, d, py in counted if playwright_of(py)}
        held = {folder: chromium_builds(folder) for folder in dict.fromkeys(folder_of.values())}
        lacking = [(name, d, py) for name, d, py in counted
                   if name in folder_of and int(build) not in held[folder_of[name]]]
        builds = held[folder_of[lacking[0][0]]] if lacking else next(iter(held.values()), [])
        # Asked for two made-up suites, it differs only when it is each suite's own.
        own_folders = browsers_folder("one", "one") != browsers_folder("other", "other")
    if jobs > 1 and len(work) > 1:
        print("%d suites, %d at a time, longest first" % (len(work), min(jobs, len(work))), flush=True)

    def one(item):
        name, d, py = item
        started = time.time()
        out, returncode, records = run_suite(d, py, timeout=limit_of(name, times))
        return name, out, returncode, records, time.time() - started

    def report(name, out, returncode, records, seconds):
        nonlocal passed, failed, skipped, canary
        took[name] = round(seconds)
        if name == CANARY_SUITE:
            canary = canary_counts(records)
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
            for ln in where_it_failed(out, records):
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
        without = sum(1 for _name, _d, py in counted if playwright_of(py) is None)
        if older:
            print("Playwright %s for %d of the suites that use it, an older one for %d, named below"
                  % (newest, len(counted) - without - len(older), len(older)))
        elif without:
            print("Playwright %s for every suite that uses it, apart from %d whose environment has none"
                  % (newest, without))
        else:
            print("Playwright %s for every suite that uses it" % newest)
    if build and int(build) in builds:
        print("and its own Chromium, build %s, for the tests that start one themselves" % build)
    elif build:
        print("but its own Chromium, build %s, is not installed, so the tests that start one "
              "themselves %s" % (build, "take build %d" % builds[0] if builds else "have none to take"))

    if unasked:
        print("\nenvironments that could not say what they hold")
        for py, why in unasked:
            print("   %s, %s" % (printable_place(py, REPO, []), why))

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
    # A run that holds the core suite has to have seen every test of the
    # canary pass. Not being skipped is not enough, since a canary that was
    # deleted, renamed or deselected, or a core that collected nothing, has
    # no skip to show.
    canary_folder = next((d for name, d, _kind in plan if name == CANARY_SUITE), None)
    told = canary_refusal(canary_folder, canary, any(CANARY in ln for ln in skip_lines))
    if told:
        print("\n" + "\n".join(told))
        refused = True
    if older:
        print("\nNOT EVERY SUITE RAN ON PLAYWRIGHT %s." % newest)
        print("CI and the packaged app install the newest Playwright, and two versions")
        print("can differ in what a page hands over, so a pass on an older one says")
        print("nothing about them. Upgrade Playwright in each environment named above,")
        print("or give the one holding the newest what those suites need.")
        refused = True
    if build and int(build) not in builds:
        print("\nPLAYWRIGHT %s'S OWN CHROMIUM, BUILD %s, IS NOT INSTALLED HERE." % (newest, build))
        print("A test that starts Chromium itself takes the newest build installed,")
        print(("%d here" % builds[0] if builds else "and there is none here")
              + ", while CI and the packaged app run %s. Install it with" % build)
        print("   python -m playwright install chromium")
        print("in an environment holding Playwright %s." % newest)
        if own_folders:
            print("With PLAYWRIGHT_BROWSERS_PATH set as it is, each suite looks in a folder of")
            print("its own, and these lack it. Run the install with each one's environment,")
            print("from each one's folder.")
            for name, d, py in lacking:
                print("   %-16s %s, from %s" % (name, printable_place(py, REPO, []), printable_place(d, REPO, [])))
        refused = True
    if refused or broken:
        return 1
    if canary_folder is not None:
        print("\nall suites passed, privacy canary included")
        return 0
    # A part of a CI run without the core says which part runs the canary,
    # since each part's log ended "privacy canary included" until 2026-10-07.
    parts = parse_shard(args.shard)[1] if args.shard else 0
    home = canary_part([name for name, _d, _kind in suites(args.quick)], times, parts) if parts else None
    if home:
        print("\nall suites passed, and the privacy canary runs in part %d of %d, "
              "which holds the %s suite" % (home, parts, CANARY_SUITE))
    else:
        print("\nall suites passed, and the privacy canary was not among them")
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
