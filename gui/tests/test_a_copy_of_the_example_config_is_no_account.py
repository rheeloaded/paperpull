"""A copy of a provider's example config is not an account.

iCloud keeps both sides of a clash as "config.example 2.json", and Finder's
Duplicate makes "config.example copy.json". Each was listed as an account
named "example 2" or "example copy", which then said it shared a browser
with the real one and asked to change a port in the copy. Every folder is
under tmp_path.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")


@pytest.mark.parametrize("name", ["config.example.json", "config.example 2.json", "config.example 13.json",
                                  "config.example copy.json", "config.example copy 2.json",
                                  "Config.Example 2.json"])
def test_the_example_and_its_copies_are_no_account(tmp_path, name):
    (tmp_path / name).write_text("{}", encoding="utf-8")
    assert app_module._accounts(tmp_path) == ["primary"]


@pytest.mark.parametrize("name, account", [("config.kim.json", "kim"), ("config.example-2.json", "example-2"),
                                           ("config.examples.json", "examples"),
                                           ("config.example 2 kim.json", "example 2 kim")])
def test_another_config_is_still_an_account(tmp_path, name, account):
    (tmp_path / name).write_text("{}", encoding="utf-8")
    assert app_module._accounts(tmp_path) == ["primary", account]
