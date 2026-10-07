"""The statements page counts as open on a year with no statement in it yet.

Ally's statements page opens on its newest year, and the check of the page
counted rows alone. When that year holds nothing Ally has posted yet, the
page has no row, so Discover took it for a page that never opened and
listed none of the years before it. Since a Discover whose page will not
open now stops the run, that would have stopped every such run. The page
is now told by its own address, which the live probe found,
and its year picker. The Tax Forms tab, whose address only begins with the
statements page's, and a statements address that drew no list at all,
still do not count, and Discover stops on the second.

In a real browser attached over CDP, as at home. Ally is a made-up host
name the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches Ally. Every year is invented.
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
import ally_docs as app_mod
import ally_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

ALLY_HOST = "secure.ally.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % ALLY_HOST)

STATEMENTS_PATH = "/bank/statements-and-forms"
TAX_PATH = STATEMENTS_PATH + "/tax"

# The statements page on a year with nothing posted in it yet.
STATEMENTS_PAGE = """<!doctype html><html><head><title>Statements and Tax Forms</title>
</head><body><main>
<h1>Statements and Tax Forms</h1>
<label for="statementYear">Year</label>
<select id="statementYear"><option>2031</option><option>2030</option></select>
<table><thead><tr><th>Date Posted</th><th>Statement Title</th></tr></thead>
<tbody></tbody></table>
<p>There are no statements for this year.</p>
</main></body></html>"""

# The Tax Forms tab, with a year picker of its own and no form yet.
TAX_PAGE = """<!doctype html><html><head><title>Tax Forms</title></head><body><main>
<h1>Tax Forms</h1>
<label for="taxYear">Tax year</label>
<select id="taxYear"><option>2030</option></select>
<p>There are no tax forms for this year.</p>
</main></body></html>"""

# What the statements address shows when the list does not draw.
BROKEN_PAGE = """<!doctype html><html><head><title>Statements and Tax Forms</title>
</head><body><main><h1>Something went wrong</h1>
<p>We could not load this page. Please try again later.</p></main></body></html>"""


class FakeAlly:
    statements_draw = True


SITE = FakeAlly()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = urlsplit(self.path).path.rstrip("/")
        if host != ALLY_HOST:
            self.send_error(404)
            return
        if path == STATEMENTS_PATH:
            page = STATEMENTS_PAGE if SITE.statements_draw else BROKEN_PAGE
        elif path == TAX_PATH:
            page = TAX_PAGE
        else:
            self.send_error(404)
            return
        data = page.encode("utf-8")
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
    return "http://%s:%d%s" % (ALLY_HOST, server, path)


@pytest.fixture(autouse=True)
def made_up_ally(server, monkeypatch):
    """Ally is the made-up site, its statements draw, and the app's waits
    are short."""
    SITE.statements_draw = True
    base = "http://%s:%d" % (ALLY_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    for name, path in (("home", "/"), ("login", "/"), ("documents", STATEMENTS_PATH),
                       ("documents_alt", "/statements"),
                       ("documents_alt2", "/dashboard/#/statements"),
                       ("statements", "/bank/statements")):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "DOCUMENT_URL_CANDIDATES", [
        site.URLS[name] for name in ("documents", "documents_alt", "documents_alt2", "statements")])
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == ALLY_HOST)
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))


@pytest.fixture
def tab(attached):
    """A tab in the browser the app attaches to, for a look at a page."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(attached)
    page = browser.contexts[0].new_page()
    yield page
    page.close()
    pw.stop()


def test_the_statements_page_on_a_year_with_no_row_counts_as_open(tab, server):
    tab.goto(address(server, STATEMENTS_PATH))
    assert site.collect_documents(tab) == [], "the made-up page has a row"
    assert site.on_documents_page(tab)
    before = tab.url
    assert site.ensure_statements(tab) and tab.url == before


def test_the_tax_forms_tab_does_not_count(tab, server):
    tab.goto(address(server, TAX_PATH))
    assert site.year_select(tab)[1] == ["2030"], "the made-up tab has no year picker"
    assert not site.statements_page_drawn(tab)


def test_the_statements_address_with_no_list_does_not_count(tab, server):
    SITE.statements_draw = False
    tab.goto(address(server, STATEMENTS_PATH))
    assert "Something went wrong" in tab.inner_text("main")
    assert not site.on_documents_page(tab)


def run_discover(tmp_path, attached, server, capsys):
    """Discover from the person's Ally tab on the statements address, the
    only tab open."""
    theirs = testkit.open_tab(attached, address(server, STATEMENTS_PATH),
                              "Statements and Tax Forms")
    testkit.keep_only(attached, {theirs})
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


def test_discover_on_a_year_with_no_statement_yet_reads_the_list(server, attached,
                                                                  tmp_path, capsys):
    ended, said, whole = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("returned", 0) and whole is True, said[-1500:]
    assert "Could not open your Ally statements" not in said, said[-1500:]


def test_discover_where_the_list_never_draws_still_stops(server, attached, tmp_path, capsys):
    SITE.statements_draw = False
    ended, said, whole = run_discover(tmp_path, attached, server, capsys)
    assert ended == ("exit", 0) and whole is False, said[-1500:]
    assert "Could not open your Ally statements" in said, said[-1500:]
