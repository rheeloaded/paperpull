"""The history's Date range control, in the shapes it might take.

The 0.34.1 Run All found the Date range opener, pressed it, and then saw
no option at all, with the page's buttons the same as before (#26). So
either the menu did not open or its options are not buttons, options,
radios or links. These pages stand in for the likely shapes, a list of
plain divs, a select that only exists once the opener is pressed, and a
from and to date picker, because what appears after a click is DOM
behavior a fake page cannot show.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
import att_site as site

TODAY = date(2026, 9, 25)
HISTORY = "https://www.att.com/acctmgmt/billing/billandpaymenthistory"


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("https://www.att.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body="<h1>history</h1>"))
    pg = ctx.new_page()
    pg.goto(HISTORY)
    yield pg
    browser.close()
    driver.stop()


BILLS = """
<button>Bill<br>Aug 06 - Sep 05<br>$1.00</button>
<button>Bill<br>Jul 06 - Aug 05<br>$1.00</button>
<div id="older"></div>
"""

SHOW_OLDER = """
function showOlder(t) {
  window.chosen = t;
  document.getElementById('older').innerHTML =
    '<button>Bill<br>Sep 06 - Oct 05<br>$1.00</button>';
}
"""


def test_a_date_range_made_of_plain_divs_is_chosen_by_its_words(page):
    """The options may be divs with no role, which none of the role
    lookups in 0.34.1 could see. A year printed on the history before the
    menu opened is not an option."""
    page.set_content(f"""<body><h3>2025</h3>
      <button id="dr" aria-expanded="false" onclick="window.opens=(window.opens||0)+1;
        this.setAttribute('aria-expanded','true');
        document.getElementById('menu').style.display='block'">Date range</button>
      <div id="menu" style="display:none">
        <div class="opt" onclick="showOlder(this.innerText)">Last 6 months</div>
        <div class="opt" onclick="showOlder(this.innerText)">Last 12 months</div>
        <div class="opt" onclick="showOlder(this.innerText)">Last 24 months</div>
      </div>{BILLS}<script>{SHOW_OLDER}</script></body>""")
    trace = []
    chose, anchor = site.widen_range(page, "2025-10-05", trace, today=TODAY)
    assert chose and anchor is None
    assert page.evaluate("window.chosen") == "Last 12 months"
    assert page.evaluate("window.opens") == 1
    note = trace[0]
    assert note["kind"] == "text" and note["chose"] == "Last 12 months"
    assert note["opener_click"] == "ok" and note["opener_after"] == "true"
    assert note["opener"]["tag"] == "button"
    assert note["appeared_count"] >= 3


def test_a_select_that_appears_after_the_opener_is_set_through_the_filter(page):
    page.set_content(f"""<body>
      <button onclick="window.opens=(window.opens||0)+1;
        document.getElementById('slot').innerHTML =
        '<label>Show bills from <select id=s><option>Last 6 months</option>' +
        '<option>Last 18 months</option></select></label>'">Date range</button>
      <div id="slot"></div>{BILLS}</body>""")
    trace = []
    chose, anchor = site.widen_range(page, "2025-10-05", trace, today=TODAY)
    assert chose and anchor is None
    assert page.evaluate("document.getElementById('s').value") == "Last 18 months"
    assert page.evaluate("window.opens") == 1
    assert trace[0]["kind"] == "select after opener"


def test_a_date_picker_is_recorded_and_never_typed_into(page):
    """A from and to picker has no option to choose. The next file has to
    say that is what appeared, and nothing is typed or applied."""
    page.set_content(f"""<body>
      <button onclick="window.opens=(window.opens||0)+1;
        document.getElementById('picker').style.display='block'">Date range</button>
      <div id="picker" style="display:none" role="dialog">
        <input type="date" aria-label="From date"><input type="date" aria-label="To date">
        <button onclick="window.applied=true">Apply</button>
      </div>{BILLS}</body>""")
    trace = []
    chose, _ = site.widen_range(page, "2025-10-05", trace, today=TODAY)
    assert not chose
    note = trace[0]
    assert note["options"] == [] and note["chose"] == ""
    assert note["counts_before"]["date_inputs"] == 0
    assert note["counts_after"]["date_inputs"] == 2
    assert note["counts_after"]["dialogs"] == 1
    kinds = [(x["tag"], x["type"]) for x in note["appeared"]]
    assert kinds.count(("input", "date")) == 2
    assert {"tag": "button", "role": "", "type": "", "text": "Apply"} in note["appeared"]
    assert page.evaluate("window.opens") == 1
    assert page.evaluate("window.applied") is None
    assert page.evaluate(
        "Array.from(document.querySelectorAll('input')).every(i => i.value === '')")


def test_a_menu_that_never_opens_says_so(page):
    """The 0.34.1 file could not tell a menu that did not open from one
    whose options it could not see."""
    page.set_content(f"""<body>
      <button aria-expanded="false" aria-haspopup="listbox"
        onclick="window.opens=(window.opens||0)+1">Date range</button>{BILLS}</body>""")
    trace = []
    chose, _ = site.widen_range(page, "2025-10-05", trace, today=TODAY)
    assert not chose
    note = trace[0]
    assert note["appeared_count"] == 0 and note["appeared"] == []
    assert note["opener"] == {"tag": "button", "role": "", "expanded": "false",
                              "haspopup": "listbox", "controls": False}
    assert note["opener_after"] == "false"
    assert page.evaluate("window.opens") == 1


def test_what_appeared_is_masked_before_it_is_recorded(page):
    page.set_content(f"""<body>
      <button onclick="document.getElementById('m').style.display='block'">Date range</button>
      <div id="m" style="display:none"><div>Account 123456789</div>
        <div>Balance $84.20</div></div>{BILLS}</body>""")
    trace = []
    site.widen_range(page, "2025-10-05", trace, today=TODAY)
    texts = [x["text"] for x in trace[0]["appeared"]]
    assert "Account #########" in texts and "Balance $x.xx" in texts
    assert not any("123456789" in t or "84.20" in t for t in texts)
