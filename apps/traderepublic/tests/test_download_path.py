"""Trade Republic's real download path, under testkit.StrictDelivery.

0.34.0 shipped four apps that passed the capture a keyword it did not
take, and every document they asked for failed while their tests passed,
because none ran process() or download_one(). This runs this app's own
loop with the month's fetch stubbed and every place() call held to its
real signature. Every value is invented."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fakes  # noqa: E402,F401
from _fakes import statement  # noqa: E402
import traderepublic_docs as app_mod  # noqa: E402
import traderepublic_site as site  # noqa: E402
from paperpull_core import delivery  # noqa: E402
from paperpull_core.journal import Journal  # noqa: E402
from paperpull_core.models import State  # noqa: E402
from paperpull_core.testkit import StrictDelivery, sample_pdf, text_pdf  # noqa: E402


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key, *a, **kw):
        return self.data.get(key)

    def update(self, key, rec, *a, **kw):
        self.data.setdefault(key, {}).update(rec)

    def append_rows(self, *a, **kw):
        pass


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


PERIODS = ("2026-10", "2026-09", "2026-08")


def _app(tmp_path, monkeypatch, answers):
    app = object.__new__(app_mod.App)
    app.args = app_mod.build_parser().parse_args([])
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress, app.discovery, app.index_csv = _Store(), _Store(), _Store()
    app._journal = Journal()
    failures = []
    app.page = lambda: object()
    app.check_session = lambda page: None
    app._on_its_site = lambda: app.page()
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "fetch_month",
                        lambda page, m: answers.get(m.period, site.Answer(site.NO_STATEMENT, 404)))
    return app, failures


def _docs(periods=PERIODS):
    out = []
    for p in periods:
        m = site.month_of(p)
        out.append(app_mod.Document(title=app_mod.TITLE, category="Statement",
                                    summary="Account Statement", date=m.date, period=p,
                                    document_id=p))
    return out


def _right(*periods):
    return {p: site.Answer(site.PDF, 200, statement(p)) for p in periods}


def test_a_run_reaches_the_capture_with_arguments_it_accepts(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch, _right(*PERIODS))
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["place"] * 3
    assert app.stats["failed"] == 0 and not failures
    assert len(app.stats["new_files"]) == 3
    first = spy.calls[0].arguments
    assert first["strict"] is True
    assert first["expect"] == site.identity_for(site.month_of("2026-10"))
    assert first["rivals"] == site.rivals_for(site.month_of("2026-10"))
    assert first["data"] == statement("2026-10")


def test_what_was_placed_is_the_months_bytes(tmp_path, monkeypatch):
    StrictDelivery().install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch, _right("2026-10"))
    app.process(_docs(("2026-10",)))
    saved = Path(app.stats["new_files"][0])
    assert saved.read_bytes() == statement("2026-10")
    assert saved.name == "2026-10-31 Trade Republic Account Statement.pdf"
    assert app.progress.get("id:2026-10")["state"] == State.COMPLETED.value


def test_a_month_with_no_pdf_never_reaches_the_capture(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch, {})
    app.process(_docs(("2026-09",)))
    assert spy.calls == [] and app.stats["no_statement"] == 1 and failures


def test_a_pdf_not_shown_to_be_this_month_never_reaches_the_capture(tmp_path, monkeypatch):
    """place(strict=True) refuses only a refused verdict and saves an
    unchecked or unreadable one, so the app's own check comes first."""
    spy = StrictDelivery().install(monkeypatch)
    lines = ["Invented Broker GmbH", "Kontoauszug ohne Zeitraum",
             "Buchungen und Salden ohne echte Werte"]
    answers = {"2026-10": site.Answer(site.PDF, 200, text_pdf(lines)),
               "2026-09": site.Answer(site.PDF, 200, sample_pdf()),
               "2026-08": site.Answer(site.PDF, 200, statement("2026-07"))}
    app, _ = _app(tmp_path, monkeypatch, answers)
    app.process(_docs())
    assert spy.calls == []
    assert app.stats["failed"] == 3 and not app.stats["new_files"]
    assert not list(tmp_path.glob("*.pdf"))


def test_a_wrong_document_from_the_capture_is_a_failure(tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app, failures = _app(tmp_path, monkeypatch, _right("2026-10"))
    app.process(_docs(("2026-10",)))
    assert app.stats["failed"] == 1 and app.stats["wrong_document"] == 1
    assert not app.stats["new_files"] and failures
    assert app.progress.get("id:2026-10")["state"] == State.FAILED.value


def test_a_folder_that_would_not_take_it_is_a_failure_tried_again(tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOT_PLACED).install(monkeypatch)
    app, _ = _app(tmp_path, monkeypatch, _right("2026-10"))
    app.process(_docs(("2026-10",)))
    rec = app.progress.get("id:2026-10")
    assert rec["state"] == State.FAILED.value and "put in place" in rec["notes"]
    assert app.stats["no_statement"] == 0


def test_nothing_from_the_capture_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    for outcome in (delivery.NOTHING, delivery.NOT_A_PDF, delivery.TOO_LARGE):
        StrictDelivery(outcome=outcome).install(monkeypatch)
        app, _ = _app(tmp_path, monkeypatch, _right("2026-10"))
        app.process(_docs(("2026-10",)))
        assert app.stats["failed"] == 1 and app.stats["manual_review"] == 0
        assert not app.stats["new_files"]
