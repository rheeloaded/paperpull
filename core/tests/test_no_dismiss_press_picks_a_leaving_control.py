"""No control that closes an account or signs out is pressed to put an
overlay away.

Eleven apps cut from one scaffold put a cookie banner or a survey away by
pressing every visible button whose name began with close, dismiss, no
thanks or not now, `^(close|dismiss|no thanks|not now)\\b`. "Close
account" begins with close. The one check before the press read the
button's text alone against the app's own blocklist, and SBA's and ADP's,
among others, had no "close account" in it, nor any app a "sign out". A
button named "Close" by its aria-label whose text said "Close my
account", or whose title did, passed in every one of them. T-Mobile's
`^close\\b` checked nothing at all, Verizon's `^close .*(menu|sign in)`
reached "Close menu and sign out", and Costco closed its receipt dialog
through `button:has-text('Close')`, which is a part of a name too. Found
in the review of 0.45.0.

So this asks two things of every app.

  * Every pattern, plain text or :has-text a locator is handed, followed
    back to where it is built, picks none of the controls below that
    close an account or sign out. The patterns are found by the locator
    they reach (test_every_app_hands_playwright_a_pattern_it_can_read),
    never by what a helper is called.
  * Every app function that presses whatever such a pattern picks is run
    against a page holding those controls, each named the way a dismiss
    control is by one of its labels, and presses none of them, while it
    still presses a plain Close, so the check does not pass by pressing
    nothing.

Every word here is made up.
"""
import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from paperpull_core import controls

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "_pattern_census", Path(__file__).with_name("test_every_app_hands_playwright_a_pattern_it_can_read.py"))
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)

# What a dismiss control must never be. Each starts the way one does.
LEAVING = [
    "Close account", "Close my account", "Close this account", "Close Apple Card Account",
    "Close joint account", "Close and sign out", "Dismiss and sign out", "Close and log out",
    "Not now, sign out", "No thanks, close my account", "Close menu and sign out",
    "Close sign in and delete", "Close, then log off",
]

# A dismiss word, in what a pattern is asked to pick.
DISMISS_WORD = re.compile(r"^\W*(close|dismiss|no,?\s*thanks|not\s+now)\b", re.I)


def _picks(text: str, flags: int):
    try:
        rx = re.compile(text, flags)
    except re.error:
        return []
    return [label for label in LEAVING if rx.search(label)]


def written_patterns():
    """(where, reaches, pattern, flags) for each pattern written out whole."""
    out = []
    for p in census.PATTERNS:
        call = p.source.parent.get(p.built)
        flags = census.flags_of(call) if isinstance(call, ast.Call) else 0
        for variant in p.variants:
            if variant and all(kind == "text" for kind, _ in variant):
                out.append((p.where(), p.reaches(), "".join(n for _, n in variant), flags))
    return out


def plain_texts():
    """(where, reaches, text, exact) for plain text a locator is handed."""
    out, follow = [], census.Follow()
    for source in census.SOURCES:
        for sink, given in census.sinks(source):
            exact = any(kw.arg == "exact" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                        for kw in sink.keywords)
            for expr, where, _ in follow(given, source, source.function_of(sink)):
                if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                    out.append(("%s line %d" % (where.name, expr.lineno),
                                "%s line %d" % (source.name, sink.lineno), expr.value, exact))
    return out


# Playwright's text pseudo-classes and text= selectors that match a part of
# a name. :text-is() and text="..." in quotes match the whole of it.
_PART_OF_A_NAME = re.compile(
    r""":(?:has-text|text)\(\s*(['"])(?P<a>.*?)\1\s*\)|(?<![\w-])text\s*=\s*(?P<b>[^'"\s\]>][^\]>]*)""", re.I)


def css_texts():
    """(where, text) for each part-of-a-name text in a selector written in
    an app or the core."""
    out = []
    for source in census.SOURCES:
        for node in ast.walk(source.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in _PART_OF_A_NAME.finditer(node.value):
                    out.append(("%s line %d" % (source.name, node.lineno), (m.group("a") or m.group("b") or "").strip()))
    return out


def test_no_pattern_a_locator_is_handed_picks_a_control_that_closes_an_account_or_signs_out():
    found = []
    for where, reaches, text, flags in written_patterns():
        picked = _picks(text, flags)
        if picked:
            found.append("%s, reaching %s, %r picks %s" % (where, reaches, text, picked))
    for where, reaches, text, exact in plain_texts():
        words = " ".join(text.split()).lower()
        if not words:
            continue
        picked = [l for l in LEAVING if (l.lower() == words if exact else words in l.lower())]
        if picked:
            found.append("%s, reaching %s, the text %r picks %s" % (where, reaches, text, picked))
    for where, text in css_texts():
        if text and [l for l in LEAVING if text.lower() in l.lower()]:
            found.append("%s, the selector text %r is a part of %r" % (where, text, LEAVING[0]))
    assert not found, "These pick a control that closes an account or signs out. %s" % "; ".join(found)


def test_the_census_reads_patterns_text_and_selectors():
    """Not vacuous. The one in the core and the one Verizon hands it are
    seen, and a selector's part-of-a-name text is read."""
    patterns = written_patterns()
    assert len(patterns) > 150, len(patterns)
    texts = {text for _, _, text, _ in patterns}
    assert any(DISMISS_WORD.search(text) or "(?:close|dismiss" in text for text in texts)
    if hasattr(controls, "DISMISS_NAME_RE"):
        assert controls.DISMISS_NAME_RE.pattern in texts, "the core's own pattern was not followed"
    assert any(text for _, _, text, _ in plain_texts())
    assert [m.group("a") for m in _PART_OF_A_NAME.finditer("[role=dialog] button:has-text('Close')")] == ["Close"]
    assert [m.group("b") for m in _PART_OF_A_NAME.finditer("text=Close")] == ["Close"]
    assert not list(_PART_OF_A_NAME.finditer("button:text-is('Close')"))


# -- the core's own words -------------------------------------------------------

@pytest.mark.parametrize("label", ["Close", "close", " Close ", "Dismiss", "No thanks", "No, thanks",
                                   "Not now", "Close dialog", "Close this banner", "Close pop-up",
                                   "Close survey", "Close menu", "× Close", "Close ×"])
def test_a_dismiss_control_s_whole_name_is_taken(label):
    assert controls.DISMISS_NAME_RE.search(label)
    assert controls.is_dismiss_label(label)


@pytest.mark.parametrize("label", LEAVING + ["Close Account menu and delete", "Closed accounts",
                                             "Sign out", "Log out"])
def test_a_control_that_closes_an_account_or_signs_out_is_never_one(label):
    assert not controls.is_dismiss_label(label), label


@pytest.mark.parametrize("label", ["Sign out", "Sign Out", "Log out", "Logout", "Log off", "Signout",
                                   "Close account", "Close my account", "Close Apple Card Account",
                                   "Close joint account"])
def test_the_shared_blocklist_names_closing_an_account_and_signing_out(label):
    assert controls.SETTINGS_CONTROL_RE.search(label), label


@pytest.mark.parametrize("label", ["Closing Disclosure", "Closed Account Statement", "Account closure letter",
                                   "Close of business summary", "Statement closing date",
                                   "Download statement", "Credit Card Statement", "Logo"])
def test_the_shared_blocklist_still_lets_documents_through(label):
    assert not controls.SETTINGS_CONTROL_RE.search(label), label


def test_a_glyph_alone_beside_a_dismiss_name_is_taken():
    assert controls.is_dismiss_control(["×", "Close"])
    assert controls.is_dismiss_control(["Close"])
    assert not controls.is_dismiss_control([])
    assert not controls.is_dismiss_control(["×"])
    assert not controls.is_dismiss_control(["Close my account", "Close"])
    assert not controls.is_dismiss_control(["Close", "Close account"])
    assert not controls.is_dismiss_control(["Close", "Sign out"])


# -- every app's dismiss press, in a browser -------------------------------------

def _calls_core_dismiss(fn) -> bool:
    return any(isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Attribute) and n.func.attr == "dismiss_overlays")
        or (isinstance(n.func, ast.Name) and n.func.id in ("dismiss_overlays", "_dismiss_overlays")))
        for n in ast.walk(fn))


def _presses(fn) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "click"
               for n in ast.walk(fn))


def dismiss_helpers():
    """(app, function name) for each app function, taking a page alone,
    that presses what a pattern picking Close picks, or hands the core's
    dismiss_overlays the page. Found by what it does."""
    found = set()
    for p in census.PATTERNS:
        if not p.sink_source.name.startswith("apps/"):
            continue
        fn = p.sink_source.function_of(p.sink)
        if fn is None or isinstance(fn, ast.Lambda) or not _presses(fn):
            continue
        call = p.source.parent.get(p.built)
        flags = census.flags_of(call) if isinstance(call, ast.Call) else 0
        texts = ["".join(n for _, n in v) for v in p.variants if v and all(k == "text" for k, _ in v)]
        if any(re.compile(t, flags).search("Close") or re.compile(t, flags).search("Close menu")
               for t in texts if _compiles(t, flags)):
            found.add((p.sink_source.name, fn.name))
    for source in census.SOURCES:
        if not source.name.startswith("apps/"):
            continue
        closing = _closing_patterns(source)
        for node in source.tree.body:
            if isinstance(node, ast.FunctionDef) and _calls_core_dismiss(node):
                found.add((source.name, node.name))
            # A pattern picking Close handed to a helper of the app's own,
            # which reads labels with it rather than handing it to a locator,
            # Golden 1's close_history through _pager.
            elif isinstance(node, ast.FunctionDef) and _presses(node) and any(
                    isinstance(a, ast.Name) and a.id in closing
                    for n in ast.walk(node) if isinstance(n, ast.Call) for a in n.args):
                found.add((source.name, node.name))
    out = []
    for name, fn_name in sorted(found):
        source = next(s for s in census.SOURCES if s.name == name)
        fn = next(n for n in source.tree.body if isinstance(n, ast.FunctionDef) and n.name == fn_name)
        if [a.arg for a in fn.args.args] == ["page"]:
            out.append((name, fn_name))
    return out


def _closing_patterns(source) -> set:
    """The module's own names for a compiled pattern that takes "Close"."""
    out = set()
    for node in source.tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call) \
                and census.is_re(node.value, "compile") and node.value.args \
                and isinstance(node.value.args[0], ast.Constant) and isinstance(node.value.args[0].value, str):
            text, flags = node.value.args[0].value, census.flags_of(node.value)
            if _compiles(text, flags) and re.compile(text, flags).search("Close"):
                out.add(node.targets[0].id)
    return out


def _compiles(text, flags) -> bool:
    try:
        re.compile(text, flags)
        return True
    except re.error:
        return False


HELPERS = dismiss_helpers()

# Each control a dismiss press must leave alone, named Close or the like by
# one of its labels, then two it should press, all in a dialog that stays
# open, the way a receipt dialog that ignores Escape does.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Account</title>
<script>window.hits = {}; function hit(k) { window.hits[k] = (window.hits[k] || 0) + 1; }</script>
</head><body><main><h1>Account</h1>
<div role="dialog" aria-modal="true" style="min-width: 400px; min-height: 400px">
<button type="button" onclick="hit('close-account')">Close account</button>
<button type="button" aria-label="Close" onclick="hit('text-says-close-my-account')">Close my account</button>
<button type="button" title="Close Apple Card Account" onclick="hit('title-says-close-account')">Close</button>
<button type="button" onclick="hit('dismiss-and-sign-out')">Dismiss and sign out</button>
<button type="button" onclick="hit('not-now-sign-out')">Not now, sign out</button>
<button type="button" onclick="hit('close-menu-and-sign-out')">Close menu and sign out</button>
<button type="button" aria-label="Close" onclick="hit('text-says-sign-out')">Sign out</button>
<button type="button" onclick="hit('ok')">Close</button>
<button type="button" onclick="hit('ok-menu')">Close Mobile menu</button>
</div></main></body></html>"""

LEAVE_ALONE = ["close-account", "text-says-close-my-account", "title-says-close-account",
               "dismiss-and-sign-out", "not-now-sign-out", "close-menu-and-sign-out",
               "text-says-sign-out"]


def test_every_dismiss_press_is_here():
    """Not vacuous. The eleven of the scaffold, American Family's, Apple
    Card's, T-Mobile's and Verizon's of their own, and Costco's receipt
    dialog's Close, once the core's helper is what they press through."""
    apps = {name.split("/")[1] for name, _ in HELPERS}
    assert ("apps/golden1/golden1_site.py", "close_history") in HELPERS, HELPERS
    assert apps >= {"adp", "amfam", "applecard", "att", "etrade", "golden1", "nelnet", "newrez",
                    "sba", "smud", "statefarm", "tmobile", "verizon",
                    "wellsfargo"} | ({"costco"} if hasattr(controls, "dismiss_overlays") else set()), sorted(apps)


def _module(name: str):
    path = REPO / name
    for m in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[m]
    sys.path.insert(0, str(path.parent))
    try:
        return importlib.import_module(path.stem)
    finally:
        sys.path.pop(0)


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


@pytest.mark.parametrize("helper", HELPERS, ids=lambda h: "%s.%s" % (h[0].split("/")[1], h[1]))
def test_no_dismiss_press_presses_a_control_that_closes_an_account_or_signs_out(browser, helper):
    name, fn_name = helper
    module = _module(name)
    page = browser.new_page()
    try:
        page.set_content(PAGE)
        getattr(module, fn_name)(page)
        hits = page.evaluate("window.hits")
    finally:
        page.close()
    wrong = sorted(k for k in LEAVE_ALONE if hits.get(k))
    assert not wrong, "%s.%s pressed %s" % (name, fn_name, wrong)
    assert hits.get("ok") or hits.get("ok-menu"), "%s.%s pressed nothing at all, %s" % (name, fn_name, hits)


# -- the core's helper, on the shapes its review found ---------------------------

def _run_core(browser, html, **kwargs):
    page = browser.new_page()
    try:
        page.set_content("<script>window.hits = {}; function hit(k) { window.hits[k] = "
                         "(window.hits[k] || 0) + 1; }</script>" + html)
        pressed = controls.dismiss_overlays(page, **kwargs)
        return pressed, page.evaluate("window.hits")
    finally:
        page.close()


def test_a_close_that_confirms_closing_the_account_is_never_pressed(browser):
    """The button says Close and nothing else. The dialog it sits in asks
    whether to close the account, so pressing it confirms that."""
    for dialog in ('<div role="dialog" aria-label="Close your account?">',
                   '<div role="alertdialog" aria-labelledby="t"><h2 id="t">Sign out of every device?</h2>',
                   '<dialog open><h3>Close your account</h3>'):
        end = "</dialog>" if dialog.startswith("<dialog") else "</div>"
        pressed, hits = _run_core(browser, dialog + '<button onclick="hit(\'confirm\')">Close</button>' + end
                                  + '<div role="dialog" aria-label="Cookies">'
                                  '<button onclick="hit(\'ok\')">Close</button></div>')
        assert not hits.get("confirm"), dialog
        assert hits.get("ok") == 1 and pressed == 1, (dialog, hits)


def test_a_close_that_leaves_the_page_moves_none_of_the_others_along(browser):
    html = "".join('<button onclick="hit(\'%s\'); this.remove()">Close</button>' % k for k in "abc")
    pressed, hits = _run_core(browser, html)
    assert pressed == 3 and hits == {"a": 1, "b": 1, "c": 1}, hits


def test_a_bare_close_beside_the_app_s_own_menu_name_is_taken(browser):
    """Verizon's, a Close shown with "Close Mobile menu" as its aria-label."""
    verizon = re.compile(r"^\s*close\s+(?:[\w'-]+\s+){0,2}?menu\s*$", re.I)
    pressed, hits = _run_core(browser, '<button aria-label="Close Mobile menu" onclick="hit(\'menu\')">Close</button>'
                              '<button aria-label="Close Mobile menu" onclick="hit(\'out\')">Sign out</button>',
                              name_re=verizon)
    assert hits == {"menu": 1}, hits


@pytest.mark.parametrize("label", ["Close account dialog", "Close my account window", "Close and sign out menu",
                                   "Close autopay panel", "Close session window", "Close policy dialog",
                                   "Close Savings panel", "Close bill download menu"])
def test_nothing_may_stand_between_close_and_what_it_puts_away(label):
    """AmFam's and Apple Card's own names took none of these, and the core's
    must not either (review of this change)."""
    assert not controls.is_dismiss_label(label), label
