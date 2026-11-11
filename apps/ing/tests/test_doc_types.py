"""ING's categories, file names, dates, and the guards around its pages.

The examples are invented. ING's own Postbox words are not checked on an
account yet, so these hold what the app does with them, not what ING shows.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import ing_site as site
from paperpull_core import doc_types


def test_the_planned_categories_have_folders_and_routes():
    assert storage.SPEC.provider == "ING"
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


def test_unread_rows_and_the_archive_are_read_unless_set_otherwise():
    assert storage.SPEC.config_defaults["include_unread"] is True
    assert storage.SPEC.config_defaults["read_archive"] is True


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
    ("Erträgnisaufstellung 2025", site.TAX),
    ("Ertraegnisaufstellung 2025", site.TAX),
    ("Steuerbescheinigung zum Depot", site.TAX),          # tax wins over depot
    ("Vertragsinformationen", site.CONTRACT),
    ("Preis- und Leistungsverzeichnis", site.CONTRACT),
    ("Mitteilung", site.MESSAGE),
    ("Wichtige Information zu deinem Konto", site.MESSAGE),
    ("", site.OTHER),
])
def test_a_document_sorts_into_its_postbox_filter(text, category):
    assert site.classify(text) == category


@pytest.mark.parametrize("kind,subject,category", [
    # The row's document type decides, whatever its subject says.
    ("Kontoauszug", "Steuerbescheinigung", site.ACCOUNT),
    ("Depotauszug", "Mitteilung zu deinem Kontoauszug", site.SECURITIES),
    ("Steuerbescheinigung", "zum Depot", site.TAX),
    # A type that says only that it is a message, or nothing known, leaves
    # it to the type and the subject read together.
    ("Mitteilung", "Kontoauszug 1/2026", site.ACCOUNT),
    ("Information", "Jahressteuerbescheinigung 2025", site.TAX),
    ("Mitteilung", "Wichtige Information", site.MESSAGE),
    ("", "Depotauszug zum 31.12.2025", site.SECURITIES),
    ("Dokument", "Vollmacht", site.OTHER),
])
def test_a_rows_document_type_decides_its_kind_before_its_subject(kind, subject, category):
    assert site.classify(kind, subject) == category


@pytest.mark.parametrize("title,summary", [
    ("Kontoauszug 10/2026", "Kontoauszug"),
    ("Kreditkartenabrechnung", "Kreditkartenabrechnung"),
    ("Depotauszug", "Depotauszug"),
    ("Wertpapierabrechnung Verkauf", "Wertpapierabrechnung Verkauf"),
    ("Jahressteuerbescheinigung 2025", "Jahressteuerbescheinigung"),
    ("Preis- und Leistungsverzeichnis", "Preis- und Leistungsverzeichnis"),
])
def test_known_ing_titles_name_their_file(title, summary):
    rules = doc_types.load_rules()
    assert doc_types.classify_document(title, rules)[1] == summary


@pytest.mark.parametrize("subject,summary", [
    ("Kontoauszug 10/2026 vom 31.10.2026 zu Konto 1234567890", "Kontoauszug"),
    ("Abrechnung Kauf WKN A0B1C2 vom 02.10.2026 zu Depot 509999999", "Wertpapierabrechnung Kauf"),
    ("Abrechnung Verkauf WKN A0B1C2 vom 02.10.2026", "Wertpapierabrechnung Verkauf"),
    ("Depotauszug vom 31.12.2025 zu Depot 509999999", "Depotauszug"),
    ("Ertragsabrechnung WKN A0B1C2 vom 15.06.2026", "Ertragsabrechnung"),
    ("Kapitalmaßnahme WKN A0B1C2 vom 01.04.2026", "Kapitalmassnahme"),
    ("Kosteninformation zu Wertpapier EXAMPLE ETF", "Kosteninformation"),
    ("Mitteilung über steigende Sollzinssätze", "Mitteilung"),
    ("Kreditkartenabrechnung 1234********5678 per 30.04.2019", "Kreditkartenabrechnung"),
    ("Depotauszug jährlich vom 31.12.2019", "Depotauszug"),
    ("Vollmachtsdokument", "Vollmacht"),
])
def test_example_subjects_name_their_file(subject, summary):
    assert doc_types.classify_document(subject, doc_types.load_rules())[1] == summary


def test_dates_in_the_shapes_the_page_uses():
    assert site.parse_date("09.02.2026") == "2026-02-09"
    assert site.parse_date("9.2.2026") == "2026-02-09"
    assert site.parse_date("2026-02-09") == "2026-02-09"
    assert site.parse_date("31.02.2026") == ""
    assert site.parse_date("29.02.1900") == ""
    # A day named in words is not a date this app keys a document by.
    assert site.parse_date("gestern") == ""
    assert site.parse_date("Heute") == ""


def test_a_statement_of_no_known_kind_is_filed_as_one_by_its_title():
    assert site.filed_category({"category": site.OTHER, "title": "Kontoauszug 1/2026"}) == site.ACCOUNT
    assert site.filed_category({"category": site.OTHER, "title": "Vollmacht"}) == site.OTHER
    assert site.filed_category({"category": site.TAX, "title": "Kontoauszug"}) == site.TAX


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
    for name in ["Herunterladen", "PDF herunterladen", "Download", "Postfach", "Postbox", "Dokumente",
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


def test_only_the_banking_host_is_allowed():
    assert site.is_safe_url("https://banking.ing.de/app/postbox/postbox")
    assert site.is_safe_url("https://banking.ing.de/app/obligo")
    # ING's sign-in and public pages are not a signed-in banking page.
    assert not site.is_safe_url("https://www.ing.de/")
    assert not site.is_safe_url("https://access.ing.de/delogin/w/login")
    assert not site.is_safe_url("https://ing.de/")
    assert not site.is_safe_url("http://banking.ing.de/")
    assert not site.is_safe_url("https://banking.ing.de.example/")
    assert not site.is_safe_url("https://noting.de/")
    assert not site.is_safe_url("https://ing.com/")
    assert not site.is_safe_url("https://banking.ing.de@evil.example/")


class _NoPassword:
    def count(self):
        return 0


class _Page:
    def __init__(self, url):
        self.url = url

    def locator(self, *_):
        return _NoPassword()


def test_the_documents_page_is_a_signed_in_banking_page():
    assert site.on_documents_page(_Page("https://banking.ing.de/app/postbox/postbox"))
    assert site.on_documents_page(_Page("https://banking.ing.de/app/obligo"))
    assert not site.on_documents_page(_Page("https://banking.ing.de/login"))
    assert not site.on_documents_page(_Page("https://www.ing.de/"))
    assert not site.on_documents_page(_Page("https://example.com/postbox"))
    assert not site.on_documents_page(_Page("https://banking.ing.de.example.ing.de/postbox"))


@pytest.mark.parametrize("url", [
    "https://apps.ing.de/",
    "https://apps.ing.de/dare/",
    "https://access.ing.de/delogin/w/login",
    "https://www.ing.de/",
    "https://banking.ing.de/app/login",
    "https://banking.ing.de/timeout",
    "about:blank",
])
def test_an_ing_login_or_public_page_is_never_treated_as_signed_in(url):
    assert site.looks_signed_out(_Page(url))


def test_a_page_with_a_password_field_is_signed_out():
    class P(_Page):
        def locator(self, sel):
            class L:
                def count(self):
                    return 1 if "password" in sel else 0
            return L()
    assert site.looks_signed_out(P("https://banking.ing.de/app/postbox/postbox"))


def test_sign_in_uses_the_official_ing_entry_and_the_postbox_its_own_address():
    assert site.URLS["login"] == "https://banking.ing.de/app/obligo"
    assert site.URLS["documents"] == "https://banking.ing.de/app/postbox/postbox"
    assert site.URLS["archive"] == "https://banking.ing.de/app/postbox/postbox_archiv"
    for url in site.URLS.values():
        assert site.is_safe_url(url), url


def test_the_survey_follows_only_exact_document_words():
    for name in ["Postfach", "Postbox", "Dokumente", "Kontoauszüge", "Steuerbescheinigungen"]:
        assert site.SURVEY_LINK_RE.match(name), name
    assert not site.SURVEY_LINK_RE.match("Überweisung")
    assert not site.SURVEY_LINK_RE.match("Depot")


def test_account_numbers_are_masked_in_the_survey():
    assert site.redact("Depot 509999999 anzeigen") == "Depot ######### anzeigen"


def test_json_bodies_are_recorded_as_shape_not_values():
    shape = site._shape({"accounts": [{"number": "509999999", "balance": 12.5}]})
    assert shape == {"accounts": ["1 item(s)", {"number": "string", "balance": "number"}]}


def test_two_orders_of_one_day_that_differ_late_in_the_subject_keep_two_keys():
    import ing_docs
    head = "Abrechnung Kauf WKN A0B1C2 vom 05.11.2026 zu Depot 509999999 Ordernr. "
    one = ing_docs.Document(title=head + "111111", category=site.SECURITIES, date="2026-11-06")
    two = ing_docs.Document(title=head + "222222", category=site.SECURITIES, date="2026-11-06")
    assert len(head) > 60 and one.key != two.key


def test_two_accounts_documents_of_one_title_and_day_keep_two_keys():
    import ing_docs
    one = ing_docs.Document(title="Kontoauszug 1/2026", category=site.ACCOUNT, date="2026-01-31", account="1234")
    two = ing_docs.Document(title="Kontoauszug 1/2026", category=site.ACCOUNT, date="2026-01-31", account="5678")
    assert one.key != two.key


def test_the_inactivity_page_is_signed_out_not_a_challenge():
    class P(_Page):
        def title(self):
            return "ING Banking"

        def locator(self, sel):
            class L:
                def count(self):
                    return 1 if "password" in sel else 0

                def inner_text(self, timeout=0):
                    return "Automatische Abmeldung. Anmeldename Passwort Friendly Captcha Anmelden"
            return L()
    page = P("https://banking.ing.de/timeout")
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
            return "ING Banking"

        def locator(self, sel):
            class L:
                def count(self):
                    return 0

                def inner_text(self, timeout=0):
                    return text
            return L()
    return P(url)


def test_a_page_that_names_the_ing_app_is_not_a_challenge():
    page = _page_saying("https://banking.ing.de/app/settings",
                        "Karten. Deine Karte in der ING-App verwalten. Apple Pay mit der ING-App.")
    assert site.detect_security_challenge(page) is None


def test_a_prompt_to_confirm_in_the_app_is_one():
    page = _page_saying("https://banking.ing.de/app/obligo",
                        "Bitte bestätige deine Anmeldung in der ING-App.")
    assert site.detect_security_challenge(page)
