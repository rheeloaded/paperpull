"""The Costco site layer, which was written without a Costco account.

Most of what this app believes about a signed-in Costco page is a guess,
and a test cannot make a guess true. What it can do is hold the parts
that do not depend on guessing. A purchase read off a card becomes the
right kind of Purchase. Nothing that spends money, renews a membership or
starts a return is ever a control this app would touch. No URL off
costco.com is ever opened. A diagnostics file carries shapes and not
values.

Every record here is made up. Nothing in them is a real purchase.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

# What _READ_HISTORY_JS hands back, which is deliberately shaped like the
# JSON record a real API would give. When a tester's recording shows
# Costco's own call, these stop being synthetic and only the reader
# changes.
CARD_WAREHOUSE = {
    "orderNumber": "7741234567",
    "href": "https://www.costco.com/myaccount/orders/7741234567",
    "createdDateTime": "2026-09-13",
    "total": "$42.17",
    "status": "",
    "purchaseType": "WAREHOUSE",
    "cardText": "In-Warehouse 09/13/2026 $42.17 Springfield #123",
}
CARD_ONLINE = {
    "orderNumber": "220026789012",
    "href": "https://www.costco.com/myaccount/orders/220026789012",
    "createdDateTime": "2026-09-10",
    "total": "$61.50",
    "status": "",
    "purchaseType": "ONLINE",
    "cardText": "Online Order Sep 10, 2026 $61.50 Delivered",
}
CARD_CANCELLED = dict(CARD_ONLINE, orderNumber="220026789055", status="CANCELLED")


# -- a card becomes a purchase -------------------------------------------------

def test_a_warehouse_card_becomes_an_in_store_purchase():
    p = site.record_to_purchase(CARD_WAREHOUSE)
    assert p.purchase_type == IN_STORE
    assert p.order_number == "7741234567"
    assert p.purchase_date == "2026-09-13"
    assert p.total == "$42.17"
    assert p.store_info == "In-Warehouse"


def test_an_online_card_becomes_an_online_purchase():
    p = site.record_to_purchase(CARD_ONLINE)
    assert p.purchase_type == ONLINE
    assert p.store_info == "Online"
    assert p.total == "$61.50"


def test_the_link_the_page_drew_is_kept_over_one_this_app_would_assemble():
    """Where a Costco receipt lives is the main thing this app does not
    know. An href the site itself rendered is the only trustworthy
    answer until a recording gives a better one."""
    p = site.record_to_purchase(CARD_WAREHOUSE)
    assert p.receipt_url == CARD_WAREHOUSE["href"]
    assert p.details_url == CARD_WAREHOUSE["href"]


def test_an_href_that_is_not_costco_is_dropped_not_followed():
    evil = dict(CARD_WAREHOUSE, href="https://costco.com.evil.test/steal")
    p = site.record_to_purchase(evil)
    assert "evil.test" not in p.receipt_url
    assert p.receipt_url.startswith("https://www.costco.com/")


def test_a_cancelled_card_is_not_pending():
    assert not site.record_is_pending(CARD_CANCELLED)
    assert site.record_to_purchase(CARD_CANCELLED).status == "Canceled"


def test_a_card_with_no_key_is_dropped_and_a_bad_key_too():
    assert site.record_to_purchase({"purchaseType": "ONLINE"}) is None
    assert site.record_to_purchase({"orderNumber": "../../etc"}) is None
    assert site.record_to_purchase({"orderNumber": "a" * 100}) is None


def test_the_card_text_is_kept_as_the_summary_so_a_tester_can_check_it():
    p = site.record_to_purchase(CARD_WAREHOUSE)
    assert p.summary.startswith("In-Warehouse 09/13/2026")


def test_money_in_every_spelling_a_card_might_use():
    assert site.money_from_api("$12.34") == "$12.34"
    assert site.money_from_api("USD 12.34") == "$12.34"
    assert site.money_from_api(1234.5) == "$1,234.50"
    assert site.money_from_api(None) == ""
    assert site.money_from_api("free") == ""


def test_costcos_own_words_route_to_the_right_folder():
    for word in ("WAREHOUSE", "IN_WAREHOUSE", "GAS", "FUEL", "PHARMACY", "OPTICAL"):
        assert site.purchase_kind(word) == IN_STORE, word
    for word in ("ONLINE", "SHIP", "DELIVERY", "SAME_DAY", "TRAVEL", "PHOTO"):
        assert site.purchase_kind(word) == ONLINE, word
    assert site.purchase_kind("SOMETHING_COSTCO_ADDED") == ONLINE
    assert site.purchase_label("GAS") == "Gas Station"
    assert site.purchase_label("SOMETHING_COSTCO_ADDED") == "Something Costco Added"


# -- the URLs ------------------------------------------------------------------

def test_the_orders_route_carries_the_client_id_that_is_the_same_for_everybody():
    """VERIFIED. The sign-in redirect hands that UUID back as client_id,
    which is what proves it is not an account id."""
    assert site.MYACCOUNT_APP_ID == "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
    assert site.ORDERS_URL.endswith("/ordersandpurchases")
    assert site.MYACCOUNT_APP_ID in site.ORDERS_URL


def test_every_candidate_route_is_on_costco():
    for url in site.ORDER_ROUTES:
        assert site.is_safe_url(url), url


def test_only_costco_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.costco.com/myaccount/")
    assert site.is_safe_url("https://signin.costco.com/oauth2/v2.0/authorize")
    assert not site.is_safe_url("https://costco.com.evil.test/x")
    assert not site.is_safe_url("http://www.costco.com/")
    assert not site.is_safe_url("https://user@costco.com/")
    assert not site.is_safe_url("")


def test_a_route_off_costco_is_refused_rather_than_opened():
    class _P:
        url = ""

        def goto(self, *a, **k):
            raise AssertionError("should never have navigated")

    for bad in ("https://evil.test/orders", "http://www.costco.com/x"):
        try:
            site.goto_orders_route(_P(), bad)
        except ValueError:
            continue
        raise AssertionError("opened " + bad)


# -- the guards ----------------------------------------------------------------

def test_nothing_that_spends_renews_returns_or_prints_is_safe():
    for name in ("Add to Cart", "Add All to Cart", "Buy It Again", "Reorder",
                 "Checkout", "Start a Return", "Return Item", "Request a Refund",
                 "Renew Membership", "Auto Renew", "Upgrade Membership",
                 "Cancel Order", "Cancel Membership", "Pay Now", "Print",
                 "Contact Us", "Customer Service", "Chat", "Sign Out"):
        assert not site.is_safe_control(name), name


def test_the_controls_that_only_look_at_a_purchase_are_safe():
    for name in ("View Receipt", "View Order Details", "Order Details",
                 "Purchase History", "Orders & Purchases", "In-Warehouse",
                 "Online Orders", "View More", "Next Page"):
        assert site.is_safe_control(name), name


def test_a_control_with_no_name_is_never_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("   ")


# -- reading the page ----------------------------------------------------------

class _Page:
    """Enough of a page for the text-reading helpers."""

    def __init__(self, body, url="https://www.costco.com/myaccount/", has_area=True):
        self._body = body
        self._has = has_area
        self.url = url

    def title(self):
        return "Costco"

    def locator(self, sel):
        page = self

        class _L:
            def count(self_):
                if sel == "body":
                    return 1
                if "password" in sel:
                    return 1 if "Password" in page._body else 0
                return 1 if page._has else 0

            @property
            def first(self_):
                return self_

            def inner_text(self_, timeout=0):
                return page._body

            def all(self_):
                return []
        return _L()


def test_the_sign_in_host_alone_says_signed_out():
    """VERIFIED. Opening the orders route signed out lands on the B2C
    authorize endpoint, so the URL answers this without reading the page."""
    signin = _Page("anything", url="https://signin.costco.com/e07/oauth2/v2.0/authorize")
    assert site.looks_signed_out(signin)
    assert site.looks_signed_out(_Page("x", url="https://www.costco.com/LogonForm?langId=-1"))


def test_a_password_box_says_signed_out_even_on_costco_itself():
    assert site.looks_signed_out(_Page("Sign In\nEmail Address\nPassword"))


def test_a_page_of_orders_does_not_say_signed_out():
    page = _Page("Orders & Purchases\nIn-Warehouse\n09/13/2026 $42.17")
    assert not site.looks_signed_out(page)


def test_the_words_for_an_empty_list_and_an_unlinked_membership():
    assert site.history_state(_Page("You don't have any orders yet.")) == "empty"
    assert site.history_state(_Page("Add your membership to see warehouse receipts")) \
        == "no-membership"
    assert site.history_state(_Page("Orders & Purchases\n09/13/2026 $42.17")) == ""


def test_the_waiting_room_and_the_bot_check_are_both_called_out_by_name():
    """Costco runs Akamai and a queue-it waiting room. Both look like a
    page that never arrives, and a tester should be told which."""
    assert site.detect_security_challenge(_Page("You are now in line"))
    assert site.detect_security_challenge(_Page("Press and hold to confirm"))
    assert site.detect_security_challenge(_Page("Access Denied"))
    assert not site.detect_security_challenge(_Page("Orders & Purchases"))


# -- the diagnostics file ------------------------------------------------------

def test_the_diagnose_file_keeps_shapes_and_masks_values():
    masked = site.mask_json([CARD_WAREHOUSE, CARD_ONLINE, CARD_CANCELLED,
                             dict(CARD_ONLINE, orderNumber="220026789077")])
    assert len(masked) == 4 and masked[3] == "... 1 more"
    first = masked[0]
    assert first["purchaseType"] == "WAREHOUSE"
    assert "7741234567" not in site.to_json(masked)
    assert "42.17" not in site.to_json(masked)


def test_masking_takes_numbers_emails_and_the_owners_name():
    site.set_private_words(["Alex Morgan"])
    try:
        out = site.mask_text("Alex Morgan card 4111111111111111 pat@example.com")
        assert "Alex Morgan" not in out
        assert "4111111111111111" not in out
        assert "pat@example.com" not in out
    finally:
        site.set_private_words([])
