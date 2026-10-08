"""No census of the repository's Python reads a copy a build made.

Installing the core on CI (`pip install ./core`) builds it inside the
checkout and leaves core/build/lib/paperpull_core, a second copy of every
core module. The page-script census read that copy's press as one nobody
reviewed and failed every CI run from d92f3873 (fixed in d06a1770). The
force census read all 34 copies as sources of their own, so CI's core suite
ran 34 more tests than a land here from 39110f4d on, and the main checkout
here still holds a build folder from August with an older core in it.

So this finds, by what it does, every helper in a core test module that
walks a folder for Python files, points it at a made-up tree holding the
folders a build or an install makes beside the source, and fails on any
copy it hands back. It never touches the checkout.
"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

# What a build or an install leaves inside a checkout.
MADE = ["core/build/lib/paperpull_core/pressing.py", "core/dist/pressing.py",
        "gui/build/app.py", "gui/dist/app.py",
        "gui/node_modules/x/pressing.py", "apps/sample/site-packages/pressing.py",
        "apps/sample/build/lib/sample_site.py", "server/build/lib/serve.py",
        "tools/build/t.py"]
# The source beside it, tests too, since one census reads only tests.
KEPT = ["core/paperpull_core/pressing.py", "core/tests/test_core.py",
        "apps/sample/sample_site.py", "apps/sample/tests/test_sample.py", "gui/app.py",
        "gui/tests/test_gui.py", "server/serve.py", "tools/t.py"]

# Censuses known to walk the repository's Python, so a change that hides
# one from the search below fails here rather than passing on nothing.
KNOWN = {"test_no_app_forces_a_press.sources",
         "test_no_app_presses_through_page_script.sources",
         "test_no_dead_collections.files",
         "test_a_printed_page_goes_back_to_the_screen.python_sources",
         "test_every_app_asks_the_core_whether_a_page_printed.python_files",
         "test_every_fresh_browser_draws_before_an_app_attaches.files_to_read"}


def _walks_for_python(fn: ast.FunctionDef) -> bool:
    """Whether a function walks a folder (rglob, os.walk) for .py files."""
    walks = looks_for_py = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "rglob" or (
                    node.func.attr == "walk" and getattr(node.func.value, "id", "") == "os"):
                walks = True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in ("*.py", ".py"):
            looks_for_py = True
    return walks and looks_for_py


def walkers():
    """(module name, function name, number of arguments) for every module
    level function of a core test module that walks a folder for Python."""
    out = []
    for path in sorted(HERE.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        has_repo = any(isinstance(n, ast.Assign) and any(
            getattr(t, "id", "") == "REPO" for t in n.targets) for n in tree.body)
        for node in tree.body:
            # A test function walks inline and cannot be handed a tree.
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_")                     and _walks_for_python(node):
                args = len(node.args.args) - len(node.args.defaults)
                if args == 0 and not has_repo:
                    continue
                out.append((path.stem, node.name, args))
    return out


WALKERS = walkers()


def test_the_search_finds_every_census_known_to_walk_the_repository():
    found = {"%s.%s" % (m, f) for m, f, _ in WALKERS}
    assert KNOWN <= found, "not found any more, %s" % sorted(KNOWN - found)


@pytest.fixture
def made_up_tree(tmp_path):
    for rel in MADE + KEPT:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("module,name,args", WALKERS, ids=["%s.%s" % w[:2] for w in WALKERS])
def test_no_census_reads_a_copy_a_build_made(module, name, args, made_up_tree, monkeypatch):
    if str(HERE) not in sys.path:
        monkeypatch.syspath_prepend(str(HERE))
    mod = importlib.import_module(module)
    fn = getattr(mod, name)
    if args == 0:
        monkeypatch.setattr(mod, "REPO", made_up_tree)
        found = list(fn())
    else:
        found = [p for top in ("apps", "core", "gui", "server", "tools")
                 for p in fn(made_up_tree / top)]
    rel = sorted({Path(str(p)).resolve().relative_to(made_up_tree.resolve()).as_posix()
                  for p in found})
    assert rel, "%s.%s read nothing in the made-up tree, so this proves nothing" % (module, name)
    assert set(rel) <= set(KEPT), "%s.%s reads what a build or an install made, %s" % (
        module, name, sorted(set(rel) - set(KEPT)))
