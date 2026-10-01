"""A document's row is found by its own date, never by a date that holds it.

When a document was discovered without its id, its download goes back to
the list and finds its row by the title, the date and the account the row
showed. The date was looked for anywhere in the row's words, and a date a
page writes as 1/5/2025 is inside 11/5/2025. The same statement for the
same account comes every month and the list is newest first, so January's
statement took November's row above it, and November's PDF was saved
under January's name.

The table below is made up in the shape of USAA's documents list, a title
that opens the document, the date it was delivered and the account. Every
date and account is invented, and the browser is refused the network, so
nothing here can reach a real site.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import usaa_site as site

PAGE = r"""<!doctype html><html><body><main><h1>My Documents</h1>
<table>
 <thead><tr><th>Document title</th><th>Date delivered</th><th>Account</th><th>Options</th></tr></thead>
 <tbody id="rows"></tbody>
</table></main>
<script>
const ROWS = __ROWS__;
document.getElementById('rows').innerHTML = ROWS.map(([title, date, account], i) =>
  '<tr><td><button data-testid="readDocument-' + i + '">' + title + '</button></td>' +
  '<td>' + date + '</td><td>' + account + '</td>' +
  '<td><button data-testid="actions-' + i + '">Options</button></td></tr>').join('');
</script></body></html>"""

STATEMENT = "Bank Statement"
ACCOUNT = "Example Checking 0000"


@pytest.fixture()
def documents():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()

    def show(*rows):
        pg.set_content(PAGE.replace("__ROWS__", json.dumps([list(r) for r in rows])))
        return pg
    yield show
    browser.close()
    driver.stop()


def _row_of(control):
    return control.get_attribute("data-testid") if control is not None else None


def test_january_finds_its_own_row_below_november(documents):
    page = documents((STATEMENT, "11/5/2025", ACCOUNT), (STATEMENT, "1/5/2025", ACCOUNT))
    assert _row_of(site._find_doc_row(page, STATEMENT, "1/5/2025", ACCOUNT)) == "readDocument-1"
    assert _row_of(site._find_doc_row(page, STATEMENT, "11/5/2025", ACCOUNT)) == "readDocument-0"


def test_a_date_written_out_finds_its_own_row(documents):
    page = documents((STATEMENT, "15 Jan 2025", ACCOUNT), (STATEMENT, "5 Jan 2025", ACCOUNT))
    assert _row_of(site._find_doc_row(page, STATEMENT, "5 Jan 2025", ACCOUNT)) == "readDocument-1"


def test_a_date_found_only_inside_another_finds_no_row(documents):
    page = documents((STATEMENT, "11/5/2025", ACCOUNT), (STATEMENT, "12/1/2025", ACCOUNT))
    for date_text in ("1/5/2025", "2/1/2025", "1/5/20"):
        assert site._find_doc_row(page, STATEMENT, date_text, ACCOUNT) is None, date_text
