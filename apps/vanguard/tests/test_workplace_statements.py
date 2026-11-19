"""Synthetic workplace retirement statements and their read-only routes."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vanguard_site as site
from paperpull_core.testkit import text_pdf

PLAN = "900001"
START, END = "2032-01-01", "2032-03-31"
OLDER_START, OLDER_END = "2031-10-01", "2031-12-31"
PDF_PATH = "/VGApp/pe/employee/openpdf"


def row(start, end, index):
    return {"startDate": start, "endDate": end, "statementViewPDFURL":
            f"{PDF_PATH}?documentType=statement&index={index}"}


class Response:
    def __init__(self, body, content_type):
        self.status = 200
        self.headers = {"content-type": content_type}
        self._body = body
        self.disposed = False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


class WorkplacePage:
    url = "https://ownyourfuture.vanguard.com/main/manage/statements"

    def __init__(self):
        self.previous = f"https://ownyourfuture.vanguard.com/main/manage?planId={PLAN}#statementsAndTaxForms"
        self.active_plan = PLAN
        self.rows = [row(START, END, 0), row(OLDER_START, OLDER_END, 1)]
        self.pdf = {}
        self.requests = []
        self.responses = []
        self.context = SimpleNamespace(request=SimpleNamespace(get=self.get))

    def evaluate(self, _script):
        return self.previous

    def get(self, url, *, max_redirects, timeout, headers, params=None):
        self.requests.append(url)
        assert max_redirects == 0 and 0 < timeout <= 25000
        host = urlsplit(url)
        assert (host.scheme, host.netloc) == ("https", "retirementplans.vanguard.com")
        if url == site.WORKPLACE_LIST:
            assert params == {"SelectedPlanId": PLAN}
            assert headers == {"Accept": "application/json"}
            payload = {"statementPlan": {"planId": self.active_plan}, "statementData": self.rows}
            response = Response(json.dumps(payload).encode(), "text/html")
        else:
            assert params is None and host.path == PDF_PATH
            assert headers == {"Accept": "application/pdf"}
            query = parse_qs(host.query)
            assert sorted(query) == ["documentType", "index"]
            assert query["documentType"] == ["statement"]
            response = Response(self.pdf[query["index"][0]], "application/pdf")
        self.responses.append(response)
        return response


def test_discovery_keeps_exact_plan_and_period_and_filters_by_year():
    page = WorkplacePage()
    docs = site.collect_documents(page)
    assert {(d["account_id"], d["date"], d["doc_type"]) for d in docs} == {
        (PLAN, END, site.WORKPLACE_STATEMENT), (PLAN, OLDER_END, site.WORKPLACE_STATEMENT)}
    assert [d["date"] for d in site.collect_documents(page, keep=lambda year: year == "2031")] == [
        OLDER_END]
    assert all("openpdf" not in str(d) for d in docs)
    assert all(r.disposed for r in page.responses)


def test_download_rebinds_moved_index_and_checks_the_plan_and_period(tmp_path):
    page = WorkplacePage()
    doc = site.collect_documents(page)[0]
    page.rows = [row(OLDER_START, OLDER_END, 0), row(START, END, 1)]
    pdf = text_pdf([f"Workplace plan {PLAN}", "January 1, 2032 through March 31, 2032"])
    page.pdf = {"1": pdf}
    out = tmp_path / "statement.pdf"
    assert site.download_document(page, PLAN, False, doc["doc_type"], doc["title"], END, out,
                                  document_id_hint=doc["document_id"])
    assert out.read_bytes() == pdf
    assert page.requests[-1].endswith("documentType=statement&index=1")
    assert all(r.disposed for r in page.responses)


@pytest.mark.parametrize("rendered", [
    ("900002", "January 1, 2032 through March 31, 2032"),
    (PLAN, "October 1, 2031 through March 31, 2032"),
    (PLAN, "January 1, 2032 through June 30, 2032"),
    (PLAN, "January 1, 2032 opened. March 31, 2032 balance snapshot."),
])
def test_pdf_for_another_plan_or_period_is_not_saved(tmp_path, rendered):
    page = WorkplacePage()
    page.pdf = {"0": text_pdf(list(rendered))}
    doc = site.collect_documents(page)[0]
    out = tmp_path / "statement.pdf"
    assert not site.download_document(page, PLAN, False, doc["doc_type"], doc["title"], END, out,
                                      document_id_hint=doc["document_id"])
    assert not out.exists()


def test_another_plan_in_the_list_is_refused():
    page = WorkplacePage()
    page.active_plan = "900002"
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert page.requests == [site.WORKPLACE_LIST]
    assert all(r.disposed for r in page.responses)


@pytest.mark.parametrize("unknown", [
    "https://retirementplans.vanguard.com.example.org/VGApp/pe/employee/openpdf?index=1&documentType=statement",
    "/VGApp/pe/employee/openpdf?index=1&documentType=tax",
    "/VGApp/pe/employee/openpdf?index=1&index=2&documentType=statement",
    "/VGApp/pe/employee/statement?index=1&documentType=statement",
])
def test_unknown_pdf_route_is_refused_before_request(unknown):
    page = WorkplacePage()
    page.rows[0]["statementViewPDFURL"] = unknown
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert page.requests == [site.WORKPLACE_LIST]


def test_unbound_statement_tab_does_not_guess_another_plan():
    page = WorkplacePage()
    page.previous = "https://ownyourfuture.vanguard.com/main/manage"
    assert not site.on_documents_page(page)
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert page.requests == []
