"""The checks that have to pass before this app touches a real account.
No browser, no network, invented values only. The made-up documents page
below is a spy: it records every load, every press, every request this app
makes and every download, and the tests read what it recorded."""
import io
import json
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import simmons_site as site  # noqa: E402
import simmons_docs as docs  # noqa: E402
from paperpull_core import pressing  # noqa: E402
from paperpull_core.testkit import sample_pdf, text_pdf  # noqa: E402

BASE = "https://login.simmonsbank.com"
# Invented details, which must never leave through a log, the console, the
# index, a diagnostic, a trace, a record or a file name.
USER = "0a1b2c3d-1111-4222-8333-944455556666"
ACCOUNT = "7e7e7e7e-2222-4333-8444-955566667777"
OTHER_ACCOUNT = "7e7e7e7e-2222-4333-8444-955566668888"
# Digits no date or time of day holds, since a run writes its clock into
# names and lines and 00:34:56 would have spelled the old "3456".
NUMBER = "88129786"
LAST4 = "9786"
ACCT_LABEL = "RE ARM %s (x%s)" % (NUMBER, LAST4)
OWNER = "Quentin Wombatson"
BLOB = "blob:https://login.simmonsbank.com/5a5a5a5a-3333-4444-8555-a66677778888"
D1 = "11111111-aaaa-4bbb-8ccc-000000000001"
D2 = "11111111-aaaa-4bbb-8ccc-000000000002"
D3 = "11111111-aaaa-4bbb-8ccc-000000000003"
D4 = "11111111-aaaa-4bbb-8ccc-000000000004"
START = "2023-10-15"
EMAIL = "quentin.w@example.test"
MEMO = "Zorblax escrow refund"
INSTITUTION = "%s/a/consumer/api/users/%s/documents/settings/institution" % (BASE, USER)
# The app's own download folder under the output folder, the one a run uses.
DL = ".simmons-downloads"


def doc(did, kind, title, date, n=1):
    tag = {"statement": "STATEMENT", "notice": "NOTICE", "tax": "TAX"}[kind]
    m, d, y = date[5:7], date[8:10], date[:4]
    return {"documentId": did, "documentType": kind, "documentTitle": title, "description": None,
            "date": date, "documentFilename": "RE ARM %s-%s-%s-%s-%s-%d.pdf" % (NUMBER, tag, m, d, y, n),
            "accountIds": [ACCOUNT]}


DOCS = [doc(D1, "statement", "Loan Periodic Statement October 2031", "2031-10-13"),
        doc(D2, "notice", "Prime Rate Notice August 2031", "2031-08-20", 2),
        doc(D3, "notice", "Notice of Address Change (Previous Address) February 2031", "2031-02-07", 3),
        doc(D4, "tax", "2030 Tax Reporting January 2031", "2031-01-24", 4)]
PRIVATE = [USER, ACCOUNT, NUMBER, LAST4, "Quentin", "Wombatson", BLOB, D1, D2, D3, D4,
           "5a5a5a5a-3333-4444-8555-a66677778888", EMAIL, MEMO, "1234.56"]

TYPE = {"statement": "Statement", "notice": "Notice", "tax": "Tax"}


def row_text(d, acct=ACCT_LABEL):
    return "%s %s, %s" % (d["documentTitle"], TYPE[d["documentType"]], acct)


def list_url(start=START):
    return "%s/a/consumer/api/v0/users/%s/documents/all?startDate=%s" % (BASE, USER, start)


def pdf_url(did):
    return "%s/a/consumer/api/users/%s/documents/%s" % (BASE, USER, did)


def pdf_for(d):
    """A PDF that prints its own date as a statement would, and the tax year
    for a tax form."""
    iso = d["date"]
    lines = ["Simmons Bank", d["documentTitle"], "Statement Date %s/%s/%s" % (iso[5:7], iso[8:10], iso[:4])]
    if d["documentType"] == "tax":
        lines = ["Simmons Bank", "Form 1098 Mortgage Interest Statement", "Tax year 2030"]
    lines += ["Line %d of the made-up document" % n for n in range(12)]
    return text_pdf(lines)


# ---------------------------------------------------------------------------
# The made-up page
# ---------------------------------------------------------------------------

class Frame:
    def __init__(self, page):
        self.page = page


class Req:
    def __init__(self, url, method="GET"):
        self.url, self.method = url, method


class Resp:
    def __init__(self, url, data=None, status=200, ctype="application/json", page=None,
                 readable=True, raw=None, location=None):
        self.url, self.status = url, status
        self.headers = {"content-type": ctype}
        if location is not None:
            self.headers["location"] = location
        self._body = raw if raw is not None else json.dumps(data).encode()
        self.readable = readable
        self.request = Req(url)
        self.frame = Frame(page)

    def body(self):
        if not self.readable:
            raise RuntimeError("Network.getResponseBody: No resource with given identifier")
        return self._body

    def dispose(self):
        pass


class Download:
    def __init__(self, url, name, data):
        self.url, self.suggested_filename, self.data = url, name, data
        self.cancelled = self.deleted = False

    def save_as(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.data)

    def path(self):
        return None

    def cancel(self):
        self.cancelled = True

    def delete(self):
        self.deleted = True


class Client:
    """The browser's own request client, a spy."""

    def __init__(self, page):
        self.page = page
        self.asked = []

    def get(self, url, max_redirects=None, timeout=None, **kw):
        self.asked.append((url, max_redirects))
        return self.page.answer_to(url)


class Context:
    def __init__(self, page):
        self.listeners = []
        self.request = Client(page)

    def on(self, event, fn):
        assert event == "response"
        self.listeners.append(fn)

    def remove_listener(self, event, fn):
        if fn in self.listeners:
            self.listeners.remove(fn)


class Handle:
    def __init__(self, page, i):
        self.page, self.i = page, i
        self.disposed = False

    def evaluate(self, js, arg=None):
        return self.page.texts()[self.i]

    def dispose(self):
        self.disposed = True


class Locator:
    def __init__(self, page, css):
        self.page, self.css = page, css

    def evaluate_all(self, js):
        if self.css == "button":
            return self.page.buttons()
        if self.css == 'button[aria-label="user menu"]':
            return [OWNER]
        return []

    def count(self):
        if self.css == "input[type='password']":
            return 1 if self.page.password else 0
        if self.css == "button":
            return len(self.page.texts())
        return 0

    def nth(self, i):
        page = self.page

        class One:
            def element_handle(self, timeout=None):
                return Handle(page, i)
        return One()

    def inner_text(self, timeout=None):
        return ""


class Page:
    """The documents page. `docs` is what the list answer holds, `rows` the
    row texts the page draws (the answer's own unless given), `extra` other
    buttons on the page. A press of a row makes the page ask for its PDF and
    the browser raise its download, unless told otherwise."""

    def __init__(self, documents=DOCS, rows=None, answer=None, accounts=None, institution=None,
                 start=START):
        self.docs = [dict(d) for d in documents]
        self.rows = rows
        self.answer = answer
        self.accounts = accounts if accounts is not None else {
            "accounts": [{"id": ACCOUNT, "name": "RE ARM %s" % NUMBER, "numbers": "x" + LAST4,
                          "balance": "0.00", "closedAccountAvailableUntil": "2032-06-30"}],
            "inactivatedAccountIds": []}
        self.institution = institution if institution is not None else {
            "settings": {"documentStartDate": START, "documentTypes": ["statement", "notice", "tax"]}}
        self.start = start
        self.url = "about:blank"
        self.password = False
        self.context = Context(self)
        self.listeners = {}
        self.gotos = []
        self.presses = []
        self.waits = []
        self.extra = ["Accept", "Enroll", "OK", "", "Sign out", "Bill pay"]
        self.list_status = 200
        self.list_location = None     # where a redirect list answer says to go
        self.list_readable = True
        self.on_press = None          # what a press brings, by default the PDF
        self.pdf_override = {}
        self.later_rows = None        # rows drawn after the first poll
        self.more_buttons = []        # buttons beyond the rows, as the script reads them
        self.hear_institution = True

    # -- what the page shows
    def buttons(self):
        """Every button as the page script reads it: its text, the list item
        it sits in (-1 for none) and whether it is drawn."""
        rows = self.rows if self.rows is not None else [row_text(d) for d in self.docs]
        if self.later_rows is not None and len(self.waits) >= 2:
            rows = self.later_rows
        out = [{"t": t, "item": -1, "shown": True} for t in self.extra]
        out += [{"t": t, "item": n, "shown": True} for n, t in enumerate(rows)]
        return out + list(self.more_buttons)

    def texts(self):
        return [b["t"] for b in self.buttons()]

    def locator(self, css):
        return Locator(self, css)

    def title(self):
        return "Documents"

    def is_closed(self):
        return False

    # -- loading
    def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append(url)
        self.url = url
        for r in self.responses():
            for fn in list(self.context.listeners):
                fn(r)

    def responses(self):
        answer = self.answer if self.answer is not None else {"documents": self.docs}
        out = [Resp(list_url(self.start), answer, status=self.list_status, page=self,
                    readable=self.list_readable, location=self.list_location),
               Resp("%s/a/consumer/api/users/%s/accounts" % (BASE, USER), self.accounts, page=self),
               # What the page also asks, which this app never reads.
               Resp("%s/a/consumer/api/users/%s/documents/settings/per-account" % (BASE, USER),
                    {"settings": [{"accountId": ACCOUNT, "notifications": {"email": EMAIL}}]},
                    page=self),
               Resp("%s/a/consumer/api/v0/users/%s/accounts/%s/transactions" % (BASE, USER, ACCOUNT),
                    {"transactions": [{"memo": MEMO, "amount": "1234.56"}]}, page=self)]
        if self.hear_institution:
            out.append(Resp(INSTITUTION, self.institution, page=self))
        return out

    def answer_to(self, url):
        if url == INSTITUTION:
            return Resp(url, self.institution, page=self)
        if url.startswith(list_url(self.start).split("?")[0]):
            answer = self.answer if self.answer is not None else {"documents": self.docs}
            return Resp(url, answer, page=self)
        for d in self.docs:
            if url == pdf_url(d["documentId"]):
                data = self.pdf_override.get(d["documentId"], pdf_for(d))
                return Resp(url, raw=data, ctype="application/pdf", page=self)
        return Resp(url, raw=b"<html>not here</html>", status=404, ctype="text/html", page=self)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def on(self, event, fn):
        self.listeners.setdefault(event, []).append(fn)

    def remove_listener(self, event, fn):
        if fn in self.listeners.get(event, []):
            self.listeners[event].remove(fn)

    def fire(self, event, thing):
        for fn in list(self.listeners.get(event, [])):
            fn(thing)

    # -- a press, as press_once would make it
    def press(self, handle):
        text = self.texts()[handle.i]
        self.presses.append(text)
        d = next(d for d in self.docs if row_text(d) == text)
        (self.on_press or Page.brings_pdf)(self, d)

    def brings_pdf(self, d):
        self.fire("request", Req(pdf_url(d["documentId"])))
        self.fire("download", Download(BLOB, d["documentFilename"], pdf_for(d)))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """Every wait is a moment, and press_once is the page's own press after
    the app's guard and check pass, as the real one asks them."""
    monkeypatch.setattr(site, "LIST_WAIT_MS", 1000)
    monkeypatch.setattr(site, "DOWNLOAD_WAIT_MS", 1000)

    def press_once(page, el, *, what, words, guard, check=None, brought=None, dl_dir=None,
                   timeout=None, step=""):
        assert guard(page.texts()[el.i]), "the guard refused the row"
        assert not check or check() == ""
        page.press(el)
        return pressing.Pressed(pressing.PRESSED)
    monkeypatch.setattr(site.pressing, "press_once", press_once)


def listing_of(page):
    return site.read_listing(page, site.Run())


# ---------------------------------------------------------------------------
# Hearing the list
# ---------------------------------------------------------------------------

def test_the_list_is_heard_from_the_pages_own_answer():
    page = Page()
    run = site.Run()
    got = site.collect_download_docs(page, run)
    assert [(d.kind, d.title, d.date_text) for d in got] == [
        (d["documentType"], d["documentTitle"], d["date"]) for d in DOCS]
    assert [d.document_id for d in got] == [site.record_hash(d["documentId"]) for d in DOCS]
    assert page.gotos == [site.DOCUMENTS_URL] and page.presses == []
    assert page.context.request.asked == [], "the list is heard, never asked"
    assert run.available_until == "2032-06-30"


def test_each_family_has_its_own_file_name():
    assert site.summary_for("statement", "Loan Periodic Statement October 2031") == "Loan Statement"
    assert site.summary_for("notice", "Prime Rate Notice August 2031") == "Notice - Prime Rate Notice"
    assert site.summary_for("notice", "Notice of Address Change (Previous Address) February 2031") \
        == "Notice - Notice of Address Change (Previous Address)"
    assert site.summary_for("tax", "2030 Tax Reporting January 2031") == "Tax Reporting 2030"
    assert site.summary_for("tax", "Something else") == "Tax Reporting"
    assert site.summary_for("notice", "Escrow letter") == "Notice - Escrow letter"


def test_a_body_the_browser_dropped_is_asked_once_at_its_exact_address():
    page = Page()
    page.list_readable = False
    got = site.collect_download_docs(page, site.Run())
    assert len(got) == 4
    assert page.context.request.asked == [(list_url(), 0)]


@pytest.mark.parametrize("answer", [
    {"documents": DOCS, "next": "abc"},
    {"items": DOCS},
    {"documents": [dict(DOCS[0], documentType="letter")]},
    {"documents": [dict(DOCS[0], date="2031-02-30")]},
    {"documents": [dict(DOCS[0], documentId="not-a-uuid")]},
    {"documents": [dict(DOCS[0], documentFilename="statement.html")]},
    {"documents": [dict(DOCS[0], accountIds=[ACCOUNT, OTHER_ACCOUNT])]},
    {"documents": [dict(DOCS[0], accountIds=[])]},
    {"documents": [dict(DOCS[0], extra=1)]},
    {"documents": [DOCS[0], dict(DOCS[1], documentId=D1)]},
], ids=["pager key", "no documents", "unknown type", "no such day", "bad id", "not a pdf",
        "two accounts in one", "no account", "unknown key", "one id twice"])
def test_an_answer_this_cannot_read_whole_stops_the_list(answer):
    page = Page(answer=answer)
    with pytest.raises(site.ListStopped):
        listing_of(page)
    assert page.presses == []


def test_two_accounts_across_the_list_stop_it():
    page = Page(documents=[DOCS[0], dict(DOCS[1], accountIds=[OTHER_ACCOUNT])])
    with pytest.raises(site.ListStopped, match="more than one account"):
        listing_of(page)


def test_rows_of_two_accounts_stop_the_list():
    rows = [row_text(DOCS[0]), row_text(DOCS[1], "RE ARM 99999999 (x9999)")]
    with pytest.raises(site.ListStopped):
        listing_of(Page(documents=DOCS[:2], rows=rows))


def test_an_accounts_answer_of_two_accounts_stops_the_list():
    accounts = {"accounts": [{"id": ACCOUNT}, {"id": OTHER_ACCOUNT}]}
    with pytest.raises(site.ListStopped, match="more than one account"):
        listing_of(Page(accounts=accounts))


def test_an_accounts_answer_for_another_account_stops_the_list():
    accounts = {"accounts": [{"id": OTHER_ACCOUNT, "closedAccountAvailableUntil": "2032-06-30"}]}
    with pytest.raises(site.ListStopped):
        listing_of(Page(accounts=accounts))


def test_no_accounts_answer_names_no_date_and_the_list_still_reads():
    page = Page()
    page.responses = lambda: [Resp(list_url(), {"documents": page.docs}, page=page)]
    listing = listing_of(page)
    assert listing.available_until == "" and len(listing.entries) == 4


@pytest.mark.parametrize("change", ["missing", "extra", "title", "type"])
def test_rows_that_are_not_the_answers_stop_the_list(change):
    rows = [row_text(d) for d in DOCS]
    if change == "missing":
        rows = rows[1:]
    elif change == "extra":
        rows = rows + [row_text(DOCS[0]).replace("October", "September")]
    elif change == "title":
        rows[0] = rows[0].replace("October", "September")
    else:
        rows[1] = rows[1].replace(" Notice, ", " Statement, ")
    page = Page(rows=rows)
    with pytest.raises(site.ListStopped, match="rows"):
        listing_of(page)
    assert page.presses == []


def test_rows_drawn_late_are_waited_for():
    page = Page()
    page.rows = []
    page.later_rows = [row_text(d) for d in DOCS]
    assert len(listing_of(page).rows) == 4


def test_a_row_this_cannot_read_stops_the_list():
    rows = [row_text(d) for d in DOCS] + ["Something odd, RE ARM %s (x%s)" % (NUMBER, LAST4)]
    with pytest.raises(site.ListStopped, match="could not be read"):
        listing_of(Page(rows=rows))


def test_a_list_asked_from_after_a_document_stops():
    with pytest.raises(site.ListStopped):
        listing_of(Page(start="2031-03-01"))


def test_a_list_asked_from_another_day_than_the_banks_stops():
    institution = {"settings": {"documentStartDate": "2029-01-01"}}
    with pytest.raises(site.ListStopped, match="first day"):
        listing_of(Page(institution=institution))


def test_with_no_settings_heard_the_banks_first_day_is_asked_once():
    page = Page()
    page.hear_institution = False
    assert len(listing_of(page).entries) == 4
    assert page.context.request.asked == [(INSTITUTION, 0)]


def test_a_self_consistent_list_asked_from_a_later_day_stops():
    """The rows and the answer agree, and the list was still asked from a
    later day than the bank's first, so older documents would be missed."""
    page = Page(documents=DOCS[:1], start="2031-10-01")
    page.hear_institution = False
    with pytest.raises(site.ListStopped, match="first day"):
        listing_of(page)


def test_settings_heard_for_another_user_do_not_vouch_for_the_list():
    """A settings answer of another userId naming the same later day is not
    the bank's word for this list, so the list's own user's settings are
    asked, and their first day stops the list."""
    page = Page(documents=DOCS[:1], start="2031-10-01")
    page.hear_institution = False
    own = page.responses
    stranger = INSTITUTION.replace(USER, OTHER_ACCOUNT)
    page.responses = lambda: own() + [Resp(stranger, {"settings": {"documentStartDate": "2031-10-01"}},
                                           page=page)]
    with pytest.raises(site.ListStopped, match="first day"):
        listing_of(page)
    assert page.context.request.asked == [(INSTITUTION, 0)]


def test_settings_answered_twice_differently_stop_the_list():
    page = Page()
    own = page.responses
    page.responses = lambda: own() + [Resp(INSTITUTION, {"settings": {"documentStartDate": "2029-01-01"}},
                                           page=page)]
    with pytest.raises(site.ListStopped, match="twice"):
        listing_of(page)


@pytest.mark.parametrize("institution", [{}, {"settings": {}}, {"settings": {"documentStartDate": "x"}}])
def test_a_first_day_that_cannot_be_read_stops_the_list(institution):
    with pytest.raises(site.ListStopped, match="first day"):
        listing_of(Page(institution=institution))


def test_a_row_outside_the_list_stops_it():
    page = Page()
    page.more_buttons = [{"t": row_text(DOCS[0]), "item": -1, "shown": True}]
    with pytest.raises(site.ListStopped, match="outside the list"):
        listing_of(page)


def test_a_hidden_row_stops_the_list():
    page = Page()
    page.more_buttons = [{"t": row_text(DOCS[0]), "item": 9, "shown": False}]
    with pytest.raises(site.ListStopped, match="not drawn"):
        listing_of(page)


def test_two_rows_in_one_list_item_stop_the_list():
    page = Page(documents=DOCS[:1])
    page.more_buttons = [{"t": row_text(DOCS[0]), "item": 0, "shown": True}]
    with pytest.raises(site.ListStopped):
        listing_of(page)


def test_an_empty_list_is_a_whole_list_of_nothing():
    page = Page(documents=[])
    assert site.collect_download_docs(page, site.Run()) == []


@pytest.mark.parametrize("status, location", [
    (401, None), (403, None), (302, "/login"), (301, BASE + "/login?next=documents"),
    (303, "/"), (307, "https://sso.example.test/signin"), (308, "/dashboard"), (302, None),
    (307, "/a/consumer/api/v0/users/%s/documents/all?startDate=%s" % (USER, START))],
    ids=["401", "403", "302 to sign-in", "301 to sign-in", "303 off the API",
         "307 to another host", "308 to the dashboard", "redirect that says nowhere",
         "redirect inside the documents API"])
def test_a_signed_out_list_answer_ends_the_session(status, location):
    page = Page()
    page.list_status, page.list_location = status, location
    with pytest.raises(site.SessionExpired):
        listing_of(page)


@pytest.mark.parametrize("status, location", [(304, None), (300, None)],
                         ids=["304 from a cache", "300"])
def test_a_list_answer_that_is_no_sign_out_stops_the_list_and_never_says_signed_out(status,
                                                                                    location):
    """A 304 a cache revalidation brings is no sign-out. It carries no list
    to read, so the list stops, and the run says so rather than tell the
    account holder to sign in again."""
    page = Page()
    page.list_status, page.list_location = status, location
    with pytest.raises(site.ListStopped, match="carries nothing this can read"):
        listing_of(page)
    assert page.presses == [] and page.context.request.asked == []


def test_an_html_list_answer_ends_the_session():
    page = Page()
    page.responses = lambda: [Resp(list_url(), raw=b"<html>sign in</html>", ctype="text/html",
                                   page=page)]
    with pytest.raises(site.SessionExpired):
        listing_of(page)


def test_the_sign_in_page_ends_the_session():
    page = Page()
    page.goto = lambda url, **kw: setattr(page, "url", BASE + "/login")
    with pytest.raises(site.SessionExpired):
        listing_of(page)


def test_an_answer_another_tab_got_is_not_heard():
    page, other = Page(), Page()
    run = site.Run()
    run.attach(page.context)
    page.responses = lambda: [Resp(list_url(), {"documents": DOCS}, page=other)]
    with pytest.raises(site.ListStopped, match="no documents answer"):
        site.read_listing(page, run)


# ---------------------------------------------------------------------------
# Hosts and guards
# ---------------------------------------------------------------------------

def test_the_hosts_are_exact():
    assert site.is_safe_url(site.DOCUMENTS_URL)
    for url in ["https://simmonsbank.com/documents", "http://login.simmonsbank.com/documents",
                "https://login.simmonsbank.com.evil.test/", "https://user@login.simmonsbank.com/",
                "https://login.simmonsbank.com:8443/", "", None]:
        assert not site.is_safe_url(url), url
    assert site.is_download_url(BLOB)
    for url in [BLOB + "x", "blob:https://evil.test/5a5a5a5a-3333-4444-8555-a66677778888",
                "blob:http://login.simmonsbank.com/5a5a5a5a-3333-4444-8555-a66677778888",
                pdf_url(D1), "", None]:
        assert not site.is_download_url(url), url
    assert site.pdf_ids(pdf_url(D1)) == (USER, D1)
    for path in ["all", "settings", "disclosures"]:
        assert site.pdf_ids("%s/a/consumer/api/users/%s/documents/%s" % (BASE, USER, path)) == ("", "")
    assert site.pdf_ids(pdf_url(D1).replace("/api/users/", "/api/v0/users/")) == ("", "")
    assert site.list_address(list_url()) == (USER, START)
    assert site.list_address(list_url() + "&limit=10") == ("", "")


REFUSED = ["Accept", "Enroll", "Enroll all accounts", "OK", "Notify at", "Filter documents menu",
           "Apply", "Clear all", "Dashboard", "Messages", "Accounts", "Transfers", "Remote deposits",
           "Bill pay", "Send money with Zelle®", "Open a new account", "Refer a Friend",
           "Direct Deposit Switch", "Support", "Sign out", "Personal settings", "Account settings",
           "user menu", "Skip to main content", "Privacy policy", "Go paperless with your statements!",
           "Accounts to enroll", "Reorder Checks", "Make a payment", "",
           row_text(DOCS[0]) + " | Accept", "Accept | " + row_text(DOCS[0])]


@pytest.mark.parametrize("label", REFUSED)
def test_every_control_but_a_document_row_is_refused(label):
    assert not site.is_safe_control(label)
    assert not site.is_document_row(label, row_text(DOCS[0]))


def test_a_row_is_pressed_only_for_its_own_document():
    want = row_text(DOCS[2])
    assert site.is_document_row(want, want), "a notice whose title says Change is its own row"
    assert site.is_document_row(want + " | " + want, want)
    assert not site.is_document_row(row_text(DOCS[0]), want)
    assert not site.is_document_row(want, "")
    assert not site.is_document_row(want, "Accept")
    assert site.is_safe_control(row_text(DOCS[0]))
    assert site.is_safe_control("Download statement") and site.is_safe_control("Loan Statement")


def test_an_account_part_the_blocklist_refuses_is_never_pressed():
    want = "Loan Periodic Statement October 2031 Statement, Transfer funds (x1234)"
    assert not site.is_document_row(want, want)


def test_the_row_guard_is_asked_before_the_first_press(tmp_path, monkeypatch):
    """press_once asks the app's guard only before its press through the
    page, never before Playwright's own first press, which is the press made
    nearly every time. So a row whose account part the blocklist refuses is
    refused by the app itself, before press_once is called."""
    page = Page(rows=[row_text(d, "Transfer funds (x%s)" % LAST4) for d in DOCS])
    pressed = []

    def press_once(page, el, **kw):
        # As the real one presses first, with no guard asked.
        pressed.append(el.i)
        return pressing.Pressed(pressing.PRESSED)
    monkeypatch.setattr(site.pressing, "press_once", press_once)
    got, out, trace = take(page, tmp_path)
    assert got is False and pressed == [] and not out.exists()
    assert {"note": "the row's own text is not a document row this presses"} in trace


def test_an_accounts_answer_of_no_account_says_so():
    """A paid-off loan's account leaves the accounts answer once its date
    has passed, and the list stops in words that say what it saw."""
    with pytest.raises(site.ListStopped, match="no account this can read"):
        listing_of(Page(documents=[], accounts={"accounts": []}))


# ---------------------------------------------------------------------------
# Taking one document
# ---------------------------------------------------------------------------

def take(page, tmp_path, d=DOCS[0], **kw):
    out = tmp_path / "out" / "doc.pdf"
    trace = []
    got = site.download_document(page, site.Run(), tmp_path / DL, out,
                                 record_id=kw.get("record_id", site.record_hash(d["documentId"])),
                                 iso_date=kw.get("iso", d["date"]), title=d["documentTitle"],
                                 kind=d["documentType"], trace=trace)
    return got, out, trace


def test_the_download_the_press_brings_is_taken_and_bound(tmp_path):
    page = Page()
    got, out, trace = take(page, tmp_path)
    assert got is True and out.read_bytes() == pdf_for(DOCS[0])
    assert page.presses == [row_text(DOCS[0])]
    assert page.context.request.asked == [], "nothing was asked again"
    assert {"note": "document taken", "how": "download", "where": "event"} in trace
    for word in PRIVATE:
        assert word not in json.dumps(trace), word


def test_a_download_named_for_another_file_is_refused_and_cancelled(tmp_path):
    page = Page()
    seen = []

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        dl = Download(BLOB, DOCS[1]["documentFilename"], pdf_for(d))
        seen.append(dl)
        page.fire("download", dl)
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists()
    assert seen[0].cancelled and seen[0].deleted
    assert page.context.request.asked == [], "a wrong download is not followed by a fetch"


def test_a_download_from_anywhere_but_the_banks_page_is_refused(tmp_path):
    page = Page()
    seen = []

    def brings(page, d):
        dl = Download("https://evil.test/x.pdf", d["documentFilename"], pdf_for(d))
        seen.append(dl)
        page.fire("download", dl)
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and seen[0].cancelled


def test_a_second_download_means_none_is_taken(tmp_path):
    page = Page()
    seen = []

    def brings(page, d):
        for _ in range(2):
            dl = Download(BLOB, d["documentFilename"], pdf_for(d))
            seen.append(dl)
            page.fire("download", dl)
    page.on_press = brings
    got, out, trace = take(page, tmp_path)
    assert got is False and not out.exists()
    assert all(dl.cancelled for dl in seen)
    assert site.SECOND_DOWNLOAD_WAIT_MS in page.waits


def test_no_download_then_the_exact_address_the_page_asked_is_fetched_once(tmp_path):
    page = Page()
    page.on_press = lambda page, d: page.fire("request", Req(pdf_url(d["documentId"])))
    got, out, trace = take(page, tmp_path)
    assert got is True and out.read_bytes() == pdf_for(DOCS[0])
    assert page.context.request.asked == [(pdf_url(D1), 0)]
    assert {"note": "document taken", "how": "fetched"} in trace


def test_no_download_and_nothing_asked_fetches_nothing(tmp_path):
    page = Page()
    page.on_press = lambda page, d: None
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists()
    assert page.context.request.asked == []


def test_html_where_the_pdf_should_be_is_not_kept(tmp_path):
    page = Page()
    page.on_press = lambda page, d: page.fire("request", Req(pdf_url(d["documentId"])))
    page.pdf_override[D1] = b"<html><body>Please sign in</body></html>"
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists()


def test_a_request_for_another_documents_pdf_takes_nothing(tmp_path):
    page = Page()
    seen = []

    def brings(page, d):
        page.fire("request", Req(pdf_url(D2)))
        dl = Download(BLOB, d["documentFilename"], pdf_for(d))
        seen.append(dl)
        page.fire("download", dl)
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and seen[0].cancelled


def test_a_tab_the_press_opened_takes_nothing(tmp_path):
    page = Page()

    class Tab:
        closed = False

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True
    tab = Tab()
    page.on_press = lambda page, d: page.fire("popup", tab)
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and tab.closed


def test_a_download_with_no_request_of_its_own_is_not_taken(tmp_path):
    page = Page()
    seen = []

    def brings(page, d):
        dl = Download(BLOB, d["documentFilename"], pdf_for(d))
        seen.append(dl)
        page.fire("download", dl)
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and seen[0].cancelled and seen[0].deleted


def test_two_requests_for_the_pdf_take_nothing(tmp_path):
    page = Page()

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        page.fire("request", Req(pdf_url(d["documentId"])))
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and page.context.request.asked == []


def test_a_file_in_the_folder_with_no_event_is_not_asked_again(tmp_path):
    page = Page()

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        (tmp_path / DL).mkdir(exist_ok=True)
        (tmp_path / DL / "landed.pdf").write_bytes(pdf_for(d))
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists()
    assert page.context.request.asked == [], "no second request for a download already come"
    assert list((tmp_path / DL).iterdir()) == [], \
        "a file whose download cannot be told is not taken, and not left behind either"


def test_a_download_still_being_written_is_not_asked_again(tmp_path):
    page = Page()

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        (tmp_path / DL).mkdir(exist_ok=True)
        (tmp_path / DL / "landed.pdf.crdownload").write_bytes(b"%PDF-1.4 partial")
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists() and page.context.request.asked == []


@pytest.mark.parametrize("how", ["another file's name", "two downloads", "not the bank's"])
def test_a_refused_download_leaves_nothing_in_the_download_folder(tmp_path, how):
    """A real browser pointed at the folder writes each download there under
    the bank's own documentFilename, which carries the account number, and
    canceling or deleting Playwright's download does not remove that file.
    Refused, it is removed from the app's own folder before the run goes
    on."""
    page = Page()
    folder = tmp_path / DL

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        name = DOCS[1]["documentFilename"] if how == "another file's name" else d["documentFilename"]
        url = "https://evil.test/x.pdf" if how == "not the bank's" else BLOB
        for n in range(2 if how == "two downloads" else 1):
            folder.mkdir(exist_ok=True)
            (folder / (name if n == 0 else name.replace(".pdf", " (1).pdf"))).write_bytes(pdf_for(d))
            page.fire("download", Download(url, name, pdf_for(d)))
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is False and not out.exists()
    assert list(folder.iterdir()) == [], "a refused download stayed under the bank's file name"


def test_a_download_kept_from_the_event_leaves_no_copy_in_the_folder(tmp_path):
    page = Page()
    folder = tmp_path / DL

    def brings(page, d):
        page.fire("request", Req(pdf_url(d["documentId"])))
        folder.mkdir(exist_ok=True)
        # The browser's own copy, still being written when the event is taken.
        (folder / (d["documentFilename"] + ".crdownload")).write_bytes(b"%PDF-1.4 part")
        page.fire("download", Download(BLOB, d["documentFilename"], pdf_for(d)))
    page.on_press = brings
    got, out, _ = take(page, tmp_path)
    assert got is True and out.read_bytes() == pdf_for(DOCS[0])
    assert list(folder.iterdir()) == []


def test_a_download_landing_after_its_capture_is_gone_before_the_next_and_at_the_end(
        tmp_path, monkeypatch):
    """With no download, the PDF is asked once more and saved, and the
    browser's own download of it may still land afterwards, under the bank's
    file name. It is gone before the next press, and the run ends with the
    folder holding nothing it did not keep."""
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    cfg.update(output_dir=str(tmp_path / "out"), owner="Example Owner", delay_min_seconds=0,
               delay_max_seconds=0)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    page = Page()
    folder = tmp_path / "out" / DL
    seen_at_press = []

    def brings(page, d):
        seen_at_press.append(sorted(p.name for p in folder.iterdir()))
        page.fire("request", Req(pdf_url(d["documentId"])))
    page.on_press = brings

    def own_page(self):
        self._dl_dir = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._work_page = page
        return page
    landed = []

    def late(self, factor=1.0):
        # The browser finishes the download its capture gave up on.
        name = DOCS[len(landed) % len(DOCS)]["documentFilename"]
        (folder / name).write_bytes(b"%PDF-1.4 late")
        landed.append(name)
    monkeypatch.setattr(docs.App, "page", own_page)
    monkeypatch.setattr(docs.App, "_on_its_site", lambda self: page)
    monkeypatch.setattr(docs.App, "check_session", lambda self, page: None)
    monkeypatch.setattr(docs.App, "_delay", late)
    with redirect_stdout(io.StringIO()):
        docs.main(["--config", str(path), "--all", "--yes"])
    assert len(page.presses) == 4 and len(landed) == 4
    assert seen_at_press == [[]] * 4, "a late download was still there at the next press"
    assert list(folder.iterdir()) == [], "the run ended with a download it did not keep"
    assert len(list((tmp_path / "out" / "Statements").glob("*.pdf"))) == 1


def test_nothing_outside_the_download_folder_is_ever_removed(tmp_path):
    assert site.DOWNLOAD_FOLDER == DL
    out = tmp_path / "out"
    folder = out / DL
    (folder / "inside").mkdir(parents=True)
    (folder / "left.pdf").write_bytes(b"%PDF-1.4 x")
    (folder / "arriving.pdf.crdownload").write_bytes(b"%PDF-1.4 x")
    (folder / "inside" / "deeper.pdf").write_bytes(b"%PDF-1.4 x")
    (out / "beside.pdf").write_bytes(b"%PDF-1.4 x")
    other = tmp_path / "Downloads"
    other.mkdir()
    (other / "mine.pdf").write_bytes(b"%PDF-1.4 x")
    assert site.empty_download_folder(other) == 0 and (other / "mine.pdf").exists()
    assert site.empty_download_folder(out) == 0 and (out / "beside.pdf").exists()
    assert site.empty_download_folder(None) == 0
    assert site.empty_download_folder(folder, unfinished=False) == 1
    assert sorted(p.name for p in folder.iterdir()) == ["arriving.pdf.crdownload", "inside"]
    assert site.empty_download_folder(folder) == 1
    assert [p.name for p in folder.iterdir()] == ["inside"]
    assert (folder / "inside" / "deeper.pdf").exists() and (out / "beside.pdf").exists()
    assert site.clear_what_came(other, set()) == 0 and (other / "mine.pdf").exists()


def test_a_row_whose_visibility_cannot_be_read_stops_the_list():
    """A browser without checkVisibility says nothing of whether a row is
    seen, and the list stops rather than take it for one."""
    page = Page()
    page.more_buttons = [{"t": row_text(DOCS[0]), "item": 9, "shown": None}]
    with pytest.raises(site.ListStopped, match="not drawn"):
        listing_of(page)


def test_the_census_describes_only_what_the_app_reads_itself():
    assert site.is_census_url(site.DOCUMENTS_URL) and site.is_census_url(list_url())
    assert site.is_census_url(INSTITUTION)
    for url in ["%s/a/consumer/api/users/%s/accounts" % (BASE, USER),
                "%s/a/consumer/api/users/%s/documents/settings/per-account" % (BASE, USER),
                "%s/a/consumer/api/v0/users/%s/accounts/%s/transactions" % (BASE, USER, ACCOUNT),
                pdf_url(D1), "https://evil.test/documents"]:
        assert not site.is_census_url(url), url


def test_a_turned_off_row_is_left_for_the_next_run(tmp_path, monkeypatch):
    page = Page()

    def off(*a, **kw):
        raise pressing.TurnedOff("save the document", "the control is turned off", ["off"])
    monkeypatch.setattr(site.pressing, "press_once", off)
    got, out, _ = take(page, tmp_path)
    assert got is None and not out.exists()


def test_a_record_no_longer_listed_presses_nothing(tmp_path):
    page = Page(documents=DOCS[1:])
    got, _, _ = take(page, tmp_path)
    assert got is False and page.presses == []
    got, _, _ = take(Page(), tmp_path, iso="2031-10-12")
    assert got is False


@pytest.mark.parametrize("record_id", ["", D1, "abc", "g" * 64])
def test_a_record_that_names_no_document_presses_nothing(tmp_path, record_id):
    page = Page()
    got, _, _ = take(page, tmp_path, record_id=record_id)
    assert got is False and page.presses == [] and page.gotos == []


def test_two_rows_of_one_title_press_neither(tmp_path):
    rows = [row_text(d) for d in DOCS]
    twin = dict(DOCS[0], documentId="11111111-aaaa-4bbb-8ccc-000000000009", date="2031-10-14")
    page = Page(documents=DOCS + [twin], rows=rows + [rows[0]])
    got, _, trace = take(page, tmp_path)
    assert got is False and page.presses == []


def test_a_list_that_stops_while_a_document_is_sought_stops_the_run(tmp_path):
    page = Page(rows=[row_text(d) for d in DOCS[1:]])
    with pytest.raises(pressing.Stop) as stop:
        take(page, tmp_path)
    assert page.presses == []
    # A Resume would read the same list for its first document (#124).
    assert stop.value.list_unread


# ---------------------------------------------------------------------------
# Whether the PDF names its document
# ---------------------------------------------------------------------------

def test_a_pdf_that_prints_its_date_names_its_document():
    assert site.pdf_names_document(pdf_for(DOCS[0]), "statement", DOCS[0]["documentTitle"],
                                   DOCS[0]["date"])[0]


def test_a_pdf_of_another_day_does_not():
    other = text_pdf(["Simmons Bank", "Statement Date 09/12/2031", "Payment due"] +
                     ["line %d" % n for n in range(12)])
    ok, report = site.pdf_names_document(other, "statement", DOCS[0]["documentTitle"],
                                         DOCS[0]["date"])
    assert not ok and report["verdict"]["outcome"] == "refused"


def test_a_pdf_with_no_text_names_nothing():
    assert not site.pdf_names_document(sample_pdf(), "statement", DOCS[0]["documentTitle"],
                                       DOCS[0]["date"])[0]
    assert not site.pdf_names_document(b"<html>", "statement", DOCS[0]["documentTitle"],
                                       DOCS[0]["date"])[0]


def test_a_tax_form_names_its_year():
    assert site.pdf_names_document(pdf_for(DOCS[3]), "tax", DOCS[3]["documentTitle"],
                                   DOCS[3]["date"])[0]
    other = text_pdf(["Form 1098", "Tax year 2023"] + ["line %d" % n for n in range(12)])
    assert not site.pdf_names_document(other, "tax", DOCS[3]["documentTitle"], DOCS[3]["date"])[0]


# ---------------------------------------------------------------------------
# The run: records, names and privacy
# ---------------------------------------------------------------------------

def make_app(tmp_path, monkeypatch, page, *more):
    cfg = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
    cfg.update(output_dir=str(tmp_path / "out"), owner="Example Owner", delay_min_seconds=0,
               delay_max_seconds=0)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    args = docs.build_parser().parse_args(["--config", str(path), "--all", "--yes", *more])
    app = docs.App(args)
    app._dl_dir = tmp_path / "out" / ".simmons-downloads"
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    return app


def everything_written(tmp_path):
    return "".join(p.read_text(encoding="utf-8", errors="ignore")
                   for p in (tmp_path / "out").rglob("*")
                   if p.is_file() and p.suffix in (".csv", ".txt", ".log", ".json"))


def without_the_folder(text, tmp_path):
    """text with the test's own folder taken out however it is written,
    since pytest numbers it and pytest-49786 would hold the tail."""
    for written in (str(tmp_path), json.dumps(str(tmp_path))[1:-1], tmp_path.as_posix()):
        text = text.replace(written, "<folder>")
    return text


def test_a_run_saves_every_document_under_its_own_name(tmp_path, monkeypatch, caplog):
    page = Page()
    app = make_app(tmp_path, monkeypatch, page)
    caplog.set_level(logging.INFO)
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.cmd_run("all")
        app.write_run_summary()
    # In POSIX form, so the folder and the file read alike on Windows too.
    names = sorted(p.relative_to(tmp_path / "out").as_posix()
                   for p in (tmp_path / "out").rglob("*.pdf")
                   if ".simmons-downloads" not in p.parts)
    assert names == [
        "Notices/2031-02-07 Simmons Bank Notice - Notice of Address Change (Previous Address).pdf",
        "Notices/2031-08-20 Simmons Bank Notice - Prime Rate Notice.pdf",
        "Statements/2031-10-13 Simmons Bank Loan Statement.pdf",
        "Tax Documents/2031-01-24 Simmons Bank Tax Reporting 2030.pdf"]
    assert sorted(page.presses) == sorted(row_text(d) for d in DOCS)
    printed = buf.getvalue()
    assert "documents available until 2032-06-30" in printed
    seen = without_the_folder(printed + caplog.text + everything_written(tmp_path), tmp_path)
    for word in PRIVATE:
        assert word not in seen, word
    for key in list(app.discovery.data) + list(app.progress.data):
        assert not any(word in key for word in PRIVATE)
    # A second run presses nothing again.
    page.presses.clear()
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert page.presses == []


def test_a_pdf_that_does_not_name_its_document_goes_to_review(tmp_path, monkeypatch):
    page = Page(documents=DOCS[:1])

    def brings(page, d):
        wrong = text_pdf(["Statement Date 09/12/2031"] + ["line %d" % n for n in range(12)])
        page.fire("request", Req(pdf_url(d["documentId"])))
        page.fire("download", Download(BLOB, d["documentFilename"], wrong))
    page.on_press = brings
    app = make_app(tmp_path, monkeypatch, page)
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert not list((tmp_path / "out" / "Statements").glob("*.pdf"))
    assert list(app.paths.manual_review.glob("*.pdf"))
    rec = next(iter(app.progress.data.values()))
    assert rec["state"] == docs.State.NEEDS_MANUAL_REVIEW.value


def test_discover_keeps_no_id_and_says_the_date_the_documents_go(tmp_path, monkeypatch):
    page = Page()
    app = make_app(tmp_path, monkeypatch, page)
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.cmd_discover()
    assert "Simmons Bank keeps this paid-off loan's documents available until 2032-06-30." \
        in buf.getvalue()
    stored = json.dumps(app.discovery.data)
    for word in PRIVATE:
        assert word not in stored, word
    assert page.presses == []


def test_one_id_under_two_dates_stops_the_list_and_keeps_the_record(tmp_path, monkeypatch):
    page = Page()
    app = make_app(tmp_path, monkeypatch, page)
    with redirect_stdout(io.StringIO()):
        app.cmd_discover(quiet=True)
    before = dict(app.discovery.data)
    page.docs[0]["date"] = "2031-10-20"
    with redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.discovery.data == before


def test_the_key_and_the_tie_breaker_hold_no_id():
    h = site.record_hash(D1)
    d = docs.Document(title="Loan Periodic Statement October 2031", category="Statement",
                      date="2031-10-13", document_id=h, kind="statement")
    assert d.key == "id:" + h[:20] and D1 not in d.key
    tie = docs.told_apart_by(d.to_dict())
    assert len(tie) == 6 and tie not in D1
    assert docs.told_apart_by({}) == ""


def test_the_private_words_are_redacted_once_the_page_is_read():
    site.collect_download_docs(Page(), site.Run())
    text = "user %s account %s %s ending %s for %s, document %s at %s" % (
        USER, ACCOUNT, NUMBER, LAST4, OWNER, D1, BLOB)
    out = site.redact(text)
    for word in PRIVATE:
        assert word not in out, word


def test_the_dates_and_the_banks_own_words_stay_readable():
    """Only what names the account holder is private. A date, the words of
    the bank's addresses and the documents' own titles stay as they are in
    the run's own lines."""
    site.set_private_words([])
    site.collect_download_docs(Page(), site.Run())
    line = "the document dated 2031-10-13, Loan Periodic Statement, consumer users accounts 13 10"
    assert site.redact(line) == line


def test_diagnose_reads_counts_only():
    page = Page()
    run = site.Run()
    site.read_listing(page, run)
    info = site.survey(page, dwell_ms=0, run=run)
    got = info["pages"][0]
    assert got["document_rows"] == 4 and got["accounts_in_rows"] == 1
    assert got["notice_rows"] == 2 and got["available_until_heard"] is True
    blob = json.dumps(info) + json.dumps([d.__dict__ for d in site.collect_documents(page)])
    for word in PRIVATE + ["Prime Rate", "Loan Periodic"]:
        assert word not in blob, word
    assert page.presses == []


def test_the_failure_file_names_its_provider():
    src = (HERE / "simmons_docs.py").read_text(encoding="utf-8")
    assert "provider='Simmons Bank'" in src and "Bilt" not in src
    assert "bilt" not in (HERE / "simmons_site.py").read_text(encoding="utf-8")


def test_a_tax_title_that_begins_with_the_form_reports_the_year_before_it_was_issued():
    """Live the title is "1098 Tax Reporting January 2031": a January 1098
    reports the calendar year just ended, so the file says 2030."""
    assert site.tax_year("1098 Tax Reporting January 2031") == "2030"
    assert site.tax_year("2030 Tax Reporting January 2031") == "2030"
    assert site.tax_year("Tax Reporting January 2031") == ""
    assert site.summary_for("tax", "1098 Tax Reporting January 2031") == "Tax Reporting 2030"
    pdf = text_pdf(["Simmons Bank", "Form 1098 Mortgage Interest Statement", "For calendar year 2030"]
                   + ["line %d" % n for n in range(12)])
    assert site.pdf_names_document(pdf, "tax", "1098 Tax Reporting January 2031", "2031-01-21")[0]
    other = text_pdf(["Form 1098", "For calendar year 2029"] + ["line %d" % n for n in range(12)])
    assert not site.pdf_names_document(other, "tax", "1098 Tax Reporting January 2031", "2031-01-21")[0]
    # A wrong year's form that prints the issue month, "January 2031", or the
    # list's date is still the wrong year: only the tax year names a tax form.
    wrong = text_pdf(["Form 1098", "For calendar year 2029", "January 2031", "01/21/2031"]
                     + ["line %d" % n for n in range(12)])
    ok, report = site.pdf_names_document(wrong, "tax", "1098 Tax Reporting January 2031", "2031-01-21")
    assert not ok and report == {"pdf": True, "tax_year": False, "tax_form": True}
    no_form = text_pdf(["For calendar year 2030"] + ["line %d" % n for n in range(12)])
    assert not site.pdf_names_document(no_form, "tax", "1098 Tax Reporting January 2031", "2031-01-21")[0]


def test_a_date_printed_a_few_days_off_in_the_titles_month_names_the_document():
    """Live a statement listed on the 11th prints "Statement Date 04/13/30"
    and nothing on the 11th, and a notice listed on the 5th prints
    "Effective Date 8/05/30". A date more than three days before or ten
    days after the list date, or in another month, does not count, and
    nothing is read into a date that is part of a longer number."""
    filler = ["line %d" % n for n in range(12)]
    pdf = text_pdf(["Mortgage Statement", "Statement Date   04/13/30", "Payment Due Date 05/05/30"] + filler)
    ok, report = site.pdf_names_document(pdf, "statement", "Loan Periodic Statement April 2030", "2030-04-11")
    assert ok and report["nearby_date"] == 2
    pdf = text_pdf(["NOTICE OF INTEREST RATE CHANGE", "New Rate 7.250%   Effective Date   8/05/30"] + filler)
    ok, report = site.pdf_names_document(pdf, "notice", "Prime Rate Notice August 2030", "2030-08-05")
    assert ok and report["nearby_date"] == 0
    pdf = text_pdf(["NOTICE OF ADDRESS CHANGE", "February 18, 2031"] + filler)
    assert site.pdf_names_document(pdf, "notice", "Notice of Address Change (Previous Address) February 2031", "2031-02-17")[0]
    for lines, title, iso in [
            (["Statement Date 04/25/30"], "Loan Periodic Statement April 2030", "2030-04-11"),
            (["Statement Date 04/07/30"], "Loan Periodic Statement April 2030", "2030-04-11"),
            (["Statement Date 05/02/30"], "Loan Periodic Statement April 2030", "2030-04-30"),
            (["Statement Date 04/13/29"], "Loan Periodic Statement April 2030", "2030-04-11"),
            (["Account 104/13/30"], "Loan Periodic Statement April 2030", "2030-04-11"),
            (["Statement Date 04/13/30"], "Loan Periodic Statement March 2030", "2030-04-11")]:
        ok, report = site.pdf_names_document(text_pdf(lines + filler), "statement", title, iso)
        assert not ok and report["nearby_date"] is None, (lines, title, iso)
    # The window's edges, three days before and ten after, both inclusive.
    for lines, iso, want in [(["Statement Date 04/08/30"], "2030-04-11", -3), (["Statement Date 04/07/30"], "2030-04-11", None),
                             (["Statement Date 04/21/30"], "2030-04-11", 10), (["Statement Date 04/22/30"], "2030-04-11", None)]:
        ok, report = site.pdf_names_document(text_pdf(lines + filler), "statement", "Loan Periodic Statement April 2030", iso)
        assert report["nearby_date"] == want and ok is (want is not None), (lines, want)
    # A title naming no month leaves the list date's own month as the bound.
    ok, report = site.pdf_names_document(text_pdf(["Effective Date 4/13/30"] + filler), "notice", "Rate Notice", "2030-04-11")
    assert ok and report["nearby_date"] == 2
    ok, report = site.pdf_names_document(text_pdf(["Effective Date 5/02/30"] + filler), "notice", "Rate Notice", "2030-04-30")
    assert not ok and report["nearby_date"] is None
    assert site.nearby_date_offset("", "2030-04-11", "2030-04") is None
    assert site.nearby_date_offset("04/13/30", "not a date", "2030-04") is None


def the_panel_reads_it_all_taken(monkeypatch, tmp_path, app):
    """What the control panel makes of this run's real records, by its own
    code. A run says nothing of a document it leaves, so these are what stop
    it settling a gap (#149)."""
    monkeypatch.syspath_prepend(str(HERE.parents[1] / "gui"))
    panel = pytest.importorskip("app")
    return panel._took_everything({"script_name": "simmons_docs.py", "dir": str(tmp_path)},
                                  "primary", app.paths.root, {})


def test_a_row_turned_off_is_left_for_the_panel_too(tmp_path, monkeypatch):
    """Its Run All lists the document, leaves no record of it, finishes
    clean, and the next run takes it. Each of the two reads as it is."""
    page = Page()
    app = make_app(tmp_path, monkeypatch, page)
    real = site.pressing.press_once
    tried = []

    def off_once(*a, **kw):
        tried.append(1)
        if len(tried) == 1:
            raise pressing.TurnedOff("save the document", "the control is turned off", ["off"])
        return real(*a, **kw)

    with monkeypatch.context() as turned_off:
        turned_off.setattr(site.pressing, "press_once", off_once)
        with redirect_stdout(io.StringIO()) as said:
            app.cmd_run("all")
    assert "left for the next run" in said.getvalue()
    assert app.stats["manual_review"] + app.stats["failed"] == 0
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is False
    with redirect_stdout(io.StringIO()):
        app.cmd_run("all")
    assert the_panel_reads_it_all_taken(monkeypatch, tmp_path, app) is True
