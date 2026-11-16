"""paperpull_core.pressing in a real browser, on pages made for it.

A press brings its control to the middle of the window, reads the topmost
element at the point Playwright will press, and presses unforced only when
that is the control or inside it, the button or link around an element
counting as the control the way it does for Playwright. Anything else on
top, and nothing is pressed and the run stops. Every page here replaces
eval as American Express does, so page.evaluate fails on all of them and
what is read is read in the module's own world. Each page writes what was
pressed into a line of its own, read back through a locator. Every word
on these pages is made up.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paperpull_core import pressing
from paperpull_core.words import words_for

WORDS = words_for("Example Bank")
CANARY = "Quillonby"

HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>made up</title>
<script>window.eval = function () { throw new Error('eval is disabled'); };
function said(what) { document.getElementById('log').textContent += what + ';'; }</script>
<style>[hidden] { display: none !important; } html, body { margin: 0; font: 16px sans-serif; }
.go { position: absolute; width: 120px; height: 36px; }
.cover { position: fixed; background: #016fd0; color: #fff; z-index: 10; }</style>
</head><body><output id="log"></output>
"""

PAGES = {}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = PAGES.get(self.path.lstrip("/"), "").encode("utf-8")
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def show(browser, server, request):
    """A page of this test's own, with eval replaced, open in a tab of its
    own sized 1000 by 600."""
    context = browser.new_context(viewport={"width": 1000, "height": 600})
    name = request.node.name.replace("[", "_").replace("]", "")

    def open_page(body):
        PAGES[name] = HEAD + body + "</body></html>"
        page = context.new_page()
        page.goto(server + name)
        return page

    yield open_page
    context.close()


def pressed(page):
    return [p for p in page.locator("#log").inner_text().split(";") if p]


BUTTON = ('<button class="go" id="go" style="right: 40px; bottom: 30px; position: fixed;" '
          'onclick="said(\'go\')">Download</button>')


def test_eval_is_refused_on_these_pages(show):
    """Not vacuous. Playwright's own evaluate fails here as it does on
    American Express, so whatever reads these pages reads them another way."""
    page = show(BUTTON)
    with pytest.raises(Exception, match="eval is disabled"):
        page.evaluate("1 + 1")


def test_a_control_with_nothing_on_top_is_pressed_once(show):
    page = show(BUTTON)
    pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert pressed(page) == ["go"]


def test_something_over_its_middle_means_nothing_is_pressed(show):
    """A box over the middle of the button, labeled with a word on no list.
    Nothing is pressed, not the box, and the stop says what is over the
    button only through the word list."""
    page = show(BUTTON + '<div class="cover" role="button" aria-label="Chat with %s" '
                'style="right: 20px; bottom: 20px; width: 200px; height: 60px;" '
                'onclick="said(\'cover\')"><span>%s</span></div>' % (CANARY, CANARY))
    with pytest.raises(pressing.Covered) as stopped:
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert pressed(page) == []
    stop = stopped.value
    assert stop.lines[0] == "Something on the page covers the button, so nothing was pressed."
    assert "stays in place as the page scrolls" in stop.lines[1]
    assert stop.facts["over_it"]["tag"] == "div" and stop.facts["over_it"]["role"] == "button"
    assert stop.facts["fixed"] is True
    said = " ".join(stop.lines) + repr(stop.facts)
    assert CANARY.lower() not in said.lower()
    assert "a" * len(CANARY) in said, "the word off the list is said as its shape"
    assert stop.reason == "something on the page is over the control"


def test_something_over_one_corner_leaves_the_middle_to_be_pressed(show):
    page = show(BUTTON + '<div class="cover" style="right: 20px; bottom: 20px; width: 40px; '
                'height: 20px;" onclick="said(\'cover\')"></div>')
    pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert pressed(page) == ["go"]


def test_a_control_is_brought_to_the_middle_before_it_is_read(show):
    """A bar pinned to the foot of the window covers the button where the
    page first shows it. In the middle of the window it is clear."""
    page = show('<div style="height: 560px"></div>'
                '<button class="go" id="go" style="position: relative; display: block; '
                'margin-left: 400px" onclick="said(\'go\')">Download</button>'
                '<div style="height: 1200px"></div>'
                '<div class="cover" style="left: 0; right: 0; bottom: 0; height: 60px;" '
                'onclick="said(\'bar\')"></div>')
    pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert pressed(page) == ["go"]


def test_an_icon_inside_the_button_counts_as_the_button(show):
    """The locator finds an icon that lets presses through to its button.
    Playwright checks a press against the button around an element, and so
    does this."""
    page = show('<button class="go" id="go" style="left: 100px; top: 100px" '
                'onclick="said(\'go\')"><span id="icon" title="Pdf download icon" '
                'style="pointer-events: none">PDF</span></button>')
    pressing.click(page, page.locator("#icon"), css="[title]", what="the icon", words=WORDS)
    assert pressed(page) == ["go"]


def test_a_frame_over_the_control_is_said_to_be_a_frame(show):
    page = show(BUTTON + '<iframe class="cover" title="Chat" srcdoc="hello" '
                'style="right: 10px; bottom: 10px; width: 300px; height: 100px; border: 0">'
                '</iframe>')
    with pytest.raises(pressing.Covered) as stopped:
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert stopped.value.facts["over_it"]["tag"] == "iframe"
    assert pressed(page) == []


def _in_a_shadow_root(covered: bool) -> str:
    over = ('<div id="over" style="position: absolute; left: 0; top: 0; width: 120px; '
            'height: 36px; background: red"></div>') if covered else ""
    return ('<div id="host" style="position: absolute; left: 100px; top: 100px"></div>'
            '<script>const root = document.getElementById("host").attachShadow({mode: "open"});'
            'root.innerHTML = \'<button id="inner" style="width: 120px; height: 36px">Go</button>'
            + over + '\';'
            'root.getElementById("inner").onclick = () => said("inner");</script>')


@pytest.mark.parametrize("covered", [False, True], ids=["clear", "covered"])
def test_a_control_in_a_shadow_root_is_read_through_it(show, covered):
    """The button and, on one page, a box over it, both inside one shadow
    root."""
    page = show(_in_a_shadow_root(covered))
    button = page.locator("#host").locator("#inner")
    if covered:
        with pytest.raises(pressing.Covered):
            pressing.click(page, button, css="button", what="the button", words=WORDS)
        assert pressed(page) == []
    else:
        pressing.click(page, button, css="button", what="the button", words=WORDS)
        assert pressed(page) == ["inner"]


def test_a_radio_button_under_its_own_label_is_checked_through_the_label(show):
    """The input is drawn by its label, which sits over it, as styled radio
    buttons are. Playwright's own unforced check refuses it, the label is
    pressed instead, and it reads as checked."""
    body = ('<div style="position: absolute; left: 100px; top: 100px">'
            '<input type="radio" id="pdf" name="t" value="statement_pdf" '
            'style="position: absolute; left: 0; top: 0; width: 18px; height: 18px; margin: 0; '
            'opacity: 0" onchange="said(\'pdf\')">'
            '<label for="pdf" style="position: relative; z-index: 1; display: block; '
            'padding-left: 28px; line-height: 18px">Billing Statement (PDF)</label></div>')
    page = show(body)
    with pytest.raises(Exception):
        page.locator("#pdf").check(timeout=1500)
    assert pressed(page) == [], "Playwright's own check pressed nothing"
    pressing.check(page, page.locator("#pdf"), css="input[type=radio]", what="the PDF choice",
                   words=WORDS)
    assert page.locator("#pdf").is_checked() and pressed(page) == ["pdf"]


def test_a_radio_button_drawn_by_its_label_alone_is_checked_through_it(show):
    page = show('<label style="position: absolute; left: 100px; top: 100px">'
                '<input type="radio" id="pdf" value="statement_pdf" style="display: none" '
                'onchange="said(\'pdf\')"> Billing Statement (PDF)</label>')
    pressing.check(page, page.locator("#pdf"), css="input[type=radio]", what="the PDF choice",
                   words=WORDS)
    assert page.locator("#pdf").is_checked() and pressed(page) == ["pdf"]


def test_a_checkbox_already_checked_is_not_pressed(show):
    page = show('<input type="checkbox" id="c" checked onclick="said(\'c\')">')
    pressing.check(page, page.locator("#c"), css="input", what="the box", words=WORDS)
    assert pressed(page) == [] and page.locator("#c").is_checked()


def test_a_control_the_selector_does_not_find_is_not_pressed(show):
    """The caller's selector and Playwright's box have to agree on exactly
    one element, or nothing is pressed."""
    page = show(BUTTON)
    with pytest.raises(pressing.Unread) as stopped:
        pressing.click(page, page.locator("#go"), css="a", what="the button", words=WORDS)
    assert stopped.value.facts == {"why": "none"}
    assert pressed(page) == []


# Something that comes over the button the moment the pointer moves onto it,
# after every read before the press has passed. Its own presses are told.
LATE = ('<button class="go" id="go" style="left: 400px; top: 250px" onclick="said(\'go\')">'
        'Download</button>%s<script>let once = false; document.addEventListener("mousemove",'
        ' () => { if (once) return; once = true;'
        ' document.getElementById("late").style.visibility = "visible"; });</script>')
LATE_DIV = ('<div id="late" style="position: fixed; left: 380px; top: 230px; width: 200px; '
            'height: 80px; z-index: 9; background: #06c; visibility: hidden" '
            'onmousedown="said(\'div-down\')" onclick="said(\'div-click\')"></div>')
LATE_FRAME = ('<iframe id="late" style="position: fixed; left: 380px; top: 230px; width: 200px; '
              'height: 80px; border: 0; z-index: 9; visibility: hidden" '
              'srcdoc="<body style=&quot;margin: 0&quot;><button style=&quot;width: 200px; '
              'height: 80px&quot; onmousedown=&quot;parent.said(\'frame-down\')&quot; '
              'onclick=&quot;parent.said(\'frame-click\')&quot;>Chat</button></body>"></iframe>')


def test_an_element_that_comes_over_the_control_as_it_is_pressed_stops_the_run(show):
    """Playwright's own check at the press keeps the press from the element
    that came over the button, and says so only when its verdict is waited
    for. So the press is not reported as made, and the run stops."""
    page = show(LATE % LATE_DIV)
    with pytest.raises(pressing.NotPressed):
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS,
                       timeout=2000)
    assert pressed(page) == []


def test_a_frame_that_comes_over_the_control_as_it_is_pressed_stops_the_run(show):
    """Playwright's own check cannot see into a frame, so the press goes to
    the frame that came over the button. The point is read again right
    after the press, and the frame there stops the run, so the press is not
    reported as made."""
    page = show(LATE % LATE_FRAME)
    with pytest.raises(pressing.Covered) as stopped:
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    stop = stopped.value
    assert stop.reason == "something on the page came over the control"
    assert stop.facts["after_the_press"] is True and stop.facts["over_it"]["tag"] == "iframe"
    assert stop.lines[0].startswith("Something came over the button as it was pressed")
    assert "go" not in pressed(page)


def test_a_frame_already_under_the_control_is_not_taken_for_one_that_came_over_it(show):
    """A box with its own Close sits over a frame, and the Close hides the
    box, so once it is pressed the frame is on top at the point. The frame
    was there before the press, under the box, so nothing stops."""
    page = show('<iframe srcdoc="under" style="position: fixed; left: 300px; top: 200px; '
                'width: 400px; height: 200px; border: 0"></iframe>'
                '<div id="box" style="position: fixed; left: 280px; top: 180px; width: 440px; '
                'height: 240px; background: #fff; z-index: 5">'
                '<button class="go" id="close" style="left: 160px; top: 100px" '
                'onclick="said(\'close\'); document.getElementById(\'box\').hidden = true">'
                'Close</button></div>')
    pressing.click(page, page.locator("#close"), css="button", what="the Close", words=WORDS)
    assert pressed(page) == ["close"]


def test_a_frame_raised_over_a_control_still_there_stops_the_run(show):
    """A frame sits under the button, and pressing the button raises the
    frame over it. The frame was at the point before the press, but the
    button is still there under it, so the frame came over the button and
    the run stops."""
    page = show('<iframe id="under" srcdoc="under" style="position: fixed; left: 300px; '
                'top: 200px; width: 400px; height: 200px; border: 0; z-index: 1"></iframe>'
                '<button class="go" id="go" style="position: fixed; left: 440px; top: 280px; '
                'z-index: 5" onclick="said(\'go\'); '
                'document.getElementById(\'under\').style.zIndex = 9">Download</button>')
    with pytest.raises(pressing.Covered) as stopped:
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert stopped.value.facts["after_the_press"] is True
    assert pressed(page) == ["go"]


def test_two_elements_of_one_box_are_not_told_apart_so_nothing_is_pressed(show):
    """Two buttons drawn in the same place, both matching the selector. The
    box cannot say which is the one Playwright would press, so neither is."""
    page = show('<button class="go" id="a" style="left: 100px; top: 100px" '
                'onclick="said(\'a\')">One</button>'
                '<button class="go" id="b" style="left: 100px; top: 100px" '
                'onclick="said(\'b\')">Two</button>')
    with pytest.raises(pressing.Unread) as stopped:
        pressing.click(page, page.locator("#b"), css="button", what="the button", words=WORDS)
    assert stopped.value.facts == {"why": "several"}
    assert pressed(page) == []


def test_a_checked_checkbox_under_its_own_label_is_not_pressed(show):
    """Its label is drawn over it, so a press would go through the label and
    uncheck it. It is checked already, so nothing is pressed at all."""
    page = show('<div style="position: absolute; left: 100px; top: 100px">'
                '<input type="checkbox" id="c" checked style="position: absolute; left: 0; '
                'top: 0; width: 18px; height: 18px; margin: 0; opacity: 0" '
                'onclick="said(\'c\')">'
                '<label for="c" style="position: relative; z-index: 1; display: block; '
                'padding-left: 28px; line-height: 18px">Keep me posted</label></div>')
    pressing.check(page, page.locator("#c"), css="input", what="the box", words=WORDS)
    assert pressed(page) == [] and page.locator("#c").is_checked()


def test_a_covered_label_is_not_pressed_either(show):
    page = show('<div style="position: absolute; left: 100px; top: 100px">'
                '<input type="radio" id="pdf" style="opacity: 0; position: absolute; margin: 0">'
                '<label for="pdf" style="position: relative; z-index: 1; padding-left: 28px">PDF'
                '</label></div><div class="cover" style="left: 90px; top: 90px; width: 300px; '
                'height: 60px" onclick="said(\'cover\')"></div>')
    with pytest.raises(pressing.Covered):
        pressing.check(page, page.locator("#pdf"), css="input", what="the PDF choice",
                       words=WORDS)
    assert pressed(page) == [] and not page.locator("#pdf").is_checked()


# --- A control the page keeps turned off -----------------------------------------

OFF_BUTTON = BUTTON.replace(' onclick=', ' disabled onclick=')
OFF_COVER = ('<div class="cover" style="right: 0; bottom: 0; width: 300px; height: 120px;" '
             'onclick="said(\'cover\')">Chat</div>')
# How Bootstrap and Material UI draw a turned off control, so it takes no
# pointer and what is at its point is what holds it.
NO_POINTER = '<style>#go { pointer-events: none; }</style>'


def _click_off(page, timeout):
    pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS,
                   timeout=timeout)


def test_a_control_turned_off_the_whole_press_is_left_with_nothing_pressed(show):
    """Playwright says it waited the whole time and never began its press,
    and the control still shows, turned off, with nothing over it."""
    page = show(OFF_BUTTON)
    with pytest.raises(pressing.TurnedOff) as stop:
        _click_off(page, 700)
    assert pressed(page) == []
    assert stop.value.after_a_press
    assert stop.value.facts == {"verdict": "off", "error": "timeout"}


def test_a_turned_off_control_is_waited_for_the_presses_own_time(show, monkeypatch):
    """A press given longer than PRESS_MS, as one that waits for a download
    is, waits that long for the control to turn on, as Playwright always
    did, so a dialog's Download the page turns on late is still pressed."""
    import time
    monkeypatch.setattr(pressing, "PRESS_MS", 300)
    page = show(OFF_BUTTON)
    started = time.monotonic()
    with pytest.raises(pressing.TurnedOff):
        _click_off(page, 1500)
    assert time.monotonic() - started >= 1.4
    assert pressed(page) == []


def test_a_control_the_page_turns_on_while_it_is_waited_for_is_pressed(show):
    page = show(OFF_BUTTON + "<script>setTimeout(() => { "
                "document.getElementById('go').disabled = false; }, 400);</script>")
    _click_off(page, 8000)
    assert pressed(page) == ["go"]


def test_a_turned_off_control_under_a_cover_stops_the_run_as_covered(show):
    page = show(OFF_BUTTON + OFF_COVER)
    with pytest.raises(pressing.Covered):
        _click_off(page, 700)
    assert pressed(page) == []


def test_a_turned_off_control_drawn_to_take_no_pointer_is_left(show):
    """What is at its point is what holds it, which is no cover."""
    page = show(OFF_BUTTON + NO_POINTER)
    with pytest.raises(pressing.TurnedOff):
        _click_off(page, 700)
    assert pressed(page) == []


def test_a_cover_over_a_turned_off_control_drawn_to_take_no_pointer_still_stops_the_run(show):
    page = show(OFF_BUTTON + NO_POINTER + OFF_COVER)
    with pytest.raises(pressing.Covered):
        _click_off(page, 700)
    assert pressed(page) == []


def test_a_control_turned_on_that_takes_no_pointer_is_not_pressed(show):
    """Only a control read as turned off is read that way. One turned on
    that takes no pointer cannot take the press, and nothing is pressed."""
    page = show(BUTTON + NO_POINTER)
    with pytest.raises(pressing.Covered):
        _click_off(page, 700)
    assert pressed(page) == []


def test_a_hidden_turned_off_control_stops_the_run_before_any_press(show):
    """One that does not show is no turned off control that shows. It is
    read before any press, and that it cannot be read stops the run."""
    page = show(OFF_BUTTON.replace('position: fixed;', 'position: fixed; display: none;'))
    with pytest.raises(pressing.Unread):
        _click_off(page, 8000)
    assert pressed(page) == []


def test_a_frame_raised_over_a_control_turned_on_late_stops_the_run(show):
    """A frame sits under the window's middle, behind the page. A control
    is pressed there first, and its look notes that frame. The next one is
    drawn turned off and taking no pointer, the first press has the page
    turn it on while Playwright waits, and its press raises the frame over it. The note the
    first look left is not taken for this control's, so the frame that came
    over it stops the run."""
    page = show(
        '<style>.spacer { height: 1200px; } .ctl { display: block; width: 200px; '
        'height: 40px; margin-left: 100px; } #F { position: fixed; left: 0; top: 0; '
        'width: 100vw; height: 100vh; z-index: -1; border: 0; } '
        '#b:disabled { pointer-events: none; }</style>'
        '<iframe id="F" srcdoc="<p>chat</p>"></iframe><div class="spacer"></div>'
        '<button id="a" class="ctl" type="button" onclick="said(\'a\'); setTimeout(() => { '
        'document.getElementById(\'b\').disabled = false; }, 1500)">Open</button>'
        '<div class="spacer"></div><button id="b" class="ctl" type="button" disabled '
        'onclick="said(\'b\'); document.getElementById(\'F\').style.zIndex = 1000">'
        'Download</button><div class="spacer"></div>')
    pressing.click(page, page.locator("#a"), css="button", what="the control a", words=WORDS)
    with pytest.raises(pressing.Covered):
        pressing.click(page, page.locator("#b"), css="button", what="the control b",
                       words=WORDS, timeout=4000)
    assert pressed(page) == ["a", "b"]


# --- A cover that passes before the press (click_when_clear, #221) ---------------

def in_page(page, js):
    """Run `js` in a world of the test's own in the page, which shares the
    page's elements, since the page's own eval is replaced."""
    session = page.context.new_cdp_session(page)
    try:
        frame = session.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        world = session.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": "test"})
        answer = session.send("Runtime.evaluate", {
            "expression": js, "contextId": world["executionContextId"]})
        assert not answer.get("exceptionDetails"), answer
    finally:
        session.detach()


class Steps:
    """The clock click_when_clear waits by, which moves only while it waits,
    and that wait, which does what the page does meanwhile, one step a wait,
    and never sleeps. Past 100 waits it fails, so a press that never stops
    trying fails rather than hangs."""

    def __init__(self, *during):
        self.during = list(during)
        self.t = 0.0
        self.calls = 0

    def clock(self):
        return self.t

    def wait(self, page, ms):
        self.calls += 1
        assert self.calls <= 100, "the press never stopped trying"
        self.t += ms / 1000.0
        if self.during:
            step = self.during.pop(0)
            step(page) if callable(step) else in_page(page, step)


def _when_clear(page, steps, locator="#go", find=None, **kw):
    loc = page.locator(locator)
    return pressing.click_when_clear(
        page, loc, find or (lambda: loc), css="button", what="the button", words=WORDS,
        clock=steps.clock, wait=steps.wait, **kw)


# A box over the button, gone once the run has waited once.
PASSING = BUTTON + ('<div class="cover" id="cover" style="right: 20px; bottom: 20px; '
                    'width: 200px; height: 60px;" onclick="said(\'cover\')"></div>')
GONE = "document.getElementById('cover').hidden = true"
# The yes or no facts a cover is said with, once it has been waited for.
ABOUT = ("over_it_holds_control", "control_clickable", "clip_at_point", "over_it_in_menu")


def test_a_control_with_nothing_on_top_is_pressed_once_and_not_waited_for(show):
    page = show(BUTTON)
    steps = Steps()
    assert _when_clear(page, steps) == {}
    assert pressed(page) == ["go"] and steps.calls == 0


def test_a_cover_that_passes_before_the_press_is_waited_for(show):
    page = show(PASSING)
    steps = Steps(GONE)
    said = _when_clear(page, steps)
    assert pressed(page) == ["go"]
    assert steps.calls == 1
    assert said["attempts"] == 2 and said["covered_ms"] == pressing.CLEAR_EVERY_MS
    assert said["cleared"] is True
    assert set(ABOUT) <= set(said), said


def test_a_cover_that_stays_stops_the_run_once_the_time_is_up(show):
    page = show(PASSING)
    steps = Steps()
    with pytest.raises(pressing.Covered) as stopped:
        _when_clear(page, steps)
    stop = stopped.value
    assert pressed(page) == []
    assert stop.after_a_press is False
    assert stop.reason == "something on the page is over the control"
    assert stop.lines[0] == "Something on the page covers the button, so nothing was pressed."
    facts = stop.facts
    assert facts["attempts"] >= 2 and facts["covered_ms"] >= pressing.CLEAR_MS, facts
    assert facts["cleared"] is False and "checked_again" not in facts
    assert set(ABOUT) <= set(facts), facts
    assert facts["over_it"]["tag"] == "div" and facts["fixed"] is True
    assert steps.calls == pressing.CLEAR_MS // pressing.CLEAR_EVERY_MS


def test_the_control_found_again_is_the_one_pressed(show):
    """While the cover passes the page draws the button again as a new
    element. The one found again is pressed, not the one first found."""
    page = show(PASSING.replace(' onclick="said(\'go\')"', ' data-say="go"')
                + '<script>document.addEventListener("click", (e) => {'
                  ' const b = e.target.closest("[data-say]"); if (b) said(b.dataset.say); });'
                  '</script>')
    steps = Steps(GONE + "; const old = document.getElementById('go');"
                         " const now = old.cloneNode(true); now.id = 'go2';"
                         " now.dataset.say = 'go2'; old.replaceWith(now)")
    _when_clear(page, steps, find=lambda: page.locator("#go2"))
    assert pressed(page) == ["go2"]


@pytest.mark.parametrize("how", ["not_found", "refused"])
def test_a_control_not_found_again_or_refused_by_the_check_is_not_pressed(show, how):
    page = show(PASSING)
    steps = Steps(GONE)
    checked = []

    def check(found):
        checked.append(found)
        return how != "refused"
    with pytest.raises(pressing.Covered) as stopped:
        _when_clear(page, steps, find=(lambda: None) if how == "not_found"
                    else (lambda: page.locator("#go")), check=check)
    assert pressed(page) == []
    facts = stopped.value.facts
    assert facts["checked_again"] is False and facts["cleared"] is False
    assert facts["attempts"] == 1
    assert len(checked) == (1 if how == "refused" else 0)


def test_the_check_runs_before_every_try_but_the_first(show):
    page = show(PASSING)
    steps = Steps("void 0", GONE)
    checked = []
    _when_clear(page, steps, check=lambda found: checked.append(found) or True)
    assert pressed(page) == ["go"] and len(checked) == 2 and steps.calls == 2


def test_a_frame_that_comes_over_the_control_as_it_is_pressed_is_not_tried_again(show):
    """Once the cover passed, a frame comes over the button as the pointer
    moves onto it, and Playwright's press goes to the frame. That stop came
    after a press, so nothing is tried again."""
    page = show(LATE % LATE_FRAME + '<div class="cover" id="cover" style="left: 380px; '
                'top: 230px; width: 200px; height: 80px"></div>')
    steps = Steps(GONE)
    with pytest.raises(pressing.Covered) as stopped:
        _when_clear(page, steps)
    stop = stopped.value
    assert stop.after_a_press is True and stop.facts["after_the_press"] is True
    assert steps.calls == 1
    assert pressed(page).count("frame-down") == 1 and "go" not in pressed(page)


def _raising(stop):
    calls = []

    def press(*args, **kwargs):
        calls.append(1)
        raise stop
    return press, calls


@pytest.mark.parametrize("stop", [
    pressing.NotPressed("press a control", "the press did not go through", ["x"],
                        after_a_press=True),
    pressing.Unread("press a control", "the control could not be checked", ["x"]),
    pressing.NoAnswer("press a control", "the press was made and the page did not answer",
                      ["x"], after_a_press=True),
    pressing.TurnedOff("press a control", "the control is turned off", ["x"],
                       after_a_press=True),
    pressing.Covered("press a control", "something on the page came over the control", ["x"],
                     after_a_press=True),
], ids=lambda s: type(s).__name__ + ("_after_a_press" if s.after_a_press else ""))
def test_only_a_cover_before_any_press_is_waited_for(monkeypatch, stop):
    press, calls = _raising(stop)
    monkeypatch.setattr(pressing, "_click", press)
    steps = Steps()
    with pytest.raises(pressing.Stop) as raised:
        pressing.click_when_clear(object(), object(), lambda: pytest.fail("found again"),
                                  css="button", what="the button", words=WORDS,
                                  clock=steps.clock, wait=steps.wait)
    assert raised.value is stop and calls == [1] and steps.calls == 0
    assert stop.facts == {}


def test_a_stop_on_a_later_try_says_how_long_it_was_waited_for(monkeypatch):
    covered = pressing.Covered("press a control", "something on the page is over the control",
                               ["x"], {"over_it": {}})
    then = pressing.NotPressed("press a control", "the press did not go through", ["x"],
                               {"error": "timeout"}, after_a_press=True)
    stops = [covered, then]
    calls = []

    def press(*args, **kwargs):
        calls.append(1)
        raise stops.pop(0)
    monkeypatch.setattr(pressing, "_click", press)
    steps = Steps()
    with pytest.raises(pressing.NotPressed) as raised:
        pressing.click_when_clear(object(), "first", lambda: "again", css="button",
                                  what="the button", words=WORDS,
                                  clock=steps.clock, wait=steps.wait)
    assert raised.value is then and calls == [1, 1] and steps.calls == 1
    assert then.facts == {"error": "timeout", "attempts": 2,
                          "covered_ms": pressing.CLEAR_EVERY_MS}


def test_a_plain_press_says_a_cover_as_it_always_did(show):
    """Only a press that waits for a cover says the yes or no facts, so
    every other press's stop is as it was."""
    page = show(PASSING)
    with pytest.raises(pressing.Covered) as stopped:
        pressing.click(page, page.locator("#go"), css="button", what="the button", words=WORDS)
    assert set(stopped.value.facts) == {"over_it", "topmost", "fixed"}


# A menu's panel under the button that opened it, holding the control, over
# a band of the page's own. Each page draws one of the ways a control can be
# covered, and the facts say which. Every word is made up.
MENU_PAGE = ('<div id="head" style="position: absolute; left: 0; top: 0; width: 900px">'
             '<button id="opener" aria-expanded="true" style="position: absolute; left: 10px; '
             'top: 10px; width: 120px; height: 30px">Accounts</button>%s'
             '<div id="panel" style="position: absolute; left: 0; top: 60px; width: 600px; '
             'height: 300px; background: #fff; z-index: 2; %s">'
             '<div id="entries" style="position: relative; width: 600px; height: 300px">'
             '<button id="go" style="position: absolute; left: 100px; top: 100px; width: 200px; '
             'height: 40px; %s" onclick="said(\'go\')">View Statements</button>%s</div></div></div>')
BAND_UNDER = ('<div id="band" style="position: absolute; left: 0; top: 60px; width: 900px; '
              'height: 500px; background: #eef; z-index: 1">Summary</div>')
ENTRY_OVER = ('<div id="entry" style="position: absolute; left: 80px; top: 90px; width: 300px; '
              'height: 60px; z-index: 3; background: #ddd">Summary</div>')

COVERS = {
    # The tester's shape. The panel takes no pointer, so the point finds
    # the band under it.
    "a panel that takes no pointer over a band": (
        MENU_PAGE % (BAND_UNDER, "pointer-events: none", "", ""),
        {"over_it_holds_control": False, "control_clickable": False, "clip_at_point": False,
         "over_it_in_menu": False}),
    # The panel cut away while it grows, so the point finds the band.
    "a panel cut away at the point": (
        MENU_PAGE % (BAND_UNDER, "clip-path: inset(0 0 100% 0)", "", ""),
        {"over_it_holds_control": False, "control_clickable": True, "clip_at_point": True,
         "over_it_in_menu": False}),
    # The control takes no pointer, so the point finds what holds it.
    "the panel on top of a control that takes no pointer": (
        MENU_PAGE % ("", "", "pointer-events: none", ""),
        {"over_it_holds_control": True, "control_clickable": False, "clip_at_point": False,
         "over_it_in_menu": True}),
    # Another entry of the menu drawn over the control.
    "another entry of the menu": (
        MENU_PAGE % ("", "", "", ENTRY_OVER),
        {"over_it_holds_control": False, "control_clickable": True, "clip_at_point": False,
         "over_it_in_menu": True}),
}


# The page's address is the test's name, so no id holds a space.
@pytest.mark.parametrize("shape", list(COVERS), ids=lambda shape: shape.replace(" ", "_"))
def test_a_cover_that_stays_is_said_in_yes_or_no(show, shape):
    body, said = COVERS[shape]
    page = show(body)
    steps = Steps()
    with pytest.raises(pressing.Covered) as stopped:
        _when_clear(page, steps, opener=page.locator("#opener"), limit_ms=250)
    facts = stopped.value.facts
    assert {k: facts.get(k) for k in ABOUT} == said, facts
    assert pressed(page) == []


def test_with_no_opener_whether_the_cover_is_in_its_menu_is_not_known(show):
    body, _ = COVERS["another entry of the menu"]
    page = show(body)
    with pytest.raises(pressing.Covered) as stopped:
        _when_clear(page, Steps(), limit_ms=250)
    assert stopped.value.facts["over_it_in_menu"] is None
    assert stopped.value.facts["over_it_holds_control"] is False
