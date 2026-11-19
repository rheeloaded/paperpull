"""Drive a synthetic Chase statements page and check which PDFs are saved."""

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
DATES = ("2032-03-09", "2031-03-09")
PDFS = {(card, date): text_pdf([card, date]) for card in CARDS for date in DATES}


def statement_button(index, date):
    return (f'<button type="button" aria-label="Mar 9, {date[:4]} Download" '
            f'data-pdf="{index}:{date}"></button>')


def card_markup(index, duplicate):
    tables = []
    for date in DATES:
        buttons = statement_button(index, date)
        if duplicate and index == 0 and date == DATES[0]:
            buttons += statement_button(index, date)
        hidden = "" if date == DATES[0] else "hidden"
        tables.append(f'<table data-year="{date[:4]}" {hidden}><tbody><tr><td>'
                      f'{buttons}</td></tr></tbody></table>')
    return f"""
      <mds-accordion-item>
        <template shadowrootmode="open"><slot></slot></template>
        <button type="button" aria-expanded="false">{CARDS[index]}</button>
        <div hidden>{''.join(tables)}</div>
      </mds-accordion-item>
    """


def fixture_page(duplicate, load_older):
    pdfs = {f"{i}:{date}": base64.b64encode(PDFS[card, date]).decode("ascii")
            for i, card in enumerate(CARDS) for date in DATES}
    cards = ''.join(card_markup(i, duplicate) for i in range(len(CARDS)))
    return f"""<!doctype html><main>
      <mds-data-table-action-bar><mds-select>
        <button type="button" aria-haspopup="listbox" aria-expanded="false">2032</button>
        <div role="listbox" hidden>
          <mds-select-option><div role="option">2032</div></mds-select-option>
          <mds-select-option><div role="option" aria-label="2031 2031">2031</div></mds-select-option>
        </div>
      </mds-select></mds-data-table-action-bar>
      <div role="option" aria-label="2031">Unrelated option</div>
      {cards}
    </main><script>
      const pdfs = {json.dumps(pdfs)};
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
        const tables = document.querySelectorAll('table[data-year]');
        for (const table of tables) table.hidden = true;
        function showTables() {{
          for (const table of tables) table.hidden = table.dataset.year !== year;
        }}
        if (year === '2032') showTables();
        else if ({json.dumps(load_older)}) setTimeout(showTables, 450);
        showMenu(false);
      }});
      for (const header of document.querySelectorAll('mds-accordion-item > button')) {{
        header.addEventListener('click', () => {{
          const open = header.getAttribute('aria-expanded') === 'false';
          header.setAttribute('aria-expanded', String(open));
          header.nextElementSibling.hidden = !open;
        }});
      }}
      window.downloads = 0;
      for (const button of document.querySelectorAll('[data-pdf]')) {{
        button.addEventListener('click', () => {{
          window.downloads++;
          const bytes = Uint8Array.from(atob(pdfs[button.dataset.pdf]), c => c.charCodeAt(0));
          const link = document.createElement('a');
          link.href = URL.createObjectURL(new Blob([bytes], {{type: 'application/pdf'}}));
          link.download = 'synthetic.pdf';
          link.click();
        }});
      }}
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

        def open_page(duplicate=False, load_older=True):
            context.route(DASHBOARD, lambda route: route.fulfill(
                content_type="text/html", body=fixture_page(duplicate, load_older)))
            page.goto(STATEMENTS)
            return page

        yield open_page
        browser.close()


def test_discovers_both_cards_in_both_years_and_downloads_the_requested_card(open_statements, tmp_path):
    page = open_statements()
    listing = site.chase_collect_via_api(page)
    assert listing.passed_over == ()
    assert sorted((doc["account"], doc["date"]) for doc in listing) == sorted(PDFS)

    assert site.select_year(page, DATES[0][:4])
    output = tmp_path / "statement.pdf"
    assert site.chase_download(page, page.context, CARDS[1], DATES[1], output)
    assert output.read_bytes() == PDFS[CARDS[1], DATES[1]]
    assert page.evaluate("window.downloads") == 1


def test_same_card_and_date_with_two_buttons_is_passed_over(open_statements, tmp_path):
    page = open_statements(duplicate=True)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == DATES[0][:4])
    assert [(doc["account"], doc["date"]) for doc in listing] == [(CARDS[1], DATES[0])]
    assert listing.passed_over == ("statement rows",)
    assert not site.chase_download(page, page.context, CARDS[0], DATES[0], tmp_path / "ambiguous.pdf")
    assert page.evaluate("window.downloads") == 0


def test_unconfirmed_historical_tables_do_not_count_as_read(open_statements, monkeypatch):
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 200)
    page = open_statements(load_older=False)
    listing = site.chase_collect_via_api(page, keep=lambda year: year == DATES[1][:4])
    assert not listing
    assert listing.passed_over == ("statement rows",)
