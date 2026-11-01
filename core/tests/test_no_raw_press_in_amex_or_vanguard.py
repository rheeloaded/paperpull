"""Amex and Vanguard press nothing except through paperpull_core.pressing.

A forced press on a tester's American Express statements page opened a
chat, and the presses after it opened a charge dispute with a live agent
(#66). Since then every Amex and Vanguard press goes through
paperpull_core.pressing, which brings the control to the middle of the
window, presses only when it is the thing on top there and its words pass
the guard, presses unforced and reads the page again.
test_no_app_forces_a_press fails on a forced press, a press at a point and
dispatch_event, so a plain el.click() passes it. A pull request for Amex
(#135) added nine of them and an Escape sent to whatever had the focus,
and no census saw any.

So this reads the Python source of both apps, apart from their tests, from
the syntax tree, never by searching the text, and finds every press made
another way. A press is click, dblclick, tap, check, uncheck, set_checked,
press or press_sequentially of anything but a name the file imports,
called or handed on, a getattr of one of those names, any call of a page's
keyboard, and a press of the mouse or the touch screen. A use of a function
or a class of the core that makes such a press is one too. The core is read
the same way and followed through its own calls, apart from pressing
itself, so a press handed to a helper of the core is found
(controls.click_next_page and controls.dismiss_overlays press with
Playwright's own click).

Each press found has to be in ALLOWED with the reason it is safe, and each
entry there still found, so the list says what the code does. A press in
JavaScript is for test_no_app_presses_through_page_script to read.
"""
import ast
import os
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "paperpull_core"

# The apps every press of which goes through paperpull_core.pressing.
APPS = ("amex", "vanguard")

# Playwright's presses of a control, on a Locator, an ElementHandle, a Page
# or a Frame, a key sent to an element among them.
PRESSES = frozenset(("click", "dblclick", "tap", "check", "uncheck", "set_checked", "press",
                     "press_sequentially"))

# A page's devices, each to its calls that press, None for every call. A
# key goes to whatever has the focus.
DEVICES = {"keyboard": None, "mouse": frozenset(("click", "dblclick", "down", "up")),
           "touchscreen": frozenset(("tap",))}

# The one module of the core a press may go through.
PRESSING = "paperpull_core.pressing"

# Folders a build or an install makes, copies of what ships and never what
# a run reads from this tree.
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}

# Every press found that does not go through pressing, by the file, the
# function it is in and the call as written, with the reason it is safe.
# Each is made once in its function, and a second press like it is a new
# one to read.
ALLOWED = {
    ("apps/amex/amex_site.py", "close_file_type_dialog", "own.press('Escape', timeout=3000)"):
        "Escape for the file type dialog when it shows neither a Cancel nor a Close. A key "
        "goes to the element that has the focus, and this is sent only once one of the "
        "dialog's own controls holds it, so it reaches that dialog and nothing else on the "
        "page. Escape activates no control, it asks the dialog to close.",
    ("apps/amex/amex_site.py", "scroll_full_page", "page.keyboard.press('End')"):
        "End once the wheel has scrolled, so a list that loads as it scrolls shows its last "
        "rows. Only Diagnose calls scroll_full_page. A key goes to whatever has the focus, "
        "and End activates no button or link. In a text field it moves the caret, and in a "
        "select it would move the choice, but no Amex code puts the focus in a select.",
    ("apps/amex/amex_site.py", "next_page", "_click_next_page(page, FALLBACK['next_page'])"):
        "controls.click_next_page presses unforced with Playwright's own click, past "
        "pressing. Nothing calls next_page, as the module's header says and "
        "test_nothing_calls_amex_next_page holds, so the press is never made. A caller "
        "would have to press through pressing instead.",
}


def is_test(name: str) -> bool:
    return name.startswith("test_") or name == "conftest.py"


def sources(top: Path) -> list:
    """Every Python file under `top` but a test and a copy a build made."""
    out = []
    for folder, dirs, files in os.walk(top):
        # Pruned as the walk goes, so a test folder, an environment and a
        # copy a build made are never entered.
        dirs[:] = sorted(d for d in dirs if d != "tests" and d not in MADE_FOLDERS
                         and not d.startswith((".", "__")) and not d.endswith(".egg-info"))
        out.extend(Path(folder) / f for f in files if f.endswith(".py") and not is_test(f))
    return sorted(out)


def core_sources() -> dict:
    """The core's modules, by their names, to their source."""
    out = {}
    for path in sorted(CORE.glob("*.py")):
        name = "paperpull_core" if path.stem == "__init__" else "paperpull_core." + path.stem
        out[name] = path.read_text(encoding="utf-8-sig")
    return out


def _imports(tree, module: str, modules) -> dict:
    """Each name the file binds by an import, anywhere in it, to (m, None)
    for module m and (m, name) for a name taken from m. `module` is the
    file's own name, for an import relative to it, and `modules` the core's
    names, to tell a module of the core from a name in one."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = (a.name, None)
                else:
                    root = a.name.split(".")[0]
                    out[root] = (root, None)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = module.split(".")
                if module != "paperpull_core":
                    package = package[:-1]
                package = package[:len(package) - (node.level - 1)]
                base = ".".join(package + ([base] if base else []))
            for a in node.names:
                whole = "%s.%s" % (base, a.name)
                out[a.asname or a.name] = (whole, None) if whole in modules else (base, a.name)
    return out


def _root(node):
    """The name an attribute chain starts from, None when it starts from a
    call, a subscript or anything else."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _of_a_module(node, imports) -> bool:
    """Whether `node` starts from a name the file imports, a module or what
    one holds, never a Playwright object, which a run is handed and never
    imports. Its own presses are read where it is written. A name taken
    from Playwright itself does not count."""
    bound = imports.get(_root(node))
    return bound is not None and not bound[0].startswith("playwright")


def _device_names(tree) -> dict:
    """Names the file binds to a page's device, `kb = page.keyboard`, so a
    press through the name is found too."""
    out = {}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Attribute)
                and node.value.attr in DEVICES):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out.update((t.id, node.value.attr) for t in targets if isinstance(t, ast.Name))
    return out


def _device(node, names) -> str:
    """"keyboard", "mouse" or "touchscreen" when `node` is one, else ""."""
    if isinstance(node, ast.Attribute) and node.attr in DEVICES:
        return node.attr
    if isinstance(node, ast.Name):
        return node.id if node.id in DEVICES else names.get(node.id, "")
    return ""


def _press_of(receiver, name, imports, devices) -> bool:
    """Whether `name` of `receiver` presses past pressing."""
    device = _device(receiver, devices)
    if device:
        return DEVICES[device] is None or name in DEVICES[device]
    return name in PRESSES and not _of_a_module(receiver, imports)


def _module_named(node, imports, modules) -> str:
    """The core module `node` names, or ""."""
    if isinstance(node, ast.Name):
        bound = imports.get(node.id)
        return bound[0] if bound and bound[1] is None and bound[0] in modules else ""
    if isinstance(node, ast.Attribute):
        outer = _module_named(node.value, imports, modules)
        whole = "%s.%s" % (outer, node.attr)
        return whole if outer and whole in modules else ""
    return ""


def _core_part(node, imports, modules, own=None) -> tuple:
    """(m, name) when `node` names a function or a class of core module m,
    else (). `own` holds a module of the core's own, for a name it uses
    without an import."""
    if isinstance(node, ast.Name):
        bound = imports.get(node.id)
        if bound:
            return bound if bound[1] is not None and bound[0] in modules else ()
        return (own or {}).get(node.id, ())
    if isinstance(node, ast.Attribute):
        module = _module_named(node.value, imports, modules)
        if module and "%s.%s" % (module, node.attr) not in modules:
            return (module, node.attr)
    return ()


def _short(part) -> str:
    module, name = part
    return "%s.%s" % (module.split(".")[-1], name)


def _presses_in(tree, imports, devices, modules, core, own=None) -> list:
    """(node, call, how) for each press inside `tree` that does not go
    through pressing, `call` as written. `core` holds the core's functions
    and classes that press past pressing, to how."""
    parents = {child: parent for parent in ast.walk(tree)
               for child in ast.iter_child_nodes(parent)}

    def called(node):
        up = parents.get(node)
        return up if isinstance(up, ast.Call) and up.func is node else node

    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            if _press_of(node.value, node.attr, imports, devices):
                out.append((node, ast.unparse(called(node)), "Playwright's %s" % node.attr))
                continue
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
                and _press_of(node.args[0], node.args[1].value, imports, devices)):
            out.append((node, ast.unparse(node), "Playwright's %s" % node.args[1].value))
            continue
        if core and isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            part = _core_part(node, imports, modules, own)
            if part in core:
                out.append((node, ast.unparse(called(node)),
                            "%s, which presses %s" % (_short(part), core[part])))
    return sorted(out, key=lambda found: (found[0].lineno, found[0].col_offset))


def core_presses(modules: dict) -> dict:
    """Each function and class of the core, outside pressing, that presses
    past pressing, itself or through another of the core's, as (m, name) to
    how. `modules` holds the core's sources by name."""
    names = frozenset(modules)
    direct, uses = {}, {}
    for module, source in sorted(modules.items()):
        if module == PRESSING:
            continue
        tree = ast.parse(source)
        imports = _imports(tree, module, names)
        devices = _device_names(tree)
        defs = [n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        own = {n.name: (module, n.name) for n in defs}
        for node in defs:
            key = (module, node.name)
            found = _presses_in(node, imports, devices, names, {}, own)
            if found:
                direct[key] = "with %s" % found[0][1]
            uses[key] = sorted({part for n in ast.walk(node)
                                if isinstance(n, (ast.Name, ast.Attribute))
                                and isinstance(n.ctx, ast.Load)
                                for part in [_core_part(n, imports, names, own)]
                                if part and part != key and part[0] != PRESSING})
    out = dict(direct)
    grew = True
    while grew:
        grew = False
        for key, used in sorted(uses.items()):
            hit = next((u for u in used if u in out), None) if key not in out else None
            if hit:
                out[key] = "through %s" % _short(hit)
                grew = True
    return out


CORE_SOURCES = core_sources()
CORE_MODULES = frozenset(CORE_SOURCES)
CORE_PRESSES = core_presses(CORE_SOURCES)


def _scopes(tree) -> dict:
    """Each node to the function or class it is written in, by its dotted
    name, "<module>" outside them all."""
    out = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            out[child] = name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, child.name if name == "<module>" else "%s.%s" % (name, child.name))
            else:
                visit(child, name)

    visit(tree, "<module>")
    return out


def raw_presses(source: str, modules=CORE_MODULES, core=None) -> list:
    """Every press in `source`, a file of an app, that does not go through
    pressing, as (line, function, call, how) in the order of the file."""
    tree = ast.parse(source)
    scopes = _scopes(tree)
    found = _presses_in(tree, _imports(tree, "", modules), _device_names(tree), modules,
                        CORE_PRESSES if core is None else core)
    return [(node.lineno, scopes[node], call, how) for node, call, how in found]


SOURCES = [p for app in APPS for p in sources(REPO / "apps" / app)]


def _name(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def test_the_census_reads_both_apps_and_follows_the_core():
    """Not vacuous. Each app's site and docs module is read, no test, and
    the core's own presses past pressing are known, none of pressing's."""
    names = {_name(p) for p in SOURCES}
    assert {"apps/amex/amex_site.py", "apps/amex/amex_docs.py", "apps/vanguard/vanguard_site.py",
            "apps/vanguard/vanguard_docs.py"} <= names
    assert not [n for n in names if "/tests/" in n or n.split("/")[-1].startswith("test_")]
    assert {PRESSING, "paperpull_core.controls"} <= CORE_MODULES
    assert ("paperpull_core.controls", "click_next_page") in CORE_PRESSES
    assert ("paperpull_core.controls", "dismiss_overlays") in CORE_PRESSES
    assert not [k for k in CORE_PRESSES if k[0] == PRESSING]


def not_allowed(name: str, source: str) -> list:
    """Each press of file `name` that ALLOWED does not name, or names and
    the function makes twice, as a line of the failure."""
    found = raw_presses(source)
    made = Counter((scope, call) for _line, scope, call, _how in found)
    return ["line %d in %s, %s (%s)" % (line, scope, call, how)
            for line, scope, call, how in found
            if (name, scope, call) not in ALLOWED or made[(scope, call)] > 1]


@pytest.mark.parametrize("path", SOURCES, ids=_name)
def test_every_press_goes_through_pressing(path):
    name = _name(path)
    wrong = not_allowed(name, path.read_text(encoding="utf-8-sig"))
    assert not wrong, "%s presses past paperpull_core.pressing at\n  %s\nPress through " \
        "pressing.click or pressing.check instead, or add the press to ALLOWED with the " \
        "reason it is safe." % (name, "\n  ".join(wrong))


def test_an_allowed_press_is_allowed_once_in_its_own_function():
    """The press ALLOWED names passes where it is, and the same call made
    twice there, or in another function or file, does not."""
    once = '''
def scroll_full_page(page):
    page.keyboard.press('End')
'''
    twice = once + "    page.keyboard.press('End')\n"
    elsewhere = once.replace("scroll_full_page", "scroll_the_list")
    assert not_allowed("apps/amex/amex_site.py", once) == []
    assert len(not_allowed("apps/amex/amex_site.py", twice)) == 2
    assert len(not_allowed("apps/amex/amex_site.py", elsewhere)) == 1
    assert len(not_allowed("apps/amex/amex_docs.py", once)) == 1


def test_every_allowed_press_is_still_made():
    found = {(_name(p), scope, call)
             for p in SOURCES
             for _line, scope, call, _how in raw_presses(p.read_text(encoding="utf-8-sig"))}
    gone = sorted(k for k in ALLOWED if k not in found)
    assert not gone, "ALLOWED names a press nothing makes any more, %s" % gone


def test_nothing_calls_amex_next_page():
    """ALLOWED lets Amex's next_page press through controls.click_next_page
    because nothing calls it. Nothing in Amex or the core names it."""
    amex = [p for p in SOURCES if _name(p).startswith("apps/amex/")]
    assert len(amex) >= 3, amex
    callers = []
    for path in amex + sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Name) and node.id == "next_page"
                     or isinstance(node, ast.Attribute) and node.attr == "next_page"
                     or isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "getattr" and len(node.args) > 1
                     and isinstance(node.args[1], ast.Constant)
                     and node.args[1].value == "next_page")
            if named:
                callers.append("%s:%d" % (_name(path), node.lineno))
    assert not callers, "Amex's next_page is called at %s, and its press must go " \
        "through pressing now" % callers


def test_the_census_finds_every_kind_of_press_it_is_for():
    """The census, on a source made for it. If one of these stops being
    found, the census above passes on nothing."""
    made = '''
from paperpull_core import controls
from paperpull_core.controls import dismiss_overlays as _put_away
import paperpull_core.controls
from playwright.sync_api import Locator


def presses(page, el, handle, frame, rows, retry):
    el.click()
    handle.dblclick(timeout=3000)
    el.tap()
    el.check()
    el.uncheck()
    el.set_checked(True)
    el.press("Enter")
    el.press_sequentially("x")
    page.locator("a").first.click()
    frame.click("#x")
    rows.nth(0).check()
    page.keyboard.press("Escape")
    page.keyboard.down("Enter")
    page.keyboard.type("hello")
    kb = page.keyboard
    kb.insert_text("x")
    page.mouse.click(1, 2)
    page.mouse.down()
    page.touchscreen.tap(1, 2)
    retry(el.click)
    getattr(el, "click")()
    getattr(page.keyboard, "press")("Enter")
    Locator.click(el)
    controls.click_next_page(page, "a")
    _put_away(page)
    paperpull_core.controls.dismiss_overlays(page)


class Pages:
    def forward(self, el):
        el.click()
'''
    found = [(scope, call) for _line, scope, call, _how in raw_presses(made)]
    assert found == [
        ("presses", "el.click()"), ("presses", "handle.dblclick(timeout=3000)"),
        ("presses", "el.tap()"), ("presses", "el.check()"), ("presses", "el.uncheck()"),
        ("presses", "el.set_checked(True)"), ("presses", "el.press('Enter')"),
        ("presses", "el.press_sequentially('x')"), ("presses", "page.locator('a').first.click()"),
        ("presses", "frame.click('#x')"), ("presses", "rows.nth(0).check()"),
        ("presses", "page.keyboard.press('Escape')"), ("presses", "page.keyboard.down('Enter')"),
        ("presses", "page.keyboard.type('hello')"), ("presses", "kb.insert_text('x')"),
        ("presses", "page.mouse.click(1, 2)"), ("presses", "page.mouse.down()"),
        ("presses", "page.touchscreen.tap(1, 2)"), ("presses", "el.click"),
        ("presses", "getattr(el, 'click')"), ("presses", "getattr(page.keyboard, 'press')"),
        ("presses", "Locator.click(el)"),
        ("presses", "controls.click_next_page(page, 'a')"), ("presses", "_put_away(page)"),
        ("presses", "paperpull_core.controls.dismiss_overlays(page)"),
        ("Pages.forward", "el.click()")]


def test_a_press_through_pressing_is_left_alone():
    """A press through pressing however it is imported, a function of the
    app's own module or of a module of the core that presses nothing, and
    what moves, scrolls, focuses, fills or picks without a press."""
    alone = '''
from paperpull_core import pressing, failure, naming
from paperpull_core.controls import control_labels
from paperpull_core.pressing import click as press_it
import paperpull_core.pressing
import amex_site as site


def fine(page, el, loc):
    pressing.click(page, el, css=pressing.BUTTONS, what="the Download", words=[])
    pressing.check(page, el, css="input", what="the PDF", words=[])
    pressing.press_once(page, el, what="the Download", words=[], guard=None)
    paperpull_core.pressing.click(page, el, css="a", what="a", words=[])
    press_it(page, el, css="a", what="a", words=[])
    site.click(page)
    naming.check("{date}")
    failure.check
    control_labels(el)
    page.mouse.wheel(0, 3000)
    page.mouse.move(1, 2)
    el.focus(timeout=3000)
    el.hover()
    el.fill("x")
    loc.select_option(label="2025")
    el.is_checked()
    getattr(el, "inner_text")()
'''
    assert raw_presses(alone) == []


def test_the_core_is_followed_through_its_own_calls():
    """A press of the core is found through a module, a relative import, a
    name taken under another name and a class, and pressing's own and a
    function that presses through pressing are not."""
    core = core_presses({
        "paperpull_core": "",
        PRESSING: "def click(page, el):\n    el.click()\n",
        "paperpull_core.helpers": "def put_away(page):\n    page.keyboard.press('Escape')\n\n"
                                  "def url(page):\n    return page.url\n",
        "paperpull_core.middle": "from . import helpers\n\ndef tidy(page):\n"
                                 "    helpers.put_away(page)\n\ndef own(page):\n    tidy(page)\n",
        "paperpull_core.top": "from .middle import own as _own\nfrom paperpull_core import pressing\n\n"
                              "class Pager:\n    def forward(self, page):\n        _own(page)\n\n"
                              "def safe(page, el):\n    pressing.click(page, el)\n",
    })
    assert core == {
        ("paperpull_core.helpers", "put_away"): "with page.keyboard.press('Escape')",
        ("paperpull_core.middle", "tidy"): "through helpers.put_away",
        ("paperpull_core.middle", "own"): "through middle.tidy",
        ("paperpull_core.top", "Pager"): "through middle.own"}
    app = '''
from paperpull_core import top
from paperpull_core.helpers import url


def run(page, el):
    top.safe(page, el)
    url(page)
    top.Pager().forward(page)
'''
    modules = {"paperpull_core", PRESSING, "paperpull_core.helpers", "paperpull_core.middle",
               "paperpull_core.top"}
    assert [(call, how) for _line, _scope, call, how in raw_presses(app, modules, core)] == [
        ("top.Pager()", "top.Pager, which presses through middle.own")]
