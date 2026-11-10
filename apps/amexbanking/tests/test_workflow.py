import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from pathlib import Path
import json
import pytest
from storage import SPEC
from amexbanking_docs import Document, App
from paperpull_core.models import State


class DummyArgs:
    def __init__(self, **kw):
        self.config = kw.get("config", "")
        self.redownload = kw.get("redownload", False)
        self.max_docs = kw.get("max_docs", None)
        self.dry_run = kw.get("dry_run", False)
        self.start_date = kw.get("start_date", None)
        self.end_date = kw.get("end_date", None)
        self.year = kw.get("year", None)
        self.type = kw.get("type", None)
        self.apply = kw.get("apply", False)
        self.yes = kw.get("yes", False)


@pytest.fixture
def app_instance(tmp_path):
    from paperpull_core import storage
    storage.bind(SPEC)

    cfg_path = tmp_path / "config.json"
    cfg = {
        "owner": "biz",
        "output_dir": str(tmp_path),
        "min_pdf_bytes": 10,
        "max_path_length": 240,
        "pilot_count": 3,
        "default_start_date": "2023-01-01",
        "filename_pattern": "{account}/{year}/{date:yyyy-mm-dd}[ {kind}][ ({part})]",
        "account_name": "AmexBiz 1234",
    }
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "Statements").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Tax Documents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Backups").mkdir(parents=True, exist_ok=True)

    return App(DummyArgs(config=str(cfg_path))), tmp_path


def test_document_key_generation_and_roundtrip():
    doc = Document(
        title="Business Checking Statement",
        date="2026-10-31",
        category="Statement",
        summary="Business Checking Statement",
        account="AmexBiz 1234",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:abc-123",
        account_token="tok-xyz",
    )
    assert doc.key == "id:URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:abc-123"

    # Roundtrip to dict and back
    data = doc.to_dict()
    restored = Document.from_dict(data)
    assert restored.key == doc.key
    assert restored.account == "AmexBiz 1234"
    assert restored.account_token == "tok-xyz"

    # Fallback key when document_id is missing
    fallback_doc = Document(
        title="Account Statement",
        date="2025-05-31",
        category="Statement",
        account="AmexBiz 1234",
    )
    assert fallback_doc.key.startswith("Statement:2025-05-31:")


def test_in_scope_filtering_by_year_and_type(app_instance):
    app, root = app_instance
    doc26_stmt = Document(title="Statement", date="2026-05-31", category="Statement")
    doc25_stmt = Document(title="Statement", date="2025-05-31", category="Statement")
    doc26_tax = Document(title="Tax Doc", date="2026-12-31", category="Tax Document")
    doc22_stmt = Document(title="Old Statement", date="2022-05-31", category="Statement")

    # default_start_date = 2023-01-01 -> doc22 is out of scope
    assert app._in_scope(doc22_stmt) is False
    assert app._in_scope(doc26_stmt) is True
    assert app._in_scope(doc25_stmt) is True
    assert app._in_scope(doc26_tax) is True

    # Filter by year = 2026
    app.args.year = "2026"
    assert app._in_scope(doc26_stmt) is True
    assert app._in_scope(doc25_stmt) is False

    # Filter by type = tax_document
    app.args.year = None
    app.args.type = "Tax Document"
    assert app._in_scope(doc26_stmt) is False
    assert app._in_scope(doc26_tax) is True


def test_select_ordering_and_pilot_limit(app_instance):
    app, root = app_instance
    docs = [
        Document(title="S1", date="2026-01-31", category="Statement", document_id="1"),
        Document(title="S2", date="2026-05-31", category="Statement", document_id="2"),
        Document(title="S3", date="2026-08-31", category="Statement", document_id="3"),
        Document(title="S4", date="2026-10-31", category="Statement", document_id="4"),
    ]
    for d in docs:
        app.discovery.update(d.key, d.to_dict())

    # Full selection: sorted newest first
    selected = app._select()
    assert len(selected) == 4
    assert [d.date for d in selected] == ["2026-10-31", "2026-08-31", "2026-05-31", "2026-01-31"]

    # Pilot selection (limit=2)
    piloted = app._select(limit=2)
    assert len(piloted) == 2
    assert [d.date for d in piloted] == ["2026-10-31", "2026-08-31"]
