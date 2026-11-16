"""A document saved and checked stays saved while its index is open in Excel.

On Windows, Excel holds a CSV it has open so that nobody else can write it.
Every app writes a saved document's row into its index after it has
recorded the document done, and the append gave up at once with
PermissionError. The app's handler for the document then recorded it
Failed, still marked downloaded, so no later run asked for it again, its
row was never written, and Rename, Review Names, Verify and the panel's
move to a documents folder never reached the file. A receipt app appends
its order history before its receipt index, so a held order history lost
the index row too.

Now an append waits the minute a write waits for a held file, once in a
run for each file, and then keeps the rows it could not write beside the
file, in the output folder, and writes them in at the first chance the file
is free. The document stays saved, and the run says so and says what waits.

Chase stands for the document apps and Lowe's for the receipt apps, each
built from its own code with a made-up config and output folder
(test_every_app_renames_each_file_for_its_own_record.Home), only the site
and the tab stood in for. On Windows the file is held open the way Excel
holds it (test_rename_with_a_ledger_held_open.held_like_excel), and on
every system a write is refused where Windows refuses it. Every name and
number is invented.
"""
import ast
import csv
import errno
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from paperpull_core import run_reporting, shared_folder, storage as core_storage, testkit
from paperpull_core.models import Item, Purchase, State

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402
from test_rename_with_a_ledger_held_open import held_like_excel  # noqa: E402

REPO = census.REPO
INDEX = "Chase Document Index.csv"
LOWES_HISTORY = "Lowe's Order History.csv"

on_windows = pytest.mark.skipif(os.name != "nt", reason="Windows is where a file Excel has "
                                "open cannot be written by anyone else")


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


panel = _module("paperpull_panel_run_result_ledger", REPO / "gui" / "run_result.py")


def rows_in(path: Path) -> list:
    """The rows the file itself holds, read the way the panel and the
    spreadsheet tools read it, and nothing kept beside it."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pauses(monkeypatch) -> list:
    """Each pause a wait for a held file takes, without the pause. An app's
    own pause between documents is none here, since Home sets it to 0."""
    paused = []
    monkeypatch.setattr("time.sleep", lambda s: paused.append(s) if s else None)
    return paused


class Refused:
    """Every open of one file for writing refused, as Windows refuses it
    while Excel holds the file, until `lifted`. Each refusal is counted."""

    def __init__(self, monkeypatch, path: Path, error=None, modes=("w", "a")):
        self.path = os.path.normcase(os.path.abspath(str(path)))
        self.error = error or (lambda p: PermissionError(
            errno.EACCES, "The process cannot access the file because it is being used by "
            "another process", str(p)))
        self.modes = modes
        self.times = 0
        self.lifted = False
        real = shared_folder.open_to_write

        def open_to_write(p, mode="w", encoding=None, newline=None):
            if (not self.lifted and mode[:1] in self.modes
                    and os.path.normcase(os.path.abspath(str(p))) == self.path):
                self.times += 1
                raise self.error(p)
            return real(p, mode, encoding=encoding, newline=newline)

        monkeypatch.setattr(shared_folder, "open_to_write", open_to_write)


def files_beside(folder: Path) -> list:
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def way_out(app):
    """The end of a download run as the app's own main ends one, its run
    state saved and its summary written, which writes the result line."""
    app.stats["mode"] = "all"
    app.progress.save(leaving=True)
    app.discovery.save(leaving=True)
    app.write_run_summary()


# -- Chase ------------------------------------------------------------------------------

class Tab:
    url = "https://secure.chase.com/"
    context = None

    def evaluate(self, *_a, **_kw):
        return {}


def chase(tmp_path, monkeypatch, capsys, **settings):
    """Chase with its site stood in, saving a PDF that passes its check."""
    home = census.Home(REPO / "apps" / "chase", tmp_path, monkeypatch, capsys)
    if settings:
        home.config.update(settings)
        home._write_config()
    site = sys.modules["chase_site"]
    body = testkit.sample_pdf()

    def chase_download(page, ctx, account, date, out_path, *_a, **_kw):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(body)
        return True

    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "chase_download", chase_download)
    monkeypatch.setattr(home.mod.App, "check_session", lambda self, page: None)
    monkeypatch.setattr(home.mod.App, "_on_its_site", lambda self: Tab())
    return home


def statements(home, n: int = 1) -> list:
    """`n` monthly statements of one card, the newest first."""
    Document = home.mod.Document
    category = (home.config.get("document_types") or ["Statement"])[0]
    return [Document(title="Statement 2026-%02d-12" % month, category=category,
                     summary="Monthly Statement", date="2026-%02d-12" % month,
                     account="CARD (...1234)", document_id="DOC%04d" % month)
            for month in range(9, 9 - n, -1)]


def one_line_saying(text: str, *words) -> list:
    return [line for line in text.splitlines() if all(w in line for w in words)]


def saved_and_counted(app, docs) -> list:
    """Every document is saved, recorded done for good, counted among what
    the run saved and in its kind's count, and none failed."""
    for doc in docs:
        rec = app.progress.get(doc.key)
        assert (rec["state"], rec.get("downloaded_ok")) == ("Completed", True), rec
    assert app.stats["failed"] == 0, app.stats
    saved = [Path(p) for p in app.stats["new_files"]]
    assert len(saved) == len(docs) and all(p.is_file() for p in saved), saved
    assert app.stats["statements"] == len(docs), app.stats
    return saved


@on_windows
def test_a_statement_saved_while_excel_has_the_index_open_is_saved(tmp_path, monkeypatch,
                                                                  capsys):
    home = chase(tmp_path, monkeypatch, capsys)
    app = home.build()
    paused = pauses(monkeypatch)
    doc, = statements(home)
    app.index_csv._ensure_header()
    index = app.index_csv.path
    capsys.readouterr()
    with held_like_excel(index):
        app.process([doc])
        held_rows = rows_in(index)
    said = capsys.readouterr().out
    saved, = saved_and_counted(app, [doc])
    assert paused == [2] * 30, "it waits the minute a write waits"
    assert said.count("is open in another program") == 1, said
    assert one_line_saying(said, INDEX, "is open in another program"), said
    assert "Saved: %s" % saved.name in said, said
    assert held_rows == [], "nothing was written into the file Excel holds"
    way_out(app)
    rows = rows_in(index)
    assert [r["PDF Full Path"] for r in rows] == [str(saved)], rows
    assert app._already_done(doc)


@pytest.mark.parametrize("error", [
    lambda p: PermissionError(errno.EACCES, "Permission denied", str(p)),
    lambda p: OSError(errno.EBUSY, "Device or resource busy", str(p)),
], ids=["refused", "busy"])
def test_a_statement_saved_while_its_index_refuses_writes_is_saved(tmp_path, monkeypatch,
                                                                  capsys, error):
    """The same on every system, the index refused where Windows refuses it
    to a program while Excel holds it, or busy as a shared folder may say
    of a file open on another computer."""
    home = chase(tmp_path, monkeypatch, capsys)
    app = home.build()
    doc, = statements(home)
    app.index_csv._ensure_header()
    index = app.index_csv.path
    refused = Refused(monkeypatch, index, error)
    capsys.readouterr()
    app.process([doc])
    said = capsys.readouterr().out
    assert refused.times >= 1, "the index was never refused, so this proves nothing"
    saved, = saved_and_counted(app, [doc])
    assert "Saved: %s" % saved.name in said, said
    assert rows_in(index) == []
    refused.lifted = True
    way_out(app)
    assert [r["PDF Full Path"] for r in rows_in(index)] == [str(saved)]
    assert app._already_done(doc)


@on_windows
def test_five_statements_wait_one_minute_in_all(tmp_path, monkeypatch, capsys):
    home = chase(tmp_path, monkeypatch, capsys)
    app = home.build()
    paused = pauses(monkeypatch)
    docs = statements(home, 5)
    app.index_csv._ensure_header()
    index = app.index_csv.path
    capsys.readouterr()
    with held_like_excel(index):
        app.process(docs)
        way_out(app)
        held_rows = rows_in(index)
    said = capsys.readouterr().out
    saved = saved_and_counted(app, docs)
    assert held_rows == []
    assert paused == [2] * 30, "each document waited its own minute"
    assert said.count("is open in another program") == 1, said
    assert len(one_line_saying(said, "5 rows", INDEX)) == 1, said
    # Closed now, and the next command of the app writes them in.
    assert len(home.build().index_csv.read_all()) == 5
    assert sorted(r["PDF Full Path"] for r in rows_in(index)) == sorted(map(str, saved))


def run_all(home, docs, monkeypatch, mark: str):
    """Run All through the app's own main, the list it reads being `docs`,
    its exit code and what it printed."""
    def discover(self, quiet=False, finish=True):
        for doc in docs:
            listed = doc.to_dict()
            listed["state"] = State.DISCOVERED.value
            self.discovery.update(doc.key, listed, save=False)
        return len(docs)

    monkeypatch.setattr(home.mod.App, "cmd_discover", discover)
    monkeypatch.setenv(run_reporting.MARK_ENV, mark)
    home.capsys.readouterr()
    try:
        code = home.mod.main(["--config", str(home.cfg), "--all", "--yes"])
    except SystemExit as stop:
        code = stop.code
    return code, home.capsys.readouterr().out


def result_of(out: str, mark: str) -> dict:
    found = [panel.parse(line, mark) for line in out.splitlines()]
    found = [r for r in found if r is not None]
    assert len(found) == 1, out[-1500:]
    return found[0]


@on_windows
def test_a_run_that_ends_with_the_index_still_open_finishes(tmp_path, monkeypatch, capsys):
    """Excel is still open when the run ends. The run finished and says so,
    the panel is told how many rows wait, the rows are kept past the run,
    and once Excel is closed a Rename reaches every file."""
    home = chase(tmp_path, monkeypatch, capsys)
    paused = pauses(monkeypatch)
    docs = statements(home, 5)
    index = home.build().index_csv
    index._ensure_header()
    mark = "a1" * 16
    with held_like_excel(index.path):
        code, out = run_all(home, docs, monkeypatch, mark)
        assert rows_in(index.path) == []
        kept = home.build().index_csv.read_all()
    assert code == 0, out[-1500:]
    result = result_of(out, mark)
    assert (result["failed"], result["new_files"], result["stopped"]) == (0, 5, 0), result
    assert result["rows_waiting"] == 5 and result["attention"], result
    assert paused == [2] * 30
    assert len(kept) == 5, "the rows kept did not outlive the run"
    saved = sorted(home.out.rglob("*.pdf"))
    assert len(saved) == 5, saved
    home.set_pattern(census.PATTERN)
    said = home.rename()
    assert "5 file(s) would be renamed." in said, said[-1500:]
    for path in saved:
        assert path.name in said, (path.name, said[-1500:])


@on_windows
def test_a_holder_that_lets_others_write_takes_the_row_at_once(tmp_path, monkeypatch, capsys):
    """A program that lets others read and write a file but not delete it
    keeps it from being replaced, and an append still goes through."""
    home = chase(tmp_path, monkeypatch, capsys)
    app = home.build()
    paused = pauses(monkeypatch)
    doc, = statements(home)
    app.index_csv._ensure_header()
    index = app.index_csv.path
    with held_like_excel(index, share=3):
        app.process([doc])
        held_rows = rows_in(index)
    saved, = saved_and_counted(app, [doc])
    assert [r["PDF Full Path"] for r in held_rows] == [str(saved)]
    assert paused == []
    assert set(files_beside(home.out)) <= {INDEX, "progress.json", "discovery.json"}, (
        files_beside(home.out))


def test_rows_waiting_are_kept_beside_their_ledger_and_nowhere_a_ledger_is_looked_for(
        tmp_path, monkeypatch, capsys):
    """Never in the documents folder, which another program may watch, and
    never under a name the panel or a spreadsheet tool takes for a ledger."""
    documents = tmp_path / "Watched"
    home = chase(tmp_path, monkeypatch, capsys, documents_dir=str(documents))
    app = home.build()
    doc, = statements(home)
    app.index_csv._ensure_header()
    before = set(files_beside(home.out))
    Refused(monkeypatch, app.index_csv.path)
    app.process([doc])
    saved_and_counted(app, [doc])
    kept = set(files_beside(home.out)) - before - {"progress.json", "discovery.json"}
    assert len(kept) == 1, "the row was kept nowhere beside the index"
    assert not documents.exists() or not [p for p in documents.rglob("*") if p.is_file()]
    assert sorted(p.name for p in home.out.glob("* Index.csv")) == [INDEX]
    assert not list(home.out.glob("* Order History.csv"))
    assert sorted(p.name for p in home.out.glob("* Document Index.csv")) == [INDEX]


def test_rows_are_never_kept_through_a_link_on_the_server(tmp_path, monkeypatch):
    """On PaperPull Server a link left at the name the rows are kept under
    is replaced, never written through. A second name of a file outside
    stands in for the link, as it does in test_shared_folder_links_and_pipes."""
    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    canary = tmp_path / "config" / "server.json"
    canary.parent.mkdir()
    canary.write_text('{"password": "MARKER-31c9"}\n', encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    columns = ["Document Date", "PDF Full Path", "Processing Status"]
    ledger = core_storage.CsvFile(install / "Testco Document Index.csv", columns, once=True)
    ledger._ensure_header()
    Refused(monkeypatch, ledger.path)
    before = set(files_beside(install))
    ledger.append_rows([{"Document Date": "2026-09-12", "PDF Full Path": "a.pdf",
                         "Processing Status": "Completed"}])
    kept = sorted(set(files_beside(install)) - before)
    assert len(kept) == 1, files_beside(install)
    (install / kept[0]).unlink()
    os.link(canary, install / kept[0])
    ledger.append_rows([{"Document Date": "2026-08-12", "PDF Full Path": "b.pdf",
                         "Processing Status": "Completed"}])
    assert canary.read_text(encoding="utf-8") == '{"password": "MARKER-31c9"}\n'
    assert os.stat(install / kept[0]).st_nlink == 1


def test_a_second_persons_rows_are_kept_in_their_own_folder(tmp_path, monkeypatch, capsys):
    """Two people on one install, the second's output folder written as the
    panel writes it, beside the install. Only the second's index is refused."""
    home = chase(tmp_path, monkeypatch, capsys)
    install = tmp_path / "Chase Statements"
    install.mkdir()
    first = dict(home.config, output_dir=".")
    (install / "config.json").write_text(json.dumps(first), encoding="utf-8")
    second = dict(home.config, output_dir="../Chase Statements - Robin", owner="Robin Example")
    robin_cfg = install / "config.robin.json"
    robin_cfg.write_text(json.dumps(second), encoding="utf-8")
    monkeypatch.chdir(install)
    mine = home.mod.App(home.mod.build_parser().parse_args(["--config", "config.json"]))
    mine.index_csv._ensure_header()
    mine_before = sorted(str(p.relative_to(install)) for p in install.rglob("*"))
    mine_index = mine.index_csv.path.resolve().read_bytes()
    robin = home.mod.App(home.mod.build_parser().parse_args(["--config", str(robin_cfg)]))
    robin.index_csv._ensure_header()
    robin_folder = robin.index_csv.path.resolve().parent
    assert robin_folder == (tmp_path / "Chase Statements - Robin").resolve()
    before = set(files_beside(robin_folder))
    Refused(monkeypatch, robin.index_csv.path)
    doc, = statements(home)
    robin.process([doc])
    rec = robin.progress.get(doc.key)
    assert (rec["state"], rec.get("downloaded_ok")) == ("Completed", True), rec
    assert len(set(files_beside(robin_folder)) - before
               - {"progress.json", "discovery.json"}) == 1
    assert sorted(str(p.relative_to(install)) for p in install.rglob("*")) == mine_before
    assert mine.index_csv.path.resolve().read_bytes() == mine_index


def test_a_run_state_and_an_index_both_refused_on_the_way_out_are_both_said(
        tmp_path, monkeypatch, capsys):
    """The run state not written still makes the run one that stopped, and
    the rows that wait are said besides. Neither hides the other."""
    home = chase(tmp_path, monkeypatch, capsys)
    app = home.build()
    doc, = statements(home)
    app.index_csv._ensure_header()
    Refused(monkeypatch, app.index_csv.path)
    app.process([doc])
    # A change the run left to its save on the way out, as Golden 1's
    # carried titles are.
    app.progress.data[doc.key]["checked_at"] = "2026-09-12T10:00:00"
    progress = str(app.paths.progress_json)
    real = core_storage.atomic_write_json

    def write(path, data, **how):
        if str(path) == progress:
            raise PermissionError(errno.EACCES, "held", progress)
        return real(path, data, **how)

    monkeypatch.setattr(core_storage, "atomic_write_json", write)
    mark = "b2" * 16
    monkeypatch.setenv(run_reporting.MARK_ENV, mark)
    capsys.readouterr()
    way_out(app)
    out = capsys.readouterr().out
    result = result_of(out, mark)
    assert result["stopped"] == 1 and result["rows_waiting"] == 1, result
    assert "run state could not be written" in out, out
    assert len(one_line_saying(out, "1 row", INDEX)) == 1, out


# -- Lowe's ------------------------------------------------------------------------------

# Each purchase's items, all of which Lowe's classifies with confidence.
ITEMS = {"123456781": ["Garden Hose 50 ft", "Interior Paint 1 gal"],
         "123456782": ["Cordless Drill 20V"],
         "123456783": ["Lumber 2x4x8", "Garden Hose 50 ft"],
         "123456784": ["Interior Paint 1 gal"],
         "123456785": ["Cordless Drill 20V", "Lumber 2x4x8"]}


def lowes(tmp_path, monkeypatch, capsys):
    """Lowe's with its site stood in, each purchase's details page showing
    its own items and its receipt saying its own number."""
    home = census.Home(REPO / "apps" / "lowes", tmp_path, monkeypatch, capsys)
    site = sys.modules["lowes_site"]
    shown = {}

    def goto_details(page, p):
        shown["p"] = p

    def extract(page, p):
        p.items = [Item(name=name, quantity="1", line_total="$10.00")
                   for name in ITEMS[p.order_number]]
        return p

    def capture(self, page, p, out):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(testkit.text_pdf(
            ["Order # %s" % p.order_number, "September 12, 2026"] + ITEMS[p.order_number]
            + ["Total Billed %s" % p.total]))

    monkeypatch.setattr(site, "goto_details", goto_details)
    monkeypatch.setattr(site, "extract_details", extract)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "on_details_page", lambda page: True)
    monkeypatch.setattr(site, "scroll_full_page", lambda page: None)
    monkeypatch.setattr(site, "receipt_is_present", lambda page: True)
    monkeypatch.setattr(site, "details_number", lambda page: shown["p"].order_number)
    monkeypatch.setattr(home.mod.App, "check_session", lambda self, page: False)
    monkeypatch.setattr(home.mod.App, "page", lambda self: Tab())
    monkeypatch.setattr(home.mod.App, "_capture_document", capture)
    return home


def purchases(*numbers) -> list:
    return [Purchase(purchase_type="Online", purchase_date="2026-09-12", order_number=n,
                     total="$%d.00" % (10 * len(ITEMS[n]))) for n in numbers]


def each_once(rows, numbers, items: bool) -> None:
    """Each purchase is in the rows once, by each of its items for an order
    history, and nothing else is."""
    got = sorted((r["Order or Receipt Number"], r["Item Name"] if items else "") for r in rows)
    want = sorted((n, name if items else "") for n in numbers
                  for name in (ITEMS[n] if items else [""]))
    assert got == want, got


def receipts_saved(app, bought) -> None:
    for p in bought:
        rec = app.progress.get(p.key)
        assert (rec["state"], rec.get("downloaded_ok")) == ("Completed", True), rec
    assert app.stats["failed"] == 0, app.stats
    assert app.stats["receipts_downloaded"] == len(bought), app.stats
    assert len(app.stats["new_files"]) == len(bought)


@on_windows
def test_a_receipt_saved_while_excel_has_its_index_open_is_saved(tmp_path, monkeypatch,
                                                                capsys):
    home = lowes(tmp_path, monkeypatch, capsys)
    app = home.build()
    pauses(monkeypatch)
    bought = purchases("123456781")
    app.index_csv._ensure_header()
    with held_like_excel(app.index_csv.path):
        app.process_purchases(bought)
        assert rows_in(app.index_csv.path) == []
    receipts_saved(app, bought)
    each_once(rows_in(app.order_csv.path), ["123456781"], items=True)
    way_out(app)
    each_once(rows_in(app.index_csv.path), ["123456781"], items=False)
    each_once(rows_in(app.order_csv.path), ["123456781"], items=True)


@on_windows
def test_an_order_history_open_in_excel_keeps_nothing_from_the_index(tmp_path, monkeypatch,
                                                                    capsys):
    """The order history is written first, and its refusal used to leave the
    receipt index without its row as well."""
    home = lowes(tmp_path, monkeypatch, capsys)
    app = home.build()
    pauses(monkeypatch)
    bought = purchases("123456781")
    app.order_csv._ensure_header()
    with held_like_excel(app.order_csv.path):
        app.process_purchases(bought)
        assert rows_in(app.order_csv.path) == []
        each_once(rows_in(app.index_csv.path), ["123456781"], items=False)
    receipts_saved(app, bought)
    way_out(app)
    each_once(rows_in(app.order_csv.path), ["123456781"], items=True)
    each_once(rows_in(app.index_csv.path), ["123456781"], items=False)


def test_rows_kept_go_in_once_whatever_comes_after(tmp_path, monkeypatch, capsys):
    """Two purchases' rows kept, both ledgers refused, then two commands
    with both free. Then two more kept, and the run that writes them in
    stopped by Ctrl+C after they were written and before they were
    forgotten, and run again. Each purchase is in each ledger once."""
    home = lowes(tmp_path, monkeypatch, capsys)
    app = home.build()
    app.order_csv._ensure_header()
    app.index_csv._ensure_header()
    refusals = [Refused(monkeypatch, app.order_csv.path),
                Refused(monkeypatch, app.index_csv.path)]
    first = purchases("123456781", "123456782")
    app.process_purchases(first)
    receipts_saved(app, first)
    assert rows_in(app.order_csv.path) == [] and rows_in(app.index_csv.path) == []
    for refused in refusals:
        refused.lifted = True
    home.rename()
    home.rename()
    numbers = ["123456781", "123456782"]
    each_once(rows_in(app.order_csv.path), numbers, items=True)
    each_once(rows_in(app.index_csv.path), numbers, items=False)

    for refused in refusals:
        refused.lifted = False
    app = home.build()
    later = purchases("123456783", "123456784")
    app.process_purchases(later)
    for refused in refusals:
        refused.lifted = True
    forget = core_storage.CsvFile._forget_kept
    stopped = []

    def stopped_once(ledger):
        if not stopped:
            stopped.append(ledger.path.name)
            raise KeyboardInterrupt
        return forget(ledger)

    monkeypatch.setattr(core_storage.CsvFile, "_forget_kept", stopped_once)
    app = home.build()
    with pytest.raises(KeyboardInterrupt):
        app.process_purchases(purchases("123456785"))
    assert stopped, "nothing was stopped, so this proves nothing"
    home.rename()
    home.rename()
    # The purchase being saved when Ctrl+C came may have written its rows
    # or not, as before, and never twice.
    numbers += ["123456783", "123456784"]
    for ledger, items in ((app.order_csv, True), (app.index_csv, False)):
        rows = rows_in(ledger.path)
        each_once([r for r in rows if r["Order or Receipt Number"] != "123456785"], numbers,
                  items=items)
        last = [r for r in rows if r["Order or Receipt Number"] == "123456785"]
        assert len(last) in (0, len(ITEMS["123456785"]) if items else 1), last


# -- every app ---------------------------------------------------------------------------

def ledgers_of(app) -> list:
    """Every ledger the app keeps, found as what it is, never by its name."""
    return [v for v in vars(app).values() if isinstance(v, core_storage.CsvFile)]


def one_written_down(home, app) -> Path:
    """One document or one purchase saved and written down by the app's
    own code."""
    if hasattr(home.mod, "Document"):
        pair = census.two_documents(home)
        if pair is None:
            Document = home.mod.Document
            category = (home.config.get("document_types") or ["Statement"])[0]
            pair = (Document(title=census.TITLE, category=category,
                             summary="Monthly Statement", date=census.DATE,
                             account=census.ACCOUNTS[0]),)
        doc = pair[0]
        census.downloaded(app, doc)
        return Path(doc.pdf_path)
    return census.purchased(home, app, "ORD" + census.ACCOUNTS[0])


def ledgers_declared(app_dir: Path) -> int:
    """How many ledgers an app declares, by the CSV files its spec names."""
    tree = ast.parse((app_dir / "storage.py").read_text(encoding="utf-8-sig"))
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] == "CsvSpec")


LEDGER_CASES = [(d, which) for d in census.APPS for which in range(ledgers_declared(d))]


@pytest.mark.parametrize("app_dir,which", LEDGER_CASES,
                         ids=["%s-%d" % (d.name, w) for d, w in LEDGER_CASES])
def test_every_app_keeps_a_saved_document_saved_while_a_ledger_is_refused(
        app_dir, which, tmp_path, monkeypatch, capsys):
    """Each ledger of each app refused in turn while the app writes down a
    document it saved, by its own code. Nothing is raised into the save, and
    once the ledger is free again the app's Rename finds the file named in
    every ledger once."""
    home = census.Home(app_dir, tmp_path, monkeypatch, capsys)
    app = home.build()
    ledgers = sorted(ledgers_of(app), key=lambda c: c.path.name)
    assert ledgers, "%s keeps no ledger this finds" % app_dir.name
    assert len(ledgers) == ledgers_declared(app_dir), [c.path.name for c in ledgers]
    refused = Refused(monkeypatch, ledgers[which].path)
    try:
        path = one_written_down(home, app)
    except OSError as e:
        pytest.fail("%s raised %r into a saved document" % (app_dir.name, e))
    assert refused.times >= 1, "%s never wrote %s" % (app_dir.name, ledgers[which].path.name)
    recs = [r for r in app.progress.data.values()
            if isinstance(r, dict) and r.get("pdf_path") == str(path)]
    assert recs and all(r.get("downloaded_ok") is True for r in recs), recs
    census.saved(app)
    refused.lifted = True
    said = home.rename()
    for ledger in ledgers:
        rows = rows_in(ledger.path)
        if "PDF Full Path" in ledger.columns:
            named = [r for r in rows if (r.get("PDF Full Path") or "") == str(path)]
        else:
            named = [r for r in rows if (r.get("PDF Filename") or "") == path.name]
        assert len(named) == 1, "%s's %s names %s %d times\n%s" % (
            app_dir.name, ledger.path.name, path.name, len(named), said[-800:])


# -- the source, where nothing written after a document is done may fail it ----------------------

SKIP = {".venv", "venv", "build", "dist", "site-packages", "node_modules", "tests",
        "__pycache__"}


def _app_sources(top_folder: Path):
    """Every app's own Python, never a copy a build or an install made, nor
    a test."""
    for top, dirs, files in os.walk(top_folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.endswith("browser-profile"))
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(top) / name


def _true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _marks(fn) -> list:
    """Where a function marks a document done for good, downloaded_ok set
    True by value, whether by an assignment, a dict or a keyword."""
    at = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _true(node.value) and any(
                isinstance(t, ast.Attribute) and t.attr == "downloaded_ok"
                or isinstance(t, ast.Subscript) and "downloaded_ok" in ast.unparse(t.slice)
                for t in node.targets):
            at.append(node.lineno)
        elif isinstance(node, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "downloaded_ok" and _true(v)
                for k, v in zip(node.keys, node.values)):
            at.append(node.lineno)
        elif isinstance(node, ast.Call) and any(
                kw.arg == "downloaded_ok" and _true(kw.value) for kw in node.keywords):
            at.append(node.lineno)
    return at


def _in_try(fn) -> set:
    inside = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                inside |= {id(n) for n in ast.walk(stmt)}
    return inside


def _made(tree) -> dict:
    """What each attribute of self is made by, self.index_csv = CsvFile(...)
    as CsvFile, through the module's own names for the core's classes."""
    made = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for t in node.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                        and t.value.id == "self":
                    made[t.attr] = ast.unparse(node.value.func).split(".")[-1]
    return made


# What a write is, by the call that writes. A CSV of the app's own is a
# CsvFile whatever the attribute holding it is called, and a ledger walked
# in a loop (Meijer's `for book in (...)`) is known by the CsvFile methods
# called on it.
LEDGER_CALLS = {"append_rows", "rewrite", "_ensure_header"}
WRITES = {"atomic_write_text", "atomic_write_json", "write_text", "write_bytes",
          "open_to_write", "write_whole", "copy_whole", "backup_file"}
MOVES = {"shutil": {"move", "copy", "copy2", "copyfile"}, "os": {"replace", "rename"}}
# The one write the core makes safe for a document saved and checked. An
# append to a ledger waits for it and keeps what it cannot write (CsvFile).
SAFE = {("CsvFile", "append_rows")}
# The run state, progress.json and discovery.json, held open while a run
# writes it, waits its minute and raises as before. That is outside what
# was fixed here and is said in the notes of the change.
RUN_STATE = "JsonStore"
# Each write after the mark the core does not make safe, by app, function,
# the write, and why it stays.
KNOWN = {
    ("meijer", "process_one", "CsvFile.rewrite"):
        "A purchase no longer listed and then saved has its unlisted rows taken out of both "
        "CSVs by a rewrite, which waits its minute for a held file and then raises as every "
        "rewrite does. Rare, and a rewrite cannot keep rows aside as an append does.",
}


def _open_mode(call, at: int) -> str:
    """The mode an open asks for, the second argument of open() and the
    first of a path's own open()."""
    given = call.args[at] if len(call.args) > at else next(
        (kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if given is None:
        return "r"
    return str(given.value) if isinstance(given, ast.Constant) else "?"


def _per_document(fn) -> set:
    """Each node inside a try that is inside a loop, the way every app's
    handler for one document among many is written. A Failed record is
    written there, so it is where a mark followed by a write that raises
    turns a saved document into a failed one."""
    inside = set()
    for loop in ast.walk(fn):
        if isinstance(loop, (ast.For, ast.While)):
            for node in ast.walk(loop):
                if isinstance(node, ast.Try):
                    for stmt in node.body:
                        inside |= {id(n) for n in ast.walk(stmt)}
    return inside


def _writes_after_the_mark(path: Path) -> list:
    """(function, the write) for each write outside any try that follows the
    mark that a document is done for good, in the function that marks or in
    one that calls it on the way up to the handler for one document, the
    way a receipt app writes both CSVs after the method that saved the
    receipt returns. Followed through the app's own methods."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    methods = {n.name: n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    made = _made(tree)
    tried = {name: _in_try(fn) for name, fn in methods.items()}
    handled = {name: _per_document(fn) for name, fn in methods.items()}

    def own(call):
        f = call.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)                 and f.value.id == "self" and f.attr in methods:
            return f.attr
        return None

    def calls(name):
        return [n for n in ast.walk(methods[name]) if isinstance(n, ast.Call)]

    def calls_untried(name):
        return [n for n in calls(name) if id(n) not in tried[name]]

    marking = {name for name, fn in methods.items() if _marks(fn)}
    grew = True
    while grew:
        grew = False
        for name in methods:
            if name not in marking and any(own(n) in marking and id(n) not in handled[name]
                                           for n in calls(name)):
                marking.add(name)
                grew = True

    def writes_of(call, seen):
        f = call.func
        if isinstance(f, ast.Attribute):
            owner = f.value
            kind = None
            if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)                     and owner.value.id == "self":
                kind = made.get(owner.attr)
            if f.attr in LEDGER_CALLS and kind in (None, "CsvFile"):
                return ["CsvFile.%s" % f.attr]
            if kind == RUN_STATE and f.attr in ("update", "save"):
                return ["JsonStore.%s" % f.attr]
            if f.attr in WRITES:
                return [f.attr]
            if isinstance(owner, ast.Name) and f.attr in MOVES.get(owner.id, ()):
                return ["%s.%s" % (owner.id, f.attr)]
            if f.attr == "open" and set(_open_mode(call, 0)) & set("wax+?"):
                return ["open"]
        elif isinstance(f, ast.Name):
            if f.id in WRITES:
                return [f.id]
            if f.id == "open" and set(_open_mode(call, 1)) & set("wax+?"):
                return ["open"]
        inner = own(call)
        if inner is None or inner in seen:
            return []
        out = []
        for n in calls_untried(inner):
            out += writes_of(n, seen | {inner})
        return out

    found = []
    for name in marking:
        points = _marks(methods[name]) + [n.lineno for n in calls(name)
                                          if own(n) in marking and own(n) != name
                                          and id(n) not in handled[name]]
        if not points:
            continue
        start = min(points)
        for n in calls_untried(name):
            if n.lineno > start:
                for write in writes_of(n, {name}):
                    found.append((name, write))
    return sorted(set(found))


def test_the_census_finds_the_writes_after_the_mark():
    """Not a check that passes because it found nothing. Chase writes its row
    after it marks a statement done, and Lowe's writes both CSVs after the
    receipt is marked, in the function that called the one that marks."""
    chase_found = _writes_after_the_mark(REPO / "apps" / "chase" / "chase_docs.py")
    assert ("download_one", "CsvFile.append_rows") in chase_found, chase_found
    assert ("download_one", "JsonStore.update") in chase_found, chase_found
    lowes_found = _writes_after_the_mark(REPO / "apps" / "lowes" / "lowes_receipts.py")
    assert ("process_one", "CsvFile.append_rows") in lowes_found, lowes_found


def test_nothing_written_after_a_document_is_done_can_fail_it():
    """Each write that follows the mark that a document is done for good, in
    every app, is one the core makes safe, the run state, or listed."""
    unsafe, seen = [], set()
    for path in _app_sources(REPO / "apps"):
        app = path.relative_to(REPO / "apps").parts[0]
        for fn, write in _writes_after_the_mark(path):
            kind = write.split(".")
            if tuple(kind) in SAFE or kind[0] == RUN_STATE:
                continue
            if (app, fn, write) in KNOWN:
                seen.add((app, fn, write))
                continue
            unsafe.append("%s %s %s" % (app, fn, write))
    assert not unsafe, "a write after a document is done that can fail it:\n" + "\n".join(unsafe)
    assert seen == set(KNOWN), "listed but not found any more, %s" % sorted(set(KNOWN) - seen)
