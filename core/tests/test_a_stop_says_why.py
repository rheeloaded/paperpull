"""A run that stops says why, so the panel never guesses a sign-out.

Every stop read the same on the panel: "<provider> may have signed you
out partway ... Sign in again, then continue." A stop at a page that was
not what the app expected, most often a provider's site having changed,
said that too, so the person signed in and pressed Continue, which stopped
at the same place again. A timeout or an error the app did not expect read
as a sign-out or as an exit code.

The run's result line now carries one word for why, worked out in one
place from the exception the run is leaving on (run_reporting.stop_reason).
"""
import importlib.util
import json
from pathlib import Path

import pytest

from paperpull_core import browser, pressing, run_reporting
from paperpull_core.run_reporting import PREFIX, report_run_result, stop_reason

ROOT = Path(__file__).resolve().parents[2]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


panel = _module("paperpull_panel_run_result_stop", ROOT / "gui" / "run_result.py")


@pytest.fixture(autouse=True)
def nobody_asked_yet(monkeypatch):
    monkeypatch.setattr(browser, "_NOBODY_ANSWERED", False)


def _why_leaving_on(raise_it):
    """stop_reason() as an app's finally sees it, on the way out of raise_it."""
    seen = {}
    try:
        try:
            raise_it()
        finally:
            seen["why"] = stop_reason()
    except BaseException:
        pass
    return seen["why"]


def _stop():
    return pressing.Stop("open the documents page", "the page was not the documents page",
                         ["The documents page did not open."])


def test_a_run_not_leaving_on_anything_has_no_reason():
    assert stop_reason() == ""


def test_a_changed_page_is_said_as_one_even_once_main_has_turned_it_into_an_exit():
    """pressing.stop_run raises a plain SystemExit while handling the Stop."""
    def stop_then_leave():
        try:
            raise _stop()
        except pressing.Stop:
            raise SystemExit(0)
    assert _why_leaving_on(stop_then_leave) == "page"
    assert _why_leaving_on(lambda: (_ for _ in ()).throw(_stop())) == "page"


def test_a_question_nobody_was_there_to_answer_is_the_provider_needing_the_person(monkeypatch):
    monkeypatch.setattr(browser, "can_ask", lambda: False)

    def signed_out():
        if browser.ask_or_none("Press Enter after you are signed in... ") is None:
            raise SystemExit(0)
    assert _why_leaving_on(signed_out) == "needs_you"


def test_an_exit_with_nobody_asked_is_no_reason_the_core_can_name():
    """An app's own stop, as a list it could not read, says why in its
    words, and the page sends the person to them."""
    def leave():
        raise SystemExit(0)
    assert _why_leaving_on(leave) == ""


def test_an_exit_with_a_message_is_not_taken_for_the_provider_needing_the_person(monkeypatch):
    monkeypatch.setattr(browser, "_NOBODY_ANSWERED", True)

    def cannot_connect():
        raise SystemExit("Could not connect to your signed-in browser.")
    assert _why_leaving_on(cannot_connect) == ""


class TimeoutError(Exception):
    """Named as Playwright's is."""


@pytest.mark.parametrize("err, why", [
    (TimeoutError("Timeout 30000ms exceeded."), "slow"),
    (RuntimeError("Page.goto: net::ERR_CONNECTION_RESET"), "error"),
    (KeyError("statement_date"), "error"),
])
def test_anything_else_is_slow_or_an_error(err, why):
    def fail():
        raise err
    assert _why_leaving_on(fail) == why


def test_the_result_line_carries_the_reason_only_for_a_stop(capsys):
    try:
        try:
            raise _stop()
        except pressing.Stop:
            raise SystemExit(0)
    except SystemExit:
        pass
    report_run_result({"new_files": []})
    clean = json.loads(capsys.readouterr().out.split(PREFIX, 1)[1])
    assert "stop" not in clean and clean["stopped"] == 0
    try:
        raise SystemExit(0)
    except SystemExit:
        try:
            raise _stop()
        except pressing.Stop:
            report_run_result({"new_files": []})
    stopped = json.loads(capsys.readouterr().out.split(PREFIX, 1)[1])
    assert (stopped["stopped"], stopped["stop"]) == (1, "page")


def test_the_panel_takes_the_same_words_and_no_others():
    assert panel.STOP_REASONS == run_reporting.STOP_REASONS
    mark = panel.new_mark()

    def line(**extra):
        return panel.PREFIX + mark + " " + json.dumps(dict(
            {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}, **extra))
    for word in run_reporting.STOP_REASONS:
        assert panel.parse(line(stopped=1, stop=word), mark)["stop"] == word
    assert panel.parse(line(stopped=1, stop="signed_out_maybe"), mark)["stop"] == ""
    assert panel.parse(line(stopped=1, stop=7), mark)["stop"] == ""
    assert panel.parse(line(stopped=0, stop="page"), mark)["stop"] == "", "only a stop has a reason"
    assert panel.parse(line(stopped=1), mark)["stop"] == "", "an app from before sends none"
