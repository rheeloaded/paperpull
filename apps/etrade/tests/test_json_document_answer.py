"""A document whose PDF comes back inside a JSON answer (#36, 0.38.0).

RECORDED. Pressing a document's link makes the page POST to
/etaz/api/adsal/accountdocs/<...>/<n>.pdf, and the answer is JSON with the
PDF inside it as base64 text, which the page hands to the browser as a
download. Two of the tester's four statements reached the app through that
download and two did not. Here the page downloads nothing at all, so the
PDF inside the answer is the only way the document can be saved.

Everything here is invented.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site
import test_download_period as period  # noqa: E402  its made-up page and list answers

_PRESS = 'fetch("/docs/" + d.documentDate.slice(0, 10) + ".pdf");'
_ASK = ('fetch("/etaz/api/adsal/accountdocs/v1/" + d.documentDate.slice(0, 10) + ".pdf?RequestID=1",'
        ' {method: "POST", body: JSON.stringify({documentId: d.documentId})})')
JSON_PAGE = period.PAGE.replace(_PRESS, _ASK + ";")
assert JSON_PAGE != period.PAGE, "the page's press did not change"
# The same press, and a moment after its answer a download of another
# document starts, the way an earlier press's late download would.
LATE_PAGE = period.PAGE.replace(_PRESS, _ASK + """.then(() => setTimeout(() => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob(["%PDF-1.4\\n% an earlier document\\n%%EOF\\n"],
                                                {type: "application/pdf"}));
          a.download = "earlier.pdf";
          document.body.appendChild(a);
          a.click();
        }, 300));""")
assert LATE_PAGE != period.PAGE, "the page's press did not change"


def _pdf(day: str) -> bytes:
    return b"%PDF-1.4\n% invented statement " + day.encode() + b"\n" + b"x" * 400 + b"\n%%EOF\n"


def _site(carries_pdf: bool, page_html: str):
    def answer(route):
        url = route.request.url
        if "/etaz/api/adsal/accountdocs/v1/" in url:
            day = url.split("/v1/", 1)[1][:10]
            body = {"documentStream": base64.b64encode(_pdf(day)).decode() if carries_pdf else "",
                    "fileName": "Statement.pdf", "status": "SUCCESS"}
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        route.fulfill(status=200, content_type="text/html", body=page_html)
    return answer


def _page(browser, carries_pdf=True, page_html=JSON_PAGE):
    ctx = browser.new_context()
    ctx.route("https://us.etrade.com/**", _site(carries_pdf, page_html))
    ctx.route("https://ext-web.etrade.com/**", period._answer)
    pg = ctx.new_page()
    site.collect_download_docs(pg)
    return ctx, pg


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


def test_the_pdf_inside_the_json_answer_is_saved(browser, tmp_path):
    ctx, pg = _page(browser)
    try:
        day = "2025-11-30"
        out = tmp_path / "statement.pdf"
        trace: list = []
        assert site.download_bill(pg, tmp_path / "dl", day, out, title=period.TITLE, trace=trace), trace
        assert out.read_bytes() == _pdf(day)
        assert {"note": "the PDF came inside its JSON answer"} in trace, trace
    finally:
        ctx.close()


def test_each_document_is_saved_from_its_own_answer(browser, tmp_path):
    """The answer is tied to the request this press made, so the second
    document never takes the first one's."""
    ctx, pg = _page(browser)
    try:
        for day in ("2025-11-30", "2026-02-28"):
            out = tmp_path / ("%s.pdf" % day)
            assert site.download_bill(pg, tmp_path / "dl", day, out, title=period.TITLE), day
            assert out.read_bytes() == _pdf(day), day
    finally:
        ctx.close()


def test_a_late_download_does_not_take_this_documents_name(browser, tmp_path):
    """A download event is not tied to the press, so this press's own
    answer wins over one that starts while the app is still waiting."""
    ctx, pg = _page(browser, page_html=LATE_PAGE)
    try:
        day = "2025-11-30"
        out = tmp_path / "statement.pdf"
        assert site.download_bill(pg, tmp_path / "dl", day, out, title=period.TITLE)
        assert out.read_bytes() == _pdf(day)
    finally:
        ctx.close()


def test_a_json_answer_with_no_pdf_in_it_saves_nothing(browser, tmp_path):
    """And the attempt file says what the answer held instead, in counts
    and fixed words, so the next round knows where the PDF went."""
    ctx, pg = _page(browser, carries_pdf=False)
    try:
        out = tmp_path / "statement.pdf"
        trace: list = []
        assert not site.download_bill(pg, tmp_path / "dl", "2025-11-30", out, title=period.TITLE,
                                      trace=trace)
        assert not out.exists()
        assert {"note": "the PDF came inside its JSON answer"} not in trace
        shape = {"note": "its JSON answer held no PDF", "texts": 3, "longest": len("Statement.pdf"),
                 "base64": False, "begins": "other"}
        assert shape in trace, trace
        assert "Statement.pdf" not in json.dumps(trace)
    finally:
        ctx.close()


def test_only_text_that_is_a_pdf_is_read_out_of_an_answer():
    pdf = _pdf("2025-01-31")
    encoded = base64.b64encode(pdf).decode()
    assert site._pdf_in_json({"documentStream": encoded}) == pdf
    assert site._pdf_in_json({"a": [{"b": encoded}]}) == pdf
    assert site._pdf_in_json({"url": "data:application/pdf;base64," + encoded}) == pdf
    assert site._pdf_in_json({"wrapped": encoded[:40] + "\n" + encoded[40:]}) == pdf
    assert site._pdf_in_json({"first": "JVBERi0 not base64 !!", "then": encoded}) == pdf
    assert site._pdf_in_json({"documentStream": base64.b64encode(b"<html>no</html>").decode()}) is None
    assert site._pdf_in_json({"documentStream": "JVBERi0 not base64 !!"}) is None
    assert site._pdf_in_json({"cut": base64.b64encode(pdf[:-40]).decode()}) is None
    assert site._pdf_in_json({"status": "SUCCESS", "count": 3}) is None
    assert site._pdf_in_json(None) is None


def test_an_answer_with_no_pdf_is_described_by_its_shape_alone():
    zipped = base64.b64encode(b"PK\x03\x04" + b"\x00" * 60).decode()
    assert site._json_answer_shape({"doc": zipped, "name": "Jane Q Invented"}) == {
        "texts": 2, "longest": len(zipped), "base64": True, "begins": "zip"}
    gz = base64.b64encode(b"\x1f\x8b\x08" + b"\x00" * 60).decode()
    assert site._json_answer_shape({"doc": gz})["begins"] == "gzip"
    assert site._json_answer_shape({"status": "SUCCESS", "count": 3}) == {
        "texts": 1, "longest": 7, "base64": True, "begins": "other"}
    assert site._json_answer_shape({"count": 3}) == {
        "texts": 0, "longest": 0, "base64": False, "begins": "nothing"}
    assert site._json_answer_shape(None)["begins"] == "nothing"
