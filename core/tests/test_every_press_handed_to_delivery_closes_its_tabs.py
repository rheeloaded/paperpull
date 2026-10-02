"""Every press an app hands to the core's delivery asks for its tabs closed.

Delivery arms every way a document can arrive before it fires the press,
a new tab among them. It reads a tab at the provider's own address and
turns any other away, and it closes the tabs the press opened only when
the request asks it to, which is off by default. Navy Federal and Fairfax
Water asked. Target RedCard and T-Mobile did not, so a tab their press
opened stayed open in the person's browser, one per document, whether it
was read or turned away (2026-10-01).

So every DocumentRequest an app builds with a press asks. An app that
someday works on in the tab its press opened is named in KEEPS_ITS_TABS
with its reason. Read from the source, so no browser and no account.
"""
import ast
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(p for p in (REPO / "apps").iterdir()
              if p.is_dir() and not p.name.startswith(("_", ".")))
IDS = [p.name for p in APPS]

# An app whose run carries on in the tab its press opens, and why. None does.
KEEPS_ITS_TABS: dict = {}

# DocumentRequest's fields in order, for a request built positionally.
FIELDS = ("trigger", "url", "expect", "rivals", "while_waiting",
          "close_new_tabs", "hints")


def presses(tree):
    """Every DocumentRequest built with a press, as (line, closes its tabs)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name != "DocumentRequest":
            continue
        given = dict(zip(FIELDS, node.args))
        given.update((k.arg, k.value) for k in node.keywords if k.arg)
        trigger = given.get("trigger")
        if trigger is None or (isinstance(trigger, ast.Constant) and trigger.value is None):
            continue
        closes = given.get("close_new_tabs")
        yield node.lineno, isinstance(closes, ast.Constant) and closes.value is True


def test_the_reader_finds_a_press_that_leaves_its_tabs():
    tree = ast.parse("from paperpull_core.delivery import DocumentRequest\n"
                     "a = DocumentRequest(trigger=link.click, hints=(DOWNLOAD,))\n"
                     "b = delivery.DocumentRequest(lambda: btn.click(), close_new_tabs=True)\n"
                     "c = DocumentRequest(url=href)\n"
                     "d = DocumentRequest(trigger=None)\n")
    assert sorted(presses(tree)) == [(2, False), (3, True)]


def test_presses_are_found_at_all():
    found = [line for app in APPS for path in sorted(app.glob("*.py"))
             for line, _ in presses(ast.parse(io.open(path, encoding="utf-8",
                                                      errors="ignore").read()))]
    assert len(found) >= 4, "the apps hand delivery at least four presses"


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_press_asks_for_the_tabs_it_opens_to_be_closed(app):
    if app.name in KEEPS_ITS_TABS:
        pytest.skip(KEEPS_ITS_TABS[app.name])
    for path in sorted(app.glob("*.py")):
        text = io.open(path, encoding="utf-8", errors="ignore").read()
        for line, closes in presses(ast.parse(text)):
            assert closes, (
                "%s:%d hands delivery a press without close_new_tabs=True, so a tab "
                "it opens stays open in the person's browser" % (path.relative_to(REPO), line))
