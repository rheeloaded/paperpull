import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock

_repo_root = Path(__file__).resolve().parents[3]
_app_dir = Path(__file__).resolve().parents[1]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from apps.discoverbank.discoverbank_site import (
    discoverbank_download,
    parse_statements_api,
    RawDoc,
    _write_if_pdf,
)


def test_parse_statements_api():
    sample_json = [
        {
            "name": "October 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-12345",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-12345",
                }
            ],
        },
        {
            "name": "September 2026",
            "statementDate": "2026-09-30T00:00:00-05:00",
            "id": "stmt-67890",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-67890",
                }
            ],
        },
    ]

    docs = parse_statements_api(sample_json, "Checking (••••)")
    assert len(docs) == 2
    assert docs[0].title == "Checking Statement"
    assert docs[0].date_text == "2026-10-31"
    assert "stmt-12345" in docs[0].href
    assert docs[0].account == "Checking (••••)"
    assert docs[0].text == "October 2026"
    assert docs[0].row_index == 0
    assert docs[1].date_text == "2026-09-30"
    assert docs[1].row_index == 1


def test_parse_statements_api_savings():
    sample_json = [
        {
            "name": "October 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-99999",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC2/statements/stmt-99999",
                }
            ],
        }
    ]
    docs = parse_statements_api(sample_json, "Online Savings Account (••••)")
    assert len(docs) == 1
    assert docs[0].title == "Savings Statement"
    assert docs[0].date_text == "2026-10-31"
    assert docs[0].account == "Online Savings Account (••••)"


def test_parse_statements_api_skips_missing_binary():
    sample_json = [
        {
            "name": "No binary",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-nobin",
            "links": [
                {
                    "rel": "self",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-nobin",
                }
            ],
        },
        {
            "name": "Valid binary",
            "statementDate": "2026-08-31T00:00:00-05:00",
            "id": "stmt-valid",
            "links": [
                {
                    "rel": "binary",
                    "href": "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-valid",
                }
            ],
        },
    ]
    docs = parse_statements_api(sample_json, "Checking")
    assert len(docs) == 1
    assert docs[0].text == "Valid binary"
    assert docs[0].date_text == "2026-08-31"


def test_raw_doc_fields():
    doc = RawDoc(
        title="Checking Statement",
        date_text="2026-10-31",
        href="https://bank.discover.com/test",
        text="October 2026",
        account="Checking (••••)",
        row_index=0,
    )
    assert doc.title == "Checking Statement"
    assert doc.date_text == "2026-10-31"
    assert doc.href == "https://bank.discover.com/test"
    assert doc.text == "October 2026"
    assert doc.account == "Checking (••••)"
    assert doc.row_index == 0


def test_parse_statements_api_money_market_and_cd():
    sample_json = [
        {
            "name": "MM Oct 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-mm",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/mm.pdf"}],
        },
        {
            "name": "CD Oct 2026",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-cd",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/cd.pdf"}],
        },
    ]
    mm_docs = parse_statements_api([sample_json[0]], "Money Market Account (••••1111)")
    assert len(mm_docs) == 1
    assert mm_docs[0].title == "Money Market Statement"

    cd_docs = parse_statements_api([sample_json[1]], "12-Month CD (••••2222)")
    assert len(cd_docs) == 1
    assert cd_docs[0].title == "CD Statement"


def test_parse_statements_api_null_date_and_unsafe_url():
    sample_json = [
        {
            "name": "Null date",
            "statementDate": None,
            "id": "stmt-null",
            "links": [{"rel": "binary", "href": "https://bank.discover.com/ok.pdf"}],
        },
        {
            "name": "Unsafe URL",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-unsafe",
            "links": [{"rel": "binary", "href": "https://card.discover.com/forbidden.pdf"}],
        },
        {
            "name": "HTTP URL",
            "statementDate": "2026-10-31T00:00:00-05:00",
            "id": "stmt-http",
            "links": [{"rel": "binary", "href": "http://bank.discover.com/insecure.pdf"}],
        },
    ]
    docs = parse_statements_api(sample_json, "Checking")
    assert len(docs) == 1
    assert docs[0].text == "Null date"
    assert docs[0].date_text == ""


def test_discoverbank_download_success(tmp_path):
    page = MagicMock()
    valid_pdf = b"%PDF-1.4 test content\n%%EOF"
    b64 = base64.b64encode(valid_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://bank.discover.com/download/pdf",
    )
    assert res is True
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_discoverbank_download_invalid_pdf(tmp_path):
    page = MagicMock()
    not_pdf = b"<html>Sign In Required</html>"
    b64 = base64.b64encode(not_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://bank.discover.com/download/pdf",
    )
    assert res is False
    assert not out_file.exists()


def test_discoverbank_download_unsafe_url(tmp_path):
    page = MagicMock()
    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="https://card.discover.com/download/pdf",
    )
    assert res is False
    assert not out_file.exists()
    page.evaluate.assert_not_called()


def test_discoverbank_download_empty_href(tmp_path):
    page = MagicMock()
    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-10-31", out_file,
        href="",
    )
    assert res is False
    assert not out_file.exists()


def test_parse_statements_api_relative_url():
    sample_json = [
        {
            "name": "August 2026",
            "statementDate": "2026-08-31T00:00:00-05:00",
            "id": "stmt-relative",
            "links": [
                {
                    "rel": "binary",
                    "href": "/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative",
                }
            ],
        }
    ]
    docs = parse_statements_api(sample_json, "Savings (••••)")
    assert len(docs) == 1
    assert docs[0].href == "https://bank.discover.com/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative"


def test_discoverbank_download_relative_url(tmp_path):
    page = MagicMock()
    valid_pdf = b"%PDF-1.4 relative test\n%%EOF"
    b64 = base64.b64encode(valid_pdf).decode("ascii")
    page.evaluate.return_value = {"ok": True, "b64": b64}

    out_file = tmp_path / "statement.pdf"
    res = discoverbank_download(
        page, None, "Checking", "2026-08-31", out_file,
        href="/bank/deposits/servicing/documents/v1/accounts/ACC1/statements/stmt-relative",
    )
    assert res is True
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_write_if_pdf_atomic(tmp_path):
    out_file = tmp_path / "test.pdf"
    assert not _write_if_pdf(b"not a pdf", out_file)
    assert not out_file.exists()

    valid_pdf = b"%PDF-1.7 atomic write content"
    assert _write_if_pdf(valid_pdf, out_file)
    assert out_file.exists()
    assert out_file.read_bytes() == valid_pdf


def test_list_deposit_accounts_from_fiber():
    from discoverbank_site import list_deposit_accounts
    page = MagicMock()
    page.evaluate.return_value = [
        {"index": 0, "text": "Checking (••••)", "id": "SM_CHECKING"},
        {"index": 1, "text": "Savings (••••)", "id": "SM_SAVINGS"},
    ]
    accounts = list_deposit_accounts(page)
    assert len(accounts) == 2
    assert accounts[0]["text"] == "Checking (••••)"
    assert accounts[1]["text"] == "Savings (••••)"


def test_discoverbank_collect_fiber_direct_fetch():
    from discoverbank_site import discoverbank_collect
    page = MagicMock()

    def mock_eval(script, *args):
        if "__reactFiber" in script:
            return [
                {"label": "Checking (••••)", "id": "SM_CHECKING"},
                {"label": "Savings (••••)", "id": "SM_SAVINGS"},
            ]
        if "fetch(url" in script:
            url = args[0]
            if "SM_CHECKING" in url:
                return [
                    {
                        "statementDate": "2026-10-31",
                        "name": "Checking Stmt",
                        "links": [{"rel": "binary", "href": "/bank/deposits/servicing/documents/v1/accounts/SM_CHECKING/statements/stmt-oc"}]
                    }
                ]
            elif "SM_SAVINGS" in url:
                return [
                    {
                        "statementDate": "2026-10-31",
                        "name": "Savings Stmt",
                        "links": [{"rel": "binary", "href": "/bank/deposits/servicing/documents/v1/accounts/SM_SAVINGS/statements/stmt-osa"}]
                    }
                ]
        return []

    page.evaluate.side_effect = mock_eval
    docs = discoverbank_collect(page)
    assert len(docs) == 2
    accts = {d.account for d in docs}
    assert "Checking (••••)" in accts
    assert "Savings (••••)" in accts

