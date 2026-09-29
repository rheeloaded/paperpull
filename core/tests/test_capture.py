"""Taking a PDF the browser downloaded."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.capture import snapshot, take_new_pdf  # noqa: E402

PDF = b"%PDF-1.4\nbody\n%%EOF\n"


def test_a_pdf_that_appeared_is_taken(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    before = snapshot(dl)
    (dl / "statement.pdf").write_bytes(PDF)
    assert take_new_pdf(dl, before, out) is True
    assert out.read_bytes() == PDF
    assert not (dl / "statement.pdf").exists(), "it is moved, not copied"


def test_a_file_that_was_already_there_is_not_taken(tmp_path):
    """The whole point of the snapshot. Yesterday's download is not this
    click's answer."""
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    (dl / "old.pdf").write_bytes(PDF)
    before = snapshot(dl)
    assert take_new_pdf(dl, before, out) is False
    assert (dl / "old.pdf").exists()


def test_a_download_still_in_flight_is_not_taken(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    before = snapshot(dl)
    for name in ("a.pdf.crdownload", "b.partial", "c.part", "d.tmp", "e.download"):
        (dl / name).write_bytes(PDF)
    assert take_new_pdf(dl, before, out) is False


def test_something_that_is_not_a_pdf_is_not_taken(tmp_path):
    """An expired link answers with an HTML error page, which is still a
    file appearing in the folder."""
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    before = snapshot(dl)
    (dl / "oops.pdf").write_bytes(b"<html>Session expired</html>")
    assert take_new_pdf(dl, before, out) is False


def test_an_empty_file_is_not_taken(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    before = snapshot(dl)
    (dl / "empty.pdf").write_bytes(b"")
    assert take_new_pdf(dl, before, out) is False


def test_it_replaces_whatever_was_at_the_destination(tmp_path):
    dl, out = tmp_path / "dl", tmp_path / "out.pdf"
    dl.mkdir()
    out.write_bytes(b"stale")
    before = snapshot(dl)
    (dl / "new.pdf").write_bytes(PDF)
    assert take_new_pdf(dl, before, out) is True
    assert out.read_bytes() == PDF


def test_no_download_folder_is_not_an_error(tmp_path):
    assert take_new_pdf(None, set(), tmp_path / "out.pdf") is False
    assert take_new_pdf(tmp_path / "missing", set(), tmp_path / "out.pdf") is False
    assert snapshot(None) == set()
    assert snapshot(tmp_path / "missing") == set()


# -- a caller that reads a key off the answer (#43) --------------------------

def test_the_two_fetches_answer_with_different_shapes_on_purpose():
    """Each app used to carry its own copy of this, answering with a
    dictionary. The shared one answers with base64 alone, and two apps
    kept reading .get("b64") off it. A tester's full run died on the
    thirteenth receipt with AttributeError."""
    from paperpull_core import capture
    assert "return btoa(s)" in capture.FETCH_AS_B64
    assert "out.b64 = btoa(s)" in capture.FETCH_WITH_STATUS
    assert "status: r.status" in capture.FETCH_WITH_STATUS


def test_no_app_reads_a_key_off_the_one_that_returns_a_string():
    import re
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    offenders = []
    for site in sorted(repo.glob("apps/*/*_site.py")):
        text = site.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(\w+)\s*=\s*_?fetch_as_b64\([^\n]*\)", text):
            after = text[m.end():m.end() + 400]
            if re.search(r"\b%s\s*\.\s*get\s*\(" % re.escape(m.group(1)), after):
                offenders.append(site.parent.name)
    assert not offenders, ("reads a key off base64, which is a string: "
                           + ", ".join(sorted(set(offenders))))


# -- a browser pointed at a folder (measured 2026-09-29) ---------------------
#
# Once set_download_dir has pointed the browser at a folder, the browser's
# file there is the only copy of a download, and the event's save_as writes
# an empty file. A finished file of the same name is written over in place.
# test_every_app_leaves_no_copy.py holds all of that in a real browser.
# These hold the rules for which file in the folder is whose.

import os  # noqa: E402

from paperpull_core.capture import (arrived, clear_archived_copies,  # noqa: E402
                                    clear_copies, take_download)

OTHER = b"%PDF-1.4\nsomething else entirely\n%%EOF\n"


def rewrite(path, data):
    """Write `data` over `path` and make sure the change shows, as a browser
    finishing a download a moment later would."""
    path.write_bytes(data)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


class Download:
    """A download event. `writes` is what save_as puts in the file, which is
    nothing at all once the browser has been pointed at a folder."""

    def __init__(self, name="Statement.pdf", writes=b"", raises=False):
        self.suggested_filename = name
        self.writes, self.raises, self.saved_to = writes, raises, None

    def save_as(self, path):
        if self.raises:
            raise RuntimeError("the download failed")
        self.saved_to = Path(path)
        Path(path).write_bytes(self.writes)


def folder(tmp_path):
    dl = tmp_path / ".app-downloads"
    dl.mkdir()
    return dl, tmp_path / "Statements" / "2026-08-31 Statement.pdf"


def test_a_file_written_again_in_place_is_taken(tmp_path):
    """The browser writes a finished file of the same name over the old one.
    Compared by name, that download never arrived, and AT&T failed every
    bill after one was left in its folder under the usual name."""
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(OTHER)
    before = snapshot(dl)
    rewrite(dl / "Statement.pdf", PDF)
    out.parent.mkdir()
    assert take_new_pdf(dl, before, out) is True
    assert out.read_bytes() == PDF


def test_a_plain_set_of_names_still_means_new_names_only(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(OTHER)
    before = set(os.listdir(dl))
    rewrite(dl / "Statement.pdf", PDF)
    assert arrived(dl, before) == []
    (dl / "new.pdf").write_bytes(PDF)
    assert arrived(dl, before) == ["new.pdf"]


def test_the_snapshot_is_still_a_set_of_names(tmp_path):
    """Newrez and the delivery module subtract one from another."""
    dl, _ = folder(tmp_path)
    (dl / "a.pdf").write_bytes(PDF)
    before = snapshot(dl)
    assert before == {"a.pdf"} and isinstance(before, set)
    (dl / "b.pdf").write_bytes(PDF)
    assert set(os.listdir(dl)) - before == {"b.pdf"}


def test_nothing_is_taken_once_an_earlier_download_has_finished_since(tmp_path):
    """A download an earlier capture gave up on can finish as the very file
    that looks new, and saving it under this document's name is the wrong
    document (#38)."""
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf.crdownload").write_bytes(b"%PDF-1.4\npart")
    before = snapshot(dl)
    (dl / "Statement.pdf.crdownload").rename(dl / "Statement.pdf")
    out.parent.mkdir()
    assert take_new_pdf(dl, before, out) is False
    assert (dl / "Statement.pdf").exists()


def test_a_download_abandoned_long_ago_stops_nothing(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "Unconfirmed 1234.crdownload").write_bytes(b"x")
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(PDF)
    out.parent.mkdir()
    assert take_new_pdf(dl, before, out) is True


# take_download

def test_the_browsers_file_is_taken_when_the_events_is_empty(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(PDF)
    assert take_download(Download(), dl, before, out) == "folder"
    assert out.read_bytes() == PDF
    assert list(dl.iterdir()) == [], "moved, so no copy is left behind"


def test_the_events_file_is_used_when_it_holds_the_pdf(tmp_path):
    """A browser never pointed at a folder."""
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(OTHER)
    before = snapshot(dl)
    assert take_download(Download(writes=PDF), dl, before, out) == "event"
    assert out.read_bytes() == PDF
    assert (dl / "Statement.pdf").read_bytes() == OTHER, "the folder is not touched"


def test_the_browsers_numbered_name_is_taken(tmp_path):
    """Written when a download of the same name is still arriving."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement (1).pdf").write_bytes(PDF)
    assert take_download(Download(), dl, before, out) == "folder"
    assert out.read_bytes() == PDF


def test_a_file_written_over_in_place_is_taken(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(OTHER)
    before = snapshot(dl)
    rewrite(dl / "Statement.pdf", PDF)
    assert take_download(Download(), dl, before, out) == "folder"
    assert out.read_bytes() == PDF


def test_a_file_under_another_name_is_never_taken_as_this_download(tmp_path):
    """The browser saves whatever else is downloaded in it into the same
    folder, from any tab."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "somebody else's.pdf").write_bytes(OTHER)
    assert take_download(Download(), dl, before, out) == ""
    assert (dl / "somebody else's.pdf").exists()
    assert not out.exists(), "and no empty file is left under the document's name"


def test_two_files_that_could_be_this_download_mean_neither(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(OTHER)
    before = snapshot(dl)
    rewrite(dl / "Statement.pdf", PDF)
    (dl / "Statement (1).pdf").write_bytes(PDF)
    assert take_download(Download(), dl, before, out) == ""
    assert sorted(p.name for p in dl.iterdir()) == ["Statement (1).pdf", "Statement.pdf"]


def test_the_events_name_is_not_enough_once_an_earlier_download_finished(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "Statement.pdf.crdownload").write_bytes(b"%PDF-1.4\npart")
    before = snapshot(dl)
    (dl / "Statement.pdf.crdownload").rename(dl / "Statement.pdf")
    assert take_download(Download(), dl, before, out) == ""
    assert (dl / "Statement.pdf").exists()


def test_a_named_file_that_is_not_a_pdf_is_not_taken(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(b"<html>Your session has expired</html>")
    assert take_download(Download(), dl, before, out) == ""


def test_an_event_that_fails_to_save_still_finds_the_browsers_file(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(PDF)
    assert take_download(Download(raises=True), dl, before, out) == "folder"


def test_without_a_folder_only_the_event_is_read(tmp_path):
    _, out = folder(tmp_path)
    assert take_download(Download(writes=PDF), None, set(), out) == "event"
    out.unlink()
    assert take_download(Download(), None, set(), out) == ""
    assert not out.exists(), "the event's empty file is not left behind"


# clear_copies

def test_an_exact_copy_that_arrived_is_cleared(tmp_path):
    """A capture that got its document some other way, while the browser
    also saved it into the folder."""
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    out.parent.mkdir()
    out.write_bytes(PDF)
    (dl / "Statement.pdf").write_bytes(PDF)
    assert clear_copies(dl, before, out) == 1
    assert list(dl.iterdir()) == []
    assert out.read_bytes() == PDF


def test_anything_else_in_the_folder_is_left_alone(tmp_path):
    dl, out = folder(tmp_path)
    (dl / "was here.pdf").write_bytes(PDF)
    before = snapshot(dl)
    out.parent.mkdir()
    out.write_bytes(PDF)
    (dl / "somebody else's.pdf").write_bytes(OTHER)
    (dl / "Statement.pdf.crdownload").write_bytes(PDF)
    assert clear_copies(dl, before, out) == 0
    assert sorted(p.name for p in dl.iterdir()) == [
        "Statement.pdf.crdownload", "somebody else's.pdf", "was here.pdf"]


def test_nothing_is_cleared_against_a_document_that_is_not_there(tmp_path):
    dl, out = folder(tmp_path)
    before = snapshot(dl)
    (dl / "Statement.pdf").write_bytes(b"")
    assert clear_copies(dl, before, out) == 0
    out.parent.mkdir()
    out.write_bytes(b"")
    assert clear_copies(dl, before, out) == 0, "an empty file is nobody's document"
    assert clear_copies(None, before, out) == 0


# clear_archived_copies

def test_copies_of_archived_documents_are_cleared_and_nothing_else(tmp_path):
    dl, _ = folder(tmp_path)
    archive = tmp_path / "Statements"
    archive.mkdir()
    (archive / "2026-08-31 Statement.pdf").write_bytes(PDF)
    (dl / "Statement.pdf").write_bytes(PDF)
    (dl / "Statement (1).pdf").write_bytes(OTHER)
    (dl / "Statement.pdf.crdownload").write_bytes(PDF)
    got = clear_archived_copies(dl, [str(archive / "2026-08-31 Statement.pdf"), None, "",
                                     str(archive / "deleted after an import.pdf")])
    assert got == (1, 1)
    assert sorted(p.name for p in dl.iterdir()) == ["Statement (1).pdf",
                                                    "Statement.pdf.crdownload"]
    assert (archive / "2026-08-31 Statement.pdf").read_bytes() == PDF


def test_a_copy_whose_document_was_deleted_after_an_import_stays(tmp_path):
    """Nothing then proves it is a copy."""
    dl, _ = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(PDF)
    assert clear_archived_copies(dl, [str(tmp_path / "Statements" / "gone.pdf")]) == (0, 1)
    assert (dl / "Statement.pdf").exists()


def test_relative_record_paths_are_read_from_where_the_app_runs(tmp_path, monkeypatch):
    """Newer installs keep output_dir "." and record paths relative to it."""
    dl, _ = folder(tmp_path)
    (tmp_path / "Statements").mkdir()
    (tmp_path / "Statements" / "a.pdf").write_bytes(PDF)
    (dl / "Statement.pdf").write_bytes(PDF)
    monkeypatch.chdir(tmp_path)
    assert clear_archived_copies(dl, [os.path.join("Statements", "a.pdf")]) == (1, 0)


def test_a_file_in_the_folder_is_never_its_own_twin(tmp_path):
    dl, _ = folder(tmp_path)
    (dl / "Statement.pdf").write_bytes(PDF)
    assert clear_archived_copies(dl, [str(dl / "Statement.pdf")]) == (0, 1)
    assert (dl / "Statement.pdf").exists()


def test_empty_files_are_nobodys_copies(tmp_path):
    dl, _ = folder(tmp_path)
    (tmp_path / "empty.pdf").write_bytes(b"")
    (dl / "empty.pdf").write_bytes(b"")
    assert clear_archived_copies(dl, [str(tmp_path / "empty.pdf")]) == (0, 1)


def test_no_folder_is_not_an_error(tmp_path):
    assert clear_archived_copies(None, []) == (0, 0)
    assert clear_archived_copies(tmp_path / "missing", [str(tmp_path)]) == (0, 0)
