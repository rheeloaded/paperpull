"""Two documents on one day do not differ by " (2)".

The same complaint arrived twice, on #43 and then #49. Two things on one
date produced one filename and the second got " (2)" added. The objection
is not that it is ugly. It is that it says nothing about which document it
is, and it is not stable: delete the first file and the next run gives that
name to the other one, so the archive's filenames are not identities.

The receipt apps answer with the order number. The document apps passed
nothing, so they still got " (2)", and four of them had built their own
version of this by hand, each gated on detecting an ambiguous pair.

unique_path already uses a distinguisher ONLY when the name it would
otherwise write is taken, so handing it the document id needs no detection
and changes nothing for a document whose name is free. That last part is
what these check, in both directions.
"""
import ast
from pathlib import Path

import pytest

from paperpull_core.storage import unique_path

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))


def offers_an_id(app: Path) -> bool:
    """An app whose documents carry an id it could name them by."""
    return "self.document_id" in entry_of(app).read_text(
        encoding="utf-8", errors="ignore")


# -- the mechanism, before asking whether the apps use it ----------------------

def test_a_free_name_is_unchanged_by_offering_a_distinguisher(tmp_path):
    """The reason this is safe to add to thirty-eight apps at once."""
    plain = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240)
    with_id = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240,
                          distinguisher="a1b2c3")
    assert plain.name == with_id.name == "2026-03-31 Statement.pdf"


def test_a_taken_name_gets_the_id_rather_than_a_number(tmp_path):
    (tmp_path / "2026-03-31 Statement.pdf").write_bytes(b"%PDF-1.7")
    got = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240,
                      distinguisher="a1b2c3")
    assert "a1b2c3" in got.name
    assert "(2)" not in got.name


def test_two_documents_of_one_day_get_two_names(tmp_path):
    """The case from the reports, played out."""
    first = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240,
                        distinguisher="aaaaaa")
    first.write_bytes(b"%PDF-1.7")
    second = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240,
                         distinguisher="bbbbbb")
    second.write_bytes(b"%PDF-1.7")
    assert first.name != second.name
    assert "bbbbbb" in second.name


def test_no_id_still_falls_back_to_a_number(tmp_path):
    """An app with nothing to offer must still not overwrite."""
    (tmp_path / "2026-03-31 Statement.pdf").write_bytes(b"%PDF-1.7")
    got = unique_path(tmp_path, "2026-03-31 Statement.pdf", 240, distinguisher="")
    assert got.name == "2026-03-31 Statement (2).pdf"


# -- and that the apps hand it over --------------------------------------------

@pytest.mark.parametrize("app", [d for d in APPS if offers_an_id(d)],
                         ids=lambda d: d.name)
def test_this_app_names_a_second_document_by_its_id(app):
    src = entry_of(app).read_text(encoding="utf-8", errors="ignore")
    assert "distinguisher=" in src, (
        "%s carries a document id and does not offer it, so two documents "
        "on one day differ by ' (2)'" % app.name)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_whatever_is_offered_is_something_the_document_knows(app):
    """A distinguisher built from anything but the document itself would be
    as unstable as the number it replaces."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "distinguisher":
                continue
            text = ast.unparse(kw.value)
            assert any(w in text for w in
                       ("document_id", "order_number", "doc.", "purchase.",
                        "payment_id", "item_id")), \
                "%s names a file by %s, which the document does not carry" % (
                    app.name, text)


def test_there_are_apps_with_an_id_to_check():
    """This collected nobody once, on a different check, and the failure
    mode was silence."""
    assert len([d for d in APPS if offers_an_id(d)]) >= 30
