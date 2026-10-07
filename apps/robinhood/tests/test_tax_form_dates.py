"""A tax form saved as 0000-00-00 gets a date, and its file takes it (#62).

The tester's first run saved a tax form named 0000-00-00, because its title
named no year and the title was all the date was read from. The page is
read for the year now. Three things follow from the form already on disk.

Rename names a file from its ledger row, and that row has no date, so a
date the record learned later never reached the file. The rename reads the
date the saved form was found to have, or the year it prints, into the row
it renames from, in a view, so a preview changes nothing.

The page's year gives the form a new key. Without a move the form would be
fetched a second time beside the saved one. It moves only by the year
the saved file itself prints, since when a form was listed or saved says
nothing about its year. A second copy is the worst an unsure case can cost,
never a form marked done that was not saved.

A form listed for one year that prints another goes to Manual Review and
neither year is done. A form already saved under its year is not kept a
second time when the page lists it without one. Rename dates a row only by
the year its own file prints.

A form the page gives no year at all is named for the year it prints when
it is saved, and keeps the undated key the page lists it by.

The PDFs here are made up, a line or two in the way a 1099 prints its
year, with invented years.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402  binds this provider's AppSpec
import robinhood_docs  # noqa: E402
import robinhood_site as site  # noqa: E402
from paperpull_core import doc_types  # noqa: E402
from paperpull_core import storage as core_storage  # noqa: E402
from paperpull_core.models import State  # noqa: E402

TITLE = "Consolidated Form 1099"
UNDATED = "0000-00-00 Robinhood Consolidated 1099 Tax Form.pdf"
FORM_2022 = ["Robinhood Securities LLC", "2022 1099-DIV Dividends and Distributions",
             "2022 1099-B Proceeds From Broker and Barter Exchange Transactions",
             "Date prepared 02/14/2023"]
FORM_2021 = ["Robinhood Securities LLC", "2021 1099-DIV", "Tax Year 2021"]
FORM_2004 = ["Robinhood Securities LLC", "2004 1099-DIV", "Tax Year 2004"]


def _text_pdf(path: Path, lines) -> None:
    """A one page PDF whose lines pypdf reads back."""
    stream = "".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (720 - 20 * i, line)
                     for i, line in enumerate(lines)).encode("latin-1")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out) + b" " * 4000)


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


class _Page:
    url = site.TAX_URL

    def goto(self, url, **kw):
        self.url = url

    def wait_for_timeout(self, ms):
        pass


def _app(tmp_path, apply=False):
    app = object.__new__(robinhood_docs.App)
    app.args = SimpleNamespace(apply=apply, redownload=False, start_date=None,
                               end_date=None, year=None, type=None, max_docs=None,
                               dry_run=False)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 1000, "owner": "",
                  "document_types": ["Statement", "Tax Document"],
                  "delay_min_seconds": 0, "delay_max_seconds": 0}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.document_index_csv,
                                    storage.DOCUMENT_INDEX_COLUMNS)
    app.rules = doc_types.load_rules()
    app.stats = {"mode": "", "discovered": 0, "manual_review": 0, "new_files": [],
                 "dates": [], "statements": 0, "tax_documents": 0,
                 "insurance_documents": 0, "other": 0, "validation_failures": 0,
                 "duplicate_filenames": 0, "failed": 0, "skipped_out_of_scope": 0,
                 "skipped_completed": 0}
    app._journal = SimpleNamespace(checkpoint=lambda *a, **k: None,
                                   op=lambda *a, **k: None)
    app.check_session = lambda page: False
    app.write_failure = lambda *a, **k: None
    page = _Page()
    app.page = lambda: page
    return app


def _saved_undated(app, lines=FORM_2022, listed_on="2026-09-29T10:00:00", keep_file=True):
    """The tester's state after 0.41.0. A form saved without a date, its
    record, its discovery entry and its ledger row."""
    doc = robinhood_docs.Document(title=TITLE, category=doc_types.TAX,
                                  summary="Consolidated 1099 Tax Form", date="",
                                  source_url=site.TAX_URL, discovered_at=listed_on)
    path = app.paths.folder_for(doc_types.TAX) / UNDATED
    if keep_file:
        _text_pdf(path, lines)
    doc.pdf_path, doc.pdf_filename = str(path), path.name
    doc.downloaded_ok = True
    doc.state = State.COMPLETED.value
    app.progress.update(doc.key, doc.to_dict())
    app.discovery.update(doc.key, doc.to_dict())
    app._write_row(doc, "Downloaded", "Completed")
    return doc, path


def _listing(*years):
    """What the tax page lists now, the same title under each year."""
    out = []
    for year in years:
        r = site.RawDoc(title=TITLE, date_text="%s-12-31" % year, text=TITLE)
        r.tax_year = year
        out.append(r)
    return out


def _discover(app, monkeypatch, listing):
    monkeypatch.setattr(site, "document_source_urls", lambda: [(site.TAX_URL, "tax")])
    monkeypatch.setattr(site, "collect_download_docs", lambda page, **kw: list(listing))
    monkeypatch.setattr(site, "expand_all", lambda page: None)
    monkeypatch.setattr(site, "scroll_full_page", lambda page, **kw: None)
    app.cmd_discover(quiet=True)


def _listed(year):
    return robinhood_docs.Document(title=TITLE, category=doc_types.TAX,
                                   summary="Consolidated 1099 Tax Form",
                                   date="%s-12-31" % year, tax_year=year)


def _names(app):
    return sorted(p.name for p in app.paths.folder_for(doc_types.TAX).glob("*.pdf"))


# -- the year a form prints ---------------------------------------------------

def test_the_year_a_tax_form_prints():
    from datetime import date
    today = date(2026, 9, 30)
    assert site.printed_tax_year("\n".join(FORM_2022), today) == "2022"
    assert site.printed_tax_year("\n".join(FORM_2021), today) == "2021"
    assert site.printed_tax_year("Form 1099-B 2022\nForm 1099-DIV 2022", today) == "2022"
    assert site.printed_tax_year("TAX YEAR: 2022", today) == "2022"
    # a revision date, an account number and an amount are not the tax year
    assert site.printed_tax_year("Form 1099-B (Rev. January 2024)\n2022 1099-B", today) == "2022"
    assert site.printed_tax_year("Account 20221099 Total $2022.50 1099", today) == ""
    # two years named as often as each other say nothing
    assert site.printed_tax_year("2022 1099-DIV\n2021 1099-B", today) == ""
    # a year still running is not a form's year
    assert site.printed_tax_year("2026 1099-DIV", today) == ""
    assert site.printed_tax_year("", today) == ""
    assert site.printed_tax_year("Monthly statement for January 2022", today) == ""


# -- Rename, with the form already on disk ------------------------------------

def test_rename_names_a_form_saved_undated_for_the_year_it_prints(tmp_path):
    app = _app(tmp_path, apply=True)
    doc, path = _saved_undated(app)
    app.cmd_rename()
    want = "2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf"
    assert _names(app) == [want]
    row = app.index_csv.read_all()[-1]
    assert row["Document Date"] == "2022-12-31"
    assert row["PDF Filename"] == want
    assert row["Period"] == "Tax Year 2022"
    rec = app.progress.get(doc.key)
    assert rec["pdf_filename"] == want and Path(rec["pdf_path"]).exists()
    # renaming touches no key, so the page's undated listing is still done
    assert app._already_done(robinhood_docs.Document.from_dict(doc.to_dict()))


def test_a_rename_preview_changes_nothing(tmp_path, capsys):
    app = _app(tmp_path, apply=False)
    doc, path = _saved_undated(app)
    app.cmd_rename()
    assert "2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf" in capsys.readouterr().out
    assert _names(app) == [UNDATED]
    assert app.index_csv.read_all()[-1]["Document Date"] == ""
    assert app.progress.get(doc.key)["pdf_filename"] == UNDATED


def test_a_form_that_prints_no_clear_year_keeps_its_name(tmp_path):
    app = _app(tmp_path, apply=True)
    _saved_undated(app, lines=["Robinhood Securities LLC", "2022 1099-DIV", "2021 1099-B"])
    app.cmd_rename()
    assert _names(app) == [UNDATED]
    assert app.index_csv.read_all()[-1]["Document Date"] == ""


# -- discovery, with the page's year -----------------------------------------

def test_the_form_the_page_now_dates_is_not_fetched_again(tmp_path, monkeypatch):
    """The saved file prints the year the page now lists it for, so it is
    that listed form."""
    app = _app(tmp_path, apply=True)
    doc, path = _saved_undated(app, lines=FORM_2022)
    _discover(app, monkeypatch, _listing("2022"))

    dated = _listed("2022")
    assert app._already_done(dated), "the saved form would be fetched a second time"
    rec = app.progress.get(dated.key)
    assert rec["downloaded_ok"] and rec["date"] == "2022-12-31"
    assert rec["undated_key"] == doc.key
    assert app.progress.get(doc.key) is None, "moved, not copied"
    assert app.discovery.get(doc.key) is None
    assert app.discovery.get(dated.key)["state"] == State.COMPLETED.value
    # a page that lists it without a year again is still listing that form
    assert app._already_done(robinhood_docs.Document.from_dict(doc.to_dict()))

    app.cmd_rename()
    assert _names(app) == ["2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]
    assert app.index_csv.read_all()[-1]["Document Date"] == "2022-12-31"


def test_the_year_the_file_prints_says_which_of_several_it_is(tmp_path, monkeypatch):
    app = _app(tmp_path)
    doc, path = _saved_undated(app, lines=FORM_2021)
    _discover(app, monkeypatch, _listing("2022", "2021"))
    assert app._already_done(_listed("2021"))
    assert not app._already_done(_listed("2022")), "2022 was never saved"
    assert app.progress.get(_listed("2021").key)["undated_key"] == doc.key


def test_an_unsure_case_moves_nothing(tmp_path, monkeypatch):
    """Two listed years and no file to read, or one listed year that had not
    ended when the saved form was listed. Either way nothing is marked done
    that was not saved. The saved record stays where it was."""
    app = _app(tmp_path)
    doc, _ = _saved_undated(app, keep_file=False)
    _discover(app, monkeypatch, _listing("2022", "2021"))
    assert not app._already_done(_listed("2022"))
    assert not app._already_done(_listed("2021"))
    assert app.progress.get(doc.key)["downloaded_ok"]

    app = _app(tmp_path / "second")
    doc, _ = _saved_undated(app, keep_file=False, listed_on="2025-11-01T10:00:00")
    _discover(app, monkeypatch, _listing("2025"))
    assert not app._already_done(_listed("2025")), "a 2025 form was not out in 2025"
    assert app.progress.get(doc.key)["downloaded_ok"]


def test_an_undated_listing_never_saved_is_not_fetched_under_no_date(tmp_path, monkeypatch):
    """A form whose download failed before is listed by its year now. The
    old undated listing would press the first control of the title, of
    whatever year, and save it as 0000-00-00."""
    app = _app(tmp_path)
    doc = robinhood_docs.Document(title=TITLE, category=doc_types.TAX,
                                  summary="Consolidated 1099 Tax Form", date="",
                                  source_url=site.TAX_URL)
    doc.state = State.NEEDS_MANUAL_REVIEW.value
    app.progress.update(doc.key, doc.to_dict())
    app.discovery.update(doc.key, doc.to_dict())
    _discover(app, monkeypatch, _listing("2022"))
    assert [d.key for d in app._select()] == [_listed("2022").key]


# -- a form the page gives no year ---------------------------------------------

def test_a_form_saved_without_a_year_is_named_for_the_year_it_prints(tmp_path, monkeypatch):
    app = _app(tmp_path)
    pressed = []

    def fake_download(page, title, out_path, year=""):
        pressed.append(year)
        _text_pdf(Path(out_path), FORM_2022)
        return True
    monkeypatch.setattr(site, "download_named", fake_download)
    doc = robinhood_docs.Document(title=TITLE, category=doc_types.TAX,
                                  summary="Consolidated 1099 Tax Form", date="",
                                  source_url=site.TAX_URL)
    key = doc.key
    app.download_one(_Page(), doc, storage.build_pdf_filename("", doc.summary, ""))

    want = "2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf"
    assert _names(app) == [want]
    rec = app.progress.get(key)
    assert rec["state"] == State.COMPLETED.value
    assert rec["date"] == "", "the key the page lists it by must not move"
    assert rec["printed_date"] == "2022-12-31"
    assert rec["pdf_filename"] == want
    row = app.index_csv.read_all()[-1]
    assert row["Document Date"] == "2022-12-31" and row["PDF Filename"] == want
    assert pressed == [""]
    # the next run lists it the same way and knows it is done, and a rename
    # finds it already named
    assert app._already_done(robinhood_docs.Document(
        title=TITLE, category=doc_types.TAX, summary="Consolidated 1099 Tax Form", date=""))
    app.args.apply = True
    app.cmd_rename()
    assert _names(app) == [want]


def test_a_dated_form_is_pressed_for_its_own_year(tmp_path, monkeypatch):
    app = _app(tmp_path)
    pressed = []

    def fake_download(page, title, out_path, year=""):
        pressed.append(year)
        _text_pdf(Path(out_path), FORM_2021)
        return True
    monkeypatch.setattr(site, "download_named", fake_download)
    doc = _listed("2021")
    app.download_one(_Page(), doc, storage.build_pdf_filename(doc.date, doc.summary, ""))
    assert pressed == ["2021"]
    assert _names(app) == ["2021-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]


def test_a_saved_form_whose_file_prints_no_year_is_not_moved(tmp_path, monkeypatch):
    """When it was listed says nothing about which year's form it is, since
    a form comes out in the year after its own. Nothing is marked done that
    was not saved, and the saved record stays where it was."""
    app = _app(tmp_path)
    doc, _ = _saved_undated(app, lines=["Robinhood Securities LLC"])
    _discover(app, monkeypatch, _listing("2022"))
    assert not app._already_done(_listed("2022"))
    assert app.progress.get(doc.key)["downloaded_ok"]


# -- what the saved form prints, against what it was listed as ----------------

def _fake_download(monkeypatch, lines):
    def fake(page, title, out_path, year=""):
        _text_pdf(Path(out_path), lines)
        return True
    monkeypatch.setattr(site, "download_named", fake)


def _everything(app):
    return sorted(p.name for p in app.paths.root.rglob("*") if p.is_file()
                  and p.suffix != ".json" and not p.name.endswith(".csv"))


def test_a_form_listed_for_one_year_that_prints_another_goes_to_manual_review(tmp_path, monkeypatch):
    app = _app(tmp_path)
    _fake_download(monkeypatch, FORM_2022)
    doc = _listed("2021")
    app.download_one(_Page(), doc, storage.build_pdf_filename(doc.date, doc.summary, ""))
    assert _names(app) == []
    assert [p.name for p in app.paths.manual_review.glob("*.pdf")] == [
        "2021-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]
    rec = app.progress.get(doc.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and rec["pdf_path"] == ""
    assert not app._already_done(doc), "the copy in Manual Review must not count as done"
    assert not app._already_done(_listed("2022"))
    assert app.stats["wrong_document"] == 1


def test_a_form_saved_under_its_year_is_not_kept_again_from_an_undated_listing(tmp_path, monkeypatch):
    app = _app(tmp_path)
    saved = _listed("2022")
    path = app.paths.folder_for(doc_types.TAX) / "2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf"
    _text_pdf(path, FORM_2022)
    saved.pdf_path, saved.pdf_filename = str(path), path.name
    saved.downloaded_ok, saved.state = True, State.COMPLETED.value
    app.progress.update(saved.key, saved.to_dict())

    _fake_download(monkeypatch, FORM_2022)
    undated = robinhood_docs.Document(title=TITLE, category=doc_types.TAX,
                                      summary="Consolidated 1099 Tax Form", date="",
                                      source_url=site.TAX_URL)
    app.download_one(_Page(), undated, storage.build_pdf_filename("", undated.summary, ""))
    assert _everything(app) == [path.name], "a second copy was kept"
    assert app._already_done(undated), "the undated listing is that saved form"


def test_rename_dates_each_row_only_by_its_own_file(tmp_path):
    """A form moved to 2022 by the year its file prints, and a second row of
    the same title whose file prints none. Only the first takes 2022."""
    app = _app(tmp_path, apply=True)
    doc, path = _saved_undated(app, lines=FORM_2022)
    moved = dict(app.progress.get(doc.key), date="2022-12-31", undated_key=doc.key)
    del app.progress.data[doc.key]
    app.progress.update(_listed("2022").key, moved)
    other = app.paths.folder_for(doc_types.TAX) / "0000-00-00 Robinhood Consolidated 1099 Tax Form b.pdf"
    _text_pdf(other, ["Robinhood Securities LLC"])
    app.index_csv.append_rows([{"Category": doc_types.TAX, "Document Date": "",
                                "Document Title": TITLE,
                                "Document Summary": "Consolidated 1099 Tax Form",
                                "PDF Filename": other.name, "PDF Full Path": str(other)}])
    app.cmd_rename()
    assert sorted(r["Document Date"] for r in app.index_csv.read_all()) == ["", "2022-12-31"]
    assert [n for n in _names(app) if n.startswith("2022")] == [
        "2022-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]


def test_a_form_left_under_the_name_it_was_delivered_to_is_finished_by_rename(tmp_path,
                                                                             monkeypatch):
    """Moving a form into place failed, a scanner holding it open for
    instance, so it was recorded under the name it was written to beside
    its place, for Rename to finish. Rename puts it in place."""
    app = _app(tmp_path)
    _fake_download(monkeypatch, FORM_2004)
    real_replace = Path.replace

    def held_open(self, target):
        if self.name.endswith(".delivering"):
            raise PermissionError(32, "The file is being used by another process")
        return real_replace(self, target)
    monkeypatch.setattr(Path, "replace", held_open)
    doc = _listed("2004")
    app.download_one(_Page(), doc, storage.build_pdf_filename(doc.date, doc.summary, ""))
    monkeypatch.setattr(Path, "replace", real_replace)
    staged = "2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf.delivering"
    assert _everything(app) == [staged]
    assert app.index_csv.read_all()[0]["PDF Filename"] == staged

    app.args.apply = True
    app.cmd_rename()
    assert _everything(app) == ["2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]
    row = app.index_csv.read_all()[0]
    assert row["PDF Filename"] == "2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf"
    assert app.progress.get(doc.key)["pdf_path"] == row["PDF Full Path"]


def test_a_form_that_failed_its_check_is_left_for_the_next_run(tmp_path, monkeypatch):
    """A form that fails its check goes to Manual Review, and when that move
    fails too it stays under the name it was written to beside its place,
    marked for review. Rename leaves it so, and the next run fetches the
    form again and gives it the form's own name, where Rename used to give
    that name to what failed and the form came beside it under another."""
    app = _app(tmp_path)

    def expired(page, title, out_path, year=""):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"%PDF-1.4\n<html>Session expired</html>\n%%EOF\n")
        return True
    monkeypatch.setattr(site, "download_named", expired)
    real_replace = Path.replace

    def held_open(self, target):
        if self.name.endswith(".delivering"):
            raise PermissionError(32, "The file is being used by another process")
        return real_replace(self, target)
    monkeypatch.setattr(Path, "replace", held_open)
    doc = _listed("2004")
    name = storage.build_pdf_filename(doc.date, doc.summary, "")
    app.download_one(_Page(), doc, name)
    monkeypatch.setattr(Path, "replace", real_replace)
    staged = "2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf.delivering"
    assert _everything(app) == [staged]
    assert app.progress.get(doc.key)["state"] == State.NEEDS_MANUAL_REVIEW.value

    app.args.apply = True
    app.cmd_rename()
    assert _everything(app) == [staged]

    _fake_download(monkeypatch, FORM_2004)
    app.download_one(_Page(), _listed("2004"), name)
    assert _everything(app) == ["2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]


def test_rename_leaves_alone_the_date_of_a_row_it_does_not_hold(tmp_path):
    """An index copied from another folder can name a form there, which is
    not this app's to read. The form the app holds is dated and renamed,
    and the other row keeps no date, as it had."""
    app = _app(tmp_path / "out", apply=True)
    _saved_undated(app, lines=FORM_2004)
    outside = tmp_path / "elsewhere" / "Another 1099.pdf"
    _text_pdf(outside, FORM_2004)
    copied = {"Category": doc_types.TAX, "Document Date": "", "Period": "",
              "Document Title": "Another Form", "Document Summary": "Another Form",
              "PDF Filename": outside.name, "PDF Full Path": str(outside)}
    app.index_csv.append_rows([copied])
    app.cmd_rename()
    assert _names(app) == ["2004-12-31 Robinhood Consolidated 1099 Tax Form.pdf"]
    assert {k: app.index_csv.read_all()[1][k] for k in copied} == copied
    assert outside.is_file()
