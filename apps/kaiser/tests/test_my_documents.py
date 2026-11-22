from base64 import b64encode
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_site as site


LIST = "/northern-california/secure/my-documents-myc"
VIEWER = LIST + "/viewer"


def document(title):
    buffer = BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=612, height=792)
    pdf.add_metadata({"/Title": title})
    pdf.write(buffer)
    return buffer.getvalue()


FIRST = document("Synthetic notice one")
SECOND = document("Synthetic notice two")


def feed():
    premium = """<div class="_datafeed_row">
        <a id="getdoc_10" class="_document_name" href="#">Premium Bills</a>
        <span class="_document_date">Apr 6, 2031</span></div>"""
    rows = []
    for key in (20, 21):
        rows.append(f"""<div class="_datafeed_row">
            <a id="getdoc_{key}" class="_document_name" href="#">Membership Notice</a>
            <span class="_document_date">Apr 6, 2031</span>
            <a class="download-pdf-link" href="#" data-docid="{key}">Download PDF</a>
            <a href="#appointment">Make an appointment</a>
        </div>""")
    payload = json.dumps({20: b64encode(FIRST).decode(), 21: b64encode(SECOND).decode()})
    return premium + "".join(rows) + """
    <script>
      const pdfs = PAYLOAD;
      document.querySelector('#getdoc_10').addEventListener('click', event => {
          event.preventDefault();
          location.href = 'my-documents-myc/viewer?item=synthetic';
      });
      document.querySelectorAll('.download-pdf-link').forEach(link => {
          link.addEventListener('click', event => {
              event.preventDefault();
              const original = Uint8Array.from(atob(pdfs[link.dataset.docid]), c => c.charCodeAt(0));
              const url = URL.createObjectURL(new Blob([original], {type:'application/pdf'}));
              const anchor = document.createElement('a');
              anchor.href = url;
              anchor.download = 'synthetic fixture.pdf';
              anchor.click();
          });
      });
      document.querySelectorAll('a[href="#appointment"]').forEach(link =>
          link.addEventListener('click', () => { window.unexpectedAction = true; }));
    </script>""".replace("PAYLOAD", payload)


@pytest.fixture
def page():
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is unavailable")
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            def serve(route):
                u = urlsplit(route.request.url)
                if u.netloc != site.HOST:
                    route.abort()
                    return
                if u.path == site._WRAPPER_PATH:
                    html = f'<iframe src="{LIST}" style="width:850px;height:450px"></iframe>'
                elif u.path == LIST:
                    html = feed()
                elif u.path == VIEWER:
                    html = '<main><div id="documentcontent">Premium bill. Statement Date: 3/31/2031. Synthetic premium.</div></main>'
                else:
                    html = '<main><h2>Statements &amp; Billing</h2></main>'
                route.fulfill(content_type="text/html", body=html)
            context.route("**/*", serve)
            yield page
        finally:
            browser.close()


def test_archive_preserves_premium_id_and_saves_both_same_day_notices(page, tmp_path):
    from hashlib import sha256
    page.goto(site.URLS["login"])
    listed = site.collect_download_docs(page)
    assert len(listed) == 3
    premium = listed[0]
    old_fingerprint = sha256(b"Premium bill. Statement Date: 3/31/2031. Synthetic premium.").hexdigest()
    assert premium.document_id == sha256(f"kaiser:getdoc_10:{old_fingerprint}".encode()).hexdigest()
    assert premium.date_text == "2031-03-31"
    assert listed[1].document_id != listed[2].document_id
    assert listed[1].date_text == listed[2].date_text
    for index, data in enumerate((FIRST, SECOND), start=1):
        output = tmp_path / f"notice-{index}.pdf"
        assert site.download_bill(page, listed[index], output)
        assert output.read_bytes() == data
    existing = tmp_path / "previously archived.pdf"
    existing.write_bytes(FIRST)
    duplicate = tmp_path / "duplicate.pdf"
    assert site.download_bill(page, listed[1], duplicate,
                              existing_pdfs={sha256(FIRST).hexdigest(): existing}) == existing
    assert existing.read_bytes() == FIRST
    assert not duplicate.exists()
    frame = site._history_frame(page)
    assert not frame.evaluate("Boolean(window.unexpectedAction)")


def test_changed_pdf_row_refuses_to_mark_list_complete(page):
    page.goto(site.URLS["login"])
    frame = site._history_frame(page)
    frame.locator('a[data-docid="21"]').evaluate("e => e.setAttribute('data-docid', '20')")
    with pytest.raises(site.ListStopped, match="unrecognized document action"):
        site.collect_download_docs(page)


def test_native_blob_archives_without_a_download_event_or_leftover_copy(page, tmp_path, monkeypatch):
    page.goto(site.URLS["login"])
    rows = site.collect_download_docs(page)
    on = page.on
    remove_listener = page.remove_listener
    monkeypatch.setattr(page, "on", lambda event, handler: on(event, handler) if event != "download" else None)
    monkeypatch.setattr(page, "remove_listener",
                        lambda event, handler: remove_listener(event, handler) if event != "download" else None)
    archived = tmp_path / "notice.pdf"
    assert site.download_bill(page, rows[1], archived) == archived
    assert archived.read_bytes() == FIRST
    assert list(tmp_path.iterdir()) == [archived]


def test_payment_history_is_outside_discovery(page):
    page.goto(site.BASE + "/secure/coverage-costs/payment-history")
    assert not site.is_history_tab(page)
    with pytest.raises(site.ListStopped, match="My Documents"):
        site.collect_download_docs(page)


def test_scope_includes_notices_and_excludes_records_from_other_pages():
    from types import SimpleNamespace
    import kaiser_docs as docs

    app = docs.App.__new__(docs.App)
    app.args = SimpleNamespace(type="", year=None, start_date="", end_date="", max_docs=None)
    app.config = json.loads((Path(__file__).resolve().parents[1] / "config.example.json").read_text())
    app.stats = {}
    app._current_bill_ids = {"notice-id"}
    notice = docs.Document(title="Synthetic notice", category=docs.doc_types.OTHER,
                           date="2031-04-06", source_url=site.DOCUMENTS_URL, document_id="notice-id")
    medical = docs.Document(title="Medical Bill", category=docs.doc_types.STATEMENT, date="2031-04-06",
                            source_url=site.medical.SOURCE_URL, document_id="medical-id")
    app.discovery = SimpleNamespace(data={item.key: item.to_dict() for item in (notice, medical)})
    assert [d.document_id for d in app._select()] == ["notice-id"]
    assert len(app.discovery.data) == 2
