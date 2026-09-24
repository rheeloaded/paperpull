"""Finding a control by what it says, when its name says something else.

A tester's survey counted eighteen document controls on a page by their
own words, and the scan discovery uses found none of them, so the run
reported no documents on a page holding nine (#38).

The two scans differ in what they match. One reads the element's text,
the other the ACCESSIBLE NAME, and an aria-label replaces that name
outright. Describing a row on its control is good practice and it makes
the control unfindable by what is written on it.

In a real browser, because the accessible name is computed by the
browser and nothing else can stand in for it.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.controls import controls_named  # noqa: E402

WORDS = re.compile(r"^\s*(view|download|open)\s*$", re.I)


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def test_a_label_that_describes_the_row_hides_the_word_on_the_control(page):
    page.set_content("""<body>
      <a href="#" aria-label="Statement for September 2026, opens a file">Download</a>
      <a href="#" aria-label="Statement for August 2026, opens a file">Download</a>
    </body>""")
    assert page.get_by_role("link", name=WORDS).count() == 0, "this is the scan that found none"
    assert controls_named(page, WORDS).count() == 2


def test_the_accessible_name_is_still_what_is_tried_first(page):
    page.set_content('<body><a href="#">Download</a><a href="#">Download</a></body>')
    assert controls_named(page, WORDS).count() == 2


def test_a_page_with_no_such_control_still_answers_with_none(page):
    page.set_content('<body><a href="#">Pay my bill</a><p>Download</p></body>')
    assert controls_named(page, WORDS).count() == 0, \
        "a paragraph is not a control, and the guard word is not matched"


def test_a_button_counts_as_well_as_a_link(page):
    page.set_content('<body><button aria-label="row 1">View</button></body>')
    assert controls_named(page, WORDS).count() == 1
