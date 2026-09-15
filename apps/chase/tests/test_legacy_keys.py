"""Synthetic regression coverage for archives predating full card keys."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chase_docs import Document, migrate_legacy_keys, App, State, sanitize_component
from types import SimpleNamespace


def legacy(doc):
    return f"{doc.category}:{doc.date}:{sanitize_component(doc.title)[:60]}:{sanitize_component(doc.account)[:40]}"


def document(last4="1234", **kw):
    return Document(category="Statement", date="2026-01-01", title="Statement",
                    account=f"EXAMPLE LONG CARD PRODUCT NAME SHARED PREFIX (...{last4})", **kw)


def test_completed_legacy_archive_skips_without_pdf():
    doc = document(state=State.COMPLETED.value, downloaded_ok=True)
    records = {legacy(doc): doc.to_dict()}
    assert migrate_legacy_keys(records) == 1
    app = App.__new__(App)
    app.args = SimpleNamespace(redownload=False)
    app.progress = records
    assert app._already_done(doc)
    app.args.redownload = True
    assert not app._already_done(doc)
    assert migrate_legacy_keys(records) == 0


def test_two_cards_sharing_old_prefix_are_not_both_completed():
    first, second = document(downloaded_ok=True), document("5678")
    assert legacy(first) == legacy(second)
    records = {legacy(first): first.to_dict(), second.key: second.to_dict()}
    migrate_legacy_keys(records)
    assert records[first.key]["downloaded_ok"]
    assert not records[second.key]["downloaded_ok"]


def test_fresh_discovery_does_not_replace_completed_record():
    old = document(state=State.COMPLETED.value, pdf_path="Statements/example.pdf")
    fresh = document()
    records = {legacy(old): old.to_dict(), fresh.key: fresh.to_dict()}
    migrate_legacy_keys(records)
    assert len(records) == 1
    assert records[fresh.key]["state"] == State.COMPLETED.value
    assert records[fresh.key]["pdf_path"] == "Statements/example.pdf"


def test_existing_completed_current_record_is_preserved():
    old, new = document(downloaded_ok=True), document(downloaded_ok=True, notes="current")
    records = {legacy(old): old.to_dict(), new.key: new.to_dict()}
    migrate_legacy_keys(records)
    assert records[new.key]["notes"] == "current"


def test_unknown_and_api_keys_are_untouched():
    doc, api = document(), document(document_id="synthetic-id")
    records = {"unknown": doc.to_dict(), api.key: api.to_dict()}
    assert migrate_legacy_keys(records) == 0
    assert set(records) == {"unknown", api.key}


def test_conflicting_full_identity_is_not_merged():
    doc = document(downloaded_ok=True)
    other = doc.to_dict(); other["account"] += " different"
    records = {legacy(doc): doc.to_dict(), doc.key: other}
    assert migrate_legacy_keys(records) == 0
    assert len(records) == 2




def test_startup_rediscovery_and_restarts_never_download_completed_archive(tmp_path, monkeypatch):
    import json
    import chase_docs
    old = document(downloaded_ok=True, state=State.COMPLETED.value)
    # Real on-disk legacy state, plus the duplicate discovery created by a
    # newer version. Deliberately no PDF: completion must survive imports.
    (tmp_path / "progress.json").write_text(json.dumps({legacy(old): old.to_dict()}))
    (tmp_path / "discovery.json").write_text(json.dumps({
        legacy(old): old.to_dict(), old.key: document().to_dict()}))
    config = {"output_dir": str(tmp_path), "owner": "",
              "document_types": ["Statement"], "min_pdf_bytes": 2000}
    monkeypatch.setattr(chase_docs, "load_config", lambda path: config)
    monkeypatch.setattr(chase_docs, "ensure_owner", lambda *args: None)
    monkeypatch.setattr(App, "_setup_logging", lambda self: None)
    monkeypatch.setattr(App, "page", lambda self: object())
    monkeypatch.setattr(App, "_delay", lambda self: None)
    def unexpected_download(*args, **kwargs):
        raise AssertionError("Completed statement reached the downloader")
    monkeypatch.setattr(App, "download_one", unexpected_download)
    args = SimpleNamespace(config=None, redownload=False, start_date=None)
    for _ in range(3):
        app = App(args)
        assert app._record_chase_doc({"title": old.title, "date": old.date,
                                      "account": old.account}) == 0
        assert len(app.discovery.data) == 1
        app.process([Document.from_dict(v) for v in app.discovery.data.values()])
        assert app.stats["skipped_completed"] == 1
        assert app.stats["failed"] == 0
        assert app.stats["new_files"] == []
        assert set(json.loads((tmp_path / "progress.json").read_text())) == {old.key}
