"""A Diagnose that found only a sign-in page never reads as a report saved.

Made while signed out, a support report exited 0 and the panel said "Support
report saved", ready to attach to an issue. The app's own checks had just
written down that the window was on a sign-in page. Every app's Diagnose
writes what it found through write_shaped and ends in failure.write_survey,
so that is where the two are put together.
"""
import json

import pytest

from paperpull_core import failure, run_reporting, words


def _diagnose(folder, info):
    words.write_shaped(folder / "diagnose-documents.json", info, words.words_for("Testco"))


@pytest.mark.parametrize("found", [{"signed_out": True}, {"signed_out": False, "challenge": "A check"},
                                   {"signed_out": True, "collected": 0}])
def test_a_sign_in_page_or_a_check_ends_as_nothing_read(tmp_path, found):
    _diagnose(tmp_path, dict(found))
    said = []
    with pytest.raises(SystemExit) as out:
        failure.write_survey(tmp_path, provider="Testco", say=said.append)
    assert out.value.code == run_reporting.NOTHING_READ
    assert list(tmp_path.glob("survey-*.json")), "the survey is still written"


def test_the_exit_is_the_last_thing_so_the_survey_is_whole(tmp_path):
    _diagnose(tmp_path, {"signed_out": True})
    with pytest.raises(SystemExit):
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    survey = next(tmp_path.glob("survey-*.json"))
    assert json.loads(survey.read_text(encoding="utf-8"))["kind"] == "paperpull-survey"


def test_a_signed_in_page_is_a_report_saved(tmp_path):
    _diagnose(tmp_path, {"signed_out": False, "challenge": None, "collected": 3})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


def test_a_signed_in_page_it_cannot_make_sense_of_is_a_report_saved(tmp_path):
    """Nothing found on a signed-in page is what a repair needs to see, and
    no sign-in would change it."""
    _diagnose(tmp_path, {"signed_out": False, "challenge": None, "collected": 0, "documents_page_found": False})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


def test_rows_read_are_not_nothing_read_whatever_a_check_said(tmp_path):
    _diagnose(tmp_path, {"signed_out": True, "collected": 12})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


# Every key an app's Diagnose writes the count of what a reader of the
# provider's own list read under, as the apps write them. Most write
# "collected", four whose list is an API answer "documents_total", and U.S.
# Bank and Discover Card a count from each of two readers. The census in
# test_every_diagnose_counts_under_a_key_the_core_reads.py holds the apps
# to the core's own list, and this to what the core does with each.
COUNT_KEYS = ("collected", "documents_total", "collected_generic", "statements_read",
              "statement_links")


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_rows_read_under_any_count_key_are_not_nothing_read(tmp_path, key):
    """A report that read rows, made where a sign-in check also tripped, is
    a report saved, whichever key the app counted them under."""
    _diagnose(tmp_path, {"signed_out": True, key: 12})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_rows_read_past_a_check_are_not_nothing_read(tmp_path, key):
    _diagnose(tmp_path, {"signed_out": False, "challenge": "A check", key: 3})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


@pytest.mark.parametrize("value", ["ERR the list would not answer", "12", True, [1, 2], {"rows": 2},
                                   1.0, 0, None, -1])
@pytest.mark.parametrize("key", COUNT_KEYS)
def test_only_a_count_above_none_is_something_read(tmp_path, key, value):
    """An error an app wrote where its count goes, a yes, a list or a
    number that is not a whole one is not rows read. A signed-out report
    holding one still says it read nothing."""
    _diagnose(tmp_path, {"signed_out": True, key: value})
    with pytest.raises(SystemExit) as out:
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    assert out.value.code == run_reporting.NOTHING_READ


def test_one_count_above_none_is_enough(tmp_path):
    _diagnose(tmp_path, {"signed_out": True, "collected": 0, "statements_read": "ERR x",
                         "statement_links": 4})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


def test_counts_of_none_and_an_error_are_nothing_read(tmp_path):
    _diagnose(tmp_path, {"signed_out": True, "collected_generic": 0, "statements_read": "ERR x"})
    with pytest.raises(SystemExit) as out:
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    assert out.value.code == run_reporting.NOTHING_READ


@pytest.mark.parametrize("key", ["rows_collected", "links_collected", "print_receipt_controls",
                                 "invoice_controls", "pay_assignments", "rows", "row_counts",
                                 "cards_collected", "collect_error"])
def test_a_count_that_is_not_of_documents_is_not_something_read(tmp_path, key):
    """A loose scrape's count of every row or link on the page, which a
    sign-in page's own lists fill, a count of a receipt page's buttons, of
    pay assignments or a key no app counts its documents under is not read
    as documents."""
    _diagnose(tmp_path, {"signed_out": True, key: 5})
    with pytest.raises(SystemExit) as out:
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    assert out.value.code == run_reporting.NOTHING_READ


def test_the_list_here_is_the_cores(tmp_path):
    assert tuple(words.COUNT_KEYS) == COUNT_KEYS


def _saved(folder) -> bool:
    try:
        failure.write_survey(folder, provider="Testco", say=lambda *_a: None)
    except SystemExit as out:
        assert out.code == run_reporting.NOTHING_READ
        return False
    return True


def test_a_count_past_what_the_file_holds_still_counts(tmp_path):
    _diagnose(tmp_path, {"signed_out": True, "collected": 250000})
    assert _saved(tmp_path)


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_keys_written_through_fixed_are_read(tmp_path, key):
    """ING writes its keys as Fixed strings."""
    _diagnose(tmp_path, {words.Fixed("signed_out"): True, words.Fixed(key): 3})
    assert _saved(tmp_path)


def test_none_beside_a_count_past_a_check_is_something_read(tmp_path):
    _diagnose(tmp_path, {"challenge": "A check", "signed_out": False, "collected": None,
                         "documents_total": 2})
    assert _saved(tmp_path)


@pytest.mark.parametrize("key", COUNT_KEYS)
def test_a_signed_in_page_with_an_error_where_a_count_goes_is_a_report_saved(tmp_path, key):
    _diagnose(tmp_path, {"signed_out": False, "challenge": None, key: "ERR x"})
    assert _saved(tmp_path)


@pytest.mark.parametrize("found", [{"signed_out": None}, {"signed_out": ""}, {"signed_out": 0},
                                   {"signed_out": False, "challenge": ""},
                                   {"signed_out": False, "challenge": None}])
def test_a_check_that_said_nothing_is_no_check(tmp_path, found):
    _diagnose(tmp_path, dict(found))
    assert _saved(tmp_path)


@pytest.mark.parametrize("first, then, saved", [(0, 3, True), (3, 0, False)])
def test_a_later_count_replaces_an_earlier_one(tmp_path, first, then, saved):
    _diagnose(tmp_path, {"signed_out": True, "collected": first})
    _diagnose(tmp_path, {"signed_out": True, "collected": then})
    assert _saved(tmp_path) is saved


def test_a_count_in_a_file_that_is_not_a_diagnose_changes_nothing(tmp_path):
    """eBay, Best Buy, Home Depot and Lowe's write a history file beside
    their finding, with counts and no signed_out."""
    _diagnose(tmp_path, {"signed_out": True, "collected": 0})
    words.write_shaped(tmp_path / "diagnose-history.json", {"collected": 5, "cards_collected": 9},
                       words.words_for("Testco"))
    assert not _saved(tmp_path)


def test_the_file_written_is_the_same_whatever_it_counted(tmp_path):
    found = {"signed_out": True, "collected": 5, "rows_collected": 7, "error": "x"}
    _diagnose(tmp_path, dict(found))
    written = json.loads((tmp_path / "diagnose-documents.json").read_text(encoding="utf-8"))
    assert written == words.shape_tree(found, words.words_for("Testco"))
    assert written["collected"] == 5 and written["rows_collected"] == 7


def test_it_counts_for_the_run_that_found_it_only(tmp_path):
    other = tmp_path / "other"
    _diagnose(tmp_path, {"signed_out": True})
    assert failure.write_survey(other, provider="Testco", say=lambda *_a: None), "another folder's run"
    with pytest.raises(SystemExit):
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None), "asked once"


def test_a_later_look_replaces_an_earlier_one(tmp_path):
    _diagnose(tmp_path, {"signed_out": True})
    _diagnose(tmp_path, {"signed_out": False})
    assert failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


def test_a_file_that_is_not_a_diagnose_changes_nothing(tmp_path):
    _diagnose(tmp_path, {"signed_out": True})
    words.write_shaped(tmp_path / "diagnose-extra.json", {"rows": 3}, words.words_for("Testco"))
    with pytest.raises(SystemExit):
        failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)


def test_the_words_fit_where_it_runs(capsys, monkeypatch):
    monkeypatch.delenv(run_reporting.MARK_ENV, raising=False)
    run_reporting.nothing_read()
    terminal = capsys.readouterr().out
    assert "run Diagnose again" in terminal
    monkeypatch.setenv(run_reporting.MARK_ENV, "a" * 32)
    run_reporting.nothing_read()
    panel = capsys.readouterr().out
    assert "make the report again" in panel and "Diagnose" not in panel
    assert run_reporting.nothing_read().code == run_reporting.NOTHING_READ
