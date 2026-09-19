"""Fidelity, the parts that can be tested before the site is mapped. The
guard, the host allowlist, the date shapes, the folders, and the survey's
redaction. The document API itself is filled in after a signed-in survey."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import fidelity_site as site
from paperpull_core import doc_types


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Fidelity"
    assert [f.name for f in storage.SPEC.folders if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Statements", "Tax Documents", "Trade Confirmations", "Letters", "Other Documents"]
    assert storage.SPEC.routes[storage.CONFIRM] == "trade_confirmations"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement", "Tax Document", "Trade Confirmation", "Letter"]


@pytest.mark.parametrize("title,category,summary", [
    ("Statement - Individual - 07/31/2026", "Statement", "Statement"),
    ("Monthly Statement", "Statement", "Monthly Statement"),
    ("2025 Form 1099-R", "Tax Document", "1099-R Tax Form"),
    ("2025 Tax Reporting Statement", "Tax Document", "1099 Tax Form"),
    ("Form 5498", "Tax Document", "5498 Tax Form"),
    ("Trade Confirmation 06/12/2026", "Statement", "Trade Confirmation"),
])
def test_known_fidelity_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


def test_dates_in_the_three_shapes_the_site_might_use():
    assert site.parse_date("02/09/2026") == "2026-02-09"
    assert site.parse_date("Feb 9, 2026") == "2026-02-09"
    assert site.parse_date("2026-02-09T00:00:00") == "2026-02-09"
    assert site.parse_date("yesterday") == ""


def test_trading_and_moving_money_are_never_safe():
    for name in ["Trade", "Buy", "Sell", "Transfer", "Wire money", "Withdraw", "Take a distribution",
                 "Deposit checks", "Bill Pay", "Change beneficiaries", "Link bank account",
                 "Log out", "Change password", "Go paperless", "Open an account", "Roll over"]:
        assert not site.is_safe_control(name), name


def test_reading_a_document_is_safe():
    for name in ["Download", "View statement", "Statements", "Tax forms", "Trade confirmations",
                 "Download PDF", "2025 Form 1099-R", "View"]:
        assert site.is_safe_control(name), name


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit statement")           # "edit" inside Credit
    assert not site.is_safe_control("Exchange")                # a trade word on its own


def test_only_fidelity_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://digital.fidelity.com/ftgw/digital/portfolio/documents")
    assert site.is_safe_url("https://www.fidelity.com/")
    assert not site.is_safe_url("http://digital.fidelity.com/")
    assert not site.is_safe_url("https://fidelity.com.example/")
    assert not site.is_safe_url("https://notfidelity.com/")
    assert not site.is_safe_url("https://user:pw@digital.fidelity.com/")


def test_the_documents_page_is_the_hub_not_any_signed_in_page():
    class SimpleLocator:
        def count(self): return 0
    class P:
        url = "https://digitalservices.fidelity.com/navigate/ent-documentcenter/statements?poe=fidcom"
        def locator(self, *_): return SimpleLocator()
    assert site.on_documents_page(P())
    P.url = "https://digitalservices.fidelity.com/navigate/ent-documentcenter/trade-confirmations?poe=fidcom"
    assert site.on_documents_page(P())
    P.url = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"
    assert not site.on_documents_page(P())


def test_epoch_dates_are_midnight_eastern_in_both_halves_of_the_year():
    assert site.epoch_date(1788148800) == "2026-08-31"      # EDT, 04:00 UTC
    assert site.epoch_date(1735707600) == "2025-01-01"      # EST, 05:00 UTC
    assert site.epoch_date(1788148800000) == "2026-08-31"   # milliseconds tolerated
    assert site.epoch_date(None) == "" and site.epoch_date("x") == ""


ACCOUNTS = {"123456789": {"type": "Brokerage", "name": "BrokerageLink"},
            "12345": {"type": "WPS", "name": "SOME EMPLOYER RETIREMENT SAVINGS PLAN"}}


def test_a_statement_row_carries_kind_account_date_and_what_the_download_needs():
    d = {"id": "YzoyMDI2LTA4LTMx", "type": "PI Monthly/Quarterly Statement", "acctNum": "123456789",
         "periodStartDate": 1785556800, "periodEndDate": 1788148800, "generatedDate": 1788148800,
         "formatTypes": {"formatType": {"isPDF": True, "isHTML": True, "isCSV": True}}}
    r = site._row("Statement", "Statement", d, ACCOUNTS, "STMT")
    assert r["title"] == "Monthly Statement" and r["date"] == "2026-08-31" and r["period_start"] == "2026-08-01"
    assert r["account"] == "BrokerageLink 6789"          # never the whole number
    assert r["item_id"] == "YzoyMDI2LTA4LTMx" and r["client_id"] == "STMT|Brokerage"
    assert r["category"] == "Statement"


def test_a_trade_confirmation_row_files_as_a_confirmation():
    d = {"id": "abc", "type": "Trade Confirm", "acctNum": "123456789", "periodEndDate": 1789444800,
         "generatedDate": 1789444800, "formatTypes": {"formatType": {"isPDF": True}}}
    r = site._row("Trade Confirmation", "Trade Confirmation", d, ACCOUNTS, "TC")
    assert r["category"] == "Trade Confirmation" and r["date"] == "2026-09-15" and r["client_id"] == "TC|Brokerage"


def test_collect_asks_one_year_at_a_time_only_for_wanted_kinds_and_only_years_in_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(site, "list_accounts", lambda page: ACCOUNTS)
    def fake_list(page, doc_type, year):
        calls.append((doc_type, year))
        return [{"id": "%s-%d" % (doc_type, year), "type": "x", "acctNum": "123456789",
                 "periodEndDate": 1788148800, "formatTypes": {"formatType": {"isPDF": True}}}]
    monkeypatch.setattr(site, "list_kind", fake_list)
    monkeypatch.setattr(site, "list_tax_year", lambda page, y: (calls.append(("TAX", y)), [])[1])
    rows = site.collect_documents(None, keep=lambda y: y in ("2026", "2025"),
                                  config={"document_types": ["Statement", "Tax Document"]})
    assert calls == [("STMT", 2026), ("STMT", 2025), ("TAX", 2025)]     # no TC, no current tax year
    assert [r["item_id"] for r in rows] == ["STMT-2026", "STMT-2025"]


def test_the_pdf_comes_back_from_base64_and_a_deflated_one_is_inflated(monkeypatch):
    import base64, zlib
    pdf = b"%PDF-1.4 fake"
    monkeypatch.setattr(site, "_post", lambda page, url, body: {"document": {"docDetail": {
        "content": base64.b64encode(pdf).decode(), "deflated": "Y", "contentType": "application/pdf"}}})
    assert site.fetch_pdf(None, "id", "STMT", "Brokerage") == pdf
    monkeypatch.setattr(site, "_post", lambda page, url, body: {"document": {"docDetail": {
        "content": base64.b64encode(zlib.compress(pdf)).decode(), "deflated": "Y"}}})
    assert site.fetch_pdf(None, "id", "STMT", "Brokerage") == pdf


def test_download_resolves_the_id_fresh_and_refuses_a_non_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(site, "resolve_item", lambda *a, **k: {"item_id": "fresh", "client_id": "TC|Brokerage"})
    seen = {}
    def fake_fetch(page, item_id, doc_type, acct_type):
        seen.update(item_id=item_id, doc_type=doc_type, acct_type=acct_type)
        return b"%PDF-1.4 ok"
    monkeypatch.setattr(site, "fetch_pdf", fake_fetch)
    out = tmp_path / "x.pdf"
    assert site.download_document(None, "Trade Confirmation", "2026-09-15", out, item_hint="stale",
                                  client_hint="STMT|Brokerage", account="BrokerageLink 6789")
    assert seen == {"item_id": "fresh", "doc_type": "TC", "acct_type": "Brokerage"} and out.read_bytes().startswith(b"%PDF")
    monkeypatch.setattr(site, "fetch_pdf", lambda *a: b"<html>sign in</html>")
    assert not site.download_document(None, "Statement", "2026-08-31", tmp_path / "y.pdf", account="BrokerageLink 6789")
    assert not (tmp_path / "y.pdf").exists()


def test_the_in_page_post_only_ever_goes_to_a_fidelity_host():
    assert "host.endsWith('.fidelity.com')" in site._POST_JS
    with pytest.raises(ValueError):
        site._post(None, "https://evil.example/x", {})


def test_a_sign_in_answer_stops_the_run(monkeypatch):
    class P:
        def evaluate(self, js, arg): return {"status": 401, "json": None}
    with pytest.raises(site.SessionExpired):
        site._post(P(), site.API["list"], {})


def test_the_survey_follows_only_exact_document_words():
    assert site.SURVEY_LINK_RE.match("Statements")
    assert site.SURVEY_LINK_RE.match("Documents")
    assert site.SURVEY_LINK_RE.match("Tax Forms")
    assert not site.SURVEY_LINK_RE.match("Trade")
    assert not site.SURVEY_LINK_RE.match("Transfer money")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("acct 123456789 view") == "acct ######### view"
    assert site.redact("Z12-345678") == "Z12-######"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"accounts": [{"number": "123456789", "balance": 12.5}]})
    assert shape == {"accounts": ["list of 1", {"number": "str", "balance": "float"}]}
