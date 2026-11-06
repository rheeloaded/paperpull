"""A month with no transactions, told from a month that did not draw (#136).

Venmo's Statements page has two sentences for a month with nothing in it,
and which of them a person sees goes by a setting of their own account. The
app knew one, "No transactions yet for this month", so a month that said
"There are no transactions for these dates." read as a month still drawing,
and the list stopped there for good with "the month's transactions did not
finish drawing", every run, with nothing saved.

So an empty month has to pass for neither a stopped list nor anything else,
and a month that really did not draw has to stop. When Venmo's own request
for a month fails, its page draws the heading and the picker and no list and
no words, and a month holding only pending transactions draws no completed
list and no words either. Neither is an empty month.

In a real browser, on the page's real address, since what the app reads is
what the browser shows of the page. The pages are made up here from the
shapes Venmo's own page code draws, read from its public files on
2026-11-03, and every name, date and amount is invented. Nothing reaches
Venmo. Every request is answered here, and the browser can resolve no host
at all, so one that slipped past would fail rather than go out. No answer
here is a redirect, since Playwright hands only the first address of a
redirect to its route and the next one would go to the network.
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import venmo_docs as docs  # noqa: E402
import venmo_site as site  # noqa: E402
from paperpull_core import listing  # noqa: E402
from paperpull_core.models import State  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")

HOST = "account.venmo.com"
NO_HOST_RESOLVES = "--host-resolver-rules=MAP * ~NOTFOUND"
TODAY = date(2026, 10, 13)
FAKE_PROFILE_ID = "4455667788990011"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]

REPORTED = "the month's transactions did not finish drawing"

ROW = ('<a class="transactionListItem_transactionItem__Aq604" role="group" href="/statement/detail/1">'
       '<span>An invented payment</span><span data-testid="money">-$1.00</span></a>')
ROWS = ('<div class="transactionListItem_sectionContainer__x"><b>Completed transactions</b>'
        '<div class="transactionListItem_completedTransactionList__nfpG1">%s</div></div>' % (ROW * 3))
PENDING = ('<div class="transactionListItem_sectionContainer__x"><b>Pending transactions</b>'
           '<p>These transactions are not final and are subject to change</p>'
           '<div class="transactionListItem_pendingTransactionList__HLD2p">%s</div></div>' % ROW)
# The older page's words, drawn in its own paragraph with a line break.
OLDER_EMPTY = ('<p class="statement_noTransactionMessage__4GT4m">There are no transactions for these '
               'dates.<br>To view past transactions, select new dates.</p>')
# The newer page's words, under the month's own name and a picture.
NEWER_EMPTY = ('<div class="emptyTxn_noTrans__D6goP"><p class="emptyTxn_selectMonth__F4j_m">%s</p>'
               '<p>No transactions yet for this month, but as soon as they start rolling in, '
               'we’ll list them here.</p></div>')
# Venmo's own request for the month failed. Its notice has gone by the time
# the app gives up, and no list and no words are drawn.
NOTHING = ""
HIDDEN_WORDS = '<p style="display:none">There are no transactions for these dates.</p>'


def statement_url(month=10, year=2026):
    return (f"https://{HOST}/statement?accountType=personal&month={month}"
            f"&profileId={FAKE_PROFILE_ID}&year={year}")


def statement_page(month_id, body, footer="", later=None):
    """One month's page as it draws: the shimmer, then `body`, then, when
    given, `later` a moment after."""
    year, month = month_id.split("-")
    name = f"{MONTH_NAMES[int(month) - 1]} {year}"
    body = body % name if "%s" in body else body
    later_js = ("setTimeout(() => { place(%s); }, 120);" % json.dumps(later)) if later else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Venmo | Account Statement</title>
</head><body><nav><a href="/account/logout">Log out</a></nav>
<main><h1>Account Statement</h1>
<input type="text" value="{name}">
<button>Download CSV</button><button>Send to email</button>
<section id="statement"><div data-testid="shimmer"></div></section>
</main><footer>{footer}</footer>
<script>
const place = html => {{ document.getElementById('statement').innerHTML = html; }};
setTimeout(() => {{ place({json.dumps(body)}); {later_js} }}, 30);
</script></body></html>"""


class Venmo:
    """The made-up site. `months` says what a month draws, and a month not
    named draws its rows."""

    def __init__(self):
        self.months, self.footer, self.later = {}, "", {}

    def answer(self, route):
        parts = urlsplit(route.request.url)
        if parts.hostname != HOST:
            route.abort()
            return
        if parts.path == "/statement" and not parts.query:
            # The plain address settles on the month's own, in the page.
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body="<!doctype html><script>history.replaceState(null, '', %s);</script>"
                               % json.dumps(statement_url()))
            return
        q = parse_qs(parts.query)
        month = "%s-%02d" % (q["year"][0], int(q["month"][0]))
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=statement_page(month, self.months.get(month, ROWS), self.footer,
                                          self.later.get(month)))


@pytest.fixture(scope="module")
def chromium():
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[NO_HOST_RESOLVES])
        yield browser
        browser.close()


@pytest.fixture
def venmo():
    return Venmo()


@pytest.fixture
def page(chromium, venmo, monkeypatch):
    """A tab on the made-up site, with the app's waits short."""
    monkeypatch.setattr(site, "POLL_MS", 25)
    monkeypatch.setattr(site, "EMPTY_HOLD_MS", 300)
    monkeypatch.setattr(site, "SETTLE_MS", 1500)
    context = chromium.new_context()
    context.route("**/*", venmo.answer)
    tab = context.new_page()
    yield tab
    context.close()


def months_read(page, walk=3):
    return [d.document_id for d in site.collect_download_docs(page, today=TODAY, limit=walk)]


def stop_of(page, walk=3):
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, today=TODAY, limit=walk)
    return stop.value


def test_the_older_page_s_words_are_an_empty_month_and_the_walk_goes_on(page, venmo):
    venmo.months["2026-08"] = OLDER_EMPTY
    assert months_read(page) == ["2026-09", "2026-07"]


def test_the_newer_page_s_words_are_an_empty_month_and_the_walk_goes_on(page, venmo):
    venmo.months["2026-08"] = NEWER_EMPTY
    assert months_read(page) == ["2026-09", "2026-07"]


def test_two_months_read_and_then_months_with_nothing_as_in_the_report(page, venmo):
    """The report's walk, two statements and then a month with none, with
    more of both behind it."""
    venmo.months.update({"2026-07": OLDER_EMPTY, "2026-06": OLDER_EMPTY, "2026-04": OLDER_EMPTY})
    assert months_read(page, 6) == ["2026-09", "2026-08", "2026-05"]


def test_every_month_empty_is_a_list_with_nothing_in_it(page, venmo):
    venmo.months.update({m: OLDER_EMPTY for m in ("2026-09", "2026-08", "2026-07")})
    assert months_read(page) == []


def test_each_empty_month_holds_before_it_is_believed(page, venmo):
    """The sentence for a moment and then the rows is a month with rows,
    with the older page's words as with the newer's."""
    venmo.months["2026-09"] = OLDER_EMPTY
    venmo.later["2026-09"] = ROWS
    assert months_read(page, 1) == ["2026-09"]


def test_a_month_that_drew_nothing_stops_and_says_so(page, venmo):
    venmo.months["2026-08"] = NOTHING
    stop = stop_of(page)
    assert [d.document_id for d in stop.docs] == ["2026-09"]
    assert stop.month == "2026-08"
    assert str(stop) == "the page drew neither the month's transactions nor its words for a month with none"


def test_a_month_holding_only_pending_transactions_is_never_empty(page, venmo):
    venmo.months["2026-08"] = PENDING
    stop = stop_of(page)
    assert [d.document_id for d in stop.docs] == ["2026-09"]
    assert str(stop) == "the month shows pending transactions and no completed ones"


def test_the_words_beside_pending_transactions_are_not_an_empty_month(page, venmo):
    venmo.months["2026-08"] = PENDING + OLDER_EMPTY
    assert str(stop_of(page)) == "the page draws transactions and says there are none"


def test_the_words_beside_completed_transactions_are_not_an_empty_month(page, venmo):
    venmo.months["2026-08"] = ROWS + OLDER_EMPTY
    assert str(stop_of(page)) == "the page draws transactions and says there are none"


def test_words_the_page_does_not_show_are_not_an_empty_month(page, venmo):
    venmo.months["2026-08"] = HIDDEN_WORDS
    assert stop_of(page).month == "2026-08"


def test_the_words_outside_the_statement_are_not_an_empty_month(page, venmo):
    venmo.months["2026-08"] = NOTHING
    venmo.footer = "There are no transactions for these dates."
    assert stop_of(page).month == "2026-08"


def test_a_month_of_rows_the_list_cannot_read_stops_as_it_did(page, venmo):
    """Something in the list that is not a row. The words of the fall-through
    are the ones the report quotes, and they stay for a list that is drawn."""
    venmo.months["2026-08"] = ROWS.replace("</a></div></div>", "</a><span>x</span></div></div>")
    assert str(stop_of(page)) == REPORTED


# The whole app on the same pages. A run holds its clock (HeldDay), since
# the walk goes back from the day the app reads.

class HeldDay(date):
    @classmethod
    def today(cls):
        return TODAY


def make_app(*args):
    tmp = tempfile.mkdtemp()
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out")})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([*args, "--config", str(cfg)]))


@pytest.fixture
def app_on(page, monkeypatch):
    monkeypatch.setattr(site, "_date", HeldDay)

    def made(*args):
        app = make_app(*args, "--start-date", "2026-06-01")
        app.page = lambda: page
        app._on_its_site = lambda: page
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        return app
    return made


def test_discover_reads_past_an_empty_month_and_calls_the_list_whole(app_on, venmo):
    venmo.months["2026-07"] = OLDER_EMPTY
    app = app_on("--discover")
    with redirect_stdout(io.StringIO()) as said:
        app.cmd_discover()
    assert "stopped partway" not in said.getvalue()
    assert "Discovery complete" in said.getvalue()
    assert sorted(r["document_id"] for r in app.discovery.data.values()) == ["2026-06", "2026-08", "2026-09"]
    assert listing.last(app) != listing.STOPPED
    assert list(app.paths.diagnostics.glob("failure-*.json")) == []


def test_a_pilot_past_an_empty_month_saves_its_statement(app_on, venmo):
    """The report's second half, a pilot that saved nothing."""
    venmo.months["2026-08"] = OLDER_EMPTY
    app = app_on("--pilot")
    with redirect_stdout(io.StringIO()):
        app.cmd_pilot()
    records = list(app.progress.data.values())
    assert [(r["document_id"], r["state"]) for r in records] == [("2026-09", State.COMPLETED.value)]
    saved = Path(records[0]["pdf_path"])
    assert saved.name == "2026-09-30 Venmo Statement.pdf"
    assert saved.read_bytes()[:5] == b"%PDF-"


def test_a_list_that_stops_says_which_month_and_writes_what_it_saw(app_on, venmo):
    venmo.months["2026-07"] = NOTHING
    app = app_on("--discover")
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "stopped partway" in said.getvalue()
    assert "It stopped on 2026-07." in said.getvalue()
    assert listing.last(app) == listing.STOPPED
    assert sorted(r["document_id"] for r in app.discovery.data.values()) == ["2026-08", "2026-09"]
    text = next(app.paths.diagnostics.glob("failure-*.json")).read_text(encoding="utf-8")
    assert FAKE_PROFILE_ID not in text
    seen = json.loads(text)["extra"]["month_page"]
    assert {k: seen[k] for k in ("heading", "months", "lists", "rows", "children", "pager", "pending",
                                 "loading", "empty")} == {
        "heading": True, "months": 1, "lists": 0, "rows": 0, "children": 0, "pager": 0, "pending": 0,
        "loading": 0, "empty": False}
