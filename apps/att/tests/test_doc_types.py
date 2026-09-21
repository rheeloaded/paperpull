"""AT&T classification, the carrier guard, and the survey's promises.

The site layer is unverified, so what these pin is everything that must be
true before a tester ever runs it: the guard refuses every control that
pays or changes service, the survey cannot leak a number, and a bill row's
date is read in the forms att.com is likely to print it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
from paperpull_core import doc_types
import att_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bills_are_monthly_statements():
    for title in ["Monthly Statement - August 12, 2026", "Wireless bill", "Bill",
                  "Fiber bill", "Invoice", "Monthly bill for July"]:
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
    assert build_pdf_filename("2026-08-12", "Monthly Statement", "Statement") == \
        "2026-08-12 AT&T Monthly Statement Statement.pdf"


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
                  "Show older bills", "Download statement"]:
        assert site.is_safe_control(label), label
        assert site.BILL_CONTROL_RE.search(label) or "more" in label or "older" in label \
            or "history" in label, label


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

def test_bill_dates_in_every_form_att_prints():
    assert site.parse_date("Aug 12, 2026 Download bill PDF") == "2026-08-12"
    assert site.parse_date("August 12, 2026") == "2026-08-12"
    assert site.parse_date("Bill for 08/12/2026") == "2026-08-12"
    assert site.parse_date("08/12/26") == "2026-08-12"
    assert site.parse_date("2026-08-12") == "2026-08-12"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("August 2026") == ("2026-08-31", "August 2026")
    assert site._human_date("2026-08-12") == "August 12, 2026"


# -- the survey a tester attaches to an issue --------------------------------

def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 bill") == "account ######### bill"
    assert site.redact("Aug 12, 2026") == "Aug 12, 2026"       # dates are short runs
    assert site.redact("phone 555-0100") == "phone 555-0100"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "att_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"bills": [{"amount": 12.5, "date": "x"}], "n": 3}) == \
        {"bills": ["list of 1", {"amount": "float", "date": "str"}], "n": "int"}


def test_the_survey_follows_only_billing_links():
    for text in ["Bill history", "See bill history", "View bills", "Past bills",
                 "Billing", "Statements"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Pay bill", "Upgrade", "Shop", "Account", "Support"]:
        assert not site.SURVEY_LINK_RE.match(text), text


# -- hosts --------------------------------------------------------------------

def test_only_att_hosts():
    assert site.is_safe_url("https://www.att.com/acctmgmt/billandpay/history")
    assert site.is_safe_url("https://signin.att.com/x")
    assert not site.is_safe_url("https://att.com.evil.test/bill.pdf")
    assert not site.is_safe_url("http://www.att.com/bill.pdf")
    assert not site.is_safe_url("https://user@att.com/bill.pdf")
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_unverified_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "Not yet tested against a real account" in readme


# -- round two, from the first tester's survey (#26) --------------------------

class _Loc:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n

    def or_(self, other):
        return _Loc(self._n + other._n)


class _Page:
    def __init__(self, url, bill_controls=1, body=""):
        self.url = url
        self._n = bill_controls
        self._body = body

    def get_by_role(self, role, name=None):
        # the fake splits its bill controls between the two roles
        return _Loc(self._n - self._n // 2 if role == "button" else self._n // 2)

    def locator(self, sel):
        page = self

        class _Body:
            def inner_text(self_, timeout=0):
                return page._body
        return _Body()


def test_the_overview_with_its_one_view_bill_button_is_not_the_billing_page():
    """Sign-in lands on /acctmgmt/overview, a shop page with one "View
    bill" button. That button alone passed the first check, so discovery
    read 125 rows of phones and cases and no bills."""
    assert not site._looks_like_billing(_Page("https://www.att.com/acctmgmt/overview?x=1", bill_controls=1))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/billing/mybillingcenter", bill_controls=0))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/x", bill_controls=3))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/x", bill_controls=0, body="Your bill history"))


def test_the_billing_center_is_tried_first_and_the_nav_link_is_allowed():
    assert site.BILLING_CANDIDATES[0] == "https://www.att.com/acctmgmt/billing/mybillingcenter"
    assert site.is_safe_control("Billing")
    assert site.BILLING_NAV_RE.match("Billing") and site.BILLING_NAV_RE.match("Bill & payments")
    for text in ("Billing", "View bill", "Bill history"):
        assert site.SURVEY_LINK_RE.match(text), text
    # The nav's money words stay refused whatever the survey wants.
    for text in ("Payments", "Pay off my device", "Check my usage", "See usage details"):
        assert not site.is_safe_control(text), text


def test_a_url_in_the_survey_loses_its_query_string():
    """Query strings carry session details the survey has no use for.
    Nothing after the ? reaches the file."""
    assert site.redact("https://www.att.com/acctmgmt/overview?haloSuccess=true&lt=abcDEF123456789") == \
        "https://www.att.com/acctmgmt/overview?..."
    assert site.redact("see https://www.att.com/a?b=c and https://www.att.com/d") == \
        "see https://www.att.com/a?... and https://www.att.com/d"


# -- round three, from the second survey ------------------------------------

def test_the_history_api_answer_gives_every_bill_its_date_and_hint():
    """content.historyList[] of {type, displayDate, cycleStartDate,
    cycleEndDate, statementId, invoiceIndex, ...}, the shape the second
    survey recorded. Payments are left out, the id rides as the hint."""
    body = {"content": {"accountNumber": "x", "billFound": True, "historyList": [
        {"type": "Bill", "displayDate": "Aug 22, 2026", "cycleStartDate": "07/23/2026",
         "cycleEndDate": "08/22/2026", "statementId": "S1", "invoiceIndex": "3"},
        {"type": "Payment", "displayDate": "Aug 10, 2026", "cycleEndDate": "", "statementId": ""},
        {"type": "Bill", "displayDate": "Jul 22, 2026", "cycleStartDate": "2026-06-23",
         "cycleEndDate": "2026-07-22", "statementId": "S2", "invoiceIndex": "2"},
        {"type": "Bill", "displayDate": "Jun 22, 2026", "statementId": "S3"},
    ]}}
    got = site._history_from_api(body)
    assert [(b["date"], b["hint"], b["start"]) for b in got] == [
        ("2026-08-22", "S1|3", "2026-07-23"), ("2026-07-22", "S2|2", "2026-06-23"), ("2026-06-22", "S3|", "")]
    assert site._history_from_api({}) == [] and site._history_from_api({"content": {}}) == []


def test_bill_buttons_without_a_year_step_the_year_back_across_january():
    """"Bill / Jul 23 - Aug 22 / $xx.xx". The newest takes this year, and
    each older one goes back a year whenever its month is later than the
    one before it."""
    iso, prev = site._period_end("Bill\nJan 23 - Feb 22\n$10.00", 2026, None)
    assert (iso, prev) == ("2026-02-22", 2)
    iso, prev = site._period_end("Bill\nDec 23 - Jan 22\n$10.00", 2026, 2)
    assert (iso, prev) == ("2026-01-22", 1)
    iso, prev = site._period_end("Bill\nNov 23 - Dec 22\n$10.00", 2026, 1)
    assert (iso, prev) == ("2025-12-22", 12)
    assert site._period_end("Bill\nno dates here", 2026, 12) == (None, 12)


def test_the_two_pdf_buttons_are_allowed_and_see_bill_history_is_not_a_bill():
    for text in ("Download PDF", "View/print PDF"):
        assert site.PDF_BUTTON_RE.match(text), text
        assert site.is_safe_control(text), text
    assert not site.PDF_BUTTON_RE.match("Download bill & payment info")
    # Round two clicked this instead of Download PDF. It is navigation.
    assert not site.BILL_CONTROL_RE.search("See bill history")
    assert site.BILL_CONTROL_RE.search("View bill") and site.BILL_CONTROL_RE.search("Download PDF")
    # The history page's bill buttons pass the guard, the account picker does not matter.
    assert site.is_safe_control("Bill\nJul 23 - Aug 22\n$xx.xx")
    assert site.BILL_BUTTON_RE.match("Bill\nJul 23 - Aug 22\n$xx.xx")


def test_the_history_page_counts_as_billing_and_its_api_is_recognized():
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/billing/billandpaymenthistory?filter=bill", bill_controls=0))
    assert site.HISTORY_API_RE.search("https://www.att.com/msapi/webbillexpms/v1/billandpaymenthistory")
    assert not site.HISTORY_API_RE.search("https://www.att.com/msapi/webbillexpms/v1/billandpaymenthistorygraph")
    assert site.HISTORY_URL.startswith("https://www.att.com/acctmgmt/billing/billandpaymenthistory")


def test_download_bill_takes_a_hint_and_a_trace():
    params = inspect.signature(site.download_bill).parameters
    assert "hint" in params and "trace" in params
