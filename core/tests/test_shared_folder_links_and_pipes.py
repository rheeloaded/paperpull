"""What the core and the tools read and write in PaperPull Server's shared
folder goes through no link someone left there, and waits on no pipe.

Someone who can write to the data folder can leave a link at a name a run
or the panel will read or write, and a write through it lands on the
server's own password file or a signed-in profile, while a read through it
copies what it leads to into a spreadsheet or the records (a private report
of 2026-11-10). A named pipe left there holds whatever opens it for good.

As in test_server_output_links.py, a hard link stands in on Windows for a
link at a file's name, since Windows gives an ordinary user no symbolic
links, and the same rule refuses both. A real symbolic link and a named
pipe are tried where the system has them, and are skipped with the reason
on Windows, where these run under WSL instead.
"""
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from paperpull_core import pdf_reader, receipt_pdf, shared_folder, storage, testkit  # noqa: E402

CANARY = '{"password": {"salt": "MARKER-7f3a"}}\n'
POSIX_ONLY = "needs POSIX, run under WSL on its own Linux filesystem (not /mnt/c)"


@pytest.fixture()
def place(tmp_path, monkeypatch):
    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    outside = tmp_path / "config"
    outside.mkdir()
    canary = outside / "server.json"
    canary.write_bytes(CANARY.encode("utf-8"))
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.chdir(install)
    return SimpleNamespace(data=data, install=install, canary=canary, outside=outside)


@pytest.fixture()
def server(place, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    return place


@pytest.fixture()
def desktop(place, monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    return place


def untouched(place) -> bool:
    return place.canary.read_bytes() == CANARY.encode("utf-8")


def plant(place, at: Path) -> None:
    """A second name of the canary at `at`, the stand-in for a link."""
    os.link(place.canary, at)


def symlink_or_skip(target: Path, at: Path) -> None:
    try:
        at.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let a test make a symbolic link")


def fifo_or_skip(at: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip(POSIX_ONLY)
    os.mkfifo(at)


def within(seconds, fn, *args):
    """fn(*args) in a thread, failing if it is still waiting after seconds.
    What it raised or answered is handed back."""
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


# -- the reader -------------------------------------------------------------------------

def test_a_plain_file_is_read_on_either_edition(place, monkeypatch):
    f = place.install / "progress.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    for edition in ("", "1"):
        monkeypatch.setenv("PAPERPULL_SERVER", edition)
        assert shared_folder.read_text(f) == '{"a": 1}'


def test_on_the_server_a_second_name_of_another_file_is_never_read(server):
    plant(server, server.install / "progress.json")
    with pytest.raises(OSError):
        shared_folder.read_plain(server.install / "progress.json")


def test_on_the_desktop_a_link_the_person_made_is_read_as_before(desktop):
    plant(desktop, desktop.install / "progress.json")
    assert shared_folder.read_text(desktop.install / "progress.json") == CANARY


def test_on_the_server_a_symbolic_link_is_never_read(server):
    symlink_or_skip(server.canary, server.install / "progress.json")
    with pytest.raises(OSError):
        shared_folder.read_plain(server.install / "progress.json")


@pytest.mark.parametrize("edition", ["", "1"])
def test_a_named_pipe_is_never_waited_on(place, monkeypatch, edition):
    monkeypatch.setenv("PAPERPULL_SERVER", edition)
    fifo_or_skip(place.install / "progress.json")
    got = within(3, shared_folder.read_plain, place.install / "progress.json")
    assert isinstance(got.get("error"), OSError)


def test_a_pipe_left_after_the_look_never_holds_a_write_either(server, monkeypatch):
    """The open itself must not wait, since the look before it can be
    answered by a plain file that is swapped for a pipe in between."""
    at = server.install / "All Purchases.csv"
    fifo_or_skip(at)
    real = os.lstat
    plain = real(server.canary)
    monkeypatch.setattr(shared_folder.os, "lstat",
                        lambda p, *a, **k: plain if Path(p) == at else real(p, *a, **k))
    got = within(3, lambda: shared_folder.open_to_write(at, "w").close())
    assert got.get("error") is not None


# -- writing whole ----------------------------------------------------------------------

def test_a_whole_write_replaces_a_link_and_never_writes_through_it(server):
    at = server.install / ".transactions-cache.json"
    plant(server, at)
    shared_folder.write_whole(at, '{"version": 9}')
    assert untouched(server)
    assert at.read_text(encoding="utf-8") == '{"version": 9}' and os.stat(at).st_nlink == 1
    assert sorted(p.name for p in server.install.iterdir()) == [".transactions-cache.json"]


def test_a_whole_write_is_as_before_on_the_desktop(desktop):
    at = desktop.install / "a.txt"
    shared_folder.write_whole(at, b"bytes")
    shared_folder.write_whole(at, "text")
    assert at.read_text(encoding="utf-8") == "text"
    assert sorted(p.name for p in desktop.install.iterdir()) == ["a.txt"]


# -- the places a run, a tool or the panel read or write ---------------------------------

class _PrintedPage:
    """Enough of a page for print_page_to_pdf, its PDF made up."""

    def __init__(self):
        self.context = SimpleNamespace(new_cdp_session=lambda page: _Session())

    def evaluate(self, *_a, **_k):
        return "screen"

    def emulate_media(self, **_k):
        pass


class _Session:
    def send(self, method, params=None):
        return {"data": __import__("base64").b64encode(b"%PDF-1.4 printed").decode()}

    def detach(self):
        pass


def test_a_printed_page_is_never_written_through_a_link_at_its_staged_name(server):
    staged = server.install / "Statements" / "2026-05-14 Testco Statement.pdf.delivering"
    staged.parent.mkdir()
    plant(server, staged)
    with pytest.raises(SystemExit):
        receipt_pdf.print_page_to_pdf(_PrintedPage(), staged)
    assert untouched(server)


def test_a_trimmed_pdf_is_never_written_through_a_link_beside_it(server):
    """The trimmed copy was written beside the PDF under a fixed name first,
    which a link left there sent to the server's password file."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(testkit.text_pdf(["Invoice 12345"]))))
    writer.add_blank_page(width=612, height=792)
    pdf = server.install / "invoice.pdf"
    with open(pdf, "wb") as f:
        writer.write(f)
    plant(server, server.install / ("invoice.pdf" + pdf_reader.TRIMMING))
    reader = PdfReader(str(pdf))
    pdf_reader._trim(reader, len(reader.pages), str(pdf))
    assert untouched(server)
    assert len(PdfReader(str(pdf)).pages) == 1


def test_a_backup_left_as_a_link_is_never_read_as_the_records(server, monkeypatch):
    """Even when the look for a link is answered before it is left, as a
    share writer who wins the race arranges."""
    store = storage.JsonStore(server.install / "progress.json", server.install / "Backups")
    (server.install / "progress.json").write_text("{ broken", encoding="utf-8")
    (server.install / "Backups").mkdir()
    server.canary.write_text('{"k": {"state": "MARKER-7f3a"}}', encoding="utf-8")
    os.link(server.canary, server.install / "Backups" / "progress.20990101-000000.json.bak")
    monkeypatch.setattr(storage.shared_folder, "linked", lambda p: False)
    assert "MARKER-7f3a" not in json.dumps(store._recover_from_backup() or {})


def _shop_install(place):
    """One receipts install with an order history the purchases export reads."""
    shop = place.data / "Shop Receipts"
    shop.mkdir()
    (shop / "Shop Order History.csv").write_text(
        "Purchase Date,Order or Receipt Number,Item Name,Line Item Total\n2026-05-14,A1,A thing,4.00\n", encoding="utf-8")
    return shop


def test_the_purchases_spreadsheet_is_never_written_through_a_link(server):
    import export_purchases
    _shop_install(server)
    plant(server, server.data / "All Purchases.xlsx")
    with pytest.raises(SystemExit):
        export_purchases.export(server.data, None, None, False)
    assert untouched(server)


def test_an_order_history_left_as_a_link_is_never_read_into_the_spreadsheet(server):
    import export_purchases
    shop = _shop_install(server)
    (shop / "Shop Order History.csv").unlink()
    server.canary.write_text("Purchase Date,Order or Receipt Number,Item Name,Line Item Total\n2026-01-01,MARKER-7f3a,"
                             "x,1.00\n", encoding="utf-8")
    plant(server, shop / "Shop Order History.csv")
    try:
        export_purchases.export(server.data, None, None, True)
    except (OSError, SystemExit):
        pass
    for made in server.data.glob("All Purchases.*"):
        assert "MARKER-7f3a" not in made.read_text(encoding="utf-8", errors="replace")


def test_an_order_history_that_is_a_pipe_never_holds_the_export(server):
    import export_purchases
    shop = _shop_install(server)
    (shop / "Shop Order History.csv").unlink()
    fifo_or_skip(shop / "Shop Order History.csv")
    within(3, export_purchases.export, server.data, None, None, True)


def test_the_transactions_cache_is_never_written_through_a_link(server):
    import export_transactions
    cache = export_transactions.Cache(server.data)
    cache.data, cache.dirty = {"x": 1}, True
    plant(server, server.data / ".transactions-cache.tmp")
    cache.save()
    assert untouched(server)
    assert json.loads((server.data / export_transactions.CACHE_NAME).read_text(encoding="utf-8"))


def test_the_spreadsheets_are_written_as_before_on_the_desktop(desktop):
    import export_purchases
    _shop_install(desktop)
    for as_csv in (False, True):
        made = export_purchases.export(desktop.data, None, None, as_csv)
        assert Path(made["path"]).is_file() and made["sources"]


def test_a_second_persons_config_is_never_written_through_a_link_at_its_name(server):
    import add_account
    install = server.data / "Bank Statements"
    install.mkdir()
    (install / "config.json").write_text(json.dumps({
        "owner": "Pat Example", "output_dir": ".", "profile_dir": "./browser-profile",
        "cdp_url": "http://127.0.0.1:9236"}), encoding="utf-8")
    dangling = server.outside / "new.json"
    symlink_or_skip(dangling, install / "config.spouse.json")
    add_account.make_config(install, "spouse", owner="Jamie Example", taken=set())
    assert not dangling.exists()
    assert json.loads((install / "config.spouse.json").read_text(encoding="utf-8"))["owner"] \
        == "Jamie Example"
    assert untouched(server)


# -- what Playwright and shutil write, and the status the panel reads ----------------

class _Download:
    """A finished download that writes the file it is handed the way
    Playwright's save_as does, with a plain open."""

    def __init__(self, data=b"%PDF-1.4 a statement"):
        self.data = data

    def path(self):
        return None

    def failure(self):
        return None

    def save_as(self, path):
        with open(path, "wb") as f:
            f.write(self.data)


def test_a_download_is_never_saved_through_a_link_beside_its_place(server, monkeypatch):
    """It was saved at a fixed name beside its place first, x.saving, which a
    link left there sent to the server's password file."""
    from paperpull_core import intake
    monkeypatch.setattr(intake, "finish", lambda download, partial=None: True)
    out = server.install / "Statements" / "2026-05-14 Testco Statement.pdf.delivering"
    out.parent.mkdir()
    plant(server, out.with_name(out.name + ".saving"))
    intake.save_download_as(_Download(), out)
    assert untouched(server)
    assert out.read_bytes() == b"%PDF-1.4 a statement"


def test_a_download_saved_where_a_link_was_left_replaces_the_link(server, monkeypatch):
    from paperpull_core import intake
    monkeypatch.setattr(intake, "finish", lambda download, partial=None: True)
    out = server.install / "2026-05-14 Testco Statement.pdf"
    plant(server, out)
    intake.save_download_as(_Download(), out)
    assert untouched(server) and out.read_bytes() == b"%PDF-1.4 a statement"
    assert os.stat(out).st_nlink == 1
    assert sorted(p.name for p in server.install.iterdir()) == [out.name]


class _Recorded(_Download):
    """A download that notes where it was asked to save."""

    def __init__(self, own=None):
        super().__init__()
        self.own, self.saved_at = own, []

    def path(self):
        return self.own

    def save_as(self, path):
        self.saved_at.append(Path(path))
        super().save_as(path)


@pytest.mark.parametrize("edition", ["", "1"])
def test_playwright_never_writes_into_the_folder_the_document_goes_to(place, monkeypatch,
                                                                     tmp_path, edition):
    """It writes the path it is handed with a plain open, through a link
    left there. Its own copy is copied into place, or one it saves in a
    private folder outside the share, and nothing is left beside the
    document."""
    from paperpull_core import intake
    monkeypatch.setenv("PAPERPULL_SERVER", edition)
    monkeypatch.setattr(intake, "finish", lambda download, partial=None: True)
    out = place.install / "2026-05-14 Testco Statement.pdf"
    remote = _Recorded()
    intake.save_download_as(remote, out)
    assert out.read_bytes() == b"%PDF-1.4 a statement"
    assert len(remote.saved_at) == 1
    assert place.data not in remote.saved_at[0].parents
    assert not remote.saved_at[0].parent.exists(), "its private folder was left"
    own = tmp_path / "playwright-artifacts" / "1234"
    own.parent.mkdir()
    own.write_bytes(b"%PDF-1.4 its own copy")
    local = _Recorded(str(own))
    intake.save_download_as(local, out)
    assert local.saved_at == [] and out.read_bytes() == b"%PDF-1.4 its own copy"
    assert sorted(p.name for p in place.install.iterdir()) == [out.name]


def _acl(path: Path) -> list:
    """What icacls says of a file's permissions, without its name."""
    import subprocess
    said = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                          check=True).stdout.splitlines()
    lines = [line.strip() for line in said if line.strip()
             and not line.startswith("Successfully processed")]
    return sorted([lines[0][len(str(path)):].strip()] + lines[1:])


def test_a_saved_document_takes_its_folders_own_permissions_on_windows(place, monkeypatch):
    """A document saved in a folder of 0700 mode took that folder's
    protected permissions on Windows, owner, SYSTEM and Administrators
    alone, and kept them once moved out (the review of 3eaaaccb). It is
    made in its own folder as any file is now."""
    if sys.platform != "win32":
        pytest.skip("Windows permissions, icacls")
    import subprocess
    from paperpull_core import intake
    monkeypatch.setattr(intake, "finish", lambda download, partial=None: True)
    # pytest's own temporary folders are the owner's alone, so the folder
    # is given what an ordinary one carries, Everyone may read, for the two
    # to be told apart.
    subprocess.run(["icacls", str(place.install), "/grant", "*S-1-1-0:(OI)(CI)(R)"],
                   capture_output=True, check=True)
    plain = place.install / "written plainly.pdf"
    plain.write_bytes(b"%PDF-1.4")
    assert any("Everyone" in line or "S-1-1-0" in line for line in _acl(plain))
    out = place.install / "2026-05-14 Testco Statement.pdf"
    intake.save_download_as(_Recorded(), out)
    assert _acl(out) == _acl(plain)


def test_on_the_server_a_download_is_never_saved_into_a_folder_that_leads_out(server,
                                                                             monkeypatch):
    from paperpull_core import intake
    monkeypatch.setattr(intake, "finish", lambda download, partial=None: True)
    elsewhere = server.outside / "profiles"
    elsewhere.mkdir()
    folder = server.install / "Statements"
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(elsewhere), str(folder))
    else:
        os.symlink(elsewhere, folder, target_is_directory=True)
    with pytest.raises(SystemExit):
        intake.save_download_as(_Recorded(), folder / "2026-05-14 Testco Statement.pdf")
    assert list(elsewhere.iterdir()) == []


class _PrintingPage:
    """A page whose pdf() writes a path it is handed the way Playwright
    does, with a plain open, and answers its bytes either way."""

    def emulate_media(self, **_k):
        pass

    def pdf(self, path=None, **_k):
        data = b"%PDF-1.4 printed"
        if path is not None:
            with open(path, "wb") as f:
                f.write(data)
        return data


def test_a_page_printed_headless_is_never_written_through_a_link(server):
    out = server.install / "2026-05-14 Shop Receipt.pdf"
    plant(server, out)
    with pytest.raises(SystemExit):
        receipt_pdf._print_checked(_PrintingPage(), out, lambda: None)
    assert untouched(server)


def test_a_page_printed_headless_is_written_as_before_on_the_desktop(desktop):
    out = desktop.install / "2026-05-14 Shop Receipt.pdf"
    receipt_pdf._print_checked(_PrintingPage(), out, lambda: None)
    assert out.read_bytes() == b"%PDF-1.4 printed"


def test_a_move_replaces_a_link_at_its_place_and_never_follows_it(server):
    src = server.install / "downloads" / "statement.pdf"
    src.parent.mkdir()
    src.write_bytes(b"%PDF-1.4 moved")
    dst = server.install / "2026-05-14 Testco Statement.pdf"
    plant(server, dst)
    shared_folder.move(src, dst)
    assert untouched(server) and dst.read_bytes() == b"%PDF-1.4 moved" and not src.exists()


def test_a_move_across_drives_is_written_whole_and_reads_no_link(server, monkeypatch):
    import errno
    src = server.install / "downloads" / "statement.pdf"
    src.parent.mkdir()
    src.write_bytes(b"%PDF-1.4 moved")
    dst = server.install / "2026-05-14 Testco Statement.pdf"
    plant(server, dst)
    real = os.replace

    def other_drive(a, b):
        if Path(a) == src:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(a, b)
    monkeypatch.setattr(shared_folder.os, "replace", other_drive)
    shared_folder.move(src, dst)
    assert untouched(server) and dst.read_bytes() == b"%PDF-1.4 moved" and not src.exists()
    os.link(server.canary, src)
    with pytest.raises(OSError):
        shared_folder.move(src, server.install / "another.pdf")
    assert not (server.install / "another.pdf").exists()


def test_a_move_onto_a_link_to_a_folder_never_moves_into_that_folder(server):
    """shutil.move moved a file into the folder a link at its place led to,
    the server's own settings folder among them."""
    src = server.install / "statement.pdf"
    src.write_bytes(b"%PDF-1.4 moved")
    dst = server.install / "2026-05-14 Testco Statement.pdf"
    symlink_or_skip(server.outside, dst)
    shared_folder.move(src, dst)
    assert sorted(p.name for p in server.outside.iterdir()) == ["server.json"]
    assert not dst.is_symlink() and dst.read_bytes() == b"%PDF-1.4 moved"


def test_a_link_is_never_moved_into_place_as_a_link(server):
    src = server.install / "statement.pdf"
    symlink_or_skip(server.canary, src)
    with pytest.raises(OSError):
        shared_folder.move(src, server.install / "kept.pdf")
    assert not os.path.lexists(server.install / "kept.pdf")


def test_a_second_name_of_another_file_is_never_moved_into_place(server):
    """The file moved has to be a plain file of its own, so a link left
    where a download arrives is never carried into the archive."""
    src = server.install / "statement.pdf"
    os.link(server.canary, src)
    with pytest.raises(OSError):
        shared_folder.move(src, server.install / "kept.pdf")
    assert not os.path.lexists(server.install / "kept.pdf") and untouched(server)


def test_a_move_on_the_desktop_is_shutils_as_before(desktop):
    src = desktop.install / "a.pdf"
    src.write_bytes(b"x")
    shared_folder.move(src, desktop.install / "b.pdf")
    assert (desktop.install / "b.pdf").read_bytes() == b"x" and not src.exists()


def test_the_status_the_panel_reads_for_every_account_never_goes_through_a_link(server):
    import status
    install = server.install
    (install / "storage.py").write_text('SPEC = AppSpec(provider="Testco", kind=DOCUMENT)\n',
                                        encoding="utf-8")
    server.canary.write_text('{"k": {"date": "2026-05-14", "downloaded_ok": true, '
                             '"title": "MARKER-7f3a"}}', encoding="utf-8")
    os.link(server.canary, install / "progress.json")
    assert status._read_json(install / "progress.json") == {}


def test_the_status_never_waits_on_a_pipe(server):
    import status
    fifo_or_skip(server.install / "progress.json")
    within(3, status.scan_install, server.install)


def test_an_archive_in_manual_review_left_as_a_link_is_never_taken_for_the_same_one(server):
    """A ZIP set aside is compared with the one already in Manual Review by
    that name, and the same one is not kept twice. A second name of a file
    outside the data folder, left at that name, was opened and compared, and
    when it held the same files the archive set aside was deleted and the
    record pointed at the link."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1099.pdf", b"%PDF-1.4 a form")
    data = buf.getvalue()
    review = server.install / "Manual Review"
    review.mkdir()
    server.canary.write_bytes(data)
    os.link(server.canary, review / "1099.zip")
    path = server.install / "1099.pdf"
    path.write_bytes(data)
    kept = receipt_pdf._set_aside(path, review)
    assert kept == review / "1099 (2).zip" and kept.read_bytes() == data
    assert server.canary.read_bytes() == data and os.stat(server.canary).st_nlink == 2
