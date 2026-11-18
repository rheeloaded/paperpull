"""A documents folder filed without kind folders holds only what the Move
filed there (follow-up of the 0.69.0 release review, #201).

With "kind_folders": false the documents folder itself is where documents
are filed, and it may be a broad one, a person's Documents say. Every file
anywhere in it counted as one the account holds, so a record naming some
other PDF there, one an imported history or a hand-edited index brought,
had Rename rename it, the Move move it and AT&T's wrong-year repair put it
in Manual Review. Now the Move writes down each document it files there,
by its size and SHA-256, before it moves anything, and only those are held
there, under any name a later Rename gives them. A folder of a kind inside
it holds its files as it always did.

Every folder is a throwaway one under tmp_path, and every name and account
is invented.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import renaming, storage  # noqa: E402
from paperpull_core.storage import Paths  # noqa: E402
from test_documents_folder import ACCOUNTS, BEFORE, FIRST, SECOND, Office, body_of, moving  # noqa: E402

FOREIGN = b"%PDF-1.4\n% a person's own invented file, never filed by PaperPull\n%%EOF\n"


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def flat(office):
    office.paths = Paths(office.out, documents_dir=str(office.docs), kind_folders=False)
    office.paths.ensure()


@pytest.fixture
def office(tmp_path):
    office = Office(tmp_path)
    for account in ACCOUNTS:
        office.saved(account)
    flat(office)
    assert office.where() == BEFORE
    return office


def foreign_file(office, imported=True) -> Path:
    """A PDF of the person's own in the broad documents folder, and a
    record and index row naming it, as an imported history could."""
    path = office.docs / "Taxes" / "2025 return.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FOREIGN)
    record = {"date": "2026-09-12", "title": "Monthly Statement", "summary": "Monthly Statement",
              "account": "Imported 9999", "category": "Statement", "pdf_path": str(path),
              "pdf_filename": path.name, "downloaded_ok": True, "state": "Completed"}
    if imported:
        record["imported_at"] = "2026-11-18T09:00:00"
    office.progress.update("Imported 9999", record)
    office.progress.save()
    office.index_csv.append_rows([{
        "Document Date": "2026-09-12", "Document Title": "Monthly Statement",
        "Document Summary": "Monthly Statement", "Account": "Imported 9999",
        "PDF Filename": path.name, "PDF Full Path": str(path),
        "Processing Status": "Completed", "Notes": ""}])
    return path


def moved(office, monkeypatch):
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)


# -- what is held ----------------------------------------------------------------------------

def test_a_file_the_move_never_filed_is_not_held_in_the_flat_documents_folder(
        office, monkeypatch):
    moved(office, monkeypatch)
    foreign = foreign_file(office)
    folders = office.paths.filing_folders()
    assert renaming.held_document(str(foreign), folders) is None
    assert renaming.held_row({"PDF Full Path": str(foreign),
                              "Processing Status": "Completed"}, folders) is None
    for name in (FIRST, SECOND):
        assert renaming.held_document(str(office.docs / name), folders) is not None


def test_rename_and_the_move_leave_a_file_they_never_filed_alone(office, monkeypatch):
    moved(office, monkeypatch)
    foreign = foreign_file(office)
    storage.set_filename_patterns({"filename_pattern": "{year}/{date} {account}"})
    code, said = office.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert foreign.read_bytes() == FOREIGN, "the person's file is where it was"
    assert office.where()[FOREIGN] == "Watched/Taxes/2025 return.pdf"
    moving(monkeypatch)
    office.rename()
    assert office.where()[FOREIGN] == "Watched/Taxes/2025 return.pdf"


def test_a_document_the_move_filed_is_still_held_after_rename_names_it_again(
        office, monkeypatch):
    moved(office, monkeypatch)
    for pattern in ("{year}/{date} {account}", "{date} {account} statement"):
        storage.set_filename_patterns({"filename_pattern": pattern})
        flat(office)
        code, said = office.rename()
        assert code == 0 and "Renamed 2 file(s)." in said, (pattern, said)
    assert office.where() == {body_of(a): "Watched/2026-09-12 %s statement.pdf" % a
                              for a in ACCOUNTS}
    office.follows()


def test_the_record_holds_only_sizes_and_digests(office, monkeypatch):
    moved(office, monkeypatch)
    written = json.loads((office.out / storage.FILED_FLAT).read_text(encoding="utf-8"))
    assert set(written) == {"files"}
    assert sorted(written["files"]) == sorted(
        [[len(body_of(a)), hashlib.sha256(body_of(a)).hexdigest()]
         for a in ACCOUNTS])
    for size, digest in written["files"]:
        assert isinstance(size, int) and re.fullmatch(r"[0-9a-f]{64}", digest)


def test_a_folder_of_a_kind_in_the_flat_folder_holds_its_files_as_before(office):
    """A document a Move with kind folders left there is held without any
    record, and the Move brings it out."""
    inside = office.docs / "Statements" / "left.pdf"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(FOREIGN)
    assert renaming.held_document(str(inside), office.paths.filing_folders()) is not None


def test_with_kind_folders_nothing_is_held_by_a_record(tmp_path):
    """The control. An account that never set kind_folders lists no flat
    folder, and holds what it always held."""
    paths = Paths(tmp_path / "out", documents_dir=str(tmp_path / "Watched"))
    folders = paths.filing_folders()
    assert not any(isinstance(f, storage.FlatRoot) for f in folders)
    kept = tmp_path / "Watched" / "Statements" / "a.pdf"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(FOREIGN)
    assert renaming.held_document(str(kept), folders) is not None
    loose = tmp_path / "Watched" / "b.pdf"
    loose.write_bytes(FOREIGN)
    assert renaming.held_document(str(loose), folders) is None
    assert not (tmp_path / "out" / storage.FILED_FLAT).exists()


def test_a_path_made_from_a_flat_folder_is_a_plain_path(tmp_path):
    root = storage.flat_root(tmp_path, lambda _p: True)
    assert root == tmp_path and hash(root) == hash(tmp_path)
    for made in (root / "x", root.resolve(), root.parent):
        assert type(made) is type(Path()), made


# -- written before anything moves ---------------------------------------------------------

def test_the_record_is_written_before_the_first_file_moves(office, monkeypatch):
    real = renaming.apply
    seen = {}

    def spy(changes, *a, **kw):
        record = office.out / storage.FILED_FLAT
        seen["written"] = json.loads(record.read_text(encoding="utf-8"))["files"]
        seen["where"] = office.where()
        return real(changes, *a, **kw)

    monkeypatch.setattr(renaming, "apply", spy)
    moved(office, monkeypatch)
    assert seen["where"] == BEFORE
    assert len(seen["written"]) == 2


def test_a_record_that_cannot_be_written_moves_nothing(office, monkeypatch):
    real = storage.atomic_write_text

    def refuse(path, text, encoding="utf-8", **how):
        if Path(path).name == storage.FILED_FLAT:
            raise PermissionError("locked")
        return real(path, text, encoding, **how)

    monkeypatch.setattr(storage, "atomic_write_text", refuse)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 1 and "Nothing was moved" in said, said
    assert office.where() == BEFORE


def test_a_record_that_cannot_be_read_holds_nothing_and_moves_nothing(office, monkeypatch):
    moved(office, monkeypatch)
    (office.out / storage.FILED_FLAT).write_text("{not json", encoding="utf-8")
    flat(office)
    assert renaming.held_document(str(office.docs / FIRST), office.paths.filing_folders()) is None
    office.saved("Brokerage 3333")
    flat(office)
    before = office.where()
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 1 and "Nothing was moved" in said and storage.FILED_FLAT in said, said
    assert office.where() == before


# -- documents 0.69.0 filed before the record existed ----------------------------------------

def test_documents_filed_before_the_record_are_found_from_the_accounts_own_records(
        office, monkeypatch):
    moved(office, monkeypatch)
    foreign = foreign_file(office, imported=True)
    record = office.out / storage.FILED_FLAT
    record.unlink()
    flat(office)
    folders = office.paths.filing_folders()
    for name in (FIRST, SECOND):
        assert renaming.held_document(str(office.docs / name), folders) is not None
    assert renaming.held_document(str(foreign), folders) is None, "an imported record's file"
    assert record.exists(), "written down once"
    assert len(json.loads(record.read_text(encoding="utf-8"))["files"]) == 2


def test_the_first_record_leaves_out_one_not_saved_and_checked(office, monkeypatch):
    moved(office, monkeypatch)
    foreign = foreign_file(office, imported=False)
    office.progress.data["Imported 9999"]["downloaded_ok"] = False
    office.progress.data["Imported 9999"]["state"] = "Needs Manual Review"
    office.progress.save()
    (office.out / storage.FILED_FLAT).unlink()
    flat(office)
    assert renaming.held_document(str(foreign), office.paths.filing_folders()) is None


def test_an_empty_record_is_not_written_again_from_the_records(office, monkeypatch):
    moved(office, monkeypatch)
    (office.out / storage.FILED_FLAT).write_text('{"files": []}', encoding="utf-8")
    flat(office)
    assert renaming.held_document(str(office.docs / FIRST), office.paths.filing_folders()) is None
    assert json.loads((office.out / storage.FILED_FLAT).read_text(encoding="utf-8")) == \
        {"files": []}
