"""Every browser a test starts as a program of its own keeps off the Keychain.

On a Mac, Chromium asks the login Keychain for its "Chrome Safe Storage"
key the first time a profile starts, to encrypt that profile's cookies. A
test browser starts with a fresh profile each time, so a full run put up
the "wants to use your confidential information" prompt again and again.
Playwright's own launch passes --use-mock-keychain, so the browsers it
starts never asked. The browsers a test starts itself with
subprocess.Popen and a debugging port did not pass it, testkit's
_start_fresh_browser and the copies of _start_browser in the tests.

This reads testkit and every test file and fails on a command line, a
list holding --remote-debugging-port, that does not also hold
--use-mock-keychain. A command line inside a string, a sample the census
tests read, is not a command line here. The sign-in browser in
browser.py is left out on purpose: it is the person's own profile and
keeps its cookies in the real Keychain.
"""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTKIT = REPO / "core" / "paperpull_core" / "testkit.py"
MOCK = "--use-mock-keychain"
# Written as a pattern rather than the switch itself: the census in
# test_every_fresh_browser_draws_before_an_app_attaches takes a function
# holding the bare switch for one that starts a browser.
PORT = re.compile(r"^--remote-debugging-port\b")


def files_read():
    yield TESTKIT
    for path in sorted(REPO.glob("*/**/tests/**/*.py")):
        if not any(p.startswith(".") or p == "node_modules" for p in path.relative_to(REPO).parts):
            yield path


def strings(node):
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def command_lines(path):
    """Each list in the file that names a debugging port, with its line."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.List) and any(PORT.match(s) for s in strings(node)):
            yield node.lineno, strings(node)


def test_every_browser_a_test_starts_uses_the_mock_keychain():
    found, missing = 0, []
    for path in files_read():
        for line, args in command_lines(path):
            found += 1
            if MOCK not in args:
                missing.append("%s:%d" % (path.relative_to(REPO), line))
    assert found >= 10, "the census found only %d command lines; is it reading the tests?" % found
    assert missing == [], "add %r to these browser command lines: %s" % (MOCK, missing)
