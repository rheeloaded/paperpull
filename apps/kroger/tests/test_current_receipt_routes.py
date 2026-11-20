"""Synthetic API keys and the different keys used by the receipt routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kroger_site as site
from paperpull_core.models import Purchase

KEY = "011~00123~2026-09-13~5~1234"
ROUTE = "2026-09-13_011_00123_5_1234"


def test_routes_reorder_the_api_key_without_changing_purchase_identity():
    purchase = site.record_to_purchase({"receiptKey": KEY, "purchaseType": "IN_STORE"})
    assert purchase.order_number == KEY
    assert purchase.receipt_url == site.BASE + site.RECEIPT_PATH + ROUTE
    assert purchase.details_url == site.BASE + site.DETAIL_PATH + ROUTE


def test_resume_updates_an_old_receipt_url():
    class Page:
        def goto(self, url, **kwargs):
            self.url = url
        def wait_for_function(self, *args, **kwargs):
            pass
        def wait_for_timeout(self, *args):
            pass
    page = Page()
    site.goto_receipt(page, Purchase(order_number=KEY,
        receipt_url=site.BASE + site.RECEIPT_PATH + KEY))
    assert page.url == site.BASE + site.RECEIPT_PATH + ROUTE


def test_other_keys_are_preserved():
    for key in ("123456", ROUTE, "011~00123~20260913~5~1234"):
        assert site.page_key(key) == key


def test_saving_does_not_reopen_the_current_receipt(monkeypatch):
    from types import SimpleNamespace
    import kroger_receipts as app_mod

    opened = []
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "goto_receipt", lambda *args: opened.append(args))
    monkeypatch.setattr(site, "scroll_full_page", lambda page: None)
    monkeypatch.setattr(site, "receipt_is_present", lambda page: False)
    monkeypatch.setattr(site, "receipt_failed", lambda page: True)
    monkeypatch.setattr(app_mod.not_shown, "tried_again", lambda *args: False)
    app = app_mod.App.__new__(app_mod.App)
    page = SimpleNamespace(url=site.receipt_url(KEY))
    assert not app._save_receipt(page, Purchase(order_number=KEY))
    assert opened == []
