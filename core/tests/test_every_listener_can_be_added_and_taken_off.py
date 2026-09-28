"""Every listener handed to Playwright can be added, and taken off again.

Meijer handed page.on a list's own append method (#42). Playwright marks the
function it is given so it can find it again, a built-in method cannot be
marked, and every receipt on 0.39.1 raised AttributeError before anything
was pressed. No test pressed a receipt control in a browser, so nothing had
run that line. The same code took the listener off with a second
downloads.append, which is a new object each time it is written and so
never the one that was added.

This asks every app, the core and the panel at once, by what the code does,
whether a listener is a built-in, a collection's own method or a function
such as print, or is taken off with an expression that makes a new object
each time.
"""
import ast
import builtins
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

ADDS = {"on", "once", "add_listener", "remove_listener", "off"}
# Methods of list, set, dict, deque and queue that a listener might be
# written as. Each is built in, so none can carry Playwright's mark.
BUILT_IN = {"append", "appendleft", "add", "extend", "insert", "put", "put_nowait",
            "update", "setdefault"}

# A built-in function handed over by its bare name, print say, which
# Playwright cannot mark either.
BUILT_IN_NAMES = {n for n in dir(builtins) if callable(getattr(builtins, n))
                  and not isinstance(getattr(builtins, n), type)}


def is_built_in(handler) -> bool:
    """A handler Playwright cannot mark."""
    return ((isinstance(handler, ast.Attribute) and handler.attr in BUILT_IN)
            or (isinstance(handler, ast.Name) and handler.id in BUILT_IN_NAMES))


def is_new_each_time(handler) -> bool:
    """A handler that is a new object each time it is written."""
    return isinstance(handler, ast.Lambda) or (
        isinstance(handler, ast.Attribute) and handler.attr in BUILT_IN)


PLACES = ([d for d in sorted((REPO / "apps").iterdir()) if d.is_dir() and list(d.glob("*.py"))]
          + [REPO / "core" / "paperpull_core", REPO / "gui"])


def listeners(tree):
    """(line, method, handler) for every call that adds or takes off one."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ADDS and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            yield node.lineno, node.func.attr, node.args[1]


def found_in(place: Path):
    """(file, line, method, handler) for every listener in a folder's own
    modules, its tests left out."""
    for path in sorted(place.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for line, how, handler in listeners(tree):
            yield path.name, line, how, handler


@pytest.mark.parametrize("place", PLACES, ids=lambda p: p.name)
def test_no_listener_is_a_built_in_method(place):
    bad = ["%s line %d, %s(..., %s)" % (name, line, how, ast.unparse(handler))
           for name, line, how, handler in found_in(place)
           if is_built_in(handler)]
    assert not bad, "a built-in handed to Playwright as a listener: %s" % "; ".join(bad)


@pytest.mark.parametrize("place", PLACES, ids=lambda p: p.name)
def test_a_listener_is_taken_off_with_the_one_that_was_added(place):
    """A lambda, or an attribute of a collection, is a new object each time
    it is written, so taking it off removes nothing."""
    bad = ["%s line %d, %s" % (name, line, ast.unparse(handler))
           for name, line, how, handler in found_in(place)
           if how in ("remove_listener", "off") and is_new_each_time(handler)]
    assert not bad, "a listener taken off with a new object: %s" % "; ".join(bad)


def test_this_finds_what_meijer_shipped():
    """Proof the check is not passing for want of anything to look at."""
    shipped = ('def press(page):\n'
               '    downloads = []\n'
               '    page.on("download", downloads.append)\n'
               '    page.remove_listener("download", downloads.append)\n')
    found = list(listeners(ast.parse(shipped)))
    assert [(how, ast.unparse(h)) for _, how, h in found] == [
        ("on", "downloads.append"), ("remove_listener", "downloads.append")]
    assert all(is_built_in(h) for _, _how, h in found)
    assert is_new_each_time(found[1][2])
    assert is_built_in(ast.parse("print", mode="eval").body)
    assert not is_built_in(ast.parse("on_download", mode="eval").body)
    assert not is_new_each_time(ast.parse("on_download", mode="eval").body)
    assert sum(1 for place in PLACES for _ in found_in(place)) > 20, \
        "few listeners anywhere, so the check is looking in the wrong place"
