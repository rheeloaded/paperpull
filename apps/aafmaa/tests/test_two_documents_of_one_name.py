"""Two AAFMAA documents that want one file name.

When a file already has a document's name, the download adds something its
record knows that tells the two apart, and Rename hands plan() the same
thing. The other document apps add the end of the provider's id. AAFMAA
has none. What its listing recorded as the id was the View control's
postback name, such as ctl00$Main$rptDocuments$ctl02$lnkViewDocument,
which names a row's place on whichever page of the table is showing, so
every document's ended in "cument". The second of two files was saved as
"... cument.pdf" and a third as "... cument (2).pdf", which says nothing
about which document is which, and a pattern's {number} wrote the
control's name into the file name.

What tells two of them apart now is the policy number. It is part of the
document's identity, the same on every run, and already in the summary
AAFMAA names a file by, so under the default pattern two files wanting one
name are of one policy, and the second is told apart by " (2)".

Each document is listed through the app's own listing, saved through its
own run and download_one with the page's part stood in for, and renamed
through its own main. Every title, policy, name and date is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import aafmaa_docs as app_mod
import aafmaa_site as site
from paperpull_core import storage as core_storage
from paperpull_core import testkit
from paperpull_core.models import State

DATE_TEXT = "6/15/2026"
NAMED_ALREADY = "Every file is already named the way this app names them."


def view_control(row: int) -> str:
    return "ctl00$Main$rptDocuments$ctl%02d$lnkViewDocument" % row


@pytest.fixture
def home(tmp_path, monkeypatch):
    # What loading a config sets in the core, put back after, so no other
    # test names files by this one's pattern.
    for name in ("_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    return tmp_path


def build(home: Path, pattern: str = ""):
    """The app as its own main builds it, with `pattern` as the File names
    page would save it."""
    config = {"filename_pattern": pattern} if pattern else {}
    return testkit.receipt_app(app_mod, home, default_start_date="", **config)


def listed(app, title: str, policy: str, insured: str, row: int):
    """One row of the documents table, as collect_document_index reads it,
    recorded by the app's own listing."""
    app._record_indexed_doc({
        "title": title, "documentDate": "2026-06-15", "displayDate": DATE_TEXT,
        "accountName": "%s %s" % (policy, insured), "documentId": view_control(row),
        "category": "",
    })
    found = [app_mod.Document.from_dict(r) for r in app.discovery.data.values()
             if r["title"] == title and r["account"].startswith(policy)]
    assert len(found) == 1
    return found[0]


def run(app, monkeypatch, docs):
    """The app's own run over `docs`. The page's part, finding the row and
    taking its PDF, hands over a PDF that prints the row's policy number,
    as AAFMAA's do."""
    def taken(page, title, date_text, account, out_path):
        Path(out_path).write_bytes(testkit.text_pdf(["Policy " + account.split()[0], title]))
        return True
    monkeypatch.setattr(site, "download_document_row", taken)
    monkeypatch.setattr(app, "_on_its_site", lambda: None)
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    app.process(docs)
    app.progress.save()
    app.discovery.save()
    saved = [app_mod.Document.from_dict(app.progress.get(d.key)) for d in docs]
    assert [d.state for d in saved] == [State.COMPLETED.value] * len(docs)
    return [Path(d.pdf_path) for d in saved]


def rename(home: Path, capsys, *flags) -> str:
    """The app's own Rename, as the panel presses it, and what it said."""
    capsys.readouterr()
    app_mod.main(["--config", str(home / "config.json"), "--rename", *flags])
    return " ".join(capsys.readouterr().out.split())


def test_two_policies_under_a_pattern_without_the_account_are_told_apart_by_policy(
        home, monkeypatch, capsys):
    """A pattern leaving out the summary gives one statement of each of two
    policies one name. The second is told apart by its own policy number,
    and Rename offers nothing for either."""
    app = build(home, "{date:yyyy-mm-dd} {provider} {kind}")
    docs = [listed(app, "Premium Statement", "5550001-1", "Dana Example", 1),
            listed(app, "Premium Statement", "5550002-1", "Dana Example", 2)]
    first, second = run(app, monkeypatch, docs)
    assert first.name == "2026-06-15 AAFMAA Statement.pdf"
    assert second.name == "2026-06-15 AAFMAA Statement 5550002-1.pdf"
    assert NAMED_ALREADY in rename(home, capsys)


def test_two_titles_of_one_summary_for_one_policy_are_told_apart_by_place(
        home, monkeypatch, capsys):
    """Under the default pattern the summary carries the policy and the
    insured, so two documents wanting one name are of one policy, two
    titles AAFMAA's rules give one summary. The policy is already in the
    name, so the second is told apart by " (2)", never by "cument"."""
    app = build(home)
    docs = [listed(app, "Premium Statement", "5550001-1", "Dana Example", 1),
            listed(app, "Premium Notice", "5550001-1", "Dana Example", 2)]
    first, second = run(app, monkeypatch, docs)
    assert first.name == "2026-06-15 AAFMAA Premium Statement 5550001-1 Dana Example.pdf"
    assert second.name == "2026-06-15 AAFMAA Premium Statement 5550001-1 Dana Example (2).pdf"
    assert NAMED_ALREADY in rename(home, capsys)


def test_a_pattern_naming_the_number_writes_no_control_name(home, monkeypatch):
    """AAFMAA gives no document a number, so a pattern's {number} is empty
    and its optional section drops out, as the File names page says for a
    field this provider never fills."""
    app = build(home, "{date:yyyy-mm-dd} {provider}[ {number}] {summary}")
    docs = [listed(app, "Premium Statement", "5550001-1", "Dana Example", 2)]
    path, = run(app, monkeypatch, docs)
    assert path.name == "2026-06-15 AAFMAA Premium Statement 5550001-1 Dana Example.pdf"
    for store in ("progress.json", "discovery.json"):
        text = (home / "out" / store).read_text(encoding="utf-8")
        assert "lnkViewDocument" not in text, store


def test_a_file_an_older_version_told_apart_by_cument_is_offered_its_name(
        home, monkeypatch, capsys):
    """An archive saved before this holds "... cument.pdf" and records that
    keep the postback name as an id. Rename offers the name a download
    gives that file today, and after it has nothing left to do. The
    records forget the postback name, so no pattern can write it."""
    app = build(home)
    docs = [listed(app, "Premium Statement", "5550001-1", "Dana Example", 1),
            listed(app, "Premium Notice", "5550001-1", "Dana Example", 2)]

    def as_it_was(*args, **kwargs):
        return core_storage.unique_path(*args, **{**kwargs, "distinguisher": "cument"})
    with monkeypatch.context() as before:
        before.setattr(app_mod, "unique_path", as_it_was)
        first, second = run(app, before, docs)
    assert second.name.endswith(" Dana Example cument.pdf")
    # The records as the version before this wrote them, the postback name
    # kept as the document's id.
    for name in ("progress.json", "discovery.json"):
        path = home / "out" / name
        data = json.loads(path.read_text(encoding="utf-8"))
        for row, record in enumerate(data.values(), 1):
            record["document_id"] = view_control(row)
        path.write_text(json.dumps(data), encoding="utf-8")

    said = rename(home, capsys)
    assert second.name in said and second.name.replace(" cument", " (2)") in said, said
    assert first.exists() and second.exists()
    said = rename(home, capsys, "--apply")
    assert not second.exists()
    assert second.with_name(second.name.replace(" cument", " (2)")).exists(), said
    assert first.exists()
    assert NAMED_ALREADY in rename(home, capsys)
    for name in ("progress.json", "discovery.json"):
        assert "lnkViewDocument" not in (home / "out" / name).read_text(encoding="utf-8")
