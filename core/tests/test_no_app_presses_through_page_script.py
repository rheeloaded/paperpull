"""No app presses a control through page script unless that press was
reviewed, and each reviewed press says why it is safe.

Playwright's own click checks that the element would receive the press,
waits while something covers it, and refuses when something else would
take it. A press made through page script, el.click() run inside the page
by evaluate, skips all of that. It reaches the element itself whatever is
drawn over it, a hidden element included, and when Playwright's own press
had reached the page before it raised, it is a second press.

Twelve apps made such a press whenever Playwright's own click raised,
thirteen presses in all, and three more made presses of their own this
way. A review after the change that stopped forced presses found them,
since test_no_app_forces_a_press reads Python and never JavaScript. The
fallbacks now go through paperpull_core.pressing.press_once, which makes
the press through the page at most once and only when it is safe. The
presses that remain are in REVIEWED, each with its site's reason.

So this reads every app, the core, the panel and the server, apart from
their tests, and finds JavaScript two ways. Every string written in them,
and every script handed to Playwright's evaluate and its kin or to the
DevTools protocol, followed back through names, imports, joins, formats,
a module's own callers and the helpers that pass a script along, so a
press put together from pieces is found too. A script that cannot be
followed back to what it says fails here, unless it is in READ_AS_DATA
with the reason it holds no script.

A press in JavaScript is a call of click() on anything, straight or
through call, apply or bind, an event of a press handed to dispatchEvent or
one this cannot read, a form's submit or requestSubmit, the handler of a
press called straight, el.onclick() or el.onmousedown() say, an event built
by hand with an init...Event call, and jQuery's trigger of a press.

Each press found has to be in REVIEWED, and each entry there still found,
so the list says what the code does.
"""
import ast
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What ships, apps and the core and what the panel and the server run.
ROOTS = ("apps", "core", "gui", "server")

# Every way Playwright runs a script in a page, by the position and the
# name the script is passed under.
EVALUATORS = {"evaluate": (0, "expression"), "evaluate_handle": (0, "expression"),
              "evaluate_all": (0, "expression"), "wait_for_function": (0, "expression"),
              "eval_on_selector": (1, "expression"), "eval_on_selector_all": (1, "expression"),
              "add_init_script": (0, "script"), "add_script_tag": (None, "content")}

# And the DevTools protocol's own, by the key that holds the script.
CDP = {"Runtime.evaluate": "expression", "Runtime.callFunctionOn": "functionDeclaration",
       "Runtime.compileScript": "expression", "Page.addScriptToEvaluateOnNewDocument": "source"}

# Events that, dispatched to an element, are a press nobody made.
PRESS_EVENTS = frozenset(("click", "dblclick", "auxclick", "mousedown", "mouseup", "pointerdown",
                          "pointerup", "touchstart", "touchend", "keydown", "keyup", "keypress",
                          "submit"))

# A press in JavaScript, by what it is called here.
PRESSES = (
    ("click()", re.compile(r"\.\s*click\s*\(\s*\)")),
    ("click()", re.compile(r"""\[\s*(['"`])click\1\s*\]\s*\(""")),
    ("click.call()", re.compile(r"\.\s*click\s*\.\s*(?:call|apply|bind)\s*\(")),
    ("submit.call()", re.compile(r"\.\s*(?:submit|requestSubmit)\s*\.\s*(?:call|apply|bind)\s*\(")),
    ("submit()", re.compile(r"\.\s*(?:submit|requestSubmit)\s*\(")),
    ("a handler called", re.compile(r"\.\s*on(?:%s)\s*(?:\.\s*(?:call|apply|bind)\s*)?\("
                                    % "|".join(sorted(PRESS_EVENTS)))),
    ("an event built by hand", re.compile(r"\binit(?:Mouse|Pointer|Touch|Keyboard|UI)?Event\s*\(")),
    ("trigger()", re.compile(r"""\.\s*trigger(?:Handler)?\s*\(\s*(['"`])(?:%s)\1"""
                             % "|".join(sorted(PRESS_EVENTS)))),
)
_DISPATCH = re.compile(r"\bdispatchEvent\s*\(")
_BUILT = re.compile(r"""\s*new\s+\w+\s*\(\s*(['"`])([\w:-]+)\1""")

# Every press made through page script that is still made, each with its
# site's reason, keyed by the file, the name of the script or of the
# function it is written in, and the kind of press.
REVIEWED = {
    ("core/paperpull_core/pressing.py", "_PRESS_JS", "click()"):
        "The press through the page that press_once makes at most once, after "
        "Playwright's own press raised. Only when every line of Playwright's account "
        "says it waited for the control or found it not ready, nothing a press brings "
        "came and the control heard no press, it is still on the page, the app's own "
        "guard and checks pass its words, and it is the thing on top in the middle of "
        "the window. In the same step it must still be on the page, have heard no "
        "press and have the words it had before Playwright pressed. What it cannot "
        "tell stops the run, and a control the page took away is not pressed at all. "
        "When this press itself raises it may have been made, and nothing more is "
        "pressed.",
    ("apps/adp/adp_site.py", "open_tax_statement_check", "click()"):
        "The last button on the page whose whole text is View statement, an "
        "SDF-BUTTON or a BUTTON found through every open shadow root, which on "
        "ADP's statements page is the Tax Statements card's own. It is pressed only "
        "after ADP has refused a tax statement for want of its identity check, so "
        "that ADP shows its prompt to the person, who answers it in the browser, "
        "and the statement ADP's viewer fetches once the check is passed is taken "
        "as it passes. Nothing checks whether it shows or what covers it. A check "
        "left unanswered ends the tax statements for the run, so it is not pressed "
        "again in that run.",
    ("apps/mtb/mtb_site.py", "_OPEN_TABLE_CLICK_JS", "click()"):
        "The first collapsed year heading on M&T's statements list, in a frame "
        "M&T serves, whose press lists that year through a GET. Its heading's words "
        "are read first and checked against the forbidden words, and the press then "
        "finds the first collapsed heading again in a call of its own. The loop "
        "stops the moment the count of collapsed years stops falling, so a heading "
        "that does not open is pressed once. Nothing checks what covers it, and "
        "paperpull_core.pressing reads only a page's main frame, so it could not "
        "check a heading in this frame.",
    ("apps/pge/pge_site.py", "_SAVE_BLOB_JS", "click()"):
        "A link this code makes itself, pointing at a PDF the page made, on the "
        "page's own origin and marked as a download, never one of the page's own "
        "controls, so nothing the page drew is pressed. It is the contributor's "
        "way, from the commit that made the capture work on a live account.",
    ("apps/pge/pge_site.py", "_SAVE_URL_JS", "click()"):
        "A link this code makes itself, to an address on the history's own origin, "
        "marked as a download, never one of the page's own controls. The page "
        "checks the origin once more before it presses.",
}

# Parts of a script that are not followed back, each a value put into a
# script rather than a script, with the reason, keyed by the file, the
# function the part is in and what the part is. Every script is followed
# to the end today, so this is empty.
READ_AS_DATA = {}


def is_test(path: Path) -> bool:
    parts = path.relative_to(REPO).parts
    return ("tests" in parts or path.name.startswith("test_")
            or path.name == "conftest.py" or ".venv" in parts
            or any(p.startswith(".") for p in parts))


def sources():
    out = []
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            # Pruned as the walk goes, so a linked environment is never
            # entered, which was most of the census's time.
            dirs[:] = sorted(d for d in dirs if d != "tests" and not d.startswith((".", "__")))
            out.extend(Path(folder) / f for f in files
                       if f.endswith(".py") and not f.startswith("test_") and f != "conftest.py")
    return sorted(p for p in out if not is_test(p))


# ---------------------------------------------------------------------------
# Presses in a piece of JavaScript
# ---------------------------------------------------------------------------

def presses_in(js: str) -> list:
    """Every press in `js`, as its kind, in order."""
    out = []
    for kind, pattern in PRESSES:
        out.extend((m.start(), kind) for m in pattern.finditer(js))
    for m in _DISPATCH.finditer(js):
        built = _BUILT.match(js, m.end())
        if built is None:
            out.append((m.start(), "dispatchEvent of an event it cannot read"))
        elif built.group(2).lower() in PRESS_EVENTS:
            out.append((m.start(), "dispatchEvent of %s" % built.group(2).lower()))
    return [kind for _at, kind in sorted(out)]


# ---------------------------------------------------------------------------
# Modules, read once
# ---------------------------------------------------------------------------

class Module:
    """One source file, parsed, with what its names are bound to."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.rel = path.relative_to(REPO).as_posix()
        except ValueError:
            # A source made up by a test of this census.
            self.rel = path.name
        self.text = path.read_text(encoding="utf-8-sig")
        self.tree = ast.parse(self.text)
        self.parent = {}
        self.functions = {}
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        # Names bound at module level, to every value they are given.
        self.values = {}
        # Names that are imports, to (module file, name in it or None).
        self.imports = {}
        for node in self.tree.body:
            for target, value in _assignments(node):
                self.values.setdefault(target, []).append(value)
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = self._import(node.module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = \
                        self._import(alias.name, None)

    def _import(self, module: str, name):
        """Where an import leads, as (file, name), or None when it leads
        outside what ships here."""
        parts = module.split(".")
        candidates = []
        if parts[0] == "paperpull_core":
            base = REPO / "core" / "paperpull_core"
            if len(parts) == 1:
                if name:
                    candidates.append((base / ("%s.py" % name), None))
                candidates.append((base / "__init__.py", name))
            else:
                candidates.append((base.joinpath(*parts[1:]).with_suffix(".py"), name))
        else:
            candidates.append((self.path.parent.joinpath(*parts).with_suffix(".py"), name))
        for path, what in candidates:
            if path.exists():
                return (path, what)
        return None

    def owner(self, node) -> str:
        """The name a string belongs to, the module-level name it is bound
        to, else the function it is written in, else <module>."""
        at = node
        while at in self.parent:
            up = self.parent[at]
            if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return up.name
            if up is self.tree:
                break
            at = up
        for target, _value in _assignments(at):
            return target
        return "<module>"

    def enclosing(self, node) -> list:
        """The functions around `node`, innermost first."""
        out = []
        at = node
        while at in self.parent:
            at = self.parent[at]
            if isinstance(at, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                out.append(at)
        return out


def _assignments(node):
    """(name, value) for each plain name a statement binds, a loop over a
    tuple or list written out included, element by element."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id, node.value
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
        yield node.target.id, node.value
    elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        yield node.target.id, node.value
    elif isinstance(node, (ast.For, ast.comprehension)):
        target, items = node.target, node.iter
        if isinstance(items, (ast.Tuple, ast.List)):
            for item in items.elts:
                if isinstance(target, ast.Name):
                    yield target.id, item
                elif isinstance(target, ast.Tuple) and isinstance(item, ast.Tuple) \
                        and len(target.elts) == len(item.elts):
                    for name, value in zip(target.elts, item.elts):
                        if isinstance(name, ast.Name):
                            yield name.id, value


_MODULES = {}


def module(path: Path) -> Module:
    path = Path(path)
    if path not in _MODULES:
        _MODULES[path] = Module(path)
    return _MODULES[path]


# ---------------------------------------------------------------------------
# Following a script back to what it says
# ---------------------------------------------------------------------------

class Read:
    """What a script says, as far as it could be followed. `text` is the
    script with every part that could not be read left out, `holes` says
    where those parts were, `literals` is each string it was made from,
    as (file, owner, line, text), once for every time it was read in, and
    `followed` every function whose callers handed it in, by (file,
    function)."""

    def __init__(self, text="", holes=(), literals=(), followed=()):
        self.text = text
        self.holes = list(holes)
        self.literals = list(literals)
        self.followed = set(followed)

    def __add__(self, other):
        return Read(self.text + other.text, self.holes + other.holes,
                    self.literals + other.literals, self.followed | other.followed)


def _hole(mod: Module, node, what: str) -> Read:
    fn = mod.enclosing(node)
    where = fn[0].name if fn and not isinstance(fn[0], ast.Lambda) else mod.owner(node)
    return Read("", [(mod.rel, where, what, getattr(node, "lineno", 0))])


def read(mod: Module, node, seen=frozenset(), depth=0) -> Read:
    """What `node`, a script's expression in `mod`, says."""
    if depth > 40:
        return _hole(mod, node, "too deep")
    key = (mod.rel, id(node))
    if key in seen:
        return Read()
    seen = seen | {key}
    nxt = depth + 1
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return Read(node.value, literals=[(mod.rel, mod.owner(node), node.lineno, node.value)])
        return Read()
    if isinstance(node, ast.JoinedStr):
        out = Read()
        for part in node.values:
            if isinstance(part, ast.Constant):
                out = out + read(mod, part, seen, nxt)
            elif isinstance(part, ast.FormattedValue):
                out = out + read(mod, part.value, seen, nxt)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return read(mod, node.left, seen, nxt) + read(mod, node.right, seen, nxt)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        template = read(mod, node.left, seen, nxt)
        values = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
        filled = [read(mod, v, seen, nxt) for v in values]
        return _format(template, filled)
    if isinstance(node, ast.IfExp):
        return read(mod, node.body, seen, nxt) + Read("\n") + read(mod, node.orelse, seen, nxt)
    if isinstance(node, (ast.List, ast.Tuple)):
        out = Read()
        for elt in node.elts:
            out = out + read(mod, elt, seen, nxt) + Read("\n")
        return out
    if isinstance(node, ast.Dict):
        out = Read()
        for value in node.values:
            out = out + read(mod, value, seen, nxt) + Read("\n")
        return out
    if isinstance(node, ast.Subscript):
        return read(mod, node.value, seen, nxt)
    if isinstance(node, ast.Call):
        return _read_call(mod, node, seen, nxt)
    if isinstance(node, ast.Name):
        return _read_name(mod, node, seen, nxt)
    if isinstance(node, ast.Attribute):
        base = node.value
        if isinstance(base, ast.Name) and base.id in mod.imports and mod.imports[base.id]:
            path, name = mod.imports[base.id]
            if name is None:
                other = module(path)
                if node.attr in other.values:
                    return _read_values(other, other.values[node.attr], seen, nxt)
                if node.attr in other.imports:
                    return _read_import(other, node.attr, seen, nxt)
        return _hole(mod, node, ast.unparse(node))
    return _hole(mod, node, ast.unparse(node))


def _format(template: Read, filled: list) -> Read:
    """`template` % `filled`, each %s, %r or %d taking the next value."""
    pieces = re.split(r"(%%|%[-#0 +]*\d*(?:\.\d+)?[srdif])", template.text)
    out = Read("", template.holes, template.literals, template.followed)
    values = list(filled)
    for piece in pieces:
        if piece == "%%":
            out.text += "%"
        elif re.fullmatch(r"%[-#0 +]*\d*(?:\.\d+)?[srdif]", piece or ""):
            if values:
                out = out + values.pop(0)
        else:
            out.text += piece
    for rest in values:
        out = out + rest
    return out


_DATA_CALLS = frozenset(("json.dumps", "_json.dumps", "repr", "int", "len", "float",
                         "bool", "round", "id"))


def _read_call(mod: Module, node: ast.Call, seen, depth) -> Read:
    func = node.func
    name = ast.unparse(func)
    if name in _DATA_CALLS:
        return Read()
    if isinstance(func, ast.Attribute):
        if func.attr in ("strip", "lstrip", "rstrip", "lower", "upper", "encode", "decode"):
            return read(mod, func.value, seen, depth)
        if func.attr == "replace" and len(node.args) == 2:
            base = read(mod, func.value, seen, depth)
            old, new = read(mod, node.args[0], seen, depth), read(mod, node.args[1], seen, depth)
            if not old.holes and not new.holes:
                base.text = base.text.replace(old.text, new.text)
                return base + Read("", new.holes + old.holes, new.literals + old.literals,
                                   new.followed | old.followed)
            return base + new
        if func.attr == "format":
            out = read(mod, func.value, seen, depth)
            for arg in list(node.args) + [k.value for k in node.keywords]:
                out = out + read(mod, arg, seen, depth)
            return out
        if func.attr == "join" and len(node.args) == 1:
            sep = read(mod, func.value, seen, depth)
            items = read(mod, node.args[0], seen, depth)
            return items + sep
        if name in ("textwrap.dedent", "inspect.cleandoc"):
            return read(mod, node.args[0], seen, depth) if node.args else Read()
    if isinstance(func, ast.Name) and func.id == "str" and node.args:
        return read(mod, node.args[0], seen, depth)
    # A function of the module's own, by what it returns.
    if isinstance(func, ast.Name) and len(mod.functions.get(func.id, ())) == 1 \
            and func.id not in mod.values:
        made = mod.functions[func.id][0]
        returned = _returns(made)
        if returned:
            return _read_values(mod, returned, seen, depth)
    return _hole(mod, node, name + "()")


def _read_values(mod: Module, values, seen, depth) -> Read:
    out = Read()
    for value in values:
        out = out + read(mod, value, seen, depth) + Read("\n")
    return out


def _read_import(mod: Module, name: str, seen, depth) -> Read:
    target = mod.imports.get(name)
    if not target:
        return _hole(mod, mod.tree, name)
    path, what = target
    other = module(path)
    if what is None:
        return _hole(mod, mod.tree, name)
    if what in other.values:
        return _read_values(other, other.values[what], seen, depth)
    if what in other.imports:
        return _read_import(other, what, seen, depth)
    return _hole(other, other.tree, what)


def _bound_otherwise(mod: Module, fn, name: str) -> bool:
    """Whether `fn` binds `name` some way _assignments cannot follow, a
    loop over anything not written out, a with, an except, an import, a
    walrus, or a target inside a tuple or a subscript."""
    for node in ast.walk(fn):
        targets = []
        if isinstance(node, (ast.For, ast.comprehension)) and _written_out(mod, node.iter) is None:
            targets.append(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            targets.append(node.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name == name:
            return True
        elif isinstance(node, ast.NamedExpr):
            targets.append(node.target)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((a.asname or a.name.split(".")[0]) == name for a in node.names):
                return True
        elif isinstance(node, ast.Assign):
            targets.extend(t for t in node.targets if not isinstance(t, ast.Name))
        for target in targets:
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(target)):
                return True
    return False


def _written_out(mod: Module, items):
    """`items` as the tuple or list written out it is, directly or as a
    name the module binds once to one, else None."""
    if isinstance(items, ast.Name) and len(mod.values.get(items.id, ())) == 1:
        items = mod.values[items.id][0]
    return items if isinstance(items, (ast.Tuple, ast.List)) else None


def _loops(mod: Module, fn) -> list:
    """Every loop in `fn` over a tuple or list written out, as a statement
    _assignments can read."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.comprehension)):
            items = _written_out(mod, node.iter)
            if items is not None and items is not node.iter:
                out.append(ast.For(target=node.target, iter=items, body=[], orelse=[]))
    return out


def _read_name(mod: Module, node: ast.Name, seen, depth) -> Read:
    name = node.id
    for fn in mod.enclosing(node):
        out, bound = Read(), False
        if not isinstance(fn, ast.Lambda):
            # Bound in the function, by an assignment anywhere in it.
            values = [v for stmt in list(ast.walk(fn)) + _loops(mod, fn)
                      for t, v in _assignments(stmt) if t == name]
            if values:
                bound = True
                out = out + _read_values(mod, values, seen, depth)
            if _bound_otherwise(mod, fn, name):
                bound = True
                out = out + _hole(mod, node, name)
        args = fn.args
        params = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
        if args.vararg is not None:
            params.append(args.vararg.arg)
        if args.kwarg is not None:
            params.append(args.kwarg.arg)
        if name in params:
            bound = True
            if isinstance(fn, ast.Lambda):
                out = out + _hole(mod, node, name)
            else:
                out = out + _read_parameter(mod, fn, name, seen, depth, node)
        if bound:
            return out
    if name in mod.values:
        return _read_values(mod, mod.values[name], seen, depth)
    if name in mod.imports:
        return _read_import(mod, name, seen, depth)
    return _hole(mod, node, name)


def _returns(fn) -> list:
    """What `fn` returns, its own return statements only."""
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(child, ast.Return) and child.value is not None:
                out.append(child.value)
            walk(child)
    walk(fn)
    return out


def _read_parameter(mod: Module, fn, name: str, seen, depth, at) -> Read:
    """A script handed in to `fn` as `name`, read at every call of `fn` in
    its module, and its default when a call leaves it out."""
    args = fn.args
    positional = [a.arg for a in args.posonlyargs + args.args]
    method = bool(positional) and positional[0] in ("self", "cls")
    defaults = dict(zip(positional[len(positional) - len(args.defaults):], args.defaults))
    defaults.update({a.arg: d for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None})
    calls = [n for n in ast.walk(mod.tree) if isinstance(n, ast.Call)
             and ((isinstance(n.func, ast.Name) and n.func.id == fn.name)
                  or (isinstance(n.func, ast.Attribute) and n.func.attr == fn.name))]
    if not calls:
        return _hole(mod, at, "%s, handed to %s from elsewhere" % (name, fn.name))
    out = Read(followed={(mod.rel, fn.name)})
    for call in calls:
        given = None
        for k in call.keywords:
            if k.arg == name:
                given = k.value
        if given is None and name in positional:
            index = positional.index(name)
            if method and isinstance(call.func, ast.Attribute):
                index -= 1
            if 0 <= index < len(call.args) and not any(isinstance(a, ast.Starred)
                                                       for a in call.args[:index + 1]):
                given = call.args[index]
        if given is None:
            given = defaults.get(name)
        if given is None:
            out = out + _hole(mod, call, "%s, left out of a call of %s" % (name, fn.name))
        else:
            out = out + read(mod, given, seen, depth) + Read("\n")
    return out


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------

def _not_code(mod: Module, node) -> bool:
    """A docstring, or a string standing alone as a statement."""
    up = mod.parent.get(node)
    return isinstance(up, ast.Expr)


def scripts(mod: Module):
    """Every script `mod` hands to a page, as (call, expression), and None
    for the expression of a script given some other way than in the call,
    from a file, from an address or in a spread of keywords, which nothing
    here can read."""
    for node in ast.walk(mod.tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        name = node.func.attr
        if name in EVALUATORS:
            position, keyword = EVALUATORS[name]
            given = None
            for k in node.keywords:
                if k.arg == keyword:
                    given = k.value
            if given is None and position is not None and len(node.args) > position:
                given = node.args[position]
            # A spread of keywords or arguments can only carry the script
            # when it was not given here, and a file or an address always
            # can, beside one that was.
            elsewhere = any(k.arg in ("path", "url") for k in node.keywords) or (
                name in ("add_init_script", "add_script_tag")
                and any(k.arg is None for k in node.keywords))
            if given is not None:
                yield node, given
            if given is None or elsewhere:
                yield node, None
        elif name == "send" and len(node.args) > 1:
            method, params = node.args[0], node.args[1]
            if isinstance(method, ast.Constant) and method.value in CDP:
                keys = {CDP[method.value]}
            elif isinstance(method, ast.Constant):
                continue
            else:
                # A method named in a variable may be any of them.
                keys = set(CDP.values())
            if isinstance(params, ast.Dict):
                for k, v in zip(params.keys, params.values):
                    if k is None or (isinstance(k, ast.Constant) and k.value in keys):
                        yield node, v
            else:
                # Parameters in a variable. The script in them is read only
                # when the method is known to take one, and a method in a
                # variable may be any.
                yield node, (params if isinstance(method, ast.Constant) else None)


def census(paths=None):
    """(found, holes, followed). `found` maps (file, owner, kind) to the
    lines a press is written on, `holes` maps (file, function, part) to the
    lines of a part of a script handed to a page that could not be
    followed, and `followed` is every (file, function) whose callers handed
    in a script it passed along."""
    found, holes, followed = {}, {}, set()
    for path in paths if paths is not None else sources():
        mod = module(path)
        # Every string written here.
        for node in ast.walk(mod.tree):
            text = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and not _not_code(mod, node) and not isinstance(mod.parent.get(node), ast.JoinedStr):
                text = node.value
            elif isinstance(node, ast.JoinedStr) and not _not_code(mod, node):
                text = " ".join(p.value for p in node.values if isinstance(p, ast.Constant))
            if text:
                for kind in presses_in(text):
                    found.setdefault((mod.rel, mod.owner(node), kind), set()).add(node.lineno)
        # Every script handed to a page, followed back.
        for call, given in scripts(mod):
            if given is None:
                fn = mod.enclosing(call)
                where = fn[0].name if fn and not isinstance(fn[0], ast.Lambda) else "<module>"
                holes.setdefault((mod.rel, where, "a script given another way"), set()).add(
                    call.lineno)
                continue
            got = read(mod, given)
            followed |= got.followed
            for rel, where, what, line in got.holes:
                holes.setdefault((rel, where, what), set()).add(line)
            # A press in the whole that no one string holds was put together
            # from parts, and no string's owner can answer for it.
            whole = presses_in(got.text)
            parts = []
            for rel, owner, line, text in got.literals:
                for kind in presses_in(text):
                    parts.append(kind)
                    found.setdefault((rel, owner, kind), set()).add(line)
            for kind in set(whole):
                if whole.count(kind) > parts.count(kind):
                    fn = mod.enclosing(call)
                    where = fn[0].name if fn and not isinstance(fn[0], ast.Lambda) else "<module>"
                    found.setdefault((mod.rel, where, kind + " put together from parts"),
                                     set()).add(call.lineno)
    return found, holes, followed


@pytest.fixture(scope="module")
def counted():
    return census()


def test_the_census_reads_every_app_and_the_core():
    """Not vacuous. Every app's site module, the core and the panel are
    read, and no test."""
    names = {p.relative_to(REPO).as_posix() for p in sources()}
    apps = sorted(d.name for d in (REPO / "apps").iterdir() if (d / ("%s_site.py" % d.name)).exists())
    assert len(apps) >= 60
    for app in apps:
        assert "apps/%s/%s_site.py" % (app, app) in names, app
    assert {"core/paperpull_core/pressing.py", "core/paperpull_core/capture.py",
            "gui/app.py"} <= names
    assert not [n for n in names if "/tests/" in n or n.split("/")[-1].startswith("test_")]


def test_every_press_made_through_page_script_was_reviewed(counted):
    found, _holes, _followed = counted
    unreviewed = sorted(k for k in found if k not in REVIEWED)
    assert not unreviewed, (
        "A press made through page script that nobody reviewed, %s at lines %s. A "
        "press through the page reaches the element whatever covers it, a hidden one "
        "too, and after a press of Playwright's that raised it can be a second press. "
        "Press through paperpull_core.pressing (click, or press_once for a fallback), "
        "or add it to REVIEWED with its site's reason."
        % (unreviewed, [found[k] for k in unreviewed]))


def test_every_reviewed_press_is_still_made(counted):
    found, _holes, _followed = counted
    gone = sorted(k for k in REVIEWED if k not in found)
    assert not gone, "REVIEWED names a press nothing makes any more, %s" % gone
    assert all(len(reason) > 80 for reason in REVIEWED.values())


def test_every_script_handed_to_a_page_is_read_to_the_end(counted):
    """A script the census cannot follow back could hold any press. Each
    part not followed is a value put into a script, with its reason."""
    _found, holes, _followed = counted
    unread = sorted(k for k in holes if k not in READ_AS_DATA)
    assert not unread, (
        "A script handed to a page that this cannot read, %s at lines %s. Write it "
        "as a string this can follow, or add the part to READ_AS_DATA with the "
        "reason it holds no script." % (unread, [holes[k] for k in unread]))
    stale = sorted(k for k in READ_AS_DATA if k not in holes)
    assert not stale, "READ_AS_DATA names a part nothing hands to a page any more, %s" % stale


def test_scripts_handed_through_a_helper_are_followed_in_the_tree(counted):
    """Not vacuous. The helpers that pass a script they were given to a page
    are read at their callers, in the apps and in the core."""
    _found, _holes, followed = counted
    assert {("apps/anthem/anthem_site.py", "_prime_and_fetch"),
            ("apps/capitalone/capitalone_site.py", "_evaluate_with_retry"),
            ("apps/schwab/schwab_site.py", "_evaluate_with_retry"),
            ("core/paperpull_core/pressing.py", "_in_own_world"),
            ("core/paperpull_core/pressing.py", "_ask"),
            ("core/paperpull_core/recorder.py", "_fill_capture_js")} <= followed


def test_every_kind_of_press_is_found_in_javascript():
    """The census, on scripts made for it. If one of these stops being
    found, the census above passes on nothing."""
    made = {
        "el => el.click()": ["click()"],
        "(el) => { el.scrollIntoView(); el.click (); return true; }": ["click()"],
        "el => el['click']()": ["click()"],
        "el => HTMLElement.prototype.click.call(el)": ["click.call()"],
        "f => HTMLFormElement.prototype.submit.call(f)": ["submit.call()"],
        "el => el.closest('form').submit()": ["submit()"],
        "f => f.requestSubmit(f.querySelector('button'))": ["submit()"],
        "el => el.onclick(new Event('x'))": ["a handler called"],
        "el => el.onmousedown()": ["a handler called"],
        "el => el.onclick.call(el)": ["a handler called"],
        "el => { const e = document.createEvent('MouseEvents'); e.initMouseEvent('click'); }":
            ["an event built by hand"],
        "el => el.dispatchEvent(new MouseEvent('click', {bubbles: true}))": ["dispatchEvent of click"],
        "el => el.dispatchEvent(new PointerEvent(\"pointerdown\"))": ["dispatchEvent of pointerdown"],
        "el => el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))":
            ["dispatchEvent of keydown"],
        "(el, ev) => el.dispatchEvent(ev)": ["dispatchEvent of an event it cannot read"],
        "() => $('#pay').trigger('click')": ["trigger()"],
    }
    for js, kinds in made.items():
        assert presses_in(js) == kinds, js


def test_what_is_no_press_is_left_alone():
    """Listening for a press, naming one, an event that is no press, and a
    word that only looks like one."""
    for js in ("el => el.addEventListener('click', () => {}, true)",
               "el => el.hasAttribute('onclick')",
               "el => el.dispatchEvent(new CustomEvent('change', {detail: {value: 3}}))",
               "el => el.dispatchEvent(new Event('input', {bubbles: true}))",
               "el => typeof el.click === 'function'",
               "() => document.querySelectorAll('[onclick], [tabindex]').length",
               "el => el.focus()",
               "<button onclick=\"leaveSample()\">Leave the sample</button>"):
        assert presses_in(js) == [], js


SAMPLE_SITE = r'''
import json

from sample_core import BORROWED_JS

_OPEN_JS = "el => el.click()"
_HALF = "el => el."
_OTHER_HALF = "click()"
_NOTHING_JS = "el => el.innerText"
_TEMPLATE = "(el) => { %s }"
_KINDS = (("first", "el => el.innerText"), ("second", "el => el.dispatchEvent(new MouseEvent('mousedown'))"))


def _made_js():
    return "el => el.closest('form').submit()"


def _evaluate(page, js, arg=None):
    return page.evaluate(js, arg)


def _catch_pdf(page, el):
    try:
        el.click(timeout=8000)
    except Exception:
        el.evaluate("el => el.click()")


def presses(page, el, session, how):
    el.evaluate(_OPEN_JS)
    el.evaluate(_HALF + _OTHER_HALF)
    el.evaluate(_TEMPLATE % "el.click();")
    el.evaluate(f"(el) => {{ el.{'click'}(); }}")
    _evaluate(page, "() => document.querySelector('#go').click()")
    page.evaluate(_made_js())
    page.evaluate(BORROWED_JS)
    page.eval_on_selector("#go", "el => el.click()")
    page.add_init_script(script="window.addEventListener('load', () => document.body.click())")
    session.send("Runtime.evaluate", {"expression": "document.forms[0].requestSubmit()"})
    for _name, js in _KINDS:
        el.evaluate(js)
    el.evaluate("el => el.innerText".replace("innerText", "click()"))
    el.evaluate(json.dumps(how))
    el.evaluate(_NOTHING_JS)
    el.evaluate(how.script)


def elsewhere(page, el, session, method, kw):
    page.add_init_script(path="press.js")
    page.add_script_tag(url="https://example.test/press.js")
    el.evaluate(**kw)
    session.send(method, {"expression": _HALF + _OTHER_HALF})
    el.evaluate("el => el.onmousedown()")
    page.add_init_script("() => 1", **kw)
    session.send(method, kw)
    el.evaluate("el => el.onclick.call(el)")
'''

SAMPLE_CORE = r'''
BORROWED_JS = "el => el.dispatchEvent(new PointerEvent('pointerup'))"
'''


def test_the_census_follows_a_script_back_wherever_it_is_built(tmp_path):
    """A module made for the census. Every press it makes is found, under
    the name of the string that holds it, a press put together from parts
    under the function that hands it over, and a script it cannot read is
    a part it could not follow, a script given from a file, from an address
    or in a spread of keywords among them. A DevTools call whose method is
    in a variable is read too."""
    site = tmp_path / "sample_site.py"
    site.write_text(SAMPLE_SITE, encoding="utf-8")
    (tmp_path / "sample_core.py").write_text(SAMPLE_CORE, encoding="utf-8")
    found, holes, followed = census([site])
    assert sorted(found) == [
        ("sample_core.py", "BORROWED_JS", "dispatchEvent of pointerup"),
        ("sample_site.py", "_KINDS", "dispatchEvent of mousedown"),
        ("sample_site.py", "_OPEN_JS", "click()"),
        ("sample_site.py", "_catch_pdf", "click()"),
        ("sample_site.py", "_made_js", "submit()"),
        ("sample_site.py", "elsewhere", "a handler called"),
        ("sample_site.py", "elsewhere", "click() put together from parts"),
        ("sample_site.py", "presses", "click()"),
        ("sample_site.py", "presses", "click() put together from parts"),
        ("sample_site.py", "presses", "submit()"),
    ], sorted(found)
    assert found[("sample_site.py", "elsewhere", "click() put together from parts")] == {52}
    assert holes[("sample_site.py", "elsewhere", "a script given another way")] == {49, 50, 51,
                                                                                     54, 55}
    assert found[("sample_site.py", "elsewhere", "a handler called")] == {53, 56}
    # The four strings in presses() that each hold a whole press, the
    # template's filling among them, and the three put together, from two
    # names, an f-string and what a replace made.
    assert found[("sample_site.py", "presses", "click()")] == {32, 34, 37, 38}
    assert found[("sample_site.py", "presses", "click() put together from parts")] == {31, 33, 42}
    assert found[("sample_site.py", "_KINDS", "dispatchEvent of mousedown")] == {11}
    assert ("sample_site.py", "_evaluate") in followed
    assert sorted(holes) == [("sample_site.py", "elsewhere", "a script given another way"),
                             ("sample_site.py", "presses", "how.script")], holes
