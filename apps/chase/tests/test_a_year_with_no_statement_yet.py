"""The document center counts as open on a year with no statement in it yet.

Chase's document center opens with one card's accordion expanded on the
current year, and the check of the page counted rows alone. From New Year
until that card's first statement of the year, and all year for a card
with no statement in it, that view can hold no row, so Discover took the
center for a page that never opened and listed none of the years before
it, and a download gave up the same way. Since a Discover whose page will
not open now stops the run, that would have stopped every such run. The
center is now told by its route, its "View:" year picker showing a year,
and a card accordion, which the live probe found and the
collector works through. The dashboard's own front page, drawn under a
route pasted into its address, with a picker of something other than years
and a card of its own, still does not count, and Discover stops there. So
do the center's tax documents and year-end summaries, tabs of their own
that this app does not collect, whether they show a row or none.

In a real browser attached over CDP, as at home. Chase is a made-up host
name the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches Chase. Its dashboard is one page that
draws whatever its route after # names, and only the route the probe found
the statements at draws the center. Every card and year is invented.
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
from paperpull_core import testkit

CHASE_HOST = "secure.chase.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % CHASE_HOST)

DASHBOARD = "/web/auth/dashboard"
CENTER_ROUTE = "#/dashboard/documents/myDocs/index"
CARD = "EXAMPLE CARD (...0001)"

# The center on a year with no statement in it yet. The picker shows the
# year, the card's accordion is open, and there is no row. Its tabs are
# named in the address after the route, and each draws the same frame.
# The dashboard is asked with ?rows=1 for a row in the view, as a year
# with a statement in it has, and with ?nocard=1 for no card at all.
CENTER = """<h1>Statements &amp; documents</h1>
<p><input id="filterstyledselect-year" aria-label="View:" value="2031" readonly></p>
<button type="button" class="card" aria-expanded="true">%s</button>
<ul class="rows"><li class="statement">Jan 15, 2031 Statement %s <a href="#"
aria-label="Jan 15, 2031 Statement %s Saves document">Saves document</a></li></ul>
<p class="none">There are no documents for this time period.</p>""" % (CARD, CARD, CARD)

# A view of the year's activity, on a route of its own, with a picker of
# years and the card.
ACTIVITY_ROUTE = "#/dashboard/activity/index"
ACTIVITY = """<h1>Year in review</h1>
<p><input id="filterstyledselect-year" aria-label="View:" value="2031" readonly></p>
<button type="button">%s</button>""" % CARD

# The dashboard's front page, drawn for every other route. It has a styled
# picker too, of the activity shown, and a button for the card.
FRONT = """<h1>Accounts</h1>
<p><input id="filterstyledselect-activity" aria-label="Showing:" value="Last 30 days" readonly></p>
<button type="button">%s</button>
<p>Your accounts at a glance.</p>""" % CARD

DASHBOARD_PAGE = """<!doctype html><html><head><title>Chase</title></head><body>
<main id="view"></main>
<template id="center">%s</template>
<template id="activity">%s</template>
<template id="front">%s</template>
<script>
function route() {
  const asked = new URLSearchParams(location.search);
  const center = location.hash.startsWith('%s');
  const activity = location.hash === '%s';
  document.title = center ? 'Statements & documents' : activity ? 'Year in review' : 'Accounts';
  const drawn = document.getElementById(center ? 'center' : activity ? 'activity' : 'front');
  const view = document.getElementById('view');
  view.replaceChildren(drawn.content.cloneNode(true));
  if (center) {
    view.querySelector(asked.get('rows') ? '.none' : '.rows').remove();
    if (asked.get('nocard')) view.querySelector('.card').remove();
  }
}
addEventListener('hashchange', route);
route();
</script></body></html>""" % (CENTER, ACTIVITY, FRONT, CENTER_ROUTE, ACTIVITY_ROUTE)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host != CHASE_HOST or urlsplit(self.path).path != DASHBOARD:
            self.send_error(404)
            return
        data = DASHBOARD_PAGE.encode("utf-8")
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


@pytest.fixture(autouse=True)
def made_up_chase(server, monkeypatch):
    """Chase is the made-up site, and the app's waits are short."""
    def made_up(url):
        parts = urlsplit(url)
        return urlunsplit(("http", "%s:%d" % (CHASE_HOST, server), parts.path, parts.query,
                           parts.fragment))

    for name, url in list(site.URLS.items()):
        monkeypatch.setitem(site.URLS, name, made_up(url))
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES",
                        [made_up(url) for url in site.DOCUMENT_URL_CANDIDATES])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == CHASE_HOST)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))


def dashboard(server, route, asked=""):
    return "http://%s:%d%s%s%s" % (CHASE_HOST, server, DASHBOARD, asked, route)


@pytest.fixture
def tab(attached, server):
    """The person's tab, in the browser the app attaches to."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(attached)
    page = browser.contexts[0].new_page()
    yield page
    page.close()
    pw.stop()


def test_the_center_on_a_year_with_no_row_counts_as_open(tab, server):
    tab.goto(dashboard(server, CENTER_ROUTE))
    assert site.collect_documents(tab) == [], "the made-up center has a row"
    assert site.on_documents_page(tab)
    before = tab.url
    assert site.ensure_statements(tab) and tab.url == before


def test_the_center_with_a_row_still_counts_as_open(tab, server):
    """The other side, a year with a statement in it, read by its row as
    it always was, on the center's first tab or named as its statements."""
    for route in (CENTER_ROUTE, CENTER_ROUTE + ";documentType=STATEMENTS"):
        tab.goto(dashboard(server, route, "?rows=1"))
        assert len(site.collect_documents(tab)) == 1
        assert site.on_documents_page(tab)
    tab.goto(dashboard(server, CENTER_ROUTE + ";documentType=STATEMENTS"))
    assert site.on_documents_page(tab)


@pytest.mark.parametrize("kind", ["TAX_DOCUMENTS", "YEAR_END_STATEMENTS"])
@pytest.mark.parametrize("asked", ["", "?rows=1"], ids=["no row", "a row"])
def test_another_tab_of_the_center_never_counts(tab, server, kind, asked):
    """Tax documents and year-end summaries are tabs of the same center,
    which this app does not collect, so a run left there goes on to the
    statements rather than take what it finds for them."""
    tab.goto(dashboard(server, CENTER_ROUTE + ";documentType=" + kind, asked))
    assert "Statements & documents" == tab.title()
    assert not site.on_documents_page(tab)


def test_the_center_with_no_card_does_not_count(tab, server):
    tab.goto(dashboard(server, CENTER_ROUTE, "?nocard=1"))
    assert tab.locator("#filterstyledselect-year").count() == 1
    assert not site.on_documents_page(tab)


@pytest.mark.parametrize("route", ["", "#/dashboard/documents/index"],
                         ids=["front page", "front page under a pasted route"])
def test_the_front_page_with_a_picker_and_a_card_does_not_count(tab, server, route):
    tab.goto(dashboard(server, route))
    assert "Your accounts at a glance" in tab.inner_text("main")
    assert not site.on_documents_page(tab)


def test_a_year_picker_and_a_card_off_the_center_do_not_count(tab, server):
    tab.goto(dashboard(server, ACTIVITY_ROUTE))
    assert "Year in review" in tab.inner_text("main")
    assert not site.on_documents_page(tab)


def run_discover(tmp_path, attached, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": attached,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    capsys.readouterr()
    try:
        ended = ("returned", app_mod.main(["--config", str(cfg), "--discover"]))
    except SystemExit as e:
        ended = ("exit", e.code)
    said = " ".join(capsys.readouterr().out.split())
    noted = tmp_path / "out" / "last-listing.json"
    return ended, said, json.loads(noted.read_text(encoding="utf-8"))["complete"]


def their_tab(attached, server, route, title):
    """The person's Chase tab on this route, the only tab open."""
    theirs = testkit.open_tab(attached, dashboard(server, route), title)
    testkit.keep_only(attached, {theirs})


def test_discover_on_a_year_with_no_statement_yet_reads_the_list(server, attached,
                                                                  tmp_path, capsys):
    their_tab(attached, server, CENTER_ROUTE, "Statements & documents")
    ended, said, whole = run_discover(tmp_path, attached, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert "Could not open your Chase statements" not in said, said[-1500:]


@pytest.mark.parametrize("route, title", [
    ("", "Accounts"),
    (CENTER_ROUTE + ";documentType=TAX_DOCUMENTS", "Statements & documents"),
], ids=["front page", "tax documents"])
def test_discover_off_the_statements_still_stops(server, attached, tmp_path, capsys,
                                                  route, title):
    """Nothing here leads to the statements, as a menu would at Chase, so a
    run left on the front page or on the tax documents stops rather than
    call an empty list read."""
    their_tab(attached, server, route, title)
    ended, said, whole = run_discover(tmp_path, attached, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "Could not open your Chase statements" in said, said[-1500:]
