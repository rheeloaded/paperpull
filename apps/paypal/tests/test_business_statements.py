"""A business account's statements, read from their own page and pressed for.

Asked for the statements address, PayPal sends a business account to its
settings page. Its statements are on /reports/accountStatements, a page
that asks for its own list as it loads and draws a row for each report,
each ready one ending in a Download button (business_pages has the whole
invented account). These drive the app through main against that page in
a real browser, the way the panel runs it.

Every page is served by the browser's own router, which aborts every other
request. DNS is mapped to nothing and no proxy is used, and Playwright's
own request client is made to fail, so nothing can leave this machine. A
press the app must never make, on a control that would create, generate
or request a statement or download a CSV, sends the invented site a flag,
and each test checks it saw none.

The router cancels a download it answers, so here a statement saved
through a link to PayPal's own address arrives by the app asking that
address once more from inside the page, as it does in a browser that never
hands a download over. test_business_statements_attached.py has the
browser's own download of both kinds, attached the way the app attaches
at home.
"""
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import paypal_docs
import paypal_site as site
import business_pages as B

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]


def _moved_to(path, body):
    return ("<!doctype html><html><head><title>PayPal</title><script>"
            "history.replaceState(null, '', %s)</script></head><body>%s</body></html>"
            % (json.dumps(path), body))


class FakeBusiness(B.Business):
    """The invented account behind the browser's router. Every request the
    pages make is kept in `requested`, so one that got past the router
    would show up there and not in `routed`."""

    def __init__(self, context, variant="blob"):
        super().__init__(variant)
        self.routed, self.requested = [], []
        context.on("request", lambda r: self.requested.append(r.url))
        context.route("**/*", self._answer)

    def _answer(self, route):
        req = route.request
        url = req.url
        self.routed.append(url)
        parts = urlsplit(url)
        path = parts.path
        if parts.hostname != "www.paypal.com":
            route.abort()
        elif url == B.STATEMENTS:
            route.fulfill(status=200, content_type="text/html", body=_moved_to(
                B.SETTINGS, "<main><h1>Account access</h1><a href='/businessmanage/users'>"
                            "Manage users</a></main>"))
        elif path == B.REPORTS and self.reports_page:
            route.fulfill(status=200, content_type="text/html", body=self.page_html())
        elif path == B.LIST and req.method == "POST" and self.list_answers:
            self.unmarked += (req.headers or {}).get("x-csrf-token") != "invented-token"
            route.fulfill(status=200, content_type="application/json; charset=utf-8",
                          body=self.list_answer(req.post_data))
        elif path.startswith(B.FILES) and req.method == "GET":
            pdf = self.file(path)
            if pdf is None:
                route.fulfill(status=404, content_type="text/plain", body="gone")
            else:
                route.fulfill(status=200, content_type="application/pdf", body=pdf, headers={
                    "Content-Disposition": 'attachment; filename="%s"' % B.SAVED_NAME})
        elif path == B.PRESSED:
            self.pressed.append(parse_qs(parts.query).get("row", [""])[0])
            route.fulfill(status=204, body="")
        elif path == B.FLAG:
            self.flags.append(parse_qs(parts.query).get("what", [""])[0])
            route.fulfill(status=204, body="")
        else:
            route.abort()

    def nothing_got_past_the_router(self):
        own = lambda urls: sorted({u for u in urls if not u.startswith(("blob:", "data:"))})  # noqa: E731
        return own(self.requested) == own(self.routed)


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


@pytest.fixture(autouse=True)
def nothing_asked_outside_the_browser(monkeypatch):
    """Playwright's own request client goes to the real network whatever the
    browser's router says, so any use of it here fails the test instead."""
    from playwright.sync_api import APIRequestContext

    def refused(*_a, **_k):
        raise AssertionError("Playwright's own request client was used")
    for name in ("get", "post", "fetch", "head", "put", "patch", "delete"):
        monkeypatch.setattr(APIRequestContext, name, refused)


def _site(browser, variant="blob", downloads=True):
    context = browser.new_context(accept_downloads=downloads)
    return FakeBusiness(context, variant), context


@pytest.fixture()
def business(browser):
    fake, context = _site(browser)
    yield fake, context
    context.close()


def _attach(monkeypatch, context, answer=None):
    """The app attaches to the test's browser the way it attaches to the
    person's, and the person at the console is played here."""
    def browser(self):
        self._context, self._cdp_mode = context, True
        return context
    monkeypatch.setattr(paypal_docs.App, "browser", browser)
    monkeypatch.setattr(paypal_docs.browser_launcher, "ask_or_none", lambda prompt: answer)


def _run(monkeypatch, context, tmp_path, *flags, capsys):
    """One command through main, as the panel runs it. Its output, folded,
    its run result line, and the code it stopped with, None when it did
    not stop."""
    _attach(monkeypatch, context)
    stopped = None
    try:
        paypal_docs.main(list(flags) + ["--config", str(B.config(tmp_path))])
    except SystemExit as e:
        stopped = e.code
    out = capsys.readouterr().out
    return " ".join(out.split()), B.result_of(out), stopped


# -- the run -----------------------------------------------------------------

def test_a_business_accounts_ready_statements_are_pressed_for_and_saved(
        business, tmp_path, monkeypatch, capsys):
    """The statements address lands on the business settings page, the run
    goes to the business statements page by its address, reads the list
    the page gets for itself, presses each ready PDF statement's Download
    in its own row and saves each with its own bytes under its days. The
    CSV and the statement still being made are left alone and said."""
    fake, context = business
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--all", "--yes",
                                 capsys=capsys)
    assert B.statements(tmp_path) == B.FILED, said
    assert sorted(fake.pressed) == sorted([B.ACCOUNT_ID + "1", B.ACCOUNT_ID + "4"])
    assert fake.flags == [], "a control that makes a report or a CSV was pressed"
    assert fake.lists >= 1 and fake.unmarked == 0, "the list was asked for by the app"
    assert result and result["new_files"] == 2 and not result["stopped"]
    assert not result["failed"] and not result["manual_review"]
    assert "1 in another kind of file" in said and "1 not ready yet" in said
    written = B.everything_written(tmp_path / "out")
    for canary in B.CANARIES:
        assert canary not in written, "%s reached a file this run wrote" % canary
    assert ".PDF" not in written, "the downloaded file's own name was kept"
    assert fake.nothing_got_past_the_router()


def test_a_second_run_takes_nothing_twice(business, tmp_path, monkeypatch, capsys):
    fake, context = business
    _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    fake.pressed.clear()
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert fake.pressed == [] and result["new_files"] == 0
    assert "Already downloaded" in said


def test_a_statement_whose_text_names_other_days_is_refused(business, tmp_path,
                                                            monkeypatch, capsys):
    """August's row hands over July's statement. It is destroyed rather than
    filed under August's name, and the run says a wrong document came."""
    fake, context = business
    fake.served[B.ACCOUNT_ID + "1"] = B.JULY
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    saved = B.statements(tmp_path)
    assert "2031-08-31 PayPal Monthly Statement.pdf" not in saved
    assert saved.get("2031-07-31 PayPal Monthly Statement.pdf") == B.JULY
    assert result["wrong_document"] == 1


def test_a_row_is_found_by_its_days_whatever_order_the_table_draws(business, tmp_path,
                                                                  monkeypatch, capsys):
    """The table draws its rows in the opposite order to the list's answer,
    so the row in a statement's place in the answer is another statement's.
    Each statement is still pressed for in the row that shows its days, and
    the CSV of the same days is never taken for the PDF."""
    fake, context = business
    fake.reverse = True
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert B.statements(tmp_path) == B.FILED, said
    assert sorted(fake.pressed) == sorted([B.ACCOUNT_ID + "1", B.ACCOUNT_ID + "4"])
    assert fake.flags == []
    assert not result["manual_review"] and not result["wrong_document"]


@pytest.mark.parametrize("variant", ["blob", "direct"])
def test_with_no_download_the_statement_is_read_where_the_page_saved_it(
        browser, tmp_path, monkeypatch, capsys, variant):
    """A browser that never hands the download over, as one attached over
    DevTools might not. The blob the page built is read from the page, and
    an address of PayPal's own is asked for once from inside the page."""
    monkeypatch.setattr(site, "BUSINESS_SETTLE_MS", 3000, raising=False)
    fake, context = _site(browser, variant, downloads=False)
    try:
        said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    finally:
        context.close()
    assert B.statements(tmp_path) == B.FILED, said
    assert said.count("the document arrived by ask") == 2
    assert fake.flags == [] and fake.nothing_got_past_the_router()


# -- the guard -----------------------------------------------------------------

MAKES_A_REPORT = ["Create statement", "Generate statement", "Request statement",
                  "Request a statement", "Prepare statement", "Schedule statement",
                  "Get statement", "Run report", "Create report", "Export",
                  "Download CSV", "Download as CSV", "Download XLSX", "CSV",
                  "Download Excel", "Download TXT", "Download tab-delimited",
                  "Download QIF", "New statement", "Retry"]


@pytest.mark.parametrize("label", MAKES_A_REPORT)
def test_the_guard_refuses_a_control_that_makes_a_report_or_another_kind_of_file(label):
    assert not site.is_safe_control(label), label
    reads = getattr(site, "reads_as_download", None)
    assert reads is None or not reads([label], {"shows": label, "named": []}), label


def test_the_guard_still_passes_a_statements_download():
    for label in ("Download", "Download PDF", "Download statement"):
        assert site.is_safe_control(label), label
        assert site.reads_as_download([label], {"shows": label, "named": ["download"]}), label


def test_a_download_control_is_one_only_when_both_readings_say_so():
    assert not site.reads_as_download(["Download"], None), "a control that would not answer"
    assert not site.reads_as_download([], {"shows": "Download", "named": []})
    assert not site.reads_as_download(["Download"], {"shows": "Download CSV", "named": []})
    assert not site.reads_as_download(["Download"], {"shows": "Download",
                                                     "named": ["Request statement"]})
    assert not site.reads_as_download(["Download", "Generate"], {"shows": "Download",
                                                                 "named": []})


def test_no_forbidden_control_is_pressed_on_the_page(business, tmp_path, monkeypatch, capsys):
    """Create statement, Request statement, Generate statement and Download
    CSV are all on the invented page, and the site saw no press on any, in
    a run that pressed the two ready statements' Download and nothing else."""
    fake, context = business
    _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert fake.flags == []
    assert sorted(fake.pressed) == sorted([B.ACCOUNT_ID + "1", B.ACCOUNT_ID + "4"])


# -- rows this app cannot read ------------------------------------------------------

def test_a_row_whose_status_cannot_be_read_is_refused_and_written_down(
        business, tmp_path, monkeypatch, capsys):
    """Its status is a word nobody has seen. The row is left alone, the run
    is not clean, and the failure file says what kind of value it was
    without saying the value."""
    fake, context = business
    odd = B.ACCOUNT_ID + "5"
    fake.pages = [B.ROWS + [B.row(odd, "Jun 1, 2031 - Jun 30, 2031", status=B.HOLDER)]]
    fake.shown[odd] = B.shown("Jun 1, 2031 - Jun 30, 2031", "Jul 2, 2031", "PDF", B.HOLDER,
                              "download")
    fake.served[odd] = B.JUNE
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert odd not in fake.pressed
    assert "2031-06-30 PayPal Monthly Statement.pdf" not in B.statements(tmp_path)
    assert result["failed"] == 1 and result["new_files"] == 2
    files = sorted((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert files, "no failure file was written"
    text = files[0].read_text(encoding="utf-8")
    unread = json.loads(text)["extra"]["postmortem"]["unread"]
    assert [u["reads_as"] for u in unread] == ["unread status"]
    for canary in B.CANARIES:
        assert canary.lower() not in text.lower()


# -- a list of more than one page ---------------------------------------------------

def test_a_list_of_two_pages_is_paged_by_its_own_next_control(business, tmp_path,
                                                              monkeypatch, capsys):
    fake, context = business
    later = B.OTHER_ID + "6"
    fake.pages = [B.ROWS, [B.row(later, "May 1, 2031 - May 31, 2031")]]
    fake.next = True
    fake.shown[later] = B.shown("May 1, 2031 - May 31, 2031", "Jun 2, 2031", "PDF", "Ready",
                                "download")
    fake.served[later] = B.MAY
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    saved = B.statements(tmp_path)
    assert saved.get("2031-05-31 PayPal Monthly Statement.pdf") == B.MAY, said
    assert len(saved) == 3 and not result["stopped"]
    assert fake.flags == []


def test_a_list_that_says_more_follow_with_no_next_control_stops(business, tmp_path,
                                                                monkeypatch, capsys):
    """What came is saved, and the run stops as a stop rather than finish
    clean on a list it read only part of."""
    fake, context = business
    fake.pages = [B.ROWS, [B.row(B.OTHER_ID + "6", "May 1, 2031 - May 31, 2031")]]
    fake.next = False
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--all", "--yes",
                                 capsys=capsys)
    assert stopped == 0 and result["stopped"] == 1
    assert B.statements(tmp_path) == B.FILED
    assert "could not page" in said


# -- sign-in and the list ------------------------------------------------------------

def test_login_on_a_business_account_says_success_only_once_the_list_came(
        business, tmp_path, monkeypatch, capsys):
    fake, context = business
    said, _, _ = _run(monkeypatch, context, tmp_path, "--login", capsys=capsys)
    assert "Success" in said and "business account" in said
    fake.list_answers = False
    monkeypatch.setattr(site, "REPORTS_WAIT_MS", 3000, raising=False)
    said, _, _ = _run(monkeypatch, context, tmp_path, "--login", capsys=capsys)
    assert "Success" not in said
    assert "never arrived" in said


def test_a_pilot_whose_list_never_comes_stops_and_says_so(business, tmp_path, monkeypatch,
                                                          capsys):
    fake, context = business
    fake.list_answers = False
    monkeypatch.setattr(site, "REPORTS_WAIT_MS", 3000, raising=False)
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--pilot", capsys=capsys)
    assert stopped == 0 and result["stopped"] == 1
    assert "never arrived" in said and fake.pressed == []


# -- Resume -------------------------------------------------------------------------

def test_resume_after_a_stopped_business_run_is_not_reported_clean(
        business, tmp_path, monkeypatch, capsys):
    """The pilot stopped before anything was listed. Resume used to say
    everything in scope was complete, and the panel called the run clean."""
    fake, context = business
    fake.reports_page = False
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--pilot", capsys=capsys)
    assert result["stopped"] == 1
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--resume", capsys=capsys)
    assert "everything in scope is complete" not in said
    assert "No PayPal statements have been listed yet" in said
    assert stopped == 0 and result and result["stopped"] == 1


def test_resume_after_a_run_whose_list_stopped_says_so_too(business, tmp_path,
                                                           monkeypatch, capsys):
    """Everything an earlier run listed is saved, and the latest run stopped
    before its list came. What it knows is complete, the list is not."""
    fake, context = business
    _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    fake.reports_page = False
    _run(monkeypatch, context, tmp_path, "--pilot", capsys=capsys)
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--resume", capsys=capsys)
    assert "everything in scope is complete" not in said
    assert "stopped before it read PayPal's whole list" in said
    assert stopped == 0 and result["stopped"] == 1


def test_resume_after_a_whole_list_still_finishes_clean(business, tmp_path, monkeypatch,
                                                        capsys):
    fake, context = business
    _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--resume", capsys=capsys)
    assert "everything in scope is complete" in said
    assert stopped is None and result["stopped"] == 0


# -- Diagnose -------------------------------------------------------------------------

def test_the_business_diagnose_keeps_no_word_off_the_list(business, tmp_path, monkeypatch,
                                                          capsys):
    """A holder's name in the title, a heading and a status, an id of
    letters and of letters and digits in every report's id, in a row's
    words and in the address and the name of a link the page already made.
    Diagnose presses nothing and writes none of them."""
    fake, context = business
    fake.title = fake.heading = "Statements for " + B.HOLDER
    fake.extra = ("<a download='%s' href='%s%s' style='display:none'>saved</a>"
                  % (B.SAVED_NAME, B.FILES, B.OTHER_ID))
    fake.shown[B.ACCOUNT_ID + "1"] = B.shown("Aug 1, 2031 - Aug 31, 2031 " + B.ACCOUNT_ID,
                                             "Sep 2, 2031", "PDF", "Ready", "download")
    fake.pages = [B.ROWS + [B.row(B.OTHER_ID, "Jun 1, 2031 - Jun 30, 2031", status=B.HOLDER)]]
    fake.shown[B.OTHER_ID] = B.shown("Jun 1, 2031 - Jun 30, 2031", "Jul 2, 2031", "PDF",
                                     B.HOLDER, "none")
    _run(monkeypatch, context, tmp_path, "--diagnose", capsys=capsys)
    folder = tmp_path / "out" / "Diagnostics"
    text = (folder / "diagnose-documents.json").read_text(encoding="utf-8")
    for path in sorted(folder.glob("survey-*.json")):
        text += path.read_text(encoding="utf-8")
    for canary in B.CANARIES:
        assert canary.lower() not in text.lower(), "%s came out" % canary
    info = json.loads((folder / "diagnose-documents.json").read_text(encoding="utf-8"))
    found = info["business"]
    assert found["listed"] is True and found["rows"] == 5 and found["has_more"] is False
    assert found["counts"]["ready"] == 2 and found["counts"]["unread status"] == 1
    assert [r["reads_as"] for r in found["rows_read"]][:4] == ["ready", "other type",
                                                                "not ready", "ready"]
    assert "Aug 9, 9999 - Aug 99, 9999" in [r["period"] for r in found["rows_read"]]
    ready = found["ready_row"]
    assert ready["rows_naming_it"] == 2 and ready["position"] == 0
    assert "Aug 9, 9999 - Aug 99, 9999" in ready["row"]
    assert [c["download"] for c in ready["controls"]] == [True]
    links = found["table"]["links"]
    assert [link["kind"] for link in links] == ["relative"]
    assert links[0]["path"].startswith("/reports/apis/")
    assert fake.pressed == [] and fake.flags == []
    assert fake.nothing_got_past_the_router()
