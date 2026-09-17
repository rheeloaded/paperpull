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


def test_the_launcher_source_honours_the_port_override_and_opens_the_browser():
    src = msix.LAUNCHER_CS
    assert "PAPERPULL_PORT" in src
    assert '"8765"' in src
    assert "-m uvicorn app:app --host 127.0.0.1" in src
    assert "WaitForExit" in src
