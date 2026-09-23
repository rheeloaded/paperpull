"""The calendar facts, including the leap year rule that was copied into
twenty-nine apps."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.dates import human_date, last_day  # noqa: E402


def test_the_ordinary_months():
    assert last_day(2026, 1) == 31
    assert last_day(2026, 4) == 30
    assert last_day(2026, 12) == 31


def test_february_in_a_common_year():
    assert last_day(2026, 2) == 28
    assert last_day(2027, 2) == 28


def test_february_in_a_leap_year():
    assert last_day(2024, 2) == 29
    assert last_day(2028, 2) == 29


def test_the_century_rule():
    """1900 was not a leap year and 2000 was. The reason the rule is three
    clauses and not one."""
    assert last_day(1900, 2) == 28
    assert last_day(2100, 2) == 28
    assert last_day(2000, 2) == 29
    assert last_day(2400, 2) == 29


def test_a_date_a_person_reads():
    assert human_date("2026-08-31") == "August 31, 2026"
    assert human_date("2026-01-01") == "January 1, 2026"


def test_a_leading_zero_does_not_survive_into_the_day():
    assert human_date("2026-09-05") == "September 5, 2026"


def test_anything_it_cannot_read_comes_back_unchanged():
    """A label that is merely unexpected beats a run that stops."""
    for odd in ("", "not a date", "2026", "2026-13-01", "2026-08-31T09:00:00"):
        assert human_date(odd) == odd


# -- a date that is merely shaped like one -------------------------------------

def test_a_real_day_is_real():
    from paperpull_core.dates import is_real_date
    for iso in ("2026-08-31", "2024-02-29", "2026-01-01", "2026-12-31"):
        assert is_real_date(iso), iso


def test_a_day_that_does_not_exist():
    from paperpull_core.dates import is_real_date
    for iso in ("2026-02-30", "2026-13-45", "2026-00-10", "2026-04-31",
                "2026-11-31", "2026-13-13", "2026-99-99"):
        assert not is_real_date(iso), iso


def test_february_the_twenty_ninth_only_in_a_leap_year():
    from paperpull_core.dates import is_real_date
    assert is_real_date("2024-02-29")
    assert not is_real_date("2026-02-29")
    assert not is_real_date("1900-02-29")
    assert is_real_date("2000-02-29")


def test_a_reference_number_is_not_a_date():
    """The one that sent thirty-seven apps filing documents under it."""
    from paperpull_core.dates import is_real_date
    for not_a_date in ("1234-56-78", "0000-00-00", "9999-99-99", ""):
        assert not is_real_date(not_a_date), not_a_date


def test_nothing_useful_is_not_a_date():
    from paperpull_core.dates import is_real_date
    for junk in (None, "not a date", "2026", "2026-08", "2026-08-31T09:00", 20260831):
        assert not is_real_date(junk), junk


def test_checked_keeps_a_real_date_and_drops_an_impossible_one():
    from paperpull_core.dates import checked
    assert checked("2026-08-31") == "2026-08-31"
    assert checked("1234-56-78") is None
    assert checked(None) is None


def test_checked_answers_the_way_the_app_already_did():
    """Six apps say "" for no date and the rest say None. A date they
    should never have believed has to look like the one they know."""
    from paperpull_core.dates import checked
    assert checked("1234-56-78", "") == ""
    assert checked("", "") == ""
    assert checked("2026-08-31", "") == "2026-08-31"
