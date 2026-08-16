"""PDF validation tests (all local, using pypdf-generated files)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_pdf import validate_pdf


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
    """Robinhood delivers some tax forms (e.g. 1099-R) as a ZIP holding the
    PDF; it must be detected and unpacked, not saved as a broken 'PDF'."""
    import zipfile
    from receipt_pdf import extract_pdfs_from_zip, is_zip

    inner = tmp_path / "inner.pdf"
    make_pdf(inner)
    zpath = tmp_path / "download.pdf"          # named .pdf but really a zip
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(inner, "8W14VV76_UAN30035133_2026-01-10_0.pdf")
    inner.unlink()

    assert is_zip(zpath)
    out = tmp_path / "2025-12-31 Robinhood 1099-R Tax Form.pdf"
    zpath.replace(out)
    saved = extract_pdfs_from_zip(out, out)
    assert len(saved) == 1 and saved[0] == out
    assert not is_zip(out)
    assert validate_pdf(out, min_bytes=1000).ok


def test_zip_with_multiple_pdfs_numbers_extras(tmp_path):
    import zipfile
    from receipt_pdf import extract_pdfs_from_zip

    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(a); make_pdf(b)
    out = tmp_path / "Form.pdf"
    with zipfile.ZipFile(out, "w") as z:
        z.write(a, "first.pdf")
        z.write(b, "second.pdf")
    a.unlink(); b.unlink()
    saved = extract_pdfs_from_zip(out, out)
    assert len(saved) == 2
    assert saved[0].name == "Form.pdf"
    assert saved[1].name == "Form (2 of 2).pdf"


def test_zip_without_pdfs_returns_empty(tmp_path):
    import zipfile
    from receipt_pdf import extract_pdfs_from_zip

    out = tmp_path / "Form.pdf"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("readme.txt", "no pdfs here")
    assert extract_pdfs_from_zip(out, out) == []


def test_image_based_pdf_not_rejected_for_no_text(tmp_path):
    # a blank-page PDF has no extractable text; token check must not reject it
    p = tmp_path / "img.pdf"
    make_pdf(p)
    r = validate_pdf(p, min_bytes=1000, expect_tokens=["robinhood", "12345"])
    assert r.ok, r.reason
