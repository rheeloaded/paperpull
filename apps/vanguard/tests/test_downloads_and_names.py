"""What the maintainer's review of #57 changed, each held here.

The browser's own copy of a statement never stays beside the one the app
saved. A statement is named for its account once. Discover walks the year
picker once, and Diagnose takes no screenshot of a brokerage page. Every
account, holder and amount is invented."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import vanguard_docs as docs
import vanguard_site as site
from paperpull_core import doc_types
from paperpull_core.testkit import sample_pdf

TITLE = "Account Statement - Example Holder — Cash Plus Account — 1234567"
LABEL = ("Download a pdf statement generated on August 31, 2026 with "
         "description Example Holder — Cash Plus Account — 1234567")
PDF = sample_pdf()


# -- the download ----------------------------------------------------------------

VANGUARD_NAME = "2026-08 VG Statement Cash Plus Account x4567.pdf"


class _Icon:
    """The row's download icon. Pressing it has the browser save its own
    copy under Vanguard's name into whatever folder it was last pointed at."""

    def __init__(self, page, saves=True):
        self.page, self.saves, self.clicked = page, saves, 0

    def get_attribute(self, name):
        return LABEL if name == "aria-label" else None

    def click(self, **kw):
        self.clicked += 1
        if self.saves:
            self.page.saves_into.mkdir(parents=True, exist_ok=True)
            (self.page.saves_into / VANGUARD_NAME).write_bytes(PDF)


class _Rows:
    """page.locator(...).filter(...).filter(...).first.get_by_title(...).first,
    and the statements table that on_documents_page counts."""

    def __init__(self, icon):
        self.icon = icon

    def filter(self, **kw):
        return self

    @property
    def first(self):
        return self

    def get_by_title(self, _title):
        return _Title(self.icon)

    def count(self):
        return 1


class _Title:
    def __init__(self, icon):
        self.first = icon


class _Cdp:
    def __init__(self, page):
        self.page = page

    def send(self, method, params):
        if method == "Browser.setDownloadBehavior":
            self.page.saves_into = Path(params["downloadPath"])


class _Context:
    def __init__(self, page):
        self.page = page

    def new_cdp_session(self, _page):
        return _Cdp(self.page)


class _Download:
    suggested_filename = VANGUARD_NAME

    def __init__(self, page):
        self.page = page

    def save_as(self, path):
        Path(path).write_bytes((self.page.saves_into / VANGUARD_NAME).read_bytes())


class _Page:
    url = "https://statements.web.vanguard.com/"

    def __init__(self, own_downloads, event=True, saves=True):
        self.saves_into = own_downloads     # the browser's own folder until told otherwise
        self.icon = _Icon(self, saves)
        self.event = event
        self.context = _Context(self)

    def locator(self, sel):
        return _Rows(self.icon)

    def evaluate(self, js, arg=None):
        return True

    def wait_for_timeout(self, ms):
        pass

    def expect_download(self, timeout=None):
        page = self

        class _Waiting:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                if not page.event:
                    raise RuntimeError("no download event")
                self.value = _Download(page)
                return False
        return _Waiting()


def _download(tmp_path, **kw):
    own = tmp_path / "Downloads"
    staging = tmp_path / ".vanguard-downloads"
    archive = tmp_path / "Statements"
    archive.mkdir()
    page = _Page(own, **kw)
    out = archive / "2026-08-31 Vanguard Account Statement.pdf"
    got = site.download_document(page, account_id="123400000000001", charitable=False,
                                 doc_type="Statement", title=TITLE, date="2026-08-31",
                                 out_path=out, dl_dir=staging)
    return got, page, archive, staging, out


def test_the_browsers_own_copy_never_stays_in_the_archive(tmp_path):
    """Pointed at the archive folder, the browser saved its own copy under
    Vanguard's name beside every statement the app saved."""
    got, page, archive, staging, out = _download(tmp_path)
    assert got is True and page.icon.clicked == 1
    assert page.saves_into == staging
    assert sorted(p.name for p in archive.iterdir()) == [out.name]
    assert out.read_bytes() == PDF
    assert list(staging.iterdir()) == [], "and the staging folder does not keep it either"
    assert not (tmp_path / "Downloads").exists()


def test_a_statement_saved_without_the_event_is_taken_from_the_staging_folder(tmp_path):
    """A real Edge or Chrome can save a download itself and raise no event."""
    got, _page, archive, staging, out = _download(tmp_path, event=False)
    assert got is True and out.read_bytes() == PDF
    assert sorted(p.name for p in archive.iterdir()) == [out.name]
    assert list(staging.iterdir()) == []


def test_nothing_is_left_when_nothing_arrives(tmp_path):
    got, _page, archive, staging, _out = _download(tmp_path, event=False, saves=False)
    assert got is False
    assert list(archive.iterdir()) == []
    assert list(staging.iterdir()) == []


def test_without_a_staging_folder_the_browser_is_left_where_it_is(tmp_path):
    """Only the download event is taken then, and no folder is made."""
    own = tmp_path / "Downloads"
    page = _Page(own)
    out = tmp_path / "Statements" / "x.pdf"
    got = site.download_document(page, account_id="123400000000001", charitable=False,
                                 doc_type="Statement", title=TITLE, date="2026-08-31",
                                 out_path=out)
    assert got is True and out.read_bytes() == PDF
    assert page.saves_into == own
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Downloads", "Statements"]


# -- names, discovery and Diagnose ------------------------------------------------

class _Store:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def update(self, key, value, save=True):
        self.data.setdefault(key, {}).update(value)

    def save(self, backup=False):
        pass


def _app(tmp_path=None):
    app = docs.App.__new__(docs.App)
    app.args = SimpleNamespace(start_date=None, end_date=None, year=None, type=None,
                               account=None, max_docs=None, redownload=False)
    app.config = {"document_types": list(storage.ALL_CATEGORIES), "account_labels": {},
                  "default_start_date": ""}
    app.rules = doc_types.load_rules()
    app.stats = {"skipped_out_of_scope": 0, "discovered": 0}
    app.discovery, app.progress = _Store(), _Store()
    app._journal = app._requests = None
    if tmp_path is not None:
        app.paths = storage.Paths(tmp_path)
        app.paths.ensure()
    return app


def _listed():
    """One statement as list_documents hands it over."""
    return {"account": "Example Holder — Cash Plus Account — 1234567",
            "account_id": "123400000000001", "last4": "4567", "date": "2026-08-31",
            "period": "2026-08", "title": TITLE, "category": "Statement",
            "statement_id": "opaque==", "doc_type": "Statement", "occurrence": 0}


def test_a_statement_is_named_for_its_account_once():
    app = _app()
    assert app._record_vanguard_doc(_listed(), set()) == 1
    [rec] = app.discovery.data.values()
    assert rec["summary"] == TITLE
    assert storage.build_pdf_filename(rec["date"], rec["summary"], "", record=rec).count(
        "Cash Plus Account") == 1


def test_a_statement_saved_under_the_doubled_name_is_given_the_new_one():
    """The name a record carries is what Rename reads, so a file saved under
    the doubled name can take the new one without being downloaded again.
    The key is the title and does not change."""
    app = _app()
    app._record_vanguard_doc(_listed(), set())
    [key] = app.discovery.data
    app.discovery.data[key].update(summary=TITLE + " - Example Holder — Cash Plus "
                                   "Account — 1234567", downloaded_ok=True)
    assert app._record_vanguard_doc(_listed(), set()) == 0
    assert list(app.discovery.data) == [key]
    assert app.discovery.data[key]["summary"] == TITLE
    assert app.discovery.data[key]["downloaded_ok"] is True


def test_rename_moves_a_file_saved_under_the_doubled_name(tmp_path, capsys):
    """What the contributor's own 135 statements need, end to end. Discover
    runs again with this build and Rename then gives every file the name a
    download would give it today, without downloading anything."""
    app = _app(tmp_path)
    app.args.apply = False
    app.config.update(max_path_length=240, min_pdf_bytes=1000)
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.index_csv = storage.CsvFile(app.paths.document_index_csv,
                                    storage.DOCUMENT_INDEX_COLUMNS)
    app._record_vanguard_doc(_listed(), set())
    [key] = app.discovery.data
    doubled = TITLE + " - Example Holder — Cash Plus Account — 1234567"
    rec = dict(app.discovery.data[key], summary=doubled)
    folder = app.paths.folder_for("Statement")
    old = folder / storage.build_pdf_filename(rec["date"], doubled, "", record=rec)
    old.write_bytes(PDF)
    rec.update(state=docs.State.COMPLETED.value, downloaded_ok=True,
               pdf_filename=old.name, pdf_path=str(old))
    app.progress.update(key, dict(rec))
    app.discovery.update(key, dict(rec))
    app.index_csv.append_rows([{
        "Document Date": rec["date"], "Category": "Statement",
        "Document Summary": doubled, "Document Title": rec["title"],
        "PDF Filename": old.name, "PDF Full Path": str(old),
        "Processing Status": "Completed"}])

    app._record_vanguard_doc(_listed(), set())
    app.args.apply = True
    app.cmd_rename()
    new = storage.build_pdf_filename(rec["date"], TITLE, "", record=app.discovery.get(key))
    assert new.count("Cash Plus Account") == 1
    assert sorted(p.name for p in folder.glob("*.pdf")) == [new]
    assert app.index_csv.read_all()[0]["PDF Filename"] == new
    assert list(app.progress.data) == [key]
    assert app._already_done(docs.Document.from_dict(app.discovery.get(key)))


def test_discover_walks_the_year_picker_once(monkeypatch):
    """list_accounts walked every year of the picker to learn that no account
    is a charitable one, and then the documents were read by a second walk."""
    app = _app()
    page = SimpleNamespace(url="https://statements.web.vanguard.com/")
    app.page = lambda: page
    app.check_session = lambda p: None
    monkeypatch.setattr(site, "ensure_statements", lambda p: True)
    walks = []
    monkeypatch.setattr(site, "list_accounts", lambda p: walks.append("accounts") or [])
    monkeypatch.setattr(site, "collect_documents",
                        lambda p, keep=None: walks.append("documents") or [_listed()])
    assert app.cmd_discover(quiet=True) == 1
    assert walks == ["documents"]


def test_diagnose_takes_no_screenshot_and_reads_what_vanguard_sends(tmp_path, monkeypatch):
    app = _app(tmp_path)

    class _NoPictures:
        url = "https://statements.web.vanguard.com/"

        def title(self):
            return "Statements"

        def screenshot(self, **kw):
            raise AssertionError("Diagnose took a screenshot of a brokerage page")

        def locator(self, sel):
            return SimpleNamespace(count=lambda: 0, inner_text=lambda timeout=0: "")

    page = _NoPictures()
    app.page = lambda: page
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    stmt = {"accountId": "123400000000001", "accountNumber": "1234567",
            "statementDescription": "Example Holder — Cash Plus Account — 1234567",
            "endDate": "2026-08-31", "frequencyType": "MONTHLY",
            "statementType": "ACCOUNT_GROUP", "statementId": "opaque=="}
    walks = []
    monkeypatch.setattr(site, "collect_statements_json",
                        lambda p, years=None, keep=None: walks.append(1) or [stmt])
    monkeypatch.setattr(site, "list_accounts",
                        lambda p: (_ for _ in ()).throw(AssertionError("a second walk")))
    monkeypatch.setattr(site, "read_page_ui", lambda p: {"years": ["2026", "2025"]})
    app.cmd_diagnose()
    info = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(
        encoding="utf-8"))
    assert not info.get("error"), info.get("error")
    assert walks == [1]
    assert info["documents_total"] == 1
    assert info["documents_by_category"] == {"Statement": 1}
    assert info["samples"][0]["date"] == "2026-08-31"
    assert info["rendered"] == {"years": ["2026", "2025"]}
    assert "1234567" not in json.dumps(info["documents_by_account"])
    assert not list(app.paths.diagnostics.glob("*.png"))
