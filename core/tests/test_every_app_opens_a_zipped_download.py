"""A ZIP the provider hands over reaches the code that opens it.

Every docs module cut from the old USAA one carries a branch for a tax
form that arrives as a ZIP holding its PDF, now receipt_pdf.open_zip. In
the apps that take a browser download, that branch could never run. Their
captures took a file only when it began with the PDF marker, and the
scaffold's download_one then deleted anything that did not, before the
branch was reached. A provider that handed over a ZIP got "Could not
capture the document PDF" and a manual review on every run.

What the branch did once it ran was no better, as a review found. It
filed the first of several PDFs under the document's name before any
check, left the others beside it unchecked, and destroyed the archive's
other files. So a ZIP holding one PDF and nothing else is opened, and
anything more is kept whole in Manual Review for a person.

MEASURED 2026-09-29 on Playwright's Chromium 153, headless, against a
local server. A ZIP a page hands over is always a download, whether it is
sent as application/zip or application/octet-stream, with an attachment
header or without, and when the link opens a new tab, which is left
holding nothing. The download event is raised on the page that was
clicked. Its response body cannot be read (Network.getResponseBody finds
no resource), which is true of every download, PDF included. Once
capture.set_download_dir has pointed the browser at a folder, the event's
save_as writes an empty file and the browser's file in that folder is the
only copy. In a browser never pointed anywhere, save_as holds the bytes.

So the bytes of a ZIP are only ever in the event's own file or in the
folder, and the only code that reads either is capture.take_download and
capture.take_new_pdf, or an app's own save of the event. That is where a
ZIP is accepted.

THE CENSUS. Every app whose download_one opens a ZIP is found by what it
does, and so is every one of those whose download_one can reach code that
takes a browser download. Each of those is driven here end to end, its
own capture in a real Chromium against a real server, then its own
download_one, in the browser as that app leaves it (pointed at a folder
given relative, the way every install gives it, or never pointed at all),
once with a ZIP of one PDF and once with a ZIP of two. The rest take their
documents through delivery, which checks a document's identity from its
text and so takes only a PDF, or ask the provider for the bytes
themselves, and those keep only a PDF. Their branch can run only if a
provider's own answer to them were a ZIP, and that is said here rather
than hidden.
"""
import ast
import inspect
import io
import json
import os
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

ZIP_NAME = "TaxForms.zip"
PDF_NAME = "Statement.pdf"
DATE = "2026-01-31"
ACCOUNT = "SAPPHIRE 1234"
# What the PDF inside each ZIP says, so every app's own reading of a saved
# document finds what it looks for, its name, the date in every form an
# app prints one in, and the account.
PRINTED = ("{provider} Tax Form 1099 {account} Statement Period Ending 01/31/26 "
           "January 31, 2026 Jan 31, 2026 01/31/2026 1/31/2026 2026-01-31 Page 1 of 1")

FLAGS = ["--disable-extensions", "--disable-sync", "--disable-background-networking",
         "--disable-component-update", "--no-first-run",
         # Nothing here may reach a real provider. Every page is local.
         "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"]


def text_pdf(text: str, salt: str = "") -> bytes:
    """A one-page PDF whose text pypdf reads back, big enough for every
    app's minimum size. `salt` makes two of them differ."""
    safe = text.replace("\\", "").replace("(", "[").replace(")", "]")
    stream = ("BT /F1 10 Tf 36 720 Td (%s) Tj ET" % safe).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%" + salt.encode("ascii") + b"\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, xref)
    return bytes(out) + b" " * 5000


def zipped(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


# -- the provider ------------------------------------------------------------

class Provider:
    """A real server. Every document it hands out is new bytes, so which
    request a saved file came from is never in doubt."""

    PAGE = (b"<!doctype html><meta charset='utf-8'>"
            b"<a id='zip' href='/zip'>Download tax form</a> "
            b"<a id='octet' href='/octet'>Download tax forms</a> "
            b"<a id='blank' href='/zip' target='_blank'>Open tax form</a> "
            b"<a id='pdf' href='/pdf'>Download statement</a>")

    def __init__(self):
        self.served: list = []     # what each answer carried, in order
        self.inside: list = []     # the PDF inside each ZIP answered
        self.pages = {"/": self.PAGE}
        self.text = PRINTED.format(provider="Wells Fargo", account=ACCOUNT)
        # What each ZIP holds besides the form, a second PDF when a test
        # asks for one.
        self.more: dict = {}
        provider = self

        class Handler(BaseHTTPRequestHandler):
            # Keep-alive, as in test_delivery_live. Closed after every
            # request, a whole suite's sockets once ran a Windows runner
            # out of buffer space.
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                path = self.path.split("?")[0]
                headers = []
                status = 200
                if path in ("/zip", "/octet"):
                    pdf = text_pdf(provider.text, os.urandom(8).hex())
                    body = zipped(dict({"1099-INT.pdf": pdf}, **provider.more))
                    provider.inside.append(pdf)
                    provider.served.append(body)
                    kind = "application/zip" if path == "/zip" else "application/octet-stream"
                    headers = [("content-type", kind),
                               ("content-disposition", 'attachment; filename="%s"' % ZIP_NAME)]
                elif path == "/pdf":
                    body = text_pdf(provider.text, os.urandom(8).hex())
                    provider.served.append(body)
                    headers = [("content-type", "application/pdf"),
                               ("content-disposition", 'attachment; filename="%s"' % PDF_NAME)]
                elif path in provider.pages:
                    body = provider.pages[path]
                    headers = [("content-type", "text/html; charset=utf-8")]
                else:
                    body, status = b"not here", 404
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
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
        self.inside.clear()
        self.more = {}

    def ours(self, url) -> bool:
        return str(url).startswith(self.base + "/")


@pytest.fixture(scope="module")
def provider():
    p = Provider()
    yield p
    p.httpd.shutdown()


@pytest.fixture(scope="module")
def playwright_driver():
    with sync_playwright() as p:
        yield p


def _launch(driver, profile):
    return driver.chromium.launch_persistent_context(
        str(profile), headless=True, accept_downloads=True, args=FLAGS)


@pytest.fixture(scope="module")
def browser_context(playwright_driver, tmp_path_factory):
    """The browser's own context, the one an attached browser is used
    through and the only one set_download_dir reaches. The apps that point
    the browser at a folder are driven in this one."""
    ctx = _launch(playwright_driver, tmp_path_factory.mktemp("profile"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="module")
def plain_context(playwright_driver, tmp_path_factory):
    """A browser nothing ever points at a folder, as the apps that take a
    download without one leave theirs."""
    ctx = _launch(playwright_driver, tmp_path_factory.mktemp("plain-profile"))
    yield ctx
    ctx.close()


@pytest.fixture
def page(browser_context, provider):
    pg = browser_context.new_page()
    pg.goto(provider.base + "/")
    yield pg
    pg.close()


def module_of(app: Path, suffix: str):
    """An app's own module, imported fresh, since every app has a storage
    module and a site module of the same shape."""
    import importlib
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_site", "_docs")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_%s" % (app.name, suffix))
    finally:
        sys.path.pop(0)


def archives_in(folder: Path) -> list:
    """Every file under `folder` that is still a ZIP, or a temporary one
    extraction made, whatever it is called."""
    out = []
    for p in Path(folder).rglob("*"):
        if not p.is_file():
            continue
        with p.open("rb") as f:
            magic = f.read(4)
        if magic == b"PK\x03\x04" or p.suffix.lower() in (".zip", ".tmp"):
            out.append(str(p.relative_to(folder)))
    return out


# -- what this rests on --------------------------------------------------------

def test_a_zip_is_a_download_and_the_folder_holds_the_only_copy(page, provider, tmp_path):
    from paperpull_core.capture import set_download_dir
    staging = tmp_path / ".downloads"
    set_download_dir(page, staging)
    provider.reset()
    with page.expect_download() as info:
        page.click("#zip")
    saved = tmp_path / "saved.pdf"
    info.value.save_as(str(saved))
    assert (staging / ZIP_NAME).read_bytes() == provider.served[0]
    assert saved.read_bytes() == b"", "save_as now carries the bytes"


def test_a_browser_never_pointed_at_a_folder_hands_the_zip_to_save_as(plain_context, provider,
                                                                     tmp_path):
    pg = plain_context.new_page()
    try:
        pg.goto(provider.base + "/")
        provider.reset()
        with pg.expect_download() as info:
            pg.click("#zip")
        saved = tmp_path / "saved.pdf"
        info.value.save_as(str(saved))
        assert saved.read_bytes() == provider.served[0]
    finally:
        pg.close()


def test_the_answer_of_a_download_cannot_be_read_off_the_response(page, provider):
    bodies = []

    def on_response(res):
        if res.url.endswith("/octet"):
            try:
                bodies.append(res.body())
            except Exception as e:
                bodies.append(e)

    page.on("response", on_response)
    provider.reset()
    with page.expect_download():
        page.click("#octet")
    page.wait_for_timeout(300)
    page.remove_listener("response", on_response)
    assert bodies and all(isinstance(b, Exception) for b in bodies), bodies


def test_a_zip_opened_in_a_new_tab_is_still_a_download_on_this_page(page, provider,
                                                                   browser_context):
    tabs = []

    def on_page(tab):
        tabs.append(tab)

    browser_context.on("page", on_page)
    provider.reset()
    try:
        with page.expect_download():
            page.click("#blank")
        page.wait_for_timeout(500)
        # The new tab never holds a document. Playwright gives its address
        # as an empty string, so there is nothing in it to read.
        assert len(tabs) == 1 and tabs[0].url in ("", "about:blank"), [t.url for t in tabs]
    finally:
        browser_context.remove_listener("page", on_page)
        for t in tabs:
            t.close()


# -- the proof, one app ------------------------------------------------------------

WELLS = REPO / "apps" / "wellsfargo"


def test_wells_fargo_takes_a_pdf_from_this_page(page, provider, tmp_path, monkeypatch):
    """The control. The same capture against the same page takes a PDF."""
    site = module_of(WELLS, "site")
    monkeypatch.setattr(site, "is_safe_url", provider.ours)
    staging = tmp_path / ".wellsfargo-downloads"
    out = tmp_path / "Statements" / "2026-01-31 Wells Fargo Statement.pdf"
    out.parent.mkdir()
    site.set_download_dir(page, staging)
    provider.reset()
    assert site._catch_pdf(page, page.locator("#pdf"), "Download statement", out, [], staging)
    assert out.read_bytes() == provider.served[0]


@pytest.mark.parametrize("link", ["#zip", "#octet"], ids=["application/zip", "octet-stream"])
def test_wells_fargo_takes_a_zip_download(link, page, provider, tmp_path, monkeypatch):
    site = module_of(WELLS, "site")
    monkeypatch.setattr(site, "is_safe_url", provider.ours)
    staging = tmp_path / ".wellsfargo-downloads"
    out = tmp_path / "Tax Documents" / "2026-01-31 Wells Fargo Tax Form.pdf"
    out.parent.mkdir()
    site.set_download_dir(page, staging)
    provider.reset()
    got = site._catch_pdf(page, page.locator(link), "Download tax form", out, [], staging)
    assert got, "the ZIP the provider handed over was refused"
    assert out.read_bytes() == provider.served[0]
    assert len(provider.served) == 1, "the provider was asked again"
    assert not list(staging.iterdir()), "the browser's file was left in the folder"


ROW_LINK_PAGE = (b"<!doctype html><meta charset='utf-8'><div>Form 1099-INT "
                 b"<a href='/zip' aria-label='Download 1099 January 31, 2026'>"
                 b"Download 1099</a></div>")


def test_wells_fargo_takes_a_zip_its_row_links_to_on_the_first_ask(browser_context, provider,
                                                                  tmp_path, monkeypatch):
    """A control whose own link is the document is fetched through the
    session before anything is pressed. A ZIP there was refused and the
    control then pressed, so the provider was asked twice."""
    site = module_of(WELLS, "site")
    monkeypatch.setattr(site, "is_safe_url", provider.ours)
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    provider.pages["/wells-row"] = ROW_LINK_PAGE
    pg = browser_context.new_page()
    try:
        pg.goto(provider.base + "/wells-row")
        staging = tmp_path / ".wellsfargo-downloads"
        site.set_download_dir(pg, staging)
        out = tmp_path / "Tax Documents" / "2026-01-31 Wells Fargo Form 1099-INT.pdf"
        provider.reset()
        # The title as discovery writes it, the kind and then the date, since
        # the download presses nothing for a title that names no kind.
        title = "%s - %s" % (site.KIND_TITLES["tax"], site._human_date(DATE))
        assert site.download_bill(pg, staging, DATE, out, title=title, trace=[])
        assert out.read_bytes() == provider.served[0]
        assert len(provider.served) == 1, "the provider was asked again"
        assert not list(staging.iterdir())
    finally:
        pg.close()


# -- the census ----------------------------------------------------------------------

def app_modules(app: Path):
    return [p for p in sorted(app.glob("*.py")) if not p.name.startswith("test_")]


def callee(node) -> str:
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    return name.lstrip("_")


def functions_named(app: Path, name: str):
    for path in app_modules(app):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                yield path, node


def opens_a_zip(app: Path) -> bool:
    """Its download_one opens a ZIP. Found by what it does, never a name."""
    for _path, fn in functions_named(app, "download_one"):
        names = {callee(c) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        if {"is_zip", "open_zip"} <= names:
            return True
    return False


def reachable(app: Path, start: str = "download_one") -> dict:
    """The app's own functions download_one can reach, by name, each with
    its definitions. A capture a module still carries and nothing calls is
    not what a run does. ADP carried the scaffold's whole _catch_pdf while
    it took every document from its statement services instead, and an
    earlier version of this census drove the dead copy and passed."""
    defs: dict = {}
    for path in app_modules(app):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore"))):
            if isinstance(node, ast.FunctionDef):
                defs.setdefault(node.name, []).append(node)
    seen: dict = {}
    todo = [start]
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen[name] = defs[name]
        for fn in defs[name]:
            for node in ast.walk(fn):
                # Called, or handed over to be called later, as a listener is.
                ref = node.attr if isinstance(node, ast.Attribute) else \
                    node.id if isinstance(node, ast.Name) else None
                if ref in defs:
                    todo.append(ref)
    return seen


# What taking a download the browser was handed looks like in an app's
# own code. Waiting for one, saving one, or reading the folder one lands in.
TAKES = {"expect_download", "take_download", "take_new_pdf", "save_download", "save_as"}


def takes_a_download(app: Path) -> bool:
    for fns in reachable(app).values():
        for fn in fns:
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                if callee(node) in TAKES:
                    return True
                if (callee(node) == "on" and node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "download"):
                    return True
    return False


def points_at_a_folder(app: Path) -> bool:
    return any(callee(c) == "set_download_dir"
               for path in app_modules(app)
               for c in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore")))
               if isinstance(c, ast.Call))


def hands_to_delivery(app: Path) -> bool:
    for path in app_modules(app):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for c in ast.walk(tree):
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "delivery"
                    and c.func.attr in ("deliver", "place", "render")):
                return True
    return False


def has_scaffold_capture(app: Path) -> bool:
    """The capture every scaffold app shares, _catch_pdf(page, el, label,
    out_path, trace, dl_dir)."""
    for _path, fn in functions_named(app, "_catch_pdf"):
        args = [a.arg for a in fn.args.args]
        return args[:6] == ["page", "el", "label", "out_path", "trace", "dl_dir"]
    return False


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")))
ZIP_APPS = [d for d in APPS if opens_a_zip(d)]
TAKING = [d for d in ZIP_APPS if takes_a_download(d)]
DELIVERED = [d for d in ZIP_APPS if d not in TAKING and hands_to_delivery(d)]
ASKING = [d for d in ZIP_APPS if d not in TAKING and d not in DELIVERED]

# Vanguard takes its download through capture.take_download since the
# download folder fix, but its own capture and its download gate keep a
# PDF only, so a ZIP is not filed there yet, the same open question as the
# apps whose ZIP branch cannot run. Strict, so it fails here the moment it
# passes, and the entry has to go.
PENDING = {
    "vanguard": "Vanguard's capture and download gate keep a PDF only, so a ZIP is not filed yet",
}


def test_the_apps_that_open_a_zip_are_found():
    """Not vacuous. These are the ones this was found in."""
    names = {d.name for d in ZIP_APPS}
    assert len(ZIP_APPS) >= 46
    assert {"wellsfargo", "adp", "etrade", "statefarm", "usaa", "citi", "tmobile"} <= names
    assert {"wellsfargo", "att", "newrez", "verizon", "chase", "amex"} <= {d.name for d in TAKING}
    assert {"tmobile", "navyfederal"} <= {d.name for d in DELIVERED}
    # ADP asks its statement services for every document.
    assert {"citi", "usaa", "fidelity", "adp"} <= {d.name for d in ASKING}
    assert sorted(TAKING + DELIVERED + ASKING) == ZIP_APPS


def test_what_is_reachable_follows_calls_and_listeners(tmp_path):
    """The reader under the census, on a made-up app."""
    app = tmp_path / "made"
    app.mkdir()
    (app / "made_site.py").write_text(
        "def download_bill(page):\n    return _catch(page)\n"
        "def _catch(page):\n    def on_download(d):\n        take_download(d)\n"
        "    page.on('download', on_download)\n"
        "def _never_called(page):\n    page.expect_download()\n", encoding="utf-8")
    (app / "made_docs.py").write_text(
        "class App:\n    def download_one(self, page):\n        site.download_bill(page)\n",
        encoding="utf-8")
    seen = set(reachable(app))
    assert {"download_one", "download_bill", "_catch", "on_download"} <= seen
    assert "_never_called" not in seen
    assert takes_a_download(app)
    (app / "made_docs.py").write_text(
        "class App:\n    def download_one(self, page):\n        site.fetch(page)\n",
        encoding="utf-8")
    assert not takes_a_download(app), "a capture nothing calls counted"


def download_folder_of(app: Path):
    """The attribute a docs module keeps its download folder in, and the
    folder's own name, as the module sets them."""
    for path in app_modules(app):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="ignore"))):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target, value = node.targets[0], node.value
            if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                    and target.value.id == "self" and isinstance(value, ast.BinOp)
                    and isinstance(value.op, ast.Div) and isinstance(value.right, ast.Constant)
                    and str(value.right.value).startswith(".")):
                return target.attr, value.right.value
    return None, None


def capture_entry(app: Path) -> str:
    """The site function download_one hands the output path to."""
    for _path, fn in functions_named(app, "download_one"):
        for c in ast.walk(fn):
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "site"
                    and any(isinstance(a, ast.Name) and a.id == "out_path"
                            for a in list(c.args) + [k.value for k in c.keywords])):
                return c.func.attr
    return ""


# -- how each one is driven ------------------------------------------------------

# Every app pressed the same way, the scaffold's own _catch_pdf on the link.
def _scaffold(site, pg, out_path, dl_dir, provider):
    return site._catch_pdf(pg, pg.locator("#zip"), "Download tax form", out_path, [], dl_dir)


CHASE_NAME = "Jan 31, 2026 Tax Form %s Saves document" % ACCOUNT
AMEX_PAGE = (b"<!doctype html><meta charset='utf-8'>"
             b"<button data-testid='statements/2026-01-31/download-button' "
             b"onclick=\"document.getElementById('dlg').hidden=false\">Download</button>"
             b"<div id='dlg' role='dialog' hidden><label>"
             b"<input type='radio' name='t' value='statement_pdf'>"
             b"PDF</label><a id='x-download-confirm-anchor' href='/zip'>Download</a></div>")
DOMINION_PAGE = (b"<!doctype html><meta charset='utf-8'><div class='MuiExpansionPanel-root'>"
                 b"<div class='MuiExpansionPanelSummary-root' aria-expanded='true'>"
                 b"Bill 1/31/2026</div><div><button onclick=\"location.href='/zip'\">"
                 b"Download Your Detailed Bill PDF</button></div></div>")
VERIZON_PAGE = b"""<!doctype html><meta charset='utf-8'>
<div role="combobox" id="c0" tabindex="0">Bill date</div>
<div role="listbox" id="l0" hidden><div role="option">January 31, 2026</div></div>
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
document.getElementById("getmybill").onclick = () => { location.href = "/zip"; };
</script>"""


class Drive:
    """How one app is driven. `page` is what the provider shows it.
    `wrap` stands in for the site function download_one calls, and does
    what that function does once it has found the control, with this
    app's own code. Without one, that function runs as it is. `stub` is
    what may not run here at all, the walk to a provider's own page."""

    def __init__(self, page=None, wrap=None, stub=None, doc=None):
        self.page, self.wrap = page, wrap
        self.stub = dict(stub or {})
        self.doc = dict(doc or {})


def _ally(site, pg, out_path, dl_dir, provider):
    return site._download_via_row(pg, pg.context, ACCOUNT, DATE, out_path)


def _usbank(site, pg, out_path, dl_dir, provider):
    return site._click_row_and_capture(pg, pg.context, ACCOUNT, DATE, out_path)


def _chase(site, pg, out_path, dl_dir, provider):
    return site._click_row_and_capture(pg, pg.context, ACCOUNT, DATE, out_path)


def _robinhood(site, pg, out_path, dl_dir, provider):
    return site._click_and_capture(pg, pg.locator("#zip"), "Tax form", out_path)


NAVIGATION = ("goto_documents", "ensure_statements", "ensure_documents", "expand_all",
              "scroll_full_page", "dismiss_timeout", "dismiss_overlay")

DRIVES = {
    "verizon": Drive(page=VERIZON_PAGE),
    "amex": Drive(page=AMEX_PAGE),
    "dominion": Drive(page=DOMINION_PAGE),
    "chase": Drive(page=("<!doctype html><meta charset='utf-8'><a id='row' href='/zip' "
                         "aria-label='%s'>%s</a>" % (CHASE_NAME, CHASE_NAME)).encode("utf-8"),
                   wrap=_chase),
    "ally": Drive(wrap=_ally, stub={"_find_row_control": lambda pg, *a, **k: pg.locator("#zip")}),
    "usbank": Drive(wrap=_usbank,
                    stub={"find_row_control": lambda pg, *a, **k: (pg.locator("#zip"), "Download")}),
    "robinhood": Drive(wrap=_robinhood, doc={"source_url": "{base}/"}),
    # Its own row walk reads WebForms pager pages, so only the finding of
    # the row stands in. The press, the three ways it watches and the save
    # are its own.
    "aafmaa": Drive(page=(b"<!doctype html><meta charset='utf-8'>"
                          b"<a id='view' href='/zip?row=aafmaa-0001'>View</a>"),
                    stub={"_fresh_view_target": lambda *a, **k: "aafmaa-0001",
                          "_clear_leftover_dialog": lambda *a, **k: None,
                          "_answer_view_disclosure": lambda *a, **k: False,
                          "on_documents_page": lambda *a, **k: True,
                          "showing_documents_list": lambda *a, **k: True}),
    "wealthfront": Drive(doc={"href": "{base}/zip"}),
}


def drive_of(app: Path):
    if app.name in DRIVES:
        return DRIVES[app.name]
    # The scaffold's own capture, but only where a run reaches it.
    if has_scaffold_capture(app) and "_catch_pdf" in reachable(app):
        return Drive(wrap=_scaffold)
    return None


def census(apps, failing=lambda d: True):
    """`apps` as parameters, the pending ones that fail here marked as
    known failures."""
    return [pytest.param(d, id=d.name, marks=pytest.mark.xfail(strict=True, reason=PENDING[d.name]))
            if d.name in PENDING and failing(d) else pytest.param(d, id=d.name) for d in apps]


@pytest.mark.parametrize("app", census(TAKING, failing=lambda d: drive_of(d) is None))
def test_every_app_that_takes_a_download_and_opens_a_zip_is_driven_here(app):
    """A new app that takes a download and opens a ZIP has to be driven by
    this file, with its own capture, before it can pass."""
    assert drive_of(app) is not None, (
        "%s takes a browser download and its download_one opens a ZIP, and nothing "
        "here drives it. Add it to DRIVES." % app.name)


@pytest.mark.parametrize("holding", ["one PDF", "two PDFs"])
@pytest.mark.parametrize("app", census(TAKING))
def test_a_zip_download_is_filed_as_the_pdf_inside_it(app, holding, provider, browser_context,
                                                      plain_context, tmp_path, monkeypatch):
    """The app's own capture in a real browser, then its own download_one.
    A ZIP holding one PDF ends with that PDF in the archive, the record
    completed, and no ZIP left anywhere, in the folder or out of it. A ZIP
    holding two ends with neither filed, the archive kept whole in Manual
    Review, and the record waiting for a person, since which one is this
    document cannot be told."""
    drive = drive_of(app)
    assert drive is not None
    docs = module_of(app, "docs")
    site = docs.site
    name = sys.modules["storage"].SPEC.provider
    provider.text = PRINTED.format(provider=name, account=ACCOUNT)
    path = "/" + app.name
    provider.pages[path] = drive.page or Provider.PAGE

    monkeypatch.setattr(site, "is_safe_url", provider.ours, raising=False)
    for step in NAVIGATION:
        if hasattr(site, step):
            monkeypatch.setattr(site, step, lambda *a, **k: True)
    for stubbed, fn in drive.stub.items():
        monkeypatch.setattr(site, stubbed, fn)

    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.chdir(install)
    config = json.loads((app / "config.example.json").read_text(encoding="utf-8"))
    config.update(owner="Example Holder", output_dir=".")
    (install / "config.json").write_text(json.dumps(config), encoding="utf-8")
    instance = docs.App(SimpleNamespace(config=str(install / "config.json")))
    instance.check_session = lambda p: None

    folder_attr, folder_name = download_folder_of(app)
    context = browser_context if points_at_a_folder(app) else plain_context
    pg = context.new_page()
    try:
        pg.goto(provider.base + path)
        staging = None
        if folder_attr:
            # As the app sets it up, relative to where it runs, which is
            # how every install gives it.
            staging = Path(".") / folder_name
            setattr(instance, folder_attr, staging)
            site.set_download_dir(pg, staging)

        if drive.wrap is not None:
            entry = capture_entry(app)
            real = getattr(site, entry)
            signature = inspect.signature(real)

            def stand_in(*args, **kwargs):
                # Bound to the real function first, so a call download_one
                # makes that the real one would refuse fails here too.
                bound = signature.bind(*args, **kwargs).arguments
                return drive.wrap(site, pg, Path(bound["out_path"]), bound.get("dl_dir"),
                                  provider)

            monkeypatch.setattr(site, entry, stand_in)

        doc_kwargs = {k: (v.format(base=provider.base) if isinstance(v, str) else v)
                      for k, v in drive.doc.items()}
        kind = (config.get("document_types") or ["Statement"])[0]
        doc = docs.Document(title="Tax form", category=kind, summary="Tax form",
                            date=DATE, date_text=DATE, account=ACCOUNT, **doc_kwargs)
        provider.reset()
        if holding == "two PDFs":
            provider.more = {"1099-DIV.pdf": text_pdf("another form " + provider.text, "div")}
        instance.download_one(pg, doc, "2026-01-31 %s Tax form.pdf" % name)
    finally:
        pg.close()

    from paperpull_core.models import State
    record = instance.progress.get(doc.key) or {}
    assert len(provider.served) == 1, "the provider was asked %d times" % len(provider.served)
    if staging is not None:
        assert not list((install / staging).iterdir()), "left in the download folder"
    if holding == "one PDF":
        assert record.get("state") == State.COMPLETED.value, (record.get("state"),
                                                              record.get("notes"))
        filed = install / record["pdf_path"]
        assert filed.read_bytes() == provider.inside[0], \
            "something other than the PDF inside was filed"
        assert not archives_in(install), archives_in(install)
        return
    assert record.get("state") == State.NEEDS_MANUAL_REVIEW.value, record.get("state")
    assert "held 2 PDFs" in (record.get("notes") or ""), record.get("notes")
    review = instance.paths.manual_review
    assert [p.read_bytes() for p in review.iterdir()] == [provider.served[0]], \
        "the archive was not kept whole in Manual Review"
    pdfs = [str(p.relative_to(install)) for p in install.rglob("*.pdf")]
    assert not pdfs, "a PDF was filed from an archive of two: %s" % pdfs
    archives = archives_in(install)
    assert len(archives) == 1 and Path(archives[0]).parent.name == Path(review).name, archives


def _row_link_fetches(app: Path) -> list:
    """Every fetch of a control's own link that download_bill makes, as
    (line, whether it asks for a ZIP too)."""
    out = []
    for _path, fn in functions_named(app, "download_bill"):
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and callee(c) == "fetch_pdf":
                zip_ok = any(k.arg == "zip_ok" and isinstance(k.value, ast.Constant)
                             and k.value.value is True for k in c.keywords)
                out.append((c.lineno, zip_ok))
    return out


def test_the_row_link_fetches_are_found():
    """Not vacuous. Ten scaffold apps fetch a control's own link first."""
    assert len([d for d in TAKING if _row_link_fetches(d)]) >= 10


@pytest.mark.parametrize("app", census([d for d in TAKING if _row_link_fetches(d)]))
def test_a_row_link_that_answers_with_a_zip_is_kept_on_the_first_ask(app):
    """The fetch a Wells Fargo row link makes, driven above, in every app
    that makes it. Refused, the control is pressed and the provider asked
    a second time for the same file."""
    assert all(zip_ok for _line, zip_ok in _row_link_fetches(app)), _row_link_fetches(app)
    for _path, fn in functions_named(app, "_fetch_pdf"):
        inner = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and callee(c) == "core_fetch_pdf"]
        assert inner and all(any(k.arg == "zip_ok" for k in c.keywords) for c in inner), (
            "%s's _fetch_pdf does not pass zip_ok on to the core" % app.name)


def test_delivery_takes_only_a_pdf(tmp_path):
    """Why the apps that take their documents through delivery cannot open
    a ZIP. Delivery checks a document's identity from its text before it
    ever reaches the archive, and a ZIP has none, so it is refused as not
    a PDF and nothing is left under the document's name."""
    from paperpull_core import delivery
    out = tmp_path / "2026-01-31 Tax Form.pdf"
    got = delivery.place(zipped({"1099.pdf": text_pdf("a form")}), out)
    assert got.outcome == delivery.NOT_A_PDF
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []
