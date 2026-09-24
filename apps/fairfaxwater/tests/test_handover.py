"""Where the site layer stops, and the one provider whose document is
not on the provider's host.

View opens a tab on docsight.net. Every other app could get away with
an allowlist guessed from the provider's own domain. This one proves the
allowlist has to travel with the request, because a guess would refuse
the document and a wildcard would accept anything.

This app also hand-rolled the mechanism the interceptor grew for it. It
listened at the context for the answer rather than at the tab, because
a tab's first response can land before a listener attached on the page
event exists, and two of five bills were lost that way on its first
pilot. These pin down that none of that came back as app code.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fairfaxwater_site as site
from paperpull_core import delivery


class _View:
    def __init__(self):
        self.clicks = []

    def click(self, **kw):
        self.clicks.append(1)


def ready(monkeypatch, view=None):
    view = view if view is not None else _View()
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "_row_for", lambda p, d, t: view)
    monkeypatch.setattr(site, "_guarded_click", lambda v, **kw: v.click() or True)
    return view


def test_the_route_hands_over_and_does_not_click(monkeypatch):
    view = ready(monkeypatch)
    req = site.bill_request(None, "Water bill", "2026-07-15")
    assert req is not None
    assert view.clicks == [], "the route clicked instead of handing over"
    req.trigger()
    assert view.clicks == [1]


def test_the_document_host_is_allowed_and_is_not_the_provider(monkeypatch):
    """The fact that makes this app the interesting one. The bill is
    served from a third party, so an allowlist derived from the
    provider's own name would refuse every document."""
    assert "docsight.net" in site.ALLOWED_HOSTS
    assert site.is_safe_url("https://docsight.net/doc/1.pdf")
    assert site.is_safe_url("https://www.fairfaxwater.org/x")
    assert not site.is_safe_url("https://docsight.net.evil.example/doc.pdf")
    assert not site.is_safe_url("https://somewhere-else.example/doc.pdf")


def test_the_hint_says_the_answer_arrives_in_flight(monkeypatch):
    ready(monkeypatch)
    req = site.bill_request(None, "Water bill", "2026-07-15")
    assert req.hints == (delivery.RESPONSE,)
    assert delivery._order(req.hints)[0] == delivery.RESPONSE
    # Reordered, never restricted, so a portal that starts firing an
    # ordinary download still works.
    assert set(delivery._order(req.hints)) == {
        delivery.DOWNLOAD, delivery.RESPONSE, delivery.TAB, delivery.FOLDER}


def test_the_tab_the_portal_opens_is_closed(monkeypatch):
    ready(monkeypatch)
    req = site.bill_request(None, "Water bill", "2026-07-15")
    assert req.close_new_tabs is True


def test_the_bill_is_checked_against_its_date(monkeypatch):
    ready(monkeypatch)
    req = site.bill_request(None, "Water bill", "2026-07-15")
    assert req.expect.date == "2026-07-15"
    assert sorted(req.expect.strong()) == ["date"]


def test_a_missing_row_expands_the_history_then_gives_up(monkeypatch):
    tried = []
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "_row_for", lambda p, d, t: None)
    monkeypatch.setattr(site, "expand_history",
                        lambda p, until_year=None: tried.append(until_year))
    assert site.bill_request(None, "Water bill", "2026-07-15") is None
    assert tried == [2025], "the history was not expanded past the bill's year"


def test_a_documents_page_that_will_not_open_hands_over_nothing(monkeypatch):
    monkeypatch.setattr(site, "goto_documents", lambda p: False)
    assert site.bill_request(None, "Water bill", "2026-07-15") is None


# -- none of what moved to the core came back ---------------------------------

def test_the_app_no_longer_listens_for_answers_itself(monkeypatch):
    source = inspect.getsource(site.bill_request)
    assert "on(\"response\"" not in source
    assert "on('response'" not in source


def test_the_app_no_longer_closes_or_refetches_tabs(monkeypatch):
    source = inspect.getsource(site.bill_request)
    for gone in ("close()", "ctx.request.get", "is_closed"):
        assert gone not in source, gone


def test_the_old_entry_point_is_gone():
    """download_document clicked, listened, re-fetched, refused and
    closed. Leaving it beside the new path would let a caller keep all
    of that."""
    assert not hasattr(site, "download_document")
    assert hasattr(site, "bill_request")
