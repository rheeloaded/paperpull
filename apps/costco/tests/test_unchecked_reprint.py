"""A receipt that did not come through the check is never filed.

The render goes through delivery.render, which prints to a staging file,
reads it back, and moves it into place only if it is this purchase. When
that render came back with nothing, the app went on to _finish_pdf
anyway, found no file, failed validation, and reprinted the page
straight to the final path, outside the isolation and outside the check.
The case where the checked render fails is the case where a stale
receipt is still on screen, so that reprint is the one most likely to be
the wrong purchase, and it was marked verified.

Driven through _save_receipt with the page and the render stubbed,
because no test before this one reached that branch at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_receipts as app_mod
import costco_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.models import IN_STORE, Purchase


class _Paths:
    def __init__(self, root):
        self.root = root
        self.manual_review = root / "review"

    def folder_for(self, *a):
        return self.root


def _app(tmp_path, render_outcome, calls):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 100}
    app.paths = _Paths(tmp_path)
    app.stats = {"failed": 0, "manual_review": 0, "duplicate_filenames": 0,
                 "validation_failures": 0, "new_files": []}
    app._journal = Journal()
    app._record_state = lambda p, state, **kw: calls.append(("state", state))
    app._write_csv_rows = lambda p, **kw: calls.append(
        ("csv", kw.get("receipt_status")))
    app.write_failure = lambda *a, **kw: calls.append(("failure file",))
    app._capture_document = lambda page, purchase, out: delivery.Delivery(
        render_outcome)
    app._finish_pdf = lambda *a, **kw: calls.append(("finish", kw)) or True
    return app


class _Page:
    url = "https://www.costco.com/myaccount/#/app/receipts"


def _stub_site(monkeypatch):
    for name, value in (("looks_signed_out", False), ("on_receipt_page", True),
                        ("receipt_is_present", True)):
        monkeypatch.setattr(site, name, lambda *a, v=value: v)
    monkeypatch.setattr(site, "scroll_full_page", lambda *a: None)
    monkeypatch.setattr(app_mod, "restoring", _NoRestore)


class _NoRestore:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _purchase():
    return Purchase(order_number="w1", purchase_type=IN_STORE,
                    purchase_date="2026-01-15", total="$76.41")


def test_a_render_that_produced_nothing_is_a_failure_not_a_reprint(
        tmp_path, monkeypatch):
    _stub_site(monkeypatch)
    calls = []
    app = _app(tmp_path, delivery.NOTHING, calls)
    assert app._save_receipt(_Page(), _purchase()) is False
    assert not any(c[0] == "finish" for c in calls), \
        "an unchecked reprint could still be filed"
    assert app.stats["failed"] == 1
    assert ("csv", "Capture failed") in calls


def test_a_checked_receipt_is_finished_without_a_reprint(
        tmp_path, monkeypatch):
    """A reprint over a receipt that passed the check is the same bypass
    from the other side, so a checked one is validated as it is."""
    _stub_site(monkeypatch)
    calls = []
    app = _app(tmp_path, delivery.SAVED, calls)
    assert app._save_receipt(_Page(), _purchase()) is True
    finishes = [c for c in calls if c[0] == "finish"]
    assert finishes and finishes[0][1].get("reprint") is False
