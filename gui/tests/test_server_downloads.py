"""What the desktop opens a folder for, PaperPull Server hands the browser.

Two places in the panel showed a folder on the desktop and nothing on the
server, whose folders are on the server and not on the computer the panel
is used from.

  A support report or a recording says to attach its file to an issue.
  /api/diagnostics/download gives the browser the survey Diagnose wrote,
  or the recording, from the last hour, the way the failure file is given.
  A screenshot is never among them, since it is a picture of the page.

  A run that sets documents aside says they are in the Manual Review
  folder. /api/aside/download gives the browser what is in it, as one zip.

On the server the data folder is usually a share others can write to, so
neither follows a link, and neither takes a path from the page, only the
app, the account and, for a report, which of the two. Both answer only on
the server. Every name here is invented.
"""
import asyncio
import io
import os
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]
PDF = b"%PDF-1.4\n% invented\n%%EOF\n"


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """A provider on the server with two people, each with a folder."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    install = tmp_path / "data" / "Shop Receipts"
    install.mkdir(parents=True)
    monkeypatch.setenv("APPS_ROOT", str(install.parent))
    (install / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    (install / "config.robin.json").write_text('{"output_dir": "robin"}', encoding="utf-8")
    meta = {"name": "Shop Receipts", "dir": str(install), "accounts": ["primary", "robin"]}
    monkeypatch.setattr(app_module, "discover_apps", lambda: {"Shop Receipts": meta})
    return install


def asked(fn, **query):
    """(status, response) for one call of a route."""
    try:
        return 200, fn(**query)
    except fastapi.HTTPException as e:
        return e.status_code, str(e.detail)


def named(response) -> str:
    """The file name the browser is told, in either of the forms it takes."""
    told = response.headers["content-disposition"]
    if "filename*=utf-8''" in told:
        return urllib.parse.unquote(told.split("filename*=utf-8''", 1)[1])
    return told.split('filename="', 1)[1].rstrip('"')


def body_of(response) -> bytes:
    """Everything a response sends, a whole one or one streamed."""
    if hasattr(response, "body_iterator"):
        async def read():
            return b"".join([part async for part in response.body_iterator])
        return asyncio.run(read())
    return response.body


def written(folder: Path, name: str, data: bytes = b"{}", age: float = 0) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    if age:
        then = time.time() - age
        os.utime(path, (then, then))
    return path


def can_link(tmp_path) -> bool:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path)
        return True
    except (OSError, NotImplementedError):
        return False


# -- a support report or a recording ------------------------------------------------

def test_the_newest_survey_from_the_last_hour_is_given(shop):
    diag = shop / "Diagnostics"
    written(diag, "survey-diagnose-20260101-090000.json", b'{"old": 1}', age=7200)
    written(diag, "survey-diagnose-20260101-100000.json", b'{"new": 1}')
    written(diag, "diagnose-documents.json", b'{"detailed": 1}')
    written(diag, "diagnose-page.png", b"picture")
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        action="diagnose")
    assert status == 200, got
    assert named(got) == "survey-diagnose-20260101-100000.json"
    assert body_of(got) == b'{"new": 1}'


def test_a_recording_from_the_last_hour_is_given_and_an_older_one_is_not(shop):
    diag = shop / "Diagnostics"
    written(diag, "recording.json", b'{"steps": []}')
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        action="record")
    assert status == 200 and named(got) == "recording.json"
    written(diag, "recording.json", b'{"steps": []}', age=7200)
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      action="record")
    assert status == 404


def test_a_second_persons_report_is_their_own(shop):
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json", b'{"first": 1}')
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      account="robin", action="diagnose")
    assert status == 404, "the first person's survey is not the second's"
    written(shop / "robin" / "Diagnostics", "survey-diagnose-20260101-100000.json",
            b'{"robin": 1}')
    status, got = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                        account="robin", action="diagnose")
    assert status == 200 and body_of(got) == b'{"robin": 1}'


@pytest.mark.parametrize("query,code", [
    ({"app": "Shop Receipts", "action": "screenshot"}, 400),
    ({"app": "Shop Receipts", "action": ""}, 400),
    ({"app": "Nobody", "action": "diagnose"}, 404),
    ({"app": "Shop Receipts", "account": "stranger", "action": "diagnose"}, 404),
])
def test_a_report_asked_wrongly_is_refused(shop, query, code):
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json")
    assert asked(app_module.api_diagnostics_download, **query)[0] == code


def test_a_linked_survey_is_not_given(shop, tmp_path):
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles", "Cookies", b"signed in")
    (shop / "Diagnostics").mkdir()
    (shop / "Diagnostics" / "survey-diagnose-20260101-100000.json").symlink_to(secret)
    status, _ = asked(app_module.api_diagnostics_download, app="Shop Receipts",
                      action="diagnose")
    assert status == 404


# -- what was set aside --------------------------------------------------------------

def test_what_was_set_aside_comes_as_one_zip(shop, tmp_path, monkeypatch):
    aside = shop / "Manual Review"
    written(aside, "2026-05-14 Shop Unsure Receipt.pdf", PDF)
    written(aside / "Invoices", "2026-05-14 Shop Invoice (1 of 2).pdf", PDF + b"2")
    written(aside, ".2026-05-14 Shop Half.pdf.part", b"half")
    written(shop / "Online", "2026-05-14 Shop Filed Receipt.pdf", PDF)
    # Nothing of it is left on disk, since the zip is a file of no name.
    monkeypatch.setattr(app_module.tempfile, "tempdir", str(tmp_path / "temp"))
    (tmp_path / "temp").mkdir()
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200, got
    assert got.media_type == "application/zip"
    assert named(got) == "Shop Receipts set aside.zip"
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert sorted(z.namelist()) == [
            "Manual Review/2026-05-14 Shop Unsure Receipt.pdf",
            "Manual Review/Invoices/2026-05-14 Shop Invoice (1 of 2).pdf"]
        assert z.read("Manual Review/2026-05-14 Shop Unsure Receipt.pdf") == PDF
    assert list((tmp_path / "temp").iterdir()) == []


def test_nothing_set_aside_is_said(shop):
    (shop / "Manual Review").mkdir()
    status, detail = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 404 and detail == "Nothing is set aside for this account now."


def test_a_second_persons_set_aside_is_their_own(shop):
    written(shop / "Manual Review", "first.pdf", PDF)
    written(shop / "robin" / "Manual Review", "robin.pdf", PDF)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts", account="robin")
    assert status == 200
    assert named(got) == "Shop Receipts robin set aside.zip"
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/robin.pdf"]


def test_links_in_the_set_aside_folder_are_left_out(shop, tmp_path):
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles" / "Default", "Cookies", b"signed in")
    aside = shop / "Manual Review"
    written(aside, "real.pdf", PDF)
    (aside / "cookies.pdf").symlink_to(secret)
    (aside / "profile").symlink_to(secret.parent, target_is_directory=True)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/real.pdf"]
        assert all(b"signed in" not in z.read(n) for n in z.namelist())


@pytest.mark.parametrize("query", [{"app": "Nobody"},
                                   {"app": "Shop Receipts", "account": "stranger"}])
def test_set_aside_asked_wrongly_is_refused(shop, query):
    written(shop / "Manual Review", "real.pdf", PDF)
    assert asked(app_module.api_aside_download, **query)[0] == 404


# -- only the server -----------------------------------------------------------------

def test_neither_answers_on_the_desktop(shop, monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER")
    written(shop / "Diagnostics", "survey-diagnose-20260101-100000.json")
    written(shop / "Manual Review", "real.pdf", PDF)
    assert asked(app_module.api_diagnostics_download, app="Shop Receipts",
                 action="diagnose")[0] == 404
    assert asked(app_module.api_aside_download, app="Shop Receipts")[0] == 404


def test_the_page_offers_them_on_the_server_and_a_folder_on_the_desktop():
    script = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "(SERVER ? '<button type=\"button\" class=\"btn btn-s\" data-do=\"report-download\"" in script
    assert "const aside = SERVER && o.aside;" in script
    assert "const folder = !SERVER && !inSample() && (o.aside || !o.names);" in script
    assert "'/api/diagnostics/download?'" in script and "'/api/aside/download?'" in script


def test_the_page_never_goes_to_a_download_of_its_own_api():
    """Each download is asked for first (fetchDownload), so a refusal is
    said in the panel. Sent to the address, a refused spreadsheet Download
    replaced the panel with the refusal's JSON and dropped a run streaming
    on that page (the release review of 0.57.1)."""
    import re
    script = (REPO / "gui" / "static" / "app.js").read_text(encoding="utf-8")
    went = re.findall(r"(?:location(?:\.href)?\s*=|location\.(?:assign|replace)\(|window\.open\()"
                      r"\s*['\"`]/api/", script)
    assert went == [], went
    assert "await fetchDownload('/api/export/download')" in script
    assert "await fetchDownload('/api/failure/download?'" in script


# -- what the review of the first version found -----------------------------------

def test_a_manual_review_folder_that_is_a_link_holds_nothing(shop, tmp_path):
    """A share writer swaps the folder itself for a link to a signed-in
    profile. Every file under it resolves inside the folder's own target,
    so a check against that target let them all through."""
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles" / "Default", "Cookies", b"signed in")
    (shop / "Manual Review").symlink_to(secret.parent, target_is_directory=True)
    status, detail = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 404, detail


def test_a_diagnostics_folder_that_is_a_link_hands_nothing_over(shop, tmp_path):
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    elsewhere = tmp_path / "profiles" / "Default"
    written(elsewhere, "survey-diagnose-20260101-100000.json", b"signed in")
    written(elsewhere, "failure-run-20260101-100000.json", b"signed in")
    (shop / "Diagnostics").symlink_to(elsewhere, target_is_directory=True)
    assert asked(app_module.api_diagnostics_download, app="Shop Receipts",
                 action="diagnose")[0] == 404
    assert asked(app_module.api_failure_download, app="Shop Receipts")[0] == 404


def test_a_file_with_a_second_hard_link_is_left_out(shop, tmp_path):
    """A hard link reads as a plain file, and could be a second name of a
    file elsewhere on the same disk."""
    outside = written(tmp_path / "profiles", "Cookies", b"signed in")
    aside = shop / "Manual Review"
    written(aside, "real.pdf", PDF)
    try:
        os.link(outside, aside / "cookies.pdf")
    except OSError:
        pytest.skip("this system makes no hard link here")
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/real.pdf"]


def test_an_account_whose_folder_is_outside_the_data_folder_hands_nothing(shop, tmp_path,
                                                                           monkeypatch):
    monkeypatch.setenv("APPS_ROOT", str(shop.parent))
    away = tmp_path / "away"
    written(away / "Manual Review", "real.pdf", PDF)
    written(away / "Diagnostics", "survey-diagnose-20260101-100000.json")
    (shop / "config.json").write_text('{"output_dir": "%s"}' % away.as_posix(), encoding="utf-8")
    assert asked(app_module.api_aside_download, app="Shop Receipts")[0] == 404
    assert asked(app_module.api_diagnostics_download, app="Shop Receipts",
                 action="diagnose")[0] == 404
    (shop / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    written(shop / "Manual Review", "real.pdf", PDF)
    assert asked(app_module.api_aside_download, app="Shop Receipts")[0] == 200


def test_the_failure_file_is_handed_over_from_its_checked_open(shop):
    written(shop / "Diagnostics", "failure-run-20260101-100000.json", b'{"step": "a step"}')
    status, got = asked(app_module.api_failure_download, app="Shop Receipts")
    assert status == 200
    assert named(got) == "failure-run-20260101-100000.json"
    assert body_of(got) == b'{"step": "a step"}'


def test_a_file_swapped_for_a_link_after_the_list_is_not_read(shop, tmp_path, monkeypatch):
    """The walk lists a real file, and a share writer swaps it for a link
    before it is read. What is read is what the checked open reached."""
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles", "Cookies", b"signed in")
    aside = shop / "Manual Review"
    real = written(aside, "real.pdf", PDF)
    swapped = written(aside, "swapped.pdf", PDF)
    listed = app_module._set_aside

    def then_swap(meta, account):
        out = listed(meta, account)
        swapped.unlink()
        swapped.symlink_to(secret)
        return out
    monkeypatch.setattr(app_module, "_set_aside", then_swap)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/real.pdf"]
        assert z.read("Manual Review/real.pdf") == real.read_bytes()


def test_a_file_swapped_after_its_check_is_still_read_from_the_checked_open(
        shop, tmp_path, monkeypatch):
    """The window the first version left wide, between the check and the
    read. The file is swapped for a link the moment its check is done."""
    # The swap deletes a file the checked open still holds. Linux, where the
    # server runs, allows that. Windows refuses it (WinError 32 on CI, whose
    # runner makes links), so there the swap this guards against cannot
    # happen.
    if os.name == "nt":
        pytest.skip("Windows will not delete a file that is open")
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "profiles", "Cookies", b"signed in")
    real = written(shop / "Manual Review", "real.pdf", PDF)
    checked = app_module._open_plain

    def then_swap(path, inside):
        fd = checked(path, inside)
        Path(path).unlink()
        Path(path).symlink_to(secret)
        return fd
    monkeypatch.setattr(app_module, "_open_plain", then_swap)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.read("Manual Review/real.pdf") == PDF
    assert real.is_symlink()


# -- what the safety review of the fix found ---------------------------------------

def test_a_named_pipe_is_refused_without_waiting(shop):
    """Opening a pipe waits for a writer, which held the panel's thread for
    good. A pipe named like a failure file or a set-aside PDF is passed by."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("this system has no named pipes")
    import threading
    diag, aside = shop / "Diagnostics", shop / "Manual Review"
    diag.mkdir()
    os.mkfifo(diag / "failure-pilot-20260101-120000.json")
    written(aside, "real.pdf", PDF)
    os.mkfifo(aside / "pipe.pdf")
    got = {}

    def ask():
        got["failure"] = asked(app_module.api_failure_download, app="Shop Receipts")[0]
        status, response = asked(app_module.api_aside_download, app="Shop Receipts")
        with zipfile.ZipFile(io.BytesIO(body_of(response))) as z:
            got["zipped"] = z.namelist()
    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    worker.join(20)
    assert not worker.is_alive(), "a named pipe held the request"
    assert got == {"failure": 404, "zipped": ["Manual Review/real.pdf"]}


def test_a_file_dated_past_what_a_zip_holds_is_still_zipped(shop):
    path = written(shop / "Manual Review", "future.pdf", PDF)
    try:
        os.utime(path, (7258118400, 7258118400))        # the year 2200
    except (OSError, OverflowError, ValueError):
        pytest.skip("this system cannot date a file that far ahead")
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.getinfo("Manual Review/future.pdf").date_time[0] == 2107


def test_a_backslash_in_a_name_is_no_separator_in_the_zip(shop):
    if os.sep == "\\":
        pytest.skip("a Windows file name cannot hold a backslash")
    # A name starting with a dot is left out as hidden, so this one does not.
    written(shop / "Manual Review", "x\\..\\..\\evil.pdf", PDF)
    status, got = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body_of(got))) as z:
        assert z.namelist() == ["Manual Review/x_.._.._evil.pdf"]


def test_more_than_the_most_is_said_and_sends_nothing(shop, monkeypatch):
    monkeypatch.setattr(app_module, "ASIDE_MOST", len(PDF) + 1)
    written(shop / "Manual Review", "one.pdf", PDF)
    written(shop / "Manual Review", "two.pdf", PDF)
    status, detail = asked(app_module.api_aside_download, app="Shop Receipts")
    assert status == 413 and "Copy it from the Manual Review folder" in detail


# -- the spreadsheet an export wrote ------------------------------------------------
#
# /api/export/download hands over the file the last export wrote, beside the
# installs in the data folder. That folder is often a share others can write,
# so the name is checked again when it is downloaded, not only when the export
# ended. The server's settings in /config stand in for what a link could reach.

HISTORY = ("Purchase Date,Order or Receipt Number,Item Name,Quantity,Unit Price,"
           "Line Item Total,Order Total\n"
           "2026-05-14,1001,Invented Item,1,$5.00,$5.00,$5.00\n")
SETTINGS = b'{"password": "an invented secret"}'


class AskedToExport:
    """The page asking for every purchase, with nothing else in its body."""
    async def json(self):
        return {}


def sent(got) -> bytes:
    """What the browser would get, from a refusal, a response, or the file
    a file response names, read the way it reads it."""
    if isinstance(got, str):
        return got.encode()
    if hasattr(got, "path"):
        return Path(got.path).read_bytes()
    return body_of(got)


def exported(shop, monkeypatch) -> Path:
    """The spreadsheet a real export of purchases writes, from one invented
    order history, which is the file the panel then hands over."""
    monkeypatch.setattr(app_module, "_LAST_EXPORT", None)
    (shop / "Shop Order History.csv").write_text(HISTORY, encoding="utf-8")
    result = asyncio.run(app_module.api_export(AskedToExport()))
    assert result["ok"], result
    sheet = Path(result["path"])
    assert sheet.parent == shop.parent and app_module._LAST_EXPORT == sheet
    return sheet


def test_the_spreadsheet_an_export_wrote_is_handed_over_as_before(shop, monkeypatch):
    """What the page gets for a spreadsheet nobody touched, the name, type,
    size and bytes the file response it used to send gave."""
    from fastapi.responses import FileResponse
    sheet = exported(shop, monkeypatch)
    status, got = asked(app_module.api_export_download)
    assert status == 200, got
    before = FileResponse(sheet, filename=sheet.name)
    assert got.media_type == before.media_type
    assert got.headers["content-disposition"] == before.headers["content-disposition"]
    assert named(got) == "All Purchases.xlsx"
    assert got.headers["content-length"] == str(sheet.stat().st_size)
    assert body_of(got) == sheet.read_bytes()


def test_a_spreadsheet_swapped_for_a_link_after_the_export_is_not_handed_over(
        shop, tmp_path, monkeypatch):
    """A share writer swaps the spreadsheet for a link to the server's own
    settings between the export and the download. The file response the
    download used followed it."""
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "config", "server.json", SETTINGS)
    sheet = exported(shop, monkeypatch)
    sheet.unlink()
    sheet.symlink_to(secret)
    status, got = asked(app_module.api_export_download)
    assert SETTINGS not in sent(got)
    assert status == 404


def test_a_spreadsheet_swapped_for_a_hard_link_after_the_export_is_not_handed_over(
        shop, tmp_path, monkeypatch):
    """A hard link reads as a plain file, and could be a second name of the
    server's settings on the same disk."""
    secret = written(tmp_path / "config", "server.json", SETTINGS)
    sheet = exported(shop, monkeypatch)
    sheet.unlink()
    try:
        os.link(secret, sheet)
    except OSError:
        pytest.skip("this system makes no hard link here")
    status, got = asked(app_module.api_export_download)
    assert SETTINGS not in sent(got)
    assert status == 404


def test_a_spreadsheet_outside_the_folder_the_export_was_given_is_not_handed_over(
        shop, tmp_path, monkeypatch):
    """Both exports write only into the folder the panel names, so a file
    anywhere else is none of theirs."""
    secret = written(tmp_path / "config", "server.json", SETTINGS)
    monkeypatch.setattr(app_module, "_LAST_EXPORT", secret)
    status, got = asked(app_module.api_export_download)
    assert SETTINGS not in sent(got)
    assert status == 404


def test_a_spreadsheet_in_an_apps_root_outside_the_data_folder_is_not_handed_over(
        shop, tmp_path, monkeypatch):
    """On the server the folder it sits in has to be inside the data folder
    too, as for every other file the panel hands over."""
    sheet = exported(shop, monkeypatch)
    away = tmp_path / "config"
    away.mkdir()
    moved = away / sheet.name
    sheet.replace(moved)
    monkeypatch.setattr(app_module, "apps_root", lambda: away)
    monkeypatch.setattr(app_module, "_LAST_EXPORT", moved)
    assert asked(app_module.api_export_download)[0] == 404


def test_a_spreadsheet_that_grows_while_it_is_sent_is_sent_at_the_length_it_was_told(
        shop, monkeypatch):
    """A share writer adding to it after it was opened. The browser was told
    its length then, and a response longer than that is cut off unfinished."""
    sheet = exported(shop, monkeypatch)
    real = sheet.read_bytes()
    status, got = asked(app_module.api_export_download)
    assert status == 200, got
    with open(sheet, "ab") as more:
        more.write(b"added since")
    assert body_of(got) == real
    assert got.headers["content-length"] == str(len(real))


def test_a_spreadsheet_that_is_gone_says_nothing_was_exported(shop, monkeypatch):
    exported(shop, monkeypatch).unlink()
    assert asked(app_module.api_export_download) == (404, "Create the file first.")


def test_a_spreadsheet_swapped_after_its_check_is_still_read_from_the_checked_open(
        shop, tmp_path, monkeypatch):
    """The window a check by name leaves, between the check and the read.
    The spreadsheet is swapped for a link the moment its check is done."""
    # Windows will not delete a file that is open, so there this swap
    # cannot happen (see the set-aside test above).
    if os.name == "nt":
        pytest.skip("Windows will not delete a file that is open")
    if not can_link(tmp_path):
        pytest.skip("this system makes no symbolic links for an ordinary user")
    secret = written(tmp_path / "config", "server.json", SETTINGS)
    sheet = exported(shop, monkeypatch)
    real = sheet.read_bytes()
    checked = app_module._open_plain

    def then_swap(path, inside):
        fd = checked(path, inside)
        Path(path).unlink()
        Path(path).symlink_to(secret)
        return fd
    monkeypatch.setattr(app_module, "_open_plain", then_swap)
    status, got = asked(app_module.api_export_download)
    assert status == 200, got
    assert body_of(got) == real
    assert sheet.is_symlink()
