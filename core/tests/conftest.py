"""Bind a representative AppSpec before each core test.

The core is provider-agnostic but a few helpers (filenames, PDF validation
messages) need *some* provider bound. Tests that care about the unbound case
clear it themselves.
"""
import itertools
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


@pytest.fixture(scope="session")
def _project_dirs(tmp_path_factory):
    """Where a test that has no tmp_path gets the folder its spec is bound
    to, and the number of the next one."""
    return tmp_path_factory.mktemp("bound"), itertools.count()


@pytest.fixture(autouse=True)
def bound_spec(request, _project_dirs):
    # A test that has tmp_path binds that, as every test once did. One that
    # has not gets an empty folder of its own all the same. pytest lists
    # every folder it has made in the run before it makes the next tmp_path,
    # so each one cost more than the last. Made for each of ten thousand
    # tests, most of which never touch it, that came to a minute and a half
    # on Windows.
    if "tmp_path" in request.fixturenames:
        project_dir = request.getfixturevalue("tmp_path")
    else:
        root, numbers = _project_dirs
        project_dir = root / str(next(numbers))
        project_dir.mkdir()
    storage.bind(make_spec(project_dir))
    storage.set_filename_owner("")
    yield storage.spec()
    storage.set_filename_owner("")
