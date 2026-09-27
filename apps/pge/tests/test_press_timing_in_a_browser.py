"""When things happen around the press. From the second review of round
eight (#33).

Playwright's click waits on a page load the click started, and raises
when that load is slow, after the click has already arrived. The link's
own click that followed was a second press on his account.

And the ears closed about eleven seconds after the press, before the
wait for a viewer. A bill slower than that was lost, and a very late one
could be heard in the next bill's window and saved under that bill's
name. They stay open now until the viewer wait is over.

Every date, byte and address here is invented.
"""
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site


def _browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    return driver, browser


# -- a press that arrived and then raised -------------------------------------

LINK_THAT_LOADS_SLOWLY = (
    b"<a id=l>View Bill PDF</a><script>"
    b"document.getElementById('l').addEventListener('click', () => {"
    b" location.href = '/viewer'; });</script>")


class _SlowViewer(BaseHTTPRequestHandler):
    """Answers the viewer seven seconds late and counts every request for
    it, which is how a second press shows up."""
    asked = []

    def do_GET(self):
        if self.path.startswith("/viewer"):
            type(self).asked.append(time.monotonic())
            time.sleep(7)
            body = b"<p>a viewer</p>"
        else:
            body = LINK_THAT_LOADS_SLOWLY
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def log_message(self, *a):
        pass


@pytest.fixture()
def slow_site():
    _SlowViewer.asked = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowViewer)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    driver, browser = _browser()
    ctx = browser.new_context()
    ctx.set_default_timeout(30000)          # what pge_docs sets
    page = ctx.new_page()
    page.goto("http://127.0.0.1:%d/" % server.server_address[1])
    yield page
    browser.close()
    driver.stop()
    server.shutdown()
    server.server_close()


def test_a_press_that_raised_after_it_arrived_is_not_pressed_again(slow_site):
    said = {}
    site._press_once(slow_site, slow_site.query_selector("#l"), lambda: False,
                     seconds=1.0, said=said)
    # A second press would ask for the viewer again straight away.
    time.sleep(1.5)
    assert len(_SlowViewer.asked) == 1, "the link was pressed twice"
    assert said == {"landed": True, "own_click": False, "late_error": True}


# -- a bill slower than the press window --------------------------------------

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
_LATE = "%PDF-1.4 a late invented bill"

# The press hands the bill over as a download fourteen and a half seconds
# later. The press window closes near eleven seconds, and the viewer wait
# after it runs past eighteen, so this lands inside the wait.
ROW = """<table><tbody><tr class="rowbox">
  <td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td>
  <td></td>
  <td><div class="align-right"><a class="pdf-link">View Bill PDF</a></div></td>
  <td class="no-padding-right"><p class="payoffamount-divpara">$12.34</p></td>
</tr></tbody></table>
<script>
  window.presses = 0;
  document.querySelector('a.pdf-link').addEventListener('click', () => {
    window.presses++;
    setTimeout(() => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob(['%s'], {type: 'application/octet-stream'}));
      a.download = 'late.pdf';
      document.body.appendChild(a);
      a.click();
    }, 14500);
  });
</script>""" % _LATE


def test_a_bill_slower_than_the_press_window_is_taken_for_its_own_bill(tmp_path):
    from paperpull_core.journal import Journal
    driver, browser = _browser()
    try:
        ctx = browser.new_context(accept_downloads=True)
        ctx.set_default_timeout(30000)
        ctx.route("https://myaccount.pge.com/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body="<h1>history</h1>"))
        page = ctx.new_page()
        page.goto(HISTORY)
        page.set_content(ROW)
        out = tmp_path / "bill.pdf"
        j = Journal(page)
        site.set_journal(j)
        t0 = time.monotonic()
        try:
            ok = site.download_bill(page, {"date_text": "2031-04-17", "row_index": 0,
                                           "page_number": 1}, out, {})
        finally:
            site.set_journal(None)
        took = time.monotonic() - t0
        assert ok is True, "the bill arrived %.1fs after the press and was lost" % 14.5
        assert out.read_bytes() == _LATE.encode()
        assert page.evaluate("window.presses") == 1
        pressed = [e.get("facts", {}) for e in j.report()["entries"]
                   if e.get("kind") == "result" and e.get("outcome") == "pressed the pdf control"]
        assert pressed and pressed[0]["download"] is True and pressed[0]["from_page"] is False
        assert took > 14.0
    finally:
        browser.close()
        driver.stop()
