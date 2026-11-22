"""A card's statement rows that Chase draws through slots (#232, 0.70.0).

A contributor saw the per-card wait time out with eleven of the year's rows
on screen and bound to the open card, because Chase draws the table through
slots. Here each card's accordion item sits in a component's shadow root and
holds a slot, and the card's table is the component's own child assigned to
that slot, so the table is never inside the item in the document tree, only
in the drawn one. Synthetic cards, dates and PDFs only.
"""

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chase_site as site
from paperpull_core.testkit import text_pdf


DASHBOARD = "https://secure.chase.com/web/auth/dashboard"
STATEMENTS = DASHBOARD + "#/dashboard/mydocs/documents/statements/fixture"
CARDS = ("EXAMPLE ONE (...0001)", "EXAMPLE TWO (...0002)")
YEARS = ("2032", "2031")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov")
PDFS = {(card, f"{year}-{m:02d}-09"): text_pdf([card, f"{year}-{m:02d}-09"])
        for card in CARDS for year in YEARS for m in range(1, len(MONTHS) + 1)}


def rows(index, year):
    return "".join(
        f'<tr><td><button type="button" aria-label="{month} 9, {year} Download" '
        f'data-pdf="{index}:{year}-{m:02d}-09"></button></td></tr>'
        for m, month in enumerate(MONTHS, 1))


def fixture_page(*, years=YEARS, load_older=True, panel_shown=(), pager=False,
                 empty=(), stale=False, outer_pager=False):
    """years, the years each card's table holds. panel_shown, cards whose
    panel is drawn while the card stays closed. empty, cards whose table
    holds no row. stale, the old year's rows stay when another is chosen.
    outer_pager, the cards sit in an outer accordion item that holds a pager
    of its own."""
    pdfs = {f"{CARDS.index(card)}:{date}": base64.b64encode(data).decode("ascii")
            for (card, date), data in PDFS.items()}
    items, panels = [], []
    for i, card in enumerate(CARDS):
        items.append(f'<mds-accordion-item><button type="button" aria-expanded="false">'
                     f'{card}</button><div class="panel"><slot name="p{i}"></slot></div>'
                     f'</mds-accordion-item>')
        tables = "".join(
            f'<table data-year="{year}" {"" if year == YEARS[0] else "hidden"}><tbody>'
            f'{"" if i in empty else rows(i, year)}</tbody></table>' for year in years)
        more = '<button type="button">Next page</button>' if pager else ""
        hidden = "" if i in panel_shown else "hidden"
        panels.append(f'<div slot="p{i}" {hidden}>{tables}{more}</div>')
    return f"""<!doctype html><main>
      <mds-data-table-action-bar><mds-select>
        <button type="button" aria-haspopup="listbox" aria-expanded="false">{YEARS[0]}</button>
        <div role="listbox" hidden>
          <mds-select-option><div role="option">{YEARS[0]}</div></mds-select-option>
          <mds-select-option><div role="option">{YEARS[1]}</div></mds-select-option>
        </div>
      </mds-select></mds-data-table-action-bar>
      {'<mds-accordion-item class="outer">' if outer_pager else ''}
      <mds-card-list>
        <template shadowrootmode="open">{''.join(items)}</template>
        {''.join(panels)}
      </mds-card-list>
      {'<button type="button" class="more">Show more</button></mds-accordion-item>'
       if outer_pager else ''}
    </main><script>
      const pdfs = {json.dumps(pdfs)};
      const host = document.querySelector('mds-card-list');
      const picker = document.querySelector('mds-select button');
      const menu = picker.nextElementSibling;
      function showMenu(open) {{
        picker.setAttribute('aria-expanded', String(open));
        menu.hidden = !open;
      }}
      picker.addEventListener('click', () => showMenu(menu.hidden));
      picker.addEventListener('keydown', e => {{ if (e.key === 'Escape') showMenu(false); }});
      menu.addEventListener('click', e => {{
        const year = e.target.innerText;
        picker.textContent = year;
        const tables = host.querySelectorAll('table[data-year]');
        if (!{json.dumps(stale)}) for (const table of tables) table.hidden = true;
        function showTables() {{
          for (const table of tables)
            if (!{json.dumps(stale)} || table.dataset.year === year)
              table.hidden = table.dataset.year !== year;
        }}
        if (year === '{YEARS[0]}') showTables();
        else if ({json.dumps(load_older)}) setTimeout(showTables, 450);
        showMenu(false);
      }});
      host.shadowRoot.querySelectorAll('mds-accordion-item > button').forEach((header, i) => {{
        header.addEventListener('click', () => {{
          const open = header.getAttribute('aria-expanded') === 'false';
          header.setAttribute('aria-expanded', String(open));
          host.querySelector(`[slot="p${{i}}"]`).hidden = !open;
        }});
      }});
      window.downloads = 0;
      window.pages = 0;
      for (const button of host.querySelectorAll('[data-pdf]')) {{
        button.addEventListener('click', () => {{
          window.downloads++;
          const bytes = Uint8Array.from(atob(pdfs[button.dataset.pdf]), c => c.charCodeAt(0));
          const link = document.createElement('a');
          link.href = URL.createObjectURL(new Blob([bytes], {{type: 'application/pdf'}}));
          link.download = 'synthetic.pdf';
          link.click();
        }});
      }}
      for (const button of document.querySelectorAll('[slot] > button, button.more'))
        button.addEventListener('click', () => window.pages++);
    </script>"""


@pytest.fixture
def open_statements():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(
                args=["--host-resolver-rules=MAP * ~NOTFOUND"])
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        context = browser.new_context(accept_downloads=True, service_workers="block")
        context.route("**/*", lambda route: route.abort())
        page = context.new_page()
        wait = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: wait(min(ms, 25))

        def open_page(**shape):
            context.route(DASHBOARD, lambda route: route.fulfill(
                content_type="text/html", body=fixture_page(**shape)))
            page.goto(STATEMENTS)
            return page

        yield open_page
        browser.close()


def _year(listing, year):
    return sorted((doc["account"], doc["date"]) for doc in listing if doc["date"][:4] == year)


def _expected(year):
    return sorted(key for key in PDFS if key[1][:4] == year)


def test_slotted_rows_of_the_current_year_are_read_whole_without_waiting(open_statements):
    page = open_statements()
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[0])
    assert listing.passed_over == ()
    assert _year(listing, YEARS[0]) == _expected(YEARS[0])
    assert len(listing) == 2 * len(MONTHS)
    assert page.evaluate("window.downloads") == 0


def test_slotted_rows_on_screen_are_confirmed_at_the_first_look(open_statements, monkeypatch):
    # With no time to wait at all, rows already drawn are still confirmed.
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 0)
    page = open_statements()
    assert site.select_year(page, YEARS[0]) and site.expand_only_card(page, CARDS[1])
    assert site._wait_for_personal_card_rows(page, CARDS[1], YEARS[0])


def test_slotted_rows_of_an_older_year_drawn_late_are_read_whole(open_statements):
    page = open_statements()
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[1])
    assert listing.passed_over == ()
    assert _year(listing, YEARS[1]) == _expected(YEARS[1])


def test_slotted_rows_that_never_reach_the_year_are_not_a_whole_list(open_statements, monkeypatch):
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 300)
    page = open_statements(load_older=False)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[1])
    assert not listing
    assert listing.passed_over == ("statement rows",)


def test_the_old_years_slotted_rows_left_on_screen_are_not_the_chosen_year(open_statements, monkeypatch):
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 300)
    page = open_statements(load_older=False, stale=True)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[1])
    assert not _year(listing, YEARS[1])
    assert listing.passed_over == ("statement rows",)
    assert site.select_year(page, YEARS[1]) and site.expand_only_card(page, CARDS[0])
    assert not site._wait_for_personal_card_rows(page, CARDS[0], YEARS[1])
    assert site._wait_for_personal_card_rows(page, CARDS[0], YEARS[0])


def test_another_cards_slotted_rows_never_confirm_the_open_card(open_statements, monkeypatch):
    # Card one's table holds no row, card two's panel is drawn while it is
    # closed. Card one's wait must not take card two's rows as its own.
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 300)
    page = open_statements(empty=(0,), panel_shown=(1,))
    assert site.expand_only_card(page, CARDS[0])
    assert not site._wait_for_personal_card_rows(page, CARDS[0], YEARS[0])
    # Card two opened beside card one, its rows bound to it, still never one's.
    page.get_by_role("button", name=CARDS[1], exact=True).click()
    assert site._wait_for_personal_card_rows(page, CARDS[1], YEARS[0])
    assert not site._wait_for_personal_card_rows(page, CARDS[0], YEARS[0])
    assert site.read_card_rows(page, CARDS[0], year=YEARS[0]).passed_over == ("statement rows",)


def test_an_empty_slotted_table_is_not_a_whole_list(open_statements, monkeypatch):
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 300)
    page = open_statements(empty=(0, 1))
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[0])
    assert not listing
    assert listing.passed_over == ("statement rows",)


def test_a_pager_drawn_through_the_slot_leaves_the_list_not_whole_and_unpressed(open_statements):
    page = open_statements(pager=True)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[0])
    assert _year(listing, YEARS[0]) == _expected(YEARS[0])
    assert listing.passed_over == ("statement rows",)
    assert page.evaluate("window.pages") == 0 and page.evaluate("window.downloads") == 0


def test_a_slotted_row_downloads_its_own_cards_statement(open_statements, tmp_path):
    page = open_statements()
    assert site.select_year(page, YEARS[0])
    date = f"{YEARS[1]}-03-09"
    output = tmp_path / "statement.pdf"
    assert site.chase_download(page, page.context, CARDS[1], date, output)
    assert output.read_bytes() == PDFS[CARDS[1], date]
    assert page.evaluate("window.downloads") == 1


def test_a_page_that_breaks_during_the_wait_is_not_confirmed(open_statements, monkeypatch):
    page = open_statements()
    assert site.expand_only_card(page, CARDS[0])

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic page gone")
    monkeypatch.setattr(page, "evaluate", broken)
    assert not site._wait_for_personal_card_rows(page, CARDS[0], YEARS[0])


def test_a_pager_in_an_outer_item_holding_the_cards_leaves_the_list_not_whole(open_statements):
    page = open_statements(outer_pager=True)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == YEARS[0])
    assert _year(listing, YEARS[0]) == _expected(YEARS[0])
    assert listing.passed_over == ("statement rows",)
    assert page.evaluate("window.pages") == 0 and page.evaluate("window.downloads") == 0
