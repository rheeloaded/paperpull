"""Every app's check of what is done, its Rename preview, its Review Names
and its Verify finish past a named pipe a record or an index row names.

A record or a row can name any path, a history imported from another
computer or a file edited by hand, and on PaperPull Server someone on the
share can leave a named pipe where a saved file was. pdf_reader opened and
read such a path in the run's own process before any time limit, so
whatever reached it through a record or a row waited for good, Target's
invoice walk and Robinhood's tax forms among them (the bug hunt of
2026-11-14, finding 4). A folder named like a PDF is the case every system
can make, and Verify has to report it and go on.

Each app here is built as it is at home, from its own code, with a made-up
config and output folder and no browser to reach for. Its records hold the
pipe in every path field, pdf_path and each file of a list of invoices, in
each shape the app's own code reads a record in, the shapes the census of
values that are not text builds, and its index holds a row naming it.
Then the app's own _already_done for each record, its Rename preview and
its Verify through its own main, and a receipt app's Review Names, each
have to finish within half a minute.

A named pipe is POSIX, skipped on Windows with the reason and run under
WSL. A Windows named pipe that never writes stands in for one where a
record names it, since a read of it waits as the other's open does. Every
name, number and file here is invented.
"""
import importlib.util
import json
import os
import sys
import threading
import traceback
from pathlib import Path

import pytest

from paperpull_core import pdf_reader
from paperpull_core import storage as core_storage
from paperpull_core.models import State

POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"
SECONDS = 30


def _harness(file: str, name: str):
    """A sibling test file, for the harness that builds an app as it is at
    home and runs its own commands."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renames = _harness("test_every_app_renames_only_a_file_it_holds.py", "pipe_rename_harness")
reviews = _harness("test_every_app_reviews_a_name_once.py", "pipe_review_harness")
shapes = _harness("test_every_app_reads_a_record_value_that_is_not_text_as_none.py",
                  "pipe_shapes_harness")
REVIEWS = {a.name for a in reviews.APPS}


def within(seconds, fn, *args, **kwargs):
    """fn(*args, **kwargs) in a thread, failing if it is still waiting after
    `seconds`, with where it waits. What it answered or raised is handed
    back."""
    got = {}

    def run():
        try:
            got["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        frame = sys._current_frames().get(t.ident)
        lines = [f for f in traceback.extract_stack(frame)
                 if "paperpull_core" in f.filename or "apps" in Path(f.filename).parts]
        where = ", ".join("%s:%d %s" % (Path(f.filename).name, f.lineno, f.name)
                          for f in lines[-6:])
        raise AssertionError("still waiting after %s s, in %s" % (seconds, where))
    return got


class _Fifo:
    def __init__(self):
        if not hasattr(os, "mkfifo"):
            pytest.skip(POSIX_ONLY)
        self.made = []

    def at(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        self.made.append(path)
        return path

    def close(self):
        for path in self.made:
            try:
                os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass


class _WindowsPipe:
    """Many instances, since every look at the pipe's name takes one."""

    def __init__(self):
        if os.name != "nt":
            pytest.skip("a Windows named pipe, which only Windows makes")
        import _winapi
        self._winapi = _winapi
        self.path = Path(r"\\.\pipe\paperpull-test-%d-%s" % (os.getpid(), os.urandom(4).hex()))
        self.handles = [_winapi.CreateNamedPipe(
            str(self.path), _winapi.PIPE_ACCESS_DUPLEX, 0, _winapi.PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0, _winapi.NULL) for _ in range(1024)]

    def at(self, _path: Path) -> Path:
        return self.path

    def still_there(self) -> bool:
        """Whether an instance is left, so a look that raised was not one
        that found every instance taken."""
        try:
            os.stat(self.path)
            return True
        except OSError:
            return False

    def close(self):
        for h in self.handles:
            try:
                self._winapi.CloseHandle(h)
            except OSError:
                pass


class _Folder:
    def at(self, path: Path) -> Path:
        path.mkdir(parents=True)
        return path

    def close(self):
        pass


KINDS = {"named pipe": _Fifo, "Windows named pipe": _WindowsPipe,
         "folder named like a PDF": _Folder}


@pytest.fixture(params=list(KINDS))
def stand_in(request):
    made = KINDS[request.param]()
    yield made
    made.close()


@pytest.fixture(autouse=True)
def fresh_reader():
    pdf_reader.stop()
    yield
    pdf_reader.stop()


def records_naming(app_dir: Path, there: Path) -> dict:
    """A record of each shape the app reads, each naming `there` in every
    path field it keeps."""
    bases = shapes.records(shapes.fields_of(app_dir))
    bases["set aside"] = dict(bases["compared"], state=State.NEEDS_MANUAL_REVIEW.value,
                              downloaded_ok=False)
    named = {"pdf_path": str(there), "pdf_filename": there.name,
             "invoices": [{"file": str(there), "part": "1 of 1", "number": "", "kept": True}]}
    return {"Invented:pipe %s" % base: dict(rec, **named) for base, rec in bases.items()}


def _main(home, *command):
    """The app's own main, as the panel runs it, and what it said."""
    home.capsys.readouterr()
    try:
        home.mod.main(["--config", str(home.cfg), *command])
    except SystemExit:
        pass
    return " ".join(home.capsys.readouterr().out.split())


def _already_done(home, recs: dict) -> int:
    """The app's own _already_done over each record, built the way the app
    builds its own. How many it was asked about."""
    inst = home.build()
    entry = renames.entry_of(home.app)
    built = home.mod.Purchase if entry.name.endswith("_receipts.py") else home.mod.Document
    asked = 0
    for rec in recs.values():
        try:
            doc = built.from_dict(dict(rec))
        except Exception:
            continue
        inst._already_done(doc)
        asked += 1
    return asked


def ends(got: dict, what: str, home) -> None:
    error = got.get("error")
    assert error is None or isinstance(error, SystemExit), (
        "%s's %s ended with %r" % (home.app.name, what, error))


@pytest.mark.parametrize("app", renames.APPS, ids=renames.IDS)
def test_every_command_finishes_past_a_pipe_a_record_names(app, stand_in, tmp_path,
                                                           monkeypatch, capsys):
    home = renames.Home(app, tmp_path, monkeypatch, capsys)
    inst = home.build()
    core_storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    filed = inst.paths.folder_for(next(iter(core_storage.spec().routes), "Statement"))
    there = stand_in.at(filed / "2026-05-14 Invented Statement.pdf")
    recs = records_naming(app, there)
    shapes.write(inst, recs)
    inst.index_csv.append_rows([renames.a_row(inst.index_csv.columns, 1, there)])
    monkeypatch.setattr(home.mod, "ask", lambda prompt: "", raising=False)

    # A folder opens at once on every system and fails as it always did, so
    # it is the case every system makes for Verify alone.
    if not isinstance(stand_in, _Folder):
        got = within(SECONDS, _already_done, home, recs)
        ends(got, "check of what is done", home)
        assert got.get("value"), "%s built no record to ask about, so this proves nothing" % (
            app.name)
        ends(within(SECONDS, _main, home, "--rename"), "Rename preview", home)
        if app.name in REVIEWS:
            ends(within(SECONDS, _main, home, "--review-names"), "Review Names", home)
    got = within(SECONDS, _main, home, "--verify")
    ends(got, "Verify", home)
    rows = [r for r in home.build().index_csv.read_all() if r.get("PDF Full Path") == str(there)]
    assert rows and not (rows[0].get("Verified At") or "").strip(), (
        "%s's Verify took a row naming %s for a good one\n%s"
        % (app.name, type(stand_in).__name__, got.get("value", "")[-1500:]))
    if isinstance(stand_in, _WindowsPipe):
        assert stand_in.still_there(), "every instance of the pipe was taken, so this proves nothing"
    assert home.browser.asked == 0, "a command reached for a browser"
    # The records are as they were, naming the pipe, never read into.
    held = json.loads(inst.paths.progress_json.read_text(encoding="utf-8"))
    assert any(isinstance(r, dict) and r.get("pdf_path") == str(there) for r in held.values())
