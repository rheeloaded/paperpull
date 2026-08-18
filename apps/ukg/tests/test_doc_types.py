"""UKG document classification: a 'statement' here means a pay statement."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds UKG's AppSpec (the rules file is found through it)
from paperpull_core import doc_types

RULES = doc_types.load_rules()


@pytest.mark.parametrize("title,summary", [
    ("Pay Statement 08/15/2026", "Pay Statement"),
    ("Earnings Statement - August 2026", "Pay Statement"),
    ("Paystub 08/15/2026", "Pay Statement"),
    ("Pay Stub", "Pay Statement"),
    ("Payslip August", "Pay Statement"),
    ("Direct Deposit Advice", "Pay Statement"),
])
def test_pay_documents_classify_as_statements(title, summary):
    cat, got, conf = doc_types.classify_document(title, RULES)
    assert cat == doc_types.STATEMENT, title
    assert got == summary, (title, got)


@pytest.mark.parametrize("title,summary", [
    ("W-2 2025", "W-2 Tax Form"),
    ("W-2c Corrected 2024", "W-2c Corrected Tax Form"),
    ("1095-C 2025", "1095 Health Coverage Form"),
    ("1099-NEC 2025", "1099-NEC Tax Form"),
])
def test_payroll_tax_forms(title, summary):
    cat, got, conf = doc_types.classify_document(title, RULES)
    assert cat == doc_types.TAX, title
    assert got == summary, (title, got)


def test_noise_is_skipped():
    for title in ("Marketing Update", "Company Newsletter", "Privacy Notice"):
        assert doc_types.should_skip(title, RULES), title
    assert not doc_types.should_skip("Pay Statement 08/15/2026", RULES)


def test_only_configured_categories_are_wanted():
    cfg = {"document_types": ["Statement", "Tax Document"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_a_pay_statement_routes_to_the_pay_folder(tmp_path):
    """The classifier speaks in categories; the folder carries the payroll
    wording. This is the join between the two."""
    cat, _, _ = doc_types.classify_document("Pay Statement 08/15/2026", RULES)
    assert storage.Paths(tmp_path).folder_for(cat).name == "Pay Statements"
