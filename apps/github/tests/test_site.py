"""The GitHub site layer, against the page shape GitHub's documentation
describes. Every row here is made up. Nothing in them is a real payment."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import github_site as site
from paperpull_core.models import ONLINE, Purchase

ROW_WITH_LINKS = site.RawCard(
    text="Sep 13, 2026\nGitHub Pro (monthly)\nVisa ending in 4242\n$4.00\nReceipt\nInvoice",
    links=[
        {"text": "", "href": "/account/billing/history/12345678/receipt", "label": "View receipt", "download": False},
        {"text": "", "href": "/account/billing/history/12345678/receipt.pdf", "label": "Download receipt", "download": True},
        {"text": "", "href": "/account/billing/history/12345678/invoice.pdf", "label": "Download invoice", "download": True},
        {"text": "Payment information", "href": "/settings/billing/payment_information", "label": "", "download": False},
    ])
ROW_WITHOUT_LINKS = site.RawCard(text="2026-08-13\nSponsorship to @someone\n$5.00", links=[])
ROW_NO_AMOUNT = site.RawCard(text="Date\nDescription\nAmount", links=[])


def test_a_payment_row_becomes_a_purchase_with_its_receipt_link_first():
    p = site.card_to_purchase(ROW_WITH_LINKS)
    assert p.purchase_type == ONLINE
    assert p.purchase_date == "2026-09-13"
    assert p.total == "$4.00"
    assert p.items[0].name == "GitHub Pro (monthly)"
    assert p.order_number == "12345678"
    assert p.receipt_url.endswith("/receipt.pdf"), "the download link comes before the view link"
    links = site.receipt_links(ROW_WITH_LINKS)
    assert [ln["label"] for ln in links] == ["Download receipt", "Download invoice", "View receipt"]
    assert all(ln["href"].startswith("https://github.com/") for ln in links)


def test_a_row_without_a_receipt_link_still_gets_a_stable_key():
    p = site.card_to_purchase(ROW_WITHOUT_LINKS)
    assert p.purchase_date == "2026-08-13" and p.total == "$5.00"
    assert p.items[0].name == "Sponsorship to @someone"
    assert p.order_number.startswith("p") and len(p.order_number) == 13
    assert p.order_number == site.card_to_purchase(ROW_WITHOUT_LINKS).order_number
    assert p.receipt_url == ""


def test_a_header_row_without_an_amount_is_not_a_payment():
    assert site.card_to_purchase(ROW_NO_AMOUNT) is None


def test_dates_in_the_forms_github_prints():
    assert site.parse_date("Sep 13, 2026") == "2026-09-13"
    assert site.parse_date("13 Sep 2026") == "2026-09-13"
    assert site.parse_date("2026-09-13T00:00:00Z") == "2026-09-13"
    assert site.parse_date("09/13/2026") == "2026-09-13"
    assert site.parse_date("no date here") is None


def test_nothing_that_pays_changes_a_plan_or_touches_the_card_is_safe():
    for t in ("Pay now", "Update payment method", "Add a card", "Remove", "Cancel plan", "Upgrade",
              "Downgrade", "Edit", "Sponsor", "Sign out", "Manage spending limit", "Redeem coupon"):
        assert not site.is_safe_control(t), t
    for t in ("View receipt", "Download receipt", "Download invoice", "Receipt", "Payment history", "Next"):
        assert site.is_safe_control(t), t


def test_only_github_hosts():
    assert site.is_safe_url("https://github.com/account/billing/history/1/receipt")
    assert site.is_safe_url("https://objects.githubusercontent.com/x.pdf")
    assert not site.is_safe_url("https://github.com.evil.test/x")
    assert not site.is_safe_url("http://github.com/")
    assert not site.is_safe_url("https://user@github.com/")


class _Page:
    url = "https://github.com/account/billing/history"

    def __init__(self, text, has_main=True):
        self._t = text
        self._m = has_main

    def title(self):
        return "Payment history"

    def locator(self, sel):
        page = self

        class _L:
            def count(self_):
                return 1 if (page._m or sel == "body") else 0

            @property
            def first(self_):
                return self_

            def inner_text(self_, timeout=0):
                return page._t
        return _L()


def test_the_empty_history_and_a_receipt_page_are_recognized():
    assert site.history_state(_Page("Payment history\nYou have not made any payments.\nAmounts shown in USD")) == "empty"
    assert site.history_state(_Page("Payment history\nSep 13, 2026 GitHub Pro $4.00")) == ""
    assert site.receipt_is_present(_Page("Receipt\nGitHub Pro (monthly) $4.00\nTotal $4.00\nPaid Sep 13, 2026"))
    assert not site.receipt_is_present(_Page("Settings\nBilling and licensing"))


def test_receipt_lines_give_items_without_the_totals():
    p = site.extract_details(_Page("Receipt\nGitHub Pro (monthly) $4.00\nCopilot Pro $10.00\nSubtotal $14.00\nTotal $14.00"),
                             Purchase(purchase_type=ONLINE, order_number="x"))
    assert [i.name for i in p.items] == ["GitHub Pro (monthly)", "Copilot Pro"]


def test_the_diagnose_file_masks_numbers_emails_and_handles():
    assert site.mask_text("Sponsorship to @someone, card 4242, pat@example.com, Sep 13, 2026") == \
        "Sponsorship to @<user>, card ####, <email>, Sep ##, ####"
    assert site.mask_href("/account/billing/history/12345678/receipt.pdf?x=1") == "/account/billing/history/<id>/receipt.pdf?..."
    assert site.mask_href("https://github.com/settings/billing") == "https://github.com/settings/billing"


def test_two_payments_on_one_day_get_two_filenames():
    """GitHub's rows carry no description, so the ID column is what tells
    two payments apart. It leads the filename (#43)."""
    row = site.RawCard(text="2026-09-21\n1EAX6IX2\nVisa ending in 4242\n$4.00\nSuccess",
                       links=[{"text": "", "href": "/account/receipt/ch_123", "label": "", "download": False}])
    p = site.card_to_purchase(row)
    assert p.items[0].name == "1EAX6IX2"
    assert site.payment_id(p) == "1EAX6IX2"
    other = site.card_to_purchase(site.RawCard(text="2026-09-21\n0TMCZ5RM\nVisa ending in 4242\n$10.00\nSuccess", links=[]))
    assert site.payment_id(other) == "0TMCZ5RM" and site.payment_id(other) != site.payment_id(p)
    assert site.payment_id(site.card_to_purchase(site.RawCard(text="2026-08-13\nGitHub Pro\n$4.00", links=[]))) == ""
