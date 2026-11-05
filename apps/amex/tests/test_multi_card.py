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


HTML_SAME_LABEL_AND_NUMBER = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
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
    <span data-testid="simple_switcher_display_name">Blue Cash Everyday</span>
    <span data-testid="simple_switcher_display_number">••••12345</span>
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

HTML_ONE_CARD_MISSING_DIGITS = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
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
    <span data-testid="simple_switcher_display_name">Amex EveryDay</span>
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

HTML_FOOTER_HELP_LINE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<section id="table-area">
  <p>Statement period: October 2026</p>
</section>
<footer>
  <p>If there are no statements available yet, please contact customer care.</p>
</footer>
</body></html>"""

HTML_GERMAN_NO_STATEMENTS = """<!doctype html><html><head><meta charset="utf-8"><title>Abrechnungen</title></head>
<body>
<section id="table-area">
  <p>Es liegen keine Abrechnungen vor.</p>
</section>
</body></html>"""

HTML_GERMAN_PAPERLESS_NOTICE = """<!doctype html><html><head><meta charset="utf-8"><title>Abrechnungen</title></head>
<body>
<section id="table-area">
  <p>Sie erhalten keine Abrechnungen per Post.</p>
</section>
</body></html>"""

HTML_EVAL_DISABLED_DELAYED_REDRAW = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<script>
window.eval = function () { throw new Error('eval is disabled'); };
</script>
</head>
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
  <button id="old-btn" data-testid="axp-pdf-statements/common/Table/recent-statements/2026-10-11/download-button">Download</button>
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
  }, 100);
  setTimeout(() => {
    document.querySelector('#table-area').innerHTML = `
      <button data-testid="axp-pdf-statements/common/Table/recent-statements/2026-09-18/download-button">Download</button>
    `;
  }, 1200);
});
</script>
</body></html>"""

HTML_EMPTY_CARD_TRANSITION = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Empty Card</span>
    <span data-testid="simple_switcher_display_number">••••11111</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Empty Card</span>
    <span data-testid="simple_switcher_display_number">••••11111</span>
  </div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Full Card</span>
    <span data-testid="simple_switcher_display_number">••••22222</span>
  </div>
</div>
<section id="table-area">
  <p id="empty-msg">No billing statements available</p>
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
      <span data-testid="simple_switcher_display_name">Full Card</span>
      <span data-testid="simple_switcher_display_number">••••22222</span>
    `;
  }, 100);
  setTimeout(() => {
    document.querySelector('#table-area').innerHTML = `
      <button data-testid="axp-pdf-statements/common/Table/recent-statements/2026-09-18/download-button">Download</button>
    `;
  }, 1200);
});
</script>
</body></html>"""

HTML_TURNED_OFF_CARD_OPTION = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title></head>
<body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">
    <span data-testid="simple_switcher_display_name">Active Card</span>
    <span data-testid="simple_switcher_display_number">••••11111</span>
  </div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Active Card</span>
    <span data-testid="simple_switcher_display_number">••••11111</span>
  </div>
  <button disabled data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">
    <span data-testid="simple_switcher_display_name">Canceled Card</span>
    <span data-testid="simple_switcher_display_number">••••99999</span>
  </button>
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


def test_select_limit_1_with_two_cards_returns_one():
    """Verify that --max-docs 1 with 2 cards in discovery returns at most 1 document (#134)."""
    app = SimpleNamespace()
    app.args = SimpleNamespace(max_docs=None, start_date=None, end_date=None, doc_types=[])
    app.config = {"default_start_date": "", "document_types": ["Statement"]}
    app.discovery = SimpleNamespace(data={
        "k1": {"category": "Statement", "date": "2026-10-11", "account": "Card A (11111)", "title": "Statement"},
        "k2": {"category": "Statement", "date": "2026-09-18", "account": "Card B (22222)", "title": "Statement"},
    })
    app._in_scope = lambda doc: True
    selected = app_mod.App._select(app, limit=1)
    assert len(selected) == 1


def test_ensure_card_digits_extraction(monkeypatch):
    """Verify that ensure_card extracts digits strictly from (digits)
    rather than mixing in product numbers like 2% (#134)."""
    fake_page = SimpleNamespace()
    monkeypatch.setattr(site, "_current_card_digits", lambda p: "12345")
    assert site.ensure_card(fake_page, "Blue Cash 2% Everyday (12345)") is True


def test_two_cards_with_same_label_and_same_number_stops_the_run(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_SAME_LABEL_AND_NUMBER)
    with pytest.raises(pressing.Stop) as exc_info:
        site.list_cards(pg)
    assert exc_info.value.reason == "two cards share a label"
    ctx.close()


def test_multiple_cards_where_one_has_no_digits_stops_the_run(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_ONE_CARD_MISSING_DIGITS)
    with pytest.raises(pressing.Stop) as exc_info:
        site.list_cards(pg)
    assert exc_info.value.reason == "a card has no account number"
    ctx.close()


def test_has_no_statements_ignores_footer_and_detects_german(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_FOOTER_HELP_LINE)
    # Help text inside <footer> should NOT trigger has_no_statements
    assert site.has_no_statements(pg) is False

    pg.set_content(HTML_GERMAN_NO_STATEMENTS)
    # German phrase inside <section> should trigger has_no_statements
    assert site.has_no_statements(pg) is True
    ctx.close()


def test_cmd_discover_stops_when_statements_page_fails_twice(monkeypatch):
    """cmd_discover must raise SystemExit(0) when goto_documents fails twice."""
    app = SimpleNamespace()
    app.page = lambda: SimpleNamespace(url="https://global.americanexpress.com/dashboard")
    app.check_session = lambda p: None
    monkeypatch.setattr(app_mod.listing, "started", lambda a: None)
    monkeypatch.setattr(site, "goto_documents", lambda p: False)

    with pytest.raises(SystemExit) as exc:
        app_mod.App.cmd_discover(app)
    assert exc.value.code == 0


def test_cmd_discover_stops_when_card_has_zero_buttons_and_no_message(monkeypatch):
    """cmd_discover must raise SystemExit(0) when a card has 0 buttons and no empty message."""
    app = SimpleNamespace()
    app.page = lambda: SimpleNamespace(url="https://global.americanexpress.com/activity/statements")
    app.check_session = lambda p: None
    monkeypatch.setattr(app_mod.listing, "started", lambda a: None)
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "list_cards", lambda p: [{"index": 0, "tid": "1", "label": "Card 1 (11111)", "digits": "11111", "name": "Card 1"},
                                                        {"index": 1, "tid": "2", "label": "Card 2 (22222)", "digits": "22222", "name": "Card 2"}])
    monkeypatch.setattr(site, "select_card", lambda p, c: True)
    monkeypatch.setattr(site, "collect_download_docs", lambda p, account="": [])
    monkeypatch.setattr(site, "has_no_statements", lambda p: False)

    with pytest.raises(SystemExit) as exc:
        app_mod.App.cmd_discover(app)
    assert exc.value.code == 0


def test_cmd_discover_single_card_preserves_unnamed_key(monkeypatch):
    """cmd_discover with one card listed passes account='' to collect_download_docs,
    preserving the :Unnamed key from main."""
    app = SimpleNamespace()
    app.page = lambda: SimpleNamespace(url="https://global.americanexpress.com/activity/statements")
    app.check_session = lambda p: None
    app.args = SimpleNamespace(start_date=None)
    app.config = {"default_start_date": "", "document_types": ["Statement"]}
    app.rules = []
    app.stats = {"discovered": 0, "skipped_out_of_scope": 0}
    app._record_rawdoc = lambda r, url: app_mod.App._record_rawdoc(app, r, url)
    stored_keys = {}
    app.discovery = SimpleNamespace(
        data=stored_keys,
        get=lambda k: stored_keys.get(k),
        update=lambda k, v, save=False: stored_keys.setdefault(k, v),
        save=lambda **k: None,
    )
    monkeypatch.setattr(app_mod.listing, "started", lambda a: None)
    monkeypatch.setattr(app_mod.listing, "read_whole", lambda a: None)
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "list_cards", lambda p: [{"index": 0, "tid": "1", "label": "Only Card (12345)", "digits": "12345", "name": "Only Card"}])
    monkeypatch.setattr(site, "collect_download_docs", lambda p, account="": [
        site.RawDoc(title="Monthly Statement - October 11, 2026", date_text="2026-10-11", href="tid1", account=account)
    ])
    monkeypatch.setattr(app_mod.doc_types, "should_skip", lambda t, r: False)
    monkeypatch.setattr(app_mod.doc_types, "classify_document", lambda t, r: ("Statement", "Monthly Statement", "high"))
    monkeypatch.setattr(app_mod.doc_types, "wanted", lambda c, cfg: True)

    n = app_mod.App.cmd_discover(app, quiet=True)
    assert n == 1
    assert len(stored_keys) == 1
    recorded_key = list(stored_keys.keys())[0]
    assert recorded_key.endswith(":Unnamed")


def test_download_one_leaves_missing_card_for_manual_review(monkeypatch):
    """When a document's card is not found in the switcher, download_one leaves
    the document in State.NEEDS_MANUAL_REVIEW and returns cleanly without raising."""
    app = SimpleNamespace()
    app._card_count = 2
    app.discovery = SimpleNamespace(data={})
    app.paths = SimpleNamespace(
        folder_for=lambda c: Path("/tmp"),
        manual_review=Path("/tmp/manual_review"),
    )
    app.config = {"max_path_length": 200, "min_pdf_bytes": 100}
    app.stats = {"duplicate_filenames": 0, "manual_review": 0}
    app.check_session = lambda p: None
    recorded = []
    app._record = lambda doc, st, notes="": recorded.append((st, notes))
    app._write_row = lambda *a, **k: None

    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "ensure_card", lambda p, acct: False)  # Card not in switcher

    doc = Document(title="Monthly Statement", category="Statement", date="2026-10-11",
                   account="Closed Card (99999)")
    fake_page = SimpleNamespace()
    app_mod.App.download_one(app, fake_page, doc, "stmt.pdf")

    assert len(recorded) == 1
    state, notes = recorded[0]
    assert state == State.NEEDS_MANUAL_REVIEW
    assert "Could not switch to card" in notes or "not found in switcher" in notes


def test_download_one_leaves_no_account_on_multicard_for_manual_review(monkeypatch):
    """When a document has no account on a multi-card login, download_one leaves
    the document in State.NEEDS_MANUAL_REVIEW and returns cleanly without downloading."""
    app = SimpleNamespace()
    app._card_count = 2
    app.discovery = SimpleNamespace(data={})
    app.paths = SimpleNamespace(
        folder_for=lambda c: Path("/tmp"),
        manual_review=Path("/tmp/manual_review"),
    )
    app.config = {"max_path_length": 200, "min_pdf_bytes": 100}
    app.stats = {"duplicate_filenames": 0, "manual_review": 0}
    app.check_session = lambda p: None
    recorded = []
    app._record = lambda doc, st, notes="": recorded.append((st, notes))
    app._write_row = lambda *a, **k: None

    monkeypatch.setattr(site, "goto_documents", lambda p: True)

    doc = Document(title="Monthly Statement", category="Statement", date="2026-10-11",
                   account="")
    fake_page = SimpleNamespace()
    app_mod.App.download_one(app, fake_page, doc, "stmt.pdf")

    assert len(recorded) == 1
    state, notes = recorded[0]
    assert state == State.NEEDS_MANUAL_REVIEW
    assert "multiple cards" in notes


def test_card_switch_with_eval_disabled(browser):
    """Amex turns window.eval off. select_card must wait for the old button to hide
    via driver-level wait_for_element_state, not evaluate(), and succeed."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_EVAL_DISABLED_DELAYED_REDRAW)
    cards = site.list_cards(pg)
    assert len(cards) == 2
    assert site.select_card(pg, cards[1]) is True
    docs = site.collect_download_docs(pg, account=cards[1]["label"])
    assert len(docs) == 1
    assert docs[0].date_text == "2026-09-18"
    assert docs[0].account == "Amex EveryDay Card (67890)"
    ctx.close()


def test_card_switch_empty_to_full_card(browser):
    """When switching from an empty card to a full card, select_card must hold the
    previous card's empty message and wait until it clears, not returning immediately."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_EMPTY_CARD_TRANSITION)
    assert site.has_no_statements(pg) is True
    cards = site.list_cards(pg)
    assert len(cards) == 2
    assert site.select_card(pg, cards[1]) is True
    # Card 2 has statements, not an empty message
    assert site.has_no_statements(pg) is False
    docs = site.collect_download_docs(pg, account=cards[1]["label"])
    assert len(docs) == 1
    assert docs[0].date_text == "2026-09-18"
    ctx.close()


def test_cmd_discover_one_empty_card_one_full_card(browser, monkeypatch):
    """cmd_discover on an account with Card 1 empty and Card 2 having statements
    completes cleanly and records Card 2's statements."""
    app = SimpleNamespace()
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_EMPTY_CARD_TRANSITION)
    app.page = lambda: pg
    app.check_session = lambda p: None
    stored_docs = {}
    app.discovery = SimpleNamespace(
        data=stored_docs,
        update=lambda k, v, save=False: stored_docs.setdefault(k, v),
        save=lambda **k: None,
    )
    app._record_rawdoc = lambda r, url: 1
    monkeypatch.setattr(app_mod.listing, "started", lambda a: None)
    monkeypatch.setattr(app_mod.listing, "read_whole", lambda a: None)
    monkeypatch.setattr(site, "goto_documents", lambda p: True)

    app.stats = {"discovered": 0}
    n = app_mod.App.cmd_discover(app, quiet=True)
    assert n == 1
    ctx.close()


def test_card_switch_turned_off_option_leaves_its_card(browser, monkeypatch):
    """A disabled/turned off card option in the switcher is not pressed. The
    card is marked for Discover to go on without it, the switcher is closed
    so nothing covers the next press, and the card on show stays on show."""
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_TURNED_OFF_CARD_OPTION)
    cards = site.list_cards(pg)
    assert len(cards) == 2
    # Card 2 is disabled
    assert site.select_card(pg, cards[1]) is False
    assert cards[1]["turned_off"] is True
    assert pg.locator(site._SWITCHER_COMBOBOX_SEL).get_attribute("aria-expanded") == "false"
    assert site.current_card_label(pg) == "Active Card (11111)"
    ctx.close()


def test_german_paperless_notice_not_treated_as_no_statements(browser):
    """The notice 'Sie erhalten keine Abrechnungen per Post' must not match has_no_statements."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.set_content(HTML_GERMAN_PAPERLESS_NOTICE)
    assert site.has_no_statements(pg) is False
    ctx.close()


def test_download_one_on_single_card_does_not_call_list_cards(monkeypatch):
    """On a single-card account, download_one does not call list_cards when doc.account is empty."""
    app = SimpleNamespace()
    app._card_count = 1
    app.paths = SimpleNamespace(
        folder_for=lambda c: Path("/tmp"),
        manual_review=Path("/tmp/manual_review"),
    )
    app.config = {"max_path_length": 200, "min_pdf_bytes": 100}
    class _Stats(dict):
        def __missing__(self, key):
            if key in ("new_files", "dates"):
                self[key] = []
            else:
                self[key] = 0
            return self[key]

    app.stats = _Stats()
    app.check_session = lambda p: None
    app.discovery = SimpleNamespace(data={})
    app.journal = SimpleNamespace(checkpoint=lambda *a, **kw: None)
    app._record = lambda *a, **kw: None
    app._write_row = lambda *a, **kw: None

    called = []
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "list_cards", lambda p: called.append("list_cards") or [])
    monkeypatch.setattr(site, "download_document", lambda p, c, d, o: True)
    monkeypatch.setattr(site, "close_file_type_dialog", lambda p, quiet=True: None)
    monkeypatch.setattr(app_mod.receipt_pdf, "validate_pdf",
                        lambda *a, **kw: SimpleNamespace(ok=True, message="", size_bytes=1000, page_count=1))

    doc = Document(title="Monthly Statement", category="Statement", date="2026-10-11", account="")
    fake_page = SimpleNamespace()
    app_mod.App.download_one(app, fake_page, doc, "stmt.pdf")

    assert called == [], "list_cards should not be called for single-card account downloads"


# ---------------------------------------------------------------------------
# A card switch, on pages made for what each wait is there for
# ---------------------------------------------------------------------------

def statement_row(date: str) -> str:
    """One row, with its Download twice, the copy for a wide window and the
    hidden one for a narrow window, the wide one first."""
    tid = "axp-pdf-statements/common/Table/recent-statements/%s/download-button" % date
    return ('<div class="row"><button class="dl" data-testid="%s">Download</button>'
            '<button class="dl mobile" style="display:none" data-testid="%s">Download</button></div>'
            % (tid, tid))


def switch_page(area: str, on_switch: str = "", style: str = "") -> str:
    """A statements page with eval off and two cards, Alpha on show, that
    counts the presses of Bravo's option in #presses. `area` is what the
    statements area holds and `on_switch` what pressing Bravo's option does,
    with moveSwitcher() to show Bravo in the switcher and draw(html) to fill
    the statements area."""
    def card(name, digits):
        return ('<span data-testid="simple_switcher_display_name">%s</span>'
                '<span data-testid="simple_switcher_display_number">••••%s</span>' % (name, digits))
    return """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<script>window.eval = function () { throw new Error('eval is disabled'); };</script>
<style>%(style)s</style></head><body>
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;">
  <div data-testid="simple_switcher_selected_option_display">%(alpha)s</div>
</div>
<div role="listbox">
  <div data-testid="simple_switcher_product_option_CARD_1" role="option" style="display:none;">%(alpha)s</div>
  <div data-testid="simple_switcher_product_option_CARD_2" role="option" style="display:none;">%(bravo)s</div>
</div>
<section id="table-area">%(area)s</section>
<span id="presses">0</span>
<script>
const cb = document.querySelector('[data-testid="simple_switcher_combobox"]');
const opts = document.querySelectorAll('[role="option"]');
const area = document.getElementById('table-area');
function moveSwitcher() {
  document.querySelector('[data-testid="simple_switcher_selected_option_display"]').innerHTML = `%(bravo)s`;
}
function draw(html) { area.innerHTML = html; }
cb.addEventListener('click', () => {
  const open = cb.getAttribute('aria-expanded') === 'true';
  cb.setAttribute('aria-expanded', open ? 'false' : 'true');
  opts.forEach(o => o.style.display = open ? 'none' : 'block');
});
document.querySelector('[data-testid="simple_switcher_product_option_CARD_2"]').addEventListener('click', () => {
  const presses = document.getElementById('presses');
  presses.textContent = Number(presses.textContent) + 1;
  cb.setAttribute('aria-expanded', 'false');
  opts.forEach(o => o.style.display = 'none');
  %(on_switch)s
});
</script></body></html>""" % {"alpha": card("Alpha Card", "11111"), "bravo": card("Bravo Card", "22222"),
                              "area": area, "on_switch": on_switch, "style": style}


@pytest.fixture
def page_of(browser):
    """A page in a context of its own, drawn from the html handed to it."""
    contexts = []

    def _page(html: str):
        ctx = browser.new_context()
        contexts.append(ctx)
        pg = ctx.new_page()
        pg.set_content(html)
        return pg

    yield _page
    for ctx in contexts:
        ctx.close()


def test_a_list_none_of_whose_downloads_shows_stops_before_the_switch(page_of):
    """A button that does not show reads as gone from the start, so with every
    Download hidden there is nothing to hold, and the old list would be taken
    for the new card's. The card is not pressed, and the switcher is closed."""
    pg = page_of(switch_page(statement_row("2030-11-11"), style=".dl { display: none; }"))
    cards = site.list_cards(pg)
    with pytest.raises(pressing.Stop) as stop:
        site.select_card(pg, cards[1])
    assert stop.value.reason == "no download button shows"
    assert pg.locator("#presses").inner_text() == "0"
    assert pg.locator(site._SWITCHER_COMBOBOX_SEL).get_attribute("aria-expanded") == "false"


def test_discover_stops_on_a_switch_that_failed_for_any_other_reason(monkeypatch):
    """Only a card the page has turned off is gone on from. Any other False
    from select_card is a switch that failed, which stops Discover."""
    app = SimpleNamespace()
    app.page = lambda: SimpleNamespace(url="https://global.americanexpress.com/activity/statements")
    app.check_session = lambda p: None
    noted = []
    monkeypatch.setattr(app_mod.listing, "started", lambda a: None)
    monkeypatch.setattr(app_mod.listing, "read_whole", lambda a: noted.append("whole"))
    monkeypatch.setattr(site, "goto_documents", lambda p: True)
    monkeypatch.setattr(site, "list_cards", lambda p: [
        {"index": 0, "tid": "1", "label": "Card 1 (11111)", "digits": "11111", "name": "Card 1"},
        {"index": 1, "tid": "2", "label": "Card 2 (22222)", "digits": "22222", "name": "Card 2"}])
    monkeypatch.setattr(site, "select_card", lambda p, c: False)

    with pytest.raises(pressing.NoAnswer):
        app_mod.App.cmd_discover(app)
    assert noted == []


def test_the_empty_message_held_is_the_words_and_not_the_region_around_them(page_of):
    """The region around the words stays whatever is drawn in it, so a wait on
    it could only run out. The words are held however deep they sit."""
    pg = page_of(switch_page('<div class="wrap"><p id="empty"><span id="words">'
                             "No statements available</span></p></div>"))
    el = site._get_no_statements_element(pg)
    assert el.get_attribute("id") == "words"


def test_the_region_is_held_when_nothing_inside_it_says_the_words(page_of):
    pg = page_of(switch_page("No statements available"))
    assert site._get_no_statements_element(pg).get_attribute("id") == "table-area"


def test_a_switcher_that_opens_on_no_card_answers_none_and_is_closed(page_of, monkeypatch):
    monkeypatch.setattr(site, "LINK_WAIT_MS", 300)
    pg = page_of("""<!doctype html><meta charset="utf-8">
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox" style="cursor:pointer;"
     onclick="this.setAttribute('aria-expanded', this.getAttribute('aria-expanded') === 'true' ? 'false' : 'true')">
  <span data-testid="simple_switcher_display_name">Solo Card</span>
</div>""")
    assert site.list_cards(pg) is None
    assert pg.locator(site._SWITCHER_COMBOBOX_SEL).get_attribute("aria-expanded") == "false"


def test_no_switcher_at_all_is_an_empty_list_and_not_a_switcher_unread(page_of, monkeypatch):
    monkeypatch.setattr(site, "LINK_WAIT_MS", 300)
    assert site.list_cards(page_of("<!doctype html><p>Statements</p>")) == []


def test_a_document_of_a_card_behind_a_switcher_that_will_not_open_is_left(page_of, monkeypatch,
                                                                         capsys):
    """A statement filed by card and a switcher that shows none is left for
    review by the caller, which a False says, and never taken from whatever
    card is on show."""
    monkeypatch.setattr(site, "LINK_WAIT_MS", 300)
    pg = page_of("""<!doctype html><meta charset="utf-8">
<div data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox">
  <span data-testid="simple_switcher_display_number">••••11111</span>
</div>""")
    assert site.ensure_card(pg, "Bravo Card (22222)") is False


def test_goto_documents_leaves_the_switcher_alone_where_the_link_shows(open_page, monkeypatch):
    """A person with one card reached the statements through this link before
    any switcher was pressed, so a switcher that would not open, here one
    turned off, must not stop them on /overview."""
    monkeypatch.setattr(site, "LINK_WAIT_MS", 100)
    server = MockAmexServer()
    server.routes["/overview"] = """<!doctype html><html><head><meta charset="utf-8"><title>Overview</title></head>
<body>
<button disabled data-testid="simple_switcher_combobox" aria-expanded="false" role="combobox">Solo Card</button>
<a href="/activity/statements">Statements &amp; Activity</a>
</body></html>"""
    page = open_page("/overview", server)
    assert site.goto_documents(page) is True
    assert "/activity/statements" in page.url


@pytest.mark.parametrize("html,says", [
    ("<main><section id='table-area'><p>No statements available</p></section></main>", True),
    ("<main><section id='table-area'></section><section><p>Older cards, there are no statements "
     "available before 2015.</p></section></main>", False),
    ("<main><section id='table-area'></section><p>If you just opened your account, you have no "
     "statements yet.</p></main>", False),
    ("<main><section id='table-area'></section><section><p>You chose paperless, so you will get "
     "no billing statements by mail.</p></section></main>", False),
    ("<main><section id='table-area'><p>You chose paperless, so you will get no billing "
     "statements by mail.</p></section></main>", False),
    ("<main><section id='table-area'></section><section><p>Sie erhalten keine Abrechnungen per "
     "Post.</p></section></main>", False),
    ("<main><section id='table-area'></section></main><footer><p>There are no statements "
     "available yet.</p></footer>", False),
], ids=["the-pages-own-words", "help-line-in-a-section", "help-line-in-a-paragraph",
        "paperless-note-in-a-section", "paperless-note-in-the-area", "german-paperless-note",
        "footer-help-line"])
def test_only_the_statements_own_region_says_a_card_is_empty(page_of, html, says):
    """A card read as empty is a card whose statements are never read, so a
    help line with the same words and no list drawn must not pass for it."""
    assert site.has_no_statements(page_of("<!doctype html>" + html)) is says
