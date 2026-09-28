"""A press and hold check is known however it spells its and.

The check a tester met on Target on 0.39.1 said "Press & hold" (#48), with
an ampersand. Walmart listed that spelling. Eight other apps listed only
"press and hold", and their check compares the page's words with each marker
as it is written, so the same check would have gone unnoticed there too.

Found by what the code says rather than by app name, so a new app that
lists one spelling is held to both.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SITES = sorted(p for p in (REPO / "apps").glob("*/*_site.py")
               if "press and hold" in p.read_text(encoding="utf-8", errors="ignore").lower()
               or "press & hold" in p.read_text(encoding="utf-8", errors="ignore").lower())


def test_there_are_apps_to_look_at():
    assert len(SITES) >= 10, [p.parent.name for p in SITES]


@pytest.mark.parametrize("site", SITES, ids=lambda p: p.parent.name)
def test_both_spellings_are_listed(site):
    text = site.read_text(encoding="utf-8", errors="ignore")
    assert '"press and hold"' in text and '"press & hold"' in text, site.parent.name
