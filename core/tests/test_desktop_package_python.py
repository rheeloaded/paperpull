"""The Windows and macOS packages carry the same CPython from the same
python-build-standalone release, each archive checked against its published
SHA-256, and install every package from a lock that holds each file's hash.

The Windows package was built on python.org's embeddable CPython 3.12.10,
the last 3.12 with Windows binaries there, so no later 3.12 security fix
could reach it. Both packages installed lower bounds (playwright>=1.44 and
so on), whatever PyPI held on the day, and the Windows build ran get-pip.py
as downloaded, with nothing checking a byte of either.

python.org's files came signed by the Python Software Foundation and
python-build-standalone's come unsigned, so the Windows workflow signs the
interpreter's programs and libraries along with PaperPull.exe.
"""
import base64
import fnmatch
import hashlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / "packaging"


def _load(name, path):
    sys.path.insert(0, str(PACKAGING))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def bw(monkeypatch, tmp_path):
    mod = _load("bw_python", PACKAGING / "build_windows.py")
    monkeypatch.setattr(mod, "DIST", tmp_path / "dist")
    monkeypatch.setattr(mod, "STAGE", tmp_path / "dist" / "PaperPull")
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


@pytest.fixture()
def bm(monkeypatch):
    mod = _load("bm_python", PACKAGING / "build_macos.py")
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


@pytest.fixture()
def lock_tool():
    return _load("lock_tool", PACKAGING / "lock.py")


def _builders(bw, bm):
    return ((bw, "windows"), (bm, "macos"))


# -- one Python, from one release ----------------------------------------------

def test_both_packages_carry_the_same_python_from_the_same_release(bw, bm):
    assert bw.PY_VERSION == bm.PY_VERSION
    assert bw.PBS_TAG == bm.PBS_TAG
    assert bw.PY_VERSION.startswith("3.12.")
    for mod, _ in _builders(bw, bm):
        for arch in mod.ARCHES:
            assert mod.triple(arch).startswith(mod.ARCHES[arch] + "-")


def test_each_python_archive_is_fetched_against_its_own_published_digest(bw, bm, monkeypatch):
    every = list(bw.PBS_SHA256.values()) + list(bm.PBS_SHA256.values())
    assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in every)
    assert len(set(every)) == len(every), "one archive each, no digest copied to another"

    class Fetched(Exception):
        pass

    for mod, system in _builders(bw, bm):
        assert set(mod.PBS_SHA256) == set(mod.ARCHES)
        asked = []

        def fake_fetch(url, dest, sha256=""):
            asked.append((url, dest.name, sha256))
            raise Fetched()

        monkeypatch.setattr(mod, "fetch", fake_fetch)
        for arch in mod.ARCHES:
            monkeypatch.setattr(mod, "ARCH", arch)
            with pytest.raises(Fetched):
                mod.stage_python()
            name = "cpython-%s+%s-%s-install_only_stripped.tar.gz" % (
                mod.PY_VERSION, mod.PBS_TAG, mod.triple(arch))
            assert asked[-1] == (
                "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s"
                % (mod.PBS_TAG, name), name, mod.PBS_SHA256[arch]), (system, arch)
        assert len(asked) == len(mod.ARCHES), "%s fetches one file per build" % system


def test_nothing_is_fetched_from_bootstrap_or_without_a_digest():
    for name in ("build_windows.py", "build_macos.py"):
        source = (PACKAGING / name).read_text(encoding="utf-8")
        assert "get-pip" not in source and "bootstrap.pypa.io" not in source, name
        assert "python.org/ftp" not in source, name
        calls = [line for line in source.splitlines()
                 if re.search(r"\bfetch\(", line) and not line.lstrip().startswith("def fetch(")]
        assert calls, name
        for call in calls:
            assert "sha256=" in call, (name, call)


def _fake_archive(path: Path) -> str:
    """A python-build-standalone archive in miniature, every name the
    builder keeps or prunes, and its digest."""
    names = {
        "python/python.exe": b"MZ", "python/pythonw.exe": b"MZ",
        "python/python312.dll": b"MZ", "python/python3.dll": b"MZ",
        "python/vcruntime140.dll": b"MZ", "python/LICENSE.txt": b"license",
        "python/DLLs/_socket.pyd": b"MZ", "python/DLLs/_ssl.pyd": b"MZ",
        "python/DLLs/_testcapi.pyd": b"MZ", "python/DLLs/_ctypes_test.pyd": b"MZ",
        "python/DLLs/_tkinter.pyd": b"MZ", "python/DLLs/tcl86t.dll": b"MZ",
        "python/DLLs/tk86t.dll": b"MZ", "python/DLLs/zlib1.dll": b"MZ",
        "python/Lib/os.py": b"", "python/Lib/venv/__init__.py": b"",
        "python/Lib/ensurepip/_bundled/pip-25.0.1-py3-none-any.whl": b"PK",
        "python/Lib/tkinter/__init__.py": b"", "python/Lib/idlelib/idle.py": b"",
        "python/Lib/turtledemo/__main__.py": b"", "python/Lib/turtle.py": b"",
        "python/Lib/site-packages/README.txt": b"",
        "python/Lib/site-packages/pip/__init__.py": b"",
        "python/tcl/tcl8.6/init.tcl": b"", "python/include/Python.h": b"",
        "python/libs/python312.lib": b"", "python/Scripts/.empty": b"",
    }
    with tarfile.open(path, "w:gz") as t:
        for name, data in names.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_staged_python_reads_only_its_own_folders_and_drops_what_it_never_needs(bw, monkeypatch):
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    digest = _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, digest)
    py = bw.stage_python()
    pydir = bw.STAGE / "python"
    assert py == pydir / "python.exe"
    # The ._pth file beside the DLL is what makes Python ignore PYTHONPATH,
    # PYTHONHOME and the current folder. Its name must be the DLL's.
    pth = pydir / "python312._pth"
    assert pth.read_text(encoding="utf-8").splitlines() == [
        "DLLs", "Lib", "Lib\\site-packages", "import site"]
    assert (pydir / "Lib" / "site-packages" / "sitecustomize.py").is_file()
    for kept in ("python.exe", "python312.dll", "DLLs/_socket.pyd", "DLLs/_ssl.pyd",
                 "Lib/os.py", "Lib/site-packages/pip/__init__.py", "Scripts"):
        assert (pydir / kept).exists(), kept
    for gone in ("tcl", "include", "libs", "Lib/tkinter", "Lib/idlelib", "Lib/turtledemo",
                 "Lib/turtle.py", "Lib/ensurepip", "Lib/venv", "DLLs/_tkinter.pyd",
                 "DLLs/tcl86t.dll", "DLLs/tk86t.dll", "DLLs/zlib1.dll",
                 "DLLs/_testcapi.pyd", "DLLs/_ctypes_test.pyd"):
        assert not (pydir / gone).exists(), gone


def test_an_installer_upgrade_replaces_the_bundled_python_whole(bw):
    """Inno Setup copies over an install without removing anything, so an
    upgrade from the embeddable build would keep its files, and a package
    that moved down a version would leave both versions' metadata."""
    bw.DIST.mkdir(parents=True)
    iss = bw.write_inno_script().read_text(encoding="utf-8")
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    entries = [line for line in section.splitlines() if line.startswith("Type:")]
    assert entries == ['Type: filesandordirs; Name: "{app}\\python"']
    assert iss.index("[InstallDelete]") < iss.index("[Files]")


def test_a_damaged_archive_is_never_unpacked(bw, monkeypatch):
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, "0" * 64)
    with pytest.raises(SystemExit):
        bw.stage_python()
    assert not (bw.STAGE / "python").exists()
    assert not (cache / bw.pbs_asset()).exists(), "deleted, so the next build fetches it again"


class _Ran:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, "", returncode


def test_the_build_refuses_a_python_that_is_not_the_one_it_names(bw, bm, monkeypatch, tmp_path):
    """Each smoke test asks the packaged Python which it is before anything
    else, and stops on any answer but PY_VERSION."""
    for mod, system in _builders(bw, bm):
        asked = []

        def run(cmd, **kw):
            asked.append(cmd)
            if "platform.python_version()" in " ".join(cmd):
                return _Ran("3.12.10\n")
            return _Ran("ok\n")

        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(SystemExit) as stop:
            mod.smoke_test(tmp_path / "python")
        assert "3.12.10" in str(stop.value) and mod.PY_VERSION in str(stop.value), system
        assert len(asked) == 1, "%s stopped at the first question" % system
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Ran(bw.PY_VERSION + "\n"))
    assert bw.check_python_version(tmp_path / "python", bw.PY_VERSION) == bw.PY_VERSION


# -- what the Windows workflow signs -------------------------------------------

WINDOWS_WORKFLOW = REPO / ".github" / "workflows" / "build-windows.yml"
SET_ASIDE = "Set PaperPull.exe and the interpreter aside for signing"
SIGN = "Sign PaperPull.exe and the interpreter"
PUT_BACK = "Put the signed files back"

# PaperPull.exe and every program and library of the interpreter that
# python-build-standalone ships unsigned, as Get-AuthenticodeSignature read
# them in a package staged from SIGNED_FOR. The two Visual C++ runtime DLLs
# beside them carry Microsoft's signature and stay as they are, and so do
# the packages' own files under Lib\site-packages and Scripts.
SIGNED = (
    "PaperPull.exe",
    "python\\python.exe", "python\\pythonw.exe", "python\\python3.dll", "python\\python312.dll",
    "python\\DLLs\\libcrypto-3-x64.dll", "python\\DLLs\\libffi-8.dll",
    "python\\DLLs\\libssl-3-x64.dll", "python\\DLLs\\sqlite3.dll",
) + tuple("python\\DLLs\\%s.pyd" % m for m in (
    "_asyncio", "_bz2", "_ctypes", "_decimal", "_elementtree", "_hashlib", "_lzma", "_msi",
    "_multiprocessing", "_overlapped", "_queue", "_socket", "_sqlite3", "_ssl", "_uuid",
    "_wmi", "_zoneinfo", "pyexpat", "select", "unicodedata", "winsound"))
SIGNED_FOR = ("20261026", "3.12.16", "x64")     # PBS_TAG, PY_VERSION, ARCH


def _windows_steps() -> dict:
    """{step name: its lines} of build-windows.yml, read as text like the
    other workflow tests. A step ends at the first line that is not
    indented under it."""
    steps, name = {}, None
    for line in WINDOWS_WORKFLOW.read_text(encoding="utf-8").splitlines():
        m = re.match(r"      - (?:name: (.+)|uses: .+)$", line)
        if m:
            name = m.group(1)
            if name:
                assert name not in steps, "two steps named %r" % name
                steps[name] = []
        elif name and (line.startswith("        ") or not line.strip()):
            steps[name].append(line)
        else:
            name = None
    return {k: "\n".join(v) for k, v in steps.items()}


def _script(step: str) -> str:
    return textwrap.dedent(step.split("run: |\n", 1)[1])


def _set_aside_list(steps: dict) -> list:
    block = _script(steps[SET_ASIDE]).split("$sign = @(\n", 1)[1].split("\n)\n", 1)[0]
    lines = [line for line in block.splitlines() if line.strip()]
    listed = [re.fullmatch(r"\s*'([^']+)'", line) for line in lines]
    assert all(listed), "one quoted path a line: %r" % lines
    return [m.group(1) for m in listed]


def test_the_windows_workflow_signs_what_python_build_standalone_leaves_unsigned(bw):
    """The list was taken from one archive, and another can add or drop a
    file. A new PBS_TAG takes it again from its staged python\\ and
    python\\DLLs with Get-AuthenticodeSignature, in the workflow and here,
    and only then moves SIGNED_FOR. The workflow also stops on any program
    or library left unsigned there, so a missed file cannot ship."""
    assert (bw.PBS_TAG, bw.PY_VERSION, bw.ARCH) == SIGNED_FOR
    listed = _set_aside_list(_windows_steps())
    assert listed == list(SIGNED)
    assert len(set(listed)) == len(listed)
    for rel in listed[1:]:
        assert rel.startswith("python\\"), rel
        assert "\\Lib\\" not in rel and "\\Scripts\\" not in rel, "a package's file, not the interpreter's"
        assert not rel.rsplit("\\", 1)[-1].lower().startswith("vcruntime"), "Microsoft's signature stays"
        under = rel.split("\\", 1)[1].replace("\\", "/")
        assert not any(fnmatch.fnmatch(under, p) for p in bw.PRUNE), "%s is pruned, never shipped" % rel


def test_only_what_was_set_aside_is_signed_and_every_copy_is_checked():
    steps = _windows_steps()
    order = ["Stage the package", SET_ASIDE, SIGN, PUT_BACK,
             "Build the zip, installer and MSIX from the stage", "Sign the installer",
             "Check every shipped program is signed"]
    assert [n for n in steps if n in order] == order
    assert "--arch" not in steps["Stage the package"], "the list names the x64 build's files"
    for name in (SET_ASIDE, SIGN, PUT_BACK, "Sign the installer", "Check every shipped program is signed"):
        assert "if: env.SIGNING == 'true'" in steps[name], name
    sign = steps[SIGN]
    assert re.search(r"^\s+files-folder: \$\{\{ github\.workspace \}\}\\to-sign\\stage$", sign, re.M)
    assert re.search(r"^\s+files-folder-filter: exe,dll,pyd$", sign, re.M)
    assert re.search(r"^\s+files-folder-recurse: true$", sign, re.M)
    assert "files:" not in sign and "files-catalog:" not in sign, "the folder holds exactly the list"
    assert "to-sign\\stage" not in steps["Sign the installer"]
    for name in (PUT_BACK, "Check every shipped program is signed"):
        assert "Get-Content to-sign\\signed.txt" in _script(steps[name]), name
    # The quota the comment states is the list's.
    n = len(SIGNED)
    assert "That is %d signatures a build, %d" % (n, n + 1) in WINDOWS_WORKFLOW.read_text(encoding="utf-8")


# The steps themselves, run by PowerShell over a stage of stand-in files.
# The workflow runs them in pwsh, a machine without it in Windows
# PowerShell, and they are written for both.

needs_windows = pytest.mark.skipif(os.name != "nt", reason="the steps run on a Windows runner")


def _run_steps(cwd: Path, *names: str) -> tuple:
    """(exit code, what it printed) of the named steps run in turn, as the
    runner would in the workspace cwd. A step that stops prints its reason
    on one line, where PowerShell's own error display would wrap it."""
    steps = _windows_steps()
    body = "\n".join(_script(steps[n]) for n in names)
    script = ("$ProgressPreference = 'SilentlyContinue'\ntry {\n%s\n} catch {\n"
              "  [Console]::Out.WriteLine('STOPPED ' + $_.Exception.Message)\n  exit 1\n}\n" % body)
    shell = shutil.which("pwsh") or shutil.which("powershell")
    ran = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand",
         base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
        cwd=cwd, capture_output=True, text=True, timeout=300,
        env=dict(os.environ, RUNNER_TEMP=str(cwd / "runner-temp")))
    return ran.returncode, ran.stdout + ran.stderr


def _at(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("\\"))


NOT_LISTED = ("python\\vcruntime140.dll", "python\\Lib\\site-packages\\greenlet\\_greenlet.pyd",
              "python\\Scripts\\uvicorn.exe")


def _stage(bw, monkeypatch, root: Path, runtime: bytes = b"MZ", extra: str = "") -> Path:
    """A stand-in stage under root, its interpreter files recorded by the
    build's own record_interpreter as staging records them."""
    stage = root / "dist" / "PaperPull"
    for rel in SIGNED + NOT_LISTED + ((extra,) if extra else ()):
        _at(stage, rel).parent.mkdir(parents=True, exist_ok=True)
        _at(stage, rel).write_bytes(b"MZ")
    _at(stage, "python\\vcruntime140.dll").write_bytes(runtime)
    monkeypatch.setattr(bw, "DIST", root / "dist")
    monkeypatch.setattr(bw, "STAGE", stage)
    bw.record_interpreter()
    return stage


def _signed_files() -> list:
    """Files with a valid embedded signature, one for each signer, from the
    Python running this suite. python.org's build signs its own and ships
    Microsoft's runtime signed. A copy over a set-aside file stands in for
    the signing action."""
    base = Path(sys.base_prefix)
    found = [p for p in (base / "vcruntime140.dll", base / "python.exe", base / "python3.dll")
             if p.is_file()]
    if not found:
        return []
    script = "".join(
        "$s = Get-AuthenticodeSignature -LiteralPath '%s'\n"
        "if ($s.Status -eq 'Valid') { [Console]::Out.WriteLine('%d ' + $s.SignerCertificate.Subject) }\n"
        % (p, i) for i, p in enumerate(found))
    shell = shutil.which("pwsh") or shutil.which("powershell")
    out = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand",
         base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
        capture_output=True, text=True, timeout=120).stdout
    signers = {}
    for line in out.splitlines():
        i, _, subject = line.partition(" ")
        if i.isdigit() and subject:
            signers.setdefault(subject, found[int(i)])
    return list(signers.values())


def _signed_or_skip() -> list:
    signed = _signed_files()
    if not signed:
        pytest.skip("no file with a valid embedded signature beside the Python running this suite")
    return signed


def _signed_stage(bw, monkeypatch, root: Path, signed: bytes, extra: str = "") -> Path:
    """A stage the workflow's own step set aside, each set-aside file then
    replaced by a signed one as the signing action would leave it."""
    stage = _stage(bw, monkeypatch, root, runtime=signed, extra=extra)
    code, out = _run_steps(root, SET_ASIDE)
    assert code == 0, out
    for rel in SIGNED:
        _at(root / "to-sign" / "stage", rel).write_bytes(signed)
    return stage


def test_the_build_records_each_interpreter_file_as_the_checked_archive_held_it(bw, monkeypatch):
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    digest = _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, digest)
    bw.stage_python()
    record = bw.DIST / bw.PYTHON_RECORD
    assert record.parent == bw.STAGE.parent, "beside the stage, so it never ships"
    with tarfile.open(cache / bw.pbs_asset()) as t:
        held = {m.name: hashlib.sha256(t.extractfile(m).read()).hexdigest()
                for m in t.getmembers() if m.isfile()}
    lines = record.read_text(encoding="ascii").splitlines()
    want = ["python\\DLLs\\_socket.pyd", "python\\DLLs\\_ssl.pyd", "python\\python.exe",
            "python\\python3.dll", "python\\python312.dll", "python\\pythonw.exe",
            "python\\vcruntime140.dll"]
    assert sorted(line.split("  ", 1)[1] for line in lines) == want, "pruned files are not recorded"
    for line in lines:
        digest, rel = line.split("  ", 1)
        assert digest == held[rel.replace("\\", "/")], rel


@needs_windows
def test_the_record_is_the_archives_even_when_a_package_overwrites_a_file(bw, monkeypatch):
    """Staging records the files as it unpacks them, before any package is
    installed, so a file a wheel overwrites no longer matches its record
    and the workflow will not sign it."""
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    digest = _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, digest)
    monkeypatch.setattr(bw, "host_arch", lambda: bw.ARCH)

    def a_wheel_overwrites(py):
        (bw.STAGE / "python" / "python312.dll").write_bytes(b"MZ from a wheel")

    monkeypatch.setattr(bw, "install_packages", a_wheel_overwrites)
    for name in ("stage_code", "write_launchers", "audit"):
        monkeypatch.setattr(bw, name, lambda: None)
    monkeypatch.setattr(bw, "smoke_test", lambda py: None)
    assert bw.main(["--stage-only"]) == 0
    recorded = dict(reversed(line.split("  ", 1)) for line in
                    (bw.DIST / bw.PYTHON_RECORD).read_text(encoding="ascii").splitlines())
    assert recorded["python\\python312.dll"] == hashlib.sha256(b"MZ").hexdigest()
    assert (bw.STAGE / "python" / "python312.dll").read_bytes() == b"MZ from a wheel"


@needs_windows
def test_setting_aside_moves_exactly_the_listed_files_and_stops_on_a_missing_one(bw, monkeypatch, tmp_path):
    stage = _stage(bw, monkeypatch, tmp_path)
    code, out = _run_steps(tmp_path, SET_ASIDE)
    assert code == 0, out
    assert "%d files set aside for signing" % len(SIGNED) in out
    aside = tmp_path / "to-sign" / "stage"
    for rel in SIGNED:
        assert _at(aside, rel).is_file() and not _at(stage, rel).exists(), rel
    assert len([p for p in aside.rglob("*") if p.is_file()]) == len(SIGNED)
    for rel in NOT_LISTED:
        assert _at(stage, rel).is_file(), rel
    assert (tmp_path / "to-sign" / "signed.txt").read_text(encoding="ascii").split() == list(SIGNED)

    other = tmp_path / "another"
    _at(_stage(bw, monkeypatch, other), "python\\DLLs\\_ssl.pyd").unlink()
    code, out = _run_steps(other, SET_ASIDE)
    assert code == 1 and "STOPPED" in out and "_ssl.pyd" in out, out


@needs_windows
def test_nothing_is_signed_once_an_interpreter_file_is_not_the_archives(bw, monkeypatch, tmp_path):
    """The packages are installed into the interpreter's own folder after
    the archive's check, and a wheel's data files land under it, so one
    could overwrite python312.dll and have it signed with the project's
    certificate."""
    changed = tmp_path / "changed"
    _at(_stage(bw, monkeypatch, changed), "python\\python312.dll").write_bytes(b"MZ from a wheel")
    code, out = _run_steps(changed, SET_ASIDE)
    assert code == 1 and "STOPPED python\\python312.dll is no longer the file the checked archive held" in out, out
    assert not (changed / "to-sign" / "stage").exists(), "stopped before anything was set aside"

    unrecorded = tmp_path / "unrecorded"
    _stage(bw, monkeypatch, unrecorded)
    record = unrecorded / "dist" / bw.PYTHON_RECORD
    record.write_text("".join(line + "\n" for line in record.read_text(encoding="ascii").splitlines()
                              if not line.endswith("\\_ssl.pyd")), encoding="ascii")
    code, out = _run_steps(unrecorded, SET_ASIDE)
    assert code == 1 and "STOPPED python\\DLLs\\_ssl.pyd did not come from the checked archive" in out, out


@needs_windows
def test_putting_back_stops_on_a_file_that_came_back_unsigned(bw, monkeypatch, tmp_path):
    _stage(bw, monkeypatch, tmp_path)
    code, out = _run_steps(tmp_path, SET_ASIDE, PUT_BACK)
    assert code == 1 and "STOPPED PaperPull.exe is not validly signed" in out, out


@needs_windows
def test_putting_back_checks_each_signer_and_every_interpreter_file(bw, monkeypatch, tmp_path):
    signed = _signed_or_skip()
    one = signed[0].read_bytes()

    stage = _signed_stage(bw, monkeypatch, tmp_path / "signed", one)
    code, out = _run_steps(tmp_path / "signed", PUT_BACK)
    assert code == 0, out
    assert "%d files signed by " % len(SIGNED) in out
    for rel in SIGNED:
        assert _at(stage, rel).read_bytes() == one, rel
    assert not [p for p in (tmp_path / "signed" / "to-sign" / "stage").rglob("*") if p.is_file()]
    for rel in NOT_LISTED[1:]:
        assert _at(stage, rel).read_bytes() == b"MZ", "a package's own file is left as it came"

    # A file a new archive brings that nobody listed.
    _signed_stage(bw, monkeypatch, tmp_path / "new", one, extra="python\\DLLs\\_interpreters.pyd")
    code, out = _run_steps(tmp_path / "new", PUT_BACK)
    assert code == 1 and "STOPPED not signed and not on the list to sign: _interpreters.pyd" in out, out

    if len(signed) > 1:
        _signed_stage(bw, monkeypatch, tmp_path / "odd", one)
        _at(tmp_path / "odd" / "to-sign" / "stage", "python\\DLLs\\_ssl.pyd").write_bytes(
            signed[1].read_bytes())
        code, out = _run_steps(tmp_path / "odd", PUT_BACK)
        assert code == 1 and "STOPPED python\\DLLs\\_ssl.pyd is signed by" in out, out


@needs_windows
def test_the_last_check_reads_each_signed_file_in_the_zip(bw, monkeypatch, tmp_path):
    one = _signed_or_skip()[0].read_bytes()
    for case, unsigned in (("whole", None), ("missed", "python\\DLLs\\_ssl.pyd")):
        root = tmp_path / case
        stage = _signed_stage(bw, monkeypatch, root, one)
        code, out = _run_steps(root, PUT_BACK)
        assert code == 0, out
        if unsigned:
            _at(stage, unsigned).write_bytes(b"MZ")
        bw.zip_it()
        (root / "to-sign" / "installer").mkdir(parents=True)
        (root / "to-sign" / "installer" / "PaperPull-0.0.0-setup.exe").write_bytes(one)
        code, out = _run_steps(root, "Check every shipped program is signed")
        if unsigned:
            assert code == 1 and "_ssl.pyd is not validly signed" in out, out
        else:
            assert code == 0, out
            lines = [line for line in out.splitlines() if " signed by " in line]
            assert len(lines) == len(SIGNED) + 1, out
            assert lines[0].startswith("dist\\PaperPull-0.0.0-setup.exe signed by ")
            assert "zip\\python\\DLLs\\winsound.pyd signed by " in out


# -- every package from the hashed lock ----------------------------------------

def _record_installs(bw, monkeypatch):
    ran = []

    def run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        ran.append((cmd, kw.get("env")))
        if "wheel" in cmd:
            out = Path(cmd[cmd.index("-w") + 1])
            (out / "paperpull_core-0.1.6-py3-none-any.whl").write_bytes(b"PK")
        if cmd[-2:] == ["list", "--format=freeze"]:
            return _Ran("pip==26.2.1\nsetuptools==84.0.0\nplaywright==1.63.0\n")
        return _Ran()

    monkeypatch.setattr(subprocess, "run", run)
    return ran


def test_every_package_comes_from_the_lock_and_nothing_else_is_fetched(bw, monkeypatch, tmp_path):
    ran = _record_installs(bw, monkeypatch)
    py = tmp_path / "python" / "python.exe"
    lock = tmp_path / "requirements-windows-x64.txt"
    bw.install_locked(py, lock)
    assert all(cmd[0] == str(py) for cmd, _ in ran), "only the staged Python runs pip"
    installs = [cmd for cmd, _ in ran if "install" in cmd]
    first = installs[0]
    assert "--require-hashes" in first and first[first.index("-r") + 1] == str(lock)
    assert first[first.index("--only-binary") + 1] == ":all:"
    wheel = next(cmd for cmd, _ in ran if "wheel" in cmd)
    assert "--no-build-isolation" in wheel and "--no-deps" in wheel, "no build backend fetched"
    core = installs[1]
    assert "--no-deps" in core and "--no-index" in core
    assert core[-1].endswith(".whl")
    assert len(installs) == 2, "nothing installed by name"
    assert any(cmd[-1] == "check" for cmd, _ in ran)
    uninstall = next(cmd for cmd, _ in ran if "uninstall" in cmd)
    assert {"pip", "setuptools"} <= set(uninstall)


def test_a_package_set_that_does_not_fit_together_stops_the_build(bw, monkeypatch, tmp_path):
    ran = _record_installs(bw, monkeypatch)
    real = subprocess.run

    def run(cmd, **kw):
        if [str(c) for c in cmd][-1] == "check":
            return _Ran("paperpull-core 0.1.6 requires pypdf, which is not installed.\n", 1)
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as stop:
        bw.install_locked(tmp_path / "python.exe", tmp_path / "lock.txt")
    assert "requires pypdf" in str(stop.value)
    assert not any("uninstall" in cmd for cmd, _ in ran)


def test_each_build_installs_its_own_systems_and_architectures_lock(bw, bm, monkeypatch, tmp_path):
    for mod, system in _builders(bw, bm):
        got = []
        monkeypatch.setattr(mod, "install_locked",
                            lambda py, lock, env=None: got.append((lock, env)))
        for arch in mod.ARCHES:
            monkeypatch.setattr(mod, "ARCH", arch)
            mod.install_packages(tmp_path / "python")
            assert got[-1][0] == PACKAGING / ("requirements-%s-%s.txt" % (system, arch))
            assert got[-1][0].is_file(), got[-1][0]
    assert got[-1][1]["PYTHONNOUSERSITE"] == "1", "the Mac build keeps the user's packages out"


# -- the locks ------------------------------------------------------------------

def _direct_pins() -> dict:
    out = {}
    for line in (PACKAGING / "requirements.in").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            m = re.fullmatch(r"([A-Za-z0-9_.-]+)(\[[^\]]+\])?==(\S+)", line)
            assert m, "every requirement is pinned to one version: %r" % line
            out[_norm(m.group(1))] = m.group(3)
    return out


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries(text: str) -> dict:
    """{package: (version, [hashes])} from a pip requirements file with hashes."""
    out, current = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+) \\", line)
        h = re.fullmatch(r"\s+--hash=sha256:([0-9a-f]{64})( \\)?", line)
        if m:
            current = _norm(m.group(1))
            assert current not in out, "%s twice" % current
            out[current] = (m.group(2), [])
        elif h and current:
            out[current][1].append(h.group(1))
        else:
            raise AssertionError("a line pip would read as something other than a pin: %r" % line)
    return out


def test_every_lock_pins_every_package_with_its_hashes(bw, bm, lock_tool):
    direct = _direct_pins()
    assert {"playwright", "pypdf", "fastapi", "uvicorn", "openpyxl", "pdfplumber",
            "anyio", "setuptools"} <= set(direct)
    for mod, system in _builders(bw, bm):
        for arch in mod.ARCHES:
            text = mod.lock_file(arch).read_text(encoding="utf-8")
            entries = _lock_entries(text)
            assert all(hashes for _, hashes in entries.values()), (system, arch)
            for name, version in direct.items():
                assert entries.get(name, (None,))[0] == version, (system, arch, name)
            # pypdf[crypto] brought its cryptography in, as the core asks.
            assert "cryptography" in entries and "cffi" in entries, (system, arch)
            head = text.split("\n", 4)[:4]
            assert any(mod.PY_VERSION in line for line in head), (system, arch)
            assert any(mod.triple(arch) in line for line in head), (system, arch)
            assert any(lock_tool.AS_OF in line for line in head), (system, arch)
            if system == "macos":
                assert any("macOS %s" % mod.MACOS_MIN in line for line in head), arch


def test_the_desktop_packages_and_the_server_image_pin_the_same_versions():
    server = _lock_entries("\n".join(
        line for line in (REPO / "server" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if not line.startswith("--only-binary")))
    for name, version in _direct_pins().items():
        if name in server:
            assert server[name][0] == version, name


def test_the_lock_tool_resolves_each_lock_for_its_own_platform(bw, bm, lock_tool, monkeypatch):
    targets = lock_tool.targets()
    want = {mod.lock_file(a) for mod, _ in _builders(lock_tool.build_windows, lock_tool.build_macos)
            for a in mod.ARCHES}
    assert {t["lock"] for t in targets} == want and len(targets) == len(want)
    monkeypatch.setenv("UV_INDEX_URL", "https://example.invalid/simple")
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "15.0")
    for t in targets:
        cmd = lock_tool.command(["uv"], t)
        assert cmd[cmd.index("--python-platform") + 1] == t["platform"]
        assert cmd[cmd.index("--python-version") + 1] == bw.PY_VERSION
        assert cmd[cmd.index("--only-binary") + 1] == ":all:"
        assert cmd[cmd.index("--exclude-newer") + 1] == lock_tool.AS_OF
        assert "--generate-hashes" in cmd
        env = lock_tool.environment(t)
        assert "UV_INDEX_URL" not in env and env["UV_NO_CONFIG"] == "1"
        if t["platform"].endswith("apple-darwin"):
            assert env["MACOSX_DEPLOYMENT_TARGET"] == bm.MACOS_MIN
        else:
            assert "MACOSX_DEPLOYMENT_TARGET" not in env


def test_the_lock_tool_writes_every_lock_or_none(lock_tool, monkeypatch, tmp_path):
    targets = []
    for i, t in enumerate(lock_tool.targets()):
        t = dict(t, lock=tmp_path / ("lock-%d.txt" % i))
        t["lock"].write_text("the old lock\n", encoding="utf-8")
        targets.append(t)
    monkeypatch.setattr(lock_tool, "targets", lambda: targets)
    monkeypatch.setattr(lock_tool, "install_uv", lambda folder: ["uv"])
    answers = {t["platform"]: "x==1 \\\n    --hash=sha256:%s\n" % ("a" * 64) for t in targets}
    answers[targets[2]["platform"]] = None
    monkeypatch.setattr(lock_tool, "resolve", lambda uv, t: answers[t["platform"]])
    assert lock_tool.main([]) == 1
    assert all(t["lock"].read_text(encoding="utf-8") == "the old lock\n" for t in targets)

    answers[targets[2]["platform"]] = "x==1 \\\n    --hash=sha256:%s\n" % ("b" * 64)
    assert lock_tool.main(["--check"]) == 1, "every lock differs from what it would write"
    assert all(t["lock"].read_text(encoding="utf-8") == "the old lock\n" for t in targets)
    assert lock_tool.main([]) == 0
    assert lock_tool.main(["--check"]) == 0
    assert targets[2]["lock"].read_text(encoding="utf-8").endswith("b" * 64 + "\n")
