"""An online invoice that never says "Walmart", in a real browser (#63).

A tester's first Pilot printed three online orders, and every one was put
aside in Manual Review with "Extractable text does not mention
Walmart/order details". The check looks for a few words and passes a file
holding any one of them, the provider's name, the order number as the app
keeps it, the date written 2026-06-03, or the start of an item name read
from the order's page.

Measured over saved Walmart documents, value free, a Walmart document
prints its order number in hyphenated groups, seven digits, a hyphen and
eight on an online invoice, twice, and groups of four on a store receipt.
The unbroken number was on none of them, the date was never written that
way, and nearly every invoice never says Walmart. So an invoice passed only
when an item name came out on the paper the way it was read from the page,
and on the tester's pages none did. How his invoices differ is not known.
Here each name is cut short by the invoice's layout, one way a name read
on screen can be missing from the paper, and the invoice is known by the
order number it prints instead.

How they differed was found later. Walmart's print style had come to hide
the item list, so the invoices printed no items at all, and a document
that prints none of the order's items is put aside now (see
test_a_receipt_prints_its_items.py). A name cut short still counts as
printed when its first twelve letters and digits come out.

Nothing that is not this order's document may pass for it because of
that. A page printing another order's number, or a longer number holding
this one, and a page other than the order's own are turned away before
anything is printed, since the page is checked first (page_check), and the
order is asked for again on the next run. A heading that names the order
over an invoice that never came is printed and put aside. A file put aside
also used to be reported as "? bytes, ? pages" and left nothing to attach.

Every page is invented and served to Playwright's own Chromium from inside
the test. Every other request is refused, so nothing reaches Walmart or
any other site. Every order number, name, address, item and amount is
invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import walmart_receipts as app_mod
import walmart_site as site
from paperpull_core.models import ONLINE, Purchase

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

# Fifteen digits, as an online order's key is, and printed on its invoice
# as seven, a hyphen and eight.
ORDER = "100000000000011"
PRINTED = "1000000-00000011"
ANOTHER = "1000000-00000099"
LIST = "https://orders.example.invalid/orders"
ADDRESS = LIST + "/" + ORDER

# A details page laid out the way Walmart's behaves, as far as a saved
# document shows it. On screen the order with its item tiles, on paper only
# the invoice, which has no "Walmart" on it. The invoice's item column is
# narrow, so a long name is cut short there.
PAGE = """<!doctype html><html><head><title>Order details</title><style>
@media print { .screen-layout { display: none } }
@media screen { .print-invoice { display: none } }
.print-invoice .cut { display: inline-block; max-width: 8em; overflow: hidden;
  white-space: nowrap; text-overflow: ellipsis; vertical-align: bottom }
</style></head><body>
<div class="screen-layout">
  <header><a href="/">Walmart</a></header>
  <h1>Jun 3, 2026 order</h1>
  <p>Order# 1000000-00000011</p>
  <p>Delivered</p>
  <div data-testid="itemtile-stack"><span data-testid="productName">Invented Paper Towels, 6 Double Rolls</span><div>Qty 1</div><span data-testid="line-price">$12.47</span></div>
  <p>Subtotal $12.47</p><p>Tax $0.87</p><p>Total $13.34</p>
</div>
<div class="print-invoice">%s</div>
</body></html>"""

INVOICE = """
  <h2>Invoice</h2>
  <p>Jun 3, 2026 order</p>
  <p>Order# %(number)s</p>
  <p>Dana Example</p><p>100 Example Street, Springfield, ST 00000</p>
  <p><span class="%(name_class)s">Invented Paper Towels, 6 Double Rolls</span> Qty 1 $12.47</p>
  <p>Subtotal (1 item) $12.47</p><p>Tax $0.87</p><p>Total $13.34</p>
  <p>Order# %(number)s</p>
  <p>Payment method</p>"""


def invoice(number=PRINTED, name_cut=True):
    return PAGE % (INVOICE % {"number": number, "name_class": "cut" if name_cut else ""})


# The invoice's heading and nothing under it, no item and no amount.
HEADING_ONLY = PAGE % """
  <h2>Invoice</h2>
  <p>Jun 3, 2026 order</p>
  <p>Order# 1000000-00000011</p>"""

# Every value the page carries, none of which may reach a failure file.
VALUES = (ORDER, PRINTED, ANOTHER, "Dana Example", "Example Street",
          "Invented Paper Towels", "12.47", "13.34")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--disable-extensions", "--disable-sync", "--no-first-run",
            "--host-resolver-rules=MAP * ~NOTFOUND"])
        try:
            yield b
        finally:
            b.close()


@pytest.fixture()
def shown(browser):
    """What the invented order page shows, set by each test, and a page
    that has it open. The address of the list of orders shows something
    only when a test says what. Every other request is refused."""
    served = {"html": invoice(), "list": None}
    context = browser.new_context()

    def answer(route):
        address = route.request.url.split("?")[0]
        if address == ADDRESS:
            body = served["html"]
        elif address == LIST and served["list"] is not None:
            body = served["list"]
        else:
            route.abort()
            return
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)

    context.route("**/*", answer)
    served["page"] = context.new_page()
    yield served
    context.close()


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    """The invented host is the one order pages are opened on, and the
    scroll before a print is kept short."""
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: (url or "").startswith("https://orders.example.invalid/"))
    real = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=50: real(page, rounds, delay_ms))


def app_for(tmp_path, page):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg)]))
    app._work_page = page
    return app


def run_one(tmp_path, shown, html):
    """The order taken the way a run takes it, from opening its page to
    filing its document, and its record afterwards."""
    shown["html"] = html
    app = app_for(tmp_path, shown["page"])
    purchase = Purchase(purchase_type=ONLINE, order_number=ORDER, details_url=ADDRESS)
    app.process_one(shown["page"], purchase)
    return app, purchase, app.progress.get(purchase.key)


def put_aside(tmp_path, rec):
    path = Path(rec["pdf_path"])
    return (rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok")
            and path.parent == tmp_path / "out" / "Manual Review" and path.exists())


def refused(tmp_path, rec):
    """Turned away before anything was printed, and left for the next run."""
    return (rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok")
            and not list((tmp_path / "out").rglob("*.pdf")))


# An invoice that prints this order's own number, from an order page that
# shows no amount, so no total was read and the number is not enough. It
# passes the check of the page and is printed, then put aside.
NO_TOTAL = invoice().replace(
    "<p>Subtotal $12.47</p><p>Tax $0.87</p><p>Total $13.34</p>", "").replace(
    '<span data-testid="line-price">$12.47</span>', "")


# -- the invoice is known by its own order number ------------------------------------

def test_an_invoice_that_never_says_walmart_is_known_by_its_order_number(tmp_path, shown):
    """The report. The order's page was read, its date and its item, and
    its invoice printed with the item's name cut short and no "Walmart" on
    it. It went to Manual Review, and it is the order's own invoice."""
    app, purchase, rec = run_one(tmp_path, shown, invoice())

    assert rec["purchase_date"] == "2026-06-03", rec
    assert [i["name"] for i in rec["items"]] == ["Invented Paper Towels, 6 Double Rolls"]
    assert rec.get("downloaded_ok") is True, rec
    saved = Path(rec["pdf_path"])
    assert saved.parent == tmp_path / "out" / "Invoices" and saved.exists(), rec
    assert not list((tmp_path / "out" / "Manual Review").iterdir())


def test_an_invoice_that_prints_its_item_names_passes_as_before(tmp_path, shown):
    """What worked before still works, an invoice whose item name comes out
    on the paper in full."""
    app, purchase, rec = run_one(tmp_path, shown, invoice(name_cut=False))

    assert rec.get("downloaded_ok") is True, rec
    assert Path(rec["pdf_path"]).parent == tmp_path / "out" / "Invoices"


# -- and nothing that is not this order's document passes because of it -----------

def test_another_orders_invoice_is_refused_before_it_is_printed(tmp_path, shown):
    app, purchase, rec = run_one(tmp_path, shown, invoice(number=ANOTHER))

    assert refused(tmp_path, rec), rec


@pytest.mark.parametrize("longer", ["91000000-00000011", "1000000-000000111",
                                    "1000000-00000011-5"])
def test_a_longer_number_holding_this_one_is_refused_before_it_is_printed(tmp_path, shown, longer):
    app, purchase, rec = run_one(tmp_path, shown, invoice(number=longer))

    assert refused(tmp_path, rec), rec


def test_a_heading_over_an_invoice_that_never_came_is_still_put_aside(tmp_path, shown):
    """The order's number and nothing an invoice carries under it, not an
    item and not an amount."""
    app, purchase, rec = run_one(tmp_path, shown, HEADING_ONLY)

    assert put_aside(tmp_path, rec), rec


def test_a_page_that_is_not_this_orders_gets_nothing_from_its_number(tmp_path, shown):
    """The order's address sends the tab on to the list of orders, and
    what is printed there shows this order's number and an amount. Only
    the order's own page is known by the number it prints, and the list is
    turned away before it is printed."""
    shown["list"] = invoice()
    app, purchase, rec = run_one(
        tmp_path, shown, "<!doctype html><script>location.replace('/orders')</script>")

    assert shown["page"].url == LIST, "the tab really did move on"
    assert refused(tmp_path, rec), rec


# -- a file put aside says what it is --------------------------------------------------

def test_the_pilot_report_measures_a_file_put_aside(tmp_path, shown, capsys):
    """It read "? bytes, ? pages" for a file sitting in Manual Review,
    because the size and pages were only recorded for a file that passed."""
    app, purchase, rec = run_one(tmp_path, shown, NO_TOTAL)
    assert put_aside(tmp_path, rec), rec
    capsys.readouterr()

    app._pilot_report([purchase])
    out = capsys.readouterr().out

    size = Path(rec["pdf_path"]).stat().st_size
    assert "PDF exists: True  (%d bytes, 1 pages)" % size in out, out
    assert "? bytes" not in out and "? pages" not in out, out


def test_a_file_put_aside_leaves_a_failure_file_with_none_of_its_words(tmp_path, shown):
    """What the file holds, as counts and yes or no, so the next report says
    whether it was an invoice, a blank print or another page altogether."""
    app, purchase, rec = run_one(tmp_path, shown, NO_TOTAL)
    assert put_aside(tmp_path, rec), rec

    written = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(written) == 1, written
    raw = written[0].read_text(encoding="utf-8")
    report = json.loads(raw)
    facts = report["extra"]["postmortem"]
    assert report["step"] == "check the saved document", report
    assert facts["pages"] == 1 and facts["text_characters"] > 100, facts
    assert facts["says_walmart"] is False, facts
    assert facts["prints_this_order_number"] is True, facts
    assert facts["prints_an_amount"] is True and facts["prints_a_date"] is True, facts
    # Its one item is printed, cut short, and counts the way the check that
    # wants an item counts it (site.items_printed). It was put aside for the
    # other order's number.
    assert facts["item_names_read"] == 1 and facts["item_names_printed"] == 1, facts
    assert {"invoice", "subtotal", "total", "tax", "qty", "payment"} <= set(facts["words"]), facts
    assert facts["printed_from_this_order"] is True, facts
    for value in VALUES:
        assert value not in raw, value


# -- the number itself ------------------------------------------------------------------

@pytest.mark.parametrize("text, order, total, found", [
    ("Order# 1000000-00000011\nTotal $13.34", ORDER, "$13.34", ["1000000-00000011"]),
    ("Order# 1000000 - 00000011\nTotal $13.34", ORDER, "$13.34", ["1000000-00000011"]),
    ("Order# 1000000-\n00000011\nTotal $13.34", ORDER, "$13.34", ["1000000-00000011"]),
    ("Order# 1000000-00000011\nTotal $1,013.34", ORDER, "$1013.34", ["1000000-00000011"]),
    # A store receipt's twenty digits, in groups of four.
    ("1000-0000-0000-0000-0022\nTOTAL $4.10", "10000000000000000022", "$4.10",
     ["1000-0000-0000-0000-0022"]),
    ("Order# 1000000-00000099\nTotal $13.34", ORDER, "$13.34", []),
    ("Order# 91000000-00000011\nTotal $13.34", ORDER, "$13.34", []),
    ("Order# 1000000-000000111\nTotal $13.34", ORDER, "$13.34", []),
    ("Order# 1000000-00000011", ORDER, "$13.34", []),
    ("Order# 1000-0011\nTotal $13.34", "10000011", "$13.34", []),
    # An amount, but not the order's own total, and no total known at all.
    ("Order# 1000000-00000011\nMembers save $35.00", ORDER, "$13.34", []),
    ("Order# 1000000-00000011\nTotal $13.34", ORDER, "", []),
])
def test_the_order_number_as_walmart_prints_it(text, order, total, found):
    assert site.order_number_as_printed(text, order, total) == found


# The review's page. The heading over an invoice that never came, with a
# promotion's amount beside it and not the order's total.
NEVER_CAME = PAGE % """
  <h2>Invoice</h2>
  <p>Jun 3, 2026 order</p>
  <p>Order# 1000000-00000011</p>
  <p>We could not load the rest of this invoice</p>
  <p>Members save $35.00</p>"""


def test_an_amount_that_is_not_the_orders_total_is_not_enough(tmp_path, shown):
    app, purchase, rec = run_one(tmp_path, shown, NEVER_CAME)

    assert put_aside(tmp_path, rec), rec


def test_an_order_whose_total_nobody_knows_gets_nothing_from_its_number(tmp_path, shown):
    """No amount on the order's page, so no total was read, and the invoice
    is checked the way it always was."""
    html = invoice().replace("<p>Subtotal $12.47</p><p>Tax $0.87</p><p>Total $13.34</p>", "")
    html = html.replace('<span data-testid="line-price">$12.47</span>', "")
    app, purchase, rec = run_one(tmp_path, shown, html)

    assert rec["total"] == "", rec
    assert put_aside(tmp_path, rec), rec
