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

    def fake_catch(page, el, label, out_path, trace=None, dl_dir=None, check=None):
        pressed.append({"label": label, "visible": el.is_visible(),
                        "still the one": check() == "" if check else None})
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
    assert no_click == [{"label": "Statement for June 2026", "visible": True, "still the one": True}]
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
    assert no_click == [{"label": "Statement for June 2026", "visible": True, "still the one": True}]
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
    assert no_click == [{"label": "Form 1098 for 2025", "visible": True, "still the one": True}]


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


# -- what the network did, counted in a real browser -------------------------

PDF_BODY = b"%PDF-1.4\n" + b"0" * 3000 + b"\n%%EOF\n"


@pytest.fixture()
def browser_any_host(monkeypatch):
    """A browser whose every address is answered here. The statements page
    is Newrez's, the document comes from an invented address that is not,
    and one call is held and never answered. The waits are cut to seconds
    so a capture that gives up does so quickly."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "FIRST_WAIT_S", 1)
    monkeypatch.setattr(site, "LAST_WAIT_S", 1)
    monkeypatch.setattr(site, "IN_FLIGHT_WAIT_S", 3)
    ctx = browser.new_context(accept_downloads=True)
    state = {"page": "<h1>empty</h1>", "held": []}

    def serve(route):
        url = route.request.url
        if url.startswith(MONTHLY):
            route.fulfill(status=200, content_type="text/html", body=state["page"])
        elif url.endswith("/api/doc"):
            route.fulfill(status=500, content_type="application/json", body="{}")
        elif url.endswith("/held"):
            state["held"].append(route)
        elif url.endswith("/attach"):
            route.fulfill(status=200, body=PDF_BODY, headers={
                "content-type": "application/pdf",
                "content-disposition": "attachment; filename=Monthly Statement.pdf"})
        else:
            route.fulfill(status=404, body="")

    ctx.route("**/*", serve)
    pg = ctx.new_page()
    yield pg, state
    for route in state["held"]:
        try:
            route.abort()
        except Exception:
            pass
    browser.close()
    driver.stop()


def _link(onclick: str) -> str:
    return ("<table><tbody><tr><td>June 2026</td><td><a id='dl' href='javascript:void(0)'"
            " aria-label='Statement for June 2026' onclick=" + '"' + onclick + '"' + ">Download</a>"
            "</td></tr></tbody></table>")


def test_a_capture_that_gives_up_counts_every_request_by_where_it_went(browser_any_host, tmp_path):
    """Newrez answers its own call with an error, and the call to another
    address is never answered. Both are counted, the waiting one keeps the
    capture waiting to the cap, and no address reaches the facts."""
    page, state = browser_any_host
    state["page"] = _link("fetch('https://servicing.newrez.com/api/doc');"
                          "fetch('https://docs.example.test/held')")
    page.goto(MONTHLY)
    trace = []
    el = page.locator("#dl")
    assert site._catch_pdf(page, el, "Statement for June 2026", tmp_path / "s.pdf", trace,
                           tmp_path / "dl") is False
    gave_up = trace[-1]
    assert gave_up["note"] == "no PDF arrived"
    assert gave_up["in_flight_s"] == 3
    net = site.capture_facts(trace)["network"]
    assert net["provider"]["fetch_requests"] == 1
    assert net["provider"]["status_5xx"] == 1 and net["provider"]["finished"] == 1
    # the answered call is matched to the request it answers, so it is not pending
    assert net["provider"]["pending"] == 0
    assert net["elsewhere"]["fetch_requests"] == 1
    assert net["elsewhere"]["pending"] == 1 and net["elsewhere"]["pending_answered"] == 0
    assert "example" not in json.dumps(site.capture_facts(trace))


def test_a_document_the_browser_turns_into_a_download_is_counted_and_saved(browser_any_host, tmp_path,
                                                                          monkeypatch):
    """The shape his recording showed, a click that ends in a download
    named Monthly Statement.pdf, here from an address that is not Newrez's.
    The first wait is left long, since a capture that lands returns at once
    and a slow machine should not move it into the next wait."""
    monkeypatch.setattr(site, "FIRST_WAIT_S", 10)
    page, state = browser_any_host
    state["page"] = _link("location.href='https://docs.example.test/attach'")
    page.goto(MONTHLY)
    trace = []
    out = tmp_path / "s.pdf"
    assert site._catch_pdf(page, page.locator("#dl"), "Statement for June 2026", out, trace,
                           tmp_path / "dl")
    assert out.read_bytes()[:5] == b"%PDF-"
    facts = site.landing_facts(trace)
    assert facts["how"] == "download event" and facts["window"] == "first wait"
    assert facts["after_click_s"] < 10
    assert facts["network"]["elsewhere"]["document_requests"] == 1
    assert facts["network"]["elsewhere"]["attachments"] == 1


# -- the press lands on the control the guard approved, or nowhere -----------

def _pressable(month: str) -> str:
    """A row whose two controls write down which month was pressed."""
    note = "window.__pressed=(window.__pressed||[]).concat(['%s'])" % month
    link = "<a href='javascript:void(0)' aria-label='Statement for %s' onclick=\"%s\">%s</a>"
    return ("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (month, link % (month, note, "View"), link % (month, note, "Download")))


def _list(*months, extra: str = "") -> str:
    return ("<html><body><table><tbody id='t'>" + "".join(_pressable(m) for m in months)
            + "</tbody></table>" + extra + "</body></html>")


def _pressed(page) -> list:
    return page.evaluate("window.__pressed || []")


def _before_the_press(monkeypatch, do) -> None:
    """Runs `do(page)` once, when the capture reads the page's controls,
    which it does after the row was found and approved and before the
    press."""
    real = site._control_texts
    done = []

    def hooked(page):
        if not done:
            done.append(True)
            do(page)
        return real(page)

    monkeypatch.setattr(site, "_control_texts", hooked)


JUNE = "[aria-label='Statement for June 2026']"
RENAME = "document.querySelectorAll(sel).forEach(a => a.setAttribute('aria-label', 'Statement for May 2026'))"
JUNE_BECOMES_MAY = "sel => " + RENAME
JUNE_BECOMES_MAY_SOON = "sel => setTimeout(() => " + RENAME + ", 700)"


def test_a_row_drawn_while_an_earlier_download_is_waited_on_does_not_move_the_press(
        browser_any_host, tmp_path, monkeypatch):
    """A leftover download in the folder kept the capture waiting between
    finding June and pressing it, and a newer row drawn meanwhile moved the
    press onto July. The wait comes before the row is looked for now."""
    monkeypatch.setattr(site, "EARLIER_STILL_S", 3)
    monkeypatch.setattr(site, "_ABANDONED", {})
    page, state = browser_any_host
    newer = json.dumps(_pressable("August 2026"))
    state["page"] = _list("July 2026", "June 2026", extra=(
        "<script>setTimeout(function(){document.getElementById('t')"
        ".insertAdjacentHTML('afterbegin', " + newer + ")}, 1000)</script>"))
    dl = tmp_path / "dl"
    dl.mkdir()
    (dl / "Unconfirmed 1.crdownload").write_bytes(b"%PDF-1.4 part")
    page.goto(MONTHLY)
    trace = []
    site.download_bill(page, dl, "2026-06-30", tmp_path / "s.pdf",
                       title="Mortgage Statement - June 30, 2026", trace=trace)
    assert _pressed(page) == ["June 2026"]
    assert site.capture_facts(trace)["steps"][:2] == ["stayed on the list", "waited for an earlier download"]


def test_a_list_that_redraws_in_another_order_before_the_press_does_not_move_it(
        browser_any_host, tmp_path, monkeypatch):
    """The control is held as the element the guard approved, not as the
    third control on the page, so a row drawn above it cannot take the
    press."""
    page, state = browser_any_host
    state["page"] = _list("July 2026", "June 2026")
    page.goto(MONTHLY)
    _before_the_press(monkeypatch, lambda p: p.evaluate(
        "row => document.getElementById('t').insertAdjacentHTML('afterbegin', row)",
        _pressable("August 2026")))
    trace = []
    site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                       title="Mortgage Statement - June 30, 2026", trace=trace)
    assert _pressed(page) == ["June 2026"]
    assert "clicked" in site.capture_facts(trace)["steps"]


def test_a_row_that_moves_before_it_is_held_is_not_fetched(browser_any_host, tmp_path, monkeypatch):
    """A control whose link is a PDF on Newrez's own host is fetched rather
    than pressed. The list redrew after June was found and before it was
    held, so the third control on the page became July's, and July's link
    was fetched and saved as June."""
    page, state = browser_any_host

    def linked(month: str) -> str:
        slug = month.split()[0].lower()
        return ("<tr><td>%s</td><td><a href='https://servicing.newrez.com/doc/%s.pdf' "
                "aria-label='Statement for %s'>Download</a></td></tr>" % (month, slug, month))

    state["page"] = ("<html><body><table><tbody id='t'>" + linked("July 2026") + linked("June 2026")
                     + "</tbody></table></body></html>")
    fetched = []

    def fetch(p, href):
        # Never sent. Which link would have been fetched is the question.
        fetched.append(href.rsplit("/", 1)[-1])
        return PDF_BODY

    monkeypatch.setattr(site, "_fetch_pdf", fetch)
    page.goto(MONTHLY)
    real = site._wait_for_control

    def found_then_redrawn(p, iso, trace):
        el, label = real(p, iso, trace)
        p.evaluate("row => document.getElementById('t').insertAdjacentHTML('afterbegin', row)",
                   linked("August 2026"))
        return el, label

    monkeypatch.setattr(site, "_wait_for_control", found_then_redrawn)
    trace = []
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2026-06-30", out,
                              title="Mortgage Statement - June 30, 2026", trace=trace) is False
    assert not out.exists() and fetched == []
    facts = site.capture_facts(trace)
    assert facts["steps"][-1] == "row changed before the press"
    assert facts["click"]["why"] == "its name changed"


def test_a_row_reused_for_another_month_before_the_press_is_not_pressed(
        browser_any_host, tmp_path, monkeypatch):
    """A page can keep the element and give it another row's name. It is
    read again right before the press, and nothing is pressed."""
    page, state = browser_any_host
    state["page"] = _list("July 2026", "June 2026")
    page.goto(MONTHLY)
    _before_the_press(monkeypatch, lambda p: p.evaluate(JUNE_BECOMES_MAY, JUNE))
    trace = []
    assert site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                              title="Mortgage Statement - June 30, 2026", trace=trace) is False
    assert _pressed(page) == []
    facts = site.capture_facts(trace)
    assert facts["steps"][-1] == "row changed before the press"
    assert facts["click"]["why"] == "its name changed"


COVER = "<div style='position:fixed;left:0;top:0;width:100%;height:100%;z-index:9'></div>"


def test_a_press_through_the_page_is_made_only_on_the_approved_row(browser_any_host, tmp_path,
                                                                  monkeypatch):
    """When the ordinary press cannot reach the control, something lying
    over it say, the control is pressed through the page instead. Its row
    changed while the ordinary press was trying, and that press used to go
    through anyway."""
    monkeypatch.setattr(site, "CLICK_TIMEOUT_MS", 2000)
    page, state = browser_any_host
    state["page"] = _list("July 2026", "June 2026", extra=COVER)
    page.goto(MONTHLY)
    # after the name is read again, while the ordinary press is still trying
    _before_the_press(monkeypatch, lambda p: p.evaluate(JUNE_BECOMES_MAY_SOON, JUNE))
    trace = []
    site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                       title="Mortgage Statement - June 30, 2026", trace=trace)
    assert _pressed(page) == []
    facts = site.capture_facts(trace)
    assert "click failed" in facts["steps"] and "row changed before the page click" in facts["steps"]
    assert facts["click"]["why"] == "its name changed"


def test_the_press_through_the_page_reads_the_name_in_the_same_step(browser_any_host, tmp_path,
                                                                    monkeypatch):
    """The name is read once more inside the page, in the same step as the
    press, so a change in the moment after the last reading is caught too."""
    monkeypatch.setattr(site, "CLICK_TIMEOUT_MS", 1000)
    page, state = browser_any_host
    state["page"] = _list("July 2026", "June 2026", extra=COVER)
    page.goto(MONTHLY)
    real = site._still_the_one
    readings = []

    def read_then_changed(el, iso, label):
        why = real(el, iso, label)
        readings.append(why)
        if len(readings) == 3:
            # the third reading is the one before the press through the page
            page.evaluate(JUNE_BECOMES_MAY, JUNE)
        return why

    monkeypatch.setattr(site, "_still_the_one", read_then_changed)
    trace = []
    site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                       title="Mortgage Statement - June 30, 2026", trace=trace)
    assert readings == ["", "", ""]
    assert _pressed(page) == []
    assert "row changed before the page click" in site.capture_facts(trace)["steps"]


def test_another_tab_keeping_a_call_open_does_not_keep_the_capture_waiting(browser_any_host, tmp_path,
                                                                          monkeypatch):
    """His browser has his other tabs in it. One of them holding a call
    open counted as the document on its way and kept every capture that
    gave up waiting its full extra time, and filled the counts with it."""
    page, state = browser_any_host
    state["page"] = _list("June 2026")
    page.goto(MONTHLY)
    other = page.context.new_page()
    other.goto("https://mail.example.test/inbox")

    def other_tab_calls(p):
        other.evaluate("() => { fetch('https://mail.example.test/held'); }")
        other.wait_for_timeout(300)

    _before_the_press(monkeypatch, other_tab_calls)
    trace = []
    assert site.download_bill(page, None, "2026-06-30", tmp_path / "s.pdf",
                              title="Mortgage Statement - June 30, 2026", trace=trace) is False
    assert _pressed(page) == ["June 2026"]
    gave_up = trace[-1]
    assert gave_up["note"] == "no PDF arrived"
    assert gave_up["in_flight_s"] == 0
    assert gave_up["network"]["elsewhere"]["requests"] == 0
    assert state["held"], "the other tab's call really was held open"
