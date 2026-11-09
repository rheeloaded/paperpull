"""A Discover Bank statement list is noted whole only when every account on
the account menu was read, and a statement is saved only under its own
account, with its own bytes.

The statements page holds an account menu, a React button whose state
names every deposit account and the id its statement list is asked by.
Discovery reads that state and asks each account's list from inside the
page. As first written it read the menu and, when that found nothing,
pressed the menu open, chose each account in turn and read whatever list
calls the browser had recorded, then read the page's text under every
dropdown it could choose. A list call that failed, an account with no id,
an account whose name the click guard did not like (a certificate of
deposit, for the word deposit) and a statement with no PDF were passed over
without a word, and the list was noted whole. With nothing read at all the
empty list was noted whole too.

Now nothing on the page is pressed. An account whose list did not answer,
an account with no id or a name another account has, and a statement
whose PDF is not its own account's, whose date is no day, or whose kind
the account's name and its id disagree on, make the list not whole. What
was read is kept, a failure file is written, and Pilot, Run All and
Discover stop at their end. With no menu to read, the one list the page
asked for itself is read and the list is never noted whole. With none,
the run stops with its list unread.

The list call takes no paging anybody has seen, and both accounts it was
first run on answered exactly 100 statements, so a list of 100, or an
empty one, is not noted whole either. The one control a run presses is
the inactivity dialog's keep-alive, by its whole name, and Login says
signed in only once a statement list answers.

Driven in a real browser on a made-up copy of the page, served for
bank.discover.com by the test. Every account, id and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import discoverbank_docs as app_mod
import discoverbank_site as site
from paperpull_core import listing, testkit

BASE = "https://bank.discover.com"
PAGE_URL = BASE + "/web/deposits/documents/statements"
LIST_PATH = "/bank/deposits/servicing/documents/v1/accounts/%s/statements"

CHECKING = {"label": "Checking (••••0001)", "id": "1000~OC~01"}
SAVINGS = {"label": "Online Savings (••••0002)", "id": "2000~OSA~02"}
ACCOUNTS = [CHECKING, SAVINGS]

PAGE = """<!doctype html><html><body>
<h1>Statements</h1>
%s
<script>
window.pressed = 0;
document.addEventListener('click', () => { window.pressed += 1; }, true);
const menu = %s;
const btn = document.getElementById('menu');
if (btn && menu) {
  btn['__reactFiber$made'] = { memoizedProps: { className: 'x' },
                                return: { memoizedProps: { options: menu }, return: null } };
}
for (const u of %s) fetch(u, { credentials: 'include' });
</script></body></html>"""


DASHBOARD = """<!doctype html><html><body><nav>
<a href="#activity">Activity &amp; Statements</a> <a href="#statements">Statements</a>
<button>Statements</button></nav><main>Your accounts</main>
<script>
history.replaceState({}, '', '/web/dashboard');
window.pressed = 0;
document.addEventListener('click', () => {
  window.pressed += 1;
  fetch('/web/pressed', { keepalive: true }).catch(() => {});
}, true);
</script></body></html>"""


def statements(account_id, count):
    """`count` statements of one account, a month apart back from the newest."""
    out = []
    for i in range(count):
        year, month = 2031 - i // 12, 12 - i % 12
        sid = "s%s%04d" % (account_id[:4], i)
        out.append({"name": "Statement %02d/%d" % (month, year), "id": sid,
                    "statementDate": "%d-%02d-28T00:00:00-05:00" % (year, month),
                    "links": [{"rel": "self", "href": LIST_PATH % account_id},
                              {"rel": "binary", "href": (LIST_PATH % account_id) + "/" + sid}]})
    return out


def statement(account_id, month, under=None):
    """One statement as the list names it. `under` puts its PDF under
    another account's id."""
    sid = "s%s%02d" % (account_id[:4], month)
    return {"name": "Statement %02d/2031" % month, "id": sid,
            "statementDate": "2031-%02d-28T00:00:00-05:00" % month,
            "links": [{"rel": "self", "href": LIST_PATH % account_id},
                      {"rel": "binary",
                       "href": (LIST_PATH % (under or account_id)) + "/" + sid}]}


class Site:
    """What the made-up bank.discover.com answers, and what was asked."""

    def __init__(self):
        self.menu = ACCOUNTS
        self.page_calls = []
        self.lists = {a["id"]: [statement(a["id"], 1), statement(a["id"], 2)]
                      for a in ACCOUNTS}
        self.failing = set()
        self.asked = []
        self.pdfs = {}
        # The Statements address lands on the dashboard instead.
        self.dashboard = False

    def html(self):
        button = ('<button id="menu" class="acct_dropdown_x" aria-expanded="false">%s</button>'
                  % (self.menu[0]["label"] if self.menu else "Statements")) \
            if self.menu is not None else ""
        return PAGE % (button, json.dumps(self.menu), json.dumps(self.page_calls))

    def pdf_for(self, url):
        if url not in self.pdfs:
            self.pdfs[url] = testkit.text_pdf(["Made-up statement", url])
        return self.pdfs[url]

    def answer(self, route):
        url = route.request.url
        self.asked.append(url)
        path = url[len(BASE):] if url.startswith(BASE + "/") else ""
        if url == BASE + "/web/dashboard" or (url == PAGE_URL and self.dashboard):
            return route.fulfill(status=200, content_type="text/html", body=DASHBOARD)
        if url == PAGE_URL:
            return route.fulfill(status=200, content_type="text/html", body=self.html())
        for acct_id, items in self.lists.items():
            if path == LIST_PATH % acct_id:
                if acct_id in self.failing:
                    return route.fulfill(status=500, content_type="application/json", body="{}")
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(items))
            if path.startswith(LIST_PATH % acct_id + "/"):
                return route.fulfill(status=200, content_type="application/pdf",
                                     body=self.pdf_for(url))
        return route.abort()


@pytest.fixture()
def bank():
    return Site()


@pytest.fixture()
def page(bank):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", bank.answer)
    pg = ctx.new_page()
    shortened = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: shortened(min(ms, 100))
    pg.load = lambda: (pg.goto(PAGE_URL), pg.wait_for_load_state("networkidle"))
    yield pg
    browser.close()
    driver.stop()


@pytest.fixture
def make_app(tmp_path, monkeypatch, page):
    def build(*argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 50}),
            encoding="utf-8")
        args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = app_mod.App(args)
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_on_its_site", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        page.load()
        return app
    return build


def failure(tmp_path):
    [path] = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def saved(app):
    return [r for r in app.progress.data.values() if r.get("state") == "Completed"]


def owner_of(href):
    return site.account_of_href(href)


def assert_each_file_is_its_own(app, bank):
    """Every saved statement holds the bytes served for its own address,
    under the account that address belongs to, with the kind it is."""
    by_id = {a["id"]: a for a in bank.menu or ACCOUNTS}
    for rec in saved(app):
        assert Path(rec["pdf_path"]).read_bytes() == bank.pdfs[rec["href"]], rec["href"]
        acct = by_id[owner_of(rec["href"])]
        assert rec["account"] == acct["label"], rec
        assert rec["title"] == site.kind_of_label(acct["label"]) + " Statement", rec


def assert_nothing_pressed(page):
    assert page.evaluate("window.pressed") == 0
    menu = page.locator("#menu")
    if menu.count():
        assert menu.get_attribute("aria-expanded") == "false"


# -- a whole list ------------------------------------------------------------------

def test_every_account_read_is_a_whole_list(make_app, bank, page):
    app = make_app("--all")
    app.cmd_run("all")
    assert len(saved(app)) == 4
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"], SAVINGS["id"]}
    assert_each_file_is_its_own(app, bank)
    assert listing.last(app) == listing.COMPLETE
    assert_nothing_pressed(page)


def test_a_second_run_finds_every_statement_already_saved(make_app, bank):
    make_app("--all").cmd_run("all")
    fetched = len([u for u in bank.asked if "/statements/s" in u])
    app = make_app("--all")
    app.cmd_run("all")
    assert app.stats["skipped_completed"] == 4 and not app.stats["new_files"]
    assert len([u for u in bank.asked if "/statements/s" in u]) == fetched


def test_a_certificate_of_deposit_is_read_and_menu_actions_are_not_accounts(make_app, bank):
    """A name that says certificate of deposit used to be refused for the
    word deposit and passed over without a word. A menu's own action, or
    an option for every account, is no account and no part missing."""
    cd = {"label": "Certificate of Deposit (••••0003)", "id": "3000~CD~03"}
    bank.menu = ACCOUNTS + [cd, {"label": "Open a new account", "id": ""},
                            {"label": "All accounts", "id": ""}]
    bank.lists[cd["id"]] = [statement(cd["id"], 3)]
    app = make_app("--all")
    app.cmd_run("all")
    assert len(saved(app)) == 5
    [rec] = [r for r in saved(app) if owner_of(r["href"]) == cd["id"]]
    assert (rec["title"], rec["account"]) == ("CD Statement", cd["label"])
    assert listing.last(app) == listing.COMPLETE


# -- a list read in part -----------------------------------------------------------

def stops_at_its_end(app, tmp_path, capsys, reason="some of the list could not be read"):
    with pytest.raises(SystemExit) as stopped:
        app.cmd_run("all")
    assert stopped.value.code == 0
    assert listing.last(app) == listing.STOPPED
    out = said(capsys)
    assert "Discover Bank's statement list was not read whole" in out
    assert "so this run stops here" in out
    report = failure(tmp_path)
    assert (report["step"], report["reason"]) == ("read the statement list", reason)


def test_an_account_whose_list_did_not_answer_is_passed_over(make_app, bank, page, tmp_path,
                                                             capsys):
    bank.failing.add(SAVINGS["id"])
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"]}
    assert_each_file_is_its_own(app, bank)
    assert_nothing_pressed(page)
    with pytest.raises(SystemExit):
        make_app("--resume").cmd_resume()


def test_a_statement_under_another_account_is_never_taken(make_app, bank, tmp_path, capsys):
    """One checking account's list names a PDF that sits under the other
    checking account. Both are checking, so only the account the PDF sits
    under tells them apart. It is not saved under the first, its bytes are
    never asked for, and the list is not whole."""
    other = {"label": "Checking (••••0005)", "id": "1005~OC~05"}
    bank.menu = ACCOUNTS + [other]
    bank.lists[other["id"]] = [statement(other["id"], 4)]
    stray = statement(CHECKING["id"], 9, under=other["id"])
    bank.lists[CHECKING["id"]].append(stray)
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert stray["links"][1]["href"] not in {r["href"][len(BASE):] for r in saved(app)}
    assert not any(u.endswith(stray["links"][1]["href"]) for u in bank.asked)
    assert len(saved(app)) == 5
    assert_each_file_is_its_own(app, bank)


def test_an_account_named_one_kind_with_an_id_of_another_is_refused(make_app, bank, tmp_path,
                                                                    capsys):
    bank.menu = [CHECKING, {"label": "Checking (••••0009)",
                            "id": SAVINGS["id"]}]
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"]}


def test_an_account_with_no_id_is_passed_over(make_app, bank, tmp_path, capsys):
    bank.menu = [CHECKING, {"label": "Savings (••••0004)", "id": ""}]
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"]}


def test_an_option_whose_name_says_an_action_is_never_asked_and_passed_over(
        make_app, bank, tmp_path, capsys):
    bank.menu = [CHECKING, {"label": "Transfer funds", "id": "T1"}]
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"]}
    assert not any("/accounts/T1/" in u for u in bank.asked)


def test_two_accounts_with_one_name_are_both_passed_over(make_app, bank, tmp_path, capsys):
    bank.menu = [CHECKING, {"label": CHECKING["label"], "id": "1001~OC~02"}]
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert saved(app) == []


def test_a_statement_with_no_date_is_never_filed(make_app, bank, tmp_path, capsys):
    undated = statement(CHECKING["id"], 5)
    undated["statementDate"] = None
    bank.lists[CHECKING["id"]].append(undated)
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert all(r["date"] for r in saved(app)) and len(saved(app)) == 4


# -- no account menu ---------------------------------------------------------------

def test_no_menu_and_no_list_stops_with_the_list_unread(make_app, bank, page, tmp_path, capsys):
    bank.menu = None
    app = make_app("--pilot")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_pilot()
    assert stopped.value.code == 0
    assert listing.last(app) == listing.STOPPED
    assert not app.discovery.data and saved(app) == []
    assert "its list of accounts could not be read" in said(capsys)
    report = failure(tmp_path)
    assert report["reason"] == "the account menu could not be read"
    assert_nothing_pressed(page)


def test_no_menu_reads_the_one_list_the_page_asked_and_never_calls_it_whole(
        make_app, bank, page, tmp_path, capsys):
    bank.menu = None
    bank.page_calls = [BASE + LIST_PATH % SAVINGS["id"]]
    app = make_app("--all")
    stops_at_its_end(app, tmp_path, capsys)
    assert {owner_of(r["href"]) for r in saved(app)} == {SAVINGS["id"]}
    assert {(r["title"], r["account"]) for r in saved(app)} == {("Savings Statement", "Savings")}
    assert_nothing_pressed(page)


def test_no_menu_and_two_lists_the_page_asked_reads_neither(make_app, bank, tmp_path, capsys):
    bank.menu = None
    bank.page_calls = [BASE + LIST_PATH % a["id"] for a in ACCOUNTS]
    app = make_app("--discover")
    with pytest.raises(SystemExit):
        app.cmd_discover()
    assert listing.last(app) == listing.STOPPED and not app.discovery.data


# -- Diagnose ----------------------------------------------------------------------

def test_diagnose_reports_the_menu_and_its_lists_and_presses_nothing(make_app, bank, page,
                                                                     tmp_path):
    """Diagnose reads the account menu and each list the way discovery does,
    saves nothing, and chooses nothing on the page."""
    bank.failing.add(SAVINGS["id"])
    app = make_app("--diagnose")
    app.cmd_diagnose()
    report = json.loads((tmp_path / "out" / "Diagnostics" / "diagnose-documents.json")
                        .read_text(encoding="utf-8"))
    api = report["statements_api"]
    assert api["account_menu_read"] is True and api["accounts"] == 2
    assert api["statements"] == 2 and len(api["passed_over"]) == 1
    assert not any("/statements/s" in u for u in bank.asked)
    assert saved(app) == [] and not app.discovery.data
    assert_nothing_pressed(page)


# -- a page that is not the statements page --------------------------------------

def test_a_menu_on_another_page_of_the_site_is_not_the_statements_page(page):
    page.load()
    assert site.on_documents_page(page)
    page.evaluate("history.pushState({}, '', '/web/dashboard')")
    assert not site.on_documents_page(page)


def test_statements_are_opened_by_their_address_and_no_menu_or_link_is_pressed(page, bank):
    """When the Statements address lands on another page of the site, the
    run says it could not open Statements. It used to press the site's own
    Activity or Statements link, past what the README said it pressed."""
    bank.dashboard = True
    page.goto(BASE + "/web/dashboard")
    assert site.ensure_statements(page) is False
    assert site.goto_documents(page) is False
    # Each press tells the made-up server, since the page is opened again
    # after a press and starts its own count over.
    assert page.evaluate("window.pressed") == 0
    assert not any(u.endswith("/web/pressed") for u in bank.asked)
    assert bank.asked.count(PAGE_URL) >= 2


# -- a list that may be cut short ----------------------------------------------------

def test_a_list_as_long_as_one_answer_holds_says_older_ones_are_out_of_reach(
        make_app, bank, tmp_path, capsys):
    """The list call takes no paging anybody has seen and says no total, and
    both accounts it was first run on answered exactly 100 statements, one
    of them for 108 months. So a list of 100 may have older statements past
    it that no call this app knows reaches. It is what Discover gives, so it
    is read as whole and the run says so. A run stopped at it stopped every
    run of such an account, and the panel then offered a sign-in and a
    Continue that could not help."""
    bank.lists[SAVINGS["id"]] = statements(SAVINGS["id"], 100)
    app = make_app("--discover")
    app.cmd_discover()
    assert listing.last(app) == listing.COMPLETE
    assert len(app.discovery.data) == 102
    assert "may have older statements this app cannot reach" in said(capsys)
    assert not list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))


@pytest.mark.parametrize("count", [99, 101])
def test_a_list_shorter_or_longer_than_one_answer_holds_is_whole(make_app, bank, count):
    bank.lists[SAVINGS["id"]] = statements(SAVINGS["id"], count)
    app = make_app("--discover")
    app.cmd_discover()
    assert listing.last(app) == listing.COMPLETE
    assert len(app.discovery.data) == count + 2


def test_an_account_whose_list_answers_empty_is_not_a_whole_list(make_app, bank, page, tmp_path,
                                                               capsys):
    """An empty list for an account the menu holds is what a list that did
    not load can look like, so it is not called whole either."""
    bank.lists[SAVINGS["id"]] = []
    app = make_app("--all")
    app.cmd_run("all")
    assert listing.last(app) != listing.COMPLETE
    assert {owner_of(r["href"]) for r in saved(app)} == {CHECKING["id"]}
    out = said(capsys)
    assert "answered with no statements" in out and "this run stops" not in out
    assert_nothing_pressed(page)


# -- Login --------------------------------------------------------------------------

def test_login_says_signed_in_once_the_menu_and_a_list_answer(make_app, capsys):
    make_app("--login").cmd_login()
    assert "Success" in said(capsys)


@pytest.mark.parametrize("how", ["no list answers", "no menu"])
def test_login_on_the_statements_address_alone_says_nothing_of_a_session(make_app, bank, capsys,
                                                                          how):
    """A tab at the Statements address said Success, signed in or not."""
    if how == "no list answers":
        bank.failing.update(a["id"] for a in ACCOUNTS)
    else:
        bank.menu = None
    make_app("--login").cmd_login()
    out = said(capsys)
    assert "Success" not in out
    assert "cannot say whether you are signed in" in out
    assert not any("/statements/s" in u for u in bank.asked)


# -- the inactivity dialog -------------------------------------------------------------

KEEP_ALIVE_PAGE = """<!doctype html><html><body>
<div role="dialog"><p>Are you still there?</p>%s<button>Log out</button></div>
<script>
window.pressed = [];
document.addEventListener('click', e => window.pressed.push(e.target.textContent), true);
</script></body></html>"""


@pytest.mark.parametrize("label", ["I'm still here", "Stay signed in", "Continue session",
                                   "Keep me signed in"])
def test_the_inactivity_dialogs_keep_alive_is_the_one_button_pressed(page, label):
    page.set_content(KEEP_ALIVE_PAGE % ("<button>%s</button>" % label))
    site.dismiss_timeout(page)
    assert page.evaluate("window.pressed") == [label]


@pytest.mark.parametrize("label", ["Stay signed in and transfer funds",
                                   "Continue session to pay bills",
                                   "I'm still here, open an account"])
def test_a_button_that_only_starts_like_a_keep_alive_is_never_pressed(page, label):
    page.set_content(KEEP_ALIVE_PAGE % ("<button>%s</button>" % label))
    site.dismiss_timeout(page)
    assert page.evaluate("window.pressed") == []
    assert not site.is_keep_alive(label)


def test_a_keep_alive_name_over_other_words_is_never_pressed(page):
    """A button is found by its accessible name, which an aria-label gives,
    and what it shows is what a person would be pressing."""
    page.set_content(KEEP_ALIVE_PAGE % '<button aria-label="Stay signed in">Transfer funds</button>')
    site.dismiss_timeout(page)
    assert page.evaluate("window.pressed") == []
