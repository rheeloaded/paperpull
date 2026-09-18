"""One Amazon app, many stores. `marketplace` in config.json picks the store,
and with it the currency, the date order and whether to ask for English.
Nothing about the order-history or printable-summary paths changes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_site as site


@pytest.fixture(autouse=True)
def back_to_dot_com():
    yield
    site.set_marketplace(None)


def test_the_default_is_amazon_com_and_nothing_asks_for_a_language():
    assert site.set_marketplace(None) == "amazon.com"
    assert site.URLS["orders"] == "https://www.amazon.com/gp/css/order-history"
    assert site.print_invoice_url("111-1") == "https://www.amazon.com/gp/css/summary/print.html?orderID=111-1"
    assert site.ALLOWED_HOSTS == {"amazon.com"} and site.CURRENCY == "$" and not site.DAY_FIRST


def test_a_store_moves_every_url_and_the_allowlist_with_it():
    site.set_marketplace("amazon.co.uk")
    assert site.URLS["home"] == "https://www.amazon.co.uk/"
    assert site.orders_url(2025, 10) == "https://www.amazon.co.uk/gp/css/order-history?timeFilter=year-2025&startIndex=10"
    assert site.is_safe_url("https://www.amazon.co.uk/gp/css/summary/print.html?orderID=1")
    assert not site.is_safe_url("https://www.amazon.com/gp/css/order-history")   # the old store is now foreign
    assert not site.is_safe_url("https://www.amazon.co.uk.evil.example/")


def test_a_store_that_is_not_in_english_asks_for_english_on_every_url():
    site.set_marketplace("amazon.de")
    assert site.URLS["orders"].endswith("/gp/css/order-history?language=en_GB")
    assert site.orders_url(2024) == "https://www.amazon.de/gp/css/order-history?timeFilter=year-2024&language=en_GB"
    assert site.print_invoice_url("302-1") == "https://www.amazon.de/gp/css/summary/print.html?orderID=302-1&language=en_GB"
    assert site.order_details_url("302-1").endswith("&language=en_GB")


@pytest.mark.parametrize("bad", ["evil.com", "amazon.com.evil.example", "www.amazon.xx", "https://amazon.com/../"])
def test_an_unknown_store_is_refused_not_guessed(bad):
    with pytest.raises(ValueError) as e:
        site.set_marketplace(bad)
    assert "amazon.co.uk" in str(e.value)          # the message lists what is allowed
    assert site.ALLOWED_HOSTS == {"amazon.com"}    # and nothing changed


def test_lenient_spellings_of_a_known_store_are_fine():
    assert site.set_marketplace(" https://www.Amazon.co.uk/ ") == "amazon.co.uk"


# -- money ------------------------------------------------------------------------

def test_amounts_are_found_by_shape_whatever_the_store_prints():
    assert site.find_amounts("Grand Total: $1,234.56. Tax $0.00, refund -$5.00") == [1234.56, 0.0, -5.0]
    assert site.find_amounts("Summe 12,99 € und 1.234,56 €") == [12.99, 1234.56]
    assert site.find_amounts("Total £9.99 and 129,00 kr and 49,99 zł") == [9.99, 129.0, 49.99]
    assert site.find_amounts("Order 112-3456789-1234567 placed 5 January 2025") == []   # no bare numbers
    assert site.find_amounts("$12.999") == []                                            # three decimals is not money


def test_money_is_written_back_in_one_canonical_form():
    site.set_marketplace("amazon.de")
    assert site.parse_money("Summe: 1.234,56 €") == "€1,234.56"
    assert site.parse_subtotal("Item(s) Subtotal: 344,23 €") == 344.23
    assert site.money_value("€1,234.56") == 1234.56
    site.set_marketplace("amazon.co.uk")
    assert site.parse_money("Grand Total: £9.99") == "£9.99"
    assert site.fmt_money(-5) == "-£5.00"


def test_amount_after_a_label_skips_a_label_with_no_amount_near_it():
    text = "Total items: 3\nOrder Total: $43.99"
    assert site.amount_after(r"total", text, 20) == "$43.99"
    assert site.amount_after(r"grand\s+total", text) == ""


# -- dates ------------------------------------------------------------------------

def test_dates_in_three_orders_and_two_languages():
    assert site.parse_date("Order Placed: January 5, 2025") == "2025-01-05"
    assert site.parse_date("Order placed 5 January 2025") == "2025-01-05"
    assert site.parse_date("Bestellt am 5. Januar 2025") == "2025-01-05"
    assert site.parse_date("Bestellt am 3. März 2024") == "2024-03-03"
    assert site.parse_date("Bestellung vom 12. Dezember 2023") == "2023-12-12"
    assert site.parse_date("Ordered 14 Oct 2025") == "2025-10-14"


def test_a_slash_date_is_read_in_the_order_the_store_uses():
    assert site.parse_date("05/01/2025") == "2025-05-01"       # amazon.com, month first
    site.set_marketplace("amazon.co.uk")
    assert site.parse_date("05/01/2025") == "2025-01-05"       # day first
    site.set_marketplace("amazon.de")
    assert site.parse_date("05.01.2025") == "2025-01-05"
    assert site.parse_date("31/12/2025") == "2025-12-31"
    assert site.parse_date("13/13/2025") is None


# -- items on a euro summary ------------------------------------------------------

def test_whole_foods_style_pairs_work_in_euros_too():
    site.set_marketplace("amazon.de")
    text = "Item(s) Subtotal: 22,97 €\nGrand Total: 22,97 €\nBio Bananen, 1 kg\n1,99 €\nBio Bananen, 1 kg\n1,99 €\nLachsfilet\n18,99 €\n"
    items = site._parse_items_from_summary_text(text)
    assert [(i.name, i.quantity, i.unit_price, i.line_total) for i in items] == \
        [("Bio Bananen, 1 kg", "2", "€1.99", "€3.98"), ("Lachsfilet", "1", "€18.99", "€18.99")]
    assert round(sum(site.money_value(i.line_total) for i in items), 2) == site.parse_subtotal(text)


def test_the_sold_by_layout_reads_pounds():
    site.set_marketplace("amazon.co.uk")
    text = "Some Product Title That Is Long Enough\nSold by: Amazon EU S.a.r.L.\nQty: 2\n£30.99\n"
    items = site._parse_items_from_summary_text(text)
    assert [(i.name, i.quantity, i.unit_price) for i in items] == \
        [("Some Product Title That Is Long Enough", "2", "£30.99")]


def test_the_config_key_reaches_the_site_module(tmp_path, monkeypatch):
    """App.__init__ applies config['marketplace'] before anything else runs."""
    import amazon_receipts
    src = Path(amazon_receipts.__file__).read_text(encoding="utf-8")
    head = src.split("def __init__(self, args):")[1].split("self.paths = ")[0]
    assert 'site.set_marketplace(self.config.get("marketplace"))' in head
