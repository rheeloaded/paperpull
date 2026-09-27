"""A printed receipt loses blank pages at its end and nothing else.

RECORDED, the owner's first Apple Store invoice printed a second page with
nothing on it. The PDFs here are built by hand, a page of text and blank
pages, so no browser is needed.
"""
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import apple_site as site  # noqa: E402


def _text_page(writer: PdfWriter, words: str):
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % words).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    return page


def _pdf(tmp_path, pages) -> Path:
    writer = PdfWriter()
    for kind in pages:
        if kind == "blank":
            writer.add_blank_page(width=612, height=792)
        else:
            _text_page(writer, kind)
    out = tmp_path / "receipt.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    return out


def test_a_blank_last_page_is_dropped(tmp_path):
    path = _pdf(tmp_path, ["Order Number W0000000001", "blank"])
    assert site.drop_blank_last_pages(path) == 1
    reader = PdfReader(str(path))
    assert len(reader.pages) == 1
    assert "W0000000001" in reader.pages[0].extract_text()


def test_every_blank_page_at_the_end_goes_and_one_with_words_stays(tmp_path):
    path = _pdf(tmp_path, ["Receipt", "Visit Apple Support", "blank", "blank"])
    assert site.drop_blank_last_pages(path) == 2
    assert len(PdfReader(str(path)).pages) == 2


def test_a_receipt_with_nothing_blank_is_left_as_it_was(tmp_path):
    path = _pdf(tmp_path, ["Receipt", "Visit Apple Support"])
    before = path.read_bytes()
    assert site.drop_blank_last_pages(path) == 0
    assert path.read_bytes() == before


def test_the_first_page_is_never_dropped(tmp_path):
    path = _pdf(tmp_path, ["blank"])
    assert site.drop_blank_last_pages(path) == 0
    assert len(PdfReader(str(path)).pages) == 1


def test_a_file_that_cannot_be_read_is_left_alone(tmp_path):
    path = tmp_path / "not.pdf"
    path.write_bytes(b"not a pdf")
    assert site.drop_blank_last_pages(path) == 0
    assert path.read_bytes() == b"not a pdf"
