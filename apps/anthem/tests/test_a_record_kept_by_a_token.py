"""An EOB an older version recorded by its token is set down, never tried again.

Until #210 the claim number was read from the claim identifier's value, and
once Anthem put an opaque token there ("e_" and hex, made new on every call)
every EOB was recorded as Medical|e_...|EOB|n. The guard refuses that id, so
each run offered every such record, failed on it and wrote a failure file,
and each listing added more. The same EOB is listed now by the claim number
shown beside the token. A record whose id the guard refuses and that was
never downloaded is set down as No Longer Listed when the app starts. One
that was downloaded, or holds a file, is never touched.

The records are written by the app's own recording code, as the older
version wrote them, into the app's real stores. Every claim number, token
and name here is invented.
"""
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_docs as app_mod  # noqa: E402
from paperpull_core.models import State  # noqa: E402

TOKEN_ID = "Medical|e_" + "2e" * 67 + "|EOB|2"
OTHER_TOKEN_ID = "Pharmacy|e_" + "4f" * 67 + "|EOB|0"
GOOD_ID = "Medical|9000000AA0001|EOB|2"


@pytest.fixture
def build(tmp_path, monkeypatch):
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")

    def made(*flags):
        return app_mod.App(app_mod.build_parser().parse_args(["--config", str(cfg), *flags]))
    return made


def listed(app, doc_id, title="Medical Explanation of Benefits"):
    """One row recorded as cmd_discover records it, and its key."""
    assert app._record_statement_doc({"title": title, "date": "2026-03-04",
                                      "account": "Dana Example - Medical claim", "doc_id": doc_id})
    return "id:" + doc_id


def failed(app, key):
    """The record a download that the guard refused left behind."""
    doc = app_mod.Document.from_dict(app.discovery.get(key))
    app._record(doc, State.FAILED, notes="Could not capture the document PDF")


def saved_to_disk(app):
    app.progress.save()
    app.discovery.save()


def on_disk(app):
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))  # noqa: E731
    return read(app.paths.progress_json), read(app.paths.discovery_json)


def test_a_token_record_that_failed_is_set_down_and_never_offered_again(build):
    first = build("--all")
    token, good = listed(first, TOKEN_ID), listed(first, GOOD_ID)
    failed(first, token)
    saved_to_disk(first)
    assert {d.key for d in first._select()} == {token, good}

    app = build("--all")
    progress, discovery = on_disk(app)
    assert progress[token]["state"] == discovery[token]["state"] == State.NO_LONGER_LISTED.value
    assert app_mod.TOKEN_ID_NOTE in progress[token]["notes"]
    assert "Could not capture the document PDF" in progress[token]["notes"]
    assert [d.key for d in app._select()] == [good]
    assert discovery[good]["state"] == State.DISCOVERED.value
    assert build("--all", "--redownload")._select()[0].key == good
    assert len(build("--all", "--redownload")._select()) == 1


def test_a_token_record_only_listed_is_set_down_without_a_record_of_progress(build):
    first = build("--all")
    token = listed(first, OTHER_TOKEN_ID, "Pharmacy Explanation of Benefits")
    saved_to_disk(first)
    app = build("--all")
    progress, discovery = on_disk(app)
    assert discovery[token]["state"] == State.NO_LONGER_LISTED.value
    assert token not in progress
    assert app._select() == []


def test_setting_down_is_done_once(build):
    first = build("--all")
    failed(first, listed(first, TOKEN_ID))
    saved_to_disk(first)
    app = build("--all")
    assert app_mod.retire_token_records(app.progress, app.discovery) == 0


@pytest.mark.parametrize("store, change", [
    ("progress", {"downloaded_ok": True}),
    ("progress", {"pdf_path": "/invented/eob.pdf"}),
    ("progress", {"state": State.COMPLETED.value}),
    ("progress", {"state": State.PDF_VERIFIED.value}),
    ("progress", {"state": State.NEEDS_MANUAL_REVIEW.value, "pdf_path": "/invented/eob.pdf"}),
    ("discovery", {"downloaded_ok": True}),
    ("discovery", {"pdf_path": "/invented/eob.pdf"}),
])
def test_a_token_record_that_was_downloaded_or_holds_a_file_stays_as_it_is(build, store, change):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    failed(first, token)
    getattr(first, store).update(token, change, save=False)
    saved_to_disk(first)
    before = on_disk(first)
    app = build("--all")
    assert on_disk(app) == before
    assert app_mod.retire_token_records(app.progress, app.discovery) == 0


@pytest.mark.parametrize("doc_id", [
    GOOD_ID,
    "Pharmacy|20260301|Statement|0",
    "Medical|9000000AA0001|EOB",
    "ClaimsSummary|2025",
    "Letter|e_" + "2e" * 67,
])
def test_an_id_the_guard_takes_or_of_another_surface_stays_as_it_is(build, doc_id):
    first = build("--all")
    key = listed(first, doc_id)
    failed(first, key)
    saved_to_disk(first)
    before = on_disk(first)
    app = build("--all")
    assert on_disk(app) == before
    assert app.progress.get(key)["state"] == State.FAILED.value


def test_a_record_value_that_is_not_text_is_passed_over(build):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    failed(first, token)
    first.discovery.update(token, {"document_id": ["not", "text"]}, save=False)
    first.progress.update(token, {"notes": 7}, save=False)
    assert app_mod.retire_token_records(first.progress, first.discovery) == 0
    first.discovery.update(token, {"document_id": TOKEN_ID}, save=False)
    assert app_mod.retire_token_records(first.progress, first.discovery) == 1
    assert first.progress.get(token)["notes"] == app_mod.TOKEN_ID_NOTE


def test_a_token_record_only_progress_holds_is_set_down_too(build):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    failed(first, token)
    del first.discovery.data[token]
    saved_to_disk(first)
    app = build("--all")
    progress, discovery = on_disk(app)
    assert progress[token]["state"] == State.NO_LONGER_LISTED.value
    assert token not in discovery


@pytest.mark.parametrize("state", [State.NEEDS_MANUAL_REVIEW.value, State.PDF_SAVED.value,
                                   State.NO_RECEIPT_AVAILABLE.value, State.CANCELED.value,
                                   "a state of another version"])
def test_only_a_record_discovered_or_failed_or_with_no_state_is_set_down(build, state):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    failed(first, token)
    first.progress.update(token, {"state": state}, save=False)
    saved_to_disk(first)
    before = on_disk(first)
    app = build("--all")
    assert on_disk(app) == before


def test_a_record_with_no_state_is_set_down(build):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    first.discovery.data[token].pop("state")
    saved_to_disk(first)
    app = build("--all")
    assert on_disk(app)[1][token]["state"] == State.NO_LONGER_LISTED.value


def test_two_stores_naming_two_ids_are_left_as_they_are(build):
    first = build("--all")
    token = listed(first, TOKEN_ID)
    failed(first, token)
    first.progress.update(token, {"document_id": GOOD_ID}, save=False)
    saved_to_disk(first)
    before = on_disk(first)
    app = build("--all")
    assert on_disk(app) == before
