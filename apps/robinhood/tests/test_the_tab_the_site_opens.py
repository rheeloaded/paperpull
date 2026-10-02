"""The tab Robinhood opens for a statement is closed, however late it comes.

A statement's Download PDF asks Robinhood's API for a signed link, and the
page opens that link in a new tab once the answer is in (see the note above
_click_and_capture). The app takes the PDF from the link in the answer. The
answer always comes before the tab, since the page needs it to open one,
and the press closed only the tabs it had heard of by then. A tab that
reached Playwright a moment later stayed open in the person's browser, one
per statement.

Every page is served from memory, the link from a server on this machine,
and every other request is refused, so nothing leaves this machine.
"""
import logging
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import robinhood_site as site  # noqa: E402
from paperpull_core.testkit import TabsHeardLate  # noqa: E402

STATEMENTS = "https://robinhood.com/account/reports-statements"
API = "https://api.robinhood.com/documents/invented-statement/download/?redirect=false"
PDF = b"%PDF-1.4 invented statement " + b"x" * 400

PAGE = """<!doctype html><html><body><main><h1>Statements</h1>
<a href="#" id="pdf">Download PDF</a></main><script>
const API = '%s';
document.getElementById('pdf').addEventListener('click', (e) => {
  e.preventDefault();
  %%s
});
</script></body></html>""" % API

# What the recording showed, the answer and then the tab.
ONCE = "fetch(API).then(r => r.json()).then(j => window.open(j.download_url, '_blank'));"

# The page asks again a second after the first answer and opens its tab a
# second and a half after that, so the second answer lands while the press
# waits for the tab.
TWICE = ("fetch(API).then(r => r.json()).then(j => {"
         " setTimeout(() => fetch(API), 1000);"
         " setTimeout(() => window.open(j.download_url, '_blank'), 2500); });")


class _Link(BaseHTTPRequestHandler):
    """The signed link's answer, the PDF."""
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF)))
        self.end_headers()
        self.wfile.write(PDF)

    def log_message(self, *args):
        pass


@pytest.fixture()
def statements(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Link)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    link = "http://127.0.0.1:%d/invented-statement.pdf" % server.server_address[1]
    # The link Robinhood hands back is on its document store. Here it is on
    # this machine, and only that one address passes.
    monkeypatch.setattr(site, "is_document_store_url", lambda url: url == link)
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        server.shutdown()
        server.server_close()
        pytest.skip("no browser to drive: %s" % e)
    served = {"page": "", "links": [link]}
    asked: list = []

    def answer(route):
        # The API answers each asking in turn with the next link it is
        # given, and the last one after that.
        url = served["links"][min(len(asked), len(served["links"]) - 1)]
        asked.append(url)
        route.fulfill(status=200, content_type="application/json",
                      headers={"Access-Control-Allow-Origin": "*"},
                      body='{"download_url": "%s"}' % url)

    ctx = browser.new_context(accept_downloads=False)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(STATEMENTS, lambda r: r.fulfill(status=200, content_type="text/html", body=served["page"]))
    ctx.route(lambda url: url.startswith("https://api.robinhood.com/documents/"), answer)
    page = ctx.new_page()

    def show(script, *links):
        served["page"] = PAGE % script
        served["links"] = list(links) or [link]
        page.goto(STATEMENTS)
        return page

    yield SimpleNamespace(show=show, link=link, asked=asked)
    browser.close()
    driver.stop()
    server.shutdown()
    server.server_close()


def _heard(page):
    heard: list = []
    page.context.on("page", lambda p: heard.append(p))
    return heard


def _wait_until_heard(page, heard, real_wait):
    # The tab has to have reached Playwright before whether it was closed
    # means anything.
    deadline = time.monotonic() + 20
    while not heard and time.monotonic() < deadline:
        real_wait(100)
    return heard


@pytest.mark.parametrize("seconds", [0, 1.5], ids=["at the next turn", "a moment later"])
def test_the_tab_the_site_opens_after_its_answer_is_closed(statements, tmp_path, monkeypatch, caplog,
                                                           seconds):
    caplog.set_level(logging.INFO)
    page = statements.show(ONCE)
    heard = _heard(page)
    late = TabsHeardLate(monkeypatch)
    answered: list = []
    page.on("response", lambda r: answered.append(r.url) if "/documents/" in r.url else None)
    # The tab reaches Playwright once the app's own wait has come back with
    # the answer in hand, the moment its press takes itself to be done.
    real_wait = page.wait_for_timeout

    def wait(ms):
        real_wait(ms)
        if answered:
            late.let_through_soon(page, seconds)

    page.wait_for_timeout = wait
    out = tmp_path / "Statements" / "2026-09-30 Robinhood Statement.pdf"
    assert site._click_and_capture(page, page.locator("#pdf"), "Invented statement", out) is True
    assert out.read_bytes() == PDF
    assert late.announced == 1 and _wait_until_heard(page, heard, real_wait), "the page opened its one tab"
    assert all(p.is_closed() for p in heard), "the tab the site opened is closed, though it came late"
    assert len(page.context.pages) == 1
    # Seen inside the wait, not found after it had run out. A tab
    # announced just before the wait began was missed by a wait for the
    # next one, and the press sat out five seconds.
    assert "no tab opened" not in caplog.text


def test_a_second_answer_while_the_tab_is_waited_for_is_not_taken(statements, tmp_path):
    """The press is over once it has its answer. One that came while its tab
    was waited for replaced it, and that link was the one fetched."""
    other = "https://example.invalid/another-statement.pdf"
    page = statements.show(TWICE, statements.link, other)
    heard = _heard(page)
    out = tmp_path / "Statements" / "2026-09-30 Robinhood Statement.pdf"
    assert site._click_and_capture(page, page.locator("#pdf"), "Invented statement", out) is True
    assert out.read_bytes() == PDF
    assert _wait_until_heard(page, heard, page.wait_for_timeout), "the page opened its tab"
    assert statements.asked == [statements.link, other], "the page asked twice"
    assert all(p.is_closed() for p in heard), "the tab that came two and a half seconds on is closed"
