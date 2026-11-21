from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def browser_page():
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("Playwright Chromium is unavailable")
        browser = playwright.chromium.launch()
        try:
            yield browser.new_page(accept_downloads=True)
        finally:
            browser.close()
