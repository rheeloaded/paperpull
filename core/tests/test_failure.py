"""The failure diagnostic, measured against the bugs that caused it.

Costco went from a scaffold to a working provider through eight bugs,
and the estimate was nine to twelve tester rounds to fix them remotely
because each one hides the next. The claim this module makes is that a
census of the app's own selectors, taken at the moment of failure,
states most of them outright in one file.

The tests below are those eight bugs, replayed. Each one builds the page
state that bug produced and asks whether the file would have said so.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import failure


class FakePage:
    """A page that answers the three questions this module asks.

    `nodes` maps a selector to the list of node descriptions the browser
    would return, so a test writes the DOM it cares about and nothing
    else."""

    def __init__(self, nodes=None, url="https://bank.example/documents",
                 state=None, errors=None, bad_selectors=()):
        self.nodes = nodes or {}
        self.url = url
        self._state = state or {}
        self._errors = errors or []
        self._bad = set(bad_selectors)
        self.evaluated = []

    def evaluate(self, script, arg=None):
        self.evaluated.append(script[:40])
        if "__ppErrors" in script and "addEventListener" not in script:
            return self._errors
        if "window.__ppErrors = []" in script:
            return "installed"
        if "for (const [name, sel] of selectors)" in script:
            return [self._census_one(name, sel) for name, sel in arg]
        if "largest_visible" in script:
            base = {"title": "Bank", "ready": "complete",
                    "html_overflow": "auto", "body_overflow": "auto",
                    "body_scroll_height": 2000, "body_text_len": 3000,
                    "counts": {"buttons": 12, "links": 40, "dialogs": 0,
                               "iframes": 0, "inputs": 3, "passwords": 0},
                    "largest_visible": {"tag": "main", "class": "",
                                        "text_len": 3000},
                    "anything_visible": True}
            base.update(self._state)
            return base
        if "scroll_height" in script:
            return self._state.get("kept")
        return None

    def _census_one(self, name, sel):
        if sel in self._bad:
            raise_msg = "Failed to execute 'querySelectorAll'"
            return {"name": name, "selector": sel, "error": raise_msg}
        found = self.nodes.get(sel, [])
        return {"name": name, "selector": sel, "matched": len(found),
                "visible": sum(1 for n in found if n.get("on_screen")),
                "nodes": found[:5]}


def node(on_screen=True, **kw):
    n = {"tag": "div", "class": "", "id": "", "role": "", "testid": "",
         "box": [600, 400], "display": "block", "visibility": "visible",
         "text_len": 500, "on_screen": on_screen}
    n.update(kw)
    return n


# -- bug one, a selector the browser cannot parse ------------------------------

def test_a_playwright_selector_is_named_without_asking_the_page():
    """It can never work inside the page, so the answer needs no page.
    This one was silent for a whole build, and every list read empty."""
    sel = "button:has-text('View Receipt')"
    assert failure.playwright_only(sel) == ":has-text("
    out = failure.census(FakePage(), {"receipt_button": sel})
    assert len(out) == 1
    assert "Playwright's dialect" in out[0]["error"]
    assert ":has-text(" in out[0]["error"]


def test_every_playwright_only_form_is_caught():
    for sel in ("a:has(span)", "div:text('x')", "li:nth-match(a, 2)",
                "text=Save", "div >> a", "*:visible"):
        assert failure.playwright_only(sel), sel


def test_plain_css_is_left_alone():
    for sel in ("[role=dialog]", "a[href*='order' i]", "button.primary",
                "tbody tr:first-child", "#main > .row"):
        assert not failure.playwright_only(sel), sel


def test_a_bad_selector_never_reaches_the_page():
    page = FakePage()
    failure.census(page, {"x": "button:has-text('Go')"})
    assert page.evaluated == [], "it asked the page about a selector that cannot work"


def test_the_summary_says_a_selector_cannot_work():
    report = {"selectors": failure.census(
        FakePage(), {"receipt_button": "button:has-text('View')"})}
    said = " ".join(failure.summarize(report))
    assert "cannot work as written" in said


# -- bug four, the hidden copy a framework leaves in the markup ----------------

def test_a_match_that_is_not_on_screen_is_reported_as_such():
    """Bootstrap leaves an empty modal in the markup with role=dialog on
    it from page load, nought by nought. Every piece of code looking for
    the receipt found that one, and the PDF came out at 989 bytes."""
    page = FakePage(nodes={"[role=dialog]": [
        node(on_screen=False, tag="div", **{"class": "modal fade"},
             box=[0, 0], display="none", text_len=281)]})
    out = failure.census(page, {"receipt_area": "[role=dialog]"})
    assert out[0]["matched"] == 1
    assert out[0]["visible"] == 0
    assert out[0]["nodes"][0]["class"] == "modal fade"


def test_the_summary_names_the_hidden_copy_problem():
    page = FakePage(nodes={"[role=dialog]": [node(on_screen=False, box=[0, 0])]})
    report = {"selectors": failure.census(page, {"receipt_area": "[role=dialog]"}),
              "page": failure.page_state(page)}
    said = " ".join(failure.summarize(report))
    assert "none of them were on screen" in said
    assert "hidden copy" in said


# -- bug two, the rows had not been drawn yet ---------------------------------

def test_nothing_matched_is_reported_as_the_two_things_it_could_be():
    page = FakePage(nodes={})
    report = {"selectors": failure.census(page, {"order_row": ".row"}),
              "page": failure.page_state(page)}
    said = " ".join(failure.summarize(report))
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
        state={"anything_visible": False, "largest_visible": None})
    report = {"selectors": failure.census(page, {"order_row": ".row",
                                                 "tab": "[role=tab]"}),
              "page": failure.page_state(page)}
    said = " ".join(failure.summarize(report))
    assert "Nothing on the page was visible at all" in said
    assert "did not put it back" in said
    assert "the one before it" in said


# -- bug five, the open dialog locked the page --------------------------------

def test_a_locked_page_is_called_out_as_the_reason_a_render_is_blank():
    page = FakePage(state={"body_overflow": "hidden"})
    report = {"page": failure.page_state(page), "selectors": []}
    said = " ".join(failure.summarize(report))
    assert "Scrolling is locked" in said
    assert "one blank screen" in said


# -- the postmortem, for a document that rendered to nothing ------------------

def test_a_block_of_no_size_is_stated_outright():
    page = FakePage(state={"kept": {"tag": "div", "class": "modal fade",
                                    "box": [0, 0], "scroll_height": 0,
                                    "display": "none", "position": "fixed",
                                    "text_len": 281}})
    pm = failure.postmortem(page, "[role=dialog]", saved_bytes=989,
                            expected_bytes=3000)
    assert pm["saved_bytes"] == 989
    assert pm["kept"]["box"] == [0, 0]
    said = " ".join(failure.summarize({"extra": {"postmortem": pm}}))
    assert "nought by nought" in said


def test_a_postmortem_without_a_selector_still_reports_the_size():
    pm = failure.postmortem(FakePage(), "", saved_bytes=989)
    assert pm["saved_bytes"] == 989
    assert "kept" not in pm


# -- bug eight, what the text actually looked like -----------------------------

def test_the_text_it_was_reading_is_quoted_with_the_numbers_gone():
    """A till prints line items with no currency sign, which the parser
    assumed there would be. No amount of watching a person shows that.
    The lines themselves do, and they are the one thing worth quoting."""
    lines = failure.quote("E 933402 DORITOS 30Z 7.29 3\nSUBTOTAL 49.06\n")
    assert lines[0].startswith("E ######")
    assert "DORITOS" in lines[0]
    assert "7.29" not in lines[0] and "933402" not in lines[0]


def test_quoting_keeps_the_shape_and_drops_the_values():
    lines = failure.quote("Member 111962277349\nTotal $50.59\npat@example.com")
    joined = " ".join(lines)
    assert "Member" in joined
    assert "111962277349" not in joined
    assert "50.59" not in joined
    assert "pat@example.com" not in joined


def test_quoting_nothing_is_not_an_error():
    assert failure.quote("") == []
    assert failure.quote(None) == []


# -- the session ended ---------------------------------------------------------

def test_a_password_field_says_the_session_probably_ended():
    page = FakePage(state={"counts": {"passwords": 1, "buttons": 2, "links": 1,
                                      "dialogs": 0, "iframes": 0, "inputs": 3}})
    said = " ".join(failure.summarize({"page": failure.page_state(page),
                                       "selectors": []}))
    assert "session" in said


# -- the file ------------------------------------------------------------------

def test_the_file_is_written_where_everything_else_is(tmp_path):
    page = FakePage(nodes={"[role=dialog]": [node(on_screen=False)]})
    out = failure.write_failure(
        tmp_path, command="pilot", step="save the receipt",
        reason="the PDF came out at 989 bytes", page=page,
        selectors={"receipt_area": "[role=dialog]"},
        provider="Testco", version="0.30.2", say=lambda *a: None)
    assert out
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert got["kind"] == "paperpull-failure"
    assert got["provider"] == "Testco"
    assert got["step"] == "save the receipt"
    assert got["selectors"][0]["visible"] == 0
    assert "no keystroke" in got["note"]


def test_the_filename_says_which_command_and_when(tmp_path):
    out = failure.write_failure(tmp_path, command="Run All", step="x",
                                reason="y", say=lambda *a: None)
    name = Path(out).name
    assert name.startswith("failure-run-all-")
    assert name.endswith(".json")


def test_two_failures_in_one_run_do_not_overwrite_each_other(tmp_path):
    import time as _t
    a = failure.write_failure(tmp_path, command="pilot", step="one",
                              reason="r", say=lambda *a: None)
    _t.sleep(1.05)
    b = failure.write_failure(tmp_path, command="pilot", step="two",
                              reason="r", say=lambda *a: None)
    assert a != b
    assert len(list(Path(tmp_path).glob("failure-*.json"))) == 2


def test_the_reason_goes_through_redaction(tmp_path):
    out = failure.write_failure(
        tmp_path, command="pilot", step="x",
        reason="could not open https://bank.example/doc?token=abc123secret",
        say=lambda *a: None)
    got = Path(out).read_text(encoding="utf-8")
    assert "abc123secret" not in got


def test_the_log_tail_is_kept_and_cut(tmp_path):
    out = failure.write_failure(tmp_path, command="pilot", step="x", reason="r",
                                log_lines=["line %d" % i for i in range(200)],
                                say=lambda *a: None)
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert len(got["log_tail"]) == 40
    assert got["log_tail"][-1] == "line 199"


# -- it may never make things worse -------------------------------------------

def test_a_page_that_raises_on_everything_still_writes_a_file(tmp_path):
    """It runs when something has already gone wrong. A diagnostic that
    fails in the middle of a failure costs the round it was meant to
    save."""
    class Hostile:
        @property
        def url(self):
            raise RuntimeError("detached")

        def evaluate(self, *a, **k):
            raise RuntimeError("execution context destroyed")

    out = failure.write_failure(tmp_path, command="pilot", step="x",
                                reason="r", page=Hostile(),
                                selectors={"a": ".x"}, say=lambda *a: None)
    assert out, "it gave up rather than writing what it could"
    got = json.loads(Path(out).read_text(encoding="utf-8"))
    assert got["page"]["url"] == ""


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


def test_a_census_of_four_hundred_selectors_is_cut(tmp_path):
    big = {"sel%d" % i: ".c%d" % i for i in range(400)}
    out = failure.census(FakePage(), big)
    assert len(out) <= 40


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
    names = _names_in(Path(failure.__file__))
    assert "screenshot" not in names


def test_no_page_script_uses_a_playwright_selector():
    """This module of all modules."""
    for name in ("_CENSUS_JS", "_PAGE_STATE_JS", "_COLLECT_ERRORS_JS"):
        code = "\n".join(ln.split("//")[0]
                         for ln in getattr(failure, name).splitlines())
        for bad in failure.PLAYWRIGHT_ONLY:
            assert bad not in code, "%s carries %s" % (name, bad)
