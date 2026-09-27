"""E*TRADE's document table is built from web components.

A tester's trace came back saying "the row holds nothing that looks
clickable" while the row plainly held a document, and the outline beside
it showed why. The cell was a `slot`, and what a slot shows lives
somewhere else entirely, so a walk over each element's own children
reached the slot and stopped (#36).

These run in a real browser, because a shadow root is the one thing a
fake page cannot honestly stand in for. The date, the account and the
link are invented, in the shape the trace showed.
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
  <td><div>07/31/26</div></td>
  <td><div>Invented Brokerage - 4242</div></td>
  <td><div><my-cell><slot name="doc"></slot></my-cell></div></td>
</tr>
</tbody></table>
<script>
class MyCell extends HTMLElement {
  connectedCallback() {
    const sr = this.attachShadow({mode: 'open'});
    sr.innerHTML = '<a href="/doc/statement.pdf">Account Statement</a><slot></slot>';
  }
}
customElements.define('my-cell', MyCell);
</script>
"""

ISO = "2026-07-31"
DATES = ["07/31/26", "07/31/2026"]
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
    return page.evaluate(site._ROW_BY_DATE_JS, [DATES, TITLE, False]) or {}


def test_the_link_inside_a_shadow_root_is_found(page):
    got = _walk(page)
    assert [c["text"] for c in got["cands"]] == [TITLE], \
        "the document's own link is in the shadow root, not in the row's children"
    assert got["cands"][0]["kind"] == "title"


def test_the_outline_shows_where_it_was_and_nothing_it_said(page, monkeypatch):
    """The outline goes into download-attempt.json, which is attached to a
    public issue. It used to carry each element's own text, the account
    column among it (#36, review). Now tags, roles and shapes."""
    monkeypatch.setattr(site, "_LISTED", {})
    page.set_content(ROW)
    found = site._row_by_date(page, ISO, TITLE)
    outline = "\n".join(site._outline_line(p, TITLE) for p in found["outline"])
    assert "my-cell" in outline
    assert "~a = <the title> href=relative pdf" in outline, outline
    assert "row_level-1" in outline
    for leaked in ("Invented", "Brokerage", "4242", TITLE, "statement.pdf", "07/31"):
        assert leaked not in outline, leaked


def test_a_row_that_names_nothing_is_taken_only_when_the_lists_say_it_is_alone(page):
    """A row with the date and no element naming the document is the
    document's only when the lists the page loaded held one document on
    that date. Otherwise it could be another document of the same day."""
    page.set_content("<table><tbody><tr><td><div>07/31/26</div></td>"
                     "<td><div>Invented Brokerage - 4242</div></td></tr></tbody></table>")
    alone = page.evaluate(site._ROW_BY_DATE_JS, [DATES, TITLE, True]) or {}
    assert alone.get("cands") == []
    assert alone.get("outline")
    unsure = page.evaluate(site._ROW_BY_DATE_JS, [DATES, TITLE, False]) or {}
    assert unsure == {"refused": "no row of this date names this document", "rows": 1, "named": 0}


def test_the_walk_is_in_the_source_for_both_the_outline_and_the_candidates():
    js = site._ROW_BY_DATE_JS
    assert "assignedElements" in js and "shadowRoot" in js
    assert js.count("inside(el)") >= 2, "the outline and the candidates both use it"
