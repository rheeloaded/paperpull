"""The census for the eleven apps that drive an API rather than a page.

They declare no selectors, so the selector census has nothing to say
about them and their failure file carried a page state and little else.
This is their half, and the questions it has to answer are the same
ones. Did the call happen. What came back. Is an empty answer an empty
account or a filter that excluded everything.

It also has to be as safe as everything else, and its risk is different.
The shape of an answer is the most useful thing in it and the only part
derived from the provider rather than from our own source, so the
canary at the end puts a fake secret in every position a JSON body has.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import api_census as A


class FakeRequest:
    def __init__(self, method="GET"):
        self.method = method


class FakeResponse:
    def __init__(self, url, status=200, ctype="application/json",
                 body=None, method="GET", length=None, raises=False):
        self.url = url
        self.status = status
        self.headers = {"content-type": ctype}
        if length is not None:
            self.headers["content-length"] = str(length)
        self.request = FakeRequest(method)
        self._body = body
        self._raises = raises

    def json(self):
        if self._raises:
            raise RuntimeError("not json after all")
        return self._body


class FakePage:
    def __init__(self):
        self.handlers = {}
        self.removed = []

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.removed.append(event)

    def emit(self, response):
        for h in self.handlers.get("response", []):
            h(response)


def bank(url):
    return url.startswith("https://api.bank.example/")


def seen(*responses, **kw):
    page = FakePage()
    r = A.Requests(page, bank, **kw)
    r.start()
    for response in responses:
        page.emit(response)
    return r


# -- the path, which is structure and an account number in one breath ---------

def test_an_account_number_in_a_path_is_masked():
    assert A.path_shape(
        "https://api.bank.example/v1/accounts/12345678/documents"
    ) == "/v1/accounts/#/documents"


def test_a_uuid_and_a_hash_in_a_path_are_masked():
    assert A.path_shape("https://x/app/4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf/o") \
        == "/app/#/o"
    assert A.path_shape("https://x/d/9f86d081884c7d659a2feaa0c55ad015") == "/d/#"


def test_the_structure_itself_survives():
    """The half worth having. An endpoint that moved from /v1 to /v2 is
    the answer to a whole round."""
    assert A.path_shape("https://x/ebusiness/order/v1/orders/graphql") \
        == "/ebusiness/order/v1/orders/graphql"


def test_a_segment_long_enough_to_be_a_token_is_masked():
    assert A.path_shape("https://x/s/" + "a" * 80) == "/s/#"


# -- the query, names and never values ----------------------------------------

def test_the_names_of_the_parameters_come_out_and_the_values_do_not():
    keys = A.query_keys("https://x/y?year=2026&token=SECRETTOKEN123&page=2")
    assert keys == ["page", "token", "year"]


def test_a_parameter_named_after_an_account_is_masked_too():
    assert "#" in A.query_keys("https://x/y?88213344=1")


def test_a_url_with_no_query_says_nothing():
    assert A.query_keys("https://x/y") == []


# -- the shape, the point and the risk ----------------------------------------

def test_a_body_becomes_its_keys_and_the_types_of_its_values():
    shape = A.shape_of({"documents": [{"id": "D1", "date": "2026-01-02",
                                       "amount": 12.5, "ok": True}],
                        "total": 1, "next": None})
    assert shape == {"documents": ["1 item(s)", {"id": "string",
                                                 "date": "string",
                                                 "amount": "number",
                                                 "ok": "bool"}],
                     "total": "number", "next": "null"}


def test_an_object_keyed_by_an_account_number_has_its_keys_masked():
    """The case where the keys are the values. It exists."""
    assert A.shape_of({"88213344": {"balance": 1.0}}) == {"#": {"balance": "number"}}


def test_a_long_list_reports_its_length_and_one_shape():
    shape = A.shape_of({"docs": [{"id": "a"}] * 250})
    assert shape["docs"][0] == "250 item(s)"
    assert shape["docs"][1] == {"id": "string"}


def test_an_empty_list_is_told_apart_from_a_full_one():
    assert A.shape_of({"docs": []})["docs"] == ["0 item(s)", None]


def test_a_body_nested_beyond_reason_stops():
    deep = {"a": 1}
    for _ in range(40):
        deep = {"x": deep}
    assert "..." in json.dumps(A.shape_of(deep))


def test_a_body_with_hundreds_of_keys_is_cut_and_says_so():
    shape = A.shape_of({"k%d" % i: i for i in range(100)})
    assert len(shape) == A.MAX_KEYS + 1
    assert "70 more key(s)" in shape["..."]


# -- what gets recorded --------------------------------------------------------

def test_a_provider_call_is_described():
    r = seen(FakeResponse("https://api.bank.example/v1/docs?year=2026",
                          body={"docs": [{"id": "a"}]}, method="POST"))
    e = r.seen[0]
    assert e["path"] == "/v1/docs"
    assert e["method"] == "post"
    assert e["status"] == 200
    assert e["kind"] == "json"
    assert e["query_keys"] == ["year"]
    assert e["shape"] == {"docs": ["1 item(s)", {"id": "string"}]}


def test_a_call_somewhere_else_is_counted_and_never_described():
    """An advertiser's address on a bank's page is still a record of
    what somebody was doing."""
    r = seen(FakeResponse("https://ads.example/pixel?u=SECRET", body={"x": 1}))
    assert r.seen == []
    assert r.counts["elsewhere"] == 1
    assert "SECRET" not in json.dumps(r.report())


def test_a_body_too_large_is_not_read():
    """Reading one is a round trip, and a year of transactions has the
    same shape as a month of them."""
    r = seen(FakeResponse("https://api.bank.example/v1/tx", body={"a": 1},
                          length=9_000_000))
    assert "not read" in r.seen[0]["shape"]
    assert r.counts["too_large"] == 1
    assert r.counts["bodies_read"] == 0


def test_a_body_that_will_not_parse_is_recorded_as_such():
    r = seen(FakeResponse("https://api.bank.example/v1/x", raises=True))
    assert r.seen[0]["shape"] == "unreadable"
    assert r.counts["unreadable"] == 1


def test_a_pdf_is_noted_and_never_opened():
    r = seen(FakeResponse("https://api.bank.example/d/1.pdf",
                          ctype="application/pdf"))
    assert r.seen[0]["kind"] == "pdf"
    assert "shape" not in r.seen[0]


def test_only_the_most_recent_are_kept():
    r = seen(*[FakeResponse("https://api.bank.example/v1/p%d" % i)
               for i in range(60)], limit=5)
    assert len(r.seen) == 5
    assert r.seen[-1]["path"] == "/v1/p59"
    assert r.counts["provider"] == 60


def test_bodies_read_is_capped_however_many_arrive():
    r = seen(*[FakeResponse("https://api.bank.example/v1/p%d" % i,
                            body={"a": i}) for i in range(80)])
    assert r.counts["bodies_read"] <= A.MAX_BODIES


# -- what it tells the reader --------------------------------------------------

def test_a_failing_status_is_read_for_what_it_means():
    r = seen(FakeResponse("https://api.bank.example/v1/docs", status=401))
    said = " ".join(A.summarize(r.report()))
    assert "answered 401" in said
    assert "session is probably over" in said


def test_a_404_and_a_429_say_different_things():
    a = " ".join(A.summarize(seen(
        FakeResponse("https://api.bank.example/v1/x", status=404)).report()))
    b = " ".join(A.summarize(seen(
        FakeResponse("https://api.bank.example/v1/x", status=429)).report()))
    assert "has moved" in a
    assert "slow the run down" in b


def test_an_empty_answer_is_named_as_the_two_things_it_could_be():
    """The question a maintainer cannot answer from outside, and the one
    that costs a round every time."""
    r = seen(FakeResponse("https://api.bank.example/v1/docs",
                          body={"data": {"documents": []}}))
    said = " ".join(A.summarize(r.report()))
    assert "empty list" in said
    assert "account with nothing in it or a filter" in said


def test_a_full_answer_is_not_called_empty():
    r = seen(FakeResponse("https://api.bank.example/v1/docs",
                          body={"data": {"documents": [{"id": "a"}]}}))
    assert not any("empty list" in s for s in A.summarize(r.report()))


def test_no_provider_call_at_all_is_the_first_thing_said():
    r = seen(FakeResponse("https://ads.example/x"))
    said = " ".join(A.summarize(r.report()))
    assert "not one of them went to the provider" in said


def test_a_page_that_made_no_requests_says_so():
    said = " ".join(A.summarize(seen().report()))
    assert "no requests at all" in said


def test_an_api_that_stopped_answering_json_is_called_out():
    r = seen(FakeResponse("https://api.bank.example/v1/docs", ctype="text/html"))
    said = " ".join(A.summarize(r.report()))
    assert "may have moved" in said


def test_summarizing_something_that_is_not_a_report_is_empty():
    assert A.summarize(None) == []
    assert A.summarize({}) == []


# -- it may never make a working run fail -------------------------------------

def test_a_response_that_raises_on_everything_does_not_escape():
    class Hostile:
        @property
        def url(self):
            raise RuntimeError("gone")

    page = FakePage()
    r = A.Requests(page, bank)
    r.start()
    page.emit(Hostile())          # must not raise out of the listener
    assert r.counts["unreadable"] == 1


def test_a_page_that_will_not_take_a_listener_does_not_raise():
    class Hostile:
        def on(self, *a, **k):
            raise RuntimeError("no")

    r = A.Requests(Hostile(), bank)
    r.start()
    assert r.report()["seen"] == []


def test_starting_twice_listens_once():
    page = FakePage()
    r = A.Requests(page, bank)
    r.start()
    r.start()
    page.emit(FakeResponse("https://api.bank.example/v1/x"))
    assert len(r.seen) == 1


def test_stopping_removes_the_listener():
    page = FakePage()
    r = A.Requests(page, bank)
    r.start()
    r.stop()
    assert page.removed == ["response"]


def test_a_missing_safety_check_defaults_to_describing_nothing_off_host():
    """With no is_safe_url everything counts as the provider's, which is
    what a test harness wants and what an app never does."""
    page = FakePage()
    r = A.Requests(page)
    r.start()
    page.emit(FakeResponse("https://anywhere.example/x"))
    assert r.counts["provider"] == 1


# -- the canary, for the one part derived from the provider -------------------

CANARY_BODY = {
    "CANARYKEY": "CANARYVALUE",
    "member": {"name": "CANARYNAME", "address": "CANARYSTREET",
               "card": "CANARYCARD"},
    "documents": [{"id": "CANARYDOCID", "url": "https://x/CANARYPATH",
                   "amount": 1234.56}],
    "88213344": {"balance": 99.99},
}


def test_no_value_from_a_body_comes_out():
    r = seen(FakeResponse(
        "https://api.bank.example/v1/accounts/88213344/docs"
        "?token=CANARYTOKEN&year=2026", body=CANARY_BODY))
    body = json.dumps(r.report())
    for canary in ("CANARYVALUE", "CANARYNAME", "CANARYSTREET", "CANARYCARD",
                   "CANARYDOCID", "CANARYPATH", "CANARYTOKEN",
                   "1234.56", "99.99", "88213344"):
        assert canary not in body, canary


def test_the_key_names_do_come_out_because_that_is_the_point():
    """An API that renamed documents to items looks from outside exactly
    like an account with nothing in it."""
    r = seen(FakeResponse("https://api.bank.example/v1/docs", body=CANARY_BODY))
    body = json.dumps(r.report())
    for kept in ("CANARYKEY", "member", "documents", "amount", "balance"):
        assert kept in body, kept
