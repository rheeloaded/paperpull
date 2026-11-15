"""What a Diagnose writes as "collected" is a count, never an error.

The core reads a detailed Diagnose file for whether it read anything at all
(paperpull_core.words, _note_what_was_read). A report made on a sign-in page
or a security check that collected nothing says so, and the panel tells the
person to sign in rather than that a report was saved. "Nothing" there is a
count of none.

Seven apps wrote the error their listing met into "collected", the type of
error in four first shells and its whole message in Fidelity, NetBenefits and
Invest529. A signed-out report then held words there, which read as
something collected, so it was called a saved report. And three of those
wrote the count over the error a moment later anyway, so the error was lost
and a listing that failed read as an account with nothing to list. An error
goes under a key of its own, "collect_error", as several apps already did.

This reads the shape of the code. Every assignment to info["collected"] in
an app's own script is a len() of something, a whole number such as the 0
a failed listing collected, or, as two apps write it, a len() or None.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in REPO.glob("apps/*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")) and not p.name.startswith("."))


def _is_count(node) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
        return True
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return True
    if isinstance(node, ast.IfExp):
        return all(_is_count(n) or (isinstance(n, ast.Constant) and n.value is None)
                   for n in (node.body, node.orelse))
    return False


def _key(target):
    """The constant key of a subscript, through Fixed("...") as ING writes
    its keys, or None."""
    if not isinstance(target, ast.Subscript):
        return None
    key = target.slice
    if isinstance(key, ast.Call) and key.args and isinstance(key.args[0], ast.Constant):
        key = key.args[0]
    return key.value if isinstance(key, ast.Constant) else None


def _writes(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if _key(target) == "collected":
                    yield node.lineno, node.value


def test_the_census_finds_apps_to_read():
    assert len(ENTRIES) > 80
    assert sum(1 for p in ENTRIES for _ in _writes(p)) >= 40, "the census found the writes"


@pytest.mark.parametrize("path", ENTRIES, ids=lambda p: p.parent.name)
def test_collected_is_only_ever_a_count(path):
    wrong = ["%s:%d" % (path.relative_to(REPO), line)
             for line, value in _writes(path) if not _is_count(value)]
    assert not wrong, ("an error is written into collected, where a signed-out report then "
                       "reads as one that collected something. Put it under collect_error. "
                       + ", ".join(wrong))


def test_the_census_tells_an_error_from_a_count():
    """Its own check, against the two shapes it is there to catch and the
    shapes it lets through."""
    def value(src):
        return ast.parse(src).body[0].value
    assert _is_count(value("x = len(docs)"))
    assert _is_count(value("x = len(docs) if docs is not None else None"))
    assert _is_count(value("x = 0"))
    assert not _is_count(value("x = True"))
    assert not _is_count(value("x = type(e).__name__"))
    assert not _is_count(value('x = "%s: %s" % (type(e).__name__, e)'))
    assert not _is_count(value("x = len(docs) if docs else type(e).__name__"))
