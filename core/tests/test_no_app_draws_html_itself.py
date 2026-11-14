"""No app draws HTML in a browser by itself. The core does, inertly.

Anthem drew a secure message's body with page.set_content in a page of the
signed-in context with JavaScript on (a private report of 2026-11-10). It
draws through receipt_pdf.inert_pdf_bytes now, and this holds every app to
that. Only the core may put HTML of its own into a page, set_content, the
DevTools call behind it, a data: address or an answer made up for a
request, since those are the ways a page of the app's own making comes to
be drawn.

The core's print_html_to_pdf draws a print snapshot, the provider's own
page as its print dialog would print it, in a tab of the signed-in context
with its styles, so it is kept to the apps that use it today. A new one is
a decision to make, and the inert drawing is the one to reach for first.
"""
import ast
import os
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# Never into a virtual environment a checkout keeps beside an app's code.
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules"}


def _sources():
    for top, dirs, files in os.walk(REPO / "apps"):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(top) / name


SOURCES = list(_sources())

# The apps that print the provider's own page through print_html_to_pdf,
# and how many places in each. Reviewed 2026-11-14.
PRINTS_A_SNAPSHOT = {
    "affirm/affirm_site.py": 1, "amazon/amazon_receipts.py": 1,
    "apple/apple_receipts.py": 2, "bestbuy/bestbuy_receipts.py": 1,
    "costco/costco_receipts.py": 1, "ebay/ebay_receipts.py": 1, "gap/gap_receipts.py": 1,
    "github/github_receipts.py": 1, "homedepot/homedepot_receipts.py": 1,
    "kroger/kroger_receipts.py": 1, "lowes/lowes_receipts.py": 1,
    "meijer/meijer_receipts.py": 1, "netbenefits/netbenefits_site.py": 1,
    "target/target_receipts.py": 1, "walmart/walmart_receipts.py": 1,
}


def _calls(tree, name):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name]


def _is_data_address(node) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip().lower().startswith("data:")
    if isinstance(node, ast.JoinedStr) and node.values:
        return _is_data_address(node.values[0])
    return False


def test_there_are_apps_to_look_at():
    assert len(SOURCES) > 200


def test_no_app_puts_html_of_its_own_into_a_page():
    found = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        where = path.relative_to(REPO / "apps").as_posix()
        for call in _calls(tree, "set_content") + _calls(tree, "fulfill"):
            found.append("%s:%d %s" % (where, call.lineno, call.func.attr))
        for call in _calls(tree, "goto"):
            if call.args and _is_data_address(call.args[0]):
                found.append("%s:%d goto data:" % (where, call.lineno))
        if "setDocumentContent" in text:
            found.append("%s Page.setDocumentContent" % where)
    assert not found, found


def test_only_the_apps_that_print_a_snapshot_use_the_drawing_that_is_not_inert():
    used = Counter()
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        n = len(_calls(tree, "print_html_to_pdf"))
        if n:
            used[path.relative_to(REPO / "apps").as_posix()] = n
    assert dict(used) == PRINTS_A_SNAPSHOT
    assert not any(k.startswith("anthem/") for k in used)
