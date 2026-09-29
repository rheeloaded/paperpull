"""Vanguard's download, in a real browser and against a local server.

Measured 2026-09-29, by two sessions, on Chromium 149 to 153 and Edge 154
with Playwright 1.63. Once the browser's download folder is set over
DevTools, Playwright's download event still fires, but its own copy never
exists and save_as writes an EMPTY file. The browser's file in that folder
is the only copy. The review fix merged for #57 took the empty file, found
no PDF, then deleted the browser's file, so every statement failed and
nothing was left, and its tests passed because their fake save_as copied
the browser's bytes. The contributor's own version pointed the folder at
the archive and left an empty file there, his "five ghost files".

So these drive a browser. A persistent context is one where setting the
folder takes effect, as it does in the Edge or Chrome a person signs in
to. A context of Playwright's own making is one where it has no effect,
the other world a statement has to be saved in. Everything here is made
up and nothing leaves this machine."""
import http.server
import socketserver
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vanguard_site as site

PDF = b"%PDF-1.4\n% invented statement 2026-08-31\n" + b"0" * 250000 + b"\n%%EOF\n"
NAME = "2026-08 VG Statement Cash Plus Account x4567.pdf"
TITLE = "Account Statement - Example Holder — Cash Plus Account — 1234567"
LABEL = ("Download a pdf statement generated on August 31, 2026 with "
         "description Example Holder — Cash Plus Account — 1234567")
PAGE = ("<!doctype html><html><head><meta charset='utf-8'></head><body><table>"
        "<tr><th>Account</th><th>Date</th><th></th></tr>"
        "<tr><td>Example Holder — Cash Plus Account — 1234567</td><td>08/31/2026</td>"
        "<td><a title='Pdf download icon' aria-label='%s' href='/doc'>pdf</a></td></tr>"
        "</table></body></html>" % LABEL).encode("utf-8")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/doc"):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % NAME)
            self.send_header("Content-Length", str(len(PDF)))
            self.end_headers()
            self.wfile.write(PDF)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/" % srv.server_address[1]
    srv.shutdown()


@pytest.fixture()
def browser_page(tmp_path, server, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    opened = []

    def start(folder_takes_effect: bool):
        try:
            if folder_takes_effect:
                ctx = driver.chromium.launch_persistent_context(
                    str(tmp_path / "profile"), headless=True, accept_downloads=True)
                opened.append(ctx)
                pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                browser = driver.chromium.launch(headless=True)
                opened.append(browser)
                pg = browser.new_context(accept_downloads=True).new_page()
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        pg.goto(server)
        return pg

    # The page is on this machine, not statements.web.vanguard.com.
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    yield start
    for thing in opened:
        try:
            thing.close()
        except Exception:
            pass
    driver.stop()


def _download(page, tmp_path, dl_dir=True):
    archive = tmp_path / "Statements"
    staging = tmp_path / ".vanguard-downloads"
    out = archive / "2026-08-31 Vanguard Account Statement - Cash Plus Account.pdf"
    got = site.download_document(page, account_id="123400000000001", charitable=False,
                                 doc_type="Statement", title=TITLE, date="2026-08-31",
                                 out_path=out, dl_dir=staging if dl_dir else None)
    return got, archive, staging, out


def _listing(folder: Path):
    return sorted((p.name, p.stat().st_size) for p in folder.iterdir()) if folder.exists() else []


@pytest.mark.parametrize("folder_takes_effect", [True, False],
                         ids=["the folder takes effect", "the folder has no effect"])
def test_a_statement_is_saved_whole(browser_page, tmp_path, caplog, folder_takes_effect):
    page = browser_page(folder_takes_effect)
    with caplog.at_level("INFO", logger=site.log.name):
        got, archive, staging, out = _download(page, tmp_path)
    assert got is True
    # each world took the way it is meant to, or the test proves nothing
    way = "the browser's own file" if folder_takes_effect else "the download event"
    assert any(("captured via " + way) in r.getMessage() for r in caplog.records), caplog.text
    assert out.read_bytes() == PDF
    assert _listing(archive) == [(out.name, len(PDF))], "one file, whole, under the app's name"
    assert _listing(staging) == [], "the browser's file was moved, not copied"


def test_nothing_else_in_the_folder_is_touched(browser_page, tmp_path):
    """A download started in another tab of that browser lands in the same
    folder, and is the person's own."""
    staging = tmp_path / ".vanguard-downloads"
    staging.mkdir()
    theirs = b"%PDF-1.4\n% somebody else's download\n" + b"1" * 5000
    (staging / "their own download.pdf").write_bytes(theirs)
    page = browser_page(True)
    got, archive, staging, out = _download(page, tmp_path)
    assert got is True and out.read_bytes() == PDF
    assert (staging / "their own download.pdf").read_bytes() == theirs
    assert _listing(staging) == [("their own download.pdf", len(theirs))]


def test_a_leftover_under_the_same_name_is_not_taken_for_the_new_file(browser_page, tmp_path):
    """The browser writes a download over a file of the same name in place,
    so a folder compared by names alone never sees it arrive."""
    staging = tmp_path / ".vanguard-downloads"
    staging.mkdir()
    old = b"%PDF-1.4\n% an older try\n" + b"2" * 1000
    (staging / NAME).write_bytes(old)
    page = browser_page(True)
    got, archive, staging, out = _download(page, tmp_path)
    assert got is True
    assert out.read_bytes() == PDF, "the new download, not the file that was there"


def test_without_a_staging_folder_the_event_is_saved(browser_page, tmp_path):
    page = browser_page(True)
    got, archive, staging, out = _download(page, tmp_path, dl_dir=False)
    assert got is True and out.read_bytes() == PDF
    assert not staging.exists()


def test_a_failed_download_leaves_no_empty_file_and_deletes_nothing(browser_page, tmp_path, monkeypatch):
    """A download that is not a PDF leaves nothing under the statement's
    name, and whatever the browser wrote to its folder stays there."""
    monkeypatch.setattr(sys.modules[__name__], "PDF", b"<html>signed out</html>" + b" " * 5000)
    page = browser_page(True)
    got, archive, staging, out = _download(page, tmp_path)
    assert got is False
    assert _listing(archive) == []
    assert [n for n, _size in _listing(staging)] == [NAME], "the browser's file is kept"
