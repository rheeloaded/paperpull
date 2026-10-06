"""What Diagnose prints keeps no word off the word list.

Every file Diagnose writes goes through paperpull_core.words on its way to
the disk, where a word that is not on the fixed list leaves as its shape.
What Diagnose printed did not, and the panel shows that output, where a
tester can copy it into a public issue as easily as attach a file.
Twenty-three apps printed each sample document's title as the page wrote
it, and those and Paylocity its date. PG&E printed the page's address with
its query, its title and the labels of its controls, Capital One the page's
headings and its accounts, Ally, Chase, U.S. Bank and Discover a dropdown's
own label, the addresses the page asked and values from the provider's
answers, and eight receipt apps an order number, on a line of its own and
in the name of the file they wrote, which is the name an attachment shows.

So every line Diagnose prints is tried here with an invented value, letters
and digits, standing in for everything that came off a page or out of a
record, and a line passes only when that value does not come out as it went
in. What may come out whole is a word we wrote, a count made with len, a
yes or no, a word from a list written in the app's source and a path in
the app's own folders whose name we wrote. Anything else goes through
shape, shape_url or shape_tree with the app's own words first. That holds
for a count read back from what an app gathered too, since shape_tree leaves
a whole number and a yes or no as they are, so no key is trusted to hold
one. A Fixed string is trusted where it is made, as it is in a file.

The lines are found by what they do. Every print, log line and traceback in
cmd_diagnose, in any function that names a diagnose- file and in any
function only those call. A log line a provider's site module writes while
Diagnose runs is not read here, since that module serves every command.
Nothing here is a real value.
"""
import ast
import builtins
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import words as W  # noqa: E402
from paperpull_core.redact import set_private_words  # noqa: E402

# Invented, letters and digits, the kind of value masking let through. Each
# part is looked for on its own.
CANARY = "Zorvex4821Quillam"
PARTS = ("zorvex", "4821", "quillam")

SHAPERS = ("shape", "shape_url", "shape_name", "shape_tree")
CONSOLE = ("print", "sys.stdout.write", "sys.stderr.write")
# Every app logs at INFO to the console, which the panel shows.
LOGS = ("info", "warning", "warn", "error", "exception", "critical", "log")
LOGGER = re.compile(r"(^|\.)(_?log|logger|LOG|logging)$")
# What these print is an exception's own text, which nothing here can shape.
TRACEBACKS = ("traceback.print_exc", "traceback.print_exception",
              "traceback.print_stack", "traceback.print_tb")


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))


@pytest.fixture(autouse=True)
def _no_owner():
    set_private_words([])
    yield
    set_private_words([])


# -- what stands in for a page --------------------------------------------------

class Leak(str):
    """Whatever came off a page or out of a record. Every attribute, item,
    call and element of it is another, and it reads as the canary."""

    def __new__(cls):
        return super().__new__(cls, CANARY)

    def __getattribute__(self, name):
        if name.startswith("__") and name.endswith("__"):
            return super().__getattribute__(name)
        return Leak()

    def __getitem__(self, key):
        return Leak()

    def __call__(self, *args, **kwargs):
        return Leak()

    def __iter__(self):
        return iter((Leak(), Leak()))

    def __len__(self):
        return 2

    def __bool__(self):
        return True

    def __truediv__(self, other):
        return Leak()

    def __rtruediv__(self, other):
        return Leak()

    def __radd__(self, other):
        # A sum of what a page gave can be an amount, so it is a page's too.
        return Leak()


def site_of(app: Path):
    """The app's site module. Everything it hands back is a page's, and it
    carries the name and the file words_for reads the app's words from."""
    site = Leak()
    module = "%s_site" % app.name
    object.__setattr__(site, "__name__", module)
    object.__setattr__(site, "__file__", str(app / (module + ".py")))
    return site


class Folders:
    """The app's own folders, the ones the person set up."""

    def __init__(self, root):
        self._root = root

    def __getattr__(self, name):
        return self._root / name


class App:
    """self. Its folders are the person's, and every other part of it, an
    order number typed for it or a page it holds, is a page's."""

    def __init__(self, root):
        self.paths = Folders(root)

    def __getattr__(self, name):
        return Leak()


# -- finding the lines -------------------------------------------------------------

def own_nodes(fn):
    """Every node of a function's own body. A function or class defined in
    it is one node, and nothing inside it is."""
    todo = list(fn.body)
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))


def functions_of(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def names_a_diagnose_file(fn) -> bool:
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str)
               and c.value.startswith("diagnose-") for c in ast.walk(fn))


def diagnose_functions(tree):
    """cmd_diagnose, every function that names a diagnose- file, the functions
    defined inside those, and every method or function of the module that
    only those call, until nothing more turns up."""
    fns = functions_of(tree)
    module_level = {fn for fn in tree.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
    chosen = {fn for fn in fns if fn.name == "cmd_diagnose" or names_a_diagnose_file(fn)}
    through_self, by_name = {}, {}
    for fn in fns:
        for node in own_nodes(fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "self":
                through_self.setdefault(node.func.attr, set()).add(fn)
            elif isinstance(node.func, ast.Name):
                by_name.setdefault(node.func.id, set()).add(fn)
    for node in top_level(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                by_name.setdefault(call.func.id, set()).add(tree)
    grew = True
    while grew:
        grew = False
        for fn in fns:
            if fn in chosen:
                continue
            inside = any(fn in set(functions_of(c)) - {c} for c in chosen)
            called = (by_name if fn in module_level else through_self).get(fn.name)
            if inside or (called and called <= chosen):
                chosen.add(fn)
                grew = True
    return sorted(chosen, key=lambda fn: fn.lineno)


def is_log(call) -> bool:
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr in LOGS \
        and bool(LOGGER.search(ast.unparse(f.value)))


def console_lines(fn):
    """Every call in fn's own body that writes to the console."""
    return sorted((n for n in own_nodes(fn) if isinstance(n, ast.Call)
                   and (ast.unparse(n.func) in CONSOLE + TRACEBACKS or is_log(n))),
                  key=lambda n: n.lineno)


def stores(target, name) -> bool:
    """Whether an assignment's target binds name. self.stats["mode"] = ...
    reads self and binds nothing."""
    return any(isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store)
               for n in ast.walk(target))


def bindings(fn, name):
    """Each place fn binds name, as (kind, node). A comprehension's own
    names are its own and not fn's."""
    found = []
    for node in own_nodes(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    found.append(("assign", node))
                elif stores(t, name):
                    found.append(("other", node))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found.append(("for", node))
            elif stores(node.target, name):
                found.append(("other", node))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and stores(node.target, name):
            found.append(("other", node))
        elif isinstance(node, ast.ExceptHandler) and node.name == name:
            found.append(("other", node))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None \
                and stores(node.optional_vars, name):
            found.append(("other", node))
        elif isinstance(node, ast.NamedExpr) and node.target.id == name:
            found.append(("other", node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                (a.asname or a.name.split(".")[0]) == name for a in node.names):
            found.append(("other", node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == name:
            found.append(("other", node))
    a = fn.args
    for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
        if arg.arg == name:
            found.append(("arg", arg))
    return sorted(found, key=lambda kind_node: kind_node[1].lineno)


def top_level(tree):
    """What a module binds when it is imported, outside any function."""
    todo = list(tree.body)
    while todo:
        node = todo.pop(0)
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                todo.extend(getattr(node, field, None) or [])


def module_names(tree):
    names = {}
    for node in top_level(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = (node, alias)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = (node, None)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names[n.id] = (node, None)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            names[node.target.id] = (node, None)
    return names


def free_names(expr):
    bound = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.comprehension):
            bound |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.Lambda):
            bound |= {a.arg for a in node.args.args}
    return sorted({n.id for n in ast.walk(expr) if isinstance(n, ast.Name)
                   and isinstance(n.ctx, ast.Load) and n.id not in bound})


def followed(expr) -> bool:
    """An assignment worth following rather than standing in for. The app's
    words, a path in its own folders, a value already shaped, or a string
    written in its source. A dictionary or a list made empty is filled later
    with what a page said, so it is a page's."""
    if isinstance(expr, ast.Call):
        return ast.unparse(expr.func) in ("words_for",) + SHAPERS
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        return True
    return isinstance(expr, (ast.Constant, ast.JoinedStr))


class NotDefined(Exception):
    pass


def enclosing(tree, fn):
    """The function fn is defined in, if it is defined in one."""
    for outer in functions_of(tree):
        if fn is not outer and any(child is fn for child in own_nodes(outer)):
            return outer
    return None


class Scope:
    """What each name a line reads stands for when the line is tried."""

    def __init__(self, app: Path, tree, fn, root: Path):
        self.app, self.fn, self.root = app, fn, root
        self.module = module_names(tree)
        self.me = App(root)
        outer = enclosing(tree, fn)
        self.outer = Scope(app, tree, outer, root) if outer is not None else None

    def module_value(self, name):
        node, alias = self.module[name]
        if isinstance(node, ast.ImportFrom):
            if node.module == "paperpull_core.words":
                return getattr(W, alias.name)
            if node.module == "paperpull_core" and alias.name == "words":
                return W
            if (node.module or "").startswith("paperpull_core"):
                value = getattr(importlib.import_module(node.module), alias.name, None)
                if isinstance(value, (str, int, float, bool)):
                    return value
            return Leak()
        if isinstance(node, ast.Import):
            if alias.name == "%s_site" % self.app.name:
                return site_of(self.app)
            return Leak()
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            return node.value.value
        return Leak()

    def value(self, name, line, seen=()):
        found = bindings(self.fn, name)
        if found:
            kinds = {kind for kind, _ in found}
            first_arg = (self.fn.args.posonlyargs + self.fn.args.args)[:1]
            if kinds == {"arg"} and first_arg and first_arg[0].arg == name == "self":
                return self.me
            if kinds == {"for"}:
                loops = [node for _, node in found]
                loop = next((n for n in loops if n.lineno <= line <= n.end_lineno), loops[0])
                if isinstance(loop.iter, (ast.List, ast.Tuple, ast.Set)) and loop.iter.elts:
                    return self.evaluate(loop.iter.elts[0], line, seen)
                return Leak()
            if kinds == {"assign"}:
                before = [node for _, node in found if node.lineno < line]
                if not before:
                    raise NotDefined("%s, which is read before it is set" % name)
                # Followed only when every assignment is. A loop can bring
                # a later one back round to the line, so the one that lets
                # a page's words out is the one tried, if any does.
                if all(followed(node.value) for _, node in found) and name not in seen:
                    values = [self.evaluate(node.value, line, seen + (name,))
                              for _, node in found]
                    return next((v for v in values if leaks(v, self.root)),
                                values[found.index(("assign", before[-1]))])
            return Leak()
        if self.outer is not None:
            return self.outer.value(name, line, seen)
        if name in self.module:
            return self.module_value(name)
        if hasattr(builtins, name):
            return getattr(builtins, name)
        raise NotDefined("%s, which is not defined" % name)

    def evaluate(self, expr, line, seen=()):
        env = {"__builtins__": builtins}
        for name in free_names(expr):
            env[name] = self.value(name, line, seen)
        return eval(compile(ast.Expression(body=expr), "<diagnose>", "eval"), env)

    def said(self, call):
        args = call.args
        if is_log(call) and call.func.attr == "log":
            args = args[1:]
        out = []
        for arg in args:
            if isinstance(arg, ast.Starred):
                out.extend(self.evaluate(arg.value, call.lineno))
            else:
                out.append(self.evaluate(arg, call.lineno))
        if is_log(call):
            # A log line is its message with the rest put in its places.
            return str(out[0]) % tuple(out[1:]) if len(out) > 1 else str(out[0] if out else "")
        return " ".join(str(v) for v in out)


def leaks(text, root=None) -> bool:
    """Whether a part of the canary came out. The app's folders here are a
    temporary folder pytest numbers, which is taken out first, since its
    number could hold the canary's digits one day."""
    text = str(text)
    if root is not None:
        text = text.replace(str(root), "<folder>")
    low = text.lower()
    return any(part in low for part in PARTS)


def what_diagnose_prints(app: Path, tree, root: Path):
    """Each line Diagnose prints that carries more than words of ours, as
    (line number, what it printed or why it could not be tried)."""
    for fn in diagnose_functions(tree):
        scope = Scope(app, tree, fn, root)
        for call in console_lines(fn):
            if ast.unparse(call.func) in TRACEBACKS:
                yield call.lineno, None, "it prints an exception's own text"
                continue
            if all(isinstance(a, ast.Constant) for a in call.args):
                continue
            try:
                yield call.lineno, scope.said(call), None
            except NotDefined as e:
                yield call.lineno, None, "it reads %s" % e
            except Exception as e:  # a line that cannot be tried is reported
                yield call.lineno, None, "it could not be tried, %s: %s" % (
                    type(e).__name__, str(e)[:80])


def provider_of(tree) -> str:
    return next(ast.unparse(k.value) for n in ast.walk(tree) if isinstance(n, ast.Call)
                and ast.unparse(n.func) == "failure.write_survey"
                for k in n.keywords if k.arg == "provider")


# -- the census ----------------------------------------------------------------------

@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_line_diagnose_prints_keeps_no_word_off_the_list(app, tmp_path):
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    tried, wrong = 0, []
    for line, text, why in what_diagnose_prints(app, tree, tmp_path):
        if why:
            wrong.append("line %d, %s" % (line, why))
            continue
        tried += 1
        if leaks(text, tmp_path):
            shown = text.replace(str(tmp_path), "<folder>").strip()
            wrong.append("line %d prints %r" % (line, shown[:110]))
    assert tried, "%s prints nothing from Diagnose, so nothing was tried" % app.name
    assert not wrong, "%s prints what a page said\n  %s" % (app.name, "\n  ".join(wrong))


def shaped_with_other_words(tree):
    """Each shaping in a Diagnose line whose words are not the app's own,
    words_for with the name the app gives its survey, bound once."""
    expected = "words_for(%s, site)" % provider_of(tree)
    wrong = []
    for fn in diagnose_functions(tree):
        for call in console_lines(fn):
            for c in ast.walk(call):
                if not (isinstance(c, ast.Call) and ast.unparse(c.func) in SHAPERS):
                    continue
                words = c.args[1] if len(c.args) > 1 else next(
                    (k.value for k in c.keywords if k.arg == "words"), None)
                if isinstance(words, ast.Name):
                    found = bindings(fn, words.id)
                    if found and all(kind == "assign" and ast.unparse(node.value) == expected
                                     for kind, node in found):
                        continue
                elif words is not None and ast.unparse(words) == expected:
                    continue
                wrong.append("line %d, %s" % (c.lineno, ast.unparse(c)[:90]))
    return expected, wrong


def diagnose_file_names(app: Path, tree, root: Path):
    """Each path Diagnose makes in the app's folders, as (line, path)."""
    for fn in diagnose_functions(tree):
        scope = Scope(app, tree, fn, root)
        for node in own_nodes(fn):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) \
                    and ast.unparse(node.left).startswith("self.paths."):
                yield node.lineno, scope.evaluate(node, node.lineno)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_what_diagnose_prints_is_shaped_with_the_apps_own_words(app):
    """The words the file is written with, from what the app's source calls
    it, and never a set with a page's words added to it."""
    expected, wrong = shaped_with_other_words(ast.parse(entry_of(app).read_text(encoding="utf-8")))
    assert not wrong, "%s shapes a line with words other than %s\n  %s" % (
        app.name, expected, "\n  ".join(wrong))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_file_diagnose_writes_is_named_by_the_app(app, tmp_path):
    """A tester attaches the detailed file, and an attachment shows its name.
    Every path Diagnose makes in the app's folders is tried the same way."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    names = list(diagnose_file_names(app, tree, tmp_path))
    assert names, "%s makes no path for Diagnose, so nothing was tried" % app.name
    wrong = ["line %d, %s" % (line, Path(path).name) for line, path in names
             if leaks(path, tmp_path)]
    assert not wrong, "%s names a Diagnose file after what a page said\n  %s" % (
        app.name, "\n  ".join(wrong))


# -- and that the census can tell ------------------------------------------------------

LOOKS = '''
import logging
import traceback

import zorbank_site as site
from paperpull_core.models import IN_STORE, ONLINE
from paperpull_core.words import shape, shape_tree, shape_url, words_for, write_shaped

log = logging.getLogger(__name__)


def report(info):
    print(%(module_line)s)


class Downloader:
    def cmd_diagnose(self):
        self.stats["mode"] = "diagnose"
        words = %(words)s
        page = self.page()
        info = {"collected": 0, "samples": []}
        out = self.paths.diagnostics / "diagnose-history.json"
        write_shaped(out, info, words)
        print(f"Wrote {out}")
        label = "Documents"
        for ptype in (ONLINE, IN_STORE):
            p = self.pick(ptype)
            out = self.paths.diagnostics / f"diagnose-{ptype}%(name_part)s.json"
            write_shaped(out, info, words)
            print(f"Wrote {out}")
            print(%(line)s)
            %(statement)s
        self.helper(info)
        report(info)

    def helper(self, info):
        print(%(helper_line)s)

    def write_survey(self):
        failure.write_survey(self.paths.diagnostics, provider='Zorbank')
'''

PLAIN = {"module_line": "len(info)", "words": "words_for('Zorbank', site)", "name_part": "",
         "line": "len(info)", "statement": "pass", "helper_line": "len(info)"}


def looks_like(**parts):
    return ast.parse(LOOKS % dict(PLAIN, **parts))


def census_of(tmp_path, **parts):
    app = tmp_path / "zorbank"
    app.mkdir(exist_ok=True)
    said = list(what_diagnose_prints(app, looks_like(**parts), tmp_path))
    return [(None if text is None else text.replace(str(tmp_path), "<folder>"), why)
            for _, text, why in said]


def caught(said) -> bool:
    return any(text is not None and leaks(text) for text, _ in said)


@pytest.mark.parametrize("line", [
    "f'  [{info[\"category\"]}] {info[\"date\"]}  <- {info[\"title\"][:50]}'",
    "f'Current URL: {page.url}'",
    "f'Page title: {page.title()}'",
    "f'Rows collected: {info.get(\"collected\", \"?\")}'",
    "f'Diagnosing {ptype} purchase #{p.order_number} ...'",
    "', '.join(info['year_options'])",
    "shape(info['title'], words) + info['date']",
    "sum(info['amounts'])",
])
def test_the_census_catches_a_line_that_says_what_a_page_said(tmp_path, line):
    assert caught(census_of(tmp_path, line=line))


@pytest.mark.parametrize("line", [
    "shape(f'  [{info[\"category\"]}] {info[\"date\"]}  <- {info[\"title\"][:50]}', words, collapse=False)",
    "f'Current URL: {shape_url(page.url, words)}'",
    "f'Rows collected: {shape_tree(info.get(\"collected\", \"?\"), words)}, found {len(info)}'",
    "f'Diagnosing {ptype} purchase #{shape(p.order_number, words)} ...'",
    "', '.join(shape(o, words) for o in info['year_options'])",
    "f'{label} {shape_tree(sum(info[\"counts\"]), words)}'",
])
def test_the_census_passes_a_line_built_from_the_list(tmp_path, line):
    said = census_of(tmp_path, line=line)
    assert all(why is None for _, why in said), said
    assert not caught(said), said


@pytest.mark.parametrize("parts", [
    {"helper_line": "info['title']"},
    {"module_line": "info['title']"},
    {"statement": "log.info('could not select %r', info['title'])"},
    {"statement": "log.warning('landed on %s', page.url)"},
    {"statement": "label = info['title']"},
], ids=["a method only Diagnose calls", "a function only Diagnose calls", "a log line",
        "another log line", "a name a page's words reach later in a loop"])
def test_the_census_reads_every_way_a_page_can_reach_the_console(tmp_path, parts):
    if "label" not in parts.get("statement", ""):
        assert caught(census_of(tmp_path, **parts))
    else:
        assert caught(census_of(tmp_path, line="label", **parts))


def test_the_census_refuses_a_traceback(tmp_path):
    said = census_of(tmp_path, statement="traceback.print_exc()")
    assert any(why and "exception" in why for _, why in said), said


def test_the_census_catches_an_order_number_in_a_files_name(tmp_path):
    assert caught(census_of(tmp_path, name_part="-{p.order_number}"))
    app = tmp_path / "zorbank"
    named = [path for _, path in diagnose_file_names(
        app, looks_like(name_part="-{p.order_number}"), tmp_path)]
    assert any(leaks(path, tmp_path) for path in named), named
    plain = [path for _, path in diagnose_file_names(app, looks_like(), tmp_path)]
    assert plain and not any(leaks(path, tmp_path) for path in plain), plain


def test_the_census_catches_a_line_whose_words_were_never_set(tmp_path):
    said = census_of(tmp_path, line="shape(info['title'], wordz)")
    assert any(why and "not defined" in why for _, why in said), said


@pytest.mark.parametrize("parts", [
    {"words": "words_for(page.title(), site)"},
    {"line": "shape(info['title'], words | {'zorvex4821quillam'})"},
    {"line": "shape(info['title'])"},
])
def test_the_census_catches_words_that_are_not_the_apps_own(parts):
    _, wrong = shaped_with_other_words(looks_like(line=parts.get(
        "line", "shape(info['title'], words)"), **{k: v for k, v in parts.items() if k != "line"}))
    assert wrong
    _, plain = shaped_with_other_words(looks_like(line="shape(info['title'], words)"))
    assert not plain, plain
