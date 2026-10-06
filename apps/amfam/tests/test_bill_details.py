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
loaded the page again. Each bill opens its list one of three ways, in
place, at a route of its own, or a few seconds after the press. Run
through the app's own discovery and download loop, in a real browser,
since a blob and its tab are the browser's doing."""
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

BASE = "https://myaccount.amfam.com"

# The invented bills. Each card shows a billing account number, and C's
# ends in the same four digits as A's.
CARDS = {
    "A": ("Auto", "9900123401"),
    "B": ("Home", "9900567802"),
    "C": ("Umbrella", "9911113401"),
}
# Both A and B have a statement dated 09/12/2026.
DATES = {
    "A": ["09/12/2026", "08/12/2026"],
    "B": ["09/12/2026", "08/28/2026"],
    "C": ["09/20/2026"],
}
POLICY = {"A": "ZA-0001-2345-01", "B": "ZH-0006-7890-02", "C": "ZU-0004-4444-03"}
ROUTE = {"A": "x7k2", "B": "m4q9", "C": "t2v8"}


def iso(date: str) -> str:
    m, d, y = date.split("/")
    return "%s-%s-%s" % (y, m, d)


def pdf(bill: str, date: str) -> bytes:
    """An invented statement, which prints its own policy and period."""
    return testkit.text_pdf(["Invented insurer statement",
                             "Policy %s" % POLICY[bill],
                             "Statement period ending %s" % date])


def name_of(bill: str, date: str) -> str:
    """The file a statement is saved as, its bill's last four in its name."""
    return "%s American Family Billing Statement ...%s.pdf" % (iso(date), CARDS[bill][1][-4:])


def details_button(bill: str) -> str:
    return "<button data-cy='billDetails' onclick=\"details('%s')\">Bill details</button>" % bill


def card(bill: str, control: str) -> str:
    heading, account = CARDS[bill]
    return ("<div class='bill-card' data-cy='billCard'><h2>%s</h2>"
            "<p><span>Billing account</span> <span>%s</span></p>"
            "<p><span>Amount due</span> <span>$123.45</span></p>"
            "<p><span>Due date</span> <span>10/01/2026</span></p>"
            "<button data-cy='editAutopay' onclick=\"flag('edit-autopay-%s')\">Edit autopay</button>"
            "%s</div>" % (heading, account, bill, control))


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
function flag(name) { fetch('/flag/' + name); }
function openStatement(bill, date) {
  flag('statement-' + bill + '-' + date.split('/').join('-'));
  const bytes = Uint8Array.from(atob(PDFS[bill + '|' + date]), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  window.open(url, '_blank');
  URL.revokeObjectURL(url);
}
function rows(bill) {
  return DATES[bill].map((d) =>
    "<div class='statement-row' data-cy='statementRow'><div class='cols'>" +
    "<div class='pdf-col'><a class='link' data-cy='statementPDF' title='View statement' " +
    "onclick=\"openStatement('" + bill + "','" + d + "')\">" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div>" +
    "<span class='label'>PDF</span>" +
    "<div class='icon' style='display:inline-block;width:12px;height:12px'></div></a></div>" +
    "<div class='date-col'><span>" + d + "</span></div></div></div>").join('');
}
function list(bill) {
  return "<div class='statements' id='statements-" + bill + "'>" +
    "<div class='statements-header'>Billing statements</div>" +
    "<div class='statements-body'><div class='statements-note'><span>Your recent statements</span></div>" +
    "<div class='statements-list'><app-statement-list><div class='list'>" +
    "<form class='statement-filter' onsubmit=\"flag('form-submit'); return false;\">" +
    "<select onchange=\"flag('form-change')\"><option>Last 12 months</option></select></form>" +
    "<div class='rows'>" + rows(bill) + "</div>" +
    "<div class='list-end'><span>End of list</span></div><div class='list-foot'></div>" +
    "</div></app-statement-list></div></div></div>";
}
function view(heading, bill) {
  document.querySelector('.page').innerHTML = '<h1>' + heading + '</h1>' +
    "<div class='bill-summary'><span>Billing account " + ACCOUNT[bill] + "</span></div>" + list(bill);
}
function details(bill) {
  flag('bill-details-' + bill);
  const way = WAYS[bill];
  if (way === 'place') {
    document.getElementById('details').innerHTML = list(bill);
  } else if (way === 'route') {
    history.pushState({}, '', '/billing/bill-details/' + ROUTE[bill]);
    view('Bill details', bill);
  } else if (way === 'late') {
    history.pushState({}, '', '/billing/bill-details/' + ROUTE[bill]);
    document.querySelector('.page').innerHTML = '<h1>Bill details</h1><p>Loading</p>';
    setTimeout(() => view('Bill details', bill), 3000);
  } else if (way === 'autopay') {
    history.pushState({}, '', '/billing/autopay');
    view('Autopay', bill);
  }
}
"""


def billing_page(ways: dict, controls: dict = None, before: str = "") -> str:
    """Billing & Payments the way the tester's Diagnose saw it, one card for
    each bill in `ways`, saying how its Bill details opens its statements.
    `controls` replaces a bill's Bill details button, and `before` is drawn
    above the bills."""
    controls = controls or {}
    bills = list(ways)
    pdfs = {"%s|%s" % (b, d): base64.b64encode(pdf(b, d)).decode("ascii")
            for b in bills for d in DATES[b]}
    script = (SCRIPT.replace("__PDFS__", json.dumps(pdfs))
              .replace("__DATES__", json.dumps({b: DATES[b] for b in bills}))
              .replace("__WAYS__", json.dumps(ways))
              .replace("__ROUTE__", json.dumps(ROUTE))
              .replace("__ACCOUNT__", json.dumps({b: CARDS[b][1] for b in bills})))
    cards = "".join(card(b, controls.get(b, details_button(b))) for b in bills)
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
        pytest.skip("no browser to drive: %s" % e)

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


def only_details_and_statements(s: Site) -> set:
    """Every press the stand-in server heard, once the page has had time to
    tell it, after checking that none was anything but a Bill details or a
    statement."""
    s.settle(300)
    heard = set(s.pressed)
    others = {p for p in heard if not p.startswith(("bill-details-", "statement-"))}
    assert not others, "pressed something else: %s" % sorted(others)
    return heard


def tabs_left(page) -> list:
    return [p for p in page.context.pages if not p.is_closed() and p is not page]


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


def test_a_bill_details_that_lands_on_autopay_is_refused(billing_site, tmp_path):
    """A's Bill details takes the tab to /billing/autopay, which shows
    statement links too. Nothing there is read or pressed, and B, whose
    press opens a route of its own, is still saved."""
    s = billing_site(billing_page({"A": "autopay", "B": "route"}))
    app = app_on(s.page, tmp_path)
    run(app)
    assert saved(tmp_path) == expected("B")
    assert not [r for r in app.discovery.data.values() if r.get("account") == "...3401"]
    heard = only_details_and_statements(s)
    assert "bill-details-A" in heard
    assert not {p for p in heard if p.startswith("statement-A-")}
    assert tabs_left(s.page) == []


def test_bills_that_cannot_be_told_apart_are_left_alone(billing_site, tmp_path):
    """A and C end in the same four digits, so which of the two a statement
    belongs to could not be told. Neither is opened, and B still is."""
    s = billing_site(billing_page({"A": "route", "C": "route", "B": "route"}))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("B")
    heard = only_details_and_statements(s)
    assert "bill-details-A" not in heard and "bill-details-C" not in heard
    assert tabs_left(s.page) == []


def test_a_list_already_showing_is_never_taken_for_a_bills_own(billing_site, tmp_path):
    """Billing & Payments shows a statement list before any press, and each
    bill's own list opens in place beside it. Only what a bill's press
    brought is that bill's."""
    other = ("<div class='statements' id='statements-other'><div class='statements-header'>Statements</div>"
             "<div class='statement-row' data-cy='statementRow'><div class='cols'><div class='pdf-col'>"
             "<a class='link' data-cy='statementPDF' title='View statement' onclick=\"flag('other-statement')\">"
             "<span class='label'>PDF</span></a></div><div class='date-col'><span>07/12/2026</span></div>"
             "</div></div></div>")
    s = billing_site(billing_page({"A": "place", "B": "place"}, before=other))
    run(app_on(s.page, tmp_path))
    assert saved(tmp_path) == expected("A", "B")
    only_details_and_statements(s)
    assert tabs_left(s.page) == []


def test_diagnose_presses_each_bill_details_and_says_what_it_did(billing_site, tmp_path):
    """Where each press led, as its shape, how many statement links showed
    and how many seconds they took, written through the word list. No
    statement is pressed and the invented account numbers stay out."""
    s = billing_site(billing_page({"A": "late", "B": "route"}))
    app = app_on(s.page, tmp_path)
    app.cmd_diagnose()
    written = (tmp_path / "out" / "Diagnostics" / "diagnose-documents.json").read_text(encoding="utf-8")
    info = json.loads(written)
    bills = info["bills"]
    assert [b["pressed"] for b in bills] == [True, True]
    assert [b["safe"] for b in bills] == [True, True]
    assert [b["identity_read"] for b in bills] == [True, True]
    assert [b["statement_links"] for b in bills] == [2, 2]
    assert bills[0]["seconds_until_links"] >= 2 and bills[1]["seconds_until_links"] <= 1
    assert bills[0]["address"] == "https://myaccount.amfam.com/billing/bill-details/a9a9"
    assert bills[1]["address"] == "https://myaccount.amfam.com/billing/bill-details/a9a9"
    for _heading, account in CARDS.values():
        assert account not in written and account[-4:] not in written
    assert [d["bill"] for d in info["documents_recognized"]] == [True] * 4
    heard = only_details_and_statements(s)
    assert not {p for p in heard if p.startswith("statement-")}, "Diagnose pressed a statement"
    assert tabs_left(s.page) == []
