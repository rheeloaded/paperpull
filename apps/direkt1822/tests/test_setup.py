"""Initial 1822direkt setup checks, with invented controls only."""
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import direkt1822_site as site


def test_sign_in_and_postbox_use_the_confirmed_public_routes():
    assert site.URLS["login"] == "https://www.1822direkt-banking.de/ng-banking/login/eingabe"
    assert site.URLS["documents"] == "https://www.1822direkt-banking.de/ng-banking/banking/postbox"


@pytest.mark.parametrize("url", ["https://evil.example/", "https://www.1822direkt-banking.de.evil.example/",
                                "http://www.1822direkt-banking.de/", "https://www.1822direkt-banking.de:8443/"])
def test_other_hosts_and_unexpected_connections_are_refused(url):
    assert not site.is_safe_url(url)


@pytest.mark.parametrize("label", ["Überweisung", "Dokumente löschen", "Mark as read", "Kredit beantragen",
                                  "PDF herunterladen | Überweisung", "Depot eröffnen", "Pay", "PIN ändern"])
def test_financial_and_account_changes_are_refused(label):
    assert not site.is_safe_control(label)


def test_the_app_holds_no_capture_tool_of_its_own():
    """capture_structure.py masked only runs of five digits or more, sixteen
    hex letters or segments over a hundred letters, so a file name in an
    address reached a file people attach to issues. Record in the panel
    writes a page's addresses through the fixed list of words, so the app
    keeps its three modules and nothing that writes a capture beside them."""
    assert sorted(p.name for p in APP.glob("*.py")) == [
        "direkt1822_docs.py", "direkt1822_site.py", "storage.py"]


def test_nothing_offers_to_open_a_conversation():
    """Opening a conversation marks it read at the bank, so this version
    never does, and neither its config nor its command line offers it."""
    import direkt1822_docs as docs
    config = json.loads((APP / "config.example.json").read_text(encoding="utf-8"))
    assert not any("conversation" in key for key in config)
    flags = {flag for action in docs.build_parser()._actions for flag in action.option_strings}
    assert not any("mark" in flag or "conversation" in flag for flag in flags)
    assert "leseUndVermerke" not in site._API_JS
