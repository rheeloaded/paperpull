"""E*TRADE's document table is built from web components.

A tester's trace came back saying "the row holds nothing that looks
clickable" while the row plainly held a document, and the outline beside
it showed why. The cell was a `slot`, and what a slot shows lives
somewhere else entirely, so a walk over each element's own children
reached the slot and stopped (#36).

These run in a real browser, because a shadow root is the one thing a
fake page cannot honestly stand in for.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

ROW = """
<table><tbody>
<tr class="row_level-1">
  <td><div>06/30/26</div></td>
  <td><div>Individual Brokerage - 1551</div></td>
  <td><div><my-cell><slot name="doc"></slot></my-cell></div></td>
</tr>
</tbody></table>
<script>
class MyCell extends HTMLElement {
  connectedCallback() {
    const sr = this.attachShadow({mode: 'open'});
    sr.innerHTML = '<a href="/doc/9.pdf">Account Statement</a><slot></slot>';
  }
}
customElements.define('my-cell', MyCell);
</script>
"""

DATES = ["06/30/26", "06/30/2026"]
TITLE = "Account Statement"


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def _walk(page):
    page.set_content(ROW)
    return page.evaluate(site._ROW_BY_DATE_JS, [DATES, TITLE]) or {}


def test_the_link_inside_a_shadow_root_is_found(page):
    got = _walk(page)
    assert [c["text"] for c in got["cands"]] == [TITLE], \
        "the document's own link is in the shadow root, not in the row's children"


def test_the_outline_shows_where_it_was(page):
    outline = "\n".join(_walk(page)["outline"])
    assert "my-cell" in outline
    assert "a = Account Statement" in outline, outline
    assert "href=/doc/9.pdf" in outline


def test_a_row_with_nothing_in_its_shadow_still_answers(page):
    page.set_content("<table><tbody><tr><td><div>06/30/26</div></td>"
                     "<td><div>Individual Brokerage - 1551</div></td></tr></tbody></table>")
    got = page.evaluate(site._ROW_BY_DATE_JS, [DATES, TITLE]) or {}
    assert got.get("cands") == []
    assert got.get("outline")


def test_the_walk_is_in_the_source_for_both_the_outline_and_the_candidates():
    js = site._ROW_BY_DATE_JS
    assert "assignedElements" in js and "shadowRoot" in js
    assert js.count("inside(el)") >= 2, "the outline and the candidates both use it"
