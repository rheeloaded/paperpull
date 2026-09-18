"""The Scope row on the panel. All years is the default and adds nothing to
the command. One year, or a date range, becomes the same --year,
--start-date and --end-date flags every app already takes, so a scoped run
skips the years outside its window on sites with a year picker. Whatever the
page sends is validated before it reaches a command line."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

META = {"python": "py", "script": "x_docs.py", "login_flag": "--login",
        "accounts": ["primary", "esther"], "dir": "."}


def test_all_years_adds_no_flags():
    assert app_module._scope_flags() == []
    assert app_module._scope_flags("", "", "") == []
    assert app_module._build_cmd(META, "primary", "all") == ["py", "x_docs.py", "--all", "--yes"]


def test_one_year_becomes_the_year_flag():
    assert app_module._scope_flags("2025") == ["--year", "2025"]
    cmd = app_module._build_cmd(META, "esther", "discover", app_module._scope_flags("2025"))
    assert cmd == ["py", "x_docs.py", "--discover", "--year", "2025", "--config", "config.esther.json"]


def test_a_date_range_becomes_start_and_end_flags():
    assert app_module._scope_flags("", "2023-01-01", "2024-12-31") == \
        ["--start-date", "2023-01-01", "--end-date", "2024-12-31"]
    assert app_module._scope_flags("", "2023-01-01", "") == ["--start-date", "2023-01-01"]
    assert app_module._scope_flags("", "", "2024-12-31") == ["--end-date", "2024-12-31"]


def test_login_is_never_scoped():
    cmd = app_module._build_cmd(META, "primary", "login", ["--year", "2025"])
    assert cmd == ["py", "x_docs.py", "--login"]


@pytest.mark.parametrize("year", ["25", "2025x", "1899", "--all", "2025 --yes", "x"])
def test_a_year_that_is_not_a_year_is_refused(year):
    with pytest.raises(fastapi.HTTPException) as e:
        app_module._scope_flags(year)
    assert e.value.status_code == 400


@pytest.mark.parametrize("date", ["2025", "2025-13-01", "2025-01-32", "01/02/2025", "2025-1-2",
                                  "2025-01-01 --redownload"])
def test_a_date_that_is_not_an_iso_date_is_refused(date):
    with pytest.raises(fastapi.HTTPException):
        app_module._scope_flags("", date, "")
    with pytest.raises(fastapi.HTTPException):
        app_module._scope_flags("", "", date)


def test_a_start_after_the_end_is_refused():
    with pytest.raises(fastapi.HTTPException):
        app_module._scope_flags("", "2025-01-01", "2024-01-01")


def test_surrounding_whitespace_is_tolerated():
    assert app_module._scope_flags(" 2025 ", "", "") == ["--year", "2025"]


def test_the_page_has_the_scope_row():
    """The row is on the page, defaults to all years, and every run reads it."""
    html = app_module.index()
    body = html.body.decode("utf-8") if hasattr(html, "body") else str(html)
    assert 'id="year"' in body and 'id="start"' in body and 'id="end"' in body
    assert "All years (default)" in body
    assert "q.set('year'" in body and "q.set('start'" in body and "q.set('end'" in body
