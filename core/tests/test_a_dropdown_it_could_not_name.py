"""A dropdown whose identity could not be read is refused, and said to be there.

safe_selects reads what each dropdown is called before it may be read or
set, and refuses one it cannot name. That stays. But it said nothing more,
so an app looking for its year picker among the dropdowns could not tell
a page whose picker did not answer from a page without one, and took the
next dropdown of years for it. Ally pressed another year's tax form that
way (found on 2026-10-01, see apps/ally/tests/test_a_year_it_could_not_show.py).
A caller that hands in a list now gets each dropdown whose identity could
not be read. One that answered with no name at all is refused as before
and is not in the list, since it was read.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import controls  # noqa: E402
from paperpull_core.testkit import stall_reads  # noqa: E402

PAGE = """<body>
  <label for="first">Year</label><select id="first" data-guid="first"><option>2025</option></select>
  <select data-guid="nameless"><option>2025</option></select>
  <label for="second">Year</label><select id="second" data-guid="second"><option>2025</option></select>
</body>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    pg.set_content(PAGE)
    yield pg
    browser.close()
    driver.stop()


def _guids(locators):
    return [s.get_attribute("data-guid") for s in locators]


def test_every_dropdown_that_could_be_named_is_yielded(page):
    """The twin with nothing stalled. The nameless one is refused, and it
    was read, so it is not listed as unread."""
    missed = []
    assert _guids(s for s, _ in controls.safe_selects(page, unread=missed)) == ["first", "second"]
    assert missed == []


def test_a_dropdown_whose_identity_could_not_be_read_is_refused_and_listed(page, monkeypatch):
    stall_reads(monkeypatch, {"first"}, locator=("evaluate",), scripts=(controls.IDENTITY_JS,))
    missed = []
    assert _guids(s for s, _ in controls.safe_selects(page, unread=missed)) == ["second"]
    assert _guids(missed) == ["first"]


def test_a_caller_that_hands_in_no_list_is_answered_as_before(page, monkeypatch):
    stall_reads(monkeypatch, {"first"}, locator=("evaluate",), scripts=(controls.IDENTITY_JS,))
    assert _guids(s for s, _ in controls.safe_selects(page)) == ["second"]
    assert controls.control_identity(page.locator("[data-guid=first]")) == ""
