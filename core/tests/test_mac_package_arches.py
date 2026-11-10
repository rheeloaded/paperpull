"""The Mac package is built for Apple Silicon and for Intel, and a release
carries both (#88).

The Mac build was arm64 only, so an Intel Mac had to run PaperPull from a
checkout. packaging/build_macos.py now takes --arch, the macOS workflow
builds each architecture on a runner of its own, and tools/release.sh and
tools/release_assets.py pick up and label every dmg it makes. A new
architecture added to one of them and not the others would build a dmg no
release ever carries, so they are checked against each other.
"""
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import release_assets  # noqa: E402


@pytest.fixture()
def bm(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "bm_arches", REPO / "packaging" / "build_macos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


def _workflow_arches():
    text = (REPO / ".github" / "workflows" / "build-macos.yml").read_text(encoding="utf-8")
    return dict(re.findall(r"- arch: (\S+)\s+runner: (\S+)", text))


def test_each_arch_fetches_a_python_of_its_own_architecture(bm, monkeypatch):
    monkeypatch.setattr(bm, "ARCH", "arm64")
    assert "-aarch64-apple-darwin-" in bm.pbs_asset()
    monkeypatch.setattr(bm, "ARCH", "x86_64")
    assert "-x86_64-apple-darwin-" in bm.pbs_asset()
    assert bm.pbs_url().endswith("/" + bm.pbs_asset())


def test_each_arch_python_is_pinned_to_its_published_checksum(bm, monkeypatch):
    """The tarball is checked against python-build-standalone's own
    SHA256SUMS before anything is built from it, one digest per arch."""
    assert set(bm.PBS_SHA256) == set(bm.ARCHES)
    assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in bm.PBS_SHA256.values())
    assert len(set(bm.PBS_SHA256.values())) == len(bm.PBS_SHA256), "one tarball each"
    asked = []

    class Fetched(Exception):
        pass

    def fake_fetch(url, dest, sha256=""):
        asked.append((url, dest.name, sha256))
        raise Fetched()

    monkeypatch.setattr(bm, "fetch", fake_fetch)
    for arch in bm.ARCHES:
        monkeypatch.setattr(bm, "ARCH", arch)
        with pytest.raises(Fetched):
            bm.stage_python()
        assert asked[-1] == (bm.pbs_url(), bm.pbs_asset(), bm.PBS_SHA256[arch]), arch


def test_a_download_that_does_not_match_its_checksum_is_deleted_and_stops(bm, tmp_path):
    cached = tmp_path / "python.tar.gz"
    cached.write_bytes(b"the tarball")
    good = hashlib.sha256(b"the tarball").hexdigest()
    bm.fetch("https://example.invalid/never", cached, sha256=good)
    assert cached.exists(), "a matching file is kept and nothing is downloaded"
    with pytest.raises(SystemExit) as stop:
        bm.fetch("https://example.invalid/never", cached, sha256="0" * 64)
    assert not cached.exists(), "the next build downloads it again rather than trust it"
    assert good in str(stop.value)


def test_the_launcher_plist_and_dmg_follow_the_arch_being_built(bm):
    """A launcher compiled for arm64 inside an Intel bundle would not open
    at all on the Mac it was made for."""
    source = (REPO / "packaging" / "build_macos.py").read_text(encoding="utf-8")
    assert '"clang", "-fobjc-arc", "-O2", "-arch", ARCH' in source
    assert '"LSArchitecturePriority": [ARCH]' in source
    assert '"PaperPull-%s-%s.dmg" % (version(), ARCH)' in source


def test_an_intel_mac_will_not_try_to_build_for_apple_silicon(bm, monkeypatch):
    monkeypatch.setattr(bm.sys, "platform", "darwin")
    monkeypatch.setattr(bm, "host_arch", lambda: "x86_64")
    monkeypatch.setattr(bm, "stage_python", lambda: pytest.fail("built anyway"))
    assert bm.main(["--arch", "arm64"]) == 1


def test_the_workflow_builds_every_arch_on_a_runner_of_its_own(bm):
    arches = _workflow_arches()
    assert set(arches) == set(bm.ARCHES)
    assert arches["arm64"] != arches["x86_64"], "each is smoke-tested on its own hardware"
    assert "intel" in arches["x86_64"]


def test_a_release_carries_and_labels_every_dmg_the_workflow_builds():
    script = (REPO / "tools" / "release.sh").read_text(encoding="utf-8")
    notes = release_assets.downloads_section("1.2.3")
    for arch in _workflow_arches():
        name = "PaperPull-1.2.3-%s.dmg" % arch
        assert 'PaperPull-"$VERSION"-%s.dmg' % arch in script, arch
        assert release_assets.label(name, "1.2.3") != name, "%s has no label" % arch
        assert "`%s`" % name in notes, arch
        assert name in release_assets.release_files("1.2.3"), "%s is not required" % arch
