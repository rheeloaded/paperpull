"""Tests for Schwab view-only brokerage accounts discovery and downloads.

Schwab accounts in accountSelectorData.brokerageAccountList may be listed in
viewOnlyAccounts rather than brokerageAccounts (e.g. Schwab One view-only,
trusts, or accounts with restricted trading permissions). These accounts still
hold statements, tax forms and confirmations.
"""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import storage as core_storage
import schwab_docs as docs
import schwab_site as site

PAGE = SimpleNamespace(url="https://client.schwab.com/retail/accounts/statements/#/")


def pdf_of(document_id: str) -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": f"document {document_id}"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def _setup_config(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    config = json.loads((Path(docs.__file__).parent / "config.example.json")
                        .read_text(encoding="utf-8"))
    config.update({
        "owner": "Test Owner", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(docs.App, "page", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "_on_its_site", lambda app: PAGE)
    monkeypatch.setattr(docs.App, "check_session", lambda app, *_a, **_kw: None)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return cfg, Path(config["output_dir"])


def test_view_only_accounts_are_discovered_when_brokerage_accounts_is_empty(monkeypatch):
    """When brokerageAccounts is empty, viewOnlyAccounts must still be discovered."""
    view_only_payload = {
        "accountSelectorData": {
            "brokerageAccountList": {
                "brokerageAccounts": [],
                "viewOnlyAccounts": [
                    {
                        "id": "12345678",
                        "nickName": "SchwabOne",
                        "accountType": "S1",
                        "isViewOnly": True,
                        "isClosed": False,
                        "isCharitable": False,
                        "isPrimaryAccount": True,
                    }
                ]
            }
        }
    }
    sent_headers = {}

    def mock_gateway(page, url, headers, post_body=None):
        nonlocal sent_headers
        if url == site.API["accounts"]:
            return {"status": 200, "body": view_only_payload}
        sent_headers = dict(headers)
        return {
            "status": 200,
            "body": {
                "documents": [
                    {
                        "documentId": "DOC-VO-1",
                        "documentName": "Brokerage Statement",
                        "type": "Statements",
                        "onDemandDocumentType": "Statements",
                        "date": "10/31/2026",
                        "accountDisplayName": "1234-5678",
                    }
                ]
            }
        }

    monkeypatch.setattr(site, "_gateway_call", mock_gateway)

    accounts = site.list_accounts(PAGE)
    assert len(accounts) == 1
    assert accounts[0]["account_id"] == "12345678"
    assert accounts[0]["label"] == "SchwabOne (...5678)"
    assert accounts[0]["last4"] == "5678"
    assert accounts[0]["closed"] is False
    assert accounts[0]["charitable"] is False

    docs_collected = site.collect_documents(PAGE)
    assert len(docs_collected) == 1
    doc = docs_collected[0]
    assert doc["account"] == "SchwabOne (...5678)"
    assert doc["account_id"] == "12345678"
    assert doc["title"] == "Brokerage Statement"
    assert doc["date"] == "2026-10-31"
    assert sent_headers.get("schwab-client-ids") == "12345678"


def test_charitable_view_only_account_uses_charitable_header(monkeypatch):
    """A view-only account marked charitable must send schwab-client-charitable-ids."""
    payload = {
        "accountSelectorData": {
            "brokerageAccountList": {
                "brokerageAccounts": [],
                "viewOnlyAccounts": [
                    {
                        "id": "99998888",
                        "nickName": "Giving Fund",
                        "accountType": "DAF",
                        "isViewOnly": True,
                        "isCharitable": True,
                    }
                ]
            }
        }
    }
    sent_headers = {}

    def mock_gateway(page, url, headers, post_body=None):
        nonlocal sent_headers
        if url == site.API["accounts"]:
            return {"status": 200, "body": payload}
        sent_headers = dict(headers)
        return {"status": 200, "body": {"documents": []}}

    monkeypatch.setattr(site, "_gateway_call", mock_gateway)

    accounts = site.list_accounts(PAGE)
    assert len(accounts) == 1
    assert accounts[0]["charitable"] is True

    site.collect_documents(PAGE)
    assert sent_headers.get("schwab-client-charitable-ids") == "99998888"
    assert "schwab-client-ids" not in sent_headers


def test_mixed_brokerage_and_view_only_accounts(monkeypatch):
    """Both standard brokerageAccounts and viewOnlyAccounts are included."""
    payload = {
        "accountSelectorData": {
            "brokerageAccountList": {
                "brokerageAccounts": [
                    {"id": "11112222", "nickName": "Active Trading", "accountType": "B"}
                ],
                "viewOnlyAccounts": [
                    {"id": "33334444", "nickName": "Custodial", "accountType": "UTMA", "isViewOnly": True}
                ]
            }
        }
    }
    sent_headers = {}

    def mock_gateway(page, url, headers, post_body=None):
        nonlocal sent_headers
        if url == site.API["accounts"]:
            return {"status": 200, "body": payload}
        sent_headers = dict(headers)
        return {
            "status": 200,
            "body": {
                "documents": [
                    {"documentId": "D1", "documentName": "Brokerage Statement", "type": "Statements",
                     "onDemandDocumentType": "Statements", "date": "09/30/2026", "accountDisplayName": "1111-2222"},
                    {"documentId": "D2", "documentName": "Brokerage Statement", "type": "Statements",
                     "onDemandDocumentType": "Statements", "date": "09/30/2026", "accountDisplayName": "3333-4444"},
                ]
            }
        }

    monkeypatch.setattr(site, "_gateway_call", mock_gateway)

    accounts = site.list_accounts(PAGE)
    assert len(accounts) == 2
    assert {a["account_id"] for a in accounts} == {"11112222", "33334444"}

    docs_collected = site.collect_documents(PAGE)
    assert len(docs_collected) == 2
    assert "11112222" in sent_headers.get("schwab-client-ids", "")
    assert "33334444" in sent_headers.get("schwab-client-ids", "")


def test_view_only_account_end_to_end_discover_and_download(tmp_path, monkeypatch):
    """End-to-end test verifying discovery and download with a view-only account."""
    cfg, out = _setup_config(tmp_path, monkeypatch)
    downloaded_docs = []

    def mock_gateway(page, url, headers, post_body=None):
        if url == site.API["accounts"]:
            return {
                "status": 200,
                "body": {
                    "accountSelectorData": {
                        "brokerageAccountList": {
                            "brokerageAccounts": [],
                            "viewOnlyAccounts": [
                                {
                                    "id": "12345678",
                                    "nickName": "SchwabOne",
                                    "accountType": "S1",
                                    "isViewOnly": True,
                                }
                            ]
                        }
                    }
                }
            }
        return {
            "status": 200,
            "body": {
                "documents": [
                    {
                        "documentId": "DOC-VO-123",
                        "documentName": "Brokerage Statement",
                        "type": site.TYPE_STATEMENTS,
                        "onDemandDocumentType": "Statements",
                        "date": "10/31/2026",
                        "accountDisplayName": "1234-5678",
                    }
                ]
            }
        }

    def mock_pdf(page, doc):
        downloaded_docs.append(doc["documentId"])
        return 200, pdf_of(doc["documentId"])

    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "_gateway_call", mock_gateway)
    monkeypatch.setattr(site, "fetch_pdf", mock_pdf)

    # Run discover
    docs.main(["--config", str(cfg), "--discover"])
    disc_data = json.loads((out / "discovery.json").read_text(encoding="utf-8"))
    assert len(disc_data) == 1
    key = list(disc_data.keys())[0]
    rec = disc_data[key]
    assert rec["account"] == "SchwabOne (...5678)"
    assert rec["category"] == "Statement"
    assert rec["date"] == "2026-10-31"

    # Run download all
    docs.main(["--config", str(cfg), "--all", "--yes"])
    assert downloaded_docs == ["DOC-VO-123"]
    prog_data = json.loads((out / "progress.json").read_text(encoding="utf-8"))
    assert len(prog_data) == 1
    assert prog_data[key]["state"] == "Completed"
    pdfs = list(out.rglob("*.pdf"))
    assert len(pdfs) == 1
    assert "SchwabOne" in pdfs[0].name

