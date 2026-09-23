"""What happens to the record of everything downloaded when its file is
not what it should be.

progress.json is the only thing that knows a document has already been
fetched. Lose it and the next run downloads the whole archive again, which
on a provider with a daily cap takes days and on any provider is rude.
So a file that cannot be read is kept, not replaced, and an earlier backup
is tried before giving up.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.storage import JsonStore  # noqa: E402

GOOD = {"chase:2026-08-31:Statement": {"downloaded_ok": True}}


def store(tmp_path, content: str):
    p = tmp_path / "progress.json"
    p.write_text(content, encoding="utf-8")
    return p, JsonStore(p, tmp_path / "Backups")


def backups(tmp_path):
    d = tmp_path / "Backups"
    return sorted(x.name for x in d.glob("*.bak")) if d.exists() else []


def test_an_ordinary_file_loads(tmp_path):
    _p, s = store(tmp_path, json.dumps(GOOD))
    assert s.load() == GOOD
    assert backups(tmp_path) == [], "nothing was wrong, so nothing was kept"


def test_a_truncated_file_is_kept_before_starting_over(tmp_path):
    _p, s = store(tmp_path, '{"a": {"downloaded_ok": tr')
    assert s.load() == {}
    assert backups(tmp_path), "the unreadable file was thrown away"


def test_valid_json_of_the_wrong_shape_is_kept_too(tmp_path):
    """A list, or a bare null, is as unusable as a truncated file. It used
    to fall straight through, so the next save replaced the file with {}
    and the record of every download went with it, unbacked up."""
    for content in ("[]", "null", '"progress"', "42"):
        d = tmp_path / content.strip('"[]')[:4] or tmp_path / "x"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "progress.json"
        p.write_text(content, encoding="utf-8")
        s = JsonStore(p, d / "Backups")
        assert s.load() == {}, content
        kept = list((d / "Backups").glob("*.bak"))
        assert kept, "%s was thrown away rather than kept" % content
        assert kept[0].read_text(encoding="utf-8") == content


def test_an_earlier_backup_is_used_rather_than_starting_empty(tmp_path):
    """The whole point of keeping backups."""
    b = tmp_path / "Backups"
    b.mkdir()
    (b / "progress.20260101-000000.json.bak").write_text(json.dumps(GOOD), encoding="utf-8")
    _p, s = store(tmp_path, "[]")
    assert s.load() == GOOD


def test_the_newest_readable_backup_wins(tmp_path):
    import os
    import time
    b = tmp_path / "Backups"
    b.mkdir()
    old = b / "progress.20260101-000000.json.bak"
    new = b / "progress.20260601-000000.json.bak"
    old.write_text(json.dumps({"old": {}}), encoding="utf-8")
    new.write_text(json.dumps({"new": {}}), encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 1000, now - 1000))
    os.utime(new, (now, now))
    _p, s = store(tmp_path, "[]")
    assert s.load() == {"new": {}}


def test_a_backup_that_is_also_broken_is_skipped(tmp_path):
    import os
    import time
    b = tmp_path / "Backups"
    b.mkdir()
    good = b / "progress.20260101-000000.json.bak"
    bad = b / "progress.20260601-000000.json.bak"
    good.write_text(json.dumps(GOOD), encoding="utf-8")
    bad.write_text("{oh dear", encoding="utf-8")
    now = time.time()
    os.utime(good, (now - 1000, now - 1000))
    os.utime(bad, (now, now))
    _p, s = store(tmp_path, "[]")
    assert s.load() == GOOD


def test_a_file_that_is_simply_absent_is_not_an_error(tmp_path):
    s = JsonStore(tmp_path / "progress.json", tmp_path / "Backups")
    assert s.load() == {}
    assert backups(tmp_path) == []
