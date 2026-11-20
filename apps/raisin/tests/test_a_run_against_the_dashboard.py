"""Login, Discover, Pilot, Resume and Diagnose against a stand-in dashboard.

Invented customer, deposits, documents and PDFs only. The stand-in answers
what the page's own fetch would (fake_raisin.FakePage).
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import raisin_docs as app_mod
import raisin_site as site
from fake_raisin import CUSTOMER, DASHBOARD, OTHER_CUSTOMER, TOKEN, FakePage, pdf_for
from paperpull_core import listing
from paperpull_core.models import State
from paperpull_core.testkit import text_pdf


@pytest.fixture
def run(monkeypatch, tmp_path):
    site._RUN.clear()
    made = {}

    def make(page=None, *argv):
        page = page or FakePage()
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                      "min_pdf_bytes": 100}), encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(config), *argv])
        monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
        app = app_mod.App(args)
        app._work_page = page
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_delay", lambda *a, **kw: None)
        made["app"] = app
        return app, page
    yield make
    site._RUN.clear()


def pdfs(root):
    return sorted(p for p in Path(root).rglob("*.pdf") if p.is_file())


# -- Login -----------------------------------------------------------------------

def test_login_says_success_only_after_the_lists_answered(run, capsys):
    app, page = run()
    app.cmd_login()
    said = capsys.readouterr().out
    assert "Success" in said
    asked = [p for p, _, _ in page.asked]
    assert asked[:2] == [site.ACTIVE_PATH, site.INACTIVE_PATH]
    assert asked[2] == site.DOCUMENTS_PATH


def test_login_with_no_deposits_rests_on_the_two_deposit_lists(run, capsys):
    page = FakePage()
    page.active, page.inactive = [], []
    app, _ = run(page)
    app.cmd_login()
    assert "Success" in capsys.readouterr().out
    assert [p for p, _, _ in page.asked] == [site.ACTIVE_PATH, site.INACTIVE_PATH]


def _no_token(p):
    del p.storage["auth_token"]


@pytest.mark.parametrize("spoil", [
    lambda p: setattr(p, "url", "https://example.test/"),
    lambda p: setattr(p, "url", "https://www.raisin.com/savings/"),
    _no_token,
    lambda p: p.status.update({site.ACTIVE_PATH: 401}),
    lambda p: p.status.update({site.INACTIVE_PATH: 403}),
    lambda p: p.body.update({site.ACTIVE_PATH: "<html>"}),
    lambda p: p.status.update({"FDA_t001": 500}),
])
def test_login_never_says_success_without_the_lists(run, capsys, spoil):
    page = FakePage()
    spoil(page)
    app, _ = run(page)
    app.cmd_login()
    assert "Success" not in capsys.readouterr().out


# -- Discover and Resume --------------------------------------------------------

def test_discover_reads_every_deposit_then_calls_the_list_whole(run, capsys):
    app, page = run(None, "--discover")
    assert app.cmd_discover() == 3
    assert listing.last(app) == listing.COMPLETE
    keys = sorted(app.discovery.data)
    assert keys == ["id:FDA_t001:d0001", "id:FDA_t003:d0003", "id:OMA_t002:d0002"]
    for rec in app.discovery.data.values():
        assert rec["account"] == site.tag(CUSTOMER)
    cats = {rec["document_id"]: rec["category"] for rec in app.discovery.data.values()}
    assert cats == {"d0001": "Statement", "d0002": "Statement", "d0003": "Tax Document"}


def test_a_contract_title_is_filed_as_a_contract(run):
    page = FakePage()
    page.documents["OMA_t002"][0].update(title="Bestätigung der Kontoeröffnung",
                                          document_type="CONFIRMATION")
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    assert app.discovery.get("id:OMA_t002:d0002")["category"] == storage.CONTRACT


def test_a_list_that_stops_on_the_second_deposit_is_never_whole(run, capsys):
    page = FakePage()
    page.status["OMA_t002"] = 500
    app, _ = run(page)
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED
    assert not app.discovery.data, "a part of a list was recorded"
    # And Resume after it is never clean.
    page.status.clear()
    with pytest.raises(SystemExit):
        app.cmd_resume()
    said = capsys.readouterr().out
    assert "Nothing to resume - everything in scope is complete" not in said


def test_a_sign_out_while_listing_stops_the_run_as_signed_out(run, capsys):
    page = FakePage()
    page.status[site.INACTIVE_PATH] = 401
    app, _ = run(page)
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert "signed out" in capsys.readouterr().out
    assert listing.last(app) == listing.STOPPED


def test_pilot_saves_each_document_under_its_own_name(run, capsys):
    app, page = run(None, "--pilot")
    app.cmd_pilot()
    saved = pdfs(app.paths.root)
    assert len(saved) == 3, capsys.readouterr().out
    assert {p.read_bytes() for p in saved} == set(page.files.values())
    for key in ("id:FDA_t001:d0001", "id:OMA_t002:d0002", "id:FDA_t003:d0003"):
        assert app.progress.get(key)["downloaded_ok"]
    # And a second run asks for no file again.
    before = len([a for a in page.asked if a[2] == "pdf"])
    app.process(app._select())
    assert len([a for a in page.asked if a[2] == "pdf"]) == before


def test_two_documents_on_one_day_are_two_files(run):
    page = FakePage()
    page.documents["OMA_t002"].append({"id": "d0005", "created": "2026-05-03",
                                       "title": "Kontoauszug", "document_type": "STATEMENT"})
    page.files["d0005"] = pdf_for("03.05.2026", "Kontoauszug")
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    assert len(pdfs(app.paths.root)) == 4
    assert app.progress.get("id:OMA_t002:d0005")["downloaded_ok"]
    assert app.progress.get("id:OMA_t002:d0002")["downloaded_ok"]


def test_one_id_under_two_deposits_is_two_records(run):
    page = FakePage()
    page.documents["FDA_t003"] = [dict(page.documents["FDA_t001"][0])]
    app, _ = run(page)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    assert app.progress.get("id:FDA_t001:d0001")["downloaded_ok"]
    assert app.progress.get("id:FDA_t003:d0001")["downloaded_ok"]


def test_a_document_no_longer_listed_is_said_as_gone_and_kept_pending(run, capsys):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.documents["OMA_t002"] = []
    site._RUN.clear()
    app.process(app._select())
    assert "no longer listed" in capsys.readouterr().out
    rec = app.progress.get("id:OMA_t002:d0002")
    assert rec["state"] == State.FAILED.value and not rec.get("downloaded_ok")
    assert app.progress.get("id:FDA_t001:d0001")["downloaded_ok"]


def test_a_refused_file_reads_the_list_again_and_goes_on(run, capsys):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0002"] = 403
    asked = len(page.asked)
    app.process(app._select())
    assert any(p == site.ACTIVE_PATH for p, _, _ in page.asked[asked:]), "the list was not read again"
    assert not app.progress.get("id:OMA_t002:d0002").get("downloaded_ok")
    assert app.progress.get("id:FDA_t001:d0001")["downloaded_ok"]
    assert app.stats["refused_by_kind"] == {"refused": 1}


def test_a_refused_file_whose_list_is_refused_too_stops_as_signed_out(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0001"] = 403
    page.status[site.ACTIVE_PATH] = 401
    with pytest.raises(SystemExit):
        app.process(app._select())
    assert page.files["d0001"] not in {p.read_bytes() for p in pdfs(app.paths.root)}
    assert not app.progress.get("id:FDA_t003:d0003"), "the run went on past a sign-out"


def test_a_file_answered_as_signed_out_stops_the_run_when_the_list_is_too(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0002"] = 401
    page.status[site.ACTIVE_PATH] = 401
    with pytest.raises(SystemExit):
        app.process(app._select())
    assert not app.progress.get("id:OMA_t002:d0002") or \
        not app.progress.get("id:OMA_t002:d0002").get("downloaded_ok")
    assert not app.progress.get("id:FDA_t003:d0003"), "the run went on past a sign-out"


def test_a_file_refused_as_signed_out_while_the_list_answers_is_that_files_alone(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.status["d0002"] = 401
    app.process(app._select())
    assert not app.progress.get("id:OMA_t002:d0002").get("downloaded_ok")
    assert app.progress.get("id:FDA_t003:d0003")["downloaded_ok"]


@pytest.mark.parametrize("data, kind", [
    (pdf_for("03.05.2026", "Kontoauszug"), "wrong"),       # a neighbor's day, read day first
    (pdf_for("05.03.2026", "Kontoauszug", issuer="Musterbank AG"), "unconfirmed"),
    (text_pdf(["Raisin", "ohne Datum", "x" * 60]), "unconfirmed"),
])
def test_a_pdf_that_does_not_show_its_row_is_never_filed(run, data, kind):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.files["d0001"] = data
    app.process(app._select())
    rec = app.progress.get("id:FDA_t001:d0001")
    assert not rec.get("downloaded_ok") and rec["state"] == State.FAILED.value
    assert data not in {p.read_bytes() for p in pdfs(app.paths.root)}
    assert app.stats["refused_by_kind"] == {kind: 1}
    if kind == "wrong":
        assert app.stats["wrong_document"] == 1


def test_another_customers_records_wait_for_their_own_dashboard(run):
    app, page = run()
    app.cmd_discover(quiet=True)
    page.url = DASHBOARD % OTHER_CUSTOMER
    app._customer = ""
    asked = len(page.asked)
    assert app._select() == []
    assert len(page.asked) == asked
    # And a record handed over anyway is refused before anything is asked.
    doc = app_mod.Document.from_dict(app.discovery.get("id:FDA_t001:d0001"))
    with pytest.raises(site.ListStopped, match="Reopen"):
        site.listed_now(page, doc.account, doc.deposit_id, doc.document_id)
    assert len(page.asked) == asked


def test_resume_after_a_whole_list_takes_only_what_is_left(run, capsys):
    app, page = run()
    app.cmd_discover(quiet=True)
    app.process(app._select()[:1])
    site._RUN.clear()
    app.stats["mode"] = "resume"
    app.cmd_resume()
    assert len(pdfs(app.paths.root)) == 3
    assert "Resuming: 2 document(s) remaining." in capsys.readouterr().out


def test_a_tab_on_raisin_without_the_dashboard_is_told_to_open_it(run, capsys):
    page = FakePage()
    page.url = "https://www.raisin.com/savings/"
    app, _ = run(page)
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert "not on your dashboard" in capsys.readouterr().out
    assert not page.asked


def test_a_tab_of_another_site_is_never_read(run, capsys):
    page = FakePage()
    page.url = "https://example.test/?customer_id=" + CUSTOMER
    app, _ = run(page)
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert not page.asked


# -- privacy --------------------------------------------------------------------

def _everything_written(root):
    out = b""
    for p in Path(root).rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


def test_the_token_and_customer_number_reach_no_file_line_or_log(run, capsys, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    app, page = run()
    app.cmd_login()
    app, page = run()
    app.cmd_discover()
    page.files["d0001"] = pdf_for("05.03.2026", "Kontoauszug", issuer="Musterbank AG")
    page.status["d0002"] = 500
    app.process(app._select())
    app.stats["mode"] = "diagnose"
    app.cmd_diagnose()
    app.write_survey()
    app.write_failure("check the document pdf", "the pdf did not show its row")
    app.progress.save()
    app.discovery.save()
    seen = capsys.readouterr()
    digits = CUSTOMER.split("_", 1)[1]
    for canary in (TOKEN, CUSTOMER, digits):
        written = _everything_written(tmp_path)
        assert canary.encode() not in written
        assert canary.encode("utf-16-le") not in written
        assert canary not in seen.out and canary not in seen.err
        assert canary not in caplog.text
    assert list(app.paths.diagnostics.glob("diagnose-documents.json"))


def test_diagnose_says_counts_and_states(run):
    app, page = run()
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert info["documents_total"] == 3
    assert info["deposits"] == {"term_deposits": 2, "overnight_savings": 1}
    assert info["token_present"] is True and info["customer_id_in_address"] is True
    text = json.dumps(info)
    for value in ("d0001", "FDA_t001", "Kontoauszug", "2026-03-05", "ACCOUNT_STATEMENT"):
        assert value not in text


def test_diagnose_on_a_stopped_list_says_where_and_the_answers_shape(run):
    page = FakePage()
    page.body[site.ACTIVE_PATH] = json.dumps({"unknownKey": [{"x": "BAC_000000000042"}]})
    app, _ = run(page)
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert info["error"] == "ListStopped"
    assert "deposits_active" in info["shapes"]
    assert "000000000042" not in json.dumps(info)
