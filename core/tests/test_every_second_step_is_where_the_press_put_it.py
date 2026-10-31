"""A control a press revealed is pressed only where that press put it.

The captures cut from one scaffold press a document's control, wait for the
PDF, and when nothing came press a second step, a control the press newly
showed whose words finish a download (Download PDF, Save PDF and the like).
Nothing tied that control to the document. A list drawn anew after a press
that went through, or a panel opened for another row, shows a Download of
another document, and its PDF was saved under this one's name. Since
eba349c4 a control that left the page before its press ends the capture,
and this is the same for a press that went through.

The census has two halves.

  * In the source, every press an app makes after the document's own press,
    in every function that makes that press through pressing.press_once,
    is of a control chosen by something handed the place read just before
    that press (controls.place_of), or is a press reviewed here by name.
  * In a real browser, each such app's own _catch_pdf is run against a
    statements list whose press is followed by a Download PDF in a list
    drawn anew, in a new row, in another row's panel, in a row drawn anew
    beside the control's own, and in a dialog the page already showed.
    None of those is pressed and nothing is saved. A dialog the press
    opened and a menu beside the control are pressed and their PDF saved.

Every word here is made up.
"""
import ast
import importlib
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from paperpull_core import controls, pressing

REPO = Path(__file__).resolve().parents[2]

# What a press may be, made through Playwright on a value of the capture's.
PRESSES = {"click", "dblclick", "tap", "check", "set_checked", "dispatch_event",
           "select_option", "press"}

# A press after the document's own that presses nothing the press revealed,
# by app and by what makes it, with why.
REVIEWED = {
    # The document's own control once more, after a clean press that showed
    # nothing at all and left the tab where it was (Apple Card's first press
    # is sometimes dropped while the page settles).
    ("applecard", "_press_again"): "the document's own control again",
}


# -- the source -----------------------------------------------------------------

def _names(tree):
    """The names this module gives the core's second_step, place_of and
    where_it_sits, and the core's controls module."""
    step, place, where, module = set(), set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "paperpull_core.controls":
            for a in node.names:
                {"second_step": step, "place_of": place, "where_it_sits": where}.get(
                    a.name, set()).add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "paperpull_core":
            for a in node.names:
                if a.name == "controls":
                    module.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "paperpull_core.controls" and a.asname:
                    module.add(a.asname)
    return step, place, where, module


def _calls(node, names, module, attr):
    """Whether `node` is a call of one of `names`, or of `attr` on the
    controls module."""
    f = node.func if isinstance(node, ast.Call) else None
    return (isinstance(f, ast.Name) and f.id in names) or (
        isinstance(f, ast.Attribute) and f.attr == attr
        and isinstance(f.value, ast.Name) and f.value.id in module)


def _is_press_once(node):
    f = node.func if isinstance(node, ast.Call) else None
    return isinstance(f, ast.Attribute) and f.attr == "press_once" \
        and isinstance(f.value, ast.Name) and f.value.id == "pressing"


def _passes(call, names):
    """Whether a call hands on one of `names`."""
    values = list(call.args) + [k.value for k in call.keywords]
    return any(isinstance(v, ast.Name) and v.id in names for v in values)


def _presses_in(fn):
    """The presses of a control Playwright makes in `fn`, as (line, receiver
    name). A key pressed on the keyboard, PG&E's Escape that closes its page
    picker, presses no control."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in PRESSES:
            receiver = node.func.value
            if isinstance(receiver, ast.Attribute) and receiver.attr == "keyboard":
                continue
            out.append((node.lineno, receiver.id if isinstance(receiver, ast.Name) else ""))
    return out


def _names_nothing(node) -> bool:
    """A value that names no control, None or a tuple whose first item is
    None, as `(None, "")` does for a step not looked for."""
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    return (isinstance(node, ast.Tuple) and bool(node.elts)
            and isinstance(node.elts[0], ast.Constant) and node.elts[0].value is None)


def _choices(value) -> list:
    """What an assignment takes a control from. Through a conditional, each
    side that names one, so `(None, "") if unsure_press else
    _second_step(page, appeared, place, trace)` is the call alone and still
    has to pass the place. A side that is neither a call nor nothing is kept
    as it is, and counts as not chosen."""
    if isinstance(value, ast.IfExp):
        return [c for side in (value.body, value.orelse)
                if not _names_nothing(side) for c in _choices(side)]
    return [value]


def _site_modules():
    for app in sorted(p for p in (REPO / "apps").iterdir()
                      if p.is_dir() and not p.name.startswith(("_", "."))):
        for path in sorted(app.glob("*.py")):
            yield app.name, path


def census():
    """Every app module's captures, as (app, function, findings, line), where
    findings name each later press that is not tied to the place."""
    out = []
    for app, path in _site_modules():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        step, place_of, where, module = _names(tree)
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

        def chooses(name, seen=()):
            """Whether a module function chooses a control against a place,
            through the core's second_step or where_it_sits, directly or
            through another module function."""
            fn = functions.get(name)
            if fn is None or name in seen:
                return False
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and (
                        _calls(node, step, module, "second_step")
                        or _calls(node, where, module, "where_it_sits")):
                    return True
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and chooses(node.func.id, seen + (name,)):
                    return True
            return False

        def presses(name, seen=()):
            fn = functions.get(name)
            if fn is None or name in seen:
                return False
            return bool(_presses_in(fn)) or any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and presses(n.func.id, seen + (name,)) for n in ast.walk(fn))

        for fn in functions.values():
            first = min((n.lineno for n in ast.walk(fn) if _is_press_once(n)), default=None)
            if first is None:
                continue
            press = next(n for n in ast.walk(fn) if _is_press_once(n) and n.lineno == first)
            pressed = press.args[1].id if len(press.args) > 1 and isinstance(press.args[1], ast.Name) else None
            places, findings = set(), []
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and n.lineno < first \
                        and _calls(n.value, place_of, module, "place_of"):
                    read = n.value.args[1] if len(n.value.args) > 1 else None
                    if pressed is None or not (isinstance(read, ast.Name) and read.id == pressed):
                        findings.append("line %d reads the place of something other than the "
                                        "control press_once presses" % n.lineno)
                        continue
                    places |= {t.id for t in n.targets if isinstance(t, ast.Name)}
            chosen = {}
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Call, ast.IfExp)):
                    for t in n.targets:
                        for name in ([t] if isinstance(t, ast.Name) else getattr(t, "elts", [])):
                            if isinstance(name, ast.Name):
                                chosen.setdefault(name.id, []).extend(_choices(n.value))
            for line, receiver in _presses_in(fn):
                if line <= first:
                    continue
                made = chosen.get(receiver, [])
                if not made or not all(
                        isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and chooses(c.func.id) and _passes(c, places)
                        for c in made):
                    findings.append("line %d presses %s, not chosen against the place"
                                    % (line, receiver or "a value it did not name"))
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and n.lineno > first and isinstance(n.func, ast.Name) \
                        and n.func.id != fn.name and presses(n.func.id) \
                        and not chooses(n.func.id) and (app, n.func.id) not in REVIEWED:
                    findings.append("line %d calls %s, which presses" % (n.lineno, n.func.id))
                if _is_press_once(n) and n.lineno > first:
                    findings.append("line %d presses a second control through press_once" % n.lineno)
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and (_calls(n, step, module, "second_step")
                                                or (isinstance(n.func, ast.Name)
                                                    and chooses(n.func.id))):
                    if not _passes(n, places):
                        findings.append("line %d chooses a second step without the place "
                                        "read before the press" % n.lineno)
            out.append((app, fn.name, findings, fn.lineno))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and _calls(n, step, module, "second_step"):
                given = n.args[4] if len(n.args) > 4 else next(
                    (k.value for k in n.keywords if k.arg == "place"), None)
                if given is None or (isinstance(given, ast.Constant) and given.value is None):
                    out.append((app, "<module>", ["line %d hands the core's second_step no place"
                                                  % n.lineno], n.lineno))
    return out


CENSUS = census()


def test_a_step_not_looked_for_after_an_unsure_press_is_still_chosen_against_the_place():
    """The census looks through `(None, "") if unsure_press else ...` to the
    call, which must pass the place, and a conditional whose other side
    names a control of its own is not let through."""
    good = ast.parse("step, label = (None, '') if unsure else _second_step(page, seen, place, trace)").body[0]
    assert [ast.unparse(c) for c in _choices(good.value)] == ["_second_step(page, seen, place, trace)"]
    bad = ast.parse("step, label = other if unsure else _second_step(page, seen, place, trace)").body[0]
    assert [ast.unparse(c) for c in _choices(bad.value)] == ["other", "_second_step(page, seen, place, trace)"]


def test_the_census_is_not_vacuous():
    """Every app cut from the scaffold, and AT&T's own menu."""
    captures = {app for app, fn, _, _ in CENSUS if fn == "_catch_pdf"}
    assert captures >= {"amfam", "applecard", "att", "etrade", "golden1", "nelnet", "newrez",
                        "sba", "smud", "statefarm", "wellsfargo"}, captures


@pytest.mark.parametrize("entry", [e for e in CENSUS], ids=lambda e: "%s.%s" % (e[0], e[1]))
def test_every_press_after_the_first_is_chosen_against_the_place(entry):
    app, fn, findings, line = entry
    assert not findings, "%s %s (line %d): %s" % (app, fn, line, " | ".join(findings))


def test_the_reviewed_presses_are_still_there():
    """A reviewed press that has gone is taken off the list."""
    for app, name in REVIEWED:
        tree = ast.parse((REPO / "apps" / app / ("%s_site.py" % app)).read_text(encoding="utf-8-sig"))
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), (app, name)


def test_the_census_finds_a_second_step_without_a_place(tmp_path, monkeypatch):
    """A made-up app whose capture presses what the core chose, with no
    place read before its press, and one that presses a control it found
    by its own search."""
    app = tmp_path / "apps" / "madeup"
    app.mkdir(parents=True)
    (app / "madeup_site.py").write_text(
        "from paperpull_core import pressing\n"
        "from paperpull_core.controls import second_step as _core_second_step\n"
        "from paperpull_core.controls import place_of as _place_of\n"
        "def _second_step(page, appeared, place, trace=None):\n"
        "    return _core_second_step(page, appeared, None, None, place, trace)\n"
        "def _catch_pdf(page, el, label, out_path, trace=None, dl_dir=None):\n"
        "    outcome = pressing.press_once(page, el, what='x', words=None, guard=None)\n"
        "    step, text = _second_step(page, set(), None, trace)\n"
        "    step.click()\n"
        "    other = page.get_by_role('button').first\n"
        "    other.click()\n"
        "def _catch_two(page, el):\n"
        "    place = _place_of(page, el)\n"
        "    pressing.press_once(page, el, what='x', words=None, guard=None)\n"
        "    step, text = _second_step(page, set(), place)\n"
        "    step.click()\n"
        "def _catch_three(page, el, row):\n"
        "    place = _place_of(page, row)\n"
        "    pressing.press_once(page, el, what='x', words=None, guard=None)\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "REPO", tmp_path)
    found = {fn: findings for a, fn, findings, _ in census() if a == "madeup"}
    assert any("presses step" in f for f in found["_catch_pdf"]), found
    assert any("presses other" in f for f in found["_catch_pdf"]), found
    assert any("without the place" in f for f in found["_catch_pdf"]), found
    assert found["_catch_two"] == [], found
    assert any("other than the control" in f for f in found["_catch_three"]), found


# -- in a real browser ----------------------------------------------------------

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40
_OTHER = b"%PDF-1.4\n" + b"2 0 obj << >> endobj\n" * 40

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<style>html, body { margin: 0; font: 16px sans-serif; } button { height: 32px; }</style>
<script>
window.presses = 0; window.laterPresses = 0; window.rightPresses = 0; window.done = false;
function control(text, right) {
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = text;
  b.onclick = () => {
    if (right) { window.rightPresses++; fetch('/statement.pdf'); }
    else { window.laterPresses++; fetch('/other.pdf'); }
  };
  return b;
}
function row(date, ctl) {
  const tr = document.createElement('tr');
  const a = document.createElement('td'); a.textContent = date;
  const b = document.createElement('td'); b.append(ctl);
  tr.append(a, b);
  return tr;
}
function dialog(...ctls) {
  const d = document.createElement('div');
  d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true');
  d.append(...ctls);
  document.body.append(d);
}
function atTheEnd(role, ...ctls) {
  const m = document.createElement('div');
  if (role) m.setAttribute('role', role);
  m.append(...ctls);
  document.body.append(m);
}
window.then = %s;
</script></head>
<body><header><nav><a href="/home">Home</a> <a href="/help">Help</a></nav></header>
<main><h1>Statements</h1>
<table><tbody id="rows">
<tr id="r1"><td>June 30, 2026</td><td><button id="get" type="button"
  onclick="window.presses++; const el = this;
           setTimeout(() => { window.then(el); window.done = true; }, 30);"
  >Download statement</button></td></tr>
<tr id="r2"><td>May 31, 2026</td><td><button type="button">Download statement</button></td></tr>
</tbody></table></main>
<div role="dialog" id="shown">Your session is active</div>
<div role="dialog" id="closed" hidden></div>
<div popover id="pop"></div>
<dialog id="modal"></dialog>
</body></html>"""

# What the page does once the press went through, by what it shows. Each
# shows a Download PDF, and only those put by the press are pressed. The
# shapes in EACH_APP are run through every app's own capture too.
SHOWN_ELSEWHERE = {
    "a list drawn anew": "(el) => document.getElementById('rows').replaceChildren("
                         "row('June 30, 2026', control('Download PDF')),"
                         "row('May 31, 2026', control('Download PDF')))",
    "the next row drawn anew": "(el) => document.getElementById('r2').replaceWith("
                               "row('May 31, 2026', control('Download PDF')))",
    "a row added to the list": "(el) => document.getElementById('rows').append("
                               "row('July 31, 2026', control('Download PDF')))",
    "another row's panel": "(el) => document.getElementById('r2').cells[1].append(control('Download PDF'))",
    "a dialog the page already showed": "(el) => document.getElementById('shown')"
                                        ".append(control('Download PDF'))",
    "two in the dialog the press opened": "(el) => dialog(control('Download PDF', true),"
                                          " control('Download PDF'))",
    "a plain box drawn at the end of the page": "(el) => atTheEnd('', control('Download PDF'))",
    "a list drawn anew and a dialog": "(el) => { document.getElementById('rows').replaceChildren("
                                      "row('June 30, 2026', control('Download PDF')));"
                                      " dialog(control('Download PDF')); }",
    "the plain choice elsewhere and another in the dialog":
        "(el) => { dialog(control('Itemized PDF')); document.getElementById('rows')"
        ".append(row('July 31, 2026', control('Regular PDF'))); }",
}
PUT_BY_THE_PRESS = {
    "the dialog the press opened": "(el) => dialog(control('Download PDF', true))",
    "a menu beside the control": "(el) => { const m = document.createElement('div');"
                                 " m.className = 'menu'; m.append(control('Download PDF', true));"
                                 " el.after(m); }",
    "the dialog the press opened, with another elsewhere":
        "(el) => { dialog(control('Download PDF', true));"
        " document.getElementById('rows').append(row('July 31, 2026', control('Download PDF'))); }",
    "a menu drawn at the end of the page": "(el) => atTheEnd('menu', control('Download PDF', true))",
    "a dialog that was hidden": "(el) => { const d = document.getElementById('closed');"
                                " d.append(control('Download PDF', true)); d.hidden = false; }",
    "a popover": "(el) => { const p = document.getElementById('pop');"
                 " p.append(control('Download PDF', true)); p.showPopover(); }",
    "a modal dialog element": "(el) => { const d = document.getElementById('modal');"
                              " d.append(control('Download PDF', true)); d.showModal(); }",
    "a list of choices beside the control":
        "(el) => { const u = document.createElement('ul'); const li = document.createElement('li');"
        " li.append(control('Download PDF', true)); u.append(li); el.after(u); }",
}
EACH_APP = ["a list drawn anew", "another row's panel", "the dialog the press opened"]

WORDS = re.compile(r"^\s*(download\s+pdf|regular\s+pdf|itemized\s+pdf)\s*$", re.I)


def _allow(_text):
    return True


def site_of(app: str):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        return importlib.import_module("%s_site" % app)
    finally:
        sys.path.pop(0)


APPS = sorted({app for app, fn, _, _ in CENSUS if fn == "_catch_pdf"})


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path.startswith("/statement.pdf"):
            body, kind = _PDF, "application/pdf"
        elif self.path.startswith("/other.pdf"):
            body, kind = _OTHER, "application/pdf"
        else:
            body, kind = self.server.page.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def site(browser, monkeypatch):
    """The statements page on a site of the test's own, opened for what the
    page does once the press went through."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    context = browser.new_context(viewport={"width": 1000, "height": 700})
    monkeypatch.setattr(pressing, "PRESS_MS", 3000)

    def open_page(then):
        httpd.page = PAGE % then
        page = context.new_page()
        page.port = httpd.server_address[1]
        page.goto("http://127.0.0.1:%d/statements" % page.port)
        return page

    yield open_page
    context.close()
    httpd.shutdown()
    httpd.server_close()


def _pressed_then_chosen(page):
    """The core's own choice after the press, with the place read before it."""
    before = controls.control_texts(page)
    place = controls.place_of(page, page.locator("#get"))
    page.locator("#get").click()
    page.wait_for_function("() => window.done")
    appeared = controls.control_texts(page) - before
    trace = []
    return controls.second_step(page, appeared, WORDS, _allow, place, trace), trace


@pytest.mark.parametrize("shape", sorted(SHOWN_ELSEWHERE))
def test_the_core_takes_nothing_the_press_did_not_put_there(site, shape):
    page = site(SHOWN_ELSEWHERE[shape])
    (step, text), trace = _pressed_then_chosen(page)
    assert (step, text) == (None, ""), shape
    assert trace and trace[-1]["note"].startswith("a revealed control is not where the press put it")
    assert set(trace[-1]["where"]) <= controls.WHERE_WORDS | {controls.SEVERAL}, trace


@pytest.mark.parametrize("shape", sorted(PUT_BY_THE_PRESS))
def test_the_core_takes_what_the_press_put_there(site, shape):
    page = site(PUT_BY_THE_PRESS[shape])
    (step, text), trace = _pressed_then_chosen(page)
    assert text == "Download PDF", (shape, trace)
    step.click()
    assert page.evaluate("window.rightPresses") == 1, "the control taken is not the one put there"
    assert page.evaluate("window.laterPresses") == 0
    assert trace[-1]["where"] in controls.TIED, trace


def test_the_core_takes_nothing_once_the_page_was_loaded_anew(site):
    page = site("(el) => {}")
    place = controls.place_of(page, page.locator("#get"))
    page.locator("#get").click()
    page.goto("http://127.0.0.1:%d/viewer" % page.port)
    page.evaluate("() => dialog(control('Download PDF', true))")
    trace = []
    assert controls.second_step(page, {"Download PDF"}, WORDS, _allow, place, trace) == (None, "")
    assert trace[-1]["where"] == [controls.LOADED_ANEW], trace


def test_the_core_takes_nothing_when_the_place_could_not_be_read(site):
    page = site("(el) => dialog(control('Download PDF', true))")
    page.locator("#get").click()
    page.wait_for_function("() => window.done")
    trace = []
    assert controls.second_step(page, {"Download PDF"}, WORDS, _allow, None, trace) == (None, "")
    assert trace[-1]["where"] == [controls.NOT_READ], trace


def test_a_list_of_one_row_that_grows_a_row_is_not_beside_the_control(site):
    """Before the press the list held the pressed control and nothing else
    to press, so the box around both held nothing else either, and a row
    added to it would have passed for a menu beside the control. The row
    the control sat in bounds it."""
    page = site("(el) => document.getElementById('rows').append("
                "row('July 31, 2026', control('Download PDF')))")
    page.evaluate("() => document.getElementById('r2').remove()")
    (step, text), trace = _pressed_then_chosen(page)
    assert (step, text) == (None, ""), trace


# The same statements as cards, in no row of a list or a table, so no row
# bounds what sits beside the control, and `body` is the whole page.
CARDS = """<!doctype html><html><head><meta charset="utf-8"><script>
window.rightPresses = 0; window.laterPresses = 0; window.done = false;
function control(text, right) {
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = text;
  b.onclick = () => { if (right) window.rightPresses++; else window.laterPresses++; };
  return b;
}
window.then = %s;
</script></head><body>%s</body></html>"""
OWN_CARD = ("<div class='card'><span>June 30, 2026</span> <button id='get' type='button'"
            " onclick='const el = this; setTimeout(() => { window.then(el); window.done = true; }, 30);'"
            ">Download statement</button></div>")
OTHER_CARD = ("<div class='card' id='c2'><span>May 31, 2026</span>"
              " <button type='button'>Download statement</button></div>")


def test_another_cards_panel_in_a_list_of_no_rows_is_not_beside_the_control(site):
    """No row bounds the box around the two controls here, the list of
    cards does, and it held the other card's control before the press."""
    page = site("(el) => {}")
    page.set_content(CARDS % ("(el) => document.getElementById('c2').append(control('Download PDF'))",
                              "<div class='cards'>%s%s</div>" % (OWN_CARD, OTHER_CARD)))
    (step, text), trace = _pressed_then_chosen(page)
    assert (step, text) == (None, ""), trace
    assert trace[-1]["where"] == [controls.ELSEWHERE], trace


def test_a_menu_beside_the_control_in_a_list_of_no_rows_is_taken(site):
    page = site("(el) => {}")
    page.set_content(CARDS % ("(el) => el.after(control('Download PDF', true))",
                              "<div class='cards'>%s%s</div>" % (OWN_CARD, OTHER_CARD)))
    (step, text), trace = _pressed_then_chosen(page)
    assert text == "Download PDF" and trace[-1]["where"] == controls.BESIDE_THE_CONTROL, trace


PRESSED = ("<button id='get' type='button'"
           " onclick='const el = this; setTimeout(() => { window.then(el); window.done = true; }, 30);'"
           ">Download statement</button>")
OTHER_ROW = ("<div class='row'><span>May 31, 2026</span>"
             " <button type='button'>Download statement</button></div>")

# Rows built as web components, each keeping its own control in a shadow
# root of its own, the way E*TRADE's documents table is built.
SHADOW_ROW = """<x-row id='b'></x-row><script>
customElements.define('x-row', class extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = '<span>May 31, 2026</span> <button type="button">Download statement</button><slot></slot>';
  }
});
</script>"""
SHADOW_PICKER = """<x-pick id='c'></x-pick><script>
customElements.define('x-pick', class extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = '<div role="listbox" id="lb">Choose a period</div>';
  }
});
</script>"""
SHADOW_OWN = """<x-own id='a'></x-own><script>
customElements.define('x-own', class extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = '<span>June 30, 2026</span> <span class="w"><button id="get" type="button">'
      + 'Download statement</button></span>';
    r.getElementById('get').addEventListener('click', function () {
      const el = this;
      setTimeout(() => { window.then(el); window.done = true; }, 30);
    });
  }
});
</script>"""


@pytest.mark.parametrize("then, body, where", [
    ("(el) => document.getElementById('b').append(control('Download PDF'))",
     "<div class='rows'><div class='row'><span>June 30, 2026</span> %s</div>%s</div>"
     % (PRESSED, SHADOW_ROW), controls.ELSEWHERE),
    ("(el) => document.getElementById('c').shadowRoot.getElementById('lb')"
     ".append(control('Download PDF'))",
     "<div class='row'><span>June 30, 2026</span> %s</div>%s%s" % (PRESSED, OTHER_ROW, SHADOW_PICKER),
     controls.ELSEWHERE),
    ("(el) => document.getElementById('dc').append(control('Download PDF'))",
     "<div class='row'><span>June 30, 2026</span> %s</div>%s<div role='dialog' id='dc'"
     " style='display: contents'><p>Your session is active</p></div>" % (PRESSED, OTHER_ROW),
     controls.ELSEWHERE),
    ("(el) => { for (let i = 0; i < 7; i++) document.body.append(control('Download PDF'));"
     " const d = document.createElement('div'); d.setAttribute('role', 'dialog');"
     " d.append(control('Download PDF', true), control('Download PDF', true));"
     " document.body.append(d); }",
     "<div class='row'><span>June 30, 2026</span> %s</div>%s" % (PRESSED, OTHER_ROW),
     controls.CROWDED),
], ids=["another web component row", "a listbox already open in a shadow root",
        "a dialog already open with no box of its own", "more of them than are read"])
def test_what_the_page_already_held_is_read_wherever_it_is(site, then, body, where):
    """Found by the review. Both reads stopped at shadow roots, so another
    row's control there went uncounted and a listbox open there looked
    opened by the press. A dialog already open with no box of its own read
    as hidden, so it looked opened by the press too. And past the eighth
    control of one name, one where the press put it could be all that was
    read."""
    page = site("(el) => {}")
    page.set_content(CARDS % (then, body))
    (step, text), trace = _pressed_then_chosen(page)
    assert (step, text) == (None, ""), trace
    assert trace[-1]["where"] == [where], trace


@pytest.mark.parametrize("then", [
    "(el) => el.after(control('Download PDF', true))",
    "(el) => { const d = document.createElement('div'); d.setAttribute('role', 'dialog');"
    " d.append(control('Download PDF', true)); el.getRootNode().append(d); }",
], ids=["a menu beside it", "a dialog the press opened"])
def test_a_control_put_by_a_press_inside_a_shadow_root_is_taken(site, then):
    page = site("(el) => {}")
    page.set_content(CARDS % (then, "<div class='rows'>%s%s</div>" % (SHADOW_OWN, OTHER_ROW)))
    (step, text), trace = _pressed_then_chosen(page)
    assert text == "Download PDF" and trace[-1]["where"] in controls.TIED, trace
    step.click()
    assert page.evaluate("window.rightPresses") == 1


def test_a_page_with_nothing_else_to_press_is_not_beside_the_control(site):
    """The body held nothing to press but the pressed control, so a box
    drawn at the end of the page would have passed for a menu beside it.
    Neither the body nor the page is ever beside the control."""
    page = site("(el) => {}")
    page.set_content(CARDS % ("(el) => { const d = document.createElement('div');"
                              " d.append(control('Download PDF')); document.body.append(d); }",
                              OWN_CARD))
    (step, text), trace = _pressed_then_chosen(page)
    assert (step, text) == (None, ""), trace
    assert trace[-1]["where"] == [controls.ELSEWHERE], trace


@pytest.fixture()
def capture(site, tmp_path, monkeypatch):
    """Run an app's own _catch_pdf on the statements page, the page doing
    `then` once the press went through."""

    def run(app, then):
        app_site = site_of(app)
        page = site(then)
        monkeypatch.setattr(app_site, "is_safe_url", lambda url: (
            urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == page.port))
        # Every wait is a moment, so a run of the capture takes about a
        # second, and the page's own answer still comes in time.
        own_wait = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: own_wait(min(ms, 30))
        out = tmp_path / app / "2026-06-30 Statement.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = tmp_path / app / "downloads"
        staging.mkdir()
        trace = []
        page.result = {"trace": trace, "out": out}
        try:
            page.result["saved"] = app_site._catch_pdf(page, page.locator("#get"),
                                                       "Download statement", out, trace, staging)
        except pressing.Stop as stop:
            page.result["stop"] = stop
        return page

    yield run


def test_every_app_with_a_second_step_is_driven():
    assert set(APPS) >= {"amfam", "applecard", "att", "etrade", "golden1", "nelnet", "newrez",
                         "sba", "smud", "statefarm", "wellsfargo"}, APPS


@pytest.mark.parametrize("shape", [s for s in EACH_APP if s in SHOWN_ELSEWHERE])
@pytest.mark.parametrize("app", APPS)
def test_no_app_presses_a_control_shown_elsewhere(capture, app, shape):
    page = capture(app, SHOWN_ELSEWHERE[shape])
    assert "stop" not in page.result, page.result
    assert page.evaluate("window.presses") == 1, "the document's own control was not pressed once"
    assert page.evaluate("window.laterPresses") == 0, "another document's Download PDF was pressed"
    assert page.result["saved"] is False
    assert not page.result["out"].exists()
    notes = [t for t in page.result["trace"] if isinstance(t, dict)
             and str(t.get("note", "")).startswith("a revealed control is not where the press put it")]
    assert notes, page.result["trace"]


@pytest.mark.parametrize("shape", [s for s in EACH_APP if s in PUT_BY_THE_PRESS])
@pytest.mark.parametrize("app", APPS)
def test_every_app_presses_a_control_the_press_put_there_and_saves_it(capture, app, shape):
    page = capture(app, PUT_BY_THE_PRESS[shape])
    assert "stop" not in page.result, page.result
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.rightPresses") == 1, "the revealed Download PDF was not pressed"
    assert page.evaluate("window.laterPresses") == 0
    assert page.result["saved"] is True
    assert page.result["out"].read_bytes() == _PDF
