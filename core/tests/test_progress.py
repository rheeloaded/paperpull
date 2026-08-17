"""Progress-file atomic writes, updates, and corrupt-file recovery."""
import json
import sys
from pathlib import Path


from paperpull_core.storage import JsonStore, atomic_write_json, backup_file


def test_atomic_write_and_load(tmp_path):
    p = tmp_path / "progress.json"
    store = JsonStore(p, tmp_path / "Backups")
    store.load()
    store.update("Online:123", {"state": "Discovered"})
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["Online:123"]["state"] == "Discovered"
    assert "updated_at" in data["Online:123"]


def test_update_merges(tmp_path):
    store = JsonStore(tmp_path / "p.json", tmp_path / "Backups")
    store.load()
    store.update("k", {"a": 1})
    store.update("k", {"b": 2})
    rec = store.get("k")
    assert rec["a"] == 1 and rec["b"] == 2


def test_corrupt_file_recovery_from_backup(tmp_path):
    p = tmp_path / "progress.json"
    backups = tmp_path / "Backups"
    # write good data + backup
    store = JsonStore(p, backups)
    store.load()
    store.update("Online:1", {"state": "Completed"})
    backup_file(p, backups)
    # corrupt the live file
    p.write_text("{ this is not json !!!", encoding="utf-8")
    # new store should recover from backup
    store2 = JsonStore(p, backups)
    data = store2.load()
    assert data.get("Online:1", {}).get("state") == "Completed"


def test_corrupt_file_no_backup_starts_fresh(tmp_path):
    p = tmp_path / "progress.json"
    p.write_text("not json at all", encoding="utf-8")
    store = JsonStore(p, tmp_path / "Backups")
    data = store.load()
    assert data == {}
    # the corrupt file was preserved as a backup for inspection
    assert list((tmp_path / "Backups").glob("progress.*.bak"))


def test_atomic_write_replaces_not_appends(tmp_path):
    p = tmp_path / "x.json"
    atomic_write_json(p, {"a": 1})
    atomic_write_json(p, {"b": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"b": 2}
    # no stray temp files left behind
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_backup_file_timestamped_no_overwrite(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("{}", encoding="utf-8")
    b1 = backup_file(p, tmp_path / "Backups")
    b2 = backup_file(p, tmp_path / "Backups")
    assert b1.exists() and b2.exists() and b1 != b2
