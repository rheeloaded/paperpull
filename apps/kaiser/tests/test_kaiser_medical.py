from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_medical as medical


def test_medical_identity_binds_the_account_and_row():
    text = "Billing statement for April 1, 2031 View statement (PDF)"
    date = "April 1, 2031 Apr 1, 2031"
    first = medical._bill_from_row(text, date, "synthetic-a")
    assert first.date_text == "2031-04-01"
    assert first == medical._bill_from_row(text.replace(" ", "  "), date, "synthetic-a")
    assert first.document_id != medical._bill_from_row(text, date, "synthetic-b").document_id
    assert first.document_id != medical._bill_from_row("Updated " + text, date, "synthetic-a").document_id


def test_malformed_or_ambiguous_row_is_refused():
    with pytest.raises(medical.MedicalListError):
        medical._bill_from_row("Billing statement", "April 31, 2031", "synthetic")
    with pytest.raises(medical.MedicalListError):
        medical._bill_from_row("Billing statement", "Apr 1, 2031. Apr 2, 2031", "synthetic")


@pytest.mark.parametrize(("text", "accept"), [
    ("Account statement. Statement date: 4/1/2031", True),
    ("Account statement. Date of statement: April 1, 2031", True),
    ("Account statement. Bill Date: 4/1/2031", True),
    ("Account statement. Amount due 4/1/2031", False),
    ("Account statement. Statement date: 4/11/2031. Due: 4/1/2031", False),
    ("Account statement. Statement date: 4/31/2031. Due: 4/1/2031", False),
    ("Account statement. 14/1/2031", False),
    ("Payment information 4/1/2031", False),
])
def test_pdf_date_matches_the_row_without_date_substrings(monkeypatch, text, accept):
    bill = medical._bill_from_row("Medical statement", "April 1, 2031", "synthetic")
    monkeypatch.setattr(medical.pdf_reader, "read",
                        lambda *args, **kwargs: medical.pdf_reader.Read(True, 1, (text,)))
    assert medical._matches_pdf(b"%PDF-test", bill) is accept
    assert not medical._matches_pdf(b"<html>", bill)


def test_medical_details_origin_and_path_are_exact():
    legitimate = "https://healthy.kaiserpermanente.org/mychartcn/Billing/Details"
    assert medical.is_details_url(legitimate + "?synthetic=true")
    assert not medical.is_details_url(legitimate + "/DownloadSomething")
    assert not medical.is_details_url(legitimate.replace(".org/", ".org.test/"))


def test_accessible_label_must_match_the_selected_statement_day():
    label = "View the statement sent on April 1, 2031 (PDF)."
    assert medical.matches_accessible_label(label, "2031-04-01")
    assert not medical.matches_accessible_label(label, "2031-04-02")
    assert not medical.matches_accessible_label(label + " Pay now", "2031-04-01")
