"""A bill is saved only from what its own press brought. From the third
review of round eight (#33).

Four ways something else could have been saved under a bill's date.
A viewer an earlier bill left open, whose frame had followed a redirect
away from the address its viewer names, was fetched again when the next
press brought nothing. A download of an earlier bill's blob, held back by
the browser and let go later, was heard as the next bill. A PDF that
another tab loaded while a bill was open was heard on the whole browser
and taken, from any host. And for a new tab standing at a PDF on another
PG&E address, the download link the history made for it moved the
history tab itself to the PDF instead of saving anything.

Every date, byte and address here is invented, and nothing is asked of a
real host (conftest.py answers the session's requests).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
_PDF = b"%PDF-1.4 an invented bill"

# Two bill rows in his round three shape, each link with its own id.
ROWS = """<table><tbody>
<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right"><a class="pdf-link" id="a">View Bill PDF</a></div></td>
  <td><p class="payoffamount-divpara">$12.34</p></td></tr>
<tr class="rowbox"><td><div class="slds-col row-box">03/18/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right"><a class="pdf-link" id="b">View Bill PDF</a></div></td>
  <td><p class="payoffamount-divpara">$56.78</p></td></tr>
</tbody></table><div id="dlg"></div>
<script>
  window.presses = 0;
  const on = (id, fn) => document.getElementById(id).addEventListener('click', () => {
    window.presses++; fn(); });
  %s
</script>"""

A = {"date_text": "2031-04-17", "row_index": 0, "page_number": 1}
B = {"date_text": "2031-03-18", "row_index": 1, "page_number": 1}


def _serve(extra=None):
    extra = dict(extra or {})

    def serve(route):
        url = route.request.url
        for part, (ctype, body) in extra.items():
            if part in url:
                route.fulfill(status=200, headers={"content-type": ctype}, body=body)
                return
        route.fulfill(status=200, headers={"content-type": "text/html"},
                      body="<h1>history</h1>")
    return serve


def _launch(extra=None):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.set_default_timeout(30000)          # what pge_docs sets
    ctx.route("**/*", lambda r: r.abort())
    for host in ("https://myaccount.pge.com/**", "https://www.pge.com/**",
                 "https://elsewhere.test/**"):
        ctx.route(host, _serve(extra))
    return driver, browser, ctx


def _take(page, doc, out):
    from paperpull_core.journal import Journal
    j = Journal(page)
    site.set_journal(j)
    try:
        ok = site.download_bill(page, doc, out, {})
    finally:
        site.set_journal(None)
    results = [(e.get("outcome"), e.get("facts", {})) for e in j.report()["entries"]
               if e.get("kind") == "result"]
    return ok, results


@pytest.fixture()
def browser_parts():
    made = []

    def make(extra=None):
        parts = _launch(extra)
        made.append(parts)
        return parts

    yield make
    for driver, browser, _ in made:
        browser.close()
        driver.stop()


# -- a viewer an earlier bill left open ---------------------------------------

def test_an_earlier_bills_viewer_that_moved_on_is_never_saved_as_the_next(
        browser_parts, session, tmp_path):
    """The safety review's probe. Bill A's viewer names one address, and its
    frame has followed a redirect to another. The next press brings
    nothing, and the page was asked again for the address the frame stood
    at, which was bill A."""
    bill_a = "https://myaccount.pge.com/sfc/files/invented-bill-a"
    session.answers[bill_a] = b"%PDF-1.4 invented bill A"
    _, _, ctx = browser_parts({
        "viewbill": ("text/html", "<script>location.replace('/sfc/files/invented-bill-a')</script>"),
        "/sfc/files/": ("text/plain", "not the bill, only a stand in for the viewer's page")})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % """
      on('a', () => { document.getElementById('dlg').innerHTML =
        '<div role="dialog"><iframe src="/myaccount/s/viewbill?bill=A"></iframe></div>'; });
      on('b', () => {});      // the site ignores a second press while its dialog is open
    """)
    ok_a, _ = _take(page, A, tmp_path / "a.pdf")
    assert ok_a is True and (tmp_path / "a.pdf").read_bytes() == b"%PDF-1.4 invented bill A"
    assert any(f.url == bill_a for f in page.frames), "the frame stands at an address its viewer does not name"

    ok_b, results = _take(page, B, tmp_path / "b.pdf")
    assert ok_b is False, "bill A was saved under bill B's date"
    assert not (tmp_path / "b.pdf").exists()
    assert page.evaluate("window.presses") == 2
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed and pressed[0]["from_page"] is False
    # everything the session was asked for was on PG&E and answered here
    assert all(u.startswith("https://myaccount.pge.com/") for _, u in session.asked)


# -- a download of an earlier bill's blob --------------------------------------

def test_a_download_of_an_earlier_bills_blob_is_never_saved_as_the_next(
        browser_parts, tmp_path):
    """Bill A opens in a new tab at a blob, and is taken. While bill B is
    open, a download of that same blob turns up, the shape of a save the
    browser held back and let go later. It belongs to bill A."""
    _, _, ctx = browser_parts({"/viewer-b": ("text/html", "<p>a viewer with nothing in it</p>")})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % """
      on('a', () => {
        const b = new TextEncoder().encode('%PDF-1.4 invented bill A');
        window.lastBlob = URL.createObjectURL(new Blob([b], {type: 'text/plain'}));
        window.open(window.lastBlob);
      });
      on('b', () => {
        setTimeout(() => {
          const a = document.createElement('a');
          a.href = window.lastBlob; a.download = 'late.pdf';
          document.body.appendChild(a); a.click();
        }, 500);
        document.getElementById('dlg').innerHTML =
          '<div role="dialog"><iframe src="/myaccount/s/viewer-b"></iframe></div>';
      });
    """)
    ok_a, _ = _take(page, A, tmp_path / "a.pdf")
    assert ok_a is True and (tmp_path / "a.pdf").read_bytes() == b"%PDF-1.4 invented bill A"

    ok_b, results = _take(page, B, tmp_path / "b.pdf")
    assert ok_b is False, "bill A's blob was saved under bill B's date"
    assert not (tmp_path / "b.pdf").exists()
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed and pressed[0]["download"] is False


def test_a_download_of_an_address_saved_for_an_earlier_bill_is_never_the_next(
        browser_parts, tmp_path):
    """The same for a new tab at a PDF on the history's own origin, which
    the contributor's download link saves when the session cannot fetch
    it. A download of that address turning up while bill B is open is
    bill A's.

    A download a link starts is not routed, so here it can reach no host
    and the browser gives it up (conftest.py). What this shows is whose
    download each bill takes it to be, which is the part that decides
    where a late one would be saved."""
    _, _, ctx = browser_parts({
        "/docs/": ("text/html", "<p>the browser's viewer</p>"),
        "/viewer-b": ("text/html", "<p>a viewer with nothing in it</p>")})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % """
      on('a', () => window.open('/docs/invented-bill-a.pdf'));
      on('b', () => {
        setTimeout(() => {
          const a = document.createElement('a');
          a.href = '/docs/invented-bill-a.pdf'; a.download = 'late.pdf';
          document.body.appendChild(a); a.click();
        }, 500);
        document.getElementById('dlg').innerHTML =
          '<div role="dialog"><iframe src="/myaccount/s/viewer-b"></iframe></div>';
      });
    """)
    ok_a, results_a = _take(page, A, tmp_path / "a.pdf")
    ok_b, results = _take(page, B, tmp_path / "b.pdf")
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed and pressed[0]["download"] is False, "bill A's download was taken as bill B's"
    assert ok_b is False and not (tmp_path / "b.pdf").exists()
    # and bill A's tab was read, its address saved from, and nothing came
    assert ok_a is False
    assert ("read the new tab", {"pge_origin": True, "bill": False, "by_download": False}) in results_a


# -- a PDF somewhere else while a bill is open ---------------------------------

STRAYS = {
    # another tab the history never opened, on PG&E itself
    "another tab": ("tab", "https://www.pge.com/rates/invented-rate-schedule.pdf"),
    # the history itself, loading a PDF from a host that is not PG&E's
    "another host": ("history", "https://elsewhere.test/invented-flyer.pdf"),
}


@pytest.mark.parametrize("where", sorted(STRAYS))
def test_a_pdf_the_press_did_not_bring_is_never_the_bill(browser_parts, tmp_path, where):
    who, stray = STRAYS[where]
    _, _, ctx = browser_parts({
        "invented-": ("application/pdf", "%PDF-1.4 not a bill at all"),
        "/viewer-b": ("text/html", "<p>a viewer with nothing in it</p>")})
    page = ctx.new_page()
    page.goto(HISTORY)
    # The other tab is set going before the bill is taken, so it waits long
    # enough to land well inside the press, which lasts eleven seconds.
    delay = 4000 if who == "tab" else 1000
    fetch_it = ("setTimeout(() => fetch('%s', {mode: 'no-cors'}).catch(() => 0), %d);"
                % (stray, delay))
    page.set_content(ROWS % ("""
      on('b', () => {
        %s
        document.getElementById('dlg').innerHTML =
          '<div role="dialog"><iframe src="/myaccount/s/viewer-b"></iframe></div>';
      });""" % (fetch_it if who == "history" else "")))
    if who == "tab":
        other = ctx.new_page()
        other.goto("https://www.pge.com/en/home")
        other.evaluate("() => { %s }" % fetch_it)
        page.bring_to_front()
    ok, results = _take(page, B, tmp_path / "b.pdf")
    assert ok is False, "a PDF the press did not bring was saved as the bill"
    assert not (tmp_path / "b.pdf").exists()
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed and pressed[0]["answer"] is False


def test_a_pdf_in_a_tab_the_history_opened_before_the_press_is_never_the_bill(
        browser_parts, tmp_path):
    """An answer counted as the bill's when it came from the history or from
    any tab the history had opened, whenever that was. So a tab left open
    from before the press, one an earlier bill opened or one opened from the
    history by hand, loading a PDF while this bill was open, had that PDF
    saved as this bill. Only a tab this press opened counts now (review of
    round eight's repair)."""
    _, _, ctx = browser_parts({
        "invented-": ("application/pdf", "%PDF-1.4 not a bill at all"),
        "/viewer-b": ("text/html", "<p>a viewer with nothing in it</p>")})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % """
      on('b', () => {
        document.getElementById('dlg').innerHTML =
          '<div role="dialog"><iframe src="/myaccount/s/viewer-b"></iframe></div>';
      });""")
    with page.expect_popup() as opened:
        page.evaluate("() => { window.open('https://myaccount.pge.com/myaccount/s/rates'); }")
    earlier = opened.value
    earlier.wait_for_load_state()
    assert earlier.opener() is page, "the history opened it"
    # Set going before the bill is taken, to land well inside the press.
    earlier.evaluate("() => { setTimeout(() => fetch('/myaccount/s/invented-rates.pdf')"
                     ".catch(() => 0), 4000); }")
    page.bring_to_front()
    ok, results = _take(page, B, tmp_path / "b.pdf")
    assert ok is False, "a PDF in a tab open before the press was saved as the bill"
    assert not (tmp_path / "b.pdf").exists()
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed and pressed[0]["answer"] is False
    assert not earlier.is_closed(), "a tab open before the press is left as it was"


def test_the_first_answer_of_the_tab_the_press_opened_is_still_the_bill(
        browser_parts, tmp_path):
    """A new tab's first answer comes before the tab can be named, and it
    is the one answer the round five listener was put on the whole browser
    to hear. It is held by address and taken once the tab stands there."""
    _, _, ctx = browser_parts({"/docs/": ("text/plain", _PDF.decode())})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % """
      on('b', () => window.open('https://myaccount.pge.com/docs/invented-bill.pdf'));""")
    ok, results = _take(page, B, tmp_path / "b.pdf")
    assert ok is True and (tmp_path / "b.pdf").read_bytes() == _PDF
    pressed = [f for o, f in results if o == "pressed the pdf control"]
    assert pressed[0]["tab"] is True and pressed[0]["answer"] is True
    assert len(page.context.pages) == 1


# -- a new tab at a PDF on another PG&E address --------------------------------

def test_a_new_tab_at_a_pdf_on_another_pge_address_is_saved_and_the_history_stays(
        browser_parts, session, tmp_path):
    """The contributor's download link was made on the history for the new
    tab's address. On another origin the browser ignores the download mark
    and follows the link, so the history tab itself went to the PDF and
    nothing was saved. It is asked for through the session now."""
    pdf_url = "https://www.pge.com/bills/invented-bill.pdf"
    session.answers[pdf_url] = _PDF
    # What the tab shows is not a PDF the listener could take, so only the
    # way the new tab's address is read decides.
    _, _, ctx = browser_parts({"/bills/": ("text/plain", "the browser's viewer")})
    page = ctx.new_page()
    page.goto(HISTORY)
    page.set_content(ROWS % ("on('b', () => window.open('%s'));" % pdf_url))
    ok, results = _take(page, B, tmp_path / "b.pdf")
    assert page.url == HISTORY, "the history tab went to the PDF"
    assert ok is True and (tmp_path / "b.pdf").read_bytes() == _PDF
    assert ("read the new tab", {"pge_origin": True, "bill": True, "by_download": False}) in results
    assert ("get", pdf_url) in session.asked
