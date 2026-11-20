"""Exercise Starlink's invoice grid and PDF guard with invented data."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import starlink_site as site


FIRST = "INV-TEST-FIRST"
SECOND = "INV-TEST-SECOND"
THIRD = "INV-TEST-THIRD"
DATE = "2032-03-05"


def test_same_date_invoices_have_distinct_keys():
    result = site._parse_view({
        "range": "1 - 2", "previous": False, "next": False,
        "rows": [[FIRST, "03/05/2032"], [SECOND, "03/05/2032"]],
    })
    assert len({row.record.document_id for row in result.bills}) == 2
    assert all(row.record.date_text == DATE for row in result.bills)
    assert FIRST not in repr(result.bills[0].record)


@pytest.mark.parametrize("raw", [
    {"range": "1 - 2", "rows": [[FIRST, "03/05/2032"]], "previous": False, "next": False},
    {"range": "11 - 11", "rows": [[FIRST, "03/05/2032"]], "previous": False, "next": False},
    {"range": "1 - 1", "rows": [["../payment", "03/05/2032"]], "previous": False, "next": False},
    {"range": "1 - 1", "rows": [[FIRST, "unavailable"]], "previous": False, "next": False},
    {"range": "1 - 2", "rows": [[FIRST, "03/05/2032"]] * 2, "previous": False, "next": False},
])
def test_refuses_incomplete_or_ambiguous_rows(raw):
    with pytest.raises(site.ListStopped):
        site._parse_view(raw)


@pytest.mark.parametrize("number,date,accepted", [
    (FIRST, "Friday, March 5, 2032", True),
    (SECOND, "Friday, March 5, 2032", False),
    (FIRST, "Saturday, March 6, 2032", False),
])
def test_pdf_requires_labeled_number_and_date(monkeypatch, number, date, accepted):
    # The expected number and date in unrelated text must not suffice.
    pdf_text = f"Invoice\n{number}\nInvoice Date: {date}\nNotes: {FIRST} {DATE}"
    monkeypatch.setattr(site.pdf_reader, "page_texts", lambda *args, **kwargs: [pdf_text])
    assert site._pdf_matches(b"%PDF-", site.Bill(FIRST, DATE)) is accepted
    assert not site._pdf_matches(b"<html>Sign in</html>", site.Bill(FIRST, DATE))


def test_fetch_has_exact_invoice_path_and_disables_redirects(monkeypatch):
    response = SimpleNamespace(status=200, headers={"content-type": "application/pdf"},
                               body=lambda: b"%PDF-", dispose=lambda: None)

    def get(url, *, max_redirects, timeout):
        assert url == f"{site.BASE}/api/webagg/v1/public/invoice/{FIRST}/download"
        assert max_redirects == 0 and timeout > 0
        return response

    page = SimpleNamespace(url=site.DOCUMENTS_URL, request=SimpleNamespace(get=get))
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    assert site._fetch_pdf(page, site.Bill(FIRST, DATE)) == b"%PDF-"
    response.status = 404
    assert site._fetch_pdf(page, site.Bill(FIRST, DATE)) == b""
    page.url = "https://starlink.com.example.test/account/billing"
    with pytest.raises(site.ListStopped):
        site._fetch_pdf(page, site.Bill(FIRST, DATE))


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    html = """
    <section class="MuiDataGrid-root" id="invoices">
      <div role="grid">
        <div role="columnheader" data-field="payableEntityCreatedDate">Date</div>
        <div role="columnheader" data-field="payableEntityReferenceId">Invoice Number</div>
        <div id="rows"></div>
      </div>
      <div class="MuiTablePagination-root">
        <p class="MuiTablePagination-displayedRows"></p>
        <button type="button" aria-label="Go to previous page"></button>
        <button type="button" aria-label="Go to next page"></button>
      </div>
    </section>
    <section class="MuiDataGrid-root">
      <div role="grid">
        <div role="columnheader" data-field="paymentDate">Date</div>
        <div role="columnheader" data-field="appliedInvoices">Invoice Number</div>
      </div>
      <div class="MuiTablePagination-root">
        <p class="MuiTablePagination-displayedRows">1 - 10</p>
        <button type="button" aria-label="Go to next page" onclick="window.paymentClicked=true"></button>
      </div>
    </section>
    <button type="button" onclick="window.paymentClicked=true">Make a Payment</button>
    <script>
    const invoice = document.querySelector('#invoices');
    const previous = invoice.querySelector('[aria-label="Go to previous page"]');
    const next = invoice.querySelector('[aria-label="Go to next page"]');
    const pages = [["TEST_FIRST", "TEST_SECOND"], ["TEST_THIRD"]];
    const rows = invoice.querySelector('#rows');
    const range = invoice.querySelector('.MuiTablePagination-displayedRows');
    function render(index) {
      previous.disabled = index === 0;
      next.disabled = index === 1;
      range.textContent = index ? '3 - 3' : '1 - 2';
      rows.innerHTML = pages[index].map(value => `<div role="row" class="MuiDataGrid-row">
        <div role="gridcell" data-field="payableEntityReferenceId">${value}</div>
        <div role="gridcell" data-field="payableEntityCreatedDate">03/05/2032</div>
        <button type="button" aria-label="Download" onclick="window.downloadClicked=true"></button>
      </div>`).join('');
    }
    previous.onclick = () => render(0);
    next.onclick = () => render(1);
    window.renderInvoicePage = render;
    render(0);
    </script>
    """.replace("TEST_FIRST", FIRST).replace("TEST_SECOND", SECOND).replace("TEST_THIRD", THIRD)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html")
                      if route.request.url == site.DOCUMENTS_URL else route.abort())
            tab.goto(site.DOCUMENTS_URL)
            yield tab
        finally:
            browser.close()


def test_discovery_rewinds_and_reads_all_invoice_pages_only(page):
    page.evaluate("renderInvoicePage(1)")
    docs = site.collect_download_docs(page)
    assert [r.document_id for r in docs] == [site.Bill(number, DATE).key for number in (FIRST, SECOND, THIRD)]
    assert page.locator("#invoices .MuiTablePagination-displayedRows").inner_text() == "1 - 2"
    assert not page.evaluate("Boolean(window.paymentClicked || window.downloadClicked)")


def test_refuses_pdf_for_other_row_without_writing(page, monkeypatch, tmp_path):
    docs = site.collect_download_docs(page)
    path = tmp_path / "invoice.pdf"
    monkeypatch.setattr(site, "_fetch_pdf", lambda page, bill: b"%PDF-")
    monkeypatch.setattr(site.pdf_reader, "page_texts", lambda *args, **kwargs: [
        f"Invoice\n{FIRST}\nInvoice Date: Friday, March 5, 2032"
    ])
    assert not site.download_bill(page, DATE, path, document_id=docs[1].document_id)
    assert not path.exists()
    assert site.download_bill(page, DATE, path, document_id=docs[0].document_id)
    assert path.read_bytes() == b"%PDF-"


def test_refuses_invoice_pager_with_conflicting_label(page):
    pager = page.locator('#invoices [aria-label="Go to next page"]')
    pager.evaluate("el => el.title = 'Make a Payment'")
    with pytest.raises(site.ListStopped, match="pager changed"):
        site.collect_download_docs(page)
    assert page.locator("#invoices .MuiTablePagination-displayedRows").inner_text() == "1 - 2"


def test_refuses_pager_that_jumps_over_invoices(page):
    page.locator('#invoices [aria-label="Go to next page"]').evaluate("""el => {
        el.onclick = () => {
            renderInvoicePage(1);
            document.querySelector('#invoices .MuiTablePagination-displayedRows').textContent = '4 - 4';
        };
    }""")
    with pytest.raises(site.ListStopped, match="skipped or changed pages"):
        site.collect_download_docs(page)


@pytest.mark.parametrize("status,mime", [(401, ""), (403, ""), (302, "text/html"), (200, "text/html")])
def test_refused_pdf_refreshes_the_list_and_leaves_only_that_invoice_pending(page, monkeypatch, tmp_path, status, mime):
    first = site.collect_download_docs(page)[0]
    path = tmp_path / "invoice.pdf"
    refreshed = []
    read = site._refresh_invoices
    response = SimpleNamespace(status=status, headers={"content-type": mime}, dispose=lambda: None)
    monkeypatch.setattr(type(page.request), "get", lambda self, url, **options: response)

    def refresh(page):
        refreshed.append(True)
        return read(page)

    monkeypatch.setattr(site, "_refresh_invoices", refresh)
    assert not site.download_bill(page, DATE, path, document_id=first.document_id)
    assert refreshed == [True]
    assert not path.exists()


@pytest.mark.parametrize("read_error", [site.SessionExpired, site.ListStopped])
def test_refused_pdf_propagates_an_unreadable_or_signed_out_history(page, monkeypatch, tmp_path, read_error):
    first = site.collect_download_docs(page)[0]
    path = tmp_path / "invoice.pdf"
    response = SimpleNamespace(status=302, headers={}, dispose=lambda: None)
    monkeypatch.setattr(type(page.request), "get", lambda self, url, **options: response)

    def unread(page):
        raise read_error()

    monkeypatch.setattr(site, "_refresh_invoices", unread)
    with pytest.raises(read_error):
        site.download_bill(page, DATE, path, document_id=first.document_id)
    assert not path.exists()
