"""Every action a workflow runs is named by its full commit, with the version
it is beside it, and Dependabot proposes their updates.

A tag is whatever its owner points it at today, and these workflows sign
the Windows package with the release environment's Azure credential, sign
and notarize the Mac bundle with its certificate, and push the server image.
A commit cannot be moved. The workflows are read as text, since the Python
that runs this suite may have no YAML parser.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40} # v\d+\.\d+\.\d+")


def _uses():
    for wf in WORKFLOWS:
        for n, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(-\s+)?uses:\s*(.+?)\s*$", line)
            if m:
                yield wf.name, n, m.group(2)


def test_every_action_is_named_by_its_commit_and_version():
    found = list(_uses())
    assert {name for name, _, _ in found} == {wf.name for wf in WORKFLOWS}, "every workflow uses actions"
    for name, n, ref in found:
        assert PINNED.fullmatch(ref), "%s:%d %s" % (name, n, ref)


def test_one_action_is_at_one_commit_everywhere():
    """Two versions of the same action is a half-done update."""
    seen = {}
    for name, n, ref in _uses():
        action, at = ref.split("@", 1)
        seen.setdefault(action, set()).add(at)
    assert all(len(at) == 1 for at in seen.values()), seen


def test_dependabot_proposes_the_actions_updates():
    text = (REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    block = text.split("package-ecosystem: github-actions", 1)[1].split("package-ecosystem:", 1)[0]
    assert re.search(r"directory: /\s*$", block, re.M), "the root, which takes in .github/workflows"
    assert "interval: weekly" in block


def test_the_tests_run_on_the_versions_the_windows_package_ships():
    """tools/release.sh waits for a passing Tests run, so it must be a run
    of what the package carries, not of whatever PyPI held that day."""
    text = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    install = text.split("- name: Install what every suite needs", 1)[1].split("- name:", 1)[0]
    lines = [line.strip() for line in install.splitlines() if "pip install" in line]
    assert lines == [
        "python -m pip install --upgrade pip",
        "python -m pip install --require-hashes --only-binary :all: -r packaging/requirements-windows-x64.txt",
        "python -m pip install pytest==9.1.1",
        "python -m pip install --no-deps --no-build-isolation ./core",
    ]
    assert (REPO / "packaging" / "requirements-windows-x64.txt").is_file()


def test_every_pytest_the_tests_install_is_one_pinned_version():
    """The runner reads pytest's output, so a pytest that came out after the
    last run here is not taken unseen. 9.2.0 printed each failure under two
    paths and failed the runner's own tests on a tag (2026-10-30)."""
    text = (REPO / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    installs = re.findall(r"pip install (?:\S+ )*pytest\S*", text)
    assert len(installs) == 2, installs
    assert set(installs) == {"pip install pytest==9.1.1"}, installs


def test_each_package_workflow_checks_the_python_it_installed():
    """The packaged interpreter is asked its version on the runner, after
    the build, against the version the builder names. The installed MSIX
    is asked through its interpreter DLL's version, since a program inside
    WindowsApps does not start by its path with its output read."""
    win = (REPO / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    mac = (REPO / ".github" / "workflows" / "build-macos.yml").read_text(encoding="utf-8")
    assert "build_windows.PY_VERSION" in win and '-Filter "python3*.dll"' in win
    assert "$dll.VersionInfo.ProductVersion" in win
    assert 'python\\python.exe") -c' not in win, "WindowsApps refuses it"
    assert re.search(r"if \(\$have -ne \$want\) \{ throw ", win)
    assert "build_macos.PY_VERSION" in mac and 'test "$have" = "$want"' in mac
