"""No app and nothing in the core presses past Playwright's own checks.

Playwright's force=True turns off the checks it makes before a press, the
check that the element itself would receive the press among them, and
presses the middle of the element whatever is drawn over it there. On a
tester's American Express statements page a chat bubble sat over part of
the last Download button. The forced press opened the chat, the presses
after it landed on the chat's suggested replies, one of them opened a
window to dispute a charge, and a live agent joined.

A press at a point on the page, page.mouse.click or a mouse down and up,
lands on whatever is on top at that point in the same way. A press event
that Playwright's dispatch_event sends to an element skips every check as
well.

So this reads the Python source of every app, the core, the panel and the
server, apart from their tests, and fails on three things. A Playwright
action called with force, a press of the mouse or the touch screen at a
point on the page, and a dispatch_event call that names a press event, or
names its event in a way this cannot read. A press goes through
paperpull_core.pressing, which brings the control to the middle of the
window, presses only when it is the thing on top there, and presses
unforced so Playwright checks once more.

It reads Python and never JavaScript, so a press a page script makes is
not read here. el.click() inside an evaluate is one, and
test_no_app_presses_through_page_script reads those.

Read from the syntax tree, never by searching the text, so a force
argument of something that is not a press (prime_session, a token
reader, an opener, logging.basicConfig) is no press at all.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Every Playwright action that takes force, on a Locator, an ElementHandle,
# a Page or a Frame, and the ones the census was asked to hold besides.
FORCEABLE = frozenset((
    "click", "dblclick", "tap", "check", "uncheck", "set_checked", "hover", "fill",
    "clear", "select_option", "select_text", "drag_to", "drag_and_drop", "press",
    "press_sequentially", "type"))

# A press of the mouse or the touch screen at a point on the page.
AT_A_POINT = {"mouse": frozenset(("click", "dblclick", "down", "up")),
              "touchscreen": frozenset(("tap",))}

# Events that, dispatched to an element, are a press nobody made.
PRESS_EVENTS = frozenset(("click", "dblclick", "mousedown", "mouseup", "pointerdown",
                          "pointerup", "touchstart", "touchend"))

# What ships, apps and the core and what the panel and the server run.
ROOTS = ("apps", "core", "gui", "server")


def is_test(path: Path) -> bool:
    parts = path.relative_to(REPO).parts
    return ("tests" in parts or path.name.startswith("test_")
            or path.name == "conftest.py" or ".venv" in parts
            or any(p.startswith(".") for p in parts))


def sources():
    out = []
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if not is_test(path):
                out.append(path)
    return out


def _forced(call: ast.Call) -> bool:
    """Whether a call passes force with anything but a plain False, by name
    or inside a dict it spreads into its keywords."""
    for k in call.keywords:
        if k.arg == "force":
            return not (isinstance(k.value, ast.Constant) and k.value.value is False)
        if k.arg is None:
            spread = k.value
            if isinstance(spread, ast.Dict):
                for key, value in zip(spread.keys, spread.values):
                    if isinstance(key, ast.Constant) and key.value == "force" and not (
                            isinstance(value, ast.Constant) and value.value is False):
                        return True
            if (isinstance(spread, ast.Call) and getattr(spread.func, "id", "") == "dict"
                    and any(kw.arg == "force" for kw in spread.keywords)):
                return True
    return False


def _aliases(tree) -> dict:
    """Names a module binds to a page's mouse or touch screen,
    `mouse = page.mouse`, so a press through the name is still found."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Attribute) and value.attr in AT_A_POINT:
                for t in targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = value.attr
    return out


def _device(node, aliases) -> str:
    """"mouse" or "touchscreen" when `node` is one, else ""."""
    if isinstance(node, ast.Attribute) and node.attr in AT_A_POINT:
        return node.attr
    if isinstance(node, ast.Name):
        if node.id in AT_A_POINT:
            return node.id
        return aliases.get(node.id, "")
    return ""


def _event_types(call: ast.Call) -> list:
    """The event types a dispatch_event call names, None for one that is
    not written out, since a press could be in it."""
    found = [a.value for a in call.args
             if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    for k in call.keywords:
        if k.arg == "type":
            found.append(k.value.value if isinstance(k.value, ast.Constant) else None)
    if not found and (call.args or call.keywords):
        found.append(None)
    return found


def presses_past_the_checks(source: str) -> list:
    """Every press in `source` that skips Playwright's checks, as
    (line, what) pairs."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name in FORCEABLE and _forced(node):
            out.append((node.lineno, "%s with force" % name))
        device = _device(node.func.value, aliases)
        if device and name in AT_A_POINT[device]:
            out.append((node.lineno, "%s.%s at a point" % (device, name)))
        if name == "dispatch_event":
            kinds = _event_types(node)
            if any(k is None or str(k).lower() in PRESS_EVENTS for k in kinds):
                out.append((node.lineno, "dispatch_event of %s" % (
                    ", ".join(str(k) for k in kinds) or "an event")))
    return sorted(out)


SOURCES = sources()


def test_the_census_reads_every_app_and_the_core():
    """Not vacuous. Every app's site and docs module is read, and the core's
    own package, and no test."""
    names = {p.relative_to(REPO).as_posix() for p in SOURCES}
    apps = sorted(d.name for d in (REPO / "apps").iterdir() if (d / ("%s_site.py" % d.name)).exists())
    assert len(apps) >= 60
    for app in apps:
        assert "apps/%s/%s_site.py" % (app, app) in names, app
    assert {"apps/amex/amex_site.py", "apps/vanguard/vanguard_site.py",
            "core/paperpull_core/pressing.py", "core/paperpull_core/controls.py"} <= names
    assert not [n for n in names if "/tests/" in n or n.split("/")[-1].startswith("test_")]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(REPO).as_posix())
def test_nothing_presses_past_playwrights_checks(path):
    found = presses_past_the_checks(path.read_text(encoding="utf-8-sig"))
    assert not found, "%s presses past Playwright's checks at %s. Press through " \
        "paperpull_core.pressing instead." % (path.relative_to(REPO).as_posix(), found)


def _presses_through_pressing(app: Path) -> bool:
    for path in sorted(app.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "pressing"
                    and node.attr in ("click", "check", "press_once")):
                return True
    return False


def test_every_app_that_presses_through_pressing_stops_its_run_on_a_stop():
    """A stop is a SystemExit, so it passes every except Exception on its
    way out, and an app whose main() did not take it would leave without
    saying why in its own words or writing its failure file. Every app
    that presses through paperpull_core.pressing catches pressing.Stop in
    main() and hands it to pressing.stop_run."""
    users = []
    for app in sorted(d for d in (REPO / "apps").iterdir() if d.is_dir()):
        if not _presses_through_pressing(app):
            continue
        users.append(app.name)
        entry = sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py"))
        assert entry, "%s presses through pressing and has no main() to stop in" % app.name
        tree = ast.parse(entry[0].read_text(encoding="utf-8-sig"))
        main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
        assert main, "%s has no main()" % app.name
        handlers = [h for n in ast.walk(main[0]) if isinstance(n, ast.Try) for h in n.handlers
                    if h.type is not None and ast.unparse(h.type) == "pressing.Stop"]
        assert handlers, "%s does not catch pressing.Stop in main()" % app.name
        assert any("pressing.stop_run(app, " in ast.unparse(h) for h in handlers), \
            "%s catches pressing.Stop without pressing.stop_run" % app.name
    assert {"amex", "vanguard", "adp", "amfam", "applecard", "att", "etrade", "golden1",
            "newrez", "pge", "sba", "smud", "statefarm", "verizonmobile",
            "wellsfargo"} <= set(users), users


def test_the_census_finds_every_kind_of_press_it_is_for():
    """The census, on sources made for it. If one of these stops being
    found, the census above passes on nothing."""
    made = '''
def press(page, btn, el, handle, opts):
    btn.click(force=True, timeout=8000)
    el.check(force=True)
    handle.dblclick(force=1)
    page.click("#x", force=True)
    page.locator("a").hover(**{"force": True})
    btn.tap(**dict(force=True))
    btn.fill("x", force=opts.force)
    page.drag_and_drop("#a", "#b", force=True)
    page.mouse.click(10, 20)
    page.mouse.down()
    page.mouse.up()
    mouse = page.mouse
    mouse.click(1, 2)
    page.touchscreen.tap(1, 2)
    el.dispatch_event("click")
    page.dispatch_event("#x", "pointerdown")
    el.dispatch_event(type="mouseup")
    el.dispatch_event(kind)
'''
    found = [what for _line, what in presses_past_the_checks(made)]
    assert found == [
        "click with force", "check with force", "dblclick with force", "click with force",
        "hover with force", "tap with force", "fill with force", "drag_and_drop with force",
        "mouse.click at a point", "mouse.down at a point", "mouse.up at a point",
        "mouse.click at a point", "touchscreen.tap at a point", "dispatch_event of click",
        "dispatch_event of #x, pointerdown", "dispatch_event of mouseup",
        "dispatch_event of None"]


def test_a_force_that_is_no_press_is_left_alone():
    """force= on a function of the app's own, a token reader, an opener or
    logging, a press made unforced, a force of False, the mouse moved or
    scrolled, and an event that is not a press."""
    alone = '''
def fine(page, el, opener, log):
    prime_session(page, force=True)
    token = _get_token(page, force=True)
    state = opener(page, force=True)
    logging.basicConfig(level=logging.INFO, force=True)
    refresh_installs(force=True)
    el.click()
    el.click(force=False, timeout=8000)
    page.mouse.move(1, 2)
    page.mouse.wheel(0, 3000)
    page.keyboard.press("End")
    el.dispatch_event("change")
    el.dispatch_event("input")
'''
    assert presses_past_the_checks(alone) == []
