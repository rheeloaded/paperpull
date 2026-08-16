"""Filename generation, Windows sanitization, and duplicate numbering."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import build_pdf_filename, sanitize_component, title_case, unique_path


def test_basic_filename():
    assert build_pdf_filename("2024-12-31", "Groceries") == \
        "2024-12-31 Robinhood Groceries Receipt.pdf"


def test_apostrophe_preserved():
    assert build_pdf_filename("2023-04-12", "Children's Clothing") == \
        "2023-04-12 Robinhood Children's Clothing Receipt.pdf"


def test_invoice_document_type():
    assert build_pdf_filename("2024-01-01", "Electronics", "Invoice") == \
        "2024-01-01 Robinhood Electronics Invoice.pdf"


def test_multi_part_filename():
    assert build_pdf_filename("2024-01-01", "Groceries", part=(1, 2)) == \
        "2024-01-01 Robinhood Groceries Receipt (1 of 2).pdf"
    # single-document orders get no part suffix
    assert build_pdf_filename("2024-01-01", "Groceries", part=(1, 1)) == \
        "2024-01-01 Robinhood Groceries Receipt.pdf"


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
    p = unique_path(tmp_path, "2026-07-19 Robinhood Clothing Receipt.pdf")
    assert p.name == "2026-07-19 Robinhood Clothing Receipt.pdf"


def test_unique_path_numbering(tmp_path):
    (tmp_path / "2026-07-19 Robinhood Clothing Receipt.pdf").write_bytes(b"x")
    p2 = unique_path(tmp_path, "2026-07-19 Robinhood Clothing Receipt.pdf")
    assert p2.name == "2026-07-19 Robinhood Clothing Receipt (2).pdf"
    p2.write_bytes(b"x")
    p3 = unique_path(tmp_path, "2026-07-19 Robinhood Clothing Receipt.pdf")
    assert p3.name == "2026-07-19 Robinhood Clothing Receipt (3).pdf"


def test_unique_path_case_insensitive(tmp_path):
    (tmp_path / "2026-07-19 Robinhood CLOTHING RECEIPT.PDF").write_bytes(b"x")
    p = unique_path(tmp_path, "2026-07-19 Robinhood Clothing Receipt.pdf")
    assert p.name == "2026-07-19 Robinhood Clothing Receipt (2).pdf"


def test_unique_path_never_existing(tmp_path):
    for _ in range(5):
        p = unique_path(tmp_path, "r.pdf")
        assert not p.exists()
        p.write_bytes(b"x")


def test_long_path_trimmed(tmp_path):
    p = unique_path(tmp_path, ("Very " * 60) + "Long Receipt.pdf", max_path_length=200)
    assert len(str(p)) <= 200
    assert p.suffix == ".pdf"
