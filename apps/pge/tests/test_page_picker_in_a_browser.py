"""The Jump to picker in a real browser, from the review of round eight.

Until round eight every label read empty, so the picker's option was never
clicked and every jump went by value, the only jump proven on his history
(round three found a bill on page 2 with it, round five walked all seven
pages). Reading labels brought the option click back, first and with no
limit on its wait, and an option that could not take a click spent thirty
seconds, raised, and skipped the by-value jump. A review showed that here.

The picker below is shaped like the one his logs describe, a
lightning-combobox reading Jump to whose parent hears a change event
carrying the page. Every date here is invented, and the timings mirror the
app's own thirty second default.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.set_default_timeout(30000)          # what pge_docs sets
    ctx.route("https://myaccount.pge.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body="<h1>history</h1>"))
    pg = ctx.new_page()
    pg.goto("https://myaccount.pge.com/myaccount/s/bill-and-payment-history")
    yield pg
    browser.close()
    driver.stop()


OPTION = "<lightning-base-combobox-item data-value='%d' role='option' %s>%d</lightning-base-combobox-item>"

# The list hangs below the picker the way a dropdown does, so a click on
# the picker lands on the picker and not on one of its options.
PICKER = """<body>
<style>
  lightning-combobox { display: inline-block; position: relative; padding: 4px; }
  .list { position: absolute; top: 100%%; left: 0; }
  lightning-base-combobox-item { display: block; }
</style>
<table><tbody id="rows"></tbody></table>
<div class="pagination-block">
  <lightning-combobox aria-label="Jump to" id="cb"><span id="shown">1</span><div class="list">%(options)s</div></lightning-combobox>
</div>
%(extra)s
<script>
  const pages = {1: ['01/05/2031', '12/05/2030'], 2: ['11/05/2030', '10/05/2030'],
                 3: ['09/05/2030', '08/05/2030']};
  const cb = document.getElementById('cb');
  cb.options = [{value: '1'}, {value: '2'}, {value: '3'}];
  window.opened = 0; window.optionClicks = 0; window.escapes = 0;
  function draw(p) {
    cb.value = String(p);
    document.getElementById('shown').textContent = String(p);
    document.getElementById('rows').innerHTML = pages[p].map(d =>
      '<tr><td>' + d + '</td><td>Bill Charges</td><td><a class="pdf-link">View Bill PDF</a></td></tr>').join('');
  }
  draw(1);
  if (%(hears_value)s) cb.addEventListener('change', e => draw(Number(e.detail.value)));
  cb.addEventListener('click', e => { if (e.target === cb || e.target.id === 'shown') window.opened++; });
  for (const o of cb.querySelectorAll('lightning-base-combobox-item')) {
    o.addEventListener('click', e => { e.stopPropagation(); window.optionClicks++; draw(Number(o.dataset.value)); });
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') window.escapes++; });
</script></body>"""


def _picker(page, hears_value=True, option_style="", extra=""):
    options = "".join(OPTION % (n, option_style, n) for n in (1, 2, 3))
    page.set_content(PICKER % {"options": options, "extra": extra,
                               "hears_value": "true" if hears_value else "false"})


def _first_date(page):
    return page.evaluate("document.querySelector('#rows td').textContent")


def test_the_picker_is_asked_by_value_first_and_nothing_is_clicked(page):
    """The jump proven on his history goes first, and it clicks nothing."""
    _picker(page)
    assert site.goto_page_number(page, 2) is True
    assert _first_date(page) == "11/05/2030"
    assert page.evaluate("window.opened") == 0, "the picker was opened"
    assert page.evaluate("window.optionClicks") == 0


def test_a_hidden_option_does_not_stop_the_jump_that_works(page):
    """The review's case. The option is in the page but hidden, and the
    picker hears its value. The draft clicked the option first, waited out
    the thirty second default, raised, and never asked by value."""
    _picker(page, option_style="style='display:none'")
    t0 = time.monotonic()
    assert site.goto_page_number(page, 2) is True
    took = time.monotonic() - t0
    assert _first_date(page) == "11/05/2030"
    assert took < 15, "the jump took %.1fs, the by-value jump takes about one" % took


def test_when_the_value_is_not_heard_the_option_is_clicked(page):
    """The fallback, for a picker whose parent does not hear the value."""
    _picker(page, hears_value=False)
    assert site.goto_page_number(page, 3) is True
    assert _first_date(page) == "09/05/2030"
    assert page.evaluate("window.opened") == 1
    assert page.evaluate("window.optionClicks") == 1


# A dialog that appears once the picker opens and covers everything, with
# a button of its own that no guard has looked at.
COVER_ON_OPEN = """() => {
  window.promo = 0;
  document.getElementById('cb').addEventListener('click', () => {
    if (document.getElementById('promo')) return;
    document.body.insertAdjacentHTML('beforeend',
      '<div role="dialog" style="position:fixed;inset:0;z-index:10;background:#fff">' +
      '<button id="promo" style="width:100%;height:100%">Enroll in paperless</button></div>');
    document.getElementById('promo').addEventListener('click', () => window.promo++);
  });
}"""


def test_an_option_under_a_dialog_is_reached_by_its_own_click_never_the_dialog(page):
    """An option that cannot take a click gets its own click, which reaches
    that element and nothing else. The draft waited thirty seconds on the
    click and gave up."""
    _picker(page, hears_value=False)
    page.evaluate(COVER_ON_OPEN)
    t0 = time.monotonic()
    assert site.goto_page_number(page, 2) is True
    took = time.monotonic() - t0
    assert _first_date(page) == "11/05/2030"
    assert page.evaluate("window.promo") == 0, "the dialog took the click"
    assert page.evaluate("window.optionClicks") == 1
    assert took < 25, "the jump took %.1fs" % took


# A parent that only hears the picker's value once the picker has been
# opened. Whether his does is not known. What is known is the order the
# jump ran in when it walked all seven of his pages, open, Escape, value.
HEARS_ONCE_OPENED = """<script>
  document.getElementById('cb').addEventListener('change', e => {
    if (window.opened > 0) draw(Number(e.detail.value));
  });
</script>"""


def test_the_sequence_that_walked_his_history_is_the_last_thing_tried(page):
    """Rounds three and five reached every page by opening the picker,
    finding no option in it, pressing Escape and asking by value. The round
    eight repair asked by value first, with the picker never opened, and
    gave up after the option path without asking by value again, so that
    exact sequence was no longer anywhere (second review of round eight)."""
    page.set_content(PICKER % {"options": "", "extra": HEARS_ONCE_OPENED,
                               "hears_value": "false"})
    assert site.goto_page_number(page, 2) is True
    assert _first_date(page) == "11/05/2030"
    assert page.evaluate("window.opened") == 1
    assert page.evaluate("window.escapes") >= 1
    assert page.evaluate("window.optionClicks") == 0


STRAY = ("<lightning-combobox aria-label='Filter'>"
         "<lightning-base-combobox-item id='stray' data-value='2' role='option'>2"
         "</lightning-base-combobox-item></lightning-combobox>"
         "<script>window.stray = 0; document.getElementById('stray')"
         ".addEventListener('click', () => window.stray++);</script>")


def test_an_option_in_another_list_is_never_the_one_clicked(page):
    """The option was looked for across the whole page. A picker with no
    list of its own could click another list's option reading the same
    number. It is looked for inside the picker now, and nothing is left
    open over the rows when the jump fails."""
    page.set_content(PICKER % {"options": "", "extra": STRAY, "hears_value": "false"})
    assert site.goto_page_number(page, 2) is False
    assert page.evaluate("window.stray") == 0, "another list's option was clicked"
    assert _first_date(page) == "01/05/2031"
    assert page.evaluate("window.escapes") >= 1
