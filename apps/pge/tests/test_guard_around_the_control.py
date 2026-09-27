"""A refused control is never pressed through what is around it or inside
it. From the second review of round eight (#33).

The row hands over the link and the cell it sits in as separate
candidates, innermost first, and each was judged on its own labels. So a
link refused for an aria-label reading Pay this bill left its cell
approved, and the click on the cell landed on the link. A span reading
View Bill PDF inside a button whose aria-label read Pay this bill was
approved, and the click bubbled into the button. The review did both in
a real browser, in the row shape his round three outline showed.

The third review found the rest of what a click reaches. A plain box
around the link that carries a Pay label, which is no control by its tag
and was judged only when its own words were exactly View Bill PDF. The
page wide look, which judged a link alone and approved one its row had
refused. A label, whose click goes to its control wherever that sits. And
words slotted into a Pay button in a shadow root, whose click bubbles up
through the slot and not straight to the host.

A safety review of that repair found the page wide look reaching a row
that was not the bill's. A payment made on the bill's day carries the
bill's date, and the receipt link in its row was saved as the bill.

Every date, amount and address here is invented.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40


def _serve(route):
    """The history, and an answer carrying the bill, only so a press on an
    approved control has something to hand back quickly."""
    if "/sfsites/aura" in route.request.url:
        route.fulfill(status=200, content_type="application/json;charset=UTF-8",
                      body=json.dumps({"actions": [{
                          "id": "7;a", "state": "SUCCESS",
                          "returnValue": base64.b64encode(_PDF).decode()}]}))
    else:
        route.fulfill(status=200, content_type="text/html", body="<h1>history</h1>")


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
    ctx.route("https://myaccount.pge.com/**", _serve)
    pg = ctx.new_page()
    pg.goto(HISTORY)
    yield pg
    browser.close()
    driver.stop()


# His round three outline, tr.rowbox with the control in the fourth cell.
# The cell's contents change from test to test. Whatever carries
# data-refused counts every click that reaches it, and whatever carries
# data-bill asks for the bill when pressed.
TABLE = """<table><tbody><tr class="rowbox">
  <td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td>
  <td></td>
  <td>%s</td>
  <td class="no-padding-right"><div><div class="payoffamount-div">
    <p class="payoffamount-divpara">$12.34</p></div></div></td>
</tr></tbody></table>"""

HOOKS = """<script>
  window.refused = window.refused || 0; window.presses = 0;
  for (const el of document.querySelectorAll('[data-refused]')) {
    el.addEventListener('click', e => { e.preventDefault(); window.refused++; });
  }
  for (const el of document.querySelectorAll('[data-bill]')) {
    el.addEventListener('click', () => {
      window.presses++;
      fetch('/myaccount/s/sfsites/aura?r=9&aura.ApexAction.execute=1',
            {method: 'POST', body: 'message={}'});
    });
  }
</script>"""

ROW = TABLE + HOOKS


def _page_with(cell, outside=""):
    """The row with `cell` in its fourth cell, and `outside` after the
    table, before the clicks are counted."""
    return TABLE % cell + outside + HOOKS


def _download(page, tmp_path):
    from paperpull_core.journal import Journal
    j = Journal(page)
    site.set_journal(j)
    try:
        ok = site.download_bill(page, {"date_text": "2031-04-17", "row_index": 0,
                                       "page_number": 1}, tmp_path / "bill.pdf", {})
    finally:
        site.set_journal(None)
    results = [(e.get("outcome"), e.get("facts", {})) for e in j.report()["entries"]
               if e.get("kind") == "result"]
    return ok, results


REFUSED_IN_THE_ROW = {
    # the review's first shape, the link refused and its cell approved
    "a hidden Pay label on the link": (
        '<div class="align-right"><a class="pdf-link" data-refused '
        'aria-label="Pay this bill">View Bill PDF</a></div>'),
    "a hidden Enroll title on the link": (
        '<div class="align-right"><a class="pdf-link" data-refused '
        'title="Enroll in paperless billing">View Bill PDF</a></div>'),
    # the review's second shape, the words inside a refused control
    "the words inside a Pay button": (
        '<button data-refused aria-label="Pay this bill"><span>View Bill PDF</span></button>'),
    "the words inside an autopay link": (
        '<a data-refused href="#pay" title="Set up autopay"><span>View Bill PDF</span></a>'),
    # a clickable box that is no control by its tag, refused by its label
    "the words inside a Pay box": (
        '<div data-refused aria-label="Pay this bill"><span>View Bill PDF</span></div>'),

    # From the third review of round eight. A plain box around his very
    # link, carrying the label. The box is no control by its tag or role,
    # so it was never judged unless its own text read View Bill PDF, and
    # any other words in it let the link through.
    "a Pay box around the link": (
        '<div data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a></div>'),
    "an Enroll title on a box around the link": (
        '<div data-refused title="Enroll in paperless billing">'
        '<a class="pdf-link">View Bill PDF</a></div>'),
    "a Pay span around the link": (
        '<span data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a></span>'),
    "a Pay box around the link and more words": (
        '<div data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a>'
        '<span> opens in a new window</span></div>'),
    # a label is handed a click and gives it to its control, wherever that is
    "a label for a Pay button": (
        '<label for="paybtn">View Bill PDF</label>',
        '<button id="paybtn" data-refused aria-label="Pay this bill">Pay</button>'),
    "a label around the words for a Pay button": (
        '<label for="paybtn"><span>View Bill PDF</span></label>',
        '<button id="paybtn" data-refused aria-label="Pay this bill">Pay</button>'),
    # the words slotted into a Pay button inside an open shadow root, where
    # a click on them bubbles through the slot and the button
    "the words slotted into a Pay button": (
        '<x-pay><span>View Bill PDF</span></x-pay>',
        """<script>
          class XPay extends HTMLElement { constructor() { super();
            const r = this.attachShadow({mode: 'open'});
            r.innerHTML = '<button aria-label="Pay this bill"><slot></slot></button>';
            r.querySelector('button').addEventListener('click', () => {
              window.refused = (window.refused || 0) + 1; });
          } }
          customElements.define('x-pay', XPay);
        </script>"""),
    # the same in a closed shadow root, which the page cannot see into at
    # all, so what a click does in there cannot be judged and is refused
    "the words slotted into a closed component": (
        '<y-pay><span>View Bill PDF</span></y-pay>',
        """<script>
          class YPay extends HTMLElement { constructor() { super();
            const r = this.attachShadow({mode: 'closed'});
            r.innerHTML = '<button aria-label="Pay this bill"><slot></slot></button>';
            r.querySelector('button').addEventListener('click', () => {
              window.refused = (window.refused || 0) + 1; });
          } }
          customElements.define('y-pay', YPay);
        </script>"""),
    # labels the guard had never read, an aria-labelledby and an alt
    "the link named by a hidden Pay heading": (
        '<span id="payname" hidden>Pay this bill</span>'
        '<div class="align-right"><a class="pdf-link" data-refused '
        'aria-labelledby="payname">View Bill PDF</a></div>'),
    "a Pay picture inside the link": (
        '<div class="align-right"><a class="pdf-link" data-refused>View Bill PDF'
        '<img alt="Pay this bill" src="data:," width="1" height="1"></a></div>'),
}


def _page_for(shape):
    got = REFUSED_IN_THE_ROW[shape]
    return _page_with(*got) if isinstance(got, tuple) else ROW % got


@pytest.mark.parametrize("shape", sorted(REFUSED_IN_THE_ROW))
def test_a_refused_control_is_never_pressed_through_its_neighbor(page, tmp_path, shape):
    page.set_content(_page_for(shape))
    ok, results = _download(page, tmp_path)
    assert page.evaluate("window.refused") == 0, "the refused control took a press"
    assert page.evaluate("location.hash") != "#pay"
    assert ok is False
    assert [o for o, _ in results] == ["found no pdf control"], results
    facts = results[0][1]
    assert facts["row_found"] is True
    assert facts["row_refused"] >= 1
    assert facts["row_nearby"] >= 1, "refused for what was around it"
    # and a row that refused is not looked at again page wide
    assert facts["page_looked"] is False and facts["page_links"] == 0
    assert all(isinstance(v, (bool, int)) for v in facts.values())


def test_a_row_that_refused_is_not_approved_again_page_wide(page, tmp_path):
    """The page wide look judged each link on its own, with nothing else
    from its row beside it. The link inside a Pay button reads safe on its
    own, and pressing it presses the button. Judged alone it is still
    refused for the button around it, and a row that refused anything is
    not looked at page wide any more."""
    page.set_content(ROW % ('<button data-refused aria-label="Pay this bill">'
                            '<a class="pdf-link">View Bill PDF</a></button>'))
    assert site.pick_document_control([page.query_selector("a.pdf-link")]) is None
    ok, results = _download(page, tmp_path)
    assert page.evaluate("window.refused") == 0
    assert ok is False
    facts = results[0][1]
    assert facts["row_refused"] >= 1
    assert facts["page_looked"] is False


# -- the page wide look, for a row the usual look does not find ------------

# Rows the usual look does not find, a plain list rather than a table. The
# page wide look goes from each View Bill PDF control to the row it sits
# in, and that row must be judged as a row found the usual way would be.
LIST = """<ul><li class="bill">
  <span class="slds-col row-box">04/17/2031</span> <span>Bill Charges</span>
  <span class="cell">%s</span> <span class="payoffamount-divpara">$12.34</span>
</li></ul>"""

AROUND_THE_LINK = {
    "a Pay box around the link": (
        '<div data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a></div>'),
    "an Enroll title on a box around the link": (
        '<div data-refused title="Enroll in paperless billing">'
        '<a class="pdf-link">View Bill PDF</a></div>'),
    "a Pay span around the link": (
        '<span data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a></span>'),
    "a Pay box around the link and more words": (
        '<div data-refused aria-label="Pay this bill"><a class="pdf-link">View Bill PDF</a>'
        '<span> opens in a new window</span></div>'),
}


@pytest.fixture()
def no_table(monkeypatch):
    """The usual look waits up to twenty seconds for table rows, and these
    pages have none, so it is told at once."""
    monkeypatch.setattr(site, "wait_for_rows", lambda page, seconds=20: 0)


@pytest.mark.parametrize("shape", sorted(AROUND_THE_LINK))
def test_the_page_wide_look_judges_the_row_it_reaches(page, tmp_path, no_table, shape):
    """The evidence review's probe. The link was handed over alone, the
    box around it carrying Pay was no control, and the press landed on
    the box."""
    page.set_content(LIST % AROUND_THE_LINK[shape] + HOOKS)
    ok, results = _download(page, tmp_path)
    assert page.evaluate("window.refused") == 0, "the refused box took a press"
    assert ok is False
    assert [o for o, _ in results] == ["found no pdf control"], results
    facts = results[0][1]
    assert facts["row_found"] is False and facts["page_looked"] is True
    assert facts["page_refused"] >= 1 and facts["page_nearby"] >= 1


def test_the_page_wide_look_still_presses_a_row_that_passes(page, tmp_path, no_table):
    page.set_content(LIST % '<a class="pdf-link" data-bill>View Bill PDF</a>' + HOOKS)
    ok, _ = _download(page, tmp_path)
    assert ok is True
    assert (tmp_path / "bill.pdf").read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1


def test_a_bill_with_no_date_is_never_looked_for_page_wide(page, tmp_path):
    """With no date to hold a row to, any bill's link would have done, and
    the first one on the page was pressed."""
    page.set_content(ROW % '<a class="pdf-link" data-bill>View Bill PDF</a>')
    ok = site.download_bill(page, {"date_text": "", "row_index": 0, "page_number": 1},
                            tmp_path / "bill.pdf", {})
    assert ok is False
    assert page.evaluate("window.presses") == 0
    assert not (tmp_path / "bill.pdf").exists()


# -- the page wide look reaches the bill's own row and no other ---------------

# A payment made on the day a bill is dated, above the bill. Its row holds a
# link to the payment's receipt, a PDF on PG&E whose words pass the guard on
# their own. The bill's words sit in a plain box with more words after them,
# so the bill's row hands over no control at all. The safety review of round
# eight's repair built this in a real browser, and the page wide look saved
# the receipt as the bill. Every date, amount and address is invented.
RECEIPT = "https://myaccount.pge.com/myaccount/s/receipts/invented-receipt.pdf"
RECEIPT_BYTES = b"%PDF-1.4 an invented payment receipt, not a bill"

# Every click anywhere on the page is counted and goes nowhere.
COUNT_EVERY_CLICK = """<script>
  window.clicks = 0;
  document.addEventListener('click', e => { window.clicks++; e.preventDefault(); }, true);
</script>"""

PAYMENT_TR = """<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Payment Received</div></td><td></td>
  <td><a class="receipt" href="/myaccount/s/receipts/invented-receipt.pdf">View receipt</a></td>
  <td><p class="payoffamount-divpara">$12.34</p></td></tr>"""

BILL_TR_WITH_NO_CONTROL = """<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right">View Bill PDF <span>(opens in a new window)</span></div></td>
  <td><p class="payoffamount-divpara">$56.78</p></td></tr>"""

# The same two, as list items the usual look does not find.
PAYMENT_LI = """<li class="payment">
  <span class="slds-col row-box">04/17/2031</span> <span>Payment Received</span>
  <span class="cell"><a class="receipt" data-refused
    href="/myaccount/s/receipts/invented-receipt.pdf">View receipt</a></span>
  <span class="payoffamount-divpara">$12.34</span></li>"""

BILL_LI_WITH_NO_CONTROL = """<li class="bill">
  <span class="slds-col row-box">04/17/2031</span> <span>Bill Charges</span>
  <span class="cell"><span class="align-right">View Bill PDF
    <span>(opens in a new window)</span></span></span>
  <span class="payoffamount-divpara">$56.78</span></li>"""

BILL_LI = """<li class="bill">
  <span class="slds-col row-box">04/17/2031</span> <span>Bill Charges</span>
  <span class="cell"><a class="pdf-link" data-bill>View Bill PDF</a></span>
  <span class="payoffamount-divpara">$56.78</span></li>"""


def _take(page, tmp_path, row_index):
    """The bill as discovery would hand it over. Discovery counts every row
    and keeps the index of the one that reads View Bill PDF."""
    from paperpull_core.journal import Journal
    j = Journal(page)
    site.set_journal(j)
    try:
        ok = site.download_bill(page, {"date_text": "2031-04-17", "row_index": row_index,
                                       "page_number": 1}, tmp_path / "bill.pdf", {})
    finally:
        site.set_journal(None)
    results = [(e.get("outcome"), e.get("facts", {})) for e in j.report()["entries"]
               if e.get("kind") == "result"]
    return ok, results


def test_a_found_bill_row_is_never_traded_for_another_row_page_wide(page, tmp_path, session):
    """The safety review's probe. The bill's row was found and handed over
    nothing, so the page wide look ran. It went to the first control on the
    page whose own row carried the bill's date, which was the payment's
    receipt link, and saved the receipt as the bill. When the bill's row
    was found, a look across the page can only reach some other row, so it
    does not run."""
    session.answers[RECEIPT] = RECEIPT_BYTES
    page.set_content("<table><tbody>" + PAYMENT_TR + BILL_TR_WITH_NO_CONTROL
                     + "</tbody></table>" + COUNT_EVERY_CLICK)
    ok, results = _take(page, tmp_path, row_index=1)
    assert ok is False, "the payment's receipt was saved as the bill"
    assert not (tmp_path / "bill.pdf").exists()
    assert page.evaluate("window.clicks") == 0, "something was pressed"
    assert session.asked == [], "the receipt was asked for"
    assert [o for o, _ in results] == ["found no pdf control"], results
    facts = results[0][1]
    assert facts["row_found"] is True and facts["row_candidates"] == 0
    assert facts["page_looked"] is False and facts["page_rows"] == 0
    assert facts["page_links"] == 0
    assert all(isinstance(v, (bool, int)) for v in facts.values())


def test_with_no_row_found_a_payment_on_the_bills_date_is_never_the_bill(
        page, tmp_path, no_table, session):
    """The same payment where no row is found the usual way. The page wide
    look held the row it reached to the date alone, and a payment's row
    carries the date as well as a bill's does. A row it takes must read
    View Bill PDF, the same test the usual look and discovery use."""
    session.answers[RECEIPT] = RECEIPT_BYTES
    page.set_content("<ul>" + PAYMENT_LI + BILL_LI_WITH_NO_CONTROL + "</ul>"
                     + HOOKS + COUNT_EVERY_CLICK)
    ok, results = _take(page, tmp_path, row_index=1)
    assert ok is False, "the payment's receipt was saved as the bill"
    assert not (tmp_path / "bill.pdf").exists()
    assert page.evaluate("window.clicks") == 0, "something was pressed"
    assert page.evaluate("window.refused") == 0
    assert session.asked == [], "the receipt was asked for"
    assert [o for o, _ in results] == ["found no pdf control"], results
    facts = results[0][1]
    assert facts["row_found"] is False and facts["page_looked"] is True
    assert facts["page_rows"] == 0 and facts["page_links"] == 0


def test_with_no_row_found_the_bills_own_row_is_taken_over_a_payment_on_its_date(
        page, tmp_path, no_table, session):
    """The payment comes first on the page and first in what the look finds,
    and the bill's own row is the one pressed."""
    session.answers[RECEIPT] = RECEIPT_BYTES
    page.set_content("<ul>" + PAYMENT_LI + BILL_LI + "</ul>" + HOOKS)
    ok, results = _take(page, tmp_path, row_index=1)
    assert ok is True
    assert (tmp_path / "bill.pdf").read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.refused") == 0, "the receipt link took a press"
    assert session.asked == [], "the receipt was asked for"


def test_with_no_row_found_a_row_reached_from_two_of_its_controls_is_one_row(
        page, tmp_path, no_table):
    """The look reaches rows from every control that could be a bill's PDF,
    and a bill row can hold two of them. It is still one row, and its View
    Bill PDF link is the one pressed."""
    page.set_content("<ul>" + BILL_LI.replace(
        "View Bill PDF</a>",
        'View Bill PDF</a> <a class="dl" data-refused download href="#dl">Download</a>')
        + "</ul>" + HOOKS)
    assert len(page.query_selector_all(site.FALLBACK["download_control"])) == 2
    rows, crowded = site._bill_rows_page_wide(page, "2031-04-17")
    assert len(rows) == 1 and crowded == 0
    ok, results = _take(page, tmp_path, row_index=0)
    assert ok is True
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.refused") == 0, "the other control took the press"
    assert "refused more than one bill row with the date" not in [o for o, _ in results]


def test_with_no_row_found_a_row_holding_more_than_one_bill_is_refused(page, tmp_path, no_table):
    """The row a control sits in is the nearest list item or table row
    above it. When the bills are plain boxes inside one list item, that
    item is the row every control reaches, it reads View Bill PDF, and its
    first date can be this bill's while the only link in it is another
    bill's. Pressing inside it saved the March bill as April's."""
    page.set_content("""<ul><li class="history">
      <div class="bill-box"><span class="slds-col row-box">04/17/2031</span>
        <span>Bill Charges</span> <span class="align-right">View Bill PDF
        <span>(opens in a new window)</span></span></div>
      <div class="bill-box"><span class="slds-col row-box">03/18/2031</span>
        <span>Bill Charges</span> <a class="pdf-link" data-bill>View Bill PDF</a></div>
    </li></ul>""" + HOOKS)
    ok, results = _take(page, tmp_path, row_index=0)
    assert page.evaluate("window.presses") == 0, "another bill's link was pressed"
    assert ok is False and not (tmp_path / "bill.pdf").exists()
    assert [o for o, _ in results] == ["refused a row that holds more than one bill",
                                       "found no pdf control"], results
    facts = results[1][1]
    assert facts["page_looked"] is True and facts["page_rows"] == 1
    assert facts["page_crowded"] == 1 and facts["page_links"] == 0


def test_the_usual_look_refuses_a_row_holding_more_than_one_bill(page, tmp_path, no_table):
    """The same crowded list item, with a class that makes it one of the
    rows the usual look reads. That look took any row reading View Bill
    PDF with the bill's date, so it pressed the March bill's link inside
    it and saved it as April's (final review of #33)."""
    page.set_content("""<ul><li class="document-history">
      <div class="bill-box"><span class="slds-col row-box">04/17/2031</span>
        <span>Bill Charges</span> <span class="align-right">View Bill PDF
        <span>(opens in a new window)</span></span></div>
      <div class="bill-box"><span class="slds-col row-box">03/18/2031</span>
        <span>Bill Charges</span> <a class="pdf-link" data-bill>View Bill PDF</a></div>
    </li></ul>""" + HOOKS)
    ok, results = _take(page, tmp_path, row_index=0)
    assert page.evaluate("window.presses") == 0, "another bill's link was pressed"
    assert ok is False and not (tmp_path / "bill.pdf").exists()
    assert results[0][0] == "refused a row that holds more than one bill", results


def test_with_no_row_found_two_bill_rows_with_the_date_are_refused(page, tmp_path, no_table):
    """Nothing says which of two bill rows with one date is this bill. The
    look took the first, whatever it was, and now it takes neither."""
    page.set_content("<ul>" + BILL_LI + BILL_LI + "</ul>" + HOOKS)
    ok, results = _take(page, tmp_path, row_index=0)
    assert ok is False
    assert page.evaluate("window.presses") == 0
    assert not (tmp_path / "bill.pdf").exists()
    assert [o for o, _ in results] == ["refused more than one bill row with the date",
                                       "found no pdf control"], results
    assert results[0][1] == {"rows": 2}
    facts = results[1][1]
    assert facts["row_found"] is False and facts["page_looked"] is True
    assert facts["page_rows"] == 2 and facts["page_links"] == 0


# -- the row is a bill's row ---------------------------------------------------

PAYMENT_THEN_BILL = """<table><tbody>
<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Payment Received</div></td><td></td>
  <td><a class="payment-link" data-refused href="#pay">View payment details</a></td>
  <td><p class="payoffamount-divpara">$12.34</p></td></tr>
<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right"><a class="pdf-link" data-bill>View Bill PDF</a></div></td>
  <td><p class="payoffamount-divpara">$56.78</p></td></tr>
</tbody></table>""" + HOOKS


def test_a_payment_on_the_bills_date_is_not_taken_for_the_bill(page, tmp_path):
    """The history holds payments as well as bills, and a payment made on
    the day another bill is dated shares its date. The usual look took
    the first row with the date, and a refused row is not second guessed
    page wide any more, so the bill would have been given up on."""
    page.set_content(PAYMENT_THEN_BILL)
    row = site._row_for_date(page, "2031-04-17", 0)
    assert row is not None and "View Bill PDF" in row.inner_text()
    ok, results = _download(page, tmp_path)
    assert ok is True and page.evaluate("window.presses") == 1
    assert page.evaluate("window.refused") == 0


def test_an_unlabeled_link_around_hidden_words_is_not_pressed(page):
    """Words the eye cannot see, inside a link that says nothing. The span
    reads View Bill PDF, a press on it lands on the link, and the link has
    not been judged by anything a person would read."""
    page.set_content(ROW % ('<a data-refused href="#pay">'
                            '<span style="display:none">View Bill PDF</span></a>'))
    row = page.query_selector("tr")
    tally = {}
    assert site.pick_document_control(site.row_controls(row), tally) is None
    assert tally.get("unlabeled", 0) >= 1 and tally.get("nearby", 0) >= 1


APPROVED = {
    # his row as the outline drew it
    "his link": '<div class="align-right"><a class="pdf-link" data-bill>View Bill PDF</a></div>',
    # a button whose every label is a bill, with the words in a span
    "a bill button": '<button class="slds-button" data-bill><span>View Bill PDF</span></button>',
    # Pay in the same cell, beside the link and not around it
    "Pay beside it": ('<div class="align-right"><a class="pdf-link" data-bill>View Bill PDF</a>'
                      '<button data-refused>Pay bill</button></div>'),
    # A handler on the page's body hears every click, and the body's text
    # is the whole history with its Payment rows. It is no control around
    # the link, and judging it would refuse every bill.
    "a page wide handler": (
        '<div class="align-right"><a class="pdf-link" data-bill>View Bill PDF</a></div>'
        '<script>document.body.setAttribute("onclick", "void 0");'
        'document.body.insertAdjacentHTML("beforeend", "<p>Payment received</p>");</script>'),
    # Labels on the boxes around the link that name nothing forbidden. A
    # box needs no document word, only no forbidden one.
    "a plain label on the box around it": (
        '<div class="align-right" aria-label="Amount and actions">'
        '<a class="pdf-link" data-bill title="Bill for April">View Bill PDF</a></div>'),
    "a picture of a PDF inside the link": (
        '<div class="align-right"><a class="pdf-link" data-bill>View Bill PDF'
        '<img alt="PDF" src="data:," width="1" height="1"></a></div>'),
}


# Components around the link that the page can see into, or that are
# Salesforce's own, are judged like anything else and do not stop it.
OPEN_BOX = """<script>
  class XBox extends HTMLElement { constructor() { super();
    this.attachShadow({mode: 'open'}).innerHTML = '<span class="frame"><slot></slot></span>';
  } }
  customElements.define('x-box', XBox);
  class LightningFormattedUrl extends HTMLElement { constructor() { super(); } }
  customElements.define('lightning-formatted-url', LightningFormattedUrl);
</script>"""
APPROVED["his link in a component that shows its inside"] = (
    '<x-box><a class="pdf-link" data-bill>View Bill PDF</a></x-box>', OPEN_BOX)
APPROVED["his link in a Salesforce component"] = (
    '<lightning-formatted-url><a class="pdf-link" data-bill>View Bill PDF</a>'
    '</lightning-formatted-url>', OPEN_BOX)


@pytest.mark.parametrize("shape", sorted(APPROVED))
def test_a_control_whose_neighbors_all_pass_is_still_pressed_once(page, tmp_path, shape):
    """The rule is about what a press could set off, not about what shares
    a row, so a Pay button beside the link does not stop it."""
    got = APPROVED[shape]
    page.set_content(_page_with(*got) if isinstance(got, tuple) else ROW % got)
    ok, results = _download(page, tmp_path)
    assert ok is True
    assert (tmp_path / "bill.pdf").read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.refused") == 0


def test_a_heading_above_the_table_is_not_judged_as_part_of_the_press(page, tmp_path):
    """The history is a region that reads Bill and Payment History, and
    Payment is a forbidden word. Labels on plain boxes are judged up to the
    bill's row and no further, so the region every bill sits in does not
    refuse them all."""
    page.set_content('<section aria-label="Bill and Payment History" title="Payment history">'
                     + TABLE % '<div class="align-right"><a class="pdf-link" data-bill>'
                                'View Bill PDF</a></div>'
                     + '</section>' + HOOKS)
    ok, results = _download(page, tmp_path)
    assert ok is True
    assert page.evaluate("window.presses") == 1


def test_a_control_holding_more_than_can_be_judged_is_refused(page, tmp_path):
    """The look inside a control stopped after two hundred things and
    approved what it had seen, so a Pay control further in was never
    judged. Past what it judges now, it refuses (third review of round
    eight). Nothing a bill row really holds comes near this."""
    # Controls by their role, but not ones the row hands over as candidates,
    # so only the look inside the link can find the last one.
    filler = '<span role="link" title="View bill"></span>' * 399
    page.set_content(ROW % ('<a class="pdf-link" data-bill>View Bill PDF' + filler
                            + '<span role="link" data-refused title="Pay this bill"></span></a>'))
    ok, results = _download(page, tmp_path)
    assert page.evaluate("window.presses") == 0, "pressed with a Pay control inside it"
    assert ok is False
    assert results[0][1]["row_nearby"] >= 1
