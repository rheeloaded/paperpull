"""Statements & Notices' two lists and a document's PDF, asked in a real
browser by the scripts the site layer runs inside the page.

The unit tests answer those scripts themselves, so with any of them
replaced by a syntax error every one of them still passed. Here the
client portal is a made-up site on this machine. Its Statements & Notices
page asks the statement API for the current quarter's statements and for
the quarterly performance reports, the way client.adviceworks.net does,
with an authorization and an x-session-id header of its own. The API
answers the statements two a page, and a PDF only with the page's own
headers and, for a report, its accountId header.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every other host name fails to resolve, so nothing
reaches Cetera. Every account, id, date and name is invented.
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
import cetera_docs as app_mod
import cetera_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HOST = "client.adviceworks.test"
HOSTS = "--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" % HOST

SESSION = "fake-session-0000"
ACCOUNTS = [{"accountNum": "XXXX-3141", "accountType": "BR", "accountId": 60000001, "custodian": "TESTCO"},
            {"accountNum": "XXXX-2718", "accountType": "BR", "accountId": 60000002, "custodian": "TESTCO"}]
PAGE_SIZE = 2


def _sid(acct, day, kind="statement"):
    return "St" + base64.b64encode(f"{acct}|{day}|{kind}".encode()).decode()


# The statements, newest first, as (account, MM/DD/YYYY), over two pages.
# A third part, when there is one, sets the statement's id apart.
STATEMENTS = [("XXXX-3141", "09/30/2026"), ("XXXX-2718", "09/30/2026"), ("XXXX-3141", "08/31/2026")]
# The reports, as (report id, MM/DD/YYYY, name).
REPORTS = [("50000002", "09/30/2026", "2026 Q3 Example Household"),
           ("50000001", "06/30/2026", "2026 Q2 Example Household")]
PDFS = {_sid(a, d): testkit.text_pdf([f"Cetera test statement {a} {d}"],
                                     min_bytes=100_000 if i == 0 else 4000)
        for i, (a, d) in enumerate(STATEMENTS)}
PDFS.update({rid: testkit.text_pdf([f"Cetera test report {d}"]) for rid, d, _ in REPORTS})

# The page asks what the live page asks on load, from its own script.
STATEMENTS_PAGE = """<!doctype html><html><head><title>Statements &amp; Notices</title></head>
<body><main><h1>Statements &amp; Notices</h1><table><tbody id="rows"></tbody></table></main>
<script>
const api = "/integrate-api/cpstatement/v1/experience/";
const headers = {"content-type": "application/json", "authorization": %(token)s,
                 "x-session-id": %(session)s};
fetch(api + "statements?pageNum=1", {method: "POST", headers: headers,
      body: JSON.stringify({accountList: %(accounts)s, quarter: "q3", year: "2026"})})
  .then(r => r.json())
  .then(a => {
    for (const s of (a.statementData || [])) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + s.statementDateFormated + "</td><td>" + s.statementName + "</td>";
      document.getElementById("rows").appendChild(tr);
    }
    return fetch(api + "accountQprs?quarter=all&year=all", {headers: headers});
  });
</script></body></html>"""


class FakeCetera:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, path, query, what the body asked).
        self.seen = []
        # The page's token, which a reload of the page may change.
        self.token = "Bearer fake-browser-token-0000"
        self.statements = list(STATEMENTS)
        self.reports = list(REPORTS)
        self.list_status = 200
        self.is_ria = False
        # What a document's PDF is answered with instead, by its id,
        # "json", "html" or "refused" (a 403).
        self.instead = {}
        # Page two of the statements gives page one's last row again in
        # place of its own, as a sort that moves between pages does.
        self.unstable = False


SITE = FakeCetera()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, value):
        self._send(status, json.dumps(value).encode(), "application/json")

    def _signed_in(self):
        return (self.headers.get("authorization") == SITE.token
                and self.headers.get("x-session-id") == SESSION)

    def _pdf(self, key):
        instead = SITE.instead.get(key)
        if instead == "json":
            return self._json(200, {"message": "Statement not available"})
        if instead == "html":
            return self._send(200, b"<!doctype html><title>Error</title>", "text/html")
        if instead == "refused":
            return self._json(403, {"message": "Forbidden"})
        if key not in PDFS:
            return self._json(404, {"message": "no such document"})
        return self._send(200, PDFS[key], "application/pdf")

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(("GET", parts.path, parts.query, None))
        if parts.path == site.DOCUMENTS_PATH:
            html = STATEMENTS_PAGE % {"token": json.dumps(SITE.token), "session": json.dumps(SESSION),
                                      "accounts": json.dumps(ACCOUNTS)}
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if not parts.path.startswith(site.API_PATH):
            return self.send_error(404)
        if not self._signed_in():
            return self._json(401, {"message": "Unauthorized"})
        q = parse_qs(parts.query)
        if parts.path == site.QPR_LIST_PATH:
            rows = [{"statementName": name, "statementId": rid, "statementDate": "1790000000000",
                     "statementDateFormated": day, "accountId": 70000001, "isRia": SITE.is_ria}
                    for rid, day, name in SITE.reports]
            return self._json(200, {"statementData": rows, "totalItems": len(rows)})
        head, _, seg = parts.path.rpartition("/")
        if head == site.DOWNLOAD_PATH and q == {"isStatementIdEncoded": ["true"],
                                                "statementType": ["STATEMENTS"]}:
            return self._pdf(base64.urlsafe_b64decode(seg).decode())
        if head == site.QPR_DOWNLOAD_PATH and q.get("statementType") == ["QPR"]:
            if self.headers.get("accountId") != "70000001":
                return self._json(400, {"message": "no account"})
            return self._pdf(seg)
        self.send_error(404)

    def do_POST(self):
        parts = urlsplit(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SITE.seen.append(("POST", parts.path, parts.query, body.get("quarter")))
        if parts.path != site.LIST_PATH:
            return self.send_error(404)
        if not self._signed_in():
            return self._json(401, {"message": "Unauthorized"})
        if SITE.list_status != 200:
            return self._json(SITE.list_status, {"message": "Server error"})
        rows = [{"accountNum": s[0], "accountType": "BR", "statementName": "Brokerage Statement",
                 "statementId": _sid(*s), "statementDate": "1790000000000", "statementDateFormated": s[1]}
                for s in SITE.statements]
        if body.get("quarter") != "All":
            rows = rows[:1]
        n = int(parse_qs(parts.query)["pageNum"][0])
        part = rows[(n - 1) * PAGE_SIZE:n * PAGE_SIZE]
        if SITE.unstable and n > 1 and part:
            part = [rows[(n - 1) * PAGE_SIZE - 1]] + part[1:]
        return self._json(200, {"statementData": part, "totalItems": str(len(rows))})

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
    return "http://%s:%d%s" % (HOST, server, path)


@pytest.fixture(autouse=True)
def fake_cetera(server, monkeypatch):
    """The client portal is the made-up site, on plain http."""
    SITE.reset()
    site._RUN.clear()
    base = address(server, "")
    page = address(server, site.DOCUMENTS_PATH)
    monkeypatch.setattr(site, "HOST", "%s:%d" % (HOST, server))
    monkeypatch.setattr(site, "BASE", base)
    monkeypatch.setattr(site, "API", base + site.API_PATH)
    monkeypatch.setattr(site, "QPR_LIST_URL", base + site.QPR_LIST_PATH + "?quarter=all&year=all")
    for name in ("DOCUMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, page)
    for name in ("home", "login", "documents", "statements"):
        monkeypatch.setitem(site.URLS, name, page)
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == HOST)
    # The app's own check of a download address, path, id and query, on
    # the made-up host and its port.
    real = site.is_download_url
    monkeypatch.setattr(site, "is_download_url",
                        lambda url: urlsplit(url or "").hostname == HOST
                        and real(url.replace("http://", "https://", 1)))
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run(tmp_path, cdp_url, capsys, *command):
    try:
        ended = ("returned", app_mod.main([*command, "--config", str(config_for(tmp_path, cdp_url))]))
    except SystemExit as e:
        ended = ("exit", e.code)
    return ended, capsys.readouterr().out


def folded(out):
    return " ".join(out.split())


def panel_reads(out):
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def discovered(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(r["document_id"] for r in found.values())


def saved(tmp_path):
    return sorted(p.read_bytes() for p in (tmp_path / "out").rglob("*.pdf"))


def listing_note(tmp_path):
    return json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))


def lists_read():
    """The readings of the statement list the app asked, every quarter."""
    return sum(1 for s in SITE.seen if s[:2] == ("POST", site.LIST_PATH) and s[2] == "pageNum=1"
               and s[3] == "All")


def page_loads():
    return sum(1 for s in SITE.seen if s[:2] == ("GET", site.DOCUMENTS_PATH))


def their_tab(attached, server):
    theirs = testkit.open_tab(attached, address(server, site.DOCUMENTS_PATH), "Statements & Notices")
    testkit.keep_only(attached, {theirs})


LISTED = sorted(["statement-3141-20260930", "statement-2718-20260930", "statement-3141-20260831",
                 "qpr-50000002", "qpr-50000001"])


def test_both_lists_are_read_once_and_every_document_saved(attached, server, tmp_path, capsys):
    """The statements are walked over two pages and the reports read by the
    in-page list script with the page's own two headers, once for the whole
    run, and each PDF is asked by the in-page PDF script, a report with its
    accountId header."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert saved(tmp_path) == sorted(PDFS.values()), folded(out)
    assert lists_read() == 1 and page_loads() == 1, SITE.seen
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert SITE.token not in out and SESSION not in out


def test_an_empty_history_stops_discover(attached, server, tmp_path, capsys):
    SITE.statements, SITE.reports = [], []
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "holds no statements" in folded(out), folded(out)
    assert "Discovery complete" not in out
    assert listing_note(tmp_path)["complete"] is False


def test_a_report_whose_isria_is_not_true_or_false_stops_discover(attached, server, tmp_path, capsys):
    SITE.is_ria = "Y"
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "isRia" in folded(out), folded(out)


@pytest.mark.parametrize("instead", ["json", "html"])
def test_a_document_answered_with_no_pdf_fails_alone_and_the_older_ones_are_saved(
        attached, server, tmp_path, capsys, instead):
    """The newest statement is answered 200 with JSON or a page. It fails
    alone, the run goes on to the older ones, and the next run tries it
    again rather than stopping there for good."""
    newest = _sid(*STATEMENTS[0])
    SITE.instead = {newest: instead}
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)
    assert saved(tmp_path) == sorted(v for k, v in PDFS.items() if k != newest), folded(out)

    SITE.instead = {}
    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")
    assert saved(tmp_path) == sorted(PDFS.values()), folded(out)


def test_a_page_that_repeats_a_row_and_drops_another_stops_discover(attached, server, tmp_path, capsys):
    """Page two gives page one's last statement again in place of its own,
    so the count still comes to totalItems. The list stops rather than be
    called whole without the statement it left out."""
    SITE.unstable = True
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "two statements carry one id" in folded(out), folded(out)
    assert "Discovery complete" not in out
    assert listing_note(tmp_path)["complete"] is False


def test_one_document_refused_while_the_lists_answer_fails_alone(attached, server, tmp_path, capsys):
    """The portal refuses the newest statement's PDF with a 403, fresh
    headers and all, while both lists still answer. That document fails
    alone and every other is saved, where the run stopped there as signed
    out on every run for good."""
    newest = _sid(*STATEMENTS[0])
    SITE.instead = {newest: "refused"}
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)
    assert saved(tmp_path) == sorted(v for k, v in PDFS.items() if k != newest), folded(out)
    assert panel_reads(out)["stopped"] == 0, folded(out)


def test_headers_that_ran_out_are_taken_again_once(attached, server, tmp_path, capsys):
    """The page's token changes after Discover read the list, as a token
    that runs out does. The first PDF asked with the kept headers is
    refused, the page is opened again for its new ones, and every document
    is saved."""
    their_tab(attached, server)
    run(tmp_path, attached, capsys, "--discover")
    SITE.token = "Bearer fake-browser-token-1111"

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert saved(tmp_path) == sorted(PDFS.values()), folded(out)


def test_a_session_that_ends_stops_the_run_once(attached, server, tmp_path, capsys):
    """Every request of the page is refused once Discover has read the
    list, the page's own included."""
    their_tab(attached, server)
    run(tmp_path, attached, capsys, "--discover")
    SITE.token = "Bearer fake-browser-token-1111"

    def refuse_everything(self):
        return False
    original = _Handler._signed_in
    _Handler._signed_in = refuse_everything
    try:
        ended, out = run(tmp_path, attached, capsys, "--resume")
    finally:
        _Handler._signed_in = original

    assert "answered as signed out" in folded(out), folded(out)
    assert "Nothing was saved" not in out, folded(out)
    assert saved(tmp_path) == []


def test_two_statements_of_one_account_and_date_are_left_and_the_rest_saved(
        attached, server, tmp_path, capsys):
    """A corrected statement beside the first, same account and date.
    Neither is fetched, Discover names the date, and every other document
    is listed and saved."""
    SITE.statements = STATEMENTS + [("XXXX-3141", "09/30/2026", "corrected")]
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "2026-09-30" in folded(out) and "told apart" in folded(out), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    left = _sid(*STATEMENTS[0])
    assert saved(tmp_path) == sorted(v for k, v in PDFS.items() if k != left), folded(out)


@pytest.mark.parametrize("change", ["empty", "500"])
def test_a_list_that_stops_during_resume_stops_once(attached, server, tmp_path, capsys, change):
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--discover")
    assert discovered(tmp_path) == LISTED, folded(out)
    if change == "empty":
        SITE.statements = []
    else:
        SITE.list_status = 500
    SITE.seen.clear()
    site._RUN.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert "could not be read again" in folded(out), folded(out)
    assert "Nothing was saved" not in out, folded(out)
    assert saved(tmp_path) == []
    assert listing_note(tmp_path)["complete"] is False
    assert "then Resume" not in folded(out), folded(out)


def test_diagnose_reads_the_page_and_writes_its_file(attached, server, tmp_path, capsys):
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--diagnose")

    found = json.loads((tmp_path / "out" / "diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert "error" not in found, found.get("error")
    assert len(found["documents_recognized"]) == len(LISTED), found
    assert found["rows_collected"] >= 1, found
    assert SITE.token not in json.dumps(found) and SESSION not in json.dumps(found)
