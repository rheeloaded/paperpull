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


def ready_calls(tree):
    """Calls to ready() imported from paperpull_core.ready, by any name."""
    names, modules = set(), set()
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
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in names:
            yield node
        elif (isinstance(f, ast.Attribute) and f.attr == "ready"
              and isinstance(f.value, ast.Name) and f.value.id in modules):
            yield node


def test_there_are_apps_to_check():
    assert len(APPS) >= 48


def test_the_reader_finds_a_call_it_is_shown():
    """A guard that finds nothing proves nothing, so it is shown one."""
    tree = ast.parse(
        "from paperpull_core.ready import ready as wait_until\n"
        "wait_until(page,\n    [a],\n    invariant=x,\n    budget_ms=1)\n")
    assert len(list(ready_calls(tree))) == 1


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
def test_no_app_builds_its_own_strategy(app):
    """A strategy made outside the module is where a click or a reload
    between guesses would get in."""
    for path, text in sources(app):
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                    node.module or "").endswith("paperpull_core.ready"):
                assert "Strategy" not in {a.name for a in node.names}, \
                    path.name
