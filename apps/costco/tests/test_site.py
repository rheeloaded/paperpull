"""The Costco site layer, written from a member's recording.

The first version of this file tested guesswork. This one tests what a
recording established, so the things it holds are things Costco actually
does. Issue #47 has the recording.

The parts that still cannot be tested without an account are the ones
that need a live page, and those are held by shape instead. Nothing that
spends money, renews a membership or starts a return is ever a control
this app would touch. No URL off costco.com is ever opened. Print Receipt
and Print Invoice are never pressed, because both call window.print() and
open a dialog no program can dismiss.

Every record here is made up. Nothing in them is a real purchase.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_site as site
from paperpull_core.models import IN_STORE, ONLINE, Purchase

# What read_rows hands back. The warehouse row has no href and no number,
# because Costco's list gives it neither, which is the whole reason
# warehouse_key exists.
ROW_WAREHOUSE = {
    "purchaseType": "WAREHOUSE",
    "href": "",
    "createdDateTime": "2026-08-30",
    "total": "$50.59",
    "status": "",
    "where": "FAIRFAX",
    "index": 0,
    "cardText": "In-Warehouse 08/30/2026 FAIRFAX Total $50.59 View Receipt",
}
ROW_ONLINE = {
    "purchaseType": "ONLINE",
    "href": ("https://www.costco.com/myaccount/#/app/"
             "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf/orderdetails/220026789012"),
    "createdDateTime": "2026-05-14",
    "total": "$61.50",
    "status": "",
    "where": "",
    "index": 0,
    "cardText": "Order Placed May 14, 2026 Total $61.50 Delivered View Order Details",
}


# -- a row becomes a purchase --------------------------------------------------

def test_a_warehouse_row_becomes_an_in_store_purchase():
    p = site.record_to_purchase(ROW_WAREHOUSE)
    assert p.purchase_type == IN_STORE
    assert p.purchase_date == "2026-08-30"
    assert p.total == "$50.59"
    assert p.store_info == "In-Warehouse"


def test_a_warehouse_receipt_is_keyed_by_what_its_row_shows():
    """Costco's list gives a warehouse receipt no number and no address,
    so its identity is made from the date, the total and the warehouse."""
    p = site.record_to_purchase(ROW_WAREHOUSE)
    assert p.order_number == "wh-20260830-5059-FAIRFAX"


def test_two_warehouse_rows_that_differ_get_different_keys():
    a = site.record_to_purchase(ROW_WAREHOUSE)
    b = site.record_to_purchase(dict(ROW_WAREHOUSE, total="$12.00"))
    c = site.record_to_purchase(dict(ROW_WAREHOUSE, createdDateTime="2026-08-31"))
    d = site.record_to_purchase(dict(ROW_WAREHOUSE, where="CHANTILLY"))
    assert len({a.order_number, b.order_number, c.order_number, d.order_number}) == 4


def test_a_warehouse_row_with_nothing_on_it_is_dropped():
    """Rather than every empty row collapsing onto one key."""
    assert site.record_to_purchase({"purchaseType": "WAREHOUSE"}) is None


def test_an_online_row_is_keyed_by_the_order_number_in_its_link():
    p = site.record_to_purchase(ROW_ONLINE)
    assert p.purchase_type == ONLINE
    assert p.order_number == "220026789012"
    assert p.details_url == ROW_ONLINE["href"]


def test_an_href_that_is_not_costco_is_dropped_not_followed():
    """The order number is read out of the path either way, which is
    harmless, and the address itself is thrown away and rebuilt on
    costco.com."""
    evil = dict(ROW_ONLINE,
                href="https://costco.com.evil.test/orderdetails/220026789012")
    p = site.record_to_purchase(evil)
    assert p.order_number == "220026789012"
    assert "evil.test" not in p.details_url
    assert "evil.test" not in p.receipt_url
    assert p.details_url.startswith("https://www.costco.com/")


def test_an_href_too_short_to_carry_an_order_number_yields_no_purchase():
    evil = dict(ROW_ONLINE, href="https://costco.com.evil.test/orderdetails/1")
    assert site.record_to_purchase(evil) is None


def test_which_tab_a_purchase_came_from_is_kept():
    p = site.record_to_purchase(dict(ROW_WAREHOUSE, tab="Warehouse"))
    assert p.fulfillment == "Warehouse"


def test_a_warehouse_receipt_is_never_pending():
    """It is a thing that already happened at a till."""
    assert not site.record_is_pending(ROW_WAREHOUSE)


def test_an_online_order_still_on_its_way_is_pending():
    for word in ("Processing", "In Transit", "Shipping soon", "On its way"):
        row = dict(ROW_ONLINE, cardText="Order Placed May 14, 2026 " + word)
        assert site.record_is_pending(row), word


def test_a_delivered_order_is_not_pending():
    assert not site.record_is_pending(ROW_ONLINE)


def test_a_cancelled_order_is_not_pending():
    assert not site.record_is_pending(dict(ROW_ONLINE, status="CANCELLED"))


def test_costcos_own_words_route_to_the_right_folder():
    for word in ("WAREHOUSE", "IN_WAREHOUSE", "GAS", "GASSTATION", "CARWASH",
                 "GASANDCARWASH", "PHARMACY", "OPTICAL"):
        assert site.purchase_kind(word) == IN_STORE, word
    for word in ("ONLINE", "SHIP", "DELIVERY", "SAME_DAY", "TRAVEL", "PHOTO"):
        assert site.purchase_kind(word) == ONLINE, word
    assert site.purchase_kind("SOMETHING_COSTCO_ADDED") == ONLINE
    assert site.purchase_label("GASSTATION") == "Gas Station"
    assert site.purchase_label("CARWASH") == "Car Wash"


# -- the quarters --------------------------------------------------------------

def test_a_quarter_covers_its_three_months():
    """SEEN. The picker holds quarters, "2026 April - June" and so on."""
    for day in ("2026-04-01", "2026-05-14", "2026-06-30"):
        assert site.range_covers("2026 April - June", day), day


def test_a_quarter_does_not_cover_the_month_either_side():
    assert not site.range_covers("2026 April - June", "2026-03-31")
    assert not site.range_covers("2026 April - June", "2026-07-01")


def test_a_quarter_does_not_cover_another_year():
    assert not site.range_covers("2026 April - June", "2025-05-14")


def test_the_option_it_opens_on_covers_nothing_in_particular():
    """"Last 3 Months" moves, so it is never chosen on purpose."""
    assert not site.range_covers("Last 3 Months", "2026-05-14")
    assert not site.range_covers("", "2026-05-14")


def test_a_date_that_is_not_a_date_does_not_raise():
    assert not site.range_covers("2026 April - June", "")
    assert not site.range_covers("2026 April - June", "sometime")


# -- the URLs ------------------------------------------------------------------

def test_the_orders_route_carries_the_client_id_that_is_the_same_for_everybody():
    assert site.MYACCOUNT_APP_ID == "4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf"
    assert site.ORDERS_URL.endswith("/ordersandpurchases")


def test_an_order_details_url_is_built_from_the_order_number():
    assert site.details_url("220026789012").endswith("/orderdetails/220026789012")
    assert site.is_safe_url(site.details_url("220026789012"))


def test_only_costco_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.costco.com/myaccount/")
    assert site.is_safe_url("https://signin.costco.com/oauth2/v2.0/authorize")
    # The GraphQL host, which is a different subdomain and still Costco.
    assert site.is_safe_url(site.ORDER_API)
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
                 "Cancel Order", "Cancel Membership", "Pay Now",
                 "Contact Us", "Customer Service", "Chat", "Sign Out"):
        assert not site.is_safe_control(name), name


def test_the_two_print_controls_are_refused_although_they_are_the_right_ones():
    """Both call window.print(), SEEN in the recording, which opens a
    dialog no program can answer or dismiss. The app renders the receipt
    itself instead."""
    assert not site.is_safe_control("Print Receipt")
    assert not site.is_safe_control("Print Invoice")


def test_every_control_the_recording_shows_this_app_using_is_allowed():
    for name in ("Warehouse", "Online", "View Receipt", "View Order Details",
                 "Showing"):
        assert site.is_safe_control(name), name


def test_a_control_with_no_name_is_never_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("   ")


def test_opening_a_tab_by_a_name_the_guard_refuses_raises():
    class _P:
        url = site.ORDERS_URL

        def get_by_role(self, *a, **k):
            raise AssertionError("should never have looked for it")

    for bad in ("Renew Membership", "Sign Out", ""):
        try:
            site.open_tab(_P(), bad)
        except ValueError:
            continue
        raise AssertionError("looked for " + bad)


# -- reading the page ----------------------------------------------------------

class _Page:
    """Enough of a page for the text-reading helpers."""

    def __init__(self, body, url="https://www.costco.com/myaccount/",
                 has_dialog=True):
        self._body = body
        self._dialog = has_dialog
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
                if "dialog" in sel:
                    return 1 if page._dialog else 0
                return 1 if page._dialog else 0

            @property
            def first(self_):
                return self_

            def inner_text(self_, timeout=0):
                return page._body

            def all(self_):
                return []
        return _L()


def test_the_sign_in_host_alone_says_signed_out():
    signin = _Page("x", url="https://signin.costco.com/e07/oauth2/v2.0/authorize")
    assert site.looks_signed_out(signin)


def test_a_password_box_says_signed_out_even_on_costco_itself():
    assert site.looks_signed_out(_Page("Sign In\nEmail Address\nPassword"))


def test_a_page_of_orders_does_not_say_signed_out():
    assert not site.looks_signed_out(
        _Page("Orders & Purchases\nWarehouse\nOnline\n08/30/2026 $50.59"))


def test_the_words_for_an_empty_tab_and_an_unlinked_membership():
    assert site.history_state(_Page("You don't have any orders yet.")) == "empty"
    assert site.history_state(
        _Page("Add your membership to see warehouse receipts")) == "no-membership"
    assert site.history_state(_Page("Warehouse\n08/30/2026 $50.59")) == ""


def test_the_waiting_room_and_the_bot_check_are_both_called_out_by_name():
    assert site.detect_security_challenge(_Page("You are now in line"))
    assert site.detect_security_challenge(_Page("Press and hold to confirm"))
    assert site.detect_security_challenge(_Page("Access Denied"))
    assert not site.detect_security_challenge(_Page("Orders & Purchases"))


def test_a_receipt_is_on_screen_when_a_dialog_is_up():
    """SEEN. A warehouse receipt opens in a dialog on the same page and
    never navigates, so there is no address to recognise it by."""
    assert site.on_receipt_page(_Page("Total $50.59"))
    assert not site.on_receipt_page(_Page("Orders", has_dialog=False))


def test_a_receipt_is_on_screen_on_the_online_print_view():
    page = _Page("Total $61.50", has_dialog=False,
                 url="https://www.costco.com/OrderDetailPrintView?orderId=1")
    assert site.on_receipt_page(page)


def test_a_dialog_with_money_in_it_counts_as_a_rendered_receipt():
    assert site.receipt_is_present(_Page("SUBTOTAL 49.06 TOTAL $50.59"))
    assert not site.receipt_is_present(_Page("Loading your receipt"))


def test_the_pages_own_words_for_a_receipt_that_would_not_load():
    assert site.receipt_failed(_Page("There was a problem loading this receipt"))
    assert not site.receipt_failed(_Page("Total $50.59"))


# -- the print view, read and never pressed ------------------------------------

class _LinkPage:
    def __init__(self, href):
        self.url = "https://www.costco.com/myaccount/"
        self._href = href
        self.clicked = False

    def locator(self, sel):
        page = self

        class _L:
            def count(self_):
                return 1 if page._href is not None else 0

            @property
            def first(self_):
                return self_

            def get_attribute(self_, name):
                return page._href

            def click(self_, **k):
                page.clicked = True
                raise AssertionError("Print Invoice must never be clicked")
        return _L()


def test_the_print_invoice_link_is_read_not_pressed():
    """Pressing it once navigates, and pressing it again on the page it
    lands on calls window.print(). SEEN, twice, in the recording."""
    page = _LinkPage("/OrderDetailPrintView?orderId=220026789012")
    url = site.print_view_url(page)
    assert url == "https://www.costco.com/OrderDetailPrintView?orderId=220026789012"
    assert not page.clicked


def test_a_print_invoice_link_pointing_somewhere_else_is_ignored():
    assert site.print_view_url(_LinkPage("https://evil.test/OrderDetailPrintView")) == ""
    assert site.print_view_url(_LinkPage("/some/other/page")) == ""
    assert site.print_view_url(_LinkPage(None)) == ""


def test_the_isolation_script_hides_the_dialogs_own_controls():
    """A printed receipt with a Print Receipt link and a Close button in
    it looks like a screenshot of a website."""
    js = site._ISOLATE_RECEIPT_JS
    assert "printBtn" in js
    assert "button" in js
    assert "display = 'none'" in js


def test_the_isolation_script_lets_the_dialog_grow_to_its_full_height():
    """A dialog keeps its own scroll, so printToPDF would otherwise
    capture one screen of a receipt that runs to two pages."""
    js = site._ISOLATE_RECEIPT_JS
    assert "maxHeight" in js and "overflow" in js


# -- what runs where ----------------------------------------------------------

# Playwright understands these on top of CSS. The browser does not, and
# a selector carrying one reaches querySelectorAll as a syntax error.
PLAYWRIGHT_ONLY = (":has-text(", ":has(", ":text(", ":text-is(",
                   ":visible", ":nth-match(", ">>")


def test_nothing_handed_to_the_browser_is_a_playwright_selector():
    """Discovery runs inside the page, so what it hands to
    querySelectorAll has to be plain CSS. A live run against a real
    account is what found that out, after the first version passed
    `button:has-text('View Receipt')` straight into the browser and
    every tab came back empty."""
    import inspect
    src = inspect.getsource(site.read_rows)
    assert "RECEIPT_CONTROL_TEXT" in src, "it is matching on text now"
    for bad in PLAYWRIGHT_ONLY:
        assert bad not in site.FALLBACK["order_link"], bad


def test_a_control_is_matched_by_what_it_says():
    matcher = re.compile(site.RECEIPT_CONTROL_TEXT, re.I)
    assert matcher.search("View Receipt")
    assert matcher.search("view receipt")
    assert not matcher.search("Print Receipt")


def test_the_selectors_meant_for_playwright_are_only_used_there():
    """These carry :has-text on purpose, and page.locator is the only
    thing that may see them."""
    import inspect
    for name in ("receipt_button", "dialog_close", "print_invoice"):
        assert ":has-text(" in site.FALLBACK[name], name
    src = inspect.getsource(site)
    assert 'page.evaluate(_READ_ROWS_JS' in src
    assert 'FALLBACK["receipt_button"]] ) or []' not in src


# -- the diagnostics file ------------------------------------------------------

def test_the_diagnose_file_keeps_shapes_and_masks_values():
    masked = site.mask_json([ROW_WAREHOUSE, ROW_ONLINE])
    text = site.to_json(masked)
    assert "50.59" not in text
    assert "220026789012" not in text
    assert "WAREHOUSE" in text


def test_masking_takes_numbers_emails_and_the_owners_name():
    site.set_private_words(["Alex Morgan"])
    try:
        out = site.mask_text("Alex Morgan card 4111111111111111 pat@example.com")
        assert "Alex Morgan" not in out
        assert "4111111111111111" not in out
        assert "pat@example.com" not in out
    finally:
        site.set_private_words([])


def test_the_survey_names_the_api_it_does_not_call():
    """A reader of a diagnostics file should be able to tell the endpoint
    exists from the fact that this app does not use it."""
    assert "ecom-api.costco.com" in site.ORDER_API
    assert "graphql" in site.ORDER_API


def test_the_module_says_which_facts_came_from_the_recording():
    """Every claim about a signed-in page is marked, so the next person
    can tell what was observed from what was assumed."""
    doc = site.__doc__ or ""
    assert "SEEN" in doc
    assert doc.count("SEEN") >= 5
    assert not re.search(r"^GUESS", doc, re.M), "the guesses are gone now"
