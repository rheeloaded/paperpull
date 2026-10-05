"""Resume with no TSP tab of the person's open, in a real browser.

TSP keeps its session in the tab the person signed in with. My Account
answers a call only when it carries two values that its page keeps in the
tab's own sessionStorage, so a new tab is not signed in. After a Discover,
Resume goes straight to the documents found. The app used the person's TSP
tab when one was open and otherwise the first open tab of any site, so with
theirs closed it read that other site's page, its title and text for a
security check and its fields for a password, then loaded that tab away to
the mailbox page of My Account and asked the mailbox from there for its
messages, with neither of the session's values. My Account answered 401, as
it does any call without them, and the run said the person's session had
expired and told them to sign in again and list their statements again.

Now a run with no tab of the person's on the site stops at the first
document and says that tab is not open and how to open it, with every
document left as it was for the next run, and a tab of another site is
never read or loaded. The person's own tab, when it is open, is still the
one used.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. My Account and another site are made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches TSP. The made-up mailbox answers a call only
when it carries the two values a signed-in tab keeps, and 401 otherwise, as
My Account answers cookies alone. Every subject, id, value and date is
invented.
"""
import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import tsp_docs as app_mod
import tsp_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

TSP_HOST = "api.rk.tsp.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (TSP_HOST, ELSEWHERE_HOST))

# My Account's made-up pages, the one the person signs in on and the mailbox
# page it then shows, and the made-up mailbox the app calls.
WELCOME = "/my-account/welcome"
MAILBOX = "/my-account/mailbox"
API = "/api/mailbox"

# The two values a signed-in tab of My Account keeps in its own
# sessionStorage, which every call to the mailbox carries as headers.
SESSION_TOKEN = "invented-session-token"
REQUEST_HEADER = "invented-request-header"

# Each message as the mailbox lists it, with its id in the shape the app
# checks for, its client id, its subject, the date the mailbox gives it, and
# that date as the app keeps it.
MESSAGES = [
    ("a1b2c3d4e5f6a7b8c9d0e1f2", "4321", "Quarterly Statement", "Jul 1, 2026", "2026-07-01"),
    ("a1b2c3d4e5f6a7b8c9d0e1f3", "4321", "Quarterly Statement", "Apr 1, 2026", "2026-04-01"),
]
# Each statement prints its own date, which the app checks a saved file for.
PDFS = {item_id: testkit.text_pdf([subject, "Statement date " + listed,
                                   "Every figure here is invented"])
        for item_id, _client, subject, listed, _date in MESSAGES}

# Where the person signs in, in the tab they keep open. It leaves the two
# values in that tab's own sessionStorage and moves on to the mailbox page.
WELCOME_PAGE = """<!doctype html><html><head><title>Welcome</title></head><body>
<script>
sessionStorage.setItem('alightPersonSessionToken', '%s');
sessionStorage.setItem('alightRequestHeader', '%s');
location.replace('%s');
</script></body></html>""" % (SESSION_TOKEN, REQUEST_HEADER, MAILBOX)

MAILBOX_PAGE = """<!doctype html><html><head><title>My Account</title></head><body>
<main><h1>My Account</h1><p>Mailbox</p></main></body></html>"""

# A page of another site, open in the person's browser.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main></body></html>"""

# Page's own ways of reading what a page shows, or of acting in it.
READING = ("title", "content", "evaluate", "locator", "inner_text", "text_content",
           "query_selector", "query_selector_all", "get_by_role", "get_by_text", "click")


class FakeTsp:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path, what the mailbox was asked for, the
        # address of the page that asked, and whether it carried the session).
        self.seen = []
        # What was read of a page while it was on the other site, as (how, where).
        self.read = []


SITE = FakeTsp()


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

    def _json(self, value, status=200):
        self._send(json.dumps(value).encode("utf-8"), "application/json", status)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        asked = (query.get("subcategory") or [""])[0]
        signed = (self.headers.get("alightpersonsessiontoken") == SESSION_TOKEN
                  and self.headers.get("alightrequestheader") == REQUEST_HEADER)
        SITE.seen.append((host, path, asked, self.headers.get("Referer") or "", signed))
        item = (query.get("itemId") or [""])[0]
        if host == TSP_HOST and path == WELCOME:
            self._page(WELCOME_PAGE)
        elif host == TSP_HOST and path == MAILBOX:
            self._page(MAILBOX_PAGE)
        elif host == TSP_HOST and path == API and not signed:
            self._json({}, 401)
        elif host == TSP_HOST and path == API and asked == "items":
            self._json({"spm": {"unfilteredMsgCount": len(MESSAGES), "items": [
                {"mailboxItemId": i, "clientId": c, "mailItemSubject": s,
                 "deletionDate": listed, "mimeType": "application/pdf", "unread": True}
                for i, c, s, listed, _date in MESSAGES]}})
        elif host == TSP_HOST and path == API and asked == "itemContent" and item in PDFS:
            self._json({"spm": {"itemContent": {
                "mimetype": "application/pdf",
                "pdfContent": base64.b64encode(PDFS[item]).decode("ascii")}}})
        elif host == ELSEWHERE_HOST and path == "/inbox":
            self._page(ELSEWHERE_PAGE)
        elif host == ELSEWHERE_HOST:
            self._page("<!doctype html><html><head><title>Elsewhere</title></head>"
                       "<body><p>Another page</p></body></html>")
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


def noted(name, real):
    """Page's own `name`, noting each call made while the page is on the
    other site, and where it was."""
    def noting(self, *args, **kwargs):
        if urlsplit(self.url or "").hostname == ELSEWHERE_HOST:
            SITE.read.append((name, self.url))
        return real(self, *args, **kwargs)
    return noting


@pytest.fixture(autouse=True)
def fake_tsp(server, monkeypatch):
    """My Account is the made-up site, what is read of a page while it is on
    the other site is noted, and the app's waits are short."""
    SITE.reset()
    base = "http://%s:%d" % (TSP_HOST, server)
    monkeypatch.setattr(site, "MYACCOUNT", base)
    monkeypatch.setattr(site, "API_BASE", base + API)
    for name, path in (("home", "/"), ("login", "/"), ("documents", MAILBOX)):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == TSP_HOST)

    def on_my_account(page):
        # The app's own test of a My Account page, which names the real
        # host, with the made-up host in its place.
        try:
            url = page.url or ""
            return (site.is_safe_url(url) and urlsplit(url).hostname == TSP_HOST
                    and not site.looks_signed_out(page))
        except Exception:
            return False

    monkeypatch.setattr(site, "on_documents_page", on_my_account)
    # The call made inside the page refuses any address but My Account's
    # own https host before it is sent. Here that host is the made-up one,
    # served over http.
    fetch = site._FETCH_JS.replace("'https:'", "'http:'").replace(
        "'api.rk.tsp.gov'", "'%s'" % TSP_HOST)
    assert "'http:'" in fetch and "'%s'" % TSP_HOST in fetch and "tsp.gov" not in fetch, \
        "the page's own check of the address is no longer where this test looks for it"
    monkeypatch.setattr(site, "_FETCH_JS", fetch)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
    for name in READING:
        monkeypatch.setattr(Page, name, noted(name, getattr(Page, name)))
    return SITE


def seeded(tmp_path, cdp_url):
    """A config, and the documents a Discover that read the whole mailbox
    found, none of them downloaded."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for item_id, client_id, subject, _listed, date in MESSAGES:
        doc = app_mod.Document(title=subject, category="Statement", summary=subject,
                               date=date, date_text=date, item_id=item_id,
                               client_id=client_id)
        records[doc.key] = dict(doc.to_dict(), state=State.DISCOVERED.value)
    (out / "discovery.json").write_text(json.dumps(records), encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg, sorted(records)


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
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("state") in (
                      State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value))


def asked_of_tsp():
    """Every request made of My Account, as (path, what the mailbox was
    asked for)."""
    return [(path, asked) for host, path, asked, _referer, _signed in SITE.seen
            if host == TSP_HOST]


def mailbox_calls():
    """Each call to the mailbox, as the address of the page that made it and
    whether it carried the person's session."""
    return [(referer, signed) for host, path, _asked, referer, signed in SITE.seen
            if host == TSP_HOST and path == API]


def test_resume_with_no_tab_of_theirs_open_stops_and_says_so(attached, server, tmp_path,
                                                             capsys):
    """The person's TSP tab is closed and another site's tab is the only one
    open. The run stops at the first document, saying the tab is not open
    and to open it with login.bat, with nothing marked, nothing asked of
    TSP, and the other site's tab never read or loaded. The app read that
    tab, loaded it away to My Account, asked the mailbox from it with no
    session, and said the person's session had expired."""
    cfg, keys = seeded(tmp_path, attached)
    inbox = address(server, ELSEWHERE_HOST, "/inbox")
    elsewhere = testkit.open_tab(attached, inbox, "Inbox")
    testkit.keep_only(attached, {elsewhere})

    try:
        code = "finished with %r" % app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out

    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs.get(elsewhere) == inbox, "the other site's tab was loaded somewhere else\n" + out
    assert not SITE.read, "the other site's page was read, %s" % SITE.read
    assert not marked(tmp_path), "documents were marked %s\n%s" % (marked(tmp_path), out)
    assert code == 0, "the run %s rather than stopping\n%s" % (code, out)
    said = folded(out)
    assert "The TSP tab you signed in with is not open." in said, out
    assert "login.bat" in said, out
    assert "session has expired" not in said, "the person was never signed out\n" + out
    assert panel_reads(out)["stopped"] == 1
    assert not marked(tmp_path) and not downloaded(tmp_path), \
        "every document is left as it was for the next run"
    assert not asked_of_tsp(), "nothing was asked of TSP, %s" % asked_of_tsp()
    assert tabs == {elsewhere: inbox}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_their_tab_on_my_account_is_still_the_one_used(attached, server, tmp_path, capsys):
    """The person's TSP tab is open on My Account, signed in, beside another
    site's tab. Every document is asked for from their tab, with the session
    it keeps, and no tab of the run's own is opened."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    theirs = testkit.open_tab(attached, address(server, TSP_HOST, WELCOME), "My Account")
    testkit.keep_only(attached, {elsewhere, theirs})
    theirs_at = address(server, TSP_HOST, MAILBOX)
    SITE.seen.clear()

    assert app_mod.main(["--resume", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert downloaded(tmp_path) == keys, folded(out)
    assert set(mailbox_calls()) == {(theirs_at, True)}, \
        "every call to the mailbox came from their tab, with the session it keeps"
    assert not SITE.read
    assert sorted(t["id"] for t in testkit.tabs_of(attached)) == sorted([elsewhere, theirs])
