"""One date per statement, the one the vendor's list shows.

A pilot on 0.34.1 asked the vendor for a statement dated 2026-09-21. The
vendor's own list ran by month ends, 08/31/26 back to 09/30/25, so no
control on the page carried that date and nothing was saved. The date
came from the text around a control with no date of its own, where the
first date found is whatever the page prints near it, and a record made
that way by an earlier discovery sorted newest and was tried first on
every pilot after it (#35).

The same trace showed no Statement History control and yet twelve dated
statements, so the vendor can open straight on its list.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import golden1_site as site

# The vendor's page as the trace describes it. A dated list, and a
# dateless View PDF for the current statement beside a date that names
# no statement at all, the day the page was read.
VENDOR = """<body>
  <main>
    <section><h2>Current Statement</h2><p>As of 09/21/2026</p>
      <p><a href="#">View PDF</a></p></section>
    <section><h2>History</h2>
      <a href="#">08/31/26</a><a href="#">07/31/26</a><a href="#">06/30/26</a>
      <a href="#">Pay my loan</a>
    </section>
  </main>
</body>"""


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


@pytest.fixture()
def on_the_vendor(monkeypatch):
    """The page under test is the vendor's tab already, and nothing
    navigates away from it."""
    monkeypatch.setattr(site, "open_vendor", lambda p: None)
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "scroll_full_page", lambda p, *a, **k: None)


def test_discovery_reads_only_the_dates_the_vendor_lists(page, on_the_vendor):
    page.set_content(VENDOR)
    docs = site.collect_download_docs(page)
    assert [d.date_text for d in docs] == ["2026-08-31", "2026-07-31", "2026-06-30"]
    assert all(d.dated_by == "label" for d in docs)
    assert "2026-09-21" not in [d.date_text for d in docs]


def test_capture_finds_each_discovered_date_and_nothing_for_a_date_not_listed(page, on_the_vendor):
    page.set_content(VENDOR)
    for d in site.collect_download_docs(page):
        el, label = site._control_for(page, d.date_text)
        assert el is not None and site.parse_date(label) == d.date_text
    el, _ = site._control_for(page, "2026-09-21")
    assert el is None
    assert "2026-09-21" not in site._control_dates(page)


def test_a_row_date_is_taken_only_when_the_row_names_one_day(page):
    page.set_content("""<body>
      <div><p>Statement 08/31/2026</p><p><a id="one" href="#">View PDF</a></p></div>
      <div><p>08/01/2026 to 08/31/2026</p><p><a id="two" href="#">View PDF</a></p></div>
    </body>""")
    one = page.locator("#one")
    two = page.locator("#two")
    assert site._date_of_control(one, "View PDF", False) == ("2026-08-31", "row")
    assert site._date_of_control(two, "View PDF", False)[0] is None
    # Beside a dated list a dateless control is not read at all.
    assert site._date_of_control(one, "View PDF", True)[0] is None
    assert site._date_of_control(one, "08/31/26", True) == ("2026-08-31", "label")


def test_the_trace_says_the_list_was_already_there_without_statement_history(page, on_the_vendor, tmp_path):
    page.set_content(VENDOR.replace("<h2>History</h2>", ""))
    trace = []
    ok = site.download_bill(page, tmp_path, "2026-09-21", tmp_path / "x.pdf", trace=trace)
    assert ok is False
    notes = [t.get("note") for t in trace]
    assert "no statement history control, the vendor's page already lists dated statements" in notes
    listed = next(t for t in trace if "dated_statements" in t)
    assert listed["dated_statements"] == 3
    missing = next(t for t in trace if t.get("note") == "no control on this page carries that date")
    assert "2026-09-21" not in missing["dates_here"]
    assert "2026-08-31" in missing["dates_here"]


# -- the orchestrator ---------------------------------------------------------

import golden1_docs  # noqa: E402
from paperpull_core.models import State  # noqa: E402


class _Store:
    def __init__(self, data):
        self.data = data


def _app_with(records):
    app = object.__new__(golden1_docs.App)
    app.discovery = _Store(dict(records))
    return app


def test_a_date_an_earlier_discovery_made_up_is_retired_once_the_vendor_lists_its_own():
    stale = "Statement:2026-09-21:Account Statement - Sep 21, 2026:"
    kept_done = "Statement:2026-05-31:Account Statement - May 31, 2026:"
    listed = "Statement:2026-08-31:Account Statement - Aug 31, 2026:"
    app = _app_with({stale: {"state": State.NEEDS_MANUAL_REVIEW.value},
                     kept_done: {"state": State.COMPLETED.value, "downloaded_ok": True},
                     listed: {"state": State.DISCOVERED.value}})
    app._listed_keys = {listed}
    docs = [site.RawDoc(title="Account Statement - Aug 31, 2026", date_text="2026-08-31",
                        dated_by="label")]
    assert app._retire_unlisted(docs) == 1
    assert set(app.discovery.data) == {kept_done, listed}


def test_nothing_is_retired_when_the_list_was_not_read_from_the_vendors_own_dates():
    app = _app_with({"a": {"state": State.DISCOVERED.value}})
    app._listed_keys = set()
    assert app._retire_unlisted([]) == 0
    assert app._retire_unlisted([site.RawDoc(title="t", date_text="2026-08-31", dated_by="row")]) == 0
    assert set(app.discovery.data) == {"a"}


def _text_pdf(path: Path, text: str) -> None:
    """A one page PDF whose text pypdf can read back."""
    stream = ("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % text).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out) + b" " * 4000)


def _capturing_app(tmp_path, monkeypatch, printed: str):
    app = object.__new__(golden1_docs.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(tmp_path / "p.json")
    app.discovery = storage.JsonStore(tmp_path / "d.json")
    app.index_csv = storage.CsvFile(tmp_path / "i.csv", storage.DOCUMENT_INDEX_COLUMNS)
    app._dl_dir = tmp_path
    app._journal = None
    app.stats = {"manual_review": 0, "new_files": [], "dates": [], "statements": 0,
                 "tax_documents": 0, "insurance_documents": 0, "other": 0,
                 "validation_failures": 0, "duplicate_filenames": 0}
    app.check_session = lambda page: None
    app.write_failure = lambda *a, **k: None
    monkeypatch.setattr(golden1_docs.site, "goto_documents", lambda page: True)

    def fake_download(page, dl_dir, iso, out_path, title="", trace=None):
        _text_pdf(Path(out_path), printed)
        return True
    monkeypatch.setattr(golden1_docs.site, "download_bill", fake_download)
    return app


class _Page:
    url = "https://ebank.hepsiian.com/statements"


def _doc():
    return golden1_docs.Document(title="Account Statement - Aug 31, 2026",
                                 category="Statement", summary="Account Statement",
                                 date="2026-08-31")


def test_a_statement_that_does_not_print_its_date_is_not_filed_under_it(tmp_path, monkeypatch):
    app = _capturing_app(tmp_path, monkeypatch,
                         "Golden 1 Credit Union Statement Period Ending 09/30/26 Page 1 of 3")
    doc = _doc()
    app.download_one(_Page(), doc, "2026-08-31 Golden 1 Account Statement.pdf")
    assert not list(app.paths.folder_for(doc.category).glob("*.pdf"))
    assert app.progress.get(doc.key)["state"] == State.NEEDS_MANUAL_REVIEW.value
    attempt = json.loads((app.paths.diagnostics / "download-attempt.json").read_text())
    note = attempt["responses"][-1]
    assert note["check"]["outcome"] == "refused"
    assert "09/30/26" not in json.dumps(attempt)


def test_a_statement_that_prints_its_date_is_filed(tmp_path, monkeypatch):
    app = _capturing_app(tmp_path, monkeypatch,
                         "Golden 1 Credit Union Statement Period Ending 08/31/26 Page 1 of 3")
    app.journal.checkpoint = lambda *a, **k: None
    doc = _doc()
    app.download_one(_Page(), doc, "2026-08-31 Golden 1 Account Statement.pdf")
    assert app.progress.get(doc.key)["state"] == State.COMPLETED.value
    assert list(app.paths.folder_for(doc.category).glob("*.pdf"))
