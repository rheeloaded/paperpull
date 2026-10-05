"""Resume with no Chase tab of the person's open, in a real browser.

Chase keeps its session in the tab the person signed in with, so a new tab
is not signed in, and the statements are reached by pressing the
dashboard's own documents menu in that tab. After a Discover, Resume goes
straight to the documents found. The app used the person's Chase tab when
one was open and otherwise the first open tab of any site, so with theirs
closed it pressed a button named "Documents" and a link named "Statements",
names it looks for in Chase's own menu, on whatever page that tab showed.
Then it loaded Chase's own addresses in that same tab, found no statements
at any of them, and marked every document for manual review.

Now a run with no tab of the person's on the site stops at the first
document and says that tab is not open and how to open it, with every
document left as it was for the next run, and a tab of another site is
never read, pressed or loaded. The person's own tab, when it is open, is
still the one used.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Chase and another site are made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches Chase. Chase's dashboard is one page that draws
whatever its route after # names, and only the route the live probe found
the statements at draws them. Every card, statement and date is invented.
Once the run is on the statements page in the person's tab, the press that
saves a statement is stood in for, since which tab the run works in is what
is under test.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import chase_docs as app_mod
import chase_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

CHASE_HOST = "secure.chase.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (CHASE_HOST, ELSEWHERE_HOST))

# Chase's dashboard, and the route after # the live probe found the
# statements at. Every other route draws the dashboard's front page, and
# every address the app tries for itself is another route.
DASHBOARD = "/web/auth/dashboard"
STATEMENTS_ROUTE = "#/dashboard/documents/myDocs/index"

ACCOUNT = "EXAMPLE CARD (...0001)"
# Each statement's date, and that date as its row writes it.
STATEMENTS = [("2026-06-15", "Jun 15, 2026"), ("2026-05-15", "May 15, 2026")]
DATES = [date for date, _written in STATEMENTS]

ROW = ('<li class="statement">{written} Statement {account} <a href="#" '
       'aria-label="{written} Statement {account} Saves document">Saves document</a></li>')

# The statements page has the year picker, already on the statements' year,
# the card's accordion, and a row for each statement named in full, as Chase
# names them.
DASHBOARD_PAGE = """<!doctype html><html><head><title>Chase</title></head><body>
<main id="view"></main>
<template id="statements"><h1>Statements &amp; documents</h1>
<p><input id="filterstyledselect-year" value="2026" readonly></p>
<button type="button" aria-expanded="false">%s</button>
<ul>%s</ul></template>
<template id="front"><h1>Accounts</h1><p>Your accounts at a glance.</p></template>
<script>
function route() {
  const statements = location.hash === '%s';
  document.title = statements ? 'Statements & documents' : 'Accounts';
  const drawn = document.getElementById(statements ? 'statements' : 'front');
  document.getElementById('view').replaceChildren(drawn.content.cloneNode(true));
}
addEventListener('hashchange', route);
route();
</script></body></html>""" % (
    ACCOUNT, "".join(ROW.format(written=w, account=ACCOUNT) for _d, w in STATEMENTS),
    STATEMENTS_ROUTE)

# A page of another site, open in the person's browser, with a button named
# like Chase's documents menu and a link named like the submenu link the app
# presses after it. The button asks this site for an address of its own when
# pressed, so a press is seen as well as a link followed.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<nav><button type="button" id="documents">Documents</button>
<a href="/bait/statements">Statements</a></nav>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main>
<script>
document.getElementById('documents').addEventListener('click', () => fetch('/bait/documents'));
</script></body></html>"""


class FakeChase:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path).
        self.seen = []
        # Each press, as the address of the tab that asked and the date.
        self.pressed = []


SITE = FakeChase()


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
        if host == CHASE_HOST and path == DASHBOARD:
            self._page(DASHBOARD_PAGE)
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
def fake_chase(server, monkeypatch):
    """Chase is the made-up site, its saving press is stood in for, and the
    app's waits are short."""
    SITE.reset()

    def made_up(url):
        """The same address and route, on the made-up Chase."""
        parts = urlsplit(url)
        return urlunsplit(("http", "%s:%d" % (CHASE_HOST, server), parts.path, parts.query,
                           parts.fragment))

    for name, url in list(site.URLS.items()):
        monkeypatch.setitem(site.URLS, name, made_up(url))
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES",
                        [made_up(url) for url in site.DOCUMENT_URL_CANDIDATES])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == CHASE_HOST)

    def saved_from(page, ctx, account, date, out_path):
        # The row's link is on the statements page and nowhere else.
        SITE.pressed.append((page.url, date))
        where = urlsplit(page.url or "")
        if where.hostname != CHASE_HOST or where.path != DASHBOARD \
                or "#" + where.fragment != STATEMENTS_ROUTE:
            return False
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(testkit.text_pdf(["Chase", "Statement", account, date]))
        return True

    monkeypatch.setattr(site, "_click_row_and_capture", saved_from)
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
        doc = app_mod.Document(title="Statement", category="Statement",
                               summary="Statement - " + ACCOUNT, date=date, date_text=date,
                               account=ACCOUNT)
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
    """The other site's look-alike button pressed and its link followed."""
    return [(h, p) for h, p in SITE.seen if h == ELSEWHERE_HOST and p.startswith("/bait/")]


def test_resume_with_no_tab_of_theirs_open_stops_and_says_so(attached, server, tmp_path,
                                                             capsys):
    """The person's Chase tab is closed and another site's tab is the only
    one open. The run stops at the first document, saying the tab is not
    open and to open it with login.bat, with nothing marked and nothing
    asked of Chase. The app pressed the other site's look-alike button and
    followed its look-alike link, loaded Chase's addresses in that tab, and
    marked every document for manual review."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})

    code = "finished"
    try:
        app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out

    assert not bait_followed(), "the run pressed or followed these on another site's page %s" \
        % bait_followed()
    assert not marked(tmp_path), "documents were marked %s\n%s" % (marked(tmp_path), out)
    assert code == 0, "the run %s rather than stopping\n%s" % (code, out)
    said = folded(out)
    assert "The Chase tab you signed in with is not open." in said, out
    assert "login.bat" in said, out
    assert panel_reads(out)["stopped"] == 1
    assert not marked(tmp_path) and not downloaded(tmp_path), \
        "every document is left as it was for the next run"
    assert not [s for s in SITE.seen if s[0] == CHASE_HOST], "nothing was asked of Chase"
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: address(server, ELSEWHERE_HOST, "/inbox")}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_their_tab_on_the_statements_page_is_still_the_one_used(attached, server, tmp_path,
                                                                capsys):
    """The person's Chase tab is open on the statements page, beside another
    site's tab. Every statement is asked for from their tab, and no tab of
    the run's own is opened."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere_at = address(server, ELSEWHERE_HOST, "/inbox")
    elsewhere = testkit.open_tab(attached, elsewhere_at, "Inbox")
    theirs_at = address(server, CHASE_HOST, DASHBOARD + STATEMENTS_ROUTE)
    theirs = testkit.open_tab(attached, theirs_at, "Statements & documents")
    testkit.keep_only(attached, {elsewhere, theirs})

    assert app_mod.main(["--resume", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert downloaded(tmp_path) == keys, folded(out)
    assert [where for where, _date in SITE.pressed] == [theirs_at] * len(DATES)
    assert not bait_followed()
    assert {t["id"]: t["url"] for t in testkit.tabs_of(attached)} == \
        {elsewhere: elsewhere_at, theirs: theirs_at}, \
        "both tabs are where they were, and no tab of the run's own was opened"
