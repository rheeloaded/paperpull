"""Tests for multi-card account support, card switcher navigation,
and single-card download ordering (#134).
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
from amex_docs import Document
from paperpull_core import pressing
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


def test_select_groups_by_card_account():
    """Verify that _select groups by card account while preserving newest-to-oldest order."""
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


def test_select_pilot_takes_from_both_cards():
    """Verify that a pilot / limited run selects documents across multiple cards
    to test the switch, then groups by card."""
    app = SimpleNamespace()
    app.args = SimpleNamespace(max_docs=None, start_date=None, end_date=None, doc_types=[])
    app.config = {"default_start_date": "", "document_types": ["Statement"]}
    app.discovery = SimpleNamespace(data={
        "k1": {"category": "Statement", "date": "2026-10-11", "account": "Card A (11111)", "title": "Statement"},
        "k2": {"category": "Statement", "date": "2026-09-11", "account": "Card A (11111)", "title": "Statement"},
        "k3": {"category": "Statement", "date": "2026-08-11", "account": "Card A (11111)", "title": "Statement"},
        "k4": {"category": "Statement", "date": "2026-07-11", "account": "Card A (11111)", "title": "Statement"},
        "k5": {"category": "Statement", "date": "2026-06-11", "account": "Card A (11111)", "title": "Statement"},
        "k6": {"category": "Statement", "date": "2026-05-18", "account": "Card B (22222)", "title": "Statement"},
        "k7": {"category": "Statement", "date": "2026-04-18", "account": "Card B (22222)", "title": "Statement"},
        "k8": {"category": "Statement", "date": "2026-03-18", "account": "Card B (22222)", "title": "Statement"},
    })
    app._in_scope = lambda doc: True

    selected = app_mod.App._select(app, limit=5)
    accounts = [d.account for d in selected]
    # Both cards must be included in the pilot of 5
    assert "Card A (11111)" in accounts
    assert "Card B (22222)" in accounts
    assert len(selected) == 5
    # Grouped by card
    assert accounts == ["Card A (11111)", "Card A (11111)", "Card A (11111)", "Card B (22222)", "Card B (22222)"]


def test_one_card_archive_from_main_keeps_its_records():
    """An archive written by main has account='', producing keys ending in :Unnamed.
    On a single-card account, the new code must keep account='' so existing
    downloaded records are recognized and not downloaded again."""
    main_doc = Document(
        title="Monthly Statement - October 11, 2026",
        category="Statement",
        date="2026-10-11",
        account="",
        summary="Monthly Statement",
    )
    assert main_doc.key.endswith(":Unnamed")

    app = SimpleNamespace()
    app.args = SimpleNamespace(redownload=False)
    app.progress = {
        main_doc.key: {"state": State.COMPLETED.value, "downloaded_ok": True}
    }

    # Discovering with a single card produces a doc with account=""
    new_doc = Document(
        title="Monthly Statement - October 11, 2026",
        category="Statement",
        date="2026-10-11",
        account="",
        summary="Monthly Statement",
    )
    assert new_doc.key == main_doc.key
    assert app_mod.App._already_done(app, new_doc) is True


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

HTML_SAME_NAME_NO_NUMBER = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
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
</script>
</body></html>"""

HTML_IN_PLACE_REDRAW = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Amex EveryDay Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<section id="table-area">
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
  setTimeout(() => {
    document.querySelector('[data-testid="simple_switcher_selected_option_display"]').innerHTML = `
      <span data-testid="simple_switcher_display_name">Amex EveryDay Card</span>
      <span data-testid="simple_switcher_display_number">••••67890</span>
    `;
    document.querySelector('#table-area').innerHTML = `
      <button data-testid="axp-pdf-statements/common/Table/recent-statements/2026-09-18/download-button">Download</button>
    `;
  }, 1000);
});
</script>
</body></html>"""

HTML_SWITCH_NEVER_TAKES = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Amex EveryDay Card</span>
    <span data-testid="simple_switcher_display_number">••••67890</span>
  </div>
</div>
<section id="table-area">
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
  // Option clicked but the page never updates to Card 2
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


def test_two_cards_with_same_name_and_no_number_stops_the_run(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_SAME_NAME_NO_NUMBER)
    with pytest.raises(pressing.Stop):
        site.list_cards(pg)
    ctx.close()


def test_card_switch_redraws_in_place_after_delay(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_IN_PLACE_REDRAW)
    cards = site.list_cards(pg)
    assert len(cards) == 2
    # Switch to card 2 which takes 1 second to redraw in place
    assert site.select_card(pg, cards[1]) is True
    # Verify that the switch completed and card 2 statements are collected
    docs = site.collect_download_docs(pg, account=cards[1]["label"])
    assert len(docs) == 1
    assert docs[0].date_text == "2026-09-18"
    assert docs[0].account == "Amex EveryDay Card (67890)"
    ctx.close()


def test_card_switch_that_never_takes_stops_the_run(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_SWITCH_NEVER_TAKES)
    cards = site.list_cards(pg)
    assert len(cards) == 2
    # Switching to card 2 when switch never takes must raise NoAnswer
    with pytest.raises(pressing.NoAnswer):
        site.select_card(pg, cards[1])
    ctx.close()


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
