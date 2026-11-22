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


# -- review repairs (review-238.md) ------------------------------------------


class _Tab:
    """A Dashboard tab of the person's, on some page, never closed."""

    def __init__(self, url):
        self.url = url

    def is_closed(self):
        return False


def test_a_dashboard_tab_off_the_invoices_page_is_told_to_open_invoices(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    tab = _Tab(f"https://dash.cloudflare.com/{ACCOUNT}/home/overview")
    monkeypatch.setattr(app, "page", lambda: tab)
    with pytest.raises(SystemExit):
        app._on_its_site()
    said = capsys.readouterr().out
    assert "Invoices and documents" in said and "not open" not in said, said


def test_a_dashboard_tab_on_invoices_is_used_as_before(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    tab = _Tab(f"https://dash.cloudflare.com/{ACCOUNT}/billing/invoices")
    monkeypatch.setattr(app, "page", lambda: tab)
    assert app._on_its_site() is tab


def _download(tmp_path, monkeypatch, change):
    app = _app(tmp_path, monkeypatch)
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    app.cmd_discover(quiet=True)
    change(page)
    doc = app._select()[-1]
    app.download_one(page, doc, "invoice.pdf")
    return app, app.progress.get(doc.key)


def test_a_pdf_that_names_another_invoice_is_counted_as_a_wrong_document(tmp_path, monkeypatch):
    def other(page):
        page.pdfs[FIRST] = page.pdfs[SECOND] = text_pdf(["Invoice CF-00000009", "February 6, 2032"])
    app, rec = _download(tmp_path, monkeypatch, other)
    assert app.stats.get("wrong_document") == 1 and app.stats["failed"] == 1
    assert "did not show this invoice" in rec["notes"], rec["notes"]
    assert "Could not capture" not in rec["notes"]


def test_an_invoice_gone_from_the_list_is_said_as_gone(tmp_path, monkeypatch):
    def gone(page):
        page.pages = {1: ([], False)}
        site._RUN.clear()
    app, rec = _download(tmp_path, monkeypatch, gone)
    assert "no longer listed" in rec["notes"], rec["notes"]
    assert not app.stats.get("wrong_document")


def test_a_refused_pdf_is_said_as_refused(tmp_path, monkeypatch):
    def refuse(page):
        page.pdf_status = 403
    app, rec = _download(tmp_path, monkeypatch, refuse)
    assert "refused" in rec["notes"], rec["notes"]
    assert not app.stats.get("wrong_document")


class _Redirect(Response):
    def __init__(self, location):
        super().__init__(b"", "text/html", 302)
        self.headers["location"] = location


@pytest.mark.parametrize("location", ["/login", "https://dash.cloudflare.com/login?redirect_uri=x",
                                      "https://example.test/login", "/somewhere", ""])
def test_a_history_redirected_anywhere_is_a_list_stop(location):
    page = Page()
    page.context = SimpleNamespace(request=SimpleNamespace(get=lambda url, **kw: _Redirect(location)))
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)


def test_a_history_refused_says_billing_access():
    page = Page()
    page.history_status = 403
    with pytest.raises(site.ListStopped, match="billing access"):
        site.collect_download_docs(page)


def test_a_history_cycling_between_two_pages_stops_at_the_third():
    page = Page()
    first, second = [entry(FIRST)], [entry(SECOND)]
    page.pages = {n: (first if n % 2 else second, True) for n in range(1, 201)}
    with pytest.raises(site.ListStopped, match="repeated"):
        site.collect_download_docs(page)
    assert len(page.fetched) == 3


def test_login_words_print_through_a_plain_windows_console():
    source = (Path(app_mod.__file__)).read_text(encoding="utf-8")
    assert "→" not in source


def test_a_pdf_whose_text_cannot_be_read_is_said_as_unreadable(tmp_path, monkeypatch):
    def broken(page):
        monkeypatch.setattr(site.pdf_reader, "page_texts", lambda *a, **k: 1 / 0)
    app, rec = _download(tmp_path, monkeypatch, broken)
    assert "could not be read" in rec["notes"], rec["notes"]
    assert not app.stats.get("wrong_document")


@pytest.mark.parametrize("printed", ["11/1/2032", "1/11/2032", "11/01/2032", "21/1/2032"])
def test_a_date_found_only_inside_another_date_is_refused(printed):
    assert not site._printed_date(f"Invoice CF-00000001 Date {printed}", "2032-01-01")


@pytest.mark.parametrize("printed", ["1/1/2032", "January 1, 2032", "2032-01-01"])
def test_the_invoice_date_printed_on_its_own_is_found(printed):
    assert site._printed_date(f"Invoice CF-00000001 Date {printed}", "2032-01-01")


def test_a_history_text_with_a_lone_surrogate_half_is_made_whole():
    page = Page()
    row = entry(FIRST)
    row["note"] = "\ud83d"
    page.pages = {1: ([row], False)}
    body = json.dumps({"success": True, "result": [row],
                       "result_info": {"next_page": False, "page": 1}}).encode()
    page.context = SimpleNamespace(request=SimpleNamespace(
        get=lambda url, **kw: Response(body)))
    assert len(site.collect_download_docs(page)) == 1


# -- 0.70.0 reports on #238 ---------------------------------------------------
# A contributor's Dashboard draws Invoices and documents at
# /<account>/settings/billing/invoices, and a signed-out browser's history
# request is answered 403 with the Dashboard API's error code 10000.

SETTINGS = f"https://dash.cloudflare.com/{ACCOUNT}/settings/billing/invoices"


def _errors(*codes):
    return json.dumps({"success": False, "result": None,
                       "errors": [{"code": c, "message": "Synthetic error"} for c in codes]}).encode()


def _answering(page, status, body):
    """page whose history answers status with body, every response kept."""
    def get(url, **kw):
        page.fetched.append((urlsplit(url).path, kw.get("params")))
        response = Response(body, status=status)
        page.responses.append(response)
        return response
    page.context = SimpleNamespace(request=SimpleNamespace(get=get))
    return page


@pytest.mark.parametrize("url", [SETTINGS, SETTINGS + "/", SETTINGS.replace(ACCOUNT, ACCOUNT.upper())])
def test_the_settings_route_of_invoices_is_the_invoices_page(url):
    page = Page()
    page.url = url
    assert site.is_invoice_page_url(url)
    assert site.invoice_list_ready(page)
    assert len(site.collect_download_docs(page)) == 2
    assert {path for path, _ in page.fetched} == {f"/api/v4/accounts/{ACCOUNT}/billing/history"}


def test_the_settings_route_is_the_same_account_as_the_billing_route(tmp_path):
    listed = Page()
    doc = site.collect_download_docs(listed)[0]
    moved = Page()
    moved.url = SETTINGS
    assert site.account_tag(moved) == site.account_tag(listed) == doc.account
    target = tmp_path / "invoice.pdf"
    assert site.download_bill(moved, DATE, target, account=doc.account, document_id=doc.document_id)
    assert target.read_bytes() == moved.pdfs[FIRST]


def test_another_accounts_settings_route_downloads_nothing(tmp_path):
    doc = site.collect_download_docs(Page())[0]
    other = Page(OTHER)
    other.url = SETTINGS.replace(ACCOUNT, OTHER)
    with pytest.raises(site.ListStopped):
        site.download_bill(other, DATE, tmp_path / "other.pdf", account=doc.account,
                           document_id=doc.document_id)
    assert not other.fetched and not (tmp_path / "other.pdf").exists()


@pytest.mark.parametrize("other_url", [
    f"https://dash.cloudflare.com/{ACCOUNT}/settings/billing/invoices/extra",
    f"https://dash.cloudflare.com/{ACCOUNT}/settings/billing/invoicesx",
    f"https://dash.cloudflare.com/{ACCOUNT}/settingsx/billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}/settings/billing",
    f"https://dash.cloudflare.com/{ACCOUNT}/settings/billing/payment",
    f"https://dash.cloudflare.com/{ACCOUNT}/settings/settings/billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}/settings//billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}/foo/settings/billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}%2Fsettings/billing/invoices",
    "https://dash.cloudflare.com/settings/billing/invoices",
    f"https://dash.cloudflare.com/settings/billing/invoices?account={ACCOUNT}",
    f"https://dash.cloudflare.com/{ACCOUNT[:31]}/settings/billing/invoices",
    f"https://dash.cloudflare.com/{ACCOUNT}0/settings/billing/invoices",
    f"https://dash.cloudflare.com.attacker.example/{ACCOUNT}/settings/billing/invoices",
    f"https://x.dash.cloudflare.com/{ACCOUNT}/settings/billing/invoices",
    f"http://dash.cloudflare.com/{ACCOUNT}/settings/billing/invoices",
    f"https://dash.cloudflare.com:8443/{ACCOUNT}/settings/billing/invoices",
    f"https://dash.cloudflare.com@evil.example/{ACCOUNT}/settings/billing/invoices",
])
def test_a_lookalike_of_the_settings_route_requests_nothing(other_url):
    page = Page()
    page.url = other_url
    assert not site.is_invoice_page_url(other_url)
    with pytest.raises(site.ListStopped):
        site.collect_download_docs(page)
    assert not page.fetched


def test_the_query_or_fragment_of_the_settings_route_cannot_choose_the_account():
    page = Page()
    page.url = SETTINGS + f"?account={OTHER}#/{OTHER}/billing/invoices"
    site.collect_download_docs(page)
    assert {path for path, _ in page.fetched} == {f"/api/v4/accounts/{ACCOUNT}/billing/history"}


def test_a_dashboard_tab_on_the_settings_route_is_used(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    tab = _Tab(SETTINGS)
    monkeypatch.setattr(app, "page", lambda: tab)
    assert app._on_its_site() is tab
    assert "not on Invoices" not in capsys.readouterr().out


@pytest.mark.parametrize("codes", [(10000,), (9109, 10000)])
def test_a_history_refused_with_the_signed_out_code_reads_as_signed_out(codes):
    page = _answering(Page(), 403, _errors(*codes))
    with pytest.raises(site.SessionExpired):
        site.collect_download_docs(page)
    assert not site.invoice_list_ready(_answering(Page(), 403, _errors(*codes)))
    assert page.responses and all(r.disposed for r in page.responses)


def test_discover_says_signed_out_on_the_signed_out_code(tmp_path, monkeypatch, capsys):
    app = _app(tmp_path, monkeypatch)
    page = _answering(Page(), 403, _errors(10000))
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    said = capsys.readouterr().out
    assert "signed out before the invoice list could be read" in said, said
    assert "billing access" not in said and "discovery stopped" not in said


def test_a_pdf_refused_while_signed_out_stops_the_run_as_signed_out(tmp_path):
    page = Page()
    [first, _] = site.collect_download_docs(page)
    page.pdf_status = 403
    _answering(page, 403, _errors(10000))
    with pytest.raises(site.SessionExpired):
        site.download_bill(page, DATE, tmp_path / "invoice.pdf", account=first.account,
                           document_id=first.document_id)
    assert not (tmp_path / "invoice.pdf").exists()


@pytest.mark.parametrize("body", [
    _errors(9109), _errors(10001), _errors(1000), _errors(100000), _errors(),
    _errors("10000"), _errors(10000.0), _errors(True),
    b"", b"<html>Forbidden</html>", b'{"errors": [{"code": 10000', b"[10000]",
    json.dumps({"errors": {"code": 10000}}).encode(),
    json.dumps({"errors": "10000"}).encode(),
    json.dumps({"errors": [10000, "10000"]}).encode(),
    json.dumps({"errors": [{"message": "10000"}]}).encode(),
    json.dumps({"result": {"errors": [{"code": 10000}]}}).encode(),
    b'{"errors": [{"code": 10000}]}\xff',
    json.dumps({"errors": [{"code": 10000}], "pad": "x" * site.LIST_BYTES}).encode(),
], ids=lambda body: f"body{len(body)}")
def test_any_other_refusal_of_the_history_still_says_billing_access(body):
    page = _answering(Page(), 403, body)
    with pytest.raises(site.ListStopped, match="billing access"):
        site.collect_download_docs(page)
    assert page.responses and all(r.disposed for r in page.responses)


def test_a_refusal_whose_body_cannot_be_read_still_says_billing_access():
    class Unreadable(Response):
        def body(self):
            raise OSError("synthetic read failure")
    page = Page()
    page.context = SimpleNamespace(request=SimpleNamespace(
        get=lambda url, **kw: page.responses.append(Unreadable(b"", status=403)) or page.responses[-1]))
    with pytest.raises(site.ListStopped, match="billing access"):
        site.collect_download_docs(page)
    assert page.responses[0].disposed


@pytest.mark.parametrize("status, error", [(200, site.ListStopped), (500, site.ListStopped),
                                           (401, site.SessionExpired)])
def test_the_signed_out_code_outside_a_refusal_keeps_its_old_meaning(status, error):
    with pytest.raises(error):
        site.collect_download_docs(_answering(Page(), status, _errors(10000)))


@pytest.mark.parametrize("body, said, not_said", [
    (_errors(10000), "answered the invoice list as signed out", "Open Manage Account"),
    (_errors(9109), "Open Manage Account", "signed out"),
])
def test_login_says_signed_out_only_on_the_signed_out_code(tmp_path, monkeypatch, capsys, body, said,
                                                           not_said):
    app = _app(tmp_path, monkeypatch)
    page = _answering(Page(), 403, body)
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(app, "close", lambda: None)
    app.cmd_login()
    out = capsys.readouterr().out
    assert said in out and not_said not in out and "Success" not in out, out
