"""A year whose order list runs past the most this app reads of one year.

Discover reads each year's order list YEAR_PAGES pages at most. A year that
still shows a next page there was not read to its end, so the run may not
finish as though the list were whole. It stopped at once, inside Discover,
before anything was downloaded, and every run after read the list again and
stopped at the same place, so an account with such a year downloaded nothing
on any run. Before the limit was raised to 500 such an account was read 60
pages a year and got the rest, missing that year's older orders with no
word.

So the run reads on past that year, downloads every order it did read, and
stops at its end, leaving the list noted as one that stopped and a failure
file for whoever repairs it. A run after that reads the list again, takes
what is new and stops at the same place, and once the year fits the run
finishes clean. An account with no such year runs as it always did.

The pages are served from this machine to a browser the app attaches to
over CDP, the way it does at home, as in test_a_list_that_never_came.py.
The limit is lowered to two pages and each page holds one order, so the
runs stay short. Every order number and amount is invented.
"""
import json
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
import amazon_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
HISTORY = "/gp/css/order-history"
PRINT = "/gp/css/summary/print.html"

Y0 = date.today().year
Y1, Y2, Y3, Y4 = Y0 - 1, Y0 - 2, Y0 - 3, Y0 - 4

# Each order, the year and day it was placed. January 1 of this year has
# always gone by when a run asks.
A1 = "114-0000000-0000001"
A2 = "114-0000000-0000002"
L1 = "114-0000000-0000011"
L2 = "114-0000000-0000012"
L3 = "114-0000000-0000013"
O1 = "114-0000000-0000021"
PLACED = {A1: (Y0, "January 1"), A2: (Y0, "January 1"), L1: (Y1, "December 1"),
          L2: (Y1, "November 2"), L3: (Y1, "October 3"), O1: (Y2, "June 5")}

CARD = ('<div class="order-card js-order-card"><div>Order placed</div><div>%s, %d</div>'
        "<div>Total</div><div>$12.34</div><div>Order # %s</div>"
        '<a href="/gp/your-account/order-details?orderID=%s">View order details</a></div>')
NEXT = '<ul class="a-pagination"><li class="a-last"><a href="%s">Next</a></li></ul>'


def card(order):
    year, day = PLACED[order]
    return CARD % (day, year, order, order)


def orders_page(count, cards=""):
    """The Your Orders page as Amazon draws it, its own count in the period
    menu's label and the orders under it."""
    return """<!doctype html><html><head><title>Your Orders</title></head><body>
<section class="your-orders-content-container js-yo-container">
<h1>Your Orders</h1>
<form class="js-time-filter-form" action="/your-orders/orders">
<label class="a-form-label time-filter__label" for="time-filter">
<span class="num-orders">%d orders</span> placed in</label>
<select id="time-filter" name="timeFilter"><option>past 3 months</option></select>
</form>
%s
</section></body></html>""" % (count, cards)


EMPTY = orders_page(0)


def summary_page(order):
    """The printable summary, laid out the way the app reads it."""
    year, day = PLACED[order]
    return ("<!doctype html><html><head><title>Amazon.com - Order %s</title></head><body>"
            "<h1>Details for Order #%s</h1>"
            "<p>Order Placed: %s, %d</p><p>Amazon.com order number: %s</p>"
            "<p>Order Total: $12.34</p><h2>Items Ordered</h2>"
            "<p>Invented Desk Lamp, Brass</p><p>Sold by: Example Seller Co</p><p>$12.34</p>"
            "<p>Item(s) Subtotal: $12.34</p><p>Grand Total: $12.34</p>"
            "</body></html>" % (order, order, day, year, order))


class FakeAmazon:
    """Each year's order list, one order a page, chosen by the startIndex it
    is asked for, and each order's printable summary."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.years = {}     # year -> [[order, ...] for each page]
        self.more = {}      # year -> whether its last page still shows Next
        self.seen = []

    def page(self, year, at):
        pages = self.years.get(year)
        if not pages:
            return EMPTY
        # Past the end, Amazon keeps serving the last page.
        at = min(at, len(pages) - 1)
        cards = "".join(card(o) for o in pages[at])
        if at < len(pages) - 1 or self.more.get(year):
            cards += NEXT % (HISTORY + "?timeFilter=year-%d&startIndex=%d" % (year, (at + 1) * 10))
        return orders_page(sum(len(p) for p in pages), cards)

    def asked(self, path):
        return [s for s in self.seen if s.startswith(path)]


SITE = FakeAmazon()


def long_account():
    """Last year's list runs to a third page, one past the limit of two."""
    SITE.years = {Y0: [[A1]], Y1: [[L1], [L2], [L3]], Y2: [[O1]]}


def ordinary_account():
    """Last year's list ends on its second page, at the limit and no further."""
    SITE.years = {Y0: [[A1]], Y1: [[L1], [L2]], Y2: [[O1]]}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _answer(self, body):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(self.path)
        query = parse_qs(parts.query)
        order = (query.get("orderID") or [""])[0]
        if parts.path == HISTORY:
            spec = (query.get("timeFilter") or [""])[0]
            year = int(spec[5:]) if spec.startswith("year-") else Y0
            self._answer(SITE.page(year, int((query.get("startIndex") or ["0"])[0]) // 10))
        elif parts.path == PRINT and order in PLACED:
            self._answer(summary_page(order))
        elif parts.path == "/":
            self._answer("<!doctype html><html><head><title>Amazon.com</title></head>"
                         "<body><h1>Amazon.com</h1></body></html>")
        else:
            self.send_error(404)

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
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_amazon(server, monkeypatch):
    """Every address the app opens points at the made-up store, every wait
    is short, and the limit is two pages."""
    SITE.reset()
    real = site.set_marketplace

    def here(domain=None):
        said = real(domain)
        monkeypatch.setattr(site, "BASE", server)
        monkeypatch.setitem(site.URLS, "home", server + "/")
        monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
        return said

    monkeypatch.setattr(site, "set_marketplace", here)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    for name, ms in (("ORDERS_WAIT_MS", 800), ("YEAR_WAIT_MS", 800), ("SETTLE_MS", 0),
                     ("YEAR_SETTLE_MS", 0), ("CHALLENGE_WAIT_MS", 1500)):
        monkeypatch.setattr(site, name, ms, raising=False)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    monkeypatch.setattr(app_mod, "YEAR_PAGES", 2)
    yield SITE
    real(site.DEFAULT_MARKETPLACE)


def config_for(folder, cdp_url):
    folder.mkdir(parents=True, exist_ok=True)
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(folder / "out"),
        "profile_dir": str(folder / "launched-profile"), "cdp_url": cdp_url,
        "pilot_online": 2, "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def printed(capsys):
    return " ".join(capsys.readouterr().out.split())


def run(folder, cdp_url, capsys, *flags, stops=True):
    """One run of the app. A run that stops leaves on SystemExit with code 0
    while the exception is in flight, which the core reports as stopped."""
    cfg = config_for(folder, cdp_url)
    if stops:
        with pytest.raises(SystemExit) as left:
            app_mod.main([*flags, "--config", str(cfg)])
        out = printed(capsys)
        assert left.value.code == 0, out
    else:
        assert app_mod.main([*flags, "--config", str(cfg)]) == 0
        out = printed(capsys)
    return out


def out_dir(folder):
    return folder / "out"


def saved(folder):
    """The orders whose receipt this account has saved."""
    path = out_dir(folder) / "progress.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k.split(":", 1)[1] for k, rec in data.items()
            if isinstance(rec, dict) and rec.get("downloaded_ok")}


def known(folder):
    path = out_dir(folder) / "discovery.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k.split(":", 1)[1] for k in data}


def note(folder):
    return json.loads((out_dir(folder) / "last-listing.json").read_text(encoding="utf-8"))


def failures(folder):
    return sorted((out_dir(folder) / "Diagnostics").glob("failure-*.json"))


def printed_for(order):
    return [s for s in SITE.asked(PRINT) if "orderID=" + order in s]


def a_list_stop(out):
    """What the panel reads at the end, a stop at a page and not a list
    left unread, which would offer to read it again rather than Continue."""
    return '"stopped": 1' in out and '"stop": "page"' in out and "list_not_read" not in out


# -- what a run does with a year past the limit ---------------------------------------

def test_run_all_downloads_every_order_it_read_and_then_stops(attached, tmp_path, capsys):
    """Everything read is downloaded, the years before the long one too,
    and only then does the run stop, as a stop at a page."""
    long_account()
    out = run(tmp_path, attached, capsys, "--all", "--yes")

    assert saved(tmp_path) == {A1, L1, L2, O1}, out
    assert L3 not in known(tmp_path) and not printed_for(L3)
    assert all(len(printed_for(o)) == 1 for o in (A1, L1, L2, O1)), SITE.asked(PRINT)
    history = SITE.asked(HISTORY)
    assert not any("year-%d&startIndex=20" % Y1 in s for s in history), "past the limit"
    assert any("year-%d" % Y3 in s for s in history), "the walk went on to the older years"
    assert not any("year-%d" % Y4 in s for s in history), "and ended at the first empty one"
    assert note(tmp_path)["complete"] is False
    assert len(failures(tmp_path)) == 1
    assert a_list_stop(out), out
    assert out.index("ran past 2 pages") < out.index("Processing 4 purchase(s)") \
        < out.index("downloads anything new and stops at the same place"), out


def test_a_run_after_a_stopped_one_downloads_only_what_is_new(attached, tmp_path, capsys):
    """Continue reads the list again, takes the order placed since, and
    stops at the same place. With nothing new it says so and stops again."""
    long_account()
    run(tmp_path, attached, capsys, "--all", "--yes")
    SITE.years[Y0] = [[A2, A1]]
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume")

    assert saved(tmp_path) == {A1, A2, L1, L2, O1}, out
    assert SITE.asked(PRINT) and all("orderID=" + A2 in s for s in SITE.asked(PRINT)), \
        SITE.asked(PRINT)
    assert any("year-%d" % Y0 in s for s in SITE.asked(HISTORY)), "the list was read again"
    assert a_list_stop(out), out
    assert "downloads anything new and stops at the same place" in out, out

    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume")
    assert "Nothing to resume" in out and not SITE.asked(PRINT), out
    assert a_list_stop(out), out


def test_a_pilot_downloads_what_it_read_and_then_stops(attached, tmp_path, capsys):
    long_account()
    out = run(tmp_path, attached, capsys, "--pilot")

    assert len(saved(tmp_path)) == 2, out
    assert O1 in known(tmp_path), "the walk went on past the long year"
    assert a_list_stop(out), out
    # A pilot takes a few of what it read, so it promises nothing more.
    assert "stops at the same place" in out and "downloads anything new" not in out, out


def test_a_pilot_with_nothing_to_pilot_still_stops(attached, tmp_path, capsys):
    """Pilot's way out when nothing is chosen stops on a cut list too."""
    long_account()
    out = run(tmp_path, attached, capsys, "--pilot", "--order-number", L3)

    assert "No purchases discovered to pilot" in out, out
    assert not saved(tmp_path)
    assert a_list_stop(out), out


@pytest.mark.parametrize("flags", [("--all", "--yes", "--dry-run"), ("--dry-run",)],
                         ids=["Run All dry", "dry run"])
def test_a_dry_run_saves_nothing_and_promises_no_download(attached, tmp_path, capsys, flags):
    """A dry run, alone or with --all, saves nothing, so its words at the
    stop do not say a run again downloads anything new."""
    long_account()
    out = run(tmp_path, attached, capsys, *flags)

    assert not saved(tmp_path), out
    assert a_list_stop(out), out
    assert "stops at the same place" in out and "downloads anything new" not in out, out


def test_check_whats_there_reads_the_older_years_and_then_stops(attached, tmp_path, capsys):
    """Discover downloads nothing, and says it read only part of the list."""
    long_account()
    out = run(tmp_path, attached, capsys, "--discover")

    assert known(tmp_path) == {A1, L1, L2, O1}, out
    assert not SITE.asked(PRINT)
    assert "read part of your order history" in out and "Discovery complete" not in out, out
    assert "stops at the same place" in out and "downloads anything new" not in out, out
    assert note(tmp_path)["complete"] is False
    assert a_list_stop(out), out


def test_a_support_report_is_still_written(attached, tmp_path, capsys):
    """A Diagnose with nothing known reads the list. Reaching the limit it
    writes its report rather than leave before it."""
    long_account()
    out = run(tmp_path, attached, capsys, "--diagnose", stops=False)

    assert "ran past 2 pages" in out and "not taken as read whole" in out, out
    assert "stops" not in out, "a support report says nothing of a stop it does not make"
    assert list((out_dir(tmp_path) / "Diagnostics").glob("survey-diagnose-*.json")), out
    assert len(failures(tmp_path)) == 1


def test_once_the_year_fits_the_run_finishes_clean(attached, tmp_path, capsys, monkeypatch):
    """When the year comes to fit, the next run reads it whole, takes only
    the orders it had not reached, and notes the list as read whole."""
    long_account()
    run(tmp_path, attached, capsys, "--all", "--yes")
    monkeypatch.setattr(app_mod, "YEAR_PAGES", 3)
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume", stops=False)

    assert saved(tmp_path) == {A1, L1, L2, L3, O1}, out
    assert SITE.asked(PRINT) and all("orderID=" + L3 in s for s in SITE.asked(PRINT)), \
        SITE.asked(PRINT)
    assert note(tmp_path)["complete"] is True
    assert '"stopped": 0' in out, out


# -- an account with no such year ---------------------------------------------------

def test_an_ordinary_account_finishes_clean(attached, tmp_path, capsys):
    """A year that ends exactly at the limit is whole, and every run on such
    an account is what it always was."""
    ordinary_account()
    out = run(tmp_path, attached, capsys, "--all", "--yes", stops=False)

    assert saved(tmp_path) == {A1, L1, L2, O1}, out
    assert note(tmp_path)["complete"] is True
    assert not failures(tmp_path) and "ran past" not in out
    assert '"stopped": 0' in out, out

    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume", stops=False)
    assert "Nothing to resume" in out and not SITE.asked(HISTORY), out


@pytest.mark.parametrize("command", ["--discover", "--pilot", "--diagnose"])
def test_an_ordinary_account_finishes_clean_on_every_command(attached, tmp_path, capsys,
                                                             command):
    """Check what's there, a pilot and a support report on a fresh folder,
    each as it always was."""
    ordinary_account()
    out = run(tmp_path, attached, capsys, command, stops=False)

    assert not failures(tmp_path) and "ran past" not in out, out
    assert note(tmp_path)["complete"] is True
    if command == "--discover":
        assert "Discovery complete" in out and known(tmp_path) == {A1, L1, L2, O1}, out
    if command == "--pilot":
        assert len(saved(tmp_path)) == 2 and '"stopped": 0' in out, out
    if command == "--diagnose":
        assert list((out_dir(tmp_path) / "Diagnostics").glob("survey-diagnose-*.json")), out
