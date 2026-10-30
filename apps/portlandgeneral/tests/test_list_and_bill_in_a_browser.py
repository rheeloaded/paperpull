"""Billing & Payment History's list and a bill's PDF, asked in a real browser
by the two scripts the site layer runs inside the page.

The unit tests answer those scripts themselves, so with either script
replaced by a syntax error every one of them still passed. Here the page
and the account API are made-up sites on this machine. The page asks the
API for getAccountInfo and the first page of getAccountDetails the way
portlandgeneral.com does, with an authorization header of its own, and
the API answers the list two rows a page, issuing every bill id afresh
with each answer, and a bill's PDF only for an id it issued and only with
the page's own headers.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every other host name fails to resolve, so nothing
reaches Portland General Electric. Every account number, id, date and
amount is invented.
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
import portlandgeneral_docs as app_mod
import portlandgeneral_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

PAGE_HOST = "portlandgeneral.test"
API_HOST = "api.portlandgeneral.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (PAGE_HOST, API_HOST))

TOKEN = "Bearer fake-browser-token-0000"
ACCOUNT = "9876500012"
PAGE_SIZE = 2

# The history, newest first, as (type, date): three bills and two payments,
# so the walk takes three pages.
HISTORY = [("Bill", "2026-09-30"), ("Payment", "2026-09-20"), ("Bill", "2026-08-31"),
           ("Payment", "2026-08-20"), ("Bill", "2026-07-31")]
BILL_DATES = [day for kind, day in HISTORY if kind == "Bill"]
PDFS = {day: testkit.text_pdf([f"Portland General Electric test bill {day}"]) for day in BILL_DATES}

# The page asks what the live page asks on load, from its own script.
BILLING_HISTORY = """<!doctype html><html><head><title>Billing & Payment History</title></head>
<body><main><h1>Billing &amp; Payment History</h1><div id="rows"></div></main>
<script>
const api = %(api)s;
const headers = {"content-type": "application/json", "authorization": %(token)s,
                 "aws_graphql_server": "test"};
function ask(body) {
  return fetch(api + "/pge-graphql", {method: "POST", headers: headers, body: JSON.stringify(body)})
    .then(r => r.json());
}
ask({operationName: "getAccountInfo", variables: {params: {}},
     query: "query getAccountInfo($params: AccountInfoParams) { getAccountInfo { accountMeta { totalAccounts } } }"})
  .then(() => ask({operationName: "getAccountDetails",
                   variables: {params: {accountNumberList: [{accountNumber: %(account)s}]},
                               paymentHistoryParams: {pagingParams: {limit: %(size)d, offset: 0}}},
                   query: "query getAccountDetails($params: AccountDetailParams) { getAccountDetails { x } }"}))
  .then(a => { document.getElementById("rows").textContent =
                 a.data.getAccountDetails[0].paymentHistory.paymentHistoryDetails.length + " rows"; });
</script></body></html>"""


class FakePge:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, host, path).
        self.seen = []
        # Every bill id issued, to the date of its bill.
        self.issued = {}
        self.answers = 0
        # A row type the history holds besides Bill and Payment, if any.
        self.extra_type = ""
        self.accounts = 1


SITE = FakePge()


def _row(n, kind, day):
    ref = ""
    if kind == "Bill":
        ref = "enc+%d/%d=" % (SITE.answers, n)
        SITE.issued[ref] = day
    return {"date": day + "T00:00:00.000Z", "amountDue": 50.0 if kind == "Bill" else 0,
            "amountPaid": 50.0 if kind == "Payment" else 0, "encryptedBillId": ref,
            "billingPeriodStartDate": "", "billingPeriodEndDate": "", "kwh": 400 + n,
            "type": kind, "__typename": "PaymentHistoryDetail"}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype, cors=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.send_header("Access-Control-Allow-Headers", "authorization, aws_graphql_server, content-type")
            self.send_header("Access-Control-Allow-Methods", "POST")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, value):
        self._send(status, json.dumps(value).encode(), "application/json", cors=True)

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def do_GET(self):
        path = urlsplit(self.path).path
        SITE.seen.append(("GET", self._host(), path))
        if self._host() == PAGE_HOST and path == site.DOCUMENTS_PATH:
            html = BILLING_HISTORY % {"api": json.dumps(site.API), "token": json.dumps(TOKEN),
                                      "account": json.dumps(ACCOUNT), "size": PAGE_SIZE}
            self._send(200, html.encode(), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        SITE.seen.append(("OPTIONS", self._host(), urlsplit(self.path).path))
        self._send(204, b"", "text/plain", cors=True)

    def do_POST(self):
        path = urlsplit(self.path).path
        SITE.seen.append(("POST", self._host(), path))
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self._host() != API_HOST:
            return self.send_error(404)
        if self.headers.get("authorization") != TOKEN or not self.headers.get("aws_graphql_server"):
            return self._json(401, {"message": "Unauthorized"})
        if path == "/pge-graphql" and body.get("operationName") == "getAccountInfo":
            return self._json(200, {"data": {"getAccountInfo": {"accountMeta": {
                "totalAccounts": SITE.accounts, "hasInactiveAccounts": False}}}})
        if path == "/pge-graphql" and body.get("operationName") == "getAccountDetails":
            paging = body["variables"]["paymentHistoryParams"]["pagingParams"]
            history = HISTORY + ([(SITE.extra_type, "2026-07-15")] if SITE.extra_type else [])
            SITE.answers += 1
            rows = [_row(n, kind, day) for n, (kind, day)
                    in enumerate(history[paging["offset"]:paging["offset"] + paging["limit"]])]
            return self._json(200, {"data": {"getAccountDetails": [{
                "accountNumber": ACCOUNT, "mainCustomerName": "Example, Dana",
                "paymentHistory": {"paymentHistoryDetails": rows,
                                   "totalDetailsRecords": len(history)}}]}})
        if path == "/pge-bill-api/pdf/bills":
            day = SITE.issued.get(body.get("encryptedBillId"))
            if not day or body.get("isSummary") is not False or body.get("isNonDetailed") is not False:
                return self._json(400, {"message": "no such bill"})
            return self._send(200, PDFS[day], "application/pdf", cors=True)
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
def fake_pge(server, monkeypatch):
    """portlandgeneral.com and its account API are the made-up sites, on
    plain http."""
    SITE.reset()
    site._RUN.clear()
    documents = address(server, PAGE_HOST, site.DOCUMENTS_PATH)
    api = address(server, API_HOST, "")
    for name in ("DOCUMENTS_URL", "STATEMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, documents)
    monkeypatch.setattr(site, "BASE", address(server, PAGE_HOST, ""))
    for name in ("home", "login", "documents", "statements"):
        monkeypatch.setitem(site.URLS, name, documents)
    monkeypatch.setattr(site, "API", api)
    monkeypatch.setattr(site, "GRAPHQL_URL", api + "/pge-graphql")
    monkeypatch.setattr(site, "PDF_URL", api + site.DOWNLOAD_PATH)
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (PAGE_HOST, API_HOST))
    monkeypatch.setattr(site, "is_download_url", lambda url: url == api + site.DOWNLOAD_PATH)
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
    return sorted((r["document_id"], r["date"]) for r in found.values())


def page_loads():
    return sum(1 for s in SITE.seen if s == ("GET", PAGE_HOST, site.DOCUMENTS_PATH))


def their_tab(attached, server):
    """The person's own tab on the site, the one at home they signed in
    with."""
    theirs = testkit.open_tab(attached, address(server, PAGE_HOST, site.DOCUMENTS_PATH),
                              "Billing & Payment History")
    testkit.keep_only(attached, {theirs})


LISTED = sorted((f"bill-0012-{day}", day) for day in BILL_DATES)


def test_every_page_is_listed_and_every_bill_saved_from_one_reading(attached, server, tmp_path,
                                                                    capsys):
    """The list is walked over three pages by the in-page list script, with
    the page's own headers, and each bill's PDF is asked by the in-page PDF
    script with an id from that one reading. Each saved file is the PDF the
    API gave for that date, and the page is not loaded once a bill."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    asked = [s for s in SITE.seen if s[0] == "POST" and s[2] == "/pge-graphql"]
    # getAccountInfo and the first page from the page itself, then pages
    # two and three from the app, on each reading.
    assert len(asked) % 4 == 0 and asked, SITE.seen
    readings = len(asked) // 4
    assert readings == page_loads(), SITE.seen
    assert readings < len(BILL_DATES), "the list was read again for every bill, %s" % SITE.seen
    saved = sorted((tmp_path / "out").rglob("*.pdf"))
    assert sorted(p.read_bytes() for p in saved) == sorted(PDFS.values()), folded(out)
    assert sum(1 for s in SITE.seen if s[2] == "/pge-bill-api/pdf/bills" and s[0] == "POST") == 3
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert TOKEN not in out and "fake-browser-token" not in out


def test_a_row_of_an_unknown_type_stops_discover_and_names_it(attached, server, tmp_path, capsys):
    """A row of type Rebill on the last page. It was passed over in silence;
    the list now stops on it, keeping the bills read before it."""
    SITE.extra_type = "Rebill"
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "'Rebill'" in out and "stopped partway" in out, folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)


def test_discover_says_when_the_sign_in_holds_other_accounts(attached, server, tmp_path, capsys):
    SITE.accounts = 3
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended[1] in (0, None), folded(out)
    assert "holds 2 other account(s)" in folded(out), folded(out)
    assert discovered(tmp_path) == LISTED
