"""Every import in every app must actually resolve.

A user hit this in the wild. Six apps still carried "from receipt_pdf import
save_download" from before that module moved into paperpull_core, and every
one of those raised ModuleNotFoundError the moment a download started.

874 tests did not catch it, and the reason is worth stating. The imports sit
INSIDE functions, so nothing executes them until the app is running against a
real account, and no amount of importing the module at test time reaches them.
An import at the top of a file is checked by the act of loading it. A deferred
one is checked by nothing.

So this walks the syntax tree instead, finds every import at any depth, and
asks whether the module exists.
"""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir())

# Imports guarded for a platform or an optional feature. Nothing here today,
# but the list is the honest place to put one rather than loosening the check.
EXPECTED_MISSING = set()


def _module_names(tree):
    """(module, lineno) for every absolute import anywhere in the tree."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((a.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # relative, resolved against the package
                continue
            if node.module:
                out.append((node.module.split(".")[0], node.lineno))
    return out


def _resolves(name, *extra_paths):
    """Both the file's own folder and the app root go on the path.

    A file under tests/ imports its app's storage and *_site modules, which sit
    one level up, exactly as the app's own conftest arranges at runtime.
    Checking only the file's own folder reported every app as broken, which was
    the check being wrong rather than the apps.
    """
    added = [str(p) for p in extra_paths]
    sys.path[:0] = added
    try:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            return False
    finally:
        del sys.path[:len(added)]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_import_in_this_app_resolves(app):
    """Including the ones hidden inside functions, which is where the real
    failure lived."""
    # utf-8-sig, not utf-8. One app's entry file carries a byte order mark,
    # which Python itself handles when importing, so a check that chokes on it
    # is reporting a fault in the check.
    broken = []
    for py in sorted(app.rglob("*.py")):
        if ".venv" in py.parts or "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8-sig"))
        except SyntaxError as e:
            broken.append("%s:%s does not parse (%s)" % (py.name, e.lineno, e.msg))
            continue
        for name, lineno in _module_names(tree):
            if name in EXPECTED_MISSING:
                continue
            if not _resolves(name, py.parent, app):
                broken.append("%s:%d imports %r, which does not exist"
                              % (py.name, lineno, name))
    assert not broken, "\n".join(broken)


def test_the_module_that_actually_broke_is_gone_for_good():
    """receipt_pdf moved into paperpull_core. Naming it directly is the exact
    mistake a user reported, and it is silent until a download starts."""
    offenders = []
    for app in APPS:
        for py in sorted(app.rglob("*.py")):
            if ".venv" in py.parts or "__pycache__" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8-sig"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in (
                        "receipt_pdf", "models", "doc_types", "classification"):
                    offenders.append("%s/%s:%d imports %r directly" % (
                        app.name, py.name, node.lineno, node.module))
    assert not offenders, "\n".join(offenders)
