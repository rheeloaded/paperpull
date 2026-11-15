"""A file another program holds open is never copied into place by a move.

On the desktop shared_folder.move was shutil.move, which copies and then
deletes whenever its rename fails. A fresh file a sync client or a backup
tool held open, as Windows lets them without delete sharing, was then
copied to its name and could not be taken away, so the app counted it not
moved and the next run saved it a second time (a release review of
2026-11-15). The desktop renames first now, and copies only to another
drive, which a rename cannot reach. Every value is invented.
"""
import errno
import os

import pytest

from paperpull_core import shared_folder


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(shared_folder, "on_server", lambda: False)


def held_open(monkeypatch, src):
    """The rename and the delete of src refused, as Windows refuses them
    for a file open without delete sharing."""
    real_replace, real_rename, real_unlink = os.replace, os.rename, os.unlink
    held = os.path.normcase(os.path.abspath(src))

    def ours(path):
        return os.path.normcase(os.path.abspath(os.fspath(path))) == held

    def replace(a, b, *k, **kw):
        if ours(a):
            raise PermissionError(errno.EACCES, "used by another process", os.fspath(a))
        return real_replace(a, b, *k, **kw)

    def rename(a, b, *k, **kw):
        if ours(a):
            raise PermissionError(errno.EACCES, "used by another process", os.fspath(a))
        return real_rename(a, b, *k, **kw)

    def unlink(path, *k, **kw):
        if ours(path):
            raise PermissionError(errno.EACCES, "used by another process", os.fspath(path))
        return real_unlink(path, *k, **kw)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "remove", unlink)


def test_a_file_held_open_is_not_copied_into_place(desktop, tmp_path, monkeypatch):
    src = tmp_path / ".invoice-2.pdf.delivering"
    src.write_bytes(b"%PDF-1.4 invented")
    dst = tmp_path / "2026-09-12 Invoice (2 of 3).pdf"
    held_open(monkeypatch, src)
    with pytest.raises(OSError):
        shared_folder.move(src, dst)
    assert not dst.exists(), "a copy was left at the name, which nothing records"
    assert src.read_bytes() == b"%PDF-1.4 invented"


def test_a_plain_move_on_one_drive_renames(desktop, tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4 a")
    dst = tmp_path / "sub" / "b.pdf"
    dst.parent.mkdir()
    shared_folder.move(src, dst)
    assert dst.read_bytes() == b"%PDF-1.4 a" and not src.exists()


def test_a_move_to_another_drive_still_copies(desktop, tmp_path, monkeypatch):
    """A rename to another drive fails with EXDEV, which Python gives for
    Windows' "cannot move the file to a different disk drive" as well."""
    error = OSError(errno.EXDEV, "Invalid cross-device link")
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4 a")
    dst = tmp_path / "b.pdf"
    real_replace = os.replace
    asked = []

    def replace(a, b, *k, **kw):
        if os.fspath(a) == os.fspath(src) and not asked:
            asked.append(True)
            raise error
        return real_replace(a, b, *k, **kw)

    monkeypatch.setattr(os, "replace", replace)
    shared_folder.move(src, dst)
    assert asked and dst.read_bytes() == b"%PDF-1.4 a" and not src.exists()
