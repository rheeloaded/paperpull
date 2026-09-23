"""The failure diagnostic, measured against the bugs that caused it.

Costco went from a scaffold to a working provider through eight bugs,
and the estimate was nine to twelve tester rounds to fix them remotely
because each one hides the next. The claim this module makes is that a
census of the app's own selectors, taken at the moment of failure,
states most of them outright in one file.

The tests below are those eight bugs, replayed. Each one builds the page
state that bug produced and asks whether the file would have said so.

What may leave the file at all is held by test_failure_canary.py, which
runs a real browser over a page carrying a fake secret in every channel
and asserts that none of them comes out.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import failure


class FakePage:
    """A page that answers the three questions this module asks."""

    def __init__(self, nodes=None, state=None, errors=0, bad_selectors=(),
                 kept=None):
        self.nodes = nodes or {}
        self._state = state or {}
        self._errors = errors
        self._bad = set(bad_selectors)
        self._kept = kept
        self.asked = []

    def evaluate(self, script, arg=None):
        self.asked.append(script[:50])
        if "__ppErrorCount = 0" in script:
            return "installed"
        if "__ppErrorCount" in script or "__ppRejectCount" in script:
            return self._errors
        if "for (const [name, sel] of selectors)" in script:
            return [self._one(name, sel) for name, sel in arg]
        if "largest_visible" in script:
            base = {"ready": "complete", "html_overflow": "auto",
                    "body_overflow": "auto", "body_scroll_height": 2000,
                    "body_text_len": 3000, "visible_elements": 120,
                    "counts": {"buttons": 12, "links": 40, "dialogs": 0,
                               "iframes": 0, "inputs": 3, "passwords": 0},
                    "largest_visible": {"tag": "main", "class": "content",
                                        "text_len": 3000}}
            base.update(self._state)
            return base
        if "scroll_height" in script:
            return self._kept
        return None

    def _one(self, name, sel):
        if sel in self._bad:
            return {"name": name, "evaluation": "invalid_css_selector"}
        found = self.nodes.get(sel, [])
        return {"name": name, "matched": len(found),
                "visible": sum(1 for n in found if n.get("on_screen")),
                "nodes": found[:5]}


def node(on_screen=True, **kw):
    n = {"tag": "div", "class": "", "has_id": False, "has_testid": False,
         "role": "", "box": [600, 400], "display": "block",
         "visibility": "visible", "position": "static", "text_len": 500,
         "on_screen": on_screen}
    n.update(kw)
    return n


# -- bug one, a selector the browser cannot parse ------------------------------

def test_a_playwright_selector_is_named_without_asking_the_page():
    """It can never work inside the page, so the answer needs no page.
    This one was silent for a whole build, and every list read empty."""
    page = FakePage()
    out = failure.census(page, {"receipt_button": "button:has-text('View')"})
    assert out[0]["evaluation"] == "playwright_only_syntax"
    assert out[0]["syntax"] == ":has-text("
    assert page.asked == [], "it asked the page about one that cannot work"


def test_every_playwright_only_form_is_caught():
    for sel in ("a:has(span)", "div:text('x')", "li:nth-match(a, 2)",
                "text=Save", "div >> a", "*:visible", "xpath=//a"):
        assert failure.playwright_only(sel), sel


def test_plain_css_is_left_alone():
    for sel in ("[role=dialog]", "a[href*='order' i]", "button.primary",
                "tbody tr:first-child", "#main > .row"):
        assert not failure.playwright_only(sel), sel


def test_a_selector_the_browser_rejects_keeps_its_category():
    """Rather than becoming nought matches, which reads as a page that
    has not drawn."""
    page = FakePage(bad_selectors={".a[["})
    out = failure.census(page, {"row": ".a[["})
    assert out[0]["evaluation"] == "invalid_css_selector"
    assert "matched" not in out[0]


def test_the_summary_says_a_selector_is_the_wrong_dialect():
    said = " ".join(failure.summarize({"selectors": failure.census(
        FakePage(), {"receipt_button": "button:has-text('View')"})}))
    assert "Playwright's dialect" in said
    assert "syntax error inside the page" in said


# -- bug four, the hidden copy a framework leaves in the markup ----------------

def test_a_match_that_is_not_on_screen_is_reported_as_such():
    """Bootstrap leaves an empty modal in the markup with role=dialog on
    it from page load, nought by nought. Every piece of code looking for
    the receipt found that one, and the PDF came out at 989 bytes."""
    page = FakePage(nodes={"[role=dialog]": [
        node(on_screen=False, **{"class": "modal fade"}),
    ]})
    out = failure.census(page, {"receipt_area": "[role=dialog]"})
    assert out[0]["matched"] == 1
    assert out[0]["visible"] == 0
    assert out[0]["nodes"][0]["signal_classes"] == ["fade", "modal"]


def test_the_summary_names_the_hidden_copy_problem():
    page = FakePage(nodes={"[role=dialog]": [
        node(on_screen=False, box=[0, 0], display="none",
             **{"class": "modal fade"})]})
    said = " ".join(failure.summarize({
        "selectors": failure.census(page, {"receipt_area": "[role=dialog]"}),
        "page": failure.page_state(page)}))
    assert "none of them were on screen" in said
    assert "hidden copy of a dialog" in said
    assert "fade.modal" in said


def test_something_hidden_that_is_not_a_dialog_is_not_called_one():
    """An input of type hidden matching nothing visible is an input of
    type hidden. Saying otherwise every time is how a file stops being
    read."""
    page = FakePage(nodes={"input[type=hidden]": [node(on_screen=False,
                                                       tag="input")]})
    said = " ".join(failure.summarize({"selectors": failure.census(
        page, {"hidden_input": "input[type=hidden]"})}))
    assert "none of them were on screen" in said
    assert "hidden copy of a dialog" not in said


# -- bug two, the rows had not been drawn yet ---------------------------------

def test_nothing_matched_is_reported_as_the_two_things_it_could_be():
    page = FakePage(nodes={})
    said = " ".join(failure.summarize({
        "selectors": failure.census(page, {"order_row": ".row"}),
        "page": failure.page_state(page)}))
    assert "matched nothing" in said
    assert "had not drawn yet" in said


# -- bug six, the page was hidden and never put back --------------------------

def test_a_page_with_nothing_visible_says_what_that_means():
    """Saving a receipt sets display none on everything except the
    receipt, and nothing puts it back, so the first document of a run
    worked and every one after it failed."""
    page = FakePage(
        nodes={".row": [node(on_screen=False), node(on_screen=False)],
               "[role=tab]": [node(on_screen=False)]},
        state={"largest_visible": None, "visible_elements": 0})
    said = " ".join(failure.summarize({
        "selectors": failure.census(page, {"order_row": ".row",
                                           "tab": "[role=tab]"}),
        "page": failure.page_state(page)}))
    assert "Nothing on the page was visible at all" in said
    assert "did not put it back" in said
    assert "the one before it" in said


# -- bug five, the open dialog locked the page --------------------------------

def test_a_locked_page_is_called_out_as_the_reason_a_render_is_blank():
    page = FakePage(state={"body_overflow": "hidden"})
    said = " ".join(failure.summarize({"page": failure.page_state(page),
                                       "selectors": []}))
    assert "Scrolling is locked" in said
    assert "one blank screen" in said


# -- the postmortem, for a document that rendered to nothing ------------------

def test_a_block_of_no_size_is_stated_outright():
    page = FakePage(kept={"tag": "div", "class": "modal fade", "box": [0, 0],
                          "scroll_height": 0, "display": "none",
                          "position": "fixed", "text_len": 281})
    pm = failure.postmortem(page, "[role=dialog]", saved_bytes=989,
                            expected_bytes=3000)
    assert pm["saved_bytes"] == 989
    assert pm["kept"]["box"] == [0, 0]
    assert pm["kept"]["signal_classes"] == ["fade", "modal"]
    said = " ".join(failure.summarize({"extra": {"postmortem": pm}}))
    assert "nought by nought" in said


def test_a_postmortem_without_a_selector_still_reports_the_size():
    pm = failure.postmortem(FakePage(), "", saved_bytes=989)
    assert pm["saved_bytes"] == 989
    assert "kept" not in pm


def test_a_postmortem_refuses_a_playwright_selector_too():
    page = FakePage()
    failure.postmortem(page, "div:has-text('Total')", saved_bytes=989)
    assert page.asked == []


# -- bug eight, the parser's own assumption ------------------------------------

def test_the_parser_says_why_nothing_was_accepted():
    """A till prints line items with no currency sign, which the parser
    assumed there would be. Counting what was thrown away and why says
    that, and says it without a single line of the receipt."""
    counts = failure.parser_counts(candidates=12, accepted=0,
                                   rejected={"missing currency symbol": 12})
    said = " ".join(failure.summarize({"extra": {"parser": counts}}))
    assert "12 line(s) looked like items and none were accepted" in said
    assert "missing currency symbol" in said


def test_a_parser_that_worked_says_nothing():
    counts = failure.parser_counts(candidates=12, accepted=12)
    assert failure.summarize({"extra": {"parser": counts}}) == []


def test_parser_counts_are_bounded_and_never_text():
    counts = failure.parser_counts(candidates="lots", accepted=-5,
                                   rejected={"a reason": "many"})
    assert counts["candidates"] == 0
    assert counts["accepted"] == 0
    assert counts["rejected"]["a reason"] == 0


# -- the session ended ---------------------------------------------------------

def test_a_password_field_says_the_session_probably_ended():
    page = FakePage(state={"counts": {"passwords": 1, "buttons": 2}})
    said = " ".join(failure.summarize({"page": failure.page_state(page),
                                       "selectors": []}))
    assert "session" in said


# -- what may leave at all -----------------------------------------------------

def test_a_tag_nobody_has_heard_of_becomes_other():
    """A custom element can be named after anything, a company or a
    person included."""
    page = FakePage(nodes={".x": [node(tag="acme-customer-panel")]})
    out = failure.census(page, {"x": ".x"})
    assert out[0]["nodes"][0]["tag"] == "other"


def test_a_class_that_is_not_a_layout_word_does_not_come_out():
    """Whole tokens only. A compound class does not get to contribute
    one of its halves."""
    page = FakePage(nodes={".x": [node(**{"class": "customer-4821-panel"})]})
    out = failure.census(page, {"x": ".x"})
    assert out[0]["nodes"][0]["signal_classes"] == []


def test_an_id_becomes_a_yes_or_no():
    page = FakePage(nodes={".x": [node(has_id=True)]})
    out = failure.census(page, {"x": ".x"})
    assert out[0]["nodes"][0]["has_id"] is True
    assert "id" not in out[0]["nodes"][0]


def test_a_role_outside_the_aria_vocabulary_becomes_other():
    page = FakePage(nodes={".x": [node(role="customer-row")]})
    out = failure.census(page, {"x": ".x"})
    assert out[0]["nodes"][0]["role"] == "other"


def test_an_exception_becomes_one_word():
    for err, word in (
            (RuntimeError("Timeout 30000ms exceeded waiting for x"), "timeout"),
            (RuntimeError("net::ERR_ABORTED at https://bank/x?t=secret"), "navigation"),
            (RuntimeError("Execution context was destroyed"), "detached"),
            (RuntimeError("'.a[[' is not a valid selector"), "selector"),
            (RuntimeError("something nobody planned for"), "unknown")):
        assert failure.error_kind(err) == word, err


def test_a_step_built_from_a_page_is_refused():
    """A step is written in the source. Anything that looks like it came
    from a page does not get to be one."""
    assert failure._step("open the receipt") == "open the receipt"
    assert failure._step("open https://bank.example/x?t=1") == "unnamed step"
    assert failure._step("Receipt for Alex Morgan") == "unnamed step"
    assert failure._step("open the saved PDF") == "unnamed step"
    assert failure._step("") == "unnamed step"


# -- the file ------------------------------------------------------------------

def test_the_file_is_written_where_everything_else_is(tmp_path):
    page = FakePage(nodes={"[role=dialog]": [node(on_screen=False)]})
    out = failure.write_failure(
        tmp_path, command="pilot", step="save the receipt",
        reason="the document would not render", page=page,
        selectors={"receipt_area": "[role=dialog]"},
        provider="Testco", version="0.30.2", say=lambda *a: None)
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert got["kind"] == "paperpull-failure"
    assert got["schema"] == 2
    assert got["provider"] == "Testco"
    assert got["step"] == "save the receipt"
    assert got["selectors"][0]["visible"] == 0
    assert "no text from the page" in got["note"]


def test_the_filename_says_which_command_and_when(tmp_path):
    out = failure.write_failure(tmp_path, command="pilot", step="x",
                                reason="y", say=lambda *a: None)
    assert Path(out).name.startswith("failure-pilot-")
    assert Path(out).name.endswith(".json")


def test_two_failures_in_one_run_do_not_overwrite_each_other(tmp_path):
    import time as _t
    a = failure.write_failure(tmp_path, command="pilot", step="one",
                              reason="r", say=lambda *a: None)
    _t.sleep(1.05)
    b = failure.write_failure(tmp_path, command="pilot", step="two",
                              reason="r", say=lambda *a: None)
    assert a != b
    assert len(list(Path(tmp_path).glob("failure-*.json"))) == 2


# -- it may never make things worse -------------------------------------------

def test_a_page_that_raises_on_everything_still_writes_a_file(tmp_path):
    """It runs when something has already gone wrong. A diagnostic that
    fails in the middle of a failure costs the round it was meant to
    save."""
    class Hostile:
        def evaluate(self, *a, **k):
            raise RuntimeError("execution context destroyed")

    out = failure.write_failure(tmp_path, command="pilot", step="x",
                                reason="r", page=Hostile(),
                                selectors={"a": ".x"}, say=lambda *a: None)
    assert out, "it gave up rather than writing what it could"
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert got["page"]["evaluation"] == "detached"
    assert got["selectors"][0]["evaluation"] == "detached"


def test_a_directory_that_cannot_be_written_returns_none_rather_than_raising():
    assert failure.write_failure("\x00 not a path", command="p", step="s",
                                 reason="r", say=lambda *a: None) is None


def test_selectors_that_are_not_a_dictionary_are_ignored():
    assert failure.census(FakePage(), None) == []
    assert failure.census(FakePage(), []) == []
    assert failure.census(FakePage(), {}) == []


def test_watching_for_page_errors_never_raises():
    class Hostile:
        def evaluate(self, *a, **k):
            raise RuntimeError("no")
    failure.watch_errors(Hostile())


def test_summarizing_something_that_is_not_a_report_is_empty():
    assert failure.summarize(None) == []
    assert failure.summarize("nonsense") == []
    assert failure.summarize({}) == []


def test_a_census_of_four_hundred_selectors_is_cut():
    big = {"sel%d" % i: ".c%d" % i for i in range(400)}
    assert len(failure.census(FakePage(), big)) <= 40


def test_a_census_that_goes_wrong_reports_a_category_not_a_crash():
    class Broken(FakePage):
        def _one(self, name, sel):
            raise RuntimeError("Execution context was destroyed")

    out = failure.census(Broken(), {"x": ".x"})
    assert out[0]["evaluation"] == "detached"


# -- the promises this module makes -------------------------------------------

def _names_in(path: Path) -> set:
    import io
    import tokenize
    out = set()
    with io.open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.NAME:
                out.add(tok.string)
    return out


def test_it_reads_no_cookie_and_no_storage():
    names = _names_in(Path(failure.__file__))
    for never in ("cookies", "storage_state", "add_cookies", "all_headers",
                  "localStorage", "sessionStorage"):
        assert never not in names, never


def test_it_takes_no_screenshot():
    """A picture cannot be read or edited by the person sending it, and
    the whole point is that they can."""
    assert "screenshot" not in _names_in(Path(failure.__file__))


def test_it_does_not_redact_because_it_does_not_collect():
    """The first version scrubbed what it gathered and eleven canaries
    came out of it. Nothing here is scrubbed, because nothing that would
    need scrubbing is taken."""
    assert "redact" not in _names_in(Path(failure.__file__))


def test_no_page_script_uses_a_playwright_selector():
    """This module of all modules."""
    for name in ("_CENSUS_JS", "_PAGE_STATE_JS", "_COUNT_ERRORS_JS"):
        code = "\n".join(ln.split("//")[0]
                         for ln in getattr(failure, name).splitlines())
        for bad in failure.PLAYWRIGHT_ONLY:
            assert bad not in code, "%s carries %s" % (name, bad)
