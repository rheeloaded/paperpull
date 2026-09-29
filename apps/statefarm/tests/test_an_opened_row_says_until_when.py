"""An opened row that also says until when its document stays online (#37).

His 0.39.1 Pilot asked the list for 2026, found the Payment Receipt's row,
pressed its View Documents and saw the receipt appear, and then found no
row carrying the receipt's date, so it pressed nothing. The row was drawn
again, open, and a document there says until when it stays online, a day
two years on. Read that way, the opened row carried a day in 2028.

Here the opened row writes that line two ways, inside the row with the
month spelled out, and beside the button in the container the button sits
in, so the button's nearest dated container names only the day ahead.
Every date and name is invented, and nothing leaves this machine.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site

CENTER = "https://edocuments.statefarm.com/DocumentCenterUI/"

PAGE = """<!doctype html><html><body><h1>Document Center</h1><div id='rows'></div><script>
window.docsPressed = 0;
function openDoc(tag) {
  const bytes = new TextEncoder().encode('%PDF-1.4 ' + tag);
  window.open(URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'})), '_blank');
}
const ROWS = ROWS_JSON;
const WHERE = WHERE_JSON;
const LATER = LATER_JSON;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                'September', 'October', 'November', 'December'];
let openAt = -1;
function until(when) {
  const [m, d] = when.split('/');
  return WHERE === 'in the row' ? MONTHS[Number(m) - 1] + ' ' + Number(d) + ', ' + LATER
                                : m + '/' + d + '/' + LATER;
}
function docLink(r) {
  const a = document.createElement('a');
  a.href = '#';
  a.textContent = r.doc;
  a.onclick = () => { window.docsPressed++; openDoc('the document of ' + r.when); return false; };
  return a;
}
function rowNode(r, i, open) {
  const row = document.createElement('div');
  row.setAttribute('role', 'row');
  row.innerHTML = "<span class='when'></span> <span>Sent by mail.</span> <span class='act'><button class='view'></button></span>";
  row.querySelector('.when').textContent = (open && WHERE === 'with no date of its own') ? '' : r.when;
  const b = row.querySelector('button');
  b.textContent = open ? 'View Documents ' + i : 'View Documents' + i;
  b.onclick = () => press(i);
  if (open) {
    const docs = document.createElement('div');
    docs.appendChild(docLink(r));
    const line = document.createElement('span');
    line.textContent = ' Available online until ' + until(r.when);
    docs.appendChild(line);
    (WHERE === 'in the row' ? row : row.querySelector('.act')).appendChild(docs);
  }
  return row;
}
function press(i) {
  const list = document.getElementById('rows');
  const was = openAt;
  openAt = openAt === i ? -1 : i;
  [was, i].forEach(k => { if (k >= 0) list.children[k].replaceWith(rowNode(ROWS[k], k, k === openAt)); });
}
ROWS.forEach((r, i) => document.getElementById('rows').appendChild(rowNode(r, i, false)));
</script></body></html>"""

ROWS = [{"when": "09/12/2026", "doc": "Payment Receipt - Payment Receipt"},
        {"when": "07/22/2026", "doc": "Payment Receipt - Payment Receipt"},
        {"when": "04/16/2026", "doc": "Renewal Notice - 2017 Invented Roadster"}]


def _drive(where):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda r: r.abort())
    # Two years on from today, so the line stays a day ahead whenever this runs.
    html = (PAGE.replace("ROWS_JSON", json.dumps(ROWS)).replace("WHERE_JSON", json.dumps(where))
            .replace("LATER_JSON", json.dumps(date.today().year + 2)))
    ctx.route("https://edocuments.statefarm.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=html))
    pg = ctx.new_page()
    pg.goto(CENTER)
    return driver, browser, pg


@pytest.mark.parametrize("where", ["in the row", "beside the button"])
def test_the_opened_row_is_found_by_its_own_date_and_its_document_saved(tmp_path, where):
    driver, browser, pg = _drive(where)
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        assert site.download_bill(pg, None, "2026-07-22", out, title="Payment Receipt - Billing/Payments",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 the document of 07/22/2026"
        assert pg.evaluate("window.docsPressed") == 1
        assert {"note": "the row's control left the page after its press, so its row was looked "
                        "for again by this date", "rows_with_this_date": 1} in trace, trace
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["list_calls_after_the_press"] == 0, row
    finally:
        browser.close()
        driver.stop()


def test_a_row_that_names_only_a_day_ahead_takes_in_no_other_row(tmp_path):
    """The walk up past a day ahead stops before a container holding
    another row's View Documents, so a row with no date of its own is never
    dated by the row next to it. Nothing is pressed, and the trace says the
    one View Documents with nothing but a day ahead."""
    driver, browser, pg = _drive("with no date of its own")
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        assert not site.download_bill(pg, None, "2026-07-22", out,
                                      title="Payment Receipt - Billing/Payments", trace=trace)
        assert not out.exists() and pg.evaluate("window.docsPressed") == 0
        [again] = [t for t in trace if t.get("note") == "the row's control left the page after "
                   "its press, so its row was looked for again by this date"]
        assert again["rows_with_this_date"] == 0 and again["only_days_ahead"] == 1, again
        assert again["openers"] == 3 and again["with_another_date"] == 2, again
    finally:
        browser.close()
        driver.stop()


def test_a_link_with_only_a_day_ahead_is_never_dated_by_the_row_beside_it():
    """A row whose control is the document itself, naming no day but the
    one it stays online until. Walking past that day must stop at the row,
    since the list above it holds the other row's link and date, and the
    link would otherwise be taken as the other row's document."""
    from datetime import date
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    try:
        pg = browser.new_page()
        pg.set_content(
            "<main><div id='list'>"
            "<div role='row'><span>03/14/2026</span> <a href='#'>Renewal Notice</a></div>"
            "<div role='row'><a href='#'>Declarations Page</a> "
            "<span>Available online until 01/27/%d</span></div>"
            "</div></main>" % (date.today().year + 2))
        assert sorted(site._control_dates(pg)) == ["2026-03-14", "no date"]
        assert [name for _h, name in site._controls_for(pg, "2026-03-14")] == ["Renewal Notice"]
    finally:
        browser.close()
        driver.stop()


def test_a_day_ahead_is_passed_over_and_a_day_that_does_not_exist_is_still_none():
    from datetime import date
    later = date.today().year + 2
    assert site._date_not_ahead("03/13/2026 Available until March 13, %d" % later) == "2026-03-13"
    assert site._date_not_ahead("Available until 03/13/%d, sent 03/13/2026" % later) == "2026-03-13"
    assert site._date_not_ahead("Available until 03/13/%d" % later) is None
    assert site._date_not_ahead("Reference 13/45/2026") is None
    # parse_date itself is unchanged, the list's own dates go through it.
    assert site.parse_date("Available until March 13, %d" % later) == "%d-03-13" % later


# -- from the review of this change --------------------------------------------
#
# A row's date can sit in an element with no control of its own, a document
# sent by mail with no online copy, and the first version of the walk past a
# day ahead climbed into the list and took that neighbor's date, so another
# document was saved under this one's name.

LATER = date.today().year + 2

_PRESS_COUNT = ("<script>window.docsPressed = 0;"
                "function pressDoc(tag) { window.docsPressed++; openDoc(tag); }"
                "function openDoc(tag) { const b = new TextEncoder().encode('%PDF-1.4 ' + tag);"
                " window.open(URL.createObjectURL(new Blob([b], {type: 'application/pdf'})), '_blank'); }"
                "</script>")

NEIGHBOR_WITH_NO_CONTROL = {
    "a View Documents row": (
        "<main><div id='list'>"
        "<div role='row'><span>03/14/2026</span> <span>Renewal Notice, sent by mail</span></div>"
        "<div role='row'><span>Declarations Page</span> <span>Available online until 01/27/%d</span>"
        " <button class='view' onclick='this.nextElementSibling.hidden = false'>View Documents1</button>"
        "<div class='docs' hidden><a href='#' onclick=\"pressDoc('the declarations of 01/27/2026');"
        "return false\">Declarations Page - Homeowners</a></div></div>"
        "</div></main>" % LATER),
    "a document link row": (
        "<main><div id='list'>"
        "<div role='row'><span>03/14/2026</span> <span>Renewal Notice, no longer online</span></div>"
        "<div role='row'><a href='#' onclick=\"pressDoc('the declarations of 01/27/2026');"
        "return false\">Declarations Page</a> <span>Available online until 01/27/%d</span></div>"
        "</div></main>" % LATER),
}


def _serve(body):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda r: r.abort())
    html = "<!doctype html><html><body><h1>Document Center</h1>%s%s</body></html>" % (body, _PRESS_COUNT)
    ctx.route("https://edocuments.statefarm.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=html))
    pg = ctx.new_page()
    pg.goto(CENTER)
    return driver, browser, pg


@pytest.mark.parametrize("which", sorted(NEIGHBOR_WITH_NO_CONTROL))
def test_a_row_is_never_dated_by_a_neighbor_that_has_no_control(tmp_path, monkeypatch, which):
    # No row here carries the date, so the page's wait for one would run
    # its full length. Nothing pressed is proved as well by a short one.
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 3000)
    driver, browser, pg = _serve(NEIGHBOR_WITH_NO_CONTROL[which])
    try:
        assert [name for _h, name in site._controls_for(pg, "2026-03-14")] == []
        out = tmp_path / "doc.pdf"
        trace: list = []
        site.download_bill(pg, None, "2026-03-14", out, title="Declarations Page - Homeowners",
                           trace=trace)
        assert not out.exists() and pg.evaluate("window.docsPressed") == 0, trace
    finally:
        browser.close()
        driver.stop()


# A date heading over a block of rows, rows kept by key and opened by place,
# and a newer notice of the same day added and opened in the pressed row's
# place. With a line saying until when inside the opened row, the other
# View Documents in the block read no date at all, and counting only those
# that read this date let the coupe notice be saved as the roadster's.
_UNDER_ONE_DATE = """<section id='day'><h3>03/14/2026</h3></section><script>
let data = [{key: 'a', doc: 'Renewal Notice - 2017 Invented Roadster', tag: 'the roadster notice'}];
const NEWER = {key: 'b', doc: 'Renewal Notice - 2019 Invented Coupe', tag: 'the coupe notice'};
const kept = {};
let openAt = -1;
function rowFor(r) {
  if (!kept[r.key]) {
    const row = document.createElement('div');
    row.setAttribute('role', 'row');
    row.innerHTML = "<button class='view'></button><div class='docs' hidden><a href='#'></a>"
      + " <span>Available online until 03/14/LATER</span></div>";
    row.querySelector('a').textContent = r.doc;
    row.querySelector('a').onclick = () => { pressDoc(r.tag); return false; };
    row.querySelector('button').onclick = () => press(r.key);
    kept[r.key] = row;
  }
  return kept[r.key];
}
function draw() {
  const day = document.getElementById('day');
  data.forEach((r, i) => {
    const row = rowFor(r);
    const b = row.querySelector('button');
    b.textContent = 'View Documents' + i;
    b.setAttribute('aria-expanded', String(i === openAt));
    row.querySelector('.docs').hidden = i !== openAt;
    day.appendChild(row);
  });
}
function press(key) {
  openAt = data.findIndex(r => r.key === key);
  draw();
  setTimeout(() => { data = [NEWER].concat(data); draw(); }, 150);
}
draw();
</script>"""


def test_a_row_opened_in_place_under_a_date_heading_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 3000)
    driver, browser, pg = _serve(_UNDER_ONE_DATE.replace("LATER", str(LATER)))
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto", trace=trace)
        saved = out.read_bytes() if out.exists() else b""
        assert saved in (b"", b"%PDF-1.4 the roadster notice"), (saved, trace)
    finally:
        browser.close()
        driver.stop()


# -- from the second review of this change ---------------------------------------
#
# The walk past a day ahead was bounded by the nearest row, table row or list
# item, and a whole category drawn as one list item, or a layout table, is
# a row by that measure. A row that prints no date then took a neighbor's,
# one sent by mail with no control of its own. Any visible control also
# counted as the document a row revealed, so a help link beside a folded
# row's until line started the walk before any press. A control whose text
# around it holds other rows had a day ahead passed over there too, and the
# next date belonged to a neighbor. And an opened row that renames its button
# Hide Documents went uncounted as another row's. Each page below must save
# nothing, or only the document asked for.

IN_A_CATEGORY_ITEM = (
    "<main><ul id='cats'><li class='cat'><h2>Homeowners</h2>"
    "<div class='doc'><span>03/14/2026</span> <span>Declarations Page, sent by mail</span></div>"
    "<div class='doc'><span>Declarations Page</span> "
    "<button class='view' onclick='this.nextElementSibling.hidden = false'>View Documents1</button>"
    "<div class='docs' hidden><a href='#' onclick=\"pressDoc('the declarations of 01/27/2026');"
    "return false\">Declarations Page - Homeowners</a> "
    "<span>Available online until 01/27/%d</span></div></div>"
    "</li></ul></main>" % LATER)

IN_A_LAYOUT_TABLE = IN_A_CATEGORY_ITEM.replace(
    "<ul id='cats'><li class='cat'>", "<table><tr><td>").replace("</li></ul>", "</td></tr></table>")

REDRAWN_IN_A_CATEGORY_ITEM = """<main><ul id='cats'><li class='cat'><h2>Homeowners</h2>
<div class='doc'><span>03/14/2026</span> <span>Declarations Page, sent by mail</span></div>
<div class='doc' id='b'></div></li></ul></main><script>
function drawB(open) {
  const row = document.createElement('div');
  row.className = 'doc';
  row.id = 'b';
  row.innerHTML = "<span>Declarations Page</span> <button class='view'></button>";
  const b = row.querySelector('button');
  b.textContent = open ? 'View Documents 1' : 'View Documents1';
  b.onclick = () => drawB(!open);
  if (open) {
    const docs = document.createElement('div');
    docs.innerHTML = "<a href='#'>Declarations Page - Homeowners</a> <span>Available online until 01/27/LATER</span>";
    docs.querySelector('a').onclick = () => { pressDoc('the declarations of 01/27/2026'); return false; };
    row.appendChild(docs);
  }
  document.getElementById('b').replaceWith(row);
}
drawB(false);
</script>""".replace("LATER", str(LATER))

HELP_LINK_WHILE_FOLDED = (
    "<main><ul id='cats'><li class='cat'><h2>Homeowners</h2>"
    "<div class='doc'><span>03/14/2026</span> <span>Declarations Page, sent by mail</span></div>"
    "<div class='doc'><span>Declarations Page</span> "
    "<span>Available online until 01/27/%d</span> <a href='#help' class='help'>What is this?</a> "
    "<button class='view' onclick='this.nextElementSibling.hidden = false'>View Documents1</button>"
    "<div class='docs' hidden><a href='#' onclick=\"pressDoc('the declarations of 01/27/2026');"
    "return false\">Declarations Page - Homeowners</a></div></div>"
    "</li></ul></main>" % LATER)

DIRECT_LINK = (
    "<main><div id='list'>"
    "<div role='row'><span>03/14/2026</span> <span>Renewal Notice, sent by mail</span></div>"
    "<div role='row'><a href='#' onclick=\"pressDoc('the undated notice');return false\">"
    "Renewal Notice</a></div>"
    "<div role='row'><span>02/02/2026</span> <a href='#' onclick=\"pressDoc('the declarations');"
    "return false\">Declarations Page</a> <span>Available online until February 2, %d</span></div>"
    "</div></main>" % LATER)

VIEW_DOCUMENTS_UNDATED = (
    "<main><div id='list'>"
    "<div role='row'><span>03/14/2026</span> <span>Declarations Page, sent by mail</span></div>"
    "<div role='row'><span>Declarations Page</span> "
    "<button class='view' onclick='this.nextElementSibling.hidden = false'>View Documents1</button>"
    "<div class='docs' hidden><a href='#' onclick=\"pressDoc('the undated declarations');"
    "return false\">Declarations Page - Homeowners</a></div></div>"
    "<div role='row'><span>02/02/2026</span> <a href='#' onclick=\"pressDoc('the renewal');"
    "return false\">Renewal Notice</a> <span>Available online until February 2, %d</span></div>"
    "</div></main>" % LATER)

UNDER_ONE_DATE_HIDE = """<section id='day'><h3>03/14/2026</h3></section><script>
let data = [{key: 'a', doc: 'Renewal Notice - 2017 Invented Roadster', tag: 'the roadster notice'}];
const NEWER = {key: 'b', doc: 'Renewal Notice - 2019 Invented Coupe', tag: 'the coupe notice'};
const kept = {};
let openAt = -1;
function rowFor(r) {
  if (!kept[r.key]) {
    const row = document.createElement('div');
    row.setAttribute('role', 'row');
    row.innerHTML = "<button class='view'></button><div class='docs' hidden><a href='#'></a>"
      + " <span>Available online until 03/14/LATER</span></div>";
    row.querySelector('a').textContent = r.doc;
    row.querySelector('a').onclick = () => { pressDoc(r.tag); return false; };
    row.querySelector('button').onclick = () => press(r.key);
    kept[r.key] = row;
  }
  return kept[r.key];
}
function draw() {
  const day = document.getElementById('day');
  data.forEach((r, i) => {
    const row = rowFor(r);
    const b = row.querySelector('button');
    b.textContent = i === openAt ? 'Hide Documents' : 'View Documents' + i;
    b.setAttribute('aria-expanded', String(i === openAt));
    row.querySelector('.docs').hidden = i !== openAt;
    day.appendChild(row);
  });
}
function press(key) {
  openAt = data.findIndex(r => r.key === key);
  draw();
  setTimeout(() => { data = [NEWER].concat(data); draw(); }, 150);
}
draw();
</script>""".replace("LATER", str(LATER))


def _run(body, iso, title, tmp_path):
    driver, browser, pg = _serve(body)
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        site.download_bill(pg, None, iso, out, title=title, trace=trace)
        return (out.read_bytes() if out.exists() else b""), pg.evaluate("window.docsPressed"), trace
    finally:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("body,title,allowed", [
    (IN_A_CATEGORY_ITEM, "Declarations Page - Homeowners", b""),
    (IN_A_LAYOUT_TABLE, "Declarations Page - Homeowners", b""),
    (REDRAWN_IN_A_CATEGORY_ITEM, "Declarations Page - Homeowners", b""),
    (HELP_LINK_WHILE_FOLDED, "Declarations Page - Homeowners", b""),
    (DIRECT_LINK, "Renewal Notice - Auto", b""),
    (VIEW_DOCUMENTS_UNDATED, "Declarations Page - Homeowners", b""),
    (UNDER_ONE_DATE_HIDE, "Renewal Notice - Auto", b"%PDF-1.4 the roadster notice"),
], ids=["a category drawn as one list item", "a layout table row", "a row drawn anew in a category",
        "a help link beside a folded row", "an undated document link", "an undated View Documents row",
        "a row that renames its button Hide Documents"])
def test_no_page_has_another_documents_file_saved_under_this_name(tmp_path, monkeypatch, body, title,
                                                                     allowed):
    # No row carries the date on most of these, so the page's wait would run
    # its full length. Nothing pressed is proved as well by a short one.
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 3000)
    saved, pressed, trace = _run(body, "2026-03-14", title, tmp_path)
    assert saved in (b"", allowed), (saved, trace)
    if not allowed:
        assert pressed == 0, trace
