"""Diagnostics say what the Postbox on screen shows without exposing the owner,
and without moving the tab."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ing_docs as docs
import ing_site as site
from paperpull_core import redact

POSTBOX = site.URLS["documents"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(redact, "_PRIVATE_WORDS", [])
    config = json.loads((Path(site.__file__).parent / "config.example.json").read_text())
    config.update(owner="May Price", output_dir=str(tmp_path / "output"),
                  profile_dir=str(tmp_path / "profile"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    args = docs.build_parser().parse_args(["--config", str(path)])
    return docs.App(args)


def test_diagnose_away_from_the_postbox_reports_no_listing_rather_than_zero(
        app, monkeypatch, capsys):
    page = SimpleNamespace(url="https://banking.ing.de/app/obligo")
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)
    monkeypatch.setattr(site, "survey", lambda page: {
        "pages": [{"title": "May Price"}], "responses": []})

    app.cmd_diagnose()

    text = (app.paths.diagnostics / "diagnose-documents.json").read_text()
    report = json.loads(text)
    assert report["collected"] is None
    assert "collect_error" in report
    assert "May" not in text and "Price" not in text
    assert "Rows collected: unavailable" in capsys.readouterr().out


def _row(subject, date="28.01.2026", unread=False, link="download"):
    return {"kind": "Kontoauszug", "subject": subject, "date": date, "unread": unread,
            "hrefs": ["%s?3-1.-rows-0-%s" % (POSTBOX, link)] if link else []}


class Postbox:
    """The Postbox on screen, which Diagnose reads as it stands."""
    url = POSTBOX

    def __init__(self, rows):
        self.rows = rows
        self.looks = []

    def locator(self, _selector):
        return SimpleNamespace(count=lambda: 0, inner_text=lambda timeout=None: "")

    def title(self):
        return "Internetbanking"

    def goto(self, *_a, **_kw):
        pytest.fail("Diagnose must not move the tab")

    def evaluate(self, _js, arg=None):
        assert isinstance(arg, dict) and "rowSelectors" in arg, "Diagnose only reads rows"
        self.looks.append(arg["scroll"])
        return {"table_present": True, "settled": True, "truncated": False, "empty": False,
                "pagination": 0, "rows": self.rows}


def test_diagnose_reads_the_postbox_on_screen_and_says_what_it_left_out(
        app, monkeypatch, capsys):
    page = Postbox([_row("Kontoauszug 01/2026"),
                    _row("Kontoauszug 02/2026", "28.02.2026", unread=True),
                    _row("Kontoauszug 03/2026", "Heute"),
                    _row("Kontoauszug 04/2026", "28.04.2026", link=""),
                    _row("Kontoauszug 05/2026", "28.05.2026", link="archivieren")])
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(site, "survey", lambda page: {"pages": [], "responses": []})
    monkeypatch.setitem(app.config, "include_unread", False)

    app.cmd_diagnose()

    out = " ".join(capsys.readouterr().out.split())
    assert page.looks == [False]
    assert "Rows collected: 1 " in out
    assert ("Left out: 1 without a readable date, 1 marked unread, 1 without a download "
            "link, 0 with several, 1 with one this app does not follow.") in out
    text = (app.paths.diagnostics / "diagnose-documents.json").read_text()
    report = json.loads(text)
    assert report["collected"] == 1 and "collect_error" not in report
    for said in (out, text):
        assert "/2026" not in said and "-rows-" not in said and "Kontoauszug" not in said


def test_diagnose_failure_is_reported_and_not_a_success(app, monkeypatch, capsys):
    monkeypatch.setattr(app, "page", lambda: object())
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)

    def broken(page):
        raise RuntimeError("survey unavailable")

    monkeypatch.setattr(site, "survey", broken)
    with pytest.raises(SystemExit) as stopped:
        app.cmd_diagnose()
    assert stopped.value.code == 1
    assert "survey failed" in capsys.readouterr().out.lower()
    report = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text())
    assert "error" in report


def test_diagnose_refuses_the_sign_in_page_without_surveying_it(app, monkeypatch):
    page = SimpleNamespace(url="https://apps.ing.de/dare/",
                           locator=lambda *_: SimpleNamespace(count=lambda: 0))
    monkeypatch.setattr(app, "page", lambda: page)
    monkeypatch.setattr(site, "survey", lambda *_: pytest.fail("sign-in must not be surveyed"))

    with pytest.raises(SystemExit) as stopped:
        app.cmd_diagnose()
    assert stopped.value.code == 1
    report = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text())
    assert report["signed_out"] is True and "survey" not in report


def test_the_owner_is_private_before_any_diagnostic_is_written(app):
    assert redact.redact("May Price") == "[name] [name]"


def test_open_browser_uses_the_official_ing_login_entry(app, monkeypatch):
    opened = {}

    def open_browser(profile, port, url, **kwargs):
        opened.update(profile=profile, port=port, url=url, **kwargs)
        return "browser"

    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser", open_browser)
    app.cmd_open_browser()

    assert opened["url"] == "https://banking.ing.de/app/obligo"
    assert opened["port"] == "9307"
    assert opened["prefer_real"] is True


def test_record_opts_in_to_html_navigation_metadata(app, monkeypatch):
    from paperpull_core import recorder

    called = {}
    monkeypatch.setattr(app, "page", lambda: object())

    def record(*args, **kwargs):
        called.update(kwargs)
        return "recording.json"

    monkeypatch.setattr(recorder, "record_session", record)
    app.cmd_record()
    assert called["include_html"] is True


def test_record_and_diagnose_choose_a_banking_tab_over_a_login_tab(monkeypatch):
    class Page:
        def __init__(self, url):
            self.url = url

        def is_closed(self):
            return False

        def locator(self, selector):
            return SimpleNamespace(count=lambda: 0)

    login = Page("https://apps.ing.de/dare/")
    old_banking = Page("https://banking.ing.de/app/old")
    current_banking = Page("https://banking.ing.de/app/current")
    app = object.__new__(docs.App)
    app._work_page = None
    app._cdp_mode = True
    app._requests = object()
    monkeypatch.setattr(app, "browser", lambda: SimpleNamespace(
        pages=[login, old_banking, current_banking]))

    assert app.page() is current_banking


def test_survey_reports_the_page_without_clicking_its_postbox_link(monkeypatch):
    class Page:
        url = "https://banking.ing.de/app/overview"

        def on(self, *args):
            pass

        def wait_for_timeout(self, ms):
            pass

        def remove_listener(self, *args):
            pass

        def get_by_role(self, *args, **kwargs):
            pytest.fail("diagnostics must not click a bank control")

    summary = {"controls": [{"role": "link", "text": "Postbox", "survey": True}]}
    monkeypatch.setattr(site, "_page_summary", lambda page: summary)
    report = site.survey(Page(), dwell_ms=0)
    assert report["pages"] == [summary]
    assert report["postbox_structure"] == {"inspected": False}


def test_postbox_census_rejects_another_host_without_inspecting_it():
    page = SimpleNamespace(url="https://banking.ing.de.attacker.invalid/app/postbox/postbox")
    with pytest.raises(site.SessionExpired):
        site.postbox_census(page)


def test_postbox_census_rejects_invalid_counts():
    result = dict(table_present=True, filter_present=True, truncated=False,
                  rows=1, rows_with_kind=1, rows_with_subject=1, rows_with_date=1,
                  rows_with_parseable_date=1, rows_with_download=2,
                  statement_candidates=0, tax_candidates=0, unread_rows=0,
                  pagination_controls=0)
    page = SimpleNamespace(url="https://banking.ing.de/app/postbox/postbox",
                           evaluate=lambda *_: result)
    with pytest.raises(RuntimeError, match="inconsistent"):
        site.postbox_census(page)


def test_postbox_census_rejects_mutually_inconsistent_categories():
    result = dict(table_present=True, filter_present=True, truncated=False,
                  rows=1, rows_with_kind=1, rows_with_subject=1, rows_with_date=1,
                  rows_with_parseable_date=1, rows_with_download=1,
                  statement_candidates=1, tax_candidates=1, unread_rows=0,
                  pagination_controls=0)
    page = SimpleNamespace(url="https://banking.ing.de/app/postbox/postbox",
                           evaluate=lambda *_: result)
    with pytest.raises(RuntimeError, match="inconsistent"):
        site.postbox_census(page)


def test_postbox_census_rejects_dates_without_a_date_field():
    result = dict(table_present=True, filter_present=True, truncated=False,
                  rows=1, rows_with_kind=1, rows_with_subject=1, rows_with_date=0,
                  rows_with_parseable_date=1, rows_with_download=1,
                  statement_candidates=0, tax_candidates=0, unread_rows=0,
                  pagination_controls=0)
    page = SimpleNamespace(url="https://banking.ing.de/app/postbox/postbox",
                           evaluate=lambda *_: result)
    with pytest.raises(RuntimeError, match="inconsistent"):
        site.postbox_census(page)


def test_postbox_census_does_not_export_unexpected_page_values():
    result = dict(table_present=True, filter_present=False, truncated=False,
                  rows=1, rows_with_kind=1, rows_with_subject=1, rows_with_date=1,
                  rows_with_parseable_date=1, rows_with_download=1,
                  statement_candidates=0, tax_candidates=0, unread_rows=1,
                  pagination_controls=0,
                  customer="May Price", href="private-account-id")
    page = SimpleNamespace(url="https://banking.ing.de/app/postbox/postbox_archiv",
                           evaluate=lambda *_: result)
    census = site.postbox_census(page)
    assert census["area"] == "archive"
    assert "customer" not in census and "href" not in census
    assert "May Price" not in str(census) and "private-account-id" not in str(census)
