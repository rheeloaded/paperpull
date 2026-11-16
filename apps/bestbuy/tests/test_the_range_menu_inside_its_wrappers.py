"""The range menu is pressed through its own button when the parts around
it and inside it carry test ids that start the same way (#226).

A tester's purchase history drew the range menu as a button inside two
wrappers, all three the same size, with the label and the icon inside the
button, and every one of the five carried a test id starting with the
menu's. The menu was found and its press checked by that prefix, so the
check counted three elements drawn in the menu's place, pressed nothing,
and every run stopped at "choose a year". Now the button carrying the test
id is the one found, and the press names it by its tag and its whole test
id, so neither the wrappers nor the parts inside it count. A page where
only a wrapper carries the test id is pressed through the wrapper as
before.

A year drawn as an option around an element of its own size would have
stopped the same way once the menu opened, the year being named by its tag
alone. It is named by its role now.

Every page here is made up, shaped like the nodes the tester's file
recorded, and so is every word and test id on it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_site as site
from paperpull_core import failure

sync_api = pytest.importorskip("playwright.sync_api")

TESTID = "YearDate-Filter-TestID"

# Each part of the tester's menu, the outer wrapper, the inner one, the
# button, its label and its icon, with a test id of its own or all with one.
OWN_IDS = tuple(TESTID + s for s in ("", "-container", "-button", "-label", "-icon"))
ONE_ID = (TESTID,) * 5

BOX = ("display: flex; width: 200px; height: 48px; margin: 0; padding: 0; border: 0; "
       "box-sizing: border-box")
OPEN = "said('menu'); document.getElementById('years').hidden = false"

YEARS = """<ul id="years" hidden><li onclick="said('2026')">2026</li>
<li onclick="said('2025')">2025</li></ul>"""

# Each press is written down where the test can read it.
LOG = ("<script>function said(w) { document.getElementById('log').textContent += w + ';'; }"
       "</script>")


def page_of(menu, years=YEARS):
    return ('<!doctype html><html><body><output id="log"></output>%s%s%s</body></html>'
            % (menu, years, LOG))


def wrapped(ids=OWN_IDS, label="Past 3 Years"):
    """The tester's shape, a div holding a div holding the button, all three
    200 by 48, the button holding its label and a 24 by 24 icon."""
    outer, inner, button, words, icon = ids
    return ('<div data-testid=\'%s\' style="%s">'
            '<div class="relative" id="range-box" data-testid=\'%s\' style="%s; position: relative">'
            '<button type="button" class="relative" id="range" role="combobox" data-testid=\'%s\' '
            'style="%s; position: relative; align-items: center" onclick="%s">'
            '<span data-testid=\'%s\' style="display: flow-root">%s</span>'
            '<div data-testid=\'%s\' style="width: 24px; height: 24px"></div>'
            '</button></div></div>') % (outer, BOX, inner, BOX, button, BOX, OPEN, words, label,
                                        icon)


def one_button(label="Past 3 Years"):
    return ('<button type="button" data-testid="%s" onclick="%s">%s</button>'
            % (TESTID, OPEN, label))


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def show(browser, monkeypatch):
    monkeypatch.setattr(site, "hide_survey", lambda page: None)
    context = browser.new_context()

    def open_page(html):
        page = context.new_page()
        page.set_content(html)
        return page

    yield open_page
    context.close()


def said(page):
    return [w for w in page.locator("#log").inner_text().split(";") if w]


# What the tester's file recorded of the five, every field but the label's
# box, which is as wide as the font draws it.
RECORDED = [
    {"tag": "div", "signal_classes": [], "has_id": False, "has_testid": True, "role": "",
     "box": [200, 48], "display": "flex", "position": "static", "text_len": 12},
    {"tag": "div", "signal_classes": ["relative"], "has_id": True, "has_testid": True,
     "role": "", "box": [200, 48], "display": "flex", "position": "relative", "text_len": 12},
    {"tag": "button", "signal_classes": ["relative"], "has_id": True, "has_testid": True,
     "role": "combobox", "box": [200, 48], "display": "flex", "position": "relative",
     "text_len": 12},
    {"tag": "span", "signal_classes": [], "has_id": False, "has_testid": True, "role": "",
     "display": "flow-root", "position": "static", "text_len": 12},
    {"tag": "div", "signal_classes": [], "has_id": False, "has_testid": True, "role": "",
     "box": [24, 24], "display": "block", "position": "static", "text_len": 0},
]


@pytest.mark.parametrize("ids", [OWN_IDS, ONE_ID], ids=["own test ids", "one test id"])
def test_the_made_up_menu_is_shaped_as_the_tester_recorded(show, ids):
    page = show(page_of(wrapped(ids)))
    got = {e["name"]: e for e in failure.census(page, site.FALLBACK)}
    menu = got["year_menu"]
    assert (menu["matched"], menu["visible"]) == (5, 5)
    for node, recorded in zip(menu["nodes"], RECORDED):
        assert {k: node[k] for k in recorded} == recorded


@pytest.mark.parametrize("ids", [OWN_IDS, ONE_ID], ids=["own test ids", "one test id"])
def test_the_menu_inside_its_wrappers_is_pressed_through_its_button(show, ids):
    page = show(page_of(wrapped(ids)))
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


@pytest.mark.parametrize("ids", [OWN_IDS, ONE_ID], ids=["own test ids", "one test id"])
def test_the_years_are_read_from_the_menu_inside_its_wrappers(show, ids):
    page = show(page_of(wrapped(ids)))
    assert site.year_choices(page) == ["2026", "2025"]
    assert said(page) == ["menu"]


def test_a_wrapper_wider_than_the_menu_with_words_of_its_own_is_not_pressed(show):
    """The wrapper carries the menu's test id and words beside the button.
    Only the button is pressed."""
    html = page_of(
        '<div data-testid="%s" style="display: flex; width: 300px; height: 48px" '
        'onclick="if (event.target === this) said(\'wrapper\')">'
        '<span style="width: 100px" onclick="said(\'words\')">Showing</span>'
        '<button type="button" data-testid="%s-button" style="%s" onclick="%s">Past 3 Years'
        '</button></div>' % (TESTID, TESTID, BOX, OPEN))
    page = show(html)
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]
    page = show(html)
    assert site.year_choices(page) == ["2026", "2025"]
    assert said(page) == ["menu"]


def test_a_menu_whose_test_id_only_its_wrapper_carries_is_pressed_through_the_wrapper(show):
    """No button carries the test id. The one element that does is pressed,
    as before, and the press lands on the button inside it."""
    html = page_of('<div data-testid="%s" style="%s"><button type="button" style="%s" '
                   'onclick="%s">Past 3 Years</button></div>' % (TESTID, BOX, BOX, OPEN))
    page = show(html)
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]
    page = show(html)
    assert site.year_choices(page) == ["2026", "2025"]
    assert said(page) == ["menu"]


def test_a_second_button_with_a_test_id_that_starts_the_same_is_never_pressed(show):
    """The first button carrying a test id that starts with the menu's reads
    "All Orders". It is not the menu, so nothing is pressed."""
    page = show(page_of(
        '<button type="button" data-testid="%s-Type" style="%s" onclick="said(\'orders\')">'
        'All Orders</button>' % (TESTID, BOX) + wrapped()))
    with pytest.raises(site.Refused):
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    with pytest.raises(site.Refused):
        site.year_choices(page)
    assert said(page) == []


@pytest.mark.parametrize("menu", [one_button(), wrapped()], ids=["one button", "wrapped"])
def test_a_menu_drawn_after_the_choice_began_is_waited_for(show, monkeypatch, menu):
    """The page has no menu as pick_year begins. Its first step draws it in
    a task queued behind that step, and the menu is still pressed."""
    page = show(page_of(""))
    assert page.locator("button").count() == 0

    def draws_the_menu(p):
        p.evaluate("(html) => setTimeout(() => document.body.insertAdjacentHTML("
                   "'beforeend', html), 0)", menu)

    monkeypatch.setattr(site, "hide_survey", draws_the_menu)
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


def test_a_test_id_that_would_end_the_selector_still_names_the_button_alone(show):
    """The press names the button by its whole test id, written so that no
    character in it ends the selector."""
    odd = TESTID + '-"a\\b] c'
    page = show(page_of(wrapped(OWN_IDS[:2] + (odd,) + OWN_IDS[3:])))
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


# Years drawn as options, each holding an element of its own size, and each
# inside an element of its own size.
OPTIONS = """<div id="years" role="listbox" hidden>
<div role="option" onclick="said('2026')"><div>2026</div></div>
<div role="option" onclick="said('2025')"><div>2025</div></div></div>"""
OPTIONS_WRAPPED = """<div id="years" role="listbox" hidden>
<div><div role="option" onclick="said('2026')">2026</div></div>
<div><div role="option" onclick="said('2025')">2025</div></div></div>"""


@pytest.mark.parametrize("years", [OPTIONS, OPTIONS_WRAPPED],
                         ids=["option around the year", "option inside a wrapper"])
@pytest.mark.parametrize("menu", [one_button(), wrapped()], ids=["one button", "wrapped"])
def test_a_year_drawn_as_an_option_is_pressed(show, menu, years):
    page = show(page_of(menu, years))
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


def test_an_option_that_reads_more_than_its_year_is_pressed_at_the_year(show):
    """The option also says how many purchases the year holds, so it does
    not read as the year. The element reading the year alone is pressed, as
    before, and the press reaches the option around it."""
    page = show(page_of(one_button(), """<div id="years" role="listbox" hidden>
<div role="option" onclick="said('2025')"><div>2025</div><div>4 purchases</div></div></div>"""))
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


def test_the_survey_counts_the_menus_own_button(show):
    """Diagnose and a failure file count the button the run presses as well
    as everything the menu's test id matches."""
    page = show(page_of(wrapped()))
    got = {e["name"]: e for e in failure.census(page, site.FALLBACK)}
    assert got["year_menu"]["matched"] == 5
    assert (got["year_menu_button"]["matched"], got["year_menu_button"]["visible"]) == (1, 1)
    assert got["year_menu_button"]["nodes"][0]["role"] == "combobox"
