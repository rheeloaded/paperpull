"""A row that could not be read does not move the others up.

Several statements of one date are labeled the same on Ally's page, and
nothing tells them apart but their order, so the download takes the Nth
row of the date the way the API listed them. A row whose words or whose
control did not answer in time was left out, and every row after it moved
up one place. The row taken was the next statement's. A tax row whose
words did not answer was kept with no words, so a trust's form passed for
a plain one and was taken by its place.

Found by the census that followed CI run 36792330947, where E*TRADE passed
over a control that did not answer in time. Every row here is invented and
the browser is refused the network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ally_site as site
from paperpull_core.testkit import stall_reads

STATEMENTS = """<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body><table><tbody>%s</tbody></table></body></html>""" % "".join(
    "<tr data-guid='r%d'><td>September 16, 2026</td><td><span class='sr-only'>Download statement for: </span>"
    "<button type='button' data-guid='b%d'>Statement</button></td></tr>" % (i, i) for i in range(3))

TAX = """<!doctype html><html><body><table><tbody>
<tr data-guid='r-trust'><td>1099-INT</td><td>Invented Family Trust</td>
  <td><button type='button' data-guid='b-trust'>Download</button></td></tr>
<tr data-guid='r0'><td>1099-INT</td><td>Interest</td><td><button type='button' data-guid='b0'>Download</button></td></tr>
<tr data-guid='r1'><td>1099-INT</td><td>Interest</td><td><button type='button' data-guid='b1'>Download</button></td></tr>
</tbody></table></body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    yield ctx.new_page()
    browser.close()
    driver.stop()


def _guid(ctrl):
    return None if ctrl is None else ctrl.get_attribute("data-guid")


def test_each_statement_of_a_date_is_taken_by_its_place(page):
    """The twin with nothing stalled, so the tests below are about the stall."""
    page.set_content(STATEMENTS)
    assert [_guid(site._find_row_control(page, "2026-09-16", "", n)) for n in range(3)] == ["b0", "b1", "b2"]


@pytest.mark.parametrize("stalled", ["r0", "b0"])
def test_a_row_that_could_not_be_read_does_not_move_the_others_up(page, monkeypatch, stalled):
    """The first row's words, or its control's, did not answer. The second
    statement was asked for and the third one's control came back."""
    page.set_content(STATEMENTS)
    stall_reads(monkeypatch, {stalled}, locator=("inner_text",))
    got = site._find_row_control(page, "2026-09-16", "", 1)
    assert got is None, "it took %s for the second statement" % _guid(got)


def test_each_tax_form_is_taken_by_its_place(page):
    page.set_content(TAX)
    assert [_guid(site._find_tax_row_control(page, "Form 1099-INT", "", n)) for n in range(2)] == ["b0", "b1"]


@pytest.mark.parametrize("stalled, wanted", [("r-trust", 0), ("b0", 0)])
def test_a_tax_row_that_could_not_be_read_is_not_counted_in_or_out(page, monkeypatch, stalled, wanted):
    """The trust's row words did not answer and it was kept with none, so
    it passed for the first plain form. Or the first plain form's control
    did not answer and the second one moved into its place."""
    page.set_content(TAX)
    stall_reads(monkeypatch, {stalled}, locator=("inner_text",))
    got = site._find_tax_row_control(page, "Form 1099-INT", "", wanted)
    assert got is None, "it took %s for plain form %d" % (_guid(got), wanted)
