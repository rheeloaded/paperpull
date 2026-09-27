"""The double-click files do what they say, run for real (#47).

review_names.bat and review_names.command find the Python a folder should
run on, a checkout's own venv, or the packaged app's Python when the folder
has no setup file, which is how a folder the packaged app made looks. They
hand the app the account named after them, and pass its exit code back.

paperpull.bat opens the control panel when it is double-clicked in the
packaged app with nothing after it, because older shortcuts to the panel's
old launcher land on it, and otherwise runs the terminal command. Its exit
code is the command's, where every run used to report success.

The batch files run under cmd, on Windows only. The .command runs under
bash, Git's own on Windows, so the Windows test runner covers both. No
test here links to a real Python folder. A stand-in Python is a copy of
the interpreter's own files, pointed at its library by PYTHONHOME, so
nothing that cleans up a test folder can reach a real install.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WINDOWS = sys.platform == "win32"
APP = "lowes"                       # the one with an apostrophe in its name
SCRIPT = "lowes_receipts.py"

# The app's own script, replaced by one that says what it was given.
FAKE_APP = "import sys\nprint('APP GOT', sys.argv[1:])\nsys.exit(4)\n"

windows_only = pytest.mark.skipif(not WINDOWS, reason="batch files run on Windows")


def _bash():
    """Git's bash on Windows, never the WSL one on PATH, whose paths differ."""
    if WINDOWS:
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


def _stand_in_python(folder: Path) -> dict:
    """A python.exe in `folder` that runs, and the environment it needs."""
    folder.mkdir(parents=True, exist_ok=True)
    base = Path(sys.base_prefix)
    for f in [base / "python.exe", *base.glob("*.dll")]:
        shutil.copy2(f, folder / f.name)
    return dict(os.environ, PYTHONHOME=str(base))


def _cmd(bat: Path, *args, env=None):
    """Run a batch file the way a double-click does, with no one to press a
    key at its pause."""
    line = subprocess.list2cmdline([str(bat), *args])
    return subprocess.run("cmd /c " + line + " < NUL", shell=True, capture_output=True,
                          text=True, env=env, cwd=str(bat.parent))


# -- review_names.bat ----------------------------------------------------------

@windows_only
def test_review_names_bat_runs_on_the_installed_apps_python(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.bat", install)
    (install / SCRIPT).write_text(FAKE_APP, encoding="utf-8")
    env = _stand_in_python(tmp_path / "Local" / "PaperPull" / "python")
    env["LOCALAPPDATA"] = str(tmp_path / "Local")

    r = _cmd(install / "review_names.bat", env=env)
    assert "APP GOT ['--review-names']" in r.stdout, r.stdout + r.stderr
    assert "Lowe's Receipts - review names" in r.stdout
    assert r.returncode == 4, "the app's own exit code must come back"

    r = _cmd(install / "review_names.bat", "spouse", env=env)
    assert "APP GOT ['--review-names', '--config', 'config.spouse.json']" in r.stdout, r.stdout


@windows_only
def test_review_names_bat_asks_for_setup_in_a_checkout_that_has_none(tmp_path):
    """A folder with setup.bat is set up by it, and never borrows the
    installed app's Python, whose shared code may be another version."""
    folder = tmp_path / "lowes"
    folder.mkdir()
    for name in ("review_names.bat", "setup.bat"):
        shutil.copy2(REPO / "apps" / APP / name, folder)
    (folder / SCRIPT).write_text(FAKE_APP, encoding="utf-8")
    env = _stand_in_python(tmp_path / "Local" / "PaperPull" / "python")
    env["LOCALAPPDATA"] = str(tmp_path / "Local")

    r = _cmd(folder / "review_names.bat", env=env)
    assert "run setup.bat first" in r.stdout, r.stdout
    assert "APP GOT" not in r.stdout
    assert r.returncode == 1


@windows_only
def test_review_names_bat_says_what_to_do_when_the_app_is_not_installed(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.bat", install)
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "nowhere"))
    r = _cmd(install / "review_names.bat", env=env)
    assert "was not found" in r.stdout and "paperpull.bat lowes review-names" in r.stdout, r.stdout
    assert r.returncode == 1


# -- paperpull.bat -------------------------------------------------------------

def _packaged_folder(tmp_path: Path, with_exe: bool) -> tuple:
    folder = tmp_path / ("installed" if with_exe else "checkout")
    env = _stand_in_python(folder / "python")
    shutil.copy2(REPO / "paperpull.bat", folder)
    (folder / "paperpull.py").write_text(
        "import sys\nprint('TERMINAL GOT', sys.argv[1:])\nsys.exit(3)\n", encoding="utf-8")
    if with_exe:
        # Stands in for the panel's PaperPull.exe. It prints this computer's
        # name, which nothing else here does.
        shutil.copy2(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "hostname.exe",
                     folder / "PaperPull.exe")
    return folder, env


@windows_only
def test_paperpull_bat_double_clicked_in_the_package_opens_the_panel(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=True)
    r = _cmd(folder / "paperpull.bat", env=env)
    assert os.environ.get("COMPUTERNAME", "").lower() in r.stdout.lower(), r.stdout + r.stderr
    assert "TERMINAL GOT" not in r.stdout


@windows_only
def test_paperpull_bat_with_a_command_runs_it_and_passes_its_exit_code_back(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=True)
    r = _cmd(folder / "paperpull.bat", "costco", "review-names", env=env)
    assert "TERMINAL GOT ['costco', 'review-names']" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3


@windows_only
def test_paperpull_bat_in_a_checkout_is_only_the_terminal_command(tmp_path):
    folder, env = _packaged_folder(tmp_path, with_exe=False)
    r = _cmd(folder / "paperpull.bat", env=env)
    assert "TERMINAL GOT []" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 3


# -- review_names.command ------------------------------------------------------

def _run_command(script: Path, home: Path, *args):
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run a .command with")
    env = dict(os.environ, HOME=home.as_posix())
    return subprocess.run([bash, script.as_posix(), *args], capture_output=True, text=True,
                          env=env, cwd=str(script.parent))


def _fake_mac_app(home: Path) -> None:
    """PaperPull.app in ~/Applications, with a python3 that says what it
    was given and whether it was started the way the app starts it."""
    py = home / "Applications" / "PaperPull.app" / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\necho "BUNDLED PY: $* NOUSERSITE=$PYTHONNOUSERSITE"\n',
                  encoding="utf-8", newline="\n")
    py.chmod(0o755)


def test_review_names_command_runs_on_the_apps_own_python(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.command", install)
    _fake_mac_app(tmp_path / "home")

    r = _run_command(install / "review_names.command", tmp_path / "home")
    assert "BUNDLED PY: %s --review-names NOUSERSITE=1" % SCRIPT in r.stdout, r.stdout + r.stderr
    assert "Lowe's Receipts - review names" in r.stdout
    assert r.returncode == 0

    r = _run_command(install / "review_names.command", tmp_path / "home", "spouse")
    assert "--review-names --config config.spouse.json" in r.stdout, r.stdout + r.stderr


def test_review_names_command_asks_for_setup_in_a_checkout_that_has_none(tmp_path):
    folder = tmp_path / "lowes"
    folder.mkdir()
    for name in ("review_names.command", "setup.command"):
        shutil.copy2(REPO / "apps" / APP / name, folder)
    _fake_mac_app(tmp_path / "home")
    r = _run_command(folder / "review_names.command", tmp_path / "home")
    assert "run ./setup.command first" in r.stdout, r.stdout + r.stderr
    assert "BUNDLED PY" not in r.stdout
    assert r.returncode == 1


def test_review_names_command_says_what_to_do_when_the_app_is_not_found(tmp_path):
    install = tmp_path / "Lowe's Receipts"
    install.mkdir()
    shutil.copy2(REPO / "apps" / APP / "review_names.command", install)
    (tmp_path / "home").mkdir()
    r = _run_command(install / "review_names.command", tmp_path / "home")
    assert "was not found in Applications" in r.stdout, r.stdout + r.stderr
    assert "paperpull lowes review-names" in r.stdout
    assert r.returncode == 1
