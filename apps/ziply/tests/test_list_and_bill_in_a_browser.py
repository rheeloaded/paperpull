"""Billing's bill list and a bill's PDF, asked in a real browser by the
scripts the site layer runs inside the page.

The unit tests answer those scripts themselves, so with any of them
replaced by a syntax error every one of them still passed. Here My
Account is a made-up site on this machine. Its Billing page asks the
account API, POST /myapi, for billingDetails and then the page's own
billStatements, the way ziplyfiber.com does, with an authorization header
of its own. The API answers the list only with that header and a bill's
PDF only with the session cookie the Billing page set.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every other host name fails to resolve, so nothing
reaches Ziply Fiber. Every account number, invoice id, date and amount is
invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ziply_docs as app_mod
import ziply_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HOST = "ziplyfiber.test"
HOSTS = "--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" % HOST

TOKEN = "Bearer fake-browser-token-0000"
SESSION = "zsess=fake-cookie-0000"
ACCOUNT = "40000000005551"
OTHER = "40000000007772"

# The history, newest first, as (date, invoice id).
BILLS = [("2026-10-13", "70000003"), ("2026-09-13", "70000002"), ("2026-08-13", "70000001")]
# One bill of about 100 KB, so the PDF script builds its base64 from more
# than one 32 KB piece.
PDFS = {inv: testkit.text_pdf([f"Ziply Fiber test bill {day}"],
                              min_bytes=100_000 if inv == BILLS[0][1] else 4000)
        for day, inv in BILLS}

# The page asks what the live page asks on load, from its own script,
# billingDetails for each account it shows and then the Past bills query.
BILLING = """<!doctype html><html><head><title>Billing</title></head>
<body><main><h1>Billing</h1><table><tbody id="bills"></tbody></table></main>
<script>
const headers = {"content-type": "application/json", "authorization": %(token)s,
                 "requestid": "req-test-0001"};
function ask(op, variables) {
  return fetch("/myapi", {method: "POST", headers: headers,
                          body: JSON.stringify({operationName: op, variables: variables,
                                                query: "query " + op + " { x }"})})
    .then(r => r.json());
}
const accounts = %(accounts)s;
Promise.all(accounts.map(a => ask("billingDetails", {accountNumber: a})))
  .then(() => ask("billStatements", {isCurrentBill: false, accountNumber: accounts[0], billsRequired: 5}))
  .then(a => {
    for (const b of (a.data.billStatements.billStatements || [])) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + b.date + "</td><td><a href='" + b.url + "'>View PDF</a></td>";
      document.getElementById("bills").appendChild(tr);
    }
  });
</script></body></html>"""


class FakeZiply:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, path, operation or query).
        self.seen = []
        # The accounts the Billing page asks billingDetails about.
        self.accounts = [ACCOUNT]
        # The list answers with no bills, or with this APIStatus and error.
        self.empty = False
        self.api_status = 200
        self.lists_until_signed_out = -1
        # What a bill's PDF is answered with instead, by invoice id,
        # "json", "html", "redirect" or "403".
        self.instead = {}
        # The session ends as such a bill is asked for, so every list asked
        # after it is refused.
        self.signs_out_at_the_bill = False


SITE = FakeZiply()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype, cookie=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", SESSION + "; Path=/")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, value):
        self._send(status, json.dumps(value).encode(), "application/json")

    def _to_sign_in(self):
        self.send_response(302)
        self.send_header("Location", "/login")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(("GET", parts.path, parts.query))
        if parts.path == site.DOCUMENTS_PATH:
            html = BILLING % {"token": json.dumps(TOKEN), "accounts": json.dumps(SITE.accounts)}
            return self._send(200, html.encode(), "text/html; charset=utf-8", cookie=True)
        if parts.path == "/login":
            return self._send(200, b"<!doctype html><title>Sign in</title><input type=password>",
                              "text/html; charset=utf-8")
        if parts.path == site.DOWNLOAD_PATH:
            inv = (parse_qs(parts.query).get("invoiceId") or [""])[0]
            if SESSION not in (self.headers.get("Cookie") or ""):
                return self._to_sign_in()
            instead = SITE.instead.get(inv)
            if instead and SITE.signs_out_at_the_bill:
                SITE.lists_until_signed_out = 0
            if instead == "json":
                return self._json(200, {"error": True, "message": "Invoice not available"})
            if instead == "html":
                return self._send(200, b"<!doctype html><title>Sign in</title>", "text/html")
            if instead == "redirect":
                return self._to_sign_in()
            if instead == "403":
                return self._json(403, {"message": "Forbidden"})
            if inv not in PDFS:
                return self._json(404, {"message": "no such invoice"})
            return self._send(200, PDFS[inv], "application/pdf")
        self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        op = body.get("operationName")
        SITE.seen.append(("POST", path, op, (body.get("variables") or {}).get("billsRequired")))
        if path != "/myapi":
            return self.send_error(404)
        if self.headers.get("authorization") != TOKEN:
            return self._json(401, {"message": "Unauthorized"})
        if op == "billingDetails":
            return self._json(200, {"data": {"billingDetails": {"accountNumber": body["variables"]["accountNumber"]}}})
        if op == "billStatements":
            if SITE.lists_until_signed_out == 0:
                return self._json(401, {"message": "Unauthorized"})
            SITE.lists_until_signed_out -= 1
            asked = body["variables"]["accountNumber"]
            rows = [] if SITE.empty or asked != SITE.accounts[0] else [
                {"status": "CLOSED", "date": day, "amount_due": "65.00", "id": inv,
                 "url": "http://%s:%d%s?invoiceId=%s" % (HOST, self.server.server_address[1],
                                                         site.DOWNLOAD_PATH, inv),
                 "__typename": "BillStatement"} for day, inv in BILLS]
            rows = rows[:int(body["variables"].get("billsRequired") or 5)]
            return self._json(200, {"data": {"billStatements": {
                "error": False, "APIStatus": SITE.api_status, "message": None,
                "billStatements": rows, "__typename": "BillStatementsResponse"}}})
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


def address(server, path):
    return "http://%s:%d%s" % (HOST, server, path)


@pytest.fixture(autouse=True)
def fake_ziply(server, monkeypatch):
    """ziplyfiber.com is the made-up site, on plain http."""
    SITE.reset()
    site._RUN.clear()
    base = address(server, "")
    billing = address(server, site.DOCUMENTS_PATH)
    monkeypatch.setattr(site, "BASE", base)
    for name in ("DOCUMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, billing)
    for name in ("home", "login", "documents", "statements"):
        monkeypatch.setitem(site.URLS, name, billing)
    monkeypatch.setattr(site, "API_URL", base + "/myapi")
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == HOST)

    def is_download_url(url):
        parts = urlsplit(url or "")
        q = parse_qs(parts.query)
        return (parts.hostname == HOST and parts.path == site.DOWNLOAD_PATH and set(q) == {"invoiceId"}
                and bool(site.INVOICE_ID_RE.fullmatch(q["invoiceId"][0])))
    monkeypatch.setattr(site, "is_download_url", is_download_url)
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
    """A run, as the panel's button starts it. How it ended and what it
    printed."""
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


def lists_asked():
    """The bill lists the app asked, with the 100 bills it asks for."""
    return sum(1 for s in SITE.seen if s[:3] == ("POST", "/myapi", "billStatements")
               and s[3] == site.BILLS_ASKED)


def page_loads():
    return sum(1 for s in SITE.seen if s[:2] == ("GET", site.DOCUMENTS_PATH))


def their_tab(attached, server):
    """The person's own tab on My Account, the one at home they signed in
    with."""
    theirs = testkit.open_tab(attached, address(server, site.DOCUMENTS_PATH), "Billing")
    testkit.keep_only(attached, {theirs})


LISTED = sorted(f"bill-5551-{inv}" for _, inv in BILLS)


def test_every_bill_is_listed_once_and_saved(attached, server, tmp_path, capsys):
    """The list is asked by the in-page list script with the page's own
    headers, once for the whole run, and each bill's PDF by the in-page PDF
    script with the session's cookie. Each saved file is that bill's PDF and
    its name carries the account's last four digits."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert saved(tmp_path) == sorted(PDFS.values()), folded(out)
    assert lists_asked() == 1 and page_loads() == 1, SITE.seen
    names = sorted(p.name for p in (tmp_path / "out").rglob("*.pdf"))
    assert all("Ziply Fiber Internet Bill XXXX-5551" in n for n in names), names
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert TOKEN not in out and "fake-browser-token" not in out and ACCOUNT not in out


def test_login_says_success_only_for_a_list_with_bills(attached, server, tmp_path, capsys):
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--login")
    assert "Success" in out, folded(out)

    SITE.empty = True
    ended, out = run(tmp_path, attached, capsys, "--login")
    assert "Success" not in out, folded(out)


@pytest.mark.parametrize("change, said", [("empty", "holds no bills"), ("500", "status 500"),
                                          ("second account", "asked about 2 accounts")])
def test_a_list_that_cannot_be_read_whole_stops_discover(attached, server, tmp_path, capsys,
                                                          change, said):
    """A list with no bills, one the API answers with an error status, or a
    page that asks about two accounts. Each stops Discover, which lists
    nothing and never calls the list read."""
    SITE.empty = change == "empty"
    SITE.api_status = 500 if change == "500" else 200
    if change == "second account":
        SITE.accounts = [ACCOUNT, OTHER]
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert said in folded(out), folded(out)
    assert "Discovery complete" not in out
    assert discovered(tmp_path) == []
    assert listing_note(tmp_path)["complete"] is False


def test_a_json_answer_fails_that_bill_and_the_rest_are_saved(attached, server, tmp_path, capsys):
    SITE.instead = {BILLS[1][1]: "json"}
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert saved(tmp_path) == sorted(PDFS[inv] for _, inv in BILLS if inv != BILLS[1][1]), folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)


def bill_asks(inv):
    return sum(1 for s in SITE.seen if s[:2] == ("GET", site.DOWNLOAD_PATH) and s[2] == "invoiceId=" + inv)


@pytest.mark.parametrize("instead", ["html", "redirect", "403"])
def test_a_bill_refused_while_the_list_reads_fails_alone(attached, server, tmp_path, capsys, instead):
    """The newest bill is answered with a sign-in page, a redirect to one,
    or a 403, while the session still works. That stopped every run at the
    newest bill as signed out (#124). The list is read again, it still
    reads, so that bill fails alone, asked for once, and the other two are
    saved."""
    SITE.instead = {BILLS[0][1]: instead}
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert saved(tmp_path) == sorted(PDFS[inv] for _, inv in BILLS[1:]), folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)
    assert bill_asks(BILLS[0][1]) == 1, SITE.seen
    assert lists_asked() == 2 and page_loads() == 2, SITE.seen
    assert not any(s[:2] == ("GET", "/login") for s in SITE.seen), SITE.seen
    assert panel_reads(out)["stopped"] == 0, folded(out)
    attempt = (tmp_path / "out" / "Diagnostics" / "download-attempt.json").read_text(encoding="utf-8")
    assert "refused, the list still reads" in attempt
    assert "Sign in" not in attempt and "Forbidden" not in attempt and ACCOUNT not in attempt


@pytest.mark.parametrize("instead", ["html", "redirect"])
def test_a_bill_refused_with_the_list_refused_too_stops_the_run_once(attached, server, tmp_path, capsys,
                                                                     instead):
    """The session ends as the newest bill is asked for, so the list read
    again for it is refused too. The run stops as signed out, saving
    nothing and recording nothing against the bill."""
    SITE.instead = {BILLS[0][1]: instead}
    SITE.signs_out_at_the_bill = True
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "answered as signed out" in folded(out), folded(out)
    assert "manual review" not in out.lower() and "Nothing was saved" not in out, folded(out)
    assert saved(tmp_path) == []
    # Discover's list, then the one read again after the refusal, refused.
    assert bill_asks(BILLS[0][1]) == 1 and lists_asked() == 2, SITE.seen
    assert not any(s[:2] == ("GET", "/login") for s in SITE.seen), SITE.seen


def test_another_account_at_resume_stops_once_and_names_it(attached, server, tmp_path, capsys):
    """Discover listed the account ending 5551. The page now shows another,
    so Resume stops at the first bill, naming the account to choose,
    rather than send every bill to be retried."""
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--discover")
    assert discovered(tmp_path) == LISTED, folded(out)
    SITE.accounts = [OTHER]
    site._RUN.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert "the account ending 7772" in folded(out) and "ending 5551" in folded(out), folded(out)
    assert "Nothing was saved" not in out and "manual review" not in out.lower(), folded(out)
    assert saved(tmp_path) == []
    assert ACCOUNT not in out and OTHER not in out


@pytest.mark.parametrize("change", ["empty", "500", "second account"])
def test_a_list_that_stops_during_resume_stops_once(attached, server, tmp_path, capsys, change):
    """Discover read the whole list. Resume reads none of its own, so the
    first bill reads it, and when it stops the run stops there with the
    list noted as unread."""
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--discover")
    assert discovered(tmp_path) == LISTED, folded(out)
    SITE.empty = change == "empty"
    SITE.api_status = 500 if change == "500" else 200
    if change == "second account":
        SITE.accounts = [ACCOUNT, OTHER]
    SITE.seen.clear()
    site._RUN.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert "could not be read again" in folded(out), folded(out)
    assert "Nothing was saved" not in out, folded(out)
    assert lists_asked() <= 1, SITE.seen
    assert saved(tmp_path) == []
    # A second Resume would read the same list and stop at the same bill
    # (#124), so the list is noted as one that stopped.
    assert listing_note(tmp_path)["complete"] is False
    assert "then Resume" not in folded(out), folded(out)


def test_a_list_refused_while_bills_download_stops_as_signed_out(attached, server, tmp_path, capsys):
    """The session ends after Discover. The list asked again for the first
    bill of a Resume is refused, and the run stops once as signed out."""
    their_tab(attached, server)
    run(tmp_path, attached, capsys, "--discover")
    SITE.lists_until_signed_out = 0
    site._RUN.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert "answered as signed out" in folded(out), folded(out)
    assert saved(tmp_path) == []


def test_diagnose_reads_the_page_and_writes_its_file(attached, server, tmp_path, capsys):
    """Diagnose runs the row script over the page's bill table and the list
    script for the bills it recognizes, and writes its file."""
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--diagnose")

    found = json.loads((tmp_path / "out" / "diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert "error" not in found, found.get("error")
    assert len(found["documents_recognized"]) == len(BILLS), found
    assert found["rows_collected"] == len(BILLS), found
    assert TOKEN not in json.dumps(found) and ACCOUNT not in json.dumps(found)
