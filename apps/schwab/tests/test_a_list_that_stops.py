"""An answer the app cannot read stops the list, and the run says so.

A sign-in whose accounts all sat under viewOnlyAccounts read as no accounts,
and Discover ended clean with `Documents known: 0` (#137). Any answer the app
could not read did the same, so a Resume after it found nothing left to do.
Now a refused answer, an answer of another shape, or a row with no id stops
the list. Discover records nothing and leaves the listing noted as stopped,
and a download that reads the day's list stops once with the list unread.
"""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import listing
from paperpull_core import storage as core_storage
import schwab_docs as docs
import schwab_site as site

PAGE = SimpleNamespace(url="https://client.schwab.com/retail/accounts/statements/#/")


def accounts_answer(brokerage=None, view_only=None):
    return {"status": 200, "body": {"accountSelectorData": {"brokerageAccountList": {
        "brokerageAccounts": brokerage if brokerage is not None else [],
        "viewOnlyAccounts": view_only if view_only is not None else [],
    }}}}


ONE_ACCOUNT = accounts_answer(view_only=[{"id": "12345678", "nickName": "SchwabOne"}])

ONE_DOCUMENT = {"status": 200, "body": {"documents": [{
    "documentId": "DOC-1", "documentName": "Brokerage Statement",
    "type": site.TYPE_STATEMENTS, "onDemandDocumentType": "Statements",
    "date": "10/31/2026", "accountDisplayName": "1234-5678",
}]}}

ACCOUNTS_THAT_STOP = {
    "refused": {"status": 500, "body": None, "text": "server error"},
    "no token": {"status": 0, "body": None, "text": "no bearer token"},
    "not an object": {"status": 200, "body": ["accounts"]},
    "a third list": {"status": 200, "body": {"accountSelectorData": {
        "brokerageAccountList": {"otherAccounts": [{"id": "12345678"}]}}}},
    "no list at all": {"status": 200, "body": {"accountSelectorData": {}}},
    "another shape above the list": {"status": 200, "body": {"accountSelectorData": []}},
    "both lists empty": accounts_answer(),
    "a list that is not one": {"status": 200, "body": {"accountSelectorData": {
        "brokerageAccountList": {"brokerageAccounts": {"id": "12345678"}}}}},
    "a good list beside one that is not one": accounts_answer(
        brokerage=[{"id": "11112222", "nickName": "Trading"}],
        view_only={"id": "33334444"}),
    "rows saying accountId": accounts_answer(view_only=[{"accountId": "12345678"}]),
    "a row with no id beside a good one": accounts_answer(
        brokerage=[{"id": "11112222", "nickName": "Trading"}],
        view_only=[{"nickName": "SchwabOne"}]),
    "a row that is not an object": accounts_answer(
        brokerage=[{"id": "11112222", "nickName": "Trading"}, "33334444"]),
}

DOCUMENTS_THAT_STOP = {
    "refused": {"status": 500, "body": None, "text": "server error"},
    "not an object": {"status": 200, "body": ["documents"]},
    "not a list": {"status": 200, "body": {"documents": {"documentId": "DOC-1"}}},
}


def gateway(accounts, documents):
    def answer(_page, url, _headers, post_body=None):
        return accounts if url == site.API["accounts"] else documents
    return answer


def setup_app(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    config = json.loads((Path(docs.__file__).parent / "config.example.json")
                        .read_text(encoding="utf-8"))
    config.update({
        "owner": "Test Owner", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(docs.App, "page", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "_on_its_site", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "check_session", lambda app, *_a, **_kw: None)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return cfg, Path(config["output_dir"])


def pdf() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def note_of(out: Path) -> dict:
    return json.loads((out / "last-listing.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("answer", ACCOUNTS_THAT_STOP.values(), ids=ACCOUNTS_THAT_STOP.keys())
def test_an_accounts_answer_that_cannot_be_read_whole_stops_the_list(monkeypatch, answer):
    monkeypatch.setattr(site, "_gateway_call", gateway(answer, ONE_DOCUMENT))
    with pytest.raises(site.ListStopped):
        site.list_accounts(PAGE)


@pytest.mark.parametrize("answer", DOCUMENTS_THAT_STOP.values(), ids=DOCUMENTS_THAT_STOP.keys())
def test_a_documents_answer_that_cannot_be_read_stops_the_list(monkeypatch, answer):
    monkeypatch.setattr(site, "_gateway_call", gateway(ONE_ACCOUNT, answer))
    with pytest.raises(site.ListStopped):
        site.collect_documents(PAGE)


@pytest.mark.parametrize("documents", [{}, {"documents": None}, {"documents": []}],
                         ids=["no key", "null", "empty"])
def test_a_day_with_no_documents_is_no_stop(monkeypatch, documents):
    """A day's list with nothing on it is an answer, so a document no longer
    listed still goes on to the id its record keeps."""
    monkeypatch.setattr(site, "_gateway_call",
                        gateway(ONE_ACCOUNT, {"status": 200, "body": documents}))
    assert site.collect_documents(PAGE) == []


def test_an_empty_list_beside_a_list_with_rows_is_no_stop(monkeypatch):
    answer = {"status": 200, "body": {"accountSelectorData": {"brokerageAccountList": {
        "brokerageAccounts": [{"id": "11112222", "nickName": "Trading"}],
        "viewOnlyAccounts": None}}}}
    monkeypatch.setattr(site, "_gateway_call", gateway(answer, ONE_DOCUMENT))
    assert [a["account_id"] for a in site.list_accounts(PAGE)] == ["11112222"]


@pytest.mark.parametrize("accounts, documents", [
    *((answer, ONE_DOCUMENT) for answer in ACCOUNTS_THAT_STOP.values()),
    *((ONE_ACCOUNT, answer) for answer in DOCUMENTS_THAT_STOP.values()),
], ids=[*(f"accounts {name}" for name in ACCOUNTS_THAT_STOP),
        *(f"documents {name}" for name in DOCUMENTS_THAT_STOP)])
def test_discover_stops_with_nothing_recorded_and_the_list_not_whole(
        tmp_path, monkeypatch, capsys, accounts, documents):
    cfg, out = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr(site, "_gateway_call", gateway(accounts, documents))

    with pytest.raises(SystemExit) as stopped:
        docs.main(["--config", str(cfg), "--discover"])

    assert stopped.value.code == 1
    said = capsys.readouterr().out
    assert "The Charles Schwab list stopped" in said
    assert "Discovery complete" not in said
    assert not json.loads((out / "discovery.json").read_text(encoding="utf-8"))
    assert note_of(out)["complete"] is False
    assert list((out / "Diagnostics").glob("failure-*.json"))


def test_a_whole_list_after_a_stop_is_noted_whole(tmp_path, monkeypatch):
    cfg, out = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr(site, "_gateway_call", gateway(
        ACCOUNTS_THAT_STOP["refused"], ONE_DOCUMENT))
    with pytest.raises(SystemExit):
        docs.main(["--config", str(cfg), "--discover"])

    monkeypatch.setattr(site, "_gateway_call", gateway(ONE_ACCOUNT, ONE_DOCUMENT))
    docs.main(["--config", str(cfg), "--discover"])

    assert len(json.loads((out / "discovery.json").read_text(encoding="utf-8"))) == 1
    assert note_of(out)["complete"] is True


@pytest.mark.parametrize("answer", DOCUMENTS_THAT_STOP.values(), ids=DOCUMENTS_THAT_STOP.keys())
def test_a_list_that_stops_while_downloading_stops_once_with_the_list_unread(
        tmp_path, monkeypatch, capsys, answer):
    cfg, out = setup_app(tmp_path, monkeypatch)
    two = {"status": 200, "body": {"documents": [
        {**ONE_DOCUMENT["body"]["documents"][0], "documentId": f"DOC-{n}",
         "date": f"{n:02d}/30/2026"} for n in (9, 10)]}}
    monkeypatch.setattr(site, "_gateway_call", gateway(ONE_ACCOUNT, two))
    docs.main(["--config", str(cfg), "--discover"])

    reads = []

    def refused(_page, url, _headers, post_body=None):
        reads.append(url)
        return answer

    fetched = []
    monkeypatch.setattr(site, "_gateway_call", refused)
    monkeypatch.setattr(site, "fetch_pdf", lambda _p, doc: fetched.append(doc) or (200, pdf()))
    capsys.readouterr()

    with pytest.raises(listing.ListNotRead):
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg), "--resume"]))
        app.cmd_resume()

    assert len(reads) == 1
    assert not fetched
    assert not json.loads((out / "progress.json").read_text(encoding="utf-8"))
    assert "could not be read again" in capsys.readouterr().out


def test_the_documents_page_is_asked_at_its_retail_address_first(monkeypatch):
    went = []
    page = SimpleNamespace(url="", goto=lambda url, **_kw: went.append(url),
                           wait_for_timeout=lambda _ms: None)
    monkeypatch.setattr(site, "dismiss_timeout", lambda _page: None)
    monkeypatch.setattr(site, "looks_signed_out", lambda _page: False)
    monkeypatch.setattr(site, "on_documents_page", lambda _page: bool(went))

    assert site.goto_documents(page) is True
    assert went == ["https://client.schwab.com/retail/accounts/statements/"]


def test_the_older_address_is_asked_only_when_the_retail_one_does_not_open(monkeypatch):
    went = []
    page = SimpleNamespace(url="", goto=lambda url, **_kw: went.append(url),
                           wait_for_timeout=lambda _ms: None)
    monkeypatch.setattr(site, "dismiss_timeout", lambda _page: None)
    monkeypatch.setattr(site, "looks_signed_out", lambda _page: False)
    monkeypatch.setattr(site, "on_documents_page",
                        lambda _page: bool(went) and "/app/" in went[-1])

    assert site.goto_documents(page) is True
    assert went == ["https://client.schwab.com/retail/accounts/statements/",
                    "https://client.schwab.com/app/accounts/statements/"]
