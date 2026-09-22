"""The recorder, and the four promises it makes to a tester.

A tester presses Record, clicks their way to a statement, and attaches
what comes out to a public issue. These are the things that must be true
of that file, tested against a fake page so no browser is needed.

    1. it will not start before the person is signed in
    2. no keystroke is captured, ever
    3. no cookie, header or stored token can reach the file
    4. a control is named by role, not by a class or a position
"""
import json
import re
from pathlib import Path

import pytest
from paperpull_core.recorder import REDACTED, Recorder, _CAPTURE_JS
from paperpull_core.redact import set_private_words

CORE = Path(__file__).resolve().parents[1] / "paperpull_core"


def safe(url):
    return (url or "").startswith("https://bank.example/")


class FakeLocator:
    def __init__(self, n=0):
        self._n = n

    def count(self):
        return self._n


class FakeFrame:
    def __init__(self, url=""):
        self.url = url


class FakePage:
    """Enough of a Playwright page to drive the recorder."""

    def __init__(self, url="https://bank.example/accounts", passwords=0):
        self.url = url
        self._passwords = passwords
        self.handlers = {}
        self.bindings = {}
        self.evaluated = []
        self.main_frame = FakeFrame(url)
        self.context = self
        self.removed = []

    def locator(self, sel):
        return FakeLocator(self._passwords if "password" in sel else 0)

    def expose_binding(self, name, fn):
        self.bindings[name] = fn

    def evaluate(self, script, arg=None):
        self.evaluated.append((script, arg))
        return "installed"

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.removed.append(event)

    # -- test helpers ----------------------------------------------------
    def fire(self, record):
        self.bindings["__ppRecorderPost"](None, record)

    def emit(self, event, *args):
        for h in self.handlers.get(event, []):
            h(*args)


class FakeResponse:
    def __init__(self, url, ctype="application/json", status=200,
                 body=None, method="GET", post=None):
        self.url = url
        self.headers = {"content-type": ctype}
        self.status = status
        self._body = body
        self.request = type("R", (), {"method": method, "post_data": post})()

    def json(self):
        return self._body


def rec(page=None, **kw):
    page = page or FakePage()
    r = Recorder(page, is_safe_url=safe, provider="Bank", **kw)
    r.start()
    return r, page


@pytest.fixture(autouse=True)
def _clean():
    set_private_words([])
    yield
    set_private_words([])


# -- 1. it will not start before the person is signed in ----------------------

def test_a_password_field_on_the_page_refuses_the_recording():
    page = FakePage(passwords=1)
    r = Recorder(page, is_safe_url=safe)
    assert "password" in r.refusal()
    with pytest.raises(RuntimeError, match="password"):
        r.start()
    assert page.bindings == {}, "nothing may be installed on a sign-in page"


def test_a_page_off_the_providers_site_refuses_the_recording():
    r = Recorder(FakePage(url="https://google.com/search"), is_safe_url=safe)
    assert "provider's own site" in r.refusal()
    with pytest.raises(RuntimeError):
        r.start()


def test_an_app_that_says_signed_out_refuses_the_recording():
    r = Recorder(FakePage(), is_safe_url=safe, looks_signed_out=lambda p: True)
    assert "sign in first" in r.refusal()
    with pytest.raises(RuntimeError):
        r.start()


def test_a_signed_in_provider_page_is_allowed():
    r = Recorder(FakePage(), is_safe_url=safe, looks_signed_out=lambda p: False)
    assert r.refusal() is None
    r.start()
    assert "__ppRecorderPost" in r.page.bindings


# -- 2. no keystroke is captured, ever ----------------------------------------

def test_the_capture_script_listens_for_nothing_that_could_see_a_keystroke():
    """Not filtered afterwards. There is no listener to filter."""
    listened = set(re.findall(r'addEventListener\("(\w+)"', _CAPTURE_JS))
    assert listened == {"click", "change", "submit"}, listened
    for never in ("keydown", "keyup", "keypress", "input", "beforeinput", "paste"):
        assert never not in listened


def test_the_capture_script_never_reads_an_input_value():
    """el.value would be the typed text. The only `value` it may read is a
    button's caption attribute, and only for a button."""
    assert ".value" not in _CAPTURE_JS.replace("el.options[el.selectedIndex]", "")
    assert "getAttribute(\"value\")" in _CAPTURE_JS


def test_a_typed_field_records_that_it_was_typed_into_and_not_what():
    r, page = rec()
    page.fire({"action": "fill", "locator": {"how": "id", "value": "searchBox"},
               "label": "Search", "value": "hunter2", "at": 1})
    step = r.steps[0]
    assert step["value"] == REDACTED
    assert "hunter2" not in json.dumps(r.report())


def test_a_dropdown_keeps_its_option_because_that_is_the_signal():
    r, page = rec()
    page.fire({"action": "select", "locator": {"how": "role", "role": "combobox",
                                               "name": "Statement period"},
               "label": "Statement period", "option": "March 2026", "at": 1})
    assert r.steps[0]["option"] == "March 2026"


def test_an_option_carrying_something_private_is_still_redacted():
    set_private_words(["Bryan"])
    r, page = rec()
    page.fire({"action": "select", "locator": {"how": "id", "value": "acct"},
               "label": "Account", "option": "Bryan's checking 998877665",
               "at": 1})
    out = r.steps[0]["option"]
    assert "Bryan" not in out and "998877665" not in out


# -- 3. no session can reach the file ------------------------------------------

def _code_only(path: Path) -> str:
    """The file with its comments and strings taken out, so a docstring
    that promises never to read a cookie does not read as reading one."""
    import io
    import tokenize
    kept = []
    with io.open(path, encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                kept.append(tok.string)
    return " ".join(kept)


def test_the_recorder_never_asks_for_a_cookie_a_header_or_storage():
    """Requirement 3 holds because the code to violate it is not there."""
    src = _code_only(CORE / "recorder.py")
    for never in ("cookies", "storage_state", "add_cookies", "all_headers",
                  "localStorage", "sessionStorage"):
        assert never not in src, never


def test_a_request_is_described_by_names_and_shapes_not_values():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "Statements"}, "label": "Statements", "at": 1})
    page.emit("response", FakeResponse(
        "https://bank.example/api/docs?acct=99887766&type=STATEMENT",
        body={"documents": [{"id": "abc", "balance": 1234.56}], "count": 1},
        method="POST", post='{"accountId": "X1", "year": 2026}'))
    entry = r.requests[0]
    assert entry["query"] == "acct=...&type=STATEMENT"
    assert entry["post_keys"] == ["accountId", "year"]
    assert entry["shape"] == {"documents": ["list of 1", {"id": "str", "balance": "float"}],
                              "count": "int"}
    blob = json.dumps(r.report())
    for value in ("1234.56", "X1", "99887766"):
        assert value not in blob, value


def test_a_request_to_anywhere_but_the_provider_is_counted_not_described():
    r, page = rec()
    page.emit("response", FakeResponse("https://ads.example/track?uid=abc",
                                       body={"seen": True}))
    assert r.requests == []
    assert r.dropped["off_host_request"] == 1


# -- 4. a control is named by role, not by a class or a position ---------------

def test_the_capture_script_never_builds_a_class_or_position_locator():
    for never in ("className", "classList", "nth-child", "nthChild",
                  "getAttribute(\"class\")", "querySelectorAll"):
        assert never not in _CAPTURE_JS, never


def test_a_hashed_id_is_not_treated_as_stable():
    """Angular and styled-components ids change on every deploy."""
    hashy = re.search(r"const HASHY = (/.*?/i);", _CAPTURE_JS).group(1)
    assert "ng-" in hashy and "css-" in hashy and "[0-9]{6,}" in hashy


def test_role_and_name_come_first_in_the_preference_order():
    order = [m for m in re.findall(r'how: "(\w+)"', _CAPTURE_JS)]
    assert order[0] == "role"
    assert order.index("testid") < order.index("text")
    assert order[-1] == "unresolved"


# -- the noise filter ----------------------------------------------------------

def test_a_click_on_nothing_nameable_is_dropped_as_wandering():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "unresolved", "tag": "div"},
               "label": "  ", "at": 1})
    assert r.steps == []
    assert r.dropped["unresolved"] == 1


def test_the_same_click_twice_in_a_moment_is_one_click():
    r, page = rec()
    loc = {"how": "role", "role": "button", "name": "Download"}
    page.fire({"action": "click", "locator": loc, "label": "Download", "at": 1000})
    page.fire({"action": "click", "locator": loc, "label": "Download", "at": 1200})
    assert len(r.steps) == 1 and r.dropped["repeat"] == 1


def test_the_same_click_later_is_a_real_second_click():
    r, page = rec()
    loc = {"how": "role", "role": "button", "name": "Next"}
    page.fire({"action": "click", "locator": loc, "label": "Next", "at": 1000})
    page.fire({"action": "click", "locator": loc, "label": "Next", "at": 9000})
    assert len(r.steps) == 2


# -- what a step caused --------------------------------------------------------

def test_a_step_carries_what_it_set_off():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "March 2026"}, "label": "March 2026", "at": 1})
    page.main_frame.url = "https://bank.example/statements/view"
    page.emit("framenavigated", page.main_frame)
    page.emit("response", FakeResponse("https://bank.example/api/pdf",
                                       ctype="application/pdf"))
    page.emit("download", type("D", (), {"suggested_filename": "stmt_998877665.pdf"})())
    effect = r.steps[0]["effect"]
    assert effect["navigated"] and effect["download"] and effect["requests"] == 1
    assert "998877665" not in effect["download_name"]


def test_the_capture_script_is_put_back_after_a_navigation():
    r, page = rec()
    before = len(page.evaluated)
    page.emit("framenavigated", page.main_frame)
    assert len(page.evaluated) > before, "a new document has no listeners"


def test_a_new_tab_is_noted_with_whether_it_left_the_provider():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "View"}, "label": "View", "at": 1})
    page.emit("page", FakePage(url="https://docs.vendor.example/x"))
    assert r.steps[0]["effect"]["new_tab"] is True
    assert r.steps[0]["effect"]["new_tab_off_host"] is True


# -- stopping ------------------------------------------------------------------

def test_stopping_takes_every_listener_back_off():
    r, page = rec()
    r.stop()
    for event in ("framenavigated", "response", "download"):
        assert event in page.removed, event


def test_stopping_silences_what_is_left_in_the_page():
    r, page = rec()
    r.stop()
    assert any("__ppRecorderPost = () => {}" in str(s) for s, _ in page.evaluated)


def test_a_recording_with_nothing_in_it_is_still_a_valid_report():
    r, _ = rec()
    report = r.stop()
    assert report["steps"] == [] and report["kind"] == "paperpull-recording"
    assert json.dumps(report)


def test_the_report_says_what_it_does_not_contain():
    r, _ = rec()
    assert "Typed values are never captured" in r.stop()["note"]


def test_the_summary_reads_as_a_sentence():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "Bills"}, "label": "Bills", "at": 1})
    assert r.summary() == "1 step(s) (1 click), 0 provider request(s)"


# -- the guard's opinion, carried through ---------------------------------------

def test_the_apps_own_guard_verdict_rides_along_when_it_is_given():
    r, page = rec(is_safe_control=lambda t: "pay" not in t.lower())
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "Pay bill"}, "label": "Pay bill", "at": 1})
    page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                              "name": "View statement"}, "label": "View statement", "at": 2})
    assert r.steps[0]["guard_allows"] is False
    assert r.steps[1]["guard_allows"] is True


def test_a_click_on_a_heading_or_a_paragraph_is_wandering():
    """The mouse landing on the page, not on a control. The live run put
    "Welcome back, [name]" in as a step until this."""
    r, page = rec()
    for tag in ("h1", "p", "span", "div"):
        page.fire({"action": "click", "locator": {"how": "text", "value": "Some words"},
                   "label": "Some words", "tag": tag, "at": 1})
    assert r.steps == []
    assert r.dropped["unresolved"] == 4


def test_a_div_that_carries_a_role_is_a_control_and_is_kept():
    r, page = rec()
    page.fire({"action": "click", "locator": {"how": "role", "role": "button",
                                              "name": "Download"},
               "label": "Download", "tag": "div", "at": 1})
    assert len(r.steps) == 1


def test_the_click_before_a_dropdown_changes_is_the_same_act():
    """A select fires click then change. Two steps for one thing sends the
    maintainer looking for a click that does not exist."""
    r, page = rec()
    loc = {"how": "role", "role": "combobox", "name": "Period"}
    page.fire({"action": "click", "locator": loc, "label": "Period", "at": 1000})
    page.fire({"action": "select", "locator": loc, "label": "Period",
               "option": "March 2026", "at": 1100})
    assert [s["action"] for s in r.steps] == ["select"]
    assert r.steps[0]["i"] == 0, "the step that remains is renumbered"


def test_a_click_long_before_a_change_is_its_own_step():
    r, page = rec()
    loc = {"how": "role", "role": "checkbox", "name": "PDF only"}
    page.fire({"action": "click", "locator": loc, "label": "PDF only", "at": 1000})
    page.fire({"action": "check", "locator": loc, "label": "PDF only",
               "checked": True, "at": 9000})
    assert [s["action"] for s in r.steps] == ["click", "check"]


# -- waiting for the person ----------------------------------------------------

def test_with_no_console_it_waits_for_the_panels_file_and_prints_no_prompt(tmp_path, monkeypatch):
    """The panel runs an app with its input closed. A live run found that
    input() raises ValueError there, not EOFError, and that the prompt had
    already been printed before it did."""
    from paperpull_core import recorder as mod
    monkeypatch.setattr(mod, "can_ask", lambda: False)
    said = []
    stop = tmp_path / ".stop-recording"

    def asked(*a, **k):
        raise AssertionError("it must not ask when nobody can answer")

    monkeypatch.setattr("builtins.input", asked)
    import threading
    threading.Timer(0.05, lambda: stop.write_text("stop", encoding="utf-8")).start()
    mod._wait_for_stop(stop, said.append)
    assert any("control panel" in s for s in said)
    assert not any("Press Enter" in s for s in said)


def test_with_a_console_it_waits_for_enter(tmp_path, monkeypatch):
    from paperpull_core import recorder as mod
    monkeypatch.setattr(mod, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    mod._wait_for_stop(tmp_path / "never-written", said := [].append)
    assert not any("control panel" in s for s in said.__self__)


@pytest.mark.parametrize("boom", [EOFError, OSError, ValueError, RuntimeError])
def test_a_console_that_turns_out_not_to_be_one_falls_back(tmp_path, monkeypatch, boom):
    from paperpull_core import recorder as mod
    monkeypatch.setattr(mod, "can_ask", lambda: True)

    def raiser(*a, **k):
        raise boom("no console after all")

    monkeypatch.setattr("builtins.input", raiser)
    stop = tmp_path / ".stop-recording"
    stop.write_text("stop", encoding="utf-8")
    said = []
    mod._wait_for_stop(stop, said.append)
    assert any("control panel" in s for s in said)
