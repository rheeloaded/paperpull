"""Reading a statements list in a real browser, as the page would draw it.

The first recording (#52) showed that every document on all three lists is
one icon button named "Download statement of <month> <year> (PDF)". The
pages here are made up, with invented months, and keep that shape. What
they pin is how the app reads whatever it is given. A document is dated by
its own button's name, never by the text around it. A card statement and a
Savings statement of the same month come out as two documents. A control of
any other shape is counted and never read, since the tester's own Diagnose
found one the wider pattern matched on a Savings page that holds no
document at all. The survey's
guesses about which page is which still read the wider, older shapes.
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


def button(month, year):
    return ('<ui-button role="button" tabindex="0" aria-label="Download statement of %s %s (PDF)">'
            '<svg width="16" height="16"></svg></ui-button>' % (month, year))


# The recorded shape. The row shows the month and the year is a heading
# the row does not repeat.
CARD_PAGE = """
<main><h2>Statements</h2><button>Export Transactions</button>
<section><h3>2031</h3><ul>
  <li><div>March</div> %s</li>
  <li><div>February</div> %s</li>
  <li><div>January</div> %s</li>
</ul></section>
</main>
""" % (button("March", 2031), button("February", 2031), button("January", 2031))

# What the first build guessed a Savings page would look like, a statement
# and a tax form each with a Download PDF button. No list the tester
# recorded looks like this.
GUESSED_SAVINGS_PAGE = """
<main><h1>Savings</h1><h2>Statements</h2>
<ul>
  <li><span>March 2031</span> <button>Download PDF</button></li>
  <li><span>Tax Year 2030</span> <span>Form 1099-INT</span> <button>Download PDF</button></li>
</ul>
<button>Withdraw</button> <button>Add Money</button>
</main>
"""

GUESSED_CARD_PAGE = """
<main><h1>Statements</h1>
<ul>
  <li><span>March 2031</span> <button>Download PDF</button></li>
  <li><span>February 2031</span> <button>Download PDF</button></li>
</ul>
<button>Export Transactions</button>
</main>
"""


def test_each_card_statement_is_read_under_its_own_month(page):
    page.set_content(CARD_PAGE)
    trace = []
    docs = site.collect_download_docs(page, site.CARD, trace)
    assert [(d.kind, d.date_text) for d in docs] == [
        ("card", "2031-03-31"), ("card", "2031-02-28"), ("card", "2031-01-31")]
    assert docs[0].title == "Apple Card Statement - March 2031"
    assert trace[-1]["controls_of_another_shape"] == 0


def test_a_card_and_a_savings_statement_of_one_month_are_two_documents(page):
    page.set_content(CARD_PAGE)
    card = site.collect_download_docs(page, site.CARD)
    savings = site.collect_download_docs(page, site.SAVINGS)
    titles = {d.title for d in card + savings if d.date_text == "2031-02-28"}
    assert titles == {"Apple Card Statement - February 2031", "Savings Statement - February 2031"}


def test_a_control_of_any_other_shape_is_never_read_as_a_document(page):
    """The first build read any control whose words said PDF or download,
    and dated it from the text around it, a lone year on the tax list. No
    list the tester recorded offers a document that way, and a Savings
    page does carry a control of that wider kind that is not a document.
    So nothing but the recorded button is read, and the rest is counted
    for the trace."""
    page.set_content(GUESSED_SAVINGS_PAGE)
    trace = []
    assert site.collect_download_docs(page, site.SAVINGS, trace) == []
    assert trace[-1]["controls_of_another_shape"] == 2
    assert site.collect_download_docs(page, site.TAX) == []
    assert site._control_for(page, site.TAX, "2030-12-31") == (None, "")


def test_a_statement_button_whose_row_speaks_of_tax_is_left_alone_and_counted(page):
    """A statement list's button is that list's statement, unless its row
    says tax, when it is neither a statement nor, off the tax list, a tax
    form. It is left unread and the trace says so."""
    page.set_content("<main><h2>Statements</h2><ul><li><div>Tax statement, March 2031</div> %s</li>"
                     "<li><div>February 2031</div> %s</li></ul></main>"
                     % (button("March", 2031), button("February", 2031)))
    trace = []
    docs = site.collect_download_docs(page, site.SAVINGS, trace)
    assert [d.date_text for d in docs] == ["2031-02-28"]
    assert trace[-1]["controls_without_one_date"] == 1


def test_the_download_finds_the_control_discovery_listed(page):
    page.set_content(CARD_PAGE)
    el, label = site._control_for(page, site.CARD, "2031-01-31")
    assert el is not None and label == "Download statement of January 2031 (PDF)"
    row = el.evaluate("e => e.parentElement.innerText")
    assert "January" in row
    assert site._control_for(page, site.CARD, "2030-12-31") == (None, "")


def test_two_buttons_that_read_as_one_document_are_neither_pressed(page):
    """Two buttons on one list that name the same month could be two
    documents. Pressing the first was a guess, so neither is pressed."""
    page.set_content("<main><ul><li>%s</li><li>%s</li><li>%s</li></ul></main>"
                     % (button("March", 2031), button("March", 2031), button("February", 2031)))
    assert site._control_for(page, site.CARD, "2031-03-31") == (None, "")
    assert site._control_for(page, site.CARD, "2031-02-28")[1] == "Download statement of February 2031 (PDF)"


def test_the_card_page_is_not_taken_for_savings_and_the_other_way_round(page):
    """The survey's own guess at which page it is on, from the wider shape."""
    page.set_content(GUESSED_CARD_PAGE)
    assert site._looks_like(page, site.CARD)
    assert not site._looks_like(page, site.SAVINGS)
    page.set_content(GUESSED_SAVINGS_PAGE)
    assert site._looks_like(page, site.SAVINGS)
    assert not site._looks_like(page, site.CARD)
    assert site._looks_like(page, site.TAX)


def test_a_page_of_tax_forms_alone_is_not_taken_for_the_card_statements(page):
    """A survey that starts on such a page would otherwise call it the
    card's statements."""
    page.set_content("<main><h1>Documents</h1><ul><li><span>Tax Year 2030</span> "
                     "<span>Form 1099-INT</span> <button>Download PDF</button></li></ul></main>")
    assert site._looks_like(page, site.TAX)
    assert not site._looks_like(page, site.CARD)
    assert not site._looks_like(page, site.SAVINGS)


TWO_MARCHES = ("<main><ul>"
               "<li><ui-button role='button' tabindex='0' data-guid='march' "
               "aria-label='Download statement of March 2031 (PDF)'></ui-button></li>"
               "<li><ui-button role='button' tabindex='0' data-guid='mar' "
               "aria-label='Download statement of Mar 2031 (PDF)'></ui-button></li>"
               "</ul></main>")


def test_two_buttons_that_name_one_month_two_ways_are_neither_pressed(page):
    """The twin with nothing stalled, so the test below is about the stall."""
    page.set_content(TWO_MARCHES)
    assert site._control_for(page, site.CARD, "2031-03-31") == (None, "")


def test_a_button_that_could_not_be_read_keeps_the_other_from_being_the_only_one(page, monkeypatch):
    """The March button's name did not answer in time. It read as no
    document at all, so the Mar button was the only one left reading as
    March 2031, and it was pressed. Found by the census that followed CI
    run 36792330947, where E*TRADE passed over a control the same way."""
    from paperpull_core.testkit import stall_reads
    page.set_content(TWO_MARCHES)
    stall_reads(monkeypatch, {"march"}, locator=("get_attribute",))
    assert site._control_for(page, site.CARD, "2031-03-31") == (None, "")
