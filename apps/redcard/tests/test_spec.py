"""Locks in the facts that must not drift when this app moves onto the core.

Every expected value here was taken from the app's own code as it was BEFORE
the shared-core migration. If any of them changed, an existing archive would
be stranded: a renamed CSV orphans the index, a moved folder hides the
documents, and a different provider string renames every new PDF.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage


def test_provider_string_is_unchanged():
    """This string is embedded in every PDF filename."""
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-01-02", "thing", "Statement") ==         "2026-01-02 Target Circle Card Thing Statement.pdf"


def test_csv_filenames_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.document_index_csv.name == "Target Circle Card Document Index.csv"


def test_precreated_folders_are_unchanged(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ['Backups', 'Diagnostics', 'Logs', 'Manual Review', 'Statements', 'Tax Documents', 'Year-End Summaries']


def test_every_declared_route_resolves(tmp_path):
    paths = storage.Paths(tmp_path)
    for key in storage.SPEC.routes:
        assert paths.folder_for(key).is_dir()
