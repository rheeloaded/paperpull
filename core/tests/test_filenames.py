"""Filename generation, Windows sanitization, and duplicate numbering."""
import sys
from pathlib import Path

import pytest


from paperpull_core.storage import (build_pdf_filename, sanitize_component,
                                    title_case, unique_path)


def test_basic_filename():
    assert build_pdf_filename("2024-12-31", "Groceries") == \
        "2024-12-31 Testco Groceries Receipt.pdf"


def test_apostrophe_preserved():
    assert build_pdf_filename("2023-04-12", "Children's Clothing") == \
        "2023-04-12 Testco Children's Clothing Receipt.pdf"


def test_invoice_document_type():
    assert build_pdf_filename("2024-01-01", "Electronics", "Invoice") == \
        "2024-01-01 Testco Electronics Invoice.pdf"


def test_multi_part_filename():
    assert build_pdf_filename("2024-01-01", "Groceries", part=(1, 2)) == \
        "2024-01-01 Testco Groceries Receipt (1 of 2).pdf"
    # single-document orders get no part suffix
    assert build_pdf_filename("2024-01-01", "Groceries", part=(1, 1)) == \
        "2024-01-01 Testco Groceries Receipt.pdf"


def test_title_case():
    assert title_case("groceries and household") == "Groceries and Household"
    assert title_case("children's clothing") == "Children's Clothing"
    assert title_case("school and office supplies") == "School and Office Supplies"


def test_sanitize_removes_forbidden_chars():
    assert sanitize_component('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"


def test_sanitize_control_chars_and_spaces():
    assert sanitize_component("  a\x00b\x1fc  ") == "abc"


def test_sanitize_trailing_dots_and_spaces():
    assert sanitize_component("Receipt. . .") == "Receipt"
    assert not sanitize_component("x. ").endswith((" ", "."))


def test_sanitize_empty_and_reserved():
    assert sanitize_component("") == "Unnamed"
    assert sanitize_component("???") == "Unnamed"
    assert sanitize_component("CON") != "CON"
    assert sanitize_component("aux") .upper() != "AUX"


def test_sanitize_length_cap():
    assert len(sanitize_component("x" * 500, max_len=120)) <= 120


def test_unique_path_no_collision(tmp_path):
    p = unique_path(tmp_path, "2026-07-19 Testco Clothing Receipt.pdf")
    assert p.name == "2026-07-19 Testco Clothing Receipt.pdf"


def test_unique_path_numbering(tmp_path):
    (tmp_path / "2026-07-19 Testco Clothing Receipt.pdf").write_bytes(b"x")
    p2 = unique_path(tmp_path, "2026-07-19 Testco Clothing Receipt.pdf")
    assert p2.name == "2026-07-19 Testco Clothing Receipt (2).pdf"
    p2.write_bytes(b"x")
    p3 = unique_path(tmp_path, "2026-07-19 Testco Clothing Receipt.pdf")
    assert p3.name == "2026-07-19 Testco Clothing Receipt (3).pdf"


def test_unique_path_case_insensitive(tmp_path):
    (tmp_path / "2026-07-19 Testco CLOTHING RECEIPT.PDF").write_bytes(b"x")
    p = unique_path(tmp_path, "2026-07-19 Testco Clothing Receipt.pdf")
    assert p.name == "2026-07-19 Testco Clothing Receipt (2).pdf"


def test_unique_path_never_existing(tmp_path):
    for _ in range(5):
        p = unique_path(tmp_path, "r.pdf")
        assert not p.exists()
        p.write_bytes(b"x")


def test_long_path_trimmed(tmp_path):
    p = unique_path(tmp_path, ("Very " * 60) + "Long Receipt.pdf", max_path_length=200)
    assert len(str(p)) <= 200
    assert p.suffix == ".pdf"


# -- filing into awkward folders --------------------------------------------

def test_an_empty_name_does_not_resolve_to_the_folder_itself(tmp_path):
    """"dir / ''" is just "dir", so an empty name handed the caller its own
    output folder to write a PDF over. Reachable whenever a scraped title
    sanitises away to nothing."""
    got = unique_path(tmp_path, "", max_path_length=240)
    assert got != tmp_path
    assert got.parent == tmp_path
    assert got.suffix == ".pdf"


def test_a_folder_too_deep_to_file_into_says_so(tmp_path):
    """It used to return a path longer than the limit it was given, and the
    failure then surfaced as an unexplained OS error at the write."""
    deep = tmp_path
    while len(str(deep)) < 250:
        deep = deep / "a-reasonably-long-folder-name"
    deep.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError) as e:
        unique_path(deep, "2026-08-18 Statement.pdf", max_path_length=240)
    assert "too deep" in str(e.value)
    assert "max_path_length" in str(e.value), "the message must say what to change"


def test_a_returned_path_always_respects_the_limit(tmp_path):
    """Including once collision suffixes start being added."""
    folder = tmp_path / ("d" * 60)
    folder.mkdir()
    limit = len(str(folder)) + 40
    for _ in range(6):
        p = unique_path(folder, "A Very Long Statement Name Indeed.pdf",
                                max_path_length=limit)
        assert len(str(p)) <= limit, "%d > %d for %s" % (len(str(p)), limit, p.name)
        p.write_bytes(b"x")


def test_collision_suffixes_stay_unique_even_when_truncated(tmp_path):
    folder = tmp_path / ("d" * 60)
    folder.mkdir()
    limit = len(str(folder)) + 40
    names = []
    for _ in range(5):
        p = unique_path(folder, "A Very Long Statement Name Indeed.pdf",
                                max_path_length=limit)
        p.write_bytes(b"x")
        names.append(p.name)
    assert len(set(names)) == len(names), names
