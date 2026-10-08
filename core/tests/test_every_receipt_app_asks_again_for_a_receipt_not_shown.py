"""A receipt page that did not show its receipt is asked for again, in every
receipt app.

A tester's Kroger run met Kroger's own "There was a problem loading the
receipt. Please try again." on some of his receipts (#70). The app
recorded each as No Receipt Available, which is final, printed that it was
marked for manual review, and wrote it into both CSVs. The next run said
each was "Already completed and PDF verified" and skipped it, with no file
on disk. Nine receipt apps did the same when their receipt page did not
show the receipt, and Meijer, whose skip never held that state final,
wrote the purchase into both CSVs again on every run that retried it.

So a page that did not show the receipt is a failure the next run asks
for again, with nothing written to the CSVs, and a record an older version
made final that way is asked for again too. A purchase the provider showed
has no receipt keeps its record.

These drive each receipt app's own _already_done, and its own step that
looks for the receipt on the page with that page never showing one, over
an output folder on disk. The site module is a stand-in that answers
nothing, so the only thing a run meets is a page without its receipt.
Every name, number and address is invented.
"""
import argparse
import ast
import collections
import datetime
import importlib
import itertools
import inspect
import sys
from pathlib import Path

import pytest

from paperpull_core.models import ONLINE, Purchase, State

REPO = Path(__file__).resolve().parents[2]

ORDER = "ORDER-0001"
DATE = "2026-05-14"

# Word for word what receipt apps up to 0.44.0 noted with No Receipt
# Available when the receipt page did not show the receipt, and who wrote
# each. Records on disk carry these, so they are written out here rather
# than read from the core, which a test would then only agree with.
OLDER_VERSIONS_WROTE = {
    "No printable order summary available": "Amazon, 0.1.0 to 0.44.0",
    "Details page did not fill in": "Best Buy, Home Depot and Lowe's, 0.36.0 to 0.44.0",
    "Costco could not load this receipt": "Costco, 0.31.0 to 0.44.0",
    "Kroger could not load this receipt": "Kroger, 0.29.1 to 0.44.0 (#70)",
    "Receipt page did not render": "Costco and Kroger",
    "Order-details receipt did not render": "eBay 0.29.0 and Gap 0.4.0, to 0.44.0",
    "Receipt page did not show a receipt": "GitHub and Meijer, 0.30.0 to 0.44.0",
}

# What a provider showed, and stays final. Target's order with no receipt
# control and GitHub's payment row with no receipt link.
PROVIDER_SHOWED = ["No printable receipt available", "The payment row carries no receipt link"]


def entry_of(app: Path):
    found = sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


def _app_class(app: Path):
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    return next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App"), None)


def skips_what_it_saved(app: Path) -> bool:
    """A receipt app, found by what its App does. Its skip decision reads
    the progress record's downloaded_ok and state."""
    cls = _app_class(app)
    if cls is None:
        return False
    skip = next((n for n in cls.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_already_done"), None)
    return bool(skip and "downloaded_ok" in ast.unparse(skip)
                and "state" in ast.unparse(skip) and "_record_state" in ast.unparse(cls))


def _asks_for_the_receipt(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "receipt_is_present")


def _not_shown_tests(fn):
    """Every `if` in a function that is entered when the page was found not
    to show the receipt, by the call itself or a name it was kept in."""
    kept = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign) and _asks_for_the_receipt(n.value)
            for t in n.targets if isinstance(t, ast.Name)}
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        for part in ast.walk(node.test):
            if isinstance(part, ast.UnaryOp) and isinstance(part.op, ast.Not) and (
                    _asks_for_the_receipt(part.operand)
                    or (isinstance(part.operand, ast.Name) and part.operand.id in kept)):
                found.append(node)
                break
    return found


def looking_methods(app: Path):
    """The App's methods that look for the receipt on the page and act on
    not finding it."""
    cls = _app_class(app)
    return [m for m in cls.body if isinstance(m, ast.FunctionDef) and _not_shown_tests(m)]


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and skips_what_it_saved(d))
IDS = [d.name for d in APPS]
LOOKING = [(d, m.name) for d in APPS for m in looking_methods(d)]
LOOKING_IDS = ["%s.%s" % (d.name, name) for d, name in LOOKING]


def test_every_receipt_app_is_asked():
    """Not a census of nobody. The fourteen receipt apps, and the nine that
    look for the receipt on a page before printing it."""
    assert len(APPS) >= 14, IDS
    assert len({d for d, _ in LOOKING}) >= 9, LOOKING_IDS


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


class _Anything:
    """Answers every call and attribute with nothing, which is a journal or
    a browser page that does no harm."""

    url = ""

    def __getattr__(self, name):
        return lambda *a, **k: None


class _SiteThatShowsNothing:
    """The app's site module, where every page is this purchase's and
    belongs to the provider, and no receipt ever shows on it."""

    def __getattr__(self, name):
        if name.startswith("is_"):            # is_safe_url, is_receipt_address
            return lambda *a, **k: True
        return lambda *a, **k: None


RUNS = itertools.count(1)


def app_in(mod, out: Path, redownload: bool = False, day: int = None):
    """The app's own downloader over an output folder on disk, without its
    __init__, which would want a config file and a console. A new one is a
    new run, started a day after the one before, unless `day` says which.
    A run is counted by the day it started."""
    storage = sys.modules["storage"]            # the app's own, loaded with it
    inst = object.__new__(mod.App)
    inst.config = {"max_path_length": 240, "min_pdf_bytes": 2000, "owner": ""}
    inst.args = argparse.Namespace(redownload=redownload)
    inst.paths = storage.Paths(out)
    inst.paths.ensure()
    backups = inst.paths.backups
    inst.progress = storage.JsonStore(inst.paths.progress_json, backups)
    inst.discovery = storage.JsonStore(inst.paths.discovery_json, backups)
    inst.progress.load()
    inst.discovery.load()
    inst.index_csv = storage.CsvFile(inst.paths.receipt_index_csv,
                                     storage.RECEIPT_INDEX_COLUMNS, backups)
    inst.order_csv = storage.CsvFile(inst.paths.order_history_csv,
                                     storage.ORDER_HISTORY_COLUMNS, backups)
    inst.stats = collections.defaultdict(int)
    inst.stats["new_files"] = []
    inst.stats["dates_processed"] = []
    n = next(RUNS)
    inst.stats["started"] = (datetime.datetime(2031, 1, 1, 12)
                             + datetime.timedelta(days=n if day is None else day, minutes=n % 600)
                             ).isoformat(timespec="seconds")
    inst.write_failure = lambda *a, **k: None
    inst.check_session = lambda *a, **k: False
    inst._journal = _Anything()                 # the journal property makes one otherwise
    return inst


def purchase():
    return Purchase(purchase_type=ONLINE, purchase_date=DATE, order_number=ORDER,
                    total="$12.34", summary="Garden Hose",
                    receipt_url="https://receipts.example.invalid/r/" + ORDER)


def done(mod, out: Path, rec: dict) -> bool:
    """What a new run's skip decision answers for this purchase's record."""
    inst = app_in(mod, out)
    p = purchase()
    inst.progress.update(p.key, dict(p.to_dict(), **rec))
    return bool(app_in(mod, out)._already_done(p))


@pytest.mark.parametrize("app", APPS, ids=IDS)
@pytest.mark.parametrize("note", sorted(OLDER_VERSIONS_WROTE))
def test_a_record_an_older_version_made_final_is_asked_for_again(app, note, tmp_path):
    mod = load(app)
    rec = {"state": State.NO_RECEIPT_AVAILABLE.value}

    assert not done(mod, tmp_path / "bare", dict(rec, notes=note)), \
        "%s skips a purchase %s left No Receipt Available with %r" % (
            app.name, OLDER_VERSIONS_WROTE[note], note)
    # After a note an earlier step of the same run wrote, as _record_state
    # joins them.
    assert not done(mod, tmp_path / "joined", dict(rec, notes="Earlier step; " + note)), app.name


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_only_those_records_are_asked_for_again(app, tmp_path):
    """A purchase the provider showed has no receipt is answered as it
    always was, and a receipt saved for good stays saved, whatever its
    note says."""
    mod = load(app)
    rec = {"state": State.NO_RECEIPT_AVAILABLE.value}
    before = done(mod, tmp_path / "none", dict(rec, notes=""))
    for i, note in enumerate(PROVIDER_SHOWED):
        assert done(mod, tmp_path / ("showed%d" % i), dict(rec, notes=note)) == before, \
            (app.name, note)
    # An older note somewhere before the last one is not what the state was
    # written with.
    assert done(mod, tmp_path / "earlier",
                dict(rec, notes="Receipt page did not render; " + PROVIDER_SHOWED[0])) == before
    for i, note in enumerate(sorted(OLDER_VERSIONS_WROTE)):
        assert done(mod, tmp_path / ("saved%d" % i),
                    dict(rec, notes=note, downloaded_ok=True)), (app.name, note)


def look(mod, out: Path, method: str, redownload: bool = False, rec: dict = None,
         day: int = None):
    """One run's look for the receipt on a page that never shows it, by the
    app's own method. The run, and what it printed is read off capsys."""
    inst = app_in(mod, out, redownload, day)
    p = purchase()
    inst.discovery.update(p.key, p.to_dict())
    if rec:
        inst.progress.update(p.key, dict(p.to_dict(), **rec))
    found = getattr(inst, method)
    named = inspect.signature(found).parameters
    args = [_Anything() if n == "page" else p for n in named if n in ("page", "purchase")]
    assert not found(*args), "nothing was saved"
    return inst


def written_down(inst) -> int:
    return sum(1 for f in (inst.order_csv, inst.index_csv) for r in f.read_all()
               if ORDER in " ".join(r.values()))


@pytest.mark.parametrize("app, method", LOOKING, ids=LOOKING_IDS)
def test_a_page_that_did_not_show_the_receipt_is_asked_for_again(app, method, tmp_path,
                                                                 monkeypatch, capsys):
    mod = load(app)
    monkeypatch.setattr(mod, "site", _SiteThatShowsNothing())
    p = purchase()

    for n in (1, 2):
        inst = look(mod, tmp_path, method)
        said = " ".join(capsys.readouterr().out.split())
        rec = inst.progress.get(p.key) or {}
        assert rec.get("state") not in (State.NO_RECEIPT_AVAILABLE.value, State.COMPLETED.value,
                                        State.CANCELED.value), (app.name, rec.get("state"))
        assert "on %d of 3 separate days. It is tried again next run." % n in said, said
        assert "marked for manual review" not in said, said
        assert not done_already(mod, tmp_path, p),             "%s's next run skips a purchase whose receipt page did not show it" % app.name
        # The panel counts it as something to look at.
        assert inst.stats["failed"] + inst.stats["manual_review"] >= 1
        # The run that saves it writes it down. The CSVs only take rows on
        # the end, so rows written now would stand beside those, once per try.
        assert not written_down(inst), app.name

    # The third run that finds nothing sets it aside, and writes it down once.
    inst = look(mod, tmp_path, method)
    said = " ".join(capsys.readouterr().out.split())
    assert "on 3 of 3 separate days. It is set aside for review" in said, said
    assert (inst.progress.get(p.key) or {}).get("state") == State.NO_RECEIPT_AVAILABLE.value
    assert inst.stats["manual_review"] >= 1
    rows = written_down(inst)
    assert rows >= 2, "a row in each CSV"
    assert done_already(mod, tmp_path, p)

    # Download again asks for it, and finding nothing again writes nothing.
    inst = look(mod, tmp_path, method, redownload=True)
    capsys.readouterr()
    assert written_down(inst) == rows


@pytest.mark.parametrize("app, method", LOOKING, ids=LOOKING_IDS)
def test_download_again_keeps_a_receipt_saved_before(app, method, tmp_path, monkeypatch, capsys):
    """Download again asks for a receipt saved before, and when its page
    does not show it no plain run asks for it again, so the run does not
    say one will."""
    mod = load(app)
    monkeypatch.setattr(mod, "site", _SiteThatShowsNothing())
    p = purchase()
    inst = look(mod, tmp_path, method, redownload=True,
                rec={"state": State.COMPLETED.value, "downloaded_ok": True})
    said = " ".join(capsys.readouterr().out.split())
    assert "The receipt saved before is kept." in said, said
    assert "tried again next run" not in said, said
    assert (inst.progress.get(p.key) or {}).get("downloaded_ok")
    assert done_already(mod, tmp_path, p)
    assert not written_down(inst)


def done_already(mod, out: Path, p) -> bool:
    return bool(app_in(mod, out)._already_done(p))


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_no_receipt_app_records_no_receipt_from_a_page_that_did_not_show_one(app):
    """By the code, for a branch a stand-in cannot reach. Nothing entered
    because the receipt was not found on the page records the purchase as
    having none or writes it into the CSVs."""
    cls = _app_class(app)
    faults = []
    for m in cls.body:
        if not isinstance(m, ast.FunctionDef):
            continue
        for branch in _not_shown_tests(m):
            for node in ast.walk(ast.Module(body=branch.body, type_ignores=[])):
                if not isinstance(node, ast.Call):
                    continue
                said = ast.unparse(node)
                if "NO_RECEIPT_AVAILABLE" in said or (
                        isinstance(node.func, ast.Attribute) and node.func.attr == "_write_csv_rows"):
                    faults.append("%s line %d: %s" % (m.name, node.lineno, said[:80]))
    assert not faults, faults


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_a_purchase_set_aside_is_never_said_to_be_completed(app):
    """A run told a tester "Already completed and PDF verified" for a
    receipt never saved (#70). Every place an app says it asks the core
    first, which says a purchase set aside was skipped for that."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    said = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
            and isinstance(n.value, str) and "Already completed and PDF verified" in n.value]
    asked = {id(a) for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "skipped"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "not_shown"
             for a in n.args}
    assert said, "the app says it skipped something"
    assert all(id(n) in asked for n in said), app.name


def test_the_words_for_a_purchase_set_aside():
    from paperpull_core import not_shown
    aside = {"state": State.NO_RECEIPT_AVAILABLE.value, "not_shown_days": ["a", "b", "c"]}
    assert "did not show on 3 separate days" in not_shown.skipped(aside, "done")
    assert not_shown.skipped(dict(aside, not_shown_days=["a", "b"]), "done") == "done"
    assert not_shown.skipped(dict(aside, downloaded_ok=True), "done") == "done"
    assert not_shown.skipped({"state": State.COMPLETED.value}, "done") == "done"
    assert not_shown.skipped(None, "done") == "done"


@pytest.mark.parametrize("app, method", LOOKING, ids=LOOKING_IDS)
def test_a_purchase_written_down_before_is_not_written_down_again(app, method, tmp_path,
                                                                  monkeypatch, capsys):
    """An older version recorded the purchase as having no receipt and wrote
    it into both CSVs then. Asked for again and set aside after three more
    runs, it keeps those rows and gets no second set."""
    mod = load(app)
    monkeypatch.setattr(mod, "site", _SiteThatShowsNothing())
    inst = app_in(mod, tmp_path)
    p = purchase()
    inst._write_csv_rows(p, receipt_status="No printable receipt available",
                         processing_status=State.NEEDS_MANUAL_REVIEW.value,
                         notes_extra=sorted(OLDER_VERSIONS_WROTE)[0])
    before = written_down(inst)
    assert before >= 2
    rec = {"state": State.NO_RECEIPT_AVAILABLE.value, "notes": sorted(OLDER_VERSIONS_WROTE)[0]}
    look(mod, tmp_path, method, rec=rec)
    for _ in range(2):
        inst = look(mod, tmp_path, method)
    capsys.readouterr()
    assert (inst.progress.get(p.key) or {}).get("state") == State.NO_RECEIPT_AVAILABLE.value
    assert written_down(inst) == before, app.name


@pytest.mark.parametrize("app, method", LOOKING, ids=LOOKING_IDS)
def test_a_history_that_cannot_be_written_leaves_it_to_the_next_run(app, method, tmp_path,
                                                                    monkeypatch, capsys):
    """The third run could not write the order history, open in Excel. The
    purchase is not set aside with nothing written. The run after writes it
    down and sets it aside."""
    mod = load(app)
    monkeypatch.setattr(mod, "site", _SiteThatShowsNothing())
    p = purchase()
    for _ in range(2):
        look(mod, tmp_path, method)
    real = mod.App._write_csv_rows

    def locked(self, *a, **k):
        raise PermissionError("the file is open in another program")

    monkeypatch.setattr(mod.App, "_write_csv_rows", locked)
    # Raised to the run, which records a failure, or caught by the app's own
    # step, which does the same (GitHub, Meijer).
    try:
        look(mod, tmp_path, method)
    except PermissionError:
        pass
    assert not done_already(mod, tmp_path, p), app.name
    monkeypatch.setattr(mod.App, "_write_csv_rows", real)
    inst = look(mod, tmp_path, method)
    capsys.readouterr()
    assert (inst.progress.get(p.key) or {}).get("state") == State.NO_RECEIPT_AVAILABLE.value
    assert written_down(inst) >= 2
    assert done_already(mod, tmp_path, p)


@pytest.mark.parametrize("app, method", LOOKING, ids=LOOKING_IDS)
def test_every_run_of_one_day_counts_once(app, method, tmp_path, monkeypatch, capsys):
    """Pilot, Run All and Resume one after another, or a server running every
    hour through a provider's outage, are many runs on one bad day. They
    count as one, so a receipt is never set aside in an evening."""
    mod = load(app)
    monkeypatch.setattr(mod, "site", _SiteThatShowsNothing())
    p = purchase()
    for _ in range(4):
        inst = look(mod, tmp_path, method, day=7)
    said = " ".join(capsys.readouterr().out.split())
    assert said.count("on 1 of 3 separate days. It is tried again next run.") == 4, said
    assert (inst.progress.get(p.key) or {}).get("state") != State.NO_RECEIPT_AVAILABLE.value
    assert not done_already(mod, tmp_path, p)
    assert not written_down(inst)
