"""Resume with no DFAS myPay tab of the person's open, in a real browser.

DFAS myPay keeps its session in the tab the person signed in with, which
holds the token every document request carries, so a new tab is not signed
in. After a Discover, Resume goes straight to the documents found. The app
used the person's myPay tab when one was open and otherwise the first open
tab of any site, so with theirs closed it read whatever page that tab
showed, looking there for a sign-in or a security check. Then it refused to
ask for the document from a tab that was not on myPay and said myPay had
returned a sign-in page and the session had expired, though nothing had
been asked of myPay, and the result the panel reads said the run had not
stopped.

Now a run with no tab of the person's on the site stops at the first
document and says that tab is not open and how to open it, with every
document left as it was for the next run, and a tab of another site is
never read. The person's own tab, when it is open, is still the one used.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. DFAS myPay and another site are made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches DFAS myPay. Every document and date is
invented. With the person's tab open, the request that saves a document is
stood in for, since which tab the run works in is what is under test.
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
import mypay_docs as app_mod
import mypay_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

MYPAY_HOST = "mypay.dfas.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (MYPAY_HOST, ELSEWHERE_HOST))

DATES = ["2026-06-15", "2026-05-15"]
# Each document as discovery names it, by the app's own number for a
# statement and the document's date.
DOC_IDS = ["21|%s" % d for d in DATES]

# The page the person's own tab is on, made up.
MYPAY_PAGE = """<!doctype html><html><head><title>Documents</title></head><body>
<main><h1>Documents</h1></main></body></html>"""

# A page of another site, open in the person's browser.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main></body></html>"""


class FakeMyPay:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path).
        self.seen = []
        # Every look the app took at what a page shows, as the address of
        # the tab it looked at.
        self.read = []


SITE = FakeMyPay()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _page(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path
        SITE.seen.append((host, path))
        if host == MYPAY_HOST and path == "/":
            self._page(MYPAY_PAGE)
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


def on_mypay(url):
    """Whether an address is on the made-up site. The app's own checks want
    https on DFAS myPay's real host, and this site is plain http on a
    made-up one."""
    return urlsplit(url or "").hostname == MYPAY_HOST


def noting(look):
    """One of the app's looks at a page, which notes the tab it looked at
    and then looks as it always did."""
    def noted(page, *args, **kwargs):
        SITE.read.append(page.url)
        return look(page, *args, **kwargs)
    return noted


@pytest.fixture(autouse=True)
def fake_mypay(server, monkeypatch):
    """DFAS myPay is the made-up site, every look the app takes at a page's
    title, words and fields is noted, and the app's waits are short."""
    SITE.reset()
    base = "http://%s:%d" % (MYPAY_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name in ("home", "login"):
        monkeypatch.setitem(site.URLS, name, base + "/")
    # is_mypay_frame_page asks is_safe_url, so it answers for the made-up
    # site too.
    monkeypatch.setattr(site, "is_safe_url", on_mypay)
    monkeypatch.setattr(site, "is_mypay_frame", lambda frame: on_mypay(frame.url))
    for name in ("detect_security_challenge", "looks_signed_out"):
        monkeypatch.setattr(site, name, noting(getattr(site, name)))
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
    return SITE


@pytest.fixture
def asked_for(monkeypatch):
    """The request that saves a document, stood in for. myPay answers it only
    from inside a tab on its own site, which holds the session, so the
    document is saved only when it is asked for from one. Each ask, as the
    address of the tab that asked and the document asked for."""
    asked = []

    def download_document(page, doc_id, out_path):
        asked.append((page.url, doc_id))
        if not on_mypay(page.url):
            return False
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(testkit.text_pdf(["Statement", doc_id]))
        return True

    monkeypatch.setattr(site, "download_document", download_document)
    return asked


def seeded(tmp_path, cdp_url):
    """A config, and the documents a Discover that read every statement
    found, none of them downloaded."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for doc_id, date in zip(DOC_IDS, DATES):
        assert site.parse_doc_id(doc_id), "the app takes %s as a document's identity" % doc_id
        doc = app_mod.Document(title="Statement", category="Statement", summary="Statement",
                               date=date, date_text=date, document_id=doc_id)
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


def read_elsewhere():
    """The looks the app took at another site's page."""
    return [url for url in SITE.read if urlsplit(url or "").hostname == ELSEWHERE_HOST]


def test_resume_with_no_tab_of_theirs_open_stops_and_says_so(attached, server, tmp_path,
                                                             capsys):
    """The person's DFAS myPay tab is closed and another site's tab is the
    only one open. The run stops at the first document, saying the tab is
    not open and to open it with login.bat, with nothing marked, nothing
    asked of DFAS myPay and the other site's page never read. The app read
    that page, then said myPay had returned a sign-in page and the session
    had expired, and the panel was told the run had not stopped."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})

    try:
        ended = "returned %s" % (app_mod.main(["--resume", "--config", str(cfg)]),)
    except SystemExit as stopped:
        ended = "stopped with code %s" % (stopped.code,)
    out = capsys.readouterr().out

    assert not marked(tmp_path), "documents were marked %s\n%s" % (marked(tmp_path), out)
    assert ended == "stopped with code 0", "the run %s\n%s" % (ended, out)
    said = folded(out)
    assert "The DFAS myPay tab you signed in with is not open." in said, out
    assert "login.bat" in said, out
    assert panel_reads(out)["stopped"] == 1
    assert not marked(tmp_path) and not downloaded(tmp_path), \
        "every document is left as it was for the next run"
    assert not [s for s in SITE.seen if s[0] == MYPAY_HOST], "nothing was asked of DFAS myPay"
    assert not read_elsewhere(), "the app read another site's page at %s" % read_elsewhere()
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: address(server, ELSEWHERE_HOST, "/inbox")}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_their_mypay_tab_is_still_the_one_used(attached, server, tmp_path, capsys, asked_for):
    """The person's DFAS myPay tab is open beside another site's tab. Every
    document is asked for from their tab, and no tab of the run's own is
    opened."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    theirs_at = address(server, MYPAY_HOST, "/")
    theirs = testkit.open_tab(attached, theirs_at, "Documents")
    testkit.keep_only(attached, {elsewhere, theirs})

    assert app_mod.main(["--resume", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert downloaded(tmp_path) == keys, folded(out)
    assert asked_for == [(theirs_at, doc_id) for doc_id in DOC_IDS]
    assert not read_elsewhere()
    assert sorted(t["id"] for t in testkit.tabs_of(attached)) == sorted([elsewhere, theirs])
