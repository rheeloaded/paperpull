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
