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

A list that may be partial stops too. The live table says nothing of how
many bills it holds, so rows that have not settled, anything near the table
that looks like a pager or a show-more control or says there are more bills
than were read, and hidden row numbers that do not count the rows read all
stop it. The shape headed "the live
table" below comes from the words of the pull request that reported it, and
every other shape around it is invented, since this project cannot see the
page.

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
from datetime import date, timedelta
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
%(before)s<table id="billHistoryTable"><thead>%(head)s</thead>
<tbody>%(rows)s</tbody>%(foot)s</table>%(after)s</main></body></html>"""

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

# Billing History as My Energy Center drew it on 2026-11-06, seven header
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
# cell, the Due Date header, and in each row the Statement Date, since the
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
# A number a person can see, or one in a header cell, is not the hidden cell
# the live table draws, so it stays a column and the row is one too wide.
TABLES["number shown"] = (LIVE_HEAD, LIVE_ROW, lambda n: "<td>%d</td>" % (n + 1))
TABLES["hidden number in a header cell"] = (
    LIVE_HEAD, LIVE_ROW, lambda n: '<th style="display:none;">%d</th>' % (n + 1))
# A hidden number as tall as every row, drawn in the first row only. Passed
# over, the rows below it would read as lining up.
TABLES["hidden tall number"] = (
    LIVE_HEAD, LIVE_ROW,
    lambda n: '<td rowspan="3" style="display:none;">1</td>' if n == 0 else "")
# A hidden cell two columns wide is no row number, under a header that has
# those two columns, so its digits are not asked to count the rows.
TABLES["hidden wide cell"] = (
    LIVE_HEAD.replace("<tr>", '<tr><th colspan="2">Reference</th>'), LIVE_ROW,
    lambda n: '<td colspan="2" style="display:none;">77</td>')
# The three shapes the review measured, each a real # column with one cell
# that has no header. Passing the first cell over put the Due Date under
# Statement Date, on a clean exit.
NUMBER = TABLES["hidden row number"][2]
HASH_HEAD = LIVE_HEAD.replace("<tr>", "<tr><th>#</th>")
TABLES["hash with a headerless details cell"] = (
    HASH_HEAD.replace("<th>Details</th>", ""), LIVE_ROW, NUMBER)
TABLES["hash with one more cell"] = (
    HASH_HEAD, LIVE_ROW.replace("</tr>", "<td></td></tr>"), NUMBER)
TABLES["hash with one row wider"] = (
    HASH_HEAD, lambda n: LIVE_ROW.replace("</tr>", "<td></td></tr>") if n == 2 else LIVE_ROW,
    NUMBER)
# Rows numbered as a second page would be, and with a bill left out.
TABLES["numbers from eleven"] = (
    LIVE_HEAD, LIVE_ROW, lambda n: '<td style="display:none;">%d</td>' % (n + 11))
TABLES["a gap in the numbers"] = (
    LIVE_HEAD, LIVE_ROW, lambda n: '<td style="display:none;">%d</td>' % (1, 2, 4)[n])
# Rows counted from 0 and down, which nothing says the live page does not do.
TABLES["numbers from zero, counting down"] = (
    LIVE_HEAD, LIVE_ROW, lambda n: '<td style="display:none;">%d</td>' % (2 - n))

PAGER = ('<nav aria-label="Bill pages"><ul class="pagination"><li class="active"><a href="#">1</a>'
         '</li><li><a href="#">2</a></li><li><a href="#">3</a></li></ul></nav>')

# An element with nothing in it still takes up room with this.
SIZED = ' style="display:block;height:20px;"'

# Each way something near the table says there may be more bills than it
# shows, as what is set on the page. All invented.
MORE_NEAR = {
    "a pager after the table": {"after": PAGER},
    "a pager above the table": {"before": PAGER},
    "a pager in the footer": {"foot": '<tfoot><tr><td colspan="7">%s</td></tr></tfoot>' % PAGER},
    "a pager deep in wrappers": {"after": "<div><div><div><div>%s</div></div></div></div>" % PAGER},
    "a Next link alone": {"after": '<p><a href="#">Next</a></p>'},
    "an arrow with only a label": {"after": '<a href="#" aria-label="Next page"%s></a>' % SIZED},
    "an arrow with only a title": {"after": '<a href="#" title="Next page"%s></a>' % SIZED},
    "a Next button": {"after": '<button type="button">Next</button>'},
    "a Next input": {"after": '<input type="submit" value="Next">'},
    "a Next span that is a button": {"after": '<span role="button">Next</span>'},
    "a Next span that is a link": {"after": '<span role="link">Next</span>'},
    "a Next div with a handler": {"after": '<div onclick="void 0">Next</div>'},
    "a class named as a pagination": {"after": '<div class="bill-pagination"%s></div>' % SIZED},
    "an id named as a pagination": {"after": '<div id="billPagination"%s></div>' % SIZED},
    "a class named as a pager": {"after": '<div class="bill-pager"%s></div>' % SIZED},
    "an id named as a pager": {"after": '<div id="billPager"%s></div>' % SIZED},
    "a label named as a pagination": {"after": '<div aria-label="Pagination"%s></div>' % SIZED},
    "page numbers alone": {"after": '<p><a href="#">1</a> <a href="#">2</a></p>'},
    "a Show more button": {"after": '<button type="button">Show more</button>'},
    "a Load more input": {"after": '<input type="button" value="Load more">'},
    "a Show more span": {"after": '<span class="link">Show more</span>'},
    "a Show more row": {"tail": '<tr><td colspan="7"><a href="#">Show more</a></td></tr>'},
    "a line of what is shown": {"after": "<p>Showing 1 to 3 of 24 bills</p>"},
    "a line of a later page": {"after": "<p>Page 2 of 2</p>"},
    "a line of 3 of 24 bills": {"after": "<p>Showing 3 of 24 bills</p>"},
    "a Next 10 Bills button": {"after": '<button type="button">Next 10 Bills</button>'},
    "a View All 24 Bills link": {"after": '<p><a href="#">View All 24 Bills</a></p>'},
}

# What is not near the table, not drawn, or a bill's own.
NOT_MORE_NEAR = {
    "a pager the page hides": {"after": '<div style="display:none;">%s</div>' % PAGER},
    "a pager with nothing in it": {"after": '<ul class="pagination"></ul>'},
    "a Show more out of sight": {"after": '<button style="visibility:hidden;">Show more</button>'},
    "a Next link far below": {"after": '<div style="height:600px;"></div><a href="#">Next</a>'},
    "a Next link far above": {"before": '<a href="#">Next</a><div style="height:600px;"></div>'},
    "a View all link beside the table": {
        "before": '<div style="display:flex;"><div style="flex:1;">',
        "after": '</div><aside style="width:200px;"><a href="#">View all</a></aside></div>'},
    "a detail row's own link": {
        "detail": lambda n: ('<tr><td colspan="7"><a href="#">Show more</a></td></tr>'
                             if n == 0 else "")},
    "a line that counts the rows read": {"after": "<p>Showing 1 to 3 of 3 entries</p>"},
    "a line of one page": {"after": "<p>Page 1 of 1</p>"},
    "a View all that counts the rows read": {"after": '<p><a href="#">View all 3 bills</a></p>'},
    "the plugin's info line agreeing": {
        "after": '<div id="billHistoryTable_info">Showing 1 to 3 of 3 entries</div>'},
    "a wrapper named as a pagination": {"before": '<div class="table-pagination-wrap">',
                                        "after": "</div>"},
    "a wrapper with an id that starts with page": {"before": '<div id="pageRow">',
                                                   "after": "</div>"},
    "names that only start with page": {
        "after": ('<div class="pageRight"%s></div><div id="pageRoot"%s></div>'
                  '<div class="paginated-list"%s></div>' % (SIZED, SIZED, SIZED))},
}

# Draws the first three rows now and the rest a second and a half later, the
# gap the review's probe measured.
LATE_BATCH = """<script>
const body = document.querySelector('#billHistoryTable tbody');
const late = Array.from(body.rows).slice(3);
late.forEach((tr) => tr.remove());
setTimeout(() => late.forEach((tr) => body.appendChild(tr)), 1500);
</script>"""


def drawn(day):
    return "%s %d, %d" % (day.strftime("%b"), day.day, day.year)


def invented_days(count):
    return [date(2031, 12, 20) - timedelta(days=30 * n) for n in range(count)]


def invented_bills(count):
    """Bills a month apart, each as BILLS holds it."""
    return [("ISU%012d" % (301 + n), drawn(day), drawn(day + timedelta(days=10)))
            for n, day in enumerate(invented_days(count))]


def invented_listed(count):
    """Those bills as a Discover lists them."""
    return [("ISU%012d" % (301 + n), day.isoformat()) for n, day in enumerate(invented_days(count))]


# The pull request counts 25 rows in the table body, nine bills and their
# detail rows. How the sixteen detail rows fall among the bills, and what
# they hold, is invented.
def live_details(n):
    links = ('<tr class="detail"><td colspan="7"><a href="#">View Your Detailed Bill PDF</a>'
             "</td></tr>")
    usage = '<tr class="detail"><td colspan="7">Days in Billing Cycle 30</td></tr>'
    return links + usage if n < 7 else links


# The two controls sdge_site.py names on this page, drawn above the table.
LIVE_ABOVE = ('<select id="accountList"><option value="1">Account one</option></select>'
              '<p><a id="downloadBillingHisotry" href="#">Download billing history (Excel)</a></p>')

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
        self.bills = BILLS
        # Anything else on the page, as the keys of MORE_NEAR name it.
        self.before = self.after = self.foot = self.tail = ""
        self.detail = lambda n: ""


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
            self._page(BILLING_HISTORY % {
                "head": head, "before": SITE.before, "after": SITE.after, "foot": SITE.foot,
                "rows": "".join(
                    (row(n) if callable(row) else row).format(
                        inv=inv, control=control(n),
                        statement="" if inv == SITE.blank else statement, due=due) + SITE.detail(n)
                    for n, (inv, statement, due) in enumerate(SITE.bills)) + SITE.tail})
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
    """My Energy Center is the made-up site, on plain http. Its rows stand
    still, so the wait for them to settle is cut short, and the test of
    rows drawn in two batches puts the shipped wait back."""
    SITE.reset()
    monkeypatch.setattr(site, "ROWS_QUIET_MS", 200)
    documents = address(server, MEC_HOST, site.DOCUMENTS_PATH)
    for name in ("DOCUMENTS_URL", "STATEMENTS_URL", "BILLING_URL"):
        monkeypatch.setattr(site, name, documents)
    monkeypatch.setattr(site, "BASE", address(server, MEC_HOST, ""))
    for name in ("documents", "statements"):
        monkeypatch.setitem(site.URLS, name, documents)
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == MEC_HOST)
    return SITE


SHIPPED_QUIET_MS = site.ROWS_QUIET_MS


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


def resume(tmp_path, cdp_url, capsys):
    """A Resume on the same folder."""
    try:
        ended = ("returned", app_mod.main(["--resume", "--config",
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


def read_whole(tmp_path):
    """What the run's own note says of the last listing."""
    note = tmp_path / "out" / "last-listing.json"
    return json.loads(note.read_text(encoding="utf-8"))["complete"]


def on_their_tab(cdp_url, server):
    theirs = testkit.open_tab(cdp_url, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(cdp_url, {theirs})


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
                                   "second cells hidden", "numbered column", "hidden wide cell",
                                   "numbers from zero, counting down"])
def test_the_statement_date_column_is_found_in_other_table_shapes(table, attached, server,
                                                                  tmp_path, capsys):
    """Statement Date as the first cell of the header's second row, the
    second column of the table since the control column's header spans
    both rows, and each row's control cell drawn as a header cell of its
    row. Every bill is listed by its Statement Date either way. A hidden
    cell two columns wide is no row number, so its digits stop nothing, and
    taking the colspan check out stops this list on them."""
    SITE.table = table
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)


DUE_DATES = {"2026-10-01", "2026-09-01", "2026-10-14"}


@pytest.mark.parametrize("table", ["rowspan zero", "tall cell", "hidden first cell with words",
                                   "number shown", "hidden number in a header cell",
                                   "hidden tall number", "hash with a headerless details cell",
                                   "hash with one more cell", "hash with one row wider"])
def test_a_table_whose_rows_may_not_line_up_stops_rather_than_misdate(table, attached, server,
                                                                      tmp_path, capsys):
    """A header cell of rowspan 0, or a row's cell as tall as every row, can
    put a Due Date in the Statement Date column of what is read, though the
    browser draws it under Due Date. Each bill was dated by its Due Date.
    The list now stops, and no bill is dated by its Due Date. It stops too
    on a first cell that is not the live table's hidden number, one a person
    can see, a header cell, a tall cell or one holding words. And on a real
    # column with one cell that has no header, where passing the first cell
    over dated bills by their Due Date on a clean exit."""
    SITE.table = table
    theirs = testkit.open_tab(attached, address(server, MEC_HOST, "/portal/Dashboard/index"),
                              "My Energy Center")
    testkit.keep_only(attached, {theirs})

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "stopped partway" in out, folded(out)
    assert not {date for _id, date in discovered(tmp_path)} & DUE_DATES, folded(out)


def test_the_live_table_lists_all_nine_bills(attached, server, tmp_path, capsys):
    """Billing History as the pull request describes it, seven header cells,
    25 rows in the table body, nine bills and their detail rows, each bill
    led by its hidden number, no table plugin, no info line and no pager.
    Nothing near it may read as a pager, or every run stops."""
    SITE.table, SITE.bills = "hidden row number", invented_bills(9)
    SITE.detail, SITE.before = live_details, LIVE_ABOVE
    assert 9 + sum(live_details(n).count("<tr") for n in range(9)) == 25
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == invented_listed(9), folded(out)
    assert read_whole(tmp_path) is True
    assert panel_reads(out)["stopped"] == 0, folded(out)


@pytest.mark.parametrize("shape", sorted(MORE_NEAR))
def test_a_pager_or_a_show_more_control_near_the_table_stops_the_list(shape, attached, server,
                                                                      tmp_path, capsys):
    """The table shows some of the bills and says so only by what is near
    it. This ended clean with the list noted whole, and the rest were never
    known. The list now stops, keeping the bills it read."""
    SITE.table = "hidden row number"
    for name, value in MORE_NEAR[shape].items():
        setattr(SITE, name, value)
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "shows a pager or a show-more control" in folded(out), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert read_whole(tmp_path) is False


@pytest.mark.parametrize("shape", sorted(NOT_MORE_NEAR))
def test_what_is_hidden_far_off_or_a_bills_own_stops_nothing(shape, attached, server, tmp_path,
                                                             capsys):
    """A pager a page keeps hidden, or a link that is not by the table, says
    nothing of it, and a stop here would be every run's."""
    SITE.table = "hidden row number"
    for name, value in NOT_MORE_NEAR[shape].items():
        setattr(SITE, name, value)
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert read_whole(tmp_path) is True


def test_a_hidden_first_cell_with_words_stays_a_column(attached, server, tmp_path, capsys):
    """Only digits are a row number. A hidden cell of words is a column, so
    its row is one too wide, and the list says so. Passed over as a number,
    it would stop for another reason and hide what the page had changed."""
    SITE.table = "hidden first cell with words"
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "does not line up" in folded(out), folded(out)


def test_the_failure_file_says_what_the_wait_for_rows_found(attached, server, tmp_path, capsys):
    """A run that stops writes down the wait it took, from the journal the
    app hands to the site layer, so a repair can see how the rows came."""
    SITE.table, SITE.after = "hidden row number", PAGER
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    [written] = (tmp_path / "out").rglob("failure-*.json")
    assert "a further bill row" in written.read_text(encoding="utf-8")


def test_a_resume_after_a_pager_saves_nothing_and_reads_as_stopped(attached, server, tmp_path,
                                                                   capsys):
    """The stop goes through the app's own listing, so a Resume on what was
    kept reads the same list, stops there, and is not called finished."""
    SITE.table, SITE.after = "hidden row number", PAGER
    on_their_tab(attached, server)
    discover(tmp_path, attached, capsys)

    ended, out = resume(tmp_path, attached, capsys)

    assert ended[0] == "exit", folded(out)
    assert panel_reads(out)["stopped"] == 1, folded(out)
    assert read_whole(tmp_path) is False
    assert not list((tmp_path / "out").rglob("*.pdf")), folded(out)


def test_rows_drawn_in_two_batches_are_read_once_they_settle(attached, server, tmp_path, capsys,
                                                             monkeypatch):
    """Three rows, and the rest a second and a half later, with the wait the
    app ships. The wait for rows ends on the first one, so three of twelve
    were read as the whole list."""
    monkeypatch.setattr(site, "ROWS_QUIET_MS", SHIPPED_QUIET_MS)
    SITE.table, SITE.bills, SITE.after = "hidden row number", invented_bills(12), LATE_BATCH
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("returned", 0), folded(out)
    assert discovered(tmp_path) == invented_listed(12), folded(out)


@pytest.mark.parametrize("table", ["numbers from eleven", "a gap in the numbers"])
def test_hidden_numbers_that_do_not_count_the_rows_stop_the_list(table, attached, server,
                                                                tmp_path, capsys):
    """Rows numbered from 11 are a second page, and a gap is a bill the
    table did not draw. Both read as the whole list, and now the bills read
    are kept and the list stops."""
    SITE.table = table
    on_their_tab(attached, server)

    ended, out = discover(tmp_path, attached, capsys)

    assert ended == ("exit", 1), folded(out)
    assert "hidden row numbers do not count the 3 rows read" in folded(out), folded(out)
    assert discovered(tmp_path) == LISTED, folded(out)
    assert read_whole(tmp_path) is False


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
