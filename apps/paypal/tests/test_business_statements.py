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
        # The statements address answers a sign-in page while this is set.
        self.signed_out = False
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
        elif url == B.STATEMENTS and self.signed_out:
            route.fulfill(status=200, content_type="text/html", body=_moved_to(
                "/signin?returnUri=%2Fmyaccount%2Fstatements%2Fmonthly",
                "<form><input type='email' name='login_email'>"
                "<input type='password' name='login_password'></form>"))
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


def _run(monkeypatch, context, tmp_path, *flags, capsys, cfg=None):
    """One command through main, as the panel runs it, with any settings
    in `cfg` added to the config. Its output, folded, its run result line,
    and the code it stopped with, None when it did not stop."""
    _attach(monkeypatch, context)
    stopped = None
    try:
        paypal_docs.main(list(flags) + ["--config", str(B.config(tmp_path, **(cfg or {})))])
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


def test_a_statement_whose_text_names_other_days_goes_to_review_not_the_archive(
        business, tmp_path, monkeypatch, capsys):
    """August's row hands over July's statement. It is never filed under
    August's name, and it is not destroyed either, since the check can be
    wrong too. It waits in Manual Review with a note saying which it was."""
    fake, context = business
    fake.served[B.ACCOUNT_ID + "1"] = B.JULY
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    saved = B.statements(tmp_path)
    assert "2031-08-31 PayPal Monthly Statement.pdf" not in saved
    assert saved.get("2031-07-31 PayPal Monthly Statement.pdf") == B.JULY
    assert B.statements(tmp_path, "Manual Review") == {
        "2031-08-31 PayPal Monthly Statement.pdf": B.JULY}
    assert result["manual_review"] == 1 and result["wrong_document"] == 0
    assert "It names other days than it was listed under" in said
    assert "could not be checked" not in said


def test_with_refuse_wrong_documents_set_such_a_statement_is_not_kept(
        business, tmp_path, monkeypatch, capsys):
    fake, context = business
    fake.served[B.ACCOUNT_ID + "1"] = B.JULY
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys,
                           cfg={"refuse_wrong_documents": True})
    assert "2031-08-31 PayPal Monthly Statement.pdf" not in B.statements(tmp_path)
    assert B.statements(tmp_path, "Manual Review") == {}
    assert result["wrong_document"] == 1


# -- a correct statement is never destroyed --------------------------------------------
#
# Each statement here names its own first and last day, the day the period
# before it closed, transactions inside it and a payment due after it, as a
# real statement does (business_pages.statement). An August statement that
# named July's closing day and a payment on the 17th was taken for July's
# and destroyed, and so was a custom statement over July and August, since
# July's month was found inside 08/17/2031 and a statement ending on the
# same day as a monthly one kept no fact of its own (review of 69dbec7).

def _with_custom(fake, *also):
    """The list holding the custom statement over July and August, and the
    statements named, by their ids."""
    fake.pages = [[r for r in B.ROWS if r["id"] in also] + [B.CUSTOM_ROW]]
    fake.shown[B.CUSTOM_ID] = B.CUSTOM_SHOWN
    fake.served[B.CUSTOM_ID] = B.CUSTOM


def test_a_correct_monthly_statement_naming_the_days_around_it_is_filed(
        business, tmp_path, monkeypatch, capsys):
    fake, context = business
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert B.statements(tmp_path) == B.FILED, said
    assert B.statements(tmp_path, "Manual Review") == {}
    assert not result["manual_review"] and not result["wrong_document"]


def test_a_correct_custom_statement_is_filed(business, tmp_path, monkeypatch, capsys):
    """July's statement is listed beside it, and the custom statement names
    July's last day among its own transactions."""
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "4")
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert B.statements(tmp_path) == {
        B.CUSTOM_FILED: B.CUSTOM, "2031-07-31 PayPal Monthly Statement.pdf": B.JULY}, said
    assert not result["manual_review"] and not result["wrong_document"]


def test_a_monthly_and_a_custom_statement_ending_the_same_day_are_both_filed(
        business, tmp_path, monkeypatch, capsys):
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "1")
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert B.statements(tmp_path) == {
        B.CUSTOM_FILED: B.CUSTOM, "2031-08-31 PayPal Monthly Statement.pdf": B.AUGUST}, said
    assert not result["manual_review"] and not result["wrong_document"]


@pytest.mark.parametrize("refuse", [False, True], ids=["by default", "refusing"])
def test_with_both_months_and_the_custom_listed_nothing_is_destroyed(
        business, tmp_path, monkeypatch, capsys, refuse):
    """The custom statement's first day is July's and its last day August's,
    so nothing of its own is left to tell it by, and the July day among its
    transactions reads as July's. It waits in Manual Review, and both
    monthly statements are filed. With refuse_wrong_documents set it was
    destroyed, refused with nothing of its own ever checked."""
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "1", B.ACCOUNT_ID + "4")
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys,
                           cfg={"refuse_wrong_documents": refuse})
    assert B.statements(tmp_path) == B.FILED, said
    assert B.statements(tmp_path, "Manual Review") == {B.CUSTOM_FILED: B.CUSTOM}
    assert result["manual_review"] == 1 and not result["wrong_document"]


# -- a statement ending on the same day as another ----------------------------------
#
# The custom statement over July and August, with a payment on August 1, the
# first day of August's statement. Its text names its own first day and
# August's both, and its last day is August's too.

def test_a_statement_naming_one_ending_the_same_day_as_plainly_is_filed_as_neither(
        business, tmp_path, monkeypatch, capsys):
    """The custom statement's own row hands over the custom statement. It
    names August's first day as plainly as its own, so it is not filed,
    and August's statement, which does not name the custom one's first
    day, is."""
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "1")
    fake.served[B.CUSTOM_ID] = B.CUSTOM_TIES
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert B.statements(tmp_path) == {"2031-08-31 PayPal Monthly Statement.pdf": B.AUGUST}, said
    assert B.statements(tmp_path, "Manual Review") == {B.CUSTOM_FILED: B.CUSTOM_TIES}
    assert result["manual_review"] == 1 and not result["wrong_document"]
    assert "ending on the same day as plainly as its own" in said


@pytest.mark.parametrize("also", [(), (B.ACCOUNT_ID + "4",)], ids=["alone", "july listed"])
def test_the_custom_statement_handed_over_in_augusts_row_is_not_filed_as_augusts(
        business, tmp_path, monkeypatch, capsys, also):
    """August's row hands over the custom statement. Beside the whole list
    it named August's own day and nothing of the custom one's, since July
    shares its first day, and it was filed as August's (review of c880958).
    Compared alone with the statement that ends on the same day, it names
    each as plainly, and it waits in Manual Review."""
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "1", *also)
    fake.served[B.ACCOUNT_ID + "1"] = B.CUSTOM_TIES
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    filed = B.statements(tmp_path)
    assert "2031-08-31 PayPal Monthly Statement.pdf" not in filed, said
    review = B.statements(tmp_path, "Manual Review")
    assert review["2031-08-31 PayPal Monthly Statement.pdf"] == B.CUSTOM_TIES
    assert not result["wrong_document"]


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


def test_a_table_of_numeric_dates_drawn_in_another_order_presses_each_in_its_own_row(
        business, tmp_path, monkeypatch, capsys):
    """The dates written MM/DD/YYYY, August's statement made on the 7th of
    September, and the table drawn in the opposite order to the answer.
    July's 07/2031 was found inside 09/07/2031 in August's row, and the
    row in July's place in the answer, August's, was pressed for July
    (review of c880958)."""
    fake, context = business
    aug, csv, sep, jul = (B.ACCOUNT_ID + n for n in "1234")
    fake.reverse = True
    fake.shown = {
        aug: B.shown("08/01/2031 - 08/31/2031", "09/07/2031", "PDF", "Ready", "download"),
        csv: B.shown("08/01/2031 - 08/31/2031", "09/07/2031", "CSV", "Ready", "csv"),
        sep: B.shown("09/01/2031 - 09/30/2031", "10/01/2031", "PDF", "In progress", "generate"),
        jul: B.shown("07/01/2031 - 07/31/2031", "08/02/2031", "PDF", "Ready", "download"),
    }
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert sorted(fake.pressed) == sorted([aug, jul]), said
    assert B.statements(tmp_path) == B.FILED
    assert not result["manual_review"] and fake.flags == []


def test_two_rows_naming_a_statements_days_are_never_told_apart_by_position(
        business, tmp_path, monkeypatch, capsys):
    """July's row is drawn with August's days, so two rows name August's
    days and none names July's. The row in August's place in the answer,
    under a table drawn in the opposite order, is July's, and it was pressed
    for August. Now neither is pressed, and both wait for a later run."""
    fake, context = business
    fake.reverse = True
    fake.shown[B.ACCOUNT_ID + "4"] = B.shown("Aug 1, 2031 - Aug 31, 2031", "Aug 2, 2031", "PDF",
                                             "Ready", "download")
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert fake.pressed == [], said
    assert B.statements(tmp_path) == {} and B.statements(tmp_path, "Manual Review") == {}
    assert result["manual_review"] == 2
    assert site.MANY_ROWS in said and site.NO_ROW in said


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
    reads = getattr(site, "is_download_control", None)
    assert reads is None or not reads([label], {"shows": label, "named": []}), label


def test_the_guard_still_passes_a_statements_download():
    for label in ("Download", "Download PDF", "Download statement"):
        assert site.is_safe_control(label), label
        assert site.is_download_control([label], {"shows": label, "named": ["download"]}), label


def test_a_download_control_is_one_only_when_both_readings_say_so():
    assert not site.is_download_control(["Download"], None), "a control that would not answer"
    assert not site.is_download_control([], {"shows": "Download", "named": []})
    assert not site.is_download_control(["Download"], {"shows": "Download CSV", "named": []})
    assert not site.is_download_control(["Download"], {"shows": "Download",
                                                     "named": ["Request statement"]})
    assert not site.is_download_control(["Download", "Generate"], {"shows": "Download",
                                                                 "named": []})


def _changed_at_the_first_press(monkeypatch, script):
    """Run `script` in the page as the first press is armed, after the app
    has found the row and read its control and before it presses."""
    real, done = site.blob_capture.arm, []

    def arm(page):
        if not done:
            done.append(True)
            page.evaluate(script)
        return real(page)
    monkeypatch.setattr(site.blob_capture, "arm", arm)


@pytest.mark.parametrize("change", [
    "(row) => { row.querySelector('button.dl').firstChild.nodeValue = 'Request statement'; }",
    "(row) => { row.children[1].lastChild.textContent = 'Jun 1, 2031 - Jun 30, 2031'; }",
    "(row) => { row.children[1].lastChild.textContent = 'Jul 1, 2031 - Aug 31, 2031'; }",
], ids=["its control relabeled", "another statement drawn in its row",
        "a statement ending the same day drawn in its row"])
def test_a_row_that_changed_between_reading_and_the_press_is_not_pressed(
        business, tmp_path, monkeypatch, capsys, change):
    """August's row, found and read, is changed before the press, its
    Download given another label, or its row given another statement's
    days, one that ends on August's last day among them. Nothing is pressed
    for August, and July is taken as before."""
    fake, context = business
    _changed_at_the_first_press(monkeypatch, (
        "() => (%s)(document.querySelector('button.dl[data-row=\"%s\"]').closest('tr'))"
        % (change, B.ACCOUNT_ID + "1")))
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert fake.pressed == [B.ACCOUNT_ID + "4"], said
    assert B.statements(tmp_path) == {"2031-07-31 PayPal Monthly Statement.pdf": B.JULY}
    assert result["manual_review"] == 1 and fake.flags == []


def test_a_row_redrawn_with_a_statement_ending_the_same_day_is_not_pressed(
        business, tmp_path, monkeypatch, capsys):
    """At the first press, August's row is drawn again with the custom
    statement in it, its days and its Download. The row still named
    August's last day, which was all the check at the press asked, and the
    custom statement was pressed for and filed as August's (review of
    c880958). The whole choice is made again at the press now, and it no
    longer comes to that row, so nothing is pressed for either."""
    fake, context = business
    _with_custom(fake, B.ACCOUNT_ID + "1")
    fake.served[B.CUSTOM_ID] = B.CUSTOM_TIES
    _changed_at_the_first_press(monkeypatch, (
        "() => { const b = document.querySelector('button.dl[data-row=\"%s\"]');"
        " b.closest('tr').children[1].lastChild.textContent = 'Jul 1, 2031 - Aug 31, 2031';"
        " b.dataset.row = '%s'; }" % (B.ACCOUNT_ID + "1", B.CUSTOM_ID)))
    said, result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    assert fake.pressed == [], said
    assert B.statements(tmp_path) == {}
    assert result["manual_review"] == 2 and fake.flags == []


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


def test_a_business_runs_failure_file_counts_the_business_pages_own_selectors(
        business, tmp_path, monkeypatch, capsys):
    """The journal and the failure file counted the personal statements
    page's selectors on the business page, and said the rows matched
    nothing and the selector was wrong."""
    fake, context = business
    odd = B.ACCOUNT_ID + "5"
    fake.pages = [B.ROWS + [B.row(odd, "Jun 1, 2031 - Jun 30, 2031", status=B.HOLDER)]]
    fake.shown[odd] = B.shown("Jun 1, 2031 - Jun 30, 2031", "Jul 2, 2031", "PDF", B.HOLDER,
                              "download")
    said, _result, _ = _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    files = sorted((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    report = json.loads(files[0].read_text(encoding="utf-8"))
    counted = {e["name"]: e for e in report["selectors"]}
    assert set(counted) == {"doc_row", "download_control", "page_ready"}, sorted(counted)
    assert all(e.get("matched") for e in counted.values()), counted
    assert "matched nothing" not in said


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


def test_resume_after_a_pilot_stopped_at_a_sign_in_page_is_not_reported_clean(
        business, tmp_path, monkeypatch, capsys):
    """Run All read the whole list. The Pilot after it met a sign-in page
    with nobody at the console to answer, the panel's most common stop, and
    left by the session check's own stop, past every place a stopped list
    was noted. Resume said everything was complete from Run All's note."""
    fake, context = business
    _run(monkeypatch, context, tmp_path, "--all", "--yes", capsys=capsys)
    fake.signed_out = True
    said, result, stopped = _run(monkeypatch, context, tmp_path, "--pilot", capsys=capsys)
    assert stopped == 0 and result["stopped"] == 1 and "signed you out" in said
    fake.signed_out = False
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
