"""Whether the page in front of an app is the purchase it is about to save.

The pieces every receipt app's page check is built from. The address has
to name the purchase where the provider keys it and nowhere else, since a
sign-in page carries the purchase's own address in its return address. A
page's numbers have to be the purchase's and at least one. And the page is
read as the screen or the printer lays it out, as asked, whatever an
earlier print left the tab in. Every number here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import page_check  # noqa: E402
from paperpull_core.page_check import (NAMES_ANOTHER, NAMES_NONE, address_names,  # noqa: E402
                                       names_only, page_text, plain, same_address)


def test_a_number_is_its_letters_and_digits():
    assert plain("1000000-00000031") == plain("100000000000031") == "100000000000031"
    assert plain("7q2wx5a") == "7Q2WX5A"
    assert plain(None) == ""


def test_the_path_names_a_purchase_by_a_segment_of_its_own():
    assert address_names("https://shop.example/orders/100000000000031", "100000000000031")
    assert address_names("https://shop.example/orders/stores/1000-0000-0000-0031?x=1",
                         "1000-0000-0000-0031")
    assert address_names("https://shop.example/orders/1000-0000-0000-0031/receipts",
                         "1000000000000031")
    assert not address_names("https://shop.example/orders/1000000000000312", "100000000000031"), \
        "a longer number that begins with this one is another purchase"
    assert not address_names("https://shop.example/orders", "100000000000031")


def test_a_return_address_never_names_the_purchase():
    """A sign-in page carries the page it came from in its query, the
    purchase's own address included."""
    signin = ("https://shop.example/account/login?returnUrl=%2Forders%2F100000000000031"
              "&orderID=100000000000031")
    assert not address_names(signin, "100000000000031")
    assert not address_names(signin, "100000000000031", query="orderId2")


def test_the_one_query_parameter_a_provider_keys_on_counts():
    url = "https://shop.example/gp/css/summary/print.html?orderID=112-1000000-1000031"
    assert address_names(url, "112-1000000-1000031", query="orderID")
    assert address_names(url, "112-1000000-1000031", query="orderid"), "its name in any case"
    assert not address_names(url, "112-1000000-1000031"), "only when it is asked for"
    assert not address_names(url, "112-1000000-1000047", query="orderID")


def test_nothing_names_a_purchase_with_no_number():
    assert not address_names("https://shop.example/orders/", "")


def test_the_same_address_as_a_provider_might_still_write_it():
    link = "https://shop.example/account/receipt/30000001"
    assert same_address(link, link)
    assert same_address("https://SHOP.example/account/receipt/30000001/", link)
    assert same_address("http://shop.example/account/receipt/30000001", link)
    assert same_address(link + "?locale=en", link), "a parameter added along the way"
    assert same_address(link + "#top", link), "a fragment the link did not have"


def test_another_address_is_not_the_same_one():
    link = "https://shop.example/account/receipt/30000001?v=2"
    assert not same_address("https://shop.example/account/billing/history", link)
    assert not same_address("https://shop.example/account/receipt/30000001", link), \
        "a parameter the link had is missing"
    assert not same_address("https://shop.example/account/receipt/30000001?v=3", link)
    assert not same_address("https://other.example/account/receipt/30000001?v=2", link)
    assert not same_address("https://shop.example:8443/account/receipt/30000001?v=2", link)
    assert not same_address("", link)


def test_a_page_that_routes_by_its_fragment_names_its_purchase_there():
    link = "https://shop.example/orders.html#/order/2026000031"
    assert same_address(link, link)
    assert not same_address("https://shop.example/orders.html#/order/2026000047", link)
    assert not same_address("https://shop.example/orders.html", link)


def test_a_page_names_only_this_purchase():
    """Given the numbers an app read off the page, dashes and all."""
    assert names_only(["1000000-00000031"], "100000000000031") == ""
    assert names_only(["1000000-00000031", "100000000000031"], "100000000000031") == ""


def test_a_page_naming_another_purchase_or_none_is_not_this_ones():
    assert names_only([], "100000000000031") == NAMES_NONE
    assert names_only(["", "  "], "100000000000031") == NAMES_NONE
    assert names_only(["100000000000047"], "100000000000031") == NAMES_ANOTHER
    assert names_only(["100000000000031", "100000000000047"], "100000000000031") == NAMES_ANOTHER, \
        "a list names this purchase among others"


def test_the_reasons_carry_no_value_from_any_page():
    """They reach the record, the console and a failure file."""
    for reason in (page_check.NOT_ITS_ADDRESS, page_check.NAMES_ANOTHER,
                   page_check.NAMES_NONE, page_check.IS_THE_LIST):
        assert not any(ch.isdigit() for ch in reason)
        assert reason == reason.lower()


PAGE = """<!doctype html><html><head><style>
@media print { .screen-only { display: none } }
@media screen { .print-only { display: none } }
</style></head><body>
<p class="screen-only">Order details #100000000000031</p>
<p class="print-only">Order# 1000000-00000031</p>
</body></html>"""

MEDIA = "() => matchMedia('print').matches ? 'print' : 'screen'"


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    pg.set_content(PAGE)
    yield pg
    browser.close()
    driver.stop()


def test_a_page_is_read_as_the_printer_lays_it_out(page):
    assert "Order# 1000000-00000031" in page_text(page, "print")
    assert "Order details" not in page_text(page, "print")


def test_a_page_is_read_as_the_screen_lays_it_out(page):
    assert "Order details #100000000000031" in page_text(page, "screen")
    assert "Order#" not in page_text(page, "screen")


def test_a_page_is_put_back_the_way_it_was(page):
    """Printing a page leaves the tab in print media, so an app's second
    purchase meets a page in print. It is read as asked either way, and
    left as it was found."""
    page_text(page, "print")
    assert page.evaluate(MEDIA) == "screen"
    page.emulate_media(media="print")
    assert "Order details" in page_text(page, "screen")
    assert page.evaluate(MEDIA) == "print"


def test_a_page_that_cannot_be_read_answers_nothing():
    class Gone:
        url = "https://shop.example/orders/100000000000031"

        def evaluate(self, script):
            raise RuntimeError("Target page, context or browser has been closed")

        def emulate_media(self, media=None):
            raise RuntimeError("Target page, context or browser has been closed")

        def locator(self, selector):
            raise RuntimeError("Target page, context or browser has been closed")

    assert page_text(Gone(), "print") == ""
