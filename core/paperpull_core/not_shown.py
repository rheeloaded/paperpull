"""A receipt page that did not show its receipt.

A receipt app opens a purchase's receipt page and checks that the receipt
is on it before anything is printed. When it is not, the page failed to
load or never filled in, or the provider said it had a problem loading the
receipt and to try again (Kroger, #70). Such a page says nothing about
whether the purchase has a receipt. Up to 0.44.0 nine receipt apps
recorded it as No Receipt Available, which is final, printed that it was
marked for manual review and wrote the purchase into both CSVs. No later
run asked for it again, so a receipt a passing fault kept off the page was
never saved, and the next run said it was already completed.

Now each of them records it with tried_again(), as a failure the next run
asks for again, the way Uber records a receipt that never came and Meijer a
row that gave none. It writes no CSV rows, since the CSVs only ever take
rows on the end and the run that saves the receipt writes the purchase
down.

asked_again() is for the records those versions left. A No Receipt
Available record whose note is one of the words they wrote for a page that
did not show is not done, so the next run asks for its receipt. The words
are kept here exactly as they were written and never change, since records
on disk carry them. A purchase recorded No Receipt Available for what the
provider showed, a Target order with no receipt control or a GitHub
payment whose row has no receipt link, keeps its record.
"""
from __future__ import annotations

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


def tried_again(app, purchase, why: str) -> bool:
    """Record that this purchase's receipt page did not show its receipt,
    as a failure the next run asks for again. Always False, nothing was
    saved. `why` is a sentence without its full stop."""
    app._record_state(purchase, State.FAILED, notes="%s, %s" % (why, TRIED_AGAIN))
    app.stats["failed"] += 1
    print("  %s. It is tried again next run." % why)
    return False


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
