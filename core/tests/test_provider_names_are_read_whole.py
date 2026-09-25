"""Every tool that reads a provider's name out of storage.py reads all of it.

The panel, the status tool and the migration tool each find an app's name
with a regex over its storage.py rather than importing it. All three
stopped at any quote mark, so provider="Lowe's" came back as "Lowe", the
first name with an apostrophe in fifty. Each pattern is taken from its own
file here, so a copy that drifts is caught, and held to the name the
app's AppSpec really declares, for every app.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
READERS = {
    "gui/app.py": "_PROVIDER_RE",
    "tools/status.py": "PROVIDER_RE",
    "tools/migrate.py": "PROVIDER_RE",
}


def _pattern(path: str, name: str) -> "re.Pattern":
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets)
                and isinstance(node.value, ast.Call) and node.value.args):
            return re.compile(ast.literal_eval(node.value.args[0]))
    raise AssertionError("%s has no %s" % (path, name))


def _declared(storage: Path) -> str:
    """The provider= of the AppSpec call, as Python reads it."""
    for node in ast.walk(ast.parse(storage.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AppSpec":
            for kw in node.keywords:
                if kw.arg == "provider":
                    return ast.literal_eval(kw.value)
    return ""


APPS = sorted(p for p in (REPO / "apps").glob("*/storage.py") if _declared(p))


def test_there_are_apps_to_read():
    assert len(APPS) >= 50


@pytest.mark.parametrize("path,name", sorted(READERS.items()))
def test_each_reader_gets_every_apps_name_whole(path, name):
    pattern = _pattern(path, name)
    wrong = {}
    for storage in APPS:
        m = pattern.search(storage.read_text(encoding="utf-8"))
        got = m.group(1) if m else None
        if got != _declared(storage):
            wrong[storage.parent.name] = got
    assert not wrong, "%s reads these names wrong: %s" % (path, wrong)


@pytest.mark.parametrize("path,name", sorted(READERS.items()))
def test_an_apostrophe_and_either_quote_are_read(path, name):
    pattern = _pattern(path, name)
    for src, want in (('provider="Lowe\'s",', "Lowe's"), ("provider='Target',", "Target"),
                      ('provider = "Kroger (Pick \'n Save)"', "Kroger (Pick 'n Save)")):
        assert pattern.search(src).group(1) == want, src
