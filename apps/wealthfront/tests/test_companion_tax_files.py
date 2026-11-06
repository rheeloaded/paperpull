"""The files of a tax form stay together (#142). A 1099 can come with a workbook
or a corrected copy beside its PDF. They are saved beside it, the record lists
them, and a Rename or a Move takes them along.

Everything here runs on the real app, its real progress file and index and the
real Rename, so a record has the key the app gives it. Only the browser is a
stand-in, and each file is known by its bytes, never its name. Every value is
invented.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from paperpull_core import doc_types, receipt_pdf, renaming, storage
from paperpull_core.models import State
import wealthfront_docs as app_mod

PATTERN = "{provider}/[ {account}]/[ {year}]/{date:yyyy-mm-dd}[ {kind}][ ({part})]"
ANOTHER = "{provider}/[ {year}]/{date:yyyy-mm-dd} Renamed[ {kind}][ ({part})]"
DATE = "2031-12-31"
PDF_START = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
DONE = "Every file is already named the way this app names them."


@pytest.fixture(autouse=True)
def reset_patterns():
    yield
    storage.set_filename_owner("")
    storage.set_filename_patterns({})


class Arrives:
    """page.expect_download with a download that came."""

    def __init__(self, download):
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_app(tmp_path, pattern=PATTERN, documents=False):
    out = tmp_path / "out"
    cfg = tmp_path / "config.json"
    settings = {"output_dir": str(out), "min_pdf_bytes": 10, "max_path_length": 240}
    if pattern:
        settings["filename_pattern_statements"] = pattern
    if documents:
        settings["documents_dir"] = str(tmp_path / "Watched")
    cfg.write_text(json.dumps(settings), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(cfg), "--yes"])
    app = app_mod.App(args)
    app.paths.ensure()
    app.stats = {"new_files": [], "tax_documents": 0, "statements": 0, "other": 0,
                 "duplicate_filenames": 0, "manual_review": 0, "failed": 0,
                 "validation_failures": 0, "dates": []}
    app._journal = MagicMock()
    app.progress.load()
    app.discovery.load()
    return app


def a_form(title="Consolidated Form 1099"):
    return app_mod.Document(title=title, category=doc_types.TAX,
                            summary="Consolidated 1099 Tax Form", date=DATE,
                            account="Investing", href="")


def stand_in(monkeypatch, app):
    def save(download, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(download.body)

    monkeypatch.setattr(receipt_pdf, "save_download", save)
    monkeypatch.setattr(receipt_pdf, "validate_pdf",
                        lambda path, min_bytes: SimpleNamespace(ok=True, size_bytes=100, page_count=1))
    monkeypatch.setattr(app_mod.site, "is_safe_url", lambda url: True)
    monkeypatch.setattr(app, "check_session", lambda page: None)


def download(app, monkeypatch, names, doc=None):
    """The app saves a form whose dialog lists `names`, and each file's bytes
    say which download it was."""
    doc = doc or a_form()
    stand_in(monkeypatch, app)
    bodies = [PDF_START + name.encode() for name in names]
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links",
                        lambda page, account, title: ["http://example.com/" + n for n in names])
    page = MagicMock()
    page.expect_download = MagicMock(side_effect=[
        Arrives(SimpleNamespace(suggested_filename=name, body=body))
        for name, body in zip(names, bodies)])
    page.locator().count.return_value = 1
    app.download_one(page, doc, storage.build_pdf_filename(doc.date, doc.summary, "", record=doc))
    return doc, bodies


def rename(app):
    said = []
    try:
        renaming.run_for(app, apply_changes=True, say=said.append)
        code = 0
    except SystemExit as stop:
        code = stop.code
    return code, "\n".join(said)


def files(top):
    """Each document on disk by its bytes, seen from `top`."""
    return {p.read_bytes(): p.relative_to(top).as_posix()
            for p in top.rglob("*") if p.is_file() and "Tax Documents" in p.parts}


def stored(app, doc):
    """The record as it is on disk."""
    return json.loads(app.paths.progress_json.read_text(encoding="utf-8"))[doc.key]


def bodies_listed(rec):
    return [Path(e["file"]).read_bytes() for e in rec["invoices"]]


def index_row(app):
    rows = app.index_csv.read_all()
    assert len(rows) == 1
    return rows[0]


# -- the download ---------------------------------------------------------------

def test_the_files_of_a_form_are_saved_together_and_listed(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "gain_loss.xls"])
    assert ":" in doc.key, "a record's key has colons, and a Rename reads them"
    folder = app.paths.tax_documents / "Wealthfront" / "Investing" / "2031"
    first = folder / "2031-12-31 Tax Document.pdf"
    second = folder / "2031-12-31 Tax Document (2 of 2).xls"
    assert first.read_bytes() == bodies[0] and second.read_bytes() == bodies[1]
    assert sorted(app.stats["new_files"]) == sorted([str(first), str(second)])
    rec = stored(app, doc)
    assert rec["pdf_path"] == str(first)
    assert rec["invoices"] == [{"file": str(first), "kept": True},
                               {"file": str(second), "kept": True}]
    assert rec["notes"] == "form set has 2 files"


def test_a_form_of_one_file_lists_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    doc, _bodies = download(app, monkeypatch, ["form.pdf"])
    rec = stored(app, doc)
    assert rec["invoices"] is None and rec["notes"] == ""


def test_a_name_taken_is_counted_once(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    download(app, monkeypatch, ["form.pdf"], a_form("First Form"))
    assert app.stats["duplicate_filenames"] == 0
    download(app, monkeypatch, ["corrected.pdf"], a_form("Second Form"))
    assert app.stats["duplicate_filenames"] == 1


def test_no_folder_is_made_when_the_dialog_gives_no_link(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    doc = a_form()
    stand_in(monkeypatch, app)
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links", lambda *a: [])
    monkeypatch.setattr(app_mod.site, "find_row_download", lambda *a: None)
    page = MagicMock()
    page.locator().count.return_value = 1
    app.download_one(page, doc, storage.build_pdf_filename(doc.date, doc.summary, "", record=doc))
    assert doc.state == State.NO_RECEIPT_AVAILABLE.value
    assert not (app.paths.tax_documents / "Wealthfront").exists()


def test_no_folder_is_made_when_no_download_arrives(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    doc = a_form()
    stand_in(monkeypatch, app)
    monkeypatch.setattr(app_mod.site, "resolve_tax_file_links",
                        lambda *a: ["http://example.com/form.pdf"])
    monkeypatch.setattr(app_mod.site, "find_row_download", lambda *a: object())
    page = MagicMock()
    page.expect_download = MagicMock(side_effect=TimeoutError("nothing came"))
    page.locator().count.return_value = 1
    app.download_one(page, doc, storage.build_pdf_filename(doc.date, doc.summary, "", record=doc))
    assert doc.state == State.FAILED.value
    assert not (app.paths.tax_documents / "Wealthfront").exists()


def test_a_folder_that_cannot_be_made_leaves_the_files_in_the_folder_of_their_kind(
        tmp_path, monkeypatch):
    """A folder is made through unique_path, as every app's is, which is also
    what holds one inside the data folder on PaperPull Server."""
    app = make_app(tmp_path)
    monkeypatch.setattr(storage, "_make_folder", lambda folder: False)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "gain_loss.xls"])
    folder = app.paths.tax_documents
    assert (folder / "2031-12-31 Tax Document.pdf").read_bytes() == bodies[0]
    assert (folder / "2031-12-31 Tax Document (2 of 2).xls").read_bytes() == bodies[1]
    assert doc.state == State.COMPLETED.value


# -- a Move and a Rename --------------------------------------------------------

@pytest.mark.parametrize("pattern", [PATTERN, ""], ids=["pattern", "no pattern"])
@pytest.mark.parametrize("names", [("form.pdf", "gain_loss.xls"),
                                   ("form.pdf", "corrected.pdf", "gain_loss.xlsx"),
                                   ("form.pdf", "lots.csv")],
                         ids=["xls", "pdf and xlsx", "csv"])
def test_a_move_takes_every_file_of_a_form(tmp_path, monkeypatch, names, pattern):
    app = make_app(tmp_path, pattern, documents=True)
    doc, bodies = download(app, monkeypatch, list(names))
    before = files(tmp_path)
    assert set(before) == set(bodies)
    assert all(path.startswith("out/") for path in before.values())

    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")
    code, said = rename(app)
    assert code == 0 and "Moved %d file(s)" % len(names) in said, said
    after = files(tmp_path)
    assert after == {body: "Watched/" + path[len("out/"):] for body, path in before.items()}

    rec = stored(app, doc)
    assert bodies_listed(rec) == bodies
    assert Path(rec["pdf_path"]).read_bytes() == bodies[0]
    row = index_row(app)
    assert Path(row["PDF Full Path"]).read_bytes() == bodies[0]
    assert row["PDF Filename"] == Path(row["PDF Full Path"]).name

    code, said = rename(app)
    assert code == 0 and "Moved" not in said, said
    assert files(tmp_path) == after


def test_a_rename_takes_every_file_of_a_form_and_keeps_each_ending(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "corrected.pdf", "gain_loss.xlsx"])
    storage.set_filename_patterns({"filename_pattern_statements": ANOTHER})
    code, said = rename(app)
    assert code == 0 and "Renamed 3 file(s)" in said, said
    folder = "out/Tax Documents/Wealthfront/2031/2031-12-31 Renamed Tax Document"
    after = {bodies[0]: folder + ".pdf",
             bodies[1]: folder + " (2 of 3).pdf",
             bodies[2]: folder + " (3 of 3).xlsx"}
    assert files(tmp_path) == after
    rec = stored(app, doc)
    assert bodies_listed(rec) == bodies
    assert Path(rec["pdf_path"]).read_bytes() == bodies[0]

    code, said = rename(app)
    assert code == 0 and DONE in said, said
    assert files(tmp_path) == after


def test_a_move_after_a_rename_takes_them_from_where_the_rename_left_them(tmp_path, monkeypatch):
    app = make_app(tmp_path, documents=True)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "gain_loss.xls"])
    storage.set_filename_patterns({"filename_pattern_statements": ANOTHER})
    code, said = rename(app)
    assert code == 0 and "Renamed 2 file(s)" in said, said
    renamed = files(tmp_path)

    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")
    code, said = rename(app)
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert files(tmp_path) == {body: "Watched/" + path[len("out/"):]
                               for body, path in renamed.items()}
    assert bodies_listed(stored(app, doc)) == bodies


def test_two_forms_of_one_name_each_keep_their_files_through_every_rename(tmp_path, monkeypatch):
    """The second form's name is taken, so its PDF has a " (2)" and its workbook
    does as well, once a Rename has written the part first. It goes on following
    its PDF."""
    app = make_app(tmp_path, pattern="")
    first, first_bodies = download(app, monkeypatch, ["form.pdf", "a.xls"], a_form("First Form"))
    second, second_bodies = download(app, monkeypatch, ["other.pdf", "b.xls"], a_form("Second Form"))
    assert files(tmp_path)[second_bodies[1]].endswith(" (2) (2 of 2).xls")

    rename(app)
    code, said = rename(app)
    assert code == 0 and DONE in said, said

    storage.set_filename_patterns({"filename_pattern_statements": ANOTHER})
    code, said = rename(app)
    assert code == 0 and "Renamed 4 file(s)" in said, said
    after = files(tmp_path)
    folder = "out/Tax Documents/Wealthfront/2031/"
    assert all(path.startswith(folder) for path in after.values()), after
    assert set(after) == set(first_bodies + second_bodies)
    assert bodies_listed(stored(app, first)) == first_bodies
    assert bodies_listed(stored(app, second)) == second_bodies
    code, said = rename(app)
    assert code == 0 and DONE in said, said
    assert files(tmp_path) == after


def test_a_pattern_with_no_part_keeps_the_files_together(tmp_path, monkeypatch):
    """Under such a pattern a name no longer says which file of the form it
    is. They still go together, told apart by their endings or a " (2)"."""
    plain = "{provider}/{date:yyyy-mm-dd}[ {kind}]"
    app = make_app(tmp_path)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "corrected.pdf", "gain_loss.xls"])
    storage.set_filename_patterns({"filename_pattern_statements": plain})
    code, said = rename(app)
    assert code == 0 and "Renamed 3 file(s)" in said, said
    code, said = rename(app)
    assert code == 0 and DONE in said, said

    storage.set_filename_patterns({"filename_pattern_statements": ANOTHER})
    code, said = rename(app)
    assert code == 0 and "Renamed 3 file(s)" in said, said
    after = files(tmp_path)
    assert set(after) == set(bodies)
    assert all(path.startswith("out/Tax Documents/Wealthfront/2031/") for path in after.values()), after
    assert after[bodies[2]].endswith(".xls")
    assert bodies_listed(stored(app, doc)) == bodies
    code, said = rename(app)
    assert code == 0 and DONE in said, said


def test_a_file_of_another_kind_stays_and_the_move_goes_on(tmp_path, monkeypatch):
    """A Rename holds only what an app can name. Such a file is kept where it
    was saved and the record goes on naming it there."""
    app = make_app(tmp_path, documents=True)
    doc, bodies = download(app, monkeypatch, ["form.pdf", "read_me.txt"])
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")
    code, said = rename(app)
    assert code == 0 and "Moved 1 file(s)" in said, said
    after = files(tmp_path)
    assert after[bodies[0]].startswith("Watched/") and after[bodies[1]].startswith("out/")
    assert bodies_listed(stored(app, doc)) == bodies
