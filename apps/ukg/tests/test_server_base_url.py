"""On PaperPull Server, base_url has to be on UKG's own site.

UKG has no one address, so base_url names the employer's UKG site, the
sign-in browser opens it, and ukg_site.is_safe_url allows whatever host it
names. On the server config.json sits in a shared folder, so somebody who
can write there could send the signed-in browser to a page of their own,
which the Browser Screen then shows as UKG's. So there the core stops a
run, the sign-in included, unless base_url is an https address on
ultipro.com or saashr.com. Here the app's own --open-browser runs with the
sign-in browser itself replaced, so nothing is opened. The desktop reads
base_url as written.

Every folder is a throwaway one under tmp_path.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
import ukg_site as site

ukg_docs = importlib.import_module("ukg_docs")


@pytest.fixture()
def opened(monkeypatch):
    """Every page a sign-in browser was asked to open. No browser starts,
    and the fake answers as one that did, since a window that did not open
    ends the sign-in with NOTHING_OPENED instead."""
    pages = []

    def open_signin_browser(profile, port, url, **_kw):
        pages.append(url)
        return "Chrome"

    monkeypatch.setattr(ukg_docs.browser_launcher, "open_signin_browser", open_signin_browser)
    # A run's log file is not what this is about, and the root logger lasts
    # the whole test session.
    monkeypatch.setattr(ukg_docs.App, "_setup_logging", lambda self: None)
    monkeypatch.setattr(site, "BASE", site.BASE)
    monkeypatch.setattr(site, "URLS", dict(site.URLS))
    return pages


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """A data folder with a UKG install in it, server mode on, and the
    run's working folder the install, as the panel starts a run."""
    install = tmp_path / "data" / "UKG Pay Statements"
    install.mkdir(parents=True)
    (tmp_path / "profiles").mkdir()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.chdir(install)
    return install


def config(folder: Path, base_url) -> Path:
    path = folder / "config.json"
    path.write_text(json.dumps({
        "owner": "Pat", "output_dir": ".", "cdp_url": "http://127.0.0.1:9334",
        "profile_dir": "./browser-profile", "base_url": base_url}), encoding="utf-8")
    return path


def sign_in(path: Path):
    return ukg_docs.main(["--open-browser", "--config", str(path)])


def test_ukg_declares_base_url_with_its_own_domains():
    assert storage.SPEC.url_settings == {"base_url": ("ultipro.com", "saashr.com")}


@pytest.mark.parametrize("address", [
    "https://example.ultipro.com", "https://example.ultipro.com/", "https://Example2.UltiPro.com",
    "https://secure6.saashr.com", "https://xxxx.ultipro.com", "https://secureN.saashr.com"])
def test_a_ukg_address_opens_on_the_server(server, opened, address):
    """The examples config.example.json and the README give, and a real
    tenant's shape, all pass, and every page the app then builds is one its
    own URL guard allows."""
    assert sign_in(config(server, address)) == 0
    assert opened == [address.rstrip("/")]
    built = list(site.URLS.values()) + [site.api_url("/pay/companies")]
    assert built and all(site.is_safe_url(url) for url in built)


@pytest.mark.parametrize("address", [
    "https://evil.example", "https://example.ultipro.com.evil.example",
    "https://evilultipro.com", "https://ultipro.com", "http://example.ultipro.com",
    "https://example.ultipro.com@evil.example", "https://evil.example\\@example.ultipro.com",
    "https://example.ultipro.com:8443", "https://example.ultipro.com/c/hcm/EDIT/EePayrollDirectDepositSummary",
    "https://example.ultipro.com?next=https://evil.example", "https://example.ultipro.com.",
    "https://exampleultipro.com", "https://example.ſaashr.com", "https://yourhost/wfc/",
    " https://example.ultipro.com", 7])
def test_any_other_address_stops_the_sign_in_before_a_browser_opens(server, opened, address):
    with pytest.raises(SystemExit) as stopped:
        sign_in(config(server, address))
    said = str(stopped.value)
    assert "base_url" in said and "https address on ultipro.com or saashr.com" in said
    assert opened == []
    assert site.BASE != address


def test_on_the_server_no_base_url_still_opens_ukgs_own_sign_in(server, opened):
    """Before base_url is set, the sign-in opens UKG's general page, a fixed
    address in the code, so the person can find their employer's."""
    assert sign_in(config(server, "")) == 0
    assert opened == ["https://www.ukg.com/login"]


def test_on_the_desktop_base_url_is_read_as_written(tmp_path, monkeypatch, opened):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.chdir(tmp_path)
    assert sign_in(config(tmp_path, "https://evil.example")) == 0
    assert opened == ["https://evil.example"]
