"""Every receipt app shows its own check keeping a receipt and refusing a page.

A receipt app decides whether a saved PDF is the purchase it was saved
under by handing validate_pdf the list expected_tokens_for makes. That
list began with the provider's name, which every page of the provider's
site carries, so the check passed any page at all. On 2026-09-29 a
Walmart order list was kept that way as an online order's invoice.

The name counts for nothing now, and each receipt app has a test that
hands its own _finish_pdf a correct receipt, which it keeps, and a page
naming only the provider, which it puts aside. Measured first on the
receipts the owner had already saved, since a correct receipt refused is
a receipt lost to Manual Review.

An app counts as a receipt app here by what it does, calling
expected_tokens_for, not by its name, so the next one is held to the same.
It needs no browser and no account.
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import receipt_pdf  # noqa: E402

TEST_FILE = "test_a_receipt_names_its_purchase.py"


def token_calls(app: Path):
    """Every call to expected_tokens_for in an app's own code."""
    out = []
    for path in sorted(app.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "expected_tokens_for":
                out.append((path.name, node))
    return out


RECEIPT_APPS = sorted(p for p in (REPO / "apps").iterdir()
                      if p.is_dir() and not p.name.startswith(("_", "."))
                      and token_calls(p))


def test_the_census_finds_the_receipt_apps():
    """The fourteen found on 2026-09-29. One that stops calling it has
    moved its check somewhere else, and this says so rather than letting
    it drop out of the guard quietly."""
    found = {p.name for p in RECEIPT_APPS}
    assert found >= {"amazon", "apple", "bestbuy", "costco", "ebay", "gap", "github",
                     "homedepot", "kroger", "lowes", "meijer", "target", "uber",
                     "walmart"}, sorted(found)


@pytest.mark.parametrize("app", RECEIPT_APPS, ids=[p.name for p in RECEIPT_APPS])
def test_every_call_is_one_the_core_accepts(app):
    params = inspect.signature(receipt_pdf.expected_tokens_for).parameters
    for filename, call in token_calls(app):
        where = "%s/%s line %d" % (app.name, filename, call.lineno)
        assert len(call.args) <= 1, where
        for kw in call.keywords:
            assert kw.arg in params and kw.arg != "purchase", where


@pytest.mark.parametrize("app", RECEIPT_APPS, ids=[p.name for p in RECEIPT_APPS])
def test_every_receipt_app_shows_its_check_both_ways(app):
    test = app / "tests" / TEST_FILE
    assert test.is_file(), "%s has no %s" % (app.name, TEST_FILE)
    source = test.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tests = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    drives = [n for n in tests if "file_a_receipt(" in ast.get_source_segment(source, n)]
    kept = [n for n in drives if "assert filed.kept" in ast.get_source_segment(source, n)]
    refused = [n for n in drives if "assert not filed.kept" in ast.get_source_segment(source, n)]
    assert kept, "%s keeps no correct receipt in its test" % app.name
    assert refused, "%s refuses no page in its test" % app.name
