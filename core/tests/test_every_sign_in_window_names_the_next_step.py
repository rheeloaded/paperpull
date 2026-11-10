"""Every sign-in window says what to do once signed in, in the words of
where the run is.

Open sign-in window ended its log with "then run the pilot", a command
nobody under the control panel can type. Most apps moved to the panel's
own button, and six were left saying "run the pilot" or "press Discover or
Pilot". Each app's cmd_open_browser now ends with run_reporting.after_sign_in,
which names the panel's button under the panel and the pilot in a
terminal, and the button it names is the one the panel shows.
"""
import ast
import re
from pathlib import Path

import pytest

from paperpull_core import run_reporting

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))

# The runs as a terminal names them, which no button under the panel is.
TERMINAL_WORDS = ("pilot", "discover")


def _method(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, "%s has one %s" % (path.name, name)
    return found[0]


def _prints(fn) -> list:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "print"]


def _calls(node, name: str) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == name
               for n in ast.walk(node))


def test_every_app_is_checked():
    assert len(ENTRIES) >= 85


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.parent.name)
def test_the_window_names_the_next_step_where_the_run_is(path):
    fn = _method(path, "cmd_open_browser")
    prints = _prints(fn)
    assert any(_calls(p, "after_sign_in") for p in prints), \
        "%s says what to do once signed in through after_sign_in" % path.parent.name
    said = [n.value for p in prints for n in ast.walk(p)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and any(w in n.value.lower() for w in TERMINAL_WORDS)]
    assert not said, "%s names a run as a terminal does, %r" % (path.parent.name, said)


def test_the_button_it_names_is_the_panels(monkeypatch):
    js = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"^\s*pilot: \['([^']+)',", js, re.M)
    assert m, "app.js names the button for the newest few"
    monkeypatch.setenv(run_reporting.MARK_ENV, "0" * 32)
    assert run_reporting.after_sign_in() == "press " + m.group(1)
    monkeypatch.delenv(run_reporting.MARK_ENV)
    assert run_reporting.after_sign_in() == "run the pilot"
