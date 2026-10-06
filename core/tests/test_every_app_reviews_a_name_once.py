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
files.

These run each app's own review_names over an output folder on disk, with
the typing stood in for. Every name, number and answer is invented.
"""
import importlib
import sys
from pathlib import Path

import pytest

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
    __init__, which would want a config file and a console."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240}
    inst.paths = storage.Paths(out)
    inst.paths.ensure()
    inst.progress = storage.JsonStore(inst.paths.progress_json)
    inst.discovery = storage.JsonStore(inst.paths.discovery_json)
    inst.index_csv = storage.CsvFile(inst.paths.receipt_index_csv,
                                     storage.RECEIPT_INDEX_COLUMNS)
    inst.order_csv = storage.CsvFile(inst.paths.order_history_csv,
                                     storage.ORDER_HISTORY_COLUMNS)
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
    """Of eleven rows the run was unsure of, three name a receipt in a
    folder the app files receipts in, and only those are offered. The rest
    name no file, the folder the app runs in, the output folder itself, a
    receipt reached by climbing out of it, one somewhere else, one no longer
    on disk, the app's own config file in an output folder set to the app's
    folder, and a PDF in Logs. The second receipt offered cannot be
    renamed, which is said, and the review goes on to its end with the CSVs
    naming every file as it now is. Every question is answered with a new
    name, so a row offered by mistake would be renamed, and it would show."""
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
    rows = [index_row("ORDER-0001", first),
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
            index_row("ORDER-0011", last)]
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
    assert {"here": everything_under(here), "elsewhere": everything_under(elsewhere)} == before
    assert {p: p.read_bytes() for p in kept} == kept
    assert "It could not be renamed (PermissionError), so it keeps its name." in said, said
    garden = [p for p in filed.iterdir() if "Garden Hose" in p.name]
    lamp = [p for p in inst.paths.manual_review.iterdir() if "Lamp" in p.name]
    assert len(garden) == len(lamp) == 1 and not first.exists() and not last.exists(), said
    names = [r["PDF Filename"] for r in rows]
    paths = [r["PDF Full Path"] for r in rows]
    names[0], names[-1] = garden[0].name, lamp[0].name
    paths[0], paths[-1] = str(garden[0]), str(lamp[0])
    index = inst.index_csv.read_all()
    assert [r["PDF Filename"] for r in index] == names
    assert [r["PDF Full Path"] for r in index] == paths
    assert [r["PDF Filename"] for r in inst.order_csv.read_all()] == names


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
@pytest.mark.parametrize("stop, ends", [(EOFError, SystemExit),
                                        (KeyboardInterrupt, KeyboardInterrupt)],
                         ids=["console gone", "ctrl c"])
def test_a_review_cut_short_still_writes_down_what_it_renamed(app, stop, ends, tmp_path,
                                                               monkeypatch):
    """The console goes away at the second question, which the app's own ask
    answers by stopping, or the person presses Ctrl+C there. The first
    receipt is renamed on disk, and both CSVs name it as it now is."""
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

    def console(prompt=""):
        for line in typed:
            return line
        raise stop
    monkeypatch.setattr("builtins.input", console)

    with pytest.raises(ends):
        inst.cmd_review_names()

    garden = [p.name for p in filed.iterdir() if "Garden Hose" in p.name]
    assert len(garden) == 1 and not first.exists() and second.is_file()
    assert [r["PDF Filename"] for r in inst.index_csv.read_all()] == [garden[0], second.name]
    assert [r["PDF Filename"] for r in inst.order_csv.read_all()] == [garden[0], second.name]
