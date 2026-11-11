"""MBNA's guard, host allowlist and document kinds.
Invented values only, never a real account's."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import mbna_docs as app_mod
import mbna_site as site
from paperpull_core import doc_types

APP = Path(__file__).resolve().parents[1]


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "MBNA"
    assert [f.name for f in storage.SPEC.folders
            if not f.name.startswith(("Backups", "Logs", "Diagnostics", "Manual"))] == \
        ["Statements", "Other Documents"]
    assert storage.SPEC.routes[storage.STATEMENT] == "statements"
    assert storage.SPEC.default_route == "other_documents"


def test_an_install_starts_with_every_kind_the_real_build_may_file():
    """An install keeps the document_types it was set up with, and a kind
    added to the template later reaches new installs only, so a tester who
    sets up this shell would never get one. Every kind is in from the
    first build, the template and the defaults alike."""
    every = storage.ALL_CATEGORIES + [storage.OTHER]
    template = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    assert template["document_types"] == every
    assert storage.SPEC.config_defaults["document_types"] == every
    assert template["cdp_url"] == "http://127.0.0.1:9312"


@pytest.mark.parametrize("title,category,summary", [
    ("Statement 1/2026", "Statement", "Credit Card Statement"),
    ("eStatement", "Statement", "Credit Card Statement"),
    ("MBNA Rewards World Elite Mastercard statement", "Statement", "Credit Card Statement"),
    ("Relevé", "Statement", "Credit Card Statement"),
    ("Relevés de compte", "Statement", "Credit Card Statement"),
])
def test_card_statement_titles_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


@pytest.mark.parametrize("name", [
    # Paying and moving money
    "Make a payment", "Pay now", "Payments", "Pre-authorized payment", "Autopay", "Add payee",
    "Balance transfer", "Transfer funds", "Interac e-Transfer", "Deposit", "Withdraw",
    "Send money", "Stop payment",
    # Credit and the card
    "Cash advance", "Request cheques", "Convenience cheques", "Increase credit limit",
    "Credit limit increase", "Borrow", "Instalment plan", "Installment plan", "Payment plan",
    "Pay over time", "Redeem rewards", "Rewards", "Points", "Cash back", "Offers",
    "Upgrade", "Product change", "Apply now", "Buy",
    "Open a new card", "Open an account", "Get a new card", "Add an authorized user",
    "Add a user", "Add card", "Authorized users", "Close account", "Close my card",
    # Ordering, requesting, signing, uploading and statement delivery
    "Order a card", "Order paper statements", "Request a statement copy", "Request a copy",
    "Duplicate statement", "Reprint statement", "Upload document", "Sign document",
    "Switch to paper statements", "Switch to eStatements", "Go paperless",
    "Delivery preferences", "Paper statements",
    # The card, the account and the person's data
    "Lock card", "Unlock card", "Freeze card", "Replace card", "Activate card", "Change PIN",
    "Report a lost or stolen card", "Report fraud", "Dispute a transaction", "Travel notice",
    "Alerts", "Notifications", "Enrol", "Register", "Nickname", "Password", "Profile",
    "Settings", "Preferences", "Address", "Email", "Phone", "Contact information",
    "Chat with us", "Edit", "Update", "Delete", "Remove", "Cancel", "Submit", "Confirm",
    "Accept", "Agree", "Mark as read", "Archive", "Sign off", "Sign out", "Log out", "Logout",
    # French
    "Faire un paiement", "Payer", "Virement", "Transfert de solde", "Transférer", "Déposer",
    "Retrait", "Envoyer", "Demander des chèques", "Chèques", "Avance de fonds",
    "Augmenter la limite de crédit", "Emprunter", "Prêt", "Versements égaux", "Récompenses",
    "Offres", "Acheter", "Ouvrir une carte", "Ouvrir un compte",
    "Ajouter un utilisateur autorisé", "Utilisateurs autorisés", "Fermer le compte",
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
    "Virer des fonds",
    "Payer les factures",
    "Ajouter un bénéficiaire",
    "Download PDF | Make a payment",
])
def test_paying_borrowing_and_changing_the_card_are_never_safe(name):
    assert not site.is_safe_control(name), name
    # Beside a document's own word, so only the blocklist can refuse it.
    assert not site.is_safe_control("Statements " + name), name


@pytest.mark.parametrize("name", [
    "Statements", "eStatements", "Documents", "Download", "Download PDF", "PDF",
    "View statement", "View", "Open", "Open statement", "Open card statement",
    "Open account statement", "Credit card statement", "Statement details", "Show more",
    "Load more", "See all", "View older",
    "Relevés", "Relevé", "Télécharger", "Télécharger le PDF", "Ouvrir", "Afficher", "Voir",
    "Afficher plus", "Voir plus", "Ouvrir le relevé", "Relevé de carte de crédit",
])
def test_reading_a_statement_is_safe(name):
    assert site.is_safe_control(name), name


@pytest.mark.parametrize("name", ["Overview", "Accounts", "Transactions", "Help", "Card 1111",
                                  "Open card details", "View card", "View transactions",
                                  "Aperçu", "Transactions récentes", "Aide",
                                  "Afficher la carte"])
def test_a_control_that_names_no_document_is_refused(name):
    """The allowlist, which refuses whatever names no document, however
    harmless it reads."""
    assert not site.is_safe_control(name)


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    assert site.is_safe_control("Credit card statement")   # "edit" inside "Credit"
    assert not site.is_safe_control("Credit limit")


def test_only_mbna_ca_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://service.mbna.ca/waw/mbna/login")
    assert site.is_safe_url("https://authentication.mbna.ca/")
    assert site.is_safe_url("https://authorization.mbna.ca/as/a")
    assert site.is_safe_url("https://www.mbna.ca/en")
    assert not site.is_safe_url("http://service.mbna.ca/")                    # not https
    assert not site.is_safe_url("https://service.mbna.ca.example/")
    assert not site.is_safe_url("https://notmbna.ca/")
    assert not site.is_safe_url("https://service.mbna.ca@evil.test/")
    assert not site.is_safe_url("https://service.mbna.ca:8443/")
    assert not site.is_safe_url("https://www.mbna.com/")
    assert not site.is_safe_url("https://www.mbna.co.uk/")
    assert not site.is_safe_url("https://www.td.com/")


def test_the_sign_in_opens_where_mbna_ca_sends_it():
    """The address mbna.ca's own Login links lead to, which hands over to
    the host the request names, whose bare address answers "not found"."""
    assert site.URLS["login"] == "https://service.mbna.ca/waw/mbna/login"
    assert "//authentication.mbna.ca/" in site.LOGIN_URL_MARKERS
    assert site.is_safe_url(site.URLS["login"]) and site.is_safe_url(site.URLS["home"])


def test_the_document_key_tells_two_cards_apart():
    one = app_mod.Document(category="Statement", date="2026-03-31", title="Statement",
                           account="Card 1111")
    two = app_mod.Document(category="Statement", date="2026-03-31", title="Statement",
                           account="Card 2222")
    assert one.key != two.key
