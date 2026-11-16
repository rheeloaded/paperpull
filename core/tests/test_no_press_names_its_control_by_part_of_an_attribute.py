"""No press names its control by the start, the end or a part of an
attribute (#226).

paperpull_core.pressing finds the control a press is for by the selector
the app hands it and the box Playwright gives, and presses only when
exactly one element the selector matches is drawn in that box. A selector
that matches the start of an attribute, [data-testid^='...'], also
matches each wrapper around the control and each part inside it whose
attribute starts the same way, and a wrapper is often drawn the very size
of what it holds. On a tester's Best Buy history five elements carried a
test id starting with the range menu's, three of them drawn in one box, so
the check counted three, pressed nothing, and every run stopped at "choose
a year". The end of an attribute ($=), a part of one (*=) and a word
before a hyphen (|=) widen a selector the same way.

So this reads the Python source of every app, the core, the panel and the
server, apart from their tests, from the syntax tree. A press is a call of
a function of pressing that takes a css, or of a function of the same
module that hands its own css on to one, Best Buy's _press say. The css a
press is given is read through the names the module and the function bind,
pressing's own constants, string formatting and joining, either branch of
an if, and what a function of the module returns, and every piece of text
that can make it up is looked at. A piece that only the page decides, a tag
or a test id read from the element, is not text in the source, and it is
the element's own whole value rather than a part.

A press found here is either changed or listed in EXCEPTIONS with the
reason it stays, and each entry there has to be found still.
"""
import ast
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRESSING = REPO / "core" / "paperpull_core" / "pressing.py"

# What ships, apps and the core and what the panel and the server run.
ROOTS = ("apps", "core", "gui", "server")

# Folders a build or an install makes, copies of what ships.
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}

# An attribute matched by its start, its end, a part of it or the word
# before a hyphen.
PART_OF_AN_ATTRIBUTE = re.compile(r"[\^$*|]=")

# Presses that name their control by part of an attribute and were there
# before this census, by file, function and the css as written, each with
# why it stays.
EXCEPTIONS = {
    ("apps/amex/amex_site.py", "goto_documents", "opt_css"):
        "The card option is named by its own whole test id. The prefix it was "
        "found by is handed on only for an option that carries no test id, which "
        "that prefix does not find.",
    ("apps/amex/amex_site.py", "select_card", "opt_css"):
        "The same card option, named the same way.",
    ("apps/amex/amex_site.py", "download_document", "sel"):
        "A row's Download button by the end of its test id, which holds the "
        "statement's own date or year.",
    ("apps/amex/amex_site.py", "download_document",
     "'%s, %s' % (_DIALOG_CONFIRM_SEL, pressing.BUTTONS)"):
        "The download dialog's confirm by the whole end of its test id or of "
        "its id.",
    ("apps/venmo/venmo_site.py", "show_all", "SHOW_MORE_CSS"):
        "The part match names the list around the control, never the control, "
        "which is a button or an element with the role button.",
}


def is_test(name: str) -> bool:
    return name.startswith("test_") or name == "conftest.py"


def sources() -> list:
    out = []
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            # Pruned as the walk goes, so a test folder, an environment and
            # a copy a build made are never entered.
            dirs[:] = sorted(d for d in dirs if d != "tests" and d not in MADE_FOLDERS
                             and not d.startswith((".", "__")) and not d.endswith(".egg-info"))
            out.extend(Path(folder) / f for f in files if f.endswith(".py") and not is_test(f))
    return sorted(out)


def _parameters(fn) -> tuple:
    a = fn.args
    return [p.arg for p in a.posonlyargs + a.args], [p.arg for p in a.kwonlyargs]


def _bindings(nodes) -> dict:
    """Each name an assignment among `nodes` binds, to every value it is
    given."""
    out = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            out.setdefault(node.target.id, []).append(node.value)
    return out


class Module:
    def __init__(self, tree):
        self.tree = tree
        self.names = _bindings(tree.body)
        self.functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


_PRESSING = Module(ast.parse(PRESSING.read_text(encoding="utf-8-sig")))

# Each function of pressing that takes a css, to the place of the css among
# its plain arguments, None when it is given by name only.
TAKES_A_CSS = {}
for _name, _fn in _PRESSING.functions.items():
    _plain, _named = _parameters(_fn)
    if "css" in _plain:
        TAKES_A_CSS[_name] = _plain.index("css")
    elif "css" in _named:
        TAKES_A_CSS[_name] = None


def pieces(node, module: Module, local: dict, seen=()) -> list:
    """Every piece of text in the source that can make up `node`'s value."""
    if node is None:
        return []
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.Name):
        if node.id in seen:
            return []
        values = local.get(node.id) or module.names.get(node.id) or []
        return [s for v in values for s in pieces(v, module, local, seen + (node.id,))]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "pressing":
        return [s for v in _PRESSING.names.get(node.attr, [])
                for s in pieces(v, _PRESSING, {}, seen)]
    if isinstance(node, ast.Call):
        own = module.functions.get(node.func.id) if isinstance(node.func, ast.Name) else None
        joins = isinstance(node.func, ast.Attribute) and node.func.attr in ("join", "format")
        if own is None and not joins:
            return []
        out = [s for a in node.args for s in pieces(a, module, local, seen)]
        out += [s for k in node.keywords for s in pieces(k.value, module, local, seen)]
        if joins:
            out += pieces(node.func.value, module, local, seen)
        if own is not None and own.name not in seen:
            inner = _bindings(ast.walk(own))
            for r in ast.walk(own):
                if isinstance(r, ast.Return):
                    out += pieces(r.value, module, inner, seen + (own.name,))
        return out
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.IfExp, ast.JoinedStr, ast.FormattedValue,
                         ast.Tuple, ast.List, ast.GeneratorExp, ast.ListComp, ast.Subscript)):
        return [s for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)
                for s in pieces(child, module, local, seen)]
    return []


def _css_place(call, in_pressing: bool, wrappers: dict):
    """Where `call` takes a css, as TAKES_A_CSS says, or False when it is
    not a press."""
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
            and f.value.id == "pressing" and f.attr in TAKES_A_CSS:
        return TAKES_A_CSS[f.attr]
    if isinstance(f, ast.Name):
        if in_pressing and f.id in TAKES_A_CSS:
            return TAKES_A_CSS[f.id]
        if f.id in wrappers:
            return wrappers[f.id]
    return False


def _css_of(call, place):
    for k in call.keywords:
        if k.arg == "css":
            return k.value
    if place is not None and place < len(call.args):
        return call.args[place]
    return None


def presses(source: str, in_pressing: bool = False) -> tuple:
    """Every press in `source` with the css it is given, as (line,
    function, css as written, the pieces of text that can make it up), and
    the module's own functions that hand their css on to a press."""
    tree = ast.parse(source)
    module = Module(tree)
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    wrappers = {}
    grew = True
    while grew:
        grew = False
        for fn in functions:
            if fn.name in wrappers:
                continue
            plain, named = _parameters(fn)
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                place = _css_place(call, in_pressing, wrappers)
                css = _css_of(call, place) if place is not False else None
                if isinstance(css, ast.Name) and css.id in plain + named:
                    wrappers[fn.name] = plain.index(css.id) if css.id in plain else None
                    grew = True
                    break
    out = []
    for fn in functions:
        local = _bindings(ast.walk(fn))
        plain, named = _parameters(fn)
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            place = _css_place(call, in_pressing, wrappers)
            css = _css_of(call, place) if place is not False else None
            if css is None:
                continue
            if fn.name in wrappers and isinstance(css, ast.Name) and css.id in plain + named:
                continue  # handed on, and read where the wrapper is called
            out.append((call.lineno, fn.name, ast.unparse(css), pieces(css, module, local)))
    return sorted(out), wrappers


def by_part_of_an_attribute(found) -> list:
    return [(line, fn, css) for line, fn, css, texts in found
            if any(PART_OF_AN_ATTRIBUTE.search(t) for t in texts)]


SOURCES = sources()


def _census() -> dict:
    out = {}
    for path in SOURCES:
        found, _ = presses(path.read_text(encoding="utf-8-sig"),
                           in_pressing=path.resolve() == PRESSING.resolve())
        out[path.relative_to(REPO).as_posix()] = found
    return out


CENSUS = _census()


def test_no_press_names_its_control_by_part_of_an_attribute():
    found = [(rel, line, fn, css) for rel, presses_found in CENSUS.items()
             for line, fn, css in by_part_of_an_attribute(presses_found)
             if (rel, fn, css) not in EXCEPTIONS]
    assert not found, (
        "These presses name their control by the start, the end or a part of an "
        "attribute, which also matches a wrapper or a part drawn in the control's "
        "box, so pressing reads several and presses nothing. Name the control by "
        "its tag, its role or its whole attribute. Found %s" % found)


def test_every_exception_is_still_found():
    found = {(rel, fn, css) for rel, presses_found in CENSUS.items()
             for _line, fn, css in by_part_of_an_attribute(presses_found)}
    stale = sorted(set(EXCEPTIONS) - found)
    assert not stale, "These are no longer found, so they are no exceptions now. %s" % stale


def test_the_census_reads_the_presses_of_every_app_and_the_core():
    """Not vacuous. The presses of the apps and of pressing itself are read,
    through the apps' own wrappers, and most of their css is read whole."""
    read = [p for found in CENSUS.values() for p in found]
    assert len(read) >= 50
    assert sum(1 for p in read if p[3]) >= 40
    assert {"click", "check", "look"} <= set(TAKES_A_CSS)
    bestbuy = CENSUS["apps/bestbuy/bestbuy_site.py"]
    assert [fn for _line, fn, _css, _texts in bestbuy] == ["year_choices", "pick_year",
                                                          "pick_year"]
    assert any(texts == ["label"] for _line, _fn, _css, texts in CENSUS[
        "core/paperpull_core/pressing.py"])
    for rel in ("apps/alpaca/alpaca_site.py", "apps/chasebusiness/chasebusiness_site.py",
                "apps/firsthorizon/firsthorizon_site.py", "apps/wellsfargo/wellsfargo_site.py"):
        assert CENSUS[rel], rel


def _found_in(source: str) -> list:
    found, _ = presses(source)
    return [css for _line, _fn, css in by_part_of_an_attribute(found)]


def test_a_part_match_is_found_however_the_css_is_written():
    """Best Buy's range menu as it was, and the ways a css reaches a press,
    in a module made up here."""
    source = '''
from paperpull_core import pressing
MENU = "[data-testid^='Range']"
LIST = "[class*='list']"
EXACT = "[data-testid='Range']"

def _by(op, value):
    return "[data-testid%s'%s']" % (op, value)

def _press(page, el, what, css, guard):
    pressing.click(page, el, css=css, what=what, words=None)

def _press_by_name(page, el, *, css):
    _press(page, el, "x", css, None)

def presses(page, el, tag):
    _press(page, el, "the menu", MENU, None)
    _press_by_name(page, el, css="%s, %s" % (LIST, pressing.BUTTONS))
    pressing.click(page, el, css=f"{tag}[id$='-end']", what="x", words=None)
    pressing.check(page, el, css=_by("^=", "Range"), what="x", words=None)
    pressing.look(page, el, "[title|='en']")
    pressing.click(page, el, css=EXACT, what="x", words=None)
    pressing.click(page, el, css=_by("=", "Range"), what="x", words=None)
    pressing.click(page, el, css=tag, what="x", words=None)
'''
    assert _found_in(source) == [
        "MENU", "'%s, %s' % (LIST, pressing.BUTTONS)", "f\"{tag}[id$='-end']\"",
        "_by('^=', 'Range')", '"[title|=\'en\']"']
