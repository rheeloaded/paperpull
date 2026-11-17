"""Every browser a test starts as a program of its own keeps off the Keychain.

On a Mac, Chromium asks the login Keychain for its "Chrome Safe Storage"
key the first time a profile starts, to encrypt that profile's cookies. A
test browser starts with a fresh profile each time, so a full run put up
the "wants to use your confidential information" prompt again and again.
Playwright's own launch passes --use-mock-keychain, so the browsers it
starts never asked. The browsers a test starts itself with
subprocess.Popen and a debugging port did not pass it, testkit's
_start_fresh_browser and the copies of _start_browser in the tests.

This reads testkit and every Python file under a tests folder, of every
app, core, gui and server, conftest files included, and finds each place
that starts a program, by subprocess, asyncio.create_subprocess_exec,
os.spawn or exec, or a name bound to one of them. It reads the command
line through list and tuple literals, f-strings, + joins, % and format, a
string split into words, the names of the function and the module, a name
imported from testkit or a file beside it, and a function that returns
it. A start inside a string, a sample another census reads, is not code
and is not a start.

Three kinds of start have to hold --use-mock-keychain, before "--" and
before any address the browser is given.

- One whose command line gives a browser a profile, a debugging port or
  headless mode.
- One that stands in for the Popen of a product module that starts a
  browser and hands the real Popen the command line it was given, as
  test_browser_launch does to run browser._launch for real. That module is
  found by reading the product code for the same switches.
- One whose command line cannot be read whole and whose program is named
  for a browser.

A test that hands a real browser on disk to such a product start, with
the real Popen under it and no stand-in, is found as well, read from the
names of the code on the way. The person's own sign-in start,
browser._launch, never takes the switch. It is their own profile and keeps
its cookies in the real Keychain, and test_browser_launch holds it to that.

It needs no browser.
"""
import ast
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TESTKIT = REPO / "core" / "paperpull_core" / "testkit.py"
MOCK = "--use-mock-keychain"
# What makes a command line a browser's, written as patterns rather than the
# switches themselves: the census in
# test_every_fresh_browser_draws_before_an_app_attaches takes a string
# holding the bare debugging port switch for a browser start.
BROWSER_SWITCH = re.compile(r"^--(remote-debugging-(port|pipe)|user-data-dir|headless)(=|$)")
SWITCH_IN_TEXT = re.compile(r"--(remote-debugging-(port|pipe)|user-data-dir|headless)")
PROGRAM_OF_A_BROWSER = re.compile(r"chrom|msedge|edge\b|edge\.exe|brave", re.I)
# How the code that names a program can say it is a browser.
NAMED_FOR_A_BROWSER = re.compile(r"chrom|msedge|\bedge\b|browser|executable_path|\bexe\b", re.I)
# How a test names a real browser on disk, Playwright's own or a fixture's.
A_REAL_BROWSER = re.compile(r"executable_path|browser_exe|chromium_exe|chrome_exe")

FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)
# One word of a command line that could not be read, and any number of them.
ONE, MANY = "<one word>", "<any words>"
UNREAD = (ONE, MANY)
PYTHON = "<python>"
# Past this many ways one command line can come out, the rest are left out.
WAYS = 32
DEEP = 8

STARTERS = {"subprocess", "asyncio", "os"}
SUBPROCESS_STARTS = {"Popen", "run", "call", "check_call", "check_output",
                     "getoutput", "getstatusoutput"}
ASYNC_STARTS = {"create_subprocess_exec", "create_subprocess_shell"}
SKIPPED = ("node_modules", "build", "dist", "__pycache__")


def _os_start(name) -> bool:
    return name == "system" or name.startswith(("spawn", "posix_spawn")) or re.fullmatch(
        r"exec(l|le|lp|lpe|v|ve|vp|vpe)", name) is not None


def start_kind(owner, name):
    """How owner.name starts a program, "argv" for a command line in its
    first argument, "words" for one word per argument, "shell" for one
    string, or None when it starts none."""
    if owner == "subprocess" and name in SUBPROCESS_STARTS:
        return "shell" if name.startswith("get") else "argv"
    if owner == "asyncio" and name in ASYNC_STARTS:
        return "words" if name.endswith("exec") else "shell"
    if owner == "os" and _os_start(name):
        return "shell" if name == "system" else "words"
    return None


def python_files(root: Path):
    """Every .py file under root, never going into a hidden folder, where a
    worktree's .venv links to a whole Python install, or a built one."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIPPED)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(folder) / name


def _is_test_code(path) -> bool:
    return path == TESTKIT or "tests" in path.relative_to(REPO).parts[:-1]


def files_read():
    yield TESTKIT
    for path in python_files(REPO):
        if path != TESTKIT and _is_test_code(path):
            yield path


class Start:
    def __init__(self, call, kind, name, ways):
        self.call, self.kind, self.name, self.ways = call, kind, name, ways
        self.line = call.lineno


class Module:
    """One file's code, read for the programs it starts and their command
    lines. others maps the last name of a module it can import to that
    module, read on its own."""

    def __init__(self, source: str, path: Path = None, others=None):
        self.path = path
        self.tree = ast.parse(source)
        self.others = others if others is not None else {}
        self._up, self._starts = None, None
        self.modules = {m: set() for m in STARTERS}
        self.from_modules, self.imported, self.full = {}, {}, {}
        nodes = list(ast.walk(self.tree))
        for node in nodes:
            if isinstance(node, ast.Import):
                for a in node.names:
                    last = a.name.split(".")[-1]
                    self.full[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                    if a.name in self.modules:
                        self.modules[a.name].add(a.asname or a.name)
                    elif last in self.others and (a.asname or "." not in a.name):
                        self.imported[a.asname or a.name] = (last, None)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                last = mod.split(".")[-1]
                for a in node.names:
                    self.full[a.asname or a.name] = (mod + "." + a.name).lstrip(".")
                    if mod in self.modules:
                        self.from_modules[a.asname or a.name] = (mod, a.name)
                    elif a.name in self.others:
                        self.imported[a.asname or a.name] = (a.name, None)
                    elif last in self.others:
                        self.imported[a.asname or a.name] = (last, a.name)
        self.functions, self._tables, self.may_hold_a_start = {}, {}, set()
        for node in nodes:
            if isinstance(node, FUNCTION):
                self.functions.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.Assign) and isinstance(node.value, (ast.Attribute, ast.Name)):
                self.may_hold_a_start |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    @property
    def up(self):
        if self._up is None:
            self._up = {child: node for node in ast.walk(self.tree)
                        for child in ast.iter_child_nodes(node)}
        return self._up

    def other(self, last):
        return self.others.get(last)

    # -- what starts a program ------------------------------------------------

    def start_of(self, func, at, depth=0):
        """(kind, name) when calling func starts a program, else None."""
        if depth > 3:
            return None
        if isinstance(func, ast.Attribute):
            value, owner = func.value, None
            if isinstance(value, ast.Name):
                owner = next((m for m, names in self.modules.items() if value.id in names), None)
                if owner is None and value.id in STARTERS and value.id not in self.full:
                    owner = value.id
            elif isinstance(value, ast.Attribute) and value.attr in STARTERS:
                owner = value.attr
            kind = start_kind(owner, func.attr)
            return (kind, func.attr) if kind else None
        if isinstance(func, ast.Name):
            if func.id in self.from_modules:
                owner, name = self.from_modules[func.id]
                kind = start_kind(owner, name)
                return (kind, name) if kind else None
            found = self._value_of(func, at) if func.id in self.may_hold_a_start else None
            if found is not None:
                module, value, where = found
                if isinstance(value, (ast.Attribute, ast.Name)):
                    return module.start_of(value, where, depth + 1)
        return None

    def starts(self):
        """Each call here that starts a program, with every command line it
        can be given, each a tuple of words. A string is split into words,
        as a shell would."""
        if self._starts is not None:
            return self._starts
        out = []
        for call in ast.walk(self.tree):
            if not isinstance(call, ast.Call):
                continue
            found = self.start_of(call.func, call)
            if found is None:
                continue
            kind, name = found
            if kind == "argv":
                given = call.args[0] if call.args else next(
                    (k.value for k in call.keywords if k.arg == "args"), None)
                ways = self.words(given, call) if given is not None else [(MANY,)]
            elif kind == "shell":
                ways = self.words(call.args[0], call) if call.args else [(MANY,)]
            else:
                ways = [()]
                for arg in call.args:
                    if isinstance(arg, ast.Starred):
                        more = self.words(arg.value, call)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        more = self.words(arg, call)
                    else:
                        more = [(t,) for t in self.text(arg, call)]
                    ways = _cross(ways, more)
            out.append(Start(call, kind, name, ways))
        self._starts = out
        return out

    # -- reading a command line -----------------------------------------------

    def words(self, node, at, depth=0):
        """Every command line node can be, each a tuple of words."""
        if depth > DEEP or node is None:
            return [(MANY,)]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            ways = [()]
            for elt in node.elts:
                if isinstance(elt, ast.Starred):
                    ways = _cross(ways, self.words(elt.value, at, depth + 1))
                else:
                    ways = _cross(ways, [(t,) for t in self.text(elt, at, depth + 1)])
            return ways
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if _is_text(node):
                return _split_all(self.text(node, at, depth + 1))
            return _cross(self.words(node.left, at, depth + 1), self.words(node.right, at, depth + 1))
        if isinstance(node, (ast.Constant, ast.JoinedStr)) or (
                isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
            return _split_all(self.text(node, at, depth + 1))
        if isinstance(node, ast.IfExp):
            return (self.words(node.body, at, depth + 1)
                    + self.words(node.orelse, at, depth + 1))[:WAYS]
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in ("list", "tuple") and node.args:
                return self.words(node.args[0], at, depth + 1)
            if isinstance(f, ast.Attribute) and f.attr == "split" and not node.args:
                return _split_all(self.text(f.value, at, depth + 1))
            if (isinstance(f, ast.Attribute) and f.attr == "split"
                    and isinstance(f.value, ast.Name) and f.value.id == "shlex" and node.args):
                return _split_all(self.text(node.args[0], at, depth + 1))
            returned = self._returns(f, depth)
            if returned is not None:
                return [w for module, value in returned
                        for w in module.words(value, value, depth + 1)][:WAYS] or [(MANY,)]
            return [(MANY,)]
        if isinstance(node, (ast.Name, ast.Attribute)):
            found = self._value_of(node, at)
            if found is None:
                return [(MANY,)]
            module, value, where = found
            return module.words(value, where, depth + 1)
        return [(MANY,)]

    def text(self, node, at, depth=0):
        """Every string node can be, with what cannot be read as {} inside
        it, or ONE when none of it can be read."""
        if depth > DEEP:
            return [ONE]
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else [str(node.value)]
        if isinstance(node, ast.JoinedStr):
            out = [""]
            for part in node.values:
                if isinstance(part, ast.Constant):
                    out = [o + str(part.value) for o in out]
                else:
                    inner = self.text(part.value, at, depth + 1)
                    out = [o + (i if i not in UNREAD else "{}") for o in out for i in inner][:WAYS]
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.text(node.left, at, depth + 1), self.text(node.right, at, depth + 1)
            return [(a if a not in UNREAD else "{}") + (b if b not in UNREAD else "{}")
                    for a in left for b in right][:WAYS]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return [t if t not in UNREAD else ONE for t in self.text(node.left, at, depth + 1)]
        if isinstance(node, ast.IfExp):
            return (self.text(node.body, at, depth + 1) + self.text(node.orelse, at, depth + 1))[:WAYS]
        if isinstance(node, ast.BoolOp):
            return [t for v in node.values for t in self.text(v, at, depth + 1)][:WAYS]
        if isinstance(node, ast.Attribute) and node.attr == "executable" and isinstance(
                node.value, ast.Name) and node.value.id == "sys":
            return [PYTHON]
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "format":
                return [t if t not in UNREAD else ONE for t in self.text(f.value, at, depth + 1)]
            if isinstance(f, ast.Name) and f.id in ("str", "Path") and node.args:
                return self.text(node.args[0], at, depth + 1)
            if (isinstance(f, ast.Attribute) and f.attr == "which") or (
                    isinstance(f, ast.Name) and f.id == "which"):
                return self.text(node.args[0], at, depth + 1) if node.args else [ONE]
            returned = self._returns(f, depth)
            if returned is not None:
                return [t for module, value in returned
                        for t in module.text(value, value, depth + 1)][:WAYS] or [ONE]
            return [ONE]
        if isinstance(node, (ast.Name, ast.Attribute)):
            found = self._value_of(node, at)
            if found is None:
                return [ONE]
            module, value, where = found
            return module.text(value, where, depth + 1)
        return [ONE]

    # -- following names --------------------------------------------------------

    def scopes(self, node):
        """The functions node is inside, the nearest first."""
        out = []
        while node in self.up:
            node = self.up[node]
            if isinstance(node, FUNCTION):
                out.append(node)
        return out

    @staticmethod
    def own_nodes(body):
        """The code of these statements, without the functions and classes
        inside them."""
        stack = list(body)
        while stack:
            node = stack.pop()
            yield node
            stack.extend(n for n in ast.iter_child_nodes(node)
                         if not isinstance(n, FUNCTION + (ast.ClassDef, ast.Lambda)))

    @staticmethod
    def params(fn) -> set:
        args = fn.args
        return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs
                + [args.vararg, args.kwarg] if a is not None}

    @staticmethod
    def _bound(node):
        """Each (name, value) node binds, value ONE for a binding with no
        value to read (a loop, a with, an unpacked tuple)."""
        out = []
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.append((target.id, node.value))
                else:
                    out += [(t.id, ONE) for t in ast.walk(target) if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            out.append((name, ast.BinOp(left=ast.Name(id=name, ctx=ast.Load()), op=ast.Add(),
                                        right=node.value) if isinstance(node.op, ast.Add) else ONE))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.append((node.target.id, node.value if node.value is not None else ONE))
        elif isinstance(node, ast.NamedExpr):
            out.append((node.target.id, node.value))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.append((node.name, ONE))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension, ast.withitem)):
            target = getattr(node, "target", None) or getattr(node, "optional_vars", None)
            if target is not None:
                out += [(t.id, ONE) for t in ast.walk(target) if isinstance(t, ast.Name)]
        return out

    def _last_binding(self, scope, name, before):
        """(key, node, value) for the last binding of name in scope's own
        code before the line, or None."""
        table = self._tables.get(id(scope))
        if table is None:
            table = {}
            body = scope.body
            for node in self.own_nodes(body):
                for bound, value in self._bound(node):
                    key = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
                    table.setdefault(bound, []).append((key, node, value))
            self._tables[id(scope)] = table
        best = None
        for key, node, value in table.get(name, ()):
            if before is not None and key[0] >= before:
                continue
            if best is None or key >= best[0]:
                best = (key, node, value)
        return best

    def _value_of(self, node, at):
        """(module, value, where) for the value a name or module.name holds
        where at reads it, or None when it cannot be read."""
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in self.imported:
                last, _ = self.imported[node.value.id]
                other = self.other(last)
                if other is not None:
                    return other._value_of(ast.Name(id=node.attr, ctx=ast.Load()), None)
            return None
        if not isinstance(node, ast.Name):
            return None
        name = node.id
        line = getattr(at, "lineno", None)
        for fn in self.scopes(at) if at is not None else []:
            found = self._last_binding(fn, name, line)
            if found is not None:
                _, where, value = found
                return None if value is ONE else (self, value, where)
            if name in self.params(fn):
                return None
            line = None
        found = self._last_binding(self.tree, name, None)
        if found is not None:
            _, where, value = found
            return None if value is ONE else (self, value, where)
        if name in self.imported:
            last, there = self.imported[name]
            other = self.other(last)
            if other is not None and there is not None:
                return other._value_of(ast.Name(id=there, ctx=ast.Load()), None)
        return None

    def _returns(self, func, depth):
        """[(module, value)] for what a function called here returns, or
        None when it is not a function this can read."""
        if depth > DEEP - 2:
            return None
        module, name = self, None
        if isinstance(func, ast.Name):
            name = func.id
            if name not in self.functions and name in self.imported:
                last, name = self.imported[name]
                module = self.other(last)
        elif (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
              and func.value.id in self.imported):
            module = self.other(self.imported[func.value.id][0])
            name = func.attr
        if module is None or not name or name not in module.functions:
            return None
        out = []
        for fn in module.functions[name]:
            out += [(module, n.value) for n in module.own_nodes(fn.body)
                    if isinstance(n, ast.Return) and n.value is not None]
        return out or None

    # -- which starts are held to the rule ----------------------------------

    def holder(self, start):
        """The function a start is in and the parameters its command line
        is read from, or (None, set())."""
        scopes = self.scopes(start.call)
        if not scopes:
            return None, set()
        fn = scopes[0]
        params = self.params(fn) - {"self", "cls"}
        given = start.call.args[:1] if start.kind != "words" else start.call.args
        read, seen = set(), set()
        stack = list(given)
        while stack:
            node = stack.pop()
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and n.id not in seen:
                    seen.add(n.id)
                    read.add(n.id)
                    found = self._last_binding(fn, n.id, start.line)
                    if found is not None and found[2] is not ONE:
                        stack.append(found[2])
        return fn, read & params

    def program_guard(self, start, fn, params):
        """What an if around the start says its program is, as texts, when
        it compares the first word of a parameter, else None."""
        node = start.call
        while node in self.up and node is not fn:
            parent = self.up[node]
            if isinstance(parent, ast.If) and any(node is s for s in parent.body):
                test = parent.test
                if (isinstance(test, ast.Compare) and len(test.ops) == 1
                        and isinstance(test.ops[0], ast.Eq)
                        and isinstance(test.left, ast.Subscript)
                        and isinstance(test.left.value, ast.Name) and test.left.value.id in params
                        and isinstance(test.left.slice, ast.Constant) and test.left.slice.value == 0):
                    return self.text(test.comparators[0], parent)
            node = parent
        return None

    def stands_in_for(self, fn, browser_starts) -> set:
        """The start names of browser starting modules fn is put in place
        of by a setattr here, by its own name or as the class it calls."""
        names = {fn.name}
        parent = self.up.get(fn)
        if fn.name == "__call__" and isinstance(parent, ast.ClassDef):
            names = {parent.name}
        out = set()
        for call in ast.walk(self.tree):
            if not (isinstance(call, ast.Call) and _name(call.func) == "setattr"):
                continue
            args = call.args
            if len(args) >= 3 and isinstance(args[1], ast.Constant):
                target, attr, value = ast.unparse(args[0]), args[1].value, args[2]
            elif len(args) == 2 and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                target, _, attr = args[0].value.rpartition(".")
                value = args[1]
            else:
                continue
            handed = value.func if isinstance(value, ast.Call) else value
            if not (isinstance(handed, ast.Name) and handed.id in names):
                continue
            parts = target.split(".")
            owner = parts[-1]
            if owner not in STARTERS:
                continue
            if len(parts) == 1:
                modules = set(browser_starts)
            else:
                full = self.full.get(parts[0], parts[0])
                modules = {(full + "." + ".".join(parts[1:-1])).strip(".").split(".")[-1]}
            if any(attr in browser_starts.get(m, set()) for m in modules):
                out.add(attr)
        return out

    def named_for_a_browser(self, start) -> bool:
        """Whether the code naming the start's program says it is a browser."""
        given = start.call.args[0] if start.call.args else None
        if given is None:
            return False
        texts, node, at = [], given, start.call
        for _ in range(4):
            if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
                node = node.elts[0]
                node = node.value if isinstance(node, ast.Starred) else node
            texts.append(ast.unparse(node))
            found = self._value_of(node, at) if isinstance(node, (ast.Name, ast.Attribute)) else None
            if found is None or found[0] is not self:
                break
            _, node, at = found
        return any(NAMED_FOR_A_BROWSER.search(t) for t in texts)


def _name(func) -> str:
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _is_text(node) -> bool:
    return isinstance(node, (ast.Constant, ast.JoinedStr)) or (
        isinstance(node, ast.BinOp) and (_is_text(node.left) or _is_text(node.right))
        and not isinstance(node.left, (ast.List, ast.Tuple)))


def _split_all(texts):
    return [tuple(t.split()) if t not in UNREAD else (MANY,) for t in texts]


def _cross(lefts, rights):
    return [a + b for a in lefts for b in rights][:WAYS]


def is_a_browser(way) -> bool:
    return any(BROWSER_SWITCH.match(w) for w in way if w not in UNREAD)


def read_whole(way) -> bool:
    return bool(way) and all(w not in UNREAD for w in way[1:]) and way[0] != MANY


def not_a_browser_program(way) -> bool:
    return bool(way) and way[0] not in UNREAD and not PROGRAM_OF_A_BROWSER.search(way[0])


def switch_problem(way) -> str:
    """Why this command line does not keep off the Keychain, or ""."""
    if MOCK not in way:
        return "no %s" % MOCK
    at = way.index(MOCK)
    if "--" in way[:at]:
        return "%s after the end of the switches" % MOCK
    if any(w not in UNREAD and not w.startswith("-") for w in way[1:at]):
        return "%s after an address" % MOCK
    return ""


def held(module, start, browser_starts):
    """Why the start has to hold the switch, or "" when it need not."""
    if any(is_a_browser(w) for w in start.ways):
        return "a browser's command line"
    fn, params = module.holder(start)
    if fn is not None and params:
        guard = module.program_guard(start, fn, params)
        stands_in = module.stands_in_for(fn, browser_starts)
        if stands_in and not (guard and all(t not in UNREAD and not PROGRAM_OF_A_BROWSER.search(t)
                                            for t in guard)):
            return "stands in for the %s of a module that starts a browser" % "/".join(sorted(stands_in))
    if all(not_a_browser_program(w) or read_whole(w) for w in start.ways):
        return ""
    if module.named_for_a_browser(start):
        return "a browser's program with a command line it cannot read whole"
    return ""


def problems(module, name, browser_starts) -> list:
    out = []
    for start in module.starts():
        why = held(module, start, browser_starts)
        if not why:
            continue
        ways = [w for w in start.ways if is_a_browser(w)] or start.ways
        for wrong in sorted({switch_problem(w) for w in ways} - {""}):
            out.append("%s:%d %s, %s" % (name, start.line, why, wrong))
    return out


class Others(dict):
    """The modules a file can import, read only when they are asked for."""

    def __init__(self, paths, cache):
        super().__init__()
        self.paths, self.cache = paths, cache

    def __contains__(self, last):
        return last in self.paths

    def get(self, last, default=None):
        path = self.paths.get(last)
        if path is None:
            return default
        if path not in self.cache:
            self.cache[path] = Module(path.read_text(encoding="utf-8"), path)
        return self.cache[path]


def read_all():
    """Each file, read with testkit and the files beside it as what it can
    import."""
    paths = list(files_read())
    by_folder = {}
    for path in paths:
        by_folder.setdefault(path.parent, {})[path.stem] = path
    cache, out = {}, {}
    for path in paths:
        beside = dict(by_folder[path.parent])
        beside.pop(path.stem, None)
        beside["testkit"] = TESTKIT
        out[path] = Module(path.read_text(encoding="utf-8"), path, Others(beside, cache))
    return out


def product_browser_starts() -> dict:
    """{module's last name: the start names it starts a browser with}, read
    from every product file that names a browser's switch."""
    out = {}
    for path in python_files(REPO):
        if _is_test_code(path):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if not SWITCH_IN_TEXT.search(source):
            continue
        try:
            module = Module(source, path)
        except SyntaxError:
            continue
        for start in module.starts():
            if any(is_a_browser(w) for w in start.ways):
                out.setdefault(path.stem, set()).add(start.name)
    return out


MODULES = read_all()
BROWSER_STARTS = product_browser_starts()


def _rel(path) -> str:
    return path.relative_to(REPO).as_posix()


def test_every_browser_a_test_starts_uses_the_mock_keychain():
    found = [p for module in MODULES.values() for p in problems(module, _rel(module.path),
                                                                BROWSER_STARTS)]
    assert found == [], "add %r to these command lines, before any \"--\" or address: %s" % (
        MOCK, found)


def test_the_product_starts_a_browser_where_it_is_known_to():
    """The sign-in window, browser._launch, starts a browser by Popen. The
    stand-ins above are held to the switch only because this is found."""
    assert "Popen" in BROWSER_STARTS.get("browser", set()), BROWSER_STARTS


def held_starts():
    return sorted("%s:%d" % (_rel(m.path), s.line) for m in MODULES.values()
                  for s in m.starts() if held(m, s, BROWSER_STARTS))


def test_the_census_finds_the_browsers_tests_start():
    """A file whose start stops being found has moved it where this cannot
    see, and this says so rather than letting it drop out quietly. The
    files are what the census found on 2026-11-17, not what it reads."""
    files = {start.rsplit(":", 1)[0] for start in held_starts()}
    known = {
        "core/paperpull_core/testkit.py",
        "core/tests/test_a_printed_page_goes_back_to_the_screen.py",
        "core/tests/test_browser_launch.py",
        "apps/bestbuy/tests/test_a_list_that_never_came.py",
        "apps/bestbuy/tests/test_signed_out_mid_run.py",
        "apps/github/tests/test_signed_out_mid_run.py",
        "apps/target/tests/test_a_receipt_control_it_could_not_read.py",
        "apps/target/tests/test_every_invoice_of_an_order.py",
        "apps/target/tests/test_the_list_already_open.py",
        "apps/walmart/tests/test_a_list_that_never_came.py",
        "apps/walmart/tests/test_signed_out_mid_run.py",
    }
    assert known <= files, sorted(known - files)
    assert len(MODULES) > 800, "the census read only %d files" % len(MODULES)


# -- a test that runs the product's own browser start ----------------------

def product_starters(browser_starts) -> dict:
    """{module's last name: its functions that start a browser, and every
    function there that calls one}."""
    out = {}
    for path in python_files(REPO):
        if _is_test_code(path) or path.stem not in browser_starts:
            continue
        module = Module(path.read_text(encoding="utf-8", errors="replace"), path)
        found = {fn.name for start in module.starts() if any(is_a_browser(w) for w in start.ways)
                 for fn in module.scopes(start.call)[:1]}
        while True:
            more = {name for name, fns in module.functions.items() if name not in found
                    for fn in fns for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in found}
            if not more:
                break
            found |= more
        out.setdefault(path.stem, set()).update(found)
    return out


def _setattr_names(nodes) -> set:
    out = set()
    for node in nodes:
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and _name(call.func) == "setattr" and call.args:
                first = call.args[0]
                if len(call.args) >= 3 and isinstance(call.args[1], ast.Constant):
                    out.add(call.args[1].value)
                elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.add(first.value.rpartition(".")[2])
    return out


def _fixtures(module) -> dict:
    """The fixtures of the module and of a conftest beside it, by name."""
    trees = [module.tree]
    conftest = module.path.parent / "conftest.py"
    if conftest.is_file() and conftest != module.path:
        trees.insert(0, ast.parse(conftest.read_text(encoding="utf-8")))
    return {fn.name: fn for tree in trees for fn in ast.walk(tree)
            if isinstance(fn, FUNCTION) and any(
                _name(d.func if isinstance(d, ast.Call) else d) == "fixture"
                for d in fn.decorator_list)}


def runs_a_product_start(module, starters, browser_starts) -> list:
    """Each test or fixture here that hands a real browser on disk to a
    product function that starts one, itself or through a function of this
    file, with no setattr of that module's Popen or of the function on the
    way. The setattr can be in the test, a function it calls here, a
    function it is inside, a fixture it takes or an autouse fixture, here or
    in a conftest beside it.

    A test that runs the start with a program of its own, a shell script
    named chrome say, or that stops it before any start, is not one. That a
    real browser is handed is read from the names of the code on the way,
    so this is a net under the census above rather than a proof."""
    fixtures = _fixtures(module)
    autouse = [fn for fn in fixtures.values() if any(
        isinstance(d, ast.Call) and any(k.arg == "autouse" for k in d.keywords)
        for d in fn.decorator_list)]
    every = [fn for fns in module.functions.values() for fn in fns]

    def calls(fn) -> set:
        return {n.func.id for n in Module.own_nodes(fn.body)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in module.functions}

    def reached(fn) -> set:
        out = set()
        for call in Module.own_nodes(fn.body):
            if not isinstance(call, ast.Call):
                continue
            f = call.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                last = module.full.get(f.value.id, f.value.id).split(".")[-1]
                if f.attr in starters.get(last, set()):
                    out.add((last, f.attr))
            elif isinstance(f, ast.Name) and f.id in module.full:
                mod, _, name = module.full[f.id].rpartition(".")
                last = mod.split(".")[-1]
                if name in starters.get(last, set()):
                    out.add((last, name))
        return out

    def patched_by(fn, seen=()) -> set:
        """The names fn sets, itself or through a function here it calls."""
        out = _setattr_names([fn])
        for name in calls(fn):
            for other in module.functions[name]:
                if other not in seen:
                    out |= patched_by(other, seen + (fn,))
        return out

    def patched_around(fn) -> set:
        around = [fn] + [fixtures[p] for p in Module.params(fn) if p in fixtures] + autouse
        around += module.scopes(fn)
        out = set()
        for each in around:
            out |= patched_by(each)
        return out

    def is_entry(fn) -> bool:
        return fn.name.startswith("test") or fn.name in fixtures

    out = []

    def check(fn, wants, path, seen):
        """Whether every way to fn, a function reaching wants, is patched."""
        patched = patched_around(fn)
        wants = {(last, name) for last, name in wants
                 if not patched & (browser_starts.get(last, set()) | starters[last])}
        if not wants:
            return
        if is_entry(fn):
            on_the_way = [fn] + [fixtures[p] for p in Module.params(fn) if p in fixtures]
            on_the_way += [f for name in path for f in module.functions.get(name, [])]
            if not any(A_REAL_BROWSER.search(ast.unparse(f)) for f in on_the_way):
                return
            for last, name in sorted(wants):
                out.append("%s %s calls %s.%s" % (_rel(module.path), " via ".join(path), last, name))
            return
        for caller in every:
            if caller not in seen and fn.name in calls(caller):
                check(caller, wants, [caller.name] + path, seen + (caller,))

    for fn in every:
        found = reached(fn)
        if found:
            check(fn, found, [fn.name], (fn,))
    return sorted(set(out))


def test_a_test_that_runs_a_product_browser_start_puts_its_own_popen_under_it():
    """With its own Popen in place, the start is either a stand-in or one
    the census above reads."""
    starters = product_starters(BROWSER_STARTS)
    assert "_launch" in starters.get("browser", set()), starters
    found = [p for module in MODULES.values() if module.path != TESTKIT
             for p in runs_a_product_start(module, starters, BROWSER_STARTS)]
    assert found == []


# -- the census on samples ------------------------------------------------------
#
# Each sample is a file with {flag} where the switch goes, as a list item,
# or {word} inside a string. It must be found without the switch and pass
# with it. The debugging port switch is written as @PORT and put together at
# run time, so no string here holds it bare (the module docstring says why).
# Where the sample's program is named "program" rather than for a browser,
# only the reading of the command line can find it.

PORT_SWITCH = "--remote-debugging" + "-port"

SAMPLES = {
    "a list": '''
import subprocess
def start(exe, profile):
    return subprocess.Popen([exe, "--headless=new", "@PORT=0", {flag}"--user-data-dir=%s" % profile])
''',
    "a tuple": '''
import subprocess
def start(exe):
    return subprocess.Popen((exe, "@PORT=0", {flag}"about:blank"))
''',
    "an f-string port": '''
import subprocess
def start(program, port):
    return subprocess.Popen([program, f"@PORT={port}", {flag}"--no-first-run"])
''',
    "a + join": '''
import subprocess
def start(program, port):
    return subprocess.Popen([program] + ["@PORT=" + port] + [{flag}"--no-first-run"])
''',
    "a module variable spread": '''
import subprocess
ARGS = ["--headless=new", "@PORT=0", {flag}]
def start(exe):
    return subprocess.Popen([exe, *ARGS, "about:blank"])
''',
    "a name in the function": '''
from subprocess import Popen
def start(exe):
    cmd = [exe, "@PORT=0"]
    cmd += [{flag}"about:blank"]
    return Popen(cmd)
''',
    "a helper that builds it": '''
import subprocess
def argv(exe):
    return [exe, "@PORT=0", {flag}"about:blank"]
def start(exe):
    return subprocess.Popen(argv(exe))
''',
    "asyncio": '''
import asyncio
async def start(exe):
    return await asyncio.create_subprocess_exec(exe, "@PORT=0", {flag}"about:blank")
''',
    "asyncio with a spread": '''
import asyncio
ARGS = ("@PORT=0", {flag})
async def start(exe):
    return await asyncio.create_subprocess_exec(exe, *ARGS)
''',
    "a string split": '''
import subprocess
def start(exe):
    return subprocess.Popen([exe, *"@PORT=0 {word} --no-first-run".split()])
''',
    "one string": '''
import subprocess
def start():
    return subprocess.Popen("chromium @PORT=0 {word} about:blank", shell=True)
''',
    "a name bound to Popen": '''
import subprocess
START = subprocess.Popen
def start(exe):
    return START([exe, "@PORT=0", {flag}])
''',
    "os.spawnv": '''
import os
def start(exe):
    return os.spawnv(os.P_NOWAIT, exe, [exe, "@PORT=0", {flag}"about:blank"])
''',
    "a stand-in for the sign-in Popen": '''
import subprocess
from paperpull_core import browser
def test_it(monkeypatch):
    real = subprocess.Popen
    def popen(cmd, **kwargs):
        cmd = [cmd[0], {flag}*cmd[1:]]
        return real(cmd, **kwargs)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
''',
    "a browser program with a command line it cannot read": '''
import subprocess
def start(chromium_exe, args):
    return subprocess.Popen([chromium_exe, {flag}*args])
''',
}

# A sample whose own testkit holds the command line, imported from there.
TESTKIT_SAMPLE = '''
ARGS = ["--headless=new", "@PORT=0", {flag}]
def argv(exe):
    return [exe, *ARGS]
'''
FROM_TESTKIT = '''
import subprocess
from paperpull_core import testkit
from paperpull_core.testkit import ARGS
def start(exe):
    subprocess.Popen(testkit.argv(exe))
    subprocess.Popen([exe, *ARGS])
'''
SAMPLE_STARTS = {"browser": {"Popen"}}


def _sample(text, flag):
    return text.replace("@PORT", PORT_SWITCH).replace("{word}", MOCK if flag else "").replace(
        "{flag}", ('"%s", ' % MOCK) if flag else "")


def _found(source, others=None):
    module = Module(source, Path("sample.py"), others)
    return problems(module, "sample.py", SAMPLE_STARTS), module.starts()


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_a_start_without_the_switch_is_found(name):
    wrong, starts = _found(_sample(SAMPLES[name], flag=False))
    assert starts, "the census did not see the start in %r" % name
    assert wrong, "the census passed %r without the switch" % name


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_the_same_start_with_the_switch_passes(name):
    wrong, starts = _found(_sample(SAMPLES[name], flag=True))
    assert starts and wrong == [], wrong


@pytest.mark.parametrize("flag", [False, True])
def test_a_command_line_from_testkit_is_read_there(flag):
    kit = Module(_sample(TESTKIT_SAMPLE, flag), Path("testkit.py"))
    wrong, starts = _found(FROM_TESTKIT, {"testkit": kit})
    assert len(starts) == 2
    assert all(is_a_browser(w) for s in starts for w in s.ways)
    assert (wrong == []) is flag, wrong


@pytest.mark.parametrize("tail", ['"--", "about:blank", "%s"' % MOCK, '"about:blank", "%s"' % MOCK])
def test_the_switch_after_the_end_of_the_switches_or_an_address_is_found(tail):
    wrong, _ = _found('import subprocess\nsubprocess.Popen([exe, "%s=0", %s])\n'
                      % (PORT_SWITCH, tail))
    assert wrong, tail


def test_a_start_inside_a_string_is_not_a_start():
    """Another census's sample code is text, not a start."""
    source = "SAMPLE = '''\nimport subprocess\nsubprocess.Popen([exe, \"%s=0\"])\n'''\n" % PORT_SWITCH
    assert _found(source) == ([], [])


def test_other_programs_are_left_alone():
    """Python, git, node and a program whose whole command line can be read
    and gives no browser switch need nothing, nor does a stand-in for a
    module that starts no browser, nor one that hands on only Python."""
    source = '''
import shutil, subprocess, sys
from paperpull_core import browser, packager
def run(args, script):
    subprocess.run([sys.executable, script, *args])
    subprocess.check_output(["git", "rev-parse", "HEAD"])
    subprocess.run([shutil.which("node"), "-e", script, *args])
    subprocess.Popen([exe, "--version"])
def test_it(monkeypatch):
    real = subprocess.run
    def run(cmd, **kw):
        return real(cmd, **kw)
    monkeypatch.setattr(packager.subprocess, "run", run)
    def popen(cmd, **kw):
        if cmd[0] == sys.executable:
            return subprocess.Popen(cmd, **kw)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
'''
    wrong, starts = _found(source)
    assert len(starts) == 6 and wrong == [], wrong


RUNS_THE_SIGN_IN = '''
import subprocess
from paperpull_core import browser
def start(exe, tmp_path):
    return browser._launch(exe, browser.CHROMIUM, tmp_path, "9", "about:blank")
def test_it(monkeypatch, tmp_path, pw):
    {patch}
    start({exe}, tmp_path)
'''


@pytest.mark.parametrize("patch,exe,found", [
    ("pass", "pw.chromium.executable_path", True),
    ('monkeypatch.setattr(browser.subprocess, "Popen", lambda cmd, **kw: None)',
     "pw.chromium.executable_path", False),
    ('monkeypatch.setattr(browser, "_launch", lambda *a, **kw: None)',
     "pw.chromium.executable_path", False),
    ("pass", "str(tmp_path / 'chrome.sh')", False),
])
def test_a_test_that_runs_the_sign_in_start_with_the_real_popen_is_found(patch, exe, found, tmp_path):
    path = tmp_path / "test_sample.py"
    path.write_text(RUNS_THE_SIGN_IN.replace("{patch}", patch).replace("{exe}", exe),
                    encoding="utf-8")
    module = Module(path.read_text(encoding="utf-8"), path)
    module.path = REPO / "core" / "tests" / "test_sample.py"
    starts = {"browser": {"_launch", "_try_each"}}
    assert bool(runs_a_product_start(module, starts, {"browser": {"Popen"}})) is found


def test_no_product_file_names_the_switch():
    """The switch is for the browsers tests start. A product file that
    named it could hand it to the person's own browser, whose cookies are
    then kept under a key that is not in their Keychain."""
    named = [_rel(path) for path in python_files(REPO)
             if not _is_test_code(path) and MOCK in path.read_text(encoding="utf-8", errors="replace")]
    assert named == []
