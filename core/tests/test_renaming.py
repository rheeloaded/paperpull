"""Renaming files already downloaded, and the ledger that points at them.

A tester asked how to re-pull five receipts so they would take a better
name (#43). Nothing about those files needed fetching. These pin the
promises the rename makes, above all that it cannot lose a file and
cannot leave the ledger pointing at one that is gone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import renaming  # noqa: E402
from paperpull_core.storage import JsonStore  # noqa: E402

PATH = "PDF Full Path"
NAME = "PDF Filename"


def row(folder, name, **kw):
    p = Path(folder) / name
    p.write_bytes(b"%PDF-1.7 a file")
    r = {PATH: str(p), NAME: name, "Notes": ""}
    r.update(kw)
    return r


def by_order(r):
    """A naming scheme that puts the order number in, which is the whole
    point of the exercise."""
    return "2026-09-23 Testco %s Receipt.pdf" % r["order"]


# -- planning ----------------------------------------------------------------

def test_a_file_already_named_right_is_left_alone(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco A1 Receipt.pdf", order="A1")
    [change] = renaming.plan([r], by_order)
    assert not change.renaming
    assert change.reason == "already named that"


def test_running_it_twice_does_nothing_the_second_time(tmp_path):
    rows = [row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")]
    renaming.apply(renaming.plan(rows, by_order))
    renaming.update_rows(rows, renaming.Result())
    rows[0][PATH] = str(tmp_path / "2026-09-23 Testco A1 Receipt.pdf")
    rows[0][NAME] = "2026-09-23 Testco A1 Receipt.pdf"
    assert not any(c.renaming for c in renaming.plan(rows, by_order))


def test_a_record_whose_file_is_gone_is_reported_not_renamed(tmp_path):
    r = {PATH: str(tmp_path / "deleted.pdf"), NAME: "deleted.pdf", "order": "A1"}
    [change] = renaming.plan([r], by_order)
    assert not change.renaming
    assert "not on disk" in change.reason


def test_a_row_too_thin_to_name_does_not_stop_the_rest(tmp_path):
    good = row(tmp_path, "one.pdf", order="A1")
    bad = row(tmp_path, "two.pdf")           # no order at all

    def build(r):
        return by_order(r)                    # raises KeyError on the second

    changes = renaming.plan([good, bad], build)
    assert changes[0].renaming
    assert not changes[1].renaming and "could not work out a name" in changes[1].reason


# -- doing it ----------------------------------------------------------------

def test_the_file_is_renamed_and_nothing_else_moves(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    result = renaming.apply(renaming.plan([r], by_order))
    assert result.renamed == 1
    assert (tmp_path / "2026-09-23 Testco A1 Receipt.pdf").exists()
    assert not (tmp_path / "2026-09-23 Testco Widget Receipt.pdf").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-23 Testco A1 Receipt.pdf"]


def test_two_files_that_want_each_others_names_both_land(tmp_path):
    """A straight rename would refuse or overwrite depending on the
    platform, and one of the two would be gone."""
    a = row(tmp_path, "2026-09-23 Testco A2 Receipt.pdf", order="A1")
    b = row(tmp_path, "2026-09-23 Testco A1 Receipt.pdf", order="A2")
    (tmp_path / a[NAME]).write_bytes(b"%PDF-A")
    (tmp_path / b[NAME]).write_bytes(b"%PDF-B")
    result = renaming.apply(renaming.plan([a, b], by_order))
    assert result.renamed == 2
    assert (tmp_path / "2026-09-23 Testco A1 Receipt.pdf").read_bytes() == b"%PDF-A"
    assert (tmp_path / "2026-09-23 Testco A2 Receipt.pdf").read_bytes() == b"%PDF-B"
    assert not list(tmp_path.glob("*.renaming*"))


def test_a_file_that_is_not_in_the_ledger_is_never_touched(tmp_path):
    (tmp_path / "somebody elses file.pdf").write_bytes(b"%PDF-")
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    renaming.apply(renaming.plan([r], by_order))
    assert (tmp_path / "somebody elses file.pdf").exists()


def test_two_records_wanting_one_name_do_not_become_one_file(tmp_path):
    a = row(tmp_path, "first.pdf", order="A1")
    b = row(tmp_path, "second.pdf", order="A1")   # the same name, somehow
    result = renaming.apply(renaming.plan([a, b], by_order))
    assert result.renamed == 2
    assert len(list(tmp_path.iterdir())) == 2, "neither file was written over"


def test_nothing_happens_until_apply_is_called(tmp_path):
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    renaming.plan([r], by_order)
    assert (tmp_path / "2026-09-23 Testco Widget Receipt.pdf").exists()


# -- the ledger --------------------------------------------------------------

def test_the_index_is_pointed_at_the_file_as_it_is_now_called(tmp_path):
    """Verify reads the full path out of the index, so a rename that
    skipped this would report every file on disk as missing."""
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    result = renaming.apply(renaming.plan([r], by_order))
    assert renaming.update_rows([r], result, note="renamed") == 1
    assert r[NAME] == "2026-09-23 Testco A1 Receipt.pdf"
    assert Path(r[PATH]).exists()
    assert "renamed" in r["Notes"]


def test_a_second_csv_carrying_only_the_name_is_updated_too(tmp_path):
    """A receipt app writes the order history as well as the index, and
    that one has no full path column."""
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    history = {NAME: "2026-09-23 Testco Widget Receipt.pdf", "Notes": ""}
    result = renaming.apply(renaming.plan([r], by_order))
    assert renaming.update_rows([history], result) == 1
    assert history[NAME] == "2026-09-23 Testco A1 Receipt.pdf"


def test_the_run_state_follows_and_its_key_never_changes(tmp_path):
    store = JsonStore(tmp_path / "progress.json", tmp_path / "Backups")
    store.load()
    r = row(tmp_path, "2026-09-23 Testco Widget Receipt.pdf", order="A1")
    store.update("Online:A1", {"pdf_filename": r[NAME], "pdf_path": r[PATH],
                               "downloaded_ok": True})
    result = renaming.apply(renaming.plan([r], by_order))
    assert renaming.update_progress(store, result) == 1
    rec = store.get("Online:A1")
    assert rec["pdf_filename"] == "2026-09-23 Testco A1 Receipt.pdf"
    assert Path(rec["pdf_path"]).exists()
    assert rec["downloaded_ok"] is True, "what stops a second download is untouched"
    assert list(store.data) == ["Online:A1"], "the identity is the key and it did not move"


def test_an_untouched_row_is_not_rewritten(tmp_path):
    r = {PATH: "", NAME: "", "Notes": "keep me"}
    assert renaming.update_rows([r], renaming.Result(), note="renamed") == 0
    assert r["Notes"] == "keep me"
