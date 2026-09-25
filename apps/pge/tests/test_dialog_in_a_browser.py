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
    assert "_pdf_from_here(page" in block
    outside = block.split("if moved:")[0] + block.split("else:")[-1]
    assert "_pdf_from_here(page" in block
    # and it is not nested under the moved branch any more
    moved_at = block.index("moved = ")
    asked_at = block.index("_pdf_from_here(page")
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

    before = site._viewers_now(page)
    page.evaluate(LATE_BLOB)
    assert site._pdf_from_here(page) is None, "read at once, it is missed"

    j = Journal(page)
    site.set_journal(j)
    page.evaluate("() => { location.hash = '#/bill'; }")
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
    before = site._viewers_now(page)
    got = site._wait_for_viewer(page, before)
    assert not got.ready
    assert [a.strategy for a in got.attempts] == [
        "count_reached", "network_idle", "count_settled"]


PRESS = """<body><button id=b>View Bill PDF</button><script>
  window.presses = 0;
  document.getElementById('b').addEventListener('click', () => {
    window.presses++;
    %s
  });
</script></body>"""


def test_a_press_that_opens_no_tab_is_not_pressed_again(page):
    """No tab is not a failed click. The old fallback pressed a second
    time, and a bill in a dialog opened twice, which is the two dialogs
    in his failure file (#33)."""
    page.set_content(PRESS % "document.body.insertAdjacentHTML("
                     "'beforeend', '<div role=dialog>bill</div>');")
    popup = site._press_once(page, page.locator("#b"), lambda: False,
                             seconds=1.0)
    assert popup is None
    assert page.evaluate("window.presses") == 1
    assert page.locator("[role=dialog]").count() == 1


def test_a_tab_that_opens_late_is_still_caught(page):
    page.set_content(PRESS % "setTimeout(() => window.open('about:blank'), 1500);")
    popup = site._press_once(page, page.locator("#b"), lambda: False)
    assert popup is not None
    assert page.evaluate("window.presses") == 1
    popup.close()


def test_the_wait_hears_a_listener_while_it_waits(page):
    """A listener only gets its event while this thread is inside a
    Playwright call. The old loop slept in time.sleep and could never see
    a download or a response arrive, so it spun its full length."""
    import time as _time
    heard = []
    page.on("console", lambda msg: heard.append(msg.text))
    page.set_content(PRESS % "setTimeout(() => console.log('arrived'), 800);")
    t0 = _time.monotonic()
    site._press_once(page, page.locator("#b"), lambda: bool(heard))
    took = _time.monotonic() - t0
    assert heard and took < 3.0, "waited %.1fs for an event at 0.8s" % took


def test_no_wait_in_the_site_layer_sleeps_through_an_event():
    """The loops that wait on a listener's flag use the browser's timer."""
    import inspect
    src = inspect.getsource(site.download_bill) + inspect.getsource(site._press_once)
    assert "time.sleep(" not in src
    assert "expect_popup" not in src, "a timed-out expect_popup led to a second press"


def test_a_hash_change_after_the_press_is_not_the_bill_arriving(page):
    """The draft counted the page's own address, so a hash change right
    after the press read as ready while the viewer was still seconds
    away, and the journal would have taught the next round that no wait
    was needed."""
    before = site._viewers_now(page)
    page.evaluate("() => { location.hash = '#/bill'; }")
    page.evaluate(LATE_BLOB)
    got = site._wait_for_viewer(page, before)
    assert got.ready and got.winner != "already"
    assert got.elapsed_ms >= 1000


def test_a_viewer_from_an_earlier_bill_is_not_read_first(page):
    """What the viewers pointed at before the press goes to the back, so
    an earlier bill left open is not saved under this one's name."""
    page.evaluate(BLOB)
    page.wait_for_timeout(200)
    before = site._viewers_now(page)
    page.evaluate("""() => {
        const bytes = new Uint8Array([37,80,68,70,45,50,46,48,32,110,101,119]);
        const u = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
        document.body.insertAdjacentHTML('beforeend',
            '<div role="dialog"><iframe src="' + u + '"></iframe></div>');
    }""")
    page.wait_for_timeout(200)
    assert site._pdf_from_here(page, before).startswith(b"%PDF-2.0 new")


# -- round seven, a bill inside Salesforce's own answer (#33) ------------------

import base64 as _b64  # noqa: E402
import json as _json  # noqa: E402

_PDF = b"%PDF-1.4\n" + b"0" * 400


class _Res:
    def __init__(self, url, body, ct="application/json;charset=UTF-8"):
        self.url, self._text, self.headers = url, body, {"content-type": ct}

    def text(self):
        return self._text


def _aura(value, state="SUCCESS", prefix=""):
    return prefix + _json.dumps({"actions": [
        {"id": "1;a", "state": state, "returnValue": value}]})


AURA = "https://myaccount.pge.com/myaccount/s/sfsites/aura?r=12&aura.ApexAction.execute=1"


def test_a_bill_handed_back_inside_an_apex_answer_is_read():
    """His files showed no request for a PDF anywhere and Apex answers of
    seven to fourteen thousand characters, the size of a small bill
    written out as base64."""
    encoded = _b64.b64encode(_PDF).decode()
    for value in (encoded, {"returnValue": encoded},
                  {"returnValue": "data:application/pdf;base64," + encoded}):
        assert site._pdf_in_aura(_Res(AURA, _aura(value))) == _PDF
    assert site._pdf_in_aura(_Res(AURA, _aura(encoded, prefix="while(1);\n"))) == _PDF


def test_nothing_but_a_pdf_in_a_successful_answer_on_pge_counts():
    encoded = _b64.b64encode(_PDF).decode()
    assert site._pdf_in_aura(_Res(AURA, _aura("hello"))) is None
    assert site._pdf_in_aura(_Res(AURA, _aura(encoded, state="ERROR"))) is None
    assert site._pdf_in_aura(_Res(AURA.replace("myaccount.pge.com",
                                               "evil.example"),
                                  _aura(encoded))) is None
    not_pdf = _b64.b64encode(b"JVBERi0 but not really" * 20).decode()
    assert site._pdf_in_aura(_Res(AURA, _aura(not_pdf))) is None
    assert site._pdf_in_aura(_Res(AURA, "not json at all")) is None


def test_the_capture_listens_for_a_bill_inside_salesforces_answer():
    import inspect
    src = inspect.getsource(site.download_bill)
    assert "_pdf_in_aura(res)" in src
