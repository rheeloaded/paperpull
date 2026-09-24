"""A dropdown is filtered before it is touched, in every app.

The first live probe of the Ally app landed on the dashboard rather than
the statements page, and its account-picker lookup matched a money TRANSFER
widget's <select> and set it. That is where safe_selects came from, and four
apps use it.

Three did not. Navy Federal walked every dropdown on the page and took the
first one whose options looked like years. Target and Wealthfront walked
every dropdown and took the first one carrying a matching option text. All
three then called select_option on whatever that turned out to be.

The find is not the point on its own, since a transfer widget rarely lists
years. The point is that these apps pick a control out of a page they have
not confirmed and set it, which is the exact thing the filter exists to
stop, and being right about a page most of the time is what a first probe
is worst at.

So a sweep of every dropdown has to go through the filter, and this says
which sweeps do not.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())

# Reading what is there is fine. These are the calls that CHANGE a control.
SETTERS = {"select_option", "check", "uncheck", "set_checked", "fill"}
# Names that mean the filter has already been applied.
FILTERED = ("safe_selects", "_safe_selects", "describe_selects",
            "is_money_control", "is_forbidden_context")


def sweeps(tree):
    """Every `page.locator("select")` and `page.query_selector_all("select")`,
    with the function it sits in."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def holder(node):
        while node is not None and not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node = parents.get(node)
        return node

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in ("locator", "query_selector_all"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        if node.args[0].value.strip() != "select":
            continue
        yield node, holder(node)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_sweep_of_every_dropdown_goes_through_the_filter(app):
    path = app / ("%s_site.py" % app.name)
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    loose = []
    for node, fn in sweeps(tree):
        if fn is None:
            loose.append("line %d, outside any function" % node.lineno)
            continue
        body = ast.unparse(fn)
        if any(name in fn.name for name in ("safe_select", "describe_select")):
            continue                       # this IS the filter
        if any(name in body for name in FILTERED):
            continue
        sets = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr in SETTERS for n in ast.walk(fn))
        # Handing the control back counts too. Navy Federal's lookup picks one
        # and returns it, and the caller is what sets it, which is the same
        # dropdown chosen the same way with the check in neither place.
        hands_it_out = any(
            isinstance(n, (ast.Return, ast.Yield)) and n.value is not None
            and not (isinstance(n.value, ast.Constant) and n.value.value in (None, ""))
            for n in ast.walk(fn))
        if not (sets or hands_it_out):
            continue                       # reads only, changes nothing
        loose.append("%s(), line %d" % (fn.name, node.lineno))
    assert not loose, (
        "%s walks every dropdown on the page and sets one, with nothing "
        "deciding which may be touched: %s" % (app.name, "; ".join(loose)))


def test_the_filter_refuses_a_money_widget_and_keeps_a_year_picker():
    """The filter itself, since everything above is only as good as it is."""
    from paperpull_core.controls import is_forbidden_context
    import re
    blocklist = re.compile(r"(transfer|pay\b|payment|zelle|wire\b)", re.I)
    for identity in ("fromAccount | Pay from | Make a payment",
                     "transferTo | To | Balance transfer",
                     "amount | Amount | Payment"):
        assert is_forbidden_context(identity, blocklist), identity
    for identity in ("statementPeriod | Statement period | Statements",
                     "documentYear | Year | Statements & documents",
                     "taxYear | Tax year | Tax forms"):
        assert not is_forbidden_context(identity, blocklist), identity


def test_a_dropdown_nobody_can_read_is_refused():
    """An empty identity means the page would not say what the control is,
    and a control that will not identify itself is not set."""
    from paperpull_core.controls import is_forbidden_context
    import re
    assert is_forbidden_context("", re.compile(r"transfer", re.I))
