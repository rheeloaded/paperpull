"""One document, one record, asked for by its own id and its own account's
token; every run but Resume lists afresh; a list is whole only when every
part of it was read; and nothing that opens, orders or moves anything
passes as a document control."""
import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import amexbanking_docs
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
        "owner": "biz", "output_dir": str(tmp_path), "min_pdf_bytes": 10,
        "max_path_length": 240, "delay_min_seconds": 0, "delay_max_seconds": 0,
    }), encoding="utf-8")
    return App(DummyArgs(config=str(cfg_path))), tmp_path


def _pdf(path: _Path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(testkit.text_pdf([text]))
    return path


def _doc(date="2025-12-31", category="Tax Document", doc_id="URN:DOC:TX:AAAAAA",
         title="FORM_1099_INT Tax Form", token="tok-checking"):
    return Document(title=title, date=date, category=category, summary=category,
                    account="AmexBiz 1234", document_id=doc_id, account_token=token)


def _raw(doc_id="URN:DOC:BS:1", date="2026-10-31", token="tok-checking"):
    return site.RawDoc(title="Business Checking Statement", date_text=date,
                       href=doc_id, document_id=doc_id, account="Business Checking",
                       account_token=token)


# --- a document is not taken for another one of the same day -----------------

def test_a_second_form_of_the_same_year_is_not_taken_for_the_first(app_env):
    app, root = app_env
    first = _doc(doc_id="URN:DOC:TX:INT001")
    second = _doc(doc_id="URN:DOC:TX:MSC002", title="FORM_1099_MISC Tax Form")
    pdf = _pdf(app.paths.folder_for("Tax Document") / "2025-12-31 Tax Document.pdf")
    app.progress.update(first.key, dict(first.to_dict(), downloaded_ok=True,
                                        state=State.PDF_VERIFIED.value, pdf_path=str(pdf)))
    assert app._already_done(second) is False


# --- every run but Resume reads the list -------------------------------------

def test_run_all_lists_again(app_env):
    app, _ = app_env
    app.args.yes = True
    app.discovery.data["id:x"] = _doc().to_dict()
    app.cmd_discover = MagicMock(return_value=0)
    app.process = MagicMock()
    app.cmd_run("all")
    assert app.cmd_discover.called


def test_pilot_lists_again(app_env):
    app, _ = app_env
    app.discovery.data["id:x"] = _doc().to_dict()
    app.cmd_discover = MagicMock(return_value=0)
    app.process = MagicMock()
    app.cmd_pilot()
    assert app.cmd_discover.called


def test_resume_reads_no_list(app_env):
    app, _ = app_env
    app.discovery.data["id:x"] = _doc().to_dict()
    app.cmd_discover = MagicMock(return_value=0)
    app.process = MagicMock()
    app.cmd_resume()
    assert not app.cmd_discover.called
    assert app.process.called


# --- a list is whole only when all of it was read ----------------------------

def _discover(app, monkeypatch, listed, finish=True):
    page = MagicMock()
    page.url = site.DOCUMENTS_URL
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(app, "write_failure", lambda *a, **k: None)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "collect_documents", lambda page: listed)
    called = []
    monkeypatch.setattr(amexbanking_docs.listing, "read_whole", lambda a: called.append(a))
    return called


def test_a_list_read_through_is_whole(app_env, monkeypatch):
    app, _ = app_env
    called = _discover(app, monkeypatch, site._listed([_raw()]))
    app.cmd_discover(quiet=True)
    assert called
    assert "id:URN:DOC:BS:1" in app.discovery.data


def test_a_list_that_answered_empty_is_not_whole_and_stops_nothing(app_env, monkeypatch):
    app, _ = app_env
    called = _discover(app, monkeypatch, site._listed([], {site.EMPTY_LIST}))
    app.cmd_discover(quiet=True)
    assert not called


@pytest.mark.parametrize("part", [site.NO_DATE, site.NO_ID, site.UNKNOWN_KIND,
                                  site.NO_ANSWER, site.SHORT_OF_COUNT,
                                  site.SEVERAL_ACCOUNTS, site.NO_TOKEN])
def test_a_part_passed_over_keeps_what_was_read_and_stops_the_run(app_env, monkeypatch, part):
    app, _ = app_env
    called = _discover(app, monkeypatch, site._listed([_raw()], {part}))
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert not called
    assert "id:URN:DOC:BS:1" in app.discovery.data


def test_run_all_takes_what_was_read_then_stops(app_env, monkeypatch):
    app, _ = app_env
    _discover(app, monkeypatch, site._listed([_raw()], {site.NO_DATE}))
    app.args.yes = True
    app.process = MagicMock()
    with pytest.raises(SystemExit):
        app.cmd_run("all")
    (taken,), _ = app.process.call_args
    assert [d.document_id for d in taken] == ["URN:DOC:BS:1"]


def test_a_list_that_never_answered_stops_the_run_unread(app_env, monkeypatch):
    app, _ = app_env
    called = _discover(app, monkeypatch, None)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert not called


def test_a_list_refused_as_signed_out_stops_the_run(app_env, monkeypatch):
    app, _ = app_env
    called = _discover(app, monkeypatch, None)

    def refused(page):
        raise site.SessionExpired("refused")
    monkeypatch.setattr(site, "collect_documents", refused)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert not called


# --- each account keeps its own token and name -------------------------------

class Page:
    """A Documents and Statements tab, its switcher showing `name` and
    `number`, or none at all."""

    def __init__(self, url=site.DOCUMENTS_URL, name="", number=""):
        self.url = url
        self.name, self.number = name, number
        self.handlers = {}

    def on(self, event, fn):
        self.handlers[event] = fn

    def locator(self, sel):
        return _Loc(self, sel)


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def count(self):
        if "display_name" in self.sel:
            return 1 if self.page.name else 0
        if "display_number" in self.sel:
            return 1 if self.page.number else 0
        if "switcher" in self.sel:
            return 1 if self.page.name else 0
        return 0

    @property
    def first(self):
        return self

    def is_visible(self):
        return self.count() > 0

    def locator(self, sel):
        return _Loc(self.page, sel)

    def inner_text(self, timeout=None):
        if "display_name" in self.sel:
            return self.page.name
        if "display_number" in self.sel:
            return self.page.number
        return ""


def _request(token):
    return SimpleNamespace(url=site.LIST_URL,
                           post_data=json.dumps({"accountToken": token}) if token else None)


def _answer(page, token="tok-checking", status=200, statements=None):
    statements = [{"statementMonth": "10", "statementYear": "2026",
                   "documentIdentifier": "URN:DOC:1"}] if statements is None else statements
    page.handlers["response"](SimpleNamespace(
        url=site.LIST_URL, status=status, request=_request(token),
        json=lambda: {"statements": statements, "totalCount": len(statements)}))


def _heard(page):
    site.attach_banking_listener(page, site.SESSION)
    return page


def test_a_list_is_filed_under_the_token_it_was_asked_for():
    page = _heard(Page(url="https://www.americanexpress.com/en-us/banking/personal/savings/accounts/x"))
    _answer(page, token="tok-savings")
    listed = site.collect_documents(page)
    (doc,) = listed
    assert listed.passed_over == ()
    assert doc.account_token == "tok-savings"
    # No label configured or shown, so named from the page's address
    assert doc.account == "Personal Savings"
    assert doc.title == "Personal Savings Statement"


def test_the_account_is_read_from_the_page_once_its_list_answered():
    """The switcher is read on the page the list came from, not the one the
    run found the tab on, which may show another account."""
    page = Page(url="https://www.americanexpress.com/en-us/banking/personal/savings/accounts/x",
                name="Old Account", number="0000")
    page.wait_for_timeout = lambda ms: None

    def goto(url, **kw):
        page.url = url
        page.name, page.number = "Business Checking", "•••• 4321"
        _answer(page)
    page.goto = goto
    assert site.ensure_statements(page)
    (doc,) = site.collect_documents(page)
    assert doc.account == "Business Checking 4321"


def test_the_page_text_is_not_read_for_an_account():
    page = Page()
    page.locator = lambda sel: MagicMock(
        count=lambda: 0, first=MagicMock(inner_text=lambda: "Send a Payment •••• 2024"))
    assert site.detect_account_label(page) == ""


def test_lists_of_two_accounts_are_not_taken():
    page = _heard(Page())
    _answer(page, token="tok-checking")
    _answer(page, token="tok-savings",
            statements=[{"statementMonth": "10", "statementYear": "2026",
                         "documentIdentifier": "URN:DOC:2"}])
    listed = site.collect_documents(page)
    assert list(listed) == []
    assert site.SEVERAL_ACCOUNTS in listed.passed_over


def test_a_list_asked_for_no_account_is_passed_over():
    page = _heard(Page())
    _answer(page, token="")
    listed = site.collect_documents(page)
    assert list(listed) == []
    assert site.NO_TOKEN in listed.passed_over


def test_a_list_that_failed_is_passed_over():
    page = _heard(Page())
    _answer(page)
    _answer(page, status=500)
    listed = site.collect_documents(page)
    assert [d.document_id for d in listed] == ["URN:DOC:1"]
    assert site.NO_ANSWER in listed.passed_over


@pytest.mark.parametrize("status", [401, 403])
def test_a_list_refused_raises_session_expired(status):
    page = _heard(Page())
    _answer(page, status=status)
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)


def test_a_list_heard_before_the_page_loaded_again_is_let_go(monkeypatch):
    page = _heard(Page())
    _answer(page, token="tok-before")
    page.reload = lambda **kw: _answer(page, token="tok-now")
    page.wait_for_timeout = lambda ms: None
    assert site.goto_documents(page)
    (doc,) = site.collect_documents(page)
    assert doc.account_token == "tok-now"


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
    cfg.write_text(json.dumps({"output_dir": str(tmp_path), "owner": "biz"}), encoding="utf-8")
    (tmp_path / "discovery.json").write_text(json.dumps(
        {"id:old": dict(_doc().to_dict(), account_token="tok-old", account="Old 0000")}),
        encoding="utf-8")
    App(DummyArgs(config=str(cfg)))
    assert site.SESSION.account_label == ""
    assert site.SESSION.label_configured is False


def test_a_document_known_already_keeps_its_account_and_token(app_env):
    app, _ = app_env
    app._record_discover_doc(_raw(token="tok-before"))
    again = _raw(token="tok-now")
    again.account = "Another Account"
    app._record_discover_doc(again)
    rec = app.discovery.data["id:URN:DOC:BS:1"]
    assert rec["account_token"] == "tok-before"
    assert rec["account"] == "Business Checking"


# --- a config is tied to the account its records hold ------------------------

def _held(app, token="tok-checking", digits="1234"):
    rec = dict(_doc(doc_id="URN:DOC:TX:OLD", token=token).to_dict(), account_digits=digits)
    app.discovery.data[_doc(doc_id="URN:DOC:TX:OLD").key] = rec
    app.progress.data[_doc(doc_id="URN:DOC:TX:OLD").key] = dict(rec, downloaded_ok=True,
                                                                  state=State.COMPLETED.value)


def _another(token="tok-checking", digits="1234"):
    raw = _raw(doc_id="URN:DOC:BS:NEW", token=token)
    raw.account_digits = digits
    return site._listed([raw], token=token, digits=digits)


@pytest.mark.parametrize("token, digits", [("tok-other", "1234"), ("tok-checking", "9999"),
                                           ("tok-other", "")])
def test_a_list_of_another_account_stops_the_run_before_anything_is_taken(
        app_env, monkeypatch, capsys, token, digits):
    app, _ = app_env
    _held(app)
    called = _discover(app, monkeypatch, _another(token, digits))
    app.args.yes = True
    app.process = MagicMock()
    with pytest.raises(SystemExit):
        app.cmd_run("all")
    out = " ".join(capsys.readouterr().out.split())
    assert "shows another American Express Banking account" in out
    assert "account switcher, then press Continue" in out
    assert not app.process.called and not called
    assert "id:URN:DOC:BS:NEW" not in app.discovery.data
    assert app.discovery.data["id:URN:DOC:TX:OLD"]["account_token"] == "tok-checking"


@pytest.mark.parametrize("token, digits", [("tok-checking", "1234"), ("tok-checking", ""),
                                           ("", "1234")])
def test_a_list_of_the_account_the_records_hold_is_taken(app_env, monkeypatch, token, digits):
    app, _ = app_env
    _held(app)
    called = _discover(app, monkeypatch, _another(token, digits))
    app.cmd_discover(quiet=True)
    assert called
    assert "id:URN:DOC:BS:NEW" in app.discovery.data


def test_a_config_with_no_records_takes_the_account_shown_and_keeps_it(app_env, monkeypatch):
    app, _ = app_env
    _discover(app, monkeypatch, _another("tok-first", "4321"))
    app.cmd_discover(quiet=True)
    rec = app.discovery.data["id:URN:DOC:BS:NEW"]
    assert (rec["account_token"], rec["account_digits"]) == ("tok-first", "4321")
    assert app._held_accounts() == ({"tok-first"}, {"4321"})


def test_the_switcher_is_read_when_the_config_names_the_account():
    """A name set in the config goes on the documents, and the digits the
    switcher shows still go with them, since they say which account it is."""
    site.SESSION.account_label, site.SESSION.label_configured = "Ops", True
    page = _heard(Page(name="Business Checking", number="•••• 9999"))
    _answer(page)
    listed = site.collect_documents(page)
    (doc,) = listed
    assert doc.account == "Ops"
    assert (listed.token, listed.digits, doc.account_digits) == ("tok-checking", "9999", "9999")


def test_a_second_config_on_the_first_accounts_page_stops(tmp_path, monkeypatch):
    """The review's case. biz2, named Ops, saved its own account before,
    and its window now shows the first account, whose list answers with the
    first account's token while the switcher shows its digits."""
    from paperpull_core import storage
    storage.bind(SPEC)
    cfg = tmp_path / "config.biz2.json"
    cfg.write_text(json.dumps({"owner": "biz", "output_dir": str(tmp_path), "account_name": "Ops",
                               "min_pdf_bytes": 10, "max_path_length": 240}), encoding="utf-8")
    app = App(DummyArgs(config=str(cfg), yes=True))
    _held(app, token="tok-ops", digits="5555")
    page = _heard(Page(name="Business Checking", number="•••• 1111"))
    page.wait_for_timeout = lambda ms: None
    page.reload = lambda **kw: _answer(page, token="tok-first")
    page.goto = lambda url, **kw: _answer(page, token="tok-first")
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(app, "write_failure", lambda *a, **k: None)
    app.process = MagicMock()
    with pytest.raises(SystemExit):
        app.cmd_run("all")
    assert not app.process.called
    assert "id:URN:DOC:1" not in app.discovery.data


# --- the loop over the documents ---------------------------------------------

def test_a_document_refused_as_signed_out_stops_the_run(app_env, monkeypatch):
    app, _ = app_env
    page = MagicMock()
    page.url = site.DOCUMENTS_URL
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    asked = []

    def refused(page, doc, out_path, **kw):
        asked.append(doc.document_id)
        raise site.SessionExpired("refused")
    monkeypatch.setattr(site, "amexbanking_download", refused)
    docs = [_doc(doc_id="URN:DOC:TX:1"), _doc(doc_id="URN:DOC:TX:2")]
    with pytest.raises(SystemExit):
        app.process(docs)
    assert asked == ["URN:DOC:TX:1"]
    assert app.progress.get(docs[0].key) is None


def test_a_document_that_would_not_come_fails_alone(app_env, monkeypatch):
    app, _ = app_env
    page = MagicMock()
    page.url = site.DOCUMENTS_URL
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(app, "write_failure", lambda *a, **k: None)
    asked = []
    monkeypatch.setattr(site, "amexbanking_download",
                        lambda page, doc, out_path, **kw: asked.append(doc.document_id) or False)
    docs = [_doc(doc_id="URN:DOC:TX:1"), _doc(doc_id="URN:DOC:TX:2")]
    app.process(docs)
    assert asked == ["URN:DOC:TX:1", "URN:DOC:TX:2"]
    assert app.progress.get(docs[0].key)["state"] == State.FAILED.value


def test_each_document_is_asked_for_with_its_own_id_and_token(app_env, monkeypatch):
    app, _ = app_env
    page = MagicMock()
    page.url = site.DOCUMENTS_URL
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    asked = []

    def save(page, doc, out_path, **kw):
        asked.append((doc.document_id, doc.account_token))
        _pdf(out_path, doc.document_id)
        return True
    monkeypatch.setattr(site, "amexbanking_download", save)
    docs = [_doc(doc_id="URN:DOC:TX:1", token="tok-a"), _doc(doc_id="URN:DOC:TX:2", token="tok-b")]
    app.process(docs)
    assert asked == [("URN:DOC:TX:1", "tok-a"), ("URN:DOC:TX:2", "tok-b")]
    paths = {app.progress.get(d.key)["pdf_path"] for d in docs}
    assert len(paths) == 2


# --- Login --------------------------------------------------------------------

@pytest.mark.parametrize("answered, said", [
    (True, "answers with your documents list"),
    (False, "cannot say whether you are signed in"),
])
def test_login_says_signed_in_only_once_the_list_answers(app_env, monkeypatch, capsys,
                                                          answered, said):
    app, _ = app_env
    page = MagicMock()
    page.url = site.DOCUMENTS_URL
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "answers_its_list", lambda page: answered)
    app.cmd_login()
    out = " ".join(capsys.readouterr().out.split())
    assert said in out
    assert ("Success" in out) is answered


# --- controls ----------------------------------------------------------------

@pytest.mark.parametrize("name", [
    # Every control the 2026-11-08 survey marked safe that is not a document
    "Open New Account", "View All Account Details", "View All Gift Cards",
    "Download the App", "Order Checks", "Give Feedback", "Go to Business Line of Credit",
    "Send a Payment", "Make a Payment", "Scheduled Payments", "Redeem Rewards",
    "View Rewards", "Redeem Points", "Redeem a Statement Credit",
])
def test_controls_that_are_not_documents_are_not_safe(name):
    assert site.is_safe_control(name) is False


@pytest.mark.parametrize("name", ["Documents and Statements", "Download Statement (PDF)",
                                  "View 1099 Tax Form", "Print Statement",
                                  "Rewards Checking Statement"])
def test_document_controls_stay_safe(name):
    assert site.is_safe_control(name) is True
