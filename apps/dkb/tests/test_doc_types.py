"""DKB, the parts that can be tested before the Postfach is mapped. The
guard, the host allowlist, the date shapes, the folders, the sorting into
the Postfach's six kinds, the in-page calls, and the survey's redaction.
Every account number, IBAN and id below is invented."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import dkb_site as site
from paperpull_core import doc_types


@pytest.fixture(autouse=True)
def _no_listing_kept_between_tests(monkeypatch):
    monkeypatch.setattr(site, "_listing", {})


def test_the_folders_are_the_six_postfach_filters():
    assert storage.SPEC.provider == "DKB"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Kontoauszuege", "Kreditkartenabrechnungen", "Wertpapierdokumente",
         "Steuerbescheinigungen", "Vertragsinformationen", "Mitteilungen", "Sonstige Dokumente"]
    assert storage.SPEC.config_defaults["document_types"] == site.ALL_CATEGORIES + [site.OTHER]
    assert storage.ALL_CATEGORIES == site.ALL_CATEGORIES
    for category in site.ALL_CATEGORIES:
        assert category in storage.SPEC.routes
        assert category in storage.FALLBACK_SUMMARY
    # The two the core counts by its own names.
    assert site.ACCOUNT == doc_types.STATEMENT and site.TAX == doc_types.TAX


@pytest.mark.parametrize("text,category", [
    ("bankAccountStatement", site.ACCOUNT),
    ("Kontoauszug Nr. 10/2026", site.ACCOUNT),
    ("Rechnungsabschluss Tagesgeld", site.ACCOUNT),
    ("creditCardStatement", site.CARD),
    ("Kreditkartenabrechnung Oktober", site.CARD),
    ("Depotauszug zum 31.12.2025", site.SECURITIES),
    ("Wertpapierabrechnung Kauf", site.SECURITIES),
    ("Ertragsabrechnung Ausschüttung", site.SECURITIES),
    ("Sparplan Ausführung", site.SECURITIES),
    ("Jahressteuerbescheinigung 2025", site.TAX),
    ("Verlustbescheinigung", site.TAX),
    ("Steuerbescheinigung zum Depot", site.TAX),          # tax wins over depot
    ("Vertragsinformationen", site.CONTRACT),
    ("Preis- und Leistungsverzeichnis", site.CONTRACT),
    ("Mitteilung", site.MESSAGE),
    ("Wichtige Information zu deinem Konto", site.MESSAGE),
    ("", site.OTHER),
])
def test_a_document_sorts_into_its_postfach_filter(text, category):
    assert site.classify(text) == category


@pytest.mark.parametrize("title,summary", [
    ("Kontoauszug 10/2026", "Kontoauszug"),
    ("Kreditkartenabrechnung", "Kreditkartenabrechnung"),
    ("Depotauszug", "Depotauszug"),
    ("Wertpapierabrechnung Verkauf", "Wertpapierabrechnung Verkauf"),
    ("Jahressteuerbescheinigung 2025", "Jahressteuerbescheinigung"),
    ("Preis- und Leistungsverzeichnis", "Preis- und Leistungsverzeichnis"),
])
def test_known_dkb_titles_name_their_file(title, summary):
    rules = doc_types.load_rules()
    assert doc_types.classify_document(title, rules)[1] == summary


def test_dates_in_the_shapes_the_api_and_the_page_use():
    assert site.parse_date("2026-02-09") == "2026-02-09"
    assert site.parse_date("2026-02-09T10:15:00Z") == "2026-02-09"
    assert site.parse_date("09.02.2026") == "2026-02-09"
    assert site.parse_date("31.02.2026") == ""
    assert site.parse_date("gestern") == ""


def test_moving_money_trading_and_changing_things_are_never_safe():
    for name in ["Überweisung", "Ueberweisung", "Neue Überweisung", "Echtzeitüberweisung",
                 "Dauerauftrag anlegen", "Lastschrift zurückbuchen", "Geld senden",
                 "Kaufen", "Verkaufen", "Kauf", "Verkauf", "Order", "Sparplan anlegen", "Limit ändern",
                 "Karte sperren", "PIN ändern", "Konto kündigen", "Konto eröffnen",
                 "Freigeben", "Bestätigen", "Zustimmen", "Akzeptieren",
                 "Löschen", "Archivieren", "Als gelesen markieren", "Abmelden",
                 "Passwort ändern", "Adresse ändern", "Dokument löschen",
                 "Transfer", "Pay", "Buy", "Sell", "Log out", "Edit profile", "Mark as read"]:
        assert not site.is_safe_control(name), name


def test_reading_a_document_is_safe():
    for name in ["Herunterladen", "PDF herunterladen", "Download", "Postfach", "Dokumente",
                 "Kontoauszüge", "Kreditkartenabrechnung", "Depotauszug",
                 "Steuerbescheinigung", "Dokument öffnen", "Anzeigen", "View"]:
        assert site.is_safe_control(name), name


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit Card Statement")       # "edit" inside Credit
    assert site.is_safe_control("Kreditkartenabrechnung")       # not the word Kredit
    assert site.is_safe_control("Wertpapierkauf Abrechnung")    # not the word Kauf
    assert site.is_safe_control("Wertpapierabrechnung Kauf")    # a document's name
    assert site.is_safe_control("Wertpapierabrechnung Verkauf")
    assert site.is_safe_control("Sparplanabrechnung")
    assert not site.is_safe_control("Kredit beantragen")


def test_only_dkb_de_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://banking.dkb.de/postbox")
    assert site.is_safe_url("https://banking.dkb.de/api/documentstorage/documents")
    assert site.is_safe_url("https://www.dkb.de/")
    assert not site.is_safe_url("http://banking.dkb.de/")
    assert not site.is_safe_url("https://dkb.de.example/")
    assert not site.is_safe_url("https://notdkb.de/")
    assert not site.is_safe_url("https://dkb.com/")
    assert not site.is_safe_url("https://user:pw@banking.dkb.de/")


class _NoPassword:
    def count(self):
        return 0


class _Page:
    def __init__(self, url):
        self.url = url

    def locator(self, *_):
        return _NoPassword()


def test_the_documents_page_is_a_signed_in_banking_page():
    assert site.on_documents_page(_Page("https://banking.dkb.de/postbox"))
    assert site.on_documents_page(_Page("https://banking.dkb.de/finanzstatus"))
    assert not site.on_documents_page(_Page("https://banking.dkb.de/login"))
    assert not site.on_documents_page(_Page("https://www.dkb.de/"))
    assert not site.on_documents_page(_Page("https://example.com/postbox"))


DOC = {"id": "a1b2c3d4-0000-4000-8000-000000000001", "type": "document",
       "attributes": {"documentType": "bankAccountStatement", "contentType": "application/pdf",
                      "fileName": "Kontoauszug_012026.pdf", "creationDate": "2026-02-02",
                      "metadata": {"statementDate": "2026-01-31", "subject": "Kontoauszug 1/2026",
                                   "iban": "DE00 1203 0000 0000 0012 34"}}}


def test_a_row_carries_kind_account_date_and_what_the_download_needs():
    r = site._row(DOC, {})
    assert r["title"] == "Kontoauszug 1/2026" and r["date"] == "2026-01-31"
    assert r["account"] == "1234"                         # never the whole IBAN
    assert r["category"] == site.ACCOUNT
    assert r["item_id"] == DOC["id"] and r["client_id"] == "application/pdf"


def test_a_row_without_a_subject_takes_the_message_or_the_file_name():
    d = {"id": "x1", "attributes": {"documentType": "depotStatement", "contentType": "application/pdf",
                                    "fileName": "Depotauszug.pdf", "creationDate": "2026-01-05",
                                    "metadata": {"depotNumber": "509999999"}}}
    assert site._row(d, {})["title"] == "Depotauszug"
    r = site._row(d, {"x1": {"subject": "Depotauszug zum 31.12.2025"}})
    assert r["title"] == "Depotauszug zum 31.12.2025" and r["date"] == "2026-01-05"
    assert r["category"] == site.SECURITIES and r["account"] == "9999"


def test_a_row_that_is_not_a_pdf_is_left_out_and_one_with_no_date_says_so():
    """A row with no date used to be left out like one that is not a PDF,
    with nothing said. It comes back without a date, for the listing to
    count and Discover to say."""
    not_pdf = {"id": "x", "attributes": {"contentType": "text/csv", "creationDate": "2026-01-01"}}
    no_date = {"id": "y", "attributes": {"contentType": "application/pdf", "metadata": {}}}
    assert site._row(not_pdf, {}) is None
    assert site._row(no_date, {})["date"] == ""


def test_collect_keeps_wanted_kinds_and_years_in_scope_newest_first(monkeypatch):
    def doc(i, kind, date):
        return {"id": "id%d" % i, "attributes": {"documentType": kind, "contentType": "application/pdf",
                                                  "creationDate": date, "metadata": {}}}
    monkeypatch.setattr(site, "list_messages", lambda page: {})
    monkeypatch.setattr(site, "collect_archive", lambda page: [])
    monkeypatch.setattr(site, "list_documents", lambda page: [
        doc(1, "bankAccountStatement", "2025-03-01"), doc(2, "creditCardStatement", "2026-03-01"),
        doc(3, "depotStatement", "2026-04-01"), doc(4, "bankAccountStatement", "2024-01-01")])
    rows = site.collect_documents(None, keep=lambda y: y in ("2026", "2025"),
                                  config={"document_types": [site.ACCOUNT, site.SECURITIES]})
    assert [r["item_id"] for r in rows] == ["id3", "id1"]


def test_the_document_list_walks_the_offset_until_a_short_page(monkeypatch):
    asked = []

    def fake_get(page, url, **k):
        asked.append(url)
        n = len(asked)
        size = site.PAGE_LIMIT if n < 3 else 7
        return {"json": {"data": [{"id": "%d-%d" % (n, i)} for i in range(size)],
                         "links": {"self": "https://api.dkb.de/documentstorage/documents"}}}
    monkeypatch.setattr(site, "_get", fake_get)
    docs = site.list_documents(None)
    assert len(docs) == 2 * site.PAGE_LIMIT + 7
    assert asked == [site.API["documents"] + "?page%5Blimit%5D=200&page%5Boffset%5D=" + str(o)
                     + "&sort=-creationDate" for o in (0, 200, 400)]


def test_the_messages_are_keyed_by_their_document_and_follow_next_only_on_dkb(monkeypatch):
    second = site.BASE + "/api/documentstorage/messages?page%5Boffset%5D=1"
    pages = {
        site.API["messages"]: {"data": [{"id": "m1", "attributes": {"documentId": "d1", "documentType": "taxCertification"}}],
                               "links": {"next": "/api/documentstorage/messages?page%5Boffset%5D=1"}},
        second: {"data": [{"id": "d2", "attributes": {"documentType": "bankAccountStatement"}}]},
    }
    asked = []
    monkeypatch.setattr(site, "_get", lambda page, url, **k: (asked.append(url), {"json": pages[url]})[1])
    got = site.list_messages(None)
    assert {k: v["documentType"] for k, v in got.items()} == {"d1": "taxCertification", "d2": "bankAccountStatement"}
    assert len(asked) == 2
    # A next page anywhere else, or one asked for already, is not followed,
    # and the messages are not called read whole either.
    for nxt in ("https://evil.example/x", "https://banking.dkb.de/api/documentstorage/folders",
                "https://www.dkb.de/api/documentstorage/messages", "/api/documentstorage/messages"):
        pages[second] = dict(pages[second], links={"next": nxt})
        asked.clear()
        with pytest.raises(site.ListStopped):
            site.list_messages(None)
        assert len(asked) <= 3, nxt


@pytest.mark.parametrize("doc_type,category", [
    ("bankAccountStatement", site.ACCOUNT),
    ("creditCardStatement", site.CARD),
    ("dwpOrderStatement", site.SECURITIES),
    ("dwpRevenueStatement", site.SECURITIES),
    ("dwpDepotStatement", site.SECURITIES),
    ("dwpCorporateActionNotice", site.SECURITIES),
    ("exAnteCostInformation", site.SECURITIES),
    ("taxCertification", site.TAX),
    ("stageDocumentContract", site.CONTRACT),
    ("stageDocumentMessage", site.MESSAGE),
])
def test_the_postfach_document_types_file_by_name_not_by_words(doc_type, category):
    # A subject that says otherwise does not move it.
    assert site.classify(doc_type, "Mitteilung zu deinem Kontoauszug") == category


def test_a_row_takes_its_kind_from_the_message_and_its_day_in_berlin():
    d = {"id": "d9", "attributes": {"contentType": "application/pdf", "documentTypeId": "0000",
                                    "creationDate": "2026-03-31T22:15:00.123456Z", "fileName": "77.pdf",
                                    "metadata": {"subject": "Abrechnung  Kauf WKN A0B1C2 vom 31.03.2026",
                                                 "depotNumber": "509999999", "portfolio": "x"}}}
    r = site._row(d, {"d9": {"documentType": "dwpOrderStatement"}})
    assert r["category"] == site.SECURITIES and r["date"] == "2026-04-01"
    assert r["title"] == "Abrechnung Kauf WKN A0B1C2 vom 31.03.2026"   # spaces folded
    assert r["account"] == "9999"


@pytest.mark.parametrize("when,day", [
    ("2026-01-31T23:30:00.123456Z", "2026-02-01"),     # winter, UTC+1
    ("2026-01-31T22:59:59Z", "2026-01-31"),
    ("2026-07-31T22:30:00Z", "2026-08-01"),            # summer, UTC+2
    ("2026-07-31T21:59:59Z", "2026-07-31"),
    ("2026-10-24T22:30:00+00:00", "2026-10-25"),
    ("2026-10-25T23:30:00Z", "2026-10-26"),            # summer time just ended
    ("2026-01-31", "2026-01-31"),
    ("nie", ""),
])
def test_a_timestamp_is_read_as_a_day_in_berlin(when, day):
    assert site.local_date(when) == day


@pytest.mark.parametrize("subject,summary", [
    ("Kontoauszug 10/2026 vom 31.10.2026 zu Konto 1234567890", "Kontoauszug"),
    ("Abrechnung Kauf WKN A0B1C2 vom 02.10.2026 zu Depot 509999999", "Wertpapierabrechnung Kauf"),
    ("Abrechnung Verkauf WKN A0B1C2 vom 02.10.2026", "Wertpapierabrechnung Verkauf"),
    ("Depotauszug vom 31.12.2025 zu Depot 509999999", "Depotauszug"),
    ("Ertragsabrechnung WKN A0B1C2 vom 15.06.2026", "Ertragsabrechnung"),
    ("Kapitalmaßnahme WKN A0B1C2 vom 01.04.2026", "Kapitalmassnahme"),
    ("Kosteninformation zu Wertpapier EXAMPLE ETF", "Kosteninformation"),
    ("Mitteilung über steigende Sollzinssätze", "Mitteilung"),
])
def test_recorded_subjects_name_their_file(subject, summary):
    assert doc_types.classify_document(subject, doc_types.load_rules())[1] == summary


def test_every_call_sends_the_page_s_own_headers():
    seen = {}

    class P(_Page):
        def evaluate(self, js, arg):
            seen.update(arg)
            return {"status": 200, "ct": "application/vnd.api+json", "json": {"data": []}}
    site._get(P("https://banking.dkb.de/postbox"), site.API["messages"])
    assert seen["headers"] == {"application-name": "web-banking"}
    assert "__Host-xsrf" in site._GET_JS and "x-xsrf-token" in site._GET_JS


def test_the_pdf_comes_back_from_base64(monkeypatch):
    pdf = b"%PDF-1.4 fake"
    seen = {}

    def fake_get(page, url, accept=""):
        seen.update(url=url, accept=accept)
        return {"status": 200, "ct": "application/pdf", "b64": base64.b64encode(pdf).decode()}
    monkeypatch.setattr(site, "_get", fake_get)
    assert site.fetch_pdf(None, "a1b2-c3", "application/pdf") == pdf
    assert seen == {"url": site.API["document"] + "a1b2-c3", "accept": "application/pdf"}


def test_an_id_that_could_change_the_address_is_refused():
    for bad in ["../messages/1", "a/b", "x?y=1", "", "a" * 200]:
        with pytest.raises(ValueError):
            site.fetch_pdf(None, bad)


def _by_place(rows):
    """Numbers as a listing with no stored ids gives them, each sure."""
    seen = {}
    out = []
    for r in rows:
        what = (r["title"], r["date"], r["account"])
        out.append((seen.get(what, 0), True))
        seen[what] = seen.get(what, 0) + 1
    return out


def test_download_resolves_the_id_fresh_and_refuses_a_non_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(site, "resolve_item", lambda *a, **k: {"item_id": "fresh", "client_id": "application/pdf"})
    seen = {}
    monkeypatch.setattr(site, "fetch_pdf", lambda page, item_id, ct: (seen.update(id=item_id), b"%PDF-1.4 ok")[1])
    out = tmp_path / "x.pdf"
    assert site.download_document(None, "Kontoauszug 1/2026", "2026-01-31", out,
                                  item_hint="stale", account="1234", category=site.ACCOUNT,
                                  number_rows=_by_place) == "fresh"
    assert seen == {"id": "fresh"} and out.read_bytes().startswith(b"%PDF")
    monkeypatch.setattr(site, "fetch_pdf", lambda *a: b"<html>Anmelden</html>")
    assert not site.download_document(None, "Kontoauszug", "2026-01-31", tmp_path / "y.pdf", account="1234",
                                      category=site.ACCOUNT, number_rows=_by_place)
    assert not (tmp_path / "y.pdf").exists()


def test_the_in_page_get_only_ever_goes_to_a_dkb_host_and_only_reads():
    assert "host.endsWith('.dkb.de')" in site._GET_JS
    assert "method: 'GET'" in site._GET_JS
    for verb in ("POST", "PATCH", "PUT", "DELETE"):
        assert verb not in site._GET_JS
    with pytest.raises(ValueError):
        site._get(_Page("https://banking.dkb.de/postbox"), "https://evil.example/x")


def test_a_sign_in_answer_stops_the_run():
    class P(_Page):
        def evaluate(self, js, arg):
            return {"status": 401, "ct": "application/json", "json": None}
    with pytest.raises(site.SessionExpired):
        site._get(P("https://banking.dkb.de/postbox"), site.API["documents"])
    with pytest.raises(site.SessionExpired):
        site._get(_Page("https://banking.dkb.de/login"), site.API["documents"])


def test_the_survey_follows_only_exact_document_words():
    for name in ["Postfach", "Dokumente", "Kontoauszüge", "Steuerbescheinigungen"]:
        assert site.SURVEY_LINK_RE.match(name), name
    assert not site.SURVEY_LINK_RE.match("Überweisung")
    assert not site.SURVEY_LINK_RE.match("Depot")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("Depot 509999999 anzeigen") == "Depot ######### anzeigen"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"accounts": [{"number": "509999999", "balance": 12.5}]})
    assert shape == {"accounts": ["1 item(s)", {"number": "string", "balance": "number"}]}


def test_a_listed_document_without_a_file_says_so():
    class P(_Page):
        def evaluate(self, js, arg):
            return {"status": 404, "ct": "application/vnd.api+json",
                    "json": {"errors": [{"status": "404", "code": "UnknownDocument"}]}}
    with pytest.raises(site.NoFile, match="holds no file"):
        site.fetch_pdf(P("https://banking.dkb.de/postbox"), "a1b2-c3")


def test_two_orders_of_one_day_that_differ_late_in_the_subject_keep_two_keys():
    import dkb_docs
    head = "Abrechnung Kauf WKN A0B1C2 vom 05.11.2026 zu Depot 509999999 Ordernr. "
    one = dkb_docs.Document(title=head + "111111", category=site.SECURITIES, date="2026-11-06")
    two = dkb_docs.Document(title=head + "222222", category=site.SECURITIES, date="2026-11-06")
    assert len(head) > 60 and one.key != two.key


FOLDERS = {"data": [{"id": "1", "attributes": {"name": "Mitteilungen"}},
                    {"id": "2", "attributes": {"name": "Kontoauszüge"}},
                    {"id": "9", "attributes": {"name": "Archiv", "containsSubfolders": True}}]}


def _folder(name, files):
    return {"data": {"id": "x", "type": "legacyMailboxFolderContent",
                     "attributes": {"name": name, "subfolders": [], "files": files}}}


def test_the_archive_files_by_folder_and_archiv_by_subject(monkeypatch):
    archiv = [{"id": "a%d" % i, "subject": s, "fileName": "%d.pdf" % i, "creationDate": "2019-05-0%dT10:00Z" % (i + 1)}
              for i, s in enumerate(["Kauf - WKN A0B1C2 - EXAMPLE ETF", "Kreditkartenabrechnung 1234********5678 per 30.04.2019",
                                     "Kontoauszug Nr. 004_2019", "Vollmachtsdokument"])]
    answers = {
        site.API["folders"]: FOLDERS,
        site.API["folders"] + "/1?page%5Blimit%5D=200&page%5Boffset%5D=0": _folder("Mitteilungen", [
            {"id": "m1", "subject": "Wichtig", "fileName": "m.pdf", "creationDate": "2024-12-19T09:00Z"}]),
        site.API["folders"] + "/2?page%5Blimit%5D=200&page%5Boffset%5D=0": _folder("Kontoauszüge", [
            {"id": "k1", "subject": "Kontoauszug 12/2023", "fileName": "k.pdf", "creationDate": "2023-12-05T08:00Z",
             "additionalInformation": "DE00120300000000004321"}]),
        site.API["folders"] + "/9?page%5Blimit%5D=200&page%5Boffset%5D=0": _folder("Archiv", archiv),
    }
    monkeypatch.setattr(site, "_get", lambda page, url, **k: {"json": answers[url]})
    rows = {r["item_id"]: r for r in site.collect_archive(None)}
    assert rows["m1"]["category"] == site.MESSAGE
    assert rows["k1"]["category"] == site.ACCOUNT and rows["k1"]["account"] == "4321"
    assert rows["k1"]["client_id"] == site.LEGACY and rows["k1"]["date"] == "2023-12-05"
    assert [rows["a%d" % i]["category"] for i in range(4)] == [site.SECURITIES, site.CARD, site.ACCOUNT, site.OTHER]
    assert rows["a1"]["account"] == "5678"                  # the masked card's last four


def test_an_archive_folder_is_walked_until_a_short_page(monkeypatch):
    asked = []

    def fake_get(page, url, **k):
        asked.append(url)
        size = site.PAGE_LIMIT if len(asked) < 4 else 3
        return {"json": _folder("Archiv", [{"id": "f%d-%d" % (len(asked), i)} for i in range(size)])}
    monkeypatch.setattr(site, "_get", fake_get)
    name, files, subs = site.read_folder(None, "9")
    assert (name, len(files), subs) == ("Archiv", 3 * site.PAGE_LIMIT + 3, [])
    assert asked[-1].endswith("/9?page%5Blimit%5D=200&page%5Boffset%5D=600")


def test_a_file_in_the_postfach_and_the_archive_is_taken_once_from_the_postfach(monkeypatch):
    monkeypatch.setattr(site, "list_messages", lambda page: {})
    monkeypatch.setattr(site, "list_documents", lambda page: [DOC])
    same = {"title": "Kontoauszug 1/2026", "date": "2026-01-31", "account": "1234", "category": site.ACCOUNT,
            "item_id": "old", "client_id": site.LEGACY}
    other = dict(same, title="Kontoauszug 12/2025", date="2025-12-31", item_id="older")
    monkeypatch.setattr(site, "collect_archive", lambda page: [same, other])
    rows = site.collect_documents(None)
    assert [(r["item_id"], r["client_id"]) for r in rows] == [(DOC["id"], "application/pdf"), ("older", site.LEGACY)]


def test_an_archive_file_comes_back_from_base64_inside_json(monkeypatch):
    pdf = b"%PDF-1.4 archived"
    seen = {}

    def fake_get(page, url, **k):
        seen["url"] = url
        return {"json": {"data": {"id": "a1", "type": "legacyMailboxFile",
                                  "attributes": {"content": base64.b64encode(pdf).decode(), "contentType": "application/pdf"}}}}
    monkeypatch.setattr(site, "_get", fake_get)
    assert site.fetch_pdf(None, "a1b2", site.LEGACY) == pdf
    assert seen["url"] == site.API["legacy"] + "a1b2"


def test_one_listing_serves_the_downloads_that_follow(monkeypatch):
    calls = []
    monkeypatch.setattr(site, "list_messages", lambda page: {})
    monkeypatch.setattr(site, "list_documents", lambda page: (calls.append(1), [DOC])[1])
    monkeypatch.setattr(site, "collect_archive", lambda page: [])
    site.collect_documents(None)
    for _ in range(3):
        assert site.resolve_item(None, "Kontoauszug 1/2026", "2026-01-31", "1234",
                                 item_id=DOC["id"], category=site.ACCOUNT,
                                 number_rows=_by_place)["item_id"] == DOC["id"]
    assert len(calls) == 1


def test_a_full_page_given_again_or_a_list_past_its_last_page_stops_the_listing(monkeypatch):
    """A list asked for by offset that answers every offset with the same
    page would be read fifty times over and called whole. A list that is
    still full at the last page asked for was cut there."""
    same = [{"id": "d%d" % i} for i in range(site.PAGE_LIMIT)]
    monkeypatch.setattr(site, "_get", lambda page, url, **k: {"json": {"data": same}})
    with pytest.raises(site.ListStopped, match="given already"):
        site.list_documents(None)
    count = iter(range(10 ** 6))
    monkeypatch.setattr(site, "_get", lambda page, url, **k: {"json": {"data": [
        {"id": "d%d" % next(count)} for _ in range(site.PAGE_LIMIT)]}})
    with pytest.raises(site.ListStopped, match="ran past"):
        site.list_documents(None)


def test_an_archive_folder_whose_id_cannot_be_read_stops_the_listing(monkeypatch):
    monkeypatch.setattr(site, "_get", lambda page, url, **k: {"json": {"data": [
        {"id": "1", "attributes": {"name": "Mitteilungen"}}, {"id": "../x", "attributes": {"name": "Archiv"}}]}})
    with pytest.raises(site.ListStopped):
        site.list_folders(None)


def test_an_archive_timestamp_without_seconds_is_a_day_in_berlin():
    assert site.local_date("2019-12-31T23:30Z") == "2020-01-01"
    assert site.local_date("2019-07-01T21:59Z") == "2019-07-01"


@pytest.mark.parametrize("subject,summary", [
    ("Kauf - WKN A0B1C2 - EXAMPLE ETF", "Wertpapierabrechnung Kauf"),
    ("Verkauf - WKN A0B1C2 - EXAMPLE ETF", "Wertpapierabrechnung Verkauf"),
    ("Kontoauszug Nr. 004_2019", "Kontoauszug"),
    ("Kreditkartenabrechnung 1234********5678 per 30.04.2019", "Kreditkartenabrechnung"),
    ("Fondssparpläne vom 01.04.2019", "Sparplanabrechnung"),
    ("Depotauszug jährlich vom 31.12.2019", "Depotauszug"),
    ("Vollmachtsdokument", "Vollmacht"),
])
def test_archive_subjects_name_their_file(subject, summary):
    assert doc_types.classify_document(subject, doc_types.load_rules())[1] == summary


def test_a_server_fault_is_not_taken_for_a_signed_out_session():
    class P(_Page):
        def evaluate(self, js, arg):
            return {"status": 500, "ct": "text/html", "b64": ""}
    with pytest.raises(RuntimeError, match="fault on DKB's side") as e:
        site._get(P("https://banking.dkb.de/postbox"), site.API["legacy"] + "a1")
    assert not isinstance(e.value, site.SessionExpired)


def test_a_signed_out_answer_to_the_messages_stops_the_listing(monkeypatch):
    def gone(page, url, **k):
        raise site.SessionExpired("DKB answered 401")
    monkeypatch.setattr(site, "_get", gone)
    with pytest.raises(site.SessionExpired):
        site.list_messages(None)


def test_two_accounts_documents_of_one_title_and_day_keep_two_keys():
    import dkb_docs
    one = dkb_docs.Document(title="Kontoauszug 1/2026", category=site.ACCOUNT, date="2026-01-31", account="1234")
    two = dkb_docs.Document(title="Kontoauszug 1/2026", category=site.ACCOUNT, date="2026-01-31", account="5678")
    assert one.key != two.key


def test_the_postfach_page_is_postbox():
    assert site.URLS["documents"] == "https://banking.dkb.de/postbox"


def test_the_inactivity_page_is_signed_out_not_a_challenge():
    class P(_Page):
        def title(self):
            return "DKB Banking"

        def locator(self, sel):
            class L:
                def count(self):
                    return 1 if "password" in sel else 0

                def inner_text(self, timeout=0):
                    return "Automatische Abmeldung. Anmeldename Passwort Friendly Captcha Anmelden"
            return L()
    page = P("https://banking.dkb.de/timeout")
    assert site.looks_signed_out(page)
    assert site.detect_security_challenge(page) is None


def test_nothing_keeps_the_session_alive_behind_the_bank_s_back():
    import inspect
    src = inspect.getsource(site)
    for name in ("keep_alive", "keep_session", "configure", "_REFRESH_JS"):
        assert not hasattr(site, name), name
    for word in ("'/api/refresh'", "method: 'POST'", "dispatchEvent", "mousemove"):
        assert word not in src, word


def _page_saying(url, text):
    class P(_Page):
        def title(self):
            return "DKB Banking"

        def locator(self, sel):
            class L:
                def count(self):
                    return 0

                def inner_text(self, timeout=0):
                    return text
            return L()
    return P(url)


def test_a_page_that_names_the_dkb_app_is_not_a_challenge():
    page = _page_saying("https://banking.dkb.de/settings/cards",
                        "Karten. Deine Karte in der DKB-App verwalten. Apple Pay mit der DKB-App.")
    assert site.detect_security_challenge(page) is None


def test_a_prompt_to_confirm_in_the_app_is_one():
    page = _page_saying("https://banking.dkb.de/", "Bitte bestätige deine Anmeldung in der DKB-App.")
    assert site.detect_security_challenge(page)


def test_a_word_in_the_account_field_is_not_an_account():
    assert site.account_label({"portfolio": "DKB"}) == ""
    assert site.account_label({"iban": "DE00 1203 0000 0000 0012 34"}) == "1234"
