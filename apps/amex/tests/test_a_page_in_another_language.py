"""American Express in another language, as a German account showed it (#107).

A tester's German account names its links and sections in German, and the
app looked for English words. From the dashboard it found no "Statements &
Activity" link and listed nothing, and with the older statements' section
collapsed, every older statement's Download was not found. The tester found
what is the same in every language. The links point at /activity and
/activity/statements, each with a query of its own, and the section's
heading controls content-older-statements.

So where the English words find nothing, a link is found by its address,
and a section's heading by the part it opens. An English page is reached
the way it always was. Everything here is invented, and it drives a real
browser against made-up pages served at American Express's own address, so
where each press lands and where the tab goes are the browser's own.

A link found by its address has no words of ours to go by, so it is read
with care. An independent review found a link pressed twice when its page
took longer than the wait after it, and a slow English route followed by a
press of another card's tile. Each link on the way is pressed once, and a
press whose page does not come stops the run. A link that shows, says
nothing this app never does and names one card is the only one taken.
Where links name two cards, nothing is pressed. Where the English
Statements & Activity link shows, nothing is looked for by its address, so
a tile of the page before, still drawn while the next one loads, is never
taken for the next page's own link.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amex_site as site
from paperpull_core import pressing

BASE = "https://global.americanexpress.com"
RECENT = ["2031-09-25", "2031-08-25"]
OLDER = ["2031-07-25", "2031-06-25"]


def _button(section: str, date: str) -> str:
    return ('<button data-test-id="axp-pdf-statements/common/Table/%s-statements/%s/'
            'download-button">Herunterladen</button>' % (section, date))


STATEMENTS = """<!doctype html><meta charset="utf-8"><title>PDF-Abrechnungen</title>
<main>
<h1>PDF-Abrechnungen</h1>
<section>%(recent)s</section>
<button id="header-older-statements" aria-controls="content-older-statements"
  aria-expanded="%(expanded)s">Vergangene Abrechnungen</button>
<section id="content-older-statements" %(hidden)s>%(older)s</section>
</main>
<script>
window.headPresses = 0;
document.getElementById('header-older-statements').addEventListener('click', (e) => {
  window.headPresses++;
  const open = e.target.getAttribute('aria-expanded') === 'true';
  e.target.setAttribute('aria-expanded', open ? 'false' : 'true');
  document.getElementById('content-older-statements').hidden = open;
});
</script>"""

DASHBOARD_TO_STATEMENTS = """<!doctype html><meta charset="utf-8"><title>Startseite</title>
<main><h1>Willkommen</h1>
<a href="/activity/statements?account_key=K0NT0">Abrechnung(en) runterladen</a></main>"""

DASHBOARD_TO_ACTIVITY = """<!doctype html><meta charset="utf-8"><title>Startseite</title>
<main><h1>Willkommen</h1>
<a href="/activity?inav=menu_myacct_acctsum">Kontobewegungen &amp; Abrechnungen</a></main>"""

ACTIVITY = """<!doctype html><meta charset="utf-8"><title>Kontobewegungen</title>
<main><h1>Kontobewegungen</h1>
<a href="/activity/statements?account_key=K0NT0">PDF-Abrechnungen</a></main>"""

# The English dashboard as the app has always met it, with a link to the
# statements' address beside the English one.
DASHBOARD_ENGLISH = """<!doctype html><meta charset="utf-8"><title>Home</title>
<main><h1>Welcome</h1>
<a href="/activity?inav=x">Statements &amp; Activity</a>
<a href="/activity/statements?account_key=K0NT0">Download statements</a></main>"""

ACTIVITY_ENGLISH = """<!doctype html><meta charset="utf-8"><title>Activity</title>
<main><h1>Activity</h1>
<a data-testid="goToPdfLinkLg" href="/activity/statements?account_key=K0NT0">Go to PDF Statements</a>
</main>"""


class Site:
    def __init__(self, dashboard=DASHBOARD_TO_STATEMENTS, activity=ACTIVITY, expanded=False,
                 statements=None):
        self.dashboard, self.activity, self.expanded = dashboard, activity, expanded
        self.statements = statements
        self.navigations = []

    def handle(self, route):
        req = route.request
        parts = urlsplit(req.url)
        if req.is_navigation_request():
            self.navigations.append(parts.path + ("?" + parts.query if parts.query else ""))
        if parts.hostname != "global.americanexpress.com":
            return route.abort()
        if parts.path == "/dashboard":
            return route.fulfill(content_type="text/html", body=self.dashboard)
        if parts.path == "/activity":
            return route.fulfill(content_type="text/html", body=self.activity)
        if parts.path == "/activity/statements" and self.statements:
            return route.fulfill(content_type="text/html", body=self.statements)
        if parts.path == "/activity/statements":
            return route.fulfill(content_type="text/html", body=STATEMENTS % {
                "recent": "".join(_button("recent", d) for d in RECENT),
                "older": "".join(_button("older", d) for d in OLDER),
                "expanded": "true" if self.expanded else "false",
                "hidden": "" if self.expanded else "hidden"})
        return route.fulfill(content_type="text/html", body="<p>American Express</p>")


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def open_site(browser):
    contexts = []

    def opener(fake: Site, path: str):
        ctx = browser.new_context()
        contexts.append(ctx)
        ctx.route("**/*", fake.handle)
        pg = ctx.new_page()
        pg.goto(BASE + path)
        fake.navigations.clear()
        return pg
    yield opener
    for ctx in contexts:
        ctx.close()


def test_a_dashboard_in_another_language_reaches_the_statements_by_its_link(open_site):
    fake = Site(dashboard=DASHBOARD_TO_STATEMENTS)
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert fake.navigations == ["/activity/statements?account_key=K0NT0"]


def test_an_activity_link_in_another_language_leads_on_to_the_statements(open_site):
    fake = Site(dashboard=DASHBOARD_TO_ACTIVITY)
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert fake.navigations == ["/activity?inav=menu_myacct_acctsum",
                                "/activity/statements?account_key=K0NT0"]


def test_an_english_dashboard_is_reached_as_it_always_was(open_site):
    """The English words come first, so an English page takes the way it
    always took, though a link to the statements' address is there too."""
    fake = Site(dashboard=DASHBOARD_ENGLISH, activity=ACTIVITY_ENGLISH)
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert fake.navigations == ["/activity?inav=x", "/activity/statements?account_key=K0NT0"]


def test_the_older_statements_open_by_the_part_their_heading_controls(open_site):
    """Every older statement's Download was not found while the section
    stayed collapsed. Its heading is pressed once, and an open one never."""
    fake = Site()
    pg = open_site(fake, "/activity/statements?account_key=K0NT0")
    assert site.goto_documents(pg) is True
    assert pg.evaluate("window.headPresses") == 1
    assert pg.get_attribute("#header-older-statements", "aria-expanded") == "true"
    for date in OLDER:
        assert pg.locator(site._by_test_id("$=", "/%s/download-button" % date)).first.is_visible()
    docs = site.collect_download_docs(pg)
    assert sorted(d.date_text for d in docs) == sorted(RECENT + OLDER)
    site.expand_sections(pg)
    assert pg.evaluate("window.headPresses") == 1


def test_an_open_older_section_is_never_pressed(open_site):
    fake = Site(expanded=True)
    pg = open_site(fake, "/activity/statements?account_key=K0NT0")
    assert site.goto_documents(pg) is True
    assert pg.evaluate("window.headPresses") == 0
    assert pg.get_attribute("#header-older-statements", "aria-expanded") == "true"


# ---------------------------------------------------------------------------
# A single page app, which moves the tab without loading a page
# ---------------------------------------------------------------------------

# Each link is followed by the page's own script. Its address changes after
# the first time given in SLOW and its page is drawn after the second, both
# at once when it has none, and either never when its time is -1. Only the
# main part is drawn anew, so a header stays as it was.
SPA_PAGE = """<!doctype html><meta charset="utf-8"><title>American Express</title>
<header>%(header)s</header>
<main>%(main)s</main>
<script>
window.presses = [];
const PAGES = %(pages)s;
const SLOW = %(slow)s;
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href]');
  if (!a) return;
  e.preventDefault();
  const href = a.getAttribute('href');
  window.presses.push(href);
  const [moves, draws] = SLOW[href] || [0, 0];
  if (moves >= 0) setTimeout(() => history.pushState({}, '', href), moves);
  if (draws >= 0) setTimeout(() => {
    document.querySelector('main').innerHTML = PAGES[href.split('?')[0]] || '';
  }, draws);
});
</script>"""

STATEMENTS_MAIN = "<h1>PDF-Abrechnungen</h1>" + "".join(_button("recent", d) for d in RECENT)
OUR_CARD = "/activity/statements?account_key=K0NT0"
OTHER_CARD = "/activity/statements?account_key=OTHER"


class SPA:
    def __init__(self, pages, header="", slow=None):
        self.pages = dict(pages)
        self.pages.setdefault("/activity/statements", STATEMENTS_MAIN)
        self.header, self.slow = header, slow or {}
        self.navigations = []

    def handle(self, route):
        parts = urlsplit(route.request.url)
        if parts.hostname != "global.americanexpress.com":
            return route.abort()
        return route.fulfill(content_type="text/html", body=SPA_PAGE % {
            "header": self.header, "main": self.pages.get(parts.path, ""),
            "pages": json.dumps(self.pages), "slow": json.dumps(self.slow)})


@pytest.fixture
def quick(monkeypatch):
    """The waits made short, one second after a link where the app gives
    five or six, and four more for its page to come where it gives twenty.
    Each slow page here comes after the first wait and within the second."""
    monkeypatch.setattr(site, "LINK_WAIT_MS", 1000)
    monkeypatch.setattr(site, "PDF_LINK_WAIT_MS", 1000)
    monkeypatch.setattr(site, "ROUTE_MS", 4000)
    monkeypatch.setattr(site, "LIST_WAIT_MS", 1000)


def presses(pg):
    return pg.evaluate("window.presses")


def test_a_link_whose_page_comes_after_the_wait_is_pressed_once(open_site, quick):
    """The review's German dashboard. Its link's page came after the wait,
    and the app pressed the same link again from the dashboard."""
    fake = SPA({"/dashboard": '<a href="%s">Abrechnung(en) runterladen</a>' % OUR_CARD},
               slow={OUR_CARD: [2500, 2500]})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert presses(pg) == [OUR_CARD]


def test_a_link_that_brings_nothing_stops_the_run_with_nothing_more_pressed(open_site, quick):
    """Every caller comes back to goto_documents when it finds no statements,
    and would press the link again, so the run stops at the first press."""
    fake = SPA({"/dashboard": '<a href="%s">Abrechnung(en) runterladen</a>' % OUR_CARD},
               slow={OUR_CARD: [-1, -1]})
    pg = open_site(fake, "/dashboard")
    with pytest.raises(pressing.NoAnswer):
        site.goto_documents(pg)
    assert presses(pg) == [OUR_CARD]


def test_a_slow_english_route_never_leads_to_another_cards_tile(open_site, quick):
    """The review's English dashboard. Statements & Activity was pressed,
    its page came after the wait, and the app pressed a tile of the
    dashboard that leads to another card's statements."""
    fake = SPA({
        "/dashboard": ('<a href="/activity?inav=x">Statements &amp; Activity</a>'
                       '<a href="%s">Card ending 0000 statements</a>' % OTHER_CARD),
        "/activity": ('<a data-testid="goToPdfLinkLg" href="%s">Go to PDF Statements</a>'
                      % OUR_CARD)},
        slow={"/activity?inav=x": [2500, 2500]})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert presses(pg) == ["/activity?inav=x", OUR_CARD]


def test_a_tile_still_drawn_while_the_next_page_loads_is_never_taken(open_site, quick):
    """A single page app can change its address before it draws the page,
    and the dashboard's tiles still show. Where Statements & Activity shows,
    nothing is looked for by its address, on the first look or the next."""
    fake = SPA({
        "/dashboard": ('<a href="/activity?inav=x">Statements &amp; Activity</a>'
                       '<a href="%s">Card ending 0000 statements</a>' % OTHER_CARD),
        "/activity": '<a href="%s">PDF statements</a>' % OUR_CARD},
        slow={"/activity?inav=x": [300, 8000]})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is False
    assert site.goto_documents(pg) is False
    assert presses(pg) == ["/activity?inav=x"]
    # Once the activity page is drawn, its own link is the one taken.
    pg.wait_for_selector("main a[href='%s']" % OUR_CARD, timeout=15000)
    assert site.goto_documents(pg) is True
    assert presses(pg) == ["/activity?inav=x", OUR_CARD]


def test_the_link_pressed_on_the_way_is_never_pressed_again(open_site, quick):
    """A header link stays when a single page app draws the next page. One
    that led to the activity page, and carries the test id of Go to PDF
    Statements too, is not pressed a second time."""
    fake = SPA({"/dashboard": "<h1>Willkommen</h1>", "/activity": "<h1>Kontobewegungen</h1>"},
               header=('<a data-test-id="goToPdfLinkSm" href="/activity?inav=menu">'
                       'Kontobewegungen &amp; Abrechnungen</a>'))
    pg = open_site(fake, "/dashboard")
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the link was pressed already"
    assert presses(pg) == ["/activity?inav=menu"]


def test_a_go_to_pdf_press_that_brings_nothing_stops_the_run(open_site, quick):
    fake = SPA({
        "/dashboard": '<a href="/activity?inav=x">Statements &amp; Activity</a>',
        "/activity": ('<a data-testid="goToPdfLinkLg" href="%s">Go to PDF Statements</a>'
                      % OUR_CARD)},
        slow={OUR_CARD: [-1, -1]})
    pg = open_site(fake, "/dashboard")
    with pytest.raises(pressing.NoAnswer):
        site.goto_documents(pg)
    assert presses(pg) == ["/activity?inav=x", OUR_CARD]


def test_statements_drawn_where_the_address_stays_are_taken_as_come(open_site, quick):
    """Go to PDF Statements answered as it always was, though the address
    were to stay. Its Download buttons show it came."""
    fake = SPA({
        "/dashboard": '<a href="/activity?inav=x">Statements &amp; Activity</a>',
        "/activity": ('<a data-testid="goToPdfLinkLg" href="%s">Go to PDF Statements</a>'
                      % OUR_CARD)},
        slow={OUR_CARD: [-1, 0]})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert presses(pg) == ["/activity?inav=x", OUR_CARD]


# A note pinned over the activity page as American Express showed a tester
# on a first visit to its new Statements & Activity, over Go to PDF
# Statements (#135), with a button that closes it and one that starts a
# tour. Its words here are made up.
WELCOME = ('<div id="welcome" style="position: fixed; inset: 0; background: #fff; z-index: 9">'
           '<p>Welcome to the New Statements &amp; Activity. We have added new ways to see it.</p>'
           '<button type="button" aria-label="Close" '
           'onclick="window.welcomePresses.push(\'close\')">X</button>'
           '<button type="button" onclick="window.welcomePresses.push(\'tour\')">Take a tour</button>'
           '</div>')


def test_a_welcome_note_over_the_link_stops_with_nothing_of_it_pressed(open_site, quick):
    """The note covers Go to PDF Statements, so the link is not pressed, and
    nor is anything on the note. Its close button is not told from its tour
    by anything this app has seen, so the person is told to close it. Once
    it is closed, the way in goes on from the page it stopped on."""
    fake = SPA({
        "/dashboard": '<a href="/activity?inav=x">Statements &amp; Activity</a>',
        "/activity": ('<a data-testid="goToPdfLinkLg" href="%s">Go to PDF Statements</a>'
                      % OUR_CARD) + WELCOME},
        header="<script>window.welcomePresses = [];</script>")
    pg = open_site(fake, "/dashboard")
    with pytest.raises(pressing.Covered) as stop:
        site.goto_documents(pg)
    said = " ".join(stop.value.lines)
    assert "covers the Go to PDF Statements link, so nothing was pressed" in said
    assert "Close it in the browser window yourself" in said
    assert stop.value.facts["fixed"] is True
    assert presses(pg) == ["/activity?inav=x"]
    assert pg.evaluate("window.welcomePresses") == []

    pg.evaluate("document.getElementById('welcome').remove()")
    assert site.goto_documents(pg) is True
    assert presses(pg) == ["/activity?inav=x", OUR_CARD]
    assert pg.evaluate("window.welcomePresses") == []


def test_links_to_two_cards_are_never_pressed(open_site, quick):
    fake = SPA({"/dashboard": (
        '<a href="%s">Abrechnung(en) runterladen</a>'
        '<a href="/activity/statements?account_key=ANDERE">Abrechnung(en) runterladen</a>'
        % OUR_CARD)})
    pg = open_site(fake, "/dashboard")
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the page links to more than one card"
    assert presses(pg) == []


def test_a_link_that_cannot_be_read_stops_the_run_with_nothing_pressed(open_site, quick,
                                                                       monkeypatch):
    """A link to the statements that does not answer could be another
    card's, so none is pressed, rather than the one link that did answer
    being taken as the only one."""
    from paperpull_core.testkit import stall_reads
    fake = SPA({"/dashboard": (
        '<a href="%s">Abrechnung(en) runterladen</a>'
        '<a data-guid="slow" href="/activity/statements?account_key=ANDERE">'
        'Abrechnung(en) runterladen</a>' % OUR_CARD)})
    pg = open_site(fake, "/dashboard")
    stall_reads(monkeypatch, {"slow"}, locator=("is_visible",))
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "a link to the statements could not be read"
    assert presses(pg) == []


def test_a_link_found_by_its_address_passes_by_pay_sign_out_and_a_hidden_copy(open_site,
                                                                              quick):
    """A hidden copy of the link comes first, as American Express keeps one
    for a narrow window, then links that pay, sign out and set up AutoPay,
    the last of them under the statements' own address, and one that says
    nothing. A link that names no card comes after, and names no other
    card."""
    fake = SPA({"/dashboard": (
        '<a href="%(ours)s" style="display:none">Abrechnung(en) runterladen</a>'
        '<a href="/payments?account_key=K0NT0">Rechnung bezahlen</a>'
        '<a href="/logout">Abmelden</a>'
        '<a href="%(ours)s&amp;inav=autopay">Set up AutoPay</a>'
        '<a href="%(ours)s&amp;inav=icon"><svg width="16" height="16"></svg></a>'
        '<a href="%(ours)s">Abrechnung(en) runterladen</a>'
        '<a href="/activity/statements">PDF-Abrechnungen</a>' % {"ours": OUR_CARD})})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert presses(pg) == [OUR_CARD]


def test_an_activity_link_found_by_its_address_passes_by_pay_and_sign_out(open_site, quick):
    fake = SPA({
        "/dashboard": ('<a href="/payments">Rechnung bezahlen</a>'
                       '<a href="/logout">Abmelden</a>'
                       '<a href="/activity?inav=menu_myacct_acctsum">'
                       'Kontobewegungen &amp; Abrechnungen</a>'),
        "/activity": ('<a href="/payments">Rechnung bezahlen</a>'
                      '<a href="%(ours)s" style="display:none">PDF-Abrechnungen</a>'
                      '<a href="%(ours)s">PDF-Abrechnungen</a>' % {"ours": OUR_CARD})})
    pg = open_site(fake, "/dashboard")
    assert site.goto_documents(pg) is True
    assert presses(pg) == ["/activity?inav=menu_myacct_acctsum", OUR_CARD]


# ---------------------------------------------------------------------------
# The older statements' heading, in either language
# ---------------------------------------------------------------------------

SECTION_PAGE = """<!doctype html><meta charset="utf-8"><title>Statements</title>
<main>%(before)s
<section>%(recent)s</section>
%(heading)s
<section id="content-older-statements" hidden>%(older)s</section>
</main>
<script>
window.pressed = [];
for (const el of document.querySelectorAll('[id]')) el.addEventListener('click', () => {
  window.pressed.push(el.id);
  if (!el.dataset.opens) return;
  const open = el.getAttribute('aria-expanded') === 'true';
  for (const h of document.querySelectorAll('[aria-expanded]'))
    if (h.dataset.opens) h.setAttribute('aria-expanded', open ? 'false' : 'true');
  document.getElementById('content-older-statements').hidden = open;
});
</script>"""


def section_page(heading: str, before: str = "") -> str:
    return SECTION_PAGE % {
        "before": before, "heading": heading,
        "recent": "".join(_button("recent", d) for d in RECENT),
        "older": "".join(_button("older", d) for d in OLDER)}


def older_shows(pg) -> bool:
    return all(pg.locator(site._by_test_id("$=", "/%s/download-button" % d)).first.is_visible()
               for d in OLDER)


def test_a_menu_that_opens_something_else_is_never_taken_for_the_older_heading(open_site):
    """Only the heading of the older statements' own part is pressed, not
    the first thing on the page that opens a part."""
    fake = Site(statements=section_page(
        '<button id="older" data-opens="1" aria-controls="content-older-statements"'
        ' aria-expanded="false">Vergangene Abrechnungen</button>',
        before='<button id="menu" aria-controls="menu-konto" aria-expanded="false">Men&uuml;'
               '</button>'))
    pg = open_site(fake, OUR_CARD)
    assert site.goto_documents(pg) is True
    assert pg.evaluate("window.pressed") == ["older"]
    assert older_shows(pg)


def test_an_english_older_heading_is_pressed_as_it_always_was(open_site):
    """On an English page the button named Older Statements is pressed, as
    it always was, though a glyph beside it says it controls the part."""
    fake = Site(statements=section_page(
        '<div><span id="chevron" aria-controls="content-older-statements"'
        ' aria-expanded="false">&#9662;</span>'
        '<button id="older" data-opens="1" aria-expanded="false">Older Statements</button></div>'))
    pg = open_site(fake, OUR_CARD)
    assert site.goto_documents(pg) is True
    assert pg.evaluate("window.pressed") == ["older"]
    assert older_shows(pg)


def test_a_heading_that_is_no_button_is_pressed_by_the_part_it_opens(open_site):
    fake = Site(statements=section_page(
        '<div id="older" data-opens="1" role="heading" aria-level="3" tabindex="0"'
        ' aria-controls="content-older-statements" aria-expanded="false">'
        'Vergangene Abrechnungen</div>'))
    pg = open_site(fake, OUR_CARD)
    assert site.goto_documents(pg) is True
    assert pg.evaluate("window.pressed") == ["older"]
    assert older_shows(pg)


# ---------------------------------------------------------------------------
# A Download button that carries both names
# ---------------------------------------------------------------------------

def _both(testid: str, test_id: str) -> str:
    return ('<button data-testid="%s" data-test-id="%s">Herunterladen</button>'
            % (testid, test_id))


def test_a_statement_named_by_its_second_test_id_is_listed(open_site):
    """The review's button, whose data-testid names no document and whose
    data-test-id is the statement's own. It was dropped from a list that
    was then marked whole."""
    older = "axp-pdf-statements/common/Table/older-statements/%s/download-button" % OLDER[0]
    fake = Site(statements="<main>%s%s</main>" % (
        "".join(_button("recent", d) for d in RECENT), _both("statement-actions", older)))
    pg = open_site(fake, OUR_CARD)
    assert site.goto_documents(pg) is True
    docs = site.collect_download_docs(pg)
    assert sorted(d.date_text for d in docs) == sorted(RECENT + OLDER[:1])
    assert [d.href for d in docs if d.date_text == OLDER[0]] == [older]


def test_a_button_whose_test_ids_name_two_statements_stops_the_list(open_site):
    one, two = ("axp-pdf-statements/common/Table/older-statements/%s/download-button" % d
                for d in OLDER)
    fake = Site(statements="<main>%s%s</main>" % (
        "".join(_button("recent", d) for d in RECENT), _both(one, two)))
    pg = open_site(fake, OUR_CARD)
    with pytest.raises(pressing.Stop) as stop:
        site.collect_download_docs(pg)
    assert stop.value.reason == "a download names two documents"
