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
loaded the page again. A bill's Bill details opens its list in place, at a
route of its own, seconds after the press, or in two passes, and the pages
from the review of the change go wrong the ways a site could, another
bill's details behind a press, one list for two bills, another bill's PDF
behind a link, a page that moves on by itself or redraws its bills just as
one is pressed. Run through the app's own discovery and download loop, in
a real browser, since a blob and its tab are the browser's doing."""
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


def name_of(bill: str, date: str) -> str:
    """The file a statement is saved as, its bill's last four in its name."""
    return "%s American Family Billing Statement ...%s.pdf" % (iso(date), CARDS[bill][1][-4:])


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def details_button(bill: str) -> str:
    return ("<button data-cy='billDetails' id='details-%s' onclick=\"details('%s')\">Bill details</button>"
            % (bill, bill))


def card(bill: str, control: str = None, policy: bool = False) -> str:
    """A bill's card on Billing & Payments. `control` is its Bill details,
    and an empty one draws a card with none, a bill paid in full. With
    `policy` the card shows its policy number below its account number."""
    heading, account = CARDS[bill]
    number = "<p><span>Billing account</span> <span>%s</span></p>" % account if account else ""
    if policy:
        number += "<p><span>%s policy</span> <span>%s</span></p>" % (heading, POLICY[bill])
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
# child above the rows, rows marked with data-cy, and in each a link with
# no address marked statementPDF that opens a tab at a blob of the PDF.
SCRIPT = r"""
const PDFS = __PDFS__;
const DATES = __DATES__;
const WAYS = __WAYS__;
const ROUTE = __ROUTE__;
const ACCOUNT = __ACCOUNT__;
const MORE = __MORE__;
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
function rows(bill, upto) {
  return DATES[bill].slice(0, upto || DATES[bill].length).map((d) =>
    "<div class='statement-row' data-cy='statementRow'><div class='cols'>" +
    "<div class='pdf-col'><a class='link' data-cy='statementPDF' title='View statement' " +
    "onclick=\"openStatement('" + bill + "','" + d + "')\">" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div>" +
    "<span class='label'>PDF</span>" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div></a></div>" +
    "<div class='date-col'><span>" + d + "</span></div></div></div>").join('');
}
function list(bill, upto, more) {
  return "<div class='statements' id='statements-" + bill + "'>" +
    "<div class='statements-header'>Billing statements</div>" +
    "<div class='statements-body'><div class='statements-note'><span>Your recent statements</span></div>" +
    "<div class='statements-list'><app-statement-list><div class='list'>" +
    "<form class='statement-filter' onsubmit=\"flag('form-submit'); return false;\">" +
    "<select onchange=\"flag('form-change')\"><option>Last 12 months</option></select></form>" +
    "<div class='rows'>" + rows(bill, upto) + "</div>" + (more || MORE[bill] || '') +
    "<div class='list-end'><span>End of list</span></div><div class='list-foot'></div>" +
    "</div></app-statement-list></div></div></div>";
}
function view(heading, account, bill, upto, more) {
  const summary = account ?
    "<div class='bill-summary'><span>Billing account " + ACCOUNT[account] + "</span></div>" : '';
  document.querySelector('.page').innerHTML = '<h1>' + heading + '</h1>' + summary + list(bill, upto, more);
}
function older(button, bill) {
  button.remove();
  setTimeout(() => { document.querySelector('#statements-' + bill + ' .rows').innerHTML = rows(bill); }, 300);
}
function details(bill) {
  flag('bill-details-' + bill);
  const way = WAYS[bill];
  const own = () => history.pushState({}, '', '/billing/bill-details/' + ROUTE[bill]);
  if (way === 'place') {
    document.getElementById('details').innerHTML = list(bill);
  } else if (way === 'place-late') {
    setTimeout(() => { document.getElementById('details').innerHTML = list(bill); }, 3000);
  } else if (way === 'place-twice') {
    document.getElementById('details').innerHTML = list(bill, 1);
    setTimeout(() => { document.getElementById('details').innerHTML = list(bill); }, 300);
  } else if (way === 'route') {
    own();
    view('Bill details', bill, bill);
  } else if (way === 'route-more') {
    own();
    view('Bill details', bill, bill, 1,
         "<button onclick=\"older(this, '" + bill + "')\">Show more</button>");
  } else if (way === 'late') {
    own();
    document.querySelector('.page').innerHTML = '<h1>Bill details</h1><p>Loading</p>';
    setTimeout(() => view('Bill details', bill, bill), 3000);
  } else if (way === 'autopay') {
    history.pushState({}, '', '/billing/autopay');
    view('Autopay', bill, bill);
  } else if (way === 'shows-A') {
    own();
    view('Bill details', 'A', 'A');
  } else if (way === 'same-as-A') {
    own();
    view('Bill details', null, 'A');
  } else if (way === 'moves-on-scroll') {
    own();
    view('Bill details', bill, bill);
    window.addEventListener('wheel', () => history.pushState({}, '', '/billing/autopay'), {once: true});
  } else if (way === 'moves-at-download') {
    // From the bill's second press on, the first time the app reads which
    // tabs the press opened, the tab moves to /billing/autopay.
    own();
    view('Bill details', bill, bill);
    const n = Number(sessionStorage.getItem('presses-' + bill) || 0) + 1;
    sessionStorage.setItem('presses-' + bill, String(n));
    if (n >= 2) {
      let tabs = window.__paperpullTabs, moved = false;
      Object.defineProperty(window, '__paperpullTabs', {configurable: true,
        get() { if (!moved) { moved = true; history.pushState({}, '', '/billing/autopay'); } return tabs; },
        set(v) { tabs = v; }});
    }
  }
}
(function () { __AT_MARK__ })();
"""

# What the page does the moment the app keeps a note of the statements
# showing, just before it presses a Bill details. Tied to the app's own
# step, never a clock.
AT_MARK = """
  let done = false;
  Object.defineProperty(window, '__paperpullShownBefore', {configurable: true,
    get() { return window.__shownBefore; },
    set(v) { window.__shownBefore = v; if (!done) { done = true; %s } }});
"""


def billing_page(ways: dict, controls: dict = None, before: str = "", paid: str = "",
                 more: dict = None, wrong: dict = None, at_mark: str = "",
                 policies: tuple = ()) -> str:
    """Billing & Payments the way the tester's Diagnose saw it, one card for
    each bill in `ways`, saying how its Bill details opens its statements.
    `controls` replaces a bill's Bill details, `before` is drawn above the
    bills and `paid` first among them. `more` adds a control to a bill's
    list, `wrong` sends a bill's link to another bill's PDF, `at_mark` is
    done as the app marks what shows before a press, and the cards of the
    bills in `policies` show a policy number too."""
    controls = controls or {}
    pdfs = {"%s|%s" % (b, d): b64(pdf(b, d)) for b in CARDS for d in DATES[b]}
    for link, (bill, date) in (wrong or {}).items():
        pdfs[link] = b64(pdf(bill, date))
    script = (SCRIPT.replace("__PDFS__", json.dumps(pdfs))
              .replace("__DATES__", json.dumps(DATES))
              .replace("__WAYS__", json.dumps(ways))
              .replace("__ROUTE__", json.dumps(ROUTE))
              .replace("__ACCOUNT__", json.dumps({b: CARDS[b][1] for b in CARDS}))
              .replace("__MORE__", json.dumps(more or {}))
              .replace("__AT_MARK__", AT_MARK % at_mark if at_mark else ""))
    cards = paid + "".join(card(b, controls.get(b), b in policies) for b in ways)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Billing &amp; Payments</title></head>"
            "<body><div role='main' id='main'><app-billing class='routed'><div class='page'>"
            "<h1>My bills</h1>%s<div class='bills'>%s</div>"
            "<div class='bill-actions'>"
            "<button data-cy='manageAutopay' onclick=\"flag('manage-autopay')\">Manage AutoPay</button>"
            "<button data-cy='paymentMethods' onclick=\"flag('payment-methods')\">Payment methods</button>"
            "<button data-cy='linkAccount' onclick=\"flag('link-account')\">Link account</button>"
            "</div><div id='details'></div></div></app-billing></div>"
            "<script>%s</script></body></html>" % (before, cards, script))


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


def saved(tmp_path) -> dict:
    folder = tmp_path / "out" / "Statements"
    return {p.name: p.read_bytes() for p in folder.glob("*.pdf")} if folder.exists() else {}


def expected(*bills) -> dict:
    return {name_of(b, d): pdf(b, d) for b in bills for d in DATES[b]}


def recorded(app) -> set:
    """Each document discovery recorded, as (its bill's account part, its date)."""
    return {(r.get("account"), r.get("date")) for r in app.discovery.data.values()}


def found(*bills) -> set:
    return {("..." + CARDS[b][1][-4:], iso(d)) for b in bills for d in DATES[b]}


def failure_reasons(tmp_path) -> list:
    folder = tmp_path / "out" / "Diagnostics"
    return [json.loads(p.read_text(encoding="utf-8")).get("reason")
            for p in sorted(folder.glob("failure*.json"))]


def only_details_and_statements(s: Site) -> set:
    """Every press the stand-in server heard, once the page has had time to
    tell it, after checking that none was anything but a Bill details or a
    statement."""
    s.settle(300)
    heard = set(s.pressed)
    others = {p for p in heard if not p.startswith(("bill-details-", "statement-"))}
    assert not others, "something else was pressed, %s" % sorted(others)
    return heard


def tabs_left(page) -> list:
    return [p for p in page.context.pages if not p.is_closed() and p is not page]


def statements_of(heard: set, bill: str) -> set:
    return {p for p in heard if p.startswith("statement-%s-" % bill)}


@pytest.mark.parametrize("ways", [
    {"A": "place", "B": "place"},
    {"A": "route", "B": "route"},
    {"A": "late", "B": "place"},
], ids=["in place", "at a route of its own", "seconds after the press"])
def test_each_bills_statements_are_saved_from_its_bill_details(billing_site, tmp_path, ways):
    """Both bills' statements, the two dated 09/12/2026 included, each saved
    with its own bytes under its own bill's name, and nothing pressed but
    Bill details and statementPDF."""
    s = billing_site(billing_page(ways))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    heard = only_details_and_statements(s)
    assert {"bill-details-A", "bill-details-B"} <= heard
    assert {p for p in heard if p.startswith("statement-")} == {
        "statement-%s-%s" % (b, d.replace("/", "-")) for b in ("A", "B") for d in DATES[b]}
    assert tabs_left(s.page) == [], "every tab a statement opened is closed"


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


@pytest.mark.parametrize("control", [
    "<button data-cy='billDetails' title='Edit autopay' onclick=\"details('B')\">Bill details</button>",
    "<button data-cy='billDetails' aria-label='Bill details' onclick=\"details('B')\">"
    "Bill details<span> and pay now</span></button>",
    "<span id='why-B'>Turns on autopay</span>"
    "<button data-cy='billDetails' aria-describedby='why-B' onclick=\"details('B')\">Bill details</button>",
], ids=["a title", "words beside the label", "a description"])
def test_a_bill_details_whose_words_refuse_is_never_pressed(billing_site, tmp_path, control):
    """The other bill is still opened and saved."""
    s = billing_site(billing_page({"A": "route", "B": "route"}, controls={"B": control}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
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


def test_a_bill_details_that_lands_on_autopay_is_refused(billing_site, tmp_path):
    """A's Bill details takes the tab to /billing/autopay, which shows
    statement links too. Nothing there is read or pressed, and B, whose
    press opens a route of its own, is still saved."""
    s = billing_site(billing_page({"A": "autopay", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert recorded(app) == found("B")
    heard = only_details_and_statements(s)
    assert "bill-details-A" in heard and not statements_of(heard, "A")
    assert tabs_left(s.page) == []


def test_a_bill_view_that_moves_on_by_itself_is_not_read(billing_site, tmp_path):
    """A's view takes the tab to /billing/autopay as soon as the page is
    scrolled, with its statements still showing, and no show-more was
    pressed to say so. Nothing is read there."""
    s = billing_site(billing_page({"A": "moves-on-scroll", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert recorded(app) == found("B")
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


def test_bills_that_cannot_be_told_apart_are_left_alone(billing_site, tmp_path):
    """A and C end in the same four digits, so which of the two a statement
    belongs to could not be told. Neither is opened, and B still is."""
    s = billing_site(billing_page({"A": "route", "C": "route", "B": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("B")
    assert failure_reasons(tmp_path) == ["a bill had no account of its own"]
    heard = only_details_and_statements(s)
    assert "bill-details-A" not in heard and "bill-details-C" not in heard
    assert tabs_left(s.page) == []


def test_a_bill_whose_card_shows_no_number_among_several_is_left_alone(billing_site, tmp_path):
    """N's card shows no number, so nothing its statements could be told by
    from a later bill. It is not opened, and A still is."""
    s = billing_site(billing_page({"A": "route", "N": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == ["a bill had no account of its own"]
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


def test_a_bill_whose_press_shows_another_bills_details_is_refused(billing_site, tmp_path):
    """B's Bill details shows A's details, A's account and A's statements.
    B is left alone and the run says why, and A is saved."""
    s = billing_site(billing_page({"A": "route", "B": "shows-A"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("A")
    assert saved(tmp_path) == expected("A")
    assert failure_reasons(tmp_path) == ["a bill showed another account"]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_two_bills_that_show_the_same_statements_are_both_left_alone(billing_site, tmp_path):
    """B's Bill details shows A's statements under no account at all, so the
    two lists are one and whose they are cannot be told. Neither is kept,
    and D is saved. N's card shows no number, which is a reason of its own,
    and still the failure file says first, in plain words, that two bills
    showed the same statement list, since that says which way the page
    works, with every reason beside it."""
    s = billing_site(billing_page({"A": "route", "B": "same-as-A", "N": "route", "D": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert recorded(app) == found("D")
    assert saved(tmp_path) == expected("D")
    assert failure_reasons(tmp_path) == ["two bills showed the same statement list"]
    [written] = (tmp_path / "out" / "Diagnostics").glob("failure*.json")
    said = json.loads(written.read_text(encoding="utf-8"))["extra"]["postmortem"]["refused"]
    assert said == ["a bill had no account of its own", "two bills showed the same statement list"]
    heard = only_details_and_statements(s)
    assert not statements_of(heard, "A") and not statements_of(heard, "B")
    assert tabs_left(s.page) == []


def test_a_statement_with_another_bills_bytes_is_not_kept(billing_site, tmp_path):
    """B's statement of 09/12/2026 opens A's PDF of that date. It is not
    kept as B's, the document waits for manual review and the run says why,
    and every other statement is saved."""
    s = billing_site(billing_page({"A": "route", "B": "route"},
                                  wrong={"B|09/12/2026": ("A", "09/12/2026")}))
    app = app_on(s.page, tmp_path)
    run(app)
    want = expected("A")
    want[name_of("B", "08/28/2026")] = pdf("B", "08/28/2026")
    assert saved(tmp_path) == want
    states = {(r.get("account"), r.get("date")): r.get("state") for r in app.progress.data.values()}
    assert states[("...7802", "2026-09-12")] == State.NEEDS_MANUAL_REVIEW.value
    assert failure_reasons(tmp_path) == ["two bills gave the same statement"]
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_a_bill_drawn_before_the_one_listed_is_never_pressed_in_its_place(billing_site, tmp_path):
    """X's card is drawn first just as A's Bill details is about to be
    pressed, so the place A was listed at is X's by then."""
    insert = "document.querySelector('.bills').insertAdjacentHTML('afterbegin', %s);" % json.dumps(card("X"))
    s = billing_site(billing_page({"A": "route", "X": "route"}, at_mark=insert).replace(
        card("X"), "", 1))
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
    assert "bill-details-A" not in only_details_and_statements(s)
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
    (["Bill details", "Payment due 10/01/2026 Billing account 9900123401"], ("...3401", "account")),
    (["Bill details", "Amount due $123.45\nDue 10/01/2026\nRef 55554444\n#55556666"], ("", "")),
    (["Bill details", "Auto\nBilling account 9900123401",
      "Home\nBilling account 9900567802\nPaid in full\nAuto\nBilling account 9900123401"],
     ("...3401", "account")),
], ids=["account", "label above", "policy beside an autopay bank", "a phone", "a claim and an agent",
        "a bank", "two accounts", "an account and a policy", "an account between two policies",
        "two policies and no account", "a payment date first", "nothing labeled", "the narrowest card"])
def test_a_bills_account_part_comes_only_from_a_number_its_card_labels(levels, want):
    """An account number, or a policy number when the card labels no
    account, never a bank's, a card's, a phone's, a claim's or an agent's,
    from the narrowest element that labels one, and nothing when that
    element labels two different numbers of the kind used."""
    assert site._account_of(levels) == want


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
