"""Which of two documents sharing a title and a date this one is.

Five apps carry no account in a document's key. Two documents that share a
title and a date are told apart by counting them, and the counting followed
the order the provider's API happened to answer in.

Two Fidelity accounts both have a Quarterly Statement for the same quarter,
and so do two NetBenefits plans. If that answer ever came back the other way
around, the statement already downloaded took the other one's number, so it
was skipped as already done while the other was fetched again beside it, and
the archive was then wrong about which belonged to which account.

Nothing would look broken. The count of files is right, the dates are right,
and the only sign is a statement filed under the wrong account.

A number already given now stays with the document it was given to, looked
up by what the document is rather than where it turned up. An archive that
already exists keeps every key it has, which is what makes this safe to ship
to somebody mid-way through one.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

from paperpull_core.keys import stable_occurrences  # noqa: E402

COUNTERS = ("affirm", "fairfaxwater", "fidelity", "netbenefits", "tsp")
APPS = [d for d in sorted((REPO / "apps").iterdir())
        if d.is_dir() and d.name in COUNTERS]


def rows(*accounts, title="Quarterly Statement", date="2026-03-31"):
    return [{"title": title, "date": date, "account": a} for a in accounts]


def archive(*pairs, title="Quarterly Statement", date="2026-03-31"):
    return {"k%d" % i: {"title": title, "date": date,
                        "account": account, "occurrence": occurrence}
            for i, (account, occurrence) in enumerate(pairs)}


# -- the rule itself -----------------------------------------------------------

def test_two_accounts_on_one_date_get_different_numbers():
    assert stable_occurrences(rows("Brokerage", "Roth IRA")) == [0, 1]


def test_the_answer_coming_back_the_other_way_changes_nothing():
    """The whole point. These are the same two documents either way."""
    known = archive(("Brokerage", 0), ("Roth IRA", 1))
    assert stable_occurrences(rows("Brokerage", "Roth IRA"), known) == [0, 1]
    assert stable_occurrences(rows("Roth IRA", "Brokerage"), known) == [1, 0]


def test_a_new_account_takes_a_number_nobody_is_using():
    known = archive(("Brokerage", 0), ("Roth IRA", 1))
    got = stable_occurrences(rows("Roth IRA", "Brokerage", "529"), known)
    assert got[:2] == [1, 0]
    assert got[2] == 2


def test_an_account_that_went_away_does_not_hold_its_number_against_a_new_one():
    known = archive(("Brokerage", 0), ("Roth IRA", 1))
    assert stable_occurrences(rows("Roth IRA", "529"), known) == [1, 0]


def test_tidying_is_done_on_both_sides():
    """The stored record has been through the app's cleanup and the raw row
    has not, so a difference in spacing must not look like a new document."""
    known = archive(("Brokerage", 0), ("Roth IRA", 1))
    untidy = [{"title": "Quarterly  Statement ", "date": "2026-03-31",
               "account": " Roth IRA"},
              {"title": "Quarterly Statement", "date": "2026-03-31",
               "account": "Brokerage "}]
    assert stable_occurrences(untidy, known) == [1, 0]


def test_documents_that_share_nothing_are_all_the_first_of_their_kind():
    mixed = [{"title": "Quarterly Statement", "date": "2026-03-31", "account": "A"},
             {"title": "Trade Confirmation", "date": "2026-03-31", "account": "A"},
             {"title": "Quarterly Statement", "date": "2026-06-30", "account": "A"}]
    assert stable_occurrences(mixed) == [0, 0, 0]


def test_nothing_at_all_is_not_an_error():
    assert stable_occurrences([]) == []
    assert stable_occurrences(rows("A"), {}) == [0]
    assert stable_occurrences(rows("A"), {"k": "not a record"}) == [0]


# -- and that the apps use it --------------------------------------------------

@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_no_longer_numbers_by_the_order_it_was_given(app):
    """The old loop counted as it walked. A new one written that way is the
    way this comes back, and it reads perfectly reasonably."""
    src = (app / ("%s_docs.py" % app.name)).read_text(encoding="utf-8")
    assert "stable_occurrences" in src, \
        "%s numbers documents by the order the provider answered in" % app.name
    assert "seen[pair] = occ + 1" not in src


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_still_tells_two_documents_of_one_date_apart(app):
    """Whatever the numbering, the keys have to differ, or one of the two is
    dropped as a duplicate of the other."""
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        mod = importlib.import_module("%s_docs" % app.name)
    finally:
        sys.path.pop(0)
    first, second = stable_occurrences(rows("Brokerage", "Roth IRA"))
    a = mod.Document(category="Statement", date="2026-03-31",
                     title="Quarterly Statement", account="Brokerage",
                     occurrence=first)
    b = mod.Document(category="Statement", date="2026-03-31",
                     title="Quarterly Statement", account="Roth IRA",
                     occurrence=second)
    assert a.key != b.key, app.name
