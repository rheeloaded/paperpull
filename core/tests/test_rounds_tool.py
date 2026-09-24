"""The rounds tool is the baseline every change to the tester loop is
measured against, so a miscount here is a false conclusion later. Each
case below was wrong, or nearly wrong, against the real history.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

rounds = pytest.importorskip("rounds")

NAMES = {app: names for app, names, _, _ in rounds.PROVIDERS}
T0 = datetime(2026, 9, 20, tzinfo=timezone.utc)


def _at(hours):
    return (T0 + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _post(login, hours, body=""):
    return {"author": {"login": login}, "createdAt": _at(hours),
            "body": body}


def _issue(*comments, author="tester", body=""):
    return {"number": 1, "title": "[Provider request] X",
            "author": {"login": author}, "createdAt": _at(0), "body": body,
            "comments": list(comments)}


def _ship(hours, tag):
    return _post("owner", hours,
                 f"in [{tag}](https://x/releases/tag/v{tag})")


# -- names in commit subjects -------------------------------------------------

def test_a_digit_in_a_provider_name_is_not_a_round_number():
    """"Golden 1 round three" once read as "1 round", which handed round
    one to Meijer, American Family and ADP, named earlier in the same
    subject, and zero to Golden 1."""
    got = rounds.named_rounds(
        "Add Meijer, American Family and ADP Workforce Now scaffolds, "
        "Golden 1 round three", NAMES)
    assert got == {"golden1": 3}


def test_one_subject_can_name_different_rounds_for_different_providers():
    got = rounds.named_rounds(
        "PG&E round three and E*TRADE round four, from the tester's third "
        "pilots", NAMES)
    assert got == {"pge": 3, "etrade": 4}


def test_two_providers_sharing_one_round_phrase_both_get_it():
    got = rounds.named_rounds(
        "SMUD and State Farm round two from their first surveys", NAMES)
    assert got == {"smud": 2, "statefarm": 2}


def test_an_ordinal_before_the_word_counts():
    got = rounds.named_rounds(
        "A split decimal, an empty bracket, AT&T's second round, and no "
        "query strings in a survey", NAMES)
    assert got == {"att": 2}


def test_a_clause_naming_nobody_falls_back_to_the_whole_subject():
    got = rounds.named_rounds(
        "eBay, and why round two could never have worked", NAMES)
    assert got == {"ebay": 2}


def test_plural_rounds_names_no_round():
    """"Seven rounds from the overnight surveys" is seven providers'
    rounds, not round seven of anybody."""
    assert rounds.named_rounds(
        "Seven rounds from the overnight surveys: AT&T Regular PDF", NAMES
    ) == {}
    assert rounds.named_rounds(
        "ADP's tax check, and the rounds four testers' files asked for",
        NAMES) == {}


# -- what a tester said -------------------------------------------------------

@pytest.mark.parametrize("body", [
    "Success! Pilot downloaded the 5 most recent and Run All got the rest",
    "Pilot pulled 5 docs but the current bill was downloaded twice",
    "Pilot downloaded the most recent statement but failed to discover",
])
def test_a_pilot_that_saved_something_is_working(body):
    assert rounds.says_working(body)


@pytest.mark.parametrize("body", [
    "Discovery found 1 and pilot downloaded 0",
    "no downloads with Pilot",
    "Pilot could see only the most recent bill",
])
def test_a_pilot_that_saved_nothing_is_not(body):
    assert not rounds.says_working(body)


def test_quoted_text_and_pasted_logs_are_not_the_testers_words():
    """A tester quoting the maintainer, or pasting a log that says a
    document was downloaded in a line that then failed, has not said
    anything worked."""
    assert not rounds.says_working("> Success! it worked for me\nstill 0")
    assert not rounds.says_working(
        "no luck\n```\nPilot downloaded 3 then failed\n```")


# -- ships and reports on an issue --------------------------------------------

def test_a_link_to_an_older_release_is_not_a_round():
    issue = _issue(_ship(1, "0.28.0"), _post("tester", 2),
                   _ship(3, "0.29.0"), _ship(4, "0.28.0"))
    ships = [e.tag for e in rounds.issue_events(issue, "owner")
             if e.kind == "ship"]
    assert ships == ["0.28.0", "0.29.0"]


def test_a_maintainer_opened_issue_can_announce_the_first_build():
    issue = _issue(author="owner",
                   body="Built, in https://x/releases/tag/v0.31.0")
    assert [e.kind for e in rounds.issue_events(issue, "owner")] == ["ship"]


def test_versions_compare_as_numbers_not_text():
    issue = _issue(_ship(1, "0.9.0"), _ship(2, "0.10.0"))
    ships = [e.tag for e in rounds.issue_events(issue, "owner")
             if e.kind == "ship"]
    assert ships == ["0.9.0", "0.10.0"]


# -- counting -----------------------------------------------------------------

def test_a_night_of_commits_answering_one_report_is_one_round():
    reports = [T0, T0 + timedelta(days=1)]
    night = [T0 + timedelta(hours=h) for h in (1, 2, 3, 4, 5)]
    assert rounds.grouped_rounds(night, reports) == 1
    assert rounds.grouped_rounds(
        night + [T0 + timedelta(days=1, hours=1)], reports) == 2


def _analyze(issue, now_hours=100, changed=None, commits=()):
    return rounds.analyze(
        "att", "new", (1,), {1: issue}, list(commits), "owner", NAMES,
        T0 + timedelta(hours=now_hours), changed=changed)


def test_a_release_that_did_not_touch_the_provider_is_not_a_round():
    """AT&T's issue linked 0.27.0, which carried other providers' fixes
    and nothing for AT&T, and the count came out nine where the record
    said eight."""
    issue = _issue(_ship(1, "0.26.1"), _post("tester", 2),
                   _ship(3, "0.27.0"), _ship(4, "0.27.1"),
                   _post("tester", 5, "Pilot pulled 5 docs"))
    row = _analyze(issue, changed=lambda app, a, b: b != "0.27.0")
    assert row.shipped == 2
    assert row.shipped_to_working == 2
    assert row.status == "working"


def test_rounds_to_working_stop_at_the_first_working_pilot():
    issue = _issue(_ship(1, "0.1.0"), _post("tester", 2),
                   _ship(3, "0.2.0"),
                   _post("tester", 4, "Success!"),
                   _ship(5, "0.3.0"))
    row = _analyze(issue)
    assert (row.shipped, row.shipped_to_working) == (3, 2)


def test_a_build_nobody_has_answered_is_untested_and_counts_from_the_first_ship():
    issue = _issue(_ship(1, "0.1.0"), _ship(30, "0.2.0"))
    row = _analyze(issue, now_hours=49)
    assert row.status == "untested"
    assert row.owed == "tester"
    assert row.waiting_days == 2.0


def test_a_report_nobody_has_answered_is_owed_by_the_maintainer():
    """The tool once said only how long testers had been waiting. Most
    open issues end on a tester's report, so the loop was stalled on the
    maintainer and the output hid it."""
    issue = _issue(_ship(1, "0.1.0"), _post("tester", 2, "found 0"))
    row = _analyze(issue, now_hours=26)
    assert (row.status, row.owed, row.waiting_days) == (
        "in progress", "maintainer", 1.0)


def test_the_record_can_be_read_as_it_stood_on_an_earlier_day():
    issue = _issue(_ship(1, "0.1.0"), _post("tester", 2),
                   _ship(3, "0.2.0"), _post("tester", 50, "Success!"))
    early = _analyze(issue, now_hours=10)
    late = _analyze(issue, now_hours=100)
    assert (early.shipped, early.status) == (2, "in progress")
    assert late.status == "working"


def test_a_repair_counts_its_days_from_the_issue_not_the_first_commit():
    commit = rounds.Commit(T0 - timedelta(days=300), "Add PG&E",
                           ["apps/att/att_site.py"])
    issue = _issue(_ship(1, "0.1.0"), _post("tester", 48, "Success!"))
    row = rounds.analyze("att", "repair", (1,), {1: issue}, [commit],
                         "owner", NAMES, T0 + timedelta(days=5))
    assert row.days_to_working == 2.0


def test_a_provider_issue_missing_from_the_table_is_reported():
    issues = {999: {"title": "[Provider request] Somebody New"},
              26: {"title": "[Provider request] AT&T Mobility"},
              14: {"title": "[Provider request] PG&E"},
              50: {"title": "[Feature Request] Custom File Naming"}}
    assert rounds.unmapped_issues(issues) == [
        (999, "[Provider request] Somebody New")]
