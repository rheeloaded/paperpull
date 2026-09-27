"""A run that starts anywhere in online banking still reaches the vendor.

Two pilots, on 0.34.1 and on 0.37.0, asked the vendor for a statement date
it does not list and tried nothing else. Each failure file's request census
shows the bank's documents page loading, then exactly one press of the
View Documents button. The capture made that press, so discovery never
opened the vendor's tab at all (#35).

The link named "View documents" sits in online banking's sidebar and only
moves the tab to the documents page. goto_documents takes any page
carrying it for the documents page, so a run started on the overview
pressed the link, saw no tab open, gave up, and discovery read the bank's
own page. There it found no statement named by its own date, only a
control it dated from whatever was printed near it, so nothing was
retired and a made up date was queued. The capture after it started on
the page the link had reached, pressed the button, and found the whole
list without that date on it.

The documents page asks for the member's accounts as it arrives, and the
button signs on to the vendor with one of them, so the button is pressed
only once that call has answered and the page has settled.

Only a tab the button newly opens is read. A statements tab an earlier
run left open is closed before the press, since its list outlives its
session and a bank that opens its vendor into a named window would send
the new sign-on into it instead of a new tab.

The bank and the vendor here are invented pages served to a real browser
under the real host names, so the host checks run as they do for a member.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_site as site

OVERVIEW = "https://digitalbanking.golden1.com/accounts/overview"
VENDOR_URL = "https://ebank.hepsiian.com/statements"
ACCOUNTS_PATH = "/d3rest/v6/external/fiserv/edocs-sso/members"


def bank_html(accounts_after_ms=100, inert_ms=None, opens=True, leave_to="",
              works_after_answer_ms=0):
    """The overview, with the sidebar link and no button. The link swaps
    the view for the documents page, the way the bank's single page app
    does, and that page asks for the member's accounts after
    `accounts_after_ms`. Its button opens the vendor in a new tab, but only
    `works_after_answer_ms` after the accounts have answered, or with no
    accounts call at all (`accounts_after_ms` None) once `inert_ms` has
    passed. A date is printed on both views, so a read of the bank's own
    page could make up a statement. `leave_to` makes the link send the tab
    to another site."""
    return """<html><body>
  <nav><a href="#" id="side">View documents</a></nav>
  <main id="view"><h1>Accounts</h1><p>Balances as of 01/17/2024</p></main>
  <script>
    window.ready = false;
    const ACCOUNTS_AFTER_MS = %(accounts)s, INERT_MS = %(inert)s,
          OPENS = %(opens)s, LEAVE_TO = %(leave)s, WORKS_AFTER = %(works_after)s;
    function pressVendor() {
      if (window.pressed) window.pressed();
      if (window.ready && OPENS) window.open(%(vendor)s, '_blank');
    }
    document.getElementById('side').addEventListener('click', e => {
      e.preventDefault();
      if (LEAVE_TO) { location.href = LEAVE_TO; return; }
      history.pushState({}, '', '/accounts/documents');
      document.getElementById('view').innerHTML =
        '<h1>Documents</h1><p>Updated 01/17/2024</p>' +
        '<button id="vendor">View Documents</button>';
      document.getElementById('vendor').addEventListener('click', pressVendor);
      if (ACCOUNTS_AFTER_MS !== null) {
        setTimeout(() => fetch(%(accounts_path)s).then(r => r.json())
                           .then(() => setTimeout(() => { window.ready = true; }, WORKS_AFTER)),
                   ACCOUNTS_AFTER_MS);
      } else {
        setTimeout(() => { window.ready = true; }, INERT_MS || 0);
      }
    });
  </script>
</body></html>""" % {"accounts": json.dumps(accounts_after_ms), "inert": json.dumps(inert_ms),
                     "opens": json.dumps(opens), "leave": json.dumps(leave_to),
                     "works_after": json.dumps(works_after_answer_ms),
                     "vendor": json.dumps(VENDOR_URL), "accounts_path": json.dumps(ACCOUNTS_PATH)}


VENDOR = """<html><body><main>
  <h2>Statements</h2>
  <a href="#">Current Statement</a>
  <a href="#">04/30/24</a><a href="#">03/31/24</a><a href="#">02/29/24</a>
</main></body></html>"""

# What a vendor tab an earlier run left open still shows.
OLD_VENDOR = """<html><body><main>
  <h2>Statements</h2><a href="#">01/31/24</a>
</main></body></html>"""

# Another site with a button of the same name, which opens a third.
OFFHOST = """<html><body>
  <button onclick="window.pressed && window.pressed();
                   window.open('https://odd.example.test/x', '_blank')">View Documents</button>
</body></html>"""


class _Browser:
    def __init__(self, ctx, pages, presses):
        self.ctx, self.pages, self.presses = ctx, pages, presses

    def start(self, bank=None):
        """The bank's tab, on the overview, with `bank` as its page."""
        self.pages["digitalbanking.golden1.com"] = bank or bank_html()
        pg = self.ctx.new_page()
        pg.expose_function("pressed", lambda: self.presses.append(1))
        pg.goto(OVERVIEW)
        return pg


@pytest.fixture()
def browser(monkeypatch):
    # Adopting the vendor's tab remembers it and its host for the run. Kept
    # to this test so nothing it adds is seen by another.
    monkeypatch.setattr(site, "_VENDOR_HOSTS_SEEN", set())
    monkeypatch.setattr(site, "_ADOPTED_TABS", [], raising=False)
    monkeypatch.setattr(site, "_ARRIVALS", {})
    monkeypatch.setattr(site, "_LAST_OPEN", {})
    monkeypatch.setattr(site, "BILLING_URL", site.BILLING_CANDIDATES[0])
    monkeypatch.setattr(site, "ALLOWED_HOSTS", set(site.ALLOWED_HOSTS))
    monkeypatch.setattr(site, "scroll_full_page", lambda p, *a, **k: None)
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        chromium = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = chromium.new_context()
    pages = {("ebank.hepsiian.com", "/statements"): VENDOR,
             ("ebank.hepsiian.com", "/old"): OLD_VENDOR,
             "offhost.example.test": OFFHOST,
             "odd.example.test": "<html><body><p>odd</p></body></html>"}

    def serve(route):
        u = urlsplit(route.request.url)
        if u.path == ACCOUNTS_PATH:
            return route.fulfill(status=200, content_type="application/json",
                                 body='{"members": []}')
        body = pages.get((u.hostname, u.path)) or pages.get(u.hostname) or "<html></html>"
        kind = "text/html"
        if isinstance(body, tuple):
            kind, body = body
        route.fulfill(status=200, content_type=kind, body=body)

    for host in ("digitalbanking.golden1.com", "ebank.hepsiian.com",
                 "offhost.example.test", "odd.example.test"):
        ctx.route("https://%s/**" % host, serve)
    try:
        yield _Browser(ctx, pages, [])
    finally:
        chromium.close()
        driver.stop()


def _on_the_documents_page(bank):
    bank.click("#side")
    bank.wait_for_function("window.ready === true")


def _reasons():
    """Every reason a trace may give for how the vendor's tab came out."""
    return {site.OPENED, site.REUSED, site.NO_DOCUMENTS_PAGE, site.OFF_THE_BANK,
            site.NO_CONTROL, site.REFUSED, site.LEFT_THE_BANK, site.NO_BUTTON,
            site.NO_TAB, site.STAYED_AT_THE_BANK, site.NOT_HTTPS, site.TAB_GONE,
            site.FAILED}


DOCUMENTS = "https://digitalbanking.golden1.com/accounts/documents"


def documents_html(target="_blank", opens_to=VENDOR_URL, accounts_after_ms=None,
                   works_after_answer_ms=0):
    """The documents page loaded by its address, button and all. The button
    opens `opens_to` into the window named `target`. With
    `accounts_after_ms` the page asks for the member's accounts that long
    after it loads, and the button works only `works_after_answer_ms` after
    they answer. Without it the button works at once."""
    return """<html><body>
  <main><h1>Documents</h1><button id="vendor">View Documents</button></main>
  <script>
    const ACCOUNTS_AFTER_MS = %(accounts)s, WORKS_AFTER = %(works_after)s;
    window.ready = ACCOUNTS_AFTER_MS === null;
    document.getElementById('vendor').addEventListener('click', () => {
      if (window.pressed) window.pressed();
      if (window.ready && %(opens)s) window.open(%(opens)s, %(target)s);
    });
    if (ACCOUNTS_AFTER_MS !== null) {
      setTimeout(() => fetch(%(accounts_path)s).then(r => r.json())
                         .then(() => setTimeout(() => { window.ready = true; }, WORKS_AFTER)),
                 ACCOUNTS_AFTER_MS);
    }
  </script>
</body></html>""" % {"accounts": json.dumps(accounts_after_ms),
                     "works_after": json.dumps(works_after_answer_ms),
                     "opens": json.dumps(opens_to), "target": json.dumps(target),
                     "accounts_path": json.dumps(ACCOUNTS_PATH)}


def _bank_tab(browser, url, html):
    """A bank tab at `url`, which serves `html`."""
    browser.pages[(urlsplit(url).hostname, urlsplit(url).path)] = html
    pg = browser.ctx.new_page()
    pg.expose_function("pressed", lambda: browser.presses.append(1))
    pg.goto(url)
    return pg


def test_discovery_started_on_the_overview_reads_the_vendors_list(browser):
    bank = browser.start()
    docs = site.collect_download_docs(bank)
    assert [d.date_text for d in docs] == ["2024-04-30", "2024-03-31", "2024-02-29"]
    assert all(d.dated_by == "label" for d in docs)
    # The date printed on the bank's own page names no statement.
    assert "2024-01-17" not in [d.date_text for d in docs]
    # The link moved the bank's tab, the button opened the vendor's.
    assert bank.url.endswith("/accounts/documents")
    assert site._vendor_tab(bank) is not None
    assert len(browser.presses) == 1


def test_discovery_says_where_it_read_in_counts_and_fixed_words(browser):
    trace = []
    site.collect_download_docs(browser.start(), trace=trace)
    where, read = trace
    assert where == {"note": "discovery, the vendor's tab opened", "on": "ebank.hepsiian.com",
                     "why": site.OPENED, "waited": "until the accounts answered"}
    assert where["why"] in _reasons()
    assert read["note"] == "discovery read the page"
    assert (read["dated_statements"], read["by_label"], read["by_row"]) == (3, 3, 0)
    text = json.dumps(trace)
    for page_words in ("04/30/24", "Current Statement", "Statements", "01/17/2024"):
        assert page_words not in text


def test_a_run_already_on_the_documents_page_presses_the_button_once(browser):
    bank = browser.start()
    _on_the_documents_page(bank)
    assert site.open_vendor(bank) is not None
    assert len(browser.presses) == 1


# -- when the documents page is ready ----------------------------------------

def test_the_button_waits_for_the_accounts_to_answer(browser):
    """The button is on screen at once, but it signs on with nothing until
    the accounts call has answered, which here takes four seconds, longer
    than the settling wait alone. Pressed as soon as it appeared, it
    opened nothing and discovery read the bank's own page again."""
    bank = browser.start(bank_html(accounts_after_ms=4000))
    tab = site.open_vendor(bank)
    assert tab is not None and tab.url == VENDOR_URL
    assert len(browser.presses) == 1


def test_the_button_is_left_to_settle_after_the_accounts_answer(browser):
    """The page draws what the accounts call returned a moment after it
    answers, here one second. The button is pressed two seconds after the
    answer, not on the first look after it."""
    bank = browser.start(bank_html(accounts_after_ms=500, works_after_answer_ms=1000))
    tab = site.open_vendor(bank)
    assert tab is not None and tab.url == VENDOR_URL
    assert len(browser.presses) == 1


def test_with_no_accounts_call_the_button_is_pressed_once_the_wait_is_over(browser, monkeypatch):
    """A page that never makes the accounts call still gets its button
    pressed, after the whole wait, here five seconds, which is longer than
    the button needs. The settling wait alone would be too short."""
    monkeypatch.setattr(site, "LINK_WAIT_POLLS", 10, raising=False)
    bank = browser.start(bank_html(accounts_after_ms=None, inert_ms=3500))
    tab = site.open_vendor(bank)
    assert tab is not None and tab.url == VENDOR_URL
    assert len(browser.presses) == 1


# -- nothing is pressed off the bank, nothing is read on it --------------------

def test_nothing_is_pressed_where_the_link_leaves_the_bank(browser):
    """If the sidebar link ever takes the tab to another site that has a
    button of the same name, that button is not pressed, and nothing it
    could open is let into the run's allowed hosts."""
    allowed = set(site.ALLOWED_HOSTS)
    bank = browser.start(bank_html(leave_to="https://offhost.example.test/documents"))
    assert site.open_vendor(bank) is None
    assert urlsplit(bank.url).hostname == "offhost.example.test"
    assert browser.presses == []
    assert site.ALLOWED_HOSTS == allowed and not site._VENDOR_HOSTS_SEEN
    assert not [p for p in browser.ctx.pages if "odd.example.test" in (p.url or "")]


def test_when_the_vendor_does_not_open_nothing_on_the_banks_page_becomes_a_statement(
        browser, monkeypatch):
    monkeypatch.setattr(site, "TAB_WAIT_POLLS", 4, raising=False)
    bank = browser.start(bank_html(opens=False))
    trace = []
    assert site.collect_download_docs(bank, trace=trace) == []
    assert trace == [{"note": "discovery, the vendor's tab did not open, so no list was read",
                      "on": "digitalbanking.golden1.com",
                      "why": site.NO_TAB, "waited": "until the accounts answered"}]


def test_when_the_vendor_does_not_open_a_capture_presses_nothing_on_the_banks_page(
        browser, monkeypatch, tmp_path):
    """Only the one press that tries to open the vendor. The button beside
    a printed date is not pressed again as if it were that day's
    statement."""
    monkeypatch.setattr(site, "TAB_WAIT_POLLS", 4, raising=False)
    bank = browser.start(bank_html(opens=False))
    _on_the_documents_page(bank)
    trace = []
    assert site.download_bill(bank, tmp_path, "2024-01-17", tmp_path / "x.pdf",
                              trace=trace) is False
    assert len(browser.presses) == 1
    assert trace[-1] == {"note": "the vendor's tab did not open, so no statement was pressed",
                         "on": "digitalbanking.golden1.com", "why": site.NO_TAB,
                         "waited": "not at all, the page was already open"}
    assert not (tmp_path / "x.pdf").exists()


# -- a vendor tab left open by an earlier run ---------------------------------

def test_a_vendor_tab_an_earlier_run_left_open_is_not_read(browser):
    """Its list is still on screen after the vendor's session behind it
    has ended. The run closes it, opens its own through the bank's button
    and reads that one."""
    bank = browser.start()
    _on_the_documents_page(bank)
    old = browser.ctx.new_page()
    old.goto("https://ebank.hepsiian.com/old")
    tab = site.open_vendor(bank)
    assert tab is not old and tab.url == VENDOR_URL
    assert len(browser.presses) == 1
    docs = site.collect_download_docs(bank)
    assert [d.date_text for d in docs] == ["2024-04-30", "2024-03-31", "2024-02-29"]
    assert len(browser.presses) == 1, "the capture reuses the tab this run opened"
    assert old.is_closed()
    assert not bank.is_closed()


def test_a_vendor_tab_is_not_taken_for_the_banks_documents_page(browser):
    """When the tab the run works in is a vendor tab, which happens only
    when no tab of the bank's is open, it is sent to the bank's documents
    page rather than read as it stands."""
    browser.pages["digitalbanking.golden1.com"] = bank_html()
    tab = browser.ctx.new_page()
    tab.goto("https://ebank.hepsiian.com/old")
    assert site.goto_documents(tab) is True
    assert urlsplit(tab.url).hostname == "digitalbanking.golden1.com"


def test_the_vendors_button_is_looked_for_only_on_the_bank(browser, monkeypatch):
    """Neither the button nor the sidebar link of that name is pressed on
    another site. The link would be pressed before the button's own check
    on the tab, so this one is what stops it."""
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    browser.pages[("offhost.example.test", "/link")] = (
        '<html><body><a href="#" onclick="event.preventDefault(); '
        'window.pressed && window.pressed();">View documents</a></body></html>')
    for path in ("/link", "/documents"):
        tab = browser.ctx.new_page()
        tab.expose_function("pressed", lambda: browser.presses.append(1))
        tab.goto("https://offhost.example.test" + path)
        assert site.open_vendor(tab) is None
        assert browser.presses == [], path
        assert site._open_said()["why"] == site.OFF_THE_BANK


# -- a documents page loaded by its address -----------------------------------

def test_a_documents_page_loaded_by_its_address_waits_for_the_accounts_too(browser, monkeypatch):
    """A run that starts on a bank page with no documents control at all
    loads the documents page by its address. The button is on screen at
    once, but here it signs on with nothing until the accounts have
    answered, two and a half seconds after the page loads, which is later
    than the look a loaded page is given. It is pressed once they have
    answered and the page has settled, not straight after that look."""
    monkeypatch.setattr(site, "GOTO_WAIT_MS", 500)
    monkeypatch.setattr(site, "TAB_WAIT_POLLS", 4)
    browser.pages[("digitalbanking.golden1.com", "/accounts/documents")] = documents_html(
        accounts_after_ms=2500, works_after_answer_ms=500)
    bank = _bank_tab(browser, "https://digitalbanking.golden1.com/accounts/activity",
                     "<html><body><main><h1>Activity</h1><p>Nothing here</p></main></body></html>")
    trace = []
    docs = site.collect_download_docs(bank, trace=trace)
    assert [d.date_text for d in docs] == ["2024-04-30", "2024-03-31", "2024-02-29"]
    assert urlsplit(bank.url).path == "/accounts/documents"
    assert len(browser.presses) == 1
    assert trace[0]["waited"] == "until the accounts answered"


# -- only a new tab is the vendor's new tab -----------------------------------

def test_an_old_statements_tab_a_named_window_would_reuse_is_closed_first(browser, monkeypatch):
    """A bank may open its vendor into a NAMED window. The browser then
    sends the new sign-on into an open tab of that name, an earlier run's,
    and no new tab appears. That tab is closed before the press, so the
    press opens a new one, and the new one is what is read."""
    monkeypatch.setattr(site, "TAB_WAIT_POLLS", 6)
    bank = _bank_tab(browser, DOCUMENTS, documents_html(target="statements"))
    with browser.ctx.expect_page() as opened:
        bank.evaluate("u => window.open(u, 'statements')", "https://ebank.hepsiian.com/old")
    old = opened.value
    old.wait_for_load_state()
    trace = []
    docs = site.collect_download_docs(bank, trace=trace)
    assert [d.date_text for d in docs] == ["2024-04-30", "2024-03-31", "2024-02-29"]
    assert old.is_closed() and not bank.is_closed()
    assert len(browser.presses) == 1
    assert trace[0] == {"note": "discovery, the vendor's tab opened", "on": "ebank.hepsiian.com",
                        "why": site.OPENED, "waited": "not at all, the page was already open",
                        "old_tabs_closed": 1}


def test_an_old_statements_tab_that_reloads_itself_is_never_taken_for_a_new_one(
        browser, monkeypatch):
    """The button here opens nothing, and an earlier run's statements tab
    reloads itself on the vendor's site every second. Only a tab that did
    not exist before the press is taken for the one it opened, so
    discovery reads no list at all rather than the old one."""
    monkeypatch.setattr(site, "TAB_WAIT_POLLS", 6)
    browser.pages[("ebank.hepsiian.com", "/reloading")] = (
        '<html><head><meta http-equiv="refresh" content="1"></head><body><main>'
        '<h2>Statements</h2><a href="#">01/31/24</a></main></body></html>')
    bank = _bank_tab(browser, DOCUMENTS, documents_html(opens_to=""))
    old = browser.ctx.new_page()
    old.goto("https://ebank.hepsiian.com/reloading")
    trace = []
    assert site.collect_download_docs(bank, trace=trace) == []
    assert trace[0]["why"] == site.NO_TAB
    assert len(browser.presses) == 1


def test_a_tab_that_stays_on_the_bank_is_closed_and_its_host_not_allowed(browser, monkeypatch):
    """A new tab that never leaves the bank's own site is not the vendor's.
    Taken for it, the bank's host joined the vendor's hosts for the run,
    and the bank's own tab could then pass for the vendor's."""
    monkeypatch.setattr(site, "ADOPT_WAIT_POLLS", 4)
    allowed = set(site.ALLOWED_HOSTS)
    browser.pages[("digitalbanking.golden1.com", "/accounts/handoff")] = (
        "<html><body><p>One moment</p></body></html>")
    bank = _bank_tab(browser, DOCUMENTS, documents_html(
        opens_to="https://digitalbanking.golden1.com/accounts/handoff"))
    trace = []
    assert site.collect_download_docs(bank, trace=trace) == []
    assert len(browser.presses) == 1
    assert browser.ctx.pages == [bank]
    assert site.ALLOWED_HOSTS == allowed and not site._VENDOR_HOSTS_SEEN
    assert not site._ADOPTED_TABS
    assert trace[0]["why"] == site.STAYED_AT_THE_BANK


def test_a_tab_that_closes_before_it_is_looked_at_is_said_so(monkeypatch):
    """The trace never keeps the reason an earlier try gave."""
    monkeypatch.setattr(site, "_LAST_OPEN", {})
    site._said(site.OPENED)

    class _Ctx:
        pages = ["bank"]

    class _Page:
        context = _Ctx()
    assert site._adopt_new_tab(_Page(), {"bank"}) is None
    assert site._open_said() == {"why": site.TAB_GONE}


# -- what a capture writes into the file a tester attaches ---------------------

TOKEN = "Q7X4417"


def test_a_captures_trace_holds_no_address_and_no_label(browser, monkeypatch, tmp_path):
    """The click here asks the vendor for JSON, moves the tab to a viewer
    whose address carries a token, and reveals a Download control that
    does nothing. No PDF arrives. What the trace says about all of it is
    fixed words, statuses and counts, never an address, a token or a
    control's own label."""
    for name in ("CLICK_WAIT_S", "SECOND_STEP_WAIT_S", "LAST_WAIT_S"):
        monkeypatch.setattr(site, name, 1)
    browser.pages[("ebank.hepsiian.com", "/list")] = """<html><body><main>
      <a href="#" onclick="event.preventDefault();
         fetch('/api/statement?docId=%(t)s').then(r => r.json()).then(() => {
           location.href = '/viewer?token=%(t)s'; });">04/30/24</a>
    </main></body></html>""" % {"t": TOKEN}
    browser.pages[("ebank.hepsiian.com", "/api/statement")] = (
        "application/json", '{"state": "queued"}')
    browser.pages[("ebank.hepsiian.com", "/viewer")] = (
        "<html><body><p>Statement %s</p><button>Download</button></body></html>" % TOKEN)
    tab = browser.ctx.new_page()
    tab.goto("https://ebank.hepsiian.com/list")
    downloads = tmp_path / "dl"
    downloads.mkdir()
    trace = []
    el = tab.get_by_role("link", name="04/30/24")
    assert site._catch_pdf(tab, el, "04/30/24", tmp_path / "x.pdf", trace,
                           dl_dir=downloads) is False
    notes = [t.get("note") for t in trace]
    for step in ("clicked", "the tab moved", "after the click", "second step clicked"):
        assert step in notes, step
    assert {"status": 200, "type": "json", "on": "ebank.hepsiian.com"} in trace
    text = json.dumps(trace)
    for leak in (TOKEN, "04/30/24", "Download", "/api/", "/viewer", "https:", "token"):
        assert leak not in text, leak
    assert {t["control_kind"] for t in trace if "control_kind" in t} <= {
        "a link named by its date", "a download step", "another document control"}
    assert {t["on"] for t in trace if "on" in t} == {"ebank.hepsiian.com"}


# -- the orchestrator ---------------------------------------------------------

import golden1_docs  # noqa: E402


class _Tab:
    def __init__(self, url):
        self.url = url


def test_the_run_works_in_the_banks_tab_even_when_the_vendors_is_listed_first():
    vendor = _Tab("https://ebank.hepsiian.com/old")
    bank = _Tab("https://digitalbanking.golden1.com/accounts/overview")
    lookalike = _Tab("https://digitalbanking.golden1.com.phish.example/")
    assert golden1_docs.work_tab([vendor, lookalike, bank]) is bank
    assert golden1_docs.work_tab([lookalike, vendor]) is vendor
    assert golden1_docs.work_tab([lookalike]) is lookalike
    assert golden1_docs.work_tab([]) is None


def _app(tmp_path, monkeypatch, capture_trace):
    app = object.__new__(golden1_docs.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(tmp_path / "p.json")
    app.discovery = storage.JsonStore(tmp_path / "d.json")
    app.index_csv = storage.CsvFile(tmp_path / "i.csv", storage.DOCUMENT_INDEX_COLUMNS)
    app._dl_dir = tmp_path
    app.stats = {"manual_review": 0, "duplicate_filenames": 0}
    app.check_session = lambda page: None
    app.write_failure = lambda *a, **k: None
    monkeypatch.setattr(golden1_docs.site, "goto_documents", lambda page: True)

    def no_pdf(page, dl_dir, iso, out_path, title="", trace=None):
        trace.extend(capture_trace(iso))
        return False
    monkeypatch.setattr(golden1_docs.site, "download_bill", no_pdf)
    return app


class _Page:
    url = OVERVIEW


def _doc():
    return golden1_docs.Document(title="Account Statement - Apr 30, 2024", category="Statement",
                                 summary="Account Statement", date="2024-04-30")


def _attempt(app):
    return json.loads((app.paths.diagnostics / "download-attempt.json").read_text())


def test_a_failed_capture_says_what_discovery_saw(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, lambda iso: [
        {"note": "no control on this page carries that date", "date": iso}])
    app._discovery_trace = [{"note": "discovery, the vendor's tab did not open, so no list was read",
                             "on": "digitalbanking.golden1.com", "why": site.NO_TAB}]
    app.download_one(_Page(), _doc(), "2024-04-30 Golden 1 Account Statement.pdf")
    attempt = _attempt(app)
    notes = [r["note"] for r in attempt["responses"]]
    assert notes == ["discovery, the vendor's tab did not open, so no list was read",
                     "no control on this page carries that date"]
    # Where the bank's tab stood, in the trace's own fixed words.
    assert attempt["landed_on"] == "digitalbanking.golden1.com"


def test_discoverys_lines_do_not_cut_the_captures_own(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch,
               lambda iso: [{"note": "step", "n": i} for i in range(100)])
    app._discovery_trace = [{"note": "discovery, the vendor's tab opened", "on": "ebank.hepsiian.com"},
                            {"note": "discovery read the page", "dated_statements": 3}]
    app.download_one(_Page(), _doc(), "2024-04-30 Golden 1 Account Statement.pdf")
    got = _attempt(app)["responses"]
    assert len(got) == 82
    assert [r.get("n") for r in got[2:]] == list(range(80))
