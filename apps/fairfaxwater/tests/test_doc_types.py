"""Fairfax Water, the parts that can be tested before the portal is mapped.
The guard, the host allowlist, the date shapes, the folders, and the
survey's redaction."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import fairfaxwater_site as site
from paperpull_core import doc_types


def test_the_spec():
    assert storage.SPEC.provider == "Fairfax Water"
    assert storage.SPEC.token == "fairfax"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_bill_titles_classify():
    rules = doc_types.load_rules()
    assert doc_types.classify_document("Bill", rules)[:2] == ("Statement", "Bill")
    assert doc_types.classify_document("Bill 03/15/2026", rules)[:2] == ("Statement", "Bill")
    assert doc_types.classify_document("Final Bill", rules)[:2] == ("Statement", "Final Bill")


def test_dates():
    assert site.parse_date("02/09/2026") == "2026-02-09"
    assert site.parse_date("2026-02-09T00:00:00") == "2026-02-09"
    assert site.parse_date("soon") == ""


def test_a_billing_history_row_parses_and_keeps_only_the_last_four_of_the_account():
    r = site.parse_row("123456789012 07/17/2026 $ 397.86 08/17/2026 Paid View")
    assert r == {"account": "9012", "date": "2026-07-17", "amount": "397.86", "due": "2026-08-17", "status": "Paid"}
    assert site.parse_row("Invoice Date Invoice Amount Due Date Status") is None
    assert site.parse_row("123456789012 07/17/2026 $ 397.86 08/17/2026 Past Due View")["status"] == "Past Due"


def test_the_nav_guard_opens_pages_and_nothing_else():
    assert site.is_safe_nav("Billing & Payment") and site.is_safe_nav("Dashboard") and site.is_safe_nav("Usage")
    for name in ["Payment Methods", "Start Service", "Stop Service", "Pay Now", "Profile & Accounts", "LOG OUT"]:
        assert not site.is_safe_nav(name), name


def test_paying_and_changing_service_are_never_safe():
    for name in ["Pay my bill", "Make a payment", "Set up autopay", "Add a card", "Bank account",
                 "Start service", "Stop service", "Go paperless", "Report a leak", "Payment arrangement",
                 "Update address", "Log out", "Change password", "Enroll in budget billing"]:
        assert not site.is_safe_control(name), name


def test_reading_a_bill_is_safe():
    for name in ["View bill", "Bill history", "Billing history", "Download PDF", "View", "Usage history",
                 "Statements"]:
        assert site.is_safe_control(name), name


def test_only_the_portal_and_the_utility_hosts_are_allowed():
    assert site.is_safe_url("https://www.fwcustomer.org/")
    assert site.is_safe_url("https://www.fairfaxwater.org/customer-service")
    assert not site.is_safe_url("http://www.fwcustomer.org/")
    assert not site.is_safe_url("https://fwcustomer.org.example/")
    assert not site.is_safe_url("https://user:pw@www.fwcustomer.org/")


def test_collect_reads_rows_and_a_scoped_run_keeps_only_its_years(monkeypatch):
    texts = ["123456789012 07/17/2026 $ 397.86 08/17/2026 Paid View",
             "123456789012 04/16/2026 $ 384.81 05/18/2026 Paid View",
             "123456789012 10/17/2025 $ 404.66 11/17/2025 Paid View"]
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "expand_history", lambda page, until_year=None: len(texts))
    monkeypatch.setattr(site, "_row_texts", lambda page: texts)
    rows = site.collect_documents(None)
    assert [r["date"] for r in rows] == ["2026-07-17", "2026-04-16", "2025-10-17"]
    assert rows[0] == {"title": "Bill", "date": "2026-07-17", "account": "Account 9012", "category": "Statement",
                       "item_id": "2026-07-17", "client_id": "397.86", "href": site.URLS["documents"], "period_start": ""}
    rows = site.collect_documents(None, keep=lambda y: y == "2025")
    assert [r["date"] for r in rows] == ["2025-10-17"]


def test_the_pdf_host_is_allowed_only_because_the_portal_opens_it_and_nothing_else_is():
    assert site.is_safe_url("https://docsight.net/XDSServer/Fairfax_Water_Invoice.pdf?x=1")
    assert not site.is_safe_url("https://docsight.net.example/")
    assert "never navigates there" in site.__doc__


def test_the_survey_follows_only_exact_bill_words():
    assert site.SURVEY_LINK_RE.match("Bills")
    assert site.SURVEY_LINK_RE.match("Billing History")
    assert site.SURVEY_LINK_RE.match("Usage")
    assert not site.SURVEY_LINK_RE.match("Pay bill")
    assert not site.SURVEY_LINK_RE.match("Start service")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("account 123456789 view") == "account ######### view"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"accounts": [{"number": "123456789", "balance": 12.5}]})
    assert shape == {"accounts": ["1 item(s)", {"number": "string", "balance": "number"}]}


def test_a_click_reads_the_controls_own_text_before_it_clicks():
    class C:
        def __init__(self, text): self.text, self.clicked = text, False
        def inner_text(self, timeout=None): return self.text
        def click(self, timeout=None): self.clicked = True
    ok = C("View"); assert site._guarded_click(ok) and ok.clicked
    more = C("Show More"); assert site._guarded_click(more) and more.clicked
    pay = C("Pay Now"); assert not site._guarded_click(pay) and not pay.clicked
