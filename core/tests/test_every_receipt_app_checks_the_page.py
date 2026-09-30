"""Every receipt app that prints a page reads it first, to see whose it is.

The check on a saved file asks whether the file names the purchase, and a
page can name a purchase without being its receipt. The order list names
every purchase on it, GitHub's payment history names each payment's date,
amount and id, and a wrong page read first writes its own facts into the
purchase. On 2026-09-29 each of those, printed in a purchase's place, was
kept as the purchase's receipt in a browser run of the app itself.

So an app that prints a page checks it before printing, the way Best Buy
reads the number on its details page (details_number) or through the
page_check the other apps share (not_this_purchase). Here an app counts by
what it does. It is a receipt app when it calls expected_tokens_for, and it
prints a page when a method of its own calls _capture_document or one of
receipt_pdf's print functions. Each such method has to call a page check
before it prints, or be called only from places that already have. A
method nothing calls is left alone, and so are _capture_document and
_finish_pdf, which print the page they are handed.

It needs no browser and no account.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

PRINTS = {"_capture_document", "print_page_to_pdf", "print_html_to_pdf", "print_frame_to_pdf"}
CHECKS = {"not_this_purchase", "details_number"}
HANDED_A_PAGE = {"_capture_document", "_finish_pdf"}

# Apps that check what they print another way, and how.
OTHER_WAYS = {
    "apple": "every receipt goes through delivery.render, which checks the printed "
             "receipt's own number and refuses by default",
}

# Receipt apps that print a page and do not yet read it first. Named here so
# that a run says so, rather than letting them pass quietly.
LEFT = {
    "costco": "checks date and total in delivery.render only when refuse_wrong_documents is set",
    "ebay": "reopens the order when the address lacks its number, and checks nothing after",
    "kroger": "reopens the order when the address lacks its number, and checks nothing after",
}


def _called(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _calls(fn, names):
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and _called(n) in names]


def app_modules(app: Path):
    out = []
    for path in sorted(app.glob("*.py")):
        try:
            out.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
    return out


def is_receipt_app(app: Path) -> bool:
    return any(_calls(tree, {"expected_tokens_for"}) for _, tree in app_modules(app))


def printers(app: Path):
    """(module, method, first print line, check lines) for every method of
    the app's own that prints a page. _capture_document counts as printing
    only where it does, since Uber's places the provider's own PDF."""
    out = []
    for path, tree in app_modules(app):
        capture = [fn for fn in ast.walk(tree)
                   if isinstance(fn, ast.FunctionDef) and fn.name == "_capture_document"]
        prints_via = PRINTS if any(_calls(fn, PRINTS) for fn in capture) \
            else PRINTS - {"_capture_document"}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef) or fn.name in HANDED_A_PAGE:
                continue
            prints = _calls(fn, prints_via)
            if prints:
                out.append((path, tree, fn, min(prints), _calls(fn, CHECKS)))
    return out


def unchecked(app: Path):
    """The methods that print a page with no check before it, in the method
    or at every place the method is called from."""
    missing = []
    for path, tree, fn, first_print, checks in printers(app):
        if any(line < first_print for line in checks):
            continue
        callers = [(caller, [n.lineno for n in ast.walk(caller)
                             if isinstance(n, ast.Call) and _called(n) == fn.name])
                   for caller in ast.walk(tree) if isinstance(caller, ast.FunctionDef)]
        callers = [(c, lines) for c, lines in callers if lines]
        if not callers:
            continue    # nothing calls it
        for caller, lines in callers:
            before = _calls(caller, CHECKS)
            if not all(any(check < line for check in before) for line in lines):
                missing.append("%s %s, called from %s" % (path.name, fn.name, caller.name))
    return missing


APPS = sorted(p for p in (REPO / "apps").iterdir()
              if p.is_dir() and not p.name.startswith(("_", ".")))
PRINTING = [p for p in APPS if is_receipt_app(p) and printers(p)]


def test_the_census_finds_the_receipt_apps_that_print_a_page():
    """The thirteen found on 2026-09-29. One that stops printing a page has
    moved its capture somewhere else, and this says so rather than letting
    it drop out of the guard quietly."""
    found = {p.name for p in PRINTING}
    assert found >= {"amazon", "apple", "bestbuy", "costco", "ebay", "gap", "github",
                     "homedepot", "kroger", "lowes", "meijer", "target", "walmart"}, sorted(found)


@pytest.mark.parametrize("app", PRINTING, ids=[p.name for p in PRINTING])
def test_a_page_is_read_before_it_is_printed(app):
    if app.name in OTHER_WAYS:
        pytest.skip("%s: %s" % (app.name, OTHER_WAYS[app.name]))
    if app.name in LEFT:
        pytest.skip("%s does not read its page yet: %s" % (app.name, LEFT[app.name]))
    assert unchecked(app) == [], "%s prints a page it never read" % app.name


def test_the_apps_left_are_still_the_ones_without_a_check():
    """An app taken off the list has to be held to the check, and one that
    gains a check comes off the list."""
    by_name = {p.name: p for p in PRINTING}
    for name in LEFT:
        assert name in by_name, "%s no longer prints a page" % name
        assert unchecked(by_name[name]), "%s reads its page now, take it off LEFT" % name
