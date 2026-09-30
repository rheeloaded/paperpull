"""Print receipts, pressed in a real browser, is seen for what it did.

Target's Print receipts builds the receipt in a frame of its own and calls
print() from there. The core's hook, installed on every page the app opens,
keeps that document at the moment print() is called and marks the page.
Since Target moved onto the core in August the marks carry the core's
names, and trigger_print_receipt went on reading the names Target's own
hook had used. So it never saw a print. Every press waited out its fifteen
seconds and came back as "inline", and the reset meant to forget a print
left by an earlier press on the same page reset names nothing reads. A
press that printed nothing was then handed the receipt the press before it
had printed.

Every page, order and receipt here is invented and served from this
machine, and no other host name resolves.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts
import target_site as site
from paperpull_core import receipt_pdf
from paperpull_core.models import IN_STORE, Purchase
from paperpull_core.testkit import receipt_app

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# Each invented order's Print receipts behaves one way. Most print from a
# frame made for it and removed right after, the way Target does, one
# prints the page itself, one only after the site has answered, one keeps
# its frame on the page, and one draws its receipt on the page and prints
# nothing.
FIRST, ON_PAGE, LATE, KEPT, NEVER = (
    "902000101", "902000102", "902000203", "902000404", "902000305")
PRESS = {FIRST: "frame", ON_PAGE: "page", LATE: "frame", KEPT: "kept", NEVER: "shown"}
LATE_SECONDS = 2.5


def receipt(number: str) -> str:
    """A receipt as the frame that prints it holds it, a whole document."""
    rows = "".join("<tr><td>Invented item %d of order %s</td><td>1</td></tr>" % (i, number)
                   for i in range(1, 9))
    return ("<!doctype html><html><head><title>Receipt</title></head><body>"
            "<h1>Store receipt</h1><p>Order number %s</p><table>%s</table>"
            "<p>Thank you for shopping.</p></body></html>" % (number, rows))


def drawn(number: str) -> str:
    """A receipt drawn on the page itself, where the app looks for one."""
    return ('<div data-test="store-pos-order-receipt-container"><h2>Store receipt</h2>'
            "<p>Order number %s</p><p>Invented item of order %s</p></div>" % (number, number))


# The receipts page. Pressing Print receipts asks the site for the order's
# receipt, then does what that order does. showOrder draws another order on
# the same document, the way Target draws each of its routes itself.
PAGE = """<!doctype html><html><head><title>Orders : Receipts</title></head><body>
<main><h1>Receipts and invoices</h1><div id="shown"></div>
<button id="print" type="button">Print receipts</button></main>
<script>
window.showOrder = (n) => {
  history.pushState({}, '', '/orders/' + n + '/receipts');
  window.order = n;
  document.getElementById('shown').innerHTML = '';
};
function printFromFrame(html, keep) {
  const f = document.createElement('iframe');
  f.name = keep ? 'kept' : 'passing';
  f.style.display = 'none';
  document.body.appendChild(f);
  f.contentDocument.open();
  f.contentDocument.write(html);
  f.contentDocument.close();
  f.contentWindow.print();
  if (!keep) f.remove();
}
document.getElementById('print').addEventListener('click', async () => {
  const o = await (await fetch('/api/receipts/' + window.order)).json();
  if (o.press === 'page') {
    document.getElementById('shown').innerHTML = o.html;
    window.print();
  } else if (o.press === 'shown') {
    document.getElementById('shown').innerHTML = o.html;
  } else {
    printFromFrame(o.html, o.press === 'kept');
  }
});
window.showOrder(location.pathname.split('/')[2]);
</script></body></html>"""


class _Target(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body: str, kind: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[:2] == ["api", "receipts"] and parts[2:] and parts[2] in PRESS:
            number = parts[2]
            if number == LATE:
                time.sleep(LATE_SECONDS)
            press = PRESS[number]
            html = drawn(number) if press in ("page", "shown") else receipt(number)
            self._send(json.dumps({"press": press, "html": html}), "application/json")
        elif parts[:1] == ["orders"] and parts[1:2] and parts[1] in PRESS:
            self._send(PAGE, "text/html; charset=utf-8")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Target)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser():
    try:
        driver = sync_playwright().start()
        b = driver.chromium.launch(headless=True, args=[NO_HOSTS])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture()
def receipts(server, browser):
    """Opens an order's receipts page in a context of its own, the hook
    installed on it the way the app installs it on the browser it uses."""
    contexts = []

    def open_order(number: str):
        context = browser.new_context()
        contexts.append(context)
        context.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
        page = context.new_page()
        page.goto("%s/orders/%s/receipts" % (server, number))
        return page

    yield open_order
    for context in contexts:
        context.close()


def print_receipts(page):
    """The control the app itself would press."""
    controls = site.find_print_receipt_controls(page)
    assert controls, "the fake page has a Print receipts control"
    return controls[0]


def show(page, number: str):
    page.evaluate("n => window.showOrder(n)", number)


def marked_frames(page) -> list:
    return [f.name for f in page.frames
            if f != page.main_frame and receipt_pdf.was_print_called(f)]


def first_press(page):
    """Given the app's own time, so on a slow machine the first press's
    print cannot land while the second press is being watched."""
    site.trigger_print_receipt(page, print_receipts(page))


@pytest.mark.parametrize("number", [FIRST, ON_PAGE], ids=["from its own frame", "the page itself"])
def test_a_press_that_prints_is_known_at_once(receipts, number):
    page = receipts(number)
    started = time.monotonic()
    kind, shown_on = site.trigger_print_receipt(page, print_receipts(page))
    took = time.monotonic() - started
    assert kind == "print_called", "reported as %r after %.1f s" % (kind, took)
    assert shown_on is page
    assert took < 8, "a print that came at once was waited on for %.1f s" % took
    assert number in (receipt_pdf.get_print_snapshot(page) or "")


def test_the_next_press_on_the_same_page_waits_for_its_own_print(receipts):
    """The site answers the second press only after a moment. A mark left by
    the first press would be taken for this one's, with the first receipt
    still kept."""
    page = receipts(FIRST)
    first_press(page)
    show(page, LATE)
    started = time.monotonic()
    kind, _ = site.trigger_print_receipt(page, print_receipts(page))
    took = time.monotonic() - started
    kept = receipt_pdf.get_print_snapshot(page) or ""
    assert kind == "print_called", "reported as %r after %.1f s" % (kind, took)
    assert LATE in kept, "the second press's receipt is the one kept"
    assert FIRST not in kept, "the first press's receipt was taken for the second's"
    assert took < 10, "the second press was waited on for %.1f s" % took


def test_a_press_that_prints_nothing_is_never_handed_the_receipt_before_it(receipts, tmp_path):
    """The second order draws its receipt on the page and prints nothing.
    What the app saves for it has to be that receipt, not the one the press
    before printed on the same page."""
    page = receipts(FIRST)
    first_press(page)
    assert FIRST in (receipt_pdf.get_print_snapshot(page) or ""), "the first press printed"
    show(page, NEVER)
    kind, _ = site.trigger_print_receipt(page, print_receipts(page), timeout_ms=1000)
    assert kind == "inline"
    left = receipt_pdf.get_print_snapshot(page) or ""
    assert FIRST not in left, "the first press's receipt was still kept for the second"

    app = receipt_app(target_receipts, tmp_path)
    out = tmp_path / "saved.pdf"
    app._capture_document(page, Purchase(purchase_type=IN_STORE, order_number=NEVER),
                          out, "store-receipt")
    saved = receipt_pdf.pdf_text(out)
    assert NEVER in saved
    assert FIRST not in saved


def test_a_frame_marked_by_the_press_before_is_not_marked_for_the_next(receipts):
    """A site that keeps its print frame keeps the mark in it too, and
    find_printing_frame looks in frames for that mark first."""
    page = receipts(KEPT)
    first_press(page)
    assert marked_frames(page) == ["kept"], "the fake's frame printed and stayed"
    show(page, NEVER)
    site.trigger_print_receipt(page, print_receipts(page), timeout_ms=1000)
    assert marked_frames(page) == [], "the frame still says it printed for this press"
