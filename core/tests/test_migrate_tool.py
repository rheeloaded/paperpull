"""Moving a download history to another computer.

The point of this tool is narrow and worth stating. A fresh install on a new
machine must skip everything the old one already downloaded, WITHOUT copying a
single PDF across. If it re-fetches, the tool has failed, and the way it would
fail is quiet, because a re-download looks exactly like a first download.
"""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
migrate = pytest.importorskip("migrate")

TERMINAL = "Completed"


def _install(root: Path, folder: str, provider: str, records: dict, kind="DOCUMENT"):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "storage.py").write_text(
        'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind),
        encoding="utf-8")
    (d / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    return d


def _rec(state=TERMINAL, ok=True, path=""):
    return {"state": state, "downloaded_ok": ok, "pdf_path": path,
            "summary": "Statement", "date": "2026-01-31"}


# -- the whole point ---------------------------------------------------------

def test_a_fresh_install_skips_everything_the_old_one_had(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": _rec(), "id:2": _rec(), "id:3": _rec()})
    archive = tmp_path / "history.ppz"
    assert migrate.export(old, archive) == 0

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    assert migrate.do_import(archive, new, assume_yes=True) == 0

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert len(got) == 3
    assert all(r["downloaded_ok"] for r in got.values())


def test_a_record_without_the_marker_still_skips_on_its_state(tmp_path):
    """Most records predate downloaded_ok and are skipped on a terminal state
    alone. Carrying only the marker would silently re-download those."""
    old = tmp_path / "old"
    recs = {"id:1": {"state": TERMINAL, "pdf_path": "", "summary": "S"}}
    _install(old, "Bank Statements", "Bank", recs)
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert got["id:1"]["state"] == TERMINAL


# -- never lose anything -----------------------------------------------------

def test_an_import_never_downgrades_a_finished_document(tmp_path):
    """A stale export must not un-finish something the target already did."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": {"state": "Failed", "downloaded_ok": False, "pdf_path": ""}})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {"id:1": _rec()})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert got["id:1"]["downloaded_ok"] is True
    assert got["id:1"]["state"] == TERMINAL


def test_an_import_never_removes_a_record_the_target_already_had(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {"id:9": _rec()})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert set(got) == {"id:1", "id:9"}


def test_importing_twice_changes_nothing_the_second_time(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec(), "id:2": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)
    first = (new / "Bank Statements" / "progress.json").read_text(encoding="utf-8")
    migrate.do_import(archive, new, assume_yes=True)
    assert (new / "Bank Statements" / "progress.json").read_text(encoding="utf-8") == first


def test_the_previous_history_is_backed_up_before_anything_is_written(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    inst = _install(new, "Bank Statements", "Bank", {"id:9": _rec()})
    migrate.do_import(archive, new, assume_yes=True)
    assert list((inst / "Backups").glob("progress.*.before-import.bak"))


# -- paths name a machine ----------------------------------------------------

def test_an_absolute_path_is_moved_to_this_machine(tmp_path):
    old = tmp_path / "old"
    old_pdf = str(old / "Bank Statements" / "Statements" / "a.pdf")
    _install(old, "Bank Statements", "Bank", {"id:1": _rec(path=old_pdf)})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    p = got["id:1"]["pdf_path"]
    assert str(new) in p and str(old) not in p


def test_a_relative_path_is_left_exactly_as_it_was(tmp_path):
    """Apps disagree on this. Chase and myPay record a path relative to their
    own folder, which is already portable. Clearing those threw away real
    information for no reason."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": _rec(path="Statements\\2026-01-31 Statement.pdf")})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert got["id:1"]["pdf_path"] == "Statements\\2026-01-31 Statement.pdf"


def test_a_windows_path_is_recognised_as_absolute_on_any_platform(tmp_path):
    """An export written on Windows can be imported on a Mac, where a
    drive-letter path would otherwise look relative and be kept as-is."""
    assert migrate._is_absolute(r"C:\Users\someone\Statements\a.pdf")
    assert migrate._is_absolute("/Users/someone/Statements/a.pdf")
    assert not migrate._is_absolute(r"Statements\a.pdf")
    assert not migrate._is_absolute("Statements/a.pdf")
    assert not migrate._is_absolute("")


def test_a_foreign_absolute_path_is_cleared_rather_than_believed(tmp_path):
    """The skip logic asks whether a review copy is still on disk. A path from
    somewhere unrelated would answer that wrongly, so it is cleared."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": _rec(path=r"D:\SomewhereElse\a.pdf")})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert got["id:1"]["pdf_path"] == ""


# -- matching installs -------------------------------------------------------

def test_an_install_is_matched_by_provider_even_if_the_folder_was_renamed(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "My Bank Docs", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "My Bank Docs" / "progress.json").read_text(encoding="utf-8"))
    assert "id:1" in got


def test_a_provider_not_installed_here_is_skipped_not_invented(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    _install(old, "Other Statements", "Other", {"id:2": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    assert not (new / "Other Statements").exists()


# -- the file itself ---------------------------------------------------------

def test_a_dry_run_writes_nothing(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, dry_run=True, assume_yes=True)

    assert json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8")) == {}


def test_minimal_leaves_the_revealing_fields_out(tmp_path):
    """--minimal exists so the file can be moved around without carrying an
    itemised account of what somebody bought."""
    old = tmp_path / "old"
    rec = _rec()
    rec.update({"title": "Dr Smith visit", "account": "CHECKING *1234",
                "total": "412.55", "items": "two things", "store_info": "Main St"})
    _install(old, "Bank Statements", "Bank", {"id:1": rec})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive, minimal=True)

    with zipfile.ZipFile(archive) as z:
        blob = z.read("apps/Bank Statements/progress.json").decode("utf-8")
    for leak in ("Dr Smith", "CHECKING *1234", "412.55", "two things", "Main St"):
        assert leak not in blob, leak
    assert json.loads(blob)["id:1"]["downloaded_ok"] is True


def test_minimal_still_carries_enough_to_skip(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec(), "id:2": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive, minimal=True)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert len(got) == 2
    assert all(r["downloaded_ok"] for r in got.values())


def test_the_export_carries_no_password_cookie_or_token(tmp_path):
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        # The bundled README says in prose that the file holds no password,
        # so scanning it for the word "password" proves nothing. Only the
        # DATA is searched.
        data = [n for n in names if n.endswith(".json")]
        blob = " ".join(z.read(n).decode("utf-8", "ignore") for n in data).lower()
    assert not any(n.lower().endswith(("cookies", "local state", "login data")) for n in names)
    for word in ("password", "bearer ", "set-cookie", "authorization"):
        assert word not in blob, word


def test_a_file_that_is_not_an_export_is_refused(tmp_path):
    junk = tmp_path / "notreally.ppz"
    junk.write_text("hello", encoding="utf-8")
    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    assert migrate.do_import(junk, new, assume_yes=True) == 1


def test_an_export_from_a_future_version_is_refused_rather_than_guessed(tmp_path):
    archive = tmp_path / "h.ppz"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps({"schema": 999, "apps": []}))
    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank", {})
    assert migrate.do_import(archive, new, assume_yes=True) == 1


def test_minimal_does_not_pretend_to_be_anonymous(tmp_path):
    """It removes the bulk, not everything. The recorded filename stays, and
    filenames name accounts. Overstating that would be worse than the leak,
    because somebody would move the file somewhere they should not."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": _rec(path="Statements\2026-08-18 Statement - FREEDOM (...0962).pdf")})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive, minimal=True)
    with zipfile.ZipFile(archive) as z:
        blob = z.read("apps/Bank Statements/progress.json").decode("utf-8")
    assert "FREEDOM" in blob
    doc = migrate.__doc__ or ""
    assert "not an anonymous one" in doc, \
        "the docstring must say plainly what --minimal does not remove"
