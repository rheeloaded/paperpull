"""The monthly page's year picker, walked in a real browser (#38).

His 0.37.1 Pilot and Run All found only the 2026 statements. The monthly
page shows one year at a time, and his recording chose 2025 and then 2024
in a year picker above the list and pressed Download on December 2024,
which arrived as Monthly Statement.pdf with no new tab and no navigation.

These pages take the shape the recording gave. A label, and beside it a
form holding a custom element holding a select with four options, the
first with no id, and no name of its own. What the first option says was
not recorded, so both shapes are here, four years, and a placeholder
before the three years he named. Below the picker is one row per
statement, a heading with the month and two links, View and Download,
neither with a label of its own.
Choosing a year redraws the list a moment later, the way the servicing app
does once its answer for that year comes back, and until then the list on
screen is still the last year's. The picker sits inside styling classes
that say "card" and "block", which the core's identity check reads and
this app's forbidden words would refuse, so these pages also show that a
class name does not decide whether the picker is used.
"""
import inspect
import json
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402  binds this provider's AppSpec
import newrez_site as site  # noqa: E402
from paperpull_core.words import Fixed, shape_tree  # noqa: E402

LOAN = "1234567"
MONTHLY = f"https://servicing.newrez.com/servicing/{LOAN}/statements/monthly"
YEARLY = f"https://servicing.newrez.com/servicing/{LOAN}/statements/yearly"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _months(year: int, first: int, last: int) -> list:
    """One row per month, newest first, the way the list shows them."""
    return ["%s %d" % (MONTHS[m - 1], year) for m in range(last, first - 1, -1)]


# Invented dates in the counts his account showed. Nine statements this
# year, as his first survey counted, seven in 2024, as the recording's
# 2024 list held, a full year between, and a fourth year with none.
LISTS = {"2026": _months(2026, 1, 9), "2025": _months(2025, 1, 12),
         "2024": _months(2024, 6, 12), "2023": []}


def _iso(month_year: str) -> str:
    return site.parse_period_date(month_year)[0]


def _pdf(month: str) -> bytes:
    """A statement that says which month it is."""
    return b"%PDF-1.4\n% " + month.encode() + b"\n" + b"0" * 3000 + b"\n%%EOF\n"


# The rows are made with the DOM rather than written as markup, so a month
# needs no quoting. Choosing a year writes it down, draws the old year's
# rows again when `STALE` is set, as a page can while it waits for its
# answer, and draws the new year's rows `DELAY` later. With `LEAVE` set the
# new rows arrive above the old ones and the old ones stay that much
# longer, as rows that animate out do. With `LOADING` set the list empties
# the moment a year is chosen, as a list showing a spinner does. View and
# Download both bring the month's statement. Capture presses the first
# control dated for the row, which is View, and View brought his
# statements on 0.37.1, though how it brings one was not recorded.
PAGE_JS = """
function seen(what, v) { window['__' + what] = (window['__' + what] || []).concat([v]); }
function statement(m) {
  seen('pressed', m);
  location.href = 'https://docs.example.test/statement?m=' + encodeURIComponent(m);
}
function link(words, act, cls) {
  const a = document.createElement('a');
  a.href = 'javascript:void(0)';
  if (cls) a.className = cls;
  a.dataset.act = '1';
  const i = document.createElement('i');
  i.className = 'icon';
  const s = document.createElement('span');
  s.className = 'words';
  s.textContent = words;
  a.appendChild(i);
  a.appendChild(s);
  a.addEventListener('click', act);
  return a;
}
function row(m) {
  const outer = document.createElement('div');
  outer.className = 'statement';
  outer.dataset.row = '1';
  const body = document.createElement('div');
  body.className = 'statement-body';
  const h = document.createElement('h6');
  h.className = 'statement-month';
  h.textContent = m;
  const links = document.createElement('div');
  links.className = 'statement-links';
  links.appendChild(link('View', function () { statement(m); }));
  links.appendChild(link('Download', function () { statement(m); }, 'download-link'));
  body.appendChild(h);
  body.appendChild(links);
  outer.appendChild(body);
  return outer;
}
function draw(y) {
  document.getElementById('rows').replaceChildren(...(LISTS[y] || []).map(row));
  window.__shown = y;
}
function arrive(y) {
  const list = document.getElementById('rows');
  const old = Array.from(list.children);
  const first = list.firstChild;
  (LISTS[y] || []).forEach(function (m) { list.insertBefore(row(m), first); });
  window.__shown = y;
  setTimeout(function () { old.forEach(function (n) { n.remove(); }); }, LEAVE);
}
function pick(y) {
  seen('picked', y);
  seen('drawnWhenPicked', window.__shown !== undefined);
  sessionStorage.setItem('picked', JSON.stringify(window.__picked));
  const was = window.__shown;
  if (LOADING) document.getElementById('rows').replaceChildren();
  if (STALE) setTimeout(function () { draw(was); }, 100);
  setTimeout(function () { if (LEAVE) { arrive(y); } else { draw(y); } }, DELAY);
}
function onScreen() {
  return Array.from(document.querySelectorAll('#rows .statement-month'))
    .map(function (h) { return h.textContent.slice(-4); });
}
"""

STYLE = "<style>.field-error, .d-none { display: none }</style>"


def _picker(years, label="Year", form_extra="", select_attrs="", hidden=False,
            placeholder=None) -> str:
    """The picker in the recorded shape. The first option has no id and
    the others do, as recorded, and what the first says was not. With
    `placeholder` the first option is that, with an empty value, and every
    year has an id."""
    first = ("<option class='year-option' value=''>%s</option>" % placeholder
             if placeholder is not None else "")
    offset = 1 if placeholder is not None else 0
    options = first + "".join(
        "<option class='year-option' value='%s'>%s</option>" % (y, y) if i + offset == 0 else
        "<option class='year-option' id='year-option-%d' value='%s'>%s</option>" % (i + offset, y, y)
        for i, y in enumerate(years))
    style = " style='display:none'" if hidden else ""
    return ("<div class='row'%s><div class='col-md-4'><div class='form-group'>"
            "<label class='form-label'>%s</label>"
            "<div class='form-control-wrap'><form class='ng-untouched ng-pristine ng-valid' novalidate>"
            "<app-year-select class='year-select'>"
            "<select class='form-select' onchange='pick(this.value)'%s>%s</select>"
            "<app-field-error class='field-error'></app-field-error>"
            "</app-year-select>%s</form></div></div></div></div>"
            % (style, label, select_attrs, options, form_extra))


def _statements_page(lists=None, delay_ms=400, stale=False, leave_ms=0, loading=False,
                     first_ms=0, picker=True, pickers=None, extra="", late_years=(),
                     late_years_ms=0) -> str:
    """The monthly page, showing the first year of `lists` at first, or
    `first_ms` after it loads, whatever the picker shows by then. The
    picker gains `late_years` as options `late_years_ms` after it loads."""
    lists = LISTS if lists is None else lists
    first = next(iter(lists))
    if pickers is None:
        pickers = _picker(list(lists)) if picker else ""
    late = ""
    if late_years:
        late = ("setTimeout(function () { const s = document.querySelector('select');"
                " %s.forEach(function (y) { const o = document.createElement('option');"
                " o.className = 'year-option'; o.id = 'year-option-' + y; o.value = y;"
                " o.textContent = y; s.appendChild(o); }); }, %d);"
                % (json.dumps(list(late_years)), late_years_ms))
    return ("<html><head>" + STYLE + "</head><body><main class='content'>"
            "<h1>Statements Monthly</h1>"
            "<div class='card'><div class='card-body d-block'>" + pickers
            + "<div class='row'><div class='col'><div id='rows' class='statement-list'></div>"
            "</div></div><div class='row d-none'></div></div></div>" + extra + "</main>"
            "<script>const LISTS = " + json.dumps(lists) + "; const DELAY = " + str(delay_ms)
            + "; const STALE = " + ("true" if stale else "false") + "; const LEAVE = "
            + str(leave_ms) + "; const LOADING = " + ("true" if loading else "false") + ";"
            + PAGE_JS + (("setTimeout(function () { draw(%s); }, %d);" % (json.dumps(first), first_ms))
                         if first_ms else "draw(%s);" % json.dumps(first))
            + late + "</script></body></html>")


def _yearly_page(*years) -> str:
    rows = "".join("<div class='form-row'><h6>Form 1098 %s</h6><div>"
                   "<a href='javascript:void(0)'><span>Download</span></a></div></div>" % y
                   for y in years)
    return "<html><body><main><h1>Statements Yearly</h1>" + rows + "</main></body></html>"


@pytest.fixture()
def pages(monkeypatch):
    """A browser whose every address is answered here. The statements pages
    are Newrez's, and a statement downloads from an invented address that
    is not, as Monthly Statement.pdf. Scrolling to the end of a list takes
    five seconds and these lists are short, so it is skipped, and a year
    with no statement is given up on after four seconds."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "scroll_full_page", lambda page, *a, **k: None)
    monkeypatch.setattr(site, "YEAR_WAIT_S", 4, raising=False)
    ctx = browser.new_context(accept_downloads=True)
    state = {"monthly": "<h1>empty</h1>", "yearly": "<h1>empty</h1>"}

    def serve(route):
        url = route.request.url
        if url.startswith(MONTHLY):
            route.fulfill(status=200, content_type="text/html", body=state["monthly"])
        elif url.startswith(YEARLY):
            route.fulfill(status=200, content_type="text/html", body=state["yearly"])
        elif url.startswith("https://docs.example.test/statement"):
            month = parse_qs(urlsplit(url).query).get("m", [""])[0]
            route.fulfill(status=200, body=_pdf(month), headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="Monthly Statement.pdf"'})
        else:
            route.fulfill(status=404, body="")

    ctx.route("**/*", serve)
    pg = ctx.new_page()
    yield pg, state
    browser.close()
    driver.stop()


def _picked(page) -> list:
    return page.evaluate("window.__picked || []")


def _pressed(page) -> list:
    return page.evaluate("window.__pressed || []")


# -- discovery ------------------------------------------------------------

def test_discovery_reads_every_year_the_picker_offers(pages):
    """Every year's statements, in the order the years are offered, and a
    December statement does not hide that year's 1098, which is dated the
    same last day of the year."""
    page, state = pages
    state["monthly"] = _statements_page()
    state["yearly"] = _yearly_page("2025", "2024")
    page.goto(MONTHLY)
    docs = site.collect_download_docs(page)
    statements = [d.date_text for d in docs if d.kind == "statement"]
    assert statements == [_iso(m) for y in ("2026", "2025", "2024") for m in LISTS[y]]
    assert [d.date_text for d in docs if d.kind == "tax"] == ["2025-12-31", "2024-12-31"]
    assert {"2025-12-31", "2024-12-31"} <= set(statements)
    # the year on screen at first is not chosen again
    assert json.loads(page.evaluate("sessionStorage.getItem('picked')")) == ["2025", "2024", "2023"]


def _years_on_screen(page) -> list:
    """Which years the rows on screen are in, and the year the picker shows."""
    return page.evaluate("[Array.from(new Set(onScreen())).sort(), document.querySelector('select').value]")


def test_a_list_left_over_from_the_year_before_is_never_read_as_the_new_one(pages, monkeypatch):
    """The list redraws two seconds after a year is chosen. It draws the
    old year's rows afresh first, and then the new rows arrive while the
    old ones are still leaving. Every row looks alike, so the rows read
    after choosing 2025 could be 2026's. The list is read only once every
    row on it is in the year the picker shows."""
    monkeypatch.setattr(site, "YEAR_WAIT_S", 8)
    page, state = pages
    lists = {y: LISTS[y] for y in ("2026", "2025", "2024")}
    state["monthly"] = _statements_page(lists, delay_ms=2000, stale=True, leave_ms=1500)
    state["yearly"] = _yearly_page()
    reads = []
    real = site._read_rows

    def reading(pg, docs, seen):
        if pg.url.startswith(MONTHLY):
            reads.append(_years_on_screen(pg))
        return real(pg, docs, seen)

    monkeypatch.setattr(site, "_read_rows", reading)
    page.goto(MONTHLY)
    docs = site.collect_download_docs(page)
    # what it showed first, then each year once its own list was on screen
    assert reads == [[["2026"], "2026"], [["2026"], "2026"], [["2025"], "2025"], [["2024"], "2024"]]
    statements = [d.date_text for d in docs if d.kind == "statement"]
    assert statements == [_iso(m) for y in lists for m in lists[y]]


def test_the_walk_says_what_each_year_gave_in_numbers_and_fixed_words(pages, monkeypatch):
    """The page is the recorded shape, and the walk reports each year it
    chose and how many statements its list showed. A year whose list never
    showed one is said so, costs only the wait, and is not read."""
    page, state = pages
    state["monthly"] = _statements_page()
    page.goto(MONTHLY)
    # the made-up select has no name of its own, as recorded
    assert page.evaluate("(() => { const s = document.querySelector('select');"
                         " return [s.labels.length, s.id, s.name, s.getAttribute('aria-label'),"
                         " s.form.elements.length]; })()") == [0, "", "", None, 1]
    reads = []
    real = site._read_rows

    def reading(pg, docs, seen):
        reads.append(_years_on_screen(pg)[1])
        return real(pg, docs, seen)

    monkeypatch.setattr(site, "_read_rows", reading)
    docs, seen = [], set()
    facts = site._walk_years(page, docs, seen)
    assert reads == ["2026", "2025", "2024"]
    assert facts == {"picker": "found", "selects": 1, "year_selects": 1, "years": 4,
                     "walked": [[2026, 9, "shown"], [2025, 12, "shown"], [2024, 7, "shown"],
                                [2023, 0, "never showed"]]}
    assert len(docs) == 28
    assert site.year_walk_lines({"monthly": facts}) == [
        "Year picker on the monthly page walked 4 years, 2026 gave 9, 2025 gave 12, "
        "2024 gave 7, 2023 never showed"]


# The shape his account most likely has. Four options, the first with no
# id, and his 2024 list of seven fits a loan whose first statement came in
# mid 2024, so the three years he named have statements and the first
# option is a placeholder.
THREE_YEARS = {y: LISTS[y] for y in ("2026", "2025", "2024")}


def _placeholder_page(**kw) -> str:
    return _statements_page(THREE_YEARS, pickers=_picker(list(THREE_YEARS), placeholder="Select Year"),
                            **kw)


def test_one_leading_placeholder_is_allowed_and_is_never_a_year():
    years = site._years_of
    assert years({"options": ["Select Year", "2026", "2025", "2024"]}) == ["2026", "2025", "2024"]
    assert years({"options": ["", "2026", "2025"]}) == ["2026", "2025"]
    assert years({"options": ["2026", "2025", "2024", "2023"]}) == ["2026", "2025", "2024", "2023"]
    # two that are not years, or one anywhere but first, is not a picker
    assert years({"options": ["Select Year", "All", "2025"]}) == []
    assert years({"options": ["2025", "Select Year", "2024"]}) == []
    assert years({"options": ["2025", "2024", "Older"]}) == []
    assert years({"options": ["Select Year"]}) == [] and years({"options": []}) == []


def test_a_picker_whose_first_option_is_a_placeholder_walks_the_three_years(pages, monkeypatch):
    """The placeholder is what the picker shows at first. It is never
    chosen and never counted, and each of the three years is chosen and
    read once its own list is on screen."""
    page, state = pages
    state["monthly"] = _placeholder_page()
    page.goto(MONTHLY)
    assert page.evaluate("[document.querySelector('select').selectedIndex,"
                         " document.querySelector('select').options.length]") == [0, 4]
    reads = []
    real = site._read_rows

    def reading(pg, docs, seen):
        reads.append(_years_on_screen(pg))
        return real(pg, docs, seen)

    monkeypatch.setattr(site, "_read_rows", reading)
    docs, seen = [], set()
    facts = site._walk_years(page, docs, seen)
    assert facts == {"picker": "found", "selects": 1, "year_selects": 1, "years": 3,
                     "walked": [[2026, 9, "shown"], [2025, 12, "shown"], [2024, 7, "shown"]]}
    assert _picked(page) == ["2026", "2025", "2024"]
    assert reads == [[["2026"], "2026"], [["2025"], "2025"], [["2024"], "2024"]]
    assert [d.date_text for d in docs] == [_iso(m) for y in THREE_YEARS for m in THREE_YEARS[y]]
    assert site.year_walk_lines({"monthly": facts}) == [
        "Year picker on the monthly page walked 3 years, 2026 gave 9, 2025 gave 12, 2024 gave 7"]
    # it is never chosen by capture either, whose list starts on it
    assert site._choose_year(page, "Select Year")[0] == "not offered"
    assert site._choose_year(page, "")[0] == "not offered"


def test_with_a_placeholder_an_older_statement_is_pressed_on_its_own_years_list(pages, tmp_path,
                                                                                 monkeypatch):
    monkeypatch.setattr(site, "LIST_WAIT_S", 12)
    page, state = pages
    state["monthly"] = _placeholder_page(delay_ms=1500, stale=True)
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, tmp_path / "dl", "2024-12-31", out,
                              title="Mortgage Statement - December 31, 2024", trace=trace), \
        [t.get("note") for t in trace]
    assert out.read_bytes() == _pdf("December 2024")
    assert _picked(page) == ["2024"] and _pressed(page) == ["December 2024"]
    assert site.capture_facts(trace)["year"]["years_offered"] == 3
    # this year's statement is on the list as drawn, so nothing is chosen for it
    page.goto(MONTHLY)
    assert site.download_bill(page, tmp_path / "dl", "2026-08-31", tmp_path / "t.pdf",
                              title="Mortgage Statement - August 31, 2026", trace=[])
    assert _picked(page) == [] and _pressed(page) == ["August 2026"]


def test_the_newest_year_is_never_chosen_while_the_first_list_is_still_drawing(pages, tmp_path,
                                                                             monkeypatch):
    """The placeholder shows and the first list is slower than the idle
    wait. This year's statement is on that first list once it draws, so
    nothing is chosen for it. Choosing this year while the page still
    loaded drew the list twice and took the row away before the press,
    where 0.37.1 had saved it."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 12)
    monkeypatch.setattr(site, "PICKER_IDLE_S", 1)
    page, state = pages
    state["monthly"] = _placeholder_page(first_ms=4000)
    page.goto(MONTHLY)
    trace = []
    assert site.download_bill(page, tmp_path / "dl", "2026-08-31", tmp_path / "s.pdf",
                              title="Mortgage Statement - August 31, 2026", trace=trace), \
        [t.get("note") for t in trace]
    assert _picked(page) == [] and _pressed(page) == ["August 2026"]


def test_years_the_picker_fills_in_late_are_seen_before_anything_is_decided(pages, tmp_path,
                                                                          monkeypatch):
    """The picker offers only this year at first, its older years a second
    later, and the first list draws after that. Deciding on the first look
    that 2024 was not offered left the statement for the next run."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 12)
    page, state = pages
    state["monthly"] = _statements_page(THREE_YEARS, pickers=_picker(["2026"], placeholder="Select Year"),
                                        first_ms=2500, late_years=["2025", "2024"], late_years_ms=1000)
    page.goto(MONTHLY)
    trace = []
    assert site.download_bill(page, tmp_path / "dl", "2024-12-31", tmp_path / "s.pdf",
                              title="Mortgage Statement - December 31, 2024", trace=trace), \
        [t.get("note") for t in trace]
    assert _picked(page) == ["2024"] and _pressed(page) == ["December 2024"]
    assert "year not offered" not in site.capture_facts(trace)["steps"]


def test_waiting_for_a_year_ignores_the_old_list_and_gives_up_on_an_empty_year(pages):
    """2025's rows arrive at two seconds, above 2026's, which leave a
    second and a half later. The wait ends only once 2026's have gone."""
    page, state = pages
    state["monthly"] = _statements_page(delay_ms=2000, stale=True, leave_ms=1500)
    page.goto(MONTHLY)
    page.select_option("select", "2025")
    shown, waited, rows = site._wait_for_year(page, "2025", budget_s=10)
    assert shown and rows == 12 and waited >= 3
    assert _years_on_screen(page) == [["2025"], "2025"]
    page.select_option("select", "2023")
    assert site._wait_for_year(page, "2023", budget_s=5) == (False, 5, 0)


# -- capture --------------------------------------------------------------

def test_an_older_statement_is_pressed_on_its_own_years_list_and_saved(pages, tmp_path, monkeypatch):
    """December 2024, the one his recording downloaded. The list as drawn
    is 2026's, so the picker is set to 2024, and the row is looked for once
    the list shows 2024. The list redraws late and draws 2026's rows again
    first."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 12)
    page, state = pages
    state["monthly"] = _statements_page(delay_ms=1500, stale=True)
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    ok = site.download_bill(page, tmp_path / "dl", "2024-12-31", out,
                            title="Mortgage Statement - December 31, 2024", trace=trace)
    assert ok, [t.get("note") for t in trace]
    assert out.read_bytes() == _pdf("December 2024")
    assert _picked(page) == ["2024"]
    assert _pressed(page) == ["December 2024"]
    facts = site.capture_facts(trace)
    steps = facts["steps"]
    assert steps.index("chose the year") < steps.index("found the row") < steps.index("clicked")
    assert facts["year"]["year_rows"] == 7 and facts["year"]["years_offered"] == 4
    assert facts["year"]["year_wait_s"] >= 1
    assert "2024" not in json.dumps(facts)


def test_a_year_is_not_chosen_before_the_page_has_drawn_its_first_list(pages, tmp_path, monkeypatch):
    """The servicing app signs in again after every load and draws its
    first list a moment later. A year chosen before then can have that
    first list land after the chosen year's, so the picker, which is on
    the page from the start, is left alone until the list has drawn."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 12)
    page, state = pages
    state["monthly"] = _statements_page(first_ms=1500)
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, tmp_path / "dl", "2024-12-31", out,
                              title="Mortgage Statement - December 31, 2024", trace=trace), \
        [t.get("note") for t in trace]
    assert page.evaluate("window.__drawnWhenPicked") == [True]
    assert out.read_bytes() == _pdf("December 2024")


def test_this_years_statement_is_pressed_without_choosing_anything(pages, tmp_path):
    page, state = pages
    state["monthly"] = _statements_page()
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, tmp_path / "dl", "2026-08-31", out,
                              title="Mortgage Statement - August 31, 2026", trace=trace)
    assert out.read_bytes() == _pdf("August 2026")
    assert _picked(page) == [] and _pressed(page) == ["August 2026"]
    assert site.capture_facts(trace)["steps"][:3] == ["stayed on the list", "found the row", "clicked"]


@pytest.mark.parametrize("may_2023", [[], ["May 2023"]], ids=["no statement", "after the wait"])
def test_a_year_whose_list_never_shows_it_means_nothing_is_pressed(pages, tmp_path, monkeypatch,
                                                                   may_2023):
    """A statement an earlier run recorded, whose year's list now shows
    none, or shows it only after the wait for it has given up. The year is
    chosen, and the wait ends there with nothing pressed, even on a row
    that turns up later. The list is empty while it loads, so a capture
    that went on looking would still be looking when the row turns up."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 16)
    page, state = pages
    state["monthly"] = _statements_page(dict(LISTS, **{"2023": may_2023}), delay_ms=6000,
                                        loading=True)
    page.goto(MONTHLY)
    trace = []
    assert not site.download_bill(page, tmp_path / "dl", "2023-05-31", tmp_path / "s.pdf",
                                  title="Mortgage Statement - May 31, 2023", trace=trace)
    page.wait_for_timeout(2500)
    assert _picked(page) == ["2023"] and _pressed(page) == []
    assert _years_on_screen(page)[0] == (["2023"] if may_2023 else [])
    steps = site.capture_facts(trace)["steps"]
    assert "list never showed the year" in steps and "clicked" not in steps


def test_a_year_the_picker_does_not_offer_is_not_chosen(pages, tmp_path, monkeypatch):
    monkeypatch.setattr(site, "LIST_WAIT_S", 3)
    page, state = pages
    state["monthly"] = _statements_page()
    page.goto(MONTHLY)
    trace = []
    assert not site.download_bill(page, tmp_path / "dl", "2019-05-31", tmp_path / "s.pdf",
                                  title="Mortgage Statement - May 31, 2019", trace=trace)
    assert _picked(page) == [] and _pressed(page) == []
    facts = site.capture_facts(trace)
    assert facts["steps"][-2:] == ["year not offered", "no row has this date"]
    assert facts["year"]["years_offered"] == 4


# -- no picker ------------------------------------------------------------

def test_without_a_picker_discovery_and_capture_are_what_they_were(pages, tmp_path):
    """The page as the app knew it before, one year and no picker. The
    same statements are found and the same row is pressed."""
    page, state = pages
    state["monthly"] = _statements_page({"2026": LISTS["2026"]}, picker=False)
    state["yearly"] = _yearly_page("2025")
    page.goto(MONTHLY)
    docs = site.collect_download_docs(page)
    assert [d.date_text for d in docs] == [_iso(m) for m in LISTS["2026"]] + ["2025-12-31"]
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, tmp_path / "dl", "2026-08-31", out,
                              title="Mortgage Statement - August 31, 2026", trace=trace)
    assert _pressed(page) == ["August 2026"] and _picked(page) == []
    assert site.capture_facts(trace)["steps"][:3] == ["stayed on the list", "found the row", "clicked"]


def test_without_a_picker_the_walk_says_so_and_touches_nothing(pages):
    page, state = pages
    state["monthly"] = _statements_page({"2026": LISTS["2026"]}, picker=False)
    page.goto(MONTHLY)
    docs, seen = [], set()
    assert site._walk_years(page, docs, seen) == {
        "picker": "none", "selects": 0, "year_selects": 0, "most_years": 0, "most_options": 0}
    assert docs == []
    assert site.year_walk_lines({"monthly": site._walk_years(page, [], set())}) == [
        "No year picker on the monthly page, it has no dropdown"]


# -- the guard ------------------------------------------------------------

ACCOUNTS = ("<form><select onchange='pick(this.value)'><option>Checking 1234</option>"
            "<option>Savings 5678</option></select></form>")


def _formless(years) -> str:
    """A select of years with no form around it, whose neighbors could be
    anything."""
    options = "".join("<option class='year-option' value='%s'>%s</option>" % (y, y) for y in years)
    return ("<div class='row'><div class='form-group'><label class='form-label'>Year</label>"
            "<select class='form-select' onchange='pick(this.value)'>" + options
            + "</select></div></div>")


@pytest.mark.parametrize("page_body, state_word, why", [
    (_statements_page(pickers=_picker(list(LISTS), form_extra=(
        "<input name='amount'><button type='submit'>Continue</button>"))),
     "refused", "its form has more to fill in"),
    (_statements_page(pickers=_picker(list(LISTS), label="Payment year")),
     "refused", "its words name an action"),
    (_statements_page(pickers=_picker(list(LISTS), select_attrs=" aria-label='Card expiration year'")),
     "refused", "its words name an action"),
    (_statements_page(pickers=_picker(list(LISTS), form_extra="").replace(
        "<form ", "<form aria-label='Schedule a payment' ")),
     "refused", "the shared filter refused it"),
    (_statements_page(pickers="<div class='payment-card'>" + _picker(list(LISTS)) + "</div>"),
     "refused", "the shared filter refused it"),
    (_statements_page(pickers=_formless(list(LISTS))), "refused", "it is not in a form"),
    (_statements_page(pickers="<h5 class='widget-title'>Make a Payment</h5>" + _picker(list(LISTS))),
     "refused", "its words name an action"),
    (_statements_page(pickers=_picker(list(LISTS)) + _picker(list(LISTS))), "more than one", ""),
    (_statements_page(pickers=_picker(list(LISTS), select_attrs=" disabled") + _picker(list(LISTS))),
     "more than one", ""),
    (_statements_page(pickers=_picker(list(LISTS), hidden=True)), "hidden", ""),
    (_statements_page(pickers=ACCOUNTS), "none", ""),
    (_statements_page(pickers=_picker(["All years", "2025", "2024"], placeholder="Select Year")),
     "none", ""),
    (_statements_page(pickers=_picker(["2025", "Last 12 months", "2024"])), "none", ""),
    (_statements_page(pickers=_picker(["2025", "2024", "Older"])), "none", ""),
    (_statements_page(pickers=_picker(["2025", "2024"], placeholder="Select a payment year")),
     "refused", "its words name an action"),
    (_statements_page(extra="<input type='password'>"), "not on a statements page", ""),
], ids=["form with more to fill in", "label names a payment", "names a card",
        "form names a payment", "a class names a payment", "not in a form",
        "heading names a payment", "two pickers", "disabled beside another", "hidden",
        "accounts", "two that are not years", "not a year in the middle", "not a year last",
        "placeholder names a payment", "signed out"])
def test_a_select_that_could_do_something_else_is_never_chosen_in(pages, tmp_path, monkeypatch,
                                                                 page_body, state_word, why):
    """Only a select that offers nothing but years, on screen, alone in its
    form, with no word around it that names an action, on a signed-in
    statements page. Anything else is left exactly as it was, by
    discovery and by capture."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 3)
    page, state = pages
    state["monthly"] = page_body
    page.goto(MONTHLY)
    before = page.evaluate("Array.from(document.querySelectorAll('select')).map(s => s.value)")
    facts = site._walk_years(page, [], set())
    assert facts["picker"] == state_word
    assert facts.get("why", "") == why
    assert "walked" not in facts
    assert site._choose_year(page, "2025")[0] == "no picker"
    assert not site.download_bill(page, tmp_path / "dl", "2025-03-31", tmp_path / "s.pdf",
                                  title="Mortgage Statement - March 31, 2025", trace=[])
    assert _picked(page) == [] and _pressed(page) == []
    assert page.evaluate("Array.from(document.querySelectorAll('select')).map(s => s.value)") == before
    line = site.year_walk_lines({"monthly": facts})[0]
    assert line.startswith(("No year picker", "The year picker", "The monthly page"))
    if state_word == "none" and facts["most_years"]:
        # a dropdown that is short of being a picker says by how much
        assert line.endswith("offers 2 among %d options" % facts["most_options"])
        assert facts["most_options"] > 2


def test_choosing_a_year_never_presses_or_submits_anything():
    """The one write is Playwright's select_option on the picker itself.
    Nothing here clicks, presses a key, types, or submits a form, and the
    scripts that read the page only read."""
    src = "".join(inspect.getsource(f) for f in (
        site._year_picker, site._find_year_picker, site._choose_year, site._wait_for_year,
        site._walk_years, site._year_for_row, site._list_dates, site._on_statements_page))
    for banned in (".click(", ".submit(", "requestSubmit", ".press(", ".fill(", ".type(",
                   "dispatch_event", ".tap(", ".check(", "keyboard", "evaluate(\"", "evaluate('"):
        assert banned not in src, banned
    assert src.count(".select_option(") == 1
    for js in (site._SELECT_FACTS_JS, site._ONE_SELECT_JS, site._ALL_SELECTS_JS,
               site._DATED_CONTROLS_JS, site._CONTROL_ROWS_JS):
        for banned in ("submit", "click", "dispatchEvent", ".value =", "selectedIndex =", "focus("):
            assert banned not in js, banned


# -- the discovery line ------------------------------------------------------

WALK = {"monthly": {"picker": "found", "selects": 1, "year_selects": 1, "years": 4,
                    "walked": [[2026, 9, "shown"], [2025, 12, "shown"], [2024, 7, "shown"],
                               [2023, 0, "never showed"]]},
        "yearly": {"picker": "none", "selects": 0, "year_selects": 0, "most_years": 0,
                   "most_options": 0}}


def test_the_discovery_line_is_numbers_and_fixed_words_only():
    assert site.year_walk_lines(WALK) == [
        "Year picker on the monthly page walked 4 years, 2026 gave 9, 2025 gave 12, "
        "2024 gave 7, 2023 never showed",
        "No year picker on the yearly page, it has no dropdown"]
    assert site.year_walk_lines({"monthly": {"picker": "none", "selects": 1, "year_selects": 0,
                                             "most_years": 3, "most_options": 4}}) == [
        "No year picker on the monthly page, it has 1 dropdown and the one with the most "
        "years offers 3 among 4 options"]
    assert site.year_walk_lines({"monthly": {"picker": "refused", "selects": 1,
                                             "why": "its form has more to fill in"}}) == [
        "The year picker on the monthly page was not used, its form has more to fill in"]
    # anything that is not a number or one of the fixed words never reaches it
    junk = {"monthly": {"picker": "found", "walked": [["September 2026", 9, "shown"],
                                                      [2025, 3, "Statement for March"],
                                                      [2024, "7", "shown"], [12345, 1, "shown"]]},
            "yearly": {"picker": "Make a payment"},
            "Statement for March": {"picker": "found"}}
    assert site.year_walk_lines(junk) == ["Year picker on the monthly page walked 1 year, 2024 gave 7"]
    # Diagnose prints each line through the word list, which keeps a
    # sentence of ours whole, years and counts included
    for line in site.year_walk_lines(WALK):
        assert isinstance(line, Fixed) and shape_tree(line) == line
    # what goes to the journal, and so to the failure file, has places and no years
    facts = site.year_walk_facts(WALK)
    assert facts["monthly"]["walked"] == [[1, 9, "shown"], [2, 12, "shown"], [3, 7, "shown"],
                                          [4, 0, "never showed"]]
    assert facts["monthly"]["years"] == 4 and facts["yearly"] == WALK["yearly"]
    assert not YEAR_RE.search(json.dumps(facts))
    assert site.year_walk_facts(junk) == {
        "monthly": {"picker": "found", "walked": [[1, 9, "shown"], [3, 7, "shown"], [4, 1, "shown"]]},
        "yearly": {}}


YEAR_RE = re.compile(r"(19|20)\d\d")


def test_discovery_prints_the_years_and_the_journal_keeps_only_their_places(tmp_path, monkeypatch,
                                                                           caplog):
    """The line is what a tester reads and copies from the run, and it may
    name the years. The journal reaches the failure file, which he attaches
    in public, and seven statements in 2024 would say when his loan began,
    so it holds each year's place in the picker and no year."""
    import newrez_docs
    from paperpull_core import doc_types
    app = object.__new__(newrez_docs.App)
    app.args = SimpleNamespace(start_date=None)
    app.config = {"document_types": ["Statement", "Tax Document"], "default_start_date": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.rules = doc_types.load_rules()
    app.stats = {"mode": "discover", "skipped_out_of_scope": 0, "discovered": 0}
    app.page = lambda: SimpleNamespace(url=MONTHLY)
    app.check_session = lambda page: None
    monkeypatch.setattr(newrez_docs.site, "goto_documents", lambda page: True)

    def collect(page, walk=None):
        walk.update(WALK)
        return [site.RawDoc(title="Mortgage Statement - December 31, 2024",
                            date_text="2024-12-31", kind="statement")]

    monkeypatch.setattr(newrez_docs.site, "collect_download_docs", collect)
    with caplog.at_level(logging.INFO):
        assert app.cmd_discover(quiet=True) == 1
    assert "Year picker on the monthly page walked 4 years, 2026 gave 9" in caplog.text
    assert "No year picker on the yearly page, it has no dropdown" in caplog.text
    entries = app.journal.report()["entries"]
    [walked] = [e for e in entries if e.get("outcome") == "looked for the year pickers"]
    assert walked["facts"]["monthly"]["walked"] == [[1, 9, "shown"], [2, 12, "shown"],
                                                    [3, 7, "shown"], [4, 0, "never showed"]]
    assert walked["facts"]["yearly"]["picker"] == "none"
    # and the failure file the run writes carries the journal with no year in it
    app.write_failure("find the documents", "the documents were not found")
    [written] = list(app.paths.diagnostics.glob("failure-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    journal = [{k: v for k, v in e.items() if k not in ("at_ms", "i")}
               for e in report["journal"]["entries"]]
    assert walked["facts"] in [e.get("facts") for e in journal]
    assert not YEAR_RE.search(json.dumps(journal)), json.dumps(journal)
