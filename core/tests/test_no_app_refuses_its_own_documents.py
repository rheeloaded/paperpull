"""No app refuses to click the documents it says it collects.

"edit" without a word boundary matched inside "Credit", so "Credit Card
Statement" was refused on a credit card provider. That was found and fixed
five separate times, one app at a time: the core in 0.17.1, then Anthem,
then Capital One, then U.S. Bank, then Schwab. Each commit says it is the
same shape as the last. Nobody asked the other forty-three.

Asked here, and two more had it. Target RedCard refused "Account
Statement", which is the only kind of document it collects, and Affirm
refused "Card Statement", because both blocklists refused the bare nouns
"card" and "account". On a card portal those are what the document is
called. What makes a control dangerous is the verb in front of the noun,
and the words that sit between them are why an exact phrase is not enough:
"Add a new card", "Manage my card".

The vocabulary is not invented here. Each app declares what it collects in
its own *_rules.json, as the summary it writes for each kind of document it
recognizes, so this asks every app about its own documents.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())

# How a provider labels the control that gets you the document.
VERBS = ("", "View ", "Download ")

# Two apps refuse a document name on purpose, and both are allowed to.
# On a military pay system "W-2", "SGLI", "FEGLI", "Beneficiary" and "Net
# Pay" name a settings form as often as a document, and neither app gates a
# click on this answer: myPay reads its documents from a JSON API and
# AAFMAA's guard only annotates the diagnose dump. Written down as names so
# the list can shrink and cannot quietly grow.
ALLOWED_TO = {
    "mypay": {"Annuitant Account Statement", "FEGLI Document", "Net Pay Advice",
              "SGLI Document", "W-2 Tax Form"},
    "aafmaa": {"Beneficiary Designation", "Payment Record"},
}


def own_documents(app: Path) -> list:
    """The summaries this app's own rules produce."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            summary = node.get("summary")
            if isinstance(summary, str) and summary.strip():
                found.append(summary.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for rules in sorted(app.glob("*_rules.json")):
        try:
            walk(json.loads(rules.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(set(found))


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_will_click_the_documents_it_collects(app):
    documents = own_documents(app)
    if not documents:
        pytest.skip("this app declares no document rules")
    site = site_of(app)
    check = getattr(site, "is_safe_control", None)
    if check is None:
        pytest.skip("guards with the blocklist inline, so pagination still works")
    refused = [d for d in documents
               if not any(check(verb + d) for verb in VERBS)]
    unexpected = sorted(set(refused) - ALLOWED_TO.get(app.name, set()))
    assert not unexpected, (
        "%s refuses to click its own documents, under any verb: %s"
        % (app.name, ", ".join(unexpected)))


@pytest.mark.parametrize("app", sorted(ALLOWED_TO))
def test_the_named_exceptions_are_still_the_only_ones(app):
    """An exception that stops being one has to be taken off the list, or
    the list becomes the place bugs go to be forgotten."""
    folder = REPO / "apps" / app
    if not folder.exists():
        pytest.skip("%s is not here" % app)
    site = site_of(folder)
    check = getattr(site, "is_safe_control", None)
    if check is None:
        pytest.skip("no control guard")
    documents = set(own_documents(folder))
    stale = sorted(name for name in ALLOWED_TO[app]
                   if name in documents
                   and any(check(verb + name) for verb in VERBS))
    assert not stale, (
        "%s no longer refuses %s, so it does not need an exception"
        % (app, ", ".join(stale)))


# -- and the verb still reaches the noun ---------------------------------------

DANGEROUS_WITH_A_NOUN = [
    "Add card", "Add a card", "Add a new card", "Add new card",
    "Manage card", "Manage my card", "Activate card", "Activate your card",
    "Replace card", "Replace my card", "Lock card", "Unlock my card",
    "Freeze card", "Link a card", "Remove card", "Report lost card",
    "Report card lost or stolen", "Lost or stolen card", "Virtual card",
    "Card settings", "Close account", "Close my account",
    "Open a new account", "Open an account", "Account settings",
    "Account services", "Manage account", "Order a replacement card",
]


@pytest.mark.parametrize("app", ["redcard", "affirm"])
def test_the_two_apps_that_were_fixed_still_refuse_the_verbs(app):
    """The fix let the noun through. It must not have let the verb through
    with it, and a phrase with a word inside it is the way that happens."""
    folder = REPO / "apps" / app
    if not folder.exists():
        pytest.skip("%s is not here" % app)
    site = site_of(folder)
    allowed = [label for label in DANGEROUS_WITH_A_NOUN
               if not site.FORBIDDEN_CONTROL_RE.search(label)]
    assert not allowed, "%s would click: %s" % (app, ", ".join(allowed))


@pytest.mark.parametrize("app", ["redcard", "affirm"])
def test_and_those_two_will_click_a_statement(app):
    folder = REPO / "apps" / app
    if not folder.exists():
        pytest.skip("%s is not here" % app)
    site = site_of(folder)
    for label in ("Account Statement", "View Account Statement",
                  "Download Account Statement", "Card Statement",
                  "View Card Statement", "Statement", "Download PDF"):
        assert site.is_safe_control(label), "%s refuses %r" % (app, label)
