"""A list that stops partway keeps a bill saved before its date gained a twin.

A bill saved under its date alone, whose date later shows a second bill, is
moved to the identity its PDF gives when the history is read whole. A list
that stopped partway has to do the same with what it read, since Resume
carries on from what that list kept. Without it Resume saves the archived
bill a second time under its new identity. All values are invented.
"""
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
from paperpull_core.testkit import text_pdf

SHARED = "2032-03-09"
OTHER = "2032-06-09"
BASE = "https://" + site.VIEWER_HOST + site.DOWNLOAD_PATH
PDFS = {name: text_pdf([f"Synthetic stopped-list bill {name}"])
        for name in ("A", "B", "X1", "X2")}


class _Response:
    headers = {"content-type": "application/pdf"}

    def __init__(self, status, content):
        self.status, self.content = status, content

    def body(self):
        return self.content

    def dispose(self):
        pass


class _Viewer:
    def __init__(self):
        self.refused, self.requested = set(), []

    def get(self, url, *, max_redirects, timeout, headers):
        name = url.rsplit("-", 1)[-1]
        self.requested.append(name)
        if name in self.refused:
            return _Response(403, b"")
        return _Response(200, PDFS[name])

    def dispose(self):
        pass


def _rows():
    return [{"cells": ["000000", day, "View Bill"], "views": [f"{BASE}?invented-{name}"]}
            for day, name in (("Mar 9, 2032", "A"), ("Mar 9, 2032", "B"),
                              ("Jun 9, 2032", "X1"), ("Jun 9, 2032", "X2"))]


@pytest.fixture
def app(monkeypatch, tmp_path):
    site._RUN.clear()
    monkeypatch.setattr(site, "_on_portal", lambda _page: True)
    monkeypatch.setattr(site, "_is_marin_water", lambda _page: True)
    monkeypatch.setattr(site, "_all_bills", lambda _page: site.bills_of(
        ["Account", "Bill Date", "Action"], _rows()))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                  "min_pdf_bytes": 100}), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config)])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    the_app = app_mod.App(args)
    monkeypatch.setattr(the_app, "page", lambda: None)
    monkeypatch.setattr(the_app, "_on_its_site", lambda: None)
    monkeypatch.setattr(the_app, "check_session", lambda _page: None)
    monkeypatch.setattr(the_app, "_delay", lambda: None)
    viewer = _Viewer()
    the_app._pw = SimpleNamespace(request=SimpleNamespace(new_context=lambda: viewer))
    yield the_app, viewer
    site._RUN.clear()


def _pdfs_under(root: Path):
    return sorted(p for p in root.rglob("*.pdf") if p.is_file())


@pytest.mark.parametrize("archived", ["matches", "unmatched"])
def test_resume_after_a_stopped_list_saves_no_second_copy_of_a_saved_bill(app, archived, tmp_path):
    the_app, viewer = app
    # The bill saved before its date gained a twin, under its date alone.
    old_key = f"id:bill-{SHARED}"
    kept = the_app.paths.folder_for("Statement") / "2032-03-09 Water Bill (archived).pdf"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(PDFS["A"] if archived == "matches" else text_pdf(["another rendering"]))
    record = {"document_id": f"bill-{SHARED}", "date": SHARED, "category": "Statement",
              "title": f"Marin Water Bill {SHARED}", "href": site.DOWNLOAD_PATH,
              "pdf_path": str(kept), "state": State.COMPLETED.value, "downloaded_ok": True,
              "pdf_sha256": sha256(kept.read_bytes()).hexdigest()}
    the_app.progress.update(old_key, record)
    the_app.discovery.update(old_key, record)
    before = {p: p.read_bytes() for p in _pdfs_under(tmp_path)}

    # The other date's second bill is refused while the list is read, so the
    # list stops with the shared date's two bills identified.
    viewer.refused.add("X2")
    with pytest.raises(SystemExit):
        the_app.cmd_discover(quiet=True)

    # Resume carries on from what that list kept, the viewer answering now.
    viewer.refused.clear()
    site._RUN.clear()
    try:
        the_app.cmd_resume()
    except SystemExit:
        pass

    for path, data in before.items():
        assert path.read_bytes() == data, "a file saved before was changed"
    saved = [p.read_bytes() for p in _pdfs_under(tmp_path)]
    if archived == "matches":
        # The archived bill is bill A, known again by its PDF, and only bill
        # B is new. Bill A is never saved a second time.
        assert saved.count(PDFS["A"]) == 1
        a_key = f"id:bill-{SHARED}-{sha256(PDFS['A']).hexdigest()}"
        assert (the_app.progress.get(a_key) or {}).get("downloaded_ok")
    else:
        # Which of the two the archived file is cannot be told, so neither
        # is fetched until Restore deleted files asks for that date.
        assert PDFS["A"] not in saved and PDFS["B"] not in saved
        assert the_app.progress.get(old_key)["downloaded_ok"]


def test_a_stopped_list_records_no_date_alone_for_a_date_told_apart_by_pdfs(app, monkeypatch):
    the_app, _viewer = app
    split_id = f"bill-{SHARED}-{sha256(PDFS['A']).hexdigest()}"
    the_app.progress.update(f"id:{split_id}", {"document_id": split_id, "date": SHARED,
                                               "state": State.COMPLETED.value,
                                               "downloaded_ok": True})
    # The list stops on its second row, after one bill of the shared date
    # was read under that date alone, before its date could be settled.
    rows = _rows()[:1] + [{"cells": ["000000", "not a date", "View Bill"],
                           "views": [f"{BASE}?invented-B"]}]
    monkeypatch.setattr(site, "_all_bills", lambda _page: site.bills_of(
        ["Account", "Bill Date", "Action"], rows))
    with pytest.raises(SystemExit):
        the_app.cmd_discover(quiet=True)
    assert the_app.discovery.get(f"id:bill-{SHARED}") is None
    assert the_app._select() == []
