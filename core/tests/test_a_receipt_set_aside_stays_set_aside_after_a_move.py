"""A receipt set aside stays set aside on another computer.

A receipt whose page showed nothing on three separate days is set aside as
No Receipt Available, and the record keeps those days (not_shown_days).
Meijer holds the purchase final only while the record holds three days,
since Meijer does not take No Receipt Available as final otherwise, and
every receipt app's skip line says a purchase set aside was skipped for
that, by the days too. tools/migrate.py --minimal carried only the fields
it listed, which left the days out, so on the new computer Meijer asked
for every receipt set aside again and the other apps said each one was
"Already completed and PDF verified", the words a tester was told for a
receipt never saved (#70). An import into an install that already knew
the purchase took the state and left the days behind, the same way.

These set a purchase aside with each receipt app's own downloader over an
output folder on disk, three days of the core's tried_again, move the
history with the tool and ask the app's own _already_done and the core's
skip line on the new computer. Every name and number is invented.
"""
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from paperpull_core import not_shown
from paperpull_core.models import State

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
migrate = pytest.importorskip("migrate")

# The census beside this file, for its stand-in run of each receipt app.
_CENSUS = Path(__file__).with_name("test_every_receipt_app_asks_again_for_a_receipt_not_shown.py")
_spec = importlib.util.spec_from_file_location("not_shown_census", _CENSUS)
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)

OTHERWISE = "  Already completed and PDF verified - skipping."
SAID = "did not show on %d separate days" % not_shown.DAYS


def install(root: Path, app: Path, records: dict = None) -> Path:
    """An output folder the tool takes for an install of this app, its own
    storage.py beside its progress.json."""
    out = root / app.name
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(app / "storage.py", out / "storage.py")
    if records is not None:
        (out / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    return out


def set_aside(mod, out: Path):
    """The purchase's receipt page shows nothing on three separate days,
    through the app's own _record_state. The third day's run saved another
    purchase's receipt first, as a run must before it sets one aside (#225)."""
    for day in range(1, not_shown.DAYS + 1):
        tried(mod, out, day, saved_first=day == not_shown.DAYS)
    p = census.purchase()
    rec = census.app_in(mod, out).progress.get(p.key)
    assert not_shown.set_aside(rec), rec
    return p


def tried(mod, out: Path, day: int, saved_first: bool = False):
    """One run on that day, whose receipt page shows nothing. A new run
    reads the purchase afresh, as a run does from discovery."""
    p = census.purchase()
    inst = census.app_in(mod, out, day=day)
    inst.discovery.update(p.key, p.to_dict())
    if saved_first:
        census.save_another(inst)
    not_shown.tried_again(inst, p, "The receipt page did not show the receipt")
    return inst


def asked_after_the_move(mod, new: Path, p):
    inst = census.app_in(mod, new)
    rec = inst.progress.get(p.key)
    return bool(inst._already_done(p)), not_shown.skipped(rec, OTHERWISE), rec


@pytest.mark.parametrize("minimal", [True, False], ids=["minimal", "whole"])
@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_a_receipt_set_aside_is_not_asked_for_again_on_a_new_computer(app, minimal, tmp_path,
                                                                       capsys):
    mod = census.load(app)
    p = set_aside(mod, install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=minimal) == 0

    install(tmp_path / "new", app, {})
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    capsys.readouterr()

    done, said, rec = asked_after_the_move(mod, tmp_path / "new" / app.name, p)
    assert done, "%s asks again for a receipt set aside on the old computer, %r" % (app.name, rec)
    assert SAID in said, (app.name, said, rec)


@pytest.mark.parametrize("minimal", [True, False], ids=["minimal", "whole"])
@pytest.mark.parametrize("app", census.APPS, ids=census.IDS)
def test_an_import_into_an_install_that_tried_once_brings_the_days(app, minimal, tmp_path,
                                                                    capsys):
    """The new computer ran once before the history came across, and its
    page showed nothing that day too. The import finishes the record as
    the old computer did, days and all."""
    mod = census.load(app)
    p = set_aside(mod, install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    assert migrate.export(tmp_path / "old", archive, minimal=minimal) == 0

    new = install(tmp_path / "new", app)
    inst = tried(mod, new, 40)
    assert inst.progress.get(p.key)["state"] == State.FAILED.value
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0
    capsys.readouterr()

    done, said, rec = asked_after_the_move(mod, new, p)
    assert rec["state"] == State.NO_RECEIPT_AVAILABLE.value, rec
    assert done, "%s asks again for a receipt set aside on the old computer, %r" % (app.name, rec)
    assert SAID in said, (app.name, said, rec)


def test_the_minimal_export_carries_the_days_and_nothing_more_of_the_purchase(tmp_path):
    """The days are dates the page showed nothing, and they travel. What
    the purchase was, its order number, summary and total, still does not."""
    app = next(a for a in census.APPS if a.name == "meijer")
    mod = census.load(app)
    p = set_aside(mod, install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    migrate.export(tmp_path / "old", archive, minimal=True)
    with zipfile.ZipFile(archive) as z:
        recs = json.loads(z.read("apps/meijer/progress.json").decode("utf-8"))
    rec = recs[p.key]
    assert len(rec[not_shown.DAYS_KEY]) == not_shown.DAYS, rec
    blob = json.dumps(rec)
    for revealing in (p.summary, p.total, "The receipt page did not show"):
        assert revealing not in blob, (revealing, rec)


def test_an_older_note_on_this_install_does_not_outlast_an_import_that_set_it_aside(tmp_path):
    """This install recorded the purchase as 0.44.0 did, No Receipt
    Available with words that have it asked for again. The old computer set
    it aside. The import finishes it, and the old words go with the state
    they were written with."""
    app = next(a for a in census.APPS if a.name == "kroger")
    mod = census.load(app)
    p = set_aside(mod, install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    migrate.export(tmp_path / "old", archive, minimal=True)

    gave_up = dict(p.to_dict(), state=State.NO_RECEIPT_AVAILABLE.value,
                   notes="Listed by an invented step; Kroger could not load this receipt")
    new = install(tmp_path / "new", app, {p.key: gave_up})
    assert not census.app_in(mod, new)._already_done(p), "asked for again before the import"
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0

    done, said, rec = asked_after_the_move(mod, new, p)
    assert done, rec
    assert SAID in said, (said, rec)
    assert rec["notes"] == "Listed by an invented step", "the notes before it stay"


@pytest.mark.parametrize("name", ["kroger", "meijer"])
def test_an_export_from_before_the_days_does_not_finish_a_receipt_asked_for_again(name,
                                                                                tmp_path):
    """The 0.44.0 tool's --minimal export carried no notes, so its record of
    a receipt that version gave up on reads as No Receipt Available and
    nothing more. This install has the same purchase with the words that
    have it asked for again, and it is still asked for after the import."""
    app = next(a for a in census.APPS if a.name == name)
    mod = census.load(app)
    p = census.purchase()
    install(tmp_path / "old", app, {p.key: {"state": State.NO_RECEIPT_AVAILABLE.value,
                                            "pdf_path": ""}})
    archive = tmp_path / "history.ppz"
    migrate.export(tmp_path / "old", archive, minimal=True)

    note = "Listed by an invented step; Receipt page did not show a receipt"
    new = install(tmp_path / "new", app, {p.key: dict(
        p.to_dict(), state=State.NO_RECEIPT_AVAILABLE.value, notes=note)})
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0

    rec = census.app_in(mod, new).progress.get(p.key)
    assert rec["notes"] == note, rec
    assert not census.app_in(mod, new)._already_done(p), rec


@pytest.mark.parametrize("state", [State.PDF_VERIFIED.value, State.COMPLETED.value])
def test_a_receipt_saved_here_keeps_its_record_when_the_old_computer_set_it_aside(state,
                                                                                   tmp_path):
    """Saved on this computer, set aside on the old one. Nothing of the
    set-aside record comes across, so the skip line still says it is done."""
    app = next(a for a in census.APPS if a.name == "meijer")
    mod = census.load(app)
    p = set_aside(mod, install(tmp_path / "old", app))
    archive = tmp_path / "history.ppz"
    migrate.export(tmp_path / "old", archive, minimal=True)

    saved = dict(census.purchase().to_dict(), state=state, downloaded_ok=True,
                 notes="Saved by an invented step", **{not_shown.DAYS_KEY: []})
    new = install(tmp_path / "new", app, {p.key: saved})
    assert migrate.do_import(archive, tmp_path / "new", assume_yes=True) == 0

    done, said, rec = asked_after_the_move(mod, new, p)
    assert done, rec
    assert said == OTHERWISE, said
    assert (rec["state"], rec["notes"], rec[not_shown.DAYS_KEY]) == (
        state, "Saved by an invented step", []), rec


@pytest.mark.parametrize("provider", ["target", "github", "meijer"])
def test_an_import_recorded_as_having_none_for_another_reason_brings_no_days(provider, tmp_path):
    """A purchase tried again here keeps three days while no receipt of its
    kind was saved before it (#225). The old computer recorded the same
    purchase as having no receipt for what the provider showed, a Target
    order with only an invoice or a GitHub payment with no receipt link,
    which carries no days. The import takes that state, and the days here go
    with the state they belonged to, so the record is never read as one set
    aside for pages that showed nothing (review of #225)."""
    days = ["2031-01-02", "2031-01-03", "2031-01-04"]
    here = {"k": {"state": State.FAILED.value,
                  "notes": "Neither a receipt nor an invoice showed, tried again next run",
                  not_shown.DAYS_KEY: list(days)}}
    there = {"k": {"state": State.NO_RECEIPT_AVAILABLE.value,
                   "notes": "No printable receipt available"}}
    migrate._merge(here, there, [], tmp_path, tmp_path, provider=provider)
    rec = here["k"]
    assert rec["state"] == State.NO_RECEIPT_AVAILABLE.value, rec
    assert not (rec.get(not_shown.DAYS_KEY) or []), rec
    assert not not_shown.set_aside(rec), rec
    assert not_shown.skipped(rec, OTHERWISE) == OTHERWISE

    # A purchase the old computer set aside for pages that showed nothing
    # brings its own days, and stays set aside.
    here = {"k": {"state": State.FAILED.value, "notes": "tried again next run",
                  not_shown.DAYS_KEY: list(days[:1])}}
    there = {"k": {"state": State.NO_RECEIPT_AVAILABLE.value,
                   "notes": "Receipt page did not render on 3 separate days, so it is not "
                            "asked for again",
                   not_shown.DAYS_KEY: list(days)}}
    migrate._merge(here, there, [], tmp_path, tmp_path, provider=provider)
    assert not_shown.set_aside(here["k"]), here["k"]
