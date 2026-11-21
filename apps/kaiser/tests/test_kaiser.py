from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_site as site


def test_only_exact_https_provider_and_document_frame():
    allowed = site.BASE + site._WRAPPER_PATH
    frame = SimpleNamespace(url=site.BASE + "/northern-california/secure/my-documents-myc")
    unrelated = SimpleNamespace(url=site.BASE + "/northern-california/secure/billing")
    assert site.is_history_tab(SimpleNamespace(url=allowed, frames=[unrelated, frame]))
    assert not site.is_history_tab(SimpleNamespace(url=allowed, frames=[unrelated]))
    assert not site.is_history_tab(SimpleNamespace(url=allowed, frames=[frame, frame]))
    assert not site.is_session_url("https://healthy.kaiserpermanente.org.example.test/")
    assert not site.is_session_url("http://healthy.kaiserpermanente.org/")


def test_printed_date_can_differ_from_feed_date():
    row = site.BillRow("getdoc_42", "2031-04-06")
    date = site._statement_date("Premium notice\nStatement Date:\n3/31/2031")
    assert date == "2031-03-31"
    assert date != row.list_date


def test_conflicting_printed_dates_refused():
    with pytest.raises(site.BillMismatch):
        site._statement_date("Statement Date: 3/31/2031\nStatement Date: 4/6/2031")


def test_same_date_bills_have_different_keys():
    first = site.Bill(site.BillRow("getdoc_42", "2031-04-06"), "2031-03-31", "abc")
    other = replace(first, row=site.BillRow("getdoc_43", "2031-04-06"))
    assert first.document_id != other.document_id


def test_changed_viewer_never_prints_or_writes(monkeypatch, tmp_path):
    bill = site.Bill(site.BillRow("getdoc_42", "2031-04-06"), "2031-03-31", "abc")
    monkeypatch.setattr(site, "_history_frame", lambda page: object())
    monkeypatch.setattr(site, "_read_bill",
                        lambda *args: (replace(bill, fingerprint="def"), "changed bill"))
    monkeypatch.setattr(site, "_validated_pdf", lambda *args: pytest.fail("unexpected print"))
    path = tmp_path / "bill.pdf"
    assert not site.download_bill(None, bill, path)
    assert not path.exists()
