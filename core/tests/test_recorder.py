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
from paperpull_core.recorder import (REDACTED, Recorder, _CAPTURE_JS,
                                    concerns, record_session)
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


def test_a_field_is_never_named_by_what_is_already_in_it():
    """`.value` is not the only way to read what is in a field.

    A server-rendered textarea holds its contents as a text node, so
    innerText reads them, and a form with the account holder's address
    pre-filled would have named the field after the address. Checked
    against the real script in a JS runtime before this was written, which
    is why the assertion is on the guard rather than on a behaviour the
    FakePage cannot produce."""
    body = _CAPTURE_JS[_CAPTURE_JS.index("const nameOf"):
                       _CAPTURE_JS.index("const locate")]
    fallback = [ln for ln in body.splitlines() if "el.innerText" in ln]
    assert len(fallback) == 1, fallback
    assert "typed ?" in fallback[0], fallback[0]
    assert 'tag === "textarea"' in body
    assert 'tag === "select"' in body


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


# -- the page is not to be trusted ---------------------------------------------
# The binding sits on window, so any script on the provider's page can call
# it, not only the listener the recorder installed. Found by auditing.

@pytest.mark.parametrize("payload", [
    None, "a string", 42, [], {"action": "eval"}, {"action": "click"},
    {"action": "click", "locator": "not a dict", "label": "x"},
    {"action": "click", "locator": {"how": ["a"], "role": {"b": 1}, "name": None},
     "label": "x", "at": "not a number"},
    {"action": "click", "locator": {"how": "role", "role": "link", "name": "x"},
     "label": "x", "tag": 99, "at": 1},
    {"action": "select", "locator": {"how": "id", "value": 1}, "option": [1, 2], "at": 1},
])
def test_a_malformed_payload_from_the_page_never_raises(payload):
    r, page = rec()
    page.fire(payload)
    assert json.dumps(r.report()), "the report must stay serialisable"


def test_a_page_cannot_grow_the_file_without_limit():
    r, page = rec()
    for i in range(600):
        page.fire({"action": "click", "locator": {"how": "role", "role": "link",
                                                  "name": "L%d" % i},
                   "label": "L%d" % i, "at": i * 1000})
    assert len(r.steps) == 400
    for i in range(500):
        page.emit("response", FakeResponse("https://bank.example/a%d" % i, body={"i": i}))
    assert len(r.requests) == 300


def test_every_string_the_page_sends_is_cut_to_a_sane_length():
    r, page = rec()
    page.fire({"action": "select", "locator": {"how": "id", "value": "x" * 500},
               "label": "L" * 5000, "option": "O" * 5000, "at": 1})
    step = r.steps[0]
    assert len(step["label"]) <= 120
    assert len(step["option"]) <= 60
    assert len(step["locator"]["value"]) <= 80


def test_a_response_or_download_before_any_click_is_not_a_crash():
    r, page = rec()
    page.emit("response", FakeResponse("https://bank.example/api/x", body={"a": 1}))
    page.emit("download", type("D", (), {"suggested_filename": "x.pdf"})())
    page.emit("page", FakePage())
    assert r.steps == []
    assert r.requests[0]["step"] is None


def test_starting_or_stopping_twice_is_harmless():
    r, page = rec()
    r.start()
    assert len(page.bindings) == 1
    r.stop()
    assert r.stop()["kind"] == "paperpull-recording"


def _session(tmp_path, monkeypatch, owner):
    """One whole record_session, with the wait for the person skipped."""
    import types
    from paperpull_core import recorder as mod
    monkeypatch.setattr(mod, "_wait_for_stop", lambda stop, say: None)
    said = []
    site = types.SimpleNamespace(is_safe_url=safe, looks_signed_out=lambda p: False)
    out = mod.record_session(FakePage(), site, tmp_path, provider="Bank",
                             owner=owner, say=said.append)
    return said, out


def test_with_no_owner_set_the_person_is_told_what_is_not_covered(tmp_path, monkeypatch):
    """redact removes the owner's name because the config gives it. With
    no owner, a name on a profile button is not caught, and saying so
    beats implying a cover that is not there."""
    said, _ = _session(tmp_path, monkeypatch, owner="")
    assert any("cannot be removed for you" in s for s in said)


def test_with_an_owner_set_it_does_not_say_that(tmp_path, monkeypatch):
    said, _ = _session(tmp_path, monkeypatch, owner="Alex Morgan")
    assert not any("cannot be removed" in s for s in said)


def test_a_session_writes_the_file_and_says_to_read_it(tmp_path, monkeypatch):
    said, out = _session(tmp_path, monkeypatch, owner="Alex Morgan")
    assert Path(out) == tmp_path / "recording.json"
    assert json.loads(Path(out).read_text(encoding="utf-8"))["kind"] == "paperpull-recording"
    assert any("Read that file through" in s for s in said)
    assert any("Nothing was recorded" in s for s in said), "an empty one says so"


def test_a_session_refuses_and_writes_nothing_on_a_sign_in_page(tmp_path, monkeypatch):
    import types
    from paperpull_core import recorder as mod
    said = []
    site = types.SimpleNamespace(is_safe_url=safe, looks_signed_out=lambda p: False)
    out = mod.record_session(FakePage(passwords=1), site, tmp_path,
                             provider="Bank", owner="", say=said.append)
    assert out is None
    assert not list(tmp_path.iterdir()), "nothing may be written when it refuses"
    assert any("Not recording" in s for s in said)


def test_a_stale_stop_file_does_not_end_the_next_recording_at_once(tmp_path, monkeypatch):
    """A recording that was interrupted can leave the sentinel behind. The
    next one must clear it before it starts waiting, or it ends instantly."""
    import types
    from paperpull_core import recorder as mod
    (tmp_path / ".stop-recording").write_text("stale", encoding="utf-8")
    seen = {}

    def wait(stop, say):
        seen["existed_when_waiting"] = stop.exists()

    monkeypatch.setattr(mod, "_wait_for_stop", wait)
    site = types.SimpleNamespace(is_safe_url=safe, looks_signed_out=lambda p: False)
    mod.record_session(FakePage(), site, tmp_path, provider="B", owner="", say=lambda *a: None)
    assert seen["existed_when_waiting"] is False
    assert not (tmp_path / ".stop-recording").exists(), "and it is cleaned up after"


def test_a_huge_response_body_is_not_fetched_while_the_person_is_clicking():
    """Reading a body is a round trip to the browser. A megabyte-sized
    transaction list has the same shape as a small one, so it is not worth
    the pause."""
    r, page = rec()
    big = FakeResponse("https://bank.example/api/all", body={"rows": [1]})
    big.headers["content-length"] = str(9_000_000)
    big.json = lambda: (_ for _ in ()).throw(AssertionError("must not read it"))
    page.emit("response", big)
    assert r.requests[0]["shape"] == "not read, 9000000 bytes"


def test_a_normal_response_body_is_still_read():
    r, page = rec()
    small = FakeResponse("https://bank.example/api/x", body={"a": 1})
    small.headers["content-length"] = "120"
    page.emit("response", small)
    assert r.requests[0]["shape"] == {"a": "int"}


# ---------------------------------------------------------------------------
# Reading the file back, before it goes anywhere
#
# The bar here is different from the rest of the module. A check that shouts
# at every year in a statement list is a check nobody reads, and one that
# says nothing at all is worse than not having it.
# ---------------------------------------------------------------------------

def a_report(**kw):
    r = {"kind": "paperpull-recording", "provider": "Testco",
         "recorded_at": "2026-09-22T10:00:00", "steps": [], "requests": [],
         "dropped": {}, "note": "Typed values are never captured."}
    r.update(kw)
    return r


def a_step(**kw):
    s = {"i": 0, "action": "click", "label": "", "at": 1,
         "locator": {"how": "role", "role": "link", "name": "Statements"},
         "effect": {"requests": 0}}
    s.update(kw)
    return s


def named(value, how="role"):
    loc = {"how": how, "role": "link", "name": value} if how == "role" \
        else {"how": how, "value": value}
    return a_report(steps=[a_step(locator=loc)])


def test_a_year_is_not_flagged():
    """A statement list is nothing but years. Flagging every one of them
    buries the single number that matters."""
    r = a_report(steps=[a_step(action="select", option="2024",
                               locator={"how": "label", "value": "Year"})])
    assert not any("2024" in c for c in concerns(r))


def test_a_number_that_is_not_a_year_is_flagged():
    assert any("48213" in c for c in concerns(named("Account 48213")))


def test_a_six_digit_number_is_not_flagged_here():
    """Redaction already took it, so seeing one would mean redaction ran
    and this is reporting on its own output. The check below covers that."""
    assert not any("123456" in c for c in concerns(named("Account [REDACTED]")))


def test_our_own_timestamp_is_never_a_concern():
    assert not any("recorded_at" in c for c in concerns(a_report()))


def test_our_own_note_is_never_a_concern():
    r = a_report(note="Typed values are never captured. Read this through.")
    assert not any(c.startswith("note") for c in concerns(r))


def test_an_email_that_slipped_through_is_flagged():
    assert any("email" in c for c in concerns(named("ada@example.test", "text")))


def test_a_street_address_is_flagged():
    r = named("1600 Pennsylvania Ave", "text")
    assert any("street address" in c for c in concerns(r))


def test_a_control_name_that_looks_like_a_name_is_not_flagged():
    """Sites label things Bill History and Account Summary all day."""
    for name in ("Bill History", "Account Summary", "View Statements",
                 "Payment History", "Tax Documents", "Order Details"):
        assert not any(name in c for c in concerns(named(name))), name


def test_a_person_shaped_name_is_flagged():
    """The one thing redaction cannot take when no owner is configured."""
    assert any("Alex Morgan" in c for c in concerns(named("Alex Morgan")))


def test_something_redaction_would_have_removed_is_flagged():
    """A value redaction removes should never be in the file. If one is,
    it got there without going through redaction, which is a bug."""
    r = named("Balance $1,204.55", "text")
    assert any("redaction would remove" in c for c in concerns(r))


def test_a_clean_recording_raises_nothing():
    assert concerns(a_report()) == []


def test_one_finding_is_one_sentence_however_often_it_appears():
    """An account number in forty rows is one thing to fix. Forty lines
    saying so is a wall of text that gets skipped."""
    s = a_step(locator={"how": "role", "role": "link", "name": "Account 48213"})
    r = a_report(steps=[s, dict(s, i=1), dict(s, i=2)])
    said = concerns(r)
    assert len(said) == 1
    assert "steps[0].locator.name (and 2 other places)" in said[0]


def test_two_places_reads_as_one_other_place():
    s = a_step(locator={"how": "role", "role": "link", "name": "Account 48213"})
    said = concerns(a_report(steps=[s, dict(s, i=1)]))
    assert "(and 1 other place)" in said[0]


def test_two_different_findings_are_two_sentences():
    r = a_report(steps=[
        a_step(locator={"how": "role", "role": "link", "name": "Account 48213"}),
        a_step(i=1, locator={"how": "text", "value": "ada@example.test"})])
    assert len(concerns(r)) == 2


def test_a_file_nested_beyond_all_reason_does_not_run_out_of_stack():
    """Running out of stack while checking a file for private data would
    fail in the one direction that matters."""
    deep = "the bottom"
    for _ in range(400):
        deep = {"x": deep}
    assert concerns(a_report(steps=[a_step(effect=deep)])) == []


def test_the_tester_is_told_what_to_look_at_without_a_maintainer_tool(tmp_path):
    """The person deciding whether to attach the file is standing in front
    of the app's console, not the maintainer's checkout, so the check runs
    at the end of the recording and not only in tools/read_recording.py."""
    import threading

    said = []
    page = FakePage()
    page.url = "https://bank.example/documents"

    class Site:
        is_safe_url = staticmethod(safe)

    def click_then_stop():
        page.fire({"action": "click", "at": 1, "label": "Alex Morgan",
                   "locator": {"how": "role", "role": "button",
                               "name": "Alex Morgan"}})
        (tmp_path / ".stop-recording").write_text("stop", encoding="utf-8")

    threading.Timer(0.05, click_then_stop).start()
    out = record_session(page, Site, tmp_path, provider="Testco", owner="",
                         say=said.append)

    printed = " ".join(said)
    assert "Before this file goes anywhere" in printed
    assert "Alex Morgan" in printed
    assert json.loads(Path(out).read_text(encoding="utf-8"))["steps"]


def test_a_clean_recording_does_not_warn_the_tester(tmp_path):
    import threading

    said = []
    page = FakePage()
    page.url = "https://bank.example/documents"

    class Site:
        is_safe_url = staticmethod(safe)

    def click_then_stop():
        page.fire({"action": "click", "at": 1, "label": "Statements",
                   "locator": {"how": "role", "role": "link",
                               "name": "Statements"}})
        (tmp_path / ".stop-recording").write_text("stop", encoding="utf-8")

    threading.Timer(0.05, click_then_stop).start()
    record_session(page, Site, tmp_path, provider="Testco", owner="",
                   say=said.append)
    assert "Before this file goes anywhere" not in " ".join(said)
