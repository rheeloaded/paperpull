"""Resume with no tab of the person's open on Uber's sites, in a real
browser.

A Discover that read both lists to their end leaves Resume nothing to read
again, so Resume goes straight to the purchases found. Every receipt is
asked for from inside a tab on its side's own site, and a call from a tab
anywhere else is refused before it is sent, since its path is relative.
Discovery opens each side's list page in its tab, and processing did not.
At home the person usually still has the tab they signed in with, which
the app reuses, so it went unseen. With no such tab the app opened a new
blank one, every call was refused, and every purchase was recorded failed
with "No receipt came back", to be tried again by a next run that met the
same.

Processing opens the side's list page in a tab that is not on the site, as
discovery does, and a side that asks for a sign-in or shows a check there
stops, as it does in discovery. The person's own tab is still the one used
when it is open, and it is never loaded again or closed.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Uber's two sites are two made-up host names the browser
is told to find on this machine, and every other name fails to resolve, so
nothing reaches Uber. Every trip, order, store, name and amount is
invented.
"""
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import uber_receipts as app_mod
import uber_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit
from paperpull_core.models import State

RIDERS_HOST = "riders.uber.test"
EATS_HOST = "www.ubereats.test"

# Uber's two hosts are found on this machine, and every other name fails to
# resolve, this machine's own address aside, so a page the test forgot to
# point here goes nowhere.
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (RIDERS_HOST, EATS_HOST))

TRIP_A = "0a1b2c3d-1111-4222-8333-444455556666"
TRIP_C = "0a1b2c3d-2222-4333-8444-dddd0000eeee"
ORDER_A = "5e6f7a8b-1234-4567-89ab-cdef01234567"
ORDER_C = "5e6f7a8b-3456-4789-abcd-ef0123456789"
RECEIPT_A = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
RECEIPT_C = "9f8e7d6c-6c5b-4a49-8382-716a5f4e3d2c"

# Each trip with where it went, what the list says it cost, the list's own
# words for when, the start its details give, and its date as the receipt
# writes it.
TRIPS = {
    TRIP_A: ("Example Station", "$18.64", "Jun 15, 11:55 AM",
             "Mon Jun 15 2026 16:05:10 GMT+0000 (Coordinated Universal Time)", "June 15, 2026"),
    TRIP_C: ("100 Example Ct", "$16.42", "Nov 12, 11:40 AM",
             "Wed Nov 12 2025 16:40:10 GMT+0000 (Coordinated Universal Time)", "November 12, 2025"),
}
# Each order with its store, its total in cents, when it was completed, the
# Receipt ID its receipt prints, the receipt's time, and its date as the
# receipt writes it.
ORDERS = {
    ORDER_A: ("Example Deli", 2735, "2026-04-18T18:11:52.604Z", RECEIPT_A,
              "2026-04-18T19:22:07.315Z", "April 18, 2026"),
    ORDER_C: ("Example Curry House", 2291, "2025-10-30T16:32:05.771Z", RECEIPT_C,
              "2025-10-30T17:41:26.208Z", "October 30, 2025"),
}

RIDES_KEYS = ["Rides:" + TRIP_A, "Rides:" + TRIP_C]
EATS_KEYS = ["Uber Eats:" + ORDER_A, "Uber Eats:" + ORDER_C]

# The receipts, drawn by a browser before any run starts.
PDFS = {}

TRIPS_PAGE = """<!doctype html><html><head><title>My Trips</title></head>
<body><h1>My Trips</h1><p>Past</p></body></html>"""
EATS_PAGE = """<!doctype html><html><head><title>Past Orders</title></head>
<body><h1>Past Orders</h1></body></html>"""
# The trips page with a check in front of it.
CHECK_PAGE = """<!doctype html><html><head><title>Uber</title></head>
<body><h1>Verify you are a human</h1></body></html>"""
# Where a signed-out trips page sends the tab.
SIGN_IN_PAGE = """<!doctype html><html><head><title>Sign in</title></head>
<body><h1>Sign in to Uber</h1><input type='password'></body></html>"""


def activity(uuid):
    where, description, subtitle, _begin, _written = TRIPS[uuid]
    return {"uuid": uuid, "title": where, "description": description, "subtitle": subtitle,
            "cardURL": "https://riders.uber.com/trips/" + uuid,
            "buttons": [{"text": "Details", "url": "https://riders.uber.com/trips/" + uuid}]}


def eats_order(uuid):
    store, cents, done, _receipt, _stamp, _written = ORDERS[uuid]
    return {"baseEaterOrder": {
                "uuid": uuid, "isCancelled": False, "isCompleted": True, "completedAt": done,
                "lastStateChangeAt": done, "fulfillmentType": "DELIVERY",
                "shoppingCart": {"items": [{"title": "Turkey Club", "price": 1275,
                                            "quantity": 1}]}},
            "storeInfo": {"title": store}, "fareInfo": {"totalPrice": cents}}


class FakeUber:
    """What the made-up sites answer, set by each test. Both lists whole and
    both sides signed in unless a test says otherwise."""

    def __init__(self):
        self.reset()

    def reset(self):
        # The trips page, or None for one that sends the tab to sign in.
        self.trips_page = TRIPS_PAGE
        self.trips = [TRIP_A, TRIP_C]
        self.orders = [ORDER_A, ORDER_C]
        # Every request, with the address of the page that made it, as the
        # browser said it in Referer.
        self.seen = []


SITE = FakeUber()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value, status=200):
        self._send(json.dumps(value).encode("utf-8"), "application/json", status)

    def _page(self, html):
        self._send(html.encode("utf-8"), "text/html; charset=utf-8")

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def _note(self, method, path, operation=""):
        SITE.seen.append((self._host(), method, path, operation,
                          self.headers.get("Referer") or ""))

    def do_GET(self):
        host, path = self._host(), urlsplit(self.path).path
        self._note("GET", path)
        parts = path.strip("/").split("/")
        if host == RIDERS_HOST and path == "/trips":
            if SITE.trips_page is None:
                self._send(b"", "text/html; charset=utf-8", 302, [("Location", "/login")])
            else:
                self._page(SITE.trips_page)
        elif host == RIDERS_HOST and path == "/login":
            self._page(SIGN_IN_PAGE)
        elif host == EATS_HOST and path == "/orders":
            self._page(EATS_PAGE)
        elif host == RIDERS_HOST and len(parts) == 3 and parts[2] == "receipt" and parts[1] in PDFS:
            self._send(PDFS[parts[1]], "application/pdf")
        elif host == EATS_HOST and len(parts) == 3 and parts[2] == "download-receipt" \
                and parts[1] in PDFS:
            self._send(PDFS[parts[1]], "application/pdf")
        else:
            self.send_error(404)

    def do_POST(self):
        host, path = self._host(), urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self._note("POST", path, body.get("operationName") or "")
        if host == RIDERS_HOST and path == "/graphql":
            self._graphql(body.get("operationName"), body.get("variables") or {})
        elif host == EATS_HOST and path == "/_p/api/getPastOrdersV1":
            listed = [] if body.get("lastWorkflowUUID") else SITE.orders
            self._json({"status": "success", "data": {
                "ordersMap": {u: eats_order(u) for u in listed}, "orderUuids": list(listed),
                "paginationData": {"nextCursor": "{}"}, "meta": {"hasMore": False}}})
        elif host == EATS_HOST and path == "/_p/api/getReceiptByWorkflowUuidV1":
            _store, _cents, _done, receipt, stamp, _written = ORDERS[body.get("workflowUuid")]
            self._json({"status": "success", "data": {
                "receiptData": "<p>Receipt ID # %s</p>" % receipt, "isPDFSupported": True,
                "timestamp": stamp, "receiptsForJob": [{"timestamp": stamp, "type": "TIPPED"}],
                "actions": [{"type": "DOWNLOAD_PDF"}]}})
        else:
            self.send_error(404)

    def _graphql(self, operation, variables):
        if operation == "Activities":
            # One page of the personal trips, and no business ones.
            listed = SITE.trips if variables.get("profileType") == "PERSONAL" \
                and not variables.get("nextPageToken") else []
            self._json({"data": {"activities": {"cityID": 8, "past": {
                "activities": [activity(u) for u in listed], "nextPageToken": None}}}})
        elif operation == "GetTrip":
            uuid = variables.get("tripUUID")
            _where, fare, _subtitle, begin, _written = TRIPS[uuid]
            self._json({"data": {"getTrip": {
                "trip": {"beginTripTime": begin, "fare": fare, "status": "COMPLETED",
                         "uuid": uuid},
                "receipt": {"distance": "3.10", "distanceLabel": "miles",
                            "duration": "12 minutes", "vehicleType": "UberX"}}}})
        elif operation == "GetReceipt":
            uuid = variables.get("tripUUID")
            self._json({"data": {"getReceipt": {
                "actionList": [{"type": "DOWNLOAD_PDF", "helpNodeUUID": ""}],
                "receiptData": "<div>Thanks for riding</div><div>Receipt ID # %s</div>" % uuid,
                "receiptsForJob": [{"timestamp": "1781563527104", "type": "COMPLETED",
                                    "eventUUID": "e1"}]}}})
        else:
            self._json({"errors": [{"message": "unknown"}]}, 400)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def receipts():
    """Uber's own receipt PDFs, made up, drawn by a browser of the test's own
    before any run starts. The app starts its own Playwright, and two
    cannot share this thread, so this one is gone before the first run."""
    pw = pytest.importorskip("playwright.sync_api")
    lines = {}
    for uuid, (_where, fare, _subtitle, _begin, written) in TRIPS.items():
        lines[uuid] = [written, "Thanks for riding, Dana", "Total " + fare,
                       "Receipt ID # %s" % uuid]
    for uuid, (store, cents, _done, receipt, _stamp, written) in ORDERS.items():
        lines[uuid] = [written, "Thanks for ordering, Dana",
                       "Here's your receipt for %s." % store, "Total",
                       "$%d.%02d" % (cents // 100, cents % 100), "Receipt ID # %s" % receipt]
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to draw the receipts: %s" % e)
        page = browser.new_page()
        for uuid, said in lines.items():
            page.set_content("<html><body>%s</body></html>" % "".join("<p>%s</p>" % s for s in said))
            PDFS[uuid] = page.pdf()
        browser.close()
    return PDFS


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
def attached(browser_exe, server, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation. That tab is on a page of the
    helper's own, not on either of Uber's sites, so no tab of the person's
    is open there unless a test opens one."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def tabs(cdp_url):
    """Every tab the browser has, as its own debugging port lists them."""
    with urllib.request.urlopen(cdp_url + "/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read()) if t.get("type") == "page"]


def on_the_sites(cdp_url):
    """The tabs on either of Uber's made-up sites."""
    return [t for t in tabs(cdp_url)
            if urlsplit(t.get("url") or "").hostname in (RIDERS_HOST, EATS_HOST)]


def close_tab(cdp_url, tab_id):
    urllib.request.urlopen("%s/json/close/%s" % (cdp_url, tab_id), timeout=10).read()


def open_their_tab(cdp_url, address, title):
    """A tab the person signed in with at home, opened by the browser
    itself the way login.bat's is, once it has drawn its page. Its id."""
    made = json.loads(urllib.request.urlopen(urllib.request.Request(
        cdp_url + "/json/new?" + address, method="PUT"), timeout=15).read())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any(t.get("id") == made.get("id") and t.get("title") == title
               for t in tabs(cdp_url)):
            return made["id"]
        time.sleep(0.2)
    pytest.fail("the tab for %s never drew" % address)


@pytest.fixture(autouse=True)
def no_tab_on_the_sites(attached):
    """Each test starts with no tab on either site, and a tab a run left open
    for the person to sign in is closed after its test."""
    for tab in on_the_sites(attached):
        close_tab(attached, tab["id"])
    yield
    for tab in on_the_sites(attached):
        close_tab(attached, tab["id"])


@pytest.fixture(autouse=True)
def fake_uber(server, receipts, monkeypatch):
    """Both of Uber's sites are the made-up ones, and every pause and wait
    is short."""
    SITE.reset()
    riders = "http://%s:%d" % (RIDERS_HOST, server)
    eats = "http://%s:%d" % (EATS_HOST, server)
    monkeypatch.setattr(site, "RIDERS_HOST", RIDERS_HOST)
    monkeypatch.setattr(site, "EATS_HOST", EATS_HOST)
    monkeypatch.setattr(site, "TRIPS_URL", riders + "/trips")
    monkeypatch.setattr(site, "EATS_ORDERS_URL", eats + "/orders")
    for name in ("home", "login", "orders"):
        monkeypatch.setitem(site.URLS, name, riders + "/trips")
    monkeypatch.setitem(site.URLS, "eats_orders", eats + "/orders")
    # Every call is only made from a tab on one of Uber's own two hosts.
    # Here those hosts are the made-up ones.
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (RIDERS_HOST, EATS_HOST))
    monkeypatch.setattr(site, "LIST_PAUSE_MS", 0)
    monkeypatch.setattr(site, "SETTLE_MS", 3000)
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
    stopped. What it printed, unfolded."""
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


def panel_reads(out):
    """The counts the panel reads, off the line the core prints for it."""
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def progress(tmp_path):
    path = tmp_path / "out" / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def downloaded(tmp_path):
    """The purchases whose receipt was saved and passed its check."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("downloaded_ok")
                  and Path(r.get("pdf_path") or "").is_file())


def failed(tmp_path):
    """The purchases recorded as failed."""
    return sorted(k for k, r in progress(tmp_path).items()
                  if isinstance(r, dict) and r.get("state") == State.FAILED.value)


def receipt_calls():
    """Each call that asked for a receipt or its PDF, with the address of
    the page that made it."""
    return [(host, referer) for host, _method, path, operation, referer in SITE.seen
            if operation == "GetReceipt"
            or path.endswith(("/receipt", "/download-receipt", "/getReceiptByWorkflowUuidV1"))]


def list_pages_loaded():
    return [(host, path) for host, method, path, _operation, _referer in SITE.seen
            if method == "GET" and path in ("/trips", "/orders")]


# -- Resume after a Discover that read both lists whole ------------------------------

def test_resume_with_no_tab_of_theirs_open_downloads_every_receipt(attached, server, tmp_path,
                                                                    capsys):
    """Discover read both lists to their end and closed the tabs it opened.
    Resume asked every receipt from a new blank tab, each call was refused
    before it was sent, and every purchase was recorded failed with no
    receipt, run after run. Each side's page is opened first now, and every
    receipt is asked for from it."""
    finished_run(tmp_path, attached, capsys, "--discover")
    assert not on_the_sites(attached), "discovery closed the tabs it opened"

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS), folded(out)
    assert not failed(tmp_path)
    assert panel_reads(out)["failed"] == 0 and panel_reads(out)["stopped"] == 0
    riders = "http://%s:%d/trips" % (RIDERS_HOST, server)
    eats = "http://%s:%d/orders" % (EATS_HOST, server)
    assert set(receipt_calls()) == {(RIDERS_HOST, riders), (EATS_HOST, eats)}, \
        "each side's receipts were asked for from its own list page"
    assert not on_the_sites(attached), "and the run closed the tabs it opened"


def test_a_pilot_with_no_tab_of_theirs_open_downloads_as_it_always_did(attached, tmp_path,
                                                                       capsys):
    """Pilot reads both lists first, in the same run, so each side's page
    was already open when its receipts were asked for."""
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS), folded(out)
    assert list_pages_loaded().count((RIDERS_HOST, "/trips")) == 1, "the trips page opened once"
    assert not on_the_sites(attached)


def test_their_own_tabs_are_used_never_loaded_again_and_left_open(attached, server, tmp_path,
                                                                  capsys):
    """At home the tabs the person signed in with are still open. Resume
    asks every receipt from them, loads neither of them again, and leaves
    them open where they were, with no tab of its own left beside them."""
    theirs = {"http://%s:%d/trips?tab=theirs" % (RIDERS_HOST, server): "My Trips",
              "http://%s:%d/orders?tab=theirs" % (EATS_HOST, server): "Past Orders"}
    ids = {open_their_tab(attached, address, title): address for address, title in theirs.items()}
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS), folded(out)
    assert not list_pages_loaded(), "neither of their tabs was loaded again"
    assert set(receipt_calls()) == {(urlsplit(a).hostname, a) for a in theirs}, \
        "every receipt was asked for from their tabs"
    assert {t["id"]: t["url"] for t in on_the_sites(attached)} == ids, \
        "their tabs are still open where they were, and nothing else is"


@pytest.mark.parametrize("trips_page, said, left_on", [
    (None, "Uber asked you to sign in again for your trips", "/login"),
    (CHECK_PAGE, "Uber is showing a check in that window", "/trips")],
    ids=["a sign-in", "a check"])
def test_a_side_that_asks_for_a_sign_in_when_its_page_is_opened_stops_there(
        attached, trips_page, said, left_on, tmp_path, capsys):
    """The trips page asked for a sign-in, or put a check in front of
    itself, when Resume opened it. The trips side stops there, as it does
    in discovery, its tab left open for the person and no trip counted as
    failed, and the Uber Eats orders are downloaded. Each trip was asked
    for from a blank tab and recorded failed, and the run finished clean."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.trips_page = trips_page
    SITE.seen.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume")

    assert said in folded(out), out
    assert panel_reads(out)["stopped"] == 1
    assert downloaded(tmp_path) == sorted(EATS_KEYS)
    assert not failed(tmp_path), "the trips are looked for again next run, not counted failed"
    assert not [c for c in receipt_calls() if c[0] == RIDERS_HOST], "no trip's receipt was asked"
    assert [urlsplit(t["url"]).path for t in on_the_sites(attached)] == [left_on], \
        "the trips tab is left open for the person"


def test_a_tab_that_leaves_the_site_partway_is_opened_on_it_again(attached, tmp_path, capsys,
                                                                 monkeypatch):
    """The trips tab was taken off the site after the first trip's receipt.
    The next trip opens the trips page in it again before anything is asked,
    rather than asking from a tab that every call is refused from."""
    finished_run(tmp_path, attached, capsys, "--discover")

    real_fetch = site.fetch_pdf
    left = []

    def fetch_then_leave(page, path, side=site.RIDES):
        got = real_fetch(page, path, side)
        if side == site.RIDES and not left:
            left.append(path)
            page.goto("about:blank")
        return got

    monkeypatch.setattr(site, "fetch_pdf", fetch_then_leave)
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert left, "the trips tab left the site after the first receipt"
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS), folded(out)
    assert list_pages_loaded().count((RIDERS_HOST, "/trips")) == 2, \
        "the trips page was opened again for the second trip"


def test_a_tab_of_theirs_that_leaves_the_site_is_let_go_of(attached, server, tmp_path, capsys,
                                                          monkeypatch):
    """The person took their trips tab to another page after the first
    trip's receipt. The tab is theirs, so it is let go of where they took
    it, never loaded back onto Uber, and the next trip opens the trips page
    in a tab of the run's own. The trips page was loaded into their tab."""
    trips = "http://%s:%d/trips?tab=theirs" % (RIDERS_HOST, server)
    their_trips = open_their_tab(attached, trips, "My Trips")
    open_their_tab(attached, "http://%s:%d/orders?tab=theirs" % (EATS_HOST, server), "Past Orders")
    finished_run(tmp_path, attached, capsys, "--discover")

    real_fetch = site.fetch_pdf
    left = []

    def fetch_then_leave(page, path, side=site.RIDES):
        got = real_fetch(page, path, side)
        if side == site.RIDES and not left:
            left.append(path)
            page.goto("about:blank")
        return got

    monkeypatch.setattr(site, "fetch_pdf", fetch_then_leave)
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume")

    assert left, "their trips tab left the site after the first receipt"
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS), folded(out)
    assert [t["url"] for t in tabs(attached) if t["id"] == their_trips] == ["about:blank"], \
        "their tab is still open where they took it, never loaded back onto Uber"
    from_theirs = [referer == trips for host, referer in receipt_calls() if host == RIDERS_HOST]
    assert from_theirs[0] and not from_theirs[-1] \
        and from_theirs == sorted(from_theirs, reverse=True), \
        "trips were asked from their tab until it left, and from the run's own after"


def test_a_dry_run_resume_opens_no_page(attached, tmp_path, capsys):
    """A dry run asks Uber for nothing, and that holds for the pages too."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--dry-run")

    assert "DRY RUN, would save" in folded(out), out
    assert not SITE.seen, "nothing was asked of either site"
    assert not downloaded(tmp_path)
