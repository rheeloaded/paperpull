"""The bill history shows eight bills a page, with Prev and Next after them.

From 0.34.0 to 0.37.0 every bill older than the newest eight went to
Manual Review on both of the tester's accounts (#26). The tester's survey
lists the eight bill buttons and then "Prev" and "Next" right after the
last of them, and the recording showed the history API handing the page
all sixteen bills with or without a date range. So the older bills were on
the next page, and nothing ever pressed Next. These pages have that shape,
with a carousel's own Prev and Next elsewhere on the page, the selected
bill's panel after the third bill, and the quick actions after the pager.
Every date and amount is invented.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_site as site

TODAY = date(2027, 4, 14)
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
        "Nov", "Dec"]
_WORDS = {"next", "prev", "number", "unnamed", "other"}
_PAGER_WORDS = {"found", "not older than this page", "no bill list",
                "no next beside the list", "next disabled", "next changed",
                "click failed", "no change", "empty page", "pages do not join",
                "pages read alike", "page limit", "failed", "unreadable"}
_PRESS_WORDS = {"pressed", "pressed after the list redrew", "bill list moved",
                "click failed"}


def _bills(newest: date, n: int) -> list:
    """n monthly bills ending on the 11th, newest first."""
    out, y, m = [], newest.year, newest.month
    for _ in range(n):
        py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
        out.append({"iso": date(y, m, 11).isoformat(),
                    "text": f"{_MON[pm - 1]} 12 - {_MON[m - 1]} 11"})
        y, m = py, pm
    return out


def _newest_now() -> date:
    """The newest bill for a run on the real today, as download_bill dates
    the list from the real today."""
    today = date.today()
    if today.day >= 12:
        return date(today.year, today.month, 11)
    return date(today.year, today.month - 1, 11) if today.month > 1 else date(today.year - 1, 12, 11)


# MODE is how the list's Next behaves. "pages" turns eight at a time and
# is disabled on the last page. "append" adds the next eight below the
# ones showing, and is disabled once all are showing. "slow" empties the
# list and draws the next page two seconds later. "inert" does nothing.
# "same" draws the same page again. "slide" moves four bills instead of
# eight. "none" has no pager beside the list at all. "labelled" has a Next
# whose aria-label names a slide, not a page. "icon" has a Next that is a
# bare icon with no words and no label, which cannot be read and so is
# never pressed. EXTRA is more script, run once the page is drawn.
_SCRIPT = r"""
const BILLS = %(bills)s;
const MODE = '%(mode)s';
const PER = 8;
let first = 0, selected = 0;
window.presses = {next: 0, prev: 0, carousel: 0, pay: 0, usage: 0, range: 0,
                  download: 0, view: 0};
function bill(i) {
  return '<button class="bill" data-iso="' + BILLS[i].iso + '" onclick="pick(' + i +
    ')">Bill<br>' + BILLS[i].text + '<br>$1.00</button>';
}
function panel() {
  return '<div class="panel"><button>Internet<br>$1.00</button>' +
    '<button onclick="presses.view++">View/print PDF</button>' +
    '<button onclick="download()">Download PDF</button></div>';
}
function pager(lastPage) {
  if (MODE === 'none') return '';
  const label = MODE === 'labelled' ? ' aria-label="Next slide"' : '';
  const face = MODE === 'icon' ? '<svg width="8" height="8"></svg>' : 'Next';
  const off = lastPage && (MODE === 'pages' || MODE === 'append');
  return '<div class="pager"><button onclick="prev()"' + (first === 0 ? ' disabled' : '') +
    '>Prev</button><button id="nx" onclick="next()"' + label +
    (off ? ' disabled' : '') + '>' + face + '</button></div>';
}
function draw() {
  const from = MODE === 'append' ? 0 : first;
  const last = Math.min(first + PER, BILLS.length);
  let html = '';
  for (let i = from; i < last; i++) {
    html += bill(i);
    if (i - from === 2 && selected >= from && selected < last) html += panel();
  }
  document.getElementById('list').innerHTML = html + pager(last >= BILLS.length);
}
function pick(i) { selected = i; draw(); }
function prev() { presses.prev++; }
function next() {
  presses.next++;
  if (MODE === 'inert') return;
  if (MODE === 'same') { draw(); return; }
  const step = MODE === 'slide' ? 4 : PER;
  if (first + step >= BILLS.length) return;
  if (MODE === 'slow') {
    document.getElementById('list').innerHTML = '<div class="spinner"></div>';
    setTimeout(() => { first += step; draw(); }, 2000);
    return;
  }
  first += step;
  draw();
}
function download() {
  presses.download++;
  const blob = new Blob(['%%PDF-1.4\n%% bill ' + BILLS[selected].iso + '\n%%%%EOF\n'],
                        {type: 'application/pdf'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bill.pdf';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
draw();
%(extra)s
"""


def _history(bills: list, mode: str = "pages", extra: str = "") -> str:
    script = _SCRIPT % {"bills": json.dumps(bills), "mode": mode, "extra": extra}
    return f"""<body>
      <header><button>Shop</button><button>Support</button>
        <button>Account<br>Wireless</button></header>
      <div class="promo"><button onclick="presses.carousel++">Prev</button>
        <button onclick="presses.carousel++">Next</button></div>
      <a role="button" tabindex="0" onclick="presses.range++"
         aria-label="open date range selector to filter your billing activity"><span
         >Date range</span></a>
      <div id="list"></div>
      <h3>Quick actions</h3>
      <button onclick="presses.pay++">Make a payment</button>
      <button onclick="presses.usage++">Check my usage</button>
      <div class="promo"><button onclick="presses.carousel++">Next</button></div>
      <script>{script}</script></body>"""


@pytest.fixture()
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        chromium = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = chromium.new_context(accept_downloads=True)
    served = {"history": "<h1>history</h1>", "billing": 0}

    def fulfill(route):
        url = route.request.url
        if "billandpaymenthistory" in url:
            body = served["history"]
        else:
            served["billing"] += 1
            body = "<h1>billing</h1>"
        route.fulfill(status=200, content_type="text/html", body=body)

    ctx.route("https://www.att.com/**", fulfill)
    yield ctx.new_page(), served
    chromium.close()
    driver.stop()


def _open(browser, bills, mode="pages"):
    page, served = browser
    served["history"] = _history(bills, mode)
    page.goto(site.HISTORY_URL)
    return page


def _pages_note(trace, n=1):
    notes = [x for x in trace if x.get("note") == "bill list pages"]
    assert len(notes) == n, trace
    for note in notes:
        # Fixed words and counts only, since the file may be posted publicly.
        assert set(note) <= {"note", "pager", "turned", "period_buttons", "after_list", "turns"}
        assert note["pager"] in _PAGER_WORDS, note["pager"]
        assert isinstance(note["turned"], int)
        assert all(isinstance(k, int) for k in note["period_buttons"])
        assert set(note.get("after_list", [])) <= _WORDS
        assert set(note.get("turns", [])) <= {"replaced", "grew"}
    return notes[0]


def _press_note(trace):
    notes = [x for x in trace if x.get("note") == "bill button"]
    assert len(notes) == 1, trace
    assert set(notes[0]) == {"note", "press"}
    assert notes[0]["press"] in _PRESS_WORDS
    return notes[0]["press"]


def _download(browser, tmp_path, html, wanted, find=None, monkeypatch=None):
    """download_bill for `wanted` on a history page drawn from `html`.
    `find`, when given, runs after find_bill_button, with the page, before
    anything is pressed."""
    page, served = browser
    served["history"] = html
    if find is not None:
        real = site.find_bill_button

        def find_then(pg, iso, trace=None, today=None, anchor_year=None):
            got = real(pg, iso, trace, today, anchor_year)
            find(pg)
            return got

        monkeypatch.setattr(site, "find_bill_button", find_then)
    dl = tmp_path / "dl"
    dl.mkdir()
    out = tmp_path / "bill.pdf"
    trace = []
    ok = site.download_bill(page, dl, wanted, out, trace=trace)
    return ok, out, trace, page


@pytest.mark.parametrize("mode", ["pages", "append"])
def test_an_older_bill_is_saved_from_the_next_page(browser, tmp_path, mode):
    """The whole download, as the app runs it, for the oldest of sixteen
    bills. 0.37.0 found no button for it and fell through to the billing
    center, which shows other dates. Next may show the older eight in
    place of the newest or add them below, and either way the bill saved
    is the one asked for."""
    bills = _bills(_newest_now(), 16)
    wanted = bills[15]["iso"]
    ok, out, trace, page = _download(browser, tmp_path, _history(bills, mode), wanted)
    assert ok
    # The PDF is the one asked for, not the newest or one a year out.
    assert out.read_bytes().startswith(b"%PDF-")
    assert f"bill {wanted}".encode() in out.read_bytes()
    presses = page.evaluate("window.presses")
    assert presses["next"] == 1 and presses["download"] == 1
    assert presses["prev"] == presses["carousel"] == 0
    assert presses["pay"] == presses["usage"] == presses["view"] == 0
    assert presses["range"] == 0, "the Date range is not needed and not opened"
    note = _pages_note(trace)
    assert note["pager"] == "found" and note["turned"] == 1
    assert note["after_list"][:2] == ["prev", "next"]
    if mode == "pages":
        assert note["period_buttons"] == [8, 8] and note["turns"] == ["replaced"]
    else:
        assert note["period_buttons"] == [8, 16] and note["turns"] == ["grew"]
    assert _press_note(trace) == "pressed"


def test_each_page_takes_its_years_from_the_page_before(browser):
    """Three pages of eight. Each page's first bill carries on from the
    last bill of the page before. Starting every page from today would
    date the third page a year late and miss its bills."""
    bills = _bills(date(2027, 4, 11), 24)
    page = _open(browser, bills)
    trace = []
    found, turned = site.find_bill_button(page, "2025-08-11", trace, today=TODAY)
    assert found is not None and "Jul 12 - Aug 11" in found.text and turned == 2
    assert found.handle.get_attribute("data-iso") == "2025-08-11"
    note = _pages_note(trace)
    assert note["pager"] == "found" and note["turned"] == 2
    assert note["period_buttons"] == [8, 8, 8]
    # The same words a year later are on the second page, and that one is
    # the bill found when it is the one asked for.
    page = _open(browser, bills)
    found, _ = site.find_bill_button(page, "2026-08-11", [], today=TODAY)
    assert found.handle.get_attribute("data-iso") == "2026-08-11"
    assert page.evaluate("window.presses.next") == 1


def test_older_bills_added_below_are_dated_from_the_ones_before_them(browser):
    """Next adds the next eight below the ones showing. Only the new ones
    are dated, going on from the last bill above them. Dating the whole
    list again from the last bill of the page before would put every bill
    a year early, and the search stopped there before this was handled."""
    bills = _bills(date(2027, 4, 11), 24)
    page = _open(browser, bills, mode="append")
    trace = []
    found, turned = site.find_bill_button(page, "2025-08-11", trace, today=TODAY)
    assert found is not None and turned == 2
    assert found.handle.get_attribute("data-iso") == "2025-08-11"
    note = _pages_note(trace)
    assert note["pager"] == "found" and note["turns"] == ["grew", "grew"]
    assert note["period_buttons"] == [8, 16, 24]
    # The same words a year later, found among the first eight added.
    page = _open(browser, bills, mode="append")
    found, _ = site.find_bill_button(page, "2026-08-11", [], today=TODAY)
    assert found.handle.get_attribute("data-iso") == "2026-08-11"
    assert page.evaluate("window.presses.next") == 1


def test_a_list_that_empties_while_the_next_page_loads_is_waited_for(browser):
    """The next page can clear the list and draw itself a moment later.
    An empty list is not a page, and the one that follows is read."""
    bills = _bills(date(2027, 4, 11), 16)
    page = _open(browser, bills, mode="slow")
    trace = []
    found, _ = site.find_bill_button(page, "2026-01-11", trace, today=TODAY)
    assert found is not None and found.handle.get_attribute("data-iso") == "2026-01-11"
    note = _pages_note(trace)
    assert note["pager"] == "found" and note["period_buttons"] == [8, 8]


@pytest.mark.parametrize("mode, wanted, why", [
    # Next does nothing. The same eight dated on from the page before
    # would put the 2027 bill under 2026.
    ("inert", "2026-04-11", "no change"),
    # Next draws the same eight again, new elements, same words.
    ("same", "2026-04-11", "no change"),
    # Next moves four bills. The second page's words differ, so it looks
    # turned, but dated on from the page before every bill on it is a
    # year early, and 2025-09-11 would press the 2026 bill.
    ("slide", "2025-09-11", "pages do not join"),
])
def test_a_page_that_did_not_turn_as_a_page_is_never_read(browser, mode, wanted, why):
    bills = _bills(date(2027, 4, 11), 24)
    page = _open(browser, bills, mode=mode)
    trace = []
    assert site.find_bill_button(page, wanted, trace, today=TODAY) == (None, 1)
    note = _pages_note(trace)
    assert note["pager"] == why and note["turned"] == 1
    presses = page.evaluate("window.presses")
    assert presses["next"] == 1 and presses["download"] == 0


def test_a_page_that_reads_like_one_before_it_is_not_taken(browser):
    """Thirty-two bills of one amount. The fourth page's bills read word
    for word like the first page's, two years on. Were the list to go back
    to its first page before the press, the press would have nothing to
    tell the two apart by, and would save a bill two years out. So a bill
    on a page like that is left for review."""
    bills = _bills(date(2027, 4, 11), 32)
    page = _open(browser, bills)
    trace = []
    assert site.find_bill_button(page, bills[28]["iso"], trace, today=TODAY) == (None, 3)
    note = _pages_note(trace)
    assert note["pager"] == "pages read alike" and note["period_buttons"] == [8, 8, 8, 8]
    # A bill on a page that reads like no other is still found.
    page = _open(browser, bills)
    found, _ = site.find_bill_button(page, bills[20]["iso"], [], today=TODAY)
    assert found.handle.get_attribute("data-iso") == bills[20]["iso"]


@pytest.mark.parametrize("mode, why", [
    ("none", "no next beside the list"),
    ("labelled", "no next beside the list"),
    ("icon", "no next beside the list"),
])
def test_a_next_that_is_not_the_bill_lists_own_is_never_pressed(browser, mode, why):
    """A carousel's Next before the list or after the quick actions, a
    Next beside the list whose label names a slide, and one with nothing
    to read at all, are left alone."""
    bills = _bills(date(2027, 4, 11), 16)
    page = _open(browser, bills, mode=mode)
    trace = []
    assert site.find_bill_button(page, "2026-01-11", trace, today=TODAY) == (None, 0)
    note = _pages_note(trace)
    assert note["pager"] == why and note["turned"] == 0
    presses = page.evaluate("window.presses")
    assert presses["next"] == presses["carousel"] == presses["pay"] == 0
    if mode == "none":
        # What follows the list, in fixed words, the carousel's Next last.
        assert note["after_list"] == ["other", "other", "next"]
    if mode == "icon":
        # Stepped over as unnamed, and the carousel's Next beyond the
        # quick actions is still not reached.
        assert note["after_list"][:4] == ["prev", "unnamed", "other", "other"]


def test_the_last_page_ends_the_search(browser):
    """A bill older than every page is not found, and a disabled Next is
    not pressed."""
    bills = _bills(date(2027, 4, 11), 16)
    page = _open(browser, bills)
    trace = []
    assert site.find_bill_button(page, "2024-01-11", trace, today=TODAY) == (None, 1)
    note = _pages_note(trace)
    assert note["pager"] == "next disabled" and note["turned"] == 1
    assert page.evaluate("window.presses.next") == 1


def test_a_bill_no_older_than_the_page_turns_no_page(browser):
    """A date the page's own span covers but no button carries is not on a
    later page, so nothing is pressed."""
    bills = _bills(date(2027, 4, 11), 16)
    page = _open(browser, bills)
    trace = []
    assert site.find_bill_button(page, "2026-12-20", trace, today=TODAY) == (None, 0)
    assert _pages_note(trace)["pager"] == "not older than this page"
    assert page.evaluate("window.presses.next") == 0


def test_only_next_itself_is_the_pagers_next():
    word = site._pager_word
    for name in ("Next", "next", "Next page", "Go to next page"):
        assert word({"text": name, "label": ""}) == "next"
        assert word({"text": "", "label": name}) == "next"
    assert word({"text": "Next", "label": "Next page"}) == "next"
    for text, label in (("Next", "Next slide"), ("Next slide", ""), ("Continue", ""),
                        ("Next, make a payment", ""), ("Next", "Pay now"),
                        ("Make a payment", "")):
        assert word({"text": text, "label": label}) == "other", (text, label)
    assert word({"text": "Prev", "label": ""}) == "prev"
    assert word({"text": "2", "label": ""}) == "number"
    assert word({"text": "", "label": ""}) == "unnamed"


# -- the press lands on the bill that was dated -------------------------------

def test_a_list_back_on_its_first_page_is_not_pressed(browser, tmp_path, monkeypatch):
    """The bill was found on the second page, and the list went back to its
    first page before the press. Pressed by its place in the list, the
    first page's bill in that place would be saved under the older bill's
    date. Nothing is pressed and nothing is saved."""
    bills = _bills(_newest_now(), 16)
    wanted = bills[12]["iso"]
    ok, out, trace, page = _download(browser, tmp_path, _history(bills), wanted,
                                     find=lambda pg: pg.evaluate("first = 0; draw();"),
                                     monkeypatch=monkeypatch)
    assert not ok and not out.exists()
    assert _press_note(trace) == "bill list moved"
    presses = page.evaluate("window.presses")
    assert presses["download"] == presses["view"] == 0
    assert page.evaluate("selected") == 0, "no bill was pressed"


@pytest.mark.parametrize("wanted_at, turned", [(3, 0), (12, 1)])
def test_a_list_drawn_again_in_place_is_pressed_in_the_same_place(
        browser, tmp_path, monkeypatch, wanted_at, turned):
    """The page draws the list again between the read and the press, the
    same bills in new elements. The list reads as it did, so the bill in
    the same place is the bill that was dated, and it is saved. Refusing
    here would cost bills on the first page that 0.37.0 saved."""
    bills = _bills(_newest_now(), 16)
    wanted = bills[wanted_at]["iso"]
    ok, out, trace, page = _download(browser, tmp_path, _history(bills), wanted,
                                     find=lambda pg: pg.evaluate("draw()"),
                                     monkeypatch=monkeypatch)
    assert ok and f"bill {wanted}".encode() in out.read_bytes()
    assert _press_note(trace) == "pressed after the list redrew"
    assert page.evaluate("window.presses.next") == turned


def test_a_bill_click_that_fails_presses_no_download(browser, tmp_path):
    """The second page selects its own first bill as it draws, and
    something over the page takes the click meant for the bill. The
    Download PDF showing is then the first bill's. 0.37.0 went on to press
    it, through the page when the click was blocked, and saved that bill
    under the date asked for. Nothing more is pressed now."""
    bills = _bills(_newest_now(), 16)
    wanted = bills[12]["iso"]
    extra = r"""
      const turn = next;
      next = function () {
        const was = first;
        turn();
        if (first === was) return;
        selected = first;
        draw();
        const cover = document.createElement('div');
        cover.style.cssText = 'position:fixed;inset:0;z-index:99';
        document.body.appendChild(cover);
      };"""
    ok, out, trace, page = _download(browser, tmp_path, _history(bills, extra=extra), wanted)
    assert not ok and not out.exists()
    assert _press_note(trace) == "click failed"
    presses = page.evaluate("window.presses")
    assert presses["next"] == 1
    assert presses["download"] == presses["view"] == 0
    # Nor is the billing center tried, since it shows the current bill.
    assert browser[1]["billing"] == 0


def test_the_date_range_is_opened_on_the_list_as_first_shown(browser, tmp_path, monkeypatch):
    """The search turned two pages and missed, and the list sat on its
    third page. A span chosen there would be read as if it were the first
    page, dated from today, and the bill would be a year out. So the page
    is opened again before the Date range, and a span that brings older
    bills is read from its first page. The span here is a stand-in, since
    att.com's Date range is a calendar that is never filled in."""
    bills = _bills(_newest_now(), 28)
    wanted = bills[21]["iso"]
    seen = []

    def widen(pg, iso, trace=None, today=None):
        seen.append(pg.evaluate("first"))
        pg.evaluate("older => { BILLS.push(...older); draw(); }", bills[20:])
        return True, None

    monkeypatch.setattr(site, "widen_range", widen)
    ok, out, trace, page = _download(browser, tmp_path, _history(bills[:20]), wanted)
    assert seen == [0], "the list was on its first page when the span was chosen"
    assert ok and f"bill {wanted}".encode() in out.read_bytes()
    _pages_note(trace, n=2)
    first, second = [x for x in trace if x.get("note") == "bill list pages"]
    assert first["pager"] == "next disabled" and first["turned"] == 2
    assert second["pager"] == "found" and second["period_buttons"] == [8, 8, 8]


# View/print PDF was never found by role before its slash was escaped, so
# the paths that press it had never run. Once they could, a bill whose
# Download PDF gave nothing had View/print PDF pressed three times, once
# from Download PDF's attempt, once as the fallback and once more when the
# fallback searched for it by its words, and a View/print PDF drawn before
# Download PDF won the wait for Download PDF. These pin it to one press
# and Download PDF first.

_DOWNLOAD_GIVES_NOTHING = "download = function () { presses.download++; };"

_VIEW_PRINT_ONLY = r"""
  panel = function () {
    return '<div class="panel"><button>Internet<br>$1.00</button>' +
      '<button onclick="presses.view++">View/print PDF</button></div>';
  };
  draw();"""

# Download PDF drawn five seconds after the panel it belongs to, and only
# for the panel drawn last. download_bill first looks two seconds after
# pressing the bill, and waits up to ten more.
_DOWNLOAD_PDF_LATE = _VIEW_PRINT_ONLY.replace("return '<div", r"""
    const mine = (window.drawn = (window.drawn || 0) + 1);
    setTimeout(function () {
      const p = document.querySelector('.panel');
      if (window.drawn !== mine || !p || p.querySelector('.dl')) return;
      p.insertAdjacentHTML('beforeend',
        '<button class="dl" onclick="download()">Download PDF</button>');
    }, 5000);
    return '<div""", 1)


def _presses_on_leaving(page, monkeypatch) -> dict:
    """The history page's counts as they stood when download_bill left it
    for the billing center, which it opens after a bill gave nothing. The
    counts go with the page. Every wait is made instant, since nothing on
    these pages is late."""
    counts = {}
    real = page.goto

    def goto(url, **kwargs):
        if "mybillingcenter" in url:
            counts.update(page.evaluate("window.presses") or {})
        return real(url, **kwargs)

    monkeypatch.setattr(page, "goto", goto)
    monkeypatch.setattr(page, "wait_for_timeout", lambda ms: None)
    return counts


def test_view_print_is_pressed_once_when_download_pdf_gives_nothing(
        browser, tmp_path, monkeypatch):
    bills = _bills(_newest_now(), 16)
    presses = _presses_on_leaving(browser[0], monkeypatch)
    ok, out, trace, page = _download(
        browser, tmp_path, _history(bills, extra=_DOWNLOAD_GIVES_NOTHING), bills[1]["iso"])
    assert not ok and not out.exists()
    assert _press_note(trace) == "pressed"
    assert presses["download"] == 1
    assert presses["view"] == 1, "View/print PDF was pressed %d times" % presses["view"]


def test_view_print_alone_is_pressed_once(browser, tmp_path, monkeypatch):
    bills = _bills(_newest_now(), 16)
    presses = _presses_on_leaving(browser[0], monkeypatch)
    ok, out, trace, page = _download(
        browser, tmp_path, _history(bills, extra=_VIEW_PRINT_ONLY), bills[1]["iso"])
    assert not ok and not out.exists()
    assert presses["download"] == 0
    assert presses["view"] == 1, "View/print PDF was pressed %d times" % presses["view"]


# The bill's panel drawn anew with no Download PDF in it, the moment
# Download PDF is about to be pressed.
_PANEL_WITHOUT_DOWNLOAD = r"""() => {
  panel = function () {
    return '<div class="panel"><button>Internet<br>$1.00</button>' +
      '<button onclick="presses.view++">View/print PDF</button></div>';
  };
  draw();
}"""


def test_a_download_pdf_that_left_the_page_is_followed_by_no_other_press(
        browser, tmp_path, monkeypatch):
    """The page drew the bill's panel anew as Download PDF was about to be
    pressed, so the control the run held left the page and Playwright's
    press never began. Nothing is pressed for this bill after that. A
    View/print PDF found on the page drawn anew may be another bill's, and
    it was pressed next."""
    sync_api = pytest.importorskip("playwright.sync_api")
    bills = _bills(_newest_now(), 16)
    presses = _presses_on_leaving(browser[0], monkeypatch)
    real = sync_api.Locator.click
    drawn = []

    def drawn_anew_first(self, *args, **kwargs):
        if not drawn and (self.get_attribute("onclick", timeout=500) or "") == "download()":
            drawn.append(1)
            self.page.evaluate(_PANEL_WITHOUT_DOWNLOAD)
            kwargs["timeout"] = 500
        return real(self, *args, **kwargs)
    monkeypatch.setattr(sync_api.Locator, "click", drawn_anew_first)
    ok, out, trace, page = _download(browser, tmp_path, _history(bills), bills[1]["iso"])
    assert drawn, "Download PDF was never pressed"
    assert not ok and not out.exists()
    counts = presses or page.evaluate("window.presses")
    assert counts["download"] == 0
    assert counts["view"] == 0, "View/print PDF was pressed after Download PDF left the page"
    assert {"note": "the control left the page before it was pressed"} in trace


def test_download_pdf_drawn_after_view_print_is_still_the_one_pressed(browser, tmp_path):
    """In real time, since what is tested is the wait."""
    bills = _bills(_newest_now(), 16)
    wanted = bills[1]["iso"]
    ok, out, trace, page = _download(
        browser, tmp_path, _history(bills, extra=_DOWNLOAD_PDF_LATE), wanted)
    assert ok and f"bill {wanted}".encode() in out.read_bytes()
    presses = page.evaluate("window.presses")
    assert presses["download"] == 1
    assert presses["view"] == 0, "View/print PDF was taken before Download PDF appeared"
