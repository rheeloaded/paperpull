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


def test_a_dropdowns_option_keeps_only_the_words_on_the_list():
    rec, page = recording()
    page.fire({"action": "select", "label": "Account", "at": 1,
               "locator": {"how": "role", "role": "combobox", "name": "Account"},
               "option": "Checking %s" % MERCHANT})
    assert rec.stop()["steps"][0]["option"] == "Checking aa9aaaaaa9aaa"


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
