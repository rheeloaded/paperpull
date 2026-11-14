"""No app writes a file the plain way, and the core only where reviewed.
Each goes through the core's shared_folder, which writes as the plain call
does on the desktop and never through a link on PaperPull Server.

On the server every provider's folder is in the data folder, often a share
other people on the network can write to and leave a link in. A download's
name is one anybody can guess, the date and the provider, and so is the
staged name it is written to first. A plain write_bytes there wrote the
document through a link left at the name, wherever it led, the server's own
password file among the places (a private report of 2026-11-10). There
were 97 of them, in 64 apps.

Playwright writes a file the same plain way when it is handed a path, a
download's save_as, a page's pdf(path=) and screenshot(path=), the last at
fixed names such as Diagnostics/diagnose-documents.png in 28 apps. So do
shutil's copies and its move, which also moves a file into the folder a
link at its name leads to. Each goes through shared_folder too, and in the
core, where the helpers themselves live, each plain write left is one
reviewed here with what it touches.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules"}
APPROVED = ("shared_folder.", "_shared_folder.")

# The core's plain writes, by file, function and call. Reviewed 2026-11-14.
CORE_REVIEWED = {
    "browser.py:_remember_declined:marker.write_text": "Playwright's browsers folder, never the share",
    "intake.py:save_download_as:download.save_as": "into a folder tempfile.mkdtemp made for it",
    "pdf_reader.py:_serve:open('w')": "os.devnull",
    "renaming.py:_moved_across:shutil.copyfileobj": "into a file open_to_write opened",
    "shared_folder.py:move:shutil.move": "the desktop branch",
    "shared_folder.py:write_bytes:Path(path).write_bytes": "the desktop branch",
    "storage.py:backup_file:shutil.copy2": "the desktop branch",
    "storage.py:backup_file:shutil.copyfileobj": "into a file open_to_write opened",
    "storage.py:backup_file:shutil.copystat": "onto the file open_to_write just wrote",
    "storage.py:ensure:probe.write_text": "the desktop branch, the server's probe is mkstemp",
    "storage.py:ensure_owner:Path(config_path).write_text": "the desktop branch",
    "testkit.py:receipt_app:cfg.write_text": "test support, a temp folder",
    "testkit.py:file_a_receipt:out.write_bytes": "test support, a temp folder",
    "testkit.py:fake:out.write_bytes": "test support, a temp folder",
}


def _sources(top_folder: Path):
    for top, dirs, files in os.walk(top_folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(top) / name


def _mode(call):
    """The mode an open is asked for, the second argument of open() and the
    first of a path's own open()."""
    at = 0 if isinstance(call.func, ast.Attribute) and ast.unparse(call.func) != "io.open" else 1
    if len(call.args) > at and isinstance(call.args[at], ast.Constant):
        return str(call.args[at].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"


def _plain_writes(path: Path) -> list:
    """(line, function, call) for each plain write in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

    def function_of(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = ast.unparse(n.func)
        if name.startswith(APPROVED):
            continue
        what = None
        if isinstance(n.func, ast.Attribute) and n.func.attr in ("write_bytes", "write_text",
                                                                 "save_as"):
            what = name
        elif (isinstance(n.func, ast.Attribute) and n.func.attr in ("pdf", "screenshot")
              and any(k.arg == "path" for k in n.keywords)):
            what = "%s(path=)" % name
        elif name.startswith("shutil.copy") or name in ("shutil.move", "os.link", "os.symlink"):
            what = name
        elif (name in ("open", "io.open") or (isinstance(n.func, ast.Attribute)
                                              and n.func.attr == "open")) \
                and any(c in _mode(n) for c in "wax+"):
            what = "%s(%r)" % (name, _mode(n))
        if what:
            out.append((n.lineno, function_of(n), what))
    return out


def test_every_app_writes_through_the_core():
    plain = ["%s:%d %s" % (p.relative_to(REPO / "apps").as_posix(), line, what)
             for p in _sources(REPO / "apps") for line, _fn, what in _plain_writes(p)]
    assert not plain, plain


def test_no_app_reaches_shutil_or_open_by_another_name():
    """So the census above is never passed by `from shutil import move`."""
    found = []
    for p in _sources(REPO / "apps"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8-sig"))):
            if isinstance(n, ast.ImportFrom) and n.module in ("shutil", "io") and \
                    any(a.name in ("move", "copy", "copy2", "copyfile", "copytree", "open")
                        for a in n.names):
                found.append("%s:%d from %s import" % (p.name, n.lineno, n.module))
            if isinstance(n, ast.Import) and any(a.name == "shutil" and a.asname for a in n.names):
                found.append("%s:%d import shutil as" % (p.name, n.lineno))
    assert not found, found


def _core_writes() -> set:
    core = REPO / "core" / "paperpull_core"
    return {"%s:%s:%s" % (p.name, fn, what) for p in sorted(core.glob("*.py"))
            for _line, fn, what in _plain_writes(p)}


def test_every_plain_write_left_in_the_core_is_one_reviewed():
    unreviewed = sorted(_core_writes() - set(CORE_REVIEWED))
    assert not unreviewed, "write these through shared_folder, or review them: %s" % unreviewed


def test_every_core_write_reviewed_is_still_there():
    gone = sorted(set(CORE_REVIEWED) - _core_writes())
    assert not gone, gone


def test_there_are_apps_to_look_at():
    assert sum(1 for _ in _sources(REPO / "apps")) > 200
