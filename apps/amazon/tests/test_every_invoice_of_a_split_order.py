"""Every invoice of an order split across sellers is on file before the order
is done.

An Amazon order split across sellers has an invoice from each, behind its
Invoice menu, and each is saved beside the first as "(2 of 3)" and so on.
The first was marked done for good the moment it was saved, and an invoice
after it that did not come was written in the log and passed over. The
order was never asked for again, so its other invoices were never saved,
and a run stopped between two invoices left it the same. One that came and
failed its check was moved to Manual Review by a move nothing guarded, and
counted nowhere.

Each run here is the app's own, from the order as discovery lists it to the
rows it writes, with only Amazon's answers stood in. Each invoice link
answers with bytes of its own, so where each file went can be told from
them. Amazon makes its invoice links afresh for each request, so the app
never knows an invoice by its link, and nothing here asks it to. Every
order number, item, link and amount is invented.
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
from paperpull_core import renaming, storage as core_storage, testkit
from paperpull_core.models import ONLINE, Item, Purchase, State

ORDER = "111-2223334-4445556"
ITEM = "Invented Garden Hose 50 ft"
DATE = "2026-09-12"
NUMBERED = "{date:yyyy-mm-dd} {provider} {summary} {number}[ ({part})]"
DONE = "Every file is already named the way this app names them."


def link(name: str) -> str:
    return "https://www.amazon.com/documents/download/%s/invoice.pdf" % name


# Three sellers, as the Invoice menu lists them.
LINKS = [link("a1b2-seller-1"), link("a1b2-seller-2"), link("a1b2-seller-3")]


def invoice(name: str, order: str = ORDER, item: str = ITEM) -> bytes:
    """An invoice naming the order and its item, and the link it came from,
    so no two read alike."""
    return testkit.text_pdf(["Invoice", "Order # " + order, "Order date " + DATE, item,
                             "Invented seller of " + name])


BODIES = {url: invoice(url) for url in LINKS + [link("a1b2-credit-note")]}
# An invoice of another order, which names nothing of this one.
ANOTHERS = testkit.text_pdf(["Invoice", "Order # 999-8887776-6655544", "2026-01-31",
                             "Invented Folding Chair", "Invented seller of somebody else"])


@pytest.fixture(autouse=True)
def default_names():
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def listed() -> Purchase:
    """The order as discovery lists it, afresh for each run."""
    return Purchase(purchase_type=ONLINE, purchase_date=DATE, order_number=ORDER,
                    total="$30.00", items=[Item(name=ITEM)])


class Tab:
    url = "https://www.amazon.com/gp/your-account/order-details?orderID=" + ORDER
    context = None

    def evaluate(self, *a, **k):
        return {}


def run(tmp_path, monkeypatch, links, answers=None, **config):
    """One run of the app over the order, a process of its own on the same
    output folder. Amazon's menu lists `links`, and each answers with its
    bytes, or with what `answers` gives for it, False for a refusal or an
    exception to raise. `redownload` is the panel's Download again. Returns
    the app and the links it asked for."""
    again = config.pop("redownload", False)
    app = testkit.receipt_app(app_mod, tmp_path, **config)
    app.args.redownload = again
    site = app_mod.site
    asked = []
    answers = dict(answers or {})

    def download(page, url, out_path):
        asked.append(url)
        said = answers.get(url, BODIES.get(url))
        if isinstance(said, BaseException):
            raise said
        if said is False:
            return False
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(said)
        return True

    monkeypatch.setattr(site, "goto_details", lambda page, purchase: None)
    monkeypatch.setattr(site, "extract_details", lambda page, purchase: purchase)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "not_this_purchase", lambda page, order: "")
    monkeypatch.setattr(site, "order_canceled", lambda page, status="": False)
    monkeypatch.setattr(site, "find_invoice_pdf_links",
                        lambda page, order: [("Invoice %d" % i, u)
                                             for i, u in enumerate(links, start=1)])
    monkeypatch.setattr(site, "download_invoice_pdf", download)
    monkeypatch.setattr(app, "check_session", lambda page: False)
    monkeypatch.setattr(app, "page", lambda: Tab())
    app._journal = MagicMock()
    app.process_purchases([listed()])
    return app, asked


def stored(app) -> dict:
    """The order's record as it is on disk."""
    return json.loads(app.paths.progress_json.read_text(encoding="utf-8"))[listed().key]


def name(k: int, n: int = 3, summary: str = "Garden Supplies") -> str:
    """The name the app gives invoice k of n under the default pattern."""
    return str(core_storage.build_pdf_filename(DATE, summary, "Invoice", part=(k, n),
                                               record=listed()))


def on_disk(app) -> dict:
    """Each file below the online folder, by its name, with its bytes."""
    return {p.name: p.read_bytes() for p in app.paths.online.rglob("*") if p.is_file()}


def in_review(app) -> dict:
    return {p.name: p.read_bytes() for p in app.paths.manual_review.rglob("*") if p.is_file()}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- one that did not come ------------------------------------------------------

def test_an_invoice_that_did_not_come_leaves_the_order_to_be_asked_again(tmp_path, monkeypatch):
    app, asked = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    purchase = listed()
    rec = stored(app)
    assert rec.get("downloaded_ok") is False, "invoice 2 of 3 never came, and the order is done for good"
    assert not app._already_done(purchase)
    assert rec["state"] == State.FAILED.value
    assert asked == LINKS
    assert on_disk(app) == {name(1): BODIES[LINKS[0]], name(3): BODIES[LINKS[2]]}
    entries = rec["invoices"]
    assert [(Path(e["file"]).name, e["part"], e["kept"]) for e in entries] == [
        (name(1), "1 of 3", True), (name(3), "3 of 3", True)]
    assert [e["sha256"] for e in entries] == [sha(BODIES[LINKS[0]]), sha(BODIES[LINKS[2]])]
    assert all(e["size"] == len(BODIES[u]) and e["pages"] == 1
               for e, u in zip(entries, (LINKS[0], LINKS[2])))
    assert "invoice 2 of 3" in rec["notes"] and "tried again next run" in rec["notes"]
    assert app.stats["failed"] == 1 and app.stats["receipts_downloaded"] == 0
    assert sorted(Path(p).name for p in app.stats["new_files"]) == [name(1), name(3)]
    assert app.index_csv.read_all() == [] and app.order_csv.read_all() == []


def test_the_next_run_asks_only_for_the_invoice_that_did_not_come(tmp_path, monkeypatch, capsys):
    run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == [LINKS[1]]
    assert on_disk(app) == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}
    assert not any(ORDER in n or " (2)" in n for n in on_disk(app))
    rows = app.index_csv.read_all()
    assert len(rows) == 1 and rows[0]["PDF Filename"] == name(1), rows
    assert rows[0]["Receipt Count"] == "3"
    assert len(app.order_csv.read_all()) == 1
    rec = stored(app)
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"] is True
    assert rec["receipt_count"] == 3
    assert rec["notes"].startswith("Also saved: %s, %s" % (name(2), name(3))), rec["notes"]
    assert [Path(e["file"]).name for e in rec["invoices"]] == [name(1), name(2), name(3)]
    # Every invoice of the order is new to the run that completed it, those
    # the first run saved included, so the panel's Move after it takes the
    # order whole (test_a_move_of_what_the_run_saved_takes_the_order_whole).
    assert sorted(Path(p).name for p in app.stats["new_files"]) == [name(1), name(2), name(3)]
    assert len(app.stats["new_files"]) == 3
    assert app.stats["failed"] == 0 and app.stats["receipts_downloaded"] == 1
    assert app._already_done(listed())


def test_an_invoice_deleted_between_runs_is_not_fetched_again(tmp_path, monkeypatch):
    """A saved invoice counts as saved after its file is deleted, the
    promise every download makes."""
    first, _ = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    (first.paths.online / name(1)).unlink()
    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == [LINKS[1]]
    assert set(on_disk(app)) == {name(2), name(3)}
    assert stored(app)["downloaded_ok"] is True


def test_the_first_link_refused_saves_nothing_as_before(tmp_path, monkeypatch, capsys):
    app, asked = run(tmp_path, monkeypatch, LINKS, {LINKS[0]: False})
    assert "Invoice PDF download failed" in capsys.readouterr().out
    rec = stored(app)
    assert rec["state"] == State.FAILED.value and not rec.get("downloaded_ok")
    assert "Invoice PDF download failed" in rec["notes"]
    assert app.stats["failed"] == 1
    assert asked == [LINKS[0]] and on_disk(app) == {}


def test_an_order_of_one_invoice_is_named_and_written_as_before(tmp_path, monkeypatch):
    app, asked = run(tmp_path, monkeypatch, LINKS[:1])
    plain = str(core_storage.build_pdf_filename(DATE, "Garden Supplies", "Invoice",
                                                record=listed()))
    assert "1 of 1" not in plain
    assert on_disk(app) == {plain: BODIES[LINKS[0]]}
    rec = stored(app)
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"] is True
    assert rec["receipt_count"] == 1 and "Also saved" not in rec["notes"]
    rows = app.index_csv.read_all()
    assert len(rows) == 1 and rows[0]["PDF Filename"] == plain


# -- a run stopped between two invoices -------------------------------------------

def test_a_run_stopped_between_two_invoices_leaves_the_order_to_finish(tmp_path, monkeypatch):
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, monkeypatch, LINKS, {LINKS[1]: KeyboardInterrupt()})
    app = testkit.receipt_app(app_mod, tmp_path)
    rec = stored(app)
    assert rec.get("downloaded_ok") is not True, "the run stopped at invoice 2 of 3, and the order is done for good"
    assert not app._already_done(listed())
    assert [Path(e["file"]).name for e in rec["invoices"]] == [name(1)]
    assert set(on_disk(app)) == {name(1)}, "no copy is left at a name of its own"

    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == LINKS[1:]
    assert on_disk(app) == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}
    assert stored(app)["downloaded_ok"] is True


# -- one that failed its check ------------------------------------------------------

def test_an_invoice_that_fails_its_check_is_put_aside_and_counted(tmp_path, monkeypatch, capsys):
    app, asked = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: ANOTHERS})
    assert (app.stats["manual_review"], app.stats["validation_failures"]) == (1, 1), \
        "an invoice put aside in Manual Review is counted"
    assert in_review(app) == {name(2): ANOTHERS}
    assert on_disk(app) == {name(1): BODIES[LINKS[0]], name(3): BODIES[LINKS[2]]}
    rec = stored(app)
    assert [(Path(e["file"]).name, e["kept"]) for e in rec["invoices"]] == [
        (name(1), True), (name(2), False), (name(3), True)]
    assert Path(rec["invoices"][1]["file"]).parent.name == "Manual Review"
    assert rec["state"] == State.COMPLETED.value and rec["downloaded_ok"] is True
    assert rec["receipt_count"] == 2
    assert rec["notes"].startswith("Also saved: %s" % name(3)), rec["notes"]
    assert "Put aside in Manual Review: %s" % name(2) in rec["notes"]
    assert "Manual Review" in capsys.readouterr().out
    # Nothing is asked again, the one put aside is on file while its copy is.
    _again, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == []


def test_a_lone_invoice_that_fails_its_check_is_put_aside_as_before(tmp_path, monkeypatch,
                                                                     capsys):
    app, asked = run(tmp_path, monkeypatch, LINKS[:1], {LINKS[0]: ANOTHERS})
    plain = str(core_storage.build_pdf_filename(DATE, "Garden Supplies", "Invoice",
                                                record=listed()))
    assert in_review(app) == {plain: ANOTHERS} and on_disk(app) == {}
    rec = stored(app)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value and not rec.get("downloaded_ok")
    assert rec["notes"].startswith("PDF validation failed: "), rec["notes"]
    assert (app.stats["manual_review"], app.stats["validation_failures"]) == (1, 1)
    rows = app.index_csv.read_all()
    assert [r["Receipt Status"] for r in rows] == ["Validation Failed"]
    assert "moved to Manual Review" in capsys.readouterr().out
    # Done while its copy is there, as a receipt put aside is.
    assert app._already_done(listed())


def test_one_put_aside_whose_copy_is_deleted_is_fetched_again(tmp_path, monkeypatch):
    """As Target's are. The copy in Manual Review is all there is of it."""
    first, _ = run(tmp_path, monkeypatch, LINKS, {LINKS[0]: ANOTHERS, LINKS[1]: False})
    assert in_review(first) == {name(1): ANOTHERS}
    (first.paths.manual_review / name(1)).unlink()
    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == LINKS[:2]
    assert on_disk(app) == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}
    rec = stored(app)
    assert rec["downloaded_ok"] is True and rec["pdf_filename"] == name(1)
    assert [(Path(e["file"]).name, e["kept"]) for e in rec["invoices"]] == [
        (name(1), True), (name(2), True), (name(3), True)]


def test_an_invoice_that_cannot_be_put_aside_is_not_left_where_it_came(tmp_path, monkeypatch,
                                                                         capsys):
    """Moving it to Manual Review raised. The run goes on, says it could not
    put the invoice aside rather than that it did, keeps no copy of it under
    a name, and the next run fetches it again. The refusal is stood in for
    at shared_folder.move, which puts every invoice in place."""
    real = app_mod.shared_folder.move

    def move(src, target):
        if Path(target).parent.name == "Manual Review":
            raise PermissionError(13, "Access is denied", str(target))
        return real(src, target)

    monkeypatch.setattr(app_mod.shared_folder, "move", move)
    app, asked = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: ANOTHERS})
    said = capsys.readouterr().out
    rec = stored(app)
    assert "Unhandled error" not in rec["notes"], rec["notes"]
    assert "moved to Manual Review" not in said and "Put aside in Manual Review" not in said
    assert rec.get("downloaded_ok") is False and not app._already_done(listed())
    assert "invoice 2 of 3" in rec["notes"]
    assert on_disk(app) == {name(1): BODIES[LINKS[0]], name(3): BODIES[LINKS[2]]}
    assert in_review(app) == {}
    monkeypatch.setattr(app_mod.shared_folder, "move", real)
    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == [LINKS[1]]
    assert on_disk(app) == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}


# -- a menu that lists another number --------------------------------------------

def test_a_menu_that_lists_one_more_saves_no_invoice_twice(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    four = LINKS + [link("a1b2-credit-note")]
    app, _asked = run(tmp_path, monkeypatch, four)
    files = on_disk(app)
    assert len(set(files.values())) == len(files) == 4, sorted(files)
    assert files[name(1)] == BODIES[LINKS[0]] and files[name(3)] == BODIES[LINKS[2]]
    assert sorted(files.values()) == sorted(BODIES[u] for u in four)
    rec = stored(app)
    listed_files = [e["file"] for e in rec["invoices"]]
    assert len(listed_files) == len(set(listed_files)) == 4
    assert rec["downloaded_ok"] is True and rec["receipt_count"] == 4


def test_a_menu_whose_invoices_moved_saves_none_twice(tmp_path, monkeypatch):
    """The same three, in another order. The first fetched is one on file
    already, so every place is asked, and only the one not on file is kept,
    under the place left for it."""
    run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    moved = [LINKS[1], LINKS[0], LINKS[2]]
    app, asked = run(tmp_path, monkeypatch, moved)
    assert asked[0] == LINKS[0] and sorted(asked) == sorted(LINKS)
    assert on_disk(app) == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}
    assert stored(app)["downloaded_ok"] is True


# -- Download again ---------------------------------------------------------------

def test_a_download_again_that_misses_one_names_what_it_saved(tmp_path, monkeypatch):
    """An order saved whole before, its files deleted since, and the second
    link refused this time. The record names every file the attempt saved,
    and a plain run after it saves no second copy of any."""
    first, _ = run(tmp_path, monkeypatch, LINKS)
    for k in (1, 2, 3):
        (first.paths.online / name(k)).unlink()
    app, asked = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False}, redownload=True)
    assert asked == LINKS
    assert set(on_disk(app)) == {name(1), name(3)}
    rec = stored(app)
    named = {Path(e["file"]).name for e in rec["invoices"]}
    assert set(on_disk(app)) <= named
    after, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == [] and set(on_disk(after)) == {name(1), name(3)}


def test_a_download_again_of_an_order_on_file_saves_no_second_copy(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, LINKS)
    app, asked = run(tmp_path, monkeypatch, LINKS, redownload=True)
    assert asked == [] and set(on_disk(app)) == {name(1), name(2), name(3)}
    assert stored(app)["downloaded_ok"] is True
    # Nothing fetched, so nothing is new. The run that completes an order
    # lists every invoice of it, and a Download again over one done before
    # listed all three (a review of 2026-11-15).
    assert app.stats["new_files"] == []


def test_a_download_again_that_fetches_a_deleted_invoice_lists_that_one(tmp_path, monkeypatch):
    first, _ = run(tmp_path, monkeypatch, LINKS)
    (first.paths.online / name(2)).unlink()
    app, asked = run(tmp_path, monkeypatch, LINKS, redownload=True)
    assert asked == [LINKS[1]]
    assert [Path(p).name for p in app.stats["new_files"]] == [name(2)]


def test_a_staging_file_the_move_refuses_is_asked_for_again(tmp_path, monkeypatch):
    """On PaperPull Server shared_folder.move refuses a link or a second
    name put at the staging name after the download, so it is never carried
    into place. The invoice is then not on file, and the next run asks for
    it again. A plain replace carried it into place (a release review of
    2026-11-15)."""
    real = app_mod.shared_folder.move

    def refusing(src, dst):
        if Path(src).name.endswith("-2.pdf.delivering"):
            raise OSError(22, "not a plain file of its own", str(src))
        return real(src, dst)

    monkeypatch.setattr(app_mod.shared_folder, "move", refusing)
    first, _ = run(tmp_path, monkeypatch, LINKS)
    assert name(2) not in on_disk(first)
    assert stored(first)["downloaded_ok"] is False
    assert not list(first.paths.online.glob("*.delivering")), "the staging file is left behind"
    monkeypatch.setattr(app_mod.shared_folder, "move", real)
    app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == [LINKS[1]] and on_disk(app)[name(2)] == BODIES[LINKS[1]]
    assert stored(app)["downloaded_ok"] is True


# -- Rename -------------------------------------------------------------------------

def test_a_rename_waits_for_the_order_and_then_takes_every_invoice(tmp_path, monkeypatch):
    first, _ = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False})
    before = on_disk(first)
    app = testkit.receipt_app(app_mod, tmp_path, filename_pattern=NUMBERED)
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    assert on_disk(app) == before, "no row names the order's files yet"

    app, asked = run(tmp_path, monkeypatch, LINKS, filename_pattern=NUMBERED)
    assert asked == [LINKS[1]]
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    numbered = {str(core_storage.build_pdf_filename(DATE, "Garden Supplies", "Invoice",
                                                    part=(k, 3), record=listed())): k
                for k in (1, 2, 3)}
    assert {n: on_disk(app)[n] for n in numbered} == {
        n: BODIES[LINKS[k - 1]] for n, k in numbered.items()}, (sorted(on_disk(app)), said)
    assert set(on_disk(app)) == set(numbered)
    said = []
    renaming.run_for(app, apply_changes=True, say=said.append)
    assert DONE in "\n".join(said), said


def test_a_move_of_what_the_run_saved_takes_the_order_whole(tmp_path, monkeypatch):
    """After a run the panel moves what new-this-run.txt lists into the
    documents folder. The run that completed an order listed only the
    invoice it fetched, so the Move took that one and left the invoices of
    the earlier run, the one the index row names among them, behind (a
    review of 2026-11-15)."""
    watched = str(tmp_path / "Watched")
    first, _ = run(tmp_path, monkeypatch, LINKS, {LINKS[1]: False}, documents_dir=watched)
    app, asked = run(tmp_path, monkeypatch, LINKS, documents_dir=watched)
    assert asked == [LINKS[1]]
    files = sorted(app.stats["new_files"])
    (app.paths.root / "new-this-run.txt").write_text(
        "# %d file(s) downloaded on this run:\n" % len(files) + "\n".join(files) + "\n",
        encoding="utf-8")
    mover = testkit.receipt_app(app_mod, tmp_path, documents_dir=watched)
    monkeypatch.setenv(renaming.MOVE_DOCUMENTS_ENV, "new")
    said = []
    renaming.run_for(mover, apply_changes=True, say=said.append)
    moved = {p.name: p.read_bytes() for p in Path(watched).rglob("*") if p.is_file()}
    assert moved == {name(k): BODIES[LINKS[k - 1]] for k in (1, 2, 3)}, (moved, said)
    assert on_disk(app) == {}, "an invoice of the order stayed behind"


def test_a_record_an_older_version_left_is_still_done(tmp_path, monkeypatch):
    """Up to 0.66.0 an order's other invoices were named in its notes
    alone. Such a record is done, and a run asks nothing of it."""
    app = testkit.receipt_app(app_mod, tmp_path)
    purchase = listed()
    app.progress.update(purchase.key, dict(purchase.to_dict(), state=State.COMPLETED.value,
                                           downloaded_ok=True,
                                           pdf_path=str(app.paths.online / name(1)),
                                           notes="Also saved: %s" % name(2)))
    assert app._already_done(listed())
    _app, asked = run(tmp_path, monkeypatch, LINKS)
    assert asked == []
