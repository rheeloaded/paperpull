"""Requested statements (#103), driven through the app's own discovery and
download with the signed-in page stood in.

The holder asks Citi for older statements, and Citi lists them for a
limited time on a call of their own, archiveStatements/retrieve, each by
its month alone ("202010") with a status and an expiry. The answers here
have the measured shapes and invented values only. No real account, no
real id, no network, nothing pressed."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import citi_docs
import citi_site as site
from paperpull_core import listing
from paperpull_core.models import State
from paperpull_core.testkit import sample_pdf

PDF = sample_pdf()
CARD = {"accountId": "invented-uuid-one",
        "accountNickname": "Costco Anywhere Visa Card by Citi - 0000", "accountType": "CARDS"}
OTHER = {"accountId": "invented-uuid-two",
         "accountNickname": "Citi Double Cash Card - 9999", "accountType": "CARDS"}
LABEL = "Costco Anywhere Visa"


def _json(body, status=200):
    return {"status": status, "ct": "application/json", "json": body}


def _regular(*dates):
    return _json({"statementsByYear": [{"displayYearTitle": d[-4:], "statementsByMonth": [
        {"displayDate": "x", "statementDate": d}]} for d in dates],
        "archivedStatementDetails": None})


def _entry(month, status="F", expiry="20311204", text="Dec, 04"):
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return {"displayDate": "%s %s" % (names[int(month[4:]) - 1], month[:4]),
            "statementDate": month, "statusIndicator": status,
            "documentExpiryDate": expiry, "documentExpirationDateText": text,
            "adaTemplate": "a" * 23}


def _requested(*entries, start="01/01/2027"):
    body = {"archivedStatementsByMonth": list(entries)}
    if start is not None:
        body["archivedStatementRequestStartDate"] = start
    return _json(body)


class Page:
    """A signed-in citi.com tab whose in-page fetch answers from a script,
    by URL, per card for the lists. Every call is kept."""
    url = "https://online.citi.com/US/nga/accstatement"

    def __init__(self, cards=(CARD,), regular=None, requested=None, pdf=None):
        self.cards = list(cards)
        self.regular = regular or {}
        self.requested = requested or {}
        self.pdf = pdf if pdf is not None else {"status": 200, "ct": "application/pdf",
                                                "b64": base64.b64encode(PDF).decode()}
        self.calls = []

    def is_closed(self):
        return False

    def title(self):
        return "Account Statements"

    def locator(self, *_):
        class _L:
            def count(self):
                return 0

            def inner_text(self, **_):
                return ""
        return _L()

    def on(self, *_):
        pass

    def goto(self, *_a, **_kw):
        raise AssertionError("the statements page is already open")

    def wait_for_timeout(self, *_):
        pass

    def evaluate(self, _js, args):
        url, body, headers = args
        assert headers == site.APP_HEADERS
        self.calls.append((url, dict(body)))
        if url == site.API_ACCOUNTS:
            return _json({"eligibleAccounts": {"cardAccounts": self.cards}})
        if url == site.API_LIST:
            return self.regular.get(body["accountId"], _regular())
        if url == site.API_REQUESTED:
            return self.requested.get(body["accountId"], _requested())
        if url == site.API_PDF:
            return self.pdf
        raise AssertionError("an unexpected call")

    def pdf_bodies(self):
        return [b for u, b in self.calls if u == site.API_PDF]


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    def build(page, *argv):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": "",
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5}),
            encoding="utf-8")
        args = citi_docs.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = citi_docs.App(args)
        app._work_page = page
        app._dl_dir = None
        monkeypatch.setattr(app, "page", lambda: page)
        monkeypatch.setattr(app, "_on_its_site", lambda: page)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        return app
    return build


def _by_month(app):
    return {r["archived_month"]: r for r in app.discovery.data.values()
            if r.get("archived_month")}


def test_requested_statements_are_listed_and_downloaded_with_the_listed_month(make_app):
    page = Page(regular={CARD["accountId"]: _regular("09/22/2026", "08/22/2026")},
                requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202012"))})
    app = make_app(page)
    app.cmd_run("all")
    got = _by_month(app)
    assert set(got) == {"202010", "202012"}
    rec = got["202010"]
    assert rec["date"] == "2020-10-31" and rec["title"] == "Monthly Statement - October 2020"
    assert rec["category"] == "Statement" and rec["account"] == LABEL
    assert rec["archived_expires"] == "2031-12-04"
    assert {"accountId": CARD["accountId"], "statementDate": "202010",
            "requestType": "ARCHIVED STATEMENTS"} in page.pdf_bodies()
    assert {"accountId": CARD["accountId"], "statementDate": "09/22/2026",
            "requestType": "RECENT STATEMENTS"} in page.pdf_bodies()
    assert len(page.pdf_bodies()) == 4
    done = {r["archived_month"]: r for r in app.progress.data.values() if r.get("archived_month")}
    assert done["202010"]["state"] == State.COMPLETED.value and done["202010"]["downloaded_ok"]
    saved = Path(done["202010"]["pdf_path"])
    assert saved.read_bytes() == PDF and saved.name.startswith("2020-10-31 ")
    assert (page.calls[2] == (site.API_REQUESTED, {"accountId": CARD["accountId"]}))
    assert listing.last(app) == listing.COMPLETE

    # A second run downloads nothing again.
    before = len(page.pdf_bodies())
    make_app(page).cmd_run("all")
    assert len(page.pdf_bodies()) == before


def test_regular_keys_are_unchanged_and_never_meet_a_requested_one(make_app):
    page = Page(regular={CARD["accountId"]: _regular("10/31/2020")},
                requested={CARD["accountId"]: _requested(_entry("202012"))})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    keys = set(app.discovery.data)
    assert "Statement:2020-10-31:Monthly Statement - October 31, 2020:Costco Anywhere Visa" in keys
    assert "Statement:2020-12-31:Monthly Statement - December 2020:Costco Anywhere Visa" in keys
    regular = app.discovery.data[
        "Statement:2020-10-31:Monthly Statement - October 31, 2020:Costco Anywhere Visa"]
    assert regular["archived_month"] == "" and regular["href"] == CARD["accountId"]


def test_a_month_the_regular_list_has_is_skipped(make_app):
    page = Page(regular={CARD["accountId"]: _regular("10/22/2020")},
                requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202009"))})
    app = make_app(page)
    app.cmd_run("all")
    assert set(_by_month(app)) == {"202009"}
    bodies = page.pdf_bodies()
    assert [b["statementDate"] for b in bodies] == ["10/22/2020", "202009"]


def test_a_month_saved_before_as_a_regular_statement_is_not_taken_again(make_app):
    first = Page(regular={CARD["accountId"]: _regular("10/22/2020")})
    make_app(first).cmd_run("all")
    # The regular list has since dropped August, and the holder requested it.
    later = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                 requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202003"))})
    app = make_app(later)
    app.cmd_run("all")
    assert set(_by_month(app)) == {"202003"}
    assert [b["statementDate"] for b in later.pdf_bodies()] == ["09/22/2026", "202003"]


def test_another_cards_month_is_not_a_reason_to_skip(make_app):
    page = Page(cards=(CARD, OTHER),
                regular={OTHER["accountId"]: _regular("10/22/2020")},
                requested={CARD["accountId"]: _requested(_entry("202010"))})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert set(_by_month(app)) == {"202010"}
    assert _by_month(app)["202010"]["href"] == CARD["accountId"]


def test_a_status_other_than_ready_is_left(make_app):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", status="P"), _entry("202012", status=""), _entry("202009"))})
    app = make_app(page)
    app.cmd_run("all")
    assert set(_by_month(app)) == {"202009"}
    assert [b["statementDate"] for b in page.pdf_bodies()] == ["202009"]


def test_an_answer_without_a_start_date_is_a_list_not_read(make_app, capsys):
    page = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                requested={CARD["accountId"]: _requested(_entry("202010"), start=None)})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert _by_month(app) == {}
    assert listing.last(app) == listing.STOPPED
    assert "did not give the requested statements list" in capsys.readouterr().out
    # The regular statements are still listed.
    assert any(r["date"] == "2026-09-22" for r in app.discovery.data.values())


def test_the_measured_empty_answer_without_a_start_date_is_not_none_requested(make_app):
    page = Page(requested={CARD["accountId"]: _requested(start=None)})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert listing.last(app) == listing.STOPPED


@pytest.mark.parametrize("answer", [
    {"status": 500, "ct": "application/json", "json": {"errors": []}},
    {"status": 200, "ct": "application/json", "json": None},
    {"status": 200, "ct": "application/octet-stream", "b64": ""},
])
def test_any_other_odd_answer_is_a_list_not_read(make_app, answer):
    page = Page(requested={CARD["accountId"]: answer})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert listing.last(app) == listing.STOPPED


def test_an_empty_real_answer_lists_none_and_the_listing_is_whole(make_app):
    page = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                requested={CARD["accountId"]: _requested()})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert _by_month(app) == {}
    assert listing.last(app) == listing.COMPLETE


def test_a_list_not_read_never_marks_a_known_one_no_longer_listed(make_app):
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"))})
    make_app(page).cmd_discover(quiet=True)
    page.requested = {CARD["accountId"]: _requested(start=None)}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    key = next(iter(_by_month(app).values()))
    assert key["state"] == State.DISCOVERED.value


def test_the_pdf_bytes_are_saved_and_anything_else_is_refused(tmp_path):
    good = Page()
    out = tmp_path / "r.pdf"
    assert site.download_bill(good, None, "2020-10-31", out, account_id="invented-uuid-one",
                              archived_month="202010")
    assert out.read_bytes() == PDF
    assert good.pdf_bodies()[-1] == {"accountId": "invented-uuid-one", "statementDate": "202010",
                                     "requestType": "ARCHIVED STATEMENTS"}
    for answer in [
            {"status": 200, "ct": "application/json",
             "json": {"pdf": base64.b64encode(PDF).decode()}},
            {"status": 200, "ct": "application/pdf",
             "b64": base64.b64encode(b"<html>not a pdf</html>").decode()},
            {"status": 200, "ct": "application/pdf", "b64": "not base64 at all!"},
            {"status": 200, "ct": "application/pdf", "b64": ""}]:
        bad = Page(pdf=answer)
        out2 = tmp_path / "s.pdf"
        assert not site.download_bill(bad, None, "2020-10-31", out2,
                                      account_id="invented-uuid-one", archived_month="202010")
        assert not out2.exists()


def test_a_month_that_is_not_the_records_is_never_asked_for(tmp_path):
    page = Page()
    assert not site.download_bill(page, None, "2020-12-31", tmp_path / "x.pdf",
                                  account_id="invented-uuid-one", archived_month="202010")
    assert not site.download_bill(page, None, "2020-10-31", tmp_path / "y.pdf",
                                  account_id="invented-uuid-one", archived_month="10/2020")
    assert page.pdf_bodies() == []


def test_a_non_pdf_answer_is_a_failure_through_the_app(make_app):
    """Nothing was saved, so nothing waits in Manual Review, and the next
    run asks for the month again (#152)."""
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"))},
                pdf={"status": 200, "ct": "application/json", "json": {"error": "x"}})
    app = make_app(page)
    app.cmd_run("all")
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.FAILED.value and not rec.get("downloaded_ok")
    assert not list(app.paths.folder_for("Statement").glob("*.pdf"))


def test_expiry_passed_marks_it_no_longer_listed_not_failed(make_app, monkeypatch):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))})
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-18")
    make_app(page).cmd_discover(quiet=True)
    # The run comes after the day it stopped being listed.
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-21")
    app = make_app(page, "--resume")
    app.cmd_resume()
    assert page.pdf_bodies() == []
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.NO_LONGER_LISTED.value
    assert app.stats["failed"] == 0 and app.stats["manual_review"] == 0
    page.requested = {CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))}
    app = make_app(page)
    app.cmd_run("all")
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.NO_LONGER_LISTED.value
    assert app.stats["failed"] == 0 and app.stats["manual_review"] == 0
    assert page.pdf_bodies() == []


def test_expiry_found_at_download_time_marks_it_no_longer_listed(make_app, monkeypatch):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))})
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-18")
    app = make_app(page)
    app.cmd_discover(quiet=True)
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-21")
    app.process(app._select())
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.NO_LONGER_LISTED.value
    assert app.stats["failed"] == 0 and app.stats.get("no_longer_listed") == 1
    assert page.pdf_bodies() == []


def test_one_a_later_listing_drops_is_no_longer_listed_and_back_when_listed_again(make_app):
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202012"))})
    make_app(page).cmd_discover(quiet=True)
    page.requested = {CARD["accountId"]: _requested(_entry("202012"))}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    states = {r["archived_month"]: (app.progress.get(k) or r)["state"]
              for k, r in app.discovery.data.items() if r.get("archived_month")}
    assert states == {"202010": State.NO_LONGER_LISTED.value, "202012": State.DISCOVERED.value}
    assert listing.last(app) == listing.COMPLETE

    page.requested = {CARD["accountId"]: _requested(_entry("202010"), _entry("202012"))}
    app = make_app(page)
    app.cmd_run("all")
    assert sorted(b["statementDate"] for b in page.pdf_bodies()) == ["202010", "202012"]


def test_a_saved_requested_statement_is_never_marked_no_longer_listed(make_app):
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"))})
    make_app(page).cmd_run("all")
    page.requested = {CARD["accountId"]: _requested()}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"]


def test_the_log_holds_counts_and_fixed_words_only(make_app, caplog):
    caplog.set_level("INFO")
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010"), _entry("202012", status="P"))},
        pdf={"status": 200, "ct": "application/json", "json": {}})
    app = make_app(page)
    app.cmd_run("all")
    text = "\n".join(r.getMessage() for r in caplog.records
                     if r.name.startswith("citi_docs"))
    assert "Requested statements: 2 listed, 1 ready, 1 not ready" in text
    for private in ("202010", "202012", "invented-uuid", "2031", "Nov"):
        assert private not in text, private


def test_the_requested_list_parses_only_its_measured_shapes():
    assert site.requested_date("202010") == "2020-10-31"
    assert site.requested_date("202002") == "2020-02-29"
    assert site.requested_date("202013") is None
    assert site.requested_date("10/22/2020") is None
    assert site.requested_date("2020-10") is None
    assert site.month_title("202010") == "October 2020"
    assert site.expiry_date("20201204", "Dec, 04") == "2020-12-04"
    assert site.expiry_date("20201204", "") == "2020-12-04"
    assert site.expiry_date("20201204", "Jan, 15") == ""
    assert site.expiry_date("12042020", "Dec, 04") == ""
    assert site.expiry_date(None) == ""
    got = site.read_requested(_requested(_entry("202010"), dict(_entry("202012"),
                                                                statementDate="2020")))
    assert got == [{"month": "202010", "date": "2020-10-31", "status": "F",
                    "expires": "2031-12-04"},
                   {"month": "", "date": "", "status": "F", "expires": "2031-12-04"}]
    assert site.read_requested(_requested(start=None)) is None
    assert site.read_requested(_requested()) == []


def test_requesting_is_still_refused_and_nothing_is_pressed():
    assert not site.is_safe_control("Request Older Statements")
    assert site.is_safe_control("Requested Statements")
    for name in ("click", "press", "dispatch_event", "check", "tap"):
        assert ("." + name + "(") not in Path(site.__file__).read_text(encoding="utf-8")


# -- from the review ---------------------------------------------------------

def test_an_odd_regular_answer_leaves_the_requested_list_unread(make_app):
    page = Page(regular={CARD["accountId"]: _json({"errors": ["x"]}, status=500)},
                requested={CARD["accountId"]: _requested(_entry("202010"))})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert _by_month(app) == {}
    assert listing.last(app) == listing.STOPPED
    assert not any(u == site.API_REQUESTED for u, _b in page.calls)


def test_cards_sharing_a_name_leave_their_requested_statements(make_app):
    twin = dict(CARD, accountId="invented-uuid-three",
                accountNickname="Costco Anywhere Visa Card by Citi - 1111")
    page = Page(cards=(CARD, twin, OTHER),
                requested={CARD["accountId"]: _requested(_entry("202010")),
                           twin["accountId"]: _requested(_entry("202010")),
                           OTHER["accountId"]: _requested(_entry("202003"))})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert {(r["account"], m) for m, r in _by_month(app).items()} == {
        ("Citi Double Cash", "202003")}
    assert listing.last(app) == listing.COMPLETE
    asked = [b["accountId"] for u, b in page.calls if u == site.API_REQUESTED]
    assert asked == [OTHER["accountId"]]


def test_a_card_not_eligible_is_not_asked_and_the_listing_is_whole(make_app):
    regular = _regular("09/22/2026")
    regular["json"]["archivedStatementsEligibleFlag"] = False
    page = Page(regular={CARD["accountId"]: regular},
                requested={CARD["accountId"]: _requested(start=None)})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert listing.last(app) == listing.COMPLETE
    assert not any(u == site.API_REQUESTED for u, _b in page.calls)


def test_a_regular_record_never_saved_gives_way_to_the_requested_one(make_app):
    first = Page(regular={CARD["accountId"]: _regular("10/22/2020")})
    make_app(first).cmd_discover(quiet=True)  # listed, never downloaded
    later = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                 requested={CARD["accountId"]: _requested(_entry("202010"))})
    app = make_app(later)
    app.cmd_run("all")
    assert [b["statementDate"] for b in later.pdf_bodies()] == ["09/22/2026", "202010"]
    old = app.progress.get(
        "Statement:2020-10-22:Monthly Statement - October 22, 2020:Costco Anywhere Visa")
    assert old["state"] == State.NO_LONGER_LISTED.value


def test_a_dry_run_writes_no_state(make_app, monkeypatch):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))})
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-18")
    app = make_app(page)
    app.cmd_discover(quiet=True)
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-21")
    app.process(app._select(), dry_run=True)
    assert not any(r.get("archived_month") for r in app.progress.data.values())
    assert page.pdf_bodies() == []


def test_a_copy_kept_for_review_is_never_marked_no_longer_listed(make_app):
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"))})
    app = make_app(page)
    app.cmd_discover(quiet=True)
    key = next(k for k, r in app.discovery.data.items() if r.get("archived_month"))
    kept = app.paths.manual_review / "kept.pdf"
    kept.write_bytes(PDF)
    app.progress.update(key, dict(app.discovery.get(key), state=State.NEEDS_MANUAL_REVIEW.value,
                                  pdf_path=str(kept)))
    page.requested = {CARD["accountId"]: _requested()}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    assert app.progress.get(key)["state"] == State.NEEDS_MANUAL_REVIEW.value


def test_redownload_skips_a_saved_requested_statement_past_its_expiry(make_app, monkeypatch):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))})
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-18")
    make_app(page).cmd_run("all")
    assert len(page.pdf_bodies()) == 1
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-21")
    app = make_app(page, "--redownload")
    app.cmd_run("all")
    assert len(page.pdf_bodies()) == 1
    rec = next(r for r in app.progress.data.values() if r.get("archived_month"))
    assert rec["state"] == State.COMPLETED.value and app.stats["manual_review"] == 0


# -- the review of citi-requested ------------------------------------------------

def _put_aside(app, key):
    """The record of `key` as one put aside for review with its copy kept."""
    kept = app.paths.manual_review / "kept.pdf"
    kept.write_bytes(PDF)
    app.progress.update(key, dict(app.discovery.get(key), state=State.NEEDS_MANUAL_REVIEW.value,
                                  pdf_path=str(kept)))
    return kept


def test_a_regular_copy_kept_for_review_is_not_taken_again_as_a_requested_one(make_app):
    """A regular statement was put aside for review with its copy kept, and
    _already_done counts it as done. The regular list has since dropped it
    and the holder requested its month. That is the same statement, so it
    does not come as a second file, and once the review copy is gone the
    requested one is taken."""
    first = Page(regular={CARD["accountId"]: _regular("10/22/2020")})
    app = make_app(first)
    app.cmd_discover(quiet=True)
    [key] = list(app.discovery.data)
    kept = _put_aside(app, key)
    later = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                 requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202003"))})
    app = make_app(later)
    app.cmd_run("all")
    assert set(_by_month(app)) == {"202003"}
    assert [b["statementDate"] for b in later.pdf_bodies()] == ["09/22/2026", "202003"]
    assert app.progress.get(key)["state"] == State.NEEDS_MANUAL_REVIEW.value

    kept.unlink()
    again = Page(regular={CARD["accountId"]: _regular("09/22/2026")},
                 requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202003"))})
    app = make_app(again)
    app.cmd_run("all")
    assert [b["statementDate"] for b in again.pdf_bodies()] == ["202010"]


def test_an_empty_list_never_says_a_requested_statement_is_gone(make_app):
    """A requested statement is listed, and the next answer carries the
    start date and no entry. That is how a card with nothing requested
    answers, and a list emptied while statements were still requested has
    not been seen, so the statement is not marked No Longer Listed, and the
    run takes it. The answer is a list read, so the listing is whole."""
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"))})
    make_app(page).cmd_discover(quiet=True)
    page.requested = {CARD["accountId"]: _requested()}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    [rec] = _by_month(app).values()
    assert rec["state"] == State.DISCOVERED.value
    assert listing.last(app) == listing.COMPLETE
    app = make_app(page)
    app.cmd_run("all")
    assert [b["statementDate"] for b in page.pdf_bodies()] == ["202010"]


def test_an_empty_list_past_the_expiry_still_marks_it_gone(make_app, monkeypatch):
    page = Page(requested={CARD["accountId"]: _requested(
        _entry("202010", expiry="20261020", text="Oct, 20"))})
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-18")
    make_app(page).cmd_discover(quiet=True)
    monkeypatch.setattr(citi_docs, "_today", lambda: "2026-10-21")
    page.requested = {CARD["accountId"]: _requested()}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    [rec] = [(app.progress.get(k) or r) for k, r in app.discovery.data.items()
             if r.get("archived_month")]
    assert rec["state"] == State.NO_LONGER_LISTED.value


def test_a_list_that_still_has_entries_still_says_one_is_gone(make_app):
    """The other side of an empty list. A list read with entries that no
    longer has a statement it listed before still marks it."""
    page = Page(requested={CARD["accountId"]: _requested(_entry("202010"), _entry("202012"))})
    make_app(page).cmd_discover(quiet=True)
    page.requested = {CARD["accountId"]: _requested(_entry("202012", status="P"))}
    app = make_app(page)
    app.cmd_discover(quiet=True)
    states = {r["archived_month"]: (app.progress.get(k) or r)["state"]
              for k, r in app.discovery.data.items() if r.get("archived_month")}
    assert states["202010"] == State.NO_LONGER_LISTED.value
