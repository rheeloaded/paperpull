"""A NetBenefits login with one plan works exactly as v0.51.0 had it.

The page stands in for a live one with one plan, which shows no Choose a
Plan page and no Select Account page, so every address shows the plan's
own Statements page. Only the page is stood in. The app's own discovery,
statement request, keep-awake reload and download run as they do live,
and their keys, file names and records are held to what v0.51.0 wrote for
the very same page, written out below. Every name and number is
invented."""
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  (binds this provider's AppSpec)
import netbenefits_site as site
import netbenefits_docs as docs
from paperpull_core import receipt_pdf
from paperpull_core.models import State
from paperpull_core.testkit import receipt_app, text_pdf

WPS = "https://workplaceservices.fidelity.com"
BARE = WPS + "/mybenefits/savings2/navigation/dc/OnlineStatement"
HEADER = "SOME CORP. 401(K)<BR>PLAN"
HEADING = "SOME CORP. 401(K) PLAN (55555)"
Q2, Q1, Q4 = "04/01/2026-06/30/2026", "01/01/2026-03/31/2026", "10/01/2025-12/31/2025"


class Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def count(self):
        if "password" in self.sel or "client-name" in self.sel:
            return 0
        return 1

    def inner_text(self, timeout=None):
        return "Home %s Statements Time period Get statement" % HEADING

    def all_inner_texts(self):
        return [HEADING, "Statements"]


class OnePlanPage:
    """A signed-in tab of a login with one plan. A statement request answers
    for the periods in `have`, with the error page for any other, and one
    in `refused` is refused by the browser, as a network blip refuses it,
    while the session stays signed in. Scripts are told apart by what they
    do, so the same page serves v0.51.0's code and today's."""

    def __init__(self, have, refused=()):
        self.url = BARE
        self.have, self.refused = set(have), set(refused)
        self.gotos, self.made, self.other = [], [], []

    def title(self):
        return "Fidelity NetBenefits"

    def locator(self, sel):
        return Loc(self, sel)

    def wait_for_timeout(self, ms):
        pass

    def is_closed(self):
        return False

    def goto(self, url, **kw):
        # No Choose a Plan page and no Select Account page. Every address
        # of the site shows the one plan's Statements page.
        assert url.startswith(WPS + "/mybenefits/"), url
        self.gotos.append(url)
        self.url = url

    def evaluate(self, js, arg=None):
        if "sodReqIndicator" in js:
            dr = arg["dateRange"]
            self.made.append((dr, arg.get("want")))
            if dr in self.refused:
                return {"status": 0, "stage": "statement", "refused": True, "signedOut": True}
            if dr not in self.have:
                return {"status": 200, "title": "Fidelity NetBenefits - Online Statement error page",
                        "isStatement": False, "period": "", "plan": "", "html": ""}
            html = "<html><head></head><body>%s|Statement Period: %s</body></html>" % (HEADER, dr)
            return {"status": 200, "title": "Fidelity NetBenefits - Statement Details",
                    "isStatement": True, "period": dr,
                    "plan": "SOME CORP. 401(K) PLAN",
                    "html": html if arg.get("want") == "html" else ""}
        if "choose a plan" in js or "accountSelect" in js:
            return None                     # neither list page is shown
        if "txnTokenValue" in js:
            return True                     # the session's own token call answers
        self.other.append(js[:60])
        raise AssertionError("a script a login with one plan never runs")


def render(pg, html, out):
    body = re.sub(r"<[^>]+>", " ", html.split("<body>", 1)[-1])
    Path(out).write_bytes(text_pdf([line.strip() for line in body.split("|")]))


@pytest.fixture(autouse=True)
def fixed(monkeypatch):
    if hasattr(site, "_plan_in_use"):
        site._plan_in_use["plan"] = None
    site._last_navigation["at"] = 0.0
    real = site.periods
    monkeypatch.setattr(site, "periods",
                        lambda kind, today=None, first_year=site.FIRST_YEAR: real(kind, date(2026, 9, 18), 2025))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render)


def run(tmp_path, page):
    """Discover, then Run All, in one process, as the panel runs them."""
    app = receipt_app(docs, tmp_path, owner="")
    app.page = lambda: page
    app._on_its_site = lambda: page
    app.cmd_discover(quiet=True)
    app.process(app._select())
    app.progress.save()
    app.discovery.save()
    return app


def saved(tmp_path):
    folder = tmp_path / "out" / "Statements"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# What v0.51.0 (c3c0f535) wrote for this very page, its keys, its file names
# and each record's fields, the times aside.
V051_KEYS = [
    "Statement:2025-12-31:Quarterly Statement",
    "Statement:2026-03-31:Quarterly Statement",
    "Statement:2026-06-30:Quarterly Statement",
]
V051_FILES = [
    "2025-12-31 NetBenefits Quarterly Statement - Some Corp. 401(K) Plan.pdf",
    "2026-03-31 NetBenefits Quarterly Statement - Some Corp. 401(K) Plan.pdf",
    "2026-06-30 NetBenefits Quarterly Statement - Some Corp. 401(K) Plan.pdf",
]
V051_FIELDS = ["account", "category", "client_id", "confidence", "date", "date_text",
               "discovered_at", "document_id", "downloaded_ok", "href", "item_id", "notes",
               "occurrence", "pdf_filename", "pdf_pages", "pdf_path", "pdf_size", "period",
               "row_index", "state", "summary", "title", "updated_at"]
TIMES = ("discovered_at", "updated_at")


def _v051_record(day, period):
    return {"title": "Quarterly Statement", "account": "Some Corp. 401(K) Plan",
            "category": "Statement", "summary": "Quarterly Statement - Some Corp. 401(K) Plan",
            "date": day, "period": "", "date_text": day, "document_id": "", "item_id": period,
            "client_id": "quarterly", "occurrence": 0, "downloaded_ok": True,
            "href": "https://workplaceservices.fidelity.com/mybenefits/savings2/sod/soddetail",
            "row_index": -1, "confidence": "High", "state": "Completed",
            "pdf_filename": "%s NetBenefits Quarterly Statement - Some Corp. 401(K) Plan.pdf" % day,
            "pdf_pages": 1, "notes": ""}


V051_RECORD = {"Statement:2025-12-31:Quarterly Statement": _v051_record("2025-12-31", Q4),
               "Statement:2026-03-31:Quarterly Statement": _v051_record("2026-03-31", Q1),
               "Statement:2026-06-30:Quarterly Statement": _v051_record("2026-06-30", Q2)}


def test_a_login_with_one_plan_keeps_v051s_keys_file_names_and_records(tmp_path):
    page = OnePlanPage(have={Q2, Q1, Q4})
    app = run(tmp_path, page)
    assert sorted(app.discovery.data) == V051_KEYS
    assert sorted(app.progress.data) == V051_KEYS
    assert saved(tmp_path) == V051_FILES
    for key, rec in app.progress.data.items():
        assert sorted(rec) == V051_FIELDS, key
        got = {k: v for k, v in rec.items() if k not in TIMES and k not in ("pdf_path", "pdf_size")}
        assert got == dict(V051_RECORD[key]), key
    # Nothing of several plans. No plan was asked for, no list was kept.
    assert page.other == []
    assert not (tmp_path / "out" / "plans.json").exists()
    assert app.stats["failed"] == 0 and app.stats["manual_review"] == 0
    # A second run makes nothing again.
    page.made.clear()
    again = run(tmp_path, page)
    assert [m for m in page.made if m[1] == "html"] == []
    assert saved(tmp_path) == V051_FILES
    assert again.stats["skipped_completed"] == 3


def test_a_history_v051_wrote_is_not_made_again(tmp_path):
    """The records v0.51.0 wrote, read by today's app, which makes no
    statement again and keeps every key."""
    out = tmp_path / "out"
    out.mkdir(parents=True)
    history = {}
    for key, rec in V051_RECORD.items():
        history[key] = dict(rec, pdf_path=str(out / "Statements" / rec["pdf_filename"]),
                            discovered_at="2026-07-02T10:00:00", updated_at="2026-07-02T10:00:00")
    (out / "progress.json").write_text(json.dumps(history), encoding="utf-8")
    (out / "discovery.json").write_text(json.dumps(history), encoding="utf-8")
    page = OnePlanPage(have={Q2, Q1, Q4})
    app = run(tmp_path, page)
    assert [m for m in page.made if m[1] == "html"] == []
    assert sorted(app.progress.data) == V051_KEYS == sorted(app.discovery.data)
    assert saved(tmp_path) == []
    assert app.stats["skipped_completed"] == 3


def test_a_refused_request_on_a_login_with_one_plan_fails_that_document_alone(tmp_path):
    """v0.51.0 failed the one document a refused request was for and went
    on. A refusal was then taken for a sign-out, which stopped the run, though
    the session's own token call still answered."""
    page = OnePlanPage(have={Q2, Q1, Q4})
    app = receipt_app(docs, tmp_path, owner="")
    app.page = lambda: page
    app._on_its_site = lambda: page
    app.cmd_discover(quiet=True)
    page.refused = {Q1}
    app.process(app._select())
    states = {k: r["state"] for k, r in app.progress.data.items()}
    assert states == {"Statement:2025-12-31:Quarterly Statement": State.COMPLETED.value,
                      "Statement:2026-03-31:Quarterly Statement": State.FAILED.value,
                      "Statement:2026-06-30:Quarterly Statement": State.COMPLETED.value}
    assert not app.stats.get("session_expired") and app.stats["failed"] == 1


def test_a_refused_request_when_the_session_is_gone_stops_the_run(tmp_path):
    page = OnePlanPage(have={Q2, Q1, Q4})
    app = receipt_app(docs, tmp_path, owner="")
    app.page = lambda: page
    app._on_its_site = lambda: page
    app.cmd_discover(quiet=True)
    page.refused = {Q2, Q1, Q4}
    real = page.evaluate
    page.evaluate = lambda js, arg=None: False if "txnTokenValue" in js and "sodReqIndicator" not in js \
        else real(js, arg)
    # The run stops as one that stopped, with the sign-out in flight.
    with pytest.raises(SystemExit):
        app.process(app._select())
    assert app.stats.get("session_expired") == 1
    assert not any(r.get("state") == State.FAILED.value for r in app.progress.data.values())
