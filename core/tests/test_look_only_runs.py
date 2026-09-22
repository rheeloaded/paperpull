"""A run that only looks at the page must not disturb the last real one.

new-this-run.txt is the user's record of what their last download run
fetched, and write_run_summary replaces it every time it is called. For a
download run that is right, including when it downloaded nothing (#17).
For diagnose and record, which download nothing by design, it destroyed a
list that was still true. Found by auditing the recorder.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))

LOOK_ONLY = ("diagnose", "record")


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_a_look_only_run_writes_no_summary(entry):
    src = entry.read_text(encoding="utf-8-sig")
    m = re.search(r'if app\.stats\["mode"\][^\n]*:\n\s*app\.write_run_summary\(\)',
                  src)
    assert m, "%s never guards write_run_summary" % entry.parent.name
    guard = m.group(0)
    for mode in LOOK_ONLY:
        assert '"%s"' % mode in guard, (
            "%s would write a run summary after --%s, which replaces "
            "new-this-run.txt with an empty list" % (entry.parent.name, mode))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_a_real_run_still_writes_one(entry):
    """The guard must exclude the look-only modes and nothing else."""
    src = entry.read_text(encoding="utf-8-sig")
    guard = re.search(r'if app\.stats\["mode"\][^\n]*:', src).group(0)
    for mode in ("all", "pilot", "resume", "verify", "dry-run", "online", "instore"):
        assert '"%s"' % mode not in guard, (
            "%s would skip the summary after --%s" % (entry.parent.name, mode))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_record_does_not_download_or_touch_history(entry):
    """cmd_record hands the page to the core and does nothing else."""
    tree = ast.parse(entry.read_text(encoding="utf-8-sig"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "cmd_record"), None)
    assert fn is not None, "%s has no cmd_record" % entry.parent.name
    body = ast.get_source_segment(entry.read_text(encoding="utf-8-sig"), fn) or ""
    assert "record_session" in body
    # Anchored. "_record(" without one matches inside "cmd_record(", the
    # same shape of bug as "edit" matching inside "Credit".
    for never in (r"download", r"progress\.save", r"discovery\.save",
                  r"index_csv", r"self\._record\(", r"unique_path\("):
        assert not re.search(never, body), (
            "%s: cmd_record does %s" % (entry.parent.name, never))
