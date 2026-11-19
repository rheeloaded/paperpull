"""A viewer that refuses every bill stops the run, and a held date that
Restore settled is not offered again. All values are invented."""
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

BASE = "https://" + site.VIEWER_HOST + site.DOWNLOAD_PATH
SHARED = "2032-03-09"
PDFS = {n: text_pdf([f"Synthetic refusing-viewer bill {n}"]) for n in ("A", "B")}


class _Response:
    headers = {"content-type": "application/pdf"}

    def __init__(self, status, content=b""):
        self.status, self.content = status, content

    def body(self):
        return self.content

    def dispose(self):
        pass


class _Viewer:
    def __init__(self, refuse):
        self.refuse, self.requested = refuse, []

    def get(self, url, *, max_redirects, timeout, headers):
        name = url.rsplit("-", 1)[-1]
        self.requested.append(name)
        if self.refuse:
            return _Response(403)
        return _Response(200, PDFS[name])

    def dispose(self):
        pass


def _app(monkeypatch, tmp_path, rows, viewer, extra=()):
    site._RUN.clear()
    reads = []

    def all_bills(_page):
        reads.append(1)
        return site.bills_of(["Account", "Bill Date", "Action"], rows())

    monkeypatch.setattr(site, "_on_portal", lambda _page: True)
    monkeypatch.setattr(site, "_is_marin_water", lambda _page: True)
    monkeypatch.setattr(site, "_all_bills", all_bills)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                  "min_pdf_bytes": 100}), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config), *extra])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(args)
    monkeypatch.setattr(app, "page", lambda: None)
    portal_tab = SimpleNamespace(url="https://ipn4.paymentus.com/cp/landing.action")
    monkeypatch.setattr(app, "_on_its_site", lambda: portal_tab)
    monkeypatch.setattr(app, "check_session", lambda _page: None)
    monkeypatch.setattr(app, "_delay", lambda: None)
    app._pw = SimpleNamespace(request=SimpleNamespace(new_context=lambda: viewer))
    return app, reads


def test_a_viewer_that_refuses_every_bill_stops_the_run_after_two(monkeypatch, tmp_path):
    def rows():
        return [{"cells": ["000000", f"Jan {d}, 2032", "View Bill"],
                 "views": [f"{BASE}?invented-{d}"]} for d in range(1, 11)]
    viewer = _Viewer(refuse=True)
    app, reads = _app(monkeypatch, tmp_path, rows, viewer)
    app.cmd_discover(quiet=True)
    docs = app._select()
    assert len(docs) == 10
    with pytest.raises(SystemExit):
        app.process(docs)
    site._RUN.clear()
    # Two bills, each asked once from the list just read and once more after
    # a fresh read, and then the run stops.
    assert len(viewer.requested) == 4
    assert len(reads) == 3
    assert not list(tmp_path.rglob("*.pdf"))


def test_a_held_date_restore_settled_is_not_offered_again(monkeypatch, tmp_path, capsys):
    def rows():
        return [{"cells": ["000000", "Mar 9, 2032", "View Bill"], "views": [f"{BASE}?invented-{n}"]}
                for n in ("A", "B")]
    viewer = _Viewer(refuse=False)
    app, _reads = _app(monkeypatch, tmp_path, rows, viewer)
    old_key = f"id:bill-{SHARED}"
    # Saved under its date alone, and its file matches neither bill now.
    record = {"document_id": f"bill-{SHARED}", "date": SHARED, "category": "Statement",
              "title": f"Marin Water Bill {SHARED}", "href": site.DOWNLOAD_PATH,
              "pdf_path": str(tmp_path / "gone.pdf"), "state": State.COMPLETED.value,
              "downloaded_ok": True, "pdf_sha256": sha256(b"another rendering").hexdigest()}
    app.progress.update(old_key, record)
    app.discovery.update(old_key, record)
    app.cmd_discover(quiet=True)
    assert "could not be matched" in capsys.readouterr().out
    app.args.redownload = True
    app.process(app._select())
    app.args.redownload = False
    capsys.readouterr()
    site._RUN.clear()
    app.cmd_discover(quiet=True)
    assert "could not be matched" not in capsys.readouterr().out
    assert app.progress.get(old_key)["downloaded_ok"]


def test_a_date_alone_record_stays_when_its_bill_is_saved_under_its_pdf(tmp_path):
    from paperpull_core.storage import JsonStore
    discovery = JsonStore(tmp_path / "discovery.json")
    progress = JsonStore(tmp_path / "progress.json")
    digest = sha256(PDFS["A"]).hexdigest()
    old_key, new_id = f"id:bill-{SHARED}", f"bill-{SHARED}-{digest}"
    original = {"document_id": f"bill-{SHARED}", "date": SHARED, "pdf_path": "original.pdf",
                "state": State.COMPLETED.value, "downloaded_ok": True, "pdf_sha256": digest}
    progress.update(old_key, original)
    progress.update(f"id:{new_id}", {"document_id": new_id, "pdf_path": "restored.pdf",
                                     "state": State.COMPLETED.value, "downloaded_ok": True})
    discovery.update(old_key, original)
    app = SimpleNamespace(discovery=discovery, progress=progress,
                          paths=SimpleNamespace(root=tmp_path))
    assert app_mod.App._replace_date_record(app, SHARED, {new_id})
    assert progress.get(old_key)["pdf_path"] == "original.pdf"
    assert progress.get(f"id:{new_id}")["pdf_path"] == "restored.pdf"
    assert discovery.get(old_key) is None


def test_refusals_parted_by_a_saved_bill_do_not_stop_the_run(monkeypatch, tmp_path):
    pdfs = {str(d): text_pdf([f"Synthetic parted refusal bill {d}"]) for d in range(1, 5)}

    class Parted(_Viewer):
        def get(self, url, *, max_redirects, timeout, headers):
            name = url.rsplit("-", 1)[-1]
            self.requested.append(name)
            # The first and third bills taken, Jan 4 and Jan 2, are refused.
            return _Response(403) if name in ("4", "2") else _Response(200, pdfs[name])

    def rows():
        return [{"cells": ["000000", f"Jan {d}, 2032", "View Bill"],
                 "views": [f"{BASE}?invented-{d}"]} for d in range(1, 5)]
    viewer = Parted(refuse=False)
    app, _reads = _app(monkeypatch, tmp_path, rows, viewer)
    app.cmd_discover(quiet=True)
    app.process(app._select())
    site._RUN.clear()
    saved = sorted(p.read_bytes() for p in tmp_path.rglob("*.pdf"))
    assert saved == sorted([pdfs["3"], pdfs["1"]])
