"""Bill & payment history's own answer and a bill's PDF, asked in a real
browser by the script the site layer runs inside the page.

The unit tests answer that script themselves, so with it replaced by a
syntax error every one of them still passed. Here the history page and its
API are a made-up site on this machine. The page asks for its bill history
the way verizon.com does, with a channelId header of its own, and the site
answers a bill's PDF only for a cycle it listed, only with that channel and
the session's cookie.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every other host name fails to resolve, so nothing
reaches Verizon. Every account number, date and amount is invented.
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
import verizonmobile_docs as app_mod
import verizonmobile_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HOST = "www.verizon.test"
HOSTS = "--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" % HOST

CHANNEL = "VZW-TEST-CHANNEL"
COOKIE = "vz_made_up_session"
ACCOUNTS = {"A": "9876543210-00001", "B": "1234567890-00001"}
ENDS = ["10/11/2026", "09/11/2026", "08/11/2026"]
# One bill of about 100 KB, so the PDF script builds its base64 from more
# than one 32 KB piece.
PDFS = {(who, end): testkit.text_pdf([f"Verizon Mobile test bill {who} {end}"],
                                     min_bytes=100_000 if end == ENDS[0] else 4000)
        for who in ACCOUNTS for end in ENDS}

# The page asks what the live page asks on load, from its own script, with
# headers of its own.
HISTORY_PAGE = """<!doctype html><html><head><title>Bill &amp; payment history</title></head>
<body><main><h1>Bill &amp; payment history</h1><div id="rows"></div></main>
<script>
fetch(%(api)s, {headers: {"channelId": %(channel)s, "session_id": "made-up"}})
  .then(r => r.json())
  .then(a => { document.getElementById("rows").textContent =
                 a.body.billingHistory.billCycle.length + " bills"; });
</script></body></html>"""


class FakeVerizon:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, path).
        self.seen = []
        # The account the session shows.
        self.shown = "A"
        # Whether the session has ended, and whether it ends at the first
        # bill's PDF.
        self.signed_out = False
        self.signs_out_at_a_bill = False


SITE = FakeVerizon()


def history_answer():
    return {"responseInfo": {"responseCode": "00", "sectionErrors": []},
            "body": {"billingHistory": {
                "billCycle": [{"billEndDate": end, "billAmount": "$10.00",
                               "cta": [{"label": "Review bill"}, {"label": "Review bill PDF"}]}
                              for end in ENDS],
                "address": {"accountName": "Example Dana", "accountNumber": ACCOUNTS[SITE.shown],
                            "state": "OR"}}}}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype, cookie=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", "%s=1; Path=/" % COOKIE)
        self.end_headers()
        self.wfile.write(data)

    def _to_sign_in(self):
        self.send_response(302)
        self.send_header("Location", "/signin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(("GET", parts.path))
        if parts.path == "/signin":
            return self._send(200, b"<!doctype html><title>Sign in</title><input type=password>",
                              "text/html; charset=utf-8")
        if SITE.signed_out:
            return self._to_sign_in()
        if parts.path == site.HISTORY_PATH:
            html = HISTORY_PAGE % {"api": json.dumps(site.HISTORY_API_PATH),
                                   "channel": json.dumps(CHANNEL)}
            return self._send(200, html.encode(), "text/html; charset=utf-8", cookie=True)
        if COOKIE not in (self.headers.get("Cookie") or ""):
            return self._to_sign_in()
        if parts.path == site.HISTORY_API_PATH:
            if self.headers.get("channelId") != CHANNEL:
                return self._send(400, b"{}", "application/json")
            return self._send(200, json.dumps(history_answer()).encode(), "application/json")
        if parts.path == site.PDF_PATH:
            if SITE.signs_out_at_a_bill:
                SITE.signed_out = True
                return self._to_sign_in()
            q = parse_qs(parts.query)
            end = (q.get("startMonthDate") or [""])[0]
            if set(q) != {"startMonthDate", "channelId"} or q["channelId"] != [CHANNEL] \
                    or end not in ENDS:
                return self._send(400, b'{"error": "no such bill"}', "application/json")
            return self._send(200, PDFS[(SITE.shown, end)], "application/pdf")
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
def fake_verizon(server, monkeypatch):
    """verizon.com is the made-up site, on plain http."""
    SITE.reset()
    history = address(server, site.HISTORY_PATH)
    monkeypatch.setattr(site, "BASE", address(server, ""))
    monkeypatch.setattr(site, "HOST", "%s:%d" % (HOST, server))
    for name in ("HISTORY_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, history)
    for name in ("home", "login", "documents", "statements"):
        monkeypatch.setitem(site.URLS, name, history)
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == HOST)
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


def page_loads():
    return sum(1 for s in SITE.seen if s == ("GET", site.HISTORY_PATH))


def pdf_asks():
    return sum(1 for s in SITE.seen if s == ("GET", site.PDF_PATH))


def their_tab(attached, server):
    """The person's own tab on the site, the one at home they signed in
    with."""
    theirs = testkit.open_tab(attached, address(server, site.HISTORY_PATH),
                              "Bill & payment history")
    testkit.keep_only(attached, {theirs})


def test_every_bill_is_listed_and_saved_by_the_page_script(attached, server, tmp_path, capsys):
    """The list is the page's own answer, and each bill's PDF is asked by
    the in-page script with the page's channel and the session's cookie.
    Each saved file is the PDF the site gave for that cycle, and the
    history is read once for Discover and once a bill."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    found = json.loads((tmp_path / "out" / "discovery.json").read_text(encoding="utf-8"))
    assert sorted(r["document_id"] for r in found.values()) == [
        "bill-3210-00001-2026-08-11", "bill-3210-00001-2026-09-11", "bill-3210-00001-2026-10-11"]
    saved = sorted((tmp_path / "out").rglob("*.pdf"))
    assert sorted(p.read_bytes() for p in saved) == sorted(PDFS[("A", end)] for end in ENDS), folded(out)
    assert pdf_asks() == len(ENDS) and page_loads() == 1 + len(ENDS), SITE.seen
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert CHANNEL not in out and ACCOUNTS["A"] not in out


def test_a_sign_out_at_a_bill_stops_the_run_once(attached, server, tmp_path, capsys):
    """The first bill's PDF is answered with the sign-in page's redirect,
    and the history read again shows the sign-in. The run stops there with
    nothing sent to review, where each bill used to go to review in turn."""
    their_tab(attached, server)
    SITE.signs_out_at_a_bill = True
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    result = panel_reads(out)
    assert pdf_asks() == 1, SITE.seen
    assert result["stopped"] == 1 and result["manual_review"] + result["failed"] == 0, folded(out)
    assert "signed out" in folded(out)
    assert not list((tmp_path / "out").rglob("*.pdf"))


def test_another_account_shown_is_asked_for_no_bill(attached, server, tmp_path, capsys):
    """Discover on account A, then My Verizon shows account B. Its PDF
    address names no account, so asking it would save B's bill under A's
    record. The run stops before asking, and names both accounts."""
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--discover")
    assert ended[1] in (0, None), folded(out)
    SITE.shown = "B"
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert pdf_asks() == 0, SITE.seen
    assert "account ending 7890-00001" in folded(out) and "ending 3210-00001" in folded(out)
    assert panel_reads(out)["stopped"] == 1
    assert not list((tmp_path / "out").rglob("*.pdf"))
