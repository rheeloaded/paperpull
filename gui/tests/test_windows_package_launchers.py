"""The Windows package opens the panel with PaperPull.exe and keeps its
terminal command, paperpull.bat, exactly as the repo has it.

The panel's launcher used to be a batch file named PaperPull.bat. Windows
does not tell that name from paperpull.bat, so writing it replaced the
terminal command in every Windows package from 0.19.0 on. On a disk that
does tell them apart the two files sat side by side instead, so both ways
of failing are checked.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def bw(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "bw_launchers", REPO / "packaging" / "build_windows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DIST", tmp_path / "dist")
    monkeypatch.setattr(mod, "STAGE", tmp_path / "dist" / "PaperPull")
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


def _staged_as_stage_code_leaves_it(bw):
    bw.STAGE.mkdir(parents=True)
    shutil.copy2(REPO / "paperpull.bat", bw.STAGE / "paperpull.bat")


def _compiles(monkeypatch, bw, works=True):
    def compile_launcher(stage, icon, say):
        if works:
            (stage / "PaperPull.exe").write_bytes(b"MZ")
        return works
    monkeypatch.setattr(bw.msix, "compile_launcher", compile_launcher)


def test_nothing_the_launchers_write_takes_the_terminal_commands_name(bw, monkeypatch):
    _staged_as_stage_code_leaves_it(bw)
    _compiles(monkeypatch, bw)
    bw.write_launchers()
    names = sorted(p.name.lower() for p in bw.STAGE.iterdir())
    assert len(names) == len(set(names)), "two files differ only in case: %s" % names
    assert (bw.STAGE / "paperpull.bat").read_bytes() == (REPO / "paperpull.bat").read_bytes()
    readme = (bw.STAGE / "README-FIRST.txt").read_text(encoding="utf-8")
    assert "Double-click PaperPull.exe" in readme
    assert "paperpull.bat <app> <command>" in readme


def test_a_package_that_could_not_build_its_exe_is_refused(bw, monkeypatch):
    """Without the exe nothing opens the panel, since there is no batch
    file for it any more."""
    _staged_as_stage_code_leaves_it(bw)
    _compiles(monkeypatch, bw, works=False)
    with pytest.raises(SystemExit):
        bw.write_launchers()


def test_a_terminal_command_replaced_on_the_way_is_caught(bw, monkeypatch):
    _staged_as_stage_code_leaves_it(bw)
    _compiles(monkeypatch, bw)
    (bw.STAGE / "paperpull.bat").write_text("@echo off\r\nrem the panel\r\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        bw.write_launchers()


def test_the_installer_shortcuts_open_the_panel_with_its_exe(bw):
    bw.DIST.mkdir(parents=True)
    iss = bw.write_inno_script().read_text(encoding="utf-8")
    targets = [line for line in iss.splitlines() if "Filename:" in line]
    assert len(targets) == 3, targets     # the two shortcuts and "Open PaperPull now"
    assert all('Filename: "{app}\\PaperPull.exe"' in line for line in targets), targets
    assert "PaperPull.bat" not in iss


def test_the_store_package_never_leaves_out_the_exe_it_runs():
    spec = importlib.util.spec_from_file_location("msix_launchers", REPO / "packaging" / "msix.py")
    msix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(msix)
    left_out = {name.lower() for name in msix.STORE_LEAVES_OUT}
    assert "paperpull.exe" not in left_out
    assert "paperpull.bat" in left_out and "readme-first.txt" in left_out
