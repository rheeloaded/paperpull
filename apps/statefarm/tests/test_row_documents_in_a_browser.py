"""A Document Center row that must be opened before its document exists.

His 0.34.0 Pilot pressed "View Documents1", watched "Payment Receipt -
Payment Receipt" appear, and stopped, because nothing pressed the
document itself. The recording he sent earlier showed that document
opening in a new tab (#37).

The rows here fold like an accordion, one open at a time, which is the
shape his trace fits. Opening every row first and then pressing the
wanted one again folds it away, which is why the last row is tried too.
The document opens in a new tab as a blob the page made, so nothing here
can reach the network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site

CENTER = "https://edocuments.statefarm.com/DocumentCenterUI/"

PAGE = """<!doctype html><html><body>
<h1>Document Center</h1>
%s
<script>
function openDoc(name) {
  const bytes = new TextEncoder().encode('%%PDF-1.4 ' + name);
  window.open(URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'})), '_blank');
}
function toggle(i) {
  document.querySelectorAll('[role=row]').forEach((row, j) => {
    const btn = row.querySelector('button.view');
    const open = j === i && btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    row.querySelector('.docs').hidden = !open;
  });
}
</script>
</body></html>"""

ROWS = [
    ("07/22/2026", "Renewal Notice - 2019 SEDAN"),
    ("09/12/2026", "Payment Receipt - Payment Receipt"),
    ("04/16/2026", "Declarations Page - Homeowners"),
]


BY_DATE = {"2026-07-22": ROWS[0][1], "2026-09-12": ROWS[1][1], "2026-04-16": ROWS[2][1]}


def _rows():
    out = []
    for i, (when, doc) in enumerate(ROWS):
        out.append(
            "<div role='row'><span>%s</span> <span>Sent by mail. Available online until %s</span>"
            "<button class='view' aria-expanded='false' onclick='toggle(%d)'>View Documents%d</button>"
            "<div class='docs' hidden><a href='#' onclick=\"openDoc('%s');return false\">%s</a></div>"
            "</div>" % (when, when[:6] + "2028", i, i, doc, doc))
    return PAGE % "".join(out)


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    # Everything is answered here or refused, so no request leaves this machine.
    ctx.route("**/*", lambda r: r.abort())
    ctx.route("https://edocuments.statefarm.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=_rows()))
    pg = ctx.new_page()
    pg.goto(CENTER)
    yield pg
    browser.close()
    driver.stop()


@pytest.mark.parametrize("when,title", [
    ("2026-09-12", "Payment Receipt - Billing/Payments"),
    ("2026-04-16", "Declarations Page - Homeowners"),
])
def test_the_row_is_opened_once_and_its_document_is_saved(page, tmp_path, when, title):
    """His Pilot ended at the revealed document. The last row is the one
    that opening every row first would have left open and then folded."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(page, None, when, out, title=title, trace=trace), trace
    assert out.read_bytes().startswith(b"%PDF-")
    clicked = [t["control"] for t in trace if t.get("note") == "clicked"]
    assert clicked[0].startswith("View Documents") and len(clicked) == 2, clicked
    assert clicked[1] == BY_DATE[when]


def test_a_revealed_document_of_another_type_is_not_pressed(page, tmp_path):
    """The wrong document would be saved under this one's name and date."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, "2026-09-12", out,
                                  title="Renewal Notice - Auto", trace=trace)
    assert not out.exists()
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents1"]
    said = [t for t in trace if t.get("note") == "no revealed document was pressed"]
    assert said and "0 revealed" in said[0]["why"], trace


def test_the_date_in_the_row_is_the_issue_date_not_the_availability_date(page):
    """Each row also says "Available online until" a date in 2028."""
    assert sorted(site._control_dates(page)) == ["2026-04-16", "2026-07-22", "2026-09-12"]
