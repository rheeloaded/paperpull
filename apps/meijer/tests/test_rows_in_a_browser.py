"""A receipt row, as his page really lays one out.

He ran 0.33.0 and it found ninety-six In-Store rows, which was the part
that had been broken. Every one of them then parsed with no date, so
every one fell outside the scope he had set and nothing was downloaded.

His rows put the date on one line and the amount on the next, in
separate elements, and the collector kept the innermost element holding
an amount. That is the second line, which has no date in it (#42).

In a real browser, because the mistake was about what innerText does
down a tree and a fake page cannot get that wrong the same way.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site


def row(date, amount, items=6, link='<a href="javascript:void(0)">view receipt pdf</a>'):
    return ('<li class="order-card"><div class="date">In-Store: %s</div>'
            '<div class="totals"><span>$%s</span>&nbsp;&nbsp;%d items</div>%s</li>'
            % (date, amount, items, link))


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def show(page, rows):
    page.set_content("<body><main><ul>%s</ul></main></body>" % "".join(rows))


def test_a_row_is_wide_enough_to_carry_its_own_date(page):
    show(page, [row("09/19/2026", "31.23", 15), row("09/12/2026", "88.40", 22)])
    got = [site.card_to_purchase(c) for c in site.collect_cards(page)]
    assert [p.purchase_date for p in got] == ["2026-09-19", "2026-09-12"]
    assert [p.total for p in got] == ["$31.23", "$88.40"]


def test_it_is_still_one_purchase_per_row(page):
    show(page, [row("09/19/2026", "31.23") for _ in range(5)])
    assert len(site.collect_cards(page)) == 5, "no row swallowed its neighbours"


def test_the_receipt_link_survives_the_widening(page):
    show(page, [row("09/19/2026", "31.23")])
    [card] = site.collect_cards(page)
    assert any(site.RECEIPT_LINK_RE.match(ln["text"]) for ln in card.links)


def test_a_store_receipt_is_filed_as_one(page):
    show(page, [row("09/19/2026", "31.23")])
    from paperpull_core.models import IN_STORE
    assert site.card_to_purchase(site.collect_cards(page)[0]).purchase_type == IN_STORE


def test_a_row_that_already_holds_its_date_is_not_widened(page):
    page.set_content('<body><main><ul>'
                     '<li class="order-card"><div>Pickup Sep 13, 2026 Order #123 $86.42</div></li>'
                     '</ul></main></body>')
    [card] = site.collect_cards(page)
    assert site.card_to_purchase(card).purchase_date == "2026-09-13"
