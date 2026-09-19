"""The MSIX manifest and version, the parts that need no Windows SDK."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))
import msix  # noqa: E402

NS = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
      "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"}


def test_the_store_version_is_four_numbers_with_no_suffix():
    assert msix.store_version("0.19.0") == "0.19.0.0"
    assert msix.store_version("0.19.0-beta.2") == "0.19.0.0"
    assert msix.store_version("1.2") == "1.2.0.0"
    assert msix.store_version("1.2.3.4") == "1.2.3.4"
    with pytest.raises(SystemExit):
        msix.store_version("beta")


def test_the_manifest_is_well_formed_and_says_what_it_must():
    doc = ET.fromstring(msix.manifest("0.19.0.0", msix.identity()))
    ident = doc.find("m:Identity", NS)
    assert ident.get("Version") == "0.19.0.0"
    assert ident.get("ProcessorArchitecture") == "x64"
    app = doc.find("m:Applications/m:Application", NS)
    assert app.get("Executable") == "PaperPull.exe"
    assert app.get("EntryPoint") == "Windows.FullTrustApplication"
    caps = [c.get("Name") for c in doc.findall("m:Capabilities/rescap:Capability", NS)]
    assert caps == ["runFullTrust"]
    visual = app.find("uap:VisualElements", NS)
    for attr in ("Square150x150Logo", "Square44x44Logo"):
        assert visual.get(attr).startswith("Assets\\")
    assert doc.find("m:Properties/m:Logo", NS).text == "Assets\\StoreLogo.png"


def test_every_image_the_manifest_names_is_one_the_build_renders():
    text = msix.manifest("0.19.0.0", msix.identity())
    import re
    named = set(re.findall(r"Assets\\(\w+)\.png", text))
    assert named <= set(msix.ASSETS), named - set(msix.ASSETS)


def test_the_identity_comes_from_the_environment_once_the_store_assigns_it(monkeypatch):
    monkeypatch.delenv("MSIX_IDENTITY_NAME", raising=False)
    assert msix.identity()["name"] == msix.DEFAULT_IDENTITY_NAME
    monkeypatch.setenv("MSIX_IDENTITY_NAME", "12345Rheeloaded.PaperPull")
    monkeypatch.setenv("MSIX_PUBLISHER", "CN=ABCDEF01-2345-6789-ABCD-EF0123456789")
    monkeypatch.setenv("MSIX_PUBLISHER_DISPLAY", "Rheeloaded")
    ident = msix.identity()
    text = msix.manifest("0.19.0.0", ident)
    assert 'Name="12345Rheeloaded.PaperPull"' in text
    assert 'Publisher="CN=ABCDEF01-2345-6789-ABCD-EF0123456789"' in text
    assert "<PublisherDisplayName>Rheeloaded</PublisherDisplayName>" in text


def test_the_launcher_source_honors_the_port_override_and_opens_the_browser():
    src = msix.LAUNCHER_CS
    assert "PAPERPULL_PORT" in src
    assert '"8765"' in src
    assert "-m uvicorn app:app --host 127.0.0.1" in src
    assert "WaitForExit" in src


def test_the_display_name_can_follow_the_spelling_the_store_reserved(monkeypatch):
    monkeypatch.delenv("MSIX_DISPLAY_NAME", raising=False)
    assert "<DisplayName>PaperPull</DisplayName>" in msix.manifest("1.0.0.0", msix.identity())
    monkeypatch.setenv("MSIX_DISPLAY_NAME", "Paperpull")
    text = msix.manifest("1.0.0.0", msix.identity())
    assert "<DisplayName>Paperpull</DisplayName>" in text
    assert 'DisplayName="Paperpull"' in text


def test_the_manifest_can_declare_a_native_arm64_package():
    """One switch builds the Windows on ARM package from the same source.
    x64 stays the default and the name every release has carried."""
    doc = ET.fromstring(msix.manifest("0.24.0.0", msix.identity(), "arm64"))
    assert doc.find("m:Identity", NS).get("ProcessorArchitecture") == "arm64"
    assert ET.fromstring(msix.manifest("0.24.0.0", msix.identity())).find("m:Identity", NS).get("ProcessorArchitecture") == "x64"


def test_sdk_tools_come_from_the_environment_not_a_literal_drive(monkeypatch, tmp_path):
    """A build on a machine whose Program Files is not on C:, or an ARM64
    machine whose native tools live in an arm64 folder, found nothing."""
    real = tmp_path / "PF"
    tool = real / "Windows Kits" / "10" / "bin" / "10.0.26100.0" / "arm64" / "makeappx.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"")
    older = real / "Windows Kits" / "10" / "bin" / "10.0.22621.0" / "x64" / "makeappx.exe"
    older.parent.mkdir(parents=True)
    older.write_bytes(b"")
    monkeypatch.setenv("ProgramW6432", str(real))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "PFx86"))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "ARM64")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    assert msix.find_makeappx() == tool           # the native one, on an ARM64 host
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    assert msix.find_makeappx() == older          # an x64 host never picks arm64 tools
    assert msix.program_files()[0] == str(real)
