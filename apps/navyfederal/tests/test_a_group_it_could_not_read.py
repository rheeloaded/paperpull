"""A group that could not be read is not taken to be folded.

The statements page lists each account as a group that opens to show its
statement rows. The download opens the account's group, folds every other
one, and presses the View of the first row on the page with the date,
which is the account's own only when the others are folded. A group whose
header did not answer in time was passed over, neither opened nor folded,
so a group left open from the last statement kept its rows on the page,
and on a day both accounts were billed its row came first and its View was
pressed for the other account.

Found by the census that followed CI run 36792330947, where E*TRADE passed
over a control that did not answer in time. The page is invented, in the
shape the app expects, and a folded group's rows leave the page.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import navyfederal_site as site
from paperpull_core.testkit import stall_reads

PAGE = """<!doctype html><html><body>
<div class="product-kind-description-row" role="button" aria-expanded="true" data-guid="hdr-a">Invented Checking</div>
<div id="rows-a"></div>
<div class="product-kind-description-row" role="button" aria-expanded="false" data-guid="hdr-b">Invented Visa</div>
<div id="rows-b"></div>
<script>
const row = k => "<table><tbody><tr><td>04/17/2031</td><td>Statement</td><td>" +
  "<button id='statement-link-" + k + "' aria-label='View statement' data-guid='view-" + k + "'>View</button>" +
  "</td></tr></tbody></table>";
const groups = () => document.querySelectorAll('.product-kind-description-row');
function draw() {
  for (const h of groups()) {
    const k = h.dataset.guid.slice(4);
    document.getElementById('rows-' + k).innerHTML = h.getAttribute('aria-expanded') === 'true' ? row(k) : '';
  }
}
for (const h of groups()) {
  h.addEventListener('click', () => {
    h.setAttribute('aria-expanded', h.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
    draw();
  });
}
window.pressed = [];
document.addEventListener('click', e => {
  const b = e.target.closest('button[id^=statement-link]');
  if (b) { window.pressed.push(b.dataset.guid); e.preventDefault(); }
}, true);
draw();
</script></body></html>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    pg.set_content(PAGE)
    yield pg
    browser.close()
    driver.stop()


def _pressed_by(page, req):
    req.trigger()
    return page.evaluate("window.pressed")


def test_the_other_groups_are_folded_before_the_row_is_found(page):
    """The twin with nothing stalled, so the test below is about the stall.
    The Checking group is open from the last statement, and the Visa's own
    View is the one pressed."""
    req = site.statement_request(page, "Invented Visa", "2031-04-17")
    assert req is not None and _pressed_by(page, req) == ["view-b"]


def test_a_group_whose_header_could_not_be_read_is_not_left_open(page, monkeypatch):
    """The open Checking group's header did not answer in time. It was
    passed over and left open, and its View was found first and would have
    been pressed for the Visa."""
    stall_reads(monkeypatch, {"hdr-a"}, locator=("inner_text",))
    req = site.statement_request(page, "Invented Visa", "2031-04-17")
    assert req is None, "it would press %s for the Visa" % _pressed_by(page, req)


def test_discovery_passes_over_an_account_while_a_group_could_not_be_read(page, monkeypatch):
    """Discovery files every row it sees under the group it opened, so a
    group left open put the Checking statement under the Visa."""
    stall_reads(monkeypatch, {"hdr-a"}, locator=("inner_text",))
    assert not site.expand_only(page, "Invented Visa")


def test_a_match_with_no_words_to_read_does_not_keep_an_account_closed(page):
    """The group selector matches any element whose class holds its words,
    an icon inside a header among them, and inner_text cannot read an
    icon. Counting that as a group that could not be read refused every
    statement on such a page, so the groups are judged as they stand,
    read in one call once the others are folded (review)."""
    page.evaluate("document.querySelector('[data-guid=hdr-b]').insertAdjacentHTML('beforeend', "
                  "\"<svg class='product-kind-description-row-icon' width='8' height='8'></svg>\")")
    assert page.locator(site.GROUP_SEL).count() == 3
    req = site.statement_request(page, "Invented Visa", "2031-04-17")
    assert req is not None and _pressed_by(page, req) == ["view-b"]
