"""Scoped discovery. A scoped run skips fetching years outside its window
and an unscoped run still walks everything."""
from types import SimpleNamespace

from paperpull_core import scope


def _args(**kw):
    base = {"year": None, "start_date": None, "end_date": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_no_flags_and_no_floor_is_unscoped():
    assert scope.year_window(_args(), {}) == (None, None)
    assert scope.period_filter(_args(), {}) is None
    assert scope.periods_in_scope(["2026", "2025", "2019"], _args(), {}) == ["2026", "2025", "2019"]


def test_year_wins_over_everything():
    args = _args(year=2024, start_date="2020-01-01", end_date="2026-12-31")
    assert scope.year_window(args, {"default_start_date": "2015-01-01"}) == (2024, 2024)
    assert scope.periods_in_scope(["2026", "2025", "2024", "2023"], args, {}) == ["2024"]


def test_start_and_end_dates_bound_the_window():
    assert scope.year_window(_args(start_date="2023-06-01"), {}) == (2023, None)
    assert scope.year_window(_args(end_date="2024-03-31"), {}) == (None, 2024)
    assert scope.periods_in_scope(["2026", "2025", "2024", "2023", "2022"],
                                  _args(start_date="2023-06-01", end_date="2024-12-31"), {}) == ["2024", "2023"]


def test_the_configured_floor_counts_and_a_flag_beats_it():
    cfg = {"default_start_date": "2022-01-01"}
    assert scope.year_window(_args(), cfg) == (2022, None)
    assert scope.year_window(_args(start_date="2019-01-01"), cfg) == (2019, None)


def test_options_that_name_no_year_are_always_kept():
    args = _args(year=2024)
    assert scope.periods_in_scope(["Current", "Last 12 months", "All", "", "2024", "2023"],
                                  args, {}) == ["Current", "Last 12 months", "All", "", "2024"]


def test_ranges_and_open_ended_options_are_kept_when_they_overlap():
    w = (2021, 2022)
    assert scope.in_window("2020-2021", w)
    assert not scope.in_window("2018-2019", w)
    assert scope.in_window("2023 and earlier", w)
    assert not scope.in_window("2019 and earlier", w)
    assert scope.in_window("Before 2022", w)
    assert scope.in_window("2019 and later", w)
    assert not scope.in_window("2023 onwards", w)
    assert scope.in_window("Tax year 2021", w)
    assert not scope.in_window("Tax year 2020", w)


def test_labels_with_digits_that_are_not_years_are_not_years():
    assert scope.in_window("Last 3 months", (2024, 2024))
    assert scope.in_window("Account ...4321", (2024, 2024))
    assert scope.in_window("Page 202", (2024, 2024))


def test_describe_reads_like_a_sentence():
    assert scope.describe((None, None)) == "every year"
    assert scope.describe((2024, 2024)) == "2024"
    assert scope.describe((2021, 2024)) == "2021 to 2024"
    assert scope.describe((2021, None)) == "2021 onward"
    assert scope.describe((None, 2024)) == "up to 2024"
