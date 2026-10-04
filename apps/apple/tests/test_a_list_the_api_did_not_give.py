"""Discovery against Apple lists that stop answering partway, in a real
browser.

Both stores opened signed in, and then Report a Problem stopped giving the
purchases. Its purchase search was refused, got no answer or answered
empty partway, or its family list did not answer or answered without its
list. Discovery said so, wrote a failure file and went on, or read the
answer as the end, and since only a store that asked for a sign-in stopped
the run, Pilot and Run All finished clean with purchases missed. A list
that did not come whole is not a list with nothing more in it.

The Apple Store's side is read from pages whose shape for an account with
no orders was never seen, so a list or a details page without its data is
written down and read again next run without stopping every run.

What was read is real, so it is kept and the run goes on with it, the
other store included. The rest is missing, so the run stops at its end
rather than finish, and Resume reads both lists again before anything
else.

The browser is started as a program of its own with a debugging port, the
way login.bat leaves one open, and the app attaches to it over CDP exactly
as it does at home. Apple's two sites are two made-up host names the
browser is told to find on this machine, and every other name fails to
resolve, so nothing reaches Apple. Every member, order, name and amount is
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
import apple_receipts as app_mod
import apple_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import run_reporting, testkit

REPORT_HOST = "reportaproblem.apple.test"
STORE_HOST = "www.apple.test"

# Apple's two hosts are found on this machine, and every other name fails
# to resolve, this machine's own address aside, so a page the test forgot to
# point here goes nowhere.
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1, MAP * ~NOTFOUND , "
         "EXCLUDE 127.0.0.1" % (REPORT_HOST, STORE_HOST))

TOKEN = "TESTTOKEN"
ORGANIZER, CHILD = "10000001", "10000002"

HOME = ("<!doctype html><html><head><title>Report a Problem</title></head><body>"
        "<h1>Report a Problem</h1><p>Found 4 results.</p>"
        "<script>sessionStorage.setItem('x-apple-xsrf-token', '%s')</script>"
        "</body></html>" % TOKEN)

FAMILY = {"members": [
    {"dsid": ORGANIZER, "givenName": "Dana", "familyName": "Example", "isHeadOfHousehold": True},
    {"dsid": CHILD, "givenName": "Quill", "familyName": "Example", "isHeadOfHousehold": False}]}


def bought(weborder, dsid, name, detail, paid, when, free=False):
    return {"purchaseId": "80000000000001", "dsid": dsid,
            "invoiceAmount": None if free else paid,
            "plis": [{"amountPaid": "$0.00" if free else paid, "isFreePurchase": free,
                      "quantity": 0 if free else 1,
                      "lineItemType": "IOSApp" if free else "BaseLineItem",
                      "localizedContent": {"nameForDisplay": name, "detailForDisplay": detail,
                                           "mediaType": "iOS App" if free else "In-App Purchase"}}],
            "weborder": weborder, "invoiceDate": None, "purchaseDate": when,
            "isPendingPurchase": False, "estimatedTotalAmount": paid}


# Three paid purchases and a free download, newest first as the search
# gives them, two batches of them.
GEMS = bought("MLF0TEST21", ORGANIZER, "Gem Pack 3", "Crystal Quarry", "$4.99",
              "2026-05-14T12:00:00Z")
FREE = bought("R00TEST0000021", ORGANIZER, "Lantern Notes", "Example Dev LLC", "$0.00",
              "2026-05-06T12:00:00Z", free=True)
BRICKS = bought("MLF0TEST22", CHILD, "400 Bricks", "Blockville", "$4.37",
                "2026-04-02T12:00:00Z")
PREMIER = bought("MLF0TEST23", ORGANIZER, "Premier", "Apple One", "$21.43",
                 "2025-11-20T12:00:00Z")
PAID = {p["weborder"]: p for p in (GEMS, BRICKS, PREMIER)}

NEWER_KEYS = ["App Store:MLF0TEST21", "App Store:MLF0TEST22"]
ALL_KEYS = NEWER_KEYS + ["App Store:MLF0TEST23"]


def receipt_html(weborder):
    """Apple's emailed receipt, as the invoice call hands it over."""
    raw = PAID[weborder]
    line = raw["plis"][0]["localizedContent"]
    return ("<html><head><style>body { font-family: sans-serif }</style></head><body>"
            "<h1>Receipt</h1><p>%s</p><p>Order ID: %s</p>"
            "<p>Document: 000000000001</p><p>Apple Account: dana@example.com</p>"
            "<table><tr><td>%s</td><td>%s</td><td>%s</td></tr></table>"
            "<p>Billing and Payment</p><p>Dana Example</p><p>Subtotal %s</p>"
            "</body></html>" % (raw["purchaseDate"][:10], weborder, line["detailForDisplay"],
                                line["nameForDisplay"], raw["invoiceAmount"], raw["invoiceAmount"]))


def page_with(data):
    """A store page carrying its data the way Apple's do, in init_data."""
    return ("<!doctype html><html><head><title>Your Orders</title></head><body>"
            "<h1>Your Orders</h1><script id=\"init_data\" type=\"application/json\">%s</script>"
            "</body></html>" % json.dumps(data))


# A store page that came without its data.
BARE = ("<!doctype html><html><head><title>Your Orders</title></head><body>"
        "<h1>Your Orders</h1></body></html>")

NO_ORDERS = page_with({"orderList": {"d": {"moreOrdersAvailable": False}, "c": []}})


def one_order(detail_url):
    return page_with({"orderList": {"d": {"moreOrdersAvailable": False},
                                    "c": ["order-W0000000001"],
                                    "order-W0000000001": {
                                        "d": {"webOrderNumber": "W0000000001"}, "c": ["0000101"],
                                        "0000101": {"d": {"quantity": 1,
                                                          "deliveryDate": "Delivered March 9, 2026",
                                                          "productShortName": "Invented Tablet",
                                                          "orderDetailUrl": detail_url}}}}})


# What a search batch answers. A batch of purchases and the next batch's
# id, or one of the ways it does not come.
def batch(purchases, following=None):
    return ("batch", purchases, following)


def refused(status):
    return ("status", status)


# The connection closed with nothing sent, which the page's fetch meets as a
# network error rather than an answer.
DROPPED = ("drop",)
# A 200 with nothing in it, which is how Report a Problem answers a receipt
# it fails to give, RECORDED.
EMPTY = ("body", "application/json", "")

# Who is signed in, as the page's own call answers it, an account in a
# family with Family Sharing on.
LOGIN = {"dsid": ORGANIZER, "name": "Dana Example", "enableFamilyUI": True,
         "enableFamilyAPI": True}


class FakeApple:
    """What the made-up sites answer, set by each test. Both lists whole
    unless a test says otherwise."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.family = ("family",)
        self.batches = {None: batch([GEMS, FREE, BRICKS], "BATCH0002"),
                        "BATCH0002": batch([PREMIER])}
        self.store_list = NO_ORDERS
        self.store_details = {}
        self.asked = []
        self.seen = []


SITE = FakeApple()


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

    def _html(self, text):
        self._send(text.encode("utf-8"), "text/html; charset=utf-8")

    def _host(self):
        return (self.headers.get("Host") or "").split(":")[0]

    def _answer(self, answer, given):
        if answer[0] == "drop":
            self.close_connection = True
        elif answer[0] == "status":
            self._json({"errors": [{"message": "refused"}]}, answer[1])
        elif answer[0] == "body":
            self._send(answer[2].encode("utf-8"), answer[1])
        else:
            given(answer)

    def do_GET(self):
        host, path = self._host(), urlsplit(self.path).path
        SITE.seen.append((host, "GET", path))
        parts = path.strip("/").split("/")
        if host == REPORT_HOST and path == "/":
            self._html(HOME)
        elif host == REPORT_HOST and path == site.FAMILY_PATH:
            SITE.asked.append(("family", None))
            self._answer(SITE.family, lambda _a: self._json(FAMILY))
        elif host == REPORT_HOST and path == site.LOGIN_PATH:
            self._json(LOGIN)
        elif host == REPORT_HOST and len(parts) == 4 and parts[:2] == ["api", "order"] \
                and parts[2] in PAID:
            self._json({"email": "dana@example.com", "invoice": receipt_html(parts[2]),
                        "refund": None, "vat": None})
        elif host == STORE_HOST and path == "/shop/order/list":
            self._html(SITE.store_list)
        elif host == STORE_HOST and path in SITE.store_details:
            self._html(SITE.store_details[path])
        else:
            self.send_error(404)

    def do_POST(self):
        host, path = self._host(), urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SITE.seen.append((host, "POST", path))
        if host == REPORT_HOST and path == site.SEARCH_PATH:
            SITE.asked.append(("search", body.get("batchId")))
            self._answer(SITE.batches.get(body.get("batchId"), batch([])),
                         lambda a: self._json({"batchId": body.get("batchId"),
                                               "nextBatchId": a[2], "query": body,
                                               "purchases": a[1]}))
        else:
            self.send_error(404)

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

    At home the person signed in to Report a Problem in that browser, and
    the app reads from that tab and leaves it open. So the tab is opened
    here too, before the app first attaches. The store's pages are read in
    a tab the app opens for itself, at home as here."""
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            open_their_tab(url, "http://%s:%d/" % (REPORT_HOST, server), "Report a Problem")
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_apple(server, monkeypatch):
    """Both of Apple's sites are the made-up ones, and every pause and wait
    is short."""
    SITE.reset()
    report = "http://%s:%d/" % (REPORT_HOST, server)
    store = "http://%s:%d/shop/order/list" % (STORE_HOST, server)
    monkeypatch.setattr(site, "REPORT_HOST", REPORT_HOST)
    monkeypatch.setattr(site, "REPORT_URL", report)
    monkeypatch.setattr(site, "STORE_LIST_URL", store)
    for name in ("home", "login", "orders"):
        monkeypatch.setitem(site.URLS, name, report)
    monkeypatch.setitem(site.URLS, "store_orders", store)
    # Every call is only made from a tab on one of Apple's own hosts. Here
    # those hosts are the made-up ones.
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname in (REPORT_HOST, STORE_HOST))
    monkeypatch.setattr(site, "STORE_PAUSE_MS", 0)
    real_walk = site.walk_purchases
    monkeypatch.setattr(site, "walk_purchases",
                        lambda page, dsids, **kw: real_walk(page, dsids, **dict(kw, pause_ms=0)))
    real_list = site.goto_store_list
    monkeypatch.setattr(site, "goto_store_list",
                        lambda page, wait_ms=20000: real_list(page, wait_ms=min(wait_ms, 1500)))
    real_detail = site.read_order_detail
    monkeypatch.setattr(site, "read_order_detail",
                        lambda page, url, wait_ms=20000: real_detail(page, url,
                                                                    wait_ms=min(wait_ms, 1500)))
    return SITE


def store_detail_url(server):
    return "http://%s:%d/shop/order/detail/100001/W0000000001" % (STORE_HOST, server)


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


def searches():
    return [a for a in SITE.asked if a[0] == "search"]


# -- a list cut short ----------------------------------------------------------------

@pytest.mark.parametrize("answer, stop, status", [(refused(503), "refused", 503),
                                                  (DROPPED, "failed", 0),
                                                  (EMPTY, "no list", 200)],
                         ids=["refused", "no answer", "an empty answer"])
def test_a_purchase_search_cut_short_is_used_and_the_run_does_not_finish(attached, answer, stop,
                                                                         status, tmp_path, capsys):
    """The first batch came and the second did not. The purchases in the
    first are real, so the pilot downloads them, and the older ones are
    missing, so it stops rather than finish. An empty answer was read as
    the end of the search."""
    SITE.batches["BATCH0002"] = answer
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Report a Problem stopped answering the purchase search partway" in said, said
    assert "this run stops here rather than finish" in said, said
    assert panel_reads(out)["stopped"] == 1, "the panel reads the run as stopped"
    assert known(tmp_path) == NEWER_KEYS, "what came is kept"
    assert downloaded(tmp_path) == NEWER_KEYS, "and used"
    assert how_far_it_got(tmp_path) == {"side": "app store", "batches": 2, "stop": stop,
                                        "status": status}


def test_a_purchase_search_that_never_came_is_not_an_empty_one(attached, tmp_path, capsys):
    SITE.batches[None] = refused(503)
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Report a Problem did not answer when this asked for your purchases" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert not known(tmp_path)


def test_a_family_list_that_did_not_answer_stops_the_run_at_its_end(attached, tmp_path, capsys):
    """Without the family list the search cannot be asked, so no purchase of
    that store was read at all."""
    SITE.family = refused(503)
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "did not answer with the family list" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert not searches() and not known(tmp_path)


@pytest.mark.parametrize("answer", [EMPTY, ("body", "text/html; charset=utf-8",
                                              "<!doctype html><html><body><p>One moment.</p>"
                                              "</body></html>")],
                         ids=["an empty answer", "a page in its place"])
def test_a_family_list_without_its_members_is_not_a_family_of_one(attached, answer, tmp_path,
                                                                  capsys):
    """An account with no Family Sharing answers an empty list of members
    (#55), and so the search is asked for the account signed in alone. An
    answer with no list at all was read the same way, and in a family the
    other members' purchases were missed while the run finished clean."""
    SITE.family = answer
    out = stopped_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "did not answer with the family list" in said, said
    assert panel_reads(out)["stopped"] == 1
    assert not searches(), "the search is not asked for one account in place of the family"


def test_a_store_order_list_without_its_orders_is_written_down_and_the_run_goes_on(attached,
                                                                                  tmp_path,
                                                                                  capsys):
    """What the list of an account with no Apple Store orders carries was
    never seen. A list without its data is written down for whoever repairs
    this, and the run is not stopped for it, since that would stop every
    run of such an account."""
    SITE.store_list = BARE
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "order list did not carry its orders" in said, said
    assert panel_reads(out)["stopped"] == 0
    assert downloaded(tmp_path) == ALL_KEYS
    assert failure_files(tmp_path)


def test_a_store_order_whose_details_did_not_come_is_read_again_next_run(attached, server,
                                                                         tmp_path, capsys):
    """An Apple Store order is recorded from its details page. One whose page
    does not carry the order may come that way every time, so it is read
    again next run, written down, and the run is not stopped for it."""
    detail = store_detail_url(server)
    SITE.store_list = one_order(detail)
    SITE.store_details[urlsplit(detail).path] = BARE
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "did not carry the order" in said, said
    assert panel_reads(out)["stopped"] == 0
    assert downloaded(tmp_path) == ALL_KEYS
    assert failure_files(tmp_path)


@pytest.mark.parametrize("command", [["--all", "--yes"], ["--discover"]], ids=["run all", "discover"])
def test_run_all_and_discover_do_not_finish_on_a_list_cut_short(attached, command, tmp_path,
                                                                 capsys):
    """Each command that reads the lists stops in its own place, Run All
    once it has downloaded what came and Discover once it has listed it."""
    SITE.batches["BATCH0002"] = refused(503)
    out = stopped_run(tmp_path, attached, capsys, *command)

    said = folded(out)
    assert "stopped answering the purchase search partway" in said, said
    assert "Discovery complete" not in said, said
    assert known(tmp_path) == NEWER_KEYS
    if command[0] == "--all":
        assert downloaded(tmp_path) == NEWER_KEYS
        assert panel_reads(out)["stopped"] == 1


# -- what worked before -------------------------------------------------------------------

def test_both_lists_read_to_their_end_finish_clean(attached, tmp_path, capsys):
    """Every batch of the search is read, the store's list holds nothing,
    and the run finishes."""
    out = finished_run(tmp_path, attached, capsys, "--pilot")

    said = folded(out)
    assert "Discovery complete" in said and "stopped answering" not in said, said
    assert downloaded(tmp_path) == ALL_KEYS
    assert panel_reads(out)["stopped"] == 0
    assert not failure_files(tmp_path)


# -- Resume after a run that stopped ---------------------------------------------------

def test_resume_reads_the_lists_after_a_pilot_whose_search_never_came(attached, tmp_path, capsys):
    """The panel says to press Resume once a run has stopped. Resume worked
    from the purchases already found, and the stopped pilot found none, so
    it had nothing to do and finished clean, the search never asked."""
    SITE.batches[None] = refused(503)
    either_run(tmp_path, attached, capsys, "--pilot")

    SITE.reset()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert searches(), "Resume asked the search"
    assert downloaded(tmp_path) == ALL_KEYS
    assert panel_reads(out)["stopped"] == 0


def test_resume_reads_what_a_search_cut_short_left_out(attached, tmp_path, capsys):
    SITE.batches["BATCH0002"] = refused(503)
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.reset()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert known(tmp_path) == ALL_KEYS
    assert downloaded(tmp_path) == ALL_KEYS
    assert panel_reads(out)["stopped"] == 0


def test_resume_goes_on_with_what_was_found_when_the_search_is_refused_again(attached, tmp_path,
                                                                            capsys):
    """When Apple refuses again, Resume still downloads the purchases it
    has, as it did, and does not call itself finished."""
    SITE.batches["BATCH0002"] = refused(503)
    either_run(tmp_path, attached, capsys, "--discover")

    SITE.batches[None] = refused(503)
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert "did not answer when this asked for your purchases" in folded(out), out
    assert downloaded(tmp_path) == NEWER_KEYS
    assert panel_reads(out)["stopped"] == 1


def test_resume_after_whole_lists_does_not_read_them_again(attached, tmp_path, capsys):
    """A Discover that read both lists to their end leaves nothing for
    Resume to read again, so Resume goes straight to the purchases found."""
    finished_run(tmp_path, attached, capsys, "--discover")

    SITE.asked.clear()
    SITE.seen.clear()
    out = finished_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert not searches(), "Resume left the search alone"
    assert (STORE_HOST, "GET", "/shop/order/list") not in SITE.seen, "and the store's list"
    assert downloaded(tmp_path) == ALL_KEYS
    assert panel_reads(out)["stopped"] == 0


def test_resume_that_meets_a_search_cut_short_again_does_not_finish(attached, tmp_path, capsys):
    """The pilot downloaded what came, so when Resume reads the search again
    and it is cut short at the same place, there is nothing new to
    download. That is still not a finished run."""
    SITE.batches["BATCH0002"] = refused(503)
    either_run(tmp_path, attached, capsys, "--pilot")
    assert downloaded(tmp_path) == NEWER_KEYS

    SITE.asked.clear()
    out = stopped_run(tmp_path, attached, capsys, "--resume", "--yes")

    assert searches(), "Resume asked the search"
    assert "Nothing to resume" in folded(out), out
    assert panel_reads(out)["stopped"] == 1
