"""T-Mobile's real download path, run end to end without a browser.

0.34.0 passed deliver() a keyword it did not take, and every bill T-Mobile
asked for failed before anything was pressed. The handover tests all
passed, because none of them ran process() or download_one(), which is
where the call is. This one does, with the page and the site layer
stubbed and the capture replaced by paperpull_core.testkit, which holds
every call to deliver's real signature.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import tmobile_docs as app_mod
import tmobile_site as site
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
    app._dl_dir = None
    failures = []
    app.page = lambda: object()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "bill_request", lambda page, date: (
        delivery.DocumentRequest(trigger=lambda: None)))
    return app, failures


def _docs():
    return [app_mod.Document(title="Bill", category="Statement",
                             summary="Monthly Bill", date=d,
                             document_id="doc-%s" % d)
            for d in ("2026-08-21", "2026-07-21", "2026-06-21")]


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
    assert first["settle_ms"] >= 60000
    assert first["strict"] is True


def test_nothing_arriving_is_a_capture_failure_not_a_crash(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures


def test_the_stand_in_refuses_what_the_real_call_would():
    """If this passed a keyword deliver() does not take, the test above
    would fail the way 0.34.0 failed on a real account."""
    import pytest
    with pytest.raises(TypeError):
        StrictDelivery()._fake("deliver")(
            object(), delivery.DocumentRequest(), "x.pdf",
            is_safe_url=lambda u: True, not_a_real_keyword=1)
