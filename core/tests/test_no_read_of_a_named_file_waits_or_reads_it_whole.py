"""No read of a file a record, an index row or a folder listing names waits
on a pipe or reads the file whole.

A run reads files it did not write, the one a record or an index row names
and the ones a folder lists, and any of them can be a named pipe, a device
or a link to one, or a file larger than free memory. pdf_reader opened and
hashed such a path in the run's own process before its time limit, so a
pipe held Target and Robinhood for good, and Robinhood's _sha256 and
E*TRADE's _same_bytes_elsewhere read another record's file whole, so one
past free memory failed the document just taken (the bug hunt of
2026-11-14, findings 4 and 6).

This reads every function of every file that ships, follows each path a
record, a row or a listing gives through the names it is put in and into
the functions of its own module it is handed to, and finds each call that
reads what such a path names. Each has to go through a reader that holds
the limits, pdf_reader and what reads through it, intake or shared_folder,
or come after a look that the file is a plain one, and for a read of the
whole file, a look at its size against a bound. Found by the call that
reads, never by a function's name. On 40491dd7 it found Robinhood's
_sha256 and E*TRADE's _same_bytes_elsewhere and nothing else.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = ("apps", "core", "gui", "server", "tools")
# Never a virtual environment a checkout keeps beside an app's code, nor a
# copy a build or an install made (test_no_census_reads_a_copy_a_build_made).
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
        "site-packages"}

# What a record or an index row names a file by.
KEYS = {"pdf_path", "PDF Full Path", "file", "pdf_filename", "PDF Filename"}
ATTRS = {"pdf_path", "pdf_filename"}
# What lists a folder. The apps and the core list a run's output folders
# and Manual Review. The panel and the tools list the install's own code,
# its templates and its plug-ins, which no record names, so there only a
# record or a row is where a path comes from.
LISTINGS = {"iterdir", "glob", "rglob", "iglob", "listdir", "scandir", "walk"}
LISTED_IN = ("apps/", "core/")

# Calls that read what a path names.
READS_WHOLE = {"read_bytes", "read_text"}
COPIES = {"shutil.copyfile", "shutil.copy", "shutil.copy2"}
OPENERS = {"open", "io.open", "os.open", "zipfile.ZipFile", "pdfplumber.open", "PdfReader",
           "pypdf.PdfReader"}
# Looks that come first and make a read safe. A plain file, not a pipe or a
# device, and for a read of it whole, a size compared with a bound.
PLAIN = {"is_file", "isfile", "S_ISREG"}
SIZED = {"st_size", "size_of", "getsize"}


def _sources():
    """Every Python file that ships, tests apart."""
    out = []
    for top in ROOTS:
        for folder, dirs, files in os.walk(REPO / top):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith(".")
                             and not d.endswith("browser-profile"))
            out.extend(Path(folder) / f for f in sorted(files)
                       if f.endswith(".py") and not f.startswith("test_")
                       and f != "conftest.py")
    return out


def _key_read(node) -> bool:
    """x.get("pdf_path"), x["PDF Full Path"], x.pdf_path and the like."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop") and node.args
            and isinstance(node.args[0], ast.Constant) and node.args[0].value in KEYS):
        return True
    if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and node.slice.value in KEYS):
        return True
    return isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) \
        and node.attr in ATTRS


def _listing(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) in LISTINGS


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _by_function(tree):
    """Every function of the module, each with its own nodes, a lambda's
    among them and those of a function defined inside it apart, and the
    function each is defined in. One walk of the module."""
    fns, nodes, outer = [], {}, {}
    todo = [(child, None) for child in ast.iter_child_nodes(tree)]
    while todo:
        node, fn = todo.pop()
        if fn is not None:
            nodes[id(fn)].append(node)
        if isinstance(node, _DEFS):
            fns.append(node)
            nodes[id(node)] = []
            if fn is not None:
                outer[id(node)] = fn
            fn = node
        todo.extend((child, fn) for child in ast.iter_child_nodes(node))
    return fns, nodes, outer


def _params(fn) -> list:
    a = fn.args
    names = [p.arg for p in a.posonlyargs + a.args]
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    return names + [p.arg for p in a.kwonlyargs]


def _callee(call) -> str:
    """The name of a function of the module, or a method of its own, that
    a call is made to, or ""."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
            and f.value.id in ("self", "cls"):
        return f.attr
    return ""


def _before(node, call) -> bool:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)) < (
        call.lineno, call.col_offset)


class _Module:
    """One file, each function's names that hold a named path, and the
    reads of them."""

    def __init__(self, tree, listings: bool):
        self.listings = listings
        # The function each one is defined in is the one whose names it
        # can read.
        self.fns, self.nodes, self.outer = _by_function(tree)
        self.taint = self._spread()

    def named(self, node, tainted: set) -> bool:
        """Whether an expression holds a path a record, a row or a listing
        gave, or a name one was put in."""
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in tainted:
                return True
            if _key_read(sub) or (self.listings and _listing(sub)):
                return True
        return False

    def _names_in(self, fn, given: set) -> set:
        tainted = set(given)
        while True:
            before = len(tainted)
            for node in self.nodes[id(fn)]:
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if node.value is not None and self.named(node.value, tainted):
                        for t in targets:
                            tainted |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
                elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                    if self.named(node.iter, tainted):
                        tainted |= {n.id for n in ast.walk(node.target)
                                    if isinstance(n, ast.Name)}
            if len(tainted) == before:
                return tainted

    def _spread(self) -> dict:
        """Each function's tainted names, a parameter among them where a
        call in the module hands it a named path, and a name of the
        function it is defined in, until nothing changes."""
        by_name = {}
        for fn in self.fns:
            by_name.setdefault(fn.name, []).append(fn)
        calls = {id(fn): [n for n in self.nodes[id(fn)]
                          if isinstance(n, ast.Call) and _callee(n) in by_name]
                 for fn in self.fns}
        given = {id(fn): set() for fn in self.fns}
        taint = {id(fn): self._names_in(fn, set()) for fn in self.fns}
        while True:
            changed = {}
            for fn in self.fns:
                outer = self.outer.get(id(fn))
                if outer is not None and not taint[id(outer)] <= given[id(fn)]:
                    given[id(fn)] |= taint[id(outer)]
                    changed[id(fn)] = fn
                for call in calls[id(fn)]:
                    for target in by_name[_callee(call)]:
                        params = _params(target)
                        handed = [(params[i], a) for i, a in enumerate(call.args)
                                  if i < len(params)]
                        handed += [(k.arg, k.value) for k in call.keywords if k.arg in params]
                        for param, arg in handed:
                            if param not in given[id(target)] \
                                    and self.named(arg, taint[id(fn)]):
                                given[id(target)].add(param)
                                changed[id(target)] = target
            if not changed:
                return taint
            for fn in changed.values():
                taint[id(fn)] = self._names_in(fn, given[id(fn)])

    def read_of(self, call, tainted: set):
        """(what, whole) when the call reads what a named path names."""
        f = call.func
        name = ast.unparse(f)
        if isinstance(f, ast.Attribute) and f.attr in READS_WHOLE and not call.args \
                and self.named(f.value, tainted):
            return "%s read whole" % f.attr, True
        if name in COPIES and call.args and self.named(call.args[0], tainted):
            return "copied by %s" % name, True
        if name in OPENERS and call.args and self.named(call.args[0], tainted) \
                and not _writes(call, 1):
            return "opened by %s" % name, False
        # path.open(), but not io.open() or the like, which name a module.
        if isinstance(f, ast.Attribute) and f.attr == "open" and name not in OPENERS \
                and self.named(f.value, tainted) and not _writes(call, 0):
            return "opened by %s" % name, False
        return None

    def unheld(self):
        """(function, call, what) for each read of a named path with no
        look before it that bounds it."""
        for fn in self.fns:
            nodes = self.nodes[id(fn)]
            for call in (n for n in nodes if isinstance(n, ast.Call)):
                found = self.read_of(call, self.taint[id(fn)])
                if not found:
                    continue
                what, whole = found
                looks = {(n.attr if isinstance(n, ast.Attribute) else n.id) for n in nodes
                         if isinstance(n, (ast.Attribute, ast.Name)) and _before(n, call)}
                if looks & SIZED or (not whole and looks & PLAIN):
                    continue
                yield fn, call, what


def _writes(call, at: int) -> bool:
    """An open for writing, whose mode, the argument at `at` or mode=,
    says so."""
    modes = call.args[at:at + 1] + [k.value for k in call.keywords if k.arg == "mode"]
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str)
               and set(m.value) & set("wax+") for m in modes)


def unheld_reads(paths=None, root: Path = REPO) -> list:
    """Each read of what a named path names that goes through no reader
    holding the limits and comes after no look that bounds it, as
    "file:line function, what"."""
    out = []
    for path in paths if paths is not None else _sources():
        rel = path.relative_to(root).as_posix()
        module = _Module(ast.parse(path.read_text(encoding="utf-8-sig")),
                         listings=rel.startswith(LISTED_IN))
        for fn, call, what in module.unheld():
            out.append((rel, call.lineno, "%s:%d %s, %s" % (rel, call.lineno, fn.name, what)))
    return [line for *_, line in sorted(out)]


def test_every_read_of_a_named_file_is_held():
    left = unheld_reads()
    assert not left, "a read of a named file with nothing to bound it:\n" + "\n".join(left)


SAMPLE = '''
import hashlib, shutil
from pathlib import Path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class App:
    def same(self, rec, out):
        own = (rec.get("pdf_path") or "").strip()
        if own and Path(own).is_file():
            return _sha256(own) == out

    def elsewhere(self, rec):
        saved = Path(str(rec.get("pdf_path") or ""))
        if saved.is_file():
            return saved.read_bytes()

    def listed(self, folder):
        for p in folder.iterdir():
            with open(p, "rb") as f:
                f.read()

    def copied(self, row, to):
        shutil.copy2(row["PDF Full Path"], to)

    def opened(self, entry):
        with Path(entry["file"]).open("rb") as f:
            return f.read(1024)

    def inside(self, rec):
        own = rec["pdf_path"]

        def read():
            return Path(own).read_bytes()
        return read()

    def held(self, folder, data):
        for p in folder.glob("*.pdf"):
            if p.is_file() and p.stat().st_size == len(data) and p.read_bytes() == data:
                return True

    def looked_at(self, rec):
        path = Path(rec["pdf_path"])
        if path.is_file():
            with path.open("rb") as f:
                return f.read(1024)

    def written(self, rec):
        with open(rec["pdf_path"], "wb") as f:
            f.write(b"")

    def through_the_reader(self, rec):
        return receipt_pdf.pdf_text(Path(rec["pdf_path"])), intake.sha256_of(rec["pdf_path"])

    def its_own(self, out_path):
        return out_path.read_bytes()
'''


def test_the_census_finds_what_it_looks_for(tmp_path):
    """Not passing on nothing. A made-up app, written to a folder of the
    test's own, holding each way a named file is read, the ways Robinhood
    and E*TRADE read one on 40491dd7 among them, and each way that is held."""
    sample = tmp_path / "apps" / "sample" / "sample_docs.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(SAMPLE, encoding="utf-8")
    found = [line.split(" ", 1)[1] for line in unheld_reads([sample], tmp_path)]
    assert found == [
        "_sha256, read_bytes read whole",
        "elsewhere, read_bytes read whole",
        "listed, opened by open",
        "copied, copied by shutil.copy2",
        "opened, opened by Path(entry['file']).open",
        "read, read_bytes read whole",
    ], found
    # The panel and the tools list no folder a record names.
    tool = tmp_path / "tools" / "sample_tool.py"
    tool.parent.mkdir(parents=True)
    tool.write_text(SAMPLE, encoding="utf-8")
    found = [line.split(" ", 1)[1] for line in unheld_reads([tool], tmp_path)]
    assert "listed, opened by open" not in found and len(found) == 5, found
