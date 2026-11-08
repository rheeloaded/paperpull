"""No panel test reaches the person's own settings, on any system (#153).

On macOS the panel's settings file is found from the home folder alone, and
the fixtures here moved only APPDATA, LOCALAPPDATA and XDG_CONFIG_HOME. So on
a Mac in daily use, running these tests wrote over the real settings.json,
and the panel showed no accounts until apps_root was put back. conftest.py
now moves the home folder for every test, and refuses any write outside the
temp folders while a test runs. These hold both in place.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MAC_FILE = ("Library", "Application Support", "PaperPull", "settings.json")


@pytest.fixture()
def app_module():
    """The panel, asked for only by the tests that need it, so the guard's
    own tests run where the panel's libraries are not installed."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    return pytest.importorskip("app")


def test_the_home_folder_is_this_tests_own(tmp_path):
    assert tmp_path in Path.home().parents
    assert tmp_path in Path(os.path.expanduser("~")).parents
    assert "APPS_ROOT" not in os.environ


def test_a_mac_fixture_that_moved_three_variables_saves_into_this_tests_home(app_module, tmp_path,
                                                                               monkeypatch):
    """The fixture of #153 as it stood, run as on a Mac. Its three variables
    leave the file where the home folder puts it. Where the home folder is
    checked before anything is written, so a tree that does not move it
    fails here naming the person's own file rather than writing to it."""
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    where = app_module._settings_path()
    assert where == Path.home().joinpath(*MAC_FILE)
    assert tmp_path / "settings" not in where.parents
    assert tmp_path in where.parents, "a test saving a setting would write %s" % where
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    assert json.loads(where.read_text(encoding="utf-8")) == {
        "terms_accepted": app_module.TERMS_VERSION}


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_on_every_system_a_test_with_no_fixture_finds_its_own_settings(platform, app_module, tmp_path,
                                                                       monkeypatch):
    """A test that moves nothing itself, as most here do not."""
    monkeypatch.setattr(app_module.sys, "platform", platform)
    assert tmp_path in app_module._settings_path().parents
    # Where the packaged panel looks for the installs, and builds the sample.
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    assert tmp_path in app_module.apps_root().parents
    assert tmp_path in app_module._sample_dest().parents


def test_playwright_is_told_where_its_browsers_are(tmp_path):
    """Found before anything moved, so a test that starts Chromium does not
    skip itself as though none were installed."""
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == "0":
        pytest.skip("browsers inside a Playwright that is not installed here")
    named = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
    assert named.is_absolute()
    assert tmp_path not in named.parents


# -- the guard -------------------------------------------------------------------

# Run in a pytest of their own with this folder's conftest.py, so what the
# guard does to a test is seen from outside it. OUTSIDE is outside that
# run's temp folders and inside this test's, and so is the home folder it
# starts with, which stands for the person's own.
WRITERS = '''
import os
import shutil
import tempfile
from pathlib import Path

import pytest

OUTSIDE = Path(os.environ["OUTSIDE"])

# Read before any test starts, as a test file's own lines are.
(Path.home() / "read-with-the-file.json").write_text("{}", encoding="utf-8")


@pytest.fixture(scope="module")
def saved_for_the_module():
    (Path.home() / "module.json").write_text("{}", encoding="utf-8")


def test_with_a_module_fixture_that_saves_in_its_home(saved_for_the_module):
    pass


@pytest.fixture()
def saved_by_a_fixture():
    (OUTSIDE / "fixture.json").write_text("{}", encoding="utf-8")


@pytest.fixture()
def saved_when_done():
    yield
    (OUTSIDE / "done.json").write_text("{}", encoding="utf-8")


def test_with_a_fixture_that_saves_outside(saved_by_a_fixture):
    pass


def test_with_a_fixture_that_saves_outside_when_done(saved_when_done):
    pass


def test_saves_outside():
    (OUTSIDE / "settings.json").write_text("{}", encoding="utf-8")


def test_saves_outside_and_hides_the_error():
    try:
        (OUTSIDE / "caught.json").write_text("{}", encoding="utf-8")
    except OSError:
        pass


def test_moves_a_file_outside(tmp_path):
    made = tmp_path / "made.json"
    made.write_text("{}", encoding="utf-8")
    os.replace(made, OUTSIDE / "moved.json")


def test_makes_a_folder_outside():
    (OUTSIDE / "folder").mkdir()


def test_saves_in_its_own_folder(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "settings.json").write_text("{}", encoding="utf-8")


def test_saves_in_its_home(tmp_path):
    (Path.home() / "Library").mkdir()
    (Path.home() / "Library" / "settings.json").write_text("{}", encoding="utf-8")


def test_removes_a_tree_in_its_own_folder(tmp_path):
    # On a Mac or Linux each entry goes by its name inside an open folder.
    (tmp_path / "tree" / "a").mkdir(parents=True)
    (tmp_path / "tree" / "a" / "b.json").write_text("{}", encoding="utf-8")
    shutil.rmtree(tmp_path / "tree")
    with tempfile.TemporaryDirectory() as made:
        Path(made, "c.json").write_text("{}", encoding="utf-8")


def test_removes_a_tree_outside():
    shutil.rmtree(OUTSIDE / "kept", ignore_errors=True)
'''


def test_a_test_that_writes_outside_its_temp_folders_fails_and_writes_nothing(tmp_path):
    run = tmp_path / "run"
    temp, outside, own = run / "temp", run / "outside", run / "own-home"
    for folder in (temp, outside / "kept", own):
        folder.mkdir(parents=True)
    (outside / "kept" / "x.json").write_text("{}", encoding="utf-8")
    (run / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (run / "conftest.py").write_text(
        "import runpy\nglobals().update({k: v for k, v in runpy.run_path(%r).items() "
        "if not k.startswith('__')})\n" % str(HERE / "conftest.py"), encoding="utf-8")
    (run / "test_writers.py").write_text(WRITERS, encoding="utf-8")
    env = dict(os.environ, OUTSIDE=str(outside), TMP=str(temp), TEMP=str(temp),
               TMPDIR=str(temp), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               HOME=str(own), USERPROFILE=str(own), APPDATA=str(own / "AppData" / "Roaming"),
               LOCALAPPDATA=str(own / "AppData" / "Local"), XDG_CONFIG_HOME=str(own / ".config"))
    for name in ("PYTEST_ADDOPTS", "PYTEST_DEBUG_TEMPROOT"):
        env.pop(name, None)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "--color=no", "-p", "no:cacheprovider",
         "--basetemp", str(temp / "base"), "test_writers.py"],
        cwd=run, env=env, capture_output=True, text=True, timeout=300)
    said = done.stdout + done.stderr
    ended = {}
    for line in said.splitlines():
        word, _, rest = line.partition(" test_writers.py::")
        if rest and word in ("PASSED", "FAILED", "ERROR"):
            ended.setdefault(rest.split(" ")[0], set()).add(word)
    assert ended == {
        "test_with_a_module_fixture_that_saves_in_its_home": {"PASSED"},
        "test_with_a_fixture_that_saves_outside": {"ERROR"},
        "test_with_a_fixture_that_saves_outside_when_done": {"PASSED", "ERROR"},
        "test_saves_outside": {"FAILED", "ERROR"},
        "test_saves_outside_and_hides_the_error": {"PASSED", "ERROR"},
        "test_moves_a_file_outside": {"FAILED", "ERROR"},
        "test_makes_a_folder_outside": {"FAILED", "ERROR"},
        "test_saves_in_its_own_folder": {"PASSED"},
        "test_saves_in_its_home": {"PASSED"},
        "test_removes_a_tree_in_its_own_folder": {"PASSED"},
        "test_removes_a_tree_outside": {"FAILED", "ERROR"},
    }, said
    assert done.returncode == 1, said
    assert str(outside / "caught.json") in said
    left = sorted(p.relative_to(run).as_posix() for folder in (outside, own)
                  for p in folder.rglob("*"))
    assert left == ["outside/kept", "outside/kept/x.json"], said
