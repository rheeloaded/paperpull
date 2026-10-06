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

They also check that every suite runs on the newest Playwright the
machine holds, as CI and the packaged app do, and that a run where one
could not is refused.
"""
import functools
import io
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
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


@pytest.fixture
def run_with(environments, asked_afresh, tmp_path, monkeypatch):
    """main() over suites of our making, each run in whichever of the
    environments named the runner picks, and each passing at once, with
    the Chromium builds named installed. Hands back which interpreter ran
    each suite."""
    def make(suites: dict, names: list, builds=("1234", "1243"), unfinished=()) -> dict:
        ran = {}

        def run_suite(d, py, timeout=rat.SUITE_LIMIT_S):
            ran[d.name] = py
            return "1 passed in 0.01s", 0, []
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
    assert out.rstrip().endswith("all suites passed, privacy canary included")


def test_a_suite_that_does_not_use_playwright_is_not_held_to_it(run_with, environments, capsys):
    # Only an environment a version behind has what the panel's suite needs,
    # and that suite starts a browser only to drive its own page.
    ran = run_with({"gui": "gui", "aafmaa": "app"}, ["panel_ui", "panel"])
    assert rat.main(["--jobs", "1"]) == 0
    out = capsys.readouterr().out
    assert ran == {"gui": environments["panel_ui"][1], "aafmaa": environments["panel"][1]}
    assert "\nPlaywright 1.63.0 for every suite that uses it\n" in out, out
    assert out.rstrip().endswith("all suites passed, privacy canary included")


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
