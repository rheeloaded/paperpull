"""A PDF the page reads into a blob, pressed in every scaffold capture.

Measured on 2026-10-05 in Chromium 153 attached over CDP, the pair CI and
the packaged app run, with each of the twelve captures cut from one
scaffold (_catch_pdf) pressed against made-up pages in Playwright 1.62 and
1.63. A PDF the page fetches and reads with Response.blob() leaves the
browser's answer empty. Playwright 1.62 then asked the address again by
itself, through the browser, and handed the capture the PDF. 1.63 asks
again only for a GET of a font, image, manifest, media, script, stylesheet
or text track, so a fetch answer now reads empty without raising, while one
read as an array buffer, a stream or through XMLHttpRequest still reads
whole. These captures asked again only when reading raised, so under 1.63
that answer was passed over.

Where the page also handed the PDF over another way the capture watches,
a download, a tab at the blob's own address, or this tab moving to it,
the document still came. Where the page kept the PDF and drew it itself,
or showed it in a frame of its own page, in a tab whose blob address it
had let go, or behind a data address, nothing else brought it, and each
of the twelve gave up on at least two of those. AT&T reads a frame's blob
back, and Apple Card and American Family keep the blobs a page makes,
which covered some of them.

None of this is known of any provider's own page. Most of these apps were
built without an account, and every way of handing a document over that a
real account has shown here (American Family's blob tab, Apple Card's
saved blob, AT&T's and Newrez's downloads, SMUD's PDF in the same tab)
still came under 1.63. The pages here are ways a page could do it.

Now such an answer is set aside when it answered a request this press
made, from its own tab or one it opened, since a late answer to the last
press was saved under the next document's name in E*TRADE (#36) and
Newrez (#38) and State Farm saved a PDF from a tab that was already open
(#37). When the capture has waited its whole time and nothing else has
brought the document, and the press read exactly one answer empty, a GET
on the provider's own host, that address is asked for once more from
inside the page, refusing any redirect. Only a PDF, or a ZIP where the app
opens one, is filed. Two such answers could be two documents, so neither
is asked, and a POST is never sent twice. American Family's capture asks
nothing again, since it never takes a PDF the press made without a tab of
its own, which could be another document (review of 0.41.0).

Each app's own capture is pressed in a real browser started as a program
of its own with a debugging port and attached over CDP, as at home. The
made-up provider answers at localhost and another site at 127.0.0.1, and
every other name fails to resolve, so nothing leaves this machine. The
page marks each request of its own with an X-Page header, so a request for
a statement without one is the capture asking again.
"""
import ast
import importlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

pytest.importorskip("playwright.sync_api", reason="needs a browser")

from paperpull_core import browser as browser_launcher  # noqa: E402
from paperpull_core import testkit  # noqa: E402

PROVIDER = "localhost"
ELSEWHERE = "127.0.0.1"
HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1, EXCLUDE localhost"

# Captures that ask nothing again, and why.
ASKS_NOTHING = {"amfam": "never takes a PDF the press made without a tab of its own"}


def has_scaffold_capture(app: Path) -> bool:
    """The capture every scaffold app shares, _catch_pdf(page, el, label,
    out_path, trace, dl_dir)."""
    path = app / ("%s_site.py" % app.name)
    if not path.exists():
        return False
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_catch_pdf":
            args = [a.arg for a in node.args.args]
            return args[:6] == ["page", "el", "label", "out_path", "trace", "dl_dir"]
    return False


SCAFFOLD = sorted(d for d in (REPO / "apps").iterdir()
                  if d.is_dir() and not d.name.startswith(("_", ".")) and has_scaffold_capture(d))
ASKING = [d for d in SCAFFOLD if d.name not in ASKS_NOTHING]


def site_of(app: Path):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


# The statements page. How its press asks for the statement and what it
# does with it is named in the page's address, way=<how>.
#   kept          reads it into a blob and keeps it, drawing it itself
#   frame         reads it into a blob and shows it in a frame of the page
#   elsewhere     POSTs for it, and reads one from another site, both kept
#   post-and-get  POSTs for it and GETs a notice beside it, both kept
#   late          reads it into a blob, waits until /gate says open, then
#                 hands it over as a download and says so at /handed
#   earlier       asked for it as the page opened, before the press, and the
#                 answer comes only once the test lets it go, while the
#                 press asks for nothing
#   nothing       the press asks for nothing
#   other         another tab of the provider, open before the press, which
#                 asks for a statement once /gate2 says open
#   wrapped       wraps fetch the way a site can, passing each call on
#                 without its signal
# Every press asks for /kept once it is done, so a test can tell.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body><main><h1>Statements</h1>
<table><tr><td>June 30, 2026</td>
<td><button id="get" type="button" style="width:220px;height:40px">Download statement</button></td>
</tr></table><div id="viewer"></div></main>
<script>
const q = new URLSearchParams(location.search);
const way = q.get('way'), doc = '/doc/' + q.get('n');
const ELSEWHERE = '%(elsewhere)s';
const own = (url, opts) => fetch(url, Object.assign({}, opts || {}, {headers: {'X-Page': '1'}}));
const blob = async (url, opts) => await (await own(url, opts)).blob();
const until = async (path) => {
  while ((await (await fetch(path)).text()) !== 'open') { await new Promise(r => setTimeout(r, 25)); }
};
if (way === 'wrapped') {
  // A site's own fetch wrapper that passes each call on without its signal.
  const theirs = window.fetch;
  window.fetch = (url, opts) => theirs(url, Object.assign({}, opts || {}, {signal: undefined}));
}
if (way === 'earlier') {
  blob(doc + '?slow=1').then(b => { window.earlier = b; });
}
if (way === 'other') {
  (async () => { await until('/gate2'); window.theirs = await blob(doc + '-other'); })();
}
document.getElementById('get').addEventListener('click', async () => {
  if (way === 'kept') {
    window.kept = await (await blob(doc)).arrayBuffer();
  } else if (way === 'frame') {
    const f = document.createElement('iframe');
    f.style.width = '600px'; f.style.height = '400px';
    f.src = URL.createObjectURL(await blob(doc));
    document.getElementById('viewer').appendChild(f);
  } else if (way === 'elsewhere') {
    const posted = await blob(doc, {method: 'POST', body: 'n=1'});
    window.kept = [posted, await (await fetch(ELSEWHERE + doc)).blob()];
  } else if (way === 'post-and-get') {
    window.kept = [await blob(doc, {method: 'POST', body: 'n=1'}), await blob(doc + '-notice')];
  } else if (way === 'late') {
    const b = await blob(doc);
    await fetch('/kept');
    await until('/gate');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b); a.download = 'statement.pdf';
    document.body.appendChild(a); a.click();
    await fetch('/handed');
    return;
  }
  await fetch('/kept');
});
</script></body></html>"""


class Provider:
    """A real server. Each statement is new bytes, so which request a saved
    file came from is never in doubt."""

    def __init__(self):
        self.n = 0
        self.reset()
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _send(self, data, kind, status=200, extra=()):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                for name, value in extra:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def _noted(self):
                # The method, host and path, whether the page marked it as its
                # own, and its Sec-Fetch-Mode, which the browser names on every
                # request it makes and Playwright's own client never does.
                host = (self.headers.get("Host") or "").split(":")[0]
                path = urlsplit(self.path).path
                provider.seen.append((self.command, host, path, self.headers.get("X-Page") == "1",
                                      self.headers.get("Sec-Fetch-Mode")))
                return host, path

            def _statement(self, path):
                # The page's own request gets the statement, and asked again
                # it answers as `again` says.
                if self.headers.get("X-Page") != "1" and provider.again == "page":
                    self._send(b"<!doctype html><title>Signed out</title><p>Sign in again</p>",
                               "text/html; charset=utf-8")
                elif self.headers.get("X-Page") != "1" and provider.again == "redirect":
                    self._send(b"", "text/plain", status=302, extra=[(
                        "Location", "http://%s:%d%s" % (ELSEWHERE, self.server.server_address[1], path))])
                else:
                    self._send(provider.statement(path), "application/pdf")

            def do_GET(self):
                host, path = self._noted()
                port = self.server.server_address[1]
                if path == "/statements" and host in (PROVIDER, ELSEWHERE):
                    page = PAGE % {"elsewhere": "http://%s:%d" % (ELSEWHERE, port)}
                    self._send(page.encode("utf-8"), "text/html; charset=utf-8")
                elif host == PROVIDER and path.startswith("/hop/"):
                    # A request that redirects to a statement, held first
                    # with slow=1 until the test lets it go.
                    give_up = time.monotonic() + 30
                    while "slow=1" in self.path and not provider.let_go and time.monotonic() < give_up:
                        time.sleep(0.02)
                    self._send(b"", "text/plain", status=302, extra=[(
                        "Location", "/doc/hopped-" + path.split("/")[2])])
                elif host == PROVIDER and path in ("/kept", "/handed"):
                    setattr(provider, path[1:], True)
                    self._send(b"ok", "text/plain")
                elif host == PROVIDER and path in ("/gate", "/gate2"):
                    opened = provider.gate_open if path == "/gate" else provider.other_open
                    self._send(b"open" if opened else b"shut", "text/plain")
                elif host == PROVIDER and path.startswith("/doc/") and "slow=1" in self.path:
                    # An answer to a request made before the press, held
                    # until the test lets it go.
                    give_up = time.monotonic() + 30
                    while not provider.let_go and time.monotonic() < give_up:
                        time.sleep(0.02)
                    self._send(provider.statement(path), "application/pdf")
                elif host == PROVIDER and path.startswith("/doc/"):
                    self._statement(path)
                elif host == ELSEWHERE and path.startswith("/doc/"):
                    self._send(provider.statement(path), "application/pdf", extra=[
                        ("Access-Control-Allow-Origin", "http://%s:%d" % (PROVIDER, port))])
                else:
                    self.send_error(404)

            def do_POST(self):
                host, path = self._noted()
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if host == PROVIDER and path.startswith("/doc/"):
                    self._send(provider.statement(path), "application/pdf")
                else:
                    self.send_error(404)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reset(self):
        """A new statement and nothing heard yet."""
        self.n += 1
        self.seen = []
        self.statements = {}
        self.again = "pdf"
        self.kept = False
        self.handed = False
        # How many times the capture has looked since the page was done, the
        # look at which /gate and /gate2 open, the look at which an answer
        # held back is let go, and whether each has happened.
        self.looks = 0
        self.open_at = self.other_at = self.let_go_at = 0
        self.gate_open = self.other_open = self.let_go = False
        # The look at which the test's own listener heard an answer it was
        # waiting for, the capture's listener being beside it.
        self.heard_at = None

    def statement(self, path) -> bytes:
        if path not in self.statements:
            self.statements[path] = testkit.text_pdf(["Made-up Bank", "Statement June 30, 2026",
                                                      "Press %d at %s" % (self.n, path)])
        return self.statements[path]

    def address(self, way=""):
        return "http://%s:%d/statements?way=%s&n=%d" % (PROVIDER, self.port, way, self.n)

    def statements_asked(self, host=PROVIDER):
        return [s for s in self.seen if s[1] == host and s[2].startswith("/doc/")]

    def asked_again(self):
        """Requests for a statement that the page did not mark as its own."""
        return [s for s in self.statements_asked() if not s[3]]


@pytest.fixture(scope="module")
def provider():
    p = Provider()
    yield p
    p.httpd.shutdown()
    p.httpd.server_close()


@pytest.fixture(autouse=True)
def fresh(provider):
    """Each test starts on a statement of its own, before it says what an
    address asked again answers."""
    provider.reset()


@pytest.fixture(scope="module")
def attached(provider, tmp_path_factory):
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    try:
        with testkit.drawn_browser(found[0][1], lambda: tmp_path_factory.mktemp("profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(scope="module")
def context(attached):
    from playwright.sync_api import sync_playwright
    driver = sync_playwright().start()
    try:
        yield driver.chromium.connect_over_cdp(attached).contexts[0]
    finally:
        driver.stop()


@pytest.fixture()
def read_empty(monkeypatch):
    """Every answer that brings a statement reads empty, as Playwright 1.63
    reads a fetch the page took into a blob, whichever Playwright runs."""
    from playwright.sync_api import Response
    real_body = Response.body
    emptied = []

    def body(self):
        if urlsplit(self.url).path.startswith("/doc/"):
            emptied.append(self.url)
            return b""
        return real_body(self)

    monkeypatch.setattr(Response, "body", body)
    return emptied


@pytest.fixture()
def pages(context):
    """Tabs a test opens, closed after it."""
    opened = []
    yield opened
    for page in opened:
        try:
            page.close()
        except Exception:
            pass


@pytest.fixture()
def press(context, provider, pages, tmp_path, monkeypatch):
    """Presses Download statement with the app's own capture, on the page
    whose press works the way named, and says whether the capture saved
    anything and where it would have filed it.

    A look the capture starts before the page says it is done lasts until
    the page says so, its own second at most, and after that each look is a
    fiftieth as long, so a capture that waits its whole time does so in a
    second or two. It counts its looks rather than the clock, so what it
    does is the same either way. Kept whole, the first look of most presses
    was a second spent after the page was done, a minute of the suite in
    all. The looks after it are counted, the gates open and an answer held
    back is let go at the ones a test names, and once /gate opens each look
    is whole again, so a download the page makes then has the capture's own
    time to arrive. A listener of the test's own, beside the capture's,
    notes the look at which an answer the capture should leave alone was
    heard. The look at which that answer is let go, or the other tab is let
    ask for it, lasts until the answer has been heard, 30 seconds at most,
    so the capture has the rest of its looks after it however slow the
    machine is. Without that, a full run on a busy machine once heard the
    other tab's answer only at the 24th of the capture's 25 looks."""

    def heard(response):
        if provider.heard_at is None and ("slow=1" in response.url or "-other" in response.url):
            provider.heard_at = provider.looks

    context.on("response", heard)

    def run(app, way):
        site = site_of(app)
        monkeypatch.setattr(site, "is_safe_url", lambda url: (
            urlsplit(url or "").scheme == "http" and urlsplit(url).hostname == PROVIDER
            and urlsplit(url).port == provider.port))
        page = context.new_page()
        pages.append(page)
        own_wait = page.wait_for_timeout

        def look(ms):
            if not provider.kept:
                done_by = time.monotonic() + ms / 1000
                while not provider.kept and time.monotonic() < done_by:
                    own_wait(25)
                return
            provider.looks += 1
            for at, name in ((provider.open_at, "gate_open"), (provider.other_at, "other_open"),
                             (provider.let_go_at, "let_go")):
                if at and provider.looks >= at:
                    setattr(provider, name, True)
            if provider.looks in (provider.other_at, provider.let_go_at):
                give_up = time.monotonic() + 30
                while provider.heard_at is None and time.monotonic() < give_up:
                    own_wait(25)
            own_wait(ms if provider.gate_open else max(1, int(ms) // 50))

        page.wait_for_timeout = look
        staging = tmp_path / (".%s-downloads" % app.name)
        site.set_download_dir(page, staging)
        page.goto(provider.address(way), wait_until="load")
        if way == "earlier":
            give_up = time.monotonic() + 20
            while not provider.statements_asked() and time.monotonic() < give_up:
                own_wait(25)
        provider.seen.clear()
        out = tmp_path / "Statements" / "2026-06-30 Statement.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        saved = site._catch_pdf(page, page.query_selector("#get"), "Download statement", out, [],
                                staging)
        return saved, out

    yield run
    context.remove_listener("response", heard)


def the_statement(provider, suffix=""):
    return provider.statement("/doc/%d%s" % (provider.n, suffix))


def capture_of(app: Path):
    tree = ast.parse((app / ("%s_site.py" % app.name)).read_text(encoding="utf-8", errors="ignore"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_catch_pdf")


def asks_again(app: Path) -> bool:
    """Whether the app's capture calls the core's ask_again."""
    called = {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
              for c in ast.walk(capture_of(app)) if isinstance(c, ast.Call)}
    return bool({"ask_again", "_ask_again"} & called)


def stops_what_it_starts(app: Path) -> bool:
    """Whether every RequestsSince the capture starts is stopped in a
    finally of the same capture, so no request listener is left behind
    holding every later request of the run."""
    capture = capture_of(app)
    started = set()
    for node in ast.walk(capture):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")).lstrip("_") == "RequestsSince":
                started |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    stopped = set()
    for node in ast.walk(capture):
        if isinstance(node, ast.Try):
            for part in node.finalbody:
                for c in ast.walk(part):
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                            and c.func.attr == "stop" and isinstance(c.func.value, ast.Name):
                        stopped.add(c.func.value.id)
    return bool(started) and started <= stopped


def test_every_scaffold_capture_is_found():
    """Not vacuous. These are the twelve this was measured in."""
    assert {d.name for d in SCAFFOLD} >= {"adp", "amfam", "applecard", "att", "etrade", "golden1",
                                          "newrez", "sba", "smud", "statefarm", "verizonmobile",
                                          "wellsfargo"}


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_every_capture_asks_again_through_the_core_or_not_at_all(app):
    """What an address asked again may answer, a redirect or a web page, and
    when nothing may be asked at all, is held by capture.ask_again and
    tested once at the end of this file. So every capture asks through it,
    and one that asks nothing again says why here. A capture that asks
    stops the request listener it starts."""
    assert asks_again(app) is (app.name not in ASKS_NOTHING), app.name
    if app.name not in ASKS_NOTHING:
        assert stops_what_it_starts(app), "%s leaves its request listener behind" % app.name


@pytest.mark.parametrize("app", ASKING, ids=lambda d: d.name)
def test_a_pdf_the_page_kept_is_asked_for_once_more(app, press, provider, read_empty):
    """The page reads the statement into a blob and keeps it, as a page
    that draws a PDF itself does. Its answer reads empty and nothing else
    brings it, so it comes only by asking its address once more, and that
    answer is filed. Apple Card presses a button that brought nothing once
    more, so its page may ask twice, and the address is still asked again
    only once."""
    saved, out = press(app, "kept")
    assert read_empty, "the capture never read the statement's answer"
    assert saved is True
    assert out.read_bytes() == the_statement(provider)
    # Asked by the page's own fetch, which names its mode, never by
    # Playwright's own client, which names none.
    assert [(s[0], s[2], s[4]) for s in provider.asked_again()] == [
        ("GET", "/doc/%d" % provider.n, "cors")], provider.seen


def test_american_family_never_asks_again(press, provider, read_empty):
    """American Family's capture takes a PDF the page made only from a tab
    the press opened for it (review of 0.41.0), so a PDF the page kept is
    neither asked for again nor filed."""
    saved, out = press(REPO / "apps" / "amfam", "kept")
    assert read_empty, "the capture never read the statement's answer"
    assert saved is False
    assert not out.exists()
    assert not provider.asked_again(), provider.seen


@pytest.mark.parametrize("app", ASKING, ids=lambda d: d.name)
def test_a_pdf_shown_in_a_frame_of_the_page_is_filed(app, press, provider):
    """The page reads the statement into a blob and shows it in a frame of
    its own page. Nothing is changed in Playwright or the browser, so on
    1.63 the answer reads empty as it does at home. The statement is filed,
    and asked for again once at most."""
    saved, out = press(app, "frame")
    assert saved is True
    assert out.read_bytes() == the_statement(provider)
    assert len(provider.asked_again()) <= 1, provider.seen


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_a_post_and_another_host_are_never_asked_again(app, press, provider, read_empty):
    """The page POSTs for one statement and reads another from another
    site, both into blobs, and both answers read empty. Neither is asked
    for again, the POSTed address is never asked with a GET, and nothing is
    filed."""
    saved, out = press(app, "elsewhere")
    assert provider.kept, "the page never got both statements"
    assert saved is False
    assert not out.exists()
    assert not provider.asked_again(), provider.seen
    assert {s[0] for s in provider.statements_asked()} == {"POST"}, provider.seen
    assert {s[0] for s in provider.statements_asked(ELSEWHERE)} == {"GET"}, provider.seen


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_a_post_beside_a_get_leaves_both_unasked(app, press, provider, read_empty):
    """The page POSTs for the statement and GETs a notice beside it, both
    into blobs, and both answers read empty. Two answers could be two
    documents, and which is this one cannot be told, so neither is asked
    for again and nothing is filed. Asking the one GET would file the
    notice."""
    saved, out = press(app, "post-and-get")
    assert provider.kept, "the page never got both"
    assert saved is False
    assert not out.exists()
    assert not provider.asked_again(), provider.seen


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_a_download_after_the_first_wait_wins_over_asking_again(app, press, provider,
                                                               read_empty):
    """The page reads the statement into a blob, its answer reads empty, and
    the page hands it over as a download only once the capture has looked
    sixteen times, past every capture's first wait. An empty answer is
    asked for again only when nothing else has come in the capture's whole
    time, so the download is filed and the address is never asked again.
    Asked as soon as it was heard, or after the first wait, the provider
    would be asked twice for one statement, and a download still arriving
    when the capture ended would be left in the folder."""
    provider.open_at = 16
    saved, out = press(app, "late")
    assert not provider.asked_again(), provider.seen
    assert provider.handed, "the page never handed the statement over"
    assert saved is True
    assert out.read_bytes() == the_statement(provider)


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_an_answer_to_a_request_made_before_the_press_is_never_asked_again(app, press, provider,
                                                                          read_empty):
    """The page asked for a statement as it opened, before the press, and
    that answer comes while the capture watches and reads empty. A late
    answer to the last document's press was saved under the next one's
    name in E*TRADE (#36) and Newrez (#38). Only an answer to a request the
    press made is asked for again, so this one never is, and nothing is
    filed."""
    provider.let_go_at = 2
    saved, out = press(app, "earlier")
    assert provider.heard_at is not None, "the earlier answer never came"
    assert provider.looks >= provider.heard_at + 5, "the capture stopped watching first"
    assert not provider.asked_again(), provider.seen
    assert saved is False
    assert not out.exists()


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_an_answer_to_another_tab_is_never_asked_again(app, press, provider, pages, context,
                                                       read_empty):
    """Another tab of the provider's, open before the press, asks for a
    statement while the capture watches, and that answer reads empty. State
    Farm saved a PDF that loaded in a tab of the person's that was already
    open (#37). Only an answer to a request from the press's own tab, or a
    tab opened since, is asked for again, so this one never is, and
    nothing is filed."""
    theirs = context.new_page()
    pages.append(theirs)
    theirs.goto(provider.address("other"), wait_until="load")
    provider.other_at = 2
    saved, out = press(app, "nothing")
    assert provider.heard_at is not None, "the other tab's answer never came"
    assert provider.looks >= provider.heard_at + 5, "the capture stopped watching first"
    assert not provider.asked_again(), provider.seen
    assert saved is False
    assert not out.exists()


# -- capture.ask_again and capture.RequestsSince, which every capture uses -----

@pytest.fixture()
def on_the_provider(context, provider, pages):
    """A tab on the made-up provider's page, the way a capture's tab is when
    it asks."""
    page = context.new_page()
    pages.append(page)
    page.goto(provider.address("nothing"), wait_until="load")
    provider.seen.clear()
    return page


def test_asking_again_files_the_one_answer_a_get_read_empty(on_the_provider, provider, tmp_path):
    """One answer, to a GET on an address the guard allows, is asked for
    once more from inside the page and its PDF filed. The list is emptied."""
    from paperpull_core.capture import ask_again
    url = "http://%s:%d/doc/b" % (PROVIDER, provider.port)
    answers = [("GET", url), ("GET", url)]
    out = tmp_path / "statement.pdf"
    assert ask_again(on_the_provider, answers, out, lambda u: True) is True
    assert out.read_bytes() == provider.statement("/doc/b")
    assert answers == []
    assert [(s[0], s[2]) for s in provider.asked_again()] == [("GET", "/doc/b")], provider.seen


@pytest.mark.parametrize("answers, why", [
    ([("GET", "/doc/a"), ("GET", "/doc/b")], "two answers could be two documents"),
    ([("POST", "/doc/a")], "a POST is never sent twice"),
    ([("POST", "/doc/a"), ("GET", "/doc/b")], "a POST beside a GET is two documents"),
    ([("GET", "elsewhere:/doc/a")], "the guard refuses another site"),
], ids=["two GETs", "a POST", "a POST and a GET", "another site"])
def test_asking_again_asks_nothing_when_it_cannot_be_sure(on_the_provider, provider, tmp_path,
                                                          answers, why):
    from paperpull_core.capture import ask_again

    def address(path):
        host = ELSEWHERE if path.startswith("elsewhere:") else PROVIDER
        return "http://%s:%d%s" % (host, provider.port, path.split(":")[-1])

    def guard(url):
        return urlsplit(url).hostname == PROVIDER

    held = [(method, address(path)) for method, path in answers]
    out = tmp_path / "statement.pdf"
    assert ask_again(on_the_provider, held, out, guard) is False, why
    assert held == []
    assert not out.exists()
    assert not provider.seen, provider.seen


def test_asking_again_files_only_a_document(on_the_provider, provider, tmp_path):
    """Asked again, the address answers with a web page, as a session that
    has lapsed would, and nothing is filed."""
    from paperpull_core.capture import ask_again
    provider.again = "page"
    out = tmp_path / "statement.pdf"
    url = "http://%s:%d/doc/p" % (PROVIDER, provider.port)
    assert ask_again(on_the_provider, [("GET", url)], out, lambda u: True) is False
    assert not out.exists()
    assert [(s[0], s[2]) for s in provider.asked_again()] == [("GET", "/doc/p")], provider.seen


def test_asking_again_follows_no_redirect(on_the_provider, provider, tmp_path):
    """Asked again, the address answers with a redirect to the same
    statement on another site. The redirect is refused, so nothing reaches
    the other site and nothing is filed."""
    from paperpull_core.capture import ask_again
    provider.again = "redirect"
    out = tmp_path / "statement.pdf"
    url = "http://%s:%d/doc/r" % (PROVIDER, provider.port)
    assert ask_again(on_the_provider, [("GET", url)], out, lambda u: True) is False
    assert not out.exists()
    assert [(s[0], s[1], s[2]) for s in provider.seen] == [("GET", PROVIDER, "/doc/r")], provider.seen


def test_asking_again_only_from_a_tab_on_the_providers_site(context, provider, pages, tmp_path):
    """The press sent its tab to another site, as a sign-in page on another
    host or a viewer would be. Asking from there would hand that site's page
    the document's address, so nothing is asked."""
    from paperpull_core.capture import ask_again
    page = context.new_page()
    pages.append(page)
    page.goto("http://%s:%d/statements?way=nothing" % (ELSEWHERE, provider.port), wait_until="load")
    provider.seen.clear()
    out = tmp_path / "statement.pdf"
    url = "http://%s:%d/doc/s" % (PROVIDER, provider.port)
    assert ask_again(page, [("GET", url)], out, lambda u: urlsplit(u).hostname == PROVIDER) is False
    assert not out.exists()
    assert not provider.statements_asked(), provider.seen


def test_asking_again_gives_up_in_its_time_when_the_page_drops_the_signal(
        context, provider, pages, tmp_path, monkeypatch):
    """The page wraps fetch, as a site can, and passes the call on without
    its abort signal, and the address never answers. Asking again still
    gives up when its time is up, rather than holding the capture for good."""
    from paperpull_core import capture
    monkeypatch.setattr(capture, "ASK_AGAIN_MS", 500)
    page = context.new_page()
    pages.append(page)
    page.goto(provider.address("wrapped"), wait_until="load")
    url = "http://%s:%d/doc/w?slow=1" % (PROVIDER, provider.port)
    started = time.monotonic()
    try:
        assert capture.ask_again(page, [("GET", url)], tmp_path / "s.pdf", lambda u: True) is False
        assert time.monotonic() - started < 10, "the time limit did not hold"
    finally:
        provider.let_go = True


def test_a_redirect_counts_as_the_request_it_began_with(context, provider, pages):
    """A request the page made before the press, held by the server and
    redirected while the press watches, is not the press's, though the
    request its redirect makes is new. One the press made and that
    redirected is the press's."""
    from paperpull_core.capture import RequestsSince
    page = context.new_page()
    pages.append(page)
    page.goto(provider.address("nothing"), wait_until="load")
    page.evaluate("u => { fetch(u); }", "/hop/early?slow=1")
    give_up = time.monotonic() + 20
    while not [s for s in provider.seen if s[2] == "/hop/early"] and time.monotonic() < give_up:
        page.wait_for_timeout(25)
    made = RequestsSince(page, context.pages)
    try:
        with page.expect_request(lambda r: urlsplit(r.url).path == "/doc/hopped-early") as early:
            provider.let_go = True
        with page.expect_request(lambda r: urlsplit(r.url).path == "/doc/hopped-late") as late:
            page.evaluate("u => { fetch(u); }", "/hop/late")
        assert early.value.redirected_from is not None and late.value.redirected_from is not None
        assert not made.made(early.value)
        assert made.made(late.value)
    finally:
        made.stop()


def test_a_press_is_its_own_tab_and_the_tabs_opened_since(context, provider, pages):
    """capture.RequestsSince holds the requests of the press's own tab and
    of tabs opened since it began, from the moment it starts until it
    stops. A request made before it started, one from a tab that was open
    before, and one made after it stopped are not the press's."""
    from paperpull_core.capture import RequestsSince

    def tab():
        page = context.new_page()
        pages.append(page)
        page.goto(provider.address("nothing"), wait_until="load")
        return page

    def asked(page, path):
        with page.expect_request(lambda r: urlsplit(r.url).path == path) as request:
            page.evaluate("u => { fetch(u); }", path)
        return request.value

    theirs, page = tab(), tab()
    earlier = asked(page, "/doc/earlier")
    made = RequestsSince(page, context.pages)
    try:
        own = asked(page, "/doc/own")
        other = asked(theirs, "/doc/theirs")
        opened = asked(tab(), "/doc/opened")
        assert made.made(own) and made.made(opened)
        assert not made.made(earlier) and not made.made(other)
    finally:
        made.stop()
    later = asked(page, "/doc/later")
    assert not made.made(later)


def test_the_page_asks_the_way_the_tests_say(context, provider, pages, tmp_path):
    """The made-up page itself, with no app. Each way asks for the
    statement the way the tests above say it does, and says it is done.
    Its download goes to a folder of the test's own, as each press's does."""
    from paperpull_core.capture import set_download_dir
    page = context.new_page()
    pages.append(page)
    set_download_dir(page, tmp_path / "downloads")

    def until(done):
        give_up = time.monotonic() + 20
        while not done() and time.monotonic() < give_up:
            page.wait_for_timeout(50)
        return done()

    for way, asks in (("kept", [("GET", PROVIDER)]),
                      ("frame", [("GET", PROVIDER)]),
                      ("elsewhere", [("POST", PROVIDER), ("GET", ELSEWHERE)]),
                      ("post-and-get", [("POST", PROVIDER), ("GET", PROVIDER)]),
                      ("late", [("GET", PROVIDER)]),
                      ("nothing", [])):
        provider.reset()
        page.goto(provider.address(way), wait_until="load")
        provider.seen.clear()
        page.click("#get")
        assert until(lambda: provider.kept), way
        if way == "late":
            assert not provider.handed, "handed over before /gate opened"
            provider.gate_open = True
            assert until(lambda: provider.handed), "never handed over once /gate opened"
        statements = [s for s in provider.seen if s[2].startswith("/doc/")]
        assert [(s[0], s[1]) for s in statements] == asks, way
        assert all(s[3] for s in statements if s[1] == PROVIDER), "the page did not mark its own"
    provider.reset()
    page.goto(provider.address("earlier"), wait_until="load")
    assert until(lambda: provider.statements_asked()), "not asked for as the page opened"
    provider.let_go = True
    assert until(lambda: page.evaluate("!!window.earlier")), "never answered once let go"
    provider.reset()
    page.goto(provider.address("other"), wait_until="load")
    assert not provider.statements_asked(), "asked before /gate2 opened"
    provider.other_open = True
    assert until(lambda: provider.statements_asked()), "never asked once /gate2 opened"
