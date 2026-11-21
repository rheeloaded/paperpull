from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_site as site

LIST_PATH = "/northern-california/secure/my-documents-myc"
DETAILS = LIST_PATH + "/viewer"
ROWS = """
<div class="_datafeed_row">
  <a id="getdoc_1" class="_document_name" href="#">Premium Bills</a>
  <span class="_document_date">Apr 6, 2031</span>
</div>
<div class="_datafeed_row">
  <a id="getdoc_2" class="_document_name" href="#">Premium Bills</a>
  <span class="_document_date">Apr 6, 2031</span>
</div>
<a href="#payment">Pay Now</a>
<script>
  for (const id of [1, 2]) {
    document.querySelector('#getdoc_' + id).addEventListener('click', event => {
      event.preventDefault();
      location.href = 'my-documents-myc/viewer?synthetic=' + id;
    });
  }
</script>
"""


def test_premium_bills_bind_the_distinct_rows_and_use_printed_date(tmp_path):
    opened = []
    return_different_bill = set()

    def serve(route):
        url = urlsplit(route.request.url)
        if url.path == site._WRAPPER_PATH:
            html = f'<iframe src="{LIST_PATH}" style="width:800px;height:400px"></iframe>'
        elif url.path == LIST_PATH:
            html = ROWS
        elif url.path == DETAILS:
            opened.append(url.query)
            n = int(url.query[-1])
            label = "Updated" if n in return_different_bill else "Original"
            html = f"<main><div id='documentcontent'>Premium bill. Statement Date: 3/{n}/2031. {label} synthetic statement.</div></main>"
        else:
            route.abort()
            return
        route.fulfill(content_type="text/html", body=html)

    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is unavailable")
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(site.BASE + site._WRAPPER_PATH)
            bills = site.collect_download_docs(page)
            assert len(bills) == 2
            assert len({bill.document_id for bill in bills}) == 2
            assert {bill.date_text for bill in bills} == {"2031-03-01", "2031-03-02"}
            result = tmp_path / "premium.pdf"
            assert site.download_bill(page, bills[0], result)
            assert result.read_bytes().startswith(b"%PDF-")
            return_different_bill.add(2)
            unexpected = tmp_path / "other.pdf"
            assert not site.download_bill(page, bills[1], unexpected)
            assert not unexpected.exists()
            assert opened == ["synthetic=1", "synthetic=2", "synthetic=1", "synthetic=2"]
        finally:
            browser.close()
