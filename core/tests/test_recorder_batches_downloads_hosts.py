"""Three facts a recording lost, kept now through the word list.

A batch of GraphQL calls, one JSON array, kept no keys and no operation
names, and its answers only the first (Scalable Capital, #170). A download
from a tab that closes blank left no trace of where the PDF came from
(Consorsbank, #178). And a provider whose API sits on a host the app does
not list yet had every call of that API dropped, the list, the messages and
the PDFs (BBVA).

Every value here is invented. Each fact is built from the word list when it
is made, and nothing is gathered and cleaned afterwards.
"""
import json
import time
from urllib.parse import urlsplit

import pytest

import paperpull_core.recorder as recorder
from paperpull_core.recorder import Recorder
from paperpull_core.redact import set_private_words
from paperpull_core.words import shape, shape_tree, shape_url

MERCHANT = "QZ4XKRWPT7MVN"
LETTERS = "QZXKRWPTKMVNB"
SURNAME = "Zorvexquill"
SMALLINT = 73517
CANARIES = (MERCHANT, LETTERS, SURNAME, str(SMALLINT))

PROVIDER = "https://bank.example/accounts"
API = "https://api.bankcdn.test/v1/docs?acct=%s" % MERCHANT
VENDOR = "https://widget.vendor.test/embed"


def safe(url):
    try:
        p = urlsplit(url or "")
        return p.scheme == "https" and p.hostname == "bank.example"
    except ValueError:
        return False


class FakeFrame:
    def __init__(self, url="", boom=False):
        self._url, self._boom = url, boom

    @property
    def url(self):
        if self._boom:
            raise RuntimeError(MERCHANT)
        return self._url


class _Raises:
    def __get__(self, obj, owner=None):
        raise RuntimeError(SURNAME)


class FakeRequest:
    def __init__(self, method="POST", post=None, kind="xhr", frame=None):
        self.method = method
        self.post_data = post
        self.resource_type = kind
        self.frame = frame


class RaisingPost(FakeRequest):
    post_data = _Raises()

    def __init__(self, **kw):
        kw.pop("post", None)
        FakeRequest.__init__(self, **kw)
        del self.__dict__["post_data"]


class RaisingFrame(FakeRequest):
    frame = _Raises()

    def __init__(self, **kw):
        FakeRequest.__init__(self, **kw)
        del self.__dict__["frame"]


class FakeResponse:
    def __init__(self, url, body=None, ctype="application/json", request=None, size=None):
        self.url = url
        self.headers = {"content-type": ctype}
        if size is not None:
            self.headers["content-length"] = str(size)
        self.status = 200
        self._body = body
        self.request = request or FakeRequest(frame=FakeFrame(PROVIDER))
        self.json_called = False

    def json(self):
        self.json_called = True
        return self._body


class FakeDownload:
    def __init__(self, url, name="statement.pdf"):
        self.suggested_filename = name
        self.url = url


class RaisingDownload:
    suggested_filename = "statement.pdf"
    url = _Raises()


class FakePage:
    def __init__(self, url=PROVIDER):
        self.url = url
        self.handlers = {}
        self.bindings = {}
        self.main_frame = FakeFrame(url)
        self.context = self

    def locator(self, sel):
        return type("L", (), {"count": lambda self: 0})()

    def expose_binding(self, name, fn):
        self.bindings[name] = fn

    def add_init_script(self, script):
        pass

    def evaluate(self, script, arg=None):
        return "installed"

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        pass

    def fire(self, record):
        self.bindings["__ppRecorderPost"](None, record)

    def emit(self, event, *args):
        for h in self.handlers.get(event, []):
            h(*args)


@pytest.fixture(autouse=True)
def _no_owner():
    set_private_words([])
    yield
    set_private_words([])


def recording(**kw):
    page = FakePage()
    rec = Recorder(page, is_safe_url=safe, provider="Bank", **kw)
    rec.start()
    page.fire({"action": "click", "label": "Statements", "at": 1,
               "locator": {"how": "role", "role": "link", "name": "Statements"}})
    return rec, page


def assert_none_came_out(report):
    text = json.dumps(report).lower()
    for canary in CANARIES:
        assert canary.lower() not in text, "%s came out" % canary


BODY2 = [
    {"operationName": "documentList",
     "query": "query documentList($p: ID!) { %s(p: $p) { id } }" % LETTERS,
     "variables": {"portfolioId": MERCHANT, "owner": {"name": SURNAME}, "n": SMALLINT}},
    {"operationName": SURNAME, "query": "{ x }", "variables": {}},
]


def graphql(body, answer=None, request=None):
    return FakeResponse("https://bank.example/graphql", body=answer if answer is not None
                        else {"data": {}},
                        request=request or FakeRequest(post=json.dumps(body),
                                                       frame=FakeFrame(PROVIDER)))


# -- A. a batch of calls -------------------------------------------------------

def test_a_batch_keeps_each_calls_keys_and_operation_and_never_a_value():
    rec, page = recording()
    page.emit("response", graphql(BODY2))
    entry = rec.requests[0]
    assert entry["batch"] == 2
    assert entry["post_items"] == [
        {"keys": ["operationName", "query", "variables"],
         "operation": shape("documentList", rec.words)},
        {"keys": ["operationName", "query", "variables"], "operation": "aaaaaaaaaaa"}]
    assert "post_keys" not in entry
    report = rec.stop()
    assert_none_came_out(report)
    text = json.dumps(report)
    assert "portfolioId" not in text and "$p" not in text and "{ id }" not in text


def test_a_batchs_answer_is_shaped_call_by_call():
    rec, page = recording()
    page.emit("response", graphql(BODY2, [
        {"data": {"documents": [{"id": MERCHANT}]}},
        {"errors": [{"message": SURNAME}]}]))
    report = rec.stop()
    got = report["requests"][0]["shape"]
    assert got[0] == "batch of 2" and len(got) == 3
    assert "data" in got[1] and "errors" in got[2]
    assert_none_came_out(report)


def test_a_batch_and_its_answer_are_described_only_so_far():
    rec, page = recording()
    body = [{"operationName": "op%d" % i, "query": "{x}"} for i in range(12)]
    page.emit("response", graphql(body, [{"a": i} for i in range(15)]))
    entry = rec.requests[0]
    assert entry["batch"] == 12 and len(entry["post_items"]) == 10
    assert entry["shape"][0] == "batch of 15" and len(entry["shape"]) == 11


def test_a_hostile_batch_of_many_calls_costs_a_bounded_entry():
    rec, page = recording()
    body = "[" + ",".join(['{"a":1}'] * 200000) + "]"
    started = time.monotonic()
    page.emit("response", graphql(None, [], FakeRequest(post=body, frame=FakeFrame(PROVIDER))))
    assert time.monotonic() - started < 5
    entry = rec.requests[0]
    assert entry["batch"] == 200000 and len(entry["post_items"]) == 10
    assert len(json.dumps(entry, default=str)) < 5000


def test_a_call_that_is_not_an_object_is_named_by_its_kind():
    rec, page = recording()
    body = [[{"operationName": MERCHANT}], SURNAME, SMALLINT, None, True, 1.5, {"k": 1}]
    page.emit("response", graphql(body))
    items = rec.requests[0]["post_items"]
    assert [i.get("kind") for i in items[:6]] == ["list", "str", "int", "NoneType", "bool", "float"]
    assert items[6] == {"keys": ["k"]}
    assert_none_came_out(rec.stop())


@pytest.mark.parametrize("name", [{MERCHANT: 1}, SMALLINT, [SURNAME], None, True])
def test_an_operation_name_that_is_not_text_is_left_out(name):
    rec, page = recording()
    page.emit("response", graphql([{"operationName": name}]))
    assert rec.requests[0]["post_items"] == [{"keys": ["operationName"]}]
    assert_none_came_out(rec.stop())


def test_an_operation_name_and_keys_are_shaped_and_cut():
    rec, page = recording()
    item = {"operationName": "x" * 500 + MERCHANT, LETTERS: 1}
    item.update({"k%02d" % i: i for i in range(40)})
    page.emit("response", graphql([item]))
    one = rec.requests[0]["post_items"][0]
    assert len(one["keys"]) == 30 and all(len(k) <= 40 for k in one["keys"])
    assert len(one["operation"]) <= 60
    assert_none_came_out(rec.stop())


@pytest.mark.parametrize("body", ['[{"operationName": "%s",' % MERCHANT, "[" + SURNAME, "[1,]",
                                  "[" * 100000 + "]" * 100000],
                         ids=["cut", "word", "comma", "deep"])
def test_a_body_that_will_not_parse_costs_only_its_names(body):
    rec, page = recording()
    page.emit("response", graphql(None, {"a": 1},
                                  FakeRequest(post=body, frame=FakeFrame(PROVIDER))))
    entry = rec.requests[0]
    assert entry["method"] == "POST" and entry["shape"] == {"a": "int"}
    assert not {"batch", "post_items", "post_keys"} & set(entry)
    assert "unreadable_response" not in rec.dropped
    assert rec.steps[0]["effect"]["requests"] == 1
    assert_none_came_out(rec.stop())


def test_a_body_over_the_limit_is_not_read(monkeypatch):
    monkeypatch.setattr(recorder, "_MAX_BODY_BYTES", 1000)
    rec, page = recording()
    page.emit("response", graphql([{"operationName": "op", "pad": "x" * 100}] * 50))
    entry = rec.requests[0]
    assert "batch" not in entry and "post_items" not in entry and entry["shape"] == {"data": {}}


def test_a_body_that_cannot_be_read_keeps_the_answer_as_a_list():
    rec, page = recording()
    page.emit("response", graphql(None, [{"a": 1}, {"a": 2}],
                                  RaisingPost(frame=FakeFrame(PROVIDER))))
    entry = rec.requests[0]
    assert "batch" not in entry and entry["method"] == "POST"
    assert entry["shape"] == ["list of 2", {"a": "int"}]
    assert "unreadable_response" not in rec.dropped


def test_an_empty_batch():
    rec, page = recording()
    page.emit("response", graphql([], []))
    entry = rec.requests[0]
    assert entry["batch"] == 0 and entry["post_items"] == [] and entry["shape"] == ["batch of 0"]


def test_one_object_keeps_its_keys_as_before_and_gains_its_operation():
    rec, page = recording()
    page.emit("response", graphql({"operationName": SURNAME, "query": "{ %s }" % LETTERS,
                                   "variables": {"id": MERCHANT}}, [{"a": 1}, {"a": 2}]))
    entry = rec.requests[0]
    assert entry["post_keys"] == ["operationName", "query", "variables"]
    assert entry["operation"] == "aaaaaaaaaaa"
    assert "batch" not in entry and entry["shape"] == ["list of 2", {"a": "int"}]
    assert_none_came_out(rec.stop())


def test_an_ordinary_request_gains_no_field():
    rec, page = recording()
    page.emit("response", FakeResponse(
        "https://bank.example/api/docs?type=STATEMENT", body={"documents": []},
        request=FakeRequest(post=json.dumps({"year": 2031}), frame=FakeFrame(PROVIDER))))
    assert set(rec.requests[0]) == {"step", "url", "status", "type", "query", "method",
                                    "post_keys", "shape"}


def test_opted_in_html_never_reads_a_batch_body():
    rec, page = recording(include_html=True)
    seen = []

    class Watched(FakeRequest):
        @property
        def post_data(self):
            seen.append(1)
            return json.dumps(BODY2)

        @post_data.setter
        def post_data(self, value):
            pass

    req = Watched(kind="document", frame=FakeFrame(PROVIDER))
    page.emit("response", FakeResponse("https://bank.example/docs", ctype="text/html",
                                       request=req))
    assert seen == []
    assert not {"batch", "post_items", "operation"} & set(rec.requests[0])


# -- B. where a download came from ----------------------------------------------

def effect_of(url):
    rec, page = recording()
    page.emit("download", FakeDownload(url))
    report = rec.stop()
    return report["steps"][0]["effect"], report, rec


def test_a_download_from_the_provider_keeps_its_address_and_parameter_names_only():
    eff, report, _ = effect_of(
        "https://bank.example/dl/%s/stmt.pdf?token=%s&acct=%s&%s=1#%s"
        % (LETTERS, MERCHANT, SURNAME, LETTERS, SURNAME))
    assert eff["download"] is True and eff["download_name"] == "statement.pdf"
    assert eff["download_from"].startswith("https://bank.example/dl/")
    assert "?" not in eff["download_from"] and "token=" not in eff["download_from"]
    assert eff["download_query_keys"] == sorted(["acct", "token", "aaaaaaaaaaaaa"])
    assert eff["download_off_host"] is False
    assert_none_came_out(report)


def test_a_download_from_another_host_says_so():
    url = "https://files.vendor.test/%s.pdf" % MERCHANT
    eff, report, rec = effect_of(url)
    assert eff["download_off_host"] is True
    assert eff["download_from"] == shape_url(url, rec.words, query=False)
    assert_none_came_out(report)


def test_a_user_and_password_before_the_host_never_leave():
    eff, report, _ = effect_of("https://%s:%s@bank.example/dl/statement.pdf" % (SURNAME, MERCHANT))
    assert eff["download_from"] == "https://bank.example/dl/statement.pdf"
    assert_none_came_out(report)


def test_a_host_hidden_behind_a_user_name_is_judged_by_the_real_host():
    eff, _, _ = effect_of("https://bank.example@evil.test/dl/x.pdf")
    assert eff["download_off_host"] is True
    assert "bank.example" not in eff["download_from"]


def test_an_id_written_in_percent_codes_is_shaped():
    eff, report, _ = effect_of("https://bank.example/dl/%s/x.pdf"
                               % "".join("%%%02X" % ord(c) for c in LETTERS))
    assert "%51%5A" not in json.dumps(report)
    assert_none_came_out(report)


def test_a_data_address_keeps_only_its_media_type():
    import base64
    url = ("data:application/pdf;base64,JVBERi0" + base64.b64encode(MERCHANT.encode()).decode()
           + "A" * 8_000_000)
    started = time.monotonic()
    eff, report, _ = effect_of(url)
    assert time.monotonic() - started < 5
    assert eff["download_from"] == "data:application/pdf"
    assert "download_query_keys" not in eff and "download_off_host" not in eff
    assert "JVBER" not in json.dumps(report)


@pytest.mark.parametrize("url,want", [
    ("data:,%s" % SURNAME, "data:"),
    ("data:text/plain;charset=utf-8;base64,QUJD", "data:text/plain")])
def test_odd_data_addresses(url, want):
    eff, report, _ = effect_of(url)
    assert eff["download_from"] == want
    assert_none_came_out(report)


def test_a_data_address_with_an_invented_type_is_shaped():
    eff, report, _ = effect_of("data:application/x-%s;base64,AA" % MERCHANT)
    assert eff["download_from"].startswith("data:application/")
    assert_none_came_out(report)


def test_a_blob_of_the_providers_page():
    eff, report, _ = effect_of("blob:https://bank.example/%s-4b2a-9c1d-%s00" % (LETTERS, SURNAME))
    assert eff["download_from"].startswith("blob:https://bank.example/")
    assert eff["download_off_host"] is False
    assert_none_came_out(report)


@pytest.mark.parametrize("url", ["blob:https://widget.vendor.test/1f2e3d", "blob:null/1f2e3d"])
def test_a_blob_of_another_origin_is_off_the_site(url):
    eff, _, _ = effect_of(url)
    assert eff["download_off_host"] is True


@pytest.mark.parametrize("download", [RaisingDownload(), FakeDownload(None), FakeDownload(""),
                                      type("D", (), {"suggested_filename": "statement.pdf"})()])
def test_a_download_whose_address_cannot_be_read_still_records_itself(download):
    rec, page = recording()
    page.emit("download", download)
    report = rec.stop()
    eff = report["steps"][0]["effect"]
    assert eff["download"] is True and eff["download_name"] == "statement.pdf"
    assert not {"download_from", "download_query_keys", "download_off_host"} & set(eff)
    assert_none_came_out(report)


@pytest.mark.parametrize("url", ["file:///C:/Users/%s/%s.pdf" % (SURNAME, MERCHANT),
                                 "javascript:alert('%s')" % SURNAME,
                                 "chrome-extension://%s/x.pdf" % LETTERS])
def test_other_schemes_are_shaped_and_off_the_site(url):
    eff, report, _ = effect_of(url)
    assert eff["download_off_host"] is True
    assert_none_came_out(report)


def test_a_check_that_fails_never_reads_as_on_the_site():
    def shaky(url):
        if "/dl/" in (url or ""):
            raise RuntimeError("no")
        return safe(url)
    page = FakePage()
    rec = Recorder(page, is_safe_url=shaky, provider="Bank")
    rec.start()
    page.fire({"action": "click", "label": "Statements", "at": 1,
               "locator": {"how": "role", "role": "link", "name": "Statements"}})
    page.emit("download", FakeDownload("https://bank.example/dl/statement.pdf"))
    eff = rec.stop()["steps"][0]["effect"]
    assert eff["download_from"] == "https://bank.example/dl/statement.pdf"
    assert eff["download_off_host"] is True


# -- C. an API on a host the app does not list -------------------------------------

def api(kind="xhr", frame=None, ctype="application/json", url=API, body=None, post=None,
        request=None):
    return FakeResponse(url, body=body if body is not None else {"documents": [{"id": SURNAME}]},
                        ctype=ctype, request=request or FakeRequest(
                            post=post, kind=kind,
                            frame=frame if frame is not None else FakeFrame(PROVIDER)))


def test_a_call_the_providers_page_makes_to_its_own_api_host_is_kept_and_marked():
    rec, page = recording()
    page.emit("response", api())
    assert len(rec.requests) == 1
    entry = rec.requests[0]
    assert entry["on_the_providers_own_site"] is False
    assert entry["url"] == shape_url(API, rec.words, query=False)[:200]
    assert entry["type"] == "json" and "documents" in entry["shape"]
    assert rec.dropped["off_host_request"] == 0
    assert rec.steps[0]["effect"]["requests"] == 1
    assert_none_came_out(rec.stop())


def test_a_fetch_and_a_pdf_are_kept_too():
    rec, page = recording()
    page.emit("response", api(kind="fetch"))
    page.emit("response", api(ctype="application/pdf"))
    assert [r["type"] for r in rec.requests] == ["json", "pdf"]
    assert all(r["on_the_providers_own_site"] is False for r in rec.requests)


def test_the_providers_own_answers_are_not_marked():
    rec, page = recording()
    page.emit("response", api(url="https://bank.example/api/docs"))
    assert "on_the_providers_own_site" not in rec.requests[0]


@pytest.mark.parametrize("frame", [FakeFrame(VENDOR),
                                   FakeFrame("https://bank.example@widget.vendor.test/"),
                                   FakeFrame(boom=True), FakeFrame("")])
def test_a_call_from_any_other_frame_is_counted_not_described(frame):
    rec, page = recording()
    page.emit("response", api(frame=frame))
    assert rec.requests == [] and rec.dropped["off_host_request"] == 1
    assert "unreadable_response" not in rec.dropped
    assert_none_came_out(rec.stop())


def test_a_call_with_no_frame_or_a_service_workers_is_counted():
    rec, page = recording()
    req = FakeRequest(kind="fetch")
    req.frame = None
    page.emit("response", api(request=req))
    page.emit("response", api(request=RaisingFrame(kind="fetch")))
    assert rec.requests == [] and rec.dropped["off_host_request"] == 2


@pytest.mark.parametrize("kind", ["document", "script", "image", "other", "eventsource",
                                  "websocket", None])
def test_a_navigation_or_anything_but_a_scripts_call_is_counted(kind):
    rec, page = recording()
    page.emit("response", api(kind=kind))
    assert rec.requests == [] and rec.dropped["off_host_request"] == 1


@pytest.mark.parametrize("ctype", ["text/plain", "image/png", "text/javascript", "text/html"])
def test_another_hosts_answer_that_is_not_json_or_pdf_is_counted(ctype):
    rec, page = recording(include_html=True)
    page.emit("response", api(ctype=ctype))
    assert rec.requests == [] and rec.dropped["off_host_request"] == 1


def test_another_hosts_answers_take_at_most_half_the_budget(monkeypatch):
    monkeypatch.setattr(recorder, "_MAX_REQUESTS", 6)
    rec, page = recording()
    for _ in range(5):
        page.emit("response", api())
    for _ in range(4):
        page.emit("response", api(url="https://bank.example/api/docs"))
    off = [r for r in rec.requests if r.get("on_the_providers_own_site") is False]
    assert len(off) == 3 and rec.dropped["off_host_request"] == 2
    assert len(rec.requests) == 6 and rec.dropped["request_limit"] == 1


def test_a_flood_of_another_hosts_answers_leaves_room_for_the_providers():
    rec, page = recording()
    for _ in range(400):
        page.emit("response", api())
    page.emit("response", api(url="https://bank.example/api/docs"))
    off = [r for r in rec.requests if r.get("on_the_providers_own_site") is False]
    assert len(off) == 150 and rec.dropped["off_host_request"] == 250
    assert "on_the_providers_own_site" not in rec.requests[-1]
    assert "150 of them to another host" in rec.summary()


def test_another_hosts_answer_before_any_step():
    page = FakePage()
    rec = Recorder(page, is_safe_url=safe, provider="Bank")
    rec.start()
    page.emit("response", api())
    assert rec.requests[0]["step"] is None
    assert rec.requests[0]["on_the_providers_own_site"] is False


def test_every_part_of_another_hosts_call_is_shaped():
    rec, page = recording()
    page.emit("response", api(
        url="https://%s.%s.test/%s/docs?%s=%s" % (LETTERS, SURNAME.lower(), MERCHANT,
                                                   SURNAME, LETTERS),
        body={MERCHANT: {SURNAME: 1}}, post=json.dumps(BODY2)))
    assert rec.requests[0]["batch"] == 2
    assert_none_came_out(rec.stop())


def test_the_providers_own_answer_needs_no_frame_or_kind():
    """The fakes of the older tests carry neither, and so does nothing on
    the provider's own host need to."""
    rec, page = recording()
    response = FakeResponse("https://bank.example/api/docs", body={"a": 1})
    response.request = type("R", (), {"method": "GET", "post_data": None})()
    page.emit("response", response)
    assert rec.requests[0]["shape"] == {"a": "int"}


# -- D. the file as written ---------------------------------------------------------

def test_the_new_fields_read_as_themselves_and_the_file_is_a_fixed_point():
    rec, page = recording()
    page.emit("response", graphql(BODY2, [{"data": {}}, {"data": {}}]))
    page.emit("response", api())
    page.emit("download", FakeDownload("https://bank.example/dl/x.pdf?token=1"))
    report = rec.stop()
    text = json.dumps(report)
    for key in ("batch", "post_items", "keys", "operation", "download_from",
                "download_query_keys", "download_off_host", "on_the_providers_own_site",
                "batch of 2"):
        assert '"%s"' % key in text, key
    assert shape_tree(report, rec.words, full_list=True) == report


def test_the_recorder_still_subscribes_to_the_same_events():
    rec, page = recording()
    assert set(page.handlers) == {"framenavigated", "response", "download", "page"}
