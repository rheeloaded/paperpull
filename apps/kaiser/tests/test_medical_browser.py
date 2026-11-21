from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
import sys

import pytest
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_medical as medical
import kaiser_site as site


def pdf_with_statement_date(day):
    writer = PdfWriter()
    sheet = writer.add_blank_page(width=612, height=792)
    n = NameObject
    sheet[n("/Resources")] = DictionaryObject({
        n("/Font"): DictionaryObject({n("/F1"): DictionaryObject({
            n("/Type"): n("/Font"), n("/Subtype"): n("/Type1"), n("/BaseFont"): n("/Helvetica")
        })})
    })
    contents = DecodedStreamObject()
    contents.set_data(f"BT /F1 12 Tf 60 700 Td (Account statement. Statement Date: 4/{day}/2031) Tj ET".encode())
    sheet[n("/Contents")] = contents
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


DETAILS = medical.DETAILS_PATH
HTML = b"""<!doctype html><main>
<div><div><div><h2>Statements &amp; Billing</h2></div></div>
<ul>
<li><span class="ba_details_statement_date">April 1, 2031 Apr 1, 2031</span><span>Account statement</span>
<a data-index="1" aria-label="View the statement sent on April 1, 2031 (PDF)." href="#view" onclick="openStatement(1);return false">View statement (PDF)</a></li>
<li><span class="ba_details_statement_date">April 2, 2031 Apr 2, 2031</span><span>Account statement</span>
<a data-index="2" href="#view" onclick="openStatement(2);return false">View statement (PDF)</a></li>
</ul></div></main>
<div class="Popup" id="viewer" role="dialog" style="position:fixed;inset:0;background:white" hidden>
<h2>Statement</h2><button type="button" aria-label="Close this popup" style="position:absolute;top:4px;right:4px;z-index:2" onclick="closeStatement()">Close</button>
<iframe style="position:absolute;top:40px;left:0;width:100%;height:100%"></iframe></div>
<script>
const viewer = document.querySelector('#viewer');
function openStatement(i) { viewer.hidden=false; viewer.querySelector('iframe').src='Details/DownloadStatement/?doc='+i }
function closeStatement() { viewer.hidden=true; viewer.querySelector('iframe').src='about:blank' }
</script>"""
DOC = pdf_with_statement_date(1)
GETS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        req = urlsplit(self.path)
        GETS.append(req.path)
        if req.path == DETAILS:
            response_type, data = "text/html", HTML
        elif req.path == DETAILS + "/DownloadStatement/":
            self.send_response(302)
            self.send_header("Location", DETAILS + "/DownloadStatementBytes/?" + req.query)
            self.end_headers()
            return
        elif req.path == DETAILS + "/DownloadStatementBytes/":
            response_type, data = "application/pdf", DOC
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", response_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_discover_and_save_an_original_medical_pdf(monkeypatch, tmp_path):
    GETS.clear()
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            _exercise_medical_browser(monkeypatch, tmp_path, server.server_port)
        finally:
            server.shutdown()
            worker.join()


def _exercise_medical_browser(monkeypatch, tmp_path, port):
    monkeypatch.setattr(medical, "BASE", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(medical, "is_details_url",
                        lambda url: url.startswith(medical.BASE + DETAILS + "?"))
    monkeypatch.setattr(medical, "_medical_download_url", lambda url: (
        url.startswith(medical.BASE + "/") and medical._VIEWER_DOWNLOAD.fullmatch(urlsplit(url).path)
    ))
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is unavailable")
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(medical.BASE + DETAILS + "?id=synthetic-account")
            bills = medical.collect_download_docs(page)
            assert len(bills) == 2
            assert not any("/Download" in path for path in GETS)
            good, refused = sorted(bills, key=lambda b: b.date_text)
            output = tmp_path / "correct.pdf"
            assert medical.download_bill(page, good, output, press=site.press_named)
            assert output.read_bytes() == DOC
            assert not page.locator(medical._DIALOG).count()
            unexpected = tmp_path / "wrong.pdf"
            assert not medical.download_bill(page, refused, unexpected, press=site.press_named)
            assert not unexpected.exists()
            assert not page.locator(medical._DIALOG).count()
            calls = len(GETS)
            page.evaluate("""() => {
                const overlay = document.createElement('div');
                overlay.style = 'position:fixed;inset:0;z-index:999;background:white';
                document.body.append(overlay);
            }""")
            with pytest.raises(site.pressing.Covered) as stop:
                medical.download_bill(page, good, tmp_path / "covered.pdf", press=site.press_named)
            assert not stop.value.after_a_press
            assert len(GETS) == calls
            page.locator('a[data-index="2"]').evaluate("link => link.textContent = 'Unknown action'")
            with pytest.raises(medical.MedicalListError):
                medical.collect_download_docs(page)
        finally:
            browser.close()
