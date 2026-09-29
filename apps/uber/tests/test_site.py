"""Uber's site layer without a browser: what it reads out of Uber's answers,
what it refuses to send, and how it walks the two lists. Every trip, order,
store and amount is invented."""
import base64
import sys
from datetime import timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import uber_site as site

TRIP_A = "0a1b2c3d-1111-4222-8333-444455556666"
TRIP_B = "0a1b2c3d-7777-4888-9999-aaaabbbbcccc"
ORDER_A = "5e6f7a8b-1234-4567-89ab-cdef01234567"
ORDER_B = "5e6f7a8b-2345-4678-9abc-def012345678"
ORDER_C = "5e6f7a8b-3456-4789-abcd-ef0123456789"


@pytest.fixture(autouse=True)
def _no_pauses(monkeypatch):
    monkeypatch.setattr(site, "LIST_PAUSE_MS", 0)


# -- dates and money ---------------------------------------------------------------

def test_a_trip_start_is_read_the_way_javascript_writes_it():
    stamp = "Mon Jun 15 2026 18:05:10 GMT+0000 (Coordinated Universal Time)"
    assert site.local_date(stamp, timezone.utc) == "2026-06-15"


def test_an_evening_order_in_america_is_filed_on_its_own_day():
    """Uber writes times in UTC, so an order at 9 PM Eastern reads as the
    next day until it is moved."""
    from datetime import timedelta
    eastern = timezone(timedelta(hours=-4))
    assert site.local_date("2026-04-19T01:05:00.000Z", eastern) == "2026-04-18"
    assert site.local_date("Sun Apr 19 2026 01:05:00 GMT+0000 (Coordinated Universal Time)",
                           eastern) == "2026-04-18"


def test_a_receipt_time_in_milliseconds_is_read_too():
    assert site.local_date("1767225600000", timezone.utc) == "2026-01-01"


@pytest.mark.parametrize("bad", ["", "soon", "Fri Foo 10 2026 18:42:48 GMT+0000",
                                 "2026-02-30T10:00:00Z"])
def test_a_time_that_cannot_be_read_gives_no_day(bad):
    assert site.local_date(bad, timezone.utc) == ""


def test_cents_are_printed_the_way_a_receipt_prints_them():
    """Uber sends some amounts as floats that miss by a hair."""
    assert site.dollars(2045.9999999999998) == "$20.46"
    assert site.dollars(13480) == "$134.80"
    assert site.dollars(0) == "$0.00"
    assert site.dollars(123456) == "$1,234.56"
    assert site.dollars(None) == ""


def test_what_a_trip_cost_comes_from_its_description():
    paid = {"description": "$18.64"}
    free = {"description": "$0.00 • Canceled"}
    fee = {"description": "$5.00 • Canceled"}
    assert site.ride_is_paid(paid) and not site.ride_is_canceled(paid)
    assert not site.ride_is_paid(free) and site.ride_is_canceled(free)
    assert site.ride_is_paid(fee), "a cancellation fee is money spent, and has a receipt"


def test_a_subtitle_is_placed_in_its_page_window():
    """The list writes no year, even for a trip from the year before."""
    upper = "2026-01-10T15:00:00.000Z"
    lower = "2025-11-01T15:00:00.000Z"
    assert site.subtitle_date("Nov 12 • 2:40 PM", [upper, lower]) == "2025-11-12"
    assert site.subtitle_date("Jan 4 • 9:00 AM", [upper, lower]) == "2026-01-04"
    assert site.subtitle_date("Oct 20 • 9:00 AM", [upper, lower]) == "", \
        "a day outside the window is not placed"
    assert site.subtitle_date("no date here", [upper, lower]) == ""


def test_a_page_token_is_the_time_it_ends():
    token = base64.b64encode(b"2025-11-12T18:02:44.118Z").decode()
    assert site.token_time(token) == "2025-11-12T18:02:44.118Z"
    assert site.token_time("not base64!") == ""
    assert site.token_time(base64.b64encode(b"hello").decode()) == ""


# -- building purchases --------------------------------------------------------------

def ride_row(uuid=TRIP_A, where="Example Station", description="$18.64",
             subtitle="Jun 15 • 1:55 PM"):
    return {"uuid": uuid, "title": where, "description": description, "subtitle": subtitle,
            "cardURL": "https://riders.uber.com/trips/%s" % uuid, "_window": ["", ""]}


def trip(begin="Mon Jun 15 2026 18:05:10 GMT+0000 (Coordinated Universal Time)",
         fare="$18.64"):
    return {"begin": begin, "fare": fare, "status": "COMPLETED", "uuid": TRIP_A,
            "vehicle": "Comfort", "distance": "2.80", "distance_label": "miles",
            "duration": "9 minutes"}


def test_a_ride_is_a_purchase_named_for_where_it_went(monkeypatch):
    monkeypatch.setattr(site, "local_date",
                        lambda stamp, tz=None: "2026-06-15" if stamp else "")
    p = site.ride_purchase(ride_row(), trip())
    assert (p.purchase_type, p.purchase_date, p.order_number, p.total) == \
        ("Rides", "2026-06-15", TRIP_A, "$18.64")
    assert p.items[0].name == "Comfort, 2.80 miles, 9 minutes"
    assert p.receipt_url == "https://riders.uber.com/trips/" + TRIP_A
    assert site.ride_summary(ride_row()) == "Ride to Example Station"


def test_a_ride_with_no_start_is_placed_by_its_subtitle():
    row = ride_row(description="$5.00 • Canceled")
    row["_window"] = ["2026-08-01T12:00:00.000Z", "2026-06-01T12:00:00.000Z"]
    p = site.ride_purchase(row, trip(begin=""))
    assert p.purchase_date == "2026-06-15" and p.status == "Canceled"


def test_a_ride_that_cannot_be_placed_is_not_made_up():
    row = ride_row(subtitle="sometime")
    assert site.ride_purchase(row, trip(begin="")) is None


def order(uuid=ORDER_A, store="Example Deli", cents=2735, when="2026-04-18T18:11:52.604Z",
          canceled=False, completed=True, items=None, kind="DELIVERY"):
    return {"baseEaterOrder": {
                "uuid": uuid, "isCancelled": canceled, "isCompleted": completed,
                "completedAt": when if completed else None, "lastStateChangeAt": when,
                "fulfillmentType": kind,
                "shoppingCart": {"items": items if items is not None else [
                    {"title": "Turkey Club", "price": 1275, "quantity": 1},
                    {"title": "Iced Tea", "price": 299, "quantity": 2}]}},
            "storeInfo": {"title": store},
            "fareInfo": {"totalPrice": cents, "checkoutInfo": []}}


def test_an_order_is_a_purchase_named_for_its_store(monkeypatch):
    p = site.eats_purchase(order())
    assert (p.purchase_type, p.order_number, p.total, p.status, p.store_info) == \
        ("Uber Eats", ORDER_A, "$27.35", "Completed", "Example Deli")
    assert p.fulfillment == "Delivery"
    assert [(i.name, i.quantity, i.unit_price, i.line_total) for i in p.items] == [
        ("Turkey Club", "1", "$12.75", "$12.75"), ("Iced Tea", "2", "$2.99", "$5.98")]
    assert p.receipt_url == ("https://www.ubereats.com/orders?mod=orderReceipt&modctx=%s&ps=1"
                             % ORDER_A)
    assert site.eats_summary(order()) == "Eats Example Deli"


def test_an_order_that_cost_nothing_is_not_paid():
    assert site.eats_is_paid(order())
    assert not site.eats_is_paid(order(cents=0, canceled=True, completed=False))
    assert not site.eats_is_paid(order(cents=0, completed=False, items=[]))
    assert not site.eats_is_paid(order(cents=0.4)), "less than a cent rounds to nothing"


def test_a_receipt_id_is_read_out_of_the_receipt_uber_answered():
    html = ('<div class="payment-meta-text">  Receipt ID # %s  <div class="divider">'
            % TRIP_A.upper())
    assert site.receipt_id_in(html) == TRIP_A
    assert site.receipt_id_in("<p>Thanks for ordering</p>") == ""
    assert site.receipt_id_in("") == ""


def test_the_identity_is_the_receipt_id_when_there_is_one():
    p = site.eats_purchase(order())
    by_id = site.identity_for(p, ORDER_B)
    assert by_id.number == ORDER_B and not by_id.date and not by_id.total
    by_facts = site.identity_for(p, "")
    assert not by_facts.number and by_facts.date == p.purchase_date and by_facts.total == "$27.35"


# -- what is refused before it is sent ----------------------------------------------

class Page:
    """A tab that answers the site layer's calls from a script."""

    def __init__(self, url="https://riders.uber.com/trips", answers=None, pdf=None):
        self.url = url
        self.answers = list(answers or [])
        self.pdf = pdf
        self.calls, self.waits, self.loads = [], [], []

    def evaluate(self, js, args):
        if js is site._PDF_JS:
            self.calls.append(("pdf", args[0]))
            return self.pdf.pop(0) if isinstance(self.pdf, list) else self.pdf
        path, headers, body = args
        self.calls.append((path, dict(headers), body))
        answer = self.answers.pop(0)
        return answer(body) if callable(answer) else answer

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def goto(self, url, **kw):
        self.loads.append(url)

    def locator(self, selector):
        class _None:
            def count(self):
                return 0

            def inner_text(self, timeout=0):
                return ""
        return _None()

    def title(self):
        return ""


def gql_answer(data, status=200):
    return {"status": status, "redirected": False, "failed": False, "data": {"data": data}}


def eats_answer(data, status=200, word="success"):
    return {"status": status, "redirected": False, "failed": False,
            "data": {"status": word, "data": data}}


REDIRECT = {"status": 0, "redirected": True, "failed": False, "data": None}


def test_only_the_three_queries_are_ever_made():
    page = Page()
    with pytest.raises(ValueError):
        site.gql(page, "SendReceiptEmail", {"tripUUID": TRIP_A})
    with pytest.raises(ValueError):
        site.gql(page, "RateTrip", {})
    assert page.calls == []


def test_no_query_this_app_makes_is_a_mutation():
    for text in site.QUERIES.values():
        assert not site._MUTATION_RE.match(text)
        assert "mutation" not in text.lower() and "sendreceipt" not in text.lower()


def test_a_mutation_is_refused_even_under_an_allowed_name(monkeypatch):
    monkeypatch.setitem(site.QUERIES, "GetReceipt",
                        "mutation SendReceiptEmail($tripUUID: String!) { x }")
    page = Page()
    with pytest.raises(ValueError):
        site.gql(page, "GetReceipt", {"tripUUID": TRIP_A})
    assert page.calls == []


def test_only_the_two_eats_calls_are_ever_made():
    page = Page(url="https://www.ubereats.com/orders")
    for name in ("sendReceiptEmailV1", "createOrderV1", "getPastOrdersV1/../x"):
        with pytest.raises(ValueError):
            site.eats_call(page, name, {})
    assert page.calls == []


def test_a_call_is_not_made_from_a_tab_on_another_site():
    page = Page(url="https://help.uber.com/riders")
    got = site.gql(page, "Activities", {})
    assert got["failed"] and page.calls == []
    page = Page(url="https://riders.uber.com/trips")
    assert site.eats_call(page, "getPastOrdersV1", {})["failed"] and page.calls == []


def test_the_calls_carry_the_headers_the_page_sends():
    page = Page(answers=[gql_answer({"getTrip": {"trip": {}, "receipt": {}}})])
    site.gql(page, "GetTrip", {"tripUUID": TRIP_A})
    path, headers, body = page.calls[0]
    assert path == "/graphql"
    assert headers == {"x-csrf-token": "x", "x-uber-rv-session-type": "desktop_session"}
    assert body["operationName"] == "GetTrip" and body["variables"] == {"tripUUID": TRIP_A}


@pytest.mark.parametrize("uuid", ["", "../trips", TRIP_A + "/x", "0A1B2C3D"])
def test_a_receipt_path_is_built_only_from_a_uuid(uuid):
    with pytest.raises(ValueError):
        site.ride_pdf_path(uuid, "1781563527104")
    with pytest.raises(ValueError):
        site.eats_pdf_path(uuid, "2026-04-18T19:22:07.315Z")


def test_a_receipt_path_refuses_a_time_of_the_wrong_shape():
    with pytest.raises(ValueError):
        site.ride_pdf_path(TRIP_A, "tomorrow&contentType=HTML")
    with pytest.raises(ValueError):
        site.eats_pdf_path(ORDER_A, "1781563527104")
    assert site.ride_pdf_path(TRIP_A, "1781563527104") == (
        "/trips/%s/receipt?contentType=PDF&timestamp=1781563527104" % TRIP_A)
    assert site.eats_pdf_path(ORDER_A, "2026-04-18T19:22:07.315Z") == (
        "/orders/%s/download-receipt?contentType=PDF&timestamp=2026-04-18T19:22:07.315Z"
        % ORDER_A)


def test_a_pdf_is_fetched_only_from_a_path_this_app_built():
    page = Page()
    for path in ("https://example.com/x.pdf", "//evil.example/x", "/graphql"):
        with pytest.raises(ValueError):
            site.fetch_pdf(page, path)
    assert page.calls == []


# -- what an answer means -------------------------------------------------------------

def test_a_graphql_answer_is_read_for_what_it_means():
    assert site.gql_kind(gql_answer({"x": 1})) == site.ANSWERED
    assert site.gql_kind(REDIRECT) == site.SIGNED_OUT
    assert site.gql_kind(gql_answer({}, status=401)) == site.SIGNED_OUT
    assert site.gql_kind({"status": 200, "data": {"errors": [
        {"message": "x", "extensions": {"redirectUrl": "https://auth.uber.com/"}}]}}) == site.SIGNED_OUT
    assert site.gql_kind({"status": 200, "data": {"errors": [
        {"message": "x", "extensions": {"code": "UNAUTHENTICATED"}}]}}) == site.SIGNED_OUT
    assert site.gql_kind({"status": 200, "data": {"errors": [{"message": "no"}], "data": None}}) \
        == site.REFUSED
    assert site.gql_kind({"status": 0, "failed": True}) == site.FAILED
    assert site.gql_kind(gql_answer({}, status=500)) == site.REFUSED


def test_an_eats_answer_is_read_for_what_it_means():
    assert site.eats_kind(eats_answer({"x": 1})) == site.ANSWERED
    assert site.eats_kind(eats_answer({"code": "404", "message": "could not find receipt"},
                                      word="failure")) == site.REFUSED
    assert site.eats_kind(eats_answer({"code": "401"}, word="failure")) == site.SIGNED_OUT
    assert site.eats_kind(REDIRECT) == site.SIGNED_OUT
    assert site.eats_kind({"status": 0, "failed": True}) == site.FAILED


def test_a_lapsed_session_is_brought_back_by_loading_the_page_again():
    """RECORDED. After a while with nothing asked, the trips page's calls
    answer a redirect while the sign-in is still good, and loading the page
    again brings it back."""
    page = Page(answers=[REDIRECT, gql_answer({"getTrip": {"trip": {"fare": "$9.00"},
                                                           "receipt": {}}})])
    got = site.read_trip(page, TRIP_A)
    assert got["kind"] == site.ANSWERED and got["trip"]["fare"] == "$9.00"
    assert page.loads == [site.TRIPS_URL], "the trips page is loaded again, once"
    assert len(page.calls) == 2


def test_a_lapse_the_page_cannot_bring_back_is_a_sign_in():
    page = Page(answers=[REDIRECT])

    def goto(url, **kw):
        page.loads.append(url)
        page.url = "https://auth.uber.com/v2/?next_url=x"
    page.goto = goto
    got = site.read_trip(page, TRIP_A)
    assert got["kind"] == site.SIGNED_OUT
    assert len(page.calls) == 1, "never asked again once the page says sign in"


def test_a_reload_that_passes_through_the_sign_in_host_is_not_a_sign_in():
    """RECORDED. The fresh load that brings a lapsed session back goes
    through auth.uber.com on its own. A tab seen there before it has come
    back is not signed out (review of 0.40.0)."""
    page = Page(answers=[REDIRECT, gql_answer({"getTrip": {"trip": {"fare": "$9.00"},
                                                           "receipt": {}}})])
    hops = ["https://auth.uber.com/v2/?next_url=x", "https://auth.uber.com/v2/?x=2",
            "https://riders.uber.com/trips?_csid=x&state=y"]

    def goto(url, **kw):
        page.loads.append(url)
        page.url = hops[0]

    def wait(ms):
        page.waits.append(ms)
        page.url = hops[min(len(page.waits), len(hops) - 1)]
    page.goto, page.wait_for_timeout = goto, wait
    got = site.read_trip(page, TRIP_A)
    assert got["kind"] == site.ANSWERED and got["trip"]["fare"] == "$9.00"
    assert len(page.waits) == 2 and len(page.calls) == 2


def test_a_second_redirect_after_a_fresh_load_is_a_sign_in():
    page = Page(answers=[REDIRECT, REDIRECT])
    assert site.read_trip(page, TRIP_A)["kind"] == site.SIGNED_OUT
    assert len(page.calls) == 2 and len(page.loads) == 1


# -- walking the lists ------------------------------------------------------------------

def activities(rows, token=""):
    return gql_answer({"activities": {"cityID": 8, "past": {"activities": rows,
                                                             "nextPageToken": token or None}}})


def test_the_trip_list_is_walked_to_its_end_for_each_profile():
    t1 = base64.b64encode(b"2026-03-01T12:00:00.000Z").decode()
    page = Page(answers=[
        activities([ride_row(TRIP_A)], t1),
        activities([ride_row(TRIP_B, description="$0.00 • Canceled")]),
        activities([]),
    ])
    walk = site.walk_rides(page)
    assert [r["uuid"] for r in walk["rides"]] == [TRIP_A, TRIP_B]
    assert walk["stop"] == site.END and walk["pages"] == 3
    bodies = [c[2]["variables"] for c in page.calls]
    assert [v["profileType"] for v in bodies] == ["PERSONAL", "PERSONAL", "BUSINESS"]
    assert bodies[1]["nextPageToken"] == t1 and "nextPageToken" not in bodies[0]
    assert all(v["orderTypes"] == ["RIDES", "TRAVEL"] and v["includeUpcoming"] is False
               for v in bodies)
    assert walk["rides"][0]["_window"] == ["", "2026-03-01T12:00:00.000Z"]
    assert walk["rides"][1]["_window"] == ["2026-03-01T12:00:00.000Z", ""]


def test_a_trip_listed_twice_is_kept_once():
    t1 = base64.b64encode(b"2026-03-01T12:00:00.000Z").decode()
    page = Page(answers=[activities([ride_row(TRIP_A)], t1), activities([ride_row(TRIP_A)]),
                         activities([ride_row(TRIP_A)])])
    assert [r["uuid"] for r in site.walk_rides(page)["rides"]] == [TRIP_A]


def test_the_floor_ends_one_profile_and_the_next_is_still_read():
    """A review of 0.40.0 found a start date ending the personal trips
    and with them the whole walk, so business trips in scope were never
    asked for, on every run and without a word."""
    t1 = base64.b64encode(b"2024-03-01T12:00:00.000Z").decode()
    page = Page(answers=[activities([ride_row(TRIP_A)], t1),
                         activities([ride_row(TRIP_B)])])
    walk = site.walk_rides(page, limit_date="2025-01-01")
    assert [c[2]["variables"]["profileType"] for c in page.calls] == ["PERSONAL", "BUSINESS"]
    assert [r["uuid"] for r in walk["rides"]] == [TRIP_A, TRIP_B]
    assert walk["stop"] == site.DATE_LIMIT and walk["pages"] == 2


def test_a_sign_in_ends_the_whole_walk():
    page = Page(answers=[REDIRECT, REDIRECT])
    walk = site.walk_rides(page)
    assert walk["stop"] == site.SIGNED_OUT
    assert [c[2]["variables"]["profileType"] for c in page.calls] == ["PERSONAL", "PERSONAL"]


def test_a_token_that_repeats_is_not_followed_to_the_page_cap():
    t1 = base64.b64encode(b"2026-03-01T12:00:00.000Z").decode()
    page = Page(answers=[activities([ride_row(TRIP_A)], t1),
                         activities([ride_row(TRIP_A)], t1),
                         activities([])])
    walk = site.walk_rides(page)
    assert walk["pages"] == 3 and walk["stop"] == site.END
    assert [c[2]["variables"]["profileType"] for c in page.calls] == [
        "PERSONAL", "PERSONAL", "BUSINESS"]


def test_a_trip_list_that_stops_answering_says_why():
    page = Page(answers=[gql_answer({}, status=500)])
    assert site.walk_rides(page)["stop"] == site.REFUSED


def eats_page(orders, more=True):
    return eats_answer({"ordersMap": {site.order_uuid(o): o for o in orders},
                        "orderUuids": [site.order_uuid(o) for o in orders],
                        "paginationData": {"nextCursor": "x"}, "meta": {"hasMore": more}})


def test_the_eats_list_is_walked_the_way_show_more_asks():
    """The next ten are asked for with the last order's uuid, RECORDED from
    the page's own code, until it says there are no more."""
    page = Page(url="https://www.ubereats.com/orders", answers=[
        eats_page([order(ORDER_A), order(ORDER_B)]),
        eats_page([order(ORDER_C, when="2025-10-30T16:32:05.771Z")], more=False)])
    walk = site.walk_eats(page)
    assert [site.order_uuid(o) for o in walk["orders"]] == [ORDER_A, ORDER_B, ORDER_C]
    assert [c[2] for c in page.calls] == [{"lastWorkflowUUID": ""},
                                          {"lastWorkflowUUID": ORDER_B}]
    assert all(c[1] == {"x-csrf-token": "x"} and c[0] == "/_p/api/getPastOrdersV1"
               for c in page.calls)
    assert walk["stop"] == site.END


def test_an_eats_list_that_repeats_itself_is_not_walked_forever():
    page = Page(url="https://www.ubereats.com/orders",
                answers=[eats_page([order(ORDER_A)])] * 5)
    walk = site.walk_eats(page)
    assert walk["pages"] == 2 and len(walk["orders"]) == 1


# -- the receipt calls --------------------------------------------------------------------

def test_a_ride_receipt_answers_its_newest_time_and_its_receipt_id():
    receipt = {"getReceipt": {
        "actionList": [{"type": "DOWNLOAD_PDF"}, {"type": "RESEND_EMAIL"}],
        "receiptData": "<p>Receipt ID # %s</p>" % TRIP_A,
        "receiptsForJob": [{"timestamp": "1781563527104", "type": "COMPLETED"},
                           {"timestamp": "1781551222580", "type": "COMPLETED"}]}}
    page = Page(answers=[gql_answer(receipt)])
    got = site.read_ride_receipt(page, TRIP_A)
    assert (got["kind"], got["stamp"], got["pdf"], got["receipt_id"], got["count"]) == \
        (site.ANSWERED, "1781563527104", True, TRIP_A, 2)


def test_a_canceled_trip_answers_no_receipt():
    page = Page(answers=[gql_answer({"getReceipt": {"actionList": [], "receiptData": "",
                                                    "receiptsForJob": []}})])
    got = site.read_ride_receipt(page, TRIP_A)
    assert got["kind"] == site.ANSWERED and not got["pdf"] and not got["stamp"]


def test_an_eats_receipt_answers_its_time_and_says_whether_it_prints_an_id():
    page = Page(url="https://www.ubereats.com/orders", answers=[
        eats_answer({"receiptData": "<p>Thanks for ordering</p>", "isPDFSupported": True,
                     "timestamp": "2025-10-30T17:41:26.208Z",
                     "receiptsForJob": [{"timestamp": "2025-10-30T17:41:26.208Z"}]})])
    got = site.read_eats_receipt(page, ORDER_C)
    assert (got["kind"], got["stamp"], got["pdf"], got["receipt_id"]) == \
        (site.ANSWERED, "2025-10-30T17:41:26.208Z", True, "")
    assert page.calls[0][2] == {"contentType": "WEB_HTML", "workflowUuid": ORDER_C,
                                "timestamp": None}


def test_the_pdf_comes_back_as_bytes():
    raw = b"%PDF-1.4 made up"
    page = Page(pdf={"status": 200, "redirected": False, "failed": False,
                     "type": "application/pdf", "b64": base64.b64encode(raw).decode()})
    got = site.fetch_pdf(page, site.ride_pdf_path(TRIP_A, "1781563527104"))
    assert got["kind"] == site.ANSWERED and got["data"] == raw


def test_a_pdf_that_is_not_there_is_refused_not_saved():
    page = Page(pdf={"status": 404, "redirected": False, "failed": False})
    got = site.fetch_pdf(page, site.ride_pdf_path(TRIP_A, ""))
    assert got["kind"] == site.REFUSED and got["data"] == b""


# -- safety ------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Resend Receipt", "Resend receipt by email", "Rate trip",
                                  "Get Help", "Add tip", "Order again", "Reorder",
                                  "Report an issue", "Pay now", "Sign out"])
def test_what_could_change_something_is_never_a_safe_control(name):
    assert not site.is_safe_control(name)


@pytest.mark.parametrize("name", ["View Receipt", "View receipt", "Download PDF",
                                  "Past Orders", "Details"])
def test_what_shows_a_receipt_is_a_safe_control(name):
    assert site.is_safe_control(name)


@pytest.mark.parametrize("url", ["https://riders.uber.com/trips", "https://www.ubereats.com/orders"])
def test_the_two_sites_are_safe(url):
    assert site.is_safe_url(url)


@pytest.mark.parametrize("url", ["http://riders.uber.com/trips", "https://auth.uber.com/v2/",
                                 "https://riders.uber.com.example.com/", "https://evil.example/",
                                 "https://help.uber.com/riders", "https://ubereats.com/orders"])
def test_nothing_else_is(url):
    assert not site.is_safe_url(url)


def test_a_sign_in_page_is_signed_out():
    assert site.looks_signed_out(Page(url="https://auth.uber.com/v2/?next_url=x"))
    assert site.looks_signed_out(Page(url="https://www.ubereats.com/login-redirect/?x=1"))
    assert not site.looks_signed_out(Page(url="https://riders.uber.com/trips"))
