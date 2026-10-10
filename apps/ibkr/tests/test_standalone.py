"""The address allowlist, the regional host rule and the browser setup. Synthetic."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ibkr_docs as docs
import ibkr_site as site


@pytest.mark.parametrize("url", ["https://www.interactivebrokers.com/sso/Login", "https://www.interactivebrokers.co.uk/portal/",
                                 "https://www.interactivebrokers.ie/AccountManagement/"])
def test_the_three_regional_hosts_are_accepted(url):
    assert site.is_safe_url(url)


@pytest.mark.parametrize("url", ["http://www.interactivebrokers.com/", "https://www.interactivebrokers.com.example.org/",
                                 "https://www.interactivebrokers.com" + "@" + "evil.example/", "https://www.interactivebrokers.com:444/",
                                 "https://evil.example/www.interactivebrokers.com", "https://ibkr.example/", "file:///example", "",
                                 "https://www.interactivebrokers.de/", "https://sub.www.interactivebrokers.com/"])
def test_anything_else_is_refused(url):
    assert not site.is_safe_url(url)


def test_an_unlisted_interactive_brokers_domain_gets_a_sentence_not_a_silent_refusal():
    assert site.regional_host_problem("https://www.interactivebrokers.de/portal") is not None
    assert site.regional_host_problem("https://www.interactivebrokers.com/portal") is None
    assert site.regional_host_problem("https://example.org/") is None


def test_the_example_config_has_its_own_port_and_profile():
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    assert config["profile_dir"] == "./browser-profile"
    assert config["cdp_url"] == "http://127.0.0.1:9284"
    assert "browser_profile_mode" not in config


def test_open_browser_uses_its_own_profile_and_the_upstream_launcher(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    profile = tmp_path / "provider-profile"
    config["profile_dir"] = str(profile)
    captured = []
    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser", lambda *a, **kw: captured.append((a, kw)) or "synthetic browser")
    app = docs.App.__new__(docs.App)
    app.config = config
    app.cmd_open_browser()
    args, kwargs = captured[0]
    assert args[0] == str(profile) and str(args[1]) == "9284" and kwargs["mode"] == "auto"
    assert site.is_safe_url(args[2])
