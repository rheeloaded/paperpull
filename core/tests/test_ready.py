"""The rules ready() keeps whatever the page does.

The waits themselves are proved in a browser in test_ready_live.py. These
are the promises that make it safe to put in a run against somebody's
bank, checked against a page that answers whatever the test tells it to.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import ready as R
from paperpull_core.journal import Journal, summarize


class Page:
    """Answers count questions from a script of values, one per ask."""

    def __init__(self, counts=(0,), url="https://example.test/list"):
        self.counts = list(counts)
        self.url = url
        self.asked = 0
        self.slept = 0

    def evaluate(self, js, arg=None):
        self.asked += 1
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    def wait_for_timeout(self, ms):
        self.slept += ms
        time.sleep(ms / 1000)

    def wait_for_load_state(self, state, timeout=None):
        return None


# -- additive only ------------------------------------------------------------

def test_a_function_of_your_own_is_refused_as_a_strategy():
    """A function of your own is where a reload or a back would get in,
    and undoing page state between guesses is the thing this was allowed
    to exist on condition of never doing."""
    with pytest.raises(TypeError):
        R.ready(Page(), [lambda page, ms, url: page.reload()],
                invariant=lambda p: True, budget_ms=100)


def test_a_strategy_cannot_be_built_from_outside_the_module():
    with pytest.raises(TypeError):
        R.Strategy("count_reached", lambda *a: True)


def test_no_strategy_here_calls_anything_that_changes_the_page():
    """Read off the source, so a strategy added later that clicks or
    navigates fails here before it reaches anybody's account."""
    source = Path(R.__file__).read_text(encoding="utf-8")
    body = source.split("# -- the strategies", 1)[1].split(
        "# -- invariants", 1)[0]
    for verb in (".click(", ".goto(", ".reload(", ".go_back(",
                 ".go_forward(", ".fill(", ".press(", ".check(",
                 ".select_option(", ".dispatch_event(", "restore("):
        assert verb not in body, "a strategy calls %s" % verb


# -- the invariant decides ----------------------------------------------------

def test_an_invariant_is_required():
    with pytest.raises(TypeError):
        R.ready(Page(), [R.network_idle()], invariant=None, budget_ms=100)


def test_a_strategy_that_finished_has_not_succeeded_on_its_own():
    """network_idle came back, and the rows are still not there."""
    got = R.ready(Page(), [R.network_idle()], invariant=lambda p: False,
                  budget_ms=100)
    assert not got.ready
    assert [(a.strategy, a.outcome) for a in got.attempts] == [
        ("network_idle", "not_satisfied")]


def test_a_page_that_is_already_ready_asks_one_question_and_waits_for_none():
    page = Page(counts=(3,))
    got = R.ready(page, [R.count_settles(".row"), R.network_idle()],
                  invariant=R.has(".row", 3), budget_ms=10000)
    assert got.winner == "already"
    assert page.asked == 1 and page.slept == 0


def test_an_invariant_that_throws_is_a_no_not_a_crash():
    def broken(page):
        raise RuntimeError("the page went away")
    got = R.ready(Page(), [R.network_idle()], invariant=broken,
                  budget_ms=100)
    assert not got.ready
    assert got.attempts[0].outcome == "not_satisfied"


def test_a_page_that_came_right_without_any_strategy_is_late_not_already():
    """"already" would tell the maintainer no wait was needed, which is
    the opposite of what happened."""
    answers = iter([False, False, True])
    got = R.ready(Page(), [R.network_idle()],
                  invariant=lambda p: next(answers), budget_ms=100)
    assert got.ready and got.winner == "late"


def test_an_invariant_in_playwrights_dialect_is_refused_when_written():
    """The one mistake that has been shipped twice fails in the
    maintainer's own tests, not on a tester's machine."""
    with pytest.raises(ValueError):
        R.has("button:has-text('View Receipt')")


# -- the count strategies -----------------------------------------------------

def test_a_count_that_is_still_nothing_is_not_settled():
    """An empty list that has not started drawing is perfectly still,
    and settling on it read Costco's list as empty."""
    page = Page(counts=(0,))
    got = R.ready(page, [R.count_settles(".row", quiet_ms=200)],
                  invariant=lambda p: False, budget_ms=400)
    assert got.attempts[0].outcome == "timed_out"


def test_a_count_that_moved_and_stopped_is_settled():
    page = Page(counts=(0, 1, 3, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6))
    got = R.ready(page, [R.count_settles(".row", quiet_ms=100)],
                  invariant=lambda p: p.counts[0] == 6, budget_ms=5000)
    assert got.ready and got.winner == "count_settled"


def test_the_address_is_compared_with_what_it_was_when_waiting_began():
    urls = iter(["https://example.test/list",
                 "https://example.test/list",
                 "https://example.test/list#/receipt/1"])

    class Moving(Page):
        @property
        def url(self):
            return next(urls, "https://example.test/list#/receipt/1")

        @url.setter
        def url(self, value):
            pass
    page = Moving()
    got = R.ready(page, [R.url_changes()],
                  invariant=lambda p: p.url.endswith("/1"), budget_ms=5000)
    assert got.ready and got.winner == "url_changed"


# -- the journal --------------------------------------------------------------

def test_the_journal_entry_is_made_of_words_from_the_fixed_lists():
    j = Journal()
    R.ready(Page(counts=(0, 0, 3)), [R.network_idle(),
                                     R.count_reaches(".row", 3)],
            invariant=R.has(".row", 3), budget_ms=5000, journal=j,
            name="order rows")
    entry = j.report()["entries"][-1]
    assert entry["kind"] == "waited" and entry["name"] == "order rows"
    for a in entry["attempts"]:
        assert a["strategy"] in R.STRATEGIES
        assert a["outcome"] in R.OUTCOMES
    assert entry["winner"] == "count_reached"


def test_a_journal_that_fails_to_record_does_not_fail_the_wait():
    class Broken:
        def waited(self, *a):
            raise RuntimeError("disk full")
    got = R.ready(Page(counts=(3,)), [], invariant=R.has(".row", 3),
                  budget_ms=100, journal=Broken())
    assert got.ready


def test_a_run_that_went_fine_still_says_which_wait_it_needed():
    """The answer is most useful from the run that worked, since that is
    the one whose wait the next round should keep."""
    j = Journal()
    R.ready(Page(counts=(0, 3)), [R.count_reaches(".row", 3)],
            invariant=R.has(".row", 3), budget_ms=5000, journal=j,
            name="order rows")
    said = " ".join(summarize(j.report()))
    assert "\"order rows\" was ready after count_reached" in said


# -- the line in the run's output ---------------------------------------------

def test_a_run_that_worked_prints_which_wait_it_needed_once(caplog):
    """A Pilot that works writes no file, so the answer goes in the output
    testers already paste. Once, or a run of two hundred receipts buries
    everything else under it."""
    R._told.clear()
    caplog.set_level("INFO", logger="paperpull_core.ready")
    for _ in range(5):
        R.ready(Page(counts=(0, 3)), [R.count_reaches(".row", 3)],
                invariant=R.has(".row", 3), budget_ms=5000,
                name="order rows")
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ["Waited for order rows, ready after count_reached in "
                     + lines[0].split(" in ")[1]]
    assert lines[0].endswith("(tried count_reached)")


def test_a_page_that_was_already_ready_prints_nothing(caplog):
    R._told.clear()
    caplog.set_level("INFO", logger="paperpull_core.ready")
    R.ready(Page(counts=(3,)), [R.network_idle()],
            invariant=R.has(".row", 3), budget_ms=100, name="order rows")
    assert not caplog.records


def test_a_name_that_is_not_ours_is_not_printed(caplog):
    """The name is written in the app's source. One built from a page
    would be a page's words in pasted output, so anything that does not
    look like ours prints as a placeholder."""
    R._told.clear()
    caplog.set_level("INFO", logger="paperpull_core.ready")
    R.ready(Page(), [R.network_idle()], invariant=lambda p: False,
            budget_ms=50, name="Order 8421997301 for Jane")
    assert "8421997301" not in caplog.text and "Jane" not in caplog.text
    assert "Waited for unnamed step, never ready" in caplog.text
