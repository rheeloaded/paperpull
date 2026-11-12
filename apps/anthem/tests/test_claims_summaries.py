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


def test_a_refused_export_is_named_rather_than_called_empty(signed_in):
    page = FakePage()
    page.evaluate = lambda js, arg=None: {"status": 500}
    got = site.list_claims_summaries(page, TODAY)
    assert list(got) == []
    assert got.refused == [p["label"] for p in site.claims_summary_periods(TODAY)]


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
    monkeypatch.setattr(site, "_today", lambda: TODAY)

    def made(*flags):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), *flags]))
        page = FakePage()
        app._on_its_site = lambda: page
        app.check_session = lambda *_a, **_kw: None
        app.fake_page = page
        # Each pause between two asks of the export, as the app's own.
        app.paused = 0

        def delay(factor=1.0):
            app.paused += 1
        app._delay = delay
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


# -- a year just ended waits -------------------------------------------------

@pytest.mark.parametrize("today, waits, files_from", [
    (date(2026, 1, 1), True, "2026-03-31"),
    (date(2026, 1, 15), True, "2026-03-31"),
    (date(2026, 3, 30), True, "2026-03-31"),
    (date(2026, 3, 31), False, None),
    (date(2026, 11, 11), False, None),
    (date(2024, 3, 29), True, "2024-03-30"),
    (date(2024, 3, 30), False, None),
])
def test_a_year_is_filed_only_once_90_days_have_passed_since_it_ended(today, waits, files_from):
    last = str(today.year - 1)
    periods = [p["period"] for p in site.claims_summary_periods(today)]
    waiting = site.claims_summaries_waiting(today)
    assert periods[0] == "%d-%02d" % (today.year, today.month)
    assert (last in periods) is not waits
    assert waiting == ([{"period": last, "label": "Claims Summary " + last,
                         "files_from": files_from}] if waits else [])
    # The years before it are filed as before, five back in all.
    assert periods[1 if waits else 2:] == [str(y) for y in range(today.year - 2, today.year - 6, -1)]


def test_a_run_in_january_leaves_the_year_just_ended_for_later(build, monkeypatch, capsys):
    monkeypatch.setattr(site, "_today", lambda: date(2026, 1, 15))
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    assert ("2025-01-01", "2025-12-31") not in app.fake_page.asked
    assert saved(app, ".pdf") == ["2024-12-31 Anthem Claims Summary 2024.pdf"]
    assert "Claims Summary 2025 is filed from 2026-03-31, 90 days after its year ended" \
        in capsys.readouterr().out
    app.progress.save()

    monkeypatch.setattr(site, "_today", lambda: date(2026, 3, 31))
    later = build("--claims-summaries")
    later.cmd_claims_summaries()
    assert ("2025-01-01", "2025-12-31") in later.fake_page.asked
    assert "2025-12-31 Anthem Claims Summary 2025.pdf" in saved(later, ".pdf")
    assert "is filed from" not in capsys.readouterr().out


# -- what is asked for, and how fast -----------------------------------------

def test_a_summary_saved_before_is_not_asked_for_again(build):
    first = build("--claims-summaries")
    first.cmd_claims_summaries()
    first.progress.save()
    every = list(first.fake_page.asked)
    assert len(every) == len(site.claims_summary_periods(TODAY))
    again = build("--claims-summaries")
    again.cmd_claims_summaries()
    held = {("2026-01-01", "2026-11-11"), ("2025-01-01", "2025-12-31"), ("2024-01-01", "2024-12-31")}
    assert again.fake_page.asked == [a for a in every if a not in held]
    restore = build("--claims-summaries", "--redownload")
    restore.cmd_claims_summaries()
    assert restore.fake_page.asked == every


def test_a_summary_outside_the_runs_dates_is_not_asked_for(build):
    app = build("--claims-summaries", "--year", "2024")
    app.cmd_claims_summaries()
    assert app.fake_page.asked == [("2024-01-01", "2024-12-31")]
    assert saved(app, ".pdf") == ["2024-12-31 Anthem Claims Summary 2024.pdf"]


def test_the_asks_are_paced_as_the_apps_other_calls(build):
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    assert len(app.fake_page.asked) > 1
    assert app.paused == len(app.fake_page.asked) - 1


# -- the CSV beside each summary ---------------------------------------------

def records(app):
    return json.loads(Path(app.paths.progress_json).read_text(encoding="utf-8"))


def test_the_csv_is_listed_in_its_summarys_record_as_anthem_handed_it_over(build, monkeypatch):
    with_bom = dict(EXPORTS)
    with_bom[("2025-01-01", "2025-12-31")] = chr(0xFEFF) + EXPORTS[("2025-01-01", "2025-12-31")]
    app = build("--claims-summaries")
    app.fake_page.exports = with_bom
    app.cmd_claims_summaries()
    app.progress.save()
    rec = records(app)["claims:2025"]
    pdf, csv = (Path(e["file"]) for e in rec["invoices"])
    assert pdf == Path(rec["pdf_path"]) and pdf.suffix == ".pdf"
    assert csv == pdf.with_suffix(".csv")
    assert csv.read_bytes() == with_bom[("2025-01-01", "2025-12-31")].encode("utf-8")
    assert all(e["kept"] for e in rec["invoices"])


@pytest.mark.parametrize("gone", [".csv", ".pdf", "both"])
def test_a_csv_deleted_after_its_summary_was_saved_is_never_written_again(build, gone):
    first = build("--claims-summaries")
    first.cmd_claims_summaries()
    first.progress.save()
    folder = Path(first.paths.root) / "Claims Summaries"
    for p in folder.iterdir():
        if gone == "both" or p.suffix == gone:
            p.unlink()
    left = sorted(p.name for p in folder.iterdir())
    again = build("--claims-summaries")
    again.cmd_claims_summaries()
    assert sorted(p.name for p in folder.iterdir()) == left


def test_a_csv_that_cannot_be_written_fails_its_summary_and_the_run_goes_on(build, monkeypatch):
    real = Path.write_bytes

    def write_bytes(self, data):
        if self.suffix == ".csv" and "2025" in self.name:
            raise OSError("invented: the disk is full")
        return real(self, data)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    app.progress.save()
    assert app.stats["failed"] == 1
    assert "claims:2025" not in records(app)
    assert {k for k, r in records(app).items() if r.get("downloaded_ok")} == {
        "claims:2026-11", "claims:2024"}
    # Nothing of the failed summary is left behind, so the next run's copy
    # takes its own name.
    assert not [n for n in saved(app, "") if "2025" in n]
    monkeypatch.setattr(Path, "write_bytes", real)
    again = build("--claims-summaries")
    again.cmd_claims_summaries()
    assert "2025-12-31 Anthem Claims Summary 2025.pdf" in saved(again, ".pdf")
    assert "2025-12-31 Anthem Claims Summary 2025.csv" in saved(again, ".csv")


def test_a_summary_that_fails_its_check_takes_its_csv_to_manual_review(build, monkeypatch):
    monkeypatch.setattr(app_mod.receipt_pdf, "validate_pdf", lambda path, min_bytes: SimpleNamespace(
        ok=False, reason="invented", size_bytes=0, page_count=0))
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    assert not list((Path(app.paths.root) / "Claims Summaries").iterdir())
    review = sorted(p.suffix for p in Path(app.paths.manual_review).iterdir())
    assert review == [".csv"] * 3 + [".pdf"] * 3
    assert not any(r.get("invoices") for r in app.progress.data.values())


def test_a_rename_takes_each_csv_with_its_summary(build, printed, tmp_path, capsys):
    """The app's own Rename, under a naming pattern set after the download,
    moves each CSV with its PDF and the record follows both."""
    from paperpull_core import storage as core_storage
    app = build("--claims-summaries")
    app.cmd_claims_summaries()
    app.progress.save()

    def on_disk():
        return {p.read_bytes(): p for p in Path(app.paths.root).rglob("*")
                if p.is_file() and p.suffix in (".pdf", ".csv") and "Claims Summaries" in p.parts}
    before = on_disk()
    assert len(before) == 6
    cfg = tmp_path / "config.json"
    config = json.loads(cfg.read_text(encoding="utf-8"))
    config["filename_pattern"] = "{provider}/{date:yyyy-mm-dd} Renamed[ {kind}]"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    try:
        capsys.readouterr()
        renamer = app_mod.App(app_mod.build_parser().parse_args(
            ["--config", str(cfg), "--rename", "--apply"]))
        renamer.cmd_rename()
        said = capsys.readouterr().out
        after = on_disk()
        assert set(after) == set(before), said
        for body, path in after.items():
            assert path != before[body] and "Renamed" in path.name, said
        for rec in records(renamer).values():
            pdf, csv = (Path(e["file"]) for e in rec["invoices"])
            assert pdf.is_file() and csv.is_file() and csv == pdf.with_suffix(".csv")
            assert Path(rec["pdf_path"]) == pdf
            assert csv.read_bytes() in [e.encode("utf-8") for e in EXPORTS.values()]
        again = app_mod.App(app_mod.build_parser().parse_args(
            ["--config", str(cfg), "--rename", "--apply"]))
        again.cmd_rename()
        assert "already named" in capsys.readouterr().out
        assert on_disk() == after
    finally:
        core_storage.set_filename_patterns({})


# -- a period whose answer did not come --------------------------------------

def no_file_for(app, start):
    """The export answers the period starting `start` with no file."""
    real = app.fake_page.evaluate

    def evaluate(js, arg=None):
        got = real(js, arg)
        return {"status": 200, "type": "text/csv", "file": None} if arg["start"] == start else got
    app.fake_page.evaluate = evaluate


def test_the_middle_of_three_periods_that_did_not_come_leaves_the_others_saved(build, monkeypatch,
                                                                                capsys):
    monkeypatch.setattr(site, "CLAIMS_SUMMARY_YEARS", 3)
    app = build("--claims-summaries")
    no_file_for(app, "2025-01-01")
    app.cmd_claims_summaries()
    app.progress.save()
    assert app.fake_page.asked == [("2026-01-01", "2026-11-11"), ("2025-01-01", "2025-12-31"),
                                   ("2024-01-01", "2024-12-31")]
    assert saved(app, ".pdf") == ["2024-12-31 Anthem Claims Summary 2024.pdf",
                                  "2026-11-11 Anthem Claims Summary 2026 Year to Date.pdf"]
    assert app.stats["failed"] == 1
    assert "claims:2025" not in records(app)
    said = capsys.readouterr().out
    assert "Claims Summary 2025 did not come as the claims list, so it is not saved" in said
    text = "".join(p.read_text(encoding="utf-8") for p in Path(app.paths.diagnostics).rglob("*")
                   if p.is_file() and "failure" in p.name)
    assert "a claims summary was not read" in text

    again = build("--claims-summaries")
    again.cmd_claims_summaries()
    assert again.fake_page.asked == [("2025-01-01", "2025-12-31")]
    assert "2025-12-31 Anthem Claims Summary 2025.pdf" in saved(again, ".pdf")
    assert not again.stats["failed"]


def test_a_run_with_a_period_that_did_not_come_does_not_end_clean(build, monkeypatch, tmp_path):
    monkeypatch.setattr(site, "CLAIMS_SUMMARY_YEARS", 3)
    page = FakePage()
    real = page.evaluate
    page.evaluate = lambda js, arg=None: (
        {"status": 500} if arg["start"] == "2025-01-01" else real(js, arg))
    monkeypatch.setattr(app_mod.App, "_on_its_site", lambda self: page)
    monkeypatch.setattr(app_mod.App, "check_session", lambda *_a, **_kw: None)
    build("--claims-summaries")
    assert app_mod.main(["--config", str(tmp_path / "config.json"), "--claims-summaries"]) == 1
    # The two that came were asked and saved, 2025's 500 answered by the stand-in.
    assert page.asked == [("2026-01-01", "2026-11-11"), ("2024-01-01", "2024-12-31")]


def test_a_sign_in_in_the_middle_saves_nothing_and_asks_no_more(build, monkeypatch):
    monkeypatch.setattr(site, "CLAIMS_SUMMARY_YEARS", 3)
    monkeypatch.setattr(site, "prime_session", lambda page, force=False: not force)
    app = build("--claims-summaries")
    real = app.fake_page.evaluate
    app.fake_page.evaluate = lambda js, arg=None: (
        {"status": 401} if arg["start"] == "2025-01-01" else real(js, arg))
    app.cmd_claims_summaries()
    assert app.stats.get("session_expired") == 1
    assert saved(app, ".pdf") == []
    assert ("2024-01-01", "2024-12-31") not in app.fake_page.asked
