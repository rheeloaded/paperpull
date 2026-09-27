"""What the review of round eight found once labels read (#33).

Reading labels switched on code that had never run on his account. The
press was forced, so a dialog over the row would have taken it. The guard
judged the first label and never the aria-label behind visible text. The
row description and the console lines carried page text. And a bill that
opened in a new tab at a blob address was waited for and thrown away,
because the host check moved to the core in 0.33.0 and the core takes no
blob address.

Every date, amount, number and address here is invented.
"""
import base64
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40


def _serve(route):
    """The history, and an answer from Salesforce carrying the bill, only
    so a press has something to hand back quickly. Whether PG&E answers
    this way is not known."""
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


def _results(journal, outcome):
    return [e.get("facts", {}) for e in journal.report()["entries"]
            if e.get("kind") == "result" and e.get("outcome") == outcome]


# His round three outline, tr.rowbox with the link in td > div.align-right
# and no href.
ROW = """<table><tbody><tr class="rowbox">
  <td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td>
  <td></td>
  <td><div class="align-right"><a class="pdf-link">%s</a></div></td>
  <td class="no-padding-right"><div><div class="payoffamount-div">
    <p class="payoffamount-divpara">$12.34</p></div></div></td>
</tr></tbody></table>"""

ON_PRESS = """<script>
  window.presses = 0;
  document.querySelector('a.pdf-link').addEventListener('click', () => {
    window.presses++;
    %s
  });
</script>"""

ASK_SALESFORCE = ("fetch('/myaccount/s/sfsites/aura?r=9&aura.ApexAction.execute=1',"
                  " {method: 'POST', body: 'message={}'});")

DIALOG_OVER_THE_ROW = """<div role="dialog" style="position:fixed;inset:0;z-index:10;background:#fff">
  <button id="promo" style="width:100%;height:100%">Enroll in paperless now, account 55 12</button>
</div><script>
  window.promo = 0;
  document.getElementById('promo').addEventListener('click', () => window.promo++);
</script>"""


def _download(page, tmp_path, date="2031-04-17"):
    from paperpull_core.journal import Journal
    out = tmp_path / "bill.pdf"
    j = Journal(page)
    site.set_journal(j)
    try:
        ok = site.download_bill(page, {"date_text": date, "row_index": 0,
                                       "page_number": 1}, out, {})
    finally:
        site.set_journal(None)
    return ok, out, j


# -- the press lands on the link and nothing else -----------------------------

def test_a_dialog_over_the_row_never_takes_the_press(page, tmp_path, caplog):
    """The review's case. The draft pressed with force, so the mouse went
    to the dialog's button, a control no guard had read. The link's own
    click reaches the link and nothing else."""
    caplog.set_level(logging.INFO, logger="pge_docs.site")
    page.set_content(ROW % "View Bill PDF" + ON_PRESS % ASK_SALESFORCE
                     + DIALOG_OVER_THE_ROW)
    ok, out, j = _download(page, tmp_path)
    assert page.evaluate("window.promo") == 0, "the dialog's button took the press"
    assert page.evaluate("window.presses") == 1
    assert ok is True and out.read_bytes() == _PDF
    pressed = _results(j, "pressed the pdf control")
    assert pressed and pressed[0]["landed"] is True and pressed[0]["own_click"] is True
    # the error that says what covered the link is page text, and stays out
    assert "Enroll" not in caplog.text and "55 12" not in caplog.text


def test_an_uncovered_link_takes_an_ordinary_click(page, tmp_path):
    page.set_content(ROW % "View Bill PDF" + ON_PRESS % ASK_SALESFORCE)
    ok, out, j = _download(page, tmp_path)
    assert ok is True and page.evaluate("window.presses") == 1
    pressed = _results(j, "pressed the pdf control")
    assert pressed[0]["landed"] is True and pressed[0]["own_click"] is False


def test_a_press_that_lands_nowhere_says_so_and_nothing_else(caplog):
    caplog.set_level(logging.INFO, logger="pge_docs.site")

    class _Gone:
        def click(self, timeout=None):
            raise RuntimeError("<button>Enroll, account 55 12</button> intercepts pointer events")

        def evaluate(self, js, arg=None):
            raise RuntimeError("<div>account 55 12</div> is not attached")

    class _Page:
        def on(self, *a):
            pass

        def remove_listener(self, *a):
            pass

        def wait_for_timeout(self, ms):
            pass

    said = {}
    assert site._press_once(_Page(), _Gone(), lambda: False, seconds=0.1, said=said) is None
    assert said == {"landed": False, "own_click": False, "late_error": False}
    assert "55 12" not in caplog.text and "Enroll" not in caplog.text


# -- the guard judges every label ---------------------------------------------

def test_every_label_is_judged_not_only_the_first(page):
    """Visible text reading View bill hid an aria-label reading Pay this
    bill, because the guard judged only the first label it found."""
    page.set_content("<button id='a' aria-label='Pay this bill'>View bill</button>"
                     "<a id='b' class='pdf-link' title='Update payment method'>View Bill PDF</a>"
                     "<a id='c' class='pdf-link'>View Bill PDF</a>")
    a, b, c = (page.query_selector("#" + x) for x in "abc")
    assert site.pick_document_control([a]) is None
    assert site.pick_document_control([b]) is None
    assert site.pick_document_control([a, b, c]) is c


# -- what he pastes is built from what may leave ------------------------------

def test_the_row_description_carries_no_page_text(page):
    """It printed the row's text and every control's label with runs of
    four digits masked, so an amount and a short run of an account number
    went through. It is built from tags, classes, the words this file
    knows and the shape of anything else now."""
    page.set_content(
        "<table><tbody><tr class='rowbox'>"
        "<td><div class='slds-col row-box'>04/17/2031</div></td>"
        "<td><span>Acct ending 55 12</span></td>"
        "<td><div class='align-right'><span class='pdf-text'>View Bill PDF</span>"
        "<a class='doc-9931' href='/myaccount/s/doc?id=0681U00000AbCdE'>Statement</a></div></td>"
        "<td><p class='payoffamount-divpara'>$87.12</p></td></tr></tbody></table>")
    said = site._describe_row(page.query_selector("tr"))
    for leak in ("87", "55 12", "Acct", "2031", "AbCdE", "0681", "9931", "Statement", "doc?id"):
        assert leak not in said, (leak, said)
    for kept in ("View Bill PDF", "<amount>", "<date>", "href=relative",
                 "div.align-right", "p.payoffamount-divpara"):
        assert kept in said, (kept, said)


def test_the_outline_is_built_from_word_lists_and_not_from_the_page(page):
    """Classes, tags and roles were let through when they merely looked
    like names, so a class or a custom tag the page made up left as
    written. Now a class must be on a list, a made up tag is named as
    custom, a made up role is dropped, and a label is only said to be
    there (second review of round eight)."""
    page.set_content(
        "<table><tbody><tr class='rowbox'>"
        "<td class='jdoe-residence'><div class='slds-col row-box'>04/17/2031</div></td>"
        "<td><c-jane-doe-card role='janedoe'>"
        "<div class='align-right'><a class='pdf-link smithfamily' "
        "title='Statement for Jane Doe'>View Bill PDF</a></div>"
        "</c-jane-doe-card></td></tr></tbody></table>")
    said = site._describe_row(page.query_selector("tr"))
    for leak in ("jdoe", "jane", "Jane", "janedoe", "smithfamily", "Doe"):
        assert leak not in said, (leak, said)
    for kept in ("tr.rowbox", "div.slds-col.row-box", "div.align-right",
                 "a.pdf-link (labeled) = View Bill PDF", "custom"):
        assert kept in said, (kept, said)


def test_the_outline_says_which_nodes_carry_a_label_the_guard_reads(page):
    """The guard judges an aria-labelledby, an alt and the label attribute
    as well now, so the outline says a node carries one, and never what it
    says (third review of round eight)."""
    page.set_content(
        "<table><tbody><tr class='rowbox'>"
        "<td><div class='slds-col row-box'>04/17/2031</div></td>"
        "<td><span id='n9' hidden>Jane Doe</span>"
        "<div class='align-right' label='Jane Doe'><a class='pdf-link' aria-labelledby='n9'>"
        "View Bill PDF<img alt='Jane Doe' src='data:,'></a></div></td></tr></tbody></table>")
    said = site._describe_row(page.query_selector("tr"))
    for leak in ("Jane", "Doe", "n9"):
        assert leak not in said, (leak, said)
    for kept in ("div.align-right (labeled)", "a.pdf-link (labeled) = View Bill PDF",
                 "img (labeled)"):
        assert kept in said, (kept, said)


def test_the_found_line_says_what_it_found_in_this_files_words(page, tmp_path, capsys):
    page.set_content(ROW % "View Bill PDF (Acct 55 12)" + ON_PRESS % ASK_SALESFORCE)
    ok, _, _ = _download(page, tmp_path)
    assert ok is True
    printed = capsys.readouterr().out
    assert "Found a bill control" in printed
    assert "55 12" not in printed and "Acct" not in printed


def test_an_address_is_said_as_pge_or_elsewhere_and_never_as_written():
    """The line for a tab that moved named the host it moved to as written,
    and a tab can move anywhere. The host is said the way the row outline
    says a link's, pge or elsewhere (review of round eight's repair)."""
    for url, said in [
            ("https://myaccount.pge.com/myaccount/s/viewbill?acct=5512", "a page on pge"),
            ("https://www.pge.com/docs/invented-bill.pdf", "a PDF on pge"),
            ("https://jane-doe-residence.example/invented-bill.pdf", "a PDF elsewhere"),
            ("http://myaccount.pge.com/insecure", "a page elsewhere"),
            ("https://myaccount.pge.com.jane-doe.example/viewer", "a page elsewhere"),
            ("blob:https://myaccount.pge.com/4b1d", "a blob on pge"),
            ("blob:https://jane-doe-residence.example/4b1d", "a blob elsewhere"),
            ("", "a page elsewhere"),
            ("https://[invented", "a page")]:
        assert site._url_shape(url) == said, url


def test_the_line_for_a_tab_that_moved_names_no_host(page, tmp_path, capsys, monkeypatch):
    """The tab moves to PG&E's viewer instead of opening one, and the line
    that says so is pasted into a public issue."""
    # The history the tab is put back on has no rows here, and the wait
    # for them would run its full twenty seconds.
    monkeypatch.setattr(site, "wait_for_rows", lambda page, seconds=20: 0)
    page.set_content(ROW % "View Bill PDF" + ON_PRESS % (
        "location.href = 'https://myaccount.pge.com/myaccount/s/viewbill?acct=5512';"))
    ok, out, _ = _download(page, tmp_path)
    assert ok is False and not out.exists()
    printed = capsys.readouterr().out
    assert "the tab moved to a page on pge rather than opening one" in printed
    assert "myaccount.pge.com" not in printed and "5512" not in printed
    assert page.url == HISTORY, "the tab is put back on the history"


# -- the tabs a press opened ---------------------------------------------------

def test_a_tab_the_press_opened_is_closed_even_when_reading_it_fails(
        page, tmp_path, monkeypatch):
    """The tabs a press opened were closed at the end of the capture, so
    anything that raised on the way skipped it, and the tab stayed open
    into the next bill (review of round eight's repair). They are closed
    however the bill ends now."""
    def fails(holders, blob_url):
        raise RuntimeError("an invented failure while the new tab is read")

    monkeypatch.setattr(site, "_take_blob", fails)
    page.set_content(ROW % "View Bill PDF" + ON_PRESS % OPEN_A_BLOB_TAB)
    ok, out, _ = _download(page, tmp_path)
    assert ok is False and not out.exists()
    assert page.evaluate("window.presses") == 1
    assert len(page.context.pages) == 1, "the tab the press opened was left open"


# -- a bill that opens in a new tab at a blob ---------------------------------

# Plain text so headless Chromium keeps it as a tab rather than turning it
# into a download, which is what it does with a PDF type. The bytes are
# what count.
OPEN_A_BLOB_TAB = ("const b = new TextEncoder().encode('%PDF-1.4 an invented bill');"
                   "window.open(URL.createObjectURL(new Blob([b], {type: 'text/plain'})));")


def test_a_bill_opened_in_a_new_tab_at_a_blob_is_saved(page, tmp_path):
    """The contributor who first built this against a real account wrote
    the wait for this tab. From 0.33.0 the host check refused its address
    and the tab was closed with nothing taken."""
    page.set_content(ROW % "View Bill PDF" + ON_PRESS % OPEN_A_BLOB_TAB)
    ok, out, j = _download(page, tmp_path)
    assert ok is True
    assert out.read_bytes() == b"%PDF-1.4 an invented bill"
    assert page.evaluate("window.presses") == 1
    pressed = _results(j, "pressed the pdf control")[0]
    assert pressed["tab"] is True and pressed["blob_tab"] is True
    # read by the page's own fetch here, since this page has no policy
    # against it (test_capture_under_a_page_policy.py has one)
    assert _results(j, "read the new tab") == [
        {"pge_origin": True, "bill": True, "by_download": False}]
    assert len(page.context.pages) == 1, "the tab is closed afterwards"


def test_a_blob_from_anywhere_else_is_never_read():
    """Neither by a fetch nor by saving it as a download."""
    class _NeverAsked:
        def evaluate(self, *a, **k):
            raise AssertionError("a blob off PG&E was fetched")

        def expect_download(self, *a, **k):
            raise AssertionError("a blob off PG&E was saved")

    for url in ("blob:https://elsewhere.test/1", "blob:http://myaccount.pge.com/1",
                "blob:https://myaccount.pge.com.elsewhere.test/1", "https://myaccount.pge.com/1"):
        assert site._pdf_from_blob_tab(_NeverAsked(), _NeverAsked(), url) is None, url
        assert site._blob_by_download((_NeverAsked(), _NeverAsked()), url) is None, url
    assert site._blob_on_pge("blob:https://myaccount.pge.com/4b1d")
