"""Renault Bank direkt's guard, host allowlist and document kinds.
Invented values only, never a real account's."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import renaultbank_docs as app_mod
import renaultbank_site as site
from paperpull_core import doc_types

APP = Path(__file__).resolve().parents[1]


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Renault Bank direkt"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Kontoauszuege", "Kreditkartenabrechnungen", "Wertpapierdokumente",
         "Steuerbescheinigungen", "Vertragsinformationen", "Mitteilungen", "Sonstige Dokumente"]
    assert storage.SPEC.routes[storage.STATEMENT] == "statements"
    assert storage.SPEC.routes[storage.SECURITIES] == "securities_documents"
    assert storage.SPEC.routes[storage.TAX] == "tax_documents"


def test_an_install_starts_with_every_kind_the_real_build_may_file():
    """An install keeps the document_types it was set up with, and a kind
    added to the template later reaches new installs only, so a person who
    set up this app before it would never get one. Every kind is in from the
    first build, the template and the defaults alike."""
    every = storage.ALL_CATEGORIES + [storage.OTHER]
    template = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    assert template["document_types"] == every
    assert storage.SPEC.config_defaults["document_types"] == every


@pytest.mark.parametrize("title,category,summary", [
    ("Kontoauszug 1/2026", "Statement", "Kontoauszug"),
    ("Finanzreport Nr. 3 per 30.09.2026", "Statement", "Finanzreport"),
    ("Kreditkartenabrechnung 9/2026", "Statement", "Kreditkartenabrechnung"),
    ("Depotauszug vom 30.09.2026", "Statement", "Depotauszug"),
    ("Abrechnung Kauf WKN A0B1C2", "Statement", "Wertpapierabrechnung Kauf"),
    ("Abrechnung Sparplan WKN A0B1C2", "Statement", "Wertpapierabrechnung Kauf"),
    ("Kosteninformation zu Wertpapier", "Statement", "Kosteninformation"),
    ("Jahressteuerbescheinigung 2025", "Tax Document", "Jahressteuerbescheinigung"),
    ("Verlustbescheinigung 2025", "Tax Document", "Verlustbescheinigung"),
])
def test_bank_and_broker_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


@pytest.mark.parametrize("name", [
    # Trading
    "Kaufen", "Verkaufen", "Order", "Order aufgeben", "Limit setzen",
    "Stop-Loss", "Kursalarm", "Preisalarm", "Sparplan anlegen", "Sparplan erstellen",
    "Sparplan ändern", "Sparplan pausieren", "Sparplan aussetzen", "Sparplan löschen",
    "Zeichnen", "Handeln", "Buy", "Sell", "Trade", "Savings plan", "Place order",
    # Money moving
    "Überweisung", "Ueberweisung", "Neue Überweisung", "Echtzeitüberweisung",
    "Dauerauftrag anlegen", "Daueraufträge", "Lastschrift zurückbuchen", "Umbuchung",
    "Vorlage speichern", "Empfänger verwalten", "Depotübertrag", "Einzahlen", "Auszahlen",
    "Transfer", "Pay", "Payment", "Standing order", "Direct debit", "Deposit", "Withdraw",
    # Credit and cards
    "Ratenkredit", "Wertpapierkredit", "Kredit beantragen", "Kreditrahmen erhöhen",
    "Dispo", "Verfügungsrahmen", "Karte sperren", "Karte entsperren", "PIN ändern",
    "Upgrade", "Open a new card",
    # Accounts and the person's data
    "Konto eröffnen", "Tagesgeld eröffnen", "Depot anlegen", "Konto kündigen",
    "Freistellungsauftrag ändern", "Kontowecker", "Benachrichtigungen", "Einstellungen",
    "Persönliche Daten", "E-Mail ändern", "Passwort ändern", "Gerät verwalten", "Adresse",
    "Als gelesen markieren", "Löschen", "Archivieren", "Abmelden", "Open a new account",
    "Settings", "Mark as read", "Log out", "Logout",
    # What the review of the first build found the guard let through
    "Verlustbescheinigung anfordern", "Kinderdepot öffnen", "Unterkonto öffnen",
    "Girokonto öffnen", "Open a child account", "Open Junior Depot", "Open savings account",
    "Open an investment account", "Open credit line", "Open overdraft", "Open position",
    "Kontoauszüge per Post bestellen", "Switch to paper statements",
    "Duplikat Kontoauszug anfordern", "Request a statement", "Dokumente unterschreiben",
    "Sign document", "Upload document", "Dokument hochladen", "Steuer-ID hinterlegen",
    "Steuerdaten aktualisieren", "Postbox freischalten", "Kopie anfordern", "Lock card",
    "Close account",
    "PDF herunterladen | Überweisung",
])
def test_trading_moving_money_and_changing_the_account_are_never_safe(name):
    assert not site.is_safe_control(name), name
    # Beside a document's own word, so only the blocklist can refuse it.
    assert not site.is_safe_control("Dokumente " + name), name


@pytest.mark.parametrize("name", [
    "Postbox", "Postfach", "Mailbox", "Dokumente", "Documents", "Herunterladen", "PDF herunterladen",
    "Download PDF", "Kontoauszug", "Depotauszug", "Wertpapierabrechnung Kauf",
    "Abrechnung Sparplan", "Kosteninformation", "Jahressteuerbescheinigung",
    "Steuerbescheinigung 2025", "Verlustbescheinigung", "Erträgnisaufstellung",
    "Dokument öffnen", "Anzeigen", "Mehr anzeigen", "Archiv", "View statement",
    "Open", "Öffnen", "View", "Anzeigen", "PDF anzeigen", "Dokument öffnen", "Open statement", "Open document",
    "Depotauszug öffnen", "Kontoauszug öffnen", "Wertpapierabrechnung",
    "Wertpapierdokumente", "Open card statement",
    "Kreditkartenabrechnung", "Finanzreport",
])
def test_reading_a_document_is_safe(name):
    assert site.is_safe_control(name), name


@pytest.mark.parametrize("name", ["Kauf", "Verkauf", " Kauf ", "kauf"])
def test_a_label_that_is_nothing_but_a_trade_is_refused(name):
    """"Kauf" is in the name of every Wertpapierabrechnung, so only a label
    that says nothing else is refused for it."""
    assert not site.is_safe_control(name)
    assert site.FORBIDDEN_CONTROL_RE.search(name)


@pytest.mark.parametrize("name", ["Übersicht", "Watchlist", "Märkte", "Overview", "Markets",
                                  "Hilfe", "Depot 1111", "Open Watchlist", "Watchlist öffnen",
                                  "Open trading view", "Depot anzeigen", "View portfolio"])
def test_a_control_that_names_no_document_is_refused(name):
    """The allowlist, which refuses whatever names no document, however
    harmless it reads."""
    assert not site.is_safe_control(name)


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Kreditkartenabrechnung")   # "kredit" not alone
    assert site.is_safe_control("Wertpapierabrechnung Kauf")  # "Kauf" not alone
    assert not site.is_safe_control("Kauf")


def test_only_the_banking_host_is_allowed():
    assert site.is_safe_url("https://banking.renault-bank-direkt.de/home")
    assert site.is_safe_url("https://banking.renault-bank-direkt.de/services_auth/auth-frontend/")
    assert not site.is_safe_url("http://banking.renault-bank-direkt.de/")             # not https
    assert not site.is_safe_url("https://banking.renault-bank-direkt.de.example/")
    assert not site.is_safe_url("https://notbanking.renault-bank-direkt.de/")
    assert not site.is_safe_url("https://banking.renault-bank-direkt.de@evil.test/")
    assert not site.is_safe_url("https://banking.renault-bank-direkt.de:8443/")
    assert not site.is_safe_url("https://www.renault-bank-direkt.de/")
    assert not site.is_safe_url("https://other.banking.renault-bank-direkt.de/")


def test_the_sign_in_address_is_the_one_the_request_names():
    assert site.URLS["login"] == "https://banking.renault-bank-direkt.de/services_cloud/portal/"
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["home"])


@pytest.mark.parametrize("category", ["Other Document", "Tax Document", "Message"])
@pytest.mark.parametrize("title", ["Kontoauszug 3/2031", "Monthly statement", "Information"])
def test_a_row_is_filed_as_its_record_is(category, title):
    """_record_statement_doc records an Other Document whose title says
    Kontoauszug or statement as a Statement. filed_category, which Discover
    numbers rows by and resolve_item finds a row by, has to read the row the
    same way, or a download never finds the row its record names and the
    document fails on every run. classify reads such a title as a Statement
    already, so only a row that arrives as an Other Document shows it."""
    row = {"title": title, "date": "2031-04-02", "account": "", "category": category,
           "item_id": "document:A1", "client_id": "", "href": ""}
    recorded = {}
    every = storage.ALL_CATEGORIES + [storage.OTHER]
    app = SimpleNamespace(
        rules=doc_types.load_rules(), stats={"skipped_out_of_scope": 0},
        config={"document_types": every}, args=SimpleNamespace(start_date=None),
        discovery=SimpleNamespace(get=lambda key: None,
                                  update=lambda key, rec, save=False: recorded.update({key: rec})))
    assert app_mod.App._record_statement_doc(app, row) == 1
    (key, rec), = recorded.items()
    assert rec["category"] == site.filed_category(row)
    assert key == app_mod.listed_key(row)


def test_the_document_key_tells_two_accounts_apart():
    one = app_mod.Document(category="Statement", date="2026-03-31", title="Finanzreport",
                           account="Girokonto 1111")
    two = app_mod.Document(category="Statement", date="2026-03-31", title="Finanzreport",
                           account="Tagesgeld 2222")
    assert one.key != two.key
