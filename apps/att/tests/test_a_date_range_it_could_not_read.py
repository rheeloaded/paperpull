"""A date range is not chosen past a dropdown that could not be read.

A bill the history does not show is reached through the history's date
range. The bill buttons carry no year ("Jul 12 - Aug 11"), so the year a
chosen span names is the year every button on the list is dated by. The
span was set in the first dropdown whose options read as spans of time,
and a dropdown whose name could not be read was passed over without a
word, as though it were not there. When that one was the list's own
filter, the span went to whatever came next, another dropdown of years, a
Date range menu the list does not follow, or a legend of years beside the
filter. The list stayed as it was, it was dated to the year asked for, and
its bill of the same month was pressed and saved under the older bill's
date. Nothing after the save reads a bill's own dates, so it was filed as
done.

Found by the census of every app that looks for one dropdown among a
page's dropdowns, after Ally pressed another year's tax form the same way
(apps/ally/tests/test_a_year_it_could_not_show.py). att.com's own date
range is a calendar that is never filled in, so this takes a page shape no
tester has shown. The page below is invented, every date on it is made
up, and the browser reaches nothing but it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_site as site
from paperpull_core import controls
from paperpull_core.testkit import stall_reads

_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
        "Nov", "Dec"]


def _bills(year: int) -> list:
    """Eight monthly bills ending on the 11th, September back to February
    of `year`, newest first, so no list of them crosses a January."""
    return [{"iso": "%d-%02d-11" % (year, m),
             "text": "%s 12 - %s 11" % (_MON[m - 2], _MON[m - 1])}
            for m in range(9, 1, -1)]


# The list as the page first shows it, and as its own filter shows 2024.
# The two read word for word alike, as one year's bills do the next.
LISTS = {"shown": _bills(2026), "2024": _bills(2024)}
WANTED = "2024-08-11"

# The names of the list's filter could not be read, or its options could not.
UNREAD = {
    "what it is": dict(locator=("evaluate",), scripts=(controls.IDENTITY_JS,)),
    "its options": dict(locator=("evaluate",), scripts=(site._OPTIONS_JS,)),
}

# Beside the list's filter, a control of years that the list does not
# follow. A second dropdown, the usage chart's own Date range menu, or a
# legend of years drawn with the filter by the list's own Date range,
# which then holds the filter until it is pressed.
DECOYS = ("dropdown", "menu", "legend")
# What the list's filter needs pressed or set before it shows 2024.
TO_2024 = {"dropdown": {"range": "2024"}, "menu": {"range": "2024"},
           "legend": {"opener": "pressed", "range": "2024"}}
# What is pressed before the filter is found to be unread.
BEFORE_ANY_CHOICE = {"dropdown": {}, "menu": {}, "legend": {"opener": "pressed"}}

PAGE = r"""<!doctype html><html><body>
<h1>Bill history</h1>
<div id="filter"></div>
<div id="list"></div>
<h2>Usage</h2>
<div id="decoy"></div>
<script>
const LISTS = %(lists)s;
const DECOY = %(decoy)s;
const RANGE = '<label for="range">Show</label><select id="range" data-guid="range">' +
  '<option>Last 6 months</option><option>2025</option><option>2024</option></select>';
let bills = LISTS.shown, selected = 0;
// Each bill pressed, by its own date, and each control set, with what to.
window.pressed = [];
window.set = {};

function draw() {
  let html = '';
  bills.forEach((b, i) => {
    html += '<button class="bill" onclick="pick(' + i + ')">Bill<br>' + b.text +
      '<br>$1.00</button>';
    if (i === 2) html += '<div class="panel"><button onclick="download()">Download PDF</button></div>';
  });
  document.getElementById('list').innerHTML = html;
}
function pick(i) { selected = i; window.pressed.push(bills[i].iso); draw(); }
function download() {
  const blob = new Blob(['%%PDF-1.4\n%% bill ' + bills[selected].iso + '\n%%%%EOF\n'],
                        {type: 'application/pdf'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bill.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
// The list follows its own filter, wherever the filter is drawn.
function follow() {
  document.getElementById('range').addEventListener('change', e => {
    window.set.range = e.target.value;
    if (LISTS[e.target.value]) { bills = LISTS[e.target.value]; selected = 0; draw(); }
  });
}
const filter = document.getElementById('filter');
const decoy = document.getElementById('decoy');
if (DECOY === 'legend') {
  filter.innerHTML = '<button id="opener">Date range</button><div id="panel"></div>';
  document.getElementById('opener').addEventListener('click', () => {
    window.set.opener = 'pressed';
    document.getElementById('panel').innerHTML =
      '<div class="legend"><div>2026</div><div>2025</div><div>2024</div></div>' + RANGE;
    follow();
    for (const d of document.querySelectorAll('.legend div'))
      d.addEventListener('click', () => { window.set.legend = d.textContent; });
  });
} else {
  filter.innerHTML = RANGE;
  follow();
}
if (DECOY === 'dropdown') {
  decoy.innerHTML = '<label for="usage">Usage year</label><select id="usage" data-guid="usage">' +
    '<option>2026</option><option>2025</option><option>2024</option></select>';
  document.getElementById('usage').addEventListener('change', e => { window.set.usage = e.target.value; });
} else if (DECOY === 'menu') {
  decoy.innerHTML = '<button id="opener">Date range</button>' +
    '<div role="listbox" id="menu" hidden><div role="option">2026</div>' +
    '<div role="option">2025</div><div role="option">2024</div></div>';
  document.getElementById('opener').addEventListener('click', () => {
    window.set.opener = 'pressed';
    document.getElementById('menu').hidden = false;
  });
  for (const o of document.querySelectorAll('[role=option]'))
    o.addEventListener('click', () => { window.set.menu = o.textContent; });
}
draw();
</script></body></html>"""


@pytest.fixture()
def att():
    """Opens the history page beside a control of years that the list does
    not follow. The billing center shows no bill, so a bill the history
    does not give is not saved."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    served = {"history": ""}

    def answer(route):
        url = route.request.url
        if not url.startswith(site.BASE + "/"):
            route.abort()
        elif "billandpaymenthistory" in url:
            route.fulfill(status=200, content_type="text/html", body=served["history"])
        else:
            route.fulfill(status=200, content_type="text/html", body="<h1>billing</h1>")

    ctx.route("**/*", answer)

    def open_page(decoy):
        served["history"] = PAGE % {"lists": json.dumps(LISTS), "decoy": json.dumps(decoy)}
        return ctx.new_page()
    yield open_page
    browser.close()
    driver.stop()


_STATE_JS = "() => ({pressed: window.pressed, set: window.set})"


def _download(page, tmp_path, monkeypatch):
    """download_bill for the August 2024 bill, as a run asks for it, and
    what the history page had pressed and set by then. A bill the history
    does not give is looked for on the billing center next, which takes
    the history's place in the tab, so the history is read as it is left."""
    left = {}
    real = page.goto

    def goto(url, **kwargs):
        if "billandpaymenthistory" not in url and not left:
            left.update(page.evaluate(_STATE_JS))
        return real(url, **kwargs)
    monkeypatch.setattr(page, "goto", goto)
    dl = tmp_path / "dl"
    dl.mkdir()
    out = tmp_path / "bill.pdf"
    trace = []
    ok = site.download_bill(page, dl, WANTED, out, trace=trace)
    return ok, out, trace, left or page.evaluate(_STATE_JS)


def _range_note(trace) -> dict:
    notes = [x for x in trace if x.get("note") == "date range"]
    assert len(notes) == 1, trace
    return notes[0]


def _saved_the_one_asked_for(decoy, ok, out, trace, history):
    """The filter was set to 2024, the list drew 2024, and its August bill
    was pressed and saved. Nothing else was set or opened."""
    assert ok and b"bill %s" % WANTED.encode() in out.read_bytes()
    assert history == {"pressed": [WANTED], "set": TO_2024[decoy]}
    assert _range_note(trace)["kind"] in ("select", "select after opener")


def _pressed_nothing(decoy, ok, out, trace, history):
    """No bill was pressed and nothing was saved, nothing was set, and the
    trace says why in fixed words."""
    pressed = history.get("pressed")
    assert not ok and not out.exists() and pressed == [], \
        "it pressed %s and %s" % (pressed, "saved it" if out.exists() else "returned %r" % ok)
    assert history["set"] == BEFORE_ANY_CHOICE[decoy]
    assert _range_note(trace)["kind"] == "a dropdown could not be read", trace


@pytest.mark.parametrize("decoy", DECOYS)
def test_the_bill_asked_for_is_saved_through_the_date_range(att, monkeypatch, tmp_path, decoy):
    """The twin with nothing in the way, so the tests below are about what
    is. The other control of years is never touched."""
    page = att(decoy)
    _saved_the_one_asked_for(decoy, *_download(page, tmp_path, monkeypatch))


@pytest.mark.parametrize("decoy", DECOYS)
@pytest.mark.parametrize("unread", list(UNREAD))
def test_a_date_range_that_could_not_be_read_presses_no_bill(att, monkeypatch, tmp_path, decoy, unread):
    """The list's filter did not answer. A name that did not answer made it
    count as absent, and the span went to the other control of years. The
    list stayed on 2026, was dated 2024, and 2026's August bill was pressed
    and saved as 2024's. Options that did not answer ended the look at the
    dropdowns, so the span went to a menu or a legend when there was one,
    and when there was not, nothing was pressed and nothing said why."""
    page = att(decoy)
    stall_reads(monkeypatch, {"range"}, **UNREAD[unread])
    _pressed_nothing(decoy, *_download(page, tmp_path, monkeypatch))


def test_a_dropdown_after_the_date_range_that_could_not_be_read_changes_nothing(att, monkeypatch, tmp_path):
    """The twin. The dropdown that did not answer comes after the list's
    filter, which was found first and could be read, so the span is set
    there as before."""
    page = att("dropdown")
    stall_reads(monkeypatch, {"usage"}, locator=("evaluate",), scripts=(controls.IDENTITY_JS,))
    _saved_the_one_asked_for("dropdown", *_download(page, tmp_path, monkeypatch))
