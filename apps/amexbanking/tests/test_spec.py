import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import pytest
from pathlib import Path
from storage import SPEC
import amexbanking_site as site


def test_spec_folders_and_routes():
    folder_attrs = [f.attr for f in SPEC.folders]
    assert "statements" in folder_attrs
    assert "tax_documents" in folder_attrs
    assert SPEC.routes["Statement"] == "statements"
    assert SPEC.routes["Tax Document"] == "tax_documents"


def test_safety_url_guards():
    assert site.is_safe_url("https://business.americanexpress.com/documents") is True
    assert site.is_safe_url("https://global.americanexpress.com/dashboard") is True
    assert site.is_safe_url("https://americanexpress.com/path") is True

    # Hostile or off-host URLs must be refused
    assert site.is_safe_url("http://business.americanexpress.com/insecure") is False
    assert site.is_safe_url("https://evil.americanexpress.com.fake/doc") is False
    assert site.is_safe_url("https://attacker.com/statement.pdf") is False


def test_safety_control_guards():
    # Safe document controls
    assert site.is_safe_control("Download Statement (PDF)") is True
    assert site.is_safe_control("View 1099 Tax Form") is True
    assert site.is_safe_control("Checking Statement") is True

    # Dangerous / money-movement controls must be refused
    assert site.is_safe_control("Pay Bill") is False
    assert site.is_safe_control("Transfer Funds") is False
    assert site.is_safe_control("Wire Money") is False
    assert site.is_safe_control("Make Deposit") is False
    assert site.is_safe_control("Close Account") is False
    assert site.is_safe_control("Save Settings") is False


def test_write_if_pdf(tmp_path):
    pdf_path = tmp_path / "valid.pdf"
    valid_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    assert site._write_if_pdf(valid_pdf_bytes, pdf_path) is True
    assert pdf_path.exists()
    assert pdf_path.read_bytes() == valid_pdf_bytes

    # Invalid non-PDF data must be rejected
    bad_path = tmp_path / "bad.pdf"
    assert site._write_if_pdf(b"<html>Not a PDF</html>", bad_path) is False
    assert not bad_path.exists()
