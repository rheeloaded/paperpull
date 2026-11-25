"""A documents folder per account (#201).

An account's config can name account_documents_dirs:
    "documents_dir": "/path/to/Default",
    "account_documents_dirs": {
        "Checking 1111": "/path/to/Banking",
        "Credit Card 2222": "/path/to/CreditCards"
    }

Each entry is held to the same safety rules as documents_dir (a full path,
not inside a browser profile, not holding/inside output_dir, inside data folder
on server). If an entry fails validation, it is refused and falls back to
documents_dir.

The Move (PAPERPULL_MOVE_DOCUMENTS=1) takes each account's documents to its own
folder, with ledgers and records following.

When an account listed in account_documents_dirs was not matched among the
listed accounts, a diagnostic warning is given to alert the user that the site
may have renamed the account.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import renaming, storage
from paperpull_core.storage import Paths
from test_documents_folder import (ACCOUNTS, BEFORE, FIRST, SECOND, Office,
                                   body_of, moving)

DATE = "2026-09-12"


@pytest.fixture(autouse=True)
def no_pattern():
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def write_cfg(folder: Path, settings: dict, name: str = "config.json") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Configuration and Validation
# ---------------------------------------------------------------------------

def test_account_documents_dirs_reaches_paths(tmp_path, capsys):
    out = tmp_path / "out"
    docs_default = tmp_path / "WatchedDefault"
    docs_checking = tmp_path / "WatchedChecking"
    docs_card = tmp_path / "WatchedCard"

    cfg = storage.load_config(write_cfg(tmp_path / "app", {
        "output_dir": str(out),
        "documents_dir": str(docs_default),
        "account_documents_dirs": {
            "Checking 1111": str(docs_checking),
            "Credit Card 2222": str(docs_card),
        }
    }))
    assert cfg["documents_dir"] == str(docs_default)
    assert cfg["account_documents_dirs"] == {
        "Checking 1111": str(docs_checking),
        "Credit Card 2222": str(docs_card),
    }

    paths = Paths(out)
    assert paths.documents == docs_default
    assert paths.documents_for("Checking 1111") == docs_checking
    assert paths.documents_for("Credit Card 2222") == docs_card
    assert paths.documents_for("Savings 3333") == docs_default
    assert paths.documents_for(None) == docs_default
    assert paths.documents_for("") == docs_default
    assert capsys.readouterr().out == ""


def test_invalid_account_documents_dirs_entries_fall_back(tmp_path, capsys):
    out = tmp_path / "out"
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    docs_default = tmp_path / "Default"

    # 1. Relative path
    # 2. Inside profile
    # 3. Holding output folder
    # 4. Empty/whitespace
    cfg = storage.load_config(write_cfg(tmp_path / "app", {
        "output_dir": str(out),
        "profile_dir": str(profile),
        "documents_dir": str(docs_default),
        "account_documents_dirs": {
            "Rel Acc": "relative/path",
            "Prof Acc": str(profile / "sub"),
            "Out Acc": str(tmp_path),  # holds out
            "Empty Acc": "   ",
            "Good Acc": str(tmp_path / "Good"),
        }
    }))
    err = capsys.readouterr().out
    assert "The documents folder for 'Rel Acc'" in err
    assert "The documents folder for 'Prof Acc'" in err
    assert "The documents folder for 'Out Acc'" in err
    assert "Good Acc" not in err

    assert cfg["account_documents_dirs"] == {
        "Good Acc": str(tmp_path / "Good")
    }

    paths = Paths(out)
    assert paths.documents_for("Rel Acc") == docs_default
    assert paths.documents_for("Prof Acc") == docs_default
    assert paths.documents_for("Out Acc") == docs_default
    assert paths.documents_for("Good Acc") == tmp_path / "Good"


def test_server_account_documents_dirs_checks_data_folder(tmp_path, monkeypatch):
    """On PaperPull Server, entries in account_documents_dirs must be inside data folder."""
    data = tmp_path / "data"
    data.mkdir()
    install = data / "app"
    install.mkdir()
    out = data / "out"
    outside = tmp_path / "outside"

    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.chdir(install)

    cfg = {"output_dir": str(out), "documents_dir": str(data / "Docs"),
           "account_documents_dirs": {"Outside": str(outside)}}
    with pytest.raises(SystemExit) as stopped:
        storage.hold_to_the_server(cfg, install / "config.json")
    assert "'Outside' documents" in str(stopped.value)
    assert "outside" in str(stopped.value)


# ---------------------------------------------------------------------------
# Filing folders and discovery of roots
# ---------------------------------------------------------------------------

def test_filing_folders_includes_all_account_destinations(tmp_path):
    out = tmp_path / "out"
    docs_default = tmp_path / "Default"
    docs_checking = tmp_path / "Checking"
    docs_card = tmp_path / "Card"

    storage.load_config(write_cfg(tmp_path / "app", {
        "output_dir": str(out),
        "documents_dir": str(docs_default),
        "account_documents_dirs": {
            "Checking 1111": str(docs_checking),
            "Credit Card 2222": str(docs_card),
        }
    }))

    paths = Paths(out)
    folders = paths.filing_folders()
    # Should include out/Statements, Default/Statements, Checking/Statements, Card/Statements
    folder_paths = [Path(f) for f in folders]
    assert out / "Statements" in folder_paths
    assert docs_default / "Statements" in folder_paths
    assert docs_checking / "Statements" in folder_paths
    assert docs_card / "Statements" in folder_paths


def test_remember_documents_writes_all_account_folders(tmp_path):
    out = tmp_path / "out"
    docs_default = tmp_path / "Default"
    docs_checking = tmp_path / "Checking"

    storage.load_config(write_cfg(tmp_path / "app", {
        "output_dir": str(out),
        "documents_dir": str(docs_default),
        "account_documents_dirs": {
            "Checking 1111": str(docs_checking),
        }
    }))

    paths = Paths(out)
    paths.remember_documents()

    remembered = json.loads(paths.documents_folders_json.read_text(encoding="utf-8"))
    assert str(docs_default) in remembered
    assert str(docs_checking) in remembered


# ---------------------------------------------------------------------------
# Move documents per account
# ---------------------------------------------------------------------------

def test_move_carries_each_account_to_its_folder(tmp_path, monkeypatch):
    office = Office(tmp_path)
    docs_checking = tmp_path / "Checking"
    docs_card = tmp_path / "Card"

    office.paths = Paths(
        office.out,
        documents_dir=str(office.docs),
        account_documents_dirs={
            ACCOUNTS[0]: str(docs_checking),
            ACCOUNTS[1]: str(docs_card),
        }
    )
    office.paths.ensure()

    first_file = office.saved(ACCOUNTS[0])
    second_file = office.saved(ACCOUNTS[1])

    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0, said
    assert "Moved 2 file(s)" in said

    target_first = docs_checking / "Statements" / FIRST
    target_second = docs_card / "Statements" / SECOND

    assert target_first.is_file()
    assert target_second.is_file()
    assert not first_file.exists()
    assert not second_file.exists()

    # Index and progress updated
    rows = office.index_csv.read_all()
    rows_by_acc = {r["Account"]: r for r in rows}
    assert rows_by_acc[ACCOUNTS[0]]["PDF Full Path"] == str(target_first)
    assert rows_by_acc[ACCOUNTS[1]]["PDF Full Path"] == str(target_second)

    rec0 = office.progress.data[ACCOUNTS[0]]
    rec1 = office.progress.data[ACCOUNTS[1]]
    assert rec0["pdf_path"] == str(target_first)
    assert rec1["pdf_path"] == str(target_second)


def test_move_flat_carries_each_account_to_its_folder_without_kind(tmp_path, monkeypatch):
    """When kind_folders is false, each account moves to the root of its folder."""
    office = Office(tmp_path)
    docs_checking = tmp_path / "Checking"
    docs_card = tmp_path / "Card"

    office.paths = Paths(
        office.out,
        documents_dir=str(office.docs),
        account_documents_dirs={
            ACCOUNTS[0]: str(docs_checking),
            ACCOUNTS[1]: str(docs_card),
        },
        kind_folders=False,
    )
    office.paths.ensure()

    first_file = office.saved(ACCOUNTS[0])
    second_file = office.saved(ACCOUNTS[1])

    moving(monkeypatch)
    code, said = office.rename()
    assert code == 0, said
    assert "Moved 2 file(s)" in said

    target_first = docs_checking / FIRST
    target_second = docs_card / SECOND

    assert target_first.is_file()
    assert target_second.is_file()
    assert not first_file.exists()
    assert not second_file.exists()

    # Verify tracked in flat filed records
    assert office.paths.filed_here(target_first)
    assert office.paths.filed_here(target_second)


# ---------------------------------------------------------------------------
# Diagnostic: Warning when account map entry matched no listed accounts
# ---------------------------------------------------------------------------

def test_unmatched_account_warning(tmp_path):
    out = tmp_path / "out"
    storage.load_config(write_cfg(tmp_path / "app", {
        "output_dir": str(out),
        "documents_dir": str(tmp_path / "Default"),
        "account_documents_dirs": {
            "Credit Card ...1111": str(tmp_path / "Card1"),
            "Old Loan ...9999": str(tmp_path / "Loan"),
        }
    }))
    paths = Paths(out)

    listed_accounts = ["Credit Card ...1111", "Checking ...2222"]

    lines = []
    storage.check_account_documents_dirs_matched(paths, listed_accounts, say=lines.append)
    assert len(lines) == 1
    assert lines[0] == "The account documents folder setting for 'Old Loan ...9999' matched no listed account."
