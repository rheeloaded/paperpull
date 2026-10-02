"""PDF validation tests (all local, using pypdf-generated files)."""
import sys
from pathlib import Path


from paperpull_core.receipt_pdf import validate_pdf


def make_pdf(path: Path, pages: int = 1, pad_to: int = 4000):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        w.write(f)
    # pad with trailing bytes after EOF so it clears the min-size check
    size = path.stat().st_size
    if size < pad_to:
        with open(path, "ab") as f:
            f.write(b" " * (pad_to - size))


def test_valid_pdf(tmp_path):
    p = tmp_path / "r.pdf"
    make_pdf(p)
    r = validate_pdf(p, min_bytes=1000)
    assert r.ok, r.reason
    assert r.page_count == 1
    assert r.size_bytes >= 1000


def test_missing_file(tmp_path):
    r = validate_pdf(tmp_path / "nope.pdf")
    assert not r.ok and "not exist" in r.reason


def test_zero_byte_file(tmp_path):
    p = tmp_path / "z.pdf"
    p.write_bytes(b"")
    r = validate_pdf(p)
    assert not r.ok and "zero" in r.reason


def test_too_small_file(tmp_path):
    p = tmp_path / "s.pdf"
    p.write_bytes(b"%PDF-1.4 tiny")
    r = validate_pdf(p, min_bytes=3000)
    assert not r.ok and "minimum" in r.reason


def test_not_a_pdf(tmp_path):
    p = tmp_path / "h.pdf"
    p.write_bytes(b"<html>this is a web page</html>" + b"x" * 5000)
    r = validate_pdf(p, min_bytes=1000)
    assert not r.ok and "signature" in r.reason


def test_corrupt_pdf_body(tmp_path):
    p = tmp_path / "c.pdf"
    p.write_bytes(b"%PDF-1.7\n" + b"garbage " * 1000)
    r = validate_pdf(p, min_bytes=1000)
    assert not r.ok


def test_zip_detection_and_extraction(tmp_path):
    """Some tax forms (a 1099-R, say) arrive as a ZIP holding the PDF. It
    must be detected and unpacked, not saved as a broken 'PDF'."""
    import zipfile
    from paperpull_core.receipt_pdf import is_zip, open_zip

    inner = tmp_path / "inner.pdf"
    make_pdf(inner)
    zpath = tmp_path / "download.pdf"          # named .pdf but really a zip
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(inner, "8W14VV76_UAN30035133_2026-01-10_0.pdf")
    inner.unlink()

    assert is_zip(zpath)
    out = tmp_path / "2025-12-31 T-Mobile 1099-R Tax Form.pdf"
    zpath.replace(out)
    opened = open_zip(out, tmp_path / "Manual Review")
    assert opened.pdf == out and opened.kept is None
    assert not is_zip(out)
    assert validate_pdf(out, min_bytes=1000).ok


def test_zip_with_several_pdfs_is_kept_for_a_person(tmp_path):
    """Which of two PDFs is the document cannot be told, so neither is
    filed under its name."""
    import zipfile
    from paperpull_core.receipt_pdf import open_zip

    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(a); make_pdf(b)
    out = tmp_path / "Form.pdf"
    with zipfile.ZipFile(out, "w") as z:
        z.write(a, "first.pdf")
        z.write(b, "second.pdf")
    a.unlink(); b.unlink()
    opened = open_zip(out, tmp_path / "Manual Review")
    assert opened.pdf is None
    assert opened.kept == tmp_path / "Manual Review" / "Form.zip"
    assert "2 PDFs" in opened.reason
    assert not list(tmp_path.glob("*.pdf"))


def test_zip_without_pdfs_is_kept_for_a_person(tmp_path):
    import zipfile
    from paperpull_core.receipt_pdf import open_zip

    out = tmp_path / "Form.pdf"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("readme.txt", "no pdfs here")
    opened = open_zip(out, tmp_path / "Manual Review")
    assert opened.pdf is None and opened.failure == "the archive held no pdf"
    assert (tmp_path / "Manual Review" / "Form.zip").exists() and not out.exists()


def test_image_based_pdf_not_rejected_for_no_text(tmp_path):
    # a blank-page PDF has no extractable text; token check must not reject it
    p = tmp_path / "img.pdf"
    make_pdf(p)
    r = validate_pdf(p, min_bytes=1000, expect_tokens=["tmobile", "12345"])
    assert r.ok, r.reason
