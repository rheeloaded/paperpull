"""One file, one record; every run lists afresh; each account keeps its own
token and name; and nothing that opens, orders or moves anything passes as
a document control."""
import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import amexbanking_site as site
from amexbanking_docs import App, Document
from paperpull_core import testkit
from paperpull_core.models import State
from storage import SPEC


class DummyArgs(SimpleNamespace):
    def __init__(self, **kw):
        base = dict(config="", redownload=False, max_docs=None, dry_run=False,
                    start_date=None, end_date=None, year=None, type=None,
                    apply=False, yes=False)
        base.update(kw)
        super().__init__(**base)


@pytest.fixture(autouse=True)
def fresh_session():
    site.SESSION = site.BankingSession()
    yield


@pytest.fixture
def app_env(tmp_path):
    from paperpull_core import storage
    storage.bind(SPEC)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "owner": "biz", "output_dir": ".", "min_pdf_bytes": 10,
        "max_path_length": 240,
    }), encoding="utf-8")
    return App(DummyArgs(config=str(cfg_path))), tmp_path


def _pdf(path: _Path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(testkit.text_pdf([text]))
    return path


def _doc(date="2025-12-31", category="Tax Document", doc_id="URN:DOC:TX:AAAAAA", title="FORM_1099_INT Tax Form"):
    return Document(title=title, date=date, category=category, summary=category,
                    account="AmexBiz 1234", document_id=doc_id)


# --- the index holds each file once -----------------------------------------

def test_reconcile_counts_a_relative_and_an_absolute_path_as_one_file(app_env, monkeypatch):
    app, root = app_env
    pdf = _pdf(root / "Statements" / "2026-10-31 Statement.pdf")
    doc = _doc("2026-10-31", "Statement", "URN:DOC:BS:111111", "Business Checking Statement")
    # The index already names the file by its absolute path...
    app.index_csv.append_rows([{"PDF Full Path": str(pdf), "Document Date": doc.date}])
    # ...and the record by the path relative to where an older run started.
    app.progress.update(doc.key, dict(doc.to_dict(), downloaded_ok=True,
                                      state=State.PDF_VERIFIED.value,
                                      pdf_path="Statements/2026-10-31 Statement.pdf"))
    monkeypatch.chdir(root.parent)  # the relative path no longer works from cwd
    app._reconcile_index()
    assert len(app.index_csv.read_all()) == 1


def test_reconcile_takes_repeated_rows_out_of_the_index(app_env):
    app, root = app_env
    pdf = str(_pdf(root / "Statements" / "2026-10-31 Statement.pdf"))
    app.index_csv.append_rows([{"PDF Full Path": pdf}, {"PDF Full Path": pdf},
                               {"PDF Full Path": ""}])
    app._reconcile_index()
    rows = app.index_csv.read_all()
    assert [r["PDF Full Path"] for r in rows] == [pdf, ""]


# --- a document is not taken for another one of the same day -----------------

def test_a_second_form_of_the_same_year_is_not_taken_for_the_first(app_env):
    app, root = app_env
    first = _doc(doc_id="URN:DOC:TX:INT001")
    second = _doc(doc_id="URN:DOC:TX:MSC002", title="FORM_1099_MISC Tax Form")
    pdf = _pdf(app.paths.folder_for("Tax Document") / "2025-12-31 Tax Document.pdf")
    app.progress.update(first.key, dict(first.to_dict(), downloaded_ok=True,
                                        state=State.PDF_VERIFIED.value, pdf_path=str(pdf)))
    assert app._already_done(second) is False


def test_the_file_named_with_its_id_is_taken_among_several(app_env):
    app, root = app_env
    folder = app.paths.folder_for("Tax Document")
    _pdf(folder / "2025-12-31 Tax Document.pdf")
    mine = _pdf(folder / "2025-12-31 Tax Document MSC002.pdf")
    doc = _doc(doc_id="URN:DOC:TX:MSC002")
    assert app._already_done(doc) is True
    assert app.progress.get(doc.key)["pdf_path"] == str(mine)


def test_several_unclaimed_files_of_the_day_are_not_guessed_at(app_env):
    app, root = app_env
    folder = app.paths.folder_for("Tax Document")
    _pdf(folder / "2025-12-31 Tax Document.pdf")
    _pdf(folder / "2025-12-31 Tax Document 2.pdf")
    assert app._already_done(_doc()) is False


def test_a_document_without_a_date_matches_no_file(app_env):
    app, root = app_env
    _pdf(app.paths.folder_for("Statement") / "2026-10-31 Statement.pdf")
    assert app._already_done(_doc(date="", category="Statement")) is False


# --- every run reads the list ------------------------------------------------

@pytest.mark.parametrize("mode, listed", [("all", True), ("resume", False)])
def test_a_full_run_lists_again_and_a_resume_does_not(app_env, mode, listed):
    app, _ = app_env
    app.discovery.data["id:x"] = _doc().to_dict()
    app.cmd_discover = MagicMock(return_value=0)
    app.process = MagicMock()
    app.write_run_summary = MagicMock()
    app.cmd_run(mode)
    assert app.cmd_discover.called is listed


def test_pilot_lists_again(app_env):
    app, _ = app_env
    app.discovery.data["id:x"] = _doc().to_dict()
    app.cmd_discover = MagicMock(return_value=0)
    app.process = MagicMock()
    app.write_run_summary = MagicMock()
    app.cmd_pilot()
    assert app.cmd_discover.called


# --- an empty listing is not a whole one --------------------------------------

@pytest.mark.parametrize("captured, whole", [([], False), (["one"], True)])
def test_only_a_listing_that_captured_something_is_whole(app_env, monkeypatch, captured, whole):
    app, _ = app_env
    raw = [site.RawDoc(title="Business Checking Statement", date_text="2026-10-31",
                       document_id="URN:DOC:BS:1")] if captured else []
    monkeypatch.setattr(app, "page", lambda: MagicMock())
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "collect_documents", lambda page: raw)
    called = []
    import amexbanking_docs
    monkeypatch.setattr(amexbanking_docs.listing, "read_whole", lambda a: called.append(a))
    app.cmd_discover(quiet=True)
    assert bool(called) is whole


# --- each account keeps its own token and name -------------------------------

def _listener(url="https://www.americanexpress.com/en-us/banking/personal/savings/accounts/x"):
    page = MagicMock()
    page.url = url
    page._banking_listener_attached = False
    handlers = {}
    page.on.side_effect = lambda ev, fn: handlers.__setitem__(ev, fn)
    site.attach_banking_listener(page, site.SESSION)
    return handlers


def _request(token, url="https://functions.americanexpress.com/ReadBankingAccountDocumentList.v1"):
    return SimpleNamespace(url=url, post_data=json.dumps({"accountToken": token}))


def test_a_later_request_replaces_the_token_an_earlier_account_left():
    handlers = _listener()
    handlers["request"](_request("tok-checking"))
    handlers["request"](_request("tok-savings"))
    assert site.SESSION.account_token == "tok-savings"


def test_a_list_is_filed_under_the_token_it_was_asked_for():
    handlers = _listener()
    site.SESSION.account_token = "tok-somebody-else"
    response = SimpleNamespace(
        url="https://functions.americanexpress.com/ReadBankingAccountDocumentList.v1",
        status=200, request=_request("tok-savings"),
        json=lambda: {"statements": [{"statementMonth": "10", "statementYear": "2026",
                                      "documentIdentifier": "URN:DOC:1"}]})
    handlers["response"](response)
    (doc,) = site.SESSION.captured_docs
    assert doc.account_token == "tok-savings"
    # No label configured or detected: named from the page's address, not "Business Checking"
    assert doc.account == "Personal Savings"
    assert doc.title == "Personal Savings Statement"


@pytest.mark.parametrize("url, kind", [
    ("https://www.americanexpress.com/en-us/banking/business/checking/accounts/t", "Business Checking"),
    ("https://www.americanexpress.com/en-us/banking/personal/checking/accounts/t", "Personal Checking"),
    ("https://www.americanexpress.com/en-us/banking/personal/savings/accounts/t", "Personal Savings"),
    ("https://www.americanexpress.com/en-us/banking/", "American Express Banking"),
])
def test_account_kind_from_url(url, kind):
    assert site.account_kind_from_url(url) == kind


def test_the_first_record_discovered_does_not_choose_the_account(tmp_path):
    from paperpull_core import storage
    storage.bind(SPEC)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"output_dir": ".", "owner": "biz"}), encoding="utf-8")
    (tmp_path / "discovery.json").write_text(json.dumps(
        {"id:old": dict(_doc().to_dict(), account_token="tok-old", account="Old 0000")}),
        encoding="utf-8")
    App(DummyArgs(config=str(cfg)))
    assert site.SESSION.account_token == ""
    assert site.SESSION.account_label == ""


# --- controls ----------------------------------------------------------------

@pytest.mark.parametrize("name", [
    # Every control the 2026-11-08 survey marked safe that is not a document
    "Open New Account", "View All Account Details", "View All Gift Cards",
    "Download the App", "Order Checks", "Give Feedback", "Go to Business Line of Credit",
    "Send a Payment", "Make a Payment", "Scheduled Payments",
])
def test_controls_that_are_not_documents_are_not_safe(name):
    assert site.is_safe_control(name) is False


@pytest.mark.parametrize("name", ["Documents and Statements", "Download Statement (PDF)",
                                  "View 1099 Tax Form", "Print Statement"])
def test_document_controls_stay_safe(name):
    assert site.is_safe_control(name) is True
