"""No app, tool or core module asks Path.exists, is_file, is_dir or stat of a
path a record, an index row or a listing named, outside a try that catches
OSError.

Python 3.12, which every build ships, re-raises from those an error other
than "not there", so a path in a folder the run may not search ended the
run at that document on every run, in 95 apps' _already_done and in
Robinhood, Amazon and the transactions export (a bug hunt of 2026-11-14).
receipt_pdf.copy_still_valid and shared_folder.file_there ask so it never
raises. This finds each such question by the call and where its path came
from, a record's or a row's field, never by the function's name.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
        "site-packages"}
ASKS = {"exists", "is_file", "is_dir", "stat"}
# The fields a record, an index row or a listing names a file by.
FIELDS = {"pdf_path", "file", "PDF Full Path", "Receipt PDF"}
CATCHES = {"OSError", "Exception", "BaseException", "PermissionError"}


def _sources():
    for root in ("apps", "tools", "core/paperpull_core", "gui"):
        for top, dirs, files in os.walk(REPO / root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
            for name in sorted(files):
                if name.endswith(".py"):
                    yield Path(top) / name


def _from_a_field(node) -> bool:
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value in FIELDS):
            return True
        if (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                and n.slice.value in FIELDS):
            return True
    return False


def _caught(node, parents) -> bool:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.Try):
            for h in node.handlers:
                names = {ast.unparse(t) for t in (h.type.elts if isinstance(h.type, ast.Tuple)
                                                  else [h.type] if h.type else [])}
                if h.type is None or names & CATCHES:
                    return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
    return False


def asked_bare(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        named = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and _from_a_field(n.value):
                named |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ASKS and not n.args):
                continue
            receiver = n.func.value
            from_field = _from_a_field(receiver) or any(
                isinstance(x, ast.Name) and x.id in named for x in ast.walk(receiver))
            if from_field and not _caught(n, parents):
                found.append("%s:%d %s" % (path.relative_to(REPO).as_posix(), n.lineno,
                                           ast.unparse(n)))
    return found


def test_no_path_a_record_names_is_asked_about_outside_a_try():
    found = [f for p in _sources() for f in asked_bare(p)]
    assert not found, found
