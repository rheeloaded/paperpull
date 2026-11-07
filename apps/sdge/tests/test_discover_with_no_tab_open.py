"""Discover with no My Energy Center tab of the person's open, in a real
browser, and Billing History's statement dates read from their own column.

With no tab of the person's on My Energy Center the app works in a new tab
of its own, which shares the session cookie. Discover asked whether that
tab was still on the site before anything had opened Billing History in
it, and a new tab is blank, so Discover, Pilot and Run All stopped at once,
saying the tab had left My Energy Center. Billing History is now opened in
that tab first, and a tab of another site is still never read or loaded.

A bill's date was the first cell of its row that read as a date. With the
Statement Date cell blank, that was the Due Date beside it. The date is now
read only from the column headed Statement Date, and a blank one stops the
list.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. My Energy Center and another site are made-up host
names the browser is told to find on this machine, and every other name
fails to resolve, so nothing reaches SDG&E. Every id, date and amount is
invented.
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
import sdge_docs as app_mod
import sdge_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

MEC_HOST = "myenergycenter.test"
ELSEWHERE_HOST = "www.elsewhere.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (MEC_HOST, ELSEWHERE_HOST))

# Each bill as the table draws it, the invoice id, Statement Date and Due
# Date. The Due Date is a date too, which is what a blank Statement Date
# used to be dated by.
BILLS = [("ISU000000000201", "Sep 12, 2026", "Oct 1, 2026"),
         ("ISU000000000202", "Aug 13, 2026", "Sep 1, 2026"),
         ("ISU000000000203", "Jul 14, 2026", "Oct 14, 2026")]

CONTROL = '<td><a href="#" class="expand">+</a></td>'
ROW = """<tr invoiceid="{inv}">{control}<td>{statement}</td><td>{due}</td>
<td>$12.34</td><td>Billed</td></tr>"""
DUE_FIRST = """<tr invoiceid="{inv}">{control}<td>{due}</td><td>{statement}</td>
<td>$12.34</td><td>Billed</td></tr>"""

BILLING_HISTORY = """<!doctype html><html><head><title>Billing History</title></head><body>
<main><h1>Billing History</h1>
<table id="billHistoryTable"><thead>%(head)s</thead>
<tbody>%(rows)s</tbody></table></main></body></html>"""

ONE_ROW = ("<tr><th></th><th>Statement Date</th><th>Due Date</th><th>Amount Due</th>"
           "<th>Status</th></tr>")


def control_of(n):
    return CONTROL


# The table's header and how each row's control cell is drawn, by the name
# of the shape. The page reads the same in each as a person sees it.
TABLES = {
    "one row": (ONE_ROW, ROW, control_of),
    # The control column's header spans both rows, so Statement Date, under
    # a heading of two columns, is in the second column though it is the
    # first cell of its own row.
    "two rows": ("<tr><th rowspan=\"2\"></th><th colspan=\"2\">Dates</th>"
                 "<th rowspan=\"2\">Amount Due</th><th rowspan=\"2\">Status</th></tr>"
                 "<tr><th>Statement Date</th><th>Due Date</th></tr>", ROW, control_of),
    # Each row's control cell is a header cell of its row.
    "row headers": (ONE_ROW, ROW, lambda n: '<th><a href="#" class="expand">+</a></th>'),
    # A header cell of rowspan 0 spans every header row, but its height
    # reads as 0. Counted as one row, the second row's Due Date would sit
    # in the Statement Date column, and every bill would take its Due Date.
    "rowspan zero": ("<tr><th rowspan=\"0\"></th><th colspan=\"2\">Dates</th>"
                     "<th rowspan=\"0\">Amount Due</th><th rowspan=\"0\">Status</th></tr>"
                     "<tr><th>Due Date</th><th>Statement Date</th></tr>", DUE_FIRST, control_of),
    # The first row's control cell is as tall as every row, so the rows
    # after it draw no control cell, and read side by side their Due Date
    # would sit in the Statement Date column.
    "tall cell": (ONE_ROW, ROW, lambda n: CONTROL.replace("<td>", "<td rowspan=\"3\">")
                  if n == 0 else ""),
}

# Billing History as My Energy Center drew it on 2026-11-06: seven header
# cells with Details last, and each bill row led by a cell of its own,
# hidden by an inline style, holding the row's number. A person sees seven
# columns. Read cell by cell, every row was one wider than the header and
# the list stopped on its first bill.
LIVE_HEAD = ("<tr><th>Statement Date</th><th>Due Date</th><th>Days in Billing Cycle</th>"
             "<th>Current Charges</th><th>Amount Due</th><th>Status</th><th>Details</th></tr>")
LIVE_ROW = """<tr invoiceid="{inv}" class="shown">{control}<td>{statement}</td><td>{due}</td>
<td>30</td><td>$12.34</td><td>$12.34</td><td>Billed</td><td class="details-control"></td></tr>"""
TABLES["hidden row number"] = (LIVE_HEAD, LIVE_ROW,
                               lambda n: '<td style="display:none;">%02d</td>' % (n + 1))
# The live table with a narrow screen's rule hiding each table's second
# cell: the Due Date header, and in each row the Statement Date, since the
# row number comes first. Read with every hidden cell passed over, both are
# six columns wide and each bill would sit under Statement Date with its Due
# Date. Only the row number is passed over, so each bill is still dated by
# the cell under Statement Date in the page's own layout.
TABLES["second cells hidden"] = (
    LIVE_HEAD.replace("<th>Due Date</th>", '<th style="display:none;">Due Date</th>'),
    LIVE_ROW.replace("<td>{statement}</td>", '<td style="display:none;">{statement}</td>'),
    TABLES["hidden row number"][2])
# A header with a column of its own for the row number, over the same
# hidden cells, keeps that column, as it always did.
TABLES["numbered column"] = (LIVE_HEAD.replace("<tr>", "<tr><th>#</th>"), LIVE_ROW,
                             TABLES["hidden row number"][2])
# A hidden first cell that is not a row number is not passed over.
TABLES["hidden first cell with words"] = (
    LIVE_HEAD, LIVE_ROW, lambda n: '<td style="display:none;">row %d</td>' % (n + 1))

DASHBOARD = """<!doctype html><html><head><title>My Energy Center</title></head><body>
<main><h1>Welcome back</h1><p>Your account at a glance.</p></main></body></html>"""

ELSEWHERE_PAGE = """<!doctype html><html><head><title>Inbox</title></head><body>
<main><h1>Inbox</h1><p>Lunch on Thursday?</p></main></body></html>"""


class FakeMec:
    def __init__(self):
        self.reset()

    def reset(self):
        # Every request, as (host, path).
        self.seen = []
        # The invoice id of a bill whose Statement Date cell is drawn blank.
        self.blank = ""
        # Which of the TABLES the bill table is drawn as.
        self.table = "one row"


SITE = FakeMec()


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
        if host == MEC_HOST and path == site.DOCUMENTS_PATH:
            head, row, control = TABLES[SITE.table]
            self._page(BILLING_HISTORY % {"head": head, "rows": "".join(
                row.format(inv=inv, control=control(n),
                           statement="" if inv == SITE.blank else statement, due=due)
                for n, (inv, statement, due) in enumerate(BILLS))})
        elif host == MEC_HOST and path == "/portal/Dashboard/index":
            self._page(DASHBOARD)
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


@pytest.fixture(autouse=True)
def fake_mec(server, monkeypatch):
    """My Energy Center is the made-up site, on plain http."""
    SITE.reset()
    documents = address(server, MEC_HOST, site.DOCUMENTS_PATH)
    for name in ("DOCUMENTS_URL", "STATEMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, documents)
    monkeypatch.setattr(site, "BASE", address(server, MEC_HOST, ""))
    for name in ("documents", "statements"):
        monkeypatch.setitem(site.URLS, name, documents)
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == MEC_HOST)
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def discover(tmp_path, cdp_url, capsys):
    """A Discover, as the panel's button runs it. How it ended and what it
    printed."""
    try:
        ended = ("returned", app_mod.main(["--discover", "--config",
                                           str(config_for(tmp_path, cdp_url))]))
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
    """Each bill listed, as (invoice id, date)."""
    path = tmp_path / "out" / "discovery.json"
    found = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted((r["document_id"], r["date"]) for r in found.values())


def tabs_on(cdp_url, host):
    return [t for t in testkit.tabs_of(cdp_url) if urlsplit(t.get("url") or "").hostname == host]


LISTED = [("ISU000000000201", "2026-09-12"), ("ISU000000000202", "2026-08-13"),
          ("ISU000000000203", "2026-07-14")]


def test_discover_with_no_tab_on_the_site_lists_in_a_tab_of_its_own(attached, server, tmp_path,
                                                                    capsys):
    """Another site's tab is the only one open. Billing History is opened in
    a new tab of the app's own and every bill is listed by its Statement
    Date, and the other site's tab is never loaded again. Discover stopped
    at once, saying the tab had left My Energy Center."""
    elsewhere = testkit.open_tab(attached, address(server, ELSEWHERE_HOST, "/inbox"), "Inbox")
    testkit.keep_only(attached, {elsewhere})
    SITE.seen.clear()

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert "left My Energy Center" not in out, folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert not [s for s in SITE.seen if s[0] == ELSEWHERE_HOST], \
        "the other site's tab was loaded, %s" % SITE.seen
    still = {t["id"]: t["url"] for t in testkit.tabs_of(attached)}
    assert still.get(elsewhere) == address(server, ELSEWHERE_HOST, "/inbox"), \
        "the other site's tab is still where it was"
    assert [urlsplit(t["url"]).path for t in tabs_on(attached, MEC_HOST)] == \
        [site.DOCUMENTS_PATH], "Billing History was opened in a tab of the app's own"


def test_their_tab_on_the_site_is_used_and_no_tab_is_opened(attached, server, tmp_path, capsys):
    """At home My Energy Center is usually still open in the tab the person
    signed in with. Discover lists the bills there and opens no tab of its
    own."""
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    tabs = testkit.tabs_of(attached)
    assert [t["id"] for t in tabs] == [theirs], "their tab was the one used, and no other opened"
    assert urlsplit(tabs[0]["url"]).path == site.DOCUMENTS_PATH


def test_a_blank_statement_date_stops_the_list_and_takes_no_due_date(attached, server, tmp_path,
                                                                     capsys):
    """The third bill's Statement Date cell is drawn blank, beside a Due Date
    of Oct 14, 2026. The bill was dated 2026-10-14. The list now stops on
    it, keeping the two bills read before it, and no bill is dated by its
    Due Date."""
    SITE.blank = "ISU000000000203"
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "Statement Date cell is blank" in out, folded(out)
    assert discovered(tmp_path) == LISTED[:2], folded(out)
    assert "2026-10-14" not in out


@pytest.mark.parametrize("table", ["two rows", "row headers", "hidden row number",
                                   "second cells hidden", "numbered column"])
def test_the_statement_date_column_is_found_in_other_table_shapes(table, attached, server,
                                                                  tmp_path, capsys):
    """Statement Date as the first cell of the header's second row, the
    second column of the table since the control column's header spans
    both rows, and each row's control cell drawn as a header cell of its
    row. Every bill is listed by its Statement Date either way."""
    SITE.table = table
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)


DUE_DATES = {"2026-10-01", "2026-09-01", "2026-10-14"}


@pytest.mark.parametrize("table", ["rowspan zero", "tall cell", "hidden first cell with words"])
def test_a_table_whose_rows_may_not_line_up_stops_rather_than_misdate(table, attached, server,
                                                                      tmp_path, capsys):
    """A header cell of rowspan 0, or a row's cell as tall as every row, can
    put a Due Date in the Statement Date column of what is read, though the
    browser draws it under Due Date. Each bill was dated by its Due Date.
    The list now stops, and no bill is dated by its Due Date."""
    SITE.table = table
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "stopped partway" in out, folded(out)
    assert not {date for _id, date in discovered(tmp_path)} & DUE_DATES, folded(out)


def test_diagnose_writes_the_header_a_date_is_read_by(attached, server, tmp_path, capsys,
                                                      monkeypatch):
    """The live header's whole text has never been seen, so a list that
    stops for want of its Statement Date column is repaired from what
    Diagnose writes, the header cells read and the column found."""
    from playwright.sync_api import Page
    real_wait = Page.wait_for_timeout
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 50)))
    SITE.table = "two rows"
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    assert app_mod.main(["--diagnose", "--config", str(config_for(tmp_path, attached))]) == 0
    capsys.readouterr()

    [written] = (tmp_path / "out").rglob("diagnose-documents.json")
    assert json.loads(written.read_text(encoding="utf-8"))["bill_table_header"] == {
        "cells": ["", "Dates", "Amount Due", "Status", "Statement Date", "Due Date"],
        "statement_date_column": 1}
