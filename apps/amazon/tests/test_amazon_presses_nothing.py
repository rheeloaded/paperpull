"""The Amazon app presses nothing, in every store (#207).

A tester saw an address card open on amazon.de and took it that the app had
pressed the ship-to name rather than the invoice menu. It had not. Amazon's
ship-to name and its invoice menu (Rechnung) are popover triggers of the
same shape, and the app reads neither by pressing. The invoice comes from a
plain GET of /your-orders/invoice/popover?orderId=<id> and the PDF link in
it, and an order on a list drawn without cards is found from the invoice
menu's data, read as an attribute. So the guard here is the narrowest one,
an allowlist that is empty.

This reads the Python source of the app, apart from its tests, from the
syntax tree, and finds every press. A press is any of Playwright's calls
that press, hover, focus or type (PRESSES) on anything but a name the file
imports, a getattr of one of them, any use of a page's keyboard or
touchscreen, a press or a move of its mouse (its wheel only scrolls), any
use of paperpull_core.pressing, any of paperpull_core.controls but its
patterns, and a page script or a DevTools command that presses (SCRIPTED).
Each press found has to be in ALLOWED with the reason it is safe, and
ALLOWED is empty. A press added to the app fails here until someone writes
down why it cannot reach the wrong control.
"""
import ast
import os
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]

PRESSES = frozenset((
    "click", "dblclick", "tap", "check", "uncheck", "set_checked", "press", "press_sequentially",
    "hover", "dispatch_event", "focus", "select_option", "fill", "type", "set_input_files",
    "drag_to", "drag_and_drop", "insert_text", "select_text"))

# A page's devices, each to its calls that press, None for every call.
DEVICES = {"keyboard": None, "touchscreen": None,
           "mouse": frozenset(("click", "dblclick", "down", "up", "move"))}

# The core modules whose use is a press, and for controls the names that
# are only patterns (all capitals), which press nothing.
PRESSING_MODULES = ("paperpull_core.pressing", "paperpull_core.controls")

# A page script or a DevTools command that presses, types or focuses.
SCRIPTED = re.compile(
    r"\.click\s*\(|dispatchEvent|\.submit\s*\(|requestSubmit|\.focus\s*\(|"
    r"\.onmouse\w*\s*\(|\.onclick\s*\(|trigger\s*\(\s*['\"]click|"
    r"new\s+(?:Mouse|Pointer|Keyboard|Touch|Focus)Event|"
    r"Input\.(?:dispatch\w+|insertText|emulateTouch\w*)", re.I)

# (file, function, call as written) to the reason the press is safe. Empty,
# and kept so on purpose.
ALLOWED: dict = {}

MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}


def sources() -> list:
    out = []
    for folder, dirs, files in os.walk(APP):
        dirs[:] = sorted(d for d in dirs if d != "tests" and d not in MADE_FOLDERS
                         and not d.startswith((".", "__")))
        out.extend(Path(folder) / f for f in files
                   if f.endswith(".py") and not f.startswith("test_") and f != "conftest.py")
    return sorted(out)


def _imports(tree) -> dict:
    """Each name the file binds by an import to the module it comes from."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                out[a.asname or a.name] = "%s.%s" % (node.module or "", a.name)
    return out


def _root(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _scopes(tree) -> dict:
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


def _docstrings(tree) -> set:
    out = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    out.add(stmt.value)
    return out


def _pressing_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in PRESSING_MODULES)


def _joined(node):
    """The string a sum of string constants makes, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _joined(node.left), _joined(node.right)
        return left + right if left is not None and right is not None else None
    return None


def presses(source: str) -> list:
    """Every press in `source`, as (line, function, call, how)."""
    tree = ast.parse(source)
    scopes, imports, docs = _scopes(tree), _imports(tree), _docstrings(tree)
    devices = {}
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Attribute)
                and node.value.attr in DEVICES):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            devices.update((t.id, node.value.attr) for t in targets if isinstance(t, ast.Name))
    found = []

    def add(node, how):
        found.append((node.lineno, scopes.get(node, "<module>"), ast.unparse(node), how))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if _pressing_module(a.name):
                    add(node, "imports %s" % a.name)
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                whole = "%s.%s" % (node.module or "", a.name)
                pattern_only = node.module == "paperpull_core.controls" and a.name.isupper()
                if _pressing_module(whole) and not pattern_only:
                    add(node, "imports %s" % whole)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            receiver = node.value
            device = (receiver.attr if isinstance(receiver, ast.Attribute) and receiver.attr in DEVICES
                      else devices.get(receiver.id, "") if isinstance(receiver, ast.Name) else "")
            if isinstance(receiver, ast.Name) and receiver.id in DEVICES:
                device = receiver.id
            if device:
                if DEVICES[device] is None or node.attr in DEVICES[device]:
                    add(node, "the page's %s" % device)
                continue
            bound = imports.get(_root(receiver))
            if node.attr in PRESSES and (bound is None or bound.startswith("playwright")):
                add(node, "Playwright's %s" % node.attr)
            elif bound and _pressing_module(_dotted(receiver).replace(_root(receiver), bound, 1)) \
                    and not node.attr.isupper() and not bound.rsplit(".", 1)[-1].isupper():
                add(node, "the core's %s" % node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) > 1
              and isinstance(node.args[1], ast.Constant) and node.args[1].value in PRESSES):
            add(node, "Playwright's %s" % node.args[1].value)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and node not in docs and SCRIPTED.search(node.value)):
            add(node, "a script that presses")
        elif isinstance(node, ast.BinOp):
            joined = _joined(node)
            if joined is not None and SCRIPTED.search(joined) and not any(
                    SCRIPTED.search(c.value) for c in ast.walk(node)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)):
                add(node, "a script, joined from pieces, that presses")
    return sorted(found)


SOURCES = sources()


def _name(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def test_the_census_reads_the_whole_app_and_no_test():
    names = {_name(p) for p in SOURCES}
    assert {"apps/amazon/amazon_site.py", "apps/amazon/amazon_receipts.py",
            "apps/amazon/storage.py"} <= names
    assert not [n for n in names if "/tests/" in n or n.split("/")[-1].startswith("test_")]


@pytest.mark.parametrize("path", SOURCES, ids=_name)
def test_amazon_presses_nothing(path):
    name = _name(path)
    wrong = ["line %d in %s, %s (%s)" % found for found in presses(path.read_text(encoding="utf-8-sig"))
             if (name, found[1], found[2]) not in ALLOWED]
    assert not wrong, "%s presses at\n  %s\nThe Amazon app reads its invoices by GET and " \
        "presses nothing. A press needs an entry in ALLOWED with the reason it cannot reach " \
        "the wrong control." % (name, "\n  ".join(wrong))


def test_every_allowed_press_is_still_made():
    made = {(_name(p), f[1], f[2]) for p in SOURCES for f in presses(p.read_text(encoding="utf-8-sig"))}
    assert not [k for k in ALLOWED if k not in made]


CAUGHT = [
    "el.click()", "el.dblclick()", "el.tap()", "el.check()", "el.uncheck()", "el.set_checked(True)",
    "el.press('Enter')", "el.press_sequentially('x')", "el.hover()", "el.dispatch_event('click')",
    "el.focus()", "el.select_option('2025')", "el.fill('x')", "el.type('x')",
    "el.set_input_files('f')", "el.drag_to(other)",
    "page.locator('a').first.click()", "frame.hover('#x')",
    "page.get_by_role('link').nth(1).focus()",
    "page.keyboard.press('Escape')", "page.keyboard.insert_text('x')",
    "kb = page.keyboard\n    kb.type('x')",
    "page.mouse.click(1, 2)", "page.mouse.down()", "page.mouse.up()", "page.mouse.move(1, 2)",
    "m = page.mouse\n    m.move(1, 2)", "page.touchscreen.tap(1, 2)",
    "retry(el.hover)", "getattr(el, 'click')()",
    "page.evaluate(\"e => document.querySelector('a').click()\")",
    "el.evaluate(\"e => e.dispatchEvent(new MouseEvent('click', {bubbles: true}))\")",
    "page.evaluate('document.forms[0].submit()')",
    "page.eval_on_selector('a', 'e => e.click()')",
    "JS = 'e => e.' + 'click()'",
    "cdp.send('Input.dispatchMouseEvent', {})", "cdp.send('Input.insertText', {})",
    "page.evaluate('e => e.onmouseover()')",
]


@pytest.mark.parametrize("call", CAUGHT)
def test_the_census_finds_each_kind_of_press(call):
    source = "def reach(page, el, frame, other, cdp, retry):\n    %s\n" % call
    found = presses(source)
    assert found and all(f[1] == "reach" for f in found), (call, found)


@pytest.mark.parametrize("source", [
    "from paperpull_core import pressing\ndef go(page):\n    pressing.click(page, 'a')\n",
    "from paperpull_core.pressing import click as go\n",
    "import paperpull_core.pressing\n",
    "from paperpull_core import controls\ndef go(page):\n    controls.click_next_page(page, 'a')\n",
    "from paperpull_core.controls import dismiss_overlays as tidy\n",
    "from playwright.sync_api import Locator\ndef go(el):\n    Locator.click(el)\n",
])
def test_the_census_finds_a_press_through_the_core_or_playwright(source):
    assert presses(source), source


@pytest.mark.parametrize("source", [
    "def ok(page):\n    page.mouse.wheel(0, 2500)\n",
    "def ok(page):\n    page.locator('a').get_attribute('href')\n",
    "def ok(page):\n    page.evaluate(\"e => e.getAttribute('data-a-popover')\")\n",
    "from paperpull_core import shared_folder\ndef ok(a, b):\n    shared_folder.move(a, b)\n",
    "from paperpull_core import naming\ndef ok():\n    naming.check('{date}')\n",
    "from paperpull_core.controls import SETTINGS_CONTROL_RE\n",
    "def ok():\n    '''Nothing here does e.click() or dispatchEvent.'''\n",
])
def test_the_census_leaves_reading_alone(source):
    assert presses(source) == [], source
