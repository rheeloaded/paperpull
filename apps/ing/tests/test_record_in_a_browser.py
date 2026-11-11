"""A simulated banking page exercises Record without contacting ING."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ing_docs as docs
import ing_site as site
from paperpull_core import recorder, redact

pw_api = pytest.importorskip("playwright.sync_api")

# Playwright's own Chromium, as every suite here runs on, never the Edge or
# Chrome installed on this computer, with every name resolved to nowhere so
# a request the route below does not answer cannot leave the machine.
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(redact, "_PRIVATE_WORDS", [])
    with pw_api.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=ARGS)
        context = browser.new_context()

        def answer(route):
            path = urlsplit(route.request.url).path
            if path == "/app/overview":
                route.fulfill(content_type="text/html", body=(
                    '<a href="/app/postbox?account=QxToken123456&amp;filter=income">Postbox</a>'))
            elif path == "/app/postbox":
                route.fulfill(content_type="text/html", body=(
                    '<button onclick="fetch(\'/api/documents\')">Download</button>'))
            elif path == "/api/documents":
                route.fulfill(content_type="application/json", body=json.dumps({
                    "documents": [{"title": "private example", "id": "secret123456"}]}))
            elif path == "/app/postbox/postbox_archiv":
                route.fulfill(content_type="text/html", body="""
                    <div class="account-filters"></div>
                    <div class="ibbr-table-wrapper-postbox">
                      <div class="ibbr-table-row postbox-unread">
                        <div class="postbox-grid-left"><span>Account</span></div>
                        <div class="postbox-grid-description">Private May Price</div>
                        <div class="postbox-grid-right">01.02.2026</div>
                        <a href="/private-account-id" onclick="window.clicked = true">Download</a>
                      </div>
                    </div>
                    <button onclick="window.clicked = true">Next page</button>
                    <script>window.clicked = false;</script>
                """)
            else:
                route.fulfill(status=404, content_type="text/plain", body="not found")

        context.route("**/*", answer)
        page = context.new_page()
        page.goto("https://banking.ing.de/app/overview")
        try:
            yield page
        finally:
            context.close()
            browser.close()


def test_recording_captures_navigation_and_requests_after_it_starts(page, tmp_path, monkeypatch):
    def navigate(page, stop_file, say):
        page.get_by_role("link", name="Postbox").click()
        with page.expect_response("**/api/documents"):
            page.get_by_role("button", name="Download").click()

    monkeypatch.setattr(recorder, "_wait_for_stop", navigate)
    output = recorder.record_session(page, site, tmp_path, provider="ING",
                                     owner="May Price", say=lambda *args: None,
                                     include_html=True)
    assert output
    text = Path(output).read_text(encoding="utf-8")
    report = json.loads(text)
    assert [step["action"] for step in report["steps"]] == ["click", "click"]
    assert report["steps"][0]["effect"]["navigated"] is True
    assert report["steps"][1]["label"] == "Download"
    assert any(request["type"] == "html" and request["method"] == "GET"
               and request.get("query_keys") == ["account", "filter"]
               for request in report["requests"])
    assert any(request["type"] == "json" and request["method"] == "GET"
               for request in report["requests"])
    assert "secret123456" not in text and "private example" not in text
    assert "QxToken123456" not in text and "income" not in text


def test_diagnose_survey_does_not_follow_the_postbox_link(page):
    before = page.url
    report = site.survey(page, dwell_ms=0)
    assert len(report["pages"]) == 1
    assert page.url == before


def test_postbox_census_counts_shapes_without_clicking_or_returning_values(page):
    page.goto("https://banking.ing.de/app/postbox/postbox_archiv")
    before = page.url
    census = site.postbox_census(page)
    assert census == {
        "inspected": True, "area": "archive", "table_present": True,
        "filter_present": True, "truncated": False, "rows": 1,
        "rows_with_kind": 1, "rows_with_subject": 1, "rows_with_date": 1,
        "rows_with_parseable_date": 1, "rows_with_download": 1,
        "statement_candidates": 0, "tax_candidates": 0,
        "unread_rows": 1, "pagination_controls": 1,
    }
    assert page.url == before and page.evaluate("window.clicked") is False
    assert "May Price" not in str(census) and "private-account-id" not in str(census)


def test_postbox_census_checks_dates_and_candidate_categories_in_the_page(page):
    page.goto("https://banking.ing.de/app/postbox/postbox_archiv")
    page.set_content("""
        <div class="ibbr-table-body">
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>Kontoauszug</span></div>
            <div class="postbox-grid-description">Private May Price</div>
            <div class="postbox-grid-right">01.02.2026</div>
            <a href="/private-account-id">Download</a>
          </div>
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>Jahressteuerbescheinigung</span></div>
            <div class="postbox-grid-description">Private tax details</div>
            <div class="postbox-grid-right">29.02.2024</div>
          </div>
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>Kontoauszug</span></div>
            <div class="postbox-grid-description">Steuerbescheinigung</div>
            <div class="postbox-grid-right">31.02.2026</div>
          </div>
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>Wertpapierabrechnung</span></div>
            <div class="postbox-grid-description">Portfolio</div>
            <div class="postbox-grid-right">2023-02-28</div>
          </div>
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>bankAccountStatement</span></div>
            <div class="postbox-grid-description">Private details</div>
            <div class="postbox-grid-right">0000-01-01</div>
          </div>
        </div>
    """)

    census = site.postbox_census(page)

    # Dates as a run reads them: the one German day a date cell shows, so an
    # ISO date, a day that does not exist and the year 0 are not read.
    assert census["rows"] == 5
    assert census["rows_with_parseable_date"] == 2
    assert census["statement_candidates"] == 3
    assert census["tax_candidates"] == 1
    assert census["rows_with_download"] == 1
    text = json.dumps(census)
    for private in ("May Price", "01.02.2026", "private-account-id", "Portfolio"):
        assert private not in text


def test_postbox_census_counts_what_a_run_reads_of_the_same_rows(page, monkeypatch):
    monkeypatch.setitem(site._READING, "pause", 10)
    examples = [
        ("Kontoauszug", "", "1.2.2026"),
        ("Steuerbescheinigung", "", "29.02.2024"),
        ("Ertraegnisaufstellung", "", "29.02.1900"),
        ("bankAccountStatement", "", "2024-02-29T12:00:00Z"),
        ("Jahressteuerbescheinigung", "", "0001-01-01"),
        ("Kontoauszug", "", "2201-01-01"),
        ("Wertpapierabrechnung", "Kontoauszug", "0000-01-01"),
        ("Kontoauszug", "Steuerbescheinigung", "31.04.2025"),
        ("Kontoauszug", "", "Datum: 05.03.2026"),
        ("Kontoauszug", "", "01.02.2026 bis 28.02.2026"),
        ("Kontoauszug", "", "01.01.1900"),
        ("Kontoauszug", "", "31.12.2200"),
        ("Kontoauszug", "", "01.01.2201"),
        ("Mitteilung", "", "2026-03-1"),
        ("Depot", "", "not a date"),
    ]
    page.goto("https://banking.ing.de/app/postbox/postbox_archiv")
    page.evaluate("""examples => {
      document.body.innerHTML = '<div class="ibbr-table-body"></div>';
      const body = document.querySelector(".ibbr-table-body");
      for (const [kind, subject, date] of examples) {
        const row = document.createElement("div");
        row.className = "ibbr-table-row";
        for (const [className, value] of [
          ["postbox-grid-left", kind], ["postbox-grid-description", subject],
          ["postbox-grid-right", date]
        ]) {
          const cell = document.createElement("div");
          cell.className = className;
          if (className === "postbox-grid-left") {
            const span = document.createElement("span");
            span.textContent = value;
            cell.appendChild(span);
          } else {
            cell.textContent = value;
          }
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
    }""", examples)

    census = site.postbox_census(page)
    seen = site._look(page, scroll=False)

    assert census["rows"] == len(seen["rows"]) == len(examples)
    read = sum(bool(r["date"] and site.parse_date(r["date"])) for r in seen["rows"])
    assert census["rows_with_parseable_date"] == read == 5
    assert census["statement_candidates"] == sum(
        site.classify(r["kind"], r["subject"]) == site.ACCOUNT for r in seen["rows"])
    assert census["tax_candidates"] == sum(
        site.classify(r["kind"], r["subject"]) == site.TAX for r in seen["rows"])
    assert census["statement_candidates"] and census["tax_candidates"]


def test_diagnose_writes_the_postbox_census_without_private_values(
        page, tmp_path, monkeypatch, capsys):
    page.goto("https://banking.ing.de/app/postbox/postbox_archiv")
    config = json.loads((Path(site.__file__).parent / "config.example.json").read_text())
    config.update(owner="May Price", output_dir=str(tmp_path / "output"),
                  profile_dir=str(tmp_path / "profile"))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    app = docs.App(docs.build_parser().parse_args(["--config", str(config_path)]))
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setitem(site._READING, "pause", 10)
    survey = site.survey
    monkeypatch.setattr(site, "survey", lambda page: survey(page, dwell_ms=0))

    app.cmd_diagnose()

    text = (app.paths.diagnostics / "diagnose-documents.json").read_text()
    report = json.loads(text)
    assert report["survey"]["postbox_structure"]["rows_with_download"] == 1
    assert report["survey"]["postbox_structure"]["rows_with_parseable_date"] == 1
    assert report["survey"]["postbox_structure"]["statement_candidates"] == 0
    assert report["survey"]["postbox_structure"]["tax_candidates"] == 0
    assert report["survey"]["postbox_structure"]["area"] == "archive"
    # The archive shows a further page, so its rows are not called read.
    assert report["collected"] is None and "collect_error" in report
    assert "May Price" not in text and "private-account-id" not in text
    output = " ".join(capsys.readouterr().out.split())
    assert "Postbox DOM: 1 rows, 1 with a download link" in output
    assert "1 readable dates, 0 possible statements and 0 possible tax documents" in output
    assert "1 marked unread, 1 paging controls." in output
    assert "Rows collected: unavailable" in output
    assert "May Price" not in output and "01.02.2026" not in output
    assert page.url.endswith("/app/postbox/postbox_archiv")
    assert page.evaluate("window.clicked") is False


@pytest.fixture
def empty_archive(page, monkeypatch):
    monkeypatch.setitem(site._READING, "pause", 10)
    page.goto("https://banking.ing.de/app/postbox/postbox_archiv")
    page.set_content("""
        <div class="ibbr-table-wrapper-postbox">
          <div class="ibbr-table-header">
            <div class="ibbr-table-row" role="row">
              <span role="columnheader"><a href="#sort-kind"
                onclick="window.clicked = true">Dokumentenart</a></span>
              <span role="columnheader"><a href="#sort-subject"
                onclick="window.clicked = true">Betreff</a></span>
              <span role="columnheader"><a href="#sort-date"
                onclick="window.clicked = true">Datum</a></span>
            </div>
          </div>
          <div class="ibbr-table-body" role="rowgroup"></div>
          <p>Zu Ihrer Suche können keine Dokumente angezeigt werden.
             Bitte passen Sie gegebenenfalls Ihre Suche oder die Filterkriterien an.</p>
        </div>
        <script>window.clicked = false;</script>
    """)
    return page


def test_an_empty_archive_with_column_headers_is_read_as_empty(empty_archive):
    before = empty_archive.url

    seen = site._look(empty_archive, scroll=False)
    assert seen["rows"] == []
    assert seen["empty"] is True and seen["settled"] is True
    area = site._read_area(empty_archive, "archive", navigate=False, scroll=False)
    assert area["rows"] == area["candidates"] == []
    assert area["undated"] == 0
    assert empty_archive.url == before and empty_archive.evaluate("window.clicked") is False


def test_the_empty_archive_census_does_not_count_column_headers(empty_archive):
    census = site.postbox_census(empty_archive)
    assert census["table_present"] is True
    for key in ("rows", "rows_with_kind", "rows_with_subject", "rows_with_date",
                "rows_with_parseable_date", "rows_with_download",
                "statement_candidates", "tax_candidates"):
        assert census[key] == 0, key
    assert empty_archive.evaluate("window.clicked") is False


def test_column_headers_without_an_empty_notice_do_not_prove_an_empty_archive(empty_archive):
    empty_archive.locator("p").evaluate("node => node.remove()")
    with pytest.raises(site.ListStopped, match="no rows this app reads"):
        site._read_area(empty_archive, "archive", navigate=False, scroll=False)


@pytest.mark.parametrize("notice,where", [
    # The notice ING shows for an empty list, but outside the list's box,
    # where a header or a side panel says something else.
    ("Zu Ihrer Suche können keine Dokumente angezeigt werden.", "body"),
    # No new messages, or a count, is not a list with nothing in it.
    ("Keine neuen Nachrichten", ".ibbr-table-wrapper-postbox"),
    ("0 Dokumente", ".ibbr-table-wrapper-postbox"),
    ("No messages", ".ibbr-table-wrapper-postbox"),
])
def test_only_the_lists_own_empty_notice_reads_as_an_empty_list(empty_archive, notice, where):
    empty_archive.locator("p").evaluate("node => node.remove()")
    empty_archive.locator(where).evaluate(
        '(node, text) => node.insertAdjacentHTML("beforeend", "<p>" + text + "</p>")', notice)
    assert site._look(empty_archive, scroll=False)["empty"] is False
    with pytest.raises(site.ListStopped, match="no rows this app reads"):
        site._read_area(empty_archive, "archive", navigate=False, scroll=False)


def test_an_empty_notice_does_not_hide_unrecognized_document_rows(empty_archive):
    empty_archive.locator(".ibbr-table-body").evaluate("""node => {
        const row = document.createElement("div");
        row.className = "ibbr-table-row";
        row.textContent = "An unrecognized document";
        node.appendChild(row);
    }""")
    with pytest.raises(site.ListStopped, match="no rows this app reads"):
        site._read_area(empty_archive, "archive", navigate=False, scroll=False)


@pytest.mark.parametrize("row_parent", [
    ".ibbr-table-body", ".ibbr-table-wrapper-postbox", "body",
])
def test_an_empty_notice_does_not_hide_a_document(empty_archive, row_parent):
    empty_archive.locator(row_parent).evaluate("""node => {
        node.insertAdjacentHTML("beforeend", `
          <div class="ibbr-table-row">
            <div class="postbox-grid-left"><span>Kontoauszug</span></div>
            <div class="postbox-grid-description">Kontoauszug 01/2026</div>
            <div class="postbox-grid-right">31.01.2026</div>
            <a href="/app/document">Download</a>
          </div>`);
    }""")
    area = site._read_area(empty_archive, "archive", navigate=False, scroll=False)
    assert len(area["rows"]) == 1
    assert area["rows"][0]["date"] == "2026-01-31"
    assert site.postbox_census(empty_archive)["rows"] == 1
    assert empty_archive.evaluate("window.clicked") is False


@pytest.mark.parametrize("obstacle,reason", [
    ('<button>Next page</button>', "further page"),
    ('<button>Weitere Dokumente laden</button>', "further page"),
    ('<a href="#more">Ältere Nachrichten anzeigen</a>', "further page"),
    ('<button>Load older documents</button>', "further page"),
    ('<div aria-busy="true">Loading</div>', "still loading"),
])
def test_an_empty_notice_does_not_hide_paging_or_loading(empty_archive, obstacle, reason):
    empty_archive.locator(".ibbr-table-wrapper-postbox").evaluate(
        '(node, html) => node.insertAdjacentHTML("beforeend", html)', obstacle)
    with pytest.raises(site.ListStopped, match=reason):
        site._read_area(empty_archive, "archive", navigate=False, scroll=False)
