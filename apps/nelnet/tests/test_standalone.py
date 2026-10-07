"""Browser setup and the host guard, against nothing but invented values."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nelnet_docs as docs
import nelnet_site as site


@pytest.mark.parametrize("url", [
    "http://nelnet.studentaid.gov/", "https://nelnet.studentaid.gov.example.org/",
    "https://nelnet.studentaid.gov" + "@" + "evil.example/",
    "https://nelnet.studentaid.gov:444/", "https://studentaid.gov/", "file:///example"])
def test_off_host_requests_are_refused(url):
    assert not site.is_safe_url(url)


def test_a_list_that_stopped_partway_is_kept_and_never_called_whole(tmp_path, monkeypatch, capsys):
    """What was listed before the stop is recorded, the run stops, and the
    listing stays noted as stopped, so no Resume calls the run finished."""
    from paperpull_core import listing
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    config.update({"owner": "Tester", "output_dir": str(tmp_path / "out")})
    (tmp_path / "config.json").write_text(json.dumps(config))
    app = docs.App(docs.build_parser().parse_args(["--discover", "--config", str(tmp_path / "config.json")]))
    failures = []
    monkeypatch.setattr(docs.App, "page", lambda self: object())
    monkeypatch.setattr(docs.App, "check_session", lambda self, page: None)
    monkeypatch.setattr(docs.App, "write_failure", lambda self, step, reason, *a, **kw: failures.append(reason))
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    listed = [site.RawDoc(title="01/15/2024 Statement", date_text="2024-01-15")]

    def stopped(page):
        raise site.ListStopped("the rows stayed the same after its pager button was pressed", listed)
    monkeypatch.setattr(site, "collect_download_docs", stopped)
    with pytest.raises(SystemExit) as code:
        app.cmd_discover()
    assert code.value.code == 1
    assert [r["title"] for r in app.discovery.data.values()] == ["01/15/2024 Statement"]
    assert listing.last(app) == listing.STOPPED
    assert failures == ["the list stopped partway"]
    said = capsys.readouterr().out
    assert "stopped partway" in said and "Discovery complete" not in said


def test_open_browser_uses_its_own_profile_and_port(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    assert config["profile_dir"] == "./browser-profile"
    assert config["cdp_url"] == "http://127.0.0.1:9283"
    profile = tmp_path / "provider-profile"
    config["profile_dir"] = str(profile)
    captured = []
    monkeypatch.setattr(docs.browser_launcher, "open_signin_browser",
                        lambda *a, **kw: captured.append((a, kw)) or "synthetic browser")
    app = docs.App.__new__(docs.App)
    app.config = config
    app.cmd_open_browser()
    args, kwargs = captured[0]
    assert args[0] == str(profile)
    assert str(args[1]) == "9283"
    assert kwargs["mode"] == "auto"
    assert site.is_safe_url(args[2])
