"""Every app names a file from the record it writes down for that file.

Rename reads a File names pattern's {number} from a file's saved record,
the order number else the document id, and what tells the second of two
files of one name apart, the order number else the last six of the id
(naming.fields_of, renaming.told_apart_by, renaming.run_for). A download
that named a file from anything else gave a file a name Rename then
offered to change.

Anthem takes its member documents, ID cards and letters each from a list
of its own, apart from its EOBs, and saves them in one loop
(anthem_docs.App._save_collected). That loop named a file from the row
the list gave, which carries the id as "doc_id", and wrote down a record
carrying it as "document_id", with no id handed to unique_path. So under a
pattern with {number}, Rename offered to add an id each of those files was
saved without, and the second of two files of one name, saved " (2)" by
the download, was offered the end of its id.

Each list here holds two documents that want one name. Anthem's code
gives the type codes "1095B" and "1095" one label, tells a member's cards
of one kind apart only by their order, and names a letter by its subject,
so two letters of one subject on one day share a name. Each is listed by
Anthem's own code from what its site hands it and saved by its own loop,
with only the provider's answers stood in, and then its own Rename runs.
Anthem's EOBs were already named from the record they are written down
by, and a test here keeps them so.

Every other app names a file from the object it writes down, which the
census at the end holds every app to.
"""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import renaming, storage, testkit
from paperpull_core.storage import sanitize_component

REPO = Path(__file__).resolve().parents[2]
ANTHEM = REPO / "apps" / "anthem"


def _rename_census():
    """The rename census, for the harness that builds an app as it is at
    home and runs its own Rename."""
    path = Path(__file__).with_name("test_every_app_renames_each_file_for_its_own_record.py")
    spec = importlib.util.spec_from_file_location("rename_census_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


census = _rename_census()
NAMED_ALREADY = census.NAMED_ALREADY
# The account and the number are fields only a record has.
NUMBERED = census.PATTERN


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return census.Home(ANTHEM, tmp_path, monkeypatch, capsys)


# -- Anthem's member documents, ID cards and letters --------------------------------

# Made up, in the shapes Anthem's site hands them over.
PERIOD = "79DM-20250101-20251231-MED-000000A00A"
CARD_DAY = "2026-01-01"
LETTER_TIME = 1767225600000      # 2026-01-01, as epoch milliseconds
LETTER_UIDS = ("u-7301aa", "u-7302bb")
SUBJECT = "Your claim was processed"

LISTS = {
    "member documents": {"status": 200, "rows": [
        {"coverageKey": PERIOD, "documentType": "1095B"},
        {"coverageKey": PERIOD, "documentType": "1095"}]},
    "ID card": {"status": 200, "body": {"result": {"data": {"patient": [
        {"name": {"given": ["JANE"], "family": "DOE"},
         "healthIdentificationCard": [
             {"cardType": "normal", "effectiveDate": CARD_DAY},
             {"cardType": "normal", "effectiveDate": CARD_DAY}]}]}}}},
    "message": {"status": 200, "messages": [
        {"msgUid": uid, "subject": SUBJECT, "body": "<p>letter %s</p>" % uid,
         "createDtTime": LETTER_TIME, "isRead": True} for uid in LETTER_UIDS]},
}


def marker(doc_id: str) -> str:
    return "the document " + doc_id


def pdf_of(doc_id: str) -> bytes:
    """A PDF that passes the app's own check and says whose it is."""
    return testkit.text_pdf([marker(doc_id)])


def taken(home, monkeypatch):
    """The three lists taken by Anthem's own commands, as Run All takes them
    after the EOBs. The provider's answers are stood in, its lists and each
    document's PDF, and nothing else."""
    site = home.mod.site
    page = SimpleNamespace(url="https://membersecure.anthem.com/member/documents")
    monkeypatch.setattr(site, "_prime_and_fetch",
                        lambda _page, _target, _bucket, _js, what, **_kw: LISTS[what])
    monkeypatch.setattr(site, "download_member_document",
                        lambda _pg, key, dtype: pdf_of(site.member_doc_id(key, dtype)))
    monkeypatch.setattr(site, "download_id_card",
                        lambda _pg, patient, kind, ordinal=0: pdf_of(
                            "IdCard|%s|%s|%d" % (patient, kind, ordinal)))
    uid_of = {"<p>letter %s</p>" % uid: uid for uid in LETTER_UIDS}
    monkeypatch.setattr(site, "render_letter",
                        lambda _pg, _label, body, _date="": pdf_of("Letter|" + uid_of[body]))
    app = home.build()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    app.cmd_documents()
    app.cmd_id_cards()
    app.cmd_letters()
    app.progress.save()
    return app


def saved_files(home, app) -> dict:
    """Each file the lists saved, by the id its bytes say, with the record
    written down for it. Six, each named in the index, none put aside."""
    by_id = {}
    for rec in app.progress.data.values():
        path = Path(rec.get("pdf_path") or "")
        assert path.parent != app.paths.manual_review, rec
        by_id[rec["document_id"]] = (path, rec)
    assert len(by_id) == 6, sorted(by_id)
    for doc_id, (path, _rec) in by_id.items():
        assert marker(doc_id).encode() in path.read_bytes(), (
            "the record of %s names a file holding another document" % doc_id)
    named = {Path(r["PDF Full Path"]) for r in app.index_csv.read_all()}
    assert named == {path for path, _rec in by_id.values()}
    assert home.browser.asked == 0, "the run reached for a browser"
    return by_id


def test_each_list_holds_two_documents_that_want_one_name(home, monkeypatch):
    """Not a check that passes because no two files ever wanted one name."""
    app = taken(home, monkeypatch)
    stems = {}
    for path, rec in saved_files(home, app).values():
        plain = storage.build_pdf_filename(rec["date"], rec["title"], "")
        stems.setdefault((path.parent, plain), []).append(path.name)
    assert sorted(len(names) for names in stems.values()) == [2, 2, 2], stems
    for (_folder, plain), names in stems.items():
        assert plain in names, "the first of two files took another name %r" % names


def test_a_preview_offers_nothing_for_a_second_file_of_one_name(home, monkeypatch):
    """The second of each two was saved " (2)", and the preview offered it
    the end of its id."""
    app = taken(home, monkeypatch)
    files = saved_files(home, app)
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before
    for path, _rec in files.values():
        assert not path.stem.endswith(" (2)"), (
            "%r was told apart by nothing, though its record keeps an id" % path.name)


def test_a_pattern_with_the_number_names_each_file_as_rename_would(home, monkeypatch):
    """Under a pattern with {number} each file was saved without its id, and
    the preview offered to add it to every one."""
    home.set_pattern(NUMBERED)
    app = taken(home, monkeypatch)
    files = saved_files(home, app)
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before
    for doc_id, (path, _rec) in files.items():
        assert sanitize_component(doc_id) in path.name, (
            "%r carries nothing of %s" % (path.name, doc_id))


# What the second of each two adds to the name both wanted, by the id of
# the document saved second. The end of an id said nothing a person could
# read, " rmal1" for a second ID card and " A1095" for a 1095-B listed
# under its other type code.
READABLE = {
    site_id: ending for site_id, ending in (
        ("MemberDoc|%s|1095B" % PERIOD, " type 1095B"),
        ("MemberDoc|%s|1095" % PERIOD, " type 1095"),
        ("IdCard|Jane Doe|normal|0", " No. 1"),
        ("IdCard|Jane Doe|normal|1", " No. 2"),
        ("Letter|%s" % LETTER_UIDS[0], " 7301aa"),
        ("Letter|%s" % LETTER_UIDS[1], " 7302bb"),
    )}
# Two documents of one day and summary under it, whatever their own names.
ONE_NAME = "{date:yyyy-mm-dd} {summary}"


def second_endings(files) -> dict:
    """What each file of a pair adds to the shorter name of its pair, by its
    document's id, for the ones that add anything."""
    by_folder = {}
    for doc_id, (path, _rec) in files.items():
        by_folder.setdefault(path.parent, []).append((doc_id, path.stem))
    out = {}
    for pair in by_folder.values():
        plain = min(stem for _id, stem in pair)
        for doc_id, stem in pair:
            if stem != plain:
                assert stem.startswith(plain), (plain, stem)
                out[doc_id] = stem[len(plain):]
    return out


def test_the_second_of_two_files_of_one_name_is_told_apart_readably(home, monkeypatch):
    app = taken(home, monkeypatch)
    endings = second_endings(saved_files(home, app))
    assert len(endings) == 3, endings
    for doc_id, ending in endings.items():
        assert ending == READABLE[doc_id], (doc_id, ending)


def test_a_pattern_change_keeps_each_readable_ending(home, monkeypatch):
    """Rename tells a file apart the way its download did, so a pattern
    giving both files of a pair one new name gives the second its ending,
    and a second Rename has nothing left to do."""
    app = taken(home, monkeypatch)
    before = second_endings(saved_files(home, app))
    home.set_pattern(ONE_NAME)
    said = home.rename("--apply")
    assert "Renamed 6 file(s)" in said, said[-1500:]
    after = second_endings(saved_files(home, home.build()))
    assert after == before, (before, after)
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]


# -- Anthem's EOBs, which its own download_one saves ---------------------------------

CLAIM = "1234500AA0001"


def eobs_taken(home, monkeypatch):
    """Two EOBs of one claim and one day, which want one name, listed by
    Anthem's own code from the rows its site hands over and taken by its
    own process and download_one, with only the provider's PDFs stood in.
    Each file's record, as written down."""
    site = home.mod.site
    page = SimpleNamespace(url="https://membersecure.anthem.com/member/eob")

    def download_document(_page, doc_id, out_path):
        Path(out_path).write_bytes(pdf_of(doc_id))
        return True

    monkeypatch.setattr(site, "ensure_statements", lambda *_a, **_kw: True)
    monkeypatch.setattr(site, "download_document", download_document)
    app = home.build()
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    for seq in (0, 1):
        assert app._record_statement_doc({
            "title": "Medical Explanation of Benefits", "date": CARD_DAY,
            "account": "Jane Doe - Medical claim " + CLAIM, "href": "",
            "doc_id": site.make_doc_id("Medical", CLAIM, "EOB", seq)}) == 1
    app.discovery.save()
    app.process([home.mod.Document.from_dict(rec) for rec in app.discovery.data.values()])
    app.progress.save()
    records = list(app.progress.data.values())
    assert len(records) == 2 and all(r.get("downloaded_ok") for r in records), records
    for rec in records:
        assert marker(rec["document_id"]).encode() in Path(rec["pdf_path"]).read_bytes()
    return records


@pytest.mark.parametrize("pattern", [None, NUMBERED], ids=["default", "numbered"])
def test_an_eob_is_named_as_rename_would_name_it(home, monkeypatch, pattern):
    """The EOBs were named from the record they are written down by, and
    stay so."""
    if pattern:
        home.set_pattern(pattern)
    names = [Path(r["pdf_path"]).name for r in eobs_taken(home, monkeypatch)]
    assert len(set(names)) == 2 and not any(n.endswith(" (2).pdf") for n in names), names
    if not pattern:
        # Anthem's own sequence number, where the end of the id said "EOB1".
        assert sorted(names)[0].endswith(" EOB 1.pdf"), names
    before = sorted(p.name for p in home.files().values())
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]
    assert sorted(p.name for p in home.files().values()) == before


def taken_again_as_before(home, monkeypatch):
    """Two EOBs of one claim and day saved as 0.45.0 saved them, the second
    told apart by the end of its id (" EOB1"), and then the second taken
    again by Download again, which leaves its old copy beside the new one
    its record names from then on. The paths of the old copy and the new."""
    today = home.mod.told_apart_by
    monkeypatch.setattr(home.mod, "told_apart_by", renaming.told_apart_by)
    records = eobs_taken(home, monkeypatch)
    second = next(r for r in records if r["pdf_path"].endswith(" EOB1.pdf"))
    old = Path(second["pdf_path"])

    def again(_page, doc_id, out_path):
        Path(out_path).write_bytes(pdf_of(doc_id + " taken again"))
        return True

    monkeypatch.setattr(home.mod.site, "download_document", again)
    app = home.build()
    monkeypatch.setattr(app, "_on_its_site",
                        lambda: SimpleNamespace(url="https://membersecure.anthem.com/member/eob"))
    monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
    app.args.redownload = True
    app.process([home.mod.Document.from_dict(app.discovery.get(k))
                 for k, rec in app.progress.data.items() if rec is not None
                 and rec.get("document_id") == second["document_id"]])
    app.progress.save()
    new = Path(app.progress.data[next(k for k, r in app.progress.data.items()
                                      if r.get("document_id") == second["document_id"])]
               ["pdf_path"])
    assert old.exists() and new != old and new.name.endswith(" EOB1 (2).pdf"), (old, new)
    # Today's rule from here on, as after an update.
    monkeypatch.setattr(home.mod, "told_apart_by", today)
    return old, new


def test_an_old_copy_saved_with_the_end_of_its_id_keeps_its_ending(home, monkeypatch):
    """The old copy's name ends " EOB1", what a download added before
    Anthem told files apart in words. Rename asked only today's rule, found
    no " EOB 1" at the end of the name, and offered the old copy " (2)",
    which says nothing about which EOB it is. It now reads the old ending
    and gives the file today's words for it, and a second Rename has
    nothing left to do."""
    old, _new = taken_again_as_before(home, monkeypatch)
    said = home.rename("--apply")
    names = {p.read_bytes(): p.name for p in home.files().values()}
    stem = old.name[:-len(" EOB1.pdf")]
    told = [n for n in names.values() if n.startswith(stem + " ")]
    assert len(told) == 2, (names, said[-1500:])
    for name in told:
        assert name in (stem + " EOB 1.pdf", stem + " EOB 1 (2).pdf"), (name, said[-1500:])
    said = home.rename()
    assert NAMED_ALREADY in said, said[-1500:]


# -- every app, read from its code ---------------------------------------------------

def entries():
    return sorted(p for d in (REPO / "apps").iterdir() if d.is_dir()
                  for p in [*d.glob("*_docs.py"), *d.glob("*_receipts.py")])


# How an app writes down a document's record. Each takes the object first,
# except progress.update, which takes the key and then the record.
RECORDERS = {"self._record": 0, "self._record_state": 0, "self.download_one": 1,
             "self.progress.update": 1}


# What a name or Rename's match of a row to its record is made from
# (naming.fields_of, renaming._key_of_record). A record made from the one a
# file was named from must not write another value over any of them.
NAMING_FIELDS = {"date", "purchase_date", "title", "summary", "category", "document_type",
                 "order_number", "document_id", "account", "total", "store_info",
                 "purchase_type"}

# A parameter of these is an app's own whole record, which every app
# writes down whole (_record, _record_state).
RECORD_CLASSES = {"Document", "Purchase"}


def _built_from(node, name: str) -> bool:
    """The record handed over is the object itself, or a dict made from it
    by dict(obj, ...) or {**obj, ...} that writes nothing over a field a
    name is made from."""
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "dict" and node.args:
        return (_built_from(node.args[0], name)
                and not any(kw.arg in NAMING_FIELDS for kw in node.keywords))
    if isinstance(node, ast.Dict):
        return (any(k is None and _built_from(v, name) for k, v in zip(node.keys, node.values))
                and not any(isinstance(k, ast.Constant) and k.value in NAMING_FIELDS
                            for k in node.keys))
    return False


def _says_where(node) -> bool:
    """A record handed to progress.update that says where a file is."""
    if isinstance(node, ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value == "pdf_path" for k in node.keys)
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "dict":
        return (any(kw.arg == "pdf_path" for kw in node.keywords)
                or any(_says_where(a) for a in node.args))
    return False


def written_apart(holders, name: str) -> list:
    """Each line where these functions write down where a file is in a
    record not made from the one they name it from."""
    return [node.lineno for fn in holders for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func) == "self.progress.update" and len(node.args) == 2
            and _says_where(node.args[1]) and not _built_from(node.args[1], name)]


def namings(path: Path):
    """Each build_pdf_filename call in the file, with the functions holding
    it, innermost last, and what it names the file from."""
    def visit(node, holders):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from visit(child, holders + [child])
                continue
            if (holders and isinstance(child, ast.Call)
                    and ast.unparse(child.func) == "build_pdf_filename"):
                record = next((kw.value for kw in child.keywords if kw.arg == "record"), None)
                yield holders, child, record
            yield from visit(child, holders)
    yield from visit(ast.parse(path.read_text(encoding="utf-8-sig")), [])


def written_down(holders, name: str) -> bool:
    """Whether the function writes down, or hands on to be written down,
    the very record it names a file from. A parameter counts only when it
    is the app's own Document or Purchase, which its callers hold and every
    app writes down whole, and never a row or a dict handed in. A function
    inside another names from the enclosing one's record, as Amazon's
    target() named each invoice of an order from the order its function
    wrote down."""
    for fn in reversed(holders):
        params = {a.arg: a for a in fn.args.args + fn.args.kwonlyargs}
        if name in params:
            annotation = params[name].annotation
            return annotation is not None and ast.unparse(annotation) in RECORD_CLASSES
        # A local name given such a record first, as "rec = dict(record, ...)"
        # is, so the same record can be shown to saved_copy.holds as well.
        aliases = {target.id for node in ast.walk(fn) if isinstance(node, ast.Assign)
                   for target in node.targets
                   if isinstance(target, ast.Name) and _built_from(node.value, name)}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                at = RECORDERS.get(ast.unparse(node.func))
                if at is not None and len(node.args) > at and (
                        _built_from(node.args[at], name)
                        or any(_built_from(node.args[at], alias) for alias in aliases)):
                    return True
    return False


def test_there_are_namings_to_check():
    """Not a check that passes because it found nobody."""
    found = [(p, holders[-1].name) for p in entries() for holders, _call, _rec in namings(p)]
    assert len({p.parent.name for p, _fn in found}) >= 61, found
    assert "_save_collected" in {fn for p, fn in found if p.parent.name == "anthem"}
    assert "_place_invoice" in {fn for p, fn in found if p.parent.name == "amazon"}


CANARY = '''
class App:
    def row_to_a_helper(self, rows):
        for r in rows:
            self.save_row(r)

    def save_row(self, r: dict):
        return build_pdf_filename("2026-01-01", "x", "", record=r)

    def id_written_over(self, r):
        record = {"title": r["label"], "document_id": r["doc_id"]}
        name = build_pdf_filename("2026-01-01", "x", "", record=record)
        self.progress.update(r["key"], dict(record, document_id="", pdf_path=name))

    def put_aside_apart(self, r):
        record = {"title": r["label"], "document_id": r["doc_id"]}
        name = build_pdf_filename("2026-01-01", "x", "", record=record)
        self.progress.update(r["key"], dict(record, pdf_path=name))
        self.progress.update(r["key"], {"title": r["label"], "pdf_path": name})

    def whole_record(self, doc: Document):
        return build_pdf_filename(doc.date, doc.summary, "", record=doc)

    def written_from_it(self, r):
        record = {"title": r["label"], "document_id": r["doc_id"]}
        name = build_pdf_filename("2026-01-01", "x", "", record=record)
        self.progress.update(r["key"], dict(record, state="Completed", pdf_path=name))

    def several_parts(self, doc: Document):
        def named_inside(i):
            return build_pdf_filename(doc.date, doc.summary, "", part=(i, 2), record=doc)
        return [named_inside(1), named_inside(2)]
'''


def test_the_census_tells_each_shape_apart(tmp_path):
    """The census refuses a row handed to a helper, an id written over the
    record a file was named from, and a file written down apart from it,
    and passes an app's own Document, named inside a function of its own
    or not, and a record written from the one the file was named from."""
    source = tmp_path / "canary_docs.py"
    source.write_text(CANARY, encoding="utf-8")
    verdict = {}
    for holders, _call, record in namings(source):
        verdict[holders[-1].name] = (written_down(holders, record.id)
                                     and not written_apart(holders, record.id))
    assert verdict == {"save_row": False, "id_written_over": False,
                       "put_aside_apart": False, "whole_record": True,
                       "written_from_it": True, "named_inside": True}, verdict


def test_every_app_names_a_file_from_the_record_it_writes_down():
    """A file named from one record and written down by another is offered
    a new name by Rename, and Anthem's lists named theirs from the row a
    list gave and wrote down a dict made apart from it.

    What tells a second file of one name apart is not read here. The
    rename census holds every app's download_one to it, and a later step
    that renames a saved file, as Ally's name from a statement's contents,
    is held by neither."""
    wrong = []
    for path in entries():
        for holders, call, record in namings(path):
            where = "%s:%d %s" % (path.relative_to(REPO).as_posix(), call.lineno,
                                  holders[-1].name)
            if not isinstance(record, ast.Name):
                wrong.append("%s names a file from no record of its own" % where)
                continue
            if not written_down(holders, record.id):
                wrong.append("%s names a file from %r and writes down another record"
                             % (where, record.id))
            apart = written_apart(holders, record.id)
            if apart:
                wrong.append("%s names a file from %r and writes down where it is apart "
                             "from it, line %s" % (where, record.id, apart))
    assert not wrong, "\n".join(wrong)
