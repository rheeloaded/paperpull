"""Discovery against a Kroger purchase history API that does not give the
history, in a real browser.

The purchase history page drew, so the session is fine, and then the
history API the page asks did not give the history. It refused, gave no
answer, or answered with something that was not the list. Kroger sits
behind Akamai Bot Manager, so a call refused from inside a page that drew
is a real possibility. Discovery read every one of those as a history with
nothing in it, printed "Discovery complete" and went on, so Pilot and Run
All finished clean with every new purchase missed. A history that did not
come is not an empty one, and the run stops the way it does for a history
page that never drew, claiming nothing.

When the API stops partway, the purchases on the pages it gave are real,
so they are kept and the run goes on with them. The oldest are missing,
so the run may not call itself finished either, and Resume reads the
history again before anything else.

An account with no loyalty card is told so in Kroger's own words, and what
the API answers for one has never been seen, so that message stands
whatever the API does.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page and the history API come from a server on
this machine and the browser resolves no host name, so nothing reaches
Kroger. Every key, store, date, amount and item is invented.
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
import kroger_receipts as app_mod
import kroger_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HISTORY = "/mypurchases"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

# Four purchases, newest first as Kroger lists them, two on each page.
STORE_KEY = "703~00218~2026-08-02~011~4410"
PICKUP_KEY = "703~00218~2026-07-27~090~3871"
OLD_STORE_KEY = "703~00218~2026-05-14~012~2906"
OLD_PICKUP_KEY = "703~00218~2026-04-30~090~1552"

NEWER_KEYS = ["In-Store:" + STORE_KEY, "Online:" + PICKUP_KEY]
ALL_KEYS = NEWER_KEYS + ["In-Store:" + OLD_STORE_KEY, "Online:" + OLD_PICKUP_KEY]


def record(key, kind, when, total):
    return {"receiptKey": key, "purchaseType": kind, "status": "COMPLETED",
            "createdDateTime": {"value": when}, "total": total,
            "lineItems": [{"upc": "0000000004011", "quantity": 1}]}


NEWER = [record(STORE_KEY, "IN_STORE", "2026-08-02T15:20:00Z", "USD 31.62"),
         record(PICKUP_KEY, "SELF_SERVE_PICKUP", "2026-07-27T17:05:00Z", "USD 47.18")]
OLDER = [record(OLD_STORE_KEY, "IN_STORE", "2026-05-14T12:41:00Z", "USD 12.09"),
         record(OLD_PICKUP_KEY, "SELF_SERVE_PICKUP", "2026-04-30T19:55:00Z", "USD 66.35")]

# The receipt page of each, in the shape a tester's receipt was recorded in
# (#41), the order's labeled lines and the store in the header, then Order
# Summary, Item Details and Payment Details.
RECEIPTS = {
    STORE_KEY: ("In Store", "Aug. 2, 2026", "$31.62", "Invented Rolled Oats, 42 oz"),
    PICKUP_KEY: ("Pickup", "Jul. 27, 2026", "$47.18", "Invented Sparkling Water, 12 pk"),
    OLD_STORE_KEY: ("In Store", "May 14, 2026", "$12.09", "Invented Honeycrisp Apples"),
    OLD_PICKUP_KEY: ("Pickup", "Apr. 30, 2026", "$66.35", "Invented Laundry Detergent"),
}


def receipt_page(key):
    kind, date, total, item = RECEIPTS[key]
    return """<!doctype html><html><head><title>Receipt</title></head><body>
<nav>Kroger  My Purchases  Weekly Ad  Digital Coupons</nav>
<main><div class="max-receipt-content">
<button id="receipt-print-button">Print</button>
<div id="receipt-print-area" data-testid="POT-original-receipt">
<div data-testid="PO-invoice-header"><p>Order Type: %s</p><p>Order Date: %s</p>
<p>Order Number: %s</p><p>Metro Market</p></div>
<h3>Order Summary</h3><p>Order Total</p><p>%s</p>
<h3>Item Details</h3><p>1 Items</p><p>%s</p><p>%s</p><p>1 x %s each</p>
<h3>Payment Details</h3><p>%s</p>
</div></div></main></body></html>""" % (kind, date, key, total, item, total, total, total)


LISTED = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1>
<div data-testid="PO-NonPendingPurchase"><p>In-Store</p><p>Aug 2, 2026</p><p>$31.62</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
<div data-testid="PO-NonPendingPurchase"><p>Pickup</p><p>Jul 27, 2026</p><p>$47.18</p>
  <a href="/mypurchases/detail/%s">See Order Details</a></div>
</main></body></html>""" % (STORE_KEY, PICKUP_KEY)

EMPTY = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1><h2>No Orders Yet</h2>
<p>Looks like there aren't any orders to show.</p></main></body></html>"""

NO_LOYALTY = """<!doctype html><html><head><title>Purchase History - Kroger</title></head><body>
<main><h1>Purchase History</h1><p>Missing Loyalty ID</p>
<p>Add a Shopper's Card to your account to see your purchases.</p></main></body></html>"""

HOME = """<!doctype html><html><head><title>Kroger</title></head>
<body><h1>Kroger</h1></body></html>"""


# What the history API answers for one page.
def listed(records, last):
    return ("page", records, last)


def refused(status):
    return ("status", status)


# The connection closed with nothing sent, which the page's fetch meets as a
# network error rather than an answer.
DROPPED = ("drop",)
# A page where the list should be, which is what a bot check sends.
NOT_JSON = ("body", "text/html; charset=utf-8",
            "<!doctype html><html><head><title>Kroger</title></head>"
            "<body><p>One moment, please.</p></body></html>")


def without_the_list(answer):
    return ("body", "application/json", json.dumps(answer))


# Every way the first page can fail to come, and the word the failure file
# keeps for why it stopped.
NO_FIRST_PAGE = {
    "refused 401": (refused(401), "refused"),
    "refused 403": (refused(403), "refused"),
    "refused 429": (refused(429), "refused"),
    "no answer": (DROPPED, "no answer"),
    "a page in its place": (NOT_JSON, "no list"),
    "an answer with no history": (without_the_list(
        {"data": None, "errors": [{"message": "unavailable"}]}), "no list"),
    "a history with no list": (without_the_list(
        {"data": {"postOrderSearch": {"data": None, "isLastPage": True}}}), "no list"),
}


class FakeKroger:
    """What the made-up site shows, set by each test."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = LISTED
        self.answers = {}
        self.asked = []
        self.seen = []


SITE = FakeKroger()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        url = urlsplit(self.path)
        SITE.seen.append(url.path)
        status = 200
        if url.path == HISTORY:
            body, kind = SITE.orders, "text/html; charset=utf-8"
        elif url.path == site.SEARCH_API:
            page_no = int((parse_qs(url.query).get("pageNo") or ["1"])[0])
            SITE.asked.append(page_no)
            answer = SITE.answers.get(page_no, refused(404))
            if answer[0] == "drop":
                self.close_connection = True
                return
            if answer[0] == "status":
                status, kind = answer[1], "application/json"
                body = json.dumps({"errors": [{"message": "refused"}]})
            elif answer[0] == "body":
                kind, body = answer[1], answer[2]
            else:
                body = json.dumps({"data": {"postOrderSearch": {
                    "data": answer[1], "pageNo": page_no, "pageSize": site.PAGE_SIZE,
                    "isLastPage": answer[2]}}})
                kind = "application/json"
        elif url.path.startswith(site.RECEIPT_PATH) and \
                url.path[len(site.RECEIPT_PATH):] in RECEIPTS:
            body, kind = receipt_page(url.path[len(site.RECEIPT_PATH):]), "text/html; charset=utf-8"
        elif url.path == "/":
            body, kind = HOME, "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
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
def fake_kroger(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the history's thirty seconds included."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800, raising=False)
    monkeypatch.setattr(site, "SETTLE_MS", 0, raising=False)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500, raising=False)
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
    """What the failure file says of the history API, which is how a
    tester's file will show how Kroger ends a long history."""
    files = failure_files(tmp_path)
    assert len(files) == 1, files
    report = json.loads(files[0].read_text(encoding="utf-8"))
    return (report.get("extra") or {}).get("postmortem")


def receipts_opened():
    return [p for p in SITE.seen if p.startswith(site.RECEIPT_PATH)]


# -- a first page that never came ----------------------------------------------------

@pytest.mark.parametrize("answer, why", list(NO_FIRST_PAGE.values()), ids=list(NO_FIRST_PAGE))
def test_a_pilot_stops_when_the_history_api_gives_no_first_page(attached, answer, why, tmp_path,
                                                                capsys):
    """It used to finish as though the account had nothing new, and the
    panel read the run as clean."""
    SITE.answers = {1: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "purchase history did not come" in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert 1 in SITE.asked, "the history API really was asked"
    assert not known(tmp_path), "nothing is recorded from a history that did not come"
    assert not receipts_opened(), "and no receipt is opened"
    facts = how_far_it_got(tmp_path)
    assert facts["pages"] == 0 and facts["last"] is False and facts["stop"] == why, facts


def test_a_page_that_says_the_history_is_empty_does_not_stand_in_for_the_api(attached, tmp_path,
                                                                            capsys):
    """The API gives an empty account's history as an empty list on its
    last page, and that is what makes a history empty. When the API
    refuses, the page's own words are all there is, so the run stops as it
    does for any history that did not come."""
    SITE.orders, SITE.answers = EMPTY, {1: refused(403)}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "purchase history did not come" in folded(out), out
    assert panel_reads(out)["stopped"] == 1


def test_with_somebody_there_it_asks_them_to_look_and_then_asks_again(attached, tmp_path, capsys,
                                                                      monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say so it asks the history API again. Past a few questions
    they give up with Ctrl+C, so a loop that asks forever fails here rather
    than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.answers = {1: listed(NEWER, last=True)}
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    SITE.answers = {1: refused(403)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    assert len(asked) == 1 and "ask Kroger" in asked[0], asked
    assert sorted(known(tmp_path)) == sorted(NEWER_KEYS)
    assert "Discovery complete" in folded(out)


# -- a history cut short --------------------------------------------------------------

@pytest.mark.parametrize("answer, why, status", [(refused(429), "refused", 429),
                                                 (DROPPED, "no answer", 0)],
                         ids=["refused", "no answer"])
def test_a_history_cut_short_is_used_and_the_run_does_not_finish(attached, answer, why, status,
                                                                 tmp_path, capsys):
    """The first page came and the second did not. The purchases on the
    first are real, so the pilot downloads them, and the oldest are
    missing, so it stops rather than finish. A page with no answer at all
    used to lose the pages before it as well, and the run found nothing."""
    SITE.answers = {1: listed(NEWER, last=False), 2: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Only 1 page(s) of your purchase history came" in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert sorted(known(tmp_path)) == sorted(NEWER_KEYS), "what it gave is kept"
    assert downloaded(tmp_path) == sorted(NEWER_KEYS), "and used"
    assert how_far_it_got(tmp_path) == {"pages": 1, "last": False, "stop": why,
                                        "status": status}


@pytest.mark.parametrize("command", [["--all", "--yes"], ["--discover"]], ids=["run all", "discover"])
def test_run_all_and_discover_do_not_finish_on_a_history_cut_short(attached, command, tmp_path,
                                                                   capsys):
    """Each command that reads the history stops in its own place, Run All
    once it has downloaded what came and Discover once it has listed it."""
    SITE.answers = {1: listed(NEWER, last=False), 2: refused(429)}
    out = stopped_run(tmp_path, attached, capsys, *command)

    said = folded(out)
    assert "Only 1 page(s) of your purchase history came" in said, said
    assert "Discovery complete" not in said, said
    assert sorted(known(tmp_path)) == sorted(NEWER_KEYS)
    if command[0] == "--all":
        assert downloaded(tmp_path) == sorted(NEWER_KEYS)
        assert panel_reads(out)["stopped"] == 1


def test_a_history_of_several_pages_is_read_to_its_last(attached, tmp_path, capsys):
    """What worked before still works. Every page is read until the API
    says it gave the last one, and only then is discovery complete."""
    SITE.answers = {1: listed(NEWER, last=False), 2: listed(OLDER, last=True)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "Discovery complete" in said and "did not come" not in said, said
    assert sorted(known(tmp_path)) == sorted(ALL_KEYS)
    assert sorted(set(SITE.asked)) == [1, 2]
    assert not failure_files(tmp_path)


# -- Resume after a run that stopped ---------------------------------------------------

def test_resume_reads_the_history_after_a_pilot_that_never_got_it(attached, tmp_path, capsys):
    """The panel says to press Resume once a run has stopped. Resume works
    from the purchases already found, and the stopped pilot found none, so
    it had nothing to do and finished clean, the history never read."""
    SITE.answers = {1: refused(403)}
    either_run(tmp_path, attached, capsys, "--pilot")

    SITE.asked.clear()
    SITE.answers = {1: listed(NEWER, last=True)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked the history API"
    assert downloaded(tmp_path) == sorted(NEWER_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_reads_what_a_history_cut_short_left_out(attached, tmp_path, capsys):
    """Resume after a history cut short used to download the part that
    came and finish clean, the older purchases never looked for."""
    SITE.answers = {1: listed(NEWER, last=False), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {1: listed(NEWER, last=False), 2: listed(OLDER, last=True)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert sorted(known(tmp_path)) == sorted(ALL_KEYS)
    assert downloaded(tmp_path) == sorted(ALL_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_goes_on_with_what_was_found_when_the_history_is_refused(attached, tmp_path,
                                                                       capsys):
    """Resume worked from the purchases already found and never asked the
    history API. Now it asks first, and when Kroger refuses, it still
    downloads the purchases it has, as it did, and does not call itself
    finished."""
    SITE.answers = {1: listed(NEWER, last=False), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {1: refused(403)}
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert "purchase history did not come" in folded(out), out
    assert downloaded(tmp_path) == sorted(NEWER_KEYS)
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_a_whole_history_does_not_read_it_again(attached, tmp_path, capsys):
    """A Discover that read the history to its last page leaves nothing for
    Resume to read again, so Resume goes straight to the purchases found."""
    SITE.answers = {1: listed(NEWER, last=True)}
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.asked.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert not SITE.asked, "Resume left the history API alone"
    assert downloaded(tmp_path) == sorted(NEWER_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_that_meets_a_history_cut_short_again_does_not_finish(attached, tmp_path, capsys):
    """The pilot downloaded what came, so when Resume reads the history
    again and it is cut short at the same place, there is nothing new to
    download. That is still not a finished run."""
    SITE.answers = {1: listed(NEWER, last=False), 2: refused(429)}
    either_run(tmp_path, attached, capsys, "--pilot")
    assert downloaded(tmp_path) == sorted(NEWER_KEYS)

    SITE.asked.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked the history API"
    assert "Nothing to resume" in folded(out), out
    assert panel_reads(out)["stopped"] == 1


# -- an account with no loyalty card -----------------------------------------------------

@pytest.mark.parametrize("answer", [refused(400), DROPPED], ids=["refused", "no answer"])
def test_an_account_with_no_loyalty_card_keeps_its_own_words(attached, answer, tmp_path, capsys):
    """Kroger says why there is no history, and what its API answers for
    such an account has never been seen. Its words stand, and the run is
    not stopped as though the history had been refused."""
    SITE.orders, SITE.answers = NO_LOYALTY, {1: answer}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "no loyalty card" in said and "did not come" not in said, said
    assert not known(tmp_path)
    assert not failure_files(tmp_path)


def test_after_kroger_says_there_is_no_loyalty_card_resume_still_reads_the_history(attached,
                                                                                  tmp_path,
                                                                                  capsys):
    """Kroger's words end that run without a stop, and the API gave no page
    to show the history was read, so Resume reads it first. A card added
    since is how its purchases are then found."""
    SITE.orders, SITE.answers = NO_LOYALTY, {1: refused(400)}
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.orders, SITE.answers = LISTED, {1: listed(NEWER, last=True)}
    SITE.asked.clear()
    finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume read the history"
    assert downloaded(tmp_path) == sorted(NEWER_KEYS)
