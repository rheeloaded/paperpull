"""No pattern handed to a Playwright locator has a "/" that ends it early.

Playwright writes a Python pattern into its selector between slashes, as
name=/pattern/flags, and reads it back the way JavaScript reads a regular
expression literal. A "/" outside a character class ends the pattern
there, whatever follows is a syntax error, and the locator raises
InvalidSelectorError the first time it is asked anything. Every caller
here wraps its locators in try, so nothing said so. The control was
simply never found.

That is how AT&T's "View/print PDF" fallback went dead from the day it
was added, twice over, and how the core's second_step could never press
a revealed "View/print PDF", because re.escape has left "/" alone since
Python 3.7. It was found while repairing American Family, whose date
pattern had one too.

Measured in a real browser, get_by_role(name=), get_by_title,
get_by_alt_text, get_by_placeholder and get_by_test_id all break on it.
get_by_text, get_by_label and has_text happen to read the pattern up to
its last slash and survive. They are held to the same rule anyway,
because the same pattern is routinely handed to both kinds, as AT&T's
was, and escaping the slash costs nothing on either side.

So this follows every pattern that reaches a locator back to where it is
built, through names, loops, parameters and their callers, module
constants and helper returns, and asks two things. Its written parts
have no bare "/", and text escaped into it at run time is escaped with
controls.escape_for_locator, never a bare re.escape. The patterns are
found by the locator they reach, never by what anything is called.

It errs toward asking. A name assigned twice, or a container read at a
place it cannot work out, is taken to hold everything it could, so a
pattern only Python reads can be named as well, and escaping its slash
costs nothing. Text put into a pattern with no escaping at all is a
different fault and is not looked for here.
"""
import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

# The locators that take a pattern. These take it as their first argument
# or as the keyword named below, and the rest only by keyword.
FIRST_ARGUMENT = {"get_by_text", "get_by_label", "get_by_title", "get_by_alt_text",
                  "get_by_placeholder", "get_by_test_id"}
KEYWORDS = {"get_by_role": ("name",), "filter": ("has_text", "has_not_text"),
            "locator": ("has_text", "has_not_text"),
            "get_by_text": ("text",), "get_by_label": ("text",), "get_by_title": ("text",),
            "get_by_alt_text": ("text",), "get_by_placeholder": ("text",),
            "get_by_test_id": ("test_id",)}
ESCAPES_FOR_A_LOCATOR = {"escape_for_locator"}
CONTAINERS = (ast.Tuple, ast.List, ast.Set, ast.Dict,
              ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
# Calls that hand back what they were given, in another container.
PASS_THROUGH = {"list", "tuple", "sorted", "set", "frozenset", "reversed", "fromkeys"}
# Calls whose answer is plain text, which a locator matches as text.
TEXT_METHODS = {"strip", "lstrip", "rstrip", "lower", "upper", "title", "casefold",
                "capitalize", "group", "format", "replace", "join", "removeprefix",
                "removesuffix", "str", "sub", "escape"}


def bare_slashes(pattern: str) -> list:
    """Where Playwright's selector parser would end this pattern early.

    Its reading, copied. A backslash takes the next character with it, a
    "[" opens a class and the first "]" closes it, and a "/" outside a
    class is the end of the literal."""
    out, in_class, i = [], False, 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            out.append(i)
        i += 1
    return out


def items(box):
    """What a container holds. A comprehension holds what it makes."""
    if isinstance(box, ast.Dict):
        return box.values
    if isinstance(box, ast.DictComp):
        return [box.value]
    if isinstance(box, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return [box.elt]
    return box.elts


def assignments(node):
    """(name, value, added) for each simple assignment a statement makes.
    `added` is True for +=, whose value is joined on rather than replacing."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value, False
            elif isinstance(target, (ast.Tuple, ast.List)) and \
                    isinstance(node.value, (ast.Tuple, ast.List)):
                for name, value in zip(target.elts, node.value.elts):
                    if isinstance(name, ast.Name):
                        yield name.id, value, False
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
        yield node.target.id, node.value, False
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and \
            isinstance(node.op, ast.Add):
        yield node.target.id, node.value, True
    elif isinstance(node, ast.NamedExpr):
        yield node.target.id, node.value, False


def unpackings(node):
    """(target, value, iterated) for a statement that binds names by
    unpacking a value or by iterating over one."""
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        yield node.target, node.iter, True
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)) and \
                    not isinstance(node.value, (ast.Tuple, ast.List)):
                yield target, node.value, False


class Source:
    """One module, read once."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.relative_to(REPO).as_posix()
        self.tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        self.parent = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        self.functions = defaultdict(list)
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name].append(node)
        self.constants = defaultdict(list)
        for node in self.tree.body:
            for name, value, added in assignments(node):
                if not added:
                    self.constants[name].append(value)
        self.imported = {}     # local name -> (module, its name there)
        self.modules = {}      # local name -> the module it stands for
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    self.imported[a.asname or a.name] = (node.module, a.name)
                    self.modules[a.asname or a.name] = "%s.%s" % (node.module, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.modules[a.asname or a.name] = a.name

    def function_of(self, node):
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return node
        return None

    def own_nodes(self, fn):
        """Everything in a function, leaving out the functions inside it."""
        for node in ast.walk(fn):
            if node is fn or self.function_of(node) is fn:
                yield node

    def returns(self, fn):
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and node.value is not None \
                    and self.function_of(node) is fn:
                yield node.value


def app_of(source: Source) -> str:
    parts = source.name.split("/")
    return parts[1] if parts[0] == "apps" else "core"


SOURCES = [Source(p) for p in sorted(list(REPO.glob("apps/*/*.py"))
                                     + list(REPO.glob("core/paperpull_core/*.py")))]
BY_MODULE = {}
for _s in SOURCES:
    if _s.name.startswith("core/paperpull_core/"):
        BY_MODULE["paperpull_core." + _s.path.stem] = _s
    else:
        BY_MODULE[("app", _s.path.parent.name, _s.path.stem)] = _s

CALLS = defaultdict(list)       # the name a function is called by -> [(source, call)]
for _s in SOURCES:
    for _node in ast.walk(_s.tree):
        if isinstance(_node, ast.Call):
            _f = _node.func
            _name = _f.id if isinstance(_f, ast.Name) else \
                _f.attr if isinstance(_f, ast.Attribute) else None
            if _name:
                CALLS[_name].append((_s, _node))


def module_named(source: Source, dotted: str):
    """The source a module name means from inside `source`, the core's by
    name and an app's own modules by their file name."""
    if dotted in BY_MODULE:
        return BY_MODULE[dotted]
    if source.name.startswith("apps/"):
        return BY_MODULE.get(("app", source.path.parent.name, dotted.split(".")[-1]))
    return None


def is_re(call, what: str) -> bool:
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == what and \
        isinstance(f.value, ast.Name) and f.value.id == "re"


def parameters(fn):
    a = fn.args
    return [p.arg for p in a.posonlyargs + a.args] + [p.arg for p in a.kwonlyargs]


def default_of(fn, name):
    a = fn.args
    positional = a.posonlyargs + a.args
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for p, d in list(zip(positional, defaults)) + list(zip(a.kwonlyargs, a.kw_defaults)):
        if p.arg == name:
            return d
    return None


def callers(source: Source, fn):
    """(source, call) for every call that reaches `fn`, from its own module,
    from a module that imports it under any name, and from an app's other
    modules calling it through the site module."""
    out = [(s, c) for s, c in CALLS.get(fn.name, []) if s is source]
    for other in SOURCES:
        if other is source:
            continue
        for alias, (module, name) in other.imported.items():
            if name == fn.name and module_named(other, module) is source:
                out += [(s, c) for s, c in CALLS.get(alias, []) if s is other]
        for alias, module in other.modules.items():
            if module_named(other, module) is source:
                out += [(s, c) for s, c in CALLS.get(fn.name, [])
                        if s is other and isinstance(c.func, ast.Attribute)
                        and isinstance(c.func.value, ast.Name) and c.func.value.id == alias]
    return out


def argument_for(call, fn, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    positional = [p.arg for p in fn.args.posonlyargs + fn.args.args]
    if name not in positional:
        return None
    i = positional.index(name)
    if positional and positional[0] in ("self", "cls") and isinstance(call.func, ast.Attribute):
        i -= 1
    if any(isinstance(a, ast.Starred) for a in call.args[:i + 1]) or not 0 <= i < len(call.args):
        return None
    return call.args[i]


class Follow:
    """What an expression may stand for, as [(expression, source, function)],
    followed through names, loops, unpacking, parameters and their callers,
    module constants, imports and helper returns. What cannot be followed
    comes back as itself. With `whole`, a literal tuple, list or dict comes
    back as one thing rather than as its items, for the unpacking and the
    indexing that need it."""

    def __init__(self):
        self.memo = {}
        # The lists made up here for what was appended to a name. Kept so
        # that no id in the memo can be handed to a new one.
        self.made = []

    def __call__(self, expr, source, fn, whole=False):
        key = (id(expr), id(source), whole)
        if key in self.memo:
            return self.memo[key] or []
        self.memo[key] = None           # in progress, so a cycle answers nothing
        found = self.follow(expr, source, fn, whole)
        self.memo[key] = found
        return found

    def follow(self, expr, source, fn, whole):
        me = [(expr, source, fn)]
        if isinstance(expr, ast.IfExp):
            return self(expr.body, source, fn, whole) + self(expr.orelse, source, fn, whole)
        if isinstance(expr, ast.BoolOp):
            return [x for v in expr.values for x in self(v, source, fn, whole)]
        if isinstance(expr, CONTAINERS):
            return me if whole else [x for e in items(expr) for x in self(e, source, fn)]
        if isinstance(expr, ast.Subscript):
            out = []
            key = expr.slice.value if isinstance(expr.slice, ast.Constant) else None
            for box, s, f in self(expr.value, source, fn, whole=True):
                if isinstance(box, ast.Dict) and key is not None and all(
                        isinstance(k, ast.Constant) for k in box.keys):
                    # A written key reads only its own value.
                    picked = [v for k, v in zip(box.keys, box.values) if k.value == key]
                    out += [x for v in picked for x in self(v, s, f, whole)]
                elif isinstance(box, CONTAINERS):
                    out += [x for e in items(box) for x in self(e, s, f, whole)]
            return out or me
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) \
                and expr.value.id in source.modules:
            other = module_named(source, source.modules[expr.value.id])
            if other is not None and expr.attr in other.constants:
                return [x for v in other.constants[expr.attr] for x in self(v, other, None, whole)]
            return me
        if isinstance(expr, ast.Call) and not is_re(expr, "compile"):
            f = expr.func
            called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if called in PASS_THROUGH and expr.args:
                return self(expr.args[0], source, fn, whole)
            if isinstance(f, ast.Name):
                where, targets = source, source.functions.get(f.id, [])
                if not targets and f.id in source.imported:
                    module, name = source.imported[f.id]
                    other = module_named(source, module)
                    if other is not None:
                        where, targets = other, other.functions.get(name, [])
                out = [x for t in targets for r in where.returns(t) for x in self(r, where, t, whole)]
                return out or me
            return me
        if isinstance(expr, ast.Name):
            return self.name(expr.id, source, fn, whole)
        return me

    def name(self, name, source, fn, whole):
        unseen = [(ast.Name(id=name), source, fn)]
        if fn is None:
            return self.module_name(name, source, whole) or unseen
        if isinstance(fn, ast.Lambda):
            if name in parameters(fn):
                return unseen
            return self.name(name, source, source.function_of(fn), whole)
        out, added = [], []
        for node in source.own_nodes(fn):
            for target, value, joined in assignments(node):
                if target == name:
                    if joined:
                        added += items(value) if isinstance(value, (ast.List, ast.Tuple)) else []
                    else:
                        out += self(value, source, fn, whole)
            for target, value, iterated in unpackings(node):
                out += self.unpacked(name, target, value, iterated, source, fn, whole)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    isinstance(node.func.value, ast.Name) and node.func.value.id == name:
                if node.func.attr == "append" and node.args:
                    added.append(node.args[0])
                elif node.func.attr == "insert" and len(node.args) > 1:
                    added.append(node.args[1])
                elif node.func.attr == "extend" and node.args:
                    for box, s, f in self(node.args[0], source, fn, whole=True):
                        added += items(box) if isinstance(box, CONTAINERS) else []
        if added:
            self.made.append(ast.List(elts=added, ctx=ast.Load()))
            out += self(self.made[-1], source, fn, whole)
        if name in parameters(fn):
            default = default_of(fn, name)
            if default is not None:
                out += self(default, source, None, whole)
            for s, call in callers(source, fn):
                given = argument_for(call, fn, name)
                if given is not None:
                    out += self(given, s, s.function_of(call), whole)
            return out or unseen
        if out:
            return out
        outer = source.function_of(fn)
        if outer is not None:
            return self.name(name, source, outer, whole)
        return self.module_name(name, source, whole) or unseen

    def unpacked(self, name, target, value, iterated, source, fn, whole):
        """What `name` takes from `target = value`, or from each item of
        `value` when it is iterated over."""
        if isinstance(target, ast.Name):
            if target.id != name or not iterated:
                return []
            out = []
            for box, s, f in self(value, source, fn, whole=True):
                if isinstance(box, CONTAINERS):
                    out += [x for e in items(box) for x in self(e, s, f, whole)]
                else:
                    out.append((box, s, f))
            return out
        if not isinstance(target, (ast.Tuple, ast.List)):
            return []
        names = [t.id if isinstance(t, ast.Name) else None for t in target.elts]
        if name not in names:
            return []
        i = names.index(name)
        wholes = self(value, source, fn, whole=True)
        if iterated:
            wholes = [x for box, s, f in wholes if isinstance(box, CONTAINERS)
                      for e in items(box) for x in self(e, s, f, whole=True)]
        out = []
        for box, s, f in wholes:
            if isinstance(box, (ast.Tuple, ast.List)) and i < len(box.elts):
                out += self(box.elts[i], s, f, whole)
        return out

    def module_name(self, name, source, whole):
        if name in source.constants:
            return [x for v in source.constants[name] for x in self(v, source, None, whole)]
        if name in source.imported:
            module, there = source.imported[name]
            other = module_named(source, module)
            if other is not None and there in other.constants:
                return [x for v in other.constants[there] for x in self(v, other, None, whole)]
        return []


def is_text(expr) -> bool:
    """Whether a locator was handed plain text, which it matches as text."""
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, str)
    if isinstance(expr, (ast.JoinedStr, ast.BinOp)):
        return True
    if isinstance(expr, ast.Call):
        f = expr.func
        called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        return called in TEXT_METHODS
    return False


def pieces(expr, source, fn, follow, depth=0):
    """What a pattern is built from, in order, as ("text", str) for what is
    written, ("escaped", node) for a bare re.escape, ("safe", node) for text
    escaped for a locator, and ("unread", node) for anything else."""
    if depth > 16:
        return [("unread", expr)]
    again = lambda e, s=source, f=fn: pieces(e, s, f, follow, depth + 1)  # noqa: E731
    if isinstance(expr, ast.Constant):
        return [("text", expr.value)] if isinstance(expr.value, str) else [("unread", expr)]
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return again(expr.left) + again(expr.right)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod):
        given = expr.right.elts if isinstance(expr.right, ast.Tuple) else [expr.right]
        return again(expr.left) + [p for g in given for p in again(g)]
    if isinstance(expr, ast.JoinedStr):
        out = []
        for v in expr.values:
            out += [("text", v.value)] if isinstance(v, ast.Constant) else again(v.value)
        return out
    if isinstance(expr, ast.IfExp):
        return again(expr.body) + again(expr.orelse)
    if isinstance(expr, ast.Call):
        f = expr.func
        if is_re(expr, "escape"):
            return [("escaped", expr)]
        called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        if called in ESCAPES_FOR_A_LOCATOR:
            return [("safe", expr)]
        if called == "replace" and isinstance(f, ast.Attribute):
            inner = again(f.value)
            if len(expr.args) >= 2 and all(isinstance(a, ast.Constant) for a in expr.args[:2]) \
                    and expr.args[0].value == "/" and expr.args[1].value == "\\/":
                return [("safe", n) if kind == "escaped" else (kind, n) for kind, n in inner]
            return inner
        if called == "format" and isinstance(f, ast.Attribute):
            given = list(expr.args) + [kw.value for kw in expr.keywords]
            return again(f.value) + [p for g in given for p in again(g)]
        if called == "map" and isinstance(f, ast.Name) and expr.args:
            # map(re.escape, words), the escaping handed over by name
            how = expr.args[0]
            if isinstance(how, ast.Attribute) and how.attr == "escape" and \
                    isinstance(how.value, ast.Name) and how.value.id == "re":
                return [("escaped", expr)]
            named = how.id if isinstance(how, ast.Name) else how.attr if isinstance(how, ast.Attribute) else ""
            return [("safe", expr)] if named in ESCAPES_FOR_A_LOCATOR else [("unread", expr)]
        if called == "join" and isinstance(f, ast.Attribute) and expr.args:
            arg = expr.args[0]
            if isinstance(arg, (ast.GeneratorExp, ast.ListComp)):
                joined = again(arg.elt)
            elif isinstance(arg, (ast.Tuple, ast.List)):
                joined = [p for e in arg.elts for p in again(e)]
            else:
                joined = again(arg)
            return again(f.value) + joined
        if isinstance(f, ast.Name) and f.id in source.functions:
            out = [p for t in source.functions[f.id] for r in source.returns(t)
                   for p in pieces(r, source, t, follow, depth + 1)]
            return out or [("unread", expr)]
        return [("unread", expr)]
    if isinstance(expr, ast.Name):
        if fn is not None and not isinstance(fn, ast.Lambda):
            written = sorted((value for node in source.own_nodes(fn)
                              for target, value, _ in assignments(node) if target == expr.id),
                             key=lambda v: (v.lineno, v.col_offset))
            if written:
                return [p for value in written for p in again(value)]
        followed = [(e, s, f) for e, s, f in follow(expr, source, fn)
                    if not (isinstance(e, ast.Name) and e.id == expr.id)]
        if followed:
            return [p for e, s, f in followed for p in pieces(e, s, f, follow, depth + 1)]
        return [("unread", expr)]
    return [("unread", expr)]


class Pattern:
    """One pattern built in one place and handed to a locator somewhere."""

    def __init__(self, built, source, fn, sink, sink_source, follow):
        self.built, self.source, self.fn = built, source, fn
        self.sink, self.sink_source = sink, sink_source
        self.variants = self.read(follow)
        self.pieces = [p for v in self.variants for p in v]

    def read(self, follow):
        """Each way the pattern can come out. A name followed to several
        patterns, the loop over a tuple of them, is read one at a time."""
        expr, fn = self.built, self.fn
        if isinstance(expr, ast.Name) and not (fn is not None and not isinstance(fn, ast.Lambda) and any(
                target == expr.id for node in self.source.own_nodes(fn)
                for target, _, _ in assignments(node))):
            leaves = [(e, s, f) for e, s, f in follow(expr, self.source, fn)
                      if not (isinstance(e, ast.Name) and e.id == expr.id)]
            if leaves:
                return [pieces(e, s, f, follow) for e, s, f in leaves]
        return [pieces(expr, self.source, fn, follow)]

    def written(self):
        return ["".join(n if kind == "text" else "x" for kind, n in v) for v in self.variants]

    def where(self) -> str:
        return "%s line %d" % (self.source.name, self.built.lineno)

    def reaches(self) -> str:
        return "%s line %d" % (self.sink_source.name, self.sink.lineno)


def sinks(source: Source):
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method in FIRST_ARGUMENT and node.args:
            yield node, node.args[0]
        for kw in node.keywords:
            if kw.arg in KEYWORDS.get(method, ()):
                yield node, kw.value


def patterns_reaching_locators():
    """Every pattern handed to a locator, once for each place it is built
    and each locator it reaches, the plain text handed to one, and every
    argument that could not be followed to either."""
    found, text, unfollowed, seen = [], 0, [], set()
    follow = Follow()
    for source in SOURCES:
        for sink, given in sinks(source):
            for expr, where, fn in follow(given, source, source.function_of(sink)):
                if isinstance(expr, ast.Call) and is_re(expr, "compile"):
                    built = expr.args[0] if expr.args else expr
                    key = (id(built), id(sink))
                    if key not in seen:
                        seen.add(key)
                        found.append(Pattern(built, where, where.function_of(expr), sink, source, follow))
                elif is_text(expr):
                    text += 1
                else:
                    unfollowed.append((source.name, sink.lineno, ast.unparse(expr)[:60]))
    return found, text, unfollowed


PATTERNS, TEXT, UNFOLLOWED = patterns_reaching_locators()
APPS = sorted({app_of(p.source) for p in PATTERNS})


def mine(app):
    """This app's patterns, one for each place one is built."""
    out, seen = [], set()
    for p in PATTERNS:
        if app_of(p.source) == app and id(p.built) not in seen:
            seen.add(id(p.built))
            out.append(p)
    return out


# -- the rule itself --------------------------------------------------------

def test_the_rule_reads_a_pattern_the_way_playwright_does():
    assert bare_slashes(r"^\s*view\s*/\s*print\s+pdf\s*$") == [11]
    assert bare_slashes(r"^\s*view\s*\/\s*print\s+pdf\s*$") == []
    assert bare_slashes(r"\d{2}[/-]\d{2}[/-]\d{4}") == [], "a slash inside a class is fine"
    assert bare_slashes(r"a\\/b") == [3], "an escaped backslash leaves the slash bare"
    assert bare_slashes(r"[\]/]") == [], "an escaped bracket does not close the class"
    assert bare_slashes(re.escape("View/print PDF")) != [], "re.escape leaves it bare"


def test_escaping_for_a_locator_fixes_only_the_slash():
    from paperpull_core.controls import escape_for_locator
    for text in ("View/print PDF", "a\\/b", "Q3 (Jul/Sep) 2026", "plain words", "07/31/26"):
        escaped = escape_for_locator(text)
        assert bare_slashes(escaped) == [], text
        assert re.fullmatch(escaped, text), "Python must still match it exactly, %r" % text


# -- every app ---------------------------------------------------------------

@pytest.mark.parametrize("app", APPS)
def test_no_pattern_this_app_hands_a_locator_has_a_bare_slash(app):
    bad = ["%s, reaching %s, reads %r" % (p.where(), p.reaches(), w)
           for p in mine(app) for w in p.written() if bare_slashes(w)]
    assert not bad, (
        "%s hands Playwright a pattern whose \"/\" ends it early, so the locator "
        "raises InvalidSelectorError when used and the control is never found. "
        "Write the slash as \\/ . %s" % (app, "; ".join(bad)))


@pytest.mark.parametrize("app", APPS)
def test_text_this_app_puts_into_such_a_pattern_is_escaped_for_a_locator(app):
    bad = ["%s, reaching %s" % (p.where(), p.reaches())
           for p in mine(app) if any(kind == "escaped" for kind, _ in p.pieces)]
    assert not bad, (
        "%s puts text into a pattern for a locator with re.escape, which leaves "
        "\"/\" bare, so text holding one is never found. Use "
        "paperpull_core.controls.escape_for_locator. %s" % (app, "; ".join(bad)))


FLAGS = {"I": re.I, "IGNORECASE": re.I, "S": re.S, "DOTALL": re.S, "M": re.M,
         "MULTILINE": re.M, "X": re.X, "VERBOSE": re.X, "A": re.A, "ASCII": re.A}


def flags_of(call) -> int:
    """The flags a re.compile call passes, read from its source."""
    given = call.args[1] if len(call.args) > 1 else None
    for kw in call.keywords:
        if kw.arg == "flags":
            given = kw.value
    total = 0
    for node in ast.walk(given) if given is not None else ():
        if isinstance(node, ast.Attribute) and node.attr in FLAGS:
            total |= FLAGS[node.attr]
    return total


def test_every_written_pattern_is_read_by_a_real_locator():
    """The rule above is a copy of how Playwright reads a pattern. This asks
    Playwright itself, handing every pattern that is written out whole to
    get_by_role and to get_by_text in a real browser, which also catches
    what the copy does not model, a named group for one, which JavaScript
    refuses, or a flag Playwright cannot carry."""
    pw = pytest.importorskip("playwright.sync_api")
    whole = {}
    for p in PATTERNS:
        call = p.source.parent.get(p.built)
        if not isinstance(call, ast.Call):
            continue
        for variant in p.variants:
            if variant and all(kind == "text" for kind, _ in variant):
                text = "".join(n for _, n in variant)
                whole.setdefault((text, flags_of(call)), p)
    assert len(whole) > 80, "only %d written patterns to ask about" % len(whole)
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True, args=[
            "--disable-extensions", "--disable-sync", "--no-first-run",
            "--disable-background-networking", "--disable-component-update"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    refused = []
    try:
        page = browser.new_page()
        page.set_content("<body><button>x</button></body>")
        for (text, flags), p in sorted(whole.items(), key=lambda kv: kv[1].where()):
            pattern = re.compile(text, flags)
            for ask in (lambda: page.get_by_role("button", name=pattern),
                        lambda: page.get_by_text(pattern)):
                try:
                    ask().count()
                except Exception as e:
                    refused.append("%s, reaching %s, %s" % (
                        p.where(), p.reaches(), str(e).strip().splitlines()[0][:140]))
                    break
    finally:
        browser.close()
        driver.stop()
    assert not refused, "Playwright cannot read these patterns. %s" % "; ".join(refused)


# -- that the census sees what it claims to -----------------------------------

def test_this_is_asking_about_a_real_number_of_patterns():
    """If the following breaks, every app above passes by asking about
    nothing. About two hundred and thirty patterns reach a locator, and
    only a few arguments are data that cannot be followed at all, the
    dates, years and list items read at run time."""
    assert len(PATTERNS) > 200, "only %d patterns were followed" % len(PATTERNS)
    assert len(APPS) > 40, "only %d apps hand a locator a pattern" % len(APPS)
    assert len(UNFOLLOWED) * 10 < len(PATTERNS), "%d arguments could not be followed, %s" % (
        len(UNFOLLOWED), UNFOLLOWED)


def test_it_follows_a_pattern_through_a_parameter_into_the_core():
    """controls_named hands its caller's pattern to get_by_role, so the
    pattern is built in the app and reaches a locator in the core."""
    across = [p for p in PATTERNS if app_of(p.source) != "core"
              and p.sink_source.name == "core/paperpull_core/controls.py"]
    assert len(across) > 10, "only %d app patterns followed into the core" % len(across)


def test_it_follows_a_pattern_through_a_loop_and_a_helper_return():
    """AT&T's _pdf_button tries its patterns in a loop, and E*TRADE builds
    one in a helper that returns it. Both were invisible to a census that
    looked for a name on the line that calls the locator."""
    att = [p for p in PATTERNS if p.source.name == "apps/att/att_site.py"
           and p.fn is None and any("download\\s+pdf|view" in w for w in p.written())]
    assert att, "AT&T's PDF_BUTTON_RE was not followed through _pdf_button's loop"
    etrade = [p for p in PATTERNS if p.source.name == "apps/etrade/etrade_site.py"
              and getattr(p.fn, "name", "") == "_title_name_re"]
    assert etrade, "E*TRADE's _title_name_re was not followed from its return"


def test_it_follows_a_tuple_unpacked_in_a_loop():
    """Meijer opens its two tabs with `for pattern, label in ((A, ...),
    (B, ...))`, handing `pattern` on to a function that gives it to
    get_by_role."""
    meijer = {w for p in PATTERNS if p.source.name == "apps/meijer/meijer_site.py"
              and p.sink_source.name == "apps/meijer/meijer_site.py"
              for w in p.written() if "store" in w or "online" in w}
    assert len(meijer) >= 2, "Meijer's two tab patterns were not both followed, %s" % meijer


def test_a_pattern_built_at_run_time_is_seen_as_such():
    """The core's second_step builds its pattern from the control's text,
    which is where re.escape left the slash bare."""
    core = [p for p in PATTERNS if p.source.name == "core/paperpull_core/controls.py"
            and getattr(p.fn, "name", "") == "second_step"]
    assert core and any(kind in ("escaped", "safe") for kind, _ in core[0].pieces), \
        "second_step's pattern was not read as text put in at run time"
