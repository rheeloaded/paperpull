"""The interceptor against a real browser and a real server.

test_delivery.py fakes the page, which proves the decisions and proves
nothing about whether a download event fires at all, whether an inline
PDF really lands somewhere readable, or whether a blob URL can be read
back. Those are the parts that have been wrong in this codebase before.

A real HTTP server rather than Playwright's routing, because routing
covers the requests one page makes and nothing else. A tab opened by
window.open is a different page and does not inherit them, and
`context.request`, which is how thirty three apps fetch a document,
never passes through them at all. Routing made three of these tests pass
against the harness instead of against the browser.

The documents are rendered by the browser and served back to it, so the
bytes are real PDFs and pypdf reads them the way it will read a bank's.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import delivery as D
from paperpull_core import identity as I

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

RECEIPT = """<!doctype html><title>Receipt</title>
<body style="font:14px system-ui;padding:24px">
<h1>Testco</h1><p>Order Number 8421997301</p><p>January 15, 2026</p>
<p>Total $1,284.55</p>
<p>Retain this document for your records. It is required for returns and
for any warranty claim you may wish to make against this purchase.</p>
</body>"""

NEIGHBOR = (RECEIPT.replace("8421997301", "8421997999")
                   .replace("January 15, 2026", "February 9, 2026")
                   .replace("$1,284.55", "$76.41"))

RIGHT = I.Identity(date="2026-01-15", total="1284.55", number="8421997301")

EXPIRED = b"<html>Your session has expired. Please sign in.</html>" + b" " * 900


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def pdfs(browser, tmp_path_factory):
    """Two real PDFs, rendered by the browser, one per document."""
    from paperpull_core import receipt_pdf
    out = {}
    d = tmp_path_factory.mktemp("pdfs")
    page = browser.new_page()
    try:
        for name, html in (("right", RECEIPT), ("wrong", NEIGHBOR)):
            page.set_content(html, wait_until="load")
            target = d / (name + ".pdf")
            receipt_pdf.print_page_to_pdf(page, target)
            out[name] = target.read_bytes()
    finally:
        page.close()
    assert out["right"].startswith(b"%PDF")
    assert out["right"] != out["wrong"]
    return out


@pytest.fixture(scope="module")
def server(pdfs):
    """A provider, near enough.

    /            a page with one link
    /doc.pdf     the document, dressed as the query string asks
                 which=right|wrong|expired, d=attachment|inline|none
    """

    class Handler(BaseHTTPRequestHandler):
        # Keep-alive, so a browser reuses one connection rather than
        # opening one per request. Every answer here carries its length.
        # Closed after each request, the whole core suite left enough
        # sockets waiting on a Windows CI runner that a navigation failed
        # with ERR_NO_BUFFER_SPACE before this test had captured anything.
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            parts = urlparse(self.path)
            query = parse_qs(parts.query)
            if parts.path != "/doc.pdf":
                body = (b'<a id="go" href="/doc.pdf?' +
                        parts.query.encode() + b'">Download statement</a>')
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            which = (query.get("which") or ["right"])[0]
            body = EXPIRED if which == "expired" else pdfs[which]
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            disposition = (query.get("d") or ["inline"])[0]
            if disposition != "none":
                self.send_header("content-disposition",
                                 '%s; filename="statement.pdf"' % disposition)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    yield base
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(accept_downloads=True)
    p = ctx.new_page()
    yield p
    ctx.close()


def guard(server):
    def is_safe(url):
        return str(url or "").startswith(server + "/")
    return is_safe


def open_list(page, server, query=""):
    page.goto(server + "/" + ("?" + query if query else ""))


# -- an attachment, which is how twenty three apps get a document -------------

def test_an_attachment_header_fires_a_download_and_it_is_caught(
        page, server, tmp_path):
    open_list(page, server, "d=attachment&which=right")
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.click("#go"), expect=RIGHT),
        out, is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.SAVED, got.report()
    assert got.mechanism == D.DOWNLOAD
    assert out.read_bytes().startswith(b"%PDF")


def test_the_wrong_document_is_refused_end_to_end(page, server, tmp_path):
    """The reason all of this was built in this order. A real PDF
    arrives, pypdf reads it, and it is February's."""
    open_list(page, server, "d=attachment&which=wrong")
    out = tmp_path / "January statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.click("#go"), expect=RIGHT),
        out, is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.WRONG, got.report()
    assert not out.exists(), "a wrong document reached the archive"
    assert list(tmp_path.iterdir()) == [], "a staging file was left behind"


def test_and_the_same_document_verifies_against_its_own_details(
        page, server, tmp_path):
    """A refusal that refuses everything is not a check, it is a bug."""
    open_list(page, server, "d=attachment&which=wrong")
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.click("#go"),
        expect=I.Identity(date="2026-02-09", number="8421997999")),
        tmp_path / "february.pdf", is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.SAVED, got.report()


# -- asking, which needs no click and no routing ------------------------------

def test_asking_for_the_url_needs_no_click_at_all(page, server, tmp_path):
    """Thirty three apps work this way and trigger nothing. The request
    goes through context.request, carrying the session's cookies, which
    is why this test needs a real server."""
    open_list(page, server)
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        url=server + "/doc.pdf?which=right", expect=RIGHT),
        out, is_safe_url=guard(server))
    assert got.outcome == D.SAVED, got.report()
    assert got.mechanism == D.ASK
    assert out.read_bytes().startswith(b"%PDF")


def test_asking_for_the_wrong_document_is_refused_too(page, server, tmp_path):
    open_list(page, server)
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        url=server + "/doc.pdf?which=wrong", expect=RIGHT),
        out, is_safe_url=guard(server))
    assert got.outcome == D.WRONG, got.report()
    assert not out.exists()


def test_a_host_the_app_does_not_allow_is_never_asked(page, server, tmp_path):
    open_list(page, server)
    got = D.deliver(page, D.DocumentRequest(
        url="http://127.0.0.1:1/doc.pdf", expect=RIGHT),
        tmp_path / "s.pdf", is_safe_url=guard(server))
    assert got.outcome == D.NOTHING


# -- a tab, and what headless does to one -------------------------------------

def test_a_document_opened_in_a_new_tab_is_caught(page, server, tmp_path):
    """Headless Chromium ships no PDF viewer, so an inline PDF opened in
    a tab may arrive as a download instead of a rendered tab. Either is
    a correct catch and the mechanism is not asserted, because which one
    happens is a property of the browser rather than of the provider.
    That difference is the same one that makes columns A and B of
    docs/delivery-architecture.md two columns."""
    open_list(page, server)
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.evaluate(
            "url => window.open(url, '_blank')",
            server + "/doc.pdf?which=right&d=inline"),
        expect=RIGHT),
        out, is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.SAVED, got.report()
    assert got.mechanism in (D.TAB, D.DOWNLOAD)
    assert out.read_bytes().startswith(b"%PDF")


def test_a_blob_url_built_in_the_page_is_caught(page, server, tmp_path):
    """Eleven providers hand over a file their own JavaScript built, and
    a blob: address means nothing outside the page that minted it."""
    open_list(page, server)
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.evaluate("""async (url) => {
            const r = await fetch(url);
            const b = await r.blob();
            window.open(URL.createObjectURL(b), '_blank');
        }""", server + "/doc.pdf?which=right&d=inline"),
        expect=RIGHT),
        out, is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.SAVED, got.report()
    assert out.read_bytes().startswith(b"%PDF")


# -- the answers that are not a document --------------------------------------

def test_an_expired_link_answering_html_is_told_apart_from_silence(
        page, server, tmp_path):
    """A site that answers an expired link with a sign-in page still
    produces a download with a plausible size."""
    open_list(page, server, "d=attachment&which=expired")
    out = tmp_path / "statement.pdf"
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.click("#go"), expect=RIGHT),
        out, is_safe_url=guard(server), settle_ms=8000)
    assert got.outcome == D.NOT_A_PDF, got.report()
    assert not out.exists()
    assert "expired link" in " ".join(D.summarize(got.report()))


def test_a_control_that_does_nothing_names_what_was_watched(
        page, server, tmp_path):
    open_list(page, server)
    got = D.deliver(page, D.DocumentRequest(
        trigger=lambda: page.evaluate("() => void 0"), expect=RIGHT),
        tmp_path / "s.pdf", is_safe_url=guard(server), settle_ms=1500)
    assert got.outcome == D.NOTHING
    assert D.DOWNLOAD in got.armed and D.TAB in got.armed
    assert "nothing came back" in " ".join(D.summarize(got.report()))


# -- a run is hundreds of these in one session --------------------------------

def test_capturing_many_documents_in_one_session_keeps_working(
        page, server, tmp_path):
    """A leaked listener would have each capture see the previous
    document's download, which on a real archive shows up as every file
    holding the one before it."""
    open_list(page, server, "d=attachment&which=right")
    for i in range(4):
        got = D.deliver(page, D.DocumentRequest(
            trigger=lambda: page.click("#go"), expect=RIGHT),
            tmp_path / ("s%d.pdf" % i), is_safe_url=guard(server),
            settle_ms=8000)
        assert got.outcome == D.SAVED, (i, got.report())
    assert len(list(tmp_path.glob("*.pdf"))) == 4
