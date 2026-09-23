"""The journal, measured against the bugs a census cannot see.

A census says what the page looked like when a run gave up. Two of the
eight Costco bugs are invisible to it, because they are about what the
app did rather than what the page was.

Bug seven counted one collection and acted on the nth of another, which
from outside reads exactly like a page that did not load. Bug six hid
the page while saving a document and never put it back, so the first
document of a run worked and every one after it failed, and by the time
the run gave up there was nothing left on screen to explain why.

Both are recorded here as they happen.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import failure
from paperpull_core.journal import Journal, _route_change, summarize


class FakePage:
    """Counts per selector, and an address that can be changed."""

    def __init__(self, counts=None, url="https://bank.example/list",
                 overflow="auto", ready="complete"):
        self.counts = counts or {}
        self.url = url
        self.overflow = overflow
        self.ready = ready
        self.asked = 0

    def evaluate(self, script, arg=None):
        self.asked += 1
        out = {}
        for name, _sel in (arg or []):
            out[name] = list(self.counts.get(name, (0, 0)))
        out["__page"] = ["auto", self.overflow, 2000, self.ready]
        return out


SELECTORS = {"order_row": ".row", "receipt_area": "[role=dialog]"}


def a_journal(page=None, **kw):
    return Journal(page or FakePage(), SELECTORS,
                   watch=("order_row", "receipt_area"), **kw)


# -- bug seven, two collections counted differently ---------------------------

def test_choosing_from_two_collections_is_said_outright():
    """Counting `button, [role=button], a` and then pressing the nth
    `button` is a bug that took two live runs to find, with a browser in
    front of me, because it presents as a page that did not load."""
    j = a_journal()
    j.chose("receipt_button", "rows on the page", candidates=5, ordinal=1)
    j.chose("receipt_button", "view receipt buttons", candidates=1, ordinal=1)
    said = " ".join(summarize(j.report()))
    assert "more than one collection" in said
    assert "rows on the page had 5" in said
    assert "view receipt buttons had 1" in said


def test_one_collection_used_consistently_says_nothing():
    j = a_journal()
    for n in range(3):
        j.chose("receipt_button", "view receipt buttons", candidates=5,
                ordinal=n)
    assert not any("more than one collection" in s for s in summarize(j.report()))


def test_reaching_past_the_end_of_a_collection_is_said():
    j = a_journal()
    j.chose("receipt_button", "view receipt buttons", candidates=3, ordinal=3)
    said = " ".join(summarize(j.report()))
    assert "took item 3 of 3, which is past the end" in said


# -- bug six, the page hidden and never put back ------------------------------

def test_a_list_that_stops_being_visible_between_checkpoints_is_said():
    """It is still in the document, so a census at the end finds it and
    reports it present. Only the pair of checkpoints shows it went."""
    page = FakePage(counts={"order_row": (5, 5)})
    j = a_journal(page)
    j.checkpoint("the list is open")
    page.counts["order_row"] = (5, 0)          # saving one hid the page
    j.checkpoint("back for the second")
    said = " ".join(summarize(j.report()))
    assert "stopped being visible while still being there" in said
    assert "did not put it back" in said


def test_a_list_that_was_never_there_is_not_reported_as_hidden():
    page = FakePage(counts={"order_row": (0, 0)})
    j = a_journal(page)
    j.checkpoint("the list is open")
    j.checkpoint("back for the second")
    assert not any("stopped being visible" in s for s in summarize(j.report()))


# -- bug three, a hash change loads nothing -----------------------------------

def test_a_hash_only_change_is_named_as_one():
    page = FakePage(url="https://bank.example/app#/list")
    j = a_journal(page)
    j.checkpoint("the list is open")
    page.url = "https://bank.example/app#/order/1"
    j.checkpoint("back to the list")
    said = " ".join(summarize(j.report()))
    assert "only the part after the # changed" in said
    assert "has to be asked for" in said


def test_every_part_of_an_address_is_told_apart():
    same = "https://bank.example/a?b=1#c"
    assert _route_change(same, same) == "same"
    assert _route_change(same, "https://bank.example/a?b=1#d") == "hash"
    assert _route_change(same, "https://bank.example/a?b=2#c") == "query"
    assert _route_change(same, "https://bank.example/z?b=1#c") == "path"
    assert _route_change(same, "https://other.example/a?b=1#c") == "host"
    assert _route_change("", same) == "unknown"
    # A string that is not an address has no host, which is a bigger
    # change than a path and is reported as the bigger one.
    assert _route_change(same, "not a url at all") == "host"


def test_the_address_itself_never_comes_out():
    """The whole point of keeping it is to say how it changed."""
    page = FakePage(url="https://bank.example/order/SECRETORDER?t=SECRETTOKEN")
    j = a_journal(page)
    j.checkpoint("the list is open")
    page.url = "https://bank.example/order/SECRETORDER?t=SECRETTOKEN#x"
    j.checkpoint("the receipt is open")
    body = json.dumps(j.report())
    assert "SECRETORDER" not in body
    assert "SECRETTOKEN" not in body
    assert "bank.example" not in body
    assert '"route_change": "hash"' in body


# -- bug five, the page locked behind a dialog --------------------------------

def test_a_locked_page_at_a_checkpoint_is_said_once():
    page = FakePage(overflow="hidden")
    j = a_journal(page)
    j.checkpoint("about to render")
    j.checkpoint("rendered")
    said = [s for s in summarize(j.report()) if "scrolling was locked" in s]
    assert len(said) == 1
    assert "one blank screen" in said[0]


# -- the second document, which is a test case of its own ---------------------

def test_a_run_that_never_tried_a_second_document_says_so():
    """The research's point. One receipt working is not the same claim
    as the provider working, and a file that does not separate them
    invites the wrong conclusion."""
    j = a_journal()
    j.op("open_item", "open the receipt", ordinal=0)
    said = " ".join(summarize(j.report()))
    assert "No second document was attempted" in said


def test_a_run_that_did_try_a_second_does_not_say_that():
    j = a_journal()
    j.op("open_item", "open the receipt", ordinal=0)
    j.op("next_item", "move to the next one", ordinal=1)
    assert not any("No second document" in s for s in summarize(j.report()))


# -- what may be written at all -----------------------------------------------

def test_a_phase_outside_the_list_becomes_other():
    j = a_journal()
    j.op("whatever the page said", "open the receipt")
    assert j.entries[0]["phase"] == "other"


def test_an_operation_that_looks_like_page_text_is_refused():
    j = a_journal()
    j.op("open_item", "Receipt for Alex Morgan")
    assert j.entries[0]["operation"] == "unnamed step"


def test_a_fact_that_is_not_a_count_or_a_word_we_wrote_is_dropped():
    j = a_journal()
    j.op("parse", "read the lines", lines=12, ok=True,
         first_line="E 933402 DORITOS 30Z 7.29 3")
    facts = j.entries[0]["facts"]
    assert facts["lines"] == 12
    assert facts["ok"] is True
    assert facts["first_line"] is None


def test_an_exception_in_a_result_becomes_one_word():
    j = a_journal()
    j.result("it would not open", error=RuntimeError(
        "Timeout 30000ms exceeded waiting for https://bank/secret"))
    assert j.entries[0]["error"] == "timeout"
    assert "bank" not in json.dumps(j.report())


def test_a_selector_in_the_wrong_dialect_is_never_sent_to_the_page():
    page = FakePage()
    j = Journal(page, {"bad": "button:has-text('x')", "good": ".row"},
                watch=("bad", "good"))
    j.checkpoint("the list is open")
    assert list(j.entries[0]["watching"]) == ["good"]


# -- it may never make a working run fail -------------------------------------

def test_a_page_that_raises_does_not_stop_the_journal():
    class Hostile:
        url = "https://bank.example/x"

        def evaluate(self, *a, **k):
            raise RuntimeError("Execution context was destroyed")

    j = Journal(Hostile(), SELECTORS, watch=("order_row",))
    entry = j.checkpoint("the list is open")
    assert entry["evaluation"] == "detached"


def test_a_journal_with_no_page_still_records_what_the_app_did():
    j = Journal(None)
    j.op("open_item", "open the receipt")
    j.chose("receipt_button", "view receipt buttons", candidates=2, ordinal=0)
    j.checkpoint("after")
    assert len(j.entries) == 3


def test_the_oldest_entries_go_when_it_fills_up():
    """A run that saves two hundred documents must not write a file
    nobody can open, and the question is almost always what happened
    last."""
    j = a_journal(limit=10)
    for n in range(50):
        j.op("open_item", "open the receipt", ordinal=n)
    report = j.report()
    assert len(report["entries"]) == 10
    assert report["dropped_oldest"] == 40
    assert report["entries"][-1]["ordinal"] == 49


def test_summarizing_something_that_is_not_a_journal_is_empty():
    assert summarize(None) == []
    assert summarize({}) == []
    assert summarize({"entries": []}) == []


# -- it lands in the failure file ---------------------------------------------

def test_the_journal_goes_into_the_failure_file(tmp_path):
    page = FakePage(counts={"order_row": (5, 5)})
    j = a_journal(page)
    j.checkpoint("the list is open")
    j.chose("receipt_button", "rows on the page", candidates=5, ordinal=1)
    j.chose("receipt_button", "view receipt buttons", candidates=1, ordinal=1)
    page.counts["order_row"] = (5, 0)
    j.checkpoint("back for the second")

    out = failure.write_failure(
        tmp_path, command="pilot", step="open the receipt",
        reason="it would not open twice", journal=j,
        provider="Testco", say=lambda *a: None)
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    assert report["journal"]["entries"]

    said = " ".join(failure.summarize(report))
    assert "more than one collection" in said, "the census cannot see this"
    assert "stopped being visible while still being there" in said


def test_a_failure_file_without_a_journal_is_unchanged(tmp_path):
    out = failure.write_failure(tmp_path, command="pilot", step="x",
                                reason="y", say=lambda *a: None)
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    assert "journal" not in report
    assert failure.summarize(report) == []


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
    import paperpull_core.journal as mod
    names = _names_in(Path(mod.__file__))
    for never in ("cookies", "storage_state", "add_cookies", "all_headers",
                  "localStorage", "sessionStorage", "screenshot"):
        assert never not in names, never


def test_it_reads_no_text_from_the_page():
    """innerText is the one call that would undo all of this."""
    import io
    import paperpull_core.journal as mod
    src = io.open(mod.__file__, encoding="utf-8").read()
    code = "\n".join(ln.split("//")[0] for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "innerText" not in code
    assert "textContent" not in code
