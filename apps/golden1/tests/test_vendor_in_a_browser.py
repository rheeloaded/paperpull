"""The vendor's statement list, as his recording shows it.

The member pressed View documents, then View Documents again which opens
the vendor's own tab, then Statement History, then a link reading
"07/31/26" which downloaded the statement.

That last step came back from the recorder with guard_allows false. The
app would have refused to press the one control that fetches a document,
because a bare date carries none of the words a document control is
recognised by (#35).

In a real browser, since what is being checked is which controls a page
hands over.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_site as site

HISTORY = """<body>
  <a href="#">Current Statement</a>
  <a href="#">Statement History</a>
  <div><a href="#">07/31/26</a><a href="#">06/30/26</a><a href="#">05/31/26</a>
       <a href="#">Pay my loan</a></div>
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
    yield pg
    browser.close()
    driver.stop()


def test_a_statement_named_only_by_its_date_is_found(page):
    page.set_content(HISTORY)
    assert site._bill_controls_by_name_only(page).count() == 0, "this is what found none"
    ctrls = site._bill_controls(page)
    got = [ctrls.nth(i).inner_text().strip() for i in range(ctrls.count())]
    assert got == ["07/31/26", "06/30/26", "05/31/26"]


def test_the_history_is_opened_before_the_list_is_read(page):
    page.set_content(HISTORY)
    assert site.open_statement_history(page) is True
    import inspect
    for fn in (site.collect_download_docs, site.download_bill):
        assert "open_statement_history(page)" in inspect.getsource(fn), fn.__name__


def test_a_date_is_pressable_and_a_payment_is_not():
    for date in ("07/31/26", "06/30/26", "Jul 31, 2026", "2026-07-31"):
        assert site.is_safe_control(date), date
        assert site.DATE_ONLY_CONTROL_RE.match(date), date
    for danger in ("Pay 07/31/26", "07/31/26 pay now", "Make a payment",
                   "Transfer", "Schedule payment", "Edit"):
        assert not site.is_safe_control(danger), danger


def test_a_page_with_no_history_control_says_so_rather_than_failing(page):
    page.set_content("<body><a href='#'>Current Statement</a></body>")
    assert site.open_statement_history(page) is False
