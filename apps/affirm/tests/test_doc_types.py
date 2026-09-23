"""Affirm, the parts that can be tested before the site is mapped. The
guard, the host allowlist, the date shapes, the folders, and the survey's
redaction."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import affirm_site as site
from paperpull_core import doc_types


def test_the_spec():
    assert storage.SPEC.provider == "Affirm"
    assert storage.SPEC.routes[storage.AGREEMENT] == "loan_agreements"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement", "Tax Document", "Loan Agreement"]


def test_titles_classify():
    rules = doc_types.load_rules()
    assert doc_types.classify_document("Statement", rules)[:2] == ("Statement", "Monthly Statement")
    assert doc_types.classify_document("August 2026 Statement", rules)[:2] == ("Statement", "Monthly Statement")
    assert doc_types.classify_document("Affirm Card Statement", rules)[:2] == ("Statement", "Card Statement")
    assert doc_types.classify_document("Loan Agreement", rules)[:2] == ("Statement", "Loan Agreement")
    assert doc_types.classify_document("Form 1099", rules)[:2] == ("Tax Document", "1099 Tax Form")


def test_dates():
    assert site.parse_date("02/09/2026") == "2026-02-09"
    assert site.parse_date("Feb 9, 2026") == "2026-02-09"
    assert site.parse_date("2025-11-29T23:17:45Z") == "2025-11-29"
    assert site.parse_date("soon") == ""


def test_paying_borrowing_and_changing_are_never_safe():
    for name in ["Pay now", "Make a payment", "Set up autopay", "Add a card", "Bank account", "Apply",
                 "Shop", "Buy now", "Prequalify", "Virtual card", "Refinance", "Log out", "Change phone",
                 "Update address", "Close account"]:
        assert not site.is_safe_control(name), name


def test_reading_a_document_is_safe():
    for name in ["Statements", "Download statement", "View", "Loan agreement", "Truth in Lending disclosure",
                 "Activity", "Download PDF"]:
        assert site.is_safe_control(name), name


def test_only_affirm_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.affirm.com/u/")
    assert site.is_safe_url("https://api.affirm.com/x")
    assert not site.is_safe_url("http://www.affirm.com/u/")
    assert not site.is_safe_url("https://affirm.com.example/")
    assert not site.is_safe_url("https://user:pw@www.affirm.com/")


DETAILS = {"modules": {"tabs": {"data": {"tabs": {"details": {"data": {"modules": {"disclosures": {"data": {"items": [
    {"label": {"value": "Cancellations with Affirm"}, "action": {"name": "CANCELLATION_EXCEPTION", "data": {}}},
    {"label": {"value": "Loan verification document"}, "action": {"name": "DOWNLOAD_LOAN_VERIFICATION",
     "data": {"path": {"path": "/api/v2/users/X/loan_verification/L1", "method": "GET"}}}},
    {"label": {"value": "Loan terms"}, "action": {"name": "OPEN_URL",
     "data": {"url": "https://www.affirm.com/api/v2/disclosures/ABC123/view", "external": False}}},
]}}}}}}}}}}


def test_the_loan_terms_url_is_taken_from_the_details_and_the_letter_is_not(monkeypatch):
    monkeypatch.setattr(site, "_get", lambda page, path: DETAILS)
    assert site.terms_url(None, "L1") == "https://www.affirm.com/api/v2/disclosures/ABC123/view"
    bad = {"modules": {"tabs": {"data": {"tabs": {"details": {"data": {"modules": {"disclosures": {"data": {"items": [
        {"label": {"value": "Loan terms"}, "action": {"name": "OPEN_URL", "data": {"url": "https://evil.example/x"}}}]}}}}}}}}}}
    monkeypatch.setattr(site, "_get", lambda page, path: bad)
    assert site.terms_url(None, "L1") == ""                      # an off-host URL is refused


def test_collect_makes_one_agreement_per_loan_dated_when_the_loan_was_made(monkeypatch):
    calls = []
    def fake_get(page, path):
        calls.append(path)
        if path.startswith("/api/v4/loans/"):
            return {"count": 2, "next": None, "data": [{"id": "L1", "merchant_name": "Pottery Barn", "status": "due"},
                                                      {"id": "L2", "merchant_name": "SAMSUNG", "status": "settled"}]}
        if path.startswith("/api/v3/loans/"):
            return {"created": "2025-11-29T23:17:45Z" if path.endswith("L1") else "2022-10-01T12:00:00Z"}
        return DETAILS
    monkeypatch.setattr(site, "_get", fake_get)
    monkeypatch.setattr(site, "on_documents_page", lambda page: True)
    rows = site.collect_documents(None)
    assert [(r["title"], r["date"], r["account"], r["item_id"], r["category"]) for r in rows] == [
        ("Loan Agreement", "2025-11-29", "Pottery Barn", "L1", "Loan Agreement"),
        ("Loan Agreement", "2022-10-01", "Samsung", "L2", "Loan Agreement")]
    rows = site.collect_documents(None, keep=lambda y: y == "2025")
    assert [r["item_id"] for r in rows] == ["L1"]


def test_download_renders_the_agreement_page_and_refuses_anything_else(monkeypatch, tmp_path):
    monkeypatch.setattr(site, "terms_url", lambda page, lid: "https://www.affirm.com/api/v2/disclosures/ABC123/view")
    class P:
        def evaluate(self, js, arg):
            return {"status": 200, "ct": "text/html; charset=utf-8", "text": "<html><head></head><body>" + "Truth in Lending " * 200 + "</body></html>", "url": arg}
    rendered = {}
    from paperpull_core import receipt_pdf
    def fake_render(page, html, out_path):
        rendered["html"] = html
        Path(out_path).write_bytes(b"%PDF-1.4" + b"x" * 2000)
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", fake_render)
    out = tmp_path / "a.pdf"
    assert site.download_document(P(), "Loan Agreement", "2025-11-29", out, item_hint="L1")
    assert "Truth in Lending" in rendered["html"]
    class Q:
        def evaluate(self, js, arg): return {"status": 200, "ct": "application/json", "text": "{}", "url": arg}
    assert not site.download_document(Q(), "Loan Agreement", "2025-11-29", tmp_path / "b.pdf", item_hint="L1")


def test_the_in_page_calls_refuse_to_run_off_host():
    assert "Refusing to call the API from an off-host page" in site._GET_JS
    assert "Refusing an off-host request" in site._TEXT_JS
    class P:
        def evaluate(self, js, arg): return {"status": 401, "json": None}
    with pytest.raises(site.SessionExpired):
        site._get(P(), "/api/v4/loans/")


def test_the_survey_follows_only_exact_document_words():
    assert site.SURVEY_LINK_RE.match("Money") and site.SURVEY_LINK_RE.match("Statements") and site.SURVEY_LINK_RE.match("Activity")
    assert not site.SURVEY_LINK_RE.match("Pay") and not site.SURVEY_LINK_RE.match("Shop now")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("loan 123456789 view") == "loan ######### view"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"loans": [{"id": "123456789", "balance": 12.5}]})
    assert shape == {"loans": ["1 item(s)", {"id": "string", "balance": "number"}]}
