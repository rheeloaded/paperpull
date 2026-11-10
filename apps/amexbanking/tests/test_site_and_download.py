import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import base64
import pytest
from unittest.mock import MagicMock
import amexbanking_site as site
from paperpull_core import intake, testkit


@pytest.fixture(autouse=True)
def fresh_session():
    site.SESSION = site.BankingSession()
    yield


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


def test_an_account_is_not_guessed_from_the_pages_text():
    """With no switcher, a name and four digits in the page's text may be
    anything, so no account is read from them."""
    page = MockPage(content="Business Checking •••• 1234 Current Balance $12,345")
    assert site.detect_account_label(page) == ""


def _raw_doc(doc_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123", token="tok-456"):
    return site.RawDoc(
        title="Business Checking Statement",
        date_text="2026-10-31",
        href=doc_id,
        category="Statement",
        document_id=doc_id,
        account="AmexBiz 1234",
        account_token=token,
    )


def _answering(pdf_bytes, status=200, redirected=False):
    page = MagicMock()
    page.evaluate.return_value = {
        "status": status, "redirected": redirected,
        "data": {"documentContent": base64.b64encode(pdf_bytes).decode("ascii")}}
    return page


def test_amexbanking_download_in_page(tmp_path):
    pdf_bytes = testkit.text_pdf(["Amex Business Statement 2026-10-31"])
    page = _answering(pdf_bytes)

    out_file = tmp_path / "statement.pdf"
    ok = site.amexbanking_download(page, _raw_doc(), out_file)
    assert ok is True
    assert out_file.read_bytes() == pdf_bytes
    # URL and body go in as arguments, with the document's own id and token,
    # through the reader that holds the answer to a document's limit.
    js, (url, body) = page.evaluate.call_args.args
    assert intake.READ_MARK in js and "ppJson" in js
    assert url == site.DOCUMENT_URL
    assert body == {"accountToken": "tok-456",
                    "bankingDocument": {"identifier": "URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123"}}


@pytest.mark.parametrize("doc_id, token", [("", "tok-456"), ("URN:DOC:1", "")])
def test_a_document_without_its_id_or_its_token_is_not_asked_for(tmp_path, doc_id, token):
    """No token is taken from the page or another account's request for it."""
    page = _answering(testkit.text_pdf(["x"]))
    out_file = tmp_path / "statement.pdf"
    assert site.amexbanking_download(page, _raw_doc(doc_id, token), out_file) is False
    assert not page.evaluate.called
    assert not out_file.exists()


@pytest.mark.parametrize("status, redirected", [(401, False), (403, False), (200, True)])
def test_a_refusal_raises_session_expired(tmp_path, status, redirected):
    page = _answering(testkit.text_pdf(["x"]), status=status, redirected=redirected)
    out_file = tmp_path / "statement.pdf"
    with pytest.raises(site.SessionExpired):
        site.amexbanking_download(page, _raw_doc(), out_file)
    assert not out_file.exists()


def test_another_answer_fails_this_document_alone(tmp_path):
    page = _answering(testkit.text_pdf(["x"]), status=500)
    out_file = tmp_path / "statement.pdf"
    assert site.amexbanking_download(page, _raw_doc(), out_file) is False
    assert not out_file.exists()


def test_the_bytes_of_another_document_are_not_saved_as_this_one(tmp_path):
    pdf_bytes = testkit.text_pdf(["Statement of one month"])
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    assert site.amexbanking_download(_answering(pdf_bytes), _raw_doc("URN:DOC:1"), first)
    assert site.amexbanking_download(_answering(pdf_bytes), _raw_doc("URN:DOC:2"), second) is False
    assert not second.exists()
    # The same document asked for again, by Download again, is its own.
    again = tmp_path / "again.pdf"
    assert site.amexbanking_download(_answering(pdf_bytes), _raw_doc("URN:DOC:1"), again)


def test_amexbanking_download_handles_evaluate_error(tmp_path):
    page = MagicMock()
    page.evaluate.side_effect = Exception("Target page, context or browser has been closed")

    out_file = tmp_path / "failed.pdf"
    ok = site.amexbanking_download(page, _raw_doc(), out_file)
    assert ok is False
    assert not out_file.exists()


def test_no_backward_compat_alias():
    assert not hasattr(site, "amexbusiness_download")
