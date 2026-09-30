"""The print hook's marks are read by the names the hook sets.

The core's hook stands in for window.print() on every page a receipt app
opens. It keeps the document being printed and marks the page, and the
frame that printed, as having printed. Target and Walmart read those marks
in JavaScript of their own, by the names Target's own hook had used before
the apps moved onto the core in August. The core's hook never set those
names. So from then on Target's Print receipts never saw a print, waited
out fifteen seconds on every press and reset names nothing reads, and
neither app ever found the frame that printed.

So only the core names the marks, and an app asks receipt_pdf. The core's
own readers are held to the names its hook sets. And every app that looks
for the frame that printed is shown one, in a real browser, next to a frame
that only looks like a receipt.
"""
import ast
import importlib
import inspect
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import receipt_pdf

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "paperpull_core"

# A window property with Print in its name, the family the hook's marks
# belong to, whatever a copy of the hook called them.
PRINT_MARK = re.compile(r"__\w*Print\w*")

SKIPPED_DIRS = {".venv", "node_modules", "__pycache__", "tests", ".git"}


def python_files(root: Path):
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(folder) / name


def strings_in(path: Path):
    """(line, text) for every string in a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def set_by_the_hook() -> set:
    return set(re.findall(r"window\.(?:top\.)?(__\w+)\s*=",
                          receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT))


def test_nothing_outside_the_core_names_the_print_hook_s_marks():
    """Tests may describe the marks, so they are left out. On the code
    before this test it found three strings in target_site and one in
    walmart_site."""
    named = []
    for top in ("apps", "gui", "tools"):
        for path in python_files(REPO / top):
            for line, text in strings_in(path):
                for name in PRINT_MARK.findall(text):
                    named.append("%s:%d %s" % (path.relative_to(REPO).as_posix(), line, name))
    assert named == [], (
        "these read or reset the print hook's marks themselves, and a copy of a "
        "name drifts from the hook that sets it. Ask receipt_pdf instead "
        "(was_print_called, get_print_snapshot, clear_print_snapshot)\n"
        + "\n".join(named))


def test_the_core_reads_its_marks_by_the_names_its_hook_sets():
    sets = set_by_the_hook()
    assert len(sets) >= 2, "the hook's own marks were not found, so this proves nothing"
    for reader in (receipt_pdf.was_print_called, receipt_pdf.get_print_snapshot,
                   receipt_pdf.clear_print_snapshot):
        names = set(PRINT_MARK.findall(inspect.getsource(reader)))
        assert names, "%s names no mark, so this proves nothing about it" % reader.__name__
        assert names <= sets, "%s reads %s, which the hook never sets" % (
            reader.__name__, sorted(names - sets))
    stray = []
    for path in python_files(CORE):
        for line, text in strings_in(path):
            stray += ["%s:%d %s" % (path.name, line, n) for n in PRINT_MARK.findall(text)
                      if n not in sets]
    assert stray == [], "names the hook never sets\n" + "\n".join(stray)


# -- the frame that printed, in a real browser ---------------------------------

def looks_for_the_frame(app: Path) -> bool:
    """Whether this app's find_printing_frame does more than say None.
    Most of them do only that, since their receipts never print from a
    frame. Asked of the function's body, not of the app's name."""
    tree = ast.parse((app / ("%s_site.py" % app.name)).read_text(
        encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "find_printing_frame":
            body = [n for n in node.body
                    if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            only_none = (len(body) == 1 and isinstance(body[0], ast.Return)
                         and (body[0].value is None
                              or (isinstance(body[0].value, ast.Constant)
                                  and body[0].value.value is None)))
            return not only_none
    return False


LOOKING = sorted(d for d in (REPO / "apps").iterdir()
                 if d.is_dir() and (d / ("%s_site.py" % d.name)).exists()
                 and looks_for_the_frame(d))


def test_some_app_looks_for_the_frame_that_printed():
    """Otherwise the browser test below has nothing to ask, and passes
    whatever the apps do."""
    assert LOOKING


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def invented_receipt(number: str, what: str) -> str:
    rows = "".join("<p>Invented %s line %d</p>" % (what, i) for i in range(1, 7))
    return "<h1>Store receipt</h1><p>Order number %s</p>%s" % (number, rows)


# The first frame only looks like a receipt, and never prints. The second
# prints as it loads and stays on the page. Both are invented.
FRAMES = """<!doctype html><html><body><main><h1>Receipts</h1>
<iframe name="looks" srcdoc="%s"></iframe>
<iframe name="printed" srcdoc="%s&lt;script&gt;print()&lt;/script&gt;"></iframe>
</main></body></html>""" % (invented_receipt("902000606", "decoy"),
                             invented_receipt("902000707", "printed"))

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"


class _Page(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        data = FRAMES.encode("utf-8") if self.path.startswith("/receipts") else b""
        self.send_response(200 if data else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def printed_page():
    """A page on which a frame printed, the hook installed as the apps
    install it, before anything was loaded."""
    sync_api = pytest.importorskip("playwright.sync_api", reason="needs a browser")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        driver = sync_api.sync_playwright().start()
        browser = driver.chromium.launch(headless=True, args=[NO_HOSTS])
    except Exception as e:
        httpd.shutdown()
        pytest.skip("no browser to drive: %s" % e)
    context = browser.new_context()
    context.add_init_script(receipt_pdf.PRINT_SUPPRESS_INIT_SCRIPT)
    page = context.new_page()
    page.goto("http://127.0.0.1:%d/receipts" % httpd.server_address[1])
    page.wait_for_function("""() => {
        const f = [...document.querySelectorAll('iframe')].find(x => x.name === 'printed');
        return f && f.contentWindow.document.readyState === 'complete';
    }""")
    yield page
    browser.close()
    driver.stop()
    httpd.shutdown()
    httpd.server_close()


@pytest.mark.parametrize("app", LOOKING, ids=lambda d: d.name)
def test_the_frame_that_printed_is_found_before_one_that_only_looks_like_a_receipt(
        app, printed_page):
    marked = [f.name for f in printed_page.frames
              if f != printed_page.main_frame and receipt_pdf.was_print_called(f)]
    assert marked == ["printed"], "the page is as described, only one frame printed"
    site = site_of(app)
    started = time.monotonic()
    frame = site.find_printing_frame(printed_page, wait_ms=2000)
    took = time.monotonic() - started
    assert frame is not None and frame.name == "printed", \
        "%s took the frame %r" % (app.name, frame.name if frame else None)
    assert took < 1.5, "%s looked for %.1f s for a frame that had printed" % (app.name, took)
