"""Whether a person has finished signing in, from their window's address and
title alone, for every provider there is.

The panel starts Get new by itself once the person is signed in
(signin_watch), and a provider has 81 ways of signing in. So the rule is held
here to the data each app carries, and to a real browser's own list of tabs.
A wrong "signed in" is harmless but it is not wanted, so what looks like a
sign-in page or a second step is asked to stay one here, and every provider it
cannot tell is named, so a provider that stops being told is noticed.
"""
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperpull_core import browser as browser_launcher  # noqa: E402
from paperpull_core import signin_watch as watch  # noqa: E402
from paperpull_core import testkit  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
APPS = REPO / "apps"
SETTLED = watch.SETTLED_LOOKS

BANK = watch.plan_for("https://bank.example/login",
                      {"login": "https://bank.example/login", "home": "https://bank.example/",
                       "documents": "https://secure.bank.example/documents"},
                      ["/login", "/mfa"])
# A window that opened on the public home page, as Chase's does.
PUBLIC = watch.plan_for("https://www.shop.example/",
                        {"login": "https://www.shop.example/", "home": "https://secure.shop.example/",
                         "documents": "https://secure.shop.example/docs"},
                        ["/login"])
# A window opened on the account's own address, sent to sign in when signed out.
OWN = watch.plan_for("https://acct.example/billing",
                     {"login": "https://acct.example/billing", "documents": "https://acct.example/billing"},
                     ["/signin"])


def tab(url, title="Your account"):
    return {"url": url, "title": title}


def settles(plan, *tabs):
    w = watch.Watch(plan)
    return any(w.look(list(tabs)) for _ in range(SETTLED + 1))


def test_a_window_on_a_sign_in_page_that_leaves_it_is_signed_in():
    w = watch.Watch(BANK)
    assert not w.look([tab("https://bank.example/login", "Sign in")])
    # A page it passes through on the way is not enough.
    assert not w.look([tab("https://bank.example/summary")])
    assert not w.look([tab("https://bank.example/accounts")])
    assert not w.look([tab("https://bank.example/accounts")])
    assert w.look([tab("https://bank.example/accounts")])


def test_an_account_page_counts_at_once_even_if_no_sign_in_was_seen():
    assert settles(PUBLIC, tab("https://secure.shop.example/overview", "Accounts"))


@pytest.mark.parametrize("url, title", [
    ("https://bank.example/mfa/start", "Bank"),
    ("https://bank.example/verify", "Bank"),
    ("https://bank.example/two-step", "Bank"),
    ("https://bank.example/account/otp", "Bank"),
    ("https://bank.example/summary", "Enter your security code"),
    ("https://bank.example/summary", "Two-step verification"),
    ("https://bank.example/summary", "Confirm it's you"),
    ("https://bank.example/summary", "Just a moment..."),
    ("https://bank.example/forgot", "Bank"),
    ("https://bank.example/logout", "Signed out"),
])
def test_a_second_step_or_a_way_out_is_not_signed_in(url, title):
    assert not settles(BANK, tab(url, title))
    # Not on an account page's own address either.
    assert not settles(PUBLIC, tab("https://secure.shop.example/verify", "Enter your code"))


def test_a_public_page_after_a_public_start_is_not_signed_in():
    assert not settles(PUBLIC, tab("https://www.shop.example/deals", "Deals"))
    # The window has gone nowhere that says anything.
    assert not settles(PUBLIC, tab("https://www.shop.example/", "Welcome"))


def test_a_public_page_counts_after_a_sign_in_was_seen_there():
    w = watch.Watch(PUBLIC)
    w.look([tab("https://www.shop.example/login", "Sign in")])
    assert [w.look([tab("https://www.shop.example/orders")]) for _ in range(SETTLED)][-1]


def test_back_at_the_account_page_it_opened_on_counts_only_after_a_sign_in():
    w = watch.Watch(OWN)
    assert not any(w.look([tab("https://acct.example/billing", "Billing")]) for _ in range(SETTLED))
    w.look([tab("https://acct.example/signin", "Sign in")])
    assert [w.look([tab("https://acct.example/billing", "Billing")]) for _ in range(SETTLED)][-1]


def test_another_site_says_nothing():
    w = watch.Watch(BANK)
    assert not any(w.look([tab("https://mail.example/inbox", "Inbox")]) for _ in range(SETTLED + 1))
    assert not settles(BANK, tab("chrome://settings", "Settings"))


def test_a_page_still_loading_says_nothing():
    assert not settles(BANK, tab("https://bank.example/accounts", ""))


def test_a_tab_still_signing_in_beside_one_that_is_not_holds_the_wait():
    assert not settles(BANK, tab("https://bank.example/accounts"), tab("https://bank.example/login", "Sign in"))


def test_a_tab_on_a_new_address_starts_the_count_again():
    w = watch.Watch(BANK)
    w.look([tab("https://bank.example/one")])
    w.look([tab("https://bank.example/two")])
    assert not w.look([tab("https://bank.example/two")])


def test_a_provider_with_no_way_to_tell_has_no_plan():
    assert watch.plan_for("https://x.example/", {"login": "https://x.example/", "home": "https://x.example/"}, []) is None
    assert watch.plan_for("nowhere", {}, []) is None


# -- every provider ---------------------------------------------------------------

# Their sign-in leaves no address to tell it by, so the window is left to the
# person to come back from, as it always was. A name added here is a provider
# whose sign-in no longer starts by itself.
CANNOT_TELL = {"applecard", "bofa", "fairfaxwater", "mypay", "paylocity", "ukg"}
# What each provider's own documents address reads as, of the ones with one,
# when it is not an account page.
DOCUMENTS_NOT_AN_ACCOUNT_PAGE = {"ibkr", "simmons"}


def _sites():
    for folder in sorted(APPS.iterdir()):
        found = list(folder.glob("*_site.py"))
        if found:
            yield folder, found[0]


def _load(folder, path, monkeypatch):
    monkeypatch.syspath_prepend(str(folder))
    for name in ("storage", path.stem):
        sys.modules.pop(name, None)
    try:
        return importlib.import_module(path.stem)
    finally:
        sys.modules.pop("storage", None)
        sys.modules.pop(path.stem, None)


@pytest.fixture(scope="module")
def providers():
    made = {}
    for folder, path in _sites():
        mp = pytest.MonkeyPatch()
        try:
            made[folder.name] = _load(folder, path, mp)
        finally:
            mp.undo()
    return made


def _plan(site):
    urls = site.URLS
    start = urls.get("login") or urls.get("documents") or urls.get("home") or ""
    return watch.plan_for(start, urls, getattr(site, "LOGIN_URL_MARKERS", ()) or ())


def test_every_provider_is_watched_or_is_named_as_one_that_cannot_be(providers):
    assert {n for n, s in providers.items() if _plan(s) is None} == CANNOT_TELL
    assert len(providers) >= 81


def test_each_providers_own_sign_in_page_is_never_called_signed_in(providers):
    for name, site in sorted(providers.items()):
        plan = _plan(site)
        login = site.URLS.get("login")
        if plan and login:
            assert not settles(plan, tab(login, "Sign in")), name


def test_each_providers_documents_are_an_account_page(providers):
    wrong = []
    for name, site in sorted(providers.items()):
        plan, documents = _plan(site), site.URLS.get("documents")
        if plan and documents and not plan["start_is_inside"] and documents != plan["start"]:
            if watch._place(documents, "Documents", plan) != watch.AN_ACCOUNT_PAGE:
                wrong.append(name)
    assert set(wrong) == DOCUMENTS_NOT_AN_ACCOUNT_PAGE


# -- said by the run, read by the panel --------------------------------------------

def test_a_marked_plan_line_is_what_a_run_under_the_panel_says(monkeypatch, capsys):
    site = type(sys)("bank_site")
    site.URLS = {"login": "https://bank.example/login", "documents": "https://bank.example/docs"}
    site.LOGIN_URL_MARKERS = ["/login"]
    monkeypatch.setitem(sys.modules, "bank_site", site)
    mark = "ab" * 16
    monkeypatch.setenv("PAPERPULL_RUN_MARK", mark)
    watch.announce("https://bank.example/login")
    said = capsys.readouterr().out
    assert said.startswith(watch.PLAN_PREFIX + mark + " ")
    plan = json.loads(said.split(mark + " ", 1)[1])
    assert plan["start"] == "https://bank.example/login" and plan["dedicated"] is True


def test_a_run_from_a_terminal_says_nothing(monkeypatch, capsys):
    monkeypatch.delenv("PAPERPULL_RUN_MARK", raising=False)
    watch.announce("https://bank.example/login")
    assert capsys.readouterr().out == ""


def test_a_sign_in_that_opened_a_window_says_what_to_watch(monkeypatch):
    said = []
    monkeypatch.setattr(watch, "announce", said.append)
    wrapped = browser_launcher._says_what_to_watch(lambda profile, port, url, **kw: "Chrome")
    assert wrapped("p", "9222", "https://bank.example/login") == "Chrome"
    assert said == ["https://bank.example/login"]
    # And one that did not open says nothing.
    wrapped = browser_launcher._says_what_to_watch(lambda profile, port, url, **kw: None)
    assert wrapped("p", "9222", "https://bank.example/login") is None
    assert len(said) == 1


# -- a real browser, its own list of tabs, a stand-in site ----------------------------

PAGES = {"/login": "Sign in", "/two-step": "Enter your code", "/accounts": "Your accounts"}


class _Site(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("<title>%s</title><p>hi" % PAGES.get(self.path, "?")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def tab_in_a_browser(tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    from playwright.sync_api import sync_playwright
    try:
        with testkit.drawn_browser(found[0][1], lambda: tmp_path_factory.mktemp("profile")) as url:
            driver = sync_playwright().start()
            try:
                yield driver.chromium.connect_over_cdp(url).contexts[0], url
            finally:
                driver.stop()
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


def test_a_real_window_is_watched_through_its_debugging_port(site, tab_in_a_browser):
    ctx, url = tab_in_a_browser
    port = int(url.rsplit(":", 1)[1])
    plan = watch.plan_for(site + "/login", {"login": site + "/login", "documents": site + "/docs"}, ["/login"])
    w = watch.Watch(plan)
    page = ctx.new_page()

    def looks():
        return [w.look(watch.read_tabs(port)) for _ in range(SETTLED + 1)]

    page.goto(site + "/login")
    assert not any(looks())
    # The second step, whose address says nothing but whose title does.
    page.goto(site + "/two-step")
    assert not any(looks())
    page.goto(site + "/accounts")
    assert any(looks())


def test_no_browser_on_the_port_is_no_list():
    assert watch.read_tabs(1) is None
