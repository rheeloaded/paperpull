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
