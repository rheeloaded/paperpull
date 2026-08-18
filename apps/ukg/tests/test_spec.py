"""UKG's own facts, and the guards that matter most on a payroll site."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import ukg_site as site


def test_provider_and_csv_name(tmp_path):
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-08-15", "august 15", "Pay Statement") == \
        "2026-08-15 UKG August 15 Pay Statement.pdf"
    assert storage.Paths(tmp_path).document_index_csv.name == "UKG Document Index.csv"


def test_precreated_folders(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert made == ["Backups", "Diagnostics", "Logs", "Manual Review",
                    "Pay Statements", "Tax Documents"]


def test_routing(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.folder_for("Statement").name == "Pay Statements"
    assert paths.folder_for("Tax Document").name == "Tax Documents"
    assert paths.folder_for("Year-End Summary").name == "Year-End Summaries"
    assert paths.folder_for("Something Else").name == "Other Documents"


# --- the tenant address -----------------------------------------------------

def test_base_url_comes_from_config_not_code():
    """Every employer has its own UKG tenant, and the address identifies the
    employer - so it must never be baked into the repo."""
    source = (Path(__file__).resolve().parents[1] / "ukg_site.py").read_text(encoding="utf-8")
    assert 'BASE = ""' in source
    for host in (".ultipro.com/", ".saashr.com/"):
        assert f"https://{host}" not in source


def test_configure_sets_the_urls():
    site.configure("https://example.ultipro.com/")
    assert site.is_configured()
    assert site.URLS["home"] == "https://example.ultipro.com"


def test_unconfigured_is_reported_clearly():
    site.configure("")
    assert not site.is_configured()
    assert "base_url" in site.configuration_help()


# --- the read-only guard ----------------------------------------------------

@pytest.mark.parametrize("control", [
    "Change Direct Deposit", "Edit Bank Account", "Update Routing Number",
    "Update W-4 Withholding", "Tax Withholding", "Change Address",
    "Change Password", "Open Enrollment", "Enroll in Benefits",
    "Request Time Off", "Submit Timecard", "Clock In", "Delete", "Cancel",
])
def test_destructive_payroll_controls_are_refused(control):
    """A payroll site can move where someone's wages land. These must never
    be clickable, whatever else changes."""
    assert site.is_safe_control(control) is False


@pytest.mark.parametrize("control", [
    "Download", "View Pay Statement", "Print Pay Stub", "Download PDF",
    "W-2", "View Earnings Statement", "Year-End Tax Form",
])
def test_document_controls_are_allowed(control):
    assert site.is_safe_control(control) is True


def test_unrecognised_controls_are_refused():
    """Deny by default: not on the allowlist means not clicked."""
    for name in ("Do The Thing", "Continue", "", "   ", "Next"):
        assert site.is_safe_control(name) is False


def test_the_orchestrator_imports():
    import importlib
    module = importlib.import_module("ukg_docs")
    assert hasattr(module, "main") and hasattr(module, "App")
