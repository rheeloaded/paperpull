"""The one repair for the bills 0.34.0 saved under the wrong year.

0.34.0 matched a bill button on its month and day alone, so a 2025 bill
asked for while only 2026's showed was saved as a copy of the 2026 bill
and marked downloaded for good. The tester found every 2025 file from May
through September was one, deleted them, and 0.34.1 still skipped each as
already downloaded (#26). Only a record proved to be a copy is cleared,
and a real bill a year older is left alone.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_docs
from storage import JsonStore


def _rec(date, size, pages=4, account="", summary="Monthly Statement"):
    # AT&T's records carry no account, the kind is in the summary, and a
    # bill downloaded before the kind was read has none (#26).
    title = f"Monthly Statement - {date}"
    return {"title": title, "category": "Statement", "date": date,
            "account": account, "summary": summary,
            "downloaded_ok": True, "state": "Completed",
            "pdf_path": "", "pdf_filename": f"{date} AT&T Monthly Statement.pdf",
            "pdf_size": size, "pdf_pages": pages, "notes": ""}


def _store():
    recs = [
        _rec("2026-07-22", 240546),
        _rec("2025-07-22", 240546, summary="Wireless Monthly Statement"),  # the copy
        _rec("2026-06-22", 251234),
        _rec("2025-06-22", 250002),                 # a real 2025 bill
        _rec("2026-08-22", 259178, pages=2),
        _rec("2025-08-22", 259178, pages=3),        # same size, other page count
        _rec("2026-07-05", 199000),
        _rec("2025-07-22", 240546, account="Other"),  # same day and size, other account
    ]
    return {att_docs.Document.from_dict(r).key: r for r in recs}


def test_a_copy_of_the_next_years_bill_is_cleared_and_a_real_bill_is_not():
    progress = _store()
    discovery = {k: {"state": "Completed"} for k in progress}
    before = {k: dict(v) for k, v in progress.items()}
    cleared = att_docs.clear_wrong_year_copies(progress, discovery)
    assert [c[1:3] for c in cleared] == [("2025-07-22", "2026-07-22")]
    copy_key = cleared[0][0]
    copy = progress[copy_key]
    assert copy["downloaded_ok"] is False and copy["state"] == "Discovered"
    assert copy["pdf_size"] == "" and copy["pdf_path"] == ""
    assert "the 2026-07-22 bill" in copy["notes"]
    assert discovery[copy_key]["state"] == "Discovered"
    # everything else, the real 2025 bills among them, is exactly as it was
    for key, rec in progress.items():
        if key != copy_key:
            assert rec == before[key], key
            assert discovery[key]["state"] == "Completed"


def test_a_cleared_copy_is_fetched_again_and_the_repair_does_nothing_twice():
    progress = _store()
    att_docs.clear_wrong_year_copies(progress, {})
    assert att_docs.clear_wrong_year_copies(progress, {}) == []
    app = SimpleNamespace(args=SimpleNamespace(redownload=False),
                          progress=SimpleNamespace(get=progress.get))
    done = {rec["date"] + rec["account"]: att_docs.App._already_done(
        app, att_docs.Document.from_dict(rec)) for rec in progress.values()}
    assert done.pop("2025-07-22") is False
    assert all(done.values())


def test_the_app_clears_them_when_it_starts_and_moves_a_copy_left_on_disk(tmp_path, capsys):
    progress = JsonStore(tmp_path / "progress.json", tmp_path / "backups")
    discovery = JsonStore(tmp_path / "discovery.json", tmp_path / "backups")
    progress.data, discovery.data = _store(), {}
    review = tmp_path / "Manual Review"
    review.mkdir()
    copy = tmp_path / "2025-07-22 AT&T Monthly Statement.pdf"
    copy.write_bytes(b"x" * 240546)
    real = tmp_path / "2025-06-22 AT&T Monthly Statement.pdf"
    real.write_bytes(b"y" * 250002)
    for rec in progress.data.values():
        if rec["date"] == "2025-07-22" and not rec["account"]:
            rec["pdf_path"] = str(copy)
        if rec["date"] == "2025-06-22":
            rec["pdf_path"] = str(real)
    app = SimpleNamespace(progress=progress, discovery=discovery,
                          paths=SimpleNamespace(manual_review=review,
                                                filing_folders=lambda: [tmp_path, review]),
                          config={"max_path_length": 240})
    att_docs.App._clear_wrong_year_copies(app)
    out = capsys.readouterr().out
    assert "1 bill(s) saved under the wrong year" in out
    assert "2025-07-22 held the 2026-07-22 bill" in out
    assert not copy.exists() and (review / copy.name).exists()
    assert real.exists(), "the real 2025 bill is never moved"
    saved = JsonStore(tmp_path / "progress.json", tmp_path / "backups")
    saved.load()
    assert sum(not r["downloaded_ok"] for r in saved.data.values()) == 1


def _repair_naming(tmp_path, monkeypatch, named):
    """The repair, run in the account's folder, with the copy's record
    naming `named` and the account filing in that folder alone."""
    folder = tmp_path / "acct"
    review = folder / "Manual Review"
    review.mkdir(parents=True)
    monkeypatch.chdir(folder)
    progress = JsonStore(folder / "progress.json", folder / "backups")
    discovery = JsonStore(folder / "discovery.json", folder / "backups")
    progress.data, discovery.data = _store(), {}
    for rec in progress.data.values():
        if rec["date"] == "2025-07-22" and not rec["account"]:
            rec["pdf_path"] = named
    app = SimpleNamespace(progress=progress, discovery=discovery,
                          paths=SimpleNamespace(manual_review=review,
                                                filing_folders=lambda: [folder, review]),
                          config={"max_path_length": 240})
    att_docs.App._clear_wrong_year_copies(app)
    return folder, review, progress


@pytest.mark.parametrize("how", ["absolute", "relative", "backslashes"])
def test_a_record_naming_a_file_outside_the_accounts_folders_never_moves_it(
        tmp_path, monkeypatch, capsys, how):
    """A record names its file, and a history imported from somewhere else
    can name any file on this computer of the copy's size. The repair moved
    that file into Manual Review whenever the app started (a private report
    of 2026-11-10). The record is still cleared, so the bill is fetched
    again."""
    decoy = tmp_path / "outside" / "decoy.pdf"
    decoy.parent.mkdir()
    decoy.write_bytes(b"x" * 240546)
    named = {"absolute": str(decoy), "relative": "../outside/decoy.pdf",
             "backslashes": "Statements\\..\\..\\outside\\decoy.pdf"}[how]
    if how == "backslashes" and sys.platform != "win32":
        named = named.replace("\\", "/")
    folder, review, progress = _repair_naming(tmp_path, monkeypatch, named)
    assert "1 bill(s) saved under the wrong year" in capsys.readouterr().out
    assert decoy.read_bytes() == b"x" * 240546 and list(review.iterdir()) == []
    assert sum(not r["downloaded_ok"] for r in progress.data.values()) == 1


def test_a_link_in_the_accounts_folder_is_not_followed_out_of_it(tmp_path, monkeypatch, capsys):
    decoy = tmp_path / "outside" / "decoy.pdf"
    decoy.parent.mkdir()
    decoy.write_bytes(b"x" * 240546)
    (tmp_path / "acct").mkdir()
    link = tmp_path / "acct" / "2025-07-22 AT&T Monthly Statement.pdf"
    try:
        link.symlink_to(decoy)
    except OSError:
        pytest.skip("this system does not let a test make a symbolic link")
    folder, review, _ = _repair_naming(tmp_path, monkeypatch, str(link))
    assert decoy.read_bytes() == b"x" * 240546 and link.is_symlink()
    assert list(review.iterdir()) == []


def test_the_repair_runs_when_the_app_starts():
    import inspect
    src = inspect.getsource(att_docs.App.__init__)
    assert src.index("self._clear_wrong_year_copies()") > src.index("migrate_legacy_keys")


# -- a history moved to another computer ----------------------------------------

APP = Path(__file__).resolve().parents[1]


def app_in(folder: Path):
    """The app as its own main builds it over `folder`, an output folder
    tools/migrate.py finds by the storage.py beside its progress.json."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "storage.py").write_bytes((APP / "storage.py").read_bytes())
    if not (folder / "progress.json").exists():
        (folder / "progress.json").write_text("{}", encoding="utf-8")
    config = json.loads((APP / "config.example.json").read_text())
    config.update({"owner": "Tester", "output_dir": str(folder)})
    cfg = folder.parent / "config.json"
    cfg.write_text(json.dumps(config))
    return att_docs.App(att_docs.build_parser().parse_args(["--discover", "--config", str(cfg)]))


@pytest.mark.parametrize("minimal", [False, True], ids=["whole", "minimal"])
def test_a_copy_moved_to_another_computer_is_cleared_there(tmp_path, capsys, minimal):
    """The history was moved before the old computer ever opened AT&T on a
    version with the repair, with no PDF copied across. The app clears the
    copy when it starts on the new computer, from what the moved records
    say of each bill, and leaves the real ones done."""
    sys.path.insert(0, str(APP.parents[1] / "tools"))
    import migrate
    old, new = tmp_path / "old" / "AT&T Statements", tmp_path / "new" / "AT&T Statements"
    old.mkdir(parents=True)
    (old / "storage.py").write_bytes((APP / "storage.py").read_bytes())
    (old / "progress.json").write_text(json.dumps(_store()), encoding="utf-8")
    app_in(new)
    archive = tmp_path / "history.ppz"
    assert migrate.export(old.parent, archive, minimal=minimal) == 0
    assert migrate.do_import(archive, new.parent, assume_yes=True) == 0

    app = app_in(new)
    assert "1 bill(s) saved under the wrong year" in capsys.readouterr().out
    done = {rec["date"] + rec["account"]: app._already_done(att_docs.Document.from_dict(rec))
            for rec in _store().values()}
    assert done.pop("2025-07-22") is False, "the copy would stay done for good"
    assert all(done.values()), done


def test_a_moved_history_naming_a_file_outside_moves_nothing_when_the_app_starts(
        tmp_path, capsys):
    """The way in the private report of 2026-11-10. A history file whose
    copy names a file beside the new computer's folders, by a path relative
    to the folder the app runs in. The import kept it as the app wrote it,
    and AT&T moved that file into Manual Review as it started. The import
    clears a path that leads out of the person's folder now, and the repair
    moves only a file the account holds."""
    sys.path.insert(0, str(APP.parents[1] / "tools"))
    import migrate
    old, new = tmp_path / "old" / "AT&T Statements", tmp_path / "new" / "AT&T Statements"
    old.mkdir(parents=True)
    (old / "storage.py").write_bytes((APP / "storage.py").read_bytes())
    records = _store()
    for rec in records.values():
        if rec["date"] == "2025-07-22" and not rec["account"]:
            rec["pdf_path"] = "../../outside/decoy.pdf"
    (old / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    decoy = tmp_path / "outside" / "decoy.pdf"
    decoy.parent.mkdir()
    decoy.write_bytes(b"x" * 240546)
    app_in(new)
    archive = tmp_path / "history.ppz"
    assert migrate.export(old.parent, archive) == 0
    assert migrate.do_import(archive, new.parent, assume_yes=True) == 0
    kept = json.loads((new / "progress.json").read_text(encoding="utf-8"))
    assert all("outside" not in (r.get("pdf_path") or "") for r in kept.values())

    app_in(new)
    assert "1 bill(s) saved under the wrong year" in capsys.readouterr().out
    assert decoy.read_bytes() == b"x" * 240546
    assert not list((new / "Manual Review").glob("decoy*"))
