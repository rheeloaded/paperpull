"""Vanguard's statements table keeps older rows behind a "Show More" control, and the app presses it when the row it was asked for is not on the page.

A made-up table. The first rows are shown, the row asked for appears only after "Show More" is pressed, and a second control on the page, "Show More
Options", is not one the app may press. Everything here is made up and nothing leaves this machine.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import vanguard_site as site

ACCOUNT = "Example Holder, Roth IRA Brokerage Account, 1234567"
TITLE = "Account Statement - " + ACCOUNT
PDF = b"%PDF-1.4\n% invented statement\n" + b"0" * 250000 + b"\n%%EOF\n"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<script>
function said(what) { navigator.sendBeacon('/pressed/' + what); }
function more() { said('more'); document.getElementById('older').style.display = 'table-row-group';
                  document.getElementById('more').style.display = %(after)s; %(then)s }
</script><style>td { height: 64px; } td a { display: inline-block; width: 120px; height: 36px; }</style></head><body>
<table><tr><th>Account</th><th>Date</th><th></th></tr>
<tbody><tr><td>%(account)s</td><td>08/31/2026</td><td></td></tr></tbody>
<tbody id="older" style="display: none">
<tr><td>%(account)s</td><td>02/28/2025</td>
<td><a title="Pdf download icon" href="/doc"
 aria-label="Download a pdf statement generated on February 28, 2025 with description %(account)s">pdf</a></td></tr>
</tbody></table>
%(button)s
<button onclick="said('options')">Show More Options</button>
%(extra)s
</body></html>"""

SHOW_MORE = '<button id="more" onclick="more()">Show More</button>'



class Fake:
    def __init__(self, rows_behind=True):
        self.pressed, self.asked = [], []
        self.hidden = rows_behind
        self.after = "'none'"          # what Show More does once pressed, goes away
        self.then = ""                 # and anything else it does then
        self.button = SHOW_MORE
        self.extra = ""

    def page(self):
        return PAGE % {"account": ACCOUNT, "after": self.after, "then": self.then,
                       "button": self.button, "extra": self.extra}


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
                self._send(PDF, "application/pdf", [("Content-Disposition", 'attachment; filename="2025-02 VG Statement.pdf"')])
            else:
                self._send(fake.page().encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            path = urlsplit(self.path).path
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
    fake = Fake()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    fake.port = httpd.server_address[1]
    yield fake
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def page(tmp_path, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        ctx = driver.chromium.launch_persistent_context(str(tmp_path / "profile"), headless=True, accept_downloads=True)
    except Exception as e:
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "ensure_statements", lambda p: True)
    monkeypatch.setattr(site, "select_year", lambda p, y: False)
    yield ctx.pages[0] if ctx.pages else ctx.new_page()
    ctx.close()
    driver.stop()


def _download(page, tmp_path, date):
    out = tmp_path / "Statements" / "doc.pdf"
    got = site.download_document(page, account_id="123400000000001", charitable=False, doc_type="Statement", title=TITLE, date=date,
                                 out_path=out, dl_dir=tmp_path / ".downloads")
    return got, out


def test_a_row_behind_show_more_is_found_and_saved(page, vanguard, tmp_path):
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out = _download(page, tmp_path, "2025-02-28")
    assert got is True and out.read_bytes() == PDF
    assert vanguard.pressed == ["more"], vanguard.pressed          # "Show More Options" was never pressed
    assert vanguard.asked == ["/doc"]


def test_a_row_already_shown_presses_nothing_extra(page, vanguard, tmp_path, monkeypatch):
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    page.evaluate("document.getElementById('older').style.display = 'table-row-group'")
    got, out = _download(page, tmp_path, "2025-02-28")
    assert got is True and vanguard.pressed == []


def test_a_row_that_is_not_there_stops_after_the_list_runs_out(page, vanguard, tmp_path):
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out = _download(page, tmp_path, "2019-05-31")
    assert got is False and not out.exists()
    assert vanguard.pressed == ["more"] and vanguard.asked == []


def test_a_row_of_another_year_picks_its_year_before_showing_more(page, vanguard, tmp_path,
                                                                  monkeypatch):
    """The table as it stands is one year. A statement of another has its
    own year picked first, so Show More is never pressed through a year the
    row is not in."""
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    picked = []

    def pick(p, year):
        picked.append(year)
        p.evaluate("""() => {
          document.getElementById('older').style.display = 'table-row-group';
          document.getElementById('more').style.display = 'none';
        }""")
        return True

    monkeypatch.setattr(site, "select_year", pick)
    got, out = _download(page, tmp_path, "2025-02-28")
    assert got is True and out.read_bytes() == PDF
    assert picked == ["2025"]
    assert vanguard.pressed == [], vanguard.pressed


def test_a_show_more_that_stays_is_pressed_once_more_and_no_further(page, vanguard, tmp_path,
                                                                    monkeypatch):
    """A control left on the page once every row is drawn draws nothing when
    pressed, and the list is taken as shown in full there, where it was
    pressed thirty times for a row the table does not have."""
    monkeypatch.setattr(site, "SHOW_MORE_WAIT_MS", 1500)
    vanguard.after = "'inline-block'"
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out = _download(page, tmp_path, "2019-05-31")
    assert got is False and not out.exists()
    assert vanguard.pressed == ["more", "more"], vanguard.pressed
    assert vanguard.asked == []


def test_a_show_more_turned_off_once_the_list_is_shown_ends_the_looking(page, vanguard, tmp_path,
                                                                        monkeypatch):
    """A list shown in full can leave its control on the page, turned off.
    Pressed, it would not go through and the run would stop, where a row
    not there leaves that one statement for review and the run goes on."""
    monkeypatch.setattr(site, "SHOW_MORE_WAIT_MS", 1500)
    vanguard.after = "'inline-block'"
    vanguard.then = "document.getElementById('more').disabled = true;"
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out = _download(page, tmp_path, "2019-05-31")
    assert got is False and not out.exists()
    assert vanguard.pressed == ["more"], vanguard.pressed


def test_a_control_named_show_more_whose_words_the_guard_refuses_is_not_pressed(
        page, vanguard, tmp_path):
    """Its name is Show More and its words are not, so the guard, which reads
    the words, refuses it."""
    vanguard.button = ('<button id="more" aria-label="Show More" onclick="more()">'
                       'Transfer money</button>')
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    got, out = _download(page, tmp_path, "2025-02-28")
    assert got is False and not out.exists()
    assert vanguard.pressed == [], vanguard.pressed


def test_a_covered_show_more_is_never_pressed(page, vanguard, tmp_path):
    """Something drawn over the control would take the press, so nothing is
    pressed and the run stops, as at every press (paperpull_core.pressing)."""
    from paperpull_core import pressing
    vanguard.extra = ('<div style="position: fixed; left: 0; top: 0; width: 100vw; '
                      'height: 100vh; background: rgba(0, 0, 0, .3)">Chat with us</div>')
    page.goto("http://127.0.0.1:%d/" % vanguard.port)
    with pytest.raises(pressing.Stop):
        _download(page, tmp_path, "2025-02-28")
    assert vanguard.pressed == [], vanguard.pressed
