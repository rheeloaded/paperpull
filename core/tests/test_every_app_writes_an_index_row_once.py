"""A document's row in the index is written once however many runs fail it.

Ally's tax forms API lists a 2019 Form 1099-INT its page cannot open, and
every run tried it again and added the same "Capture failed" row to the
document index, so the reporter's index held seven rows, word for word
alike, for one form (#152). Every document app writes its index the same
way, a row appended for each outcome, and every outcome that is tried again
on the next run, a capture that saved nothing above all, was written again
on every run it ended the same way.

Each document app is built as it is at home and its own _record and
_write_row write the document down as three runs that fail it would, each
from what discovery listed, as its process takes it. Its index then holds
one row for it. Two documents that fail are two rows. A row of the index
carries no column that names its document, so two documents whose rows read
alike word for word are one row, which says no less, and the run state keeps
a record of each and the run counts each. No app is found by its name, a
document app is one whose entry is a *_docs.py.
"""
import csv
import sys
from pathlib import Path

import pytest

from paperpull_core.models import State

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DOCUMENT_APPS = sorted(d for d in (REPO / "apps").iterdir()
                       if d.is_dir() and census.entry_of(d) is not None
                       and census.entry_of(d).name.endswith("_docs.py"))
IDS = [d.name for d in DOCUMENT_APPS]


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return census.Home(request.param, tmp_path, monkeypatch, capsys)


def listed(home, account: str, date: str = census.DATE):
    """One document as this app's own Document class records it, listed in
    discovery as its listing leaves it. Its key is returned."""
    Document = home.mod.Document
    category = (home.config.get("document_types") or ["Statement"])[0]
    doc = Document(title=census.TITLE, category=category, summary="Monthly Statement " + account,
                   date=date, account=account, document_id="DOC" + account)
    app = home.build()
    rec = doc.to_dict()
    rec["state"] = State.DISCOVERED.value
    app.discovery.update(doc.key, rec, save=False)
    app.discovery.save()
    return doc.key


def failed_on_a_run(home, key: str):
    """One run that takes the document as its process does, from what
    discovery listed, and ends it as a capture that saved nothing."""
    app = home.build()
    doc = home.mod.Document.from_dict(app.discovery.get(key))
    app._record(doc, State.FAILED, notes="Could not capture the document PDF")
    app._write_row(doc, "Capture failed", State.FAILED.value)
    app.progress.save()
    app.discovery.save()


def rows(home):
    path = home.build().paths.document_index_csv
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("home", DOCUMENT_APPS, ids=IDS, indirect=True)
def test_a_document_that_fails_on_three_runs_has_one_row(home):
    key = listed(home, census.ACCOUNTS[0])
    for _run in range(3):
        failed_on_a_run(home, key)
    held = rows(home)
    assert len(held) == 1, "%d rows for one document that failed on three runs" % len(held)
    assert held[0]["Processing Status"] == State.FAILED.value


@pytest.mark.parametrize("home", DOCUMENT_APPS, ids=IDS, indirect=True)
def test_two_documents_that_fail_have_a_row_each(home):
    """The twin, so one row above is not every row taken for one. Their
    dates and summaries tell them apart."""
    keys = [listed(home, census.ACCOUNTS[0]), listed(home, census.ACCOUNTS[1], "2026-08-12")]
    assert keys[0] != keys[1]
    for key in keys:
        failed_on_a_run(home, key)
    assert len(rows(home)) == 2, rows(home)


def test_every_document_app_is_covered():
    """Not a check that passes because it found nobody."""
    assert len(DOCUMENT_APPS) >= 67, IDS
    assert {"ally", "wellsfargo", "usbank", "wealthfront", "anthem"} <= set(IDS)
