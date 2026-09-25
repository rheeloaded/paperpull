"""Each way of waiting, against a page built to defeat every other one.

A wait that works on a page it was never going to fail on proves
nothing. Every page below is the shape of a real bug, and on each of them
all but one strategy finishes and leaves the page not ready. The list is
ordered with the right answer last, so the test also proves the wrong
ones were tried first, came back, and did not claim a win they had not
earned.

A local server supplies the parts a page on disk cannot, a request that
takes a second and an image that holds up the load event.
"""
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.journal import Journal, summarize
from paperpull_core.ready import (count_reaches, count_settles, has, load,
                                  load_complete, network_idle, ready,
                                  url_changes, url_matches)

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

ROW = "document.body.insertAdjacentHTML('beforeend', '<p class=row>r</p>')"

PAGES = {
    # Costco's tab switch. The list is asked for and drawn when the
    # answer comes, so the load is long over and nothing is on screen.
    "/fetch": """<h1>Orders</h1><script>
        fetch('/slow?ms=3000').then(() => { %s; %s; %s; });
        </script>""" % (ROW, ROW, ROW),
    # Drawn on a timer after the network has gone quiet, which is what a
    # framework that renders on the next tick of its own scheduler does.
    "/timer": """<h1>Orders</h1><script>
        setTimeout(() => { %s; %s; %s; }, 4000);
        </script>""" % (ROW, ROW, ROW),
    # A list that draws in pieces. The first row says nothing about the
    # sixth.
    "/pieces": """<h1>Orders</h1><script>
        let n = 0;
        const t = setInterval(() => { %s; if (++n === 6) clearInterval(t); },
                              400);
        </script>""" % ROW,
    # Costco's receipt. Only the part after the # changes, so nothing
    # loads, and a wait for a load waits for ever.
    "/hash": """<h1>Orders</h1><script>
        setTimeout(() => { location.hash = '#/receipts'; }, 3000);
        </script>""",
    # The document is parsed long before an image lets the load finish.
    "/image": """<h1>Orders</h1><img src="/slow?ms=3000&img=1">""",
    # Ready from the start, the case every working run is.
    "/done": """<h1>Orders</h1><p class=row>r</p><p class=row>r</p>
        <p class=row>r</p>""",
}

GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9"
       b"\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02"
       b"\x02D\x01\x00;")


class _Handler(BaseHTTPRequestHandler):
    # Keep-alive, one connection reused rather than one per request, as in
    # test_delivery_live.py. Every answer here carries its length.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/slow":
            q = parse_qs(parts.query)
            time.sleep(int(q.get("ms", ["0"])[0]) / 1000)
            body, kind = (GIF, "image/gif") if "img" in q else (b"{}",
                                                               "application/json")
        elif parts.path in PAGES:
            body = ("<!doctype html><title>t</title>%s"
                    % PAGES[parts.path]).encode()
            kind = "text/html"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def _outcomes(got):
    return [(a.strategy, a.outcome) for a in got.attempts]


ROWS_3 = has("p.row", 3)


def test_a_list_drawn_when_its_answer_comes_needs_network_quiet(site, page):
    """A count that settles on nothing is the wait that read Costco's
    list empty. The network going quiet is the one that is right."""
    page.goto(site + "/fetch")
    got = ready(page, [load(), count_settles("p.row", quiet_ms=300,
                                             at_least=0), network_idle()],
                invariant=ROWS_3, budget_ms=15000)
    assert got.ready and got.winner == "network_idle"
    assert _outcomes(got)[:2] == [("loaded", "not_satisfied"),
                                  ("count_settled", "not_satisfied")]


def test_a_list_drawn_on_a_timer_needs_the_count(site, page):
    page.goto(site + "/timer")
    got = ready(page, [load(), network_idle(), count_reaches("p.row", 3)],
                invariant=ROWS_3, budget_ms=15000)
    assert got.ready and got.winner == "count_reached"
    assert _outcomes(got)[:2] == [("loaded", "not_satisfied"),
                                  ("network_idle", "not_satisfied")]


def test_a_list_drawn_in_pieces_needs_the_count_to_stop_moving(site, page):
    """The first row arriving is not the list arriving."""
    page.goto(site + "/pieces")
    got = ready(page, [load(), count_reaches("p.row"),
                       count_settles("p.row", quiet_ms=1200)],
                invariant=has("p.row", 6), budget_ms=15000)
    assert got.ready and got.winner == "count_settled"
    assert _outcomes(got)[:2] == [("loaded", "not_satisfied"),
                                  ("count_reached", "not_satisfied")]


def test_a_change_after_the_hash_is_seen_only_by_watching_the_address(
        site, page):
    """Costco's receipt route. Nothing loads, so the load wait comes back
    at once and a count of what was already there proves nothing."""
    page.goto(site + "/hash")
    on_receipts = url_matches(r"#/receipts$")
    got = ready(page, [load(), network_idle(), count_reaches("h1"),
                       url_changes()],
                invariant=on_receipts, budget_ms=15000)
    assert got.ready and got.winner == "url_changed"
    assert [o for _, o in _outcomes(got)[:3]] == ["not_satisfied"] * 3


def test_a_page_held_up_by_an_image_needs_the_full_load(site, page):
    page.goto(site + "/image", wait_until="commit")
    complete = load_complete()
    got = ready(page, [count_reaches("h1"), load("domcontentloaded"),
                       load("load")],
                invariant=complete, budget_ms=15000)
    assert got.ready and got.winner == "loaded"
    assert _outcomes(got)[:2] == [("count_reached", "not_satisfied"),
                                  ("dom_loaded", "not_satisfied")]


def test_a_page_already_ready_costs_one_question(site, page):
    """Every working run is this case, and it must stay as fast as it was
    before anything here existed."""
    page.goto(site + "/done")
    got = ready(page, [network_idle(), count_settles("p.row")],
                invariant=ROWS_3, budget_ms=15000)
    assert got.ready and got.winner == "already"
    assert _outcomes(got) == [("already", "satisfied")]
    assert got.elapsed_ms < 2000, "one question, not a wait"


# -- the budget ---------------------------------------------------------------

def test_the_budget_is_for_the_whole_call_not_for_each_guess(site, page):
    """Four guesses at a page that never comes right, one budget of a
    second. Summed per strategy that would be four seconds or more, and
    an app that used to give up in ten would give up in forty."""
    page.goto(site + "/done")
    t0 = time.monotonic()
    got = ready(page, [url_changes(), count_reaches(".never"),
                       network_idle(), count_settles(".never")],
                invariant=has(".never"), budget_ms=1000)
    took = (time.monotonic() - t0) * 1000
    assert not got.ready
    # Four guesses each given the whole second would take over four.
    assert took < 2800, "took %dms on a 1000ms budget" % took
    assert got.attempts[0].outcome == "timed_out"
    assert {a.outcome for a in got.attempts[1:]} == {"no_budget"}


def test_a_guess_that_could_hang_can_be_given_a_smaller_share(site, page):
    page.goto(site + "/timer")
    got = ready(page, [url_changes(within_ms=300), count_reaches("p.row", 3)],
                invariant=ROWS_3, budget_ms=15000)
    assert got.ready and got.winner == "count_reached"
    first = got.attempts[0]
    assert first.outcome == "timed_out" and first.ms < 3000, "not the 8s budget"


# -- what it tells the maintainer ---------------------------------------------

def test_the_journal_names_the_wait_that_worked(site, page):
    """The point of trying several is learning which one to keep. It is
    said in the file even when the run went fine."""
    j = Journal(page)
    page.goto(site + "/timer")
    ready(page, [load(), network_idle(), count_reaches("p.row", 3)],
          invariant=ROWS_3, budget_ms=15000, journal=j, name="order rows")
    entry = j.report()["entries"][-1]
    assert entry["kind"] == "waited"
    assert entry["winner"] == "count_reached"
    assert [a["strategy"] for a in entry["attempts"]] == [
        "loaded", "network_idle", "count_reached"]
    assert all(isinstance(a["ms"], int) for a in entry["attempts"])
    said = " ".join(summarize(j.report()))
    assert "\"order rows\" was ready after count_reached" in said
    assert "Tried loaded, network_idle, count_reached" in said


def test_a_wait_that_never_came_says_what_was_tried(site, page):
    j = Journal(page)
    page.goto(site + "/done")
    ready(page, [count_reaches(".never")], invariant=has(".never"),
          budget_ms=300, journal=j, name="the receipt")
    said = " ".join(summarize(j.report()))
    assert "\"the receipt\" never became ready. Tried count_reached" in said


# -- nothing raises -----------------------------------------------------------


def test_a_page_that_closed_is_an_answer_not_an_exception(site, browser):
    """A tester closing the tab mid-run. The wait says not ready and the
    run decides what to do, rather than a trace taking the run down."""
    pg = browser.new_page()
    pg.goto(site + "/timer")
    pg.close()
    got = ready(pg, [count_reaches("p.row", 3), network_idle()],
                invariant=ROWS_3, budget_ms=2000)
    assert not got.ready
    assert {a.outcome for a in got.attempts} <= {"error", "timed_out"}


def test_a_selector_in_playwrights_dialect_is_named_not_thrown(site, page):
    """:has-text() is a SyntaxError inside the page, and has been shipped
    twice. It is reported as what it is and the next guess gets its
    turn."""
    page.goto(site + "/timer")
    got = ready(page, [count_reaches("p:has-text('r')"),
                       count_reaches("p.row", 3)],
                invariant=ROWS_3, budget_ms=15000)
    assert _outcomes(got) == [("count_reached", "invalid_selector"),
                              ("count_reached", "satisfied")]


def test_a_new_viewer_source_is_ready_and_a_hash_change_is_not(site, page):
    """The PG&E draft counted the page's own address as a source, so a
    hash change right after the click read as the viewer arriving, three
    seconds before it did. Only a viewer pointing somewhere new counts."""
    from paperpull_core.ready import new_source, sources_of

    page.goto(site + "/done")
    page.evaluate("""() => {
        document.body.insertAdjacentHTML('beforeend',
            '<iframe src="about:blank#keepalive"></iframe>');
    }""")
    before = sources_of(page, "iframe, embed, object")
    page.evaluate("""() => {
        location.hash = '#/bill';
        setTimeout(() => document.body.insertAdjacentHTML('beforeend',
            '<div role=dialog><iframe src="' + URL.createObjectURL(
                new Blob(['%PDF-1.4'], {type: 'application/pdf'})) +
            '"></iframe></div>'), 1500);
    }""")
    arrived = new_source("iframe, embed, object", before)
    assert not arrived(page), "a hash change and an old frame are not a bill"
    got = ready(page, [count_reaches("iframe", 2)], invariant=arrived,
                budget_ms=5000)
    assert got.ready and got.winner == "count_reached"
    assert got.attempts[0].ms >= 900
