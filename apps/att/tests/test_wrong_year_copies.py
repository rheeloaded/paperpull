"""The one repair for the bills 0.34.0 saved under the wrong year.

0.34.0 matched a bill button on its month and day alone, so a 2025 bill
asked for while only 2026's showed was saved as a copy of the 2026 bill
and marked downloaded for good. The tester found every 2025 file from May
through September was one, deleted them, and 0.34.1 still skipped each as
already downloaded (#26). Only a record proved to be a copy is cleared,
and a real bill a year older is left alone.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

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
                          paths=SimpleNamespace(manual_review=review),
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


def test_the_repair_runs_when_the_app_starts():
    import inspect
    src = inspect.getsource(att_docs.App.__init__)
    assert src.index("self._clear_wrong_year_copies()") > src.index("migrate_legacy_keys")
