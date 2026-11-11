"""How the Postbox is read: as its page shows it, row by row, pressing
nothing, and stopping rather than guessing when a list is not read whole.

The rows here are invented, in the shape _ROWS_JS hands back. Whether ING's
page shows its rows that way is checked only on an account (README)."""
import base64
import copy
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ing_site as site
from paperpull_core import intake

POSTBOX = "https://banking.ing.de/app/postbox/postbox"
ARCHIVE = "https://banking.ing.de/app/postbox/postbox_archiv"
OBLIGO = "https://banking.ing.de/app/obligo"


def link(name, base=POSTBOX):
    return f"{base}?1-1.-rows-{name}-download"


def row(name="d1", kind="Kontoauszug", subject="Kontoauszug 1/2026", date="31.01.2026",
        unread=False, hrefs=None, base=POSTBOX):
    return {"kind": kind, "subject": subject, "date": date, "unread": unread,
            "hrefs": [link(name, base)] if hrefs is None else list(hrefs)}


def look(*rows, table=True, settled=True, truncated=False, empty=False, pagination=0):
    return {"table_present": table, "settled": settled, "truncated": truncated,
            "empty": empty, "pagination": pagination, "rows": list(rows)}


EMPTY = look(table=False, empty=True)


def pdf(name):
    return b"%PDF-1.4\n% " + name.encode() + b"\n%%EOF\n"


def file_answer(data):
    return {"state": "file", "b64": base64.b64encode(data).decode()}


class _Count:
    def __init__(self, n):
        self.n = n

    def count(self):
        return self.n


class Page:
    """A tab on ING's banking host. `areas` holds what each list shows, as
    _ROWS_JS would hand it back (or a function of the page), and `files`
    what fetching each link answers. A link not in `files` answers as an
    expired one may: with a page."""

    def __init__(self, url=POSTBOX, areas=None, files=None):
        self.url = url
        self.areas = dict(areas or {})
        self.files = dict(files or {})
        self.lands = {}          # an address that opens another page
        self.password = False    # ING's sign-in form on screen
        self.version = 0         # goes up with each page opened
        self.gotos, self.looks, self.fetched = [], [], []

    def goto(self, url, **_):
        self.gotos.append(url)
        self.version += 1
        self.url = self.lands.get(url, url)

    def wait_for_timeout(self, _ms):
        pass

    def title(self):
        return "ING Banking"

    def locator(self, selector):
        return _Count(1 if self.password and "password" in selector else 0)

    def evaluate(self, js, arg=None):
        if isinstance(arg, dict) and "rowSelectors" in arg:
            area = site._list_area(self.url)
            self.looks.append((area, arg["scroll"]))
            seen = self.areas.get(area, look(table=False))
            seen = seen(self) if callable(seen) else seen
            if isinstance(seen, Exception):
                raise seen
            return copy.deepcopy(seen)
        if isinstance(arg, dict) and "url" in arg:
            assert "const ppLimit" in js          # read through intake, to its limit
            assert arg["host"] == "banking.ing.de"
            self.fetched.append(arg["url"])
            answer = self.files.get(arg["url"], {"state": "page", "password": False})
            answer = answer(self) if callable(answer) else answer
            if isinstance(answer, Exception):
                raise answer
            return answer
        raise AssertionError("an evaluate this app does not make")


def numbered(rows):
    """Rows numbered among those alike, as a first Discover numbers them."""
    seen, out = {}, []
    for r in rows:
        k = (r["title"], r["date"], r["account"], site.filed_category(r))
        out.append((seen.get(k, 0), True))
        seen[k] = seen.get(k, 0) + 1
    return out


def fetch_one(page, out, title="Kontoauszug 1/2026", date="2026-01-31", occurrence=0,
              twins=1, config=None):
    return site.download_document(page, title, date, out, occurrence, category=site.ACCOUNT,
                                  number_rows=numbered, twins=twins,
                                  config={"read_archive": False} if config is None else config)


# -- addresses ----------------------------------------------------------------

@pytest.mark.parametrize("address,area", [
    (POSTBOX, "postbox"),
    (POSTBOX + "?3", "postbox"),
    (POSTBOX + ";jsessionid=0A1B2C", "postbox"),
    ("https://banking.ing.de/app/postbox", "postbox"),
    ("https://banking.ing.de/app/postbox/", "postbox"),
    (ARCHIVE, "archive"),
    (ARCHIVE + "?7", "archive"),
    (OBLIGO, None),
    (POSTBOX + "/extra", None),
    ("http://banking.ing.de/app/postbox/postbox", None),
    ("https://www.ing.de/app/postbox/postbox", None),
    ("https://banking.ing.de.example/app/postbox/postbox", None),
    ("about:blank", None),
    ("", None),
])
def test_which_list_an_address_shows(address, area):
    assert site._list_area(address) == area


@pytest.mark.parametrize("href", [
    link("3"),
    link("0", ARCHIVE),
    "https://banking.ing.de/app/postbox/postbox?6-1.ILinkListener-rows-2-download",
    "https://banking.ing.de/app/postbox/dokument.pdf?id=0a1b2c",
])
def test_a_download_link_on_the_banking_host_is_followed(href):
    assert site._safe_download(href)


@pytest.mark.parametrize("href", [
    "http://banking.ing.de/app/postbox/postbox?1-1.-rows-3-download",
    "https://www.ing.de/app/postbox/postbox?1-1.-rows-3-download",
    "https://banking.ing.de.example/app/postbox?download",
    "https://user:secret@banking.ing.de/app/postbox/postbox?download",
    "https://banking.ing.de/postbox/download",
    "https://banking.ing.de/app/logout",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-archivieren",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-%61rchivieren",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-l%C3%B6schen",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-markAsRead",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-unread",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-archive",
    "https://banking.ing.de/app/postbox/postbox?action=%61rchive",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-move",
    "https://banking.ing.de/app/postbox/postbox?do=read",
    "https://banking.ing.de/app/postbox/postbox?1-1.-rows-3-delete",
    "https://banking.ing.de/app/ueberweisung/neu?download",
    "javascript:alert(1)",
    "",
])
def test_a_link_that_could_change_something_is_never_followed(href):
    assert not site._safe_download(href)


@pytest.mark.parametrize("text,last4", [
    ("Kontoauszug zu DE12 5001 0517 0123 4567 89", "6789"),
    ("Kontoauszug zu DE12500105170123456789", "6789"),
    ("Kreditkartenabrechnung 1234********5678 per 30.04.2026", "5678"),
    ("Kreditkarte ****4321", "4321"),
    ("Depotauszug zu Depot 509999999", "9999"),
    ("Kontoauszug Konto-Nr. 1234567890", "7890"),
    ("Kontoauszug 1/2026", ""),
    ("Mitteilung zu deinem Konto", ""),
    ("", ""),
])
def test_a_row_names_its_account_by_its_last_four_digits_only(text, last4):
    assert site._account(text) == last4


# -- one look at a list -------------------------------------------------------

@pytest.mark.parametrize("answer", [
    None,
    [],
    "rows",
    dict(look(), pagination=-1),
    dict(look(), pagination=True),
    dict(look(), pagination="1"),
    {k: v for k, v in look().items() if k != "settled"},
    dict(look(), settled="yes"),
    dict(look(), rows={"0": row()}),
    look("not a row"),
    look(dict(row(), kind=None)),
    look(dict(row(), unread="no")),
    look(dict(row(), hrefs="https://banking.ing.de/app/x")),
    look(row(hrefs=[link(str(i)) for i in range(site._MAX_LINKS + 2)])),
    look(row(hrefs=[""])),
    look(row(hrefs=[7])),
    look(row(hrefs=["https://banking.ing.de/app/" + "x" * 9000])),
])
def test_an_answer_in_a_shape_this_app_does_not_read_stops_the_list(answer):
    page = Page(areas={"postbox": answer})
    with pytest.raises(site.ListStopped, match="shape"):
        site._look(page, scroll=False)


def test_a_rows_words_are_read_with_their_spaces_tidied():
    page = Page(areas={"postbox": look(row(kind=" Konto\nauszug ", subject="Auszug \t 1/2026"))})
    seen = site._look(page, scroll=True)
    assert (seen["rows"][0]["kind"], seen["rows"][0]["subject"]) == ("Konto auszug", "Auszug 1/2026")
    assert page.looks == [("postbox", True)]


def test_a_look_the_page_could_not_answer_stops_or_finds_the_session_ended():
    page = Page(areas={"postbox": RuntimeError("Execution context was destroyed")})
    with pytest.raises(site.ListStopped):
        site._look(page, scroll=False)
    page.password = True
    with pytest.raises(site.SessionExpired):
        site._look(page, scroll=False)


# -- one list -----------------------------------------------------------------

def test_rows_passed_over_are_counted_by_why_and_only_rows_with_a_date_are_documents():
    page = Page(areas={"postbox": look(
        row("d1"),
        row("d2", subject="Kontoauszug 2/2026", date="28.02.2026", unread=True),
        row(subject="Kontoauszug 3/2026", date="31.03.2026", hrefs=[]),
        row(subject="Kontoauszug 4/2026", date="30.04.2026", hrefs=[link("a"), link("b")]),
        row(subject="Kontoauszug 5/2026", date="31.05.2026",
            hrefs=["https://banking.ing.de/app/logout"]),
        row(kind="", subject="Januar 2026", date="", hrefs=[]),       # a heading
        row("d7", subject="Kontoauszug 7/2026", date=""),
    )})
    area = site._read_area(page, "postbox", {"include_unread": False})
    assert [r["subject"] for r in area["rows"]] == ["Kontoauszug 1/2026"]
    assert (area["rows"][0]["date"], area["rows"][0]["date_text"]) == ("2026-01-31", "31.01.2026")
    assert area["skipped"] == {"unread": 1, "no_link": 1, "unclear": 1, "refused": 1}
    assert area["undated"] == 1
    assert len(area["candidates"]) == 6


def test_unread_rows_are_read_unless_include_unread_is_off():
    page = Page(areas={"postbox": look(row("d1", unread=True))})
    area = site._read_area(page, "postbox", {})
    assert len(area["rows"]) == 1 and area["skipped"]["unread"] == 0
    area = site._read_area(page, "postbox", {"include_unread": False})
    assert area["rows"] == [] and area["skipped"]["unread"] == 1


@pytest.mark.parametrize("seen,said", [
    (look(row(), truncated=True), "more rows than"),
    (look(row(), settled=False), "still loading"),
    (look(row(), pagination=1), "further page"),
    (look(row(kind="", subject="Januar 2026", date="", hrefs=[])), "no rows this app reads"),
    (look(table=False), "no rows this app reads"),
    (look(row(hrefs=[]), row(subject="Kontoauszug 2/2026", hrefs=[])), "menu"),
])
def test_a_list_not_read_whole_stops(seen, said):
    page = Page(areas={"postbox": seen})
    with pytest.raises(site.ListStopped, match=said):
        site._read_area(page, "postbox", {})


@pytest.mark.parametrize("source,where", [("postbox", "the Postbox"),
                                          ("archive", "the Postbox archive")])
def test_a_list_showing_only_the_notice_is_not_read_as_empty(source, where):
    """ING's notice that nothing matches is the same for an empty list and
    for a search or filter that finds nothing (#203)."""
    page = Page(url=site.URLS["archive" if source == "archive" else "documents"],
                areas={source: EMPTY})
    with pytest.raises(site.NotShownEmpty) as stop:
        site._read_area(page, source, {}, navigate=False)
    assert str(stop.value) == f"{where} shows no document, only ING's notice that nothing matches"
    assert stop.value.source == source and isinstance(stop.value, site.ListStopped)


def test_a_listing_leaves_out_a_list_showing_only_the_notice_and_names_it():
    page = Page(areas={"postbox": look(row()), "archive": EMPTY})
    rows = site._all_rows(page, {"read_archive": True}, fresh=True)
    assert [r["source"] for r in rows] == ["postbox"]
    assert site.not_shown_empty() == ["archive"]
    assert site._listing["rows"] == rows
    page.areas["archive"] = look(row("a1", base=ARCHIVE, date="31.01.2019"))
    rows = site._all_rows(page, {"read_archive": True}, fresh=True)
    assert [r["source"] for r in rows] == ["postbox", "archive"]
    assert site.not_shown_empty() == []
    page.areas["postbox"] = EMPTY
    rows = site._all_rows(page, {"read_archive": True}, fresh=True)
    assert [r["source"] for r in rows] == ["archive"]
    assert site.not_shown_empty() == ["postbox"]


def test_a_listing_that_stops_leaves_no_list_named_from_the_one_before():
    page = Page(areas={"postbox": look(row()), "archive": EMPTY})
    site._all_rows(page, {"read_archive": True}, fresh=True)
    page.areas["postbox"] = look(row(), pagination=1)
    with pytest.raises(site.ListStopped):
        site._all_rows(page, {"read_archive": True}, fresh=True)
    assert site.not_shown_empty() == []


def test_rows_alike_are_told_apart_only_by_their_place():
    page = Page(areas={"postbox": look(row("a"), row("b"), row("c", subject="Kontoauszug 2/2026"))})
    rows = site._read_area(page, "postbox", {})["rows"]
    assert [(r["rank"], r["group"]) for r in rows] == [(0, 2), (1, 2), (0, 1)]
    assert rows[0]["sig"] == rows[1]["sig"] != rows[2]["sig"]


def test_reading_a_list_opens_its_address_only_from_another_page():
    page = Page(url=OBLIGO, areas={"postbox": look(row())})
    site._read_area(page, "postbox", {})
    site._read_area(page, "postbox", {})
    assert page.gotos == [POSTBOX]


def test_an_address_that_lands_elsewhere_stops_and_a_sign_in_page_ends_the_session():
    page = Page(url=OBLIGO)
    page.lands[POSTBOX] = OBLIGO
    with pytest.raises(site.ListStopped, match="another page"):
        site._read_area(page, "postbox", {})
    page.lands[POSTBOX] = "https://banking.ing.de/app/login"
    with pytest.raises(site.SessionExpired):
        site._read_area(page, "postbox", {})


def test_without_navigating_only_the_list_on_screen_is_read():
    page = Page(url=OBLIGO, areas={"postbox": look(row())})
    with pytest.raises(site.ListStopped, match="not the Postbox"):
        site._read_area(page, "postbox", {}, navigate=False)
    page.url = POSTBOX
    site._read_area(page, "postbox", {}, navigate=False, scroll=False)
    assert page.gotos == [] and page.looks == [("postbox", False)]
    page.password = True
    with pytest.raises(site.SessionExpired):
        site._read_area(page, "postbox", {}, navigate=False)


# -- a listing ----------------------------------------------------------------

def two_lists():
    return {"postbox": look(row("p1", subject="Kontoauszug 2/2026", date="28.02.2026"),
                            row("p2", kind="Depotauszug", subject="Depotauszug zu Depot 509999999",
                                date="31.12.2025")),
            "archive": look(row("a1", subject="Kontoauszug 1/2025", date="31.01.2025",
                                base=ARCHIVE))}


def test_a_listing_reads_the_postbox_and_then_its_archive():
    page = Page(url=OBLIGO, areas=two_lists())
    rows = site._all_rows(page, {})
    assert [(r["source"], r["client_id"], r["href"], r["date"]) for r in rows] == [
        ("postbox", "postbox", POSTBOX, "2026-02-28"),
        ("postbox", "postbox", POSTBOX, "2025-12-31"),
        ("archive", "archive", ARCHIVE, "2025-01-31")]
    assert page.gotos == [POSTBOX, ARCHIVE]
    assert page.looks == [("postbox", True), ("archive", True)]
    assert (rows[1]["category"], rows[1]["account"]) == (site.SECURITIES, "9999")
    assert rows[1]["title"] == "Depotauszug zu Depot 509999999"
    assert len({r["item_id"] for r in rows}) == 3


def test_a_rows_title_carries_its_type_where_its_subject_does_not_say_it():
    page = Page(areas={"postbox": look(row(kind="Mitteilung", subject="Neue Preise ab Juli")),
                       "archive": EMPTY})
    (only,) = site._all_rows(page, {})
    assert only["title"] == "Mitteilung - Neue Preise ab Juli"
    assert only["category"] == site.MESSAGE


def test_one_listing_serves_a_while_and_another_setting_reads_again(monkeypatch):
    page = Page(areas=two_lists())
    first = site._all_rows(page, {})
    assert site._all_rows(page, {}) is first and len(page.looks) == 2
    site._all_rows(page, {}, fresh=True)
    assert len(page.looks) == 4
    site._all_rows(page, {"include_unread": False})
    assert len(page.looks) == 6
    site._all_rows(page, {"include_unread": True, "read_archive": False})
    assert len(page.looks) == 7 and page.looks[-1][0] == "postbox"
    monkeypatch.setattr(site, "LISTING_SECONDS", 0)
    site._all_rows(page, {"include_unread": True, "read_archive": False})
    assert len(page.looks) == 8


@pytest.mark.parametrize("start", [POSTBOX, POSTBOX + "?3", ARCHIVE])
def test_a_listing_opens_each_list_by_its_address_not_the_view_on_screen(start):
    # The Postbox the person left on screen may hold a search or a filter
    # of their own, and a filtered list is not the whole one.
    page = Page(url=start, areas=two_lists())
    site._all_rows(page, {}, fresh=True)
    assert page.gotos == [POSTBOX, ARCHIVE]


def test_read_archive_false_leaves_the_archive_unopened():
    page = Page(url=OBLIGO, areas=two_lists())
    rows = site._all_rows(page, {"read_archive": False})
    assert {r["source"] for r in rows} == {"postbox"} and ARCHIVE not in page.gotos


def test_diagnose_reads_the_list_on_screen_as_it_stands_and_keeps_nothing():
    page = Page(url=ARCHIVE, areas=two_lists())
    rows = site._all_rows(page, {}, navigate=False)
    assert [r["source"] for r in rows] == ["archive"]
    assert page.gotos == [] and page.looks == [("archive", False)]
    assert "rows" not in site._listing
    page.url = OBLIGO
    with pytest.raises(site.ListStopped, match="not the Postbox"):
        site._all_rows(page, {}, navigate=False)
    page.url, page.password = POSTBOX, True
    with pytest.raises(site.SessionExpired):
        site._all_rows(page, {}, navigate=False)


def test_an_id_names_its_row_within_one_listing_only():
    page = Page(areas=two_lists())
    one = site._all_rows(page, {}, fresh=True)
    two = site._all_rows(page, {}, fresh=True)
    assert [r["sig"] for r in one] == [r["sig"] for r in two]
    assert not {r["item_id"] for r in one} & {r["item_id"] for r in two}


def test_a_list_where_no_row_has_a_date_stops_and_nothing_is_kept():
    page = Page(areas={"postbox": look(row(date="")), "archive": EMPTY})
    with pytest.raises(site.ListStopped, match="date"):
        site._all_rows(page, {})
    assert "rows" not in site._listing


def test_what_a_listing_left_out_is_counted_for_discover_to_say():
    page = Page(areas={
        "postbox": look(row("d1"), row("d2", subject="Kontoauszug 2/2026", date=""),
                        row("d3", subject="Kontoauszug 3/2026", unread=True)),
        "archive": look(row(subject="Kontoauszug 1/2025",
                            hrefs=[link("a", ARCHIVE), link("b", ARCHIVE)]))})
    site._all_rows(page, {"include_unread": False})
    assert site.undated() == 1
    assert site.skipped() == {"unread": 1, "no_link": 0, "unclear": 1, "refused": 0}


def test_documents_come_newest_first_within_the_years_and_kinds_kept():
    page = Page(areas=two_lists())
    assert [r["date"] for r in site.collect_documents(page, config={})] == \
        ["2026-02-28", "2025-12-31", "2025-01-31"]
    assert [r["date"] for r in site.collect_documents(page, keep=lambda y: y == "2025", config={})] == \
        ["2025-12-31", "2025-01-31"]
    assert [r["category"] for r in
            site.collect_documents(page, config={"document_types": [site.SECURITIES]})] == \
        [site.SECURITIES]


@pytest.mark.parametrize("seen", [look(row()), EMPTY, look()])
def test_the_postbox_answers_with_a_table_or_the_words_of_an_empty_one(seen):
    page = Page(url=OBLIGO, areas={"postbox": seen})
    assert site.answers_its_list(page) is True
    assert page.gotos == [POSTBOX]


def test_a_postbox_that_shows_no_list_does_not_answer():
    page = Page(areas={"postbox": look(table=False)})
    with pytest.raises(site.ListStopped):
        site.answers_its_list(page)
    page.password = True
    with pytest.raises(site.SessionExpired):
        site.answers_its_list(page)


def test_a_sign_in_page_on_the_banking_host_is_left_for_the_person():
    page = Page(url="https://banking.ing.de/app/login")
    assert site.goto_documents(page) is False and page.gotos == []


@pytest.mark.parametrize("start", ["about:blank", OBLIGO, "https://www.ing.de/"])
def test_any_other_page_is_sent_to_the_postbox_by_its_address(start):
    page = Page(url=start)
    assert site.goto_documents(page) is True and page.gotos == [POSTBOX]


@pytest.mark.parametrize("start", [POSTBOX, ARCHIVE])
def test_a_postbox_list_on_screen_is_left_as_it_is(start):
    page = Page(url=start)
    assert site.goto_documents(page) is True and page.gotos == []


# -- one document -------------------------------------------------------------

@pytest.mark.parametrize("data", [pdf("d1"), b"PK\x03\x04" + b"\0" * 30])
def test_a_document_comes_back_as_its_bytes(data):
    page = Page(files={link("d1"): file_answer(data)})
    assert site._fetch(page, link("d1")) == data
    assert page.fetched == [link("d1")]


@pytest.mark.parametrize("answer", [
    {"state": "page", "password": True},
    {"state": "status", "status": 401},
    {"state": "status", "status": 403},
    {"state": "elsewhere"},
])
def test_an_answer_of_a_session_signed_out_ends_the_run(answer):
    page = Page(files={link("d1"): answer})
    with pytest.raises(site.SessionExpired):
        site._fetch(page, link("d1"))


@pytest.mark.parametrize("answer,said", [
    ({"state": "status", "status": 500}, "status 500"),
    ({"state": "status", "status": "500"}, "status unknown"),
    ({"state": "moved"}, "another host"),
    ({"state": "refused"}, "not one this app follows"),
    ({"state": "other", "password": False}, "something other"),
    ({"state": "file", "b64": base64.b64encode(b"<html></html>").decode()}, "could not read"),
    ({"state": "file", "b64": "not base64!"}, "could not read"),
    (None, "something other"),
])
def test_any_other_answer_fails_the_document_and_not_the_session(answer, said):
    page = Page(files={link("d1"): answer})
    with pytest.raises(RuntimeError, match=said) as raised:
        site._fetch(page, link("d1"))
    assert not isinstance(raised.value, site.SessionExpired)


def test_an_expired_link_answers_with_a_page_and_no_bytes():
    page = Page(files={link("d1"): {"state": "page", "password": False}})
    assert site._fetch(page, link("d1")) is None
    page.password = True
    with pytest.raises(site.SessionExpired):
        site._fetch(page, link("d1"))


def test_a_fetch_the_browser_did_not_finish_fails_the_document_or_finds_the_session_ended():
    page = Page(files={link("d1"): {"state": "failed"}})
    with pytest.raises(site.FetchFailed, match="could not be fetched") as raised:
        site._fetch(page, link("d1"))
    assert not isinstance(raised.value, site.SessionExpired)
    page.password = True
    with pytest.raises(site.SessionExpired):
        site._fetch(page, link("d1"))


def test_an_answer_over_the_limit_is_refused():
    page = Page(files={link("d1"): RuntimeError(intake.READ_MARK + " of 10 bytes, 20")})
    with pytest.raises(intake.TooLarge):
        site._fetch(page, link("d1"))


def test_a_fetch_the_page_could_not_finish_fails_the_document_or_finds_the_session_ended():
    page = Page(files={link("d1"): RuntimeError("Execution context was destroyed")})
    with pytest.raises(RuntimeError, match="page changed") as raised:
        site._fetch(page, link("d1"))
    assert not isinstance(raised.value, site.SessionExpired)
    page.password = True
    with pytest.raises(site.SessionExpired):
        site._fetch(page, link("d1"))


def test_a_document_is_saved_from_the_link_its_row_shows_now(tmp_path):
    page = Page(areas={"postbox": look(row("d1"))}, files={link("d1"): file_answer(pdf("d1"))})
    got = fetch_one(page, tmp_path / "doc.pdf")
    assert (tmp_path / "doc.pdf").read_bytes() == pdf("d1")
    assert got == site._listing["rows"][0]["item_id"]


def versioned(page):
    return look(row(hrefs=[f"{POSTBOX}?{page.version}-1.-rows-0-download"]))


def test_a_link_that_answers_with_a_page_is_read_again_from_the_list_opened_afresh(tmp_path):
    page = Page(url=OBLIGO, areas={"postbox": versioned})
    page.files[f"{POSTBOX}?3-1.-rows-0-download"] = file_answer(pdf("d1"))
    assert fetch_one(page, tmp_path / "doc.pdf")
    assert (tmp_path / "doc.pdf").read_bytes() == pdf("d1")
    # The listing opens the list, then each try at the document opens it
    # afresh before its link is read, the second after the first answered
    # with a page.
    assert page.fetched == [f"{POSTBOX}?2-1.-rows-0-download", f"{POSTBOX}?3-1.-rows-0-download"]
    assert page.gotos == [POSTBOX, POSTBOX, POSTBOX]


def test_each_document_reads_its_link_from_its_list_opened_afresh(tmp_path):
    # A link read from the page an earlier document left on screen may name
    # its row by a place in the list that has moved since.
    page = Page(url=POSTBOX, areas={"postbox": versioned})
    page.files[f"{POSTBOX}?2-1.-rows-0-download"] = file_answer(pdf("d1"))
    site._all_rows(page, {"read_archive": False})
    page.gotos.clear()
    assert fetch_one(page, tmp_path / "doc.pdf")
    assert page.gotos == [POSTBOX] and page.fetched == [f"{POSTBOX}?2-1.-rows-0-download"]


def test_a_document_that_twice_answers_with_a_page_fails_and_saves_nothing(tmp_path):
    page = Page(url=OBLIGO, areas={"postbox": versioned})
    with pytest.raises(RuntimeError, match="page instead of the document"):
        fetch_one(page, tmp_path / "doc.pdf")
    assert not (tmp_path / "doc.pdf").exists() and len(page.fetched) == 2


def test_a_document_over_the_limit_saves_nothing(tmp_path):
    page = Page(areas={"postbox": look(row("d1"))},
                files={link("d1"): RuntimeError(intake.READ_MARK + " of 10 bytes, 20")})
    assert fetch_one(page, tmp_path / "doc.pdf") == ""
    assert not (tmp_path / "doc.pdf").exists()


def test_documents_alike_are_each_saved_from_their_own_row(tmp_path):
    page = Page(areas={"postbox": look(row("a"), row("b"))},
                files={link("a"): file_answer(pdf("a")), link("b"): file_answer(pdf("b"))})
    for n, name in enumerate("ab"):
        fetch_one(page, tmp_path / f"{name}.pdf", occurrence=n, twins=2)
        assert (tmp_path / f"{name}.pdf").read_bytes() == pdf(name)


def test_a_list_showing_another_number_of_documents_alike_is_not_guessed_at(tmp_path):
    page = Page(areas={"postbox": look(row("a"), row("b"))},
                files={link("a"): file_answer(pdf("a")), link("b"): file_answer(pdf("b"))})
    site._all_rows(page, {"read_archive": False})
    page.areas["postbox"] = look(row("a"), row("b"), row("c"))
    with pytest.raises(site.NotToldApart):
        fetch_one(page, tmp_path / "doc.pdf", twins=2)
    assert page.fetched == []


def test_a_document_marked_unread_since_the_listing_is_left_alone(tmp_path):
    page = Page(areas={"postbox": look(row("d1"))}, files={link("d1"): file_answer(pdf("d1"))})
    site._all_rows(page, {"read_archive": False, "include_unread": False})
    page.areas["postbox"] = look(row("d1", unread=True))
    with pytest.raises(RuntimeError, match="unread"):
        fetch_one(page, tmp_path / "doc.pdf",
                  config={"read_archive": False, "include_unread": False})
    assert page.fetched == []


@pytest.mark.parametrize("title,since", [
    ("Kontoauszug 9/2026", None),                                      # never listed
    ("Kontoauszug 1/2026", look(row("d2", subject="Kontoauszug 2/2026"))),   # gone since
])
def test_a_document_the_list_does_not_show_is_not_fetched(tmp_path, title, since):
    page = Page(areas={"postbox": look(row("d1"))}, files={link("d1"): file_answer(pdf("d1"))})
    site._all_rows(page, {"read_archive": False})
    if since:
        page.areas["postbox"] = since
    with pytest.raises(RuntimeError, match="no longer lists"):
        fetch_one(page, tmp_path / "doc.pdf", title=title)
    assert page.fetched == []


# -- what the page is asked to do ----------------------------------------------

def test_a_document_is_fetched_with_a_plain_get_from_the_tabs_own_host():
    js = site._FETCH_JS
    assert 'method: "GET"' in js and 'mode: "same-origin"' in js
    assert 'credentials: "same-origin"' in js and "location.hostname !== host" in js
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in js, verb
    assert "ppRead(r)" in js and ".arrayBuffer(" not in js


def test_nothing_on_the_page_is_pressed_typed_into_or_changed():
    src = inspect.getsource(site)
    for word in (".click(", ".submit(", "dispatchEvent", ".fill(", ".press(", ".tap(",
                 ".dblclick(", ".check(", ".select_option(", ".set_input_files(",
                 ".dispatch_event(", ".type("):
        assert word not in src, word
    for js in (site._ROWS_JS, site._POSTBOX_CENSUS_JS, site._FETCH_JS):
        for word in ("click", "submit", "focus(", "innerHTML", ".remove(", ".value =",
                     "setAttribute", "classList.add", "classList.remove"):
            assert word not in js, word
