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


def test_a_windows_path_is_recognized_as_absolute_on_any_platform(tmp_path):
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
    itemized account of what somebody bought."""
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


def test_the_plan_does_not_apply_itself(tmp_path, capsys):
    """dict(records) copies only the outer mapping, so the record objects were
    shared and the plan pass edited them in place. The apply pass that followed
    then found nothing left to do and reported zero changes against a plan that
    had just promised several."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": {"state": TERMINAL, "downloaded_ok": True, "pdf_path": ""}})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Bank Statements", "Bank",
             {"id:1": {"state": "Failed", "downloaded_ok": False, "pdf_path": ""}})

    capsys.readouterr()
    migrate.do_import(archive, new, assume_yes=True)
    lines = [l for l in capsys.readouterr().out.splitlines() if "marked done" in l]
    assert len(lines) == 2, lines
    planned = lines[0].split("new,")[1].split("marked")[0].strip()
    applied = lines[1].split("new,")[1].split("marked")[0].strip()
    assert planned == applied == "1", (planned, applied)


def test_a_dry_run_leaves_the_records_in_memory_alone(tmp_path):
    """It writes nothing to disk either way, but a preview that edits what it
    is previewing is a bug waiting to escape into the apply path."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank",
             {"id:1": {"state": TERMINAL, "downloaded_ok": True, "pdf_path": ""}})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    inst = _install(new, "Bank Statements", "Bank",
                    {"id:1": {"state": "Failed", "downloaded_ok": False, "pdf_path": ""}})
    before = (inst / "progress.json").read_text(encoding="utf-8")
    migrate.do_import(archive, new, dry_run=True, assume_yes=True)
    assert (inst / "progress.json").read_text(encoding="utf-8") == before


# -- a receipt an older version gave up on (#70) ------------------------------

def _gave_up(note="Kroger could not load this receipt"):
    """A record 0.44.0 left when the receipt page did not show the receipt.
    Its receipt is asked for again (paperpull_core.not_shown)."""
    return {"state": "No Receipt Available", "pdf_path": "", "summary": "Groceries",
            "notes": "Listed by an invented step; " + note}


def test_a_receipt_an_older_version_gave_up_on_is_still_asked_for_after_a_move(tmp_path):
    from paperpull_core.not_shown import asked_again
    for minimal in (False, True):
        old = tmp_path / ("old%d" % minimal)
        _install(old, "Kroger Receipts", "Kroger", {"k:1": _gave_up(), "k:2": _rec()},
                 kind="RECEIPT")
        archive = tmp_path / ("h%d.ppz" % minimal)
        migrate.export(old, archive, minimal=minimal)
        with zipfile.ZipFile(archive) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            blob = z.read("apps/Kroger Receipts/progress.json").decode("utf-8")
        assert manifest["apps"][0]["already_downloaded"] == 1, "it was never downloaded"
        if minimal:
            assert "invented step" not in blob, "only the fixed words travel"

        new = tmp_path / ("new%d" % minimal)
        _install(new, "Kroger Receipts", "Kroger", {}, kind="RECEIPT")
        migrate.do_import(archive, new, assume_yes=True)
        got = json.loads((new / "Kroger Receipts" / "progress.json").read_text(encoding="utf-8"))
        assert asked_again(got["k:1"]), (minimal, got["k:1"])
        assert not asked_again(got["k:2"])


def test_an_import_does_not_finish_a_receipt_this_install_asks_for_again(tmp_path):
    """This install recorded the receipt as tried again. An older export that
    gave up on it does not make it final, which would keep its notes, so
    nothing would ever ask for it again."""
    old = tmp_path / "old"
    _install(old, "Kroger Receipts", "Kroger", {"k:1": _gave_up()}, kind="RECEIPT")
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    tried = {"state": "Failed", "pdf_path": "",
             "notes": "Kroger could not load this receipt, tried again next run"}
    _install(new, "Kroger Receipts", "Kroger", {"k:1": tried}, kind="RECEIPT")
    migrate.do_import(archive, new, assume_yes=True)

    got = json.loads((new / "Kroger Receipts" / "progress.json").read_text(encoding="utf-8"))
    assert got["k:1"]["state"] == "Failed", got["k:1"]


def test_the_core_beside_the_tool_comes_before_an_older_one_installed(tmp_path):
    """An app's environment can hold an older core, one without the module
    this tool reads, and the tool then failed before it could say a word."""
    import subprocess
    old = tmp_path / "old-core" / "paperpull_core"
    old.mkdir(parents=True)
    (old / "__init__.py").write_text("", encoding="utf-8")
    tool = Path(__file__).resolve().parents[2] / "tools" / "migrate.py"
    env = dict(__import__("os").environ, PYTHONPATH=str(tmp_path / "old-core"))
    r = subprocess.run([sys.executable, str(tool), "--help"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr


# -- people and settings (#67) -------------------------------------------------
#
# Someone moving from the desktop app to PaperPull Server asked for their
# providers to come along as well as the history. A second person's folder
# sits beside the install with records and no app, and the first version of
# this tool exported it as a provider of its own, which no import could
# place. Settings did not come at all.

EXAMPLE = {"owner": "", "owner_in_filename": False, "output_dir": ".",
           "profile_dir": "./browser-profile", "browser": "auto",
           "cdp_url": "http://127.0.0.1:9236", "document_types": ["Statement"],
           "default_start_date": "", "min_pdf_bytes": 2000,
           "//refuse": "a comment, never a setting"}


def _app(root: Path, folder="Bank Statements", provider="Bank", records=None,
         config=None, people=None, kind="DOCUMENT"):
    """An install shaped like one the panel makes, its app script, spec,
    example and config, and a config.<label>.json with its own folder beside
    it for each person in people ({label: (config, records)})."""
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "bank_docs.py").write_text("# the app\n", encoding="utf-8")
    (d / "storage.py").write_text(
        'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind),
        encoding="utf-8")
    (d / "config.example.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    (d / "config.json").write_text(json.dumps(dict(EXAMPLE, **(config or {}))), encoding="utf-8")
    if records is not None:
        (d / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    for label, (cfg, recs) in (people or {}).items():
        out = "../%s - %s" % (folder, label)
        (d / ("config.%s.json" % label)).write_text(
            json.dumps(dict(EXAMPLE, output_dir=out, **cfg)), encoding="utf-8")
        (root / ("%s - %s" % (folder, label))).mkdir(exist_ok=True)
        if recs is not None:
            (root / ("%s - %s" % (folder, label)) / "progress.json").write_text(
                json.dumps(recs), encoding="utf-8")
    return d


def _manifest(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        return json.loads(z.read("manifest.json").decode("utf-8"))


def test_a_second_person_comes_across_as_that_person(tmp_path):
    old = tmp_path / "old"
    _app(old, records={"id:1": _rec()},
         people={"spouse": ({"owner": "Jamie Example"}, {"id:7": _rec(), "id:8": _rec()})})
    archive = tmp_path / "h.ppz"
    assert migrate.export(old, archive) == 0
    apps = _manifest(archive)["apps"]
    assert [(a["provider"], a["account"], a["records"]) for a in apps] == [
        ("Bank", "primary", 1), ("Bank", "spouse", 2)], "found once, through its config"

    new = tmp_path / "new"
    _app(new, records={}, people={"spouse": ({}, None)})
    assert migrate.do_import(archive, new, assume_yes=True) == 0
    first = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    second = json.loads((new / "Bank Statements - spouse" / "progress.json").read_text(encoding="utf-8"))
    assert set(first) == {"id:1"} and set(second) == {"id:7", "id:8"}, "nothing mixed"


def test_the_command_line_never_invents_a_person(tmp_path, capsys):
    old = tmp_path / "old"
    _app(old, records={"id:1": _rec()}, people={"spouse": ({}, {"id:7": _rec()})})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _app(new, records={})
    migrate.do_import(archive, new, assume_yes=True)
    assert not (new / "Bank Statements - spouse").exists()
    assert not (new / "Bank Statements" / "config.spouse.json").exists()
    out = capsys.readouterr().out
    assert "Bank (spouse)" in out and "NOT SET UP HERE" in out


def test_an_install_never_run_still_comes_across_with_its_settings(tmp_path):
    old = tmp_path / "old"
    _app(old, config={"owner": "Pat Example"})
    archive = tmp_path / "h.ppz"
    assert migrate.export(old, archive) == 0
    (entry,) = _manifest(archive)["apps"]
    assert entry["records"] == 0 and entry["settings"]["owner"] == "Pat Example"


def test_the_settings_a_person_chose_travel_and_this_computers_never_do(tmp_path):
    old = tmp_path / "old"
    _app(old, records={}, config={
        "owner": "Pat Example", "default_start_date": "2021-01-01",
        "document_types": ["Statement", "Tax Document"],
        "filename_pattern_statements": "{date} {provider}",
        "output_dir": r"D:\Archive\Bank", "profile_dir": r"D:\Profiles\Bank",
        "cdp_url": "http://127.0.0.1:9999", "browser": "installed",
        "a_key_no_example_lists": "kept home"})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)
    settings = _manifest(archive)["apps"][0]["settings"]
    assert settings["owner"] == "Pat Example"
    assert settings["default_start_date"] == "2021-01-01"
    assert settings["document_types"] == ["Statement", "Tax Document"]
    assert settings["filename_pattern_statements"] == "{date} {provider}"
    for key in ("output_dir", "profile_dir", "cdp_url", "browser", "//refuse",
                "a_key_no_example_lists"):
        assert key not in settings, key


def test_minimal_carries_no_settings(tmp_path):
    old = tmp_path / "old"
    _app(old, records={"id:1": _rec()}, config={"owner": "Pat Example"})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive, minimal=True)
    with zipfile.ZipFile(archive) as z:
        assert "Pat Example" not in z.read("manifest.json").decode("utf-8")


def test_only_what_the_install_knows_is_written_and_only_its_own_kind(tmp_path):
    """What an import writes into a config it made. A file is somebody's,
    and may have been edited, so nothing in it decides this computer's
    folders, profile, browser or port, and nothing changes a setting's kind."""
    inst = _app(tmp_path)
    got = migrate.settings_to_apply(inst, dict(EXAMPLE), {
        "output_dir": "/elsewhere", "profile_dir": "/elsewhere/p", "browser": "bundled",
        "cdp_url": "http://evil.example:1", "//refuse": "x", "not_a_setting": 1,
        "min_pdf_bytes": "lots", "owner_in_filename": 1, "document_types": "Statement",
        "default_start_date": "2020-01-01", "owner": "  " + "P" * 200,
        "max_path_length": 200, "filename_pattern": "{date}" * 2000})
    assert got == {"default_start_date": "2020-01-01", "owner": "P" * 80,
                   "max_path_length": 200}, got


def test_a_file_name_pattern_is_taken_only_once_it_is_checked(tmp_path):
    inst = _app(tmp_path)
    pattern = {"filename_pattern_statements": "{date} {provider}"}
    assert migrate.settings_to_apply(inst, dict(EXAMPLE), pattern) == {}, \
        "with nothing to check it, none is taken"
    assert migrate.settings_to_apply(inst, dict(EXAMPLE), pattern,
                                     check_pattern=lambda p: "a problem") == {}
    assert migrate.settings_to_apply(inst, dict(EXAMPLE), pattern,
                                     check_pattern=lambda p: None) == pattern


UKG = Path(__file__).resolve().parents[2] / "apps" / "ukg"


def _ukg(tmp_path):
    """An install of the real UKG app, copied as the panel copies it."""
    import shutil
    inst = tmp_path / "UKG Pay Stubs"
    shutil.copytree(UKG, inst, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (inst / "config.json").write_text((inst / "config.example.json").read_text(encoding="utf-8"),
                                      encoding="utf-8")
    return inst


def test_an_address_from_a_file_is_written_only_on_the_providers_own_site(tmp_path):
    """UKG's base_url is where its sign-in window opens, the last thing on
    the browser's command line. A history file from another computer
    carried --no-sandbox into it, which the browser took as a switch (a
    private report of 2026-11-10). It is held to UKG's own domains, as
    PaperPull Server holds it before every run, and the rest of the file's
    settings still come across."""
    inst = _ukg(tmp_path)
    cfg = json.loads((inst / "config.json").read_text(encoding="utf-8"))
    for value in ("--no-sandbox", "https://attacker.example", "https://yourhost/wfc/",
                  "http://example.ultipro.com", "https://example.ultipro.com@evil.example",
                  "https://example.ultipro.com/c/hcm", "javascript:alert(1)"):
        left = []
        got = migrate.settings_to_apply(inst, dict(cfg), {"base_url": value, "owner": "Pat Example"},
                                        left_out=left)
        assert got == {"owner": "Pat Example"}, (value, got)
        assert left == ["base_url"], value
    for value in ("https://example.ultipro.com", "https://secure6.saashr.com/",
                  "https://REPLACE-ME.ultipro.com", ""):
        left = []
        got = migrate.settings_to_apply(inst, dict(cfg), {"base_url": value}, left_out=left)
        assert got == {"base_url": value} and left == [], value
    # Not the kind the install's own setting is, as before.
    assert migrate.settings_to_apply(inst, dict(cfg), {"base_url": 7}) == {}


def test_an_apps_addresses_are_read_from_its_code_without_running_it(tmp_path):
    """Running storage.py binds the core to that app for the whole process,
    and the panel imports every provider's history in one."""
    from paperpull_core import storage as core_storage
    before = core_storage._SPEC
    assert migrate.url_settings_of(_ukg(tmp_path)) == {"base_url": ("ultipro.com", "saashr.com")}
    assert core_storage._SPEC is before
    assert migrate.url_settings_of(_app(tmp_path)) == {}


def test_an_app_whose_addresses_cannot_be_read_takes_no_address_from_a_file(tmp_path):
    inst = _ukg(tmp_path)
    (inst / "storage.py").write_text("SPEC = AppSpec(url_settings=WHERE)\n", encoding="utf-8")
    assert migrate.url_settings_of(inst) is None
    left = []
    got = migrate.settings_to_apply(inst, json.loads((inst / "config.json").read_text(encoding="utf-8")),
                                    {"base_url": "https://example.ultipro.com", "owner": "Pat"},
                                    left_out=left)
    assert got == {"owner": "Pat"} and left == ["base_url"]
    (inst / "storage.py").unlink()
    assert migrate.url_settings_of(inst) is None


def test_every_other_providers_settings_come_across_as_before(tmp_path):
    """No app but UKG holds an address, so nothing of theirs is left out."""
    inst = _app(tmp_path)
    left = []
    got = migrate.settings_to_apply(inst, dict(EXAMPLE), {"default_start_date": "2020-01-01",
                                                          "owner": "Pat"}, left_out=left)
    assert got == {"default_start_date": "2020-01-01", "owner": "Pat"} and left == []


def test_a_first_persons_folder_is_never_taken_for_the_start_of_a_seconds():
    """The first version compared the start of a path with the folder and no
    separator, so a path in "Bank Statements - spouse" was taken for one in
    "Bank Statements" and moved to a folder named " - spouse" inside it."""
    new = Path("/data/Bank Statements")
    old = r"C:\Users\someone\PaperPull\Bank Statements - spouse\Statements\a.pdf"
    assert migrate._rewrite_path(old, [r"C:\Users\someone\PaperPull\Bank Statements"], new) == ""
    moved = migrate._rewrite_path(
        old, [r"C:\Users\someone\PaperPull\Bank Statements - spouse"], new)
    assert Path(moved) == new / "Statements" / "a.pdf"


def test_a_path_moved_out_of_the_old_folder_never_leads_back_out_of_the_new_one(tmp_path):
    new = tmp_path / "new" / "Bank Statements"
    base = "/Users/someone/PaperPull/Bank Statements"
    assert migrate._rewrite_path(base + "/../../../etc/passwd", [base], new) == ""
    assert Path(migrate._rewrite_path(base + "/Statements/../a.pdf", [base], new)) == new / "a.pdf"
    assert migrate._rewrite_path("Statements/a.pdf", [base], new) == "Statements/a.pdf"


def test_a_second_persons_relative_paths_are_kept_as_the_app_wrote_them(tmp_path):
    """A second person's folder sits beside the install a run starts in, so
    every path their runs record begins with "..". Cleared, Target took a
    saved invoice with no path for one never saved and fetched it again."""
    rel = r"..\Target Receipts - spouse\Invoices\a.pdf"
    old = tmp_path / "old"
    rec = _rec(path=rel)
    rec["invoices"] = [{"file": rel, "kept": True}]
    _install(old, "Target Receipts - spouse", "Target Receipts - spouse", {"T:1": rec})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Target Receipts - spouse", "Target Receipts - spouse", {})
    migrate.do_import(archive, new, assume_yes=True)
    got = json.loads((new / "Target Receipts - spouse" / "progress.json").read_text(encoding="utf-8"))
    assert got["T:1"]["pdf_path"] == rel
    assert got["T:1"]["invoices"] == [{"file": rel, "kept": True}]


def test_a_newer_file_is_never_matched_by_a_folder_name_alone(tmp_path):
    """Two people's output folders can share a name, and a folder can hold
    another provider's history. A file that says whose each history is was
    folded into whichever folder here had the same name."""
    def install(root, provider, out, people=()):
        d = root / ("%s Statements" % provider)
        d.mkdir(parents=True)
        (d / "x_docs.py").write_text("", encoding="utf-8")
        (d / "storage.py").write_text('SPEC = AppSpec(provider="%s", kind=DOCUMENT)' % provider,
                                      encoding="utf-8")
        (d / "config.json").write_text(json.dumps({"output_dir": str(out)}), encoding="utf-8")
        for label, where in people:
            (d / ("config.%s.json" % label)).write_text(
                json.dumps({"output_dir": str(where)}), encoding="utf-8")
        return d

    def history(where, recs):
        where.mkdir(parents=True, exist_ok=True)
        (where / "progress.json").write_text(json.dumps(recs), encoding="utf-8")

    old, new = tmp_path / "old", tmp_path / "new"
    install(old, "Bank", tmp_path / "o" / "Pat" / "Bank",
            people=[("jamie", tmp_path / "o" / "Jamie" / "Bank")])
    install(old, "Amex", tmp_path / "o" / "Amex" / "Statements")
    history(tmp_path / "o" / "Pat" / "Bank", {"pat:1": _rec()})
    history(tmp_path / "o" / "Jamie" / "Bank", {"jamie:1": _rec()})
    history(tmp_path / "o" / "Amex" / "Statements", {"amex:1": _rec()})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    install(new, "Bank", tmp_path / "n" / "Pat" / "Bank")
    install(new, "Discover", tmp_path / "n" / "Discover" / "Statements")
    history(tmp_path / "n" / "Pat" / "Bank", {})
    history(tmp_path / "n" / "Discover" / "Statements", {})
    migrate.do_import(archive, new, assume_yes=True)
    read = lambda p: set(json.loads((p / "progress.json").read_text(encoding="utf-8")))
    assert read(tmp_path / "n" / "Pat" / "Bank") == {"pat:1"}
    assert read(tmp_path / "n" / "Discover" / "Statements") == set()


def test_a_file_from_before_people_were_told_apart_finds_a_persons_folder_by_name(tmp_path):
    """Version 1 exported a second person's folder as a provider named for
    the folder, and found it again here only by that name."""
    archive = tmp_path / "old.ppz"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "schema": 1, "source_root": "/old",
            "apps": [{"folder": "Bank Statements - spouse", "provider": "Bank Statements - spouse",
                      "kind": None, "records": 1, "already_downloaded": 1}]}))
        z.writestr("apps/Bank Statements - spouse/progress.json", json.dumps({"id:7": _rec()}))
    new = tmp_path / "new"
    _app(new, records={}, people={"spouse": ({}, {})})
    migrate.do_import(archive, new, assume_yes=True)
    got = json.loads((new / "Bank Statements - spouse" / "progress.json").read_text(encoding="utf-8"))
    assert set(got) == {"id:7"}


def test_an_orders_invoices_follow_it_to_the_new_computer(tmp_path):
    """Target keeps a file for each invoice of an order. A saved invoice
    counts as saved whether its file is there or not, so one from another
    folder of that machine keeps its path, and one that would lead out of
    the order's folder is cleared."""
    old = tmp_path / "old"
    folder = old / "Target Receipts"
    rec = _rec(path=str(folder / "Invoices" / "a.pdf"))
    rec["invoices"] = [{"file": str(folder / "Invoices" / "a.pdf"), "kept": True},
                       {"file": r"Z:\Elsewhere\b.pdf", "kept": True},
                       {"file": str(folder) + "/../../c.pdf", "kept": False},
                       {"part": "no file"}]
    _install(old, "Target Receipts", "Target", {"T:1": rec}, kind="RECEIPT")
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)

    new = tmp_path / "new"
    _install(new, "Target Receipts", "Target", {}, kind="RECEIPT")
    migrate.do_import(archive, new, assume_yes=True)
    got = json.loads((new / "Target Receipts" / "progress.json").read_text(encoding="utf-8"))
    files = [i.get("file") for i in got["T:1"]["invoices"]]
    assert Path(files[0]) == new / "Target Receipts" / "Invoices" / "a.pdf"
    assert files[1:] == [r"Z:\Elsewhere\b.pdf", "", None]


def test_a_file_from_before_people_were_told_apart_still_imports(tmp_path):
    """Schema 1, one entry per folder, as 0.46.0 and older wrote it."""
    archive = tmp_path / "old.ppz"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "schema": 1, "source_root": r"C:\Users\someone\PaperPull",
            "apps": [{"folder": "Bank Statements", "provider": "Bank", "kind": "DOCUMENT",
                      "records": 1, "already_downloaded": 1}]}))
        z.writestr("apps/Bank Statements/progress.json", json.dumps({"id:1": _rec(
            path=r"C:\Users\someone\PaperPull\Bank Statements\Statements\a.pdf")}))
    new = tmp_path / "new"
    _app(new, records={})
    assert migrate.do_import(archive, new, assume_yes=True) == 0
    got = json.loads((new / "Bank Statements" / "progress.json").read_text(encoding="utf-8"))
    assert got["id:1"]["downloaded_ok"] is True
    assert Path(got["id:1"]["pdf_path"]) == new / "Bank Statements" / "Statements" / "a.pdf"


def test_a_file_far_larger_than_any_history_is_not_read(tmp_path, monkeypatch):
    """A zip says how big each file in it is, and need not tell the truth.
    What is read stops at the limit, whatever it says."""
    old = tmp_path / "old"
    _install(old, "Bank Statements", "Bank", {"id:%d" % i: _rec() for i in range(50)})
    archive = tmp_path / "h.ppz"
    migrate.export(old, archive)
    monkeypatch.setattr(migrate, "MAX_RECORDS_BYTES", 200)
    with pytest.raises(migrate.NotAnExport):
        migrate.read(archive)
    monkeypatch.setattr(migrate, "MAX_RECORDS_BYTES", 10 ** 8)
    monkeypatch.setattr(migrate, "MAX_TOTAL_BYTES", 200)
    with pytest.raises(migrate.NotAnExport):
        migrate.read(archive.read_bytes())
    monkeypatch.setattr(migrate, "MAX_TOTAL_BYTES", 10 ** 8)
    monkeypatch.setattr(migrate, "MAX_RECORDS", 49)
    with pytest.raises(migrate.NotAnExport):
        migrate.read(archive)


def test_one_history_named_for_several_places_is_refused(tmp_path):
    """Each entry reads its own file, so entries that share one would read
    it again for each, every one inside the limits, and together far past
    them."""
    archive = tmp_path / "h.ppz"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps({"schema": 2, "apps": [
            {"provider": "Bank", "account": "primary", "file": "apps/0/progress.json"},
            {"provider": "Bank", "account": "spouse", "file": "apps/0/progress.json"}]}))
        z.writestr("apps/0/progress.json", json.dumps({"id:1": _rec()}))
    with pytest.raises(migrate.NotAnExport):
        migrate.read(archive)


@pytest.mark.parametrize("minimal", [False, True])
def test_chase_business_ids_never_leave_this_computer(tmp_path, minimal):
    """Chase Business records its account reference and documentId empty,
    since Chase mints both anew each sign-in. Neither field is in any
    export, full or --minimal, even on a record an earlier build wrote
    with them. A moved history still skips the statement, which its key
    says on its own, and a full export keeps the record's account_digest,
    which only Rename reads to tell two accounts' files apart."""
    ref, doc_id = "ACCTREFQX0042", "DOCIDQX987654"
    rec = _rec()
    rec.update({"account_ref": ref, "document_id": doc_id, "category": "Statement",
                "account": "Business Checking", "account_digest": "0a1b2c3d4e5f"})
    key = "id:Business Checking:2026-01-31:Statement:0a1b2c3d4e5f"
    old = tmp_path / "old"
    _install(old, "Chase Business Statements", "Chase Business", {key: rec})
    archive = tmp_path / "h.ppz"
    assert migrate.export(old, archive, minimal=minimal) == 0

    with zipfile.ZipFile(archive) as z:
        blob = b" ".join(z.read(n) for n in z.namelist()).decode("utf-8", "ignore")
    assert ref not in blob and doc_id not in blob
    assert "account_ref" not in blob and "document_id" not in blob

    new = tmp_path / "new"
    _install(new, "Chase Business Statements", "Chase Business", {})
    assert migrate.do_import(archive, new, assume_yes=True) == 0
    got = json.loads((new / "Chase Business Statements" / "progress.json")
                     .read_text(encoding="utf-8"))
    assert list(got) == [key] and got[key]["downloaded_ok"] is True
    if not minimal:
        assert got[key].get("account_digest") == "0a1b2c3d4e5f", \
            "a full export keeps the digest Rename reads"
