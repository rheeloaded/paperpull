"""Documents filed straight into the documents folder, with no folder of
their kind (#201).

Every document is filed in a folder of its kind, Statements or Tax
Documents and the like, before the folders a naming pattern makes. For a
provider that files one kind, that is a folder that says nothing:

    9 Utilities/PG&E/Statements/2026/2026-10-07 Statement.pdf

"kind_folders": false in an account's config files its documents straight
into its documents folder instead:

    9 Utilities/PG&E/2026/2026-10-07 Statement.pdf

It changes only the documents folder. A download is written and checked
in the folder of its kind in the output folder as it always was, a file
that fails its check is put aside in Manual Review there, and Logs,
Diagnostics, Backups and the records stay where they are. The Move takes
each document out of the folder of its kind, in the output folder and in
the documents folder alike, keeping the folders a pattern made inside it.

A provider filing more than one kind would mix them in one folder, and two
of them could want one file name, so the setting is refused there, before
anything is saved or moved, unless the pattern names {kind}. It is refused
as well with no documents folder, since documents would then sit loose
beside the run's records.

Every folder is a throwaway one under tmp_path, and every name and account
is invented.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import renaming, storage  # noqa: E402
from paperpull_core.spec import AppSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS  # noqa: E402
from paperpull_core.storage import Paths  # noqa: E402
from test_documents_folder import (ACCOUNTS, BEFORE, FIRST, SECOND, Office, body_of,  # noqa: E402
                                   moving, write)


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def one_kind(project_dir) -> AppSpec:
    """A provider that files statements and nothing else."""
    return AppSpec(provider="Utilico", project_dir=project_dir, kind=DOCUMENT,
                   folders=[Folder("statements", "Statements"), *INFRASTRUCTURE_FOLDERS],
                   routes={"Statement": "statements"}, default_route="statements")


# -- where everything goes ---------------------------------------------------------------

def test_without_kind_folders_every_kind_goes_to_the_documents_folder_itself(tmp_path):
    out, docs = tmp_path / "out", tmp_path / "Watched"
    paths = Paths(out, documents_dir=str(docs), kind_folders=False)
    assert paths.folder_for("Statement") == out / "Statements", (
        "a download is written and checked where it always was")
    assert paths.documents_moves() == {
        out / "Statements": docs, out / "Other Documents": docs,
        docs / "Statements": docs, docs / "Other Documents": docs}
    assert docs in paths.filing_folders()


def test_kind_folders_are_kept_unless_the_config_says_otherwise(tmp_path):
    out, docs = tmp_path / "out", tmp_path / "Watched"
    assert Paths(out, documents_dir=str(docs)).documents_moves() == {
        out / "Statements": docs / "Statements",
        out / "Other Documents": docs / "Other Documents"}


# -- the setting, as load_config reads it -------------------------------------------------

def test_the_setting_reaches_the_paths_every_app_builds(tmp_path, capsys):
    out, docs = tmp_path / "out", tmp_path / "Watched"
    cfg = storage.load_config(write(tmp_path / "app", {
        "output_dir": str(out), "documents_dir": str(docs), "kind_folders": False}))
    assert Paths(Path(cfg["output_dir"])).documents_moves()[out / "Statements"] == docs
    assert capsys.readouterr().out == ""


def test_a_provider_of_several_kinds_with_no_kind_in_its_pattern_is_refused(tmp_path):
    """Statements and Other Documents in one folder, with nothing in a name
    to say which is which, and two of them could want one name."""
    out, docs = tmp_path / "out", tmp_path / "Watched"
    with pytest.raises(SystemExit) as stop:
        storage.load_config(write(tmp_path / "app", {
            "output_dir": str(out), "documents_dir": str(docs), "kind_folders": False,
            "filename_pattern": "{year}/{date} {account}"}))
    said = str(stop.value)
    assert "Statements" in said and "Other Documents" in said and "{kind}" in said, said
    assert not out.exists() and not docs.exists()


@pytest.mark.parametrize("pattern", ["{year}/{date} {account} {kind}",
                                     "{kind}/{date} {account}",
                                     "{date}[ {number|kind}]"])
def test_a_pattern_naming_the_kind_lets_several_kinds_share_the_folder(tmp_path, pattern):
    cfg = storage.load_config(write(tmp_path / "app", {
        "output_dir": str(tmp_path / "out"), "documents_dir": str(tmp_path / "Watched"),
        "kind_folders": False, "filename_pattern": pattern}))
    assert cfg["kind_folders"] is False


def test_the_usual_names_carry_the_kind_already(tmp_path):
    storage.load_config(write(tmp_path / "app", {
        "output_dir": str(tmp_path / "out"), "documents_dir": str(tmp_path / "Watched"),
        "kind_folders": False}))


def test_a_provider_of_one_kind_needs_no_kind_in_its_pattern(tmp_path):
    storage.bind(one_kind(tmp_path))
    out, docs = tmp_path / "out", tmp_path / "Watched"
    storage.load_config(write(tmp_path / "app", {
        "output_dir": str(out), "documents_dir": str(docs), "kind_folders": False,
        "filename_pattern": "{year}/{date} Statement"}))
    assert Paths(out).documents_moves() == {out / "Statements": docs,
                                            docs / "Statements": docs}


@pytest.mark.parametrize("documents", ["", "same"], ids=["none", "the output folder"])
def test_without_a_documents_folder_of_its_own_the_setting_is_refused(tmp_path, documents):
    """Documents would otherwise sit loose beside progress.json, the index
    and Logs."""
    out = tmp_path / "out"
    settings = {"output_dir": str(out), "kind_folders": False}
    if documents:
        settings["documents_dir"] = str(out)
    with pytest.raises(SystemExit) as stop:
        storage.load_config(write(tmp_path / "app", settings))
    assert "documents_dir" in str(stop.value)


@pytest.mark.parametrize("given", ["false", 0, None, "no"])
def test_a_setting_that_is_not_true_or_false_is_refused(tmp_path, given):
    with pytest.raises(SystemExit) as stop:
        storage.load_config(write(tmp_path / "app", {
            "output_dir": str(tmp_path / "out"), "documents_dir": str(tmp_path / "Watched"),
            "kind_folders": given}))
    assert "kind_folders" in str(stop.value)


def test_one_account_without_kind_folders_leaves_the_next_with_them(tmp_path):
    app = tmp_path / "app"
    first, second = tmp_path / "first", tmp_path / "second"
    storage.load_config(write(app, {"output_dir": str(first), "kind_folders": False,
                                    "documents_dir": str(tmp_path / "A")}))
    storage.load_config(write(app, {"output_dir": str(second),
                                    "documents_dir": str(tmp_path / "B")}, "config.b.json"))
    assert Paths(first).documents_moves()[first / "Statements"] == tmp_path / "A"
    assert Paths(second).documents_moves()[second / "Statements"] == tmp_path / "B" / "Statements"


# -- the move -----------------------------------------------------------------------------

@pytest.fixture
def office(tmp_path):
    """Two statements saved in the output folder, then a documents folder
    set without kind folders."""
    office = Office(tmp_path)
    for account in ACCOUNTS:
        office.saved(account)
    flat(office)
    assert office.where() == BEFORE
    return office


def flat(office):
    office.paths = Paths(office.out, documents_dir=str(office.docs), kind_folders=False)
    office.paths.ensure()


def test_the_move_files_each_document_in_the_documents_folder_itself(office, monkeypatch):
    aside = office.saved("Brokerage 3333", aside=True)
    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s) to %s." % office.docs in said, said
    where = office.where()
    assert where[body_of(ACCOUNTS[0])] == "Watched/" + FIRST
    assert where[body_of(ACCOUNTS[1])] == "Watched/" + SECOND
    assert where[body_of("Brokerage 3333")] == "out/Manual Review/" + aside.name
    office.follows()
    code, said = office.rename(apply_changes=False)
    assert "would be moved" not in said, said
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)
    code, said = office.rename(apply_changes=False)
    assert "Every file is already named the way this app names them." in said, said


def test_documents_moved_with_kind_folders_come_out_of_them(tmp_path, monkeypatch):
    """The documents folder was set first with kind folders, and the
    statements went to Watched/Statements, in the folders their pattern made
    there. Without kind folders the next Move brings them up a folder, the
    pattern's folders kept."""
    storage.set_filename_patterns({"filename_pattern": "{year}/{date} {account}"})
    office = Office(tmp_path)
    for account in ACCOUNTS:
        office.saved(account)
    office.build(documents=True)
    moving(monkeypatch)
    assert office.rename()[0] == 0
    assert office.where() == {body_of(a): "Watched/Statements/2026/2026-09-12 %s.pdf" % a
                              for a in ACCOUNTS}
    flat(office)
    code, said = office.rename()
    assert code == 0 and "Moved 2 file(s)" in said, said
    assert office.where() == {body_of(a): "Watched/2026/2026-09-12 %s.pdf" % a
                              for a in ACCOUNTS}
    office.follows()
    assert not (office.docs / "Statements").exists(), "the kind folder it emptied is taken away"


def test_a_rename_in_the_documents_folder_keeps_it_free_of_kind_folders(office, monkeypatch):
    moving(monkeypatch)
    assert office.rename()[0] == 0
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)
    storage.set_filename_patterns({"filename_pattern": "{year}/{date} {account}"})
    code, said = office.rename()
    assert code == 0 and "Renamed 2 file(s)." in said, said
    assert office.where() == {body_of(a): "Watched/2026/2026-09-12 %s.pdf" % a
                              for a in ACCOUNTS}
    office.follows()


def test_documents_filed_without_kind_folders_stay_put_when_the_setting_is_taken_out(
        office, monkeypatch):
    """Setting it back moves nothing back into a folder of a kind, and a
    Rename leaves each document where it is."""
    moving(monkeypatch)
    assert office.rename()[0] == 0
    office.build(documents=True)
    code, said = office.rename(apply_changes=False)
    assert code == 0 and "would be moved" not in said, said
    monkeypatch.delenv(renaming.MOVE_DOCUMENTS_ENV)
    code, said = office.rename(apply_changes=False)
    assert code == 0 and "Every file is already named the way this app names them." in said, said
    assert "name something other than a PDF" not in said, "each document is still the app's"
    assert office.where() == {body_of(ACCOUNTS[0]): "Watched/" + FIRST,
                              body_of(ACCOUNTS[1]): "Watched/" + SECOND}
