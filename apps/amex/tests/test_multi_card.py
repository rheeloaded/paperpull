"""Tests for multi-card account support, card switcher navigation,
offer dismissal, legacy unnamed record migration, and single-card download ordering (#134).
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amex_docs as app_mod
import amex_site as site
from amex_docs import Document, migrate_legacy_keys
from paperpull_core.models import State

BASE = "https://global.americanexpress.com"


# ---------------------------------------------------------------------------
# Unit Tests: Account name cleaning & Document keying
# ---------------------------------------------------------------------------

def test_clean_account_name():
    assert site.clean_account_name("Amex EveryDay® Card") == "Amex EveryDay Card"
    assert site.clean_account_name("Blue Cash Everyday™") == "Blue Cash Everyday"
    assert site.clean_account_name("  Gold   Card®  ") == "Gold Card"
    assert site.clean_account_name("") == ""


def test_document_key_and_summary_differ_by_card():
    doc1 = Document(
        title="Monthly Statement - October 11, 2026",
        category="Statement",
        date="2026-10-11",
        account="Blue Cash Everyday (12345)",
        summary="Monthly Statement Blue Cash Everyday (12345)",
    )
    doc2 = Document(
        title="Monthly Statement - October 11, 2026",
        category="Statement",
        date="2026-10-11",
        account="Amex EveryDay Card (67890)",
        summary="Monthly Statement Amex EveryDay Card (67890)",
    )
    assert doc1.key != doc2.key
    assert doc1.key.endswith(":Blue Cash Everyday (12345)")
    assert doc2.key.endswith(":Amex EveryDay Card (67890)")


def test_migrate_legacy_keys():
    # Test migration of records where the account exceeded 40 chars and was cut
    long_acct = "Delta SkyMiles Reserve American Express Card (12345)"
    doc = Document(
        title="Monthly Statement - October 11, 2026",
        category="Statement",
        date="2026-10-11",
        account=long_acct,
    )
    old_cut_key = f"Statement:2026-10-11:Monthly Statement - October 11, 2026:{long_acct[:40]}"
    records = {
        old_cut_key: {
            "title": "Monthly Statement - October 11, 2026",
            "account": long_acct,
            "category": "Statement",
            "date": "2026-10-11",
            "state": "Completed",
            "downloaded_ok": True,
        }
    }
    changed = migrate_legacy_keys(records)
    assert changed == 1
    assert doc.key in records
    assert old_cut_key not in records


def test_select_groups_by_card_account():
    """Verify that _select downloads all statements for a single card first,
    ordered newest to oldest, before switching to the other card."""
    app = SimpleNamespace()
    app.args = SimpleNamespace(max_docs=None, start_date=None, end_date=None, doc_types=[])
    app.config = {"default_start_date": "", "document_types": ["Statement"]}
    app.discovery = SimpleNamespace(data={
        "k1": {"category": "Statement", "date": "2026-10-11", "account": "Card B (22222)", "title": "Statement"},
        "k2": {"category": "Statement", "date": "2026-09-18", "account": "Card A (11111)", "title": "Statement"},
        "k3": {"category": "Statement", "date": "2026-08-19", "account": "Card A (11111)", "title": "Statement"},
        "k4": {"category": "Statement", "date": "2026-05-11", "account": "Card B (22222)", "title": "Statement"},
    })
    app._in_scope = lambda doc: True

    selected = app_mod.App._select(app)
    accounts = [d.account for d in selected]
    dates = [d.date for d in selected]

    # All Card A statements should come together, followed by Card B
    assert accounts == ["Card A (11111)", "Card A (11111)", "Card B (22222)", "Card B (22222)"]
    # Within Card A, dates should be descending
    assert dates[:2] == ["2026-09-18", "2026-08-19"]
    # Within Card B, dates should be descending
    assert dates[2:] == ["2026-10-11", "2026-05-11"]


# ---------------------------------------------------------------------------
# Browser integration tests (Playwright against mocked SPA HTML)
# ---------------------------------------------------------------------------

HTML_OVERVIEW = """<!doctype html><html><head><meta charset="utf-8"><title>Account Overview</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
  <span data-testid="simple_switcher_display_number">••••12345</span>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Amex EveryDay® Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<script>
const cb = document.querySelector('[data-testid="simple_switcher_combobox"]');
const opts = document.querySelectorAll('[role="option"]');
cb.addEventListener('click', () => {
  const open = cb.getAttribute('aria-expanded') === 'true';
  cb.setAttribute('aria-expanded', open ? 'false' : 'true');
  opts.forEach(o => o.style.display = open ? 'none' : 'block');
});
opts.forEach(opt => {
  opt.addEventListener('click', () => {
    window.location.href = '/dashboard?account_key=' + opt.getAttribute('data-testid');
  });
});
</script>
</body></html>"""

HTML_DASHBOARD = """<!doctype html><html><head><meta charset="utf-8"><title>Card Dashboard</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox">
  <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
  <span data-testid="simple_switcher_display_number">••••12345</span>
</div>
<a href="/activity/statements?account_key=CARD_1">Statements &amp; Activity</a>
</body></html>"""

HTML_STATEMENTS_CARD1 = """<!doctype html><html><head><meta charset="utf-8"><title>Statements and Year End Summaries</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Amex EveryDay® Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<section>
  <button data-testid="axp-pdf-statements/common/Table/recent-statements/2026-10-11/download-button">Download</button>
</section>
<script>
const cb = document.querySelector('[data-testid="simple_switcher_combobox"]');
const opts = document.querySelectorAll('[role="option"]');
cb.addEventListener('click', () => {
  const open = cb.getAttribute('aria-expanded') === 'true';
  cb.setAttribute('aria-expanded', open ? 'false' : 'true');
  opts.forEach(o => o.style.display = open ? 'none' : 'block');
});
document.querySelector('[data-testid="simple_switcher_product_option_CARD_2"]').addEventListener('click', () => {
  window.location.href = '/activity/statements?account_key=CARD_2';
});
</script>
</body></html>"""

HTML_STATEMENTS_CARD2 = """<!doctype html><html><head><meta charset="utf-8"><title>Statements and Year End Summaries</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Amex EveryDay® Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday®</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Amex EveryDay® Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<section>
  <button data-testid="axp-pdf-statements/common/Table/recent-statements/2026-09-18/download-button">Download</button>
</section>
<script>
const cb = document.querySelector('[data-testid="simple_switcher_combobox"]');
const opts = document.querySelectorAll('[role="option"]');
cb.addEventListener('click', () => {
  const open = cb.getAttribute('aria-expanded') === 'true';
  cb.setAttribute('aria-expanded', open ? 'false' : 'true');
  opts.forEach(o => o.style.display = open ? 'none' : 'block');
});
</script>
</body></html>"""

HTML_OFFER_MODAL = """<!doctype html><html><head><meta charset="utf-8"><title>Offer Dialog</title></head>
<body>
<div role="dialog" aria-modal="true" class="offer-modal">
  <p>Apply for Blue Business Cash</p>
  <button type="button" aria-label="Close">Close</button>
</div>
<script>
document.querySelector('button[aria-label="Close"]').addEventListener('click', () => {
  document.querySelector('.offer-modal').remove();
});
</script>
</body></html>"""


class MockAmexServer:
    def __init__(self):
        self.routes = {
            "/overview": HTML_OVERVIEW,
            "/dashboard": HTML_DASHBOARD,
            "/activity/statements": HTML_STATEMENTS_CARD1,
        }
        self.navigated = []

    def handle(self, route):
        req = route.request
        parts = urlsplit(req.url)
        path = parts.path
        if req.is_navigation_request():
            self.navigated.append(path + ("?" + parts.query if parts.query else ""))
        if "account_key=CARD_2" in parts.query:
            body = HTML_STATEMENTS_CARD2
        elif path in self.routes:
            body = self.routes[path]
        else:
            body = "<p>American Express</p>"
        route.fulfill(content_type="text/html", body=body)


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        b = driver.chromium.launch(headless=True)
    except Exception as e:
        driver.stop()
        pytest.skip(f"no browser available: {e}")
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def open_page(browser):
    contexts = []

    def _open(url_path: str, server: MockAmexServer):
        ctx = browser.new_context()
        contexts.append(ctx)
        ctx.route("**/*", server.handle)
        pg = ctx.new_page()
        pg.goto(BASE + url_path)
        return pg

    yield _open
    for ctx in contexts:
        ctx.close()


def test_dismiss_offer(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_OFFER_MODAL)
    assert pg.locator("[role='dialog']").is_visible()
    site.dismiss_offer(pg)
    assert pg.locator("[role='dialog']").count() == 0
    ctx.close()


def test_list_cards_and_current_card_label(open_page):
    server = MockAmexServer()
    page = open_page("/activity/statements", server)

    cards = site.list_cards(page)
    assert len(cards) == 2
    assert cards[0]["label"] == "Blue Cash Everyday (12345)"
    assert cards[0]["digits"] == "12345"
    assert cards[1]["label"] == "Amex EveryDay Card (67890)"
    assert cards[1]["digits"] == "67890"

    label = site.current_card_label(page)
    assert label == "Blue Cash Everyday (12345)"


def test_select_card_and_collect_download_docs(open_page):
    server = MockAmexServer()
    page = open_page("/activity/statements", server)

    # First card statements
    docs1 = site.collect_download_docs(page, account="Blue Cash Everyday (12345)")
    assert len(docs1) == 1
    assert docs1[0].date_text == "2026-10-11"
    assert docs1[0].account == "Blue Cash Everyday (12345)"

    # Switch to second card
    cards = site.list_cards(page)
    assert site.select_card(page, cards[1]) is True

    # Second card statements
    docs2 = site.collect_download_docs(page, account="Amex EveryDay Card (67890)")
    assert len(docs2) == 1
    assert docs2[0].date_text == "2026-09-18"
    assert docs2[0].account == "Amex EveryDay Card (67890)"


def test_goto_documents_from_overview(open_page):
    server = MockAmexServer()
    page = open_page("/overview", server)

    # Multi-card login lands on /overview: goto_documents clicks a card to reach /dashboard
    # and then reaches /activity/statements.
    assert site.goto_documents(page) is True
    assert "/activity/statements" in page.url
