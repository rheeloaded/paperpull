"""What the discovery and download traces may say, from a list, never by shape.

discovery-trace.json and download-attempt.json are attached to public
issues. The same review found two places that still let page words out by
their shape.

The periods the picker offered were every short visible text on the page
that looked like a period, and a period could be any four digits, so an
account's last four printed alone on the page left in the file.

Parameter names, of an address and of a request's body, were judged by
their shape, so a name like "JohnSmith" left as written. They leave now
only when they are on the list of names E*TRADE was seen to use, and
anything else is written as # so the count still shows.

Everything here is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

BROKERAGE = "Brokerage Statement"
ALONE = "2025-10-31"


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


# --- the periods offered -------------------------------------------------------

PICKER_PAGE = """<!doctype html><html><body>
<div><span>Account ending</span> <span>4242</span></div>
<div><span>Invented Household</span> <span>1984</span></div>
<button type="button" id="picker" aria-label="Timeframe ,  Last 90 Days"
  onclick="document.getElementById('list').hidden = false">Last 90 Days</button>
<ul id="list" role="listbox" hidden>
  <li role="option">Last 90 Days</li><li role="option">Last 12 Months</li>
  <li role="option">Year To Date</li><li role="option">2025</li><li role="option">2024</li>
</ul>
</body></html>"""


def test_the_periods_offered_hold_only_period_words(page, monkeypatch):
    """An account's last four printed alone on the page passed for a period
    and left in discovery-trace.json (review, P4). A year 19xx or 20xx
    still counts, which a four digit ending like 1984 can look like, so
    only what appeared after the picker opened is read, as before."""
    monkeypatch.setattr(site, "_choose_period", lambda *a, **k: False)
    page.set_content(PICKER_PAGE)
    trace: list = []
    site.widen_date_filter(page, [], trace)
    note = next(t for t in trace if t.get("note") == "period picker")
    assert "4242" not in json.dumps(trace), note
    assert note["offered"] == ["2024", "2025", "Last 12 Months", "Last 90 Days", "Year To Date"], note
    assert note["plan"] == ["Year To Date", "2025", "2024"], note


@pytest.mark.parametrize("text, period", [
    ("2025", True), ("1999", True), ("Year To Date", True), ("Last 90 Days", True),
    ("Last 12 Months", True), ("All", True),
    ("4242", False), ("0917", False), ("Last 4242 Days", False), ("2025 4242", False),
])
def test_a_period_is_a_period_word(text, period):
    assert site.is_date_filter(text) is period


# --- parameter names --------------------------------------------------------

def test_a_parameter_name_leaves_only_from_the_list():
    """Names were judged by their shape, so "JohnSmith" left as written
    (review, P5). Each name not on the list is one #, so the count shows."""
    got = site.mask_href("https://us.etrade.com/etx/pxy/accountdocs?acct=1551&JohnSmith=1&IRA_Rollover=2"
                         "&RequestID=7&SeqID=8")
    assert got == "etrade:/etx/pxy/accountdocs?#&#&#&RequestID&SeqID", got
    assert site.mask_href("https://us.etrade.com/login/sar?n=123") == "etrade:/login/sar?n"


PAGE = """<!doctype html><html><body>
<ul><li><span>10/31/25</span> <span data-guid='g-title'>%s</span></li></ul>
<script>
document.querySelector('[data-guid=g-title]').addEventListener('click', () => {
  fetch('https://us.etrade.com/etx/pxy/accountdocs/v2/searchItems?RequestID=1&JohnSmith=2', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({TimeFrame: '2025', pageNum: 1, JaneExample: 'x', Invented_Rollover: 2})});
});
</script></body></html>""" % BROKERAGE


def test_the_download_trace_writes_request_names_only_from_the_list(browser, monkeypatch, tmp_path):
    """The requests a press sets off go into download-attempt.json with the
    names of their parameters and of their body's keys. Those went through
    the same shape filter, so a key named for a person left as written."""
    monkeypatch.setattr(site, "_LISTED", {ALONE: 1})
    monkeypatch.setattr(site, "_LISTED_TITLES", {ALONE: {BROKERAGE}})
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        el.click(timeout=3000)
        pg.wait_for_timeout(500)
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)
    ctx = browser.new_context()
    ctx.route("https://us.etrade.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html" if r.request.method == "GET" else "application/json",
        body=PAGE if r.request.method == "GET" else "{}"))
    try:
        pg = ctx.new_page()
        pg.goto("https://us.etrade.com/etx/pxy/documents")
        trace: list = []
        assert not site.download_bill(pg, tmp_path / "dl", ALONE, tmp_path / "out.pdf", BROKERAGE, trace)
        asked = [r for t in trace if t.get("note") == "requests after that click" for r in t["requests"]]
        assert asked and asked[0]["method"] == "POST", trace
        assert asked[0]["url"] == "etrade:/etx/pxy/accountdocs/v2/searchItems?#&RequestID", asked
        assert asked[0]["post_keys"] == ["#", "#", "TimeFrame", "pageNum"], asked
        text = json.dumps(trace)
        for leaked in ("JohnSmith", "JaneExample", "Rollover", "Brokerage"):
            assert leaked not in text, (leaked, text)
    finally:
        ctx.close()
