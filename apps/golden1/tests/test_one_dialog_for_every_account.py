"""One history dialog for every account, its list drawn a moment after it opens (#35).

RECORDED, from the member's 0.39.1 Pilot of 2026-09-28. Discover listed 24
statements, all of them month ends, twelve for the checking account and the
same twelve dates again for the second account, the card, whose own list runs
on the 20th of each month. The Pilot then looked for 2026-07-31 in the card's
list and found nothing. Each account's history also read one page, where the
member counts seven years behind NEXT.

The dialog here works the way his page appears to. Statement History asks the
vendor for the account's list and the list arrives a moment later, drawn into
the same dialog the account before used. Until then the dialog holds the old
list, hidden or showing depending on the case. The card's heading names no
card, as his did, and carries a balance, which a key must not keep. Every
date, name and number is invented.
"""
import json
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


MEMBER = _month_ends(26)          # 08/31/26 back to 07/31/24, three pages
CARD = _twentieths(15)            # 09/20/26 back to 07/20/25, two pages

VENDOR = """<!doctype html><html><body>
<h1>eStatements</h1>
<form>
 <div id="panels">
  <div class="panel">
   <h2 aria-expanded="true" class="head">Member Share Draft XXXXXX1111 Balance $1,234.56</h2>
   <div class="body" id="p0"><ul><li><h3>Checking and Savings</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="0">Statement History</a></div></li></ul></li></ul></div>
  </div>
  <div class="panel">
   <h2 aria-expanded="false" class="head">PLATINUM REWARDS XXXXXXXXXXXX4321 Balance $98.76</h2>
   <div class="body" id="p1" style="display:none"><ul><li><h3>Platinum Rewards</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="1">Statement History</a></div></li></ul></li></ul></div>
  </div>
 </div>
 <div id="dlg" style="display:none">
  <div role="dialog" aria-labelledby="dt" tabindex="-1">
   <div role="document"><div><div><span id="dt">Statement History</span></div>
    <div><span id="list"></span>
     <div><button type="button" id="next"><span>NEXT</span></button>
          <button type="button" id="close"><span>Close</span></button></div></div>
   </div></div>
  </div>
 </div>
</form>
<script>
const LISTS = {0: MEMBER_JSON, 1: CARD_JSON};
const SHOW_AT_ONCE = SHOW_JSON;
const SAME_AGAIN = SAME_JSON;
const DRAW_MS = 500, NEXT_MS = 400;
let panel = 0, pageNo = 0, asked = 0;
window.__pressed = [];
for (const h of document.querySelectorAll('h2.head')) {
  h.addEventListener('click', () => {
    for (const other of document.querySelectorAll('h2.head')) {
      const open = other === h;
      other.setAttribute('aria-expanded', open ? 'true' : 'false');
      other.nextElementSibling.style.display = open ? '' : 'none';
    }
  });
}
function draw() {
  const dates = LISTS[panel].slice(pageNo * 12, pageNo * 12 + 12);
  const years = {};
  for (const d of dates) (years['20' + d.slice(-2)] = years['20' + d.slice(-2)] || []).push(d);
  let html = '<ul>';
  for (const y of Object.keys(years).sort().reverse()) {
    html += '<li><span class="yr">' + y + '</span><ul>' +
      years[y].map(d => '<li><a href="#" class="stmt">' + d + '</a></li>').join('') + '</ul></li>';
  }
  document.getElementById('list').innerHTML = html + '</ul>';
  document.getElementById('next').disabled = (pageNo + 1) * 12 >= LISTS[panel].length;
  for (const a of document.querySelectorAll('a.stmt')) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      window.__pressed.push(a.textContent);
      const pdf = '%PDF-1.4\\n% invented ' + (panel ? 'card' : 'member') + ' statement ' +
                  a.textContent + '\\n' + 'x'.repeat(300) + '\\n%%EOF\\n';
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
    const mine = ++asked;
    // The dialog the account before used, with its list still in it.
    if (SHOW_AT_ONCE) document.getElementById('dlg').style.display = '';
    setTimeout(() => {
      if (mine !== asked) return;
      panel = Number(a.dataset.panel); pageNo = 0;
      draw();
      document.getElementById('dlg').style.display = '';
    }, DRAW_MS);
  });
}
document.getElementById('next').addEventListener('click', () => {
  setTimeout(() => { if (!SAME_AGAIN) pageNo += 1; draw(); }, NEXT_MS);
});
document.getElementById('close').addEventListener('click', () => {
  document.getElementById('dlg').style.display = 'none';
});
</script></body></html>"""


def _vendor_html(show_at_once=False, same_again=False):
    return (VENDOR.replace("MEMBER_JSON", json.dumps(MEMBER)).replace("CARD_JSON", json.dumps(CARD))
            .replace("SHOW_JSON", json.dumps(show_at_once)).replace("SAME_JSON", json.dumps(same_again)))


def _drive(monkeypatch, **kw):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_content(_vendor_html(**kw))
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "open_vendor", lambda page: pg)
    return driver, browser, pg


@pytest.fixture(params=[False, True], ids=["old list hidden", "old list showing"])
def vendor(request, monkeypatch):
    driver, browser, pg = _drive(monkeypatch, show_at_once=request.param)
    yield pg
    browser.close()
    driver.stop()


def _dates(docs, account):
    return [d.date_text for d in docs if d.account == account]


def test_each_account_is_read_from_its_own_list(vendor):
    """His Discover. The second account's history was read before its own
    list arrived, and got the first account's dates. It is read from the list
    drawn for it now, every page of it, and Discover says how, in words and
    counts that carry nothing from the headings."""
    trace: list = []
    docs = site.collect_download_docs(vendor, trace=trace)
    member = _dates(docs, "")
    card = [d.date_text for d in docs if d.account]
    assert len(card) == 15 and all(d.endswith("-20") for d in card), (card, trace)
    assert card[0] == "2026-09-20" and card[-1] == "2025-07-20", card
    assert len(member) == 26 and member[0] == "2026-08-31" and member[-1] == "2024-07-31", member
    assert {d.account for d in docs if d.account} == {"account ending 4321"}
    read = [t for t in trace if t.get("note") == "a panel's statement history was read"]
    assert [(t["pages"], t["dated"], t["list"], t["paging_stopped"]) for t in read] == [
        (3, 26, site.DRAWN, "NEXT is disabled"), (2, 15, site.DRAWN, "NEXT is disabled")], read

    lines = site.discovery_lines(trace)
    assert lines[0] == "The statements page shows 2 account(s), 0 taken for a card."
    assert lines[1] == ("Account 1 heading carries the words member, share, and a masked number. "
                        "The headings under it carry checking, savings.")
    assert lines[2] == ("Account 2 heading carries the words platinum, rewards, and a masked "
                        "number. The headings under it carry platinum, rewards.")
    assert lines[3] == ("Account 1 history, 26 statements on 3 page(s). Its list was drawn after "
                        "the press. Paging stopped because NEXT is disabled.")
    assert lines[4].startswith("Account 2 history, 15 statements on 2 page(s).")
    said = json.dumps(trace) + " ".join(lines)
    for private in ("4321", "1111", "1,234.56", "98.76", "PLATINUM", "Share Draft"):
        assert private not in said, private


def test_a_card_statement_is_saved_after_discovery_read_both(vendor, tmp_path):
    """His Pilot, after that Discover. The dialog last showed the card's
    oldest page, and the statement asked for is on the card's second page."""
    docs = site.collect_download_docs(vendor, trace=[])
    [doc] = [d for d in docs if d.date_text == "2025-08-20"]
    out = tmp_path / "card.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out, title=doc.title,
                              trace=trace, account=doc.account), trace
    assert b"invented card statement 08/20/25" in out.read_bytes()
    assert vendor.evaluate("window.__pressed") == ["08/20/25"]
    [searched] = [t for t in trace if t.get("note") == "the panel's statement history was searched"]
    assert searched["panel"] == 1 and searched["pages"] == 2 and searched["found"], searched


def test_a_member_statement_after_a_card_one_comes_from_the_members_list(monkeypatch, tmp_path):
    """The dialog last held the card's list, showing it again as it opens,
    and the member's own list is the one searched."""
    driver, browser, pg = _drive(monkeypatch, show_at_once=True)
    try:
        docs = site.collect_download_docs(pg, trace=[])
        card = [d for d in docs if d.date_text == "2026-09-20"][0]
        assert site.download_bill(pg, tmp_path / "dl", "2026-09-20", tmp_path / "a.pdf",
                                  title=card.title, trace=[], account=card.account)
        out = tmp_path / "b.pdf"
        trace: list = []
        assert site.download_bill(pg, tmp_path / "dl", "2024-08-31", out,
                                  title="Account Statement - August 31, 2024", trace=trace,
                                  account=""), trace
        assert b"invented member statement 08/31/24" in out.read_bytes()
        assert pg.evaluate("window.__pressed") == ["09/20/26", "08/31/24"]
    finally:
        browser.close()
        driver.stop()


def test_a_next_that_draws_the_same_page_again_ends_the_paging(monkeypatch, tmp_path):
    """A NEXT that brings the page it was pressed on is the last page, said
    in the trace, and not a loop to the page limit."""
    monkeypatch.setattr(site, "HISTORY_WAIT_MS", 2400)
    driver, browser, pg = _drive(monkeypatch, same_again=True)
    try:
        trace: list = []
        docs = site.collect_download_docs(pg, trace=trace)
        read = [t for t in trace if t.get("note") == "a panel's statement history was read"]
        assert [(t["pages"], t["paging_stopped"]) for t in read] == [
            (1, "NEXT drew the same page again"), (1, "NEXT drew the same page again")], read
        assert len(docs) == 24
    finally:
        browser.close()
        driver.stop()


def _panel(i, heading, card=False):
    return {"i": i, "heading": heading, "card": card}


def test_a_second_account_is_keyed_by_its_masked_number_and_not_its_balance():
    """0.39.1 keyed a second account by its whole heading. A balance in it
    would have listed every statement again as new each time it changed."""
    first = _panel(0, "Member Share Draft XXXXXX1111 Balance $1,234.56")
    for balance in ("$98.76", "$0.00", "$12,345.67 as of 09/27/2026"):
        second = _panel(1, "PLATINUM REWARDS XXXXXXXXXXXX4321 Balance " + balance)
        assert site._panel_account([first, second], first) == ""
        assert site._panel_account([first, second], second) == "account ending 4321"
    for masked in ("Visa ****4321", "Card ending in 4321", "Rewards ...4321", "Rewards x4321"):
        assert site._panel_account([first, _panel(1, masked)], _panel(1, masked)) == \
            "account ending 4321", masked
    # With no masked number, the heading's words, which a balance, a date or
    # a month name does not change.
    for tail in ("$4,321.00 on 09/20/2026", "$0.00 on Oct 20, 2026"):
        plain = _panel(2, "Savings Balance " + tail)
        assert site._panel_account([first, _panel(1, "Other"), plain], plain) == \
            "account savings balance on", tail
    # A card keeps the empty key of the first panel of its kind.
    card = _panel(1, "VISA SIGNATURE CARD ****4321", card=True)
    assert site._panel_account([first, card], card) == ""


def test_two_later_accounts_never_share_a_key():
    """A key two panels shared would give them one record for each date, and
    the second account's statements on those dates would never be saved. A
    credit union can mask one member number the same on every share, with a
    suffix after it."""
    first = _panel(0, "Member XXXXXX1111-00 Balance $1.00")
    shares = [_panel(1, "Share XXXXXX1111-20 Balance $5.00"), _panel(2, "Share XXXXXX1111-70 Balance $6.00")]
    panels = [first] + shares
    assert [site._panel_account(panels, p) for p in shares] == [
        "account ending 1111-20", "account ending 1111-70"]
    twins = [_panel(1, "Visa ****4321"), _panel(2, "Visa ****4321")]
    assert [site._panel_account([first] + twins, p) for p in twins] == ["account 2", "account 3"]


def test_a_key_stays_with_its_account_when_another_closes():
    """A place would pass to the next account when one before it closed, and
    that account's statements on the closed one's dates would read as
    already saved."""
    first = _panel(0, "Checking $1.00")
    savings, market = _panel(1, "Savings $5.00"), _panel(2, "Money Market $9.00")
    before = {p["heading"]: site._panel_account([first, savings, market], p) for p in (savings, market)}
    market_later = _panel(1, "Money Market $12.00")
    assert site._panel_account([first, market_later], market_later) == before["Money Market $9.00"] \
        == "account money market"
    assert before["Savings $5.00"] == "account savings"


def test_a_next_drawn_as_a_disabled_link_ends_the_paging_at_once(monkeypatch):
    """A WebForms link button that is off is drawn as a link with the class
    aspNetDisabled, which a browser calls enabled. Pressed, it brings no
    page, and the wait for one would cost each account the whole wait."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        pg = browser.new_page()
        pg.set_content("<div role='dialog'><ul><li><a href='#'>09/20/26</a></li></ul>"
                       "<a class='aspNetDisabled'>NEXT</a><button>Close</button></div>")
        facts: dict = {}
        assert not site.next_history_page(pg, facts)
        assert facts["stopped"] == "NEXT is disabled" and "waited_s" not in facts, facts
    finally:
        browser.close()
        driver.stop()


def test_the_heading_words_a_trace_carries_come_from_the_list():
    facts = site._panel_facts({"heading": "Jane Invented's PLATINUM Visa ****4321 $55.10",
                               "sub": ["Credit Card Statements"]})
    assert facts == {"words": ["platinum", "visa"], "words_under_it": ["card", "credit", "statements"],
                     "masked_number": True}
    assert site._panel_facts({"heading": "", "sub": []}) == {
        "words": [], "words_under_it": [], "masked_number": False}
