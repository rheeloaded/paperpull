"""The newer statements view, where a part of the list could not be read.

Chase's newer statements view lists each card's statements behind one year
button shared by every card, and each row's only control is a button named
by its date, "Mar 9, 2031 Download", with no card in it. The card comes from
the accordion around the table. These are the cases around that reading
which a review of #232 asked about.

A view drawn without a year that could be read, on the older route as well
as the newer one, is the current year's statements alone, so the list is
never noted whole from it. A Download button outside every card, or one
that would submit a form, is never listed or pressed, and a button under a
cover is never pressed. The tax documents of the newer view never count as
the statements, and nothing the log says holds a card's name or last four.

A made-up page served to a bundled Chromium, every other address refused.
Every card, date and statement is invented.
"""
import base64
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chase_site as site
from paperpull_core.testkit import text_pdf


DASHBOARD = "https://secure.chase.com/web/auth/dashboard"
PERSONAL = "#/dashboard/mydocs/documents/statements"
LEGACY = "#/dashboard/documents/myDocs/index"
CARDS = ("SECRETNAME ONE (...4321)", "SECRETNAME TWO (...8765)")
DATE = "2031-03-09"


def card(index, rows, expanded=True):
    return f"""
      <mds-accordion-item>
        <button type="button" aria-expanded="{'true' if expanded else 'false'}">{CARDS[index]}</button>
        <div {'' if expanded else 'hidden'}><table><tbody>{rows}</tbody></table></div>
      </mds-accordion-item>"""


def row(index, label="Mar 9, 2031 Download", extra=""):
    return (f'<tr><td><button type="button" aria-label="{label}" data-pdf="{index}" {extra}>'
            f'</button></td></tr>')


YEAR_BUTTON = """
  <mds-data-table-action-bar><mds-select>
    <button type="button" aria-haspopup="listbox" aria-expanded="false">2031</button>
    <div role="listbox" hidden><div role="option">2031</div><div role="option">2030</div></div>
  </mds-select></mds-data-table-action-bar>"""


def page_html(body):
    pdfs = {str(i): base64.b64encode(text_pdf([c, DATE])).decode("ascii")
            for i, c in enumerate(CARDS)}
    return f"""<!doctype html><main>{body}</main><script>
      const pdfs = {json.dumps(pdfs)};
      window.presses = [];
      window.submitted = 0;
      document.addEventListener('submit', e => {{ e.preventDefault(); window.submitted++; }});
      const picker = document.querySelector('mds-select button');
      if (picker) picker.addEventListener('click', () => {{
        const menu = picker.nextElementSibling;
        menu.hidden = !menu.hidden;
        picker.setAttribute('aria-expanded', String(!menu.hidden));
      }});
      for (const header of document.querySelectorAll('mds-accordion-item > button')) {{
        header.addEventListener('click', () => {{
          const open = header.getAttribute('aria-expanded') === 'false';
          header.setAttribute('aria-expanded', String(open));
          header.nextElementSibling.hidden = !open;
        }});
      }}
      for (const button of document.querySelectorAll('[data-pdf]')) {{
        button.addEventListener('click', () => {{
          window.presses.push(button.dataset.pdf);
          const bytes = Uint8Array.from(atob(pdfs[button.dataset.pdf]), c => c.charCodeAt(0));
          const link = document.createElement('a');
          link.href = URL.createObjectURL(new Blob([bytes], {{type: 'application/pdf'}}));
          link.download = 'made-up.pdf';
          link.click();
        }});
      }}
    </script>"""


@pytest.fixture
def open_view(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(site, "_PERSONAL_ROWS_TIMEOUT_MS", 300)
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND"])
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        context = browser.new_context(accept_downloads=True, service_workers="block")
        context.route("**/*", lambda route: route.abort())
        page = context.new_page()
        wait = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: wait(min(ms, 25))

        def open_page(body, route=PERSONAL):
            context.unroute(DASHBOARD)
            context.route(DASHBOARD, lambda r: r.fulfill(content_type="text/html",
                                                         body=page_html(body)))
            page.goto(DASHBOARD + route)
            return page

        yield open_page
        browser.close()


# -- a view with no year that could be read ---------------------------------------

@pytest.mark.parametrize("route", [PERSONAL, LEGACY], ids=["newer route", "older route"])
def test_a_view_with_no_year_read_is_not_a_whole_list(open_view, route):
    """Both routes draw the cards and their date-only buttons with no year
    picker the app can read. What is read is the year on screen, so the
    walk names the year picker it could not use, rather than note one year
    as the whole list (review of #232, the older route took it whole)."""
    page = open_view(card(0, row(0)) + card(1, row(1), expanded=False), route)
    assert site.on_documents_page(page)
    got = site.chase_collect_via_api(page)
    assert sorted((d["account"], d["date"]) for d in got) == sorted((c, DATE) for c in CARDS)
    assert "year picker" in got.passed_over


def test_a_view_with_its_year_read_passes_nothing_over(open_view):
    """The control, the same cards on the newer route with the year button."""
    page = open_view(YEAR_BUTTON + card(0, row(0)) + card(1, row(1), expanded=False))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert sorted((d["account"], d["date"]) for d in got) == sorted((c, DATE) for c in CARDS)
    assert got.passed_over == ()


def test_a_card_with_no_row_in_the_year_is_not_taken_as_empty(open_view):
    """A card whose table shows no row of the year chosen may be a table
    that has not drawn yet. Nothing on the page tells that apart from a
    year with no statement, so the list is not noted whole (fail closed)."""
    page = open_view(YEAR_BUTTON + card(0, row(0)) + card(1, "", expanded=False))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert [(d["account"], d["date"]) for d in got] == [(CARDS[0], DATE)]
    assert got.passed_over == ("statement rows",)


# -- buttons that are never listed or pressed --------------------------------------

def test_a_download_button_outside_every_card_is_never_listed_or_pressed(open_view, tmp_path):
    outside = f"<table><tbody>{row(1)}</tbody></table>"
    page = open_view(YEAR_BUTTON + outside + card(0, row(0)))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert [(d["account"], d["date"]) for d in got] == [(CARDS[0], DATE)]
    assert got.passed_over == ("statement rows",)
    out = tmp_path / "statement.pdf"
    assert site.chase_download(page, page.context, CARDS[0], DATE, out)
    assert page.evaluate("window.presses") == ["0"]
    assert out.read_bytes() == text_pdf([CARDS[0], DATE])


def test_a_download_button_that_would_submit_a_form_is_never_pressed(open_view, tmp_path):
    submit = ('<tr><td><form><button type="submit" aria-label="Mar 9, 2031 Download" '
              'data-pdf="0"></button></form></td></tr>')
    page = open_view(YEAR_BUTTON + card(0, submit))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert list(got) == []
    assert "statement rows" in got.passed_over
    assert not site.chase_download(page, page.context, CARDS[0], DATE, tmp_path / "s.pdf")
    assert page.evaluate("[window.presses, window.submitted]") == [[], 0]


def test_a_covered_download_button_is_never_pressed(open_view, tmp_path):
    covered = ('<tr><td style="position:relative"><button type="button" '
               'aria-label="Mar 9, 2031 Download" data-pdf="0">x</button>'
               '<div style="position:absolute;inset:0;z-index:9"></div></td></tr>')
    page = open_view(YEAR_BUTTON + card(0, covered))
    out = tmp_path / "s.pdf"
    assert not site.chase_download(page, page.context, CARDS[0], DATE, out)
    assert page.evaluate("window.presses") == []
    assert not out.exists() or out.stat().st_size == 0


# -- the newer view's other tabs, and the log ---------------------------------------

@pytest.mark.parametrize("route", [
    "#/dashboard/mydocs/documents/tax",
    PERSONAL + ";documentType=TAX_DOCUMENTS",
], ids=["tax path", "tax documentType"])
def test_the_newer_views_tax_documents_never_count(open_view, route):
    page = open_view(YEAR_BUTTON + card(0, row(0)), route)
    assert not site.on_documents_page(page)


def test_the_log_holds_no_card_name_or_last_four(open_view, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    outside = f"<table><tbody>{row(1)}</tbody></table>"
    page = open_view(YEAR_BUTTON + outside + card(0, row(0)) + card(1, row(1), expanded=False))
    site.chase_collect_via_api(page)
    site.chase_download(page, page.context, CARDS[1], DATE, tmp_path / "s.pdf")
    site.chase_download(page, page.context, CARDS[0], "2030-01-09", tmp_path / "t.pdf")
    said = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("SECRETNAME", "4321", "8765"):
        assert secret not in said, secret


# -- review of the branch ----------------------------------------------------------

def test_a_card_table_that_pages_is_not_a_whole_list(open_view):
    """A card's table with a pager in it shows one page of the year. The
    app never presses a pager, so the rest of the year is not read and the
    list is not noted whole (review R1)."""
    pager = '<tr><td><button type="button">Next page</button></td></tr>'
    page = open_view(YEAR_BUTTON + card(0, row(0) + pager))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert [(d["account"], d["date"]) for d in got] == [(CARDS[0], DATE)]
    assert got.passed_over == ("statement rows",)


VIEW_PICKER = '<input id="filterstyledselect-year" aria-label="View:" value="2031" readonly>'


def legacy_link(index, title):
    return (f'<li><a href="#" data-pdf="{index}">Mar 9, 2031 {title} {CARDS[0]} '
            f'Saves document</a></li>')


def test_the_older_route_takes_the_row_of_the_asked_title(open_view, tmp_path):
    """Two rows of one card on one date, a statement and a corrected one.
    Discover lists the statement, whose row names the card right after its
    type, and the download presses that row, rather than give up on two
    matches or press whichever came first (review R5)."""
    rows = legacy_link(1, "Corrected Statement") + legacy_link(0, "Statement")
    body = (VIEW_PICKER + f'<mds-accordion-item><button type="button" aria-expanded="true">'
            f'{CARDS[0]}</button><div><ul>{rows}</ul></div></mds-accordion-item>')
    page = open_view(body, LEGACY)
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert [(d["account"], d["date"], d["title"]) for d in got] == [(CARDS[0], DATE, "Statement")]
    out = tmp_path / "s.pdf"
    assert site.chase_download(page, page.context, CARDS[0], DATE, out, title="Statement")
    assert page.evaluate("window.presses") == ["0"]


def test_the_older_route_with_two_rows_of_one_title_presses_neither(open_view, tmp_path):
    rows = legacy_link(1, "Statement") + legacy_link(0, "Statement")
    body = (VIEW_PICKER + f'<mds-accordion-item><button type="button" aria-expanded="true">'
            f'{CARDS[0]}</button><div><ul>{rows}</ul></div></mds-accordion-item>')
    page = open_view(body, LEGACY)
    assert not site.chase_download(page, page.context, CARDS[0], DATE, tmp_path / "s.pdf",
                                   title="Statement")
    assert page.evaluate("window.presses") == []


def test_the_older_route_with_a_card_and_no_picker_does_not_count(open_view):
    """The older center is told by its "View:" picker, as at 0.69.0. A page
    under its route with an expandable card and no picker and no statement
    button may be the dashboard's own page, and Discover stops there with
    the failure file (review R6)."""
    page = open_view(card(0, "", expanded=False), LEGACY)
    assert not site.on_documents_page(page)
    page = open_view(card(0, "", expanded=False), PERSONAL)
    assert site.on_documents_page(page), "the newer route keeps the contributor's rule"


@pytest.mark.parametrize("pager, where", [
    ('<button type="button" aria-label="Go to next page"></button>', "card"),
    ('<button type="button">Next page</button>', "action bar"),
], ids=["named anywhere", "in the shared action bar"])
def test_a_pager_named_or_placed_otherwise_is_still_seen(open_view, pager, where):
    """Re-check RC1, a pager whose name holds "next page" anywhere, or one
    in the action bar the cards share with the year button."""
    if where == "card":
        body = YEAR_BUTTON + card(0, row(0) + f"<tr><td>{pager}</td></tr>")
    else:
        body = YEAR_BUTTON.replace("</mds-data-table-action-bar>",
                                   pager + "</mds-data-table-action-bar>") + card(0, row(0))
    page = open_view(body)
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert got.passed_over == ("statement rows",)


def test_a_turned_off_pager_on_a_one_page_table_passes_nothing_over(open_view):
    pager = '<tr><td><button type="button" disabled>Next page</button></td></tr>'
    page = open_view(YEAR_BUTTON + card(0, row(0) + pager))
    got = site.chase_collect_via_api(page, keep=lambda year: year == "2031")
    assert [(d["account"], d["date"]) for d in got] == [(CARDS[0], DATE)]
    assert got.passed_over == ()
