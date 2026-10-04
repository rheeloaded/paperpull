"""Discovery against Uber lists that stop answering partway, in a real
browser.

Both sides opened signed in, and then one side's own list stopped giving
its purchases. The trip list or the Uber Eats order list was refused or
got no answer partway, the trip list answered with errors in place of the
trips, or Uber gave no answer for a trip's details, which are what place
it on a day. Discovery said so, wrote a failure file and went on, or read
the answer as the end, and since only a side that asked for a sign-in
stopped the run, Pilot and Run All finished clean with the purchases past
that point missed. A list that did not come whole is not a list with
nothing more in it. A trip Uber answered for without its details may be
the trip's own, so it is read again next run without stopping every run.

What was read is real, so it is kept and the run goes on with it, the
other side included. The rest is missing, so the run stops at its end
rather than finish, and Resume reads both lists again before anything
else.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Uber's two sites are two made-up host names the browser
is told to find on this machine, and every other name fails to resolve, so
nothing reaches Uber. Every trip, order, store, name and amount is
invented.
"""
import base64
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

RIDERS_HOST = "riders.uber.test"
EATS_HOST = "www.ubereats.test"

# Uber's two hosts are found on this machine, and every other name fails to
# resolve, this machine's own address aside, so a page the test forgot to
# point here goes nowhere.
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (RIDERS_HOST, EATS_HOST))

TRIP_A = "0a1b2c3d-1111-4222-8333-444455556666"
TRIP_B = "0a1b2c3d-7777-4888-9999-aaaabbbbcccc"
TRIP_C = "0a1b2c3d-2222-4333-8444-dddd0000eeee"
ORDER_A = "5e6f7a8b-1234-4567-89ab-cdef01234567"
ORDER_C = "5e6f7a8b-3456-4789-abcd-ef0123456789"
RECEIPT_A = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
RECEIPT_C = "9f8e7d6c-6c5b-4a49-8382-716a5f4e3d2c"

# Each trip with where it went, what the list says it cost, the list's own
# words for when, and the start its details give.
TRIPS = {
    TRIP_A: ("Example Station", "$18.64", "Jun 15 \u2022 11:55 AM",
             "Mon Jun 15 2026 16:05:10 GMT+0000 (Coordinated Universal Time)", "June 15, 2026"),
    TRIP_B: ("Example Market", "$0.00 \u2022 Canceled", "Jun 11 \u2022 4:20 PM", "", ""),
    TRIP_C: ("100 Example Ct", "$16.42", "Nov 12 \u2022 11:40 AM",
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


def token(iso):
    return base64.b64encode(iso.encode()).decode()


# Where the first page of trips ended, which is the next page's token.
T1 = token("2025-11-12T18:02:44.118Z")

RIDES_KEYS = ["Rides:" + TRIP_A, "Rides:" + TRIP_C]
EATS_KEYS = ["Uber Eats:" + ORDER_A, "Uber Eats:" + ORDER_C]

# The receipts, drawn by a browser before any run starts.
PDFS = {}

TRIPS_PAGE = """<!doctype html><html><head><title>My Trips</title></head>
<body><h1>My Trips</h1><p>Past</p></body></html>"""
EATS_PAGE = """<!doctype html><html><head><title>Past Orders</title></head>
<body><h1>Past Orders</h1></body></html>"""


# What a list call answers. A page of the list, or one of the ways it does
# not come.
def rows(uuids, following=None):
    return ("rows", uuids, following)


def refused(status):
    return ("status", status)


# The connection closed with nothing sent, which the page's fetch meets as a
# network error rather than an answer.
DROPPED = ("drop",)
# A GraphQL answer that carries errors and nothing else.
ERRORS_ONLY = ("json", {"data": None, "errors": [{"message": "unavailable"}]})
# The trip list's answer with errors in place of the trips.
NO_TRIPS = ("json", {"data": {"activities": None}, "errors": [{"message": "unavailable"}]})


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
    """What the made-up sites answer, set by each test. Both lists whole
    unless a test says otherwise."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.ride_pages = {("PERSONAL", None): rows([TRIP_A, TRIP_B], T1),
                           ("PERSONAL", T1): rows([TRIP_C])}
        self.trips = {}
        self.eats_pages = {"": rows([ORDER_A], True), ORDER_A: rows([ORDER_C], False)}
        self.asked = []
        self.seen = []


SITE = FakeUber()


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # core/tests/test_ready_live.py. Every answer carries its length.
    protocol_version = "HTTP/1.1"

    def _send(self, data, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value, status=200):
        self._send(json.dumps(value).encode("utf-8"), "application/json", status)

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def do_GET(self):
        host, path = self._host(), urlsplit(self.path).path
        SITE.seen.append((host, "GET", path))
        parts = path.strip("/").split("/")
        if host == RIDERS_HOST and path == "/trips":
            self._send(TRIPS_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif host == EATS_HOST and path == "/orders":
            self._send(EATS_PAGE.encode("utf-8"), "text/html; charset=utf-8")
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
        SITE.seen.append((host, "POST", path, body.get("operationName") or ""))
        if host == RIDERS_HOST and path == "/graphql":
            self._graphql(body.get("operationName"), body.get("variables") or {})
        elif host == EATS_HOST and path == "/_p/api/getPastOrdersV1":
            last = body.get("lastWorkflowUUID") or ""
            SITE.asked.append(("orders", last))
            self._answer(SITE.eats_pages.get(last, rows([], False)), self._orders_page)
        elif host == EATS_HOST and path == "/_p/api/getReceiptByWorkflowUuidV1":
            _store, _cents, _done, receipt, stamp, _written = ORDERS[body.get("workflowUuid")]
            self._json({"status": "success", "data": {
                "receiptData": "<p>Receipt ID # %s</p>" % receipt, "isPDFSupported": True,
                "timestamp": stamp, "receiptsForJob": [{"timestamp": stamp, "type": "TIPPED"}],
                "actions": [{"type": "DOWNLOAD_PDF"}]}})
        else:
            self.send_error(404)

    def _answer(self, answer, page):
        if answer[0] == "drop":
            self.close_connection = True
        elif answer[0] == "status":
            self._json({"errors": [{"message": "refused"}]}, answer[1])
        elif answer[0] == "json":
            self._json(answer[1])
        else:
            page(answer)

    def _trips_page(self, answer):
        self._json({"data": {"activities": {"cityID": 8, "past": {
            "activities": [activity(u) for u in answer[1]], "nextPageToken": answer[2]}}}})

    def _orders_page(self, answer):
        self._json({"status": "success", "data": {
            "ordersMap": {u: eats_order(u) for u in answer[1]}, "orderUuids": list(answer[1]),
            "paginationData": {"nextCursor": "{}"}, "meta": {"hasMore": answer[2]}}})

    def _graphql(self, operation, variables):
        if operation == "Activities":
            key = (variables.get("profileType"), variables.get("nextPageToken"))
            SITE.asked.append(("trips", key))
            self._answer(SITE.ride_pages.get(key, rows([])), self._trips_page)
        elif operation == "GetTrip":
            uuid = variables.get("tripUUID")
            _where, _desc, _subtitle, begin, _written = TRIPS[uuid]
            self._answer(SITE.trips.get(uuid, ("trip",)), lambda _a: self._json({"data": {
                "getTrip": {"trip": {"beginTripTime": begin, "fare": TRIPS[uuid][1],
                                     "status": "COMPLETED", "uuid": uuid},
                            "receipt": {"distance": "3.10", "distanceLabel": "miles",
                                        "duration": "12 minutes", "vehicleType": "UberX"}}}}))
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
        if written:
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


def open_their_tab(cdp_url, address, title):
    """A tab the person signed in with at home, opened by the browser
    itself the way login.bat's is, once it has drawn its page."""
    urllib.request.urlopen(urllib.request.Request(cdp_url + "/json/new?" + address,
                                                  method="PUT"), timeout=15).read()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        tabs = json.loads(urllib.request.urlopen(cdp_url + "/json/list", timeout=5).read())
        if any(t.get("title") == title for t in tabs):
            return
        time.sleep(0.2)
    pytest.fail("the tab for %s never drew" % address)


@pytest.fixture(scope="module")
def attached(browser_exe, server, tmp_path_factory):
    """A browser started as a program of its own with a debugging port,
    which is what the app attaches to at home. Its address, for cdp_url.
    testkit.drawn_browser hands it over only once a tab opened the way the
    app opens one has drawn a page, since a browser that has only just
    started can abort its first navigation.

    At home the person signed in to both sites in that browser, a tab on
    each, and the app reads from those tabs and leaves them open. So the
    two tabs are opened here too, before the app first attaches."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            open_their_tab(url, "http://%s:%d/trips" % (RIDERS_HOST, server), "My Trips")
            open_their_tab(url, "http://%s:%d/orders" % (EATS_HOST, server), "Past Orders")
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


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
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return sorted(data)


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
    """What the failure file says of the list, in counts and in this app's
    own words, which is all a file a tester posts may carry."""
    files = failure_files(tmp_path)
    assert len(files) == 1, files
    report = json.loads(files[0].read_text(encoding="utf-8"))
    return (report.get("extra") or {}).get("postmortem")


def list_calls():
    return [a for a in SITE.asked if a[0] in ("trips", "orders")]


# -- a list cut short ----------------------------------------------------------------

@pytest.mark.parametrize("answer, stop, status", [(refused(429), "refused", 429),
                                                  (DROPPED, "failed", 0),
                                                  (NO_TRIPS, "no list", 200)],
                         ids=["refused", "no answer", "errors and no trips"])
def test_a_trip_list_cut_short_is_used_and_the_run_does_not_finish(attached, answer, stop, status,
                                                                   tmp_path, capsys):
    """The first page of trips came and the second did not. The trip on the
    first is real and so are the orders, so the pilot downloads them, and
    the older trips are missing, so it stops rather than finish. An answer
    with errors in place of the trips was read as the end of the list."""
    SITE.ride_pages[("PERSONAL", T1)] = answer
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Uber stopped answering the trip list partway" in said, said
    assert "this run stops here rather than finish" in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert known(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS), "what came is kept"
    assert downloaded(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS), "and used"
    assert how_far_it_got(tmp_path) == {"side": "rides", "calls": 2, "stop": stop,
                                        "status": status}


def test_an_order_list_cut_short_is_used_and_the_run_does_not_finish(attached, tmp_path, capsys):
    SITE.eats_pages[ORDER_A] = refused(429)
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Uber stopped answering the order list partway" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert known(tmp_path) == sorted(RIDES_KEYS + ["Uber Eats:" + ORDER_A])
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + ["Uber Eats:" + ORDER_A])
    assert how_far_it_got(tmp_path) == {"side": "uber eats", "calls": 2, "stop": "refused",
                                        "status": 429}


def test_a_trip_list_that_never_came_still_leaves_the_orders_to_download(attached, tmp_path,
                                                                         capsys):
    """Refused at its first call, the trip list gave nothing, which is not a
    history with no trips in it. The other side is read and used all the
    same, and the run stops at its end."""
    SITE.ride_pages[("PERSONAL", None)] = refused(429)
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Uber did not answer when this asked for the trip list" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert known(tmp_path) == sorted(EATS_KEYS)
    assert downloaded(tmp_path) == sorted(EATS_KEYS)


@pytest.mark.parametrize("answer", [refused(503), refused(429), DROPPED],
                         ids=["server error", "too many requests", "no answer"])
def test_a_trip_whose_details_got_no_answer_is_not_left_for_a_clean_run(attached, answer,
                                                                        tmp_path, capsys):
    """A trip's day comes from its details, and a trip whose details got no
    answer was left to be read next run while this one finished clean. Uber
    not answering is a trip missed, so the run stops at its end."""
    SITE.trips[TRIP_C] = answer
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "did not answer with their details" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert known(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)
    assert downloaded(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)


@pytest.mark.parametrize("answer", [refused(404), ERRORS_ONLY], ids=["not found", "errors only"])
def test_a_trip_answered_without_its_details_does_not_stop_every_run(attached, answer, tmp_path,
                                                                    capsys):
    """Uber answered for the trip, without the trip. That may be the trip's
    own and come back the same every time, and stopping on it would stop
    every run, so it is read again next run, as a trip that cannot be
    placed on a day is, and the run finishes."""
    SITE.trips[TRIP_C] = answer
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "were answered without their details" in said, said
    assert panel_reads(out)["stopped"] == 0
    assert known(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)
    assert failure_files(tmp_path), "written down for whoever repairs this"


@pytest.mark.parametrize("command", [["--all", "--yes"], ["--discover"]], ids=["run all", "discover"])
def test_run_all_and_discover_do_not_finish_on_a_list_cut_short(attached, command, tmp_path,
                                                                 capsys):
    """Each command that reads the lists stops in its own place, Run All
    once it has downloaded what came and Discover once it has listed it."""
    SITE.ride_pages[("PERSONAL", T1)] = refused(429)
    out = stopped_run(tmp_path, attached, capsys, *command)

    said = folded(out)
    assert "Uber stopped answering the trip list partway" in said, said
    assert "Discovery complete" not in said, said
    assert known(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)
    if command[0] == "--all":
        assert downloaded(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)
        assert panel_reads(out)["stopped"] == 1


# -- what worked before -------------------------------------------------------------------

def test_both_lists_read_to_their_end_finish_clean(attached, tmp_path, capsys):
    """Every page of both lists is read, and the run finishes."""
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "stopped answering" not in said, said
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


# -- Resume after a run that stopped ---------------------------------------------------

def test_resume_reads_the_lists_after_a_pilot_whose_trip_list_never_came(attached, tmp_path,
                                                                        capsys):
    """The panel says to press Resume once a run has stopped. Resume worked
    from the purchases already found, and the stopped pilot found no trip,
    so it downloaded the orders and finished clean, the trips never read."""
    SITE.ride_pages[("PERSONAL", None)] = refused(429)
    either_run(tmp_path, attached, capsys, "--pilot")

    SITE.reset()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert ("trips", ("PERSONAL", None)) in SITE.asked, "Resume asked for the trips"
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_reads_what_a_list_cut_short_left_out(attached, tmp_path, capsys):
    SITE.ride_pages[("PERSONAL", T1)] = refused(429)
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.reset()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert known(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_goes_on_with_what_was_found_when_the_list_is_refused_again(attached, tmp_path,
                                                                          capsys):
    """When Uber refuses again, Resume still downloads the purchases it has,
    as it did, and does not call itself finished."""
    SITE.ride_pages[("PERSONAL", T1)] = refused(429)
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.ride_pages[("PERSONAL", None)] = refused(429)
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert "did not answer when this asked for the trip list" in folded(out), out
    assert downloaded(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_whole_lists_does_not_read_them_again(attached, tmp_path, capsys):
    """A Discover that read both lists to their end leaves nothing for
    Resume to read again, so Resume goes straight to the purchases found."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.asked.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert not list_calls(), "Resume left both lists alone"
    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 0


def test_resume_that_meets_a_list_cut_short_again_does_not_finish(attached, tmp_path, capsys):
    """The pilot downloaded what came, so when Resume reads the lists again
    and the trips are cut short at the same place, there is nothing new to
    download. That is still not a finished run."""
    SITE.ride_pages[("PERSONAL", T1)] = refused(429)
    either_run(tmp_path, attached, capsys, "--pilot")
    assert downloaded(tmp_path) == sorted(["Rides:" + TRIP_A] + EATS_KEYS)

    SITE.asked.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert list_calls(), "Resume asked for the lists"
    assert "Nothing to resume" in folded(out), out
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_a_side_asked_for_a_sign_in_reads_that_side_again(attached, tmp_path,
                                                                       capsys):
    """The orders asked for a sign-in, so that side stopped and the run
    with it, and the panel said to press Resume. Resume worked from the
    purchases already found, so the orders were never looked for. Now the
    lists are read again first."""
    SITE.eats_pages[""] = refused(401)
    out = stopped_run(tmp_path, attached, capsys, "--pilot")
    assert "Uber Eats asked you to sign in" in folded(out), out

    SITE.reset()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert downloaded(tmp_path) == sorted(RIDES_KEYS + EATS_KEYS)
    assert panel_reads(out)["stopped"] == 0
