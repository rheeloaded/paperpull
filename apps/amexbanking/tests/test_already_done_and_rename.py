import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
import pytest
from storage import SPEC
from amexbanking_docs import Document, App
from paperpull_core.models import State
from paperpull_core import renaming, testkit


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
def app_env(tmp_path):
    from paperpull_core import storage
    storage.bind(SPEC)

    cfg_path = tmp_path / "config.json"
    cfg = {
        "owner": "biz",
        "output_dir": str(tmp_path),
        "min_pdf_bytes": 10,
        "max_path_length": 240,
        "filename_pattern": "{account}/{year}/{date:yyyy-mm-dd}[ {kind}][ ({part})]",
        "account_name": "AmexBiz 1234",
    }
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "Statements").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Tax Documents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Backups").mkdir(parents=True, exist_ok=True)

    app = App(DummyArgs(config=str(cfg_path)))
    return app, tmp_path


def test_already_done_with_downloaded_ok_in_progress(app_env):
    app, root = app_env
    doc = Document(
        title="Business Checking Statement",
        date="2026-10-31",
        category="Statement",
        summary="Business Checking Statement",
        account="AmexBiz 1234",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:123",
    )
    # Initially not in progress
    assert app._already_done(doc) is False

    # Mark as downloaded_ok
    app.progress.update(doc.key, {
        "downloaded_ok": True,
        "state": State.PDF_VERIFIED.value,
        "pdf_path": "Statements/2026-10-31 Statement.pdf",
    })
    assert app._already_done(doc) is True

    # --redownload flag overrides
    app.args.redownload = True
    assert app._already_done(doc) is False


@pytest.mark.parametrize("state", [State.FAILED.value, None])
def test_a_pdf_of_the_same_day_on_disk_is_not_taken_for_the_document(app_env, state):
    """A file whose name starts with the document's date may be another
    account's statement of that month, or a file the person put there, so
    a document is done only by its own record, and is asked for again."""
    app, root = app_env
    doc = Document(
        title="Business Checking Statement",
        date="2026-09-30",
        category="Statement",
        summary="Business Checking Statement",
        account="AmexBiz 1234",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:456",
    )
    if state:
        app.progress.update(doc.key, {"downloaded_ok": False, "state": state})
    pdf_file = root / "Statements" / "2026-09-30 Old Name Receipt.pdf"
    pdf_file.write_bytes(testkit.text_pdf(["Statement 2026-09-30"]))

    assert app._already_done(doc) is False
    rec = app.progress.get(doc.key) or {}
    assert not rec.get("downloaded_ok")
    assert rec.get("pdf_path", "") == ""


def test_rename_preview_and_apply(app_env):
    app, root = app_env
    doc = Document(
        title="Business Checking Statement",
        date="2026-08-31",
        category="Statement",
        summary="Business Checking Statement",
        account="AmexBiz 1234",
        document_id="URN:AXP:SCS:BANKING_STATEMENTS:DOC:BS:789",
    )

    old_file = root / "Statements" / "2026-08-31 American Express Business Statement - Receipt.pdf"
    old_file.write_bytes(testkit.text_pdf(["Statement 2026-08-31"]))

    # The record and the index row a download writes.
    doc.pdf_path, doc.pdf_filename = str(old_file.resolve()), old_file.name
    doc.downloaded_ok = True
    doc.state = State.COMPLETED.value
    app.progress.update(doc.key, doc.to_dict())
    app._write_row(doc, "Downloaded", "Completed")

    # Verify preview plans the rename without moving the file
    preview_output = []
    app.args.apply = False
    renaming.run_for(app, apply_changes=False, say=preview_output.append)
    assert any("would be renamed" in line for line in preview_output)
    assert any("2026-08-31 Statement.pdf" in line for line in preview_output)
    assert old_file.exists()

    # Apply renames actually moves the file into {account}/{year}/
    app.args.apply = True
    result = renaming.run_for(app, apply_changes=True, say=lambda *_: None)
    assert result.renamed == 1
    assert not old_file.exists()

    expected_path = root / "Statements" / "AmexBiz 1234" / "2026" / "2026-08-31 Statement.pdf"
    assert expected_path.exists()
