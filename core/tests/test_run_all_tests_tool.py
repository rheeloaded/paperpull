"""tools/run_all_tests.py has to say where a failing suite failed.

On 2026-09-30 a GitHub test failed on CI with "Page.goto: net::ERR_ABORTED"
and nothing more, because the runner kept only pytest's assertion lines
and threw the rest away. The app visits that page twice, and the log could
not say which visit it was, so the failure could not be explained without
a rerun that never reproduced it.

These feed the runner real failing suites, run by pytest with the plugin
that writes down each failure, and check that every frame of each
traceback comes out, in a form that names no folder of the machine it ran
on, that the whole output is kept, and that the run still refuses to pass
without the privacy canary. Not only a skipped canary. A run that holds
the core suite passes only when every test of the canary ran and passed,
and a part of a CI run without the core suite says which part runs it.

They also check that every suite runs on the newest Playwright the
machine holds, as CI and the packaged app do, and that a run where one
could not is refused, and that a suite's counts come from pytest's own
last line, whatever a test's thread printed after it.

And that the core's tests, run as three suites from one folder, run each
file in exactly one of them, the canary in core, and that a core-censuses
or a core-browsers that collects nothing fails.
"""
import dataclasses
import fnmatch
import functools
import importlib.util
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

rat = pytest.importorskip("run_all_tests")


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


# The line numbers below are the ones these files are written with.
SITE = '''
import json

def goto_orders(page):
    return visit(page, "history")

def visit(page, where):
    raise RuntimeError("Page.goto: net::ERR_ABORTED at http://127.0.0.1:5/" + where
                       + "\\nCall log:\\n  - navigating to " + where)

def parse(text):
    return json.loads(text)
'''

TESTS = '''
import pytest
import fake_site

def test_the_walk():
    fake_site.goto_orders(None)

def test_a_parse():
    fake_site.parse("{")

def test_a_cause():
    try:
        {}["x"]
    except KeyError as e:
        raise ValueError("wrapped") from e

@pytest.fixture
def two_cleanups(request):
    def first():
        raise KeyError("first cleanup")
    def second():
        raise OSError("second cleanup")
    request.addfinalizer(first)
    request.addfinalizer(second)
    return 1

def test_two_cleanups(two_cleanups):
    pass

@pytest.mark.xfail(strict=True)
def test_passes_when_it_should_not():
    pass

def test_passes():
    pass
'''


def _checkout(root: Path, tests: str = TESTS) -> Path:
    """A checkout with one app suite in it, laid out like the real one,
    with the real pytest.ini at its root. So pytest's rootdir is the
    checkout while the suite runs from its own folder, and a test is named
    differently in pytest's report and in its summary line, as on CI."""
    (root / "pytest.ini").write_text((REPO / "pytest.ini").read_text(encoding="utf-8"),
                                     encoding="utf-8")
    suite = root / "apps" / "fake"
    _write(suite, "fake_site.py", SITE)
    _write(suite, "tests/test_walk.py", tests)
    return suite


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    root = tmp_path_factory.mktemp("checkout")
    suite = _checkout(root)
    output, code, failures = rat.run_suite(suite, Path(sys.executable), timeout=300)
    return {"root": root, "suite": suite, "output": output, "code": code,
            "failures": failures,
            "lines": rat.where_it_failed(output, failures, root=root)}


def _block(lines: list, head: str) -> list:
    """The lines printed under one failure, up to the next one."""
    i = lines.index(head)
    rest = lines[i + 1:]
    end = next((k for k, ln in enumerate(rest) if not ln.startswith(" ")), len(rest))
    return rest[:end]


def test_a_failure_names_every_frame_of_its_traceback(walked):
    """The case that could not be explained. The frames name the app's
    function that made the visit, so the log says which visit failed."""
    assert walked["code"] == 1
    assert _block(walked["lines"], "FAILED apps/fake/tests/test_walk.py::test_the_walk") == [
        "  apps/fake/tests/test_walk.py:5 in test_the_walk",
        "  apps/fake/fake_site.py:4 in goto_orders",
        "  apps/fake/fake_site.py:7 in visit",
        "  RuntimeError: Page.goto: net::ERR_ABORTED at http://127.0.0.1:5/history",
        "    Call log:",
        "      - navigating to history",
    ]


def test_a_library_frame_is_named_inside_its_library(walked):
    block = _block(walked["lines"], "FAILED apps/fake/tests/test_walk.py::test_a_parse")
    assert block[:2] == ["  apps/fake/tests/test_walk.py:8 in test_a_parse",
                         "  apps/fake/fake_site.py:11 in parse"]
    assert any(re.fullmatch(r"  json/decoder\.py:\d+ in raw_decode", ln) for ln in block), block
    assert block[-1].startswith("  json.decoder.JSONDecodeError: Expecting property name")


def test_a_cause_comes_first_then_what_it_led_to(walked):
    assert _block(walked["lines"], "FAILED apps/fake/tests/test_walk.py::test_a_cause") == [
        "  apps/fake/tests/test_walk.py:12 in test_a_cause",
        "  KeyError: 'x'",
        "  which led to",
        "  apps/fake/tests/test_walk.py:14 in test_a_cause",
        "  ValueError: wrapped",
    ]


def test_each_part_of_a_failed_teardown_is_shown(walked):
    """Two cleanups failing in one teardown reach pytest as one group."""
    block = _block(walked["lines"], "ERROR at teardown of apps/fake/tests/test_walk.py::test_two_cleanups")
    assert block[0].startswith("  ExceptionGroup: errors while tearing down fixture")
    parts = "\n".join(block)
    assert "  and inside that group\n  apps/fake/tests/test_walk.py:19 in first\n  KeyError: 'first cleanup'" in parts
    assert "  and inside that group\n  apps/fake/tests/test_walk.py:21 in second\n  OSError: second cleanup" in parts


def test_a_failure_that_raised_nothing_is_still_named(walked):
    """A strict xfail that passed fails the suite without an exception, so
    the plugin has nothing to write down. pytest's own line names it."""
    assert any(re.match(r"FAILED tests[\\/]test_walk\.py::test_passes_when_it_should_not", ln)
               for ln in walked["lines"]), walked["lines"]


def test_each_failure_is_printed_once(walked):
    """pytest's summary names a test from the suite's folder, its report
    from the checkout's root. A failure the plugin wrote down must not be
    printed a second time from the summary because the names differ."""
    heads = [ln.split(" - ")[0] for ln in walked["lines"] if not ln.startswith(" ")]
    assert [re.sub(r".*::", "", h) for h in heads] == [
        "test_the_walk", "test_a_parse", "test_a_cause", "test_two_cleanups",
        "test_passes_when_it_should_not"], heads


# The summary's name for a test, written down by the plugin for each failure,
# comes from pytest's cwd_relative_nodeid, whose form changed in 9.2.0
# (2026-10-27). The tests above ask whichever pytest runs them, the one
# .github/workflows/tests.yml pins on CI and the one gui/.venv holds here.
# These ask the plugin of a pytest of each form, so both stay read whichever
# one is installed.

def _where_plugin():
    spec = importlib.util.spec_from_file_location("where_it_failed_under_test",
                                                  rat.PLUGINS / "where_it_failed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _from_the_suite(path: str) -> str:
    """A path from the checkout's root made relative to apps/fake, where the
    suite runs, as bestrelpath makes it, with the system's separator."""
    return os.path.join(*Path(path).relative_to("apps/fake").parts)


class _Config_9_1:
    """cwd_relative_nodeid as pytest 9.1.1 has it, a string in, a string out."""

    def cwd_relative_nodeid(self, nodeid):
        base_path_part, *nodeid_part = nodeid.split("::")
        return "::".join([_from_the_suite(base_path_part), *nodeid_part])


@dataclasses.dataclass(frozen=True)
class _NodeId:
    """pytest 9.2.0's structured node id, as much of it as the summary uses."""
    path: str
    names: tuple = ()

    def __str__(self):
        return "::".join((self.path, *self.names))


class _Config_9_2:
    """cwd_relative_nodeid as pytest 9.2.0 has it, a structured id in and out.
    A string has no path, so it raises, as the real one does."""

    def cwd_relative_nodeid(self, nodeid):
        return dataclasses.replace(nodeid, path=_from_the_suite(nodeid.path))


def _report(nodeid: str, structured: bool):
    """A report as pytest hands it to the plugin. A 9.2.0 report carries its
    id in both forms, a 9.1.1 report only the string."""
    if not structured:
        return SimpleNamespace(nodeid=nodeid)
    path, *names = nodeid.split("::")
    return SimpleNamespace(nodeid=nodeid, id=_NodeId(path=path, names=tuple(names)))


@pytest.mark.parametrize("config, structured", [(_Config_9_1(), False), (_Config_9_2(), True)],
                         ids=["pytest 9.1.1", "pytest 9.2.0"])
@pytest.mark.parametrize("nodeid, summarized", [
    ("apps/fake/tests/test_walk.py::test_the_walk", ("tests", "test_walk.py::test_the_walk")),
    ("apps/fake/tests/test_walk.py::TestWalk::test_it[a - b]",
     ("tests", "test_walk.py::TestWalk::test_it[a - b]")),
    ("apps/fake/tests/test_walk.py", ("tests", "test_walk.py")),
], ids=["a test", "a method with a param id", "a module that did not collect"])
def test_the_plugin_names_a_failure_as_the_summary_does(config, structured, nodeid, summarized):
    """Each form of pytest gives the name its summary line prints, relative
    to the suite's folder, so the runner knows that line for one it already
    printed."""
    plugin = _where_plugin()
    got = plugin._as_summarized(SimpleNamespace(config=config), _report(nodeid, structured))
    assert got == os.path.join(*summarized)
    assert isinstance(got, str)


def test_a_pytest_that_cannot_say_leaves_the_failure_named_from_the_root():
    """The plugin must never fail a run. When neither form is taken, the
    failure keeps the name pytest reports it by."""
    class Refuses:
        def cwd_relative_nodeid(self, nodeid):
            raise TypeError("neither")

    plugin = _where_plugin()
    for structured in (False, True):
        report = _report("apps/fake/tests/test_walk.py::test_the_walk", structured)
        assert plugin._as_summarized(SimpleNamespace(config=Refuses()), report) == \
            "apps/fake/tests/test_walk.py::test_the_walk"


def test_nothing_printed_names_a_folder_of_the_machine(walked):
    """Somebody may paste the summary into a public issue. A frame is
    printed relative to the checkout or its library, so neither the
    checkout's place, the home folder nor the interpreter's appears."""
    text = "\n".join(walked["lines"]).lower()
    for place in {walked["root"], Path.home(), Path(json.__file__).parent,
                  Path(sys.prefix), Path(sys.base_prefix)}:
        assert str(place).lower() not in text, place


def _summary(output: str) -> str:
    last = [ln for ln in output.splitlines() if ln.strip()][-1]
    return re.sub(r" in [\d.]+s.*$", "", last)


def _failed_lines(output: str) -> list:
    return sorted(ln.split(" - ")[0] for ln in output.splitlines()
                  if ln.startswith(("FAILED ", "ERROR ")))


def _with_plugin(suite: Path, record, followed: Path) -> subprocess.CompletedProcess:
    """The suite run by pytest with the plugin, writing to record and
    following the tests of the file followed."""
    env = rat.with_this_core(rat.PLUGINS)
    env[rat.WHERE_FILE] = str(record)
    env[rat.OUTCOMES_OF] = str(followed)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-rsfE",
                           "-p", "no:cacheprovider", "-p", rat.WHERE],
                          cwd=suite, capture_output=True, text=True, timeout=300, env=env)


def test_the_plugin_changes_no_outcome(walked, tmp_path):
    """It must never change a run. The same suite without it, with a
    record file it cannot write, and following every test of the suite's
    file, ends exactly the same way."""
    suite = walked["suite"]
    plain = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-rsfE",
                            "-p", "no:cacheprovider"],
                           cwd=suite, capture_output=True, text=True, timeout=300)
    # A folder, so every write fails, the ones about each test followed too.
    blocked = _with_plugin(suite, tmp_path, suite / "tests" / "test_walk.py")
    followed = _with_plugin(suite, tmp_path / "record.jsonl", suite / "tests" / "test_walk.py")
    out = plain.stdout + plain.stderr
    assert _summary(out) == "4 failed, 2 passed, 1 error"
    for other in (walked["output"], blocked.stdout + blocked.stderr, followed.stdout + followed.stderr):
        assert _summary(other) == _summary(out)
        assert _failed_lines(other) == _failed_lines(out)
    assert walked["code"] == plain.returncode == blocked.returncode == followed.returncode == 1


def test_the_plugin_writes_down_how_each_test_of_one_file_ended(walked, tmp_path):
    """Passed or not, and only for the file it is given. A strict xfail
    that passed, and a teardown that failed after a test passed, count as
    failed, as pytest counts them."""
    suite = walked["suite"]
    record = tmp_path / "record.jsonl"
    _with_plugin(suite, record, suite / "tests" / "test_walk.py")
    records = rat.read_records(record)
    followed = [rec for rec in records if "outcome_of" in rec]
    assert {rec["outcome_of"].split("::")[0] for rec in followed} == {"apps/fake/tests/test_walk.py"}
    assert rat.canary_counts(records) == {"tests": 6, "passed": 1, "failed": 5, "skipped": 0,
                                          "never ran": 0, "did not finish": 0}
    assert [(rec["when"], rec.get("outcome")) for rec in followed
            if rec["outcome_of"].endswith("::test_passes")] == [
        ("collected", None), ("setup", "passed"), ("call", "passed"), ("teardown", "passed")]
    # Followed or not, each failure is written down the same way.
    assert [rec["nodeid"] for rec in records if "outcome_of" not in rec] == \
        [rec["nodeid"] for rec in walked["failures"]]
    other = tmp_path / "other.jsonl"
    _with_plugin(suite, other, suite / "fake_site.py")
    assert rat.canary_counts(rat.read_records(other))["tests"] == 0


def test_a_module_that_cannot_import_names_the_line_that_failed(tmp_path):
    """pytest wraps the import error in one of its own, whose message
    carries the module's full path. The wrapper is named and its message
    left out, while the import error under it is printed in full."""
    suite = _checkout(tmp_path, tests="import a_module_nobody_has_installed\n")
    output, code, failures = rat.run_suite(suite, Path(sys.executable), timeout=300)
    lines = rat.where_it_failed(output, failures, root=tmp_path)
    assert code == 2
    assert [ln for ln in lines if not ln.startswith(" ")] == \
        ["ERROR collecting apps/fake/tests/test_walk.py"]
    assert "  apps/fake/tests/test_walk.py:1 in <module>" in lines
    assert "  ModuleNotFoundError: No module named 'a_module_nobody_has_installed'" in lines
    assert any(ln.startswith("  _pytest.") and ": " not in ln for ln in lines), lines
    assert str(tmp_path).lower() not in "\n".join(lines).lower()


# -- what may be printed -------------------------------------------------------

def test_a_place_is_printed_relative_to_the_checkout_or_its_library(tmp_path):
    root = tmp_path / "checkout"
    stdlib = tmp_path / "Python312" / "Lib"
    site = stdlib / "site-packages"
    libs = [str(stdlib), str(site)]
    assert rat.printable_place(root / "apps" / "x" / "x_site.py", root, libs) == "apps/x/x_site.py"
    # site-packages sits inside the standard library's folder, and wins
    assert rat.printable_place(site / "playwright" / "_impl" / "_frame.py", root, libs) == \
        "playwright/_impl/_frame.py"
    assert rat.printable_place(stdlib / "asyncio" / "futures.py", root, libs) == "asyncio/futures.py"
    assert rat.printable_place(tmp_path / "Users" / "jane" / "secret.py", root, libs) == \
        "<elsewhere>/secret.py"


def test_a_generated_file_name_is_printed_only_from_a_fixed_list():
    assert rat.printable_place("<string>", REPO, []) == "<string>"
    assert rat.printable_place("<frozen importlib._bootstrap>", REPO, []) == \
        "<frozen importlib._bootstrap>"
    assert rat.printable_place("<rules for Jane Doe at 12 Elm St>", REPO, []) == "<generated>"


def _record(n_frames: int, nodeid: str = "tests/test_x.py::test_x", where: Path = REPO) -> dict:
    return {"nodeid": nodeid, "when": "call", "libraries": [],
            "errors": [[{"type": "RecursionError", "message": "too deep",
                         "frames": [[str(where / "x.py"), i, "f"] for i in range(1, n_frames + 1)],
                         "left_out": 0, "after": None}]]}


def test_a_deep_traceback_keeps_both_ends():
    lines = rat.where_it_failed("", [_record(100)])
    frames = [ln for ln in lines if ln.startswith("  x.py:")]
    assert len(frames) == rat.FRAMES_HEAD + rat.FRAMES_TAIL
    assert frames[0] == "  x.py:1 in f" and frames[-1] == "  x.py:100 in f"
    assert "  ... 70 frames left out" in lines


def test_many_failures_are_named_after_the_first_few_are_shown():
    records = [_record(1, nodeid="tests/test_x.py::test_%d" % i) for i in range(30)]
    lines = rat.where_it_failed("", records)
    shown = rat.DETAILED + rat.NAMED
    assert [ln for ln in lines if ln.startswith("FAILED ")] == \
        ["FAILED tests/test_x.py::test_%d" % i for i in range(shown)]
    assert lines.count("  x.py:1 in f") == rat.DETAILED
    assert lines[-1] == "... and %d more" % (30 - shown)


def test_a_record_that_cannot_be_read_does_not_stop_the_run():
    bad = {"nodeid": "tests/test_x.py::test_x", "when": "call",
           "errors": [[{"type": "ValueError", "message": "m", "frames": [["x.py", "not a line", "f"]]}]]}
    assert rat.where_it_failed("", [bad, _record(1)]) == [
        "FAILED tests/test_x.py::test_x",
        "  (what the plugin wrote about this failure could not be read)",
        "FAILED tests/test_x.py::test_x",
        "  x.py:1 in f",
        "  RecursionError: too deep",
    ]


def test_with_no_record_the_failure_lines_are_kept_as_before():
    """A plugin that did not load or could not write must not leave a
    failing suite with nothing said about it."""
    output = textwrap.dedent("""
        F
        ___ test_x ___
        >       assert 1 == 2
        E       assert 1 == 2
        tests/test_x.py:2: AssertionError
        =========================== short test summary info ============================
        FAILED tests/test_x.py::test_x - assert 1 == 2
        1 failed in 0.01s
        """)
    assert rat.where_it_failed(output, []) == [
        "E       assert 1 == 2", "FAILED tests/test_x.py::test_x - assert 1 == 2"]
    assert rat.where_it_failed("ERROR: usage\nsomething broke\n", []) == \
        ["ERROR: usage", "something broke"]


def test_what_the_plugin_wrote_about_a_canary_test_is_no_failure():
    """It goes in the same file as each failure. A canary test that was
    collected and passed is not printed as one, and with nothing else
    written down a failing suite still gets pytest's own lines."""
    canary = [{"outcome_of": "core/tests/test_failure_canary.py::test_it", "when": "collected"},
              {"outcome_of": "core/tests/test_failure_canary.py::test_it", "when": "call", "outcome": "passed"}]
    assert rat.where_it_failed("", canary + [_record(1)]) == [
        "FAILED tests/test_x.py::test_x", "  x.py:1 in f", "  RecursionError: too deep"]
    assert rat.where_it_failed("FAILED tests/test_x.py::test_x - assert 1 == 2\n", canary) == \
        ["FAILED tests/test_x.py::test_x - assert 1 == 2"]


# -- the whole output ----------------------------------------------------------

def test_on_ci_the_whole_output_is_a_group_that_runs_no_command(tmp_path):
    """A line of output that looks like a workflow command is shown, not
    obeyed, so a test printing '::endgroup::' cannot end the group."""
    output = "first\n::endgroup::\n::error::not a real error\nlast\n"
    buf = io.StringIO()
    rat.keep_whole_output("fake", output, ci=True, folder=tmp_path, stream=buf)
    lines = buf.getvalue().splitlines()
    assert lines[0] == "::group::fake, the whole pytest output"
    token = re.fullmatch(r"::stop-commands::([0-9a-f]{32})", lines[1]).group(1)
    assert lines[2:6] == output.splitlines()
    assert lines[6:] == ["::%s::" % token, "::endgroup::"]
    assert (tmp_path / "fake.log").read_text(encoding="utf-8") == output


def test_locally_the_whole_output_goes_to_a_file_and_one_line_says_where(tmp_path):
    buf = io.StringIO()
    rat.keep_whole_output("fake", "all of it\n", ci=False, folder=tmp_path, stream=buf)
    assert buf.getvalue() == "       whole output in %s\n" % (tmp_path / "fake.log")
    assert (tmp_path / "fake.log").read_text(encoding="utf-8") == "all of it\n"


def test_the_kept_output_is_never_committed():
    """It is whatever a test printed, and it stays on the machine."""
    rel = rat.OUTPUT.relative_to(REPO).as_posix() + "/core.log"
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO, capture_output=True)
    assert r.returncode == 0, rel + " is not ignored by git"


# -- the run as a whole --------------------------------------------------------

@pytest.fixture
def one_suite(tmp_path, monkeypatch):
    """main() over a single suite of our making, the core, with its output
    kept in tmp_path rather than the checkout's own folder. App suites of
    our making can be handed in too, and the times a run is split by."""
    def make(files: dict, others: dict = None, times: dict = None):
        (tmp_path / "pytest.ini").write_text((REPO / "pytest.ini").read_text(encoding="utf-8"),
                                             encoding="utf-8")
        suite = tmp_path / "core"
        for rel, text in files.items():
            _write(suite, rel, text)
        plan = [("core", suite, "core")]
        for name, its_files in (others or {}).items():
            for rel, text in its_files.items():
                _write(tmp_path / name, rel, text)
            plan.append((name, tmp_path / name, "app"))
        monkeypatch.setattr(rat, "suites", lambda quick: list(plan))
        if times is not None:
            (tmp_path / "times.json").write_text(json.dumps(times), encoding="utf-8")
            monkeypatch.setattr(rat, "TIMES", tmp_path / "times.json")
        monkeypatch.setattr(rat, "candidates", lambda: [])
        monkeypatch.setattr(rat, "python_for", lambda d, kind, spares: (Path(sys.executable), []))
        monkeypatch.setattr(rat, "OUTPUT", tmp_path / "test-output")
        monkeypatch.setattr(sys, "argv", ["run_all_tests.py"])
        # On CI a failing suite's whole output goes into a log group instead
        # of a line naming its file, and the Tests job itself sets
        # GITHUB_ACTIONS, so these runs are made the way a person's machine
        # makes them. The group has its own test above. Left set, the tag of
        # 0.42.0 failed here and nowhere else.
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        # The Chromium build this interpreter's Playwright was made for, in
        # a browsers folder of the test's own, so the run's check of it does
        # not depend on what this machine has installed.
        build = rat.asked(Path(sys.executable))["chromium"]
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                           str(_installed(tmp_path / "browsers", *([build] if build else []))))
        return suite
    return make


def test_a_run_without_the_canary_still_refuses_to_pass(one_suite, capsys):
    one_suite({"tests/test_failure_canary.py": """
        import pytest
        pytest.importorskip("a_module_nobody_has_installed")

        def test_it():
            pass
        """})
    assert rat.main() == 1
    assert "THE PRIVACY CANARY DID NOT RUN" in capsys.readouterr().out


def test_a_run_with_the_canary_passes(one_suite, capsys):
    one_suite({"tests/test_failure_canary.py": "def test_it():\n    pass\n"})
    assert rat.main() == 0
    assert capsys.readouterr().out.rstrip().endswith("all suites passed, privacy canary included")


# Not being skipped is not the same as having run. Until 2026-10-07 a run
# refused only a skip that named the canary, so a canary deleted, renamed
# or deselected, or a core suite that collected nothing, passed and said
# "privacy canary included".

CANARY = "def test_it():\n    pass\n"
ANOTHER = "def test_another():\n    pass\n"
# A conftest that takes the canary's tests named out of the run, as a
# marker or a keyword given to pytest would, and tells pytest so.
DESELECT = """
    def pytest_collection_modifyitems(config, items):
        dropped = [item for item in items if item.nodeid.split("::")[0].endswith("test_failure_canary.py")
                   and item.name in %r]
        config.hook.pytest_deselected(items=dropped)
        items[:] = [item for item in items if item not in dropped]
    """


@pytest.mark.parametrize("files, said", [
    ({"tests/test_another.py": ANOTHER},
     "core/tests/test_failure_canary.py is missing, so none of its tests ran."),
    ({"tests/test_another.py": ANOTHER, "tests/test_privacy_canary.py": CANARY},
     "core/tests/test_failure_canary.py is missing, so none of its tests ran."),
    ({"tests/test_failure_canary.py": CANARY, "tests/conftest.py": "collect_ignore = ['test_failure_canary.py']\n"},
     "The core suite ran none of the tests in core/tests/test_failure_canary.py."),
    ({"tests/test_failure_canary.py": CANARY, "tests/test_another.py": ANOTHER,
      "tests/conftest.py": DESELECT % (["test_it"],)},
     "Of the 1 test in core/tests/test_failure_canary.py, 0 passed and 1 never ran."),
], ids=["deleted", "renamed", "the core collected nothing", "deselected"])
def test_a_run_holding_the_core_refuses_to_pass_unless_the_canary_ran(files, said, one_suite, capsys):
    one_suite(files)
    assert rat.main() == 1
    out = capsys.readouterr().out
    assert ("\nTHE PRIVACY CANARY DID NOT RUN.\n%s\nIt is the only test holding the promise that a "
            "failure file\n" % said) in out, out
    assert "FAILING SUITE" not in out, "the core suite itself passed"
    assert "pip install playwright" not in out, "nothing was skipped"
    assert "all suites passed" not in out


def test_a_canary_that_ran_only_in_part_refuses_and_counts_each_way_it_ended(one_suite, capsys):
    """Counts, never a test's name, since this may be pasted into a public
    issue. The skip brings the line saying what to install."""
    one_suite({"tests/test_failure_canary.py": """
                   import pytest

                   def test_it():
                       pass

                   def test_the_journal():
                       pass

                   def test_needs_a_browser():
                       pytest.skip("no browser available")

                   def test_finds_nothing():
                       assert "CANARYNAME" not in "Orders for " + "CANARYNAME"
                   """,
               "tests/conftest.py": DESELECT % (["test_the_journal"],)})
    assert rat.main() == 1
    out = capsys.readouterr().out
    assert ("\nTHE PRIVACY CANARY DID NOT PASS.\nOf the 4 tests in core/tests/test_failure_canary.py, "
            "1 passed, 1 failed, 1 was skipped and 1 never ran.\n") in out, out
    assert "   pip install playwright && python -m playwright install chromium" in out, out
    assert "FAILING SUITE  core" in out


def test_each_way_a_canary_test_can_end_is_counted():
    def ended(name, **phases):
        return [{"outcome_of": name, "when": "collected"}] + [
            {"outcome_of": name, "when": when, "outcome": outcome} for when, outcome in phases.items()]
    records = (ended("a", setup="passed", call="passed", teardown="passed")
               + ended("b", setup="passed", call="failed", teardown="passed")
               + ended("c", setup="passed", call="passed", teardown="failed")
               + ended("d", setup="skipped", teardown="passed")
               + ended("e")
               + ended("f", setup="passed", call="passed")
               + [_record(1)])
    counts = rat.canary_counts(records)
    assert counts == {"tests": 6, "passed": 1, "failed": 2, "skipped": 1, "never ran": 1, "did not finish": 1}
    assert rat.canary_refusal(REPO / "core", counts, False)[:2] == [
        "THE PRIVACY CANARY DID NOT PASS.",
        "Of the 6 tests in core/tests/test_failure_canary.py, 1 passed, 2 failed, 1 was skipped, "
        "1 never ran and 1 did not finish."]
    some = rat.canary_counts(ended("a", setup="passed", call="passed", teardown="passed") + ended("e"))
    assert rat.canary_refusal(REPO / "core", some, False)[:2] == [
        "ONLY PART OF THE PRIVACY CANARY RAN.",
        "Of the 2 tests in core/tests/test_failure_canary.py, 1 passed and 1 never ran."]
    every = rat.canary_counts(ended("a", setup="passed", call="passed", teardown="passed"))
    assert rat.canary_refusal(REPO / "core", every, False) == []
    assert rat.canary_refusal(None, None, False) == [], "a run without the core is not refused"


def test_a_part_without_the_core_says_which_part_runs_the_canary(one_suite, capsys):
    """CI splits the suites into parts, and the job named tests passes when
    every part does. Each part used to end "privacy canary included",
    while only the part holding the core suite ran it."""
    one_suite({"tests/test_failure_canary.py": CANARY}, others={"aafmaa": {"tests/test_it.py": ANOTHER}},
              times={"core": 100, "aafmaa": 90})
    assert rat.main(["--shard", "2/2", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "\nok   aafmaa " in out and "\nok   core " not in out, out
    assert out.rstrip().endswith("\nall suites passed, and the privacy canary runs in part 1 of 2, "
                                 "which holds the core suite"), out
    assert "privacy canary included" not in out
    assert rat.main(["--shard", "1/2", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "\nok   core " in out and "\nok   aafmaa " not in out, out
    assert out.rstrip().endswith("\nall suites passed, privacy canary included"), out


def test_the_part_holding_the_core_refuses_to_pass_without_the_canary(one_suite, capsys):
    """The others still pass, saying where it runs, and CI's job named
    tests fails with that one part."""
    one_suite({"tests/test_another.py": ANOTHER}, others={"aafmaa": {"tests/test_it.py": ANOTHER}},
              times={"core": 100, "aafmaa": 90})
    assert rat.main(["--shard", "1/2", "--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert "\nTHE PRIVACY CANARY DID NOT RUN.\ncore/tests/test_failure_canary.py is missing" in out, out
    assert "all suites passed" not in out
    assert rat.main(["--shard", "2/2", "--jobs", "1"]) == 0
    assert "the privacy canary runs in part 1 of 2" in capsys.readouterr().out


def test_every_run_holds_the_canary_and_ci_runs_every_part():
    """A run without the canary's suite is not refused, since it never held
    the canary. So the runner's own list of suites always has that suite,
    quick or whole, with the canary in its folder, and CI's matrix runs
    every part the suites are split into. A part left out of the matrix
    could be the one holding the canary, and the job named tests would
    pass with the canary run nowhere."""
    for quick in (False, True):
        folders = [d for name, d, _kind in rat.suites(quick) if name == rat.CANARY_SUITE]
        assert folders == [REPO / "core"], quick
        assert (folders[0] / rat.CANARY_FILE).is_file()
    workflow = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    parts = int(re.search(r"--shard \$\{\{ matrix\.part \}\}/(\d+) ", workflow).group(1))
    matrix = re.search(r"^ +part: \[([\d, ]+)\]$", workflow, re.M).group(1)
    assert sorted(int(k) for k in matrix.split(",")) == list(range(1, parts + 1))


def test_a_failing_suite_in_a_run_prints_its_frames_and_keeps_its_output(one_suite, capsys, tmp_path):
    one_suite({"tests/test_failure_canary.py": "def test_it():\n    pass\n",
               "tests/test_broken.py": "def test_it():\n    assert 'print' == 'screen'\n"})
    assert rat.main() == 1
    out = capsys.readouterr().out
    assert "       FAILED core/tests/test_broken.py::test_it\n" in out
    assert "test_broken.py::test_it - " not in out, "printed twice"
    # The suite sits outside the checkout here, so only its file's name shows.
    assert "         <elsewhere>/test_broken.py:2 in test_it\n" in out
    assert "         AssertionError: assert 'print' == 'screen'\n" in out
    kept = tmp_path / "test-output" / "core.log"
    assert "       whole output in %s\n" % kept in out
    assert "1 failed, 1 passed" in kept.read_text(encoding="utf-8")


# On 2026-10-07 a run printed "ok   core   Exception occurred during
# processing of request from ('127.0.0.1', 55033)" and counted none of the
# core's 11537 passed and 305 skipped tests. A test's server had written
# socketserver's message after pytest's own last line, and the runner took
# whatever a suite printed last as its summary. A suite's stderr is read
# into its output as it is written, so a thread writing there once pytest
# is done lands after that line.
LATE = """
    import atexit, sys

    def _late():
        print("-" * 40, file=sys.%s)
        print("Exception occurred during processing of request from ('127.0.0.1', 55033)", file=sys.%s)

    atexit.register(_late)
    """
SKIPS = """
    import pytest

    def test_another():
        pass

    def test_not_here():
        pytest.skip("nothing to ask")
    """


@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_a_line_printed_after_pytests_own_last_line_is_not_the_summary(stream, one_suite, capsys):
    one_suite({"tests/test_failure_canary.py": CANARY, "tests/test_another.py": SKIPS,
               "tests/conftest.py": LATE % (stream, stream)})
    assert rat.main() == 0
    out = capsys.readouterr().out
    assert re.search(r"(?m)^ok   core +2 passed, 1 skipped in \d+\.\d\ds$", out), out
    assert "\n2 passed, 0 failed, 1 skipped, in " in out, out
    assert "Exception occurred" not in out, out
    skip = "SKIPPED [1] %s:7: nothing to ask" % os.path.join("tests", "test_another.py")
    assert "\nwhat did not run:\n   %s\n" % skip in out, out
    assert out.rstrip().endswith("all suites passed, privacy canary included"), out


def test_a_suite_stopped_for_time_says_so_whatever_pytest_printed_before():
    """A suite that hangs once pytest has printed its last line, on a
    thread that never ends, is stopped by the runner, and its line says
    that rather than how its tests went."""
    out = "..\n2 passed in 0.31s\nException occurred\n\ntimed out after 60s, the suite was stopped\n"
    assert rat.summary_of(out, -1) == "timed out after 60s, the suite was stopped"
    assert rat.summary_of(out, 1) == "2 passed in 0.31s"


@pytest.mark.parametrize("line", [
    "11537 passed, 305 skipped, 3 xfailed in 1188.23s (0:19:48)",
    "1 failed, 1 passed in 0.52s",
    "1 error in 0.12s",
    "no tests ran in 0.01s",
    "3 passed, 2 warnings, 1 deselected in 1.01s",
    "===== 3 passed in 0.12s =====",
])
def test_each_shape_of_pytests_last_line_is_the_summary(line):
    out = "....\nFAILED x.py::test_x - AssertionError\n%s\nException occurred\n" % line
    assert rat.summary_of(out, 0) == line


def test_with_no_line_of_pytests_the_last_line_is_the_summary():
    assert rat.summary_of("INTERNALERROR> a crash\n3 passed through the proxy\n\n", 3) == \
        "3 passed through the proxy"
    assert rat.summary_of("\n  \n", 0) == "no output"


# -- which Playwright each suite runs on ----------------------------------------
#
# CI and the packaged app install the newest Playwright and the Chromium it
# was made for. On the machine the whole suite runs on before every push,
# the panel's environment held 1.63 and the app environments 1.62, and 60
# of the 61 app suites ran on 1.62, in their own environment or one they
# borrowed. 1.63 stopped asking an address again when Chromium gave back an
# empty body for a document, a fetch or an xhr, and on 2026-10-05 AAFMAA's
# capture failed on CI because of it while it passed there. These build
# real environments whose packages are nothing but a name and a version, so
# the runner asks real interpreters what they hold. They leave the core off
# the path and work from a folder of their own, so only the runner can put
# the core where a suite finds it.

# The Chromium build each fake Playwright says it was made for.
CHROMIUM_FOR = {"1.62.0": "1234", "1.63.0": "1243", "1.64.0": "1250"}


@functools.lru_cache(maxsize=None)
def _site(py: Path) -> Path:
    """Where an environment keeps its packages."""
    return Path(subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                               check=True, capture_output=True, text=True, timeout=300).stdout.strip())


def _environment(folder: Path, packages: dict) -> Path:
    """An environment at folder/.venv holding each package named, empty
    but for its version, and nothing else. A Playwright also says which
    Chromium build it was made for, where a real one says it."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(folder / ".venv")],
                   check=True, capture_output=True, timeout=300)
    py = rat.venv_python(folder)
    site = _site(py)
    for name, version in packages.items():
        (site / name).mkdir(parents=True)
        (site / name / "__init__.py").write_text("", encoding="utf-8")
        info = site / ("%s-%s.dist-info" % (name, version))
        info.mkdir()
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: %s\nVersion: %s\n" % (name, version),
                                       encoding="utf-8")
        if name == "playwright":
            driver = site / name / "driver" / "package"
            driver.mkdir(parents=True)
            (driver / "browsers.json").write_text(json.dumps({"browsers": [
                {"name": "chromium-headless-shell", "revision": "1"},
                {"name": "chromium", "revision": CHROMIUM_FOR[version]}]}), encoding="utf-8")
    return py


# The panel's holds what CI and the packaged app hold. An app's own is a
# version behind, and so is the only one that can read a workbook, and the
# only one with what the panel's suite needs. One has a browser and nothing
# to read a PDF with, one has the newest Playwright and no pytest, one has
# everything the core suite needs but Playwright, and one has all of it.
HOLDING = {
    "panel": {"pytest": "9.1.1", "playwright": "1.63.0", "pypdf": "6.19.0"},
    "app": {"pytest": "9.1.1", "playwright": "1.62.0", "pypdf": "6.16.1"},
    "spreadsheets": {"pytest": "9.1.1", "playwright": "1.62.0", "pypdf": "6.16.1",
                     "openpyxl": "3.1.5", "pdfplumber": "0.11.10"},
    "panel_ui": {"pytest": "9.1.1", "playwright": "1.62.0", "fastapi": "0.141.1"},
    "browser_only": {"pytest": "9.1.1", "playwright": "1.63.0"},
    "no_pytest": {"playwright": "1.64.0", "pypdf": "6.20.0"},
    "no_browser": {"pytest": "9.1.1", "pypdf": "6.19.0", "openpyxl": "3.1.5", "pdfplumber": "0.11.10"},
    "everything": {"pytest": "9.1.1", "playwright": "1.63.0", "pypdf": "6.19.0",
                   "openpyxl": "3.1.5", "pdfplumber": "0.11.10"},
}


@pytest.fixture(scope="module")
def environments(tmp_path_factory):
    """Each one's folder and interpreter. Made side by side, since a new
    environment can take seconds on Windows."""
    root = tmp_path_factory.mktemp("environments")
    with ThreadPoolExecutor(len(HOLDING)) as pool:
        made = dict(zip(HOLDING, pool.map(lambda n: _environment(root / n, HOLDING[n]), HOLDING)))
    return {n: (root / n, py) for n, py in made.items()}


@pytest.fixture
def asked_afresh(monkeypatch, tmp_path):
    """Every interpreter asked again in this test, from a folder of its own
    and with the core off the path."""
    monkeypatch.setattr(rat, "_ASKED", {})
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.chdir(tmp_path)


def _installed(folder: Path, *builds, unfinished=()) -> Path:
    """A browsers folder holding the full Chromium builds named, each one
    finished as Playwright finishes one, and the unfinished ones without the
    mark Playwright leaves when it is done."""
    for build in builds + tuple(unfinished):
        (folder / ("chromium-%s" % build)).mkdir(parents=True)
        if build in builds:
            (folder / ("chromium-%s" % build) / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
    return folder


def test_a_suite_runs_on_the_newest_playwright_here_not_its_own_older_one(environments, asked_afresh):
    """What hid AAFMAA's failure. An app suite went to its own environment
    first, and one without its own to another app's, because the panel's
    has no core installed and was asked without the core the runner gives
    every suite."""
    folder, own = environments["app"]
    _, panel = environments["panel"]
    assert rat.python_for(folder, "app", [panel]) == (panel, [])
    assert rat.python_for(folder, "app", [own, panel]) == (panel, []), "the earlier went first, not the newest"


def test_of_two_with_the_same_playwright_the_earlier_runs_it(environments, asked_afresh, tmp_path):
    """So a run uses one environment wherever it can, as CI does."""
    _, panel = environments["panel"]
    _, browser_only = environments["browser_only"]
    assert rat.python_for(tmp_path, "server", [panel, browser_only])[0] == panel
    assert rat.python_for(tmp_path, "server", [browser_only, panel])[0] == browser_only


def test_an_environment_without_pytest_runs_no_suite(environments, asked_afresh, tmp_path):
    """However new its Playwright. Every suite is a pytest run, so in an
    environment without pytest it fails before its first test."""
    _, no_pytest = environments["no_pytest"]
    _, panel = environments["panel"]
    for kind in ("server", "app"):
        assert rat.python_for(tmp_path, kind, [no_pytest, panel]) == (panel, []), kind


def test_a_newer_playwright_is_a_higher_number_not_a_later_string():
    assert sorted(["1.100.0", "1.9.0", "1.63.1", "1.62.0", "1.63.0"], key=rat.version_key) == \
        ["1.9.0", "1.62.0", "1.63.0", "1.63.1", "1.100.0"]
    assert rat.version_key(None) == rat.version_key("unknown") == ()


# Where a test that starts Chromium itself finds it. The core's browser
# module looks where Playwright keeps its browsers, by Playwright's own
# rules, and the runner looks for the newest Playwright's own build in the
# same place for each suite. Until 2026-10-05 both read neither
# XDG_CACHE_HOME, INIT_CWD nor npm's names for a setting, and took
# PLAYWRIGHT_BROWSERS_PATH=0 and =1 as no setting at all, so the runner
# could refuse a run whose Chromium was where Playwright keeps it.

SETTINGS = ("PLAYWRIGHT_BROWSERS_PATH", "npm_config_playwright_browsers_path",
            "npm_package_config_playwright_browsers_path", "INIT_CWD", "npm_config_init_cwd",
            "npm_package_config_init_cwd", "XDG_CACHE_HOME", "LOCALAPPDATA")


@pytest.fixture(scope="module")
def a_playwright_package(tmp_path_factory):
    """A Playwright package of the module's own, a folder with an empty
    __init__.py, and where the runner hears it is from an interpreter that
    would import it. Asked once, since starting an interpreter can take
    seconds."""
    site = tmp_path_factory.mktemp("site")
    (site / "playwright").mkdir()
    (site / "playwright" / "__init__.py").write_text("", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PYTHONPATH", str(site))
        mp.setattr(rat, "_ASKED", {})
        package = rat.asked(Path(sys.executable))["package"]
    return site, package


# The rows test_browser.py holds the core to, and the one for 0, which
# needs the package the runner hears of.
@pytest.mark.parametrize("platform, settings, expected", [
    ("linux", {}, "{home}/.cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": "{tmp}/cache"}, "{tmp}/cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": ""}, "{home}/.cache/ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": "cache"}, "{tmp}/cache/ms-playwright"),
    ("darwin", {"XDG_CACHE_HOME": "{tmp}/cache"}, "{home}/Library/Caches/ms-playwright"),
    ("win32", {"LOCALAPPDATA": "{tmp}/local", "XDG_CACHE_HOME": "{tmp}/cache"}, "{tmp}/local/ms-playwright"),
    ("win32", {}, "{home}/AppData/Local/ms-playwright"),
    ("win32", {"LOCALAPPDATA": ""}, "{home}/AppData/Local/ms-playwright"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "{tmp}/own"}, "{tmp}/own"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "0"}, "{package}/driver/package/.local-browsers"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "1"}, "{tmp}/1"),
    ("win32", {"PLAYWRIGHT_BROWSERS_PATH": "1", "LOCALAPPDATA": "{tmp}/local"}, "{tmp}/1"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "rel/browsers"}, "{tmp}/rel/browsers"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "rel", "INIT_CWD": "{tmp}/project"}, "{tmp}/project/rel"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "1", "npm_config_init_cwd": "{tmp}/project"}, "{tmp}/project/1"),
    ("linux", {"npm_config_playwright_browsers_path": "{tmp}/npm"}, "{tmp}/npm"),
    ("linux", {"npm_package_config_playwright_browsers_path": "{tmp}/package"}, "{tmp}/package"),
    ("linux", {"PLAYWRIGHT_BROWSERS_PATH": "", "npm_config_playwright_browsers_path": "{tmp}/npm"},
     "{home}/.cache/ms-playwright"),
], ids=["linux", "linux under XDG_CACHE_HOME", "linux with XDG_CACHE_HOME empty",
        "linux with XDG_CACHE_HOME relative", "macos never reads XDG_CACHE_HOME",
        "windows never reads XDG_CACHE_HOME", "windows without LOCALAPPDATA",
        "windows with LOCALAPPDATA empty", "a folder", "0 inside the package", "1 is a folder",
        "1 is a folder on windows", "a relative folder", "a relative folder from INIT_CWD",
        "a relative folder from npm's INIT_CWD", "npm's name for it", "npm's package name for it",
        "set to nothing is set"])
def test_the_runner_looks_for_chromium_where_the_core_does(platform, settings, expected, a_playwright_package,
                                                          tmp_path, monkeypatch):
    """Two places that must agree, and with Playwright. A test that starts
    Chromium itself finds it through the core's browser module, and the
    runner looks for the newest Playwright's own build where the Playwright
    a suite runs on keeps it, asking that interpreter where its Playwright
    is. A Playwright package of the module's own stands in for this
    Python's and for the interpreter the runner asks."""
    from paperpull_core import browser
    site, package = a_playwright_package
    assert Path(package) == site / "playwright"
    monkeypatch.delitem(sys.modules, "playwright", raising=False)
    monkeypatch.syspath_prepend(str(site))
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", platform)
    fill = {"tmp": tmp_path, "home": home, "package": package}
    for name, value in settings.items():
        monkeypatch.setenv(name, value.format(**fill))
    assert rat.browsers_folder(package, os.getcwd()) == browser._playwright_root() == Path(expected.format(**fill))


# What the plugin writes down when a canary of one test passes, for a core
# suite that is a stand-in and runs nothing.
CANARY_PASSED = [{"outcome_of": "core/tests/test_failure_canary.py::test_it", "when": "collected"}] + [
    {"outcome_of": "core/tests/test_failure_canary.py::test_it", "when": when, "outcome": "passed"}
    for when in ("setup", "call", "teardown")]


@pytest.fixture
def run_with(environments, asked_afresh, tmp_path, monkeypatch):
    """main() over suites of our making, each run in whichever of the
    environments named the runner picks, and each passing at once, the
    core with its canary, with the Chromium builds named installed. Hands
    back which interpreter ran each suite."""
    def make(suites: dict, names: list, builds=("1234", "1243"), unfinished=()) -> dict:
        ran = {}

        def run_suite(d, py, timeout=rat.SUITE_LIMIT_S, **_):
            ran[d.name] = py
            return "1 passed in 0.01s", 0, list(CANARY_PASSED) if d.name == rat.CANARY_SUITE else []
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                           str(_installed(tmp_path / "browsers", *builds, unfinished=unfinished)))
        monkeypatch.setattr(rat, "OUTPUT", tmp_path / "test-output")
        monkeypatch.setattr(rat, "TIMES", tmp_path / "times.json")
        monkeypatch.setattr(rat, "suites", lambda quick: [(n, tmp_path / n, k) for n, k in suites.items()])
        monkeypatch.setattr(rat, "candidates", lambda: [environments[n][1] if isinstance(n, str) else n
                                                        for n in names])
        monkeypatch.setattr(rat, "run_suite", run_suite)
        return ran
    return make


def test_a_run_where_a_suite_ran_on_an_older_playwright_fails_and_names_it(run_with, environments, capsys):
    # Only the environment a version behind can read a workbook, so the core
    # suite runs there while the app suite runs on the newest.
    ran = run_with({"core": "core", "aafmaa": "app"}, ["panel", "spreadsheets"])
    assert rat.main(["--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert ran == {"core": environments["spreadsheets"][1], "aafmaa": environments["panel"][1]}
    assert "\nPlaywright 1.63.0 for 1 of the suites that use it, an older one for 1, named below\n" in out, out
    assert re.search(r"\n   core +1\.62\.0, in <elsewhere>/python", out), out
    assert "\nNOT EVERY SUITE RAN ON PLAYWRIGHT 1.63.0.\n" in out, out
    assert "all suites passed" not in out


def test_a_run_on_the_newest_playwright_and_its_own_chromium_says_so_and_passes(run_with, environments, capsys):
    ran = run_with({"server": "server", "aafmaa": "app"}, ["app", "panel"])
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert ran == {"server": environments["panel"][1], "aafmaa": environments["panel"][1]}
    assert ("\nPlaywright 1.63.0 for every suite that uses it\n"
            "and its own Chromium, build 1243, for the tests that start one themselves\n") in out, out
    assert out.rstrip().endswith("all suites passed, and the privacy canary was not among them")


def test_a_suite_that_does_not_use_playwright_is_not_held_to_it(run_with, environments, capsys):
    # Only an environment a version behind has what the panel's suite needs,
    # and that suite starts a browser only to drive its own page.
    ran = run_with({"gui": "gui", "aafmaa": "app"}, ["panel_ui", "panel"])
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert ran == {"gui": environments["panel_ui"][1], "aafmaa": environments["panel"][1]}
    assert "\nPlaywright 1.63.0 for every suite that uses it\n" in out, out
    assert out.rstrip().endswith("all suites passed, and the privacy canary was not among them")


def test_a_suite_whose_environment_has_no_playwright_is_named_apart(run_with, environments, capsys):
    # Nothing here has all the core suite needs, and the environment missing
    # least has no Playwright at all.
    ran = run_with({"core": "core", "aafmaa": "app"}, ["panel", "no_browser"])
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert ran == {"core": environments["no_browser"][1], "aafmaa": environments["panel"][1]}
    assert "\nPlaywright 1.63.0 for every suite that uses it, apart from 1 whose environment has none\n" in out, out
    assert re.search(r"\n   core +playwright \(", out), out


@pytest.mark.parametrize("builds, unfinished, take, here", [
    (("1234",), (), "take build 1234", "1234 here"),
    (("1234",), ("1243",), "take build 1234", "1234 here"),
    ((), (), "have none to take", "and there is none here"),
], ids=["an older one", "its own unfinished", "none"])
def test_a_run_without_the_newest_playwrights_own_chromium_is_refused(run_with, capsys, builds, unfinished,
                                                                    take, here):
    run_with({"server": "server", "aafmaa": "app"}, ["app", "panel"], builds=builds, unfinished=unfinished)
    assert rat.main(["--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert ("\nbut its own Chromium, build 1243, is not installed, so the tests that start one "
            "themselves %s\n" % take) in out, out
    assert "\nPLAYWRIGHT 1.63.0'S OWN CHROMIUM, BUILD 1243, IS NOT INSTALLED HERE.\n" in out, out
    assert "\n%s, while CI and the packaged app run 1243. Install it with\n" % here in out, out
    assert "each suite looks in a folder of" not in out, "one folder serves every suite here"
    assert "all suites passed" not in out


def _usual_folder(tmp_path, monkeypatch) -> Path:
    """Nothing set that Playwright reads, and the folder it then keeps its
    browsers in made one of the test's own."""
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    if sys.platform == "win32":
        return tmp_path / "local" / "ms-playwright"
    if sys.platform == "darwin":
        return tmp_path / "home" / "Library" / "Caches" / "ms-playwright"
    return tmp_path / "home" / ".cache" / "ms-playwright"


@pytest.fixture
def kept_inside():
    """Puts finished Chromium builds where an environment's Playwright keeps
    them when PLAYWRIGHT_BROWSERS_PATH is 0, inside its own package, and
    takes them out after the test, since the module shares the environments."""
    made = []

    def keep(py: Path, *builds) -> Path:
        made.append(_site(py) / "playwright" / "driver" / "package" / ".local-browsers")
        return _installed(made[-1], *builds)
    yield keep
    for folder in made:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.parametrize("kept_in, passes", [("its package", True), ("the usual folder", False)])
def test_with_browsers_path_0_the_runner_looks_inside_playwright(kept_in, passes, run_with, environments,
                                                                  kept_inside, tmp_path, monkeypatch, capsys):
    """PLAYWRIGHT_BROWSERS_PATH=0 keeps each Playwright's browsers inside its
    own package. The runner looked in the usual folder instead, so it refused
    a run whose Chromium was where Playwright keeps it, and passed one where
    a test that starts Chromium itself would find none."""
    run_with({"aafmaa": "app"}, ["panel"], builds=())
    usual = _usual_folder(tmp_path, monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    if kept_in == "its package":
        kept_inside(environments["panel"][1], "1243")
    else:
        _installed(usual, "1243")
    assert rat.main(["--jobs", "1"]) == (0 if passes else 1)
    out = capsys.readouterr().out
    if passes:
        assert "\nand its own Chromium, build 1243, for the tests that start one themselves\n" in out, out
    else:
        assert ("\nbut its own Chromium, build 1243, is not installed, so the tests that start one "
                "themselves have none to take\n") in out, out
        assert re.search(r"\n   aafmaa +<elsewhere>/python(\.exe)?, from <elsewhere>/aafmaa\n", out), out


def test_with_browsers_path_0_a_suite_without_playwright_is_not_held_to_it(run_with, environments, kept_inside,
                                                                             tmp_path, monkeypatch, capsys):
    """Its environment has no Playwright, so there is no package to keep a
    build in, and its tests cannot start Chromium through one. It is named
    among the suites missing something, and the run is not refused over a
    Chromium it could not have used."""
    ran = run_with({"core": "core", "aafmaa": "app"}, ["panel", "no_browser"], builds=())
    _usual_folder(tmp_path, monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
    kept_inside(environments["panel"][1], "1243")
    assert rat.main(["--jobs", "1"]) == 0
    assert ran == {"core": environments["no_browser"][1], "aafmaa": environments["panel"][1]}
    assert "\nand its own Chromium, build 1243, for the tests that start one themselves\n" in \
        capsys.readouterr().out


@pytest.mark.parametrize("setting", ["0", "browsers"], ids=["0", "a relative folder"])
def test_every_suite_needs_the_build_where_it_looks(setting, run_with, environments, kept_inside, tmp_path,
                                                   monkeypatch, capsys):
    """Two suites can look in two folders. With PLAYWRIGHT_BROWSERS_PATH=0
    each Playwright keeps its own browsers, and a relative folder is found
    from where each suite runs. Only one environment here has what the core
    suite needs, so the two suites run on two environments holding the same
    Playwright, and the build has to be where each suite looks."""
    on = {"aafmaa": environments["panel"][1], "core": environments["everything"][1]}
    ran = run_with({"aafmaa": "app", "core": "core"}, ["panel", "everything"], builds=())
    _usual_folder(tmp_path, monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", setting)

    def install(suite):
        if setting == "0":
            kept_inside(on[suite], "1243")
        else:
            _installed(tmp_path / suite / setting, "1243")
    install("aafmaa")
    assert rat.main(["--jobs", "1"]) == 1
    assert ran == on
    out = capsys.readouterr().out
    assert "\nbut its own Chromium, build 1243, is not installed, " in out, out
    # No one install serves both, so the suite without it is named, with the
    # environment and the folder to run the install with.
    assert "\nWith PLAYWRIGHT_BROWSERS_PATH set as it is, each suite looks in a folder of\n" in out, out
    assert re.search(r"\n   core +<elsewhere>/python(\.exe)?, from <elsewhere>/core\n", out), out
    assert "\n   aafmaa " not in out, out
    install("core")
    assert rat.main(["--jobs", "1"]) == 0
    assert "\nand its own Chromium, build 1243, for the tests " in capsys.readouterr().out


def test_an_environment_that_could_not_be_asked_is_named(run_with, tmp_path, capsys):
    run_with({"aafmaa": "app"}, [tmp_path / "gone" / "python.exe", "panel"])
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert ("\nenvironments that could not say what they hold\n"
            "   <elsewhere>/python.exe, could not be started\n") in out, out


# -- a run of the suites named (2026-10-07) --------------------------------------

def test_a_run_of_named_suites_runs_only_those_and_says_it_is_not_a_full_run(one_suite, capsys):
    """worktree.py land runs the suites a change touches, and the whole
    suite runs before each release and on CI. A part run must never read as
    a full one."""
    one_suite({"tests/test_failure_canary.py": CANARY},
              others={"aafmaa": {"tests/test_it.py": ANOTHER}, "kroger": {"tests/test_it.py": ANOTHER}})
    assert rat.main(["--suites", "kroger", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 of the 3 suites, kroger, which is not a full run" in out, out
    assert "\nok   kroger " in out and "\nok   aafmaa " not in out and "\nok   core " not in out
    assert out.rstrip().endswith("\nthe 1 suites named passed, and the privacy canary was not "
                                 "among them"), out

    assert rat.main(["--suites", "core,aafmaa", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "\nok   core " in out and "\nok   aafmaa " in out and "\nok   kroger " not in out
    assert out.rstrip().endswith("privacy canary included, which is not a full run"), out
    assert "all suites passed" not in out


def test_a_suite_named_wrong_is_refused_rather_than_skipped(one_suite, capsys):
    one_suite({"tests/test_failure_canary.py": CANARY}, others={"kroger": {"tests/test_it.py": ANOTHER}})
    assert rat.main(["--suites", "kroger,krogr", "--jobs", "1"]) == 2
    assert "no suite is named krogr" in capsys.readouterr().out


def test_named_suites_take_no_shard_and_keep_no_times(one_suite, capsys, tmp_path):
    one_suite({"tests/test_failure_canary.py": CANARY}, others={"kroger": {"tests/test_it.py": ANOTHER}},
              times={"core": 100, "kroger": 90})
    with pytest.raises(SystemExit):
        rat.main(["--suites", "kroger", "--shard", "1/2"])
    capsys.readouterr()
    before = (tmp_path / "times.json").read_text(encoding="utf-8")
    assert rat.main(["--suites", "kroger", "--jobs", "1", "--write-times"]) == 0
    assert (tmp_path / "times.json").read_text(encoding="utf-8") == before, \
        "a part run's times are not the times of a full run"


# -- the core's three suites -----------------------------------------------------
#
# Whole, core ran alone in CI's part 1 and took 36 to 45 minutes of the job's
# 45, and two runs of 12 were stopped at the limit with nothing failed. So
# its tests ran as two suites from the one folder, core and core-browsers,
# which takes the files whose own code drives a real browser. By 2026-10-18
# core took 27 to 38 minutes of its part again and part 1 of the 0.56.0 tag
# was canceled at the limit, so the censuses left it for core-censuses.

def _core_part():
    spec = importlib.util.spec_from_file_location("core_part_under_test", rat.PLUGINS / "core_part.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_core_runs_as_three_suites_from_its_one_folder():
    """The plugin and the runner name the three the same, the canary's
    suite is the first, and a quick run holds all three."""
    cp = _core_part()
    assert rat.CORE_PARTS == cp.PARTS == (cp.CORE, cp.CENSUSES, cp.BROWSERS) == (
        "core", "core-censuses", "core-browsers")
    assert rat.CANARY_SUITE == cp.CORE == rat.CORE_PARTS[0]
    for quick in (False, True):
        core = [(name, d, kind) for name, d, kind in rat.suites(quick) if d == REPO / "core"]
        assert core == [(name, REPO / "core", "core") for name in rat.CORE_PARTS], quick


def test_every_core_test_file_runs_in_exactly_one_of_the_three(monkeypatch):
    """By the plugin's own hook, as pytest asks it, over every file the core
    has. The canary stays in core though it starts a browser, a census that
    drives a browser runs with the browsers, each census name still names a
    file of core-censuses, and pytest run by hand in core/, with no part
    named, still runs every file."""
    cp = _core_part()
    tests = REPO / "core" / "tests"
    files = sorted({f for pattern in cp.PYTHON_FILES for f in tests.glob(pattern)})
    assert len(files) > 100
    kept = {}
    for part in rat.CORE_PARTS:
        monkeypatch.setenv(cp.PART, part)
        kept[part] = {f.name for f in files if cp.pytest_ignore_collect(f, None) is None}
    assert set().union(*kept.values()) == {f.name for f in files}
    for one, other in itertools.combinations(rat.CORE_PARTS, 2):
        assert not kept[one] & kept[other], (one, other)
    assert sum(len(names) for names in kept.values()) == len(files)
    assert cp.drives_a_browser(tests / rat.CANARY_FILE.split("/")[-1])
    assert "test_failure_canary.py" in kept["core"]
    assert {"test_pressing_in_a_browser.py", "test_delivery_live.py"} <= kept["core-browsers"]
    assert {"test_every_app_guard.py", "test_no_app_forces_a_press.py"} <= kept["core-censuses"]
    assert "test_every_fallback_press_in_a_browser.py" in kept["core-browsers"]
    assert all(cp.is_census(tests / name) for name in kept["core-censuses"])
    assert not any(cp.is_census(tests / name) for name in kept["core"] - cp.KEPT_IN_CORE)
    for pattern in cp.CENSUS_NAMES:
        assert any(fnmatch.fnmatch(name, pattern) for name in kept["core-censuses"]), pattern
    assert 20 <= len(kept["core-browsers"]) < len(kept["core"])
    assert len(kept["core-censuses"]) >= 20
    monkeypatch.delenv(cp.PART)
    assert all(cp.pytest_ignore_collect(f, None) is None for f in files)
    assert cp.pytest_ignore_collect(REPO / "core" / "tests" / "conftest.py", None) is None


def test_a_census_is_known_by_its_name_and_the_canary_by_its_own(tmp_path):
    """Named for what every app does or what no app does, a file goes to
    core-censuses, unless its own code drives a browser, and a name that
    only mentions every or no does not count. The canary stays in core
    whatever it is named."""
    cp = _core_part()
    plain = "def test_it():\n    assert True\n"
    drives = "def test_it():\n    with sync_playwright() as p:\n        pass\n"
    for name, text, part in [
            ("test_every_app_does_it.py", plain, "core-censuses"),
            ("test_every_receipt_app_does_it.py", plain, "core-censuses"),
            ("test_no_app_does_it.py", plain, "core-censuses"),
            ("test_no_dead_things.py", plain, "core-censuses"),
            ("test_every_press_in_a_browser.py", drives, "core-browsers"),
            ("test_not_every_app.py", plain, "core"),
            ("test_a_file_for_every_app.py", plain, "core"),
            ("test_nothing_left.py", plain, "core"),
            ("every_app_test.py", plain, "core")]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        assert cp.part_of(tmp_path / name) == part, name
    cp.KEPT_IN_CORE = frozenset({"test_every_canary.py"})
    for text in (plain, drives):
        (tmp_path / "test_every_canary.py").write_text(text, encoding="utf-8")
        assert cp.part_of(tmp_path / "test_every_canary.py") == "core"


def test_a_browser_named_only_in_words_does_not_move_a_file(tmp_path):
    cp = _core_part()
    for name, text, drives in [
            ("test_docstring.py", '"""Calls sync_playwright and launch, in words."""\n', False),
            ("test_comment.py", "# browser = p.chromium.launch()\nX = 'launch'\n", False),
            ("test_a_name_alone.py", "def test_it():\n    assert launch is not None\n", False),
            ("test_broken.py", "def test_it(:\n    sync_playwright()\n", False),
            ("test_called.py", "def test_it():\n    with sync_playwright() as p:\n        pass\n", True),
            ("test_a_method.py", "def test_it(p):\n    p.chromium.launch()\n", True),
            ("test_a_helper.py", "def test_it():\n    drawn_browser()\n", True)]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        assert cp.drives_a_browser(tmp_path / name) is drives, name
        assert cp.part_of(tmp_path / name) == ("core-browsers" if drives else "core"), name
    canary = tmp_path / "test_failure_canary.py"
    canary.write_text("def test_it():\n    launch()\n", encoding="utf-8")
    assert cp.drives_a_browser(canary) and cp.part_of(canary) == "core"


def test_a_file_pytest_collects_by_any_pattern_runs_in_one_suite(tmp_path, monkeypatch):
    """pytest also collects *_test.py, and pytest.ini may name other
    patterns. The hook reads the run's own python_files, so such a file is
    left out of all but one suite, never out of none and run in every one
    (review)."""
    cp = _core_part()

    class Config:
        def __init__(self, patterns):
            self.patterns = patterns

        def getini(self, name):
            assert name == "python_files"
            return self.patterns

    for name, patterns in [("drives_test.py", ["test_*.py", "*_test.py"]), ("check_drives.py", ["check_*.py"]),
                           ("test_drives.py", ["test_*.py", "*_test.py"])]:
        f = tmp_path / name
        f.write_text("def test_it():\n    sync_playwright()\n", encoding="utf-8")
        kept = []
        for part in rat.CORE_PARTS:
            monkeypatch.setenv(cp.PART, part)
            if cp.pytest_ignore_collect(f, Config(patterns)) is None:
                kept.append(part)
        assert kept == ["core-browsers"], name
    monkeypatch.setenv(cp.PART, "core")
    assert cp.pytest_ignore_collect(tmp_path / "drives_test.py", None), "pytest's default patterns without a config"


def test_a_file_one_part_cannot_read_is_kept_by_that_part(tmp_path, monkeypatch):
    """Each part's process reads a file for itself. A file the browsers'
    process reads as a browser file, and the censuses' process cannot read
    at that moment, would otherwise be a census there and so run nowhere
    (review). Kept by the part that could not read it, it runs twice at
    worst. A file that does not parse is placed the same by every part."""
    cp = _core_part()
    f = tmp_path / "test_every_press_in_a_browser.py"
    f.write_text("def test_it():\n    sync_playwright()\n", encoding="utf-8")
    monkeypatch.setenv(cp.PART, "core-browsers")
    assert cp.pytest_ignore_collect(f, None) is None
    real = Path.read_text

    def locked(self, *args, **kwargs):
        if self.name == f.name:
            raise PermissionError(13, "held by another process", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked)
    for part in rat.CORE_PARTS:
        monkeypatch.setenv(cp.PART, part)
        assert cp.pytest_ignore_collect(f, None) is None, part
    broken = tmp_path / "test_every_broken_census.py"
    broken.write_text("def test_it(:\n    sync_playwright()\n", encoding="utf-8")
    kept = []
    for part in rat.CORE_PARTS:
        monkeypatch.setenv(cp.PART, part)
        if cp.pytest_ignore_collect(broken, None) is None:
            kept.append(part)
    assert kept == ["core-censuses"]


SPLIT_FILES = {
    "tests/test_plain.py": "import os, pathlib\n\ndef test_plain():\n"
                           "    pathlib.Path(os.environ['RAN_IN'], 'plain').touch()\n",
    "tests/test_drives.py": "import os, pathlib\n\ndef test_drives():\n"
                            "    pathlib.Path(os.environ['RAN_IN'], 'drives').touch()\n"
                            "    if False:\n        sync_playwright()\n",
    "tests/test_every_app_is_counted.py": "import os, pathlib\n\ndef test_census():\n"
                                          "    pathlib.Path(os.environ['RAN_IN'], 'census').touch()\n",
    "tests/test_failure_canary.py": "import os, pathlib\n\ndef test_it():\n"
                                    "    pathlib.Path(os.environ['RAN_IN'], 'canary').touch()\n"
                                    "    if False:\n        launch()\n",
}


def test_each_of_the_cores_suites_runs_only_its_own_files(tmp_path, monkeypatch):
    """Through run_suite, so a real pytest with the plugin, each test leaving
    a mark of its own. No part named runs everything, as for any suite."""
    (tmp_path / "pytest.ini").write_text((REPO / "pytest.ini").read_text(encoding="utf-8"), encoding="utf-8")
    suite = tmp_path / "core"
    for rel, text in SPLIT_FILES.items():
        _write(suite, rel, text)
    ran = {}
    for part in ("", *rat.CORE_PARTS):
        marks = tmp_path / ("marks-" + (part or "whole"))
        marks.mkdir()
        monkeypatch.setenv("RAN_IN", str(marks))
        output, code, _records = rat.run_suite(suite, Path(sys.executable), timeout=300,
                                               **({"part": part} if part else {}))
        assert code == 0, output
        ran[part] = sorted(p.name for p in marks.iterdir())
    assert ran == {"": ["canary", "census", "drives", "plain"], "core": ["canary", "plain"],
                   "core-censuses": ["census"], "core-browsers": ["drives"]}


def _the_core_suites(one_suite, monkeypatch, files):
    suite = one_suite(files)
    monkeypatch.setattr(rat, "suites", lambda quick: [(name, suite, "core") for name in rat.CORE_PARTS])
    return suite


def test_a_run_of_the_three_core_suites_counts_each_test_once(one_suite, monkeypatch, tmp_path, capsys):
    _the_core_suites(one_suite, monkeypatch, SPLIT_FILES)
    monkeypatch.setenv("RAN_IN", str(tmp_path))
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    lines = {ln.split()[1]: ln for ln in out.splitlines() if ln.split()[:1] == ["ok"]}
    assert "2 passed" in lines["core"] and "1 passed" in lines["core-censuses"], out
    assert "1 passed" in lines["core-browsers"], out
    assert "\n4 passed, 0 failed, 0 skipped" in out, out
    assert out.rstrip().endswith("all suites passed, privacy canary included"), out


@pytest.mark.parametrize("suite, gone", [("core-censuses", "tests/test_every_app_is_counted.py"),
                                         ("core-browsers", "tests/test_drives.py")])
def test_a_core_suite_beside_the_canarys_that_collects_nothing_fails(one_suite, monkeypatch, tmp_path,
                                                                   capsys, suite, gone):
    """Then the rule placing the core's files found no census or no browser
    file, so the split has gone wrong, and a run is not to pass on it."""
    files = {k: v for k, v in SPLIT_FILES.items() if k != gone}
    _the_core_suites(one_suite, monkeypatch, files)
    monkeypatch.setenv("RAN_IN", str(tmp_path))
    assert rat.main(["--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert ("FAIL %-16s collected no test, so the core's split into three suites "
            "has gone wrong" % suite) in out, out
    assert "FAILING SUITE  %s" % suite in out, out
    assert any(ln.split()[:2] == ["ok", "core"] for ln in out.splitlines()), out
    assert "all suites passed" not in out, out


def test_a_run_of_the_three_without_the_canary_is_refused(one_suite, monkeypatch, tmp_path, capsys):
    """The other two pass beside a core that ran no canary, and the run is
    still refused. A run that holds neither core nor the canary is not, and
    says the canary was not among its suites."""
    files = {k: v for k, v in SPLIT_FILES.items() if k != "tests/test_failure_canary.py"}
    _the_core_suites(one_suite, monkeypatch, files)
    monkeypatch.setenv("RAN_IN", str(tmp_path))
    assert rat.main(["--jobs", "1"]) == 1
    out = capsys.readouterr().out
    assert "\nTHE PRIVACY CANARY DID NOT RUN.\ncore/tests/test_failure_canary.py is missing" in out, out
    for name in ("core-censuses", "core-browsers"):
        assert any(ln.split()[:2] == ["ok", name] for ln in out.splitlines()), out
    assert "all suites passed" not in out, out
    assert rat.main(["--suites", "core-censuses,core-browsers", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith("\nthe 2 suites named passed, and the privacy canary was not "
                                 "among them"), out


def test_naming_core_alone_runs_only_its_part_and_says_so(one_suite, monkeypatch, tmp_path, capsys):
    """core names the suite that holds the canary, never the core's whole
    folder, so a run of fewer than all three says which it holds."""
    _the_core_suites(one_suite, monkeypatch, SPLIT_FILES)
    monkeypatch.setenv("RAN_IN", str(tmp_path))
    assert rat.main(["--suites", "core", "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir() if p.name in ("canary", "census", "drives", "plain")) == [
        "canary", "plain"]
    assert ("\nthe core's tests run as 3 suites, core, core-censuses and core-browsers, and this run "
            "holds only core\n") in out, out
    assert out.rstrip().endswith("privacy canary included, which is not a full run"), out
    assert rat.main(["--suites", "core,core-browsers", "--jobs", "1"]) == 0
    assert "this run holds only core and core-browsers\n" in capsys.readouterr().out
    assert rat.main(["--suites", ",".join(rat.CORE_PARTS), "--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert "this run holds only" not in out, out
    assert "\n4 passed, 0 failed, 0 skipped" in out, out
