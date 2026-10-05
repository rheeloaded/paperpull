"""A ZIP is a document only to an app that opens one.

Some providers hand a tax form over as a ZIP holding its PDF. The capture
takes one when the app says it can open it (zip_ok), and holds it to every
rule a PDF is held to. Nothing changes for a caller that does not ask,
which includes delivery, since delivery checks a document's identity from
its text and a ZIP has none.

The opening is receipt_pdf.open_zip. What it replaced ran in no app that
takes a browser download until now, and a review found what it would have
done there. It filed the first PDF of several under the document's name
before any check, left the others beside it unchecked, and destroyed the
archive's other files. So one PDF and nothing else is opened, anything
more is kept whole for a person, nothing is ever half written under a
document's name, and the only copy of what the provider handed over is
never lost.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import receipt_pdf  # noqa: E402
from paperpull_core.capture import (clear_copies, fetch_pdf, is_document,  # noqa: E402
                                    snapshot, take_download, take_new_pdf)

PDF = b"%PDF-1.4\nthe form\n%%EOF\n"
OTHER = b"%PDF-1.4\nsomething else entirely\n%%EOF\n"


def zipped(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


ZIP = zipped({"1099-R.pdf": PDF})


class Download:
    """A download event. `writes` is what save_as puts in the file, which is
    nothing at all once the browser has been pointed at a folder."""

    def __init__(self, name="TaxForms.zip", writes=b""):
        self.suggested_filename = name
        self.writes = writes

    def save_as(self, path):
        Path(path).write_bytes(self.writes)


def folder(tmp_path):
    dl = tmp_path / ".app-downloads"
    dl.mkdir()
    out = tmp_path / "Tax Documents" / "2026-01-31 Form 1099-R.pdf"
    return dl, out


# -- what counts as a document -------------------------------------------------

def test_a_zip_is_a_document_only_when_asked():
    assert is_document(PDF) and is_document(PDF, zip_ok=True)
    assert not is_document(ZIP)
    assert is_document(ZIP, zip_ok=True)
    for other in (b"", b"<html>signed out</html>", b"PK\x05\x06" + b"\0" * 18, b"PK"):
        assert not is_document(other, zip_ok=True), other


# -- take_download -----------------------------------------------------------------

def test_a_zip_is_left_in_the_folder_for_an_app_that_does_not_open_one(tmp_path):
    """Nothing changes for a caller that does not ask. The browser's file,
    the only copy, is not moved and not deleted."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    assert take_download(Download(), dl, before, out) == ""
    assert (dl / "TaxForms.zip").read_bytes() == ZIP
    assert not out.exists(), "the event's empty file was left under the document's name"


def test_a_zip_is_taken_from_the_folder_for_an_app_that_opens_one(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    assert take_download(Download(), dl, before, out, zip_ok=True) == "folder"
    assert out.read_bytes() == ZIP
    assert list(dl.iterdir()) == []


def test_a_zip_in_the_events_own_file_is_taken(tmp_path):
    """What a browser never pointed at a folder gives."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    assert take_download(Download(writes=ZIP), dl, before, out, zip_ok=True) == "event"
    assert out.read_bytes() == ZIP


def test_a_zip_in_the_events_own_file_is_not_left_for_an_app_that_does_not_open_one(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    assert take_download(Download(writes=ZIP), dl, before, out) == ""
    assert not out.exists()


def test_a_zip_and_a_different_pdf_are_two_documents(tmp_path):
    """The folder cannot say which one is this download, so neither is
    taken, the same as for two PDFs that differ."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    (dl / "Statement.pdf").write_bytes(OTHER)
    assert take_download(Download(), dl, before, out, zip_ok=True) == ""
    assert sorted(p.name for p in dl.iterdir()) == ["Statement.pdf", "TaxForms.zip"]
    assert not out.exists()


def test_two_copies_of_one_zip_are_one_document(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    (dl / "TaxForms (1).zip").write_bytes(ZIP)
    assert take_download(Download(), dl, before, out, zip_ok=True) == "folder"
    assert clear_copies(dl, before, out) == 1
    assert list(dl.iterdir()) == []


def test_a_zip_does_not_count_against_a_pdf_for_an_app_that_does_not_open_one(tmp_path):
    """Unchanged. To such an app a ZIP is nobody's document, like an error
    page."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(PDF)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    assert take_download(Download(name="Statement.pdf"), dl, before, out) == "folder"
    assert out.read_bytes() == PDF
    assert (dl / "TaxForms.zip").exists()


# -- take_new_pdf ----------------------------------------------------------------

def test_the_folder_gives_up_a_zip_only_when_asked(tmp_path):
    dl, out = folder(tmp_path)
    out.parent.mkdir()
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    assert take_new_pdf(dl, before, out) is False
    assert (dl / "TaxForms.zip").exists()
    assert take_new_pdf(dl, before, out, zip_ok=True) is True
    assert out.read_bytes() == ZIP and list(dl.iterdir()) == []


def test_the_folder_gives_up_nothing_when_a_zip_and_a_pdf_arrived(tmp_path):
    dl, out = folder(tmp_path)
    out.parent.mkdir()
    before = snapshot(dl)
    (dl / "TaxForms.zip").write_bytes(ZIP)
    (dl / "Statement.pdf").write_bytes(OTHER)
    assert take_new_pdf(dl, before, out, zip_ok=True) is False
    assert len(list(dl.iterdir())) == 2


def test_an_unfinished_zip_is_not_taken(tmp_path):
    dl, out = folder(tmp_path)
    out.parent.mkdir()
    before = snapshot(dl)
    (dl / "TaxForms.zip.crdownload").write_bytes(ZIP)
    assert take_new_pdf(dl, before, out, zip_ok=True) is False


# -- fetch_pdf -------------------------------------------------------------------

class _Answer:
    ok = True
    status = 200
    headers: dict = {}

    def __init__(self, body):
        self._body = body

    def body(self):
        return self._body


class _Page:
    def __init__(self, body):
        answer = _Answer(body)
        self.context = type("C", (), {"request": type("R", (), {
            "get": staticmethod(lambda href, timeout=0, max_redirects=20: answer)})()})()


def test_a_link_that_answers_with_a_zip_is_kept_only_when_asked():
    page = _Page(ZIP)
    assert fetch_pdf(page, "https://example.test/f", lambda u: True) is None
    assert fetch_pdf(page, "https://example.test/f", lambda u: True, zip_ok=True) == ZIP
    assert fetch_pdf(_Page(b"<html/>"), "https://example.test/f", lambda u: True,
                     zip_ok=True) is None


# -- opening one ---------------------------------------------------------------------

def leftovers(where: Path) -> list:
    return sorted(p.name for p in where.rglob("*") if p.name.startswith(".opening-"))


def review(tmp_path) -> Path:
    return tmp_path / "Manual Review"


def test_one_pdf_and_nothing_else_takes_the_archives_place(tmp_path):
    out = tmp_path / "Form.pdf"
    out.write_bytes(zipped({"1099R.pdf": PDF}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf == out and opened.kept is None and opened.reason == ""
    assert out.read_bytes() == PDF
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Form.pdf"]


@pytest.mark.parametrize("name,data", [
    ("1099R", PDF),                                   # no extension, found by its marker
    ("1099-R.pdf", b"\r\n" + PDF),                    # a line ending before the marker
    ("1099-R.pdf", b"\xef\xbb\xbf" + PDF),            # a byte order mark
    ("1099-R.pdf", b"%!PS print stream header\n" + PDF),
    ("1099-R.PDF", b"not starting like one at all"),  # the name says so, as before
], ids=["no extension", "line ending first", "byte order mark", "print stream", "name only"])
def test_a_pdf_is_known_by_its_name_or_its_marker(tmp_path, name, data):
    """The old extractor went by the name alone, and a first version of
    this one by the marker at the very first byte, which dropped a form
    with a line or a print stream in front, as TSP's 1099-R carries."""
    out = tmp_path / "Form.pdf"
    out.write_bytes(zipped({name: data}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf == out
    assert out.read_bytes() == data


def test_two_pdfs_are_kept_for_a_person_and_neither_is_filed(tmp_path):
    """Filing the first put a document under another's name before any
    check, and the second went beside it unchecked. On a retry a third
    appeared. None of that now."""
    out = tmp_path / "Form.pdf"
    archive = zipped({"a.pdf": PDF, "b.pdf": OTHER})
    out.write_bytes(archive)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None
    assert opened.kept == review(tmp_path) / "Form.zip"
    assert opened.kept.read_bytes() == archive
    assert opened.failure == "the archive held more than one pdf"
    assert "held 2 PDFs" in opened.reason and "Manual Review" in opened.reason
    assert [p.name for p in tmp_path.iterdir()] == ["Manual Review"]


def test_a_pdf_beside_other_files_is_kept_whole(tmp_path):
    """The other files were destroyed when the PDF took the archive's
    place, and the browser's copy of the archive was already gone."""
    out = tmp_path / "Form.pdf"
    archive = zipped({"1099.pdf": PDF, "1099.csv": b"a,b\n1,2\n"})
    out.write_bytes(archive)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None
    assert opened.kept.read_bytes() == archive
    assert opened.failure == "the archive held more than one file"
    assert "a PDF and 1 other file" in opened.reason


def test_folders_and_a_macs_extra_folder_are_not_files(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("forms/", b"")
        z.writestr("forms/1099-R.pdf", PDF)
        z.writestr("__MACOSX/forms/._1099-R.pdf", b"\x00\x05\x16\x07")
    out = tmp_path / "Form.pdf"
    out.write_bytes(buf.getvalue())
    assert receipt_pdf.open_zip(out, review(tmp_path)).pdf == out
    assert out.read_bytes() == PDF


def test_an_archive_with_no_pdf_is_kept_under_its_own_name(tmp_path):
    out = tmp_path / "Form.pdf"
    archive = zipped({"readme.txt": b"no pdfs here"})
    out.write_bytes(archive)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and opened.failure == "the archive held no pdf"
    assert not out.exists()
    assert (review(tmp_path) / "Form.zip").read_bytes() == archive


def test_the_same_files_again_are_kept_once(tmp_path):
    """A document marked for review is tried again on the next run. A ZIP
    built on request stamps its files with the time, so the second answer
    differs in its bytes and holds the same files."""
    kept = review(tmp_path)
    kept.mkdir()
    first = zipfile.ZipInfo("a.pdf", date_time=(2026, 1, 1, 0, 0, 0))
    second = zipfile.ZipInfo("a.pdf", date_time=(2026, 1, 2, 0, 0, 0))
    for info, where in ((first, kept / "Form.zip"), (second, tmp_path / "Form.pdf")):
        with zipfile.ZipFile(where, "w") as z:
            z.writestr(info, PDF)
            z.writestr("b.pdf", OTHER)
    assert (kept / "Form.zip").read_bytes() != (tmp_path / "Form.pdf").read_bytes()
    opened = receipt_pdf.open_zip(tmp_path / "Form.pdf", kept)
    assert opened.kept == kept / "Form.zip"
    assert sorted(p.name for p in kept.iterdir()) == ["Form.zip"]
    assert not (tmp_path / "Form.pdf").exists()


def test_different_files_are_kept_beside_the_first(tmp_path):
    kept = review(tmp_path)
    kept.mkdir()
    (kept / "Form.zip").write_bytes(zipped({"a.pdf": PDF, "b.pdf": OTHER}))
    out = tmp_path / "Form.pdf"
    second = zipped({"a.pdf": OTHER, "c.pdf": PDF})
    out.write_bytes(second)
    opened = receipt_pdf.open_zip(out, kept)
    assert opened.kept == kept / "Form (2).zip"
    assert opened.kept.read_bytes() == second


def test_an_archive_that_breaks_while_opening_is_kept_and_nothing_is_half_written(tmp_path,
                                                                                  monkeypatch):
    import shutil
    out = tmp_path / "Form.pdf"
    archive = zipped({"1099-R.pdf": PDF})
    out.write_bytes(archive)

    def full(src, dst, *a, **k):
        dst.write(b"%PDF-1.4\nhalf")
        raise OSError("the disk is full")

    monkeypatch.setattr(shutil, "copyfileobj", full)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and opened.failure == "the archive could not be opened"
    assert not out.exists(), "something was left under the document's name"
    assert opened.kept.read_bytes() == archive
    assert leftovers(tmp_path) == []


def test_a_pdf_that_cannot_be_put_in_place_keeps_the_archive(tmp_path, monkeypatch):
    import os
    out = tmp_path / "Form.pdf"
    archive = zipped({"1099-R.pdf": PDF})
    out.write_bytes(archive)
    real = os.replace

    def locked(src, dst):
        if Path(dst) == out:
            raise PermissionError("held open by a sync client")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", locked)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    monkeypatch.setattr(os, "replace", real)
    assert opened.pdf is None
    assert opened.kept.read_bytes() == archive
    assert leftovers(tmp_path) == []
    assert not list(tmp_path.glob("*.pdf"))


def test_a_file_that_is_not_a_zip_at_all_is_kept_as_it_came(tmp_path):
    """Nothing opens it, and it is the only copy, so it is kept."""
    out = tmp_path / "Form.pdf"
    out.write_bytes(b"PK\x03\x04 but broken")
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None
    assert opened.kept.read_bytes() == b"PK\x03\x04 but broken"


def test_without_a_folder_an_archive_is_kept_where_it_landed(tmp_path):
    """Wealthfront opens a companion file this way, and keeps a companion
    under the extension Wealthfront gave it."""
    pdf_named = tmp_path / "Form (2 of 3).pdf"
    pdf_named.write_bytes(zipped({"a.pdf": PDF, "b.csv": b"x"}))
    assert receipt_pdf.open_zip(pdf_named).kept == tmp_path / "Form (2 of 3).zip"
    docx = tmp_path / "Form (3 of 3).docx"
    data = zipped({"word/document.xml": b"<w:document/>"})
    docx.write_bytes(data)
    assert receipt_pdf.open_zip(docx).kept == docx
    assert docx.read_bytes() == data


@pytest.mark.parametrize("name", ["Form.pdf", "Form.PDF"])
def test_the_kept_name_is_the_documents_own(tmp_path, name):
    out = tmp_path / name
    out.write_bytes(zipped({"readme.txt": b"x"}))
    assert receipt_pdf.open_zip(out, review(tmp_path)).kept == review(tmp_path) / "Form.zip"
