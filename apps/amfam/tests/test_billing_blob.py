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


def test_the_payment_button_on_the_billing_page_is_never_a_document():
    for words in ("Make a payment", "Pay bill", "Pay now", "Set up autopay", "Bill pay"):
        assert not site.BILL_CONTROL_RE.search(words) or not site.is_safe_control(words), words
    for words in ("View bill", "Billing statement", "Declarations page", "View ID card"):
        assert site.BILL_CONTROL_RE.search(words) and site.is_safe_control(words), words


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
