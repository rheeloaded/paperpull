"""Each receipt route opens the purchase it names, and a key whose shape is
not known is not opened at all (#225, #235).

Kroger's receipt pages moved to date_division_store_terminal_transaction,
built from the history API's division~store~date~terminal~transaction. The
purchase keeps the API's key as its identity. These tests hold the parts
the route change leans on. Two receipts from one store on one day, one
transaction the start of the other, never stand in for each other. A
saved address of another purchase is never followed. A key with tildes in
a shape this version does not know is neither guessed at nor opened at a
route that cannot show it, where three days of empty pages would set it
aside for good. Every key, store and date is invented.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import kroger_receipts as app_mod
import kroger_site as site
from paperpull_core.models import Purchase

SHORT = "011~00123~2026-09-13~5~123"
LONG = "011~00123~2026-09-13~5~1234"


def _saver(monkeypatch):
    """An app whose save path only says whether it opened a page, and a
    page that never shows a receipt, so nothing is saved."""
    opened = []
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: opened.append(purchase.order_number))
    monkeypatch.setattr(site, "scroll_full_page", lambda page: None)
    monkeypatch.setattr(site, "receipt_is_present", lambda page: False)
    monkeypatch.setattr(site, "receipt_failed", lambda page: True)
    monkeypatch.setattr(app_mod.not_shown, "tried_again", lambda *args: False)
    return app_mod.App.__new__(app_mod.App), opened


@pytest.mark.parametrize("on, wanted", [(LONG, SHORT), (SHORT, LONG)],
                         ids=["on the longer transaction", "on the shorter transaction"])
def test_a_page_of_another_receipt_that_day_is_left_for_this_ones(monkeypatch, on, wanted):
    """The browser on one of two same-day receipts at one store is not on
    the other's, though one route starts with the other."""
    app, opened = _saver(monkeypatch)
    page = SimpleNamespace(url=site.receipt_url(on))
    app._save_receipt(page, Purchase(order_number=wanted))
    assert opened == [wanted], "the save path opens this purchase's own receipt"


@pytest.mark.parametrize("tail", ["", "?from=history", "#top"])
def test_this_receipts_own_page_is_not_opened_again(monkeypatch, tail):
    app, opened = _saver(monkeypatch)
    page = SimpleNamespace(url=site.receipt_url(LONG) + tail)
    app._save_receipt(page, Purchase(order_number=LONG))
    assert opened == []


def _goto(purchase):
    page = SimpleNamespace(url="")
    page.goto = lambda url, **kw: setattr(page, "url", url)
    page.wait_for_function = lambda *a, **kw: None
    page.wait_for_timeout = lambda *a: None
    site.goto_receipt(page, purchase)
    return page.url


@pytest.mark.parametrize("saved", [
    site.BASE + site.RECEIPT_PATH + SHORT,                     # another purchase, old form
    site.BASE + site.RECEIPT_PATH + site.page_key(SHORT),      # another purchase, new form
    site.BASE + site.RECEIPT_PATH + LONG + "?from=history",    # its own, old form, a query
    "https://www.kroger.com.example.test/mypurchases/image/" + site.page_key(LONG),
    "http://www.kroger.com" + site.RECEIPT_PATH + site.page_key(LONG),
    "",
], ids=["another, old form", "another, new form", "own old form with a query",
        "another host", "plain http", "none saved"])
def test_a_saved_address_that_is_not_this_receipts_route_gives_way(saved):
    url = _goto(Purchase(order_number=LONG, receipt_url=saved))
    assert url == site.BASE + site.RECEIPT_PATH + "2026-09-13_011_00123_5_1234"


def test_a_saved_address_of_its_own_route_is_used():
    saved = site.BASE + site.RECEIPT_PATH + site.page_key(LONG) + "?from=history"
    assert _goto(Purchase(order_number=LONG, receipt_url=saved)) == saved


def test_every_part_keeps_its_own_digits():
    assert site.page_key("007~00042~2026-01-02~014~000088") == "2026-01-02_007_00042_014_000088"


@pytest.mark.parametrize("key", [
    "011~00123~20260913~5~1234",       # a date without its dashes
    "011~00123~2026-9-13~5~1234",      # a date without its zeros
    "011~00123~2026-09-13~5",          # four parts
    "011~00123~2026-09-13~5~1234~7",   # six parts
    "0A1~00123~2026-09-13~5~1234",     # a letter
    "2026-09-13~011~00123~5~1234",     # the date first
])
def test_a_key_of_a_shape_not_known_is_not_guessed_at(key):
    assert site.page_key(key) == key
    assert site.unknown_receipt_key(key)


@pytest.mark.parametrize("key", [LONG, "112233445566", "AB12-3456", site.page_key(LONG), ""])
def test_a_known_key_or_an_order_number_is_opened_as_before(key):
    assert not site.unknown_receipt_key(key)


def test_a_key_of_a_shape_not_known_is_not_opened(monkeypatch):
    """It is recorded Failed and tried again next run, never handed to
    not_shown, which on its third day would set it aside for good."""
    opened, states, asked = [], [], []
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: opened.append(1))

    def read(page, purchase):
        raise AssertionError("the receipt page was opened and read, %d time(s)" % len(opened))
    monkeypatch.setattr(site, "extract_details", read)
    monkeypatch.setattr(app_mod.not_shown, "tried_again", lambda *a: asked.append(1) or False)
    app = app_mod.App.__new__(app_mod.App)
    app.stats = {"failed": 0}
    app._forget_unread_store = lambda purchase: None
    app._record_state = lambda purchase, state, notes="", extra=None: states.append((state, notes))
    app.process_one(SimpleNamespace(url=""), Purchase(order_number="011~00123~20260913~5~1234"))
    assert opened == [] and asked == []
    assert [s for s, _ in states] == [app_mod.State.FAILED]
    assert states[0][1] == app_mod.UNKNOWN_KEY, states
    assert app.stats["failed"] == 1
