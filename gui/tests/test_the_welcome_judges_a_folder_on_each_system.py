"""What the welcome's first step says of a PaperPull folder, on Windows and
on a Mac.

The check asked os.access whether the folder could be written. On Windows
that reads only the read-only flag, which says nothing of a folder's own
rights, so it said yes to every folder, Program Files too, and a folder
PaperPull could not write was refused only at Set up, two steps on, as
before the check existed. And a folder was taken for Google Drive or iCloud
Drive by the start of its name alone, so "My Drivers" was warned of as
Google Drive's "My Drive".
"""
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


def test_where_windows_says_yes_to_every_folder_a_folder_is_made_to_find_out(box, monkeypatch):
    monkeypatch.setattr(app_module, "_ACCESS_SAYS_YES_TO_FOLDERS", True)
    asked = []

    def refused(prefix="", dir=None):
        asked.append(dir)
        raise PermissionError(13, "Access is denied", dir)
    monkeypatch.setattr(app_module.tempfile, "mkdtemp", refused)
    root, problem = app_module._root_problem(str(box / "Program Files" / "PaperPull"))
    assert root is None and "cannot write there" in problem
    # In the nearest folder that is there, which is where setting up makes it.
    assert asked == [str(box)]
    root, problem = app_module._root_problem(str(box))
    assert root is None and "cannot write there" in problem


def test_a_folder_that_can_be_written_is_fine_and_left_as_it_was(box, monkeypatch):
    monkeypatch.setattr(app_module, "_ACCESS_SAYS_YES_TO_FOLDERS", True)
    (box / "Documents").mkdir()
    root, problem = app_module._root_problem(str(box / "Documents" / "PaperPull"))
    assert problem == "" and root == box / "Documents" / "PaperPull"
    root, problem = app_module._root_problem(str(box / "Documents"))
    assert problem == "" and root == box / "Documents"
    # The folder made to find out is taken away again.
    assert [p.name for p in box.iterdir()] == ["Documents"]
    assert list((box / "Documents").iterdir()) == []


def test_where_os_access_answers_no_folder_is_made(box, monkeypatch):
    monkeypatch.setattr(app_module, "_ACCESS_SAYS_YES_TO_FOLDERS", False)

    def never(*a, **k):
        raise AssertionError("a folder was made where os.access answers")
    monkeypatch.setattr(app_module.tempfile, "mkdtemp", never)
    assert app_module._root_problem(str(box / "PaperPull"))[1] == ""


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
