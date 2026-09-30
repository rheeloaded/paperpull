"""Text holding a "/", put into a pattern an app hands a locator, is found.

These apps build a pattern from text they read, a button's whole name, a
row's account, a card's label, a document's title, and each used re.escape,
which has left "/" alone since Python 3.7. Playwright writes a pattern into
its selector between slashes and ends it at a bare one, so the locator
raised InvalidSelectorError when used, and every caller caught it. For
Apple Card, Chase and U.S. Bank nothing else looked, and the control was
never found. E*TRADE's caller fell back to a locator that reads a pattern
differently, so its builder is asked directly.

Apps whose text cannot hold a slash today are covered by the census in
test_every_app_hands_playwright_a_pattern_it_can_read instead.

In a real browser, because the selector is parsed in the browser and a
unit test of the Python pattern passes either way.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run",
        "--disable-background-networking", "--disable-component-update"]


def site_of(name: str):
    for loaded in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[loaded]
    sys.path.insert(0, str(REPO / "apps" / name))
    try:
        return importlib.import_module("%s_site" % name)
    finally:
        sys.path.pop(0)


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


def test_apple_card_finds_a_button_by_a_whole_name_holding_a_slash(page):
    site = site_of("applecard")
    page.set_content("<body><button>Statement 08/31/2026</button>"
                     "<button>Statement 08/31/2026 and more</button></body>")
    found = site._exactly_named(page, "Statement 08/31/2026")
    assert found.count() == 1
    assert found.first.inner_text() == "Statement 08/31/2026"


def test_chase_finds_the_row_of_an_account_whose_name_holds_a_slash(page):
    site = site_of("chase")
    page.set_content(
        "<body><a href='#'>Aug 09, 2026 Statement FREEDOM/FLEX (...1234) Saves document</a>"
        "<a href='#'>Aug 09, 2026 Statement SAPPHIRE (...9876) Saves document</a></body>")
    rx = site.row_label_re("2026-08-09", "FREEDOM/FLEX (...1234)", "Saves document")
    rows = page.get_by_role("link", name=rx)
    assert rows.count() == 1
    assert "FREEDOM/FLEX" in rows.first.inner_text()


def test_us_bank_picks_a_card_whose_label_holds_a_slash(page, monkeypatch):
    site = site_of("usbank")
    page.set_content("""<body>
      <div data-testid="account-dropdown">
        <button aria-expanded="false" aria-label="Choose a card"
                onclick="document.getElementById('cards').hidden = false">
          Account Altitude Go (...1111)</button>
        <ul id="cards" role="listbox" hidden>
          <li role="option" onclick="window.chosen = this.innerText">Altitude Go (...1111)</li>
          <li role="option" onclick="window.chosen = this.innerText">Cash+/Visa Signature (...2222)</li>
        </ul>
      </div></body>""")
    monkeypatch.setattr(page, "wait_for_timeout", lambda ms: None)
    assert site.select_account(page, "Cash+/Visa Signature (...2222)") is True
    assert page.evaluate("window.chosen") == "Cash+/Visa Signature (...2222)"


def test_etrade_names_a_document_whose_title_holds_a_slash(page):
    site = site_of("etrade")
    page.set_content("<body><a href='#'>Form 1099/Supplemental PDF</a>"
                     "<a href='#'>Form 1099 PDF</a></body>")
    links = page.get_by_role("link", name=site._title_name_re("Form 1099/Supplemental"))
    assert links.count() == 1
    assert links.first.inner_text() == "Form 1099/Supplemental PDF"
