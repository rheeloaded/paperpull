"""A record's account_folder leads the folders its name is filed in (#169).

ING's Postbox shows one tab per account a sign-in holds, a parent's own and
each child's, and MelleD asked that each account's documents go into a
folder named after its tab. A folder put there by the app alone would be one
Rename and the documents folder's Move do not know, and Rename would move
the file back. So the folder is part of the name, where a naming pattern's
folders are (storage.build_pdf_filename), and a download, Rename and the
Move build it in one place. A record without it is named as it always was,
in every app.

Every name here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import storage  # noqa: E402
from paperpull_core.spec import AppSpec, DOCUMENT, Folder, INFRASTRUCTURE_FOLDERS  # noqa: E402

RECORD = {"category": "Statement", "date": "2026-01-31", "summary": "Kontoauszug"}


@pytest.fixture
def bank(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(storage, name, getattr(storage, name))
    spec = AppSpec(provider="Bank", project_dir=tmp_path, kind=DOCUMENT,
                   folders=[Folder("statements", "Kontoauszuege"), *INFRASTRUCTURE_FOLDERS],
                   default_route="statements")
    storage.bind(spec)
    storage.set_filename_patterns({})
    return spec


def named(pattern=None, **record):
    return storage.build_pdf_filename("2026-01-31", "Kontoauszug", "",
                                      record=dict(RECORD, **record), pattern=pattern)


def test_a_record_without_an_account_folder_is_named_as_it_always_was(bank):
    plain = named()
    assert named(account_folder="") == plain and named(account_folder="") .folder == ""
    assert plain.folder == ""
    assert named(pattern="{year}/{date} {summary}").folder == "2026"


def test_the_account_folder_leads_the_patterns_folders(bank):
    name = named(account_folder="Mia Muster")
    assert str(name) == str(named()) and name.folder == "Mia Muster"
    with_year = named(pattern="{year}/{date} {summary}", account_folder="Mia Muster")
    assert with_year.folder == "Mia Muster/2026"


def test_an_object_record_carries_it_too(bank):
    class Doc:
        category, date, summary = "Statement", "2026-01-31", "Kontoauszug"
        account_folder = "Mia Muster"
    assert storage.build_pdf_filename("2026-01-31", "Kontoauszug", "", record=Doc()).folder \
        == "Mia Muster"


@pytest.mark.parametrize("unsafe", ["..", "../x", "a/b", "a\\b", " Mia", "Mia.", "CON", "x" * 61,
                                    "Mia:Muster", 7, None])
def test_an_account_folder_that_is_not_safe_as_it_stands_files_nothing_anywhere_new(bank, unsafe):
    assert named(account_folder=unsafe).folder == ""


def test_account_folder_name_makes_a_tab_safe_as_a_pattern_folder(bank):
    assert storage.account_folder_name("Mia Muster") == "Mia Muster"
    assert storage.account_folder_name("Mia:Muster.") == "MiaMuster"
    assert storage.account_folder_name("...") == ""
    made = storage.account_folder_name("x" * 200)
    assert made and storage.account_folder_name(made) == made


def test_a_download_and_rename_file_it_in_the_same_folder(bank, tmp_path):
    kind = tmp_path / "out" / "Kontoauszuege"
    kind.mkdir(parents=True)
    name = named(account_folder="Mia Muster")
    path = storage.unique_path(kind, name, 240)
    assert path.parent == kind / "Mia Muster"
    assert storage.filing_folder(kind, name, 240) == kind / "Mia Muster"
