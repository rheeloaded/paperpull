"""Raisin's lists, its request guard and its PDF check, on invented values.

Nobody here has a Raisin account, so every answer below is invented in the
shape the routes were recorded in (Habeas sources, sources/raisin.json, CC0).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import raisin_site as site
from fake_raisin import CUSTOMER, DASHBOARD, FakePage
from paperpull_core import identity, pdf_reader
from paperpull_core.testkit import sample_pdf, text_pdf


# -- hosts, the customer number and the request guard --------------------------

@pytest.mark.parametrize("url", [
    "https://www.raisin.com/",
    "https://api2.weltsparen.de/dbff/v1/public/deposits/dashboard/active",
])
def test_the_two_hosts_are_allowed(url):
    assert site.is_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://www.raisin.com/", "https://raisin.com/", "https://de.raisin.com/",
    "https://api.weltsparen.de/", "https://api2.weltsparen.de:8443/",
    "https://user@api2.weltsparen.de/", "https://api2.weltsparen.de.evil.test/",
    "https://www.raisin.com\\@evil.test/", "https://www.raisin.us/",
    "https://www.weltsparen.de/",
])
def test_every_other_host_is_refused(url):
    assert not site.is_safe_url(url)


def test_the_page_host_is_only_www_raisin_com():
    assert site.is_page_url("https://www.raisin.com/x")
    assert not site.is_page_url("https://api2.weltsparen.de/x")


@pytest.mark.parametrize("query", [
    "", "?customer_id=", "?customer_id=BAC_", "?customer_id=BAC_12a",
    "?customer_id=bac_123", "?customer_id=CUS_123", "?customer_id=BAC_1%26x%3D2",
    "?customer_id=BAC_1&customer_id=BAC_2",
])
def test_a_customer_number_of_another_shape_is_none(query):
    assert site.customer_of("https://www.raisin.com/savings/" + query) == ""


def test_the_customer_number_is_read_from_the_dashboards_address():
    assert site.customer_of(DASHBOARD % CUSTOMER) == CUSTOMER
    assert site.customer_of(DASHBOARD % CUSTOMER + "&customer_id=" + CUSTOMER) == CUSTOMER
    assert site.customer_of("https://evil.test/?customer_id=" + CUSTOMER) == ""


@pytest.mark.parametrize("path", [
    "/tams/v1/accounts", "/dds/api/v2/public/documents/../x",
    "/dds/api/v2/public/documents/a/b", "/dbff/v1/public/deposits/dashboard/all",
])
def test_a_request_this_app_does_not_make_is_never_asked(path):
    page = FakePage()
    with pytest.raises(ValueError):
        site._ask(page, path, {}, "json", 1000)
    assert not page.asked


# -- the lists ---------------------------------------------------------------

def test_every_deposit_active_and_ended_is_listed_with_its_documents():
    page = FakePage()
    docs = site.collect_documents(page)
    assert sorted(d.key_part for d in docs) == [
        "FDA_t001:d0001", "FDA_t003:d0003", "OMA_t002:d0002"]
    by_id = {d.document_id: d for d in docs}
    assert by_id["d0001"].created == "2026-03-05"
    assert by_id["d0001"].deposit_kind == "term_deposits" and by_id["d0002"].deposit_kind == "overnight_savings"
    assert all(d.customer == site.tag(CUSTOMER) and CUSTOMER not in repr(d) for d in docs)
    paths = [(p, q) for p, q, _ in page.asked]
    assert paths[0] == (site.ACTIVE_PATH, {"customer_id": CUSTOMER, "locale": site.LOCALE,
                                           "sort_by": "availability", "order_by": "asc"})
    assert paths[1][0] == site.INACTIVE_PATH
    assert [q["deposit_id"] for p, q in paths[2:]] == ["FDA_t001", "OMA_t002", "FDA_t003"]
    assert site.last_listing()["deposits"] == {"term_deposits": 2, "overnight_savings": 1}


def test_an_object_holding_its_entries_under_a_known_key_is_read():
    page = FakePage()
    page.body[site.ACTIVE_PATH] = json.dumps({"deposits": page.active})
    assert len(site.collect_documents(page)) == 3


@pytest.mark.parametrize("body", [
    json.dumps({"something": []}), json.dumps({"deposits": [], "items": []}),
    json.dumps(None), json.dumps(["FDA_t001"]), "<html>login</html>",
])
def test_a_deposits_answer_of_another_shape_stops_the_list(body):
    page = FakePage()
    page.body[site.ACTIVE_PATH] = body
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert "shapes" in site._RUN or body.startswith("<")


def test_no_deposits_at_all_is_a_whole_empty_list():
    page = FakePage()
    page.active, page.inactive = [], []
    assert site.collect_documents(page) == []
    assert site._RUN["docs"] == {}


def test_a_deposit_with_no_documents_is_whole():
    page = FakePage()
    page.documents["OMA_t002"] = []
    assert len(site.collect_documents(page)) == 2


@pytest.mark.parametrize("entry", [
    {}, {"accounting": None}, {"accounting": {}}, {"accounting": {"deposit_id": ""}},
    {"accounting": {"deposit_id": "XYZ_t009"}}, {"accounting": {"deposit_id": "FDA_"}},
    {"accounting": {"deposit_id": "FDA_../x"}}, {"accounting": {"deposit_id": "OMA_a/b"}},
    {"accounting": {"deposit_id": "FDA_t1?x=1"}}, {"accounting": {"deposit_id": "FDA_%2e%2e"}},
    {"accounting": {"deposit_id": "fda_t001"}}, {"accounting": {"deposit_id": "FDA_" + "a" * 300}},
])
def test_a_deposit_it_does_not_recognize_stops_the_list_before_it_is_asked_about(entry):
    page = FakePage()
    page.inactive = [entry]
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert not any(p == site.DOCUMENTS_PATH for p, _, _ in page.asked)


@pytest.mark.parametrize("change", [
    {"id": None}, {"id": ""}, {"id": "../d1"}, {"id": "d1/../../x"}, {"id": "d1?preview=false"},
    {"id": "d1#"}, {"id": "%2F"}, {"id": "d 1"}, {"title": ""}, {"title": None},
    {"document_type": None}, {"created": "03.05.2026"}, {"created": "2026-13-01"},
    {"created": "2026-02-30"}, {"created": "yesterday"}, {"created": ""}, {"created": "20260503"},
    {"created": 20260503},
])
def test_a_document_it_does_not_recognize_stops_the_list(change):
    page = FakePage()
    page.documents["OMA_t002"][0].update(change)
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)


@pytest.mark.parametrize("missing", ["id", "created", "title", "document_type"])
def test_a_document_missing_a_field_stops_the_list(missing):
    page = FakePage()
    del page.documents["OMA_t002"][0][missing]
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)


@pytest.mark.parametrize("value, day", [
    ("2026-05-03", "2026-05-03"), ("2026-05-03T09:14:00Z", "2026-05-03"),
    ("2026-05-03T09:14:00+01:00", "2026-05-03"), ("2026-05-03T09:14:00.123Z", "2026-05-03"),
    ("2026-05-03T23:59", "2026-05-03"),
])
def test_a_created_date_or_timestamp_is_its_day(value, day):
    assert site.created_date(value) == day


def test_a_documents_answer_of_another_shape_stops_the_list():
    for body in (json.dumps([]), json.dumps({"documents": {}}), json.dumps({"items": []})):
        page = FakePage()
        page.body["FDA_t003"] = body
        with pytest.raises(site.ListStopped):
            site.collect_documents(page)


def test_one_document_listed_twice_alike_is_one_and_differently_stops():
    page = FakePage()
    page.documents["FDA_t001"].append(dict(page.documents["FDA_t001"][0]))
    assert len(site.collect_documents(page)) == 3
    page.documents["FDA_t001"][1]["title"] = "Kontoauszug neu"
    with pytest.raises(site.ListStopped, match="twice"):
        site.collect_documents(page)


def test_one_id_under_two_deposits_is_two_documents():
    page = FakePage()
    page.documents["FDA_t003"] = [dict(page.documents["FDA_t001"][0])]
    docs = site.collect_documents(page)
    assert len({d.key_part for d in docs if d.document_id == "d0001"}) == 2


@pytest.mark.parametrize("status, error", [
    (401, site.SessionExpired), (403, site.ListStopped), (429, site.ListStopped),
    (500, site.ListStopped),
])
@pytest.mark.parametrize("where", ["active", "inactive", "second deposit"])
def test_every_list_that_does_not_answer_says_what_it_is(status, error, where):
    page = FakePage()
    # A whole list first, so a list that stops after it is seen to drop it.
    assert len(site.collect_documents(page)) == 3
    key = {"active": site.ACTIVE_PATH, "inactive": site.INACTIVE_PATH,
           "second deposit": "OMA_t002"}[where]
    page.status[key] = status
    with pytest.raises(error):
        site.collect_documents(page)
    assert "docs" not in site._RUN, "a list that stopped was kept as the run's list"


@pytest.mark.parametrize("held", [None, "", "not json", "{}", json.dumps({"access_token": ""}),
                                  json.dumps({"access_token": 123}), json.dumps("x")])
def test_a_page_with_no_token_is_signed_out_and_nothing_is_asked(held):
    page = FakePage()
    if held is None:
        del page.storage["auth_token"]
    else:
        page.storage["auth_token"] = held
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)
    assert not page.asked


def test_a_tab_without_the_customer_number_asks_nothing():
    page = FakePage()
    page.url = "https://www.raisin.com/savings/"
    with pytest.raises(site.ListStopped, match="dashboard"):
        site.collect_documents(page)
    assert not page.asked


def test_a_tab_that_changes_customer_partway_stops_the_list():
    page = FakePage()

    def move(p, path, query):
        if query.get("deposit_id") == "FDA_t001":
            p.url = DASHBOARD % "BAC_000000000077"
    page.on_ask = move
    with pytest.raises(site.ListStopped, match="another customer"):
        site.collect_documents(page)


def test_a_page_script_that_raises_is_a_stopped_list():
    page = FakePage()

    def boom(*a):
        raise RuntimeError("Target page, context or browser has been closed")
    page.evaluate = boom
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)


# -- the file ------------------------------------------------------------------

def test_the_file_is_asked_for_by_its_id_and_preview():
    page = FakePage()
    data = site.fetch_file(page, "d0001")
    assert data.startswith(b"%PDF-")
    assert page.asked[-1] == ("/dds/api/v2/public/documents/d0001", {"preview": "true"}, "pdf")


@pytest.mark.parametrize("status", [403, 404, 500])
def test_a_file_that_is_not_handed_over_is_refused(status):
    page = FakePage()
    page.status["d0001"] = status
    with pytest.raises(site.Refused):
        site.fetch_file(page, "d0001")


def test_a_file_answered_as_signed_out_is_a_refusal_the_list_weighs():
    page = FakePage()
    page.status["d0001"] = 401
    with pytest.raises(site.Refused):
        site.fetch_file(page, "d0001")


def test_neighbors_are_either_side_and_every_row_of_the_same_day():
    rows = [("2026-0%d-01" % m, "t") for m in range(1, 10)] + [("2026-01-01", "u")]
    assert site.neighbors(rows, 0) == rows[1:4] + [rows[9]]
    assert site.neighbors(rows, 20) == []


@pytest.mark.parametrize("data", [b"<html>", b'{"error": 1}', b"\xef\xbb\xbf%PDF-1.4", b" %PDF-1.4"])
def test_bytes_that_do_not_start_as_a_pdf_are_refused(data):
    page = FakePage()
    page.files["d0001"] = data
    with pytest.raises(site.Refused):
        site.fetch_file(page, "d0001")


def test_an_unsafe_id_is_refused_before_anything_is_asked():
    page = FakePage()
    with pytest.raises(site.Refused):
        site.fetch_file(page, "../d1")
    assert not page.asked


# -- the PDF check ---------------------------------------------------------------

def text_of(data):
    return " ".join(pdf_reader.page_texts(data, pages=3))


def row(date, title="Kontoauszug"):
    return (date, title)


def pdf(*lines):
    return text_of(text_pdf(list(lines) + ["Dieses Dokument wurde maschinell erstellt."]))


def test_a_pdf_that_shows_the_issuer_and_its_own_date_is_placed():
    text = pdf("Raisin Bank AG", "Kontoauszug", "Datum 05.03.2026")
    assert site.check_text(text, "2026-03-05", "Kontoauszug",
                           [row("2026-02-05"), row("2026-04-05")])[0] == ""


@pytest.mark.parametrize("printed", ["2026-03-05", "5.3.2026", "5. März 2026", "05. Maerz 2026"])
def test_each_named_date_form_is_read(printed):
    assert site.check_text(pdf("Weltsparen", "Datum " + printed), "2026-03-05", "Kontoauszug")[0] == ""


def test_a_day_first_date_is_never_read_month_first():
    # 03.05.2026 is the third of May. A May 3 PDF is not the March 5 row's,
    # whether or not the May row is in the run.
    may = pdf("Raisin", "Datum 03.05.2026")
    assert site.check_text(may, "2026-03-05", "Kontoauszug")[0] == site.UNCONFIRMED
    assert site.check_text(may, "2026-03-05", "Kontoauszug", [row("2026-05-03")])[0] == site.WRONG
    assert site.check_text(may, "2026-05-03", "Kontoauszug", [row("2026-03-05")])[0] == ""


def test_the_core_date_check_would_have_read_it_month_first():
    # Why the row's date is never handed to the core's check.
    assert "03.05.2026" in identity.date_variants("2026-03-05")
    assert not site.identity_for(type("D", (), {"date": "2026-03-05", "title": "x"})()).date


def test_a_neighbors_date_without_its_own_is_wrong():
    text = pdf("Raisin", "Datum 30.04.2026")
    assert site.check_text(text, "2026-05-31", "Kontoauszug", [row("2026-04-30")])[0] == site.WRONG


def test_its_own_date_inside_a_longer_one_is_not_found():
    assert site.check_text(pdf("Raisin", "Datum 15.01.2026"), "2026-01-05",
                           "Kontoauszug")[0] == site.UNCONFIRMED
    assert site.check_text(pdf("Raisin", "Datum 5.1.20261"), "2026-01-05",
                           "Kontoauszug")[0] == site.UNCONFIRMED


def test_a_pdf_that_names_no_issuer_is_unconfirmed():
    text = pdf("Musterbank AG", "Kontoauszug", "Datum 05.03.2026")
    assert site.check_text(text, "2026-03-05", "Kontoauszug")[0] == site.UNCONFIRMED


def test_an_issuer_word_inside_another_word_does_not_count():
    text = pdf("Raisinsbank AG", "Datum 05.03.2026")
    assert site.check_text(text, "2026-03-05", "Kontoauszug")[0] == site.UNCONFIRMED
    assert site.check_text(pdf("WELTSPAREN", "Datum 05.03.2026"), "2026-03-05", "x")[0] == ""


def test_a_pdf_with_no_text_is_unreadable():
    assert site.check_text(text_of(sample_pdf()), "2026-03-05", "Kontoauszug")[0] == site.UNREADABLE
    assert site.check_text("", "2026-03-05", "Kontoauszug")[0] == site.UNREADABLE


def test_two_documents_on_one_day_need_their_own_title():
    rivals = [row("2026-06-30", "Zinsbescheinigung")]
    mine = pdf("Raisin", "Kontoauszug", "Datum 30.06.2026")
    theirs = pdf("Raisin", "Zinsbescheinigung", "Datum 30.06.2026")
    neither = pdf("Raisin", "Mitteilung", "Datum 30.06.2026")
    assert site.check_text(mine, "2026-06-30", "Kontoauszug", rivals)[0] == ""
    assert site.check_text(theirs, "2026-06-30", "Kontoauszug", rivals)[0] == site.WRONG
    assert site.check_text(neither, "2026-06-30", "Kontoauszug", rivals)[0] == site.UNCONFIRMED


def test_the_check_says_which_facts_it_saw_never_their_values():
    why, found = site.check_text(pdf("Raisin", "Kontoauszug", "Datum 05.03.2026"),
                                 "2026-03-05", "Kontoauszug")
    assert why == "" and set(found) == {"issuer", "date", "title"}


# -- the guard Record reads ------------------------------------------------------

@pytest.mark.parametrize("label", [
    "Geld überweisen", "Auszahlung", "Jetzt anlegen", "Festgeld verlängern", "Kündigen",
    "Transfer money", "Open new deposit", "Referenzkonto ändern", "Abmelden",
    "Dokument löschen", "Bestätigen", "Download and confirm",
])
def test_the_guard_refuses_what_moves_money_or_changes_anything(label):
    assert not site.is_safe_control(label)


@pytest.mark.parametrize("label", ["Dokumente", "Postfach", "Download", "PDF herunterladen",
                                   "Kontoauszüge anzeigen", "Documents"])
def test_the_guard_lets_document_words_through(label):
    assert site.is_safe_control(label)
