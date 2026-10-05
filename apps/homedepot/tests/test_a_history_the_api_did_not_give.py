"""Discovery against a Home Depot order history request that does not give
the history, in a real browser.

The purchase history asked for its orders, so the session is fine, and
then the same request, asked again from inside the page a page of orders
at a time, did not give them. It refused, gave no answer, or answered
with something that was not the order history. A refused page wrote a
failure file and discovery printed "Discovery complete" and went on, and a
page with no answer at all or an answer that was not the history was read
as the end of an empty one, so Pilot and Run All finished clean with the
orders missed. A history that did not come is not an empty one, and the
run stops the way it does for a history page that never asked, claiming
nothing.

When the request stops partway, the orders on the pages it gave are real,
so they are kept and the run goes on with them. The older ones are
missing, so the run may not call itself finished either, and Resume reads
the history again before anything else.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page and the history request come from a server
on this machine and the browser resolves no host name, so nothing reaches
Home Depot. Every order number, date, amount and item is invented.
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
import homedepot_receipts as app_mod
import homedepot_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HISTORY = "/myaccount/purchase-history"
ASK = "/oms/customer/order/v1/user/USER000001/orderhistory"
DETAILS = "/myaccount/order-details"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# Home Depot's own page asks for its orders a few at a time, and this app
# asks for as many as the page does, two here, so a short history still
# takes more than one page.
PAGE_SIZE = 2

# Three online orders, newest first as Home Depot lists them, with what
# each one's receipt shows.
ORDERS = {
    "W000000041": ("2026-09-12T14:03:00", "September 12, 2026", 58.20, "Invented LED Light Bulb 4 Pack"),
    "W000000042": ("2026-08-30T10:15:00", "August 30, 2026", 23.41, "Invented Garden Hose 50 ft"),
    "W000000043": ("2026-05-14T09:41:00", "May 14, 2026", 112.00, "Invented Paint Roller Kit"),
}
NEWER = ["W000000041", "W000000042"]
OLDER = ["W000000043"]


def keys(numbers):
    return sorted("Online:" + n for n in numbers)


def order(number):
    sold, _shown, total, _item = ORDERS[number]
    return {"orderNumbers": [number], "orderOrigin": "online", "type": "COM",
            "salesDate": sold, "totalAmount": total, "transactionKey": "k" + number[-2:]}


def details_page(number):
    """The order's details page, with its receipt in a block shown only in
    print, as Home Depot's is."""
    _sold, shown, total, item = ORDERS[number]
    money = "$%.2f" % total
    return r"""<!doctype html><html><head><title>Order Details</title><style>
.sui-hidden { display: none; }
@media print { .print\:sui-block { display: block; } }
</style></head><body>
<header>Shop All Services DIY Me</header>
<main>
  <h1>ORDER DETAILS</h1><h2>ORDER # %s</h2>
  <div class="sui-hidden print:sui-block sui-m-[10px]">
    <p>Date Ordered: %s</p><p>Order Number: %s</p><p>Order Total: %s</p>
    <h3>Delivery</h3><h3>Product Information</h3>
    <p>%s</p><p>1</p><p>%s</p><p>Model #INV-36-0</p><p>Store SKU #1000000001</p>
    <h3>Payment Information</h3><p>Payment Method</p><p>AX | Ending in 0000</p>
    <h3>Payment Details</h3><p>Subtotal</p><p>%s</p><p>Order Total</p><p>%s</p>
  </div>
</main><footer>Store Locator | Home Depot</footer></body></html>""" % (
        number, shown, number, money, item, money, money, money)


# The history asks for its orders the way Home Depot's own page does, one
# POST with the range it wants and its own page size. This app's asks say
# they accept JSON, and the page's does not, which is how the two are told
# apart below.
LISTED = """<!doctype html><html><head><title>Purchase History</title></head><body>
<h1>Purchase History</h1>
<a href="/myaccount/order-details?orderNumber=W000000041">Order #W000000041</a>
<script>
fetch('%s', {method: 'POST', headers: {'content-type': 'application/json'},
  body: JSON.stringify({orderHistoryRequest: {pageSize: %d, pageNumber: 1,
    startDate: '2024-09-29', endDate: '2026-09-29', timezone: 'America/New_York'}})});
</script></body></html>""" % (ASK, PAGE_SIZE)


# What the history request answers for one page.
def listed(numbers, count):
    return ("body", "application/json",
            json.dumps({"orderCount": count, "orders": [order(n) for n in numbers]}))


def paged(numbers, count=None, cap=PAGE_SIZE, clamp=False):
    """Every page the way a server pages a list, at most `cap` orders a page
    whatever is asked for, counted from the page number at that size, with
    Home Depot's count of them when `count` is given. With `clamp` a page
    past the end answers the last page again, as some servers do."""
    return ("paged", numbers, count, cap, clamp)


def refused(status):
    return ("status", status)


# The connection closed with nothing sent, which the page's fetch meets as a
# network error rather than an answer.
DROPPED = ("drop",)
# A page where the history should be, which is what a bot check sends.
A_PAGE = ("body", "text/html; charset=utf-8",
          "<!doctype html><html><head><title>The Home Depot</title></head>"
          "<body><p>One moment, please.</p></body></html>")
# An answer with no order history in it.
NO_HISTORY = ("body", "application/json", json.dumps({"errors": [{"message": "unavailable"}]}))

# Every way the first page can fail to come, and the word the failure file
# keeps for why it stopped.
NO_FIRST_PAGE = {
    "refused 401": (refused(401), "refused", 401),
    "refused 403": (refused(403), "refused", 403),
    "refused 429": (refused(429), "refused", 429),
    "no answer": (DROPPED, "no answer", 0),
    "a page in its place": (A_PAGE, "no list", 200),
    "an answer with no history": (NO_HISTORY, "no list", 200),
}


class FakeHomeDepot:
    """What the made-up site shows, set by each test, and what its history
    request answers for each page."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.answers = {}
        self.paged = None
        self.asked = []
        self.sizes = []
        self.seen = []


SITE = FakeHomeDepot()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        SITE.seen.append(url.path)
        number = (parse_qs(url.query).get("orderNumber") or [""])[0]
        if url.path == HISTORY:
            self._answer(LISTED, "text/html; charset=utf-8")
        elif url.path == DETAILS and number in ORDERS:
            self._answer(details_page(number), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path != ASK:
            self.send_error(404)
            return
        wanted = (json.loads(body or b"{}").get("orderHistoryRequest") or {})
        number = wanted.get("pageNumber") or 1
        if self.headers.get("Accept") == "application/json":
            # This app's own ask, not the one the page made as it loaded.
            SITE.asked.append(number)
            SITE.sizes.append(wanted.get("pageSize"))
        answer = SITE.paged or SITE.answers.get(number, refused(404))
        if answer[0] == "paged":
            _kind, numbers, count, cap, clamp = answer
            start = (number - 1) * cap
            if clamp and numbers and start >= len(numbers):
                start = (len(numbers) - 1) // cap * cap
            value = {"orders": [order(n) for n in numbers[start:start + cap]]}
            if count is not None:
                value["orderCount"] = count
            self._answer(json.dumps(value), "application/json")
            return
        if answer[0] == "drop":
            self.close_connection = True
            return
        if answer[0] == "status":
            self._answer(json.dumps({"errors": [{"message": "refused"}]}), "application/json",
                         status=answer[1])
        else:
            self._answer(answer[2], answer[1])

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
def fake_home_depot(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short."""
    SITE.reset()
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setattr(site, "DETAILS_URL", server + DETAILS)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + HISTORY)
    # The history request is only kept, and asked again, on Home Depot's
    # own host, and only a details address on it is opened. Here that host
    # is this machine.
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    # Longer than the others. A request that comes late is not looked for
    # again, so a slow machine gets time for the page to make it.
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 4000, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
    real_wait = site.wait_for_details
    monkeypatch.setattr(site, "wait_for_details",
                        lambda page, timeout_ms=30000: real_wait(page, timeout_ms=min(timeout_ms, 4000)))
    return SITE


def config_for(tmp_path, cdp_url):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def folded(out):
    """What the app printed, with its line breaks read as spaces, since a
    message is wrapped wherever it happens to fill a line."""
    return " ".join(out.split())


def stopped_run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to stop rather than finish. Leaving on SystemExit
    with the exception in flight is what the core reports to the panel as
    stopped, rather than as a clean finish, and core/tests/test_run_reporting.py
    holds every app's main to that. What it printed, unfolded."""
    cfg = config_for(tmp_path, cdp_url)
    with pytest.raises(SystemExit) as stopped:
        app_mod.main([*flags, "--config", str(cfg)])
    out = capsys.readouterr().out
    assert stopped.value.code == 0, out
    return out


def finished_run(tmp_path, cdp_url, capsys, *flags):
    """The run, which has to finish. What it printed, unfolded."""
    cfg = config_for(tmp_path, cdp_url)
    assert app_mod.main([*flags, "--config", str(cfg)]) == 0
    return capsys.readouterr().out


def either_run(tmp_path, cdp_url, capsys, *flags):
    """The run, however it ends, for a test about what comes after it."""
    cfg = config_for(tmp_path, cdp_url)
    try:
        app_mod.main([*flags, "--config", str(cfg)])
    except SystemExit:
        pass
    capsys.readouterr()


def panel_reads(out):
    """The counts the panel reads, off the line the core prints for it."""
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def known(tmp_path):
    path = tmp_path / "out" / "discovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def downloaded(tmp_path):
    """The purchases whose receipt was saved and passed its check."""
    path = tmp_path / "out" / "progress.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(k for k, r in done.items()
                  if isinstance(r, dict) and r.get("downloaded_ok")
                  and Path(r.get("pdf_path") or "").is_file())


def failure_files(tmp_path):
    return list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


def how_far_it_got(tmp_path):
    """What the failure file says of the history request, in counts and in
    this app's own words, which is all a file a tester posts may carry."""
    files = failure_files(tmp_path)
    assert len(files) == 1, files
    report = json.loads(files[0].read_text(encoding="utf-8"))
    return (report.get("extra") or {}).get("postmortem")


def receipts_opened():
    return [p for p in SITE.seen if p == DETAILS]


# -- a first page that never came ----------------------------------------------------

@pytest.mark.parametrize("answer, why, status", list(NO_FIRST_PAGE.values()), ids=list(NO_FIRST_PAGE))
def test_a_pilot_stops_when_the_history_request_gives_no_first_page(attached, answer, why, status,
                                                                    tmp_path, capsys):
    """A refusal wrote a failure file and the run finished as though the
    account had nothing new, and a page with no answer, or an answer that
    was not the history, was read as an empty history. Either way the
    panel read the run as clean."""
    SITE.answers = {1: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "purchase history did not come" in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert 1 in SITE.asked, "the history request really was asked"
    assert not known(tmp_path), "nothing is recorded from a history that did not come"
    assert not receipts_opened(), "and no receipt is opened"
    assert how_far_it_got(tmp_path) == {"pages": 0, "last": False, "stop": why, "status": status}


def test_with_somebody_there_it_asks_them_to_look_and_then_asks_again(attached, tmp_path, capsys,
                                                                      monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say so it asks for the history again. Past a few questions
    they give up with Ctrl+C, so a loop that asks forever fails here rather
    than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.answers = {1: listed(OLDER, 1)}
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    SITE.answers = {1: refused(403)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    assert len(asked) == 1 and "ask Home Depot" in asked[0], asked
    assert sorted(known(tmp_path)) == keys(OLDER)
    assert "Discovery complete" in folded(out)


# -- a history cut short --------------------------------------------------------------

@pytest.mark.parametrize("answer, why, status", [(refused(429), "refused", 429),
                                                 (DROPPED, "no answer", 0),
                                                 (A_PAGE, "no list", 200)],
                         ids=["refused", "no answer", "a page in its place"])
def test_a_history_cut_short_is_used_and_the_run_does_not_finish(attached, answer, why, status,
                                                                 tmp_path, capsys):
    """The first page came and the second did not. The orders on the first
    are real, so the pilot downloads them, and the older ones are missing,
    so it stops rather than finish."""
    SITE.answers = {1: listed(NEWER, 3), 2: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Only 1 page(s) of your purchase history came" in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert sorted(known(tmp_path)) == keys(NEWER), "what it gave is kept"
    assert downloaded(tmp_path) == keys(NEWER), "and used"
    assert how_far_it_got(tmp_path) == {"pages": 1, "last": False, "stop": why, "status": status}


@pytest.mark.parametrize("command", [["--all", "--yes"], ["--discover"]], ids=["run all", "discover"])
def test_run_all_and_discover_do_not_finish_on_a_history_cut_short(attached, command, tmp_path,
                                                                   capsys):
    """Each command that reads the history stops in its own place, Run All
    once it has downloaded what came and Discover once it has listed it."""
    SITE.answers = {1: listed(NEWER, 3), 2: refused(429)}
    out = stopped_run(tmp_path, attached, capsys, *command)

    said = folded(out)
    assert "Only 1 page(s) of your purchase history came" in said, said
    assert "Discovery complete" not in said, said
    assert sorted(known(tmp_path)) == keys(NEWER)
    if command[0] == "--all":
        assert downloaded(tmp_path) == keys(NEWER)
        assert panel_reads(out)["stopped"] == 1


# -- what worked before -------------------------------------------------------------------

def test_a_history_of_several_pages_is_read_to_its_end(attached, tmp_path, capsys):
    """Every page is read until one comes back short, and only then is
    discovery complete."""
    SITE.answers = {1: listed(NEWER, 3), 2: listed(OLDER, 3)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "Discovery complete" in said and "did not come" not in said, said
    assert sorted(known(tmp_path)) == keys(NEWER + OLDER)
    assert SITE.asked == [1, 2]
    assert not failure_files(tmp_path)


def test_a_history_with_no_orders_in_it_is_still_read_as_one(attached, tmp_path, capsys):
    """Home Depot keeps two years, and an account with no order in them
    answers with an empty list. That is a history read whole."""
    SITE.answers = {1: listed([], 0)}
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "did not come" not in said, said
    assert not known(tmp_path)
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


def test_an_answer_with_no_orders_and_no_errors_is_still_read_as_an_empty_history(attached,
                                                                                tmp_path,
                                                                                capsys):
    """What Home Depot answers an account with no orders was never seen. An
    answer carrying errors, or a page, is not the history, but one that is
    only missing the order list is read as an empty history, as it always
    was, rather than stop every run of an account with nothing to find."""
    SITE.answers = {1: ("body", "application/json", json.dumps({"customerType": "B2C"}))}
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    assert "Discovery complete" in folded(out), out
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


# -- a history longer than a page -------------------------------------------------------

ALL = NEWER + OLDER


def test_a_history_is_asked_for_a_page_at_a_time_of_the_pages_own_size(attached, tmp_path,
                                                                        capsys):
    """Home Depot was asked for twenty orders a page whatever its own page
    asks for, and a page shorter than twenty was taken for the last. Where
    Home Depot gives no more than its own page size, every page past the
    first was missed while the run finished clean."""
    SITE.paged = paged(ALL, count=3)
    out = finished_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "Discovery complete" in said, said
    assert sorted(known(tmp_path)) == keys(ALL)
    assert SITE.asked == [1, 2] and set(SITE.sizes) == {PAGE_SIZE}, (SITE.asked, SITE.sizes)
    assert not failure_files(tmp_path)


def test_pages_shorter_than_asked_are_read_on_to_the_count(attached, tmp_path, capsys):
    """Home Depot's count says how many orders there are, so a page shorter
    than asked is not the end while the count says more."""
    SITE.paged = paged(ALL, count=3, cap=1)
    out = finished_run(tmp_path, attached, capsys, "--discover")

    assert "Discovery complete" in folded(out), out
    assert sorted(known(tmp_path)) == keys(ALL)
    assert SITE.asked == [1, 2, 3]


def test_without_a_count_a_short_page_is_still_the_end(attached, tmp_path, capsys):
    SITE.paged = paged(ALL)
    out = finished_run(tmp_path, attached, capsys, "--discover")

    assert "Discovery complete" in folded(out), out
    assert sorted(known(tmp_path)) == keys(ALL)
    assert SITE.asked == [1, 2]


@pytest.mark.parametrize("clamp", [False, True], ids=["an empty page", "the last page again"])
def test_a_count_larger_than_what_comes_ends_at_a_page_with_nothing_new(attached, clamp,
                                                                        tmp_path, capsys):
    """A count larger than the orders Home Depot gives ends at the first page
    with nothing new on it, empty or the last page again, rather than ask
    the same page dozens of times or stop every run. The run finishes,
    since nothing was refused."""
    SITE.paged = paged(ALL, count=5, clamp=clamp)
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "did not come" not in said, said
    assert sorted(known(tmp_path)) == keys(ALL)
    assert SITE.asked == [1, 2, 3]
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


# -- Resume after a run that stopped ---------------------------------------------------

def test_resume_reads_the_history_after_a_pilot_that_never_got_it(attached, tmp_path, capsys):
    """The panel says to press Resume once a run has stopped. Resume works
    from the orders already found, and the stopped pilot found none, so it
    had nothing to do and finished clean, the history never read."""
    SITE.answers = {1: refused(403)}
    either_run(tmp_path, attached, capsys, "--pilot")

    SITE.asked.clear()
    SITE.answers = {1: listed(OLDER, 1)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked for the history"
    assert downloaded(tmp_path) == keys(OLDER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_reads_what_a_history_cut_short_left_out(attached, tmp_path, capsys):
    """Resume after a history cut short used to download the part that
    came and finish clean, the older orders never looked for."""
    SITE.answers = {1: listed(NEWER, 3), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {1: listed(NEWER, 3), 2: listed(OLDER, 3)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert sorted(known(tmp_path)) == keys(NEWER + OLDER)
    assert downloaded(tmp_path) == keys(NEWER + OLDER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_goes_on_with_what_was_found_when_the_history_is_refused(attached, tmp_path,
                                                                       capsys):
    """Resume worked from the orders already found and never asked for the
    history. Now it asks first, and when Home Depot refuses, it still
    downloads the orders it has, as it did, and does not call itself
    finished."""
    SITE.answers = {1: listed(NEWER, 3), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {1: refused(403)}
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert "purchase history did not come" in folded(out), out
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_a_whole_history_does_not_read_it_again(attached, tmp_path, capsys):
    """A Discover that read the history to its end leaves nothing for
    Resume to read again, so Resume goes straight to the orders found."""
    SITE.answers = {1: listed(OLDER, 1)}
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.asked.clear()
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert not SITE.asked and ASK not in SITE.seen, "Resume left the history alone"
    assert downloaded(tmp_path) == keys(OLDER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_that_meets_a_history_cut_short_again_does_not_finish(attached, tmp_path, capsys):
    """The pilot downloaded what came, so when Resume reads the history
    again and it is cut short at the same place, there is nothing new to
    download. That is still not a finished run."""
    SITE.answers = {1: listed(NEWER, 3), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--pilot")
    assert downloaded(tmp_path) == keys(NEWER)

    SITE.asked.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked for the history"
    assert "Nothing to resume" in folded(out), out
    assert panel_reads(out)["stopped"] == 1
