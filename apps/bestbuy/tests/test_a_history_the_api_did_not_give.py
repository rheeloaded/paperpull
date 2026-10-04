"""Discovery against a Best Buy purchase history that stops answering, in a
real browser.

The purchase history drew, so the session is fine, and then the history
query, which this app asks again from inside the page for each year back
from this one, stopped giving the history. Best Buy's bot protection stops
answering a session that asks too quickly. A year refused right after a
year with purchases wrote a failure file and ended the walk, and so did a
request that got no answer at all, and either way discovery printed
"Discovery complete" and went on, so Pilot and Run All finished clean with
the older purchases missed. A year answered with something that was not
the history was read as an empty year. A history that did not come is not
an empty one, and the run stops the way it does for a history page that
never drew, claiming nothing.

When the walk stops partway, the purchases on the years it read are real,
so they are kept and the run goes on with them. The older ones are
missing, so the run may not call itself finished either, and Resume reads
the history again before anything else.

Past the oldest year Best Buy keeps, the query answers with GraphQL errors
rather than an empty list, and that is the end of the history and not a
fault, after an empty year as it always was and after a year with
purchases too. A refusal is never the end, even after an empty year.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Every page and the history query come from a server on
this machine and the browser resolves no host name, so nothing reaches
Best Buy. Every order number, date, amount and item is invented.
"""
import json
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_receipts as app_mod
import bestbuy_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

HISTORY = "/purchasehistory/purchases"
DETAILS = "/profile/ss/orders/order-details/"
GRAPHQL = "/gateway/graphql"

# Every host name fails to resolve, and only this machine's own address is
# left alone, so a page the test forgot to point here goes nowhere.
NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"

THIS_YEAR = date.today().year
LAST_YEAR = THIS_YEAR - 1
EARLIER = THIS_YEAR - 2

# Four online orders over three years, each with the date, total and item
# its own details page shows.
ORDERS = {
    "BBY01-800000000031": (THIS_YEAR, 1, 14, 437.12, "Invented Air Fryer XL"),
    "BBY01-800000000032": (THIS_YEAR, 1, 2, 58.20, "Invented Coffee Maker"),
    "BBY01-800000000033": (LAST_YEAR, 11, 20, 129.99, "Invented Bluetooth Speaker"),
    "BBY01-800000000034": (EARLIER, 5, 5, 249.00, "Invented Robot Vacuum"),
}
NEWER = ["BBY01-800000000031", "BBY01-800000000032"]
OLDER = ["BBY01-800000000033"]
OLDEST = ["BBY01-800000000034"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def keys(numbers):
    return sorted("Online:" + n for n in numbers)


def entry(number):
    year, month, day, total, _item = ORDERS[number]
    return {"id": number, "orderType": "online",
            "created": "%04d-%02d-%02dT15:04:00-05:00" % (year, month, day),
            "orderTotal": total, "orderStatusTitle": "Delivered"}


def details_page(number):
    """The order's own page, which is the receipt."""
    year, month, day, total, item = ORDERS[number]
    return """<!doctype html><html><head><title>Order Details</title></head><body>
<header>Shop Deals Support &amp; Services Top Deals</header>
<main><div class="order-details-page__column-wrapper">
  <h1>Order Details</h1>
  <p>Purchase Date: %s %d, %d</p><p>Order Number: %s</p><p>Total: $%.2f</p>
  <div><p>%s</p><p>Model: INV-00031</p><p>SKU: 7654321</p><p>Quantity: 1</p>
       <p>Item Total: $%.2f</p></div>
</div></main>
<footer>Corporate Information | Careers</footer></body></html>""" % (
        MONTHS[month - 1], day, year, number, total, item, total)


# The history with its range menu. Choosing a year asks for that year's
# purchases the way the page's own code does, three at a time where this
# app asks for ten, which is how the two are told apart below.
MENU = """<!doctype html><html><head><title>Purchase History</title></head><body>
<h1>Purchases</h1>
<button data-testid="YearDate-Filter-TestID"
        onclick="document.getElementById('years').hidden = false">Past 3 Years</button>
<ul id="years" hidden><li onclick="pick(THIS_YEAR)">THIS_YEAR</li>
<li onclick="pick(LAST_YEAR)">LAST_YEAR</li></ul>
<script>
function pick(year) {
  document.getElementById('years').hidden = true;
  ASK
}
</script></body></html>""".replace("THIS_YEAR", str(THIS_YEAR)).replace("LAST_YEAR", str(LAST_YEAR))

LISTED = MENU.replace("ASK", """fetch('/gateway/graphql', {method: 'POST',
    headers: {'content-type': 'application/json', 'x-client-id': 'purchase-history'},
    body: JSON.stringify({operationName: 'consolidatedQuery',
      variables: {year: year, orderOffset: 0, purchaseOffset: 0, orderLimit: 3, purchaseLimit: 3}})});""")

# The same history, where choosing a year makes no request this app can
# see, so there is no query to ask again.
SILENT = MENU.replace("ASK", "")

HOME = """<!doctype html><html><head><title>Best Buy</title></head>
<body><h1>Shop Deals</h1></body></html>"""


# What the history query answers for one year, or for each of its pages
# in turn when a list of them is given.
def listed(numbers, more=False):
    return ("page", numbers, more)


def refused(status):
    return ("status", status)


# The connection closed with nothing sent, which the page's fetch meets as a
# network error rather than an answer. It is how a session Best Buy stopped
# answering looked, net::ERR_HTTP2_PROTOCOL_ERROR on every request.
DROPPED = ("drop",)
# What the query answers past the oldest year Best Buy keeps.
ERRORS = ("body", "application/json", json.dumps({"errors": [{"message": "Bad Request"}]}))
# A page where the history should be, which is what a bot check sends.
A_PAGE = ("body", "text/html; charset=utf-8",
          "<!doctype html><html><head><title>Best Buy</title></head>"
          "<body><p>One moment, please.</p></body></html>")
# An answer with no history in it.
NO_HISTORY = ("body", "application/json", json.dumps({"data": {"customer": None}}))

# Every way this year can fail to come, and the word the failure file
# keeps for why it stopped.
NO_FIRST_YEAR = {
    "refused 403": (refused(403), "refused", 403),
    "refused 429": (refused(429), "refused", 429),
    "no answer": (DROPPED, "no answer", 0),
    "an error": (ERRORS, "graphql errors", 200),
    "a page in its place": (A_PAGE, "no list", 200),
    "an answer with no history": (NO_HISTORY, "no list", 200),
}


def history_answer(numbers, more):
    return {"data": {"customer": {"purchaseHistoryOrdersExperience": {
        "closedOrdersAndTransactions": {"entries": [entry(n) for n in numbers],
                                        "pageInfo": {"hasNext": more}},
        "openOrders": {"entries": [], "pageInfo": {"hasNext": False}}}}}}


class FakeBestBuy:
    """What the made-up site shows, set by each test. A year with no
    answer set is an empty year."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.history = LISTED
        self.answers = {}
        self.asked = []
        self.seen = []


SITE = FakeBestBuy()


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
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        number = path[len(DETAILS):-len("/view")] if path.startswith(DETAILS) else ""
        if path == HISTORY:
            self._answer(SITE.history, "text/html; charset=utf-8")
        elif number in ORDERS and path.endswith("/view"):
            self._answer(details_page(number), "text/html; charset=utf-8")
        elif path == "/":
            self._answer(HOME, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path
        SITE.seen.append(path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path != GRAPHQL:
            self.send_error(404)
            return
        variables = (json.loads(body or b"{}").get("variables") or {})
        year = variables.get("year")
        later = (variables.get("orderOffset") or 0) + (variables.get("purchaseOffset") or 0) > 0
        if variables.get("orderLimit") == site.PAGE_SIZE:
            # This app's own ask, not the one the page made when a year was
            # chosen in its menu.
            SITE.asked.append((year, 2 if later else 1))
        answer = SITE.answers.get(year, listed([]))
        if isinstance(answer, list):
            answer = answer[min(1 if later else 0, len(answer) - 1)]
        if answer[0] == "drop":
            self.close_connection = True
            return
        if answer[0] == "status":
            self._answer(json.dumps({"errors": [{"message": "refused"}]}), "application/json",
                         status=answer[1])
        elif answer[0] == "body":
            self._answer(answer[2], answer[1])
        else:
            self._answer(json.dumps(history_answer(answer[1], answer[2])), "application/json")

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
def fake_bestbuy(server, monkeypatch):
    """Every address the app opens points at the made-up site, and every
    wait is short, the history's thirty seconds and the details page's
    included."""
    SITE.reset()
    monkeypatch.setattr(site, "BASE", server)
    monkeypatch.setattr(site, "ORDERS_URL", server + HISTORY)
    monkeypatch.setitem(site.URLS, "orders", server + HISTORY)
    monkeypatch.setitem(site.URLS, "home", server + "/")
    # The history query is only kept, and asked again, on Best Buy's own
    # host, and only a details address on it is opened. Here that host is
    # this machine.
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    monkeypatch.setattr(site, "ORDERS_WAIT_MS", 800)
    monkeypatch.setattr(site, "SETTLE_MS", 0)
    monkeypatch.setattr(site, "CHALLENGE_WAIT_MS", 1500)
    real_wait = site.wait_for_details
    monkeypatch.setattr(site, "wait_for_details",
                        lambda page, timeout_ms=30000, names_ms=10000:
                        real_wait(page, timeout_ms=min(timeout_ms, 2000),
                                  names_ms=min(names_ms, 2000)))
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
    """What the failure file says of the history query, in counts and in
    this app's own words, which is all a file a tester posts may carry."""
    files = failure_files(tmp_path)
    assert len(files) == 1, files
    report = json.loads(files[0].read_text(encoding="utf-8"))
    return (report.get("extra") or {}).get("postmortem")


def receipts_opened():
    return [p for p in SITE.seen if p.startswith(DETAILS)]


# -- a history that never came ------------------------------------------------------

@pytest.mark.parametrize("answer, why, status", list(NO_FIRST_YEAR.values()), ids=list(NO_FIRST_YEAR))
def test_a_pilot_stops_when_the_history_query_gives_no_year(attached, answer, why, status,
                                                            tmp_path, capsys):
    """It used to finish as though the account had nothing new, and the
    panel read the run as clean. A page in place of the answer was read as
    an empty year, three of them as the end of the history."""
    SITE.answers = {THIS_YEAR: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "purchase history did not come" in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert (THIS_YEAR, 1) in SITE.asked, "the history query really was asked"
    assert not known(tmp_path), "nothing is recorded from a history that did not come"
    assert not receipts_opened(), "and no receipt is opened"
    assert how_far_it_got(tmp_path) == {"years": 1, "answered": 0, "last": False, "stop": why,
                                        "status": status}


def test_a_history_whose_page_makes_no_query_is_not_read_as_empty(attached, tmp_path, capsys):
    """The range menu came, so the session is fine, and choosing a year made
    no request this app could ask again. It wrote a failure file and
    finished with nothing found."""
    SITE.history = SILENT
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "purchase history did not come" in said and "made no history query" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert not SITE.asked and not known(tmp_path)
    assert how_far_it_got(tmp_path)["stop"] == "no query"


def test_a_history_that_gets_no_answer_says_to_leave_best_buy_a_while(attached, tmp_path, capsys):
    """Best Buy stops answering a session that asks too quickly, and asking
    again straight away only keeps it that way."""
    SITE.answers = {THIS_YEAR: DROPPED}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    assert "Leave it for an hour" in folded(out), out


def test_with_somebody_there_it_asks_them_to_look_and_then_asks_again(attached, tmp_path, capsys,
                                                                      monkeypatch):
    """At a console the run waits for the person rather than stopping, and
    once they say so it asks the history query again. Past a few questions
    they give up with Ctrl+C, so a loop that asks forever fails here rather
    than hanging the suite."""
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > 5:
            raise KeyboardInterrupt
        SITE.answers = {THIS_YEAR: listed(NEWER)}
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    SITE.answers = {THIS_YEAR: refused(403)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    assert len(asked) == 1 and "ask Best Buy" in asked[0], asked
    assert sorted(known(tmp_path)) == keys(NEWER)
    assert "Discovery complete" in folded(out)


# -- a history cut short --------------------------------------------------------------

@pytest.mark.parametrize("answer, why, status", [(refused(429), "refused", 429),
                                                 (DROPPED, "no answer", 0),
                                                 (A_PAGE, "no list", 200)],
                         ids=["refused", "no answer", "a page in its place"])
def test_a_history_cut_short_is_used_and_the_run_does_not_finish(attached, answer, why, status,
                                                                 tmp_path, capsys):
    """This year came and last year did not, which is not the end of a
    history. The purchases that came are real, so the pilot downloads them,
    and the older ones are missing, so it stops rather than finish."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: answer}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "stopped giving your purchase history at %d" % LAST_YEAR in said, said
    assert "Discovery complete" not in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert sorted(known(tmp_path)) == keys(NEWER), "what came is kept"
    assert downloaded(tmp_path) == keys(NEWER), "and used"
    assert how_far_it_got(tmp_path) == {"years": 2, "answered": 1, "last": False, "stop": why,
                                        "status": status}


@pytest.mark.parametrize("command", [["--all", "--yes"], ["--discover"]], ids=["run all", "discover"])
def test_run_all_and_discover_do_not_finish_on_a_history_cut_short(attached, command, tmp_path,
                                                                   capsys):
    """Each command that reads the history stops in its own place, Run All
    once it has downloaded what came and Discover once it has listed it."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: refused(429)}
    out = stopped_run(tmp_path, attached, capsys, *command)

    said = folded(out)
    assert "stopped giving your purchase history at %d" % LAST_YEAR in said, said
    assert "Discovery complete" not in said, said
    assert sorted(known(tmp_path)) == keys(NEWER)
    if command[0] == "--all":
        assert downloaded(tmp_path) == keys(NEWER)
        assert panel_reads(out)["stopped"] == 1


def test_a_year_that_gave_purchases_and_then_failed_is_not_the_end(attached, tmp_path, capsys):
    """An error past the oldest year comes in place of the year's first page.
    A year whose first page listed purchases is not past the oldest year,
    so its next page failing is a history cut short, after an empty year
    too."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: listed([]),
                    EARLIER: [listed(OLDEST, more=True), refused(429)]}
    out = stopped_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "stopped giving your purchase history at %d" % EARLIER in said, said
    assert (EARLIER, 2) in SITE.asked, "the second page really was asked"
    assert sorted(known(tmp_path)) == keys(NEWER + OLDEST)


# -- what worked before -------------------------------------------------------------------

def test_a_history_of_several_years_is_read_to_its_end(attached, tmp_path, capsys):
    """Every year is read back from this one until three in a row hold
    nothing, and only then is discovery complete."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: listed(OLDER), EARLIER: listed(OLDEST)}
    out = finished_run(tmp_path, attached, capsys, "--discover")

    said = folded(out)
    assert "Discovery complete" in said and "did not come" not in said, said
    assert sorted(known(tmp_path)) == keys(NEWER + OLDER + OLDEST)
    assert [y for y, _page in SITE.asked] == [THIS_YEAR, LAST_YEAR, EARLIER, EARLIER - 1,
                                              EARLIER - 2, EARLIER - 3]
    assert not failure_files(tmp_path)


def test_an_error_after_an_empty_year_is_still_the_end_of_the_history(attached, tmp_path, capsys):
    """Past the oldest year Best Buy keeps, the query answers with GraphQL
    errors rather than an empty list, RECORDED on the account this was
    built on, where an empty year came before it. That is the end of the
    history, not a fault, and the run finishes."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: listed([]), EARLIER: ERRORS}
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "stopped giving" not in said, said
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


def test_an_error_past_the_oldest_year_is_the_end_after_a_year_with_purchases_too(attached,
                                                                                tmp_path,
                                                                                capsys):
    """An account's oldest year can hold purchases, so the errors past it can
    come right after a year with purchases. They wrote a failure file there,
    and stopping there would end every run on such an account, so it is the
    end of the history, as it is after an empty year."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: ERRORS}
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "stopped giving" not in said, said
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


@pytest.mark.parametrize("answer, why, status", [(refused(429), "refused", 429),
                                                 (DROPPED, "no answer", 0)],
                         ids=["refused", "no answer"])
def test_a_refusal_after_an_empty_year_is_not_the_end_of_the_history(attached, answer, why, status,
                                                                     tmp_path, capsys):
    """Only Best Buy's errors past its oldest year end the history. In a
    January with nothing bought yet, a refusal of last year came right
    after an empty year and was taken for the end, and the run finished
    clean with every older purchase missed."""
    SITE.answers = {THIS_YEAR: listed([]), LAST_YEAR: answer, EARLIER: listed(OLDEST)}
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "stopped giving your purchase history at %d" % LAST_YEAR in said, said
    assert panel_reads(out)["stopped"] == 1
    assert how_far_it_got(tmp_path) == {"years": 2, "answered": 1, "last": False, "stop": why,
                                        "status": status}


# -- Resume after a run that stopped ---------------------------------------------------

def test_resume_reads_the_history_after_a_pilot_that_never_got_it(attached, tmp_path, capsys):
    """The panel says to press Resume once a run has stopped. Resume works
    from the purchases already found, and the stopped pilot found none, so
    it had nothing to do and finished clean, the history never read."""
    SITE.answers = {THIS_YEAR: refused(403)}
    either_run(tmp_path, attached, capsys, "--pilot")

    SITE.asked.clear()
    SITE.answers = {THIS_YEAR: listed(NEWER)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked the history query"
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_reads_what_a_history_cut_short_left_out(attached, tmp_path, capsys):
    """Resume after a history cut short used to download the part that
    came and finish clean, the older purchases never looked for."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: listed(OLDER)}
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert sorted(known(tmp_path)) == keys(NEWER + OLDER)
    assert downloaded(tmp_path) == keys(NEWER + OLDER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_goes_on_with_what_was_found_when_the_history_is_refused(attached, tmp_path,
                                                                       capsys):
    """Resume worked from the purchases already found and never asked the
    history query. Now it asks first, and when Best Buy refuses, it still
    downloads the purchases it has, as it did, and does not call itself
    finished."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.answers = {THIS_YEAR: refused(403)}
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert "purchase history did not come" in folded(out), out
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_a_whole_history_does_not_read_it_again(attached, tmp_path, capsys):
    """A Discover that read the history to its end leaves nothing for
    Resume to read again, so Resume goes straight to the purchases found."""
    SITE.answers = {THIS_YEAR: listed(NEWER)}
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.asked.clear()
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert not SITE.asked and GRAPHQL not in SITE.seen, "Resume left the history alone"
    assert downloaded(tmp_path) == keys(NEWER)
    assert panel_reads(out)["stopped"] == 0


def test_resume_that_meets_a_history_cut_short_again_does_not_finish(attached, tmp_path, capsys):
    """The pilot downloaded what came, so when Resume reads the history
    again and it is cut short at the same place, there is nothing new to
    download. That is still not a finished run."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: refused(429)}
    either_run(tmp_path, attached, capsys, "--pilot")
    assert downloaded(tmp_path) == keys(NEWER)

    SITE.asked.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert SITE.asked, "Resume asked the history query"
    assert "Nothing to resume" in folded(out), out
    assert panel_reads(out)["stopped"] == 1


def test_a_year_read_whole_does_not_stand_for_the_history_a_run_cut_short(attached, tmp_path,
                                                                         capsys):
    """A run for one year reads only that year, so reading it whole says
    nothing of the years a Discover cut short never reached. The mark that
    sends Resume to the history first stays, where a whole walk takes it
    away."""
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: refused(429)}
    either_run(tmp_path, attached, capsys, "--discover")
    finished_run(tmp_path, attached, capsys, "--discover", "--year", str(THIS_YEAR))

    SITE.asked.clear()
    SITE.answers = {THIS_YEAR: listed(NEWER), LAST_YEAR: listed(OLDER)}
    finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert (LAST_YEAR, 1) in SITE.asked, "Resume read the years the cut short run never reached"
    assert downloaded(tmp_path) == keys(NEWER + OLDER)
