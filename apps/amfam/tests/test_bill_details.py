"""American Family's statements, each behind its bill's Bill details.

A tester's Diagnose on 0.43.0 found Billing & Payments, headed "My bills",
with an Edit autopay and a Bill details button for each of two bills, then
Manage AutoPay, Payment methods and Link account, and no statementPDF link
at all. His recording of opening a statement began on a list of them under
a routed view's heading, a section holding a form and rows marked with
data-cy, after whatever opened that list. The app never pressed Bill
details, so a Pilot found nothing and saved nothing.

Every page here is invented, the accounts, policies, dates and PDFs too,
and nothing leaves this machine. Each control on a page tells a stand-in
server when it is pressed, so a press is seen even after the app has
loaded the page again, and a key that reaches the form above a list is
told too. A bill's Bill details opens its list in place, at a route of its
own, seconds after the press, or in two passes, and the pages from the
reviews of the change go wrong the ways a site could, another bill's
details or PDF behind a press, a page that moves on by itself or redraws
just as something is pressed, a press that opens a tab. Each is tied to a
step of the app's own, never a clock. Run through the app's own discovery
and download loop, in a real browser, since a blob and its tab are the
browser's doing."""
import base64
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import amfam_site as site  # noqa: E402
from paperpull_core import testkit  # noqa: E402
from paperpull_core.models import State  # noqa: E402

BASE = "https://myaccount.amfam.com"

# The invented bills. Each card shows a billing account number, C's ends in
# the same four digits as A's, N's card shows none, and X's card is drawn
# only as another bill is pressed.
CARDS = {
    "A": ("Auto", "9900123401"),
    "B": ("Home", "9900567802"),
    "C": ("Umbrella", "9911113401"),
    "D": ("Renters", "9900888804"),
    "N": ("Boat", ""),
    "X": ("Pet", "9900777705"),
}
# Both A and B have a statement dated 09/12/2026.
DATES = {
    "A": ["09/12/2026", "08/12/2026"],
    "B": ["09/12/2026", "08/28/2026"],
    "C": ["09/20/2026"],
    "D": ["09/05/2026"],
    "N": ["09/18/2026"],
    "X": ["09/01/2026"],
}
POLICY = {"A": "ZA-0001-2345-01", "B": "ZH-0006-7890-02", "C": "ZU-0004-4444-03",
          "D": "ZR-0008-1212-04", "N": "ZB-0005-3434-05", "X": "ZP-0007-5656-06"}
ROUTE = {"A": "x7k2", "B": "m4q9", "C": "t2v8", "D": "p3w6", "N": "r5n1", "X": "h8c4"}
AUTOPAY_LINE = "Next AutoPay 10/01/2026 from account ending in 6789"


def iso(date: str) -> str:
    m, d, y = date.split("/")
    return "%s-%s-%s" % (y, m, d)


def pdf(bill: str, date: str) -> bytes:
    """An invented statement, which prints its own policy and period."""
    return testkit.text_pdf(["Invented insurer statement",
                             "Policy %s" % POLICY[bill],
                             "Statement period ending %s" % date])


def other_pdf(date: str) -> bytes:
    """An invented document that is no bill's own."""
    return testkit.text_pdf(["Invented insurer notice", "Not a statement of any bill", date])


def part_of(bill: str) -> str:
    """The account part a bill is told by, its account's last four, or its
    policy's when its card shows no account number."""
    return "..." + (CARDS[bill][1] or POLICY[bill].replace("-", ""))[-4:]


def name_of(bill: str, date: str) -> str:
    """The file a statement is saved as, its bill's account part in its name."""
    return "%s American Family Billing Statement %s.pdf" % (iso(date), part_of(bill))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def details_button(bill: str) -> str:
    return ("<button data-cy='billDetails' id='details-%s' onclick=\"details('%s')\">Bill details</button>"
            % (bill, bill))


def card(bill: str, control: str = None, policy: bool = False, lines=()) -> str:
    """A bill's card on Billing & Payments. `control` is its Bill details,
    and an empty one draws a card with none, a bill paid in full. With
    `policy` the card shows its policy number below its account number, and
    `lines` are drawn below that."""
    heading, account = CARDS[bill]
    number = "<p><span>Billing account</span> <span>%s</span></p>" % account if account else ""
    if policy:
        number += "<p><span>%s policy</span> <span>%s</span></p>" % (heading, POLICY[bill])
    number += "".join("<p>%s</p>" % line for line in lines)
    if control == "":
        return ("<div class='bill-card' data-cy='billCard'><h2>%s</h2>%s"
                "<p><span>Paid in full</span></p></div>" % (heading, number))
    return ("<div class='bill-card' data-cy='billCard'><h2>%s</h2>%s"
            "<p><span>Amount due</span> <span>$123.45</span></p>"
            "<p><span>Due date</span> <span>10/01/2026</span></p>"
            "<button data-cy='editAutopay' onclick=\"flag('edit-autopay-%s')\">Edit autopay</button>"
            "%s</div>" % (heading, number, bill, details_button(bill) if control is None else control))


# How the invented site draws a bill's statements, the shape of the
# tester's recording. A section with a text header first, a form of one
# child above the rows, which takes the focus as a list is drawn, rows
# marked with data-cy, and in each a link with no address marked
# statementPDF that opens a tab at a blob of the PDF.
SCRIPT = r"""
const PDFS = __PDFS__;
const OTHER = __OTHER__;
const DATES = __DATES__;
const WAYS = __WAYS__;
const ROUTE = __ROUTE__;
const ACCOUNT = __ACCOUNT__;
const MORE = __MORE__;
const CARD = __CARD__;
const DRAWN = __DRAWN__;
const ALTERNATE = __ALTERNATE__;
const VANISH = __VANISH__;
const TALL = "<div class='spacer' style='height:3000px'></div>";
const LOAD = Number(sessionStorage.getItem('loads') || 0) + 1;
sessionStorage.setItem('loads', String(LOAD));
function flag(name) { fetch('/flag/' + name); }
function openPdf(data) {
  const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  window.open(url, '_blank');
  URL.revokeObjectURL(url);
}
function openStatement(bill, date) {
  flag('statement-' + bill + '-' + date.split('/').join('-'));
  openPdf(PDFS[bill + '|' + date]);
}
function link(onclick) {
  return "<a class='link' data-cy='statementPDF' title='View statement' onclick=\"" + onclick + "\">" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div>" +
    "<span class='label'>PDF</span>" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div></a>";
}
function row(onclick, d) {
  return "<div class='statement-row' data-cy='statementRow'><div class='cols'>" +
    "<div class='pdf-col'>" + link(onclick) + "</div>" +
    "<div class='date-col'><span>" + d + "</span></div></div></div>";
}
function rows(bill, upto) {
  return DATES[bill].slice(0, upto || DATES[bill].length).map(
    (d) => row("openStatement('" + bill + "','" + d + "')", d)).join('');
}
function otherRow(d) { return row("flag('other-statement'); openPdf(OTHER['" + d + "'])", d); }
function list(bill, upto, more) {
  return "<div class='statements' id='statements-" + bill + "'>" +
    "<div class='statements-header'>Billing statements</div>" +
    "<div class='statements-body'><div class='statements-note'><span>Your recent statements</span></div>" +
    "<div class='statements-list'><app-statement-list><div class='list'>" +
    "<form class='statement-filter' onsubmit=\"flag('form-submit'); return false;\">" +
    "<select onchange=\"flag('form-change')\" onkeydown=\"flag('form-key')\">" +
    "<option>Last 12 months</option><option>Last 24 months</option></select></form>" +
    "<div class='rows'>" + rows(bill, upto) + "</div>" + (more || MORE[bill] || '') +
    "<div class='list-end'><span>End of list</span></div><div class='list-foot'></div>" +
    "</div></app-statement-list></div></div></div>";
}
function focusFilter() {
  const s = document.querySelector('.statement-filter select');
  if (s) s.focus();
}
function view(heading, account, bill, upto, more, extra) {
  const summary = account ?
    "<div class='bill-summary'><span>Billing account " + ACCOUNT[account] + "</span></div>" : '';
  document.querySelector('.page').innerHTML =
    '<h1>' + heading + '</h1>' + summary + list(bill, upto, more) + (extra || '');
  focusFilter();
}
function place(bill, upto) {
  document.getElementById('details').innerHTML = list(bill, upto);
  focusFilter();
}
function older(button, bill) {
  button.remove();
  setTimeout(() => { document.querySelector('#statements-' + bill + ' .rows').innerHTML = rows(bill); }, 300);
}
function count(name) {
  const n = Number(sessionStorage.getItem(name) || 0) + 1;
  sessionStorage.setItem(name, String(n));
  return n;
}
function onSet(prop, when, act) {
  let value, done = false;
  Object.defineProperty(window, prop, {configurable: true,
    get() { return value; },
    set(v) { value = v; if (!done && when()) { done = true; act(); } }});
}
function onGet(prop, act) {
  let value = window[prop], done = false;
  Object.defineProperty(window, prop, {configurable: true,
    get() { if (!done) { done = true; act(); } return value; },
    set(v) { value = v; }});
}
function details(bill) {
  flag('bill-details-' + bill);
  const way = WAYS[bill];
  const own = (tail) => history.pushState({}, '', '/billing/bill-details/' + ROUTE[bill] + (tail || ''));
  const autopay = () => history.pushState({}, '', '/billing/autopay');
  const another = () => document.querySelector('.page').insertAdjacentHTML(
    'beforeend', "<p>Billing account " + ACCOUNT['B'] + "</p>");
  if (way === 'place') {
    place(bill);
  } else if (way === 'place-late') {
    setTimeout(() => place(bill), 3000);
  } else if (way === 'place-twice') {
    place(bill, 1);
    setTimeout(() => place(bill), 300);
  } else if (way === 'route') {
    own();
    view('Bill details', bill, bill);
  } else if (way === 'route-more') {
    own();
    view('Bill details', bill, bill, 1, "<button onclick=\"older(this, '" + bill + "')\">Show more</button>");
  } else if (way === 'late') {
    own();
    document.querySelector('.page').innerHTML = '<h1>Bill details</h1><p>Loading</p>';
    setTimeout(() => view('Bill details', bill, bill), 3000);
  } else if (way === 'autopay') {
    autopay();
    view('Autopay', bill, bill);
  } else if (way === 'query-autopay') {
    own('?next=autopay');
    view('Bill details', bill, bill);
  } else if (way === 'fragment-autopay') {
    own('#/autopay/setup');
    view('Bill details', bill, bill);
  } else if (way === 'shows-A') {
    own();
    view('Bill details', 'A', 'A');
  } else if (way === 'same-as-A') {
    own();
    view('Bill details', null, 'A');
  } else if (way === 'new-tab') {
    window.open('about:blank', '_blank');
    place(bill);
  } else if (way === 'beside') {
    document.querySelector('.bills').insertAdjacentHTML('beforeend', rows(bill));
  } else if (way === 'nothing') {
    // A press that shows nothing at all.
  } else if (way === 'never-still') {
    place(bill);
    let n = 0;
    setInterval(() => {
      n += 1;
      document.querySelector('#statements-' + bill + ' .rows').insertAdjacentHTML('beforeend', otherRow('07/0' + (n % 9 + 1) + '/2026'));
    }, 400);
  } else if (way === 'moves-on-scroll') {
    // The tab moves to /billing/autopay as soon as the view is scrolled.
    own();
    view('Bill details', bill, bill, 0, '', TALL);
    window.addEventListener('scroll', autopay, {once: true});
  } else if (way === 'names-another-on-scroll') {
    // Another bill's account is drawn in the view as soon as it is scrolled.
    own();
    view('Bill details', bill, bill, 0, '', TALL);
    window.addEventListener('scroll', another, {once: true});
  } else if (way === 'moves-when-read') {
    // The tab moves to /billing/autopay the first time the app reads what
    // the press brought.
    own();
    view('Bill details', bill, bill);
    onGet('__paperpullPressed', autopay);
  } else if (way === 'moves-at-download' || way === 'names-another-at-download') {
    // From the bill's second press on, the first time the app reads which
    // tabs the press opened, once the press is done.
    own();
    view('Bill details', bill, bill);
    if (count('presses-' + bill) >= 2) onGet('__paperpullTabs', way === 'moves-at-download' ? autopay : another);
  }
}
(function () {
  let order = DRAWN.slice();
  if (ALTERNATE && LOAD % 2 === 0) order.reverse();
  order = order.filter((b) => !(VANISH.includes(b) && LOAD > 1));
  document.querySelector('.bills').insertAdjacentHTML('beforeend', order.map((b) => CARD[b]).join(''));
  __HOOKS__
})();
"""


def billing_page(ways: dict, controls: dict = None, before: str = "", paid: str = "",
                 more: dict = None, wrong: dict = None, at_mark: str = "", at_arm: str = "",
                 policies: tuple = (), lines: dict = None, drawn: tuple = None,
                 alternate: bool = False, vanish: tuple = ()) -> str:
    """Billing & Payments the way the tester's Diagnose saw it, one card for
    each bill in `ways`, saying how its Bill details opens its statements.

    `controls` replaces a bill's Bill details, `before` is drawn above the
    bills and `paid` first among them. `more` adds a control to a bill's
    list and `wrong` sends a bill's link to another bill's PDF. `at_mark`
    is done as the app keeps a note of what shows before a Bill details
    press, and `at_arm` as it arms its catch of a statement while a list
    shows. The cards of the bills in `policies` show a policy number too,
    `lines` adds lines to a card, `drawn` is which bills are drawn as the
    page loads, `alternate` reverses their order on every other load, and
    the bills in `vanish` are drawn on the first load only."""
    controls, lines = controls or {}, lines or {}
    dated = dict(DATES)
    pdfs = {"%s|%s" % (b, d): b64(pdf(b, d)) for b in CARDS for d in dated[b]}
    for link, (bill, date) in (wrong or {}).items():
        pdfs[link] = b64(pdf(bill, date))
    others = {d: b64(other_pdf(d)) for d in ["07/0%d/2026" % n for n in range(1, 10)] + ["07/12/2026"]}
    cards = {b: card(b, controls.get(b), b in policies, lines.get(b, ())) for b in CARDS}
    hooks = ""
    if at_mark:
        hooks += "onSet('__paperpullShownBefore', () => true, () => { %s });" % at_mark
    if at_arm:
        hooks += ("onSet('__paperpullBlobs', () => !!document.querySelector('.statements .rows .statement-row'),"
                  " () => { %s });" % at_arm)
    script = (SCRIPT.replace("__PDFS__", json.dumps(pdfs))
              .replace("__OTHER__", json.dumps(others))
              .replace("__DATES__", json.dumps(dated))
              .replace("__WAYS__", json.dumps(ways))
              .replace("__ROUTE__", json.dumps(ROUTE))
              .replace("__ACCOUNT__", json.dumps({b: CARDS[b][1] for b in CARDS}))
              .replace("__MORE__", json.dumps(more or {}))
              .replace("__CARD__", json.dumps(cards))
              .replace("__DRAWN__", json.dumps(list(drawn if drawn is not None else ways)))
              .replace("__ALTERNATE__", json.dumps(alternate))
              .replace("__VANISH__", json.dumps(list(vanish)))
              .replace("__HOOKS__", hooks))
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Billing &amp; Payments</title></head>"
            "<body><div role='main' id='main'><app-billing class='routed'><div class='page'>"
            "<h1>My bills</h1>%s<div class='bills'>%s</div>"
            "<div class='bill-actions'>"
            "<button data-cy='manageAutopay' onclick=\"flag('manage-autopay')\">Manage AutoPay</button>"
            "<button data-cy='paymentMethods' onclick=\"flag('payment-methods')\">Payment methods</button>"
            "<button data-cy='linkAccount' onclick=\"flag('link-account')\">Link account</button>"
            "</div><div id='details'></div></div></app-billing></div>"
            "<script>%s</script></body></html>" % (before, paid, script))


@dataclass
class Site:
    page: object
    pressed: list
    settle: object


@pytest.fixture()
def billing_site():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)

    def start(html: str) -> Site:
        # His Chrome shows a statement in the tab it opens and downloads
        # nothing, so downloads are refused here, as in test_billing_blob.py.
        ctx = browser.new_context(accept_downloads=False)
        pressed: list = []
        ctx.route("**/*", lambda r: r.abort())
        ctx.route("%s/billing" % BASE, lambda r: r.fulfill(
            status=200, content_type="text/html", body=html))
        # The stand-in server, told of every press, whatever the page is
        # showing by then.
        ctx.route("%s/flag/*" % BASE, lambda r: pressed.append(
            urlsplit(r.request.url).path.rsplit("/", 1)[-1]) or r.fulfill(status=204, body=""))
        pg = ctx.new_page()
        pg.goto("%s/billing" % BASE)
        # The app's waits, a tenth as long. A bill's statements are waited
        # for by the clock, so a list that comes seconds late still comes.
        wait = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
        return Site(page=pg, pressed=pressed, settle=wait)

    yield start
    browser.close()
    driver.stop()


def app_on(page, tmp_path):
    """The app built by its own parser and __init__, working in `page`."""
    import amfam_docs
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    app = amfam_docs.App(amfam_docs.build_parser().parse_args(["--config", str(cfg)]))
    app._context = page.context
    app._work_page = page
    app._dl_dir = tmp_path / "out" / ".amfam-downloads"
    return app


def run(app) -> None:
    """Discovery and then every document found, as Run All does them."""
    app.cmd_discover(quiet=True)
    app.process(app._select())


def saved(tmp_path, folder: str = "Statements") -> dict:
    where = tmp_path / "out" / folder
    return {p.name: p.read_bytes() for p in where.glob("*.pdf")} if where.exists() else {}


def expected(*bills) -> dict:
    return {name_of(b, d): pdf(b, d) for b in bills for d in DATES[b]}


def recorded(app) -> set:
    """Each document discovery recorded, as (its bill's account part, its date)."""
    return {(r.get("account"), r.get("date")) for r in app.discovery.data.values()}


def found(*bills) -> set:
    return {(part_of(b), iso(d)) for b in bills for d in DATES[b]}


def failure_reasons(tmp_path) -> list:
    folder = tmp_path / "out" / "Diagnostics"
    return [json.loads(p.read_text(encoding="utf-8")).get("reason")
            for p in sorted(folder.glob("failure*.json"))]


def states(app) -> dict:
    return {(r.get("account"), r.get("date")): (r.get("state"), bool(r.get("downloaded_ok")))
            for r in app.progress.data.values()}


def only_details_and_statements(s: Site) -> set:
    """Every press the stand-in server heard, once the page has had time to
    tell it, after checking that none was anything but a Bill details or a
    statement, and that no key reached the form."""
    s.settle(300)
    heard = set(s.pressed)
    others = {p for p in heard if not p.startswith(("bill-details-", "statement-"))}
    assert not others, "something else was pressed, %s" % sorted(others)
    return heard


def tabs_left(page) -> list:
    return [p for p in page.context.pages if not p.is_closed() and p is not page]


def statements_of(heard: set, bill: str) -> set:
    return {p for p in heard if p.startswith("statement-%s-" % bill)}


REVIEW = State.NEEDS_MANUAL_REVIEW.value


# -- each bill's statements, read from its own Bill details ----------------------------

@pytest.mark.parametrize("ways", [
    {"A": "place", "B": "place"},
    {"A": "route", "B": "route"},
    {"A": "late", "B": "place"},
], ids=["in place", "at a route of its own", "seconds after the press"])
def test_each_bills_statements_are_saved_from_its_bill_details(billing_site, tmp_path, ways):
    """Both bills' statements, the two dated 09/12/2026 included, each saved
    with its own bytes under its own bill's name, and nothing pressed but
    Bill details and statementPDF. The form above each list holds the
    focus, and no key reaches it."""
    s = billing_site(billing_page(ways))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    heard = only_details_and_statements(s)
    assert {"bill-details-A", "bill-details-B"} <= heard
    assert {p for p in heard if p.startswith("statement-")} == {
        "statement-%s-%s" % (b, d.replace("/", "-")) for b in ("A", "B") for d in DATES[b]}
    assert tabs_left(s.page) == [], "every tab a statement opened is closed"


def test_two_honest_bills_on_the_same_dates_are_both_saved(billing_site, tmp_path, monkeypatch):
    """A and B bill on the same days, and their rows show only the date and
    a PDF link, so their lists look alike. Each is still its own bill, with
    its own PDFs, and both were refused on every run."""
    monkeypatch.setitem(DATES, "B", list(DATES["A"]))
    s = billing_site(billing_page({"A": "route", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "B")
    assert saved(tmp_path) == expected("A", "B")
    assert failure_reasons(tmp_path) == []
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_older_statements_a_show_more_draws_late_are_read_whole(billing_site, tmp_path):
    """A's view shows its newest statement and a Show more, whose press
    draws the older one 300 ms later. Looked up straight after the press,
    the older one was not there yet."""
    s = billing_site(billing_page({"A": "route-more", "B": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_list_drawn_in_two_passes_is_read_whole(billing_site, tmp_path):
    """B's list shows its first statement and the rest 300 ms later. Read
    at its first link, the later statement was not found and went to
    manual review on every run."""
    s = billing_site(billing_page({"A": "route", "B": "place-twice"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_list_redrawn_above_the_row_is_pressed_on_the_row_read(billing_site, tmp_path):
    """As the app arms its catch of a statement, the page draws a row of
    another document above the rows it read. The statement is pressed on
    the very link that was read, never on whatever stands in its place."""
    insert = "document.querySelector('.statements .rows').insertAdjacentHTML('afterbegin', otherRow('07/01/2026'));"
    s = billing_site(billing_page({"A": "route", "B": "route"}, at_arm=insert))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


# -- what is pressed and what is refused ---------------------------------------------

@pytest.mark.parametrize("control", [
    "<button data-cy='billDetails' title='Edit autopay' onclick=\"details('B')\">Bill details</button>",
    "<button data-cy='billDetails' aria-label='Bill details' onclick=\"details('B')\">"
    "Bill details<span> and pay now</span></button>",
    "<span id='why-B'>Turns on autopay</span>"
    "<button data-cy='billDetails' aria-describedby='why-B' onclick=\"details('B')\">Bill details</button>",
], ids=["a title", "words beside the label", "a description"])
def test_a_bill_details_whose_words_refuse_is_never_pressed(billing_site, tmp_path, control):
    """The other bill is still opened and saved, and the run says why."""
    s = billing_site(billing_page({"A": "route", "B": "route"}, controls={"B": control}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.REFUSED_BUTTON]
    heard = only_details_and_statements(s)
    assert "bill-details-A" in heard and "bill-details-B" not in heard
    assert tabs_left(s.page) == []


def test_a_bill_details_that_holds_another_control_is_never_pressed(billing_site, tmp_path):
    """B's Bill details holds a switch of its own, away from where a press
    lands, so only the check of what it holds refuses it."""
    control = ("<div role='button' tabindex='0' id='details-B' aria-label='Bill details' "
               "onclick=\"details('B')\" style='display:inline-block;position:relative;"
               "padding:8px 40px 8px 8px'>Bill details<span role='switch' aria-label='' "
               "aria-checked='false' onclick=\"flag('inner-switch-B'); event.stopPropagation()\" "
               "style='position:absolute;right:4px;top:4px;width:12px;height:12px;display:block;"
               "background:#ccc'></span></div>")
    s = billing_site(billing_page({"A": "route", "B": "route"}, controls={"B": control}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    heard = only_details_and_statements(s)
    assert "bill-details-B" not in heard
    assert tabs_left(s.page) == []


@pytest.mark.parametrize("href", ["/billing/autopay/enroll", "#autopay"], ids=["a page", "a part of this page"])
def test_a_bill_details_link_to_a_refused_address_is_never_pressed(billing_site, tmp_path, href):
    """B's Bill details is a link to /billing/autopay/enroll, or to the
    autopay part of Billing & Payments. Its address is read before the
    press, and it is left alone."""
    control = ("<a data-cy='billDetails' id='details-B' href='%s' "
               "onclick=\"event.preventDefault(); details('B')\">Bill details</a>" % href)
    s = billing_site(billing_page({"A": "route", "B": "route"}, controls={"B": control}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.LINK_REFUSED]
    assert "bill-details-B" not in only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_details_that_cannot_be_pressed_at_once_is_given_up(billing_site, tmp_path):
    """B's Bill details stays disabled for three seconds after the app
    readies its press. The press is given up after a second and a half."""
    control = ("<button data-cy='billDetails' id='details-B' disabled "
               "onclick=\"details('B')\">Bill details</button>")
    enable = ("const b = document.getElementById('details-B');"
              " if (b) setTimeout(() => { b.disabled = false; }, 3000);")
    s = billing_site(billing_page({"A": "route", "B": "route"}, controls={"B": control}, at_mark=enable))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.PRESS_FAILED]
    assert "bill-details-B" not in only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_details_that_lands_on_autopay_is_refused(billing_site, tmp_path):
    """A's Bill details takes the tab to /billing/autopay, which shows
    statement links too. Nothing there is read or pressed, and B, whose
    press opens a route of its own, is still saved."""
    s = billing_site(billing_page({"A": "autopay", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert recorded(app) == found("B")
    assert failure_reasons(tmp_path) == [site.ADDRESS_REFUSED]
    heard = only_details_and_statements(s)
    assert "bill-details-A" in heard and not statements_of(heard, "A")
    assert tabs_left(s.page) == []


@pytest.mark.parametrize("way", ["query-autopay", "fragment-autopay"], ids=["its query", "its fragment"])
def test_an_address_refused_only_by_its_query_or_fragment_is_refused(billing_site, tmp_path, way):
    """A's Bill details opens a route of its own whose path passes, with
    autopay in its query or its fragment."""
    s = billing_site(billing_page({"A": way, "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == [site.ADDRESS_REFUSED]
    assert not statements_of(only_details_and_statements(s), "A")
    assert tabs_left(s.page) == []


def test_a_bill_details_that_opens_a_new_tab_is_refused(billing_site, tmp_path):
    """B's Bill details opens a tab of its own as it shows its list. The bill
    is left alone and the tab it opened is closed."""
    s = billing_site(billing_page({"A": "route", "B": "new-tab"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.NEW_TAB]
    assert not statements_of(only_details_and_statements(s), "B")
    assert tabs_left(s.page) == []


def test_a_tab_the_person_opens_during_a_press_is_never_closed(billing_site, tmp_path):
    """A tab opened in the same browser while A's Bill details is pressed,
    not by the page, is the person's own, and stays open."""
    s = billing_site(billing_page({"A": "route", "B": "route"}))
    ctx = s.page.context
    theirs: list = []

    def flagged(route):
        name = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        s.pressed.append(name)
        route.fulfill(status=204, body="")
        if name == "bill-details-A" and not theirs:
            theirs.append(ctx.new_page())

    ctx.route("%s/flag/*" % BASE, flagged)
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    assert len(theirs) == 1 and not theirs[0].is_closed(), "the person's tab was closed"
    only_details_and_statements(s)
    assert tabs_left(s.page) == theirs


def test_statements_drawn_beside_another_bill_are_refused(billing_site, tmp_path):
    """B's Bill details draws its rows among the bills' cards, around A's
    Bill details, so whose they are cannot be told."""
    s = billing_site(billing_page({"A": "route", "B": "beside"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.BESIDE_ANOTHER]
    assert not statements_of(only_details_and_statements(s), "B")
    assert tabs_left(s.page) == []


def test_a_press_that_shows_nothing_is_said(billing_site, tmp_path):
    """B's Bill details shows nothing in twenty seconds."""
    s = billing_site(billing_page({"A": "route", "B": "nothing"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.NOTHING_SHOWN]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_list_that_never_holds_still_is_left_alone(billing_site, tmp_path):
    """B's list draws another row every 400 ms for as long as it shows."""
    s = billing_site(billing_page({"A": "route", "B": "never-still"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.NEVER_SETTLED]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_not_found_again_after_the_reload_is_said(billing_site, tmp_path):
    """B's card is drawn on the first load only, so the bill listed is not
    there when its details are opened from the page loaded afresh."""
    s = billing_site(billing_page({"A": "route", "B": "route"}, vanish=("B",)))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.NOT_FOUND]
    assert "bill-details-B" not in only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_show_more_whose_words_refuse_is_never_pressed(billing_site, tmp_path):
    """A's statements end with a Show more whose title turns on autopay.
    Its words alone passed, and it was pressed."""
    more = {"A": "<button title='Turns on autopay' onclick=\"flag('show-more-A')\">Show more</button>"}
    s = billing_site(billing_page({"A": "route", "B": "route"}, more=more))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


# -- the view a press opened, read again ---------------------------------------------

def test_a_bill_view_that_moves_on_by_itself_is_not_read(billing_site, tmp_path):
    """A's view takes the tab to /billing/autopay as soon as it is
    scrolled, with its statements still showing, and no show-more was
    pressed to say so. Nothing is read there."""
    s = billing_site(billing_page({"A": "moves-on-scroll", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert recorded(app) == found("B")
    assert failure_reasons(tmp_path) == [site.LEFT_THE_VIEW]
    assert not statements_of(only_details_and_statements(s), "A")
    assert tabs_left(s.page) == []


def test_a_bill_view_that_moves_on_as_it_is_read_is_refused(billing_site, tmp_path):
    """A's view takes the tab to /billing/autopay the moment the app reads
    what the press brought, so the press's own check of where the tab is,
    made once that is read, refuses it."""
    s = billing_site(billing_page({"A": "moves-when-read", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == [site.ADDRESS_REFUSED]
    assert not statements_of(only_details_and_statements(s), "A")
    assert tabs_left(s.page) == []


def test_a_bill_view_that_moves_on_before_a_download_is_not_read(billing_site, tmp_path):
    """Discovery reads A's statements where its press showed them. Each
    later press takes the tab to /billing/autopay once the press is done,
    with the statements still showing, so no download takes one there."""
    s = billing_site(billing_page({"A": "moves-at-download", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "B")
    assert saved(tmp_path) == expected("B")
    assert not statements_of(only_details_and_statements(s), "A")
    assert tabs_left(s.page) == []


def test_a_view_that_names_another_bill_once_scrolled_is_refused(billing_site, tmp_path):
    """A's view draws B's billing account once it is scrolled through, so
    the check of what the page shows is made again after that."""
    s = billing_site(billing_page({"A": "names-another-on-scroll", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("B")
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == [site.ANOTHER_ACCOUNT]
    assert tabs_left(s.page) == []


def test_a_view_that_names_another_bill_at_a_download_is_not_read(billing_site, tmp_path):
    """A's view draws B's billing account from its second press on, once
    the press is done, so a download checks what the page shows too."""
    s = billing_site(billing_page({"A": "names-another-at-download", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "B")
    assert saved(tmp_path) == expected("B")
    assert not statements_of(only_details_and_statements(s), "A")
    assert tabs_left(s.page) == []


# -- telling bills apart ---------------------------------------------------------------

def test_bills_that_cannot_be_told_apart_are_left_alone(billing_site, tmp_path):
    """A and C end in the same four digits, so which of the two a statement
    belongs to could not be told. Neither is opened, and B still is."""
    s = billing_site(billing_page({"A": "route", "C": "route", "B": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == [site.NO_ACCOUNT]
    heard = only_details_and_statements(s)
    assert "bill-details-A" not in heard and "bill-details-C" not in heard
    assert tabs_left(s.page) == []


def test_a_bill_whose_card_shows_no_number_among_several_is_left_alone(billing_site, tmp_path):
    """N's card shows no number, so nothing its statements could be told by
    from a later bill. It is not opened, and A still is."""
    s = billing_site(billing_page({"A": "route", "N": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.NO_ACCOUNT]
    heard = only_details_and_statements(s)
    assert "bill-details-N" not in heard
    assert tabs_left(s.page) == []


def test_a_list_already_showing_is_never_taken_for_a_bills_own(billing_site, tmp_path):
    """Billing & Payments shows a statement list before any press, one of
    its dates a bill's own, and each bill's list opens in place beside it,
    A's three seconds after its press. Only what a bill's press brought is
    that bill's, in discovery and in the download, and the wait is for that
    and not for the list already there."""
    other = ("<div class='statements' id='statements-other'><div class='statements-header'>Statements</div>"
             + "".join("<div class='statement-row' data-cy='statementRow'><div class='cols'><div class='pdf-col'>"
                       "<a class='link' data-cy='statementPDF' title='View statement' "
                       "onclick=\"flag('other-statement'); openPdf('%s')\"><span class='label'>PDF</span></a>"
                       "</div><div class='date-col'><span>%s</span></div></div></div>"
                       % (b64(other_pdf(d)), d) for d in ("07/12/2026", "09/12/2026"))
             + "</div>")
    s = billing_site(billing_page({"A": "place-late", "B": "place"}, before=other))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "B")
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_paid_bills_card_beside_another_never_lends_it_its_number(billing_site, tmp_path):
    """A paid bill's card, with no Bill details, is drawn before A's. The
    first labeled number around A's Bill details was the paid bill's, and
    both of A's statements were saved under its number."""
    s = billing_site(billing_page({"A": "route"}, paid=card("B", "")))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A")
    assert saved(tmp_path) == expected("A")
    assert tabs_left(s.page) == []


def test_a_card_with_an_account_and_a_policy_is_saved_under_its_account(billing_site, tmp_path):
    """A's card shows its billing account number and its policy number. The
    account number is what tells two bills apart, so A is saved under it,
    where a card labeling two numbers had been left alone."""
    s = billing_site(billing_page({"A": "route", "B": "route"}, policies=("A",)))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "B")
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_an_autopay_bank_on_a_card_is_never_the_bills_number(billing_site, tmp_path):
    """A's card shows its billing account and N's its policy, and each says
    "Next AutoPay 10/01/2026 from account ending in 6789". Cut at its date,
    that line read 6789 as the bill's own account, which beat N's policy
    and made A's card hold two account numbers."""
    s = billing_site(billing_page({"A": "route", "N": "route"}, policies=("N",),
                                  lines={"A": [AUTOPAY_LINE], "N": [AUTOPAY_LINE]}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A", "N")
    assert saved(tmp_path) == expected("A", "N")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_whose_press_shows_another_bills_details_is_refused(billing_site, tmp_path):
    """B's Bill details shows A's details, A's account and A's statements.
    B is left alone and the run says why, and A is saved."""
    s = billing_site(billing_page({"A": "route", "B": "shows-A"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A")
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == [site.ANOTHER_ACCOUNT]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_one_list_shown_for_two_bills_sends_their_copies_to_manual_review(billing_site, tmp_path):
    """B's Bill details shows A's statements under no account at all, so
    each of B's statements is byte for byte A's of the same date. Neither
    bill's copy is trusted, both go to Manual Review, none is deleted, and
    D is saved."""
    s = billing_site(billing_page({"A": "route", "B": "same-as-A", "D": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("D")
    in_review = saved(tmp_path, "Manual Review")
    assert sorted(in_review) == sorted([name_of("A", d) for d in DATES["A"]] +
                                       ["%s American Family Billing Statement %s.pdf" % (iso(d), part_of("B"))
                                        for d in DATES["A"]])
    assert all(data == pdf("A", d) for name, data in in_review.items() for d in DATES["A"] if iso(d) in name)
    assert {k: v for k, v in states(app).items() if k[0] != part_of("D")} == {
        (part_of(b), iso(d)): (REVIEW, False) for b in ("A", "B") for d in DATES["A"]}
    assert failure_reasons(tmp_path) == ["two bills gave the same statement"]
    assert tabs_left(s.page) == []


@pytest.mark.parametrize("link, opens", [("B|09/12/2026", ("A", "09/12/2026")),
                                         ("A|09/12/2026", ("B", "09/12/2026"))],
                         ids=["the later bill's link", "the earlier bill's link"])
def test_a_statement_with_another_bills_bytes_sends_both_to_manual_review(billing_site, tmp_path,
                                                                          link, opens):
    """One bill's statement of 09/12/2026 opens the other bill's PDF of that
    date. Which of the two copies is wrong cannot be told, and when the
    earlier one was the wrong one the right one was deleted on every run.
    Neither is deleted and neither is trusted. Both go to Manual Review and
    neither record counts as downloaded, and every other statement is
    saved."""
    s = billing_site(billing_page({"A": "route", "B": "route"}, wrong={link: opens}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == {name_of("A", "08/12/2026"): pdf("A", "08/12/2026"),
                               name_of("B", "08/28/2026"): pdf("B", "08/28/2026")}
    assert saved(tmp_path, "Manual Review") == {name_of("A", "09/12/2026"): pdf(*opens),
                                                name_of("B", "09/12/2026"): pdf(*opens)}
    got = states(app)
    assert got[("...3401", "2026-09-12")] == (REVIEW, False)
    assert got[("...7802", "2026-09-12")] == (REVIEW, False)
    assert failure_reasons(tmp_path) == ["two bills gave the same statement"]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_drawn_before_the_one_listed_is_never_pressed_in_its_place(billing_site, tmp_path):
    """X's card is drawn first just as A's Bill details is about to be
    pressed, so the place A was listed at is X's by then."""
    insert = "document.querySelector('.bills').insertAdjacentHTML('afterbegin', CARD['X']);"
    s = billing_site(billing_page({"A": "route", "X": "route"}, drawn=("A",), at_mark=insert))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    heard = only_details_and_statements(s)
    assert "bill-details-X" not in heard
    assert tabs_left(s.page) == []


def test_a_bill_details_that_changes_before_the_press_is_not_pressed(billing_site, tmp_path):
    """A's Bill details takes a title that refuses just as it is about to be
    pressed. It is read again on the element itself and left alone, and B
    is still saved."""
    change = "document.getElementById('details-A').setAttribute('title', 'Edit autopay');"
    s = billing_site(billing_page({"A": "route", "B": "route"}, at_mark=change))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == [site.CHANGED]
    assert "bill-details-A" not in only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_document_found_before_the_page_listed_bills_is_left_as_it_is(billing_site, tmp_path):
    """A document an older run found with no account part, from a list the
    page showed at once, has no bill to open now that the page lists bills.
    It is left as it is, where it was failed as a capture on every run."""
    import amfam_docs
    s = billing_site(billing_page({"A": "route", "B": "route"}))
    app = app_on(s.page, tmp_path)
    older = amfam_docs.Document(title="Account Statement - Sep 12, 2026", category="Statement",
                                summary="Billing Statement", date="2026-09-12", confidence="High")
    record = older.to_dict()
    record["state"] = State.DISCOVERED.value
    app.discovery.update(older.key, record)
    run(app)
    assert saved(tmp_path) == expected("A", "B")
    assert app.progress.get(older.key) is None
    assert app.discovery.get(older.key)["state"] == State.DISCOVERED.value
    assert failure_reasons(tmp_path) == []
    assert tabs_left(s.page) == []


@pytest.mark.parametrize("levels, want", [
    (["Bill details", "Auto\nBilling account 9900123401\nAmount due $123.45\nDue date 10/01/2026"],
     ("...3401", "account")),
    (["Bill details", "Billing account\n9900123401\nDue 10/01/2026"], ("...3401", "account")),
    (["Bill details", "Auto policy 0045-498217\nAutoPay from checking account ending in 6789"],
     ("...8217", "policy")),
    (["Bill details", "Questions? Call 608-555-0199\nBilling account 9900123401"],
     ("...3401", "account")),
    (["Bill details", "Claim # 12345678\nAgent phone 608-555-0199\nPolicy 0045498217"],
     ("...8217", "policy")),
    (["Bill details", "Paid from bank account ending 6789\nPolicy 0045498217"], ("...8217", "policy")),
    (["Bill details", "Billing account 9900123401\nBilling account 9900567802"], (None, "account")),
    (["Bill details", "Billing account 9900123401\nPolicy 0045498217"], ("...3401", "account")),
    (["Bill details", "Auto policy 0045498217\nBilling account 9900123401\nHome policy 0099887766"],
     ("...3401", "account")),
    (["Bill details", "Auto policy 0045498217\nHome policy 0099887766"], (None, "policy")),
    (["Bill details", "Auto policy 0045498217\nNext AutoPay 10/01/2026 from account ending in 6789"],
     ("...8217", "policy")),
    (["Bill details", "Auto policy 0045498217\nAutoPay $123.45 from account ending in 6789"],
     ("...8217", "policy")),
    (["Bill details", "Billing account 9900123401\nAutoPay on 10/01/2026 from account ending in 6789"],
     ("...3401", "account")),
    (["Bill details", "Paying from account ending in 6789\nEdit autopay\nBill details",
      "Auto\nBilling account 9900123401\nPaying from account ending in 6789\nEdit autopay\nBill details"],
     ("...3401", "account")),
    (["Bill details", "Billing account 9900123401\nDrafted from account ending 6789"], ("...3401", "account")),
    (["Bill details", "Billing account 9900123401\nWithdrawn from account ending 6789"], ("...3401", "account")),
    (["Bill details", "Pay from account\n6789"], ("", "")),
    (["Bill details", "Payment due 10/01/2026 Billing account 9900123401"], ("", "")),
    (["Bill details", "Billing account ****2019"], ("...2019", "account")),
    (["Bill details", "Billing account ...2019"], ("...2019", "account")),
    (["Bill details", "Amount due $123.45\nDue 10/01/2026\nRef 55554444\n#55556666"], ("", "")),
    (["Bill details", "Auto\nBilling account 9900123401",
      "Home\nBilling account 9900567802\nPaid in full\nAuto\nBilling account 9900123401"],
     ("...3401", "account")),
], ids=["account", "label above", "policy beside an autopay bank", "a phone", "a claim and an agent",
        "a bank", "two accounts", "an account and a policy", "an account between two policies",
        "two policies and no account", "autopay after a date", "autopay after an amount",
        "an account and autopay after a date", "paying from", "drafted from", "withdrawn from",
        "pay from, labeled above", "a payment due on the account's line", "masked with stars",
        "masked with dots", "nothing labeled", "the narrowest card"])
def test_a_bills_account_part_comes_only_from_a_number_its_card_labels(levels, want):
    """An account number, or a policy number when the card labels no
    account, from the narrowest element that labels one, never a number
    whose line ties it to a bank, autopay, a card, a payment, paying, a
    draft, a withdrawal, a phone, a claim or an agent, and nothing when that
    element labels two different numbers of the kind used. A mask's last
    four is never taken for a year."""
    assert site._account_of(levels) == want


# -- Diagnose ---------------------------------------------------------------------------

def test_diagnose_presses_each_bill_details_and_says_what_it_did(billing_site, tmp_path):
    """Where each press led, as its shape, how many statement links showed
    and how many seconds they took, written through the word list. No
    statement is pressed and the invented account numbers stay out."""
    s = billing_site(billing_page({"A": "late", "B": "place-twice"}))
    app = app_on(s.page, tmp_path)
    app.cmd_diagnose()
    written = (tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8")
    info = json.loads(written)
    bills = info["bills"]
    assert [b["pressed"] for b in bills] == [True, True]
    assert [b["safe"] for b in bills] == [True, True]
    assert [b["identity_read"] for b in bills] == [True, True]
    assert [b["identity_kind"] for b in bills] == ["account", "account"]
    # B's list is drawn in two passes, and both of its links are counted.
    assert [b["statement_links"] for b in bills] == [2, 2]
    # A's list is drawn three seconds after its press, so no fewer than
    # that can have passed. B's count is a whole number of seconds, however
    # long a busy machine took.
    assert bills[0]["seconds_until_links"] >= 2
    assert isinstance(bills[1]["seconds_until_links"], int) and bills[1]["seconds_until_links"] >= 0
    assert [b.get("refused") for b in bills] == [None, None]
    assert bills[0]["address"] == "https://myaccount.amfam.com/billing/bill-details/a9a9"
    assert bills[1]["address"] == "https://myaccount.amfam.com/billing"
    for _heading, account in CARDS.values():
        assert not account or (account not in written and account[-4:] not in written)
    assert [d["bill"] for d in info["documents_recognized"]] == [True] * 4
    heard = only_details_and_statements(s)
    assert not {p for p in heard if p.startswith("statement-")}, "Diagnose pressed a statement"
    assert tabs_left(s.page) == []


def test_diagnose_finds_each_bill_again_by_its_account_part(billing_site, tmp_path):
    """The bills are drawn in the other order on every other load. Each one
    Diagnose presses is the bill whose card it lists, found again by its
    account part, never by its place."""
    s = billing_site(billing_page({"A": "route", "D": "route"}, alternate=True))
    app = app_on(s.page, tmp_path)
    app.cmd_diagnose()
    info = json.loads((tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8"))
    links = {b["card"].split(" ")[0]: b["statement_links"] for b in info["bills"]}
    assert links == {"Auto": len(DATES["A"]), "Renters": len(DATES["D"])}
    assert tabs_left(s.page) == []
