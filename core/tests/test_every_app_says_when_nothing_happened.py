"""An app never ends as though it did what it was asked when it did not.

The panel reads how an app's run went from its exit code. Open sign-in
window returned 0 when no browser could open at all, so the panel put a
green "Sign-in window opened" over the words saying none had. Record
returned 0 when the recorder refused, on a sign-in page, or when nothing
was clicked, and the panel said "Recording saved", ready to attach to an
issue. The core says why in words either way. Each app now ends with the
core's NOTHING_OPENED or NOTHING_RECORDED, so the panel can say plainly
that nothing happened.
"""
import ast
import re
from pathlib import Path

import pytest

from paperpull_core import run_reporting

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))


def _method(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(found) == 1, "%s has one %s" % (path.name, name)
    return found[0]


def _exits_with(node, constant: str) -> bool:
    return any(isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
               and getattr(n.exc.func, "id", "") == "SystemExit"
               and [getattr(a, "id", "") for a in n.exc.args] == [constant]
               for n in ast.walk(node))


def test_every_app_is_checked():
    assert len(ENTRIES) >= 81


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.parent.name)
def test_no_window_is_never_a_window_opened(path):
    fn = _method(path, "cmd_open_browser")
    no_name = [n for n in ast.walk(fn) if isinstance(n, ast.If)
               and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not)
               and getattr(n.test.operand, "id", "") == "name"]
    assert len(no_name) == 1, "%s asks whether a browser opened" % path.parent.name
    assert _exits_with(no_name[0], "NOTHING_OPENED"), \
        "%s ends a sign-in with no window as if one opened" % path.parent.name


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.parent.name)
def test_nothing_recorded_is_never_a_recording_saved(path):
    fn = _method(path, "cmd_record")
    checked = [n for n in ast.walk(fn) if isinstance(n, ast.If)
               and isinstance(n.test, ast.Compare)
               and isinstance(n.test.left, ast.Call)
               and getattr(n.test.left.func, "id", "") == "record_session"
               and isinstance(n.test.ops[0], ast.Is)]
    assert len(checked) == 1, "%s reads what record_session answered" % path.parent.name
    assert _exits_with(checked[0], "NOTHING_RECORDED"), \
        "%s ends an empty or refused recording as saved" % path.parent.name


def test_the_panel_reads_the_same_numbers():
    js = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"const NOTHING_OPENED = '(\d+)', NOTHING_RECORDED = '(\d+)';", js)
    assert m, "app.js names both codes"
    assert (int(m.group(1)), int(m.group(2))) == (run_reporting.NOTHING_OPENED,
                                                  run_reporting.NOTHING_RECORDED)


def test_the_codes_are_not_ones_an_app_already_uses():
    taken = {0, 1, 2, 3, 130}
    assert run_reporting.NOTHING_OPENED not in taken
    assert run_reporting.NOTHING_RECORDED not in taken
    assert run_reporting.NOTHING_OPENED != run_reporting.NOTHING_RECORDED
