"""Costco's real download path, run end to end without a browser.

0.34.0 shipped four apps that passed the capture a keyword it did not
take, and every document they asked for failed. Their tests all passed,
because none of them ran the loop that makes the call. Costco was not
one of the four, and nothing proved that either. This test runs Costco's
own process_purchases(), through process_one(), _save_receipt() and
_capture_document(), with the page and the site layer stubbed and the
capture replaced by paperpull_core.testkit, which holds every call to
render() to its real signature.
"""
import contextlib
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_receipts as app_mod
import costco_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.models import Item, Purchase
from paperpull_core.testkit import StrictDelivery


class _Store:
    def update(self, *a, **kw):
        pass

    def append_rows(self, *a, **kw):
        pass

    def get(self, *a, **kw):
        return None


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


class _Page:
    url = "https://www.costco.com/OrderStatusCmd"


def _app(tmp_path, monkeypatch, strict=True):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": strict}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress = app.discovery = app.index_csv = app.order_csv = _Store()
    app.rules = None
    app._journal = Journal()
    failures = []
    app.page = lambda: _Page()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    # The snapshot and restore of the page's styles run in the browser.
    monkeypatch.setattr(app_mod, "restoring",
                        lambda page, **kw: contextlib.nullcontext())
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: None)
    monkeypatch.setattr(site, "goto_orders", lambda page: None)
    monkeypatch.setattr(site, "extract_details",
                        lambda page, purchase: purchase)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "on_receipt_page", lambda page: True)
    monkeypatch.setattr(site, "scroll_full_page", lambda page: None)
    monkeypatch.setattr(site, "receipt_is_present", lambda page: True)
    return app, failures


def _purchases():
    return [Purchase(purchase_date=d, order_number="11%08d" % n,
                     total="84.%02d" % n, status="Delivered",
                     items=[Item(name="Kirkland Signature Paper Towels")])
            for n, d in enumerate(("2026-08-02", "2026-07-19", "2026-06-30"))]


def test_a_run_reaches_the_capture_with_arguments_it_accepts(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process_purchases(_purchases())
    assert [c.name for c in spy.calls] == ["render"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert app.stats["receipts_downloaded"] == 3
    assert len(app.stats["new_files"]) == 3 and not failures
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True


def test_each_receipt_is_checked_against_its_own_purchase(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch)
    purchases = _purchases()
    app.process_purchases(purchases)
    assert len(spy.calls) == len(purchases)
    for call, purchase in zip(spy.calls, purchases):
        assert call.arguments["expect"] == site.identity_for(purchase)
        assert site.identity_for(purchase) not in call.arguments["rivals"]


def test_nothing_rendering_is_a_recorded_failure_not_a_crash(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process_purchases(_purchases()[:1])
    # Costco counts a receipt that did not render as failed, and says so
    # in a failure file, which an exception inside the call would not.
    assert app.stats["failed"] == 1 and failures
    assert failures[0][0] == "save the receipt"
    assert app.stats["receipts_downloaded"] == 0
    assert not app.stats["new_files"]


def test_strict_follows_refuse_wrong_documents(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch, strict=False)
    app.process_purchases(_purchases()[:1])
    assert spy.calls[0].arguments["strict"] is False


def test_a_wrong_receipt_is_counted_for_review_and_not_saved(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process_purchases(_purchases()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["wrong_document"] == 1 and failures
    assert not app.stats["new_files"]
