"""Every app renames each file for its own record, never for another's.

Rename names a file from the record its app keeps, so a naming pattern can
use what the record knows, an account or an order number (#26, #50). It
found that record by the row's date and title, and merged every record of
one date and title into one. American Family titles every bill's statement
"Account Statement" and its date, and keeps the bill's account part only
in the summary, the key and the account field. With two bills that each
had a statement of one day, Rename offered to give the first bill's file
the second bill's account part and a " (2)", and after a pattern change
both files were named for the second bill. Nothing was lost and the index
kept the right summary, but the file names said the wrong account. Citi
titles every card's statement the same way. The release review of 0.44.0
found it.

A row is now the document whose record names the row's own file, and a
date and a title are asked only where no record names it
(renaming._Known).

Each app here is built as it is at home, from its own code, with a made-up
config and output folder and no browser to reach for. Two documents of one
date and one title for two accounts, told apart the way the app tells them
apart, are written down by the app's own record and index code, each with a
file of its own named the way its download names one. Then the naming
pattern changes and the app's own Rename runs with --apply, as the panel's
File names page has it run. Each file, found by the bytes in it, has to
carry its own account and nothing of the other's, and the index and the
run state have to point at it.

An app that keeps a document under the provider's own id runs a second
time with an id on each document, since that record was keyed here by the
id and its row, which carries no id, by its date and title, so Rename
never found it at all.

A receipt app tells two purchases apart by order number, which its rows
carry, so for those this shows that what worked before still does.

The second of two files that wanted one name is told apart the way its
download told it apart, by what the download hands unique_path, the last
six characters of the id a document's record keeps, the order number for
a purchase and the first day it covers for a PayPal business statement.
Rename asked the index row, which carries an order number and never a
document's id, so under the very pattern the files were saved by, a
preview offered to rename "... Monthly Statement OC2222.pdf" to
"... (2).pdf", the complaint of #43 and #49 back again. A document's file
here is saved where the app's own download_one would save it, taken at
the moment it asks unique_path, so these hold Rename to what each app's
download does, and an id a later listing writes over the one the
download used does not move the file.
"""
import ast
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, ONLINE, State

REPO = Path(__file__).resolve().parents[2]

DATE = "2026-09-12"
ACCOUNTS = ("1111", "2222")
# What the File names page might be set to. The account and the order
# number are fields only a record has, so a file carries its own only when
# Rename found its own record.
PATTERN = "{date:yyyy-mm-dd} {provider}[ {account}][ {number}] {summary}"
RENAMED_BOTH = "Renamed 2 file(s)"
NAMED_ALREADY = "Every file is already named the way this app names them."


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
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


def gives_the_providers_id(app: Path) -> bool:
    """An app that records a document under the provider's own id, found by
    a Document it builds with a document_id that is not left empty."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "Document":
            for kw in node.keywords:
                if kw.arg == "document_id" and not (
                        isinstance(kw.value, ast.Constant) and not kw.value.value):
                    return True
    return False


WITH_IDS = [d for d in APPS if gives_the_providers_id(d)]


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


class Home:
    """One app with a made-up config and output folder, built through its
    own code and run through its own main."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch, capsys):
        # What loading an app and its config sets in the core, put back
        # after, so no other test names files by this one's pattern.
        for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        example = app / "config.example.json"
        config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
        })
        for key in ("filename_pattern", "filename_pattern_receipts",
                    "filename_pattern_statements"):
            config.pop(key, None)
        self.config = config
        self.cfg = tmp_path / "config.json"
        self._write_config()
        self.out = Path(config["output_dir"])
        self.browser = NoBrowser()
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", self.browser)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr("builtins.input", self._no_console)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def _write_config(self):
        self.cfg.write_text(json.dumps(self.config), encoding="utf-8")

    def set_pattern(self, pattern: str):
        """What the File names page saves."""
        self.config["filename_pattern"] = pattern
        self._write_config()

    def build(self):
        """The app as its own main builds it."""
        return self.mod.App(self.mod.build_parser().parse_args(["--config", str(self.cfg)]))

    def rename(self, *flags) -> str:
        """The app's own Rename, as the panel presses it, and what it said."""
        self.capsys.readouterr()
        try:
            self.mod.main(["--config", str(self.cfg), "--rename", *flags])
        except SystemExit:
            pass
        return " ".join(self.capsys.readouterr().out.split())

    def files(self) -> dict:
        """Every PDF under the output folder, by the bytes in it."""
        return {p.read_bytes(): p for p in self.out.rglob("*.pdf")}


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def body_of(account: str) -> bytes:
    return b"%PDF-1.4\n% the statement of account " + account.encode() + b"\n%%EOF\n"


# -- two documents of one date and one title -------------------------------------

TITLE = "Monthly Statement - September 12, 2026"


def two_documents(home: Home, with_ids: bool = False, titles=(TITLE, TITLE)):
    """Two documents of one date for two accounts, of one title unless
    `titles` says otherwise, as this app's own Document class records them
    and told apart the way it tells them apart, by the account or by which
    of the day's documents of that title it is. With `with_ids`, each also
    has the provider's own id, as the app records one it is given. None
    when its key tells them apart by neither, so the app never holds both."""
    Document = home.mod.Document
    category = (home.config.get("document_types") or ["Statement"])[0]
    takes = inspect.signature(Document.__init__).parameters

    def make(account, title, occurrence=None):
        kw = dict(title=title, category=category, summary="Monthly Statement", date=DATE,
                  account=account)
        if with_ids:
            kw["document_id"] = "DOC%s" % account
        if occurrence is not None:
            kw["occurrence"] = occurrence
        return Document(**kw)

    pair = (make(ACCOUNTS[0], titles[0]), make(ACCOUNTS[1], titles[1]))
    if pair[0].key == pair[1].key and "occurrence" in takes:
        pair = (make(ACCOUNTS[0], titles[0], 0), make(ACCOUNTS[1], titles[1], 1))
    return pair if pair[0].key != pair[1].key else None


class Saving(BaseException):
    """Where an app's own download asked unique_path to save a document,
    raised at that moment so nothing after it, a page or a press, is
    reached. Not an Exception, so no handler of the app's can take it."""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


def where_its_download_saves(app, doc, filename: str) -> Path:
    """The path the app's own download_one gives this document, with what
    it hands unique_path to tell the file apart when its name is taken.
    Every download_one asks for its session and its folder before that,
    and the session is all of it that needs a page."""
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


def downloaded(app, doc, body: bytes = b"") -> Path:
    """One listed document then downloaded, written down by the app's own
    code, with a file where the app's own download saves it, under the
    name its run hands the download."""
    if app.discovery.get(doc.key) is None:
        listed = doc.to_dict()
        listed["state"] = State.DISCOVERED.value
        app.discovery.update(doc.key, listed, save=False)
    name = core_storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    path = where_its_download_saves(app, doc, name)
    path.write_bytes(body or body_of(doc.account))
    doc.pdf_path, doc.pdf_filename = str(path), path.name
    doc.downloaded_ok = True
    app._record(doc, State.COMPLETED)
    app._write_row(doc, "Downloaded", State.COMPLETED.value)
    return path


def saved(app):
    app.progress.save()
    app.discovery.save()


def each_file_is_its_own(home: Home, said: str, key: str, values):
    """Each file carries its own record's value and nothing of the other's,
    the index and the run state point at it, and nothing was lost or
    doubled."""
    files = home.files()
    assert sorted(files) == sorted(body_of(a) for a in ACCOUNTS), (
        "%s lost or doubled a file\n%s" % (home.app.name, said[-1500:]))
    app = home.build()
    rows = app.index_csv.read_all()
    for account, own, other in zip(ACCOUNTS, values, reversed(values)):
        path = files[body_of(account)]
        assert own in path.name and other not in path.name and "(2)" not in path.name, (
            "%s named the file of %s %r\n%s" % (home.app.name, own, path.name, said[-1500:]))
        records = [r for r in app.progress.data.values()
                   if isinstance(r, dict) and r.get(key) == own]
        assert len(records) == 1 and Path(records[0]["pdf_path"]) == path, (
            "%s's run state does not point at the file of %s" % (home.app.name, own))
        assert [r for r in rows if Path(r["PDF Full Path"]) == path], (
            "%s's index does not point at the file of %s" % (home.app.name, own))
    assert home.browser.asked == 0, "Rename reached for a browser"


# -- every app that renames through the core ---------------------------------------

def test_there_are_apps_to_check():
    """Every app, found by what it does. Not a check that passes because it
    found nobody."""
    assert len(APPS) >= 61, IDS
    assert {"amfam", "citi", "target", "wellsfargo"} <= set(IDS)
    assert len(WITH_IDS) >= 16 and {"capitalone", "chase", "vanguard"} <= {
        d.name for d in WITH_IDS}, [d.name for d in WITH_IDS]


@pytest.mark.parametrize("home", WITH_IDS, ids=[d.name for d in WITH_IDS], indirect=True)
def test_a_document_known_by_the_providers_id_is_renamed_for_its_own_record(home):
    """A record under the provider's own id was keyed by that id here, and
    its row, which carries no id, by its date and title, so Rename never
    found it, and a pattern's account, number or kind never reached a file
    these apps had already downloaded."""
    app = home.build()
    pair = two_documents(home, with_ids=True)
    assert pair is not None
    for doc in pair:
        downloaded(app, doc)
    saved(app)
    home.set_pattern(PATTERN)
    said = home.rename("--apply")
    assert RENAMED_BOTH in said, said[-1500:]
    each_file_is_its_own(home, said, "account", ACCOUNTS)
    for account in ACCOUNTS:
        assert "DOC" + account in home.files()[body_of(account)].name


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_pattern_change_renames_each_file_for_its_own_record(home):
    app = home.build()
    if hasattr(home.mod, "Document"):
        pair = two_documents(home)
        if pair is None:
            pytest.skip("its key is the date and the title alone, so it never "
                        "holds two documents of one date and title")
        for doc in pair:
            downloaded(app, doc)
        key, values = "account", ACCOUNTS
    else:
        values = tuple("ORD" + a for a in ACCOUNTS)
        for number in values:
            purchased(home, app, number)
        key = "order_number"
    saved(app)
    home.set_pattern(PATTERN)
    said = home.rename("--apply")
    assert RENAMED_BOTH in said, said[-1500:]
    each_file_is_its_own(home, said, key, values)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_name_a_deleted_file_freed_is_never_given_its_old_document(home):
    """A file deleted after it was imported elsewhere frees its name, and a
    later document of that day and summary is saved under it, since a free
    name goes to whoever asks. The index then has a row for each, both
    naming the one file, and both records name it. The file holds the later
    document, and Rename named it for the deleted one."""
    app = home.build()
    if hasattr(home.mod, "Document"):
        first, later = two_documents(home, titles=(TITLE, "Statement - September 12, 2026"))
        path = downloaded(app, first)
        path.unlink()
        assert downloaded(app, later) == path, "the later document took another name"
        old = ACCOUNTS[0]
    else:
        path = purchased(home, app, "ORD" + ACCOUNTS[0])
        path.unlink()
        assert purchased(home, app, "ORD" + ACCOUNTS[1]) == path, (
            "the later purchase took another name")
        old = "ORD" + ACCOUNTS[0]
    saved(app)
    home.set_pattern(PATTERN)
    said = home.rename("--apply")
    files = home.files()
    assert list(files) == [body_of(ACCOUNTS[1])], said[-1500:]
    assert old not in files[body_of(ACCOUNTS[1])].name, (
        "%s named the later document's file %r for the deleted one\n%s"
        % (home.app.name, files[body_of(ACCOUNTS[1])].name, said[-1500:]))
    assert home.browser.asked == 0, "Rename reached for a browser"


def purchased(home: Home, app, number: str) -> Path:
    """One purchase listed then downloaded, written down by the app's own
    code, of one day and one summary with the other, under its own order
    number."""
    Purchase = home.mod.Purchase
    kind = next(k for k in (ONLINE, IN_STORE) if routes(app, k))
    p = Purchase(purchase_type=kind, purchase_date=DATE, order_number=number,
                 total="$%s.00" % number[-2:], summary="Household Goods",
                 document_type="Receipt", confidence="High")
    listed = p.to_dict()
    listed["state"] = State.DISCOVERED.value
    app.discovery.update(p.key, listed, save=False)
    name = core_storage.build_pdf_filename(p.purchase_date, p.summary, p.document_type,
                                           record=p)
    path = core_storage.unique_path(app.paths.folder_for(p.purchase_type, p.document_type),
                                    name, app.config["max_path_length"],
                                    distinguisher=p.order_number)
    path.write_bytes(body_of(number[3:]))
    p.pdf_path, p.pdf_filename = str(path), path.name
    app._record_state(p, State.COMPLETED, extra={"downloaded_ok": True})
    app._write_csv_rows(p, "Downloaded", State.COMPLETED.value)
    return path


def routes(app, kind: str) -> bool:
    try:
        app.paths.folder_for(kind)
        return True
    except KeyError:
        return False


# -- American Family and Citi, from their own listing ------------------------------

# How each one's site titles a statement it lists (amfam_site._documents_shown,
# citi_site.collect_download_docs), with the bill's or the card's account part
# beside the title rather than in it.
TITLED = {"amfam": "Account Statement - %s", "citi": "Monthly Statement - %s"}


def listed_and_downloaded(home: Home):
    """Both bills' statements of one day, listed by the app's own discovery
    code from what its site hands it, then downloaded."""
    app = home.build()
    site = home.mod.site
    title = TITLED[home.app.name] % site._human_date(DATE)
    for account in ACCOUNTS:
        raw = site.RawDoc(title=title, account=account, date_text=DATE,
                          href="acct-%s" % account)
        assert app._record_rawdoc(raw, "https://example.invalid/statements") == 1
    docs = [home.mod.Document.from_dict(rec) for rec in app.discovery.data.values()]
    assert len(docs) == 2 and docs[0].title == docs[1].title == title
    for doc in docs:
        assert doc.account in doc.summary, "the summary is where the account part shows"
        downloaded(app, doc)
    saved(app)
    return docs


@pytest.mark.parametrize("home", [REPO / "apps" / n for n in TITLED], ids=list(TITLED),
                         indirect=True)
def test_a_rename_preview_offers_nothing_for_two_bills_of_one_day(home):
    """The reviewer's case. Each file was already named for its own bill,
    and the preview offered to give the first the second bill's account
    part."""
    listed_and_downloaded(home)
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before


@pytest.mark.parametrize("home", [REPO / "apps" / n for n in TITLED], ids=list(TITLED),
                         indirect=True)
def test_a_pattern_change_keeps_each_bill_in_its_own_file_name(home):
    listed_and_downloaded(home)
    home.set_pattern(PATTERN)
    said = home.rename("--apply")
    assert RENAMED_BOTH in said, said[-1500:]
    each_file_is_its_own(home, said, "account", ACCOUNTS)


@pytest.mark.parametrize("home", [REPO / "apps" / n for n in TITLED], ids=list(TITLED),
                         indirect=True)
def test_a_bill_taken_again_beside_one_that_failed_keeps_its_own_account(home):
    """Download again took a second copy of the first bill beside its first,
    and the second bill's capture failed, each written down by the app's own
    code as its run writes them, from what discovery listed. The first
    bill's record then names its new copy and the second bill's names no
    file, and Rename offered the first copy the second bill's account."""
    listed_and_downloaded(home)
    app = home.build()
    listed = {r["account"]: home.mod.Document.from_dict(r) for r in app.discovery.data.values()}
    again = body_of(ACCOUNTS[0]).replace(b"%%EOF", b"taken again\n%%EOF")
    downloaded(app, listed[ACCOUNTS[0]], body=again)
    failed = listed[ACCOUNTS[1]]
    app._record(failed, State.NEEDS_MANUAL_REVIEW, notes="Could not capture the document PDF")
    app._write_row(failed, "Capture failed", State.NEEDS_MANUAL_REVIEW.value)
    saved(app)
    bills = {body_of(ACCOUNTS[0]): ACCOUNTS, again: ACCOUNTS,
             body_of(ACCOUNTS[1]): tuple(reversed(ACCOUNTS))}

    before = {body: p.name for body, p in home.files().items()}
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    home.set_pattern(PATTERN)
    said = home.rename("--apply")
    after = {body: p.name for body, p in home.files().items()}
    assert sorted(after) == sorted(before) == sorted(bills), said[-1500:]
    for body, (own, other) in bills.items():
        assert other not in after[body], (
            "%s named a file of %s %r\n%s" % (home.app.name, own, after[body], said[-1500:]))
    # The new copy is named for its own record, so it carries the account
    # twice, from the pattern's account field and from the summary.
    assert after[again].count(ACCOUNTS[0]) == 2, after[again]
    assert home.browser.asked == 0, "Rename reached for a browser"


# -- the second of two files of one name -------------------------------------------

# A pattern under which two documents of one day and one summary want one
# name, and not the name either has.
ONE_NAME = "{date:yyyy-mm-dd} {summary}"
OTHER_TITLE = "Statement - September 12, 2026"
NEVER_TWO = "its key never tells two documents of one day and one summary apart"


def two_of_one_name(home: Home, app):
    """Two files that wanted one name, the second saved beside the first
    the way the app's download saves it, each holding its own account's
    bytes. A document carries the provider's id where the app records one.
    Two documents of one title where the app's key tells them apart, and of
    two titles where it does not, as Wealthfront's keeps a document by its
    date and title alone. None when its key tells them apart by neither."""
    if not hasattr(home.mod, "Document"):
        return [purchased(home, app, "ORD" + a) for a in ACCOUNTS]
    with_ids = home.app in WITH_IDS
    pair = (two_documents(home, with_ids=with_ids)
            or two_documents(home, with_ids=with_ids, titles=(TITLE, OTHER_TITLE)))
    if pair is None:
        return None
    return [downloaded(app, doc) for doc in pair]


def added_to(plain: str, told: str) -> str:
    """What the second file's name adds to the name both wanted, the end of
    an id, an order number or " (2)"."""
    stem = plain[:-len(".pdf")]
    assert told.startswith(stem + " ") and told.endswith(".pdf"), (plain, told)
    return told[len(stem):-len(".pdf")]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_preview_offers_nothing_for_a_second_file_its_download_told_apart(home):
    """The second of two documents of one day and one summary was saved with
    the end of its id in its name, and under the very pattern it was saved
    by, the preview offered to rename it to " (2)"."""
    app = home.build()
    files = two_of_one_name(home, app)
    if files is None:
        pytest.skip(NEVER_TWO)
    first, second = files
    added = added_to(first.name, second.name)
    if home.app in WITH_IDS or not hasattr(home.mod, "Document"):
        assert added != " (2)", (
            "%s's download told %r apart by nothing" % (home.app.name, second.name))
    saved(app)
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before
    assert home.browser.asked == 0, "Rename reached for a browser"


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_pattern_giving_two_files_one_name_tells_the_second_apart_as_its_download_did(home):
    """A new pattern can give two documents one name that neither had. The
    second is told apart by what its download told it apart by, as a
    download into a folder holding the first would be, and a second Rename
    has nothing left to do. It was given " (2)", and the next Rename
    offered to rename it again."""
    app = home.build()
    files = two_of_one_name(home, app)
    if files is None:
        pytest.skip(NEVER_TWO)
    added = added_to(files[0].name, files[1].name)
    saved(app)
    home.set_pattern(ONE_NAME)
    said = home.rename("--apply")
    assert RENAMED_BOTH in said, said[-1500:]
    after = {body: p.name for body, p in home.files().items()}
    plain = after[body_of(ACCOUNTS[0])]
    assert after[body_of(ACCOUNTS[1])] == plain[:-len(".pdf")] + added + ".pdf", (
        "%s named the second file %r\n%s" % (home.app.name, after[body_of(ACCOUNTS[1])],
                                             said[-1500:]))
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert home.browser.asked == 0, "Rename reached for a browser"


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
# A File names pattern without the summary, under which these apps'
# statements of one day share a name, since their summaries carry the
# account.
NO_SUMMARY = "{date:yyyy-mm-dd} {provider}"


def test_there_are_apps_that_write_a_new_id_over_an_old_one():
    assert {"capitalone", "schwab", "vanguard"} <= {d.name for d in RELISTS}, RELISTS


def listing(app, name: str):
    """The app's own method that writes down a document its list gives it,
    taking a listed document's fields as a dict."""
    method = getattr(app, name)
    others = [set()] * (len(inspect.signature(method).parameters) - 1)
    return lambda fields: method(dict(fields), *others)


@pytest.mark.parametrize("home", RELISTS, ids=[d.name for d in RELISTS], indirect=True)
def test_an_id_a_later_listing_gives_never_moves_a_file_its_download_told_apart(home):
    """Capital One, Schwab and Vanguard keep a document under its account,
    date, title and place, and a later listing that gives it another id
    writes that over the one in discovery, where progress keeps the one its
    download told the file apart by. Rename read the newer one, so the
    preview offered to rename "... OC2222.pdf" to "... OC9999.pdf", and the
    newer one can be another statement's where the listing's order
    changed."""
    home.set_pattern(NO_SUMMARY)
    app = home.build()
    lists = listing(app, relists_with_a_new_id(home.app))
    pair = two_documents(home, with_ids=True)
    for doc in pair:
        assert lists(doc.to_dict()) == 1, "the app's own listing kept no record"
    listed = [home.mod.Document.from_dict(app.discovery.get(doc.key)) for doc in pair]
    first, second = [downloaded(app, doc) for doc in listed]
    assert added_to(first.name, second.name) != " (2)", second.name
    saved(app)

    app = home.build()
    listing(app, relists_with_a_new_id(home.app))(
        dict(listed[1].to_dict(), document_id="DOC9999"))
    assert app.discovery.get(listed[1].key)["document_id"] == "DOC9999", (
        "the later listing wrote no new id, so this shows nothing")
    saved(app)

    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before


# -- PayPal's business statements, told apart by their first days -------------------

PAYPAL = REPO / "apps" / "paypal"
FIRST_DAYS = ("2026-08-10", "2026-08-15")
LAST_DAY = "2026-08-31"


def business_statements(home: Home):
    """Two of PayPal's business statements ending on one day, listed by its
    own code from the days its list gives, as paypal_site.listing_of hands
    them over, then downloaded, each holding its own first day's bytes."""
    app = home.build()
    site = home.mod.site
    for first in FIRST_DAYS:
        period = site.Period(start=first, end=LAST_DAY)
        raw = site.RawDoc(title=period.title(), date_text=period.date, href=period.href(),
                          text="PayPal " + period.title(), period=period.covers())
        assert app._record_rawdoc(raw, "https://example.invalid/reports") == 1
    files = []
    for rec in list(app.discovery.data.values()):
        doc = home.mod.Document.from_dict(rec)
        files.append(downloaded(app, doc, body=body_of(site.business_ref(doc.href).start)))
    saved(app)
    first, second = files
    assert second.name == first.name[:-len(".pdf")] + " " + FIRST_DAYS[1] + ".pdf", (
        "the download no longer tells the second apart by its first day", second.name)
    return files


@pytest.mark.parametrize("home", [PAYPAL], ids=["paypal"], indirect=True)
def test_a_preview_offers_nothing_for_a_business_statement_told_apart_by_its_first_day(home):
    """No id tells two of PayPal's business statements ending on one day
    apart, so its download adds the first day the second covers to its
    name. A preview offered to rename it to " (2)"."""
    business_statements(home)
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before


@pytest.mark.parametrize("home", [PAYPAL], ids=["paypal"], indirect=True)
def test_a_pattern_change_keeps_a_business_statements_first_day(home):
    business_statements(home)
    home.set_pattern(ONE_NAME)
    said = home.rename("--apply")
    assert RENAMED_BOTH in said, said[-1500:]
    after = {body: p.name for body, p in home.files().items()}
    assert after == {body_of(FIRST_DAYS[0]): "%s Statement.pdf" % LAST_DAY,
                     body_of(FIRST_DAYS[1]): "%s Statement %s.pdf" % (LAST_DAY, FIRST_DAYS[1])}, (
        after, said[-1500:])
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert home.browser.asked == 0, "Rename reached for a browser"
