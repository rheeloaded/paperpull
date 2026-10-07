"""Whether the last run that read a provider's list read all of it.

Resume reads no list of its own. It carries on from discovery.json, which
holds what the runs before it listed, and a run that stopped while it was
listing, at a page it could not read, a sign-in or an account the app does
not support, left that list short or empty. Resume then found nothing left
to do, said everything in scope was complete, and the panel reported a
clean run, so a run that never listed the documents read as finished.
PayPal was the first app to be fixed, and every other document app had the
same Resume, as did eight of the fourteen receipt apps.

So each listing notes in last-listing.json, in the output folder, whether
it was read to its end. started() notes it as stopped before anything is
asked of the browser, and only read_whole(), once the app has the whole
list, notes it as complete. Any other way out of a listing, an exception, a
stop for a sign-in or a page that would not open, leaves it noted as
stopped, so an app has to say when a list is whole and never has to
remember to say that it was not.

resume() is Resume itself, for an app whose Resume works from that list.
With nothing known and no listing read whole it says so and stops at once.
After a listing that stopped it says so first, carries on with what is
known, and then stops. Both leave on SystemExit, which the panel reports
as a run that stopped (run_reporting.stopped_early). A listing read whole,
or an install from before this existed, resumes as it always did.
before_resume() and after_resume() are its two halves, for a Resume that
does more than carry on with the list.

A receipt app's Resume reads the purchase list again after a listing that
did not end whole, before it takes anything (read_again_first), as six of
them did by a mark of their own since Target's review of 0.41.0. The panel
says to press Resume after any run that stopped, and a purchase list is a
few pages where the receipts are a page each, so that Resume finishes the
job. When the list does not come this time either, the run stops with it.
"""
from __future__ import annotations

import json
import logging
import textwrap

from .storage import atomic_write_json, now_iso, spec

COMPLETE = "complete"
STOPPED = "stopped"

# The mark six receipt apps kept beside discovery.json while a Discover ran
# and after one that did not end whole, before this note took its place. An
# install whose listing stopped under an older version still has it, and
# its first Resume reads the list again as that version's would have.
OLD_MARK = ".discovery-unfinished"

log = logging.getLogger(__name__)


def _note(app, whole: bool) -> bool:
    # Never the reason a listing fails, whatever goes wrong here, as with the
    # journal. A note that cannot be written leaves the last one as it was,
    # which is no worse than before this existed.
    try:
        atomic_write_json(app.paths.last_listing, {"complete": bool(whole), "at": now_iso()})
    except Exception as e:
        log.info("could not note how the list was read: %s", e)
        return False
    return True


def _old_mark(app):
    return app.paths.last_listing.with_name(OLD_MARK)


def started(app) -> None:
    """A listing begins. Until read_whole() it is a listing that stopped."""
    if _note(app, False):
        # The note says from here on what the old mark said, so the mark goes.
        try:
            _old_mark(app).unlink(missing_ok=True)
        except OSError as e:
            log.info("could not take away the old mark of a listing: %s", e)


def read_whole(app) -> None:
    """The app has the whole list, everything the provider listed."""
    _note(app, True)


def last(app) -> str:
    """COMPLETE or STOPPED for the last listing, or "" when none was noted,
    as in an install from before this existed. With no note, the old mark a
    receipt app left is a listing that stopped."""
    try:
        got = json.loads(app.paths.last_listing.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = None
    if isinstance(got, dict) and isinstance(got.get("complete"), bool):
        return COMPLETE if got["complete"] else STOPPED
    try:
        if _old_mark(app).exists():
            return STOPPED
    except OSError:
        pass
    return ""


def _say(text: str) -> None:
    print(textwrap.fill(text, width=72), flush=True)


def _whose(provider: str) -> str:
    """The provider's name as an owner, Lowe's for Lowe's, not Lowe's's."""
    return provider if provider.endswith("'s") else provider + "'s"


def _nothing_listed(noun: str) -> None:
    provider = spec().provider
    _say("Nothing to resume. No %s %s have been listed yet, because no run "
         "has read %s list to its end. Run Pilot or Run All, which read "
         "the list first." % (provider, noun, _whose(provider)))
    raise SystemExit(0)


def before_resume(app, noun: str = "documents") -> bool:
    """What Resume says before it starts.

    With no document known and no listing read whole there is nothing to
    carry on from, so it says so and stops at once, before the browser is
    asked for anything. After a listing that stopped it says that, before
    anything else runs, and answers True. Otherwise it answers False."""
    provider = spec().provider
    said = last(app)
    if not app.discovery.data and said != COMPLETE:
        _nothing_listed(noun)
    if said == STOPPED:
        _say("The last run stopped before it read %s whole list, so there may "
             "be %s this app has not seen." % (_whose(provider), noun))
        return True
    return False


def after_resume(app) -> None:
    """The end of a Resume. When the last listing, read again here since a
    Resume may list again, still stopped before its end, the run stops as
    one that did not finish."""
    if last(app) == STOPPED:
        _say("This run stops here, because %s list was not read to its end. "
             "Run Pilot or Run All to read it again." % _whose(spec().provider))
        raise SystemExit(0)


def resume(app, remaining, process, noun: str = "documents") -> None:
    """Resume, carrying on with `remaining`, the documents in scope that the
    last lists hold and that are not done, by handing them to `process`."""
    cut_short = before_resume(app, noun)
    if not remaining and not cut_short:
        print("Nothing to resume - everything in scope is complete.")
        return
    if remaining:
        print(f"Resuming: {len(remaining)} document(s) remaining.")
        process(remaining)
    else:
        print(f"Nothing left to resume from the {noun} listed so far.")
    after_resume(app)


def read_again_first(app, noun: str = "purchases") -> bool:
    """Whether a receipt app's Resume reads the list before it takes
    anything, answered before the browser is asked for anything.

    After a listing that did not end whole it says so and answers True, and
    the caller reads the list, which stops the run when it stops. With
    nothing known and no listing ever begun, a new install, it says nothing
    has been listed and stops at once, since a whole history read that
    nobody asked for is Run All's. Otherwise, after a listing read whole or
    on an install from before this existed, it answers False and Resume
    carries on from what is known, as it always did."""
    said = last(app)
    if said == STOPPED:
        _say("The last run did not read %s whole list, so Resume reads it "
             "before anything else." % _whose(spec().provider))
        return True
    if not app.discovery.data and said != COMPLETE:
        _nothing_listed(noun)
    return False
