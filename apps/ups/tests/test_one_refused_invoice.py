"""One invoice UPS refuses on its own fails alone.

A 401, a 403 or a redirect off ups.com for one invoice's PDF was read as a
sign-out, so the run stopped at that invoice. An invoice UPS will not give
is refused on every run, so every run stopped there and Continue stopped
at it again, the loop of #124. Now My Invoices is read again when one
invoice is refused, the same way Discover reads it. A session that ended
is refused the list too, and that stops the run. A list that still reads
leaves the invoice failed alone, nothing saved, and the next run tries it
again. The invoice is asked for once.

A list that does not answer when it is read again (a 500, a timeout),
never comes or shows no invoice says nothing either way, so the run stops
with the list unread, nothing recorded against the invoice, and a run that
lists first takes it again. It is neither a sign-out nor the invoice's own
failure (the review of 2026-11-13).
"""
import base64
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import ups_site as site  # noqa: E402
import ups_docs as docs  # noqa: E402
from paperpull_core import testkit  # noqa: E402
from paperpull_core.run_reporting import ListNotRead  # noqa: E402

PDF = testkit.text_pdf(["UPS made-up shipping invoice"])
DAYS = {"row3": "2031-03-14", "row2": "2031-02-14", "row1": "2031-01-14"}


def row(i):
    return {"id": f"row{i}", "accountNumber": "A1B2C3", "invoiceNumber": f"0000000INV{i:05d}",
            "invoiceDate": DAYS[f"row{i}"] + "T00:00:00.000Z", "invoiceAmount": 2.73,
            "invoiceType": "100", "businessUnit": "EBS", "countryCode": "US", "recordType": "ACCOUNT",
            "planNumber": None, "planInvoiceNumber": None}


ROWS = [row(3), row(2), row(1)]

# What one invoice's PDF can be answered with that read as a sign-out.
REFUSALS = {
    "401": {"status": 401, "ct": "application/json", "url": site.DOWNLOAD_API},
    "403": {"status": 403, "ct": "application/json", "url": site.DOWNLOAD_API},
    "redirect off ups.com": {"status": 200, "ct": "text/html", "url": "https://sign-in.example.test/x"},
}


class Req:
    def __init__(self, post):
        self.url, self.post_data = site.LIST_API, post
        self.headers = {"x-csrf-token": "c", "x-sub-token": "s", "instance-id": "i"}

    def all_headers(self):
        return dict(self.headers)


class Resp:
    def __init__(self, post, body, status=200):
        self.url, self._body, self.status = site.LIST_API, body, status
        self.request = Req(post)

    def json(self):
        return self._body


class Page:
    """A signed-in Billing Center tab. Opening My Invoices makes it receive
    the list. Each invoice's PDF is answered from inside the page, refused
    with `refusal` for the invoices in `refused`. A session that ends at the
    refusal (`signs_out`) answers the list with a 401 from then on, and a
    list that stops answering then (`list_then`, a status, "timeout",
    "empty" or "never") answers that way."""

    def __init__(self, refused=(), refusal="401", signs_out=False, list_then=None):
        self.url = site.BASE + "/home"
        self.refused, self.refusal = set(refused), REFUSALS[refusal]
        self.list_then = 401 if signs_out else list_then
        self.list_status, self.rows = 200, ROWS
        self.listeners, self.asked, self.lists_read = [], [], 0
        # Where the next read of My Invoices leaves the tab instead, with
        # the list still received, as when UPS moves it off the Billing
        # Center while the list loads.
        self.lands_off = None

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        if url == site.INVOICES_PAGE and self.list_status == "timeout":
            raise TimeoutError("Timeout 60000ms exceeded")
        self.url = url
        if url != site.INVOICES_PAGE:
            return
        self.lists_read += 1
        if self.lands_off:
            self.url, self.lands_off = self.lands_off, None
        if self.rows is None:
            return
        body = {"error": "made-up server error"} if self.list_status >= 500 else self.rows
        for resp in [Resp('{"invoiceStatus":["OPEN"]}', []), Resp("{}", body, self.list_status)]:
            for fn in list(self.listeners):
                fn(resp)

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, *_):
        class Nothing:
            def count(self):
                return 0
        return Nothing()

    def evaluate(self, _js, args):
        _url, _headers, body = args
        number = body["invoices"][0]["invoiceNumber"]
        self.asked.append(number)
        if number in self.refused:
            if self.list_then in ("empty", "never"):
                self.rows = [] if self.list_then == "empty" else None
            elif self.list_then is not None:
                self.list_status = self.list_then
            return dict(self.refusal)
        return {"status": 200, "ct": "application/pdf", "url": site.DOWNLOAD_API,
                "b64": base64.b64encode(PDF).decode()}


@pytest.fixture(autouse=True)
def fresh():
    site._captured.update(at=0.0, rows=None, headers={})
    yield
    site._captured.update(at=0.0, rows=None, headers={})


def take(page, out, i=2):
    return site.download_bill(page, None, DAYS[f"row{i}"], out, document_id=f"row{i}")


@pytest.mark.parametrize("way", list(REFUSALS))
@pytest.mark.parametrize("kept", [False, True])
def test_an_invoice_refused_while_the_list_still_reads_fails_alone(tmp_path, way, kept):
    page = Page(refused={row(2)["invoiceNumber"]}, refusal=way)
    if kept:
        site.collect_download_docs(page)
    out = tmp_path / "i.pdf"
    assert take(page, out) is False
    assert not out.exists()
    # The list is read once more after the refusal, and the invoice is
    # asked for once, never a second time.
    assert page.lists_read == 2
    assert page.asked == [row(2)["invoiceNumber"]]


@pytest.mark.parametrize("way", list(REFUSALS))
def test_an_invoice_refused_and_the_list_refused_after_it_is_a_sign_out(tmp_path, way):
    page = Page(refused={row(2)["invoiceNumber"]}, refusal=way, signs_out=True)
    out = tmp_path / "i.pdf"
    with pytest.raises(site.SessionExpired):
        take(page, out)
    assert not out.exists()
    assert page.asked == [row(2)["invoiceNumber"]]


@pytest.mark.parametrize("rows", [[], None])
def test_a_list_read_empty_after_a_refusal_is_unread_not_a_sign_out(tmp_path, rows):
    """A list that shows nothing, or never came, after this invoice was
    listed is not a list that still reads, and nothing in it says the
    session ended."""
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403")
    site.collect_download_docs(page)
    page.rows = rows
    with pytest.raises(site.ListStopped):
        take(page, tmp_path / "i.pdf")
    assert page.asked == [row(2)["invoiceNumber"]]


@pytest.mark.parametrize("then", [500, 503, "timeout"])
def test_a_list_that_does_not_answer_after_a_refusal_is_unread(tmp_path, then):
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403", list_then=then)
    site.collect_download_docs(page)
    out = tmp_path / "i.pdf"
    with pytest.raises(site.ListStopped):
        take(page, out)
    assert not out.exists()
    assert page.asked == [row(2)["invoiceNumber"]]


def test_the_list_read_after_a_refusal_serves_the_next_invoice(tmp_path):
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403")
    site.collect_download_docs(page)
    assert take(page, tmp_path / "a.pdf") is False
    assert take(page, tmp_path / "b.pdf", i=1)
    assert (tmp_path / "b.pdf").read_bytes() == PDF
    assert page.lists_read == 2


OFF_THE_BILLING_CENTER = "https://www.ups.com/us/en/Home.page"


def test_a_tab_off_the_billing_center_stops_unweighed_with_nothing_asked(tmp_path):
    """Where the tab is says nothing about one invoice. A tab off the
    Billing Center when the invoice is about to be asked for stops the
    run as it did, with the invoice never asked and the list not read
    again for it. Weighed against the list, which opens the Billing
    Center again on its way, it failed an invoice never asked for."""
    page = Page()
    page.lands_off = OFF_THE_BILLING_CENTER
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path / "i.pdf")
    assert not (tmp_path / "i.pdf").exists()
    assert page.asked == []
    assert page.lists_read == 1


def make_app(tmp):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args(["--resume", "--config", str(cfg)]))


def run_with(tmp_path, page, then=None):
    """A Run All's downloads over the three listed invoices, with what it
    printed. `then` changes the page once the list is recorded."""
    app = make_app(tmp_path)
    for r in site.collect_download_docs(page):
        app._record_rawdoc(r, site.BILLING_URL)
    app.discovery.save()
    if then:
        then()
    app.check_session = lambda p: None
    app._on_its_site = lambda: page
    app._dl_dir = None   # set where the app opens its page, which this skips
    app._delay = lambda *a, **k: None
    seen = io.StringIO()
    ended = None
    try:
        with redirect_stdout(seen):
            app.process(app._select())
    except SystemExit as e:
        ended = e
    return app, ended, seen.getvalue()


def test_one_invoice_refused_while_the_list_reads_fails_alone_and_the_rest_are_saved(tmp_path):
    """The refused invoice stopped the run before, so the ones after it
    were never asked for, and every later run stopped at it again."""
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403")
    app, ended, said = run_with(tmp_path, page)
    assert ended is None, said
    states = {v["document_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"row3": "Completed", "row2": "Failed", "row1": "Completed"}
    assert (app.stats["failed"], len(app.stats["new_files"])) == (1, 2)
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert "session has expired" not in said
    assert page.asked.count(row(2)["invoiceNumber"]) == 1


def test_a_tab_moved_off_the_billing_center_stops_the_run_and_fails_nothing(tmp_path):
    page = Page()

    def moved_off():
        # The list kept is old, so the first invoice reads it again, and
        # that read leaves the tab off the Billing Center.
        site._captured["at"] = time.monotonic() - site._FRESH_SECONDS - 1
        page.lands_off = OFF_THE_BILLING_CENTER
    app, ended, said = run_with(tmp_path, page, then=moved_off)
    assert isinstance(ended, SystemExit), said
    assert "Nothing was saved" not in said
    assert "Failed" not in {v["state"] for v in app.progress.data.values()}
    assert app.stats["failed"] == 0
    assert page.asked == []


def test_one_invoice_refused_and_the_list_after_it_stop_the_run(tmp_path):
    page = Page(refused={row(3)["invoiceNumber"]}, refusal="401", signs_out=True)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, SystemExit)
    assert "session has expired" in said
    assert "Nothing was saved" not in said
    assert page.asked == [row(3)["invoiceNumber"]]


@pytest.mark.parametrize("then", [500, "timeout", "empty", "never"])
def test_one_invoice_refused_and_the_list_unread_after_it_stop_with_the_list_unread(tmp_path, then):
    """A 500 or a timeout there reached the loop as the invoice's own
    failure, and the run went on with no session shown. A list with no
    invoice, or none at all, was read as a sign-out. Now the run stops with
    the list unread, nothing recorded against the invoice, so Get new
    documents takes it again."""
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403", list_then=then)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, ListNotRead), said
    states = {v["document_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"row3": "Completed"}
    assert app.stats["failed"] == 0
    assert "session has expired" not in said
    assert "Nothing was saved" not in said
    assert "could not be read again" in said
    assert page.asked == [row(3)["invoiceNumber"], row(2)["invoiceNumber"]]
