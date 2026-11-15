"""FedEx Billing Online, the site layer. The guard, the host allowlist,
reading invoice rows out of answers of unknown shape, the connect-account
stop, and the download, all against made-up answers. No real account, no
network."""
import base64
import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import fedex_site as site
from paperpull_core import doc_types, testkit

PDF = b"%PDF-1.4 fake"
API = "https://api.fedex.com"


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "FedEx"
    assert storage.SPEC.routes == {"Statement": "statements"}
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_the_title_discovery_writes_classifies():
    got = doc_types.classify_document("Shipping Invoice", doc_types.load_rules())
    assert (got[0], got[1]) == ("Statement", "Shipping Invoice")


@pytest.mark.parametrize("value,iso", [
    ("2031-02-14", "2031-02-14"), ("2031-02-14T00:00:00Z", "2031-02-14"),
    ("02/14/2031", "2031-02-14"), ("2/30/2031", None), ("soon", None),
])
def test_dates_in_the_shapes_an_api_might_use(value, iso):
    assert site.parse_date(value) == iso


def test_unix_dates_in_seconds_or_milliseconds():
    assert site.iso_from_unix(1928534400) == "2031-02-11"
    assert site.iso_from_unix(1928534400000) == "2031-02-11"
    assert site.iso_from_unix(5) == ""
    assert site.iso_from_unix(True) == ""


def test_invoice_rows_are_found_however_deep_the_answer_nests_them():
    answers = [
        {"path": "/bill/v1/accounts/balancesummaries/retrieve", "status": 200,
         "body": {"output": {"balances": [{"amount": 3}]}}},
        {"path": "/bill/v1/invoices/retrieve", "status": 200,
         "body": {"output": {"invoices": [
             {"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14",
              "pdfUrl": "https://www.fedex.com/doc/INV-2.pdf"},
             {"invoiceNumber": "INV-1", "invoiceDate": "01/24/2031"},
             {"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14"},
             {"invoiceNumber": "INV-9", "invoiceDate": "someday"}]}}},
    ]
    docs = site.invoices_in(answers)
    assert [(d["id"], d["date"], d["link"]) for d in docs] == [
        ("INV-2", "2031-02-14", "https://www.fedex.com/doc/INV-2.pdf"),
        ("INV-1", "2031-01-24", "")]
    assert all(d["title"] == "Shipping Invoice" for d in docs)


def test_a_row_that_does_not_look_like_an_invoice_is_left_alone():
    assert site.invoice_doc({"trackingNumber": "1", "shipDate": "2031-02-14"}) is None
    assert site.invoice_doc({"invoiceNumber": "INV-1"}) is None


def test_a_link_off_fedex_is_never_taken():
    assert site.row_link({"pdfUrl": "https://evil.test/x.pdf"}) == ""
    assert site.row_link({"pdfUrl": "http://www.fedex.com/x.pdf"}) == ""
    assert site.row_link({"document": {"url": "https://documentapi.prod.fedex.com/d"}}) == ""
    assert site.row_link({"documentUrl": {"url": "https://documentapi.prod.fedex.com/d"}}) == \
        "https://documentapi.prod.fedex.com/d"


def test_only_billing_answers_from_the_api_are_kept():
    assert site.is_billing_answer(API + "/bill/v1/invoices/retrieve")
    assert not site.is_billing_answer(API + "/user/v2/login")
    assert not site.is_billing_answer("https://www.fedex.com/bill/v1/x")


class _Resp:
    def __init__(self, url, body, status=200):
        self.url, self._body, self.status = url, body, status

    def json(self):
        return self._body


class _Page:
    """A signed-in fedex.com tab. Opening the invoices page makes it
    receive the scripted answers, or land on the connect-account form. An
    answer is (address, body) for a 200, or (address, body, status)."""

    def __init__(self, answers, connect=False, fetch=None):
        self.url = "https://www.fedex.com/en-us/logged-in-home.html"
        self.answers, self.connect, self.fetch = answers, connect, fetch or {}
        self.listeners, self.fetched = [], []

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        if url == site.INVOICES_PAGE and self.connect:
            self.url = "https://www.fedex.com/register/connect-account/ean?linkApp=fbo"
            return
        self.url = url
        for u, body, *status in self.answers:
            for fn in list(self.listeners):
                fn(_Resp(u, body, *status))

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, url):
        self.fetched.append(url)
        return self.fetch[url]


INVOICES = [(API + "/bill/v1/invoices/retrieve",
             {"invoices": [{"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14",
                            "pdfUrl": "https://www.fedex.com/doc/INV-2.pdf"}]}),
            ("https://www.fedex.com/etc/other.json", {"invoices": [{"invoiceNumber": "X", "invoiceDate": "2031-01-01"}]})]


def _fresh():
    site._captured.update(at=0.0, answers=[])


def test_discovery_keeps_only_billing_answers_the_page_received():
    _fresh()
    page = _Page(INVOICES)
    docs = site.collect_download_docs(page)
    assert [(d.document_id, d.date_text) for d in docs] == [("INV-2", "2031-02-14")]
    assert page.listeners == []


def test_an_unconnected_account_stops_and_is_never_connected():
    _fresh()
    with pytest.raises(site.NeedsPerson):
        site.collect_download_docs(_Page([], connect=True))


def test_the_download_takes_the_rows_own_link_and_writes_only_a_pdf(tmp_path):
    _fresh()
    link = "https://www.fedex.com/doc/INV-2.pdf"
    page = _Page(INVOICES, fetch={link: {"status": 200, "ct": "application/pdf", "url": link,
                                         "b64": base64.b64encode(PDF).decode()}})
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="INV-2")
    assert out.read_bytes() == PDF
    page.fetch[link] = {"status": 200, "ct": "text/html", "url": link}
    _fresh()
    assert not site.download_bill(page, None, "2031-02-14", tmp_path / "j.pdf", document_id="INV-2")
    assert not (tmp_path / "j.pdf").exists()


def test_an_invoice_without_a_link_goes_to_the_person(tmp_path):
    _fresh()
    page = _Page([(API + "/bill/v1/invoices/retrieve",
                   {"invoices": [{"invoiceNumber": "INV-1", "invoiceDate": "2031-01-24"}]})])
    with pytest.raises(site.NeedsPerson):
        site.download_bill(page, None, "2031-01-24", tmp_path / "i.pdf", document_id="INV-1")


@pytest.mark.parametrize("after", ["sign-in", "list 401", "list 403"])
def test_a_sign_in_page_where_the_list_was_stops_the_run(tmp_path, after):
    """The list read for an invoice shows the sign-in page, or Billing
    Online refuses it, so nothing is asked for. A refused list was read as
    one with no invoice in it, and the invoice went to the person."""
    _fresh()
    page = _Opens(INVOICES, after=after, from_fetch=0,
                  fetch={LINK: {"status": 200, "ct": "application/pdf", "url": LINK,
                                "b64": base64.b64encode(PDF).decode()}})
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2")
    assert page.fetched == []
    assert not (tmp_path / "i.pdf").exists()


# What one invoice's PDF can be answered with that reads as a sign-out, a
# 401, a 403, and a redirect that ends off fedex.com.
LINK = "https://www.fedex.com/doc/INV-2.pdf"
REFUSALS = {
    "401": {"status": 401, "ct": "text/html", "url": LINK},
    "403": {"status": 403, "ct": "text/html", "url": LINK},
    "redirect": {"status": 200, "ct": "text/html", "url": "https://sign-in.example/made-up"},
}


OFF_FEDEX = "chrome-error://chromewebdata/"


class _Opens(_Page):
    """_Page, counting each time the invoices page is opened. `after`
    says what the invoices page does once `from_fetch` PDFs were asked
    for, list as before, land on a sign-in page, list nothing, or the
    connect form. "off fedex" leaves the tab on an error page once a PDF
    was asked for, where fedex.com does not open again."""

    def __init__(self, answers, after="list", from_fetch=1, **kw):
        super().__init__(answers, **kw)
        self.after, self.from_fetch, self.opened = after, from_fetch, 0

    def evaluate(self, js, url):
        got = super().evaluate(js, url)
        if self.after == "off fedex" and len(self.fetched) >= self.from_fetch:
            self.url = OFF_FEDEX
        return got

    def goto(self, url, **kw):
        if self.url == OFF_FEDEX:
            raise RuntimeError("net::ERR_INTERNET_DISCONNECTED (made up)")
        if url == site.INVOICES_PAGE:
            self.opened += 1
            changed = len(self.fetched) >= self.from_fetch
            if changed and self.after == "sign-in":
                self.url = "https://www.fedex.com/secure-login/made-up"
                return
            if changed and self.after == "nothing":
                self.url = url
                return
            if changed and self.after == "connect":
                self.connect = True
            if changed and self.after == "timeout":
                raise TimeoutError("Timeout 60000ms exceeded")
            if changed and self.after in LIST_ANSWERS:
                # Billing Online answers the list, with no invoice in it.
                self.url = url
                status, body = LIST_ANSWERS[self.after]
                for fn in list(self.listeners):
                    fn(_Resp(API + "/bill/v1/invoices/retrieve", body, status=status))
                return
        super().goto(url, **kw)


# What Billing Online can answer the invoice list with once an invoice was
# refused, each with no invoice in it. A 401 or a 403 refuses the list,
# which Discover reads as a sign-out, and so does the list read again. A
# 500 or an empty list says nothing of the session, in either.
LIST_ANSWERS = {
    "list 401": (401, {"errors": [{"code": "NOT.AUTHORIZED"}]}),
    "list 403": (403, None),
    "list 500": (500, None),
    "list empty": (200, {"output": {"invoices": []}}),
}


@pytest.mark.parametrize("kept", [False, True])
@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_an_invoice_refused_while_the_list_still_reads_fails_alone(tmp_path, how, kept):
    """A 401, a 403 or a redirect for one invoice was read as a sign-out,
    so every run stopped at that invoice and Continue stopped there again
    (#124). The list is read again with the call Discover reads it with,
    and a list that still shows invoices leaves the refusal that invoice's
    own."""
    _fresh()
    page = _Opens(INVOICES, fetch={LINK: dict(REFUSALS[how])})
    if kept:
        site.collect_download_docs(page)
    before = page.opened
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="INV-2") is False
    assert not out.exists()
    # The invoice is asked for once, never a second time, and the list is
    # read once more after the refusal.
    assert page.fetched == [LINK]
    assert page.opened - before == (1 if kept else 2)
    assert page.listeners == []


def test_the_list_read_after_a_refusal_serves_the_next_invoice(tmp_path):
    _fresh()
    page = _Opens(INVOICES, fetch={LINK: dict(REFUSALS["403"])})
    site.collect_download_docs(page)
    assert site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2") is False
    page.fetch[LINK] = {"status": 200, "ct": "application/pdf", "url": LINK,
                        "b64": base64.b64encode(PDF).decode()}
    out = tmp_path / "j.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="INV-2")
    assert out.read_bytes() == PDF
    assert page.opened == 2


SIGNED_OUT = ["sign-in", "list 401", "list 403"]


@pytest.mark.parametrize("after", SIGNED_OUT)
def test_an_invoice_refused_and_a_sign_in_page_after_it_is_a_sign_out(tmp_path, after):
    """A session that ended shows the sign-in page where the list was, or
    has the list refused with a 401 or a 403, and only that stops the run
    as signed out. A refused list with no invoice in it was read as a list
    that did not answer, since Discover read it as an empty one, so the run
    stopped with the list unread and never said the session had ended."""
    _fresh()
    page = _Opens(INVOICES, after=after, fetch={LINK: dict(REFUSALS["401"])})
    site.collect_download_docs(page)
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2")
    assert not (tmp_path / "i.pdf").exists()
    assert page.fetched == [LINK] and page.opened == 2
    assert page.listeners == []


UNREAD = ["nothing", "list 500", "list empty", "timeout", "off fedex"]


@pytest.mark.parametrize("after", UNREAD)
def test_an_invoice_refused_and_a_list_that_does_not_answer_after_it_is_unread(tmp_path, after):
    """A list that never came, answered with an error, held no invoice or
    timed out says nothing Discover reads as a sign-out. It was read as one,
    or the timeout reached the loop as the invoice's own failure and the
    run went on with no session shown. Now it stops the run with the list
    unread. So does a tab that fedex.com no longer opens in, which was read
    as a sign-out though nothing on it was a sign-in page."""
    _fresh()
    page = _Opens(INVOICES, after=after, fetch={LINK: dict(REFUSALS["403"])})
    site.collect_download_docs(page)
    with pytest.raises(site.ListStopped) as got:
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2")
    assert not isinstance(got.value, site.SessionExpired)
    assert not (tmp_path / "i.pdf").exists()
    # A tab fedex.com does not open in never reaches the invoices page.
    assert page.fetched == [LINK] and page.opened == (1 if after == "off fedex" else 2)
    assert page.listeners == []


def test_an_invoice_refused_and_the_connect_form_after_it_stops_as_not_connected(tmp_path):
    _fresh()
    page = _Opens(INVOICES, after="connect", fetch={LINK: dict(REFUSALS["403"])})
    site.collect_download_docs(page)
    with pytest.raises(site.NotConnected):
        site.download_bill(page, None, "2031-02-14", tmp_path / "i.pdf", document_id="INV-2")
    assert page.fetched == [LINK]


# -- the run ---------------------------------------------------------------------

LINK_1 = "https://www.fedex.com/doc/INV-1.pdf"
TWO_INVOICES = [(API + "/bill/v1/invoices/retrieve",
                 {"invoices": [{"invoiceNumber": "INV-2", "invoiceDate": "2031-02-14", "pdfUrl": LINK},
                               {"invoiceNumber": "INV-1", "invoiceDate": "2031-01-24",
                                "pdfUrl": LINK_1}]})]
GOOD = {"status": 200, "ct": "application/pdf",
        "b64": base64.b64encode(testkit.text_pdf(["FedEx made-up invoice INV-1"])).decode()}


def _app(tmp_path, command):
    """The app over a made-up install in tmp_path, for one command."""
    import fedex_docs as docs
    config = json.loads((Path(docs.__file__).parent / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(tmp_path / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "min_pdf_bytes": 10})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args([command, "--config", str(cfg)]))


def _run(tmp_path, page):
    """A Run All over the two invoices Discover listed, the newest asked
    for first, with how it ended and what it printed."""
    import contextlib
    import io
    app = _app(tmp_path, "--resume")
    _fresh()
    for r in site.collect_download_docs(page):
        app._record_rawdoc(r, site.BILLING_URL)
    app.discovery.save()
    app.check_session = lambda p: None
    app._on_its_site = lambda: page
    app._dl_dir = None
    app._delay = lambda *a, **k: None
    seen, ended = io.StringIO(), None
    try:
        with contextlib.redirect_stdout(seen):
            app.process(app._select())
    except SystemExit as e:
        ended = e
    return app, ended, " ".join(seen.getvalue().split())


@pytest.mark.parametrize("after", UNREAD)
def test_an_invoice_refused_and_a_list_that_does_not_answer_stop_the_run_unread(tmp_path, after):
    """The run stops at the refused invoice with nothing recorded against
    it, the listing is noted as one that stopped, and the panel offers a
    run that lists first, not Continue, which would read the same list
    for the same invoice and stop there again (#124)."""
    from paperpull_core import listing
    from paperpull_core.run_reporting import ListNotRead
    page = _Opens(TWO_INVOICES, after=after,
                  fetch={LINK: dict(REFUSALS["403"], url=LINK), LINK_1: dict(GOOD, url=LINK_1)})
    app, ended, said = _run(tmp_path, page)
    assert isinstance(ended, ListNotRead), (type(ended), said)
    assert "could not be read again" in said
    assert "session has expired" not in said and "signed out" not in said
    assert listing.last(app) == listing.STOPPED
    assert page.fetched == [LINK]
    assert all(v.get("state") != "Failed" for v in app.progress.data.values())
    assert app.stats["failed"] == 0


def test_an_invoice_refused_while_the_list_reads_fails_alone_in_the_run(tmp_path):
    page = _Opens(TWO_INVOICES, fetch={LINK: dict(REFUSALS["403"], url=LINK),
                                       LINK_1: dict(GOOD, url=LINK_1)})
    app, ended, said = _run(tmp_path, page)
    assert ended is None, said
    states = {v["document_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"INV-2": "Failed", "INV-1": "Completed"}
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert page.fetched == [LINK, LINK_1]


@pytest.mark.parametrize("after", SIGNED_OUT)
def test_an_invoice_refused_and_a_sign_in_page_stop_the_run_signed_out(tmp_path, after):
    from paperpull_core.run_reporting import ListNotRead
    page = _Opens(TWO_INVOICES, after=after,
                  fetch={LINK: dict(REFUSALS["403"], url=LINK), LINK_1: dict(GOOD, url=LINK_1)})
    app, ended, said = _run(tmp_path, page)
    assert isinstance(ended, SystemExit) and not isinstance(ended, ListNotRead), said
    assert "session has expired" in said and "could not be read again" not in said
    assert page.fetched == [LINK]
    assert app.stats["failed"] == 0
    assert all(v.get("state") != "Failed" for v in app.progress.data.values())


# -- Discover, a list refused and a tab fedex.com will not open ---------------------

BALANCE = API + "/bill/v1/accounts/balancesummaries/retrieve"
LIST = API + "/bill/v1/invoices/retrieve"

# Billing Online refusing every call the invoices page made, each with a
# 401 or a 403, with no invoice anywhere.
REFUSED = {
    "list 401": [(LIST, {"errors": [{"code": "NOT.AUTHORIZED"}]}, 401)],
    "list 403": [(LIST, None, 403)],
    "every call": [(BALANCE, None, 401), (LIST, None, 403)],
}

# Lists with no invoice that are no sign-out. FedEx answered a signed-in
# login's first call with a 401 when its shipping account was not connected
# (2026-09-25), so a call refused while another answered is not one either.
NOT_SIGNED_OUT = {
    "never came": [],
    "list 500": [(LIST, None, 500)],
    "list empty": [(LIST, {"output": {"invoices": []}})],
    "one call answered": [(BALANCE, {"output": {"balances": [{"amount": 3}]}}), (LIST, None, 403)],
    "a 500 beside a 401": [(BALANCE, None, 500), (LIST, None, 401)],
}


@pytest.mark.parametrize("how", sorted(REFUSED))
def test_a_list_billing_online_refused_is_a_sign_out(how):
    """Billing Online refusing the invoices page's calls with a 401 or a 403
    was read as a list with no invoice in it, so Discover finished, noted
    the list as read whole and found nothing new with the session ended."""
    _fresh()
    page = _Page(REFUSED[how])
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert page.listeners == []


@pytest.mark.parametrize("how", sorted(NOT_SIGNED_OUT))
def test_a_list_not_refused_by_every_call_is_no_sign_out(how):
    _fresh()
    assert site.collect_download_docs(_Page(NOT_SIGNED_OUT[how])) == []


class _LateConnect(_Page):
    """_Page that lands on the connect-account form some time after the
    invoices page opened, once that many milliseconds were waited."""

    def __init__(self, answers, after_ms):
        super().__init__(answers)
        self.after_ms, self.waited = after_ms, 0

    def wait_for_timeout(self, ms):
        self.waited += ms
        if self.waited >= self.after_ms and self.url == site.INVOICES_PAGE:
            self.url = "https://www.fedex.com/register/connect-account/ean?linkApp=fbo"


def test_a_refused_call_and_the_connect_form_after_it_is_not_a_sign_out():
    """A refused call followed by the connect form, later than the page's
    answers settle, is an account not connected. A page whose every answer
    refused is watched for the whole wait before it is called signed out,
    so the form is never taken for a sign-out."""
    _fresh()
    page = _LateConnect([(BALANCE, None, 401)], after_ms=8000)
    with pytest.raises(site.NotConnected):
        site.collect_download_docs(page)


class _Off(_Page):
    """A tab on an error page that fedex.com will not open in, or that
    opens on the sign-in page when `lands` is given."""

    def __init__(self, lands=""):
        super().__init__([])
        self.url, self.lands, self.tried = OFF_FEDEX, lands, 0

    def goto(self, url, **_):
        self.tried += 1
        if not self.lands:
            raise RuntimeError("net::ERR_INTERNET_DISCONNECTED (made up)")
        self.url = self.lands


def test_a_tab_fedex_will_not_open_in_stops_the_list_unread():
    """A tab off fedex.com that fedex.com would not open in was called a
    sign-out, which nothing on it said."""
    _fresh()
    with pytest.raises(site.ListStopped) as got:
        site.collect_download_docs(_Off())
    assert not isinstance(got.value, site.SessionExpired)
    assert "fedex.com" in str(got.value)


def test_a_tab_that_opens_on_the_sign_in_page_is_a_sign_out():
    _fresh()
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(_Off(lands=site.URLS["login"]))


def _discover(tmp_path, page):
    """Discover over the page given, with how it ended, what it printed,
    and each address the session check was asked about."""
    import contextlib
    import io
    app = _app(tmp_path, "--discover")
    app.stats["mode"] = "discover"
    _fresh()
    checked = []
    app.page = lambda: page
    app.check_session = lambda p: checked.append(p.url)
    seen, ended = io.StringIO(), None
    try:
        with contextlib.redirect_stdout(seen):
            app.cmd_discover()
    except (SystemExit, Exception) as e:
        ended = e
    return app, ended, " ".join(seen.getvalue().split()), checked


@pytest.mark.parametrize("after", ["list 401", "list 403"])
def test_discover_stops_signed_out_on_a_list_billing_online_refused(tmp_path, after):
    """Discover read the invoice list Billing Online refused as one with
    nothing in it, said Discovery complete and noted the list as read whole
    with the session ended. Now the session check is asked, the list is
    read once more, and a list refused again stops the run as signed out
    with nothing listed."""
    from paperpull_core import listing
    page = _Opens(INVOICES, after=after, from_fetch=0)
    app, ended, said, checked = _discover(tmp_path, page)
    assert type(ended) is SystemExit and ended.code == 0, (ended, said)
    assert "signed out" in said and "Discovery complete" not in said
    assert listing.last(app) == listing.STOPPED
    assert app.discovery.data == {}
    assert page.opened == 2 and checked
    assert page.listeners == []


def test_discover_stops_with_the_list_unread_on_a_tab_fedex_will_not_open(tmp_path):
    """A tab fedex.com would not open in raised SessionExpired, which
    Discover met with the session check and a second read that let it out
    as an error. Nothing on it says the session ended, so Discover stops
    with the list unread and says so."""
    from paperpull_core import listing
    page = _Off()
    app, ended, said, _ = _discover(tmp_path, page)
    assert type(ended) is SystemExit and ended.code == 1, (ended, said)
    assert "could not be read" in said and "signed out" not in said
    assert listing.last(app) == listing.STOPPED
    assert app.discovery.data == {}


def test_discover_stops_signed_out_on_a_tab_that_opens_on_the_sign_in_page(tmp_path):
    """A sign-in page where the list was, seen again after the session
    check, left Discover on SessionExpired, reported as an error."""
    from paperpull_core import listing
    app, ended, said, checked = _discover(tmp_path, _Off(lands=site.URLS["login"]))
    assert type(ended) is SystemExit and ended.code == 0, (ended, said)
    assert "signed out" in said
    assert listing.last(app) == listing.STOPPED
    assert checked


class _ConnectSecond(_Opens):
    """_Opens whose invoices page answers 401 the first time and lands on
    the connect form after that."""

    def __init__(self):
        super().__init__([], after="list 401", from_fetch=0)

    def goto(self, url, **kw):
        if url == site.INVOICES_PAGE and self.opened == 1:
            self.opened += 1
            self.url = "https://www.fedex.com/register/connect-account/ean?linkApp=fbo"
            return
        super().goto(url, **kw)


def test_discover_stops_on_the_connect_form_after_a_refused_list(tmp_path):
    """The list read once more after the session check went out of
    Discover unhandled when it met the connect form."""
    app, ended, said, _ = _discover(tmp_path, _ConnectSecond())
    assert type(ended) is SystemExit and ended.code == 0, (ended, said)
    assert "connect your shipping account" in said and "signed out" not in said


def test_diagnose_carries_shapes_never_values():
    _fresh()
    page = _Page([(API + "/bill/v1/accounts/123456789/invoices",
                   {"invoices": [{"invoiceNumber": "SECRET-1", "invoiceDate": "2031-02-14"}]})])
    report = site.survey(page)
    text = json.dumps(report["api"])
    assert "SECRET" not in text and "123456789" not in text
    assert report["api"]["invoices"] == {"rows": 1, "with_a_link": 0}
    assert site.survey(_Page([], connect=True))["api"]["not_connected"]


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._fetch_file(_Page([]), "https://evil.test/doc.pdf")


def test_paying_shipping_and_account_controls_are_never_safe():
    for name in ["Pay Now", "Make a payment", "Dispute", "Set up autopay", "CONTINUE",
                 "Connect account", "JOIN FOR FREE TODAY", "SHIP A PACKAGE", "SCHEDULE A PICKUP",
                 "RATE & SHIP", "REDIRECT A PACKAGE", "CHANGE ACCOUNT", "Log out", "Settings"]:
        assert not site.is_safe_control(name), name


def test_reading_an_invoice_is_safe():
    for name in ["Invoices", "Download PDF", "View invoice", "Download"]:
        assert site.is_safe_control(name), name


def test_only_fedex_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.fedex.com/online/billing/cbs/invoices")
    assert site.is_safe_url("https://api.fedex.com/bill/v1/x")
    assert not site.is_safe_url("http://www.fedex.com/")
    assert not site.is_safe_url("https://fedex.com.example/")
    assert not site.is_safe_url("https://notfedex.com/")
    assert not site.is_safe_url("https://cdn.appdynamics.com/x.js")
    assert not site.is_safe_url("https://user:pw@www.fedex.com/")


def test_a_list_never_read_is_read_on_a_computer_just_started(tmp_path, monkeypatch):
    """time.monotonic() counts from the computer's start on Windows, so on
    a computer up less than four minutes the list never read passed for a
    fresh one, no link was found, and the invoice went to the person. It
    failed main's CI on 2026-11-09 on a runner just started."""
    _fresh()
    ticks = itertools.count(5.0, 0.5)
    monkeypatch.setattr(site.time, "monotonic", lambda: next(ticks))
    link = "https://www.fedex.com/doc/INV-2.pdf"
    page = _Page(INVOICES, fetch={link: {"status": 200, "ct": "application/pdf", "url": link,
                                         "b64": base64.b64encode(PDF).decode()}})
    out = tmp_path / "i.pdf"
    assert site.download_bill(page, None, "2031-02-14", out, document_id="INV-2")
    assert out.read_bytes() == PDF
