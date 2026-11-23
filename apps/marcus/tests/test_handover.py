"""Where the site layer stops, and that a statement is asked for once.

The site layer finds the row, checks its link and hands over a request.
The interceptor fires that request's trigger exactly once, because a click
on somebody's bank is not a thing to repeat, and this app builds no second
request for a statement in the same run. Every value here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import marcus_docs as app
import marcus_site as site
from paperpull_core import delivery


class _Doc:
    date = "2026-07-31"
    account = "x4417"
    category = "Statement"


class _Runner:
    """Just enough of the app to exercise the handover."""

    def __init__(self, outcomes, requests=None):
        self.outcomes = list(outcomes)
        self.requests = list(requests) if requests else None
        self.config = {"refuse_wrong_documents": True}
        self.journal = None
        self.asked = []
        self.delivered = 0

    _deliver_statement = app.App._deliver_statement


@pytest.fixture
def wiring(monkeypatch):
    def install(runner):
        def statement_request(page, date, account=""):
            runner.asked.append((date, account))
            if runner.requests is None:
                return delivery.DocumentRequest(trigger=lambda: None)
            return runner.requests.pop(0)

        def deliver(page, request, out_path, **kw):
            runner.delivered += 1
            return runner.outcomes.pop(0)

        monkeypatch.setattr(site, "statement_request", statement_request)
        monkeypatch.setattr(delivery, "deliver", deliver)
        monkeypatch.setattr(app.delivery, "deliver", deliver)
    return install


def made(outcome):
    return delivery.Delivery(outcome, delivery.DOWNLOAD)


def test_a_statement_is_asked_for_by_its_date_and_its_account(wiring):
    r = _Runner([made(delivery.SAVED)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == delivery.SAVED
    assert r.asked == [("2026-07-31", "x4417")]
    assert r.delivered == 1


@pytest.mark.parametrize("outcome", [delivery.NOTHING, delivery.WRONG,
                                     delivery.NOT_A_PDF, delivery.NOT_PLACED])
def test_whatever_comes_of_the_press_nothing_is_pressed_again(wiring, outcome):
    r = _Runner([made(outcome), made(delivery.SAVED)])
    wiring(r)
    got = r._deliver_statement(None, _Doc(), Path("x.pdf"))
    assert got.outcome == outcome
    assert r.delivered == 1
    assert len(r.asked) == 1


def test_no_row_at_all_delivers_nothing(wiring):
    r = _Runner([], requests=[None])
    wiring(r)
    assert r._deliver_statement(None, _Doc(), Path("x.pdf")) is None
    assert r.delivered == 0


# -- and the route itself ------------------------------------------------------

def test_the_row_date_is_not_checked_against_the_file():
    """A row is dated the day after the period its statement prints, so
    the date is not in its own file and is in the next month's."""
    assert not site.identity_for(_Doc()).is_checkable()


class _NoPage:
    """A Documents page with nothing to press. A request that reaches for
    the page past its checks fails the test."""
    url = site.DOCUMENTS_URL

    def locator(self, *a, **kw):
        raise AssertionError("a refused row was reached for")


def _refusal(monkeypatch, **changed):
    row = dict(index=0, account="x4417", product="Online Savings",
               date="2026-07-31", label="07/31/2026",
               href=site.BASE + "/api/invented/document/7", links=1)
    row.update(changed)
    monkeypatch.setattr(site, "_list_shows", lambda page: True)
    monkeypatch.setattr(site, "_rows", lambda page: [site.Row(**row)])
    return site.statement_request(_NoPage(), "2026-07-31", "x4417")


def test_a_row_with_nothing_wrong_is_reached_for(monkeypatch):
    """The control for the refusals below. A request that refused every
    row would pass each of them."""
    with pytest.raises(AssertionError):
        _refusal(monkeypatch)


def test_a_link_that_leaves_marcus_is_refused(monkeypatch):
    assert _refusal(monkeypatch, href="https://elsewhere.example/doc/7") is None


def test_a_link_that_says_more_than_its_date_is_refused(monkeypatch):
    assert _refusal(monkeypatch, label="Transfer") is None


def test_a_row_with_two_links_is_refused(monkeypatch):
    assert _refusal(monkeypatch, links=2) is None


def test_a_row_of_another_account_is_not_this_statement(monkeypatch):
    assert _refusal(monkeypatch, account="x0926") is None


def test_the_same_statement_listed_twice_is_refused(monkeypatch):
    twin = site.Row(index=0, account="x4417", product="Online Savings",
                    date="2026-07-31", label="07/31/2026",
                    href=site.BASE + "/api/invented/document/7", links=1)
    monkeypatch.setattr(site, "_list_shows", lambda page: True)
    monkeypatch.setattr(site, "_rows", lambda page: [twin, twin])
    assert site.statement_request(_NoPage(), "2026-07-31", "x4417") is None
