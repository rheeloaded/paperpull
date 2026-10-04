"""Discovery reads each of the orders page's two tabs once, and only once its
rows show, against made-up Meijer pages in a real browser (#42).

The page opens on Online Orders, and the In-Store Receipts rows come only
after that tab is pressed. Discovery pressed it, waited the press's own
pause of two and a half seconds and read whatever was there, so rows that
came later were read as none, and the Online tab's "You haven't placed any
orders yet" was then taken to say that both tabs were empty.

A page can also keep a tab's rows when the other tab is shown, hidden
rather than removed. Chromium hands back the words of a row it does not
draw with their lines run together, "In-Store: 06/11/202618 Example Road",
where no date can be read, so every store receipt was read once more from
behind the Online tab and recorded twice, the second time with no date.
Which of the two Meijer does is not known. The tester's runs read no rows
on the Online tab right after reading the In-Store ones, so that page did
not keep them where they could be read, and both kinds of page are played
here.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page comes from a server on this machine and the
browser resolves no host name, so nothing reaches Meijer. Every store, date
and amount is invented.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_receipts as app_mod
import meijer_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

ORDERS = "/shopping/orders.html"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# The site's own header, with an amount in it, on every page it draws.
HEADER = ("<header><a href='/shopping/account.html'>Account</a>"
          "<span>mPerks savings this year $8.15</span></header>")


def store_row(date, amount, items):
    return ("<li class='order-card'><div class='date'>In-Store: %s</div><div>18 Example Road</div>"
            "<div class='totals'><span>%s</span>&nbsp;&nbsp;%d items</div>"
            "<a href='javascript:void(0)'>view receipt pdf</a></li>" % (date, amount, items))


STORE_ROWS = store_row("06/11/2026", "$23.41", 7) + store_row("06/03/2026", "$58.07", 12)
BOTH_RECEIPTS = [("2026-06-03", "$58.07"), ("2026-06-11", "$23.41")]

NO_ONLINE_ORDERS = "<p>You haven't placed any orders yet</p>"
ONLINE_ORDER = ("<ul><li class='order-card'><div>Pickup</div><div>Jun 9, 2026</div>"
                "<div>Order 4417</div><div>$31.50</div></li></ul>")


def orders_page(store_rows, kept=False, late_ms=0, online=NO_ONLINE_ORDERS):
    """The orders page, open on Online Orders.

    Its In-Store rows are drawn `late_ms` after that tab is pressed, never
    when it is None, and taken away when the other tab is pressed. Or, when
    `kept`, they are in the page from the start and hidden along with their
    tab, which is the page round four and round six play."""
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
            "<h1>Orders and Receipts</h1><div role='tablist'>"
            "<a role='tab' href='#' onclick=\"show('online');return false\">Online Orders</a>"
            "<a role='tab' href='#' onclick=\"show('store');return false\">In-Store Receipts</a></div>"
            "<div id='online'>%s</div>"
            "<div id='store' style='display:none'><ul id='rows'>%s</ul></div>"
            "<script>const ROWS = %s, LATE = %s, KEPT = %s; let timer = null;"
            "function show(which) {"
            " document.getElementById('online').style.display = which === 'online' ? '' : 'none';"
            " document.getElementById('store').style.display = which === 'store' ? '' : 'none';"
            " if (KEPT) return;"
            " clearTimeout(timer);"
            " const list = document.getElementById('rows');"
            " list.innerHTML = '';"
            " if (which === 'store' && LATE !== null) timer = setTimeout(() => { list.innerHTML = ROWS; }, LATE); }"
            "</script></main></body></html>"
            % (HEADER, online, store_rows if kept else "", json.dumps(store_rows),
               "null" if late_ms is None else int(late_ms), "true" if kept else "false"))


# A page that lays its receipts out with no tabs at all, one of them kept on
# the page and not drawn, the way a section folded away would be.
UNTABBED = ("<!doctype html><html><head><title>Your Orders</title></head><body>%s<main>"
            "<h1>Orders and Receipts</h1><ul>%s</ul><div style='display:none'><ul>%s</ul></div>"
            "</main></body></html>" % (HEADER, store_row("06/11/2026", "$23.41", 7),
                                       store_row("06/03/2026", "$58.07", 12)))


class FakeMeijer:
    """What the made-up site shows, set by each test. `later` is what a
    page past the first answers, and the first page's own again when it is
    None."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = orders_page(STORE_ROWS)
        self.later = None
        self.seen = []


SITE = FakeMeijer()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(self.path)
        if parts.path == ORDERS:
            page_no = int((parse_qs(parts.query).get("page") or ["1"])[0])
            body = SITE.later if (page_no > 1 and SITE.later is not None) else SITE.orders
        elif parts.path == "/":
            body = "<!doctype html><html><head><title>Meijer</title></head><body><h1>Meijer</h1></body></html>"
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
def browser_exe():
    """Playwright's own Chromium, found the way the app finds it in its
    bundled mode, so it is never the person's everyday browser."""
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation. The app works in a tab it opens
    for itself, so the tab that drew can stay where it is."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_meijer(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short. A tab's rows are given three seconds here, the thirty
    a purchase's tab is given at home cut down to keep the suite quick."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + ORDERS)
    monkeypatch.setattr(site, "ORDER_CANDIDATES", [server + ORDERS])
    monkeypatch.setitem(site.URLS, "orders", server + ORDERS)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    monkeypatch.setattr(site, "LIST_WAIT_MS", 3000, raising=False)
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def printed(capsys):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def discover(tmp_path, cdp_url, capsys):
    assert app_mod.main(["--discover", "--config", str(config_for(tmp_path, cdp_url))]) == 0
    return printed(capsys)


def stopped_discovery(tmp_path, cdp_url, capsys):
    """Discovery, which has to stop rather than finish. Leaving on
    SystemExit with the exception in flight is what the core reports to the
    panel as stopped, rather than as a clean finish."""
    with pytest.raises(SystemExit) as stopped:
        app_mod.main(["--discover", "--config", str(config_for(tmp_path, cdp_url))])
    out = printed(capsys)
    assert stopped.value.code == 0, out
    return out


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def found(tmp_path):
    """Each purchase discovery recorded, by its date and total."""
    return sorted((r["purchase_date"], r["total"]) for r in known(tmp_path).values())


# -- a tab hidden rather than removed ----------------------------------------------

def test_a_tab_hidden_rather_than_emptied_is_read_once(attached, tmp_path, capsys):
    """Each store receipt once, with its date. The page kept the In-Store
    rows while the Online tab was shown, and they were read again from
    there with no date, four purchases for two receipts."""
    SITE.orders = orders_page(STORE_ROWS, kept=True)
    discover(tmp_path, attached, capsys)

    assert found(tmp_path) == BOTH_RECEIPTS


def test_a_later_page_reads_only_what_it_shows(attached, tmp_path, capsys):
    """The pages after the first are read as they open, on the Online tab,
    and a later page that keeps the In-Store rows hidden there adds nothing."""
    SITE.later = orders_page(STORE_ROWS, kept=True)
    discover(tmp_path, attached, capsys)

    assert found(tmp_path) == BOTH_RECEIPTS
    assert any("page=2" in p for p in SITE.seen), "a later page was asked for"


def test_a_page_without_tabs_reads_only_the_rows_it_draws(attached, tmp_path, capsys):
    """With no tab to press, the page is read as it stands, and that used
    to take in a receipt kept on the page out of sight as well."""
    SITE.orders = UNTABBED
    discover(tmp_path, attached, capsys)

    assert found(tmp_path) == [("2026-06-11", "$23.41")]


def test_an_undated_copy_an_earlier_run_recorded_is_dropped(attached, tmp_path, capsys):
    """What the old reading left in discovery.json goes at the next
    discovery, since its row is no longer read, and nothing downloaded is
    ever dropped. The copies are made here from the words Chromium hands
    back for the hidden rows, as the old reading made them."""
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            pg = browser.new_page()
            pg.set_content(orders_page(STORE_ROWS, kept=True))
            hidden = [r for r in pg.evaluate(site._COLLECT_ROWS_JS, site.FALLBACK["row"])
                      if not r.get("shown")]
        finally:
            browser.close()
    copies = [site.card_to_purchase(site.RawCard(text=r["text"], links=r["links"])) for r in hidden]
    assert len(copies) == 2 and not any(p.purchase_date for p in copies), [p.purchase_date for p in copies]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "discovery.json").write_text(json.dumps(
        {p.key: {**p.to_dict(), "state": "Discovered"} for p in copies}), encoding="utf-8")

    SITE.orders = orders_page(STORE_ROWS, kept=True)
    discover(tmp_path, attached, capsys)

    assert found(tmp_path) == BOTH_RECEIPTS


# -- rows that come late, or never ---------------------------------------------------

def test_rows_that_come_after_the_press_pause_are_waited_for(attached, tmp_path, capsys,
                                                             monkeypatch):
    """The rows come six seconds after the press, past its own pause of two
    and a half, and inside the time a purchase's tab is given."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 15000, raising=False)
    SITE.orders = orders_page(STORE_ROWS, late_ms=6000)
    out = discover(tmp_path, attached, capsys)

    assert found(tmp_path) == BOTH_RECEIPTS, out
    assert "no orders on either tab" not in out


def test_rows_that_never_come_are_not_read_as_none(attached, tmp_path, capsys):
    """The Online tab says it has no orders, and the In-Store tab shows
    nothing. What the In-Store tab says when there are no receipts has not
    been seen, so the run stops there rather than say there is nothing."""
    SITE.orders = orders_page(STORE_ROWS, late_ms=None)
    out = stopped_discovery(tmp_path, attached, capsys)

    assert "no orders on either tab" not in out and "Discovery complete" not in out, out
    assert "Nothing showed on Meijer's In-Store Receipts tab within 3 seconds" in out, out
    assert "Look at the browser window" in out
    assert not known(tmp_path)
    assert list((tmp_path / "out" / "Diagnostics").glob("failure-*.json")), \
        "the page as it was is kept for whoever repairs this"


def test_online_orders_are_kept_when_the_in_store_rows_never_come(attached, tmp_path, capsys):
    """One tab's rows are a list, so the run goes on with them, and says
    the other tab showed nothing and was not looked at."""
    SITE.orders = orders_page(STORE_ROWS, late_ms=None, online=ONLINE_ORDER)
    out = discover(tmp_path, attached, capsys)

    assert found(tmp_path) == [("2026-06-09", "$31.50")]
    assert "Nothing showed on Meijer's In-Store Receipts tab" in out, out
    assert "The next run looks again" in out
    assert "Discovery complete" in out


def test_with_somebody_there_it_asks_and_looks_again(attached, tmp_path, capsys, monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say the page shows their receipts it opens the orders page
    again and reads both tabs. Past a few questions they give up with
    Ctrl+C, so a loop that asks forever fails here rather than hanging."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.orders = orders_page(STORE_ROWS)
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    SITE.orders = orders_page(STORE_ROWS, late_ms=None)
    discover(tmp_path, attached, capsys)

    assert len(asked) == 1 and "shows your receipts" in asked[0], asked
    assert found(tmp_path) == BOTH_RECEIPTS
