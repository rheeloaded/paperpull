"""Poppins Payroll's own facts: names, folders, routing and classification."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types

RULES = doc_types.load_rules()


def test_provider_and_csv_name(tmp_path):
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-03-13", "Pay Stub", "") == \
        "2026-03-13 Poppins Pay Stub.pdf"
    assert storage.Paths(tmp_path).document_index_csv.name == "Poppins Document Index.csv"


def test_precreated_folders(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ["Backups", "Diagnostics", "Logs", "Manual Review",
                    "Pay Stubs", "Tax Forms", "Tax Payment History"]


def test_routing(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.folder_for("Statement").name == "Pay Stubs"
    assert paths.folder_for("Tax Document").name == "Tax Forms"
    assert paths.folder_for("Year-End Summary").name == "Tax Payment History"
    assert paths.folder_for("Something Else").name == "Other Documents"


@pytest.mark.parametrize("title,category,summary", [
    ("Pay Stub February 28-March 6, 2026", doc_types.STATEMENT, "Pay Stub"),
    ("W-2 2025", doc_types.TAX, "W-2 Tax Form"),
    ("W-3 2025", doc_types.TAX, "W-3 Transmittal"),
    ("Schedule H 2025", doc_types.TAX, "Schedule H Household Employment Taxes"),
    ("Overtime premium report 2025", doc_types.TAX, "Overtime Premium Report"),
    ("Form IL-2848 2025", doc_types.TAX, "IL-2848 Power of Attorney"),
    ("Form 2848 2025", doc_types.TAX, "Form 2848 Power of Attorney"),
    ("Form SS4 2025", doc_types.TAX, "Form SS-4 Employer ID Number"),
    ("Power of Attorney for Representing Employer Under the Illinois "
     "Unemployment Insurance Act 2025", doc_types.TAX,
     "Illinois Unemployment Insurance Power of Attorney"),
    ("Federal Tax Payment History 2026-09-22", doc_types.YEAR_END,
     "Federal Tax Payment History"),
    ("State Tax Payment History 2026-09-22", doc_types.YEAR_END,
     "State Tax Payment History"),
])
def test_every_title_poppins_shows_is_classified(title, category, summary):
    got = doc_types.classify_document(title, RULES)
    assert got[:2] == (category, summary), title


def test_all_three_kinds_are_wanted_by_default():
    cfg = {"document_types": storage.SPEC.config_defaults["document_types"]}
    for cat in (doc_types.STATEMENT, doc_types.TAX, doc_types.YEAR_END):
        assert doc_types.wanted(cat, cfg)
