"""No app writes a file the plain way. Each goes through the core's
shared_folder, which writes as the plain call does on the desktop and never
through a link on PaperPull Server.

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
link at its name leads to. Each goes through shared_folder too.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules"}
APPROVED = ("shared_folder.", "_shared_folder.")


def _sources():
    for top, dirs, files in os.walk(REPO / "apps"):
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


def test_every_app_writes_through_the_core():
    plain = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        where = path.relative_to(REPO / "apps").as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = ast.unparse(n.func)
            if name.startswith(APPROVED):
                continue
            if isinstance(n.func, ast.Attribute) and n.func.attr in ("write_bytes", "write_text",
                                                                     "save_as"):
                plain.append("%s:%d %s" % (where, n.lineno, name))
            elif (isinstance(n.func, ast.Attribute) and n.func.attr in ("pdf", "screenshot")
                  and any(k.arg == "path" for k in n.keywords)):
                plain.append("%s:%d %s(path=)" % (where, n.lineno, name))
            elif name.startswith("shutil.copy") or name in ("shutil.move", "os.link",
                                                            "os.symlink"):
                plain.append("%s:%d %s" % (where, n.lineno, name))
            elif (name in ("open", "io.open") or (isinstance(n.func, ast.Attribute)
                                                  and n.func.attr == "open")) \
                    and any(c in _mode(n) for c in "wax+"):
                plain.append("%s:%d %s(%r)" % (where, n.lineno, name, _mode(n)))
    assert not plain, plain


def test_there_are_apps_to_look_at():
    assert sum(1 for _ in _sources()) > 200
