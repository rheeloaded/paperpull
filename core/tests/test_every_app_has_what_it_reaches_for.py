"""Every site.SOMETHING an app reaches for exists in that app's site module.

A user hit ModuleNotFoundError halfway through a download, because six apps
carried an import of a module that had moved, inside a function, where
nothing runs until a real account is being read. test_imports_resolve came
out of that, and its reasoning is the part worth keeping: an import at the
top of a file is checked by the act of loading it, and a deferred one is
checked by nothing.

An attribute on another module is the same. The orchestrator says
site.download_document(...) and if that app's site module has no such name,
nothing says so until the page is in front of it. Ruff cannot see it,
because it is one module reaching into another.

Asked of all forty-eight, it found six, in four apps, all inside
cmd_diagnose's try block. So nothing crashed. What happened instead is that
the survey stopped at that line and wrote an AttributeError, and Diagnose is
the file a maintainer reads to repair a provider. UKG's stopped five fields
in and had never once produced the rest.
"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d)
              and (d / ("%s_site.py" % d.name)).exists())


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def alias_for_site(tree) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if name.name.endswith("_site"):
                    return name.asname or name.name
    return ""


def reached_for(tree, alias: str) -> dict:
    """name -> first line that asks for it."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == alias:
            out.setdefault(node.attr, node.lineno)
    return out


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_everything_this_app_asks_its_site_module_for_is_there(app):
    entry = entry_of(app)
    tree = ast.parse(entry.read_text(encoding="utf-8", errors="ignore"))
    alias = alias_for_site(tree)
    assert alias, "%s never imports its site module" % app.name
    site = site_of(app)
    wanted = reached_for(tree, alias)
    assert wanted, "%s imports its site module and asks it nothing" % app.name
    missing = ["%s (line %d)" % (name, line)
               for name, line in sorted(wanted.items()) if not hasattr(site, name)]
    assert not missing, (
        "%s reaches for names its site module does not have, which raises "
        "the moment that line runs: %s" % (app.name, ", ".join(missing)))


def test_this_is_asking_about_a_real_number_of_names():
    """If the alias detection breaks, every app above passes by asking
    about nothing. The count is roughly eight hundred."""
    total = 0
    for app in APPS:
        tree = ast.parse(entry_of(app).read_text(encoding="utf-8", errors="ignore"))
        total += len(reached_for(tree, alias_for_site(tree)))
    assert total > 500, "only %d site names were examined, which is too few" % total


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_an_except_clause_names_something_that_exists(app):
    """`except site.NotMapped` cost nothing until collection failed, and
    then replaced the real error with an AttributeError about the handler.
    A handler is only evaluated when there is already a problem, which is
    the worst moment to introduce another one."""
    entry = entry_of(app)
    tree = ast.parse(entry.read_text(encoding="utf-8", errors="ignore"))
    alias = alias_for_site(tree)
    site = site_of(app) if alias else None
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        for named in (node.type.elts if isinstance(node.type, ast.Tuple)
                      else [node.type]):
            if isinstance(named, ast.Attribute) and isinstance(named.value, ast.Name) \
                    and named.value.id == alias and not hasattr(site, named.attr):
                bad.append("line %d, except %s.%s" % (node.lineno, alias, named.attr))
    assert not bad, "%s catches something that does not exist: %s" % (
        app.name, ", ".join(bad))


# -- and the same question of every other module an app reaches into -----------

def imported_modules(tree) -> dict:
    """alias -> module, for `import x as y` and `from a import b`."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                out[name.asname or name.name.split(".")[0]] = name.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for name in node.names:
                if name.name[:1].islower() and "." not in name.name:
                    out[name.asname or name.name] = "%s.%s" % (node.module, name.name)
    return out


def files_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py", "*_site.py", "storage.py"):
        for path in sorted(app.glob(pattern)):
            yield path


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_everything_this_app_asks_any_module_for_is_there(app):
    """receipt_pdf, doc_types, browser_launcher, failure, renaming, scope.
    The site module was only the one that turned out to be wrong."""
    missing = []
    for path in files_of(app):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        aliases = imported_modules(tree)
        wanted = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id in aliases:
                wanted.setdefault((node.value.id, node.attr), node.lineno)
        for (alias, attr), line in sorted(wanted.items()):
            target = aliases[alias]
            if target.endswith("_site") or target == "storage":
                continue                      # app-local, covered above
            for name in [m for m in list(sys.modules)
                         if m.endswith("_site") or m == "storage"]:
                del sys.modules[name]
            sys.path.insert(0, str(app))
            try:
                mod = importlib.import_module(target)
            except Exception:
                continue                      # not importable here, not this check
            finally:
                sys.path.pop(0)
            if not hasattr(mod, attr):
                missing.append("%s:%d %s.%s from %s"
                               % (path.name, line, alias, attr, target))
    assert not missing, (
        "%s reaches for names that are not there: %s" % (app.name, ", ".join(missing)))


def test_the_wider_check_is_also_asking_about_something():
    """Two thousand or so. If the alias map ever comes back empty, every
    app above passes by examining nothing, which is how a check quietly
    stops being one."""
    total = 0
    for app in APPS:
        for path in files_of(app):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            aliases = imported_modules(tree)
            total += len({(n.value.id, n.attr) for n in ast.walk(tree)
                          if isinstance(n, ast.Attribute)
                          and isinstance(n.value, ast.Name)
                          and n.value.id in aliases})
    assert total > 1500, "only %d module names were examined" % total
