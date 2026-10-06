"""A business account's settings page is not a sign-in page (#61).

Asked for the statements address, PayPal sent a tester's business account
to /businessmanage/account/accountAccess. The run called that a sign-in
page, went round its sign-in check and loaded the statements address four
times, and stopped with a traceback. Now it loads the address once, names
the page it landed on, says what would show it the way, and stops.

Every page here is invented and served by the browser's own router, which
aborts every other request. DNS is mapped to nothing and no proxy is used,
so nothing can leave this machine even if a request got past the router.
A page's address moves with history.replaceState rather than a redirect,
because a redirect answered by the router is followed on the real network.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import paypal_docs
import paypal_site as site

APP_DIR = Path(__file__).resolve().parents[1]
STATEMENTS = site.STATEMENTS_PAGE
SUMMARY = site.BASE + "/myaccount/summary"
BUSINESS = "/businessmanage/account/accountAccess"

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]


def _moved_to(path, body):
    return ("<!doctype html><html><head><title>PayPal</title><script>"
            "history.replaceState(null, '', %s)</script></head><body>%s</body></html>"
            % (json.dumps(path), body))


# What the statements address answers, one invented page per case.
PAGES = {
    "business": _moved_to(BUSINESS, "<main><h1>Account access</h1>"
                          "<a href='/businessmanage/users'>Manage users</a>"
                          "<button>API access</button></main>"),
    "business_with_an_id": _moved_to(
        "/businessmanage/account/5AB12345CD/accountAccess?token=Q1W2E3R4",
        "<main><h1>Account access</h1></main>"),
    "somewhere_else": _moved_to("/smarthelp/home", "<main><h1>Help Center</h1></main>"),
    "sign_in": _moved_to("/signin?returnUri=%2Fmyaccount%2Fstatements%2Fmonthly",
                         "<form><input type='email' name='login_email'>"
                         "<input type='password' name='login_password'></form>"),
    "robot": _moved_to("/auth/validatecaptcha", "<main><h1>Are you a robot?</h1></main>"),
    "statements": ("<!doctype html><html><head><title>Statements</title></head>"
                   "<body><main><h1>Statements</h1></main></body></html>"),
}


def _month(key, name):
    return {"month": name, "date": key, "title": name,
            "monthNumber": int(key[4:6]), "year": key[:4]}


# The list's shape, with invented months.
LIST = {"data": {"statements": [
    {"year": "2031", "details": [_month("20310201", "February"), _month("20310101", "January")]},
    {"year": "2030", "details": [_month("20301201", "December")]},
]}}


class FakePayPal:
    """Invented PayPal pages behind the router. `lands` says which page the
    statements address answers, and `loads` counts how often it was asked
    for. Everything the pages ask for is kept in `requested`, so a request
    that got past the router would show up there and not in `routed`."""

    def __init__(self, context):
        self.lands = "business"
        self.list_status = 200
        self.listing = LIST
        self.loads = 0
        self.routed, self.requested = [], []
        context.on("request", lambda r: self.requested.append(r.url))
        context.route("**/*", self._answer)

    def _answer(self, route):
        url = route.request.url
        self.routed.append(url)
        if url == STATEMENTS:
            self.loads += 1
            route.fulfill(status=200, content_type="text/html", body=PAGES[self.lands])
        elif url == SUMMARY:
            route.fulfill(status=200, content_type="text/html",
                          body="<!doctype html><html><body><h1>Summary</h1></body></html>")
        elif url == site.LIST_API:
            route.fulfill(status=self.list_status, content_type="application/json",
                          body=json.dumps(self.listing if self.list_status == 200 else {}))
        else:
            route.abort()

    def nothing_got_past_the_router(self):
        return sorted(set(self.requested)) == sorted(set(self.routed))


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
    except Exception as e:
        pytest.skip("no Playwright to drive: %s" % e)
    try:
        chromium = driver.chromium.launch(headless=True, args=ARGS)
    except Exception as e:
        driver.stop()
        pytest.skip("no bundled Chromium to drive: %s" % e)
    yield chromium
    chromium.close()
    driver.stop()


@pytest.fixture()
def paypal(browser):
    context = browser.new_context()
    fake = FakePayPal(context)
    page = context.new_page()
    yield fake, context, page
    context.close()


def _config(tmp_path):
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Tester", "output_dir": str(tmp_path / "out"),
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _attach(monkeypatch, context, answer=None, on_ask=None):
    """The app attaches to the test's browser the way it attaches to the
    person's, and the person at the console is played here."""
    def browser(self):
        self._context, self._cdp_mode = context, True
        return context

    def ask(prompt):
        if on_ask:
            on_ask()
        return answer
    monkeypatch.setattr(paypal_docs.App, "browser", browser)
    monkeypatch.setattr(paypal_docs.browser_launcher, "ask_or_none", ask)


def _app(tmp_path, monkeypatch, context, *flags, **kw):
    _attach(monkeypatch, context, **kw)
    argv = list(flags) + ["--config", str(_config(tmp_path))]
    return paypal_docs.App(paypal_docs.build_parser().parse_args(argv))


def _said(capsys):
    return " ".join(capsys.readouterr().out.split())


# -- the site layer ----------------------------------------------------------

def test_a_business_accounts_settings_is_not_called_a_sign_in_page(paypal):
    fake, _, page = paypal
    with pytest.raises(Exception) as got:
        site.collect_download_docs(page)
    assert not isinstance(got.value, site.SessionExpired), \
        "a business account's settings page was called a sign-in page (%s)" % got.value
    assert type(got.value).__name__ == "SentElsewhere"
    assert (got.value.where, got.value.business) == (BUSINESS, True)
    assert not site.looks_signed_out(page)
    assert fake.loads == 1
    assert fake.nothing_got_past_the_router()


def test_a_part_of_the_address_that_could_name_the_account_is_not_repeated(paypal):
    fake, _, page = paypal
    fake.lands = "business_with_an_id"
    with pytest.raises(Exception) as got:
        site.collect_download_docs(page)
    assert type(got.value).__name__ == "SentElsewhere"
    assert got.value.where == "/businessmanage/account/.../accountAccess"
    assert "Q1W2E3R4" not in str(got.value) and "5AB12345CD" not in str(got.value)


def test_another_paypal_page_is_named_without_being_called_a_business_account(paypal):
    fake, _, page = paypal
    fake.lands = "somewhere_else"
    with pytest.raises(Exception) as got:
        site.collect_download_docs(page)
    assert type(got.value).__name__ == "SentElsewhere"
    assert (got.value.where, got.value.business) == ("/smarthelp/home", False)


def test_a_sign_in_page_is_still_a_sign_in_page(paypal):
    fake, _, page = paypal
    fake.lands = "sign_in"
    with pytest.raises(site.SessionExpired, match="sign-in page"):
        site.collect_download_docs(page)
    assert site.looks_signed_out(page)
    assert getattr(site, "landed_elsewhere", lambda p: "")(page) == ""


def test_a_security_check_is_left_for_the_person_and_not_named_as_a_page(paypal):
    """A check at an address this app has no marker for is still a check.
    It goes to the person, who answers it, and is never stepped past."""
    fake, _, page = paypal
    fake.lands = "robot"
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert site.detect_security_challenge(page)
    assert getattr(site, "landed_elsewhere", lambda p: "")(page) == ""


def test_an_address_is_named_by_its_plain_words_only():
    named = site.page_named
    assert named("https://www.paypal.com" + BUSINESS) == BUSINESS
    assert named("https://www.paypal.com%s?token=Q1W2E3R4&email=someone%%40example.test"
                 % BUSINESS) == BUSINESS
    assert named("https://www.paypal.com/myaccount/transactions/details/5AB12345CD678901E") \
        == "/myaccount/transactions/details/..."
    assert named("https://business.paypal.com/reports/accountStatements") \
        == "business.paypal.com/reports/accountStatements"
    assert "evil" not in named("https://evil.test/businessmanage/account")


def test_only_paypals_own_business_pages_are_business_pages():
    assert site.is_business_page("https://www.paypal.com" + BUSINESS)
    assert not site.is_business_page(STATEMENTS)
    assert not site.is_business_page("https://evil.test" + BUSINESS)
    assert not site.is_business_page("http://www.paypal.com" + BUSINESS)


# -- the run -----------------------------------------------------------------

def test_a_pilot_on_a_business_account_stops_once_and_says_why(paypal, tmp_path,
                                                              monkeypatch, capsys):
    """The tester's own command, through main. One load, a plain message
    naming the page and what to send, a stop the panel reads as a stop,
    and no traceback."""
    fake, context, _ = paypal
    _attach(monkeypatch, context)
    with pytest.raises(SystemExit) as stopped:
        paypal_docs.main(["--pilot", "--config", str(_config(tmp_path))])
    assert stopped.value.code == 0
    assert fake.loads == 1, "the statements address was loaded %d times" % fake.loads
    out = capsys.readouterr().out
    said = " ".join(out.split())
    assert "PayPal opened %s instead of the statements page" % BUSINESS in said
    assert "business account's settings page, not a sign-in page" in said
    assert "Record" in said and "Diagnose" in said
    assert "showed a sign-in page" not in said and "signed you out" not in said
    result = [json.loads(line.split(" ", 1)[1]) for line in out.splitlines()
              if line.startswith("PAPERPULL_RUN_RESULT ")]
    assert result and result[-1]["stopped"] == 1
    assert fake.nothing_got_past_the_router()


def test_login_on_a_business_account_says_where_it_landed(paypal, tmp_path,
                                                         monkeypatch, capsys):
    fake, context, _ = paypal
    app = _app(tmp_path, monkeypatch, context, "--login")
    app.cmd_login()
    said = _said(capsys)
    assert "PayPal opened %s instead of the statements page" % BUSINESS in said
    assert "Success" not in said
    assert "Statements & Taxes" not in said, "a business account has no such place to open"
    assert fake.loads == 1


def test_diagnose_on_a_business_account_loads_the_statements_address_once(paypal, tmp_path,
                                                                         monkeypatch, capsys):
    fake, context, _ = paypal
    app = _app(tmp_path, monkeypatch, context, "--diagnose")
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json")
                      .read_text(encoding="utf-8"))
    assert info["documents_page_found"] is False
    assert fake.loads == 1, "the statements address was loaded %d times" % fake.loads


def test_diagnose_on_a_personal_account_still_reads_the_list(paypal, tmp_path,
                                                            monkeypatch, capsys):
    """Its samples come from the page it has open, not from loading the
    statements address a third time."""
    fake, context, page = paypal
    fake.lands = "statements"
    page.goto(SUMMARY)
    app = _app(tmp_path, monkeypatch, context, "--diagnose")
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json")
                      .read_text(encoding="utf-8"))
    assert info["documents_page_found"] is True
    assert len(info["documents_recognized"]) == 3 and info["rows_collected"] == 3
    assert fake.loads <= 2, "the statements address was loaded %d times" % fake.loads


# Invented, made of letters and digits. A holder's name, an id of letters
# alone and one of letters and digits, in every place Diagnose reads a word
# from, the page's title, a heading, a link and its address, a statement's
# title and a key of the list's answer. The detailed file was meant to stay
# on the tester's machine, and the app's own words told the tester to
# attach it.
NAMED = ("<!doctype html><html><head><title>Statements for Zorvexquill</title></head>"
         "<body><main><h1>Statements for Zorvexquill</h1>"
         "<a href='/merchant/QZXKRWPTKMVNB/statements'>Statements for QZ4XKRWPT7MVN</a>"
         "</main></body></html>")
NAMED_LIST = {"data": {
    "statements": [{"year": "2031", "details": [
        dict(_month("20310201", "February"), title="February QZ4XKRWPT7MVN")]}],
    "QZXKRWPTKMVNB": {"holder": "Zorvexquill"}}}


def test_diagnose_keeps_no_word_off_the_list(paypal, tmp_path, monkeypatch, capsys):
    fake, context, page = paypal
    PAGES["named"] = NAMED
    fake.lands, fake.listing = "named", NAMED_LIST
    page.goto(SUMMARY)
    app = _app(tmp_path, monkeypatch, context, "--diagnose")
    app.cmd_diagnose()
    text = (app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8")
    for canary in ("Zorvexquill", "QZXKRWPTKMVNB", "QZ4XKRWPT7MVN"):
        assert canary.lower() not in text.lower(), "%s came out" % canary
    info = json.loads(text)
    assert info["documents_page_found"] is True and info["rows_collected"] == 1
    assert "February" in text, "a word on the list should still come through"
    assert fake.nothing_got_past_the_router()


def test_a_personal_account_loads_the_statements_page_once(paypal, tmp_path, monkeypatch):
    """The list the app was built on still comes, from one load. A tab
    left on another page used to load it twice."""
    fake, context, page = paypal
    fake.lands = "statements"
    page.goto(SUMMARY)
    app = _app(tmp_path, monkeypatch, context, "--discover")
    app.cmd_discover(quiet=True)
    assert len(app.discovery.data) == 3
    assert fake.loads == 1, "the statements address was loaded %d times" % fake.loads
    assert fake.nothing_got_past_the_router()


def test_a_list_refused_on_a_signed_in_page_stops_once_in_words(paypal, tmp_path,
                                                               monkeypatch, capsys):
    """Loading the page again would be refused the same way, so it is not
    loaded again, and the stop is a sentence rather than a traceback."""
    fake, context, _ = paypal
    fake.lands, fake.list_status = "statements", 403
    app = _app(tmp_path, monkeypatch, context, "--discover")
    with pytest.raises(SystemExit) as stopped:
        app.cmd_discover()
    assert stopped.value.code == 0
    assert "did not hand over the statements list" in _said(capsys)
    assert fake.loads == 1, "the statements address was loaded %d times" % fake.loads


def test_under_the_panel_a_sign_in_page_still_stops_the_run(paypal, tmp_path,
                                                           monkeypatch, capsys):
    fake, context, _ = paypal
    fake.lands = "sign_in"
    app = _app(tmp_path, monkeypatch, context, "--discover", answer=None)
    with pytest.raises(SystemExit) as stopped:
        app.cmd_discover()
    assert stopped.value.code == 0
    assert "signed you out" in _said(capsys)
    assert fake.loads == 1


def test_under_the_panel_a_security_check_still_stops_the_run(paypal, tmp_path,
                                                              monkeypatch, capsys):
    fake, context, _ = paypal
    fake.lands = "robot"
    app = _app(tmp_path, monkeypatch, context, "--discover", answer=None)
    with pytest.raises(SystemExit) as stopped:
        app.cmd_discover()
    assert stopped.value.code == 0
    said = _said(capsys)
    assert "Security challenge detected" in said and "NOT attempt to bypass" in said
    assert "instead of the statements page" not in said
    assert fake.loads == 1


def test_at_a_console_a_sign_in_is_waited_for_and_the_list_read_after(paypal, tmp_path,
                                                                      monkeypatch):
    fake, context, _ = paypal
    fake.lands = "sign_in"

    def signs_in():
        fake.lands = "statements"
    app = _app(tmp_path, monkeypatch, context, "--discover", answer="", on_ask=signs_in)
    app.cmd_discover(quiet=True)
    assert len(app.discovery.data) == 3
    assert fake.nothing_got_past_the_router()


# -- from the safety review of this change ---------------------------------------------

def test_a_name_in_the_address_is_never_repeated():
    """Any plain word was said, so a vanity path printed its name."""
    named = site.page_named
    assert named("https://www.paypal.com/paypalme/SomeoneInvented") == "/.../..."
    assert "Invented" not in named("https://www.paypal.com/us/business/Invented")
    assert named("https://www.paypal.com" + BUSINESS) == BUSINESS


def test_a_download_refused_partway_is_a_stopped_run(paypal, tmp_path, monkeypatch, capsys):
    """It printed Stopped and returned, and the run was reported clean."""
    fake, context, _ = paypal
    app = _app(tmp_path, monkeypatch, context, "--pilot")
    doc = paypal_docs.Document(title="Invented statement", category="Statement",
                               date="2026-01-31", summary="Invented")
    monkeypatch.setattr(app, "_already_done", lambda d: False)

    def refused(page, d, filename):
        raise site.SessionExpired("PayPal refused the download")
    monkeypatch.setattr(app, "download_one", refused)
    with pytest.raises(SystemExit) as stopped:
        app.process([doc])
    assert stopped.value.code == 0
    assert "Stopped." in _said(capsys)
