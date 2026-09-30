"""American Family's statements, from the tester's answers on #45.

Billing & Payments is myaccount.amfam.com/billing, in the same tab, and a
statement opened there opens a new tab at blob:https://myaccount.amfam.com/...
His .amfam-downloads folder stayed empty, so the browser never saved one as
a download. Until 0.41.0 the app started at /documents, never matched a
control reading "View bill", and read a blob tab only by its address,
which a page can revoke the moment the tab has it.

In a real browser, since a blob and its revoking are the browser's doing.
Every page here is made up and nothing leaves this machine."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amfam_site as site

BASE = "https://myaccount.amfam.com"


def _billing(control: str) -> str:
    return ("<!doctype html><html><body><main><h1>Billing &amp; Payments</h1>"
            "<button data-cy='make-payment'>Make a payment</button>"
            "<section data-cy='statements'><h2>Statements</h2>"
            "<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
            "<span>Amount due $123.45</span>%s</div></section></main><script>"
            "window.__paid = false;"
            "document.querySelector(\"[data-cy='make-payment']\").onclick = () => { window.__paid = true; };"
            "function openStatement() {"
            " const pdf = new Blob(['%%PDF-1.4 invented statement 09/12/2026 ' + 'x'.repeat(400)],"
            "                      {type: 'application/pdf'});"
            " const url = URL.createObjectURL(pdf);"
            " window.open(url, '_blank');"
            " URL.revokeObjectURL(url);"
            "}</script></body></html>" % control)


@pytest.fixture()
def drive():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    opened = []

    def start(control):
        # His Chrome shows the statement in the tab it opens and downloads
        # nothing, which his empty .amfam-downloads says. A browser without
        # a PDF viewer, this one, would download what the tab is sent to
        # instead, so downloads are refused here to keep to his case.
        ctx = browser.new_context(accept_downloads=False)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route("%s/billing" % BASE, lambda r: r.fulfill(
            status=200, content_type="text/html", body=_billing(control)))
        ctx.route("%s/documents" % BASE, lambda r: r.fulfill(
            status=200, content_type="text/html", body="<html><body><h1>Welcome</h1></body></html>"))
        pg = ctx.new_page()
        pg.goto("%s/documents" % BASE)
        # The app's waits, a tenth as long, as in billing() below.
        wait = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        opened.append(ctx)
        return pg

    yield start
    browser.close()
    driver.stop()


def test_billing_is_where_the_statements_are_looked_for_first():
    assert site.BILLING_CANDIDATES[0] == BASE + "/billing"


@pytest.mark.parametrize("control", [
    "<button data-cy='view-statement' onclick='openStatement()'>View bill</button>",
    "<button data-cy='view-statement' onclick='openStatement()'>View statement</button>",
], ids=["View bill", "View statement"])
def test_a_statement_opened_as_a_blob_tab_and_revoked_is_saved(drive, tmp_path, control):
    page = drive(control)
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    trace: list = []
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out,
                              trace=trace) is True, trace
    assert out.read_bytes().startswith(b"%PDF-")
    assert b"invented statement 09/12/2026" in out.read_bytes()
    assert {"note": "the page made the PDF itself, a blob it opened"} in trace
    assert page.evaluate("window.__paid") is False, "nothing but the statement was pressed"
    assert len(page.context.pages) == 1, "the tab it opened is closed after"


def _pressable(words):
    return bool(site.BILL_CONTROL_RE.search(words)) and site.is_safe_control(words)


def test_the_payment_button_on_the_billing_page_is_never_a_document():
    for words in ("Make a payment", "Pay bill", "Pay now", "Set up autopay", "Bill pay"):
        assert not _pressable(words), words
    for words in ("View bill", "View billing statement", "Download bill", "View statement",
                  "Download PDF", "Statement (PDF)"):
        assert _pressable(words), words


@pytest.mark.parametrize("words", [
    "Get your bill by email", "Get your bill by text", "Get your bill in the mail",
    "Get bill reminders", "Get bill notifications", "Get billing statements by email",
    "Receive billing statement electronically", "Stop mailing my billing statement",
    "Switch billing statement to monthly", "Combine into one billing statement",
    "Get one billing statement for all your policies", "View bill and reinstate policy",
    "View declarations page and renew", "Mail me a declarations page",
    "Email declarations page", "Get ID card by mail", "View ID card request",
    "View bill and pay", "Pay your bill", "View billing options", "Download autopay form",
    "Print payment receipt", "Get a quote on your bill", "Print bill",
])
def test_a_control_that_changes_how_bills_are_sent_is_never_pressed(words):
    """Widened for 0.41.0, the words matched these, and the guard, a list of
    refusals, knew none of their verbs, so a Pilot pressed "Get your bill by
    email" and "Get bill reminders" before the statement (review)."""
    assert not _pressable(words), words


def test_a_date_run_into_the_next_word_is_read():
    """Spans with nothing between them read "09/12/2026Amount due", the way
    JSX leaves adjacent tags. The row finder in the page found that date and
    the parser refused it, so the statement's control was never found."""
    assert site.parse_date("Statement date 09/12/2026Amount due $123.45View bill") == "2026-09-12"
    assert site.parse_date("Due10/01/2026") == "2026-10-01"
    assert site.parse_date("Sep 12, 2026Paid") == "2026-09-12"
    # and a longer run of digits is still not a date
    assert site.parse_date("on 09/12/20261") is None
    assert site.parse_date("ref 123/45/2026") is None


# -- from the pre-release review of 0.41.0 ------------------------------------------------

OVERVIEW = ("<!doctype html><html><body><main><h1>Welcome back</h1>"
            "<div><span>ID cards issued 09/12/2026</span>"
            "<button onclick='openIdCard()'>View statement</button></div>"
            "<a href='/billing'>Billing &amp; Payments</a></main><script>"
            "function openIdCard() {"
            " const pdf = new Blob(['%PDF-1.4 invented ID card 09/12/2026 ' + 'y'.repeat(400)],"
            "                      {type: 'application/pdf'});"
            " window.open(URL.createObjectURL(pdf), '_blank'); }"
            "</script></body></html>")

TWO_BLOBS = ("<button data-cy='view-statement' onclick='openBoth()'>View statement</button>"
             "<script>function openBoth() { openStatement(); setTimeout(() => {"
             " URL.createObjectURL(new Blob(['%PDF-1.4 invented ID card ' + 'y'.repeat(400)],"
             " {type: 'application/pdf'})); }, 300); }</script>")

NO_TAB = ("<button data-cy='view-statement' onclick='late()'>View statement</button>"
          "<script>function late() { URL.createObjectURL(new Blob(['%PDF-1.4 invented late '"
          " + 'z'.repeat(400)], {type: 'application/pdf'})); }</script>")


def test_the_overview_tab_is_left_for_billing_and_payments(drive, tmp_path):
    """Started from the overview, which carried "View bill" and "View ID
    cards", the app took it for billing and saved an ID card as a statement."""
    page = drive("<button data-cy='view-statement' onclick='openStatement()'>View statement</button>")
    page.context.route("%s/overview" % BASE, lambda r: r.fulfill(
        status=200, content_type="text/html", body=OVERVIEW))
    page.goto("%s/overview" % BASE)
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"invented statement 09/12/2026" in out.read_bytes()
    assert b"ID card" not in out.read_bytes()


def test_a_second_pdf_the_same_press_makes_is_not_taken_for_the_statement(drive, tmp_path):
    page = drive(TWO_BLOBS)
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"invented statement 09/12/2026" in out.read_bytes()


def test_a_pdf_made_without_a_tab_of_its_own_is_never_taken(drive, tmp_path, monkeypatch):
    """A late PDF from an earlier press, or anything else the page makes."""
    page = drive(NO_TAB)
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert not out.exists()


# -- from the second review of 0.41.0 ----------------------------------------------------

@pytest.mark.parametrize("words", [
    "Get your statements online", "Get your statements in the mail", "Get statements by US mail",
    "Get statement by postal mail", "Get your statement mailed",
    "Get statements delivered electronically", "Get documents electronically",
    "Get documents via text", "Get notices texted to you", "Get PDF statements",
    "Get tax documents online", "Get statements quarterly", "Get statement on a different date",
    "Get documents in Spanish", "Stop paper - get statements online", "Go paperless",
    "View statement delivery preferences", "Open bill settings", "View statements online",
])
def test_a_control_that_changes_how_statements_arrive_is_never_pressed(words):
    """Worded with statements or documents instead of a bill, each passed
    both checks, since a word anywhere in a label matched and "get" was a
    verb the words took."""
    assert not _pressable(words), words


@pytest.mark.parametrize("words", [
    "View bill 09/12/2026", "View bill for policy ending 1234",
    "View billing statement for September 2026", "Billing statement 09/12/2026",
    "View bill, opens in a new tab", "View bill for September 12, 2026", "View current bill",
    "Download statement (PDF)", "View", "View PDF",
])
def test_a_statement_control_with_a_date_or_policy_after_its_name_is_pressable(words):
    """0.40.0 found these, and the first repair's whole-label View bill did not."""
    assert _pressable(words), words


def _page(rows: str, script: str = "") -> str:
    return ("<!doctype html><html><body><main><h1>Billing &amp; Payments</h1>"
            "<button data-cy='make-payment'>Make a payment</button>%s</main><script>"
            "window.__paid = false; window.__changed = false;"
            "document.querySelector(\"[data-cy='make-payment']\").onclick = () => { window.__paid = true; };"
            "function openPdf(words) {"
            " const pdf = new Blob(['%%PDF-1.4 invented ' + words + ' ' + 'x'.repeat(400)],"
            "                      {type: 'application/pdf'});"
            " const url = URL.createObjectURL(pdf);"
            " window.open(url, '_blank');"
            " URL.revokeObjectURL(url);"
            "}%s</script></body></html>" % (rows, script))


STATEMENT_ROW = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
                 "<span>Amount due $123.45</span>"
                 "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")


@pytest.fixture()
def billing():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)

    def start(billing_html, documents_html="<html><body><h1>Welcome</h1></body></html>"):
        ctx = browser.new_context(accept_downloads=False)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route("%s/billing" % BASE, lambda r: r.fulfill(
            status=200, content_type="text/html", body=billing_html))
        ctx.route("%s/documents" % BASE, lambda r: r.fulfill(
            status=200, content_type="text/html", body=documents_html))
        pg = ctx.new_page()
        pg.goto("%s/billing" % BASE)
        # The app's waits, a tenth as long, so a press that brings nothing
        # gives up in seconds rather than half a minute.
        wait = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        return pg

    yield start
    browser.close()
    driver.stop()


@pytest.mark.parametrize("words", ["Get your statements online", "Get statements by US mail",
                                   "Get documents electronically", "Get statements quarterly"])
def test_a_paperless_card_above_the_statements_is_never_pressed(billing, tmp_path, words):
    """Its button took the card's due date from two levels up, was listed
    as the newest Account Statement, and was pressed first by a Pilot."""
    card = ("<div data-cy='paperless'><div><span>Amount due $123.45 by Oct 1, 2026</span></div>"
            "<div><button onclick='window.__changed = true'>%s</button></div></div>" % words)
    page = billing(_page(card + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]
    out = tmp_path / "Statements" / "2026-10-01 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-10-01", out) is False
    assert page.evaluate("window.__changed") is False
    assert page.evaluate("window.__paid") is False


OTHER_ROWS = ("<div data-cy='plan-row'><span>Payment plan agreement 01/02/2026</span>"
              "<button onclick=\"openPdf('payment plan agreement')\">Download PDF</button></div>"
              "<div data-cy='id-row'><span>Auto ID card, issued 09/12/2026</span>"
              "<button onclick=\"openPdf('ID card')\">View</button></div>")


def test_another_document_on_the_billing_page_is_not_a_statement(billing, tmp_path):
    """A bare Download PDF or View takes its row's word for what it is. An
    agreement was listed as an Account Statement, and the ID card's View,
    carrying the statement's date and above it, was pressed in its place."""
    page = billing(_page(OTHER_ROWS + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()
    assert b"ID card" not in out.read_bytes()


def test_a_bare_view_in_a_statement_row_is_still_found(billing, tmp_path):
    row = ("<div data-cy='statement-row'><span>Billing statement 09/12/2026</span>"
           "<button onclick=\"openPdf('statement 09/12/2026')\">View</button></div>")
    page = billing(_page(row))
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


LATE_ROWS = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
             "<button onclick='window.__pressedSeptember = true'>View bill</button></div>"
             "<div data-cy='statement-row'><span>Statement date 08/12/2026</span>"
             "<button onclick='lateAugust()'>View bill</button></div>")
# August's PDF comes only once September has been pressed, the way one that
# is slow to come lands inside the next press's wait.
LATE_SCRIPT = ("function lateAugust() { const t = setInterval(() => {"
               " if (window.__pressedSeptember) { clearInterval(t);"
               " setTimeout(() => openPdf('AUGUST statement, late'), 300); } }, 50); }")


def test_a_pdf_that_comes_after_its_press_was_given_up_is_not_the_next_statement(billing, tmp_path):
    """Its own page opened it, so it passed as one the press had opened, and
    September was saved holding August and marked done."""
    page = billing(_page(LATE_ROWS, LATE_SCRIPT))
    folder = tmp_path / "Statements"
    august = folder / "2026-08-12 American Family Account Statement.pdf"
    september = folder / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-08-12", august) is False
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", september) is False
    assert not september.exists() and not august.exists()


def test_only_billing_and_payments_is_used(billing, tmp_path):
    """A policy paid through a mortgage has no bills, so the billing page
    showed none, and the app went on to the documents page and saved an ID
    card there as that day's statement."""
    escrow = ("<!doctype html><html><body><main><h1>Billing &amp; Payments</h1>"
              "<p>Your home policy is paid by your mortgage company. No bills are due.</p>"
              "</main></body></html>")
    documents = _page("<div><span>Auto ID card, issued 09/12/2026</span>"
                      "<button onclick=\"openPdf('ID card')\">View</button></div>")
    page = billing(escrow, documents)
    assert site.goto_documents(page) is False
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert not out.exists()
    assert site.BILLING_URL == BASE + "/billing"


def test_a_blob_opened_with_a_fragment_is_its_own_blob(billing, tmp_path):
    """blob:...#page=1 is the same blob, and the address was compared whole."""
    row = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
           "<button onclick='withFragment()'>View bill</button></div>")
    script = ("function withFragment() {"
              " const pdf = new Blob(['%PDF-1.4 invented statement 09/12/2026 ' + 'x'.repeat(400)],"
              "                      {type: 'application/pdf'});"
              " const url = URL.createObjectURL(pdf);"
              " window.open(url + '#page=1', '_blank');"
              " URL.revokeObjectURL(url); }")
    page = billing(_page(row, script))
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


# -- from the safety review of the second repair ------------------------------------------

SUMMARY = ("<div data-cy='summary'><p>Your latest billing statement was issued 09/12/2026. "
           + "Your policies stay in force while payments arrive on time, and a reminder is sent "
             "before each due date so nothing is missed along the way. " * 4 + "</p></div>")
AUGUST_ROW = ("<div data-cy='statement-row'><span>Statement date 08/12/2026</span>"
              "<button onclick=\"openPdf('statement 08/12/2026')\">View bill</button></div>")


def test_a_document_in_a_row_with_no_date_is_not_the_newest_statement(billing, tmp_path):
    """Its row had no date, so the climb reached the whole list, whose
    summary said the billing statement was issued 09/12/2026, and the
    agreement above the statements was saved as that statement."""
    agreement = ("<div data-cy='plan-row'><span>Payment plan agreement</span>"
                 "<button onclick=\"openPdf('payment plan agreement')\">Download PDF</button></div>")
    page = billing(_page("<div data-cy='list'>" + SUMMARY + agreement + STATEMENT_ROW + AUGUST_ROW + "</div>"))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12", "2026-08-12"]
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


def test_a_payments_receipt_is_not_a_statement(billing):
    receipt = ("<div data-cy='payment-row'><span>Bill payment received 09/20/2026 $123.45</span>"
               "<button onclick=\"openPdf('payment receipt')\">View</button></div>")
    page = billing(_page(receipt + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


def test_a_press_is_refused_where_another_control_sits_at_its_center(billing, tmp_path):
    """A card labelled for the statement, with a button of its own in the
    middle, pressed that button. This one has no words, so only where the
    press lands can tell."""
    card = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
            "<div role='button' aria-label='View bill for September 12, 2026' tabindex='0'"
            " style='position:relative;width:320px;height:120px'"
            " onclick=\"openPdf('statement 09/12/2026')\">"
            "<button style='position:absolute;left:110px;top:35px;width:100px;height:50px'"
            " onclick=\"event.stopPropagation(); fetch('/changed')\"></button></div></div>")
    page = billing(_page(card))
    # Kept outside the page, since a press that brings nothing loads it again.
    changed = []
    page.context.route("%s/changed" % BASE, lambda r: changed.append(1) or r.fulfill(status=204, body=""))
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert changed == []


@pytest.mark.parametrize("control", [
    "<button aria-label='View bill' onclick='window.__changed = true'>Go paperless</button>",
    "<button aria-label='View' onclick='window.__changed = true'>Enroll in paperless</button>",
    "<span id='says'>Enroll in paperless billing</span>"
    "<button aria-labelledby='says' onclick='window.__changed = true'>View bill</button>",
    "<button onclick='window.__changed = true'>View bill<img alt='and turn on autopay' src=''></button>",
], ids=["label and words differ", "a bare View that enrolls", "labelledby", "image alt"])
def test_a_control_is_pressed_only_when_every_word_it_shows_or_announces_is_safe(billing, tmp_path, control):
    row = "<div data-cy='statement-row'><span>Statement date 09/12/2026</span>%s</div>" % control
    page = billing(_page(row))
    assert site.collect_download_docs(page) == []
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert page.evaluate("window.__changed") is False


def test_show_all_never_leaves_billing_and_payments(billing):
    """"View all documents" took the app to the documents page, where an
    ID card was read as a statement."""
    documents = _page("<div><span>ID card issued 10/01/2026</span>"
                      "<button onclick=\"openPdf('ID card')\">View statement</button></div>")
    page = billing(_page(STATEMENT_ROW + "<a href='/documents'>View all documents</a>"), documents)
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]
    assert page.url.endswith("/billing")


def test_a_billing_page_that_sends_the_tab_elsewhere_is_not_billing(billing):
    page = billing("<!doctype html><html><body><p>One moment</p></body></html>")
    overview = _page("<div><span>Statement date 09/12/2026</span>"
                     "<button onclick=\"openPdf('overview')\">View statement</button></div>")
    page.context.route("%s/overview" % BASE, lambda r: r.fulfill(
        status=200, content_type="text/html", body=overview))
    page.context.route("%s/billing" % BASE, lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="<html><body><script>location.replace('/overview')</script></body></html>"))
    assert site.goto_documents(page) is False
    assert page.url.endswith("/overview"), "the tab really was sent on"


def test_a_card_naming_two_statements_is_filed_under_neither(billing, tmp_path):
    """The first date in the card won, so September was saved as the August
    statement, and the real August statement was dropped as a duplicate."""
    card = ("<div data-cy='summary-card'><span>Previous statement 08/12/2026</span>"
            "<span>Current statement 09/12/2026</span>"
            "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    page = billing(_page(card + AUGUST_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-08-12"]
    out = tmp_path / "Statements" / "2026-08-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-08-12", out) is True
    assert b"statement 08/12/2026" in out.read_bytes()


def test_a_month_named_in_the_words_picks_that_months_date(billing):
    """"View billing statement for September 2026" took the row's first
    date, the due date in October."""
    row = ("<div data-cy='statement-row'><span>Due 10/01/2026</span> <span>09/12/2026</span>"
           "<button onclick=\"openPdf('statement 09/12/2026')\">View billing statement for September 2026</button></div>")
    page = billing(_page(row))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


def test_closing_an_overlay_never_presses_close_my_account(billing):
    """Anything that began with Close was pressed."""
    page = billing(_page(
        "<button onclick='window.__changed = true'>Close my account</button>"
        "<button onclick='window.__changed = true'>Close policy</button>"
        "<div role='dialog'><button onclick='window.__closed = true'>Close</button></div>"))
    site.dismiss_overlay(page)
    assert page.evaluate("window.__changed") is False
    assert page.evaluate("window.__closed === true")


# -- from the review of the fourth repair --------------------------------------------------

def test_a_next_bill_date_is_never_the_statements_own(billing):
    """"Next bill date" counted as the statement's own date, so this card's
    statement was filed under 2026-10-12, the next statement's own key, and
    the real one would have been skipped as saved already, for good."""
    card = ("<div data-cy='summary-card'><span>Due date 10/01/2026</span> "
            "<span>Next bill date 10/12/2026</span> "
            "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    page = billing(_page(card + STATEMENT_ROW))
    assert "2026-10-12" not in [d.date_text for d in site.collect_download_docs(page)]


@pytest.mark.parametrize("row", [
    "<div data-cy='payment-row'><span>Payment received 09/20/2026 Ref 44109921</span>"
    "<button onclick=\"openPdf('payment receipt')\">View</button></div>",
    "<div data-cy='policy-row'><span>Auto policy 0045498217 renewed 09/20/2026</span>"
    "<button onclick=\"openPdf('policy summary')\">Download PDF</button></div>",
], ids=["a reference number", "a policy number"])
def test_a_tax_form_number_inside_another_number_is_not_a_tax_form(billing, row):
    page = billing(_page(row + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


def test_a_long_section_is_not_a_row(billing):
    """Read whole, a section that said "statement" far from a payment plan
    was taken for the plan's row."""
    section = ("<section data-cy='documents'><h2>Other documents</h2><p>"
               + "Your documents are kept here for seven years. " * 8
               + "Your statement arrives each month.</p><p>Updated 10/01/2026</p>"
               "<div><span>Payment plan</span>"
               "<button onclick=\"openPdf('payment plan')\">Download PDF</button></div></section>")
    page = billing(_page(section + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


def test_a_link_around_a_button_with_the_same_words_is_pressed(billing, tmp_path):
    """A router's link around a button is one control, and was refused as
    another control at its center."""
    row = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span>"
           "<a href='#' onclick=\"event.preventDefault(); openPdf('statement 09/12/2026')\">"
           "<button>View bill</button></a></div>")
    page = billing(_page(row))
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


@pytest.mark.parametrize("words", [
    "Bill payment 09/20/2026 $123.45", "Bill paid 09/20/2026 by card ending 1234 $123.45",
    "Payment 09/20/2026 applied to statement 09/12/2026", "09/20/2026 | Bill payment | $123.45 | Completed",
    "Bill date 09/12/2026 Payment due 10/01/2026", "Bill 09/12/2026 $123.45 Paid",
])
def test_a_bare_control_in_a_row_that_mentions_a_payment_is_left_alone(billing, tmp_path, words):
    """Each list of a payment's phrasings missed some, and a payment's
    receipt was saved as a statement, one of them under the statement's own
    date, above it. A bill's row that mentions a payment is left alone as
    well, since only its words could tell the two apart."""
    row = ("<div data-cy='row'><span>%s</span> "
           "<button onclick=\"openPdf('payment receipt')\">View</button></div>" % words)
    page = billing(_page(row + STATEMENT_ROW))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


def test_a_control_naming_the_bill_is_found_whatever_its_row_says(billing):
    row = ("<div data-cy='row'><span>Statement date 09/12/2026</span> <span>Payment due 10/01/2026</span> "
           "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    page = billing(_page(row))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


@pytest.mark.parametrize("card, never", [
    ("<table><tr><th>Statement date</th><th>Next bill date</th><th>Amount due</th></tr>"
     "<tr><td>09/12/2026</td><td>10/12/2026</td><td>$123.45</td></tr></table>", "2026-10-12"),
    ("<div style='display:grid;grid-template-columns:1fr 1fr'><span>Statement date</span>"
     "<span>Next statement</span><span>09/12/2026</span><span>10/12/2026</span></div>", "2026-10-12"),
    ("<table><tr><th>Bill date</th><th>Due date</th><th>Amount</th></tr>"
     "<tr><td>09/12/2026</td><td>10/01/2026</td><td>$123.45</td></tr></table>", "2026-10-01"),
    ("<table><tr><th>Next bill date</th><th>Amount</th></tr>"
     "<tr><td>10/12/2026</td><td>$123.45</td></tr></table>", "2026-10-12"),
], ids=["next bill date header", "next statement grid", "due date header", "next bill date alone"])
def test_a_card_whose_labels_sit_in_a_header_row_is_not_misdated(billing, card, never):
    """The words before the first value were the whole header row, so the
    first date read as the next statement's and the second was taken,
    September filed under October's own date."""
    html = ("<div data-cy='current-bill'>%s"
            "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>" % card)
    page = billing(_page(html + STATEMENT_ROW))
    assert never not in [d.date_text for d in site.collect_download_docs(page)]


def test_a_page_under_billing_is_not_billing(billing):
    """/billing/autopay was taken for Billing & Payments and read."""
    page = billing(_page(STATEMENT_ROW))
    page.context.route("%s/billing/autopay" % BASE, lambda r: r.fulfill(
        status=200, content_type="text/html", body=_page(STATEMENT_ROW)))
    page.goto("%s/billing/autopay" % BASE)
    assert site.goto_documents(page) is True
    assert page.url.endswith("/billing")


def test_a_close_glyph_is_pressed_and_a_title_that_refuses_is_not(billing):
    page = billing(_page(
        "<div role='dialog'><button class='close' aria-label='Close' onclick='window.__closed = true'>"
        "<span>&times;</span></button></div>"
        "<button aria-label='Close' title='Stop paper billing' onclick='window.__changed = true'>Close</button>"))
    site.dismiss_overlay(page)
    assert page.evaluate("window.__closed === true")
    assert page.evaluate("window.__changed") is False


# -- from the review of the sixth repair ---------------------------------------------------

@pytest.mark.parametrize("card", [
    "<span>Due date 10/01/2026</span><span>Next bill date 10/12/2026</span>"
    "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button>",
    "<span>Due date 10/01/2026</span><span>Next bill date 10/12/2026</span>"
    "<button onclick=\"openPdf('statement 09/12/2026')\">View</button>",
    "<span>Amount due</span><span>$123.45</span><span>Due date</span><span>10/01/2026</span>"
    "<span>Next bill date</span><span>10/12/2026</span>"
    "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button>",
], ids=["labels with values", "a bare View", "labels and values apart"])
def test_spans_that_touch_never_file_a_statement_under_the_next_ones_date(billing, card):
    """innerText ran them together, "10/01/2026Next bill date", where no
    word boundary falls, and September was filed under October's date."""
    page = billing(_page("<div data-cy='summary-card'>%s</div>" % card + STATEMENT_ROW))
    assert "2026-10-12" not in [d.date_text for d in site.collect_download_docs(page)]


def test_a_payment_word_run_into_a_number_still_leaves_the_row_alone(billing, tmp_path):
    """"Ref 4410Payment received" has no word boundary before Payment, and a
    payment's receipt above the statement took the statement's date."""
    row = ("<div data-cy='row'><span>Statement 09/12/2026</span> <span>Ref 4410</span>"
           "<span>Payment received</span> "
           "<button onclick=\"openPdf('payment receipt')\">View</button></div>")
    page = billing(_page(row + STATEMENT_ROW))
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is True
    assert b"statement 09/12/2026" in out.read_bytes()


def test_a_reference_number_does_not_make_a_statement_a_tax_document(billing):
    row = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span> <span>Ref 44109921</span> "
           "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    page = billing(_page(row))
    [doc] = site.collect_download_docs(page)
    assert doc.kind == "statement" and doc.title.startswith("Account Statement")


def test_words_run_together_inside_a_control_are_each_checked(billing, tmp_path):
    """"View statementPay now" gave "pay" no word boundary to be refused by."""
    row = ("<div data-cy='statement-row'><span>Statement date 09/12/2026</span> "
           "<button aria-label='View statement' onclick='window.__changed = true'>"
           "<span>View statement</span><span>Pay now</span></button></div>")
    page = billing(_page(row))
    assert site.collect_download_docs(page) == []
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert page.evaluate("window.__changed") is False


def test_a_date_the_page_hides_is_never_a_statements_date(billing, tmp_path):
    """A collapsed panel inside the current bill's card held another bill's
    date, read as the card's, and the September statement was saved as the
    August one above the real August row."""
    card = ("<div data-cy='current-bill'><span>Amount due $123.45</span> <span>Due 10/01/2026</span> "
            "<div style='visibility:hidden'>Bill date 08/12/2026</div>"
            "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    page = billing(_page(card + AUGUST_ROW))
    out = tmp_path / "Statements" / "2026-08-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-08-12", out) is True
    assert b"statement 08/12/2026" in out.read_bytes()


def test_a_date_written_in_pieces_is_read_whole(billing):
    """React writes {m}/{d}/{y} as five pieces of text, which read with
    spaces between as "09 / 12 / 2026", and the due date was taken."""
    row = ("<div data-cy='statement-row'><span>Statement date </span><span id='when'></span> "
           "<span>Due date 10/01/2026</span> "
           "<button onclick=\"openPdf('statement 09/12/2026')\">View bill</button></div>")
    script = "document.getElementById('when').append('09', '/', '12', '/', '2026');"
    page = billing(_page(row, script))
    assert [d.date_text for d in site.collect_download_docs(page)] == ["2026-09-12"]


# -- from the tester's recording on 0.41.0 --------------------------------------------------

def _marked_row(date: str, words: str, title: str = "View statement") -> str:
    """One row of the statements list the way his recording shows it, a row
    marked with a test id, and in it a link with no address marked
    statementPDF, holding an icon, a short word and another icon."""
    return ("<div data-cy='statementRow'><div><div><span>Statement date %s</span> <span>$123.45</span></div>"
            "<div><a class='link' data-cy='statementPDF' title='%s' onclick=\"openPdf('%s')\">"
            "<div style='display:inline-block;width:12px;height:12px'></div><span>PDF</span>"
            "<div style='display:inline-block;width:12px;height:12px'></div></a></div></div></div>"
            % (date, title, words))


def test_the_statement_link_his_recording_pressed_is_found(billing, tmp_path):
    """A link with no address has no link role, and "PDF" is not a
    statement's words, so discovery on his billing page found nothing."""
    page = billing(_page("<div data-cy='statements'>"
                         + _marked_row("09/12/2026", "statement 09/12/2026")
                         + _marked_row("08/12/2026", "statement 08/12/2026")
                         + _marked_row("07/12/2026", "statement 07/12/2026") + "</div>"))
    assert [d.date_text for d in site.collect_download_docs(page)] == [
        "2026-09-12", "2026-08-12", "2026-07-12"]
    out = tmp_path / "Statements" / "2026-08-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-08-12", out) is True
    assert b"statement 08/12/2026" in out.read_bytes()
    assert page.evaluate("window.__paid") is False


@pytest.mark.parametrize("title", ["Go paperless", "Enroll in paperless billing", "Set up autopay"])
def test_a_marked_link_whose_words_refuse_is_never_pressed(billing, tmp_path, title):
    page = billing(_page(_marked_row("09/12/2026", "statement 09/12/2026", title=title)))
    assert site.collect_download_docs(page) == []
    out = tmp_path / "Statements" / "2026-09-12 American Family Account Statement.pdf"
    assert site.download_bill(page, tmp_path / ".amfam-downloads", "2026-09-12", out) is False
    assert not out.exists()


def test_two_marked_links_in_one_row_are_left_alone(billing):
    """Which statement each one opens cannot be told."""
    row = ("<div data-cy='statementRow'><span>Statement date 09/12/2026</span> "
           "<a data-cy='statementPDF' title='View statement' onclick=\"openPdf('first')\"><span>PDF</span></a> "
           "<a data-cy='statementPDF' title='View statement' onclick=\"openPdf('second')\"><span>PDF</span></a>"
           "</div>")
    page = billing(_page(row))
    assert site.collect_download_docs(page) == []


def test_a_billing_page_with_nothing_to_take_writes_the_failure_file(monkeypatch):
    """His Pilot found nothing and finished with no file to send."""
    import amfam_docs
    app = object.__new__(amfam_docs.App)
    app.stats = {}
    written = []
    app.page = lambda: object()
    app.check_session = lambda page: None
    app.write_failure = lambda step, reason, *a, **k: written.append((step, reason))
    app.discovery = type("D", (), {"data": {}, "save": lambda self: None})()
    monkeypatch.setattr(amfam_docs.site, "goto_documents", lambda page: True)
    monkeypatch.setattr(amfam_docs.site, "collect_download_docs", lambda page: [])
    app.cmd_discover(quiet=True)
    assert written == [("find the statements", "the billing page showed no statement to take")]
