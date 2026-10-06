"""Vanguard's download icon is pressed only when nothing covers it, in a real
browser and against a local server.

The icon was pressed with force=True, which turns off Playwright's check
that the element itself receives the press, so a chat bubble or a banner
over the icon would have taken the press, as one did on a tester's American
Express page. Now the icon is brought to the middle of the window and
pressed only when it is the thing on top at the point Playwright presses,
and otherwise nothing is pressed and the run stops, saying what is over the
icon only through the word list.

The page cannot scroll, so the bubble stays over the icon. Every press of
the bubble and every download asked for is told to the made-up site.
Everything here is made up and nothing leaves this machine.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import vanguard_docs as app_mod
import vanguard_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import pressing, run_reporting, testkit
from paperpull_core.models import State

HOST = "statements.web.vanguard.test"
HOSTS = "--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" % HOST
ACCOUNT = "Example Holder, Cash Plus Account, 1234567"
TITLE = "Account Statement - " + ACCOUNT
DATE = "2026-08-31"
CANARY = "Quillonby"
PDF = b"%PDF-1.4\n% invented statement 2026-08-31\n" + b"0" * 250000 + b"\n%%EOF\n"

OVER_THE_MIDDLE = "right: 16px; bottom: 16px; width: 220px; height: 64px;"
OVER_A_CORNER = "right: 16px; bottom: 4px; width: 56px; height: 24px;"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<script>function said(what) { navigator.sendBeacon('/pressed/' + what); }</script>
<style>html, body { margin: 0; font: 16px sans-serif; }
main { box-sizing: border-box; min-height: 100vh; display: flex; flex-direction: column;
       justify-content: flex-end; }
table { width: 100%%; border-collapse: collapse; }
td { height: 64px; position: relative; }
td.icons a { position: absolute; right: 32px; top: 14px; width: 120px; height: 36px; }
#chat-launcher { position: fixed; z-index: 1000; background: #c00; color: #fff; %(bubble)s }
</style></head><body><main>
<table><tr><th>Account</th><th>Date</th><th></th></tr>
<tr><td>%(account)s</td><td>08/31/2026</td>
<td class="icons"><a title="Pdf download icon" href="/doc"
 aria-label="Download a pdf statement generated on August 31, 2026 with description %(account)s"
 >pdf</a></td></tr></table>
</main>
<div id="chat-launcher" role="button" aria-label="Chat with %(canary)s"
     onclick="said('bubble')"><span>%(canary)s</span></div>
</body></html>"""


class FakeVanguard:
    def __init__(self):
        self.bubble = OVER_THE_MIDDLE
        self.pressed = []
        self.asked = []

    def page(self):
        return PAGE % {"bubble": self.bubble, "account": ACCOUNT, "canary": CANARY}


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, data, kind, extra=()):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/doc"):
                fake.asked.append(path)
                self._send(PDF, "application/pdf", [(
                    "Content-Disposition", 'attachment; filename="2026-08 VG Statement.pdf"')])
            else:
                self._send(fake.page().encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if path.startswith("/pressed/"):
                fake.pressed.append(path[len("/pressed/"):])
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    return Handler


@pytest.fixture()
def vanguard():
    """A made-up Vanguard of this test's own, on a port of its own."""
    fake = FakeVanguard()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    fake.port = httpd.server_address[1]
    yield fake
    httpd.shutdown()
    httpd.server_close()


def settle(fake, expect=0):
    import time
    deadline = time.monotonic() + 10
    while len(fake.pressed) < expect and time.monotonic() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)


# -- the site's own download, in a browser Playwright starts ------------------------

@pytest.fixture()
def launched(tmp_path, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        ctx = driver.chromium.launch_persistent_context(str(tmp_path / "profile"), headless=True,
                                                         accept_downloads=True)
    except Exception as e:
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    yield ctx
    ctx.close()
    driver.stop()


def _download(page, tmp_path):
    out = tmp_path / "Statements" / "2026-08-31 Vanguard Account Statement.pdf"
    staging = tmp_path / ".vanguard-downloads"
    got = site.download_document(page, account_id="123400000000001", charitable=False,
                                 doc_type="Statement", title=TITLE, date=DATE,
                                 out_path=out, dl_dir=staging)
    return got, out, staging


def _listing(folder: Path):
    return sorted((p.name, p.stat().st_size) for p in folder.iterdir()) if folder.exists() else []


def test_an_icon_with_a_bubble_over_its_middle_is_never_pressed(launched, vanguard, tmp_path):
    page = launched.pages[0] if launched.pages else launched.new_page()
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    with pytest.raises(pressing.Covered) as stopped:
        _download(page, tmp_path)
    settle(vanguard)
    assert vanguard.pressed == [], "the bubble was pressed, %s" % vanguard.pressed
    assert vanguard.asked == [], "no download was asked for"
    out = tmp_path / "Statements"
    assert _listing(out) == [] and _listing(tmp_path / ".vanguard-downloads") == []
    stop = stopped.value
    assert stop.lines[0] == ("Something on the page covers the download icon of the statement "
                             "dated %s, so nothing was pressed." % DATE)
    assert CANARY.lower() not in (" ".join(stop.lines) + repr(stop.facts)).lower()


def test_an_icon_with_a_bubble_over_one_corner_is_pressed_and_saved(launched, vanguard,
                                                                    tmp_path):
    vanguard.bubble = OVER_A_CORNER
    page = launched.pages[0] if launched.pages else launched.new_page()
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out, staging = _download(page, tmp_path)
    settle(vanguard)
    assert got is True and out.read_bytes() == PDF
    assert vanguard.pressed == [] and vanguard.asked == ["/doc"]


# -- the whole run, attached to a browser the way it is at home ----------------------

@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def test_a_run_stops_at_a_covered_icon_and_says_what_covers_it(attached, vanguard, tmp_path,
                                                               capsys, monkeypatch):
    """Resume with one statement to download, the person's tab on the
    statements page and the bubble over the icon. The run stops at that
    statement with nothing pressed, says what covers the icon in words
    from the list, writes the failure file, and reads as stopped."""
    monkeypatch.setattr(site, "is_safe_url", lambda url: urlsplit(url or "").hostname == HOST)
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    from playwright.sync_api import Page
    real_wait = Page.wait_for_timeout
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))

    out = tmp_path / "out"
    out.mkdir()
    doc = app_mod.Document(title=TITLE, category="Statement", summary="Account Statement",
                           date=DATE, account=ACCOUNT, account_id="123400000000001",
                           last4="4567", doc_type="Statement")
    (out / "discovery.json").write_text(json.dumps({doc.key: doc.to_dict()}), encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": attached,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    tab = testkit.open_tab(attached, "http://%s:%d/" % (HOST, vanguard.port), "Statements")
    testkit.keep_only(attached, {tab})

    code = "finished"
    try:
        app_mod.main(["--resume", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    printed = capsys.readouterr().out
    said = " ".join(printed.split())
    settle(vanguard)

    assert vanguard.pressed == [] and vanguard.asked == [], vanguard.pressed
    assert code == 0, said
    assert ("Something on the page covers the download icon of the statement dated %s, "
            "so nothing was pressed." % DATE) in said, said
    reads = [json.loads(line[len(run_reporting.PREFIX):]) for line in printed.splitlines()
             if line.startswith(run_reporting.PREFIX)]
    assert reads and reads[-1]["stopped"] == 1
    failures = sorted(out.rglob("failure-*.json"))
    assert len(failures) == 1
    report = json.loads(failures[0].read_text(encoding="utf-8"))
    assert report["step"] == "press a download icon"
    assert report["reason"] == "something on the page is over the control"
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        assert CANARY.lower() not in path.read_text(encoding="utf-8", errors="ignore").lower(), path
    assert CANARY.lower() not in said.lower()
    progress = json.loads((out / "progress.json").read_text(encoding="utf-8")) \
        if (out / "progress.json").exists() else {}
    assert not [r for r in progress.values() if isinstance(r, dict) and r.get("state")
                in (State.NEEDS_MANUAL_REVIEW.value, State.FAILED.value)], \
        "the statement is left as it was for the next run"
