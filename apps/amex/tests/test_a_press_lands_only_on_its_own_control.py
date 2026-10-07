"""A press lands on its own Download button or nothing is pressed, in a real
browser attached the way it is at home.

On a tester's American Express statements page a chat bubble sat in the
lower right corner over part of the last Download button that showed. The
app pressed with force=True, which turns off Playwright's check that the
element itself receives the press, so the press went to the bubble and
opened the chat. Each later press landed on the chat's suggested replies,
one opened a window to dispute a charge, and a live agent joined. When the
file type dialog did not open, the app pressed the same button again, then
went on to the next document and pressed again there.

Now every press brings its control to the middle of the window, reads what
is on top at the point Playwright will press, and presses nothing when it
is not the control. A press that does not bring what it should is not made
again, and the run stops there.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches over CDP and runs its
own Run All. American Express is a made-up host name the browser is told to
find on this machine, and every other name fails to resolve. Every
statement and date is invented. The made-up page replaces eval as American
Express does, so page.evaluate and locator.evaluate fail on it as they fail
there. Every press of the bubble, a reply, a row's button, a choice, the
dialog's Download and its Cancel is told to the made-up site, which keeps
the list.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amex_docs as app_mod
import amex_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import pressing, run_reporting, testkit
from paperpull_core.models import State

AMEX_HOST = "global.americanexpress.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % AMEX_HOST)
TITLE = "Statements and Year End Summaries"

# Listed oldest first, so the newest, which a run takes first, is the last
# Download button on the page, the one the bubble sits over.
DATES = ["2026-04-27", "2026-05-27", "2026-06-27"]
NEWEST = DATES[-1]

# A word on the bubble that is on no list. It must never come out of the
# run, in what it says or in any file it writes.
CANARY = "Quillonby"

# Where the bubble sits, over the middle of the last Download button or over
# one corner of it. Every row's button is 120 by 36 pixels, 32 from the
# right edge of the window, and the last one ends 14 above the bottom.
OVER_THE_MIDDLE = "right: 16px; bottom: 16px; width: 220px; height: 64px;"
OVER_A_CORNER = "right: 16px; bottom: 4px; width: 56px; height: 24px;"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>%(title)s</title>
<script>
window.eval = function () { throw new Error('eval is disabled'); };
window.SCENARIO = %(scenario)s;
function said(what) { navigator.sendBeacon('/pressed/' + what); }
</script>
<style>
[hidden] { display: none !important; }
html, body { margin: 0; font: 16px sans-serif; }
main { box-sizing: border-box; %(main)s }
h1 { margin: 0; height: 40px; font-size: 24px; }
h2 { margin: 0; height: 30px; font-size: 18px; }
.row { position: relative; height: 64px; border-top: 1px solid #ccc; padding-left: 16px;
       line-height: 64px; }
.row button.dl { position: absolute; right: 32px; top: 14px; width: 120px; height: 36px; }
.row button.mobile { display: none; }
footer { height: %(footer)s; }
#chat-launcher { position: fixed; z-index: 1000; background: #016fd0; color: #fff;
                 border-radius: 30px; text-align: center; overflow: hidden; %(bubble)s }
#chat { position: fixed; inset: 0; pointer-events: none; z-index: 1001; }
#chat .reply { position: fixed; pointer-events: auto; }
#dispute { position: fixed; left: 20px; top: 20px; width: 300px; height: 120px;
           background: #fee; z-index: 1002; }
.backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, .3); z-index: 500; }
.dialog { position: fixed; left: 50%%; top: 50%%; transform: translate(-50%%, -50%%);
          width: 420px; background: #fff; z-index: 501; padding: 16px; }
.choice { position: relative; height: 32px; }
.choice input { position: absolute; left: 0; top: 7px; width: 18px; height: 18px;
                margin: 0; opacity: 0; }
.choice label { position: relative; z-index: 1; display: block; padding-left: 28px;
                line-height: 32px; }
.choice label::before { content: ''; position: absolute; left: 0; top: 7px; width: 16px;
                        height: 16px; border: 1px solid #333; border-radius: 50%%; }
.footer { margin-top: 12px; height: 36px; }
#chatwin { position: fixed; left: 8px; top: 8px; width: 220px; height: 90px; z-index: 900;
           background: #eef; }
#prefs { position: fixed; left: 8px; top: 110px; width: 220px; height: 40px; background: #efe; }
</style></head><body>
<main>
<h1>%(title)s</h1>
<h2>Recent Statements</h2>
%(rows)s
%(heading)s
</main>
<footer></footer>
<div id="chatwin" role="dialog" aria-label="Chat">
  <input id="chat-input" aria-label="Message">
  <button type="button" id="chat-close" aria-label="Close">x</button>
  <button type="button" id="chat-cancel">Cancel</button>
</div>
%(prefs)s
<div id="chat-launcher" role="button" tabindex="0" aria-label="Chat with %(canary)s">
  <span>%(canary)s</span></div>
<div id="chat" hidden></div>
<div id="dispute" role="dialog" aria-label="Dispute a charge" hidden>Tell us about the charge</div>
<div class="backdrop" id="backdrop" hidden></div>
<iframe id="late-frame" style="position: fixed; border: 0; z-index: 2000; visibility: hidden;
        left: 0; top: 0; width: 0; height: 0"
        srcdoc="<body style=&quot;margin: 0&quot;><button style=&quot;width: 100%%;
        height: 100%%&quot; onclick=&quot;parent.said('frame-click')&quot;>Dispute a charge</button>
        </body>"></iframe>
<div class="dialog" id="filetype" %(dialog_role)s aria-label="Select File Type" hidden>
  <h3>Select File Type</h3>
  %(first_choice)s
  <div class="choice"><input type="radio" id="ft-pdf" name="ft" value="statement_pdf">
    <label for="ft-pdf">Billing Statement (PDF)</label></div>
  <div class="choice"><input type="radio" id="ft-sr" name="ft" value="accessible_pdf">
    <label for="ft-sr">Screen Reader (PDF)</label></div>
  <div class="choice"><input type="radio" id="ft-csv" name="ft" value="csv">
    <label for="ft-csv">Spreadsheet (CSV)</label></div>
  <div class="footer">
    %(cancel)s
    <a href="#" role="button" id="myca-activity-download-footer-download-confirm-anchor"
       data-test-id="myca-activity-download-footer-download-confirm-anchor">&#x2913;</a>
  </div>
</div>
<script>
let current = null;
const dialog = document.getElementById('filetype');
const backdrop = document.getElementById('backdrop');
const lateFrame = document.getElementById('late-frame');
function openDialog(date) {
  current = date;
  for (const r of document.querySelectorAll('input[name=ft]')) r.checked = false;
  backdrop.hidden = false;
  dialog.hidden = false;
  const cancel = document.getElementById('ft-cancel');
  if (SCENARIO.frame_over_cancel && cancel) {
    const r = cancel.getBoundingClientRect();
    Object.assign(lateFrame.style, {left: (r.left - 10) + 'px', top: (r.top - 6) + 'px',
                                    width: (r.width + 20) + 'px', height: (r.height + 12) + 'px'});
  }
}
document.addEventListener('mousemove', (e) => {
  const cancel = document.getElementById('ft-cancel');
  if (!SCENARIO.frame_over_cancel || !cancel || dialog.hidden) return;
  const r = cancel.getBoundingClientRect();
  if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom)
    lateFrame.style.visibility = 'visible';
});
function closeDialog() { dialog.hidden = true; backdrop.hidden = true; }
for (const b of document.querySelectorAll('[data-testid$="/download-button"]')) {
  b.addEventListener('click', () => {
    const date = b.dataset.testid.split('/').slice(-2)[0];
    said('row/' + date);
    if (SCENARIO.no_dialog.includes(date)) return;
    openDialog(date);
  });
}
for (const r of document.querySelectorAll('input[name=ft]'))
  r.addEventListener('change', () => said('choice/' + r.value));
const cancelButton = document.getElementById('ft-cancel');
if (cancelButton) cancelButton.addEventListener('click', () => { said('cancel'); closeDialog(); });
dialog.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { said('escape'); closeDialog(); }
});
document.getElementById('chat-close').addEventListener('click', () => said('chat-close'));
document.getElementById('chat-cancel').addEventListener('click', () => said('chat-cancel'));
document.getElementById('chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') said('chat-escape');
});
const other = document.getElementById('other-pdf');
if (other) other.addEventListener('change', () => said('other-choice'));
document.getElementById('myca-activity-download-footer-download-confirm-anchor')
  .addEventListener('click', (e) => {
    e.preventDefault();
    said('confirm/' + current);
    if (SCENARIO.no_download.includes(current)) return;
    const kind = document.getElementById('ft-pdf').checked ? 'pdf' : 'csv';
    location.href = '/download/' + current + '.' + kind;
    // A chat box that takes the focus as soon as anything happens, so a key
    // sent to whatever has the focus goes to the chat.
    if (SCENARIO.steal_focus) document.getElementById('chat-input').focus();
  });
document.getElementById('chat-launcher').addEventListener('click', () => {
  said('bubble');
  const chat = document.getElementById('chat');
  chat.hidden = false;
  const replies = ['Dispute a charge', 'Pay my bill', 'Talk to an agent'];
  const under = [...document.querySelectorAll('button.dl:not(.mobile)')].slice(0, -1);
  under.forEach((b, i) => {
    const r = b.getBoundingClientRect();
    const reply = document.createElement('button');
    reply.className = 'reply';
    reply.textContent = replies[i %% replies.length];
    Object.assign(reply.style, {left: (r.left - 10) + 'px', top: (r.top - 6) + 'px',
                                width: (r.width + 20) + 'px', height: (r.height + 12) + 'px'});
    reply.addEventListener('click', () => {
      said('reply/' + i);
      if (i === 0) { said('dispute'); document.getElementById('dispute').hidden = false; }
    });
    chat.appendChild(reply);
  });
});
</script>
</body></html>"""

# The rows, each with the copy American Express keeps for a narrow window,
# hidden, under the same test id.
ROW = ('<div class="row">Statement closing %(date)s'
       '<button class="dl" data-testid="myca-activity-statements/common/Table/'
       'recent-statements/%(date)s/download-button">Download</button>'
       '<button class="dl mobile" data-testid="myca-activity-statements/common/Table/'
       'recent-statements/%(date)s/download-button">Download</button></div>')

# A collapsed section whose heading sits where the last Download button
# would, under the bubble, for Diagnose, which opens such a section.
HEADING = ('<div class="row">Year End Summary'
           '<button class="dl" aria-expanded="false">Year End Summary</button></div>')
# A choice of a PDF somewhere else on the page, a setting say, before the file
# type dialog in the page's own order.
PREFS = ('<div id="prefs"><input type="radio" id="other-pdf" name="pref" value="statement_pdf">'
         '<label for="other-pdf">Paper or PDF</label></div>')
CANCEL = '<button type="button" id="ft-cancel">Cancel</button>'
# A choice that cannot take the focus, first in the dialog, so Escape sent
# to the dialog's first control would go to whatever has the focus instead.
UNFOCUSABLE = ('<div class="choice"><input type="radio" id="ft-note" name="ft" value="pdf_note"'
               ' disabled><label for="ft-note">Notes (PDF)</label></div>')

# The page as tall as the window, with the rows at its foot, so nothing can
# scroll and the last button stays where the bubble is.
FIXED = {"main": "min-height: 100vh; display: flex; flex-direction: column; "
                 "justify-content: flex-end;", "footer": "0"}
# A page that scrolls, with the last button at the foot of the window when
# it opens, under the bubble until it is brought to the middle.
SCROLLS = {"main": "padding-top: calc(100vh - %dpx);" % (70 + 65 * len(DATES)),
           "footer": "100vh"}


class FakeAmex:
    """One made-up American Express, of a test's own."""

    def __init__(self):
        self.layout = FIXED
        self.bubble = OVER_THE_MIDDLE
        self.no_dialog = []
        self.no_download = []
        self.not_pdf = []
        self.escape_only = False
        self.steal_focus = False
        self.prefs = False
        self.heading = False
        self.frame_over_cancel = False
        self.bare_dialog = False
        self.unfocusable_first = False
        self.slow = {}
        self.never = []
        self.pressed = []
        self.downloads = []

    def page(self):
        return PAGE % {
            "title": TITLE, "canary": CANARY, "bubble": self.bubble,
            "main": self.layout["main"], "footer": self.layout["footer"],
            "rows": "".join(ROW % {"date": d} for d in DATES),
            "heading": HEADING if self.heading else "",
            "prefs": PREFS if self.prefs else "",
            "cancel": "" if self.escape_only else CANCEL,
            "dialog_role": "" if self.bare_dialog else 'role="dialog" aria-modal="true"',
            "first_choice": UNFOCUSABLE if self.unfocusable_first else "",
            "scenario": json.dumps({"no_dialog": self.no_dialog,
                                    "no_download": self.no_download,
                                    "steal_focus": self.steal_focus,
                                    "frame_over_cancel": self.frame_over_cancel})}

    def count(self, what):
        return sum(1 for p in self.pressed if p == what)


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, data, kind, extra=()):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            path = urlsplit(self.path).path
            if host != AMEX_HOST:
                self.send_error(404)
            elif path == "/activity/statements":
                self._send(fake.page().encode("utf-8"), "text/html; charset=utf-8")
            elif path.startswith("/download/"):
                name = path[len("/download/"):]
                fake.downloads.append(name)
                date, kind = name.rsplit(".", 1)
                if date in fake.never:
                    time.sleep(60)   # never answers while the run waits
                    return
                time.sleep(fake.slow.get(date, 0))
                if kind == "pdf" and date not in fake.not_pdf:
                    body = testkit.text_pdf(["American Express", "Statement", date])
                    content = "application/pdf"
                else:
                    body, content = b"date,amount\n", "text/csv"
                self._send(body, content, [("Content-Disposition",
                                            'attachment; filename="statement-%s"' % name)])
            else:
                self.send_error(404)

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

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture()
def amex():
    """A made-up American Express of this test's own, on a port of its
    own, so nothing a test's page sends late reaches the next test."""
    fake = FakeAmex()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    # An answer held back on purpose is not waited for when the test ends.
    httpd.block_on_close = False
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    fake.port = httpd.server_address[1]
    yield fake
    httpd.shutdown()
    httpd.server_close()


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


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """American Express is the made-up site, and the app's fixed pauses are
    short. Its waits for something to happen keep their length, except
    the two a test below waits out, which are cut to a few seconds."""
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == AMEX_HOST)
    monkeypatch.setattr(site, "DIALOG_WAIT_MS", 5000)
    monkeypatch.setattr(site, "DOWNLOAD_WAIT_MS", 8000)
    from playwright.sync_api import Page
    real_wait = Page.wait_for_timeout
    monkeypatch.setattr(Page, "wait_for_timeout", lambda self, ms: real_wait(self, min(ms, 200)))


def their_tab(attached, amex):
    """The person's American Express tab, open on the statements page and
    the only tab in the browser."""
    at = "http://%s:%d/activity/statements" % (AMEX_HOST, amex.port)
    tab = testkit.open_tab(attached, at, TITLE)
    testkit.keep_only(attached, {tab})
    return tab


def config(tmp_path, cdp_url):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run_all(cfg, capsys):
    """Run All, as the panel starts it, and what it said and how it ended."""
    code = "finished"
    try:
        code = app_mod.main(["--all", "--yes", "--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    return code, capsys.readouterr().out


def folded(out):
    return " ".join(out.split())


def panel_reads(out):
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def progress(tmp_path):
    path = tmp_path / "out" / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def saved(tmp_path):
    """The statements the run kept, by date, each one's PDF read back."""
    from paperpull_core.receipt_pdf import pdf_text
    out = {}
    for rec in progress(tmp_path).values():
        if isinstance(rec, dict) and rec.get("downloaded_ok") and Path(rec.get("pdf_path") or "").is_file():
            out[rec["date"]] = pdf_text(Path(rec["pdf_path"]))
    return out


def files_written(tmp_path):
    return sorted(p for p in (tmp_path / "out").rglob("*") if p.is_file())


def failure_files(tmp_path):
    return sorted((tmp_path / "out").rglob("failure-*.json"))


def settle(amex, expect):
    """Wait until the made-up site has heard `expect` presses, since a page
    tells it with a beacon that can land a moment after the run ends, and a
    moment more for one past them. A run that pressed something it should
    not have went on for seconds after it, so its beacon is in by then."""
    import time
    deadline = time.monotonic() + 15
    while len(amex.pressed) < expect and time.monotonic() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)


def test_the_made_up_page_refuses_evaluate_as_american_express_does(attached, amex):
    """Not vacuous. On this page page.evaluate and locator.evaluate fail as
    they fail on American Express, and a locator still reads it, so what
    the app does here is what it can do there."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    their_tab(attached, amex)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(attached)
        page = [t for t in browser.contexts[0].pages if AMEX_HOST in (t.url or "")][0]
        with pytest.raises(PlaywrightError, match="eval is disabled"):
            page.evaluate("1 + 1")
        with pytest.raises(PlaywrightError, match="eval is disabled"):
            page.locator("h1").evaluate("e => e.tagName")
        assert page.locator("[data-testid$='/download-button']").count() == 2 * len(DATES)
        browser.close()


def test_a_bubble_over_the_middle_of_the_button_is_never_pressed(attached, amex, tmp_path,
                                                                 capsys):
    """The bubble covers the middle of the last Download button, which is
    the newest statement's, and the page cannot scroll it away. Nothing is
    pressed, not the bubble, not a reply, not this row and not a later
    one, nothing is downloaded, and the run stops saying what covers the
    button, in words from the list. The app pressed the bubble, then the
    replies the chat put over the other rows' buttons."""
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 0)
    said = folded(out)

    assert amex.count("bubble") == 0, "the bubble was pressed, %s\n%s" % (amex.pressed, said)
    assert not [p for p in amex.pressed if p.startswith(("reply/", "dispute"))], amex.pressed
    assert amex.pressed == [], "nothing at all is pressed, %s" % amex.pressed
    assert amex.downloads == [] and saved(tmp_path) == {}
    assert code == 0, "the run %s rather than stopping\n%s" % (code, said)
    assert panel_reads(out)["stopped"] == 1
    assert ("Something on the page covers the Download button of the statement dated %s, "
            "so nothing was pressed." % NEWEST) in said, said
    assert "stays in place as the page scrolls" in said, said
    assert "labeled" in said
    # What covered it is said through the word list, in what the run says
    # and in every file it wrote.
    assert CANARY.lower() not in said.lower()
    for path in files_written(tmp_path):
        assert CANARY.lower() not in path.read_text(encoding="utf-8", errors="ignore").lower(), path
    written = failure_files(tmp_path)
    assert len(written) == 1, files_written(tmp_path)
    report = json.loads(written[0].read_text(encoding="utf-8"))
    assert report["step"] == "press a download button"
    assert report["reason"] == "something on the page is over the control"
    assert report["extra"]["over_it"]["role"] == "button"
    assert report["extra"]["over_it"]["tag"] == "div"
    assert report["extra"]["fixed"] is True


def test_a_bubble_over_one_corner_leaves_the_press_to_the_button(attached, amex, tmp_path,
                                                                 capsys):
    """The bubble covers one corner of the button and not its middle, where
    Playwright presses. Every statement is saved, each row's button and the
    dialog's Download pressed once, the plain PDF chosen through its label,
    and the bubble never pressed. A chat window open on the page has a Close
    and a Cancel of its own, and a setting elsewhere on the page offers a
    PDF, both before the file type dialog in the page's order. Neither is
    pressed, since the dialog is closed through its own Cancel and its PDF
    is looked for inside it."""
    amex.bubble = OVER_A_CORNER
    amex.prefs = True
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 4 * len(DATES))

    assert code == 0, folded(out)
    assert panel_reads(out)["stopped"] == 0, folded(out)
    assert sorted(saved(tmp_path)) == DATES, folded(out)
    for date, text in saved(tmp_path).items():
        assert date in text, "the statement saved for %s is that statement's" % date
    assert amex.count("bubble") == 0
    for date in DATES:
        assert amex.count("row/" + date) == 1, amex.pressed
        assert amex.count("confirm/" + date) == 1, amex.pressed
    assert amex.count("choice/statement_pdf") == len(DATES), amex.pressed
    assert amex.count("cancel") == len(DATES), "the dialog is closed by its own Cancel"
    assert amex.count("chat-close") == 0 and amex.count("chat-cancel") == 0, amex.pressed
    assert amex.count("other-choice") == 0, "a PDF choice outside the dialog was checked"
    assert sorted(amex.downloads) == sorted(d + ".pdf" for d in DATES)


def test_a_bubble_over_the_middle_moves_off_once_the_button_is_in_the_middle(
        attached, amex, tmp_path, capsys):
    """The page scrolls, and when it opens the bubble covers the middle of
    the last Download button. Brought to the middle of the window, the
    button is clear of the bubble, so it is pressed and every statement is
    saved, with the bubble never pressed."""
    amex.layout = SCROLLS
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 4 * len(DATES))

    assert code == 0, folded(out)
    assert sorted(saved(tmp_path)) == DATES, folded(out)
    assert amex.count("bubble") == 0, amex.pressed
    assert [p for p in amex.pressed if p.startswith("row/")] == ["row/" + d for d in reversed(DATES)]


def test_a_dialog_that_never_opens_stops_the_run_after_one_press(attached, amex, tmp_path,
                                                                 capsys):
    """The newest statement's Download opens no file type dialog. Its button
    is pressed once, never again, no later statement's button is pressed,
    and the run stops saying the dialog did not open. The app pressed it a
    second time and then went on to the next statement."""
    amex.bubble = OVER_A_CORNER
    amex.no_dialog = [NEWEST]
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 1)
    said = folded(out)

    assert amex.count("row/" + NEWEST) == 1, "pressed %d times, %s" % (
        amex.count("row/" + NEWEST), amex.pressed)
    assert amex.pressed == ["row/" + NEWEST], amex.pressed
    assert amex.downloads == [] and saved(tmp_path) == {}
    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("The Download button of the statement dated %s was pressed once and the file "
            "type dialog did not open." % NEWEST) in said, said
    report = json.loads(failure_files(tmp_path)[0].read_text(encoding="utf-8"))
    assert report["reason"] == "the dialog did not open"


def test_a_dialog_download_that_brings_nothing_stops_the_run_after_one_press(
        attached, amex, tmp_path, capsys):
    """The dialog's Download for the newest statement brings no download. It
    is pressed once, nothing for a later statement is pressed, and the run
    stops saying no download came."""
    amex.bubble = OVER_A_CORNER
    amex.no_download = [NEWEST]
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 3)
    said = folded(out)

    assert amex.count("confirm/" + NEWEST) == 1, amex.pressed
    assert [p for p in amex.pressed if p.startswith("row/")] == ["row/" + NEWEST], amex.pressed
    assert saved(tmp_path) == {}
    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("The Download of the file type dialog for the statement dated %s was pressed once "
            "and no download came." % NEWEST) in said, said


def test_a_dialog_with_no_cancel_or_close_is_closed_by_escape_sent_to_its_own_control(
        attached, amex, tmp_path, capsys):
    """The file type dialog has no Cancel or Close and closes on Escape, and
    the chat box takes the focus as the dialog's Download is pressed. Escape
    goes to one of the dialog's own controls, so the dialog closes after
    each statement and the chat box never hears it. Sent to whatever had the
    focus, it went to the chat box and the dialog stayed open."""
    amex.bubble = OVER_A_CORNER
    amex.escape_only = True
    amex.steal_focus = True
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 4 * len(DATES))

    assert code == 0 and panel_reads(out)["stopped"] == 0, folded(out)
    assert sorted(saved(tmp_path)) == DATES, folded(out)
    assert amex.count("escape") == len(DATES), amex.pressed
    assert amex.count("chat-escape") == 0, amex.pressed
    assert amex.count("chat-close") == 0 and amex.count("chat-cancel") == 0, amex.pressed


def test_a_stop_writes_its_own_failure_file_after_an_earlier_one(attached, amex, tmp_path,
                                                                 capsys):
    """The newest statement comes back as something other than a PDF, which
    writes the run's failure file and goes on, and the next statement's
    dialog never opens, which stops the run. A run writes one failure file,
    and the stop wrote nothing, so the file a tester would send named the
    first problem and not the stop. The stop writes a file of its own."""
    amex.bubble = OVER_A_CORNER
    amex.not_pdf = [NEWEST]
    amex.no_dialog = [DATES[1]]
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 5)

    assert code == 0 and panel_reads(out)["stopped"] == 1, folded(out)
    reasons = [json.loads(p.read_text(encoding="utf-8"))["reason"] for p in failure_files(tmp_path)]
    assert "the dialog did not open" in reasons, reasons
    newest = max(failure_files(tmp_path), key=lambda p: p.stat().st_mtime_ns)
    assert json.loads(newest.read_text(encoding="utf-8"))["reason"] == "the dialog did not open"


def test_diagnose_that_meets_a_covered_control_still_writes_its_files(attached, amex, tmp_path,
                                                                      capsys):
    """Diagnose opens a collapsed section, and the bubble covers its
    heading. Nothing is pressed, and Diagnose still writes its detailed file,
    which says why it stopped, and the survey that is safe to send."""
    amex.heading = True
    their_tab(attached, amex)
    code = "finished"
    try:
        code = app_mod.main(["--diagnose", "--config", str(config(tmp_path, attached))])
    except SystemExit as stopped:
        code = stopped.code
    out = capsys.readouterr().out
    settle(amex, 0)

    assert code == 0, folded(out)
    assert amex.pressed == [], amex.pressed
    detailed = tmp_path / "out" / "Diagnostics" / "diagnose-documents.json"
    info = json.loads(detailed.read_text(encoding="utf-8"))
    assert info["stopped"]["reason"] == "something on the page is over the control", info
    assert sorted((tmp_path / "out" / "Diagnostics").glob("survey-*.json")), files_written(tmp_path)
    assert ("Something on the page covers the heading of the Year End Summary section, "
            "so nothing was pressed.") in folded(out), "the stop's own words are said"
    for path in files_written(tmp_path):
        assert CANARY.lower() not in path.read_text(encoding="utf-8", errors="ignore").lower(), path


def test_a_frame_that_comes_over_cancel_after_a_saved_statement_stops_the_run(
        attached, amex, tmp_path, capsys):
    """The newest statement is saved, and as the dialog's own Cancel is
    pressed a frame comes over it and takes the press. The run stops there,
    saying the press may have gone to what came over it, and the statement
    stays recorded as saved, so the next run neither loses it nor fetches
    it again. The close made after a save used to let that stop go and the
    run went on to the next statement."""
    amex.bubble = OVER_A_CORNER
    amex.frame_over_cancel = True
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 4)
    said = folded(out)

    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("Something came over the Cancel of the file type dialog as it was pressed, and "
            "the press may have gone to it, so nothing more is pressed.") in said, said
    assert sorted(saved(tmp_path)) == [NEWEST], said
    assert [r.get("state") for r in progress(tmp_path).values() if r.get("date") == NEWEST] \
        == [State.COMPLETED.value], progress(tmp_path)
    assert [p for p in amex.pressed if p.startswith("row/")] == ["row/" + NEWEST], amex.pressed
    assert amex.count("cancel") == 0 and amex.count("frame-click") == 1, amex.pressed


def test_a_download_that_answers_after_ten_seconds_is_saved(attached, amex, tmp_path, capsys,
                                                            monkeypatch):
    """The newest statement's download starts ten seconds after its press.
    Playwright waits on what a press starts for as long as the press is
    given, and the dialog's Download is given as long as the download, so
    the statement is saved. Given the eight seconds of any other press, the
    press stopped the run as one that did not go through, though it had."""
    monkeypatch.setattr(site, "DOWNLOAD_WAIT_MS", 20000)
    amex.bubble = OVER_A_CORNER
    amex.slow = {NEWEST: 10}
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 4 * len(DATES))

    assert code == 0 and panel_reads(out)["stopped"] == 0, folded(out)
    assert sorted(saved(tmp_path)) == DATES, folded(out)
    assert amex.count("confirm/" + NEWEST) == 1, amex.pressed


def test_a_download_that_never_answers_stops_saying_the_press_was_made(attached, amex, tmp_path,
                                                                     capsys):
    """The newest statement's download never answers. The press was made, so
    the run stops saying it was pressed and the page did not answer in
    time, not that the press did not go through, and nothing is pressed
    again."""
    amex.bubble = OVER_A_CORNER
    amex.never = [NEWEST]
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 3)
    said = folded(out)

    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("The Download of the file type dialog for the statement dated %s was pressed, and "
            "the page did not answer in time, so nothing more is pressed." % NEWEST) in said, said
    assert amex.count("confirm/" + NEWEST) == 1, amex.pressed
    assert [p for p in amex.pressed if p.startswith("row/")] == ["row/" + NEWEST], amex.pressed
    assert saved(tmp_path) == {}


def test_a_dialog_with_no_element_of_its_own_stops_before_anything_in_it_is_pressed(
        attached, amex, tmp_path, capsys):
    """The file type dialog has no role, no dialog tag and no aria-modal, so
    what is its own cannot be told from the rest of the page. Its PDF
    choice is never looked for on the whole page, nothing in it is pressed,
    and the run stops."""
    amex.bubble = OVER_A_CORNER
    amex.bare_dialog = True
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 1)
    said = folded(out)

    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("The file type dialog for the statement dated %s could not be told from the rest "
            "of the page, so nothing in it was pressed." % NEWEST) in said, said
    assert amex.pressed == ["row/" + NEWEST], amex.pressed


def test_escape_is_not_sent_when_the_dialogs_first_control_cannot_take_the_focus(
        attached, amex, tmp_path, capsys):
    """The dialog has no Cancel or Close, its first control cannot take the
    focus, and the chat box takes it. Escape sent to that control would go
    to the chat box, so nothing is sent, the dialog stays open, and the run
    stops at the next statement, with the first one saved."""
    amex.bubble = OVER_A_CORNER
    amex.escape_only = True
    amex.steal_focus = True
    amex.unfocusable_first = True
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    settle(amex, 3)
    said = folded(out)

    assert code == 0 and panel_reads(out)["stopped"] == 1, said
    assert ("The file type dialog was open and would not close, so nothing was pressed for "
            "this document.") in said, said
    assert sorted(saved(tmp_path)) == [NEWEST], said
    assert amex.count("chat-escape") == 0 and amex.count("escape") == 0, amex.pressed


def test_the_stops_are_stops_and_not_failures():
    """Every stop leaves through SystemExit, which no except Exception in
    the run takes for an ordinary failure, so the run never goes on to the
    next document after one."""
    for kind in (pressing.Covered, pressing.Unread, pressing.NotPressed, pressing.NoAnswer):
        assert issubclass(kind, SystemExit) and not issubclass(kind, Exception)
