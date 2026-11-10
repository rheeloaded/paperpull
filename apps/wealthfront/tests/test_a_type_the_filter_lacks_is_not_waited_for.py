"""A document type the page's own filter does not offer is not waited for.

Discover sets the document-type filter to "Statements", then to
"Quarterly Statements". The page's filter is a native <select>, and on an
account with no quarterly statements it has no such option. Choosing it
waited out the whole timeout, and then the custom-dropdown fallback found
the text "All Document Types" on the select's own hidden <option> and
tried to click it, waiting out the timeout again before the run carried
on. Every run spent a minute there and logged "document-type filter
failed ... Timeout".

Now a type the filter does not offer is turned down at once, and a type
it does offer is still chosen. Driven in a real browser against a made-up
page. Every account and document is invented.
"""
import logging
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wealthfront_site as site

PAGE = """<!doctype html><html><body>
<label>Document type <select name="selectedDocumentType">
  <option value="VIEW_ALL">All Document Types</option>
  <option value="STATEMENT">Statements</option>
  <option value="CONFIRMATION">Trade Confirmations</option>
</select></label>
<table><tbody><tr><td>Invented Cash Account</td><td>Monthly Statement</td></tr></tbody></table>
</body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.set_default_timeout(4000)
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    shortened = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: shortened(min(ms, 200))
    pg.set_content(PAGE)
    yield pg
    browser.close()
    driver.stop()


def test_a_type_the_filter_does_not_offer_is_turned_down_at_once(page, caplog):
    caplog.set_level(logging.INFO)
    started = time.monotonic()
    assert site.set_document_type(page, "Quarterly Statements") is False
    assert time.monotonic() - started < 3
    assert "document-type filter failed" not in caplog.text
    assert page.locator("select").input_value() == "VIEW_ALL"


def test_a_type_the_filter_offers_is_still_chosen(page):
    assert site.set_document_type(page, "Statements") is True
    assert page.locator("select").input_value() == "STATEMENT"
