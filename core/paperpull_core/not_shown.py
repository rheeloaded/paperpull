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
purchase down. A receipt whose page has not shown it on RUNS separate runs
is set aside as No Receipt Available, written into the CSVs once and
counted for review, as Apple sets aside a receipt it refused, so a page
that never shows costs a few runs rather than every run. Download again
still asks for it.

asked_again() is for the records the older versions left. A No Receipt
Available record whose note is one of the words they wrote for a page that
did not show is not done, so the next run asks for its receipt. The words
are kept here exactly as they were written and never change, since records
on disk carry them. A purchase recorded No Receipt Available for what the
provider showed, a Target order with only an invoice or a GitHub payment
whose row has no receipt link, keeps its record.
"""
from __future__ import annotations

import uuid

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

# How many separate runs ask for a receipt whose page did not show it before
# it is set aside, and where the record keeps those runs.
RUNS = 3
RUNS_KEY = "not_shown_runs"


def _this_run(app) -> str:
    """The run, the same for every purchase it takes, so a purchase asked
    for twice in one run counts once."""
    key = getattr(app, "_not_shown_run", "")
    if not key:
        stats = getattr(app, "stats", None) or {}
        key = str(stats.get("started") or "") or uuid.uuid4().hex
        app._not_shown_run = key
    return key


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
    runs = [r for r in (rec.get(RUNS_KEY) or []) if isinstance(r, str) and r]
    if _this_run(app) not in runs:
        runs.append(_this_run(app))
    if len(runs) < RUNS:
        app._record_state(purchase, State.FAILED, notes="%s, %s" % (why, TRIED_AGAIN),
                          extra={RUNS_KEY: runs})
        app.stats["failed"] += 1
        print("  %s, on %d of %d separate runs. It is tried again next run."
              % (why, len(runs), RUNS))
        return False
    said = "%s on %d separate runs, so it is not asked for again" % (why, len(runs))
    # Written down once. An older version that recorded the purchase as
    # having no receipt wrote it down then, and a Download again after it
    # was set aside finds it written. The rows go first, so a history that
    # cannot be written to, open in Excel, leaves the purchase to the next
    # run rather than set aside with nothing written.
    if not written_down(app, purchase):
        app._write_csv_rows(purchase, receipt_status="No printable receipt available",
                            processing_status=State.NEEDS_MANUAL_REVIEW.value,
                            notes_extra="The receipt did not show on %d separate runs" % RUNS)
    app._record_state(purchase, State.NO_RECEIPT_AVAILABLE, notes=said, extra={RUNS_KEY: runs})
    app.stats["no_receipt"] += 1
    app.stats["manual_review"] += 1
    print("  %s, on %d of %d separate runs. It is not asked for again, and Download "
          "again still asks for it." % (why, min(len(runs), RUNS), RUNS))
    return False


def set_aside(rec) -> bool:
    """True for a record tried_again() set aside, its receipt page having
    shown nothing on RUNS separate runs. Final, as No Receipt Available is,
    in an app that does not hold that state final otherwise (Meijer)."""
    if not isinstance(rec, dict) or rec.get("state") != State.NO_RECEIPT_AVAILABLE.value:
        return False
    runs = [r for r in (rec.get(RUNS_KEY) or []) if isinstance(r, str) and r]
    return len(runs) >= RUNS


def skipped(rec, otherwise: str) -> str:
    """What a run says as it skips this purchase. A purchase set aside was
    never saved, and a tester was told such a purchase was "Already
    completed and PDF verified" with no file anywhere (#70)."""
    if set_aside(rec) and not rec.get("downloaded_ok"):
        return ("  Its receipt did not show on %d separate runs, so it is skipped. "
                "Download again asks for it." % RUNS)
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
