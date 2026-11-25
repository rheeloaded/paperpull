"""Marcus's real download path, run end to end without a browser.

An app whose tests never run process(), download_one() and
_deliver_statement() can pass deliver() a keyword it does not take and
fail every statement before anything is pressed. This runs them, with the
page and the site layer stubbed and the capture replaced by
paperpull_core.testkit, which holds every call to deliver's real
signature. Every value here is invented.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import marcus_docs as app_mod
import marcus_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.testkit import StrictDelivery


class _Store:
    def get(self, *a, **kw):
        return None

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
                  "refuse_wrong_documents": True}  # so strict is seen passed on
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress = app.discovery = app.index_csv = _Store()
    app._journal = Journal()
    failures, asked = [], []
    app.page = lambda: object()
    app.check_session = lambda page: None
    # The tab here is a stand-in with no address, so the check that it is
    # on the provider's own site (tabs.on_its_site) is stood in for too.
    app._on_its_site = lambda: app.page()
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def statement_request(page, date, account=""):
        asked.append((date, account))
        return delivery.DocumentRequest(trigger=lambda: None)
    monkeypatch.setattr(site, "statement_request", statement_request)
    return app, failures, asked


def _docs():
    return [app_mod.Document(title="Online Savings Statement",
                             category="Statement",
                             summary="Online Savings Statement x4417",
                             date=d, account="x4417")
            for d in ("2026-08-31", "2026-07-31", "2026-06-30")]


def test_a_run_reaches_the_capture_with_arguments_it_accepts(
        tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures, asked = _app(tmp_path, monkeypatch)
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["deliver"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert len(app.stats["new_files"]) == 3 and not failures
    assert asked == [("2026-08-31", "x4417"), ("2026-07-31", "x4417"),
                     ("2026-06-30", "x4417")]
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True
    assert first["settle_ms"] == 45000


def test_a_saved_statement_is_named_for_its_account(tmp_path, monkeypatch):
    StrictDelivery().install(monkeypatch)
    app, _, _ = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert [Path(p).name for p in app.stats["new_files"]] == [
        "2026-08-31 Marcus Online Savings Statement X4417.pdf"]


def test_nothing_arriving_is_a_capture_failure_and_is_not_pressed_again(
        tmp_path, monkeypatch):
    spy = StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures, asked = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert len(spy.calls) == 1, "the statement was pressed more than once"
    assert len(asked) == 1
    assert app.stats["failed"] == 1
    assert app.stats["manual_review"] == 0 and failures
    assert not app.stats["new_files"]


def test_a_wrong_document_goes_to_manual_review_and_is_not_saved(
        tmp_path, monkeypatch):
    spy = StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app, failures, _ = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert len(spy.calls) == 1
    assert app.stats["manual_review"] == 1 and failures
    assert not app.stats["new_files"]


def test_a_row_recorded_from_the_page_keeps_its_account(tmp_path, monkeypatch):
    """Two accounts' statements of one day are two records and two names."""
    app, _, _ = _app(tmp_path, monkeypatch)
    kept = {}

    class _Discovery:
        def get(self, key):
            return kept.get(key)

        def update(self, key, rec, save=True):
            kept.setdefault(key, {}).update(rec)
    app.discovery = _Discovery()
    app.rules = app_mod.doc_types.load_rules()
    app.args = type("A", (), {"start_date": None})()
    for account in ("x4417", "x0926"):
        raw = site.RawDoc(title="Online Savings Statement", account=account,
                          date_text="2026-08-31", kind="statement")
        assert app._record_rawdoc(raw, site.DOCUMENTS_URL) == 1
    assert len(kept) == 2
    assert sorted(r["summary"] for r in kept.values()) == [
        "Online Savings Statement x0926", "Online Savings Statement x4417"]
