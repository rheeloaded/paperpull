"""Every panel test keeps to folders of its own.

The panel keeps its settings in one file per person, wherever
app._settings_path says. Windows finds the folder from APPDATA and Linux
from XDG_CONFIG_HOME, and macOS from the home folder alone. The fixtures
here moved APPDATA, LOCALAPPDATA and XDG_CONFIG_HOME into their temp
folders, which on a Mac moved nothing. So a test that saved a setting
there wrote over the person's own settings.json, and the panel they use
every day showed no accounts until apps_root was put back (#153).

So the home folder and every folder the panel finds from a variable point
into a temp folder for the whole run, from before the first test file is
read, and into the test's own tmp_path while each test runs. A fixture or a
test that points one somewhere else, or replaces _settings_path, still
does. APPS_ROOT is taken away too, since a developer who runs the panel
from the repo sets it to their own installs, and no test here relies on it.

Playwright finds its browsers by the same variables, LOCALAPPDATA on
Windows and the home folder on a Mac or Linux. So the folder it would have
used is named outright, found before anything moved. Without that, a test
that starts Chromium after the move skips itself as though none were
installed.

And a guard behind all of it. While a panel test sets up, runs or tears
down, a write anywhere but the temp folders is refused, as a read-only
disk would refuse it, and the test fails naming the path, even when the
code under test caught the error. Only this process is watched, so a
program a test starts is held by the moved variables alone.
"""
import errno
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

try:
    import fcntl
except ImportError:
    fcntl = None

REPO = Path(__file__).resolve().parents[2]


def _browsers_folder():
    """Where Playwright keeps its browsers on this machine, by the rules in
    paperpull_core.browser, read from that file rather than imported, so the
    core this run imports is left to the tests."""
    spec = importlib.util.spec_from_file_location(
        "_panel_tests_browser_rules", REPO / "core" / "paperpull_core" / "browser.py")
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    folder = rules._playwright_root()
    return str(folder) if folder is not None else None


# Read now, while every variable is still the machine's own.
BROWSERS = _browsers_folder()


def _folders(home: Path) -> dict:
    """The variables a home folder sets. Path.home() reads USERPROFILE on
    Windows and HOME everywhere else."""
    return {"HOME": str(home), "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "XDG_CONFIG_HOME": str(home / ".config")}


_RUN_HOME: list = []
_AS_FOUND: dict = {}


def _move_for_the_run():
    home = Path(tempfile.mkdtemp(prefix="panel-tests-home-"))
    _RUN_HOME[:] = [home]
    moved = dict(_folders(home), APPS_ROOT=None)
    if BROWSERS:
        moved["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    for name, value in moved.items():
        _AS_FOUND[name] = os.environ.get(name)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _put_back():
    for name, value in _AS_FOUND.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _AS_FOUND.clear()
    for home in _RUN_HOME:
        shutil.rmtree(home, ignore_errors=True)
    _RUN_HOME.clear()


@pytest.fixture(autouse=True)
def _own_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for name, value in _folders(home).items():
        monkeypatch.setenv(name, value)


# -- the guard -----------------------------------------------------------------

# The audit events that change a file or a folder. For each, the argument
# naming what it changes, and the argument holding the open folder that
# name is relative to, where the event has one. POSIX's shutil.rmtree
# removes each entry by its bare name inside an open folder. An open counts
# when it can write.
_CHANGES = {"os.mkdir": ((0, 2),), "os.rename": ((0, 2), (1, 3)), "os.remove": ((0, 1),),
            "os.rmdir": ((0, 1),), "os.truncate": ((0, None),), "os.utime": ((0, 3),),
            "os.chmod": ((0, 2),), "os.chown": ((0, 3),), "os.symlink": ((1, 2),),
            "os.link": ((1, 3),), "shutil.copyfile": ((1, None),),
            "shutil.copytree": ((1, None),), "shutil.copymode": ((1, None),),
            "shutil.copystat": ((1, None),), "shutil.rmtree": ((0, 1),)}
_WRITING = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

# Folders a test may write in, filled by pytest_configure. Each is a real
# path in normcase, so a Mac's /var and /private/var are one folder.
_ALLOWED: list = []
_WATCHING = False
_WROTE: list = []
_inside = threading.local()


class WroteOutsideItsFolders(PermissionError):
    pass


def _real(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _folder_of(fd):
    """The folder an open descriptor stands for, on macOS and Linux, the
    systems that remove by descriptor, or None."""
    if hasattr(fcntl, "F_GETPATH"):
        try:
            return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0])
        except OSError:
            return None
    try:
        return os.readlink("/proc/self/fd/%d" % fd)
    except OSError:
        return None


def _allowed(full) -> bool:
    if any(full == root or full.startswith(root + os.sep) for root in _ALLOWED):
        return True
    # What Python writes beside a module it imports, the folder included.
    return (os.path.basename(full) == "__pycache__"
            or (os.path.basename(os.path.dirname(full)) == "__pycache__"
                and ".pyc" in os.path.basename(full)))


def _written(event, args) -> list:
    """Each path the event writes, as named and as a real path, leaving out
    one named in a way that cannot be followed."""
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        writes = (any(c in mode for c in "wax+") if isinstance(mode, str)
                  else bool((flags or 0) & _WRITING))
        named = [(path, None)] if writes else []
    else:
        named = [(args[i], args[f] if f is not None and f < len(args) else None)
                 for i, f in _CHANGES[event] if i < len(args)]
    out = []
    for path, fd in named:
        if not isinstance(path, (str, bytes, os.PathLike)):
            continue
        path = os.fsdecode(os.fspath(path))
        if path == os.devnull or path.startswith("\\\\.\\"):
            continue
        if isinstance(fd, int) and fd >= 0 and not os.path.isabs(path):
            folder = _folder_of(fd)
            if folder is None:
                continue
            path = os.path.join(folder, path)
        full = _real(path)
        # Asking for a folder that is already there changes nothing.
        if event == "os.mkdir" and os.path.lexists(full):
            continue
        out.append((path, full))
    return out


def _audit(event, args):
    if not _WATCHING or (event != "open" and event not in _CHANGES):
        return
    if getattr(_inside, "busy", False):
        return
    _inside.busy = True
    try:
        refused = [named for named, full in _written(event, args) if not _allowed(full)]
    finally:
        _inside.busy = False
    for path in refused:
        _WROTE.append("%s %s" % (event, path))
        raise WroteOutsideItsFolders(
            errno.EACCES, "a panel test may write only inside its temp folders", path)


sys.addaudithook(_audit)


def pytest_configure(config):
    roots = [tempfile.gettempdir(), os.environ.get("PYTEST_DEBUG_TEMPROOT"),
             sys.pycache_prefix]
    if config.option.basetemp:
        roots.append(Path(config.option.basetemp).resolve())
    _ALLOWED[:] = sorted({_real(r).rstrip("\\/") for r in roots if r})
    _move_for_the_run()


def pytest_unconfigure(config):
    _put_back()


@contextmanager
def _watched():
    global _WATCHING
    _WATCHING = True
    try:
        yield
    finally:
        _WATCHING = False


def _taken() -> list:
    wrote, _WROTE[:] = list(dict.fromkeys(_WROTE)), []
    return wrote


def _said(wrote) -> str:
    return ("this test wrote outside its temp folders, which no panel test may do "
            "(#153). Point what it writes at tmp_path.\n  " + "\n  ".join(wrote))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    _WROTE.clear()
    with _watched():
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    with _watched():
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    try:
        with _watched():
            result = yield
    except BaseException as e:
        # The teardown's own error stays the one reported, with this added.
        wrote = _taken()
        if wrote:
            e.add_note(_said(wrote))
        raise
    wrote = _taken()
    if wrote:
        pytest.fail(_said(wrote), pytrace=False)
    return result
