"""A saved Walmart receipt prints the order's items, in a real browser.

By the end of September 2026 Walmart's order page had changed. Its item
list is folded away behind a "Show items" button, and its print style hides
the list even when it is open, so the app's print of the page carried the
date, the totals and the barcode and none of the items. The check passed it
on the number and total it printed (#63), and a run saved receipts with no
items on them and called them done. A store receipt saved in July lists its
two items, the same purchase saved on 2026-10-01 lists none. A tester's
three online invoices printed none of the items their pages listed.

The invoice Walmart's own "Print invoice" button prints, items included, is
a block of its own at the end of the page, hidden until that button shows
it. The app now prints that block, without pressing anything, and a
document that prints none of the order's items is put aside.

Walmart's bot check also came up over an order page after it had opened
clean, and a print taken then carried "Robot or human?" under the totals.
The page is looked at again right before it is printed.

The pages here are laid out the way the live page measured on 2026-10-01
was, by its structure and the attributes the app reads. Every page is
invented and served to Playwright's own Chromium from inside the test,
every other request is refused, and every number, item and amount is
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
from paperpull_core import receipt_pdf
from paperpull_core.models import IN_STORE, ONLINE, Item, Purchase

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

STORE_KEY = "30000000000000000017"
STORE_PRINTED = "3000-0000-0000-0000-0017"
ONLINE_KEY = "100000000000061"
ONLINE_PRINTED = "1000000-00000061"
HOST = "https://orders.example.invalid"
STORE_ADDRESS = HOST + "/orders/" + STORE_KEY
ONLINE_ADDRESS = HOST + "/orders/" + ONLINE_KEY

ITEMS = ("Invented Folding Step Stool, White", "Invented Cotton Dish Towels, 4 Pack")
PRICES = ("$15.12", "$6.33")

# The order page as Walmart lays it out now. The item list starts folded,
# "Show items" and the overlay over the folded list both open it, and the
# print style hides the list whether it is open or not. "Print invoice"
# would print the hidden invoice block, and a press is remembered.
PAGE = """<!doctype html><html><head><title>Order details</title><style>
.item-list { display: none }
.item-list.open { display: block }
@media print {
  .site-header, .account-nav, .items-header, .item-list, .help, .site-footer
    { display: none !important }
}
</style></head><body>
<div class="site-header"><a href="/">Walmart</a> Departments Services</div>
<div class="account-nav">Account Purchase history Walmart+</div>
<main>
  <div>Invoice</div>
  <h1>%(date)s</h1>
  <p>%(label)s %(printed)s</p>
  <button data-automation-id="print-link"
    onclick="window.__printPressed = true; window.print()">Print invoice</button>
  <div class="items-header">%(kind)s %(date)s 2 items
    <button data-automation-id="items-toggle-link" aria-label="Show items"
      aria-expanded="false" onclick="showItems(this)">v</button>
  </div>
  <div data-testid="collapsedItemList">
    <button data-automation-id="show-all-items" aria-label="Show all items"
      aria-hidden="true" tabindex="-1" style="display:block;width:100%%;height:24px"
      onclick="showItems(document.querySelector('[data-automation-id=items-toggle-link]'))"></button>
  </div>
  <div class="item-list">
    <div data-testid="itemtile-stack"><div data-testid="productName">%(item0)s</div>
      <div data-testid="line-price">%(price0)s</div></div>
    <div data-testid="itemtile-stack"><div data-testid="productName">%(item1)s</div>
      <div data-testid="line-price">%(price1)s</div></div>
  </div>
  <div class="help">How can we help? View receipt details</div>
  <p>Payment method</p>
  <p>Subtotal (2 items) $21.45</p><p>Taxes $1.29</p><p>Total $22.74</p>
  <p>%(label)s %(printed)s</p>
  <p>Walmart Return Policy</p>
</main>
<div class="site-footer">All Departments Store Directory</div>
<script>
function showItems(button) {
  const open = button.getAttribute('aria-expanded') !== 'true';
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
  document.querySelector('.item-list').classList.toggle('open', open);
  const overlay = document.querySelector('[data-automation-id=show-all-items]');
  if (overlay) overlay.style.display = open ? 'none' : 'block';
}
</script>
%(invoice)s
</body></html>"""

# The invoice block, hidden by its own inline style until Walmart's button
# shows it, with its logo held back until it is needed.
INVOICE = """<div class="print-portal-root" aria-hidden="true" style="display: none;">
<div data-testid="print-invoice-layout">
  <div><img loading="lazy" alt="" width="174" height="42"
    src="data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs="><span>Invoice</span></div>
  <div><span>%(date)s</span><span>Order# %(printed)s</span></div>
  <div>
    <div><span>%(item0)s</span><span>Shopped</span><span>Qty 1</span><span>%(price0)s</span></div>
    <div><span>%(item1)s</span><span>Shopped</span><span>Qty 1</span><span>%(price1)s</span></div>
  </div>
  <div>Subtotal (2 items) $21.45</div><div>Taxes $1.29</div><div>Total $22.74</div>
  <div>Order# %(printed)s</div>
</div></div>"""

# Walmart's bot check as it came up over the order page, a box laid over
# everything with its own words.
BOT_CHECK_JS = """() => {
  const box = document.createElement('div');
  box.id = 'bot-check-over-the-page';
  box.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:#fff';
  box.innerHTML = '<h2>Robot or human?</h2><p>Activate and hold the button to confirm '
    + 'that you are human. Thank You!</p><button>PRESS &amp; HOLD</button>';
  document.body.appendChild(box);
}"""


def order_page(kind=IN_STORE, invoice=True):
    store = kind == IN_STORE
    values = {
        "date": "Sep 14, 2026 purchase" if store else "Sep 14, 2026 order",
        "label": "TC#" if store else "Order#",
        "printed": STORE_PRINTED if store else ONLINE_PRINTED,
        "kind": "Store purchase" if store else "Delivered",
        "item0": ITEMS[0], "item1": ITEMS[1], "price0": PRICES[0], "price1": PRICES[1],
    }
    values["invoice"] = INVOICE % values if invoice else ""
    return PAGE % values


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
    """What the invented order pages show, set by each test, and a page
    that has one open. How many times each was opened is counted. Every
    other request is refused."""
    served = {"html": order_page(), "opened": 0}
    context = browser.new_context()

    def answer(route):
        address = route.request.url.split("?")[0]
        if address in (STORE_ADDRESS, ONLINE_ADDRESS):
            served["opened"] += 1
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=served["html"])
        else:
            route.abort()

    context.route("**/*", answer)
    served["page"] = context.new_page()
    yield served
    context.close()


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    """The invented host is the one order pages are opened on, and the
    scroll before a print is kept short."""
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(HOST + "/"))
    real = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=50: real(page, rounds, delay_ms))
    # Each invoice block here is filled from the start or not there at all,
    # so it is looked for once rather than waited for.
    monkeypatch.setattr(site, "INVOICE_WAIT_MS", 0, raising=False)


def app_for(tmp_path, page):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg)]))
    app._work_page = page
    return app


def run_one(tmp_path, shown, kind=IN_STORE):
    """The order taken the way a run takes it, from opening its page to
    filing its document, and its record afterwards."""
    app = app_for(tmp_path, shown["page"])
    if kind == IN_STORE:
        purchase = Purchase(purchase_type=IN_STORE, order_number=STORE_KEY,
                            details_url=STORE_ADDRESS + "?groupId=0&storePurchase=true")
    else:
        purchase = Purchase(purchase_type=ONLINE, order_number=ONLINE_KEY,
                            details_url=ONLINE_ADDRESS)
    app.process_one(shown["page"], purchase)
    return app, purchase, app.progress.get(purchase.key)


def text_of(rec) -> str:
    return receipt_pdf.pdf_text(Path(rec["pdf_path"]))


def kept(rec, folder) -> bool:
    path = Path(rec["pdf_path"])
    return rec.get("downloaded_ok") is True and path.parent.name == folder and path.exists()


# -- the receipt prints the order's items --------------------------------------------

def test_a_store_receipt_prints_its_items(tmp_path, shown):
    """The report. The page listed two items and the saved receipt printed
    none. It prints both now, with the order's TC# and total."""
    app, purchase, rec = run_one(tmp_path, shown)

    assert [i["name"] for i in rec["items"]] == list(ITEMS), rec
    assert kept(rec, "In-Store"), rec
    text = text_of(rec)
    for name in ITEMS:
        assert name in " ".join(text.split()), text
    assert STORE_PRINTED in text and "$22.74" in text, text


def test_an_online_invoice_prints_its_items(tmp_path, shown):
    """A tester's three online invoices printed none of the items their
    pages listed (#63)."""
    shown["html"] = order_page(kind=ONLINE)
    app, purchase, rec = run_one(tmp_path, shown, kind=ONLINE)

    assert kept(rec, "Invoices"), rec
    text = text_of(rec)
    for name in ITEMS:
        assert name in " ".join(text.split()), text


def test_the_invoice_is_printed_alone(tmp_path, shown):
    """Walmart's invoice and nothing else, not the page's own copy of the
    totals beside it and none of the page around it."""
    app, purchase, rec = run_one(tmp_path, shown)

    text = text_of(rec)
    assert text.count("Total $22.74") == 1, text
    assert "Walmart Return Policy" not in text and "Departments" not in text, text


def test_nothing_is_pressed_and_the_page_is_put_back(tmp_path, shown):
    """Walmart's Print invoice opens a print dialog that freezes the
    browser, so it is never pressed. The page goes back to the screen as
    it was, its invoice hidden again."""
    run_one(tmp_path, shown)

    page = shown["page"]
    assert page.evaluate("window.__printPressed === true") is False
    assert page.evaluate("matchMedia('print').matches") is False
    assert page.evaluate("document.querySelectorAll('[data-paperpull-print]').length") == 0
    assert page.evaluate("document.getElementById('paperpull-printed-invoice')") is None
    assert page.evaluate(
        "getComputedStyle(document.querySelector('.print-portal-root')).display") == "none"


# -- a receipt with none of the items on it is not kept ---------------------------------

def test_a_receipt_that_prints_none_of_its_items_is_put_aside(tmp_path, shown):
    """A page with no invoice block, whose print hides its items. Its print
    is the order's own, number and total and all, and it was kept as done.
    It goes to Manual Review now, saying why."""
    shown["html"] = order_page(invoice=False)
    app, purchase, rec = run_one(tmp_path, shown)

    path = Path(rec["pdf_path"])
    assert rec["state"] == "Needs Manual Review" and not rec.get("downloaded_ok"), rec
    assert path.parent == tmp_path / "out" / "Manual Review" and path.exists(), rec
    assert "none of the order's items" in rec.get("notes", ""), rec
    assert not any(name in " ".join(text_of(rec).split()) for name in ITEMS)


def test_its_failure_file_counts_the_items_and_says_none_of_them(tmp_path, shown):
    shown["html"] = order_page(invoice=False)
    app, purchase, rec = run_one(tmp_path, shown)

    written = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(written) == 1, written
    raw = written[0].read_text(encoding="utf-8")
    facts = json.loads(raw)["extra"]["postmortem"]
    assert facts["item_names_read"] == 2 and facts["item_names_printed"] == 0, facts
    for value in (STORE_KEY, STORE_PRINTED, "Folding Step Stool", "Dish Towels", "22.74"):
        assert value not in raw, value


# -- a bot check that comes up over the page is not printed ------------------------------

@pytest.fixture()
def bot_check_after_reading(monkeypatch, shown):
    """Walmart's bot check comes up over the order page once the app has
    read it, at the scroll just before the print, the first time only.
    Opening the page again serves it clean."""
    state = {"shown": False}
    scroll = site.scroll_full_page

    def scroll_then_check(page, *a, **k):
        scroll(page, *a, **k)
        if not state["shown"]:
            state["shown"] = True
            page.evaluate(BOT_CHECK_JS)

    monkeypatch.setattr(site, "scroll_full_page", scroll_then_check)
    return state


def test_a_bot_check_over_the_page_is_answered_before_the_print(
        tmp_path, shown, bot_check_after_reading, monkeypatch):
    """The person is asked to answer it, the order's page is opened again,
    and what is printed is the invoice, with no bot check on it."""
    asked = []
    monkeypatch.setattr(app_mod.browser_launcher, "ask_or_none",
                        lambda prompt: asked.append(prompt) or "")

    app, purchase, rec = run_one(tmp_path, shown)

    assert bot_check_after_reading["shown"]
    assert len(asked) == 1, asked
    assert shown["opened"] == 2, "the order's page is opened again after the answer"
    assert kept(rec, "In-Store"), rec
    text = text_of(rec)
    assert "robot or human" not in text.lower() and "press & hold" not in text.lower(), text
    assert ITEMS[0] in " ".join(text.split()), text


def test_under_the_panel_a_bot_check_stops_the_run_before_the_print(
        tmp_path, shown, bot_check_after_reading, monkeypatch):
    """Nobody is at a console to answer it, so the run stops on its own
    terms with nothing saved for the order, and the next run takes it."""
    monkeypatch.setattr(app_mod.browser_launcher, "ask_or_none", lambda prompt: None)

    with pytest.raises(SystemExit) as stopped:
        run_one(tmp_path, shown)

    assert stopped.value.code == 0
    app = app_for(tmp_path, shown["page"])
    rec = app.progress.get(Purchase(purchase_type=IN_STORE, order_number=STORE_KEY).key) or {}
    assert not rec.get("downloaded_ok"), rec
    assert not list((tmp_path / "out" / "In-Store").glob("*.pdf"))


# -- how an item counts as printed --------------------------------------------------------

LONG = "x" * 40


@pytest.mark.parametrize("text, found", [
    ("Invented Folding Step Stool, White Shopped Qty 1 $15.12 " + LONG, (1, 1)),
    # A line break or a hyphen where the invoice's column wraps the name.
    ("Invented Folding\nStep Stool, White " + LONG, (1, 1)),
    ("INVENTED FOLDING-STEP STOOL " + LONG, (1, 1)),
    # Cut after its first twelve letters and digits, it still counts.
    ("Invented Fold… Shopped Qty 1 " + LONG, (1, 1)),
    # Less than that, or another item, does not.
    ("Invented Fol… " + LONG, (0, 1)),
    ("Invented Garden Trowel, Steel " + LONG, (0, 1)),
    # Almost no text, a scan or a blank, is not looked in.
    ("Invented Folding Step Stool", (0, 0)),
])
def test_how_an_item_counts_as_printed(text, found):
    assert site.items_printed(text, [Item(name=ITEMS[0])]) == found


def test_a_name_too_short_to_tell_is_not_looked_for():
    assert site.items_printed("Milk " + LONG, [Item(name="Milk"), Item(name="Tea 2")]) == (0, 0)


WORDS = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf")


def test_only_the_first_five_items_are_looked_for():
    items = [Item(name="Invented %s Widget" % w) for w in WORDS]
    assert site.items_printed("Invented Golf Widget " + LONG, items) == (0, 5)
    assert site.items_printed("Invented Bravo Widget " + LONG, items) == (1, 5)
