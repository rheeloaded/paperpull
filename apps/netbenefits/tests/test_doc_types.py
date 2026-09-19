"""NetBenefits, the parts that run without a browser. The periods the app
asks the site for, the guard, the host allowlist, the plan label, and what
a statement answer looks like."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import netbenefits_site as site
from paperpull_core import doc_types


def test_the_spec():
    assert storage.SPEC.provider == "NetBenefits"
    assert storage.SPEC.config_defaults["statement_period"] == "quarterly"
    assert storage.SPEC.base_url == "https://workplaceservices.fidelity.com/"
    assert storage.SPEC.token == "netbenefits"


def test_quarters_are_completed_ones_newest_first_with_the_site_date_range():
    ps = site.periods("quarterly", today=date(2026, 9, 18), first_year=2025)
    assert [p["label"] for p in ps] == ["Q2 2026", "Q1 2026", "Q4 2025", "Q3 2025", "Q2 2025", "Q1 2025"]
    assert ps[0] == {"title": "Quarterly Statement", "label": "Q2 2026", "date": "2026-06-30",
                     "start": "2026-04-01", "range": "04/01/2026-06/30/2026"}
    assert ps[2]["range"] == "10/01/2025-12/31/2025"


def test_a_quarter_that_ends_today_is_not_complete():
    ps = site.periods("quarterly", today=date(2026, 6, 30), first_year=2026)
    assert [p["label"] for p in ps] == ["Q1 2026"]
    ps = site.periods("quarterly", today=date(2026, 7, 1), first_year=2026)
    assert [p["label"] for p in ps] == ["Q2 2026", "Q1 2026"]


def test_months_too():
    ps = site.periods("monthly", today=date(2026, 3, 5), first_year=2025)
    assert [p["label"] for p in ps][:4] == ["February 2026", "January 2026", "December 2025", "November 2025"]
    assert ps[0]["range"] == "02/01/2026-02/28/2026" and ps[0]["date"] == "2026-02-28"
    assert ps[-1]["label"] == "January 2025"


def test_the_plan_label_drops_the_plan_number_and_reads_like_a_name():
    assert site.plan_label("SOME CORP. RETIREMENT SAVINGS PLAN (12345)") == "Some Corp. Retirement Savings Plan"
    assert site.plan_label("Acme 401(k) Plan") == "Acme 401(k) Plan"
    assert site.plan_label("") == ""


def _answers(by_range):
    def fake(page, date_range, want_html=False):
        r = by_range.get(date_range)
        if r is None:
            return {"status": 200, "title": "Fidelity Netbenefits - Online Statement error page", "isStatement": False, "html": ""}
        return {"status": 200, "title": "Fidelity NetBenefits - Statement Details", "isStatement": True,
                "plan": "SOME CORP. RETIREMENT SAVINGS PLAN (12345)", "period": r,
                "html": "<html><head></head><body>%s</body></html>" % r}
    return fake


@pytest.fixture
def periods_from_2024(monkeypatch):
    real = site.periods
    monkeypatch.setattr(site, "periods", lambda kind, today=None, first_year=site.FIRST_YEAR: real(kind, date(2026, 9, 18), 2024))


def test_discovery_walks_back_and_stops_at_the_first_missing_period_after_a_real_one(monkeypatch, periods_from_2024):
    have = {"04/01/2026-06/30/2026": "04/01/2026 to 06/30/2026", "01/01/2026-03/31/2026": "01/01/2026 to 03/31/2026",
            "10/01/2025-12/31/2025": "10/01/2025 to 12/31/2025", "07/01/2025-09/30/2025": "07/01/2025 to 09/30/2025"}
    calls = []
    fake = _answers(have)
    monkeypatch.setattr(site, "make_statement", lambda page, r, want_html=False: (calls.append(r), fake(page, r))[1])
    rows = site.collect_documents(None, config={"statement_period": "quarterly"})
    assert [r["date"] for r in rows] == ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    assert rows[0]["account"] == "Some Corp. Retirement Savings Plan" and rows[0]["item_id"] == "04/01/2026-06/30/2026"
    assert rows[0]["category"] == "Statement" and rows[0]["client_id"] == "quarterly"
    assert calls[-1] == "04/01/2025-06/30/2025" and len(calls) == 5    # one error page, then stop


def test_a_scoped_run_makes_only_its_years(monkeypatch, periods_from_2024):
    have = {"10/01/2025-12/31/2025": "x", "07/01/2025-09/30/2025": "x", "04/01/2025-06/30/2025": "x", "01/01/2025-03/31/2025": "x"}
    calls = []
    fake = _answers(have)
    monkeypatch.setattr(site, "make_statement", lambda page, r, want_html=False: (calls.append(r), fake(page, r))[1])
    rows = site.collect_documents(None, keep=lambda y: y == "2025", config={})
    assert len(rows) == 4 and all(r["date"].startswith("2025") for r in rows)
    assert all(r.endswith("2025") for r in calls)


def test_download_makes_the_statement_again_and_renders_it(monkeypatch, tmp_path):
    fake = _answers({"04/01/2026-06/30/2026": "04/01/2026 to 06/30/2026"})
    monkeypatch.setattr(site, "make_statement", fake)
    rendered = {}
    from paperpull_core import receipt_pdf
    def fake_render(page, html, out_path):
        rendered["html"] = html
        Path(out_path).write_bytes(b"%PDF-1.4" + b"x" * 2000)
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", fake_render)
    out = tmp_path / "s.pdf"
    assert site.download_document(None, "Quarterly Statement", "2026-06-30", out,
                                  item_hint="04/01/2026-06/30/2026", client_hint="quarterly")
    assert "04/01/2026 to 06/30/2026" in rendered["html"] and "@media print" in rendered["html"]
    assert not site.download_document(None, "Quarterly Statement", "2016-03-31", tmp_path / "n.pdf",
                                      item_hint="01/01/2016-03/31/2016")


def test_changing_the_plan_is_never_safe():
    for name in ["Manage contributions", "Manage investments", "Take a loan or withdrawal", "Exchange",
                 "Rebalance", "Change beneficiaries", "Enroll", "Log out", "Rollover"]:
        assert not site.is_safe_control(name), name


def test_reading_a_statement_is_safe():
    for name in ["View your statements", "Statements", "Get statement", "Download or Print This Statement"]:
        assert site.is_safe_control(name), name


def test_only_fidelity_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://workplaceservices.fidelity.com/mybenefits/savings2/sod/soddetail")
    assert site.is_safe_url("https://nb.fidelity.com/public/nb/default/home")
    assert not site.is_safe_url("https://fidelity.com.example/") and not site.is_safe_url("http://nb.fidelity.com/")


def test_the_statement_call_refuses_to_run_from_another_host():
    assert "here.hostname !== 'workplaceservices.fidelity.com'" in site._MAKE_JS

    class L:
        def count(self): return 0

    class P:
        url = "https://nb.fidelity.com/public/nb/default/home"
        def locator(self, *_): return L()
    with pytest.raises(RuntimeError):
        site.make_statement(P(), "01/01/2026-03/31/2026")


def test_titles_classify():
    rules = doc_types.load_rules()
    assert doc_types.classify_document("Quarterly Statement", rules)[:2] == ("Statement", "Quarterly Statement")
    assert doc_types.classify_document("Monthly Statement", rules)[:2] == ("Statement", "Monthly Statement")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("plan 123456 view") == "plan ###### view"


def test_the_session_is_kept_awake_by_reloading_the_statements_page_now_and_then(monkeypatch):
    class P:
        url = "https://workplaceservices.fidelity.com/mybenefits/savings2/navigation/dc/OnlineStatement"
        gotos = []
        def goto(self, url, **kw): self.gotos.append(url)
        def wait_for_timeout(self, ms): pass
    p = P()
    site._last_navigation["at"] = 0.0
    site._keep_awake(p)
    assert p.gotos == [site.URLS["documents"]]
    site._keep_awake(p)                      # just reloaded, nothing to do
    assert len(p.gotos) == 1
    site._last_navigation["at"] -= site.KEEP_AWAKE_SECONDS + 1
    site._keep_awake(p)
    assert len(p.gotos) == 2
