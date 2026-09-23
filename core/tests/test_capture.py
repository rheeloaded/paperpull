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
