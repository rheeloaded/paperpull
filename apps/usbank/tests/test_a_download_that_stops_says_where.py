"""A U.S. Bank download that saves nothing says which step stopped it and
what the search for its row saw (#106).

Every download that came back with nothing was written down as "capture
the document", "the document would not render", whether it had never found
the statement's row, never chosen its account or year, or pressed and got
nothing. For three rounds a tester's runs were read as a document that
would not render, when nothing had been pressed at all. Now the step and
the reason are the real ones, in words of our own, and the failure file
counts what the search for the row saw. Everything here is invented.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_docs
import usbank_site as site
from paperpull_core import words as W
from usbank_pages import CARD, CHECKING, STATEMENTS, show


def _download(page, tmp_path, account, date, listed_under=""):
    out = tmp_path / "Statements" / ("%s statement.pdf" % date)
    kw = {"listed_under": listed_under} if listed_under else {}
    return site.usbank_download(page, page.context, account, date, out, **kw), out


def test_a_statement_with_no_row_of_its_date_stops_at_finding_it(page, tmp_path):
    show(page)
    got, out = _download(page, tmp_path, CARD, "2031-10-10", listed_under=CARD)
    assert not got and not out.exists()
    assert got.step == "find the statement"
    assert got.reason == "no row reads as this date"
    assert got.row_search == {"sections": 1, "statement_sections": 1, "other_account_rows": 0,
                              "rows": 1, "with_download": 1, "this_year": 1, "this_month": 1,
                              "this_date": 0}


def test_two_rows_of_one_date_stop_at_finding_it(page, tmp_path):
    two = dict(STATEMENTS, **{CARD: {"2031": ["October 9, 2031", "October 9, 2031"],
                                     "2030": []}})
    show(page, statements=two)
    got, _out = _download(page, tmp_path, CARD, "2031-10-09", listed_under=CARD)
    assert got.step == "find the statement"
    assert got.reason == "two rows read as this date"
    assert got.row_search["this_date"] == 2


def test_an_account_the_picker_does_not_offer_stops_at_choosing_it(page, tmp_path):
    show(page)
    got, _out = _download(page, tmp_path, "Other Card ...9999", "2031-10-09")
    assert got.step == "choose the account"
    assert got.reason == "the account picker did not take it"


def test_a_year_the_picker_does_not_offer_stops_at_choosing_it(page, tmp_path):
    show(page)
    got, _out = _download(page, tmp_path, CARD, "2027-10-09", listed_under=CARD)
    assert got.step == "choose the year"
    assert got.reason == "the year picker did not take it"


def test_a_page_that_will_not_open_stops_at_opening_it(page, tmp_path, monkeypatch):
    show(page)
    monkeypatch.setattr(site, "ensure_statements", lambda pg: False)
    got, _out = _download(page, tmp_path, CARD, "2031-10-09", listed_under=CARD)
    assert got.step == "open the statements page"
    assert got.reason == "the statements page would not open"


def test_a_press_that_brings_nothing_stops_at_capturing(page, tmp_path):
    """The Download button is pressed and nothing comes of it, no download
    and no window."""
    show(page)
    expect = page.expect_download
    page.expect_download = lambda *a, timeout=None, **kw: expect(*a, timeout=1500, **kw)
    got, out = _download(page, tmp_path, CARD, "2031-10-09", listed_under=CARD)
    assert not got and not out.exists()
    assert got.step == "capture the document"
    assert got.reason == "no document came of the press"
    assert got.row_search["this_date"] == 1


def test_a_statement_is_found_under_the_account_it_was_listed_under(page, tmp_path, monkeypatch):
    """The row is pressed once its own account is chosen, from another
    account on show."""
    show(page)
    pressed = []

    def press(pg, ctx, button, label, date, out_path):
        pressed.append(label)
        return False

    monkeypatch.setattr(site, "_press_and_capture", press)
    got, _out = _download(page, tmp_path, CHECKING, "2031-09-13", listed_under=CHECKING)
    assert pressed == ["Download September 13, 2031 statement."]
    assert got.step == "capture the document"


def _pressed(monkeypatch):
    pressed = []

    def press(pg, ctx, button, label, date, out_path):
        pressed.append(label)
        return False

    monkeypatch.setattr(site, "_press_and_capture", press)
    return pressed


def test_the_account_is_chosen_by_its_picker_label_and_its_row_by_its_heading(
        page, tmp_path, monkeypatch):
    """The card's section names it another way than the picker does."""
    show(page, names={CARD: "Visa Platinum Card ...2222"})
    pressed = _pressed(monkeypatch)
    _download(page, tmp_path, "Visa Platinum Card ...2222", "2031-10-09", listed_under=CARD)
    assert pressed == ["Download October 9, 2031 statement."]


def test_an_old_list_that_stays_is_never_pressed_as_the_new_accounts(
        page, tmp_path, monkeypatch):
    """The business card's list stays on show after the card is chosen, its
    sections name no account, and both have a statement of that day."""
    monkeypatch.setattr(site, "REDRAW_MS", 1000)
    same_day = dict(STATEMENTS, **{CARD: {"2031": ["October 2, 2031"], "2030": []}})
    show(page, statements=same_day, redraw="keep", delay_ms=4000, unnamed=True)
    pressed = _pressed(monkeypatch)
    got, _out = _download(page, tmp_path, CARD, "2031-10-02", listed_under=CARD)
    assert pressed == []
    assert got.step == "choose the account"


def test_a_heading_that_follows_the_picker_is_never_pressed_for_the_old_rows(
        page, tmp_path, monkeypatch):
    """The card's name heads the list at once, and the rows under it are the
    business card's, a statement of the same day among them, for two
    seconds more."""
    same_day = dict(STATEMENTS, **{CARD: {"2031": ["October 2, 2031"], "2030": []}})
    show(page, statements=same_day, redraw="heading", delay_ms=2000)
    whose = []

    def press(pg, ctx, button, label, date, out_path):
        whose.append(button.get_attribute("data-acct"))
        return False

    monkeypatch.setattr(site, "_press_and_capture", press)
    _download(page, tmp_path, CARD, "2031-10-02", listed_under=CARD)
    assert whose == [CARD]


def _config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Test Person", "output_dir": str(tmp_path / "out"),
        "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
        "document_types": ["Statement"], "default_start_date": "",
        "min_pdf_bytes": 2000, "max_path_length": 240,
        "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5}), encoding="utf-8")
    return cfg


def test_the_failure_file_names_the_step_and_counts_the_search(page, tmp_path, monkeypatch):
    show(page)
    args = usbank_docs.build_parser().parse_args(["--config", str(_config(tmp_path)), "--pilot"])
    app = usbank_docs.App(args)
    app._work_page = page
    app.stats["mode"] = "pilot"
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    doc = usbank_docs.Document(title="Statement", category="Statement", summary="Statement",
                               date="2031-10-10", account=CARD, listed_under=CARD)
    app.download_one(page, doc, "2031-10-10 U.S. Bank Statement.pdf")
    files = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["step"] == "find the statement"
    assert report["reason"] == "no row reads as this date"
    assert report["extra"]["row_search"]["rows"] == 1
    assert report["extra"]["row_search"]["this_date"] == 0
    rec = app.progress.get(doc.key)
    # Nothing was saved, so it is a failure the next run tries again (#152).
    assert rec["state"] == "Failed"
    assert "find the statement" in rec["notes"]


def _named_steps():
    """Every step and reason usbank_site names for a download or a search,
    the constants handed to Attempt and Search."""
    tree = ast.parse(Path(site.__file__).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("Attempt", "Search"):
            for k in node.keywords:
                if k.arg in ("step", "reason") and isinstance(k.value, ast.Constant):
                    found.append(k.value.value)
    return found


def test_every_step_and_reason_a_download_names_comes_through_the_word_list():
    named = _named_steps()
    assert len(set(named)) >= 10, named
    words = W.words_for("U.S. Bank", site)
    changed = sorted({s for s in named if W.shape(s, words) != s})
    assert not changed, "these would leave as their shape: %s" % changed
    from paperpull_core.failure import _STEP_RE
    assert all(_STEP_RE.match(s) for s in named), named
