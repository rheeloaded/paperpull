"""The line each provider gets in the welcome list, from gui/providers.json.

The list used to show the "What it downloads" column of PROVIDERS.md, which
is written for GitHub and says who tested an app, which issue it came from
and how it reads the site. Someone choosing their bank read "Confirmed by
@watling777 ... (#26)". providers.json holds a short line written for them,
the group the provider sits in, and whether it has been run on a real
account yet, which must agree with the README's Untested rows.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")

REPO = Path(__file__).resolve().parents[2]
CARDS = json.loads((REPO / "gui" / "providers.json").read_text(encoding="utf-8"))

# What the GitHub tables say for maintainers and testers, never for someone
# choosing a provider. Whole words, so Capital One is not taken for an API.
NOT_FOR_THE_WELCOME_LIST = re.compile(
    r"[@#]|\b(nothing clicked|api|maintainer'?s?|contributed|confirmed|diagnose|issues?|"
    r"recordings?|pilot)\b", re.IGNORECASE)


def _apps():
    return sorted(d.name for d in (REPO / "apps").iterdir()
                  if d.is_dir() and app_module._entry_script(d))


def test_every_app_has_a_card_and_every_card_has_an_app():
    assert sorted(CARDS["providers"]) == _apps()


def test_every_line_is_written_for_the_person_choosing():
    for slug, card in CARDS["providers"].items():
        for key in ("gets", "note"):
            text = card.get(key, "")
            if key == "gets":
                assert text, slug
            hits = NOT_FOR_THE_WELCOME_LIST.findall(text)
            assert not hits, (slug, key, hits)
            assert len(text) <= 90, (slug, key, len(text))
            # The house punctuation, and nothing a person has to decode.
            assert not re.search(r"[;:\u2013\u2014`*\[\]|]", text), (slug, key, text)


def test_every_card_is_in_a_group_the_page_can_name():
    groups = CARDS["groups"]
    assert all(isinstance(v, str) and v for v in groups.values())
    for slug, card in CARDS["providers"].items():
        assert card["group"] in groups, slug


def test_not_tested_yet_is_exactly_the_readme_untested_rows():
    untested = set()
    for line in (REPO / "README.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\[`([a-z0-9_]+)`\][^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if m and "**Untested" in m.group(4):
            untested.add(m.group(1))
    marked = {slug for slug, card in CARDS["providers"].items() if card.get("tested", True) is False}
    assert untested and marked == untested
    assert all(card.get("tested", True) in (True, False) for card in CARDS["providers"].values())


def test_the_welcome_list_shows_the_card_never_the_github_table():
    got = {p["slug"]: p for p in app_module.list_providers()}
    assert sorted(got) == _apps()
    for slug, p in got.items():
        card = CARDS["providers"][slug]
        assert p["documents"] == card["gets"], slug
        assert p["group"] == card["group"]
        assert p["category"] == CARDS["groups"][card["group"]]
        assert p["tested"] is card.get("tested", True)
        assert p["note"] == card.get("note", "")
        assert "@" not in p["documents"] and "#" not in p["documents"]
    assert got["att"]["documents"] == "Monthly bills for wireless, fiber and internet"
    assert got["fedex"]["tested"] is False and got["chase"]["tested"] is True
    assert got["ing"]["tested"] is True
    assert got["ing"]["note"] == "Tested on one account so far, a populated archive not yet"


@pytest.mark.parametrize("content", ["{not json", '{"groups": {}}', "[]", '{"groups": [], "providers": []}'])
def test_a_broken_file_means_no_line_never_another_documents_text(content, tmp_path, monkeypatch):
    bad = tmp_path / "providers.json"
    bad.write_text(content, encoding="utf-8")
    monkeypatch.setattr(app_module, "PROVIDER_CARDS", bad)
    assert app_module._provider_notes() == {}
    for p in app_module.list_providers():
        assert p["documents"] == "" and p["note"] == "" and p["tested"] is True


def test_the_page_says_when_a_provider_has_not_been_run_on_a_real_account():
    page = app_module.HTML
    row = page[page.index("function renderTiles()"):]
    row = row[:row.index("\nfunction ")]
    assert "p.tested === false" in row and "Not tested on a real account yet" in row
    assert "esc(p.note)" in row and "esc(p.documents)" in row
