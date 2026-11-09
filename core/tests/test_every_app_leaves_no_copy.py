"""A download the browser saved into a folder is taken from there, once.

MEASURED 2026-09-29 on Windows, in Chromium 149, 151 and 153 and Edge 154,
attached over DevTools and launched alike, headed and headless. Once
capture.set_download_dir has pointed the browser at a folder, the browser
writes each download there under the site's own name, and that file is
the only copy. Playwright still raises the download event, and its
save_as then writes an empty file without complaint. A tester's Chrome
154 on macOS gave the event the whole file instead (see capture.py),
which take_download keeps.

Given the folder relative, as an install gives it by default with
output_dir ".", the browser accepted the setting and canceled every
download instead.

What that did to the apps that point the browser at a folder, driven
here in a real browser before this was fixed.

- With the folder relative, no download landed at all, and every
  document these apps saved came from asking the provider a second time.
- With it absolute, eleven saw the empty file, asked the provider for the
  document a second time, saved that answer, and left the browser's file
  in the hidden folder. A second copy of every statement, which outlived
  the one in the archive when somebody deleted it after importing it.
- AT&T asks nothing twice and took the file from the folder. But the
  browser overwrites a finished file of the same name in place, and a
  folder compared by name alone never saw that download arrive. One file
  left under a bill's usual name hid every later bill for good.
- Verizon watches only the folder, by name, and the same.

So every app that points the browser at a folder is found by what it
does, and each one's own capture is driven here in a real Chromium
against a real server, once into an empty folder and once with a file of
the same name already there. Nothing is faked but the provider.
"""
import ast
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

# The name the provider gives every document here. One name for all of
# them is what several providers do, and what makes a leftover dangerous.
NAME = "Statement.pdf"
OLD = b"%PDF-1.4\n% an older statement left in the folder\n%%EOF\n"


def app_modules(app: Path):
    return [p for p in sorted(app.glob("*.py")) if not p.name.startswith("test_")]


def points_the_browser_at_a_folder(app: Path) -> bool:
    """Found by what it does, never by a name."""
    for path in app_modules(app):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "Browser.setDownloadBehavior" in text:
            return True
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name.lstrip("_") == "set_download_dir":
                    return True
    return False


FOLDER_APPS = sorted(d for d in (REPO / "apps").iterdir()
                     if d.is_dir() and not d.name.startswith(("_", "."))
                     and points_the_browser_at_a_folder(d))


def site_of(app: Path):
    import importlib
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


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


SCAFFOLD = [d for d in FOLDER_APPS if has_scaffold_capture(d)]

# -- the provider ------------------------------------------------------------

class Provider:
    """A real server. Every document it hands out is new bytes, so which
    request a saved file came from is never in doubt."""

    PAGES = {
        "/": b"<!doctype html><meta charset='utf-8'>"
             b"<a id='d' href='/doc'>Download statement</a>",
    }

    def __init__(self):
        self.served: list = []
        self.pages = dict(self.PAGES)
        provider = self

        class Handler(BaseHTTPRequestHandler):
            # Keep-alive, as in test_delivery_live. Closed after every
            # request, a whole suite's sockets once ran a Windows runner
            # out of buffer space.
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/doc":
                    body = b"%PDF-1.4\n" + os.urandom(60000) + b"\n%%EOF\n"
                    provider.served.append(body)
                    self.send_response(200)
                    self.send_header("content-type", "application/pdf")
                    self.send_header("content-disposition", 'attachment; filename="%s"' % NAME)
                else:
                    body = provider.pages.get(path, b"not here")
                    self.send_response(200 if path in provider.pages else 404)
                    self.send_header("content-type", "text/html; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reset(self):
        self.served.clear()


@pytest.fixture(scope="module")
def provider():
    p = Provider()
    yield p
    p.httpd.shutdown()


@pytest.fixture(scope="module")
def browser_context(tmp_path_factory):
    """The browser's own context, the one an attached browser is used
    through and the only one set_download_dir reaches. A context made with
    new_context is not pointed anywhere by it."""
    profile = tmp_path_factory.mktemp("profile")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=True, accept_downloads=True,
            args=["--disable-extensions", "--disable-sync",
                  "--disable-background-networking"])
        yield ctx
        ctx.close()


@pytest.fixture
def page(browser_context, provider):
    pg = browser_context.new_page()
    pg.goto(provider.base + "/")
    yield pg
    pg.close()


def folder_for(tmp_path, app, left):
    staging = tmp_path / (".%s-downloads" % app)
    staging.mkdir()
    if left:
        (staging / NAME).write_bytes(OLD)
    out = tmp_path / "Statements" / "2026-08-31 Statement.pdf"
    out.parent.mkdir()
    return staging, out


def check(app, got, provider, out, staging):
    assert got, "%s saved nothing" % app
    assert len(provider.served) == 1, (
        "%s asked the provider %d times for one document the browser already had"
        % (app, len(provider.served)))
    assert out.read_bytes() == provider.served[0], "%s saved something else" % app
    copies = [p.name for p in staging.iterdir() if holds(p, provider.served[0])]
    assert not copies, "%s left the document in its download folder as %s" % (app, copies)


def holds(path: Path, data: bytes) -> bool:
    """Whether the file holds exactly `data`. The browser deletes a download
    it let go in its own time, so a file can be listed and gone before it
    is read, and one that went is no copy."""
    try:
        return path.is_file() and path.read_bytes() == data
    except FileNotFoundError:
        return False


# -- the model this rests on --------------------------------------------------

def test_a_browser_pointed_at_a_folder_keeps_the_only_copy_there(page, provider, tmp_path):
    """Everything below assumes this. If a Chromium or Playwright update
    ever changes it, the fix still holds, but read this again."""
    from paperpull_core.capture import set_download_dir
    staging = tmp_path / ".downloads"
    set_download_dir(page, staging)
    provider.reset()
    with page.expect_download() as info:
        page.click("#d")
    out = tmp_path / "saved.pdf"
    info.value.save_as(str(out))
    assert (staging / NAME).read_bytes() == provider.served[0]
    assert out.read_bytes()[:5] != b"%PDF-", "save_as now carries the bytes"


def test_a_relative_folder_is_made_absolute_so_downloads_land(page, provider, tmp_path,
                                                             monkeypatch):
    """An install passes its folder relative by default, output_dir being
    ".", and given a relative downloadPath Chromium on Windows accepts it
    and then cancels every download (measured 2026-09-29), so in that
    browser none of these apps' downloads had landed in such an install."""
    from paperpull_core.capture import set_download_dir
    monkeypatch.chdir(tmp_path)
    set_download_dir(page, Path(".downloads"))
    provider.reset()
    with page.expect_download() as info:
        page.click("#d")
    download = info.value
    assert download.failure() is None, "the browser canceled the download"
    download.save_as(str(tmp_path / "saved.pdf"))
    assert (tmp_path / ".downloads" / NAME).read_bytes() == provider.served[0]


def test_a_finished_file_of_the_same_name_is_overwritten_in_place(page, provider, tmp_path):
    from paperpull_core.capture import set_download_dir
    staging = tmp_path / ".downloads"
    staging.mkdir()
    (staging / NAME).write_bytes(OLD)
    set_download_dir(page, staging)
    provider.reset()
    with page.expect_download() as info:
        page.click("#d")
    info.value.save_as(str(tmp_path / "saved.pdf"))
    assert sorted(p.name for p in staging.iterdir()) == [NAME]
    assert (staging / NAME).read_bytes() == provider.served[0]


# -- every app that points the browser at a folder -----------------------------

def test_the_apps_that_point_the_browser_at_a_folder_are_found():
    """Not vacuous. These are the ones this was found in."""
    names = {d.name for d in FOLDER_APPS}
    assert {"wellsfargo", "att", "newrez", "verizon", "vanguard"} <= names
    assert {d.name for d in SCAFFOLD} >= {"applecard", "att", "etrade", "golden1",
                                          "newrez", "sba", "smud", "statefarm",
                                          "wellsfargo"}


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_the_browsers_file_is_taken_and_nothing_is_left(app, left, page, provider,
                                                        tmp_path, monkeypatch):
    site = site_of(app)
    monkeypatch.setattr(site, "is_safe_url", lambda u: str(u).startswith(provider.base + "/"))
    staging, out = folder_for(tmp_path, app.name, left)
    site.set_download_dir(page, staging)
    provider.reset()
    got = site._catch_pdf(page, page.locator("#d"), "Download statement", out, [], staging)
    check(app.name, got, provider, out, staging)


@pytest.mark.parametrize("app", SCAFFOLD, ids=lambda d: d.name)
def test_the_folder_every_install_passes_works(app, page, provider, tmp_path, monkeypatch):
    """The folder as a docs module passes it in an install whose output_dir
    is ".", relative to where the app runs."""
    site = site_of(app)
    monkeypatch.setattr(site, "is_safe_url", lambda u: str(u).startswith(provider.base + "/"))
    monkeypatch.chdir(tmp_path)
    staging = Path(".%s-downloads" % app.name)
    out = Path("Statements") / "2026-08-31 Statement.pdf"
    out.parent.mkdir()
    site.set_download_dir(page, staging)
    provider.reset()
    got = site._catch_pdf(page, page.locator("#d"), "Download statement", out, [], staging)
    check(app.name, got, provider, tmp_path / out, tmp_path / staging)


VERIZON_PAGE = b"""<!doctype html><meta charset='utf-8'>
<div role="combobox" id="c0" tabindex="0">Bill date</div>
<div role="listbox" id="l0" hidden>
  <div role="option">August 24, 2026</div><div role="option">July 24, 2026</div>
</div>
<div role="combobox" id="c1" tabindex="0">Delivery</div>
<div role="listbox" id="l1" hidden>
  <div role="option">View online</div><div role="option">Download PDF</div>
</div>
<button id="getmybill">Get My Bill</button>
<script>
for (const [c, l] of [["c0", "l0"], ["c1", "l1"]]) {
  document.getElementById(c).onclick = () => {
    document.querySelectorAll("[role=listbox]").forEach(x => x.hidden = true);
    document.getElementById(l).hidden = false;
  };
  document.getElementById(l).onclick = () => { document.getElementById(l).hidden = true; };
}
document.getElementById("getmybill").onclick = () => { location.href = "/doc"; };
</script>"""


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_verizon_takes_its_bill_from_the_folder(left, browser_context, provider, tmp_path):
    """Verizon picks the bill and the delivery from two dropdowns and
    presses Get My Bill, then watches only the folder."""
    site = site_of(REPO / "apps" / "verizon")
    provider.pages["/verizon"] = VERIZON_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/verizon")
        staging, out = folder_for(tmp_path, "vz", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        got = site.download_bill(pg, staging, "2026-07-24", out)
        check("verizon", got, provider, out, staging)
    finally:
        pg.close()


VANGUARD_ROW = "Example Holder — Cash Plus Account — 1234567"
VANGUARD_LABEL = ("Download a pdf statement generated on August"
                  " 31, 2026 with description " + VANGUARD_ROW)
VANGUARD_PAGE = ("<!doctype html><meta charset='utf-8'><table><tr><td>%s</td>"
                 "<td>08/31/2026</td><td><a href='/doc' title='Pdf download icon' "
                 "aria-label='%s'>PDF</a></td></tr></table>"
                 % (VANGUARD_ROW, VANGUARD_LABEL)).encode("utf-8")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_vanguard_takes_its_statement_from_the_folder(left, browser_context, provider,
                                                      tmp_path, monkeypatch):
    """Vanguard presses a row's download icon and takes the download event.
    Only the check that the statements app is open is stood in for, since
    the page is not on Vanguard's host."""
    site = site_of(REPO / "apps" / "vanguard")
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    provider.pages["/vanguard"] = VANGUARD_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/vanguard")
        staging, out = folder_for(tmp_path, "vanguard", left)
        provider.reset()
        got = site.download_document(pg, account_id="123400000000001", charitable=False,
                                     doc_type="Statement",
                                     title="Account Statement - " + VANGUARD_ROW,
                                     date="2026-08-31", out_path=out, dl_dir=staging)
        check("vanguard", got, provider, out, staging)
    finally:
        pg.close()


IBKR_PAGE = (b"<!doctype html><meta charset='utf-8'><div role='dialog'>"
             b"<select><option>August, 2026</option><option>July, 2026</option></select>"
             b"<button onclick=\"location.href='/doc'\">Download PDF</button></div>")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_ibkr_takes_its_statement_from_the_folder(left, browser_context, provider,
                                                  tmp_path, monkeypatch):
    """Interactive Brokers chooses the month in the Activity Statement
    dialog and presses Download PDF. Only the walk to that dialog is stood
    in for, since the page is not on its host."""
    site = site_of(REPO / "apps" / "ibkr")
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "open_activity_dialog", lambda page: True)
    provider.pages["/ibkr"] = IBKR_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/ibkr")
        staging, out = folder_for(tmp_path, "ibkr", left)
        provider.reset()
        got = site.download_document(pg, account_id="U1234567", doc_type="Activity Statement",
                                     title="Activity Statement - August 2026",
                                     date="2026-08-31", out_path=out, dl_dir=staging)
        check("ibkr", got, provider, out, staging)
    finally:
        pg.close()


COINBASE_PAGE = (b"<!doctype html><meta charset='utf-8'>"
                 b"<div>September 2026<div><button>HTML</button>"
                 b"<button data-testid='statements-pdf-v2' onclick=\"location.href='/doc'\">PDF</button>"
                 b"<button>CSV</button></div></div>")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_coinbase_takes_its_statement_from_the_folder(left, browser_context, provider,
                                                     tmp_path, monkeypatch):
    """Coinbase presses the row's own PDF button and takes the download
    event, through the core, only from its exact document host. Here the
    document comes from the test's provider, so that host stands in for
    the bucket, and the statements page, loaded afresh before the press,
    is this page."""
    site = site_of(REPO / "apps" / "coinbase")
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "reload_statements", lambda page: True)
    monkeypatch.setattr(site, "is_download_url", lambda url: url.startswith(provider.base + "/"))
    provider.pages["/coinbase"] = COINBASE_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/coinbase")
        staging, out = folder_for(tmp_path, "coinbase", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        got = site.download_bill(pg, staging, "2026-09-30", out,
                                 title="Monthly Statement September 2026", trace=[])
        check("coinbase", got, provider, out, staging)
    finally:
        pg.close()


ALPACA_ACCOUNT = "acc0ffee-1234-4abc-8def-0123456789ab"
ALPACA_DOC = "0f0f0f0f-1234-4abc-8def-0123456789ab"
ALPACA_LINK = "/api/v1/accounts/%s/documents/%s/url" % (ALPACA_ACCOUNT, ALPACA_DOC)
ALPACA_PAGE = ("<!doctype html><meta charset='utf-8'><table><tbody><tr><td>2026-08-31</td>"
               "<td>account_statement</td><td><p onclick=\"fetch('%s').then(r => r.json())"
               ".then(j => setTimeout(() => { location.href = j.url + '%%s'; }, %%d))\">"
               "Download</p></td></tr></tbody>"
               "</table>" % ALPACA_LINK)


def _alpaca(provider, monkeypatch, browser_context, tmp_path, left, elsewhere="", later_ms=0,
            run=None, after=None, site=None):
    """Drive Alpaca's own capture on the test's page. `elsewhere` is added
    to the link the page then downloads from, so a download that did not
    come from the link handed over can be made, and the page starts the
    download `later_ms` after the link answers. `after(page)` runs while the
    page is still open, whether the capture took the document or not."""
    site = site or site_of(REPO / "apps" / "alpaca")
    words = list(site.private_words())
    monkeypatch.setattr(site, "is_safe_url", lambda url: url.startswith(provider.base + "/"))
    monkeypatch.setattr(site, "is_download_url", lambda url: url.startswith(provider.base + "/"))
    monkeypatch.setattr(site, "check_live", lambda page, state: None)
    provider.pages["/alpaca"] = (ALPACA_PAGE % (elsewhere, later_ms)).encode("utf-8")
    provider.pages[ALPACA_LINK] = ('{"id": "%s", "url": "%s/doc"}'
                                   % (ALPACA_DOC, provider.base)).encode("utf-8")
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/alpaca")
        staging, out = folder_for(tmp_path, "alpaca", left)
        (staging / "someone else's.pdf").write_bytes(OLD)
        site.set_download_dir(pg, staging)
        provider.reset()
        return site, staging, out, site._catch_document(
            pg, run or site.Run(), staging, 1, ALPACA_DOC, "2026-08-31", "account_statement",
            out, [])
    finally:
        if after is not None:
            after(pg)
        pg.close()
        # The download's own name is made private as it is read, as the
        # account number it carries at Alpaca is. Not kept past this test.
        site.set_private_words(words)


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_alpaca_takes_its_document_from_the_folder(left, browser_context, provider,
                                                   tmp_path, monkeypatch):
    """Alpaca presses a row's own Download once. The page asks for that
    document's link, GET .../documents/<uuid>/url answering {id, url}, and
    the browser downloads the presigned file, which the app takes through
    the core only when it came from that link. Here the test's provider
    answers the link call and serves the file, so its host stands in for
    app.alpaca.markets and for the bucket, and the Live account's check,
    which reads Alpaca's own address and account switcher, is stood in
    for."""
    _site, staging, out, got = _alpaca(provider, monkeypatch, browser_context, tmp_path, left)
    check("alpaca", got, provider, out, staging)


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_alpaca_leaves_a_download_from_another_address_as_it_is(
        left, browser_context, provider, tmp_path, monkeypatch):
    """The only download after the press did not come from exactly the link
    Alpaca handed over, so it is not the press's own and the press's own did
    not come. Nothing is saved, the run stops, and that download, which
    the app cannot tell is its own, is left in the folder as it is, never
    canceled or removed."""
    from paperpull_core import pressing
    with pytest.raises(pressing.Stop) as stop:
        _alpaca(provider, monkeypatch, browser_context, tmp_path, left, elsewhere="?other=1")
    assert stop.value.reason == "the download came from elsewhere"
    assert len(provider.served) == 1, "the page's download was never made"
    staging = tmp_path / ".alpaca-downloads"
    assert not (tmp_path / "Statements" / "2026-08-31 Statement.pdf").exists()
    assert sorted(p.name for p in staging.iterdir()) == [NAME, "someone else's.pdf"]
    assert (staging / NAME).read_bytes() == provider.served[0], "it was not left as it was"


def test_alpaca_removes_a_download_that_comes_after_it_stopped_waiting(
        browser_context, provider, tmp_path, monkeypatch):
    """The press brings its download only after the capture stopped
    waiting, so the capture stops the run with nothing taken. The browser
    then saves the download into the app's folder under the provider's
    name, which at Alpaca is the account number. The run hears it all the
    same, and since it comes from exactly the link Alpaca handed that press,
    at its end cancels it and discards the file the core can tell is that
    download's. Another file in the folder stays, and so does the folder."""
    from paperpull_core import pressing
    site = site_of(REPO / "apps" / "alpaca")
    run = site.Run()
    monkeypatch.setattr(site, "DOWNLOAD_WAIT_MS", 1000)
    monkeypatch.setattr(site, "LATE_DOWNLOAD_WAIT_MS", 6000)
    closed = []
    with pytest.raises(pressing.Stop) as stop:
        _alpaca(provider, monkeypatch, browser_context, tmp_path, False, later_ms=2500,
                run=run, after=lambda pg: closed.append(run.close()), site=site)
    assert stop.value.reason == "no download came"
    staging = tmp_path / ".alpaca-downloads"
    assert len(provider.served) == 1, "the late download was never made"
    assert run.owed_link is None and run.unbound == 0, "the late download was not the press's"
    assert closed == [1], "the late download's file was not discarded"
    assert sorted(p.name for p in staging.iterdir()) == ["someone else's.pdf"]
    assert not (tmp_path / "Statements" / "2026-08-31 Statement.pdf").exists()


# First Horizon's Download PDF opens a popup that becomes the download, and
# Chromium raises that download on the opener, the run's own page. The
# popup reads as an empty address once it is left.
FIRSTHORIZON_PAGE = (b"<!doctype html><meta charset='utf-8'><div id='acc'>"
                     b"<div class='card edocs-item-card' aria-label='Monthly statement for 09/16/2026'>"
                     b"<button class='edocs-download-btn' aria-label='Open New Tab to Download PDF "
                     b"for 09/16/2026 statement' onclick=\"window.open('/doc')\">Download PDF</button>"
                     b"</div></div>")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_firsthorizon_takes_its_statement_from_the_folder(left, browser_context, provider,
                                                         tmp_path, monkeypatch):
    """First Horizon presses the bound card's Download PDF, which opens a
    popup the browser turns into a download fired on the opener, and takes
    that download through the core, only from the statement's own address.
    Only the walk to the card is stood in for, since the page is not on the
    bank's host; the card found is this page's one card, whose address is
    the test provider's document."""
    site = site_of(REPO / "apps" / "firsthorizon")
    monkeypatch.setattr(site, "_reach_card", lambda *a, **k: site.Target(
        "acc", 0, provider.base + "/doc"))
    provider.pages["/firsthorizon"] = FIRSTHORIZON_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/firsthorizon")
        staging, out = folder_for(tmp_path, "firsthorizon", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        run = site.Run()
        run.attach(pg.context)
        got = site.download_statement(pg, run, staging, out, account_id="AcctExample1",
                                      product="Express Checking", document_id="DocExample1",
                                      iso_date="2026-09-16", trace=[])
        check("firsthorizon", got, provider, out, staging)
    finally:
        pg.close()


# A statement row as Chase Business's document center draws it, every word
# made up: the row's save menu, which opens to the row's own Save as PDF.
CHASEBUSINESS_PAGE = (
    b"<!doctype html><meta charset='utf-8'><table><tr id='accountsTable-STATEMENTS-row1'>"
    b"<td>Sep 30, 2026</td><td>Statement</td><td>4 pages</td><td>"
    b"<a id='header-accountsTable-STATEMENTS-row1-cell3-downloadDocumentDropdown'"
    b" href='javascript:void(0)' aria-label='Sep 30, 2026 Opens menu to save document'"
    b" aria-expanded='false' style='display:inline-block;width:40px;height:20px'"
    b" onclick=\"this.setAttribute('aria-expanded','true');"
    b"document.getElementById('item-0-1-downloadPDFOption').style.display='block'\">"
    b"</a>"
    b"<a id='item-0-1-downloadPDFOption' href='javascript:void(0)' style='display:none'"
    b" onclick=\"location.href='/doc'\">Save as PDF</a>"
    b"</td></tr></table>")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_chasebusiness_takes_its_statement_from_the_folder(left, browser_context, provider,
                                                          tmp_path, monkeypatch):
    """Chase Business presses the bound row's save menu and then its own
    Save as PDF, through the guard, and takes the one download that brings
    through the core. Only Chase's PDF address is stood in for, by the
    test's provider, and the walk to the row (account, Statements, year) is
    this page already open."""
    site = site_of(REPO / "apps" / "chasebusiness")
    monkeypatch.setattr(site, "is_download_url", lambda url: url.startswith(provider.base + "/"))
    provider.pages["/chasebusiness"] = CHASEBUSINESS_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/chasebusiness")
        staging, out = folder_for(tmp_path, "chasebusiness", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        got = site._catch_statement(pg, site.Run(), staging, 1, "2026-09-30", out, trace=[])
        check("chasebusiness", got, provider, out, staging)
    finally:
        pg.close()


# A business card's statement row as the same document center draws it,
# every word made up: no save menu, an "opens document" link that is never
# pressed, and the row's own "Saves document" link, which downloads.
CHASEBUSINESS_CARD_PAGE = (
    b"<!doctype html><meta charset='utf-8'><table><tr id='accountsTable-STATEMENTS-row1'>"
    b"<td>Oct 13, 2026</td><td>Statement</td><td>4 pages</td><td>"
    b"<a id='accountsTable-STATEMENTS-row1-cell3-requestThisDocumentAnchor-pdf'"
    b" href='javascript:void(0);' onclick=\"document.title='opened'\">Oct 13, 2026 , opens document</a> "
    b"<a id='accountsTable-STATEMENTS-row1-cell3-requestThisDocumentAnchor-download'"
    b" href='javascript:void(0);' onclick=\"location.href='/doc'\">Oct 13, 2026 Saves document</a>"
    b"</td></tr></table>")


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_chasebusiness_takes_its_card_statement_from_the_folder(left, browser_context, provider,
                                                               tmp_path, monkeypatch):
    """Chase Business presses a business card row's own Saves document link
    once, through the guard, and takes the one download that brings through
    the core. Chase's PDF address is stood in for by the test's provider,
    and the date check by a yes, since the provider's PDF prints nothing."""
    site = site_of(REPO / "apps" / "chasebusiness")
    monkeypatch.setattr(site, "is_download_url", lambda url: url.startswith(provider.base + "/"))
    monkeypatch.setattr(site, "names_date", lambda text, iso: True)
    provider.pages["/chasebusiness-card"] = CHASEBUSINESS_CARD_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/chasebusiness-card")
        staging, out = folder_for(tmp_path, "chasebusiness", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        got = site._catch_statement(pg, site.Run(), staging, 1, "2026-10-13", out, trace=[])
        check("chasebusiness", got, provider, out, staging)
        assert pg.title() != "opened", "the opens document link was pressed"
    finally:
        pg.close()


# A document row as Simmons Bank's Banno page draws it, every word made up:
# the row's own button inside its list item, which here asks the test's
# provider for the document, as the live page asks the bank for its PDF.
SIMMONS_ROW = "Loan Periodic Statement August 2026 Statement, RE ARM 00000000 (x0000)"
SIMMONS_PAGE = (b"<!doctype html><meta charset='utf-8'><jha-list-item role='listitem'>"
                b"<button type='button' onclick=\"location.href='/doc'\">"
                + SIMMONS_ROW.encode() + b"</button></jha-list-item>")
SIMMONS_USER = "0a1b2c3d-1111-4222-8333-944455556666"
SIMMONS_DOC = "11111111-aaaa-4bbb-8ccc-000000000001"


@pytest.mark.parametrize("left", [False, True], ids=["empty folder", "same name already there"])
def test_simmons_takes_its_document_from_the_folder(left, browser_context, provider, tmp_path,
                                                   monkeypatch):
    """Simmons Bank presses the bound row's own button and takes the one
    download that press brings, through the core, when the page asked that
    document's own PDF address and the download carries its own file name.
    Only the bank's Blob address and its PDF address are stood in for, by
    the test's provider, and the documents page is this page."""
    site = site_of(REPO / "apps" / "simmons")
    monkeypatch.setattr(site, "is_download_url", lambda url: url.startswith(provider.base + "/"))
    monkeypatch.setattr(site, "pdf_ids", lambda url: (SIMMONS_USER, SIMMONS_DOC)
                        if (url or "").split("?")[0] == provider.base + "/doc" else ("", ""))
    provider.pages["/simmons"] = SIMMONS_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/simmons")
        staging, out = folder_for(tmp_path, "simmons", left)
        site.set_download_dir(pg, staging)
        provider.reset()
        target = site.Target(SIMMONS_ROW, SIMMONS_DOC, NAME, SIMMONS_USER)
        got = site._catch_document(pg, site.Run(), staging, target, out, trace=[])
        check("simmons", got, provider, out, staging)
    finally:
        pg.close()


DRIVEN_ELSEWHERE_HERE = {"verizon", "vanguard", "ibkr", "coinbase", "alpaca", "firsthorizon",
                         "chasebusiness", "simmons"}

# Apps that point the browser at a folder and take nothing from it, so
# there is no capture here to drive, and why. Each is held to that below.
TAKES_NOTHING = {
    "shelbycounty": "every document is a PDF the page builds in the browser and the app keeps as the Blob "
                    "the page made; no download event, response or folder is ever used",
    "bilt": "every statement is the PDF in the tab its own button opens, read from that tab's own "
            "answer or its address asked once more; the folder is set only so a download a press "
            "began by surprise is canceled there, counted and deleted (see observes_only), and "
            "the run then stops",
    "adp": "every document comes from ADP's statement services, fetched inside the page, "
           "and what the browser saves while a run is attached stays out of the person's "
           "own downloads, where an exact copy of a saved document goes at the next start",
    "optum": "every document is a plain link on the member site, fetched by GET of its own "
             "path with no redirect followed. Nothing is pressed and no download event or "
             "response is ever listened for",
    "spectrum": "every Internet statement is the PDF in the page's own GraphQL answer, matched to "
                "the Blob the page made of it, and every Mobile statement is its page printed with "
                "receipt_pdf.print_page_to_pdf; nothing is downloaded through the browser, and a "
                "download a press began is only counted, canceled and deleted (see observes_only)",
}


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_every_app_that_points_the_browser_at_a_folder_is_driven_here(app):
    """A new app that points the browser at a folder has to be driven by
    this file, with its own capture, before it can pass."""
    assert app in SCAFFOLD or app.name in DRIVEN_ELSEWHERE_HERE or app.name in TAKES_NOTHING, (
        "%s points the browser at a folder and nothing here drives its capture. "
        "Add a test like test_verizon_takes_its_bill_from_the_folder." % app.name)


# What taking a download looks like in an app's own code. Waiting for one,
# saving one, reading the folder one lands in, or handing the press to
# delivery.deliver, which does all of that.
TAKERS = {"expect_download", "take_download", "take_new_pdf", "save_download", "save_as",
          "snapshot", "arrived", "deliver"}

# Listening for one, or waiting for one by the event's name.
LISTENERS = {"on", "once", "wait_for_event", "expect_event"}


# What an observation-only download listener may do with the download it is
# handed: end it, and remove a file the browser had already written. Nothing
# of the download is read or saved. intake.discard is those two, the delete
# waiting only for the cancel, or as long as a download is given where the
# cancel raised, so the download handed to it alone is ended the same way.
OBSERVER_CALLS = {"cancel", "delete"}
DISCARDS = {("intake", "discard"), ("_intake", "discard")}


def observes_only(func) -> bool:
    """True when `func` is a listener that only ends the download it is given.

    The narrow rule that lets an app count a download a press began and
    stop it, without that counting as taking one. The function takes a
    single plain parameter, and every use of that name in its body is an
    exact direct call with no arguments, `download.cancel()` or
    `download.delete()`, or the name handed alone to the core's
    `intake.discard(download)`. The name appearing anywhere else, read through
    (`download.cancel.__self__.path()`), handed on (`keep(download.cancel)`),
    rebound (`drop = download.delete; drop()`), or reused as another
    function's parameter, and the listener is a taker like any other. A
    decorated function is never let off, since what a listener is handed
    is then whatever the decorator made of it, and its body says nothing
    of that.
    """
    if func.decorator_list:
        return False
    a = func.args
    if (a.posonlyargs or a.vararg or a.kwonlyargs or a.kwarg or a.defaults
            or len(a.args) != 1):
        return False
    param = a.args[0].arg
    parent = {}
    for node in ast.walk(func):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    for node in ast.walk(func):
        if isinstance(node, ast.arg) and node is not a.args[0] and node.arg == param:
            return False
        if isinstance(node, (ast.Global, ast.Nonlocal)) and param in node.names:
            return False
        if not (isinstance(node, ast.Name) and node.id == param):
            continue
        attr = parent.get(node)
        call = parent.get(attr)
        if _discarded(node, attr):
            continue
        if not (isinstance(node.ctx, ast.Load)
                and isinstance(attr, ast.Attribute) and attr.value is node
                and attr.attr in OBSERVER_CALLS
                and isinstance(call, ast.Call) and call.func is attr
                and not call.args and not call.keywords):
            return False
    return True


def _discarded(node, call) -> bool:
    """Whether `node` is the one argument of an intake.discard(...) call."""
    if not (isinstance(node.ctx, ast.Load) and isinstance(call, ast.Call)
            and call.args == [node] and not call.keywords):
        return False
    f = call.func
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
        and (f.value.id, f.attr) in DISCARDS


def is_observer(tree, handler) -> bool:
    """True when the handler passed to a download listener is, by name, a
    function of this module that observes_only, and the name is bound to
    nothing else."""
    if not isinstance(handler, ast.Name):
        return False
    defs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == handler.id:
            defs.append(node)
        elif isinstance(node, ast.Name) and node.id == handler.id and not isinstance(node.ctx, ast.Load):
            return False
        elif isinstance(node, ast.arg) and node.arg == handler.id:
            return False
        elif isinstance(node, ast.alias) and (node.asname or node.name) == handler.id:
            return False
    return bool(defs) and all(observes_only(d) for d in defs)


def listened_event(call):
    """The event a listener call names, given by position or as `event=`."""
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg == "event"), None)


def listened_handler(call):
    """The one handler an on/once call hands over, by position or as `f=`,
    or None when it hands over anything else as well."""
    given = list(call.args[1:]) + [k.value for k in call.keywords if k.arg != "event"]
    if len(call.args) > 2 or len(given) != 1:
        return None
    if len(call.args) == 2 or any(k.arg == "f" for k in call.keywords):
        return given[0]
    return None


def is_download(event) -> bool:
    return isinstance(event, ast.Constant) and event.value == "download"


def takes_from_a_folder(app: Path) -> list:
    """Every call in the app's own modules that takes a download, by file
    and line, a download listener included. A listener whose handler only
    ends the download (observes_only) takes nothing and is not counted."""
    found = []
    for path in app_modules(app):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")).lstrip("_")
            listens = name in LISTENERS and is_download(listened_event(node))
            if (listens and name in ("on", "once")
                    and is_observer(tree, listened_handler(node))):
                continue
            if name in TAKERS or listens:
                found.append((path.name, node.lineno))
    return found


@pytest.mark.parametrize("name", sorted(TAKES_NOTHING))
def test_an_app_that_takes_nothing_from_its_folder_has_nothing_that_could(name):
    """An app let off driving takes no download at all, and still points the
    browser at a folder, or its entry has to go."""
    app = REPO / "apps" / name
    assert app in FOLDER_APPS, "%s no longer points the browser at a folder" % name
    assert app not in SCAFFOLD
    assert takes_from_a_folder(app) == []


def test_what_takes_a_download_is_found(tmp_path):
    """The reader under the test above, on a made-up app."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "def a(page, dl, d, s):\n    page.on('download', s.append)\n"
        "def b(dl, d, out):\n    capture.take_download(dl, d, set(), out)\n"
        "def c(d, out):\n    _take_new_pdf(d, set(), out)\n"
        "def e(page):\n    page.on('response', print)\n"
        "def f(page, req, out, d):\n    delivery.deliver(page, req, out, is_safe_url=ok, dl_dir=d)\n"
        "def g(page):\n    with page.expect_event('download'):\n        pass\n"
        "def h(page):\n    page.wait_for_event('popup')\n"
        "def i(page, s):\n    page.context.once(event='download', f=s.append)\n"
        "def j(page):\n    page.wait_for_event(event='download')\n", encoding="utf-8")
    assert sorted(takes_from_a_folder(app)) == [("made_site.py", 2), ("made_site.py", 4),
                                                ("made_site.py", 6), ("made_site.py", 10),
                                                ("made_site.py", 12), ("made_site.py", 17),
                                                ("made_site.py", 19)]


def test_a_listener_handed_over_by_keyword_is_found(tmp_path):
    """`page.on(event="download", f=handler)` is the same listener as the
    positional form, and a handler that reads the file is a taker."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "def on_download(download):\n"
        "    open(download.path()).read()\n"
        "def press(page):\n"
        "    page.on(event='download', f=on_download)\n", encoding="utf-8")
    assert takes_from_a_folder(app) == [("made_site.py", 4)]


@pytest.mark.parametrize("body", [
    "    download.cancel.__self__.path()\n",
    "    keep(download.cancel)\n",
    "    drop = download.delete\n    drop()\n",
    "    intake.discard(download, keep)\n",
    "    intake.save_download_as(download, 'kept.pdf')\n",
    "    other.discard(download)\n",
], ids=["read-through", "handed-on", "rebound", "discard-and-more", "saved", "another-discard"])
def test_a_listener_that_does_more_than_end_the_download_is_found(tmp_path, body):
    """A listener is let off only when it does nothing with the download
    but call its cancel() or delete() directly. Each of these reaches the
    download some other way and is a taker."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "def on_download(download):\n" + body
        + "def press(page):\n    page.on('download', on_download)\n", encoding="utf-8")
    line = 3 + body.count("\n")
    assert takes_from_a_folder(app) == [("made_site.py", line)]


@pytest.mark.parametrize("decorator", ["@keep_a_copy\n", "@tools.keep_a_copy(folder)\n",
                                       "@staticmethod\n"], ids=["name", "call", "builtin"])
def test_a_decorated_listener_is_found(tmp_path, decorator):
    """A decorator replaces the function the listener is handed, so its
    own body says nothing of what runs. Here the wrapper copies the file
    the browser wrote before it calls the handler, which only cancels."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "import shutil\n"
        "def keep_a_copy(handler):\n"
        "    def wrapper(download):\n"
        "        shutil.copy(download.path(), 'kept.pdf')\n"
        "        return handler(download)\n"
        "    return wrapper\n"
        + decorator +
        "def on_download(download):\n"
        "    download.cancel()\n"
        "def press(page):\n"
        "    page.on('download', on_download)\n", encoding="utf-8")
    assert takes_from_a_folder(app) == [("made_site.py", 11)]


def test_a_listener_that_only_ends_the_download_takes_nothing(tmp_path):
    """The observation-only listener an app may keep: it counts the download
    and ends it, and reads and saves nothing of it."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "def press(page, seen):\n"
        "    def on_download(download):\n"
        "        seen.append(1)\n"
        "        try:\n"
        "            download.cancel()\n"
        "        except Exception:\n"
        "            pass\n"
        "        download.delete()\n"
        "    page.on('download', on_download)\n"
        "    page.context.on(event='download', f=on_download)\n"
        "    page.remove_listener('download', on_download)\n"
        "def press_again(page, seen):\n"
        "    def on_download(download):\n"
        "        seen.append(1)\n"
        "        intake.discard(download)\n"
        "    page.on('download', on_download)\n", encoding="utf-8")
    assert takes_from_a_folder(app) == []


# -- what the source has to say ------------------------------------------------

def calls_in(path: Path, name: str) -> list:
    """Line numbers of calls to `name`, as a function or a method, with or
    without a leading underscore."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if called.lstrip("_") == name:
                out.append(node.lineno)
    return out


def cleanup_folder_mismatch(path: Path):
    """What is wrong with the folder this module clears, or None.

    The module that clears what earlier versions left also gives the
    browser its folder, or hands a capture the folder as its dl_dir, and
    every one of those must be the folder it clears, written the same way.
    None given for dl_dir means no folder, and is not one."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    def named(call):
        f = call.func
        return (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")).lstrip("_")

    def arg(call, position, keyword):
        if len(call.args) > position:
            return call.args[position]
        return next((kw.value for kw in call.keywords if kw.arg == keyword), None)

    clears = [c for c in calls if named(c) == "clear_archived_copies"]
    if not clears:
        return None
    cleared = {ast.unparse(arg(c, 0, "dl_dir")) for c in clears}
    given = [arg(c, 1, "dirpath") for c in calls if named(c) == "set_download_dir"]
    handed = [kw.value for c in calls if named(c) != "clear_archived_copies"
              for kw in c.keywords if kw.arg == "dl_dir"]
    folders = {ast.unparse(e) for e in given + handed
               if e is not None and not (isinstance(e, ast.Constant) and e.value is None)}
    if not folders:
        return "clears a folder it never gives the browser or a capture"
    if folders != cleared:
        return "clears %s but gives the browser or a capture %s" % (
            sorted(cleared), sorted(folders))
    return None


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_a_download_event_is_saved_through_the_core(app):
    """In an app that points the browser at a folder, a download event's own
    file is empty. Saving it directly and trusting the result is the bug,
    so the event goes through capture.take_download, which knows where the
    bytes really are."""
    found = []
    for path in app_modules(app):
        for name in ("save_as", "save_download"):
            found += ["%s:%d %s" % (path.name, line, name) for line in calls_in(path, name)]
    assert not found, "%s saves a download event itself: %s" % (app.name, found)


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_every_capture_that_takes_a_download_clears_what_is_left(app):
    """A capture that ends up with the document some other way, a response
    read in flight or the provider asked again, can still find the
    browser's own file in the folder, and removes it when it is an exact
    copy of what was saved."""
    for path in app_modules(app):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
            names = {(c.func.attr if isinstance(c.func, ast.Attribute) else
                      getattr(c.func, "id", "")).lstrip("_")
                     for c in ast.walk(fn) if isinstance(c, ast.Call)}
            if "take_download" in names:
                assert "clear_copies" in names, (
                    "%s %s takes a download and never clears the copies it leaves"
                    % (path.name, fn.name))


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_copies_an_earlier_version_left_are_cleared_on_the_next_run(app):
    """Before this, eleven apps left the browser's copy of every document in
    an install with an absolute output folder. An app that points the browser
    at a folder also clears the ones that are exact copies of documents in
    its archive, from wherever it keeps its records. Vanguard points the
    browser from its site module and clears from its docs module."""
    modules = app_modules(app)
    assert any(calls_in(p, "set_download_dir") for p in modules)
    assert any(calls_in(p, "clear_archived_copies") for p in modules), (
        "%s points the browser at a folder and never clears what earlier "
        "versions left there" % app.name)


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_the_next_run_clears_the_folder_the_browser_is_pointed_at(app):
    """The cleanup and the browser are given the folder in separate calls.
    Given another folder, the cleanup would never see the copies the
    browser left, and would look through a folder where the browser saves
    nothing. Vanguard writes its folder out twice in its docs module, once
    for the cleanup and once for the capture, and its real-browser test
    shows the capture points the browser at the folder it is handed."""
    for path in app_modules(app):
        wrong = cleanup_folder_mismatch(path)
        assert wrong is None, "%s %s" % (path.name, wrong)


def test_a_cleanup_given_another_folder_is_caught(tmp_path):
    """The check above, on modules written to fail it."""
    def module(name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p

    agree = module("a_docs.py", "def page(self):\n"
                   "    site.set_download_dir(p, self._dl_dir)\n"
                   "    capture.clear_archived_copies(self._dl_dir, [])\n")
    assert cleanup_folder_mismatch(agree) is None
    other = module("b_docs.py", "def page(self):\n"
                   "    site.set_download_dir(p, self._dl_dir)\n"
                   "    capture.clear_archived_copies(self._out_dir, [])\n")
    assert "self._out_dir" in cleanup_folder_mismatch(other)
    handed = module("c_docs.py", "def page(self):\n"
                    "    capture.clear_archived_copies(Path(o) / '.x-downloads', [])\n"
                    "def one(self):\n"
                    "    site.download_document(p, dl_dir=Path(o) / '.y-downloads')\n")
    assert ".y-downloads" in cleanup_folder_mismatch(handed)
    alone = module("d_docs.py", "def page(self):\n"
                   "    capture.clear_archived_copies(self._dl_dir, [])\n")
    assert "never gives" in cleanup_folder_mismatch(alone)
    unpointed = module("e_docs.py", "def page(self):\n"
                       "    capture.clear_archived_copies(self._dl_dir, [])\n"
                       "    site.download_document(p, dl_dir=self._dl_dir)\n"
                       "    site.download_document(p, dl_dir=None)\n")
    assert cleanup_folder_mismatch(unpointed) is None


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_the_browser_is_pointed_at_a_folder_only_through_the_core(app):
    """capture.set_download_dir makes the folder absolute, which is what
    stops the browser canceling every download. An app that sent the
    DevTools call itself would skip that."""
    for path in app_modules(app):
        assert "Browser.setDownloadBehavior" not in path.read_text(encoding="utf-8",
                                                                   errors="ignore"), path.name


def test_the_source_reader_sees_through_the_underscore_imports(tmp_path):
    """Every app imports these as _snapshot, _take_new_pdf and so on."""
    probe = tmp_path / "x_site.py"
    probe.write_text("def f(dl):\n    dl.save_as('x')\n    _save_download(dl, 'y')\n"
                     "    _set_download_dir(p, d)\n", encoding="utf-8")
    assert calls_in(probe, "save_as") == [2]
    assert calls_in(probe, "save_download") == [3]
    assert calls_in(probe, "set_download_dir") == [4]
