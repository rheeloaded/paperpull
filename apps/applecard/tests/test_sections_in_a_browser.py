"""Reading a statements list in a real browser, as the page would draw it.

Nobody here has seen a signed-in card.apple.com page, so these pages are
made up (#52). What they pin is how the app reads whatever it is given.
A row's month is found by walking up from its control, and that walk is
the part a fake page object cannot stand in for, because it runs inside
the page. A card statement and a Savings statement of the same month
must come out as two documents. A control whose row does not name one
month must be left alone rather than filed under a neighbor's.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import applecard_site as site


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("https://card.apple.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body="<h1>Statements</h1>"))
    pg = ctx.new_page()
    pg.goto("https://card.apple.com/statements")
    yield pg
    browser.close()
    driver.stop()


CARD_PAGE = """
<main><h1>Statements</h1>
<ul>
  <li><span>August 2026</span> <button>Download PDF</button></li>
  <li><span>July 2026</span> <button>Download PDF</button></li>
  <li><span>June 2026</span> <button aria-label="View">View</button> <button>Download PDF</button></li>
</ul>
<button>Export Transactions</button>
</main>
"""

SAVINGS_PAGE = """
<main><h1>Savings</h1><h2>Statements</h2>
<ul>
  <li><span>August 2026</span> <button>Download PDF</button></li>
  <li><span>Tax Year 2025</span> <span>Form 1099-INT</span> <button>Download PDF</button></li>
</ul>
<button>Withdraw</button> <button>Add Money</button>
</main>
"""

# A year heading over month rows that do not repeat the year. Every
# control walks up to the group, which names no single month.
YEAR_GROUPED = """
<main><h1>Statements</h1>
<section><h3>2026</h3>
  <div><span>August</span> <button>Download PDF</button></div>
  <div><span>July</span> <button>Download PDF</button></div>
</section>
</main>
"""


def test_each_card_statement_is_read_under_its_own_month(page):
    page.set_content(CARD_PAGE)
    docs = site.collect_download_docs(page, site.CARD)
    assert [(d.kind, d.date_text) for d in docs] == [
        ("card", "2026-08-31"), ("card", "2026-07-31"), ("card", "2026-06-30")]
    assert docs[0].title == "Apple Card Statement - August 2026"


def test_the_savings_page_gives_a_savings_statement_and_its_tax_form(page):
    page.set_content(SAVINGS_PAGE)
    docs = site.collect_download_docs(page, site.SAVINGS)
    assert [(d.kind, d.date_text, d.title) for d in docs] == [
        ("savings", "2026-08-31", "Savings Statement - August 2026"),
        ("tax", "2025-12-31", "1099-INT - 2025")]


def test_the_tax_section_reads_only_the_tax_form(page):
    page.set_content(SAVINGS_PAGE)
    docs = site.collect_download_docs(page, site.TAX)
    assert [(d.kind, d.date_text) for d in docs] == [("tax", "2025-12-31")]


def test_a_card_and_a_savings_statement_of_one_month_are_two_documents(page):
    page.set_content(CARD_PAGE)
    card = site.collect_download_docs(page, site.CARD)
    page.set_content(SAVINGS_PAGE)
    savings = site.collect_download_docs(page, site.SAVINGS)
    titles = {d.title for d in card + savings if d.date_text == "2026-08-31"}
    assert titles == {"Apple Card Statement - August 2026", "Savings Statement - August 2026"}


def test_months_under_a_year_heading_are_left_alone_and_counted(page):
    """Filing August under July, or both under nothing, would be worse
    than the trace that says two controls carried no single date."""
    page.set_content(YEAR_GROUPED)
    trace = []
    assert site.collect_download_docs(page, site.CARD, trace) == []
    assert trace[-1]["controls_without_one_date"] == 2


def test_the_download_finds_the_control_discovery_listed_and_prefers_download(page):
    page.set_content(CARD_PAGE)
    el, label = site._control_for(page, site.CARD, "2026-06-30")
    assert el is not None and label == "Download PDF"
    row = el.evaluate("e => e.parentElement.innerText")
    assert "June 2026" in row
    assert site._control_for(page, site.CARD, "2026-05-31")[0] is None


def test_the_card_page_is_not_taken_for_savings_and_the_other_way_round(page):
    page.set_content(CARD_PAGE)
    assert site._looks_like(page, site.CARD)
    assert not site._looks_like(page, site.SAVINGS)
    page.set_content(SAVINGS_PAGE)
    assert site._looks_like(page, site.SAVINGS)
    assert not site._looks_like(page, site.CARD)
    assert site._looks_like(page, site.TAX)


def test_a_page_of_tax_forms_alone_is_not_taken_for_the_card_statements(page):
    """A run that starts on such a page would otherwise read it as the
    card's statements and never go looking for the real ones."""
    page.set_content("<main><h1>Documents</h1><ul><li><span>Tax Year 2025</span> "
                     "<span>Form 1099-INT</span> <button>Download PDF</button></li></ul></main>")
    assert site._looks_like(page, site.TAX)
    assert not site._looks_like(page, site.CARD)
    assert not site._looks_like(page, site.SAVINGS)
