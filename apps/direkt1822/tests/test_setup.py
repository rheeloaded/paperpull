"""Initial 1822direkt setup checks, with invented controls only."""
import importlib.util
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


def test_technical_capture_never_retains_json_scalar_values_or_query_values():
    spec = importlib.util.spec_from_file_location("capture_structure", APP / "capture_structure.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    assert capture.route("https://www.1822direkt-banking.de/ng-banking/login/eingabe") is None
    assert "PRIVATE" not in json.dumps(capture.schema({"title": "PRIVATE"}))
    metadata = capture.route("https://www.1822direkt-banking.de/JOBa1822Service/api/postboxnachricht/eingang?key=PRIVATE")
    assert metadata["query_keys"] == ["key"]
    assert "PRIVATE" not in json.dumps(metadata)
    assert capture.route("https://www.1822direkt-banking.de/JOBa1822Service/api/benutzerInfo") is None
