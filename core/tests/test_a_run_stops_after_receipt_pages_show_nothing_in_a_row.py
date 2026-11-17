"""A run stops after five receipt pages in a row, new to showing nothing,
show nothing (threads of 2026-11-16, item 3).

A receipt page that shows nothing is recorded as a failure the next run
asks for again (not_shown.tried_again), so during an outage, a rate limit
or a route change every purchase whose page shows nothing was opened on
every run, with no end. eBay's details pages have a daily cap and Best
Buy's Akamai protection blocks after too many requests, and in #225 that
was 244 Kroger purchases on every run.

What tells an outage from receipts that are truly missing is a page that
never showed nothing before and now does. So a page counts toward the
run's streak when its record, as read before this page is recorded, holds
no day before the run's day, and a Download again of a saved receipt
counts too. A page that showed nothing on an earlier day neither counts nor
resets the streak. Any save resets it. At the fifth the purchase is
recorded as before and the run stops, with exit code 0, a result line
that says stopped 1 and stop not_shown, and a failure file of its own.

These are the core cases (test-plan-next.md X1, X2, X3, X4, X7 and X8),
on a small stand-in run with a progress store on disk. Every name, number
and date is invented.
"""
import collections
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import browser, failure, listing, not_shown, pressing, run_reporting
from paperpull_core.models import IN_STORE, ONLINE, Purchase, State
from paperpull_core.run_reporting import ListNotRead, PREFIX, report_run_result, stop_reason
from paperpull_core.storage import JsonStore
from paperpull_core.words import shape_tree, words_for

D = "2026-11-17"
D1 = "2026-11-16"
D2 = "2026-11-15"
D_PLUS_1 = "2026-11-18"

STOP_WORDS = "receipt pages this run opened showed nothing"


@pytest.fixture(autouse=True)
def nobody_asked_yet(monkeypatch):
    monkeypatch.setattr(browser, "_NOBODY_ANSWERED", False)


def order(n: int, kind: str = ONLINE) -> Purchase:
    """ORDER-1001 is the newest."""
    day = 10 - (n - 1001)
    date = "2026-11-%02d" % day if day > 0 else "2026-10-%02d" % (31 + day)
    return Purchase(purchase_type=kind, purchase_date=date, order_number="ORDER-%d" % n,
                    total="$12.34", summary="Garden Hose",
                    receipt_url="https://receipts.example.invalid/r/ORDER-%d" % n)


class Run:
    """One run of a receipt app, as far as the core sees it."""

    def __init__(self, out: Path, day: str = D):
        out.mkdir(parents=True, exist_ok=True)
        self.out = out
        self.progress = JsonStore(out / "progress.json", out / "backups")
        self.progress.load()
        self.stats = collections.defaultdict(int)
        self.stats["new_files"] = []
        self.stats["started"] = day + "T09:00:00"
        self.stats["mode"] = "all"
        self.paths = SimpleNamespace(last_listing=out / "last-listing.json", root=out)
        self.args = SimpleNamespace()
        self.rows = []
        self.order_csv = SimpleNamespace(read_all=lambda: list(self.rows))
        self.failures = []
        self.calls = []

    def _record_state(self, purchase, state, notes="", extra=None):
        rec = dict(state=state.value, notes=notes)
        rec.update(extra or {})
        not_shown.let_go_on_save(self, purchase, state, rec)
        self.progress.update(purchase.key, rec)
        self.calls.append(("record", purchase.order_number, state.value))

    def _write_csv_rows(self, purchase, **kw):
        self.rows.append({"Order or Receipt Number": purchase.order_number,
                          "Purchase Type": purchase.purchase_type})

    def write_failure(self, step, reason, text="", postmortem=None, extra=None):
        self.failures.append({"step": step, "reason": reason, "extra": extra})
        self.calls.append(("failure", step))

    def given(self, n: int, kind: str = ONLINE, **rec):
        p = order(n, kind)
        self.progress.update(p.key, dict(p.to_dict(), **rec))
        return p

    def record(self, n: int, kind: str = ONLINE) -> dict:
        return self.progress.get(order(n, kind).key) or {}


def empty(run: Run, n: int, kind: str = ONLINE):
    """Purchase n's receipt page shows nothing."""
    return not_shown.tried_again(run, order(n, kind), "The receipt page showed nothing")


def saved(run: Run, n: int, kind: str = ONLINE):
    """Purchase n's receipt is saved."""
    run._record_state(order(n, kind), State.PDF_SAVED, notes="saved")


def empties(run: Run, numbers, kind: str = ONLINE):
    """Each in turn, until the stop. Answers the one the run stopped at, or
    None."""
    for n in numbers:
        try:
            assert empty(run, n, kind) is False
        except not_shown.NothingShown:
            return n
    return None


def streak(run: Run) -> int:
    return not_shown.streak(run)


# -- X1, the rule ----------------------------------------------------------------------


def test_five_new_in_a_row_stop_at_the_fifth(tmp_path, capsys):
    """X1.1. The fifth is recorded first, then the run stops. The sixth is
    never asked for."""
    run = Run(tmp_path)
    asked = []
    for n in range(1001, 1007):
        asked.append(n)
        try:
            empty(run, n)
        except not_shown.NothingShown as stop:
            assert isinstance(stop, SystemExit) and stop.code == 0
            assert not isinstance(stop, (pressing.Stop, ListNotRead))
            break
    assert asked == [1001, 1002, 1003, 1004, 1005]
    rec = run.record(1005)
    assert rec["state"] == State.FAILED.value and rec["notes"].endswith(not_shown.TRIED_AGAIN)
    assert rec[not_shown.DAYS_KEY] == [D]
    assert run.stats["failed"] == 5
    assert not run.rows, "no CSV row for any of them"
    assert STOP_WORDS in capsys.readouterr().out


def test_four_in_a_row_never_stop(tmp_path):
    """X1.2."""
    run = Run(tmp_path)
    assert empties(run, range(1001, 1005)) is None
    for n in range(1001, 1005):
        assert run.record(n)[not_shown.DAYS_KEY] == [D]
        assert run.record(n)["state"] == State.FAILED.value


def test_three_a_save_and_three_never_stop(tmp_path):
    """X1.3."""
    run = Run(tmp_path)
    assert empties(run, (1001, 1002, 1003)) is None
    saved(run, 1004)
    assert streak(run) == 0
    assert empties(run, (1005, 1006, 1007)) is None


def test_a_save_of_the_other_kind_resets_too(tmp_path):
    """X1.4. One streak for the run, since a site's request budget is the
    site's, not the kind's."""
    run = Run(tmp_path)
    assert empties(run, (1001, 1002, 1003)) is None
    saved(run, 1004, IN_STORE)
    assert empties(run, (1005, 1006, 1007, 1008)) is None


def test_known_pages_in_any_number_never_stop_and_are_recorded_as_before(tmp_path, capsys):
    """X1.5. Each says what 8b982c1d says for a record with one earlier day."""
    run = Run(tmp_path)
    for n in range(1001, 1011):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1])
    capsys.readouterr()
    assert empties(run, range(1001, 1011)) is None
    out = capsys.readouterr().out
    assert out.count("  The receipt page showed nothing, on 2 of 3 separate days. "
                     "It is tried again next run.\n") == 10, out
    assert STOP_WORDS not in out
    for n in range(1001, 1011):
        assert run.record(n)[not_shown.DAYS_KEY] == [D1, D]
        assert run.record(n)["state"] == State.FAILED.value


def test_a_known_page_on_its_third_day_after_a_save_is_set_aside_and_resets_nothing(tmp_path):
    """X1.6."""
    run = Run(tmp_path)
    run.given(1004, state=State.FAILED.value, not_shown_days=[D2, D1])
    assert empties(run, (1001, 1002)) is None
    saved(run, 1003)
    assert empties(run, (1004,)) is None
    rec = run.record(1004)
    assert rec["state"] == State.NO_RECEIPT_AVAILABLE.value and rec[not_shown.DAYS_KEY] == [D2, D1, D]
    assert len(run.rows) == 1 and run.stats["no_receipt"] == 1 and run.stats["manual_review"] == 1
    assert streak(run) == 0
    assert empties(run, range(1005, 1010)) == 1009


def test_known_pages_between_new_ones_neither_count_nor_reset(tmp_path):
    """X1.7. new, known, new, new, known, new, new, new stops at the fifth new."""
    run = Run(tmp_path)
    for n in (1002, 1005):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1])
    assert empties(run, range(1001, 1009)) == 1007
    assert not run.record(1008)
    for n in (1002, 1005):
        assert run.record(n)[not_shown.DAYS_KEY] == [D1, D]


def test_a_record_holding_only_this_day_is_new(tmp_path):
    """X1.8. An earlier run today."""
    run = Run(tmp_path)
    for n in range(1001, 1006):
        run.given(n, state=State.FAILED.value, not_shown_days=[D])
    assert empties(run, range(1001, 1007)) == 1005
    assert run.record(1005)[not_shown.DAYS_KEY] == [D]


def test_a_record_holding_an_earlier_day_and_this_one_is_known(tmp_path):
    """X1.9."""
    run = Run(tmp_path)
    for n in range(1001, 1007):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1, D])
    assert empties(run, range(1001, 1007)) is None


def test_download_again_of_saved_receipts_counts(tmp_path):
    """X1.10. Each keeps its saved copy, untouched."""
    run = Run(tmp_path)
    files = {}
    for n in range(1001, 1006):
        pdf = tmp_path / ("saved-%d.pdf" % n)
        pdf.write_bytes(b"%PDF-1.4 " + b"0" * 30000)
        files[n] = (pdf, pdf.read_bytes(), pdf.stat().st_mtime_ns)
        run.given(n, state=State.PDF_VERIFIED.value, downloaded_ok=True, pdf_path=str(pdf))
    assert empties(run, range(1001, 1007)) == 1005
    for n, (pdf, data, mtime) in files.items():
        rec = run.record(n)
        assert rec["downloaded_ok"] is True and rec["pdf_path"] == str(pdf)
        assert rec["notes"].endswith("the receipt saved before is kept")
        assert not_shown.DAYS_KEY not in rec
        assert pdf.read_bytes() == data and pdf.stat().st_mtime_ns == mtime


def test_each_run_keeps_its_own_streak(tmp_path):
    """X1.11. Two app objects in one process."""
    a, b = Run(tmp_path / "a"), Run(tmp_path / "b")
    assert empties(a, (1001, 1002, 1003)) is None
    assert empties(b, (1001, 1002, 1003)) is None
    assert empties(a, (1004,)) is None
    assert empties(b, (1004,)) is None
    assert (streak(a), streak(b)) == (4, 4)
    assert empties(a, (1005,)) == 1005
    assert streak(b) == 4


@pytest.mark.parametrize("state", [State.FAILED, State.NEEDS_MANUAL_REVIEW, State.RECEIPT_LOCATED,
                                   State.NO_RECEIPT_AVAILABLE, State.DISCOVERED],
                         ids=lambda s: s.value)
def test_only_a_save_resets_the_streak(tmp_path, state):
    """X1.12. A refused page, a page that would not open and a failed print
    each write some other state, and none of them resets it."""
    run = Run(tmp_path)
    assert empties(run, (1001, 1002)) is None
    run._record_state(order(1101), state, notes="something else")
    assert streak(run) == 2
    assert empties(run, (1003, 1004, 1005)) == 1005


def test_the_stop_comes_after_the_record_is_written_and_saved(tmp_path, capsys):
    """X1.13. The fifth is on disk, with a backup, before the stop's words."""
    run = Run(tmp_path)
    seen = []
    real_save = run.progress.save

    def save(*a, **kw):
        seen.append(("save", kw.get("backup", False)))
        return real_save(*a, **kw)
    run.progress.save = save
    assert empties(run, range(1001, 1007)) == 1005
    on_disk = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert on_disk[order(1005).key]["state"] == State.FAILED.value
    assert on_disk[order(1005).key][not_shown.DAYS_KEY] == [D]
    assert ("save", True) in seen
    assert any((tmp_path / "backups").iterdir()), "a backup beside it"
    recorded = run.calls.index(("record", "ORDER-1005", State.FAILED.value))
    assert recorded < run.calls.index(("failure", not_shown.STOP_STEP))
    out = capsys.readouterr().out
    assert out.index("The receipt page showed nothing, on 1 of 3") < out.index(STOP_WORDS)
    assert out.count(STOP_WORDS) == 1


def test_the_stop_writes_its_own_failure_file_with_counts(tmp_path):
    """X8.5. Two saved, three skipped as done, two known pages passed, then
    five new. The failure file of the run so far is set aside so the stop's
    is written."""
    run = Run(tmp_path)
    run.stats["failure_files"] = 1
    run.stats["skipped_completed"] = 3
    for n in (1003, 1004):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1])
    saved(run, 1001)
    saved(run, 1002)
    # A second file of the same purchase is still one purchase saved.
    saved(run, 1002)
    assert empties(run, range(1003, 1010)) == 1009
    assert len(run.failures) == 1
    got = run.failures[0]
    assert (got["step"], got["reason"]) == ("open the receipt",
                                            "receipt pages showed nothing in a row")
    assert got["extra"] == {"empty_pages_in_a_row": 5, "purchases_saved": 2,
                            "pages_that_showed_nothing_before": 2, "skipped_as_done": 3}


def test_the_facts_survive_the_word_list(tmp_path):
    """X8.1. Each fact name leaves as written, every value is a count."""
    run = Run(tmp_path)
    empties(run, range(1001, 1006))
    facts = run.failures[0]["extra"]
    assert len(facts) <= 20 and all(type(v) is int for v in facts.values())
    for provider in ("Target", "Kroger", "eBay", "Best Buy"):
        shaped = shape_tree(failure._only_safe(facts), words_for(provider), full_list=True)
        assert shaped == facts, (provider, shaped)


def test_the_facts_reach_a_real_failure_file(tmp_path):
    """X8.1 and X8.4. Written by the core's write_failure, as each app's
    does, the facts are in report["extra"] and no order number is."""
    run = Run(tmp_path)
    paths = []

    def write(step, reason, text="", postmortem=None, extra=None):
        paths.append(failure.write_failure(tmp_path / "Diagnostics", command="all", step=step,
                                           reason=reason, provider="Target", extra=extra,
                                           say=lambda *_a: None))
    run.write_failure = write
    empties(run, range(1001, 1006))
    text = Path(paths[0]).read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["extra"] == {"empty_pages_in_a_row": 5, "purchases_saved": 0,
                               "pages_that_showed_nothing_before": 0, "skipped_as_done": 0}
    assert (report["step"], report["reason"]) == ("open the receipt",
                                                  "receipt pages showed nothing in a row")
    assert "ORDER-10" not in text


# -- X2, adverse and malformed records -----------------------------------------------


@pytest.mark.parametrize("rec", [None, [1, 2], "a record", 7], ids=["none", "list", "text", "number"])
def test_a_record_that_is_not_a_dict_counts_as_none(tmp_path, rec):
    """X2.4."""
    run = Run(tmp_path)
    real_get = run.progress.get
    run.progress.get = lambda key, *a: rec if key.endswith("ORDER-1003") else real_get(key, *a)
    assert empties(run, range(1001, 1007)) == 1005


@pytest.mark.parametrize("started", ["yesterday", 17, None], ids=["word", "number", "none"])
def test_a_run_whose_start_cannot_be_read_counts_today(tmp_path, monkeypatch, started):
    """X2.5."""
    class Today(not_shown.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 17)
    monkeypatch.setattr(not_shown, "date", Today)
    run = Run(tmp_path)
    run.stats["started"] = started
    for n in (1001, 1002):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1])
    assert empties(run, range(1001, 1009)) == 1007
    assert run.record(1007)[not_shown.DAYS_KEY] == [D]


def test_a_run_that_crosses_midnight_keeps_its_day(tmp_path, monkeypatch):
    """X2.6. Every page is dated the run's day."""
    run = Run(tmp_path)
    run.stats["started"] = "2026-11-17T23:59:00"

    class Tomorrow(not_shown.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 18)
    assert empties(run, (1001, 1002)) is None
    monkeypatch.setattr(not_shown, "date", Tomorrow)
    assert empties(run, range(1003, 1007)) == 1005
    assert {run.record(n)[not_shown.DAYS_KEY][0] for n in range(1001, 1006)} == {D}


def test_an_older_versions_final_record_is_asked_again_and_counts(tmp_path):
    """X2.7. 0.44.0 wrote No Receipt Available with these words and no days."""
    run = Run(tmp_path)
    for n in range(1001, 1006):
        run.given(n, state=State.NO_RECEIPT_AVAILABLE.value, notes="Receipt page did not render")
        assert not_shown.asked_again(run.record(n))
    assert empties(run, range(1001, 1006)) == 1005


def test_records_brought_by_import_history(tmp_path):
    """X2.8."""
    run = Run(tmp_path)
    for n in (1001, 1002, 1003):
        run.given(n, state=State.FAILED.value, not_shown_days=[D1])
    for n in range(1004, 1009):
        run.given(n, state=State.FAILED.value)
    assert empties(run, range(1001, 1010)) == 1008


# -- X3, interrupted -------------------------------------------------------------------


def test_a_save_that_fails_inside_the_stop_does_not_stop_the_stop(tmp_path, capsys):
    """X3.3. The file open in another program."""
    run = Run(tmp_path)
    assert empties(run, range(1001, 1005)) is None

    real = run.progress.save

    def locked(*a, **kw):
        if kw.get("backup"):
            raise PermissionError("the file is open in another program")
        return real(*a, **kw)
    run.progress.save = locked
    try:
        empty(run, 1005)
    except not_shown.NothingShown:
        pass
    else:
        raise AssertionError("the run went on")
    finally:
        run.progress.save = real
    assert STOP_WORDS in capsys.readouterr().out
    assert len(run.failures) == 1


def test_a_failure_file_that_cannot_be_written_does_not_stop_the_stop(tmp_path):
    run = Run(tmp_path)

    def refused(*_a, **_kw):
        raise TypeError("write_failure() got an unexpected keyword argument 'extra'")
    run.write_failure = refused
    assert empties(run, range(1001, 1007)) == 1005


def test_ctrl_c_inside_the_stop_is_never_caught(tmp_path):
    """X3.2. The fifth is already on disk."""
    run = Run(tmp_path)

    def interrupted(*_a, **_kw):
        raise KeyboardInterrupt
    run.write_failure = interrupted
    assert empties(run, range(1001, 1005)) is None
    with pytest.raises(KeyboardInterrupt):
        empty(run, 1005)
    on_disk = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert on_disk[order(1005).key][not_shown.DAYS_KEY] == [D]


# -- X4, the runs after ----------------------------------------------------------------


def test_the_next_day_of_an_outage_counts_the_next_five(tmp_path):
    """X4.3. Yesterday's five are known and opened, then five more stop it,
    with ten pages opened."""
    first = Run(tmp_path)
    assert empties(first, range(1001, 1013)) == 1005
    run = Run(tmp_path, D_PLUS_1)
    assert empties(run, range(1001, 1013)) == 1010
    for n in range(1001, 1006):
        assert run.record(n)[not_shown.DAYS_KEY] == [D, D_PLUS_1]
    assert run.failures[0]["extra"] == {"empty_pages_in_a_row": 5, "purchases_saved": 0,
                                        "pages_that_showed_nothing_before": 5,
                                        "skipped_as_done": 0}


def test_the_third_day_of_an_outage_sets_nothing_aside(tmp_path):
    """X4.4."""
    for day, stopped_at in ((D1, 1005), (D, 1010), (D_PLUS_1, 1015)):
        run = Run(tmp_path, day)
        assert empties(run, range(1001, 1020)) == stopped_at
    for n in range(1001, 1006):
        assert run.record(n)["state"] == State.FAILED.value
    assert not run.rows


def test_three_truly_missing_in_a_row_never_stop_a_run(tmp_path):
    """X4.6, the follow-up's own case, over three days."""
    for day in (D2, D1, D):
        run = Run(tmp_path, day)
        assert empties(run, (1001, 1002, 1003)) is None
        for n in range(1004, 1010):
            saved(run, n)


def test_each_run_of_a_day_opens_five(tmp_path):
    """X4.7. Several runs in one day under PaperPull Server."""
    for _ in range(5):
        run = Run(tmp_path)
        assert empties(run, range(1001, 1013)) == 1005


# -- an unread list wins (Changes item 3, X4.9) ----------------------------------------


def test_the_stop_gives_way_to_a_list_not_read_whole(tmp_path, capsys):
    run = Run(tmp_path)
    listing.started(run)
    assert listing.last(run) == listing.STOPPED
    assert empties(run, range(1001, 1005)) is None
    with pytest.raises(ListNotRead) as stop:
        empty(run, 1005)
    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert STOP_WORDS in out and "reads the list first" in out
    assert len(run.failures) == 1
    assert listing.last(run) == listing.STOPPED


def test_after_a_list_read_whole_the_listing_stays_whole(tmp_path):
    """X4.8."""
    run = Run(tmp_path)
    listing.started(run)
    listing.read_whole(run)
    empties(run, range(1001, 1006))
    assert listing.last(run) == listing.COMPLETE


# -- X7, the run's result --------------------------------------------------------------


def _result_after(run, capsys, monkeypatch=None):
    capsys.readouterr()
    try:
        try:
            empties_raising(run)
        finally:
            report_run_result(run.stats)
    except SystemExit:
        pass
    out = capsys.readouterr().out
    return json.loads(out.split(PREFIX, 1)[1]), out


def empties_raising(run):
    for n in range(1001, 1007):
        empty(run, n)


def test_the_result_line_says_stopped_and_why(tmp_path, capsys):
    """X7.1 and X7.4."""
    run = Run(tmp_path)
    result, out = _result_after(run, capsys)
    assert (result["stopped"], result["stop"], result["failed"]) == (1, "not_shown", 5)
    assert "list_not_read" not in result
    assert "carries on from where it stopped" in out


def test_the_reason_is_the_stops_even_after_a_question_nobody_answered(tmp_path, capsys,
                                                                       monkeypatch):
    """X7.1. A prompt earlier in the run found no console and the run went on."""
    monkeypatch.setattr(browser, "_NOBODY_ANSWERED", True)
    run = Run(tmp_path)
    result, _out = _result_after(run, capsys)
    assert result["stop"] == "not_shown"


def test_the_stop_reason_word_is_one_the_panel_takes():
    assert "not_shown" in run_reporting.STOP_REASONS

    def leave():
        raise not_shown.NothingShown()
    seen = {}
    try:
        try:
            leave()
        finally:
            seen["why"] = stop_reason()
            seen["list"] = run_reporting.list_not_read()
    except SystemExit:
        pass
    assert seen == {"why": "not_shown", "list": ""}


def test_a_run_stopped_by_the_stop_exits_zero_in_a_new_process(tmp_path):
    """X7.5. The exit code a terminal sees."""
    import subprocess
    script = ("import sys\nfrom paperpull_core import not_shown\n"
              "raise not_shown.NothingShown()\n")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          cwd=str(Path(not_shown.__file__).resolve().parents[1]))
    assert done.returncode == 0, done.stderr
