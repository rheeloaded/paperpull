"""Every button in the panel is a flag every app understands.

The panel has one table of actions and sends the same flags to all
forty-eight apps. An app whose parser has never heard of one answers with
argparse's usage message and exit code 2, which reaches the person as a
button that does nothing on that provider and works everywhere else.

Adding a button is a one-line change in the panel. Adding the flag is a
change in forty-eight files, and nothing said so. That is the shape of
this, rather than any bug present today: asked directly, all forty-eight
parsers accept all twelve flags right now.

The panel's table is read out of its source with ast rather than by
importing it, so this suite needs none of the panel's dependencies.
"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(".")
              and (next(iter(d.glob("*_docs.py")), None)
                   or next(iter(d.glob("*_receipts.py")), None)))

# Flags the panel adds itself, outside the actions table.
ALWAYS = {"--year", "--start-date", "--end-date", "--config", "--yes"}


def panel_flags() -> set:
    tree = ast.parse((REPO / "gui" / "app.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ACTIONS" for t in node.targets):
            actions = ast.literal_eval(node.value)
            break
    else:
        pytest.fail("the panel no longer has an ACTIONS table to read")
    out = set(ALWAYS)
    for action in actions.values():
        for flag in action.get("flags", []):
            if flag != "__LOGIN__":      # resolved per app, checked below
                out.add(flag)
    return out


def parser_for(app_dir: Path):
    entry = (next(iter(app_dir.glob("*_docs.py")), None)
             or next(iter(app_dir.glob("*_receipts.py")), None))
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app_dir))
    try:
        mod = importlib.import_module(entry.stem)
    finally:
        sys.path.pop(0)
    return mod.build_parser()


def options(parser) -> set:
    return {s for action in parser._actions for s in action.option_strings}


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_understands_every_flag_the_panel_sends(app):
    missing = sorted(panel_flags() - options(parser_for(app)))
    assert not missing, (
        "%s would answer the panel's buttons with a usage message: %s"
        % (app.name, " ".join(missing)))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_has_the_sign_in_flag_the_panel_will_pick(app):
    """Login is the one action whose flag differs. The panel reads it off
    the entry script, and whichever it finds has to exist."""
    entry = (next(iter(app.glob("*_docs.py")), None)
             or next(iter(app.glob("*_receipts.py")), None))
    src = entry.read_text(encoding="utf-8", errors="ignore")
    chosen = "--open-browser" if "--open-browser" in src else "--login"
    assert chosen in options(parser_for(app)), \
        "%s has no %s, so the panel's Login button cannot work" % (app.name, chosen)


def test_the_table_is_still_where_this_reads_it_from():
    """If the panel stops declaring its actions this way, the checks above
    would quietly pass on an empty set."""
    flags = panel_flags()
    assert len(flags) >= 10
    for expected in ("--pilot", "--all", "--resume", "--discover", "--config"):
        assert expected in flags
