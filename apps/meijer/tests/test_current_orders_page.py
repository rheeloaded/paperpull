"""Current tab and receipt button wording, with invented dates and amounts."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meijer_site as site
from paperpull_core.models import IN_STORE


@pytest.mark.parametrize("label,pattern", [
    ("Online", site.TAB_ONLINE_RE), ("Online Orders", site.TAB_ONLINE_RE),
    ("In-Store", site.TAB_IN_STORE_RE), ("In-Store Receipts", site.TAB_IN_STORE_RE),
])
def test_old_and_current_tab_labels(label, pattern):
    assert pattern.fullmatch(label)


def test_current_download_button_is_read_only():
    label = "Download receipt from September 13, 2026, 11:41 am"
    assert site.is_receipt_control({"label": label})
    for prefix in ("Email ", "Share ", "Send ", "Delete "):
        assert not site.is_receipt_control({"label": prefix + label})
    assert not site.is_receipt_control({"label": "Download receipt from settings"})


def test_full_month_date_can_find_its_row_again():
    text = "In-Store: September 13, 2026, 11:41 am\nExample Store\n$12.34 • 2 items"
    purchase = site.card_to_purchase(site.RawCard(text=text), IN_STORE)
    assert purchase.purchase_date == "2026-09-13"
    assert "September 13, 2026" in site.row_dates(purchase.purchase_date)


def test_current_row_is_collected_and_its_download_button_can_be_selected():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''<main><div role="tablist">
          <button role="tab">Online</button><button role="tab">In-Store</button></div>
          <ul><li><div>In-Store: September 13, 2026, 11:41 am</div>
          <div>Example Store</div><div>$12.34 • 2 items</div>
          <button aria-label="Download receipt from September 13, 2026, 11:41 am">↓</button>
          </li></ul></main>''')
        assert site.orders_listed(page)
        assert site.show_tab_for(page, IN_STORE)
        cards = site.collect_cards(page)
        assert len(cards) == 1
        purchase = site.card_to_purchase(cards[0], IN_STORE)
        candidates, _handles = site.row_controls(page, purchase)
        assert any(site.is_receipt_control(c) for c in candidates)
        browser.close()
