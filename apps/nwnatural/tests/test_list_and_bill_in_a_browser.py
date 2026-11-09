"""Bill History and a bill's PDF, read in a real browser by the three
scripts the site layer runs inside the portal page.

The unit tests answer those scripts themselves, so with any of them
replaced by a syntax error every one of them still passed. Here the
portal is a made-up site on this machine. Its home page links to Bill
History the way the Paymentus portal does, with a CSRF token, and sets the
session cookie. Bill History draws the Account | Due Amount | Due Date |
Action table with padding rows and a View link per bill, and answers only
with that cookie, that token and an early dateFrom. A bill's View address
answers its PDF only with the cookie and the token.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every other host name fails to resolve, so nothing
reaches NW Natural or Paymentus. Every account number, token, date and
amount is invented.
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
import nwnatural_docs as app_mod
import nwnatural_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

PORTAL = "ipn2.paymentus.test"
MAIN = "www.nwnatural.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (PORTAL, MAIN))

TOKEN = "0000000000000-fake00"
COOKIE = "PPSESSION=fake-browser-session"
ACCOUNT = "9876543-2"
OTHER = "1234567-8"

# Newest first, as (due date as the table writes it, ISO).
BILLS = [("Oct 21, 2026", "2026-10-21"), ("Sep 22, 2026", "2026-09-22"), ("Aug 21, 2026", "2026-08-21")]
# One bill of about 100 KB, so the PDF script builds its base64 from more
# than one 32 KB piece.
PDFS = {iso: testkit.text_pdf([f"NW Natural test bill {iso}"],
                              min_bytes=100_000 if iso == BILLS[0][1] else 4000)
        for _, iso in BILLS}

HOME = """<!doctype html><html><head><title>Paymentus</title></head><body><main>
<h1>Welcome</h1><a href="/cp/bills.action?CSRF_TOKEN=%(token)s&amp;dateFrom.day=&amp;dateFrom.month=&amp;dateFrom.year=">Bill History</a>
</main></body></html>"""

# A pager the live table might draw for one page: every control disabled
# or the first page. It must not read as more pages.
ONE_PAGE_PAGER = """<div class="dataTables_paginate"><a class="paginate_button previous disabled">Previous</a>
<span><a class="paginate_button current">1</a></span><a class="paginate_button next disabled">Next</a></div>"""
MORE_PAGES_PAGER = """<div class="dataTables_paginate"><a class="paginate_button previous disabled">Previous</a>
<span><a class="paginate_button current">1</a><a class="paginate_button">2</a></span>
<a class="paginate_button next">Next</a></div>"""
# "Page 1 of 3" in an element of its own, touching the text before it,
# outside any pager box.
PAGE_LINE = """<div><a href="#">Next</a><span>Page 1 of 3</span></div>"""


class FakePortal:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (method, host, path).
        self.seen = []
        # Every document reference issued, to its bill's date.
        self.issued = {}
        self.empty = False
        self.second_account = False
        self.pager = ONE_PAGE_PAGER
        # What a bill's View address answers in place of its PDF:
        # "redirect", "datadome", or "html" for the bill dated html_for.
        self.instead = ""
        self.html_for = ""
        # What Bill History answers in place of its table: "datadome" or "500".
        self.list_instead = ""
        # The session ends once Bill History has been read this many times.
        self.lists_until_signed_out = None
        # A second bill on the first bill's due date, as a reissue would be.
        self.reissue = False


SITE = FakePortal()


def _bill_rows():
    rows = []
    bills = [] if SITE.empty else list(BILLS)
    if SITE.reissue and bills:
        bills.append(bills[0])
    for n, (shown, iso) in enumerate(bills):
        ref = "000000000%d/00000" % n
        SITE.issued[ref] = iso
        account = OTHER if SITE.second_account and n == 2 else ACCOUNT
        href = ("/cp/view-external-bill.action?&CSRF_TOKEN=%s&accountId=1&accthid=x&accountNumber=%s"
                "&docRef=%s&hashedDocRef=h%d&target=_blank" % (TOKEN, account, ref, n))
        rows.append("<tr><td>%s</td><td>$40.00</td><td>%s</td><td><a href=\"%s\">View</a></td></tr>"
                    % (account, shown, href.replace("&", "&amp;")))
    # The padding rows the live table draws.
    rows += ["<tr><td></td><td></td><td></td><td></td></tr>"] * 4
    return "".join(rows)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, data, ctype, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _html(self, html, headers=()):
        self._send(200, html.encode(), "text/html; charset=utf-8", headers)

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def do_GET(self):
        parts = urlsplit(self.path)
        q = parse_qs(parts.query, keep_blank_values=True)
        SITE.seen.append(("GET", self._host(), parts.path))
        if self._host() == MAIN:
            return self._html("<!doctype html><title>NW Natural</title><h1>My Account</h1>")
        if self._host() != PORTAL:
            return self.send_error(404)
        if parts.path == "/cp/home.action":
            return self._html(HOME % {"token": TOKEN}, [("Set-Cookie", COOKIE + "; Path=/cp")])
        signed_in = COOKIE in (self.headers.get("Cookie") or "") and q.get("CSRF_TOKEN") == [TOKEN]
        if not signed_in:
            return self._send(403, b"forbidden", "text/plain")
        until = SITE.lists_until_signed_out
        before = sum(1 for s in SITE.seen[:-1] if s[2] == "/cp/bills.action")
        if until is not None and before >= until:
            return self._redirect()
        if parts.path == "/cp/bills.action":
            if q.get("dateFrom.year") != ["2000"]:
                return self.send_error(400)
            if SITE.list_instead == "datadome":
                return self._datadome()
            if SITE.list_instead == "500":
                return self._send(500, b"error", "text/plain")
            return self._html("""<!doctype html><title>Bill History</title><h2>Bill History</h2>
<table><thead><tr><th>Account</th><th>Due Amount</th><th>Due Date</th><th>Action</th></tr></thead>
<tbody>%s</tbody></table>%s""" % (_bill_rows(), SITE.pager))
        if parts.path == "/cp/view-external-bill.action":
            iso = SITE.issued.get((q.get("docRef") or [""])[0])
            if not iso:
                return self.send_error(404)
            if SITE.instead == "redirect":
                return self._redirect()
            if SITE.instead == "datadome":
                return self._datadome()
            if SITE.instead == "refused":
                return self._send(403, b"forbidden", "text/plain")
            if SITE.instead == "html" and iso == SITE.html_for:
                return self._html("<!doctype html><title>Error</title><p>Something went wrong.</p>")
            return self._send(200, PDFS[iso], "application/pdf")
        self.send_error(404)

    def _redirect(self):
        self.send_response(302)
        self.send_header("Location", "/cp/login")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _datadome(self):
        self._send(403, b'{"url":"https://geo.captcha-delivery.test/captcha/"}',
                   "application/json", [("X-DataDome", "protected")])

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
def fake_portal(server, monkeypatch):
    """The Paymentus portal and nwnatural.com are the made-up sites, on
    plain http, and the portal host is the made-up one with its port."""
    SITE.reset()
    site._RUN.clear()
    monkeypatch.setattr(site, "PORTAL_HOST", "%s:%d" % (PORTAL, server))
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (PORTAL, MAIN))
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


def discovered(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(r["document_id"] for r in found.values())


def saved(tmp_path):
    return sorted(p.read_bytes() for p in (tmp_path / "out" / "Statements").rglob("*.pdf")) \
        if (tmp_path / "out" / "Statements").exists() else []


def lists_read():
    return sum(1 for s in SITE.seen if s == ("GET", PORTAL, "/cp/bills.action"))


def listing_note(tmp_path):
    return json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))


def their_tab(attached, server, host=PORTAL, path="/cp/home.action?CSRF_TOKEN=" + TOKEN,
              title="Paymentus"):
    """The person's own tab, the one at home they signed in with."""
    theirs = testkit.open_tab(attached, address(server, host, path), title)
    testkit.keep_only(attached, {theirs})


LISTED = sorted(f"bill-{iso}" for _, iso in BILLS)


def test_the_list_is_read_once_and_every_bill_saved(attached, server, tmp_path, capsys):
    """Bill History is read by the list script with the portal's cookie and
    token, past its padding rows and a pager showing one page, and each
    bill's PDF by the PDF script from its View address. The list is read
    once for the whole run."""
    their_tab(attached, server)
    SITE.seen.clear()

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert ended[1] in (0, None), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert saved(tmp_path) == sorted(PDFS.values()), folded(out)
    assert lists_read() == 1, SITE.seen
    assert TOKEN not in out and ACCOUNT not in out


def test_a_table_with_no_bills_stops_discover(attached, server, tmp_path, capsys):
    SITE.empty = True
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "shows no bills" in folded(out), folded(out)
    assert "Discovery complete" not in out


def test_a_pager_offering_another_page_stops_discover(attached, server, tmp_path, capsys):
    SITE.pager = MORE_PAGES_PAGER
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "shows a pager" in folded(out), folded(out)


def test_two_accounts_stop_discover_and_list_nothing(attached, server, tmp_path, capsys):
    SITE.second_account = True
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "lists the bills of 2 accounts" in folded(out), folded(out)
    assert discovered(tmp_path) == []


def test_an_html_answer_fails_that_bill_and_the_rest_are_saved(attached, server, tmp_path, capsys):
    SITE.instead, SITE.html_for = "html", BILLS[1][1]
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert saved(tmp_path) == sorted(PDFS[iso] for _, iso in BILLS if iso != BILLS[1][1]), folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)


@pytest.mark.parametrize("instead, said", [("signed out", "answered as signed out"),
                                           ("datadome", "asked to check the browser")])
def test_a_session_that_ends_or_the_bot_protection_stops_the_run_once(attached, server, tmp_path,
                                                                     capsys, instead, said):
    """A session that ends after Discover: the bill is redirected, and so is
    the list read again for it."""
    if instead == "signed out":
        SITE.lists_until_signed_out = 1
    else:
        SITE.instead = instead
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert said in folded(out), folded(out)
    assert "manual review" not in out.lower(), folded(out)
    assert saved(tmp_path) == []
    assert not any(s[2] == "/cp/login" for s in SITE.seen), SITE.seen


def test_a_tab_on_nwnatural_com_stops_once(attached, server, tmp_path, capsys):
    """The portal session timed out back to the main site."""
    their_tab(attached, server, MAIN, "/account", "NW Natural")

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert "not its payment portal" in folded(out), folded(out)
    assert not any(s[1] == PORTAL for s in SITE.seen), SITE.seen


def test_login_says_to_answer_the_bot_protection(attached, server, tmp_path, capsys):
    SITE.list_instead = "datadome"
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--login")

    assert "asked to check the browser" in folded(out), folded(out)
    assert "re-run --login" in folded(out), folded(out)
    assert "Success" not in out


def test_bills_refused_right_after_the_list_answered_fail_alone(attached, server, tmp_path, capsys):
    """The list answers, so the session works, and every bill is refused.
    Each fails alone and the run goes on, so a Resume never loops on the
    first."""
    SITE.instead = "refused"
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert "signed out" not in out, folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == len(BILLS), folded(out)
    assert saved(tmp_path) == []


@pytest.mark.parametrize("change", ["second account", "empty", "500"])
def test_a_list_that_stops_during_resume_stops_once(attached, server, tmp_path, capsys, change):
    """Discover read the whole list. Resume reads none of its own, so the
    first bill reads it, and when it stops the run stops there."""
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--discover")
    assert discovered(tmp_path) == LISTED, folded(out)
    SITE.second_account = change == "second account"
    SITE.empty = change == "empty"
    SITE.list_instead = "500" if change == "500" else ""
    SITE.seen.clear()
    site._RUN.clear()

    ended, out = run(tmp_path, attached, capsys, "--resume")

    assert "stopped while bills were being fetched" in folded(out), folded(out)
    assert "marked for manual review" not in out, folded(out)
    assert lists_read() == 1, SITE.seen
    assert saved(tmp_path) == []
    # A second Resume would read the same list and stop at the same bill
    # (#124), so the list is noted as one that stopped and the run says to
    # use a run that lists first, never to carry on from here.
    assert listing_note(tmp_path)["complete"] is False
    assert "reads the list first" in folded(out) or "read the list first" in folded(out), folded(out)
    assert "then Resume" not in folded(out), folded(out)


def test_page_n_of_m_touching_the_text_before_it_stops_discover(attached, server, tmp_path, capsys):
    SITE.pager = PAGE_LINE
    their_tab(attached, server)

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert ended == ("exit", 1), folded(out)
    assert "shows a pager" in folded(out), folded(out)


def test_the_portal_tab_is_taken_over_a_main_site_tab_naming_the_portal(attached, server, tmp_path,
                                                                        capsys):
    main = testkit.open_tab(attached, address(server, MAIN, "/account?next=%s:%d" % (PORTAL, server)),
                            "NW Natural")
    portal = testkit.open_tab(attached, address(server, PORTAL, "/cp/home.action?CSRF_TOKEN=" + TOKEN),
                              "Paymentus")
    testkit.keep_only(attached, {main, portal})

    ended, out = run(tmp_path, attached, capsys, "--discover")

    assert "Discovery complete" in out, folded(out)
    assert discovered(tmp_path) == LISTED


def test_a_reissued_bill_is_named_for_what_happens(attached, server, tmp_path, capsys):
    """Not yet saved, neither bill of the date is fetched, the date counts
    as failed and the list is read once. Already saved, the saved bill is
    kept and the other not fetched."""
    SITE.reissue = True
    their_tab(attached, server)
    ended, out = run(tmp_path, attached, capsys, "--all", "--yes")
    assert "Neither bill of that date is fetched" in folded(out), folded(out)
    assert out.count("Nothing was saved, and the next run tries it again") == 1, folded(out)
    assert lists_read() == 1, SITE.seen

    later = tmp_path / "later"
    later.mkdir()
    SITE.reset()
    site._RUN.clear()
    their_tab(attached, server)
    run(later, attached, capsys, "--all", "--yes")
    SITE.reissue = True
    ended, out = run(later, attached, capsys, "--discover")
    assert "already saved for that date is kept, and the other is not fetched" in folded(out), \
        folded(out)
