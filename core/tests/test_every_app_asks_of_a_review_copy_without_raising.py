"""Asking whether a copy set aside for review is still there never ends a run.

Every app's _already_done asks of a record put aside for review whether its
copy is still on disk and still a PDF, and fetches the document again when
it is not. It asked with Path(p).exists(), outside any try. Python 3.12,
which every build ships, re-raises from exists() an error other than "not
there", so a record naming a file in a folder the run may not search, a
share whose permissions a person changed, ended the run at that document
on every run, and validate_pdf, which Verify asks, did the same with its
own exists() and stat(). A path that is not text, a number or a list a hand
edit or a damaged file left, raised TypeError in the same line on every
system (a bug hunt of 2026-11-14).

A copy that cannot be asked about counts as not there now, so the document
is fetched again, as a deleted copy is, and a path that is not text names
nothing. The refusal is stood in for at os.stat, which Path.exists and
Path.stat both reach, so a fix of one and not the other still fails here.
Each app is built from its own code as at home (census.Home).
"""
import errno
import os
import sys
from pathlib import Path

import pytest

from paperpull_core import receipt_pdf, testkit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402

REVIEW = "Manual Review"


def refuse_under(monkeypatch, folder: Path) -> None:
    """os.stat and os.lstat refuse any path under folder, as a folder the
    run may not search refuses, and answer as ever for any other."""
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


def test_validate_pdf_never_raises_for_a_file_it_cannot_ask_about(tmp_path, monkeypatch):
    folder = tmp_path / REVIEW
    folder.mkdir()
    pdf = folder / "x.pdf"
    pdf.write_bytes(testkit.sample_pdf())
    refuse_under(monkeypatch, folder)
    said = receipt_pdf.validate_pdf(pdf, 1000)
    assert not said.ok
    assert "read" in said.reason.lower() and "does not exist" not in said.reason


def test_validate_pdf_still_says_a_missing_file_does_not_exist(tmp_path):
    assert receipt_pdf.validate_pdf(tmp_path / "gone.pdf", 1000).reason == "File does not exist"


def test_validate_pdf_says_a_name_no_file_can_have_does_not_exist(tmp_path):
    """What 3.12's exists() answered False for without raising, a path it
    cannot encode and, on Windows, a name Windows will not hold, Verify
    still says does not exist."""
    assert receipt_pdf.validate_pdf(tmp_path / "a\0b.pdf", 1000).reason == "File does not exist"
    if os.name == "nt":
        assert receipt_pdf.validate_pdf(tmp_path / "a<b.pdf", 1000).reason == \
            "File does not exist"


class _Any:
    """A document or a purchase, whatever an app's _already_done reads of
    it, with the key the record is kept under."""

    key = "census:1"

    def __getattr__(self, name):
        return ""


def _apps_that_ask():
    return [d for d in census.APPS if d.name != "sample"]


@pytest.fixture(params=_apps_that_ask(), ids=[d.name for d in _apps_that_ask()])
def app(request, tmp_path, monkeypatch, capsys):
    home = census.Home(request.param, tmp_path, monkeypatch, capsys)
    built = home.build()
    if not hasattr(built, "_already_done"):
        pytest.skip("this app keeps no review copy to ask about")
    if hasattr(built, "args"):
        monkeypatch.setattr(built.args, "redownload", False, raising=False)
    return built


def asked(app, monkeypatch, rec) -> bool:
    monkeypatch.setattr(app.progress, "get", lambda key: rec)
    return app._already_done(_Any())


def test_every_app_counts_a_copy_it_cannot_ask_about_as_not_there(app, monkeypatch, tmp_path):
    folder = tmp_path / "refused" / REVIEW
    folder.mkdir(parents=True)
    pdf = folder / "2026-05-14 Statement.pdf"
    pdf.write_bytes(testkit.sample_pdf())
    refuse_under(monkeypatch, folder)
    rec = {"state": "Needs Manual Review", "downloaded_ok": False, "pdf_path": str(pdf)}
    assert asked(app, monkeypatch, rec) is False


@pytest.mark.parametrize("named", [5, ["x"], {"k": "v"}, 2.5], ids=["number", "list", "map", "float"])
def test_every_app_reads_a_path_that_is_not_text_as_none(app, monkeypatch, named):
    rec = {"state": "Needs Manual Review", "downloaded_ok": False, "pdf_path": named}
    assert asked(app, monkeypatch, rec) is False


def test_every_app_answers_for_a_review_copy_as_before(app, monkeypatch, tmp_path):
    """What 40491dd7 answered for a review copy, kept. A copy still there
    and still a PDF keeps the document done, and none, a missing one or one
    too small asks for it again."""
    folder = tmp_path / REVIEW
    folder.mkdir()
    good = folder / "good.pdf"
    good.write_bytes(testkit.sample_pdf())
    small = folder / "small.pdf"
    small.write_bytes(b"%PDF-1.4 small")
    for path, done in (("", False), (str(folder / "gone.pdf"), False), (str(good), True),
                       (str(small), False), (str(folder), False)):
        rec = {"state": "Needs Manual Review", "downloaded_ok": False, "pdf_path": path}
        assert asked(app, monkeypatch, rec) is done, (app.__class__.__module__, path)
    missing = {"state": "Needs Manual Review", "downloaded_ok": False}
    assert asked(app, monkeypatch, missing) is False


def test_there_are_apps_to_ask():
    assert len(_apps_that_ask()) > 80
