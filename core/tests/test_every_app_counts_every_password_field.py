"""Every app counts every password field in the page, unless it is named here.

Consorsbank keeps its sign-in window in every page and draws it only when
asked, so counting every password field read each signed-in page as signed
out and refused every recording a tester started (#178). Its site module
sets PASSWORD_FIELD, which has its own looks_signed_out and the core's
recorder count only the fields the page draws. That is right only where a
site is known to keep a window like that, since a field kept out of sight
anywhere else may be the next step of a sign-in. So an app sets
PASSWORD_FIELD, or counts only drawn password fields in a check of its own,
only when it is named below with its reason, and then only to the one value
the core takes.

A check can keep only the drawn fields in many ways, and the census reads
for each (DRAWN_FORMS holds one small module per way). A selector with
:visible or the visible= engine. Playwright's is_visible, is_hidden,
bounding_box, filter(visible=), get_by_role (which leaves hidden elements
out unless asked), a wait for a drawn or hidden state (a wait's default is
drawn), and expect's checks of the same. Page script that asks whether a
field is drawn. The recorder's DRAWN_PASSWORD_FIELD, and setting
PASSWORD_FIELD at all. The field may be named in the statement itself,
through what the module or the function bound to a name, or by a helper of
the module that is handed one.

What it does not follow, so a review still reads for it. A name kept on
self or on a class, a helper in another module or in the core, a name made
at run time, and page script whose drawn test sits on a line of its own,
apart from the field and the names the script gave it.

Nothing finds an app by its name. Every module of every app is read, and no
app keeps code in a folder below its own (test_no_app_keeps_code_below_its_own_folder).
"""
import ast
import functools
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import recorder  # noqa: E402

NAMED = {
    "consorsbank": "Its sign-in window sits in every page, the bank's own included, inside web "
                   "components that draw it only when it is asked for. A tester's survey of a "
                   "signed-in page counted the one password field the public home page holds, "
                   "which headless Chromium finds with no box (#178).",
    "sparkassepc": "The signed-in Postfach keeps a password field in hidden sign-in UI. "
                   "The contributor's live session had the Postfach form and document rows "
                   "but no visible password field (#216).",
}

# A drawn-only check that is not the count of the page's own password fields,
# allowed at the one place it is and as many times as it is there. Each
# allowed app still counts every field of the page itself
# (test_an_allowed_app_still_counts_every_field_of_the_page_itself).
# (app, function, form): (how many, reason)
ALLOWED = {
    ("applecard", "looks_signed_out", "is_visible()"): (
        1, "Apple's sign-in is a frame from its own host laid over card.apple.com. The page's "
           "own password fields are all counted. In that frame only a drawn field counts, "
           "since a signed-in page may keep the frame (a guess in applecard_site.py, never "
           "measured). Neither the app's page count nor the recorder reads a frame at all, "
           "so this adds a sign-out answer and takes none away."),
}

MODULES = sorted(p for p in REPO.glob("apps/*/*.py") if not p.name.startswith("test_"))

# The folders an app keeps beside its own code that hold no code of its own.
NOT_CODE = {"tests", ".venv", "venv", "__pycache__", ".pytest_cache"}


def _password_field(tree):
    """What a module sets PASSWORD_FIELD to, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PASSWORD_FIELD" for t in node.targets):
            return node.value.value if isinstance(node.value, ast.Constant) else node
    return None


## Reading a module for a drawn-only check ##################################

PASSWORD_WORDS = ("password", "passwort", "kennwort")

# Selector text that keeps only drawn elements, :visible and the visible=
# selector engine, read with spaces taken out and in any case.
SELECTOR_DRAWN = (":visible", "visible=true", "visible=false")

# Page script that asks whether an element is drawn.
SCRIPT_DRAWN = ("offsetparent", "offsetwidth", "offsetheight", "clientwidth", "clientheight",
                "getboundingclientrect", "getclientrects", "checkvisibility",
                "getcomputedstyle", "intersectionobserver")

# Playwright calls that ask whether something is drawn.
DRAWN_CALLS = {"is_visible", "is_hidden", "bounding_box", "to_be_visible", "not_to_be_visible",
               "to_be_hidden", "not_to_be_hidden", "to_be_in_viewport", "not_to_be_in_viewport"}
# Waits whose state, or whose default state, is drawn or not drawn.
WAIT_CALLS = {"wait_for", "wait_for_selector", "wait_for_element_state"}
DRAWN_STATES = {"visible", "hidden"}
# Calls whose keywords, handed over as **, may keep only drawn elements.
KEYWORD_CALLS = {"filter", "locator", "get_by_role"}
# Calls that run page script, and where their script sits among the
# arguments. The other arguments name what it runs on.
SCRIPT_CALLS = {"evaluate": 0, "evaluate_handle": 0, "evaluate_all": 0,
                "wait_for_function": 0, "add_init_script": 0,
                "eval_on_selector": 1, "eval_on_selector_all": 1}
SCRIPT_KEYWORDS = ("expression", "script")
DRAWN_CONSTANT = "DRAWN_PASSWORD_FIELD"


def _says_password(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in PASSWORD_WORDS)


def _says(text: str, words) -> bool:
    low = text.lower().replace(" ", "")
    return any(w in low for w in words)


# Page script, read line by line. A drawn test counts when it sits on a line
# that names a password field or a name the script gave the fields, or in the
# body of a loop such a line starts, or is a function of the script that such
# a line calls. A drawn test of another element elsewhere in the script,
# beside a count of every field, is not one.
_JS_FUNCTION = re.compile(
    r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\b|\([^()]*\)\s*=>|\w+\s*=>)"
    r"|\bfunction\s+(\w+)\s*\(")
# A name given to what a line finds, never to an object the line starts.
_JS_NAME = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=(?!\s*\{)\s*(.*)")
_JS_LOOP = re.compile(r"\b(?:for|while)\s*\(")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _block(lines, i) -> str:
    """Line i and the lines after it that sit deeper, a loop's body or a
    definition carried on."""
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > _indent(lines[i])):
        j += 1
    return "\n".join(lines[i:j])


def _uses(text: str, names) -> bool:
    return any(re.search(r"(?<![\w.$])%s\b" % re.escape(n), text) for n in names)


@functools.lru_cache(maxsize=None)
def _script_tests_a_drawn_field(text: str) -> bool:
    lines = text.splitlines()
    defs = []
    for i, line in enumerate(lines):
        for m in _JS_FUNCTION.finditer(line):
            defs.append((m.group(1) or m.group(2), _block(lines, i)[m.start():]))
    drawn, grew = set(), True
    while grew:
        grew = False
        for name, body in defs:
            if name not in drawn and (_says(body, SCRIPT_DRAWN) or _uses(body, drawn - {name})):
                drawn.add(name)
                grew = True
    fields = {m.group(1) for line in lines for m in [_JS_NAME.search(line)]
              if m and _says_password(m.group(2))}
    for i, line in enumerate(lines):
        if not (_says_password(line) or _uses(line, fields)):
            continue
        region = _block(lines, i) if _JS_LOOP.search(line) else line
        if _says(region, SCRIPT_DRAWN) or _uses(region, drawn):
            return True
    return False


def _bindings(nodes):
    """Name -> what was bound to it, by assignment, loop, with, walrus or
    comprehension, anywhere in these nodes."""
    out = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            out.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t in target.elts:
                bind(t, value)
        elif isinstance(target, ast.Starred):
            bind(target.value, value)

    for top in nodes:
        for n in ast.walk(top):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    bind(t, n.value)
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value is not None:
                bind(n.target, n.value)
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                bind(n.target, n.iter)
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                bind(n.optional_vars, n.context_expr)
            elif isinstance(n, ast.NamedExpr):
                bind(n.target, n.value)
    return out


def _call_name(call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _script_args(call):
    """The arguments of a page script call that hold the script."""
    at = SCRIPT_CALLS.get(_call_name(call))
    if at is None:
        return []
    out = [call.args[at]] if len(call.args) > at else []
    return out + [k.value for k in call.keywords if k.arg in SCRIPT_KEYWORDS]


_BODIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _statements(body):
    """Every statement of a body, its nested blocks included, the bodies of
    functions and classes defined in it not."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, _BODIES):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _statements(getattr(stmt, field, None) or [])
        for h in getattr(stmt, "handlers", None) or []:
            yield from _statements(h.body)
        for c in getattr(stmt, "cases", None) or []:
            yield from _statements(c.body)


def _own(stmt):
    """The expressions a statement holds itself, not those of the statements
    in its blocks."""
    if isinstance(stmt, (ast.If, ast.While)):
        return [stmt.test]
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return [stmt.target, stmt.iter]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [i.context_expr for i in stmt.items]
    if isinstance(stmt, _BODIES):
        return list(stmt.decorator_list)
    if isinstance(stmt, ast.Match):
        return [stmt.subject]
    if hasattr(stmt, "handlers"):
        return [h.type for h in stmt.handlers if h.type is not None]
    return [stmt]


def _params(fn):
    """A function's or lambda's parameters, the positional ones in order."""
    if fn is None:
        return []
    a = fn.args
    return ([x.arg for x in a.posonlyargs + a.args]
            + [x.arg for x in a.kwonlyargs]
            + [x.arg for x in (a.vararg, a.kwarg) if x is not None])


class _NameIs:
    """A leaf that takes one name, equal to another for the same name so the
    module's record of names read keeps one entry for it."""

    def __init__(self, name):
        self.name = name

    def __call__(self, n) -> bool:
        return isinstance(n, ast.Name) and n.id == self.name

    def __eq__(self, other):
        return isinstance(other, _NameIs) and other.name == self.name

    def __hash__(self):
        return hash(("_NameIs", self.name))


class _Module:
    def __init__(self, tree):
        self.tree = tree
        self.every, self.docs, functions = [], set(), []
        for n in ast.walk(tree):
            self.every.append(n)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                self.docs.add(id(n.value))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(n)
        self.units = [("<module>", None, list(_statements(tree.body)))]
        self.units += [(fn.name, fn, list(_statements(fn.body))) for fn in functions]
        self._names = None
        self._scopes = {}
        self._known = {}

    @property
    def names(self):
        if self._names is None:
            self._names = _bindings([s for s in self.tree.body if not isinstance(s, _BODIES)])
        return self._names

    def scope(self, fn):
        """What the names of a function were bound to in it, read once and
        only when asked."""
        if id(fn) not in self._scopes:
            self._scopes[id(fn)] = {} if fn is None else _bindings(fn.body)
        return self._scopes[id(fn)]

    def involves(self, expr, scope, leaf, skip=frozenset()) -> bool:
        """Whether expr, or what a name in it was bound to, has a part leaf
        takes. Parts in skip are left out."""
        todo = [expr]
        while todo:
            n = todo.pop()
            if n is None or id(n) in skip:
                continue
            if leaf(n):
                return True
            if isinstance(n, ast.Name) and self._name_involves(n.id, scope, leaf):
                return True
            todo.extend(c for c in ast.iter_child_nodes(n) if id(c) not in skip)
        return False

    def reaches(self, expr, scope, names) -> set:
        """Which of names expr uses, itself or through what was bound to a
        name in it."""
        return {p for p in names
                if self.involves(expr, scope, _NameIs(p))}

    def _name_involves(self, name, scope, leaf) -> bool:
        # Kept per name, scope and leaf, the leaf held in the key so its id
        # is never reused. A name met again while it is being read counts as
        # not involved, which ends a loop of names.
        key = (id(scope), name, leaf)
        if key not in self._known:
            self._known[key] = False
            self._known[key] = any(self.involves(b, scope, leaf)
                                   for b in scope.get(name, []) + self.names.get(name, []))
        return self._known[key]

    def string(self, n) -> str:
        """A string a module writes, never a docstring."""
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in self.docs:
            return n.value
        return ""

    def password(self, n) -> bool:
        if isinstance(n, ast.Name):
            return _says_password(n.id)
        if isinstance(n, ast.Attribute):
            return _says_password(n.attr)
        return _says_password(self.string(n))

    def selector_drawn(self, n) -> bool:
        return _says(self.string(n), SELECTOR_DRAWN)

    def script_drawn(self, n) -> bool:
        return _says(self.string(n), SCRIPT_DRAWN)


def _drawn_call(call):
    """The drawn form a call is, or None."""
    name = _call_name(call)
    keywords = {k.arg: k.value for k in call.keywords if k.arg}
    if name in DRAWN_CALLS:
        return name + "()"
    if "visible" in keywords:
        return "%s(visible=...)" % name
    if name == "get_by_role":
        shown = keywords.get("include_hidden")
        if not (isinstance(shown, ast.Constant) and shown.value is True):
            return "get_by_role(), which leaves hidden elements out"
        return None
    if name in WAIT_CALLS:
        state = keywords.get("state")
        if state is None and name == "wait_for_element_state" and call.args:
            state = call.args[0]
        if state is None:
            return "%s(), which waits for a drawn element" % name
        if not isinstance(state, ast.Constant):
            return "%s(state=<a name>)" % name
        return "%s(state=%r)" % (name, state.value) if state.value in DRAWN_STATES else None
    if name in KEYWORD_CALLS and any(k.arg is None for k in call.keywords):
        return "%s(**...)" % name
    return None


def _helper(fn_params, asks, mod, scope):
    """(form, parameters in order, the parameters a drawn test uses) of a
    function or lambda whose drawn test asks about what it is handed, or
    None."""
    for call, form in asks:
        used = mod.reaches(call, scope, fn_params)
        if used:
            return form, fn_params, used
    return None


def _hands_a_field_to(call, helper, mod, scope) -> bool:
    """Whether a call hands a password field to a parameter the helper's
    drawn test uses."""
    _, order, used = helper
    if order and order[0] in ("self", "cls") and isinstance(call.func, ast.Attribute):
        order = order[1:]
    for i, a in enumerate(call.args):
        at = order[i] if i < len(order) and not isinstance(a, ast.Starred) else None
        if (at in used or at is None) and mod.involves(a, scope, mod.password):
            return True
    return any((k.arg in used or k.arg is None) and mod.involves(k.value, scope, mod.password)
               for k in call.keywords)


def drawn_checks(tree, mod=None):
    """[(line, function, form)] for every place a module tells a drawn
    password field from one the page keeps out of sight."""
    mod = mod or _Module(tree)
    # Every way below needs a password field, or the recorder's drawn
    # selector, named somewhere in the module.
    if not any(mod.password(n) for n in mod.every):
        return []
    hits, helpers = [], {}
    for n in mod.every:
        if (isinstance(n, ast.Name) and n.id == DRAWN_CONSTANT
                or isinstance(n, ast.Attribute) and n.attr == DRAWN_CONSTANT
                or mod.string(n) == DRAWN_CONSTANT
                or isinstance(n, ast.alias) and DRAWN_CONSTANT in (n.name, n.asname)):
            hits.append((getattr(n, "lineno", 0), "<module>", "the recorder's " + DRAWN_CONSTANT))
    selectors = any(mod.selector_drawn(n) for n in mod.every)
    for fn_name, fn, stmts in mod.units:
        params = _params(fn)
        for stmt in stmts:
            exprs = [e for e in _own(stmt) if e is not None]
            nodes = [n for e in exprs for n in ast.walk(e)]
            for n in nodes:
                text = mod.string(n)
                if text and _says_password(text) and _script_tests_a_drawn_field(text):
                    hits.append((n.lineno, fn_name, "page script that tests a field is drawn"))
            calls = [n for n in nodes if isinstance(n, ast.Call)]
            scripts = [(c, _script_args(c)) for c in calls if _script_args(c)]
            asks = [(c, _drawn_call(c)) for c in calls if not _script_args(c)]
            asks = [(c, form) for c, form in asks if form]
            if not (scripts or asks or selectors):
                continue
            scope = mod.scope(fn)
            for call, at_script in scripts:
                on = [a for a in [call.func] + call.args + [k.value for k in call.keywords]
                      if all(a is not s for s in at_script)]
                if (any(mod.involves(s, scope, mod.script_drawn) for s in at_script)
                        and any(mod.involves(a, scope, mod.password) for a in on)):
                    hits.append((call.lineno, fn_name, "%s() run on a password field" % _call_name(call)))
            drawn_selector = selectors and any(mod.involves(e, scope, mod.selector_drawn)
                                               for e in exprs)
            if not (asks or drawn_selector):
                continue
            skip = frozenset(id(s) for _, at_script in scripts for s in at_script)
            named = any(mod.involves(e, scope, mod.password, skip) for e in exprs)
            if named and drawn_selector:
                hits.append((stmt.lineno, fn_name, "a selector that keeps drawn fields"))
            if named:
                hits.extend((call.lineno, fn_name, form) for call, form in asks)
                continue
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Lambda):
                found = _helper(_params(stmt.value), asks, mod, scope)
                for t in stmt.targets if found else []:
                    if isinstance(t, ast.Name):
                        helpers.setdefault(t.id, []).append(found)
            found = params and _helper(params, asks, mod, scope)
            if found:
                helpers.setdefault(fn_name, []).append(found)
    # A helper that asks about what it is handed, handed a password field.
    for fn_name, fn, stmts in mod.units if helpers else []:
        for stmt in stmts:
            for e in _own(stmt):
                for call in [c for c in ast.walk(e) if isinstance(c, ast.Call)] if e else []:
                    for helper in helpers.get(_call_name(call), []):
                        if _hands_a_field_to(call, helper, mod, mod.scope(fn)):
                            hits.append((call.lineno, fn_name, "%s(), which asks %s"
                                         % (_call_name(call), helper[0])))
    return sorted(set(hits))


def _sets_password_field(tree, nodes=None) -> bool:
    """Whether a module gives PASSWORD_FIELD a value in any way, an
    assignment of any kind, an import under that name or a setattr."""
    for n in ast.walk(tree) if nodes is None else nodes:
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            targets = [n.target]
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            if any((a.asname or a.name).rsplit(".", 1)[-1] == "PASSWORD_FIELD" for a in n.names):
                return True
            continue
        elif isinstance(n, ast.Call) and _call_name(n) in ("setattr", "__setitem__"):
            if any(isinstance(a, ast.Constant) and a.value == "PASSWORD_FIELD" for a in n.args):
                return True
            continue
        else:
            continue
        for t in targets:
            for x in ast.walk(t):
                if (isinstance(x, ast.Name) and x.id == "PASSWORD_FIELD"
                        or isinstance(x, ast.Attribute) and x.attr == "PASSWORD_FIELD"
                        or isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant)
                        and x.slice.value == "PASSWORD_FIELD"):
                    return True
    return False


def _counts_only_drawn(tree) -> bool:
    """A password check that keeps only what the page draws."""
    return bool(drawn_checks(tree))


@functools.lru_cache(maxsize=None)
def census():
    """app -> ((module, line, function, form), ...) of every drawn-only
    check, and of setting PASSWORD_FIELD. A module that never names a
    password field is not parsed, since nothing below could find one in it."""
    found = {}
    for path in MODULES:
        text = path.read_text(encoding="utf-8")
        if not _says_password(text):
            continue
        tree = ast.parse(text)
        mod = _Module(tree)
        hits = [(path.name, line, fn, form) for line, fn, form in drawn_checks(tree, mod)]
        if _sets_password_field(tree, mod.every):
            hits.append((path.name, 0, "<module>", "PASSWORD_FIELD"))
        if hits:
            found.setdefault(path.parent.name, []).extend(hits)
    return {app: tuple(hits) for app, hits in found.items()}


def _not_allowed(found):
    """What each app was found doing that ALLOWED does not name, as many
    times as it names it and no more."""
    out = {}
    for app, hits in found.items():
        room = {(a, fn, form): n for (a, fn, form), (n, _) in ALLOWED.items() if a == app}
        for hit in hits:
            key = (app, hit[2], hit[3])
            if room.get(key, 0) > 0:
                room[key] -= 1
            else:
                out.setdefault(app, []).append(hit)
    return out


## The census ###############################################################

def test_only_a_named_app_counts_only_the_password_fields_a_page_draws():
    left = _not_allowed(census())
    assert set(left) == set(NAMED), (
        "counting only drawn password fields needs a reason here, as #178 gave Consorsbank. "
        "Found %s, named %s" % ({a: h for a, h in left.items() if a not in NAMED}, sorted(NAMED)))


def test_every_allowed_check_is_still_there_as_often_as_it_is_allowed():
    found = census()
    for (app, fn, form), (n, _) in ALLOWED.items():
        there = [h for h in found.get(app, ()) if (h[2], h[3]) == (fn, form)]
        assert len(there) == n, (app, fn, form, there)


def test_an_allowed_app_still_counts_every_field_of_the_page_itself():
    """The allowance is for one check beside the page's own count, never in
    place of it."""
    for app, fn, _ in ALLOWED:
        tree = ast.parse((REPO / "apps" / app / ("%s_site.py" % app)).read_text(encoding="utf-8"))
        [check] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn]
        counts = [n for n in ast.walk(check) if isinstance(n, ast.Call) and _call_name(n) == "count"
                  and isinstance(n.func.value, ast.Call) and _call_name(n.func.value) == "locator"
                  and isinstance(n.func.value.func.value, ast.Name)
                  and n.func.value.func.value.id == "page"
                  and [a.value for a in n.func.value.args if isinstance(a, ast.Constant)]
                  == [recorder.PASSWORD_FIELD]]
        assert counts, "%s.%s no longer counts every password field of the page" % (app, fn)


def test_a_named_app_sets_the_one_value_the_core_takes():
    for app in NAMED:
        tree = ast.parse((REPO / "apps" / app / ("%s_site.py" % app)).read_text(encoding="utf-8"))
        assert _password_field(tree) == recorder.DRAWN_PASSWORD_FIELD, app


def test_a_named_apps_own_check_counts_the_same_fields_the_recorder_does():
    """Its looks_signed_out reads PASSWORD_FIELD, so the app and the
    recorder never disagree about which fields make a sign-in page."""
    for app in NAMED:
        path = REPO / "apps" / app / ("%s_site.py" % app)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        [fn] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "looks_signed_out"]
        assert any(isinstance(n, ast.Name) and n.id == "PASSWORD_FIELD" for n in ast.walk(fn)), app
        # A selector, not the docstring's words.
        literals = [n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and "password" in n.value and "[type" in n.value]
        assert not literals, "%s counts a password selector of its own: %s" % (app, literals)


def test_no_app_keeps_code_below_its_own_folder():
    """The census reads apps/*/*.py, so code one folder deeper would be
    read by nobody."""
    deeper = sorted(str(p.relative_to(REPO)) for app in REPO.glob("apps/*/") if app.is_dir()
                    for sub in app.iterdir() if sub.is_dir() and sub.name not in NOT_CODE
                    for p in sub.rglob("*.py"))
    assert not deeper, deeper


def test_the_census_finds_an_app_that_counts_only_drawn_fields():
    tree = ast.parse('def f(page):\n    return page.locator("input[type=\'password\']:visible").count()\n')
    assert _counts_only_drawn(tree)
    assert _password_field(ast.parse('PASSWORD_FIELD = "x"\n')) == "x"
    assert not _counts_only_drawn(ast.parse('S = "input[type=\'password\']"\n'))


## Each way of counting only drawn fields, as a small module ################
# Every name and selector here is invented.

_PW = '''PW = "input[type='password']"\n\n'''

_SHOWN_IN_A_SCRIPT = '''STATE_JS = r"""() => {
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  return {password: [...document.querySelectorAll("input[type='password']")].some(shown)};
}"""


def f(page):
    return page.evaluate(STATE_JS)["password"]
'''

_LOOP_IN_A_SCRIPT = '''STATE_JS = r"""() => {
  const shown = el => !!(el.offsetWidth || el.offsetHeight);
  for (const el of document.querySelectorAll("input[type='password']")) {
    if (shown(el)) return true;
  }
  return false;
}"""


def f(page):
    return page.evaluate(STATE_JS)
'''

_NAME_IN_A_SCRIPT = '''STATE_JS = r"""() => {
  const fields = document.querySelectorAll("input[type='password']");
  return Array.from(fields).some(e => e.getClientRects().length > 0);
}"""


def f(page):
    return page.evaluate(STATE_JS)
'''

DRAWN_FORMS = {
    "a :visible selector":
        '''def f(page):\n    return page.locator("input[type='password']:visible").count() > 0\n''',
    "a :VISIBLE selector":
        '''def f(page):\n    return page.locator("input[type='password']:VISIBLE").count() > 0\n''',
    "a :not(:visible) selector":
        '''def f(page):\n    return page.locator("input[type='password']:not(:visible)").count() == 0\n''',
    "the visible=true selector engine":
        '''def f(page):\n    return page.locator("input[type='password'] >> visible=true").count() > 0\n''',
    ":visible added to a constant":
        _PW + '''def f(page):\n    return page.locator(PW + ":visible").count() > 0\n''',
    ":visible in an f-string":
        _PW + '''def f(page):\n    return page.locator(f"{PW}:visible").count() > 0\n''',
    ":visible by %":
        _PW + '''def f(page):\n    return page.locator("%s:visible" % PW).count() > 0\n''',
    ":visible by format()":
        _PW + '''def f(page):\n    return page.locator("{}:visible".format(PW)).count() > 0\n''',
    "visible=true joined on":
        _PW + '''def f(page):\n    return page.locator(" >> ".join([PW, "visible=true"])).count() > 0\n''',
    ":visible in a constant made from another":
        _PW + '''DRAWN = PW + ":visible"\n\n\ndef f(page):\n    return page.locator(DRAWN).count() > 0\n''',
    ":visible kept in a constant of its own":
        _PW + '''ONLY_DRAWN = ":visible"\n\n\ndef f(page):\n'''
              '''    return page.locator(PW + ONLY_DRAWN).count() > 0\n''',
    "is_visible() of a locator":
        '''def f(page):\n    return page.locator("input[type='password']").first.is_visible()\n''',
    "is_visible() through a constant":
        _PW + '''def f(page):\n    return page.locator(PW).is_visible()\n''',
    "is_visible() through a local name":
        '''def f(page):\n    field = page.locator("input[type='password']")\n    return field.is_visible()\n''',
    "is_visible() through a frame, as Apple Card's":
        '''def f(page):\n    for frame in page.frames:\n'''
        '''        fields = frame.locator("input[type='password'], #account")\n'''
        '''        for i in range(fields.count()):\n            if fields.nth(i).is_visible():\n'''
        '''                return True\n    return False\n''',
    "is_visible() of a selector kept in a dict":
        '''FALLBACK = {"password_field": "input[name=pin]"}\n\n\ndef f(page):\n'''
        '''    return page.locator(FALLBACK["password_field"]).is_visible()\n''',
    "is_visible() in a loop":
        _PW + '''def f(page):\n    for el in page.locator(PW).all():\n        if el.is_visible():\n'''
              '''            return True\n    return False\n''',
    "is_visible() in a comprehension":
        _PW + '''def f(page):\n    return any(e.is_visible() for e in page.query_selector_all(PW))\n''',
    "is_visible() in a lambda":
        _PW + '''def f(page):\n    return any(map(lambda e: e.is_visible(), page.locator(PW).all()))\n''',
    "is_visible() awaited":
        _PW + '''async def f(page):\n    return await page.locator(PW).is_visible()\n''',
    "is_visible() of the page":
        '''def f(page):\n    return page.is_visible("input[type='password']")\n''',
    "is_visible() of another module's constant":
        '''import a_site\n\n\ndef f(page):\n    return page.locator(a_site.PASSWORD_FIELD).is_visible()\n''',
    "is_visible() of a label":
        '''def f(page):\n    return page.get_by_label("Password").is_visible()\n''',
    "is_visible() of a form that holds the field":
        '''def f(page):\n    return page.locator("form:has(input[type='password'])").is_visible()\n''',
    "is_hidden()":
        _PW + '''def f(page):\n    return not page.locator(PW).is_hidden()\n''',
    "bounding_box()":
        _PW + '''def f(page):\n    return page.locator(PW).bounding_box() is not None\n''',
    "filter(visible=True)":
        _PW + '''def f(page):\n    return page.locator(PW).filter(visible=True).count() > 0\n''',
    "filter(visible=False)":
        _PW + '''def f(page):\n    return page.locator(PW).filter(visible=False).count() == 0\n''',
    "filter(visible=) through a name":
        _PW + '''SHOWN = True\n\n\ndef f(page):\n    return page.locator(PW).filter(visible=SHOWN).count() > 0\n''',
    "filter(**keywords)":
        _PW + '''def f(page):\n    return page.locator(PW).filter(**{"visible": True}).count() > 0\n''',
    "filter(visible=True) in a frame":
        _PW + '''def f(page):\n    return page.frame_locator("iframe").locator(PW).filter(visible=True).count() > 0\n''',
    "get_by_role(), which leaves hidden fields out":
        '''import re\n\n\ndef f(page):\n'''
        '''    return page.get_by_role("textbox", name=re.compile("password", re.I)).count() > 0\n''',
    "wait_for(state='visible')":
        _PW + '''def f(page):\n    page.locator(PW).wait_for(state="visible", timeout=500)\n    return True\n''',
    "wait_for(state=) through a name":
        _PW + '''STATE = "visible"\n\n\ndef f(page):\n    page.locator(PW).wait_for(state=STATE)\n    return True\n''',
    "wait_for(), which waits for a drawn field":
        _PW + '''def f(page):\n    page.locator(PW).wait_for(timeout=500)\n    return True\n''',
    "wait_for(**options)":
        _PW + '''def f(page):\n    opts = {"state": "visible"}\n    page.locator(PW).wait_for(**opts)\n    return True\n''',
    "wait_for_selector(), which waits for a drawn field":
        _PW + '''def f(page):\n    return page.wait_for_selector(PW, timeout=500) is not None\n''',
    "wait_for_selector(state='hidden')":
        _PW + '''def f(page):\n    page.wait_for_selector(PW, state="hidden", timeout=500)\n    return False\n''',
    "wait_for_element_state('visible')":
        _PW + '''def f(page):\n    page.query_selector(PW).wait_for_element_state("visible")\n    return True\n''',
    "expect().to_be_visible()":
        '''from playwright.sync_api import expect\n\n''' + _PW +
        '''def f(page):\n    expect(page.locator(PW)).to_be_visible()\n''',
    "a helper that asks is_visible() of what it is given":
        _PW + '''def _drawn(page, selector):\n    return page.locator(selector).is_visible()\n\n\n'''
              '''def f(page):\n    return _drawn(page, PW)\n''',
    "a helper handed the field's locator":
        _PW + '''def _drawn(loc):\n    return loc.is_visible()\n\n\n'''
              '''def f(page):\n    return _drawn(page.locator(PW))\n''',
    "a lambda helper handed the field's locator":
        _PW + '''drawn = lambda loc: loc.is_visible()  # noqa: E731\n\n\n'''
              '''def f(page):\n    return drawn(page.locator(PW))\n''',
    "the recorder's drawn selector":
        '''from paperpull_core import recorder\n\n\ndef f(page):\n'''
        '''    return page.locator(recorder.DRAWN_PASSWORD_FIELD).count() > 0\n''',
    "the recorder's drawn selector imported":
        '''from paperpull_core.recorder import DRAWN_PASSWORD_FIELD\n\n\ndef f(page):\n'''
        '''    return page.locator(DRAWN_PASSWORD_FIELD).count() > 0\n''',
    "page script that tests drawing on the field's line":
        '''def f(page):\n    return page.evaluate("() => [...document.querySelectorAll('input[type=password]')]'''
        '''.some(e => e.offsetParent)")\n''',
    "page script that hands the field to a drawn test":
        _SHOWN_IN_A_SCRIPT,
    "page script that tests the field in a loop":
        _LOOP_IN_A_SCRIPT,
    "page script that names the fields, then tests them":
        _NAME_IN_A_SCRIPT,
    "page script run on the password field":
        _PW + '''def f(page):\n    return page.locator(PW).evaluate_all("els => els.some(e => e.checkVisibility())")\n''',
    "page script run on a selector":
        _PW + '''def f(page):\n    return page.eval_on_selector_all(PW, "els => els.filter(e => e.offsetParent).length") > 0\n''',
    "page script handed the selector":
        _PW + '''def f(page):\n    return page.evaluate("s => [...document.querySelectorAll(s)]'''
              '''.some(e => e.checkVisibility())", PW)\n''',
}

# Ways to set PASSWORD_FIELD that the census must see, though only a top
# level assignment holds a value test_a_named_app_sets_the_one_value_the_core_takes reads.
SETS_PASSWORD_FIELD = {
    "an assignment": '''PASSWORD_FIELD = "input[type='password']"\n''',
    "an annotated assignment": '''PASSWORD_FIELD: str = "input[type='password']:visible"\n''',
    "an assignment under a condition":
        '''import os\n\nif os.name:\n    PASSWORD_FIELD = "input[type='password']:visible"\n''',
    "an assignment of several": '''PASSWORD_FIELD, OTHER = "input[type='password']:visible", 1\n''',
    "an import under that name":
        '''from paperpull_core.recorder import DRAWN_PASSWORD_FIELD as PASSWORD_FIELD  # noqa: F401\n''',
    "an assignment to another module": '''import a_site\n\na_site.PASSWORD_FIELD = "x"\n''',
    "globals()": '''globals()["PASSWORD_FIELD"] = "x"\n''',
    "setattr()": '''import a_site\n\nsetattr(a_site, "PASSWORD_FIELD", "x")\n''',
}

# What counts every password field, and must not be taken for a drawn-only
# check, beside drawn tests of other things as today's apps have them.
EVERY_FIELD = {
    "a count of every field":
        '''def f(page):\n    return page.locator("input[type='password']").count() > 0\n''',
    "a docstring that names a drawn selector":
        '''def f(page):\n    """Not input[type='password']:visible, every field."""\n'''
        '''    return page.locator("input[type='password']").count() > 0\n''',
    "a drawn test of another element beside it":
        _PW + '''def f(page):\n    if page.locator(PW).count() > 0:\n        return True\n'''
              '''    return not page.locator("h1").first.is_visible()\n''',
    "a :visible selector of another element in the module":
        _PW + '''def f(page):\n    if page.locator(PW).count() > 0:\n        return True\n'''
              '''    return page.locator("a.tour:visible").count() == 0\n''',
    "a key that says visible over a count of every field":
        _PW + '''def f(page):\n    out = {}\n    out["visible_password_fields"] = page.locator(PW).count()\n'''
              '''    return out\n''',
    "a wait for an attached field":
        _PW + '''def f(page):\n    page.locator(PW).first.wait_for(state="attached", timeout=500)\n    return True\n''',
    "get_by_role() asked for hidden fields too":
        '''def f(page):\n'''
        '''    return page.get_by_role("textbox", name="Password", include_hidden=True).count() > 0\n''',
    "get_by_label(), which counts hidden fields":
        '''def f(page):\n    return page.get_by_label("Password").count() > 0\n''',
    "is_enabled() of the field":
        _PW + '''def f(page):\n    return page.locator(PW).first.is_enabled()\n''',
    "page script that counts every field beside drawn tests of others":
        '''STATE_JS = r"""() => {
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const signinDrawn = () => Array.from(document.querySelectorAll('button')).some(shown);
  const out = {rows: [], password: !!document.querySelector("input[type='password']"),
               signin: signinDrawn()};
  for (const tr of document.querySelectorAll('tr')) out.rows.push({shown: shown(tr)});
  return out;
}"""


def f(page):
    return bool(page.evaluate(STATE_JS)["password"])
''',
    "the recorder's strict selector":
        '''from paperpull_core import recorder\n\n\ndef f(page):\n'''
        '''    return page.locator(recorder.PASSWORD_FIELD).count() > 0\n''',
}


@pytest.mark.parametrize("name", sorted(DRAWN_FORMS))
def test_the_census_finds_each_way_of_counting_only_drawn_fields(name):
    assert _counts_only_drawn(ast.parse(DRAWN_FORMS[name])), name


@pytest.mark.parametrize("name", sorted(SETS_PASSWORD_FIELD))
def test_the_census_finds_each_way_of_setting_password_field(name):
    assert _sets_password_field(ast.parse(SETS_PASSWORD_FIELD[name])), name


@pytest.mark.parametrize("name", sorted(EVERY_FIELD))
def test_the_census_leaves_a_count_of_every_field_alone(name):
    tree = ast.parse(EVERY_FIELD[name])
    assert not _counts_only_drawn(tree), (name, drawn_checks(tree))
    assert not _sets_password_field(tree), name


def test_a_check_is_found_in_its_own_function():
    """So ALLOWED can name one place and leave the rest of a module held."""
    tree = ast.parse(DRAWN_FORMS["is_visible() through a frame, as Apple Card's"])
    assert [(fn, form) for _, fn, form in drawn_checks(tree)] == [("f", "is_visible()")]
