"""A document already saved keeps its record when Download again saves no
copy of its own.

The panel's Download again runs an app with --redownload, so a document
app takes every document in scope again, the ones it saved before
included. The document it works on comes from discovery.json, which names
no file and never says the document was downloaded, and every step of the
attempt wrote that whole document over its record in progress.json, by
the one _record every document app has. An attempt that saved nothing, at
a site that would not hand the document over, a copy that failed its check
and was put aside, an error partway, a session that ran out or a period
the provider no longer keeps, left the record of a document the person has
naming no file, or the copy put aside, with the attempt's state and with
downloaded_ok False.

So the next plain run fetched the document again and saved a second copy
beside the first, or, where the person had deleted the first after
importing it elsewhere, brought back a copy they had let go. Rename found
no record naming the saved file. Capital One and Schwab write the id each
new listing gives a known document into discovery, so the attempt wrote
that id over the one the file was saved under as well.

Now each document app's _record asks paperpull_core.saved_copy first, as
each receipt app's _record_state does. An attempt changes nothing in a
saved document's record but its notes until it has saved a copy of its
own, and the Pilot report of that run says how it ended.

These drive each document app's own process and download_one with its
site handing nothing over, and each way its own code ends an attempt with
nothing saved through its own record and index writes, over an output
folder on disk, and its own Pilot report. Every name, number and file is
invented.
"""
import ast
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import renaming, saved_copy
from paperpull_core import storage as core_storage
from paperpull_core.models import State

REPO = Path(__file__).resolve().parents[2]

DATE = "2026-05-14"
TITLE = "Invented Monthly Statement"
SUMMARY = "Invented Statement"
ACCOUNT = "1111"
SAVED_ID = "DOC0001"
LATER_ID = "DOC0009"
# A File names pattern that carries the id, so a file is named for the id
# its record holds.
PATTERN = "{date:yyyy-mm-dd} {provider}[ {number}] {summary}"


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


def _app_class(app: Path):
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    return next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App"), None)


def _methods(cls) -> dict:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def recorder_of(app: Path):
    """The name of the method that writes a document's record, found as
    the one process hands a document and State.FAILED when download_one
    raises, or None."""
    cls = _app_class(app)
    process = _methods(cls).get("process") if cls else None
    for node in ast.walk(process) if process else ():
        if isinstance(node, ast.ExceptHandler):
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and ast.unparse(call.func.value) == "self"
                        and any(ast.unparse(a) == "State.FAILED" for a in call.args)):
                    return call.func.attr
    return None


def downloads_again(app: Path) -> bool:
    """A document app whose documents are saved once for good and taken
    again under --redownload, found by what its App does. Its skip decision
    reads both the flag and downloaded_ok, its process hands each document
    to download_one, and a failure there is written to the record."""
    cls = _app_class(app)
    if cls is None:
        return False
    methods = _methods(cls)
    skip, process = methods.get("_already_done"), methods.get("process")
    return bool(skip and process and "download_one" in methods
                and "redownload" in ast.unparse(skip)
                and "downloaded_ok" in ast.unparse(skip)
                and "self.download_one" in ast.unparse(process)
                and recorder_of(app))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and downloads_again(d))
IDS = [d.name for d in APPS]


def states_written(app: Path) -> set:
    """Every state the app's own process and download_one, and what they
    reach of the App, hand its recorder when no copy has been saved, read
    from its code. A call after downloaded_ok is set True records a save."""
    methods = _methods(_app_class(app))
    recorder = recorder_of(app)
    seen, todo = set(), ["process", "download_one"]
    while todo:
        name = todo.pop()
        if name in seen or name not in methods:
            continue
        seen.add(name)
        todo.extend(n.func.attr for n in ast.walk(methods[name])
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and ast.unparse(n.func.value) == "self")
    states = set()
    for name in seen:
        fn = methods[name]
        saves = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Attribute) and t.attr == "downloaded_ok"
                         for t in n.targets)
                 and isinstance(n.value, ast.Constant) and n.value.value is True]
        for call in ast.walk(fn):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == recorder and ast.unparse(call.func.value) == "self"
                    and not any(line < call.lineno for line in saves)):
                for arg in call.args:
                    text = ast.unparse(arg)
                    if text.startswith("State."):
                        states.add(getattr(State, text[len("State."):]))
    return states


def relists_with_a_new_id(app: Path):
    """The name of the app's method that writes the provider's id a later
    listing gives a known document over the one its discovery record holds,
    found by a call updating discovery with a document_id, or None."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and ast.unparse(node.func) == "self.discovery.update"
                    and len(node.args) == 2 and isinstance(node.args[1], ast.Dict)
                    and any(isinstance(k, ast.Constant) and k.value == "document_id"
                            for k in node.args[1].keys)):
                return fn.name
    return None


RELISTS = [d for d in APPS if relists_with_a_new_id(d)]


class NoBrowser:
    """sync_playwright() for a machine with no browser. Every attach or
    launch is refused, so nothing here reaches a real one."""

    def __init__(self):
        def refuse(*_a, **_kw):
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


class Home:
    """One app with a made-up config and output folder, built through its
    own code. Each build is a new run, as each press of a button in the
    panel is."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch):
        # What loading an app and its config sets in the core, put back
        # after, so no other test names files by this one's pattern.
        for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.app = app
        self.mod = load(app)
        self.monkeypatch = monkeypatch
        example = app / "config.example.json"
        config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
            "filename_pattern": PATTERN,
        })
        for key in ("filename_pattern_receipts", "filename_pattern_statements"):
            config.pop(key, None)
        self.config = config
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", NoBrowser())
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr("builtins.input", self._no_console)
        self.record = recorder_of(app)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def build(self, redownload: bool = False):
        """The app as its own main builds it, for Download again as the
        panel asks for it, scoped to a year."""
        flags = ["--config", str(self.cfg)]
        if redownload:
            flags += ["--redownload", "--year", DATE[:4]]
        return self.mod.App(self.mod.build_parser().parse_args(flags))


@pytest.fixture
def home(request, tmp_path, monkeypatch):
    return Home(request.param, tmp_path, monkeypatch)


def opening_pdf(path: Path) -> Path:
    """A one page PDF of invented words that opens."""
    from pypdf import PdfWriter
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "Invented words " * 200})
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def failing_copy(path: Path) -> Path:
    """What a capture that went wrong leaves, too small to pass any check."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% an invented blank print\n%%EOF\n")
    return path


class Saving(BaseException):
    """Where an app's own download asked unique_path to save a document,
    raised at that moment so nothing after it, a page or a press, is
    reached. Not an Exception, so no handler of the app's can take it."""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


def where_its_download_saves(app, doc, filename: str) -> Path:
    """The path the app's own download_one gives this document, with what
    it hands unique_path to tell the file apart when its name is taken."""
    mod = sys.modules[type(app).__module__]

    def asked(*args, **kwargs):
        raise Saving(core_storage.unique_path(*args, **kwargs))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(mod, "unique_path", asked)
        patch.setattr(app, "check_session", lambda *_a, **_kw: None)
        try:
            app.download_one(None, doc, filename)
        except Saving as saving:
            return saving.path
    raise AssertionError("%s's download_one saved the document nowhere" % mod.__name__)


def a_listed_document(home: Home, app):
    """One statement as the app's own Document class records it, with the
    provider's id where the class keeps one, written into discovery as a
    listing leaves it and handed back as _select hands it to process."""
    doc = home.mod.Document(title=TITLE, summary=SUMMARY, date=DATE, account=ACCOUNT,
                            category=(home.config.get("document_types") or ["Statement"])[0])
    if hasattr(doc, "document_id"):
        doc.document_id = SAVED_ID
    if app.discovery.get(doc.key) is None:
        listed = doc.to_dict()
        listed["state"] = State.DISCOVERED.value
        app.discovery.update(doc.key, listed)
    return home.mod.Document.from_dict(app.discovery.get(doc.key))


def file_name_for(home: Home, doc) -> str:
    """The name process hands download_one."""
    return core_storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)


def saved_by_a_first_run(home: Home, notes: str = ""):
    """The document as a first run leaves it, written by the app's own
    record and index writes in the order download_one writes them, with its
    file where download_one saves it and `notes` of its own. Returns the
    file, its record and what discovery says of it, and keeps its key on
    `home`."""
    app = home.build()
    doc = a_listed_document(home, app)
    path = opening_pdf(where_its_download_saves(app, doc, file_name_for(home, doc)))
    record = getattr(app, home.record)
    doc.pdf_path, doc.pdf_filename = str(path), path.name
    record(doc, State.PDF_SAVED, notes=notes)
    doc.pdf_size, doc.pdf_pages = path.stat().st_size, 1
    doc.downloaded_ok = True
    record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", "Completed")
    home.key = doc.key
    return path, dict(app.progress.get(doc.key)), dict(app.discovery.get(doc.key))


def unchanged(before: dict, after: dict) -> dict:
    """Each field of a saved record an attempt changed, with what it held
    and what it holds now. Its notes and when it was written are the
    attempt's to say."""
    return {f: (before.get(f), after.get(f)) for f in sorted(set(before) | set(after))
            if f not in ("notes", "updated_at") and before.get(f) != after.get(f)}


def rename_names_for(app, saved: Path) -> list:
    """The names the app's own Rename would give the saved file today, as
    its preview lists them."""
    seen = []
    real = renaming.describe
    try:
        renaming.describe = lambda changes, **k: seen.extend(changes)
        app.cmd_rename()
    finally:
        renaming.describe = real
    return [(c.new_path.name if c.renaming and c.new_path else Path(c.old_path).name)
            for c in seen if str(c.old_path) == str(saved)]


def the_saved_record_stands(home: Home, saved: Path, before: dict, found_before: dict, app,
                            renames: bool = True, ended=None):
    key = home.key
    after = app.progress.get(key)
    changed = unchanged(before, after)
    assert not changed, ("%s: a Download again that saved nothing changed the saved "
                         "document's record %r" % (home.app.name, changed))
    assert after["downloaded_ok"] is True
    notes = after.get("notes", "")
    assert saved_copy.NOTE in notes, "the record does not say the attempt saved nothing"
    if ended is not None:
        assert ended.value in notes, "the record does not say how the attempt ended"
    assert (app.discovery.get(key) or {}).get("state") == found_before.get("state")

    plain = home.build()
    assert plain._already_done(home.mod.Document.from_dict(plain.discovery.get(key))) is True, (
        "%s's next plain run would fetch the saved document again" % home.app.name)
    if renames and saved.exists():
        assert rename_names_for(plain, saved) == [saved.name], (
            "%s's Rename would no longer name the saved file as it was saved"
            % home.app.name)


def test_every_document_app_is_covered():
    """Every document app, found by what it does. Not a check that passes
    because it found nobody."""
    assert len(APPS) >= 48, IDS
    assert {"capitalone", "schwab", "wellsfargo", "paypal", "robinhood", "dominion",
            "coinbase"} <= set(IDS)
    assert {"capitalone", "schwab"} <= {d.name for d in RELISTS}
    assert all({State.NEEDS_MANUAL_REVIEW, State.FAILED, State.PDF_SAVED}
               <= states_written(d) for d in APPS)


# -- a site that hands nothing over, through the app's own process -------------------

class Blank:
    """A page at no site that shows nothing. Whatever the app asks of it
    answers None."""
    url = "about:blank"

    def __getattr__(self, name):
        return lambda *_a, **_kw: None


def handing_nothing(site):
    """The app's own site module with every function of it answering None,
    a site that hands nothing over, and everything else of it as it is."""
    stand_in = SimpleNamespace()
    for name in dir(site):
        value = getattr(site, name)
        if inspect.isfunction(value):
            value = (lambda *_a, **_kw: None)
        setattr(stand_in, name, value)
    return stand_in


def a_download_again_of_nothing(home: Home):
    """A run with --redownload through the app's own process and
    download_one, over a page that shows nothing and a site that hands
    nothing over. Returns the run."""
    app = home.build(redownload=True)
    home.monkeypatch.setattr(home.mod, "site", handing_nothing(home.mod.site))
    home.monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    for name in ("_on_its_site", "page"):
        if hasattr(app, name):
            home.monkeypatch.setattr(app, name, lambda *_a, **_kw: Blank())
    home.monkeypatch.setattr(app, "_delay", lambda *_a, **_kw: None)
    # The folder a browser's downloads land in, which an app sets when it
    # opens the browser this run never opens.
    if getattr(app, "_dl_dir", None) is None:
        app._dl_dir = Path(home.config["output_dir"]) / ".downloads"
    docs = app._select()
    assert [d.title for d in docs] == [TITLE], "the run took no document, so this shows nothing"
    assert app._already_done(docs[0]) is False, "Download again takes a saved document again"
    app.process(docs)
    return app


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_download_again_of_a_document_the_site_will_not_hand_over(home):
    saved, before, found_before = saved_by_a_first_run(home)
    app = a_download_again_of_nothing(home)
    the_saved_record_stands(home, saved, before, found_before, app)


@pytest.mark.parametrize("home", RELISTS, ids=[d.name for d in RELISTS], indirect=True)
def test_an_id_a_later_listing_gave_never_reaches_a_saved_record(home):
    """Capital One and Schwab keep a document under its account, date,
    title and place, and write the id a later listing gives it over the one
    in discovery. A Download again that saved nothing wrote that id over the
    one the saved file was named for, in the record Rename reads for the
    id. Which id Rename names a file for after a later listing is the
    rename census's to hold (test_every_app_renames_each_file_for_its_own_record),
    so this asks it nothing."""
    saved, before, found_before = saved_by_a_first_run(home)
    app = home.build()
    lists = getattr(app, relists_with_a_new_id(home.app))
    # Only what the method has no default for, so one telling whether the
    # listing surely named the document keeps its own answer.
    others = [set() for p in list(inspect.signature(lists).parameters.values())[1:]
              if p.default is p.empty]
    lists(dict(app.discovery.get(home.key), document_id=LATER_ID), *others)
    app.discovery.save()
    assert app.discovery.get(home.key)["document_id"] == LATER_ID, (
        "the later listing wrote no new id, so this shows nothing")
    found_before = dict(app.discovery.get(home.key))

    app = a_download_again_of_nothing(home)
    assert app.progress.get(home.key)["document_id"] == SAVED_ID
    the_saved_record_stands(home, saved, before, found_before, app, renames=False)


# -- each way the app's own code ends an attempt with nothing saved ------------------

def would_not_capture(home, app, doc, saved):
    # A capture that saved nothing is a failure, tried again (#152).
    getattr(app, home.record)(doc, State.FAILED,
                              notes="Could not capture the document PDF")
    app._write_row(doc, "Capture failed", State.FAILED.value)


would_not_capture.state = State.FAILED


def _put_aside(home, app, doc, out_path: Path):
    """download_one's steps from a copy on disk that fails its check."""
    record = getattr(app, home.record)
    failing_copy(out_path)
    doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
    record(doc, State.PDF_SAVED)
    quarantine = core_storage.unique_path(app.paths.manual_review, out_path.name, 240)
    out_path.replace(quarantine)
    doc.pdf_path, doc.pdf_filename = str(quarantine), quarantine.name
    record(doc, State.NEEDS_MANUAL_REVIEW, notes="PDF validation failed: an invented reason")
    app._write_row(doc, "Validation failed", "Needs Manual Review")


def put_aside_beside_the_saved_copy(home, app, doc, saved):
    out_path = where_its_download_saves(app, doc, file_name_for(home, doc))
    assert out_path != saved
    _put_aside(home, app, doc, out_path)


put_aside_beside_the_saved_copy.state = State.PDF_SAVED


def put_aside_after_the_copy_was_deleted(home, app, doc, saved):
    """The usual reason for Download again. The person deleted the saved
    file after importing it elsewhere, so the attempt saves under the very
    name the record holds."""
    saved.unlink()
    out_path = where_its_download_saves(app, doc, file_name_for(home, doc))
    assert out_path == saved
    _put_aside(home, app, doc, out_path)


put_aside_after_the_copy_was_deleted.state = State.PDF_SAVED


def an_error_partway(home, app, doc, saved):
    getattr(app, home.record)(doc, State.FAILED, notes="an invented error")


an_error_partway.state = State.FAILED


def the_session_ran_out(home, app, doc, saved):
    getattr(app, home.record)(doc, State.DISCOVERED, notes="Session expired before download")


the_session_ran_out.state = State.DISCOVERED


def no_longer_kept_online(home, app, doc, saved):
    getattr(app, home.record)(doc, State.NO_RECEIPT_AVAILABLE,
                              notes="Not available online any longer")
    app._write_row(doc, "Not available", "No Receipt Available")


no_longer_kept_online.state = State.NO_RECEIPT_AVAILABLE


ENDINGS = [would_not_capture, put_aside_beside_the_saved_copy,
           put_aside_after_the_copy_was_deleted, an_error_partway,
           the_session_ran_out, no_longer_kept_online]
CASES = [pytest.param(app, ending, id="%s-%s" % (app.name, ending.__name__))
         for app in APPS for ending in ENDINGS if ending.state in states_written(app)]


@pytest.mark.parametrize("home,ending", CASES, indirect=["home"])
def test_download_again_that_saves_nothing_keeps_the_saved_record(home, ending):
    saved, before, found_before = saved_by_a_first_run(home)
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    assert app._already_done(doc) is False, "Download again takes a saved document again"
    ending(home, app, doc, saved)
    the_saved_record_stands(home, saved, before, found_before, app,
                            ended=State.NEEDS_MANUAL_REVIEW if ending.state == State.PDF_SAVED
                            else ending.state)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_the_notes_say_how_the_latest_attempt_ended(home):
    """Two Download agains that each saved nothing, one run after the
    other. The saved copy's own notes stay, and one entry says how the
    latest attempt ended."""
    saved, before, _found = saved_by_a_first_run(home, notes="Invented note of the save")
    assert before["notes"] == "Invented note of the save"
    for ending in (would_not_capture, an_error_partway):
        app = home.build(redownload=True)
        ending(home, app, a_listed_document(home, app), saved)
    notes = home.build().progress.get(home.key)["notes"]
    assert notes.startswith(before["notes"] + "; "), notes
    assert notes.count(saved_copy.NOTE) == 1, notes
    assert State.FAILED.value in notes and "Could not capture" not in notes, notes


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_the_pilot_report_says_a_download_again_saved_nothing(home, capsys):
    """The record keeps the saved copy, so its state says nothing of the
    attempt. The Pilot report of that run names the attempt among what
    needs attention, and a later run's report, which did not try it, does
    not."""
    saved, before, _found = saved_by_a_first_run(home)
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    put_aside_beside_the_saved_copy(home, app, doc, saved)
    capsys.readouterr()
    app._pilot_report([doc])
    said = capsys.readouterr().out
    assert "Needs attention" in said, said
    assert saved_copy.NOTE in said.split("Needs attention")[-1], said

    app = home.build()
    app._pilot_report([a_listed_document(home, app)])
    assert saved_copy.NOTE not in capsys.readouterr().out


# -- an attempt that does save still takes the record --------------------------------

@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_download_again_that_saves_a_copy_takes_the_record(home):
    saved, before, _found = saved_by_a_first_run(home)
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    new = opening_pdf(where_its_download_saves(app, doc, file_name_for(home, doc)))
    assert new != saved
    record = getattr(app, home.record)
    doc.pdf_path, doc.pdf_filename = str(new), new.name
    record(doc, State.PDF_SAVED)
    doc.pdf_size, doc.pdf_pages = new.stat().st_size, 1
    doc.downloaded_ok = True
    record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", "Completed")

    after = app.progress.get(doc.key)
    assert after["pdf_path"] == str(new)
    assert after["pdf_filename"] == new.name
    assert after["downloaded_ok"] is True
    assert after["state"] == State.COMPLETED.value
    assert app.discovery.get(doc.key)["state"] == State.COMPLETED.value


# -- an attempt that left its own copy where the saved one was ----------------------
#
# The person deleted the saved file, so the attempt saves under the very name
# the record holds. When the attempt's copy then stays there, a copy that
# failed its check and could not be moved to Manual Review, or one an error
# cut short after it was written, a record kept as it was vouched for that
# copy as the one saved, and no later run fetched the document again.

def put_aside_could_not_move(home, app, doc, saved):
    """download_one's steps when the move to Manual Review fails, a file
    another program holds open, and the copy stays where it was saved."""
    saved.unlink()
    out_path = where_its_download_saves(app, doc, file_name_for(home, doc))
    assert out_path == saved
    record = getattr(app, home.record)
    failing_copy(out_path)
    doc.pdf_path, doc.pdf_filename = str(out_path), out_path.name
    record(doc, State.PDF_SAVED)
    record(doc, State.NEEDS_MANUAL_REVIEW, notes="PDF validation failed: an invented reason")
    app._write_row(doc, "Validation failed", "Needs Manual Review")


put_aside_could_not_move.state = State.PDF_SAVED


LEFT_IN_PLACE = [put_aside_could_not_move]


def never_vouched_for(home, app):
    """The record does not call the attempt's copy the saved one, and the
    next plain run takes the document again."""
    key = home.key
    rec = app.progress.get(key)
    held = Path(rec.get("pdf_path") or "")
    assert not (rec.get("downloaded_ok") and held.is_file()
                and held.stat().st_size != rec.get("pdf_size")), (
        "%s's record says the attempt's copy is the one saved" % home.app.name)
    plain = home.build()
    assert plain._already_done(home.mod.Document.from_dict(plain.discovery.get(key))) is False, (
        "%s's next plain run would never fetch the document again" % home.app.name)


@pytest.mark.parametrize("home,ending", [
    pytest.param(app, ending, id="%s-%s" % (app.name, ending.__name__))
    for app in APPS for ending in LEFT_IN_PLACE if ending.state in states_written(app)],
    indirect=["home"])
def test_a_record_never_vouches_for_a_copy_the_attempt_left_in_its_place(home, ending):
    saved, _before, _found = saved_by_a_first_run(home)
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    ending(home, app, doc, saved)
    never_vouched_for(home, app)


def test_every_document_app_has_an_ending_that_leaves_a_copy_in_place():
    assert all(any(ending.state in states_written(app) for ending in LEFT_IN_PLACE)
               for app in APPS)


GROWN = [would_not_capture, an_error_partway]


@pytest.mark.parametrize("home,ending", [
    pytest.param(app, ending, id="%s-%s" % (app.name, ending.__name__))
    for app in APPS for ending in GROWN if ending.state in states_written(app)],
    indirect=["home"])
def test_a_saved_copy_changed_outside_keeps_its_record(home, ending):
    """The person ran OCR over the saved PDF, so it is larger than when it
    was saved, and it is still theirs. A Download again that saves nothing
    changes nothing in its record but the notes."""
    saved, before, found_before = saved_by_a_first_run(home)
    with open(saved, "ab") as fh:
        fh.write(b"\n% a text layer an OCR tool added\n" * 40)
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    ending(home, app, doc, saved)
    the_saved_record_stands(home, saved, before, found_before, app, ended=ending.state)


THROUGH_DOWNLOAD_ONE = [d for d in APPS if d.name in ("capitalone", "dominion", "schwab")]


@pytest.mark.parametrize("home", THROUGH_DOWNLOAD_ONE, ids=[d.name for d in THROUGH_DOWNLOAD_ONE],
                         indirect=True)
def test_a_copy_that_could_not_be_moved_is_never_vouched_for_through_download_one(home):
    """The same through each app's own download_one, with the site handing
    over a copy that fails its check and the move to Manual Review refused."""
    saved, _before, _found = saved_by_a_first_run(home)
    saved.unlink()
    app = home.build(redownload=True)
    doc = a_listed_document(home, app)
    filename = file_name_for(home, doc)
    assert where_its_download_saves(app, doc, filename) == saved

    def hand_over(*args, **kwargs):
        for value in list(args) + list(kwargs.values()):
            if isinstance(value, Path) and value.suffix == ".pdf":
                failing_copy(value)
                return ("COPY0001", "") if home.app.name in ("capitalone", "schwab") else True
        return None

    site = handing_nothing(home.mod.site)
    for name in ("download_document", "download_statement", "download_bill"):
        setattr(site, name, hand_over)
    home.monkeypatch.setattr(home.mod, "site", site)
    home.monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    moving = Path.replace

    def refused(self, target):
        if Path(target).parent == app.paths.manual_review:
            raise OSError("another program holds the file open")
        return moving(self, target)

    home.monkeypatch.setattr(Path, "replace", refused)
    app.download_one(Blank(), doc, filename)
    assert saved.exists() and saved.stat().st_size < 1000, "the attempt left no copy, so this shows nothing"
    never_vouched_for(home, app)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_first_download_put_aside_is_recorded_as_before(home):
    """A document never saved has no copy to keep, so its record names the
    copy put aside, as it always did."""
    app = home.build()
    doc = a_listed_document(home, app)
    _put_aside(home, app, doc, where_its_download_saves(app, doc, file_name_for(home, doc)))
    rec = app.progress.get(doc.key)
    assert rec["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert Path(rec["pdf_path"]).parent == app.paths.manual_review
    assert not rec.get("downloaded_ok")
    assert app.discovery.get(doc.key)["state"] == State.NEEDS_MANUAL_REVIEW.value
