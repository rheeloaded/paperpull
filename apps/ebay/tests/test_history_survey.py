"""Reading the purchase history, and saying what it held.

A tester reported two orders found out of the nine he had made, twice, on
two different builds. Diagnose could not settle it, because it inspects
one ORDER page and says nothing about the history the orders are read
from, so both repairs were guesses and both missed (#44).

These run in a real browser. The thing being counted is what a browser
makes of a page, and a fake page cannot be wrong in the same ways.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ebay_site as site

DETAILS = "https://order.ebay.com/ord/show?orderId=%s"
WRAPPED = "https://www.ebay.com/mye/redirect?ru=x&orderId=%s"
ITEM = "https://www.ebay.com/itm/9991%d"


def row(i, link, names_order=False):
    ident = "Order number:25-1-%d" % i if names_order else ""
    return ('<div class="row"><h3>item %d</h3>'
            '<div>Order date:Sep %d, 2026 Order total:US $%d.00 %s</div>%s</div>'
            % (i, i + 1, i + 5, ident, link))


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


def test_a_link_ebay_wrapped_still_names_its_order(page):
    """His item links reach the details page, and eBay wraps some of its
    own links on the way. A wrapper still carries orderId and matched
    nothing that looked for the details host."""
    page.set_content("<body>%s%s</body>" % (row(0, '<a href="%s">a</a>' % (DETAILS % "25-1-0")),
                                            row(1, '<a href="%s">b</a>' % (WRAPPED % "25-1-1"))))
    ids = sorted(c.order_id for c in site.collect_cards(page))
    assert ids == ["25-1-0", "25-1-1"]
    for card in site.collect_cards(page):
        assert card.href.startswith("https://order.ebay.com/ord/show"), \
            "whatever the anchor said, the address is built from the id"


def test_the_survey_counts_what_the_page_holds_and_what_became_of_it(page):
    rows = "".join([row(0, '<a href="%s">a</a>' % (DETAILS % "25-1-0")),
                    row(1, '<a href="%s">b</a>' % (WRAPPED % "25-1-1")),
                    row(2, '<a href="%s">c</a>' % (ITEM % 2), names_order=True),
                    row(3, '<a href="%s">d</a>' % (ITEM % 3))])
    page.set_content("<body>%s<button>Show more</button></body>" % rows)
    got = site.history_survey(page)
    p = got["page"]
    assert p["rows_with_an_order_date"] == 4, "every row is counted, named or not"
    assert p["anchors_to_an_order"] == 2
    assert p["anchors_written_as_the_details_address"] == 1, "the gap is eBay wrapping its own"
    assert p["distinct_ids_in_text"] == 1
    assert "Show more" in p["controls_that_might_page"]
    assert got["cards_collected"] == 3
    assert got["became_purchases"] == 3


def test_the_row_that_names_no_order_at_all_is_the_one_that_is_lost(page):
    """Which is the whole question. A page of nine reporting two says so
    in one line now, rather than in a number that is true of every step."""
    rows = "".join([row(i, '<a href="%s">x</a>' % (ITEM % i), names_order=(i < 2))
                    for i in range(9)])
    page.set_content("<body>%s</body>" % rows)
    got = site.history_survey(page)
    assert got["page"]["rows_with_an_order_date"] == 9
    assert got["cards_collected"] == 2
    assert got["became_purchases"] == 2


def test_the_survey_says_nothing_it_does_not_have_to(page):
    """It goes in a file somebody attaches to a public issue. An order id
    is already in every filename, and nothing else comes back."""
    page.set_content("<body><h1>Hi Joseph!</h1>%s</body>"
                     % row(0, '<a href="%s">Something personal</a>' % (DETAILS % "25-1-0")))
    import json
    text = json.dumps(site.history_survey(page))
    assert "Joseph" not in text
    assert "Something personal" not in text


def test_diagnose_surveys_the_history_before_it_surveys_an_order():
    src = (Path(site.__file__).parent / "ebay_receipts.py").read_text(encoding="utf-8")
    block = src.split("def cmd_diagnose")[1][:2600]
    assert "history_survey(page)" in block
    assert "diagnose-history.json" in block
    assert block.index("history_survey") < block.index("goto_details"), \
        "the history first, since that is what could not be explained"


# -- the year filter is what lost them (#44) ---------------------------------

def test_discovery_reads_the_unfiltered_history_before_any_year():
    """His survey showed twenty-five orders on the unfiltered page, every
    count agreeing at every step, and two on the same page filtered to
    this year. He had made nine. So the filter lost them, and two repairs
    aimed at the card reading changed nothing for him."""
    src = (Path(site.__file__).parent / "ebay_receipts.py").read_text(encoding="utf-8")
    block = src.split("def cmd_discover")[1][:2600]
    unfiltered = block.index("goto_orders(page, None)")
    by_year = block.index("for year in self._years_to_walk()")
    assert unfiltered < by_year, "the unfiltered page is read first"
    assert "not already seen" in block, "a year adds only what the unfiltered page missed"


def test_a_year_still_reaches_back_past_what_one_page_shows():
    src = (Path(site.__file__).parent / "ebay_receipts.py").read_text(encoding="utf-8")
    block = src.split("def cmd_discover")[1][:2600]
    assert "_years_to_walk()" in block, "the filter is still walked for older history"
    assert block.count("scroll_all_orders(page)") >= 2, "both passes scroll"


def test_a_control_that_pages_is_found_by_its_label_as_well_as_its_words():
    js = site._HISTORY_SURVEY_JS
    assert "aria-label" in js
    assert "page" in js.lower()
