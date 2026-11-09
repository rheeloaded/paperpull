"""Verizon Mobile classification, the carrier guard, and the survey's promises.

A run presses nothing, so the guard says only what Diagnose would make of
each control it sees. What these pin is that it would refuse every control
that pays or changes service, that the survey cannot leak a number, and
that a date is read in the forms verizon.com prints it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds Verizon Mobile's AppSpec
from paperpull_core import doc_types
import verizonmobile_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bills_are_monthly_statements():
    for title in ["Monthly Statement - August 12, 2026", "Wireless bill", "Bill",
                  "Mobile bill", "Invoice", "Monthly bill for July"]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == "Monthly Statement", (title, s)


def test_payment_receipts_and_marketing_are_skipped():
    for t in ["Payment receipt", "Payment confirmation", "AutoPay enrollment",
              "Paperless billing", "Customer Agreement", "Usage details", "Offers for you"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 12, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-08-12", "Monthly Statement", "") == \
        "2026-08-12 Verizon Mobile Monthly Statement.pdf"


# -- the carrier guard ------------------------------------------------------

def test_every_control_that_pays_or_changes_service_is_refused():
    for label in ["Pay now", "Make a payment", "Set up AutoPay", "Manage AutoPay",
                  "Payment arrangement", "Add a line", "Upgrade", "Trade in your phone",
                  "Change plan", "Shop plans", "Add-ons", "Buy now", "Cart", "Checkout",
                  "Suspend service", "Restore service", "Transfer your number",
                  "Get a new SIM", "Activate eSIM", "International roaming",
                  "Cancel service", "Go paperless", "Update profile", "Change password",
                  "Chat with us", "Contact us", "Submit", "Confirm", "Save Changes",
                  "Turn off", "Manage", "Edit address", "Deals", "Move"]:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_bill_are_allowed():
    for label in ["Download bill", "Download bill (PDF)", "View bill", "Print bill",
                  "See bill", "Bill PDF", "PDF", "View bill history", "See more bills",
                  "Show older bills", "Download statement", "Review bill", "Review bill PDF"]:
        assert site.is_safe_control(label), label


def test_diagnose_marks_the_pages_own_bill_controls():
    """The survey saw "Review bill" and "Review bill PDF" on every cycle,
    and those are what Diagnose marks as a bill's controls."""
    for label in ["Review bill PDF", "Review bill", " review bill pdf "]:
        assert site.BILL_CONTROL_RE.search(label), label
    for label in ["Pay bill", "Review bill and pay", "Download bill", "Bill history"]:
        assert not site.BILL_CONTROL_RE.search(label), label


def test_a_bill_control_that_also_pays_is_refused():
    """"View and pay bill" is one control on some carrier pages. The pay
    word wins, whatever else the label says."""
    for label in ["View and pay bill", "Pay bill", "Download bill and pay",
                  "View bill / Make a payment"]:
        assert not site.is_safe_control(label), label


def test_the_login_and_settings_vocabulary_is_refused_too():
    for label in ["Sign in", "Log in", "Remember me", "Preferences", "Settings"]:
        assert not site.is_safe_control(label), label


# -- dates, the identity of a bill -------------------------------------------

def test_dates_in_every_form_a_page_prints():
    assert site.parse_date("Aug 12, 2026 Download bill PDF") == "2026-08-12"
    assert site.parse_date("August 12, 2026") == "2026-08-12"
    assert site.parse_date("Bill for 08/12/2026") == "2026-08-12"
    assert site.parse_date("08/12/26") == "2026-08-12"
    assert site.parse_date("2026-08-12") == "2026-08-12"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("August 2026") == ("2026-08-31", "August 2026")
    assert site.end_day("08/12/2026") == "2026-08-12"
    assert site.end_day("02/30/2026") is None and site.end_day("2026-08-12") is None


# -- the survey a tester attaches to an issue --------------------------------

def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 bill") == "account ######### bill"
    assert site.redact("Aug 12, 2026") == "Aug 12, 2026"       # dates are short runs
    assert site.redact("phone 555-0100") == "phone 555-0100"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "verizonmobile_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"bills": [{"amount": 12.5, "date": "x"}], "n": 3}) == \
        {"bills": ["1 item(s)", {"amount": "number", "date": "string"}], "n": "number"}


def test_the_survey_marks_only_billing_links():
    for text in ["Bill history", "See bill history", "View bills", "Past bills",
                 "Billing", "Statements"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Pay bill", "Upgrade", "Shop", "Account", "Support"]:
        assert not site.SURVEY_LINK_RE.match(text), text


# -- hosts --------------------------------------------------------------------

def test_only_verizon_hosts():
    assert site.is_safe_url("https://www.verizon.com/digital/nsa/secure/ui/bill/")
    assert site.is_safe_url("https://secure.verizon.com/x")
    assert not site.is_safe_url("https://verizon.com.evil.test/bill.pdf")
    assert not site.is_safe_url("http://www.verizon.com/bill.pdf")
    assert not site.is_safe_url("https://user@verizon.com/bill.pdf")
    assert all(site.is_safe_url(u) for u in site.URLS.values())
    assert site.URLS["login"] == site.HISTORY_URL == site.BILLING_URL


def test_the_confirmed_status_is_stated_where_a_reader_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "CONFIRMED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Confirmed on a real account" in readme


def test_this_is_the_wireless_side_and_the_fios_app_is_separate():
    """Two apps on one host. This one must never wander onto the Fios app's
    port or folder, so the config's port is its own."""
    import json
    cfg = json.loads((Path(site.__file__).parent / "config.example.json").read_text(encoding="utf-8-sig"))
    assert cfg["cdp_url"].endswith(":9255")
    fios = json.loads((Path(site.__file__).parents[1] / "verizon" / "config.example.json").read_text(encoding="utf-8-sig"))
    assert fios["cdp_url"] != cfg["cdp_url"]
