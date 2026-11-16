"""At most a day's worth of Amazon orders, a slower pace, and a rest after a
check (#229).

A tester with more than 2,500 orders was locked out of their Amazon account
partway through a first full run. That run opened every order one after
another, two to four and a half seconds apart, with no limit on a run or a
day, about 5,000 order pages in one sitting. A robot check under the panel
stopped it and said to press Continue, and at a console it waited for Enter
and went on.

So a run opens at most orders_per_day orders a day (200 unless set), counted
across runs in the account's own folder, and stops before the next one,
saying when it can carry on. Until then every run that opens orders, and
Check what's there, stops at once, before the browser is asked for anything,
while Sign in and Support report still work. A check met
once that day has opened an order stops the run with no prompt and rests
the account 24 hours. A check before any order that day is answered as it
always was. Between orders the wait is 5 to 10 seconds on an install still
on the old 2 to 4.5, and a few minutes' break comes every 25 orders.

The runs here that need pages get them from a server on this machine, in a
browser the app attaches to over CDP, as in test_a_year_past_the_page_limit.py.
The rest drive the app's own methods with the page and the order stubbed.
Every order number and amount is invented.
"""
import json
import sys
import threading
from datetime import date, datetime, timedelta, timezone
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
from paperpull_core.models import ONLINE, Purchase

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
HISTORY = "/gp/css/order-history"
PRINT = "/gp/css/summary/print.html"
STATE = "daily-limit.json"

LAST_YEAR = date.today().year - 1
ORDERS = ["114-0000000-0000101", "114-0000000-0000102", "114-0000000-0000103",
          "114-0000000-0000104", "114-0000000-0000105"]
# Newest first, as the list shows them and the run takes them.
PLACED = {o: "December %d" % (20 - i) for i, o in enumerate(ORDERS)}

CARD = ('<div class="order-card js-order-card"><div>Order placed</div><div>%s, %d</div>'
        "<div>Total</div><div>$12.34</div><div>Order # %s</div>"
        '<a href="/gp/your-account/order-details?orderID=%s">View order details</a></div>')

NEXT = '<ul class="a-pagination"><li class="a-last"><a href="%s">Next</a></li></ul>'

CHECK = """<!doctype html><html><head><title>Amazon.com</title></head><body>
<h4>Enter the characters you see below</h4>
<p>Sorry, we just need to make sure you're not a robot.</p>
<form action="/errors/validateCaptcha"><input id="captchacharacters"></form>
</body></html>"""

START = datetime(2026, 3, 9, 14, 0, tzinfo=timezone.utc)


def orders_page(count, cards=""):
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


def summary_page(order):
    return ("<!doctype html><html><head><title>Amazon.com - Order %s</title></head><body>"
            "<h1>Details for Order #%s</h1>"
            "<p>Order Placed: %s, %d</p><p>Amazon.com order number: %s</p>"
            "<p>Order Total: $12.34</p><h2>Items Ordered</h2>"
            "<p>Invented Desk Lamp, Brass</p><p>Sold by: Example Seller Co</p><p>$12.34</p>"
            "<p>Item(s) Subtotal: $12.34</p><p>Grand Total: $12.34</p>"
            "</body></html>" % (order, order, PLACED[order], LAST_YEAR, order))


class FakeAmazon:
    """Last year's five orders on one page, each order's printable summary,
    and a check served in place of a page the test names, once."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.seen = []
        self.check_at = set()   # "list" or an order number, served a check once
        self.more = False       # whether last year's page still shows Next

    def list_page(self, year):
        if year != LAST_YEAR:
            return orders_page(0)
        cards = "".join(CARD % (PLACED[o], LAST_YEAR, o, o) for o in ORDERS)
        if self.more:
            cards += NEXT % (HISTORY + "?timeFilter=year-%d&startIndex=10" % LAST_YEAR)
        return orders_page(len(ORDERS), cards)

    def asked(self, path):
        return [s for s in self.seen if s.startswith(path)]

    def opened(self):
        """The orders whose page the app opened, in the order it opened them."""
        got = []
        for s in self.asked(PRINT):
            order = (parse_qs(urlsplit(s).query).get("orderID") or [""])[0]
            if order not in got:
                got.append(order)
        return got


SITE = FakeAmazon()


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
            if "list" in SITE.check_at:
                SITE.check_at.discard("list")
                self._answer(CHECK)
                return
            spec = (query.get("timeFilter") or [""])[0]
            year = int(spec[5:]) if spec.startswith("year-") else LAST_YEAR + 1
            self._answer(SITE.list_page(year))
        elif parts.path == PRINT and order in PLACED:
            if order in SITE.check_at:
                SITE.check_at.discard(order)
                self._answer(CHECK)
                return
            self._answer(summary_page(order))
        elif parts.path == "/":
            self._answer("<!doctype html><html><head><title>Amazon.com</title></head>"
                         "<body><h1>Amazon.com</h1></body></html>")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class Clock:
    """The time the app reads, moved by the test."""

    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at

    def move(self, **by):
        self.at = self.at + timedelta(**by)


class Sleeps:
    """Every wait the app asks for, in seconds, none of them waited."""

    def __init__(self):
        self.asked = []

    def __call__(self, seconds):
        self.asked.append(seconds)

    def breaks(self):
        """Each break, the waits that come one after another with none of 0
        between them added up, since a break waits in steps that say how
        long it has left. Every other wait here is 0."""
        got, run = [], 0
        for s in self.asked + [0]:
            if s:
                run += s
            elif run:
                got.append(run)
                run = 0
        return got


@pytest.fixture
def clock(monkeypatch):
    c = Clock(START)
    monkeypatch.setattr(app_mod, "_now", c, raising=False)
    return c


@pytest.fixture
def sleeps(monkeypatch):
    s = Sleeps()
    monkeypatch.setattr(app_mod, "_sleep", s, raising=False)
    return s


@pytest.fixture
def prompts(monkeypatch):
    """Each prompt a run asks at the console, answered with Enter."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    return asked


def printed(capsys):
    return " ".join(capsys.readouterr().out.split())


# -- the browser runs ---------------------------------------------------------------

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


@pytest.fixture
def fake_amazon(server, monkeypatch, clock, sleeps, prompts):
    """Every address the app opens points at the made-up store, and every
    page wait is short."""
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
    # A run starts with no prompt left unanswered. Another test in this
    # process may have left one, which would make every stop here read as
    # one that needed somebody (run_reporting.stop_reason).
    monkeypatch.setattr(browser_launcher, "_NOBODY_ANSWERED", False)
    yield SITE
    real(site.DEFAULT_MARKETPLACE)


def config_for(folder, cdp_url, **more):
    folder.mkdir(parents=True, exist_ok=True)
    cfg = folder / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(folder / "out"),
        "profile_dir": str(folder / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0, **more}), encoding="utf-8")
    return cfg


def run(folder, cdp_url, capsys, *flags, stops=True, **more):
    cfg = config_for(folder, cdp_url, **more)
    if stops:
        with pytest.raises(SystemExit) as left:
            app_mod.main([*flags, "--config", str(cfg)])
        out = printed(capsys)
        assert left.value.code == 0, out
    else:
        assert app_mod.main([*flags, "--config", str(cfg)]) == 0
        out = printed(capsys)
    return out


def saved(folder):
    path = folder / "out" / "progress.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k.split(":", 1)[1] for k, rec in data.items()
            if isinstance(rec, dict) and rec.get("downloaded_ok")}


def stopped_with_continue(out):
    """The panel's reading of the run's last line: a run that stopped, for
    no reason the panel names, so it offers Continue, and not a list left
    unread, which would offer to read it again."""
    return '"stopped": 1' in out and '"stop":' not in out and "list_not_read" not in out


def test_get_new_opens_a_days_orders_then_continue_waits_for_the_next_day(
        fake_amazon, attached, tmp_path, capsys, clock):
    out = run(tmp_path, attached, capsys, "--all", "--yes", orders_per_day=3)
    assert SITE.opened() == ORDERS[:3], out
    assert saved(tmp_path) == set(ORDERS[:3]), out
    assert "at most 3 Amazon orders a day" in out, out
    assert "2 orders wait" in out, out
    assert stopped_with_continue(out), out
    # The list was read to its end, so Continue carries on without it.
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note.get("complete") is True, note

    # Right away, and a minute short of a day: nothing is asked of Amazon.
    for later in (dict(minutes=1), dict(hours=23, minutes=58)):
        clock.move(**later)
        SITE.seen.clear()
        out = run(tmp_path, attached, capsys, "--resume", orders_per_day=3)
        assert SITE.seen == [], out
        assert "at most 3 Amazon orders a day" in out, out
        assert stopped_with_continue(out), out

    # A day after the first order, Continue takes the rest and finishes,
    # without reading the list again.
    clock.move(minutes=2)
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume", stops=False, orders_per_day=3)
    assert SITE.opened() == ORDERS[3:], out
    assert not SITE.asked(HISTORY), SITE.seen
    assert saved(tmp_path) == set(ORDERS), out


def test_a_day_spent_in_a_run_whose_list_was_cut_short(fake_amazon, attached, tmp_path, capsys,
                                                       clock, monkeypatch):
    """The day's limit stops the run first. The list stays noted as one that
    stopped, so the next day's Continue reads it again and ends at the stop
    for a list cut short."""
    monkeypatch.setattr(app_mod, "YEAR_PAGES", 1)
    SITE.more = True
    out = run(tmp_path, attached, capsys, "--all", "--yes", orders_per_day=3)
    assert SITE.opened() == ORDERS[:3], out
    assert stopped_with_continue(out), out
    note = json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))
    assert note.get("complete") is False, note

    clock.move(hours=24, minutes=1)
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume", orders_per_day=3)
    assert SITE.asked(HISTORY), "the list is read again"
    assert SITE.opened() == ORDERS[3:], out
    assert '"stop": "page"' in out, out


def test_every_run_that_reads_amazon_waits_out_a_spent_day(fake_amazon, attached, tmp_path, capsys, clock):
    run(tmp_path, attached, capsys, "--all", "--yes", orders_per_day=1)
    assert SITE.opened() == ORDERS[:1]
    clock.move(hours=1)
    for flags in (("--all", "--yes"), ("--discover",), ("--pilot",), ("--dry-run",), ("--resume",)):
        SITE.seen.clear()
        out = run(tmp_path, attached, capsys, *flags, orders_per_day=1)
        assert SITE.seen == [], (flags, out)
        assert "at most 1 Amazon order a day" in out, (flags, out)


def test_a_check_after_an_order_rests_the_account_a_day(fake_amazon, attached, tmp_path, capsys,
                                                        clock, prompts):
    # The day's first order at START, the check three hours later.
    run(tmp_path, attached, capsys, "--all", "--yes", "--max-purchases", "1", stops=False)
    assert saved(tmp_path) == {ORDERS[0]}
    clock.move(hours=3)
    SITE.seen.clear()
    SITE.check_at = {ORDERS[1]}
    out = run(tmp_path, attached, capsys, "--resume")
    assert prompts == [], "no prompt after a check once an order was opened"
    assert SITE.opened() == ORDERS[1:2], out
    assert saved(tmp_path) == {ORDERS[0]}, out
    assert "characters you see" in out and "rests this account" in out, out
    assert stopped_with_continue(out), out

    # Rested a day from the check, past the end of the day it began in.
    clock.move(hours=23, minutes=59)
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--resume")
    assert SITE.seen == [], out
    clock.move(minutes=2)
    out = run(tmp_path, attached, capsys, "--resume", stops=False)
    assert saved(tmp_path) == set(ORDERS), out


def test_a_check_on_the_list_after_an_earlier_run_rests_the_account(
        fake_amazon, attached, tmp_path, capsys, clock, prompts):
    run(tmp_path, attached, capsys, "--all", "--yes", stops=False)
    assert saved(tmp_path) == set(ORDERS)
    clock.move(hours=2)
    SITE.reset()
    SITE.check_at = {"list"}
    out = run(tmp_path, attached, capsys, "--all", "--yes")
    assert prompts == [], out
    clock.move(hours=3)
    SITE.seen.clear()
    out = run(tmp_path, attached, capsys, "--discover")
    assert SITE.seen == [], out


def test_a_check_before_any_order_that_day_is_answered_as_it_always_was(
        fake_amazon, attached, tmp_path, capsys, clock, prompts):
    SITE.check_at = {"list"}
    out = run(tmp_path, attached, capsys, "--all", "--yes", stops=False)
    assert len(prompts) == 1, (prompts, out)
    assert saved(tmp_path) == set(ORDERS), out


# -- the count, without a browser -------------------------------------------------------

def purchases(n=5):
    return [Purchase(purchase_type=ONLINE, order_number=o, purchase_date="%d-12-%02d" % (LAST_YEAR, 20 - i))
            for i, o in enumerate(ORDERS[:n])]


class Opened:
    """process_one, stubbed, noting each order it was given."""

    def __init__(self, fail=()):
        self.orders = []
        self.fail = set(fail)

    def __call__(self, page, purchase, dry_run=False):
        self.orders.append(purchase.order_number)
        if purchase.order_number in self.fail:
            raise RuntimeError("an invented failure")


def an_app(monkeypatch, folder, **config):
    Path(folder).mkdir(parents=True, exist_ok=True)
    app = testkit.receipt_app(app_mod, folder, **config)
    opened = Opened()
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(app, "process_one", opened)
    return app, opened


def take(app, items):
    """process_purchases, and whether it stopped."""
    try:
        app.process_purchases(items)
    except SystemExit as left:
        assert left.code == 0
        return True
    return False


def test_the_count_carries_across_runs_and_renews_a_day_after_its_first_order(
        monkeypatch, tmp_path, clock, sleeps, capsys):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=2)
    assert take(app, purchases()) is True
    assert opened.orders == ORDERS[:2]

    clock.move(hours=23, minutes=59, seconds=59)
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=2)
    assert take(app, purchases()[2:]) is True
    assert opened.orders == []

    clock.move(seconds=1)
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=2)
    assert take(app, purchases()[2:]) is True
    assert opened.orders == ORDERS[2:4]


def test_an_order_already_saved_is_not_counted(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    done = purchases()[0]
    app.progress.update(done.key, {"downloaded_ok": True, "state": "COMPLETED"})
    assert take(app, purchases(2)) is False
    assert opened.orders == [ORDERS[1]]


def test_an_order_that_fails_is_counted(monkeypatch, tmp_path, clock, sleeps):
    app = testkit.receipt_app(app_mod, tmp_path, orders_per_day=1)
    opened = Opened(fail={ORDERS[0]})
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(app, "process_one", opened)
    assert take(app, purchases(2)) is True
    assert opened.orders == [ORDERS[0]]


def test_no_daily_limit_when_it_is_set_to_nought(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=0)
    assert take(app, purchases()) is False
    assert opened.orders == ORDERS


def test_two_accounts_count_their_own_orders(monkeypatch, tmp_path, clock, sleeps):
    first, opened_first = an_app(monkeypatch, tmp_path / "first", orders_per_day=1)
    assert take(first, purchases(2)) is True
    second, opened_second = an_app(monkeypatch, tmp_path / "second", orders_per_day=1)
    assert take(second, purchases(1)) is False
    assert opened_first.orders == opened_second.orders == [ORDERS[0]]


@pytest.mark.parametrize("held", ["", "not json", "[1, 2]", '"x"', "{}",
                                  '{"day_started": 5, "orders_opened": "x"}',
                                  '{"day_started": "yesterday", "orders_opened": 2, "rest_until": []}',
                                  '{"day_started": "%s", "orders_opened": -5}' % START.isoformat(),
                                  '{"day_started": "%s", "orders_opened": true}' % START.isoformat(),
                                  '{"day_started": "%s", "orders_opened": 1, "rest_until": "soon"}'
                                  % START.isoformat()])
def test_a_count_file_it_cannot_read_starts_a_new_day(monkeypatch, tmp_path, clock, sleeps, capsys, held):
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / STATE).write_text(held, encoding="utf-8")
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=2)
    assert take(app, purchases(3)) is True
    assert opened.orders == ORDERS[:2]
    assert json.loads((tmp_path / "out" / STATE).read_text(encoding="utf-8"))


def test_a_day_that_starts_in_the_future_is_taken_as_starting_now(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    assert take(app, purchases(2)) is True
    # The clock went back ten days, so the day began in its future.
    clock.move(days=-10)
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    assert take(app, purchases(2)[1:]) is True and opened.orders == []
    clock.move(hours=24, seconds=1)
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    assert take(app, purchases(2)[1:]) is False
    assert opened.orders == [ORDERS[1]]


def files_of(folder):
    """Every file of the account's folder but the run's log and summary, as
    bytes, to tell whether a run changed any."""
    root = Path(folder) / "out"
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and p.parent.name not in ("Logs", "Backups")
            and p.name not in ("run-summary.txt",)}


def test_a_rest_that_ends_more_than_a_day_away_lasts_a_day(monkeypatch, tmp_path, clock, sleeps):
    """Only a clock that went back leaves a rest ending further off than a
    day, and it holds no longer than a day from now."""
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / STATE).write_text(json.dumps({
        "day_started": None, "orders_opened": 0,
        "rest_until": (START + timedelta(days=10)).isoformat()}), encoding="utf-8")
    app, opened = an_app(monkeypatch, tmp_path)
    assert take(app, purchases(1)) is True and opened.orders == []
    clock.move(hours=24, seconds=1)
    app, opened = an_app(monkeypatch, tmp_path)
    assert take(app, purchases(1)) is False and opened.orders == [ORDERS[0]]


CONSOLE, PANEL = False, True
# What carries on, as the app says it and as the core's own last line goes
# on to say it, which must agree, at a console and under the panel.
CORE_SAYS = {"Discover": "press Discover again rather than Resume",
             "Check what's there": "Check what's there downloads nothing, so run it again",
             "Resume": "Resume carries on from where it stopped",
             "Continue": "Continue carries on from where it stopped"}


@pytest.mark.parametrize("flags, panel, again", [
    (["--discover"], CONSOLE, "Discover"), (["--discover"], PANEL, "Check what's there"),
    (["--pilot"], CONSOLE, "Resume"), (["--pilot"], PANEL, "Continue"),
    (["--all", "--yes"], CONSOLE, "Resume"), (["--all", "--yes"], PANEL, "Continue"),
    (["--all"], CONSOLE, "Resume"), (["--resume"], CONSOLE, "Resume"), (["--resume"], PANEL, "Continue"),
    (["--dry-run"], CONSOLE, "Resume"), (["--all", "--yes", "--dry-run"], CONSOLE, "Resume"),
    (["--pilot", "--dry-run"], PANEL, "Continue")])
def test_a_spent_day_stops_these_runs_before_the_browser(monkeypatch, tmp_path, clock, sleeps, capsys,
                                                         flags, panel, again):
    app, _ = an_app(monkeypatch, tmp_path, orders_per_day=1)
    # The orders listed, as a run that opened one had listed them.
    for p in purchases(2):
        app.discovery.update(p.key, p.to_dict(), save=False)
    app.discovery.save()
    take(app, purchases(2))
    app.progress.save()
    (tmp_path / "out" / "new-this-run.txt").write_text("# the last download run's list\n", encoding="utf-8")
    before = files_of(tmp_path)
    capsys.readouterr()

    def no_browser(self):
        raise AssertionError("the browser was asked for")

    def nobody(*_a):
        raise AssertionError("a prompt was asked")

    monkeypatch.setattr(app_mod.App, "page", no_browser)
    monkeypatch.setattr(app_mod.App, "browser", no_browser)
    monkeypatch.setattr("builtins.input", nobody)
    if panel:
        monkeypatch.setenv("PAPERPULL_RUN_MARK", "0123456789abcdef0123456789abcdef")
    else:
        monkeypatch.delenv("PAPERPULL_RUN_MARK", raising=False)
    with pytest.raises(SystemExit) as left:
        app_mod.main([*flags, "--config", str(tmp_path / "config.json")])
    out = printed(capsys)
    assert left.value.code == 0, out
    assert "at most 1 Amazon order a day" in out, out
    # What carries on, as this run is named, and the day and time it may.
    assert "%s after %s carries on" % (again, app_mod._when(START + timedelta(hours=24))) in out, out
    assert CORE_SAYS[again] in out, out
    # The runs it holds and those it does not, by the names of where it ran.
    assert ("Sign in and Support report still work" if panel
            else "--login and --diagnose still work") in out, out
    assert ("--login" not in out) if panel else ("Check what's there stop" not in out), out
    # The panel has no button called Pilot (test_a_runs_lines_name_the_panels_buttons).
    assert not panel or "Pilot" not in out, out
    assert '"stopped": 1' in out, out
    assert files_of(tmp_path) == before, "a held run changed the account's files"


@pytest.mark.parametrize("began, rest, said", [
    # A check an hour ago, in a day that began four hours ago. The rest ends later.
    (-4, 23, "rests the account until after %s"),
    # A rest that ends in two hours, in a day that ends in 23. The day ends later.
    (-1, 2, "at most 1 Amazon order a day"),
])
def test_a_held_run_says_the_later_of_a_rest_and_the_days_end(monkeypatch, tmp_path, clock, sleeps, capsys,
                                                               began, rest, said):
    (tmp_path / "out").mkdir(parents=True)
    rest_until, day_ends = START + timedelta(hours=rest), START + timedelta(hours=began + 24)
    (tmp_path / "out" / STATE).write_text(json.dumps({
        "day_started": (START + timedelta(hours=began)).isoformat(), "orders_opened": 1,
        "rest_until": rest_until.isoformat()}), encoding="utf-8")
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    assert take(app, purchases(1)) is True and opened.orders == []
    out = printed(capsys)
    later = max(rest_until, day_ends)
    assert "after " + app_mod._when(later) + " carries on" in out, out
    if said and "%s" in said:
        assert said % app_mod._when(rest_until) in out, out
        assert "orders_per_day" not in out, out
    elif said:
        assert said in out and "orders_per_day" in out, out


def test_a_spent_day_never_holds_a_support_report(monkeypatch, tmp_path, clock, sleeps, capsys):
    """A Support report reads the order list when nothing is listed yet,
    through the same cmd_discover Check what's there runs, and is never held."""
    app, _ = an_app(monkeypatch, tmp_path, orders_per_day=1)
    take(app, purchases(2))
    app.stats["mode"] = "diagnose"

    class ReachedTheBrowser(Exception):
        pass

    def the_browser():
        raise ReachedTheBrowser()

    monkeypatch.setattr(app, "page", the_browser)
    with pytest.raises(ReachedTheBrowser):
        app.cmd_discover(quiet=True, finish=False)
    app.stats["mode"] = "discover"
    with pytest.raises(SystemExit):
        app.cmd_discover()


def test_a_spent_day_holds_no_run_that_reads_nothing_from_amazon(monkeypatch, tmp_path, clock, sleeps, capsys):
    app, _ = an_app(monkeypatch, tmp_path, orders_per_day=1)
    take(app, purchases(2))
    capsys.readouterr()
    assert app_mod.main(["--verify", "--config", str(tmp_path / "config.json")]) == 0
    assert "Amazon order a day" not in printed(capsys)


def test_the_day_starts_at_its_first_order_not_at_a_run_with_none_to_open(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    done = purchases(1)[0]
    app.progress.update(done.key, {"downloaded_ok": True, "state": "COMPLETED"})
    assert take(app, [done]) is False and opened.orders == []
    assert not (tmp_path / "out" / STATE).exists()
    clock.move(hours=1)
    assert take(app, purchases(2)) is False
    day = json.loads((tmp_path / "out" / STATE).read_text(encoding="utf-8"))
    assert app_mod._moment(day["day_started"]) == START + timedelta(hours=1)


def test_the_limit_stops_the_run_when_its_progress_cannot_be_saved(monkeypatch, tmp_path, clock, sleeps, capsys):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=1)
    real_save = app.progress.save

    def no_backup(*a, **k):
        if k.get("backup"):
            raise PermissionError("an invented held file")
        return real_save(*a, **k)

    monkeypatch.setattr(app.progress, "save", no_backup)
    assert take(app, purchases(2)) is True
    out = printed(capsys)
    assert opened.orders == ORDERS[:1], out
    assert "1 order waits" in out and "carries on with it." in out, out
    assert "Progress is saved" not in out, out


@pytest.mark.parametrize("progress_too", [False, True])
def test_a_count_that_cannot_be_saved_opens_nothing(monkeypatch, tmp_path, clock, sleeps, capsys, progress_too):
    app, opened = an_app(monkeypatch, tmp_path)

    def full(*_a, **_k):
        raise OSError("an invented full disk")

    monkeypatch.setattr(app_mod, "atomic_write_json", full)
    if progress_too:
        real_save = app.progress.save
        monkeypatch.setattr(app.progress, "save",
                            lambda *a, **k: full() if k.get("backup") else real_save(*a, **k))
    assert take(app, purchases(2)) is True
    out = printed(capsys)
    assert opened.orders == []
    assert "could not be saved" in out, out
    assert ("Progress is saved" in out) is not progress_too, out


# -- a robot check, without a browser ------------------------------------------------------

def checked(monkeypatch, app, said):
    """The app's own check_session on a page that is the check `said`, with
    each prompt it asks noted and answered with Enter."""
    asked = []
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: said)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: asked.append(prompt) or "")
    try:
        app.check_session(None)
    except SystemExit as left:
        assert left.code == 0
        return True, asked
    return False, asked


ROBOT = "Security challenge detected: 'enter the characters you see'"


@pytest.mark.parametrize("said, rests", [
    (ROBOT, True),
    ("Security challenge detected: 'robot check'", True),
    ("Possible rate limiting detected: 'too many requests'", True),
    ("Security challenge detected: 'two-step verification'", False),
    ("Security challenge detected: 'enter the otp'", False),
])
def test_which_pages_rest_the_account(monkeypatch, tmp_path, clock, sleeps, said, rests):
    app, _ = an_app(monkeypatch, tmp_path)
    take(app, purchases(1))
    app.stats["mode"] = "all"
    stopped, asked = checked(monkeypatch, app, said)
    assert stopped is rests and (asked == []) is rests, (stopped, asked)
    day = json.loads((tmp_path / "out" / STATE).read_text(encoding="utf-8"))
    assert bool(day["rest_until"]) is rests


@pytest.mark.parametrize("held", ["the day file", "progress"])
def test_a_check_on_an_orders_page_stops_the_run_when_a_save_fails(
        monkeypatch, tmp_path, clock, sleeps, capsys, held):
    """process_one takes an exception from its page's check as a page that
    would not open, and opens it again. So a save that fails there, of the
    rest or of the run's progress, may not reach it, or the run goes on to
    the next orders."""
    app = testkit.receipt_app(app_mod, tmp_path)
    app.stats["mode"] = "all"
    opened, asked = [], []
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(site, "goto_details", lambda page, p: opened.append(p.order_number))
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: ROBOT if len(opened) == 2 else None)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "goto_orders", lambda page: True)
    monkeypatch.setattr(site, "extract_details", lambda page, p: p)
    monkeypatch.setattr(app_mod.App, "_canceled", lambda self, page, p: False)
    monkeypatch.setattr(app_mod.App, "_save_receipt", lambda self, page, p: False)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: asked.append(prompt) or "")
    real = app_mod.atomic_write_json

    def no_rest(path, data, **how):
        if isinstance(data, dict) and data.get("rest_until"):
            raise PermissionError("an invented held file")
        return real(path, data, **how)

    real_save = app.progress.save

    def no_backup(*a, **k):
        # The saves of a stop take a backup, the record of each order none.
        if k.get("backup"):
            raise PermissionError("an invented held file")
        return real_save(*a, **k)

    if held == "the day file":
        monkeypatch.setattr(app_mod, "atomic_write_json", no_rest)
    else:
        monkeypatch.setattr(app.progress, "save", no_backup)
    with pytest.raises(SystemExit) as left:
        app.process_purchases(purchases(3))
    out = printed(capsys)
    assert left.value.code == 0, out
    assert opened == ORDERS[:2] and asked == [], (opened, asked)
    if held == "the day file":
        assert "could not be saved" in out and "leave Amazon alone" in out, out
    else:
        assert "rests this account" in out and "Progress is saved" not in out, out


def test_a_check_still_stops_when_no_write_of_the_day_file_works(monkeypatch, tmp_path, clock, sleeps, capsys):
    """The day's file needs tidying first, a rest that has ended, and that
    write fails too. Neither may keep the check from stopping the run."""
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / STATE).write_text(json.dumps({
        "day_started": (START - timedelta(hours=1)).isoformat(), "orders_opened": 1,
        "rest_until": (START - timedelta(minutes=1)).isoformat()}), encoding="utf-8")
    app, _ = an_app(monkeypatch, tmp_path)
    app.stats["mode"] = "all"

    def nothing_written(*_a, **_k):
        raise PermissionError("an invented held file")

    monkeypatch.setattr(app_mod, "atomic_write_json", nothing_written)
    stopped, asked = checked(monkeypatch, app, ROBOT)
    assert stopped is True and asked == [], (stopped, asked)
    assert "could not be saved" in printed(capsys)


def test_a_check_once_the_day_is_over_is_answered_as_it_always_was(monkeypatch, tmp_path, clock, sleeps):
    app, _ = an_app(monkeypatch, tmp_path)
    take(app, purchases(1))
    app.stats["mode"] = "all"
    clock.move(hours=25)
    stopped, asked = checked(monkeypatch, app, ROBOT)
    assert stopped is False and len(asked) == 1


def test_a_check_in_a_support_report_rests_nothing(monkeypatch, tmp_path, clock, sleeps):
    app, _ = an_app(monkeypatch, tmp_path)
    take(app, purchases(1))
    app.stats["mode"] = "diagnose"
    stopped, asked = checked(monkeypatch, app, ROBOT)
    assert stopped is False and len(asked) == 1


def test_a_rest_outlives_the_day_it_began_in(monkeypatch, tmp_path, clock, sleeps):
    app, _ = an_app(monkeypatch, tmp_path, orders_per_day=0)
    take(app, purchases(1))
    clock.move(hours=3)
    app.stats["mode"] = "all"
    assert checked(monkeypatch, app, ROBOT)[0] is True
    clock.move(hours=21, minutes=1)        # the day is over, the rest is not
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=0)
    assert take(app, purchases(2)[1:]) is True and opened.orders == []
    clock.move(hours=3)
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=0)
    assert take(app, purchases(2)[1:]) is False and opened.orders == [ORDERS[1]]


# -- the pace ---------------------------------------------------------------------------

@pytest.mark.parametrize("set_to, between", [
    ({"delay_min_seconds": 2.0, "delay_max_seconds": 4.5}, (5.0, 10.0)),
    ({"delay_min_seconds": 2, "delay_max_seconds": 4.5}, (5.0, 10.0)),
    ({"delay_min_seconds": 2.0, "delay_max_seconds": 4.0}, (5.0, 10.0)),
    ({}, (5.0, 10.0)),
    ({"delay_min_seconds": 2.0, "delay_max_seconds": 6.0}, (2.0, 6.0)),
    ({"delay_min_seconds": 3.0, "delay_max_seconds": 6.0}, (3.0, 6.0)),
    ({"delay_min_seconds": 0, "delay_max_seconds": 0}, (0.0, 0.0)),
])
def test_the_wait_between_orders(monkeypatch, tmp_path, sleeps, set_to, between):
    # time.sleep as well, so the old code's own waits are noted, not waited.
    monkeypatch.setattr(app_mod.time, "sleep", sleeps)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                               "profile_dir": str(tmp_path / "profile"), **set_to}), encoding="utf-8")
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg)]))
    for _ in range(20):
        app._delay()
        app._delay(0.5)
    orders, pages = sleeps.asked[0::2], sleeps.asked[1::2]
    assert len(orders) == 20, sleeps.asked
    assert all(between[0] <= s <= between[1] for s in orders), orders
    assert all(between[0] / 2 <= s <= between[1] / 2 for s in pages), pages


def test_a_break_every_so_many_orders_and_none_after_the_last(monkeypatch, tmp_path, clock, sleeps, capsys):
    app, opened = an_app(monkeypatch, tmp_path, break_every_orders=2,
                         break_min_minutes=2, break_max_minutes=5)
    assert take(app, purchases()) is False
    assert opened.orders == ORDERS
    breaks = sleeps.breaks()
    assert len(breaks) == 2, sleeps.asked
    assert all(120 <= b <= 300 for b in breaks), breaks
    out = printed(capsys)
    assert out.count("break") >= 2, out


def test_no_break_just_before_the_days_limit_stops_the_run(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, orders_per_day=3, break_every_orders=3)
    assert take(app, purchases()) is True
    assert opened.orders == ORDERS[:3] and sleeps.breaks() == []


def test_breaks_are_counted_in_each_run(monkeypatch, tmp_path, clock, sleeps):
    for part in (purchases()[:2], purchases()[2:4]):
        app, _ = an_app(monkeypatch, tmp_path, break_every_orders=3)
        assert take(app, part) is False
    assert sleeps.breaks() == []


def test_a_break_skips_orders_already_saved(monkeypatch, tmp_path, clock, sleeps):
    app, opened = an_app(monkeypatch, tmp_path, break_every_orders=2)
    done = purchases()[1]
    app.progress.update(done.key, {"downloaded_ok": True, "state": "COMPLETED"})
    assert take(app, purchases()) is False
    assert opened.orders == [ORDERS[0], ORDERS[2], ORDERS[3], ORDERS[4]]
    assert len(sleeps.breaks()) == 1, sleeps.asked


def test_the_pace_is_said_once(monkeypatch, tmp_path, clock, sleeps, capsys):
    app, _ = an_app(monkeypatch, tmp_path)
    take(app, purchases())
    out = printed(capsys)
    assert out.count("Amazon orders a day") == 1, out
    assert "at most 200 Amazon orders a day" in out, out


def test_the_settings_reach_every_install():
    here = Path(app_mod.__file__).resolve().parent
    template = json.loads((here / "config.example.json").read_text(encoding="utf-8"))
    want = {"orders_per_day": 200, "break_every_orders": 25,
            "break_min_minutes": 2, "break_max_minutes": 5}
    for key, value in want.items():
        assert template.get(key) == value, key
        assert storage.SPEC.config_defaults.get(key) == value, key
    assert (template["delay_min_seconds"], template["delay_max_seconds"]) == (5.0, 10.0)


def test_an_install_without_the_settings_gets_them(tmp_path):
    app = testkit.receipt_app(app_mod, tmp_path)
    assert app.config["orders_per_day"] == 200
    assert app.config["break_every_orders"] == 25
