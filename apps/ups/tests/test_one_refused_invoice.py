"""One invoice UPS refuses on its own fails alone.

A 401, a 403 or a redirect off ups.com for one invoice's PDF was read as a
sign-out, so the run stopped at that invoice. An invoice UPS will not give
is refused on every run, so every run stopped there and Continue stopped
at it again, the loop of #124. Now My Invoices is read again when one
invoice is refused, the same way Discover reads it. A session that ended
is refused the list too, and that stops the run. A list that still reads
leaves the invoice failed alone, nothing saved, and the next run tries it
again. The invoice is asked for once.
"""
import base64
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import ups_site as site  # noqa: E402
import ups_docs as docs  # noqa: E402
from paperpull_core import testkit  # noqa: E402

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
    refusal (`signs_out`) answers the list with a 401 from then on."""

    def __init__(self, refused=(), refusal="401", signs_out=False):
        self.url = site.BASE + "/home"
        self.refused, self.refusal, self.signs_out = set(refused), REFUSALS[refusal], signs_out
        self.list_status, self.rows = 200, ROWS
        self.listeners, self.asked, self.lists_read = [], [], 0

    def on(self, _event, fn):
        self.listeners.append(fn)

    def remove_listener(self, _event, fn):
        self.listeners.remove(fn)

    def goto(self, url, **_):
        self.url = url
        if url != site.INVOICES_PAGE:
            return
        self.lists_read += 1
        if self.rows is None:
            return
        for resp in [Resp('{"invoiceStatus":["OPEN"]}', []), Resp("{}", self.rows, self.list_status)]:
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
            if self.signs_out:
                self.list_status = 401
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
def test_a_list_read_empty_after_a_refusal_is_no_list(tmp_path, rows):
    """A list that shows nothing, or never came, after this invoice was
    listed is not a list that still reads."""
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403")
    site.collect_download_docs(page)
    page.rows = rows
    with pytest.raises(site.SessionExpired):
        take(page, tmp_path / "i.pdf")
    assert page.asked == [row(2)["invoiceNumber"]]


def test_the_list_read_after_a_refusal_serves_the_next_invoice(tmp_path):
    page = Page(refused={row(2)["invoiceNumber"]}, refusal="403")
    site.collect_download_docs(page)
    assert take(page, tmp_path / "a.pdf") is False
    assert take(page, tmp_path / "b.pdf", i=1)
    assert (tmp_path / "b.pdf").read_bytes() == PDF
    assert page.lists_read == 2


def make_app(tmp):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args(["--resume", "--config", str(cfg)]))


def run_with(tmp_path, page):
    """A Run All's downloads over the three listed invoices, with what it
    printed."""
    app = make_app(tmp_path)
    for r in site.collect_download_docs(page):
        app._record_rawdoc(r, site.BILLING_URL)
    app.discovery.save()
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


def test_one_invoice_refused_and_the_list_after_it_stop_the_run(tmp_path):
    page = Page(refused={row(3)["invoiceNumber"]}, refusal="401", signs_out=True)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, SystemExit)
    assert "session has expired" in said
    assert "Nothing was saved" not in said
    assert page.asked == [row(3)["invoiceNumber"]]
