"""Mercury statement tests with invented UUIDs, accounts and periods."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mercury_site as site
from paperpull_core.testkit import text_pdf


CHECKING = "00000000-0000-0000-0000-000000000001"
SAVINGS = "00000000-0000-0000-0000-000000000002"
ORG = "00000000-0000-0000-0000-000000000003"
CREDIT = "00000000-0000-0000-0000-000000000004"
MONTH = "Feb 2032"


def row(key=CHECKING, account="Checking ••4321", period=MONTH, **extra):
    return dict({"id": key, "account": account, "period": period,
                 "available": True, "selected": False}, **extra)


def sample_pdf(number="000000004321", title="February 2032 statement",
               period="February 1, 2032-February 29, 2032 (29 days)"):
    return text_pdf(["Mercury", title, period, f"Account Number {number}",
                     "Routing Number 000000000"])


def test_discovery_preserves_accounts_and_years():
    docs = [s.doc for s in site._parse_rows([
        row(), row(SAVINGS, "Savings ••1234"),
        row(ORG, period="Dec 2031"),
        row(account="Credit", period=MONTH + "\nUpcoming"),
        row(CREDIT, "Credit ••1234"),
        row(account="Treasury ••1234"),
        row(account="Sweep Program"),
    ]).values()]
    assert [(d.account, d.date_text) for d in docs] == [
        ("Checking", "2032-02-29"), ("Savings", "2032-02-29"), ("Checking", "2031-12-31")
    ]
    assert len({d.document_id for d in docs}) == 3
    assert CHECKING not in repr(docs) and "4321" not in repr(docs)


@pytest.mark.parametrize("rows", [
    [row(key="unrecognized")],
    [row(period="Today")],
    [row(), row()],
    [row(available=False)],
    [row(account="Checking")],
])
def test_incomplete_deposit_lists_stop(rows):
    with pytest.raises(site.ListStopped):
        site._parse_rows(rows)


@pytest.mark.parametrize("input_url", [
    f"http://backend.mercury.com/organizations/{ORG}/statements/{CHECKING}",
    f"https://backend.mercury.com.evil.test/organizations/{ORG}/statements/{CHECKING}",
    f"https://backend.mercury.com/organizations/{ORG}/statements/{SAVINGS}",
    f"https://backend.mercury.com/organizations/{ORG}/statements/{CHECKING}?redirect=1",
    f"https://backend.mercury.com/users/{ORG}/statements/{CHECKING}",
])
def test_only_takes_the_pdf_address_for_the_selected_row(input_url):
    assert not site._download_address(input_url, CHECKING)


@pytest.mark.parametrize("pdf, accepted", [
    (sample_pdf(), True),
    (sample_pdf(period="February 20, 2032-February 29, 2032 (10 days)"), True),
    (sample_pdf(number="000000001234"), False),
    (sample_pdf(title="February 2031 statement"), False),
    (sample_pdf(period="January 1, 2032-January 31, 2032 (31 days)"), False),
    (sample_pdf(period="February 20, 2032-February 1, 2032"), False),
    (b"<html>Sign in</html>", False),
])
def test_account_and_period_must_match(pdf, accepted):
    statement, = site._parse_rows([row()]).values()
    assert site._matches_pdf(pdf, statement) is accepted


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    template = """
    <table><tbody>
      <tr><td></td><td>Statement period</td><td>Account</td></tr>
      <tr><td><label><input type="checkbox" value="ROW_CHECKING"></label></td>
          <td>Feb 2032</td><td>Checking ••4321</td></tr>
      <tr><td><label><input type="checkbox" value="ROW_SAVINGS"></label></td>
          <td>Feb 2032</td><td>Savings ••1234</td></tr>
      <tr><td><label><input type="checkbox" value="ROW_CREDIT"></label></td>
          <td>Feb 2032</td><td>Credit ••1234</td></tr>
    </tbody></table>
    <button>Share document</button>
    <a hidden>Download</a>
    <script>
    for (const box of document.querySelectorAll('input')) {
        box.addEventListener('change', () => {
            const link = document.querySelector('a');
            link.hidden = !box.checked;
            if (box.checked) link.href = 'https://backend.mercury.com/organizations/ORG_ID/statements/' + box.value;
        });
    }
    </script>
    """
    html = (template.replace("ROW_CHECKING", CHECKING).replace("ROW_SAVINGS", SAVINGS)
            .replace("ROW_CREDIT", CREDIT).replace("ORG_ID", ORG))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.fulfill(
                body=html, content_type="text/html; charset=utf-8"
            ) if route.request.url == site.DOCUMENTS_URL else route.abort())
            tab.goto(site.DOCUMENTS_URL)
            yield tab
        finally:
            browser.close()


def test_site_reads_table_and_selects_each_pdf_by_its_row_id(page, tmp_path, monkeypatch):
    fetches = []
    def fetch(_page, href):
        key = href.rsplit("/", 1)[1]
        fetches.append(key)
        selected = page.locator('input:checked')
        assert selected.count() == 1 and selected.input_value() == key
        return sample_pdf(number="000000004321" if key == CHECKING else "000000001234")

    monkeypatch.setattr(site, "_fetch_pdf", fetch)
    docs = site.collect_download_docs(page)
    assert {d.account for d in docs} == {"Checking", "Savings"}
    for doc in docs:
        output = tmp_path / f"{doc.account}.pdf"
        assert site.download_bill(page, doc.date_text, output, account=doc.account,
                                  document_id=doc.document_id)
        assert output.exists()
        assert not page.locator('input:checked').count()
    assert fetches == [CHECKING, SAVINGS]


def test_existing_user_selection_is_left_alone(page, tmp_path, monkeypatch):
    page.locator("label").nth(1).click()
    doc = site.collect_download_docs(page)[0]
    def unexpected(*_args):
        pytest.fail("A download began with a pre-existing selection")
    monkeypatch.setattr(site, "_fetch_pdf", unexpected)
    with pytest.raises(site.ListStopped, match="Clear the selected rows"):
        site.download_bill(page, doc.date_text, tmp_path / "statement.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert page.locator('input:checked').input_value() == SAVINGS


@pytest.mark.parametrize("danger", ["label-points-elsewhere", "payment-label"])
def test_guard_refuses_selection_controls_that_change_meaning(page, tmp_path, danger):
    doc = site.collect_download_docs(page)[0]
    if danger == "label-points-elsewhere":
        page.locator("input").last.evaluate("(e) => e.id = 'other-choice'")
        page.locator("label").first.evaluate("(e) => e.htmlFor = 'other-choice'")
    else:
        page.locator("label").first.evaluate("(e) => e.title = 'Send payment'")
    with pytest.raises(site.ListStopped, match="selection control changed"):
        site.download_bill(page, doc.date_text, tmp_path / "statement.pdf",
                           account=doc.account, document_id=doc.document_id)
    assert not page.locator("input:checked").count()


@pytest.mark.parametrize("status, mime, data", [
    (401, "application/pdf", b""), (403, "application/pdf", b""),
    (302, "text/html", b""), (200, "text/html", b"<html>Sign in</html>"),
    (200, "application/pdf", b"<html>Not a statement</html>"),
    (429, "text/html", b""),
])
def test_pdf_fetch_does_not_follow_redirects_and_disposes_refusals(status, mime, data):
    calls = []
    disposed = []
    response = SimpleNamespace(status=status, headers={"content-type": mime},
                               body=lambda: data, dispose=lambda: disposed.append(True))

    def get(href, **kwargs):
        assert kwargs["max_redirects"] == 0
        calls.append(href)
        return response

    fake_page = SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(get=get)))
    link = f"https://backend.mercury.com/organizations/{ORG}/statements/{CHECKING}"
    exception = site.ListStopped if status == 429 else site.SessionExpired
    with pytest.raises(exception):
        site._fetch_pdf(fake_page, link)
    assert calls == [link] and disposed == [True]


@pytest.mark.parametrize("list_answer", ["ready", "signed-out", "unread", "other-organization"])
def test_refused_pdf_is_weighed_against_the_refreshed_list(page, tmp_path, monkeypatch, list_answer):
    doc = site.collect_download_docs(page)[0]
    fetches = []

    def refused(_page, href):
        fetches.append(href)
        raise site.SessionExpired()

    monkeypatch.setattr(site, "_fetch_pdf", refused)
    if list_answer == "signed-out":
        login = site.URLS["login"]
        page.route(login, lambda r: r.fulfill(body='<input type="password">'))
        page.route(site.DOCUMENTS_URL, lambda r: r.fulfill(status=302, headers={"Location": login}))
    elif list_answer == "unread":
        page.route(site.DOCUMENTS_URL, lambda r: r.fulfill(
            body="<table><tr><td>Statement period</td></tr></table>", content_type="text/html"
        ))
    elif list_answer == "other-organization":
        other_org = page.content().replace(CHECKING, ORG)
        page.route(site.DOCUMENTS_URL, lambda r: r.fulfill(body=other_org, content_type="text/html"))
    path = tmp_path / "statement.pdf"
    if list_answer == "ready":
        assert not site.download_bill(page, doc.date_text, path, account=doc.account,
                                      document_id=doc.document_id)
        assert not page.locator("input:checked").count()
    else:
        exc = site.SessionExpired if list_answer == "signed-out" else site.ListStopped
        with pytest.raises(exc):
            site.download_bill(page, doc.date_text, path, account=doc.account,
                               document_id=doc.document_id)
    assert len(fetches) == 1 and not path.exists()


def test_app_keeps_a_wrong_pdf_pending_and_reuses_a_correct_saved_statement(page, tmp_path, monkeypatch):
    import mercury_docs as mercury

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Example", "output_dir": str(tmp_path),
                                  "min_pdf_bytes": 100}))
    monkeypatch.setattr(mercury.App, "_setup_logging", lambda self: None)
    app = mercury.App(mercury.build_parser().parse_args(["--config", str(config)]))
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "_delay", lambda: None)
    assert app.cmd_discover(quiet=True) == 2
    selected = app._select()
    monkeypatch.setattr(site, "_fetch_pdf", lambda _page, _href: sample_pdf())
    app.process(selected)
    assert len(app.stats["new_files"]) == 1
    assert [doc.account for doc in app._select(pending_only=True)] == ["Savings"]
    monkeypatch.setattr(site, "_fetch_pdf",
                        lambda _page, _href: sample_pdf(number="000000001234"))
    app.cmd_resume()
    assert not app._select(pending_only=True)
    assert len(app.stats["new_files"]) == 2


@pytest.mark.parametrize("mode", [(), ("--all",), ("--pilot",), ("--resume",)])
def test_offline_preview_uses_saved_discovery_and_preserves_last_download(
    tmp_path, monkeypatch, capsys, mode,
):
    import mercury_docs as mercury

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Example", "output_dir": str(tmp_path)}))
    monkeypatch.setattr(mercury.App, "_setup_logging", lambda self: None)
    app = mercury.App(mercury.build_parser().parse_args(["--config", str(config)]))
    statement, = site._parse_rows([row()]).values()
    app._record_rawdoc(statement.doc, site.DOCUMENTS_URL)
    app.discovery.save()
    last_files = app.paths.root / "new-this-run.txt"
    app.paths.run_summary.write_text("previous download summary")
    last_files.write_text("previous file")

    def inaccessible(_app):
        pytest.fail("An offline preview tried to open a browser")

    monkeypatch.setattr(mercury.App, "browser", inaccessible)
    assert mercury.main(["--config", str(config), "--dry-run", *mode]) == 0
    output = capsys.readouterr().out
    assert "DRY RUN - would save:" in output
    assert "PAPERPULL_RUN_RESULT " in output
    summary = dict(line.split(":", 1) for line in app.paths.run_summary.read_text().splitlines() if ":" in line)
    assert summary["Mode"].strip() == "dry-run"
    assert summary["Documents known"].strip() == "1"
    assert summary["NEW files this run"].strip() == "0"
    assert last_files.read_text() == "previous file"
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize("account", ["Payroll ••5678", "Operations", "Brokerage ••1234"])
def test_a_row_of_an_account_it_does_not_know_stops_the_list(account):
    # A renamed or new kind of deposit account, or a row still loading,
    # skipped here would leave its statements out of a list called whole.
    with pytest.raises(site.ListStopped, match="does not recognize"):
        site._parse_rows([row(), row(SAVINGS, account)])


@pytest.mark.parametrize("cells", [("No statements", ""), ("", "")])
def test_a_row_with_no_account_is_said_as_empty_or_loading(cells):
    period, account = cells
    with pytest.raises(site.ListStopped, match="no account"):
        site._parse_rows([row(period=period, account=account)])


def test_a_table_with_no_rows_is_not_an_empty_list(page):
    page.evaluate("() => document.querySelectorAll('tr').forEach((r, i) => i && r.remove())")
    with pytest.raises(site.ListStopped, match="no statements"):
        site.collect_download_docs(page)


def beside_the_table(page, html):
    page.evaluate("(html) => document.querySelector('table').insertAdjacentHTML('afterend', html)",
                  html)


@pytest.mark.parametrize("control", [
    "<button>Next</button>", "<a href='#'>Load more</a>",
    "<button aria-label='Next page'>&gt;</button>",
    "<button aria-label='Go to next page'></button>", "<button>›</button>",
    "<a href='#'>Load older statements</a>",
])
def test_a_table_that_shows_only_part_of_its_list_stops(page, control):
    beside_the_table(page, control)
    with pytest.raises(site.ListStopped, match="only part"):
        site.collect_download_docs(page)


def test_a_pager_in_the_table_s_own_footer_stops(page):
    page.evaluate("""() => document.querySelector('table').insertAdjacentHTML('beforeend',
        '<tfoot><tr><td colspan=3><button>Next</button></td></tr></tfoot>')""")
    with pytest.raises(site.ListStopped, match="only part"):
        site.collect_download_docs(page)


@pytest.mark.parametrize("control", [
    "<button disabled>Next</button>", "<button aria-disabled='true'>Next page</button>",
    "<button hidden>Load more</button>",
])
def test_a_pager_with_nothing_more_to_show_reads_the_list(page, control):
    beside_the_table(page, control)
    assert {d.account for d in site.collect_download_docs(page)} == {"Checking", "Savings"}


def test_a_next_elsewhere_on_the_page_is_not_the_table_s_pager(page):
    # A product tour's Next in a section of its own, away from the table.
    page.evaluate("""() => {
        const table = document.querySelector('table');
        const own = document.createElement('section');
        table.replaceWith(own);
        own.append(table);
        document.body.insertAdjacentHTML('beforeend',
            '<section><button>Next</button><a href="#">See more</a></section>');
    }""")
    assert {d.account for d in site.collect_download_docs(page)} == {"Checking", "Savings"}
