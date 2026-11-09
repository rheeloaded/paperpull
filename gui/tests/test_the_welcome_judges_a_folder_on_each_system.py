"""What the welcome's first step says of a PaperPull folder, on Windows and
on a Mac.

The check asked os.access whether the folder could be written. On Windows
that reads only the read-only flag, which says nothing of a folder's own
rights, so it said yes to every folder, Program Files too, and a folder
PaperPull could not write was refused only at Set up, two steps on, as
before the check existed. Windows is asked now, by opening the folder for
the right to add a folder to it, which writes nothing. A first try made a
folder and took it away again, and the route census caught the check
changing the disk. And a folder was taken for Google Drive or iCloud
Drive by the start of its name alone, so "My Drivers" was warned of as
Google Drive's "My Drive".
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A private settings file, so tests never touch the real one, and an
    empty folder to type paths in."""
    p = tmp_path / "settings" / "settings.json"
    monkeypatch.setattr(app_module, "_settings_path", lambda: p)
    monkeypatch.delenv("APPS_ROOT", raising=False)
    box = tmp_path / "box"
    box.mkdir()
    return box


def test_where_windows_says_yes_to_every_folder_windows_is_asked_instead(box, monkeypatch):
    monkeypatch.setattr(app_module, "_ACCESS_SAYS_YES_TO_FOLDERS", True)
    asked = []

    def refused(folder):
        asked.append(folder)
        return False
    monkeypatch.setattr(app_module, "_windows_may_add_a_folder", refused)
    root, problem = app_module._root_problem(str(box / "Program Files" / "PaperPull"))
    assert root is None and "cannot write there" in problem
    # Of the nearest folder that is there, which is where setting up makes it.
    assert asked == [box]
    root, problem = app_module._root_problem(str(box))
    assert root is None and "cannot write there" in problem


def test_where_os_access_answers_windows_is_not_asked(box, monkeypatch):
    monkeypatch.setattr(app_module, "_ACCESS_SAYS_YES_TO_FOLDERS", False)

    def never(folder):
        raise AssertionError("Windows was asked where os.access answers")
    monkeypatch.setattr(app_module, "_windows_may_add_a_folder", never)
    assert app_module._root_problem(str(box / "PaperPull"))[1] == ""


@pytest.mark.skipif(sys.platform != "win32", reason="asks Windows itself")
def test_windows_answers_for_a_folder_of_ones_own_and_for_system32(box):
    """The real question, put to this computer. It changes nothing on disk,
    which the route census holds /api/root/check to as well."""
    import ctypes
    (box / "Documents").mkdir()
    assert app_module._windows_may_add_a_folder(box / "Documents")
    assert app_module._root_problem(str(box / "Documents" / "PaperPull")) == \
        (box / "Documents" / "PaperPull", "")
    assert sorted(p.name for p in box.rglob("*")) == ["Documents"], "nothing was made"
    # A person may make a folder at the top of the system drive and not a
    # file, so asked for the right to add a file it would be refused.
    drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
    assert app_module._windows_may_add_a_folder(drive), "a folder at the top of %s is fine" % drive
    if not ctypes.windll.shell32.IsUserAnAdmin():
        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        assert app_module._windows_may_add_a_folder(system32) is False
        assert "cannot write there" in app_module._root_problem(str(system32 / "PaperPull"))[1]
    assert app_module._windows_may_add_a_folder(box / "not there") is False


@pytest.mark.parametrize("parts, service", [
    (("C:\\", "Users", "me", "iCloudDrive", "PaperPull"), "iCloud Drive"),
    (("C:\\", "Users", "me", "OneDrive - Contoso", "PaperPull"), "OneDrive"),
    (("C:\\", "Users", "me", "Dropbox (Personal)", "PaperPull"), "Dropbox"),
    (("G:\\", "My Drive", "PaperPull"), "Google Drive"),
    (("C:\\", "Users", "me", "Google Drive", "PaperPull"), "Google Drive"),
    (("/", "Users", "me", "Library", "Mobile Documents", "com~apple~CloudDocs", "PaperPull"), "iCloud Drive"),
    (("/", "Users", "me", "Library", "CloudStorage", "GoogleDrive-me@example.com", "My Drive", "PaperPull"),
     "Google Drive"),
    (("D:\\", "My Drivers", "PaperPull"), ""),
    (("/", "Users", "me", "My Driveway Photos", "PaperPull"), ""),
    (("/", "Users", "me", "Mobile Documents Archive", "PaperPull"), ""),
    (("C:\\", "Users", "me", "Documents", "PaperPull"), ""),
    (("/", "Users", "me", "Documents", "PaperPull"), ""),
])
def test_a_sync_service_is_named_and_a_fine_folder_is_not(parts, service):
    class Typed:
        """A path as either system writes it, read part by part."""
        def __init__(self, parts):
            self.parts = parts
    assert app_module._synced_by(Typed(parts)) == service
