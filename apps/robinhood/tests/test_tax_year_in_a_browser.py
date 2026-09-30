"""A tax form's year, read off the page the way the browser draws it (#62).

The tester's first run saved a tax form named 0000-00-00. Its title line
named the form and not the year, and the title was the only thing the date
was read from. Forms of several years that share a title were also one
document, because a title was all that told them apart, so every year but
the first was dropped without a word.

These pages are made up, with invented years, in the shapes a tax page can
take. The year on a line of the form's own card, the year as a heading over
its forms, the chosen year of a picker. What they pin is how the app reads
whatever it is given. A form is dated by its own card first, then by the
nearest year above it that is not inside another form's card. An issue
date, a copyright year or a tab that is not chosen names nothing, and a
form the page gives no year keeps no date rather than a guessed one. The
download presses the control of the year that was listed, never the first
control of that title.

Every page is served from memory for robinhood.com and every other request
is refused, so nothing leaves this machine.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import robinhood_site as site  # noqa: E402

TAX = "https://robinhood.com/account/reports-statements/tax"
CRYPTO = "https://robinhood.com/account/reports-statements/crypto"


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        launched = driver.chromium.launch(
            headless=True,
            args=["--disable-extensions", "--disable-sync", "--no-first-run"])
    except Exception as e:
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    try:
        yield launched
    finally:
        launched.close()
        driver.stop()


@pytest.fixture()
def show(browser):
    ctx = browser.new_context(accept_downloads=True)
    pages = {}

    def answer(route):
        body = pages.get(route.request.url.split("#")[0])
        if body is None:
            route.abort()
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=body)

    ctx.route("**/*", answer)
    page = ctx.new_page()

    def open_page(html, url=TAX):
        pages[url] = "<!doctype html><html><body>%s%s</body></html>" % (html, GIVE)
        page.goto(url)
        return page

    try:
        yield open_page
    finally:
        ctx.close()


# Pressing a form's Download PDF hands back a small file that says which
# year's control was pressed, as a download the browser saves.
GIVE = """<script>
function give(year) {
  const blob = new Blob(['%PDF-1.4\\n% invented form for tax year ' + year + '\\n'],
                        {type: 'application/pdf'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'form.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
</script>"""


def card(title, *lines, year=""):
    more = "".join("<div>%s</div>" % line for line in lines)
    return ('<div class="card"><div>%s</div>%s'
            '<button onclick="give(\'%s\')">Download PDF</button>'
            '<button>Download CSV</button></div>' % (title, more, year))


def read(page):
    return [(d.title, d.date_text, getattr(d, "tax_year", ""))
            for d in site.collect_download_docs(page)]


NAV = ('<nav><a href="/account">Account</a> <span>Robinhood 2024 recap</span></nav>'
       '<h1>Tax documents</h1>')
FOOTER = "<footer>&copy; 2024 Robinhood Markets</footer>"


# -- the year beside a form ------------------------------------------------

def test_a_form_whose_card_names_its_tax_year_is_dated_by_it(show):
    page = show(NAV + "<main>%s</main>" % card(
        "Consolidated Form 1099", "Robinhood Securities", "Tax year 2022",
        "Available Feb 14, 2023") + FOOTER)
    assert read(page) == [("Consolidated Form 1099", "2022-12-31", "2022")]


def test_a_lone_year_in_the_card_is_the_tax_year_once_its_dates_are_out(show):
    page = show(NAV + "<main>%s</main>" % card(
        "Consolidated Form 1099", "Robinhood Securities", "2022",
        "Updated Mar 3, 2023") + FOOTER)
    assert read(page) == [("Consolidated Form 1099", "2022-12-31", "2022")]


def test_forms_named_alike_under_year_headings_are_two_documents(show):
    page = show(NAV + "<main>"
                "<section><h2>2022</h2>%s</section>"
                "<section><h2>2021</h2>%s</section></main>" % (
                    card("Consolidated Form 1099", "Robinhood Securities", year="2022"),
                    card("Consolidated Form 1099", "Robinhood Securities", year="2021")))
    assert read(page) == [("Consolidated Form 1099", "2022-12-31", "2022"),
                          ("Consolidated Form 1099", "2021-12-31", "2021")]


def test_another_forms_card_never_dates_this_one(show):
    """The same layout flat, headings and cards side by side. The second
    form's nearest year above it is in the first form's card, and that
    year is the first form's own."""
    page = show(NAV + "<main><h3>2022</h3>%s%s<h3>2021</h3>%s</main>" % (
        card("Form 1099-DIV", "Tax year 2020"),
        card("Consolidated Form 1099"),
        card("Consolidated Form 1099")))
    assert read(page) == [("Form 1099-DIV", "2020-12-31", "2020"),
                          ("Consolidated Form 1099", "2022-12-31", "2022"),
                          ("Consolidated Form 1099", "2021-12-31", "2021")]


def test_a_form_shown_again_without_its_year_is_one_document_with_it(show):
    """The same form in a block of recent documents and again under its
    year. Kept once, with the year, and the recent copy is never pressed."""
    page = show(NAV + "<main><h2>Recent documents</h2>%s"
                "<section><h2>2022</h2>%s</section></main>" % (
                    card("Consolidated Form 1099", year="recent"),
                    card("Consolidated Form 1099", year="2022")))
    assert read(page) == [("Consolidated Form 1099", "2022-12-31", "2022")]


# -- a year among years -----------------------------------------------------

def test_the_chosen_tab_names_the_forms_and_the_nearest_tab_does_not(show):
    page = show(NAV + '<div role="tablist">'
                '<button role="tab" aria-selected="true">2022</button>'
                '<button role="tab" aria-selected="false">2021</button></div>'
                "<main>%s</main>" % card("Consolidated Form 1099"))
    assert read(page) == [("Consolidated Form 1099", "2022-12-31", "2022")]


def test_the_chosen_option_of_a_dropdown_names_the_forms(show):
    page = show(NAV + '<label>Tax year <select><option>2022</option>'
                '<option selected>2021</option><option>2020</option></select></label>'
                "<main>%s</main>" % card("Consolidated Form 1099"))
    assert read(page) == [("Consolidated Form 1099", "2021-12-31", "2021")]


def test_a_row_of_year_buttons_with_none_chosen_names_nothing(show):
    page = show(NAV + "<div><button>2022</button><button>2021</button></div>"
                "<main>%s</main>" % card("Consolidated Form 1099"))
    assert read(page) == [("Consolidated Form 1099", "", "")]


# -- what is never a tax year ------------------------------------------------

def test_an_issue_date_a_recap_and_a_copyright_name_nothing(show):
    page = show(NAV + "<main>%s</main>" % card(
        "Consolidated Form 1099", "Available Feb 14, 2023",
        "Account \u2022\u2022\u2022\u20222019") + FOOTER)
    assert read(page) == [("Consolidated Form 1099", "", "")]


def test_a_year_that_has_not_ended_is_not_a_tax_year(show):
    """A form for a year still running does not exist yet."""
    from datetime import date
    this_year = date.today().year
    page = show(NAV + "<main>%s</main>" % card(
        "Consolidated Form 1099", "Tax year %d" % this_year))
    assert read(page) == [("Consolidated Form 1099", "", "")]
    assert site.tax_year_of("Consolidated Form 1099", "2022", date(2026, 9, 30)) == "2022"
    assert site.tax_year_of("Consolidated Form 1099", "2026", date(2026, 9, 30)) == ""
    assert site.tax_year_of("January 2022 Monthly Statement", "2021", date(2026, 9, 30)) == ""


# -- read as before -----------------------------------------------------------

def test_a_title_that_names_its_year_is_read_as_before(show):
    page = show(NAV + "<main><h2>2021</h2>%s</main>" % card("2022 Consolidated Form 1099"))
    assert read(page) == [("2022 Consolidated Form 1099", "2022-12-31", "")]


def test_statement_links_are_read_as_before(show):
    page = show("<h1>Robinhood Crypto account statements</h1><main>"
                '<a download href="#">January 2022 Monthly Statement</a>'
                '<a download href="#">February 2022 Monthly Statement</a>'
                '<a href="#">View More</a></main>', url=CRYPTO)
    assert read(page) == [("January 2022 Monthly Statement", "2022-01-31", ""),
                          ("February 2022 Monthly Statement", "2022-02-28", "")]


# -- the control that is pressed ---------------------------------------------

def test_the_download_presses_the_control_of_its_own_year(show, tmp_path):
    page = show(NAV + "<main>"
                "<section><h2>2022</h2>%s</section>"
                "<section><h2>2021</h2>%s</section></main>" % (
                    card("Consolidated Form 1099", year="2022"),
                    card("Consolidated Form 1099", year="2021")))
    for year in ("2021", "2022"):
        out = tmp_path / ("form %s.pdf" % year)
        assert site.download_named(page, "Consolidated Form 1099", out, year=year)
        assert out.read_bytes().startswith(b"%PDF-")
        assert ("tax year %s" % year).encode() in out.read_bytes()


def test_no_control_is_pressed_for_a_year_the_page_does_not_show(show, tmp_path):
    page = show(NAV + "<main><section><h2>2022</h2>%s</section></main>"
                % card("Consolidated Form 1099", year="2022"))
    out = tmp_path / "form.pdf"
    assert not site.download_named(page, "Consolidated Form 1099", out, year="2020")
    assert not out.exists()
