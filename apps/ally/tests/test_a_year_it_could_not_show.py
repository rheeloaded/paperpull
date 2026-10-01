"""A tax form is pressed only when the year picker is known to show its year.

A tax row on Ally's page names its form, 1099-INT, and nothing that says
which tax year it is for, and every year has one. So the year the list
shows is what decides which year's form is pressed, and the list follows
its year picker. The download moved the picker to the form's year and
went on whether or not the move was made. It took a picker whose options
it could not read for a page with no picker, and with no picker it
skipped the move and the check that the year can be reached at all. Each
way the form on screen, another year's, was pressed and saved under this
one's name. The check of which document Ally served catches that only
when the record carries an id and the page is seen asking for the form by
it.

Found by a read-only audit on 2026-10-01, after CI run 36792330947 showed
reads failing on a slow runner. The page below is invented in the shape of
Ally's Statements and Tax Forms page, every date and form on it is made
up, and the browser is refused the network.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ally_site as site
from paperpull_core import controls
from paperpull_core.testkit import stall_reads

LISTS = {
    "statements": {
        "2026": ["September 06, 2026", "August 06, 2026"],
        "2025": ["September 06, 2025", "August 06, 2025"],
    },
    # One 1099-INT a tax year, posted the January after it.
    "tax": {
        "2025": ["January 10, 2026"],
        "2024": ["January 12, 2025"],
        "2023": ["January 11, 2024"],
    },
}
TAX_YEAR_OPTIONS = {"taxYear-2025", "taxYear-2024", "taxYear-2023"}
# The tax picker's options could not be read, or the words that say what
# the picker is could not.
UNREAD = {
    "its options": dict(stalled=TAX_YEAR_OPTIONS, locator=("all_inner_texts",)),
    "what it is": dict(stalled={"taxYear"}, locator=("evaluate",), scripts=(controls.IDENTITY_JS,)),
}

PAGE = """<!doctype html><html><head><style>
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
</style></head><body>
<main>
 <h1>Statements and Tax Forms</h1>
 <div role="tablist">
  <button role="tab" data-tab="statements" aria-selected="true">Statements</button>
  <button role="tab" data-tab="tax" aria-selected="false">Tax Forms</button>
 </div>
 <div id="picker"></div>
 <table>
  <thead><tr><th>Date Posted</th><th>Document</th></tr></thead>
  <tbody id="rows"></tbody>
 </table>
</main>
<script>
const LISTS = %(lists)s;
const PICKER = %(picker)s;
window.__pressed = [];

function save(words) {
  const pdf = '%%PDF-1.4\\n%% invented ' + words + '\\n' + 'x'.repeat(300) + '\\n%%%%EOF\\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
  a.download = 'document.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function draw(tab, year) {
  const tax = tab === 'tax';
  const body = document.getElementById('rows');
  body.innerHTML = LISTS[tab][year].map(posted =>
    '<tr><td>' + posted + '</td><td><span class="sr-only">Download ' +
    (tax ? 'tax form' : 'statement') + ' for: </span><button type="button">' +
    (tax ? '1099-INT' : 'Statement') + '</button></td></tr>').join('');
  for (const b of body.querySelectorAll('button')) {
    b.addEventListener('click', () => {
      const words = tax ? year + ' 1099-INT'
                        : 'statement ' + b.closest('tr').cells[0].textContent;
      window.__pressed.push(words);
      save(words);
    });
  }
}

// Opens a tab on its first year, the way the page shows it at first.
function open(tab) {
  for (const t of document.querySelectorAll('[role=tab]'))
    t.setAttribute('aria-selected', String(t.dataset.tab === tab));
  const years = Object.keys(LISTS[tab]).sort().reverse();
  let shown = years[0];
  const picker = document.getElementById('picker');
  picker.innerHTML = '';
  if (!(tab === 'tax' && PICKER === 'none')) {
    const id = tab === 'tax' ? 'taxYear' : 'statementYear';
    const words = tab === 'tax' && PICKER === 'keeps a word' ? ['All years'] : [];
    picker.innerHTML = '<label for="' + id + '">Year</label><select id="' + id +
      '" data-guid="' + id + '">' + words.concat(years).map(y =>
        '<option data-guid="' + id + '-' + y + '">' + y + '</option>').join('') +
      '</select>';
    const sel = document.getElementById(id);
    sel.value = shown;
    sel.addEventListener('change', () => {
      // A picker held by the page's own state puts back what it showed
      // when the change does not reach that state, and the list stays as
      // it was.
      if (tab === 'tax' && PICKER === 'keeps') { sel.value = shown; return; }
      if (tab === 'tax' && PICKER === 'keeps a word') { sel.value = 'All years'; return; }
      shown = sel.value;
      draw(tab, shown);
    });
  }
  if (tab === 'tax' && PICKER === 'two') {
    // A second dropdown of years after the one the list follows, which
    // moves nothing.
    picker.insertAdjacentHTML('beforeend', '<label for="archiveYear">Archive year</label>' +
      '<select id="archiveYear" data-guid="archiveYear">' +
      years.map(y => '<option>' + y + '</option>').join('') + '</select>');
  }
  draw(tab, shown);
}
window.__open = open;
for (const t of document.querySelectorAll('[role=tab]'))
  t.addEventListener('click', () => open(t.dataset.tab));
open('statements');
</script></body></html>"""


@pytest.fixture()
def ally(monkeypatch):
    """Opens the page, with a tax year picker that works, one that keeps
    its year, one that puts a word back, one followed by a second dropdown
    of years, or none."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda route: route.abort())
    # Reaching the page is tested elsewhere, and a goto would name Ally's
    # real host. The page above is the documents page.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def open_page(picker="works"):
        pg = ctx.new_page()
        pg.set_content(PAGE % {"lists": json.dumps(LISTS), "picker": json.dumps(picker)})
        # The page draws as soon as it is asked, so the pauses a run takes
        # for Ally's own page are cut short, as AmFam's blob test does.
        wait = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        return pg
    yield open_page
    browser.close()
    driver.stop()


def _tax_form(page, year, tmp_path):
    """Ask for one year's 1099-INT the way a run does, as discovery
    recorded it from Ally's API, filed on the last day of its tax year."""
    out = tmp_path / ("%s 1099-INT.pdf" % year)
    got = site.ally_download(page, page.context, "", "%s-12-31" % year, out,
                             kind="tax", title="Form 1099-INT")
    return got, out


def _pressed_nothing(page, caplog, why, got, out):
    """Nothing was pressed or saved, and the log says it was for `why`."""
    pressed = page.evaluate("window.__pressed")
    assert not got and not out.exists() and pressed == [], \
        "it pressed %s and %s" % (pressed, "saved it" if out.exists() else "returned %r" % got)
    said = [r.getMessage() for r in caplog.records]
    assert any(why in s for s in said), "nothing was pressed, but not because %s. It said %s" % (why, said)


def _pressed(page, year, got, out):
    assert got and b"invented %s 1099-INT" % year.encode() in out.read_bytes()
    assert page.evaluate("window.__pressed") == ["%s 1099-INT" % year]


def test_the_form_of_the_year_asked_for_is_pressed(ally, tmp_path):
    """The twin with nothing in the way, so the tests below are about what
    is. The year on screen first, then one the picker has to move to."""
    page = ally()
    for year in ("2025", "2023"):
        got, out = _tax_form(page, year, tmp_path)
        assert got, year
        assert b"invented %s 1099-INT" % year.encode() in out.read_bytes()
    assert page.evaluate("window.__pressed") == ["2025 1099-INT", "2023 1099-INT"]


@pytest.mark.parametrize("unread", list(UNREAD))
def test_a_year_picker_that_could_not_be_read_presses_nothing(ally, monkeypatch, caplog, tmp_path, unread):
    """The picker's options did not answer, or the words that say what it
    is did not, and it was taken for no picker at all. The list stayed on
    2025 and its form was pressed for 2024's."""
    page = ally()
    stall_reads(monkeypatch, **UNREAD[unread])
    _pressed_nothing(page, caplog, "a dropdown could not be read", *_tax_form(page, "2024", tmp_path))


@pytest.mark.parametrize("unread", list(UNREAD))
def test_a_year_picker_passed_over_for_another_presses_nothing(ally, monkeypatch, caplog, tmp_path, unread):
    """The list follows the first dropdown of years, which could not be
    read, so the second was taken for the year picker and set to 2024,
    and the list stayed on 2025. Read again, the second does say 2024, so
    only the first one going unread says the year is not known."""
    page = ally("two")
    stall_reads(monkeypatch, **UNREAD[unread])
    _pressed_nothing(page, caplog, "a dropdown before the year picker could not be read",
                     *_tax_form(page, "2024", tmp_path))


def test_a_year_picker_that_would_not_move_presses_nothing(ally, monkeypatch, caplog, tmp_path):
    """Setting the picker to 2024 failed, and the answer that said so was
    thrown away. The list stayed on 2025 and its form was pressed."""
    page = ally()
    stall_reads(monkeypatch, {"taxYear"}, locator=("select_option",))
    _pressed_nothing(page, caplog, "the year picker would not move", *_tax_form(page, "2024", tmp_path))


def test_a_year_picker_that_would_not_move_to_the_year_it_shows_is_enough(ally, monkeypatch, tmp_path):
    """The twin. Setting the picker failed, and it already showed 2025, the
    year asked for, so 2025's form is pressed as it was before."""
    page = ally()
    stall_reads(monkeypatch, {"taxYear"}, locator=("select_option",))
    _pressed(page, "2025", *_tax_form(page, "2025", tmp_path))


@pytest.mark.parametrize("picker, why", [
    ("keeps", "the year picker shows 2025"),
    ("keeps a word", "the year picker shows another option"),
])
def test_a_year_picker_that_puts_back_what_it_showed_presses_nothing(ally, caplog, tmp_path, picker, why):
    """The picker was set to 2024 and the page put back what it showed
    before. Setting it raised nothing, so only reading it again shows the
    move did not take. A word the page shows is not written to the log."""
    page = ally(picker)
    _pressed_nothing(page, caplog, why, *_tax_form(page, "2024", tmp_path))
    assert "All years" not in caplog.text


def test_a_year_picker_that_could_not_be_read_again_presses_nothing(ally, monkeypatch, caplog, tmp_path):
    """The picker was set to 2024 and what it shows then did not answer.
    Before, it was never read again, and 2024's form was pressed, the
    right one, on the word of the set alone. Now a set that is not read
    back is not taken as the year."""
    page = ally()
    stall_reads(monkeypatch, {"taxYear"}, locator=("evaluate",), scripts=(getattr(site, "_SHOWN_JS", None),))
    _pressed_nothing(page, caplog, "the year picker could not be read", *_tax_form(page, "2024", tmp_path))


def test_a_list_that_goes_back_to_its_first_year_before_the_press_presses_nothing(
        ally, monkeypatch, caplog, tmp_path):
    """The picker was set to 2024 and read back as 2024. Then, as a view
    that finishes loading late does, the tax list was drawn again on its
    first year, 2025, just before its rows were looked for, and 2025's
    form was pressed for 2024's."""
    page = ally()
    find = site._find_tax_row_control

    def late(pg, *args, **kwargs):
        pg.evaluate("window.__open('tax')")
        return find(pg, *args, **kwargs)
    monkeypatch.setattr(site, "_find_tax_row_control", late)
    _pressed_nothing(page, caplog, "the year picker no longer shows 2024", *_tax_form(page, "2024", tmp_path))


@pytest.mark.parametrize("year", ["2024", "2025"])
def test_a_tax_list_with_no_year_picker_presses_nothing(ally, caplog, tmp_path, year):
    """With no picker nothing says which year the list shows, and every
    year has a 1099-INT. 2025's form, the one on screen, was pressed for
    2024's, and for 2025's it was pressed only by luck, so it is not
    pressed either."""
    page = ally("none")
    _pressed_nothing(page, caplog, "no year picker was found", *_tax_form(page, year, tmp_path))


def test_a_year_the_picker_cannot_reach_presses_nothing(ally, caplog, tmp_path):
    """Ally's API lists a form older than its picker's first year, and the
    form on screen is not it. This one was refused before, and still is."""
    page = ally()
    _pressed_nothing(page, caplog, "cannot be reached from the page", *_tax_form(page, "2019", tmp_path))


def test_a_statement_is_found_by_its_own_date_with_the_picker_unread(ally, monkeypatch, tmp_path):
    """Statements need none of this. Their rows are found by a date with
    the year in it, so with the picker unread the statement on screen is
    still saved, and one of another year is not taken for it."""
    page = ally()
    stall_reads(monkeypatch, {"statementYear-2026", "statementYear-2025"}, locator=("all_inner_texts",))
    shown = tmp_path / "shown.pdf"
    assert site.ally_download(page, page.context, "", "2026-08-06", shown)
    assert b"invented statement August 06, 2026" in shown.read_bytes()
    other = tmp_path / "other.pdf"
    assert not site.ally_download(page, page.context, "", "2025-08-06", other)
    assert not other.exists()
    assert page.evaluate("window.__pressed") == ["statement August 06, 2026"]
