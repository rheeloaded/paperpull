"""Resume with no AAFMAA tab of the person's open, or with theirs on another
page of the site, in a real browser.

After a Discover, Resume goes straight to the documents found. The app used
the person's AAFMAA tab when one was open and otherwise the first open tab
of any site, and nothing opened the documents page first. Each document's
row is found by walking the table's pager, which starts by clicking a link
named exactly "1", so the app clicked such a link on whatever page that tab
showed, read that page's rows, found no row, and marked every document for
manual review with nothing asked of AAFMAA. The same happened in the
person's own AAFMAA tab when it was on another page of the site.

AAFMAA keeps its session in a cookie, which a new tab shares. So with no tab
of the person's on the site the documents page is opened in a tab of the
app's own, and a tab of theirs on another page of the site is sent to the
documents page before any row is looked for. A tab of another site is never
read, clicked or loaded.

A View may also post the page back and answer with the PDF itself, which
the browser shows in the tab at the documents page's own address. The tab
was judged to be on the documents page by its address alone, before each
document and after each press, so it was never put back, and each document
after it was looked for inside the PDF viewer and marked for manual review.
A tab is on the documents page only when its list is showing.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. AAFMAA and another site are made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches AAFMAA. Every title, policy, name and date is
invented.
"""
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import aafmaa_docs as app_mod
import aafmaa_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

AAFMAA_HOST = "connect.aafmaa.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (AAFMAA_HOST, ELSEWHERE_HOST))

# Each row as the table shows it, Date, Document, Policy and Name of Insured,
# with the postback target its View control names.
ROWS = [
    ("6/15/2026", "Premium Statement", "5550001-1", "Dana Example",
     "ctl00$Main$rptDocuments$ctl01$lnkViewDocument"),
    ("5/15/2026", "Premium Statement", "5550002-1", "Dana Example",
     "ctl00$Main$rptDocuments$ctl02$lnkViewDocument"),
]
PDFS = {}

ROW = """<tr><td>{date}</td><td>{title}</td><td>{policy}</td><td>{insured}</td>
<td><a class="view" data-n="{n}" href="javascript:__doPostBack('{target}','')">View in Browser</a></td>
<td><a href="javascript:__doPostBack('{copy}','')">Download a Copy</a></td><td></td></tr>"""

# A View hands its document over as a download, or with view=postback posts
# the page back, answered with the PDF itself, which the browser shows in
# the tab at this page's own address.
DOCUMENTS_PAGE = """<!doctype html><html><head><title>Documents</title></head><body>
<main><h1>My Documents</h1>
<form method="post" action="/Documents/default.aspx"><input type="hidden" name="row" id="row"></form>
<table><tr><th>Date</th><th>Document</th><th>Policy</th><th>Name of Insured</th>
<th>View in Browser</th><th>Download a Copy</th></tr>
%(rows)s
</table></main>
<script>
function __doPostBack() {}
const VIEW = '%(view)s';
for (const a of document.querySelectorAll('a.view')) {
  a.addEventListener('click', (e) => {
    e.preventDefault();
    if (VIEW === 'postback') {
      document.getElementById('row').value = a.dataset.n;
      document.forms[0].submit();
      return;
    }
    fetch('/doc/' + a.dataset.n).then(r => r.blob()).then(b => {
      const d = document.createElement('a');
      d.href = URL.createObjectURL(b);
      d.download = 'statement.pdf';
      document.body.appendChild(d);
      d.click();
    });
  });
}
</script></body></html>"""

# The landing page, with a link that reads "1", as a count beside a menu
# might, which is not the documents table's pager.
HOME_PAGE = """<!doctype html><html><head><title>Member Center</title></head><body>
<main><h1>Welcome back</h1><p>Messages <a href="/Messages/default.aspx">1</a></p>
<p>Your coverage at a glance.</p></main></body></html>"""

MESSAGES_PAGE = """<!doctype html><html><head><title>Messages</title></head><body>
<main><h1>Messages</h1></main></body></html>"""

# A page of another site, open in the person's browser, with a link that
# reads "1" as a page number of its own.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Page <a href="/bait/page-one">1</a> of 3</p>
<p>Lunch on Thursday?</p></main></body></html>"""


class FakeAafmaa:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path).
        self.seen = []
        # How a View hands its document over, "download" or "postback",
        # which the documents page takes in when it is drawn, and the row
        # each postback asked for, in order.
        self.view = "download"
        self.posted = []


SITE = FakeAafmaa()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _page(self, html):
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        parts = urlsplit(self.path)
        path = parts.path
        SITE.seen.append((host, path))
        shown = parse_qs(parts.query).get("pdf", [""])[0]
        if host == AAFMAA_HOST and path == "/Documents/default.aspx" and shown in PDFS:
            # A PDF shown at the documents page's own address, as a View a
            # person pressed in their own tab leaves it.
            self._send(PDFS[shown], "application/pdf")
        elif host == AAFMAA_HOST and path == "/Documents/default.aspx":
            rows = "".join(ROW.format(date=d, title=t, policy=p, insured=i, target=tg, n=n,
                                      copy=tg.replace("lnkViewDocument", "lnkDownloadCopy"))
                           for n, (d, t, p, i, tg) in enumerate(ROWS))
            self._page(DOCUMENTS_PAGE % {"rows": rows, "view": SITE.view})
        elif host == AAFMAA_HOST and path == "/Home/default.aspx":
            self._page(HOME_PAGE)
        elif host == AAFMAA_HOST and path == "/Messages/default.aspx":
            self._page(MESSAGES_PAGE)
        elif host == AAFMAA_HOST and path.startswith("/doc/") and path[5:] in PDFS:
            self._send(PDFS[path[5:]], "application/pdf")
        elif host == ELSEWHERE_HOST and path == "/inbox":
            self._page(ELSEWHERE_PAGE)
        elif host == ELSEWHERE_HOST:
            self._page("<!doctype html><html><head><title>Elsewhere</title></head>"
                       "<body><p>Another page</p></body></html>")
        else:
            self.send_error(404)

    def do_POST(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path
        form = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        SITE.seen.append((host, path))
        row = parse_qs(form).get("row", [""])[0]
        SITE.posted.append(row)
        if host == AAFMAA_HOST and path == "/Documents/default.aspx" and row in PDFS:
            self._send(PDFS[row], "application/pdf")
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
    """Each statement prints its own policy number, which the app checks a
    saved file for."""
    for n, (date, title, policy, insured, _target) in enumerate(ROWS):
        PDFS[str(n)] = testkit.text_pdf(["Armed Forces Mutual", title, date,
                                         "Policy %s" % policy, insured])
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


def address(server, host, path):
    return "http://%s:%d%s" % (host, server, path)


@pytest.fixture(autouse=True)
def fake_aafmaa(server, monkeypatch):
    """AAFMAA is the made-up site, and the app's waits are short."""
    SITE.reset()
    base = "http://%s:%d" % (AAFMAA_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name, path in (("home", "/"), ("login", "/"), ("home_app", "/Home/default.aspx"),
                       ("documents", "/Documents/default.aspx")):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES", [base + "/Documents/default.aspx"])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == AAFMAA_HOST)
    from playwright.sync_api import Page
    real_wait = Page.wait_for_timeout
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to finish. What it printed."""
    assert app_mod.main([*flags, "--config", str(config_for(tmp_path, cdp_url))]) == 0
    return capsys.readouterr().out


def folded(out):
    return " ".join(out.split())


def panel_reads(out):
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def progress(tmp_path):
    path = tmp_path / "out" / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def downloaded(tmp_path):
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("downloaded_ok")
                  and Path(r.get("pdf_path") or "").is_file())


def marked(tmp_path):
    """The documents marked for manual review or failed."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("state") in (
                      State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value))


def discovered(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return sorted(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else []


def discover_with_their_tab(attached, server, tmp_path, capsys):
    """A Discover with the person's documents tab open, as at home, which
    then closes. Every document is known and none is downloaded."""
    theirs = testkit.open_tab(attached, address(server, AAFMAA_HOST, "/Documents/default.aspx"),
                              "Documents")
    testkit.keep_only(attached, {theirs})
    run(tmp_path, attached, capsys, "--discover")
    assert len(discovered(tmp_path)) == len(ROWS)
    assert not downloaded(tmp_path)
    return theirs


def open_tab_at(cdp_url, address, seconds=15):
    """A tab the browser opens itself at this address, the way the person's
    own tab is opened, once the browser lists it there. Its id. A PDF it
    shows has no title of the page's own to wait for."""
    made = json.loads(urllib.request.urlopen(urllib.request.Request(
        "%s/json/new?%s" % (cdp_url, address), method="PUT"), timeout=15).read().decode("utf-8"))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(t.get("id") == made["id"] and t.get("url") == address
               for t in testkit.tabs_of(cdp_url)):
            return made["id"]
        time.sleep(0.1)
    raise AssertionError("the tab for %s never got there" % address)


def on_host(cdp_url, host):
    return [t for t in testkit.tabs_of(cdp_url) if urlsplit(t.get("url") or "").hostname == host]


def bait_followed():
    """The links that read "1" and are not the table's pager, followed."""
    return [(h, p) for h, p in SITE.seen
            if (h == ELSEWHERE_HOST and p.startswith("/bait/")) or p == "/Messages/default.aspx"]


# -- Resume with no tab of theirs on AAFMAA ----------------------------------------

def test_resume_opens_the_documents_page_in_a_tab_of_its_own(attached, server, tmp_path, capsys):
    """The person's AAFMAA tab was closed after Discover, and another site's
    tab is the only one open. Every document is downloaded from the
    documents page, opened in a tab of the app's own, and the other site's
    tab is never touched. The app clicked the other site's "1" and marked
    every document for manual review."""
    theirs = discover_with_their_tab(attached, server, tmp_path, capsys)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.close_tab(attached, theirs)
    SITE.seen.clear()

    out = run(tmp_path, attached, capsys, "--resume")

    assert not bait_followed(), "a link on another site's page was followed, %s" % bait_followed()
    assert downloaded(tmp_path) == discovered(tmp_path), folded(out)
    assert not marked(tmp_path), folded(out)
    assert panel_reads(out)["manual_review"] == 0
    still = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert still.get(elsewhere) == address(server, ELSEWHERE_HOST, "/inbox"), \
        "the other site's tab is still where it was"
    assert [urlsplit(t["url"]).path for t in on_host(attached, AAFMAA_HOST)] == \
        ["/Documents/default.aspx"], "the documents page was opened in a tab of the app's own"


def test_their_tab_on_another_page_is_sent_to_the_documents_page(attached, server, tmp_path,
                                                                 capsys):
    """The person's AAFMAA tab is open on the landing page, where a link reads
    "1". The tab is sent to the documents page before any row is looked for,
    and every document is downloaded there. The app clicked that "1" and
    looked for the rows on the messages page it led to."""
    theirs = discover_with_their_tab(attached, server, tmp_path, capsys)
    landing = testkit.open_tab(attached, address(server, AAFMAA_HOST, "/Home/default.aspx"),
                               "Member Center")
    testkit.keep_only(attached, {landing})
    assert theirs != landing
    SITE.seen.clear()

    out = run(tmp_path, attached, capsys, "--resume")

    assert not bait_followed(), "the landing page's own link was followed, %s" % bait_followed()
    assert downloaded(tmp_path) == discovered(tmp_path), folded(out)
    assert not marked(tmp_path), folded(out)
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert list(tabs) == [landing] and urlsplit(tabs[landing]).path == "/Documents/default.aspx", \
        "their tab was the one used, now on the documents page, and no other was opened"


def test_their_tab_on_the_documents_page_is_used_as_it_always_was(attached, server, tmp_path,
                                                                  capsys):
    """At home the documents page is usually still open in the tab the
    person signed in with. Resume downloads every document there and opens
    no tab of its own."""
    theirs = discover_with_their_tab(attached, server, tmp_path, capsys)
    SITE.seen.clear()

    out = run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == discovered(tmp_path), folded(out)
    assert [t["id"] for t in testkit.tabs_of(attached)] == [theirs]


# -- a document shown in the tab at the documents page's own address ---------------

def test_documents_shown_in_the_tab_are_each_found_and_downloaded(attached, server, tmp_path,
                                                                  capsys):
    """Each View posts the page back and the answer is the PDF itself, which
    the browser shows in their tab at the documents page's own address. The
    tab was put back on the documents list only when its address had left
    /Documents/, so the second document's row was looked for inside the PDF
    viewer and the document went to manual review. Every document is
    downloaded in their tab, which ends on the documents list. The page in
    their tab is drawn by Discover, so it posts back from the start."""
    SITE.view = "postback"
    theirs = discover_with_their_tab(attached, server, tmp_path, capsys)
    SITE.seen.clear()

    out = run(tmp_path, attached, capsys, "--resume")

    assert sorted(SITE.posted) == ["0", "1"], "each View posted the page back, %s" % SITE.posted
    assert downloaded(tmp_path) == discovered(tmp_path), folded(out)
    assert not marked(tmp_path), folded(out)
    tabs = testkit.tabs_of(attached)
    assert [t["id"] for t in tabs] == [theirs], "their tab was the one used, and no other opened"
    assert tabs[0].get("title") == "Documents", "their tab ends on the documents list"


def test_their_tab_showing_a_pdf_at_the_documents_address_is_sent_to_the_list(attached, server,
                                                                              tmp_path, capsys):
    """The person's AAFMAA tab is at the documents page's own address and
    shows a PDF, as a View they pressed themselves leaves it. Before each
    document the tab was judged ready by its address alone, so every row was
    looked for inside the PDF viewer and every document went to manual
    review. Their tab is sent to the documents list first, and every
    document is downloaded there."""
    theirs = discover_with_their_tab(attached, server, tmp_path, capsys)
    showing = open_tab_at(attached, address(server, AAFMAA_HOST, "/Documents/default.aspx?pdf=0"))
    testkit.keep_only(attached, {showing})
    assert showing != theirs
    SITE.seen.clear()

    out = run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == discovered(tmp_path), folded(out)
    assert not marked(tmp_path), folded(out)
    tabs = testkit.tabs_of(attached)
    assert [t["id"] for t in tabs] == [showing], "their tab was the one used, and no other opened"
    assert tabs[0].get("title") == "Documents", "their tab ends on the documents list"
