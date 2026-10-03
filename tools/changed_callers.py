"""Name every caller of each function a change touched, and check the call.

    python tools/changed_callers.py
    python tools/changed_callers.py --base HEAD~3
    python tools/changed_callers.py --base origin/main --repo ../another-checkout
    python tools/changed_callers.py --all       every unresolved call, not the first few

Before a change is called ready, every caller of anything it changed is
checked. Done by hand, that check reached the callers somebody thought to
look for, and twice that was not all of them.

In 0.34.0 four apps passed rivals= to the shared deliver(), which did not
take it. Every one of those calls raised TypeError the moment it ran,
while 5,316 tests passed, because the tests called deliver() another way.
On 2026-10-02 a hand merge left a function returning a pair, (found,
unread), where it had returned a list, and a test elsewhere still walked
the list. This makes the first kind of check mechanical and puts the
second in front of a person, where it cannot be overlooked.

WHAT COUNTS AS CHANGED

The base side of every Python file git diff names is read from git, and
the other side is the file on disk, so an edit nobody has committed yet
counts. Files git does not track yet are read too. Functions and methods
are compared by name. One has changed when its parameters did, meaning
their names, their order, which of them have defaults, and whether it
takes *args or **kwargs. It has also changed when the set of things its
return statements return did, or when it is gone. A function that is new
since the base has its callers checked as well, since a new shared
function is where the next rivals= would come from, but it is shown only
when a call to it does not fit. Changed tests and fixtures are left out,
because pytest calls them and nothing else does.

HOW A CALL IS TIED TO ITS DEFINITION

Every call by the function's name anywhere in the checkout is found and
traced the way Python would look the name up. A call is resolved when it
is made in the module that defines the function, or through an import of
it (from X import name, import X, import X as Y, a module of a package,
or a relative import), or as self.name or cls.name in the class that has
the method or a class built on it. An import is followed through any
module that only passes the name along, the way each app's storage.py
passes on the shared one. A module named by its last part alone, like
storage, is taken to be the one nearest the importing file, which is
where Python would find it first. A call to a class is a call to its
__init__.

A resolved call is checked against the new definition. A keyword the
function does not accept, or more positional arguments than it takes, is
an ERROR. A required parameter left out is a WARNING, unless the call
passes *args or **kwargs, in which case it cannot be checked and the line
says so. A call to a function that is gone is an ERROR. When what a
function returns has changed, no verdict is possible, so every call is
listed for a person to read.

A call that may or may not reach the function, like obj.name() on an
object whose class cannot be known from here, is listed as unresolved and
is never an error. A call that plainly reaches something else, a builtin,
a library, or another definition in this checkout, is counted and not
listed.

WHAT IT CANNOT SEE

A function handed somewhere and called later, a call through getattr or
through a name bound by assignment, a method on an object whose class it
cannot know, the fields of a dataclass, a decorator that changes a
signature, a subclass that inherits a changed __init__, and a property,
which is read rather than called. What a caller does with a changed
return value is for the person reading it.

HOW LONG IT TAKES

Every file is read and parsed once at most, and a file whose text never
says a name being looked for is not searched for calls to it. git costs
about a second a process on a busy Windows machine, so the base side of
every changed file comes from one git cat-file, which reads the very
objects git show would print for each file at the base, and all three
git commands start side by side.

It exits 1 when any call is an ERROR, 2 when the base cannot be read, and
0 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import os
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]

# Folders of somebody else's code, or of copies of this code. Never callers.
SKIP = frozenset({".venv", "venv", "dist", "build", "__pycache__", "node_modules", ".git"})
BUILTINS = frozenset(dir(builtins))
IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
OBJECT_ID = re.compile(r"[0-9a-f]{40,64}")

# What a call is traced to. A definition here is ("func", path, name),
# ("class", path, qualified name), ("method", path, class, name, how it
# was reached) or ("module", path). These two stand for everything else.
UNKNOWN = ("unknown",)    # could be anything, the function included
OTHER = ("other",)        # a builtin, a library, or nothing that is a function here
# What a module name means when no file in the checkout could be it.
EXTERNAL = "<external>"

RESOLVED, UNRESOLVED, ELSEWHERE = "resolved", "unresolved", "elsewhere"
METHOD_KINDS = ("method", "classmethod", "staticmethod")
# A call on one of these can never reach a function of this checkout.
LITERALS = (ast.Constant, ast.JoinedStr, ast.List, ast.Tuple, ast.Dict, ast.Set,
            ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
# Decorators that make a def something read rather than called.
READ_NOT_CALLED = frozenset({"property", "cached_property", "setter", "getter", "deleter"})
NONE_RETURN = ast.dump(ast.parse("None", mode="eval").body)

SHOWN = 20       # unresolved calls listed for each function without --all
RETURNS = 4      # changed return statements shown on each side
WIDTH = 110


class BaseUnreadable(Exception):
    """The base could not be read, so nothing can be compared."""


# -- reading the code ----------------------------------------------------------

def parse(data, name):
    """The tree of a file, or the reason there is none. A warning about an
    old escape in somebody's string is not this tool's to print."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(data, filename=name), None
    except (SyntaxError, ValueError, RecursionError) as e:
        where = " at line %d" % e.lineno if getattr(e, "lineno", None) else ""
        return None, "%s%s" % (type(e).__name__, where)


def last_name(node) -> str:
    """The name a decorator or a base class is known by, however it is reached."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def dotted(node):
    """a.b.c as ("a", "b", "c"), or None when it is not a plain chain of names."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    names.append(node.id)
    return tuple(reversed(names))


def flat(body):
    """The statements of a block, counting those under if, try, with, for
    and while as the block's own, since a name bound there is bound in the
    block. A def or a class is a block of its own and is not entered."""
    for node in body:
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(node, field, None)
            if isinstance(inner, list):
                yield from flat(inner)
        for part in [*getattr(node, "handlers", ()), *getattr(node, "cases", ())]:
            yield from flat(part.body)


def returns_of(fn) -> dict:
    """What each return statement of a def returns, as ast.dump without
    line numbers, mapped to the expression, which is None for a bare
    return. The returns of a def or a class inside it are theirs."""
    out = {}
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Return):
            out[NONE_RETURN if node.value is None else ast.dump(node.value)] = node.value
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.extend(c for c in ast.iter_child_nodes(node)
                         if isinstance(c, (ast.stmt, ast.excepthandler, ast.match_case)))
    return out


def imported_module(value):
    """The module a call like importorskip("name") or import_module("name")
    loads, which is how tests here load a tool or an app module by name."""
    if (isinstance(value, ast.Call) and value.args and isinstance(value.args[0], ast.Constant)
            and isinstance(value.args[0].value, str)
            and last_name(value.func) in ("importorskip", "import_module")):
        return value.args[0].value
    return None


def assigned_names(target):
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


class Def:
    """One def as its callers see it. Its parameters and what it returns."""

    def __init__(self, node, qual, cls, kind, decorators, lines):
        a = node.args
        self.name, self.qual, self.cls, self.kind = node.name, qual, cls, kind
        self.node, self.line = node, node.lineno
        self.decorators = decorators
        self.pos = [p.arg for p in a.posonlyargs + a.args]
        self.posonly = len(a.posonlyargs)
        self.required = len(self.pos) - len(a.defaults)
        self.star = a.vararg.arg if a.vararg else None
        self.kwonly = [p.arg for p in a.kwonlyargs]
        self.kw_required = {p.arg for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is None}
        self.stars = a.kwarg.arg if a.kwarg else None
        # Its text, decorators included. Most defs in a changed file are
        # word for word what they were, and need nothing more worked out.
        first = min([node.lineno] + [d.lineno for d in node.decorator_list])
        self.text = b"\n".join(lines[first - 1:node.end_lineno or node.lineno])
        self._returns = None

    @property
    def returns(self) -> dict:
        if self._returns is None:
            self._returns = returns_of(self.node)
        return self._returns

    def key(self):
        """What a caller depends on. Annotations and the default values
        themselves are not part of it, only whether a default is there."""
        return (self.kind, tuple(self.pos), self.posonly, self.required, bool(self.star),
                tuple(sorted(self.kwonly)), frozenset(self.kw_required), bool(self.stars))

    def shown(self) -> str:
        parts = []
        for i, p in enumerate(self.pos):
            parts.append(p + ("=..." if i >= self.required else ""))
            if i + 1 == self.posonly:
                parts.append("/")
        if self.star:
            parts.append("*" + self.star)
        elif self.kwonly:
            parts.append("*")
        parts += [k + ("" if k in self.kw_required else "=...") for k in self.kwonly]
        if self.stars:
            parts.append("**" + self.stars)
        before = "@%s " % self.kind if self.kind in ("staticmethod", "classmethod") else ""
        return "%s%s(%s)" % (before, self.name, ", ".join(parts))


def definitions(tree, data):
    """Every module-level function and every method of a class, by
    qualified name, and the line of every class. A name defined twice, in
    the two branches of an if say, keeps both."""
    defs, classes = {}, {}
    lines = data.splitlines() if data else []

    def visit(body, prefix, cls):
        for node in flat(body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = {last_name(d) for d in node.decorator_list}
                if "overload" in decorators:
                    continue
                if cls is None:
                    kind = "function"
                elif "staticmethod" in decorators:
                    kind = "staticmethod"
                elif "classmethod" in decorators:
                    kind = "classmethod"
                else:
                    kind = "method"
                qual = prefix + node.name
                defs.setdefault(qual, []).append(Def(node, qual, cls, kind, decorators, lines))
            elif isinstance(node, ast.ClassDef):
                qual = prefix + node.name
                classes.setdefault(qual, node.lineno)
                visit(node.body, qual + ".", qual)

    if tree is not None:
        visit(tree.body, "", None)
    return defs, classes


class ClassInfo:
    """What a class body says about the names on the class."""

    def __init__(self, qual, node=None):
        self.qual = qual
        self.bases = list(node.bases) if node is not None else []
        self.methods, self.nested, self.attrs = set(), set(), set()
        # A class the change removed, put back so its callers can be found.
        self.stand_in = node is None
        for st in flat(node.body if node is not None else []):
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.methods.add(st.name)
            elif isinstance(st, ast.ClassDef):
                self.nested.add(st.name)
            elif isinstance(st, ast.Assign):
                for t in st.targets:
                    self.attrs.update(assigned_names(t))
            elif isinstance(st, ast.AnnAssign):
                self.attrs.update(assigned_names(st.target))


# The fields of each kind of node that can hold another node worth a
# visit. A name, a constant and the load or store marks are never one.
_FIELDS = {ast.Name: (), ast.Constant: ()}


def fields_of(kind) -> tuple:
    found = _FIELDS.get(kind)
    if found is None:
        found = _FIELDS[kind] = tuple(f for f in kind._fields if f not in ("ctx", "op", "ops"))
    return found


class Module:
    """One file as its callers see it. The names bound in it, its classes,
    and every call in it under the name it calls."""

    def __init__(self, rel, tree):
        self.rel = rel
        self.names = {}       # name -> every way it is bound
        self.aliases = {}     # name -> what from X import name as other calls it here
        self.star = []        # (module, level) of each from X import *
        self.dotted = set()   # a.b.c of each plain import a.b.c
        self.classes = {}     # qualified name -> ClassInfo
        self.spans = []       # (first line, last line, qualified name) of each class
        self.calls = {}       # called name -> the calls that name it
        for st in flat(tree.body):
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.bind(st.name, ("func", rel, st.name))
            elif isinstance(st, ast.ClassDef):
                self.bind(st.name, ("class", rel, st.name))
            elif isinstance(st, ast.Assign) and not imported_module(st.value):
                for t in st.targets:
                    for name in assigned_names(t):
                        self.bind(name, ("assign",))
            elif isinstance(st, ast.AnnAssign) and st.value is not None:
                for name in assigned_names(st.target):
                    self.bind(name, ("assign",))
        self._classes(tree.body, "")
        self._scan(tree)

    def _scan(self, tree):
        # One pass over every node, by hand rather than with ast.walk, which
        # took three times as long over this checkout. An import anywhere in
        # the file counts for the whole file, since tests here often import
        # inside a test.
        calls, stack = self.calls, [tree]
        pop, push = stack.pop, stack.append
        while stack:
            node = pop()
            kind = node.__class__
            if kind is ast.Call:
                f = node.func
                if f.__class__ is ast.Attribute:
                    calls.setdefault(f.attr, []).append(node)
                elif f.__class__ is ast.Name:
                    calls.setdefault(f.id, []).append(node)
            elif kind is ast.Import:
                for a in node.names:
                    if a.asname:
                        self.bind(a.asname, ("import", a.name))
                    else:
                        top = a.name.split(".")[0]
                        self.bind(top, ("import", top))
                        if "." in a.name:
                            self.dotted.add(a.name)
                continue
            elif kind is ast.ImportFrom:
                for a in node.names:
                    if a.name == "*":
                        self.star.append((node.module or "", node.level))
                        continue
                    self.bind(a.asname or a.name, ("from", node.module or "", node.level, a.name))
                    if a.asname and a.asname != a.name:
                        self.aliases.setdefault(a.name, set()).add(a.asname)
                continue
            elif kind is ast.Assign:
                loaded = imported_module(node.value)
                if loaded:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            self.bind(t.id, ("import", loaded))
            for field in _FIELDS.get(kind) or fields_of(kind):
                value = getattr(node, field, None)
                if value.__class__ is list:
                    for item in value:
                        if isinstance(item, ast.AST):
                            push(item)
                elif isinstance(value, ast.AST):
                    push(value)

    def bind(self, name, how):
        self.names.setdefault(name, []).append(how)

    def _classes(self, body, prefix):
        for node in flat(body):
            if isinstance(node, ast.ClassDef):
                qual = prefix + node.name
                self.classes[qual] = ClassInfo(qual, node)
                self.spans.append((node.lineno, node.end_lineno or node.lineno, qual))
                self._classes(node.body, qual + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._classes(node.body, prefix + node.name + ".<locals>.")

    def context(self, call):
        """The class a call is written in, found by the lines each class
        spans, the innermost when classes nest."""
        found, start = None, 0
        for first, last, qual in self.spans:
            if first <= call.lineno <= last and first >= start:
                found, start = qual, first
        return found


# -- the checkout --------------------------------------------------------------

def module_names(rel: str) -> list:
    """Every dotted name a file could be imported by, from its full path
    down to its last part alone."""
    parts = list(PurePosixPath(rel).parts)
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return [".".join(parts[i:]) for i in range(len(parts))]


def sys_path_root(rel: str, depth: int) -> tuple:
    """The folder that has to be on sys.path for a name of `depth` parts to mean this file."""
    parts = PurePosixPath(rel).parts
    drop = depth + (1 if parts[-1] == "__init__.py" else 0)
    return parts[:max(0, len(parts) - drop)]


def shared(a: tuple, b: tuple) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def skipped(rel: str) -> bool:
    """Whether a path lies in one of the folders that are never read."""
    return any(part in SKIP or "site-packages" in part for part in rel.split("/")[:-1])


def python_files(root: Path) -> list:
    out = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and "site-packages" not in d)
        here = os.path.relpath(folder, root).replace(os.sep, "/")
        for name in sorted(names):
            if name.endswith(".py"):
                out.append(name if here == "." else here + "/" + name)
    return out


class Checkout:
    """The Python files of the working tree, each read and parsed at most
    once, and how a name in one of them is traced to a definition."""

    def __init__(self, root: Path, files, stand_ins=None):
        self.root = root
        self.stand_ins = dict(stand_ins or {})   # path -> base bytes, for files the change deleted
        self.files = set(files) | set(self.stand_ins)
        self.by_name = {}
        for rel in sorted(self.files):
            for name in module_names(rel):
                self.by_name.setdefault(name, []).append(rel)
        self.gone = {}        # path -> what the change removed from a file still here
        self.unparsed = {}
        self._bytes, self._trees, self._modules = {}, {}, {}
        self._memo, self._busy, self._found, self._callee = {}, set(), {}, {}

    def read(self, rel):
        if rel not in self._bytes:
            data = self.stand_ins.get(rel)
            if data is None:
                try:
                    data = (self.root / rel).read_bytes()
                except OSError:
                    data = None
            self._bytes[rel] = data
        return self._bytes[rel]

    def tree(self, rel):
        if rel not in self._trees:
            data, tree = self.read(rel), None
            if data is not None:
                tree, why = parse(data, rel)
                if why:
                    self.unparsed[rel] = why
            self._trees[rel] = tree
        return self._trees[rel]

    def module(self, rel):
        if rel not in self._modules:
            tree = self.tree(rel)
            mod = Module(rel, tree) if tree is not None else None
            if mod is not None:
                # A removed class first, so its methods have it to stand in.
                for change in sorted(self.gone.get(rel, ()), key=lambda c: c.kind != "class"):
                    change.stand_in(mod)
            self._modules[rel] = mod
        return self._modules[rel]

    def _once(self, key, work):
        """Each question answered once. A question met again while it is
        being answered is a loop of imports, and is answered UNKNOWN."""
        if key in self._memo:
            return self._memo[key]
        if key in self._busy:
            return [UNKNOWN]
        self._busy.add(key)
        try:
            out = work()
        finally:
            self._busy.discard(key)
        self._memo[key] = out
        return out

    def find_module(self, name: str, importer: str, level: int = 0):
        """The file a module name means to the file that imports it. A
        relative name is found by its path. Any other is a file it could
        name, and when several could, the one nearest the importer, the
        way storage means the app's own storage.py. EXTERNAL when no file
        here could be it, None when two are equally near."""
        key = (name, PurePosixPath(importer).parent.as_posix(), level)
        if key in self._found:
            return self._found[key]
        if level:
            base = PurePosixPath(importer).parent
            for _ in range(level - 1):
                base = base.parent
            path = base.joinpath(*name.split(".")) if name else base
            found = next((rel for rel in (path.as_posix() + ".py", (path / "__init__.py").as_posix())
                          if rel in self.files), None)
        else:
            candidates = self.by_name.get(name)
            if not candidates:
                found = EXTERNAL
            elif len(candidates) == 1:
                found = candidates[0]
            else:
                here = PurePosixPath(importer).parent.parts
                depth = len(name.split("."))
                ranked = sorted(((shared(here, sys_path_root(rel, depth)), rel) for rel in candidates),
                                reverse=True)
                found = ranked[0][1] if ranked[0][0] > ranked[1][0] else None
        self._found[key] = found
        return found

    def as_module(self, found):
        if found is EXTERNAL:
            return OTHER
        return ("module", found) if found else UNKNOWN

    def lookup(self, rel: str, name: str) -> list:
        """What `name` is at the top of the module in `rel`, followed
        through imports to where it is defined."""
        return self._once(("lookup", rel, name), lambda: self._lookup(rel, name))

    def _lookup(self, rel, name):
        mod = self.module(rel)
        if mod is None:
            return [UNKNOWN]
        out = []
        for how in mod.names.get(name, ()):
            out += self.resolve(mod, how)
        if not out:
            for source, level in mod.star:
                found = self.find_module(source, rel, level)
                if found is EXTERNAL:
                    out.append(OTHER)
                elif found:
                    got = self.lookup(found, name)
                    if any(t[0] != "missing" for t in got):
                        out += got
        if not out and rel.endswith("__init__.py"):
            sub = self.find_module(name, rel, 1)
            if sub:
                out.append(("module", sub))
        return out or [("missing", rel, name)]

    def resolve(self, mod, how) -> list:
        kind = how[0]
        if kind in ("func", "class"):
            return [how]
        if kind == "assign":
            return [UNKNOWN]
        if kind == "import":
            return [self.as_module(self.find_module(how[1], mod.rel))]
        _, source, level, name = how
        # from paperpull_core import storage names a module, not a name in one.
        sub = self.find_module(source + "." + name if source else name, mod.rel, level)
        if sub and sub is not EXTERNAL:
            return [("module", sub)]
        found = self.find_module(source, mod.rel, level)
        if found is EXTERNAL:
            return [OTHER]
        if not found:
            return [UNKNOWN]
        return self.lookup(found, name)

    def name_targets(self, rel, name) -> list:
        got = self.lookup(rel, name)
        if name in BUILTINS and all(t[0] == "missing" for t in got):
            return [OTHER]
        return got

    def chain_targets(self, rel, chain) -> list:
        return self._once(("chain", rel, chain), lambda: self._chain(rel, chain))

    def _chain(self, rel, chain):
        mod = self.module(rel)
        if mod is None:
            return [UNKNOWN]
        start, rest = None, chain[1:]
        for k in range(len(chain), 1, -1):
            full = ".".join(chain[:k])
            if full in mod.dotted:
                start, rest = [self.as_module(self.find_module(full, rel))], chain[k:]
                break
        if start is None:
            start = self.name_targets(rel, chain[0])
        for attr in rest:
            start = [t for root in start for t in self.member(root, attr)]
        return start

    def expr_targets(self, rel, node) -> list:
        if isinstance(node, ast.Subscript):
            node = node.value
        chain = dotted(node)
        return self.chain_targets(rel, chain) if chain else [UNKNOWN]

    def member(self, target, attr) -> list:
        kind = target[0]
        if kind == "module":
            return self.lookup(target[1], attr)
        if kind == "class":
            return self.method_targets(target[1], target[2], attr, "class")
        if kind in ("unknown", "missing"):
            return [UNKNOWN]
        return [OTHER]

    def method_targets(self, rel, cls, attr, how) -> list:
        """What `attr` is on a class, reached through the class itself or
        through an instance of it, looking in its bases when the class does
        not have it."""
        return self._once(("method", rel, cls, attr, how), lambda: self._method(rel, cls, attr, how))

    def _method(self, rel, cls, attr, how):
        mod = self.module(rel)
        info = mod.classes.get(cls) if mod else None
        if info is None:
            return [UNKNOWN]
        if attr in info.methods:
            return [("method", rel, cls, attr, how)]
        if attr in info.nested:
            return [("class", rel, cls + "." + attr)]
        if attr in info.attrs or all(last_name(b) == "object" for b in info.bases):
            # Set on the instance, or on nothing. Either way it could be anything.
            return [UNKNOWN]
        return self.inherited(rel, cls, attr, how)

    def inherited(self, rel, cls, attr, how="instance") -> list:
        """What `attr` is in the bases of a class, as super() finds it."""
        mod = self.module(rel)
        info = mod.classes.get(cls) if mod else None
        if info is None:
            return [UNKNOWN]
        out = []
        for base in info.bases:
            for t in self.expr_targets(rel, base):
                if t[0] == "class":
                    out += self.method_targets(t[1], t[2], attr, how)
                elif t[0] in ("unknown", "missing"):
                    out.append(UNKNOWN)
                else:
                    out.append(OTHER)
        return out or [OTHER]

    def callee(self, mod, call) -> list:
        """Everything the function a call names could be."""
        f = call.func
        if isinstance(f, ast.Name):
            return self.name_targets(mod.rel, f.id)
        if not isinstance(f, ast.Attribute):
            return [UNKNOWN]
        value, attr = f.value, f.attr
        if isinstance(value, ast.Name) and value.id in ("self", "cls"):
            ctx = mod.context(call)
            if not ctx:
                return [UNKNOWN]
            return self.method_targets(mod.rel, ctx, attr, "instance" if value.id == "self" else "class")
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "super":
            ctx = mod.context(call)
            return self.inherited(mod.rel, ctx, attr) if ctx else [UNKNOWN]
        if isinstance(value, ast.Call):
            # C().method() reaches the method of the class C makes. What any
            # other call returns is not known here.
            made = []
            for t in self.callee(mod, value):
                if t[0] == "class":
                    made += self.method_targets(t[1], t[2], attr, "instance")
                else:
                    made.append(UNKNOWN)
            return made or [UNKNOWN]
        if isinstance(value, LITERALS):
            return [OTHER]
        chain = dotted(value)
        if chain is None:
            return [UNKNOWN]
        return [t for root in self.chain_targets(mod.rel, chain) for t in self.member(root, attr)]

    def classify(self, mod, call, change):
        """RESOLVED when the call reaches the definition, with whether the
        call fills its first parameter by the way it is made, UNRESOLVED
        when it might, ELSEWHERE when it plainly reaches something else."""
        f = call.func
        if isinstance(f, ast.Name) and change.kind in METHOD_KINDS and change.name != "__init__":
            return ELSEWHERE, False        # a bare name never reaches a method
        targets = self._callee.get(id(call))
        if targets is None:
            targets = self._callee[id(call)] = self.callee(mod, call)
        for t in targets:
            bound = change.reached_by(t)
            if bound is not None:
                return RESOLVED, bound
        if any(t[0] in ("unknown", "missing") for t in targets):
            return UNRESOLVED, change.assumed_bound(f)
        return ELSEWHERE, False


# -- what changed --------------------------------------------------------------

class Change:
    """A function, method or class the change touched, and how."""

    def __init__(self, rel, qual, kind, what, old, new, line):
        self.rel, self.qual, self.kind, self.what = rel, qual, kind, what
        self.old, self.new, self.line = old, new, line
        owner, _, self.name = qual.rpartition(".")
        self.cls = owner or None
        self.methods = set()       # for a class that is gone, the methods it had
        self.moved = False         # gone, but the module still binds the name another way
        self.inherits = False      # a method gone from a class that may inherit one

    def call_names(self) -> set:
        if self.kind == "class":
            return {self.name} | self.methods
        if self.name == "__init__":
            return {"__init__", self.cls.rpartition(".")[2]}
        return {self.name}

    def reached_by(self, t):
        """None when `t` is not this definition. Otherwise whether a call
        reaching it that way fills the first parameter itself."""
        if self.kind == "function":
            return False if t == ("func", self.rel, self.name) else None
        if self.kind == "class":
            if t == ("class", self.rel, self.qual):
                return True
            if t[0] == "method" and t[1:3] == (self.rel, self.qual):
                return t[4] == "instance"
            return None
        if self.name == "__init__" and t == ("class", self.rel, self.cls):
            return True
        if t[0] == "method" and t[1:4] == (self.rel, self.cls, self.name):
            return self.kind == "classmethod" or (self.kind == "method" and t[4] == "instance")
        return None

    def assumed_bound(self, func) -> bool:
        """For a call that could not be traced, whether to read it as one
        that fills the first parameter, as obj.method() does."""
        if self.kind == "classmethod":
            return True
        if self.kind == "method":
            return isinstance(func, ast.Attribute) or self.name == "__init__"
        return False

    def stand_in(self, mod):
        """Put what the change removed back into the module's names, so a
        call is traced to it as it was before and can be called an error.
        A name the module binds some other way now, by an import say, was
        moved rather than removed, and its callers reach the new one."""
        if self.kind == "class":
            parent, _, name = self.qual.rpartition(".")
            if not parent and name in mod.names:
                self.moved = True
                return
            if parent and parent not in mod.classes:
                return
            info = ClassInfo(self.qual)
            info.methods |= self.methods
            mod.classes[self.qual] = info
            if parent:
                mod.classes[parent].nested.add(name)
            else:
                mod.names[name] = [("class", mod.rel, self.qual)]
        elif self.cls is None:
            if self.name in mod.names:
                self.moved = True
                return
            mod.names[self.name] = [("func", mod.rel, self.name)]
        else:
            info = mod.classes.get(self.cls)
            if info is None:
                return
            if self.name in info.attrs:
                self.moved = True
                return
            if not info.stand_in:
                # The class is still here, so a call may now reach a method
                # it inherits, or for __init__ the one every class has.
                self.inherits = self.name == "__init__" or any(
                    last_name(b) != "object" for b in info.bases)
            info.methods.add(self.name)


def is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def returns_changed(old, new) -> bool:
    before = set().union(*(d.returns for d in old))
    after = set().union(*(d.returns for d in new))
    # A function that returns nothing but None either way has not changed
    # its answer by gaining or losing an early bare return.
    return before != after and not (before <= {NONE_RETURN} and after <= {NONE_RETURN})


def compare(rel, old_tree, old_data, new_tree, new_data, left_out) -> list:
    """What changed in one file."""
    old_defs, old_classes = definitions(old_tree, old_data)
    new_defs, new_classes = definitions(new_tree, new_data)
    testing = is_test_file(rel)
    gone, out = {}, []
    for qual, line in sorted(old_classes.items(), key=lambda kv: kv[0].count(".")):
        if qual not in new_classes and not any(qual.startswith(g + ".") for g in gone):
            gone[qual] = Change(rel, qual, "class", {"removed"}, [], [], line)
    for qual in sorted(old_defs.keys() | new_defs.keys()):
        old, new = old_defs.get(qual, []), new_defs.get(qual, [])
        if old and new and [x.text for x in old] == [x.text for x in new]:
            continue
        d = (new or old)[0]
        if d.cls is not None and any(d.cls == g or d.cls.startswith(g + ".") for g in gone):
            # The class's own entry covers the methods it took with it.
            if d.cls in gone:
                gone[d.cls].methods.add(d.name)
            continue
        if not old:
            what = {"new"}
        elif not new:
            what = {"removed"}
        else:
            what = set()
            if [x.key() for x in old] != [x.key() for x in new]:
                what.add("signature")
            if returns_changed(old, new):
                what.add("return")
        if not what:
            continue
        if any(x.decorators & READ_NOT_CALLED for x in old + new):
            if what != {"new"}:
                left_out["properties"] += 1
            continue
        if testing and (d.name.startswith("test") or "fixture" in d.decorators):
            if what != {"new"}:
                left_out["tests"] += 1
            continue
        out.append(Change(rel, qual, d.kind, what, old, new, d.line))
    for change in gone.values():
        change.methods.discard("__init__")
    return list(gone.values()) + out


# -- checking a call -----------------------------------------------------------

def check_call(d, call, bound):
    """What is wrong with one call to one definition. Errors as (kind,
    words), warnings, and the parameters it could not be checked for."""
    shift = 1 if bound and d.pos else 0
    pos = d.pos[shift:]
    posonly = max(0, d.posonly - shift)
    required = max(0, d.required - shift)
    spread = any(isinstance(a, ast.Starred) for a in call.args)
    given = sum(1 for a in call.args if not isinstance(a, ast.Starred))
    named = [k.arg for k in call.keywords if k.arg is not None]
    spread_named = any(k.arg is None for k in call.keywords)
    takes = set(pos[posonly:]) | set(d.kwonly)
    errors, warned, unchecked = [], [], []
    for k in named:
        if k in takes or d.stars:
            continue
        if k in pos[:posonly]:
            errors.append(("keyword", "passes %s= by name, and %s takes it only by position" % (k, d.qual)))
        else:
            errors.append(("keyword", "passes %s=, which %s does not accept" % (k, d.qual)))
    if given > len(pos) and not d.star:
        errors.append(("count", "passes %d positional arguments, and %s takes at most %d"
                       % (given, d.qual, len(pos))))
    if not spread:
        for p in pos[:given]:
            if p in named and p in takes:
                errors.append(("twice", "passes %s both by position and by name" % p))
    missing_pos = [p for i, p in enumerate(pos[:required])
                   if i >= given and not (p in named and i >= posonly)]
    missing_kw = [k for k in d.kwonly if k in d.kw_required and k not in named]
    if spread_named:
        unchecked = missing_pos + missing_kw
    elif spread:
        unchecked = missing_pos
        warned = ["does not pass %s, which %s requires" % (k, d.qual) for k in missing_kw]
    else:
        warned = ["does not pass %s, which %s requires" % (p, d.qual) for p in missing_pos + missing_kw]
    return errors, warned, unchecked


def best_fit(defs, call, bound):
    """A name defined twice is fine when the call fits either."""
    best = None
    for d in defs:
        got = check_call(d, call, bound)
        score = (len(got[0]), len(got[1]), len(got[2]))
        if best is None or score < best[0]:
            best = (score, got)
    return best[1]


# -- git -----------------------------------------------------------------------

def from_git(root: Path, base: str):
    """The Python files git diff names against the base, the ones git does
    not track, each changed one as the base has it, and the base's commit
    id. All three git processes start at once, and git cat-file is handed
    the paths when git diff has named them."""
    if base.startswith("-"):
        raise BaseUnreadable("a ref cannot start with a dash")
    pipes = dict(cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = []
    try:
        for command in (["diff", "--name-only", "-z", "--no-renames", base, "--"],
                        ["ls-files", "-z", "--others", "--exclude-standard"],
                        ["cat-file", "--batch"]):
            started.append(subprocess.Popen(["git", *command], stdin=subprocess.PIPE, **pipes))
    except OSError as e:
        for p in started:
            p.kill()
        raise BaseUnreadable("git could not be run (%s)" % type(e).__name__)
    diff, others, cat = started
    d_out, d_err = diff.communicate()
    o_out, o_err = others.communicate()
    changed = [p for p in paths_of(d_out) if p.endswith(".py") and not skipped(p)]
    untracked = [p for p in paths_of(o_out) if p.endswith(".py") and not skipped(p) and p not in changed]
    asked = [base + "^{commit}"] + ["%s:%s" % (base, p) for p in changed]
    if diff.returncode != 0 or others.returncode != 0:
        asked = []
    c_out, c_err = cat.communicate("".join(a + "\n" for a in asked).encode("utf-8"))
    for p, err in ((diff, d_err), (others, o_err), (cat, c_err)):
        if p.returncode != 0:
            raise BaseUnreadable(first_line(err))
    blobs, commit = read_batch(c_out, asked, changed)
    return changed, untracked, blobs, commit


def paths_of(raw: bytes) -> list:
    return [p for p in raw.decode("utf-8", "replace").split("\0") if p and "\n" not in p]


def first_line(raw: bytes) -> str:
    lines = [ln.strip() for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[0] if lines else "nothing"


def read_batch(out: bytes, asked: list, paths: list):
    """What git cat-file --batch said about each object asked for. A
    header line, then exactly that many bytes, or a line saying missing."""
    at, got = 0, []
    for _ in asked:
        end = out.find(b"\n", at)
        if end < 0:
            raise BaseUnreadable("git cat-file stopped before it had answered")
        head = out[at:end].decode("utf-8", "replace").split()
        at = end + 1
        if len(head) == 3 and OBJECT_ID.fullmatch(head[0]) and head[2].isdigit():
            size = int(head[2])
            got.append((head[0], head[1], out[at:at + size]))
            at += size + 1
        else:
            got.append(None)
    commit = got[0][0] if got[0] else None
    blobs = {p: g[2] for p, g in zip(paths, got[1:]) if g and g[1] == "blob"}
    return blobs, commit


# -- the report ----------------------------------------------------------------

def plural(n: int, word: str, words: str = "") -> str:
    return "%d %s" % (n, word if n == 1 else (words or word + "s"))


def clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= WIDTH else text[:WIDTH - 3] + "..."


def find_calls(co, change, index):
    """Every call that may be to the change's definition, sorted into
    resolved and unresolved, and a count of those that plainly are not."""
    names = change.call_names()
    resolved, unresolved, elsewhere = [], [], 0
    for rel in sorted({rel for n in names for rel in index.get(n, ())}):
        mod = co.module(rel)
        if mod is None:
            continue
        keys = set(names)
        for name in names:
            keys |= mod.aliases.get(name, set())
        seen = set()
        for key in sorted(keys):
            for call in mod.calls.get(key, ()):
                if id(call) in seen:
                    continue
                seen.add(id(call))
                group, bound = co.classify(mod, call, change)
                if group == RESOLVED:
                    resolved.append((rel, call, bound))
                elif group == UNRESOLVED:
                    # A gone class lists unresolved calls by its own name
                    # only, not every obj.method() named like one of its methods.
                    if change.kind != "class" or key == change.name:
                        unresolved.append((rel, call, bound))
                else:
                    elsewhere += 1

    def order(found):
        return (found[0], found[1].lineno, found[1].col_offset)

    return sorted(resolved, key=order), sorted(unresolved, key=order), elsewhere


def verdict(change, call, bound):
    """What one resolved call gets, a label and what it says. The label is
    None for a call to a new function that fits, which is not shown."""
    what = change.what
    if "removed" in what:
        if change.inherits:
            return "read", []
        return "ERROR", ["still calls %s" % clip(ast.unparse(call.func))]
    if not what & {"signature", "new"}:
        return "read", []
    errors, warned, unchecked = best_fit(change.new, call, bound)
    if errors:
        return "ERROR", [e[1] for e in errors]
    if warned:
        return "WARNING", warned
    if what == {"new"}:
        return None, []
    if unchecked:
        return "unchecked", ["passes *args or **kwargs, so it cannot be checked for %s"
                             % ", ".join(unchecked)]
    return "ok", []


def unresolved_note(change, call, bound) -> list:
    """For a call that could not be traced, the keyword it passes that the
    new definition would refuse, when every definition by the name would."""
    if "removed" in change.what or not change.new:
        return []
    said = []
    for d in change.new:
        refused = [e[1] for e in check_call(d, call, bound)[0] if e[0] == "keyword"]
        if not refused:
            return []
        said.append(refused[0])
    return ["if it is this one, it " + said[0]]


def site_lines(label, rel, call, notes) -> list:
    where = "%s:%d" % (rel, call.lineno)
    first = "  %-10s %s%s" % (label, where, "  " + notes[0] if notes else "")
    return [first] + ["  %s %s  %s" % (" " * 10, " " * len(where), n) for n in notes[1:]]


def returned(node) -> str:
    return " ".join(("return " + ("None" if node is None else ast.unparse(node))).split())


def around_difference(text: str, others: list) -> str:
    """A long line cut so that where it parts from the nearest line on the
    other side stays in view. Clipped at the end instead, two returns that
    differ only near the end would read the same."""
    if len(text) <= WIDTH:
        return text
    same = max((shared(text, other) for other in others), default=0)
    start = max(0, same - 30)
    return clip(("..." if start else "") + text[start:])


def header(change) -> list:
    """The lines that say which definition changed and how. A signature
    is printed whole, since the difference can be its last parameter."""
    what = change.what
    if change.kind == "class":
        return ["%s  class %s  is gone, it was at line %d" % (change.rel, change.qual, change.line)]
    if "removed" in what:
        return ["%s  %s  is gone, it was at line %d" % (change.rel, change.qual, change.line)]
    if what == {"new"}:
        return (["%s:%d  %s  is new" % (change.rel, change.line, change.qual)]
                + ["    now  %s" % d.shown() for d in change.new])
    lines = ["%s:%d  %s" % (change.rel, change.line, change.qual)]
    if "signature" in what:
        lines.append("  signature changed")
        lines += ["    was  %s" % d.shown() for d in change.old]
        lines += ["    now  %s" % d.shown() for d in change.new]
    if "return" in what:
        before = {k: v for d in change.old for k, v in d.returns.items()}
        after = {k: v for d in change.new for k, v in d.returns.items()}
        dropped = sorted(returned(before[k]) for k in before.keys() - after.keys())
        added = sorted(returned(after[k]) for k in after.keys() - before.keys())
        lines.append("  return changed, so read each call below")
        for word, had, mine, theirs in (("was", before, dropped, added), ("now", after, added, dropped)):
            if not had:
                lines.append("    %s  no return statement" % word)
            lines += ["    %s  %s" % (word, around_difference(t, theirs)) for t in mine[:RETURNS]]
            if len(mine) > RETURNS:
                lines.append("    %s  and %d more" % (word, len(mine) - RETURNS))
    return lines


def describe(change, resolved, unresolved, elsewhere, show_all):
    """The block printed for one change, and what it counted. A new
    function's block is empty unless a call to it does not fit."""
    count = {"errors": 0, "warnings": 0, "resolved": 0, "unresolved": 0}
    lines = header(change)
    if change.moved:
        lines.append("  the module still binds the name another way, by an import or an")
        lines.append("  assignment, so its callers reach that and are checked there")
        return lines, count
    if change.inherits and "removed" in change.what:
        lines.append("  the class is still here and may inherit %s, so read each call below"
                     % change.name)
    body = []
    for rel, call, bound in resolved:
        label, notes = verdict(change, call, bound)
        if label is None:
            continue
        count["errors"] += label == "ERROR"
        count["warnings"] += label == "WARNING"
        count["resolved"] += 1
        body += site_lines(label, rel, call, notes)
    if change.what == {"new"}:
        return (lines + body if body else []), count

    shown = hidden = 0
    for rel, call, bound in unresolved:
        notes = unresolved_note(change, call, bound)
        count["unresolved"] += 1
        if not notes and not show_all and shown >= SHOWN:
            hidden += 1
            continue
        shown += not notes
        body += site_lines("unresolved", rel, call, notes)
    if hidden:
        body.append("  and %s named %s, --all lists every one"
                    % (plural(hidden, "more unresolved call"), change.name))
    if not resolved and not unresolved:
        body.append("  no call sites found" if "removed" in change.what else
                    "  no call sites found, it may be called by reference or from outside the checkout")
    if elsewhere:
        body.append("  %s named %s %s" % (
            plural(elsewhere, "call"), change.name,
            "reaches another definition and is not listed" if elsewhere == 1
            else "reach other definitions and are not listed"))
    return lines + body, count


def run(root: Path, base: str, show_all: bool = False) -> int:
    t0 = time.time()
    if not (root / ".git").exists():
        print("changed_callers needs the top folder of a git checkout, and %s is not one" % root.name,
              file=sys.stderr)
        return 2
    try:
        changed, untracked, blobs, commit = from_git(root, base)
    except BaseUnreadable as e:
        print("changed_callers cannot read the base %r here, so nothing was compared. git said %s"
              % (base, e), file=sys.stderr)
        return 2

    deleted = {p for p in changed if not (root / p).is_file()}
    co = Checkout(root, python_files(root), stand_ins={p: blobs[p] for p in deleted if p in blobs})
    left_out = {"tests": 0, "properties": 0}
    changes, notes = [], []
    for rel in changed + untracked:
        old_tree = new_tree = None
        if rel in blobs:
            old_tree, why = parse(blobs[rel], rel)
            if why:
                notes.append("Could not parse %s at the base (%s), so its functions were not compared."
                             % (rel, why))
                continue
        if rel not in deleted:
            new_tree = co.tree(rel)
            if new_tree is None:
                notes.append("Could not parse %s on disk (%s), so its functions were not compared."
                             % (rel, co.unparsed.get(rel, "it could not be read")))
                continue
        changes += compare(rel, old_tree, blobs.get(rel), new_tree,
                           None if rel in deleted else co.read(rel), left_out)
    for change in changes:
        if "removed" in change.what and change.rel not in deleted:
            co.gone.setdefault(change.rel, []).append(change)

    # Which files could hold a call to each name, from the words in their
    # text, so a file that never says a name is never parsed for it.
    wanted = {n.encode("utf-8"): n for c in changes for n in c.call_names()}
    index = {}
    for rel in sorted(co.files - deleted):
        data = co.read(rel)
        if data is not None:
            for word in wanted.keys() & set(IDENTIFIER.findall(data)):
                index.setdefault(wanted[word], []).append(rel)

    out = ["Callers of what changed since %s%s, in %s%s." % (
        base, " (%s)" % commit[:10] if commit else "",
        plural(len(changed) + len(untracked), "changed Python file"),
        ", %d of them untracked" % len(untracked) if untracked else "")]
    skipped = []
    if left_out["tests"]:
        skipped.append("%s and fixtures, which pytest calls" % plural(left_out["tests"], "changed test"))
    if left_out["properties"]:
        skipped.append("%s, which %s read rather than called" % (
            plural(left_out["properties"], "changed property", "changed properties"),
            "is" if left_out["properties"] == 1 else "are"))
    if skipped:
        out.append("Left out are " + ", and ".join(skipped) + ".")
    out += notes

    total = {"errors": 0, "warnings": 0, "resolved": 0, "unresolved": 0}
    changed_n = new_n = 0
    for change in sorted(changes, key=lambda c: (c.rel, c.line, c.qual)):
        lines, count = describe(change, *find_calls(co, change, index), show_all)
        total["errors"] += count["errors"]
        total["warnings"] += count["warnings"]
        if change.what == {"new"}:
            new_n += 1
        else:
            changed_n += 1
            total["resolved"] += count["resolved"]
            total["unresolved"] += count["unresolved"]
        if lines:
            out += [""] + lines
    if not changed_n:
        out += ["", "No function changed since %s." % base]
    out += ["", "%s, %s, %s (%d resolved, %d unresolved) of %s, and %s checked, in %.1fs" % (
        plural(total["errors"], "error"), plural(total["warnings"], "warning"),
        plural(total["resolved"] + total["unresolved"], "call site"),
        total["resolved"], total["unresolved"], plural(changed_n, "changed function"),
        plural(new_n, "new function"), time.time() - t0)]
    print("\n".join(out))
    return 1 if total["errors"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="the ref to compare with, origin/main unless named")
    ap.add_argument("--repo", default=str(REPO), help="the checkout to look in, this one unless named")
    ap.add_argument("--all", action="store_true",
                    help="list every unresolved call, not only the first %d of each function" % SHOWN)
    args = ap.parse_args(argv)
    try:
        # A character the console cannot show is written escaped, not
        # allowed to stop the report halfway.
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    return run(Path(args.repo).resolve(), args.base, args.all)


if __name__ == "__main__":
    raise SystemExit(main())
