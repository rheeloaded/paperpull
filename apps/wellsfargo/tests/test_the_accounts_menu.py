"""Statements & Documents is reached through the top bar's Accounts menu,
and nothing else in that menu is ever pressed (#27).

A tester on PaperPull Server, signed in on the accounts summary, had every
run of 0.56.1 stop at its first step, "the page has no statements and
documents link". The failure file and Diagnose counted no control named
Statements, Documents or Statements & Documents anywhere on the page, shown
or hidden, no menu item and no button named Menu, and five collapsed
buttons. The tester's screenshots showed where the link lives. The top
bar's Accounts button opens a menu of columns, and the link sits in it as
View Statements & Documents. That menu is not in the page until it is
opened, so nothing the app looked for was there to find.

So when no Statements & Documents link shows and no Menu button applies,
the app opens a button whose whole name is Accounts, only one, only while
it says it is closed, and in the menu it builds presses the link by its
whole name and nothing else. The same menu holds Close an Account, Stop
Future Payments, overdraft services and Download Account Activity, so the
pages here hold all of them, each going somewhere of its own when pressed.
A menu that shows no such link is left open with nothing more pressed, and
the stop says what it showed, in counts.

On 0.57.0 the same tester's runs opened the menu, 54 controls showing before
and 83 after, and found a link by the whole name View Statements &
Documents, and both still stopped there. The link's own words, read again
before the press as its aria-label or else its text, were not that whole
name, so its text holds something its name leaves out, a mark hidden from a
screen reader or a word drawn for one alone. The link's words are now read
the ways its name is made, and what it shows still has to name statements
and documents, so a control showing View Check Copies under a name put
there for a screen reader alone, in the usual ways such words are hidden,
is still refused.

Everything here is invented, and real Chromium is driven against made-up
pages served at Wells Fargo's own addresses.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wellsfargo_docs as app_mod
import wellsfargo_site as site
from paperpull_core import failure, pressing

SIGNED_IN = "https://connect.secure.wellsfargo.com"
SUMMARY = SIGNED_IN + "/accounts/start?_x=T0K3N"
EDOCS = SIGNED_IN + "/edocs/documents?_x=T0K3N"

# Every control notes its own press, kept for the page the tab goes to, and
# a control with somewhere to go goes there from a handler, the way Wells
# Fargo's links with no address do.
TRACK = """<script>
window.pressed = JSON.parse(sessionStorage.getItem('pressed') || '[]');
document.addEventListener('click', (e) => {
  const el = e.composedPath().find((n) => n.dataset && n.dataset.name);
  if (!el) return;
  window.pressed.push(el.dataset.name);
  sessionStorage.setItem('pressed', JSON.stringify(window.pressed));
  if (el.dataset.go) location.href = el.dataset.go;
}, true);
</script>"""


def _entry(name, words):
    return ('<li><a role="link" tabindex="0" data-name="%s" data-go="/elsewhere/%s?_x=T0K3N">'
            '%s</a></li>' % (name, name, words))


# The tester's Accounts menu, column by column, every entry going somewhere
# of its own. The column heading Statements & Documents is a heading, not a
# control.
NEIGHBORS = {
    "summary": "Account Summary", "alerts": "Manage Alerts",
    "overdraft": "Add or Change Overdraft Services", "stop-payments": "Stop Future Payments",
    "stop-check": "Stop a Check", "direct-deposit": "Set Up Direct Deposit",
    "recurring": "Recurring Payments", "activity": "Download Account Activity",
    "claims": "Track Claims", "close": "Close an Account",
    "access": "Add or Remove Online Account Access",
    "card-onoff": "Turn Card On or Off", "replace": "Replace My Card",
    "wallets": "Add Cards to Digital Wallets", "activate": "Activate Debit Card",
    "pin": "Change Your PIN", "design": "Design Card", "limits": "Manage Debit Card Limits",
    "verification": "Verification of Deposit", "delivery": "Manage Delivery Preferences",
    "military": "Upload Military Documents",
    "order": "Order Checks", "cashiers": "Cashier&#39;s Check",
    "copies": "View Check Copies", "currency": "Foreign Currency",
}
_FIRST = ("summary", "alerts")
_ACCOUNTS = ("overdraft", "stop-payments", "stop-check", "direct-deposit", "recurring",
             "activity", "claims", "close", "access")
_CARDS = ("card-onoff", "replace", "wallets", "activate", "pin", "design", "limits")
_DOCUMENTS = ("verification", "delivery", "military")
_CHECKS = ("order", "cashiers", "copies", "currency")

# The link in each shape it could be drawn in.
LINKS = {
    "a link with no address": ('<a role="link" tabindex="0" data-name="documents" data-go="%s">'
                               'View Statements &amp; Documents</a>' % EDOCS, "documents"),
    "a link with an address": ('<a href="%s" data-name="documents">View Statements &amp; '
                               'Documents</a>' % EDOCS, "documents"),
    "an entry of a menu": ('<div role="menuitem" tabindex="0" data-name="documents" data-go="%s">'
                           'View Statements &amp; Documents</div>' % EDOCS, "documents"),
    "the section's own name": ('<a role="link" tabindex="0" data-name="documents" data-go="%s">'
                               'Statements &amp; Documents</a>' % EDOCS, "documents"),
}


def _menu(link=LINKS["a link with no address"][0]):
    def column(heading, names, first=""):
        return '<section><h3>%s</h3><ul>%s%s</ul></section>' % (
            heading, first, "".join(_entry(n, NEIGHBORS[n]) for n in names))
    return ('<section><ul>%s</ul></section>' % "".join(_entry(n, NEIGHBORS[n]) for n in _FIRST)
            + column("Manage Accounts", _ACCOUNTS) + column("Manage Cards", _CARDS)
            + column("Statements &amp; Documents", _DOCUMENTS,
                     first="<li>%s</li>" % link if link else "")
            + column("Checks &amp; Currency", _CHECKS))


ACCOUNTS = ('<button data-name="accounts" aria-expanded="false" '
            'aria-controls="accounts-panel">Accounts</button>')

PAGE = """<!doctype html><meta charset="utf-8"><title>Account Summary</title>
<header><nav aria-label="Main">%(accounts)s
<button data-name="brokerage">Brokerage</button>
<button data-name="transfer" aria-expanded="false">Transfer &amp; Pay</button>
<button data-name="plan" aria-expanded="false">Plan &amp; Learn</button>
<button data-name="security" aria-expanded="false">Security &amp; Support</button>
<button data-name="welcome" aria-expanded="false">Welcome Dana</button>%(extra)s
</nav><div id="accounts-panel"></div></header>
<main><h1>Account Summary</h1>
<button data-name="cash" aria-expanded="true">Cash Accounts</button>
<p>Everyday Checking ...1111</p><button data-name="more" aria-label="More options">...</button>
</main>
<script>
const MENU = %(menu)s;
// The menu is built only once it is opened, a moment after the press, and
// taken away again when it is closed.
for (const b of document.querySelectorAll('[aria-controls=accounts-panel]'))
  b.addEventListener('click', () => {
    const panel = document.getElementById('accounts-panel');
    const open = b.getAttribute('aria-expanded') === 'true';
    b.setAttribute('aria-expanded', open ? 'false' : 'true');
    if (open) { panel.innerHTML = ''; return; }
    setTimeout(() => { panel.innerHTML = MENU; }, 300);
  });
</script>""" + TRACK

EDOCS_PAGE = """<!doctype html><meta charset="utf-8"><title>Statements</title>
<main><form><a role="link" tabindex="0">Statement 09/30/26 (123K, PDF)</a></form></main>"""


def _page(accounts=ACCOUNTS, menu=None, extra=""):
    return PAGE % {"accounts": accounts, "extra": extra,
                   "menu": json.dumps(_menu() if menu is None else menu)}


class Site:
    """Wells Fargo's addresses, served from here, with every address the
    tab is sent to kept."""

    def __init__(self, landing: str):
        self.landing = landing
        self.navigations = []

    def handle(self, route):
        req = route.request
        parts = urlsplit(req.url)
        if req.is_navigation_request():
            self.navigations.append(req.url)
        if parts.hostname not in ("connect.secure.wellsfargo.com", "www.wellsfargo.com"):
            return route.abort()
        if parts.path == "/accounts/start":
            return route.fulfill(content_type="text/html", body=self.landing)
        if parts.path == "/edocs/documents":
            return route.fulfill(content_type="text/html", body=EDOCS_PAGE)
        return route.fulfill(content_type="text/html", body="<p>Wells Fargo</p>" + TRACK)


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

    def opener(fake: Site):
        ctx = browser.new_context()
        contexts.append(ctx)
        ctx.route("**/*", fake.handle)
        pg = ctx.new_page()
        pg.goto(SUMMARY)
        fake.navigations.clear()
        return pg
    yield opener
    for ctx in contexts:
        ctx.close()


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(site, "_SHOW_MS", 2000)
    monkeypatch.setattr(site, "_MENU_SHOW_MS", 2000)


def _pressed(pg):
    return pg.evaluate("JSON.parse(sessionStorage.getItem('pressed') || '[]')")


def _stops(pg):
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    return stop.value


# -- the link in the menu the Accounts button opens ------------------------------

@pytest.mark.parametrize("shape", list(LINKS))
def test_the_link_the_accounts_menu_builds_is_pressed_and_nothing_else(open_site, shape):
    link, name = LINKS[shape]
    fake = Site(_page(menu=_menu(link)))
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert fake.navigations == [EDOCS], fake.navigations
    assert _pressed(pg) == ["accounts", name], _pressed(pg)
    assert site._on_edocs(pg.url)


def test_the_way_says_the_accounts_menu_showed_the_link(open_site):
    fake = Site(_page())
    pg = open_site(fake)
    way = {}
    assert site.goto_documents(pg, way=way) is True
    assert way["accounts_buttons_shown"] == 1
    assert way["accounts_menu_pressed"] is True
    assert way["menu_pressed"] is False
    assert way["documents_link_shown"] is True
    assert way["controls_shown_before"] >= 6


def test_an_accounts_menu_with_no_such_link_stops_with_nothing_else_pressed(open_site):
    fake = Site(_page(menu=_menu(link="")))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert stop.step == "open the statements page"
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []
    facts = stop.facts
    assert facts["accounts_buttons_shown"] == 1
    assert facts["accounts_menu_pressed"] is True and facts["menu_pressed"] is False
    assert facts["documents_link_shown"] is False
    assert facts["accounts_menu_said_open"] is True
    # What the opened menu showed, in counts. Its 25 entries came, none
    # names statements and one names documents (Upload Military Documents).
    assert facts["controls_shown_after"] - facts["controls_shown_before"] == len(NEIGHBORS)
    assert facts["statements_controls_shown"] == 0
    assert facts["documents_controls_shown"] == 1
    # Nothing was closed, the menu still shows for the failure file.
    assert pg.get_attribute("[data-name=accounts]", "aria-expanded") == "true"
    assert pg.locator("#accounts-panel [data-name=close]").is_visible()


@pytest.mark.parametrize("words", [
    "View Statements &amp; Documents settings", "Manage Statements &amp; Documents",
    "View Statements", "Statements &amp; Documents Delivery Preferences",
    "View Statements &amp; Documents and Close an Account"])
def test_a_link_with_more_or_fewer_words_in_the_accounts_menu_is_never_pressed(open_site, words):
    link = '<a role="link" tabindex="0" data-name="wrong" data-go="%s">%s</a>' % (EDOCS, words)
    fake = Site(_page(menu=_menu(link)))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


def test_close_an_account_is_refused_even_were_the_name_rule_to_take_it(open_site, monkeypatch):
    """Two rules stand between the menu and a wrong press. Were the link's
    name rule ever to take Close an Account, the guard over the link's
    words refuses it, since it names no document."""
    monkeypatch.setattr(site, "DOCUMENTS_LINK_RE", re.compile(r"^\s*close an account\s*$", re.I))
    fake = Site(_page(menu=_menu(link="")))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert stop.facts["documents_link_shown"] is True
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


def test_the_failure_file_keeps_what_the_accounts_menu_showed(open_site, tmp_path):
    fake = Site(_page(menu=_menu(link="")))
    pg = open_site(fake)
    stop = _stops(pg)
    out = failure.write_failure(tmp_path, "run", stop.step, stop.reason, page=pg,
                                provider="Wells Fargo", extra=stop.facts, say=lambda *a: None)
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    assert report["reason"] == "the accounts menu has no statements and documents link"
    # Every fact of the stop is one the file keeps, none dropped as a word
    # it may not carry.
    assert report["extra"] == stop.facts, (report["extra"], stop.facts)
    counts = report["page"]["counts"]
    assert counts["documents_controls"] == 1 and counts["statements_controls"] == 0
    assert counts["links_with_no_href"] == len(NEIGHBORS)


# -- what is never pressed ----------------------------------------------------------

def test_an_accounts_button_that_says_it_is_open_is_never_pressed(open_site):
    """Pressing an open menu closes it."""
    fake = Site(_page(accounts=ACCOUNTS.replace('"false"', '"true"')))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the page has no statements and documents link"
    assert stop.facts["accounts_buttons_shown"] == 1
    assert stop.facts["accounts_menu_pressed"] is False
    assert _pressed(pg) == [] and fake.navigations == []


def test_an_accounts_button_that_says_nothing_of_a_menu_is_never_pressed(open_site):
    fake = Site(_page(accounts=ACCOUNTS.replace(' aria-expanded="false"', "")))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the page has no statements and documents link"
    assert stop.facts["accounts_menu_pressed"] is False
    assert _pressed(pg) == [] and fake.navigations == []


@pytest.mark.parametrize("label", ["Accounts menu", "My Accounts", "Account", "Close Accounts",
                                   "Accounts &amp; Transfers", "All accounts summary"])
def test_a_button_whose_name_is_more_than_accounts_is_never_pressed(open_site, label):
    fake = Site(_page(accounts=ACCOUNTS.replace(">Accounts<", ">%s<" % label)))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the page has no statements and documents link"
    assert stop.facts["accounts_buttons_shown"] == 0
    assert _pressed(pg) == [] and fake.navigations == []


def test_a_button_named_accounts_only_for_a_screen_reader_is_never_pressed(open_site):
    """Its name read again from what it says of itself is not Accounts."""
    button = ('<button data-name="accounts" aria-expanded="false" aria-controls="accounts-panel" '
              'aria-labelledby="said">Transfer money</button><span id="said" hidden>Accounts</span>')
    fake = Site(_page(accounts=button))
    pg = open_site(fake)
    assert pg.get_by_role("button", name=site.ACCOUNTS_BUTTON_RE).count() == 1
    stop = _stops(pg)
    assert stop.reason == "the page has no statements and documents link"
    assert stop.facts["accounts_buttons_shown"] == 1
    assert stop.facts["accounts_menu_pressed"] is False
    assert _pressed(pg) == [] and fake.navigations == []


def test_two_accounts_buttons_open_neither(open_site):
    second = ACCOUNTS.replace('data-name="accounts"', 'data-name="accounts-two"')
    fake = Site(_page(extra=second))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the page has no statements and documents link"
    assert stop.facts["accounts_buttons_shown"] == 2
    assert _pressed(pg) == [] and fake.navigations == []


@pytest.mark.parametrize("expanded", ["false", "true"])
def test_with_a_menu_button_the_accounts_button_is_never_pressed(open_site, expanded):
    """A narrow window's Menu is opened as it was, and the Accounts menu
    is not tried after it. A Menu that says it is open is not pressed, and
    neither is Accounts on a page like that, which this app does not know."""
    menu = ('<button data-name="menu" aria-expanded="%s" onclick="this.setAttribute('
            '\'aria-expanded\', \'true\'); document.getElementById(\'drawer\').hidden = false;">'
            'Menu</button><div id="drawer" %s><a role="link" tabindex="0" data-name="help">'
            'Help</a></div>') % (expanded, "hidden" if expanded == "false" else "")
    fake = Site(_page(extra=menu))
    pg = open_site(fake)
    stop = _stops(pg)
    opened = expanded == "false"
    assert stop.reason == ("the menu has no statements and documents link" if opened
                           else "the page has no statements and documents link")
    assert stop.facts["menu_pressed"] is opened
    assert stop.facts["menu_button_shown"] is True
    assert "accounts_menu_pressed" not in stop.facts
    assert _pressed(pg) == (["menu"] if opened else []), _pressed(pg)
    assert fake.navigations == []


def test_a_link_named_for_a_screen_reader_alone_is_never_pressed(open_site):
    """Its own words, read again before the press, are those of View Check
    Copies, which the guard alone would let through."""
    link = ('<a role="link" tabindex="0" data-name="copies-too" data-go="/elsewhere/copies" '
            'aria-labelledby="named">View Check Copies</a>'
            '<span id="named" hidden>View Statements &amp; Documents</span>')
    fake = Site(_page(menu=_menu(link)))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert stop.facts["documents_link_shown"] is True
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


def test_an_accounts_button_under_a_cover_is_not_pressed_and_not_said_pressed(open_site):
    """A press that stops the run leaves whether it was made unknown, not
    a no."""
    cover = ('<div data-name="cover" style="position:fixed;top:0;left:0;width:100%;'
             'height:300px;background:#fff"></div>')
    fake = Site(_page(extra=cover))
    pg = open_site(fake)
    way = {}
    with pytest.raises(pressing.Covered):
        site.goto_documents(pg, way=way)
    assert way["accounts_buttons_shown"] == 1
    assert way["accounts_menu_pressed"] is None
    assert _pressed(pg) == [] and fake.navigations == []


def test_a_link_that_shows_already_is_pressed_with_the_accounts_menu_left_closed(open_site):
    link = ('<a role="link" tabindex="0" data-name="documents" data-go="%s">'
            'View Statements &amp; Documents</a>' % EDOCS)
    fake = Site(_page().replace("<main>", "<main>" + link))
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert _pressed(pg) == ["documents"], _pressed(pg)


def test_only_the_links_whole_name_and_the_buttons_whole_name_are_taken():
    """Every entry of the tester's Accounts menu, by its words alone. Only
    the link reads as the documents link, and nothing reads as the Accounts
    button but Accounts."""
    words = [w.replace("&#39;", "'") for w in NEIGHBORS.values()] + [
        "Manage Accounts", "Manage Cards", "Checks & Currency", "Brokerage", "Transfer & Pay",
        "Plan & Learn", "Security & Support", "Welcome Dana", "Cash Accounts"]
    for w in words:
        assert not site.DOCUMENTS_LINK_RE.match(w), w
        assert not site.is_accounts_button(w), w
    for w in ("View Statements & Documents", "  view statements and documents ",
              "Statements & Documents", "Statement and Documents"):
        assert site.DOCUMENTS_LINK_RE.match(w), w
        assert site.is_safe_control(w), w
        assert not site.is_accounts_button(w), w
    assert site.is_accounts_button("Accounts") and site.is_accounts_button("  accounts ")
    # The guard over every press refuses these by their own words too.
    for w in ("Close an Account", "Close Account", "Stop a Check", "Stop Future Payments",
              "Add or Change Overdraft Services", "Manage Delivery Preferences"):
        assert not site.is_safe_control(w), w
    # And by the words that refuse a control whatever else it says.
    for w in ("Close an Account", "Close a account", "Stop a Check", "stop check"):
        assert site.FORBIDDEN_CONTROL_RE.search(w), w
        assert not site.is_safe_control("View statement, " + w), w


# -- the link's own words, read the ways its name is made (0.57.0) ------------------

# How a site draws words for a screen reader alone, a pixel wide and cut away.
SR_ONLY = ("position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);"
           "white-space:nowrap")
NAME = "View Statements &amp; Documents"


def _link(inner, attrs="", name="documents", go=EDOCS):
    return ('<a role="link" tabindex="0" data-name="%s" data-go="%s"%s>%s</a>'
            % (name, go, attrs, inner))


def _wrong(inner, attrs=""):
    return _link(inner, attrs, name="wrong", go="/elsewhere/wrong?_x=T0K3N")


# The link with the whole name View Statements & Documents and text that,
# read alone, holds more, each the way a site draws a mark hidden from a
# screen reader or a word for one alone. Each shows View Statements &
# Documents.
WHOLE_BY_NAME = {
    "a mark hidden from a screen reader": _link(
        NAME + '<span aria-hidden="true"> &#8250;</span>'),
    "an icon's word hidden from a screen reader": _link(
        '<span aria-hidden="true" class="icon">chevron_right</span>' + NAME),
    "and for a screen reader, the ampersand hidden from one": _link(
        'View Statements <span aria-hidden="true">&amp;</span><span style="%s">and</span> '
        'Documents' % SR_ONLY),
    "labeled by its own part, with a note for a screen reader": _link(
        '<span id="own-name">%s</span><span style="%s"> opens the page</span>' % (NAME, SR_ONLY),
        ' aria-labelledby="own-name"'),
}
# Characters of no width, which its name leaves out and its text keeps.
NO_WIDTH = {
    "a space of no width": _link("View Statements &amp;&#8203; Documents"),
    "a soft hyphen": _link("View State&shy;ments &amp; Docu&shy;ments"),
}


@pytest.mark.parametrize("shape", list(WHOLE_BY_NAME))
def test_a_link_whose_text_holds_more_than_its_name_is_pressed(open_site, shape):
    """The 0.57.0 round. The menu opened and the link showed by its whole
    name, and its text, read again alone, refused it in both runs. Read the
    ways its name is made, it is the link."""
    fake = Site(_page(menu=_menu(WHOLE_BY_NAME[shape])))
    pg = open_site(fake)
    way = {}
    assert site.goto_documents(pg, way=way) is True
    assert fake.navigations == [EDOCS], fake.navigations
    assert _pressed(pg) == ["accounts", "documents"], _pressed(pg)
    read = way["documents_link_read"]
    assert read["taken"] is True and read["text_is_whole"] is False, read
    assert read["seen_names_both"] is True and read["words_refused"] is False, read


@pytest.mark.parametrize("shape", list(NO_WIDTH))
def test_a_link_whose_text_holds_characters_of_no_width_is_pressed(open_site, shape):
    """The 0.57.0 safety review. Found by its whole name, which leaves such
    characters out, it is read whole once they are taken out of its words
    too."""
    fake = Site(_page(menu=_menu(NO_WIDTH[shape])))
    pg = open_site(fake)
    way = {}
    assert site.goto_documents(pg, way=way) is True
    assert fake.navigations == [EDOCS], fake.navigations
    assert _pressed(pg) == ["accounts", "documents"], _pressed(pg)
    assert way["documents_link_read"]["text_is_whole"] is True


def test_the_made_up_menu_counts_as_the_testers_menu_did(open_site):
    """The failure file of 0.57.0 counted one control naming statements, two
    naming documents and none named Statements & Documents alone, with the
    menu open. The made-up menu with such a link counts the same."""
    fake = Site(_page(menu=_menu(WHOLE_BY_NAME["a mark hidden from a screen reader"])))
    pg = open_site(fake)
    assert site._open_accounts_menu(pg, {}) is not None
    pg.wait_for_selector("#accounts-panel [data-name=documents]")
    counts = pg.evaluate(failure._PAGE_STATE_JS)["counts"]
    assert counts["statements_controls"] == 1 and counts["documents_controls"] == 2, counts
    assert counts["statements_and_documents_controls"] == 0, counts
    assert counts["links"] == 0, counts


@pytest.mark.parametrize("inner, attrs", [
    # A label naming the link on a control holding Close an Account, which a
    # check of the label alone took.
    ("Close an Account", ' aria-label="%s"' % NAME),
    # The whole name for a screen reader, and words closing an account
    # hidden from one.
    (NAME + '<span aria-hidden="true"> Close an Account</span>', ""),
    # A label naming the link on a control whose style draws Close an
    # Account.
    ('<span class="drawn"></span><style>.drawn::before { content: "Close an Account"; }</style>',
     ' aria-label="%s"' % NAME),
])
def test_a_link_any_of_whose_words_the_guard_refuses_is_never_pressed(open_site, inner, attrs):
    fake = Site(_page(menu=_menu(_wrong(inner, attrs))))
    pg = open_site(fake)
    stop = _stops(pg)
    # Found by the whole name in the menu, which is left open.
    assert stop.facts["documents_link_shown"] is True
    assert pg.get_by_role("link", name=site.DOCUMENTS_LINK_RE).count() == 1
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert stop.facts["documents_link_read"]["words_refused"] is True
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


def test_a_link_whose_label_says_something_else_is_never_pressed(open_site):
    """Named by a part of its own, while its label says View Check Copies.
    A control with a label takes its label, whatever its other words say."""
    inner = '<span id="own-name">%s</span>' % NAME
    fake = Site(_page(menu=_menu(_wrong(inner, ' aria-labelledby="own-name" '
                                               'aria-label="View Check Copies"'))))
    pg = open_site(fake)
    stop = _stops(pg)
    # Found by the whole name in the menu, which is left open.
    assert stop.facts["documents_link_shown"] is True
    assert pg.get_by_role("link", name=site.DOCUMENTS_LINK_RE).count() == 1
    assert stop.reason == "the accounts menu has no statements and documents link"
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


# Words for a screen reader alone, each way left out of what a control
# shows on its own, before the words it shows. Each is the only one of
# those ways that applies to its words.
UNSEEN = {
    "drawn a pixel wide": '<span style="display:inline-block;width:1px;height:1px;'
                          'overflow:hidden;white-space:nowrap">%s</span>',
    "cut away": '<span style="position:absolute;clip:rect(0 0 0 0);white-space:nowrap">%s</span>',
    "cut away by a path": '<span style="clip-path:inset(50%%)">%s</span>',
    "outside its own box": '<span style="position:absolute;left:-10000px">%s</span>',
    "see-through": '<span style="opacity:0">%s</span>',
    "in a color of no strength": '<span style="color:transparent">%s</span>',
}
# What such a control shows, hidden from a screen reader. The space before
# it keeps the words apart, so with any one of the ways above not applied,
# what it shows names statements and documents, and only that way refuses it.
SHOWS_COPIES = ' <span aria-hidden="true">View Check Copies</span>'


@pytest.mark.parametrize("how", list(UNSEEN))
def test_a_control_showing_view_check_copies_named_for_a_screen_reader_is_never_pressed(
        open_site, how):
    """Its name, read the way a screen reader reads it, is the link's whole
    name, and it shows View Check Copies, which names no statements."""
    inner = UNSEEN[how] % NAME + SHOWS_COPIES
    fake = Site(_page(menu=_menu(_wrong(inner))))
    pg = open_site(fake)
    stop = _stops(pg)
    # Found by the whole name in the menu, which is left open.
    assert stop.facts["documents_link_shown"] is True
    assert pg.get_by_role("link", name=site.DOCUMENTS_LINK_RE).count() == 1
    assert stop.reason == "the accounts menu has no statements and documents link"
    read = stop.facts["documents_link_read"]
    assert read["said_is_whole"] is True and read["seen_names_both"] is False, read
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


@pytest.mark.parametrize("link", [
    # Named by a part of its own that is not drawn.
    _wrong('Statements of Documents Archive<span id="own-name" hidden>%s</span>' % NAME,
           ' aria-labelledby="own-name"'),
    # Named by words of the page outside it.
    _wrong("Older Statements and Tax Documents", ' aria-labelledby="named"')
    + '<span id="named">%s</span>' % NAME,
])
def test_a_link_labelled_by_words_it_does_not_show_as_its_own_is_never_pressed(open_site, link):
    """What it shows names statements and documents, and is not the link."""
    fake = Site(_page(menu=_menu(link)))
    pg = open_site(fake)
    stop = _stops(pg)
    # Found by the whole name in the menu, which is left open.
    assert stop.facts["documents_link_shown"] is True
    assert pg.get_by_role("link", name=site.DOCUMENTS_LINK_RE).count() == 1
    assert stop.reason == "the accounts menu has no statements and documents link"
    read = stop.facts["documents_link_read"]
    assert read["labelled_by"] is True and read["labelled_by_itself"] is False, read
    assert read["seen_names_both"] is True, read
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


def test_the_failure_file_says_how_the_links_words_read(open_site, tmp_path):
    inner = UNSEEN["drawn a pixel wide"] % NAME + SHOWS_COPIES
    fake = Site(_page(menu=_menu(_wrong(inner))))
    pg = open_site(fake)
    stop = _stops(pg)
    out = failure.write_failure(tmp_path, "run", stop.step, stop.reason, page=pg,
                                provider="Wells Fargo", extra=stop.facts, say=lambda *a: None)
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    # Every fact is kept, the file keeps twenty of them at most.
    assert len(stop.facts) <= 20 and report["extra"] == stop.facts, (report["extra"], stop.facts)
    read = report["extra"]["documents_link_read"]
    assert set(read) == {
        "words_read", "label_given", "labelled_by", "labelled_by_itself", "style_given",
        "label_is_whole",
        "text_is_whole", "said_is_whole", "labelled_is_whole", "seen_names_both",
        "words_refused", "hidden_elements", "text_length", "said_length", "seen_length", "taken"}
    assert read["words_read"] is True and read["label_given"] is False
    assert read["text_is_whole"] is False and read["said_is_whole"] is True
    assert read["seen_names_both"] is False and read["taken"] is False
    assert read["hidden_elements"] == 1
    assert read["said_length"] == len("View Statements & Documents")
    # Lengths and yes or no, and no word of the link in the file.
    raw = Path(out).read_text(encoding="utf-8")
    assert "Check Copies" not in raw and "View Statements" not in raw


def test_a_link_under_a_cover_stops_with_how_it_was_reached(open_site):
    cover = ('<div data-name="cover" style="position:fixed;top:0;left:0;width:100%;'
             'height:100%;background:#fff"></div>')
    fake = Site(_page(menu=_menu() + cover))
    pg = open_site(fake)
    with pytest.raises(pressing.Covered) as stop:
        site.goto_documents(pg)
    facts = stop.value.facts
    assert facts["accounts_menu_pressed"] is True and facts["documents_link_shown"] is True
    assert facts["documents_link_read"]["taken"] is True
    assert "over_it" in facts
    assert _pressed(pg) == ["accounts"], _pressed(pg)
    assert fake.navigations == []


@pytest.mark.parametrize("does, tabs", [("window.open('%s')" % EDOCS, 1), ("", 0)])
def test_a_link_that_does_not_open_the_page_in_this_tab_says_what_it_did(
        open_site, monkeypatch, does, tabs):
    monkeypatch.setattr(site, "_OPEN_MS", 2000)
    link = ('<a role="link" tabindex="0" data-name="documents" onclick="%s">%s</a>'
            % (does, NAME))
    fake = Site(_page(menu=_menu(link)))
    pg = open_site(fake)
    stop = _stops(pg)
    assert stop.reason == "the link did not open the statements page"
    assert stop.facts["tabs_opened"] == tabs and stop.facts["address_changed"] is False
    assert stop.facts["documents_link_read"]["taken"] is True
    assert _pressed(pg) == ["accounts", "documents"], _pressed(pg)


def test_an_accounts_button_another_comes_before_is_not_pressed_for_it(open_site, monkeypatch):
    """The 0.57.0 release review's MINOR. The button was the first of those
    named Accounts by its place, found again at the press, so one drawn
    before it in between took its place. It has to be the only one that
    shows, at every read and at the press, or nothing is pressed."""
    fake = Site(_page())
    pg = open_site(fake)
    counted = site._controls_shown

    def and_another_comes(page):
        page.evaluate("""() => {
          const b = document.createElement('button');
          b.dataset.name = 'accounts-two';
          b.setAttribute('aria-expanded', 'false');
          b.textContent = 'Accounts';
          document.querySelector('nav').prepend(b);
        }""")
        return counted(page)
    monkeypatch.setattr(site, "_controls_shown", and_another_comes)
    way = {}
    with pytest.raises(pressing.Stop):
        site.goto_documents(pg, way=way)
    assert way["accounts_buttons_shown"] == 1
    assert _pressed(pg) == [], _pressed(pg)
    assert fake.navigations == []


# -- Diagnose -----------------------------------------------------------------------

def _config(tmp_path):
    example = Path(app_mod.__file__).parent / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return cfg


def _diagnose(pg, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "survey", lambda page, dwell_ms=4000, max_follow=6: {
        "pages": [site._page_summary(page)], "responses": [], "followed": max_follow})
    monkeypatch.setattr(site, "expand_all", lambda page: None)
    monkeypatch.setattr(site, "scroll_full_page", lambda page, *a, **k: None)

    def page(self):
        self._work_page = pg
        return pg
    monkeypatch.setattr(app_mod.App, "page", page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    assert app_mod.main(["--config", str(_config(tmp_path)), "--diagnose"]) == 0
    out = tmp_path / "out"
    (detailed,) = sorted(out.rglob("diagnose-documents.json"))
    (survey,) = sorted(out.rglob("survey-diagnose-*.json"))
    return (json.loads(detailed.read_text(encoding="utf-8")),
            json.loads(survey.read_text(encoding="utf-8")))


def test_diagnose_says_the_accounts_menu_showed_no_link(open_site, tmp_path, monkeypatch):
    fake = Site(_page(menu=_menu(link="")))
    pg = open_site(fake)
    info, report = _diagnose(pg, tmp_path, monkeypatch)
    assert info["stopped"]["reason"] == "the accounts menu has no statements and documents link"
    assert info["documents_link"]["way"]["accounts_menu_pressed"] is True
    assert info["documents_link"]["way"]["documents_link_shown"] is False
    facts = report["extra"]["stopped"]["facts"]
    assert facts["accounts_menu_pressed"] is True and facts["documents_link_shown"] is False
    assert facts["documents_controls_shown"] == 1
    # The survey counts the page with the menu still open.
    assert report["page"]["counts"]["links_with_no_href"] == len(NEIGHBORS)
    assert _pressed(pg) == ["accounts"] and fake.navigations == []


def test_diagnose_says_the_accounts_menu_opened_the_documents(open_site, tmp_path, monkeypatch):
    fake = Site(_page())
    pg = open_site(fake)
    info, report = _diagnose(pg, tmp_path, monkeypatch)
    assert info["documents_page_opened"] is True
    assert info["documents_link"]["way"]["accounts_menu_pressed"] is True
    assert report["extra"]["way"]["accounts_menu_pressed"] is True
    assert report["extra"]["way"]["documents_link_shown"] is True
    # How the link's words read, in both files.
    assert info["documents_link"]["way"]["documents_link_read"]["taken"] is True
    assert report["extra"]["way"]["documents_link_read"]["taken"] is True
    assert "stopped" not in report["extra"]
    assert _pressed(pg) == ["accounts", "documents"] and fake.navigations == [EDOCS]
