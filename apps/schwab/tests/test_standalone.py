"""Synthetic checks for upstream-compatible browser setup and URL guards."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schwab_docs as docs
import schwab_site as site


@pytest.mark.parametrize("url", ["http://client.schwab.com/", "https://client.schwab.com.example.org/",
    "https://client.schwab.com" + "@" + "evil.example/", "https://client.schwab.com:444/", "file:///example"])
def test_off_host_requests_are_refused(url):
    assert not site.is_safe_url(url)


def test_open_browser_uses_its_own_profile_and_upstream_launcher(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    assert config["profile_dir"] == "./browser-profile"
    assert config["cdp_url"] == "http://127.0.0.1:9245"
    assert "browser_profile_mode" not in config
    profile = tmp_path / "provider-profile"
    config["profile_dir"] = str(profile)
    captured = []
    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser", lambda *a, **kw: captured.append((a, kw)) or "synthetic browser")
    app = docs.App.__new__(docs.App);app.config = config
    app.cmd_open_browser()
    args, kwargs = captured[0]
    assert args[0] == str(profile)
    assert str(args[1]) == "9245"
    assert kwargs["mode"] == "auto"
    assert site.is_safe_url(args[2])
