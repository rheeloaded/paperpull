"""Every account's statements, every page of them (#35, round six).

RECORDED, from the member's recording of 2026-09-27. The vendor's page
holds one panel per account, headed by an element that carries
aria-expanded, and each panel has its own Statement History link. The
member's card was the second panel, and its heading was pressed open
before its Statement History. Statement History opens a dialog listing
twelve statements a page, each a link whose whole label is its date,
under year headings, with NEXT under the list and Close beside it.
Pressing a date downloads the statement.

The app read the first panel's first page only, so older statements were
never listed and the card was never seen. Here the vendor is made up in
that shape, twenty-six member statements and fifteen card statements, so
both walks have more than one page. Every date and name is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_site as site


def _month_ends(n, first_year=2026, first_month=8):
    import calendar
    out, y, m = [], first_year, first_month
    for _ in range(n):
        out.append("%02d/%02d/%02d" % (m, calendar.monthrange(y, m)[1], y % 100))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _twentieths(n, first_year=2026, first_month=9):
    out, y, m = [], first_year, first_month
    for _ in range(n):
        out.append("%02d/20/%02d" % (m, y % 100))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


MEMBER = _month_ends(26)          # 08/31/26 back to 07/31/24
CARD = _twentieths(15)            # 09/20/26 back to 07/20/25

VENDOR = """<!doctype html><html><body>
<h1>eStatements</h1>
<form>
 <div id="panels">
  <div class="panel">
   <h2 aria-expanded="true" class="head" data-a="1" data-b="2">Member Statements</h2>
   <div class="body" id="p0"><ul><li><h3 id="h0">Checking and Savings</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="0" target="_blank">Statement History</a></div></li>
         <li><a href="#">Pay my loan</a></li></ul></li></ul></div>
  </div>
  <div class="panel">
   <h2 aria-expanded="false" class="head" data-a="1" data-b="2">VISA SIGNATURE CARD ****4321</h2>
   <div class="body" id="p1" style="display:none"><ul><li><h3 id="h1">Visa Signature</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="1" target="_blank">Statement History</a></div></li>
         <li><a href="#">Make a payment</a></li></ul></li></ul></div>
  </div>
 </div>
 <div id="dlg" style="display:none">
  <div role="dialog" aria-labelledby="dt" tabindex="-1">
   <div role="document"><div><div><span id="dt">Statement History</span></div>
    <div><span id="list"></span>
     <div><button type="button" id="next" name="next"><span>NEXT</span></button>
          <button type="button" id="close" name="close"><span>Close</span></button></div></div>
   </div></div>
  </div>
 </div>
</form>
<script>
const LISTS = {0: %(member)s, 1: %(card)s};
let panel = 0, pageNo = 0;
window.__pressed = [];
for (const h of document.querySelectorAll('h2.head')) {
  h.addEventListener('click', () => {
    const open = h.getAttribute('aria-expanded') !== 'true';
    h.setAttribute('aria-expanded', open ? 'true' : 'false');
    h.nextElementSibling.style.display = open ? '' : 'none';
  });
}
function draw() {
  const dates = LISTS[panel].slice(pageNo * 12, pageNo * 12 + 12);
  const years = {};
  for (const d of dates) (years['20' + d.slice(-2)] = years['20' + d.slice(-2)] || []).push(d);
  let html = '<ul>';
  for (const y of Object.keys(years).sort().reverse()) {
    html += '<li><span class="yr">' + y + '</span><ul>' +
      years[y].map(d => '<li><a href="#" class="stmt" target="_blank">' + d + '</a></li>').join('') +
      '</ul></li>';
  }
  document.getElementById('list').innerHTML = html + '</ul>';
  const last = (pageNo + 1) * 12 >= LISTS[panel].length;
  document.getElementById('next').disabled = last;
  for (const a of document.querySelectorAll('a.stmt')) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      window.__pressed.push(a.textContent);
      const pdf = '%%PDF-1.4\\n%% invented ' + (panel ? 'card' : 'member') + ' statement ' +
                  a.textContent + '\\n' + 'x'.repeat(300) + '\\n%%%%EOF\\n';
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([pdf], {type: 'application/pdf'}));
      link.download = 'dxweb.pdf';
      document.body.appendChild(link);
      link.click();
    });
  }
}
for (const a of document.querySelectorAll('a.hist')) {
  a.addEventListener('click', (e) => {
    e.preventDefault();
    panel = Number(a.dataset.panel); pageNo = 0;
    draw();
    document.getElementById('dlg').style.display = '';
  });
}
document.getElementById('next').addEventListener('click', () => { pageNo += 1; draw(); });
document.getElementById('close').addEventListener('click', () => {
  document.getElementById('dlg').style.display = 'none';
});
</script></body></html>""" % {"member": repr(MEMBER).replace("'", '"'), "card": repr(CARD).replace("'", '"')}


@pytest.fixture()
def vendor(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_content(VENDOR)
    # The bank's side, reaching the vendor, is tested elsewhere. Here the
    # tab this run opened is the vendor itself.
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "open_vendor", lambda page: pg)
    yield pg
    browser.close()
    driver.stop()


def _titles(docs, kind):
    return [d.title for d in docs if d.title.startswith(kind)]


def test_every_page_of_every_account_is_read(vendor):
    trace: list = []
    docs = site.collect_download_docs(vendor, trace=trace)
    member = _titles(docs, "Account Statement - ")
    card = _titles(docs, "Credit Card Statement - ")
    assert len(member) == 26 and len(card) == 15, (len(member), len(card))
    assert member[0] == "Account Statement - August 31, 2026"
    assert member[-1] == "Account Statement - July 31, 2024"
    assert card[0] == "Credit Card Statement - September 20, 2026"
    assert card[-1] == "Credit Card Statement - July 20, 2025"
    assert all(d.account == "" for d in docs), "the first panel of each kind keeps its old keys"
    panels = [t for t in trace if t.get("note") == "a panel's statement history was read"]
    assert [(p["card"], p["pages"], p["dated"]) for p in panels] == [(False, 3, 26), (True, 2, 15)]
    assert "VISA" not in str(trace) and "4321" not in str(trace), "no heading leaves in the trace"


def test_an_old_member_statement_is_found_on_its_own_page(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2024-08-31", out,
                              title="Account Statement - August 31, 2024", trace=trace), trace
    assert b"invented member statement 08/31/24" in out.read_bytes()
    assert vendor.evaluate("window.__pressed") == ["08/31/24"]


def test_a_card_statement_is_found_in_the_cards_own_panel(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out,
                              title="Credit Card Statement - August 20, 2025", trace=trace), trace
    assert b"invented card statement 08/20/25" in out.read_bytes()
    assert vendor.evaluate("window.__pressed") == ["08/20/25"]


def test_a_date_on_no_page_presses_nothing(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert not site.download_bill(vendor, tmp_path / "dl", "2019-01-31", out,
                                  title="Account Statement - January 31, 2019", trace=trace)
    assert vendor.evaluate("window.__pressed") == [] and not out.exists()


def test_next_and_close_are_pressed_and_nothing_else_new():
    for label in ("NEXT", "Next", " next "):
        assert site.NEXT_PAGE_RE.match(label), label
    for label in ("Next payment", "Next due date", "Pay next bill"):
        assert not site.NEXT_PAGE_RE.match(label), label
    assert site.CLOSE_RE.match("Close") and not site.CLOSE_RE.match("Close account")


def test_a_panel_heading_is_opened_only_when_it_names_no_money_moving():
    assert site.panel_heading_is_safe("VISA SIGNATURE CARD ****4321")
    assert site.panel_heading_is_safe("Member Statements")
    for danger in ("Make a payment", "Transfer funds", "Pay my card", "Close account",
                   "Cancel card", "Zelle"):
        assert not site.panel_heading_is_safe(danger), danger
