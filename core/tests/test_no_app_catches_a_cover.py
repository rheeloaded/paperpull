"""No app catches pressing.Covered, and a press made again after a stop is
made only once that stop is read for whether it came after a press (#221).

A Wells Fargo tester's runs stopped, Covered, on the documents link of the
Accounts menu, before anything was pressed, most likely while the menu was
still opening. The press is now made again once such a cover has passed,
for a few seconds, by paperpull_core.pressing.click_when_clear, which tries
again only a Covered that came before any press. A cover that came over a
control as it was pressed may have taken the press, and pressing again
could do a second thing.

An app that caught Covered itself and pressed again would have no such
rule, and a try written in an app for one cover reads the same as one for
any other. So this reads the Python source of every app, the core, the
panel and the server, apart from their tests, from the syntax tree.

  * No handler outside the core names Covered. The one that did before the
    helper came, American Express's card switcher, presses nothing again,
    leaves the switcher for the card on show, and re-raises a stop that
    came after a press. It is listed by name, and held to that.
  * Every handler in the core that names Covered reads after_a_press.
  * Every handler anywhere that catches Covered or Stop and presses in its
    own body reads after_a_press before that press.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = ("apps", "core", "gui", "server")
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}
CORE = "core/paperpull_core/"

# A press of a control, by the name of what is called.
PRESSES = frozenset(("click", "dblclick", "tap", "check", "uncheck", "set_checked",
                     "press_once", "click_when_clear", "_click", "_press"))

# The handlers outside the core that name Covered, each by its file and the
# function it is in, and why it may.
KNOWN = {
    ("apps/amex/amex_site.py", "list_cards"):
        "leaves the card switcher unpressed and re-raises a stop after a press",
}


def _sources():
    out = []
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            dirs[:] = sorted(d for d in dirs if d != "tests" and d not in MADE_FOLDERS
                             and not d.startswith((".", "__")) and not d.endswith(".egg-info"))
            out.extend(Path(folder) / f for f in files
                       if f.endswith(".py") and not f.startswith("test_") and f != "conftest.py")
    return sorted(out)


def _names(node) -> set:
    """The class names an except clause catches."""
    if node is None:
        return set()
    if isinstance(node, ast.Tuple):
        return set().union(*(_names(e) for e in node.elts))
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    return set()


def _reads(body, before=None) -> bool:
    """Whether the statements read after_a_press, before line `before`
    when given."""
    for stmt in body:
        for node in ast.walk(stmt):
            if (isinstance(node, ast.Attribute) and node.attr == "after_a_press"
                    and isinstance(node.ctx, ast.Load)
                    and (before is None or node.lineno < before)):
                return True
    return False


def _presses(body) -> list:
    """The lines of every press in the statements."""
    found = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in PRESSES:
                    found.append(node.lineno)
    return sorted(found)


def handlers(source: str):
    """Every except clause in `source` as (function, names, handler), the
    function the innermost one it is in, or "" at the top of the module."""
    tree = ast.parse(source)
    out = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                else function
            if isinstance(child, ast.ExceptHandler):
                out.append((function, _names(child.type), child))
            visit(child, inner)
    visit(tree, "")
    return out


def census():
    """(outside, core_unread, pressed_unread, in_core), where outside is
    every handler outside the core naming Covered as (path, function),
    core_unread every handler in the core naming Covered that does not read
    after_a_press, pressed_unread every handler catching Covered or Stop
    that presses before it reads after_a_press, and in_core every handler
    in the core naming Covered as (path, function)."""
    outside, core_unread, pressed_unread, in_core = [], [], [], []
    for path in _sources():
        rel = path.relative_to(REPO).as_posix()
        for function, names, handler in handlers(path.read_text(encoding="utf-8-sig")):
            if "Covered" in names:
                if rel.startswith(CORE):
                    in_core.append((rel, function))
                    if not _reads(handler.body):
                        core_unread.append((rel, function, handler.lineno))
                else:
                    outside.append((rel, function))
            if names & {"Covered", "Stop"}:
                presses = _presses(handler.body)
                if presses and not _reads(handler.body, before=presses[0]):
                    pressed_unread.append((rel, function, handler.lineno))
    return outside, core_unread, pressed_unread, in_core


OUTSIDE, CORE_UNREAD, PRESSED_UNREAD, IN_CORE = census()


def test_no_app_catches_a_cover_but_those_listed():
    assert sorted(set(OUTSIDE)) == sorted(KNOWN), OUTSIDE


def test_the_listed_handler_presses_nothing_again_and_reads_after_a_press():
    for (rel, function), _why in KNOWN.items():
        found = [h for f, names, h in handlers((REPO / rel).read_text(encoding="utf-8-sig"))
                 if f == function and "Covered" in names]
        assert len(found) == 1, (rel, function)
        assert _reads(found[0].body), (rel, function)
        assert not _presses(found[0].body), (rel, function)


def test_every_handler_of_a_cover_in_the_core_reads_after_a_press():
    assert not CORE_UNREAD, CORE_UNREAD
    # Not vacuous. click_when_clear's own handler is one of them.
    assert ("core/paperpull_core/pressing.py", "click_when_clear") in IN_CORE, IN_CORE


def test_no_handler_of_a_stop_presses_before_it_reads_after_a_press():
    assert not PRESSED_UNREAD, PRESSED_UNREAD


def test_the_census_finds_what_it_is_for():
    """The census, on a source made for it. If any of these stops being
    found, the census above passes on nothing."""
    made = '''
def tries_again(page, link):
    try:
        pressing.click(page, link)
    except pressing.Covered:
        pressing.click(page, link)


def reads_first(page, link):
    try:
        pressing.click(page, link)
    except (pressing.Unread, pressing.Stop) as stop:
        if stop.after_a_press:
            raise
        link.click()


def reads_after(page, link):
    try:
        pressing.click(page, link)
    except Stop as stop:
        link.click()
        if stop.after_a_press:
            raise


def leaves_it(page, link):
    try:
        pressing.click(page, link)
    except Covered as stop:
        return stop.reason
'''
    found = [(f, sorted(n & {"Covered", "Stop"}), bool(_presses(h.body)),
              bool(_presses(h.body)) and not _reads(h.body, before=_presses(h.body)[0]))
             for f, n, h in handlers(made)]
    assert found == [
        ("tries_again", ["Covered"], True, True),
        ("reads_first", ["Stop"], True, False),
        ("reads_after", ["Stop"], True, True),
        ("leaves_it", ["Covered"], False, False)]
    assert _reads(handlers(made)[1][2].body) and not _reads(handlers(made)[3][2].body)
