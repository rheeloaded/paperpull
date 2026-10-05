"""A View press whose first answer calls itself a PDF and holds none.

In a real browser, started as a program of its own with a debugging port
the way login.bat leaves one open, with the browser's own PDF viewer, and
attached over CDP as the app attaches at home. Measured on 2026-10-05 in
Chromium 153 with Playwright 1.63, the pair CI and the packaged app run.

A PDF the page reads into a blob leaves the browser holding nothing of the
answer it came in, so that answer's body reads empty. Playwright 1.62
asked the address again by itself when that happened, and 1.63 no longer
does for a fetch or a page, so on CI the press's answer read empty while
its download came a moment later. The capture stopped at the empty answer
and the document went to manual review (Tests runs 37304657273 and
37304766489, test_resume_with_no_tab_open.py). Here the first read of that
answer reads empty on every Playwright, and the page hands the document
over only once the app has read it, so the order is the one CI met, every
time, with nothing timed.

A PDF shown in the tab after a form posts back answers with the viewer's
own page, 536 bytes of HTML, and the viewer's own answer brings the PDF a
moment later. Nothing is changed in the browser for that one.

An answer that held no PDF may be asked for once more, only with a GET on
Armed Forces Mutual's own host, never a postback and never another host,
and what comes back is kept only when it is a PDF.

The made-up Armed Forces Mutual answers at localhost, since asking again
goes through Playwright's own client outside the browser, which finds a
host through the operating system and knows no made-up name. Another site
is 127.0.0.1. Every other name fails to resolve, so nothing leaves this
machine. Every title, policy, name and date is invented.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import aafmaa_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

AAFMAA_HOST = "localhost"
ELSEWHERE_HOST = "127.0.0.1"
HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1, EXCLUDE localhost"
TARGET = "ctl00$Main$rptDocuments$ctl01$lnkViewDocument"
DOCUMENTS_PATH = "/Documents/default.aspx"
STATEMENT = testkit.text_pdf(["Armed Forces Mutual", "Premium Statement", "6/15/2026",
                              "Policy 5550001-1", "Dana Example"])

# The documents page, one row. How its View press hands the document over is
# named in the page's address, press=<way>.
#   download   reads it into a blob, waits until the app has read its
#              answer, then hands it over as a download (CI's order)
#   blob       reads it into a blob and hands nothing over
#   elsewhere  reads it from another site into a blob, nothing more
#   postback   posts the page back, and the answer is the PDF, shown in the tab
PAGE = """<!doctype html><html><head><title>Documents</title></head><body>
<main><h1>My Documents</h1>
<form method="post" action=""><input type="hidden" name="__EVENTTARGET" value=""></form>
<table><tr><th>Date</th><th>Document</th><th>Policy</th><th>View in Browser</th></tr>
<tr><td>6/15/2026</td><td>Premium Statement</td><td>5550001-1</td>
<td><a class="view" href="javascript:__doPostBack('%(target)s','')">View in Browser</a></td></tr>
</table></main>
<script>
function __doPostBack() {}
const press = new URLSearchParams(location.search).get('press');
const ELSEWHERE = '%(elsewhere)s';
function handOver(blob) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'statement.pdf';
  document.body.appendChild(a);
  a.click();
}
async function readIt() {
  while ((await (await fetch('/gate')).text()) !== 'open') {
    await new Promise(r => setTimeout(r, 25));
  }
}
document.querySelector('a.view').addEventListener('click', async (e) => {
  e.preventDefault();
  if (press === 'postback') { document.forms[0].submit(); return; }
  const from = press === 'elsewhere' ? ELSEWHERE + '/doc/0' : '/doc/0';
  const blob = await (await fetch(from)).blob();
  if (press === 'download') { await readIt(); handOver(blob); }
});
</script></body></html>"""


class FakeSite:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, host, path, Sec-Fetch-Mode). A browser
        # names a mode on each request it makes here, and Playwright's own
        # client names none, so a None is a request from outside the page.
        self.seen = []
        # The page hands the document over only once this opens, which the
        # app's read of its answer does (EmptyReads).
        self.read = False
        # What Armed Forces Mutual answers once the document has been handed
        # over, "pdf" the same again, "gone" a 410, "page" a web page.
        self.after_first = "pdf"
        self.handed = 0


SITE = FakeSite()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _noted(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path
        SITE.seen.append((self.command, host, path, self.headers.get("Sec-Fetch-Mode")))
        return host, path

    def _document(self):
        if SITE.handed and SITE.after_first == "gone":
            self._send(b"gone", "text/plain", status=410)
        elif SITE.handed and SITE.after_first == "page":
            self._send(b"<!doctype html><title>Signed out</title><p>Sign in again</p>",
                       "text/html; charset=utf-8")
        else:
            SITE.handed += 1
            self._send(STATEMENT, "application/pdf")

    def do_GET(self):
        host, path = self._noted()
        port = self.server.server_address[1]
        if host == AAFMAA_HOST and path == DOCUMENTS_PATH:
            page = PAGE % {"target": TARGET, "elsewhere": "http://%s:%d" % (ELSEWHERE_HOST, port)}
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        elif host == AAFMAA_HOST and path == "/gate":
            self._send(b"open" if SITE.read else b"shut", "text/plain")
        elif host == AAFMAA_HOST and path == "/doc/0":
            self._document()
        elif host == ELSEWHERE_HOST and path == "/doc/0":
            SITE.handed += 1
            self._send(STATEMENT, "application/pdf", extra=[
                ("Access-Control-Allow-Origin", "http://%s:%d" % (AAFMAA_HOST, port))])
        else:
            self.send_error(404)

    def do_POST(self):
        host, path = self._noted()
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if host == AAFMAA_HOST and path == DOCUMENTS_PATH:
            self._document()
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def attached(server, tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    try:
        with testkit.drawn_browser(found[0][1], lambda: tmp_path_factory.mktemp("profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_aafmaa(server, monkeypatch):
    """Armed Forces Mutual is the made-up site, its own host the only one
    the app may ask, and the row is found where the pager walk would find
    it."""
    SITE.reset()
    base = "http://%s:%d" % (AAFMAA_HOST, server)
    monkeypatch.setitem(site.URLS, "documents", base + DOCUMENTS_PATH)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (
        urlsplit(url or "").hostname == AAFMAA_HOST and urlsplit(url).port == server))
    monkeypatch.setattr(site, "_fresh_view_target", lambda *a, **kw: TARGET)
    return SITE


class EmptyReads:
    """body() reads nothing for the answers `which` picks, as Chromium
    answered on CI, the first time each is read, or every time with
    `every`. Reading one opens the gate the page waits on."""

    def __init__(self):
        self.which = lambda response: False
        self.every = False
        self.emptied = []

    def read(self):
        """Whether the app has read one of those answers yet."""
        return bool(self.emptied)


@pytest.fixture()
def empty_reads(monkeypatch):
    from playwright.sync_api import Response

    rule = EmptyReads()
    real_body = Response.body

    def body(self):
        if rule.which(self) and (rule.every or not any(r is self for r in rule.emptied)):
            rule.emptied.append(self)
            SITE.read = True
            return b""
        return real_body(self)

    monkeypatch.setattr(Response, "body", body)
    return rule


@pytest.fixture()
def press(attached, server, tmp_path):
    """Presses View in a tab of the attached browser, on the documents page
    whose press hands the document over in the way named, and says what the
    capture did and where it would have filed the document.

    A press that hands the document over keeps the app's own half-second
    looks and its thirty seconds, since the viewer's answer came up to 1.9
    seconds after the first in forty presses measured in one browser. A
    press that hands nothing over is given `quick`, which says when the app
    has read the answer the test is about. Until then each look keeps its
    own length, so a slow browser cannot run the press out of time before
    that answer is heard, and after it each look is a tenth as long, so the
    press is given up in about three seconds. The capture counts its looks
    rather than the clock, so what it does is the same either way."""
    from playwright.sync_api import sync_playwright

    driver = sync_playwright().start()
    page = None
    try:
        browser = driver.chromium.connect_over_cdp(attached)
        page = browser.contexts[0].new_page()
        own_wait = page.wait_for_timeout

        def run(way, quick=None):
            page.wait_for_timeout = lambda ms: own_wait(
                max(1, ms // 10) if quick is not None and quick() else ms)
            page.goto("http://%s:%d%s?press=%s" % (AAFMAA_HOST, server, DOCUMENTS_PATH, way),
                      wait_until="domcontentloaded")
            SITE.seen.clear()
            out = tmp_path / "Statements" / "2026-06-15 AAFMAA Premium Statement.pdf"
            saved = site.download_document_row(page, "Premium Statement", "6/15/2026",
                                               "5550001-1 Dana Example", out)
            return saved, out

        yield run
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        driver.stop()


def asked_from_outside():
    return [s for s in SITE.seen if s[3] is None]


def is_the_document(response):
    return urlsplit(response.url).hostname == AAFMAA_HOST and \
        urlsplit(response.url).path == "/doc/0"


def test_an_answer_read_empty_then_the_download(press, empty_reads):
    """CI's order. The page reads the document into a blob, the app hears
    the answer and reads nothing in it, and only then does the page hand
    the document over as a download. Asked for again, the document is gone,
    so the download is the only way it can come. The capture stopped at the
    empty answer and the document went to manual review."""
    empty_reads.which = is_the_document
    SITE.after_first = "gone"
    saved, out = press("download")
    assert empty_reads.emptied, "the app read the answer before the download came"
    assert saved is True
    assert out.read_bytes() == STATEMENT


def test_an_answer_read_empty_and_nothing_more_is_asked_for_again(press, empty_reads):
    """The page reads the document into a blob and hands nothing over. Once
    the press has gone quiet, the answer's address on Armed Forces Mutual's
    own host is asked for once more, from outside the page, and the PDF it
    answers with is filed."""
    empty_reads.which = is_the_document
    saved, out = press("blob")
    assert saved is True
    assert out.read_bytes() == STATEMENT
    asks = [s for s in SITE.seen if s[2] == "/doc/0"]
    assert [(s[0], s[1], s[3]) for s in asks] == [("GET", AAFMAA_HOST, "cors"),
                                                  ("GET", AAFMAA_HOST, None)], SITE.seen


def test_a_postback_shown_in_the_tab(press):
    """The press posts the page back and the answer is the PDF, which the
    browser shows in the tab. Nothing is changed in the browser. The
    postback's own answer reads as the viewer's page, and the PDF comes in
    the viewer's answer a moment later. The capture stopped at the viewer's
    page and the document went to manual review."""
    saved, out = press("postback")
    assert saved is True
    assert out.read_bytes() == STATEMENT
    assert [s[0] for s in SITE.seen if s[2] == DOCUMENTS_PATH] == ["POST"], SITE.seen
    assert not asked_from_outside(), SITE.seen


def test_an_answer_from_another_host_is_never_asked_for_again(press, empty_reads):
    """A PDF answer from a host that is not Armed Forces Mutual's reads
    empty. Its address is never asked for, the press is listened to until
    its time is up, and nothing is filed."""
    empty_reads.which = lambda r: urlsplit(r.url).hostname == ELSEWHERE_HOST
    saved, out = press("elsewhere", quick=empty_reads.read)
    assert empty_reads.emptied, "the other host's answer was heard and read"
    assert saved is False
    assert not out.exists()
    assert [s for s in SITE.seen if s[1] == ELSEWHERE_HOST] == [
        ("GET", ELSEWHERE_HOST, "/doc/0", "cors")], SITE.seen


def test_a_postback_is_never_sent_again(press, empty_reads):
    """Every answer reads empty, the postback's and the viewer's both. The
    postback is never sent a second time, nor its address asked for with a
    GET it never made, and nothing is filed."""
    empty_reads.which = lambda r: True
    empty_reads.every = True
    saved, out = press("postback", quick=empty_reads.read)
    assert len(empty_reads.emptied) >= 1
    assert saved is False
    assert not out.exists()
    assert [s[0] for s in SITE.seen if s[2] == DOCUMENTS_PATH] == ["POST"], SITE.seen
    assert not asked_from_outside(), SITE.seen


def test_what_an_address_asked_again_answers_is_measured(press, empty_reads):
    """Asked for again, the document's address answers with a web page, as
    a lapsed session might. Only a PDF is filed, so nothing is."""
    empty_reads.which = is_the_document
    SITE.after_first = "page"
    saved, out = press("blob", quick=empty_reads.read)
    assert saved is False
    assert not out.exists()
    assert [(s[0], s[3]) for s in SITE.seen if s[2] == "/doc/0"] == [
        ("GET", "cors"), ("GET", None)], SITE.seen
