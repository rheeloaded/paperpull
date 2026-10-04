"""Both sides, the lists, the receipts and a lapsed session, in a real
headless browser against made-up pages.

Every address is answered from inside the test by a route and anything not
answered is refused, so nothing reaches Uber. The browser is also told to
resolve no host at all, which keeps the same promise a second way. Every
trip, order, store, name and amount is invented."""
import base64
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import uber_receipts as app_mod
import uber_site as site
from paperpull_core import classification, delivery, receipt_pdf
from paperpull_core.api_census import Requests
from paperpull_core.models import Item, Purchase

RIDERS = "https://riders.uber.com"
EATS = "https://www.ubereats.com"
AUTH = "https://auth.uber.com"

TRIP_A = "0a1b2c3d-1111-4222-8333-444455556666"
TRIP_B = "0a1b2c3d-7777-4888-9999-aaaabbbbcccc"
TRIP_C = "0a1b2c3d-2222-4333-8444-dddd0000eeee"
ORDER_A = "5e6f7a8b-1234-4567-89ab-cdef01234567"
ORDER_B = "5e6f7a8b-2345-4678-9abc-def012345678"
ORDER_C = "5e6f7a8b-3456-4789-abcd-ef0123456789"
RECEIPT_ID = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"


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


@pytest.fixture(autouse=True)
def _no_pauses(monkeypatch):
    monkeypatch.setattr(site, "LIST_PAUSE_MS", 0)
    monkeypatch.setattr(site, "SETTLE_MS", 3000)


def make_pdf(browser, lines):
    """A real PDF, drawn by the browser from made-up receipt lines, the way
    Uber's own receipts are made."""
    context = browser.new_context()
    page = context.new_page()
    page.set_content("<html><body>%s</body></html>"
                     % "".join("<p>%s</p>" % line for line in lines))
    data = page.pdf()
    context.close()
    return data


class FakeUber:
    """Made-up pages for Uber's hosts, answered by a route. Anything not
    here is refused, and every request is written down."""

    def __init__(self, browser):
        self.pages, self.seen = {}, []
        self.context = browser.new_context()
        self.context.route("**/*", self._serve)

    def at(self, url, answer):
        self.pages[url] = answer
        return self

    def _serve(self, route, request):
        parts = urlsplit(request.url)
        key = "%s://%s%s" % (parts.scheme, parts.netloc, parts.path)
        self.seen.append((request.method, key, dict(request.headers), request.post_data,
                          parts.query))
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

    def operations(self):
        """The GraphQL operation of every call to riders.uber.com/graphql."""
        return [json.loads(s[3] or "{}").get("operationName")
                for s in self.requested(RIDERS + "/graphql")]


def html_answer(body):
    return {"body": "<html><body>%s</body></html>" % body}


def json_answer(data, status=200):
    return {"status": status, "content_type": "application/json", "body": json.dumps(data)}


def pdf_answer(data):
    return {"content_type": "application/pdf", "body": data,
            "headers": {"content-disposition": "attachment; filename=receipt_x.pdf"}}


def redirect_to_sign_in():
    return {"status": 302, "headers": {"location": AUTH + "/v2/?next_url=x"}, "body": ""}


TRIPS_PAGE = html_answer("<h1>My Trips</h1><p>Past</p>")
EATS_PAGE = html_answer("<h1>Past Orders</h1>")
SIGN_IN = html_answer("<p>What's your phone number or email?</p>"
                      "<input type='tel' name='phone'><button>Continue</button>")


def _app(tmp_path, context, riders=None, eats=None):
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
    app._cut_short_sides = set()
    app._cdp_mode, app._context = True, context
    app._work_page, app._eats_page = riders, eats
    app._pw = app._browser = None
    app._journal = app._requests = None
    app.browser = lambda: context
    app.page = lambda: riders
    app.eats_page = lambda: eats
    app.failures = []
    app.write_failure = lambda *a, **kw: app.failures.append(a)
    return app


# -- rides, made up -----------------------------------------------------------------

def token(iso):
    return base64.b64encode(iso.encode()).decode()


def activity(uuid, where, description, subtitle):
    return {"uuid": uuid, "title": where, "description": description, "subtitle": subtitle,
            "cardURL": RIDERS + "/trips/" + uuid,
            "buttons": [{"text": "Details", "url": RIDERS + "/trips/" + uuid}]}


def begin(uuid):
    return {TRIP_A: "Mon Jun 15 2026 16:05:10 GMT+0000 (Coordinated Universal Time)",
            TRIP_C: "Wed Nov 12 2025 16:40:10 GMT+0000 (Coordinated Universal Time)"}[uuid]


def graphql(pages, receipts=None, lapse=None):
    """POST /graphql, answering Activities from `pages` by the token asked
    for, GetTrip from begin(), and GetReceipt from `receipts`. `lapse` is
    how many calls answer a redirect first, the way a lapsed session does."""
    state = {"lapse": lapse or 0}

    def answer(request):
        if state["lapse"] > 0:
            state["lapse"] -= 1
            return redirect_to_sign_in()
        body = json.loads(request.post_data or "{}")
        op, variables = body.get("operationName"), body.get("variables") or {}
        if op == "Activities":
            key = (variables.get("profileType"), variables.get("nextPageToken"))
            rows, following = pages.get(key, ([], None))
            return json_answer({"data": {"activities": {"cityID": 8, "past": {
                "activities": rows, "nextPageToken": following}}}})
        if op == "GetTrip":
            uuid = variables["tripUUID"]
            return json_answer({"data": {"getTrip": {
                "trip": {"beginTripTime": begin(uuid), "fare": "$18.64", "status": "COMPLETED",
                         "uuid": uuid},
                "receipt": {"distance": "3.10", "distanceLabel": "miles",
                            "duration": "12 minutes", "vehicleType": "UberX"}}}})
        if op == "GetReceipt":
            return json_answer({"data": {"getReceipt": (receipts or {})[variables["tripUUID"]]}})
        return json_answer({"errors": [{"message": "unknown"}]}, 400)
    return answer


T1 = token("2025-11-12T18:02:44.118Z")
RIDE_PAGES = {
    ("PERSONAL", None): ([activity(TRIP_A, "Example Station", "$18.64", "Jun 15 \u2022 11:55 AM"),
                          activity(TRIP_B, "Example Market", "$0.00 \u2022 Canceled",
                                   "Jun 11 \u2022 4:20 PM")], T1),
    ("PERSONAL", T1): ([activity(TRIP_C, "100 Example Ct", "$16.42", "Nov 12 \u2022 11:40 AM")], None),
}


def ride_receipt(printed, stamp="1781563527104"):
    return {"actionList": [{"type": "DOWNLOAD_PDF", "helpNodeUUID": ""},
                           {"type": "RESEND_EMAIL", "helpNodeUUID": ""}],
            "receiptData": "<div>Thanks for riding</div><div>Receipt ID # %s</div>" % printed,
            "receiptsForJob": [{"timestamp": stamp, "type": "COMPLETED", "eventUUID": "e1"},
                               {"timestamp": "1781551222580", "type": "COMPLETED",
                                "eventUUID": "e2"}]}


def riders_site(browser, **pages):
    fake = FakeUber(browser)
    fake.at(RIDERS + "/trips", TRIPS_PAGE)
    fake.at(AUTH + "/v2/", SIGN_IN)
    for url, answer in pages.items():
        fake.at(RIDERS + url, answer)
    page = fake.context.new_page()
    page.goto(RIDERS + "/trips")
    return fake, page


def test_rides_are_read_from_inside_the_trips_page(browser, tmp_path, capsys):
    fake, page = riders_site(browser, **{"/graphql": graphql(RIDE_PAGES)})
    app = _app(tmp_path, fake.context, riders=page)

    assert app._discover_rides() == 2

    assert sorted(app.discovery.data) == ["Rides:" + TRIP_A, "Rides:" + TRIP_C]
    a = app.discovery.data["Rides:" + TRIP_A]
    assert (a["purchase_date"], a["total"], a["summary_hint"]) == \
        ("2026-06-15", "$18.64", "Ride to Example Station")
    assert app.discovery.data["Rides:" + TRIP_C]["purchase_date"] == "2025-11-12"
    assert app.stats["unpaid_skipped"] == 1, "the canceled trip that cost nothing"
    assert fake.operations() == ["Activities", "Activities", "Activities", "GetTrip", "GetTrip"]
    for _m, _u, headers, _b, _q in fake.requested(RIDERS + "/graphql"):
        assert headers.get("x-csrf-token") == "x"
        assert headers.get("x-uber-rv-session-type") == "desktop_session"
    assert {s[1] for s in fake.seen} == {RIDERS + "/trips", RIDERS + "/graphql"}


def test_a_ride_receipt_is_ubers_own_pdf_checked_for_its_receipt_id(browser, tmp_path):
    pdf = make_pdf(browser, ["Jun 15, 2026", "Thanks for riding, Dana", "Total $18.64",
                             "Receipt ID # %s" % TRIP_A])
    receipt_path = "/trips/%s/receipt" % TRIP_A
    fake, page = riders_site(browser, **{
        "/graphql": graphql(RIDE_PAGES, receipts={TRIP_A: ride_receipt(TRIP_A)}),
        receipt_path: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, riders=page)
    purchase = Purchase(purchase_type="Rides", purchase_date="2026-06-15", order_number=TRIP_A,
                        total="$18.64")
    out = tmp_path / "Rides" / "2026-06-15 Uber Ride to Example Station Receipt.pdf"

    got = app._capture_document(page, purchase, out)

    assert got.outcome == delivery.SAVED, got.report()
    assert got.verdict.outcome == "verified"
    assert out.read_bytes() == pdf
    asked = fake.requested(RIDERS + receipt_path)
    assert len(asked) == 1, "asked for once"
    assert parse_qs(asked[0][4]) == {"contentType": ["PDF"], "timestamp": ["1781563527104"]}
    assert fake.operations() == ["GetReceipt"]


def test_a_ride_pdf_that_carries_another_trips_id_is_refused(browser, tmp_path):
    pdf = make_pdf(browser, ["Jun 15, 2026", "Total $18.64", "Receipt ID # %s" % TRIP_C])
    receipt_path = "/trips/%s/receipt" % TRIP_A
    fake, page = riders_site(browser, **{
        "/graphql": graphql(RIDE_PAGES, receipts={TRIP_A: ride_receipt(TRIP_A)}),
        receipt_path: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, riders=page)
    purchase = Purchase(purchase_type="Rides", purchase_date="2026-06-15", order_number=TRIP_A,
                        total="$18.64")
    out = tmp_path / "Rides" / "2026-06-15 Uber Ride to Example Station Receipt.pdf"

    got = app._capture_document(page, purchase, out)

    assert got.outcome == delivery.WRONG
    assert not out.exists(), "nothing is filed under this purchase's name"
    assert not list(out.parent.glob("*.delivering")), "and nothing is left half done"


def test_a_lapsed_session_is_brought_back_by_loading_the_trips_page_again(browser, tmp_path):
    """RECORDED. After a while with nothing asked, the trips page's own calls
    answered a redirect while the sign-in was still good, and loading the
    page again brought the session back without anybody signing in."""
    fake, page = riders_site(browser, **{"/graphql": graphql(RIDE_PAGES, lapse=1)})
    app = _app(tmp_path, fake.context, riders=page)

    assert app._discover_rides() == 2

    assert len(fake.requested(RIDERS + "/trips")) == 2, "loaded once more, and only once"
    assert fake.operations()[:2] == ["Activities", "Activities"], "the first call asked again"
    assert not app._stopped_sides


def test_a_session_a_fresh_load_cannot_bring_back_stops_the_rides_side(browser, tmp_path, capsys):
    fake, page = riders_site(browser, **{"/graphql": graphql(RIDE_PAGES, lapse=99)})
    app = _app(tmp_path, fake.context, riders=page)
    # Signed out, the trips page sends the tab on to Uber's sign-in page.
    gone = html_answer("<script>location.href = '%s/v2/?next_url=x'</script>" % AUTH)
    fake.at(RIDERS + "/trips", lambda request: (
        TRIPS_PAGE if len(fake.requested(RIDERS + "/trips")) == 1 else gone))

    assert app._discover_rides() == 0

    assert app._stopped_sides == {"Rides"} and id(page) in app._left_open
    assert page.url.startswith(AUTH), "the tab is left on the sign-in page for the person"
    assert len(fake.requested(RIDERS + "/graphql")) == 1, "never asked again in a loop"
    assert "Uber asked you to sign in again for your trips" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        app._stop_if_unfinished()


def test_a_failure_file_written_after_a_receipt_carries_no_trip_or_receipt_id(browser, tmp_path):
    """A failure file is a thing a tester posts in public, and a receipt's
    address and answer carry the trip's id. The request census still says
    which calls were made."""
    pdf = make_pdf(browser, ["Jun 15, 2026", "Total $18.64", "Receipt ID # %s" % TRIP_A])
    receipt_path = "/trips/%s/receipt" % TRIP_A
    fake, page = riders_site(browser, **{
        "/graphql": graphql(RIDE_PAGES, receipts={TRIP_A: ride_receipt(TRIP_A)}),
        receipt_path: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, riders=page)
    del app.write_failure                       # the real one, writing the real file
    app._requests = Requests(page, site.is_safe_url)
    app._requests.start()
    purchase = Purchase(purchase_type="Rides", purchase_date="2026-06-15", order_number=TRIP_A,
                        total="$18.64")
    out = tmp_path / "Rides" / "2026-06-15 Uber Ride to Example Station Receipt.pdf"
    assert app._capture_document(page, purchase, out).outcome == delivery.SAVED

    app.write_failure("save the receipt", "the receipt was not saved")

    written = next(app.paths.diagnostics.glob("failure-*.json")).read_text(encoding="utf-8")
    assert TRIP_A not in written and TRIP_A.replace("-", "") not in written
    assert "/graphql" in written, "the calls are still described"
    report = json.loads(written)
    asked = [e for e in report["journal"]["entries"] if e.get("outcome") == "asked for the receipt"]
    assert asked and asked[0]["facts"]["status"] == 200


# -- Uber Eats, made up ----------------------------------------------------------------

def order(uuid, store, cents, when, items=None, canceled=False):
    return {"baseEaterOrder": {
                "uuid": uuid, "isCancelled": canceled, "isCompleted": not canceled,
                "completedAt": None if canceled else when, "lastStateChangeAt": when,
                "fulfillmentType": "DELIVERY",
                "shoppingCart": {"items": items or [{"title": "Turkey Club", "price": 1275,
                                                     "quantity": 1}]}},
            "storeInfo": {"title": store}, "fareInfo": {"totalPrice": cents}}


EATS_ORDERS = [
    order(ORDER_A, "Example Deli", 2735, "2026-04-18T18:11:52.604Z"),
    order(ORDER_B, "Example Hardware", 0, "2026-01-08T15:20:11.000Z", items=[], canceled=True),
    order(ORDER_C, "Example Curry House", 2291, "2025-10-30T16:32:05.771Z"),
]


def past_orders(orders, per_page=2):
    """POST /_p/api/getPastOrdersV1, ten at a time on Uber and two here,
    the next ones by the last one's uuid, the way the page's own code asks."""
    def answer(request):
        body = json.loads(request.post_data or "{}")
        last = body.get("lastWorkflowUUID") or ""
        uuids = [o["baseEaterOrder"]["uuid"] for o in orders]
        start = uuids.index(last) + 1 if last else 0
        chunk = orders[start:start + per_page]
        return json_answer({"status": "success", "data": {
            "ordersMap": {o["baseEaterOrder"]["uuid"]: o for o in chunk},
            "orderUuids": [o["baseEaterOrder"]["uuid"] for o in chunk],
            "paginationData": {"nextCursor": "{}"},
            "meta": {"hasMore": start + per_page < len(orders)}}})
    return answer


def eats_receipt(receipt_html, stamp):
    def answer(request):
        body = json.loads(request.post_data or "{}")
        if body.get("contentType") != "WEB_HTML" or "workflowUuid" not in body:
            return json_answer({"status": "failure", "data": {"code": "400"}})
        return json_answer({"status": "success", "data": {
            "receiptData": receipt_html, "isPDFSupported": True, "timestamp": stamp,
            "receiptsForJob": [{"timestamp": stamp, "type": "TIPPED", "eventUUID": "e1"}],
            "actions": [{"type": "DOWNLOAD_PDF"}, {"type": "RESEND_EMAIL"}]}})
    return answer


def eats_site(browser, **pages):
    fake = FakeUber(browser)
    fake.at(EATS + "/orders", EATS_PAGE)
    for url, answer in pages.items():
        fake.at(EATS + url, answer)
    page = fake.context.new_page()
    page.goto(EATS + "/orders")
    return fake, page


def test_uber_eats_orders_are_read_the_way_show_more_asks(browser, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "local_date", _eastern(site.local_date))
    fake, page = eats_site(browser, **{"/_p/api/getPastOrdersV1": past_orders(EATS_ORDERS)})
    app = _app(tmp_path, fake.context, eats=page)

    assert app._discover_eats() == 2

    assert sorted(app.discovery.data) == ["Uber Eats:" + ORDER_A, "Uber Eats:" + ORDER_C]
    a = app.discovery.data["Uber Eats:" + ORDER_A]
    assert (a["purchase_date"], a["total"], a["summary_hint"], a["store_info"]) == \
        ("2026-04-18", "$27.35", "Eats Example Deli", "Example Deli")
    assert app.stats["unpaid_skipped"] == 1, "the canceled order that cost nothing"
    asked = fake.requested(EATS + "/_p/api/getPastOrdersV1")
    assert [json.loads(s[3]) for s in asked] == [{"lastWorkflowUUID": ""},
                                                {"lastWorkflowUUID": ORDER_B}]
    assert all(s[2].get("x-csrf-token") == "x" for s in asked)


def _eastern(real):
    """This computer's zone, pinned to America's east coast for the test."""
    from datetime import timedelta, timezone
    zone = timezone(timedelta(hours=-5))
    return lambda stamp, tz=None: real(stamp, tz or zone)


def test_a_newer_eats_receipt_is_checked_for_the_receipt_id_it_prints(browser, tmp_path):
    stamp = "2026-04-18T19:22:07.315Z"
    pdf = make_pdf(browser, ["April 18, 2026", "Thanks for tipping, Dana", "Total $27.35",
                             "Receipt ID # %s" % RECEIPT_ID])
    download = "/orders/%s/download-receipt" % ORDER_A
    fake, page = eats_site(browser, **{
        "/_p/api/getReceiptByWorkflowUuidV1": eats_receipt(
            "<p>Receipt ID # %s</p>" % RECEIPT_ID, stamp),
        download: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, eats=page)
    purchase = Purchase(purchase_type="Uber Eats", purchase_date="2026-04-18",
                        order_number=ORDER_A, total="$27.35")
    out = tmp_path / "Uber Eats" / "2026-04-18 Uber Eats Example Deli Receipt.pdf"

    got = app._capture_document(page, purchase, out)

    assert got.outcome == delivery.SAVED, got.report()
    assert got.verdict.outcome == "verified"
    asked = fake.requested(EATS + download)
    assert len(asked) == 1
    assert parse_qs(asked[0][4]) == {"contentType": ["PDF"], "timestamp": [stamp]}


def test_an_older_eats_receipt_is_filed_by_its_own_date_and_total(browser, tmp_path):
    """Before December 2025 an Eats receipt prints no Receipt ID, RECORDED.
    It is filed when it carries its own date and total, and refused when it
    carries another order's date and total instead."""
    stamp = "2025-10-30T17:41:26.208Z"
    mine = make_pdf(browser, ["October 30, 2025", "Thanks for ordering, Dana",
                              "Here's your receipt for Example Curry House.", "Total", "$22.91"])
    theirs = make_pdf(browser, ["October 31, 2025", "Thanks for ordering, Dana",
                                "Here's your receipt for Example Noodles.", "Total", "$18.40"])
    download = "/orders/%s/download-receipt" % ORDER_C
    served = {"pdf": mine}
    fake, page = eats_site(browser, **{
        "/_p/api/getReceiptByWorkflowUuidV1": eats_receipt("<p>Thanks for ordering</p>", stamp),
        download: lambda request: pdf_answer(served["pdf"])})
    app = _app(tmp_path, fake.context, eats=page)
    neighbour = Purchase(purchase_type="Uber Eats", purchase_date="2025-10-31",
                         order_number=ORDER_B, total="$18.40",
                         items=[Item(name="Dan Dan Noodles")])
    app.discovery.update(neighbour.key, neighbour.to_dict(), save=False)
    purchase = Purchase(purchase_type="Uber Eats", purchase_date="2025-10-30",
                        order_number=ORDER_C, total="$22.91")
    app.discovery.update(purchase.key, purchase.to_dict(), save=False)
    out = tmp_path / "Uber Eats" / "2025-10-30 Uber Eats Example Curry House Receipt.pdf"

    got = app._capture_document(page, purchase, out)
    assert got.outcome == delivery.SAVED, got.report()
    assert got.verdict.outcome == "verified"

    out.unlink()
    served["pdf"] = theirs
    got = app._capture_document(page, purchase, out)
    assert got.outcome == delivery.WRONG
    assert not out.exists()


def test_an_older_receipt_that_never_says_uber_is_filed_not_sent_for_review(browser, tmp_path):
    """RECORDED. An older Uber Eats receipt paid by card can never
    prints the word Uber, and its items were named Plate and Bowl, so the
    last check before filing found nothing it knew to look for and sent a
    good receipt to Manual Review. It carries its total, its store and its
    date as a receipt writes it, and those are looked for too."""
    stamp = "2025-03-06T18:09:44.571Z"
    pdf = make_pdf(browser, ["Card ending 0000", "March 6, 2025", "Thanks for ordering, Dana",
                             "Here's your receipt for Example Wok (100 Example Rd).", "Total",
                             "$41.86", "1", "Plate", "$11.40", "1", "Bowl", "$9.85",
                             "Subtotal", "$31.10", "Payments", "$41.86"])
    download = "/orders/%s/download-receipt" % ORDER_C
    fake, page = eats_site(browser, **{
        "/_p/api/getReceiptByWorkflowUuidV1": eats_receipt("<p>Thanks for ordering</p>", stamp),
        download: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, eats=page)
    purchase = Purchase(purchase_type="Uber Eats", purchase_date="2025-03-06",
                        order_number=ORDER_C, total="$41.86", store_info="Example Wok",
                        items=[Item(name="Plate"), Item(name="Bowl")])
    purchase.summary = "Eats Example Wok"
    app.discovery.update(purchase.key, purchase.to_dict(), save=False)

    assert app._save_receipt(page, purchase, {})

    assert Path(purchase.pdf_path).parent == tmp_path / "Uber Eats"
    assert not list(app.paths.manual_review.glob("*.pdf"))
    assert app.progress.get(purchase.key)["downloaded_ok"] is True


def test_an_older_receipt_is_not_refused_by_the_orders_around_it(browser, tmp_path):
    """A review of 0.40.0. One order shares this one's day, another its
    total, and the first one's total is printed on this receipt as an
    item's price. Counted against its neighbors the receipt had nothing of
    its own left and was refused and destroyed. It carries its own date and
    total, so it is filed."""
    stamp = "2025-10-30T17:41:26.208Z"
    pdf = make_pdf(browser, ["October 30, 2025", "Thanks for ordering, Dana",
                             "Here's your receipt for Example Curry House.", "Total", "$22.91",
                             "1", "Plate", "$11.40", "Subtotal", "$19.95"])
    download = "/orders/%s/download-receipt" % ORDER_C
    fake, page = eats_site(browser, **{
        "/_p/api/getReceiptByWorkflowUuidV1": eats_receipt("<p>Thanks for ordering</p>", stamp),
        download: pdf_answer(pdf)})
    app = _app(tmp_path, fake.context, eats=page)
    for uuid, day, total in ((ORDER_A, "2025-10-30", "$11.40"), (ORDER_B, "2025-11-01", "$22.91")):
        neighbor = Purchase(purchase_type="Uber Eats", purchase_date=day, order_number=uuid,
                            total=total)
        app.discovery.update(neighbor.key, neighbor.to_dict(), save=False)
    purchase = Purchase(purchase_type="Uber Eats", purchase_date="2025-10-30",
                        order_number=ORDER_C, total="$22.91")
    out = tmp_path / "Uber Eats" / "2025-10-30 Uber Eats Example Curry House Receipt.pdf"

    got = app._capture_document(page, purchase, out)

    assert got.outcome == delivery.SAVED, got.report()
    assert got.verdict.outcome == "verified" and out.exists()


def test_an_eats_order_uber_keeps_no_receipt_for_is_not_fetched(browser, tmp_path):
    fake, page = eats_site(browser, **{
        "/_p/api/getReceiptByWorkflowUuidV1": json_answer({"status": "failure", "data": {
            "code": "404", "message": "could not find receipt"}})})
    app = _app(tmp_path, fake.context, eats=page)
    purchase = Purchase(purchase_type="Uber Eats", purchase_date="2026-01-08",
                        order_number=ORDER_B, total="$3.00")
    out = tmp_path / "Uber Eats" / "x.pdf"

    assert app._capture_document(page, purchase, out) is None
    assert not [s for s in fake.seen if "download-receipt" in s[1]]


def test_a_signed_out_eats_answer_stops_the_eats_side(browser, tmp_path, capsys):
    fake, page = eats_site(browser, **{
        "/_p/api/getPastOrdersV1": json_answer({"status": "failure", "data": {"code": "401"}})})
    app = _app(tmp_path, fake.context, eats=page)

    assert app._discover_eats() == 0

    assert app._stopped_sides == {"Uber Eats"} and id(page) in app._left_open
    assert len(fake.requested(EATS + "/_p/api/getPastOrdersV1")) == 2, \
        "asked once more after a fresh load, and then never again"
    assert "Uber Eats asked you to sign in" in capsys.readouterr().out
