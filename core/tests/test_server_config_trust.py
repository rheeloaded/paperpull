"""On PaperPull Server a config's profile_dir, cdp_url, output_dir and a
provider's url_settings are not taken on trust.

An install's config.json lives in /data, often a shared folder that other
people on the network can write to. Whoever can write it could point a
signed-in browser profile into the share where others read its cookies,
aim cdp_url at a browser on another machine, send documents outside
/data, or send the signed-in browser to a page of their own in place of
the provider's (UKG's base_url). So with PAPERPULL_SERVER=1, load_config
takes the profile from the profiles volume, the way the panel names it,
accepts a cdp_url only on 127.0.0.1 or localhost, refuses an output_dir
that leads outside APPS_ROOT, a link included, and accepts a url_setting
only as an https address under the provider's own domains. On the
desktop every one of them is read exactly as written.

Every folder is a throwaway one under tmp_path.
"""
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import storage


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """A data folder with one install in it, a profiles volume beside it,
    server mode on, and the run's working folder the install, as the panel
    starts a run. Returns the install folder."""
    data = tmp_path / "data"
    install = data / "Testco Statements"
    install.mkdir(parents=True)
    (tmp_path / "profiles").mkdir()
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.chdir(install)
    return install


def write(install: Path, settings: dict, name: str = "config.json") -> Path:
    import json
    path = install / name
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def as_the_panel_writes_it(install: Path, **changed) -> dict:
    settings = {"owner": "", "output_dir": ".", "cdp_url": "http://127.0.0.1:9299",
                "profile_dir": str(install.parent.parent / "profiles" / install.name)}
    settings.update(changed)
    return settings


def link_folder(target: Path, link: Path) -> None:
    """A folder link, a junction on Windows, where a symbolic link needs a
    right this account may not have."""
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


# -- the desktop is untouched ----------------------------------------------------------

def test_on_the_desktop_every_setting_is_read_as_written(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    written = {"output_dir": str(tmp_path / "anywhere"), "profile_dir": str(tmp_path / "p"),
               "cdp_url": "http://192.0.2.7:9222"}
    cfg = storage.load_config(write(tmp_path, written, "my settings.json"))
    assert {key: cfg[key] for key in written} == written
    assert capsys.readouterr().out == ""


# -- the profile ---------------------------------------------------------------------------

def test_a_config_as_the_panel_writes_it_loads_quietly(server, capsys):
    cfg = storage.load_config(write(server, as_the_panel_writes_it(server)))
    assert cfg["profile_dir"] == str(server.parent.parent / "profiles" / "Testco Statements")
    assert cfg["output_dir"] == "." and cfg["cdp_url"] == "http://127.0.0.1:9299"
    assert capsys.readouterr().out == ""


def test_a_profile_pointed_into_the_share_is_not_used(server, capsys):
    shared = str(server / "browser-profile")
    cfg = storage.load_config(write(server, as_the_panel_writes_it(server, profile_dir=shared)))
    assert cfg["profile_dir"] == str(server.parent.parent / "profiles" / "Testco Statements")
    said = capsys.readouterr().out
    assert "profile_dir" in said and "profiles volume" in said and shared in said


@pytest.mark.parametrize("given", [7, ["a"], {"x": 1}, "", "../../elsewhere"])
def test_any_other_profile_is_not_used_either(server, given):
    cfg = storage.load_config(write(server, as_the_panel_writes_it(server, profile_dir=given)))
    assert cfg["profile_dir"] == str(server.parent.parent / "profiles" / "Testco Statements")


def test_a_config_that_names_no_profile_gets_the_volumes(server, capsys):
    settings = as_the_panel_writes_it(server)
    del settings["profile_dir"]
    cfg = storage.load_config(write(server, settings))
    assert cfg["profile_dir"] == str(server.parent.parent / "profiles" / "Testco Statements")
    assert capsys.readouterr().out == ""


def test_a_second_account_has_the_profile_the_panel_gives_it(server):
    settings = as_the_panel_writes_it(server, output_dir="../Testco Statements - spouse",
                                      profile_dir=str(server / "spouse-profile"))
    cfg = storage.load_config(write(server, settings, "config.spouse.json"))
    assert cfg["profile_dir"] == str(server.parent.parent / "profiles"
                                     / "Testco Statements - spouse")


@pytest.mark.parametrize("name", ["settings.json", "config..json", "config.json.bak"])
def test_a_config_by_any_other_name_is_refused_on_the_server(server, name):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server), name))
    assert "config.<account>.json" in str(stopped.value)


# -- the browser a run drives ----------------------------------------------------------------

@pytest.mark.parametrize("cdp", [
    "http://127.0.0.1:9299", "http://localhost:9299", "HTTP://LocalHost:9299",
    "ws://127.0.0.1:9222/devtools/browser/0b3c-41d2", "https://127.0.0.1:9222",
    "http://127.0.0.1", "", None])
def test_a_browser_inside_the_container_is_used(server, cdp):
    settings = as_the_panel_writes_it(server, cdp_url=cdp)
    assert storage.load_config(write(server, settings))["cdp_url"] == cdp


def test_a_config_that_names_no_browser_still_loads(server):
    settings = as_the_panel_writes_it(server)
    del settings["cdp_url"]
    assert "cdp_url" not in storage.load_config(write(server, settings))


@pytest.mark.parametrize("cdp", [
    "http://192.168.1.50:9222", "http://evil.example:9222", "ws://evil.example:9222/devtools",
    "http://127.0.0.1.evil.example:9222", "http://localhost.evil.example:9222",
    "http://evil.example\\@127.0.0.1:9222", "http://evil.example/@127.0.0.1:9222",
    "http://127.0.0.1:9222@evil.example", "http://someone@127.0.0.1:9222",
    "http://127.0.0.1:9222\\@evil.example", "http://127.0.0.1:9222?x=@evil.example",
    "http://[::ffff:c000:207]:9222", "http://0x7f000001:9222", "http://2130706433:9222",
    " http://evil.example:9222", "http://127.0.0.1:9222 evil", "//127.0.0.1:9222",
    "file:///etc/passwd", "127.0.0.1:9222", 9222, ["http://127.0.0.1:9222"],
    "http://localhoſt:9222", "http://127.0.0.١:9222"])
def test_a_browser_anywhere_else_stops_the_run(server, cdp):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server, cdp_url=cdp)))
    said = str(stopped.value)
    assert "cdp_url" in said and "127.0.0.1 or localhost" in said


# -- where documents go ----------------------------------------------------------------------

@pytest.mark.parametrize("out", [".", "", "Statements", "../Testco Statements - spouse"])
def test_a_folder_inside_the_data_folder_is_used(server, out):
    assert storage.load_config(write(server, as_the_panel_writes_it(server, output_dir=out)))[
        "output_dir"] == out


def test_the_data_folder_itself_is_inside_it(server):
    out = str(server.parent)
    assert storage.load_config(write(server, as_the_panel_writes_it(server, output_dir=out)))[
        "output_dir"] == out


@pytest.mark.parametrize("out", ["../..", "../../profiles/Testco Statements", "../../data-other"])
def test_a_folder_outside_the_data_folder_stops_the_run(server, out):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server, output_dir=out)))
    assert "outside" in str(stopped.value) and "output_dir" in str(stopped.value)


def test_an_absolute_folder_elsewhere_stops_the_run(server, tmp_path):
    with pytest.raises(SystemExit):
        storage.load_config(write(server, as_the_panel_writes_it(
            server, output_dir=str(tmp_path / "elsewhere"))))


@pytest.mark.parametrize("key", ["output_dir", "documents_dir"])
def test_a_folder_under_the_home_folder_is_outside_the_data_folder(server, tmp_path,
                                                                    monkeypatch, key):
    """"~" is the home folder of the server's own user, never inside the
    data folder, so it stops the run as any folder outside it does, rather
    than being read as a folder named "~" in the install (#166)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server, **{key: "~/Statements"})))
    assert "outside" in str(stopped.value) and key in str(stopped.value)
    assert [p for p in tmp_path.rglob("*") if p.name.startswith("~")] == []


@pytest.mark.parametrize("out", [7, ["."], {"a": "."}, None])
def test_an_output_dir_that_is_no_text_stops_the_run(server, out):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server, output_dir=out)))
    assert "output_dir" in str(stopped.value)


def test_a_config_that_names_no_output_dir_stops_rather_than_save_outside(server):
    settings = as_the_panel_writes_it(server)
    del settings["output_dir"]
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, settings))
    assert "names no output_dir" in str(stopped.value)


def test_a_linked_folder_that_leads_out_of_the_data_folder_stops_the_run(server, tmp_path):
    """The folder named is inside the data folder by its name, and outside
    it by where the link leads, which is where the files would go."""
    away = tmp_path / "profiles" / "Somebody Else"
    away.mkdir(parents=True)
    link_folder(away, server / "Statements")
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(server, as_the_panel_writes_it(server, output_dir="Statements")))
    assert "outside" in str(stopped.value)


def test_an_install_folder_that_is_a_link_out_of_the_data_folder_stops_the_run(
        tmp_path, monkeypatch):
    """Somebody with the share replaced the whole install folder with a link
    to a folder outside it, and its own config says ".", as every fresh
    install's does."""
    data = tmp_path / "data"
    data.mkdir()
    away = tmp_path / "profiles"
    away.mkdir()
    link_folder(away, data / "Testco Statements")
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setenv("APPS_ROOT", str(data))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(away))
    install = data / "Testco Statements"
    monkeypatch.chdir(install)
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(install, as_the_panel_writes_it(install)))
    assert "outside" in str(stopped.value)


def test_a_linked_folder_that_stays_in_the_data_folder_is_used(server):
    other = server.parent / "Testco Archive"
    other.mkdir()
    link_folder(other, server / "Statements")
    assert storage.load_config(write(server, as_the_panel_writes_it(
        server, output_dir="Statements")))["output_dir"] == "Statements"


# -- the site a provider is reached at -------------------------------------------------------
#
# UKG has no one address, so its base_url names the employer's own UKG site
# and its URL guard allows whatever host that is. A provider declares such a
# setting in AppSpec.url_settings with the domains it may sit under. Testco
# stands in here with two made-up ones.

DOMAINS = ("testco.example", "ready.example")


@pytest.fixture()
def tenant(server, bound_spec):
    """The server fixture, with Testco declaring base_url the way UKG does."""
    storage.bind(replace(bound_spec, url_settings={"base_url": DOMAINS}))
    return server


@pytest.mark.parametrize("address", [
    "https://name.testco.example", "https://name.testco.example/",
    "HTTPS://Name.TestCo.EXAMPLE", "https://x9.testco.example",
    "https://a-b.c.testco.example", "https://secure6.ready.example",
    "https://xn--nme-6cd.testco.example", "", None])
def test_an_address_on_the_providers_own_site_is_used(tenant, address):
    cfg = storage.load_config(write(tenant, as_the_panel_writes_it(tenant, base_url=address)))
    assert cfg["base_url"] == address


def test_a_config_that_names_no_address_still_loads(tenant):
    assert "base_url" not in storage.load_config(write(tenant, as_the_panel_writes_it(tenant)))


@pytest.mark.parametrize("address", [
    "http://name.testco.example", "https://evil.example", "https://evil.example/",
    "https://testco.example", "https://nametestco.example",
    "https://name.testco.example.evil.example", "https://testco.example.evil.example",
    "https://name.testco.example@evil.example", "https://someone@name.testco.example",
    "https://evil.example\\@name.testco.example", "https://evil.example/.name.testco.example",
    "https://evil.example#.name.testco.example", "https://evil.example?.name.testco.example",
    "https://name.testco.example:443", "https://name.testco.example:8443",
    "https://name.testco.example/c/hcm/EDIT/EePayrollDirectDepositSummary",
    "https://name.testco.example?next=https://evil.example", "https://name.testco.example#x",
    "https://name.testco.example//", "https://name.testco.example/\\evil.example",
    "https://name.testco.example.", "https://name..testco.example", "https://-name.testco.example",
    " https://name.testco.example", "https://name.testco.example ", "https://name.testco.example\n",
    "https://name.teſtco.example", "https://nаme.testco.example", "https://name.testco.examplе",
    "//name.testco.example", "name.testco.example", "https:name.testco.example",
    "javascript:alert(1)//.testco.example", "file:///etc/passwd", "data:text/html,hi",
    "https://[::1]", "https://127.0.0.1", 7, True, ["https://name.testco.example"],
    {"href": "https://name.testco.example"}])
def test_an_address_anywhere_else_stops_the_run(tenant, address):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(tenant, as_the_panel_writes_it(tenant, base_url=address)))
    said = str(stopped.value)
    assert "base_url" in said and "https address on testco.example or ready.example" in said
    assert "stopped before opening any page" in said


def test_the_refusal_does_not_repeat_the_address(tenant):
    """A provider's own address can name the person's employer, and a run's
    words reach the panel's run log."""
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(write(tenant, as_the_panel_writes_it(
            tenant, base_url="https://employer-name.testco.example:8443")))
    assert "employer-name" not in str(stopped.value)


def test_an_address_is_held_for_a_second_account_too(tenant):
    settings = as_the_panel_writes_it(tenant, output_dir="../Testco Statements - spouse",
                                      base_url="https://evil.example")
    with pytest.raises(SystemExit):
        storage.load_config(write(tenant, settings, "config.spouse.json"))


def test_only_the_settings_a_provider_declares_are_held(tenant):
    """A setting the provider has not named as its address is not judged
    as one, whatever it holds."""
    settings = as_the_panel_writes_it(tenant, note="http://evil.example")
    assert storage.load_config(write(tenant, settings))["note"] == "http://evil.example"


def test_a_provider_without_an_address_setting_reads_base_url_as_any_other(server):
    settings = as_the_panel_writes_it(server, base_url="http://evil.example")
    assert storage.load_config(write(server, settings))["base_url"] == "http://evil.example"


def test_on_the_desktop_an_address_is_read_as_written(tmp_path, monkeypatch, bound_spec):
    storage.bind(replace(bound_spec, url_settings={"base_url": DOMAINS}))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    written = {"output_dir": str(tmp_path / "anywhere"), "base_url": "http://evil.example/x"}
    assert storage.load_config(write(tmp_path, written))["base_url"] == "http://evil.example/x"


@pytest.mark.parametrize("domains", [
    "testco.example", ("*.testco.example",), ("https://testco.example",), ("Testco.example",),
    ("testco.example/",), ("testco",), (), ("testco.example", 7), ["testco.example"]])
def test_a_provider_must_declare_plain_domains(bound_spec, domains):
    with pytest.raises(ValueError) as refused:
        replace(bound_spec, url_settings={"base_url": domains})
    assert "url_settings['base_url']" in str(refused.value)
