"""Amazon Visa's guard, host allowlist, document kinds and dates.
Invented values only, never a real account's."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import amazonvisa_docs as app_mod
import amazonvisa_site as site
from paperpull_core import doc_types

APP = Path(__file__).resolve().parents[1]


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "Amazon Visa"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Kreditkartenabrechnungen", "Steuerbescheinigungen", "Vertragsinformationen",
         "Mitteilungen", "Sonstige Dokumente"]
    assert storage.SPEC.routes[storage.CARD] == "card_statements"
    assert storage.SPEC.routes[storage.CONTRACT] == "contract_information"
    assert storage.SPEC.routes[storage.TAX] == "tax_documents"
    assert storage.SPEC.default_route == "other_documents"


def test_an_install_starts_with_every_kind_the_app_may_file():
    """An install keeps the document_types it was set up with, and a kind
    added to the template later reaches new installs only, so a person who
    set up this app before it would never get one. Every kind is in from the
    first build, the template, the defaults and the list alike."""
    template = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    assert template["document_types"] == storage.ALL_CATEGORIES
    assert storage.SPEC.config_defaults["document_types"] == storage.ALL_CATEGORIES
    assert site.storage_categories() == storage.ALL_CATEGORIES


@pytest.mark.parametrize("kind,title,category", [
    ("cat_contratos", "Vertragsinformation", "Contract Information"),
    ("cat_sonstige", "Dokument", "Other Document"),
    ("", "Dokument", "Other Document"),
])
def test_a_category_document_is_filed_by_its_category(kind, title, category):
    assert site.filed_category({"kind": kind, "title": title}) == category


def test_a_statement_keeps_the_kind_its_row_names():
    row = {"title": "Kreditkartenabrechnung", "category": "Credit Card Statement"}
    assert site.filed_category(row) == "Credit Card Statement"
    rules = doc_types.load_rules()
    assert doc_types.classify_document("Kreditkartenabrechnung", rules)[1] == \
        "Kreditkartenabrechnung"


@pytest.mark.parametrize("name", [
    # Money moving and paying the card off
    "Überweisung", "Ueberweisung", "Lastschrift zurückbuchen", "Einzahlen", "Auszahlen",
    "Transfer", "Pay", "Payment", "Direct debit", "Deposit", "Withdraw",
    # Credit and the card itself
    "Kredit beantragen", "Kreditrahmen erhöhen", "Verfügungsrahmen", "Karte sperren",
    "Karte entsperren", "PIN ändern", "Upgrade", "Open a new card", "Lock card",
    "Credit limit", "Close card",
    # The person's data and the account
    "Konto kündigen", "Einstellungen", "Persönliche Daten", "E-Mail ändern",
    "Passwort ändern", "Gerät verwalten", "Adresse", "Benachrichtigungen",
    "Als gelesen markieren", "Löschen", "Archivieren", "Abmelden", "Settings",
    "Mark as read", "Log out", "Logout",
    # Requesting, signing and uploading
    "Kontoauszüge per Post bestellen", "Switch to paper statements",
    "Duplikat anfordern", "Request a statement", "Dokumente unterschreiben",
    "Sign document", "Upload document", "Dokument hochladen", "Kopie anfordern",
    "PDF herunterladen | Überweisung",
])
def test_paying_moving_money_and_changing_the_card_are_never_safe(name):
    assert not site.is_safe_control(name), name
    # Beside a document's own word, so only the blocklist can refuse it.
    assert not site.is_safe_control("Dokumente " + name), name


@pytest.mark.parametrize("name", [
    "Dokumente", "Documents", "Herunterladen", "PDF herunterladen", "Download PDF",
    "Kreditkartenabrechnung", "Abrechnung", "Mehr anzeigen", "Open", "Öffnen", "View",
    "Anzeigen", "PDF anzeigen", "Dokument öffnen", "Open statement", "View statement",
])
def test_reading_a_document_is_safe(name):
    assert site.is_safe_control(name), name


@pytest.mark.parametrize("name", ["Übersicht", "Overview", "Hilfe", "Karte 1111",
                                  "Umsätze", "Transactions"])
def test_a_control_that_names_no_document_is_refused(name):
    assert not site.is_safe_control(name)


def test_only_the_portal_host_is_allowed():
    assert site.is_safe_url("https://kunden.openbankpay.com/amazon/documentation")
    assert site.is_safe_url("https://kunden.openbankpay.com/amazon/login")
    assert not site.is_safe_url("http://kunden.openbankpay.com/amazon/")            # not https
    assert not site.is_safe_url("https://kunden.openbankpay.com.example/amazon/")
    assert not site.is_safe_url("https://notkunden.openbankpay.com/amazon/")
    assert not site.is_safe_url("https://kunden.openbankpay.com@evil.test/amazon/")
    assert not site.is_safe_url("https://kunden.openbankpay.com:8443/amazon/")
    assert not site.is_safe_url("https://www.openbankpay.com/amazon/")
    assert not site.is_safe_url("https://other.kunden.openbankpay.com/amazon/")
    # The document store the PDFs come from is reached only from inside the
    # page, and never by an address this app opens.
    assert not site.is_safe_url(
        "https://prod-de-mbgdcs-documents01.s3.eu-west-1.amazonaws.com/x.pdf")


def test_the_sign_in_address_is_the_portals_own():
    assert site.URLS["login"] == "https://kunden.openbankpay.com/amazon/login"
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["documents"])
    assert site.URLS["login"] == app_mod.site.URLS["login"]


def test_the_document_key_tells_two_cards_apart():
    one = app_mod.Document(category="Credit Card Statement", date="2026-03-31",
                           title="Kreditkartenabrechnung", account="Vertrag 1111")
    two = app_mod.Document(category="Credit Card Statement", date="2026-03-31",
                           title="Kreditkartenabrechnung", account="Vertrag 2222")
    assert one.key != two.key


# -- dates --------------------------------------------------------------------------

@pytest.mark.parametrize("stamp,day", [
    # Winter time, an hour ahead of UTC.
    ("2026-02-28T23:30:00Z", "2026-03-01"),
    ("2026-02-28T22:59:59Z", "2026-02-28"),
    ("2026-03-28T23:30:00Z", "2026-03-29"),
    # Summer time, two hours ahead, from the last Sunday of March to the
    # last Sunday of October.
    ("2026-06-30T21:59:59Z", "2026-06-30"),
    ("2026-06-30T22:00:00.000Z", "2026-07-01"),
    ("2026-06-30T22:00:00.000+0000", "2026-07-01"),
    ("2026-06-30T22:00:00+00:00", "2026-07-01"),
    ("2026-10-24T22:30:00Z", "2026-10-25"),
    ("2026-10-25T22:30:00Z", "2026-10-25"),
    # A moment written in another zone, a space before the time, a small z.
    ("2026-02-28T23:30:00-01:00", "2026-03-01"),
    ("2026-02-28 23:30:00z", "2026-03-01"),
])
def test_a_timestamp_with_a_zone_is_its_day_in_berlin(stamp, day):
    """The date is in each document's identity and its file name."""
    assert site.parse_date(stamp) == day


@pytest.mark.parametrize("value,day", [
    ("2026-02-28", "2026-02-28"),
    ("2026-02-28T23:30:00", "2026-02-28"),
    ("28.02.2026", "2026-02-28"),
    ("20260228", "2026-02-28"),
    ("", ""),
    ("bald", ""),
    ("9999-12-31T23:30:00Z", ""),
])
def test_a_plain_day_is_taken_as_it_is(value, day):
    assert site.parse_date(value) == day
