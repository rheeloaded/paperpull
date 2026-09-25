"""Fairfax Water's real download path, run end to end without a browser.

0.34.0 passed deliver() a keyword it did not take, and every bill Fairfax
Water asked for failed before anything was pressed. The handover tests
all passed, because none of them ran process() or download_one(), which
is where the call is. This one does, with the page and the site layer
stubbed and the capture replaced by paperpull_core.testkit, which holds
every call to deliver's real signature.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import fairfaxwater_docs as app_mod
import fairfaxwater_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.testkit import StrictDelivery


class _Store:
    def update(self, *a, **kw):
        pass

    def append_rows(self, *a, **kw):
        pass


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


def _request(page, title, date, **kw):
    return delivery.DocumentRequest(trigger=lambda: None)


def _app(tmp_path, monkeypatch, bill_request=_request):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": True}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress = app.discovery = app.index_csv = _Store()
    app._journal = Journal()
    failures = []
    app.page = lambda: object()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "bill_request", bill_request)
    return app, failures


def _docs():
    return [app_mod.Document(title="Water Bill", category="Statement",
                             summary="Water Bill", date=d,
                             document_id="doc-%s" % d)
            for d in ("2026-08-05", "2026-05-05", "2026-02-05")]


def test_a_run_reaches_the_capture_with_arguments_it_accepts(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["deliver"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert len(app.stats["new_files"]) == 3 and not failures
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True
    assert first["is_safe_url"] is site.is_safe_url


def test_nothing_arriving_is_a_capture_failure_not_a_crash(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures
    assert not app.stats["new_files"]


def test_an_expired_session_stops_the_run_instead_of_failing_every_bill(
        tmp_path, monkeypatch):
    def expired(page, title, date, **kw):
        raise site.SessionExpired("sign-in page")

    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch, bill_request=expired)
    app.process(_docs())
    assert not spy.calls
    assert app.stats["session_expired"] == 1
    assert app.stats["failed"] == 0 and app.stats["manual_review"] == 0
