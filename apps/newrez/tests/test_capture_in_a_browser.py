"""Capture finding its row on the servicing app, in a real browser.

His Pilot on 0.34.1 found eleven documents and saved one of five (#38).
The attempt file for a failed one held an empty list, so capture never
reached a click, and the failure file ended on the servicing app signing
in again through Okta with no list requested yet. Capture looked for the
row five seconds after loading the page, where discovery looks ten or
more after. These drive a real page whose rows arrive late, whose rows
are named by an aria-label so they are found by their words, and whose
1098 lives on the yearly page.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import newrez_site as site

LOAN = "1234567"
MONTHLY = f"https://servicing.newrez.com/servicing/{LOAN}/statements/monthly"
YEARLY = f"https://servicing.newrez.com/servicing/{LOAN}/statements/yearly"


def _row(month: str, hidden: bool = False) -> str:
    style = " style='display:none'" if hidden else ""
    return (f"<tr{style}><td>{month}</td>"
            f"<td><a href='javascript:void(0)' aria-label='Statement for {month}'>View</a></td>"
            f"<td><a href='javascript:void(0)' aria-label='Statement for {month}'>Download</a></td></tr>")


def _late(rows: str, ms: int) -> str:
    """A page whose list is written in after `ms`, the way the servicing
    app fills it in once its sign-in has finished."""
    return ("<html><body><main><h1>Statements</h1><table><tbody id='t'></tbody></table></main>"
            "<script>setTimeout(function(){document.getElementById('t').innerHTML = "
            + json.dumps(rows) + "}, " + str(ms) + ")</script></body></html>")


@pytest.fixture()
def browser_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    bodies = {"monthly": "<h1>empty</h1>", "yearly": "<h1>empty</h1>"}

    def serve(route):
        which = "yearly" if route.request.url.endswith("/yearly") else "monthly"
        route.fulfill(status=200, content_type="text/html", body=bodies[which])

    ctx.route("https://servicing.newrez.com/**", serve)
    pg = ctx.new_page()
    yield pg, bodies
    browser.close()
    driver.stop()


@pytest.fixture()
def no_click(monkeypatch):
    """Nothing is clicked. Capture's own click is replaced by a note of
    which control it would have pressed, and the route to the servicing
    app is taken as done, since the test page already is it."""
    class Pressed(list):
        pass

    pressed = Pressed()

    def fake_catch(page, el, label, out_path, trace=None, dl_dir=None):
        pressed.append({"label": label, "visible": el.is_visible()})
        return True

    monkeypatch.setattr(site, "_catch_pdf", fake_catch)
    opened = []

    def fake_goto(page):
        opened.append(page.url)
        return True

    monkeypatch.setattr(site, "goto_documents", fake_goto)
    pressed.opened = opened
    return pressed


def test_capture_waits_for_rows_that_arrive_after_the_app_signs_in_again(browser_page, no_click, tmp_path):
    """Four of his five were looked for before the list was on the page."""
    page, bodies = browser_page
    bodies["monthly"] = _late(_row("July 2026") + _row("June 2026"), 3000)
    page.goto(MONTHLY)
    trace = []
    ok = site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                            title="Mortgage Statement - June 30, 2026", trace=trace)
    assert ok, trace
    assert no_click == [{"label": "Statement for June 2026", "visible": True}]
    found = [t for t in trace if t["note"] == "found the row"][0]
    assert found["waited_s"] >= 2
    assert found["dates_read"][:2] == ["2026-07-31", "2026-07-31"]


def test_a_control_on_screen_wins_over_a_hidden_copy_of_the_same_row(browser_page, no_click, tmp_path):
    """The failure file counted eight rows with four on screen. A hidden
    twin of the list comes first here, as a phone layout kept in the page
    would, and is found by its words like the visible one."""
    page, bodies = browser_page
    bodies["monthly"] = ("<table><tbody>" + _row("June 2026", hidden=True) + _row("June 2026")
                         + "</tbody></table>")
    page.goto(MONTHLY)
    trace = []
    assert site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                              title="Mortgage Statement - June 30, 2026", trace=trace)
    assert no_click == [{"label": "Statement for June 2026", "visible": True}]
    found = [t for t in trace if t["note"] == "found the row"][0]
    assert found["chosen_visible"] is True
    assert found["same_date"] == 4


def test_a_1098_is_looked_for_on_the_yearly_page(browser_page, no_click, tmp_path):
    """Discovery reads the 1098s off the yearly page and capture only
    ever opened the monthly one."""
    page, bodies = browser_page
    bodies["monthly"] = "<table><tbody>" + _row("June 2026") + "</tbody></table>"
    bodies["yearly"] = ("<table><tbody><tr><td>2025</td><td><a href='javascript:void(0)'"
                        " aria-label='Form 1098 for 2025'>Download</a></td></tr></tbody></table>")
    page.goto(MONTHLY)
    trace = []
    assert site.download_bill(page, None, "2025-12-31", tmp_path / "t.pdf",
                              title="Tax Document - December 31, 2025", trace=trace)
    assert page.url == YEARLY
    assert no_click == [{"label": "Form 1098 for 2025", "visible": True}]


def test_a_row_that_is_not_there_leaves_a_trace_that_says_so(browser_page, no_click, tmp_path, monkeypatch):
    """His attempt file for June held an empty list, which said nothing
    about why. It must now say what the page held, with the loan number
    masked."""
    monkeypatch.setattr(site, "LIST_WAIT_S", 3, raising=False)
    page, bodies = browser_page
    bodies["monthly"] = "<table><tbody>" + _row("July 2026") + _row("May 2026") + "</tbody></table>"
    page.goto(MONTHLY)
    trace = []
    assert not site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                                  title="Mortgage Statement - June 30, 2026", trace=trace)
    assert no_click == []
    assert trace, "an empty trace is what his file held"
    miss = trace[-1]
    assert miss["note"] == "no row on the page has this date"
    assert miss["controls"] == 4 and miss["visible"] == 4
    assert "2026-06-30" not in miss["dates_read"]
    assert "2026-07-31" in miss["dates_read"] and "2026-05-31" in miss["dates_read"]
    assert LOAN not in json.dumps(trace)


def test_capture_does_not_reload_a_statements_page_the_run_just_opened(browser_page, no_click, tmp_path):
    """The run opens the monthly page and then capture opened it again,
    which starts the app's sign-in over while the first load is still
    signing in."""
    page, bodies = browser_page
    bodies["monthly"] = "<table><tbody>" + _row("June 2026") + "</tbody></table>"
    page.goto(MONTHLY)
    page.evaluate("window.__stayed = 1")
    trace = []
    assert site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                              title="Mortgage Statement - June 30, 2026", trace=trace)
    assert page.evaluate("window.__stayed") == 1
    assert no_click.opened == []
    assert trace[0]["note"] == "already on the statements page"
