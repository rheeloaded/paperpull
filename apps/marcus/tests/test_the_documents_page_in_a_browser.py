"""The Documents page read and pressed in a real browser.

The page here is built the way Marcus builds its own, as it was read on
2026-11: two tabs, a panel with one table (role=grid), a "Date Range"
widget that is an input over a listbox of years, and a notice in place of
the table for a year with no statement. A year's rows are drawn a moment
after the year is chosen, and until then the panel still holds what the
year before it showed, a notice of no documents included.

Every page here is made up and served from memory, every account, date and
address is invented, and every other request is refused, so nothing leaves
this machine.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import marcus_site as site  # noqa: E402
from paperpull_core import delivery  # noqa: E402
from paperpull_core.testkit import text_pdf  # noqa: E402

DOC = site.BASE + "/api/invented/document/"
PDF = text_pdf(["Marcus by Goldman Sachs", "Online Savings Account",
                "Statement Period 12/01/2025 to 12/31/2025"])

PAGE = """<!doctype html><html><body>
<style>.hidden { display: none; }</style>
<h1>Documents</h1>
<button role="tab" data-testid="statements_statements" id="statements"
        aria-selected="true" aria-controls="statements-tab">Account Statements</button>
<button role="tab" data-testid="statements_taxDocuments" id="taxDocuments"
        aria-selected="false">Tax Forms</button>
<div data-testid="statements_selectStatementDate_drop_down">
  <label for="selectStatementDate">Date Range</label>
  <input id="selectStatementDate" readonly value="2026"
         aria-controls="selectStatementDate-listbox" aria-expanded="false">
  <ul id="selectStatementDate-listbox" role="listbox" class="hidden">
    <li role="option" aria-selected="true"><span>2026</span></li>
    <li role="option" aria-selected="false"><span>2025</span></li>
    <li role="option" aria-selected="false"><span>2024</span></li>
    <li role="option" aria-selected="false"><span>2023</span></li>
  </ul>
  <select aria-hidden="true"><option>2026</option></select>
</div>
<section role="tabpanel" data-testid="statements_statements_tab"
         id="statements-tab"></section>
<section role="tabpanel" data-testid="statements_taxDocuments_tab" class="hidden">
  <table role="grid"><tbody><tr role="row"><td>****4417</td><td>1099-INT</td>
  <td><a data-testid="download_99" href="https://www.marcus.com/api/invented/tax/99">01/31/2026</a></td>
  </tr></tbody></table></section>
<script>
const DOC = '%s';
const YEARS = {
  '2026': [['****4417', 'Online Savings', '02/01/2026', 1],
           ['****4417', 'Online Savings', '01/01/2026', 2]],
  '2025': [['****4417', 'Online Savings', '12/01/2025', 3],
           ['****0926', 'Online Savings', '12/01/2025', 4]],
  '2024': [],
  '2023': [],
};
const panel = document.getElementById('statements-tab');
const input = document.getElementById('selectStatementDate');
const list = document.getElementById('selectStatementDate-listbox');
function draw(year) {
  const rows = YEARS[year];
  if (!rows.length) {
    panel.innerHTML = '<p>No documents found for this time frame.</p>';
    return;
  }
  panel.innerHTML = '<table role="grid"><tbody>' + rows.map(r =>
    '<tr role="row"><td>' + r[0] + '</td><td>' + r[1] + '</td><td>' +
    '<a data-testid="download_' + r[3] + '" href="' + DOC + r[3] +
    '?accountId=invented&fromDate=2025-11-01&toDate=2025-11-30">' + r[2] +
    '</a></td></tr>').join('') + '</tbody></table>';
}
input.addEventListener('click', () => list.classList.toggle('hidden'));
for (const li of list.querySelectorAll('li')) {
  li.addEventListener('click', () => {
    for (const o of list.querySelectorAll('li')) o.setAttribute('aria-selected', 'false');
    li.setAttribute('aria-selected', 'true');
    input.value = li.textContent.trim();
    list.classList.add('hidden');
    // The year's rows come a moment later. Until then the panel holds
    // what it held, as the site's does.
    setTimeout(() => draw(li.textContent.trim()), 600);
  });
}
draw('2026');
</script></body></html>""" % DOC


@pytest.fixture()
def marcus():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True, args=["--host-resolver-rules=MAP * ~NOTFOUND"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    asked = []

    def document(route):
        asked.append(route.request.url.split("?")[0].rsplit("/", 1)[-1])
        route.fulfill(status=200, content_type="application/pdf", body=PDF,
                      headers={"content-disposition":
                               'attachment; filename="invented.pdf"'})

    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(site.DOCUMENTS_URL, lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE))
    ctx.route(DOC + "*", document)
    page = ctx.new_page()
    page.goto(site.DOCUMENTS_URL)
    yield SimpleNamespace(page=page, ctx=ctx, asked=asked)
    browser.close()
    driver.stop()


def test_the_page_is_read_as_a_signed_in_documents_page(marcus):
    assert site.goto_documents(marcus.page)
    assert not site.looks_signed_out(marcus.page)
    assert site.detect_security_challenge(marcus.page) is None
    assert site._shown_year(marcus.page) == "2026"
    assert site._year_options(marcus.page) == ["2026", "2025", "2024", "2023"]


def test_every_year_is_listed_and_an_empty_year_is_not_a_stop(marcus):
    docs = site.collect_download_docs(marcus.page)
    assert [(d.date_text, d.account) for d in docs] == [
        ("2026-02-01", "x4417"), ("2026-01-01", "x4417"),
        ("2025-12-01", "x4417"), ("2025-12-01", "x0926")]
    assert site._shown_year(marcus.page) == "2023"
    assert not marcus.asked, "listing asked for a document"
    assert not any("1099" in d.title or d.date_text == "2026-01-31"
                   for d in docs), "the Tax Forms panel was read"


def test_a_year_with_rows_is_not_read_as_empty_from_the_notice_before_it(marcus):
    """After an empty year the panel still says no documents for a moment.
    That notice is the year before's, and the rows are waited for."""
    site.collect_download_docs(marcus.page)            # ends on an empty year
    assert site._says_empty(marcus.page)
    assert site._select_year(marcus.page, "2025")
    assert [r.date for r in site._rows(marcus.page)] == ["2025-12-01"] * 2


def test_a_year_out_of_scope_is_never_selected(marcus):
    docs = site.collect_download_docs(marcus.page, keep=lambda y: False)
    assert [d.date_text for d in docs] == ["2026-02-01", "2026-01-01"]
    assert site._shown_year(marcus.page) == "2026"


def test_a_statement_of_another_year_is_found_pressed_once_and_saved(
        marcus, tmp_path):
    """Of two accounts with a statement of one day, the one asked for."""
    request = site.statement_request(marcus.page, "2025-12-01", "x0926")
    assert request is not None, "the row and its link were found"
    out = tmp_path / "Statements" / "2025-12-01 Marcus Statement.pdf"
    out.parent.mkdir(parents=True)
    got = delivery.deliver(marcus.page, request, out,
                           is_safe_url=site.is_safe_url, settle_ms=5000,
                           strict=False)
    assert (got.outcome, got.mechanism) == (delivery.SAVED, delivery.DOWNLOAD)
    assert out.read_bytes() == PDF
    assert marcus.asked == ["4"], "one press, of the row of that account"
    assert marcus.ctx.pages == [marcus.page]


def test_a_statement_that_is_not_listed_is_not_pressed_for(marcus):
    assert site.statement_request(marcus.page, "2025-11-01", "x4417") is None
    assert site.statement_request(marcus.page, "2026-02-01", "x0926") is None
    assert not marcus.asked


def test_the_tax_forms_tab_left_open_is_not_read_as_the_list(marcus):
    marcus.page.evaluate(
        "() => { document.getElementById('statements')"
        ".setAttribute('aria-selected', 'false'); }")
    assert not site._list_shows(marcus.page)
