"""A statement posted on the 6th is found on a page that writes 06 (#56).

Reported on 0.39.1. Discovery read every statement from Ally's API, and
then each download stopped at "statement row not found". His page writes
the date posted as "September 06, 2026". The row finder looked for
"September 6, 2026" and "Sep 6, 2026", and a has_text filter is a
substring test, so no row ever matched. Every date in this suite was the
16th, where the two spellings are the same, so a day below ten was never
tried.

The page below is made up in the shape of his screenshot. A Year picker,
then a table headed Date Posted and Statement Title with one row per
statement, and the title is a button that says Statement beside a hidden
"Download statement for" label. Pressing it downloads the PDF. Every date
is invented, and the browser is refused the network, so nothing here can
reach a real site.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ally_site as site

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
ROWS = {
    "2026": ["%s 06, 2026" % m for m in reversed(MONTHS[:9])],
    "2025": ["%s 06, 2025" % m for m in reversed(MONTHS)],
}

PAGE = """<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body>
<nav><ul><li><a href="#">Accounts</a></li><li><a href="#">Status Tracker</a></li></ul></nav>
<main>
 <h1>Statements and Tax Forms</h1>
 <div role="tablist">
  <button role="tab" aria-selected="true">Statements</button>
  <button role="tab" aria-selected="false">Tax Forms</button>
 </div>
 <p>Primary account owners can view and download 7 years of statements and tax forms.</p>
 <label for="statementYear">Year</label>
 <select id="statementYear"><option>2026</option><option>2025</option></select>
 <table>
  <thead><tr><th>Date Posted</th><th>Statement Title</th></tr></thead>
  <tbody id="rows"></tbody>
 </table>
</main>
<script>
const ROWS = %(rows)s;
window.__pressed = [];
function draw() {
  const year = document.getElementById('statementYear').value;
  const body = document.getElementById('rows');
  body.innerHTML = ROWS[year].map(d =>
    '<tr><td>' + d + '</td><td><span class="sr-only">Download statement for: </span>' +
    '<button type="button" class="link">Statement</button></td></tr>').join('');
  for (const b of body.querySelectorAll('button')) {
    b.addEventListener('click', () => {
      const posted = b.closest('tr').cells[0].textContent;
      window.__pressed.push(posted);
      const pdf = '%%PDF-1.4\\n%% invented statement ' + posted + '\\n' +
                  'x'.repeat(300) + '\\n%%%%EOF\\n';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
      a.download = 'statement.pdf';
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }
}
document.getElementById('statementYear').addEventListener('change', draw);
draw();
</script></body></html>""" % {"rows": json.dumps(ROWS)}


@pytest.fixture()
def ally(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    pg.set_content(PAGE)
    # Reaching the page is tested elsewhere, and a goto would name Ally's
    # real host. The page above is the statements page.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    yield pg
    browser.close()
    driver.stop()


def test_both_spellings_of_a_day_below_ten_are_looked_for():
    needles = site._date_needles("2026-09-06")
    for spelled in ("September 06, 2026", "September 6, 2026",
                    "Sep 06, 2026", "Sep 6, 2026", "09/06/2026", "9/6/2026"):
        assert spelled in needles, spelled
    # A day of two digits has one spelling, and it is listed once.
    needles = site._date_needles("2026-08-16")
    assert len(needles) == len(set(needles))
    assert "August 16, 2026" in needles


def test_the_statement_posted_on_the_sixth_is_pressed(ally, tmp_path):
    out = tmp_path / "s.pdf"
    assert site.ally_download(ally, ally.context, "", "2026-09-06", out)
    assert b"invented statement September 06, 2026" in out.read_bytes()
    assert ally.evaluate("window.__pressed") == ["September 06, 2026"]


def test_an_earlier_year_is_picked_before_its_row_is_found(ally, tmp_path):
    out = tmp_path / "s.pdf"
    assert site.ally_download(ally, ally.context, "", "2025-03-06", out)
    assert b"invented statement March 06, 2025" in out.read_bytes()
    assert ally.evaluate("window.__pressed") == ["March 06, 2025"]


def test_a_day_that_only_ends_the_same_presses_nothing(ally, tmp_path):
    """The 16th and the 26th are not the 6th, and a day with no row is
    not some neighbor's."""
    for date in ("2026-09-16", "2026-09-26", "2026-09-07"):
        out = tmp_path / ("%s.pdf" % date)
        assert not site.ally_download(ally, ally.context, "", date, out), date
        assert not out.exists()
    assert ally.evaluate("window.__pressed") == []
