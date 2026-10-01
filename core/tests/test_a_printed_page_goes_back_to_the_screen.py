"""A page printed to PDF goes back to the media it was in.

print_page_to_pdf switches the page to print media, so the print style
sheet is the one used, and afterwards it asked Playwright to undo that with
emulate_media(media=None). In Playwright for Python None means "leave it as
it is". Only the string "null" takes the emulation off. So the page stayed
in print media, through every navigation after it too, and every page an
app read after its first print was read in its printed layout. A block
shown only on screen dropped out of innerText and a block shown only on
paper appeared in it, so the second purchase of a run was read differently
from the first. Attached to a browser somebody opened, the tab on their
screen showed the printed layout from the first purchase to the end of the
run.

It cost Walmart its quantities. In saved runs the first purchase of a run
has a quantity on every item and the in-store purchases after it have
none, and a purchase read once each way has the same items, names, total
and date both times and differs only there.

In a real browser, because the emulation is the browser's, both launched
and attached the way the apps attach at home. Every page and purchase here
is invented.
"""
import ast
import importlib
import itertools
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser as browser_launcher
from paperpull_core import receipt_pdf

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

REPO = Path(__file__).resolve().parents[2]

PAGE = """<!doctype html><html><head><title>%(name)s</title><style>
@media print { .on-screen { display: none } }
@media screen { .on-paper { display: none } }
</style></head><body>
<p class="on-screen">Shown on screen %(name)s</p>
<p class="on-paper">Printed only %(name)s</p>
<p>Order 1000000001, an invented purchase.</p>
</body></html>"""

# A details page laid out the way Walmart's behaves. Its receipt is
# print-only, as the app's own notes say, and print media hides the screen
# layout, item tiles and all, which is what the quantities lost in saved
# runs point to. A tile's parts sit against each other with no text between
# them, as a page a script rendered has them, which is what makes a hidden
# tile's text run together. Every item and amount is invented.
WALMART = """<!doctype html><html><head><title>Purchase details</title><style>
@media print { .screen-layout { display: none } }
@media screen { .print-receipt { display: none } }
</style></head><body>
<div class="screen-layout">
  <h1>%(date)s purchase</h1>
  <p>Walmart Supercenter</p>
  <div data-testid="itemtile-stack"><span data-testid="productName">%(first)s</span><div>Qty %(q1)s</div><span data-testid="line-price">%(p1)s</span></div>
  <div data-testid="itemtile-stack"><span data-testid="productName">%(second)s</span><div>Qty %(q2)s</div><span data-testid="line-price">%(p2)s</span></div>
  <p>Total %(total)s</p>
</div>
<div class="print-receipt">
  <p>Walmart receipt</p>
  <p>%(date)s</p>
  <p>%(first)s %(p1)s</p>
  <p>%(second)s %(p2)s</p>
  <p>TOTAL %(total)s</p>
</div>
</body></html>"""

WALMART_PAGES = {
    "/walmart/1": {"date": "Feb 2, 2026", "first": "Invented Oat Cereal, 12 oz",
                   "q1": "2", "p1": "$7.38", "second": "Invented Dish Soap, 20 fl oz",
                   "q2": "1", "p2": "$3.07", "total": "$10.45"},
    "/walmart/2": {"date": "Feb 17, 2026", "first": "Invented Paper Towels, 6 Rolls",
                   "q1": "3", "p1": "$20.61", "second": "Invented Bananas, each",
                   "q2": "1", "p2": "$0.29", "total": "$20.90"},
}

# Every host name fails to resolve, so an attached browser reaches nothing
# but the server this file starts.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The page a tab of the attached browser is opened on. Once it has drawn it
# tells the server so, by the name its tab was opened with, never through the
# debugging port.
DRAWN = """<!doctype html><html><head><title>Ready</title></head><body><script>
fetch('/beacon/%(tab)s', {cache: 'no-store'}).catch(() => {});
</script></body></html>"""

# The names of the tabs whose page has drawn.
DRAWN_TABS = set()


class _Site(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/beacon/"):
            DRAWN_TABS.add(path[len("/beacon/"):])
            body = "ok"
        elif path.startswith("/drawn/"):
            body = DRAWN % {"tab": path[len("/drawn/"):]}
        elif path in WALMART_PAGES:
            body = WALMART % WALMART_PAGES[path]
        else:
            body = PAGE % {"name": path.strip("/") or "first"}
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def site():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def pw():
    """One Playwright for the module. Two cannot share a thread, and the
    attached test needs the same one the launched browser came from."""
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def media(page) -> str:
    return page.evaluate("() => matchMedia('print').matches ? 'print' : 'screen'")


def text(page) -> str:
    return page.locator("body").inner_text()


def test_the_page_is_on_screen_again_after_it_is_printed(site, page, tmp_path):
    page.goto(site + "/first")
    receipt_pdf.print_page_to_pdf(page, tmp_path / "r.pdf")
    assert media(page) == "screen"
    assert "Shown on screen first" in text(page)
    assert "Printed only" not in text(page)


def test_the_next_page_is_read_on_screen(site, page, tmp_path):
    """The emulation outlives a navigation, which is how a run's second
    purchase came to be read in print."""
    page.goto(site + "/first")
    receipt_pdf.print_page_to_pdf(page, tmp_path / "r.pdf")
    page.goto(site + "/second")
    assert media(page) == "screen"
    assert "Shown on screen second" in text(page)
    assert "Printed only" not in text(page)


def test_the_pdf_is_still_printed_in_print_media(site, page, tmp_path):
    """Putting the page back must not reach the print itself."""
    from pypdf import PdfReader
    page.goto(site + "/first")
    out = tmp_path / "r.pdf"
    receipt_pdf.print_page_to_pdf(page, out)
    printed = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "Printed only first" in printed
    assert "Shown on screen" not in printed


def test_a_page_already_in_print_media_is_left_in_it(site, page, tmp_path):
    """Home Depot switches the page to print itself, keeps only its
    receipt, prints, and then switches back. A caller gets back the media
    it had set."""
    page.goto(site + "/first")
    page.emulate_media(media="print")
    receipt_pdf.print_page_to_pdf(page, tmp_path / "r.pdf")
    assert media(page) == "print"


def test_a_print_that_fails_puts_the_page_back_too(site, page, tmp_path, monkeypatch):
    """The fallbacks after a failed print, and the purchases after it, read
    the page too."""
    page.goto(site + "/first")

    def no_session(self, *a, **k):
        raise RuntimeError("the print could not start")

    monkeypatch.setattr(type(page.context), "new_cdp_session", no_session)
    with pytest.raises(RuntimeError):
        receipt_pdf.print_page_to_pdf(page, tmp_path / "r.pdf")
    monkeypatch.undo()
    assert media(page) == "screen"


def _start_browser(exe, profile):
    """The browser as a program of its own with a debugging port, and its
    address, or None for the address when it opened no port.

    It starts with no window of its own, so its only tabs are the ones
    opened here. The blank tab a browser starts with was sometimes never
    listed by Playwright at all, and taking it raised IndexError on CI."""
    proc = subprocess.Popen(
        [exe, "--headless=new", "--remote-debugging-port=0",
         "--user-data-dir=%s" % profile, "--disable-extensions", "--disable-sync",
         "--no-first-run", "--no-default-browser-check", "--no-startup-window", NO_HOSTS],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port, deadline = "", time.monotonic() + 30
    while not port and time.monotonic() < deadline and proc.poll() is None:
        try:
            port = (profile / "DevToolsActivePort").read_text().split()[0]
        except (OSError, IndexError):
            time.sleep(0.1)
    if not port or not browser_launcher.wait_for_debug_port(port):
        return proc, None
    return proc, "http://127.0.0.1:%s" % port


def _page_targets(cdp_url):
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def _addresses(cdp_url):
    return [t.get("url") for t in _page_targets(cdp_url)]


def _close_tab(cdp_url, target_id):
    urllib.request.urlopen(cdp_url + "/json/close/" + target_id, timeout=10).read()


def _gone(cdp_url, target_id, seconds=10):
    """Until the tab is off the browser's list."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if all(t["id"] != target_id for t in _page_targets(cdp_url)):
            return
        time.sleep(0.1)


def _drawn(name, seconds) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if name in DRAWN_TABS:
            return True
        time.sleep(0.05)
    return False


def _only_tab_left(cdp_url, target_id, seconds) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if [t["id"] for t in _page_targets(cdp_url)] == [target_id]:
            return True
        time.sleep(0.1)
    return False


_TAB_NAMES = itertools.count(1)


def _open_drawn(cdp_url, site):
    """A tab the browser itself opens on a page of this file's server, once
    that page has drawn, as its id and address, or None.

    The first tab a fresh browser opens sometimes never sends a single
    request, for a minute and more. It was 3 fresh starts in 50 for this
    file, and about two in five in a count made for the Target test. A
    second tab always drew. So a tab that has not drawn in 10 seconds is
    closed, and another opened once it is gone, three at most."""
    for _attempt in range(3):
        name = "tab%d" % next(_TAB_NAMES)
        address = "%s/drawn/%s" % (site, name)
        request = urllib.request.Request(cdp_url + "/json/new?" + address, method="PUT")
        with urllib.request.urlopen(request, timeout=10) as r:
            tab = json.loads(r.read().decode("utf-8"))
        if _drawn(name, 10):
            return {"id": tab["id"], "address": address}
        _close_tab(cdp_url, tab["id"])
        _gone(cdp_url, tab["id"])
    return None


@pytest.fixture(scope="module")
def attached(pw, site, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    the way login.bat leaves one open. Its address, for connect_over_cdp.

    It is handed over with one tab, on a page of this file's server that
    has drawn. A browser that cannot get there is closed and another
    started, three at most, and a failure says what each one did."""
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    tried = []
    for _start in range(3):
        proc, url = _start_browser(found[0][1], tmp_path_factory.mktemp("attached-profile"))
        if url is None:
            proc.kill()
            proc.wait(timeout=15)
            pytest.skip("the browser opened no debugging port")
        ready = _open_drawn(url, site)
        if ready is not None and _only_tab_left(url, ready["id"], 10):
            break
        tried.append("%s, tabs %r" % ("no tab drew its page" if ready is None else
                                      "a tab never closed", _addresses(url)))
        proc.kill()
        proc.wait(timeout=15)
    else:
        pytest.fail("three fresh browsers in a row were not ready, %s" % "; ".join(tried))
    yield url
    try:
        pw.chromium.connect_over_cdp(url).new_browser_cdp_session().send("Browser.close")
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)


def test_the_tab_somebody_is_watching_goes_back_to_screen(site, pw, attached, tmp_path):
    """Target prints in the tab the person signed in with, and the others
    print in a tab of that person's browser. It showed the printed layout
    from the first purchase until the app let go of the browser.

    The tab is one the browser opened itself, as the person's was, and its
    page drew before anything attached."""
    own = _open_drawn(attached, site)
    if own is None:
        pytest.fail("the test's own tab never drew its page, tabs %r" % _addresses(attached))
    connected = pw.chromium.connect_over_cdp(attached)
    try:
        listed = connected.contexts[0].pages
        tab = next((p for p in listed if p.url == own["address"]), None)
        assert tab is not None, "Playwright does not list the tab, only %r" % [
            p.url for p in listed]
        tab.goto(site + "/first")
        receipt_pdf.print_page_to_pdf(tab, tmp_path / "r.pdf")
        assert media(tab) == "screen"
        tab.goto(site + "/second")
        assert media(tab) == "screen"
        assert "Printed only" not in text(tab)
    finally:
        connected.close()


def walmart_site():
    """Walmart's own site module, with this checkout's core under it."""
    app = REPO / "apps" / "walmart"
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("walmart_site")
    finally:
        sys.path.pop(0)


def test_walmart_reads_a_second_purchase_the_way_it_read_the_first(site, page, tmp_path):
    """Walmart's items are read from tiles on the screen layout. A tile the
    printed layout does not show gives back its text with nothing between
    its lines, and "Qty 2" run onto the item's own words no longer matches.
    Read by Walmart's own extract_details, with the print a run makes in
    between."""
    ws = walmart_site()
    from paperpull_core.models import IN_STORE, Purchase
    read = []
    for n, path in enumerate(("/walmart/1", "/walmart/2"), start=1):
        page.goto(site + path)
        purchase = Purchase(purchase_type=IN_STORE, order_number="1000000000000000%d" % n)
        ws.extract_details(page, purchase)
        receipt_pdf.print_page_to_pdf(page, tmp_path / ("%d.pdf" % n))
        read.append(purchase)
    for purchase, path in zip(read, ("/walmart/1", "/walmart/2")):
        shown = WALMART_PAGES[path]
        assert [(i.name, i.quantity, i.unit_price) for i in purchase.items] == [
            (shown["first"], shown["q1"], shown["p1"]),
            (shown["second"], shown["q2"], shown["p2"])], path
        assert purchase.total == shown["total"], path


# ---------------------------------------------------------------------------
# Nothing asks Playwright to put the media back with None
# ---------------------------------------------------------------------------

SKIP_DIRS = {".venv", "venv", "build", "dist", "node_modules", "__pycache__",
             ".git", "site-packages"}


def python_sources():
    for top in ("apps", "core", "gui", "tools"):
        for root, dirs, files in os.walk(REPO / top):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    yield Path(root) / f


def _is_none(node) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.IfExp):
        return _is_none(node.body) or _is_none(node.orelse)
    return False


def none_media_calls(tree):
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emulate_media"):
            continue
        given = [kw.value for kw in node.keywords if kw.arg == "media"]
        given += node.args[:1]
        if any(_is_none(v) for v in given):
            yield node.lineno


def test_the_census_reads_the_calls_it_is_looking_for():
    """So the check below is not passing on a tree it never read."""
    tree = ast.parse("page.emulate_media(media=None)\n"
                     "page.emulate_media(None)\n"
                     "page.emulate_media(media='print' if x else None)\n"
                     "page.emulate_media(media='null')\n"
                     "page.emulate_media(media='print' if x else 'null')\n"
                     "page.emulate_media(color_scheme='dark')\n")
    assert list(none_media_calls(tree)) == [1, 2, 3]
    assert any(p.name == "receipt_pdf.py" for p in python_sources())


def test_nothing_puts_the_media_back_with_none():
    """emulate_media(media=None) changes nothing in Playwright for Python,
    so a call written to put the page back leaves it in print."""
    found = []
    for path in python_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        found += ["%s:%d" % (path.relative_to(REPO).as_posix(), line)
                  for line in none_media_calls(tree)]
    assert not found, "media=None leaves the emulation as it is, use \"null\" in %s" % found
