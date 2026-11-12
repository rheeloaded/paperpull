"""A documents folder for each account (#102).

An account's config can name documents_dir, a folder of its own that a
program such as Paperless may watch. A download is written and checked in
output_dir as it always was, and one that fails its check is put aside in
Manual Review beside it, on the same drive. Only a document saved and
checked is moved into the same folder of its kind in the documents folder,
by the app's own Rename, which the control panel runs once each download
run has ended for what that run saved, and for what was saved before when
the person asks. Manual Review, Logs, Diagnostics, Backups, the index,
the order history, progress.json and discovery.json never move. Every path
a run writes to is what it always was, the setting or not.

Setting it moves nothing. Files saved before stay where they are, where
Rename, Review Names and every check of a file the app holds still find
them. The Move keeps every rule a rename keeps, copies to another drive or
share where a rename cannot go, never leaves two copies, and puts every
file back when a ledger cannot be written. Each documents folder it filled
is written down, so its documents are still found after the setting
changes or is cleared.

On PaperPull Server a documents_dir is held inside the data folder, where
its links lead, as output_dir is.

Every folder is a throwaway one under tmp_path, and every name and account
is invented.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import renaming, storage  # noqa: E402
from paperpull_core.storage import Paths  # noqa: E402
from test_naming_folders import link_folder  # noqa: E402

DATE = "2026-09-12"
ACCOUNTS = ("Checking 1111", "Savings 2222")


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def write(folder: Path, settings: dict, name: str = "config.json") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


# -- where everything goes ---------------------------------------------------------------

def old_layout(out: Path) -> dict:
    """Every path Paths gave before documents_dir existed, for the bound
    spec, written out the way it was built."""
    sp = storage.spec()
    paths = {f.attr: out / f.name for f in sp.folders}
    paths.update({c.attr: out / c.filename.format(provider=sp.provider) for c in sp.csv_files})
    paths.update(progress_json=out / "progress.json", discovery_json=out / "discovery.json",
                 last_listing=out / "last-listing.json", run_summary=out / "run-summary.txt")
    return paths


OLD_FILING = ("Statements", "Other Documents", "Manual Review")


@pytest.mark.parametrize("documents", [False, True])
def test_every_path_is_where_it_always_was_with_a_documents_folder_or_without(
        tmp_path, documents):
    """A download is written and checked in the output folder whatever the
    setting says, and one that fails its check is put aside beside it."""
    out, docs = tmp_path / "out", tmp_path / "Watched"
    paths = Paths(out, documents_dir=str(docs) if documents else "")
    for attr, path in old_layout(out).items():
        assert getattr(paths, attr) == path, attr
    assert paths.folder_for("Statement") == out / "Statements"
    assert paths.all_dirs() == [out] + [out / f.name for f in storage.spec().folders
                                         if f.precreate]
    if not documents:
        assert paths.documents == out and paths.documents_moves() == {}
        assert paths.filing_folders() == [out / name for name in OLD_FILING]
        return
    assert paths.documents == docs
    assert paths.documents_moves() == {out / "Statements": docs / "Statements",
                                       out / "Other Documents": docs / "Other Documents"}
    assert paths.filing_folders() == [out / name for name in OLD_FILING] + [
        docs / "Statements", docs / "Other Documents"]


def test_a_run_writes_nothing_in_the_documents_folder(tmp_path):
    out, docs = tmp_path / "out", tmp_path / "Watched"
    Paths(out, documents_dir=str(docs)).ensure()
    assert not docs.exists()
    assert sorted(p.name for p in out.iterdir()) == [
        "Backups", "Diagnostics", "Logs", "Manual Review", "Statements"]


def test_the_documents_folder_is_the_output_folder_spelled_another_way(tmp_path):
    out = tmp_path / "out"
    paths = Paths(out, documents_dir=str(out / "." / ""))
    assert paths.documents_moves() == {}
    assert paths.filing_folders() == [out / name for name in OLD_FILING]


# -- the setting, as load_config reads it -------------------------------------------------

def test_a_documents_folder_reaches_the_paths_every_app_builds(tmp_path, capsys):
    out, docs = tmp_path / "out", tmp_path / "Watched"
    cfg = storage.load_config(write(tmp_path / "app", {"output_dir": str(out),
                                                       "documents_dir": str(docs)}))
    assert cfg["documents_dir"] == str(docs)
    paths = Paths(Path(cfg["output_dir"]))
    assert paths.documents == docs and paths.statements == out / "Statements"
    assert capsys.readouterr().out == ""


def test_no_documents_folder_adds_nothing_to_a_config(tmp_path):
    out = tmp_path / "out"
    cfg = storage.load_config(write(tmp_path / "app", {"output_dir": str(out)}))
    assert "documents_dir" not in cfg
    assert Paths(Path(cfg["output_dir"])).documents == out


def test_each_account_has_its_own_documents_folder(tmp_path):
    app = tmp_path / "app"
    first, second = tmp_path / "first", tmp_path / "second"
    storage.load_config(write(app, {"output_dir": str(first),
                                    "documents_dir": str(tmp_path / "Docs")}))
    storage.load_config(write(app, {"output_dir": str(second)}, "config.spouse.json"))
    assert Paths(first).documents == tmp_path / "Docs"
    assert Paths(second).documents == second


def test_a_documents_folder_holding_the_output_folder_is_not_used(tmp_path, capsys):
    """Its records and Manual Review would sit in the watched folder."""
    out = tmp_path / "Watched" / "out"
    cfg = storage.load_config(write(tmp_path / "app", {
        "output_dir": str(out), "documents_dir": str(tmp_path / "Watched")}))
    assert cfg["documents_dir"] == "" and Paths(out).documents == out
    assert "holds the output folder" in capsys.readouterr().out
    inside = storage.load_config(write(tmp_path / "app", {
        "output_dir": str(out), "documents_dir": str(out / "Documents")}))
    assert inside["documents_dir"] == str(out / "Documents"), "a folder inside it may be"


@pytest.mark.parametrize("given", ["Watched", "./Watched", "~Watched", 7, ["x"], "   "])
def test_a_documents_folder_that_is_not_a_full_path_is_not_used(tmp_path, capsys, given):
    """A typo in a setting never sends documents somewhere nobody meant,
    and never stops a run. "~/Watched" is the folder Watched in the home
    folder (#166, test_spec_and_paths), and "~Watched" is a folder of that
    name, which is not a full path."""
    out = tmp_path / "out"
    cfg = storage.load_config(write(tmp_path / "app", {"output_dir": str(out),
                                                       "documents_dir": given}))
    assert cfg["documents_dir"] == ""
    assert Paths(out).documents == out
    said = capsys.readouterr().out
    assert "documents folder" in said and "output folder as before" in said


@pytest.mark.parametrize("where", ["profile", "inside", "around"])
def test_a_documents_folder_at_a_browser_profile_is_not_used(tmp_path, capsys, where):
    out, profile = tmp_path / "out", tmp_path / "home" / "browser-profile"
    docs = {"profile": profile, "inside": profile / "Default",
            "around": tmp_path / "home"}[where]
    cfg = storage.load_config(write(tmp_path / "app", {
        "output_dir": str(out), "profile_dir": str(profile), "documents_dir": str(docs)}))
    assert cfg["documents_dir"] == ""
    assert Paths(out).documents == out
    assert "browser profile" in capsys.readouterr().out


# -- PaperPull Server -------------------------------------------------------------------

@pytest.fixture()
def server(tmp_path, monkeypatch):
    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    (tmp_path / "profiles").mkdir()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.chdir(install)
    return install


def on_the_server(install: Path, **changed) -> Path:
    settings = {"owner": "", "output_dir": ".", "cdp_url": "http://127.0.0.1:9299",
                "profile_dir": str(install.parent.parent / "profiles" / install.name)}
    settings.update(changed)
    return write(install, settings)


def test_on_the_server_a_documents_folder_inside_the_data_folder_is_kept(server):
    docs = server.parent / "Documents"
    cfg = storage.load_config(on_the_server(server, documents_dir=str(docs)))
    assert cfg["documents_dir"] == str(docs)
    assert Paths(Path(cfg["output_dir"])).documents == docs


@pytest.mark.parametrize("given", ["outside", "relative", "number"])
def test_on_the_server_a_documents_folder_anywhere_else_stops_the_run(server, given):
    value = {"outside": str(server.parent.parent / "elsewhere"), "relative": "Documents",
             "number": 7}[given]
    with pytest.raises(SystemExit) as stop:
        storage.load_config(on_the_server(server, documents_dir=value))
    assert "documents_dir" in str(stop.value) or "outside" in str(stop.value)
    assert not (server.parent.parent / "elsewhere").exists()


def test_on_the_server_a_documents_folder_that_is_a_link_out_stops_the_run(server):
    outside = server.parent.parent / "elsewhere"
    outside.mkdir()
    link_folder(outside, server.parent / "Documents")
    with pytest.raises(SystemExit) as stop:
        storage.load_config(on_the_server(server, documents_dir=str(server.parent / "Documents")))
    assert "outside" in str(stop.value)


def test_on_the_server_a_link_out_inside_the_documents_folder_stops_the_run(server):
    outside = server.parent.parent / "elsewhere"
    outside.mkdir()
    docs = server.parent / "Documents"
    docs.mkdir()
    link_folder(outside, docs / "Statements")
    with pytest.raises(SystemExit) as stop:
        storage.load_config(on_the_server(server, documents_dir=str(docs)))
    assert "link" in str(stop.value)


# -- Rename and the Move -----------------------------------------------------------------

INDEX_COLUMNS = ["Document Date", "Document Title", "Document Summary", "Account",
                 "PDF Filename", "PDF Full Path", "Processing Status", "Notes",
                 "Order or Receipt Number"]


def body_of(key: str) -> bytes:
    return b"%PDF-1.4\n% the invented statement " + key.encode() + b"\n%%EOF\n"


class Office:
    """Enough of a statements app for Rename, its folders the core's own
    Paths, its index and run state real files."""

    def __init__(self, tmp_path: Path):
        self.out = tmp_path / "out"
        self.docs = tmp_path / "Watched"
        self.config = {"max_path_length": 240}
        self.build(documents=False)
        backups = self.out / "Backups"
        self.index_csv = storage.CsvFile(self.out / "Testco Document Index.csv",
                                         INDEX_COLUMNS, backups)
        self.order_csv = None
        self.progress = storage.JsonStore(self.out / "progress.json", backups)
        self.discovery = storage.JsonStore(self.out / "discovery.json", backups)
        self.progress.load()
        self.discovery.load()

    def build(self, documents: bool):
        """The app's folders, with or without its documents folder."""
        self.paths = Paths(self.out, documents_dir=str(self.docs) if documents else "")
        self.paths.ensure()

    def saved(self, account: str, aside: bool = False, checked: bool = True) -> Path:
        """A statement as a download leaves it. One not `checked` failed its
        check and could not be put aside, so it is still in the folder of
        its kind, recorded as needing review."""
        name = storage.build_pdf_filename(DATE, "Monthly Statement", "",
                                          record={"account": account})
        folder = self.paths.manual_review if aside else self.paths.folder_for("Statement")
        path = storage.unique_path(folder, name if not aside else str(name))
        path.write_bytes(body_of(account))
        status = "Completed" if checked else "Needs Manual Review"
        self.index_csv.append_rows([{
            "Document Date": DATE, "Document Title": "Monthly Statement",
            "Document Summary": "Monthly Statement", "Account": account,
            "PDF Filename": path.name, "PDF Full Path": str(path),
            "Processing Status": status, "Notes": ""}])
        self.progress.update(account, {
            "date": DATE, "title": "Monthly Statement", "summary": "Monthly Statement",
            "account": account, "category": "Statement", "pdf_path": str(path),
            "pdf_filename": path.name, "downloaded_ok": checked, "state": status})
        return path

    def rename(self, apply_changes=True):
        said = []
        try:
            renaming.run_for(self, apply_changes=apply_changes, say=said.append)
            code = 0
        except SystemExit as stop:
            code = stop.code
        return code, "\n".join(said)

    def where(self) -> dict:
        """Each statement's file by its bytes, seen from tmp_path."""
        top = self.out.parent
        return {p.read_bytes(): p.relative_to(top).as_posix()
                for p in top.rglob("*.pdf")}

    def follows(self) -> None:
        rows = storage.CsvFile(self.index_csv.path, INDEX_COLUMNS).read_all()
        self.progress.save()
        on_disk = storage.JsonStore(self.out / "progress.json")
        on_disk.load()
        for row in rows:
            path = Path(row["PDF Full Path"])
            assert path.read_bytes() == body_of(row["Account"]), row
            assert row["PDF Filename"] == path.name
            for records in (self.progress.data, on_disk.data):
                assert records[row["Account"]]["pdf_path"] == str(path)


FIRST = "2026-09-12 Testco Monthly Statement.pdf"
SECOND = "2026-09-12 Testco Monthly Statement (2).pdf"
BEFORE = {body_of(ACCOUNTS[0]): "out/Statements/" + FIRST,
          body_of(ACCOUNTS[1]): "out/Statements/" + SECOND}


@pytest.fixture
def office(tmp_path):
    """Two statements saved before the account had a documents folder, and
    the folder then set."""
    office = Office(tmp_path)
    for account in ACCOUNTS:
        office.saved(account)
    office.build(documents=True)
    assert office.where() == BEFORE
    return office


def moving(monkeypatch):
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "1")


def test_setting_a_documents_folder_moves_nothing(office):
    code, said = office.rename(apply_changes=False)
    assert code == 0 and "Every file is already named the way this app names them." in said
    assert "name something other than a PDF" not in said, "a file saved before is held"
    assert office.where() == BEFORE


def test_a_file_saved_before_is_renamed_where_it_is(office):
    storage.set_filename_patterns({"filename_pattern": "{provider}/{date} {account}"})
    code, said = office.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert office.where() == {
        body_of(a): "out/Statements/Testco/2026-09-12 %s.pdf" % a for a in ACCOUNTS}
    office.follows()


def test_after_a_run_only_what_it_saved_and_checked_moves(office, monkeypatch):
    """A download is written and checked in the output folder, and once its
    run has ended the panel moves what the run listed in new-this-run.txt.
    The documents saved before wait for the person's own Move."""
    new = office.saved("Brokerage 3333")
    failed = office.saved("Loan 4444", checked=False)
    assert new.parent == failed.parent == office.out / "Statements"
    (office.out / "new-this-run.txt").write_text(
        "# 1 file(s) downloaded on this run:\n%s\n" % new, encoding="utf-8")
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "new")
    code, said = office.rename()
    assert code == 0 and "Moved 1 file(s)" in said, said
    where = office.where()
    assert where[body_of("Brokerage 3333")] == "Watched/Statements/" + new.name
    assert where[body_of("Loan 4444")] == "out/Statements/" + failed.name
    for account in ACCOUNTS:
        assert where[body_of(account)] == BEFORE[body_of(account)]
    office.follows()


def test_a_document_that_failed_its_check_never_moves(office, monkeypatch):
    """Put aside it could not be, so it is still in the folder of its kind,
    and its record says it needs review. It never reaches the watched
    folder, through no Move at all."""
    failed = office.saved("Loan 4444", checked=False)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert office.where()[body_of("Loan 4444")] == "out/Statements/" + failed.name


def test_the_move_takes_each_document_saved_before_to_the_documents_folder(
        office, monkeypatch):
    aside = office.saved("Brokerage 3333", aside=True)
    moving(monkeypatch)
    code, said = office.rename(apply_changes=False)
    assert code == 0 and "2 file(s) would be moved." in said, said
    assert str(office.docs / "Statements" / FIRST) in said
    assert office.where()[body_of(ACCOUNTS[0])] == BEFORE[body_of(ACCOUNTS[0])]
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s) to %s." % office.docs in said, said
    where = office.where()
    assert where[body_of(ACCOUNTS[0])] == "Watched/Statements/" + FIRST
    assert where[body_of(ACCOUNTS[1])] == "Watched/Statements/" + SECOND
    assert where[body_of("Brokerage 3333")] == "out/Manual Review/" + aside.name, (
        "a file put aside never reaches the documents folder")
    office.follows()
    assert (office.out / "Statements").is_dir(), "the folder they were in is kept"
    code, said = office.rename(apply_changes=False)
    assert "Every document is in the documents folder already." in said, said
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)
    code, said = office.rename(apply_changes=False)
    assert "Every file is already named the way this app names them." in said, said


def test_the_move_keeps_a_patterns_folders_and_tells_apart_a_clash(office, monkeypatch):
    storage.set_filename_patterns({"filename_pattern": "{provider}/{date} {account}"})
    assert office.rename()[0] == 0
    theirs = office.docs / "Statements" / "Testco" / ("2026-09-12 %s.pdf" % ACCOUNTS[0])
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"%PDF- somebody's own file")
    # A move keeps every name and folder whatever the pattern says now.
    storage.set_filename_patterns({})
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0, said
    assert theirs.read_bytes() == b"%PDF- somebody's own file"
    where = office.where()
    assert where[body_of(ACCOUNTS[0])] == "Watched/Statements/Testco/2026-09-12 %s (2).pdf" % (
        ACCOUNTS[0])
    assert where[body_of(ACCOUNTS[1])] == "Watched/Statements/Testco/2026-09-12 %s.pdf" % (
        ACCOUNTS[1])
    assert not (office.out / "Statements" / "Testco").exists(), "its emptied folder goes"
    office.follows()


def test_a_move_that_cannot_write_the_index_puts_every_file_back(office, monkeypatch):
    storage.set_filename_patterns({"filename_pattern": "{provider}/{date} {account}"})
    assert office.rename()[0] == 0
    before = office.where()
    real = storage.atomic_write_text

    def refuse(path, text, encoding="utf-8", **how):
        if Path(path).name == "Testco Document Index.csv":
            raise PermissionError("%s stayed locked." % path)
        return real(path, text, encoding, **how)

    monkeypatch.setattr(storage, "atomic_write_text", refuse)
    monkeypatch.setattr(renaming, "free_to_write", lambda *_a, **_kw: True)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 1 and "every file was put back" in said, said
    assert office.where() == before
    assert not (office.docs / "Statements" / "Testco").exists(), "a folder made for nothing"
    monkeypatch.setattr(storage, "atomic_write_text", real)
    office.follows()


def test_a_move_with_no_documents_folder_says_there_is_nothing_to_move(tmp_path, monkeypatch):
    office = Office(tmp_path)
    office.saved(ACCOUNTS[0])
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "there are none to move" in said
    assert office.where() == {body_of(ACCOUNTS[0]): "out/Statements/" + FIRST}


def test_documents_moved_before_are_found_after_the_folder_changes_or_is_cleared(
        office, monkeypatch):
    """Each documents folder the Move filled is written down beside the
    records, so after the setting changes its documents are still the
    app's, and a Move takes them on to the new folder, or back to the
    output folder once the setting is cleared."""
    moving(monkeypatch)
    assert office.rename()[0] == 0
    assert json.loads((office.out / "documents-folders.json").read_text("utf-8")) == [
        str(office.docs)]
    first_docs, office.docs = office.docs, office.out.parent / "Other Watched"
    office.build(documents=True)
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)
    code, said = office.rename(apply_changes=False)
    assert "Every file is already named the way this app names them." in said, said
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert office.where() == {b: p.replace("out/", "Other Watched/") for b, p in BEFORE.items()}
    assert not list(first_docs.rglob("*.pdf"))
    office.follows()
    office.build(documents=False)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert office.where() == BEFORE
    office.follows()


def across(monkeypatch, docs: Path, refuse_unlink: bool = False):
    """Renames from one side of `docs` to the other refused as a rename to
    another drive is, so the Move has to copy, and with `refuse_unlink`,
    the file it copied cannot be taken away from where it was."""
    real_rename, real_unlink = Path.rename, Path.unlink

    def rename(self, target):
        if (docs in Path(target).parents) != (docs in self.parents):
            raise OSError(18, "Invalid cross-device link", str(self))
        return real_rename(self, target)

    def unlink(self, *a, **kw):
        if refuse_unlink and docs not in self.parents and self.suffix == ".pdf":
            raise PermissionError(13, "held by another program", str(self))
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(Path, "unlink", unlink)


def test_the_move_goes_to_a_documents_folder_on_another_drive(office, monkeypatch):
    across(monkeypatch, office.docs)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert office.where() == {b: p.replace("out/", "Watched/") for b, p in BEFORE.items()}
    assert not [p for p in office.docs.rglob("*") if ".moving" in p.name]
    office.follows()


def test_a_copy_to_another_drive_that_cannot_leave_its_first_place_goes_again(
        office, monkeypatch):
    """There are never two copies, one in each place."""
    across(monkeypatch, office.docs, refuse_unlink=True)
    moving(monkeypatch)
    code, said = office.rename()
    assert office.where() == BEFORE, said
    assert not list(office.docs.rglob("*.pdf"))
    monkeypatch.undo()
    office.follows()


def test_every_invoice_of_an_order_split_into_several_moves(tmp_path, monkeypatch):
    """Target keeps each invoice of a split order in the record's list, and
    only one of them has an index row. Each goes, and the list follows."""
    office = Office(tmp_path)
    first = office.saved("Order 5555")
    second = first.with_name("2026-09-12 Testco Monthly Statement (2 of 2).pdf")
    second.write_bytes(body_of("Order 5555 part 2"))
    rec = office.progress.data["Order 5555"]
    rec["order_number"] = "5555"
    rec["invoices"] = [{"file": str(first), "kept": True}, {"file": str(second), "kept": True},
                       {"file": str(first.with_name("put aside.pdf")), "kept": False}]
    office.build(documents=True)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    office.progress.save()
    invoices = office.progress.data["Order 5555"]["invoices"]
    assert [Path(e["file"]).parent for e in invoices[:2]] == [office.docs / "Statements"] * 2
    assert all(Path(e["file"]).is_file() for e in invoices[:2])


@pytest.mark.parametrize("key", ["Tax 2024", "Statement:2026-09-12:Monthly Statement"],
                         ids=["a plain key", "a key of category, date and title"])
def test_companion_files_of_a_document_move(tmp_path, monkeypatch, key):
    """A document app with companion files (.xls, .pdf) in its invoices moves
    them to the documents folder, with no order number. What follows the first
    colon of a document's key is not one."""
    office = Office(tmp_path)
    first = office.saved("Tax 2024")
    second = first.with_name("2026-09-12 Testco Monthly Statement (2 of 2).xls")
    second.write_bytes(b"dummy xls content")
    rec = office.progress.data.pop("Tax 2024")
    office.progress.data[key] = rec
    rec["invoices"] = [{"file": str(first), "kept": True}, {"file": str(second), "kept": True}]
    office.build(documents=True)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    office.progress.save()
    invoices = office.progress.data[key]["invoices"]
    assert [Path(e["file"]).parent for e in invoices] == [office.docs / "Statements"] * 2
    assert all(Path(e["file"]).is_file() for e in invoices)
    assert Path(invoices[1]["file"]).read_bytes() == b"dummy xls content"


def lists(tmp_path, record: dict):
    """An app with one record listing two files, and the two."""
    first, second = tmp_path / "a (1 of 2).pdf", tmp_path / "a (2 of 2).pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    record = dict(record, pdf_path=str(first), invoices=[{"file": str(first), "kept": True},
                                                         {"file": str(second), "kept": True}])
    return first, second, record


@pytest.mark.parametrize("documents", [False, True], ids=["a rename", "a move"])
def test_a_document_is_found_by_the_row_naming_its_file(tmp_path, documents):
    first, second, rec = lists(tmp_path, {})
    row = {"PDF Full Path": str(first), "PDF Filename": first.name,
           "Document Title": "Form", "Document Date": "2026-09-12"}
    app = SimpleNamespace(progress=SimpleNamespace(data={"Tax:2026-09-12:Form": rec}))
    extra = renaming._invoices_alone(app, [row], documents=documents)
    assert [r["PDF Full Path"] for r in extra] == [str(second)]
    assert extra[0]["Order or Receipt Number"] == ""
    assert extra[0]["Document Title"] == "Form"


def test_a_document_takes_nothing_from_another_documents_row(tmp_path):
    """No row names this document's file, and a row with no number is not its
    own for having no number either."""
    _first, _second, rec = lists(tmp_path, {})
    row = {"PDF Full Path": str(tmp_path / "another.pdf"), "PDF Filename": "another.pdf",
           "Document Title": "Another", "Document Date": "2026-09-12"}
    app = SimpleNamespace(progress=SimpleNamespace(data={"Tax 2024": rec}))
    assert renaming._invoices_alone(app, [row], documents=False) == []
    assert all(r.get("Document Title") != "Another"
               for r in renaming._invoices_alone(app, [row], documents=True))


def test_an_order_takes_nothing_from_a_row_of_another_order(tmp_path):
    """A row naming an order's file may be another order's (_Known.record_for).
    A Rename leaves such an order's invoices alone, rather than give them the
    other purchase's date."""
    first, _second, rec = lists(tmp_path, {"order_number": "111", "purchase_date": "2026-09-01"})
    row = {"PDF Full Path": str(first), "PDF Filename": first.name,
           "Order or Receipt Number": "222", "Purchase Date": "2026-09-12"}
    app = SimpleNamespace(progress=SimpleNamespace(data={"Online:111": rec}))
    assert renaming._invoices_alone(app, [row], documents=False) == []
    moved = renaming._invoices_alone(app, [row], documents=True)
    assert [(r["Order or Receipt Number"], r["Purchase Date"]) for r in moved] == [("111", "2026-09-01")]


@pytest.mark.parametrize("name,document,row", [
    ("a.pdf", True, True), ("a.xls", True, True), ("a.xlsx", True, True), ("a.csv", True, True),
    ("A.XLS", True, True), ("a.txt", False, False), ("a.zip", False, False),
    ("a.pdf.renaming", False, True), ("a.xls.renaming", False, False),
    ("a.txt.renaming", False, False), ("a.pdf.delivering", False, True),
    ("a.xls.delivering", False, False)])
def test_what_an_app_holds_by_how_a_file_ends(tmp_path, name, document, row):
    path = tmp_path / name
    path.write_bytes(b"a file")
    held = {"PDF Full Path": str(path), "Processing Status": "Completed"}
    assert (renaming.held_document(str(path), [tmp_path]) is not None) == document
    assert (renaming.held_row(held, [tmp_path]) is not None) == row


@pytest.mark.skipif(os.name != "nt", reason="only Windows keeps a read-only file from being deleted, "
                                            "elsewhere its folder decides and the move goes ahead")
def test_a_read_only_file_on_its_way_to_another_drive_stays_where_it_was(
        office, monkeypatch):
    """Its copy carries none of its attributes, so when the file itself
    cannot be taken away, the copy can, and there are never two.
    test_a_copy_to_another_drive_that_cannot_leave_its_first_place_goes_again
    refuses the delete on every system."""
    import stat as stat_module
    across(monkeypatch, office.docs)
    first = office.out / "Statements" / FIRST
    os.chmod(first, stat_module.S_IREAD)
    try:
        moving(monkeypatch)
        code, said = office.rename()
        where = office.where()
        assert where[body_of(ACCOUNTS[0])] == BEFORE[body_of(ACCOUNTS[0])], said
        assert where[body_of(ACCOUNTS[1])] == "Watched/Statements/" + SECOND
        assert [p.name for p in office.docs.rglob("*.pdf")] == [SECOND]
        assert not [p for p in office.docs.rglob("*") if ".moving" in p.name]
        office.follows()
    finally:
        os.chmod(first, stat_module.S_IREAD | stat_module.S_IWRITE)


def test_a_copy_that_failed_its_check_beside_one_that_passed_never_moves(
        office, monkeypatch):
    """Download again saved a second copy of a purchase that failed its
    check and could not be put aside. The purchase's record, found by its
    order number, says it was saved, and kept that from the copy that
    passed, so it names that copy and not this one. This one stays, even
    where its row reads Completed."""
    rows = office.index_csv.read_all()
    rows[0]["Order or Receipt Number"] = "7001"
    office.index_csv.rewrite(rows)
    office.progress.update(ACCOUNTS[0], {"order_number": "7001"})
    failed = office.out / "Statements" / "2026-09-12 Testco Monthly Statement (3).pdf"
    failed.write_bytes(body_of("a copy that failed"))
    office.index_csv.append_rows([{
        "Document Date": DATE, "Document Title": "Monthly Statement",
        "Document Summary": "Monthly Statement", "Account": ACCOUNTS[0],
        "PDF Filename": failed.name, "PDF Full Path": str(failed),
        "Processing Status": "Completed", "Notes": "", "Order or Receipt Number": "7001"}])
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert failed.is_file(), "a file no record names stays where it is"


def test_a_documents_folder_inside_manual_review_or_a_hidden_folder_is_not_used(
        tmp_path, capsys):
    out = tmp_path / "out"
    for inside in ("Manual Review", "Logs", ".chase-downloads"):
        cfg = storage.load_config(write(tmp_path / "app", {
            "output_dir": str(out), "documents_dir": str(out / inside / "Docs")}))
        assert cfg["documents_dir"] == "", inside
        assert "Manual Review, Logs" in capsys.readouterr().out


def test_on_the_server_a_folder_used_before_with_a_link_out_is_not_the_apps(server):
    """documents-folders.json is in the shared folder. A folder it names
    whose folder of a kind leads out of the data folder through a link is
    left out, so nothing in it is held, renamed or moved."""
    outside = server.parent.parent / "elsewhere"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF- not the app's")
    watched = server.parent / "Watched"
    watched.mkdir()
    link_folder(outside, watched / "Statements")
    (server / "documents-folders.json").write_text(json.dumps([str(watched)]),
                                                   encoding="utf-8")
    cfg = storage.load_config(on_the_server(server))
    paths = Paths(Path(cfg["output_dir"]))
    assert paths.documents_roots() == []
    assert watched / "Statements" not in paths.filing_folders()
    assert renaming.held_document(str(watched / "Statements" / "secret.pdf"),
                                  paths.filing_folders()) is None


def test_on_the_server_a_move_into_a_folder_that_became_a_link_out_is_refused(server):
    outside = server.parent.parent / "elsewhere"
    outside.mkdir()
    folder = server.parent / "Watched" / "Statements"
    folder.parent.mkdir()
    link_folder(outside, folder)
    with pytest.raises(PermissionError):
        renaming._make_folders(folder, renaming.Result())


# -- what travels and what a second person gets ------------------------------------------

def _tool(name: str):
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "tools" / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("tool_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_documents_folder_never_travels_to_another_computer(tmp_path):
    migrate = _tool("migrate")
    install = tmp_path / "Testco Statements"
    write(install, {"documents_dir": "", "owner": ""}, "config.example.json")
    assert "documents_dir" not in migrate.settings_allowed(install)
    assert migrate.settings_to_apply(install, {}, {"documents_dir": str(tmp_path / "x")}) == {}


def test_a_second_person_starts_with_documents_in_their_own_folder(tmp_path):
    add_account = _tool("add_account")
    install = tmp_path / "Testco Statements"
    write(install, {"output_dir": ".", "documents_dir": str(tmp_path / "First's Documents"),
                    "owner": "First"})
    made = add_account.make_config(install, "spouse")
    cfg = json.loads(made.read_text(encoding="utf-8"))
    assert "documents_dir" not in cfg
    assert os.path.normpath(cfg["output_dir"]) == os.path.normpath("../Testco Statements - spouse")
