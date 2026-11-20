"""Synthetic accounts, dates, IDs and PDFs for the Cloudflare invoice connector."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloudflare_docs as app_mod
import cloudflare_site as site
from paperpull_core.testkit import text_pdf

ACCOUNT = "0" * 32
OTHER = "1" * 32
FIRST = "00000000-0000-0000-0000-000000000001"
SECOND = "00000000-0000-0000-0000-000000000002"
DATE = "2032-02-06"
NUMBERS = {FIRST: "CF-00000001", SECOND: "CF-00000002"}


def entry(invoice_id, **changes):
    row = {"type": "invoice", "source": "stripe", "invoice_id": invoice_id,
           "receipt_id": NUMBERS[invoice_id], "occurred_at": DATE + "T00:00:00Z"}
    row.update(changes)
    return row


class Response:
    def __init__(self, body, content_type="application/json", status=200):
        self._body = body
        self.headers = {"content-type": content_type}
        self.status = status
        self.disposed = False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


class Page:
    def __init__(self, account=ACCOUNT):
        self.url = f"https://dash.cloudflare.com/{account}/billing/invoices"
        self.context = SimpleNamespace(request=SimpleNamespace(get=self.get))
        self.pages = {1: ([entry(FIRST), entry(FIRST, type="credit")], True),
                      2: ([entry(SECOND)], False)}
        self.pdfs = {invoice_id: text_pdf([f"Invoice {number}", "February 6, 2032"])
                     for invoice_id, number in NUMBERS.items()}
        self.history_status = self.pdf_status = 200
        self.pdf_type = "application/pdf"
        self.page_echo = {}
        self.fetched = []
        self.responses = []

    def wait_for_timeout(self, ms):
        assert ms > 0

    def get(self, url, *, max_redirects, timeout, headers, params):
        parsed = urlsplit(url)
        assert (parsed.scheme, parsed.netloc) == ("https", "dash.cloudflare.com")
        assert max_redirects == 0 and timeout > 0
        self.fetched.append((parsed.path, params))
        if parsed.path.endswith("/billing/history"):
            assert headers == {"Accept": "application/json"}
            current = params["page"]
            assert params["per_page"] == 50
            rows, next_page = self.pages[current]
            response = Response(json.dumps({"success": True, "result": rows,
                        "result_info": {"next_page": next_page,
                                        "page": self.page_echo.get(current, current)}}).encode(),
                                status=self.history_status)
        else:
            assert headers == {"Accept": "application/pdf"}
            assert params == {"doctype": "invoice", "isLegacy": "false"}
            assert parsed.path.split("/")[-3] == "receipts"
            response = Response(self.pdfs[parsed.path.split("/")[-2]], self.pdf_type,
                                status=self.pdf_status)
        self.responses.append(response)
        return response


def test_walks_all_pages_and_saves_same_date_invoices_separately(tmp_path):
    page = Page()
    docs = site.collect_download_docs(page)
    assert len(docs) == 2
    assert {d.date_text for d in docs} == {DATE}
    assert len({d.document_id for d in docs}) == 2
    assert [params["page"] for _path, params in page.fetched] == [1, 2]
    for i, (doc, invoice_id) in enumerate(zip(docs, (FIRST, SECOND))):
        target = tmp_path / f"{i}.pdf"
        assert site.download_bill(page, doc.date_text, target,
                                  account=doc.account, document_id=doc.document_id)
        assert target.read_bytes() == page.pdfs[invoice_id]
        assert invoice_id not in repr(doc)
    assert len(page.fetched) == 4
    assert all(response.disposed for response in page.responses)


def test_resume_refreshes_list_and_will_not_download_another_accounts_invoice(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    reopened = Page()
    assert site.download_bill(reopened, DATE, tmp_path / "invoice.pdf",
                              account=doc.account, document_id=doc.document_id)
    assert len(reopened.fetched) == 3
    other = Page(OTHER)
    with pytest.raises(site.ListStopped):
        site.download_bill(other, DATE, tmp_path / "other.pdf", account=doc.account,
                           document_id=doc.document_id)
    assert not other.fetched and not (tmp_path / "other.pdf").exists()


@pytest.mark.parametrize("number, date", [("CF-00000009", "February 6, 2032"),
                                         ("CF-00000001", "February 7, 2032")])
def test_refuses_pdf_with_another_invoice_number_or_date(tmp_path, number, date):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdfs[FIRST] = text_pdf([number, date])
    target = tmp_path / "invoice.pdf"
    assert not site.download_bill(page, DATE, target, account=doc.account, document_id=doc.document_id)
    assert not target.exists()


def test_accepts_cloudflare_pdf_number_extracted_with_a_null_separator():
    assert site._printed_number("Invoice number CF\x0000000001", NUMBERS[FIRST])
    assert not site._printed_number("Other ref XCF-00000001", NUMBERS[FIRST])


@pytest.mark.parametrize("status, content_type", [(403, "application/pdf"),
                                                 (302, "text/html"),
                                                 (200, "text/html")])
def test_a_pdf_refusal_checks_the_list_before_counting_it_as_an_invoice_failure(tmp_path, status, content_type):
    page = Page()
    [first, _] = site.collect_download_docs(page)
    page.pdf_status, page.pdf_type = status, content_type
    target = tmp_path / "invoice.pdf"
    assert not site.download_bill(page, DATE, target, account=first.account,
                                  document_id=first.document_id)
    assert [params["page"] for path, params in page.fetched if path.endswith("/billing/history")] == [
        1, 2, 1, 2]
    assert not target.exists()

    for history_status, error in ((401, site.SessionExpired), (500, site.ListStopped)):
        page = Page()
        site.collect_download_docs(page)
        page.pdf_status, page.pdf_type = status, content_type
        page.history_status = history_status
        with pytest.raises(error):
            site.download_bill(page, DATE, target, account=first.account, document_id=first.document_id)
        assert len(page.fetched) == 4 and not target.exists()


def test_rate_limited_pdf_stops_without_another_request(tmp_path):
    page = Page()
    [first, _] = site.collect_download_docs(page)
    page.pdf_status = 429
    count = len(page.fetched)
    with pytest.raises(site.ListStopped, match="limiting invoice requests"):
        site.download_bill(page, DATE, tmp_path / "invoice.pdf", account=first.account,
                           document_id=first.document_id)
    assert len(page.fetched) == count + 1


@pytest.mark.parametrize("other_url", [
    f"https://dash.cloudflare.com.attacker.example/{ACCOUNT}/billing/invoices",
    f"http://dash.cloudflare.com/{ACCOUNT}/billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}/billing/payment",
])
def test_does_not_request_data_from_an_unrecognized_tab(other_url):
    page = Page()
    page.url = other_url
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert not page.fetched


def test_unfinished_pagination_is_a_list_stop():
    page = Page()
    page.pages[2] = ([], True)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_a_nonempty_page_must_confirm_the_requested_page():
    page = Page()
    page.page_echo[2] = None
    with pytest.raises(site.ListStopped, match="different or incomplete"):
        site.collect_download_docs(page)


def test_a_repeated_page_cannot_complete_the_list():
    page = Page()
    page.pages[2] = (page.pages[1][0], False)
    with pytest.raises(site.ListStopped, match="repeated"):
        site.collect_download_docs(page)


def test_a_mixed_history_still_lists_stripe_invoices_on_all_pages():
    page = Page()
    for n, (rows, next_page) in page.pages.items():
        page.pages[n] = ([{"type": "invoice", "source": "legacy"}, *rows], next_page)
    assert len(site.collect_download_docs(page)) == 2


@pytest.mark.parametrize("malformed", [{"source": None}, {"source": "strpie"}, {"invoice_id": None}])
def test_does_not_silently_skip_an_unreadable_invoice(malformed):
    page = Page()
    page.pages[1] = ([entry(FIRST) | malformed], False)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_answered_empty_list_is_valid():
    page = Page()
    page.pages[1] = ([], False)
    page.page_echo[1] = None
    assert site.collect_download_docs(page) == []


def test_login_needs_an_answer_from_the_selected_accounts_list():
    page = Page()
    assert site.invoice_list_ready(page)
    page.pages[1] = ([], True)
    assert not site.invoice_list_ready(page)
    page.url = "https://dash.cloudflare.com/login"
    checks = len(page.fetched)
    assert not site.invoice_list_ready(page)
    assert len(page.fetched) == checks


@pytest.mark.parametrize("prior_listing_stopped", [False, True])
def test_app_keeps_same_day_filenames_unique_and_resumes_the_account_currently_open(
    tmp_path, monkeypatch, prior_listing_stopped,
):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic Owner", "output_dir": str(tmp_path), "min_pdf_bytes": 100,
    }), encoding="utf-8")
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    active = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: active)
    if prior_listing_stopped:
        active.history_status = 500
        with pytest.raises(SystemExit):
            app.cmd_discover(quiet=True)
        assert not app.discovery.data
    else:
        assert app.cmd_discover(quiet=True) == 2
        app.process(app._select())

    active = Page(OTHER)
    app.cmd_resume()
    assert len(active.fetched) == 4
    resumed = [rec for rec in app.progress.data.values() if rec["account"] == site.account_tag(active)]
    assert len(resumed) == 2 and all(rec["downloaded_ok"] for rec in resumed)
    saved = [Path(rec["pdf_path"]) for rec in app.progress.data.values()]
    assert len(set(saved)) == len(saved) == (2 if prior_listing_stopped else 4)
    assert {path.read_bytes() for path in saved} == set(active.pdfs.values())
    assert app._select(pending_only=True) == []


class _Fields:
    """A page's password fields, drawn or not, as a locator counts them."""

    def __init__(self, url, drawn, hidden):
        self.url, self.drawn, self.hidden = url, drawn, hidden

    def locator(self, selector):
        count = self.drawn + (0 if ":visible" in selector else self.hidden)
        return SimpleNamespace(count=lambda: count)


def test_a_password_field_reads_as_signed_out_whether_drawn_or_not():
    url = f"https://dash.cloudflare.com/{ACCOUNT}/billing/invoices"
    assert site.looks_signed_out(_Fields(url, drawn=0, hidden=1))
    assert site.looks_signed_out(_Fields(url, drawn=1, hidden=0))
    assert not site.looks_signed_out(_Fields(url, drawn=0, hidden=0))
    assert not site.looks_signed_out(_Fields("https://example.test/login", drawn=1, hidden=1))


def _app(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic Owner", "output_dir": str(tmp_path), "min_pdf_bytes": 100,
    }), encoding="utf-8")
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    return app


def test_legacy_invoices_the_app_does_not_save_are_counted_and_said(tmp_path, monkeypatch, capsys):
    page = Page()
    legacy = {"type": "invoice", "source": "legacy"}
    page.pages[1] = ([legacy, entry(FIRST), legacy], True)
    page.pages[2] = ([entry(SECOND), legacy], False)
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    capsys.readouterr()
    assert app.cmd_discover(quiet=True) == 2
    said = capsys.readouterr().out
    assert "3 older Cloudflare invoices" in said and "not saved" in said, said
    assert site.legacy_count() == 3


def test_a_history_with_no_legacy_invoice_says_nothing_of_them(tmp_path, monkeypatch, capsys):
    page = Page()
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    assert "older Cloudflare invoice" not in capsys.readouterr().out
    assert site.legacy_count() == 0


def test_a_stopped_list_leaves_no_legacy_count_of_an_earlier_one():
    page = Page()
    page.pages[1] = ([{"type": "invoice", "source": "legacy"}, entry(FIRST)], True)
    site.collect_download_docs(page)
    assert site.legacy_count() == 1
    page.history_status = 500
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert site.legacy_count() == 0
