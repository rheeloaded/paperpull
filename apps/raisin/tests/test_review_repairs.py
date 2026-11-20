"""The repairs made after the independent review of the first build, each
with the review's own scenario, on invented values."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import raisin_docs as app_mod
import raisin_site as site
from fake_raisin import CUSTOMER, FakePage, pdf_for
from paperpull_core import delivery, pdf_reader
from paperpull_core.models import State
from paperpull_core.testkit import StrictDelivery, text_pdf


def text(*lines):
    data = text_pdf(list(lines) + ["Dieses Dokument wurde maschinell erstellt."])
    return " ".join(pdf_reader.page_texts(data, pages=3))


@pytest.fixture
def run(monkeypatch, tmp_path):
    site._RUN.clear()

    def make(page=None):
        page = page or FakePage()
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                      "min_pdf_bytes": 100}), encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(config)])
        monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
        app = app_mod.App(args)
        app._work_page = page
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_delay", lambda *a, **kw: None)
        return app, page
    yield make
    site._RUN.clear()


# -- MAJOR 2, a right document is not refused for a title word of another day -----

def test_a_right_document_naming_another_days_title_is_placed(run, monkeypatch):
    page = FakePage()
    page.documents["FDA_t001"] = [
        {"id": "d0011", "created": "2026-03-31", "title": "Kontoauszug März 2026",
         "document_type": "STATEMENT"},
        {"id": "d0012", "created": "2026-02-28", "title": "Zinsbescheinigung",
         "document_type": "INTEREST"}]
    page.files["d0011"] = text_pdf(["Raisin Bank AG", "31.03.2026",
                                    "Kontoauszug fuer Maerz 2026. Ihre Zinsbescheinigung folgt.",
                                    "x" * 40])
    page.files["d0012"] = pdf_for("28.02.2026", "Zinsbescheinigung")
    # The other deposits' documents are left out, since a second
    # Zinsbescheinigung among them would share the word and hide what this
    # shows from the core's check.
    page.documents["OMA_t002"] = page.documents["FDA_t003"] = []
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    assert app.progress.get("id:FDA_t001:d0011")["downloaded_ok"]
    assert not app.stats.get("wrong_document")


def test_the_core_is_handed_only_rows_of_the_same_day(run, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    page = FakePage()
    page.documents["OMA_t002"].append({"id": "d0005", "created": "2026-05-03",
                                       "title": "Kontoauszug", "document_type": "STATEMENT"})
    page.files["d0005"] = pdf_for("03.05.2026", "Kontoauszug")
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    docs = app._select()
    app.process(docs)
    for call, doc in zip(spy.calls, docs):
        labels = sorted(r.label for r in call.arguments["rivals"])
        same_day = sorted(d.title for d in docs if d.date == doc.date and d is not doc)
        assert labels == same_day


# -- MAJOR 1 scenario C, a title seen only inside a longer neighbor title ------------

def test_a_title_seen_only_inside_a_same_day_neighbors_longer_title_is_wrong():
    longer = text("Raisin", "Kontoauszug Tagesgeld", "Datum 30.06.2026")
    rivals = [("2026-06-30", "Kontoauszug Tagesgeld")]
    assert site.check_text(longer, "2026-06-30", "Kontoauszug", rivals)[0] == site.WRONG
    # The longer one's own PDF is its own.
    assert site.check_text(longer, "2026-06-30", "Kontoauszug Tagesgeld",
                           [("2026-06-30", "Kontoauszug")])[0] == ""


# -- MINOR 3, a paged answer is never read as all of it ------------------------------

@pytest.mark.parametrize("more", [
    {"totalPages": 3}, {"last": False}, {"hasMore": True}, {"next": "/page/2"},
    {"totalElements": 9},
])
def test_a_paged_deposits_answer_stops_the_list(more):
    page = FakePage()
    page.body[site.ACTIVE_PATH] = json.dumps({"content": page.active, **more})
    with pytest.raises(site.ListStopped, match="pages"):
        site.collect_documents(page)


@pytest.mark.parametrize("more", [{"totalPages": 2}, {"total": 5}, {"has_more": True}])
def test_a_paged_documents_answer_stops_the_list(more):
    page = FakePage()
    page.body["FDA_t003"] = json.dumps({"documents": page.documents["FDA_t003"], **more})
    with pytest.raises(site.ListStopped, match="pages"):
        site.collect_documents(page)


def test_an_answer_that_says_it_is_all_is_read():
    page = FakePage()
    page.body[site.ACTIVE_PATH] = json.dumps({"content": page.active, "totalPages": 1,
                                              "last": True, "totalElements": 2})
    page.body["FDA_t003"] = json.dumps({"documents": page.documents["FDA_t003"], "total": 1})
    assert len(site.collect_documents(page)) == 3


# -- MINOR 5, a timestamp is the day it was in Germany -------------------------------

@pytest.mark.parametrize("value, day", [
    ("2026-03-31T23:30:00Z", "2026-04-01"),       # summer time, 01:30 the next day
    ("2026-01-31T22:59:00Z", "2026-01-31"),       # winter time, 23:59
    ("2026-01-31T23:00:00Z", "2026-02-01"),
    ("2026-10-25T00:30:00Z", "2026-10-25"),       # the night summer time ends
    ("2026-06-30T23:30:00+02:00", "2026-06-30"),
    ("2026-06-30T23:30:00", "2026-06-30"),        # no zone, the day written
])
def test_a_timestamp_is_the_day_it_was_in_germany(value, day):
    assert site.created_date(value) == day


# -- MINOR 7, contract confirmations are not statements ------------------------------

@pytest.mark.parametrize("title, category", [
    ("Bestätigung Vertragsabschluss", storage.CONTRACT),
    ("Abschlussbestätigung Festgeld", storage.CONTRACT),
    ("Kontoabschluss 2025", "Statement"),
    ("Steuer-ID Bestätigung", storage.CONTRACT),
    ("Jahressteuerbescheinigung 2025", "Tax Document"),
])
def test_titles_are_filed_by_kind(run, title, category):
    app, _ = run()
    raw = site.RawDoc("d1", "FDA_t001", "term_deposits", "2026-01-01", title, "X", "c")
    assert app._classify(raw)[0] == category


# -- MINOR 8, English day-first dates and a customer number in the fragment ----------

def test_an_english_day_first_date_is_read_and_a_slashed_one_never():
    assert site.check_text(text("Raisin", "5 March 2026"), "2026-03-05", "x")[0] == ""
    assert site.check_text(text("Raisin", "05/03/2026"), "2026-03-05", "x")[0] == site.UNCONFIRMED


def test_a_customer_number_in_the_fragment_is_read_by_the_same_rule():
    assert site.customer_of("https://www.raisin.com/#/?customer_id=" + CUSTOMER) == CUSTOMER
    assert site.customer_of("https://www.raisin.com/?customer_id=" + CUSTOMER
                            + "#/?customer_id=BAC_000000000077") == ""
    assert site.customer_of("https://www.raisin.com/#/?customer_id=BAC_x") == ""


# -- MINOR 9, refused files stop the run after a few, and a vanished one is gone -----

def test_three_refused_files_in_a_row_stop_the_run(run):
    page = FakePage()
    page.documents["FDA_t001"] += [{"id": "d000%d" % n, "created": "2026-0%d-01" % n,
                                    "title": "Kontoauszug", "document_type": "S"}
                                   for n in (6, 7, 8)]
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    for doc_id in ("d0001", "d0002", "d0003", "d0006", "d0007", "d0008"):
        page.status[doc_id] = 403
    with pytest.raises(SystemExit):
        app.process(app._select())
    assert app.stats["refused_by_kind"] == {"refused": 3}
    assert len([a for a in page.asked if a[2] == "pdf"]) == 3


def test_a_saved_file_between_refusals_starts_the_count_again(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0002"] = 403
    page.status["d0003"] = 403
    app.process(app._select())
    assert app.stats["refused_by_kind"] == {"refused": 2}
    assert app.progress.get("id:FDA_t001:d0001")["downloaded_ok"]


def test_a_refused_file_no_longer_listed_is_gone(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0002"] = 404

    def vanish(p, path, query):
        if path == site.ACTIVE_PATH and any(a[2] == "pdf" for a in p.asked):
            p.documents["OMA_t002"] = []
    page.on_ask = vanish
    app.process(app._select())
    assert app.stats["refused_by_kind"].get("gone") == 1
    assert app.progress.get("id:OMA_t002:d0002")["state"] == State.FAILED.value


# -- NITs -----------------------------------------------------------------------------

def test_an_empty_document_type_stops_the_list():
    page = FakePage()
    page.documents["OMA_t002"][0]["document_type"] = "  "
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)


def test_the_pilot_report_prints_no_deposit_or_document_id(run, capsys, monkeypatch):
    StrictDelivery(outcome=delivery.NOT_PLACED).install(monkeypatch)
    app, _ = run()
    app.cmd_pilot()
    said = capsys.readouterr().out
    assert "Needs attention" in said
    for value in ("FDA_t001", "OMA_t002", "d0001", "d0002"):
        assert value not in said
