"""Resume with no Anthem tab of the person's open, in a real browser.

Anthem keeps its session in a token held in the memory of the tab the person
signed in with, so a new tab is not signed in. After a Discover, Resume goes
straight to the documents found. The app used the person's Anthem tab when
one was open and otherwise the first open tab of any site, so with theirs
closed it read whatever page that tab showed, to see whether Anthem had
signed the person out, and then refused to fetch from it. It said Anthem had
returned a sign-in page in place of a document and the session had expired,
with nothing asked of Anthem, and ended as a run whose session expired, with
code 2 and no stop counted on the panel's result line. Nothing said the tab
was closed.

Now a run with no tab of the person's on the site stops at the first
document and says that tab is not open and how to open it, with every
document left as it was for the next run, and a tab of another site is
never read. The person's own tab, when it is open, is still the one used.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Anthem and another site are made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches Anthem. Every claim number and date is invented.
Once the run is in the person's tab, the call that fetches an EOB is stood
in for, since which tab the run works in is what is under test. After the
EOBs, Resume goes on to Anthem's lists of member documents, ID cards and
letters, which are stood in for as empty, the way each came back when it was
asked for from a tab that was not on Anthem. They take the tab the EOBs do,
so with no EOB left and no Anthem tab open they stop the run too.
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
import anthem_docs as app_mod
import anthem_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

ANTHEM_HOST = "membersecure.anthem.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (ANTHEM_HOST, ELSEWHERE_HOST))

# Each EOB a Discover found, by its claim type, claim number and date.
CLAIMS = [("Medical", "900000000000001", "2026-06-15"),
          ("Pharmacy", "900000000000002", "2026-05-15")]

# The EOB center's summary, where a Discover leaves the person's tab, since
# it is the page Discover opens there to capture the session.
THEIR_PAGE = "/member/claims/eob-center/summary"

EOB_CENTER_PAGE = """<!doctype html><html><head><title>Explanation of Benefits</title>
</head><body><main><h1>Explanation of Benefits</h1>
<p>Medical</p><p>Pharmacy</p><p>Chiropractic</p>
</main></body></html>"""

# A page of another site, open in the person's browser.
ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main></body></html>"""


class FakeAnthem:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path).
        self.seen = []
        # The address of each page the app read to check its session.
        self.read = []
        # The address of the tab each EOB was asked for from, and the EOB,
        # when the call that fetches one is stood in for.
        self.asked = []


SITE = FakeAnthem()


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
        if host == ANTHEM_HOST and path == THEIR_PAGE:
            self._page(EOB_CENTER_PAGE)
        elif host == ELSEWHERE_HOST and path == "/inbox":
            self._page(ELSEWHERE_PAGE)
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


def noted(real):
    """One of the app's own checks of a page, which first notes where the
    page it reads is."""
    def check(page):
        SITE.read.append(page.url)
        return real(page)
    return check


@pytest.fixture(autouse=True)
def fake_anthem(server, monkeypatch):
    """Anthem is the made-up site, its lists of member documents, ID cards
    and letters are empty, every page the app reads to check its session is
    noted, and the app's waits are short."""
    SITE.reset()
    base = "http://%s:%d" % (ANTHEM_HOST, server)
    monkeypatch.setattr(site, "BASE", base)
    monkeypatch.setattr(site, "LOGIN_URL", base + "/account-login/")
    for name, path in (("home", "/"), ("login", "/account-login/"),
                       ("documents", "/member/claims/eob-center"),
                       ("member_documents", "/member/documents"), ("idcard", "/member/idcard")):
        monkeypatch.setitem(site.URLS, name, base + path)
    monkeypatch.setattr(site, "DOCUMENTS_URL", base + "/member/documents")
    monkeypatch.setattr(site, "IDCARD_URL", base + "/member/idcard")

    def on_anthem(url):
        return urlsplit(url or "").hostname == ANTHEM_HOST

    # The member portal the app fetches from, and every page Anthem owns that
    # the app may work in, are the made-up host here.
    monkeypatch.setattr(site, "is_safe_url", on_anthem)
    monkeypatch.setattr(site, "is_anthem_owned", on_anthem)
    # check_session reads the page it is handed for a check and for a sign-out.
    for name in ("detect_security_challenge", "looks_signed_out"):
        monkeypatch.setattr(site, name, noted(getattr(site, name)))
    for name in ("list_member_documents", "list_id_cards", "list_letters"):
        monkeypatch.setattr(site, name, lambda page: [])
    from playwright.sync_api import Page
    real_wait, real_wait_for = Page.wait_for_timeout, Page.wait_for_selector
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))
    monkeypatch.setattr(Page, "wait_for_selector", lambda self, selector, **kw: real_wait_for(
        self, selector, **{**kw, "timeout": min(kw.get("timeout") or 30000, 1500)}))
    return SITE


@pytest.fixture
def stood_in_download(fake_anthem, monkeypatch):
    """The call that fetches an EOB from inside the person's tab is stood in
    for. It saves one only when asked from a tab on Anthem, the one place the
    real call fetches from, and notes which tab asked. A test without this
    fixture runs the real call."""
    def saved_from(page, doc_id, out_path):
        SITE.asked.append((page.url, doc_id))
        if urlsplit(page.url or "").hostname != ANTHEM_HOST:
            return False
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(testkit.text_pdf(["Anthem", "Explanation of Benefits", doc_id]))
        return True

    monkeypatch.setattr(site, "download_document", saved_from)
    return SITE.asked


def seeded(tmp_path, cdp_url):
    """A config, and the EOBs a Discover that read every claim type found,
    none of them downloaded."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for claim_type, claim, date in CLAIMS:
        doc_id = site.make_doc_id(claim_type, claim, "EOB")
        assert site.parse_doc_id(doc_id), "an identity the app would refuse, %s" % doc_id
        account = "%s claim %s" % (claim_type, claim)
        doc = app_mod.Document(title="%s Explanation of Benefits" % claim_type,
                               category="Insurance Document",
                               summary="Explanation of Benefits - %s" % account,
                               date=date, date_text=date, account=account, document_id=doc_id)
        records[doc.key] = dict(doc.to_dict(), state=State.DISCOVERED.value)
    (out / "discovery.json").write_text(json.dumps(records), encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Insurance Document"], "default_start_date": "",
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
    """The pages of another site the app read to check its session."""
    return sorted({url for url in SITE.read if urlsplit(url or "").hostname == ELSEWHERE_HOST})


def test_resume_with_no_tab_of_theirs_open_stops_and_says_so(attached, server, tmp_path,
                                                             capsys):
    """The person's Anthem tab is closed and another site's tab is the only
    one open. The run stops at the first document, saying the tab is not
    open and to open it with login.bat, with nothing marked, nothing asked of
    Anthem and the other site's page never read. The app read the other
    site's page to see whether Anthem had signed the person out, said Anthem
    had returned a sign-in page and the session had expired, and ended with
    code 2 and no stop counted."""
    cfg, _keys = seeded(tmp_path, attached)
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})

    try:
        code = "returned %s" % app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out

    assert not read_elsewhere(), "another site's page was read, %s, and the run %s\n%s" % (
        read_elsewhere(), code, out)
    assert not marked(tmp_path), "documents were marked %s\n%s" % (marked(tmp_path), out)
    assert code == 0, "the run %s rather than stopping\n%s" % (code, out)
    said = folded(out)
    assert "The Anthem tab you signed in with is not open." in said, out
    assert "login.bat" in said, out
    assert panel_reads(out)["stopped"] == 1
    assert not marked(tmp_path) and not downloaded(tmp_path), \
        "every document is left as it was for the next run"
    assert not [s for s in SITE.seen if s[0] == ANTHEM_HOST], "nothing was asked of Anthem"
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: address(server, ELSEWHERE_HOST, "/inbox")}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_with_no_eob_left_the_other_lists_stop_too_rather_than_read_as_empty(
        attached, server, tmp_path, capsys):
    """No EOB is left to resume, so Resume goes straight on to member
    documents, ID cards and letters, with no Anthem tab of the person's open.
    It stops there and says the tab is not open. Each list was asked for
    from a tab that was not on Anthem and came back empty, and the run said
    there was nothing to download, three times, and finished clean."""
    cfg, _keys = seeded(tmp_path, attached)
    (tmp_path / "out" / "discovery.json").write_text("{}", encoding="utf-8")
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})

    try:
        code = "returned %s" % app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out

    said = folded(out)
    assert "No member documents to download" not in said, out
    assert code == 0, "the run %s rather than stopping\n%s" % (code, out)
    assert "The Anthem tab you signed in with is not open." in said, out
    assert panel_reads(out)["stopped"] == 1
    assert not read_elsewhere(), "another site's page was read, %s" % read_elsewhere()
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: address(server, ELSEWHERE_HOST, "/inbox")}, \
        "the other site's tab is where it was, and no tab of the run's own is left behind"


def test_their_tab_on_the_member_portal_is_still_the_one_used(attached, server, tmp_path,
                                                             capsys, stood_in_download):
    """The person's Anthem tab is open on the EOB center, beside another
    site's tab. Every EOB is asked for from their tab, which stays where it
    is, the other site's page is never read, and no tab of the run's own is
    opened."""
    cfg, keys = seeded(tmp_path, attached)
    elsewhere_at = address(server, ELSEWHERE_HOST, "/inbox")
    elsewhere = testkit.open_tab(attached, elsewhere_at, "Inbox")
    theirs_at = address(server, ANTHEM_HOST, THEIR_PAGE + "?eobType=Medical")
    theirs = testkit.open_tab(attached, theirs_at, "Explanation of Benefits")
    testkit.keep_only(attached, {elsewhere, theirs})

    code = app_mod.main(["--resume", "--config", str(cfg)])
    out = capsys.readouterr().out

    assert code == 0, out
    assert downloaded(tmp_path) == keys, folded(out)
    assert [where for where, _doc in stood_in_download] == [theirs_at] * len(CLAIMS)
    assert not read_elsewhere(), "another site's page was read, %s" % read_elsewhere()
    tabs = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert tabs == {elsewhere: elsewhere_at, theirs: theirs_at}, \
        "their tab is where it was beside the other site's, and no tab of the run's own is open"
