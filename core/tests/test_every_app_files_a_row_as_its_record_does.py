"""A row of the list is read as its record is, by every app that re-files one.

DKB's _record_statement_doc records an Other Document whose title says
Kontoauszug or statement as a Statement, and its site's filed_category
applies the same rule, since Discover numbers the rows by it and a
download finds its row by it. 1822direkt and Renault Bank direkt were built
from DKB with the rule in their docs module and not in filed_category. A
row 1822direkt's bank tags ADV (an Other Document) titled Kontoauszug was
recorded as a Statement and looked for as an Other Document, so it failed
on every run and was never saved.

So every app whose docs module re-files an Other Document by its title,
and reads a row's category through site.filed_category, is asked the same
question. Is a row of that category filed as its record is, for titles the
rule takes and titles it does not? The rule is read from the docs module
itself (its pattern and its flags), so a rule that changes in one place
and not the other fails here.

What this cannot see. An app that re-files by its title and matches rows by
a category it reads some other way than filed_category. None does today.
"""
import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

from paperpull_core import doc_types

REPO = Path(__file__).resolve().parents[2]

TITLES = ("Kontoauszug 3/2031", "KONTOAUSZUG Nr. 4", "Monthly statement", "Statement of account",
          "Information zum Konto", "Kontoauszüge", "Steuerbescheinigung 2030", "")


def docs_of(app: Path):
    found = sorted(app.glob("*_docs.py"))
    return found[0] if found else None


def _attr(node, owner: str):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == owner:
        return node.attr
    return None


def refiling(tree):
    """The pattern and flags of the docs module's rule that re-files an
    Other Document by its title as a Statement, or None. The rule is an if
    whose test asks category == doc_types.OTHER and re.search(pattern,
    title, flags), and whose body sets category to doc_types.STATEMENT."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.BoolOp):
            continue
        parts = node.test.values
        other = any(isinstance(p, ast.Compare) and _attr(p.comparators[0], "doc_types") == "OTHER"
                    for p in parts)
        search = [p for p in parts if isinstance(p, ast.Call) and _attr(p.func, "re") == "search"]
        sets = any(isinstance(s, ast.Assign) and _attr(s.value, "doc_types") == "STATEMENT"
                   for s in node.body)
        if other and search and sets:
            call = search[0]
            pattern = ast.literal_eval(call.args[0])
            flags = 0
            for f in call.args[2:3]:
                for name in re.findall(r"re\.(\w+)", ast.unparse(f)):
                    flags |= getattr(re, name)
            return pattern, flags
    return None


def reads_rows_by_filed_category(tree) -> bool:
    return any(_attr(n, "site") == "filed_category" for n in ast.walk(tree))


def selected():
    out = []
    for app in sorted((REPO / "apps").iterdir()):
        docs = docs_of(app) if app.is_dir() else None
        if docs is None:
            continue
        tree = ast.parse(docs.read_text(encoding="utf-8-sig"))
        rule = refiling(tree)
        if rule and reads_rows_by_filed_category(tree):
            out.append((app, rule))
    return out


APPS = selected()
IDS = [app.name for app, _rule in APPS]


def site_of(app: Path):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def disagreements(rule, filed_category) -> list:
    """Each row filed otherwise than its record, as (category, title, what
    the record holds, what filed_category answers). The record keeps a row's
    own category, but for an Other Document whose title the rule takes."""
    pattern, flags = rule
    out = []
    for category in (doc_types.OTHER, doc_types.STATEMENT, doc_types.TAX, "Message"):
        for title in TITLES:
            recorded = (doc_types.STATEMENT if category == doc_types.OTHER
                        and re.search(pattern, title or "Statement", flags) else category)
            row = {"title": title, "category": category, "date": "2031-04-02", "account": "",
                   "item_id": "invented", "kind": ""}
            filed = filed_category(row)
            if filed != recorded:
                out.append((category, title, recorded, filed))
    return out


def test_the_apps_that_re_file_a_row_are_read():
    """Not vacuous. DKB, ING, Renault Bank direkt and 1822direkt carry the
    rule today."""
    assert {"dkb", "ing", "renaultbank", "direkt1822"} <= set(IDS), IDS


@pytest.mark.parametrize("app,rule", APPS, ids=IDS)
def test_a_row_is_filed_as_its_record_is(app, rule):
    site = site_of(app)
    found = disagreements(rule, site.filed_category)
    assert not found, (
        "%s's docs module re-files an Other Document by its title, and its "
        "site's filed_category does not, so a download looks for that row "
        "under another kind than its record and never finds it: %s" % (app.name, found))


def test_the_census_finds_a_filed_category_that_keeps_the_rows_kind():
    keeps = lambda row: row["category"]  # noqa: E731
    found = disagreements((r"statement|kontoauszug", re.I), keeps)
    assert ("Other Document", "Kontoauszug 3/2031", "Statement", "Other Document") in found
    assert all(category == doc_types.OTHER for category, *_rest in found)


def test_the_census_reads_the_rule_from_the_code():
    tree = ast.parse(
        "def record(d, title):\n"
        "    if category == doc_types.OTHER and re.search(r'statement|kontoauszug', title, re.I):\n"
        "        category = doc_types.STATEMENT\n"
        "    return site.filed_category(d)\n")
    assert refiling(tree) == ("statement|kontoauszug", re.I)
    assert reads_rows_by_filed_category(tree)
    assert refiling(ast.parse("if category == doc_types.OTHER:\n    category = 1\n")) is None
