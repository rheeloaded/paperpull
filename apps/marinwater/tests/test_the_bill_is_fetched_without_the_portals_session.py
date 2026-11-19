"""A bill's PDF is asked for in a request context of its own.

The viewer is Playwright's own APIRequestContext, which Chromium's routes and
host rules never see, so these tests serve the viewer from a local server on
127.0.0.1 and let the app's own check accept that one address. Everything
else runs as the app runs it, the real `App._viewer`, the real
`site._pdf_bytes` and a real browser context holding a cookie, so a context
that shared the browser's cookies or followed a redirect would show here.
All values are invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marinwater_docs as app_mod
import marinwater_site as site
from paperpull_core.testkit import text_pdf

PDF = text_pdf(["Synthetic Marin Water bill", "Mar 9, 2032"])
COOKIE = "Ck4Pmtsx"


class _Viewer(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802  (the handler's own name)
        self.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        if "redirect" in self.path:
            self.send_response(302)
            self.send_header("Location", "/resource/SSEPDFExtractor.dll?after-the-redirect")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF)))
        self.end_headers()
        self.wfile.write(PDF)

    def log_message(self, *args):
        pass


@pytest.fixture
def viewer_host(monkeypatch):
    _Viewer.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Viewer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}{site.DOWNLOAD_PATH}"
    # The one address this test accepts in place of the real viewer host.
    monkeypatch.setattr(site, "is_download_url", lambda url: str(url).startswith(base + "?"))
    monkeypatch.setattr(site, "_on_portal", lambda _page: True)
    monkeypatch.setattr(site, "_is_marin_water", lambda _page: True)
    yield base
    server.shutdown()
    server.server_close()


@pytest.fixture
def driver():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        yield playwright, browser
        browser.close()


def _app_on(playwright, context):
    app = app_mod.App.__new__(app_mod.App)
    app._pw, app._context = playwright, context
    return app


def _bill(ref):
    return site.RawDoc(title="Marin Water Bill 2032-03-09", date_text="2032-03-09",
                       href=site.DOWNLOAD_PATH, document_id="bill-2032-03-09", bill_ref=ref)


def test_the_pdf_request_carries_no_cookie_of_the_browser(driver, viewer_host):
    playwright, browser = driver
    context = browser.new_context()
    context.add_cookies([{"name": "JSESSIONID", "value": COOKIE, "url": viewer_host}])
    # The control. The browser's own request context does carry the cookie,
    # so the server below would see one if the app's viewer shared it.
    context.request.get(viewer_host + "?control").dispose()
    assert COOKIE in _Viewer.seen[-1][1].get("cookie", "")

    app = _app_on(playwright, context)
    viewer = app._viewer()
    try:
        data = site._pdf_bytes(None, _bill(viewer_host + "?invented-bill"), [], viewer)
    finally:
        viewer.dispose()
    assert data == PDF
    path, headers = _Viewer.seen[-1]
    assert path.endswith("?invented-bill")
    assert "cookie" not in headers
    assert "referer" not in headers and "authorization" not in headers
    assert headers.get("accept") == "application/pdf"
    context.close()


def test_a_redirect_from_the_viewer_is_never_followed(driver, viewer_host):
    playwright, browser = driver
    context = browser.new_context()
    app = _app_on(playwright, context)
    viewer = app._viewer()
    trace: list = []
    try:
        data = site._pdf_bytes(None, _bill(viewer_host + "?redirect"), trace, viewer)
    finally:
        viewer.dispose()
    assert data == b""
    assert [p for p, _ in _Viewer.seen] == [site.DOWNLOAD_PATH + "?redirect"]
    assert trace and trace[0]["status"] == 302
    context.close()


class _Spy:
    """A viewer whose every request fails, counting its disposals."""

    def __init__(self, fails_with):
        self.fails_with, self.disposed = fails_with, 0

    def get(self, *_args, **_kw):
        raise self.fails_with

    def dispose(self):
        self.disposed += 1


def _run_app(tmp_path, monkeypatch, spy):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                  "min_pdf_bytes": 100}), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config)])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(args)
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(app, "_on_its_site", lambda: None)
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    made = []
    app._pw = SimpleNamespace(request=SimpleNamespace(
        new_context=lambda **kw: made.append(kw) or spy))
    return app, made


def test_the_viewer_is_disposed_when_discovery_fails_on_it(tmp_path, monkeypatch, viewer_host):
    rows = [{"cells": ["000000", "Mar 9, 2032", "View Bill"], "views": [f"{viewer_host}?{n}"]}
            for n in ("one", "two")]
    monkeypatch.setattr(site, "_all_bills", lambda _page: site.bills_of(
        ["Account", "Bill Date", "Action"], rows))
    site._RUN.clear()
    spy = _Spy(RuntimeError("invented network failure"))
    app, made = _run_app(tmp_path, monkeypatch, spy)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert made == [{}] and spy.disposed == 1


def test_the_viewer_is_disposed_when_a_download_is_interrupted(tmp_path, monkeypatch, viewer_host):
    site._RUN.clear()
    site._RUN["bills"] = [_bill(viewer_host + "?interrupted")]
    spy = _Spy(KeyboardInterrupt())
    app, made = _run_app(tmp_path, monkeypatch, spy)
    doc = app_mod.Document(category="Statement", date="2032-03-09",
                           title="Marin Water Bill 2032-03-09", document_id="bill-2032-03-09",
                           href=site.DOWNLOAD_PATH)
    with pytest.raises(KeyboardInterrupt):
        app.download_one(None, doc, "2032-03-09 Water Bill.pdf")
    site._RUN.clear()
    assert made == [{}] and spy.disposed == 1
