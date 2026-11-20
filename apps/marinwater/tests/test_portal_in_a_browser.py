"""An offline Paymentus page and synthetic DataProse PDFs."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marinwater_site as site
from paperpull_core.testkit import text_pdf

HOME = site.BASE + "/cp/landing.action"
HISTORY = site.BASE + site.HISTORY_PATH + "?accountId=0&accthid=invented&CSRF_TOKEN=test"
VIEWER = "https://" + site.VIEWER_HOST + site.DOWNLOAD_PATH
DAY = "2032-01-09"
PDF = text_pdf(["Synthetic Marin Water bill", "Jan 9, 2032"])


class Viewer:
    def get(self, url, *, max_redirects, timeout, headers):
        assert url == VIEWER + "?fixture-pdf"
        assert max_redirects == 0 and headers == {"Accept": "application/pdf"}
        return self

    status = 200
    headers = {"content-type": "application/pdf", "content-length": str(len(PDF))}

    def body(self):
        return PDF

    def dispose(self):
        pass


@pytest.fixture
def portal():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND"])
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        context = browser.new_context(service_workers="block")
        seen = []

        def route(mock):
            request = mock.request
            seen.append((request.method, request.url))
            if request.url == HOME:
                html = ("<title>Marin Water</title><input type='password' hidden>"
                        f"<a href='{HISTORY}'>View Bill History</a>")
            elif request.url == HISTORY:
                html = ("<title>Marin Water Bill History</title><table><tbody>"
                        "<tr><th>Account</th><th>Bill Date</th><th>Action</th></tr>"
                        "<tr><td>000000</td><td>Jan 9, 2032</td>"
                        f"<td><a href='{VIEWER}?fixture-pdf'>View Bill</a></td></tr>"
                        "</tbody></table>")
            else:
                return mock.abort()
            mock.fulfill(content_type="text/html", body=html)

        context.route("**/*", route)
        page = context.new_page()
        page.goto(HOME)
        site._RUN.clear()
        yield page, seen
        site._RUN.clear()
        browser.close()


def test_history_and_pdf_use_the_known_document_routes(portal, tmp_path):
    page, seen = portal
    assert site.goto_documents(page)
    assert not site.looks_signed_out(page)
    viewer = Viewer()
    bill, = site.collect_download_docs(page, viewer=viewer)
    assert bill.date_text == DAY and bill.href == site.DOWNLOAD_PATH
    output = tmp_path / "synthetic.pdf"
    assert site.download_bill(page, None, DAY, output, href=bill.href,
                              document_id=bill.document_id, viewer=viewer)
    assert output.read_bytes() == PDF
    assert page.url == HOME
    assert seen == [("GET", HOME), ("GET", HISTORY)]


@pytest.mark.parametrize("url", [
    "http://solsearcher.dataprose.com/resource/SSEPDFExtractor.dll?fixture",
    "https://solsearcher.dataprose.com.example.test/resource/SSEPDFExtractor.dll?fixture",
    "https://solsearcher.dataprose.com/resource/payment?fixture",
    "https://ipn4.paymentus.com/cp/mwdc",
])
def test_unrelated_views_are_refused(url):
    assert not site.is_download_url(url)


@pytest.mark.parametrize("label", [
    "Pay Now", "Schedule a Payment", "Change payment method", "Enroll in AutoPay",
    "View Bill and Pay", "Sign Out", "Start Service", "Close Account",
])
def test_payment_and_account_controls_are_refused(label):
    assert not site.is_safe_control(label)
