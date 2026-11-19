"""Review of #234, the workplace statements' adverse cases.

Cases from the independent test plan the contributor's tests did not reach,
a plan number inside a longer number, answers that are not the statement
list or not a PDF, a period the fresh list no longer has, a brokerage
record on a workplace tab, and the two kinds kept apart in the archive.
Every plan, account and period is invented."""
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vanguard_docs as docs
import vanguard_site as site
from paperpull_core.testkit import text_pdf
from test_workplace_statements import END, PLAN, START, Response, WorkplacePage, row
from test_downloads_and_names import _app

PERIOD = "January 1, 2032 through March 31, 2032"


def _first(page):
    return site.collect_documents(page)[0]


def _download(page, doc, out):
    return site.download_document(page, PLAN, False, doc["doc_type"], doc["title"], END, out,
                                  document_id_hint=doc["document_id"])


def test_a_plan_number_inside_a_longer_number_is_not_the_plan(tmp_path):
    page = WorkplacePage()
    page.pdf = {"0": text_pdf([f"Plan {PLAN}7", PERIOD])}
    out = tmp_path / "statement.pdf"
    assert not _download(page, _first(page), out)
    assert not out.exists()


def test_the_control_with_the_plan_and_the_period_is_saved(tmp_path):
    page = WorkplacePage()
    pdf = text_pdf([f"Plan number {PLAN}", PERIOD])
    page.pdf = {"0": pdf}
    out = tmp_path / "statement.pdf"
    assert _download(page, _first(page), out)
    assert out.read_bytes() == pdf


class _Answering(WorkplacePage):
    """The PDF route answers with the status, type and body a case gives."""

    def __init__(self, status, content_type, body):
        super().__init__()
        self.answer = (status, content_type, body)

    def get(self, url, **kw):
        response = super().get(url, **kw) if url == site.WORKPLACE_LIST else None
        if response is not None:
            return response
        self.requests.append(url)
        assert kw["max_redirects"] == 0
        status, content_type, body = self.answer
        response = Response(body, content_type)
        response.status = status
        self.responses.append(response)
        return response


@pytest.mark.parametrize("status,content_type,body", [
    (302, "application/pdf", b""),
    (200, "text/html", text_pdf([f"Plan {PLAN}", PERIOD])),
    (200, "application/pdf", b"<html>Sign in</html>"),
    (401, "application/pdf", text_pdf([f"Plan {PLAN}", PERIOD])),
    (200, "application/pdf", b"<!-- sign in -->\n" + text_pdf([f"Plan {PLAN}", PERIOD])),
])
def test_an_answer_that_is_not_the_pdf_saves_nothing(tmp_path, status, content_type, body):
    page = _Answering(status, content_type, body)
    out = tmp_path / "statement.pdf"
    assert not _download(page, _first(page), out)
    assert not out.exists()
    assert all(r.disposed for r in page.responses)


class _Listing(WorkplacePage):
    def __init__(self, status=200, raw=None):
        super().__init__()
        self.status, self.raw = status, raw

    def get(self, url, **kw):
        response = super().get(url, **kw)
        if url == site.WORKPLACE_LIST:
            response.status = self.status
            if self.raw is not None:
                response._body = self.raw
        return response


@pytest.mark.parametrize("status,raw", [
    (302, None),
    (500, None),
    (200, b"<html>Sign in</html>"),
    (200, b'{"statementPlan": {"planId": "900001"}}'),
    (200, b'{"statementPlan": {"planId": "900001"}, "statementData": {}}'),
    (200, b'{"statementData": []}'),
    (200, json.dumps({"statementPlan": {"planId": PLAN}, "statementData": [
        {"startDate": "2032-03-31", "endDate": "2032-01-01",
         "statementViewPDFURL": "/VGApp/pe/employee/openpdf?documentType=statement&index=0"}]}).encode()),
    (200, json.dumps({"statementPlan": {"planId": PLAN}, "statementData": [
        row(START, END, 0), row(START, END, 1)]}).encode()),
    (200, json.dumps({"statementPlan": {"planId": PLAN}, "statementData": [
        {"startDate": "soon", "endDate": END,
         "statementViewPDFURL": "/VGApp/pe/employee/openpdf?documentType=statement&index=0"}]}).encode()),
])
def test_a_list_that_is_not_readable_stops(status, raw):
    page = _Listing(status, raw)
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert page.requests == [site.WORKPLACE_LIST]


def test_an_answered_empty_list_lists_nothing_and_does_not_stop():
    page = WorkplacePage()
    page.rows = []
    assert site.collect_documents(page) == []


def test_a_period_the_fresh_list_no_longer_has_asks_for_no_pdf(tmp_path):
    page = WorkplacePage()
    doc = _first(page)
    page.rows = [page.rows[1]]
    out = tmp_path / "statement.pdf"
    assert not _download(page, doc, out)
    assert page.requests == [site.WORKPLACE_LIST, site.WORKPLACE_LIST]
    assert not out.exists()


def test_a_brokerage_statement_on_a_workplace_tab_stops_with_nothing_pressed(tmp_path):
    page = WorkplacePage()
    with pytest.raises(site.ListStopped):
        site.download_document(page, "10001111", False, "Statement",
                               "Account Statement - Synthetic Brokerage 1111", END,
                               tmp_path / "statement.pdf")
    assert page.requests == []


def test_the_two_kinds_of_one_date_and_label_are_two_records():
    app = _app()
    base = {"account": "Synthetic Plan 1111", "account_id": "1111", "date": END,
            "title": "Account Statement - Synthetic Plan 1111", "category": "Statement",
            "doc_type": "Statement"}
    app._record_vanguard_doc(dict(base), set())
    app._record_vanguard_doc({**base, "doc_type": site.WORKPLACE_STATEMENT,
                              "document_id": f"workplace-{START}-{END}"}, set())
    kinds = sorted(r["doc_type"] for r in app.discovery.data.values())
    assert kinds == ["Statement", site.WORKPLACE_STATEMENT]
    brokerage = next(r for r in app.discovery.data.values() if r["doc_type"] == "Statement")
    assert brokerage["document_id"] == ""
    assert brokerage["href"] == site.URLS["documents"]


@pytest.mark.parametrize("pdf_lines,reason", [
    ([f"Plan {PLAN}", PERIOD], None),
    (["Plan 900002", PERIOD], "plan or period"),
    ([f"Plan {PLAN}", "October 1, 2031 through December 31, 2031"], "plan or period"),
])
def test_a_refused_pdf_says_why_without_the_plan_number(tmp_path, caplog, pdf_lines, reason):
    page = WorkplacePage()
    page.pdf = {"0": text_pdf(pdf_lines)}
    out = tmp_path / "statement.pdf"
    with caplog.at_level(logging.INFO, logger=site.log.name):
        saved = _download(page, _first(page), out)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert saved is (reason is None)
    if reason:
        assert reason in said
    assert PLAN not in said and "openpdf" not in said and "index=" not in said


def test_a_period_missing_from_the_fresh_list_says_so(tmp_path, caplog):
    page = WorkplacePage()
    doc = _first(page)
    page.rows = [page.rows[1]]
    with caplog.at_level(logging.INFO, logger=site.log.name):
        assert not _download(page, doc, tmp_path / "statement.pdf")
    assert "not in the plan's list" in " ".join(r.getMessage() for r in caplog.records)


def test_resume_on_a_brokerage_tab_leaves_workplace_records_as_they_are(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._record_vanguard_doc({"account": "Synthetic Plan 900001", "account_id": PLAN, "date": END,
                              "title": "Account Statement - Synthetic Plan 900001",
                              "category": "Statement", "doc_type": site.WORKPLACE_STATEMENT,
                              "document_id": f"workplace-{START}-{END}"}, set())
    before = json.dumps(app.discovery.data, sort_keys=True)
    app.page = lambda: SimpleNamespace(url=site.URLS["documents"])
    selected = []
    monkeypatch.setattr(docs.listing, "resume", lambda _a, left, _p: selected.extend(left))
    app.cmd_resume()
    assert selected == []
    assert json.dumps(app.discovery.data, sort_keys=True) == before
