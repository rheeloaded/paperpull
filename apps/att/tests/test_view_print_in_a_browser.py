"""AT&T's "View/print PDF" button is found by the patterns that name it.

Both of the places that look for it by role used a pattern reading
view\\s*/\\s*print, and Playwright writes a pattern into its selector
between slashes, so the bare "/" ended it early. The locator raised
InvalidSelectorError, the caller caught it, and the button was never found
by _pdf_button (since round three) or by the fallback _view_print_button
(since round six). Nothing said so.

In a real browser, because the selector is parsed in the browser and a
unit test of the Python pattern passes either way.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_site as site

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


def test_the_fallback_finds_the_view_print_button(page):
    page.set_content("<body><button>Download PDF</button><button>View/print PDF</button></body>")
    el, label = site._view_print_button(page)
    assert label == "View/print PDF", "the fallback never found its button"
    assert el.inner_text() == "View/print PDF"


def test_the_fallback_finds_it_as_a_link_with_spaces_too(page):
    page.set_content("<body><a href='#'>View / print PDF</a></body>")
    el, label = site._view_print_button(page)
    assert label == "View / print PDF"


def test_the_pdf_button_falls_back_to_view_print(page):
    """A bill whose only PDF control is View/print PDF. _pdf_button tried
    PDF_BUTTON_RE for exactly this and found nothing."""
    page.set_content("<body><button>View/print PDF</button></body>")
    el, label = site._pdf_button(page)
    assert label == "View/print PDF"


def test_the_pdf_button_still_prefers_download_pdf(page):
    page.set_content("<body><button>View/print PDF</button><button>Download PDF</button></body>")
    el, label = site._pdf_button(page)
    assert label == "Download PDF"


def test_the_menu_entry_is_still_found_by_its_words(page):
    """The menu under Download PDF is made of plain elements, found by text.
    get_by_text read the old pattern too, so this pins that the escaped
    one still matches there."""
    page.set_content("<body><div class='menu'><div>Regular PDF</div>"
                     "<div>View/print PDF</div></div></body>")
    el, label = site._menu_entry(page, site._VIEW_PRINT_RE, wait_ms=0)
    assert label == "View/print PDF"


def test_nothing_else_is_taken_for_it(page):
    page.set_content("<body><button>View/print PDF of every bill</button>"
                     "<button>Print</button></body>")
    assert site._view_print_button(page) == (None, "")
