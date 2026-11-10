"""Each test starts with no Postbox listing kept from the one before
(ing_site._listing), as each run of the app does."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ing_site


@pytest.fixture(autouse=True)
def _no_listing_kept_between_tests(monkeypatch):
    monkeypatch.setattr(ing_site, "_listing", {})
