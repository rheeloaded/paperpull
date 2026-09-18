"""Synthetic fixtures for provider parsing, filing and control checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import usbank_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def test_card_statements():
    for title, summary in [
            ("Credit Card Statement", "Credit Card Statement"),
            ("Billing Statement - March 2026", "Billing Statement"),
            ("Monthly Statement", "Monthly Statement"),
            ("eStatement", "Account Statement"),
            ("Statement", "Statement")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == summary, (title, s)


def test_tax_forms_classify_but_are_out_of_scope():
    for title, summary in [
            ("2025 1099-MISC", "1099-MISC Tax Form"),
            ("Form 1099-C Cancellation of Debt", "1099-C Tax Form"),
            ("Tax Form Package 2025", "Tax Document")]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.TAX, title
        assert s == summary, (title, s)


def test_card_paperwork_is_skipped():
    for title in ["Cardmember Agreement", "Cardholder Agreement",
                  "Change in Terms", "Important Information About Your Account",
                  "Privacy Pledge", "Consumer Pricing Information",
                  "Guide to Benefits", "ESign Consent"]:
        assert doc_types.should_skip(title, RULES), title
    assert not doc_types.should_skip("Credit Card Statement", RULES)


def test_only_statements_are_in_scope():
    cfg = {"document_types": ["Statement"]}
    assert doc_types.wanted(doc_types.STATEMENT, cfg)
    assert not doc_types.wanted(doc_types.TAX, cfg)
    assert not doc_types.wanted(doc_types.OTHER, cfg)


def test_unknown_is_low_confidence_other():
    cat, _, conf = doc_types.classify_document("Welcome Kit", RULES)
    assert cat == doc_types.OTHER and conf == doc_types.LOW


def test_month_year_files_on_last_day():
    assert site.parse_period_date("Statement December 2025")[0] == "2025-12-31"
    assert site.parse_period_date("February 2024 Statement")[0] == "2024-02-29"


def test_mmddyyyy_exact():
    assert site.parse_period_date("Statement 01/15/2025")[0] == "2025-01-15"


def test_filename():
    assert build_pdf_filename("2026-03-15", "Credit Card Statement", "") == \
        "2026-03-15 U.S. Bank Credit Card Statement.pdf"


def test_money_actions_are_never_safe():
    for label in ["Pay card", "Make a payment", "Schedule payment", "Autopay",
                  "Pay bills", "Transfer", "Send money with Zelle", "Zelle",
                  "Wire transfer", "Deposit", "Withdraw", "Stop payment"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_usbank_card_actions_are_never_safe():
    for label in ["ExtendPay Plan", "ExtendPay Loan", "ExtendPay Fix",
                  "Simple Loan", "Balance transfer", "Cash advance",
                  "Order convenience checks", "Redeem rewards",
                  "Real-Time Rewards", "Rewards center", "Redeem FlexPoints",
                  "Book travel", "Travel Center", "View offers",
                  "Request credit line increase", "Increase my credit limit",
                  "Add authorized user", "Activate card", "Lock card",
                  "Freeze card", "Replace card", "Close account",
                  "Dispute a transaction", "Report fraud", "Apply now",
                  "Set travel notification", "Go paperless",
                  "Update address", "Change username", "Enroll",
                  "Submit", "Confirm", "Authorize"]:
        assert not site.is_safe_control(label), label
        assert site.FORBIDDEN_CONTROL_RE.search(label), label


def test_document_actions_are_safe():
    for label in ["Download", "Download PDF", "View statement",
                  "Download statement", "View document", "Open PDF", "Save PDF",
                  "View 1099", "Statement PDF", "View eStatement",
                  "View tax form"]:
        assert site.is_safe_control(label), label


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("More")


def test_payment_widget_selects_are_refused():
    for identity in [
            "fromAccount | fromAccount | Select an account",
            "payFromAccount | Pay from | Make a payment",
            "amount | Amount | Payment",
            "paymentAmount | How much | Pay card",
            "payee | Select a payee | Bill Pay",
            "transferTo | To | Balance transfer",
            "planTerm | Choose a term | ExtendPay Plan",
            "redeemFor | Redeem for | Rewards center"]:
        assert site.is_money_control(identity), identity


def test_statement_pickers_are_allowed():
    for identity in [
            "statementPeriod | Statement period | Statements",
            "documentYear | Year | Statements & documents",
            "cardSelector | Choose a card | Documents",
            "taxYear | Tax year | Tax forms"]:
        assert not site.is_money_control(identity), identity


def test_unreadable_identity_fails_closed():
    assert site.is_money_control("")


def test_real_card_names_are_accepted_as_headers():
    for label in ["U.S. Bank Cash+ Visa Signature Card (...1234)",
                  "Shopper Cash Rewards Visa Signature (...5678)",
                  "Triple Cash Rewards World Elite Mastercard ...7890",
                  "Altitude Reserve Visa Infinite (...9012)",
                  "Altitude Go Visa Signature ****4321",
                  "FlexPerks Gold American Express (...3456)",
                  "Smartly Visa Signature ending in 1111"]:
        assert site.is_card_control(label), label


def test_the_blocklist_alone_would_have_refused_a_real_card():
    for label in ["Shopper Cash Rewards Visa Signature (...5678)",
                  "Triple Cash Rewards World Elite Mastercard ...7890"]:
        assert site.FORBIDDEN_CONTROL_RE.search(label), label
        assert site.is_card_control(label), label


def test_card_shaped_actions_are_still_refused():
    for label in ["Pay Cash+ (...1234)", "Redeem rewards (...1234)",
                  "Activate your Altitude Go (...1234)",
                  "Lock card ...7890", "Close account (...9012)",
                  "Add authorized user to Cash+ (...1234)",
                  "Transfer a balance to Altitude Go ****4321",
                  "Order convenience checks for ...7890"]:
        assert not site.is_card_control(label), label


def test_a_label_with_no_card_number_is_not_a_header():
    assert not site.is_card_control("Cash+ Visa Signature")
    assert not site.is_card_control("Statements & documents")
    assert not site.is_card_control("")


def test_card_masking_shapes():
    for text in ["Card (...1234)", "Card ...1234", "Card ****1234",
                 "Card xxxx1234", "Card ending in 1234", "Card ending 1234"]:
        assert site.CARD_RE.search(text), text
    assert not site.CARD_RE.search("Statement December 2025")


def test_card_is_read_from_the_row():
    assert site.card_in_row(
        "Aug 09, 2026 Statement Cash+ Visa Signature (...1234) Download") \
        == "Cash+ Visa Signature (...1234)"
    assert site.card_in_row("Aug 09, 2026 Statement Download") == ""


def test_doc_title_drops_the_date_card_and_verbs():
    assert site.doc_title_in_row(
        "Aug 09, 2026 Statement Cash+ Visa Signature (...1234) Download",
        "Cash+ Visa Signature (...1234)") == "Statement"
    assert site.doc_title_in_row("08/09/2026 Billing Statement PDF") == \
        "Billing Statement"

    assert site.doc_title_in_row("Aug 09, 2026 Download") == "Statement"


def test_a_rewards_named_card_does_not_lose_its_statements():
    for name in [
            "Aug 09, 2026 Statement Shopper Cash Rewards (...5678) Download",
            "Aug 09, 2026 Statement Triple Cash Rewards World Elite ...7890 View"]:

        assert not site.is_safe_control(name), name

        assert site.is_safe_row_control(name), name


    plain = "08/09/2026 eStatement Altitude Reserve (...9012) PDF"
    assert site.is_safe_control(plain) and site.is_safe_row_control(plain)


def test_a_row_naming_no_card_is_unchanged():
    for name in ["Download", "View statement", "Aug 09, 2026 Statement PDF"]:
        assert site.is_safe_row_control(name) == site.is_safe_control(name), name


def test_a_rewards_ACTION_next_to_a_card_is_still_refused():
    for name in ["Redeem rewards for Cash+ (...1234)",
                 "Pay Shopper Cash Rewards (...5678)",
                 "Transfer a balance to Altitude Go ****4321",
                 "Activate Cash+ (...1234)",
                 "Redeem FlexPoints"]:
        assert not site.is_safe_row_control(name), name


def test_an_empty_row_control_is_not_safe():
    assert not site.is_safe_row_control("")
    assert not site.is_safe_row_control("(...1234)")


def test_row_label_re_requires_the_date():
    rx = site.row_label_re("2026-08-09")
    assert rx.search("Aug 09, 2026 Statement Download")
    assert rx.search("Aug 9, 2026 Statement Download")
    assert rx.search("08/09/2026 Statement Download")
    assert rx.search("8/9/2026 Statement Download")
    assert rx.search("2026-08-09 Statement Download")

    assert not rx.search("Aug 19, 2026 Statement Download")
    assert not rx.search("Aug 10, 2026 Statement Download")
    assert not rx.search("08/19/2026 Statement Download")


def test_row_label_re_requires_the_card_when_one_is_given():
    rx = site.row_label_re("2026-08-09", "Cash+ Visa Signature (...1234)")
    assert rx.search(
        "Aug 09, 2026 Statement Cash+ Visa Signature (...1234) Download")
    assert not rx.search(
        "Aug 09, 2026 Statement Altitude Go (...5678) Download")


def test_row_label_re_card_and_action_are_optional():
    rx = site.row_label_re("2026-08-09", "", "")
    assert rx.search("Aug 09, 2026 Statement")
    rx2 = site.row_label_re("2026-08-09", "Cash+ (...1234)", "Saves document")
    assert rx2.search("Aug 09, 2026 Statement Cash+ (...1234) Saves document")
    assert not rx2.search("Aug 09, 2026 Statement Cash+ (...1234) Download")


class _StubLocator:
    def count(self):
        return 0


class _StubPage:

    def locator(self, _selector):
        return _StubLocator()


def test_select_period_succeeds_when_there_is_no_picker():
    assert site.select_period(_StubPage(), "2026") is True


def test_period_options_reports_no_picker_as_empty():
    assert site.period_options(_StubPage()) == []


def test_the_real_download_control_is_parsed():
    m = site.ROW_DOWNLOAD_ARIA_RE.match("Download March 15, 2026 statement.")
    assert m
    assert site.parse_period_date(m.group(1))[0] == "2026-03-15"


def test_the_view_link_is_not_read_as_a_second_statement():
    view = "View March 15, 2026 statement in a new window."
    assert site.ROW_VIEW_ARIA_RE.match(view)
    assert not site.ROW_DOWNLOAD_ARIA_RE.match(view)


def test_the_disclosures_section_is_not_collected():
    assert site.STATEMENT_SECTION_RE.search("Credit Card ...4321 statements")
    assert not site.STATEMENT_SECTION_RE.search("E-statement disclosures")


def test_the_account_is_read_from_the_section_heading():
    assert site.account_in_heading("Credit Card ...4321 statements") == \
        "Credit Card ...4321"
    assert site.account_in_heading("E-statement disclosures") == ""

    assert site.account_in_heading("Pay Credit Card ...4321 statements") == ""


def test_the_real_account_label_clears_the_card_guard():
    assert site.is_card_control("Credit Card ...4321")


def test_row_label_re_matches_the_real_control_name():
    rx = site.row_label_re("2026-03-15")
    assert rx.search("Download March 15, 2026 statement.")
    assert not rx.search("Download February 15, 2026 statement.")

    assert not rx.search("Download March 5, 2026 statement.")


def test_row_label_re_is_usable_as_a_python_pattern_not_a_selector():
    assert "/" in site.row_label_re("2026-03-15").pattern


def test_a_maintenance_notice_is_not_rate_limiting():
    notice = ("Transfers: Most new transfers can be submitted, but some features "
              "may be temporarily unavailable. Bill pay, Zelle, mobile check deposit")
    assert not any(rx.search(notice) for rx in site.RATE_LIMIT_MARKERS)


def test_real_throttling_is_still_detected():
    for text in ["Too many requests", "Our service is temporarily unavailable",
                 "The site is currently unavailable", "HTTP error 429",
                 "We're experiencing technical difficulties",
                 "unusual traffic from your network"]:
        assert any(rx.search(text) for rx in site.RATE_LIMIT_MARKERS), text


# -- the verb "edit" must not match inside the noun "Credit" ------------------

def test_a_credit_card_statement_is_never_refused():
    """"edit" without a leading word boundary matched inside "Credit", so the
    one label a credit-card provider must never refuse was refused. Same fix
    as core 0.17.1, anthem and capitalone."""
    for label in ("Credit Card Statement", "Credit Card Monthly Statement"):
        assert site.is_safe_control(label), label


def test_the_edit_verb_is_still_refused_on_its_own():
    for label in ("Edit", "Edit profile", "Change address", "Update contact info"):
        assert not site.is_safe_control(label), label


def test_a_scoped_run_never_selects_a_year_it_will_throw_away(monkeypatch):
    """Selecting a year is a round trip, three seconds on a good day. With
    --year 2025 the picker's other years are not touched. Without a scope
    every year still is, which is what keeps discovery.json complete."""
    selected = []
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "account_options", lambda page: ["Card ...4321"])
    monkeypatch.setattr(site, "period_options", lambda page: ["2026", "2025", "2024", "2019"])
    monkeypatch.setattr(site, "select_period", lambda page, y: (selected.append(y), True)[1])
    monkeypatch.setattr(site, "read_rows", lambda page, acct: [])
    site.usbank_collect_structured(page=None, keep=lambda y: y == "2025")
    assert selected == ["2025"]
    selected.clear()
    site.usbank_collect_structured(page=None, keep=None)
    assert selected == ["2026", "2025", "2024", "2019"]
