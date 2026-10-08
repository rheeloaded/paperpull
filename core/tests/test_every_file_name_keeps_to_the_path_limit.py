"""Every name found for a file keeps to the path limit of its app.

unique_path finds a free name for a file and cuts it to fit
max_path_length, the limit in each app's config, which the message for a
folder too deep to file into tells a person to raise. Called without it,
unique_path keeps to 240 whatever the config says. A name could then be
longer than the person's limit, or a folder deeper than 240 allows was
refused with a ValueError, and Rename's apply() caught only OSError. It
was the one call in the apps and the core that left the limit out, for a
file whose target was taken when apply came to rename it.

So this reads the Python source of every app, the core, the panel and the
server, apart from their tests, and fails on any call of a core function
that takes max_path_length, found by that parameter and never by a name,
that does not pass it, or passes a number of its own in place of the
config's.
"""
import ast
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "paperpull_core"

# What ships, apps and the core and what the panel and the server run.
ROOTS = ("apps", "core", "gui", "server")

LIMIT = "max_path_length"

# Folders that hold no source of ours. A build folder holds a copy of the
# core from whenever the core was last built, which CI does for a wheel,
# and an old copy would be read as code that ships.
SKIP_DIRS = {"tests", "build", "dist", "site-packages", "node_modules", "__pycache__"}


def sources():
    """Every Python file that ships, never a test, and never one in a folder
    of SKIP_DIRS or one whose name starts with a dot, such as an app's
    .venv."""
    out = []
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            out += [Path(folder) / f for f in sorted(files)
                    if f.endswith(".py") and not f.startswith("test_") and f != "conftest.py"]
    return out


def limited_functions() -> dict:
    """Every function of the core's own modules that takes the limit, by
    name, with the place of the limit among its positional arguments, or
    None when it can be passed only by keyword."""
    found = {}
    for path in sorted(CORE.glob("*.py")):
        for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional = [a.arg for a in node.args.posonlyargs + node.args.args]
            keyword_only = [a.arg for a in node.args.kwonlyargs]
            if LIMIT in positional:
                found[node.name] = positional.index(LIMIT)
            elif LIMIT in keyword_only:
                found[node.name] = None
    return found


LIMITED = limited_functions()


def called(func: ast.expr, aliases: dict) -> str:
    """The core function a call reaches, by its own name, its name under an
    import alias, or as an attribute of a module."""
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def what_is_wrong(call: ast.Call, place) -> str:
    """Why a call of a limited function does not keep to the config's
    limit, or "" when it does."""
    if any(k.arg is None for k in call.keywords) or any(
            isinstance(a, ast.Starred) for a in call.args):
        return "passes its arguments in a way this cannot read"
    given = [k.value for k in call.keywords if k.arg == LIMIT]
    if not given and place is not None and len(call.args) > place:
        given = [call.args[place]]
    if not given:
        return "leaves the limit out, so 240 is used whatever the config says"
    if isinstance(given[0], ast.Constant):
        return "passes a number of its own in place of the config's limit"
    return ""


def calls(path: Path):
    """Each call of a limited function in one file, with what is wrong. A
    file that never names one, under an alias or not, is not parsed."""
    text = path.read_text(encoding="utf-8-sig")
    if not any(name in text for name in LIMITED):
        return
    tree = ast.parse(text)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in LIMITED and alias.asname:
                    aliases[alias.asname] = alias.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = called(node.func, aliases)
            if name in LIMITED:
                yield node, what_is_wrong(node, LIMITED[name])


def test_the_functions_that_take_the_limit_are_found():
    """Not a check that passes because it found nothing to check."""
    assert {"unique_path", "fitted_name", "plan"} <= set(LIMITED), LIMITED


def apps():
    """Every app, found by its entry file and never by a list of names."""
    return sorted(d.name for d in (REPO / "apps").iterdir()
                  if d.is_dir() and (any(d.glob("*_docs.py")) or any(d.glob("*_receipts.py"))))


def test_every_name_found_for_a_file_keeps_to_the_config_limit():
    checked, wrong = set(), []
    for path in sources():
        for call, problem in calls(path):
            checked.add(path.relative_to(REPO).parts[:2])
            if problem:
                wrong.append("%s:%d %s, %s" % (path.relative_to(REPO), call.lineno,
                                               ast.unparse(call)[:100], problem))
    # Every app names what it downloads through unique_path, so an app with
    # no call found means this read it wrong, not that it is right.
    unread = [app for app in apps() if ("apps", app) not in checked]
    assert len(apps()) >= 61 and not unread, "found no call to check in %s" % unread
    assert not wrong, "\n".join(wrong)
