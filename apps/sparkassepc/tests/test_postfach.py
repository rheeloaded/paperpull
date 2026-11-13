"""Exercise the Postfach's identity and download boundaries."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sparkassepc_site as site


def test_document_is_named_without_a_full_account_number():
    doc = site._normalize({"folder": "Posteingang", "number": 1, "index": 0,
                           "title": "Kontoauszug zu Konto 1234567890", "date": "01.03.2026",
                           "identity": "invented-id"})
    assert doc["date"] == "2026-03-01"
    assert doc["category"] == "Statement"
    assert doc["account"] == "Konto 7890"
    assert "1234567890" not in doc["title"]


@pytest.mark.parametrize("label", ["Als gelesen setzen", "Als ungelesen setzen", "Löschen",
                                   "Papierkorb leeren", "Überweisung senden"])
def test_state_changing_controls_are_refused(label):
    assert not site.is_safe_control(label)


@pytest.mark.parametrize("path", [
    "/services/download.service/sk-pforzheim-calw/invented/test.pdf?logout=1",
    "/services/download.service/another-bank/invented/test.pdf",
    "/services/download.service/sk-pforzheim-calw/invented/test.html",
])
def test_download_service_path_is_specific(path):
    assert not site._pdf_path(site.BASE + path)


def test_incomplete_paging_never_returns_a_partial_list(monkeypatch):
    monkeypatch.setattr(site, "_folder", lambda *args: None)
    monkeypatch.setattr(site, "_read_page", lambda page: {"number": 1, "rows": [], "next": 3})
    with pytest.raises(site.ListStopped):
        site._collect(object())


@pytest.mark.parametrize("location, followed", [
    ("/listing", True),
    ("https://example.invalid/listing", False),
    ("/another-action", False),
])
def test_paging_follows_only_its_exact_redirect(location, followed):
    from types import SimpleNamespace

    requests = []
    first = SimpleNamespace(status=302, url=site.BASE + "/pager",
                            headers={"location": location}, dispose=lambda: None)

    def post(url, **kwargs):
        requests.append(("POST", url, kwargs["max_redirects"]))
        return first

    def get(url, **kwargs):
        requests.append(("GET", url, kwargs["max_redirects"]))
        return object()

    client = SimpleNamespace(post=post, get=get)
    destination = site.BASE + "/listing"
    response = site.redirects.post_to_listing(client, first.url, destination,
                                              site.is_safe_url, data="page=2")
    assert (response is not first) == followed
    assert requests == [("POST", first.url, 0)] + ([("GET", destination, 0)] if followed else [])


def test_document_identity_does_not_depend_on_its_page_position():
    row = {"folder": "Posteingang", "number": 1, "index": 3, "date": "01.03.2026",
           "title": "Kontoauszug", "identity": "invented-id"}
    first = site._normalize(row)
    moved = site._normalize(dict(row, number=2, index=0))
    other = site._normalize(dict(row, identity="invented-other"))
    assert first["item_id"] == moved["item_id"] != other["item_id"]
    assert "invented-id" not in first["item_id"]
