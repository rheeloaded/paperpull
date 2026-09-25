"""RedCard's real download path, run end to end without a browser.

0.34.0 passed deliver() a keyword it did not take, and every statement
RedCard asked for failed before anything was pressed. The handover tests
all passed, because none of them ran process(), download_one() or
_deliver_statement(), which is where the call and its retry are. This one
does, with the page and the site layer stubbed and the capture replaced
by paperpull_core.testkit, which holds every call to deliver's real
signature.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import redcard_docs as app_mod
import redcard_site as site
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


def _app(tmp_path, monkeypatch):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": True}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress = app.discovery = app.index_csv = _Store()
    app._journal = Journal()
    failures, resyncs = [], []
    app.page = lambda: object()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "statement_request", lambda page, date: (
        delivery.DocumentRequest(trigger=lambda: None)))
    monkeypatch.setattr(site, "resync",
                        lambda page: resyncs.append(page) or True)
    return app, failures, resyncs


def _docs():
    return [app_mod.Document(title="Billing Statement", category="Statement",
                             summary="Billing Statement", date=d,
                             document_id="doc-%s" % d)
            for d in ("2026-08-12", "2026-07-12", "2026-06-12")]


def test_a_run_reaches_the_capture_with_arguments_it_accepts(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures, resyncs = _app(tmp_path, monkeypatch)
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["deliver"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert len(app.stats["new_files"]) == 3 and not failures
    assert not resyncs, "a saved statement was pressed again"
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True


def test_the_download_is_given_the_long_settle_it_needs(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _, _ = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert spy.calls[0].arguments["settle_ms"] == 45000


def test_nothing_arriving_is_retried_once_then_a_capture_failure(
        tmp_path, monkeypatch):
    spy = StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures, resyncs = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert len(spy.calls) == 2, "the statement was pressed more than twice"
    assert len(resyncs) == 1
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures
    assert not app.stats["new_files"]


def test_a_document_that_arrived_and_was_not_placed_is_not_pressed_again(
        tmp_path, monkeypatch):
    spy = StrictDelivery(outcome=delivery.NOT_PLACED).install(monkeypatch)
    app, failures, resyncs = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert len(spy.calls) == 1 and not resyncs
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures
