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
all.

Page script is read the other way round. A password field in it may only
be counted, querySelectorAll's length, or querySelector taken as true or
false (by !, Boolean, if, a test against null or a ternary) with nothing of
the element read after it, itself or through a name the script gives it.
Any other use, in a script that tests drawing anywhere or is joined to one
that does, is a drawn-only check. Script that Python puts together, by an
f-string, %, +, join, replace or json.dumps, is put together before it is
read.

The field may be named in the statement itself, through what the module, the
function or a function around it bound to a name or gave a parameter as its
default, through a dict entry, through a constant another module of the
same app holds and this one imports or reads off that module, or by a
helper of the module, or a helper of that helper, that is handed one. Text a
page shows is not a field, so what get_by_text, has_text and the name of a
button or a link match is not read as one.

What it does not follow, and a review still reads for (NOT_FOLLOWED holds
each as a test that is expected to fail). A field named only as a PIN or by
an id with no password word in it, a name kept on self or on a class, and a
helper in another module or in the core. Names reused within one function
for different things are read as all of them at once.

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
# times as it is there. Each allowed check stands after the page's own
# count, which decides alone at the top of the function
# (test_an_allowed_app_still_counts_every_field_of_the_page_itself).
# (app, module, function, the call as written): (how many, reason)
ALLOWED = {
    ("applecard", "applecard_site.py", "looks_signed_out", "fields.nth(i).is_visible()"): (
        1, "Apple's sign-in is a frame from its own host laid over card.apple.com. The page's "
           "own password fields are all counted first. In a frame on Apple's sign-in host only "
           "a drawn field counts, since a signed-in page may keep the frame (a guess in "
           "applecard_site.py, never measured). Neither the app's page count nor the recorder "
           "reads a frame at all, so this adds a sign-out answer and takes none away "
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

# The words a password field goes by. pwd only as a word of its own.
PASSWORD_WORDS = ("password", "passwort", "kennwort", "passwd", "pwd")
_PASSWORD = re.compile(r"password|passwort|kennwort|passwd|(?<![a-z])pwd|pwd(?![a-z])")

# Selector text that keeps only drawn elements, or leaves hidden ones out,
# read with spaces taken out and in any case.
SELECTOR_DRAWN = (":visible", "visible=true", "visible=false", ":not([hidden", "[hidden]",
                  "display:none", "visibility:hidden", ":not(.hidden", ":not(.d-none",
                  ":not(.invisible", ":not(.sr-only")

# Page script that asks whether an element is drawn.
SCRIPT_DRAWN = ("offsetparent", "offsetwidth", "offsetheight", "clientwidth", "clientheight",
                "getboundingclientrect", "getclientrects", "checkvisibility",
                "getcomputedstyle", "intersectionobserver", "style.display", "style.visibility",
                ".hidden", "[hidden]")
# What tells page script from a selector, written as script writes it, so
# a label that says Return or Document is no script.
_SCRIPT = re.compile(r"=>|\bfunction\s*\(|\bdocument\.|\.querySelector(?:All)?\(|\breturn\s")

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
# What matches the text a page shows, which no field has.
TEXT_CALLS = {"get_by_text", "get_by_title", "get_by_alt_text"}
TEXT_KEYWORDS = {"has_text", "has_not_text"}
# Calls that run page script, and where their script sits among the
# arguments. The other arguments name what it runs on.
SCRIPT_CALLS = {"evaluate": 0, "evaluate_handle": 0, "evaluate_all": 0,
                "wait_for_function": 0, "add_init_script": 0,
                "eval_on_selector": 1, "eval_on_selector_all": 1}
SCRIPT_KEYWORDS = ("expression", "script")
# Calls that put a container's contents into it.
MUTATORS = {"update", "setdefault", "append", "extend", "insert", "add"}
# The calls that put text together, read when script is put together.
JOINS = {"format", "join", "replace", "dumps"}
DRAWN_CONSTANT = "DRAWN_PASSWORD_FIELD"
CALLS_TO_READ = (DRAWN_CALLS | WAIT_CALLS | KEYWORD_CALLS | set(SCRIPT_CALLS)
                 | {"get_by_role", "getattr"})


def _says_password(text: str) -> bool:
    return bool(_PASSWORD.search(text.lower()))


def _says(text: str, words) -> bool:
    low = text.lower().replace(" ", "")
    return any(w in low for w in words)


def _is_script(text: str) -> bool:
    return bool(_SCRIPT.search(text))


## Page script ##############################################################

_FIELD = re.compile(r"input|\[|type|autocomplete", re.I)
_QUERY_BEFORE = re.compile(r"[\w$.\])]*\.querySelector(All)?\(\s*$")
_NAME_BEFORE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*$")
_ENDS = re.compile(r"\s*;?[ \t]*(?:\n|$)")
_TRUTH_BEFORE = re.compile(r"(?:!|Boolean\(|\b(?:if|while)\s*\()\s*$")
_PROPERTY_AFTER = re.compile(r"\s*(?:\?\.|\.|\[)")
_NULL_AFTER = re.compile(r"\s*(?:(?:!==?|===?)\s*null\b|\?(?![.?]))")
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")


def _script_literals(text: str):
    """(kind, start, end) of each string, template and regex literal of page
    script, comments left out. kind is 's' for a string or a template, 'r'
    for a regex."""
    out, i, n, prev = [], 0, len(text), ""
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c and not (text[j] == "\n" and c != "`"):
                j += 2 if text[j] == "\\" else 1
            out.append(("s", i, min(j + 1, n)))
            i, prev = j + 1, c
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "/" and (prev == "" or prev in _REGEX_BEFORE or text[:i].rstrip().endswith("return")):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n" and (in_class or text[j] != "/"):
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                j += 1
            if j < n and text[j] == "/":
                j += 1
                while j < n and text[j].isalpha():
                    j += 1
                out.append(("r", i, j))
                i, prev = j, "/"
                continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def _names_a_field(body: str) -> bool:
    return _says_password(body) and bool(_FIELD.search(body) or body.strip().lower() in PASSWORD_WORDS)


def _uses_after(text: str, name: str, at: int):
    """Where a name stands after at, spread with ... included, a property of
    the same name not."""
    for m in re.finditer(r"(?:(?<=\.\.\.)|(?<![\w$.]))%s\b" % re.escape(name), text[at:]):
        yield at + m.start(), at + m.end()


def _true_or_false(text: str, a: int, b: int) -> bool:
    """Whether what stands at text[a:b] is taken only as true or false, and
    nothing of it is read after."""
    after = text[b:b + 40]
    if _PROPERTY_AFTER.match(after):
        return False
    return bool(_TRUTH_BEFORE.search(text[max(0, a - 40):a]) or _NULL_AFTER.match(after))


def _only_counted(text: str, s: int, e: int) -> bool:
    """Whether what stands at text[s:e], a password selector or a name the
    script gave one, is only counted where it is used."""
    before = text[max(0, s - 120):s]
    query = _QUERY_BEFORE.search(before)
    close = re.match(r"\s*\)", text[e:])
    if not (query and close):
        return False
    start, end = s - len(before) + query.start(), e + close.end()
    named = _NAME_BEFORE.search(before[:query.start()])
    if named and _ENDS.match(text[end:end + 40]):
        # The list or the element is given a name. Each use of it decides.
        uses = list(_uses_after(text, named.group(1), end))
        if query.group(1):
            return all(re.match(r"\s*\.length\b", text[b:]) for _, b in uses)
        return all(_true_or_false(text, a, b) for a, b in uses)
    if query.group(1):
        return bool(re.match(r"\s*\.length\b", text[end:]))
    return _true_or_false(text, start, end)


@functools.lru_cache(maxsize=None)
def _script_reads_a_field(text: str) -> str:
    """'drawn' when page script names a password field by a selector that
    keeps drawn fields, 'used' when it uses one beyond counting it, '' when
    every one is only counted."""
    used = ""
    for kind, s, e in _script_literals(text):
        if kind == "r":
            body = text[s + 1:text.rindex("/", s + 1, e)]
            plain = re.sub(r"[\^$()?:\\]|\\b", "", body).lower()
            if _says_password(body) and (_FIELD.search(body) or plain in PASSWORD_WORDS):
                used = "used"
            continue
        body = text[s + 1:e - 1]
        if not _names_a_field(body):
            continue
        if _says(body, SELECTOR_DRAWN):
            return "drawn"
        named = _NAME_BEFORE.search(text[max(0, s - 80):s])
        if named and _ENDS.match(text[e:e + 40]):
            # A name for the selector. Each place it is handed on decides.
            if all(_only_counted(text, a, b) for a, b in _uses_after(text, named.group(1), e)):
                continue
            used = "used"
        elif not _only_counted(text, s, e):
            used = "used"
    return used


_MARK = "\x01"
_UNREAD = "\x00"


def _with_fields(text: str) -> str:
    """A script put together, each password selector joined into it written
    as one the script quotes."""
    for q in "'\"`":
        text = text.replace(q + _MARK + q, _MARK)
    return text.replace(_MARK, '"input[type=password]"')


## Reading a module #########################################################

def _bindings(nodes):
    """Name -> what was bound to it, by assignment, loop, with, walrus or
    comprehension, an item put into it, or a call that fills it, anywhere in
    these nodes."""
    out = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            out.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for t in target.elts:
                bind(t, value)
        elif isinstance(target, ast.Starred):
            bind(target.value, value)
        elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
            out.setdefault(target.value.id, []).append(value)

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
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr in MUTATORS and isinstance(n.func.value, ast.Name)):
                for v in n.args + [k.value for k in n.keywords]:
                    out.setdefault(n.func.value.id, []).append(v)
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


def _plain_role(call) -> bool:
    """get_by_role of a role no password field has."""
    role = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "role"), None)
    return isinstance(role, ast.Constant) and role.value not in FIELD_ROLES


def _composed(value) -> bool:
    """Text Python puts together."""
    return (isinstance(value, ast.JoinedStr)
            or isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Add, ast.Mod))
            or isinstance(value, ast.Call) and _call_name(value) in JOINS)


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


def _through_partial(call):
    """functools.partial(f, a, b) as the call f(a, b) it stands for, or the
    call itself."""
    if _call_name(call) == "partial" and call.args:
        return ast.Call(func=call.args[0], args=call.args[1:], keywords=call.keywords)
    return call


class _NameIs:
    """A leaf that takes one name, equal to another for the same name so the
    module keeps one record of what reaches it."""

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
        """others, the constants another module of the app holds that name a
        password field."""
        self.tree, self.others = tree, others
        self.every, self.docs, self.parent = [], set(), {}
        self.aliases, self.imported = set(), set()
        self.calls, self.marked, functions = {}, {}, []
        todo = [(tree, None, None)]
        while todo:
            n, fn, stmt = todo.pop()
            self.every.append(n)
            if isinstance(n, ast.stmt):
                stmt = n
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                self.docs.add(id(n.value))
            elif isinstance(n, ast.Import):
                self.aliases |= {a.asname or a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                self.imported |= {a.asname or a.name for a in n.names}
            if isinstance(n, ast.Call):
                self.calls.setdefault(id(fn), []).append(n)
            if self._worth_reading(n):
                self.marked.setdefault(id(fn), {})[id(stmt)] = stmt
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(n)
                self.parent[id(n)] = fn
                fn = n
            todo.extend((c, fn, stmt) for c in ast.iter_child_nodes(n))
        functions.sort(key=lambda f: f.lineno)
        self.units = [("<module>", None)] + [(fn.name, fn) for fn in functions]
        self.selectors = any(self.selector_drawn(n) for n in self.every)
        self._names = None
        self._module_scope = {}
        self._registry = {id(self._module_scope): self._module_scope}
        self._scopes = {}
        self._known = {}
        self.steps = 0

    def _worth_reading(self, n) -> bool:
        """Whether a node is one this census reads its statement for."""
        if isinstance(n, ast.Call):
            return (_call_name(n) in CALLS_TO_READ
                    or any(k.arg is None or k.arg == "visible" for k in n.keywords))
        if isinstance(n, ast.Attribute):
            return n.attr in DRAWN_CALLS
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            return n.value is not None and _composed(n.value)
        text = self.string(n)
        return bool(text) and _says_password(text) and _is_script(text)

    def statements(self, fn):
        """The statements of a function, or of the module, worth reading, in
        order. Every one where the module holds a drawn selector."""
        if self.selectors:
            return list(_statements(fn.body if fn is not None else self.tree.body))
        return sorted(self.marked.get(id(fn), {}).values(), key=lambda s: (s.lineno, s.col_offset))

    @property
    def names(self):
        if self._names is None:
            self._names = _bindings([s for s in self.tree.body if not isinstance(s, _BODIES)])
        return self._names

    def scope(self, fn):
        """What the names of a function were bound to, in it, as its
        parameters' defaults, or in a function around it. Read once and only
        when asked."""
        if fn is None:
            return self._module_scope
        if id(fn) not in self._scopes:
            out, f = {}, fn
            while f is not None:
                for table in (_bindings(f.body), _defaults(f)):
                    for name, values in table.items():
                        out.setdefault(name, []).extend(values)
                f = self.parent.get(id(f))
            self._scopes[id(fn)] = out
            self._registry[id(out)] = out
        return self._scopes[id(fn)]

    def with_lambdas(self, scope, nodes):
        """The scope with each lambda's parameters bound to what the call it
        is handed to also holds, as map and filter hand it, and the
        parameters of a lambda no call hands anything."""
        owner = {id(a): n for n in nodes if isinstance(n, ast.Call)
                 for a in n.args if isinstance(a, ast.Lambda)}
        extra, unbound = {}, set()
        for n in nodes:
            if isinstance(n, ast.Lambda):
                call = owner.get(id(n))
                given = [a for a in call.args if a is not n] if call else []
                for p in _Signature(n).names():
                    if given:
                        extra.setdefault(p, []).extend(given)
                    else:
                        unbound.add(p)
        if not extra:
            return scope, unbound
        merged = {k: list(v) for k, v in scope.items()}
        for k, v in extra.items():
            merged.setdefault(k, []).extend(v)
        self._registry[id(merged)] = merged
        return merged, unbound

    # -- What an expression names, names followed ---------------------------

    def _bound(self, sid, name):
        """(the name's place, what is bound to it, the scope that binding is
        read in)."""
        scope = self._registry[sid]
        if name in scope:
            return (sid, name), scope[name] + self.names.get(name, []), sid
        msid = id(self._module_scope)
        return (msid, name), self.names.get(name, []), msid

    def _direct(self, expr, sid, leaf, skip=frozenset()):
        """(whether expr has a part leaf takes, the names it uses), names not
        followed. A dict entry read by a constant key reads only the entries
        that key can be. Text a page shows is left out."""
        refs, todo, keys = set(), [expr], set()
        while todo:
            n = todo.pop()
            self.steps += 1
            if n is None or id(n) in skip:
                continue
            if leaf(n):
                return True, refs
            if isinstance(n, ast.Name):
                refs.add((sid, n.id))
                continue
            entry = None
            if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                    and isinstance(n.slice, ast.Constant)):
                entry = n.value.id, n.slice
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                  and n.args and isinstance(n.func.value, ast.Name) and isinstance(n.args[0], ast.Constant)):
                entry = n.func.value.id, n.args[0]
            if entry is not None:
                held = self._bound(sid, entry[0])[1]
                if held and all(isinstance(d, ast.Dict) for d in held):
                    if leaf(entry[1]):
                        return True, refs
                    if entry[0] not in keys:
                        keys.add(entry[0])
                        todo.extend(v for d in held for k, v in zip(d.keys, d.values)
                                    if not isinstance(k, ast.Constant) or k.value == entry[1].value)
                    continue
            if isinstance(n, ast.Call):
                name = _call_name(n)
                todo.append(n.func)
                if name in TEXT_CALLS:
                    continue
                plain = name == "get_by_role" and _plain_role(n)
                todo.extend(n.args)
                todo.extend(k.value for k in n.keywords
                            if k.arg not in TEXT_KEYWORDS and not (plain and k.arg == "name"))
                continue
            todo.extend(ast.iter_child_nodes(n))
        return False, refs

    def _name_involves(self, sid, name, leaf) -> bool:
        """Whether what a name was bound to has a part leaf takes, read as a
        graph of names once for each leaf, so a loop of names costs no more
        than its names."""
        table = self._known.setdefault(leaf, {})
        start = self._bound(sid, name)[0]
        if start in table:
            return table[start]
        graph, todo = {}, [(sid, name)]
        while todo:
            s, nm = todo.pop()
            place, held, bsid = self._bound(s, nm)
            if place in graph or place in table:
                continue
            hit, refs = False, set()
            for value in held:
                found, more = self._direct(value, bsid, leaf)
                if found:
                    hit = True
                    break
                refs |= more
            graph[place] = (hit, set() if hit else {self._bound(*r)[0] for r in refs})
            if not hit:
                todo.extend(refs)
        value = {place: hit for place, (hit, _) in graph.items()}
        grew = True
        while grew:
            grew = False
            for place, (_, edges) in graph.items():
                if not value[place] and any(value.get(e, table.get(e, False)) for e in edges):
                    value[place] = True
                    grew = True
        table.update(value)
        return table[start]

    def involves(self, expr, scope, leaf, skip=frozenset()) -> bool:
        """Whether expr, or what a name in it was bound to, has a part leaf
        takes. Parts in skip are left out."""
        sid = id(scope)
        self._registry.setdefault(sid, scope)
        hit, refs = self._direct(expr, sid, leaf, skip)
        return hit or any(self._name_involves(s, n, leaf) for s, n in refs)

    def reaches(self, expr, scope, names) -> set:
        """Which of names expr uses, itself or through what was bound to a
        name in it."""
        return {p for p in names if self.involves(expr, scope, _NameIs(p))}

    # -- Text ----------------------------------------------------------------

    def string(self, n) -> str:
        """A string a module writes, never a docstring."""
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in self.docs:
            return n.value
        return ""

    def text_of(self, n, scope, depth=0, seen=frozenset()) -> str:
        """The text an expression puts together, names followed. A part that
        cannot be read is written as _UNREAD, a password selector joined in
        as _MARK."""
        if depth > 12:
            return _UNREAD
        if isinstance(n, ast.Constant):
            return n.value if isinstance(n.value, str) else str(n.value)
        if isinstance(n, ast.JoinedStr):
            return "".join(self._part(v.value if isinstance(v, ast.FormattedValue) else v,
                                      scope, depth, seen) for v in n.values)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return self._part(n.left, scope, depth, seen) + self._part(n.right, scope, depth, seen)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
            template = self.text_of(n.left, scope, depth + 1, seen)
            values = iter([self._part(v, scope, depth, seen)
                           for v in (n.right.elts if isinstance(n.right, ast.Tuple) else [n.right])])
            return re.sub(r"%%|%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[a-z]",
                          lambda m: "%" if m.group(0) == "%%" else next(values, _UNREAD), template)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            name, on = n.func.attr, n.func.value
            if name == "format":
                template = self.text_of(on, scope, depth + 1, seen)
                values = iter([self._part(v, scope, depth, seen) for v in n.args])
                named = {k.arg: self._part(k.value, scope, depth, seen) for k in n.keywords if k.arg}
                return re.sub(r"\{(\w*)[^{}]*\}", lambda m: named.get(m.group(1), _UNREAD)
                              if m.group(1) and not m.group(1).isdigit() else next(values, _UNREAD),
                              template)
            if name == "join" and n.args and isinstance(n.args[0], (ast.List, ast.Tuple)):
                return self.text_of(on, scope, depth + 1, seen).join(
                    self._part(v, scope, depth, seen) for v in n.args[0].elts)
            if name == "replace" and len(n.args) >= 2:
                return self.text_of(on, scope, depth + 1, seen).replace(
                    self.text_of(n.args[0], scope, depth + 1, seen), self._part(n.args[1], scope, depth, seen))
            if name == "dumps" and n.args:
                return '"%s"' % self._part(n.args[0], scope, depth, seen)
            if name in ("strip", "lstrip", "rstrip"):
                return self.text_of(on, scope, depth + 1, seen)
        if isinstance(n, ast.Name) and n.id not in seen:
            held = self._bound(id(scope), n.id)[1] if id(scope) in self._registry else []
            if len(held) == 1:
                return self.text_of(held[0], scope, depth + 1, seen | {n.id})
        return _UNREAD

    def _part(self, n, scope, depth, seen) -> str:
        text = self.text_of(n, scope, depth + 1, seen)
        if isinstance(n, ast.Constant):
            return text
        if (_says_password(text) and not _is_script(text)
                or _UNREAD in text and not _is_script(text) and self.involves(n, scope, self.password)):
            return _MARK
        return text

    # -- Leaves --------------------------------------------------------------

    def password(self, n) -> bool:
        if isinstance(n, ast.Name):
            return _says_password(n.id) or n.id in self.others and n.id in self.imported
        if isinstance(n, ast.Attribute):
            return _says_password(n.attr) or (n.attr in self.others and isinstance(n.value, ast.Name)
                                              and n.value.id in self.aliases)
        text = self.string(n)
        return bool(text) and _says_password(text) and not text.lower().startswith("text=")

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
    if name == "getattr" and len(call.args) > 1 and isinstance(call.args[1], ast.Constant) \
            and call.args[1].value in DRAWN_CALLS:
        return "%s() through getattr" % call.args[1].value
    if "visible" in keywords:
        return "%s(visible=...)" % name
    if name == "get_by_role":
        shown = keywords.get("include_hidden")
        if _plain_role(call) or isinstance(shown, ast.Constant) and shown.value is True:
            return None
        return "get_by_role(), which leaves hidden elements out"
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
    """(node, form, what it asks about) for each drawn question among nodes,
    a call, or one of Playwright's drawn checks taken without calling it."""
    called = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    out = []
    for n in nodes:
        if isinstance(n, ast.Call) and not _script_args(n):
            form = _drawn_call(n)
            if form:
                out.append((n, form, n.args[0] if form.endswith("getattr") else n))
        elif isinstance(n, ast.Attribute) and n.attr in DRAWN_CALLS and id(n) not in called:
            out.append((n, "%s, taken without a call" % n.attr, n))
    return out


SCRIPT_FORM = "page script that tests a field is drawn"
SELECTOR_FORM = "a selector that keeps drawn fields"


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
    helpers = {}
    for fn_name, fn in mod.units:
        signature = _Signature(fn) if fn is not None else None
        for stmt in mod.statements(fn):
            exprs = [e for e in _own(stmt) if e is not None]
            nodes = [n for e in exprs for n in ast.walk(e)]
            calls = [n for n in nodes if isinstance(n, ast.Call)]
            scripts = [(c, _script_args(c)) for c in calls if _script_args(c)]
            skip = frozenset(id(s) for _, at_script in scripts for s in at_script)
            scope, unbound = mod.with_lambdas(mod.scope(fn), nodes)
            # Page script that names a password field, as written, or as
            # Python puts it together.
            for n in nodes:
                text = mod.string(n)
                if text and _says_password(text) and _is_script(text):
                    read = _script_reads_a_field(text)
                    if read == "drawn" or read and any(mod.involves(e, scope, mod.script_drawn)
                                                       for e in exprs):
                        hits.append((n.lineno, fn_name, SCRIPT_FORM, SCRIPT_FORM))
            composed = [s for _, at_script in scripts for s in at_script if not isinstance(s, ast.Constant)]
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None \
                    and _composed(stmt.value):
                composed.append(stmt.value)
            for s in composed:
                text = _with_fields(mod.text_of(s, scope))
                if _says_password(text) and _is_script(text):
                    read = _script_reads_a_field(text)
                    if read == "drawn" or read and _says(text, SCRIPT_DRAWN):
                        hits.append((s.lineno, fn_name, SCRIPT_FORM, SCRIPT_FORM))
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
            if mod.selectors:
                both = [c for c in calls if mod.involves(c, scope, mod.password)
                        and mod.involves(c, scope, mod.selector_drawn)]
                hits.extend((c.lineno, fn_name, SELECTOR_FORM, ast.unparse(c)) for c in both)
                outside = frozenset(id(c) for c in calls)
                if not both and any(mod.involves(e, scope, mod.password, outside) for e in exprs) \
                        and any(mod.involves(e, scope, mod.selector_drawn, outside) for e in exprs):
                    hits.append((stmt.lineno, fn_name, SELECTOR_FORM, SELECTOR_FORM))
            # A drawn question asked of a password field. A lambda's own
            # parameter that no call hands anything is read through the
            # whole statement.
            for node, form, about in _asks(nodes):
                if unbound and mod.reaches(about, scope, unbound):
                    named = any(mod.involves(e, scope, mod.password, skip) for e in exprs)
                else:
                    named = mod.involves(about, scope, mod.password)
                if named:
                    hits.append((node.lineno, fn_name, form, ast.unparse(node)))
                    continue
                # Or of a parameter, which makes a helper.
                if signature is not None:
                    used = mod.reaches(about, scope, signature.names())
                    if used:
                        helpers.setdefault(fn_name, []).append((signature, used, form))
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Lambda):
                    inner = _Signature(stmt.value)
                    used = mod.reaches(about, scope, inner.names())
                    for t in stmt.targets if used else []:
                        if isinstance(t, ast.Name):
                            helpers.setdefault(t.id, []).append((inner, used, form))
    # A function that hands its own parameter to a helper's asked one is a
    # helper too, read until nothing more is found.
    seen = {(name, frozenset(used)) for name, found in helpers.items() for _, used, _ in found}
    grew = bool(helpers)
    while grew:
        grew = False
        for fn_name, fn in mod.units:
            if fn is None:
                continue
            signature, scope = _Signature(fn), mod.scope(fn)
            for call in map(_through_partial, mod.calls.get(id(fn), [])):
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
    for fn_name, fn in mod.units if helpers else []:
        scope = mod.scope(fn)
        for original in mod.calls.get(id(fn), []):
            call = _through_partial(original)
            for inner, used, form in helpers.get(_call_name(call), []):
                if any((at is None or at in used) and mod.involves(arg, scope, mod.password)
                       for arg, at in inner.handed(call)):
                    hits.append((original.lineno, fn_name, "%s(), which asks %s"
                                 % (_call_name(call), form), ast.unparse(original)))
                    break
    return sorted(set(hits))


def _sets_password_field(tree, nodes=None) -> bool:
    """Whether a module gives PASSWORD_FIELD a value in any way, an
    assignment of any kind, an import from anywhere but the recorder, or a
    setattr. The recorder's own strict value imported under its own name
    sets nothing."""
    for n in ast.walk(tree) if nodes is None else nodes:
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            targets = [n.target]
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            source = getattr(n, "module", None) or ""
            for a in n.names:
                if (a.asname or a.name.rsplit(".", 1)[-1]) != "PASSWORD_FIELD":
                    continue
                if not (a.name == "PASSWORD_FIELD" and source.endswith("recorder")):
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


_TEXTLIKE = (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Name, ast.Tuple, ast.List, ast.Dict,
             ast.Subscript, ast.Attribute)


def _password_constants(tree):
    """The module's constants, named in capitals, whose value is text, a
    collection or a name and names a password field, itself or through
    another such constant. A compiled pattern is text to match, not a field."""
    names = _bindings([s for s in tree.body if not isinstance(s, _BODIES)])
    found, grew = set(), True
    while grew:
        grew = False
        for name, values in names.items():
            if name in found or not name.isupper() or not all(isinstance(v, _TEXTLIKE) for v in values):
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
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Gt)
            and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value == 0):
        return False
    count = test.left
    if not (isinstance(count, ast.Call) and not count.args and not count.keywords
            and isinstance(count.func, ast.Attribute) and count.func.attr == "count"):
        return False
    find = count.func.value
    if not (isinstance(find, ast.Call) and isinstance(find.func, ast.Attribute)
            and find.func.attr == "locator" and ast.unparse(find.func.value) == "page"
            and len(find.args) == 1 and not find.keywords):
        return False
    field = find.args[0]
    return (isinstance(field, ast.Constant) and field.value == recorder.PASSWORD_FIELD
            or ast.unparse(field) == "recorder.PASSWORD_FIELD")


def _top_of(fn):
    """The statements of a function's body, and of a try at its top."""
    for s in fn.body:
        yield s
        if isinstance(s, ast.Try):
            yield from s.body


def _decides_alone(fn):
    """The line of an if at the top of a function that says signed out on
    any password field of the page itself, or None."""
    for s in _top_of(fn):
        if (isinstance(s, ast.If) and _counts_the_page(s.test) and not s.orelse and len(s.body) == 1
                and isinstance(s.body[0], ast.Return) and isinstance(s.body[0].value, ast.Constant)
                and s.body[0].value.value is True):
            return s.lineno
    return None


def _page_count_comes_first(fn, what):
    """What keeps the page's own count from deciding alone ahead of the
    allowed call, empty when nothing does."""
    line = _decides_alone(fn)
    if not line:
        return ["no if at the top says signed out on any password field of the page"]
    allowed = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n) == what]
    if not allowed:
        return ["the allowed call is not there"]
    return ["the allowed call comes before the page's count"] if min(allowed) < line else []


def _reads_only_sign_in_frames(fn):
    """What lets Apple Card's frame check read a frame other than its sign-in
    frames, or answer signed in, empty when nothing does."""
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For) and ast.unparse(n.iter) == "page.frames"]
    if len(loops) != 1:
        return ["%d loops over page.frames" % len(loops)]
    [loop] = loops
    out, first = [], loop.body[0]
    if not (isinstance(first, ast.If) and not first.orelse
            and ast.unparse(first.test).startswith("not _on_sign_in_host(frame.url")
            and [type(s) for s in first.body] == [ast.Continue]):
        out.append("the loop does not skip a frame off the sign-in host first")
    if not [n for n in ast.walk(loop) if isinstance(n, ast.Call)
            and ast.unparse(n) == "fields.nth(i).is_visible()"]:
        out.append("the allowed call is not in the loop")
    answers = {ast.unparse(n) for n in ast.walk(loop) if isinstance(n, ast.Return)}
    if answers != {"return True"}:
        out.append("in the loop a frame answers %s" % sorted(answers))
    bound = _bindings(fn.body)
    if not bound.get("fields") or not all(
            isinstance(v, ast.Call) and _call_name(v) == "locator" and ast.unparse(v.func.value) == "frame"
            for v in bound["fields"]):
        out.append("fields is found other than in a frame")
    if [ast.unparse(v) for v in bound.get("frame", [])] != ["page.frames"]:
        out.append("frame is bound other than by the loop over page.frames")
    return out


def test_an_allowed_app_still_counts_every_field_of_the_page_itself():
    """The allowance is for one check after the page's own count, which
    decides alone at the top of the function, never in place of it."""
    for app, module, name, what in ALLOWED:
        assert not _page_count_comes_first(_function(app, module, name), what), (app, module, name)


def test_apple_cards_allowed_check_reads_only_its_sign_in_frames():
    """page.frames holds the page's own frame too. So the loop the allowed
    check sits in skips every frame not on Apple's sign-in host first, and
    in it a frame's fields only ever say signed out."""
    fn = _function("applecard", "applecard_site.py", "looks_signed_out")
    assert not _reads_only_sign_in_frames(fn)


# Apple Card's check changed in the ways that would make its allowance hide
# a drawn-only check of the page's own fields. Each is one edit of the real
# function, so a change to the app that breaks an edit is seen here.
_APPLE_PAGE = '''        if page.locator("input[type='password']").count() > 0:
            return True'''
_APPLE_LOOP = '''            if not _on_sign_in_host(frame.url or ""):
                continue
'''
_APPLE_ASK = '''                if fields.nth(i).is_visible():
                    return True'''
_APPLE_END = '''    except Exception:
        pass
    return False


def detect_security_challenge'''
APPLE_CHANGED = {
    "the page's count only where the page draws a field": [(_APPLE_PAGE, '''        if (page.locator("input[type='password']").count() > 0
                and page.locator("input[type='password']").first.is_visible()):
            return True''')],
    "the page's count under a condition": [(_APPLE_PAGE, '''        if not page.frames[1:]:
            if page.locator("input[type='password']").count() > 0:
                return True''')],
    "the page's count after the frames": [(_APPLE_PAGE, "        pass"), (_APPLE_END, '''    except Exception:
        pass
    if page.locator("input[type='password']").count() > 0:
        return True
    return False


def detect_security_challenge''')],
    "the loop reads every frame, the page's own too": [(_APPLE_LOOP, "")],
    "a frame with hidden fields answers signed in": [(_APPLE_ASK, _APPLE_ASK + '''
                    return False''')],
}


@pytest.mark.parametrize("name", sorted(APPLE_CHANGED))
def test_apple_cards_tests_see_each_change_that_would_widen_its_allowance(name):
    text = (REPO / "apps" / "applecard" / "applecard_site.py").read_text(encoding="utf-8")
    for old, new in APPLE_CHANGED[name]:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    [fn] = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "looks_signed_out"]
    what = next(iter(ALLOWED))[3]
    found = _page_count_comes_first(fn, what) + _reads_only_sign_in_frames(fn)
    left = _not_allowed({"applecard": tuple(_app_hits({"applecard_site.py": text}))})
    assert found or left, name


@pytest.mark.parametrize("test, alone", [
    ('page.locator("input[type=\'password\']").count() > 0', True),
    ("page.locator(recorder.PASSWORD_FIELD).count() > 0", True),
    ('page.locator("input[type=\'password\']").count() > 0'
     ' and page.locator("input[type=\'password\']").first.is_visible()', False),
    ('page.locator("input[type=\'password\']:visible").count() > 0', False),
    ('page.locator("input[type=\'password\']").count() > 1', False),
    ('frame.locator("input[type=\'password\']").count() > 0', False),
    ("count() > 0", False),
    ("page.count() > 0", False),
])
def test_the_page_count_reads_only_a_count_that_decides_alone(test, alone):
    assert _counts_the_page(ast.parse(test, mode="eval").body) is alone


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
    "page script that reads the field after !!":
        _script('''() => !!document.querySelector("input[type='password']")?.offsetParent'''),
    "page script that reads the field's width after !!":
        _script('''() => !!document.querySelector("input[type='password']").offsetWidth'''),
    "page script that reads the field inside Boolean()":
        _script('''() => Boolean(document.querySelector("input[type='password']")?.offsetParent)'''),
    "page script that names the field, then reads it":
        _script('''() => { const el = document.querySelector("input[type='password']"); '''
                '''return !!el && !!el.offsetParent; }'''),
    "page script that names the field by let, then tests it against null":
        _script('''() => {\n  let el = document.querySelector("input[type='password']");\n'''
                '''  return !!el && el.offsetParent !== null;\n}'''),
    "page script that hands the named field on":
        _script('''() => {\n  var f = document.querySelector("input[type='password']");\n  var g = f;\n'''
                '''  return !!f && g.checkVisibility();\n}'''),
    "page script that reads the first of the list":
        _script('''() => { const els = document.querySelectorAll("input[type='password']");\n'''
                '''  return els.length && !!els[0].offsetParent; }'''),
    "page script that compares the list with its hidden ones":
        _script('''() => document.querySelectorAll("input[type='password']").length > '''
                '''[...document.querySelectorAll("input[type='password']")].filter(e => !e.offsetParent).length'''),
    "page script that finds the field in a shadow root":
        _script('''() => [...document.querySelectorAll('x-login')].some(h => h.shadowRoot && '''
                '''h.shadowRoot.querySelector("input[type='password']") && h.offsetParent)'''),
    "page script that tests a field's type":
        _script('''() => [...document.querySelectorAll('input')].some(e => e.type === 'password' && e.offsetParent)'''),
    "page script that tests a field's type by a pattern":
        _script('''() => [...document.querySelectorAll('input')].some(e => /^password$/i.test(e.type) && e.offsetParent)'''),
    "page script run on every input":
        '''def f(page):\n    return page.locator("input").evaluate_all('''
        '''"els => els.some(e => e.type === 'password' && e.offsetParent)")\n''',
    "page script that waits for the field to be drawn":
        '''def f(page):\n    page.wait_for_function("() => { const e = document.querySelector('input[type=password]'); '''
        '''return e && e.offsetParent; }")\n''',
    "page script put together by an f-string":
        _PW + '''def f(page):\n    return page.evaluate(f"() => [...document.querySelectorAll('{PW}')]'''
              '''.some(e => e.offsetParent)")\n''',
    "page script put together by %":
        _PW + '''def f(page):\n    return page.evaluate("() => [...document.querySelectorAll('%s')]'''
              '''.some(e => e.offsetParent)" % PW)\n''',
    "page script put together with json.dumps":
        '''import json\n\n''' + _PW + '''def f(page):\n    return page.evaluate("() => [...document.querySelectorAll(" + json.dumps(PW) + ")]'''
        '''.some(e => e.offsetParent)")\n''',
    "page script joined at the call":
        '''_VISIBLE_JS = "const visible = el => !!(el.offsetWidth || el.offsetHeight);"\n'''
        '''_PW_JS = """return [...document.querySelectorAll("input[type='password']")].some(visible);"""\n\n\n'''
        '''def f(page):\n    return page.evaluate("() => {" + _VISIBLE_JS + _PW_JS + "}")\n''',
    "page script joined by join()":
        '''_VISIBLE_JS = "const visible = el => !!(el.offsetWidth || el.offsetHeight);"\n'''
        '''_PW_JS = """return [...document.querySelectorAll("input[type='password']")].some(visible);"""\n\n\n'''
        '''def f(page):\n    return page.evaluate("() => {%s}" % "\\n".join([_VISIBLE_JS, _PW_JS]))\n''',
    "page script joined in a local name":
        '''_PW_JS = """return [...document.querySelectorAll("input[type='password']")].some(visible);"""\n\n\n'''
        '''def f(page):\n    vis = "const visible = el => !!el.offsetParent;"\n'''
        '''    script = "() => {" + vis + _PW_JS + "}"\n    return page.evaluate(script)\n''',
    "a selector that names a document form":
        '''def f(page):\n    return page.locator("#document-login input[type='password']:visible").count() > 0\n''',
    "a selector that says function":
        '''def f(page):\n    return page.locator("[data-function=login] input[type=password]:visible").count() > 0\n''',
    "a selector that says return":
        '''def f(page):\n    return page.locator("form[aria-label='Return to sign in'] '''
        '''input[type=password]:visible").count() > 0\n''',
    "a drawn selector constant that names documents":
        _PW + '''ONLY = ":visible, a[href*='documents']:visible"\n\n\n'''
              '''def f(page):\n    return page.locator(PW + ONLY).count() > 0\n''',
    "a selector that leaves a hidden class out":
        '''def f(page):\n    return page.locator("input[type='password']:not(.hidden)").count() > 0\n''',
    "a selector that leaves a d-none class out":
        '''def f(page):\n    return page.locator("input[type='password']:not(.d-none)").count() > 0\n''',
    "a helper whose question sits in a lambda":
        _PW + '''def _drawn(page, sel):\n    return any(map(lambda e: e.is_visible(), page.locator(sel).all()))\n\n\n'''
              '''def f(page):\n    return _drawn(page, PW)\n''',
    "a helper handed the field by keyword":
        _PW + '''def _drawn(page, *, sel):\n    return page.locator(sel).is_visible()\n\n\n'''
              '''def f(page):\n    return _drawn(page, sel=PW)\n''',
    "a helper through functools.partial":
        '''import functools\n\n''' + _PW + '''def _drawn(page, sel):\n    return page.locator(sel).is_visible()\n\n\n'''
        '''def f(page):\n    g = functools.partial(_drawn, page, PW)\n    return g()\n''',
    "a helper of a helper of a helper":
        _PW + '''def _a(loc):\n    return loc.is_visible()\n\n\ndef _b(loc):\n    return _a(loc)\n\n\n'''
              '''def _c(page, sel):\n    return _b(page.locator(sel))\n\n\ndef f(page):\n    return _c(page, PW)\n''',
    "a helper that is a nested function":
        _PW + '''def f(page):\n    def drawn(sel):\n        return page.locator(sel).is_visible()\n    return drawn(PW)\n''',
    "a helper through a local name":
        _PW + '''def _d(page, sel):\n    loc = page.locator(sel)\n    return loc.first.is_visible()\n\n\n'''
              '''def f(page):\n    s = PW\n    return _d(page, s)\n''',
    "a helper that hands back the drawn locator":
        _PW + '''def _shown(loc):\n    return loc.filter(visible=True)\n\n\n'''
              '''def f(page):\n    return _shown(page.locator(PW)).count() > 0\n''',
    "a dict keyed by a name, read by its text":
        '''KEY = "login"\nS = {KEY: "input[type='password']"}\n\n\n'''
        '''def f(page):\n    return page.locator(S["login"]).is_visible()\n''',
    "a dict filled by an item":
        '''S = {}\nS["login"] = "input[type='password']"\n\n\n'''
        '''def f(page):\n    return page.locator(S["login"]).is_visible()\n''',
    "a dict made by dict()":
        '''S = dict(login="input[type='password']")\n\n\n'''
        '''def f(page):\n    return page.locator(S["login"]).is_visible()\n''',
    "a dict entry read by get()":
        '''S = {"login": "input[type='password']", "rows": "tr"}\n\n\n'''
        '''def f(page):\n    return page.locator(S.get("login")).is_visible()\n''',
    "a dict filled by update()":
        '''S = {"rows": "tr"}\nS.update(login="input[type='password']")\n\n\n'''
        '''def f(page):\n    return page.locator(S["login"]).is_visible()\n''',
    "a dict in a dict":
        '''S = {"sign_in": {"field": "input[type='password']"}}\n\n\n'''
        '''def f(page):\n    return page.locator(S["sign_in"]["field"]).is_visible()\n''',
    "is_visible() through getattr":
        _PW + '''def f(page):\n    return getattr(page.locator(PW).first, "is_visible")()\n''',
    "bounding_box kept as a name and called":
        _PW + '''def f(page):\n    box = page.locator(PW).first.bounding_box\n    return box() is not None\n''',
    "expect() kept as a name":
        '''from playwright.sync_api import expect\n\n''' + _PW +
        '''def f(page):\n    e = expect(page.locator(PW))\n    e.to_be_visible(timeout=500)\n''',
    "page script joined in a call of the app's own":
        '''_SHOWN_FN = "const shown = el => !!el.offsetParent;"\n\n\n'''
        '''def _run(page, js):\n    return page.evaluate(js)\n\n\n'''
        '''def f(page):\n    return _run(page, r"""() => { %s\n'''
        '''  return [...document.querySelectorAll("input[type='password']")].some(shown); }""" % _SHOWN_FN)\n''',
    "is_visible() in a lambda handed as a keyword":
        _PW + '''def f(page):\n    return max(page.locator(PW).all(), key=lambda e: e.is_visible()).count() > 0\n''',
    "get_by_role() of a text box kept as a name":
        '''def f(page):\n    box = page.get_by_role("textbox", name="Password")\n    return box.count() > 0\n''',
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
    "an import from another app's site":
        '''from consorsbank_site import PASSWORD_FIELD  # noqa: F401\n''',
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
    "page script that tests the field by if":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  if (document.querySelector("input[type='password']")) return {out: true};\n'''
                '''  return {rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "page script that tests a named field by Boolean()":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  const pw = document.querySelector("input[type='password']");\n'''
                '''  return {password: Boolean(pw), rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "page script that tests the field by a ternary":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  return {password: document.querySelector("input[type='password']") ? 1 : 0,'''
                ''' rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "page script that tests the field by !":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  if (!document.querySelector("input[type='password']")) return '''
                '''{rows: [...document.querySelectorAll('tr')].filter(shown).length};\n  return {out: true};\n}'''),
    "page script that counts a named list":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  const all = document.querySelectorAll("input[type='password']");\n'''
                '''  return {password: all.length > 0, rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "page script with a pattern that holds quotes":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  const id = (a.getAttribute('href') || '').match(/PostBackOptions\\("([^"]+)"/); '''
                '''const pw = !!document.querySelector("input[type='password']");\n'''
                '''  return {pw: pw, rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "page script with a comment that names the field":
        _script('''() => {\n  const shown = el => !!el.offsetParent;\n'''
                '''  // the bank's input[type=password] isn't drawn on every page\n'''
                '''  return {pw: !!document.querySelector("input[type='password']"), '''
                '''rows: [...document.querySelectorAll('tr')].filter(shown).length};\n}'''),
    "a pattern that names a password, matched against a button":
        '''import re\n\nSKIP_RE = re.compile(r"sign out|password|delete", re.I)\n\n\n'''
        '''def f(page):\n    return page.get_by_role("button").filter(has_not_text=SKIP_RE).first.is_visible()\n''',
    "is_visible() of a link that names a password":
        '''def f(page):\n    if page.locator("input[type='password']").count() > 0:\n        return True\n'''
        '''    return page.get_by_role("link", name="Forgot your password?").is_visible()\n''',
    "get_by_role() of a button in the sign-in form":
        '''def f(page):\n    if page.locator("input[type='password']").count() > 0:\n        return True\n'''
        '''    return page.locator("form:has(input[type='password'])").get_by_role("button").count() > 0\n''',
    "is_visible() of text a page shows":
        '''MARKERS = ("Enter your password", "Sign in")\n\n\ndef f(page):\n'''
        '''    return any(page.get_by_text(m).first.is_visible() for m in MARKERS)\n''',
    "pwd inside another word":
        '''def f(page):\n    return page.locator("#upwdate").is_visible()\n''',
    "a dict entry read by get() beside a password entry":
        '''S = {"password_field": "input[type='password']", "rows": "tr"}\n\n\ndef f(page):\n'''
        '''    if page.locator(S["password_field"]).count() > 0:\n        return True\n'''
        '''    return page.locator(S.get("rows")).first.is_visible()\n''',
    "a lambda drawn test of another element in the same statement":
        _PW + '''def f(page):\n    return page.locator(PW).count() > 0 or '''
              '''any(map(lambda e: e.is_visible(), page.locator("nav").all()))\n''',
    "a comprehension drawn test of another element in the same statement":
        _PW + '''def f(page):\n    return page.locator(PW).count() > 0 or '''
              '''any(e.is_visible() for e in page.locator("nav").all())\n''',
}

# A module's own constant named as another module's that names a password
# field, used beside a drawn test of another element.
SAME_NAME_ELSEWHERE = {
    "x_site.py": '''import re\n\nFORBIDDEN_CONTROL_RE = re.compile(r"sign out|password|delete", re.I)\n'''
                 '''LOGIN = "input[type='password']"\n''',
    "x_docs.py": '''import re\n\nFORBIDDEN_CONTROL_RE = re.compile(r"close|delete", re.I)\n'''
                 '''LOGIN = "a.login"\n\n\ndef open_first(page):\n'''
                 '''    b = page.locator("button").filter(has_not_text=FORBIDDEN_CONTROL_RE).first\n'''
                 '''    return b.is_visible() and page.locator(LOGIN).is_visible()\n''',
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


def test_a_constant_of_the_same_name_as_another_modules_is_this_modules_own():
    assert not _app_hits(SAME_NAME_ELSEWHERE)


def test_a_loop_of_names_is_read_in_steps_that_grow_with_its_names():
    """Names that bind each other in a loop, as cursors do, read once each
    for each question rather than once for every path through them."""
    def module(n):
        names = ["n%d" % i for i in range(n)]
        lines = [_PW + "def f(page):"] + ["    %s = page.locator('a')" % x for x in names]
        lines += ["    for _ in range(3):"]
        lines += ["        %s = %s" % (x, " or ".join(y for y in names if y != x)) for x in names]
        for x in names:
            lines += ["        if %s.first.is_visible():" % x, "            return True"]
        return "\n".join(lines + ["    return page.locator(PW).count() > 0"]) + "\n"
    steps = []
    for n in (6, 12):
        mod = _Module(ast.parse(module(n)))
        assert not drawn_checks(mod.tree, mod)
        steps.append(mod.steps)
    # Twice the names, each asked about, and each bound from all the others,
    # is about eight times the work, never the factorial of a path count.
    assert steps[1] < 20 * steps[0], steps


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
