"""Strike's real download path, run end to end without a browser.

The page and the Documents API are stubbed and the capture is replaced by
paperpull_core.testkit, which holds every call to place() to its real
signature. A monthly statement is its PDF, through place(), and then its
CSV beside it. A year's entry is a CSV alone. Every value is invented.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import strike_docs as app_mod
import strike_site as site
from paperpull_core import delivery
from paperpull_core.journal import Journal
from paperpull_core.testkit import StrictDelivery, sample_pdf


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


PDF = sample_pdf()
HEADER = ",".join(site.CSV_COLUMNS)


def _csv(*dates):
    return ("\n".join([HEADER] + ["r%d,%s,Deposit,1.00,,,,,,,," % (i, d)
                                   for i, d in enumerate(dates)]) + "\n").encode()


def _app(tmp_path, monkeypatch, pdf=PDF, csv=None, wants_csv=True):
    app = object.__new__(app_mod.App)
    app.args = type("A", (), {"redownload": False})()
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": True, "save_statement_csv": wants_csv}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress, app.discovery, app.index_csv = _Store(), _Store(), _Store()
    app._journal = Journal()
    failures, asked = [], []
    app.page = lambda: object()
    app.check_session = lambda page: None
    # The tab here is a stand-in with no address, so the check that it is
    # on the provider's own site (tabs.on_its_site) is stood in for too.
    app._on_its_site = lambda: app.page()
    app._delay = lambda *a, **kw: None
    app.write_failure = lambda *a, **kw: failures.append(a)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)

    def statement_bytes(page, year, month, fmt):
        asked.append((year, month, fmt))
        if fmt == "pdf":
            return pdf
        return csv if csv is not None else _csv(
            "%s 15 %d 12:00:00" % (app_mod.MONTHS[(month or 1) - 1][:3], year))
    monkeypatch.setattr(site, "statement_bytes", statement_bytes)
    monkeypatch.setattr(site, "tax_bytes", lambda page, doc_id: pdf)
    monkeypatch.setattr(site, "list_tax_documents",
                        lambda page: [{"id": "f-1", "year": 2025, "file_name": "1099-B"}])
    return app, failures, asked


def _months(*pairs):
    docs = []
    for y, m in pairs:
        d = app_mod.App.statement_doc({"type": "Month", "year": y, "month": m})
        d.category, d.summary = "Statement", "Account Statement"
        docs.append(d)
    return docs


def test_a_run_reaches_the_capture_with_arguments_it_accepts(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, failures, _ = _app(tmp_path, monkeypatch)
    app.process(_months((2026, 10), (2026, 9), (2026, 8)))
    assert [c.name for c in spy.calls] == ["place"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True
    assert not failures


def test_a_monthly_statement_saves_its_pdf_and_its_csv_beside_it(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _, asked = _app(tmp_path, monkeypatch)
    doc = _months((2026, 10))[0]
    app.process([doc])
    args = spy.calls[0].arguments
    assert args["data"] == PDF and args["expect"] == site.identity_for(doc)
    pdf, csv = (Path(p) for p in app.stats["new_files"])
    assert pdf.suffix == ".pdf" and csv == pdf.with_suffix(".csv")
    assert pdf.read_bytes() == PDF and site.csv_problem(csv.read_bytes(), 2026, 10) == ""
    assert asked == [(2026, 10, "pdf"), (2026, 10, "csv")]
    rec = app.progress.get(doc.key)
    assert rec["downloaded_ok"] and rec["pdf_ok"] and rec["csv_ok"]
    assert [e["file"] for e in rec["invoices"]] == [str(pdf), str(csv)], \
        "a Rename would leave the CSV behind"


def test_csvs_turned_off_saves_the_pdf_alone(tmp_path, monkeypatch):
    StrictDelivery().install(monkeypatch)
    app, _, asked = _app(tmp_path, monkeypatch, wants_csv=False)
    app.process(_months((2026, 10)))
    assert asked == [(2026, 10, "pdf")]
    assert [Path(p).suffix for p in app.stats["new_files"]] == [".pdf"]


def test_a_csv_of_another_month_is_not_saved_and_only_it_is_asked_again(
        tmp_path, monkeypatch):
    StrictDelivery().install(monkeypatch)
    app, failures, asked = _app(tmp_path, monkeypatch, csv=_csv("Sep 30 2026 12:00:00"))
    doc = _months((2026, 10))[0]
    app.process([doc])
    rec = app.progress.get(doc.key)
    assert rec["pdf_ok"] and not rec.get("csv_ok") and not rec.get("downloaded_ok")
    assert app.stats["failed"] == 1 and failures
    assert not list(tmp_path.glob("*.csv"))
    assert not app._already_done(doc), "the missing CSV would never be asked for"

    # The next run, with the right CSV, asks for the CSV alone.
    asked.clear()
    app.stats["failed"] = 0
    app.config["save_statement_csv"] = True
    monkeypatch.setattr(site, "statement_bytes",
                        lambda page, y, m, fmt: asked.append((y, m, fmt)) or
                        _csv("Oct 02 2026 08:00:00"))
    app.process([_months((2026, 10))[0]])
    assert asked == [(2026, 10, "csv")]
    assert app.progress.get(doc.key)["downloaded_ok"]
    assert len(list(tmp_path.glob("*.pdf"))) == 1, "the PDF was saved a second time"


def test_the_annual_entry_is_a_csv_alone(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _, asked = _app(tmp_path, monkeypatch,
                         csv=_csv("Jan 03 2025 10:00:00", "Dec 30 2025 10:00:00"))
    doc = app_mod.App.statement_doc({"type": "Year", "year": 2025, "month": None})
    doc.category, doc.summary = "Statement", "Annual Transactions"
    app.process([doc])
    assert not spy.calls, "a PDF was asked for the annual entry"
    assert asked == [(2025, None, "csv")]
    (saved,) = app.stats["new_files"]
    assert saved.endswith("Annual Transactions.csv")
    assert app.progress.get(doc.key)["downloaded_ok"]


def test_a_tax_form_is_placed_as_a_pdf(tmp_path, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    app, _, _ = _app(tmp_path, monkeypatch)
    doc = app_mod.App.tax_doc({"id": "f-1", "year": 2025, "file_name": "1099-B"})
    doc.category, doc.summary = "Tax Document", "1099-B Tax Form"
    app.process([doc])
    assert [c.name for c in spy.calls] == ["place"]
    assert app.progress.get(doc.key)["downloaded_ok"]


def test_nothing_arriving_is_a_capture_failure_not_a_crash(tmp_path, monkeypatch):
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures, asked = _app(tmp_path, monkeypatch, pdf=b"")
    app.process(_months((2026, 10)))
    assert app.stats["failed"] == 1
    assert app.stats["manual_review"] == 0 and failures
    assert not app.stats["new_files"]
    assert asked == [(2026, 10, "pdf")], "a CSV was asked for with no PDF saved"
