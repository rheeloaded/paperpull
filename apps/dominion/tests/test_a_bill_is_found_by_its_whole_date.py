"""A bill is opened by its whole date, never by a date that holds it.

Discovery lists each bill by the first date in its panel header, read
whole. The download then looked for the panel by spelling that date again
as M/D/YYYY and taking the first header that merely CONTAINED the
spelling. "1/5/2025" is inside "11/5/2025", and bills are listed newest
first, so a January bill opened the November panel above it and saved
November's PDF under January's date. Dominion's PDF is checked by size
alone and a saved bill is never fetched again, so January's own bill was
lost for good. A header that writes 01/15/2025 has the same trouble with
11/15/2025, and one that writes 01/05/2025 was never found at all, since
1/5/2025 is not inside it.

The page below is made up in the shape of the billing history. Panels
newest first, a header holding the statement date, and a Download Your
Detailed Bill PDF button inside each panel, shown only while that panel is
open. The page writes down which panel was opened and which bill was
downloaded, and every date and amount is invented. It is served to the
browser by a route, so reloading it works the way the app needs and
nothing can reach a real site.
"""
import base64
import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import dominion_docs as app_mod
import dominion_site as site
from paperpull_core import receipt_pdf
from paperpull_core.journal import Journal
from paperpull_core.models import State
from paperpull_core.testkit import text_pdf

# Not Dominion's host. The route below answers it, and the app reads only
# the hash route from the address.
ADDRESS = "http://bills.test/portal/#/Billinghistory"

PAGE = r"""<!doctype html><html><head><style>
.MuiCollapse-container{display:none}
.MuiExpansionPanel-root.open .MuiCollapse-container{display:block}
</style></head><body>
<main><h1>Billing History</h1><div id="bills"></div>
<nav><button id="prev" aria-label="previous page">&lt;</button>
<button id="next" aria-label="next page">&gt;</button></nav></main>
<script>
const PAGES = __PAGES__;
const PDFS = __PDFS__;
let at = 0;
function note(what) {
  const seen = JSON.parse(sessionStorage.getItem('seen') || '[]');
  seen.push(what);
  sessionStorage.setItem('seen', JSON.stringify(seen));
}
function draw() {
  const list = document.getElementById('bills');
  list.innerHTML = PAGES[at].map(([bill, head]) =>
    '<div class="MuiPaper-root MuiExpansionPanel-root" data-bill="' + bill + '">' +
    '<div class="MuiButtonBase-root MuiExpansionPanelSummary-root" role="button"' +
    ' tabindex="0" aria-expanded="false">' +
    '<div class="MuiExpansionPanelSummary-content">' + head + '</div></div>' +
    '<div class="MuiCollapse-container"><div class="MuiExpansionPanelDetails-root">' +
    '<button type="button" class="MuiButton-root">Download Your Detailed Bill PDF</button>' +
    '</div></div></div>').join('');
  for (const panel of list.querySelectorAll('.MuiExpansionPanel-root')) {
    const bill = panel.dataset.bill;
    const head = panel.querySelector('.MuiExpansionPanelSummary-root');
    head.addEventListener('click', () => {
      const open = panel.classList.contains('open');
      for (const other of list.querySelectorAll('.MuiExpansionPanel-root')) {
        other.classList.remove('open');
        other.firstChild.setAttribute('aria-expanded', 'false');
      }
      if (!open) {
        panel.classList.add('open');
        head.setAttribute('aria-expanded', 'true');
        note('opened ' + bill);
      }
    });
    panel.querySelector('button').addEventListener('click', () => {
      note('downloaded ' + bill);
      const bytes = Uint8Array.from(atob(PDFS[bill]), c => c.charCodeAt(0));
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
      a.download = 'bill.pdf';
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }
  document.getElementById('prev').disabled = at === 0;
  document.getElementById('next').disabled = at === PAGES.length - 1;
}
document.getElementById('prev').addEventListener('click', () => { at -= 1; draw(); });
document.getElementById('next').addEventListener('click', () => { at += 1; draw(); });
draw();
</script></body></html>"""


def _page_of(pages):
    """The billing history, one list of (bill, header) per page of it."""
    bills = [bill for rows in pages for bill, _ in rows]
    pdfs = {bill: base64.b64encode(text_pdf(["Invented bill [%s]" % bill])).decode()
            for bill in bills}
    return (PAGE.replace("__PAGES__", json.dumps(pages))
                .replace("__PDFS__", json.dumps(pdfs)))


@pytest.fixture()
def history():
    """Open a made-up billing history in a real browser, newest bill first."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    served = {}

    def answer(route):
        if route.request.url.startswith("http://bills.test/portal/"):
            route.fulfill(status=200, content_type="text/html", body=served["html"])
        else:
            route.abort()
    ctx.route("**/*", answer)
    pg = ctx.new_page()

    def show(*pages):
        served["html"] = _page_of([list(rows) for rows in pages])
        pg.goto(ADDRESS)
        pg.evaluate("sessionStorage.clear()")
        return pg
    yield show
    browser.close()
    driver.stop()


def _seen(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('seen') || '[]')")


def _saved_bill(path):
    return receipt_pdf.pdf_text(Path(path))


NOVEMBER_ABOVE_JANUARY = [("November", "<p>11/5/2025</p><p>$141.07</p>"),
                          ("January", "<p>1/5/2025</p><p>$188.32</p>")]


def test_a_january_bill_opens_the_january_panel_and_no_other(history, tmp_path):
    page = history(NOVEMBER_ABOVE_JANUARY)
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2025-01-05", out)
    assert _seen(page) == ["opened January", "downloaded January"]
    assert "[January]" in _saved_bill(out)


def test_the_newer_bill_is_still_its_own(history, tmp_path):
    page = history(NOVEMBER_ABOVE_JANUARY)
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2025-11-05", out)
    assert _seen(page) == ["opened November", "downloaded November"]
    assert "[November]" in _saved_bill(out)


def test_a_header_that_pads_its_month_with_a_zero(history, tmp_path):
    """1/15/2025 is inside 01/15/2025 and inside 11/15/2025 alike."""
    page = history([("November", "<p>11/15/2025</p><p>$141.07</p>"),
                    ("January", "<p>01/15/2025</p><p>$188.32</p>")])
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2025-01-15", out)
    assert _seen(page) == ["opened January", "downloaded January"]
    assert "[January]" in _saved_bill(out)


def test_a_header_that_pads_its_day_with_a_zero(history, tmp_path):
    """Discovery reads 01/05/2025 as 2025-01-05, and the download has to
    find it by the same reading, where 1/5/2025 is inside no header."""
    page = history([("November", "<p>11/05/2025</p><p>$141.07</p>"),
                    ("January", "<p>01/05/2025</p><p>$188.32</p>")])
    assert site._panel_dates(page) == ["2025-11-05", "2025-01-05"]
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2025-01-05", out)
    assert _seen(page) == ["opened January", "downloaded January"]
    assert "[January]" in _saved_bill(out)


def test_only_the_first_date_in_a_header_is_its_bill(history, tmp_path):
    """Discovery dates a bill by the first date in its header, so a later
    date in a newer bill's header is not the older bill's own."""
    page = history([("February", "<p>2/4/2026</p><p>Read 1/5/2026 to 2/3/2026</p>"),
                    ("January", "<p>1/5/2026</p><p>Read 12/4/2025 to 1/4/2026</p>")])
    assert site._panel_dates(page) == ["2026-02-04", "2026-01-05"]
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2026-01-05", out)
    assert _seen(page) == ["opened January", "downloaded January"]
    assert "[January]" in _saved_bill(out)


def test_a_bill_on_a_later_page_is_paged_to(history, tmp_path):
    """The newer bill that holds its date is on the first page and its own
    panel on the second."""
    page = history([("November", "<p>11/5/2025</p><p>$141.07</p>")],
                   [("January", "<p>1/5/2025</p><p>$188.32</p>")])
    out = tmp_path / "bill.pdf"
    assert site.download_statement(page, "2025-01-05", out)
    assert _seen(page) == ["opened January", "downloaded January"]
    assert "[January]" in _saved_bill(out)


def test_a_bill_with_no_panel_of_its_own_presses_nothing(history, tmp_path):
    for date in ("2025-01-05", "2025-01-15", "2025-02-01"):
        page = history([("November", "<p>11/5/2025</p><p>$141.07</p>"),
                        ("November15", "<p>11/15/2025</p><p>$139.80</p>"),
                        ("December", "<p>12/1/2025</p><p>$152.66</p>")])
        out = tmp_path / ("%s.pdf" % date)
        assert not site.download_statement(page, date, out), date
        assert not out.exists(), date
        assert _seen(page) == [], (date, _seen(page))


# -- the whole run ---------------------------------------------------------


class _Records:
    """progress, discovery and the index, written down rather than saved."""

    def __init__(self):
        self.data = {}

    def update(self, key, value, **kw):
        self.data.setdefault(key, {}).update(value)

    def get(self, key):
        return self.data.get(key)

    def append_rows(self, rows):
        pass

    def save(self, **kw):
        pass


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, *a):
        return self.root


def _app(tmp_path):
    app = object.__new__(app_mod.App)
    app.args = type("Args", (), {"redownload": False})()
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress, app.discovery, app.index_csv = _Records(), _Records(), _Records()
    app._journal = Journal()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app.write_failure = lambda *a, **kw: None
    return app


def _bill(date):
    return app_mod.Document(title="Statement - %s" % date, category="Statement",
                            summary="Account Statement", date=date)


def test_a_run_files_january_under_january(history, tmp_path):
    page = history(NOVEMBER_ABOVE_JANUARY)
    app = _app(tmp_path)
    app.page = lambda: page
    doc = _bill("2025-01-05")
    app.process([doc])
    rec = app.progress.get(doc.key)
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"]
    assert "[January]" in _saved_bill(rec["pdf_path"])
    assert _seen(page) == ["opened January", "downloaded January"]


def test_a_run_never_remembers_another_bill_as_one_it_could_not_find(history, tmp_path):
    """Saving November's bill as January's would have marked January done
    for good. With no panel of its own it is left to look for again."""
    page = history([("November", "<p>11/15/2025</p><p>$139.80</p>")])
    app = _app(tmp_path)
    app.page = lambda: page
    doc = _bill("2025-01-15")
    app.process([doc])
    rec = app.progress.get(doc.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert not rec.get("downloaded_ok")
    assert not list(tmp_path.glob("*.pdf"))
    assert _seen(page) == []
