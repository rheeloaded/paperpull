"""Counts-only completion results for the local control panel."""
import json

PREFIX = "PAPERPULL_RUN_RESULT "


def report_run_result(stats):
    result = {name: int(stats.get(name, 0)) for name in
              ("manual_review", "failed", "validation_failures")}
    result["new_files"] = len(stats.get("new_files", []))
    # Never include account labels, paths, or provider response text.
    print(PREFIX + json.dumps(result), flush=True)
