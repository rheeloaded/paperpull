"""What the server image is built from, checked without Docker.

server/build.py hands Docker a folder of the files git tracks, from the
places the image needs, and nothing else. A working copy also holds a
provider's downloads, its records and a signed-in browser profile, none of
them tracked, and none of them may ever reach a published image. These
tests hold that line, and hold the Dockerfile to the folder build.py makes.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

import build  # noqa: E402


# -- what is chosen --------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "VERSION", "LICENSE", "paperpull.py",
    "core/paperpull_core/receipt_pdf.py", "core/pyproject.toml",
    "gui/app.py", "gui/run_result.py",
    "apps/walmart/walmart_receipts.py", "apps/walmart/config.example.json",
    "apps/walmart/category_rules.json",
    "packaging/paperpull.ico",
    "server/Dockerfile", "server/entrypoint.sh", "server/chrome.sh",
])
def test_what_the_image_needs_is_chosen(path):
    assert build.selected([path]) == [path]


@pytest.mark.parametrize("path", [
    "apps/walmart/tests/test_spec.py",          # tests
    "core/tests/test_page_check.py",
    "server/tests/test_build_context.py",
    "apps/walmart/login.bat",                   # desktop launchers
    "apps/walmart/setup.command",
    "docs/panel.png",                           # not a place the image needs
    "tools/run_all_tests.py",
    ".github/workflows/tests.yml",
    "packaging/build_windows.py",
    "apps/walmart/In-Store/2026-01-01 Walmart Receipt.pdf",    # never tracked, still refused
    "apps/walmart/browser-profile/Default/Cookies",
    "apps/walmart/Diagnostics/failure-run.json",
    "apps/walmart/Walmart Order History.csv",
])
def test_what_it_does_not_need_is_left_out(path):
    assert build.selected([path]) == []


# -- the folder Docker is handed -----------------------------------------------------

def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def working_copy(tmp_path):
    """A repository laid out like this one, with the things a real working
    copy holds and git does not track beside the things it does."""
    repo = tmp_path / "repo"
    files = {
        "VERSION": b"9.9.9\r\n",
        "apps/shop/shop.py": b"print('one')\r\nprint('two')\r\n",
        "apps/shop/config.example.json": b'{"owner": ""}\r\n',
        "apps/shop/login.bat": b"@echo off\r\n",
        "apps/shop/tests/test_shop.py": b"def test(): pass\n",
        "server/start.sh": b"#!/bin/sh\r\necho start\r\n",
        "packaging/paperpull.ico": b"\x00\x00\x01\x00\r\n\x00",
        "docs/notes.md": b"notes\n",
    }
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "add", "-A")
    # What a run leaves behind, never added.
    untracked = {
        "apps/shop/progress.json": b'{"Order:1": {"downloaded_ok": true}}',
        "apps/shop/In-Store/2026-01-01 Shop Receipt.pdf": b"%PDF-1.7 a real receipt",
        "apps/shop/browser-profile/Default/Cookies": b"session",
        "apps/shop/notes-to-self.txt": b"account 12345",
    }
    for rel, data in untracked.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    return repo


def test_only_tracked_files_in_the_allowed_places_reach_docker(working_copy, tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()

    n = build.make_context(ctx, repo=working_copy)

    got = sorted(str(p.relative_to(ctx)).replace("\\", "/")
                 for p in ctx.rglob("*") if p.is_file())
    assert got == ["VERSION", "apps/shop/config.example.json", "apps/shop/shop.py",
                   "packaging/paperpull.ico", "server/start.sh"], got
    assert n == len(got)


def test_text_files_get_lf_and_binary_files_are_left_alone(working_copy, tmp_path):
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    build.make_context(ctx, repo=working_copy)

    assert (ctx / "server/start.sh").read_bytes() == b"#!/bin/sh\necho start\n"
    assert (ctx / "apps/shop/shop.py").read_bytes() == b"print('one')\nprint('two')\n"
    assert (ctx / "VERSION").read_bytes() == b"9.9.9\n"
    assert (ctx / "packaging/paperpull.ico").read_bytes() == b"\x00\x00\x01\x00\r\n\x00"


# -- the Dockerfile and the folder agree ------------------------------------------------

def dockerfile_sources():
    """Every path the Dockerfile copies from the build folder."""
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*COPY\s+(?!--from)(.+)$", line)
        if m:
            parts = m.group(1).split()
            out += [p for p in parts[:-1] if not p.startswith("--")]
    return out


def test_everything_the_dockerfile_copies_is_in_the_folder_build_makes():
    chosen = build.selected(build.tracked(REPO))
    for src in dockerfile_sources():
        folder = src.rstrip("/") + "/"
        if any(p.startswith(folder) for p in chosen):
            continue        # a folder, and build.py hands over what is in it
        assert src in chosen, "%s is copied but build.py does not hand it over" % src


def test_the_dockerfile_copies_nothing_from_outside_the_allowed_places():
    for src in dockerfile_sources():
        assert build.allowed(src) or build.allowed(src.rstrip("/") + "/"), src


# -- what the image is set up to do ------------------------------------------------

def test_the_google_key_is_checked_against_the_published_fingerprint():
    """google.com/linuxrepositories, the Linux Package Signing Authority."""
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert "GOOGLE_SIGNING_FINGERPRINT=EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796" in text
    assert 'grep -q "^fpr:::::::::${GOOGLE_SIGNING_FINGERPRINT}:"' in text


def test_chrome_is_not_left_in_the_image():
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    install = text.index("apt-get install -y --no-install-recommends google-chrome-stable")
    step_end = text.index("\n\n", install)
    assert "apt-get purge -y google-chrome-stable" in text[install:step_end]
    assert "test ! -e /usr/bin/google-chrome-stable" in text[install:step_end]


def test_chrome_keeps_no_passwords_and_reports_nothing():
    import json
    policies = json.loads((SERVER / "chrome-policies.json").read_text(encoding="utf-8"))
    assert policies["PasswordManagerEnabled"] is False
    assert policies["AutofillCreditCardEnabled"] is False
    assert policies["MetricsReportingEnabled"] is False
    assert policies["SyncDisabled"] is True


def test_every_package_is_pinned():
    lines = [line.strip() for line in
             (SERVER / "requirements.txt").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines and all("==" in line for line in lines), lines


def test_everything_runs_as_pp_after_the_root_step():
    text = (SERVER / "entrypoint.sh").read_text(encoding="utf-8")
    assert text.rstrip().splitlines()[-2].startswith("exec setpriv --reuid=pp --regid=pp")


def test_only_the_panel_listens_beyond_the_container_and_only_as_the_server():
    """The panel is on the network, and it is there only as PaperPull Server,
    which never answers without a password. Screen sharing listens inside
    the container, and nothing else is started that listens at all."""
    text = (SERVER / "start.sh").read_text(encoding="utf-8")
    assert text.count("0.0.0.0") == 1
    assert "--host 0.0.0.0 --port 8765" in text
    assert text.index("export PAPERPULL_SERVER=1") < text.index("--host 0.0.0.0")
    assert "-localhost -rfbport 5900" in text
    assert "websockify" not in text
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert [line for line in dockerfile.splitlines() if line.startswith("EXPOSE")] == ["EXPOSE 8765"]


def test_novnc_is_its_web_files_and_not_its_dependencies():
    """Installed, Debian's novnc package brings Node.js and NumPy, about 90
    MB the image never uses, and the panel carries the connection itself."""
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    install = dockerfile[dockerfile.index("apt-get install -y --no-install-recommends \\"):]
    install = install[:install.index("&& cd /tmp")]
    assert "novnc" not in install and "websockify" not in install
    assert "apt-get download novnc" in dockerfile and "dpkg-deb -x novnc_" in dockerfile
