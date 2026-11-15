"""No app, tool, core module or panel code asks Path.exists, is_file,
is_dir, is_symlink, stat or lstat, or os.stat, os.lstat or os.path.getsize,
of a path a record, an index row or a listing named, outside the body of a
try that catches OSError.

Python 3.12, which every build ships, re-raises from those an error other
than "not there", so a path in a folder the run may not search ended the
run at that document on every run, in 95 apps' _already_done, in
Robinhood, Amazon, the transactions export, Rename's plan and the panel's
Documents count (a bug hunt of 2026-11-14). receipt_pdf.copy_still_valid
and shared_folder.file_there ask so it never raises.

This finds each such question by where its path came from, never by the
function's name. A path is a record's or a row's when it is read from one
of FIELDS, from a key a function is handed for that field (KEY_NAMES), or
by a function that reads it from a row (READERS), and so is any name
assigned from an expression that holds one, through a chain of
assignments, a tuple, a for loop or a comprehension. A question in an
except, else or finally block is not caught by its own try.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
        "site-packages"}
ASKS = {"exists", "is_file", "is_dir", "is_symlink", "stat", "lstat"}
OS_ASKS = {"os.stat", "os.lstat", "os.path.getsize", "os.path.getmtime", "os.path.getctime"}
# The fields a record, an index row or a listing names a file by.
FIELDS = {"pdf_path", "file", "PDF Full Path", "Receipt PDF"}
# A key a function is handed for the field a path is in (renaming.plan).
KEY_NAMES = {"path_key"}
# A function that reads a row's path (export_transactions.pdf_path).
READERS = {"pdf_path"}
# Questions the census sees that are not of a path a row names, each with
# why. Rename asks whether the new name is free in the file's own filing
# folder, a folder of the account's that a download writes into, reached
# here through the row only because the plan carries both in one tuple.
NOT_A_ROW_S_PATH = {
    "core/paperpull_core/renaming.py target.exists()",
}
CATCHES = {"OSError", "Exception", "BaseException", "PermissionError", "IOError",
           "EnvironmentError"}


def _sources():
    for root in ("apps", "tools", "core/paperpull_core", "gui"):
        for top, dirs, files in os.walk(REPO / root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
            for name in sorted(files):
                if name.endswith(".py"):
                    yield Path(top) / name


def _key(node) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in FIELDS
    return isinstance(node, ast.Name) and node.id in KEY_NAMES


def _from_a_field(node) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "get" and n.args and _key(n.args[0]):
                return True
            if isinstance(f, ast.Name) and f.id in READERS:
                return True
        if isinstance(n, ast.Subscript) and _key(n.slice):
            return True
    return False


def _names(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _bindings(fn):
    """Each (target, value) a function binds a name by."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                yield t, n.value
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value is not None:
            yield n.target, n.value
        elif isinstance(n, ast.NamedExpr):
            yield n.target, n.value
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            yield n.target, n.iter


def _named_by_a_record(fn) -> set:
    named = set()
    pairs = list(_bindings(fn))
    grew = True
    while grew:
        grew = False
        for target, value in pairs:
            if _from_a_field(value) or _names(value) & named:
                new = _names(target) - named
                if new:
                    named |= new
                    grew = True
    return named


def _caught(node, parents) -> bool:
    child = node
    while child in parents:
        par = parents[child]
        if isinstance(par, ast.Try) and child in par.body:
            for h in par.handlers:
                types = (h.type.elts if isinstance(h.type, ast.Tuple)
                         else [h.type] if h.type else [])
                if h.type is None or {ast.unparse(t) for t in types} & CATCHES:
                    return True
        if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        child = par
    return False


def _asked_of(call):
    """The path a call asks the disk about, or None."""
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in ASKS and not call.args:
        return f.value
    if isinstance(f, ast.Attribute) and ast.unparse(f) in OS_ASKS and call.args:
        return call.args[0]
    return None


def asked_bare_in(source: str, where: str = "<sample>") -> list:
    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        named = _named_by_a_record(fn)
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            asked = _asked_of(n)
            if asked is None or not (_from_a_field(asked) or _names(asked) & named):
                continue
            if not _caught(n, parents):
                found.append("%s:%d %s" % (where, n.lineno, ast.unparse(n)))
    return sorted(set(found))


def asked_bare(path: Path) -> list:
    return asked_bare_in(path.read_text(encoding="utf-8-sig"),
                         path.relative_to(REPO).as_posix())


def _excused(found: str) -> bool:
    where, _, asked = found.partition(" ")
    return "%s %s" % (where.rsplit(":", 1)[0], asked) in NOT_A_ROW_S_PATH


def test_no_path_a_record_names_is_asked_about_outside_a_try():
    found = [f for p in _sources() for f in asked_bare(p)]
    assert not [f for f in found if not _excused(f)], found


def test_each_question_let_be_is_still_there():
    """An excuse outlives the line it was for only until this fails."""
    found = {"%s %s" % (f.split(" ", 1)[0].rsplit(":", 1)[0], f.split(" ", 1)[1])
             for p in _sources() for f in asked_bare(p)}
    assert NOT_A_ROW_S_PATH <= found, NOT_A_ROW_S_PATH - found


# The shapes a path from a record reaches a question by, each of which the
# census must see, and the ones it must let be.
SEEN = {
    "field": 'def f(rec):\n    return Path(rec.get("pdf_path")).exists()\n',
    "subscript": 'def f(e):\n    return Path(e["file"]).is_file()\n',
    "two steps": 'def f(rec):\n    raw = rec.get("pdf_path")\n    p = Path(raw)\n'
                 '    where = p.resolve()\n    return where.is_file()\n',
    "for loop": 'def f(rec):\n    files = [rec.get("pdf_path")]\n    for raw in files:\n'
                '        Path(raw).exists()\n',
    "tuple": 'def f(rec):\n    a, b = rec.get("pdf_path"), 1\n    return a.stat()\n',
    "comprehension": 'def f(rows):\n    return [Path(r["PDF Full Path"]) for r in rows'
                     ' if Path(r["PDF Full Path"]).is_file()]\n',
    "key handed in": 'def f(row, path_key):\n    raw = row.get(path_key)\n'
                     '    return Path(raw).exists()\n',
    "reader": 'def f(index, r):\n    return pdf_path(index, r).is_file()\n',
    "os.path.getsize": 'def f(rec):\n    return os.path.getsize(rec["pdf_path"])\n',
    "walrus": 'def f(rec):\n    if (p := Path(rec["file"])).exists():\n        pass\n',
    "in a handler": 'def f(rec):\n    try:\n        pass\n    except OSError:\n'
                    '        Path(rec["file"]).exists()\n',
    "caught by a narrower try": 'def f(rec):\n    try:\n        Path(rec["file"]).exists()\n'
                                '    except ValueError:\n        pass\n',
}
LET_BE = {
    "in a try": 'def f(rec):\n    try:\n        return Path(rec["file"]).exists()\n'
                '    except OSError:\n        return False\n',
    "the helper": 'def f(rec):\n    return shared_folder.file_there(rec.get("pdf_path"))\n',
    "a path of its own": 'def f(self):\n    return self.paths.out.exists()\n',
    "another field": 'def f(rec):\n    return Path(rec.get("profile_dir")).exists()\n',
}


def test_the_census_sees_every_shape_a_record_s_path_takes():
    missed = [name for name, source in SEEN.items() if not asked_bare_in(source)]
    assert not missed, missed


def test_the_census_lets_a_question_asked_safely_be():
    flagged = {name: asked_bare_in(source) for name, source in LET_BE.items()}
    assert not any(flagged.values()), flagged
