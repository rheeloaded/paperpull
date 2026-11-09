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
import lock  # noqa: E402


# -- what is chosen --------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "VERSION", "LICENSE", "paperpull.py",
    "core/paperpull_core/receipt_pdf.py", "core/pyproject.toml",
    "gui/app.py", "gui/run_result.py",
    "gui/providers.json",                       # the welcome's provider lines
    "gui/static/index.html", "gui/static/app.css", "gui/static/app.js",   # the page itself
    "apps/walmart/walmart_receipts.py", "apps/walmart/config.example.json",
    "apps/walmart/category_rules.json",
    "packaging/paperpull.ico",
    "server/Dockerfile", "server/entrypoint.sh", "server/chrome.sh",
    "tools/add_account.py",                     # Add a person
    "tools/status.py",                          # the Status tab
    "tools/export_purchases.py",                # the purchases spreadsheet
    "tools/export_transactions.py",             # the transactions workbook
    "tools/make_sample.py",                     # the sample archive
    "tools/migrate.py",                         # Export history and Import a history file (#67)
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
    "tools/worktree.py",
    "tools/release.sh",
    ".github/workflows/tests.yml",
    "packaging/build_windows.py",
    "apps/walmart/In-Store/2026-01-01 Walmart Receipt.pdf",    # never tracked, still refused
    "apps/walmart/browser-profile/Default/Cookies",
    "apps/walmart/Diagnostics/failure-run.json",
    "apps/walmart/Walmart Order History.csv",
])
def test_what_it_does_not_need_is_left_out(path):
    assert build.selected([path]) == []


def test_tools_are_named_one_script_at_a_time():
    """tools/ also holds the release and test machinery, which no image
    needs, so the image takes only the scripts the panel runs, each one a
    file git tracks. gui/tests/test_every_panel_tool_reaches_the_server.py
    holds the list to the scripts the panel names."""
    named = [a for a in build.ALLOWED if a.startswith("tools")]
    assert named and "tools/" not in named
    tracked = set(build.tracked(REPO))
    for path in named:
        assert path in tracked, path


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


def test_a_saved_image_keeps_the_tag_server_md_names(monkeypatch, tmp_path):
    """SERVER.md has a person who imports the saved file write
    paperpull-server:dev in compose.yaml, and an import brings back only the
    tags that were saved. Saving the version alone left nothing by that name."""
    seen = []

    def run(cmd, **kwargs):
        seen.append(list(cmd))
        if cmd[:2] == ["docker", "save"]:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"an image")
        out = "" if kwargs.get("text") else b""
        return subprocess.CompletedProcess(cmd, 0, out, out)

    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.main(["--save", str(tmp_path / "paperpull-server.tar")]) == 0
    saved = [c for c in seen if c[:2] == ["docker", "save"]]
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    assert len(saved) == 1
    assert {"paperpull-server:dev", "paperpull-server:%s" % version} <= set(saved[0])
    assert "`paperpull-server:dev`" in (REPO / "SERVER.md").read_text(encoding="utf-8")


# -- the Dockerfile and the folder agree ------------------------------------------------

def dockerfile_sources():
    """Every path the Dockerfile copies from the build folder."""
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    text = re.sub(r"\\\n", " ", text)       # a step continued on the next line
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


def requirement_lines(name: str) -> list:
    return [line.split("#")[0].strip() for line in
            (SERVER / name).read_text(encoding="utf-8").splitlines()
            if line.split("#")[0].strip()]


def dist_name(requirement: str) -> str:
    return re.sub(r"[-_.]+", "-", re.split(r"[\[=<>~! ]", requirement)[0]).lower()


def test_every_package_is_pinned():
    lines = requirement_lines("requirements.in")
    assert lines and all("==" in line for line in lines), lines


def locked() -> dict:
    """Each package in requirements.txt, its version and its hashes."""
    packages, current = {}, None
    for line in requirement_lines("requirements.txt"):
        line = line.rstrip("\\").strip()
        if line.startswith("--hash="):
            assert current, line
            packages[current][1].append(line)
        elif line.startswith("--"):
            assert line == "--only-binary :all:", line
        else:
            name, _, version = line.partition("==")
            assert version, "%s is not pinned to one version" % line
            current = dist_name(name)
            packages[current] = (version, [])
    return packages


def test_the_lock_names_every_package_at_one_version_with_its_hashes():
    packages = locked()
    assert len(packages) > len(requirement_lines("requirements.in"))
    for name, (version, hashes) in packages.items():
        assert hashes and all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", h) for h in hashes), name


def test_the_lock_holds_each_direct_pin_at_its_version():
    """requirements.in is what a person raises, and the image installs the
    lock, so a pin raised without running server/lock.py again is caught."""
    packages = locked()
    for line in requirement_lines("requirements.in"):
        name, version = dist_name(line), line.partition("==")[2]
        assert name in packages, "%s is not in requirements.txt, run server/lock.py" % name
        assert packages[name][0] == version, \
            "requirements.txt has %s %s, run server/lock.py" % (name, packages[name][0])


def test_the_lock_was_resolved_in_the_image_s_own_base():
    image = lock.base_image()
    assert image.startswith("python:")
    text = (SERVER / "requirements.txt").read_text(encoding="utf-8")
    assert text.startswith(lock.header(image)), "the lock was resolved in another base"


def test_the_base_is_named_by_its_digest():
    """A tag alone moves whenever its publisher rebuilds it, so the same
    Dockerfile built a different base from one day to the next."""
    image = lock.base_image()
    assert re.fullmatch(r"python:3\.\d+-slim-\w+@sha256:[0-9a-f]{64}", image), image
    assert lock.base_tag(image) == image.split("@")[0]
    assert "@" not in lock.header(image) and lock.base_tag(image) in lock.header(image)
    froms = [line for line in (SERVER / "Dockerfile").read_text(encoding="utf-8").splitlines()
             if line.startswith("FROM")]
    assert froms == ["FROM " + image]


def test_a_new_digest_needs_no_new_lock():
    """Dependabot's weekly digest leaves requirements.txt alone, so the lock
    names the tag it was resolved in, and either digest of it matches."""
    tag = "python:3.12-slim-bookworm"
    one, two = tag + "@sha256:" + "1" * 64, tag + "@sha256:" + "2" * 64
    assert lock.header(one) == lock.header(two) == lock.header(tag)


def fake_inspect(monkeypatch, answer, code=0):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, code, answer, "no such image" if code else "")

    monkeypatch.setattr(lock.subprocess, "run", run)
    return seen


DOCKERFILE = ("# the base\n"
              "FROM python:3.12-slim-bookworm@sha256:%s\n"
              "RUN echo FROM python:3.12-slim-bookworm@sha256:%s\n" % ("a" * 64, "a" * 64))


def test_base_writes_the_tag_s_digest_of_today(monkeypatch, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(DOCKERFILE, encoding="utf-8", newline="\n")
    seen = fake_inspect(monkeypatch, "sha256:%s\n" % ("b" * 64))

    assert lock.refresh_base(dockerfile) == 0

    assert seen == [["docker", "buildx", "imagetools", "inspect", "python:3.12-slim-bookworm",
                     "--format", "{{.Manifest.Digest}}"]]
    assert dockerfile.read_bytes() == DOCKERFILE.replace("a" * 64, "b" * 64, 1).encode()


def test_base_keeps_the_file_s_own_line_endings(monkeypatch, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_bytes(DOCKERFILE.replace("\n", "\r\n").encode())
    fake_inspect(monkeypatch, "sha256:%s\n" % ("b" * 64))

    assert lock.refresh_base(dockerfile) == 0
    assert dockerfile.read_bytes() == DOCKERFILE.replace("a" * 64, "b" * 64, 1).replace("\n", "\r\n").encode()


def test_base_check_writes_nothing_and_says_when_the_tag_moved(monkeypatch, tmp_path):
    """The Server image workflow's weekly run asks, in case Dependabot ever
    stops proposing a digest of the same tag."""
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(DOCKERFILE, encoding="utf-8", newline="\n")
    fake_inspect(monkeypatch, "sha256:%s\n" % ("b" * 64))
    assert lock.refresh_base(dockerfile, check=True) == 1
    assert dockerfile.read_text(encoding="utf-8") == DOCKERFILE

    fake_inspect(monkeypatch, "sha256:%s\n" % ("a" * 64))
    assert lock.refresh_base(dockerfile, check=True) == 0
    assert lock.refresh_base(dockerfile) == 0
    assert dockerfile.read_text(encoding="utf-8") == DOCKERFILE


def test_base_follows_no_tag_when_the_from_line_has_none(monkeypatch, tmp_path):
    """docker would read python@sha256:... as python:latest."""
    dockerfile = tmp_path / "Dockerfile"
    text = "FROM python@sha256:%s\n" % ("a" * 64)
    dockerfile.write_text(text, encoding="utf-8", newline="\n")
    seen = fake_inspect(monkeypatch, "sha256:%s\n" % ("b" * 64))

    assert lock.refresh_base(dockerfile) == 1
    assert seen == [] and dockerfile.read_text(encoding="utf-8") == text


def test_base_without_docker_changes_nothing(monkeypatch, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(DOCKERFILE, encoding="utf-8", newline="\n")

    def run(cmd, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(lock.subprocess, "run", run)
    assert lock.refresh_base(dockerfile) == 1
    assert dockerfile.read_text(encoding="utf-8") == DOCKERFILE


@pytest.mark.parametrize("answer, code", [
    ("", 1),                                   # docker could not reach the registry
    ("sha256:%s\n" % ("b" * 63), 0),           # not a digest
    ("<no value>\n", 0),
])
def test_base_changes_nothing_without_a_digest(monkeypatch, tmp_path, answer, code):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(DOCKERFILE, encoding="utf-8", newline="\n")
    fake_inspect(monkeypatch, answer, code)

    assert lock.refresh_base(dockerfile) == 1
    assert dockerfile.read_text(encoding="utf-8") == DOCKERFILE


def test_the_image_installs_only_the_lock_s_files():
    text = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    install = [line for line in text.splitlines() if "-r /tmp/requirements.txt" in line]
    assert len(install) == 1
    assert "--require-hashes" in install[0] and "--only-binary :all:" in install[0]
    core = [line for line in text.splitlines() if "pip install" in line and "/opt/paperpull/core" in line]
    assert len(core) == 1
    assert "--no-deps" in core[0] and "--no-build-isolation" in core[0]
    assert "pip install" not in text.replace(install[0], "").replace(core[0], "")


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


def test_a_profiles_lock_from_the_last_start_goes_before_anything_opens():
    """A lock a browser left in its profile when the container stopped named
    the old process, or the old container, so Chrome took the profile for
    one in use and Amazon's sign-in window never opened its debugging port
    (#78). Only Chrome's three lock names go, only in a profile folder
    itself, and before the panel can start a browser."""
    text = (SERVER / "start.sh").read_text(encoding="utf-8")
    sweep = text[text.index('find "${PAPERPULL_PROFILES:-/profiles}"'):]
    sweep = sweep[:sweep.index("2>/dev/null")]
    assert "-mindepth 2 -maxdepth 2" in sweep
    assert sorted(re.findall(r"-name (\S+)", sweep)) == [
        "SingletonCookie", "SingletonLock", "SingletonSocket"]
    assert "-exec rm -f {} +" in sweep
    assert text.index(sweep) < text.index("Xvfb :99") < text.index("exec python -m uvicorn")


def test_novnc_is_its_web_files_and_not_its_dependencies():
    """Installed, Debian's novnc package brings Node.js and NumPy, about 90
    MB the image never uses, and the panel carries the connection itself."""
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    install = dockerfile[dockerfile.index("apt-get install -y --no-install-recommends \\"):]
    install = install[:install.index("&& cd /tmp")]
    assert "novnc" not in install and "websockify" not in install
    assert "apt-get download novnc" in dockerfile and "dpkg-deb -x novnc_" in dockerfile
