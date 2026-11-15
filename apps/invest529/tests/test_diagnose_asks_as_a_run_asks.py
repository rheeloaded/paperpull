"""Invest529's Diagnose asks for the kinds and years a run asks for.

Diagnose listed with the page alone, so it read statements and 1099-Q forms
whatever document_types held and every year whatever the run was given. It
now hands the listing the config and the run's years, as Discover does.
Only the two list calls are stood in, and every name and number is made up.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  (binds this provider's AppSpec)
import invest529_site as site
import invest529_docs as docs
from paperpull_core.words import shape_tree, words_for

OWNERS = [{"ownerPidm": "1001", "beneficiaries": [{
    "beneficiaryPidm": "2002", "beneficiaryName": "Sam Example",
    "accounts": [{"officialStatements": [
        {"startDate": "2030-01-01", "endDate": "2030-03-31", "seqNo": "11"},
        {"startDate": "2031-01-01", "endDate": "2031-03-31", "seqNo": "12"},
    ]}]}]}]
FORMS = [{"taxYear": "2030", "accountNumber": "999001", "correctionIndicator": ""},
         {"taxYear": "2031", "accountNumber": "999001", "correctionIndicator": ""}]


def _diagnose(tmp_path, monkeypatch, flags=(), statements_raise=None, signed_out=False,
              **config):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "delay_min_seconds": 0,
        "delay_max_seconds": 0, **config}), encoding="utf-8")
    asked = []

    def statements(page):
        asked.append("statements")
        if statements_raise:
            raise statements_raise
        return OWNERS

    def forms(page):
        asked.append("1099")
        return FORMS

    monkeypatch.setattr(site, "list_statements", statements)
    monkeypatch.setattr(site, "list_1099", forms)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: signed_out)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)
    monkeypatch.setattr(site, "survey", lambda page, **k: {"pages": [], "responses": []})
    monkeypatch.setattr(docs.App, "page", lambda self, *a, **k: object())
    monkeypatch.setattr(docs.App, "write_survey", lambda self: None)
    code = docs.main(["--config", str(cfg), "--diagnose", *flags])
    info = json.loads(next((tmp_path / "out").rglob("diagnose-documents.json"))
                      .read_text(encoding="utf-8"))
    return code, info, asked


@pytest.mark.parametrize("kinds", [None, [], ["Statement", "Tax Document"]])
def test_a_report_with_both_kinds_asks_both_as_before(tmp_path, monkeypatch, kinds):
    extra = {} if kinds is None else {"document_types": kinds}
    code, info, asked = _diagnose(tmp_path, monkeypatch, **extra)
    assert asked == ["statements", "1099"]
    assert info["collected"] == 4


def test_a_run_of_tax_forms_only_gets_a_report_of_tax_forms_only(tmp_path, monkeypatch):
    code, info, asked = _diagnose(tmp_path, monkeypatch, document_types=["Tax Document"])
    assert asked == ["1099"]
    assert info["collected"] == 2


def test_a_run_of_statements_only_gets_a_report_of_statements_only(tmp_path, monkeypatch):
    code, info, asked = _diagnose(tmp_path, monkeypatch, document_types=["Statement"])
    assert asked == ["statements"]
    assert info["collected"] == 2


def test_a_report_for_one_year_counts_that_year_only(tmp_path, monkeypatch):
    code, info, asked = _diagnose(tmp_path, monkeypatch, flags=("--year", "2031"))
    assert asked == ["statements", "1099"]
    assert info["collected"] == 2


def test_a_start_date_in_the_config_counts_from_that_year(tmp_path, monkeypatch):
    code, info, asked = _diagnose(tmp_path, monkeypatch, default_start_date="2031-01-01")
    assert info["collected"] == 2


def test_a_listing_that_fails_keeps_its_error_and_a_count(tmp_path, monkeypatch):
    code, info, asked = _diagnose(tmp_path, monkeypatch,
                                  statements_raise=site.SessionExpired("made up"))
    # Written as every value of the file is, a word off the list as its shape.
    said = shape_tree("SessionExpired: made up", words_for("Invest529", site))
    assert info["collect_error"] == said, info
    assert info["collected"] == 0 and isinstance(info["collected"], int)
