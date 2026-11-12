"""Anthem's claims list, filed as one claims summary a year.

The claims list is not the EOB Center. Anthem exports it only as a CSV, by
claims.v1.summaryDownload for a start and an end date, asked for by POST (a
GET of it answers 500), with the file base64 in result.data.file. The app
asks for each calendar year that has ended, and for the current year up to
today, and files each one that holds a claim as a PDF table with the CSV
kept beside it. A completed year is one document, downloaded once. The
current year is a document for each month a run sees, since its list grows.

The app is built by its own parser with a made-up config. Only the page is
stood in: it answers the export in the shape the site hands it over, and
the PDF printing is stood in. Every name, claim number and amount is invented.
"""
import base64
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core import testkit  # noqa: E402

site = app_mod.site

TODAY = date(2026, 11, 11)
COLUMNS = ["Claim Type", "Claim Number", "Patient", "Service Date", "Claim Received",
           "Processed Date", "Status", "Provided By", "Billed", "Plan Discount", "Allowed",
           "Plan Paid", "Additional Savings", "Deductible", "Coinsurance", "Copay",
           "Not Covered", "Your Cost"]


def csv_of(*claims):
    lines = [",".join(COLUMNS)]
    for number, day in claims:
        lines.append(",".join(["Medical", number, "Dana Example", day, day, day, "Processed",
                               "Example Clinic <b>&</b> Lab", "$120.00", "$20.00", "$100.00",
                               "$80.00", "$0.00", "$0.00", "$20.00", "$0.00", "$0.00", "$20.00"]))
    return "\r\n".join(lines) + "\r\n"


# What the export answers for each (start, end) it is asked for. A year the
# plan held no claims answers an empty file.
EXPORTS = {
    ("2026-01-01", "2026-11-11"): csv_of(("9000000AA0003", "2026-03-04")),
    ("2025-01-01", "2025-12-31"): csv_of(("9000000AA0002", "2025-06-01"),
                                         ("9000000AA0004", "2025-07-01")),
    ("2024-01-01", "2024-12-31"): csv_of(("9000000AA0001", "2024-09-01")),
}


class FakePage:
    url = "https://membersecure.anthem.com/member/claims"

    def __init__(self, exports=None):
        self.exports = EXPORTS if exports is None else exports
        self.asked = []

    def evaluate(self, js, arg=None):
        assert "claims.v1.summaryDownload" in js, "an unexpected call into the page"
        self.asked.append((arg["start"], arg["end"]))
        text = self.exports.get((arg["start"], arg["end"]), "")
        return {"status": 200, "type": "text/csv",
                "file": base64.b64encode(text.encode("utf-8")).decode()}


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(site, "is_anthem_owned_page", lambda page: True)
    monkeypatch.setattr(site, "prime_session", lambda page, force=False: True)


@pytest.fixture
def printed(monkeypatch):
    """The browser's print-to-PDF stood in: each HTML it is handed, kept."""
    seen = []

    def to_pdf(_page, html):
        seen.append(html)
        return testkit.text_pdf(["claims summary %d" % len(seen)])
    monkeypatch.setattr(site, "render_html_to_pdf", to_pdf)
    return seen


# -- the periods -------------------------------------------------------------

def test_the_periods_are_this_year_to_date_then_each_year_that_has_ended():
    periods = site.claims_summary_periods(TODAY)
    assert periods[0] == {"period": "2026-11", "start": "2026-01-01", "end": "2026-11-11",
                          "label": "Claims Summary 2026 Year to Date", "date": "2026-11-11"}
    assert periods[1] == {"period": "2025", "start": "2025-01-01", "end": "2025-12-31",
                          "label": "Claims Summary 2025", "date": "2025-12-31"}
    years = [p["period"] for p in periods[1:]]
    assert years == [str(y) for y in range(2025, 2025 - len(years), -1)]
    assert len(years) >= 4


# -- the listing -------------------------------------------------------------

def test_each_period_that_holds_a_claim_is_listed_and_an_empty_one_is_not(signed_in):
    page = FakePage()
    rows = site.list_claims_summaries(page, TODAY)
    assert [r["doc_id"] for r in rows] == [
        "ClaimsSummary|2026-11", "ClaimsSummary|2025", "ClaimsSummary|2024"]
    assert [r["date"] for r in rows] == ["2026-11-11", "2025-12-31", "2024-12-31"]
    assert {r["folder_attr"] for r in rows} == {"claims_summaries"}
    assert len({r["key"] for r in rows}) == 3
    assert rows[1]["csv"] == EXPORTS[("2025-01-01", "2025-12-31")]
    # every period was asked for, the empty ones too
    assert len(page.asked) == len(site.claims_summary_periods(TODAY))


def test_a_refused_export_stops_the_listing_rather_than_call_it_empty(signed_in):
    page = FakePage()
    page.evaluate = lambda js, arg=None: {"status": 500}
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(page, TODAY)


def test_an_export_that_answers_a_sign_in_page_is_an_expired_session(signed_in):
    page = FakePage()
    page.evaluate = lambda js, arg=None: {"status": 200, "html": True}
    with pytest.raises(site.SessionExpired):
        site.list_claims_summaries(page, TODAY)


# -- the PDF -----------------------------------------------------------------

def test_the_pdf_is_a_table_of_every_column_and_claim_with_nothing_unescaped(printed):
    pdf = site.render_claims_summary(FakePage(), "Claims Summary 2025",
                                     EXPORTS[("2025-01-01", "2025-12-31")])
    assert pdf.startswith(b"%PDF")
    html = printed[0]
    for column in COLUMNS:
        assert "<th>%s</th>" % column in html
    assert "9000000AA0002" in html and "9000000AA0004" in html
    assert "Claims Summary 2025" in html
    assert "<b>&</b>" not in html and "&lt;b&gt;&amp;&lt;/b&gt;" in html


# -- the run -----------------------------------------------------------------

@pytest.fixture
def build(tmp_path, monkeypatch, signed_in, printed):
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(site, "claims_summary_periods",
                        lambda today=None, _real=site.claims_summary_periods: _real(TODAY))

    def made(*flags):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), *flags]))
        page = FakePage()
        app._on_its_site = lambda: page
        app.check_session = lambda *_a, **_kw: None
        return app
    return made


def saved(app, suffix):
    return sorted(p.name for p in Path(app.paths.root).rglob("*" + suffix))


def test_each_summary_is_filed_as_a_pdf_with_its_csv_beside_it(build, printed):
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    app.progress.save()
    assert saved(app, ".pdf") == [
        "2024-12-31 Anthem Claims Summary 2024.pdf",
        "2025-12-31 Anthem Claims Summary 2025.pdf",
        "2026-11-11 Anthem Claims Summary 2026 Year to Date.pdf"]
    folder = Path(app.paths.root) / "Claims Summaries"
    assert sorted(p.name for p in folder.glob("*.csv")) == [
        n[:-4] + ".csv" for n in saved(app, ".pdf")]
    assert (folder / "2025-12-31 Anthem Claims Summary 2025.csv").read_bytes() \
        == EXPORTS[("2025-01-01", "2025-12-31")].encode("utf-8")
    assert len(printed) == 3


def test_a_summary_downloaded_once_is_not_printed_again(build, printed):
    first = build("--claims-summaries")
    first.cmd_claims_summaries()
    first.progress.save()
    del printed[:]
    again = build("--claims-summaries")
    again.cmd_claims_summaries()
    assert printed == []
    assert again.stats["skipped_completed"] == 3


def test_run_all_and_resume_take_the_claims_summaries(build, monkeypatch):
    taken = []
    monkeypatch.setattr(app_mod.App, "cmd_claims_summaries", lambda self: taken.append(1))
    for name in ("cmd_documents", "cmd_id_cards", "cmd_letters", "cmd_discover", "process"):
        monkeypatch.setattr(app_mod.App, name, lambda self, *a, **kw: None)
    monkeypatch.setattr(app_mod.App, "_select", lambda self, *a, **kw: [])
    app = build("--all", "--yes")
    app.cmd_run("all")
    monkeypatch.setattr(app_mod.listing, "before_resume", lambda *a, **kw: None)
    monkeypatch.setattr(app_mod.listing, "after_resume", lambda *a, **kw: None)
    build("--resume").cmd_resume()
    assert taken == [1, 1]
