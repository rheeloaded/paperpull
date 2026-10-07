"""A name a person has fixed is not asked about again (#47), and Review
Names renames nothing but a receipt the app holds.

review_names asks about each receipt whose name the app was unsure of, the
rows of the index marked Low or Review. Renaming one set its status to
Completed and left its confidence Low, so the next review asked about every
receipt already renamed, in all thirteen receipt apps, while the tester
expected only the ones he had kept as they were.

It also offered every such row, and a row written for a purchase with no
receipt file has an empty path, which reads as the folder the app runs in.
A new name typed for one had the app rename that folder. Windows refuses,
since the folder is in use, and so does any other system, since the new
name is inside the old, so the review stopped with a traceback partway
through. The receipts renamed before it were renamed on disk and in
progress.json, while the CSVs, written only at the end, still named the old
files. Closing the console window partway, which ends the process with
nothing run after it, left every rename of that review out of them.

A receipt whose PDF failed its check is put aside in Manual Review, one of
the folders the review offers receipts from. A new name for it marked it
Completed, so no run fetched it again, though its copy was still the one
that failed. A new name for an older copy of a purchase was written into
the purchase's record as well, which changed what the next run fetched.

These run each app's own review_names over an output folder on disk, with
the typing stood in for. Every name, number and answer is invented.
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

import pytest

from paperpull_core.models import ONLINE, Purchase, State

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d)
              and "def cmd_review_names" in entry_of(d).read_text(encoding="utf-8"))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


@pytest.fixture(autouse=True)
def default_names():
    """Files named the default way, whatever a test before this one chose."""
    from paperpull_core import storage
    storage.set_filename_owner("")
    storage.set_filename_patterns({})
    yield
    storage.set_filename_patterns({})


def app_in(mod, out: Path):
    """The app's own downloader over an output folder on disk, without its
    __init__, which would want a config file and a console. Its stores and
    CSVs keep their backups in Backups, as the app's own do."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240}
    inst.paths = storage.Paths(out)
    inst.paths.ensure()
    backups = inst.paths.backups
    inst.progress = storage.JsonStore(inst.paths.progress_json, backups)
    inst.discovery = storage.JsonStore(inst.paths.discovery_json, backups)
    inst.index_csv = storage.CsvFile(inst.paths.receipt_index_csv,
                                     storage.RECEIPT_INDEX_COLUMNS, backups)
    inst.order_csv = storage.CsvFile(inst.paths.order_history_csv,
                                     storage.ORDER_HISTORY_COLUMNS, backups)
    return inst


def receipt(folder: Path, name: str) -> Path:
    """A receipt of invented bytes, saved where the test says."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.4\n% invented receipt\n%%EOF\n")
    return path


def index_row(number: str, path, status: str = "Review Needed") -> dict:
    """An index row as a run writes one for a receipt it was unsure of.
    `path` is written as it is given, so "" and "." are rows as a run
    wrote them, not files."""
    text = str(path)
    return {"Purchase Date": "2026-05-14", "Purchase Type": "Online",
            "Order or Receipt Number": number,
            "PDF Filename": Path(text).name if text else "", "PDF Full Path": text,
            "Document Type": "Receipt", "Classification Confidence": "Low",
            "Processing Status": status, "Notes": ""}


def order_row(number: str, name: str) -> dict:
    return {"Purchase Date": "2026-05-14", "Purchase Type": "Online",
            "Order or Receipt Number": number, "Item Name": "Invented Item",
            "PDF Filename": name, "Processing Status": "Review Needed"}


def everything_under(folder: Path) -> dict:
    """Every file and folder below `folder`, each file with its bytes."""
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in folder.rglob("*")}


def runnable(mod, out: Path):
    """app_in, with what the app's own skip decision reads as well, the
    smallest PDF it takes and the command line."""
    inst = app_in(mod, out)
    inst.config["min_pdf_bytes"] = 2000
    inst.args = argparse.Namespace(redownload=False)
    return inst


def opening_pdf(folder: Path, name: str) -> Path:
    """A one page PDF of invented words that opens and is larger than the
    smallest the app takes. A copy put aside that passes this much counts
    as done while it is there, as one does that failed only on its words."""
    from pypdf import PdfWriter
    folder.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 200})
    path = folder / name
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def as_a_run_left_it(inst, number: str, path: Path, saved: bool, confidence: str):
    """A receipt's records, written by the app's own _record_state and
    _write_csv_rows in the order its run writes them. A receipt saved
    passed its check and was marked for review for its name alone. One not
    saved failed its check and was put aside in Manual Review."""
    purchase = Purchase(purchase_type=ONLINE, purchase_date="2026-05-14",
                        order_number=number, summary="Unsure Purchase",
                        confidence=confidence, pdf_path=str(path), pdf_filename=path.name)
    inst._record_state(purchase, State.PDF_SAVED)
    if saved:
        inst._record_state(purchase, State.PDF_VERIFIED, extra={
            "pdf_size": path.stat().st_size, "pdf_pages": 1, "downloaded_ok": True})
        inst._write_csv_rows(purchase, receipt_status="Downloaded",
                             processing_status="Review Needed")
        inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                           notes="Low classification confidence")
    else:
        inst._record_state(purchase, State.NEEDS_MANUAL_REVIEW,
                           notes="PDF validation failed, an invented reason")
        inst._write_csv_rows(purchase, receipt_status="Validation Failed",
                             processing_status=State.NEEDS_MANUAL_REVIEW.value,
                             notes_extra="Validation, an invented reason")
    return purchase


def test_every_receipt_app_is_covered():
    assert len(APPS) >= 14, [a.name for a in APPS]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_renamed_receipt_is_not_asked_about_again(app, tmp_path, monkeypatch, capsys):
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    filed = inst.paths.folder_for("Online")
    inst.index_csv.append_rows([
        index_row("ORDER-0001", receipt(filed, "2026-05-14 Unsure Receipt.pdf")),
        index_row("ORDER-0002", receipt(filed, "2026-05-14 Other Receipt.pdf"))])

    answers = iter(["Garden Hose", ""])          # rename the first, keep the second
    monkeypatch.setattr(mod, "ask", lambda prompt: next(answers))
    inst.cmd_review_names()
    renamed = [r for r in inst.index_csv.read_all()
               if r["Order or Receipt Number"] == "ORDER-0001"][0]
    assert "Garden Hose" in renamed["PDF Filename"]

    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "")
    inst.cmd_review_names()
    assert len(asked) == 1, "only the receipt kept as it was is asked about again"
    assert "ORDER-0002" in capsys.readouterr().out.split("need review")[-1]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_receipt_renamed_before_the_fix_is_not_asked_about_either(app, tmp_path, monkeypatch):
    """The tester's archive, renamed on 0.39.0, still says Low beside each
    name he fixed. The note every rename leaves is what tells them apart."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    old = index_row("ORDER-0003", receipt(inst.paths.folder_for("Online"),
                                          "2026-05-14 Gas Station Receipt.pdf"))
    old.update({"Processing Status": "Completed", "Notes": "renamed via --review-names"})
    inst.index_csv.append_rows([old])
    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "")
    inst.cmd_review_names()
    assert asked == []


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_only_a_receipt_the_app_holds_is_renamed(app, tmp_path, monkeypatch, capsys):
    """Of fourteen rows, three name a receipt in a folder the app files
    receipts in, and each is offered once, though a second row the run was
    unsure of names the first. Eight are left out, and the review says so.
    They name no file, the folder the app runs in, the output folder
    itself, a receipt reached by climbing out of it, one somewhere else,
    one no longer on disk, the app's own config file in an output folder
    set to the app's folder, and a PDF in Logs. The second receipt offered
    cannot be renamed, which is said, and the review goes on to its end.
    Every row of a purchase naming its renamed file follows it, a finished
    one included, and a finished row of another purchase naming the same
    file is left as it is. The CSVs and progress.json name every file as it
    now is, and each CSV is backed up once. Every question is answered with
    a new name, so a row offered by mistake would be renamed, and it would
    show."""
    mod = load(app)
    here = tmp_path / "here"                     # the folder the app runs in
    receipt(here, "2026-05-14 Here Receipt.pdf")
    monkeypatch.chdir(here)
    elsewhere = tmp_path / "elsewhere"
    outside = receipt(elsewhere, "2026-05-14 Elsewhere Receipt.pdf")
    climbed = receipt(elsewhere, "2026-05-14 Climbed Receipt.pdf")
    out = tmp_path / "out"
    inst = app_in(mod, out)
    filed = inst.paths.folder_for("Online")      # where the app files an online purchase
    first = receipt(filed, "2026-05-14 First Receipt.pdf")
    locked = receipt(filed, "2026-05-14 Locked Receipt.pdf")
    last = receipt(inst.paths.manual_review, "2026-05-14 Last Receipt.pdf")
    config = out / "config.json"
    config.write_text('{"owner": "Dana Example"}', encoding="utf-8")
    logged = receipt(inst.paths.logs, "2026-05-14 Logged Receipt.pdf")
    finished = index_row("ORDER-0011", last, status="Completed")
    finished["Classification Confidence"] = "High"
    another = index_row("ORDER-0012", first, status="Completed")
    another["Classification Confidence"] = "High"
    rows = [index_row("ORDER-0001", first),
            index_row("ORDER-0001", first),      # a second row for the one file
            index_row("ORDER-0002", "", status="Needs Manual Review"),
            index_row("ORDER-0003", "."),
            index_row("ORDER-0004", out),
            index_row("ORDER-0005", inst.paths.manual_review / ".." / ".." / "elsewhere"
                      / climbed.name),
            index_row("ORDER-0006", outside),
            index_row("ORDER-0007", filed / "2026-05-14 Gone Receipt.pdf"),
            index_row("ORDER-0008", config),
            index_row("ORDER-0009", logged),
            index_row("ORDER-0010", locked),
            index_row("ORDER-0011", last),
            finished,
            another]                             # another purchase naming the first's file
    inst.index_csv.append_rows(rows)
    inst.order_csv.append_rows([order_row(r["Order or Receipt Number"], r["PDF Filename"])
                                for r in rows])
    before = {"here": everything_under(here), "elsewhere": everything_under(elsewhere)}
    kept = {p: p.read_bytes() for p in (config, logged, locked)}

    real = Path.rename

    def rename(self, target):
        if self.name == locked.name:
            raise PermissionError(13, "The file is open in another program")
        return real(self, target)
    monkeypatch.setattr(Path, "rename", rename)
    answers = ["Garden Hose", "Hardware", "Lamp"]
    asked = []

    def answer(prompt):
        asked.append(prompt)
        return answers[len(asked) - 1] if len(asked) <= len(answers) else "Extra %d" % len(asked)
    monkeypatch.setattr(mod, "ask", answer)

    inst.cmd_review_names()                      # it finishes, with no traceback

    said = " ".join(capsys.readouterr().out.split())
    assert len(asked) == 3, "only the three receipts the app holds are offered, %s" % said
    assert ("8 row(s) marked for review have no receipt PDF in this app's folders to "
            "rename, so they are left out." in said), said
    assert {"here": everything_under(here), "elsewhere": everything_under(elsewhere)} == before
    assert {p: p.read_bytes() for p in kept} == kept
    assert "It could not be renamed (PermissionError), so it keeps its name." in said, said
    garden = [p for p in filed.iterdir() if "Garden Hose" in p.name]
    lamp = [p for p in inst.paths.manual_review.iterdir() if "Lamp" in p.name]
    assert len(garden) == len(lamp) == 1 and not first.exists() and not last.exists(), said
    names = [r["PDF Filename"] for r in rows]
    paths = [r["PDF Full Path"] for r in rows]
    for i, now in ((0, garden[0]), (1, garden[0]), (11, lamp[0]), (12, lamp[0])):
        names[i], paths[i] = now.name, str(now)
    index = inst.index_csv.read_all()
    assert [r["PDF Filename"] for r in index] == names
    assert [r["PDF Full Path"] for r in index] == paths
    assert [r["PDF Filename"] for r in inst.order_csv.read_all()] == names
    assert [i for i, r in enumerate(index) if "renamed via --review-names" in r["Notes"]] \
        == [0, 1, 11, 12]
    progress = json.loads(inst.paths.progress_json.read_text(encoding="utf-8"))
    assert {key: record["pdf_filename"] for key, record in progress.items()} \
        == {"Online:ORDER-0001": garden[0].name, "Online:ORDER-0011": lamp[0].name}
    assert sorted(p.name.split(".")[0] for p in inst.paths.backups.iterdir()) \
        == sorted([inst.index_csv.path.stem, inst.order_csv.path.stem])


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
@pytest.mark.parametrize("trouble", ["ctrl c in a write", "progress fails", "index locked"])
def test_a_rename_is_written_down_when_writing_it_goes_wrong(app, trouble, tmp_path,
                                                            monkeypatch):
    """Something goes wrong after the first receipt is renamed. Ctrl+C lands
    while the index is written, saving progress.json fails, or the index
    stays open in another program. The review stops with that error, and
    the CSVs name the file as it now is, the order history even when the
    index cannot be written."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    filed = inst.paths.folder_for("Online")
    first = receipt(filed, "2026-05-14 First Receipt.pdf")
    second = receipt(filed, "2026-05-14 Second Receipt.pdf")
    inst.index_csv.append_rows([index_row("ORDER-0001", first),
                                index_row("ORDER-0002", second)])
    inst.order_csv.append_rows([order_row("ORDER-0001", first.name),
                                order_row("ORDER-0002", second.name)])
    csv_class, index_path = type(inst.index_csv), inst.index_csv.path
    real_rewrite = csv_class.rewrite
    index_writes = []

    def rewrite(self, rows, *args, **kwargs):
        if self.path == index_path:
            index_writes.append(len(rows))
            if trouble == "index locked":
                raise PermissionError(13, "The file is open in another program")
            if trouble == "ctrl c in a write" and len(index_writes) == 1:
                raise KeyboardInterrupt
        return real_rewrite(self, rows, *args, **kwargs)
    monkeypatch.setattr(csv_class, "rewrite", rewrite)
    if trouble == "progress fails":
        def update(key, record, save=True):
            raise PermissionError(13, "progress.json is open in another program")
        monkeypatch.setattr(inst.progress, "update", update)
    monkeypatch.setattr(mod, "ask", lambda prompt: "Garden Hose")

    with pytest.raises(KeyboardInterrupt if trouble == "ctrl c in a write"
                       else PermissionError):
        inst.cmd_review_names()

    garden = [p.name for p in filed.iterdir() if "Garden Hose" in p.name]
    assert len(garden) == 1 and not first.exists() and second.is_file()
    assert [r["PDF Filename"] for r in inst.order_csv.read_all()] == [garden[0], second.name]
    if trouble != "index locked":
        assert [r["PDF Filename"] for r in inst.index_csv.read_all()] == [garden[0], second.name]


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_link_to_a_receipt_is_not_offered(app, tmp_path, monkeypatch):
    """A row naming a link, outside the app's folders, to a receipt inside
    them. A rename would move the link, which is not the app's to move."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    held = receipt(inst.paths.folder_for("Online"), "2026-05-14 Held Receipt.pdf")
    link = tmp_path / "elsewhere" / "2026-05-14 Linked Receipt.pdf"
    link.parent.mkdir()
    try:
        link.symlink_to(held)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let a test make a link")
    inst.index_csv.append_rows([index_row("ORDER-0001", link)])
    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "Garden Hose")
    inst.cmd_review_names()
    assert asked == [] and link.is_symlink() and held.is_file()


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
@pytest.mark.parametrize("stop, ends", [(EOFError, SystemExit),
                                        (KeyboardInterrupt, KeyboardInterrupt)],
                         ids=["console gone", "ctrl c"])
def test_a_review_cut_short_has_written_down_what_it_renamed(app, stop, ends, tmp_path,
                                                              monkeypatch):
    """The console goes away at the second question, which the app's own ask
    answers by stopping, or the person presses Ctrl+C there. Closing the
    console window there instead ends the process with nothing run after
    it, so both CSVs already name the first receipt as it now is when the
    second question is asked, and still do once the review has stopped."""
    mod = load(app)
    inst = app_in(mod, tmp_path / "out")
    filed = inst.paths.folder_for("Online")
    first = receipt(filed, "2026-05-14 First Receipt.pdf")
    second = receipt(filed, "2026-05-14 Second Receipt.pdf")
    inst.index_csv.append_rows([index_row("ORDER-0001", first),
                                index_row("ORDER-0002", second)])
    inst.order_csv.append_rows([order_row("ORDER-0001", first.name),
                                order_row("ORDER-0002", second.name)])
    typed = iter(["Garden Hose"])
    on_disk = []

    def written_down():
        return ([r["PDF Filename"] for r in inst.index_csv.read_all()],
                [r["PDF Filename"] for r in inst.order_csv.read_all()])

    def console(prompt=""):
        for line in typed:
            return line
        on_disk.append(written_down())          # what a closed window would leave
        raise stop
    monkeypatch.setattr("builtins.input", console)

    with pytest.raises(ends):
        inst.cmd_review_names()

    garden = [p.name for p in filed.iterdir() if "Garden Hose" in p.name]
    assert len(garden) == 1 and not first.exists() and second.is_file()
    now = ([garden[0], second.name], [garden[0], second.name])
    assert on_disk == [now], "written down before the second question"
    assert written_down() == now


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_completes_only_a_receipt_that_was_saved(app, tmp_path, monkeypatch):
    """A receipt whose PDF failed its check is put aside in Manual Review
    as Needs Manual Review, with no downloaded_ok. The next run fetches it
    again when its copy fails the check, and when its copy opens it is
    kept as done until the person deletes it, which is how Meijer and
    Walmart tell a person to ask for it again. A new name for it marked it
    Completed, in progress.json and both CSVs, and after that no run
    fetched it, whatever became of its copy. Uber names every receipt
    itself, so these are the only receipts its review offers.

    A receipt saved and marked for review for its name alone has
    downloaded_ok, and Completed is what a new name is for. All three are
    renamed in one review, a receipt put aside first and last, so nothing
    one rename decides carries over to the next. Each skip is the app's
    own _already_done."""
    mod = load(app)
    inst = runnable(mod, tmp_path / "out")
    assert callable(getattr(inst, "_already_done", None)), \
        "a run decides what to fetch again in _already_done"
    aside, filed = inst.paths.manual_review, inst.paths.folder_for(ONLINE)
    failed = as_a_run_left_it(inst, "ORDER-0001",
                              receipt(aside, "2026-05-14 Failed Receipt.pdf"),
                              saved=False, confidence="High")
    saved = as_a_run_left_it(inst, "ORDER-0002",
                             opening_pdf(filed, "2026-05-14 Saved Receipt.pdf"),
                             saved=True, confidence="Low")
    kept = as_a_run_left_it(inst, "ORDER-0003",
                            opening_pdf(aside, "2026-05-14 Kept Receipt.pdf"),
                            saved=False, confidence="Low")
    receipts = (failed, saved, kept)
    assert [inst._already_done(p) for p in receipts] == [False, True, True], \
        "as a run leaves them, only the copy that fails its check is fetched again"

    answers = iter(["Garden Hose", "Hardware", "Lamp"])
    monkeypatch.setattr(mod, "ask", lambda prompt: next(answers))
    inst.cmd_review_names()

    def renamed(folder, word):
        found = [p for p in folder.iterdir() if word in p.name]
        assert len(found) == 1, sorted(p.name for p in folder.iterdir())
        return found[0]
    garden, hardware, lamp = renamed(aside, "Garden Hose"), renamed(filed, "Hardware"), \
        renamed(aside, "Lamp")
    assert [inst._already_done(p) for p in receipts] == [False, True, True], \
        "a new name changes nothing a run fetches"
    progress = json.loads(inst.paths.progress_json.read_text(encoding="utf-8"))
    assert {p.key: (progress[p.key]["state"], progress[p.key].get("downloaded_ok"),
                    progress[p.key]["summary"], progress[p.key]["pdf_path"])
            for p in receipts} == {
        failed.key: ("Needs Manual Review", None, "Garden Hose", str(garden)),
        saved.key: ("Completed", True, "Hardware", str(hardware)),
        kept.key: ("Needs Manual Review", None, "Lamp", str(lamp))}
    statuses = {"ORDER-0001": "Needs Manual Review", "ORDER-0002": "Completed",
                "ORDER-0003": "Needs Manual Review"}
    for csv in (inst.index_csv, inst.order_csv):
        assert {r["Order or Receipt Number"]: r["Processing Status"]
                for r in csv.read_all()} == statuses, csv.path.name

    asked = []
    monkeypatch.setattr(mod, "ask", lambda prompt: asked.append(prompt) or "Extra")
    inst.cmd_review_names()
    assert asked == [], "a receipt renamed is not offered again"

    hardware.unlink()
    lamp.unlink()
    assert [inst._already_done(p) for p in (saved, kept)] == [True, False], \
        "a receipt saved stays done once its file is deleted, a copy put aside does not"


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_a_new_name_for_an_older_copy_leaves_the_record_alone(app, tmp_path, monkeypatch):
    """A purchase's record says what a run fetches, and it names the copy
    the last run left. An older copy keeps rows of its own, which the
    review offers. Here one was put aside before a later run saved the
    receipt, one before a newer copy that opens was put aside as well, and
    one before a later run found a page that was another purchase's and
    kept nothing. A new name for the older copy was written into the
    record as well. That moved the first record off the receipt saved and
    marked the failed copy's rows Completed, had the next run fetch a third
    copy of the second, and stopped the third from being fetched again.
    Only the older copy's rows take its new name now."""
    mod = load(app)
    inst = runnable(mod, tmp_path / "out")
    aside, filed = inst.paths.manual_review, inst.paths.folder_for(ONLINE)
    as_a_run_left_it(inst, "ORDER-0001", receipt(aside, "2026-05-14 First Receipt.pdf"),
                     saved=False, confidence="High")
    later = as_a_run_left_it(inst, "ORDER-0001",
                             opening_pdf(filed, "2026-05-14 Saved Receipt.pdf"),
                             saved=True, confidence="Low")
    as_a_run_left_it(inst, "ORDER-0002", receipt(aside, "2026-05-14 Small Receipt.pdf"),
                     saved=False, confidence="High")
    newer = as_a_run_left_it(inst, "ORDER-0002",
                             opening_pdf(aside, "2026-05-14 Newer Receipt.pdf"),
                             saved=False, confidence="High")
    as_a_run_left_it(inst, "ORDER-0003", opening_pdf(aside, "2026-05-14 Kept Receipt.pdf"),
                     saved=False, confidence="High")
    refused = Purchase(purchase_type=ONLINE, purchase_date="2026-05-14",
                       order_number="ORDER-0003")
    inst._record_state(refused, State.NEEDS_MANUAL_REVIEW,
                       notes="The page was another purchase's")
    purchases = (later, newer, refused)
    records = json.loads(inst.paths.progress_json.read_text(encoding="utf-8"))
    assert [inst._already_done(p) for p in purchases] == [True, True, False]

    # Each older copy is renamed and each copy a record names is kept.
    answers = iter(["Garden Hose", "", "Hardware", "", "Lamp"])
    monkeypatch.setattr(mod, "ask", lambda prompt: next(answers))
    inst.cmd_review_names()

    assert [inst._already_done(p) for p in purchases] == [True, True, False], \
        "a new name for an older copy changes nothing a run fetches"
    assert json.loads(inst.paths.progress_json.read_text(encoding="utf-8")) == records
    index = inst.index_csv.read_all()
    assert [(r["Order or Receipt Number"], r["Processing Status"]) for r in index] == [
        ("ORDER-0001", "Needs Manual Review"), ("ORDER-0001", "Review Needed"),
        ("ORDER-0002", "Needs Manual Review"), ("ORDER-0002", "Needs Manual Review"),
        ("ORDER-0003", "Needs Manual Review")]
    assert [word in r["PDF Filename"] for r, word in zip(
        index, ["Garden Hose", "Saved", "Hardware", "Newer", "Lamp"])] == [True] * 5
    assert [r["Processing Status"] for r in inst.order_csv.read_all()] == [
        r["Processing Status"] for r in index]
