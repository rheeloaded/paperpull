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


# -- from the pre-release review of 0.41.0 ---------------------------------------------

PAGE_TWO = """<!doctype html><html><body>
<button id="both">View statement</button>
<button id="twoopen">Open two</button>
<script>
const pdf = (tag) => new Blob(['%PDF-1.4 invented ' + tag + ' ' + 'x'.repeat(300)],
                               {type: 'application/pdf'});
document.getElementById('both').onclick = () => {
  window.open(URL.createObjectURL(pdf('statement')), '_blank');
  URL.createObjectURL(pdf('id card'));
};
document.getElementById('twoopen').onclick = () => {
  window.open(URL.createObjectURL(pdf('first')), '_blank');
  window.open(URL.createObjectURL(pdf('second')), '_blank');
};
</script></body></html>"""


def _two(page):
    """PAGE_TWO at an address of its own, so its script runs in a fresh window."""
    page.context.route("%s/two" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=PAGE_TWO))
    page.goto("%s/two" % HOST)


def test_only_the_pdf_the_page_opened_is_taken(page):
    """The newest PDF the page made was taken, and a press can make another,
    an ID card, after the statement it opens (review)."""
    _two(page)
    assert blob_capture.arm(page)
    page.click("#both")
    page.wait_for_timeout(300)
    assert b"invented id card" in blob_capture.take(page)[0], "the newest, the old way"
    data, _name = blob_capture.take(page, opened=True)
    assert b"invented statement" in data


def test_two_pdfs_opened_by_one_press_are_a_guess_and_neither_is_taken(page):
    _two(page)
    assert blob_capture.arm(page)
    page.click("#twoopen")
    page.wait_for_timeout(300)
    assert blob_capture.take(page, opened=True) is None


# -- the tabs a press asked for (2026-10-01) -------------------------------------------

PAGE_TABS = """<!doctype html><html><body>
<button id="tab">Open</button>
<button id="apart">Open apart</button>
<button id="here">Open here</button>
<button id="link">Link</button>
<button id="save">Save</button>
<button id="bare">Save unnamed</button>
<button id="named">Named</button>
<button id="framed">Framed</button>
<button id="gone">Gone</button>
<button id="nothing">Nothing</button>
<iframe name="inside" src="about:blank"></iframe>
<script>
document.getElementById('tab').onclick = () => window.open('about:blank', '_blank');
document.getElementById('apart').onclick = () => window.open('about:blank', '_blank', 'noopener');
document.getElementById('here').onclick = () => window.open('#here', '_self');
document.getElementById('named').onclick = () => window.open('about:blank', 'statement');
document.getElementById('framed').onclick = () => window.open('about:blank', 'inside');
// A link to a new tab, or one that saves, named or not.
const anchor = (download) => {
  const a = document.createElement('a');
  a.href = download === null ? 'about:blank'
                             : URL.createObjectURL(new Blob(['words'], {type: 'text/plain'}));
  a.target = '_blank';
  if (download !== null) a.setAttribute('download', download);
  document.body.appendChild(a);
  a.click();
};
document.getElementById('link').onclick = () => anchor(null);
document.getElementById('save').onclick = () => anchor('words.txt');
document.getElementById('bare').onclick = () => anchor('');
// A tab that closes itself, the way one does when what it was sent to
// turns into a download.
document.getElementById('gone').onclick = () => window.open('about:blank', '_blank').close();
document.getElementById('nothing').onclick = () => {};
</script></body></html>"""


def _tabs_page(page):
    page.context.route("%s/tabs" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=PAGE_TABS))
    page.goto("%s/tabs" % HOST)


def test_the_new_tabs_a_page_asks_for_are_counted(page):
    _tabs_page(page)
    assert blob_capture.tabs_asked(page) is None, "a page never armed cannot say"
    assert blob_capture.arm(page)
    assert blob_capture.tabs_asked(page) == 0
    with page.context.expect_page():
        page.click("#tab")
    assert blob_capture.tabs_asked(page) == 1
    with page.context.expect_page():
        page.click("#apart")
    assert blob_capture.tabs_asked(page) == 2, "a tab asked for with no window back still opens"
    with page.context.expect_page():
        page.click("#link")
    assert blob_capture.tabs_asked(page) == 3
    page.click("#here")
    with page.expect_download():
        page.click("#save")
    with page.expect_download():
        page.click("#bare")
    assert blob_capture.tabs_asked(page) == 3, "this tab and a link that saves open no tab"
    assert blob_capture.arm(page)
    assert blob_capture.tabs_asked(page) == 0, "arming again counts afresh"


def test_a_window_the_page_already_had_is_no_new_tab(page):
    """A name sends window.open back to a window the page opened before, or
    to a frame of the page, and neither is a new tab to wait for."""
    _tabs_page(page)
    assert blob_capture.arm(page)
    with page.context.expect_page():
        page.click("#named")
    assert blob_capture.tabs_asked(page) == 1
    page.click("#named")
    page.click("#framed")
    page.wait_for_timeout(300)
    assert blob_capture.tabs_asked(page) == 1
    assert len(page.context.pages) == 2


def test_a_tab_the_browser_refuses_is_not_counted(page):
    """A window.open that hands back no window though it asked for one, as
    a browser that refuses the tab answers."""
    page.context.route("%s/refusing" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html",
        body="<button onclick=\"window.open('about:blank', '_blank')\">Open</button>"
             "<script>window.open = function () { return null; };</script>"))
    page.goto("%s/refusing" % HOST)
    assert blob_capture.arm(page)
    page.click("button")
    assert blob_capture.tabs_asked(page) == 0
    assert len(page.context.pages) == 1


def _late(page, monkeypatch):
    from paperpull_core.testkit import TabsHeardLate
    heard: list = []
    page.context.on("page", lambda p: heard.append(p))
    return TabsHeardLate(monkeypatch), heard


def _heard(page, heard, seconds=10):
    import time
    deadline = time.monotonic() + seconds
    while not heard and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    return heard


def test_a_tab_playwright_hears_of_late_is_waited_for_and_closed(page, monkeypatch):
    """The page asked for it before the press was over, and Playwright heard
    of it a second after. Closing only the tabs already heard of left it
    open in a full run on a busy machine (2026-10-01)."""
    _tabs_page(page)
    before = set(page.context.pages)
    late, heard = _late(page, monkeypatch)
    assert blob_capture.arm(page)
    page.click("#tab")
    late.let_through_soon(page, 1.0)
    blob_capture.close_new_tabs(page, before)
    assert late.announced == 1 and _heard(page, heard)
    assert all(p.is_closed() for p in heard)
    assert page.context.pages == [page]


def test_a_tab_asked_for_after_arming_again_is_waited_for(page, monkeypatch):
    """The first tab of a press is open when the page is armed for its second
    step, which asks for another. Counted from the first arming, the open
    one would stand for the late one and nothing would be waited for."""
    _tabs_page(page)
    before = set(page.context.pages)
    assert blob_capture.arm(page)
    with page.context.expect_page():
        page.click("#tab")
    late, heard = _late(page, monkeypatch)
    assert blob_capture.arm(page)
    armed_at = set(page.context.pages)
    page.click("#tab")
    late.let_through_soon(page, 1.0)
    blob_capture.close_new_tabs(page, before, armed_at)
    assert late.announced == 1 and _heard(page, heard)
    assert all(p.is_closed() for p in heard)
    assert page.context.pages == [page]


@pytest.mark.parametrize("button", ["#nothing", "#gone"], ids=["no tab", "a tab that closed itself"])
def test_a_press_with_no_tab_still_open_is_not_held_up(page, button):
    import time
    _tabs_page(page)
    before = set(page.context.pages)
    assert blob_capture.arm(page)
    page.click(button)
    t0 = time.monotonic()
    blob_capture.close_new_tabs(page, before, wait_ms=5000)
    assert time.monotonic() - t0 < 4, "waited for a tab that was never coming"


def test_a_tab_that_never_comes_is_waited_for_no_longer_than_asked(page, monkeypatch):
    import time
    _tabs_page(page)
    before = set(page.context.pages)
    late, heard = _late(page, monkeypatch)
    assert blob_capture.arm(page)
    page.click("#tab")
    t0 = time.monotonic()
    blob_capture.close_new_tabs(page, before, wait_ms=700)
    took = time.monotonic() - t0
    assert 0.6 < took < 4, took
    late.let_through()
    for p in _heard(page, heard):
        p.close()


def test_closing_tabs_on_a_page_that_cannot_be_asked_raises_nothing():
    class _Gone:
        def evaluate(self, *a, **k):
            raise RuntimeError("target closed")

        @property
        def context(self):
            raise RuntimeError("target closed")
    blob_capture.close_new_tabs(_Gone(), set())
