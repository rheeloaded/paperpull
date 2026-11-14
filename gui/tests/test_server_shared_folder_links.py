"""What the panel reads and writes in PaperPull Server's shared folder goes
through no link someone left there, and waits on no pipe.

Someone who can write to the data folder can leave a link at a name the
panel reads or writes. A read through it showed or copied what it led to,
the server's own password file among the places, and a write through it
landed there. Setting a provider up copied the example config into the
share and then made config.json from that copy, so two links in a timed
race wrote a password record of somebody else's choosing into server.json
(a private report of 2026-11-10). A named pipe left there held the panel's
thread for good.

A hard link stands in on Windows for a link at a file's name, as in
core/tests/test_server_output_links.py. A symbolic link and a named pipe
are tried where the system has them, and are skipped with the reason on
Windows, where these run under WSL instead.
"""
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import server_mode  # noqa: E402

MARKER = "MARKER-7f3a"
POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"
EXAMPLE = {"owner": "", "output_dir": ".", "profile_dir": "./browser-profile",
           "browser": "auto", "cdp_url": "http://127.0.0.1:9236", "min_pdf_bytes": 2000}


@pytest.fixture()
def server(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    outside = tmp_path / "config"
    outside.mkdir()
    canary = outside / "server.json"
    canary.write_bytes(json.dumps({"owner": MARKER, "password": {"salt": MARKER}}).encode())
    root = tmp_path / "templates" / "apps"
    d = root / "bank"
    d.mkdir(parents=True)
    (d / "bank_docs.py").write_text("# the app\n", encoding="utf-8")
    (d / "storage.py").write_text('SPEC = AppSpec(\n    provider="Bank",\n    kind=DOCUMENT,\n)\n',
                                  encoding="utf-8")
    (d / "config.example.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    monkeypatch.setattr(app_module, "_templates_root", lambda: root)
    monkeypatch.setattr(app_module, "_provider_notes", lambda: {})
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_CONFIG", str(outside))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    return SimpleNamespace(data=data, canary=canary, before=canary.read_bytes(), template=d)


def untouched(place) -> bool:
    return place.canary.read_bytes() == place.before


def fifo_or_skip(at: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip(POSIX_ONLY)
    os.mkfifo(at)


def within(seconds, fn, *args):
    got = {}

    def run():
        try:
            got["value"] = fn(*args)
        except BaseException as e:  # noqa: BLE001
            got["error"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "still waiting after %s s" % seconds
    return got


# -- setting a provider up --------------------------------------------------------------

class ShareWriter:
    """Someone on the share who wins the race. Each time the panel opens a
    file of the install it just made to read it, its copy of the example
    config among them, the file is swapped first for a second name of the
    server's password file. Python's own audit hook sees every open before
    it happens, whatever the code that asks for it, so this does not depend
    on how the panel is written."""

    active = None

    def __init__(self, folder: Path, canary: Path):
        self.folder, self.canary, self.swapped = folder.resolve(), canary, []
        if not getattr(ShareWriter, "_hooked", False):
            sys.addaudithook(ShareWriter._hook)
            ShareWriter._hooked = True

    @staticmethod
    def _hook(event, args):
        me = ShareWriter.active
        if me is None or event != "open" or not args or not isinstance(args[0], (str, Path)):
            return
        path = Path(args[0])
        mode, flags = (args[1] if len(args) > 1 else None), (args[2] if len(args) > 2 else 0)
        reading = (mode is not None and "r" in str(mode) and "+" not in str(mode)) or \
                  (mode is None and isinstance(flags, int) and not flags & (os.O_WRONLY | os.O_RDWR))
        if not reading or path.name != "config.example.json":
            return
        try:
            if path.resolve().parent != me.folder:
                return
        except OSError:
            return
        ShareWriter.active = None
        try:
            spare = path.with_name(".swap")
            os.link(me.canary, spare)
            os.replace(spare, path)
            me.swapped.append(str(path))
        finally:
            ShareWriter.active = me


def test_setting_a_provider_up_never_makes_its_config_from_the_shares_copy(server):
    dst = server.data / "Bank Statements"
    writer = ShareWriter(dst, server.canary)
    ShareWriter.active = writer
    try:
        assert app_module.create_install(server.data, "bank") == "created"
    finally:
        ShareWriter.active = None
    made = json.loads((dst / "config.json").read_text(encoding="utf-8"))
    assert MARKER not in json.dumps(made), "config.json was made from the link"
    assert made["output_dir"] == "." and made["min_pdf_bytes"] == 2000
    assert untouched(server)


def test_setting_a_provider_up_writes_through_no_link_left_in_its_folder(server, monkeypatch):
    """Each file is written as a new one of its own, so a second name of the
    password file left at config.json is replaced, never written."""
    dst = server.data / "Bank Statements"
    real = app_module._make_folder

    def made_then_planted(folder):
        real(folder)
        if Path(folder) == dst and not (dst / "config.json").exists():
            os.link(server.canary, dst / "config.json")
    monkeypatch.setattr(app_module, "_make_folder", made_then_planted)
    assert app_module.create_install(server.data, "bank") == "created"
    assert untouched(server)
    assert os.stat(dst / "config.json").st_nlink == 1


# -- what the panel reads ---------------------------------------------------------------

def test_a_config_left_as_a_link_is_never_read(server):
    install = server.data / "Bank Statements"
    install.mkdir()
    os.link(server.canary, install / "config.json")
    assert app_module._read_json(install / "config.json") is None


def test_the_list_of_a_runs_new_files_is_never_read_through_a_link(server, monkeypatch):
    """The list names a document that is there, so read through the link it
    would be shown on the page and handed to the plug-ins."""
    root = server.data / "Bank Statements"
    (root / "Statements").mkdir(parents=True)
    (root / "Statements" / ("%s.pdf" % MARKER)).write_bytes(b"%PDF-1.4")
    server.canary.write_text("Statements/%s.pdf\n" % MARKER, encoding="utf-8")
    os.link(server.canary, root / "new-this-run.txt")
    assert app_module._saved_this_run(root, 0) == []
    monkeypatch.setattr(server_mode, "output_root", lambda install, account: root)
    assert server_mode.new_files(root, "primary", 0) == []


def test_a_copy_is_never_read_through_a_link_nor_written_through_one(server):
    src, dst = server.data / "src.txt", server.data / "dst.txt"
    os.link(server.canary, src)
    with pytest.raises(OSError):
        app_module._copy_file(src, dst)
    src.unlink()
    src.write_bytes(b"its own")
    os.utime(src, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    os.link(server.canary, dst)
    app_module._copy_file(src, dst)
    assert untouched(server) and dst.read_bytes() == b"its own"
    assert os.stat(dst).st_mtime_ns == os.stat(src).st_mtime_ns


def test_on_the_desktop_a_copy_is_as_before(server, monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER")
    src, dst = server.data / "src.txt", server.data / "dst.txt"
    src.write_bytes(b"its own")
    app_module._copy_file(src, dst)
    assert dst.read_bytes() == b"its own"


def test_a_spreadsheet_refused_for_a_link_is_said_and_the_panel_goes_on(server):
    """The export runs inside the panel, and the core's refusal of a link
    is a SystemExit, which would have ended the panel itself."""
    shop = server.data / "Shop Receipts"
    shop.mkdir()
    (shop / "Shop Order History.csv").write_text(
        "Purchase Date,Order or Receipt Number,Item Name,Line Item Total\n2026-05-14,A1,A thing,4.00\n", encoding="utf-8")
    os.link(server.canary, server.data / "All Purchases.xlsx")

    class Req:
        async def json(self):
            return {}
    got = asyncio.run(app_module.api_export(Req()))
    assert got["ok"] is False and got["reason"]
    assert untouched(server)


@pytest.mark.parametrize("name", ["config.json", "progress.json", "new-this-run.txt"])
def test_a_pipe_in_the_shared_folder_never_holds_the_panel(server, name):
    root = server.data / "Bank Statements"
    root.mkdir()
    fifo_or_skip(root / name)
    if name == "config.json":
        within(3, app_module._read_json, root / "config.json")
    elif name == "progress.json":
        within(3, app_module._latest_saved, root)
    else:
        within(3, app_module._saved_this_run, root, 0)
        within(3, server_mode.new_files, root, "primary", 0)


def test_a_person_left_as_a_link_with_nothing_at_its_end_is_never_written_through(server):
    install = server.data / "Bank Statements"
    install.mkdir()
    (install / "config.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    dangling = server.canary.parent / "new.json"
    try:
        (install / "config.spouse.json").symlink_to(dangling)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let a test make a symbolic link")
    with pytest.raises(Exception):
        app_module._make_account(install, "spouse", "Jamie Example")
    assert not dangling.exists() or MARKER not in dangling.read_text(encoding="utf-8")


def test_a_removed_install_never_moves_into_a_link_at_its_dated_name(server):
    """Removed/<name> taken, the dated name was used unchecked, and anybody
    can guess it to the second."""
    removed = server.data / "Removed"
    removed.mkdir()
    (removed / "Bank Statements").mkdir()
    elsewhere = server.canary.parent / "elsewhere"
    elsewhere.mkdir()
    dated = removed / "Bank Statements (20261114-120000)"
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(elsewhere), str(dated))
    else:
        os.symlink(elsewhere, dated, target_is_directory=True)
    got = app_module._free_removed_name(removed, "Bank Statements", "20261114-120000",
                                        os.path.lexists)
    assert got == removed / "Bank Statements (20261114-120000 2)"
