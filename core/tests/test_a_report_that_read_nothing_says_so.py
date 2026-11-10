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
