"""Whether the last run that read a provider's list read all of it.

Resume reads no list of its own. It carries on from discovery.json, which
holds what the runs before it listed, and a run that stopped while it was
listing, at a page it could not read, a sign-in or an account the app does
not support, left that list short or empty. Resume then found nothing left
to do, said everything in scope was complete, and the panel reported a
clean run, so a run that never listed the documents read as finished.
PayPal was the first app to be fixed, and every other document app had the
same Resume.

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
"""
from __future__ import annotations

import json
import logging
import textwrap

from .storage import atomic_write_json, now_iso, spec

COMPLETE = "complete"
STOPPED = "stopped"

log = logging.getLogger(__name__)


def _note(app, whole: bool) -> None:
    # Never the reason a listing fails, whatever goes wrong here, as with the
    # journal. A note that cannot be written leaves the last one as it was,
    # which is no worse than before this existed.
    try:
        atomic_write_json(app.paths.last_listing, {"complete": bool(whole), "at": now_iso()})
    except Exception as e:
        log.info("could not note how the list was read: %s", e)


def started(app) -> None:
    """A listing begins. Until read_whole() it is a listing that stopped."""
    _note(app, False)


def read_whole(app) -> None:
    """The app has the whole list, everything the provider listed."""
    _note(app, True)


def last(app) -> str:
    """COMPLETE or STOPPED for the last listing, or "" when none was noted,
    as in an install from before this existed."""
    try:
        got = json.loads(app.paths.last_listing.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(got, dict) or not isinstance(got.get("complete"), bool):
        return ""
    return COMPLETE if got["complete"] else STOPPED


def _say(text: str) -> None:
    print(textwrap.fill(text, width=72), flush=True)


def before_resume(app, noun: str = "documents") -> bool:
    """What Resume says before it starts.

    With no document known and no listing read whole there is nothing to
    carry on from, so it says so and stops at once, before the browser is
    asked for anything. After a listing that stopped it says that, before
    anything else runs, and answers True. Otherwise it answers False."""
    provider = spec().provider
    said = last(app)
    if not app.discovery.data and said != COMPLETE:
        _say("Nothing to resume. No %s %s have been listed yet, because no run "
             "has read %s's list to its end. Run Pilot or Run All, which read "
             "the list first." % (provider, noun, provider))
        raise SystemExit(0)
    if said == STOPPED:
        _say("The last run stopped before it read %s's whole list, so there may "
             "be %s this app has not seen." % (provider, noun))
        return True
    return False


def after_resume(app) -> None:
    """The end of a Resume. When the last listing, read again here since a
    Resume may list again, still stopped before its end, the run stops as
    one that did not finish."""
    if last(app) == STOPPED:
        _say("This run stops here, because %s's list was not read to its end. "
             "Run Pilot or Run All to read it again." % spec().provider)
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
