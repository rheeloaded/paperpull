"""Validate counts reported by this process; never read a prior run's summary."""
import hmac
import json
import re
import secrets
PREFIX = "PAPERPULL_RUN_RESULT "
# The line tools/export_transactions.py writes naming the spreadsheet it
# wrote, which the panel offers to show or hand over.
EXPORT_PREFIX = "PAPERPULL_EXPORT_RESULT "
# The mark the panel gives each run it starts, in this variable. Only the
# run's own result line carries it (core run_reporting.marked), and a line
# without it is shown as any other line, never taken as a result. A run
# prints names it read from the disk and text a provider's page gave it,
# and on Linux and macOS a file name may hold a line break, so a name could
# otherwise start a line of its own reading like a result.
MARK_ENV = "PAPERPULL_RUN_MARK"
_MARK = re.compile(r"[0-9a-f]{32}")
FIELDS = ("manual_review", "failed", "validation_failures", "new_files")
# Counts an app from before they existed does not send. Absent is zero,
# present has to be a count like the rest, so an install the panel has
# not refreshed yet still reports its run.
OPTIONAL = ("wrong_document", "stopped", "name_review", "alike", "list_not_read")
# Counts the panel says but that never make a run one to look at.
# Documents that share a type and a date with another are listed again on
# every run and can never be saved, even once taken by hand from the
# provider's own page, so a run that counted them would need a look for
# good, and the row would never again say it is due or overdue.
SAID_ONLY = ("alike",)
# What cannot be shown on one line, the same set as core run_reporting's
# (core/tests/test_one_line.py holds the two to it). A line feed or a
# carriage return would end a line of the stream the page reads, the
# rest end one for str.splitlines or move a terminal about, and half of a
# character cannot be sent as UTF-8 at all.
_NOT_ONE_LINE = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f" + chr(0x2028) + chr(0x2029)
                           + chr(0xd800) + "-" + chr(0xdfff) + "]")


def one_line(text) -> str:
    """Text as one line, each character that would end the line written as
    its escape, \\n for a line feed."""
    return _NOT_ONE_LINE.sub(lambda m: repr(m.group())[1:-1], str(text))


def on_one_line(text) -> bool:
    """Whether text shows as one line as it is, with nothing to escape."""
    return _NOT_ONE_LINE.search(str(text)) is None


def new_mark() -> str:
    """A mark for one run, handed to it in MARK_ENV."""
    return secrets.token_hex(16)


def _marked(line, prefix, mark):
    """The object a line marked for this run carries after the prefix, or
    None for any other line."""
    if not (isinstance(mark, str) and _MARK.fullmatch(mark)):
        return None
    if not line.startswith(prefix):
        return None
    rest = line[len(prefix):]
    # As bytes, since hmac takes text of ASCII alone and the line may hold
    # any text at all, half of a character among it.
    head = rest[:len(mark) + 1].encode("utf-8", "surrogatepass")
    if not hmac.compare_digest(head, (mark + " ").encode("ascii")):
        return None
    try:
        data = json.loads(rest[len(mark) + 1:])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _count(value):
    return type(value) is int and value >= 0


def parse(line, mark):
    """The counts on this run's own result line, the one carrying `mark`."""
    data = _marked(line, PREFIX, mark)
    if data is None or not all(_count(data.get(k)) for k in FIELDS):
        return None
    if any(k in data and not _count(data[k]) for k in OPTIONAL):
        return None
    result = {k: data[k] for k in FIELDS}
    result.update({k: data.get(k, 0) for k in OPTIONAL})
    # Part of manual_review, never more than it.
    if result["name_review"] > result["manual_review"]:
        return None
    result["attention"] = any(result[k] for k in FIELDS + OPTIONAL
                              if k != "new_files" and k not in SAID_ONLY)
    return result


def exported(line, mark):
    """The path on the export's own line naming what it wrote, the one
    carrying `mark`, or None."""
    data = _marked(line, EXPORT_PREFIX, mark)
    path = data.get("path") if data is not None else None
    return path if isinstance(path, str) and path else None
