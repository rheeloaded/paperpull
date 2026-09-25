"""The period picker the tester's recording showed, driven for real.

On 0.34.0 discovery still found one document (#36). His recording of
the two older statements he fetched by hand showed why. The picker is a
button named "Timeframe ,  Last 90 Days", its label and its period
together, and the app looked for a button named exactly "Last 90 Days".
It never found one, so no period was ever chosen and every round read
the default ninety days. The recording also showed Apply running the
search inside the page with no navigation at all, and "Year To Date"
sitting beside the years, where the old choice would have taken it
alone and stopped at this year.

The page below copies those facts, the button's name, the options as
role=option, a form whose Apply the page handles itself, and a fresh
searchItems answer per period. It runs in a real browser because the
accessible name is what went wrong, and only a browser computes one.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

# One statement per period, dated inside it. The default is the last
# ninety days, which held one statement in his account too.
DATES = {"Last 90 Days": ["2026-08-31"],
         "Year To Date": ["2026-08-31", "2026-03-31"],
         "2026": ["2026-08-31", "2026-03-31"],
         "2025": ["2025-12-31", "2025-09-30", "2025-06-30"],
         "2024": ["2024-12-31"]}

PAGE = """<!doctype html><html><body>
<form id="filters">
  <button type="button" id="picker" aria-label="Timeframe ,  Last 90 Days"
          aria-haspopup="listbox">Last 90 Days</button>
  <div role="listbox" id="list" style="display:none">
    <div role="option">Last 90 Days</div>
    <div role="option">Year To Date</div>
    <div role="option">2026</div>
    <div role="option">2025</div>
    <div role="option">2024</div>
  </div>
  <button type="button">More filters</button>
  <button type="reset">Reset</button>
  <button type="submit">Apply</button>
</form>
<table><tbody id="rows"></tbody></table>
<script>
let current = "Last 90 Days", pending = null;
const picker = document.getElementById("picker");
const list = document.getElementById("list");
picker.addEventListener("click", () => {
  list.style.display = list.style.display === "none" ? "block" : "none";
});
for (const o of list.querySelectorAll("[role=option]")) {
  o.addEventListener("click", () => { pending = o.textContent.trim(); list.style.display = "none"; });
}
function search(tf) {
  return fetch("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems", {
    method: "POST", headers: {"Content-Type": "text/plain"},
    body: JSON.stringify({TimeFrame: tf, pageNum: 1})
  }).then(r => r.json()).then(b => {
    const rows = document.getElementById("rows");
    rows.innerHTML = "";
    for (const d of b.defaultDocumentList) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + d.documentDate + "</td><td><a href='#'>" + d.documentTitle + "</a></td>";
      rows.appendChild(tr);
    }
  });
}
document.getElementById("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  if (pending) { current = pending; pending = null; }
  picker.setAttribute("aria-label", "Timeframe ,  " + current);
  picker.textContent = current;
  search(current);
});
search(current);
</script></body></html>"""


def _answer(route):
    req = route.request
    if req.method != "POST":
        return route.fulfill(status=204, headers={"access-control-allow-origin": "*"})
    tf = json.loads(req.post_data or "{}").get("TimeFrame", "")
    body = {"defaultDocumentList": [
        {"documentGuid": "g-%s" % d, "documentId": "i-%s" % d, "documentTypeName": "Statements",
         "documentTitle": "Single Account Statement", "documentDate": d + "T00:00:00",
         "displayMultipleAccounts": "Individual Brokerage"} for d in DATES.get(tf, [])],
        "numFound": str(len(DATES.get(tf, [])))}
    route.fulfill(status=200, content_type="application/json",
                  headers={"access-control-allow-origin": "*"}, body=json.dumps(body))


@pytest.fixture(scope="module")
def discovered():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("https://us.etrade.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=PAGE))
    ctx.route("https://ext-web.etrade.com/**", _answer)
    pg = ctx.new_page()
    # One discovery serves both tests, since each period takes seconds.
    docs = site.collect_download_docs(pg)
    yield docs, list(getattr(site, "DISCOVERY_TRACE", []))
    browser.close()
    driver.stop()


def test_discovery_reads_every_period_the_picker_offers(discovered):
    """His 0.34.0 run found one statement, the one the default ninety
    days held, while the years beside it held more (#36)."""
    docs = discovered[0]
    want = sorted({d for dates in DATES.values() for d in dates}, reverse=True)
    assert sorted({d.date_text for d in docs}, reverse=True) == want


def test_the_trace_says_what_the_picker_offered_and_what_each_period_brought(discovered):
    """So the next report explains itself even with only the file (#36)."""
    trace = discovered[1]
    picker = next(t for t in trace if t.get("note") == "period picker")
    assert picker["found"] is True and picker["showing"] == "Last 90 Days"
    assert picker["plan"] == ["Year To Date", "2026", "2025", "2024"]
    chosen = [t for t in trace if t.get("note") == "period chosen"]
    assert [t["period"] for t in chosen] == picker["plan"]
    for t in chosen:
        assert t["option_clicked"] and t["apply_clicked"] and t["navigated"] is False
        assert t["lists"] >= 1 and t["picker_shows"] == t["period"]
        assert t["dates"] == sorted(DATES[t["period"]], reverse=True)
        assert t["rows_after"] == len(DATES[t["period"]])
    result = trace[-1]
    assert result["note"] == "discovery result" and result["documents"] == 6
    # Period words, counts, booleans and dates, and nothing from the page.
    text = json.dumps(trace)
    assert "Individual" not in text and "Single Account" not in text
