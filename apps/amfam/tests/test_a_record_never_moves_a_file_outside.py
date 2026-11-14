"""A record that names a file outside the account's folders never moves it.

A statement byte for byte another bill's sends that other bill's file to
Manual Review (_distrust). Its record names the file, and a history file
imported from somewhere else can name any file on this computer, which was
then moved (a private report of 2026-11-10). Only a document the account
holds, in a folder it files in once links and ".." are followed, is moved
now, and the record is marked for review either way. Every name and file
here is invented.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import amfam_docs  # noqa: E402


class Store(dict):
    def update(self, key, value=None):
        if value is None:
            return super().update(key)
        self[key] = value


def distrusted(tmp_path, named):
    folder = tmp_path / "acct"
    review = folder / "Manual Review"
    statements = folder / "Statements"
    review.mkdir(parents=True, exist_ok=True)
    statements.mkdir(exist_ok=True)
    progress = Store({"k": {"pdf_path": named, "state": "Completed", "downloaded_ok": True,
                            "date": "2026-09-12", "title": "Billing Statement", "notes": ""}})
    app = SimpleNamespace(progress=progress, discovery=Store(), config={"max_path_length": 240},
                          paths=SimpleNamespace(manual_review=review,
                                                filing_folders=lambda: [statements, review]),
                          SAME_PDF=amfam_docs.App.SAME_PDF, _write_row=lambda *a, **k: None)
    amfam_docs.App._distrust(app, "k")
    return progress["k"], review, statements


@pytest.mark.parametrize("how", ["absolute", "climbing out"])
def test_a_file_outside_the_accounts_folders_stays_where_it_is(tmp_path, monkeypatch, how):
    decoy = tmp_path / "outside" / "decoy.pdf"
    decoy.parent.mkdir()
    decoy.write_bytes(b"%PDF-1.4 not the account's")
    monkeypatch.chdir(tmp_path)
    named = str(decoy) if how == "absolute" else "acct/Statements/../../outside/decoy.pdf"
    rec, review, _ = distrusted(tmp_path, named)
    assert decoy.read_bytes() == b"%PDF-1.4 not the account's"
    assert list(review.iterdir()) == []
    assert rec["downloaded_ok"] is False and amfam_docs.App.SAME_PDF in rec["notes"]


def test_the_accounts_own_twin_still_goes_to_manual_review(tmp_path):
    twin = tmp_path / "acct" / "Statements" / "2026-09-12 Billing Statement.pdf"
    twin.parent.mkdir(parents=True)
    twin.write_bytes(b"%PDF-1.4 the account's own")
    rec, review, _ = distrusted(tmp_path, str(twin))
    assert not twin.exists() and (review / twin.name).read_bytes() == b"%PDF-1.4 the account's own"
    assert rec["pdf_path"] == str(review / twin.name)
