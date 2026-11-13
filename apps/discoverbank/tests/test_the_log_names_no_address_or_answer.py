"""Discover Bank's log names no page address, no account id and nothing a
page or an answer said.

The log is written to a file in the output folder and shown on the panel,
where a tester can copy it into a public issue. It used to carry the
address the tab was on, the documents address, a statement's whole PDF
address with the account's id in it, an error's own text, which Playwright
writes with the address it was at, a statement's name from the list, and up
to 300 characters of what Discover answered when a PDF was refused.

Each case here hands the app an invented value, letters and digits, where
an address, an id or a page's words would be, and the log must not give it
back. A place is named by where it leads (urls.where_it_leads), an error by
its kind (failure.error_kind), and a name the page wrote by its shape
(words.shape_label). Nothing here is a real value.
"""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import discoverbank_docs as app_mod
import discoverbank_site as site

CANARY = "Zorvex4821Quillam"
PARTS = ("zorvex", "4821", "quillam")
BASE = "https://bank.discover.com"
ACCOUNT_ID = "4821~OC~77"
LIST_PATH = "/bank/deposits/servicing/documents/v1/accounts/%s/statements"
PDF = BASE + LIST_PATH % ACCOUNT_ID + "/s" + CANARY
# An address with an id in its path, the way an app's own route can name an
# account, on the statements page and off it.
ON_STATEMENTS = BASE + "/web/deposits/documents/statements/" + CANARY
OFF_STATEMENTS = BASE + "/web/accounts/" + CANARY
SIGNED_OUT = ("https://portal.discover.com/customersvcs/universalLogin/logoff_confirmed?id="
              + CANARY)


def clean(caplog) -> None:
    text = caplog.text.lower()
    assert caplog.records, "nothing was logged, so nothing was checked"
    for part in PARTS:
        assert part not in text, caplog.text
    assert "/accounts/" not in text, caplog.text


class Failing:
    """A tab whose every call fails with an error that names the address it
    was at and the page's words, the way Playwright's own errors do."""

    def __init__(self, url):
        self.url = url

    def on(self, *_a):
        """Listening is the one call that works, so a probe gets as far as
        the page."""

    def __getattr__(self, name):
        def fail(*_a, **_kw):
            raise RuntimeError("Page.%s: %s at %s" % (name, CANARY, self.url))
        return fail


class Lands:
    """A tab that opens any address it is given at `to`, an address with an
    id in it, and whose other calls answer nothing."""

    def __init__(self, url, to):
        self.url, self.to = url, to

    def goto(self, *_a, **_kw):
        self.url = self.to

    def wait_for_timeout(self, *_a):
        pass

    def wait_for_selector(self, *_a, **_kw):
        pass

    def __getattr__(self, name):
        def fail(*_a, **_kw):
            raise RuntimeError("no such element")
        return fail


class Answers:
    """A tab whose page answers every evaluate with `answer`."""

    def __init__(self, answer):
        self.url = BASE + "/web/deposits/documents/statements"
        self.answer = answer

    def evaluate(self, *_a):
        return self.answer


@pytest.fixture(autouse=True)
def _info(caplog):
    caplog.set_level(logging.INFO)


# -- the statements page -----------------------------------------------------------

@pytest.mark.parametrize("url", [OFF_STATEMENTS, SIGNED_OUT])
def test_an_address_that_would_not_open_is_named_by_where_it_leads(caplog, url):
    assert site.goto_documents(Failing(url)) is False
    clean(caplog)


def test_the_statements_page_reached_is_named_by_where_it_leads(caplog):
    assert site.goto_documents(Lands(OFF_STATEMENTS, ON_STATEMENTS)) is True
    clean(caplog)
    assert "bank.discover.com" in caplog.text


# -- the lists ----------------------------------------------------------------------

@pytest.mark.parametrize("read", [
    site.read_account_menu, site.discoverbank_collect, site.collect_documents,
    site.probe_statements_api, lambda page: site.probe_api(page, seconds=0),
    lambda page: site._read_list(page, BASE + LIST_PATH % ACCOUNT_ID),
], ids=["menu", "collect", "rows", "probe-statements", "probe-api", "one-list"])
def test_a_read_that_fails_says_its_kind_and_not_its_text(caplog, read):
    try:
        read(Failing(ON_STATEMENTS))
    except RuntimeError:
        pass
    clean(caplog)


def test_a_statement_refused_on_the_list_is_named_by_its_place(caplog):
    """A statement whose PDF sits under another account is refused, and the
    line that says so used to give the name the list gave it."""
    item = {"name": CANARY, "statementDate": "2031-01-28",
            "links": [{"rel": "binary", "href": BASE + LIST_PATH % "9~OC~9" + "/s1"}]}
    listed = site.parse_statements_api([item], "Checking (" + CANARY + ")", ACCOUNT_ID)
    assert list(listed) == [] and listed.passed_over == ("statement list",)
    clean(caplog)


def test_a_statement_whose_kinds_disagree_is_named_by_its_place(caplog):
    item = {"name": CANARY, "statementDate": "2031-01-28",
            "links": [{"rel": "binary", "href": PDF}]}
    listed = site.parse_statements_api([item], "Savings (" + CANARY + ")", ACCOUNT_ID)
    assert list(listed) == []
    clean(caplog)


# -- a statement's PDF -----------------------------------------------------------------

def test_a_refused_pdf_answer_leaves_its_words_and_its_address_out(caplog, tmp_path):
    """Discover answered the PDF's address with an error page. Up to 300
    characters of it, and the whole address with the account's id, went
    into the log."""
    page = Answers({"ok": False, "status": 403, "b64": "",
                    "text": "<html>%s %s</html>" % (CANARY, PDF)})
    out = tmp_path / "statement.pdf"
    assert site.discoverbank_download(page, None, "Checking (" + CANARY + ")", "2031-01-28",
                                      out, href=PDF) is False
    assert not out.exists()
    clean(caplog)
    assert "403" in caplog.text


@pytest.mark.parametrize("href", [BASE + "/web/accounts/" + CANARY + "/profile",
                                  "https://elsewhere.example/" + CANARY])
def test_an_address_that_is_no_statement_pdf_is_refused_by_where_it_leads(caplog, tmp_path,
                                                                          href):
    out = tmp_path / "statement.pdf"
    assert site.discoverbank_download(Answers({}), None, "Checking", "2031-01-28", out,
                                      href=href) is False
    assert not out.exists()
    clean(caplog)


def test_a_statement_with_no_address_is_named_by_its_kind(caplog, tmp_path):
    assert site.discoverbank_download(Answers({}), None, "Checking (" + CANARY + ")",
                                      "2031-01-28", tmp_path / "s.pdf") is False
    clean(caplog)


# -- a document that failed --------------------------------------------------------------

def test_a_document_that_failed_is_named_by_its_date_and_kind(caplog, tmp_path, monkeypatch):
    """The download loop logged the document's key, which is its PDF's
    address with the account's id, and the whole error with its traceback."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Test Person", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "document_types": ["Statement"], "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5}), encoding="utf-8")
    app = app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), "--yes"]))
    caplog.set_level(logging.INFO)

    def fails(*_a, **_kw):
        raise RuntimeError("%s at %s" % (CANARY, PDF))

    monkeypatch.setattr(app, "_on_its_site", lambda: None)
    monkeypatch.setattr(app, "download_one", fails)
    doc = app_mod.Document(title="Checking Statement", category="Statement",
                           summary="Checking Statement", date="2031-01-28", href=PDF,
                           account="Checking (" + CANARY + ")", document_id=PDF)
    app.process([doc])
    assert app.stats["failed"] == 1
    clean(caplog)
    assert "2031-01-28" in caplog.text
