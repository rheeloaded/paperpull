"""Labels read off real ElementHandles, round eight of #33.

Every fake in the other tests takes inner_text(timeout=None), and a real
ElementHandle's inner_text takes no arguments at all. So the label reader
passed every test here and read every control on the tester's history as
unlabeled, the guard refused them all, and View Bill PDF was never
pressed. His 0.37.0 journal showed it, 140 ms from taking the first bill
to giving up and no wait for a viewer in between.

The fake below is shaped like the real handle, and the rest drive a real
browser, because a fake that is kinder than the thing it stands for is
how this got past. Every date, amount and address here is invented.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site


class _NoProps:
    def get_properties(self):
        return {}


class _Handle:
    """Shaped like Playwright's ElementHandle, whose inner_text takes no
    timeout. Passing one raises TypeError, exactly as the real one does.
    It sits inside nothing and holds nothing, which is what it tells the
    guard when asked what is around it."""

    def __init__(self, text="", attrs=None):
        self._text, self._attrs = text, dict(attrs or {})

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def evaluate(self, expression, arg=None):
        return []

    def evaluate_handle(self, expression, arg=None):
        return _NoProps()


def test_a_handle_that_takes_no_timeout_still_has_a_label():
    assert site.control_label(_Handle("View Bill PDF")) == "View Bill PDF"
    assert site.control_label(_Handle("", {"aria-label": "View PDF"})) == "View PDF"
    assert site.all_labels(_Handle("3", {"aria-label": "Jump to"})) == "3 | Jump to"


def test_the_guard_judges_a_handles_real_text():
    view, pay = _Handle("View Bill PDF"), _Handle("Pay bill")
    assert site.pick_document_control([pay, view]) is view
    assert site.pick_document_control([pay, _Handle("Make a payment")]) is None
    assert site.is_page_option(site.control_label(_Handle("4")), 4)


# -- in a real browser ---------------------------------------------------------

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40


def _aura_answer() -> str:
    """Salesforce's answer carrying the bill as base64, the way round seven
    reads it. Only here so the press has something to hand back."""
    return json.dumps({"actions": [{
        "id": "7;a", "state": "SUCCESS",
        "returnValue": {"returnValue": base64.b64encode(_PDF).decode()}}]})


def _serve(route):
    if "/sfsites/aura" in route.request.url:
        route.fulfill(status=200, content_type="application/json;charset=UTF-8",
                      body=_aura_answer())
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
    ctx.route("https://myaccount.pge.com/**", _serve)
    pg = ctx.new_page()
    pg.goto(HISTORY)
    yield pg
    browser.close()
    driver.stop()


# The row as his round three outline drew it, tr.rowbox with the link in
# td > div.align-right, and no href. Invented date and amount.
ROW = """
<tr class="rowbox">
  <td><div class="slds-col row-box">%s</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td>
  <td>%s</td>
  <td><div class="align-right"><a class="pdf-link">View Bill PDF</a></div></td>
  <td class="no-padding-right"><div><div class="payoffamount-div">
    <p class="payoffamount-divpara">$12.34</p></div></div></td>
</tr>"""

PAGE = """<body><table><tbody>%s</tbody></table><script>
  window.presses = 0;
  for (const a of document.querySelectorAll('a.pdf-link')) {
    a.addEventListener('click', () => {
      window.presses++;
      fetch('/myaccount/s/sfsites/aura?r=9&aura.ApexAction.execute=1',
            {method: 'POST', body: 'message={}'});
    });
  }
</script></body>"""


def test_a_real_bill_row_hands_over_its_view_bill_pdf_link(page):
    page.set_content(PAGE % (ROW % ("04/17/2031", "")))
    row = site._row_for_date(page, "2031-04-17", 0)
    assert row is not None
    link = site.pick_document_control(site.row_controls(row))
    assert link is not None, "every control in the row read as unlabeled"
    assert site.control_label(link) == "View Bill PDF"
    assert link.evaluate("el => el.tagName") == "A", "the link itself, not its cell"


def test_a_real_pay_button_in_the_row_is_still_never_the_one(page):
    page.set_content(PAGE % (ROW % ("04/17/2031", "<button>Pay bill</button>")))
    row = site._row_for_date(page, "2031-04-17", 0)
    link = site.pick_document_control(site.row_controls(row))
    assert site.control_label(link) == "View Bill PDF"
    page.set_content("<table><tbody><tr><td>04/17/2031</td>"
                     "<td>Bill Charges View Bill PDF</td>"
                     "<td><button>Pay bill</button></td></tr></tbody></table>")
    row = site._row_for_date(page, "2031-04-17", 0)
    assert site.control_label(site.row_controls(row)[0]) == "Pay bill"
    assert site.pick_document_control(site.row_controls(row)) is None


def test_the_view_bill_pdf_link_is_chosen_over_an_earlier_control_that_passes(page, tmp_path):
    """The first control that passed the guard was the one pressed. A row
    holding another document action ahead of the bill's link, one whose
    words pass the guard as well, had that pressed instead, and whatever it
    brought would have been taken for the bill (review of round eight's
    repair). The View Bill PDF link goes first now, and the others are
    still there, in their order, when it is refused."""
    page.set_content(PAGE % (ROW % ("04/17/2031", '<a class="usage-link">View usage details</a>'))
                     + "<script>window.usage = 0; document.querySelector('a.usage-link')"
                       ".addEventListener('click', () => window.usage++);</script>")
    row = site._row_for_date(page, "2031-04-17", 0)
    link = site.pick_document_control(site.row_controls(row), row=row)
    assert link is not None and site.control_label(link) == "View Bill PDF"
    assert link.evaluate("el => el.className") == "pdf-link"
    assert site.download_bill(page, {"date_text": "2031-04-17", "row_index": 0,
                                     "page_number": 1}, tmp_path / "bill.pdf", {}) is True
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.usage") == 0, "the other control took the press"


def test_a_control_that_passes_is_still_taken_when_it_is_the_only_one(page):
    """Preferring View Bill PDF is an order, not a new rule. A row whose
    one approved control says something else still hands it over, as it
    did before."""
    page.set_content("<table><tbody><tr><td>04/17/2031</td><td>Bill Charges View Bill PDF</td>"
                     "<td><a class='doc'>Download bill</a></td></tr></tbody></table>")
    row = site._row_for_date(page, "2031-04-17", 0)
    link = site.pick_document_control(site.row_controls(row), row=row)
    assert link is not None and site.control_label(link) == "Download bill"


def test_a_real_page_option_reads_its_number(page):
    page.set_content("<div aria-label='Jump to'>1</div>"
                     "<lightning-base-combobox-item data-value='3'>3"
                     "</lightning-base-combobox-item>")
    opt = page.query_selector("lightning-base-combobox-item[data-value='3']")
    assert site.is_page_option(site.control_label(opt), 3)
    assert site.all_labels(page.query_selector("div")) == "1 | Jump to"


def _results(journal) -> list:
    return [e for e in journal.report()["entries"] if e.get("kind") == "result"]


def test_download_bill_presses_view_bill_pdf_once_and_saves_the_bill(page, tmp_path):
    """The whole of what his run never reached. It found the row, read
    every control as unlabeled, printed that no link was found and gave
    up without pressing anything.

    The press and the one press are what this proves. How PG&E hands the
    bill back after it is not known, and the answer served here is only a
    stand-in so the capture has something to take."""
    from paperpull_core.journal import Journal
    page.set_content(PAGE % "".join(ROW % (d, "") for d in
                                    ("04/17/2031", "03/18/2031", "02/16/2031")))
    out = tmp_path / "bill.pdf"
    doc = {"date_text": "2031-03-18", "row_index": 1, "page_number": 1}
    j = Journal(page)
    site.set_journal(j)
    try:
        assert site.download_bill(page, doc, out, {}) is True
    finally:
        site.set_journal(None)
    assert out.read_bytes() == _PDF
    assert page.evaluate("window.presses") == 1
    # and the failure file would have said how the press went
    pressed = [e for e in _results(j) if e["outcome"] == "pressed the pdf control"]
    assert pressed and pressed[0]["facts"]["answer"] is True
    assert pressed[0]["facts"]["tab"] is False
    assert pressed[0]["facts"]["landed"] is True
    assert pressed[0]["facts"]["own_click"] is False


def test_a_bill_with_no_control_says_so_in_the_journal(page, tmp_path):
    """His file could only be read off the time between two entries. The
    next one says the row was found, how many controls it handed over,
    and that they were refused rather than missing, in numbers only."""
    from paperpull_core.journal import Journal
    # The words are in the row, so it counts as a bill row, but nothing in
    # it reads as the control itself, and Pay is refused.
    page.set_content("<table><tbody><tr><td>04/17/2031</td>"
                     "<td>Bill Charges View Bill PDF</td>"
                     "<td><button>Pay bill</button></td></tr></tbody></table>")
    j = Journal(page)
    site.set_journal(j)
    try:
        doc = {"date_text": "2031-04-17", "row_index": 0, "page_number": 1}
        assert site.download_bill(page, doc, tmp_path / "bill.pdf", {}) is False
    finally:
        site.set_journal(None)
    results = [(e["outcome"], e["facts"]) for e in _results(j)]
    assert len(results) == 1 and results[0][0] == "found no pdf control"
    facts = results[0][1]
    assert facts["row_found"] is True
    # the button is handed over by the walk and by the query, and refused
    # both times, and nothing in the row was unlabeled
    assert facts["row_candidates"] >= 1
    assert facts["row_refused"] == facts["row_candidates"]
    assert facts["row_unlabeled"] == 0
    assert facts["page_links"] == 0 and facts["page_refused"] == 0
    assert all(isinstance(v, (bool, int)) for v in facts.values())
