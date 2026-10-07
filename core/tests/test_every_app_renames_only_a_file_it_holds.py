"""Rename renames nothing but a document its app holds, in every app.

Rename gives each file the index names the name the app would give it
today (paperpull_core.renaming). It planned every row whose path was on
disk, whatever was there. A row naming the output folder itself, a folder
the app files documents in, a file outside the app's folders, one reached
by climbing out of them through "..", the app's own config file in an
output folder set to the app's own folder, a file in Logs, Diagnostics or
Backups, or a file that is not a PDF, was renamed to a document's name by
--apply, and the panel's Apply renames runs that with no preview first. A
row naming "." had it try to rename the folder it runs in. No app writes
such a row itself. An index copied along with its output folder to a new
place, or edited by hand, holds them.

Each app here is built as it is at home, from its own code, with a made-up
config in its output folder and no browser to reach for, and its own
Rename runs through its own main as the panel runs it. Every name, number
and file is invented.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import storage as core_storage

REPO = Path(__file__).resolve().parents[2]

DATE = "2026-05-14"
# The folders that hold a run's own records and never a document.
RECORDS = ("logs", "diagnostics", "backups")


def entry_of(app: Path):
    for pattern in ("*_receipts.py", "*_docs.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


def renames_through_the_core(app: Path) -> bool:
    """An app whose Rename is the core's, found by a call to
    renaming.run_for in its own code and never by its name."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    return any(isinstance(node, ast.Call) and ast.unparse(node.func) == "renaming.run_for"
               for node in ast.walk(tree))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and renames_through_the_core(d))
IDS = [d.name for d in APPS]
RECEIPT_APPS = [d for d in APPS if entry_of(d).name.endswith("_receipts.py")]


class NoBrowser:
    """sync_playwright() for a machine with no browser. Rename never needs
    one, so any attach or launch is counted and refused."""

    def __init__(self):
        self.asked = 0

        def refuse(*_a, **_kw):
            self.asked += 1
            raise Exception("connect ECONNREFUSED 127.0.0.1:9")
        self.chromium = SimpleNamespace(connect_over_cdp=refuse,
                                        launch_persistent_context=refuse,
                                        launch=refuse)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def pdf(path: Path, what: str) -> Path:
    """A PDF of invented bytes, its own, so it can be found again by them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% " + what.encode() + b"\n%%EOF\n")
    return path


def everything_under(folder: Path) -> dict:
    """Every file and folder below `folder`, each file with its bytes."""
    return {p.relative_to(folder).as_posix(): (p.read_bytes() if p.is_file() else None)
            for p in folder.rglob("*")}


class Home:
    """One app with a made-up config and output folder, built through its
    own code and run through its own main. The config sits in the output
    folder, as it does when the output folder is set to the app's own."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch, capsys):
        # What loading an app and its config sets in the core, put back
        # after, so no other test names files by this one's pattern.
        for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        self.out = tmp_path / "out"
        example = app / "config.example.json"
        config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        config.update({
            "owner": "Dana Example", "output_dir": str(self.out),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
        })
        for key in ("filename_pattern", "filename_pattern_receipts",
                    "filename_pattern_statements"):
            config.pop(key, None)
        self.out.mkdir()
        self.cfg = self.out / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.browser = NoBrowser()
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", self.browser)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr("builtins.input", self._no_console)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def build(self):
        """The app as its own main builds it."""
        return self.mod.App(self.mod.build_parser().parse_args(["--config", str(self.cfg)]))

    def rename(self, *flags):
        """The app's own Rename, as the panel presses it. What it said, with
        its lines joined, and the error it ended with, None when it ended
        cleanly."""
        self.capsys.readouterr()
        error = None
        try:
            self.mod.main(["--config", str(self.cfg), "--rename", *flags])
        except SystemExit:
            pass
        except Exception as e:                   # what a person would see as a traceback
            error = e
        return " ".join(self.capsys.readouterr().out.split()), error


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def a_row(columns, number: int, path) -> dict:
    """An index row as a run writes one, for a receipt or a document,
    whichever the app's index holds. `path` is written as it is given, so
    "." is a row as written and not a file. Each row is named for its
    own number, so each would be given a name of its own."""
    text = str(path)
    summary = "Invented Thing %d" % number
    row = {"Purchase Date": DATE, "Document Date": DATE, "Purchase Type": "Online",
           "Category": "Statement", "Order or Receipt Number": "ORDER-%04d" % number,
           "Purchase Summary": summary, "Document Summary": summary,
           "Document Title": summary, "Document Type": "Receipt",
           "PDF Filename": Path(text).name, "PDF Full Path": text,
           "Classification Confidence": "High", "Processing Status": "Completed",
           "Notes": ""}
    return {k: v for k, v in row.items() if k in columns}


def an_archive(home: Home, here: Path, elsewhere: Path):
    """An output folder whose index names a PDF in every folder the app
    files documents in, by its own spec, and every kind of thing the app
    does not hold. The PDFs it holds, by the bytes in each, the folder it
    files most in, and the rows, the ones it holds first."""
    app = home.build()
    folders = [getattr(app.paths, f.attr) for f in core_storage.spec().folders
               if f.attr not in RECORDS]
    assert app.paths.manual_review in folders
    held = {}
    for i, folder in enumerate(folders):
        path = pdf(folder / ("old name %d.pdf" % i), "held %d" % i)
        held[path.read_bytes()] = path
    filed = app.paths.folder_for(next(iter(core_storage.spec().routes), "Statement"))
    not_held = [
        filed,                                                       # a folder it files in
        pdf(elsewhere / "elsewhere.pdf", "elsewhere"),               # a file elsewhere
        app.paths.manual_review / ".." / ".." / "elsewhere" / "climbed.pdf",
        home.cfg,                                                    # the app's own config
        pdf(app.paths.logs / "logged.pdf", "logged"),
        pdf(app.paths.diagnostics / "diagnosed.pdf", "diagnosed"),
        pdf(app.paths.backups / "backed up.pdf", "backed up"),
        filed / "notes.txt",                                         # not a PDF
        ".",                                                         # the folder it runs in
        home.out,                                                    # the output folder itself
    ]
    pdf(elsewhere / "climbed.pdf", "climbed")
    (filed / "notes.txt").write_text("invented notes", encoding="utf-8")
    pdf(here / "here.pdf", "here")
    columns = app.index_csv.columns
    rows = [a_row(columns, i, path) for i, path in enumerate([*held.values(), *not_held])]
    app.index_csv.append_rows(rows)
    return held, filed, rows


def test_there_are_apps_to_check():
    """Every app, found by what it does. Not a check that passes because it
    found nobody."""
    entries = [d.name for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d)]
    assert len(APPS) >= 61 and sorted(IDS) == sorted(entries), sorted(set(entries) - set(IDS))


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_rename_renames_only_a_document_the_app_holds(home, tmp_path, monkeypatch):
    """--apply renames the PDF in each folder the app files documents in,
    Manual Review included, and points the index at it. Nothing else the
    index names is touched, on disk or in the index, and Rename says how
    many rows it left alone and why."""
    here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
    held, filed, rows = an_archive(home, here, elsewhere)
    monkeypatch.chdir(here)
    before = {"here": everything_under(here), "elsewhere": everything_under(elsewhere)}
    # The config, the log, the diagnosis and the notes, each where it was.
    kept = {p: p.read_bytes() for p in home.out.rglob("*")
            if p.is_file() and p.suffix in (".json", ".pdf", ".txt")
            and p.read_bytes() not in held
            and p.name not in ("progress.json", "discovery.json")}

    said, error = home.rename("--apply")

    assert error is None, "%s's Rename ended with %r\n%s" % (home.app.name, error, said[-1500:])
    assert home.out.is_dir() and filed.is_dir(), (
        "%s renamed a folder\n%s" % (home.app.name, said[-1500:]))
    assert {"here": everything_under(here), "elsewhere": everything_under(elsewhere)} \
        == before, "%s renamed something outside its folders\n%s" % (home.app.name,
                                                                     said[-1500:])
    assert {p: p.read_bytes() for p in kept if p.is_file()} == kept, (
        "%s renamed its config, a log, a diagnosis or a file that is no PDF\n%s"
        % (home.app.name, said[-1500:]))
    now = {p.read_bytes(): p for p in home.out.rglob("*.pdf") if p.read_bytes() in held}
    assert sorted(now) == sorted(held), "%s lost a PDF it holds" % home.app.name
    for body, old in held.items():
        assert now[body].parent == old.parent and now[body].name != old.name, (
            "%s did not rename %s\n%s" % (home.app.name, old, said[-1500:]))
    assert "Renamed %d file(s)." % len(held) in said, said[-1500:]
    assert ("%d row(s) of the index name something other than a PDF in this app's "
            "folders, so they are left alone." % (len(rows) - len(held))) in said, said[-1500:]

    index = home.build().index_csv.read_all()
    assert [r["PDF Full Path"] for r in index[len(held):]] \
        == [r["PDF Full Path"] for r in rows[len(held):]]
    assert [r["PDF Filename"] for r in index[len(held):]] \
        == [r["PDF Filename"] for r in rows[len(held):]]
    assert [Path(r["PDF Full Path"]) for r in index[:len(held)]] == [now[b] for b in held]
    assert home.browser.asked == 0, "Rename reached for a browser"


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_rename_preview_offers_only_a_document_the_app_holds(home, tmp_path, monkeypatch):
    """The preview, what Rename preview and the File names page show before
    anything is renamed, lists the PDFs the app holds and nothing else, says
    how many rows it leaves alone, and changes nothing."""
    here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
    held, _filed, rows = an_archive(home, here, elsewhere)
    monkeypatch.chdir(here)
    before = {"out": everything_under(home.out), "here": everything_under(here),
              "elsewhere": everything_under(elsewhere)}

    said, error = home.rename()

    assert error is None, "%s's Rename ended with %r\n%s" % (home.app.name, error, said[-1500:])
    assert "%d file(s) would be renamed." % len(held) in said, (
        "%s offered to rename something it does not hold\n%s" % (home.app.name, said[-1500:]))
    for old in held.values():
        assert old.name in said
    assert ("%d row(s) of the index name something other than a PDF in this app's "
            "folders, so they are left alone." % (len(rows) - len(held))) in said, said[-1500:]
    after = {"out": everything_under(home.out), "here": everything_under(here),
             "elsewhere": everything_under(elsewhere)}
    for name in ("progress.json", "discovery.json", "run-summary.txt", "new-this-run.txt"):
        before["out"].pop(name, None)
        after["out"].pop(name, None)
    logs = [k for k in after["out"] if k.startswith("Logs/")]
    for k in logs:
        if k not in before["out"]:
            after["out"].pop(k)
    assert after == before, "%s's preview changed something" % home.app.name


@pytest.mark.parametrize("home", RECEIPT_APPS, ids=[d.name for d in RECEIPT_APPS],
                         indirect=True)
def test_each_purchases_order_history_follows_its_own_file(home):
    """Two receipts of one day filed under one name in two folders, renamed
    apart. A purchase's rows in the order history, which carry its number
    and its file's name and no path, take the new name of its own file.
    Matched by the name alone, both purchases' rows took whichever came
    last, and Review Names, which finds them by the name the index gives
    the file, could no longer put them right."""
    app = home.build()
    first, second = [getattr(app.paths, f.attr) for f in core_storage.spec().folders
                     if f.attr not in RECORDS][:2]
    old = "old name.pdf"
    rows = [a_row(app.index_csv.columns, 1, pdf(first / old, "first")),
            a_row(app.index_csv.columns, 2, pdf(second / old, "second"))]
    app.index_csv.append_rows(rows)
    numbers = [r["Order or Receipt Number"] for r in rows]
    app.order_csv.append_rows([{"Order or Receipt Number": number, "Item Name": item,
                                "PDF Filename": old}
                               for number, item in ((numbers[0], "Invented Item"),
                                                    (numbers[0], "Other Item"),
                                                    (numbers[1], "Invented Item"))])

    said, error = home.rename("--apply")

    assert error is None, "%s's Rename ended with %r\n%s" % (home.app.name, error, said[-1500:])
    after = home.build()
    named = {r["Order or Receipt Number"]: r["PDF Filename"] for r in after.index_csv.read_all()}
    assert len(set(named.values()) - {old}) == 2, said[-1500:]
    assert [(r["Order or Receipt Number"], r["PDF Filename"])
            for r in after.order_csv.read_all()] == [
        (numbers[0], named[numbers[0]]), (numbers[0], named[numbers[0]]),
        (numbers[1], named[numbers[1]])], home.app.name


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_link_is_not_renamed(home, tmp_path):
    """A row naming a link to a PDF the app holds, the link in a folder the
    app files documents in. A rename would move the link, which the app did
    not make, and leave the document it leads to as it was."""
    app = home.build()
    filed = app.paths.folder_for(next(iter(core_storage.spec().routes), "Statement"))
    target = pdf(filed / "held.pdf", "held")
    link = filed / "linked.pdf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let a test make a link")
    app.index_csv.append_rows([a_row(app.index_csv.columns, 1, link)])
    said, error = home.rename("--apply")
    assert error is None and link.is_symlink() and target.is_file(), said[-1500:]
