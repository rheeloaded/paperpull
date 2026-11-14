"""Every app's sign-in window is opened at a web address the launcher takes.

The launcher now refuses an address that is not http or https with a name
after the //, since the address is the last thing on the browser's command
line and Chromium read a value like --no-sandbox there as a switch of its
own (paperpull_core.browser.signin_address_ok). A sign-in address the check
refused would leave that app with no way to sign in, so each app's own
addresses are held to it here, read from its site module as it runs, and
each app's Login command is read for where its address comes from, its
site module's URLS or a written address the check takes. UKG's URLS is
built from the person's base_url, which the import holds to UKG's own
domains, and which the launcher refuses whole when it is not an address.
"""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from paperpull_core import browser

REPO = Path(__file__).resolve().parents[2]
SITES = sorted((REPO / "apps").glob("*/*_site.py"))
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py"))
                 and "open_signin_browser(" in p.read_text(encoding="utf-8-sig"))


def site_module(path: Path):
    name = "_signin_census_" + path.stem
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(path.parent))
        sys.modules.pop(name, None)


def test_there_are_apps_to_look_at():
    assert len(SITES) > 80 and len(ENTRIES) > 80


@pytest.mark.parametrize("path", SITES, ids=[p.parent.name for p in SITES])
def test_every_address_an_app_opens_is_one_the_launcher_takes(path):
    urls = getattr(site_module(path), "URLS", None) or {}
    refused = {k: v for k, v in urls.items() if not browser.signin_address_ok(v)}
    assert not refused, refused


def _from_urls(node) -> bool:
    """site.URLS["x"] or site.URLS.get("x")."""
    if isinstance(node, ast.Subscript):
        return ast.unparse(node.value).endswith("URLS")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr == "get" and ast.unparse(node.func.value).endswith("URLS")
    return False


def _unsure_parts(node) -> list:
    """The parts of an address expression that are neither the site's URLS
    nor a written address the launcher takes."""
    if _from_urls(node):
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [] if browser.signin_address_ok(node.value) else [node.value]
    if isinstance(node, ast.BoolOp):
        return [p for v in node.values for p in _unsure_parts(v)]
    if isinstance(node, ast.IfExp):
        return _unsure_parts(node.body) + _unsure_parts(node.orelse)
    return [ast.unparse(node)]


@pytest.mark.parametrize("path", ENTRIES, ids=[p.parent.name for p in ENTRIES])
def test_every_login_command_opens_an_address_from_its_site(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    calls = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        opens = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and ast.unparse(c.func).endswith("open_signin_browser")]
        if not opens:
            continue
        assigned = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(node.value)
        for call in opens:
            calls += 1
            given = call.args[2] if len(call.args) > 2 else next(
                (k.value for k in call.keywords if k.arg == "url"), None)
            assert given is not None, "%s: no address handed over" % fn.name
            values = assigned.get(given.id, []) if isinstance(given, ast.Name) else [given]
            assert values, "%s: %s is never set" % (fn.name, ast.unparse(given))
            unsure = [p for v in values for p in _unsure_parts(v)]
            assert not unsure, "%s opens %s" % (fn.name, unsure)
    assert calls, "no Login command found"
