"""A record that stands for several files is done only once each of them is.

Amazon saves an order split across sellers as an invoice from each, and
Wealthfront a tax form whose dialog lists a workbook or a corrected copy as
a set of files. Each took its files in a loop, and a file that did not come
was written in the log and passed over, a `continue` after a refusal or an
`except` that fell through, while the record went on to be marked done for
good. Amazon even marked it before its loop began. The order or the form was
never asked for again, so the files that did not come were never saved
(a bug hunt of 2026-11-14, both proven by a run of each app's own code).
Target's invoice walk had been put right before that, and leaves an order
to be tried again until every invoice is on file.

So this reads every app's own code for a loop that saves a file each time
round for one record, found by what the loop calls, a save, a download, a
print or a move, followed into the app's own functions, and never by a
function's name. The call is handed something the loop's own variable
leads to, which leaves out a loop that tries one file twice the same way.
A loop that tries one file at several addresses is read as well, and
passes, since it stops at the first that answers. A loop that marks a
record done itself takes a record each time round, and is left out. The
record has to be marked done (downloaded_ok True by value) after the loop,
in the function it is in or in one that calls that function. Then

* it must not be marked done before the loop, since a file of the loop
  that does not come, or a run stopped between two, then leaves it done,
* and every way out of a file in the loop, each `continue` and `break` and
  each `except` of a save that falls through, has to write down what
  became of that file somewhere the record's outcome is read from, a name
  of the function read after the loop or one its caller handed it.

What it does not follow is said here, so the list cannot be taken for
more. A `while` loop has no variable of its own, and is left out. A
function is followed only by the name its module calls it by, `self.x`, a
function of the module, or one of another of the app's modules through the
name it is imported as, and only one caller up. On 40491dd7 it flagged
Amazon's _save_invoices, before its loop and at both of its continues, and
Wealthfront's download_one, at the refused link and at the except.
"""
import ast
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# Never into a virtual environment a checkout keeps beside an app's code,
# nor a copy a build or an install made (test_no_census_reads_a_copy_a_build_made).
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
        "site-packages"}

# What puts a file on disk, as the core and Playwright name it. A path's own
# replace takes one argument, where a string's takes two.
SAVES = {"save_download", "save_download_as", "save_as", "write_bytes", "print_page_to_pdf",
         "print_frame_to_pdf", "print_html_to_pdf", "move", "copy_whole", "deliver",
         "take_download"}
# What adds to a collection a branch writes what became of its file in.
MUTATORS = {"append", "add", "extend", "insert", "update", "setdefault"}
LOOPS = (ast.For, ast.AsyncFor)
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
LEAVES = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _sources():
    for top, dirs, files in os.walk(REPO / "apps"):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(top) / name


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _marks_done(node) -> bool:
    """downloaded_ok True by value, in a dict, a keyword or an assignment."""
    if isinstance(node, ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value == "downloaded_ok" and _is_true(v)
                   for k, v in zip(node.keys, node.values))
    if isinstance(node, ast.keyword):
        return node.arg == "downloaded_ok" and _is_true(node.value)
    if isinstance(node, ast.Assign) and _is_true(node.value):
        return any((isinstance(t, ast.Attribute) and t.attr == "downloaded_ok")
                   or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                       and t.slice.value == "downloaded_ok") for t in node.targets)
    return False


def _own(nodes):
    """Every node of these, never into a function defined inside them."""
    out, todo = [], list(nodes)
    while todo:
        node = todo.pop()
        out.append(node)
        todo.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, FUNCS))
    return out


def _root(node):
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


class App:
    """One app's modules, its functions by the names its code calls them by."""

    def __init__(self, files):
        self.funcs, self.aliases, self._parents, self._nodes = {}, {}, {}, {}
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            mod = path.stem
            # The modules an app's code reaches by name are imported at the
            # top of the module, some inside a try.
            tops = list(tree.body) + [n for s in tree.body if isinstance(s, ast.Try)
                                      for n in s.body]
            self.aliases[mod] = {a.asname or a.name: a.name for n in tops
                                 if isinstance(n, ast.Import) for a in n.names}
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs[(mod, node.name)] = (node, path)
                elif isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.funcs.setdefault((mod, "self." + sub.name), (sub, path))
        self._saves, self._done = {}, {}

    def parents_of(self, fn) -> dict:
        """Each node of a function by the node it is in."""
        if id(fn) not in self._parents:
            self._parents[id(fn)] = {c: n for n in ast.walk(fn) for c in ast.iter_child_nodes(n)}
        return self._parents[id(fn)]

    def nodes_of(self, fn) -> list:
        if id(fn) not in self._nodes:
            self._nodes[id(fn)] = _own(fn.body)
        return self._nodes[id(fn)]

    def callee(self, mod, call):
        f = call.func
        if isinstance(f, ast.Name):
            return (mod, f.id) if (mod, f.id) in self.funcs else None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == "self" and (mod, "self." + f.attr) in self.funcs:
                return mod, "self." + f.attr
            other = self.aliases.get(mod, {}).get(f.value.id)
            if (other, f.attr) in self.funcs:
                return other, f.attr
        return None

    def _function(self, cache, key, test) -> bool:
        if key not in cache:
            # A call back into it while it is read adds nothing.
            cache[key] = False
            cache[key] = self._among(cache, key[0], self.nodes_of(self.funcs[key][0]), test)
        return cache[key]

    def _among(self, cache, mod, nodes, test) -> bool:
        for node in nodes:
            if test(node):
                return True
            if isinstance(node, ast.Call):
                key = self.callee(mod, node)
                if key is not None and self._function(cache, key, test):
                    return True
        return False

    def saves(self, mod, nodes) -> bool:
        """Whether these nodes, or a function of the app they call, save a file."""
        return self._among(self._saves, mod, nodes, _saves_here)

    def done(self, mod, nodes) -> bool:
        """Whether these nodes, or a function of the app they call, mark a record done."""
        return self._among(self._done, mod, nodes, _marks_done)


def _saves_here(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    return name in SAVES or (name == "replace" and isinstance(f, ast.Attribute)
                             and len(node.args) == 1 and not node.keywords)


def _led_to(loop) -> set:
    """The names the loop's own variable leads to inside it."""
    led = {n.id for n in ast.walk(loop.target) if isinstance(n, ast.Name)}
    nodes = _own(loop.body)
    for _ in range(10):
        before = set(led)
        for node in nodes:
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
                value, targets = node.value, [node.target]
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                value, targets = node.context_expr, [node.optional_vars]
            elif isinstance(node, LOOPS):
                value, targets = node.iter, [node.target]
            else:
                continue
            if value is not None and _mentions(value, led):
                led |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        if led == before:
            break
    return led


def _on_the_way(stmts) -> list:
    """The nodes of these statements the code after them can come from. A
    branch of an if that ends by leaving, a return or a continue, is not
    one of them."""
    out = []
    for s in stmts:
        if isinstance(s, ast.If):
            out.extend(_own([s.test]))
            for branch in (s.body, s.orelse):
                if branch and not isinstance(branch[-1], LEAVES):
                    out.extend(_on_the_way(branch))
        else:
            out.extend(_own([s]))
    return out


def _mentions(node, names) -> bool:
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(node))


def _saves_a_file_each_time(app, mod, loop) -> bool:
    nodes = _own(loop.body)
    if not app.saves(mod, nodes):
        return False
    led = _led_to(loop)
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        handed = list(node.args) + [k.value for k in node.keywords]
        if isinstance(node.func, ast.Attribute):
            handed.append(node.func.value)
        if not any(_mentions(h, led) for h in handed):
            continue
        key = app.callee(mod, node)
        if _saves_here(node) or (key is not None and app.saves(key[0], [node])):
            return True
    return False


def _levels(app, fn, node):
    """(the statements before, the statements after) `node` at each level of
    the function up from it, the nearest first. Climbing stops past a level
    whose statements after it leave that level, by a return, a raise, a
    continue or a break."""
    out, parents = [], app.parents_of(fn)
    while node is not fn and node in parents:
        parent = parents[node]
        for field in ("body", "orelse", "finalbody", "handlers"):
            block = getattr(parent, field, None)
            if isinstance(block, list) and node in block:
                at = block.index(node)
                out.append((block[:at], block[at + 1:]))
                if any(isinstance(s, LEAVES) for s in block[at + 1:]):
                    return out
                break
        node = parent
    return out


def _statement_of(app, fn, node):
    parents = app.parents_of(fn)
    while not isinstance(node, ast.stmt):
        node = parents[node]
    return node


def _ways_out(app, mod, loop):
    """Each continue and break of this loop, with the statements before it in
    its block, and each except of a save in it that falls through, with its
    body."""
    found = []

    def visit(stmts):
        for i, s in enumerate(stmts):
            if isinstance(s, (ast.Continue, ast.Break)):
                found.append((type(s).__name__.lower(), s, stmts[:i]))
            if isinstance(s, FUNCS + LOOPS + (ast.While,)):
                continue
            if isinstance(s, ast.Try):
                for h in s.handlers:
                    if app.saves(mod, _own(s.body)) and not isinstance(h.body[-1], LEAVES):
                        found.append(("except", h, h.body))
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(s, field, None) or [])
            for h in getattr(s, "handlers", None) or []:
                visit(h.body)
            if isinstance(s, ast.Match):
                for case in s.cases:
                    visit(case.body)
    visit(loop.body)
    return found


def _written(stmts) -> set:
    """The names these statements write what they came to into."""
    out = set()
    for node in _own(stmts):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign))
                   else [])
        out |= {_root(t) for t in targets}
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATORS):
            out.add(_root(node.func.value))
    return out - {None, "self"}


def _names_of(app, fn) -> tuple:
    """(its parameters but self, every name it assigns)."""
    args = fn.args
    params = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs
              + [args.vararg, args.kwarg] if a is not None} - {"self"}
    assigned = {n.id for n in app.nodes_of(fn) if isinstance(n, ast.Name)
                and isinstance(n.ctx, ast.Store)}
    return params, assigned


def census(apps_root: Path, files=None) -> tuple:
    """({where: what is wrong}, the loops it read) over every app below
    `apps_root`, where is "app/module.py:function:line"."""
    by_app = {}
    for path in (files if files is not None else _sources()):
        app = path.relative_to(apps_root).parts[0]
        by_app.setdefault(app, []).append(path)
    flagged, read = {}, set()
    for name, files_of_app in sorted(by_app.items()):
        app = App(files_of_app)
        loops = [(key, fn, path, loop) for key, (fn, path) in app.funcs.items()
                 for loop in app.nodes_of(fn)
                 if isinstance(loop, LOOPS) and _saves_a_file_each_time(app, key[0], loop)
                 # A loop that marks a record done takes a record each time round.
                 and not app.done(key[0], _own(loop.body))]
        callers = {}
        for key, (fn, _path) in app.funcs.items() if loops else ():
            for node in app.nodes_of(fn):
                if isinstance(node, ast.Call):
                    reached = app.callee(key[0], node)
                    if reached is not None:
                        callers.setdefault(reached, []).append((key, node))
        for key, fn, path, loop in loops:
            mod = key[0]
            here = [(mod, _levels(app, fn, loop))]
            here += [(caller[0], _levels(app, app.funcs[caller][0],
                                         _statement_of(app, app.funcs[caller][0], call)))
                     for caller, call in callers.get(key, ())]
            before = any(app.done(m, _on_the_way(b)) for m, levels in here for b, _a in levels)
            after = any(app.done(m, _own(a)) for m, levels in here for _b, a in levels)
            if not (before or after):
                continue
            where = "%s/%s:%s:%d" % (name, path.name, key[1].replace("self.", ""),
                                     loop.lineno)
            read.add(where)
            wrong = []
            if before:
                wrong.append("the record is marked done before the loop")
            params, assigned = _names_of(app, fn)
            later = {n.id for _b, a in here[0][1] for n in _own(a)
                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            kept_for = params | (assigned & later)
            for kind, node, stmts in _ways_out(app, mod, loop):
                if not _written(stmts) & kept_for:
                    wrong.append("the %s at line %d writes down nothing of its file"
                                 % (kind, node.lineno))
            if wrong:
                flagged[where] = wrong
    return flagged, read


@pytest.fixture(scope="module")
def found():
    return census(REPO / "apps")


def test_no_record_of_several_files_is_done_while_one_of_them_is_not(found):
    flagged, _read = found
    assert not flagged, (
        "these mark a record done while a file of its set may not have come, so it is never "
        "asked for again. Mark it done only once every file is on file, and write each way "
        "out of the loop down where the outcome is read: %s" % flagged)


def test_the_census_reads_the_loops_it_is_about(found):
    """Not a census of nothing. The loops that save the files of one record."""
    _flagged, read = found
    apps = {where.split("/")[0] for where in read}
    assert {"amazon", "wealthfront", "target", "anthem"} <= apps, sorted(read)


# The shape that was there on 40491dd7, and the shape that put it right. The
# canary holds the census to what it has to see.
BEFORE = '''
import site_of_it as site

class App:
    def _save_invoices(self, page, purchase, invoices):
        if not self._finish_pdf(page, purchase, invoices[0]):
            return False
        names = []
        for i, url in enumerate(invoices[1:], start=2):
            extra = self.folder / ("%d.pdf" % i)
            if not site.download(page, url, extra):
                log.warning("did not come")
                continue
            try:
                extra.replace(self.review / extra.name)
            except OSError:
                log.warning("stayed")
            names.append(extra.name)
        return True

    def _finish_pdf(self, page, purchase, path):
        self.progress.update(purchase.key, {"downloaded_ok": True})
        return True
'''

AFTER = '''
import site_of_it as site

class App:
    def _save_invoices(self, page, purchase, invoices):
        walk = {"lacking": []}
        self._take(page, invoices, walk)
        return self._file(purchase, walk)

    def _take(self, page, invoices, walk):
        for i, url in enumerate(invoices, start=1):
            staged = self.folder / ("%d.pdf" % i)
            if not site.download(page, url, staged):
                walk["lacking"].append(i)
                continue
            try:
                staged.replace(self.folder / ("kept %d.pdf" % i))
            except OSError:
                walk["lacking"].append(i)

    def _file(self, purchase, walk):
        if walk["lacking"]:
            return False
        self.progress.update(purchase.key, {"downloaded_ok": True})
        return True
'''

SITE = '''
from paperpull_core import shared_folder

def download(page, url, out):
    shared_folder.write_bytes(out, b"%PDF")
    return True
'''

TRIES_TWICE = '''
class App:
    def download_one(self, page, doc, out_path):
        for attempt in (1, 2):
            try:
                receipt_pdf.save_download(page.download, out_path)
                break
            except Exception:
                log.warning("again")
        doc.downloaded_ok = True
'''


@pytest.mark.parametrize("code, wanted", [
    (BEFORE, ["the record is marked done before the loop",
              "the continue at line 13 writes down nothing of its file",
              "the except at line 16 writes down nothing of its file"]),
    (AFTER, None),
    (TRIES_TWICE, None),
], ids=["before", "after", "one file tried twice"])
def test_the_census_sees_the_shapes_it_is_about(tmp_path, code, wanted):
    app = tmp_path / "invented"
    app.mkdir()
    (app / "invented_receipts.py").write_text(code, encoding="utf-8")
    (app / "site_of_it.py").write_text(SITE, encoding="utf-8")
    flagged, read = census(tmp_path, sorted(app.glob("*.py")))
    if wanted is None:
        assert not flagged, flagged
    else:
        assert list(flagged.values()) == [wanted], flagged
    if code is not TRIES_TWICE:
        assert read, "the loop that saves each invoice is read"
    else:
        assert not read, read
