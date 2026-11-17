"""A receipt page that did not show its receipt.

A receipt app opens a purchase's receipt page and checks that the receipt
is on it before anything is printed. When it is not, the page failed to
load or never filled in, or the provider said it had a problem loading the
receipt and to try again (Kroger, #70). Such a page says nothing about
whether the purchase has a receipt. Up to 0.44.0 nine receipt apps
recorded it as No Receipt Available, which is final, printed that it was
marked for manual review and wrote the purchase into both CSVs. No later
run asked for it again, so a receipt a passing fault kept off the page was
never saved, and the next run said it was already completed. Target did
the same for an order whose page showed neither a receipt nor an invoice.

Now each of them records it with tried_again(), as a failure the next run
asks for again, the way Uber records a receipt that never came and Meijer a
row that gave none. It writes no CSV rows then, since the CSVs only ever
take rows on the end and the run that saves the receipt writes the
purchase down. A receipt whose page has not shown it on DAYS separate days
is set aside as No Receipt Available, written into the CSVs once and
counted for review, as Apple sets aside a receipt it refused, so a page
that never shows costs a few days of runs rather than every run. The days
are counted, not the runs, since Pilot, Run All and Resume one after
another, or a server running every hour through a provider's outage, are
many runs on one bad day, and PaperPull Server offers no Download again to
ask for a receipt once more after it is set aside.

It is set aside only on a run that saved a receipt of its kind, online or
in-store, before it, with no receipt page of that kind showing nothing in
between (#225). Kroger once stopped showing the receipt for every purchase
a tester had, and the third day of runs set every one of them aside, on
PaperPull Server. A provider whose receipt pages show nothing for every
purchase has broken pages, which says nothing about whether the purchases
have receipts. Without such a save the purchase is tried again next run
and keeps its most recent DAYS days, so a provider that shows no receipt at
all costs time, never the purchases. The cost is a receipt that is truly
missing and has no receipt of its kind saved before it in a run, the newest
purchase most often. It is asked for on every such run and set aside only
on a run that saved a newer one first. A purchase set aside already stays
set aside, those an earlier version set aside included. Whether a run
saved one is kept on the app object, so it is that run's alone.

A run stops after STOP_AFTER receipt pages in a row show nothing that
had not shown nothing before (threads of 2026-11-16, item 3). During an
outage, a rate limit or a route change every purchase whose page shows
nothing was otherwise opened on every run, with no end, and eBay's details
pages have a daily cap and Best Buy's Akamai protection blocks after too
many requests. What tells an outage from receipts that are truly missing
is a page that never showed nothing before and now does, so only those
count, a page whose record holds no day before the run's own, and a
Download again of a receipt saved before, whose page showed it once. A
receipt that is truly missing shows nothing on every run, so from its
second day it is known and cannot stop anything, and five of them at the
head of the list hold a run for one day at most. Any save sets the count
back to nothing. Every other outcome leaves it as it is. The count is
kept on the app object, so it is that run's alone. The stop records the
purchase first, as it always was, then saves progress, says why, writes a
failure file of its own and leaves on NothingShown, a SystemExit with code
0 that the core reports as a stop of its own kind (run_reporting). A run
whose list was not read whole leaves the way such a run leaves, on a
ListNotRead, so the panel offers a run that reads the list first.

asked_again() is for the records the older versions left. A No Receipt
Available record whose note is one of the words they wrote for a page that
did not show is not done, so the next run asks for its receipt. The words
are kept here exactly as they were written and never change, since records
on disk carry them. A purchase recorded No Receipt Available for what the
provider showed, a Target order with only an invoice or a GitHub payment
whose row has no receipt link, keeps its record.

The rows such a purchase was written down with, by an older version or
when it was set aside, stay in the CSVs once a later run saves it, beside
that run's rows. The CSVs are the person's own files, only ever added to,
and the All Purchases workbook leaves those rows out (export_purchases).
"""
from __future__ import annotations

import re
from datetime import date

from .characters import whole_characters
from .models import State
from .run_reporting import ListNotRead, under_panel

# Word for word what each receipt app noted with No Receipt Available, up to
# 0.44.0, when the receipt page did not show the receipt. Wealthfront noted
# the last with it, up to 0.61.0, when it found no safe download control for
# a row, which says no more about whether there is a document (#152).
OLD_NOTES = frozenset({
    "No printable order summary available",     # Amazon
    "Details page did not fill in",             # Best Buy, Home Depot, Lowe's
    "Costco could not load this receipt",       # Costco
    "Kroger could not load this receipt",       # Kroger
    "Receipt page did not render",              # Costco, Kroger
    "Order-details receipt did not render",     # eBay, Gap
    "Receipt page did not show a receipt",      # GitHub, Meijer
    "No safe download control found for this row",  # Wealthfront
})

TRIED_AGAIN = "tried again next run"

# On how many separate days a receipt's page may show nothing before it is
# set aside, and where the record keeps those days.
DAYS = 3
DAYS_KEY = "not_shown_days"

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_ONE_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _this_day(app) -> str:
    """The day the run started, the same for every purchase it takes, so
    every run of one day counts once."""
    key = getattr(app, "_not_shown_day", "")
    if not key:
        stats = getattr(app, "stats", None) or {}
        started = str(stats.get("started") or "")
        key = started[:10] if _DAY_RE.match(started) else date.today().isoformat()
        app._not_shown_day = key
    return key


def _days(rec) -> list:
    """The days a record keeps, from a list only. One string is no list of
    days, and was read one character at a time, as ten days."""
    days = rec.get(DAYS_KEY) if isinstance(rec, dict) else None
    if not isinstance(days, list):
        return []
    return [d for d in days if isinstance(d, str) and d]


def _a_day(text: str) -> bool:
    if not _ONE_DAY_RE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _days_so_far(app, rec) -> list:
    """The days that count for this run, each a real date no later than the
    run's own. Words that are no date count for nothing, and so does a day
    after the run's, from a clock set back or a record made on a computer
    ahead in time, which would otherwise bring a purchase closer to being
    set aside on a day that has not come."""
    today = _this_day(app)
    return [d for d in _days(rec) if _a_day(d) and d <= today]


def _holds_days(rec) -> bool:
    """Whether a record holds anything under DAYS_KEY at all, so a save lets
    it go whatever it is."""
    return isinstance(rec, dict) and bool(rec.get(DAYS_KEY))


# What a receipt app records the moment it has saved a file for a purchase,
# a receipt, one invoice of an order, or a copy put aside for review.
SAVED_STATES = frozenset({State.PDF_SAVED.value, State.PDF_VERIFIED.value})

# Where a run keeps, on its own app object, each kind of purchase
# (Purchase.purchase_type) it has saved a receipt of, and whether no receipt
# page of that kind has shown nothing since the last one it saved.
SAVED_KEY = "_not_shown_saved"


def _saved(app) -> dict:
    kinds = getattr(app, SAVED_KEY, None)
    if not isinstance(kinds, dict):
        kinds = {}
        setattr(app, SAVED_KEY, kinds)
    return kinds


# Where a run keeps the purchases that were set aside when it began and that
# it has since written another state over, short of a save.
SET_ASIDE_KEY = "_not_shown_set_aside"


def _set_aside_before(app) -> set:
    keys = getattr(app, SET_ASIDE_KEY, None)
    if not isinstance(keys, set):
        keys = set()
        setattr(app, SET_ASIDE_KEY, keys)
    return keys


# How many receipt pages in a row, new to showing nothing, stop a run. More
# than the three truly missing receipts in a row the follow-up names, with
# two to spare, and no more than the smallest default Pilot (5 purchases in
# Amazon, eBay, GitHub and Meijer), so a Pilot during an outage shows the
# stop rather than a page of failures.
STOP_AFTER = 5

# Where a run keeps its count, on its own app object, so two accounts in one
# process keep two.
STREAK_KEY = "_not_shown_streak"

# The stop's failure file. Its step and reason, and its facts, each a count.
STOP_STEP = "open the receipt"
STOP_REASON = "receipt pages showed nothing in a row"


class NothingShown(SystemExit):
    """The run stopping after STOP_AFTER receipt pages in a row, new to
    showing nothing, showed nothing. A SystemExit with code 0, so no app
    catches it on its way out (each loop catches Exception), and neither a
    pressing.Stop, which Best Buy's and Meijer's mains would take, nor a
    ListNotRead. run_reporting.stop_reason names it not_shown."""

    def __init__(self):
        super().__init__(0)


class NothingShownListUnread(ListNotRead):
    """The same stop in a run whose list was not read whole, which leaves the
    way such a run leaves (Changes item 3 of the test plan)."""


# What a Pilot catches to print its results before the stop goes on.
STOPS = (NothingShown, NothingShownListUnread)


def _streak(app) -> dict:
    kept = getattr(app, STREAK_KEY, None)
    if not isinstance(kept, dict):
        kept = {"in_a_row": 0, "known": 0, "saved": set()}
        setattr(app, STREAK_KEY, kept)
    return kept


def streak(app) -> int:
    """How many receipt pages in a row, new to showing nothing, this run has
    met since its last save."""
    return _streak(app)["in_a_row"]


def let_go_on_save(app, purchase, state, rec: dict) -> None:
    """Every receipt app's _record_state hands this the record it is about
    to write. When the state says a file was just saved for the purchase,
    the days its page showed nothing count no longer and the record lets
    them go. A saved receipt is never asked for again anyway, but a copy put
    aside for review, or a Target order with one of its invoices saved and
    another missing, has no downloaded_ok, and one more day of an empty page
    used to set it aside. It is a save that lets them go, not a page that
    showed. A page that showed and saved nothing new, a print that failed or
    a Target walk that found only invoices already on file, keeps them.

    Every save, of a record with days or without, also lets a purchase of
    its kind whose page shows nothing later in this run be set aside
    (tried_again). And a purchase set aside before, written over on a
    Download again with another state before its page is looked at (GitHub
    and Meijer note that its receipt was located), is remembered for this
    run, so a page that shows nothing again leaves it set aside.

    A purchase recorded as having no receipt for what the provider showed,
    a Target order with only an invoice or a GitHub payment with no receipt
    link, is final for its own reason, and its days go with it. tried_again
    writes its own days with the state, so only that write keeps them. Kept
    on such a record, they read as a purchase set aside for pages that
    showed nothing, since a purchase now keeps three days while it is tried
    again (review of #225)."""
    before = app.progress.get(purchase.key) or {}
    value = getattr(state, "value", state)
    if value not in SAVED_STATES:
        if set_aside(before):
            _set_aside_before(app).add(purchase.key)
        if value == State.NO_RECEIPT_AVAILABLE.value and DAYS_KEY not in rec and _holds_days(before):
            rec[DAYS_KEY] = []
        return
    _saved(app)[purchase.purchase_type] = True
    _set_aside_before(app).discard(purchase.key)
    # A save of either kind sets the run's count of empty pages back, and is
    # counted by purchase, not by file, for the stop's facts.
    kept = _streak(app)
    kept["in_a_row"] = 0
    kept["saved"].add(purchase.key)
    if _holds_days(before):
        # The store merges a record into the one it has, so the days are
        # written empty rather than left out.
        rec[DAYS_KEY] = []


def written_down(app, purchase) -> bool:
    """Whether the order history already has rows for this purchase. One
    that cannot be read is taken as not, and writing to it says why. The
    history holds half of a character as U+FFFD (characters.py), so the
    order number is asked for that way too."""
    try:
        rows = app.order_csv.read_all()
    except Exception:
        return False
    number = purchase.order_number
    if isinstance(number, str):
        number = whole_characters(number)
    return any(r.get("Order or Receipt Number") == number
               and r.get("Purchase Type", purchase.purchase_type) == purchase.purchase_type
               for r in rows)


def tried_again(app, purchase, why: str) -> bool:
    """Record that this purchase's receipt page did not show its receipt.
    Always False, nothing was saved. `why` is a sentence without its full
    stop.

    On its DAYS-th separate day it is set aside only when this run saved a
    receipt of its kind before it, with no page of that kind showing
    nothing in between, or when it was set aside before. This page showed
    nothing, so the next one of its kind waits for another save.

    Once the purchase is recorded, a page new to showing nothing counts
    toward the run's stop, and the STOP_AFTER-th in a row stops the run
    (_counted). Whether it is new is read from the record as it was before
    this page, since the record written here holds this run's day."""
    kinds = _saved(app)
    kind = purchase.purchase_type
    after_a_save = kinds.get(kind)          # None when this run saved none
    if kind in kinds:
        kinds[kind] = False
    rec = app.progress.get(purchase.key) or {}
    if not isinstance(rec, dict):
        rec = {}
    if rec.get("downloaded_ok"):
        # Download again, for a receipt saved before. The copy saved then
        # stands, and no plain run asks for it again. Its page showed the
        # receipt once, so it counts.
        app._record_state(purchase, State.FAILED,
                          notes="%s, the receipt saved before is kept" % why)
        app.stats["failed"] += 1
        print("  %s. The receipt saved before is kept." % why)
        return _counted(app, True)
    new = not any(d < _this_day(app) for d in _days_so_far(app, rec))
    days = _days_so_far(app, rec)
    if _this_day(app) not in days:
        days.append(_this_day(app))
    seen = len(days)
    # The most recent DAYS, never a list that grows by a day on every run.
    days = days[-DAYS:]
    if len(days) < DAYS:
        app._record_state(purchase, State.FAILED, notes="%s, %s" % (why, TRIED_AGAIN),
                          extra={DAYS_KEY: days})
        app.stats["failed"] += 1
        print("  %s, on %d of %d separate days. It is tried again next run."
              % (why, len(days), DAYS))
        return _counted(app, new)
    if not (after_a_save or set_aside(rec) or purchase.key in _set_aside_before(app)):
        app._record_state(purchase, State.FAILED, notes="%s, %s" % (why, TRIED_AGAIN),
                          extra={DAYS_KEY: days})
        app.stats["failed"] += 1
        lower = kind.lower()
        if after_a_save is None:
            because = "no %s receipt was saved before it in this run" % lower
        else:
            because = ("an %s receipt page showed nothing after the last %s receipt this run "
                       "saved" % (lower, lower))
        print("  %s, on %s separate days. It is not set aside, because %s, and it is tried "
              "again next run." % (why, seen if seen <= DAYS else "more than %d" % DAYS,
                                   because))
        return _counted(app, new)
    said = "%s on %d separate days, so it is not asked for again" % (why, len(days))
    # Written down once. An older version that recorded the purchase as
    # having no receipt wrote it down then, and a Download again after it
    # was set aside finds it written. The rows go first, so a history that
    # cannot be written to, open in Excel, leaves the purchase to the next
    # run rather than set aside with nothing written.
    if not written_down(app, purchase):
        app._write_csv_rows(purchase, receipt_status="No printable receipt available",
                            processing_status=State.NEEDS_MANUAL_REVIEW.value,
                            notes_extra="The receipt did not show on %d separate days" % DAYS)
    app._record_state(purchase, State.NO_RECEIPT_AVAILABLE, notes=said, extra={DAYS_KEY: days})
    app.stats["no_receipt"] += 1
    app.stats["manual_review"] += 1
    print("  %s, on %d of %d separate days. It is set aside for review and not asked "
          "for again." % (why, min(len(days), DAYS), DAYS))
    return _counted(app, new)


def _counted(app, new: bool) -> bool:
    """Count a page that showed nothing, once its purchase is recorded, and
    stop the run at the STOP_AFTER-th in a row new to showing nothing. A
    page that showed nothing on an earlier day neither counts nor sets the
    count back. False, nothing was saved."""
    kept = _streak(app)
    if not new:
        kept["known"] += 1
        return False
    kept["in_a_row"] += 1
    if kept["in_a_row"] >= STOP_AFTER:
        _stop(app)
    return False


def _provider() -> str:
    try:
        from .storage import spec
        return spec().provider or "The provider"
    except Exception:
        return "The provider"


def _list_unread(app) -> bool:
    try:
        from . import listing
        return listing.last(app) == listing.STOPPED
    except Exception:
        return False


def _stop(app) -> None:
    """Stop the run after STOP_AFTER pages in a row, new to showing nothing,
    as pressing.stop_run stops one at a press. Progress is saved with a
    backup, the reason is said in our own words, and a failure file of the
    stop's own is written, the newest in the folder, with counts only. A
    save or a file that cannot be written does not keep the run going, and
    nothing here catches a KeyboardInterrupt."""
    kept = _streak(app)
    stats = getattr(app, "stats", None)
    stats = stats if isinstance(stats, dict) else {}
    try:
        app.progress.save(backup=True)
    except Exception:
        pass
    again = "Press Continue" if under_panel() else "Run Resume"
    print()
    print("!! The last %d receipt pages this run opened showed nothing, and none of them"
          % STOP_AFTER)
    print("   had shown nothing before. %s may not be showing receipts right now, so"
          % _provider())
    print("   the run stops here rather than open every purchase. Nothing saved is lost.")
    print("   %s in a few hours or tomorrow to carry on from here." % again)
    facts = {
        "empty_pages_in_a_row": int(kept["in_a_row"]),
        "purchases_saved": len(kept["saved"]),
        "pages_that_showed_nothing_before": int(kept["known"]),
        "skipped_as_done": int(stats.get("skipped_completed", 0) or 0),
    }
    stats.pop("failure_files", None)
    try:
        app.write_failure(STOP_STEP, STOP_REASON, extra=facts)
    except Exception:
        pass
    if _list_unread(app):
        from . import listing
        whole_run = listing.say_unread(app).whole_run
        raise NothingShownListUnread(whole_run)
    raise NothingShown()


def set_aside(rec) -> bool:
    """True for a record tried_again() set aside, its receipt page having
    shown nothing on DAYS separate days. Final, as No Receipt Available is,
    in an app that does not hold that state final otherwise (Meijer)."""
    if not isinstance(rec, dict) or rec.get("state") != State.NO_RECEIPT_AVAILABLE.value:
        return False
    return len(_days(rec)) >= DAYS


def skipped(rec, otherwise: str) -> str:
    """What a run says as it skips this purchase. A purchase set aside was
    never saved, and a tester was told such a purchase was "Already
    completed and PDF verified" with no file anywhere (#70)."""
    if set_aside(rec) and not rec.get("downloaded_ok"):
        return ("  Its receipt did not show on %d separate days, so it is set aside "
                "for review and skipped." % DAYS)
    return otherwise


def asked_again(rec) -> bool:
    """True for a record an older version made final when the receipt page
    did not show the receipt, so its receipt is asked for again."""
    if not isinstance(rec, dict) or rec.get("state") != State.NO_RECEIPT_AVAILABLE.value:
        return False
    if rec.get("downloaded_ok"):
        return False
    # Each step of a run adds its note after the ones before it, so the last
    # one is the note the state was written with.
    last = str(rec.get("notes") or "").rsplit("; ", 1)[-1].strip()
    return last in OLD_NOTES
