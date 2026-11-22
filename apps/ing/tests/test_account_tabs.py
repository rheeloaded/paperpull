"""ING's account tabs (#169), each account's Postbox and archive read alone.

MelleD's Postbox shows one tab per account above the list, their own and
each child's, in the archive too, in the same order every sign-in. The plain
list address opens the first account. A tab is a link to the list's own page
with an opaque value that changes on every page, and following it is a GET.
How the selected tab is marked was not recorded, so the stand-in marks it
the ways the app reads (a class word, aria, or classes the others lack).

The runs go through the app's main against the stand-in tab of
test_a_run_against_the_postfach.py, given tabs. Every name, subject and date
here is invented.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import ing_docs as docs
import ing_site as site
from paperpull_core import renaming
from paperpull_core import storage as core_storage

from test_a_run_against_the_postfach import (ARCHIVE, LISTS, POSTBOX, Bank, Home, statement,
                                              tax, whose)

OWN, MIA, LEO = "Alex Muster", "Mia Muster", "Leo Muster"
TAB_HREF = re.compile(r"x=tab(\d+)-(\d+)$")


class TabbedBank(Bank):
    """The banking tab with account tabs. `accounts` are the tab labels in
    the order shown, the first the one the plain address opens, and
    `by_account` what each account's two lists show. Each page's tab links
    carry its version, so only the page on screen answers one.

    `lands` sends a followed tab to another account, `mark` says how the
    selected tab is marked ("class", "aria-selected", "aria-current",
    "superset", "none", "two"), `order_after_follow` shows the tabs in
    another order on a followed tab's page, and `bars` and `loose` stand
    for a page with two tab bars or a box of links not read as one."""

    def __init__(self, accounts=(OWN, MIA, LEO)):
        super().__init__()
        self.accounts = list(accounts)
        self.by_account = {a: {"postbox": [], "archive": []} for a in self.accounts}
        self.current = self.accounts[0]
        self.lists = self.by_account[self.current]
        self.lands = {}
        self.mark = "class"
        self.order_after_follow = None
        self.labels_shown = None
        self.bars = 1
        self.loose = 0
        self.hrefs = {}            # label -> an href to show in place of the tab's own
        self.tab_gotos = []

    def goto(self, url, **kw):
        m = TAB_HREF.search(urlsplit(url).query) if urlsplit(url).query else None
        area = site._list_area(url)
        if m and area:
            self.tab_gotos.append(url)
            version, i = int(m.group(1)), int(m.group(2))
            self.gotos.append(url)
            self.version += 1
            self.url = LISTS[area]
            if version != self.version - 1:
                # A tab link read from an earlier page opens nothing new.
                self.acted.append("followed a tab link of an earlier page")
                return
            label = self.accounts[i]
            self.current = self.lands.get(label, label)
            self.url = LISTS[area] + "?x=shown%d" % self.version
            self.lists = self.by_account[self.current]
            return
        super().goto(url, **kw)
        if url in LISTS.values():
            self.current = self.accounts[0]
            self.lists = self.by_account[self.current]

    def evaluate(self, js, arg=None):
        if isinstance(arg, dict) and "mark" in arg and js == site._TABS_JS:
            return self._tabs()
        return super().evaluate(js, arg)

    def _tabs(self):
        area = site._list_area(self.url)
        if area is None or self.password or len(self.accounts) < 2:
            return {"bars": 0, "loose": self.loose, "count": 0, "tabs": []}
        labels = list(self.accounts)
        followed = "shown" in urlsplit(self.url).query
        if followed and self.order_after_follow:
            labels = list(self.order_after_follow)
        if self.labels_shown:
            labels = list(self.labels_shown)
        tabs = []
        for label in labels:
            i = self.accounts.index(label) if label in self.accounts else 0
            selected = label == self.current
            href = self.hrefs.get(label, "%s?x=tab%d-%d" % (LISTS[area], self.version, i))
            marked = (self.mark in ("class", "aria-selected", "aria-current") and selected) \
                or self.mark == "two" and labels.index(label) < 2
            classes = ["pill"] + (["pill-on"] if self.mark == "superset" and selected else [])
            tabs.append({"label": label, "href": href, "marked": marked, "classes": classes})
        return {"bars": self.bars, "loose": self.loose, "count": len(tabs), "tabs": tabs}


class TabHome(Home):
    def __init__(self, tmp_path, monkeypatch, capsys):
        super().__init__(tmp_path, monkeypatch, capsys)
        self.bank = TabbedBank()
        monkeypatch.setattr(docs.App, "page", lambda app: self.bank)
        monkeypatch.setattr(docs.App, "_on_its_site", lambda app: self.bank)

    def run(self, *flags):
        self.capsys.readouterr()
        for kept in (self.bank.gotos, self.bank.looked, self.bank.fetched, self.bank.stale,
                     self.bank.tab_gotos):
            kept.clear()
        site._listing.clear()
        self.stopped = None
        try:
            code = docs.main(["--config", str(self.cfg), *flags])
        except SystemExit as stop:
            self.stopped, code = stop, stop.code
        said = " ".join(self.capsys.readouterr().out.split())
        assert self.bank.acted == []
        # Only the two lists, by their own addresses, and tab links of the
        # page on screen are ever opened.
        assert set(self.bank.gotos) - set(self.bank.tab_gotos) <= {POSTBOX, ARCHIVE}
        return code, said

    def files(self) -> dict:
        """Whose bytes each PDF holds, by its path under the output folder."""
        return {p.relative_to(self.out).as_posix(): whose(p.read_bytes())
                for p in sorted(self.out.rglob("*.pdf"))}

    def everything_said(self) -> str:
        """Every file a run writes that is not a record or a document."""
        texts = []
        for p in self.out.rglob("*"):
            if p.is_file() and p.suffix in (".log", ".txt", ".json") and p.name not in (
                    "progress.json", "discovery.json") and "Backups" not in p.parts:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(texts)


@pytest.fixture
def home(tmp_path, monkeypatch, capsys):
    site.remember_home("")
    yield TabHome(tmp_path, monkeypatch, capsys)
    site.remember_home("")


def three_accounts(home):
    b = home.bank
    b.by_account[OWN]["postbox"] = [statement("O1", 1), tax("O2")]
    b.by_account[OWN]["archive"] = [statement("O3", 1, 2019)]
    b.by_account[MIA]["postbox"] = [statement("M1", 1)]
    b.by_account[MIA]["archive"] = [statement("M2", 2, 2019)]
    b.by_account[LEO]["postbox"] = [statement("L1", 1), statement("L2", 2)]


def names_said(text: str) -> list:
    low = text.lower()
    return [n for n in (OWN, MIA, LEO, "Muster", "Mia", "Leo") if n.lower() in low]


# -- each account read alone and filed apart --------------------------------------

def test_every_account_tab_is_read_and_each_is_filed_in_its_own_folder(home):
    three_accounts(home)
    code, said = home.run_all()
    assert code == 0 and home.stopped is None, said
    files = home.files()
    # The home account files as it always did, in the folder of its kind.
    assert files["Kontoauszuege/" + next(p.split("/")[-1] for p, w in files.items()
                                         if w == "O1")] == "O1"
    assert {w for p, w in files.items() if p.startswith("Kontoauszuege/Mia Muster/")} == \
        {"M1", "M2"}
    assert {w for p, w in files.items() if p.startswith("Kontoauszuege/Leo Muster/")} == \
        {"L1", "L2"}
    assert sorted(files.values()) == ["L1", "L2", "M1", "M2", "O1", "O2", "O3"]
    home_keys = [k for k, w in home.held().items() if w in ("O1", "O2", "O3")]
    assert home_keys and all(not k.startswith("@") for k in home_keys)
    assert {w for k, w in home.held().items() if k.startswith("@Mia Muster:")} == {"M1", "M2"}
    assert "ING shows 3 accounts as tabs" in said
    assert "Account 1 (the one the Postbox opens on): 3 document(s) listed" in said
    assert "Account 2 (tab 2): 2 document(s) listed" in said
    assert "Account 3 (tab 3): 2 document(s) listed" in said


def test_two_accounts_with_one_document_alike_each_keep_their_own(home):
    b = home.bank
    b.by_account[OWN]["postbox"] = [statement("O1", 1)]
    b.by_account[MIA]["postbox"] = [statement("M1", 1)]
    b.by_account[LEO]["postbox"] = [statement("L1", 1)]
    assert home.run_all()[0] == 0
    assert sorted(home.held().values()) == ["L1", "M1", "O1"]
    names = {Path(p).name for p in home.files()}
    assert len(names) == 1     # one name, three folders, no (2)
    assert home.run_all()[0] == 0 and home.bank.fetched == []


def test_documents_saved_before_tabs_are_neither_fetched_again_nor_renamed(home):
    """An install that read only the first account (every run before #169),
    then the same Postbox with the children's tabs beside it."""
    accounts = home.bank.accounts
    home.bank.accounts = [OWN]
    home.bank.by_account[OWN]["postbox"] = [statement("O1", 1), statement("O1b", 1)]
    home.bank.by_account[OWN]["archive"] = [tax("O2", 2019)]
    assert home.run_all()[0] == 0
    before = home.files()
    before_keys = sorted(home.held())
    home.bank.accounts = accounts
    home.bank.by_account[MIA]["postbox"] = [statement("M1", 1)]
    code, said = home.run_all()
    assert code == 0, said
    assert home.bank.fetched == ["M1"]
    after = home.files()
    assert {p: w for p, w in after.items() if w != "M1"} == before
    assert sorted(k for k in home.held() if not k.startswith("@")) == before_keys
    # Rename's plan moves nothing, the account's own folder included.
    app = docs.App(docs.build_parser().parse_args(["--config", str(home.cfg)]))
    plan = renaming.run_for(app, apply_changes=False, say=lambda *_: None)
    assert not list(getattr(plan, "planned", []) or []) and not getattr(plan, "renamed", 0)
    assert home.files() == after


def test_rename_keeps_a_childs_file_in_its_accounts_folder(home, monkeypatch):
    three_accounts(home)
    assert home.run_all()[0] == 0
    # A naming pattern with a folder of its own, after the account's.
    monkeypatch.setattr(core_storage, "_FILENAME_PATTERN", "{year}/{date} {summary}")
    app = docs.App(docs.build_parser().parse_args(["--config", str(home.cfg), "--rename",
                                                   "--apply"]))
    monkeypatch.setattr(core_storage, "_FILENAME_PATTERN", "{year}/{date} {summary}")
    renaming.run_for(app, apply_changes=True, say=lambda *_: None)
    files = home.files()
    mia = [p for p, w in files.items() if w in ("M1", "M2")]
    assert len(mia) == 2 and all(p.startswith("Kontoauszuege/Mia Muster/20") for p in mia), mia
    own = [p for p, w in files.items() if w == "O1"]
    assert own and own[0].startswith("Kontoauszuege/2026/")


def test_the_archive_of_each_account_is_read_behind_its_own_tab(home):
    b = home.bank
    b.by_account[MIA]["archive"] = [tax("M9", 2018)]
    assert home.run_all()[0] == 0
    assert home.files() == {next(iter(home.files())): "M9"}
    assert next(iter(home.files())).startswith("Steuerbescheinigungen/Mia Muster/")
    home.configure(read_archive=False)
    assert home.run_all()[0] == 0
    assert all(not u.startswith(ARCHIVE) for u in home.bank.gotos)


def test_an_empty_account_is_read_as_empty_right_after_its_tab_is_followed(home):
    home.bank.by_account[OWN]["postbox"] = [statement("O1", 1)]
    code, said = home.run_all()
    assert code == 0, said
    assert "Account 2 (tab 2): 0 document(s) listed" in said


# -- the account shown must be the one followed -----------------------------------

@pytest.mark.parametrize("mark", ["class", "aria-selected", "aria-current", "superset"])
def test_each_way_the_selected_tab_is_marked_is_read(home, mark):
    three_accounts(home)
    home.bank.mark = mark
    assert home.run("--discover")[0] == 0
    assert len(home.store("discovery.json")) == 7


@pytest.mark.parametrize("mark", ["none", "two"])
def test_a_selected_tab_that_cannot_be_told_stops_the_listing(home, mark):
    three_accounts(home)
    home.bank.mark = mark
    code, said = home.run("--discover")
    assert code == 1 and home.store("discovery.json") == {}
    assert "which account tab is selected cannot be told" in said
    assert home.bank.tab_gotos == []


def test_a_tab_that_opens_another_account_stops_the_listing(home):
    three_accounts(home)
    home.bank.lands = {MIA: LEO}
    code, said = home.run("--discover")
    assert code == 1 and home.store("discovery.json") == {}
    assert "the account shown is not the one whose tab was followed" in said
    assert names_said(said) == []


def test_tabs_shown_in_another_order_after_a_tab_is_followed_stop_the_listing(home):
    three_accounts(home)
    home.bank.order_after_follow = [MIA, OWN, LEO]
    code, said = home.run("--discover")
    assert code == 1 and home.store("discovery.json") == {}


def test_a_download_whose_tab_now_opens_another_account_saves_nothing(home):
    three_accounts(home)
    assert home.run("--discover")[0] == 0
    home.bank.lands = {MIA: LEO}
    code, said = home.run("--resume")
    assert not any(w in ("M1", "M2", "L1", "L2") and p.startswith("Kontoauszuege/Mia")
                   for p, w in home.files().items())
    assert "M1" not in home.bank.fetched and "M2" not in home.bank.fetched
    assert all(not ("Leo" in p and w.startswith("M")) for p, w in home.files().items())
    assert names_said(said) == []


def test_a_tab_link_is_read_from_the_page_each_time(home):
    three_accounts(home)
    assert home.run_all()[0] == 0
    for name in ("discovery.json", "progress.json"):
        assert "x=tab" not in (home.out / name).read_text(encoding="utf-8")
    assert "x=tab" not in home.everything_said()


# -- the home account is remembered -------------------------------------------------

def test_a_postbox_that_opens_on_another_account_than_before_stops(home):
    three_accounts(home)
    assert home.run("--discover")[0] == 0
    remembered = json.loads((home.out / docs.ACCOUNTS_FILE).read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{32}", remembered["home"])
    assert names_said(json.dumps(remembered)) == []
    # ING now opens Mia's account on the plain address.
    b = home.bank
    b.accounts = [MIA, OWN, LEO]
    b.by_account = {MIA: b.by_account[MIA], OWN: b.by_account[OWN], LEO: b.by_account[LEO]}
    known = home.store("discovery.json")
    code, said = home.run_all()
    assert code == 1 and home.bank.fetched == []
    assert home.store("discovery.json") == known
    assert "opens on another account than it did before" in said
    assert names_said(said) == []


def test_the_home_account_seen_first_is_written_once_and_kept(home):
    three_accounts(home)
    assert home.run("--discover")[0] == 0
    first = (home.out / docs.ACCOUNTS_FILE).read_text(encoding="utf-8")
    assert home.run("--discover")[0] == 0
    assert (home.out / docs.ACCOUNTS_FILE).read_text(encoding="utf-8") == first


def test_a_postbox_of_one_account_writes_no_home_and_reads_as_always(home):
    home.bank.accounts = [OWN]
    home.bank.by_account[OWN]["postbox"] = [statement("O1", 1)]
    code, said = home.run_all()
    assert code == 0 and not (home.out / docs.ACCOUNTS_FILE).exists()
    assert "accounts as tabs" not in said
    assert home.bank.tab_gotos == []


# -- what is not an account tab -----------------------------------------------------

@pytest.mark.parametrize("labels,why", [
    ([OWN, MIA, MIA], "two account tabs carry the same name"),
    ([OWN, "Mia:Muster", "Mia/Muster"], "two account tabs carry the same name"),
    ([OWN, "mia muster", "Mia Muster"], "two account tabs carry the same name"),
    ([OWN, "Weiteres Konto hinzufügen"], "a link that is not an account's"),
    ([OWN, "Konto eröffnen"], "a link that is not an account's"),
    ([OWN, "..."], "leaves no folder name"),
    ([OWN, ""], "carries no name"),
    ([OWN, "x" * 121], "carries no name"),
])
def test_tabs_this_app_does_not_read_as_accounts_stop_the_listing(home, labels, why):
    home.bank.by_account[OWN]["postbox"] = [statement("O1", 1)]
    home.bank.labels_shown = labels
    code, said = home.run("--discover")
    assert code == 1 and home.store("discovery.json") == {}
    assert why in said
    assert home.bank.tab_gotos == []


def test_more_tabs_than_this_app_reads_stop_the_listing(home):
    home.bank.labels_shown = [OWN] + ["Kind %d" % n for n in range(20)]
    code, said = home.run("--discover")
    assert code == 1 and "more account tabs than this app reads" in said


def test_two_tab_bars_stop_the_listing(home):
    home.bank.bars = 2
    code, said = home.run("--discover")
    assert code == 1 and "more than one row of account tabs" in said


@pytest.mark.parametrize("href", [
    "https://evil.example/app/postbox/postbox?x=tab1-1",
    "http://banking.ing.de/app/postbox/postbox?x=tab1-1",
    "https://banking.ing.de/app/obligo?x=tab1-1",
    "https://banking.ing.de/app/postbox/postbox_archiv?x=tab1-1",
    "https://banking.ing.de/app/postbox/postbox",
    "https://banking.ing.de/app/postbox/postbox?x=tab1-1-archivieren",
    "https://banking.ing.de/app/postbox/postbox?x=delete-1",
    "https://user@banking.ing.de/app/postbox/postbox?x=tab1-1",
])
def test_a_tab_link_this_app_does_not_follow_stops_that_list_unopened(home, href):
    home.bank.by_account[MIA]["postbox"] = [statement("M1", 1)]
    home.bank.hrefs = {MIA: href}
    code, said = home.run("--discover")
    assert code == 1 and home.store("discovery.json") == {}
    assert "an account tab links to an address this app does not follow" in said
    assert home.bank.tab_gotos == []
    assert href == POSTBOX or href not in home.bank.gotos


# -- privacy --------------------------------------------------------------------------

def test_no_tab_name_reaches_the_screen_the_log_or_a_failure_file(home):
    three_accounts(home)
    code, said = home.run_all()
    assert code == 0
    home.bank.lands = {LEO: MIA}
    site._listing.clear()
    code2, said2 = home.run("--discover")
    assert code2 == 1
    assert names_said(said) == [] and names_said(said2) == []
    # The records, their backups and new-this-run.txt name the folders the
    # files are in, as they always name each file. Nothing else does: the
    # logs, the failure file, the run summary and the remembered home.
    records = ("discovery.json", "progress.json", "new-this-run.txt")
    leaks = [p.name for p in home.out.rglob("*")
             if p.is_file() and p.suffix in (".log", ".txt", ".json")
             and p.name not in records and "Backups" not in p.parts
             and names_said(p.read_text(encoding="utf-8", errors="replace"))]
    assert leaks == []
    assert list((home.out / "Diagnostics").glob("failure-*.json"))


# -- the account's folder --------------------------------------------------------------

def test_a_childs_document_whose_folder_leaves_no_room_is_not_saved_with_the_home_files(
        home, monkeypatch):
    home.bank.by_account[OWN]["postbox"] = [statement("O1", 1)]
    home.bank.by_account[MIA]["postbox"] = [statement("M1", 2)]
    # A path limit the account's folder does not fit under, though the name
    # alone does, so the naming core files the name in the folder of its kind.
    real = core_storage.filing_folder

    def no_room(directory, filename, max_path_length=240):
        return Path(directory)
    monkeypatch.setattr(core_storage, "filing_folder", no_room)
    code, said = home.run_all()
    monkeypatch.setattr(core_storage, "filing_folder", real)
    assert "M1" not in home.files().values()
    assert any("account's folder could not be used" in n for n in home.failed())
    assert "O1" in home.files().values()
