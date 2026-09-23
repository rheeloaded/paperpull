"""A list that is created empty, never added to, and then walked anyway.

Robinhood and USAA each carried thirty lines that save the corrected copies
in a tax form set. Neither has ever run. The list of extra links was created
empty at the top of the function and nothing anywhere put a link in it, so
the loop had nothing to walk, every time, since the first commit.

Nothing catches this. It is not an error, no linter minds it, the tests pass
because the code under them does nothing, and a reader sees a feature. The
only way it shows up is somebody asking why a corrected 1099 never arrived,
and the answer would have looked like a provider problem.

So the shape is checked instead: in this repository, a collection that is
set empty and demonstrably never filled must not then be iterated.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".venv", "__pycache__", ".git", "dist", "build", "site-packages",
             "node_modules", ".pytest_cache"}

# Calls that only read. Passing the name to anything else could fill it.
READ_ONLY = {"len", "bool", "any", "all", "print", "str", "repr", "sorted",
             "enumerate", "reversed", "join", "format", "isinstance",
             "info", "debug", "warning", "error", "exception"}
# Calls that hand back the same sequence, so `for x in enumerate(names)`
# still walks `names`.
PASS_THROUGH = ("enumerate", "reversed", "sorted", "list", "tuple", "set")


def files():
    for path in sorted(REPO.rglob("*.py")):
        if set(path.parts) & SKIP_DIRS:
            continue
        yield path


def empty_literal(node) -> bool:
    if isinstance(node, (ast.List, ast.Tuple)) and not node.elts:
        return True
    if isinstance(node, ast.Dict) and not node.keys:
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("list", "dict", "set") and not node.args)


def called(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def unwrap(node):
    while isinstance(node, ast.Call) and node.args and called(node) in PASS_THROUGH:
        node = node.args[0]
    return node


def dead_in(fn) -> list:
    """Names in this function that are set empty, never filled, then walked."""
    made = {}
    for node in ast.walk(fn):
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and empty_literal(value):
            made.setdefault(target.id, node.lineno)
    if not made:
        return []

    filled, walked = set(), {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in made:
            filled.add(node.value.id)                     # .append, .add, .update
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id in made and isinstance(node.ctx, ast.Store):
            filled.add(node.value.id)                     # d[k] = v
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and node.target.id in made:
            filled.add(node.target.id)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in made and not empty_literal(node.value):
            filled.add(node.targets[0].id)                # reassigned to something
        elif isinstance(node, ast.Call) and called(node) not in READ_ONLY:
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, ast.Starred):
                    arg = arg.value
                if isinstance(arg, ast.Name) and arg.id in made:
                    filled.add(arg.id)                    # somebody else may fill it
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) \
                and node is not fn:
            for inner in ast.walk(node):                  # a closure may fill it
                if isinstance(inner, ast.Name) and inner.id in made:
                    filled.add(inner.id)
        elif isinstance(node, (ast.Return, ast.Yield)) \
                and isinstance(node.value, ast.Name) and node.value.id in made:
            filled.add(node.value.id)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            it = unwrap(node.iter)
            if isinstance(it, ast.Name) and it.id in made:
                walked.setdefault(it.id, getattr(node, "lineno", made[it.id]))

    return [(name, made[name], line)
            for name, line in sorted(walked.items()) if name not in filled]


@pytest.mark.parametrize("path", list(files()), ids=lambda p: p.name)
def test_nothing_walks_a_collection_that_is_always_empty(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError as exc:
        pytest.fail("%s does not parse: %s" % (path.relative_to(REPO), exc))
    found = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for name, made, walked in dead_in(fn):
                found.append("%s(): `%s` set empty at line %d, walked at line %d"
                             % (fn.name, name, made, walked))
    assert not found, "%s\n  %s" % (path.relative_to(REPO), "\n  ".join(found))


def test_the_check_still_recognizes_the_shape_it_was_written_for():
    """Robinhood's, as it stood. A check that cannot fail guards nothing."""
    tree = ast.parse(
        "def download_one(self, doc, folder):\n"
        "    extra_hrefs = []\n"
        "    saved = fetch(doc)\n"
        "    for n, href in enumerate(extra_hrefs, start=2):\n"
        "        save(href, n, len(extra_hrefs) + 1)\n")
    fn = tree.body[0]
    assert [n for n, _m, _w in dead_in(fn)] == ["extra_hrefs"]


def test_a_list_something_else_fills_is_left_alone():
    """The same shape, filled by a helper it is handed to, must pass."""
    for body in (
            "    hrefs = []\n    collect(page, hrefs)\n    for h in hrefs: go(h)\n",
            "    hrefs = []\n    hrefs.append(x)\n    for h in hrefs: go(h)\n",
            "    hrefs = []\n    hrefs = scrape(page)\n    for h in hrefs: go(h)\n",
            "    hrefs = []\n\n    def seen(r):\n        hrefs.append(r)\n"
            "    for h in hrefs: go(h)\n"):
        fn = ast.parse("def f(page, x):\n" + body).body[0]
        assert dead_in(fn) == [], body
