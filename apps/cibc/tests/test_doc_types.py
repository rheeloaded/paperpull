"""CIBC's guard, host allowlist and document kinds.
Invented values only, never a real account's."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import cibc_docs as app_mod
import cibc_site as site
from paperpull_core import doc_types

APP = Path(__file__).resolve().parents[1]


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "CIBC"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Statements", "Credit Card Statements", "Line of Credit Statements",
         "Tax Documents", "Other Documents"]
    assert storage.SPEC.routes[storage.STATEMENT] == "statements"
    assert storage.SPEC.routes[storage.CARD] == "card_statements"
    assert storage.SPEC.routes[storage.CREDIT_LINE] == "line_of_credit_statements"
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
    assert template["cdp_url"] == "http://127.0.0.1:9311"


@pytest.mark.parametrize("title,category,summary", [
    ("Chequing account statement 1/2026", "Statement", "Account Statement"),
    ("Savings account statement", "Statement", "Account Statement"),
    ("eStatement", "Statement", "Account Statement"),
    ("Relevé de compte de chèques", "Statement", "Account Statement"),
    ("CIBC Dividend Visa Card statement", "Statement", "Credit Card Statement"),
    ("Credit card statement 9/2026", "Statement", "Credit Card Statement"),
    ("Relevé de carte de crédit", "Statement", "Credit Card Statement"),
    ("Personal line of credit statement", "Statement", "Line of Credit Statement"),
    ("Relevé de marge de crédit", "Statement", "Line of Credit Statement"),
    ("T5 Statement of Investment Income 2025", "Tax Document", "T5 Tax Slip"),
    ("T5008 2025", "Tax Document", "T5008 Tax Slip"),
    ("RRSP contribution receipt", "Tax Document", "Contribution Receipt"),
])
def test_bank_card_and_credit_line_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


@pytest.mark.parametrize("name", [
    # Money moving
    "Transfer funds", "Interac e-Transfer", "Send money", "Request money", "Pay bills",
    "Bill payments", "Make a payment", "Add payee", "Manage recipients", "Deposit a cheque",
    "Mobile cheque deposit", "Withdraw", "Global Money Transfer", "Wire payment",
    "Buy foreign currency", "Convert", "Stop a cheque", "Stop payment",
    # Trading and investing
    "Buy", "Sell", "Trade", "Invest now",
    # Credit and cards
    "Cash advance", "Balance transfer", "Increase credit limit", "Request a limit increase",
    "Borrow", "Instalment plan", "Installment plan", "Pace It", "Pay over time",
    "Redeem rewards", "Aventura points", "Offers", "Upgrade your card", "Apply now",
    "Open a new account", "Open an account", "Open a TFSA", "Open a GIC", "Open savings account",
    "Open a line of credit", "Open overdraft protection", "Get a new card", "Get a loan",
    "Get a mortgage", "Close account", "Close my card",
    # Ordering, requesting, signing, uploading and statement delivery
    "Order cheques", "Order paper statements", "Request a statement copy", "Request a copy",
    "Duplicate statement", "Reprint statement", "Upload document", "Sign document",
    "eSign documents", "Switch to paper statements", "Switch to eStatements", "Go paperless",
    "Delivery preferences", "Paper statements",
    # The card, the account and the person's data
    "Lock card", "Unlock card", "Freeze card", "Replace card", "Activate card", "Change PIN",
    "Report a lost or stolen card", "Report fraud", "Dispute a transaction", "Travel notice",
    "Alerts", "Notifications", "Enrol", "Register", "Nickname", "Add a beneficiary",
    "Authorized user", "Password", "Profile", "Settings", "Preferences", "Address",
    "Email", "Phone", "Contact information", "Chat with us",
    "Edit", "Update", "Delete", "Remove", "Cancel", "Submit", "Confirm", "Accept", "Agree",
    "Mark as read", "Archive", "Sign off", "Sign out", "Log out", "Logout",
    # French
    "Virement Interac", "Virements", "Transférer des fonds", "Payer des factures", "Paiements",
    "Déposer un chèque", "Retrait", "Envoyer de l'argent", "Demander de l'argent", "Acheter",
    "Vendre", "Avance de fonds", "Augmenter la limite de crédit", "Emprunter",
    "Versements égaux", "Récompenses", "Offres", "Ouvrir un compte", "Ouvrir une carte",
    "Ouvrir une marge de crédit", "Ouvrir un nouveau compte", "Fermer le compte",
    "Commander des relevés papier", "Téléverser un document", "Signer", "Copie du relevé",
    "Verrouiller la carte", "Déverrouiller", "Bloquer la carte", "Remplacer la carte",
    "Activer la carte", "Carte perdue ou volée", "Fraude", "Contester une transaction",
    "Alertes", "Avis de voyage", "Inscription", "Mot de passe", "Profil", "Paramètres",
    "Préférences", "Adresse", "Courriel", "Téléphone", "Modifier", "Changer", "Supprimer",
    "Annuler", "Soumettre", "Confirmer", "Accepter", "Déconnexion", "Fermeture de session",
    "Quitter",
    # French for what the English above refuses, found by the review of
    # the first build.
    "Régler le solde du relevé",
    "Rembourser le solde du relevé",
    "Acquitter le solde du relevé",
    "Règlement du relevé",
    "Passer aux relevés électroniques",
    "Adhérer aux relevés électroniques",
    "Opter pour les relevés électroniques",
    "Abonnement aux relevés électroniques",
    "Recevoir les relevés en ligne",
    "Gérer les relevés électroniques",
    "Ajouter un bénéficiaire",
    "Dépôt mobile",
    "Download PDF | Transfer funds",
])
def test_moving_money_borrowing_and_changing_the_account_are_never_safe(name):
    assert not site.is_safe_control(name), name
    # Beside a document's own word, so only the blocklist can refuse it.
    assert not site.is_safe_control("Statements " + name), name


@pytest.mark.parametrize("name", [
    "Statements", "eStatements", "Documents", "eDocuments", "Download", "Download PDF",
    "PDF", "View statement", "View", "Open", "Open statement", "Open document",
    "Open card statement", "Open line of credit statement", "Open savings account statement",
    "Credit card statement", "Line of credit statement", "Account statement",
    "Statements and documents", "Tax slips", "T5", "T5008", "Show more", "Load more",
    "See all", "View older",
    "Relevés", "Relevé", "Relevé de carte de crédit", "Télécharger", "Télécharger le PDF",
    "Feuillets d'impôt", "Ouvrir", "Afficher", "Voir", "Afficher plus", "Voir plus",
    "Ouvrir le relevé", "Documents électroniques",
])
def test_reading_a_document_is_safe(name):
    assert site.is_safe_control(name), name


@pytest.mark.parametrize("name", ["Overview", "Accounts", "Transactions", "Help",
                                  "Chequing 1111", "Open account details", "View accounts",
                                  "Open my accounts", "Aperçu", "Comptes", "Aide",
                                  "Ouvrir mes comptes", "Afficher le compte"])
def test_a_control_that_names_no_document_is_refused(name):
    """The allowlist, which refuses whatever names no document, however
    harmless it reads."""
    assert not site.is_safe_control(name)


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit card statement")   # "edit" inside "Credit"
    assert site.is_safe_control("Line of credit statement")
    assert not site.is_safe_control("Credit limit")


def test_only_cibconline_cibc_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.cibconline.cibc.com/")
    assert site.is_safe_url(
        "https://www.cibconline.cibc.com/ebm-resources/public/banking/cibc/client/web/index.html#/signon")
    assert site.is_safe_url("https://cibconline.cibc.com/")
    assert not site.is_safe_url("http://www.cibconline.cibc.com/")             # not https
    assert not site.is_safe_url("https://www.cibc.com/")                       # the public site
    assert not site.is_safe_url("https://cibc.com/")
    assert not site.is_safe_url("https://www.cibconline.cibc.com.example/")
    assert not site.is_safe_url("https://notcibconline.cibc.com/")
    assert not site.is_safe_url("https://www.cibconline.cibc.com@evil.test/")
    assert not site.is_safe_url("https://www.cibconline.cibc.com:8443/")
    assert not site.is_safe_url("https://www.cibconline.cibc.ca/")


def test_the_sign_in_address_is_the_one_the_request_names():
    assert site.URLS["login"] == "https://www.cibconline.cibc.com/"
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["home"])


def test_the_document_key_tells_two_accounts_apart():
    one = app_mod.Document(category="Statement", date="2026-03-31", title="Account Statement",
                           account="Chequing 1111")
    two = app_mod.Document(category="Statement", date="2026-03-31", title="Account Statement",
                           account="Savings 2222")
    assert one.key != two.key
