"""The import says why it left "kind_folders": false out (follow-up of the
0.69.0 release review, #201).

tools/migrate.py settings_to_apply leaves kind_folders false out of a config
with no documents folder of its own, which is every config an import makes,
since documents_dir names this computer's folders and never travels. The
import's note says so in words of its own, and an address left out is said
as it always was.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
gui = pytest.importorskip("app")

ADDRESS = ("Its base_url was left out, since it is not an address on the provider's own "
           "site. Set it in the provider's settings.")


def test_nothing_left_out_says_nothing():
    assert gui._left_out_note([]) == ""


def test_an_address_left_out_is_said_as_before():
    assert gui._left_out_note(["base_url", "base_url"]) == ADDRESS


def test_kind_folders_left_out_is_said_with_its_reason_and_never_as_an_address():
    said = gui._left_out_note(["kind_folders"])
    assert "not an address" not in said
    assert "documents folder" in said and "kind_folders" in said, said
    assert "—" not in said and ";" not in said


def test_both_left_out_are_both_said():
    said = gui._left_out_note(["kind_folders", "base_url"])
    assert said.startswith(ADDRESS) and "no folder for each kind" in said, said
