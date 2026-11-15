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
:visible, the visible= engine or a CSS test of hiding. Playwright's
is_visible, is_hidden, bounding_box, filter(visible=), get_by_role for a
text box (which leaves hidden elements out unless asked), a wait for a drawn
or hidden state (a wait's default is drawn), and expect's checks of the
same. The recorder's DRAWN_PASSWORD_FIELD, and setting PASSWORD_FIELD at
all. Page script is read the other way round. A password selector in it may
only be counted, by !!querySelector, querySelector against null or
querySelectorAll's length, itself or through a name the script gives it. Any
other use, in a script that tests drawing anywhere or is joined to one that
does, is a drawn-only check. The field may be named in the statement itself,
through what the module, the function or a function around it bound to a
name or gave a parameter as its default, through a constant of another
module of the same app, or by a helper of the module, or a helper of that
helper, that is handed one.

What it does not follow, and a review still reads for (NOT_FOLLOWED holds
each as a test that is expected to fail). A field named only as a PIN or by
an id with no password word in it, a name kept on self or on a class, a
helper in another module or in the core, and names reused within one
function for different things, which are read as all of them at once.

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

# A drawn-only check that is not the count of the page's own password
# fields, allowed as the one call it is, in its module and function, as many
# times as it is there. Each allowed check stands beside the page's own
# count, which decides alone
# (test_an_allowed_app_still_counts_every_field_of_the_page_itself).
# (app, module, function, the call as written): (how many, reason)
ALLOWED = {
    ("applecard", "applecard_site.py", "looks_signed_out", "fields.nth(i).is_visible()"): (
        1, "Apple's sign-in is a frame from its own host laid over card.apple.com. The page's "
           "own password fields are all counted. In that frame only a drawn field counts, "
           "since a signed-in page may keep the frame (a guess in applecard_site.py, never "
           "measured). Neither the app's page count nor the recorder reads a frame at all, "
           "so this adds a sign-out answer and takes none away "
           "(test_apple_cards_allowed_check_reads_only_its_sign_in_frames)."),
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

PASSWORD_WORDS = ("password", "passwort", "kennwort", "passwd", "pwd")

# Selector text that keeps only drawn elements, or leaves hidden ones out,
# read with spaces taken out and in any case.
SELECTOR_DRAWN = (":visible", "visible=true", "visible=false", ":not([hidden", "[hidden]",
                  "display:none", "visibility:hidden")

# Page script that asks whether an element is drawn.
SCRIPT_DRAWN = ("offsetparent", "offsetwidth", "offsetheight", "clientwidth", "clientheight",
                "getboundingclientrect", "getclientrects", "checkvisibility",
                "getcomputedstyle", "intersectionobserver", "style.display", "style.visibility",
                ".hidden", "[hidden]")
# What tells page script from a selector.
SCRIPT_MARKS = ("=>", "function", "document", "queryselector", "return ")

# Playwright calls that ask whether something is drawn.
DRAWN_CALLS = {"is_visible", "is_hidden", "bounding_box", "to_be_visible", "not_to_be_visible",
               "to_be_hidden", "not_to_be_hidden", "to_be_in_viewport", "not_to_be_in_viewport"}
# Waits whose state, or whose default state, is drawn or not drawn.
WAIT_CALLS = {"wait_for", "wait_for_selector", "wait_for_element_state"}
DRAWN_STATES = {"visible", "hidden"}
# Calls whose keywords, handed over as **, may keep only drawn elements.
KEYWORD_CALLS = {"filter", "locator", "get_by_role"}
# The roles a password field can be found by.
FIELD_ROLES = {"textbox"}
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


def _is_script(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in SCRIPT_MARKS)


# Page script. The quoted strings in it that name a password field, and
# whether each is only counted.
_JS_STRING = re.compile(r'''"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`''')
_JS_FIELD = re.compile(r"input|\[|type|autocomplete", re.I)
_JS_QUERY_BEFORE = re.compile(r"[\w$.\])]*\.querySelector(All)?\(\s*$")
_JS_NAME_BEFORE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*$")
_JS_STATEMENT_ENDS = re.compile(r"\s*\)?\s*;?[ \t]*(?:\n|$)")


def _names_a_field(body: str) -> bool:
    return _says_password(body) and bool(_JS_FIELD.search(body)
                                          or body.strip().lower() in PASSWORD_WORDS)


def _uses_after(text: str, name: str, at: int):
    """Where a name stands after at, spread with ... included, a property of
    the same name not."""
    for m in re.finditer(r"(?:(?<=\.\.\.)|(?<![\w$.]))%s\b" % re.escape(name), text[at:]):
        yield at + m.start(), at + m.end()


def _only_counted(text: str, s: int, e: int, depth: int = 0) -> bool:
    """Whether what stands at text[s:e], a password selector or a name the
    script gave one, is only counted where it is used."""
    if depth > 4:
        return False
    before, after = text[max(0, s - 120):s], text[e:e + 60]
    query = _JS_QUERY_BEFORE.search(before)
    if not query:
        return False
    head = before[:query.start()]
    named = _JS_NAME_BEFORE.search(head)
    if named and _JS_STATEMENT_ENDS.match(after):
        # The list or the element is given a name. Each use of it decides.
        rest = [(a, b) for a, b in _uses_after(text, named.group(1), e)]
        if query.group(1):
            return all(re.match(r"\s*\.length\b", text[b:]) for a, b in rest)
        return all(re.search(r"!!\s*$", text[:a]) or re.match(r"\s*(?:!==?|===?)\s*null\b", text[b:])
                   for a, b in rest)
    if query.group(1):
        return bool(re.match(r"\s*\)\s*\.length\b", after))
    return bool(re.search(r"(?:!!|Boolean\()\s*$", head)
                or re.match(r"\s*\)\s*(?:!==?|===?)\s*null\b", after))


@functools.lru_cache(maxsize=None)
def _script_reads_a_field(text: str) -> str:
    """'drawn' when page script names a password field by a selector that
    keeps drawn fields, 'used' when it uses one beyond counting it, '' when
    every one is only counted."""
    used = ""
    for m in _JS_STRING.finditer(text):
        body = m.group(0)[1:-1]
        if not _names_a_field(body):
            continue
        if _says(body, SELECTOR_DRAWN):
            return "drawn"
        s, e = m.start(), m.end()
        named = _JS_NAME_BEFORE.search(text[max(0, s - 80):s])
        if named and _JS_STATEMENT_ENDS.match(text[e:e + 40]):
            # A name for the selector. Each place it is handed on decides.
            if all(_only_counted(text, a, b) for a, b in _uses_after(text, named.group(1), e)):
                continue
            used = "used"
        elif not _only_counted(text, s, e):
            used = "used"
    return used


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


def _defaults(fn):
    """A function's parameters bound to their defaults."""
    a = fn.args
    positional = a.posonlyargs + a.args
    out = {p.arg: [d] for p, d in zip(positional[len(positional) - len(a.defaults):], a.defaults)}
    out.update({p.arg: [d] for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
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


class _Signature:
    """The parameters of a function or lambda, as a call hands them over."""

    def __init__(self, fn):
        a = fn.args
        self.positional = [x.arg for x in a.posonlyargs + a.args]
        self.keyword = [x.arg for x in a.kwonlyargs]
        self.rest = a.vararg.arg if a.vararg else None
        self.more = a.kwarg.arg if a.kwarg else None

    def names(self):
        return set(self.positional + self.keyword) | {n for n in (self.rest, self.more) if n}

    def handed(self, call):
        """(argument, the parameter it lands in, or None for one that cannot
        be told) for each argument of a call."""
        positional = self.positional
        if positional and positional[0] in ("self", "cls") and isinstance(call.func, ast.Attribute):
            positional = positional[1:]
        for i, a in enumerate(call.args):
            if isinstance(a, ast.Starred):
                yield a, None
            else:
                yield a, positional[i] if i < len(positional) else self.rest
        for k in call.keywords:
            yield k.value, (k.arg if k.arg in positional or k.arg in self.keyword
                            else self.more if k.arg else None)


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
    def __init__(self, tree, others=frozenset()):
        """others, the names of constants of the app's other modules that
        name a password field."""
        self.tree, self.others = tree, others
        self.every, self.docs, functions, self.parent = [], set(), [], {}
        todo = [(tree, None)]
        while todo:
            n, fn = todo.pop()
            self.every.append(n)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                self.docs.add(id(n.value))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(n)
                self.parent[id(n)] = fn
                fn = n
            todo.extend((c, fn) for c in ast.iter_child_nodes(n))
        functions.sort(key=lambda f: f.lineno)
        self.units = [("<module>", None, list(_statements(tree.body)))]
        self.units += [(fn.name, fn, list(_statements(fn.body))) for fn in functions]
        self._names = None
        self._scopes = {}
        self._known = {}
        self._reading = set()
        self._cycle = False

    @property
    def names(self):
        if self._names is None:
            self._names = _bindings([s for s in self.tree.body if not isinstance(s, _BODIES)])
        return self._names

    def scope(self, fn):
        """What the names of a function were bound to, in it, as its
        parameters' defaults, or in a function around it. Read once and only
        when asked."""
        if id(fn) not in self._scopes:
            out, f = {}, fn
            while f is not None:
                for table in (_bindings(f.body), _defaults(f)):
                    for name, values in table.items():
                        out.setdefault(name, []).extend(values)
                f = self.parent.get(id(f))
            self._scopes[id(fn)] = out
        return self._scopes[id(fn)]

    def involves(self, expr, scope, leaf, skip=frozenset()) -> bool:
        """Whether expr, or what a name in it was bound to, has a part leaf
        takes. Parts in skip are left out. A constant key of a dict that a
        name holds reads only that key's value."""
        todo = [expr]
        while todo:
            n = todo.pop()
            if n is None or id(n) in skip:
                continue
            if leaf(n):
                return True
            if isinstance(n, ast.Name) and self._name_involves(n.id, scope, leaf):
                return True
            if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                    and isinstance(n.slice, ast.Constant)):
                held = scope.get(n.value.id, []) + self.names.get(n.value.id, [])
                if held and all(isinstance(d, ast.Dict) for d in held):
                    if leaf(n.slice):
                        return True
                    todo.extend(v for d in held for k, v in zip(d.keys, d.values)
                                if k is None or isinstance(k, ast.Constant) and k.value == n.slice.value)
                    continue
            todo.extend(c for c in ast.iter_child_nodes(n) if id(c) not in skip)
        return False

    def _name_involves(self, name, scope, leaf) -> bool:
        # Kept per name, scope and leaf, the leaf held in the key so its id
        # is never reused. A name met again while it is being read counts as
        # not involved for now, which ends a loop of names, and an answer of
        # no reached through such a loop is not kept, since the loop was not
        # read to its end.
        key = (id(scope), name, leaf)
        if key in self._known:
            return self._known[key]
        if key in self._reading:
            self._cycle = True
            return False
        self._reading.add(key)
        outer, self._cycle = self._cycle, False
        try:
            found = any(self.involves(b, scope, leaf)
                        for b in scope.get(name, []) + self.names.get(name, []))
        finally:
            self._reading.discard(key)
        if found or not self._cycle:
            self._known[key] = found
        self._cycle = outer or self._cycle
        return found

    def reaches(self, expr, scope, names) -> set:
        """Which of names expr uses, itself or through what was bound to a
        name in it."""
        return {p for p in names if self.involves(expr, scope, _NameIs(p))}

    def string(self, n) -> str:
        """A string a module writes, never a docstring."""
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in self.docs:
            return n.value
        return ""

    def password(self, n) -> bool:
        if isinstance(n, ast.Name):
            return _says_password(n.id) or n.id in self.others
        if isinstance(n, ast.Attribute):
            return _says_password(n.attr) or n.attr in self.others
        return _says_password(self.string(n))

    def selector_drawn(self, n) -> bool:
        text = self.string(n)
        return _says(text, SELECTOR_DRAWN) and not _is_script(text)

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
        role = call.args[0] if call.args else keywords.get("role")
        shown = keywords.get("include_hidden")
        if isinstance(role, ast.Constant) and role.value not in FIELD_ROLES:
            return None
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


def _asks(nodes):
    """(node, form) for each drawn question among nodes, a call, or one of
    Playwright's drawn checks taken without calling it."""
    called = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    out = []
    for n in nodes:
        if isinstance(n, ast.Call) and not _script_args(n):
            form = _drawn_call(n)
            if form:
                out.append((n, form))
        elif isinstance(n, ast.Attribute) and n.attr in DRAWN_CALLS and id(n) not in called:
            out.append((n, "%s, taken without a call" % n.attr))
    return out


def drawn_checks(tree, mod=None):
    """[(line, function, form, what)] for every place a module tells a drawn
    password field from one the page keeps out of sight. what is the call as
    written, or the form where there is no one call."""
    mod = mod or _Module(tree)
    # Every way below needs a password field, or the recorder's drawn
    # selector, named somewhere in the module.
    if not any(mod.password(n) for n in mod.every):
        return []
    hits = []
    for n in mod.every:
        if (isinstance(n, ast.Name) and n.id == DRAWN_CONSTANT
                or isinstance(n, ast.Attribute) and n.attr == DRAWN_CONSTANT
                or mod.string(n) == DRAWN_CONSTANT
                or isinstance(n, ast.alias) and DRAWN_CONSTANT in (n.name, n.asname)):
            form = "the recorder's " + DRAWN_CONSTANT
            hits.append((getattr(n, "lineno", 0), "<module>", form, form))
    selectors = any(mod.selector_drawn(n) for n in mod.every)
    helpers = {}
    for fn_name, fn, stmts in mod.units:
        signature = _Signature(fn) if fn is not None else None
        for stmt in stmts:
            exprs = [e for e in _own(stmt) if e is not None]
            nodes = [n for e in exprs for n in ast.walk(e)]
            calls = [n for n in nodes if isinstance(n, ast.Call)]
            scripts = [(c, _script_args(c)) for c in calls if _script_args(c)]
            asks = _asks(nodes)
            texts = [n for n in nodes if _says_password(mod.string(n)) and _is_script(mod.string(n))]
            if not (scripts or asks or selectors or texts):
                continue
            scope = mod.scope(fn)
            skip = frozenset(id(s) for _, at_script in scripts for s in at_script)
            # Page script that names a password field.
            for n in texts:
                read = _script_reads_a_field(mod.string(n))
                if read == "drawn" or read and any(mod.involves(e, scope, mod.script_drawn)
                                                   for e in exprs):
                    form = "page script that tests a field is drawn"
                    hits.append((n.lineno, fn_name, form, form))
            # Page script run on a password field.
            for call, at_script in scripts:
                on = [a for a in [call.func] + call.args + [k.value for k in call.keywords]
                      if all(a is not s for s in at_script)]
                if (any(mod.involves(s, scope, mod.script_drawn) for s in at_script)
                        and any(mod.involves(a, scope, mod.password) for a in on)):
                    form = "%s() run on a password field" % _call_name(call)
                    hits.append((call.lineno, fn_name, form, ast.unparse(call)))
            # A selector that keeps drawn fields, in one call, or bound or
            # returned outside any call.
            if selectors:
                form = "a selector that keeps drawn fields"
                both = [c for c in calls
                        if mod.involves(c, scope, mod.password)
                        and mod.involves(c, scope, mod.selector_drawn)]
                hits.extend((c.lineno, fn_name, form, ast.unparse(c)) for c in both)
                outside = frozenset(id(c) for c in calls)
                if not both and any(mod.involves(e, scope, mod.password, outside) for e in exprs) \
                        and any(mod.involves(e, scope, mod.selector_drawn, outside) for e in exprs):
                    hits.append((stmt.lineno, fn_name, form, form))
            # A drawn question asked of a password field. A lambda's own
            # parameter is bound only by what the statement hands it.
            lambdas = {a for n in nodes if isinstance(n, ast.Lambda) for a in _Signature(n).names()}
            for node, form in asks:
                if lambdas and mod.reaches(node, scope, lambdas):
                    named = any(mod.involves(e, scope, mod.password, skip) for e in exprs)
                else:
                    named = mod.involves(node, scope, mod.password)
                if named:
                    hits.append((node.lineno, fn_name, form, ast.unparse(node)))
                    continue
                # Or of a parameter, which makes a helper.
                if signature is not None:
                    used = mod.reaches(node, scope, signature.names())
                    if used:
                        helpers.setdefault(fn_name, []).append((signature, used, form))
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Lambda):
                    inner = _Signature(stmt.value)
                    used = mod.reaches(node, scope, inner.names())
                    for t in stmt.targets if used else []:
                        if isinstance(t, ast.Name):
                            helpers.setdefault(t.id, []).append((inner, used, form))
    # A function that hands its own parameter to a helper's asked one is a
    # helper too, read until nothing more is found.
    seen = {(name, frozenset(used)) for name, found in helpers.items() for _, used, _ in found}
    grew = bool(helpers)
    while grew:
        grew = False
        for fn_name, fn, stmts in mod.units:
            if fn is None:
                continue
            signature, scope = _Signature(fn), mod.scope(fn)
            for stmt in stmts:
                for call in [c for e in _own(stmt) if e for c in ast.walk(e) if isinstance(c, ast.Call)]:
                    for inner, used, form in list(helpers.get(_call_name(call), [])):
                        for arg, at in inner.handed(call):
                            if at is not None and at not in used:
                                continue
                            mine = mod.reaches(arg, scope, signature.names())
                            if mine and (fn_name, frozenset(mine)) not in seen:
                                seen.add((fn_name, frozenset(mine)))
                                helpers.setdefault(fn_name, []).append(
                                    (signature, mine, "%s(), which asks %s" % (_call_name(call), form)))
                                grew = True
    # A helper handed a password field.
    for fn_name, fn, stmts in mod.units if helpers else []:
        scope = mod.scope(fn)
        for stmt in stmts:
            for call in [c for e in _own(stmt) if e for c in ast.walk(e) if isinstance(c, ast.Call)]:
                for inner, used, form in helpers.get(_call_name(call), []):
                    if any((at is None or at in used) and mod.involves(arg, scope, mod.password)
                           for arg, at in inner.handed(call)):
                        hits.append((call.lineno, fn_name, "%s(), which asks %s"
                                     % (_call_name(call), form), ast.unparse(call)))
                        break
    return sorted(set(hits))


def _sets_password_field(tree, nodes=None) -> bool:
    """Whether a module gives PASSWORD_FIELD a value in any way, an
    assignment of any kind, another name imported as it, or a setattr. The
    recorder's own strict value imported under its own name sets nothing."""
    for n in ast.walk(tree) if nodes is None else nodes:
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            targets = [n.target]
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            if any(a.asname == "PASSWORD_FIELD" and a.name.rsplit(".", 1)[-1] != "PASSWORD_FIELD"
                   for a in n.names):
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


def _password_constants(tree):
    """The module's constants, named in capitals, whose value names a
    password field, itself or through another such constant."""
    names = _bindings([s for s in tree.body if not isinstance(s, _BODIES)])
    found, grew = set(), True
    while grew:
        grew = False
        for name, values in names.items():
            if name in found or not name.isupper():
                continue
            if any(isinstance(x, ast.Constant) and isinstance(x.value, str) and _says_password(x.value)
                   or isinstance(x, ast.Name) and x.id in found
                   for v in values for x in ast.walk(v)):
                found.add(name)
                grew = True
    return found


def _app_hits(texts):
    """[(module, line, function, form, what)] of one app, its modules given
    as {file name: text}. A module that never names a password field, or a
    constant of another module of the app that does, is not parsed, since
    nothing could be found in it."""
    trees = {name: ast.parse(text) for name, text in texts.items() if _says_password(text)}
    others = set()
    for tree in trees.values():
        others |= _password_constants(tree)
    hits = []
    for name, text in sorted(texts.items()):
        tree = trees.get(name)
        if tree is None:
            if not any(re.search(r"\b%s\b" % re.escape(o), text) for o in others):
                continue
            tree = ast.parse(text)
        mod = _Module(tree, frozenset(others))
        hits += [(name, line, fn, form, what) for line, fn, form, what in drawn_checks(tree, mod)]
        if _sets_password_field(tree, mod.every):
            hits.append((name, 0, "<module>", "PASSWORD_FIELD", "PASSWORD_FIELD"))
    return hits


@functools.lru_cache(maxsize=None)
def census():
    """app -> ((module, line, function, form, what), ...) of every drawn-only
    check, and of setting PASSWORD_FIELD."""
    apps = {}
    for path in MODULES:
        apps.setdefault(path.parent.name, {})[path.name] = path.read_text(encoding="utf-8")
    found = {app: tuple(_app_hits(texts)) for app, texts in apps.items()}
    return {app: hits for app, hits in found.items() if hits}


def _not_allowed(found):
    """What each app was found doing that ALLOWED does not name, as many
    times as it names it and no more."""
    out = {}
    for app, hits in found.items():
        room = {key: n for key, (n, _) in ALLOWED.items() if key[0] == app}
        for hit in hits:
            key = (app, hit[0], hit[2], hit[4])
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
    for (app, module, fn, what), (n, _) in ALLOWED.items():
        there = [h for h in found.get(app, ()) if (h[0], h[2], h[4]) == (module, fn, what)]
        assert len(there) == n, (app, module, fn, what, there)


def _function(app, module, name):
    tree = ast.parse((REPO / "apps" / app / module).read_text(encoding="utf-8"))
    [fn] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    return fn


def _counts_the_page(test) -> bool:
    """page.locator(<every password field>).count() > 0, and nothing else."""
    return (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Gt)
            and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == 0
            and isinstance(test.left, ast.Call) and _call_name(test.left) == "count"
            and not test.left.args and isinstance(test.left.func.value, ast.Call)
            and _call_name(test.left.func.value) == "locator"
            and ast.unparse(test.left.func.value.func.value) == "page"
            and [ast.literal_eval(a) for a in test.left.func.value.args] == [recorder.PASSWORD_FIELD])


def test_an_allowed_app_still_counts_every_field_of_the_page_itself():
    """The allowance is for one check beside the page's own count, which
    decides alone, never in place of it."""
    for app, module, name, _ in ALLOWED:
        fn = _function(app, module, name)
        decides = [n for n in ast.walk(fn) if isinstance(n, ast.If) and _counts_the_page(n.test)
                   and len(n.body) == 1 and isinstance(n.body[0], ast.Return)
                   and isinstance(n.body[0].value, ast.Constant) and n.body[0].value.value is True]
        assert decides, "%s.%s no longer says signed out on any password field of the page" % (
            module, name)


@pytest.mark.parametrize("test, alone", [
    ('page.locator("input[type=\'password\']").count() > 0', True),
    ('page.locator("input[type=\'password\']").count() > 0'
     ' and page.locator("input[type=\'password\']").first.is_visible()', False),
    ('page.locator("input[type=\'password\']:visible").count() > 0', False),
    ('page.locator("input[type=\'password\']").count() > 1', False),
    ('frame.locator("input[type=\'password\']").count() > 0', False),
])
def test_the_page_count_reads_only_a_count_that_decides_alone(test, alone):
    assert _counts_the_page(ast.parse(test, mode="eval").body) is alone


def test_apple_cards_allowed_check_reads_only_its_sign_in_frames():
    """The fields it asks about are found in a frame, and only in the frames
    of the page, never in the page itself."""
    fn = _function("applecard", "applecard_site.py", "looks_signed_out")
    bound = _bindings(fn.body)
    assert bound["fields"] and all(
        isinstance(v, ast.Call) and _call_name(v) == "locator" and ast.unparse(v.func.value) == "frame"
        for v in bound["fields"]), [ast.unparse(v) for v in bound["fields"]]
    assert [ast.unparse(v) for v in bound["frame"]] == ["page.frames"]


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


def _script(js, call="page.evaluate(STATE_JS)"):
    return 'STATE_JS = r"""%s"""\n\n\ndef f(page):\n    return %s\n' % (js, call)


DRAWN_FORMS = {
    "a :visible selector":
        '''def f(page):\n    return page.locator("input[type='password']:visible").count() > 0\n''',
    "a :VISIBLE selector":
        '''def f(page):\n    return page.locator("input[type='password']:VISIBLE").count() > 0\n''',
    "a :not(:visible) selector":
        '''def f(page):\n    return page.locator("input[type='password']:not(:visible)").count() == 0\n''',
    "the visible=true selector engine":
        '''def f(page):\n    return page.locator("input[type='password'] >> visible=true").count() > 0\n''',
    "a CSS test of hiding in the selector":
        '''def f(page):\n    return page.locator("input[type='password']:not([hidden])"'''
        '''":not([style*='display: none'])").count() > 0\n''',
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
    "a password field by id":
        '''def f(page):\n    return page.locator("#pwd").is_visible()\n''',
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
    "is_visible() of a dict entry that holds the field":
        '''FALLBACK = {"login": "input[type='password']"}\n\n\ndef f(page):\n'''
        '''    return page.locator(FALLBACK["login"]).is_visible()\n''',
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
    "is_visible() in a closure over the field":
        _PW + '''def f(page):\n    fields = page.locator(PW)\n\n    def drawn():\n'''
              '''        return fields.first.is_visible()\n    return drawn()\n''',
    "is_visible() kept as a name and called":
        _PW + '''def f(page):\n    shown = page.locator(PW).first.is_visible\n    return shown()\n''',
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
    "a helper whose first question is of the page":
        _PW + '''def _drawn(page, selector):\n'''
              '''    return page.locator("#main").is_visible() and page.locator(selector).first.is_visible()\n'''
              '''\n\ndef f(page):\n    return _drawn(page, PW)\n''',
    "a helper whose default is the field":
        _PW + '''def _drawn(page, selector=PW):\n    return page.locator(selector).is_visible()\n\n\n'''
              '''def f(page):\n    return _drawn(page)\n''',
    "a helper of a helper":
        _PW + '''def _shown(loc):\n    return loc.is_visible()\n\n\n'''
              '''def _any_shown(page, selector):\n    return _shown(page.locator(selector))\n\n\n'''
              '''def f(page):\n    return _any_shown(page, PW)\n''',
    "a helper with *args after a keyword":
        _PW + '''def _drawn(page, *selectors, timeout=500):\n'''
              '''    return any(page.locator(s).is_visible(timeout=timeout) for s in selectors)\n\n\n'''
              '''def f(page):\n    return _drawn(page, PW)\n''',
    "a method helper":
        _PW + '''class Site:\n    def _drawn(self, page, selector):\n'''
              '''        return page.locator(selector).is_visible()\n\n'''
              '''    def f(self, page):\n        return self._drawn(page, PW)\n''',
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
        _script('''() => {
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  return {password: [...document.querySelectorAll("input[type='password']")].some(shown)};
}''', 'page.evaluate(STATE_JS)["password"]'),
    "page script that tests the field in a loop":
        _script('''() => {
  const shown = el => !!(el.offsetWidth || el.offsetHeight);
  for (const el of document.querySelectorAll("input[type='password']")) {
    if (shown(el)) return true;
  }
  return false;
}'''),
    "page script that names the fields, then tests them":
        _script('''() => {
  const fields = document.querySelectorAll("input[type='password']");
  return Array.from(fields).some(e => e.getClientRects().length > 0);
}'''),
    "page script with its drawn test in a callback below":
        _script('''() => {
  return [...document.querySelectorAll("input[type='password']")].some(e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
}'''),
    "page script with forEach and its body below":
        _script('''() => {
  let found = false;
  document.querySelectorAll("input[type='password']").forEach(e => {
    if (e.offsetParent !== null) found = true;
  });
  return found;
}'''),
    "page script chained on the next line":
        _script('''() => Array.from(document.querySelectorAll("input[type='password']"))
  .some(d => {
    const st = getComputedStyle(d);
    return st.visibility !== 'hidden' && st.display !== 'none';
  })'''),
    "page script that names the selector, then the list":
        _script('''() => {
  const sel = "input[type='password']";
  const els = document.querySelectorAll(sel);
  return [...els].some(e => e.offsetParent !== null);
}'''),
    "page script with a helper written flat":
        _script('''() => {
const shown = el => {
return el.offsetWidth > 0;
};
return [...document.querySelectorAll("input[type='password']")].some(shown);
}'''),
    "page script that tests style and the hidden property":
        _script('''() => [...document.querySelectorAll("input[type='password']")]
  .some(e => !e.hidden && e.style.display !== "none")'''),
    "page script with a CSS test of hiding in its selector":
        _script('''() => !!document.querySelector("input[type='password']:not([hidden])")'''),
    "page script joined to a drawn test kept apart":
        '''_SHOWN_FN = r"""
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);"""

_STATE_JS = r"""() => {%s
  return {password: [...document.querySelectorAll("input[type='password']")].some(shown)};
}""" % _SHOWN_FN


def f(page):
    return bool(page.evaluate(_STATE_JS)["password"])
''',
    "page script run on the password field":
        _PW + '''def f(page):\n    return page.locator(PW).evaluate_all("els => els.some(e => e.checkVisibility())")\n''',
    "page script run on a selector":
        _PW + '''def f(page):\n    return page.eval_on_selector_all(PW, "els => els.filter(e => e.offsetParent).length") > 0\n''',
    "page script handed the selector":
        _PW + '''def f(page):\n    return page.evaluate("s => [...document.querySelectorAll(s)]'''
              '''.some(e => e.checkVisibility())", PW)\n''',
}

# A check in one module on a constant of another module of the same app.
ACROSS_MODULES = {
    "x_site.py": '''SIGN_IN_FIELD = "input[type='password']"\n''',
    "x_docs.py": '''import x_site as site\n\n\ndef f(page):\n'''
                 '''    return page.locator(site.SIGN_IN_FIELD).first.is_visible()\n''',
}

# Ways to set PASSWORD_FIELD that the census must see, though only a top
# level assignment holds a value test_a_named_app_sets_the_one_value_the_core_takes reads.
SETS_PASSWORD_FIELD = {
    "an assignment": '''PASSWORD_FIELD = "input[type='password']"\n''',
    "an annotated assignment": '''PASSWORD_FIELD: str = "input[type='password']:visible"\n''',
    "an assignment under a condition":
        '''import os\n\nif os.name:\n    PASSWORD_FIELD = "input[type='password']:visible"\n''',
    "an assignment of several": '''PASSWORD_FIELD, OTHER = "input[type='password']:visible", 1\n''',
    "another name imported as it":
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
    "a drawn test of another element in the same statement":
        _PW + '''def f(page):\n'''
              '''    return page.locator(PW).count() > 0 or not page.locator("nav").first.is_visible()\n''',
    "a :visible selector of another element in the module":
        _PW + '''def f(page):\n    if page.locator(PW).count() > 0:\n        return True\n'''
              '''    return page.locator("a.tour:visible").count() == 0\n''',
    "a :visible selector of another element in the same statement":
        _PW + '''def f(page):\n'''
              '''    return page.locator(PW).count() > 0 or page.locator("a.tour:visible").count() == 0\n''',
    "a key that says visible over a count of every field":
        _PW + '''def f(page):\n    out = {}\n    out["visible_password_fields"] = page.locator(PW).count()\n'''
              '''    return out\n''',
    "a dict of selectors with a drawn test of another entry":
        '''FALLBACK = {"password_field": "input[type='password']", "statements": "a.statements"}\n\n\n'''
        '''def f(page):\n    if page.locator(FALLBACK["password_field"]).count() > 0:\n        return True\n'''
        '''    return not page.locator(FALLBACK["statements"]).first.is_visible()\n''',
    "a wait for an attached field":
        _PW + '''def f(page):\n    page.locator(PW).first.wait_for(state="attached", timeout=500)\n    return True\n''',
    "a wait for the page to settle":
        _PW + '''def f(page):\n    page.locator("main").wait_for(timeout=5000)\n    return page.locator(PW).count() > 0\n''',
    "get_by_role() asked for hidden fields too":
        '''def f(page):\n'''
        '''    return page.get_by_role("textbox", name="Password", include_hidden=True).count() > 0\n''',
    "get_by_role() of a link that names a password":
        '''def f(page):\n    if page.locator("input[type='password']").count() > 0:\n        return True\n'''
        '''    return page.get_by_role("link", name="Forgot your password?").count() > 0\n''',
    "get_by_label(), which counts hidden fields":
        '''def f(page):\n    return page.get_by_label("Password").count() > 0\n''',
    "is_enabled() of the field":
        _PW + '''def f(page):\n    return page.locator(PW).first.is_enabled()\n''',
    "a name reused for a role list and the fields":
        _PW + '''def summary(page):\n    out = {}\n    for role in ("link", "button"):\n'''
              '''        loc = page.get_by_role(role)\n        out[role] = loc.count()\n'''
              '''    loc = page.locator(PW)\n    out["password_fields"] = loc.count()\n    return out\n''',
    "page script that counts every field beside drawn tests of others":
        _script('''() => {
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const signinDrawn = () => Array.from(document.querySelectorAll('button')).some(shown);
  const out = {rows: [], password: !!document.querySelector("input[type='password']"),
               signin: signinDrawn()};
  for (const tr of document.querySelectorAll('tr')) out.rows.push({shown: shown(tr)});
  return out;
}''', 'bool(page.evaluate(STATE_JS)["password"])'),
    "page script that counts every field on one line with a drawn test":
        _script('''() => {
  const shown = el => !!el && !!(el.offsetWidth || el.offsetHeight);
  return {password: !!document.querySelector("input[type='password']"), signin: [...document.querySelectorAll("button")].some(shown)};
}''', 'bool(page.evaluate(STATE_JS)["password"])'),
    "page script that counts every field by length, by name and against null":
        _script('''() => {
  const shown = el => !!(el.offsetWidth || el.offsetHeight);
  const fields = document.querySelectorAll("input[type='password']");
  const one = document.querySelector("input[name=password]");
  return {n: fields.length, any: one !== null, all: document.querySelectorAll("input[type=password]").length,
          tabs: [...document.querySelectorAll('[role=tab]')].some(shown)};
}'''),
    "page script that counts every field and lists hidden rows":
        _script('''() => ({password: !!document.querySelector("input[type='password']"),
  hidden: document.querySelectorAll('tr[hidden], tr:not([hidden])').length})'''),
    "page script that reads a URL's password part":
        _script('''() => {
  const u = new URL(location.href);
  const shown = el => !!(el.offsetWidth || el.offsetHeight);
  return {user: !!u.password, rows: [...document.querySelectorAll('tr')].filter(shown).length};
}'''),
    "a selector beside page script that tests drawing":
        _PW + '''SHOWN_JS = "() => [...document.querySelectorAll('button')].some(e => e.offsetParent)"\n\n\n'''
              '''def f(page):\n    return page.locator("input[type='password']").count() > 0 and page.evaluate(SHOWN_JS)\n''',
    "the recorder's strict selector":
        '''from paperpull_core import recorder\n\n\ndef f(page):\n'''
        '''    return page.locator(recorder.PASSWORD_FIELD).count() > 0\n''',
    "the recorder's strict selector imported":
        '''from paperpull_core.recorder import PASSWORD_FIELD\n\n\ndef f(page):\n'''
        '''    return page.locator(PASSWORD_FIELD).count() > 0\n''',
}

# Ways the census does not follow, each expected to fail so a reader sees
# them, and so a census that learns one says so.
NOT_FOLLOWED = {
    "a field named only as a PIN":
        '''def f(page):\n    return page.locator("input[name='pin']:visible").count() > 0\n''',
    "a selector kept on self":
        _PW + '''class Site:\n    def __init__(self):\n        self.sel = PW\n\n'''
              '''    def f(self, page):\n        return page.locator(self.sel).is_visible()\n''',
    "a helper in another module":
        _PW + '''import helpers\n\n\ndef f(page):\n    return helpers.drawn(page, PW)\n''',
}


@pytest.mark.parametrize("name", sorted(DRAWN_FORMS))
def test_the_census_finds_each_way_of_counting_only_drawn_fields(name):
    assert _counts_only_drawn(ast.parse(DRAWN_FORMS[name])), name


def test_the_census_finds_a_check_on_a_constant_of_another_module():
    hits = _app_hits(ACROSS_MODULES)
    assert [(h[0], h[2]) for h in hits] == [("x_docs.py", "f")], hits


@pytest.mark.parametrize("name", sorted(SETS_PASSWORD_FIELD))
def test_the_census_finds_each_way_of_setting_password_field(name):
    assert _sets_password_field(ast.parse(SETS_PASSWORD_FIELD[name])), name


@pytest.mark.parametrize("name", sorted(EVERY_FIELD))
def test_the_census_leaves_a_count_of_every_field_alone(name):
    tree = ast.parse(EVERY_FIELD[name])
    assert not _counts_only_drawn(tree), (name, drawn_checks(tree))
    assert not _sets_password_field(tree), name


@pytest.mark.parametrize("name", sorted(NOT_FOLLOWED))
@pytest.mark.xfail(strict=True, reason="a way the census does not follow, see its docstring")
def test_the_census_does_not_follow(name):
    assert _counts_only_drawn(ast.parse(NOT_FOLLOWED[name])), name


def test_a_check_is_found_in_its_own_function_as_written():
    """So ALLOWED can name one call and leave the rest of a module held."""
    tree = ast.parse(DRAWN_FORMS["is_visible() through a frame, as Apple Card's"])
    assert [(fn, form, what) for _, fn, form, what in drawn_checks(tree)] == [
        ("f", "is_visible()", "fields.nth(i).is_visible()")]


def test_a_name_read_inside_a_loop_of_names_is_read_again():
    """A name met while its own reading is under way counts as no field for
    that moment only, so a second check through it is still found."""
    src = _PW + '''def f(page):
    parent = None
    node = page.locator("form")
    for _ in range(2):
        if node.first.is_visible():
            return True
        node = parent
        parent = node
        node = page.locator(PW)
    return parent.first.is_visible()
'''
    lines = [line for line, _, _, _ in drawn_checks(ast.parse(src))]
    assert lines == [7, 12], lines
