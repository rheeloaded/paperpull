"""The Documents settings offer the Move that brings documents out of their
kind folders once "kind_folders" is false (#201).

A Move without kind folders takes each document out of the folder of its
kind, in the output folder and in the documents folder alike. The panel
counted only what was outside the documents folder, so a document already
in Watched/Statements was never counted, and with nothing counted the page
never offered the Move that brings it out. The panel reads the app's kind
folders from its own storage.py, as it reads its provider and kind, and the
census here holds that reading to each app's AppSpec.

Every folder is a throwaway one under tmp_path, and every name is invented.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
gui = pytest.importorskip("app")

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(p.parent for p in (REPO / "apps").glob("*/storage.py"))
PDF = b"%PDF-1.4\n" + b"0" * 4000 + b"\n%%EOF\n"
STORAGE = '''SPEC = AppSpec(
    provider="Utilico",
    kind=DOCUMENT,
    folders=[
        Folder("statements", "Statements"),
        Folder("other_documents", "Other Documents", precreate=False),
        *INFRASTRUCTURE_FOLDERS,
    ],
)
'''


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    d = tmp_path / "Utilico Statements"
    d.mkdir()
    (d / "storage.py").write_text(STORAGE, encoding="utf-8")
    out, docs = tmp_path / "out", tmp_path / "Watched"
    files = {"kind_in_docs": docs / "Statements" / "2026" / "2026-01-31 Statement.pdf",
             "other_in_docs": docs / "Other Documents" / "2026-02-01 Notice.pdf",
             "flat": docs / "2026" / "2026-03-31 Statement.pdf",
             "out": out / "Statements" / "2026-04-30 Statement.pdf",
             "aside": out / "Manual Review" / "2026-05-31 Statement.pdf"}
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF)
    (out / "progress.json").write_text(json.dumps({
        key: {"state": "Completed", "downloaded_ok": True, "pdf_path": str(path)}
        for key, path in files.items()}), encoding="utf-8")
    meta = {"dir": str(d), "name": d.name, "accounts": ["primary"]}

    def config(**more):
        (d / "config.json").write_text(json.dumps(dict(
            {"output_dir": str(out), "documents_dir": str(docs)}, **more)), encoding="utf-8")
    return meta, config


def test_without_kind_folders_a_document_in_a_kind_folder_of_the_documents_folder_is_left(
        install):
    meta, config = install
    config(kind_folders=False)
    # Watched/Statements/2026, Watched/Other Documents and out/Statements,
    # and never Watched/2026, where a pattern's folder holds one already
    # out, nor Manual Review.
    assert gui._documents_left(meta, "primary") == 3


@pytest.mark.parametrize("given", [None, True, "false", 0])
def test_with_kind_folders_only_what_is_outside_the_documents_folder_is_left(install, given):
    """The control, as the count always was, and a setting a run refuses
    changes nothing here."""
    meta, config = install
    config(**({} if given is None else {"kind_folders": given}))
    assert gui._documents_left(meta, "primary") == 1


def test_the_page_says_where_they_are(install):
    meta, config = install
    config(kind_folders=False)
    answer = gui._documents_answer(meta, "primary", Path(gui._account_root(meta, "primary")),
                                   apps={})
    assert answer["left"] == 3 and answer["kind_folders"] is False
    config()
    answer = gui._documents_answer(meta, "primary", Path(gui._account_root(meta, "primary")),
                                   apps={})
    assert answer["kind_folders"] is True


@pytest.mark.parametrize("app", APPS, ids=[a.name for a in APPS])
def test_the_panel_reads_each_apps_kind_folders_as_its_spec_declares_them(app, monkeypatch):
    core = str(REPO / "core")
    if core not in sys.path:
        monkeypatch.syspath_prepend(core)
    from paperpull_core import storage as core_storage
    from paperpull_core.spec import INFRASTRUCTURE_FOLDERS
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    found = importlib.util.spec_from_file_location("_panel_kinds_of_%s" % app.name,
                                                   app / "storage.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    kept = {f.attr for f in INFRASTRUCTURE_FOLDERS}
    declared = [f.name for f in module.SPEC.folders if f.attr not in kept]
    assert gui._kind_folder_names(app) == declared


def test_a_document_in_a_patterns_folder_named_like_a_kind_folder_is_not_left(tmp_path,
                                                                               monkeypatch):
    """{type} is Online or In-Store, the names of a receipts app's kind
    folders, and an {account} may be anything. A document its pattern put
    in Watched/Statements is where it belongs, and the Move leaves it, so
    counting it offered a Move that never ends (review of #217)."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    d = tmp_path / "Utilico Statements"
    d.mkdir()
    (d / "storage.py").write_text(STORAGE, encoding="utf-8")
    out, docs = tmp_path / "out", tmp_path / "Watched"
    placed = docs / "Statements" / "2026-09-12 Monthly Statement.pdf"
    stray = docs / "Statements" / "Savings 2222" / "2026-09-12 Monthly Statement.pdf"
    for path in (placed, stray):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF)
    out.mkdir()
    (out / "progress.json").write_text(json.dumps({
        account: {"state": "Completed", "downloaded_ok": True, "pdf_path": str(path),
                  "date": "2026-09-12", "summary": "Monthly Statement", "account": account,
                  "category": "Statement"}
        for account, path in (("Statements", placed), ("Savings 2222", stray))}),
        encoding="utf-8")
    (d / "config.json").write_text(json.dumps({
        "output_dir": str(out), "documents_dir": str(docs), "kind_folders": False,
        "filename_pattern": "{account}/{date} {summary}"}), encoding="utf-8")
    meta = {"dir": str(d), "name": d.name, "accounts": ["primary"]}
    # Savings 2222 belongs in Watched/Savings 2222, so it is still left.
    assert gui._documents_left(meta, "primary") == 1


def test_an_earlier_documents_folder_filed_flat_is_left_as_a_whole(tmp_path, monkeypatch):
    """Without kind folders, documents in a documents folder used before
    and filed the same way move to the new one whole (core
    Paths.documents_moves), a document at its top too."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    d = tmp_path / "Utilico Statements"
    d.mkdir()
    (d / "storage.py").write_text(STORAGE, encoding="utf-8")
    out, old, docs = tmp_path / "out", tmp_path / "Old", tmp_path / "Watched"
    files = [old / "2026" / "2026-01-31 Statement.pdf", old / "2026-02-28 Statement.pdf"]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PDF)
    out.mkdir()
    (out / "progress.json").write_text(json.dumps({
        str(n): {"state": "Completed", "downloaded_ok": True, "pdf_path": str(path)}
        for n, path in enumerate(files)}), encoding="utf-8")
    (out / "documents-folders.json").write_text(json.dumps([str(old)]), encoding="utf-8")
    (out / "documents-folders-flat.json").write_text(json.dumps([str(old)]), encoding="utf-8")
    (d / "config.json").write_text(json.dumps({
        "output_dir": str(out), "documents_dir": str(docs), "kind_folders": False}),
        encoding="utf-8")
    meta = {"dir": str(d), "name": d.name, "accounts": ["primary"]}
    assert gui._documents_left(meta, "primary") == 2
