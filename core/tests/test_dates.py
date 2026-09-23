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
