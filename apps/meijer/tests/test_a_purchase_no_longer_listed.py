"""A purchase Meijer no longer lists, against made-up Meijer pages in a real
browser (#42).

A tester's Run All saved 94 of the 97 purchases discovery knew. Each of the
last three, his oldest store receipts, printed that its row carried no
receipt or details link, was counted for manual review and written into both
CSVs, and every later run looked for it twice more and wrote it down again.
The file he could attach kept only the last of the three, and both of its
looks found the In-Store tab drawing 95 rows and not the purchase's. Meijer
appears to list about two years of store receipts, and those three had
dropped off the end of the list.

Now a purchase older than every row its tab draws is written down as no
longer listed, with the oldest date the list shows, and later runs skip it
until a discovery finds it on the list again. It goes into the CSVs once, so
a spend summary still counts it. That is said only of a list seen whole, its
tab opened, its rows stopped changing and drawing no more when scrolled to
the end, no control showing that would show more of it or a narrower part of
it, going back at least twenty months, and read by the run's own discovery.
A list behind a Load more button, under a remembered filter or cut short
looks the same otherwise (review), and every such purchase, and one missing
from inside the range the list shows, stays a failure that says so. The file
to attach keeps every attempt of the run.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Meijer. Every store, date
and amount is invented, and the runs take a day in 2028 to be today.
"""
import contextlib
import importlib.util
import io
import json
import re
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_receipts as app_mod
import meijer_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

ORDERS = "/shopping/orders.html"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The site's own header, with an amount in it, on every page it draws.
HEADER = ("<header><a href='/shopping/account.html'>Account</a>"
          "<span>mPerks savings this year $8.15</span></header>")

# The day the runs here take to be today. Twenty months before it is
# 2026-10-01, so a list going back to 2026-09-12 goes back far enough and
# one going back only to 2028 does not.
TODAY = date(2028, 6, 1)

NO_ONLINE_ORDERS = "<p>You haven't placed any orders yet</p>"
ONLINE_ORDER = ("<ul><li class='order-card'><div>Pickup</div><div>Jun 9, 2026</div>"
                "<div>Order 4417</div><div>$31.50</div></li></ul>")

# The purchases tool, which builds its Orders and Summary sheets from each
# app's Order History.
_spec = importlib.util.spec_from_file_location(
    "export_purchases", Path(__file__).resolve().parents[3] / "tools" / "export_purchases.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def _text_pdf(lines) -> bytes:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out) + b" " * 4000


class Receipt:
    """One store receipt as the In-Store tab lists it, and its till receipt,
    which prints its date the way a till does and its total."""

    def __init__(self, iso, amount, items):
        self.iso, self.amount, self.items = iso, amount, items
        self.rid = "r" + iso.replace("-", "")

    def row(self):
        y, m, d = self.iso.split("-")
        return ("<li class='order-card'><div class='date'>In-Store: %s/%s/%s</div>"
                "<div>18 Example Road</div>"
                "<div class='totals'><span>%s</span>&nbsp;&nbsp;%d items</div>"
                "<a href='javascript:void(0)' onclick=\"saveReceipt('%s');return false\">"
                "view receipt pdf</a></li>" % (m, d, y, self.amount, self.items, self.rid))

    def pdf(self):
        y, m, d = self.iso.split("-")
        return _text_pdf(["MEIJER STORE 000", "%s/%s/%s 10:15" % (m, d, y[2:]),
                          "TOTAL %s" % self.amount.lstrip("$"), "THANK YOU"])


# Newest first, as the tab lists them. The gap is inside the range the
# shorter list still shows, and the last two are older than all of it.
R1 = Receipt("2026-06-11", "$23.41", 7)
R2 = Receipt("2026-06-03", "$58.07", 12)
GAP = Receipt("2026-05-27", "$14.62", 4)
R3 = Receipt("2026-05-20", "$31.90", 9)
OLD1 = Receipt("2026-05-12", "$9.85", 2)
OLD2 = Receipt("2026-05-04", "$40.16", 6)
EVERY = [R1, R2, GAP, R3, OLD1, OLD2]

# A list that draws its rows one at a time, and one older than all of them.
GROWING = [Receipt("2026-08-%02d" % (28 - 3 * i), "$%d.%02d" % (20 + i, 11 * i % 100), 3 + i)
           for i in range(9)]
GONE = Receipt("2026-03-02", "$12.34", 3)

# A list going back far enough, K1 and K2, a row it draws only when it is
# scrolled to its end, S1, two purchases older than all of them, C1 and C2,
# and two from the last few months, F1 and F2.
K1 = Receipt("2026-09-20", "$41.10", 5)
K2 = Receipt("2026-09-12", "$17.35", 3)
S1 = Receipt("2026-09-05", "$22.22", 2)
C1 = Receipt("2026-08-30", "$26.40", 4)
C2 = Receipt("2026-08-21", "$63.12", 8)
F1 = Receipt("2028-05-20", "$12.80", 2)
F2 = Receipt("2028-04-11", "$35.55", 6)
KNOWN = [F1, F2, K1, K2, C1, C2]

# A row's receipt link downloads the receipt from this site.
SAVE_JS = ("function saveReceipt(rid) { const a = document.createElement('a');"
           " a.href = '/receipt/' + rid + '.pdf'; a.download = 'receipt.pdf';"
           " document.body.appendChild(a); a.click(); a.remove(); }")

# The In-Store list. Drawn whole when its tab is pressed, or with GROWS one
# row at a time, the first when the tab is pressed and each next one when
# drawOne is called, which is never by a clock, and with ENDLESS made-up rows
# newer than any purchase here go on after them. LATER rows come only from
# the Load more button, which nothing presses, and SCROLLED rows once the
# page is scrolled to its end, or with SCROLL_AFTER that many calls of
# drawOne after that, the way a fetch for older receipts comes late. With
# HIDDEN the page says the browser is not showing it.
_LIST_JS = r"""
let n = 0, scrolledIn = false, pending = 0;
function list() { return document.getElementById('rows'); }
function made(k) {
  const d = new Date(2026, 7, 31 - k);
  const two = (v) => String(v).padStart(2, '0');
  const when = two(d.getMonth() + 1) + '/' + two(d.getDate()) + '/' + d.getFullYear();
  return "<li class='order-card'><div class='date'>In-Store: " + when + "</div>"
    + "<div>18 Example Road</div><div class='totals'><span>$" + (100 + k) + ".37</span>"
    + "&nbsp;&nbsp;3 items</div><a href='javascript:void(0)'>view receipt pdf</a></li>";
}
function drawOne() {
  if (document.getElementById('store').style.display === 'none') return;
  if (pending > 0) {
    pending -= 1;
    if (pending === 0) list().insertAdjacentHTML('beforeend', SCROLLED.join(''));
  }
  if (!GROWS) return;
  if (n < ROWS.length) list().insertAdjacentHTML('beforeend', ROWS[n]);
  else if (ENDLESS) list().insertAdjacentHTML('beforeend', made(n));
  else return;
  n += 1;
}
window.drawOne = drawOne;
function show(which) {
  document.getElementById('online').style.display = which === 'online' ? '' : 'none';
  document.getElementById('store').style.display = which === 'store' ? '' : 'none';
  list().innerHTML = '';
  n = 0;
  scrolledIn = false;
  pending = 0;
  if (which !== 'store') return;
  if (GROWS) { drawOne(); return; }
  list().innerHTML = ROWS.join('');
}
function loadMore() { list().insertAdjacentHTML('beforeend', LATER.join('')); }
window.addEventListener('scroll', () => {
  if (!SCROLLED.length || scrolledIn) return;
  if (window.innerHeight + window.scrollY < document.documentElement.scrollHeight - 10) return;
  scrolledIn = true;
  if (SCROLL_AFTER) pending = SCROLL_AFTER;
  else list().insertAdjacentHTML('beforeend', SCROLLED.join(''));
});
if (HIDDEN) Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'});
"""


def orders_page(receipts, grows=False, endless=False, later=(), scrolled=(), choose=False,
                tabs=True, online=NO_ONLINE_ORDERS, scroll_after=0, hidden=False):
    """The orders page, open on Online Orders, whose In-Store rows are drawn
    when that tab is pressed and taken away when the other one is (see
    _LIST_JS). `choose` puts a remembered choice of period above the list,
    and without `tabs` the rows are drawn on a page with no tabs at all."""
    if not tabs:
        return ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
                "<h1>Orders and Receipts</h1>%s<ul id='rows'>%s</ul><script>%s</script>"
                "</main></body></html>"
                % (HEADER, NO_ONLINE_ORDERS, "".join(r.row() for r in receipts), SAVE_JS))
    above = ("<div class='period'><label>Show <select id='period'>"
             "<option selected>Last 6 months</option><option>Last 12 months</option>"
             "<option>All receipts</option></select></label></div>") if choose else ""
    below = ("<button id='more' onclick='loadMore()'>Load more</button>" if later else "") + \
        ("<div style='height:4000px'></div>" if scrolled else "")
    head = ("const ROWS = %s, LATER = %s, SCROLLED = %s, GROWS = %s, ENDLESS = %s,"
            " SCROLL_AFTER = %d, HIDDEN = %s;"
            % (json.dumps([r.row() for r in receipts]), json.dumps([r.row() for r in later]),
               json.dumps([r.row() for r in scrolled]), "true" if grows else "false",
               "true" if endless else "false", int(scroll_after), "true" if hidden else "false"))
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
            "<h1>Orders and Receipts</h1><div role='tablist'>"
            "<a role='tab' href='#' onclick=\"show('online');return false\">Online Orders</a>"
            "<a role='tab' href='#' onclick=\"show('store');return false\">In-Store Receipts</a></div>"
            "<div id='online'>%s</div>"
            "<div id='store' style='display:none'>%s<ul id='rows'></ul>%s</div>"
            "<script>%s%s%s</script></main></body></html>"
            % (HEADER, online, above, below, head, _LIST_JS, SAVE_JS))


class FakeMeijer:
    """What the made-up site shows, and what the app was seen to do. Each
    receipt is there to download whether or not the list shows it."""

    def __init__(self):
        self.orders = orders_page([])
        self.pdfs = {r.rid: r.pdf() for r in EVERY + GROWING + KNOWN + [GONE, S1]}
        self.failures = []
        self.asked = []


SITE = FakeMeijer()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == ORDERS:
            body, kind, extra = SITE.orders.encode("utf-8"), "text/html; charset=utf-8", {}
        elif path == "/":
            body, kind, extra = (b"<!doctype html><html><head><title>Meijer</title></head>"
                                 b"<body><h1>Meijer</h1></body></html>"), "text/html; charset=utf-8", {}
        elif path.startswith("/receipt/") and path[9:-4] in SITE.pdfs:
            body, kind = SITE.pdfs[path[9:-4]], "application/pdf"
            extra = {"Content-Disposition": "attachment; filename=receipt.pdf"}
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    """Playwright's own Chromium, found the way the app finds it in its
    bundled mode, so it is never the person's everyday browser."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation. The app works in a tab it opens
    for itself, so the tab that drew can stay where it is."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(scope="module", autouse=True)
def fake_meijer(server):
    """Every address the app opens points at the made-up site, every wait is
    short, and today is TODAY. Held for the whole file, since a history of
    runs is read by several tests. A tab is given half a second to start
    drawing once pressed and three seconds for its rows, a purchase's row is
    looked for twice, and the rows count as settled after a second without
    a change, or a second and a half once the list is scrolled to its end.

    Every failure file the app is asked to write, and every purchase it
    takes to the receipt step, is noted as well."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(site, "BASE", server)
        mp.setattr(site, "ORDERS_URL", server + ORDERS)
        mp.setattr(site, "ORDER_CANDIDATES", [server + ORDERS])
        mp.setitem(site.URLS, "orders", server + ORDERS)
        mp.setitem(site.URLS, "home", server + "/")
        mp.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
        mp.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
        mp.setattr(site, "SETTLE_MS", 0, raising=False)
        mp.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
        mp.setattr(site, "LIST_WAIT_MS", 3000, raising=False)
        mp.setattr(site, "ROWS_STEADY_MS", 1000, raising=False)
        mp.setattr(site, "ROW_LOOKS", 2, raising=False)
        mp.setattr(site, "TAB_PAUSE_MS", 500, raising=False)
        mp.setattr(site, "SCROLL_STEADY_MS", 1500, raising=False)
        mp.setattr(app_mod, "_today", lambda: TODAY, raising=False)
        real_failure = app_mod.App.write_failure
        real_save = app_mod.App._save_receipt

        def write_failure(self, step, reason="", *args, **kw):
            SITE.failures.append((step, reason))
            return real_failure(self, step, reason, *args, **kw)

        def save_receipt(self, page, purchase):
            SITE.asked.append(purchase.purchase_date)
            return real_save(self, page, purchase)
        mp.setattr(app_mod.App, "write_failure", write_failure)
        mp.setattr(app_mod.App, "_save_receipt", save_receipt)
        yield SITE


@pytest.fixture
def growing(monkeypatch):
    """Each time the app asks the page how many rows it draws, the page
    draws its next row first. The list grows as fast as the app looks at it
    and no faster, however busy the machine is, and stops once it has drawn
    them all."""
    real = site.rows_showing

    def look(page, purchase_type):
        try:
            page.evaluate("() => window.drawOne && window.drawOne()")
        except Exception:
            pass
        return real(page, purchase_type)
    monkeypatch.setattr(site, "rows_showing", look)


def config_for(folder, cdp_url):
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(folder / "out"),
        "profile_dir": str(folder / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def _json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def run(folder, cdp_url, *flags) -> dict:
    """One run of the app on the made-up site, and what it did. What it
    printed, with its line breaks read as spaces, since a message is wrapped
    wherever it happens to fill a line, the result it gave the panel, the
    failure files it was asked for and wrote, the purchases it took to the
    receipt step, what it left in progress.json, the CSVs and the file to
    attach, and the orders the purchases tool builds from its Order History."""
    diagnostics = folder / "out" / "Diagnostics"
    before = set(diagnostics.glob("failure-*.json"))
    SITE.failures.clear()
    SITE.asked.clear()
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        code = app_mod.main([*flags, "--config", str(config_for(folder, cdp_url))])
    out = " ".join(said.getvalue().split())
    assert code == 0, out
    result = re.findall(r"PAPERPULL_RUN_RESULT (\{[^}]*\})", out)
    written = sorted(set(diagnostics.glob("failure-*.json")) - before)
    attempt = _json(diagnostics / "download-attempt.json", {})
    rows = {}
    for name in ("Meijer Order History.csv", "Meijer Receipt Index.csv"):
        path = folder / "out" / name
        rows[name] = (storage.CsvFile(path, storage.ORDER_HISTORY_COLUMNS
                                      if "History" in name else storage.RECEIPT_INDEX_COLUMNS)
                      .read_all() if path.exists() else [])
    history = folder / "out" / "Meijer Order History.csv"
    summary = folder / "out" / "run-summary.txt"
    return {"out": out, "result": json.loads(result[-1]) if result else {},
            "failures": list(SITE.failures), "asked": list(SITE.asked),
            "failure_files": [_json(p) for p in written],
            "progress": _json(folder / "out" / "progress.json", {}),
            "discovery": _json(folder / "out" / "discovery.json", {}),
            "attempts": attempt.get("attempts") if isinstance(attempt, dict) else None,
            "rows": rows,
            "orders": (export.orders_from(export.load_purchases("Meijer", history))
                       if history.exists() else []),
            "summary": summary.read_text(encoding="utf-8") if summary.exists() else ""}


def by_date(records) -> dict:
    """Each store receipt's record, by its date."""
    return {r.get("purchase_date"): r for r in records.values()
            if isinstance(r, dict) and r.get("purchase_type") == "In-Store"}


def dates_in(rows) -> list:
    return sorted(r.get("Purchase Date") for r in rows)


def attempts_said(took) -> list:
    """Each attempt in the file to attach, as (its place, of how many, what
    it came to)."""
    return [(a.get("place"), a.get("of"), a.get("outcome")) for a in (took["attempts"] or [])]


def notes_in(attempt, note) -> list:
    return [t for t in attempt.get("responses") or [] if t.get("note") == note]


def judged(attempt) -> list:
    """How each look of an attempt judged its list, as the file to attach
    keeps it."""
    return notes_in(attempt, "the oldest row the list shows")


def mark_saved(folder, receipts):
    """Write these purchases down as saved by an earlier run, the way a run
    leaves a receipt that passed its check."""
    known = by_date(_json(folder / "out" / "discovery.json", {}))
    progress = _json(folder / "out" / "progress.json", {})
    for r in receipts:
        rec = dict(known[r.iso])
        rec.update({"state": "Completed", "downloaded_ok": True})
        progress["In-Store:" + rec["order_number"]] = rec
    (folder / "out" / "progress.json").write_text(json.dumps(progress), encoding="utf-8")


# -- his Run All, then the next run, then a list that shows one again -------------------
#
# Discovery knew six store receipts. The tab now draws the newest three of
# the four it still has, so the two oldest have dropped off its end and one
# from inside its range is missing.

@pytest.fixture(scope="module")
def history(attached, tmp_path_factory):
    folder = tmp_path_factory.mktemp("history")
    took = {}
    SITE.orders = orders_page(EVERY)
    took["discovery"] = run(folder, attached, "--discover")
    SITE.orders = orders_page([R1, R2, R3])
    took["first"] = run(folder, attached, "--all", "--yes")
    took["second"] = run(folder, attached, "--all", "--yes")
    SITE.orders = orders_page([R1, R2, R3, OLD1])
    took["listed again"] = run(folder, attached, "--all", "--yes")
    return took


def statuses(rows, receipt) -> list:
    return [r.get("Processing Status") for r in rows if r.get("Purchase Date") == receipt.iso]


def test_the_two_oldest_are_written_down_as_no_longer_listed(history):
    """Each says the oldest date the list still shows, writes no failure
    file and counts for no review. Each goes into both CSVs once, so the
    purchases tool's spend summary still counts it. The receipts saved
    beside them count for review as they always did, since a store address
    names nothing the app can sort them by."""
    assert len(by_date(history["discovery"]["discovery"])) == 6, "discovery knew all six"
    first = history["first"]
    records = by_date(first["progress"])
    for r in (OLD1, OLD2):
        rec = records[r.iso]
        assert rec["state"] == "No Longer Listed", rec
        assert not rec.get("downloaded_ok")
        assert R3.iso in rec.get("notes", ""), rec
    said = ("Meijer no longer lists this purchase. Its In-Store Receipts tab goes back to "
            "2026-05-20, and this purchase is older, so there is no row to press. Later runs "
            "skip it unless Meijer lists it again.")
    assert first["out"].count(said) == 2, first["out"]
    assert "No receipt or details link" not in first["out"]
    assert first["failures"] == [("find the receipt", "its row is not on the page")], \
        "the only failure file asked for is the missing purchase inside the range"
    saved = [r for r in (R1, R2, R3) if records[r.iso].get("downloaded_ok")]
    assert saved == [R1, R2, R3], first["out"]
    assert first["result"].get("manual_review") == len(saved), first["result"]
    assert first["result"].get("failed") == 1, first["result"]
    assert "No longer listed:          2" in first["summary"], first["summary"]
    for name, rows in first["rows"].items():
        assert dates_in(rows) == sorted(r.iso for r in saved + [OLD1, OLD2]), (name, dates_in(rows))
        assert statuses(rows, OLD1) == statuses(rows, OLD2) == ["No Longer Listed"], name
    totals = {o["Date"]: o["Order Total"] for o in first["orders"]}
    assert totals[OLD1.iso] == 9.85 and totals[OLD2.iso] == 40.16, first["orders"]
    assert [o["Date"] for o in first["orders"]].count(OLD1.iso) == 1
    assert first["out"].count("What the page answered is in") == 1, \
        "only the failure asks for the file to be attached"


def test_a_purchase_missing_from_inside_the_listed_range_is_a_failure(history):
    """Its date is inside the range the list shows, so it is not said to
    have dropped off. It says what happened, and the next run looks for it
    again without writing it down at all."""
    first, second = history["first"], history["second"]
    rec = by_date(first["progress"])[GAP.iso]
    assert rec["state"] == "Failed", rec
    assert "Its row is not on Meijer's In-Store Receipts tab" in rec.get("notes", ""), rec
    assert ("Its row is not on Meijer's In-Store Receipts tab, so nothing was pressed. "
            "The next run looks for it again.") in first["out"], first["out"]
    [failure] = first["failure_files"]
    assert (failure["step"], failure["reason"]) == ("find the receipt", "its row is not on the page")
    assert GAP.iso in second["asked"], "looked for again"
    assert by_date(second["progress"])[GAP.iso]["state"] == "Failed"
    for rows in second["rows"].values():
        assert GAP.iso not in dates_in(rows), "never written into a CSV"


def test_the_file_to_attach_keeps_every_attempt_of_the_run_in_order(history):
    """It kept only the last, so his Run All left a record of one of the
    three. Each says its place in the run, what it came to, and how each
    look judged the list."""
    first = history["first"]
    assert attempts_said(first) == [(3, 6, "its row is not on the page"),
                                     (5, 6, "dropped off the list"),
                                     (6, 6, "dropped off the list")], first["attempts"]
    gap, old1, old2 = first["attempts"]
    whole = {"note": "the oldest row the list shows", "rows": 3, "earlier_than_every_row": True,
             "listed_by_discovery": False, "tab_opened": True, "controls_read": True,
             "more_controls": 0, "back_twenty_months": True, "discovery_read_the_tab": True,
             "saved_before": False}
    for a in (old1, old2):
        assert judged(a) == [whole] * 2, a
    assert [n["earlier_than_every_row"] for n in judged(gap)] == [False, False], gap
    assert len(notes_in(gap, "the purchase's tab")) == 2, "two looks, as before"


def test_a_later_run_does_not_try_them_again(history):
    """The second run takes neither to the receipt step, says why it skips
    each, and adds nothing to the CSVs, where every purchase is still
    written once."""
    second = history["second"]
    assert OLD1.iso not in second["asked"] and OLD2.iso not in second["asked"], second["asked"]
    assert second["asked"] == [GAP.iso], second["asked"]
    assert second["out"].count("Meijer no longer lists it, so it is skipped.") == 2, second["out"]
    assert attempts_said(second) == [(3, 6, "its row is not on the page")]
    for name, rows in second["rows"].items():
        assert dates_in(rows) == sorted([R1.iso, R2.iso, R3.iso, OLD1.iso, OLD2.iso]), \
            (name, dates_in(rows))
    records = by_date(second["progress"])
    assert records[OLD1.iso]["state"] == records[OLD2.iso]["state"] == "No Longer Listed"
    assert second["result"].get("failed") == 1 and "No longer listed:          2" in second["summary"]


def test_one_the_list_shows_again_is_tried_again(history):
    """A discovery that finds it on the list again puts it back, and the
    receipt is saved. Its rows as no longer listed give way to the saved
    receipt's, so it is still one purchase in the CSVs. The other is still
    skipped."""
    again = history["listed again"]
    assert ("1 purchase(s) Meijer had stopped listing are on its list again, so this run "
            "tries them again.") in again["out"], again["out"]
    assert again["asked"] == [GAP.iso, OLD1.iso], again["asked"]
    records = by_date(again["progress"])
    assert records[OLD1.iso].get("downloaded_ok") is True, records[OLD1.iso]
    assert Path(records[OLD1.iso]["pdf_path"]).read_bytes() == OLD1.pdf()
    assert records[OLD2.iso]["state"] == "No Longer Listed"
    assert again["out"].count("Meijer no longer lists it, so it is skipped.") == 1
    for name, rows in again["rows"].items():
        assert dates_in(rows).count(OLD1.iso) == 1, (name, dates_in(rows))
        assert statuses(rows, OLD1) != ["No Longer Listed"], name
        assert statuses(rows, OLD2) == ["No Longer Listed"], name
    assert [o["Date"] for o in again["orders"]].count(OLD1.iso) == 1


# -- a purchase that drops off a second time ----------------------------------------------

@pytest.fixture(scope="module")
def known(attached, tmp_path_factory):
    """What a discovery of the whole list found, KNOWN, as its
    discovery.json, for the tests below that start from it."""
    folder = tmp_path_factory.mktemp("known")
    SITE.orders = orders_page(KNOWN)
    took = run(folder, attached, "--discover")
    assert len(by_date(took["discovery"])) == len(KNOWN), took["out"]
    return (folder / "out" / "discovery.json").read_text(encoding="utf-8")


def start_from(folder, known_list):
    out = folder / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "discovery.json").write_text(known_list, encoding="utf-8")


ONLY_C1 = ("--start-date", C1.iso, "--end-date", C1.iso)


def test_its_rows_go_into_the_csvs_once_even_when_it_drops_off_again(attached, known, tmp_path,
                                                                     monkeypatch):
    """It drops off, a later discovery finds it again although its row is
    gone by the time it is looked for, so it fails that run, and the run
    after says once more that it has dropped off. Its rows as no longer
    listed are in each CSV once."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2])
    first = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)
    assert by_date(first["progress"])[C1.iso]["state"] == "No Longer Listed", first["out"]

    SITE.orders = orders_page([K1, K2, C1])
    real = app_mod.App.process_purchases

    def then_without_it(self, purchases, dry_run=False):
        SITE.orders = orders_page([K1, K2])
        return real(self, purchases, dry_run=dry_run)
    monkeypatch.setattr(app_mod.App, "process_purchases", then_without_it)
    second = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)
    assert by_date(second["progress"])[C1.iso]["state"] == "Failed", second["out"]

    monkeypatch.setattr(app_mod.App, "process_purchases", real)
    third = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)
    assert by_date(third["progress"])[C1.iso]["state"] == "No Longer Listed", third["out"]
    for name, rows in third["rows"].items():
        assert dates_in(rows) == [C1.iso], (name, dates_in(rows))


# -- a list that draws its rows a few at a time -----------------------------------------

def test_discovery_reads_a_list_that_draws_its_rows_a_few_at_a_time(attached, tmp_path,
                                                                     monkeypatch, growing):
    """The rows come one at a time, one more each time the app counts them.
    Read at its first rows, discovery found the two drawn by then and left
    the rest for a later run."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 10000, raising=False)
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 1500, raising=False)
    SITE.orders = orders_page(GROWING, grows=True)
    took = run(tmp_path, attached, "--discover")

    found = sorted((r["purchase_date"], r["total"]) for r in took["discovery"].values())
    assert found == sorted((r.iso, r.amount) for r in GROWING), took["out"]


def test_a_list_still_drawing_its_rows_is_judged_once_they_stop(attached, tmp_path, monkeypatch,
                                                                growing):
    """The rows come one at a time, one more each time the app counts them,
    and the purchase's row is the last. The press gives up on it while the
    list is still drawing, and only once the rows stop changing is it
    looked for again and saved. The one that has dropped off is judged
    against the whole list, so the date it names is the oldest of all of
    it, not of the rows drawn when the press gave up."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 10000, raising=False)
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 1500, raising=False)
    SITE.orders = orders_page(GROWING + [GONE])
    run(tmp_path, attached, "--discover")
    SITE.orders = orders_page(GROWING, grows=True)
    last = GROWING[-1]
    took = run(tmp_path, attached, "--all", "--yes", "--start-date", GONE.iso,
               "--end-date", last.iso)

    assert took["asked"] == [last.iso, GONE.iso], took["asked"]
    records = by_date(took["progress"])
    assert records[last.iso].get("downloaded_ok") is True, took["out"]
    assert records[GONE.iso]["state"] == "No Longer Listed", took["out"]
    assert "Its In-Store Receipts tab goes back to %s" % last.iso in took["out"], took["out"]


def test_a_list_that_never_stops_changing_is_never_read_as_whole(attached, tmp_path,
                                                                  monkeypatch, growing):
    """Rows go on coming for as long as the tab is open, one more each time
    the app counts them, every one newer than the purchase. However long it
    is watched the list was never seen whole, so the purchase is not said to
    have dropped off it. It is a failure, and the next run looks for it
    again."""
    SITE.orders = orders_page([GONE])
    run(tmp_path, attached, "--discover")
    SITE.orders = orders_page([], grows=True, endless=True)
    took = run(tmp_path, attached, "--all", "--yes", "--start-date", GONE.iso,
               "--end-date", GONE.iso)

    rec = by_date(took["progress"])[GONE.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Meijer no longer lists" not in took["out"]
    [attempt] = took["attempts"] or [{}]
    assert attempt.get("outcome") == "its row is not on the page", attempt
    settled = notes_in(attempt, "the rows once they settled")
    assert settled and not any(n["settled"] for n in settled), attempt
    assert all(n["discovery_read_the_tab"] and n["back_twenty_months"] for n in judged(attempt))


# -- a list that shows only part of what Meijer holds -----------------------------------
#
# Each list goes back far enough and draws no newer purchase than the one
# looked for, which is older than every row it shows, and the run's own
# discovery read it. Only what each test names keeps the purchase from
# being said to have dropped off.

FAILED = "Its row is not on Meijer's In-Store Receipts tab, so nothing was pressed."


def kept_a_failure(took, receipt):
    rec = by_date(took["progress"])[receipt.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Meijer no longer lists" not in took["out"]
    assert FAILED in took["out"], took["out"]
    for rows in took["rows"].values():
        assert receipt.iso not in dates_in(rows)


def test_rows_behind_a_load_more_button_are_never_taken_for_dropped(attached, known, tmp_path):
    """The tab draws its newest rows and a Load more button, which nothing
    presses, and the two oldest behind it. They are on Meijer's list, so
    each stays a failure the next run looks for again."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2], later=[C1, C2])
    took = run(tmp_path, attached, "--all", "--yes", "--start-date", C2.iso, "--end-date", C1.iso)

    for r in (C1, C2):
        kept_a_failure(took, r)
    assert len(took["attempts"] or []) == 2, took["attempts"]
    for attempt in took["attempts"]:
        assert [n["more_controls"] for n in judged(attempt)] == [1, 1], attempt
        assert all(n["earlier_than_every_row"] and n["back_twenty_months"] for n in judged(attempt))


def test_a_list_under_a_remembered_filter_is_never_taken_for_the_whole(attached, known, tmp_path):
    """The tab remembers a choice of the last six months and draws only
    those. The purchase is older, and on Meijer's list all the same."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([F1, F2], choose=True)
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["more_controls"] for n in judged(attempt)] == [1, 1], attempt


def test_a_list_that_goes_back_less_than_twenty_months_is_never_taken_for_the_whole(
        attached, known, tmp_path):
    """Meijer answers with its newest receipts only, as it might while it
    slows requests down, and shows no control for more. A list going back
    a few months is not taken for all it holds."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([F1, F2])
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["back_twenty_months"] for n in judged(attempt)] == [False, False], attempt
    assert [n["more_controls"] for n in judged(attempt)] == [0, 0], attempt


def test_resume_never_decides_it(attached, known, tmp_path):
    """A Resume after a list read whole reads no list of its own before it
    presses, so what a purchase's tab shows then is never taken for all of
    Meijer's list. The run that stopped and told the person to press Resume
    did so because Meijer seemed to be slowing requests, when a short list
    is likeliest. A Resume after a listing that stopped reads the list
    first, as Run All does, and decides only as Run All decides."""
    start_from(tmp_path, known)
    (tmp_path / "out" / "last-listing.json").write_text(
        json.dumps({"complete": True, "at": "2026-01-20T10:00:00"}), encoding="utf-8")
    mark_saved(tmp_path, [F1, F2, K1, K2, C2])
    SITE.orders = orders_page([K1, K2])
    took = run(tmp_path, attached, "--resume")

    assert took["asked"] == [C1.iso], took["asked"]
    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["discovery_read_the_tab"] for n in judged(attempt)] == [False, False], attempt


def test_a_run_whose_discovery_could_not_read_the_tab_never_decides_it(attached, known, tmp_path,
                                                                        monkeypatch):
    """The In-Store tab draws nothing while discovery reads it, and the run
    goes on with the Online order it found. By the time the purchase is
    looked for the tab draws its rows, which the run's discovery never read."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([], online=ONLINE_ORDER)
    real = app_mod.App.process_purchases

    def then_drawn(self, purchases, dry_run=False):
        SITE.orders = orders_page([K1, K2])
        return real(self, purchases, dry_run=dry_run)
    monkeypatch.setattr(app_mod.App, "process_purchases", then_drawn)
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    assert "Nothing showed on Meijer's In-Store Receipts tab" in took["out"], took["out"]
    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["discovery_read_the_tab"] for n in judged(attempt)] == [False, False], attempt


@pytest.mark.parametrize("brings", ["more rows", "its row"])
def test_a_list_that_draws_more_as_it_is_scrolled_is_never_taken_for_the_whole(
        attached, known, tmp_path, brings):
    """The list draws more of itself once it is scrolled to its end. Its
    row is looked for again then, and saved when it came, and a list that
    drew more as it was scrolled is never taken for all Meijer holds."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2], scrolled=[S1] if brings == "more rows" else [C1])
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    if brings == "its row":
        rec = by_date(took["progress"])[C1.iso]
        assert rec.get("downloaded_ok") is True, took["out"]
        assert Path(rec["pdf_path"]).read_bytes() == C1.pdf()
        return
    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    scrolled = notes_in(attempt, "the rows once scrolled to the end")
    assert [n["changed"] for n in scrolled] == [True, True], attempt


def test_rows_a_scroll_brings_slowly_are_waited_for(attached, known, tmp_path, monkeypatch,
                                                    growing):
    """Scrolled to its end, the list fetches an older receipt, which comes
    only after the app has counted the rows four more times, two seconds at
    the least, longer than the rows' usual quiet of one. The quiet after a
    scroll, four seconds here, is longer still, so the new row is seen and
    the list is not taken for all Meijer holds."""
    monkeypatch.setattr(site, "SCROLL_STEADY_MS", 4000, raising=False)
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2], scrolled=[S1], scroll_after=4)
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    scrolled = notes_in(attempt, "the rows once scrolled to the end")
    assert [n["changed"] for n in scrolled] == [True, True], attempt


def test_a_list_on_a_page_the_browser_is_not_showing_is_never_taken_for_the_whole(
        attached, known, tmp_path):
    """The page says the browser is not showing it, and such a page may not
    draw what scrolling asks of it."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2], hidden=True)
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    settled = notes_in(attempt, "the rows once they settled")
    assert [n["page_visible"] for n in settled] == [False, False], attempt


def test_a_page_without_the_tab_never_decides_it(attached, known, tmp_path):
    """The page draws the rows with no tabs at all, so no look opened the
    In-Store Receipts tab, and what it draws is not taken for that list."""
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2], tabs=False)
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["tab_opened"] for n in judged(attempt)] == [False, False], attempt


def test_controls_that_could_not_be_read_count_as_ones_that_show_more(attached, known, tmp_path,
                                                                     monkeypatch):
    """The page does not answer when asked what controls the list shows,
    the way a stalled page does not, and that is never taken for none."""
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout
    script = getattr(site, "_MORE_CONTROLS_JS", None)
    real = Page.evaluate

    def evaluate(self, expression, *args, **kwargs):
        if script is not None and expression == script:
            raise PlaywrightTimeout("Timeout exceeded, a stalled read.")
        return real(self, expression, *args, **kwargs)
    monkeypatch.setattr(Page, "evaluate", evaluate)
    start_from(tmp_path, known)
    SITE.orders = orders_page([K1, K2])
    took = run(tmp_path, attached, "--all", "--yes", *ONLY_C1)

    kept_a_failure(took, C1)
    [attempt] = took["attempts"] or [{}]
    assert [n["controls_read"] for n in judged(attempt)] == [False, False], attempt


def test_a_purchase_this_runs_discovery_found_is_never_taken_for_one_no_longer_listed(
        attached, tmp_path, monkeypatch):
    """Discovery reads the list with the purchase on it, and the page its
    row is looked for on a moment later no longer shows it. It was on the
    list, so it is a failure, however old it is."""
    SITE.orders = orders_page([R1, OLD1])
    real = app_mod.App.process_purchases

    def then_without_it(self, purchases, dry_run=False):
        SITE.orders = orders_page([R1])
        return real(self, purchases, dry_run=dry_run)
    monkeypatch.setattr(app_mod.App, "process_purchases", then_without_it)
    took = run(tmp_path, attached, "--all", "--yes")

    rec = by_date(took["progress"])[OLD1.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Its row is not on Meijer's In-Store Receipts tab" in took["out"], took["out"]
    [attempt] = took["attempts"] or [{}]
    assert [(n["earlier_than_every_row"], n["listed_by_discovery"]) for n in judged(attempt)] == \
        [(True, True), (True, True)], attempt


def test_it_has_dropped_off_only_when_every_look_finds_so(attached, tmp_path, monkeypatch):
    """The first look finds the list going back past the purchase's date,
    and the second, a moment later, a list that no longer does. The second
    look alone does not make it one Meijer no longer lists. It is a
    failure, and the next run looks for it again."""
    SITE.orders = orders_page([R1, OLD1, OLD2])
    run(tmp_path, attached, "--discover")
    SITE.orders = orders_page([R1, OLD2])
    real = getattr(site, "listed_rows", None)

    def then_shorter(page, purchase_type):
        got = real(page, purchase_type)
        SITE.orders = orders_page([R1])
        return got
    monkeypatch.setattr(site, "listed_rows", then_shorter, raising=False)
    took = run(tmp_path, attached, "--all", "--yes", "--start-date", OLD1.iso,
               "--end-date", OLD1.iso)

    rec = by_date(took["progress"])[OLD1.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Meijer no longer lists" not in took["out"]
    [attempt] = took["attempts"] or [{}]
    assert [n["earlier_than_every_row"] for n in judged(attempt)] == [False, True], attempt


# -- reading the list ------------------------------------------------------------------------

@contextlib.contextmanager
def a_page():
    """A page in Playwright's own Chromium, started and stopped here, since
    no app runs in these tests."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        yield browser.new_page()
    finally:
        browser.close()
        driver.stop()


def test_the_oldest_date_a_list_shows_is_read_only_when_every_row_shows_one():
    """A row whose date cannot be read could be the oldest, so then the
    list is not said to go back to any date."""
    with a_page() as pg:
        pg.set_content("<main><ul>%s%s</ul></main>" % (R1.row(), R3.row()))
        assert site.listed_rows(pg, "In-Store") == {"rows": 2, "oldest": R3.iso}
        undated = R3.row().replace("05/20/2026", "13/45/2026")
        pg.set_content("<main><ul>%s%s</ul></main>" % (R1.row(), undated))
        assert site.listed_rows(pg, "In-Store") == {"rows": 2, "oldest": ""}


def many(count):
    """`count` receipts two days apart, the newest first."""
    first = date(2026, 9, 30)
    return [Receipt(date.fromordinal(first.toordinal() - 2 * i).isoformat(),
                    "$%d.%02d" % (10 + i // 100, i % 100), 2) for i in range(count)]


def test_the_oldest_date_is_not_read_off_a_list_longer_than_the_collector_reads():
    """The collector hands back at most ROWS_CAP rows, so on a longer list
    the last row it read is not the list's oldest, and no oldest date is
    read off it. A shorter list still gives its oldest row."""
    longer, shorter = many(401), many(399)
    with a_page() as pg:
        pg.set_content("<main><ul>%s</ul></main>" % "".join(r.row() for r in longer))
        assert site.listed_rows(pg, "In-Store")["oldest"] == ""
        assert site.rows_capped(pg) is True
        pg.set_content("<main><ul>%s</ul></main>" % "".join(r.row() for r in shorter))
        assert site.listed_rows(pg, "In-Store") == {"rows": 399, "oldest": shorter[-1].iso}
        assert site.rows_capped(pg) is False


class _Capped:
    """A page that always draws as many rows as the collector reads, on a
    clock of this test's own, moved only by its waits."""

    def __init__(self, clock):
        self.clock = clock

    def evaluate(self, script, arg=None):
        row = {"text": "In-Store: 05/20/2026\n18 Example Road\n$31.90", "shown": True, "links": []}
        return [dict(row) for _ in range(getattr(site, "ROWS_CAP", 400))]

    def wait_for_timeout(self, ms):
        self.clock[0] += ms / 1000.0


def test_a_list_the_collector_stopped_reading_is_never_taken_as_settled(monkeypatch):
    """Its count holds still at the cap however long it is watched, since
    the collector reads no further, so that is no sign the list has stopped
    drawing."""
    clock = [0.0]
    monkeypatch.setattr(site, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    got = site.settle_rows(_Capped(clock), "In-Store", wait_ms=10000)
    assert got["settled"] is False, got


def test_a_list_the_collector_stopped_reading_gives_no_oldest_date():
    assert site.listed_rows(_Capped([0.0]), "In-Store")["oldest"] == ""


# A list's main content, with the two tabs, two rows and what each test adds.
LIST_PAGE = ("<main><h1>Orders and Receipts</h1><div role='tablist'>"
             "<a role='tab' href='#'>Online Orders</a><a role='tab' href='#'>In-Store Receipts</a>"
             "</div><div id='store'><ul>%s%s</ul>%s</div></main>")

# Controls a list of words that say "more" missed (review).
CONTROLS = {
    "a load more with a number": "<button>Load 20 more</button>",
    "a show more with a number": "<a href='#'>Show 10 more</a>",
    "a plus more": "<button>+ More</button>",
    "an arrow": "<button>&#8594;</button>",
    "a year": "<button>2025</button>",
    "a month": "<button>March</button>",
    "all receipts": "<a href='#'>All receipts</a>",
    "a div that answers a click": "<div onclick='void 0'>Earlier receipts</div>",
    "a div shown as clickable": "<div style='cursor:pointer'>Earlier receipts</div>",
    "a summary": "<details><summary>Filters</summary><p>Any</p></details>",
    "a tab of its own": "<div role='tab'>Pickup</div>",
    "a radio": "<div role='radio' aria-checked='true'>2024</div>",
    "an option": "<div role='option'>Last year</div>",
    "a menu item": "<div role='menuitem'>Archive</div>",
    "a span a keyboard reaches": "<span tabindex='0'>Older</span>",
    "a dropdown": "<select><option>Last 6 months</option></select>",
}


def test_every_control_but_the_tabs_and_the_rows_own_links_counts():
    """Any control the list shows may show more of it or a narrower part of
    it, whatever it says, so each of these counts as one, and so does one on
    a row that is neither its receipt link nor its details link."""
    counted = {}
    with a_page() as pg:
        for name, control in CONTROLS.items():
            pg.set_content(LIST_PAGE % (K1.row(), K2.row(), control))
            counted[name] = site.more_controls(pg)
        on_a_row = K2.row().replace("</li>", "<button>See all 12 receipts</button></li>")
        pg.set_content(LIST_PAGE % (K1.row(), on_a_row, ""))
        counted["a button on a row"] = site.more_controls(pg)
    assert counted == {name: 1 for name in list(CONTROLS) + ["a button on a row"]}, counted


def test_the_tabs_and_the_rows_own_receipt_and_details_links_do_not_count():
    details = K2.row().replace("</li>", "<a href='/shopping/order-details/1'>View order details</a></li>")
    with a_page() as pg:
        pg.set_content(LIST_PAGE % (K1.row(), details, ""))
        assert site.more_controls(pg) == 0


def test_a_pause_right_after_a_read_is_never_counted_as_the_rows_holding_still(monkeypatch):
    """This program is held up right after it reads three rows, longer than
    the rows have to hold still, and the page draws a fourth meanwhile. The
    time it was held up is not time anything saw the count stay the same,
    so the wait goes on, reads the fourth row, and settles on four. Time is
    this test's own clock, moved only by the page's waits and the hold-up."""
    clock = [0.0]
    monkeypatch.setattr(site, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 1500, raising=False)
    row = {"text": "In-Store: 05/20/2026\n18 Example Road\n$31.90", "shown": True, "links": []}

    class Page:
        reads = 0

        def evaluate(self, script, arg=None):
            self.reads += 1
            drawn = 3 if self.reads <= 2 else 4
            if self.reads == 2:
                clock[0] += 1.6     # held up after this read, while the fourth row comes
            return [dict(row) for _ in range(drawn)]

        def wait_for_timeout(self, ms):
            clock[0] += ms / 1000.0

    assert site.settle_rows(Page(), "In-Store", wait_ms=10000) == \
        {"rows": 4, "changed": True, "settled": True}
