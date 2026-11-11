"""Counts-only completion results for the local control panel."""
import json
import os
import re
import sys

PREFIX = "PAPERPULL_RUN_RESULT "

# The mark the control panel gives a run it starts, and takes a result line
# from that run only when the line carries it (gui/run_result.py). A run
# prints names it read from the disk and text a provider's page gave it,
# and on Linux and macOS a file name may hold a line break, so a name could
# start a line of its own that reads like a result. The mark is new for
# each run and nothing but the line below writes it, so such a line cannot
# carry it. A run started from a terminal has none and prints the line
# unmarked, as before, for nobody to read.
MARK_ENV = "PAPERPULL_RUN_MARK"
_MARK = re.compile(r"[0-9a-f]{32}")

# How an app ends when the thing it was asked for did not happen, so the
# panel never says a window opened that did not, or a recording was saved
# that holds nothing. Each is said in words first, by the core, and the
# code only tells the panel which headline to put over those words. 3 is
# already an app's "no console to answer a prompt". gui/static/app.js keeps
# the same numbers, and core/tests/test_every_app_says_when_nothing_happened.py
# holds the two to it.
NOTHING_OPENED = 5
NOTHING_RECORDED = 6
# A run that downloads found no signed-in browser to attach to, most often
# a first Get new pressed before Open sign-in window. Nothing was started,
# so the panel says to sign in first and never offers Continue.
NOT_SIGNED_IN = 7
# A support report that ran, and whose own findings say the window was on a
# sign-in page or a security check. Its files are there and say so, but it
# read nothing of the account's documents, and "Support report saved" read
# as though it had.
NOTHING_READ = 8


def under_panel() -> bool:
    """Whether the control panel started this run, so its words are the
    names on the panel's buttons. In a terminal they are the flags' names."""
    return bool(os.environ.get(MARK_ENV, ""))


def after_sign_in(record: bool = False) -> str:
    """What to do once signed in, in the words of where the run is: the
    panel's button under the panel, the command in a terminal.

    `record` is for a first shell of a provider, which downloads nothing
    yet, so the step after signing in is a recording of one trip to a
    document. Record steps sits in Get help, under More."""
    if record:
        return ("press Record steps (More, then Get help)" if os.environ.get(MARK_ENV, "")
                else "run record")
    return "press Try the newest few first" if os.environ.get(MARK_ENV, "") else "run the pilot"


def not_signed_in(cdp_url, err) -> SystemExit:
    """The exit for a run that could not attach to the signed-in browser at
    cdp_url, after saying so in the words of where it runs: the panel's
    buttons under the panel, which marks its runs, and login.bat in a
    terminal. Raised by each app as `raise not_signed_in(cdp_url, e)`."""
    if os.environ.get(MARK_ENV, ""):
        words = ("No signed-in browser window was open for this run, so nothing was downloaded. "
                 "Press Open sign-in window, sign in there and leave the window open, then run this again.")
    else:
        words = (f"Could not connect to your signed-in browser at {cdp_url}.\n"
                 "Run login.bat first and keep that browser window OPEN.")
    print(f"{words}\n({err})", file=sys.stderr, flush=True)
    return SystemExit(NOT_SIGNED_IN)


def nothing_read() -> SystemExit:
    """The exit of a Diagnose that read no signed-in page, after saying so
    in the words of where it runs. Raised from failure.write_survey, which
    every app's Diagnose ends in, once the survey is written."""
    if os.environ.get(MARK_ENV, ""):
        words = ("The window was on a sign-in page or a security check, so this support report "
                 "read nothing useful. Sign in, leave the window on the page that has your "
                 "documents, then make the report again.")
    else:
        words = ("The browser window was on a sign-in page or a security check, so Diagnose read "
                 "nothing useful.\nSign in, leave that window on the documents page, then run "
                 "Diagnose again.")
    print(words, flush=True)
    return SystemExit(NOTHING_READ)


# What cannot be shown on one line of a run's output. A line feed or a
# carriage return ends the line, the other control characters and the two
# Unicode separators end it for str.splitlines or move a terminal about.
# Half of a character, which a name that is not UTF-8 on Linux reads as,
# cannot be written as UTF-8 at all. A tab is left as it is. gui/run_result.py keeps the same set, and
# core/tests/test_one_line.py holds the two to it.
_NOT_ONE_LINE = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f" + chr(0x2028) + chr(0x2029)
                           + chr(0xd800) + "-" + chr(0xdfff) + "]")


def one_line(text) -> str:
    """Text as one line of a run's output, each character that would end
    the line or move a terminal written as its escape, \\n for a line feed."""
    return _NOT_ONE_LINE.sub(lambda m: repr(m.group())[1:-1], str(text))


def on_one_line(text) -> bool:
    """Whether text shows as one line as it is, with nothing to escape."""
    return _NOT_ONE_LINE.search(str(text)) is None


def marked(prefix: str, payload: dict) -> str:
    """A line the control panel reads, carrying the mark it gave this run,
    or unmarked for a run it did not start."""
    mark = os.environ.get(MARK_ENV, "")
    if not _MARK.fullmatch(mark):
        mark = ""
    return prefix + (mark + " " if mark else "") + json.dumps(payload)


def stopped_early() -> bool:
    """True while the run is on its way out on an exception.

    Every app writes its result from a `finally`, so the result is written
    on the way out of a run that stopped as well. The common stop is a
    sign-out or a security check in the middle of a run under the panel,
    where there is nobody to answer the prompt, and the app leaves with
    SystemExit(0). Exit code 0 and all-zero counts read as "finished, no
    issues", which is how a MyECP run that had lost its session on the
    19th of 25 statements looked clean. The exception in flight is what
    tells the two apart, and it is here, in one place, rather than at the
    114 places an app can stop."""
    return sys.exc_info()[1] is not None


class ListNotRead(SystemExit):
    """A Resume stopping because no run has read the provider's list to its
    end, so it has nothing more to carry on with (paperpull_core.listing).
    Only a run that lists can, and pressing Resume again would stop here
    again, which is how Chase's Continue went round and round (#124). So the
    run's summary says so, and the panel offers Get new documents instead.
    `whole_run` is what to run, as the stop has just said it."""

    def __init__(self, whole_run: str):
        super().__init__(0)
        self.whole_run = whole_run


def list_not_read() -> str:
    """What to run instead, while the run is on its way out on a
    ListNotRead, or "" for any other way out."""
    stop = sys.exc_info()[1]
    return stop.whole_run if isinstance(stop, ListNotRead) else ""


# Why a run stopped, as one of these words, so the panel can say whose it
# is to fix rather than guess a sign-out for every stop. A run that knows
# no more sends none. gui/run_result.py takes only these, and
# core/tests/test_a_stop_says_why.py holds the two lists to each other.
#   needs_you  the provider wanted the person, to sign in again, get past
#              a check or wait for a page, and nobody was at the console
#   page       a page was not what the app expected (pressing.Stop), which
#              a changed site makes, and so do a chat window over a button
#              or a second tab, whose stops say to close it and Resume
#   slow       a wait for the provider's page ran out (a timeout), which a
#              busy site and a page that has changed both look like
#   error      anything else the app did not expect
STOP_REASONS = ("needs_you", "page", "slow", "error")


def _timed_out(exc) -> bool:
    """Whether exc is a wait that ran out, told by its kind and never by
    its words, which say "exceeded" for a recursion limit or a quota too.
    Playwright's TimeoutError and Python's own are both named so."""
    return isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__


def stop_reason() -> str:
    """Why the run is on its way out, while it is, or "".

    A pressing.Stop is caught by the app's own main() and left on a plain
    SystemExit raised while handling it (pressing.stop_run), so the stop is
    found on the exception's context as well as in flight."""
    from .browser import nobody_answered
    from .pressing import Stop
    exc = sys.exc_info()[1]
    if exc is None:
        return ""
    seen, link = set(), exc
    while link is not None and id(link) not in seen:
        # A list that stopped partway is its provider's page not reading as
        # expected too. Each app that has one keeps its own class, in its own
        # site file, so it is known here by name. Only that name is, so a
        # class an app puts under it for a stop a sign-in may cure, as
        # Charles Schwab's for an answer refused, gives no reason, and the
        # panel offers the sign-in first.
        if isinstance(link, Stop) or type(link).__name__ == "ListStopped":
            return "page"
        seen.add(id(link))
        link = link.__context__
    if not isinstance(exc, SystemExit):
        return "slow" if _timed_out(exc) else "error"
    if nobody_answered() and exc.code in (0, None):
        return "needs_you"
    return ""


# The runs that write a run summary yet save nothing. Verify checks the
# files already saved, a dry run (--dry-run, alone or with a download mode)
# plans names and saves none, and Amazon's --reparse-items reads its saved
# receipts again offline.
SAVES_NOTHING = ("verify", "dry-run", "reparse-items")

# The second line of new-this-run.txt. Each line names a file where the run
# saved it, and the list is kept as it is until the next download run, so a
# Rename or the panel's move to a documents folder since may have given that
# file another name or folder, or, when two files traded names, given its
# name to another file.
NEW_LIST_NOTE = ("# Each file is named as this run saved it. A Rename or a move since may "
                 "have given it another name or folder, or given its name to another file.\n")


def lists_what_it_saved(stats, args=None) -> bool:
    """Whether a run's summary writes new-this-run.txt, the list of the files
    it saved. A run that saves nothing leaves the list as the last download
    run wrote it, as Discover and Rename leave it by writing no summary at
    all, so the list always says what was last downloaded."""
    return stats.get("mode") not in SAVES_NOTHING and not getattr(args, "dry_run", False)


def report_run_result(stats):
    result = {name: int(stats.get(name, 0)) for name in
              ("manual_review", "failed", "validation_failures")}
    result["new_files"] = len(stats.get("new_files", []))
    # Of manual_review, the receipts saved under a name the app was unsure
    # of. Their files are where they belong and Review Names gives each a
    # better name, so the panel says that rather than sending the person to
    # an empty Manual Review folder.
    result["name_review"] = min(int(stats.get("name_review", 0) or 0), result["manual_review"])
    # A document that arrived, was read back, and was not the one asked
    # for. It is counted inside manual_review as well, which is what made
    # it invisible, since "needs review" reads the same whether nothing
    # arrived or the wrong statement did. The second means the run's other
    # documents are in doubt too, so it is reported on its own.
    wrong = int(stats.get("wrong_document", 0) or 0)
    result["wrong_document"] = wrong
    if wrong:
        print("\n%s, since %s not the one asked for. Nothing was saved under "
              "%s. That is a wrong document arriving, not a missing one, so "
              "it is worth reporting."
              % ("1 document was refused" if wrong == 1 else "%d documents were refused" % wrong,
                 "it was" if wrong == 1 else "each was",
                 "its name" if wrong == 1 else "their names"), flush=True)
    # Documents the list held that share a type and a date with another,
    # so a row could not be bound to one of them, and they were left
    # unsaved. The rest of the run went on, so this is said on its own.
    # They are listed again on every run, so the panel names them but
    # never takes them as a reason to look (gui/run_result.py).
    result["alike"] = int(stats.get("alike", 0) or 0)
    # A run state the save on the way out could not write holds none of
    # what this run did, so the next run may fetch it all again. Such a run
    # is not one that finished, whatever else it did.
    from .storage import unsaved_on_leaving
    unsaved = unsaved_on_leaving()
    result["stopped"] = int(stopped_early() or bool(unsaved))
    # Sent only when it is known, as an app from before it sends nothing.
    why = stop_reason()
    if why:
        result["stop"] = why
    whole_run = list_not_read()
    if whole_run:
        # Sent only when it is so, as an app from before it sends nothing.
        result["list_not_read"] = 1
    if unsaved and not stopped_early():
        print("\nThis run did its work, but its run state could not be written, so "
              "the next run may download again what this one saved. Close the "
              "program that has it open before running again.", flush=True)
    elif result["stopped"] and getattr(sys.exc_info()[1], "code", None) == NOT_SIGNED_IN:
        # Nothing started, and not_signed_in has said to sign in first, so
        # there is nothing here for Continue to carry on with.
        pass
    elif result["stopped"] and stats.get("mode") == "rename":
        # Rename downloads nothing for Resume to carry on with, and when it
        # stops it has just said what it put back and what to do instead.
        print("\nThis run stopped before it finished.", flush=True)
    elif result["stopped"] and stats.get("mode") == "discover":
        # Resume downloads, and Discover was run only to see what is there.
        print("\nThis run stopped before it finished. Check what's there downloads nothing, "
              "so run it again rather than Continue." if under_panel() else
              "\nThis run stopped before it finished. Discover downloads nothing, "
              "so press Discover again rather than Resume.", flush=True)
    elif result["stopped"] and whole_run:
        # Resume has just said the list was not read to its end. Saying here
        # that Resume carries on is what sent people round again (#124).
        print("\nThis run stopped before it finished. Whatever it saved is kept. "
              "%s would only stop here again, so run %s, either of which "
              "reads the list first." % ("Continue" if under_panel() else "Resume", whole_run), flush=True)
    elif result["stopped"]:
        print("\nThis run stopped before it finished. Whatever it saved is kept, "
              "and %s carries on from where it stopped."
              % ("Continue" if under_panel() else "Resume"), flush=True)
    # Never include account labels, paths, or provider response text.
    print(marked(PREFIX, result), flush=True)
