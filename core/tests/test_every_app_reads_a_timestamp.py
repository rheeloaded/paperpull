"""A date with a time after it is still that date.

Thirty-four apps could not read `2026-03-04T12:00:00Z`. The pattern ended
in a word boundary, and there is none between the `4` and the `T`, so the
match failed and the date came back empty. Plenty of these apps take their
dates from a JSON API, where that is the ordinary way to write one.

Three apps could read it. E*TRADE got the one character fix in round four
of its tester's pilots, after the API handed back dates it could not read,
and the two scaffolds cut afterwards carried the fix along. The other
thirty-four kept the version E*TRADE had just been fixed out of.

An undated document is not a lost one, it is filed with an empty date, so
this was never going to crash anything. It sorts to the bottom, matches no
period, and leaves a hole where a statement should be.

An app whose provider never writes a date that way still has to answer
correctly, so all forty-four are asked.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())

# tsp reads one shape only, "Feb 9, 2026", because that is the only shape
# its mailbox API returns, and its own docstring says so.
NARROW = {"tsp"}


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
@pytest.mark.parametrize("stamp", [
    "2026-03-04T12:00:00Z",
    "2026-03-04T00:00:00.000Z",
    "2026-03-04T12:00:00-05:00",
    "2026-03-04Z",
])
def test_a_date_with_a_time_after_it_is_read_as_that_date(app, stamp):
    site = site_of(app)
    if getattr(site, "parse_date", None) is None:
        pytest.skip("this app reads its dates somewhere other than parse_date")
    if app.name in NARROW:
        pytest.skip("reads one shape only, which its own docstring states")
    if read(site, "2026-03-04") is None:
        pytest.skip("this app does not read a bare ISO date either")
    assert read(site, stamp) == "2026-03-04", \
        "%s could not read %s" % (app.name, stamp)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_longer_run_of_digits_is_still_not_a_date(app):
    """The boundary was there for a reason. Allowing a letter after the day
    must not also allow a fifth digit, or an account number becomes a date."""
    site = site_of(app)
    for text in ("2026-03-045", "12026-03-04", "9876-54-3210"):
        got = read(site, text)
        assert got in (None, "", "2026-03-04") or not got.startswith("2026-03-04"), \
            "%s read %s as %s" % (app.name, text, got)
        if text == "2026-03-045":
            assert not got, "%s read %s as %s" % (app.name, text, got)
