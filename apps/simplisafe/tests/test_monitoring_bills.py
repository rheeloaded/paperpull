"""SimpliSafe monitoring history and invoice tests with invented data."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simplisafe_site as site


FIRST = "0" * 31 + "1"
SECOND = "0" * 31 + "2"
DATE = "2032-03-05"
HISTORY_URL = f"https://{site.API_HOST}/v1/users/123/paymentHistory?numInvoices=7&fromInvoice=0"
MAIN_FRAME = object()


def view(*ids):
    return {"range": "1 – 1 of 2", "rows": [{"id": key,"date":"03/05/32"} for key in ids]}


@pytest.mark.parametrize("address", [
    HISTORY_URL.replace("api.simplisafe.com", "api.simplisafe.com.example"),
    HISTORY_URL.replace("/paymentHistory", "/paymentMethods"),
    HISTORY_URL.replace("https:", "http:"),
    HISTORY_URL.replace("fromInvoice=0", "fromInvoice=1"),
    HISTORY_URL + "&numInvoices=1",
    HISTORY_URL + "&extra=anything",
    HISTORY_URL + "#fragment",
])
def test_only_the_original_monitoring_request_can_be_widened(address):
    assert site._history_request(address) is None
    assert site._history_request(HISTORY_URL)


@pytest.mark.parametrize("response_ids,total", [([FIRST],2), ([FIRST,FIRST],2), ([FIRST,SECOND],3)])
def test_history_must_match_the_count_and_contain_unique_invoices(response_ids,total):
    payload = {"totalNumInvoices": total, "invoices": [{"invoiceId": key} for key in response_ids]}
    with pytest.raises(site.ListStopped):
        site._reply_ids(payload, 2)


def test_row_dates_and_same_day_invoice_ids_remain_distinct():
    count, bills = site._parse_view(view(FIRST, SECOND))
    assert count == len(bills) == 2
    assert {bill.record.date_text for bill in bills.values()} == {DATE}
    assert FIRST not in repr([bill.record for bill in bills.values()])
    with pytest.raises(site.ListStopped):
        site._parse_view(view(FIRST, FIRST))


@pytest.mark.parametrize("rendered_ids", [(FIRST,SECOND),(FIRST,"f"*32)])
def test_full_history_replays_only_the_same_get_and_checks_rendered_rows(monkeypatch, rendered_ids):
    handled = []

    class Route:
        request = SimpleNamespace(method="GET", url=HISTORY_URL, frame=MAIN_FRAME, resource_type="xhr")

        def fetch(self, url, *, max_redirects, timeout):
            assert urlsplit(url).path == urlsplit(HISTORY_URL).path
            assert urlsplit(url).netloc == site.API_HOST
            assert parse_qs(urlsplit(url).query) == {"numInvoices": ["2"], "fromInvoice": ["0"]}
            assert max_redirects == 0 and timeout > 0
            data = {"totalNumInvoices": 2, "invoices": [{"invoiceId": FIRST},{"invoiceId": SECOND}]}
            return SimpleNamespace(status=200, headers={"content-type":"application/json"},
                                   text=lambda: json.dumps(data), body=lambda: json.dumps(data).encode(),
                                   dispose=lambda: handled.append("disposed"))

        def fulfill(self, *, response):
            handled.append("delivered")

    class Page:
        main_frame = MAIN_FRAME

        def route(self, pattern, action):
            assert pattern.fullmatch(HISTORY_URL)
            self.action = action

        def reload(self, **options):
            self.action(Route())

        def unroute(self, pattern, action):
            assert action == self.action
            handled.append("unregistered")

        def wait_for_function(self, _function, *, arg, timeout):
            assert arg == 2 and timeout > 0

    page = Page()
    monkeypatch.setattr(site, "_view", lambda seen: site._parse_view(view(*rendered_ids)))
    if rendered_ids == (FIRST,SECOND):
        assert len(site._load_full_history(page, 2)) == 2
    else:
        with pytest.raises(site.ListStopped,match="do not match"):
            site._load_full_history(page, 2)
    assert handled == ["delivered","disposed","unregistered"]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    html = """
    <ss-monitoring-payments>
      <table><thead><tr><th>Date</th><th>Invoice</th></tr></thead><tbody>
          <tr><td>03/05/32</td><td><a>ROW_A</a></td></tr>
          <tr><td>03/05/32</td><td><a>ROW_B</a></td></tr>
      </tbody></table>
      <table hidden><thead><tr><th>Invoice Summary</th></tr></thead></table>
      <div class="mat-mdc-paginator-range-label">1 – 2 of 2</div>
    </ss-monitoring-payments>
    <button id="incidental">Pay balance</button>
    <script>
    for (const link of document.querySelectorAll('a')) {
       link.onclick = () => {
          const dialog = document.createElement('mat-dialog-container');
          const id = window.forceInvoice || link.textContent;
          const date = window.forceDate || '03/05/2032';
          dialog.innerHTML = '<ss-payment-details-display><div class="invoice-container">'
            + '<h2>Invoice: SS' + id + '</h2><h3>Date:</h3><p>' + date + '</p>'
            + '<table><thead><tr><th>Description</th><th>Total</th></tr></thead>'
            + '<tbody><tr><td>Example monitoring</td><td>$1.00</td></tr></tbody></table></div>'
            + '</ss-payment-details-display><button class="close" type="button">Close</button>';
          dialog.querySelector('button').onclick = () => dialog.remove();
          document.body.append(dialog);
       };
    }
    </script>
    """.replace("ROW_A", FIRST).replace("ROW_B", SECOND)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8")
                      if route.request.url == site.BASE+"/" else route.abort())
            tab.goto(site.DOCUMENTS_URL)
            yield tab
        finally:
            browser.close()


def test_both_visible_bills_render_and_match(page, tmp_path):
    records = site.collect_download_docs(page)
    assert len(records) == 2
    for index, doc in enumerate(records):
        path = tmp_path/f"{index}.pdf"
        assert site.download_bill(page, doc.date_text, path, document_id=doc.document_id)
        assert path.read_bytes().startswith(b"%PDF-")
        assert not page.locator(site._DIALOG).count()


@pytest.mark.parametrize("wrong_value", [
    ("forceInvoice", SECOND), ("forceDate", "03/06/2032"), ("forceDate", "Unavailable"),
])
def test_wrong_view_is_closed_and_never_saved(page, tmp_path, wrong_value):
    first = site.collect_download_docs(page)[0]
    page.evaluate("([name,value]) => window[name]=value", list(wrong_value))
    path = tmp_path/"bill.pdf"
    assert not site.download_bill(page, first.date_text, path, document_id=first.document_id)
    assert not path.exists()
    assert not page.locator(site._DIALOG).count()


def test_rejects_invoice_control_that_navigates_to_another_host(page, tmp_path):
    first = site.collect_download_docs(page)[0]
    page.locator("ss-monitoring-payments a").first.evaluate("el=>el.href='https://example.test/'")
    with pytest.raises(site.ListStopped,match="view control"):
        site.download_bill(page, first.date_text, tmp_path/"bill.pdf", document_id=first.document_id)
    assert not page.locator(site._DIALOG).count()


def test_discovery_leaves_an_existing_account_dialog_open(page):
    page.evaluate("""() => {
        const dialog = document.createElement('mat-dialog-container');
        dialog.textContent = 'Example account dialog';
        document.body.append(dialog);
    }""")
    with pytest.raises(site.ListStopped, match="Close the open SimpliSafe dialog"):
        site.collect_download_docs(page)
    assert page.locator(site._DIALOG).count() == 1
