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


@pytest.mark.parametrize("number,billing_date,issue_date,accepted", [
    (FIRST, DATE, "Friday, March 5, 2032", True),
    (FIRST, DATE, "Saturday, March 6, 2032", True),
    (FIRST, "2031-12-31", "Thursday, January 1, 2032", True),
    (SECOND, DATE, "Friday, March 5, 2032", False),
    (SECOND, DATE, "Saturday, March 6, 2032", False),
    (FIRST, DATE, "Thursday, March 4, 2032", False),
    (FIRST, DATE, "Sunday, March 7, 2032", False),
    (FIRST, DATE, "Unavailable", False),
])
def test_pdf_requires_labeled_number_and_date(monkeypatch, number, billing_date, issue_date, accepted):
    # The expected number and date in unrelated text must not suffice.
    pdf_text = f"Invoice\n{number}\nInvoice Date: {issue_date}\nNotes: {FIRST} {billing_date}"
    monkeypatch.setattr(site.pdf_reader, "page_texts", lambda *args, **kwargs: [pdf_text])
    bill = site.Bill(FIRST, billing_date)
    assert site._pdf_matches(b"%PDF-", bill) is accepted
    assert not site._pdf_matches(b"<html>Sign in</html>", bill)


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


class _Fields:
    def __init__(self, count=0, broken=False):
        self._count, self._broken = count, broken
        self.selectors = []

    def locator(self, selector):
        self.selectors.append(selector)
        return self

    def count(self):
        if self._broken:
            from playwright.sync_api import Error
            raise Error("page went away")
        return self._count


@pytest.mark.parametrize("fields,signed_out", [
    (_Fields(0), False), (_Fields(1), True), (_Fields(broken=True), True),
])
def test_signed_out_counts_every_password_field(fields, signed_out):
    fields.url = site.DOCUMENTS_URL
    assert site.looks_signed_out(fields) is signed_out
    # Hidden fields count too, so the selector asks for no drawn state.
    assert fields.selectors == ['input[type="password"]']


def test_a_hidden_password_field_on_billing_reads_as_signed_out(page):
    assert not site.looks_signed_out(page)
    page.evaluate("""() => {
        const field = document.createElement('input');
        field.type = 'password';
        field.style.display = 'none';
        document.body.appendChild(field);
    }""")
    assert site.looks_signed_out(page)
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)


def test_refuses_pager_that_shows_the_same_page_again(page):
    page.locator('#invoices [aria-label="Go to next page"]').evaluate(
        "el => { el.onclick = () => renderInvoicePage(0); }")
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


@pytest.mark.parametrize("empty,whole", [(True, True), (False, False), (None, False)])
def test_an_empty_table_needs_the_grids_own_no_rows_overlay(empty, whole):
    raw = {"range": "0 - 0 of 0", "rows": [], "previous": False, "next": False}
    if empty is not None:
        raw["empty"] = empty
    if whole:
        assert site._parse_view(raw).bills == ()
    else:
        with pytest.raises(site.ListStopped):
            site._parse_view(raw)


def _empty_table(page, overlay):
    page.evaluate("""overlay => {
        const invoice = document.querySelector('#invoices');
        invoice.querySelector('#rows').innerHTML = overlay
            ? '<div class="MuiDataGrid-overlay">No rows</div>' : '';
        invoice.querySelector('.MuiTablePagination-displayedRows').textContent = '0 - 0 of 0';
        for (const button of invoice.querySelectorAll('.MuiTablePagination-root button')) {
            button.disabled = true;
        }
    }""", overlay)


def test_an_empty_footer_without_the_overlay_is_not_an_empty_history(page):
    _empty_table(page, overlay=False)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_an_empty_table_the_grid_says_is_empty_lists_nothing(page):
    _empty_table(page, overlay=True)
    assert site.collect_download_docs(page) == []


def test_a_loading_overlay_on_an_empty_footer_is_not_an_empty_history(page):
    _empty_table(page, overlay=True)
    page.evaluate("""() => document.querySelector('#invoices .MuiDataGrid-overlay')
        .innerHTML = '<span role="progressbar"></span>'""")
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


# -- review repairs, findings 3 and 4 -----------------------------------------

import json  # noqa: E402

import starlink_docs as app_mod  # noqa: E402


def _app(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic Owner", "output_dir": str(tmp_path), "min_pdf_bytes": 100,
    }), encoding="utf-8")
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    return app


def _download_first(tmp_path, monkeypatch, page, data, text):
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    monkeypatch.setattr(site, "_fetch_pdf", lambda _page, _bill: data)
    monkeypatch.setattr(site.pdf_reader, "page_texts", lambda *a, **k: [text])
    doc = next(d for d in app._select() if d.document_id == site.Bill(FIRST, DATE).key)
    app.download_one(page, doc, "invoice.pdf")
    return app, app.progress.get(doc.key)


def test_a_pdf_of_another_invoice_is_counted_as_a_wrong_document(page, tmp_path, monkeypatch):
    app, rec = _download_first(tmp_path, monkeypatch, page, b"%PDF-1.7 synthetic",
                               f"Invoice\n{SECOND}\nInvoice Date: Friday, March 5, 2032")
    assert app.stats.get("wrong_document") == 1 and app.stats["failed"] == 1
    assert "did not show this invoice" in rec["notes"], rec["notes"]
    assert site.last_refusal() == "wrong"


def test_a_refused_pdf_is_said_as_refused_not_wrong(page, tmp_path, monkeypatch):
    app, rec = _download_first(tmp_path, monkeypatch, page, b"", "")
    assert not app.stats.get("wrong_document") and app.stats["failed"] == 1
    assert "refused" in rec["notes"], rec["notes"]


def test_an_unreadable_pdf_is_said_as_unreadable_not_wrong(page, tmp_path, monkeypatch):
    app, rec = _download_first(tmp_path, monkeypatch, page, b"<html>not a pdf</html>", "")
    assert not app.stats.get("wrong_document")
    assert "could not be read" in rec["notes"], rec["notes"]


class _Tab:
    """A Starlink tab of the person's, on some page, never closed."""

    def __init__(self, url):
        self.url = url
        self.moved = []

    def is_closed(self):
        return False

    def goto(self, url, **_options):
        self.moved.append(url)


def test_a_starlink_tab_off_billing_is_told_to_open_billing_not_moved(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    tab = _Tab(site.BASE + "/account/support")
    monkeypatch.setattr(app, "page", lambda: tab)
    with pytest.raises(SystemExit):
        app._on_its_site()
    said = capsys.readouterr().out
    assert "not on Billing" in said and "not open" not in said, said
    assert tab.moved == []


def test_a_starlink_tab_on_billing_is_used_as_before(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    tab = _Tab(site.DOCUMENTS_URL)
    monkeypatch.setattr(app, "page", lambda: tab)
    assert app._on_its_site() is tab
