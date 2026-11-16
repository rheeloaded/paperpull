"""NetBenefits' Diagnose asks for the statements a run asks for.

Diagnose listed with the page alone, so it made quarterly statements for a
person whose run asks monthly ones, and every year back to the plan's start
whatever years the run was given. A support report then showed statements
made where the run's own requests failed. It now hands the listing the
config and the run's years, as Discover does.

The plan list's error went where the count of plans goes, so a report held
an error's name where a reader looks for how many plans were listed. It has
a key of its own, as the listing's error has.

Only the site's own calls are stood in. Every name, plan and date is made up.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  (binds this provider's AppSpec)
import netbenefits_site as site
import netbenefits_docs as docs
from paperpull_core.words import shape_tree, words_for


def _app(tmp_path, flags=(), **config):
    cfg = Path(tmp_path) / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(Path(tmp_path) / "out"),
        "profile_dir": str(Path(tmp_path) / "profile"),
        "delay_min_seconds": 0, "delay_max_seconds": 0, **config}), encoding="utf-8")
    return docs.App(docs.build_parser().parse_args(["--config", str(cfg), "--diagnose", *flags]))


def _diagnose(app, monkeypatch, made_statements=2, plans=None, order=None):
    """Diagnose run on a page that makes the newest `made_statements`
    statements it is asked for and the error page after them. Answers what
    the report holds and every period the listing asked for. `order`, a
    list, gets each statement asked for and each read of the plan list in
    turn, and any plan opened."""
    asked = []
    order = [] if order is None else order

    def make_statement(page, date_range, want_html=False):
        asked.append(date_range)
        order.append("statement")
        return {"isStatement": len(asked) <= made_statements, "plan": "Example Plan",
                "title": "Statement"}

    def plan_choices(page):
        order.append("plan list")
        if isinstance(plans, Exception):
            raise plans
        return plans

    monkeypatch.setattr(site, "make_statement", make_statement)
    monkeypatch.setattr(site, "read_plan_choices", plan_choices)
    monkeypatch.setattr(site, "open_plan", lambda page, plan: order.append("open plan"))
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)
    monkeypatch.setattr(site, "survey", lambda page, **k: {"pages": [], "responses": []})
    monkeypatch.setattr(docs.App, "page", lambda self, *a, **k: object())
    app.cmd_diagnose()
    report = app.paths.diagnostics / "diagnose-documents.json"
    return json.loads(report.read_text(encoding="utf-8")), asked


def test_a_monthly_run_gets_a_monthly_report(tmp_path, monkeypatch):
    app = _app(tmp_path, statement_period="monthly")
    info, asked = _diagnose(app, monkeypatch)
    monthly = [p["range"] for p in site.periods("monthly")]
    assert asked == monthly[:3], "the newest months, then the error page that ends the walk"
    assert info["collected"] == 2
    assert [s["title"] for s in info["samples"]] == ["Monthly Statement"] * 2


@pytest.mark.parametrize("written, kind", [("MONTHLY", "monthly"), ("weekly", "quarterly")])
def test_the_period_is_read_as_a_run_reads_it(tmp_path, monkeypatch, written, kind):
    info, asked = _diagnose(_app(tmp_path, statement_period=written), monkeypatch)
    assert asked == [p["range"] for p in site.periods(kind)][:3]


def test_a_report_with_no_period_set_asks_quarters_as_before(tmp_path, monkeypatch):
    app = _app(tmp_path)
    info, asked = _diagnose(app, monkeypatch)
    assert asked == [p["range"] for p in site.periods("quarterly")][:3]
    assert info["collected"] == 2


def test_a_report_for_one_year_asks_that_year_only(tmp_path, monkeypatch):
    year = site.periods("quarterly")[-1]["date"][:4]
    later = str(int(year) + 1)
    app = _app(tmp_path, flags=("--year", later))
    info, asked = _diagnose(app, monkeypatch, made_statements=99)
    wanted = [p["range"] for p in site.periods("quarterly") if p["date"][:4] == later]
    assert wanted and asked == wanted


def test_a_start_date_in_the_config_ends_the_report_where_the_run_ends(tmp_path, monkeypatch):
    periods = site.periods("quarterly")
    start = periods[len(periods) // 2]["date"][:4]
    app = _app(tmp_path, default_start_date="%s-01-01" % start)
    info, asked = _diagnose(app, monkeypatch, made_statements=10_000)
    assert asked == [p["range"] for p in periods if p["date"][:4] >= start]


def test_a_scope_that_holds_no_period_asks_for_none(tmp_path, monkeypatch):
    """A year before the picker's first lists nothing and is no error, and
    the report is a report like any other, not one that read nothing."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "delay_min_seconds": 0,
        "delay_max_seconds": 0}), encoding="utf-8")
    asked = []
    monkeypatch.setattr(site, "make_statement", lambda page, r, want_html=False: asked.append(r))
    monkeypatch.setattr(site, "read_plan_choices", lambda page: site.ONE_PLAN)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "detect_security_challenge", lambda page: None)
    monkeypatch.setattr(site, "survey", lambda page, **k: {"pages": [], "responses": []})
    monkeypatch.setattr(docs.App, "page", lambda self, *a, **k: object())
    monkeypatch.setattr(docs.App, "write_survey", lambda self: None)
    code = docs.main(["--config", str(cfg), "--diagnose", "--year", str(site.FIRST_YEAR - 1)])
    info = json.loads(next((tmp_path / "out").rglob("diagnose-documents.json"))
                      .read_text(encoding="utf-8"))
    assert asked == []
    assert info["collected"] == 0 and "collect_error" not in info and "error" not in info
    assert code in (0, None)


def test_several_plans_are_listed_as_one_is_and_none_opened(tmp_path, monkeypatch):
    """Diagnose lists the plan the tab shows and only then reads the plan
    list, which moves the tab, and it opens no plan."""
    order = []
    plans = [{"path": "/plan/a"}, {"path": "/plan/b"}]
    info, _ = _diagnose(_app(tmp_path, statement_period="monthly"), monkeypatch,
                        plans=plans, order=order)
    assert "open plan" not in order
    assert order.index("plan list") > max(i for i, o in enumerate(order) if o == "statement")
    assert info["plans"] == {"listed": 2, "left_for_review": 0}


@pytest.mark.parametrize("plans, counted", [
    (site.ONE_PLAN, {"listed": 1, "left_for_review": 0}),
    (None, None),
    ([{"path": "/plan/a"}, {"path": ""}, {"path": "/plan/c"}], {"listed": 3, "left_for_review": 1}),
    ([], {"listed": 0, "left_for_review": 0}),
])
def test_plans_holds_counts(tmp_path, monkeypatch, plans, counted):
    info, _ = _diagnose(_app(tmp_path), monkeypatch, plans=plans)
    assert info["plans"] == counted
    assert "plans_error" not in info


@pytest.mark.parametrize("error", [
    site.PlanListUnclear("the list could not be told apart"),
    site.PlanListUnavailable("the list did not show"),
    RuntimeError("something else went wrong"),
])
def test_a_plan_list_that_fails_keeps_its_error_apart_from_the_counts(tmp_path, monkeypatch,
                                                                      error):
    info, _ = _diagnose(_app(tmp_path), monkeypatch, plans=error)
    assert info["plans"] is None, "no count was read"
    # Written as every value of the file is, a word off the list as its shape.
    said = shape_tree("%s: %s" % (type(error).__name__, error), words_for("NetBenefits", site))
    assert info["plans_error"] == said, info
    # The listing still ran and was counted, and its own error key is not used.
    assert info["collected"] == 2 and "collect_error" not in info
