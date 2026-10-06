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

Now a purchase older than every row its tab draws, once the rows have
stopped changing, is written down as no longer listed, with the oldest date
the list shows, and later runs skip it until a discovery finds it on the
list again. One missing from inside the range the list shows is a failure
that says so. Neither goes into the CSVs, and the file to attach keeps every
attempt of the run.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Meijer. Every store, date
and amount is invented.
"""
import contextlib
import io
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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


def orders_page(receipts, grow_ms=None, endless=False):
    """The orders page, open on Online Orders, which has none. Its In-Store
    rows are drawn when that tab is pressed and taken away when the other
    one is. All at once, or with `grow_ms` one at a time that many
    milliseconds apart, and with `endless`, made-up rows newer than any here
    go on coming after them for as long as the tab is open.

    A row's receipt link downloads the receipt from this site."""
    script = (
        "const ROWS = %s, GROW = %s, ENDLESS = %s; let timer = null;"
        "function made(k) {"
        " const d = new Date(2026, 7, 31 - k);"
        " const two = (n) => String(n).padStart(2, '0');"
        " const when = two(d.getMonth() + 1) + '/' + two(d.getDate()) + '/' + d.getFullYear();"
        " return \"<li class='order-card'><div class='date'>In-Store: \" + when + \"</div>\""
        "  + \"<div>18 Example Road</div><div class='totals'><span>$\" + (100 + k) + \".37</span>\""
        "  + \"&nbsp;&nbsp;3 items</div><a href='javascript:void(0)'>view receipt pdf</a></li>\"; }"
        "function show(which) {"
        " document.getElementById('online').style.display = which === 'online' ? '' : 'none';"
        " document.getElementById('store').style.display = which === 'store' ? '' : 'none';"
        " clearInterval(timer);"
        " const list = document.getElementById('rows');"
        " list.innerHTML = '';"
        " if (which !== 'store') return;"
        " if (GROW === null) { list.innerHTML = ROWS.join(''); return; }"
        " let n = 0;"
        " const add = () => {"
        "  if (n < ROWS.length) list.insertAdjacentHTML('beforeend', ROWS[n]);"
        "  else if (ENDLESS) list.insertAdjacentHTML('beforeend', made(n));"
        "  else { clearInterval(timer); return; }"
        "  n += 1; };"
        " add(); timer = setInterval(add, GROW); }"
        "function saveReceipt(rid) {"
        " const a = document.createElement('a');"
        " a.href = '/receipt/' + rid + '.pdf'; a.download = 'receipt.pdf';"
        " document.body.appendChild(a); a.click(); a.remove(); }"
        % (json.dumps([r.row() for r in receipts]),
           "null" if grow_ms is None else int(grow_ms), "true" if endless else "false"))
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
            "<h1>Orders and Receipts</h1><div role='tablist'>"
            "<a role='tab' href='#' onclick=\"show('online');return false\">Online Orders</a>"
            "<a role='tab' href='#' onclick=\"show('store');return false\">In-Store Receipts</a></div>"
            "<div id='online'><p>You haven't placed any orders yet</p></div>"
            "<div id='store' style='display:none'><ul id='rows'></ul></div>"
            "<script>%s</script></main></body></html>" % (HEADER, script))


class FakeMeijer:
    """What the made-up site shows, and what the app was seen to do. Each
    receipt is there to download whether or not the list shows it."""

    def __init__(self):
        self.orders = orders_page([])
        self.pdfs = {r.rid: r.pdf() for r in EVERY + GROWING + [GONE]}
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
    """Every address the app opens points at the made-up site, and every
    wait is short. Held for the whole file, since one history of runs is
    read by several tests. A tab's rows are given three seconds, the row a
    purchase is looked for two, and the rows count as settled after one
    second without a change.

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
    receipt step, and what it left in progress.json, the CSVs and the file
    to attach."""
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
    summary = folder / "out" / "run-summary.txt"
    return {"out": out, "result": json.loads(result[-1]) if result else {},
            "failures": list(SITE.failures), "asked": list(SITE.asked),
            "failure_files": [_json(p) for p in written],
            "progress": _json(folder / "out" / "progress.json", {}),
            "discovery": _json(folder / "out" / "discovery.json", {}),
            "attempts": attempt.get("attempts") if isinstance(attempt, dict) else None,
            "rows": rows,
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


def test_the_two_oldest_are_written_down_as_no_longer_listed(history):
    """Each says the oldest date the list still shows, writes no failure
    file, goes into neither CSV, and counts for no review. The receipts
    saved beside them count for review as they always did, since a store
    address names nothing the app can sort them by."""
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
        assert dates_in(rows) == sorted(r.iso for r in saved), (name, dates_in(rows))
    assert first["out"].count("What the page answered is in") == 1, \
        "only the failure asks for the file to be attached"


def test_a_purchase_missing_from_inside_the_listed_range_is_a_failure(history):
    """Its date is inside the range the list shows, so it is not said to
    have dropped off. It says what happened, and the next run looks for it
    again without writing it down a second time."""
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
    three. Each says its place in the run and what it came to."""
    first = history["first"]
    assert attempts_said(first) == [(3, 6, "its row is not on the page"),
                                     (5, 6, "dropped off the list"),
                                     (6, 6, "dropped off the list")], first["attempts"]
    gap, old1, old2 = first["attempts"]
    for a in (old1, old2):
        assert notes_in(a, "the oldest row the list shows") == [{
            "note": "the oldest row the list shows", "rows": 3,
            "earlier_than_every_row": True, "listed_by_discovery": False}] * 2, a
    assert all(not n["earlier_than_every_row"]
               for n in notes_in(gap, "the oldest row the list shows")), gap
    assert len(notes_in(gap, "the purchase's tab")) == 2, "two looks, as before"


def test_a_later_run_does_not_try_them_again(history):
    """The second run takes neither to the receipt step, says why it skips
    each, and adds nothing to the CSVs, where every saved receipt is still
    written once."""
    second = history["second"]
    assert OLD1.iso not in second["asked"] and OLD2.iso not in second["asked"], second["asked"]
    assert second["asked"] == [GAP.iso], second["asked"]
    assert second["out"].count("Meijer no longer lists it, so it is skipped.") == 2, second["out"]
    assert attempts_said(second) == [(3, 6, "its row is not on the page")]
    for name, rows in second["rows"].items():
        assert dates_in(rows) == sorted([R1.iso, R2.iso, R3.iso]), (name, dates_in(rows))
    records = by_date(second["progress"])
    assert records[OLD1.iso]["state"] == records[OLD2.iso]["state"] == "No Longer Listed"
    assert second["result"].get("failed") == 1 and "No longer listed:          2" in second["summary"]


def test_one_the_list_shows_again_is_tried_again(history):
    """A discovery that finds it on the list again puts it back, and the
    receipt is saved. The other is still skipped."""
    again = history["listed again"]
    assert ("1 purchase(s) Meijer had stopped listing are on its list again, so this run "
            "tries them again.") in again["out"], again["out"]
    assert again["asked"] == [GAP.iso, OLD1.iso], again["asked"]
    records = by_date(again["progress"])
    assert records[OLD1.iso].get("downloaded_ok") is True, records[OLD1.iso]
    assert Path(records[OLD1.iso]["pdf_path"]).read_bytes() == OLD1.pdf()
    assert records[OLD2.iso]["state"] == "No Longer Listed"
    assert again["out"].count("Meijer no longer lists it, so it is skipped.") == 1


# -- a list that draws its rows a few at a time ----------------------------------------

def test_discovery_reads_a_list_that_draws_its_rows_a_few_at_a_time(attached, tmp_path,
                                                                     monkeypatch):
    """The rows come one at a time for about six seconds after the tab is
    pressed. Read at its first rows, discovery found the few drawn by then
    and left the rest for a later run."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 10000, raising=False)
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 2500, raising=False)
    SITE.orders = orders_page(GROWING, grow_ms=800)
    took = run(tmp_path, attached, "--discover")

    found = sorted((r["purchase_date"], r["total"]) for r in took["discovery"].values())
    assert found == sorted((r.iso, r.amount) for r in GROWING), took["out"]


def test_a_list_still_drawing_its_rows_is_judged_once_they_stop(attached, tmp_path,
                                                                monkeypatch):
    """The rows come one at a time, and the purchase's row is the last. The
    press gives up on it while the list is still drawing, and only once the
    rows stop changing is it looked for again and saved. The one that has
    dropped off is judged against the whole list, so the date it names is
    the oldest of all of it, not of the rows drawn when the press gave up."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 10000, raising=False)
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 2500, raising=False)
    monkeypatch.setattr(site, "ROW_LOOKS", 1, raising=False)
    SITE.orders = orders_page(GROWING + [GONE])
    run(tmp_path, attached, "--discover")
    mark_saved(tmp_path, GROWING[:-1])
    SITE.orders = orders_page(GROWING, grow_ms=800)
    took = run(tmp_path, attached, "--all", "--yes")

    last = GROWING[-1]
    assert took["asked"] == [last.iso, GONE.iso], took["asked"]
    records = by_date(took["progress"])
    assert records[last.iso].get("downloaded_ok") is True, took["out"]
    assert records[GONE.iso]["state"] == "No Longer Listed", took["out"]
    assert "Its In-Store Receipts tab goes back to %s" % last.iso in took["out"], took["out"]


def test_a_list_that_never_stops_changing_is_never_read_as_whole(attached, tmp_path,
                                                                  monkeypatch):
    """Rows go on coming for as long as the tab is open, every one newer
    than the purchase. However long it is watched the list was never seen
    whole, so the purchase is not said to have dropped off it. It is a
    failure, and the next run looks for it again."""
    # Longer than a row's gap even where the browser lets a timer run late.
    monkeypatch.setattr(site, "ROWS_STEADY_MS", 2000, raising=False)
    SITE.orders = orders_page([GONE])
    run(tmp_path, attached, "--discover")
    SITE.orders = orders_page([], grow_ms=300, endless=True)
    took = run(tmp_path, attached, "--resume")

    rec = by_date(took["progress"])[GONE.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Meijer no longer lists" not in took["out"]
    [attempt] = took["attempts"] or [{}]
    assert attempt.get("outcome") == "its row is not on the page", attempt
    settled = notes_in(attempt, "the rows once they settled")
    assert settled and not any(n["settled"] for n in settled), attempt


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
    assert {"note": "the oldest row the list shows", "rows": 1, "earlier_than_every_row": True,
            "listed_by_discovery": True} in attempt.get("responses", []), attempt


def test_it_has_dropped_off_only_when_every_look_finds_so(attached, tmp_path, monkeypatch):
    """The first look finds the list going back past the purchase's date,
    and the second, a moment later, a list that no longer does. The second
    look alone does not make it one Meijer no longer lists. It is a
    failure, and the next run looks for it again."""
    SITE.orders = orders_page([OLD1])
    run(tmp_path, attached, "--discover")
    SITE.orders = orders_page([R1, OLD2])
    real = getattr(site, "listed_rows", None)

    def then_shorter(page, purchase_type):
        got = real(page, purchase_type)
        SITE.orders = orders_page([R1])
        return got
    monkeypatch.setattr(site, "listed_rows", then_shorter, raising=False)
    took = run(tmp_path, attached, "--resume")

    rec = by_date(took["progress"])[OLD1.iso]
    assert rec["state"] == "Failed", took["out"]
    assert "Meijer no longer lists" not in took["out"]
    [attempt] = took["attempts"] or [{}]
    assert [n["earlier_than_every_row"] for n in
            notes_in(attempt, "the oldest row the list shows")] == [False, True], attempt


def test_the_oldest_date_a_list_shows_is_read_only_when_every_row_shows_one():
    """A row whose date cannot be read could be the oldest, so then the
    list is not said to go back to any date."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        pg = browser.new_page()
        pg.set_content("<main><ul>%s%s</ul></main>" % (R1.row(), R3.row()))
        assert site.listed_rows(pg, "In-Store") == {"rows": 2, "oldest": R3.iso}
        undated = R3.row().replace("05/20/2026", "13/45/2026")
        pg.set_content("<main><ul>%s%s</ul></main>" % (R1.row(), undated))
        assert site.listed_rows(pg, "In-Store") == {"rows": 2, "oldest": ""}
    finally:
        browser.close()
        driver.stop()
