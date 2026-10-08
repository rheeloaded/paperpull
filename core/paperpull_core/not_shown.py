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

from .models import State

# Word for word what each receipt app noted with No Receipt Available, up to
# 0.44.0, when the receipt page did not show the receipt.
OLD_NOTES = frozenset({
    "No printable order summary available",     # Amazon
    "Details page did not fill in",             # Best Buy, Home Depot, Lowe's
    "Costco could not load this receipt",       # Costco
    "Kroger could not load this receipt",       # Kroger
    "Receipt page did not render",              # Costco, Kroger
    "Order-details receipt did not render",     # eBay, Gap
    "Receipt page did not show a receipt",      # GitHub, Meijer
})

TRIED_AGAIN = "tried again next run"

# On how many separate days a receipt's page may show nothing before it is
# set aside, and where the record keeps those days.
DAYS = 3
DAYS_KEY = "not_shown_days"

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


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
    return [d for d in (rec.get(DAYS_KEY) or []) if isinstance(d, str) and d]


# What a receipt app records the moment it has saved a file for a purchase,
# a receipt, one invoice of an order, or a copy put aside for review.
SAVED_STATES = frozenset({State.PDF_SAVED.value, State.PDF_VERIFIED.value})


def let_go_on_save(app, purchase, state, rec: dict) -> None:
    """Every receipt app's _record_state hands this the record it is about
    to write. When the state says a file was just saved for the purchase,
    its page showed something, so the days it showed nothing count no
    longer and the record lets them go. A saved receipt is never asked for
    again anyway, but a copy put aside for review, or a Target order with
    one of its invoices saved and another missing, has no downloaded_ok,
    and one more day of an empty page used to set it aside."""
    if getattr(state, "value", state) not in SAVED_STATES:
        return
    if _days(app.progress.get(purchase.key) or {}):
        # The store merges a record into the one it has, so the days are
        # written empty rather than left out.
        rec[DAYS_KEY] = []


def written_down(app, purchase) -> bool:
    """Whether the order history already has rows for this purchase. One
    that cannot be read is taken as not, and writing to it says why."""
    try:
        rows = app.order_csv.read_all()
    except Exception:
        return False
    return any(r.get("Order or Receipt Number") == purchase.order_number
               and r.get("Purchase Type", purchase.purchase_type) == purchase.purchase_type
               for r in rows)


def tried_again(app, purchase, why: str) -> bool:
    """Record that this purchase's receipt page did not show its receipt.
    Always False, nothing was saved. `why` is a sentence without its full
    stop."""
    rec = app.progress.get(purchase.key) or {}
    if rec.get("downloaded_ok"):
        # Download again, for a receipt saved before. The copy saved then
        # stands, and no plain run asks for it again.
        app._record_state(purchase, State.FAILED,
                          notes="%s, the receipt saved before is kept" % why)
        app.stats["failed"] += 1
        print("  %s. The receipt saved before is kept." % why)
        return False
    days = _days(rec)
    if _this_day(app) not in days:
        days.append(_this_day(app))
    if len(days) < DAYS:
        app._record_state(purchase, State.FAILED, notes="%s, %s" % (why, TRIED_AGAIN),
                          extra={DAYS_KEY: days})
        app.stats["failed"] += 1
        print("  %s, on %d of %d separate days. It is tried again next run."
              % (why, len(days), DAYS))
        return False
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
    return False


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
