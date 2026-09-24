"""A page showing 12/31/99 does not mean the year 2099.

Eleven apps read a two digit year as two thousand plus the number. Every
one of them was generated from the same scaffold, and none of the other
thirty-seven read a two digit year at all, so nothing ever compared the two.

2099 is a date that exists, so the check that refuses impossible dates let
it through. A statement dated seventy-three years from now sorts above
everything real, is filed under a year that has not happened, and passes
every date filter, and the page it came from said 1999.

These ask all forty-eight the same question, because an app that refuses a
short year answers it correctly by refusing.
"""
import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())

THIS_YEAR = date.today().year


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def read(site, text):
    fn = getattr(site, "parse_date", None)
    return fn(text) if fn else None


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
@pytest.mark.parametrize("text", ["12/31/99", "1/2/98", "6/15/75", "1/2/69"])
def test_a_short_year_is_never_read_as_a_date_far_ahead(app, text):
    got = read(site_of(app), text)
    if not got:
        return          # refusing a short year is a correct answer
    year = int(str(got)[:4])
    assert year <= THIS_YEAR + 1, \
        "%s read %s as %s, which has not happened" % (app.name, text, got)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_short_year_that_is_read_at_all_is_read_as_the_right_one(app):
    site = site_of(app)
    for text, want in (("12/31/99", "1999-12-31"),
                       ("3/4/26", "%d-03-04" % (THIS_YEAR - THIS_YEAR % 100 + 26)),
                       ("1/2/00", "2000-01-02")):
        got = read(site, text)
        if got:
            assert got == want, "%s read %s as %s" % (app.name, text, got)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_four_digit_year_is_still_read_as_itself(app):
    """The fix must not have cost the ordinary case."""
    site = site_of(app)
    for text, want in (("03/04/2026", "2026-03-04"), ("12/31/1999", "1999-12-31")):
        got = read(site, text)
        if got:
            assert got == want, "%s read %s as %s" % (app.name, text, got)
