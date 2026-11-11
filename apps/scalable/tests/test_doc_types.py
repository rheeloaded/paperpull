"""Scalable Capital's guard, host allowlist and document kinds.
Invented values only, never a real account's."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import scalable_docs as app_mod
import scalable_site as site
from paperpull_core import doc_types

APP = Path(__file__).resolve().parents[1]


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Scalable Capital"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Kontoauszuege", "Kreditkartenabrechnungen", "Wertpapierdokumente",
         "Steuerbescheinigungen", "Vertragsinformationen", "Mitteilungen", "Sonstige Dokumente"]
    assert storage.SPEC.routes[storage.STATEMENT] == "statements"
    assert storage.SPEC.routes[storage.SECURITIES] == "securities_documents"
    assert storage.SPEC.routes[storage.TAX] == "tax_documents"


def test_an_install_starts_with_every_kind_the_real_build_may_file():
    """An install keeps the document_types it was set up with, and a kind
    added to the template later reaches new installs only, so a tester who
    sets up this shell would never get one. Every kind is in from the
    first build, the template and the defaults alike."""
    every = storage.ALL_CATEGORIES + [storage.OTHER]
    template = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    assert template["document_types"] == every
    assert storage.SPEC.config_defaults["document_types"] == every


@pytest.mark.parametrize("title,category,summary", [
    ("Kontoauszug 10/2026", "Statement", "Kontoauszug"),
    ("Depotauszug vom 30.09.2026", "Statement", "Depotauszug"),
    ("Abrechnung Kauf WKN A0B1C2", "Statement", "Wertpapierabrechnung Kauf"),
    ("Abrechnung Sparplan WKN A0B1C2", "Statement", "Wertpapierabrechnung Kauf"),
    ("Kosteninformation zu Wertpapier", "Statement", "Kosteninformation"),
    ("Jahressteuerbescheinigung 2025", "Tax Document", "Jahressteuerbescheinigung"),
    ("Verlustbescheinigung 2025", "Tax Document", "Verlustbescheinigung"),
])
def test_broker_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


@pytest.mark.parametrize("name", [
    # Trading
    "Kaufen", "Verkaufen", "Order", "Order aufgeben", "Limit setzen",
    "Stop-Loss", "Kursalarm", "Preisalarm", "Sparplan anlegen", "Sparplan erstellen",
    "Sparplan ändern", "Sparplan pausieren", "Sparplan aussetzen", "Sparplan löschen",
    "Zeichnen", "Handeln", "Buy", "Sell", "Trade", "Savings plan", "Place order",
    # Money in and out
    "Einzahlen", "Geld einzahlen", "Auszahlen", "Auszahlung", "Überweisung", "Ueberweisung",
    "Depotübertrag", "Übertrag starten", "Lastschrift", "Deposit", "Withdraw", "Transfer",
    "Wertpapierkredit", "Kredit beantragen", "Hebel",
    # The subscription
    "Upgrade", "PRIME+ Broker werden", "Abo kündigen", "Abonnement", "Tarif wechseln",
    "Mitgliedschaft", "Upgrade to PRIME+", "Subscribe",
    # Accounts, a child's included, and the person's data
    "Konto eröffnen", "Kinderdepot eröffnen", "Junior-Depot anlegen", "Kind hinzufügen",
    "Depot hinzufügen", "Einladen", "Freistellungsauftrag ändern", "Einstellungen",
    "Persönliche Daten", "E-Mail ändern", "Passwort ändern", "Gerät verwalten", "Adresse",
    "Als gelesen markieren", "Löschen", "Archivieren", "Abmelden", "Open a new account",
    "Add a child", "Invite", "Settings", "Mark as read", "Log out", "Logout",
    "PDF herunterladen | Kaufen",
])
def test_trading_moving_money_and_changing_the_account_are_never_safe(name):
    assert not site.is_safe_control(name), name
    # Beside a document's own word, so only the blocklist can refuse it.
    assert not site.is_safe_control("Dokumente " + name), name


@pytest.mark.parametrize("name", [
    "Postfach", "Mailbox", "Dokumente", "Documents", "Herunterladen", "PDF herunterladen",
    "Download PDF", "Kontoauszug", "Depotauszug", "Wertpapierabrechnung Kauf",
    "Abrechnung Sparplan", "Kosteninformation", "Jahressteuerbescheinigung",
    "Steuerbescheinigung 2025", "Verlustbescheinigung", "Erträgnisaufstellung",
    "Dokument öffnen", "Anzeigen", "Mehr anzeigen", "Archiv", "View statement",
    "Kreditkartenabrechnung",
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
                                  "Hilfe", "Depot 1111"])
def test_a_control_that_names_no_document_is_refused(name):
    """The allowlist, which refuses whatever names no document, however
    harmless it reads."""
    assert not site.is_safe_control(name)


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Kreditkartenabrechnung")   # "kredit" not alone
    assert site.is_safe_control("Wertpapierabrechnung Kauf")  # "Kauf" not alone
    assert not site.is_safe_control("Kauf")


def test_only_scalable_capital_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://de.scalable.capital/")
    assert site.is_safe_url("https://de.scalable.capital/secure-login")
    assert site.is_safe_url("https://secure.scalable.capital/authorize?client_id=x")
    assert not site.is_safe_url("http://de.scalable.capital/")             # not https
    assert not site.is_safe_url("https://de.scalable.capital.example/")
    assert not site.is_safe_url("https://notscalable.capital/")
    assert not site.is_safe_url("https://scalable.capital@evil.test/")
    assert not site.is_safe_url("https://de.scalable.capital:8443/")
    assert not site.is_safe_url("https://scalable-capital.example/")


def test_the_sign_in_address_is_the_one_the_request_names():
    assert site.URLS["login"] == "https://de.scalable.capital/secure-login"
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["home"])


def test_the_document_key_tells_a_childs_account_from_the_persons_own():
    one = app_mod.Document(category="Statement", date="2026-03-31", title="Depotauszug",
                           account="Depot 1111")
    two = app_mod.Document(category="Statement", date="2026-03-31", title="Depotauszug",
                           account="Depot 2222")
    assert one.key != two.key
