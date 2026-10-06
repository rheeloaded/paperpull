"""Summaries without their items in Manual Review, on a tester's 0.43.0 Pilot (#63).

By late September Walmart's order pages folded their items away, 0.41.0
printed them that way, and the summaries it printed went to Manual Review.
On 0.43.0 his Pilot listed three invoices in Manual Review, summaries
without items again, and nothing the run printed said which of two things
had happened.

A copy put aside counts as done while it is in Manual Review, and the run
skipped it saying "Already completed and PDF verified", so a run that only
skipped the copies an earlier version put aside read the same as one that
put them there again. It says now that an earlier run put it aside, and
that deleting it there has the next run fetch it again.

Or the run did print, and Walmart's own invoice, the block its Print
invoice button prints, was not filled the one time the app looked, so the
order page was printed in its place without a word. The block is waited
for now, up to about fifteen seconds, and taken only when it names this
order by its number or its total. When the page is printed instead the run
says so, and the journal and the failure file say whether the block was
missing, empty or found, how much text it held and how many item rows.

And when no item name could be read from the page, a summary printing the
order's number and total passed as done. A document whose order has items
by its own account has to print an item row now, and one whose order counts
none and lists none is kept as before.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine, a
server of each test's own, and the browser resolves no host name, so
nothing reaches Walmart. Walmart's Print invoice is never pressed. Every
order number, item and amount is invented.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import receipt_pdf
from paperpull_core import testkit
from paperpull_core.models import IN_STORE, ONLINE, Item

# Fifteen digits, as an online order's key is, printed as seven, a dash and
# eight.
ORDER = "100000000000071"
PRINTED = "1000000-00000071"
ITEMS = ("Invented Garden Kneeler, Green", "Invented Watering Can, 2 gal")
PRICES = ("$15.12", "$6.33")

# Another order's invoice, left in the block of this order's page.
OTHER_PRINTED = "1000000-00000083"
OTHER_ITEMS = ("Invented Desk Fan, White", "Invented Extension Cord, 6 ft")
OTHER_PRICES = ("$11.08", "$8.77")

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# What a run says, word for word.
PUT_ASIDE = ("Put aside in Manual Review by an earlier run, so it is skipped. "
             "Delete it there to have it fetched again.")
DONE = "Already completed and PDF verified - skipping."
PRINTED_INSTEAD = {
    "missing": "Walmart's own invoice never appeared on this order page, "
               "so the page itself is printed instead.",
    "empty": "Walmart's own invoice stayed empty on this order page, "
             "so the page itself is printed instead.",
    "unverified": "Walmart's own invoice on this order page names neither this "
                  "order's number nor its total, so the page itself is printed instead.",
}
NO_ITEMS = "Prints no items, though the order has 2 items"

LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<header><a href="/">Walmart</a> Save money. Live better.</header>
<h1>Purchase history</h1>
<div data-testid="order-0">
  <p>Delivered</p><p>$22.74</p>
  <a href="#" data-automation-id="view-order-details-link-%s">View details</a>
</div>
</body></html>""" % ORDER

# The order page as Walmart lays it out now, as test_a_receipt_prints_its_items
# measured it. The item list starts folded, and the print style hides it
# open or not, so a print of the page is a summary with no item on it.
PAGE = """<!doctype html><html><head><title>Order details</title><style>
.item-list { display: none }
.item-list.open { display: block }
@media print {
  .site-header, .items-header, .item-list, .site-footer, .screen-count
    { display: none !important }
}
</style></head><body>
<div class="site-header"><a href="/">Walmart</a> Departments Services</div>
<main>
  <h1>Sep 14, 2026 order</h1>
  <p>Order# %(printed)s</p>
  <button data-automation-id="print-link"
    onclick="window.__printPressed = true; window.print()">Print invoice</button>
  <div class="items-header">Delivered Sep 14, 2026 %(header)s
    <button data-automation-id="items-toggle-link" aria-label="Show items"
      aria-expanded="false" onclick="showItems(this)">v</button>
  </div>
  %(tiles)s
  <p>%(subtotal)s $21.45</p><p>Taxes $1.29</p><p>Total $22.74</p>
  <p>Order# %(printed)s</p>
</main>
<div class="site-footer">All Departments Store Directory</div>
<script>
function showItems(button) {
  const open = button.getAttribute('aria-expanded') !== 'true';
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
  const list = document.querySelector('.item-list');
  if (list) list.classList.toggle('open', open);
}
</script>
%(invoice)s
</body></html>"""

# The folded list, whose names the app reads once it opens the list.
TILES = """<div class="item-list">
  <div data-testid="itemtile-stack"><div data-testid="productName">%s</div>
    <div>Qty 1</div><div data-testid="line-price">%s</div></div>
  <div data-testid="itemtile-stack"><div data-testid="productName">%s</div>
    <div>Qty 1</div><div data-testid="line-price">%s</div></div>
</div>""" % (ITEMS[0], PRICES[0], ITEMS[1], PRICES[1])

LOGO = "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs="


def invoice_inside(printed=PRINTED, items=ITEMS, prices=PRICES, date="Sep 14, 2026",
                   subtotal="$21.45", taxes="$1.29", total="$22.74"):
    """What Walmart's own invoice holds, its rows each with a quantity."""
    return """
  <div><img loading="lazy" alt="" width="174" height="42" src="%s"><span>Invoice</span></div>
  <div><span>%s order</span><span>Order# %s</span></div>
  <div>
    <div><span>%s</span><span>Delivered</span><span>Qty 1</span><span>%s</span></div>
    <div><span>%s</span><span>Delivered</span><span>Qty 1</span><span>%s</span></div>
  </div>
  <div>Subtotal (2 items) %s</div><div>Taxes %s</div><div>Total %s</div>
  <div>Order# %s</div>""" % (LOGO, date, printed, items[0], prices[0], items[1], prices[1],
                             subtotal, taxes, total, printed)


# The block, hidden by its own inline style until Walmart's button shows it.
BLOCK = ('<div class="print-portal-root" aria-hidden="true" style="display: none;">'
         '<div data-testid="print-invoice-layout">%s</div></div>')

# A block that fills two seconds after the app has read the page and found
# it to be this order's, which is when the app goes on to print it. Tied to
# that step rather than to the page's load, since the app reads a page for
# a few seconds before it prints, and a block filled by then would come
# before even one look. Once the run has printed the page the block is left
# as it was, as though the run had gone on, so a run that printed before the
# block filled is not saved by the look its second try makes.
LATE = BLOCK % "" + """
<template id="later">%s</template>
<script>
(function wait() {
  fetch('/gate', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t === 'open') setTimeout(fill, 2000);
    else setTimeout(wait, 100);
  }, () => setTimeout(wait, 100));
})();
function fill() {
  fetch('/may-fill', {cache: 'no-store'}).then(r => r.text()).then(t => {
    if (t !== 'yes') return;
    document.querySelector('[data-testid=print-invoice-layout]').innerHTML =
      document.getElementById('later').innerHTML;
    fetch('/filled', {cache: 'no-store'});
  });
}
</script>""" % invoice_inside()

INVOICES = {
    "filled": BLOCK % invoice_inside(),
    "late": LATE,
    "missing": "",
    "empty": BLOCK % "",
    "another": BLOCK % invoice_inside(printed=OTHER_PRINTED, items=OTHER_ITEMS,
                                      prices=OTHER_PRICES, date="Aug 2, 2026",
                                      subtotal="$19.85", taxes="$1.39", total="$21.24"),
}


SUBTOTALS = {True: "Subtotal (2 items)",
             # Counted on screen, and the count hidden from the print.
             "screen": 'Subtotal <span class="screen-count">(2 items)</span>',
             False: "Subtotal"}


def order_page(invoice="missing", names=True, counted=True):
    """`names` is whether the folded list's item names can be read, and
    `counted` whether the page counts the order's items beside its subtotal,
    True, False, or "screen" for a count its print leaves out."""
    return PAGE % {"printed": PRINTED,
                   "header": "2 items" if counted else "",
                   "tiles": TILES if names else "",
                   "subtotal": SUBTOTALS[counted],
                   "invoice": INVOICES[invoice]}


class FakeWalmart:
    """What the made-up site shows and what it saw, one for each test."""

    def __init__(self):
        self.page = order_page()
        self.seen = []
        self.gate = threading.Event()       # the app has read the page and checked it
        self.printed = threading.Event()    # the app has printed something
        self.filled = threading.Event()     # the late block filled
        self.at = {}

    def opened(self) -> int:
        return self.seen.count("/orders/" + ORDER)


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        state = self.server.walmart
        path = urlsplit(self.path).path
        state.seen.append(path)
        if path == "/orders":
            self._answer(LISTED)
        elif path == "/orders/" + ORDER:
            self._answer(state.page)
        elif path == "/gate":
            self._answer("open" if state.gate.is_set() else "wait", "text/plain")
        elif path == "/may-fill":
            self._answer("no" if state.printed.is_set() else "yes", "text/plain")
        elif path == "/filled":
            state.at.setdefault("filled", time.monotonic())
            state.filled.set()
            self._answer("ok", "text/plain")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


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


@pytest.fixture()
def walmart(monkeypatch):
    """A made-up Walmart of this test's own, every address the app opens
    pointed at it, and every wait short. When the app has read and checked
    the order page, and when it prints, is written down as it happens."""
    state = FakeWalmart()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.walmart = state
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    server = "http://127.0.0.1:%d" % httpd.server_address[1]

    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setitem(site.FILTER_URL, ONLINE, server + "/orders?filterIds=online")
    monkeypatch.setitem(site.FILTER_URL, IN_STORE, server + "/orders?filterIds=in-store")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 3000, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    # A details address is built on Walmart's own host, and only an address
    # on it is opened. Here that host is this machine.
    real_card = site.card_to_purchase
    monkeypatch.setattr(site, "card_to_purchase",
                        lambda card, kind: real_card(card, kind, base_url=server))
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")

    real_check = site.not_this_purchase

    def checked(page, number):
        why = real_check(page, number)
        state.at.setdefault("checked", time.monotonic())
        state.gate.set()
        return why

    monkeypatch.setattr(site, "not_this_purchase", checked)
    real_print = receipt_pdf.print_page_to_pdf

    def printing(page, out_path, *args, **kwargs):
        state.at.setdefault("printed", time.monotonic())
        state.printed.set()
        return real_print(page, out_path, *args, **kwargs)

    monkeypatch.setattr(receipt_pdf, "print_page_to_pdf", printing)
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()


def short_wait(monkeypatch, ms):
    """The invoice waited for this long rather than its fifteen seconds."""
    monkeypatch.setattr(site, "INVOICE_WAIT_MS", ms, raising=False)


def pilot(tmp_path, cdp_url, capsys):
    """An online Pilot, and what it printed with its line breaks read as
    spaces, since a message is wrapped wherever it happens to fill a line."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    assert app_mod.main(["--pilot-online", "--config", str(cfg)]) == 0
    return " ".join(capsys.readouterr().out.split())


def record(tmp_path):
    progress = json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))
    return progress["Online:" + ORDER]


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages).split())


def saved(tmp_path, folder=""):
    return sorted((tmp_path / "out" / folder).rglob("*.pdf"))


def kept_with_its_items(rec, tmp_path):
    path = Path(rec["pdf_path"])
    assert rec.get("downloaded_ok") is True, rec
    assert path.parent == tmp_path / "out" / "Invoices" and path.exists(), rec
    text = pdf_text(path)
    for name in ITEMS:
        assert name in text, text
    assert PRINTED in text and text.count("Total $22.74") == 1, text


def put_aside(rec, tmp_path):
    path = Path(rec["pdf_path"])
    assert rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok"), rec
    assert path.parent == tmp_path / "out" / "Manual Review" and path.exists(), rec
    assert not saved(tmp_path, "Invoices"), "kept as the order's invoice"


def failure_file(tmp_path):
    written = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(written) == 1, written
    raw = written[0].read_text(encoding="utf-8")
    return raw, json.loads(raw)


# Every value the pages carry, none of which may reach a failure file.
VALUES = (ORDER, PRINTED, OTHER_PRINTED, "Garden Kneeler", "Watering Can", "Desk Fan",
          "Extension Cord", "21.45", "22.74", "15.12", "21.24")


# -- a copy put aside says so when it is skipped -------------------------------------------

def test_a_copy_put_aside_is_skipped_saying_so_and_fetched_again_once_deleted(
        attached, walmart, tmp_path, capsys, monkeypatch):
    """The first run prints the order page, its items folded away, and puts
    the summary aside. By the second Walmart shows its own invoice, and the
    copy is skipped, saying it was put aside rather than that it passed.
    Deleted, the next run fetches the order's own invoice, items and all,
    and the run after that has a purchase really done."""
    short_wait(monkeypatch, 0)
    pilot(tmp_path, attached, capsys)
    first = record(tmp_path)
    put_aside(first, tmp_path)
    copy = Path(first["pdf_path"])
    held = copy.read_bytes()

    walmart.page = order_page("filled")
    opened = walmart.opened()
    out = pilot(tmp_path, attached, capsys)
    assert PUT_ASIDE in out, out
    assert DONE not in out, out
    assert walmart.opened() == opened, "its order page is not opened again"
    assert copy.read_bytes() == held, "left where it is"
    assert record(tmp_path)["state"] == "Needs Manual Review"

    copy.unlink()
    out = pilot(tmp_path, attached, capsys)
    assert PUT_ASIDE not in out, out
    assert walmart.opened() == opened + 1
    kept_with_its_items(record(tmp_path), tmp_path)

    out = pilot(tmp_path, attached, capsys)
    assert DONE in out and PUT_ASIDE not in out, out


# -- Walmart's own invoice is waited for ---------------------------------------------------

def test_an_invoice_that_fills_two_seconds_late_is_waited_for_and_printed(
        attached, walmart, tmp_path, capsys):
    """At its own wait of about fifteen seconds. The app used to look once,
    find the block empty and print the page, a summary with no item on it."""
    walmart.page = order_page("late")
    out = pilot(tmp_path, attached, capsys)

    kept_with_its_items(record(tmp_path), tmp_path)
    assert walmart.filled.is_set(), "the block really did fill late"
    assert walmart.at["filled"] - walmart.at["checked"] >= 1.9, walmart.at
    assert walmart.at["filled"] < walmart.at["printed"], "printed only once it had filled"
    for said in PRINTED_INSTEAD.values():
        assert said not in out, out


@pytest.mark.parametrize("how", ["missing", "empty"])
def test_an_invoice_that_never_fills_is_said_and_written_down(
        attached, walmart, tmp_path, capsys, monkeypatch, how):
    """The page is printed in its place, which since late September leaves
    the items out, and the run says so in one sentence. The journal and the
    failure file say what became of the block, as a word from the fixed
    list and two counts, and nothing of the order's."""
    short_wait(monkeypatch, 1500)
    walmart.page = order_page(how)
    out = pilot(tmp_path, attached, capsys)

    assert PRINTED_INSTEAD[how] in out, out
    assert out.count(PRINTED_INSTEAD[how]) == 1, "said once, though the print is tried twice"
    assert walmart.at["printed"] - walmart.at["checked"] >= 1.4, "looked for, not glanced at"
    rec = record(tmp_path)
    put_aside(rec, tmp_path)
    assert "none of the order's items" in rec["notes"], rec

    raw, report = failure_file(tmp_path)
    block = {"state": how, "text_characters": 0, "item_rows": 0}
    assert report["extra"]["postmortem"]["invoice_block"] == block, report["extra"]
    results = [e for e in report["journal"]["entries"] if e.get("kind") == "result"]
    assert results and all(e["facts"]["invoice_block"] == block for e in results), results
    assert results[0]["outcome"] == "the order page is printed", results
    for value in VALUES:
        assert value not in raw, value


def test_another_orders_invoice_is_not_printed_as_this_ones(
        attached, walmart, tmp_path, capsys, monkeypatch):
    """The block is filled, with another order's number, items and total.
    It is not this order's invoice, so it is not printed in its place, and
    what was there is written down without a word of it."""
    short_wait(monkeypatch, 1500)
    walmart.page = order_page("another")
    out = pilot(tmp_path, attached, capsys)

    assert PRINTED_INSTEAD["unverified"] in out, out
    put_aside(record(tmp_path), tmp_path)
    for path in saved(tmp_path):
        assert OTHER_ITEMS[0] not in pdf_text(path), "the other order's invoice was printed"
    raw, report = failure_file(tmp_path)
    block = report["extra"]["postmortem"]["invoice_block"]
    assert block["state"] == "unverified" and block["item_rows"] == 2, block
    assert block["text_characters"] > 100, block
    for value in VALUES:
        assert value not in raw, value


# -- a summary with no item on it is put aside, names read or not -------------------------

@pytest.mark.parametrize("counted", [True, "screen"], ids=["counted in print", "on screen only"])
def test_a_summary_whose_item_names_were_not_read_is_put_aside(
        attached, walmart, tmp_path, capsys, monkeypatch, counted):
    """The folded list gave the app no name to look for, and the page counts
    two items, on the summary as well or only on screen. It printed the
    order's number and total and passed as done."""
    short_wait(monkeypatch, 0)
    walmart.page = order_page("missing", names=False, counted=counted)
    out = pilot(tmp_path, attached, capsys)

    rec = record(tmp_path)
    assert rec["items"] == [], rec
    put_aside(rec, tmp_path)
    assert NO_ITEMS in rec["notes"], rec
    assert "Validation failed (%s); moved to Manual Review" % NO_ITEMS in out, out
    assert ("(2 items)" in pdf_text(rec["pdf_path"])) is (counted is True)
    raw, report = failure_file(tmp_path)
    facts = report["extra"]["postmortem"]
    assert facts["item_names_read"] == 0 and facts["items_expected"] == 2, facts
    assert facts["item_rows_printed"] == 0, facts


def test_an_invoice_whose_item_names_were_not_read_is_kept(attached, walmart, tmp_path, capsys):
    """What a correct document looks like when no name could be read. Walmart's
    own invoice prints each item on a row of its own, with its quantity."""
    walmart.page = order_page("filled", names=False)
    pilot(tmp_path, attached, capsys)

    rec = record(tmp_path)
    assert rec["items"] == [], rec
    kept_with_its_items(rec, tmp_path)


def test_an_order_that_counts_no_items_and_lists_none_is_kept_as_before(
        attached, walmart, tmp_path, capsys, monkeypatch):
    """A document with no items by its nature is not asked for one. Nothing
    on the page counts or names an item, and its print names the order by
    its number and total, as it always had to."""
    short_wait(monkeypatch, 0)
    walmart.page = order_page("missing", names=False, counted=False)
    pilot(tmp_path, attached, capsys)

    rec = record(tmp_path)
    assert rec.get("downloaded_ok") is True, rec
    path = Path(rec["pdf_path"])
    assert path.parent == tmp_path / "out" / "Invoices", rec
    assert PRINTED in pdf_text(path)


# -- which invoice is this order's --------------------------------------------------------------

@pytest.mark.parametrize("text, named", [
    # Its number as Walmart prints it, and whole.
    ("Invoice\nSep 14, 2026 order\nOrder# 1000000-00000071\nQty 1", True),
    ("Invoice\nOrder 100000000000071\nQty 1", True),
    # Its total, with no number at all.
    ("Invoice\nSep 14, 2026 order\nQty 1\nTotal\n$22.74", True),
    # Another order's number and total, and a longer number holding this one.
    ("Invoice\nOrder# 1000000-00000083\nTotal\n$21.24", False),
    ("Invoice\nOrder# 91000000-00000071\nTotal\n$21.24", False),
    ("Invoice\nOrder# 1000000-000000711\nTotal\n$21.24", False),
])
def test_which_invoice_names_this_order(text, named):
    assert site.names_this_order(text, ORDER, "$22.74") is named


# -- how the order's items are counted and found on paper ------------------------------------

@pytest.mark.parametrize("text, counted", [
    ("Subtotal (2 items) $21.45", 2),
    ("Subtotal (1 item) $12.47", 1),
    ("SUBTOTAL\n(12 items)\n$80.00", 12),
    ("Subtotal $21.45", 0),
    # A count of what is in the cart is not the order's.
    ("Cart (3 items) Subtotal $21.45", 0),
    ("Subtotal (0 items) $0.00", 0),
])
def test_how_an_order_counts_its_items(text, counted):
    assert site.items_counted(text) == counted


@pytest.mark.parametrize("text, rows", [
    ("Invented Garden Kneeler, Green Delivered Qty 1 $15.12", 1),
    # The invoice's pieces side by side, read back run together, the way a
    # printed invoice came out in a real browser here.
    ("Invented Garden Kneeler, GreenDeliveredQty 1$15.12", 1),
    ("Invented Garden Kneeler\nShopped\nQty 1\n$15.12\nInvented Watering Can\nQty 2", 2),
    ("Quantity: 3", 1),
    ("Subtotal (2 items) $21.45 Taxes $1.29 Total $22.74", 0),
])
def test_how_an_item_row_is_known(text, rows):
    assert site.item_rows(text) == rows


LONG = "Invoice Sep 14, 2026 order Order# 1000000-00000071 "


@pytest.mark.parametrize("text, items, counted, why", [
    # The summary, counting its items, with no name to look for.
    (LONG + "Subtotal (2 items) $21.45 Total $22.74", [], 0, NO_ITEMS),
    # The page counts them and the paper does not.
    (LONG + "Subtotal $21.45 Total $22.74", [], 2, NO_ITEMS),
    # Read, but too short to look for.
    (LONG + "Subtotal $3.48 Total $3.48", [Item(name="Milk")], 0,
     "Prints no items, though the order has 1 item"),
    # Walmart's own invoice, its rows printed.
    (LONG + "Invented Garden Kneeler Qty 1 $15.12 Subtotal (2 items) $21.45", [], 0, ""),
    # Nothing counts an item or names one.
    (LONG + "Subtotal $21.45 Total $22.74", [], 0, ""),
    # Almost no text, a scan or a blank, judged as the check always judged it.
    ("Subtotal (2 items)", [], 0, ""),
    # Names read, as before. One printed is enough, none is not.
    (LONG + "Invented Garden Kneeler, Green $15.12", [Item(name=ITEMS[0])], 2, ""),
    (LONG + "Subtotal (2 items) $21.45", [Item(name=ITEMS[0])], 2,
     "Prints none of the order's items"),
])
def test_when_a_document_leaves_the_orders_items_out(text, items, counted, why):
    assert site.items_left_out(text, items, counted) == why
