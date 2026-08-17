"""Bind a representative AppSpec before each core test.

The core is provider-agnostic but a few helpers (filenames, PDF validation
messages) need *some* provider bound. Tests that care about the unbound case
clear it themselves.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import storage
from paperpull_core.spec import (AppSpec, CsvSpec, DOCUMENT, Folder,
                                 INFRASTRUCTURE_FOLDERS)


def make_spec(project_dir) -> AppSpec:
    return AppSpec(
        provider="Testco",
        project_dir=project_dir,
        kind=DOCUMENT,
        folders=[Folder("statements", "Statements"),
                 Folder("other_documents", "Other Documents", precreate=False),
                 *INFRASTRUCTURE_FOLDERS],
        routes={"Statement": "statements"},
        default_route="other_documents",
        csv_files=[CsvSpec("document_index_csv", "{provider} Document Index.csv",
                           ["Account Holder", "Document Date", "Notes"])],
    )


@pytest.fixture(autouse=True)
def bound_spec(tmp_path):
    storage.bind(make_spec(tmp_path))
    storage.set_filename_owner("")
    yield storage.spec()
    storage.set_filename_owner("")
