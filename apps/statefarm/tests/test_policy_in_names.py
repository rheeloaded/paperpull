"""The policy a document belongs to, in its file name (#37).

The tester's Pilot saved two renewal notices, one for his auto policy and
one for his home, and both came out as "State Farm Renewal Notice". The
title says which, "Renewal Notice - Auto" and "Renewal Notice -
Homeowners", and the file name now does too. A file saved under the old
name is renamed rather than downloaded again. Every title, date and
address here is invented."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import storage  # noqa: F401  binds the AppSpec
from paperpull_core import doc_types, renaming
from paperpull_core.models import State
import statefarm_docs
import statefarm_site as site

RULES = doc_types.load_rules()


class _Store:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def update(self, key, value, save=True):
        self.data.setdefault(key, {}).update(value)

    def save(self, backup=False):
        pass


class _Ledger:
    """The index CSV, in memory, with the columns State Farm writes."""

    columns = storage.DOCUMENT_INDEX_COLUMNS

    def __init__(self, rows):
        self.rows = rows

    def read_all(self):
        return [dict(r) for r in self.rows]

    def rewrite(self, rows):
        self.rows = [dict(r) for r in rows]


def _bare_app(discovery=None):
    app = statefarm_docs.App.__new__(statefarm_docs.App)
    app.args = types.SimpleNamespace(start_date=None)
    app.config = {"max_path_length": 240}
    app.rules = RULES
    app.stats = {"skipped_out_of_scope": 0}
    app.discovery = _Store(discovery)
    app.progress = _Store()
    return app


@pytest.mark.parametrize("title, detail", [
    ("Renewal Notice - Auto", "Auto"),
    ("Renewal Notice - Homeowners", "Homeowners"),
    ("Declarations Page - Homeowners", "Homeowners"),
    ("Renewal Notice - 2017 Invented Roadster", "2017 Invented Roadster"),
    ("Renewal Notice -  Auto  ", "Auto"),
    ("Payment Receipt - Payment Receipt", ""),
    ("Renewal Notice - ", ""),
    ("Renewal Notice", ""),
    ("1099-INT - 2025", ""),
    ("", ""),
])
def test_the_part_after_the_dash_is_what_the_document_is_for(title, detail):
    assert site.title_detail(title) == detail


def _record(app, title, date="2026-07-22"):
    raw = site.RawDoc(title=title, date_text=date,
                      href="/DocumentCenterProxyV1/document/invented-%s" % date, kind="statement")
    app._record_rawdoc(raw, site.BILLING_URL)
    return [r for r in app.discovery.data.values() if r["title"] == title][0]


def test_each_policy_names_its_own_renewal_notice():
    app = _bare_app()
    auto = _record(app, "Renewal Notice - Auto", "2026-07-22")
    home = _record(app, "Renewal Notice - Homeowners", "2026-04-16")
    assert auto["summary"] == "Renewal Notice Auto"
    assert home["summary"] == "Renewal Notice Homeowners"
    assert storage.build_pdf_filename(auto["date"], auto["summary"], "", record=auto) == \
        "2026-07-22 State Farm Renewal Notice Auto.pdf"
    assert storage.build_pdf_filename(home["date"], home["summary"], "", record=home) == \
        "2026-04-16 State Farm Renewal Notice Homeowners.pdf"


def test_a_title_with_nothing_more_to_say_keeps_its_name():
    app = _bare_app()
    assert _record(app, "Payment Receipt - Payment Receipt")["summary"] == "Receipt"
    assert _record(app, "Monthly Statement", "2026-06-02")["summary"] == "Monthly Statement"


def test_a_tax_form_is_named_for_its_form_alone():
    assert statefarm_docs.with_title_detail("1099-INT Tax Form", "1099-INT - Invented Bank",
                                            doc_types.TAX) == "1099-INT Tax Form"


def test_a_file_saved_under_the_old_name_is_renamed_not_downloaded_again(tmp_path):
    """What he has now, five files the Pilot saved as "State Farm Renewal
    Notice". The next Discover finds the same document under the same key,
    since the key is its title, gives it its new name, and Rename moves the
    file to it. Nothing is downloaded."""
    old = statefarm_docs.Document(title="Renewal Notice - Auto", category=doc_types.STATEMENT,
                                  summary="Renewal Notice", date="2026-07-22")
    folder = tmp_path / "Statements"
    folder.mkdir()
    saved = folder / "2026-07-22 State Farm Renewal Notice.pdf"
    saved.write_bytes(b"%PDF-1.7 an invented renewal notice")
    rec = old.to_dict()
    rec.update(state=State.COMPLETED.value, downloaded_ok=True, pdf_filename=saved.name,
               pdf_path=str(saved))
    app = _bare_app({old.key: rec})

    assert _record(app, "Renewal Notice - Auto", "2026-07-22") is app.discovery.data[old.key]
    assert list(app.discovery.data) == [old.key], "the same document, not a second one"
    now = app.discovery.data[old.key]
    assert now["summary"] == "Renewal Notice Auto"
    assert now["downloaded_ok"] is True and now["state"] == State.COMPLETED.value

    app.index_csv = _Ledger([{
        "Document Date": "2026-07-22", "Category": doc_types.STATEMENT,
        "Document Summary": "Renewal Notice", "Document Title": "Renewal Notice - Auto",
        "PDF Filename": saved.name, "PDF Full Path": str(saved), "Notes": ""}])
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)

    renamed = folder / "2026-07-22 State Farm Renewal Notice Auto.pdf"
    assert renamed.exists() and not saved.exists()
    assert app.index_csv.rows[0]["PDF Filename"] == renamed.name
