"""Progress-file atomic writes, updates, and corrupt-file recovery."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import storage
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


# -- the save every app makes on its way out --------------------------------------

def _line(path) -> str:
    return ("  ! %s could not be written, so it keeps what was last saved in it. Close any "
            "program that has it open before the next run." % path)


@pytest.fixture
def held(monkeypatch):
    """Files refused as Windows refuses to replace a file another program
    holds open, by path, each try at one counted, and each pause between
    tries counted and not taken."""
    real = os.replace
    held = SimpleNamespace(files=set(), tries=[], pauses=[])

    def replace(src, dst, *args, **kwargs):
        if Path(dst) in held.files:
            held.tries.append(Path(dst).name)
            raise PermissionError(13, "The process cannot access the file because it is "
                                  "being used by another process", str(dst))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr("time.sleep", lambda seconds: held.pauses.append(seconds))
    return held


def _a_store(tmp_path) -> JsonStore:
    """A run state with Online:1 saved and Online:2 noted since, not yet
    saved."""
    store = JsonStore(tmp_path / "progress.json", tmp_path / "Backups")
    store.load()
    store.update("Online:1", {"state": "Completed"})
    store.update("Online:2", {"state": "Completed"}, save=False)
    return store


def _saved_keys(store) -> list:
    return sorted(json.loads(store.path.read_text(encoding="utf-8")))


def test_a_held_file_saved_during_a_run_still_stops_it(tmp_path, held):
    """Only the save on the way out says a line and goes on. A save in the
    middle of a run that cannot write its file stops the run, as it always
    has."""
    store = _a_store(tmp_path)
    held.files.add(store.path)
    with pytest.raises(PermissionError):
        store.save()
    assert len(held.tries) == storage._LOCKED_TRIES
    assert _saved_keys(store) == ["Online:1"]


def test_a_held_file_saved_on_the_way_out_is_waited_for_then_named(tmp_path, held, capsys):
    """A file nobody had found held is waited for the usual minute, as
    closing it in that minute lets the save through. Then one line says it
    was not written and where, and nothing is raised."""
    store = _a_store(tmp_path)
    held.files.add(store.path)
    store.save(leaving=True)
    out = capsys.readouterr().out
    assert len(held.tries) == storage._LOCKED_TRIES
    assert len(held.pauses) == storage._LOCKED_TRIES
    assert out.count("is open in another program") == 1
    assert out.splitlines()[-1] == _line(store.path)
    assert _saved_keys(store) == ["Online:1"]
    assert not list(tmp_path.glob("*.tmp")), "the copy it could not put in place was left"


@pytest.mark.parametrize("waited", ["by Rename's check", "by a save that gave up"])
def test_a_file_the_run_already_waited_for_is_tried_once_on_the_way_out(tmp_path, held,
                                                                       capsys, waited):
    """Rename found progress.json held, waited its minute and stopped, and
    the save on the way out waited a second minute for the same file."""
    store = _a_store(tmp_path)
    held.files.add(store.path)
    if waited == "by Rename's check":
        assert not storage.free_to_write(store.path, say=lambda *_a: None)
    else:
        with pytest.raises(PermissionError):
            store.save()
    capsys.readouterr()
    held.tries.clear()
    held.pauses.clear()
    store.save(leaving=True)
    assert held.tries == ["progress.json"] and held.pauses == []
    assert capsys.readouterr().out.splitlines() == [_line(store.path)]
    assert _saved_keys(store) == ["Online:1"]


def test_a_file_let_go_after_the_run_waited_for_it_is_written_on_the_way_out(tmp_path, held,
                                                                              capsys):
    """Closed after the run waited for it, the file is written on the way
    out, and once written it is waited for the next time as any file is."""
    store = _a_store(tmp_path)
    held.files.add(store.path)
    assert not storage.free_to_write(store.path, say=lambda *_a: None)
    held.files.clear()
    store.save(leaving=True)
    assert capsys.readouterr().out == ""
    assert _saved_keys(store) == ["Online:1", "Online:2"]
    held.files.add(store.path)
    held.tries.clear()
    store.update("Online:3", {"state": "Completed"}, save=False)
    store.save(leaving=True)
    assert len(held.tries) == storage._LOCKED_TRIES, (
        "a file written since it was held is waited for again")


def test_a_save_on_the_way_out_keeps_its_backup(tmp_path):
    store = _a_store(tmp_path)
    store.save(backup=True, leaving=True)
    assert [b.name.split(".")[0] for b in (tmp_path / "Backups").iterdir()] == ["progress"]
    assert _saved_keys(store) == ["Online:1", "Online:2"]


def test_a_run_whose_run_state_was_not_written_is_not_reported_finished(tmp_path, monkeypatch,
                                                                       capsys):
    """The run finished, but the save on the way out could not write
    progress.json, so it holds none of what the run did. The panel is told
    the run stopped, never that it finished clean, and nothing points to
    Resume."""
    import json as _json
    from paperpull_core import run_reporting, storage
    monkeypatch.setattr(storage, "_UNSAVED", [])
    monkeypatch.setattr(storage, "_HELD", {storage._held_key(tmp_path / "progress.json")})

    def refused(*args, **kwargs):
        raise PermissionError(13, "held", str(tmp_path / "progress.json"))
    monkeypatch.setattr(storage, "atomic_write_json", refused)
    store = storage.JsonStore(tmp_path / "progress.json")
    store.data = {"k": {"state": "Completed"}}
    store._loaded = True
    store.save(leaving=True)
    run_reporting.report_run_result({"new_files": ["a.pdf"]})
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if ln.startswith(run_reporting.PREFIX)][-1]
    assert _json.loads(line[len(run_reporting.PREFIX):])["stopped"] == 1, out
    assert "run state could not be written" in out and "Resume" not in out, out


def test_a_run_that_changed_nothing_writes_nothing_on_its_way_out(tmp_path, monkeypatch, capsys):
    """A Rename preview or a Verify with progress.json held changed no
    record, so its save on the way out writes nothing, says nothing and
    leaves the run reported as it ended, never as one whose run state was
    lost. A run that did change a record is still told."""
    import json as _json
    from paperpull_core import run_reporting, storage
    path = tmp_path / "progress.json"
    path.write_text(_json.dumps({"k": {"state": "Completed"}}), encoding="utf-8")
    store = storage.JsonStore(path)
    store.load()

    def refused(*args, **kwargs):
        raise PermissionError(13, "held", str(path))
    monkeypatch.setattr(storage, "atomic_write_json", refused)
    store.save(leaving=True)
    assert storage.unsaved_on_leaving() == []
    run_reporting.report_run_result({})
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if ln.startswith(run_reporting.PREFIX)][-1]
    assert _json.loads(line[len(run_reporting.PREFIX):])["stopped"] == 0, out
    assert "could not be written" not in out, out

    store.update("k", {"state": "Needs Manual Review"}, save=False)
    store.save(leaving=True)
    assert storage.unsaved_on_leaving() == [str(path)]
