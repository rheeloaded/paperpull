"""Paylocity's own facts, and the guards that matter most on a payroll site."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import paylocity_site as site


def test_provider_and_csv_name(tmp_path):
    storage.set_filename_owner("")
    assert storage.build_pdf_filename("2026-08-15", "august 15", "Pay Statement") == \
        "2026-08-15 Paylocity August 15 Pay Statement.pdf"
    assert storage.Paths(tmp_path).document_index_csv.name == "Paylocity Document Index.csv"


def test_precreated_folders(tmp_path):
    paths = storage.Paths(tmp_path)
    paths.ensure()
    made = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    # No "Tax Documents": the app does not fetch tax forms yet, so the folder
    # would only sit there empty. It appears when one actually arrives.
    assert made == ["Backups", "Diagnostics", "Logs", "Manual Review",
                    "Pay Statements"]


def test_routing(tmp_path):
    paths = storage.Paths(tmp_path)
    assert paths.folder_for("Statement").name == "Pay Statements"
    assert paths.folder_for("Tax Document").name == "Tax Documents"
    assert paths.folder_for("Year-End Summary").name == "Year-End Summaries"
    assert paths.folder_for("Something Else").name == "Other Documents"


# --- one fixed address, not a per-employer tenant ---------------------------

def test_the_address_is_fixed_and_public():
    """Unlike UKG, Paylocity has one address. The employer is identified by the
    Company ID typed at sign-in, which this app never handles, so nothing here
    is per-tenant and there is no base_url to configure."""
    assert site.BASE == "https://access.paylocity.com"
    src = (Path(__file__).resolve().parents[1] / "paylocity_site.py").read_text(encoding="utf-8")
    assert "def configure(" not in src
    assert "base_url" not in src


def test_the_orchestrator_imports():
    import importlib
    module = importlib.import_module("paylocity_docs")
    assert hasattr(module, "main") and hasattr(module, "App")


# --- the API mechanism ------------------------------------------------------

def test_download_identity_packs_no_amount_and_no_url():
    """collect_documents identifies a statement by companyId|employeeId|
    historyId. That is everything the enqueue/poll/fetch flow needs, and it is
    not a URL, so a query-string change cannot silently fetch the wrong file."""
    rows = {"data": [
        {"id": 111, "documentNumber": "9001", "date": "2026-06-18T00:00:00",
         "type": "Regular", "amount": 1234.56, "companyId": "CO", "employeeId": "42"},
        {"id": 222, "documentNumber": "9002", "date": "2026-06-05T00:00:00",
         "type": "Regular", "amount": 2345.67, "companyId": "CO", "employeeId": "42"},
    ]}
    docs = _collect(rows)
    assert len(docs) == 2
    for d in docs:
        assert d.pdf_url.count("|") == 2
        assert not d.pdf_url.startswith("http")
        for amount in ("1234.56", "2345.67"):
            assert amount not in f"{d.title} {d.pdf_url} {d.date_text}"


def test_same_pay_date_statements_stay_distinct():
    """A regular and an off-cycle run share a date. Identical titles would
    collapse to one record and lose a statement silently."""
    rows = {"data": [
        {"id": 1, "documentNumber": "1001", "date": "2026-07-10T00:00:00",
         "type": "Regular", "companyId": "CO", "employeeId": "42"},
        {"id": 2, "documentNumber": "1002", "date": "2026-07-10T00:00:00",
         "type": "Bonus", "companyId": "CO", "employeeId": "42"},
        {"id": 3, "documentNumber": "1003", "date": "2026-06-18T00:00:00",
         "type": "Regular", "companyId": "CO", "employeeId": "42"},
    ]}
    docs = _collect(rows)
    assert len(docs) == 3
    assert len({d.title for d in docs}) == 3, [d.title for d in docs]


def test_date_is_read_by_calendar_value_not_shifted():
    assert site._iso_from_escher_date("2026-06-18T00:00:00") == "2026-06-18"
    assert site._iso_from_escher_date(None) == ""
    assert site._iso_from_escher_date("nonsense") == ""


def test_every_request_is_a_GET():
    """This app must never write to a payroll system. The only HTTP verb in
    the site layer is GET, even the report enqueue and poll."""
    src = (Path(__file__).resolve().parents[1] / "paylocity_site.py").read_text(encoding="utf-8")
    for verb in (".post(", ".put(", ".patch(", ".delete("):
        assert verb not in src, verb
    assert "request.get(" in src


def test_report_urls_must_stay_on_paylocitys_host():
    assert site.is_safe_url(site.REPORT_BASE + "/companyfiles/DocStream.aspx?r=X&att=true")
    assert not site.is_safe_url("https://evil.test/companyfiles/DocStream.aspx?r=X")
    assert site.REPORT_BASE.startswith("https://login.paylocity.com/")


def _collect(rows):
    """Drive collect_documents with a stubbed page whose request layer returns
    `rows` for the check-dates call and an empty assignment list otherwise."""
    class _Resp:
        ok = True
        def __init__(self, payload): self._p = payload
        def json(self): return self._p
    class _Req:
        def get(self, url, params=None):
            if "GetCheckDatesForPayAssignment" in url:
                return _Resp(rows)
            return _Resp({"payAssignments": []})
    class _Ctx:
        request = _Req()
    class _Page:
        context = _Ctx()
        url = "https://access.paylocity.com/Escher/Escher_WebUI/EmployeeInformation/PayHistory/Index/"
    return site.collect_documents(_Page())
