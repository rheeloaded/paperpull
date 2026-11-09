"""PaperPull Server runs only the provider code the image ships.

The confirmed weakness was that the server ran an install's entry script,
its interpreter and its imported modules from the writable /data share, so
anyone who could write to the share could run code inside the container
that holds every signed-in browser profile. The fix runs the shipped
template's code with the image interpreter, keeps /data off the import
path, and keeps only the data in /data.

These tests build a throwaway image layout under tmp_path and a throwaway
/data install, with harmless deterministic fixtures, and cover the three
confirmed cases as regressions plus the mapping, configuration and desktop
cases the plan calls for. They never touch a real install, a profile or
the network, and the one subprocess they launch is the fixture script
below, run exactly the way the panel would launch a provider.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app = pytest.importorskip("app")
import server_mode  # noqa: E402

ENTRY = "testco_docs.py"

# A stand-in template entry script. It records where it ran from and what it
# could import, so a run proves which code and modules were actually loaded.
# It writes one file in the current directory and does nothing else.
TEMPLATE_ENTRY = """\
import json, sys, importlib.util
from pathlib import Path
out = {
    "ran_from": str(Path(__file__).resolve()),
    "sys_path0": sys.path[0],
    "sibling": importlib.util.find_spec("probe_sibling") is not None,
    "planted": importlib.util.find_spec("pp_planted_module") is not None,
    "sibling_from": getattr(importlib.util.find_spec("probe_sibling"), "origin", None),
}
Path("run-marker.json").write_text(json.dumps(out), encoding="utf-8")
"""


@pytest.fixture()
def layout(tmp_path, monkeypatch):
    """An image-like tree (read-only app code) and a writable /data root.

    Returns (data_root, install_dir, template_dir). The panel is put in
    server mode and pointed at this layout.
    """
    opt = tmp_path / "opt" / "paperpull"
    gui = opt / "gui"
    gui.mkdir(parents=True)
    tmpl = opt / "templates" / "apps" / "testco"
    tmpl.mkdir(parents=True)
    # The shipped entry script and its one sibling, both trusted.
    (tmpl / ENTRY).write_text(
        TEMPLATE_ENTRY + '\n# shipped --open-browser\n', encoding="utf-8")
    (tmpl / "probe_sibling.py").write_text(
        "WHO = 'template'\n", encoding="utf-8")

    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    # A tampered copy of the entry script in /data. If the server ever ran
    # it, run-marker.json would say ran_from this path and login would read
    # its flag. It must never be the code that runs.
    (install / ENTRY).write_text(
        "raise SystemExit('the /data entry script must never run')\n"
        "# no --open-browser here\n", encoding="utf-8")
    (install / "config.json").write_text(
        '{"output_dir": ".", "cdp_url": "http://127.0.0.1:9999"}\n', encoding="utf-8")

    monkeypatch.setattr(app, "HERE", gui)
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.delenv("PAPERPULL_DATA_DIR", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    return data, install, tmpl


def _meta(install_name="Testco Statements"):
    return app.discover_apps()[install_name]


# -- the three confirmed vulnerabilities, as regressions ----------------------

def test_a_entry_script_comes_from_the_image(layout):
    """Test A. A changed entry script in /data cannot change what runs."""
    data, install, tmpl = layout
    meta = _meta()
    assert meta["runnable"] is True
    assert meta["script"] == str(tmpl / ENTRY)
    assert Path(meta["script"]).resolve() != (install / ENTRY).resolve()
    cmd = app._build_cmd(meta, "primary", "discover")
    assert cmd[0] == sys.executable
    assert "-P" in cmd
    assert str(tmpl / ENTRY) in cmd


def test_a2_interpreter_comes_from_the_image(layout):
    """Test A2. A planted .venv interpreter in /data is never used."""
    data, install, tmpl = layout
    for rel in ("Scripts/python.exe", "bin/python"):
        p = install / ".venv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/bin/sh\necho planted\n", encoding="utf-8")
    meta = _meta()
    assert meta["has_venv"] is False
    assert meta["python"] == sys.executable
    assert app._build_cmd(meta, "primary", "pilot")[0] == sys.executable


def test_b_imports_resolve_from_the_image_not_data(layout):
    """Test B. A module planted in /data is not importable by a run, while
    the shipped sibling is, proven by launching the run the panel's way."""
    data, install, tmpl = layout
    # A module planted in the install folder, named so nothing else would
    # import it. If /data were on the path, the run would find it.
    (install / "pp_planted_module.py").write_text("MARKER = 'planted'\n", encoding="utf-8")
    # A decoy sibling in /data that must lose to the template's sibling.
    (install / "probe_sibling.py").write_text("WHO = 'data-decoy'\n", encoding="utf-8")

    meta = _meta()
    cmd = app._build_cmd(meta, "primary", "discover")
    env = app._run_env(meta)
    assert env["PYTHONPATH"] == str(tmpl)
    assert env["PAPERPULL_DATA_DIR"] == str(install)
    # Launch exactly as the panel does, with the install as cwd.
    subprocess.run(cmd[:-1], cwd=str(install), env=env, check=True, timeout=60)
    import json
    marker = json.loads((install / "run-marker.json").read_text(encoding="utf-8"))
    assert marker["ran_from"] == str((tmpl / ENTRY).resolve())
    assert marker["planted"] is False
    assert marker["sibling"] is True
    assert marker["sibling_from"] == str(tmpl / "probe_sibling.py")
    assert str(install) not in marker["sys_path0"]


# -- the data anchor, config and rules stay in /data --------------------------

def test_run_env_and_cwd_keep_data_in_place(layout):
    data, install, tmpl = layout
    meta = _meta()
    env = app._run_env(meta)
    assert env["PAPERPULL_DATA_DIR"] == str(install)
    assert env["PYTHONPATH"] == str(tmpl)
    # The working directory is the install, so output_dir of "." and
    # config.<label>.json still resolve to /data.
    assert meta["dir"] == str(install)


def test_login_flag_is_read_from_the_template(layout):
    """The /data copy has no --open-browser, the template does, so the flag
    comes from the trusted template."""
    data, install, tmpl = layout
    assert _meta()["login_flag"] == "--open-browser"


def test_additional_account_config_resolves_from_data(layout):
    data, install, tmpl = layout
    (install / "config.work.json").write_text('{"output_dir": "."}\n', encoding="utf-8")
    meta = _meta()
    assert "work" in meta["accounts"]
    cmd = app._build_cmd(meta, "work", "pilot")
    assert cmd[-2:] == ["--config", "config.work.json"]


# -- mapping and configuration, fail closed -----------------------------------

def test_ambiguous_mapping_is_not_runnable(layout):
    """Two entry-shaped scripts in /data is ambiguous, so it refuses."""
    data, install, tmpl = layout
    (install / "other_docs.py").write_text("pass\n", encoding="utf-8")
    meta = _meta()
    assert meta["runnable"] is False
    assert meta["template_dir"] is None


def test_unknown_provider_name_is_not_runnable(tmp_path, monkeypatch):
    """An entry name no template ships does not map, so it refuses."""
    opt = tmp_path / "opt" / "paperpull"
    (opt / "gui").mkdir(parents=True)
    tmpl = opt / "templates" / "apps" / "testco"
    tmpl.mkdir(parents=True)
    (tmpl / ENTRY).write_text("pass\n", encoding="utf-8")
    data = tmp_path / "data"
    install = data / "Mystery Statements"
    install.mkdir(parents=True)
    (install / "mystery_docs.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(app, "HERE", opt / "gui")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    assert app.discover_apps()["Mystery Statements"]["runnable"] is False


def test_start_run_refuses_an_unmapped_install(layout):
    data, install, tmpl = layout
    (install / "other_docs.py").write_text("pass\n", encoding="utf-8")
    resp = app._start_run("Testco Statements", "primary", "discover", ())
    body = b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode()
        for chunk in _drain(resp))
    text = body.decode("utf-8", "replace")
    assert "PaperPull does not recognize this provider's folder" in text
    assert "event: done\ndata: 1" in text
    # Said as a run that did not start, never one that began and failed.
    assert "event: refused\ndata: PaperPull does not recognize this provider's folder" in text


def test_renamed_folder_still_resolves(layout):
    """A renamed provider folder keeps its entry script, so it still maps."""
    data, install, tmpl = layout
    renamed = data / "My GitHub Downloads"
    install.rename(renamed)
    meta = app.discover_apps()["My GitHub Downloads"]
    assert meta["runnable"] is True
    assert meta["script"] == str(tmpl / ENTRY)


# -- the desktop is unchanged -------------------------------------------------

def test_desktop_keeps_its_own_script_and_venv(tmp_path, monkeypatch):
    data = tmp_path / "installs"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    (install / ENTRY).write_text("# --open-browser\n", encoding="utf-8")
    (install / "config.json").write_text('{"output_dir": "."}\n', encoding="utf-8")
    venv = install / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setenv("APPS_ROOT", str(data))
    meta = app.discover_apps()["Testco Statements"]
    assert meta["script"] == ENTRY
    assert meta["python"] == str(venv)
    assert meta["has_venv"] is True
    assert meta["runnable"] is True
    cmd = app._build_cmd(meta, "primary", "discover")
    assert "-P" not in cmd
    assert cmd == [str(venv), ENTRY, "--discover"]
    assert "PAPERPULL_DATA_DIR" not in app._run_env(meta)


def _drain(response):
    """The body of a StreamingResponse, without a running event loop."""
    import anyio
    chunks = []

    async def pump():
        async for part in response.body_iterator:
            chunks.append(part)

    anyio.run(pump)
    return chunks
