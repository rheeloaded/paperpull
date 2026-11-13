"""Sparkasse Pforzheim Calw's own main against a made-up Postfach, in a browser.

Each run goes through the app's main as the panel starts it, with its real
stores, index and files and a made-up config and output folder. The page is
Playwright's own Chromium on the bank's address, every request answered by
the route below and every name resolved to nowhere, so the app's own tab
picking, listing, numbering, page turns, presses and downloads all run as
they do at the bank. Every PDF carries the name of the document it is, so a
file is known by its bytes and never by its name.

The Postfach here has the parts the app was mapped against
(sparkassepc_site.py). Its folders keep the page they were turned to, as the
bank's do. Its pager is a set of submit buttons that the page's own script
sends to the folder's .ajstep.html address, or, with `pager = "form"`, that
the browser sends as the form itself. A direct download link's own script
prepares the download and then sends the tab to the PDF service. Every
subject, identity and date is invented.
"""
import html
import io
import json
import math
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import sparkassepc_docs as docs
import sparkassepc_site as site
from paperpull_core import storage as core_storage
from paperpull_core.run_reporting import ListNotRead

pw_api = pytest.importorskip("playwright.sync_api")

APP = Path(__file__).resolve().parents[1]
HOST = "www.sparkasse-pforzheim-calw.de"
BASE = "https://" + HOST
ELSEWHERE = "https://www.elsewhere.example/inbox"
SERVICE = "/services/download.service/sk-pforzheim-calw/"

# Playwright's own Chromium, never a browser installed on this computer,
# with every name resolved to nowhere so a request the route does not
# answer cannot leave the machine.
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND"]

SIGN_IN = """<!doctype html><html><head><meta charset="utf-8"><title>Anmelden</title></head>
<body><form class="login"><input name="user"><input type="password" name="pin">
<button>Anmelden</button></form></body></html>"""
SIGN_IN_PART = '<form class="login"><input name="user"><input type="password" name="pin"></form>'

# The page's own script. The pager's buttons go to the folder's .ajstep.html
# address when the page sends them itself, and a direct download link
# prepares its download and then sends the tab to the PDF service.
PAGE_JS = """
window.bankDownload = async (event, link) => {
  event.preventDefault();
  const answer = await fetch(link.href, {method: "POST", headers: {"X-Requested-With": "XMLHttpRequest"}});
  if (!answer.ok) return;
  const to = await answer.text();
  if (window.bankMarksRead) link.closest("tr").classList.remove("tablerowmarked");
  location.href = to;
};
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!window.bankPagerScript || !form.classList.contains("postfach")) return;
  event.preventDefault();
  const body = new URLSearchParams(new FormData(form, event.submitter));
  const answer = await fetch(location.pathname.replace(/\\.html$/, ".ajstep.html"), {method: "POST",
    body, headers: {"X-Requested-With": "XMLHttpRequest"}});
  const holder = document.createElement("div");
  holder.innerHTML = await answer.text();
  form.replaceWith(...holder.childNodes);
});
"""


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


def message(name, title="Kontoauszug 1/2031", day="02.02.2031", pdf=True, unread=True):
    """A Postfach row. `name` is which document it is, and its identity is
    made from it. A row with pdf False is a message with no direct download."""
    return {"name": name, "title": title, "day": day, "pdf": pdf, "unread": unread,
            "identity": "ID-%s-7F3A" % name}


def many(prefix, count, day="02.02.2031", title="Mitteilung %d"):
    return [message("%s%03d" % (prefix, n), title % n, day) for n in range(count)]


class Bank:
    """What the bank answers. `folders` holds each folder's rows, newest
    first, and `at` the page each folder was last turned to. `pager` is
    "script", "form", or None for a Postfach whose pager went missing.
    `active` False draws the pager with no active page number this can read,
    `pager_leaves` drops the pager once a folder is turned past page 1, and
    `link_class`, `row_class` and `next_class` name the direct download
    links, the rows and the pager's next arrow. A name in `refuse` answers
    that status for its PDF, one in `not_pdf` answers a sign-in page with
    200, and once `signs_out`'s PDF is asked for the bank answers as signed
    out from then on. `marks_read` clears a row's unread mark, on the page
    and at the bank, as its download is prepared."""

    def __init__(self):
        self.folders = {folder: [] for folder in site.FOLDERS}
        self.at = {folder: 1 for folder in site.FOLDERS}
        self.size = 10
        self.pager = "script"
        self.active = True
        self.pager_leaves = False
        self.link_class = "postbox-message-direct-download"
        self.row_class = "postbox-message-row"
        self.next_class = "next"
        self.refuse = {}
        self.not_pdf = set()
        self.signs_out = None
        self.signed_out = False
        self.marks_read = False
        self.tickets = {}
        self.presses = []
        self.prepared = []
        self.fetched = []
        self.elsewhere = 0

    # -- the pages ---------------------------------------------------------

    def pages(self, folder):
        return max(1, math.ceil(len(self.folders[folder]) / self.size))

    def _row(self, folder, m):
        subject = html.escape(m["title"])
        if m["pdf"]:
            cell = ('<a class="%s" title="%s" href="%s?msg=%s&amp;dl=1" '
                    'onclick="bankDownload(event, this)">%s</a>'
                    % (self.link_class, subject, site.FOLDERS[folder], m["identity"], subject))
        else:
            cell = "<span>%s</span>" % subject
        return ('<tr class="%s%s"><td><input type="checkbox" name="sel" value="%s">'
                '</td><td></td><td>%s</td><td>%s</td></tr>'
                % (self.row_class, " tablerowmarked" if m["unread"] else "", m["identity"], cell,
                   m["day"]))

    def _pager(self, folder, number):
        pages = self.pages(folder)
        if not self.pager or pages == 1 or (self.pager_leaves and number > 1):
            return ""
        buttons = []
        for p in range(max(1, number - 2), min(pages, number + 2) + 1):
            if p == number:
                inner = ('<input type="submit" name="pg" value="%d" disabled>' % p
                         if self.active else "<span>%d</span>" % p)
                buttons.append('<li class="active">%s</li>' % inner)
            else:
                buttons.append('<li><input type="submit" name="pg" value="%d"></li>' % p)
        following = ('<span class="%s"><input type="submit" name="pg" value="%d"></span>'
                     % (self.next_class, number + 1) if number < pages else "")
        return '<div class="bpager"><ul class="pagerbuttons">%s</ul>%s</div>' % (
            "".join(buttons), following)

    def form(self, folder):
        number = min(self.at[folder], self.pages(folder))
        shown = self.folders[folder][(number - 1) * self.size:number * self.size]
        return ('<form class="postfach" method="post" action="%s">'
                '<div class="select-time"><select name="zeit"><option selected>Gesamtzeitraum</option>'
                '<option>Letzte 30 Tage</option></select></div>'
                '<input class="mkp-input-with-icon" name="suche" value="">'
                '<table><tbody>%s</tbody></table>%s</form>'
                % (site.FOLDERS[folder], "".join(self._row(folder, m) for m in shown),
                   self._pager(folder, number)))

    def page(self, folder):
        nav = "".join(
            '<a class="nbf-guided-tour-navigation_%s" href="%s?n=true">%s %d</a> ' % (
                path.rsplit("/", 1)[-1].removesuffix(".html"), path, name, len(self.folders[name]))
            for name, path in site.FOLDERS.items())
        return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>Postfach</title></head>"
                "<body><h1>Elektronisches Postfach</h1><nav>%s</nav>%s<script>"
                "window.bankPagerScript = %s; window.bankMarksRead = %s;%s</script></body></html>"
                % (nav, self.form(folder), "true" if self.pager == "script" else "false",
                   "true" if self.marks_read else "false", PAGE_JS))

    # -- what the bank answers ---------------------------------------------

    def answer(self, route):
        request = route.request
        parts = urlsplit(request.url)
        if parts.hostname == "www.elsewhere.example":
            self.elsewhere += 1
            return route.fulfill(status=200, content_type="text/html",
                                 body="<html><body><h1>Inbox</h1></body></html>")
        if parts.hostname != HOST:
            return route.fulfill(status=404, content_type="text/plain", body="not found")
        if parts.path.startswith(SERVICE):
            return self._pdf(route, parts.path)
        step = parts.path.endswith(".ajstep.html")
        path = parts.path.replace(".ajstep.html", ".html")
        folder = next((name for name, p in site.FOLDERS.items() if p == path), None)
        if folder is None:
            return route.fulfill(status=200, content_type="text/html", body=SIGN_IN)
        if self.signed_out:
            return route.fulfill(status=200, content_type="text/html",
                                 body=SIGN_IN_PART if step else SIGN_IN)
        query = parse_qs(parts.query)
        if request.method == "POST" and "msg" in query:
            return self._prepare(route, folder, query["msg"][0])
        if request.method == "POST":
            sent = parse_qs(request.post_data or "", keep_blank_values=True)
            number = int(sent["pg"][0])
            self.presses.append((folder, number, "script" if step else "form",
                                 sorted(sent), request.headers.get("x-requested-with", "")))
            self.at[folder] = number
            return route.fulfill(status=200, content_type="text/html",
                                 body=self.form(folder) if step else self.page(folder))
        return route.fulfill(status=200, content_type="text/html", body=self.page(folder))

    def _prepare(self, route, folder, identity):
        m = next(m for m in self.folders[folder] if m["identity"] == identity)
        self.prepared.append(m["name"])
        if self.marks_read:
            m["unread"] = False
        ticket = "T%04d" % len(self.tickets)
        self.tickets[ticket] = m
        return route.fulfill(status=200, content_type="text/plain",
                             body=SERVICE + ticket + "/Dokument.pdf")

    def _pdf(self, route, path):
        m = self.tickets.get(path[len(SERVICE):].split("/", 1)[0])
        name = m["name"] if m else "?"
        self.fetched.append(name)
        if self.signed_out or m is None:
            return route.fulfill(status=200, content_type="text/html", body=SIGN_IN)
        if name in self.refuse:
            return route.fulfill(status=self.refuse[name], content_type="text/html", body="no")
        if name == self.signs_out:
            self.signed_out = True
            return route.fulfill(status=200, content_type="text/html", body=SIGN_IN)
        if name in self.not_pdf:
            return route.fulfill(status=200, content_type="text/html", body=SIGN_IN)
        return route.fulfill(status=200, content_type="application/pdf", body=pdf_of(name))


def refused(*_args, **_kwargs):
    raise AssertionError("a request from outside the page would leave this test")


@pytest.fixture(scope="module")
def chromium():
    with pw_api.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=ARGS)
        try:
            yield browser
        finally:
            browser.close()


class Home:
    def __init__(self, chromium, tmp_path, monkeypatch, capsys):
        self.bank = Bank()
        self.capsys = capsys
        self.out = tmp_path / "out"
        self.config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
        self.config.update({"owner": "Dana Example", "output_dir": str(self.out),
                            "profile_dir": str(tmp_path / "profile"),
                            "cdp_url": "http://127.0.0.1:9", "delay_min_seconds": 0.01,
                            "delay_max_seconds": 0.02, "default_start_date": ""})
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(self.config), encoding="utf-8")
        for name in ("_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
            monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
        self.context = chromium.new_context()
        self.context.route("**/*", self.bank.answer)
        # The person's own tab, signed in and left on the Postfach.
        self.page = self.context.new_page()
        self.page.goto(BASE + site.FOLDERS["Posteingang"])
        context = self.context

        def attached(app):
            # The person's browser, as the app attaches to it over CDP.
            app._context, app._cdp_mode = context, True
            return context
        monkeypatch.setattr(docs.App, "browser", attached)
        # Playwright's own client sends from outside the browser, past the
        # route and the name rules above, so here it refuses everything and
        # nothing a run asks can reach the bank.
        for name in ("fetch", "get", "post", "head", "put", "delete", "patch"):
            monkeypatch.setattr(pw_api.APIRequestContext, name, refused)
        self.sleeps = []
        monkeypatch.setattr("time.sleep", lambda seconds=0, *_a, **_kw: self.sleeps.append(seconds))
        monkeypatch.setattr(site, "_cache", None)
        monkeypatch.setattr(site, "_summary", {})
        monkeypatch.setattr(site, "SETTLE_SECONDS", 3)

    def run(self, *flags):
        """The app's main and what it said, each run as a process of its own
        with no listing kept from the run before. The tabs and the page each
        folder was turned to stay, as the person's browser and the bank keep
        them."""
        self.capsys.readouterr()
        self.bank.fetched, self.bank.presses, self.bank.prepared = [], [], []
        self.sleeps.clear()
        site._cache = None
        site._summary = {}
        code = docs.main(["--config", str(self.cfg), *flags])
        return code, " ".join(self.capsys.readouterr().out.split())

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

    def states(self) -> list:
        return sorted(rec["state"] for rec in self.store("progress.json").values()
                      if isinstance(rec, dict))

    def listed_whole(self) -> bool:
        return self.store("last-listing.json").get("complete") is True

    def item_of(self, m) -> str:
        return site._digest(m["identity"])


@pytest.fixture
def home(chromium, tmp_path, monkeypatch, capsys):
    home = Home(chromium, tmp_path, monkeypatch, capsys)
    try:
        yield home
    finally:
        home.context.close()


def discover_stops(home) -> str:
    """Discover stopped with its list not called whole and nothing recorded,
    and what it said."""
    with pytest.raises(SystemExit) as stop:
        home.run("--discover")
    said = " ".join(home.capsys.readouterr().out.split())
    assert stop.value.code == 1, said
    assert not home.listed_whole()
    assert home.store("discovery.json") == {}
    return said


# -- a run that reads everything -------------------------------------------------

def test_discover_then_a_run_saves_every_folder_each_with_its_own_bytes(home):
    home.bank.folders["Posteingang"] = [
        message("P1", "Kontoauszug 2/2031", "02.03.2031"),
        message("T1", "Ihre Nachricht an uns", "01.03.2031", pdf=False),
        message("P2", "Kontoauszug 1/2031", "02.02.2031")]
    home.bank.folders["Gesendet"] = [message("G1", "Unterlagen zum Konto", "15.01.2031")]
    home.bank.folders["Papierkorb"] = [message("K1", "Zinsbescheinigung 2030", "10.01.2031")]
    code, said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 4, said
    assert "1 Postfach item(s) offer no direct PDF download" in said
    assert home.listed_whole()
    code, said = home.run("--resume")
    assert code == 0, said
    assert home.on_disk() == ["G1", "K1", "P1", "P2"]
    assert sorted(home.held().values()) == ["G1", "K1", "P1", "P2"]
    # Each PDF was prepared by its own row's press and asked for once.
    assert sorted(home.bank.prepared) == sorted(home.bank.fetched) == ["G1", "K1", "P1", "P2"]


@pytest.mark.parametrize("pager", ["script", "form"])
def test_a_list_longer_than_one_page_is_read_to_its_end_by_the_pagers_own_buttons(home, pager):
    """The page's own pager button is pressed, so the bank gets what the page
    sends, the button's own number and the form's own fields, whether the
    page's script sends it or the browser does."""
    home.bank.pager = pager
    home.bank.folders["Posteingang"] = many("P", 25)
    code, _said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 25
    assert home.listed_whole()
    assert [(f, n) for f, n, *_ in home.bank.presses] == [("Posteingang", 2), ("Posteingang", 3)]
    for _folder, _number, how, fields, said_by in home.bank.presses:
        assert how == pager
        assert fields == ["pg", "suche", "zeit"]
        assert said_by == ("XMLHttpRequest" if pager == "script" else "")
    # Each turn waits the config's own pause first.
    assert len(home.sleeps) >= 2 and all(0.01 <= s <= 0.02 for s in home.sleeps[:2])


def test_a_folder_left_on_a_later_page_is_turned_back_to_its_first(home):
    home.bank.folders["Posteingang"] = many("P", 25)
    home.bank.at["Posteingang"] = 3
    code, _said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 25
    assert [n for _f, n, *_ in home.bank.presses] == [1, 2, 3]


def test_downloads_turn_the_folder_from_where_it_stands_never_from_its_start(home):
    """After the listing, each document's folder is turned from the page it
    shows, so a run of thirty documents on three pages turns a page only
    when the next document is on another."""
    home.bank.folders["Posteingang"] = [message("P%03d" % n, "Mitteilung %d" % n,
                                                "%02d.0%d.2031" % (28 - n % 28, 9 - n // 10))
                                        for n in range(30)]
    code, said = home.run_all()
    assert code == 0, said
    assert len(home.on_disk()) == 30
    listing_turns = 2
    assert len(home.bank.presses) <= listing_turns + 3


def test_an_empty_postfach_is_listed_whole(home):
    code, _said = home.run("--discover")
    assert code == 0
    assert home.listed_whole()


def test_a_short_postfach_with_no_pager_is_listed(home):
    home.bank.folders["Posteingang"] = many("P", 4)
    code, _said = home.run("--discover")
    assert code == 0
    assert len(home.store("discovery.json")) == 4
    assert home.listed_whole()


# -- subjects are the documents' own words ------------------------------------------

@pytest.mark.parametrize("subject", ["Zinsanpassung", "Entgeltinformation 2031",
                                     "Zinsbescheinigung 2030", "Änderung Ihrer Bedingungen",
                                     "Information zur Kontoführung"])
def test_a_document_downloads_whatever_its_subject_says(home, subject):
    """The link's title is the document's subject. A press gate that read
    it as a control's label refused these on every run."""
    home.bank.folders["Posteingang"] = [message("P1", subject)]
    code, said = home.run_all()
    assert code == 0, said
    assert home.on_disk() == ["P1"]


def test_a_row_whose_unread_mark_changes_with_its_download_is_still_saved(home):
    home.bank.marks_read = True
    home.bank.folders["Posteingang"] = [message("P2", "Kontoauszug 2/2031", "02.03.2031"),
                                        message("P1")]
    code, said = home.run_all()
    assert code == 0, said
    assert home.on_disk() == ["P1", "P2"]
    assert not any(m["unread"] for m in home.bank.folders["Posteingang"])


# -- one document that will not download ----------------------------------------

@pytest.mark.parametrize("how", ["http_500", "not_a_pdf"])
def test_one_document_without_a_pdf_fails_alone_and_the_run_goes_on(home, how):
    home.bank.folders["Posteingang"] = [message("P2", "Kontoauszug 2/2031", "02.03.2031"),
                                        message("P1")]
    if how == "http_500":
        home.bank.refuse = {"P2": 500}
    else:
        home.bank.not_pdf = {"P2"}
    code, said = home.run_all()
    assert code == 1
    assert home.on_disk() == ["P1"]
    assert home.states() == ["Completed", "Failed"]
    assert "Nothing was saved, and the next run tries it again" in said
    assert home.listed_whole()
    home.bank.refuse, home.bank.not_pdf = {}, set()
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]


def test_a_signed_out_answer_stops_the_run_with_nothing_recorded_against_it(home):
    home.bank.folders["Posteingang"] = many("P", 12)
    home.run("--discover")
    home.bank.signed_out = True
    with pytest.raises(SystemExit) as stop:
        home.run("--resume")
    assert stop.value.code == 0
    said = " ".join(home.capsys.readouterr().out.split())
    assert "Your session has expired" in said or "signed you out" in said, said
    assert home.bank.fetched == []
    assert home.on_disk() == []
    assert "Completed" not in home.states()


def test_a_sign_in_page_in_place_of_a_pdf_stops_the_run_when_the_list_answers_signed_out(home):
    """A sign-in page served with 200 in place of the PDF says nothing a
    file can tell. The folder's list is asked for again, and its answer as
    signed out stops the run there, rather than fail every document after
    it one by one."""
    home.bank.folders["Posteingang"] = [message("P3", "Kontoauszug 3/2031", "02.04.2031"),
                                        message("P2", "Kontoauszug 2/2031", "02.03.2031"),
                                        message("P1")]
    home.run("--discover")
    home.bank.signs_out = "P3"
    with pytest.raises(SystemExit) as stop:
        home.run("--resume")
    assert stop.value.code == 0
    said = " ".join(home.capsys.readouterr().out.split())
    assert "Your session has expired" in said
    assert home.bank.fetched == ["P3"]
    assert home.on_disk() == []
    assert set(home.states()) <= {"Discovered"}


# -- the list is whole or it is not called whole --------------------------------

def test_a_missing_pager_on_a_full_page_stops_the_listing(home):
    home.bank.pager = None
    home.bank.folders["Posteingang"] = many("P", 15)
    said = discover_stops(home)
    assert "full page with no pager" in said


def test_a_pager_that_leaves_once_a_folder_is_turned_stops_the_listing(home):
    home.bank.pager_leaves = True
    home.bank.folders["Posteingang"] = many("P", 15)
    discover_stops(home)


def test_an_active_page_number_that_cannot_be_read_stops_the_listing(home):
    home.bank.active = False
    home.bank.folders["Posteingang"] = many("P", 15)
    said = discover_stops(home)
    assert "active page number cannot be read" in said


def test_a_row_shape_with_no_direct_download_anywhere_stops_the_listing(home):
    """A link renamed by the bank read every row as a message with no PDF,
    and the list was called whole with nothing in it."""
    home.bank.link_class = "postbox-message-download-v2"
    home.bank.folders["Posteingang"] = many("P", 3)
    said = discover_stops(home)
    assert "No Postfach row offers a direct download" in said


def test_a_downloadable_row_with_no_identity_stops_the_listing(home):
    home.bank.folders["Posteingang"] = many("P", 3)
    home.bank.folders["Posteingang"][1]["identity"] = ""
    said = discover_stops(home)
    assert "no document identity" in said


def test_a_ticked_row_is_never_sent_with_a_page_press(home):
    """A row the person ticked would go with the press. The listing opens
    each folder afresh, so this is the turn itself, on a page with a row
    ticked."""
    home.bank.folders["Posteingang"] = many("P", 15)
    home.page.goto(BASE + site.FOLDERS["Posteingang"])
    home.page.locator('input[type="checkbox"]').first.check()
    with pytest.raises(site.ListStopped, match="Clear any selected rows"):
        site._turn(home.page, 2, home.config)
    assert home.bank.presses == []


def test_a_renamed_next_arrow_stops_the_listing_rather_than_read_page_one_only(home):
    """The pager still offers page 2, and no next arrow this can read says
    there is one. Read as the last page, the listing ended at page 1."""
    home.bank.next_class = "pager-next"
    home.bank.folders["Posteingang"] = many("P", 25)
    said = discover_stops(home)
    assert "offers a later page and no next page" in said
    assert home.bank.presses == []


def test_renamed_rows_beside_a_pager_stop_the_listing_rather_than_read_empty(home):
    """Rows of a class this does not read showed as no rows at all, so a
    Postfach of three pages was listed whole with nothing in it. A short
    folder with no pager and no rows still reads as empty, which only the
    bank's own empty notice could tell apart."""
    home.bank.row_class = "postbox-row-v2"
    home.bank.folders["Posteingang"] = many("P", 25)
    said = discover_stops(home)
    assert "a pager and no rows" in said


def test_a_row_ticked_during_the_pause_is_never_sent_with_the_press(home, monkeypatch):
    """The pause comes before the look for ticked rows, so a row the person
    ticks while the run waits is seen before the press, not after it."""
    home.bank.folders["Posteingang"] = many("P", 15)
    home.page.goto(BASE + site.FOLDERS["Posteingang"])

    def pause(config=None):
        home.page.locator('input[type="checkbox"]').first.check()
    monkeypatch.setattr(site, "_pause", pause)
    with pytest.raises(site.ListStopped, match="Clear any selected rows"):
        site._turn(home.page, 2, home.config)
    assert home.bank.presses == []


def test_a_statement_the_postfach_files_as_other_is_found_again_and_saved(home, monkeypatch):
    """The record files a row of no known kind whose subject says
    Kontoauszug as a Statement, and the download has to find its row the
    same way (filed_category). The app's own classify already files such
    a subject as a Statement, so a narrower one stands in for it here, as
    a later change to its words could make it."""
    monkeypatch.setattr(site, "classify", lambda kind, title="": "Other Document")
    home.bank.folders["Posteingang"] = [message("P2", "Kontoauszug 2/2031", "02.03.2031"),
                                        message("P1", "Ihre Unterlagen", "02.02.2031")]
    code, said = home.run_all()
    assert code == 0, said
    assert home.on_disk() == ["P1", "P2"]
    categories = {rec["title"]: rec["category"] for rec in home.store("progress.json").values()}
    assert categories == {"Kontoauszug 2/2031": "Statement", "Ihre Unterlagen": "Other Document"}


def test_a_list_that_stops_while_documents_download_stops_the_run_once(home):
    home.bank.folders["Posteingang"] = many("P", 15)
    home.run("--discover")
    assert home.listed_whole()
    home.bank.active = False
    with pytest.raises(ListNotRead):
        home.run("--resume")
    assert home.bank.fetched == []
    assert home.store("progress.json") == {}
    assert not home.listed_whole()


# -- each document's own bytes ----------------------------------------------------

def test_two_documents_alike_are_two_documents_each_with_its_own_bytes(home):
    home.bank.folders["Posteingang"] = [message("K1", "Information"), message("K2", "Information")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["K1", "K2"]
    assert sorted(home.held().values()) == ["K1", "K2"]


def test_a_reordered_list_leaves_each_number_with_its_document(home):
    """Two notes of one day and one title, listed again in the other order
    and across another page. A place would hand each the other's bytes."""
    alike = [message("K1", "Information"), message("K2", "Information")]
    home.bank.folders["Posteingang"] = alike + many("P", 9, day="01.01.2031")
    home.run("--discover")
    numbered = {key: rec["item_id"] for key, rec in home.store("discovery.json").items()
                if rec["title"] == "Information"}
    assert sorted(numbered.values()) == sorted(home.item_of(m) for m in alike)
    home.bank.folders["Posteingang"] = many("P", 9, day="01.01.2031") + alike[::-1]
    code, said = home.run("--resume")
    assert code == 0, said
    by_item = {home.item_of(m): m["name"] for m in alike}
    held = home.held()
    assert {key: held[key] for key in numbered} == {key: by_item[item] for key, item in numbered.items()}


def test_a_document_gone_from_the_list_fails_and_says_so(home):
    home.bank.folders["Posteingang"] = [message("P1")]
    home.run("--discover")
    home.bank.folders["Posteingang"] = []
    code, _said = home.run("--resume")
    assert code == 1
    assert home.bank.fetched == []
    notes = [rec.get("notes", "") for rec in home.store("progress.json").values()]
    assert any("no longer shows this document" in n for n in notes)


def test_a_second_run_skips_what_was_saved(home):
    home.bank.folders["Posteingang"] = [message("P2", "Kontoauszug 2/2031", "02.03.2031"),
                                        message("P1")]
    code, _said = home.run_all()
    assert code == 0
    assert home.on_disk() == ["P1", "P2"]
    code, said = home.run_all()
    assert code == 0
    assert home.bank.fetched == [] and home.bank.prepared == []
    assert said.count("Already downloaded and verified - skipping.") == 2
    assert home.on_disk() == ["P1", "P2"]


# -- the person's tab ------------------------------------------------------------

def test_with_the_persons_tab_off_the_site_a_run_works_in_a_tab_of_its_own(home):
    """Every tab of the person's is on another site. Login, Discover and a
    run open the Postfach in a tab of the run's own, by its address, and the
    person's tab is never read, pressed or loaded."""
    home.bank.folders["Posteingang"] = [message("P1")]
    home.page.goto(ELSEWHERE)
    seen = home.bank.elsewhere
    code, said = home.run("--login")
    assert code == 0
    assert "Success" in said
    code, said = home.run_all()
    assert code == 0, said
    assert home.on_disk() == ["P1"]
    assert home.page.url == ELSEWHERE
    assert home.bank.elsewhere == seen
    assert len(home.context.pages) >= 2


# -- the sign-in ---------------------------------------------------------------

@pytest.mark.parametrize("signed_in", [True, False])
def test_login_says_success_only_when_the_list_answers(home, signed_in):
    home.bank.signed_out = not signed_in
    home.page.goto(BASE + site.FOLDERS["Posteingang"])
    code, said = home.run("--login")
    assert code == 0
    assert ("Success" in said) is signed_in


def test_only_a_drawn_password_field_reads_as_a_sign_in_page(home):
    """The signed-in Postfach keeps a password field in hidden sign-in UI,
    which the contributor's own session showed (#216), so a field kept out
    of sight leaves the Postfach signed in, while one the page draws is a
    sign-in page. The reason is named in
    core/tests/test_every_app_counts_every_password_field.py."""
    home.page.goto(BASE + site.FOLDERS["Posteingang"])
    assert not site.looks_signed_out(home.page)
    home.page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
        '<form style="display:none"><input type="password" name="pin"></form>')""")
    assert not site.looks_signed_out(home.page)
    assert site.survey(home.page, dwell_ms=0)["pages"][0]["password_fields"] == 0
    home.page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
        '<form><input type="password" name="pin2"></form>')""")
    assert site.looks_signed_out(home.page)
    assert site.survey(home.page, dwell_ms=0)["pages"][0]["password_fields"] == 1
