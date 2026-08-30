"""DFAS myPay document classification + the READ-ONLY safety guard.

Classification cases are provisional until diagnose has shown the real titles.
The SAFETY cases are not provisional: myPay can redirect retirement pay, change
tax withholding, start and stop allotments and alter SBP elections, so the
guard is the reason this app is allowed near the account at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
from paperpull_core import doc_types
import mypay_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_retiree_account_statements():
    for title, summary in [
            ("Retiree Account Statement - July 2026", "Retiree Account Statement"),
            ("eRAS 07/2026", "Retiree Account Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_crsc_statements():
    for title in ["CRSC Pay Statement January 2026",
                  "Combat-Related Special Compensation Statement"]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == "CRSC Pay Statement", (title, s)


def test_crsc_and_eras_are_told_apart_in_the_filename():
    """Both are pay statements and the core routes by category, so they share a
    folder. The filename is what keeps them distinguishable."""
    storage.set_filename_owner("")
    eras = build_pdf_filename("2026-07-31", "Retiree Account Statement", "")
    crsc = build_pdf_filename("2026-07-31", "CRSC Pay Statement", "")
    assert eras != crsc
    assert eras == "2026-07-31 DFAS myPay Retiree Account Statement.pdf"
    assert crsc == "2026-07-31 DFAS myPay CRSC Pay Statement.pdf"


def test_tax_forms():
    cat, s, _ = doc_types.classify_document("1099-R for Tax Year 2025", RULES)
    assert cat == doc_types.TAX and s == "1099-R Tax Form"


def test_year_end():
    cat, s, _ = doc_types.classify_document("Year-End Statement 2025", RULES)
    assert cat == doc_types.YEAR_END


def test_no_mortgage_vocabulary_from_the_app_this_was_cloned_from():
    """Cloned from the M&T mortgage app. A retiree pay account has no mortgage
    statements or escrow analyses, and a previous clone in this repo shipped
    the wrong provider's vocabulary for months."""
    rules_text = (Path(__file__).resolve().parents[1] / "document_rules.json").read_text(encoding="utf-8")
    for word in ("mortgage", "escrow", "1098", "hazard", "flood"):
        assert word not in rules_text.lower(), word


# -- SAFETY: myPay can move a retirement payment ---------------------------

def test_pay_changing_controls_are_never_safe():
    for label in [
            # where the money goes
            "Start Direct Deposit", "Change Direct Deposit", "Update Bank Account",
            "Routing Number", "Start Allotment", "Stop Allotment",
            "Discretionary Allotment",
            # tax and entitlements
            "Federal Withholding", "State Tax Withholding", "Update W-4",
            "Change Exemptions", "SBP Election", "Change Beneficiary",
            "TSP", "SGLI Election",
            # identity
            "Social Security Number", "Update Address", "Change Password",
            "Update Login ID", "Update Email", "Security Question",
            # consent and commit verbs
            "Agree to Terms", "I Accept", "Consent", "Submit", "Confirm",
            "Save Changes", "Manage Settings", "Turn off", "Opt Out",
            "Certify", "Authorize", "Request Payment"]:
        assert not site.is_safe_control(label), label


def test_the_documents_the_user_wants_are_allowed():
    for label in ["Download", "View Statement", "Open PDF", "Print",
                  "Retiree Account Statement", "CRSC Pay Statement", "eRAS",
                  "1099-R", "View Document", "Download PDF", "Tax Statement",
                  "Statement Archive"]:
        assert site.is_safe_control(label), label


def test_deny_by_default():
    for label in ["", "   ", "More", "Go", "Help", "Menu", "OK", "Yes"]:
        assert not site.is_safe_control(label), label


def test_the_ssn_field_is_only_ever_detected_never_used():
    """The sign-in page carries an SSN recovery field. It may be used as a
    signed-out signal and nothing else - never read from, never typed into."""
    src = (Path(__file__).resolve().parents[1] / "mypay_site.py").read_text(encoding="utf-8")
    assert "socialField" in src, "the signed-out check should know this field"
    for forbidden in (".fill(", ".type(", "input_value(", "text_content()"):
        assert forbidden not in src, forbidden
    assert site.FORBIDDEN_CONTROL_RE.search("Social Security Number")
    assert site.FORBIDDEN_CONTROL_RE.search("socialField")


# -- SAFETY: nothing is fetched until the app is actually mapped ------------

def test_a_document_is_fetched_by_a_validated_id_never_by_a_url():
    """A document is identified by "typeId|documentId", both plain integers,
    and the type must be one this app knows. The request path is then built
    from two numbers, so nothing a stored or tampered value could contain can
    steer the request somewhere else on a government system."""
    assert site.parse_doc_id("21|2025-05-20") == (21, "2025-05-20", 0)
    assert site.parse_doc_id("  20|2026-08-21  ") == (20, "2026-08-21", 0)
    assert site.parse_doc_id("21|2025-05-20|1") == (21, "2025-05-20", 1)
    for bad in ["21|abc", "99|2025-05-20", "../etc/passwd", "21", "",
                "2 1|2025-05-20", "8|2025-05-20", "21|", "|2025-05-20",
                "21|12345", "21|2025-5-20", "21|2025-05-20|x",
                "21|2025-05-20 OR 1=1", "https://evil.test/21|2025-05-20"]:
        assert site.parse_doc_id(bad) is None, bad


def test_the_identity_is_the_date_not_the_transient_id():
    """A live run recorded every eRAS and 1099-R twice and 404-ed on half of
    them: myPay hands out a numeric Id for generated documents that does not
    survive the session. The identity is type + date, and the Id is looked up
    fresh at download time."""
    src = (Path(__file__).resolve().parents[1] / "mypay_site.py").read_text(encoding="utf-8")
    assert "def resolve_document_id" in src
    assert "resolve_document_id(page, type_id, date, ordinal)" in src
    # the collector must build its key from the date, never from Id
    assert '"%d|%s" % (type_id, date)' in src


def test_the_document_types_are_the_apps_own_numbers():
    """Taken from myPay's DocumentTypeEnum, not invented."""
    assert site.DOCUMENT_TYPES[21] == "Retiree Account Statement"
    assert site.DOCUMENT_TYPES[20] == "CRSC Pay Statement"
    assert site.DOCUMENT_TYPES[18] == "1099-R Tax Form"


def test_urls_must_stay_on_mypays_host():
    assert site.is_safe_url("https://mypay.dfas.mil/x")
    for bad in ["https://mypay.dfas.mil.evil.test/x",
                "https://mypay.dfas.mil@evil.test/x",
                "http://mypay.dfas.mil/x",
                "https://dfas.mil/x",
                "https://evil.test/x",
                "//evil.test/x",
                "javascript:alert(1)",
                ""]:
        assert not site.is_safe_url(bad), bad


def test_only_mypay_frames_are_read():
    class F:
        def __init__(self, url): self.url = url
    assert site.is_mypay_frame(F("https://mypay.dfas.mil/#/statements"))
    for bad in ["https://mail.google.com/", "about:blank", "",
                "http://mypay.dfas.mil/x", "https://mypay.dfas.mil.evil.test/x"]:
        assert not site.is_mypay_frame(F(bad)), bad


def test_the_app_never_navigates_or_submits():
    """On a short government session, navigating could drop the user's place,
    and submitting a form on a pay system is out of the question."""
    src = (Path(__file__).resolve().parents[1] / "mypay_site.py").read_text(encoding="utf-8")
    for forbidden in ("page.goto", ".goto(", ".click()", ".check()",
                      ".select_option(", ".set_checked(", "on(\"dialog\"",
                      "expect_download"):
        assert forbidden not in src, forbidden


def test_no_screenshot_of_a_pay_page_is_written():
    """A screenshot of myPay shows pay amounts and identifiers, and would sit
    in Diagnostics where it is easy to attach to a bug report by accident."""
    src = (Path(__file__).resolve().parents[1] / "mypay_docs.py").read_text(encoding="utf-8")
    assert "page.screenshot(" not in src


def test_a_signin_page_returned_instead_of_a_pdf_is_recognised():
    """Government sessions are short. An expired one answers with HTML at
    HTTP 200, and if that is not spotted the run reports an empty success."""
    assert site._looks_like_login_html(
        b"<!DOCTYPE html><html><body><form><input type=\"password\"></form>")
    assert site._looks_like_login_html(b"<html>Your session has expired</html>")
    assert not site._looks_like_login_html(b"%PDF-1.7 real document")
    assert not site._looks_like_login_html(b"")


# -- ACTIVE DUTY: added but NOT verified against a real account --------------

def test_active_duty_document_types_are_enumerated():
    """One app serves retirees and active duty. A type that does not apply to
    an account returns nothing and is skipped, so listing the active-duty types
    costs a retiree nothing."""
    assert site.DOCUMENT_TYPES[2] == "Leave and Earnings Statement"
    assert site.DOCUMENT_TYPES[3] == "W-2 Tax Form"
    assert site.DOCUMENT_TYPES[4] == "W-2C Corrected Tax Form"


def test_leave_and_earnings_statements_classify_and_file_correctly():
    for title in ["Leave and Earnings Statement", "LES for 15 Aug 2026"]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert summary == "Leave and Earnings Statement", (title, summary)
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-08-15", "Leave and Earnings Statement", "") == \
        "2026-08-15 DFAS myPay Leave and Earnings Statement.pdf"


def test_a_corrected_w2_is_not_filed_as_an_ordinary_one():
    """W-2C must be matched before the generic W-2 rule, or a correction and
    the original become indistinguishable on disk."""
    for title in ["W-2C Corrected Tax Form", "W2C 2025", "W-2-C 2025"]:
        cat, summary, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert summary == "W-2C Corrected Tax Form", (title, summary)
    cat, summary, _ = doc_types.classify_document("W-2 Tax Form", RULES)
    assert summary == "W-2 Tax Form"


def test_active_duty_support_is_labelled_as_untested():
    """It was written from myPay's own type numbers against an API proven on a
    retiree account, but nobody has run it on an active-duty account. Saying so
    is the difference between a caveat and a false claim."""
    src = (Path(__file__).resolve().parents[1] / "mypay_site.py").read_text(encoding="utf-8")
    assert "NOT YET VERIFIED" in src
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "not been tested" in readme.lower() or "untested" in readme.lower()
