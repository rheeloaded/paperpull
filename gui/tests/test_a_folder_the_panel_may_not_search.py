"""A record naming a file in a folder the panel may not search never fails
a page of the panel.

Python 3.12, which every build ships, raises from Path.is_file() for a file
in a folder the process may not search, a share whose permissions a person
changed. The Documents settings counted such a record's file with
is_file() outside any try and answered with a 500, and the page that lists
what an account set aside asked the same of its record's file (a bug hunt
of 2026-11-14). Such a file is not counted and not offered now. The
refusal is stood in for at os.stat and os.lstat, as in the core's
test_every_app_asks_of_a_review_copy_without_raising.py.
"""
import errno
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
gui = pytest.importorskip("app")


def refuse_under(monkeypatch, folder: Path) -> None:
    real_stat, real_lstat = os.stat, os.lstat
    inside = os.path.normcase(os.path.abspath(folder))

    def refused(real):
        def stat(path, *a, **k):
            if isinstance(path, (str, os.PathLike)):
                named = os.path.normcase(os.path.abspath(os.fspath(path)))
                if named == inside or named.startswith(inside + os.sep):
                    raise PermissionError(errno.EACCES, "Permission denied", os.fspath(path))
            return real(path, *a, **k)
        return stat
    monkeypatch.setattr(os, "stat", refused(real_stat))
    monkeypatch.setattr(os, "lstat", refused(real_lstat))


PDF = b"%PDF-1.4\n" + b"0" * 4000 + b"\n%%EOF\n"


@pytest.fixture
def account(tmp_path, monkeypatch):
    root = tmp_path / "acct"
    folder = root / "Statements" / "refused"
    folder.mkdir(parents=True)
    pdf = folder / "2025-12-31 Statement.pdf"
    pdf.write_bytes(PDF)
    plain = root / "Statements" / "2025-11-30 Statement.pdf"
    plain.write_bytes(PDF)
    (root / "progress.json").write_text(json.dumps({
        "a": {"state": "Completed", "downloaded_ok": True, "pdf_path": str(pdf)},
        "b": {"state": "Completed", "downloaded_ok": True, "pdf_path": str(plain)}}))
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(gui, "_account_root", lambda meta, acct: root)
    monkeypatch.setattr(gui, "_documents_of", lambda meta, acct: str(docs))
    monkeypatch.setattr(gui, "_documents_roots", lambda r: [])
    monkeypatch.setattr(gui, "_indexed_files", lambda r: None)
    return root, folder, pdf, plain


def test_the_documents_count_passes_over_a_file_it_cannot_look_at(account, monkeypatch):
    root, folder, _pdf, _plain = account
    assert gui._documents_left({}, "primary") == 2
    refuse_under(monkeypatch, folder)
    assert gui._documents_left({}, "primary") == 1


def test_a_set_aside_file_it_cannot_look_at_is_not_offered(account, monkeypatch):
    root, folder, pdf, plain = account
    assert gui._set_aside_file(root, {"pdf_path": str(pdf)}) == pdf
    refuse_under(monkeypatch, folder)
    assert gui._set_aside_file(root, {"pdf_path": str(pdf)}) is None
    assert gui._set_aside_file(root, {"pdf_path": str(plain)}) == plain
