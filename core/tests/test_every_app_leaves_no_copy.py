"""A download the browser saved into a folder is taken from there, once.

MEASURED 2026-09-29 on Chromium 149, 151 and 153 and Edge 154, attached
over DevTools and launched alike, headed and headless. Once
capture.set_download_dir has pointed the browser at a folder, the browser
writes each download there under the site's own name, and that file is
the only copy. Playwright still raises the download event, and its
save_as then writes an empty file without complaint.

Given the folder relative, as every install gave it with output_dir ".",
the browser accepted the setting and canceled every download instead.

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
    copies = [p.name for p in staging.iterdir()
              if p.is_file() and p.read_bytes() == provider.served[0]]
    assert not copies, "%s left the document in its download folder as %s" % (app, copies)


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
    """Every install passes its folder relative, output_dir being ".", and
    given a relative downloadPath Chromium accepts it and then cancels every
    download (measured 2026-09-29), so none of these apps' downloads had
    ever landed in a real install."""
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
    assert {d.name for d in SCAFFOLD} >= {"adp", "applecard", "att", "etrade", "golden1",
                                          "newrez", "sba", "smud", "statefarm",
                                          "verizonmobile", "wellsfargo"}


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


DRIVEN_ELSEWHERE_HERE = {"verizon", "vanguard"}


@pytest.mark.parametrize("app", FOLDER_APPS, ids=lambda d: d.name)
def test_every_app_that_points_the_browser_at_a_folder_is_driven_here(app):
    """A new app that points the browser at a folder has to be driven by
    this file, with its own capture, before it can pass."""
    assert app in SCAFFOLD or app.name in DRIVEN_ELSEWHERE_HERE, (
        "%s points the browser at a folder and nothing here drives its capture. "
        "Add a test like test_verizon_takes_its_bill_from_the_folder." % app.name)


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
