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
        print("\n%d document(s) were refused because they were not the one "
              "asked for. Nothing was saved under their names. That is a "
              "wrong document arriving, not a missing one, so it is worth "
              "reporting." % wrong, flush=True)
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
    whole_run = list_not_read()
    if whole_run:
        # Sent only when it is so, as an app from before it sends nothing.
        result["list_not_read"] = 1
    if unsaved and not stopped_early():
        print("\nThis run did its work, but its run state could not be written, so "
              "the next run may download again what this one saved. Close the "
              "program that has it open before running again.", flush=True)
    elif result["stopped"] and stats.get("mode") == "rename":
        # Rename downloads nothing for Resume to carry on with, and when it
        # stops it has just said what it put back and what to do instead.
        print("\nThis run stopped before it finished.", flush=True)
    elif result["stopped"] and stats.get("mode") == "discover":
        # Resume downloads, and Discover was run only to see what is there.
        print("\nThis run stopped before it finished. Discover downloads nothing, "
              "so press Discover again rather than Resume.", flush=True)
    elif result["stopped"] and whole_run:
        # Resume has just said the list was not read to its end. Saying here
        # that Resume carries on is what sent people round again (#124).
        print("\nThis run stopped before it finished. Whatever it saved is kept. "
              "Resume would only stop here again, so run %s, either of which "
              "reads the list first." % whole_run, flush=True)
    elif result["stopped"]:
        print("\nThis run stopped before it finished. Whatever it saved is kept, "
              "and Resume carries on from where it stopped.", flush=True)
    # Never include account labels, paths, or provider response text.
    print(marked(PREFIX, result), flush=True)
