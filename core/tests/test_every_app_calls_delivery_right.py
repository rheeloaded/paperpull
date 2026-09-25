"""Every call an app makes into paperpull_core.delivery is one it accepts.

0.34.0 shipped with four apps passing rivals= to deliver(), which did not
take it. Every document T-Mobile, Navy Federal, Target RedCard and
Fairfax Water asked for failed with a TypeError before anything was
pressed, the run caught it as an ordinary failure, and every one of
those apps' own tests passed, because none of them calls download_one.

So this reads each app's calls and checks each keyword against the real
signature. It needs no browser and no account, which is the point.
"""
import ast
import inspect
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import delivery  # noqa: E402

APPS = sorted(p for p in (REPO / "apps").iterdir()
              if p.is_dir() and not p.name.startswith(("_", ".")))
IDS = [p.name for p in APPS]
FUNCTIONS = ("deliver", "place", "render")


def accepted(name):
    params = inspect.signature(getattr(delivery, name)).parameters
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return None
    return set(params)


def calls(tree):
    """Calls to delivery.deliver/place/render, however it was imported."""
    modules, direct = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "paperpull_core":
                for a in node.names:
                    if a.name == "delivery":
                        modules.add(a.asname or "delivery")
            elif (node.module or "").endswith("paperpull_core.delivery"):
                for a in node.names:
                    if a.name in FUNCTIONS:
                        direct[a.asname or a.name] = a.name
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "paperpull_core.delivery" and a.asname:
                    modules.add(a.asname)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr in FUNCTIONS
                and isinstance(f.value, ast.Name) and f.value.id in modules):
            yield f.attr, node
        elif isinstance(f, ast.Name) and f.id in direct:
            yield direct[f.id], node


def test_the_reader_finds_the_call_that_broke_four_apps():
    tree = ast.parse("from paperpull_core import delivery\n"
                     "delivery.deliver(page, req, out,\n"
                     "    is_safe_url=g, rivals=r)\n")
    found = list(calls(tree))
    assert [name for name, _ in found] == ["deliver"]


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_keyword_an_app_passes_is_one_delivery_takes(app):
    for path in sorted(app.glob("*.py")):
        text = io.open(path, encoding="utf-8", errors="ignore").read()
        for name, call in calls(ast.parse(text)):
            allowed = accepted(name)
            if allowed is None:
                continue
            for kw in call.keywords:
                if kw.arg is None:
                    continue
                assert kw.arg in allowed, (
                    "%s:%d passes %s= to delivery.%s, which does not take "
                    "it" % (path.name, call.lineno, kw.arg, name))


# What each app's capture waited before it handed the click over. The
# default wait is twenty seconds, and a migration that dropped to it made
# RedCard press a statement a second time on a download that was coming.
WAITED_BEFORE = {"tmobile": 60000, "redcard": 45000}


@pytest.mark.parametrize("name", sorted(WAITED_BEFORE))
def test_a_migrated_app_waits_as_long_as_it_did_before(name):
    app = REPO / "apps" / name
    found = []
    for path in sorted(app.glob("*.py")):
        text = io.open(path, encoding="utf-8", errors="ignore").read()
        for fn, call in calls(ast.parse(text)):
            if fn != "deliver":
                continue
            settle = [k for k in call.keywords if k.arg == "settle_ms"]
            found.append(settle[0].value.value if settle and isinstance(
                settle[0].value, ast.Constant) else delivery.SETTLE_MS)
    assert found and min(found) >= WAITED_BEFORE[name], found
