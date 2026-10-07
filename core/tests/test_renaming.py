"""Renaming files already downloaded, and the ledger that points at them.

A tester asked how to re-pull five receipts so they would take a better
name (#43). Nothing about those files needed fetching. These pin the
promises the rename makes, above all that it cannot lose a file and
cannot leave the ledger pointing at one that is gone.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import renaming, storage  # noqa: E402
from paperpull_core.storage import JsonStore  # noqa: E402

PATH = "PDF Full Path"
NAME = "PDF Filename"


def row(folder, name, **kw):
    p = Path(folder) / name
    p.write_bytes(b"%PDF-1.7 a file")
    r = {PATH: str(p), NAME: name, "Notes": ""}
    r.update(kw)
    return r


def by_order(r):
    """A naming scheme that puts the order number in, which is the whole
    point of the exercise."""
    return "2026-09-23 Testco %s Receipt.pdf" % r["order"]


# -- planning ----------------------------------------------------------------

def test_a_file_already_named_right_is_left_alone(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco A1 Receipt.pdf", order="A1")
    [change] = renaming.plan([r], by_order, folders=[tmp_path])
    assert not change.renaming
    assert change.reason == "already named that"


def test_running_it_twice_does_nothing_the_second_time(tmp_path):
    rows = [row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")]
    renaming.apply(renaming.plan(rows, by_order, folders=[tmp_path]))
    renaming.update_rows(rows, renaming.Result())
    rows[0][PATH] = str(tmp_path / "2026-09-23 Testco A1 Receipt.pdf")
    rows[0][NAME] = "2026-09-23 Testco A1 Receipt.pdf"
    assert not any(c.renaming for c in renaming.plan(rows, by_order, folders=[tmp_path]))


def test_a_record_whose_file_is_gone_is_reported_not_renamed(tmp_path):
    r = {PATH: str(tmp_path / "deleted.pdf"), NAME: "deleted.pdf", "order": "A1"}
    [change] = renaming.plan([r], by_order, folders=[tmp_path])
    assert not change.renaming
    assert "not on disk" in change.reason


def test_a_row_too_thin_to_name_does_not_stop_the_rest(tmp_path):
    good = row(tmp_path, "one.pdf", order="A1")
    bad = row(tmp_path, "two.pdf")           # no order at all

    def build(r):
        return by_order(r)                    # raises KeyError on the second

    changes = renaming.plan([good, bad], build, folders=[tmp_path])
    assert changes[0].renaming
    assert not changes[1].renaming and "could not work out a name" in changes[1].reason


# -- doing it ----------------------------------------------------------------

def test_the_file_is_renamed_and_nothing_else_moves(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    result = renaming.apply(renaming.plan([r], by_order, folders=[tmp_path]))
    assert result.renamed == 1
    assert (tmp_path / "2026-09-23 Testco A1 Receipt.pdf").exists()
    assert not (tmp_path / "2026-09-23 Testco Widget Receipt.pdf").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-23 Testco A1 Receipt.pdf"]


def test_two_files_that_want_each_others_names_both_land(tmp_path):
    """A straight rename would refuse or overwrite depending on the
    platform, and one of the two would be gone."""
    a = row(tmp_path, "2026-09-23 Testco A2 Receipt.pdf", order="A1")
    b = row(tmp_path, "2026-09-23 Testco A1 Receipt.pdf", order="A2")
    (tmp_path / a[NAME]).write_bytes(b"%PDF-A")
    (tmp_path / b[NAME]).write_bytes(b"%PDF-B")
    result = renaming.apply(renaming.plan([a, b], by_order, folders=[tmp_path]))
    assert result.renamed == 2
    assert (tmp_path / "2026-09-23 Testco A1 Receipt.pdf").read_bytes() == b"%PDF-A"
    assert (tmp_path / "2026-09-23 Testco A2 Receipt.pdf").read_bytes() == b"%PDF-B"
    assert not list(tmp_path.glob("*.renaming*"))


def test_a_file_that_is_not_in_the_ledger_is_never_touched(tmp_path):
    (tmp_path / "somebody elses file.pdf").write_bytes(b"%PDF-")
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    renaming.apply(renaming.plan([r], by_order, folders=[tmp_path]))
    assert (tmp_path / "somebody elses file.pdf").exists()


def test_only_a_pdf_in_a_folder_the_app_files_in_is_renamed(tmp_path, monkeypatch):
    """A ledger can name anything. Of nine rows, the one naming a PDF in the
    folder the app files documents in is renamed. Six name that folder, the
    folder holding it, a file outside it, one reached by climbing out of it
    through "..", a file in it that is not a PDF, and ".", and each is left
    out as one the app does not hold, nothing of it touched. One names a
    file no longer on disk and one names nothing, which are left out as
    before."""
    filed, elsewhere, here = tmp_path / "Statements", tmp_path / "elsewhere", tmp_path / "here"
    for folder in (filed, elsewhere, here):
        folder.mkdir()
    monkeypatch.chdir(here)
    held = row(filed, "held.pdf", order="A1")
    outside = row(elsewhere, "outside.pdf", order="A2")
    rows = [held, outside,
            {PATH: str(filed / ".." / "elsewhere" / "outside.pdf"), NAME: "outside.pdf",
             "order": "A3"},
            {PATH: str(filed), NAME: filed.name, "order": "A4"},
            {PATH: str(tmp_path), NAME: tmp_path.name, "order": "A5"},
            row(filed, "notes.txt", order="A6"),
            {PATH: ".", NAME: "", "order": "A7"},
            {PATH: str(filed / "gone.pdf"), NAME: "gone.pdf", "order": "A8"},
            {PATH: "", NAME: "", "order": "A9"}]
    before = {p: p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")}

    changes = renaming.plan(rows, by_order, folders=[filed])

    assert [c.reason for c in changes] == ["", *[renaming.NOT_HELD] * 6,
                                           "not on disk, so only the record would change"]
    result = renaming.apply(changes)
    assert result.renamed == 1
    after = {p: p.read_bytes() if p.is_file() else None for p in tmp_path.rglob("*")}
    assert after.pop(filed / "2026-09-23 Testco A1 Receipt.pdf") == before.pop(filed / "held.pdf")
    assert after == before


def test_a_pdf_left_under_the_name_it_was_delivered_to_is_finished(tmp_path):
    """Robinhood records a tax form under the name it was written to beside
    its place, ".pdf.delivering", when moving it into place fails, for
    Rename to finish."""
    filed = tmp_path / "Tax Documents"
    filed.mkdir()
    staged = row(filed, "2021-12-31 Testco Form.pdf.delivering", order="A1")
    result = renaming.apply(renaming.plan([staged], by_order, folders=[filed]))
    assert result.renamed == 1
    assert sorted(p.name for p in filed.iterdir()) == ["2026-09-23 Testco A1 Receipt.pdf"]


def test_a_row_left_alone_keeps_its_name_when_a_file_renamed_had_it(tmp_path):
    """An index copied from another folder, a row and a record there naming
    a file of the same name as one renamed here. They name a file nobody
    renamed, so they keep the name it still has."""
    filed, elsewhere = tmp_path / "Statements", tmp_path / "elsewhere"
    filed.mkdir()
    elsewhere.mkdir()
    held = row(filed, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    other = row(elsewhere, "2026-09-23 Testco Widget Receipt.pdf", order="A2")
    store = _Store({"A1": {"pdf_path": held[PATH], "pdf_filename": held[NAME]},
                    "A2": {"pdf_path": other[PATH], "pdf_filename": other[NAME]}})
    rows = [held, dict(other)]
    result = renaming.apply(renaming.plan(rows, by_order, folders=[filed]))
    assert result.renamed == 1
    assert renaming.update_rows(rows, result, note="renamed") == 1
    assert renaming.update_progress(store, result) == 1
    assert rows[1] == other
    assert store.data["A2"] == {"pdf_path": other[PATH], "pdf_filename": other[NAME]}
    assert rows[0][NAME] == store.data["A1"]["pdf_filename"] == "2026-09-23 Testco A1 Receipt.pdf"


def test_two_files_of_one_name_in_two_folders_each_keep_their_own_new_name(tmp_path):
    """An online and an in-store receipt of one day and one summary. Each row
    and each record names its own file afterwards, where both used to take
    whichever new name came last."""
    online, instore = tmp_path / "Online", tmp_path / "In-Store"
    online.mkdir()
    instore.mkdir()
    a = row(online, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    b = row(instore, "2026-09-23 Testco Widget Receipt.pdf", order="A2")
    store = _Store({"A1": {"pdf_path": a[PATH], "pdf_filename": a[NAME]},
                    "A2": {"pdf_path": b[PATH], "pdf_filename": b[NAME]}})
    rows = [a, b]
    result = renaming.apply(renaming.plan(rows, by_order, folders=[online, instore]))
    assert result.renamed == 2
    renaming.update_rows(rows, result)
    renaming.update_progress(store, result)
    for r in rows:
        assert Path(r[PATH]).name == r[NAME] and Path(r[PATH]).is_file(), r
    assert [Path(r[PATH]).parent for r in rows] == [online, instore]
    for rec in store.data.values():
        assert Path(rec["pdf_path"]).name == rec["pdf_filename"], rec


def test_the_plan_says_how_many_rows_it_left_alone(tmp_path):
    """Said once, after the files to be renamed, so a person whose index
    names files somewhere else learns why they were not offered."""
    filed = tmp_path / "Statements"
    filed.mkdir()
    rows = [row(filed, "held.pdf", order="A1"), row(tmp_path, "outside.pdf", order="A2"),
            row(tmp_path, "also outside.pdf", order="A3")]
    said = []
    renaming.describe(renaming.plan(rows, by_order, folders=[filed]), say=said.append)
    assert said == ["1 file(s) would be renamed.", "  held.pdf",
                    "    -> 2026-09-23 Testco A1 Receipt.pdf",
                    "2 row(s) of the index name something other than a PDF in this app's "
                    "folders, so they are left alone."]
    said.clear()
    renaming.describe(renaming.plan(rows[1:], by_order, folders=[filed]), say=said.append)
    assert said == ["Every file is already named the way this app names them.",
                    "2 row(s) of the index name something other than a PDF in this app's "
                    "folders, so they are left alone."]


def test_a_link_in_a_folder_the_app_files_in_is_not_renamed(tmp_path):
    """A rename would move the link and leave the file it leads to as it
    was, and the app made neither."""
    filed = tmp_path / "Statements"
    filed.mkdir()
    target = row(filed, "held.pdf", order="A1")
    link = filed / "linked.pdf"
    try:
        link.symlink_to(Path(target[PATH]))
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("this system does not let a test make a link")
    changes = renaming.plan([{PATH: str(link), NAME: link.name, "order": "A2"}], by_order,
                            folders=[filed])
    assert [c.reason for c in changes] == [renaming.NOT_HELD]
    assert renaming.held_document(target[PATH], [filed]) == Path(target[PATH])


def test_two_records_wanting_one_name_do_not_become_one_file(tmp_path):
    a = row(tmp_path, "first.pdf", order="A1")
    b = row(tmp_path, "second.pdf", order="A1")   # the same name, somehow
    result = renaming.apply(renaming.plan([a, b], by_order, folders=[tmp_path]))
    assert result.renamed == 2
    assert len(list(tmp_path.iterdir())) == 2, "neither file was written over"


def test_nothing_happens_until_apply_is_called(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    renaming.plan([r], by_order, folders=[tmp_path])
    assert (tmp_path / "2026-09-23 Testco Widget Receipt.pdf").exists()


# -- the ledger --------------------------------------------------------------

def test_the_index_is_pointed_at_the_file_as_it_is_now_called(tmp_path):
    """Verify reads the full path out of the index, so a rename that
    skipped this would report every file on disk as missing."""
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    result = renaming.apply(renaming.plan([r], by_order, folders=[tmp_path]))
    assert renaming.update_rows([r], result, note="renamed") == 1
    assert r[NAME] == "2026-09-23 Testco A1 Receipt.pdf"
    assert Path(r[PATH]).exists()
    assert "renamed" in r["Notes"]


def test_a_second_csv_carrying_only_the_name_is_updated_too(tmp_path):
    """A receipt app writes the order history as well as the index, and
    that one has no full path column."""
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    history = {NAME: "2026-09-23 Testco Widget Receipt.pdf", "Notes": ""}
    result = renaming.apply(renaming.plan([r], by_order, folders=[tmp_path]))
    assert renaming.update_rows([history], result) == 1
    assert history[NAME] == "2026-09-23 Testco A1 Receipt.pdf"


def test_the_run_state_follows_and_its_key_never_changes(tmp_path):
    store = JsonStore(tmp_path / "progress.json", tmp_path / "Backups")
    store.load()
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    store.update("Online:A1", {"pdf_filename": r[NAME], "pdf_path": r[PATH],
                               "downloaded_ok": True})
    result = renaming.apply(renaming.plan([r], by_order, folders=[tmp_path]))
    assert renaming.update_progress(store, result) == 1
    rec = store.get("Online:A1")
    assert rec["pdf_filename"] == "2026-09-23 Testco A1 Receipt.pdf"
    assert Path(rec["pdf_path"]).exists()
    assert rec["downloaded_ok"] is True, "what stops a second download is untouched"
    assert list(store.data) == ["Online:A1"], "the identity is the key and it did not move"


def test_an_untouched_row_is_not_rewritten(tmp_path):
    r = {PATH: "", NAME: "", "Notes": "keep me"}
    assert renaming.update_rows([r], renaming.Result(), note="renamed") == 0
    assert r["Notes"] == "keep me"


# -- the index says what it was called, not what it is called now (#26) -------

class _Store:
    def __init__(self, data):
        self.data = data

    def update(self, key, patch, save=True):
        self.data.setdefault(key, {}).update(patch)

    def save(self, backup=False):
        pass


class _Paths:
    """The one folder the stand-in app files in."""

    def __init__(self, folder):
        self.folder = folder

    def filing_folders(self):
        return [self.folder]


class _App:
    """Enough of an app for run_for, with the two ledgers it reads."""

    def __init__(self, tmp_path, rows, discovery=None, progress=None):
        self.config = {"max_path_length": 240}
        self.paths = _Paths(tmp_path)
        self.index_csv = _Csv(tmp_path / "index.csv", rows)
        self.order_csv = None
        self.discovery = _Store(discovery or {})
        self.progress = _Store(progress or {})


class _Csv:
    columns = ["PDF Filename", "PDF Full Path", "Document Date",
               "Document Summary", "Document Title", "Notes"]

    def __init__(self, path, rows):
        self.path = path
        self._rows = rows
        self.rewritten = None

    def read_all(self):
        return self._rows

    def rewrite(self, rows):
        self.rewritten = rows


def test_a_summary_the_app_has_since_improved_is_what_the_file_is_named_for(tmp_path):
    """His bills were discovered before the app could read which account
    they belonged to. Discovery learned it, the index kept the old
    summary, and Rename preview said everything was already named
    correctly while every filename plainly lacked the account."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from paperpull_core.storage import set_filename_owner
    set_filename_owner("")

    name = "2026-09-05 Testco Monthly Statement.pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF-")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f),
             "Document Date": "2026-09-05",
             "Document Summary": "Monthly Statement",
             "Document Title": "Monthly Statement - September 5, 2026",
             "Notes": ""}]
    app = _App(tmp_path, rows, discovery={
        "Statement:2026-09-05:Monthly Statement - September 5, 2026:": {
            "date": "2026-09-05",
            "title": "Monthly Statement - September 5, 2026",
            "summary": "Internet Monthly Statement"}})

    said = []
    renaming.run_for(app, apply_changes=False, say=said.append)
    text = " ".join(said)
    assert "already named" not in text, text
    assert "Internet Monthly Statement" in text

    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert (tmp_path / "2026-09-05 Testco Internet Monthly Statement.pdf").exists()
    assert not f.exists()
    assert rows[0]["PDF Filename"] == "2026-09-05 Testco Internet Monthly Statement.pdf"


def test_the_index_is_still_used_when_the_app_knows_nothing_better(tmp_path):
    from paperpull_core.storage import set_filename_owner
    set_filename_owner("")
    name = "wrong.pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF-")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f),
             "Document Date": "2026-09-05", "Document Summary": "Monthly Statement",
             "Document Title": "t", "Notes": ""}]
    app = _App(tmp_path, rows)
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert (tmp_path / "2026-09-05 Testco Monthly Statement.pdf").exists()


# -- a rename names a file the way a download would (#50) ---------------------

def test_a_pattern_field_from_the_record_reaches_the_rename(tmp_path, monkeypatch):
    """Rename used to build a name from the row's date, summary and type
    alone, so a pattern naming files for their order number renamed every
    file without it while new downloads carried it."""
    from paperpull_core import storage
    storage.set_filename_owner("")
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {number}")
    name = "2026-09-05 Testco Order.pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF-")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f),
             "Document Date": "2026-09-05", "Document Summary": "Order",
             "Document Title": "", "Order or Receipt Number": "A-77", "Notes": ""}]
    app = _App(tmp_path, rows, progress={"A-77": {
        "order_number": "A-77", "purchase_date": "2026-09-05", "summary": "Order"}})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert (tmp_path / "2026-09-05 Testco A-77.pdf").exists()


def test_a_document_known_by_its_id_finds_its_record(tmp_path):
    """A row keyed by Document ID and a record keyed the same way are one
    document. They used to be keyed differently, so the record was never
    found and the improved summary never reached the file."""
    from paperpull_core.storage import set_filename_owner
    set_filename_owner("")
    name = "2026-09-05 Testco Letter.pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF-")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f),
             "Document Date": "2026-09-05", "Document Summary": "Letter",
             "Document Title": "Letter", "Document ID": "D9", "Notes": ""}]
    app = _App(tmp_path, rows, discovery={"D9": {
        "document_id": "D9", "date": "2026-09-05", "title": "Letter",
        "summary": "Annual Letter"}})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert (tmp_path / "2026-09-05 Testco Annual Letter.pdf").exists()


def test_the_first_of_a_split_order_keeps_its_part(tmp_path):
    from paperpull_core.storage import set_filename_owner
    set_filename_owner("")
    name = "2026-09-05 Testco Order (1 of 3).pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF-")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f),
             "Document Date": "2026-09-05", "Document Summary": "Order",
             "Document Title": "", "Notes": ""}]
    said = []
    renaming.run_for(_App(tmp_path, rows), apply_changes=False, say=said.append)
    assert "already named" in " ".join(said), said


def test_a_file_already_told_apart_by_its_number_stays_put(tmp_path):
    """Two returns on one day with one summary. The second was saved with its
    number in the name, and Rename used to push it on to " (2)" because its
    own name counted as taken."""
    first = row(tmp_path, "2022-08-10 Testco Return.pdf", order="A1")
    second = row(tmp_path, "2022-08-10 Testco Return A2.pdf", order="A2")
    changes = renaming.plan([first, second], lambda r: "2022-08-10 Testco Return.pdf",
                            folders=[tmp_path], distinguisher=lambda r: r["order"])
    assert [c.renaming for c in changes] == [False, False], [(c.old_name, c.new_name, c.reason) for c in changes]


def test_unique_path_can_leave_a_files_own_name_free(tmp_path):
    from paperpull_core.storage import unique_path
    (tmp_path / "a.pdf").write_bytes(b"x")
    assert unique_path(tmp_path, "a.pdf").name == "a (2).pdf"
    assert unique_path(tmp_path, "a.pdf", ignoring="a.pdf").name == "a.pdf"


# -- which record a row is (the release review of 0.44.0) ---------------------

TITLE = "Account Statement - September 12, 2026"
KEY = "Statement:2026-09-12:" + TITLE + ":%s"


def _bill(tmp_path, account):
    """One bill's statement of 2026-09-12 as American Family keeps it, with
    the bill's account part in its summary, key and account and never in
    its title. Its file, its index row, and the record a download leaves."""
    name = "2026-09-12 Testco Billing Statement %s.pdf" % account
    f = tmp_path / name
    f.write_bytes(b"%PDF- the bill " + account.encode())
    summary = "Billing Statement %s" % account
    row = {"PDF Filename": name, "PDF Full Path": str(f), "Document Date": "2026-09-12",
           "Document Summary": summary, "Document Title": TITLE, "Notes": ""}
    rec = {"date": "2026-09-12", "title": TITLE, "account": account, "summary": summary,
           "pdf_path": str(f), "pdf_filename": name}
    return row, rec


def _listed(rec):
    """The same record as discovery keeps it, which names no file."""
    return dict(rec, pdf_path="", pdf_filename="")


def _names(tmp_path):
    """Each file's name, by the bill its bytes are."""
    return {p.read_bytes()[-4:].decode(): p.name for p in tmp_path.glob("*.pdf")}


@pytest.fixture
def by_account(monkeypatch):
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {account} {summary}")


def test_two_bills_of_one_day_are_each_named_for_their_own_record(tmp_path, by_account):
    """The reviewer's case. Both statements have one date and one title,
    and the record they were merged into gave the first bill's file the
    second bill's account and a " (2)"."""
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    app = _App(tmp_path, [row1, row2],
               progress={KEY % "1111": rec1, KEY % "2222": rec2},
               discovery={KEY % "1111": _listed(rec1), KEY % "2222": _listed(rec2)})
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    assert _names(tmp_path) == {
        "1111": "2026-09-12 Testco 1111 Billing Statement 1111.pdf",
        "2222": "2026-09-12 Testco 2222 Billing Statement 2222.pdf"}, said
    assert app.progress.data[KEY % "1111"]["pdf_path"] == str(
        tmp_path / "2026-09-12 Testco 1111 Billing Statement 1111.pdf")


def test_a_bill_whose_record_is_gone_is_never_named_for_another(tmp_path, by_account):
    """Only the second bill's record is left, and it names its own file. The
    first bill's file is named from its own row, a name that lacks what its
    record would have added and never says the other bill's account."""
    (row1, _rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    app = _App(tmp_path, [row1, row2], progress={KEY % "2222": rec2})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert _names(tmp_path) == {
        "1111": "2026-09-12 Testco Billing Statement 1111.pdf",
        "2222": "2026-09-12 Testco 2222 Billing Statement 2222.pdf"}


def test_two_bills_only_listed_are_not_told_apart_by_date_and_title(tmp_path, by_account):
    """Records that name no file, as discovery keeps a document it listed.
    A date and a title cannot say which bill a row is, so neither file is
    named for either record."""
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    app = _App(tmp_path, [row1, row2],
               discovery={KEY % "1111": _listed(rec1), KEY % "2222": _listed(rec2)})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert _names(tmp_path) == {
        "1111": "2026-09-12 Testco Billing Statement 1111.pdf",
        "2222": "2026-09-12 Testco Billing Statement 2222.pdf"}


SPELLINGS = [
    pytest.param(lambda f: f.name, id="relative to where the app runs"),
    pytest.param(lambda f: str(f).upper(), id="in another case",
                 marks=pytest.mark.skipif(not (os.name == "nt" or sys.platform == "darwin"),
                                          reason="case counts in a path here")),
]


@pytest.mark.parametrize("spelled", SPELLINGS)
def test_a_record_with_its_file_spelled_another_way_is_still_its_files(tmp_path, monkeypatch,
                                                                         by_account, spelled):
    """And the record follows its file, so the next Rename has nothing to
    do. A record left with the old spelling named the file back from its
    row on the next Rename and forward again on the one after."""
    monkeypatch.chdir(tmp_path)
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    rec1["pdf_path"] = spelled(tmp_path / rec1["pdf_filename"])
    app = _App(tmp_path, [row1, row2], progress={KEY % "1111": rec1, KEY % "2222": rec2})
    renamed = {"1111": "2026-09-12 Testco 1111 Billing Statement 1111.pdf",
               "2222": "2026-09-12 Testco 2222 Billing Statement 2222.pdf"}
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert _names(tmp_path) == renamed
    assert app.progress.data[KEY % "1111"]["pdf_path"] == str(tmp_path / renamed["1111"])
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    assert _names(tmp_path) == renamed
    assert "already named" in " ".join(said), said


def test_where_case_is_ignored_one_file_has_one_spelling(tmp_path):
    a = renaming._same_file(str(tmp_path / "Statements" / "A Bill.pdf"))
    b = renaming._same_file(str(tmp_path / "STATEMENTS" / "a bill.PDF"))
    assert (a == b) == (os.name == "nt" or sys.platform == "darwin")


def test_a_bill_taken_again_beside_one_that_failed_keeps_its_own_account(tmp_path,
                                                                           by_account):
    """Download again took a second copy of the first bill, so its record
    names that copy, and failed on the second bill, so that record names
    no file. Neither record is lent by date and title, since the first
    copy would have been named for the other bill."""
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    again = tmp_path / "2026-09-12 Testco Billing Statement 1111 (2).pdf"
    again.write_bytes(b"%PDF- again 1111")
    rec1.update(pdf_path=str(again), pdf_filename=again.name)
    row1_again = dict(row1, **{"PDF Filename": again.name, "PDF Full Path": str(again)})
    app = _App(tmp_path, [row1, row2, row1_again],
               progress={KEY % "1111": rec1, KEY % "2222": _listed(rec2)})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    names = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert names == ["2026-09-12 Testco 1111 Billing Statement 1111.pdf",
                     "2026-09-12 Testco Billing Statement 1111.pdf",
                     "2026-09-12 Testco Billing Statement 2222.pdf"], names
    assert (tmp_path / "2026-09-12 Testco 1111 Billing Statement 1111.pdf").read_bytes() == (
        b"%PDF- again 1111")


def test_a_document_kept_by_an_id_counts_among_its_date_and_title(tmp_path, by_account):
    """The first bill is kept by an id and its record names its second copy.
    The second bill, of the same date and title, was only listed and has no
    id. A record kept by an id was not counted among the documents of its
    date and title, so the first copy was named for the second bill."""
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    (tmp_path / row2["PDF Filename"]).unlink()
    again = tmp_path / "2026-09-12 Testco Billing Statement 1111 (2).pdf"
    again.write_bytes(b"%PDF- again 1111")
    rec1.update(document_id="DOC1111", pdf_path=str(again), pdf_filename=again.name)
    row1_again = dict(row1, **{"PDF Filename": again.name, "PDF Full Path": str(again)})
    app = _App(tmp_path, [row1, row1_again], progress={"id:DOC1111": rec1},
               discovery={KEY % "2222": _listed(rec2)})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == [
        "2026-09-12 Testco 1111 Billing Statement 1111.pdf",
        "2026-09-12 Testco Billing Statement 1111.pdf"]


RECEIPT = "2026-09-05 Testco Household Goods Receipt.pdf"


def _receipt_rows_and_records(f, *numbers):
    rows = [{"PDF Filename": f.name, "PDF Full Path": str(f), "Purchase Date": "2026-09-05",
             "Purchase Summary": "Household Goods", "Order or Receipt Number": n,
             "Notes": ""} for n in numbers]
    records = {"In-Store:%s" % n: {"order_number": n, "purchase_date": "2026-09-05",
                                   "summary": "Household Goods", "pdf_path": str(f),
                                   "pdf_filename": f.name} for n in numbers}
    return rows, records


def test_a_file_two_purchases_rows_give_it_to_keeps_its_name(tmp_path, monkeypatch):
    """Purchase 1001's file was deleted after it was imported elsewhere, and
    purchase 1002 of that day and summary was saved under the name it
    freed. The index has a row for each naming the one file, and both
    records name it. The file holds 1002's receipt and was named for 1001.
    Whose file it is cannot be told from the ledger, so it keeps its name."""
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {number} {summary}")
    f = tmp_path / RECEIPT
    f.write_bytes(b"%PDF- the receipt of 1002")
    rows, records = _receipt_rows_and_records(f, "1001", "1002")
    renaming.run_for(_App(tmp_path, rows, progress=records), apply_changes=True,
                     say=lambda *a: None)
    assert [p.name for p in tmp_path.glob("*.pdf")] == [RECEIPT]


def test_a_file_whose_record_has_another_order_number_keeps_its_name(tmp_path, monkeypatch):
    """The same, after purchase 1001's row was taken out of the index and
    1002's record lost. The one record naming the file is another
    purchase's than its row says."""
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {number} {summary}")
    f = tmp_path / RECEIPT
    f.write_bytes(b"%PDF- the receipt of 1002")
    rows, _records = _receipt_rows_and_records(f, "1002")
    _rows, records = _receipt_rows_and_records(f, "1001")
    renaming.run_for(_App(tmp_path, rows, progress=records), apply_changes=True,
                     say=lambda *a: None)
    assert [p.name for p in tmp_path.glob("*.pdf")] == [RECEIPT]


def _bills_whose_names_read_alike(folder, first, second):
    """Two bills of one day, the first for account 1111 and the second for
    none, whose files' names read alike, each with its row and record."""
    rows, records = [], {}
    for account, summary in (("1111", first), ("", second)):
        f = folder / ("2026-09-12 Testco %s.pdf" % summary)
        f.write_bytes(b"%PDF- " + summary.encode())
        rows.append({"PDF Filename": f.name, "PDF Full Path": str(f),
                     "Document Date": "2026-09-12", "Document Summary": summary,
                     "Document Title": TITLE, "Notes": ""})
        records[KEY % summary] = {"date": "2026-09-12", "title": TITLE, "account": account,
                                  "summary": summary, "pdf_path": str(f),
                                  "pdf_filename": f.name}
    return rows, records


def _each_follows_its_own_file(folder, first, second):
    rows, records = _bills_whose_names_read_alike(folder, first, second)
    app = _App(folder, rows, progress=records)
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    files = {p.read_bytes(): p.name for p in folder.glob("*.pdf")}
    assert files == {b"%PDF- " + first.encode(): "2026-09-12 Testco 1111 %s.pdf" % first,
                     b"%PDF- " + second.encode(): "2026-09-12 Testco %s.pdf" % second}, files
    for row in rows:
        assert Path(row["PDF Full Path"]).read_bytes() == b"%PDF- " + row[
            "Document Summary"].encode(), row
    for rec in records.values():
        assert Path(rec["pdf_path"]).read_bytes() == b"%PDF- " + rec["summary"].encode(), rec
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    assert "already named" in " ".join(said), said


def _a_folder_that_tells_case_apart(tmp_path):
    """A folder with Windows' case sensitive attribute, or None where one
    cannot be made here."""
    folder = tmp_path / "case"
    folder.mkdir()
    if os.name != "nt":
        return None
    import subprocess
    try:
        done = subprocess.run(["fsutil.exe", "file", "setCaseSensitiveInfo", str(folder),
                               "enable"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    (folder / "a").write_bytes(b"a")
    tells = done.returncode == 0 and not (folder / "A").exists()
    (folder / "a").unlink()
    return folder if tells else None


def test_two_files_whose_names_differ_in_case_each_keep_their_row(tmp_path, by_account):
    """In a folder that tells case apart, two names that differ only in case
    are two files. After the first was renamed, the second's row and record
    were pointed at the first's new name, since the two spellings read
    alike, and nothing pointed at the second file any more."""
    folder = _a_folder_that_tells_case_apart(tmp_path)
    if folder is None:
        pytest.skip("no folder that tells case apart can be made here")
    _each_follows_its_own_file(folder, "ACME Statement", "Acme Statement")


def test_two_files_that_read_alike_each_keep_their_row(tmp_path, monkeypatch, by_account):
    """The same in any folder, with two names made to read alike as two
    names differing only in case do in such a folder."""
    real = renaming._same_file
    monkeypatch.setattr(renaming, "_same_file", lambda raw: real(raw.replace("South", "North")))
    _each_follows_its_own_file(tmp_path, "North Statement", "South Statement")


def test_a_file_two_bills_records_name_is_named_from_its_row(tmp_path, by_account):
    """Both bills' records name the one file. They cannot both be right,
    and the date and title say nothing about which is, so the file is named
    from its row and for neither record."""
    (row1, rec1), (row2, rec2) = _bill(tmp_path, "1111"), _bill(tmp_path, "2222")
    (tmp_path / row2["PDF Filename"]).unlink()
    rec2.update(pdf_path=rec1["pdf_path"], pdf_filename=rec1["pdf_filename"])
    app = _App(tmp_path, [row1], progress={KEY % "1111": rec1, KEY % "2222": rec2})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert _names(tmp_path) == {"1111": "2026-09-12 Testco Billing Statement 1111.pdf"}


def test_a_copy_dated_as_its_row_is_the_record_the_row_takes(tmp_path, monkeypatch):
    """Robinhood and Newrez show Rename a copy of a record dated as its row
    now is, beside the record itself, both naming the one file. The copy is
    the one the row's own date and title name."""
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {summary}")
    name = "0000-00-00 Testco Form 1099.pdf"
    f = tmp_path / name
    f.write_bytes(b"%PDF- form")
    rows = [{"PDF Filename": name, "PDF Full Path": str(f), "Document Date": "2025-12-31",
             "Document Summary": "Form 1099", "Document Title": "Form 1099", "Notes": ""}]
    undated = {"date": "", "title": "Form 1099", "summary": "Form 1099",
               "pdf_path": str(f), "pdf_filename": name}
    copy = dict(undated, date="2025-12-31", summary="Form 1099 Tax Year 2025")
    app = _App(tmp_path, rows, progress={"Tax Document::Form 1099:": undated},
               discovery={"dated by form:2025-12-31:Form 1099": copy})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert [p.name for p in tmp_path.glob("*.pdf")] == [
        "2025-12-31 Testco Form 1099 Tax Year 2025.pdf"]


def test_every_file_of_one_order_takes_the_orders_record(tmp_path, monkeypatch):
    """An order number names one purchase whichever of its files a row is,
    as when an order was downloaded again beside its first copy and the
    record names the second."""
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "{date} {provider} {number}")
    rows = []
    for name in ("2026-09-05 Testco Order.pdf", "2026-09-05 Testco Order A-77.pdf"):
        f = tmp_path / name
        f.write_bytes(b"%PDF- " + name.encode())
        rows.append({"PDF Filename": name, "PDF Full Path": str(f),
                     "Document Date": "2026-09-05", "Document Summary": "Order",
                     "Document Title": "", "Order or Receipt Number": "A-77", "Notes": ""})
    app = _App(tmp_path, rows, progress={"Online:A-77": {
        "order_number": "A-77", "purchase_date": "2026-09-05", "summary": "Order",
        "pdf_path": rows[1]["PDF Full Path"], "pdf_filename": rows[1]["PDF Filename"]}})
    renaming.run_for(app, apply_changes=True, say=lambda *a: None)
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == [
        "2026-09-05 Testco A-77 (2).pdf", "2026-09-05 Testco A-77.pdf"]
