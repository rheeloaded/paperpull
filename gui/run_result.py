"""Validate counts reported by this process; never read a prior run's summary."""
import json
PREFIX = "PAPERPULL_RUN_RESULT "
FIELDS = ("manual_review", "failed", "validation_failures", "new_files")


def parse(line):
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX):])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or any(type(data.get(k)) is not int or data[k] < 0 for k in FIELDS):
        return None
    result = {k: data[k] for k in FIELDS}
    result["attention"] = any(result[k] for k in FIELDS if k != "new_files")
    return result
