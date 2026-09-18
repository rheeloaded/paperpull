"""Amazon loads one order-history page per year, so a scoped run visits
only the years inside its window and an unscoped run walks back to 1995
(the order-less-year early stop keeps that short in practice)."""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts

THIS_YEAR = datetime.now().year


def _app(config=None, **flags):
    args = {"year": None, "start_date": None, "end_date": None}
    args.update(flags)
    app = amazon_receipts.App.__new__(amazon_receipts.App)
    app.args = SimpleNamespace(**args)
    app.config = config or {}
    return app


def test_unscoped_goes_all_the_way_back():
    years = _app()._discover_years()
    assert years[0] == THIS_YEAR and years[-1] == 1995


def test_year_visits_one_year():
    assert _app(year=2024)._discover_years() == [2024]


def test_start_date_and_the_configured_floor_set_the_oldest_year():
    assert _app(start_date="2023-06-01")._discover_years() == list(range(THIS_YEAR, 2022, -1))
    assert _app({"default_start_date": "2022-01-01"})._discover_years() == list(range(THIS_YEAR, 2021, -1))
    assert _app({"default_start_date": "2022-01-01"}, start_date="2019-01-01")._discover_years()[-1] == 2019


def test_end_date_sets_the_newest_year_so_this_year_is_not_loaded_for_nothing():
    assert _app(start_date="2021-01-01", end_date="2023-12-31")._discover_years() == [2023, 2022, 2021]
    assert _app(end_date="2020-06-30")._discover_years()[0] == 2020


def test_an_end_date_in_the_future_does_not_invent_years():
    assert _app(end_date="%d-01-01" % (THIS_YEAR + 5))._discover_years()[0] == THIS_YEAR
