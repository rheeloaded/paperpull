"""Resume with no Paylocity tab of the person's open, or with theirs on
another page of the site, in a real browser.

After a Discover, Resume goes straight to the statements found. Escher, the
app behind Pay History, makes each statement to order through calls that
carry the person's session cookie, and it answers them only once Pay History
has been opened in that browser. Before that it answers 200 with an empty
body. The app used the person's Paylocity tab when one was open and
otherwise the first open tab of any site, and nothing opened Pay History
first. So with no Paylocity tab of theirs open it read whatever page another
site's tab showed, asked Escher for every statement with no session, was
given nothing, and marked every statement for manual review. The same
happened in the person's own tab when it was on the sign-in host's landing
page, which never opens that session. The calls carry the browser's cookies
whichever tab the app works in, so this showed only when no Escher session
was open, as when Resume runs on a later day than Discover.

Paylocity keeps its session in a cookie, which a new tab shares. So with no
tab of the person's on the site Pay History is opened in a tab of the app's
own, and a tab of theirs on another page of the site is sent to Pay History
before the first statement is asked for. A tab of another site is never
read, clicked or loaded.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. The sign-in host and another site are made-up host names
the browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches Paylocity. The app host, where Pay History, the
calls and the statements are, is this machine's own name, localhost. The app
makes those calls through Playwright's own client, outside the browser, and
that client finds a host through the operating system, which knows no
made-up name. Each opening of Pay History starts a session of its own, and
every session is forgotten when the next test starts, so a cookie one test
leaves in the browser opens nothing for the next. Every company, employee,
statement and date is invented.
"""
import itertools
import json
import sys
import threading
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import paylocity_docs as app_mod
import paylocity_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import doc_types, run_reporting, testkit
from paperpull_core.models import State

ACCESS_HOST = "access.paylocity.test"
# The app host, this machine's own name, since the calls and the statements
# are asked for outside the browser (see the top of this file).
LOGIN_HOST = "localhost"
ELSEWHERE_HOST = "www.elsewhere.test"
# The sign-in host and the other site are found on this machine, and every
# other name fails to resolve, this machine's own two names aside, so a page
# the test forgot to point here goes nowhere.
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1, EXCLUDE %s" % (ACCESS_HOST, ELSEWHERE_HOST, LOGIN_HOST))

# Where each thing is on the app host, taken from the app's own addresses.
PAY_HISTORY_PATH = urlsplit(site.PAY_HISTORY_URL).path
API_PATH = urlsplit(site.API).path
REPORT_BASE_PATH = urlsplit(site.REPORT_BASE).path
REPORT_PATH = REPORT_BASE_PATH + "/companyfiles/DocStream.aspx"
SESSION_COOKIE = "escher_session"

COMPANY_ID = "900000000000001"
EMPLOYEE_ID = "900000000000002"
# Each statement as Escher lists it, its history id, document number and
# pay date.
STATEMENTS = [
    (900000000000011, "900000000000021", "2026-06-07"),
    (900000000000012, "900000000000022", "2026-05-24"),
]
PDFS = {}

PAY_HISTORY_PAGE = """<!doctype html><html><head><title>Pay History</title></head><body>
<main><h1>Pay History</h1><p>Current Check</p></main></body></html>"""

# The page of the sign-in host the person lands on once signed in, which
# never opens the session Escher's calls need.
LANDING_PAGE = """<!doctype html><html><head><title>Paylocity</title></head><body>
<main><h1>Welcome back</h1><p>Company news and your next pay date.</p></main></body></html>"""

# A page of another site, open in the person's browser.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main></body></html>"""

# What the app may do in a tab that reads it, acts in it or loads it.
TOUCHES = ("title", "content", "locator", "evaluate", "evaluate_handle", "query_selector",
           "query_selector_all", "inner_text", "text_content", "get_by_role", "get_by_text",
           "wait_for_selector", "screenshot", "click", "fill", "press", "goto", "reload", "close")

_SESSIONS = itertools.count(1)


class FakePaylocity:
    def __init__(self):
        self.reset()

    def reset(self):
        # The sessions Pay History has opened. A cookie whose session is not
        # here, one left by an earlier test, opens nothing.
        self.sessions = set()
        # The history id of each statement Escher was asked to make, by the
        # id it was scheduled under.
        self.scheduled = {}
        # Every request, as (host, path, whether it carried a session).
        self.seen = []
        # Every read, click or load the app made in a tab, as (what, where
        # the tab was at the time).
        self.touched = []


SITE = FakePaylocity()


def escher(call, query):
    """What Escher answers a call that carries a session."""
    if call == "GetPayAssignments":
        return {"payAssignments": [{"assignmentId": 900000000000003,
                                    "company": {"name": "Example Company"}}]}
    if call == "GetCheckDatesForPayAssignment":
        return {"success": True, "data": [
            {"id": hid, "documentNumber": number, "date": date + "T00:00:00", "type": "Regular",
             "companyId": COMPANY_ID, "employeeId": EMPLOYEE_ID}
            for hid, number, date in STATEMENTS]}
    mine = query.get("companyId") == COMPANY_ID and query.get("employeeId") == EMPLOYEE_ID
    if call == "EnqueueCheckStubReport" and mine and query.get("historyId") in PDFS:
        scheduled = str(900000000000101 + len(SITE.scheduled))
        SITE.scheduled[scheduled] = query["historyId"]
        return {"response": {"scheduledId": scheduled}}
    if call == "GetCheckStubReport" and mine and query.get("scheduledReportId") in SITE.scheduled:
        return {"response": {"downloadUrl": "/companyfiles/DocStream.aspx?r=%s&att=true"
                                            % query["scheduledReportId"], "errors": []}}
    return {"response": {}}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, headers=()):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, html, headers=()):
        self._send(html.encode("utf-8"), "text/html; charset=utf-8", headers)

    def _json(self, value):
        self._send(json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

    def _has_a_session(self):
        """Whether the request carries a session Pay History opened."""
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except CookieError:
            return False
        held = jar.get(SESSION_COOKIE)
        return held is not None and held.value in SITE.sessions

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        where = urlsplit(self.path)
        path, query = where.path, {k: v[0] for k, v in parse_qs(where.query).items()}
        live = self._has_a_session()
        SITE.seen.append((host, path, live))
        escher_call = host == LOGIN_HOST and (path.startswith(API_PATH + "/") or path == REPORT_PATH)
        if host == LOGIN_HOST and path == PAY_HISTORY_PATH:
            session = "session-%d" % next(_SESSIONS)
            SITE.sessions.add(session)
            self._page(PAY_HISTORY_PAGE,
                       [("Set-Cookie", "%s=%s; Path=/; HttpOnly" % (SESSION_COOKIE, session))])
        elif escher_call and not live:
            # Without the session Pay History opens, Escher answers 200 with
            # nothing, which reads as an empty account rather than an error.
            self._send(b"", "application/json; charset=utf-8")
        elif escher_call and path.startswith(API_PATH + "/"):
            self._json(escher(path[len(API_PATH) + 1:], query))
        elif escher_call and query.get("r") in SITE.scheduled:
            self._send(PDFS[SITE.scheduled[query["r"]]], "application/pdf")
        elif host == ACCESS_HOST and path == "/":
            self._page(LANDING_PAGE)
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


@pytest.fixture(scope="module", autouse=True)
def statements():
    """Each statement as Escher makes it, by its history id."""
    for hid, number, date in STATEMENTS:
        PDFS[str(hid)] = testkit.text_pdf(["Example Company", "Pay Statement",
                                           "Pay date %s" % date, "Check number %s" % number,
                                           "Dana Example"])
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


def noting(name, real):
    """A tab's own method, which first notes its use and where the tab was
    at the time."""
    def noted(self, *args, **kwargs):
        SITE.touched.append((name, self.url))
        return real(self, *args, **kwargs)
    return noted


@pytest.fixture(autouse=True)
def fake_paylocity(server, monkeypatch):
    """Paylocity is the made-up site, every read, click or load in a tab is
    noted, and the app's waits are short."""
    SITE.reset()
    sign_in = "http://%s:%d" % (ACCESS_HOST, server)
    app_host = "http://%s:%d" % (LOGIN_HOST, server)
    monkeypatch.setattr(site, "BASE", sign_in)
    for name in ("home", "login"):
        monkeypatch.setitem(site.URLS, name, sign_in + "/")
    monkeypatch.setattr(site, "APP_HOST", app_host)
    monkeypatch.setattr(site, "API", app_host + API_PATH)
    monkeypatch.setattr(site, "PAY_HISTORY_URL", app_host + PAY_HISTORY_PATH)
    monkeypatch.setattr(site, "REPORT_BASE", app_host + REPORT_BASE_PATH)
    monkeypatch.setattr(site, "ALLOWED_HOSTS", {ACCESS_HOST, LOGIN_HOST})
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (ACCESS_HOST, LOGIN_HOST))
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
    for name in TOUCHES:
        monkeypatch.setattr(Page, name, noting(name, getattr(Page, name)))
    return SITE


def seeded(tmp_path, cdp_url):
    """A config, and the statements a Discover found, recorded the way
    discovery records them, none of them downloaded."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    rules = doc_types.load_rules()
    records = {}
    for hid, _number, date in STATEMENTS:
        title = "Pay Statement %s" % date
        category, summary, confidence = doc_types.classify_document(title, rules)
        # The statement's identity, packed the way collect_documents packs it.
        doc = app_mod.Document(title=title, category=category, summary=summary, date=date,
                               confidence=confidence,
                               source_url="%s|%s|%s" % (COMPANY_ID, EMPLOYEE_ID, hid))
        records[doc.key] = dict(doc.to_dict(), state=State.DISCOVERED.value)
    (out / "discovery.json").write_text(json.dumps(records), encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg, sorted(records)


def resume(cfg, capsys):
    """Resume, which has to finish. What it printed."""
    assert app_mod.main(["--resume", "--config", str(cfg)]) == 0
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
    """The statements marked for manual review or failed."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("state") in (
                      State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value))


def on_host(cdp_url, host):
    return [t for t in testkit.tabs_of(cdp_url) if urlsplit(t.get("url") or "").hostname == host]


def touched_on(host):
    """What the app did in a tab while the tab was on this host, each named
    once."""
    return sorted({what for what, where in SITE.touched if urlsplit(where or "").hostname == host})


def asked_with_no_session():
    """Each call to Escher for a statement that carried no session Pay
    History had opened."""
    return [path.rsplit("/", 1)[-1] for host, path, live in SITE.seen
            if host == LOGIN_HOST and not live
            and (path.startswith(API_PATH + "/") or path == REPORT_PATH)]


# -- Resume with no tab of theirs on Pay History ------------------------------------

def test_resume_opens_pay_history_in_a_tab_of_its_own(attached, server, tmp_path, capsys):
    """Discover ran on an earlier day, and another site's tab is the only one
    open, so no tab of the person's is on Paylocity and no Escher session is
    open. Pay History is opened in a tab of the app's own, every statement is
    downloaded through it, and the other site's tab is never read or loaded.
    The app read the other site's page, asked Escher for each statement with
    no session, and marked every statement for manual review."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})
    SITE.seen.clear()

    out = resume(cfg, capsys)

    used = touched_on(ELSEWHERE_HOST)
    assert not marked(tmp_path), \
        "marked for manual review %s, the other site's tab used for %s, Escher asked with " \
        "no session for %s" % (marked(tmp_path), used, asked_with_no_session())
    assert not used, "the other site's tab was used for %s" % used
    assert downloaded(tmp_path) == keys, folded(out)
    assert panel_reads(out)["manual_review"] == 0
    assert not asked_with_no_session(), "every statement was asked for in the session Pay " \
        "History opened"
    still = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert still.get(elsewhere) == address(server, ELSEWHERE_HOST, "/inbox"), \
        "the other site's tab is still where it was"
    assert [urlsplit(t["url"]).path for t in on_host(attached, LOGIN_HOST)] == \
        [PAY_HISTORY_PATH], "Pay History was opened in a tab of the app's own"


def test_their_tab_on_another_page_is_sent_to_pay_history(attached, server, tmp_path, capsys):
    """Discover ran on an earlier day, and the person's Paylocity tab is open
    on the sign-in host's landing page, which never opens Escher's session.
    The tab is sent to Pay History before the first statement is asked for,
    and every statement is downloaded there with no tab of the app's own
    opened. The app worked in the landing page, asked Escher for each
    statement with no session, and marked every statement for manual
    review."""
    cfg, keys = seeded(tmp_path, attached)
    landing = testkit.open_tab(attached, address(server, ACCESS_HOST, "/"), "Paylocity")
    testkit.keep_only(attached, {landing})
    SITE.seen.clear()

    out = resume(cfg, capsys)

    assert not marked(tmp_path), "marked for manual review %s, Escher asked with no session " \
        "for %s" % (marked(tmp_path), asked_with_no_session())
    assert downloaded(tmp_path) == keys, folded(out)
    assert not asked_with_no_session(), "Pay History was opened before the first statement " \
        "was asked for"
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {landing: address(server, LOGIN_HOST, PAY_HISTORY_PATH)}, \
        "their tab was the one used, now on Pay History, and no other was opened"


def test_their_tab_on_pay_history_is_used_as_it_always_was(attached, server, tmp_path, capsys):
    """At home Pay History is usually still open in the tab the person
    signed in with. Resume downloads every statement there, does not load
    the page again, and opens no tab of its own."""
    cfg, keys = seeded(tmp_path, attached)
    theirs = testkit.open_tab(attached, address(server, LOGIN_HOST, PAY_HISTORY_PATH),
                              "Pay History")
    testkit.keep_only(attached, {theirs})
    SITE.seen.clear()

    out = resume(cfg, capsys)

    assert downloaded(tmp_path) == keys, folded(out)
    assert not marked(tmp_path), folded(out)
    assert not [p for _h, p, _live in SITE.seen if p == PAY_HISTORY_PATH], \
        "their tab was not loaded again"
    assert [t["id"] for t in testkit.tabs_of(attached)] == [theirs]
