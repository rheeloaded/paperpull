"""Sonic history, PDF identity, and retry fixtures with invented bills."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sonic_site as site
from paperpull_core.testkit import text_pdf


FIRST = "9000000001"
SECOND = "9000000002"
DATE = "2032-03-01"


def href(invoice_id):
    return f"{site.INVOICE_PATH}?id={invoice_id}&amp;pdf=1"


def row(invoice_id=FIRST, date="Mar 1, 2032", link=None):
    return f'<li class="list-group-item"><div>{date}<br><a title="Download PDF" href="{link or href(invoice_id)}">PDF</a></div></li>'


def history(*rows):
    return '<div class="panel panel-sonic"><ul class="list-group">' + "".join(rows) + "</ul></div>"


def pdf(invoice_id=FIRST, date="03/01/32"):
    return text_pdf(["Sonic", f"Payment Due On: {date}", "Invoice Date: 02/15/32",
                     f"Invoice Number: {invoice_id}"])


class Response:
    def __init__(self, data, mime, status=200):
        self.data = data
        self.headers = {"content-type": mime}
        self.status = status
        self.released = False

    def body(self):
        return self.data

    def dispose(self):
        self.released = True


class Page:
    url = site.URLS["login"]

    def __init__(self):
        self.html = history(row(), row(SECOND)).encode()
        self.pdfs = {FIRST: pdf(), SECOND: pdf(SECOND)}
        self.calls = []
        self.responses = []
        self.pdf_status = 200
        self.history_status = 200
        self.pdf_mime = "application/pdf"
        self.context = SimpleNamespace(request=SimpleNamespace(get=self.get))

    def locator(self, _selector):
        return SimpleNamespace(count=lambda: 0)

    def title(self):
        return "Billing & Payments"

    def get(self, url, *, max_redirects, timeout, headers):
        assert max_redirects == 0 and timeout > 0
        address = urlsplit(url)
        assert (address.scheme, address.netloc) == ("https", site.HOST)
        self.calls.append(url)
        if url == site.DOCUMENTS_URL:
            assert headers == {"Accept": "text/html"}
            response = Response(self.html, "text/html", self.history_status)
        else:
            assert address.path == site.INVOICE_PATH
            assert headers == {"Accept": "application/pdf"}
            query = parse_qs(address.query)
            assert set(query) == {"id", "pdf"} and query["pdf"] == ["1"]
            response = Response(self.pdfs[query["id"][0]], self.pdf_mime, self.pdf_status)
        self.responses.append(response)
        return response


def test_discovers_full_list_and_distinguishes_bills_on_same_date(tmp_path):
    page = Page()
    records = site.collect_download_docs(page)
    assert len({r.document_id for r in records}) == 2
    assert {r.date_text for r in records} == {DATE}
    assert not any(number in repr(records) for number in (FIRST, SECOND))
    for index, (doc, invoice_id) in enumerate(zip(records, [FIRST,SECOND])):
        target = tmp_path/f"{index}.pdf"
        assert site.download_bill(page, doc.date_text, target, document_id=doc.document_id)
        assert target.read_bytes() == page.pdfs[invoice_id]
    assert page.calls.count(site.DOCUMENTS_URL) == 1
    assert all(response.released for response in page.responses)


@pytest.mark.parametrize("forged", [
    f"https://members.sonic.net.other.test{href(FIRST)}",
    f"http://members.sonic.net{href(FIRST)}",
    f"//members.sonic.net{href(FIRST)}",
    f"/account/billing/payment/?id={FIRST}&amp;pdf=1",
    f"{site.INVOICE_PATH}?id={FIRST}&amp;pdf=0",
    f"{href(FIRST)}&amp;id={SECOND}",
    f"{href(FIRST)}#unrecognized",
])
def test_refuses_links_outside_the_observed_pdf_route(forged):
    with pytest.raises(site.ListStopped):
        site._parse_history(history(row(link=forged)))


@pytest.mark.parametrize("unreadable", [
    lambda: history(row(), row()),
    lambda: history(row(), '<li class="list-group-item">Mar 2, 2032</li>'),
    lambda: history(row(date="Feb 30, 2032")),
    lambda: history(row()).replace("</ul>", ""),
    lambda: history(row()) + history(row(SECOND)),
])
def test_incomplete_history_never_looks_successful(unreadable):
    with pytest.raises(site.ListStopped):
        site._parse_history(unreadable())


def test_signed_out_html_does_not_look_like_an_empty_archive():
    with pytest.raises(site.SessionExpired):
        site._parse_history('<form><input type="password"></form>')


@pytest.mark.parametrize("data", [
    pdf(invoice_id=SECOND),
    pdf(date="03/02/32"),
    pdf(date="03/02/32    Unrelated date: 03/01/32"),
    text_pdf([f"Unrelated ref {FIRST}", "Payment Due On: 03/01/32"]),
])
def test_wrong_number_or_date_never_saves_a_pdf(tmp_path, data):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdfs[FIRST] = data
    target = tmp_path/"bill.pdf"
    assert not site.download_bill(page, doc.date_text, target, document_id=doc.document_id)
    assert not target.exists()


def test_accepts_the_start_of_the_listed_service_period():
    data = text_pdf([f"Invoice Number: {FIRST}", "Invoice Date: 02/15/32",
                     "03/01/32 - 03/31/32"])
    assert site._pdf_matches(data, site.Bill(FIRST, DATE))


def test_distinguishes_two_labeled_dates_on_the_same_line():
    data = text_pdf([f"Invoice Number: {FIRST}",
                     "Invoice Date: 02/15/32    Payment Due On: 03/01/32"])
    assert site._pdf_matches(data, site.Bill(FIRST, DATE))


@pytest.mark.parametrize("status, mime", [(403, "application/pdf"), (302, "text/html"),
                                         (200, "text/html")])
def test_a_pdf_refusal_reads_the_history_again(tmp_path, status, mime):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_status, page.pdf_mime = status, mime
    path = tmp_path/"bill.pdf"
    assert not site.download_bill(page, doc.date_text, path, document_id=doc.document_id)
    assert page.calls.count(site.DOCUMENTS_URL) == 2 and not path.exists()
    assert all(response.released for response in page.responses)


@pytest.mark.parametrize("history_status,error", [(401, site.SessionExpired), (500, site.ListStopped)])
def test_failed_list_recheck_stops_the_run(tmp_path, history_status, error):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_status = 403
    page.history_status = history_status
    with pytest.raises(error):
        site.download_bill(page, doc.date_text, tmp_path/"bill.pdf", document_id=doc.document_id)


def test_rate_limit_stops_at_the_first_pdf(tmp_path):
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdf_status = 429
    with pytest.raises(site.ListStopped, match="limiting"):
        site.download_bill(page, doc.date_text, tmp_path/"bill.pdf", document_id=doc.document_id)
    assert len(page.calls) == 2


def test_offline_preview_writes_summary_and_preserves_the_last_download(tmp_path, monkeypatch, capsys):
    import sonic_docs as app_module

    config = tmp_path/"config.json"
    config.write_text(json.dumps({"output_dir": str(tmp_path)}))
    monkeypatch.setattr(app_module.App, "_setup_logging", lambda self: None)
    app = app_module.App(app_module.build_parser().parse_args(["--config", str(config)]))
    for doc in site.collect_download_docs(Page()):
        app._record_rawdoc(doc, site.DOCUMENTS_URL)
    app.discovery.save()
    files = tmp_path/"new-this-run.txt"
    files.write_text("previous download\n")
    original = files.stat()

    def no_browser(_app):
        pytest.fail("A dry run opened the browser")

    monkeypatch.setattr(app_module.App, "browser", no_browser)
    assert app_module.main(["--config", str(config), "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "DRY RUN - would save:" in output and "PAPERPULL_RUN_RESULT " in output
    summary = (tmp_path/"run-summary.txt").read_text()
    fields = dict(line.split(":", 1) for line in summary.splitlines() if ":" in line)
    assert fields["Mode"].strip() == "dry-run" and fields["NEW files this run"].strip() == "0"
    assert files.read_text() == "previous download\n"
    assert (files.stat().st_ino, files.stat().st_mtime_ns) == (original.st_ino, original.st_mtime_ns)


def test_same_day_bills_get_distinct_filenames_and_resume_skips_both(tmp_path, monkeypatch):
    import sonic_docs as app_module

    config = tmp_path/"config.json"
    config.write_text(json.dumps({"output_dir": str(tmp_path), "min_pdf_bytes": 100}))
    monkeypatch.setattr(app_module.App, "_setup_logging", lambda self: None)
    app = app_module.App(app_module.build_parser().parse_args(["--config", str(config)]))
    page = Page()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "_delay", lambda: None)
    assert app.cmd_discover() == 2
    app.process(app._select())
    files = [Path(path) for path in app.stats["new_files"]]
    assert len(files) == len(set(files)) == 2
    assert {path.read_bytes() for path in files} == set(page.pdfs.values())
    calls_before_resume = len(page.calls)
    app.cmd_resume()
    assert len(page.calls) == calls_before_resume + 1
    assert page.calls[-1] == site.DOCUMENTS_URL
    assert app.stats["new_files"] == [str(path) for path in files]


def _app(tmp_path, monkeypatch, page):
    import sonic_docs as app_module

    config = tmp_path/"config.json"
    config.write_text(json.dumps({"output_dir": str(tmp_path), "min_pdf_bytes": 100}))
    monkeypatch.setattr(app_module.App, "_setup_logging", lambda self: None)
    app = app_module.App(app_module.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "_delay", lambda: None)
    monkeypatch.setattr(app, "write_failure", lambda step, reason, **_: app.stats.setdefault(
        "failures_said", []).append((step, reason)))
    return app


@pytest.mark.parametrize("change, note, wrong", [
    (lambda page: page.pdfs.update({FIRST: pdf(invoice_id=SECOND)}),
     "The PDF did not show this bill's invoice number and date", 1),
    (lambda page: setattr(page, "pdf_status", 403),
     "Sonic refused this bill's PDF", 0),
    (lambda page: page.pdfs.update({FIRST: b"%PDF-1.4 not a readable pdf"}),
     "The PDF's text could not be read", 0),
])
def test_a_bill_that_saved_nothing_says_why(tmp_path, monkeypatch, capsys, change, note, wrong):
    page = Page()
    page.html = history(row()).encode()
    app = _app(tmp_path, monkeypatch, page)
    assert app.cmd_discover() == 1
    change(page)
    app.process(app._select())
    record = next(iter(app.progress.data.values()))
    assert record["state"] == "Failed" and record["notes"] == note
    assert app.stats["failed"] == 1 and app.stats.get("wrong_document", 0) == wrong
    assert note in capsys.readouterr().out
    assert not app.stats["new_files"]


def test_login_words_print_in_a_plain_windows_console(tmp_path, monkeypatch, capsys):
    page = Page()
    page.history_status = 500
    app = _app(tmp_path, monkeypatch, page)
    monkeypatch.setattr(app, "page", lambda: page)
    app.cmd_login()
    said = capsys.readouterr().out
    assert "Could not read the Sonic bill history" in said
    said.encode("cp1252")


class _Fields:
    """A page's password fields, drawn or not, as a locator counts them."""

    def __init__(self, url, drawn, hidden):
        self.url, self.drawn, self.hidden = url, drawn, hidden

    def locator(self, selector):
        count = self.drawn + (0 if ":visible" in selector else self.hidden)
        return SimpleNamespace(count=lambda: count)


def test_a_password_field_reads_as_signed_out_whether_drawn_or_not():
    url = site.URLS["documents"]
    assert site.looks_signed_out(_Fields(url, drawn=0, hidden=1))
    assert site.looks_signed_out(_Fields(url, drawn=1, hidden=0))
    assert not site.looks_signed_out(_Fields(url, drawn=0, hidden=0))
    assert not site.looks_signed_out(_Fields("https://example.test/login", drawn=1, hidden=1))


@pytest.mark.parametrize("more", [
    '<ul class="pagination"><li><a href="?page=2">Next</a></li></ul>',
    '<nav><ul class="pager"><li><a href="#">2</a></li></ul></nav>',
    '<a rel="next" href="#">Next</a>',
    f'<a href="{site.HISTORY_PATH}?page=2">Older bills</a>',
    f'<a href="{site.DOCUMENTS_URL}?start=12">Older bills</a>',
])
def test_a_history_with_another_page_is_never_taken_as_whole(more):
    with pytest.raises(site.ListStopped, match="more than one page"):
        site._parse_history(history(row()) + more)


def test_a_link_back_to_the_history_page_itself_is_not_another_page():
    html = f'<a href="{site.HISTORY_PATH}">View Bill History</a>' + history(row())
    assert len(site._parse_history(html)) == 1


def test_a_pdf_with_no_text_is_unreadable_not_a_wrong_document(tmp_path, monkeypatch):
    from pypdf import PdfWriter
    import io

    blank = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(blank)
    page = Page()
    doc = site.collect_download_docs(page)[0]
    page.pdfs[FIRST] = blank.getvalue()
    assert not site.download_bill(page, doc.date_text, tmp_path/"bill.pdf", document_id=doc.document_id)
    assert site.last_refusal() == "unreadable"


@pytest.mark.parametrize("more", [
    '<a href="../history/?page=2">Older bills</a>',
    '<a href="history/index.php?page=2">Older bills</a>',
    f'<a href="{site.HISTORY_PATH}all/">All bills</a>',
    '<a href="https://MEMBERS.sonic.net/account/billing/history/?page=2">Older bills</a>',
    '<li class="page-item"><a class="page-link" href="#">2</a></li>',
    '<a href="?year=2031">2031</a>',
])
def test_more_shapes_of_another_page_stop_the_list(more):
    with pytest.raises(site.ListStopped, match="more than one page"):
        site._parse_history(history(row()) + more)


@pytest.mark.parametrize("link", [
    '<a href="?logout=1">Sign out</a>',
    '<a href="?lang=es">Espanol</a>',
    f'<a href="{site.HISTORY_PATH}?print=1">Print</a>',
    '<a href="/account/billing/?tab=1">Billing</a>',
    '<a href="#top">Top</a>',
])
def test_a_link_that_is_not_another_page_leaves_the_list_whole(link):
    assert len(site._parse_history(link + history(row()))) == 1
