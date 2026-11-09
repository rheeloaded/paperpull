"""A statement in two tabs, Wallet and Balance, each read for what it holds.

Venmo has a newer Statements page, set per account, where a month is two tabs
and only the open one is in the page. The Balance tab's transactions come from
a request of its own, BalanceAccountStatement, and the page writes accountTab
into the address. So a month saying it has no transactions on its Wallet tab
can hold them on its Balance tab, and calling that month empty would lose them
with no word said. A month must never pass for empty while one of its tabs
holds transactions.

The page below draws what Venmo's own page code draws, read from its public
files on 2026-11-03 and not seen on a live page. Four things in that code are
what these tests are for. The Wallet tab calls a month empty when it is not
loading and holds no rows, so its sentence is on the page before its request
has begun and after that request has failed. The Balance tab is offered only
once its answer is in and not null, and until then the page draws the Wallet
under an address naming Balance. The Balance tab's "Show more" does nothing,
so a month past its first ten cannot be drawn whole there. And the layout is
the server's yes or no, in the page's own data, and when it gives neither the
page can learn of its tabs after it has drawn, so a whole month can stand on
the older page first.

Every name, date and amount is invented. Nothing reaches Venmo. Every request
is answered here, and the browser can resolve no host at all, so one that
slipped past would fail rather than go out. No answer here is a redirect, since
Playwright hands only the first address of a redirect to its route and the next
one would go to the network.
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass
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
API_HOST = "api.venmo.com"
NO_HOST_RESOLVES = "--host-resolver-rules=MAP * ~NOTFOUND"
TODAY = date(2026, 10, 13)
THIS_MONTH = "2026-10"
FAKE_PROFILE_ID = "4455667788990011"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
PAGE_SIZE = 10

# How the page's request for a part of the month ends, when not with its rows.
FAILED = "failed"     # a 200 whose answer carries errors
BROKEN = "broken"     # a 500, whose body is not read
NO_ACCOUNT = "none"   # the Balance answer is null, the profile has no Balance account

WHAT_THE_PAGE_DOES = r"""
const params = new URLSearchParams(location.search);
const TABS = ['venmo-account', 'venmo-balance'];
const asked = params.get('accountTab');
let open = TABS.includes(asked) && !SITE.dropsTheTab ? asked : 'venmo-account';
let pending, completed, loadingHistory = false, balance, loadingBalance = false;
let tabsOn = !SITE.layoutAfter;
const sleep = ms => new Promise(done => setTimeout(done, ms));

async function ask(operationName, after) {
  const answer = await fetch('https://api.venmo.com/graphql', {
    method: 'POST', credentials: 'omit', headers: {'content-type': 'text/plain'},
    body: JSON.stringify({operationName, variables: {input: {year: params.get('year'),
                          month: params.get('month'), after: after || null}}})});
  if (!answer.ok) throw new Error('not ok');
  const body = await answer.json();
  if (body.errors) throw new Error('errors');
  return body.data;
}

function rows(items, what) {
  const drawn = ((items && items.edges) || []).map(edge =>
    '<a class="transactionListItem_transactionItem__Aq604" role="group" href="/statement/detail/1" ' +
    'data-testid="transaction-list-item-link"><span>' + what + '</span>' +
    '<span data-testid="money">-$1.00</span><div class="transactionListItem_divider__h6v5Y"></div></a>');
  const pager = items && items.pageInfo && items.pageInfo.hasNextPage
    ? '<div class="transactionListItem_showMoreButton__CmFVS"><button type="button" data-more="' + what +
      '">Show more</button></div>' : '';
  return drawn.join('') + pager;
}

function section(title, cls, items, loading, what) {
  const inside = loading ? '<div data-testid="feed-placeholder"><div data-testid="shimmer"></div></div>'
                         : rows(items, what);
  return '<div class="transactionListItem_sectionContainer__kwRv5"><b>' + title + '</b><div class="' + cls + '">' +
         inside + '</div></div>';
}

const PENDING = 'transactionListItem_pendingTransactionList__HLD2p';
const COMPLETED = 'transactionListItem_completedTransactionList__nfpG1';
const ACTIONS = '<div><button>Download CSV</button><button>Send to email</button></div>';
const emptyState = which => '<div data-testid="account-restructuring-empty-state-' + which + '">' +
  '<div class="emptyTxn_noTrans__D6goP"><p class="emptyTxn_selectMonth__F4j_m">' + MONTH_NAME + '</p>' +
  '<p>No transactions yet for this month, but as soon as they start rolling in, we’ll list them here.</p></div></div>';

function walletBody() {
  const a = loadingHistory;
  const u = ((pending && pending.edges && pending.edges.length) || 0) > 0;
  const p = ((completed && completed.edges && completed.edges.length) || 0) > 0;
  const g = !a && !u && !p;
  return '<section data-testid="venmo-account-tab-body">' + ACTIONS + (g ? emptyState('va') : '') +
    (a || u ? section('Pending transactions', PENDING, pending, a, 'WALLETPENDING') : '') +
    (a || p ? section('Completed transactions', COMPLETED, completed, a, 'WALLETROW') : '') + '</section>';
}

function balanceBody() {
  const t = loadingBalance;
  const T = balance && balance.pendingTransaction, x = balance && balance.completedTransaction;
  const f = ((T && T.edges && T.edges.length) || 0) > 0;
  const A = ((x && x.edges && x.edges.length) || 0) > 0;
  const j = !t && !f && !A;
  return '<section data-testid="venmo-balance-account-tab-body"><div>Balance Beginning balance Ending balance</div>' +
    ACTIONS + (j ? emptyState('vba') : '') +
    (t || f ? section('Pending transactions', PENDING, T, t, 'BALANCEPENDING') : '') +
    (t || A ? section('Completed transactions', COMPLETED, x, t, 'BALANCEROW') : '') +
    (loadingHistory ? '<div data-testid="account-restructuring-crypto-summary"><div data-testid="shimmer"></div></div>' : '') +
    '</section>';
}

// The page before it knows of its tabs. It draws no words until its answer
// is in, and no tabs, no address key and no Balance request.
function olderBody() {
  const none = !loadingHistory && pending && completed && !pending.edges.length && !completed.edges.length;
  return (loadingHistory ? '<div data-testid="shimmer"></div>' : '') +
    (none ? '<p>No transactions yet for this month, but as soon as they start rolling in, we\u2019ll list them here.</p>' : '') +
    (pending && pending.edges.length ? section('Pending transactions', PENDING, pending, false, 'WALLETPENDING') : '') +
    (completed && completed.edges.length ? section('Completed transactions', COMPLETED, completed, false, 'WALLETROW') : '');
}

function render() {
  if (!tabsOn) { document.getElementById('statement').innerHTML = olderBody(); return; }
  const k = !!balance;
  const G = k || open !== 'venmo-balance' ? open : 'venmo-account';
  document.getElementById('statement').innerHTML =
    '<div data-testid="account-statement-layout"><div data-testid="account-restructuring-tab-selector">' +
    '<div role="tab">Wallet</div>' + (k ? '<div role="tab">Balance</div>' : '') + '</div><div>' +
    (G === 'venmo-balance' ? balanceBody() : walletBody()) + '</div>' +
    '<p>Recent transactions could take up to 30 minutes to update your statement.</p></div>';
}

async function statementHistory() {
  loadingHistory = true; render();
  await sleep(SITE.historyAfter);
  try {
    const t = (await ask('TransactionsHistory')).transactionsHistory;
    pending = t.pendingTransaction; completed = t.completedTransaction;
  } catch (e) { /* the page's notice goes away by itself, and nothing else is drawn */ }
  loadingHistory = false; render();
}

async function balanceStatement() {
  loadingBalance = true; render();
  await sleep(SITE.balanceAfter);
  try {
    balance = (await ask('BalanceAccountStatement')).balanceAccountStatement ?? null;
  } catch (e) { balance = null; }
  loadingBalance = false; render();
}

document.addEventListener('click', async event => {
  const button = event.target.closest && event.target.closest('[data-more]');
  if (!button || button.dataset.more !== 'WALLETROW') return;  // The Balance tab's handler is empty.
  const more = (await ask('TransactionsHistory', completed.pageInfo.endCursor)).transactionsHistory.completedTransaction;
  completed = {edges: completed.edges.concat(more.edges), pageInfo: more.pageInfo};
  render();
});

function tabsMount() {
  params.set('accountTab', open);
  window.history.replaceState(null, '', location.pathname + '?' + params.toString());
  balanceStatement();
  // The left menu's own question, about this month and not the one shown.
  ask('BalanceAccountProvisioned').catch(() => {});
}

render();
setTimeout(() => {
  statementHistory();
  if (tabsOn) tabsMount();
  else setTimeout(() => { tabsOn = true; render(); tabsMount(); }, SITE.layoutAfter);
}, SITE.hydrateAfter);
"""


def statement_url(month=10, year=2026, tab=""):
    url = (f"https://{HOST}/statement?accountType=personal&month={month}"
           f"&profileId={FAKE_PROFILE_ID}&year={year}")
    return url + (f"&accountTab={tab}" if tab else "")


@dataclass
class Part:
    """What a request holds for one tab of one month."""
    rows: int = 0
    pending: int = 0


def transactions(count, what, after=None):
    """One page of `count` transactions, as the page's query asks for them."""
    start = int(after or 0)
    edges = [{"node": {"title": what}} for _ in range(start, min(count, start + PAGE_SIZE))]
    more = start + PAGE_SIZE < count
    return {"edges": edges, "pageInfo": {"hasNextPage": more, "endCursor": str(start + PAGE_SIZE)}}


class Venmo:
    """The made-up site. `wallet` and `balance` say what a month's two
    requests hold, and a month not named holds three Wallet rows and nothing
    on Balance."""

    def __init__(self):
        self.wallet, self.balance = {}, {}
        self.site = {"historyAfter": 10, "balanceAfter": 10, "hydrateAfter": 5, "dropsTheTab": False}
        # How long a month's page draws as the older page before its tabs,
        # and what the server says of tabs. A month drawn at once has its
        # yes, and a late one nothing, unless `told` names it.
        self.layout_after, self.told = {}, {}
        self.asked = []

    def graphql(self, route):
        ask = json.loads(route.request.post_data)
        op, given = ask["operationName"], ask["variables"]["input"]
        month = "%s-%02d" % (given["year"], int(given["month"]))
        self.asked.append((op, month))
        if op == "BalanceAccountProvisioned":
            held = self.balance.get(THIS_MONTH, Part())
            body = {"data": {"balanceAccountStatement": None if held == NO_ACCOUNT else {"startBalance": {"value": 0}}}}
            route.fulfill(status=200, headers={"access-control-allow-origin": f"https://{HOST}"},
                          content_type="application/json", body=json.dumps(body))
            return
        field, held = (("transactionsHistory", self.wallet.get(month, Part(3)))
                       if op == "TransactionsHistory"
                       else ("balanceAccountStatement", self.balance.get(month, Part())))
        cors = {"access-control-allow-origin": f"https://{HOST}"}
        if held == BROKEN:
            route.fulfill(status=500, headers=cors, content_type="application/json", body="{}")
            return
        if held == FAILED:
            body = {"errors": [{"message": "An invented failure"}], "data": None}
        elif held == NO_ACCOUNT:
            body = {"data": {field: None}}
        else:
            name = "WALLETROW" if op == "TransactionsHistory" else "BALANCEROW"
            body = {"data": {field: {"pendingTransaction": transactions(held.pending, name + "P"),
                                     "completedTransaction": transactions(held.rows, name, given["after"])}}}
        route.fulfill(status=200, headers=cors, content_type="application/json", body=json.dumps(body))

    def answer(self, route):
        parts = urlsplit(route.request.url)
        if parts.hostname == API_HOST and parts.path == "/graphql":
            self.graphql(route)
            return
        if parts.hostname != HOST:
            route.abort()
            return
        # The plain address settles on this month's own, in the page, with
        # the layout's tab already named.
        plain = parts.path == "/statement" and not parts.query
        settles = "history.replaceState(null, '', %s);" % json.dumps(statement_url(tab=site.WALLET_TAB))
        q = parse_qs(urlsplit(statement_url()).query if plain else parts.query)
        name = f"{MONTH_NAMES[int(q['month'][0]) - 1]} {q['year'][0]}"
        month = "%s-%02d" % (q["year"][0], int(q["month"][0]))
        drawn = dict(self.site, layoutAfter=self.layout_after.get(month, 0))
        told = self.told.get(month, None if drawn["layoutAfter"] else True)
        props = "" if told == "no data" else json.dumps(
            {"props": {"pageProps": {} if told == "not given" else {"isAccountRestructuringEnabledSSR": told}}})
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Venmo | Account Statement</title></head>
<body><nav><a href="/account/logout">Log out</a></nav>
<main><h1>Account Statement</h1><input type="text" value="{name}"><div id="statement"></div></main>
<script>{settles if plain else ""} {"window.__NEXT_DATA__ = " + props + ";" if props else ""}
const SITE = {json.dumps(drawn)}; const MONTH_NAME = {json.dumps(name)};
{WHAT_THE_PAGE_DOES}</script></body></html>""")


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
    monkeypatch.setattr(site, "EMPTY_HOLD_MS", 200)
    monkeypatch.setattr(site, "SETTLE_MS", 1500)
    monkeypatch.setattr(site, "LAYOUT_HOLD_MS", 800)
    context = chromium.new_context()
    context.route("**/*", venmo.answer)
    tab = context.new_page()
    yield tab
    context.close()


def months_read(page, walk=2):
    return [d.document_id for d in site.collect_download_docs(page, today=TODAY, limit=walk)]


def stop_of(page, walk=2):
    with pytest.raises(site.ListStopped) as stop:
        site.collect_download_docs(page, today=TODAY, limit=walk)
    return stop.value


# The list, tab by tab.

def test_each_tab_that_holds_transactions_is_a_statement_of_its_own(page, venmo):
    venmo.balance["2026-09"] = Part(2)
    assert months_read(page) == ["2026-09", "2026-09-balance", "2026-08"]


def test_a_wallet_with_no_transactions_is_not_an_empty_month_while_the_balance_holds_them(page, venmo):
    """The trap. Allowing accountTab alone would skip this month and say
    nothing."""
    venmo.wallet["2026-09"] = Part()
    venmo.balance["2026-09"] = Part(2)
    assert months_read(page) == ["2026-09-balance", "2026-08"]


def test_pending_transactions_on_the_balance_alone_stop_the_month(page, venmo):
    venmo.wallet["2026-09"] = Part()
    venmo.balance["2026-09"] = Part(0, pending=1)
    stop = stop_of(page)
    assert stop.month == "2026-09"
    assert str(stop) == "the month shows pending transactions and no completed ones"


def test_a_month_with_nothing_on_either_tab_is_the_only_empty_month(page, venmo):
    venmo.wallet["2026-09"] = Part()
    assert months_read(page) == ["2026-08"]


def test_a_month_held_empty_on_both_tabs_has_been_read_on_both(page, venmo):
    venmo.wallet.update({"2026-09": Part(), "2026-08": Part()})
    assert months_read(page) == []
    assert ("BalanceAccountStatement", "2026-08") in venmo.asked


def test_the_oldest_month_read_counts_when_only_its_balance_holds_transactions(page, venmo, monkeypatch):
    """A walk of two years calls the list whole only when its oldest month
    holds nothing, and that month's id here is its Balance one."""
    monkeypatch.setattr(site, "MAX_MONTHS", 2)
    venmo.wallet["2026-08"] = Part()
    venmo.balance["2026-08"] = Part(1)
    with pytest.raises(site.CapReached) as stop:
        site.collect_download_docs(page, today=TODAY)
    assert [d.document_id for d in stop.value.docs] == ["2026-09", "2026-08-balance"]


# A profile with no Balance account, which has the Wallet tab alone.

def test_no_balance_account_leaves_the_wallet_as_the_whole_month(page, venmo):
    venmo.balance.update({"2026-09": NO_ACCOUNT, "2026-08": NO_ACCOUNT})
    assert months_read(page) == ["2026-09", "2026-08"]


def test_an_empty_wallet_and_no_balance_account_is_an_empty_month(page, venmo):
    venmo.wallet["2026-09"] = Part()
    venmo.balance.update({"2026-09": NO_ACCOUNT, "2026-08": NO_ACCOUNT})
    assert months_read(page) == ["2026-08"]


def test_the_left_menu_s_answer_about_this_month_is_not_the_month_read(page, venmo):
    """The same field by another name, asked by the menu for the month under
    way. It says nothing of the month open, and it comes first here, as an
    app that took it for the month's own answer would need."""
    venmo.site["balanceAfter"] = 300
    venmo.balance.update({THIS_MONTH: NO_ACCOUNT, "2026-09": Part(2)})
    assert months_read(page, 1) == ["2026-09", "2026-09-balance"]


# A page that learns of its tabs after it has drawn a month.

def test_tabs_that_draw_after_the_month_has_settled_are_read(page, venmo):
    """Rows stand on the older page long enough to pass, and the Balance tab
    would go unread with nothing said."""
    venmo.layout_after.update({"2026-09": 400, "2026-08": 400})
    venmo.balance.update({"2026-09": Part(2), "2026-08": Part(1)})
    assert months_read(page) == ["2026-09", "2026-09-balance", "2026-08", "2026-08-balance"]


def test_a_wallet_that_is_empty_before_its_tabs_draw_is_not_an_empty_month(page, venmo):
    venmo.layout_after["2026-09"] = 500
    venmo.wallet["2026-09"] = Part()
    venmo.balance["2026-09"] = Part(2)
    assert months_read(page, 1) == ["2026-09-balance"]


def test_once_a_list_has_met_tabs_every_month_has_its_balance_read(page, venmo):
    """The second month stands on the older page, saying it is empty, for
    longer than its words are held, so nothing on it says tabs are coming."""
    venmo.layout_after["2026-08"] = 500
    venmo.wallet["2026-08"] = Part()
    venmo.balance["2026-08"] = Part(2)
    assert months_read(page) == ["2026-09", "2026-08-balance"]


def test_tabs_first_seen_after_months_read_without_them_stop_the_list(page, venmo):
    """The first month gave up on them, so its Balance tab was never read."""
    venmo.layout_after["2026-09"] = 60000
    stop = stop_of(page)
    assert stop.month == "2026-08"
    assert str(stop) == "the page drew statement tabs only after months read without them"
    assert [d.document_id for d in stop.docs] == ["2026-09", "2026-08"]


def test_a_first_month_that_gave_up_on_its_tabs_is_caught_by_a_later_month(page, venmo):
    """A setting that failed on one load, and came in time on the next but
    only after that month had settled, so one wait on the first month would
    read every month as a page with none."""
    venmo.layout_after.update({"2026-09": 60000, "2026-08": 400})
    stop = stop_of(page)
    assert stop.month == "2026-08"
    assert str(stop) == "the page drew statement tabs only after months read without them"


@pytest.mark.parametrize("said", [None, False])
def test_an_account_whose_page_never_draws_tabs_is_read_as_the_older_page(page, venmo, said):
    venmo.layout_after.update({THIS_MONTH: 60000, "2026-09": 60000, "2026-08": 60000})
    venmo.told.update({THIS_MONTH: said, "2026-09": said, "2026-08": said})
    assert months_read(page) == ["2026-09", "2026-08"]
    assert not [op for op, _ in venmo.asked if op != "TransactionsHistory"]


@pytest.mark.parametrize("data, told", [(True, True), (False, False), (None, None), ("not given", None),
                                        ("no data", None)])
def test_the_server_s_word_is_read_from_the_page_s_own_data(page, venmo, data, told):
    venmo.told["2026-09"] = data
    page.goto(statement_url(9, 2026))
    assert site._state(page)["told"] is told


def test_a_server_that_says_tabs_is_not_answered_by_a_page_with_none(page, venmo):
    venmo.layout_after["2026-09"] = 60000
    venmo.told["2026-09"] = True
    assert str(stop_of(page)) == "the server says the statement has tabs and the page draws none"


# What the Wallet's sentence does not prove.

def test_a_wallet_whose_request_failed_says_it_is_empty_and_is_not(page, venmo):
    venmo.wallet["2026-09"] = FAILED
    stop = stop_of(page)
    assert stop.docs == [] and stop.month == "2026-09"
    assert str(stop) == "the Wallet tab says the month has no transactions and Venmo's own answer does not"
    assert stop.seen["empty"] is True and stop.seen["answer"]["errors"] is True


def test_a_wallet_whose_answer_could_not_be_read_is_not_an_empty_month(page, venmo):
    venmo.wallet["2026-09"] = BROKEN
    stop = stop_of(page)
    assert str(stop) == ("the Wallet tab says the month has no transactions and "
                         "Venmo's own answer could not be read")
    assert stop.seen["status"] == 500


def test_the_wallet_s_sentence_before_its_request_is_not_believed(page, venmo):
    """Drawn from the first paint, and held longer than EMPTY_HOLD_MS before
    the page has asked for anything."""
    venmo.site["hydrateAfter"] = 450
    assert months_read(page, 1) == ["2026-09"]


# The Balance tab, which is drawn only once its answer is in.

def test_a_balance_answer_that_comes_late_is_waited_for(page, venmo):
    venmo.site["balanceAfter"] = 400
    venmo.balance["2026-09"] = Part(2)
    assert months_read(page, 1) == ["2026-09", "2026-09-balance"]


@pytest.mark.parametrize("how", [FAILED, BROKEN])
def test_a_balance_request_that_failed_stops_the_month_and_keeps_its_wallet(page, venmo, how):
    """The page draws the Wallet under the Balance address, rows and all, and
    looks the same as a profile with no Balance account."""
    venmo.balance["2026-09"] = how
    stop = stop_of(page)
    assert [d.document_id for d in stop.docs] == ["2026-09"]
    assert stop.month == "2026-09"
    assert str(stop) == "the page has not drawn the statement tab its address names"
    assert (stop.seen["wallet"], stop.seen["balance"], stop.seen["balance_asked"]) == (1, 0, True)


def test_a_pending_list_past_its_first_ten_stops_the_month(page, venmo):
    venmo.balance["2026-09"] = Part(2, pending=11)
    assert str(stop_of(page)) == "the statement's own answer says more transactions are to come"


def test_a_page_that_will_not_keep_the_balance_address_stops(page, venmo):
    """Venmo's server is not public, so a visit naming the tab may not last."""
    venmo.site["dropsTheTab"] = True
    assert str(stop_of(page)) == "the Statements page did not stay on the month asked for"


# Printing, one tab to a file.

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
        app = make_app(*args, "--start-date", "2026-08-01")
        app.page = lambda: page
        app._on_its_site = lambda: page
        app.check_session = lambda p: None
        app._delay = lambda *a, **k: None
        return app
    return made


def read_pdf(path):
    pypdf = pytest.importorskip("pypdf")
    return "".join(p.extract_text() for p in pypdf.PdfReader(str(path)).pages)


def saved_by_id(app):
    return {r["document_id"]: r for r in app.progress.data.values()}


def test_discover_lists_both_and_calls_the_list_whole(app_on, venmo):
    venmo.balance["2026-09"] = Part(2)
    app = app_on("--discover")
    with redirect_stdout(io.StringIO()) as said:
        app.cmd_discover()
    assert "stopped partway" not in said.getvalue()
    found = {r["document_id"]: r["title"] for r in app.discovery.data.values()}
    assert found == {"2026-09": "Venmo Statement 2026-09", "2026-09-balance": "Venmo Balance Statement 2026-09",
                     "2026-08": "Venmo Statement 2026-08"}
    assert listing.last(app) != listing.STOPPED


def test_each_tab_prints_to_a_file_of_its_own_holding_that_tab(app_on, venmo):
    venmo.balance["2026-09"] = Part(2)
    app = app_on("--all", "--yes")
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    saved = saved_by_id(app)
    assert {k: r["state"] for k, r in saved.items()} == {k: State.COMPLETED.value for k in (
        "2026-09", "2026-09-balance", "2026-08")}
    wallet, balance = Path(saved["2026-09"]["pdf_path"]), Path(saved["2026-09-balance"]["pdf_path"])
    assert wallet.name == "2026-09-30 Venmo Statement.pdf"
    assert balance.name == "2026-09-30 Venmo Balance Statement.pdf"
    assert "WALLETROW" in read_pdf(wallet) and "BALANCEROW" not in read_pdf(wallet)
    assert "BALANCEROW" in read_pdf(balance) and "WALLETROW" not in read_pdf(balance)
    assert saved["2026-09-balance"]["rows_printed"] == 2


def test_a_balance_alone_month_saves_under_its_own_name(app_on, venmo):
    venmo.wallet["2026-09"] = Part()
    venmo.balance["2026-09"] = Part(1)
    app = app_on("--all", "--yes")
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert Path(saved_by_id(app)["2026-09-balance"]["pdf_path"]).name == "2026-09-30 Venmo Balance Statement.pdf"


def test_a_busy_wallet_is_drawn_whole_by_its_own_show_more(app_on, venmo):
    venmo.wallet["2026-09"] = Part(12)
    app = app_on("--all", "--yes")
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    saved = saved_by_id(app)["2026-09"]
    assert (saved["state"], saved["rows_printed"]) == (State.COMPLETED.value, 12)


def test_a_busy_wallet_says_nothing_about_the_balance(app_on, venmo):
    """The page asks for the Wallet on the Balance tab too. That answer says
    more is to come, of the Wallet's list and not this one."""
    venmo.wallet["2026-09"] = Part(12)
    venmo.balance["2026-09"] = Part(2)
    app = app_on("--all", "--yes")
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert saved_by_id(app)["2026-09-balance"]["state"] == State.COMPLETED.value


def test_a_balance_past_its_first_ten_is_never_printed_cut_short(app_on, venmo):
    """The Balance tab's Show more does nothing, so the month is not saved.
    It is a failure the next run tries again, not a month in review with no
    file (#152), and the Wallet's statement is taken as usual."""
    venmo.balance["2026-09"] = Part(11)
    app = app_on("--all", "--yes")
    with redirect_stdout(io.StringIO()):
        try:
            app.cmd_run("all")
        except SystemExit:
            pass
    saved = saved_by_id(app)
    assert saved["2026-09-balance"]["state"] == State.FAILED.value
    assert not saved["2026-09-balance"].get("pdf_path")
    assert saved["2026-09"]["state"] == State.COMPLETED.value
    assert "Balance" not in " ".join(p.name for p in app.paths.folder_for("Statement").glob("*.pdf"))


@pytest.mark.parametrize("how", [NO_ACCOUNT, FAILED])
def test_a_listed_balance_that_has_gone_is_not_printed_as_the_wallet(app_on, venmo, how):
    """Listed on Balance, and the Balance tab no longer offered, so the page
    draws the Wallet's rows under the Balance address."""
    venmo.balance["2026-09"] = Part(2)
    app = app_on("--discover")
    with redirect_stdout(io.StringIO()):
        app.cmd_discover()
    venmo.balance["2026-09"] = how
    record = app.discovery.get(next(k for k, r in app.discovery.data.items()
                                    if r["document_id"] == "2026-09-balance"))
    doc = docs.Document.from_dict(record)
    out = Path(tempfile.mkdtemp()) / "out.pdf"
    trace = []
    assert site.download_bill(app.page(), None, doc.date, out, href=doc.href, document_id=doc.document_id,
                              profile=doc.account, trace=trace, today=TODAY) is False
    assert not out.exists()


def test_a_stop_on_a_tab_writes_which_tab_and_nothing_of_the_profile(app_on, venmo):
    venmo.balance["2026-09"] = FAILED
    app = app_on("--discover")
    with redirect_stdout(io.StringIO()) as said, pytest.raises(SystemExit):
        app.cmd_discover()
    assert "stopped partway" in said.getvalue()
    assert "It stopped on 2026-09." in said.getvalue()
    assert listing.last(app) == listing.STOPPED
    text = next(app.paths.diagnostics.glob("failure-*.json")).read_text(encoding="utf-8")
    assert FAKE_PROFILE_ID not in text
    seen = json.loads(text)["extra"]["month_page"]
    assert (seen["tabs"], seen["wallet"], seen["balance"], seen["balance_asked"]) == (1, 1, 0, True)


# Sign-in checks and Diagnose on this page.

def test_the_session_check_reads_the_page(page, venmo, monkeypatch):
    monkeypatch.setattr(site, "_date", HeldDay)
    assert site.goto_documents(page) is True
    assert site.bill_list_opens(page) is True


def test_the_survey_says_the_page_has_tabs_and_what_the_server_said(page):
    report = site.survey(page, dwell_ms=150)
    assert report["pages"][0]["statement_tabs"] == {"tabbed": 1, "wallet": 1, "balance": 0,
                                                    "server_says_tabs": True}
