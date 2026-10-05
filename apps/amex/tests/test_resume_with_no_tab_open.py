"""Resume with no American Express tab of the person's open, in a real
browser.

American Express keeps its session in a token held by the tab the person
signed in with, so a new tab is not signed in and the statements page is
reached only by clicking through that tab's own menus. After a Discover,
Resume goes straight to the documents found. The app used the person's
American Express tab when one was open and otherwise the first open tab of
any site, so with theirs closed it clicked links named like American
Express's own menus, "Statements & Activity" and "Go to PDF Statements", on
whatever page that tab showed, and marked every document for manual review
with nothing asked of American Express.

Now a run with no tab of the person's on the site stops at the first
document and says that tab is not open and how to open it, with every
document left as it was for the next run, and a tab of another site is
never read or clicked. The person's own tab, when it is open, is still the
one used.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. American Express and another site are made-up host
names the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches American Express. Every statement and
date is invented. Once the run is on the statements page in the person's
tab, the press that saves a statement is stood in for, since which tab the
run works in is what is under test.
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
import amex_docs as app_mod
import amex_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

AMEX_HOST = "global.americanexpress.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (AMEX_HOST, ELSEWHERE_HOST))

DATES = ["2026-06-27", "2026-05-27"]

STATEMENTS_PAGE = """<!doctype html><html><head><title>Statements and Year End Summaries</title>
</head><body><main><h1>Statements and Year End Summaries</h1>
<h2>Recent Statements</h2>
%s
</main></body></html>""" % "".join(
    '<p>%s <button data-testid="myca-statements/recent-statements/%s/download-button">'
    'Download</button></p>' % (d, d) for d in DATES)

# A page of another site, open in the person's browser, with links named
# like American Express's own menus.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1>
<p><a href="/bait/statements-and-activity">Statements &amp; Activity</a></p>
<p><a data-testid="goToPdfLinkLg" href="/bait/go-to-pdf-statements">Go to PDF Statements</a></p>
<p>Lunch on Thursday?</p></main></body></html>"""


class FakeAmex:
    def __init__(self):
        self.reset()

    def reset(self):
        self.seen = []


SITE = FakeAmex()


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
        if host == AMEX_HOST and path == "/activity/statements":
            self._page(STATEMENTS_PAGE)
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


@pytest.fixture(autouse=True)
def fake_amex(server, monkeypatch):
    """American Express is the made-up site, its saving press is stood in
    for, and the app's waits are short."""
    SITE.reset()
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == AMEX_HOST)
    pressed = SITE.pressed = []

    def saved_from(page, category, date, out_path):
        # The row's button is on the statements page and nowhere else.
        pressed.append((page.url, date))
        where = urlsplit(page.url or "")
        if where.hostname != AMEX_HOST or where.path != "/activity/statements":
            return False
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(testkit.text_pdf(["American Express", "Statement", date]))
        return True

    monkeypatch.setattr(site, "download_document", saved_from)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
    return SITE


def seeded(tmp_path, cdp_url):
    """A config, and the documents a Discover that read every statement
    found, none of them downloaded."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for date in DATES:
        doc = app_mod.Document(title="Statement", category="Statement", summary="Statement",
                               date=date, date_text=date)
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


def bait_followed():
    return [(h, p) for h, p in SITE.seen if h == ELSEWHERE_HOST and p.startswith("/bait/")]


def test_resume_with_no_tab_of_theirs_open_stops_and_says_so(attached, server, tmp_path,
                                                             capsys):
    """The person's American Express tab is closed and another site's tab is
    the only one open. The run stops at the first document, saying the tab
    is not open and to open it with login.bat, with nothing marked and
    nothing asked of American Express. The app clicked the other site's
    look-alike links and marked every document for manual review."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})

    code = "finished"
    try:
        app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out

    assert not bait_followed(), "a link on another site's page was followed, %s" % bait_followed()
    assert not marked(tmp_path), "documents were marked %s\n%s" % (marked(tmp_path), out)
    assert code == 0, "the run %s rather than stopping\n%s" % (code, out)
    said = folded(out)
    assert "The American Express tab you signed in with is not open." in said, out
    assert "login.bat" in said, out
    assert panel_reads(out)["stopped"] == 1
    assert not marked(tmp_path) and not downloaded(tmp_path), \
        "every document is left as it was for the next run"
    assert not [s for s in SITE.seen if s[0] == AMEX_HOST], "nothing was asked of American Express"
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: address(server, ELSEWHERE_HOST, "/inbox")}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_their_tab_on_the_statements_page_is_still_the_one_used(attached, server, tmp_path,
                                                                capsys):
    """The person's American Express tab is open on the statements page,
    beside another site's tab. Every statement is asked for from their tab,
    and no tab of the run's own is opened."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    theirs_at = address(server, AMEX_HOST, "/activity/statements")
    theirs = testkit.open_tab(attached, theirs_at, "Statements and Year End Summaries")
    testkit.keep_only(attached, {elsewhere, theirs})

    assert app_mod.main(["--resume", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert downloaded(tmp_path) == keys, folded(out)
    assert [where for where, _date in SITE.pressed] == [theirs_at] * len(DATES)
    assert not bait_followed()
    assert sorted(t["id"] for t in testkit.tabs_of(attached)) == sorted([elsewhere, theirs])
