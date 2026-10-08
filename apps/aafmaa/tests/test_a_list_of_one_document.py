"""AAFMAA's documents page counts as open by what it is, not by its rows,
in a real browser.

The page counted as open only once more than one row matched a broad row
selector, and Discover stops when the page will not open. The live page of
2026-08-21 drew three membership letters and the table's header row among
those rows, so an account with one document or none passed while they were
there. A member shown no letters, with no document yet, stopped every Pilot
and Run All, and anything that changed those rows decided it. The page is
now known by its address and by the documents table's header row (Date,
Document, Policy) or the MY DOCUMENTS section control, both as the live
page drew them. A page that never drew, or a PDF shown at the page's own
address, still does not count, and Discover stops there.

In a real browser attached over CDP, as at home. AAFMAA is a made-up host
name the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches AAFMAA. Every title, policy, name and
date is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import aafmaa_docs as app_mod
import aafmaa_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

AAFMAA_HOST = "connect.aafmaa.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % AAFMAA_HOST)

ROWS = [
    ("6/15/2031", "Premium Statement", "5550001-1", "Dana Example",
     "ctl00$Main$rptDocuments$ctl01$lnkViewDocument"),
    ("6/15/2031", "Premium Statement", "5550002-1", "Lee Example",
     "ctl00$Main$rptDocuments$ctl02$lnkViewDocument"),
]

# The membership letters every member was shown above their own documents,
# each a View of a file under /Resources/PDFFiles/.
LETTERS = """<table>
<tr><td></td><td>Letter from the President</td><td><a href="/Resources/PDFFiles/Letter.pdf">View</a></td></tr>
<tr><td></td><td>Privacy Policy</td><td><a href="/Resources/PDFFiles/Privacy.pdf">View</a></td></tr>
<tr><td></td><td>Membership Benefits</td><td><a href="/Resources/PDFFiles/Benefits.pdf">View</a></td></tr>
</table>"""

# The section controls, each a postback of this one page.
SECTIONS = """<p><a href="javascript:__doPostBack('ctl00$Main$lnkMyDocuments','')">MY DOCUMENTS</a>
<a href="javascript:__doPostBack('ctl00$Main$lnkInsurance','')">Insurance Documents</a>
<a href="javascript:__doPostBack('ctl00$Main$lnkVault','')">Digital Vault</a></p>"""

HEADER = """<tr><th>Date</th><th>Document</th><th>Policy</th><th>Name of Insured</th>
<th>View in Browser</th><th>Download a Copy</th></tr>"""

ROW = """<tr><td>{date}</td><td>{title}</td><td>{policy}</td><td>{insured}</td>
<td><a href="javascript:__doPostBack('{target}','')">View in Browser</a></td>
<td><a href="javascript:__doPostBack('{copy}','')">Download a Copy</a></td><td></td></tr>"""

PAGE = """<!doctype html><html><head><title>Member Center</title></head><body>
<form method="post" action="/Documents/default.aspx"><main>%s</main></form>
<script>function __doPostBack() {}</script></body></html>"""


class FakeAafmaa:
    def __init__(self):
        self.reset()

    def reset(self):
        # How many of ROWS the account holds, whether the member is shown
        # the membership letters and the section controls, whether an empty
        # list still draws its header row, and whether the page draws at all.
        self.held = len(ROWS)
        self.letters = True
        self.sections = True
        self.header_when_empty = True
        self.draws = True


SITE = FakeAafmaa()


def documents_page():
    if not SITE.draws:
        return PAGE % ""
    rows = "".join(ROW.format(date=d, title=t, policy=p, insured=i, target=tg,
                              copy=tg.replace("lnkViewDocument", "lnkDownloadCopy"))
                   for d, t, p, i, tg in ROWS[:SITE.held])
    table = ("<table>%s%s</table>" % (HEADER, rows)
             if SITE.held or SITE.header_when_empty else "<p>No documents found.</p>")
    return PAGE % ((SECTIONS if SITE.sections else "") + (LETTERS if SITE.letters else "")
                   + table)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path
        if host == AAFMAA_HOST and path == "/Documents/default.aspx":
            data = documents_page().encode("utf-8")
        elif host == AAFMAA_HOST and path == "/Home/default.aspx":
            data = (PAGE % "<h1>Welcome back</h1><p>Your coverage at a glance.</p>").encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
    return "http://%s:%d%s" % (AAFMAA_HOST, server, path)


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
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
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


# The pages an account's documents page may draw, each a set of SITE fields.
ACCOUNTS = {
    "two documents": {},
    "one document": {"held": 1},
    "one document, no letters": {"held": 1, "letters": False},
    "no document": {"held": 0},
    "no document, no letters": {"held": 0, "letters": False},
    "no document, no letters or sections": {"held": 0, "letters": False, "sections": False},
    "no document, no letters or header": {"held": 0, "letters": False,
                                          "header_when_empty": False},
}


def account(name):
    for field, value in ACCOUNTS[name].items():
        setattr(SITE, field, value)


# -- what counts as the documents page -----------------------------------

@pytest.mark.parametrize("name", list(ACCOUNTS))
def test_the_page_counts_as_open_whatever_it_holds(tab, server, name):
    account(name)
    tab.goto(address(server, "/Documents/default.aspx"))
    assert len(site.collect_document_index(tab)) == SITE.held
    assert site.showing_documents_list(tab)
    before = tab.url
    assert site.goto_documents(tab) and tab.url == before


def test_a_page_that_never_drew_does_not_count(tab, server):
    SITE.draws = False
    tab.goto(address(server, "/Documents/default.aspx"))
    assert tab.title() == "Member Center"
    assert not site.showing_documents_list(tab)
    assert not site.goto_documents(tab)


def test_the_same_table_on_another_page_does_not_count(tab, server):
    """Another page of the site, with the same table, is not the documents
    page, whatever it holds."""
    tab.goto(address(server, "/Home/default.aspx"))
    tab.set_content(documents_page())
    assert not site.on_documents_page(tab)
    assert not site.showing_documents_list(tab)


# -- Discover, driven through main ----------------------------------------

def run_discover(tmp_path, attached, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": attached,
        "document_types": ["Statement", "Insurance Document", "Tax Document"],
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
    return ended, said, whole, len(listed)


def their_tab(attached, server, path):
    """The person's AAFMAA tab on this page, the only tab open."""
    theirs = testkit.open_tab(attached, address(server, path), "Member Center")
    testkit.keep_only(attached, {theirs})


@pytest.mark.parametrize("name", list(ACCOUNTS))
def test_discover_reads_the_list_whatever_it_holds(server, attached, tmp_path, capsys, name):
    account(name)
    their_tab(attached, server, "/Home/default.aspx")
    ended, said, whole, listed = run_discover(tmp_path, attached, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert "Could not open your Armed Forces Mutual documents" not in said, said[-1500:]
    assert listed == SITE.held, said[-1500:]


def test_discover_stops_on_a_page_that_never_drew(server, attached, tmp_path, capsys):
    SITE.draws = False
    their_tab(attached, server, "/Home/default.aspx")
    ended, said, whole, listed = run_discover(tmp_path, attached, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "Could not open your Armed Forces Mutual documents" in said, said[-1500:]
    assert listed == 0
