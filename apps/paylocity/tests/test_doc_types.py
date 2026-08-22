"""Paylocity classification, the payroll safety guard, and the money-privacy
guarantee.

The classification cases encode what the rules file expects. The SAFETY and
PRIVACY cases are the reason this app is allowed to touch a payroll account.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds Paylocity's AppSpec
from paperpull_core import doc_types
import paylocity_site as site

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_pay_statements():
    for title in ["Pay Statement 2026-06-18",
                  "Pay Statement 2026-07-10 (Off-Cycle)",
                  "Pay Statement 2026-07-10 (#12345)"]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert summary == "Pay Statement", (title, summary)


def test_tax_forms_classify_when_they_appear():
    for title, summary in [("W-2", "W-2 Tax Form"),
                           ("1095-C", "1095 Health Coverage Form")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_no_foreign_mechanism_leaked_from_the_ukg_app_this_was_cloned_from():
    """This app began as a copy of UKG. References to UKG in a lesson comment
    are fine (that is how this repo records what it learned), but the UKG
    MECHANISM must be gone: no per-employer tenant, no UltiPro mobile API, no
    configure() call. The Dominion clone kept Robinhood's rules for months by
    leaving the mechanism in place, so this checks the machinery, not the word."""
    for f in (site.__file__, storage.__file__):
        text = Path(f).read_text(encoding="utf-8")
        for bad in ("ultipro", "def configure(", "base_url",
                    "ExternalServicesProxy", "peraton"):
            assert bad.lower() not in text.lower(), (f, bad)


# -- SAFETY: this is a payroll site ---------------------------------------

def test_wage_changing_controls_are_never_safe():
    """A payroll portal can redirect where wages land. None of these may ever
    be activated, whatever else the page calls them."""
    for label in ["Direct Deposit", "Edit Direct Deposit", "Add Bank Account",
                  "Routing Number", "Tax Withholding", "Update W-4",
                  "Change Address", "Change Password", "Update Beneficiary",
                  "Open Enrollment", "Request Time Off", "Submit Timesheet",
                  "Clock In", "Approve", "Delete", "Cancel"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_controls_are_safe():
    for label in ["Download", "View Pay Statement", "Print", "Pay Stub",
                  "Paystub", "Earnings Statement", "W-2", "Tax Form",
                  "Download PDF", "Year-End"]:
        assert site.is_safe_control(label), label


def test_deny_by_default():
    for label in ["", "More", "Continue", "Menu", "Help", "Options"]:
        assert not site.is_safe_control(label), label


# -- SAFETY: every requested URL stays on Paylocity's host ----------------

def test_off_host_urls_are_refused():
    good = "https://access.paylocity.com/Escher/Escher_WebUI/x"
    assert site.is_safe_url(good)
    for bad in [
            "https://access.paylocity.com.evil.test/x",       # suffix host
            "https://access.paylocity.com@evil.test/x",       # userinfo host
            "http://access.paylocity.com/x",                  # scheme downgrade
            "https://evil.test/Escher/x",
            "//evil.test/x",
            "javascript:alert(1)"]:
        assert not site.is_safe_url(bad), bad


# -- PRIVACY: the index records what a file IS, never what it says ---------

def test_the_pay_row_carries_no_amount():
    """collect_documents reads `amount` off each row and must not keep it. The
    title, date and identity are all that persist."""
    src = Path(site.__file__).read_text(encoding="utf-8")
    # the only mention of amount is the comment saying it is thrown away
    assert 'row.get("amount")' not in src
    assert "amount" in src.lower()  # the deliberate note is present


def test_the_employee_id_never_reaches_the_index_csv():
    """The download identity packs companyId|employeeId|historyId, and it is
    stored in discovery/progress, never written to the index. The CSV's Source
    URL column is fed from doc.href, which this app leaves empty."""
    docs_src = Path(site.__file__).parent.joinpath("paylocity_docs.py").read_text(encoding="utf-8")
    assert '"Source URL": doc.href' in docs_src
    # discovery records the packed identity under source_url, not href
    assert "source_url=source_url" in docs_src
