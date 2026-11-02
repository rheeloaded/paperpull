"""Folders from a file naming pattern (#101).

A / in a naming pattern's own text puts files in folders, inside the folder
each kind of document is filed in already, Statements or Receipts or the
like. Before, a / was dropped from the name without a word, so
"{provider}/{date}" ran the two together, and then for a day it was refused.

What is held here. A name carries its folders (storage.FileName) and is
still the name itself, so the seventy-odd places an app compares a saved
file's name with it read it as they always did. Each folder is made safe as
a name is, a folder a record says nothing about is left out, and a / in a
value never makes one. unique_path files a name in its folders, makes
them, looks for a clash there, counts them toward the path limit, and
leaves the file in the folder it was routed to when they cannot be used,
never outside it. Rename moves each file into the folders its name gives
and back out again, the index and the run state following it, takes away a
folder it leaves empty and never the folder of a kind or one holding
anything, and puts everything back when a ledger cannot be written. Review
Names does the same for each receipt it renames.

Every name, number and account here is invented.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import naming, renaming, storage  # noqa: E402
from paperpull_core.storage import FileName, folder_of, unique_path  # noqa: E402

DATE = "2026-09-12"
FOLDERS = "{provider}/[{account}/]{date:yyyy-mm-dd} {summary}"


@pytest.fixture(autouse=True)
def no_pattern():
    """Files named the default way before and after, whatever a test chose."""
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def named(pattern=FOLDERS, summary="Monthly Statement", **record):
    return storage.build_pdf_filename(DATE, summary, "", record=record, pattern=pattern)


# What a test here needs below the folder a document is routed to, for the
# pattern's folders and the longest name it checks, an ending and a count
# included.
ROOM = 110
_LONG_PATHS = []


def _long_paths_work() -> bool:
    """Whether this system holds a path longer than Windows' old 260
    characters, found once by making one in a temporary folder."""
    if not _LONG_PATHS:
        import shutil
        import tempfile
        top = Path(tempfile.mkdtemp(prefix="paperpull-long-"))
        try:
            deep = top / ("d" * 120) / ("e" * 120)
            deep.mkdir(parents=True)
            (deep / "probe.txt").write_text("x", encoding="utf-8")
            _LONG_PATHS.append(True)
        except OSError:
            _LONG_PATHS.append(False)
        finally:
            shutil.rmtree(top, ignore_errors=True)
    return _LONG_PATHS[0]


def limit_for(folder) -> int:
    """The max_path_length a test gives a file routed to `folder`. The
    usual 240 where that leaves ROOM, and more under a temporary folder deep
    enough that 240 would cut the very names a test checks, so the tests
    here pass however deep pytest's temporary folder is, on a developer's
    machine or a CI runner. Skipped only where the system cannot hold a
    path that long at all."""
    limit = max(240, len(str(folder)) + 1 + ROOM)
    if limit > 259 and not _long_paths_work():
        pytest.skip("the temporary folder is too deep for a path this system can hold")
    return limit


def filed(folder, name, **how):
    """unique_path, at the limit a test gives `folder` (limit_for)."""
    return unique_path(folder, name, limit_for(folder), **how)


def link_folder(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


# -- a name and its folders ------------------------------------------------------------

def test_a_name_from_a_pattern_with_a_slash_carries_its_folders():
    name = named(account="Checking 1111")
    assert isinstance(name, str) and isinstance(name, FileName)
    assert name == "2026-09-12 Monthly Statement.pdf"
    assert folder_of(name) == "Testco/Checking 1111"
    # It is the name itself wherever an app compares or prints it.
    assert Path("x") / name == Path("x") / "2026-09-12 Monthly Statement.pdf"
    assert "%s" % name == f"{name}" == "2026-09-12 Monthly Statement.pdf"


def test_a_name_a_caller_changes_loses_its_folders():
    """A cut or an ending added gives plain text, which is filed in the
    folder the document is routed to, where every file went before."""
    name = named(account="Checking 1111")
    for changed in (name + "", name.replace(".pdf", " x.pdf"), name[:10], name.strip()):
        assert folder_of(changed) == ""


def test_a_folder_a_record_says_nothing_about_is_left_out():
    assert folder_of(named(account="")) == "Testco"
    assert folder_of(named(account="   ")) == "Testco"
    assert folder_of(named(pattern="[{account}/]{date} {summary}", account="")) == ""
    # A folder of an optional section alone, with its / outside it.
    between = "{provider}/[{account}]/{date} {summary}"
    assert folder_of(named(pattern=between, account="")) == "Testco"
    assert folder_of(named(pattern=between, account="...")) == "Testco"
    assert folder_of(named(pattern=between, account="Joint")) == "Testco/Joint"


@pytest.mark.parametrize("account,folder", [
    ("Joint/Savings", "Testco/JointSavings"),
    ("../..", "Testco"),
    ("..", "Testco"),
    ("C:", "Testco/C"),
    ("...1234", "Testco/1234"),
    ("  Checking  1111. ", "Testco/Checking 1111"),
    ("CON", "Testco/CON File"),
    ('a<b>c"d|e?f*g\\h', "Testco/abcdefgh"),
    ("x" * 300, "Testco/" + "x" * storage.FOLDER_MAX),
])
def test_each_folder_is_made_safe_as_a_name_is(account, folder):
    """A value with a / stays one folder, and nothing a provider writes can
    climb out, name a drive or hide a folder on a Mac."""
    assert folder_of(named(account=account)) == folder


def test_a_name_with_no_folder_is_what_it_always_was():
    plain = named(pattern="{date:yyyy-mm-dd} {provider} {summary}", account="A/B")
    assert plain == "2026-09-12 Testco Monthly Statement.pdf" and folder_of(plain) == ""
    default = storage.build_pdf_filename(DATE, "a/b: c", "")
    assert default == "2026-09-12 Testco Ab C.pdf" and folder_of(default) == ""


def test_a_saved_pattern_with_folders_names_every_file_of_a_run():
    storage.set_filename_patterns({"filename_pattern": "{provider}/{year}/{date} {summary}"})
    name = storage.build_pdf_filename(DATE, "statement", "")
    assert (name, folder_of(name)) == ("2026-09-12 Statement.pdf", "Testco/2026")


def test_a_saved_pattern_too_deep_leaves_files_their_usual_names(capsys):
    storage.set_filename_patterns({"filename_pattern": "{provider}/{year}/{month}/{kind}/{date}"})
    name = storage.build_pdf_filename(DATE, "statement", "")
    assert (name, folder_of(name)) == ("2026-09-12 Testco Statement.pdf", "")
    assert "at most 3 folders deep" in capsys.readouterr().out


def test_the_preview_shows_the_folders_a_run_would_file_in():
    record = {"date": DATE, "summary": "monthly statement", "account": "Checking 1111"}
    built = storage.build_pdf_filename(DATE, record["summary"], "", record=record,
                                       pattern=FOLDERS)
    shown = naming.preview(FOLDERS, record, provider="Testco")
    assert shown == "%s/%s" % (folder_of(built), built) == \
        "Testco/Checking 1111/2026-09-12 Monthly Statement.pdf"
    assert naming.preview("{date} {summary}", record, provider="Testco") == \
        "2026-09-12 Monthly Statement.pdf"


# -- filing a name in its folders --------------------------------------------------

@pytest.fixture
def base(tmp_path):
    """The folder a document is routed to, Statements."""
    folder = tmp_path / "out" / "Statements"
    folder.mkdir(parents=True)
    return folder


def test_a_name_is_filed_in_its_folders_which_are_made(base):
    name = named(account="Checking 1111")
    got = filed(base, name)
    assert got == base / "Testco" / "Checking 1111" / "2026-09-12 Monthly Statement.pdf"
    assert got.parent.is_dir() and not got.exists()


def test_a_name_filed_in_manual_review_takes_no_folders(tmp_path):
    """Manual Review stays one folder, so everything set aside is found in
    one place. Target puts an invoice that failed its check there under the
    name the pattern gives it, folders and all."""
    aside = tmp_path / "out" / "Manual Review"
    aside.mkdir(parents=True)
    got = filed(aside, named(account="Checking 1111"))
    assert got == aside / "2026-09-12 Monthly Statement.pdf"
    assert list(aside.iterdir()) == []
    assert storage.fitted_name(aside, named(account="Checking 1111"), limit_for(aside)) == got.name


def test_a_preview_makes_no_folder(base):
    got = filed(base, named(account="Checking 1111"), make=False)
    assert got.parent == base / "Testco" / "Checking 1111"
    assert not (base / "Testco").exists()


def test_a_clash_is_looked_for_in_the_folder_the_file_goes_to(base):
    """A file of the name in the folder of its kind is another file in
    another folder, and one in the pattern's folder is the clash."""
    name = named(account="Checking 1111")
    (base / str(name)).write_bytes(b"flat")
    first = filed(base, name, distinguisher="DOC0001")
    assert first.name == str(name)
    first.write_bytes(b"first")
    second = filed(base, name, distinguisher="DOC0002")
    assert second == first.parent / "2026-09-12 Monthly Statement DOC0002.pdf"


def test_a_file_stands_in_its_own_way_only_in_its_own_folder(base):
    """A file being renamed does not hold its own name, in the folder it is
    in. A file of its name in a pattern's folder is another file, and a name
    alone said as ignoring was taken there for the file's own."""
    name = named(account="Checking 1111")
    flat = base / str(name)
    flat.write_bytes(b"the file moving")
    taken = filed(base, name)
    taken.write_bytes(b"another file")
    assert filed(base, name, ignoring=flat).name == \
        "2026-09-12 Monthly Statement (2).pdf"
    assert filed(base, name, ignoring=str(name)).name == \
        "2026-09-12 Monthly Statement (2).pdf"
    assert filed(base, name, ignoring=taken) == taken
    assert filed(base, str(name), ignoring=str(name)) == flat


def test_the_folders_count_toward_the_path_limit(base):
    name = named(account="Checking 1111", summary="A Rather Long Statement Summary " * 3)
    flat_room = len(str(base)) + 1 + len(str(name))
    limit = flat_room - 5
    got = unique_path(base, name, max_path_length=limit)
    assert got.parent == base / "Testco" / "Checking 1111"
    assert len(str(got)) <= limit and got.suffix == ".pdf"
    assert len(got.name) < len(str(name)), "the name is cut to fit under its folders"
    assert storage.fitted_name(base, name, limit) == got.name


def test_folders_too_deep_for_any_name_leave_the_file_where_it_is_routed(base):
    name = named(account="Checking 1111")
    limit = len(str(base / "Testco" / "Checking 1111")) + 10
    got = unique_path(base, name, max_path_length=limit)
    assert got.parent == base, "a folder never keeps a file from being saved"
    assert not (base / "Testco").exists()
    assert storage.fitted_name(base, name, limit) == got.name


def test_a_folder_that_leads_out_through_a_link_is_never_written_into(base, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    link_folder(outside, base / "Testco")
    got = filed(base, named(account="Checking 1111"))
    assert got.parent == base
    got.write_bytes(b"%PDF-")
    assert list(outside.iterdir()) == [], "nothing was written outside"


def test_a_file_where_a_folder_should_be_leaves_the_file_where_it_is_routed(base):
    (base / "Testco").write_bytes(b"a file of that name")
    got = filed(base, named(account="Checking 1111"))
    assert got.parent == base
    assert storage.filing_folder(base, named(account="Checking 1111"), limit_for(base)) == base, (
        "Rename asks the same, so it offers no move a download would not make")


def test_a_folder_that_cannot_be_made_leaves_the_file_where_it_is_routed(base, monkeypatch):
    def refuse(self, *a, **kw):
        raise PermissionError(13, "not allowed here", str(self))

    monkeypatch.setattr(Path, "mkdir", refuse)
    got = filed(base, named(account="Checking 1111"))
    assert got.parent == base


@pytest.mark.parametrize("folder", ["..", "../escape", "a/../../escape", "C:/x", "a//b",
                                    ".hidden", "trailing.", "x" * 61])
def test_a_name_built_by_hand_with_folders_that_climb_is_filed_where_routed(base, folder):
    """build_pdf_filename makes every folder safe, and a FileName is text
    anybody can build, so unique_path asks each folder again and files a
    name whose folders are not safe in the folder it was routed to."""
    got = filed(base, FileName("x.pdf", folder))
    assert got == base / "x.pdf"
    assert sorted(p.name for p in base.iterdir()) == []


# -- moving a saved file to the name it learned --------------------------------------

def test_refile_moves_a_saved_file_and_takes_away_the_folder_it_left(base):
    old = filed(base, named(account="List Account"))
    old.write_bytes(b"%PDF- the statement")
    new = storage.refile(old, base, named(account="Checking 1111"), limit_for(base))
    assert new == base / "Testco" / "Checking 1111" / old.name
    assert new.read_bytes() == b"%PDF- the statement"
    assert not (base / "Testco" / "List Account").exists()
    assert (base / "Testco").is_dir() and base.is_dir()


def test_refile_leaves_a_file_already_named_so(base):
    old = filed(base, named(account="Checking 1111"))
    old.write_bytes(b"%PDF-")
    assert storage.refile(old, base, named(account="Checking 1111"), limit_for(base)) == old


def test_refile_refused_takes_away_the_folder_it_made(base, monkeypatch):
    old = filed(base, named(account=""))
    old.write_bytes(b"%PDF-")

    def refuse(self, target):
        raise PermissionError(13, "held by another program")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(PermissionError):
        storage.refile(old, base, named(account="Checking 1111"), limit_for(base))
    assert old.read_bytes() == b"%PDF-"
    assert not (base / "Testco" / "Checking 1111").exists()


def test_an_empty_folder_is_taken_away_and_nothing_else(base):
    keep = base / "Testco" / "Kept"
    keep.mkdir(parents=True)
    (keep / "notes.txt").write_text("somebody's own", encoding="utf-8")
    empty = base / "Testco" / "Empty" / "Deeper"
    empty.mkdir(parents=True)
    storage.remove_empty(empty, [base])
    assert not (base / "Testco" / "Empty").exists()
    assert keep.is_dir() and (base / "Testco").is_dir()
    storage.remove_empty(keep, [base])
    assert keep.is_dir()
    storage.remove_empty(base, [base])
    assert base.is_dir(), "never the folder a document is routed to"


def test_the_folder_a_document_is_routed_to_stays_when_it_is_left_empty(tmp_path):
    routed = tmp_path / "out" / "Statements"
    empty = routed / "Testco" / "2026"
    empty.mkdir(parents=True)
    storage.remove_empty(empty, [routed])
    assert routed.is_dir() and list(routed.iterdir()) == []
    storage.remove_empty(routed, [routed])
    assert routed.is_dir() and (tmp_path / "out").is_dir()


# -- Rename into folders and back ---------------------------------------------------

INDEX = "Testco Document Index.csv"
INDEX_COLUMNS = ["Document Date", "Document Title", "Document Summary", "Account",
                 "PDF Filename", "PDF Full Path", "Processing Status", "Notes"]
ACCOUNTS = ("Checking 1111", "Savings 2222")


def body_of(key: str) -> bytes:
    return b"%PDF-1.4\n% the invented statement " + key.encode() + b"\n%%EOF\n"


class _Paths:
    def __init__(self, out: Path):
        self.statements = out / "Statements"
        self.tax_documents = out / "Tax Documents"
        self.manual_review = out / "Manual Review"
        for folder in (self.statements, self.tax_documents, self.manual_review):
            folder.mkdir(parents=True, exist_ok=True)

    def filing_folders(self):
        return [self.statements, self.tax_documents, self.manual_review]


class Bank:
    """Enough of a statements app for Rename, its index and run state real
    files written by the core's own CsvFile and JsonStore."""

    def __init__(self, tmp_path: Path):
        self.out = tmp_path / "out"
        self.paths = _Paths(self.out)
        backups = self.out / "Backups"
        self.config = {"max_path_length": limit_for(self.paths.statements)}
        self.index_csv = storage.CsvFile(self.out / INDEX, INDEX_COLUMNS, backups)
        self.order_csv = None
        self.progress = storage.JsonStore(self.out / "progress.json", backups)
        self.discovery = storage.JsonStore(self.out / "discovery.json", backups)
        self.progress.load()
        self.discovery.load()

    def saved(self, account: str, folder: Path = None, spelled: str = "") -> Path:
        """A statement of the account, saved the way a download saves it
        under the pattern set now, or in `folder` under its usual name, and
        written down as `spelled` when that is given."""
        name = storage.build_pdf_filename(DATE, "Monthly Statement", "",
                                          record={"account": account})
        if folder is None:
            path = unique_path(self.paths.statements, name, self.config["max_path_length"])
        else:
            path = unique_path(folder, str(name), self.config["max_path_length"])
        path.write_bytes(body_of(account))
        written = spelled or str(path)
        self.index_csv.append_rows([{
            "Document Date": DATE, "Document Title": "Monthly Statement",
            "Document Summary": "Monthly Statement", "Account": account,
            "PDF Filename": path.name, "PDF Full Path": written,
            "Processing Status": "Completed", "Notes": ""}])
        self.progress.update(account, {
            "date": DATE, "title": "Monthly Statement", "summary": "Monthly Statement",
            "account": account, "category": "Statement", "pdf_path": written,
            "pdf_filename": path.name, "downloaded_ok": True, "state": "Completed"})
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
        """Each statement's file by the bytes in it, as Statements/... seen
        from the output folder."""
        return {p.read_bytes(): p.relative_to(self.out).as_posix()
                for p in self.out.rglob("*.pdf")}

    def follows(self) -> None:
        """The index and the run state, in memory and on disk, name each
        statement's file where it is now."""
        rows = storage.CsvFile(self.out / INDEX, INDEX_COLUMNS).read_all()
        self.progress.save()
        on_disk = storage.JsonStore(self.out / "progress.json")
        on_disk.load()
        for account in ACCOUNTS:
            [row] = [r for r in rows if r["Account"] == account]
            path = Path(row["PDF Full Path"])
            assert path.read_bytes() == body_of(account), account
            assert row["PDF Filename"] == path.name
            for records in (self.progress.data, on_disk.data):
                assert records[account]["pdf_path"] == str(path)
                assert records[account]["pdf_filename"] == path.name


def flat_names():
    return {body_of(a): "Statements/2026-09-12 Testco Monthly Statement.pdf"
            if a == ACCOUNTS[0] else
            "Statements/2026-09-12 Testco Monthly Statement (2).pdf" for a in ACCOUNTS}


IN_FOLDERS = {body_of(a): "Statements/Testco/%s/2026-09-12 Monthly Statement.pdf" % a
              for a in ACCOUNTS}


@pytest.fixture
def bank(tmp_path):
    bank = Bank(tmp_path)
    for account in ACCOUNTS:
        bank.saved(account)
    assert bank.where() == flat_names()
    return bank


def test_rename_moves_each_file_into_the_folders_its_pattern_names(bank):
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename(apply_changes=False)
    assert code == 0 and bank.where() == flat_names(), "a preview moves nothing"
    assert not (bank.paths.statements / "Testco").exists(), "a preview makes no folder"
    assert "2 of them would move to another folder" in said
    assert "-> Testco/Checking 1111/2026-09-12 Monthly Statement.pdf" in said
    code, said = bank.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert bank.where() == IN_FOLDERS
    bank.follows()
    code, said = bank.rename(apply_changes=False)
    assert "Every file is already named the way this app names them." in said, said


def test_rename_back_to_the_default_moves_each_file_back_and_takes_its_folders_away(bank):
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    assert bank.rename()[0] == 0
    storage.set_filename_patterns({})
    code, said = bank.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert bank.where() == flat_names()
    bank.follows()
    assert sorted(p.name for p in bank.paths.statements.iterdir()) == sorted(
        Path(p).name for p in flat_names().values()), "every folder it made is gone"
    assert bank.paths.statements.is_dir() and bank.paths.manual_review.is_dir()


def test_a_file_whose_name_stays_moves_when_only_its_folders_change(tmp_path):
    """The name a file has, given folders by the new pattern or losing them,
    is a move all the same, and was taken for a file named right."""
    bank = Bank(tmp_path)
    storage.set_filename_patterns({"filename_pattern": "{date:yyyy-mm-dd} {account} {summary}"})
    for account in ACCOUNTS:
        bank.saved(account)
    flat = {body_of(a): "Statements/2026-09-12 %s Monthly Statement.pdf" % a for a in ACCOUNTS}
    assert bank.where() == flat
    storage.set_filename_patterns(
        {"filename_pattern": "{year}/{date:yyyy-mm-dd} {account} {summary}"})
    code, said = bank.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert bank.where() == {b: p.replace("Statements/", "Statements/2026/")
                            for b, p in flat.items()}
    bank.follows()
    storage.set_filename_patterns({"filename_pattern": "{date:yyyy-mm-dd} {account} {summary}"})
    code, said = bank.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert bank.where() == flat
    assert not (bank.paths.statements / "2026").exists()
    bank.follows()


def test_a_folder_holding_anything_else_is_kept(bank):
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    assert bank.rename()[0] == 0
    mine = bank.paths.statements / "Testco" / ACCOUNTS[0] / "my notes.txt"
    mine.write_text("somebody's own", encoding="utf-8")
    storage.set_filename_patterns({})
    assert bank.rename()[0] == 0
    assert mine.read_text(encoding="utf-8") == "somebody's own"
    assert not (bank.paths.statements / "Testco" / ACCOUNTS[1]).exists()


def test_a_file_in_manual_review_stays_there_with_no_folders(tmp_path):
    bank = Bank(tmp_path)
    put_aside = bank.saved(ACCOUNTS[0], folder=bank.paths.manual_review)
    bank.saved(ACCOUNTS[1])
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename()
    assert code == 0, said
    where = bank.where()
    assert where[body_of(ACCOUNTS[0])] == \
        "Manual Review/2026-09-12 Monthly Statement.pdf", said
    assert put_aside.parent == bank.paths.manual_review
    assert where[body_of(ACCOUNTS[1])] == IN_FOLDERS[body_of(ACCOUNTS[1])]
    assert sorted(p.name for p in bank.paths.manual_review.iterdir()) == \
        ["2026-09-12 Monthly Statement.pdf"]


@pytest.mark.parametrize("how", ["climbs", "link"])
def test_a_file_is_filed_where_it_really_is_however_its_path_is_spelled(tmp_path, how):
    """A recorded path that climbs out of Statements through "..", or goes
    through a link inside Statements, names a file in another of the app's
    folders. Taken by its spelling for one filed in Statements, a statement
    put aside in Manual Review was moved into the pattern's folders there,
    and a tax form was moved into Statements under the default pattern."""
    bank = Bank(tmp_path)
    statements = bank.paths.statements
    links = set()
    if how == "climbs":
        if os.name != "nt":
            # Windows takes each ".." off the spelling and POSIX climbs the
            # folders themselves, so there a path climbs only through a
            # folder that is there, as Chase was when the file was saved.
            (statements / "Chase").mkdir()
            links = {"Chase"}
        aside = os.path.join(str(statements), "Chase", "..", "..", "Manual Review", "")
        tax = os.path.join(str(statements), "Chase", "..", "..", "Tax Documents", "")
    else:
        link_folder(bank.paths.manual_review, statements / "aside")
        link_folder(bank.paths.tax_documents, statements / "tax")
        aside, tax = str(statements / "aside") + os.sep, str(statements / "tax") + os.sep
        links = {"aside", "tax"}
    name = "2026-09-12 Testco Monthly Statement.pdf"
    bank.saved(ACCOUNTS[0], folder=bank.paths.manual_review, spelled=aside + name)
    bank.saved(ACCOUNTS[1], folder=bank.paths.tax_documents, spelled=tax + name)
    code, said = bank.rename(apply_changes=False)
    assert "Every file is already named the way this app names them." in said, said
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename()
    assert code == 0, said
    real = {p.read_bytes(): p.resolve() for p in bank.out.rglob("*.pdf") if not p.is_symlink()}
    assert real[body_of(ACCOUNTS[0])] == \
        (bank.paths.manual_review / "2026-09-12 Monthly Statement.pdf").resolve(), said
    assert real[body_of(ACCOUNTS[1])] == (bank.paths.tax_documents / "Testco" / ACCOUNTS[1]
                                          / "2026-09-12 Monthly Statement.pdf").resolve(), said
    assert {p.name for p in statements.iterdir()} == links, "nothing moved into Statements"


def test_a_file_already_in_the_folder_it_moves_to_is_never_written_over(bank):
    """A file nobody's ledger names, in the folder a statement moves to,
    under the name it would take, is another file, and the statement is
    told apart beside it."""
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    theirs = bank.paths.statements / "Testco" / ACCOUNTS[0] / "2026-09-12 Monthly Statement.pdf"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"%PDF- somebody's own file")
    code, said = bank.rename()
    assert code == 0, said
    assert theirs.read_bytes() == b"%PDF- somebody's own file"
    assert bank.where()[body_of(ACCOUNTS[0])] == \
        "Statements/Testco/Checking 1111/2026-09-12 Monthly Statement (2).pdf"
    bank.follows()


def test_an_index_that_cannot_be_written_puts_every_file_back_and_its_folders_go(
        bank, monkeypatch):
    real = storage.atomic_write_text

    def refuse(path, text, encoding="utf-8", **how):
        if Path(path).name == INDEX:
            raise PermissionError("%s stayed locked." % path)
        return real(path, text, encoding, **how)

    monkeypatch.setattr(storage, "atomic_write_text", refuse)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
    monkeypatch.setattr(storage, "free_to_write", lambda *_a, **_kw: True)
    monkeypatch.setattr(renaming, "free_to_write", lambda *_a, **_kw: True)
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename()
    assert code == 1, said
    assert "every file was put back under the name it had" in said, said
    assert bank.where() == flat_names()
    assert not (bank.paths.statements / "Testco").exists(), "a folder made for nothing"
    monkeypatch.setattr(storage, "atomic_write_text", real)
    bank.follows()


def test_a_move_refused_partway_takes_away_only_the_folder_it_left_empty(bank, monkeypatch):
    real = renaming._retried_rename

    def refuse_the_second(source, target):
        if ACCOUNTS[1] in str(target):
            raise PermissionError(13, "held by another program", str(source))
        return real(source, target)

    monkeypatch.setattr(renaming, "_retried_rename", refuse_the_second)
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename()
    assert code == 0 and "Renamed 1 file(s)." in said, said
    where = bank.where()
    assert where[body_of(ACCOUNTS[0])] == IN_FOLDERS[body_of(ACCOUNTS[0])]
    assert where[body_of(ACCOUNTS[1])] == flat_names()[body_of(ACCOUNTS[1])]
    assert not (bank.paths.statements / "Testco" / ACCOUNTS[1]).exists()
    bank.follows()


def test_a_folder_leading_out_on_the_server_leaves_that_file_and_writes_the_rest(
        bank, monkeypatch):
    """On PaperPull Server a folder reached through a link out of the data
    folder stops a run before it writes there. Stopping a Rename partway
    would leave the files it had moved with ledgers naming where they were,
    so that one file stays where it is, as a move refused does."""
    from paperpull_core import shared_folder
    real = shared_folder.hold

    def hold(path):
        if ACCOUNTS[1] in str(path):
            raise shared_folder.LeadsOut("%s leads outside the data folder" % path)
        return real(path)

    monkeypatch.setattr(shared_folder, "hold", hold)
    storage.set_filename_patterns({"filename_pattern": FOLDERS})
    code, said = bank.rename()
    assert code == 0 and "Renamed 1 file(s)." in said, said
    where = bank.where()
    assert where[body_of(ACCOUNTS[0])] == IN_FOLDERS[body_of(ACCOUNTS[0])]
    assert where[body_of(ACCOUNTS[1])] == flat_names()[body_of(ACCOUNTS[1])]
    bank.follows()


def test_a_name_two_files_in_two_folders_had_is_followed_by_neither():
    """A record or row knowing a file by its name alone, as the order
    history does, cannot say which of two files of one name it is once
    each has gone to a name of its own, so it keeps the name it had."""
    c1 = renaming.Change({}, Path("A") / "x.pdf", "y.pdf", new_path=Path("A") / "y.pdf")
    c2 = renaming.Change({}, Path("B") / "x.pdf", "z.pdf", new_path=Path("B") / "z.pdf")
    result = renaming.Result()
    renaming._renamed(c1, result)
    renaming._renamed(c2, result)
    rows = [{"PDF Filename": "x.pdf"}]
    assert renaming.update_rows(rows, result) == 0 and rows == [{"PDF Filename": "x.pdf"}]

    class Store:
        data = {"k": {"pdf_filename": "x.pdf"}}

        def update(self, *a, **kw):
            raise AssertionError("a record knowing the name alone was moved")

        def save(self):
            pass

    assert renaming.update_progress(Store(), result) == 0
    c1.row = c2.row = {"Order or Receipt Number": "ORD1"}
    result.mapping = {str(c1.old_path): str(c1.new_path), str(c2.old_path): str(c2.new_path)}
    assert renaming._numbered([c1, c2], result) == {}
