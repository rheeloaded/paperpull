"""A copy of a provider's example config is not an account, until somebody
fills it in.

iCloud keeps both sides of a clash as "config.example 2.json", and Finder's
Duplicate makes "config.example copy.json". Each was listed as an account
named "example 2" or "example copy", which then said it shared a browser
with the real one and asked to change a port in the copy. A copy that holds
only the example's settings is passed over now. One somebody filled in is
their account, listed and run, and the port check Login makes reads the
same configs. Every folder is under tmp_path and every value is made up.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")

EXAMPLE = {"owner": "", "output_dir": ".", "profile_dir": "./browser-profile", "browser": "auto",
           "cdp_url": "http://127.0.0.1:9351", "document_types": ["Statement"],
           "//note": "A made-up comment.", "pilot_count": 5}


def write(path: Path, cfg) -> None:
    path.write_text(cfg if isinstance(cfg, str) else json.dumps(cfg), encoding="utf-8")


def ports():
    mod = app_module._ports()
    assert mod is not None, "the panel reads the core beside it"
    return mod


@pytest.mark.parametrize("name", ["config.example.json", "config.example 2.json", "config.example 13.json",
                                  "config.example copy.json", "config.example copy 2.json",
                                  "Config.Example 2.json"])
def test_the_example_and_its_copies_are_no_account(tmp_path, name):
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / name, EXAMPLE)
    assert app_module._accounts(tmp_path) == ["primary"]
    assert app_module._config_files(tmp_path) == []


@pytest.mark.parametrize("copy", [
    dict(EXAMPLE, **{"//note": "Another made-up comment."}),
    {k: v for k, v in EXAMPLE.items() if k != "pilot_count"},
], ids=["other comments", "without a setting the example gained"])
def test_a_copy_nobody_filled_in_is_no_account(tmp_path, copy):
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / "config.example 2.json", copy)
    assert app_module._accounts(tmp_path) == ["primary"]


@pytest.mark.parametrize("name, account", [("config.kim.json", "kim"), ("config.example-2.json", "example-2"),
                                           ("config.examples.json", "examples"),
                                           ("config.example 2 kim.json", "example 2 kim")])
def test_another_config_is_still_an_account(tmp_path, name, account):
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / name, EXAMPLE)
    assert app_module._accounts(tmp_path) == ["primary", account]


FILLED_IN = {
    "an owner": dict(EXAMPLE, owner="Invented Person"),
    "a folder": dict(EXAMPLE, output_dir="../Card Statements - kim"),
    "a port": dict(EXAMPLE, cdp_url="http://127.0.0.1:9401"),
    "a setting added": dict(EXAMPLE, default_start_date="2031-01-01"),
    "no cdp_url": {k: v for k, v in EXAMPLE.items() if k != "cdp_url"},
    "unreadable": '{"owner": "Invented Person",',
}


@pytest.mark.parametrize("copy", sorted(FILLED_IN))
@pytest.mark.parametrize("name, account", [("config.example 2.json", "example 2"),
                                           ("config.example copy.json", "example copy")])
def test_a_copy_somebody_filled_in_is_their_account(tmp_path, name, account, copy):
    """Copied from the example by Finder and filled in for a second person,
    without a new name. Hidden, it would never run and nothing would say
    so."""
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / name, FILLED_IN[copy])
    assert app_module._accounts(tmp_path) == ["primary", account]
    assert app_module._config_files(tmp_path) == [tmp_path / name]


def test_a_copy_beside_no_example_is_listed(tmp_path):
    write(tmp_path / "config.example 2.json", EXAMPLE)
    assert app_module._accounts(tmp_path) == ["primary", "example 2"]


def test_the_panel_lists_the_configs_login_checks_the_ports_of(tmp_path):
    """Whatever the copy holds, the panel's accounts and the configs the
    port check reads are the same ones."""
    shapes = dict(FILLED_IN, untouched=EXAMPLE)
    for i, (what, copy) in enumerate(sorted(shapes.items())):
        d = tmp_path / str(i)
        d.mkdir()
        write(d / "config.json", dict(EXAMPLE, owner="Invented Person"))
        write(d / "config.example.json", EXAMPLE)
        write(d / "config.example copy.json", copy)
        write(d / "config.kim.json", dict(EXAMPLE, cdp_url="http://127.0.0.1:9402"))
        listed = app_module._accounts(d)
        checked = [ports().account_of(p) for p in ports().configs_of(d)]
        assert listed == checked, what
        assert ("example copy" in listed) == (what != "untouched"), what


def test_export_history_takes_the_people_the_panel_lists(tmp_path):
    """Export history reads each person's folder from their config, and an
    untouched copy is no person there either."""
    migrate = app_module._migrate_module()
    assert migrate is not None
    write(tmp_path / "config.json", dict(EXAMPLE, owner="Invented Person"))
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / "config.example 2.json", EXAMPLE)
    write(tmp_path / "config.example copy.json", FILLED_IN["a folder"])
    assert [label for label, _ in migrate.account_configs(tmp_path)] == ["primary", "example copy"]


def test_without_the_core_only_the_example_itself_is_passed_over(tmp_path, monkeypatch):
    """An account hidden is never run, so a copy is listed when there is
    nothing to tell it by."""
    monkeypatch.setattr(app_module, "_ports", lambda: None)
    write(tmp_path / "config.example.json", EXAMPLE)
    write(tmp_path / "config.example 2.json", EXAMPLE)
    assert app_module._accounts(tmp_path) == ["primary", "example 2"]
