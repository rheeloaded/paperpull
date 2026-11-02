"""Statements Robinhood serves as HTML are rendered to PDF through the
core's inert print path. Anything else that is not a PDF is still refused,
and nothing half-made is left behind."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import robinhood_site as site  # noqa: E402
from paperpull_core import receipt_pdf  # noqa: E402

HTML = b"<!DOCTYPE html><html><head><title>Statement</title></head><body>January 2026</body></html>"
TITLE = "January 2026 \u2013 Individual Investing Account Statement"
LABEL = "Download HTML"


def fake_render(ok=True, partial=False):
    calls = []

    def render(page, html, out):
        calls.append(html)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"%PDF-1.4 rendered" if ok else b"not a pdf")
        if partial:
            raise RuntimeError("renderer died after writing")
    return render, calls


def yes(path, title):
    return True


def test_a_pdf_is_kept_as_it_is(tmp_path):
    out = tmp_path / "s.pdf"
    assert site.keep_fetched(None, b"%PDF-1.4 real", TITLE, out, label="Download PDF")
    assert out.read_bytes() == b"%PDF-1.4 real"


def test_an_html_statement_behind_a_download_html_control_is_rendered(tmp_path):
    render, calls = fake_render()
    out = tmp_path / "s.pdf"
    assert site.keep_fetched(None, HTML, TITLE, out, label=LABEL, render=render, check=yes)
    assert out.read_bytes().startswith(b"%PDF-")
    assert len(calls) == 1 and "January 2026" in calls[0]
    assert not list(tmp_path.glob("*.rendering"))


def test_the_document_title_alone_does_not_open_the_html_path(tmp_path):
    render, calls = fake_render()
    out = tmp_path / "s.pdf"
    assert not site.keep_fetched(None, HTML, TITLE + " Download HTML", out, label="Download PDF", render=render, check=yes)
    assert calls == [] and not out.exists()


def test_a_render_that_is_not_a_pdf_leaves_no_file(tmp_path):
    render, _ = fake_render(ok=False)
    out = tmp_path / "s.pdf"
    assert not site.keep_fetched(None, HTML, TITLE, out, label=LABEL, render=render, check=yes)
    assert not out.exists() and not list(tmp_path.iterdir())


def test_a_renderer_that_writes_then_dies_leaves_nothing(tmp_path):
    render, _ = fake_render(partial=True)
    out = tmp_path / "s.pdf"
    assert not site.keep_fetched(None, HTML, TITLE, out, label=LABEL, render=render, check=yes)
    assert not list(tmp_path.iterdir())


def test_a_rendering_that_does_not_name_the_month_is_refused(tmp_path):
    render, _ = fake_render()
    out = tmp_path / "s.pdf"
    assert not site.keep_fetched(None, HTML, TITLE, out, label=LABEL, render=render, check=lambda p, t: False)
    assert not list(tmp_path.iterdir())


def test_empty_and_other_bodies_are_refused(tmp_path):
    render, calls = fake_render()
    out = tmp_path / "s.pdf"
    for body in (b"", b"{\"error\": 1}", b"<svg/>"):
        assert not site.keep_fetched(None, body, TITLE, out, label=LABEL, render=render, check=yes)
    assert calls == [] and not out.exists()


def test_the_month_check_reads_the_title():
    assert site._MONTH_YEAR_IN_TITLE_RE.search(TITLE).groups() == ("January", "2026")
    assert site.rendered_names_statement(Path("/nonexistent.pdf"), "Form 1099")  # no month: not checked


def test_inert_html_strips_what_could_run():
    html = ("<html><head><base href='https://evil.test/'><script>x()</script>"
            "<link rel=stylesheet href=//evil.test/a.css><meta http-equiv=refresh content='0;url=https://evil.test'>"
            "</head><body onload='x()'><iframe src='https://evil.test'></iframe>"
            "<form action='https://evil.test'><input></form><a href='javascript:alert(1)'>a</a>"
            "<img src='/img.png' onerror='x()'><p style='color:red'>January 2026</p></body></html>")
    out = site.receipt_pdf.inert_html(html, "https://robinhood.com/") if hasattr(site, "receipt_pdf") else receipt_pdf.inert_html(html, "https://robinhood.com/")
    low = out.lower()
    for bad in ("<script", "<iframe", "<form", "<link", "<meta", "evil.test", "onload", "onerror", "javascript:"):
        assert bad not in low, bad
    assert '<base href="https://robinhood.com/">' in out and "January 2026" in out and "<img" in out and "style=" in out


def test_abbreviated_month_titles_are_checked_too():
    m = site._MONTH_YEAR_IN_TITLE_RE.search("Jan 2026 - Individual Statement")
    assert m and m.group(2) == "2026"


def test_a_download_html_control_is_discovered_like_a_pdf_one():
    """The collect script lists a statement behind a Download HTML link or
    button, with the control words stripped from the title."""
    from playwright.sync_api import sync_playwright
    page_html = (
        "<html><body>"
        "<a download href='#'>January 2026 \u2013 Individual Investing Account Statement Download HTML</a>"
        "<div><h3>Form 1099 2025</h3><button>Download HTML</button></div>"
        "<a download href='#'>Something Download CSV</a>"
        "</body></html>")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(page_html)
            got = page.evaluate(site._COLLECT_JS, False)
        finally:
            browser.close()
    titles = sorted(str(d.get("title") or d.get("own") or "") for d in got)
    assert "January 2026 \u2013 Individual Investing Account Statement" in titles, titles
    assert "Form 1099 2025" in titles, titles
    assert not any("Download" in x or "CSV" in x for x in titles), titles


def test_the_inert_render_fetches_nothing_and_runs_nothing(tmp_path):
    """Styles and images naming an outside address are not fetched, and no
    script runs, in the fresh JavaScript-off context the statement is drawn in."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from playwright.sync_api import sync_playwright
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x")

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    html = (f"<html><head><style>@import url(http://127.0.0.1:{port}/a.css); body{{background:url(http://127.0.0.1:{port}/b.png)}}</style>"
            f"<script>fetch('http://127.0.0.1:{port}/js')</script></head>"
            f"<body onload=\"fetch('http://127.0.0.1:{port}/onload')\"><img src='http://127.0.0.1:{port}/i.png'>"
            "<p>January 2026 statement text</p></body></html>")
    out = tmp_path / "r.pdf"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content("<html><body>work page</body></html>")
            receipt_pdf.print_html_inert_to_pdf(page, html, out, base="https://robinhood.com/")
            assert len(browser.contexts) == 1, "the render context was closed"
        finally:
            browser.close()
    srv.shutdown()
    assert out.read_bytes().startswith(b"%PDF-")
    assert hits == [], hits
    assert "January" in receipt_pdf.pdf_text(out) and "2026" in receipt_pdf.pdf_text(out)


def test_records_titled_with_the_old_control_words_move_under_the_cleaned_key():
    """A statement listed before the title was cleaned sits under one key,
    never beside a second record for the same statement."""
    import robinhood_docs as docs
    legacy = {"title": "January 2026 \u2013 Individual Investing Account Statement Download HTML",
              "category": "Statement", "summary": "Statement", "date": "2026-01-31",
              "account": "Individual", "state": "NEEDS_MANUAL_REVIEW", "document_id": ""}
    old_key = docs.Document.from_dict(legacy).key
    records = {old_key: dict(legacy)}
    assert docs.migrate_html_titles(records) == 1
    assert len(records) == 1
    (key, rec), = records.items()
    assert "Download" not in rec["title"] and "Download" not in key
    assert docs.Document.from_dict(rec).key == key
    # Run again: nothing to do, nothing changes.
    assert docs.migrate_html_titles(records) == 0
    # Already re-listed under the clean key and saved: the saved one stays.
    clean = dict(rec, state="COMPLETED", pdf_path="/x/y.pdf")
    both = {old_key: dict(legacy), key: clean}
    assert docs.migrate_html_titles(both) == 1
    assert list(both) == [key] and both[key]["pdf_path"] == "/x/y.pdf"


def test_both_load_time_moves_run_on_one_store():
    """A store with a cut key AND a legacy HTML title gets both moves, each
    on its own, through the same loop App.__init__ runs."""
    import robinhood_docs as docs

    class Store:
        def __init__(self, data):
            self.data = data
            self.saved = 0

        def save(self, backup=False):
            self.saved += 1
    legacy = {"title": "January 2026 \u2013 Individual Investing Account Statement Download HTML",
              "category": "Statement", "summary": "Statement", "date": "2026-01-31",
              "account": "Individual", "state": "NEEDS_MANUAL_REVIEW", "document_id": ""}
    long_acct = {"title": "February 2026 \u2013 Statement", "category": "Statement", "summary": "Statement",
                 "date": "2026-02-28", "account": "Invented Cash Rewards World Elite Mastercard (...1234)",
                 "state": "COMPLETED", "document_id": ""}
    full_key = docs.Document.from_dict(long_acct).key
    assert full_key.endswith("-1234")
    cut_key = full_key[:-len("-1234")]
    store = Store({docs.Document.from_dict(legacy).key: dict(legacy), cut_key: dict(long_acct)})

    def load_like_the_app(store):
        moved = docs.migrate_legacy_keys(store.data)
        if docs.migrate_html_titles(store.data):
            moved = True
        if moved:
            store.save(backup=True)
    load_like_the_app(store)
    assert store.saved == 1
    assert not any("Download" in k for k in store.data), list(store.data)
    assert cut_key not in store.data and full_key in store.data
    load_like_the_app(store)
    assert store.saved == 1, "nothing left to move"


def test_a_record_keyed_by_its_document_id_keeps_that_key():
    """--minimal histories drop document_id but keep the id: key. The title
    is cleaned and the key stands, so fresh discovery finds it done."""
    import robinhood_docs as docs
    rec = {"title": "March 2026 \u2013 Individual Investing Account Statement Download HTML",
           "category": "Statement", "summary": "Statement", "date": "2026-03-31",
           "account": "Individual", "state": "COMPLETED", "pdf_path": "/x/m.pdf"}
    records = {"id:0b1e-uuid": dict(rec)}
    assert docs.migrate_html_titles(records) == 1
    assert list(records) == ["id:0b1e-uuid"]
    assert "Download" not in records["id:0b1e-uuid"]["title"]
    assert records["id:0b1e-uuid"]["state"] == "COMPLETED"


def test_the_month_check_wants_a_printed_period_ending_in_the_month():
    assert site.names_month("Statement period 01/01/2026 to 01/31/2026", "January", "2026")
    assert site.names_month("Statement 01/01/2026 - 01/31/2026", "Jan", "2026")
    assert site.names_month("Period 2026-02-01 through 2026-02-28", "February", "2026")
    assert site.names_month("Statement Period:\nJanuary 1, 2026 \u2013 January 31, 2026", "January", "2026")
    assert site.names_month("Period Jan. 1st, 2026 to Jan. 31st, 2026", "January", "2026")
    assert site.names_month("For the period ending January 31, 2026", "January", "2026")
    assert site.names_month("Period ended 09/30/2026", "September", "2026")
    assert site.names_month("Statement period Sept. 1, 2026 - Sept. 30, 2026", "September", "2026")
    assert not site.names_month("", "January", "2026")
    assert not site.names_month("01/05/2026 - 01/31/2026", "January", "2026"), "bare, not the whole month"
    assert not site.names_month("01/01/2026 - 01/30/2026", "January", "2026"), "bare, not the whole month"
    assert not site.names_month("Period 12/01/2024 to 12/31/2024", "December", "2025"), "wrong year"
    assert not site.names_month("Period 02/01/2026 to 02/28/2026", "January", "2026"), "wrong month"
    assert not site.names_month("Period 01/01/2026 to 02/28/2026", "January", "2026"), "the end is what counts"
    assert not site.names_month("Decrease 12/31/2025", "December", "2025"), "a date alone is no period"


# Page 1 of real HTML months as rendered, the address and account made up.
LIVE_JANUARY = ("1 Example Plaza, Suite 100, Example City, ZZ 00000 help@robinhood.com "
                "01/01/2026 to 01/31/2026 # # Individual Account #:00000 1 Invented Street")
LIVE_FEBRUARY = ("1 Example Plaza, Suite 100, Example City, ZZ 00000 help@robinhood.com "
                 "02/01/2026 to 02/28/2026 # # Individual Account #:00000 1 Invented Street")


def test_a_bare_whole_month_range_is_the_period_of_an_html_month():
    """An HTML month prints its period bare under the address, no label."""
    assert site.names_month(LIVE_JANUARY, "January", "2026")
    assert site.names_month(LIVE_FEBRUARY, "February", "2026")
    assert not site.names_month(LIVE_FEBRUARY, "January", "2026")
    assert not site.names_month(LIVE_JANUARY, "February", "2026")
    assert site.names_month("01/01/2026 - 01/31/2026", "Jan", "2026")


def test_bare_ranges_that_disagree_name_no_month():
    """Two whole-month ranges of different months on one page, and neither
    is labeled: nothing says which is the statement's."""
    text = "01/01/2026 to 01/31/2026\n02/01/2026 to 02/28/2026"
    assert not site.names_month(text, "January", "2026")
    assert not site.names_month(text, "February", "2026")
    # A labeled range of another kind is not counted against it.
    text = LIVE_FEBRUARY + "\nTrade dates 01/01/2026 to 01/31/2026"
    assert site.names_month(text, "February", "2026")
    assert not site.names_month(text, "January", "2026")


@pytest.mark.parametrize("text", [
    "Trade date 01/30/2026",
    "Opening balance as of 12/31/2025",
    "Generated January 3, 2026",
    "January 2026 statement",
    "as of 2026-01-31",
    "Period 12/01/2025 to 12/31/2025  Trade date 01/02/2026",
    "Trade dates 01/01/2026 to 01/31/2026",
    "Transactions 01/01/2026 to 01/31/2026",
    "Trades 01/01/2026 - 01/31/2026",
    "Dated 01/01/2026 to 01/31/2026",
    "Closing 01/01/2026 to 01/31/2026",
    "Statement of activity, trade dates 01/01/2026 to 01/31/2026",
    "Generated 01/01/2026 to 01/31/2026",
    "Statement balance as of 01/01/2026 - 01/31/2026",
    "Ended 01/31/2026",
])
def test_a_date_that_is_not_the_period_end_does_not_pass_for_january(text):
    """The maintainer's counterexamples. A February page printing a trade
    date in January, an opening balance of the month before, or the day the
    page was made says nothing of the statement's own month."""
    assert not site.names_month(text, "January", "2026")


def test_only_the_first_page_is_read(tmp_path, monkeypatch):
    """A period printed on a later page, a list of trades for instance,
    is not the statement's own."""
    pages = ["Statement for an invented account", "Period 01/01/2026 to 01/31/2026"]
    monkeypatch.setattr(site, "_first_page_text", lambda path: pages[0])
    assert not site.rendered_names_statement(tmp_path / "x.pdf", TITLE)
    monkeypatch.setattr(site, "_first_page_text", lambda path: pages[1])
    assert site.rendered_names_statement(tmp_path / "x.pdf", TITLE)


def test_the_first_page_text_reads_one_page_of_a_real_render(tmp_path):
    from playwright.sync_api import sync_playwright
    html = ("<html><body><p>Period 01/01/2026 to 01/31/2026</p>"
            "<p style='page-break-before:always'>Period 02/01/2026 to 02/28/2026</p></body></html>")
    out = tmp_path / "r.pdf"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            receipt_pdf.print_html_inert_to_pdf(page, html, out, base="https://robinhood.com/")
        finally:
            browser.close()
    text = site._first_page_text(out)
    assert "01/31/2026" in text and "02/28/2026" not in text


def _done_and_reviewed():
    import robinhood_docs as docs
    legacy = {"title": "January 2026 \u2013 Individual Investing Account Statement Download HTML",
              "category": "Statement", "summary": "Statement", "date": "2026-01-31",
              "account": "Individual", "document_id": ""}
    old_key = docs.Document.from_dict(legacy).key
    clean = dict(legacy, title="January 2026 \u2013 Individual Investing Account Statement")
    new_key = docs.Document.from_dict(clean).key
    return docs, legacy, old_key, clean, new_key


def test_the_done_record_stays_when_both_titles_are_held():
    """Done, not a path, decides. The record under the cleaned key is done
    with its file deleted once imported, and the old one is in review with a
    path to the copy set aside there. The done one stays."""
    docs, legacy, old_key, clean, new_key = _done_and_reviewed()
    done = dict(clean, state="COMPLETED", downloaded_ok=True, pdf_path="")
    review = dict(legacy, state="NEEDS_MANUAL_REVIEW", pdf_path="/review/copy.pdf")
    both = {old_key: review, new_key: done}
    assert docs.migrate_html_titles(both) == 1
    assert list(both) == [new_key] and both[new_key]["state"] == "COMPLETED"
    # And the other way round: the old record is the done one.
    done = dict(legacy, state="COMPLETED", downloaded_ok=True, pdf_path="")
    review = dict(clean, state="NEEDS_MANUAL_REVIEW", pdf_path="/review/copy.pdf")
    both = {old_key: done, new_key: review}
    assert docs.migrate_html_titles(both) == 1
    assert list(both) == [new_key] and both[new_key]["state"] == "COMPLETED"
    assert "Download" not in both[new_key]["title"]


def test_when_neither_is_done_the_one_already_under_the_cleaned_key_stays():
    docs, legacy, old_key, clean, new_key = _done_and_reviewed()
    listed = dict(clean, state="DISCOVERED")
    both = {old_key: dict(legacy, state="NEEDS_MANUAL_REVIEW"), new_key: listed}
    assert docs.migrate_html_titles(both) == 1
    assert both == {new_key: listed}


# Each of these once left, or could leave, something live after the strip.
# Removing a tag joined the text around it into a new one, or a tag the
# pattern did not see opened a connection the route abort did not stop.
ADVERSARIAL = [
    "<li<link>nk rel=prefetch href=//evil.test/a>",
    "<scr<script>x</script>ipt src=//evil.test/a.js></script>",
    "<me<meta>ta http-equiv=refresh content='0;url=//evil.test/'>",
    "<if<iframe></iframe>rame src=//evil.test/></iframe>",
    "<ob<object></object>ject data=//evil.test/a></object>",
    "<em<embed>bed src=//evil.test/a>",
    "<ba<base>se href=//evil.test/>",
    "<fo<form></form>rm action=//evil.test/><button>x</button></form>",
    "<<script>script>x()<</script>/script>",
    "<l<li<link>nk>nk rel=prefetch href=//evil.test/a>",
    "<meta http-equiv=refresh content='0;url=//evil.test/'>",
    "<META HTTP-EQUIV='Refresh' CONTENT='0; URL=//evil.test/'>",
    "<iframe src=//evil.test/></iframe>",
    "<iframe srcdoc='<img src=//evil.test/a>'>",
    "<object data=//evil.test/a type=text/html></object>",
    "<link rel=prefetch href=//evil.test/a>",
    "<link rel=preload as=image href=//evil.test/a>",
    "<frameset><frame src=//evil.test/></frameset>",
    "<applet code=x codebase=//evil.test/></applet>",
    "<script\nsrc=//evil.test/a.js></script>",
    "<script src=//evil.test/a.js",
    "<svg><script>x()</script></svg>",
    "<img src=x/onerror=fetch('//evil.test/')>",
    "<img/onerror=fetch('//evil.test/') src=x>",
    "<a href=' javascript:fetch(1)'>a</a>",
    "<p o<script></script>nclick=x()>t</p>",
]
LIVE = ("<script", "<iframe", "<frame", "<object", "<embed", "<applet", "<form", "<link",
        "<meta", "onerror", "onclick", "javascript:")


@pytest.mark.parametrize("html", ADVERSARIAL)
def test_nothing_live_is_left_or_the_render_is_refused(html):
    try:
        out = receipt_pdf.inert_html("<html><head></head><body>" + html + "<p>January 2026</p></body></html>",
                                     "https://robinhood.com/")
    except receipt_pdf.UnsafeHtml:
        return
    low = out.lower()
    assert out.lower().count("<base") == 1, out
    for bad in LIVE:
        assert bad not in low, (bad, out)


@pytest.mark.parametrize("unit", ["<script>", "<script ", "<a ", "<a \"", "<li<link>nk ", "<p onclick=x "])
def test_a_page_of_broken_tags_is_read_in_one_pass(unit):
    """Each start is never scanned to the end of the page, so a large page
    of unclosed or broken tags takes no longer than a page of text."""
    import time
    html = "<html><head></head><body>" + unit * 50000 + "</body></html>"
    started = time.perf_counter()
    try:
        receipt_pdf.inert_html(html, "https://robinhood.com/")
    except receipt_pdf.UnsafeHtml:
        pass
    assert time.perf_counter() - started < 3, "the strip is no longer linear"


def test_an_unclosed_script_tag_goes_with_the_rest_of_the_page():
    """A tag with no ">" runs to the end of the page, as a browser reads it,
    and is taken out with it."""
    out = receipt_pdf.inert_html("<html><body><p>x</p><script src=//evil.test/a.js", "https://robinhood.com/")
    assert "<p>x</p>" in out and "script" not in out.lower() and "evil" not in out


def test_an_unclosed_script_element_never_shows_what_it_held():
    """A script opened and never closed holds the rest of the page as its
    code. Shown as text, a period written there would pass for the
    statement's own."""
    out = receipt_pdf.inert_html("<html><body><p>Kept</p><script><p>Period 01/01/2026 to 01/31/2026"
                                 "<img src=//evil.test/a>", "")
    assert "Kept" in out and "Period" not in out and "evil" not in out


def test_an_active_tag_the_strip_cannot_settle_refuses_the_render(monkeypatch):
    """When a pass still changes the page after the last one allowed, or an
    active tag is left, nothing is drawn."""
    monkeypatch.setattr(receipt_pdf, "_MAX_STRIPS", 1)
    with pytest.raises(receipt_pdf.UnsafeHtml):
        receipt_pdf.inert_html("<l<link>ink rel=prefetch href=//evil.test/a>", "")


def test_a_handler_written_inside_a_quoted_value_is_left_alone():
    out = receipt_pdf.inert_html('<p title="x onerror=y" data-a=\'b onclick=c\'>t</p>', "")
    assert 'title="x onerror=y"' in out and "data-a='b onclick=c'" in out


def test_a_handler_after_a_slash_or_a_quote_is_taken_out():
    out = receipt_pdf.inert_html("<img src=\"a.png\"/onerror=x() alt='a'onload=y()>", "")
    assert "onerror" not in out and "onload" not in out and 'src="a.png"' in out


@pytest.mark.parametrize("html", [
    "<me<meta>ta http-equiv=refresh content='0;url=http://127.0.0.1:{port}/refresh'>",
    "<if<iframe></iframe>rame src=http://127.0.0.1:{port}/iframe></iframe>",
    "<ob<object></object>ject data=http://127.0.0.1:{port}/object></object>",
    "<li<link>nk rel=prefetch href=http://127.0.0.1:{port}/prefetch>",
    "<meta http-equiv=refresh content='0;url=http://127.0.0.1:{port}/refresh'>",
    "<iframe src=http://127.0.0.1:{port}/iframe></iframe>",
    "<object data=http://127.0.0.1:{port}/object></object>",
    "<link rel=prefetch href=http://127.0.0.1:{port}/prefetch>",
])
def test_a_split_or_plain_active_tag_reaches_nothing_in_a_real_render(tmp_path, html):
    """In a real browser, with a local server counting every request, none
    of these is fetched, whether the strip took it out or refused the page."""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from playwright.sync_api import sync_playwright
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x")

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = tmp_path / "r.pdf"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                try:
                    receipt_pdf.print_html_inert_to_pdf(
                        page, "<html><head></head><body>" + html.format(port=port)
                        + "<p>January 2026</p></body></html>", out, base="https://robinhood.com/")
                except receipt_pdf.UnsafeHtml:
                    assert len(browser.contexts) == 1, "a refused page opens no context"
                time.sleep(0.5)
            finally:
                browser.close()
    finally:
        srv.shutdown()
    assert hits == [], hits


def test_a_hostile_page_is_stripped_and_read_in_linear_time():
    """A run of whitespace after "<" or "href=", a page of unclosed head
    tags, and a first page with no newline each took between 12 and 82
    seconds before the review's fix, and well under one second after. The
    bound is generous so a slow machine does not trip it."""
    import time
    for html in ("<" + " " * 40000 + "x",
                 "<" + " " * 20000 + "/" + " " * 20000 + "x",
                 "href=" + " " * 40000 + "x",
                 "<head" * 200000):
        t0 = time.perf_counter()
        try:
            receipt_pdf.inert_html(html, "https://robinhood.com/")
        except Exception:
            pass
        assert time.perf_counter() - t0 < 5, html[:12]
    page = "Statement " + "01/01/2026 to 01/31/2026 x " * 12000
    t0 = time.perf_counter()
    site._whole_months(page)
    assert time.perf_counter() - t0 < 5
    assert site._whole_months("Account\n01/01/2026 - 01/31/2026\n") == {(1, "2026")}


# A tag is read as a browser reads it. A comment runs to its own "-->" and a
# quote opens a value only after "=", so a stray quote cannot hide a later
# tag inside what looks like a value. A URL is read with its character
# references decoded, as the browser reads it.
STILL_LIVE = [
    "<!-- don't --><img src=x onerror=alert(1)><p title='x'>t</p>",
    "<!-- it's > --><img src=x onerror=alert(1)><p title='x'>t</p>",
    "<p a'b><img src=x onerror=alert(1)><p c='d'>t</p>",
    "<p a'b onclick=alert(1) c'd>t</p>",
    "<p =\" onclick=alert(1)\">t</p>",
    "<p a= =\"><img src=x onerror=alert(1)>\">t</p>",
    "<p a=\u00a0\"><img src=x onerror=alert(1)>\">t</p>",
    "<a href='&#106;avascript:alert(1)'>a</a>",
    "<a href='&#x6A;avascript:alert(1)'>a</a>",
    "<a href='&#0000106avascript:alert(1)'>a</a>",
    "<a href='java&Tab;script:alert(1)'>a</a>",
    "<a href='java&NewLine;script:alert(1)'>a</a>",
    "<a href='javascript&colon;alert(1)'>a</a>",
    "<a href=\"java\tscript:alert(1)\">a</a>",
    "<a href='\x01JaVaScRiPt:alert(1)'>a</a>",
    "<a href=&#106;avascript:alert(1)>a</a>",
    "<form><button formaction='&#106;avascript:alert(1)'>x</button></form>",
]
# A browser reads the body of these as text up to the element's own end
# tag, in any case and with a space or "/" before its ">". A "<!--" or a
# quote there opens nothing, so the tag after the end tag is live.
RAW_TEXT = ("style", "title", "textarea", "xmp", "noembed", "noframes")
RAW_TEXT_CASES = [
    case
    for name in RAW_TEXT
    for case in (f"<{name}><!--</{name}><img src=x onerror=alert(1)>-->",
                 f"<{name.upper()}><!--</{name.upper()}><img src=x onerror=alert(1)>-->",
                 f"<{name}><!--</{name} ><img src=x onerror=alert(1)>-->",
                 f"<{name}><!--</{name}\n/><img src=x onerror=alert(1)>-->",
                 f"<{name}><p a=\"</{name}><img src=x onerror=alert(1)>\">t</p>")
]
# A long s matches "s" in a case-blind Python pattern, but a browser ends
# the element on its own name in ASCII letters only.
RAW_TEXT_CASES.append("<style></\u017ftyle><!--</style><img src=x onerror=alert(1)>-->")
STILL_LIVE += RAW_TEXT_CASES


@pytest.mark.parametrize("html", STILL_LIVE)
def test_a_handler_or_script_url_a_misread_tag_hid_is_taken_out(html):
    import html as _h
    try:
        out = receipt_pdf.inert_html("<html><head></head><body>" + html + "</body></html>", "")
    except receipt_pdf.UnsafeHtml:
        return
    low = _h.unescape(out).lower().replace("\t", "").replace("\n", "")
    for bad in ("onerror", "onclick", "javascript:"):
        assert bad not in low, (bad, out)


def _live_in_a_browser(pages):
    """For each page, the elements bundled Chromium finds holding an on*
    attribute or a javascript: URL once the strip has run, read with
    JavaScript off and every request aborted, as the statement is drawn."""
    from playwright.sync_api import sync_playwright
    found = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(java_script_enabled=False)
            ctx.route("**/*", lambda route: route.abort())
            page = ctx.new_page()
            for html in pages:
                page.set_content(receipt_pdf.inert_html("<html><head></head><body>" + html + "</body></html>", ""))
                found[html] = page.evaluate("""() => {
                    const live = [];
                    for (const el of document.querySelectorAll('*')) {
                        for (const a of el.attributes) {
                            const v = a.value.replace(/[\\t\\n\\r]/g, '').replace(/^[\\x00-\\x20]+/, '');
                            if (/^on/i.test(a.name) || /^javascript:/i.test(v)) live.push(el.tagName + ' ' + a.name);
                        }
                    }
                    return live;
                }""")
        finally:
            browser.close()
    return {html: live for html, live in found.items() if live}


def test_no_handler_follows_a_raw_text_element_in_a_real_parse():
    """Chromium's own reading of each page after the strip leaves nothing
    live behind a style, title, textarea, xmp, noembed or noframes element."""
    assert _live_in_a_browser(RAW_TEXT_CASES) == {}


def test_the_same_names_in_svg_or_mathml_hold_nothing_live_either():
    """Inside svg or math these names hold markup, not text, and an img
    there breaks out of the svg as a live tag. The body of each is written
    as text, so it is inert whichever way the browser reads it."""
    pages = ["<svg><style><img src=x onerror=alert(1)></style></svg>",
             "<svg><title><img src=x onerror=alert(1)></title></svg>",
             "<math><style><img src=x onerror=alert(1)></style></math>",
             "<svg><style/><img src=x onerror=alert(1)></svg>",
             "<svg><style><a title=\"</style><p x=\"><img src=x onerror=alert(1)>\"></style></svg>",
             "<svg><style><!--</style><p a=\"--><img src=x onerror=alert(1)>\"></svg>"]
    assert _live_in_a_browser(pages) == {}


def test_a_raw_text_body_with_no_tag_in_it_is_left_as_it_was():
    """Rules a style holds inside a comment that closes there, as older
    pages write them, are kept as they are."""
    page = ("<title>Statement &amp; summary</title><style>/* a > b */ td>p{color:#333} "
            "a[href^='https']{color:blue} p:before{content:\"a < b\"}</style>"
            "<style type=\"text/css\"><!--\nbody{color:#000}\n--></style>"
            "<textarea>1 < 2</textarea><p onclick=x>t</p>")
    out = receipt_pdf.inert_html(page, "")
    assert page.replace("<p onclick=x>", "<p >") in out


def test_a_comment_and_the_values_around_it_are_left_as_they_were():
    page = "<!-- it's a > note --><p title='x onerror=y' data-a=\"don't\">t</p><a href='https://robinhood.com/'>a</a>"
    out = receipt_pdf.inert_html(page, "")
    assert page in out


def test_a_hostile_comment_or_attribute_is_read_in_linear_time():
    """Long runs inside a comment, of unclosed comments, of "=" and of
    character references each take well under a second."""
    import time
    for html in ("<!--" + "-" * 200000,
                 "<!-- " * 50000,
                 "<!-- '" * 50000,
                 "<p " + "=" * 200000,
                 "<p a" + "= " * 100000,
                 "<p " + "a'b " * 50000,
                 "<a href='" + "&#0" * 100000 + "'>",
                 "<a href=" + "&#106;" * 50000 + ">",
                 "<a " + "href=x/" * 50000 + ">"):
        t0 = time.perf_counter()
        try:
            receipt_pdf.inert_html(html, "https://robinhood.com/")
        except receipt_pdf.UnsafeHtml:
            pass
        assert time.perf_counter() - t0 < 3, html[:12]


@pytest.mark.parametrize("text", [
    "Statement period 02/01/2026 to 02/28/2026\nPrevious statement period 01/01/2026 to 01/31/2026",
    "Previous statement period 01/01/2026 to 01/31/2026\nStatement period 02/01/2026 to 02/28/2026",
    "Period ending February 28, 2026. Last period ended January 31, 2026",
    "Statement period 01/01/2026 to 01/31/2026\n02/01/2026 to 02/28/2026",
    LIVE_FEBRUARY + "\nPrevious statement period 01/01/2026 to 01/31/2026",
])
def test_a_page_that_prints_another_months_period_names_no_month(text):
    """A February first page that also prints January's period is not
    January's, nor February's, since nothing says which is its own."""
    assert not site.names_month(text, "January", "2026")
    assert not site.names_month(text, "February", "2026")


def test_every_period_of_the_title_month_still_passes():
    text = "Statement period 01/01/2026 to 01/31/2026\n01/01/2026 to 01/31/2026\nPeriod ending January 31, 2026"
    assert site.names_month(text, "January", "2026")
