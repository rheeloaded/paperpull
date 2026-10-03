"""The PaperPull icon on the browser tab the panel opens in.

The page names /favicon.ico, and the panel answers it with the one icon
file the packages are built from. Each kind of copy keeps that file in its
own place, the repo and the server image in packaging/ beside the panel's
folder, the Windows package and the Mac bundle's Resources right beside it.
A copy without the file answers 404, and the page still loads.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
fastapi = pytest.importorskip("fastapi")

REPO = Path(__file__).resolve().parents[2]
ICON = REPO / "packaging" / "paperpull.ico"


def test_the_page_names_the_icon():
    assert '<link rel="icon" href="/favicon.ico">' in app_module.index()


def test_the_icon_is_the_one_the_packages_are_built_from():
    answer = app_module.favicon()
    assert answer.media_type == "image/x-icon"
    assert answer.body == ICON.read_bytes()
    # An .ico starts with a reserved zero, then 1 for an icon.
    assert answer.body[:4] == b"\x00\x00\x01\x00"


def test_a_package_keeps_it_right_beside_the_panels_folder(tmp_path, monkeypatch):
    """The Windows package and the Mac bundle have no packaging folder."""
    beside = tmp_path / "paperpull.ico"
    beside.write_bytes(ICON.read_bytes())
    monkeypatch.setattr(app_module, "_ICON_PLACES",
                        (tmp_path / "packaging" / "paperpull.ico", beside))

    assert app_module.favicon().body == ICON.read_bytes()


def test_a_copy_without_the_icon_answers_404(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "_ICON_PLACES",
                        (tmp_path / "packaging" / "paperpull.ico",
                         tmp_path / "paperpull.ico"))

    with pytest.raises(fastapi.HTTPException) as refused:
        app_module.favicon()
    assert refused.value.status_code == 404
    assert "/favicon.ico" in app_module.index()


def test_the_windows_package_puts_the_icon_where_the_panel_looks():
    """build_windows.py stages the icon at the top of the package, beside
    the gui folder, which is the second place the panel looks."""
    source = (REPO / "packaging" / "build_windows.py").read_text(encoding="utf-8")
    assert 'shutil.copy2(icon, STAGE / "paperpull.ico")' in source
    assert app_module._ICON_PLACES[1] == app_module.HERE.parent / "paperpull.ico"


def test_the_mac_bundle_puts_the_icon_where_the_panel_looks():
    source = (REPO / "packaging" / "build_macos.py").read_text(encoding="utf-8")
    assert 'shutil.copy2(ico, RES / "paperpull.ico")' in source
    assert '--app-dir "$DIR/gui"' in source
