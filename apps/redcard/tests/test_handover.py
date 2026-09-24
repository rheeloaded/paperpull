"""Where the site layer stops, and where the retry lives.

TD's portal session dies quietly. The SPA keeps showing a cached
statements table while download clicks silently do nothing, so a first
attempt producing nothing is ordinary here rather than exceptional.

That retry cannot move into the interceptor, which fires a trigger
exactly once on purpose, because a click on somebody's bank is not a
thing to repeat. So the app builds a second request instead, and these
pin down when it does and, more importantly, when it must not.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import redcard_docs as app
import redcard_site as site
from paperpull_core import delivery


class _Doc:
    date = "2026-07-15"
    category = "Statement"


class _Runner:
    """Just enough of the app to exercise the retry."""

    def __init__(self, outcomes, requests=None):
        self.outcomes = list(outcomes)
        self.requests = list(requests) if requests else None
        self.config = {"refuse_wrong_documents": True}
        self.journal = None
        self.resyncs = 0
        self.delivered = 0

    _deliver_statement = app.App._deliver_statement


@pytest.fixture
def wiring(monkeypatch):
    def install(runner, resync_ok=True):
        def statement_request(page, date):
            if runner.requests is None:
                return delivery.DocumentRequest(trigger=lambda: None)
            return runner.requests.pop(0)

        def deliver(page, request, out_path, **kw):
            runner.delivered += 1
            return runner.outcomes.pop(0)

        def resync(page):
            runner.resyncs += 1
            return resync_ok

        monkeypatch.setattr(site, "statement_request", statement_request)
        monkeypatch.setattr(site, "resync", resync)
        monkeypatch.setattr(delivery, "deliver", deliver)
        monkeypatch.setattr(app.delivery, "deliver", deliver)
    return install


def made(outcome):
    return delivery.Delivery(outcome, delivery.DOWNLOAD)


def test_a_statement_that_arrives_first_time_is_not_retried(wiring):
    r = _Runner([made(delivery.SAVED)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.SAVED
    assert r.delivered == 1
    assert r.resyncs == 0


def test_nothing_coming_back_is_retried_once(wiring):
    """What a dead TD session looks like. The click lands on a cached
    table and does nothing at all."""
    r = _Runner([made(delivery.NOTHING), made(delivery.SAVED)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.SAVED
    assert r.delivered == 2
    assert r.resyncs == 1


def test_the_retry_happens_once_and_never_loops(wiring):
    r = _Runner([made(delivery.NOTHING), made(delivery.NOTHING)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.NOTHING
    assert r.delivered == 2


def test_a_wrong_document_is_never_retried(wiring):
    """The one that matters. A refused document is a real file belonging
    to another statement, and clicking again would only hide it behind a
    second attempt that might happen to work."""
    r = _Runner([made(delivery.WRONG), made(delivery.SAVED)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.WRONG
    assert r.delivered == 1
    assert r.resyncs == 0


def test_an_error_page_is_not_retried_either(wiring):
    """Something did arrive. Retrying would paper over what it was."""
    r = _Runner([made(delivery.NOT_A_PDF), made(delivery.SAVED)])
    wiring(r)
    assert r._deliver_statement(None, _Doc(), Path("x.pdf")).outcome == \
        delivery.NOT_A_PDF
    assert r.delivered == 1


def test_a_dead_session_stops_rather_than_clicking_at_nothing(wiring):
    r = _Runner([made(delivery.NOTHING)])
    wiring(r, resync_ok=False)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.NOTHING
    assert r.delivered == 1
    assert r.resyncs == 1


def test_no_row_at_all_resyncs_then_gives_up(wiring):
    r = _Runner([], requests=[None, None])
    wiring(r)
    assert r._deliver_statement(None, _Doc(), Path("x.pdf")) is None
    assert r.delivered == 0
    assert r.resyncs == 1


def test_a_row_that_appears_after_a_resync_is_delivered(wiring):
    r = _Runner([made(delivery.SAVED)],
                requests=[None, delivery.DocumentRequest(trigger=lambda: None)])
    wiring(r)
    assert r._deliver_statement(None, _Doc(), Path("x.pdf")).outcome == \
        delivery.SAVED
    assert r.resyncs == 1


# -- and the route itself ------------------------------------------------------

def test_the_route_carries_the_statement_date_to_check_against():
    ident = site.Identity(date="2026-07-15")
    assert sorted(ident.strong()) == ["date"]


def test_the_old_entry_point_is_gone():
    """download_document used to click and catch. Leaving it behind
    would let a caller quietly keep the old path."""
    assert not hasattr(site, "download_document")
    assert not hasattr(site, "_attempt_download")
    assert hasattr(site, "statement_request")
    assert hasattr(site, "resync")
