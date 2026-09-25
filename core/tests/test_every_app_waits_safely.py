"""Every app that waits through paperpull_core.ready does it the way that
teaches the maintainer something.

Adopting ready() is per app, one provider's next round at a time, so an
app that has not is not a failure. An app that has and passes no journal
is, because the whole reason for trying several waits is to find out
which one the page needed, and without the journal that answer is thrown
away at the end of the run and the next round is guessed again.

Read from the source with the AST rather than a regex, because a call
broken over three lines is the normal shape and a regex that misses it
passes an app it never looked at.
"""
import ast
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

APPS = sorted(p for p in (REPO / "apps").iterdir()
              if p.is_dir() and not p.name.startswith(("_", ".")))
IDS = [p.name for p in APPS]


def sources(app):
    for path in sorted(app.glob("*.py")):
        yield path, io.open(path, encoding="utf-8", errors="ignore").read()


def _dotted(node):
    """a.b.c for an attribute chain, or "" when it is not one."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def ready_calls(tree):
    """Calls to ready() from paperpull_core.ready, however it was reached.

    from ... import ready, from paperpull_core import ready as a module,
    import paperpull_core.ready as R, and the whole dotted path written
    out. The review found the last two passing unseen."""
    names, modules = set(), {"paperpull_core.ready"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                "paperpull_core.ready"):
            for alias in node.names:
                if alias.name == "ready":
                    names.add(alias.asname or "ready")
        elif isinstance(node, ast.ImportFrom) and node.module == "paperpull_core":
            for alias in node.names:
                if alias.name == "ready":
                    modules.add(alias.asname or "ready")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "paperpull_core.ready" and alias.asname:
                    modules.add(alias.asname)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in names:
            yield node
        elif (isinstance(f, ast.Attribute) and f.attr == "ready"
              and _dotted(f.value) in modules):
            yield node


# What only paperpull_core.ready may build with. Importing any of these is
# the way round the rule that a strategy or an invariant cannot be one of
# the app's own functions.
PRIVATE = {"Strategy", "Invariant", "_strategy", "_invariant", "_BUILDER"}


def test_there_are_apps_to_check():
    assert len(APPS) >= 48


@pytest.mark.parametrize("source", [
    "from paperpull_core.ready import ready as wait_until\n"
    "wait_until(page,\n    [a],\n    invariant=x,\n    budget_ms=1)\n",
    "import paperpull_core.ready as R\nR.ready(page, [a], x, 1)\n",
    "import paperpull_core.ready\npaperpull_core.ready.ready(page, [a], x, 1)\n",
    "from paperpull_core import ready as waits\nwaits.ready(page, [a], x, 1)\n",
])
def test_the_reader_finds_a_call_however_it_was_imported(source):
    """A guard that finds nothing proves nothing, so it is shown one of
    each shape, including the two the review found it missed."""
    assert len(list(ready_calls(ast.parse(source)))) == 1


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_wait_hands_over_the_journal(app):
    for path, text in sources(app):
        for call in ready_calls(ast.parse(text)):
            keywords = {k.arg for k in call.keywords}
            assert "journal" in keywords, (
                "%s:%d waits without a journal, so which guess worked is "
                "never written down" % (path.name, call.lineno))
            assert "name" in keywords, (
                "%s:%d waits without a name, so the journal cannot say "
                "which wait it was" % (path.name, call.lineno))


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_wait_says_what_ready_means_and_how_long_to_try(app):
    for path, text in sources(app):
        for call in ready_calls(ast.parse(text)):
            given = {k.arg for k in call.keywords} | (
                {"invariant"} if len(call.args) >= 3 else set()) | (
                {"budget_ms"} if len(call.args) >= 4 else set())
            assert {"invariant", "budget_ms"} <= given, (
                "%s:%d" % (path.name, call.lineno))


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_no_app_builds_its_own_strategy_or_invariant(app):
    """One made outside the module is where a click or a reload between
    guesses would get in, whether it is imported by name or reached
    through the module."""
    for path, text in sources(app):
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                    node.module or "").endswith("paperpull_core.ready"):
                assert not PRIVATE & {a.name for a in node.names}, path.name
            # The underscored names are this module's own and nothing
            # else's, so reaching one through any alias is the way round.
            if isinstance(node, ast.Attribute) and node.attr in PRIVATE and \
                    node.attr.startswith("_"):
                raise AssertionError("%s:%d reaches into paperpull_core.ready"
                                     % (path.name, node.lineno))


def test_the_private_check_catches_both_ways_in():
    for source in ("from paperpull_core.ready import _invariant\n",
                   "import paperpull_core.ready as R\nR._strategy('x', f, 1)\n"):
        tree = ast.parse(source)
        hit = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and PRIVATE & {
                    a.name for a in node.names}:
                hit = True
            if isinstance(node, ast.Attribute) and node.attr in PRIVATE:
                hit = True
        assert hit, source
