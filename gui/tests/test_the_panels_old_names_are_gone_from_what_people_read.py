"""The names the panel stopped using are gone from everything a person reads.

The panel's words were made one name for each thing, and its buttons named
as they read on screen. The messages the Documents folder's checks send the
page still said "the folder for every provider" and named a button, Use the
folder for every provider, that is now Use the Documents folder, and the
READMEs named Only check what's there, Rename preview, Apply renames and
Preview move, none of which is on screen any more.

A program's names are not words for a person, so the actions' labels in
gui/app.py ACTIONS, which the page never shows, and every comment and
docstring are left out.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "gui" / "static"

# Names the page no longer shows, each with the one it shows instead.
ON_SCREEN = {
    "Only check what's there": "Check what's there",
    "Only check what\\'s there": "Check what's there",
    "Rename preview": "1. Preview",
    "Apply renames": "2. Rename",
    "Preview move": "1. Preview",
    "folder for every provider": "the Documents folder",
    "Use it for every provider": "Apply to every account",
    "Use each provider's own folder": "Keep documents in the provider's folder",
    "Folder for your documents": "Your PaperPull folder",
    "Back to accounts": "All accounts",
    "Latest documents": "Newest documents",
}

# What the docs may not name in bold, the way they name a control.
IN_DOCS = ["Only check what's there", "**Rename preview**", "**Apply renames**",
           "**Preview move**", "**Use the folder for every provider**", "**Use it for",
           "**Preview renames**", "**Rename them**", "**Use each provider's own folder**"]


def _page_lines(path: Path):
    """Each line of a page file that is not a comment."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("//"):
            yield n, line


@pytest.mark.parametrize("name", ["app.js", "index.html"])
def test_the_page_never_shows_a_name_it_stopped_using(name):
    found = ["%s:%d %s" % (name, n, old) for n, line in _page_lines(STATIC / name)
             for old in ON_SCREEN if old in line]
    assert not found, found


def _said_strings(path: Path):
    """Every string in gui/app.py that is not a docstring, nor a label in
    ACTIONS, as (line, text)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ACTIONS"
                                                for t in node.targets):
            skip.update(id(n) for n in ast.walk(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def test_no_message_from_the_panel_names_what_it_stopped_using():
    strings = list(_said_strings(REPO / "gui" / "app.py"))
    assert strings, "gui/app.py was read"
    # Messages are split across lines, so they are read joined.
    joined = " ".join(" ".join(text.split()) for _, text in strings)
    found = [old for old in ("folder for every provider", "Use it for every provider",
                             "Use the folder for every provider") if old in joined]
    assert not found, found


def _docs():
    yield from (REPO / name for name in ("README.md", "SERVER.md", "PRIVACY.md", "PRIVACY-SERVER.md"))
    yield REPO / "gui" / "README.md"
    yield from sorted((REPO / "docs").glob("*.md"))
    yield from sorted((REPO / "apps").glob("*/README.md"))


def test_no_doc_names_a_control_the_panel_stopped_showing():
    found = []
    for path in _docs():
        if not path.is_file():
            continue
        text = " ".join(path.read_text(encoding="utf-8").split())
        found += ["%s %s" % (path.relative_to(REPO).as_posix(), old) for old in IN_DOCS if old in text]
    assert not found, found


def test_a_folder_with_no_config_is_told_what_mends_it(tmp_path):
    """Adding a person to a provider whose folder has no config.json said to
    sign in once first, and a sign-in never writes one. Setting a provider
    up copies its config.example.json, which is what mends it."""
    folder = tmp_path / "Chase Statements"
    folder.mkdir()
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._make_account(folder, "spouse", "")
    said = e.value.detail
    assert e.value.status_code == 409 and "Chase Statements has no config.json yet" in said
    assert "copy config.example.json to config.json" in said and "sign" not in said.lower(), said


def test_the_census_reads_what_it_says_it_reads():
    """Each list is found where it is looked for, so an empty walk is never
    a pass."""
    docs = [p for p in _docs() if p.is_file()]
    assert len(docs) > 50 and REPO / "README.md" in docs
    assert any("Check what's there" in line for _, line in _page_lines(STATIC / "app.js"))
    assert any("the Documents folder" in text for _, text in _said_strings(REPO / "gui" / "app.py"))
