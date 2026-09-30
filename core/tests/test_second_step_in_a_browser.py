"""A revealed control whose name holds a "/" is pressed like any other.

Several providers answer a Download button with a small menu, and
second_step finds the entry that finishes the download by the words it
showed. It found it with a pattern built from those words by re.escape,
which has left "/" alone since Python 3.7, and Playwright ends a pattern
at a bare "/" because it writes the pattern into its selector between
slashes. The locator raised InvalidSelectorError, second_step caught it
and moved on, and "View/print PDF", which every scaffold's vocabulary
names, could never be pressed. Nothing said so.

In a real browser, because the selector is parsed in the browser and a
unit test of the Python pattern passes either way.
"""
import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core.controls import second_step  # noqa: E402

VOCABULARY = re.compile(
    r"^\s*(download|download\s+pdf|save\s+(as\s+)?pdf|pdf|"
    r"(regular|standard|full)\s+pdf|view\s*\/\s*print\s+pdf|print)\s*$", re.I)
ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update"]


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        launched = driver.chromium.launch(headless=True, args=ARGS)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield launched
    launched.close()
    driver.stop()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def menu(entry: str, role: str = "") -> str:
    tag = "a href='#'" if role == "link" else "div role='menuitem'" if role == "menuitem" else "button"
    close = tag.split()[0]
    return "<body><div role='menu'><%s>%s</%s></div></body>" % (tag, entry, close)


def everyone(text):
    return True


def test_a_revealed_control_with_a_slash_in_its_name_is_found(page):
    page.set_content(menu("View/print PDF"))
    loc, text = second_step(page, {"View/print PDF"}, VOCABULARY, everyone)
    assert text == "View/print PDF", "the entry was never found"
    assert loc.inner_text() == "View/print PDF"


@pytest.mark.parametrize("role", ["", "link", "menuitem"])
def test_each_kind_of_control_it_tries_is_found(page, role):
    page.set_content(menu("View / Print PDF", role))
    loc, text = second_step(page, {"View / Print PDF"}, VOCABULARY, everyone)
    assert loc is not None and loc.inner_text() == "View / Print PDF"


def test_a_name_with_no_slash_is_found_as_before(page):
    page.set_content(menu("Regular PDF"))
    loc, text = second_step(page, {"Regular PDF"}, VOCABULARY, everyone)
    assert text == "Regular PDF" and loc.inner_text() == "Regular PDF"


def test_the_whole_name_must_match(page):
    """Escaping the slash must not loosen the match. A longer control that
    merely contains the words is not the one that was revealed."""
    page.set_content(menu("View/print PDF of every bill"))
    loc, text = second_step(page, {"View/print PDF"}, VOCABULARY, everyone)
    assert loc is None and text == ""


def test_the_guard_still_has_the_last_word(page):
    page.set_content(menu("View/print PDF"))
    loc, text = second_step(page, {"View/print PDF"}, VOCABULARY, lambda t: False)
    assert loc is None and text == ""


@pytest.mark.parametrize("text", ["View/print PDF", "Q3 (Jul/Sep) statement", "a/b/c",
                                  "Download \\/ PDF", "07/31/2026"])
def test_escaping_for_a_locator_finds_the_text_in_every_kind_of_locator(page, text):
    """get_by_role reads a pattern the way JavaScript reads a literal, and
    get_by_text and has_text read it another way, so all three are asked."""
    from html import escape
    from paperpull_core.controls import escape_for_locator
    page.set_content("<body><button>%s</button></body>" % escape(text))
    pat = re.compile("^" + escape_for_locator(text) + "$")
    assert page.get_by_role("button", name=pat).count() == 1
    assert page.get_by_text(pat).count() == 1
    assert page.locator("button").filter(has_text=pat).count() == 1


# -- through each app's own vocabulary and guard ------------------------------

def uses_second_step(app: Path) -> bool:
    site = app / ("%s_site.py" % app.name)
    return site.exists() and "second_step as _core_second_step" in site.read_text(
        encoding="utf-8", errors="ignore")


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and uses_second_step(d))


def site_of(app: Path):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


def test_this_asks_every_app_that_hands_the_core_its_words():
    assert len(APPS) >= 12, [a.name for a in APPS]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_each_app_presses_a_revealed_view_print_pdf(app, page):
    site = site_of(app)
    page.set_content(menu("View/print PDF"))
    loc, text = site._second_step(page, {"View/print PDF"})
    assert text == "View/print PDF", \
        "%s's second step could not find a revealed View/print PDF" % app.name
    assert loc.inner_text() == "View/print PDF"
