"""Both captures, the App Store search and the store's sign-in stop, in a
real headless browser against made-up pages.

Every address is answered from inside the test by a route and anything not
answered is refused, so nothing reaches Apple. The browser is also told to
resolve no host at all, which keeps the same promise a second way. Every
member, order, name and amount is invented."""
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import apple_receipts as app_mod
import apple_site as site
from paperpull_core import classification, delivery, receipt_pdf
from paperpull_core.api_census import Requests
from paperpull_core.models import Purchase

REPORT = "https://reportaproblem.apple.com"
STORE = "https://www.apple.com"
SECURE = "https://secure9.store.apple.com"
TOKEN = "TESTTOKEN"
ORGANIZER, CHILD = "10000001", "10000002"


@pytest.fixture()
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        chromium = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield chromium
    chromium.close()
    driver.stop()


class FakeApple:
    """Made-up pages for Apple's hosts, answered by a route. Anything not
    here is refused, and every request is written down."""

    def __init__(self, browser):
        self.pages, self.seen = {}, []
        self.context = browser.new_context()
        self.context.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
        self.context.route("**/*", self._serve)

    def at(self, url, answer):
        self.pages[url] = answer
        return self

    def _serve(self, route, request):
        parts = urlsplit(request.url)
        key = "%s://%s%s" % (parts.scheme, parts.netloc, parts.path)
        self.seen.append((request.method, key, dict(request.headers), request.post_data))
        answer = self.pages.get(key)
        if answer is None:
            route.abort()
            return
        if callable(answer):
            answer = answer(request)
        route.fulfill(status=answer.get("status", 200), headers=answer.get("headers") or {},
                      content_type=answer.get("content_type", "text/html"),
                      body=answer.get("body", ""))

    def requested(self, url):
        return [s for s in self.seen if s[1] == url]


def _app(tmp_path, context, page=None):
    """The downloader without its __init__, which would want a config file
    and a signed-in browser, pointed at the made-up site."""
    app = object.__new__(app_mod.App)
    app.args = SimpleNamespace(year=None, start_date=None, end_date=None, order_number=None,
                               max_purchases=None, redownload=False, dry_run=False, yes=True)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "refuse_wrong_documents": True,
                  "owner": "Dana Example", "default_start_date": "",
                  "delay_min_seconds": 0, "delay_max_seconds": 0}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.rules = classification.load_rules(Path(app_mod.__file__).parent / "category_rules.json")
    app._opened, app._left_open, app._stopped_sides, app._survey = [], set(), set(), {}
    app._cdp_mode, app._context, app._work_page, app._store_page = True, context, page, None
    app._pw = app._browser = None
    app.browser = lambda: context
    if page is not None:
        app.page = lambda: page
    app.failures = []
    app.write_failure = lambda *a, **kw: app.failures.append(a)
    return app


# -- Report a Problem, made up ----------------------------------------------------

HOME = ("<html><body><h1>Report a Problem</h1><p>Found 4 results.</p>"
        "<script>sessionStorage.setItem('x-apple-xsrf-token', '%s')</script>"
        "</body></html>" % TOKEN)

FAMILY = {"members": [
    {"dsid": ORGANIZER, "givenName": "Dana", "familyName": "Example", "isHeadOfHousehold": True},
    {"dsid": CHILD, "givenName": "Quill", "familyName": "Example", "isHeadOfHousehold": False}]}


def bought(weborder, dsid, name, detail, media, kind, paid, free=False, pending=False,
           invoice=True):
    return {"purchaseId": "80000000000001", "dsid": dsid,
            "invoiceAmount": paid if invoice and not free else None,
            "plis": [{"amountPaid": paid if not free else "$0.00", "isFreePurchase": free,
                      "quantity": 0 if free else 1, "lineItemType": kind,
                      "localizedContent": {"nameForDisplay": name, "detailForDisplay": detail,
                                           "mediaType": media}}],
            "weborder": weborder, "invoiceDate": None, "purchaseDate": "2026-05-14T12:00:00Z",
            "isPendingPurchase": pending, "estimatedTotalAmount": paid}


APPLE_ONE = bought("MLF0TEST01", ORGANIZER, "Premier", "Apple One", "Apple One Subscription",
                   "FirstPartySubscriptionBundle", "$21.43")
FREE_APP = bought("R00TEST0000001", ORGANIZER, "Lantern Notes", "Example Dev LLC", "iOS App",
                  "IOSApp", "$0.00", free=True)
CHILD_COINS = bought("MLF0TEST03", CHILD, "Blockville | 400 Bricks", "", "",
                     "VideoPartnerBilling", "$4.37")
PENDING = bought("MLF0TEST04", ORGANIZER, "Gem Pack 3", "Crystal Quarry", "In-App Purchase",
                 "BaseLineItem", "$1.23", pending=True)

RECEIPT = ("<html><head><style>body { font-family: sans-serif }</style></head><body>"
           "<h1>Receipt</h1><p>May 14, 2026</p><p>Order ID: __ORDER__</p>"
           "<p>Document: 000000000001</p><p>Apple Account: quill@example.com</p>"
           "<table><tr><td>Blockville</td><td>400 Bricks</td><td>$4.37</td></tr></table>"
           "<p>Billing and Payment</p><p>Dana Example</p><p>Subtotal $4.37</p>"
           "</body></html>")


def json_answer(data, status=200):
    return {"status": status, "content_type": "application/json", "body": json.dumps(data)}


def searches(batches):
    """POST /api/purchase/search, answered by batchId from `batches`, which
    maps the batchId asked for (None for the first) to (status, purchases,
    nextBatchId)."""
    def answer(request):
        body = json.loads(request.post_data or "{}")
        status, purchases, following = batches[body.get("batchId")]
        if status != 200:
            return json_answer({}, status)
        return json_answer({"batchId": body.get("batchId"), "nextBatchId": following,
                            "query": body, "purchases": purchases})
    return answer


def receipt_for(printed, dsid):
    """GET /api/order/<weborder>/invoice.html, answered only with the header
    the page's own View Receipt sends, the purchaser's dsid."""
    def answer(request):
        headers = request.headers
        if headers.get("dsid") != dsid or headers.get("x-apple-xsrf-token") != TOKEN:
            return json_answer({}, 403)
        return json_answer({"email": "quill@example.com",
                            "invoice": RECEIPT.replace("__ORDER__", printed),
                            "refund": None, "vat": None})
    return answer


def report_a_problem(browser, **pages):
    fake = FakeApple(browser)
    fake.at(REPORT + "/", {"body": HOME})
    for url, answer in pages.items():
        fake.at(REPORT + url, answer)
    page = fake.context.new_page()
    page.goto(REPORT + "/")
    return fake, page


# -- the App Store receipt ----------------------------------------------------------

def test_an_app_store_receipt_is_rendered_to_a_pdf_that_carries_its_order_id(browser, tmp_path):
    invoice = "/api/order/MLF0TEST03/invoice.html"
    fake, page = report_a_problem(browser, **{invoice: receipt_for("MLF0TEST03", CHILD)})
    app = _app(tmp_path, fake.context, page)
    purchase = Purchase(purchase_type="App Store", purchase_date="2026-05-14",
                        order_number="MLF0TEST03", total="$4.37")
    out = tmp_path / "App Store" / "2026-05-14 Apple Blockville Receipt.pdf"

    got = app._capture_app_store_receipt(page, purchase, out, {"dsid": CHILD})

    assert got.outcome == delivery.SAVED, got.report()
    assert got.verdict.outcome == "verified"
    assert "Order ID: MLF0TEST03" in receipt_pdf.pdf_text(out)
    assert len(fake.requested(REPORT + invoice)) == 1, "asked for once"
    assert fake.context.pages == [page], "the blank tab it was drawn in is closed again"


def test_a_failure_file_written_after_a_receipt_carries_no_order_id(browser, tmp_path):
    """The receipt's address carries the order id, and a failure file is a
    thing a tester posts in public. The request census still describes the
    calls that carry none, and the journal keeps the receipt call's status."""
    invoice = "/api/order/MLF0TEST03/invoice.html"
    fake, page = report_a_problem(browser, **{"/api/family": json_answer(FAMILY),
                                              invoice: receipt_for("MLF0TEST03", CHILD)})
    app = _app(tmp_path, fake.context, page)
    del app.write_failure                       # the real one, writing the real file
    app._requests = Requests(page, site.is_safe_url)
    app._requests.start()
    site.read_family(page)
    purchase = Purchase(purchase_type="App Store", purchase_date="2026-05-14",
                        order_number="MLF0TEST03", total="$4.37")
    out = tmp_path / "App Store" / "2026-05-14 Apple Blockville Receipt.pdf"
    assert app._capture_app_store_receipt(page, purchase, out, {"dsid": CHILD}).outcome == delivery.SAVED

    app.write_failure("save the receipt", "the receipt did not render")

    written = next(app.paths.diagnostics.glob("failure-*.json")).read_text(encoding="utf-8")
    assert "MLF0TEST03" not in written
    assert "/api/family" in written, "the calls with no id in them are still described"
    report = json.loads(written)
    asked = [e for e in report["journal"]["entries"] if e.get("outcome") == "asked for the receipt"]
    assert asked and asked[0]["facts"]["status"] == 200


def test_a_receipt_that_carries_another_order_id_is_refused(browser, tmp_path):
    invoice = "/api/order/MLF0TEST01/invoice.html"
    fake, page = report_a_problem(browser, **{invoice: receipt_for("MLF0TEST02", ORGANIZER)})
    app = _app(tmp_path, fake.context, page)
    purchase = Purchase(purchase_type="App Store", purchase_date="2026-05-14",
                        order_number="MLF0TEST01", total="$4.37")
    out = tmp_path / "App Store" / "2026-05-14 Apple Apple One Receipt.pdf"

    got = app._capture_app_store_receipt(page, purchase, out, {"dsid": ORGANIZER})

    assert got.outcome == delivery.WRONG
    assert not out.exists(), "nothing is filed under this purchase's name"
    assert not list(out.parent.glob("*.delivering")), "and nothing is left half done"


# -- the App Store search -------------------------------------------------------------

def test_the_app_store_is_read_from_inside_the_page_for_the_whole_family(browser, tmp_path, capsys):
    fake, page = report_a_problem(browser, **{
        "/api/family": json_answer(FAMILY),
        "/api/purchase/search": searches({None: (200, [APPLE_ONE, FREE_APP], "BATCH-2"),
                                          "BATCH-2": (200, [CHILD_COINS, PENDING], None)})})
    app = _app(tmp_path, fake.context, page)

    assert app._discover_app_store() == 2

    assert sorted(app.discovery.data) == ["App Store:MLF0TEST01", "App Store:MLF0TEST03"]
    assert app.discovery.data["App Store:MLF0TEST01"]["purchaser"] == "Dana Example"
    assert app.discovery.data["App Store:MLF0TEST03"]["purchaser"] == "Quill"
    assert app.discovery.data["App Store:MLF0TEST03"]["dsid"] == CHILD
    assert app.stats["free_skipped"] == 1 and app.stats["pending_skipped"] == 1
    asked = fake.requested(REPORT + "/api/purchase/search")
    assert [json.loads(body) for _m, _u, _h, body in asked] == [
        {"dsids": [ORGANIZER, CHILD]}, {"batchId": "BATCH-2", "dsids": [ORGANIZER, CHILD]}]
    for _method, _url, headers, _body in asked + fake.requested(REPORT + "/api/family"):
        assert headers.get("x-apple-xsrf-token") == TOKEN
        assert headers.get("x-apple-rap2-api") == "3.0.0"
    api = {url for _m, url, _h, _b in fake.seen if "/api/" in url}
    assert api == {REPORT + "/api/family", REPORT + "/api/purchase/search"}


def test_a_403_stops_the_app_store_side_and_asks_for_a_sign_in(browser, tmp_path, capsys):
    fake, page = report_a_problem(browser, **{
        "/api/family": json_answer(FAMILY),
        "/api/purchase/search": searches({None: (200, [APPLE_ONE], "BATCH-2"),
                                          "BATCH-2": (403, [], None)})})
    app = _app(tmp_path, fake.context, page)

    assert app._discover_app_store() == 1, "what was read before the 403 is kept"

    assert app._stopped_sides == {"App Store"}
    assert "Report a Problem asked you to sign in again" in capsys.readouterr().out
    assert len(fake.requested(REPORT + "/api/purchase/search")) == 2, "never asked again"
    with pytest.raises(SystemExit):
        app._stop_if_signed_out()


# -- the Apple Store --------------------------------------------------------------------

INVOICE_PAGE = """<html><head><title>Invoice</title>
<style>.print { float: right; background: #0071e3; color: #fff; border-radius: 18px; }</style>
</head><body><div id="rs-container"></div>
<script>
setTimeout(() => {
  const box = document.getElementById('rs-container');
  const button = document.createElement('button');
  button.className = 'print';
  button.textContent = 'Print';
  button.addEventListener('click', () => fetch('/pressed'));
  box.appendChild(button);
  box.insertAdjacentHTML('beforeend',
    '<h1>Apple Store</h1><h2>Invoice Receipt</h2><p>Do Not Pay</p>' +
    '<p>Order Number</p><p>__ORDER__</p><p>Order Date</p><p>April 28, 2026</p>' +
    '<table><tr><td>IPAD AIR 11 WIFI 128GB STARLIGHT</td><td>$612.34</td></tr></table>' +
    '<p>Subtotal $612.34</p><p>Sales Tax $42.87</p><p>Total $655.21</p>' +
    '<p>Items will be invoiced once they have shipped or are ready for pickup.</p>');
}, 400);
</script></body></html>"""


def test_a_store_invoice_is_printed_with_its_print_button_hidden(browser, tmp_path):
    fake = FakeApple(browser)
    url = SECURE + "/shop/order/print/invoice/100001/INV0000001"
    fake.at(url, {"body": INVOICE_PAGE.replace("__ORDER__", "W0000000001")})
    app = _app(tmp_path, fake.context)
    purchase = Purchase(purchase_type="Apple Store", purchase_date="2026-04-28",
                        order_number="W0000000001", total="$655.21", receipt_url=url)
    out = tmp_path / "Apple Store" / "2026-04-28 Apple iPad Air Receipt.pdf"

    got = app._capture_store_invoice(purchase, out)

    assert got.outcome == delivery.SAVED, got.report()
    text = receipt_pdf.pdf_text(out)
    assert "W0000000001" in text and "Invoice Receipt" in text
    assert "Print" not in text, "the Print button is not on the PDF"
    assert not fake.requested(SECURE + "/pressed"), "and it was never pressed"
    assert app._opened and all(tab.is_closed() for tab in app._opened), "the tab is closed"


SIGN_IN_PAGE = ("<html><body><h1>Sign in for faster checkout.</h1>"
                "<p>Sign in to the Apple Store</p></body></html>")


def test_a_signed_out_store_list_stops_with_the_sign_in_message(browser, tmp_path, capsys):
    """Apple answers the list with a redirect to its sign-in page, RECORDED.
    A route cannot answer a navigation with one, so the made-up list moves
    itself there, a moment after it loads, which the wait has to catch."""
    fake = FakeApple(browser)
    sign_in = SECURE + "/shop/signIn/orders"
    fake.at(STORE + "/shop/order/list",
            {"body": "<html><body><script>setTimeout(() => location.replace("
                     "'%s?ssi=TEST'), 300)</script></body></html>" % sign_in})
    fake.at(sign_in, {"body": SIGN_IN_PAGE})
    app = _app(tmp_path, fake.context)

    assert app._discover_apple_store() == 0

    said = capsys.readouterr().out
    assert "The Apple Store asked you to sign in" in said
    assert "Sign in to the Apple Store in that window" in said
    assert app._stopped_sides == {"Apple Store"}
    tab = app._store_page
    assert "/shop/signin/" in tab.url.lower()
    assert not tab.is_closed() and id(tab) in app._left_open, "left open to sign in there"
    assert not [s for s in fake.seen if "/shop/order/detail/" in s[1]], "nothing else was opened"
    assert app.discovery.data == {}
    with pytest.raises(SystemExit):
        app._stop_if_signed_out()


def page_with(data):
    """A store page carrying its data the way Apple's do, in init_data."""
    return {"body": "<html><body><h1>Your Orders</h1><script id=\"init_data\" "
                    "type=\"application/json\">%s</script></body></html>" % json.dumps(data)}


def store_item(product, delivery_text, number):
    return {"d": {"quantity": 1, "deliveryDate": delivery_text, "productShortName": product,
                  "orderDetailUrl": SECURE + "/shop/order/detail/100001/" + number}}


LISTING = {"orderList": {"d": {"moreOrdersAvailable": False},
                         "c": ["order-W0000000001", "order-W0000000003"],
                         "order-W0000000001": {"d": {"webOrderNumber": "W0000000001"},
                                               "c": ["0000101"],
                                               "0000101": store_item("iPad Air", "Delivered May 2, 2026",
                                                                     "W0000000001")},
                         "order-W0000000003": {"d": {"webOrderNumber": "W0000000003"},
                                               "c": ["0000101"],
                                               "0000101": store_item("Mac mini", "Canceled",
                                                                     "W0000000003")}}}


def store_detail(number, placed, product, tracker, invoice):
    header = {"orderNumber": number, "orderPlacedDate": placed}
    if invoice:
        header["invoiceUrl"] = SECURE + "/shop/order/print/invoice/100001/INV0000001"
    return {"orderDetail": {
        "orderHeader": {"d": header},
        "orderItems": {"c": ["orderItem-0000101"], "orderItem-0000101": {
            "orderItemDetails": {"d": {"quantity": 1, "productName": product,
                                       "totalPrice": "$612.34", "listPrice": "$612.34"}},
            "orderItemStatusTracker": {"d": tracker}}},
        "pricingSummary": {"d": {"orderTotal": "$655.21"}}}}


def the_store(fake):
    """A signed-in Apple Store with one order delivered and one canceled."""
    fake.at(STORE + "/shop/order/list", page_with(LISTING))
    fake.at(SECURE + "/shop/order/detail/100001/W0000000001", page_with(store_detail(
        "W0000000001", "April 28, 2026", "iPad Air 11-inch Wi-Fi 128GB - Starlight",
        {"currentStatus": "DELIVERED"}, True)))
    fake.at(SECURE + "/shop/order/detail/100001/W0000000003", page_with(store_detail(
        "W0000000003", "March 9, 2026", "Mac mini M4 16GB", {"statusDescription": "CANCELED"},
        False)))
    return fake


def test_a_store_order_is_read_from_the_list_and_its_details_page(browser, tmp_path):
    """The signed-in half, through the same code, with one order delivered
    and one canceled."""
    fake = the_store(FakeApple(browser))
    app = _app(tmp_path, fake.context)

    assert app._discover_apple_store() == 2

    delivered = app.discovery.data["Apple Store:W0000000001"]
    canceled = app.discovery.data["Apple Store:W0000000003"]
    assert delivered["purchase_date"] == "2026-04-28" and delivered["status"] == "Delivered"
    assert delivered["receipt_url"].endswith("/shop/order/print/invoice/100001/INV0000001")
    assert canceled["status"] == "Canceled" and canceled["receipt_url"] == ""
    assert not app._stopped_sides and not app.failures


# -- Diagnose ------------------------------------------------------------------------

# Everything in the made-up account that is the account's own, which neither
# of Diagnose's files may carry.
THE_ACCOUNTS_OWN = ("Dana", "Quill", "Example", "example.com", "MLF0TEST", "R00TEST",
                    "W0000000", "INV0000001", "Blockville", "Lantern", "Crystal", "Premier",
                    "iPad", "Mac mini", "21.43", "4.37", "612.34", TOKEN, ORGANIZER, CHILD)


def test_diagnose_counts_both_stores_and_writes_nothing_from_the_account(browser, tmp_path, capsys):
    fake, page = report_a_problem(browser, **{
        "/api/family": json_answer(FAMILY),
        "/api/purchase/search": searches({None: (200, [APPLE_ONE, FREE_APP], "BATCH-2"),
                                          "BATCH-2": (200, [CHILD_COINS, PENDING], None)})})
    the_store(fake)
    app = _app(tmp_path, fake.context, page)

    app.cmd_diagnose()
    app.write_survey()

    said = capsys.readouterr().out
    assert "App Store, signed in yes, 2 member(s), 4 purchase(s) read, 2 paid, 1 free, 1 pending" in said
    assert "Apple Store, signed in yes, 2 order(s) listed, 1 with an invoice, 1 canceled" in said
    survey_file = next(app.paths.diagnostics.glob("survey-diagnose-*.json"))
    survey = json.loads(survey_file.read_text(encoding="utf-8"))
    counts = survey["extra"]
    assert counts["app_store"]["signed_in"] is True and counts["app_store"]["members"] == 2
    assert (counts["app_store"]["purchases"], counts["app_store"]["paid"],
            counts["app_store"]["paid_by_others"]) == (4, 2, 1)
    assert counts["app_store"]["stop"] == "end" and counts["app_store"]["reached_end"] is True
    assert counts["apple_store"]["signed_in"] is True and counts["apple_store"]["state"] == "ready"
    assert (counts["apple_store"]["orders"], counts["apple_store"]["with_invoice"],
            counts["apple_store"]["canceled"]) == (2, 1, 1)
    for written in (survey_file, app.paths.diagnostics / "diagnose-apple.json"):
        text = written.read_text(encoding="utf-8")
        leaked = [word for word in THE_ACCOUNTS_OWN if word in text]
        assert not leaked, "%s carries %s" % (written.name, leaked)
    assert not [s for s in fake.seen if "/api/" in s[1] and not s[1].endswith(
        ("/api/family", "/api/purchase/search"))], "Diagnose reads, and reads only these"
