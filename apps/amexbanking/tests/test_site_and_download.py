import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from pathlib import Path
import base64
import pytest
from unittest.mock import MagicMock
import amexbanking_site as site
from paperpull_core import intake, testkit


class MockLocator:
    def __init__(self, text="", count_val=1):
        self._text = text
        self._count = count_val

    def count(self):
        return self._count

    def inner_text(self, timeout=3000):
        return self._text

    def is_visible(self):
        return bool(self._count)

    @property
    def first(self):
        return self

    def locator(self, sel):
        return MockLocator("", 0)


class MockPage:
    def __init__(self, content="", title_text="", url="https://business.americanexpress.com/"):
        self._content = content
        self._title = title_text
        self.url = url

    def title(self):
        return self._title

    def content(self):
        return self._content

    def locator(self, selector):
        if selector == "body":
            return MockLocator(self._content)
        if "password" in selector and "login" in self.url.lower():
            return MockLocator("", 1)
        if "header" in selector or "main" in selector:
            return MockLocator(self._content)
        return MockLocator("", 0)


def test_detect_security_challenge_triggers():
    for phrase in ["Please enter the code sent to your phone",
                   "Enter your 6-digit verification code",
                   "Enter the one-time code to proceed",
                   "Confirm your identity before continuing"]:
        page = MockPage(content=f"Security Check: {phrase}")
        assert site.detect_security_challenge(page) is not None

    normal_page = MockPage(content="Documents and Statements Center", title_text="Documents")
    assert site.detect_security_challenge(normal_page) is None


def test_looks_signed_out():
    signed_out_page = MockPage(url="https://business.americanexpress.com/login")
    assert site.looks_signed_out(signed_out_page) is True

    expired_page = MockPage(url="https://business.americanexpress.com/sign-in?reason=session-timeout")
    assert site.looks_signed_out(expired_page) is True

    active_page = MockPage(url="https://business.americanexpress.com/accounts/manage/documents")
    assert site.looks_signed_out(active_page) is False


def test_detect_account_label_from_header():
    page = MockPage(content="Business Checking •••• 1234 Current Balance $12,345")
    label = site.detect_account_label(page)
    assert label == "Business Checking 1234"


def _raw_doc():
    return site.RawDoc(
        title="Business Checking Statement",
        date_text="2026-10-31",
        href="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123",
        category="Statement",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123",
        account="AmexBiz 1234",
        account_token="tok-456",
    )


def test_amexbanking_download_in_page(tmp_path):
    pdf_bytes = testkit.text_pdf(["Amex Business Statement 2026-10-31"])
    b64_content = base64.b64encode(pdf_bytes).decode("ascii")
    page = MagicMock()
    page.evaluate.return_value = {"documentContent": b64_content}

    out_file = tmp_path / "statement.pdf"
    ok = site.amexbanking_download(page, _raw_doc(), out_file)
    assert ok is True
    assert out_file.read_bytes() == pdf_bytes
    # URL and body go in as arguments, with the document's own token
    _js, (url, body) = page.evaluate.call_args.args
    assert "ReadBankingDocument" in url
    assert body == {"accountToken": "tok-456",
                    "bankingDocument": {"identifier": "URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123"}}


def test_amexbanking_download_handles_evaluate_error(tmp_path):
    page = MagicMock()
    page.evaluate.side_effect = Exception("Target page, context or browser has been closed")

    out_file = tmp_path / "failed.pdf"
    ok = site.amexbanking_download(page, _raw_doc(), out_file)
    assert ok is False
    assert not out_file.exists()


def test_no_backward_compat_alias():
    assert not hasattr(site, "amexbusiness_download")
