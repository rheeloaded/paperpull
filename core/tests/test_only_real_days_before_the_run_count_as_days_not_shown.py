"""Only real days before the run's own count as days a receipt page showed
nothing (a finding of the independent test plan for the threads of
2026-11-16, X2.1 to X2.3).

A record keeps the days its receipt page showed nothing in not_shown_days,
and on the third separate day, after a save of its kind in the run, the
purchase is set aside as No Receipt Available, for good. The days were
read as any non-empty strings in whatever the value was. A value written
as one string, "2026-11-16", was read one character at a time, as ten
days, so the purchase's first empty page after a save set it aside at
once. A day after the run's own, from a clock set back or a record made on
a computer ahead in time, counted as a day too, and so did words that are
no day at all.

Now only a list of real dates counts, and only those before the run's day.
A save lets go of any value there. Every date and number is invented.
"""
import collections
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import not_shown
from paperpull_core.models import ONLINE, Purchase, State
from paperpull_core.storage import JsonStore

D = "2026-11-17"


def order(n: int) -> Purchase:
    return Purchase(purchase_type=ONLINE, purchase_date="2026-11-%02d" % (n - 1000),
                    order_number="ORDER-%d" % n, total="$12.34", summary="Garden Hose",
                    receipt_url="https://receipts.example.invalid/r/ORDER-%d" % n)


class Run:
    def __init__(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        self.progress = JsonStore(out / "progress.json", out / "backups")
        self.progress.load()
        self.stats = collections.defaultdict(int)
        self.stats["new_files"] = []
        self.stats["started"] = D + "T09:00:00"
        self.paths = SimpleNamespace(last_listing=out / "last-listing.json", root=out)
        self.rows = []
        self.order_csv = SimpleNamespace(read_all=lambda: list(self.rows))

    def _record_state(self, purchase, state, notes="", extra=None):
        rec = dict(purchase.to_dict(), state=state.value, notes=notes)
        rec.update(extra or {})
        not_shown.let_go_on_save(self, purchase, state, rec)
        self.progress.update(purchase.key, rec)

    def _write_csv_rows(self, purchase, **kw):
        self.rows.append({"Order or Receipt Number": purchase.order_number,
                          "Purchase Type": purchase.purchase_type})

    def write_failure(self, *a, **kw):
        pass


def after_a_save(tmp_path, days):
    """A run that saved a receipt of the kind, then met purchase 1001's page
    showing nothing, its record holding `days`."""
    run = Run(tmp_path)
    p = order(1001)
    run.progress.update(p.key, dict(p.to_dict(), state=State.FAILED.value, not_shown_days=days))
    run._record_state(order(1009), State.PDF_SAVED, notes="saved")
    not_shown.tried_again(run, p, "The receipt page showed nothing")
    return run, run.progress.get(p.key)


def test_days_written_as_one_string_are_not_ten_days(tmp_path):
    """X2.1. At 8b982c1d this set the purchase aside on its first day."""
    run, rec = after_a_save(tmp_path, "2026-11-16")
    assert rec["state"] == State.FAILED.value, rec
    assert rec[not_shown.DAYS_KEY] == [D], rec
    assert not run.rows, "nothing written into the CSVs"


@pytest.mark.parametrize("days", [["garbage", "words", "here"], ["", "", ""], [None, 5, 7.5],
                                  ["2026-13-45", "2026-02-30", "2026-00-01"],
                                  ["2026-11-16 and more", "2026-11-1", "20261116"]],
                         ids=["words", "empty", "not text", "not a date", "not date-shaped"])
def test_only_real_dates_count(tmp_path, days):
    """X2.2."""
    _run, rec = after_a_save(tmp_path, days)
    assert rec["state"] == State.FAILED.value, rec
    assert rec[not_shown.DAYS_KEY] == [D], rec


def test_days_after_the_runs_own_do_not_count(tmp_path):
    """X2.3. A clock set back, or a record from a computer ahead in time."""
    _run, rec = after_a_save(tmp_path, ["2026-11-18", "2026-11-19"])
    assert rec["state"] == State.FAILED.value, rec
    assert rec[not_shown.DAYS_KEY] == [D], rec


def test_two_real_earlier_days_still_set_it_aside_after_a_save(tmp_path):
    """The control, unchanged."""
    run, rec = after_a_save(tmp_path, ["2026-11-15", "2026-11-16"])
    assert rec["state"] == State.NO_RECEIPT_AVAILABLE.value, rec
    assert rec[not_shown.DAYS_KEY] == ["2026-11-15", "2026-11-16", D]
    assert len(run.rows) == 1


@pytest.mark.parametrize("days", ["2026-11-16", ["garbage"]], ids=["text", "words"])
def test_a_save_lets_go_of_whatever_was_there(tmp_path, days):
    run = Run(tmp_path)
    p = order(1001)
    run.progress.update(p.key, dict(p.to_dict(), state=State.FAILED.value, not_shown_days=days))
    run._record_state(p, State.PDF_SAVED, notes="saved")
    assert run.progress.get(p.key)[not_shown.DAYS_KEY] == []


def test_days_written_as_one_string_never_read_as_set_aside():
    """A record already set aside keeps reading as set aside by its list, as
    the census beside this file holds. One string is no list of days."""
    aside = {"state": State.NO_RECEIPT_AVAILABLE.value}
    assert not_shown.set_aside(dict(aside, not_shown_days=["2026-11-14", "2026-11-15", D]))
    assert not not_shown.set_aside(dict(aside, not_shown_days="2026-11-16"))
