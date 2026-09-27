"""The App Store side, against the shapes Report a Problem answered with on
the owner's own account, 2026-09-27. Every member, dsid, order, app and
amount here is invented."""
import sys
from datetime import timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_site as site

ORGANIZER, CHILD = "10000001", "10000002"

FAMILY = {"members": [
    {"dsid": ORGANIZER, "givenName": "Dana", "familyName": "Example", "pod": 1,
     "isAskToBuy": False, "isAskToBuyApprover": True, "isHeadOfHousehold": True,
     "mediaLinkSourceAccountInfo": None},
    {"dsid": CHILD, "givenName": "Quill", "familyName": "Example", "pod": 1,
     "isAskToBuy": True, "isAskToBuyApprover": False, "isHeadOfHousehold": False,
     "mediaLinkSourceAccountInfo": None},
]}


def pli(name, detail="", media="", kind="IOSApp", paid="$0.00", free=True,
        quantity=0, price=None):
    return {"itemId": "90000000000001", "purchaseId": "80000000000001",
            "storefrontId": "100000", "adamId": "7000000001", "guid": "TESTGUID",
            "title": None, "amountPaid": paid, "pliDate": "2026-05-14T12:00:00Z",
            "isFreePurchase": free, "isCredit": False, "quantity": quantity,
            "unitStorePrice": price,
            "localizedContent": {"nameForDisplay": name, "detailForDisplay": detail,
                                 "invoiceLine3": "", "artworkURL": "", "supportURL": "",
                                 "mediaType": media, "subscriptionCoverageDescription": None},
            "subscriptionInfo": None, "lineItemType": kind, "estimatedTotal": price}


def purchase(weborder, dsid=ORGANIZER, date="2026-05-14T12:00:00Z", invoice=None,
             plis=(), pending=False, estimated="$0.00"):
    return {"purchaseId": "80000000000001", "dsid": dsid, "invoiceAmount": invoice,
            "plis": list(plis), "weborder": weborder, "invoiceDate": None,
            "purchaseDate": date, "isPendingPurchase": pending,
            "estimatedTotalAmount": estimated}


APPLE_ONE = purchase("MLF0TEST01", invoice="$21.43", estimated="$21.43", plis=[
    pli("Premier", "Apple One", "Apple One Subscription", "FirstPartySubscriptionBundle",
        paid="$21.43", free=False, quantity=1, price="$21.43")])
FREE_APP = purchase("R00TEST0000001", plis=[pli("Lantern Notes", "Example Dev LLC", "iOS App")])
CHILD_COINS = purchase("MLF0TEST03", dsid=CHILD, invoice="$4.37", estimated="$4.37", plis=[
    pli("Blockville | 400 Bricks", "", "", "VideoPartnerBilling",
        paid="$4.37", free=False, quantity=1, price="$4.37")])
PENDING = purchase("MLF0TEST04", invoice="$1.23", estimated="$1.23", pending=True, plis=[
    pli("Gem Pack 3", "Crystal Quarry", "In-App Purchase", "BaseLineItem",
        paid="$1.23", free=False, quantity=1, price="$1.23")])
ICLOUD = purchase("MLF0TEST05", invoice="$3.12", estimated="$3.12", plis=[
    pli("iCloud+ with 200 GB storage", "iCloud", "iCloud+", "BaseSubscription",
        paid="$3.12", free=False, quantity=1, price="$3.12")])
# No invoiceAmount, and a line that was paid for all the same. Not seen on
# the owner's account, and kept by the rule for line items.
PAID_LINE_ONLY = purchase("MLF0TEST06", plis=[
    pli("Gem Pack 7", "Crystal Quarry", "In-App Purchase", "BaseLineItem",
        paid="$2.46", free=False, quantity=1, price="$2.46")])
# A free trial that starts with a receipt for nothing.
ZERO_INVOICE = purchase("MLF0TEST07", invoice="$0.00", plis=[
    pli("Harbor Plus Trial", "Puzzle Harbor: Daily Logic", "Init. Subscription",
        "BaseSubscription", paid="$0.00", free=False, quantity=1, price="$0.00")])


# -- the family -------------------------------------------------------------------

def test_the_family_is_read_with_its_organizer():
    members = site.members_from(FAMILY)
    assert [(m.dsid, m.given_name, m.organizer) for m in members] == [
        (ORGANIZER, "Dana", True), (CHILD, "Quill", False)]


def test_a_member_without_a_numeric_dsid_is_left_out():
    """A dsid goes into a request header, so it has to be the number it
    always is."""
    odd = {"members": [{"dsid": "abc", "givenName": "Nobody"}, None,
                       {"dsid": ORGANIZER, "givenName": "Dana", "isHeadOfHousehold": True}]}
    assert [m.dsid for m in site.members_from(odd)] == [ORGANIZER]
    assert site.members_from(None) == [] and site.members_from({"members": "x"}) == []


# -- what is kept ------------------------------------------------------------------

def test_only_purchases_where_money_was_spent_are_paid():
    assert site.is_paid(APPLE_ONE) and site.is_paid(CHILD_COINS) and site.is_paid(ICLOUD)
    assert site.is_paid(PAID_LINE_ONLY), "a paid line counts without an invoiceAmount"
    assert not site.is_paid(FREE_APP), "a free download has no receipt"
    assert not site.is_paid(ZERO_INVOICE), "a receipt for nothing is not money spent"


def test_a_pending_purchase_is_recognized():
    assert site.is_pending(PENDING)
    assert not site.is_pending(APPLE_ONE)


def test_the_counts_say_what_a_walk_found():
    members = site.members_from(FAMILY)
    got = site.purchase_counts([APPLE_ONE, FREE_APP, CHILD_COINS, PENDING, ICLOUD], members)
    assert got == {"purchases": 5, "paid": 3, "free": 1, "pending": 1, "paid_by_others": 1}


# -- a purchase ---------------------------------------------------------------------

def test_a_paid_purchase_becomes_one_record_keyed_by_its_weborder():
    purchase_, extras = site.app_store_purchase(APPLE_ONE, site.members_from(FAMILY),
                                                owner="Dana Example")
    assert purchase_.key == "App Store:MLF0TEST01"
    assert purchase_.purchase_type == "App Store"
    assert purchase_.total == "$21.43"
    assert purchase_.purchase_date == "2026-05-14"
    assert purchase_.summary == "Apple One" and purchase_.confidence == "High"
    assert [i.name for i in purchase_.items] == ["Premier (Apple One)"]
    assert purchase_.items[0].line_total == "$21.43"
    assert purchase_.items[0].fulfillment == "Apple One Subscription"
    assert extras["dsid"] == ORGANIZER
    assert extras["lines"][0] == {"name": "Premier", "detail": "Apple One",
                                  "media_type": "Apple One Subscription",
                                  "line_item_type": "FirstPartySubscriptionBundle",
                                  "amount_paid": "$21.43", "unit_price": "$21.43",
                                  "quantity": 1, "free": False}


def test_the_organizers_purchase_is_the_config_owners():
    members = site.members_from(FAMILY)
    _p, extras = site.app_store_purchase(APPLE_ONE, members, owner="Dana Example")
    assert extras["purchaser"] == "Dana Example"
    _p, extras = site.app_store_purchase(APPLE_ONE, members, owner="")
    assert extras["purchaser"] == "Dana", "with no owner set, the organizer's own name"


def test_a_childs_purchase_keeps_the_childs_name():
    """A child's in-game currency on Family Sharing says whose it was, and
    its receipt is asked for with the child's dsid, not the organizer's."""
    purchase_, extras = site.app_store_purchase(CHILD_COINS, site.members_from(FAMILY),
                                                owner="Dana Example")
    assert extras["purchaser"] == "Quill"
    assert extras["dsid"] == CHILD
    assert purchase_.notes == "Purchased by Quill"
    assert purchase_.summary == "Blockville"


def test_a_second_purchase_under_one_weborder_adds_its_lines():
    members = site.members_from(FAMILY)
    first = site.app_store_purchase(APPLE_ONE, members)
    again = dict(ICLOUD, weborder="MLF0TEST01")
    site.merge_purchase(first, site.app_store_purchase(again, members))
    purchase_, extras = first
    # The app's name is left off a line that already says it.
    assert [i.name for i in purchase_.items] == ["Premier (Apple One)",
                                                 "iCloud+ with 200 GB storage"]
    assert len(extras["lines"]) == 2
    assert purchase_.summary == "Apple One and iCloud+"


def test_a_purchase_without_a_usable_weborder_is_not_recorded():
    assert site.app_store_purchase(purchase(""), []) is None
    assert site.app_store_purchase(purchase("../evil"), []) is None


def test_an_evening_purchase_is_filed_on_the_local_day():
    """purchaseDate is written in UTC, so ten at night in Virginia reads as
    the next morning until it is moved."""
    eastern = timezone(timedelta(hours=-4))
    assert site.local_date("2026-06-28T02:30:00.074Z", tz=eastern) == "2026-06-27"
    assert site.local_date("2026-06-28T02:30:00Z", tz=timezone.utc) == "2026-06-28"
    assert site.local_date("2026-06-28T02:30:00-04:00", tz=eastern) == "2026-06-28"
    assert site.local_date("2026-06-28", tz=eastern) == "2026-06-28"
    for bad in ("", None, "yesterday", "2026-02-30T01:00:00Z"):
        assert site.local_date(bad) == "", bad


# -- what it is called ----------------------------------------------------------------

@pytest.mark.parametrize("line,named", [
    (dict(name="Premier", detail="Apple One", media_type="Apple One Subscription",
          line_item_type="FirstPartySubscriptionBundle"), "Apple One"),
    (dict(name="iCloud+ with 200 GB storage", detail="iCloud", media_type="iCloud+",
          line_item_type="BaseSubscription"), "iCloud+"),
    (dict(name="AppleCare+ for AirPods", detail="AppleCare", media_type="AppleCare Subscription",
          line_item_type="EvergreenSubscription"), "AppleCare"),
    (dict(name="Season Ticket", detail="Apple TV", media_type="Apple TV Subscription",
          line_item_type="BaseSubscription"), "Apple TV"),
    (dict(name="Blockville | 400 Bricks", detail="", media_type="",
          line_item_type="VideoPartnerBilling"), "Blockville"),
    (dict(name="Harbor Plus Annual", detail="Puzzle Harbor: Daily Logic",
          media_type="Subscription Renewal", line_item_type="BaseSubscription"), "Puzzle Harbor"),
    (dict(name="Gem Pack 3", detail="Crystal Quarry", media_type="In-App Purchase",
          line_item_type="BaseLineItem"), "Crystal Quarry"),
    (dict(name="Lantern Notes: Quick Ideas", detail="Example Dev LLC", media_type="iOS App",
          line_item_type="IOSApp"), "Lantern Notes"),
    (dict(name="Tide Tables – Coast Guide", detail="Example Dev LLC", media_type="App",
          line_item_type="MacApp"), "Tide Tables"),
])
def test_an_app_store_receipt_is_named_for_the_app_or_service(line, named):
    assert site.app_store_summary([line]) == (named, "High")


def test_two_things_bought_together_are_named_together():
    one = dict(name="Premier", detail="Apple One", media_type="Apple One Subscription")
    two = dict(name="Gem Pack 3", detail="Crystal Quarry", media_type="In-App Purchase")
    three = dict(name="Blockville | 80 Bricks", media_type="")
    assert site.app_store_summary([one, two]) == ("Apple One and Crystal Quarry", "High")
    assert site.app_store_summary([one, two, three]) == ("Apple One and 2 More", "High")
    assert site.app_store_summary([one, dict(one)]) == ("Apple One", "High")


def test_a_paid_line_names_the_purchase_before_a_free_one():
    free = dict(name="Lantern Notes", media_type="iOS App", line_item_type="IOSApp", free=True)
    paid = dict(name="Gem Pack 3", detail="Crystal Quarry", media_type="In-App Purchase", free=False)
    assert site.app_store_summary([free, paid])[0] == "Crystal Quarry and Lantern Notes"


def test_nothing_to_name_it_from_is_left_for_review():
    assert site.app_store_summary([]) == (site.FALLBACK_SUMMARY, "Low")


# -- asking Report a Problem, from inside the page --------------------------------------

class _Page:
    """A Report a Problem tab. Answers each API call from a list, in order,
    and writes down what it was asked."""

    def __init__(self, answers=(), url="https://reportaproblem.apple.com/"):
        self.url, self.answers, self.calls, self.waits = url, list(answers), [], []

    def evaluate(self, js, arg=None):
        if js == site._TOKEN_JS:
            return True
        assert js == site._API_JS, "only the page's own kind of call is made"
        path, method, body, dsid, version, key = arg
        self.calls.append({"path": path, "method": method, "body": body, "dsid": dsid,
                           "version": version, "key": key})
        return self.answers.pop(0)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def ok(data):
    return {"status": 200, "redirected": False, "failed": False, "data": data}


def batch(purchases, next_id=None):
    return ok({"batchId": None, "nextBatchId": next_id, "query": {}, "purchases": purchases})


def test_the_family_is_asked_for_the_way_the_page_asks():
    page = _Page([ok(FAMILY)])
    got = site.read_family(page)
    assert got["kind"] == site.ANSWERED and len(got["members"]) == 2
    assert page.calls == [{"path": "/api/family", "method": "GET", "body": None, "dsid": "",
                           "version": "3.0.0", "key": "x-apple-xsrf-token"}]


def test_the_batches_are_walked_with_every_members_dsid_until_the_end():
    page = _Page([batch([APPLE_ONE, FREE_APP], "BATCH-2"),
                  batch([CHILD_COINS, PENDING], "BATCH-3"),
                  batch([ICLOUD], None)])
    got = site.walk_purchases(page, [ORGANIZER, CHILD])
    assert got["stop"] == site.END and got["batches"] == 3
    assert [p["weborder"] for p in got["purchases"]] == [
        "MLF0TEST01", "R00TEST0000001", "MLF0TEST03", "MLF0TEST04", "MLF0TEST05"]
    assert [c["body"] for c in page.calls] == [
        {"dsids": [ORGANIZER, CHILD]},
        {"batchId": "BATCH-2", "dsids": [ORGANIZER, CHILD]},
        {"batchId": "BATCH-3", "dsids": [ORGANIZER, CHILD]}]
    assert all(c["method"] == "POST" and c["path"] == "/api/purchase/search" for c in page.calls)
    assert page.waits == [2000, 2000], "at least two seconds between searches"


def test_asking_for_less_of_a_pause_still_waits_two_seconds():
    page = _Page([batch([APPLE_ONE], "BATCH-2"), batch([ICLOUD], None)])
    site.walk_purchases(page, [ORGANIZER], pause_ms=10)
    assert page.waits == [2000]


def test_a_403_stops_the_walk_keeps_what_was_read_and_is_never_asked_again():
    page = _Page([batch([APPLE_ONE], "BATCH-2"),
                  {"status": 403, "redirected": False, "failed": False, "data": None},
                  batch([ICLOUD], None)])
    got = site.walk_purchases(page, [ORGANIZER, CHILD])
    assert got["stop"] == site.SIGNED_OUT and got["status"] == 403
    assert [p["weborder"] for p in got["purchases"]] == ["MLF0TEST01"]
    assert len(page.calls) == 2, "a refused search is not retried"


@pytest.mark.parametrize("answer,stop", [
    ({"status": 0, "redirected": True, "failed": False, "data": None}, site.SIGNED_OUT),
    ({"status": 400, "redirected": False, "failed": False, "data": None}, site.SIGNED_OUT),
    ({"status": 401, "redirected": False, "failed": False, "data": None}, site.SIGNED_OUT),
    ({"status": 500, "redirected": False, "failed": False, "data": None}, site.REFUSED),
    ({"status": 0, "redirected": False, "failed": True, "data": None}, site.FAILED),
])
def test_every_answer_that_is_not_a_200_stops_the_walk(answer, stop):
    page = _Page([answer, batch([ICLOUD], None)])
    got = site.walk_purchases(page, [ORGANIZER])
    assert got["stop"] == stop and got["purchases"] == [] and len(page.calls) == 1


def test_the_walk_stops_once_a_whole_batch_is_older_than_the_limit():
    old = [purchase("MLF0OLD%03d" % n, date="2024-03-0%dT12:00:00Z" % (n + 1)) for n in range(3)]
    page = _Page([batch([APPLE_ONE], "BATCH-2"), batch(old, "BATCH-3"), batch([ICLOUD], None)])
    got = site.walk_purchases(page, [ORGANIZER], limit_date="2025-01-01")
    assert got["stop"] == site.DATE_LIMIT and got["batches"] == 2


def test_a_cursor_seen_twice_is_the_end_rather_than_a_loop():
    page = _Page([batch([APPLE_ONE], "BATCH-2"), batch([ICLOUD], "BATCH-2"),
                  batch([CHILD_COINS], None)])
    got = site.walk_purchases(page, [ORGANIZER])
    assert got["stop"] == site.END and got["batches"] == 2


def test_the_batch_cap_ends_a_cursor_that_never_does():
    page = _Page([batch([APPLE_ONE], "BATCH-%d" % n) for n in range(10)])
    got = site.walk_purchases(page, [ORGANIZER], max_batches=4)
    assert got["stop"] == site.BATCH_CAP and got["batches"] == 4


@pytest.mark.parametrize("path", [
    "/api/problem", "/api/concern", "/api/trustAndSafety",
    "/api/purchase/applicableConcerns", "/api/refund", "/api/report",
    "/api/order/MLF0TEST01/refund", "/api/purchase/search/../problem",
    "https://reportaproblem.apple.com/api/family", "/api/log",
])
def test_nothing_but_the_three_endpoints_is_ever_called(path):
    page = _Page([ok({})])
    with pytest.raises(ValueError):
        site.api_call(page, path)
    assert page.calls == []


def test_a_call_is_never_made_from_a_tab_somewhere_else():
    """The path is relative, so it would go wherever the tab happens to be."""
    page = _Page([ok(FAMILY)], url="https://evil.test/")
    got = site.read_family(page)
    assert got["kind"] == site.FAILED and page.calls == []


def test_the_receipt_is_asked_for_with_the_purchasers_dsid():
    receipt = ("<html><body><script>alert(1)</script><p>Receipt</p>"
               "<p>Order ID: MLF0TEST03</p></body></html>")
    page = _Page([ok({"email": "quill@example.com", "invoice": receipt,
                      "refund": None, "vat": None})])
    got = site.fetch_invoice(page, "MLF0TEST03", CHILD)
    assert got["kind"] == site.ANSWERED
    assert page.calls[0]["path"] == "/api/order/MLF0TEST03/invoice.html"
    assert page.calls[0]["dsid"] == CHILD and page.calls[0]["method"] == "GET"
    assert "Order ID: MLF0TEST03" in got["html"]
    assert "<script" not in got["html"], "nothing runs in the tab it is drawn in"


def test_a_receipt_answer_that_says_sign_in_is_not_a_receipt():
    page = _Page([{"status": 401, "redirected": False, "failed": False, "data": None}])
    got = site.fetch_invoice(page, "MLF0TEST03", CHILD)
    assert got == {"kind": site.SIGNED_OUT, "status": 401, "html": ""}


def test_a_receipt_is_not_asked_for_without_a_proper_order_and_dsid():
    page = _Page([ok({})])
    assert site.fetch_invoice(page, "MLF0/../x", CHILD)["kind"] == site.REFUSED
    assert site.fetch_invoice(page, "MLF0TEST03", "")["kind"] == site.REFUSED
    assert page.calls == []


def test_an_answer_with_no_receipt_in_it_gives_no_html():
    assert site.invoice_html_from({"invoice": None}) == ""
    assert site.invoice_html_from({"invoice": "plain text"}) == ""
    assert site.invoice_html_from("not a dict") == ""
