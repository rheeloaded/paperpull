"""ING's own main against a made-up Postbox and archive.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. Only the tab
is stood in, by one that answers the two things this app asks of a page: its
rows, as _ROWS_JS hands them back, and the fetch of one link. So the app's
own session checks, listing, numbering, resolve_item and download_document
all run.

Its links work the way Apache Wicket's do, which ING's pages are probably
built with: each carries the version of the page it was read from, every
page opened is a new version, and only the page on screen answers a link.
Every PDF carries the name of the document it is, so a file is known by its
bytes and never by its name.

Whether ING's Postbox looks or answers like this is checked only on an
account (README). Every subject and date here is invented.
"""
import base64
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import ing_docs as docs
import ing_site as site
from paperpull_core import intake
from paperpull_core import storage as core_storage
from paperpull_core.models import State
from paperpull_core.run_reporting import ListNotRead

APP = Path(__file__).resolve().parents[1]
POSTBOX = site.URLS["documents"]
ARCHIVE = site.URLS["archive"]
LISTS = {"postbox": POSTBOX, "archive": ARCHIVE}
A_PAGE = {"state": "page", "password": False}


def pdf_of(document: str) -> bytes:
    """A PDF that opens, with a page, carrying which document it is."""
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Subject": "document %s" % document})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue().ljust(4000, b" ")


def whose(body: bytes) -> str:
    return body.split(b"(document ", 1)[1].split(b")", 1)[0].decode()


def listed(document, kind, subject, date, unread=False, moves=False):
    """A Postbox row as it shows: its type, subject and date. `moves` gives
    it, in place of a download link, one that would archive it."""
    return {"doc": document, "kind": kind, "subject": subject, "date": date,
            "unread": unread, "moves": moves}


def statement(document, month=1, year=2026, **more):
    return listed(document, "Kontoauszug", "Kontoauszug %02d/%d" % (month, year),
                  "28.%02d.%d" % (month, year), **more)


def tax(document, year=2025):
    return listed(document, "Steuerbescheinigung", "Jahressteuerbescheinigung %d" % year,
                  "15.02.%d" % (year + 1))


class _Locator:
    def __init__(self, bank, selector):
        self.bank, self.selector = bank, selector

    def count(self):
        return 1 if self.bank.password and "password" in self.selector else 0

    def inner_text(self, timeout=None):
        return self.bank.body


class Bank:
    """ING's banking site in the one tab a run works in.

    `lists` holds what the Postbox and its archive show. Each switch below
    names the lists that show what this app does not read whole, and
    `answer_with` what fetching a document answers in place of its PDF.
    What the app asked of the tab is kept, and anything it should never
    ask goes in `acted`."""

    def __init__(self):
        self.url = POSTBOX
        self.lists = {"postbox": [], "archive": []}
        self.version = 1
        self.pager, self.loading, self.cut, self.menus, self.blank = set(), set(), set(), set(), set()
        self.password = False
        self.signs_out_at = None     # an address that opens ING's sign-in form
        self.body = ""
        self.answer_with = {}
        self.gotos, self.looked, self.fetched, self.stale, self.acted = [], [], [], [], []

    def goto(self, url, **_):
        self.gotos.append(url)
        self.version += 1
        self.url = url
        if url == self.signs_out_at:
            self.password = True

    def wait_for_timeout(self, _ms):
        pass

    def title(self):
        return "Internetbanking"

    def locator(self, selector):
        return _Locator(self, selector)

    def evaluate(self, js, arg=None):
        if isinstance(arg, dict) and "rowSelectors" in arg:
            return self._rows()
        if isinstance(arg, dict) and "url" in arg and "const ppLimit" in js \
                and arg.get("host") == "banking.ing.de":
            return self._fetch(arg["url"])
        self.acted.append("an evaluate this app does not make")
        raise AssertionError(self.acted[-1])

    def _rows(self):
        area = site._list_area(self.url)
        self.looked.append(area)
        # A sign-in page shows no list.
        if area is None or area in self.blank or self.password:
            return {"table_present": False, "settled": True, "truncated": False,
                    "empty": False, "pagination": 0, "rows": []}
        rows = [self._row(area, e) for e in self.lists[area]]
        return {"table_present": bool(rows), "settled": area not in self.loading,
                "truncated": area in self.cut, "empty": not rows,
                "pagination": int(area in self.pager), "rows": rows}

    def _row(self, area, e):
        action = "archivieren" if e["moves"] else "download"
        hrefs = [] if area in self.menus else [
            "%s?%d-1.-rows-%s-%s" % (LISTS[area], self.version, e["doc"], action)]
        return {"kind": e["kind"], "subject": e["subject"], "date": e["date"],
                "unread": e["unread"], "hrefs": hrefs}

    def _fetch(self, url):
        area = site._list_area(url)
        m = re.fullmatch(r"(\d+)-1\.-rows-(\w+)-(\w+)", urlsplit(url).query)
        if not area or not m:
            self.acted.append("fetched an address no row showed")
            raise AssertionError(self.acted[-1])
        version, name, action = int(m.group(1)), m.group(2), m.group(3)
        if action != "download":
            self.acted.append("fetched a link that would archive " + name)
        self.fetched.append(name)
        # Only the page on screen answers a link, and a link read on an
        # earlier version of it answers with a page, as an expired one does.
        if version != self.version or site._list_area(self.url) != area:
            self.stale.append(name)
            return dict(A_PAGE)
        if not any(e["doc"] == name for e in self.lists[area]):
            return dict(A_PAGE)
        answer = self.answer_with.get(name)
        if answer == "expired":
            # ING let go of the page the link was read from, so its links
            # answer with a page until the list is opened afresh.
            self.answer_with[name] = ("expired", self.version)
            return dict(A_PAGE)
        if isinstance(answer, tuple):
            if answer[1] == self.version:
                return dict(A_PAGE)
            del self.answer_with[name]
            answer = None
        if answer == "page":
            return dict(A_PAGE)
        # The browser did not finish the fetch: the connection dropped, or
        # the link led on to another host, which a same-origin fetch refuses.
        if answer == "failed":
            return {"state": "failed"}
        if answer == "failed-once":
            del self.answer_with[name]
            return {"state": "failed"}
        if answer == "sign-in":
            return {"state": "page", "password": True}
        if answer == "large":
            raise RuntimeError(intake.READ_MARK + " of 10 bytes, 20")
        if isinstance(answer, int):
            return {"state": "status", "status": answer}
        return {"state": "file", "b64": base64.b64encode(pdf_of(name)).decode()}


class Home:
    def __init__(self, tmp_path, monkeypatch, capsys):
        self.bank = Bank()
        self.capsys = capsys
        self.out = tmp_path / "out"
        self.config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
        self.cfg = tmp_path / "config.json"
        self.configure(owner="Dana Example", output_dir=str(self.out),
                       profile_dir=str(tmp_path / "profile"), cdp_url="http://127.0.0.1:9",
                       delay_min_seconds=0, delay_max_seconds=0, default_start_date="")
        # The made-up archive is empty unless a test fills it, and an empty
        # list shows only ING's notice that nothing matches, which a run
        # cannot tell from a filter (#203). So these accounts leave the
        # archive out, as the app asks of one, and a test that fills it
        # reads it.
        self.configure(read_archive=False)
        for name in ("_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        monkeypatch.setattr(docs.App, "page", lambda app: self.bank)
        monkeypatch.setattr(docs.App, "_on_its_site", lambda app: self.bank)
        monkeypatch.setattr(docs.App, "close", lambda app: None)
        # Nobody at a console, as under the panel, so a run that would wait
        # for the person stops instead.
        monkeypatch.setattr(docs.browser_launcher, "can_ask", lambda: False)
        monkeypatch.setattr(docs.browser_launcher, "_NOBODY_ANSWERED", False)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        self.stopped = None

    def configure(self, **settings):
        self.config.update(settings)
        self.cfg.write_text(json.dumps(self.config), encoding="utf-8")

    def run(self, *flags):
        """The app's main and what it said, each run as a process of its own
        with no listing kept from the run before. A run that stops leaves on
        SystemExit, kept in `stopped`, and its code is answered."""
        self.capsys.readouterr()
        for kept in (self.bank.gotos, self.bank.looked, self.bank.fetched, self.bank.stale):
            kept.clear()
        site._listing.clear()
        self.stopped = None
        try:
            code = docs.main(["--config", str(self.cfg), *flags])
        except SystemExit as stop:
            self.stopped, code = stop, stop.code
        said = " ".join(self.capsys.readouterr().out.split())
        assert self.bank.acted == []
        # Only the two lists are ever opened, by their own addresses.
        assert set(self.bank.gotos) <= {POSTBOX, ARCHIVE}
        return code, said

    def run_all(self, *flags):
        return self.run("--all", "--yes", *flags)

    def store(self, name: str) -> dict:
        path = self.out / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def on_disk(self) -> list:
        """Whose bytes each PDF under the output folder holds."""
        return sorted(whose(p.read_bytes()) for p in self.out.rglob("*.pdf"))

    def held(self) -> dict:
        """Whose bytes each saved record's file holds, by key."""
        return {key: whose(Path(rec["pdf_path"]).read_bytes())
                for key, rec in sorted(self.store("progress.json").items())
                if isinstance(rec, dict) and rec.get("downloaded_ok")}

    def failed(self) -> list:
        """The notes of each record that failed, by key."""
        return [rec.get("notes", "") for _key, rec in sorted(self.store("progress.json").items())
                if isinstance(rec, dict) and rec.get("state") == State.FAILED.value]

    def listed_whole(self) -> bool:
        return self.store("last-listing.json").get("complete") is True


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    return Home(tmp_path, monkeypatch, capsys)


def discover_stops(home) -> str:
    """Discover stopped with its list not called whole, nothing recorded and
    nothing fetched, and what it said."""
    code, said = home.run("--discover")
    assert home.stopped is not None and code == 1
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}
    assert home.bank.fetched == []
    return said


# -- a run that reads everything -------------------------------------------------

def test_a_run_saves_the_postbox_and_the_archive_each_with_its_own_bytes(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1), tax("P2")]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    code, said = home.run_all()
    assert code == 0 and home.stopped is None
    assert home.on_disk() == ["A1", "P1", "P2"]
    assert sorted(home.held().values()) == ["A1", "P1", "P2"]
    assert home.listed_whole()
    assert home.bank.stale == []
    assert "Discovery complete. Documents known: 3" in said


def test_discover_lists_both_and_fetches_nothing(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [tax("A1", 2019)]
    code, said = home.run("--discover")
    assert code == 0 and home.stopped is None
    assert home.bank.fetched == []
    assert len(home.store("discovery.json")) == 2
    assert home.listed_whole()
    assert "Discovery complete. Documents known: 2" in said


def test_a_second_run_takes_nothing_again_though_its_list_comes_in_another_order(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2), tax("P3")]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    assert home.run_all()[0] == 0
    home.bank.lists["postbox"].reverse()
    code, said = home.run_all()
    assert code == 0
    assert home.bank.fetched == []
    assert home.on_disk() == ["A1", "P1", "P2", "P3"]
    assert said.count("Already downloaded and verified - skipping.") == 4


def test_a_document_moved_to_the_archive_is_not_taken_again(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    assert home.run_all()[0] == 0
    home.bank.lists["archive"] = [home.bank.lists["postbox"].pop()]
    code, _said = home.run_all()
    assert code == 0 and home.bank.fetched == []
    assert home.on_disk() == ["P1", "P2"]


def test_a_pilot_then_a_run_takes_each_document_once(home):
    home.configure(pilot_count=1)
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    assert home.run("--pilot")[0] == 0
    assert home.bank.fetched == ["P2"]
    assert home.run_all()[0] == 0
    assert home.bank.fetched == ["P1"]
    assert home.on_disk() == ["P1", "P2"]


# -- a list that shows only ING's notice that nothing matches ------------------
# A made-up list with no rows shows ING's notice, "Zu Ihrer Suche können keine
# Dokumente angezeigt werden" ("empty"). ING shows it for an empty list and for
# a search or filter that finds nothing (#203), so it never shows a list empty.

def notice_said(area: str) -> str:
    where = site.named(area)
    return "!! %s shows no document, only ING's notice that nothing matches." % (
        where[0].upper() + where[1:])


@pytest.mark.parametrize("area,other", [("archive", "postbox"), ("postbox", "archive")])
def test_a_list_showing_only_the_notice_is_left_out_and_the_run_stops_at_its_end(
        home, area, other):
    home.configure(read_archive=True)
    home.bank.lists[other] = [statement("K1", 1)]
    code, said = home.run_all()
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == ["K1"] and home.failed() == []
    assert not home.listed_whole()
    assert notice_said(area) in said
    assert ("This run did not read %s, which showed only ING's notice that nothing "
            "matches, so it stops here rather than finish." % site.named(area)) in said
    if area == "archive":
        assert 'set "read_archive" to false in config.json' in said
    else:
        assert "If ING shows a search or filter set on the Postbox, clear it there" in said
    assert list((home.out / "Diagnostics").glob("failure-*.json"))


def test_discover_with_a_list_showing_only_the_notice_records_the_rest_and_stops(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    code, said = home.run("--discover")
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert len(home.store("discovery.json")) == 1
    assert home.bank.fetched == [] and not home.listed_whole()
    assert "Discovery read part of the list. Documents known: 1" in said
    assert notice_said("archive") in said


def test_an_empty_postbox_and_archive_stop_rather_than_finish(home):
    home.configure(read_archive=True)
    code, said = home.run_all()
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == [] and not home.listed_whole()
    assert notice_said("postbox") in said and notice_said("archive") in said
    assert "This run did not read the Postbox and the Postbox archive" in said


def test_a_pilot_with_nothing_to_take_still_stops_when_a_list_was_left_out(home):
    code, said = home.run("--pilot")
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert "No documents in scope to pilot." in said
    assert notice_said("postbox") in said and not home.listed_whole()


def test_a_document_whose_list_shows_only_the_notice_is_left_for_now_not_failed(home):
    """A document listed before, whose list now shows only the notice (a
    filter set in ING, say), is neither failed nor called gone. Nothing is
    recorded for it, and a run that reads its list again takes it."""
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2027)]
    assert home.run("--discover")[0] == 0 and home.listed_whole()
    held_back, home.bank.lists["archive"] = home.bank.lists["archive"], []
    code, said = home.run_all()
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == ["P1"] and home.failed() == []
    assert ("Left for now, since the Postbox archive showed only ING's notice that "
            "nothing matches.") in said
    home.bank.lists["archive"] = held_back
    code, said = home.run_all()
    assert code == 0 and home.stopped is None
    assert home.on_disk() == ["A1", "P1"] and home.listed_whole()


def test_resume_leaves_a_document_whose_list_shows_only_the_notice_and_stops(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    assert home.run("--discover")[0] == 0 and home.listed_whole()
    home.bank.lists["archive"] = []
    code, said = home.run("--resume")
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == ["P1"] and home.failed() == []
    assert not home.listed_whole()
    # P1's listing showed the archive left out, so A1 after it is left for
    # now rather than looked up.
    assert ("Left for now, since the Postbox archive showed only ING's notice that "
            "nothing matches.") in said
    assert "could not be read again whole" not in said


def test_a_list_left_out_stops_the_run_though_a_later_listing_reads_it(home, monkeypatch):
    """What the run recorded came from a listing that left the archive out,
    so the run is not whole, whatever a later look for one document reads."""
    monkeypatch.setattr(site, "LISTING_SECONDS", 0)
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    opened, real = [], home.bank.goto

    def goto(url, **kw):
        if url == ARCHIVE:
            opened.append(url)
            if len(opened) == 2:
                home.bank.lists["archive"] = [statement("A1", 1, 2019)]
        real(url, **kw)

    monkeypatch.setattr(home.bank, "goto", goto)
    code, _said = home.run_all()
    assert len(opened) >= 2
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == ["P1"] and not home.listed_whole()


def test_a_pilot_that_takes_a_document_still_stops_when_a_list_was_left_out(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    code, said = home.run("--pilot")
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.on_disk() == ["P1"] and not home.listed_whole()
    assert "PILOT RESULTS" in said


def test_a_list_first_showing_only_the_notice_while_a_document_is_taken_stops_at_once(
        home, monkeypatch):
    """The listing read the archive, and the archive shows only the notice
    when the first document's link is read from it again (a filter set in
    ING meanwhile, say). Every later document would read the same list, so
    the run stops there, with nothing fetched or recorded."""
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2027), statement("A2", 2, 2027)]
    opened, real = [], home.bank.goto

    def goto(url, **kw):
        if url == ARCHIVE:
            opened.append(url)
            if len(opened) == 2:
                home.bank.lists["archive"] = []
        real(url, **kw)

    monkeypatch.setattr(home.bank, "goto", goto)
    code, said = home.run_all()
    assert isinstance(home.stopped, ListNotRead) and code == 0
    assert home.bank.fetched == [] and home.store("progress.json") == {}
    assert not home.listed_whole()
    assert ("The ING list could not be read again whole (the Postbox archive shows no "
            "document, only ING's notice that nothing matches)") in said


def test_resume_whose_first_document_is_of_a_list_showing_only_the_notice_stops_at_once(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2027)]
    assert home.run("--discover")[0] == 0 and home.listed_whole()
    home.bank.lists["archive"] = []
    _code, said = home.run("--resume")
    assert isinstance(home.stopped, ListNotRead)
    assert home.bank.fetched == [] and home.store("progress.json") == {}
    assert not home.listed_whole()
    assert "The ING list could not be read again whole" in said


def test_a_row_alike_to_a_document_of_a_list_left_out_takes_nothing_of_its_record(home):
    """A new Postbox row alike to an archived document, while the archive
    shows only the notice, is not taken for that document. Once the
    archive is read again, each is saved with its own bytes."""
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("T1", 3)]
    home.bank.lists["archive"] = [statement("A1", 1)]
    assert home.run("--discover")[0] == 0 and home.listed_whole()
    before = home.store("discovery.json")
    archived, home.bank.lists["archive"] = home.bank.lists["archive"], []
    home.bank.lists["postbox"].append(statement("P1", 1))
    home.run_all()
    assert isinstance(home.stopped, ListNotRead)
    after = home.store("discovery.json")
    for key, rec in before.items():
        if rec["client_id"] == "archive":
            assert (after[key]["client_id"], after[key]["item_id"]) == (
                "archive", rec["item_id"])
    assert sorted(home.held().values()) == ["T1"]
    home.bank.lists["archive"] = archived
    code, _said = home.run_all()
    assert code == 0 and home.stopped is None
    assert sorted(home.held().values()) == ["A1", "P1", "T1"]
    assert home.failed() == []


def test_a_run_that_left_a_list_out_and_stopped_for_a_sign_in_is_not_noted_whole(home):
    """However the run ends, a listing that left a list out is not noted
    whole, so a Resume after a sign-in says the list was not read rather
    than finish with only what that listing held."""
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.answer_with["P1"] = "sign-in"
    code, _said = home.run_all()
    assert isinstance(home.stopped, SystemExit) and code == 0
    assert not isinstance(home.stopped, ListNotRead)
    assert not home.listed_whole()
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    del home.bank.answer_with["P1"]
    _code, said = home.run("--resume")
    assert "The last run stopped before it read ING's whole list" in said
    assert isinstance(home.stopped, ListNotRead)


def test_read_archive_false_never_opens_the_archive(home):
    home.configure(read_archive=False)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    code, _said = home.run_all()
    assert code == 0
    assert ARCHIVE not in home.bank.gotos and "archive" not in home.bank.looked
    assert home.on_disk() == ["P1"]


def test_no_document_link_is_kept_on_disk(home):
    """A link carries the page it was read from, and may carry the session,
    so only the list's own address is written anywhere."""
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    assert home.run_all()[0] == 0
    written = [p for p in home.out.rglob("*") if p.is_file() and p.suffix != ".pdf"]
    assert written
    for path in written:
        assert "-rows-" not in path.read_text(encoding="utf-8", errors="replace"), path.name


class BankOfPlaces(Bank):
    """A Postbox whose links name a row by its place in the list, followed
    against the list as the server holds it when the link is fetched, the
    way a page framework's list may. The page on screen shows the rows as
    they were when it was last opened, and only an opening shows newer."""

    def __init__(self):
        super().__init__()
        self.shown = {"postbox": [], "archive": []}
        self.after_first_fetch = None

    def goto(self, url, **kw):
        super().goto(url, **kw)
        area = site._list_area(url)
        if area:
            self.shown[area] = list(self.lists[area])

    def _rows(self):
        area = site._list_area(self.url)
        self.looked.append(area)
        rows = [] if area is None else [
            {"kind": e["kind"], "subject": e["subject"], "date": e["date"],
             "unread": e["unread"],
             "hrefs": ["%s?%d-1.-rows-%d-download" % (LISTS[area], self.version, place)]}
            for place, e in enumerate(self.shown[area])]
        return {"table_present": bool(rows), "settled": True, "truncated": False,
                "empty": area is not None and not rows, "pagination": 0, "rows": rows}

    def _fetch(self, url):
        area = site._list_area(url)
        m = re.fullmatch(r"(\d+)-1\.-rows-(\d+)-download", urlsplit(url).query)
        version, place = int(m.group(1)), int(m.group(2))
        if version != self.version or site._list_area(self.url) != area \
                or place >= len(self.lists[area]):
            return dict(A_PAGE)
        name = self.lists[area][place]["doc"]
        self.fetched.append(name)
        if self.after_first_fetch:
            arrives, self.after_first_fetch = self.after_first_fetch, None
            arrives()
        return {"state": "file", "b64": base64.b64encode(pdf_of(name)).decode()}


def test_a_document_arriving_mid_run_moves_no_link_onto_its_neighbor(home):
    """Each document's link is read from its list opened afresh, never from
    the page an earlier document left on screen. Read from that page, every
    link after a new arrival would name its neighbor, and February's record
    would hold March's PDF."""
    bank = home.bank = BankOfPlaces()
    bank.lists["postbox"] = [statement("P3", 3), statement("P2", 2), statement("P1", 1)]
    bank.after_first_fetch = lambda: bank.lists["postbox"].insert(0, tax("NEW", 2026))
    code, _said = home.run_all()
    assert code == 0 and home.stopped is None
    held = home.held()
    assert len(held) == 3
    for key, whose_bytes in held.items():
        month = re.search(r"2026-(\d\d)-28", key).group(1)
        assert whose_bytes == "P%d" % int(month), key


# -- rows passed over are said, and left alone ---------------------------------

def test_a_document_marked_unread_is_said_and_left_as_it_is_when_include_unread_is_off(home):
    home.configure(include_unread=False)
    home.bank.lists["postbox"] = [statement("P1", 1), statement("U1", 2, unread=True)]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1"]
    assert "U1" not in home.bank.fetched
    assert ("!! 1 document(s) in the ING list are marked unread in the Postbox and "
            "include_unread is false") in said
    assert home.listed_whole()


def test_a_document_marked_unread_is_taken_too_by_default(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("U1", 2, unread=True)]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "U1"]
    assert "are marked unread" not in said


def test_a_link_that_would_change_something_is_never_fetched(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("M1", 2, moves=True)]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1"]
    assert "M1" not in home.bank.fetched
    assert "!! 1 document(s) in the ING list link to an address this app does not follow" in said


def test_a_document_with_no_date_this_app_reads_is_said_and_the_rest_saved(home):
    home.bank.lists["postbox"] = [statement("P1", 1), dict(statement("H1", 2), date="Heute")]
    code, said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1"]
    assert "!! 1 document(s) in the ING list carry no date this app can read," in said
    assert home.listed_whole()


def test_a_list_where_no_document_has_a_date_this_app_reads_is_not_read(home):
    home.bank.lists["postbox"] = [dict(statement("H1", 2), date="Heute")]
    said = discover_stops(home)
    assert "no document in the list carries a date this app can read" in said


# -- the list is whole or it is not called whole --------------------------------

@pytest.mark.parametrize("area", ["postbox", "archive"])
@pytest.mark.parametrize("switch,words", [
    ("pager", "has a further page or a show-more button, which this app does not press"),
    ("loading", "was still loading its rows"),
    ("cut", "shows more rows than this app reads at once"),
    ("menus", "shows no download link in its rows, and the link may sit in a menu"),
    ("blank", "showed no rows this app reads"),
])
def test_a_list_not_read_whole_records_nothing_of_either_list(home, switch, words, area):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    getattr(home.bank, switch).add(area)
    said = discover_stops(home)
    where = "the Postbox archive" if area == "archive" else "the Postbox"
    assert "!! The ING list could not be read whole, since %s %s" % (where, words) in said


def test_a_run_whose_list_is_not_read_whole_fetches_nothing(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.pager.add("archive")
    code, _said = home.run_all()
    assert home.stopped is not None and code == 1
    assert home.bank.fetched == [] and home.on_disk() == []


def test_a_list_that_signs_out_partway_records_nothing(home):
    home.configure(read_archive=True)
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.lists["archive"] = [statement("A1", 1, 2019)]
    home.bank.signs_out_at = ARCHIVE
    code, said = home.run("--discover")
    assert isinstance(home.stopped, SystemExit) and code == 0
    assert "!! ING answered the list as signed out, so this run stops here." in said
    assert home.store("discovery.json") == {}
    assert not home.listed_whole()


@pytest.mark.parametrize("how,words", [
    ("password", "!! ING appears to have signed you out."),
    ("challenge", "Stopped. Please resolve it yourself in the browser window."),
])
def test_a_run_signed_out_or_asked_to_confirm_stops_before_reading_the_list(home, how, words):
    home.bank.lists["postbox"] = [statement("P1", 1)]
    if how == "password":
        home.bank.password = True
    else:
        home.bank.body = "Bitte bestätige deine Anmeldung in der ING-App."
    code, said = home.run_all()
    assert isinstance(home.stopped, SystemExit) and code == 0
    assert words in said
    assert home.bank.looked == [] and home.bank.fetched == []
    assert not home.listed_whole()


def test_resume_whose_list_stops_takes_nothing_and_says_to_list_again(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    assert home.run("--discover")[0] == 0
    home.bank.pager.add("postbox")
    _code, said = home.run("--resume")
    assert isinstance(home.stopped, ListNotRead)
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()
    assert "The ING list could not be read again whole" in said


# -- one document --------------------------------------------------------------

def test_a_link_answered_with_a_page_is_read_again_from_the_list_opened_afresh(home):
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.answer_with["P1"] = "expired"
    code, _said = home.run_all()
    assert code == 0
    assert home.bank.fetched == ["P1", "P1"]
    assert home.bank.stale == []
    assert home.on_disk() == ["P1"]


def test_a_document_answered_with_a_page_twice_fails_and_the_next_run_takes_it(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    home.bank.answer_with["P2"] = "page"
    code, _said = home.run_all()
    assert code == 1 and home.stopped is None
    assert home.bank.fetched.count("P2") == 2
    assert home.on_disk() == ["P1"]
    assert any("its link may have expired" in notes for notes in home.failed())
    del home.bank.answer_with["P2"]
    code, _said = home.run_all()
    assert code == 0
    assert home.bank.fetched == ["P2"]
    assert home.on_disk() == ["P1", "P2"]


def test_a_fetch_the_browser_did_not_finish_twice_fails_and_says_so(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    home.bank.answer_with["P2"] = "failed"
    code, _said = home.run_all()
    assert code == 1 and home.stopped is None
    assert home.bank.fetched.count("P2") == 2
    assert home.on_disk() == ["P1"]
    notes = home.failed()
    assert any("could not be fetched" in n for n in notes)
    assert not any("its link may have expired" in n for n in notes)


def test_a_fetch_the_browser_did_not_finish_once_is_tried_again_after_a_reload(home):
    home.bank.lists["postbox"] = [statement("P1", 1)]
    home.bank.answer_with["P1"] = "failed-once"
    code, _said = home.run_all()
    assert code == 0
    assert home.bank.fetched == ["P1", "P1"]
    assert home.on_disk() == ["P1"]


def test_a_document_over_the_size_limit_saves_nothing(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    home.bank.answer_with["P2"] = "large"
    code, said = home.run_all()
    assert code == 1 and home.stopped is None
    assert home.on_disk() == ["P1"]
    assert ("Could not capture this document. Nothing was saved, and the next run "
            "tries it again.") in said


def test_a_document_answered_with_an_error_fails_and_the_run_carries_on(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    home.bank.answer_with["P2"] = 500
    code, _said = home.run_all()
    assert code == 1 and home.stopped is None
    assert home.bank.fetched == ["P2", "P1"]
    assert home.on_disk() == ["P1"]
    assert any("ING answered with status 500" in notes for notes in home.failed())


@pytest.mark.parametrize("answer", ["sign-in", 401, 403])
def test_a_document_answered_as_signed_out_stops_the_run_and_keeps_what_was_saved(home, answer):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2), statement("P3", 3)]
    home.bank.answer_with["P2"] = answer
    code, said = home.run_all()
    assert isinstance(home.stopped, SystemExit) and code == 0
    assert home.bank.fetched == ["P3", "P2"]
    assert home.on_disk() == ["P3"]
    assert "!! ING answered as signed out instead of with the document." in said
    assert "Stopped. Everything downloaded so far is saved." in said


def test_a_document_gone_from_the_list_fails_and_nothing_is_fetched_for_it(home):
    home.bank.lists["postbox"] = [statement("P1", 1), statement("P2", 2)]
    assert home.run("--discover")[0] == 0
    home.bank.lists["postbox"].pop()
    code, _said = home.run("--resume")
    assert code == 1 and home.stopped is None
    assert home.bank.fetched == ["P1"]
    assert home.on_disk() == ["P1"]
    assert any("the Postbox no longer lists this document" in notes for notes in home.failed())


# -- documents alike -------------------------------------------------------------

def test_two_documents_alike_are_each_saved_with_their_own_bytes_once(home):
    home.bank.lists["postbox"] = [statement("T1", 1), statement("T2", 1)]
    assert home.run_all()[0] == 0
    assert home.on_disk() == ["T1", "T2"]
    assert sorted(home.held().values()) == ["T1", "T2"]
    home.bank.lists["postbox"].reverse()
    assert home.run_all()[0] == 0
    assert home.bank.fetched == []
    assert home.on_disk() == ["T1", "T2"]


def test_a_document_alike_to_one_saved_is_left_rather_than_guessed_at(home):
    """ING's links last one listing, so a later run cannot tell which of two
    documents alike was saved. It saves neither again rather than guess."""
    home.bank.lists["postbox"] = [statement("T1", 1), statement("T2", 1)]
    home.bank.answer_with["T2"] = 500
    assert home.run_all()[0] == 1
    assert home.on_disk() == ["T1"]
    del home.bank.answer_with["T2"]
    code, _said = home.run_all()
    assert code == 1 and home.stopped is None
    assert home.bank.fetched == []
    assert home.on_disk() == ["T1"]


def test_two_documents_alike_but_for_their_kind_are_each_saved(home):
    subject = "Kontoauszug und Steuerbescheinigung 2025"
    home.bank.lists["postbox"] = [listed("K1", "Kontoauszug", subject, "02.01.2026"),
                                  listed("K2", "Steuerbescheinigung", subject, "02.01.2026")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["K1", "K2"]
    assert sorted(home.held().values()) == ["K1", "K2"]


# -- login -----------------------------------------------------------------------

@pytest.mark.parametrize("rows", [[statement("P1", 1)], []], ids=["rows", "empty"])
def test_login_says_success_when_the_postbox_answers_with_its_list(home, rows):
    home.bank.lists["postbox"] = rows
    code, said = home.run("--login")
    assert code == 0
    assert "Success: connected, and ING shows your Postbox list." in said
    assert home.bank.fetched == []


@pytest.mark.parametrize("how,words", [
    ("password", "Connected, but ING shows a signed-out page."),
    ("blank", "Connected, but the Postbox list did not load"),
    ("challenge", "!! Security challenge detected"),
])
def test_login_never_says_success_when_the_list_does_not_answer(home, how, words):
    home.bank.lists["postbox"] = [statement("P1", 1)]
    if how == "password":
        home.bank.password = True
    elif how == "blank":
        home.bank.blank.add("postbox")
    else:
        home.bank.body = "Bitte bestätige deine Anmeldung in der ING-App."
    code, said = home.run("--login")
    assert code == 0
    assert words in said
    assert "Success" not in said
    assert home.bank.fetched == []
