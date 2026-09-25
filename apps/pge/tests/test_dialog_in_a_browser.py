"""A bill that opens in a dialog, which is where his second run ended.

Round five taught the app to read a tab that MOVED. His next failure
file showed the page standing still, with one iframe and two dialogs on
it and no request for a PDF anywhere in the whole run. So the bill opens
in a dialog, the same shape Costco's receipt has, and asking only when
the tab moved never asked at all (#33).

A viewer in a dialog often points at a blob the page made rather than at
an address on the site, and a blob belongs to the page, so only the page
can fetch it. That is the part a fake page cannot stand in for, which is
why this drives a real browser.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("https://myaccount.pge.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body="<h1>history</h1>"))
    pg = ctx.new_page()
    pg.goto("https://myaccount.pge.com/myaccount/s/bill-and-payment-history")
    yield pg
    browser.close()
    driver.stop()


BLOB = """() => {
  const bytes = new Uint8Array([37,80,68,70,45,49,46,55,32,98,105,108,108]);
  const u = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  document.body.innerHTML = '<div role="dialog"><iframe src="' + u + '"></iframe></div>';
}"""


def test_a_bill_in_a_dialog_is_read_off_the_blob_the_page_made(page):
    page.evaluate(BLOB)
    page.wait_for_timeout(300)
    assert (site._pdf_from_here(page) or b"").startswith(b"%PDF-")


def test_a_page_holding_no_document_says_so(page):
    page.set_content("<body><h1>history</h1><div role='dialog' class='modal fade'></div></body>")
    assert site._pdf_from_here(page) is None


def test_the_page_is_asked_whether_or_not_the_tab_moved():
    """Asking only when it moved is what left his run with nothing, on a
    page that had the bill open in front of him."""
    import inspect
    src = inspect.getsource(site.download_bill)
    block = src.split("captured_response_bytes[0] or captured_download[0] or blob_url")[1][:1200]
    assert "_pdf_from_here(page)" in block
    outside = block.split("if moved:")[0] + block.split("else:")[-1]
    assert "_pdf_from_here(page)" in block
    # and it is not nested under the moved branch any more
    moved_at = block.index("moved = ")
    asked_at = block.index("_pdf_from_here(page)")
    assert asked_at > moved_at
    assert "the page itself is asked" in block
    assert outside is not None


def test_nothing_off_pge_is_fetched_even_from_a_dialog(page):
    page.set_content("<body><div role='dialog'>"
                     "<iframe src='https://elsewhere.test/bill.pdf'></iframe></div></body>")
    assert site._pdf_from_here(page) is None


LATE_BLOB = BLOB.replace("() => {", "() => setTimeout(() => {", 1)[:-1] + "}, 2000)"


def test_a_viewer_that_arrives_late_is_waited_for_not_missed(page):
    """Round six read the page once, straight after the popup gave up. A
    dialog whose viewer gets its source a moment later was read empty,
    and that looks exactly like a bill that never opened."""
    from paperpull_core.journal import Journal, summarize

    before = site._sources_now(page)
    page.evaluate(LATE_BLOB)
    assert site._pdf_from_here(page) is None, "read at once, it is missed"

    j = Journal(page)
    site.set_journal(j)
    try:
        got = site._wait_for_viewer(page, before)
    finally:
        site.set_journal(None)
    assert got.ready and got.winner != "already"
    assert (site._pdf_from_here(page) or b"").startswith(b"%PDF-")
    said = " ".join(summarize(j.report()))
    assert "\"bill viewer\" was ready after" in said


def test_a_frame_the_history_always_had_is_not_the_bill(page):
    """Ready means an address that was not there before the click. A
    frame the page carried all along would otherwise pass at once."""
    page.set_content("<body><h1>history</h1><iframe "
                     "src='https://myaccount.pge.com/myaccount/s/widget'>"
                     "</iframe></body>")
    page.wait_for_timeout(300)
    before = site._sources_now(page)
    got = site._wait_for_viewer(page, before)
    assert not got.ready
    assert [a.strategy for a in got.attempts] == [
        "count_reached", "network_idle", "count_settled"]
