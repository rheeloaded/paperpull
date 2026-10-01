"""A statement is found by its own date, never by a date that holds it.

Rows were picked by has_text, which finds its words anywhere in a row,
and the first spelling tried for January 6 is 1/6/2026, which is inside
11/6/2026. Statements are listed newest first, so on a page that wrote
dates that way a January statement took the November row above it and
pressed it. Ally checks which statement it served against the one asked
for, when it can tell, and otherwise the November PDF would have been
filed as January's.

Ally's page writes "September 06, 2026" today, so this is a page made up
in the same shape with the dates written as numbers. Every date is
invented, and the browser is refused the network, so nothing here can
reach a real site.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ally_site as site

PAGE = r"""<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body>
<main>
 <h1>Statements and Tax Forms</h1>
 <div role="tablist">
  <button role="tab" aria-selected="true">Statements</button>
  <button role="tab" aria-selected="false">Tax Forms</button>
 </div>
 <label for="statementYear">Year</label>
 <select id="statementYear"><option>2026</option></select>
 <table>
  <thead><tr><th>Date Posted</th><th>Statement Title</th></tr></thead>
  <tbody id="rows"></tbody>
 </table>
</main>
<script>
const ROWS = __ROWS__;
window.__pressed = [];
const body = document.getElementById('rows');
body.innerHTML = ROWS.map(d =>
  '<tr><td>' + d + '</td><td><span class="sr-only">Download statement for: </span>' +
  '<button type="button" class="link">Statement</button></td></tr>').join('');
for (const b of body.querySelectorAll('button')) {
  b.addEventListener('click', () => {
    const posted = b.closest('tr').cells[0].textContent;
    window.__pressed.push(posted);
    const pdf = '%PDF-1.4\n% invented statement ' + posted + '\n' + 'x'.repeat(300) + '\n%%EOF\n';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
    a.download = 'statement.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
  });
}
</script></body></html>"""


@pytest.fixture()
def statements(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    # Reaching the page is tested elsewhere, and a goto would name Ally's
    # real host. The page set below is the statements page.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def show(*rows):
        pg.set_content(PAGE.replace("__ROWS__", json.dumps(list(rows))))
        return pg
    yield show
    browser.close()
    driver.stop()


def test_a_january_statement_presses_its_own_row(statements, tmp_path):
    page = statements("11/6/2026", "1/6/2026")
    out = tmp_path / "s.pdf"
    assert site.ally_download(page, page.context, "", "2026-01-06", out)
    assert page.evaluate("window.__pressed") == ["1/6/2026"]
    assert b"invented statement 1/6/2026\n" in out.read_bytes()


def test_the_newer_statement_is_still_its_own(statements, tmp_path):
    page = statements("11/6/2026", "1/6/2026")
    out = tmp_path / "s.pdf"
    assert site.ally_download(page, page.context, "", "2026-11-06", out)
    assert page.evaluate("window.__pressed") == ["11/6/2026"]


def test_a_date_found_only_inside_another_presses_nothing(statements, tmp_path):
    """No row of January 6 or of February 1 is on the page, only rows whose
    dates hold their spellings."""
    for date in ("2026-01-06", "2026-02-01"):
        page = statements("11/6/2026", "12/1/2026", "11/16/2026")
        out = tmp_path / ("%s.pdf" % date)
        assert not site.ally_download(page, page.context, "", date, out), date
        assert not out.exists(), date
        assert page.evaluate("window.__pressed") == [], date


def test_a_date_with_spaces_of_its_own_is_still_found(statements, tmp_path):
    """has_text folds the page's whitespace before it compares a string,
    and a pattern is tested against the words as they stand, so the date
    is found however the page spaces it."""
    page = statements("September\u00a0 06,\n 2026")
    out = tmp_path / "s.pdf"
    assert site.ally_download(page, page.context, "", "2026-09-06", out)
    assert page.evaluate("window.__pressed") == ["September\u00a0 06,\n 2026"]


# -- the rows a date picks out ----------------------------------------------


@pytest.fixture()
def rows_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    yield ctx.new_page()
    browser.close()
    driver.stop()


def _found(page, html, date):
    page.set_content("<!doctype html><html><body>%s</body></html>" % html)
    rows, unread = site._rows_for_date(page, date)
    assert not unread, "every row here can be read"
    return [" ".join(text.split()) for _row, text in rows]


def test_a_date_beside_a_cell_of_numbers_is_found_and_only_its_own(rows_page):
    """A pattern is tested against a row's words with nothing between one
    cell and the next, so these rows read "411/6/2026" and "41/6/2026" and
    "September 06, 20262". The date is looked for in its own cell too."""
    html = ("<table>"
            "<tr><td>4</td><td>11/6/2026</td><td><button>Statement</button></td></tr>"
            "<tr><td>4</td><td>1/6/2026</td><td><button>Statement</button></td></tr>"
            "<tr><td>September 06, 2026</td><td>2</td><td><button>Statement</button></td></tr>"
            "</table>")
    assert _found(rows_page, html, "2026-01-06") == ["4 1/6/2026 Statement"]
    assert _found(rows_page, html, "2026-11-06") == ["4 11/6/2026 Statement"]
    assert _found(rows_page, html, "2026-09-06") == ["September 06, 2026 2 Statement"]


def test_a_month_with_its_zero_and_a_day_without_one(rows_page):
    """09/6/2026 was found while 9/6/2026 could be found anywhere in a row."""
    html = "<table><tr><td>09/6/2026</td><td><button>Statement</button></td></tr></table>"
    assert _found(rows_page, html, "2026-09-06") == ["09/6/2026 Statement"]


def test_a_date_with_a_zero_width_space_in_it(rows_page):
    """A string handed to has_text was compared with the page's zero-width
    spaces and soft hyphens taken out."""
    html = ("<table><tr><td>1/6/\u200b2026</td><td><button>Statement</button></td></tr>"
            "<tr><td>Sep\u00adtember 16, 2026</td><td><button>Statement</button></td></tr></table>")
    assert len(_found(rows_page, html, "2026-01-06")) == 1
    assert len(_found(rows_page, html, "2026-09-16")) == 1
