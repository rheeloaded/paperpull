"""Counts-only completion results for the local control panel."""
import json
import sys

PREFIX = "PAPERPULL_RUN_RESULT "


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


def report_run_result(stats):
    result = {name: int(stats.get(name, 0)) for name in
              ("manual_review", "failed", "validation_failures")}
    result["new_files"] = len(stats.get("new_files", []))
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
    result["stopped"] = int(stopped_early())
    if result["stopped"]:
        print("\nThis run stopped before it finished. Whatever it saved is kept, "
              "and Resume carries on from where it stopped.", flush=True)
    # Never include account labels, paths, or provider response text.
    print(PREFIX + json.dumps(result), flush=True)
