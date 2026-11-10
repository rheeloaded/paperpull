import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from pathlib import Path
import pytest
from paperpull_core import doc_types
import amexbanking_site as site
from storage import SPEC


@pytest.fixture
def rules():
    return doc_types.load_rules(SPEC.project_dir / "document_rules.json")


def test_classify_business_checking_statement(rules):
    cat, summary, conf = doc_types.classify_document("American Express Business Checking Statement", rules)
    assert cat == "Statement"
    assert "Business Checking Statement" in summary


def test_classify_monthly_statement(rules):
    cat, summary, conf = doc_types.classify_document("Monthly Account Statement", rules)
    assert cat == "Statement"
    assert "Monthly Statement" in summary


def test_classify_tax_forms(rules):
    cat, summary, conf = doc_types.classify_document("1099-INT Tax Form", rules)
    assert cat == "Tax Document"
    assert summary == "1099-INT Tax Form"

    cat, summary, conf = doc_types.classify_document("1099-MISC Tax Form", rules)
    assert cat == "Tax Document"
    assert summary == "1099-MISC Tax Form"


def test_skips_agreements_and_disclosures(rules):
    assert doc_types.should_skip("Deposit Account Agreement", rules) is True
    assert doc_types.should_skip("Privacy Notice and Disclosure", rules) is True
    assert doc_types.should_skip("Fee Schedule", rules) is True
    assert doc_types.should_skip("Monthly Statement", rules) is False


def test_classify_casa_account_statements(rules):
    # Personal / Rewards Checking
    cat, summary, conf = doc_types.classify_document("Rewards Checking Statement", rules)
    assert cat == "Statement"
    assert "Rewards Checking Statement" in summary

    cat, summary, conf = doc_types.classify_document("Personal Checking Statement", rules)
    assert cat == "Statement"
    assert "Personal Checking Statement" in summary

    # Savings / HYSA
    cat, summary, conf = doc_types.classify_document("High Yield Savings Statement", rules)
    assert cat == "Statement"
    assert "High Yield Savings Statement" in summary

    cat, summary, conf = doc_types.classify_document("American Express Savings Statement", rules)
    assert cat == "Statement"
    assert "Savings Statement" in summary


def test_filename_pattern_statements_does_not_say_receipt():
    from storage import build_pdf_filename
    from amexbanking_docs import Document
    doc = Document(
        title="Business Checking Statement",
        date="2026-10-31",
        category="Statement",
        summary="Business Checking Statement",
        account="AmexBiz 1234",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123",
    )
    name = build_pdf_filename(
        doc.date, doc.summary, "", record=doc,
        pattern="{account}/{year}/{date:yyyy-mm-dd}[ {kind}][ ({part})]"
    )
    assert "Receipt" not in str(name)
    assert str(name) == "2026-10-31 Statement.pdf"
    assert name.folder == "AmexBiz 1234/2026"
