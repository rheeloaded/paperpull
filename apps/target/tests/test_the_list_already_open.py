"""A run in a real browser attached the way it is at home, against a made-up
Target orders page (#48).

A tester's report on 0.41.0 counted four page loads between pressing Pilot
and Target's press and hold check. The first of them loaded again the very
orders page Login had opened a moment before. And while the app was attached,
every page it opened carried a replaced window.print and two globals of this
app's own, which any script on the page can see, the order list included,
where nothing is ever printed.

The browser is started here as a program of its own with a debugging port,
the way Login leaves one open. The orders page is opened in it through the
browser's own debugging address, so nothing is attached to that page and
nobody has touched it, like the window Login opens. The app then attaches
exactly as it does at home. Every page comes from a server on this machine
and the browser resolves no host name, so nothing reaches Target. Every order
number, store, date and amount is invented.
"""
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts as app_mod
import target_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core.models import IN_STORE, ONLINE

APP_DIR = Path(__file__).resolve().parents[1]

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# Target's own check, the way the tester met it, drawn over the list.
CHECK = ("<div id='check'><h1>Quick verification</h1>"
         "<p>Press &amp; hold to confirm you're not a bot.</p>"
         "<iframe srcdoc=\"<button>Press &amp; Hold</button>\"></iframe></div>")

# Each page says what it looks like to the server, never through the
# debugging port, so what is measured is the page's own view of itself.
REPORT = """<script>
const load = Math.random().toString(36).slice(2, 10);
function report() {
  const own = /\\[native code\\]/.test(Function.prototype.toString.call(window.print));
  const ours = Object.getOwnPropertyNames(window).filter(n => /^__paperpull/.test(n));
  fetch('/beacon?page=PAGE&load=' + load + '&native_print=' + own + '&globals=' + ours.length,
        {cache: 'no-store'}).catch(() => {});
}
report();
setInterval(report, 200);
</script>"""

# Online is the tab the page opens on, as on Target. Both tabs keep the
# address /orders, as the log of a real run shows Target's own tabs doing.
ORDERS = """<!doctype html><html><head><title>Orders</title></head><body><main>
<div role="tablist">
  <button role="tab" data-test="tabOnline">Online</button>
  <button role="tab" data-test="tabInstore">In-store</button>
</div>
<button id="filter">Filter</button>
<div id="cards"></div>
</main>CHECK
<script>
const ONLINE = [["1020001", "Sep 1, 2026", "$12.34"], ["1020002", "Aug 20, 2026", "$45.60"],
                ["1020003", "Aug 2, 2026", "$7.89"]];
const INSTORE = [["0000-1111-2222-3333", "Aug 30, 2026", "$5.67"],
                 ["0000-1111-2222-4444", "Jul 14, 2026", "$23.45"]];
function show(kind) {
  const list = document.getElementById('cards');
  list.innerHTML = '';
  for (const [id, day, total] of (kind === 'online' ? ONLINE : INSTORE)) {
    const a = document.createElement('a');
    if (kind === 'online') {
      a.setAttribute('data-test', 'order-details-link');
      a.href = '/orders/' + id;
      a.innerHTML = '<div>Order #' + id + '</div><div>Placed ' + day + '</div><div>' + total +
                    '</div><div>Delivered</div>';
    } else {
      a.setAttribute('data-test', 'store-order-details-link');
      a.href = '/orders/stores/' + id;
      a.innerHTML = '<div>Store trip at Example Town</div><div>' + day + '</div><div>' + total +
                    '</div>';
    }
    list.appendChild(a);
  }
}
document.querySelector('[data-test=tabOnline]').onclick = () => show('online');
document.querySelector('[data-test=tabInstore]').onclick = () => show('instore');
if (DRAWN_AT_ONCE) show('online');
</script>""" + REPORT.replace("PAGE", "orders") + "</body></html>"

DETAILS = ("<!doctype html><html><head><title>Order</title></head><body>"
           "<h1>Order details</h1>" + REPORT.replace("PAGE", "details") + "</body></html>")


class FakeTarget:
    """What the made-up site shows, set by each test, and what it saw."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.check = False
        self.drawn_at_once = True
        self.seen = []
        self.beacons = []

    def loads_of_orders(self) -> int:
        return sum(1 for path in self.seen if path == "/orders")

    def loads(self, page="orders") -> set:
        return {b["load"] for b in self.beacons if b["page"] == page}


SITE = FakeTarget()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, and every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(parts.path)
        if parts.path == "/orders":
            body = ORDERS.replace("CHECK", CHECK if SITE.check else "").replace(
                "DRAWN_AT_ONCE", "true" if SITE.drawn_at_once else "false")
        elif parts.path == "/details":
            body = DETAILS
        elif parts.path == "/beacon":
            q = parse_qs(parts.query)
            SITE.beacons.append({k: q.get(k, [""])[0]
                                 for k in ("page", "load", "native_print", "globals")})
            body = "ok"
        else:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def attached(tmp_path_factory):
    """Playwright's own Chromium, never the person's everyday browser,
    started as a program of its own with a debugging port, which is what the
    app attaches to at home. Its address, for cdp_url.

    It starts on a blank page. Started straight on a page from this server,
    headless Chromium would not let Playwright attach to it at all."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    profile = tmp_path_factory.mktemp("attached-profile")
    proc = subprocess.Popen(
        [found[0][1], "--headless=new", "--remote-debugging-port=0",
         "--user-data-dir=%s" % profile, "--disable-extensions", "--disable-sync",
         "--no-first-run", "--no-default-browser-check", NO_HOSTS, "about:blank"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port, deadline = "", time.monotonic() + 30
    while not port and time.monotonic() < deadline and proc.poll() is None:
        try:
            port = (profile / "DevToolsActivePort").read_text().split()[0]
        except (OSError, IndexError):
            time.sleep(0.1)
    if not port or not browser_launcher.wait_for_debug_port(port):
        proc.kill()
        pytest.skip("the browser opened no debugging port")
    url = "http://127.0.0.1:%s" % port
    yield url
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.connect_over_cdp(url).new_browser_cdp_session().send("Browser.close")
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)


@pytest.fixture(autouse=True)
def fake_target(server, monkeypatch):
    SITE.reset()
    monkeypatch.setitem(site.URLS, "orders", server + "/orders")
    monkeypatch.setitem(site.URLS, "home", server + "/")
    return SITE


def _page_targets(cdp_url):
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8")) if t.get("type") == "page"]


def open_as_login_does(cdp_url, address):
    """A tab on the address and no other, opened by the browser itself, the
    way Login's window is. Returns once the page has drawn its list."""
    earlier = SITE.loads()
    others = _page_targets(cdp_url)
    request = urllib.request.Request(cdp_url + "/json/new?" + address, method="PUT")
    urllib.request.urlopen(request, timeout=10).read()
    for target in others:
        urllib.request.urlopen(cdp_url + "/json/close/" + target["id"], timeout=10).read()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if SITE.loads() - earlier:
            return
        time.sleep(0.05)
    pytest.fail("the orders page never drew its list")


def press(cdp_url, name):
    """The person presses a control on the page, and nothing stays attached."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.connect_over_cdp(cdp_url).contexts[0].pages[0]
        page.get_by_role("button", name=name).click()


def config_for(tmp_path, cdp_url):
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                "profile_dir": str(tmp_path / "unused-profile"), "cdp_url": cdp_url,
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    kinds = [r.get("purchase_type") for r in data.values() if isinstance(r, dict)]
    return kinds.count(ONLINE), kinds.count(IN_STORE)


def printed(capsys):
    return " ".join(capsys.readouterr().out.split())


# -- the page Login opened ----------------------------------------------------------

def test_discover_reads_the_orders_page_login_opened_without_loading_it_again(
        attached, server, tmp_path):
    open_as_login_does(attached, server + "/orders")
    before = SITE.loads_of_orders()

    assert app_mod.main(["--discover", "--config", config_for(tmp_path, attached)]) == 0

    assert SITE.loads_of_orders() - before == 1, \
        "only the in-store half loads the orders page again"
    assert known(tmp_path) == (3, 2), "and the whole history is still read"


def test_the_order_list_is_left_as_target_served_it(attached, server, tmp_path):
    """Nothing is printed from the order list, so nothing of this app's is
    put on it. It used to carry a replaced window.print and two globals."""
    open_as_login_does(attached, server + "/orders")

    assert app_mod.main(["--discover", "--config", config_for(tmp_path, attached)]) == 0

    seen = [b for b in SITE.beacons if b["page"] == "orders"]
    assert len(SITE.loads()) >= 2, "the in-store half loaded the page while attached"
    changed = [b for b in seen if b["native_print"] != "true" or b["globals"] != "0"]
    assert not changed, "the order list was changed by this app: %r" % changed[:2]


def test_the_purchases_are_still_opened_with_the_print_hook(attached, server, tmp_path,
                                                          monkeypatch):
    """A receipt is taken when Target calls print(), so the pages the
    purchases are read on still have the hook when they open."""
    open_as_login_does(attached, server + "/orders")
    hooked = []

    def open_purchase(self, page, purchase, dry_run=False):
        page.goto(server + "/details", wait_until="domcontentloaded")
        hooked.append(page.evaluate("typeof window.__paperpullPrintCalled"))

    monkeypatch.setattr(app_mod.App, "process_one", open_purchase)
    assert app_mod.main(["--pilot-online", "--config", config_for(tmp_path, attached)]) == 0

    assert hooked == ["boolean"] * 3, hooked


def test_a_check_drawn_over_that_list_stops_the_run_where_it_is(attached, server, tmp_path,
                                                                capsys):
    """The check is the person's to answer, in the page as it is. The run
    used to load the orders page again under it before it stopped."""
    SITE.check = True
    open_as_login_does(attached, server + "/orders")
    before = SITE.loads_of_orders()

    with pytest.raises(SystemExit) as stop:
        app_mod.main(["--discover", "--config", config_for(tmp_path, attached)])

    out = printed(capsys)
    assert stop.value.code == 0, out
    assert "reload the page first" in out, out
    assert SITE.loads_of_orders() == before, "the page was loaded again under the check"
    assert known(tmp_path) == (0, 0), "nothing is read from under the check"


# -- anything less certain is loaded again, as before --------------------------------

def _stale(cdp_url, server, monkeypatch):
    open_as_login_does(cdp_url, server + "/orders")
    monkeypatch.setattr(site, "FRESH_LIST_MS", 0, raising=False)


def _pressed_by_the_person(cdp_url, server, monkeypatch):
    # A filter chosen by hand leaves the address as it is.
    open_as_login_does(cdp_url, server + "/orders")
    press(cdp_url, "Filter")


def _narrowed_by_its_address(cdp_url, server, monkeypatch):
    open_as_login_does(cdp_url, server + "/orders?view=recent")


def _with_no_list_on_it_yet(cdp_url, server, monkeypatch):
    # Only the list shows what a page is. One that has not drawn it is no list.
    SITE.drawn_at_once = False
    open_as_login_does(cdp_url, server + "/orders")


@pytest.mark.parametrize("left", [_stale, _pressed_by_the_person, _narrowed_by_its_address,
                                  _with_no_list_on_it_yet],
                         ids=["loaded long ago", "pressed by the person",
                              "narrowed by its address", "with no list on it yet"])
def test_an_orders_page_that_is_not_plainly_the_fresh_list_is_loaded_again(
        attached, server, tmp_path, monkeypatch, left):
    left(attached, server, monkeypatch)
    before = SITE.loads_of_orders()

    assert app_mod.main(["--discover", "--config", config_for(tmp_path, attached)]) == 0

    assert SITE.loads_of_orders() - before == 2, "each half loads the orders page, as before"
    assert known(tmp_path) == (3, 2)


def test_a_run_for_the_other_kind_loads_the_orders_page_again(attached, server, tmp_path,
                                                              monkeypatch):
    """The page opens on the online list. An in-store run cannot read that."""
    open_as_login_does(attached, server + "/orders")
    before = SITE.loads_of_orders()
    monkeypatch.setattr(app_mod.App, "process_purchases",
                        lambda self, purchases, dry_run=False: None)

    assert app_mod.main(["--pilot-instore", "--config", config_for(tmp_path, attached)]) == 0

    assert SITE.loads_of_orders() - before == 1
    assert known(tmp_path) == (0, 2)


# -- the address itself ----------------------------------------------------------------

@pytest.mark.parametrize("url, same", [
    ("https://shop.example.test/orders", True),
    ("https://shop.example.test/orders/", True),
    ("https://SHOP.example.test/orders", True),
    ("https://shop.example.test/orders?view=recent", False),
    ("https://shop.example.test/orders#instore", False),
    ("https://shop.example.test/orders/1020001", False),
    ("http://shop.example.test/orders", False),
    ("https://shop.example.test.other.test/orders", False),
    ("https://other.test/orders", False),
    ("", False),
])
def test_only_the_orders_address_itself_counts(monkeypatch, url, same):
    monkeypatch.setitem(site.URLS, "orders", "https://shop.example.test/orders")
    assert site._is_orders_address(url) is same
