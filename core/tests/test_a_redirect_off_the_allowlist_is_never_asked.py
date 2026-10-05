"""A redirect off the provider's hosts is never asked, in a real browser.

test_no_request_follows_a_redirect_off_the_allowlist.py holds every call
into Playwright's own request client to max_redirects=0, or to the core's
redirects.get, which follows one hop at a time and checks each with the
app's guard. This is what that does in a real browser, started as a program
of its own and attached over CDP the way the apps attach, for the helper
and for each app whose call changed.

A document's address that answers with a redirect to another host is never
asked there, from outside the page or at all, so the cookie the browser
holds for that host goes nowhere, and nothing from it is saved. An address
that answers directly still brings the document, and so does one sent on
within the provider's own hosts wherever the call may follow it. An address
the browser already got its document from is asked again with no redirect
followed.

The made-up provider answers at localhost, since Playwright's own client
finds a host through the operating system and knows no made-up name. The
other site is 127.0.0.1. Every other name fails to resolve in the browser,
and the client is refused any host but these two, so nothing leaves this
machine. Each app's guard is swapped for one that allows the made-up
provider alone, the way every app's own guard allows its provider alone.
Every title, date and number is invented.
"""
import base64
import importlib
import json
import sys
import threading
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core import browser as browser_launcher  # noqa: E402
from paperpull_core import capture  # noqa: E402
from paperpull_core import testkit  # noqa: E402

PROVIDER = "localhost"
ELSEWHERE = "127.0.0.1"
HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1, EXCLUDE localhost"
OURS = testkit.text_pdf(["Made-up Provider", "Monthly Statement", "June 15, 2026"])
THEIRS = testkit.text_pdf(["Another Site", "Their Own Document", "June 15, 2026"])
SENDS = ("get", "post", "put", "patch", "delete", "head", "fetch")

# Every request the server saw. A browser names a Sec-Fetch-Mode on each
# request it makes, and Playwright's own client names none.
Asked = namedtuple("Asked", "host path then mode cookie")

# A page whose one control reads a document into a blob, the way a provider's
# script hands one over, from the address in its own query.
PRESS_PAGE = """<!doctype html><html><head><title>Documents</title></head><body>
<main><h1>Statements</h1><button id="press">Download PDF</button></main>
<script>
const doc = new URLSearchParams(location.search).get('doc');
document.querySelector('#press').addEventListener('click', async () => {
  const r = await fetch(doc);
  await r.blob();
});
</script></body></html>"""
PLAIN_PAGE = "<!doctype html><title>Signed in</title><p>Account</p>"


class Site:
    def __init__(self):
        self.reset()

    def reset(self):
        self.seen = []
        self.times = {}
        self.report_then = "doc"


SITE = Site()


class _Handler(BaseHTTPRequestHandler):
    """What the made-up provider and the other site answer.

    The provider answers every address by what its `then` says.
      doc, json      the document, or a JSON answer of its own
      hop, hopjson   a 302 to the same address, which then answers doc or json
      hopwhole       the same, its Location a whole address
      away, awayjson a 302 to the same address on the other site
      hopaway        a 302 on its own host, then away
      once           the document the first time the address is asked, away after
      loop           a 302 to itself, without end
    The other site answers every address with its own document."""

    protocol_version = "HTTP/1.1"

    def _send(self, status, body=b"", kind="text/plain", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        then = (query.get("then") or [""])[0]
        SITE.seen.append(Asked(host, parts.path, then, self.headers.get("Sec-Fetch-Mode"),
                               self.headers.get("Cookie") or ""))
        port = self.server.server_address[1]
        if host == ELSEWHERE:
            if parts.path == "/page":
                self._send(200, PLAIN_PAGE.encode(), "text/html; charset=utf-8")
            elif "json" in then:
                self._send(200, b'{"theirs": true}', "application/json")
            else:
                self._send(200, THEIRS, "application/pdf")
            return
        if host != PROVIDER:
            self.send_error(404)
            return
        if parts.path == "/page":
            self._send(200, PRESS_PAGE.encode(), "text/html; charset=utf-8")
            return
        if parts.path == "/signed-in":
            self._send(200, PLAIN_PAGE.encode(), "text/html; charset=utf-8")
            return
        if parts.path.endswith("/EnqueueCheckStubReport"):
            self._send(200, b'{"response": {"scheduledId": "s-1"}}', "application/json")
            return
        if parts.path.endswith("/GetCheckStubReport"):
            body = {"response": {"downloadUrl": "/DocStream.aspx?then=" + SITE.report_then}}
            self._send(200, json.dumps(body).encode(), "application/json")
            return
        times = SITE.times[parts.path] = SITE.times.get(parts.path, 0) + 1
        kind = "json" if "json" in then else "doc"
        if then == "once":
            then = "doc" if times == 1 else "away"
        if then in ("", "doc", "json"):
            if kind == "json":
                self._send(200, b'{"ours": true}', "application/json")
            else:
                self._send(200, OURS, "application/pdf")
            return
        if then in ("hop", "hopjson"):
            where = "%s?then=%s" % (parts.path, kind)
        elif then == "hopwhole":
            where = "http://%s:%d%s?then=doc" % (PROVIDER, port, parts.path)
        elif then == "hopaway":
            where = "%s?then=away" % parts.path
        elif then in ("away", "awayjson"):
            where = "http://%s:%d%s?then=%s" % (ELSEWHERE, port, parts.path, kind)
        elif then == "loop":
            where = "%s?then=loop&n=%d" % (parts.path, times)
        else:
            self.send_error(404)
            return
        self._send(302, extra=[("Location", where)])

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
def context(server, tmp_path_factory):
    """The context of a fresh browser attached over CDP, holding a cookie
    for the other site, which a followed redirect would carry there."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    from playwright.sync_api import sync_playwright
    try:
        with testkit.drawn_browser(found[0][1], lambda: tmp_path_factory.mktemp("profile"),
                                   args=(HOSTS,)) as url:
            driver = sync_playwright().start()
            try:
                ctx = driver.chromium.connect_over_cdp(url).contexts[0]
                ctx.add_cookies([{"name": "theirs", "value": "kept-for-the-other-site",
                                  "domain": ELSEWHERE, "path": "/"}])
                yield ctx
            finally:
                driver.stop()
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def only_this_machine(monkeypatch):
    """Playwright's own client may ask the two hosts here and no other, so a
    test that built a real provider's address fails rather than asks it."""
    try:
        from playwright.sync_api import APIRequestContext
    except Exception:
        return
    for name in SENDS:
        real = getattr(APIRequestContext, name, None)
        if real is None:
            continue

        def kept(self, url, *args, _real=real, **kwargs):
            host = urlsplit(url if isinstance(url, str) else url.url).hostname
            if host not in (PROVIDER, ELSEWHERE):
                raise AssertionError("a test asked a host off this machine, %s" % host)
            return _real(self, url, *args, **kwargs)

        monkeypatch.setattr(APIRequestContext, name, kept)


@pytest.fixture()
def page(context, server):
    SITE.reset()
    tab = context.new_page()
    own = tab.wait_for_timeout
    # Every wait the capture code makes is a twentieth as long. It counts
    # its looks rather than the clock, so what it does is the same.
    tab.wait_for_timeout = lambda ms: own(max(1, int(ms) // 20))
    try:
        yield tab
    finally:
        try:
            tab.close()
        except Exception:
            pass


def base(server) -> str:
    return "http://%s:%d" % (PROVIDER, server)


def guard_for(server):
    """The made-up provider's own host, and nothing else, as an app's guard
    allows its provider's own hosts."""
    def is_safe_url(url):
        try:
            parts = urlsplit(url or "")
            return parts.scheme == "http" and parts.hostname == PROVIDER and \
                parts.port == server and not parts.username
        except ValueError:
            return False
    return is_safe_url


def asked_elsewhere():
    """Every request that reached the other site, other than a test's own
    visit to its plain page and the icon the browser asks for with it."""
    return [a for a in SITE.seen if a.host == ELSEWHERE
            and a.path not in ("/page", "/favicon.ico")]


def asked_from_outside(path):
    """How many times Playwright's own client asked the provider for `path`."""
    return len([a for a in SITE.seen if a.host == PROVIDER and a.path == path and a.mode is None])


def elsewhere_from_outside():
    """Every request Playwright's own client made to the other site. A page's
    own script follows its own redirects, as a provider's page would, and
    those carry a mode."""
    return [a for a in asked_elsewhere() if a.mode is None]


def site_of(slug: str):
    folder = str(REPO / "apps" / slug)
    sys.path.insert(0, folder)
    try:
        return importlib.import_module("%s_site" % slug)
    finally:
        sys.path.remove(folder)


# -- the core's helper ---------------------------------------------------------------

@pytest.fixture()
def redirects():
    return importlib.import_module("paperpull_core.redirects")


def test_a_redirect_on_the_providers_own_host_is_followed(page, server, redirects):
    for then in ("hop", "hopwhole"):
        SITE.reset()
        got = redirects.get(page.context.request, base(server) + "/statement.pdf?then=" + then,
                            guard_for(server), timeout=20000)
        assert got.status == 200 and got.body() == OURS, then
        assert asked_from_outside("/statement.pdf") == 2, SITE.seen


def test_a_redirect_to_another_host_is_never_asked(page, server, redirects):
    for then in ("away", "hopaway"):
        SITE.reset()
        got = redirects.get(page.context.request, base(server) + "/statement.pdf?then=" + then,
                            guard_for(server), timeout=20000)
        assert got.status == 302 and not got.ok, then
        assert asked_elsewhere() == [], asked_elsewhere()


def test_more_redirects_than_its_hops_are_given_up(page, server, redirects):
    with pytest.raises(redirects.TooManyRedirects):
        redirects.get(page.context.request, base(server) + "/statement.pdf?then=loop",
                      guard_for(server), hops=3, timeout=20000)
    assert asked_from_outside("/statement.pdf") == 4


def test_an_address_its_guard_refuses_is_never_asked(page, server, redirects):
    with pytest.raises(ValueError):
        redirects.get(page.context.request, "http://%s:%d/statement.pdf" % (ELSEWHERE, server),
                      guard_for(server), timeout=20000)
    assert SITE.seen == []


def test_what_is_asked_with_goes_with_the_first_ask_only(page, server, redirects):
    got = redirects.get(page.context.request, base(server) + "/statement.pdf",
                        guard_for(server), params={"then": "hop"}, timeout=20000)
    assert got.body() == OURS
    assert [a.then for a in SITE.seen] == ["hop", "doc"]


def test_a_link_fetched_for_the_first_time_follows_only_its_own_hosts(page, server):
    guard = guard_for(server)
    for then, wanted in (("doc", OURS), ("hop", OURS), ("hopwhole", OURS),
                         ("away", None), ("hopaway", None), ("loop", None)):
        SITE.reset()
        got = capture.fetch_pdf(page, base(server) + "/statement.pdf?then=" + then, guard)
        assert got == wanted, then
        assert asked_elsewhere() == [], (then, asked_elsewhere())


def test_a_tab_on_a_document_asks_its_own_address_and_nothing_further(page, server, tmp_path):
    """The tab is on the document, and asked again the address sends the
    session to another host. The tab already showed it, so nothing is
    followed, from outside the page or inside it."""
    guard = guard_for(server)
    for then, wanted in (("doc", OURS), ("once", None)):
        SITE.reset()
        out = tmp_path / ("%s.pdf" % then)
        start = base(server) + "/signed-in"
        page.goto(start, wait_until="domcontentloaded")
        page.goto(base(server) + "/statement.pdf?then=" + then, wait_until="domcontentloaded")
        took = capture.take_same_tab(page, start, out, None, guard)
        assert took == (wanted is not None), then
        assert (out.read_bytes() if out.exists() else None) == wanted, then
        assert asked_elsewhere() == [], (then, asked_elsewhere())


# -- every app whose call changed ------------------------------------------------------
#
# Each asks with the app's own code. A redirect it may follow is followed
# only to the provider's own host, and one to the other site is never
# asked. An app that asks again an address the browser already got its
# document from follows none, and `once` is that address sending the
# session on, the second time it is asked.

SCAFFOLD = ["adp", "amfam", "applecard", "etrade", "golden1", "newrez", "sba", "smud",
            "statefarm", "verizonmobile", "wellsfargo"]


@pytest.fixture()
def unreadable(monkeypatch):
    """The document's answer cannot be read off the response, as a blob's
    could not be under Playwright 1.62, so the capture asks its address
    again. Only the made-up provider's document is made so."""
    from playwright.sync_api import Response
    real = Response.body

    def body(self):
        parts = urlsplit(self.url)
        if parts.hostname == PROVIDER and parts.path == "/statement.pdf":
            raise RuntimeError("the answer's body is no longer available")
        return real(self)

    monkeypatch.setattr(Response, "body", body)


@pytest.mark.parametrize("slug", SCAFFOLD)
@pytest.mark.parametrize("then, wanted", [("doc", OURS), ("once", None)])
def test_a_press_whose_answer_is_asked_for_again(slug, then, wanted, page, server, tmp_path,
                                                 monkeypatch, unreadable):
    site = site_of(slug)
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    page.goto(base(server) + "/page?doc=" + quote("/statement.pdf?then=" + then),
              wait_until="domcontentloaded")
    SITE.seen.clear()
    out = tmp_path / "statement.pdf"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    took = site._catch_pdf(page, page.query_selector("#press"), "Download PDF", out, [],
                           downloads)
    # Apple Card presses once more after a press that brought nothing, and
    # the page's own fetch then follows the page's own redirect. Only what
    # the app asks from outside the page is the app's.
    assert asked_from_outside("/statement.pdf") >= 1, SITE.seen
    assert elsewhere_from_outside() == [], elsewhere_from_outside()
    assert took == (wanted is not None)
    assert (out.read_bytes() if out.exists() else None) == wanted


WALKS = [("doc", True), ("hop", True), ("away", False)]


def _kept(out: Path):
    return out.read_bytes() if out.exists() else None


@pytest.mark.parametrize("then, brings", WALKS)
def test_amazon_invoice(then, brings, page, server, tmp_path, monkeypatch):
    site = site_of("amazon")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    out = tmp_path / "invoice.pdf"
    site.download_invoice_pdf(page, base(server) + "/documents/download/a1b2/invoice.pdf?then="
                              + then, out)
    assert _kept(out) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", WALKS)
def test_mtb_statement(then, brings, page, server, tmp_path, monkeypatch):
    site = site_of("mtb")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    out = tmp_path / "statement.pdf"
    href = base(server) + "/Statements/FetchStatementandNotices?t=MTGSTMT&stmtId=9&then=" + then
    assert site.download_statement(page, href, out) == brings
    assert _kept(out) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


def test_mtb_reads_a_long_chain_as_an_ended_session(page, server, tmp_path, monkeypatch):
    site = site_of("mtb")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    href = base(server) + "/Statements/FetchStatementandNotices?t=MTGSTMT&then=loop"
    with pytest.raises(site.SessionExpired):
        site.download_statement(page, href, tmp_path / "statement.pdf")
    assert asked_from_outside("/Statements/FetchStatementandNotices") == 4


@pytest.mark.parametrize("then, brings", WALKS)
def test_discover_statement(then, brings, page, server, tmp_path, monkeypatch):
    site = site_of("discovercard")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    monkeypatch.setattr(site, "BASE", base(server))
    out = tmp_path / "statement.pdf"
    href = base(server) + "/cardmembersvcs/statements/app/stmtPDF?date=20260615&then=" + then
    assert site.discovercard_download(page, page.context, "", "2026-06-15", out,
                                      document_id=href) == brings
    assert _kept(out) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("slug", ["fedex", "stripe"])
@pytest.mark.parametrize("then, brings", WALKS)
def test_a_file_the_page_may_not_read_is_asked_through_the_session(slug, then, brings, page,
                                                                   server, monkeypatch):
    """The page is on another origin, so its own fetch of the file is
    refused and the app asks through the session instead."""
    site = site_of(slug)
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    if hasattr(site, "on_dashboard"):
        monkeypatch.setattr(site, "on_dashboard", lambda page: True)
    page.goto("http://%s:%d/page" % (ELSEWHERE, server), wait_until="domcontentloaded")
    got = site._fetch_file(page, base(server) + "/files/invoice.pdf?then=" + then)
    kept = base64.b64decode(got["b64"]) if got.get("b64") else None
    assert kept == (OURS if brings else None)
    assert asked_from_outside("/files/invoice.pdf") >= 1
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", WALKS)
def test_ukg_pay_statement(then, brings, page, server, tmp_path, monkeypatch):
    site = site_of("ukg")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    out = tmp_path / "pay.pdf"
    url = base(server) + "/pay/statements/1/2/pdf?then=" + then
    assert site.download_document(page, url, out) == brings
    assert _kept(out) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", [("json", True), ("hopjson", True), ("awayjson", False)])
def test_ukg_api(then, brings, page, server, monkeypatch):
    site = site_of("ukg")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    monkeypatch.setattr(site, "BASE", base(server))
    assert site._get_json(page, "/pay/companies?then=" + then) == ({"ours": True} if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", [("json", True), ("hopjson", True), ("awayjson", False)])
def test_paylocity_api(then, brings, page, server, monkeypatch):
    site = site_of("paylocity")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    got = site._get_json(page, base(server) + "/api/GetPayAssignments", {"then": then})
    assert got == ({"ours": True} if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", WALKS)
def test_paylocity_pay_statement(then, brings, page, server, tmp_path, monkeypatch):
    site = site_of("paylocity")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    monkeypatch.setattr(site, "API", base(server) + "/api")
    monkeypatch.setattr(site, "REPORT_BASE", base(server) + "/report")
    SITE.report_then = then
    out = tmp_path / "pay.pdf"
    assert site.download_document(page, "1|2|3", out) == brings
    assert _kept(out) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", [("doc", True), ("once", False)])
def test_pge_bill_in_the_tab(then, brings, page, server, monkeypatch):
    """The bill is in the tab, and PG&E's reader asks the tab's address."""
    site = site_of("pge")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    page.goto(base(server) + "/statement.pdf?then=" + then, wait_until="domcontentloaded")
    assert site._pdf_from_here(page) == (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()


@pytest.mark.parametrize("then, brings", [("doc", True), ("away", False)])
def test_pge_bill_a_new_tab_stands_at(then, brings, page, server, monkeypatch):
    site = site_of("pge")
    monkeypatch.setattr(site, "is_safe_url", guard_for(server))
    assert site._pdf_at(page, base(server) + "/statement.pdf?then=" + then) == \
        (OURS if brings else None)
    assert asked_elsewhere() == [], asked_elsewhere()
