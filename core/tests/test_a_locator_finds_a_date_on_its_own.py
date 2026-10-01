"""A locator handed identity.on_its_own_pattern finds a date only as a
number of its own.

A string handed to has_text, get_by_text or get_by_role finds its words
anywhere on the page, so "1/5/2025" picks out "11/5/2025" as well, which
is how a January bill and a January statement were taken for November's
(Dominion, Ally, USAA). on_its_own_pattern is the rule identity.on_its_own
already holds a document's text to, compiled for a locator.

Every kind of locator is driven in a real browser here, since a pattern
is handed to the page as a script's own pattern and some kinds read a
bare slash as its end. Nothing here reaches a real site.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import identity  # noqa: E402

PAGE = """<!doctype html><html><body>
<button>Bill 11/5/2025</button>
<button>Bill 1/5/2025</button>
<button>Bill 1/5/20250</button>
<a href="#" title="Statement 5 Jan 2025">5 Jan 2025</a>
<a href="#" title="Statement 15 Jan 2025">15 Jan 2025</a>
<p>Posted September&nbsp; 06,
   2026</p>
</body></html>"""


def test_a_date_is_found_only_as_a_number_of_its_own():
    p = identity.on_its_own_pattern("1/5/2025")
    assert p.search("Bill 1/5/2025 paid")
    assert p.search("bill dated 1/5/2025.")
    assert not p.search("Bill 11/5/2025")
    assert not p.search("Bill 1/5/20250")
    assert not identity.on_its_own_pattern("1/5/20").search("1/5/2025")
    assert not identity.on_its_own_pattern("5 Jan 2025").search("15 Jan 2025")


def test_it_matches_in_any_capitals_and_any_spacing():
    p = identity.on_its_own_pattern("September 06, 2026")
    assert p.search("SEPTEMBER 06, 2026")
    assert p.search("September\u00a0 06,\n   2026")
    assert p.search("Sep\u00adtember 06,\u200b 2026")
    assert not p.search("September 6, 2026")


def test_it_is_the_rule_on_its_own_holds_a_document_to():
    for variant in ("1/5/2025", "Jan 5, 2025", "$1.23", "2025-01-05", "05 Jan 2025"):
        for text in ("x 1/5/2025 y", "11/5/2025", "jan 5, 2025", "$31.23", "$1.23",
                     "2025-01-05t10:00", "a2025-01-05", "15 jan 2025", "05 jan 2025"):
            assert identity.on_its_own(variant, text) == bool(
                identity.on_its_own_pattern(variant).search(text)), (variant, text)


def test_nothing_to_look_for_matches_nothing():
    """A has_text of None filters nothing out, so the first row would be
    taken for a date that was blank."""
    for blank in ("", "   ", None):
        p = identity.on_its_own_pattern(blank)
        assert not p.search("Bill 1/5/2025") and not p.search(""), repr(blank)


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive, %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    pg = ctx.new_page()
    pg.set_content(PAGE)
    yield pg
    browser.close()
    driver.stop()


def test_every_kind_of_locator_takes_it(page):
    """get_by_role and get_by_title read a pattern as a script's own
    pattern, where a bare slash ends it, so the pattern's slash is
    escaped. has_text and get_by_text read it either way."""
    jan = identity.on_its_own_pattern("1/5/2025")
    assert "\\/" in jan.pattern
    assert page.get_by_role("button", name=jan).all_inner_texts() == ["Bill 1/5/2025"]
    assert page.locator("button").filter(has_text=jan).all_inner_texts() == ["Bill 1/5/2025"]
    assert page.get_by_text(jan).all_inner_texts() == ["Bill 1/5/2025"]
    five = identity.on_its_own_pattern("5 Jan 2025")
    assert page.get_by_title(five).all_inner_texts() == ["5 Jan 2025"]
    assert page.get_by_role("link", name=five).all_inner_texts() == ["5 Jan 2025"]


def test_a_plain_string_finds_the_longer_date_as_well(page):
    """What the pattern is for. A string is found inside a longer number."""
    assert page.locator("button").filter(has_text="1/5/2025").count() == 3
    assert page.get_by_role("button", name="1/5/2025").count() == 3


def test_the_page_spacing_its_date_its_own_way_is_still_found(page):
    p = identity.on_its_own_pattern("September 06, 2026")
    assert page.locator("p").filter(has_text=p).count() == 1
    assert isinstance(p, re.Pattern)


def test_nothing_to_look_for_finds_no_row(page):
    assert page.locator("button").filter(has_text=identity.on_its_own_pattern("")).count() == 0
