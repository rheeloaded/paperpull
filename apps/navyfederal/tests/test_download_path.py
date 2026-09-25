"""Navy Federal's real download path, run end to end without a browser.

0.34.0 passed deliver() a keyword it did not take, and every statement
Navy Federal asked for failed before anything was pressed. The handover
tests all passed, because none of them ran process() or download_one(),
which is where the call is. This one does, with the page and the site
layer stubbed and the capture replaced by paperpull_core.testkit, which
holds every call to deliver's real signature.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import navyfederal_docs as app_mod
import navyfederal_site as site
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


def _app(tmp_path, monkeypatch, strict=True):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": strict}
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
    monkeypatch.setattr(site, "statement_request", lambda page, acct, date: (
        delivery.DocumentRequest(trigger=lambda: None)))
    return app, failures


def _docs():
    # Two accounts billed on the same day, which is the case the rivals
    # exist for.
    rows = [("2026-08-15", "Checking"), ("2026-08-15", "Visa Signature"),
            ("2026-07-15", "Checking")]
    return [app_mod.Document(title="Statement", category="Statement",
                             summary="%s Statement" % acct, date=d,
                             account=acct, document_id="doc-%d" % n)
            for n, (d, acct) in enumerate(rows)]


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


def test_the_other_account_on_the_same_day_is_among_the_rivals(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch)
    app.process(_docs())
    labels = {r.label for r in spy.calls[0].arguments["rivals"]}
    assert "Visa Signature" in labels


def test_nothing_arriving_is_a_capture_failure_not_a_crash(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures
    assert not app.stats["new_files"]


def test_strict_follows_refuse_wrong_documents(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch, strict=False)
    app.process(_docs()[:1])
    assert spy.calls[0].arguments["strict"] is False


def test_a_wrong_statement_is_counted_for_review_and_not_saved(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["wrong_document"] == 1 and failures
    assert not app.stats["new_files"]
