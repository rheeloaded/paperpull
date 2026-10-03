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
without the privacy canary.
"""
import io
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

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


def test_the_plugin_changes_no_outcome(walked, tmp_path):
    """It must never change a run. The same suite without it, and with a
    record file it cannot write, ends exactly the same way."""
    suite = walked["suite"]
    plain = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-rsfE",
                            "-p", "no:cacheprovider"],
                           cwd=suite, capture_output=True, text=True, timeout=300)
    env = rat.with_this_core(rat.PLUGINS)
    env[rat.WHERE_FILE] = str(tmp_path)          # a folder, so the write fails
    blocked = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-rsfE",
                              "-p", "no:cacheprovider", "-p", rat.WHERE],
                             cwd=suite, capture_output=True, text=True, timeout=300, env=env)
    out = plain.stdout + plain.stderr
    assert _summary(out) == "4 failed, 2 passed, 1 error"
    for other in (walked["output"], blocked.stdout + blocked.stderr):
        assert _summary(other) == _summary(out)
        assert _failed_lines(other) == _failed_lines(out)
    assert walked["code"] == plain.returncode == blocked.returncode == 1


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
    """main() over a single suite of our making, with its output kept in
    tmp_path rather than the checkout's own folder."""
    def make(files: dict):
        (tmp_path / "pytest.ini").write_text((REPO / "pytest.ini").read_text(encoding="utf-8"),
                                             encoding="utf-8")
        suite = tmp_path / "core"
        for rel, text in files.items():
            _write(suite, rel, text)
        monkeypatch.setattr(rat, "suites", lambda quick: [("core", suite, "core")])
        monkeypatch.setattr(rat, "candidates", lambda: [])
        monkeypatch.setattr(rat, "python_for", lambda d, kind, spares: (Path(sys.executable), []))
        monkeypatch.setattr(rat, "OUTPUT", tmp_path / "test-output")
        monkeypatch.setattr(sys, "argv", ["run_all_tests.py"])
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
