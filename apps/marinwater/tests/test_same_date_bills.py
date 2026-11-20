import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marinwater_docs as app_mod
import marinwater_site as site
from paperpull_core.models import State
from paperpull_core.storage import JsonStore
from paperpull_core.testkit import text_pdf

SHARED = "2032-03-09"
UNIQUE = "2032-05-09"
BASE = "https://" + site.VIEWER_HOST + site.DOWNLOAD_PATH
PDFS = {name: text_pdf([f"Synthetic bill {name}"]) for name in ("A", "B", "C", "unique")}


class FakeResponse:
    status = 200
    headers = {"content-type": "application/pdf"}

    def __init__(self, content):
        self.content = content

    def body(self):
        return self.content

    def dispose(self):
        pass


class Viewer:
    def __init__(self):
        self.requested = []
        self.replaced = {}

    def get(self, url, *, max_redirects, timeout, headers):
        assert url.startswith(BASE + "?")
        assert max_redirects == 0 and "Cookie" not in headers
        name = url.rsplit("-", 1)[-1]
        self.requested.append(name)
        content = self.replaced.get(name, PDFS[name])
        if content is None:
            response = FakeResponse(b"")
            response.status = 403
            return response
        return FakeResponse(content)

    def dispose(self):
        pass


def rows(generation, order):
    return [{
        "cells": ["000000", "May 9, 2032" if name == "unique" else "Mar 9, 2032", "View Bill"],
        "views": [f"{BASE}?invented-{generation}-{name}"]
    } for name in order]


@pytest.fixture
def history(monkeypatch):
    state = {"generation": 1, "order": ["A", "B", "C", "unique"]}
    site._RUN.clear()
    monkeypatch.setattr(site, "_on_portal", lambda _page: True)
    monkeypatch.setattr(site, "_is_marin_water", lambda _page: True)
    monkeypatch.setattr(site, "_all_bills", lambda _page: site.bills_of(
        ["Account", "Bill Date", "Action"], rows(state["generation"], state["order"])))
    return state


def test_same_date_ids_survive_reordered_rows_and_reissued_links(history, tmp_path):
    viewer = Viewer()
    docs = site.collect_download_docs(None, viewer=viewer)
    expected = {f"bill-{SHARED}-{sha256(PDFS[name]).hexdigest()}" for name in ("A", "B", "C")}
    assert {doc.document_id for doc in docs} == expected | {f"bill-{UNIQUE}"}
    assert viewer.requested == ["A", "B", "C"]

    history.update(generation=2, order=["C", "A", "B", "unique"])
    fresh = site.collect_download_docs(None, viewer=viewer)
    assert {doc.document_id for doc in fresh} == expected | {f"bill-{UNIQUE}"}
    identity = f"bill-{SHARED}-{sha256(PDFS['B']).hexdigest()}"
    output = tmp_path / "sample.pdf"
    assert site.download_bill(None, None, SHARED, output, href=site.DOWNLOAD_PATH,
                              document_id=identity, viewer=viewer)
    assert output.read_bytes() == PDFS["B"]
    assert len({app_mod.told_apart_by({"document_id": doc_id}) for doc_id in expected}) == 3


def test_shrinking_group_keeps_id_and_changed_pdf_is_not_saved(history, tmp_path):
    viewer = Viewer()
    history["order"] = ["A", "unique"]
    docs = site.collect_download_docs(None, viewer=viewer, split_dates={SHARED})
    doc = next(bill for bill in docs if bill.date_text == SHARED)
    assert doc.document_id == f"bill-{SHARED}-{sha256(PDFS['A']).hexdigest()}"
    viewer.replaced["A"] = PDFS["B"]
    output = tmp_path / "changed.pdf"
    assert not site.download_bill(None, None, SHARED, output, href=doc.href, document_id=doc.document_id,
                                  viewer=viewer, split_dates={SHARED})
    assert not output.exists()


@pytest.mark.parametrize("unavailable", [b"not a PDF", None])
def test_unavailable_pdf_keeps_other_dates_and_duplicates_collapse(history, unavailable):
    viewer = Viewer()
    viewer.replaced.update(A=PDFS["B"], C=unavailable)
    with pytest.raises(site.ListStopped) as error:
        site.collect_download_docs(None, viewer=viewer)
    assert [b.document_id for b in error.value.docs] == [f"bill-{UNIQUE}"]
    viewer.replaced.pop("C")
    docs = site.collect_download_docs(None, viewer=viewer)
    assert sum(b.date_text == SHARED for b in docs) == 2


@pytest.mark.parametrize("prior", ["held", "matches", "missing"])
def test_date_only_records_are_promoted_without_losing_archived_identity(tmp_path, prior):
    discovery = JsonStore(tmp_path / "discovery.json")
    progress = JsonStore(tmp_path / "progress.json")
    old_id = "bill-" + SHARED
    old_key = "id:" + old_id
    archived = tmp_path / "archived.pdf"
    discovery.update(old_key, {"document_id": old_id, "date": SHARED, "ambiguous": True})
    if prior != "held":
        progress.update(old_key, {"document_id": old_id, "date": SHARED, "pdf_path": archived.name,
                                  "state": State.COMPLETED.value, "downloaded_ok": True})
    if prior == "matches":
        archived.write_bytes(PDFS["A"])
    ids = {f"{old_id}-{sha256(PDFS[name]).hexdigest()}" for name in ("A", "B", "C")}
    if prior == "matches":
        new_id = f"{old_id}-{sha256(PDFS['A']).hexdigest()}"
        progress.update(f"id:{new_id}", {"document_id": new_id, "state": State.FAILED.value})
    app = SimpleNamespace(discovery=discovery, progress=progress, paths=SimpleNamespace(root=tmp_path))
    ready = app_mod.App._replace_date_record(app, SHARED, ids)
    if prior == "missing":
        assert not ready and progress.get(old_key) and discovery.get(old_key)
    else:
        assert ready and discovery.get(old_key) is None and progress.get(old_key) is None
        if prior == "matches":
            new_id = f"{old_id}-{sha256(PDFS['A']).hexdigest()}"
            assert progress.get(f"id:{new_id}")["downloaded_ok"]
            assert archived.read_bytes() == PDFS["A"]


def test_restore_saves_same_date_bills_when_the_old_pdf_is_missing(history, monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic Owner", "output_dir": str(tmp_path), "min_pdf_bytes": 100,
    }), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config), "--end-date", SHARED])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(args)
    monkeypatch.setattr(app, "_on_its_site", lambda: None)
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    viewer = Viewer()
    app._pw = SimpleNamespace(request=SimpleNamespace(new_context=lambda: viewer))

    old_id = f"bill-{SHARED}"
    old_key = f"id:{old_id}"
    legacy = {"document_id": old_id, "date": SHARED, "pdf_path": "deleted.pdf",
              "state": State.COMPLETED.value, "downloaded_ok": True}
    app.progress.update(old_key, legacy)
    app.discovery.update(old_key, legacy)
    saved_legacy = dict(app.progress.get(old_key))
    app.cmd_discover(quiet=True)
    assert app._select() == []

    args.redownload = True
    history.update(generation=2, order=["C", "unique", "B", "A"])
    app.cmd_discover(quiet=True)
    selected = app._select()
    assert len(selected) == 3
    assert all(doc.document_id != old_id for doc in selected)
    app.process(selected)
    saved = [Path(app.progress.get(doc.key)["pdf_path"]) for doc in selected]
    assert len(set(saved)) == 3
    assert {pdf.read_bytes() for pdf in saved} == {PDFS[name] for name in ("A", "B", "C")}
    assert app.progress.get(old_key) == saved_legacy

    args.redownload = False
    history.update(generation=3, order=["B", "A", "C", "unique"])
    app.cmd_discover(quiet=True)
    assert app._select() == []
    assert all(app._already_done(doc) for doc in selected)
    assert app.progress.get(old_key) == saved_legacy
