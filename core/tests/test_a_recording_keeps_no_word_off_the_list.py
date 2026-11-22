"""A recording keeps a word off the page only when it is on the word list.

A provider can name a statement after the account it belongs to, an id
made of letters and digits, and a recording kept the name of a file a
step downloaded. Redaction masks runs of digits, so the letters went out
as they were, in a file the recorder's own note said held nothing from the
account.

Every channel a recording writes a page's words through is tried here with
an invented value made of letters and digits, the kind redaction lets
through, and none may come out. Each of these failed on the recorder as it
was, which kept them through redaction. Nothing here is a real value.
"""
import json

from paperpull_core.recorder import Recorder
from paperpull_core.redact import set_private_words

import pytest

# Invented, each made the way redaction could not see. Letters with a digit
# or two, letters alone, and a name a site might build an id from.
MERCHANT = "QZ4XKRWPT7MVN"        # thirteen letters and digits, a merchant id's shape
LETTERS = "QZXKRWPTKMVNB"         # an id of letters alone
SURNAME = "Zorvexquill"           # a name, letters only
CANARIES = (MERCHANT, LETTERS, SURNAME)


def safe(url):
    return (url or "").startswith("https://bank.example/")


class FakeFrame:
    def __init__(self, url=""):
        self.url = url


class FakePage:
    """Enough of a Playwright page to drive the recorder."""

    def __init__(self, url="https://bank.example/accounts"):
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


class FakeResponse:
    def __init__(self, url, ctype="application/json", body=None, method="GET", post=None):
        self.url = url
        self.headers = {"content-type": ctype}
        self.status = 200
        self._body = body
        self.request = type("R", (), {"method": method, "post_data": post})()

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _no_owner():
    set_private_words([])
    yield
    set_private_words([])


def recording():
    page = FakePage()
    rec = Recorder(page, is_safe_url=safe, provider="Bank")
    rec.start()
    return rec, page


def click(page, label="Statements", locator=None, at=1000):
    page.fire({"action": "click", "label": label, "at": at,
               "locator": locator or {"how": "role", "role": "link", "name": label}})


def written(rec) -> str:
    return json.dumps(rec.stop())


def assert_none_came_out(rec):
    text = written(rec)
    for canary in CANARIES:
        assert canary.lower() not in text.lower(), "%s came out" % canary


# -- the file a step downloaded -------------------------------------------------

def test_a_downloaded_files_name_leaves_as_its_shape():
    """An id of letters and digits, a code and two dates, invented. The
    kind of file stays, in lowercase, and so does where each letter and
    digit sat."""
    rec, page = recording()
    click(page, "Download")
    name = MERCHANT + "-MSR-10000000000000-20000000000000.PDF"
    page.emit("download", type("D", (), {"suggested_filename": name})())
    report = rec.stop()
    got = report["steps"][0]["effect"]["download_name"]
    assert got == "aa9aaaaaa9aaa-aaa-99999999999999-99999999999999.pdf"
    assert MERCHANT not in json.dumps(report)


def test_a_name_with_no_digits_at_all_is_shaped_too():
    rec, page = recording()
    click(page, "Download")
    page.emit("download", type("D", (), {"suggested_filename":
                                         "%s_%s.pdf" % (SURNAME, LETTERS)})())
    assert_none_came_out(rec)


# -- what a control is called ----------------------------------------------------

def test_a_controls_label_keeps_only_the_words_on_the_list():
    rec, page = recording()
    click(page, "Statement for %s" % SURNAME)
    step = rec.stop()["steps"][0]
    assert step["label"] == "Statement for aaaaaaaaaaa"
    assert step["locator"]["name"] == "Statement for aaaaaaaaaaa"


def test_a_dropdowns_option_keeps_only_the_words_a_name_may_keep():
    """An account picker's option is an account, and Checking is on the
    list, so the list alone kept it. An option keeps only KINDS (#103)."""
    rec, page = recording()
    page.fire({"action": "select", "label": "Account", "at": 1,
               "locator": {"how": "role", "role": "combobox", "name": "Account"},
               "option": "Checking %s" % MERCHANT})
    assert rec.stop()["steps"][0]["option"] == "aaaaaaaa aa9aaaaaa9aaa"


def test_an_account_pickers_option_named_in_words_on_the_list_leaves_as_its_shape():
    rec, page = recording()
    page.fire({"action": "select", "label": "Account", "at": 1,
               "locator": {"how": "role", "role": "combobox", "name": "Account"},
               "option": "Custom Cash Card - 1234"})
    assert rec.stop()["steps"][0]["option"] == "aaaaaa aaaa aaaa - 9999"


def test_a_card_tile_clicked_leaves_no_word_of_its_name():
    """A card's tile is a control, and its name is spelled in words on the
    list. A control's name keeps only KINDS (#103)."""
    rec, page = recording()
    click(page, "Custom Cash Card - 1234",
          {"how": "role", "role": "link", "name": "Custom Cash Card - 1234"})
    step = rec.stop()["steps"][0]
    assert step["label"] == "aaaaaa aaaa aaaa - 9999"
    assert step["locator"]["name"] == "aaaaaa aaaa aaaa - 9999"


def test_a_statement_pickers_option_keeps_its_month():
    rec, page = recording()
    page.fire({"action": "select", "label": "Statement", "at": 1,
               "locator": {"how": "role", "role": "combobox", "name": "Statement"},
               "option": "October 2026 statement"})
    assert rec.stop()["steps"][0]["option"] == "October 9999 statement"


def test_a_test_id_an_id_and_a_name_attribute_are_shaped():
    """A site builds those from what it shows, a holder's name, an account."""
    rec, page = recording()
    click(page, "View", {"how": "testid", "value": "acct-" + MERCHANT}, at=1000)
    click(page, "View", {"how": "id", "value": "holder_" + SURNAME}, at=3000)
    click(page, "View", {"how": "name", "value": "pay" + LETTERS}, at=5000)
    assert_none_came_out(rec)


def test_how_a_control_was_found_and_its_role_are_words_of_ours():
    """The binding is on window, so any script on the page can call it and
    say anything in any field."""
    rec, page = recording()
    click(page, "Download", {"how": MERCHANT, "role": LETTERS, "name": "Download",
                             "tag": "x-" + SURNAME.lower()})
    locator = rec.stop()["steps"][0]["locator"]
    assert locator["how"] == "unresolved"
    assert locator["role"] == "other"
    assert_none_came_out(rec)


# -- where the page went and what it asked for ---------------------------------------

def test_where_a_step_landed_is_shaped_path_and_fragment_alike():
    rec, page = recording()
    click(page)
    page.main_frame.url = ("https://bank.example/merchant/%s/statements#/acct/%s"
                           % (LETTERS, SURNAME))
    page.emit("framenavigated", page.main_frame)
    landed = rec.stop()["steps"][0]["effect"]["landed_on"]
    assert landed == "https://bank.example/merchant/aaaaaaaaaaaaa/statements#/acct/aaaaaaaaaaa"


def test_a_requests_address_query_body_keys_and_post_keys_are_shaped():
    rec, page = recording()
    click(page)
    page.emit("response", FakeResponse(
        "https://bank.example/api/merchant/%s/docs?merchant=%s&type=STATEMENT"
        % (LETTERS, LETTERS),
        body={MERCHANT: {"balance": 1.0}, "documents": [{"id": "x"}]},
        method="POST", post=json.dumps({MERCHANT: 1, "year": 2031})))
    report = rec.stop()
    entry = report["requests"][0]
    assert entry["url"] == "https://bank.example/api/merchant/aaaaaaaaaaaaa/docs"
    assert entry["query"] == "merchant=aaaaaaaaaaaaa&type=STATEMENT"
    assert entry["post_keys"] == ["aa9aaaaaa9aaa", "year"]
    assert "aa9aaaaaa9aaa" in entry["shape"] and "documents" in entry["shape"]
    assert_none_came_out(rec)


def test_the_shape_of_a_deep_page_comes_through_whole():
    """The rule goes over the whole report on the way out, and a page's
    shape nests two levels for each element between the body and the
    control. A real page is forty elements deep, and a rule that stopped
    at fourteen levels cut every one of them short without saying so."""
    rec, page = recording()
    node = {"tag": "button", "attrs": ["type"], "child_count": 0, "visible": True,
            "text": True}
    for _ in range(60):
        node = {"tag": "div", "attrs": ["class"], "child_count": 1, "visible": True,
                "children": [node]}
    page.fire({"action": "click", "label": "Download", "at": 1,
               "locator": {"how": "role", "role": "button", "name": "Download"},
               "structure": {"root": {"tag": "body", "attrs": [], "child_count": 1,
                                      "visible": True, "children": [node]},
                             "nodes": 62, "truncated": False}})
    shape = rec.stop()["steps"][0]["structure"]
    depth, here = 0, shape["root"]
    while here.get("children"):
        here = here["children"][0]
        depth += 1
    assert depth == 61 and here["tag"] == "button", "cut at %d" % depth
    assert "..." not in json.dumps(shape)


def test_a_content_type_and_a_method_are_words_of_ours():
    rec, page = recording()
    click(page)
    page.emit("response", FakeResponse(
        "https://bank.example/api/docs", ctype="application/json; profile=" + MERCHANT,
        body={"documents": []}, method=LETTERS))
    entry = rec.stop()["requests"][0]
    assert entry["type"] == "json"
    assert entry["method"] == "other"
    assert_none_came_out(rec)


# -- a batch of calls, where a download came from, another host's answer ----------
# Each channel the recorder reads since it learned batches (#170), the source
# of a download (#178) and a provider's own API on a host the app does not
# list. Every invented value goes into one channel at a time.

class _Frame:
    def __init__(self, url):
        self.url = url


class _PageCall(FakeResponse):
    """An answer to a script's call made by the provider's own page."""

    def __init__(self, url, body=None, post=None, frame="https://bank.example/accounts"):
        FakeResponse.__init__(self, url, body=body, method="POST", post=post)
        self.request.resource_type = "fetch"
        self.request.frame = _Frame(frame)


def _batch(item, answer=None):
    return _PageCall("https://bank.example/graphql", body=answer or [{"data": {}}],
                     post=json.dumps([item, {"operationName": "documents"}]))


_CHANNELS = {
    "a call's key": lambda: _batch({MERCHANT: 1, LETTERS + SURNAME: 2}),
    "an operation's name": lambda: _batch({"operationName": MERCHANT + SURNAME + LETTERS}),
    "a variable's value": lambda: _batch({"variables": {"id": MERCHANT, "who": SURNAME,
                                                       "acct": LETTERS}}),
    "the query's text": lambda: _batch({"query": "{ %s(%s: %s) }" % (MERCHANT, SURNAME, LETTERS)}),
    "a call that is a string": lambda: _batch("%s %s %s" % (MERCHANT, SURNAME, LETTERS)),
    "an answer's key and value, first call": lambda: _batch(
        {"operationName": "documents"}, [{MERCHANT: SURNAME, "a": LETTERS}]),
    "an answer's key and value, last call": lambda: _batch(
        {"operationName": "documents"}, [{}] * 9 + [{MERCHANT: SURNAME, "a": LETTERS}]),
    "another host's name": lambda: _PageCall(
        "https://%s.%s.%s.test/docs" % (MERCHANT, SURNAME, LETTERS), body={"a": 1}),
    "another host's path": lambda: _PageCall(
        "https://api.bankcdn.test/%s/%s/%s" % (MERCHANT, SURNAME, LETTERS), body={"a": 1}),
    "another host's query": lambda: _PageCall(
        "https://api.bankcdn.test/docs?%s=%s&acct=%s" % (SURNAME, MERCHANT, LETTERS),
        body={"a": 1}),
    "another host's answer": lambda: _PageCall(
        "https://api.bankcdn.test/docs", body={MERCHANT: {SURNAME: LETTERS}}),
}


@pytest.mark.parametrize("channel", sorted(_CHANNELS))
def test_every_new_channel_of_a_request_keeps_no_word_off_the_list(channel):
    rec, page = recording()
    click(page)
    page.emit("response", _CHANNELS[channel]())
    assert len(rec.requests) == 1, "the request was not kept, so this proves nothing"
    assert_none_came_out(rec)


_SOURCES = {
    "a path": "https://bank.example/dl/%s/%s/%s.pdf" % (MERCHANT, SURNAME, LETTERS),
    "a parameter's value": "https://bank.example/dl?doc=%s&who=%s&acct=%s"
                           % (MERCHANT, SURNAME, LETTERS),
    "a parameter's name": "https://bank.example/dl?%s=1&%s=2&%s=3" % (MERCHANT, SURNAME, LETTERS),
    "a fragment": "https://bank.example/dl#%s/%s/%s" % (MERCHANT, SURNAME, LETTERS),
    "another host": "https://%s.%s.%s.test/dl" % (MERCHANT, SURNAME, LETTERS),
    "a data payload": "data:application/pdf;base64,%s%s%s" % (MERCHANT, SURNAME, LETTERS),
    "a data media type": "data:application/%s-%s-%s;base64,AA" % (MERCHANT, SURNAME, LETTERS),
    "a blob's path": "blob:https://bank.example/%s-%s-%s" % (MERCHANT, SURNAME, LETTERS),
    "a user before the host": "https://%s:%s@bank.example/dl/%s" % (MERCHANT, SURNAME, LETTERS),
}


@pytest.mark.parametrize("channel", sorted(_SOURCES))
def test_where_a_download_came_from_keeps_no_word_off_the_list(channel):
    rec, page = recording()
    click(page, "Download")
    page.emit("download", type("D", (), {"suggested_filename": "statement.pdf",
                                         "url": _SOURCES[channel]})())
    report = rec.stop()
    assert report["steps"][0]["effect"].get("download_from"), "nothing was kept to test"
    text = json.dumps(report).lower()
    for canary in CANARIES:
        assert canary.lower() not in text, "%s came out" % canary
