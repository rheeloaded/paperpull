"""Counts-only completion results for the local control panel."""
import json

PREFIX = "PAPERPULL_RUN_RESULT "


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
    # Never include account labels, paths, or provider response text.
    print(PREFIX + json.dumps(result), flush=True)
