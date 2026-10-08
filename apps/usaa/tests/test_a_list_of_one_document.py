"""USAA's documents page counts as open by what it is, not by its rows,
and its list is read from USAA's own answer to the page, in a real browser.

The page counted as open only once more than one row matched a broad row
selector, so an account with a single document, or none yet, could stop
every Pilot and Run All since Discover stops when the page will not open.
The page is now known by its address and its own heading or its table's
header row, as the probe of 2026-07-24 saw them, and a page that never drew
still stops the run.

The list itself was never read from the rows. USAA's page asks its
documents API for every document once, as it loads, and pages its table in
the browser (the probe heard eight answers of a hundred for 724 documents
while the table showed eighteen months in pages of ten). The collector
listens for those answers, and it loaded the page itself until the opener
learned to keep a page already showing (70c3256a, in 0.26.0). From then on
Discover opened the page, the collector found it open and listened to a
page that asked nothing more, so every Discover listed nothing and said the
list was read. The collector now loads the page while it listens, and a
page whose list never arrives stops the run rather than count as empty.

The row fallback, for a record with no document id, loads the list afresh
for the same reason, since a PDF still showing from the last document is
what made every capture save the same file in July.

In a real browser attached over CDP, as at home. USAA is a made-up host
name the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches USAA. Every title, account and date is
invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import usaa_docs as app_mod
import usaa_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

USAA_HOST = "www.usaa.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % USAA_HOST)

API = "/v1/enterprise/my-documents/experience/individuals/example/documents"

# Every document the made-up account could hold, newest first, as the API
# lists them.
DOCS = [
    {"title": "CHECKING STATEMENT", "displayDate": "07/16/2031",
     "documentDate": "2031-07-16", "accountName": "EXAMPLE CHECKING *0001",
     "category": "Banking", "documentId": "aaaaaaaa-0000-4000-8000-000000000001"},
    {"title": "SAVINGS STATEMENT", "displayDate": "07/01/2031",
     "documentDate": "2031-07-01", "accountName": "EXAMPLE SAVINGS *0002",
     "category": "Banking", "documentId": "aaaaaaaa-0000-4000-8000-000000000002"},
    {"title": "CHECKING STATEMENT", "displayDate": "06/16/2031",
     "documentDate": "2031-06-16", "accountName": "EXAMPLE CHECKING *0001",
     "category": "Banking", "documentId": "aaaaaaaa-0000-4000-8000-000000000003"},
]
PDFS = {}

# The documents page. It asks the API for every document as it loads, then
# draws the heading, the table's header row and one row per document, ten
# to a page. Asked, it draws its heading as plain text rather than as a
# heading, or an empty account's list with no table at all. A title opens its document at the page's own address with
# ?documentId=, where the PDF shows in a blob: iframe beside the table, as
# it does at a deep link. The PDF takes a moment to arrive, as USAA's does.
DOCUMENTS_PAGE = """<!doctype html><html><head><title>My Documents | USAA</title></head>
<body><div id="root"></div>
<script>
const DRAWS = %(draws)s;
const HEADING = '%(heading)s';
const TABLE_WHEN_EMPTY = %(table_when_empty)s;
function shown(id) {
  setTimeout(() => fetch('/doc/' + id).then(r => r.blob()).then(b => {
    for (const old of document.querySelectorAll('iframe')) old.remove();
    const f = document.createElement('iframe');
    f.src = URL.createObjectURL(b);
    document.getElementById('root').appendChild(f);
  }), 400);
}
function draw(docs, failed) {
  const root = document.getElementById('root');
  const table = docs.length || TABLE_WHEN_EMPTY;
  root.innerHTML = '<main><' + HEADING + ' class="title">My Documents</' + HEADING + '>' + (failed
    ? '<p>We are unable to show your documents right now.</p>'
    : !table ? '<p>You have no documents.</p>'
    : '<table><thead><tr><th>Document title</th><th>Date delivered</th>' +
      '<th>Account</th><th>Actions</th></tr></thead><tbody></tbody></table>' +
      (docs.length ? '' : '<p>You have no documents.</p>')) + '</main>';
  if (failed || !table) return;
  const body = root.querySelector('tbody');
  docs.slice(0, 10).forEach((d, n) => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><button type="button" data-testid="readDocument-' + n + '">' +
      d.title + '</button></td><td>' + d.displayDate + '</td><td>' + d.accountName +
      '</td><td><button type="button" data-testid="actions-' + n + '">Options</button></td>';
    tr.querySelector('button').addEventListener('click', () => {
      history.pushState({}, '', '/my/documents?documentId=' + d.documentId +
                        '&documentDate=' + d.documentDate);
      shown(d.documentId);
    });
    body.appendChild(tr);
  });
  const asked = new URLSearchParams(location.search).get('documentId');
  if (asked) shown(asked);
}
if (DRAWS) {
  fetch('%(api)s?limit=100').then(r => {
    if (!r.ok) throw new Error('refused');
    return r.json();
  }).then(j => draw(j.documents, false), () => draw([], true));
}
</script></body></html>"""

# Another page of the signed-in site, with a table of rows of its own.
ACCOUNTS_PAGE = """<!doctype html><html><head><title>Accounts | USAA</title></head><body>
<main><h1>Accounts</h1><table><tbody>
<tr><td>EXAMPLE CHECKING *0001</td><td>$1.00</td></tr>
<tr><td>EXAMPLE SAVINGS *0002</td><td>$2.00</td></tr>
<tr><td>EXAMPLE CARD *0003</td><td>$3.00</td></tr>
</tbody></table></main></body></html>"""


class FakeUsaa:
    def __init__(self):
        self.reset()

    def reset(self):
        # How many of DOCS the account holds, whether the page draws at all,
        # and the status the API answers with.
        self.held = len(DOCS)
        self.draws = True
        self.api_status = 200
        # The tag the heading is drawn in, and whether an empty account's
        # list still draws its table.
        self.heading = "h1"
        self.table_when_empty = True
        # How many times the API was asked.
        self.asked = 0


SITE = FakeUsaa()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path
        if host != USAA_HOST:
            self.send_error(404)
        elif path == "/my/documents":
            page = DOCUMENTS_PAGE % {"draws": "true" if SITE.draws else "false", "api": API,
                                     "heading": SITE.heading,
                                     "table_when_empty": "true" if SITE.table_when_empty
                                     else "false"}
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/my/accounts":
            self._send(ACCOUNTS_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == API:
            SITE.asked += 1
            if SITE.api_status != 200:
                self._send(b'{"error":"unavailable"}', "application/json", SITE.api_status)
                return
            body = json.dumps({"documents": DOCS[:SITE.held]}).encode("utf-8")
            self._send(body, "application/json")
        elif path.startswith("/doc/") and path[5:] in PDFS:
            self._send(PDFS[path[5:]], "application/pdf")
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


@pytest.fixture(scope="module", autouse=True)
def statements():
    """Each statement prints its own title, account and date."""
    for d in DOCS:
        PDFS[d["documentId"]] = testkit.text_pdf(
            ["USAA", d["title"], d["accountName"], d["displayDate"]])
    return PDFS


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def address(server, path):
    return "http://%s:%d%s" % (USAA_HOST, server, path)


@pytest.fixture(autouse=True)
def made_up_usaa(server, monkeypatch):
    """USAA is the made-up site, and the app's waits are short."""
    SITE.reset()

    def made_up(url):
        parts = urlsplit(url)
        return urlunsplit(("http", "%s:%d" % (USAA_HOST, server), parts.path, parts.query,
                           parts.fragment))

    monkeypatch.setattr(site, "BASE", "http://%s:%d" % (USAA_HOST, server))
    for name, url in list(site.URLS.items()):
        monkeypatch.setitem(site.URLS, name, made_up(url))
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES",
                        [made_up(url) for url in site.DOCUMENT_URL_CANDIDATES])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == USAA_HOST)
    monkeypatch.setattr(site, "ANSWER_WAIT_S", 5, raising=False)
    monkeypatch.setattr(site, "DRAW_WAIT_S", 3, raising=False)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 300)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 3000)}))
    return SITE


@pytest.fixture
def tab(attached, server):
    """A tab in the browser the app attaches to."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(attached)
    page = browser.contexts[0].new_page()
    yield page
    page.close()
    pw.stop()


def drawn(tab, server, path="/my/documents"):
    tab.goto(address(server, path))
    if SITE.draws and path.startswith("/my/documents"):
        tab.wait_for_function("document.querySelector('.title') !== null", timeout=10000)


# -- what counts as the documents page -----------------------------------

@pytest.mark.parametrize("held", [0, 1, 3], ids=["no document", "one document", "three"])
def test_the_page_counts_as_open_whatever_it_holds(tab, server, held):
    SITE.held = held
    drawn(tab, server)
    assert tab.locator("table tbody tr").count() == held
    assert site.documents_page_drawn(tab)
    before = tab.url
    assert site.goto_documents(tab) and tab.url == before


def test_an_empty_account_with_no_table_counts_by_its_heading(tab, server):
    SITE.held, SITE.table_when_empty = 0, False
    drawn(tab, server)
    assert tab.locator("table").count() == 0
    assert site.documents_page_drawn(tab)


@pytest.mark.parametrize("held", [0, 1], ids=["no document", "one document"])
def test_a_heading_drawn_as_plain_text_counts_by_the_header_row(tab, server, held):
    SITE.held, SITE.heading = held, "div"
    drawn(tab, server)
    assert tab.get_by_role("heading").count() == 0
    assert site.documents_page_drawn(tab)


def test_a_page_that_never_drew_does_not_count(tab, server):
    SITE.draws = False
    drawn(tab, server)
    assert tab.title() == "My Documents | USAA"
    assert not site.documents_page_drawn(tab)
    assert not site.goto_documents(tab)


def test_another_page_with_rows_does_not_count(tab, server):
    drawn(tab, server, "/my/accounts")
    assert tab.locator("table tbody tr").count() == 3
    assert not site.documents_page_drawn(tab)


# -- Discover, driven through main ----------------------------------------

def run_discover(tmp_path, attached, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": attached,
        "document_types": ["Statement", "Tax Document", "Insurance Document"],
        "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    capsys.readouterr()
    try:
        ended = ("returned", app_mod.main(["--config", str(cfg), "--discover"]))
    except SystemExit as e:
        ended = ("exit", e.code)
    said = " ".join(capsys.readouterr().out.split())
    noted = tmp_path / "out" / "last-listing.json"
    whole = json.loads(noted.read_text(encoding="utf-8"))["complete"]
    found = tmp_path / "out" / "discovery.json"
    listed = json.loads(found.read_text(encoding="utf-8")) if found.exists() else {}
    return ended, said, whole, sorted(r.get("document_id") for r in listed.values())


def their_tab(attached, server, path, title):
    """The person's USAA tab on this page, the only tab open."""
    theirs = testkit.open_tab(attached, address(server, path), title)
    testkit.keep_only(attached, {theirs})


@pytest.mark.parametrize("held", [0, 1, 3], ids=["no document", "one document", "three"])
@pytest.mark.parametrize("path, title", [
    ("/my/documents", "My Documents | USAA"),
    ("/my/accounts", "Accounts | USAA"),
], ids=["their tab on the documents", "their tab elsewhere"])
def test_discover_lists_every_document_the_page_was_given(server, attached, tmp_path, capsys,
                                                          held, path, title):
    SITE.held = held
    their_tab(attached, server, path, title)
    ended, said, whole, listed = run_discover(tmp_path, attached, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert "Could not open your USAA documents" not in said, said[-1500:]
    assert listed == sorted(d["documentId"] for d in DOCS[:held]), said[-1500:]


def test_discover_stops_on_a_page_that_never_drew(server, attached, tmp_path, capsys):
    SITE.draws = False
    their_tab(attached, server, "/my/accounts", "Accounts | USAA")
    ended, said, whole, listed = run_discover(tmp_path, attached, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "Could not open your USAA documents" in said, said[-1500:]
    assert listed == []


def test_discover_stops_when_the_list_never_arrives(server, attached, tmp_path, capsys):
    """The page draws its heading and says it cannot show the documents,
    so no list was read, and the run says so rather than call it empty."""
    SITE.api_status = 503
    their_tab(attached, server, "/my/accounts", "Accounts | USAA")
    ended, said, whole, listed = run_discover(tmp_path, attached, capsys)
    assert SITE.asked >= 1
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert listed == []


# -- the row fallback ------------------------------------------------------

def test_the_row_fallback_never_saves_the_document_still_showing(tab, server, tmp_path):
    """A record with no document id is downloaded by pressing its title.
    With the last document's PDF still showing beside the table, the press
    has to be on a list loaded afresh, or the capture takes that PDF."""
    first, other = DOCS[0], DOCS[2]
    tab.goto(address(server, "/my/documents?documentId=%s&documentDate=%s"
                     % (first["documentId"], first["documentDate"])))
    tab.wait_for_selector("iframe[src^='blob:']", timeout=10000)
    out = tmp_path / "statement.pdf"
    assert site.download_document_row(tab, other["title"], other["displayDate"],
                                      other["accountName"], out)
    assert out.read_bytes() == PDFS[other["documentId"]]
