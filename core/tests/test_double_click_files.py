"""The double-click files do what they say, run for real (#47).

review_names.bat and review_names.command find the Python a folder should
run on, a checkout's own venv, or the packaged app's Python when the folder
has no setup file, which is how a folder the packaged app made looks. They
hand the app the account named after them, and pass its exit code back.

paperpull.bat opens the control panel when it is double-clicked in the
packaged app with nothing after it, because older shortcuts to the panel's
old launcher land on it, and otherwise runs the terminal command. Its exit
code is the command's, where every run used to report success.

setup-all.bat says all is set when every setup worked, and names the one
that did not, where every run since 0.19.0 reported a problem.

The batch files run under cmd, on Windows only. The .command runs under
bash, Git's own on Windows, so the Windows test runner covers both. No
test here links to a real Python folder. A stand-in Python is a copy of
the interpreter's own files, pointed at its library by PYTHONHOME, so
nothing that cleans up a test folder can reach a real install.

Every shell script the repository ships is also read by bash -n, which
runs none of it, since setup-all.command did not parse for a month and
nothing asked. A Mac runs a .command with /bin/bash, which is 3.2, so on
a Mac that bash reads them as well, and CI does this on macOS and Linux.
"""
import os
import re
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


# -- setup-all.bat -------------------------------------------------------------

# pip in the stand-in venvs. It fails the requirements of the folder named in
# FAKE_PIP_FAILS_IN and does nothing else, so nothing is ever installed.
FAKE_PIP = ("import os, sys\n"
            "failing = os.path.basename(os.getcwd()) == os.environ.get('FAKE_PIP_FAILS_IN')\n"
            "sys.exit(1 if failing and '-r' in sys.argv else 0)\n")


def _setup_all_checkout(tmp_path: Path) -> tuple:
    """setup-all.bat beside one app and the GUI, each with a venv already
    there, so it makes none, and a pip that is FAKE_PIP."""
    checkout = tmp_path / "checkout"
    for folder in ("apps/demo", "gui"):
        (checkout / folder).mkdir(parents=True)
        (checkout / folder / "requirements.txt").write_text("pypdf\n", encoding="utf-8")
        env = _stand_in_python(checkout / folder / ".venv" / "Scripts")
    (checkout / "core").mkdir()
    (checkout / "core" / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copy2(REPO / "setup-all.bat", checkout)
    pip = tmp_path / "fake" / "pip"
    pip.mkdir(parents=True)
    (pip / "__init__.py").write_text("", encoding="utf-8")
    (pip / "__main__.py").write_text(FAKE_PIP, encoding="utf-8")
    env.update(PYTHONPATH=str(tmp_path / "fake"), PYTHONNOUSERSITE="1", PIP_NO_INDEX="1")
    # The script stops when it finds no Python on PATH, so one is there.
    env["PATH"] = str(checkout / "gui" / ".venv" / "Scripts") + os.pathsep + env.get("PATH", "")
    return checkout, env


@windows_only
def test_setup_all_bat_says_all_set_when_nothing_failed_and_names_what_did(tmp_path):
    """From 0.19.0 every run listed playwright-chromium among the setups
    that had problems and asked for another run, since the script still
    checked for a browser download it no longer made."""
    checkout, env = _setup_all_checkout(tmp_path)
    r = _cmd(checkout / "setup-all.bat", env=env)
    assert "All set - 1 apps + the GUI are ready." in r.stdout, r.stdout + r.stderr
    assert "problems" not in r.stdout

    env["FAKE_PIP_FAILS_IN"] = "demo"
    r = _cmd(checkout / "setup-all.bat", env=env)
    assert "Some setups had problems: demo(deps)" in r.stdout, r.stdout + r.stderr


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


# -- every shell script parses -------------------------------------------------

# A first line that hands the file to sh or bash.
SHELL_FIRST_LINE = re.compile(r"#!\s*(/usr)?/bin/(env\s+)?(ba)?sh\b")

# What removing the browser download left in setup-all.command in 0.19.0, an
# if with nothing but comments in it, which bash refuses to read.
EMPTIED_IF = """#!/usr/bin/env bash
for app in apps/*/; do
    if [ $first -eq 1 ]; then
# The browser download is no longer part of setup.
    fi
    echo "ok"
done
"""


def _bashes():
    """Each bash here that a script could meet. A Mac runs a .command with
    /bin/bash, which is 3.2, while PATH can find a newer one first."""
    found = {}
    for bash in (_bash(), None if WINDOWS else "/bin/bash"):
        if bash and Path(bash).is_file():
            found.setdefault(os.path.realpath(bash), bash)
    return list(found.values())


def _shell_scripts():
    """(path, text) for every tracked file a shell runs, found by its suffix
    or its first line, so paperpull, which has no suffix, is one of them."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")
    listed = subprocess.run([git, "ls-files", "-z"], cwd=REPO, capture_output=True)
    if listed.returncode:
        pytest.skip("not a git checkout")
    scripts = []
    for rel in listed.stdout.decode("utf-8").split("\0"):
        f = REPO / rel
        if not rel or not f.is_file():
            continue
        with f.open("rb") as fh:
            first = fh.readline(200).decode("utf-8", "replace")
        if f.suffix in (".command", ".sh") or SHELL_FIRST_LINE.match(first):
            # Read as text, so the CRLF a Windows checkout can give a file
            # that git stores with LF does not count against it.
            scripts.append((rel, f.read_text(encoding="utf-8")))
    return scripts


def _parse_errors(bash, scripts, folder: Path) -> list:
    """What bash -n says about each script that does not parse, or whose
    here-document runs to the end of the file, which bash -n only warns of.

    Each script gets a bash of its own, except on Windows, where Git's bash
    takes one to nine seconds to start on a busy machine. There one bash
    reads them all, each the body of a function of its own after a no-op,
    so that a script of comments alone still parses, and prints them back
    with --pretty-print, which runs nothing. Every function has to come
    back, in order, since a quote left open in one script can run into the
    next and close on a later apostrophe, and the whole would still parse.
    When they do not, halving the scripts finds the first one that breaks
    them, and bash reads that one alone, so the message is its own."""
    def alone(n):
        name, text = scripts[n]
        f = folder / ("alone-%d.sh" % n)
        f.write_bytes(text.encode("utf-8"))
        r = subprocess.run([bash, "-n", f.as_posix()], capture_output=True, text=True)
        said = r.stderr.replace(f.as_posix(), name).strip()
        if r.returncode or "delimited by end-of-file" in said:
            return said or "bash -n ended %d on %s" % (r.returncode, name)
        return ""

    def first_ones_come_back(n):
        """Whether the first n scripts come back as n functions, or None
        from a bash before 5.2, which has no --pretty-print."""
        f = folder / ("first-%d.sh" % n)
        f.write_bytes("".join("function _script_%d {\n:\n%s\n\n}\n" % (i, text)
                              for i, (_, text) in enumerate(scripts[:n])).encode("utf-8"))
        r = subprocess.run([bash, "--pretty-print", f.as_posix()], capture_output=True, text=True)
        if r.returncode and "--pretty-print" in r.stderr:
            return None
        back = re.findall(r"^(?:function )?_script_(\d+) \(\)", r.stdout, re.M)
        return r.returncode == 0 and back == [str(i) for i in range(n)]

    every = first_ones_come_back(len(scripts)) if WINDOWS else None
    if every is None:
        return [e for e in map(alone, range(len(scripts))) if e]
    if every:
        return []
    # The first `good` scripts come back and the first `bad` do not.
    good, bad = 0, len(scripts)
    while bad - good > 1:
        mid = (good + bad) // 2
        if first_ones_come_back(mid):
            good = mid
        else:
            bad = mid
    return [alone(bad - 1) or "%s parses alone but not as the body of a function"
            % scripts[bad - 1][0]]


@pytest.mark.parametrize("bash", _bashes())
def test_the_parse_check_names_an_if_with_nothing_left_in_it(bash, tmp_path):
    """Among scripts that parse, the check names the one that does not, in
    bash's own words, a quote left open is named although a later
    apostrophe closes it, and a script of a comment alone parses, as it
    does for bash -n on its own."""
    before = ("before.sh", "#!/bin/sh\necho before\n")
    notes = ("notes.sh", "#!/bin/sh\n# a comment and nothing else\n")
    errors = _parse_errors(bash, [before, ("emptied.command", EMPTIED_IF), notes], tmp_path)
    assert len(errors) == 1, errors
    assert errors[0].startswith("emptied.command: line 5: syntax error"), errors

    open_quote = ("open-quote.command", "#!/usr/bin/env bash\necho 'Run this app's setup first'\n")
    later = ("later.sh", "#!/bin/sh\n# this app's own check\necho done\n")
    errors = _parse_errors(bash, [open_quote, later, notes], tmp_path)
    assert len(errors) == 1, errors
    assert errors[0].startswith("open-quote.command: line "), errors
    assert "unexpected EOF while looking for matching" in errors[0], errors

    assert _parse_errors(bash, [notes, before], tmp_path) == []


@pytest.mark.parametrize("bash", _bashes())
def test_every_shell_script_parses(bash, tmp_path):
    """From 0.19.0, setup-all.command held an if with nothing but comments
    in it. bash reads a whole loop before it runs any of it, so the script
    printed its header and the Python it found, ended on a syntax error,
    and set nothing up."""
    scripts = _shell_scripts()
    names = {name for name, _ in scripts}
    assert len(scripts) > 100, len(scripts)
    assert {"setup-all.command", "paperpull", "server/start.sh"} <= names, sorted(names)
    errors = _parse_errors(bash, scripts, tmp_path)
    assert not errors, "bash cannot read these.\n" + "\n".join(errors)


def test_every_shell_script_checks_out_with_unix_line_endings():
    """A Windows clone gives a text file CRLF unless .gitattributes pins
    it, and a script with CRLF does not start on macOS or Linux, or in WSL
    on that clone. paperpull has no suffix, so the *.command and *.sh lines
    missed it, and in WSL it said env could not find bash with a carriage
    return on the end."""
    names = [name for name, _ in _shell_scripts()]
    assert "paperpull" in names, names
    r = subprocess.run([shutil.which("git"), "check-attr", "-z", "eol", "--", *names],
                       cwd=REPO, capture_output=True, text=True)
    fields = r.stdout.split("\0")
    eol = dict(zip(fields[0::3], fields[2::3]))
    unpinned = [name for name in names if eol.get(name) != "lf"]
    assert not unpinned, "pin these to LF in .gitattributes, " + ", ".join(unpinned)
