"""TSP's real download path, run end to end without a browser.

0.34.0 shipped four apps that passed the capture a keyword it did not
take, and every document they asked for failed. Their tests all passed,
because none of them ran process() or download_one(), which is where
the call is. TSP was not one of the four, and nothing proved that. This
test runs TSP's own loop, with the page and the Secure Mailbox fetch
stubbed and the capture replaced by paperpull_core.testkit, which holds
every call to place() to its real signature.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import tsp_docs as app_mod
import tsp_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.testkit import StrictDelivery, sample_pdf


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


PDF = sample_pdf()


def _app(tmp_path, monkeypatch, data=PDF):
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
    monkeypatch.setattr(site, "document_bytes",
                        lambda page, title, date, **kw: data)
    return app, failures


def _docs():
    return [app_mod.Document(title="Quarterly Statement", category="Statement",
                             summary="Quarterly Statement", date=d,
                             document_id="doc-%s" % d)
            for d in ("2026-07-01", "2026-04-01", "2026-01-01")]


def test_a_run_reaches_the_capture_with_arguments_it_accepts(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch)
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["place"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert len(app.stats["new_files"]) == 3 and not failures
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True


def test_the_fetched_bytes_are_what_is_placed_under_this_documents_identity(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch)
    doc = _docs()[0]
    app.process([doc])
    args = spy.calls[0].arguments
    assert args["data"] == PDF
    assert args["expect"] == site.identity_for(doc)
    assert Path(app.stats["new_files"][0]).read_bytes() == PDF


def test_nothing_arriving_is_a_capture_failure_not_a_crash(
        tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch, data=b"")
    app.process(_docs()[:1])
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures
    assert not app.stats["new_files"]
