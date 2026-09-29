"""A PDF the page builds and opens as a blob: tab, kept as it is made (#45).

American Family opens each statement in a new tab at a blob: address. A
page that revokes the address as soon as the tab has it leaves nothing to
read back by that address, so the blob is kept when the page makes it. In
a real browser, since revoking is the browser's doing. Every page here is
made up and nothing leaves this machine."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import blob_capture  # noqa: E402

HOST = "https://example.test"

PAGE = """<!doctype html><html><body>
<button id="open">View statement</button>
<button id="save">Save statement</button>
<button id="text">Export as text</button>
<script>
const pdf = (tag) => new Blob(['%PDF-1.4 invented statement ' + tag + ' ' + 'x'.repeat(300)],
                               {type: 'application/pdf'});
document.getElementById('open').onclick = () => {
  const url = URL.createObjectURL(pdf('opened'));
  window.open(url, '_blank');
  URL.revokeObjectURL(url);
};
document.getElementById('save').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(pdf('saved'));
  a.download = 'Statement 2026-09.pdf';
  document.body.appendChild(a);
  a.click();
};
document.getElementById('text').onclick = () => {
  URL.createObjectURL(new Blob(['just words ' + 'y'.repeat(300)], {type: 'text/plain'}));
};
</script></body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=PAGE))
    pg = ctx.new_page()
    pg.goto("%s/billing" % HOST)
    yield pg
    browser.close()
    driver.stop()


def test_a_blob_opened_in_a_tab_and_revoked_at_once_is_still_taken(page):
    assert blob_capture.arm(page)
    with page.context.expect_page():
        page.click("#open")
    # the address is gone, the way a page that revokes at once leaves it
    gone = page.evaluate("""async () => { const u = window.__paperpullBlobs[0].url;
        try { await fetch(u); return false; } catch (e) { return true; } }""")
    assert gone, "the address was revoked, so only the kept blob can be read"
    data, name = blob_capture.take(page)
    assert data.startswith(b"%PDF-") and b"invented statement opened" in data
    assert name == ""


def test_a_blob_saved_through_an_anchor_keeps_the_name_the_page_gave_it(page):
    assert blob_capture.arm(page)
    with page.expect_download():
        page.click("#save")
    data, name = blob_capture.take(page)
    assert b"invented statement saved" in data
    assert name == "Statement 2026-09.pdf"


def test_only_a_pdf_is_ever_taken(page):
    assert blob_capture.arm(page)
    page.click("#text")
    assert blob_capture.take(page) is None


def test_arming_again_forgets_what_an_earlier_press_made(page):
    """A document is only taken from a blob made after its own press."""
    assert blob_capture.arm(page)
    with page.context.expect_page():
        page.click("#open")
    assert blob_capture.take(page) is not None
    assert blob_capture.arm(page)
    assert blob_capture.take(page) is None


def test_a_page_that_cannot_be_asked_gives_nothing_and_raises_nothing():
    class _Gone:
        def evaluate(self, *a, **k):
            raise RuntimeError("target closed")
    assert blob_capture.arm(_Gone()) is False
    assert blob_capture.take(_Gone()) is None
