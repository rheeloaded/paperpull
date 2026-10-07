"""paperpull_core.pressing.press_once in a real browser, on pages made for it.

press_once makes Playwright's own unforced press, and only when that raised
and it is safe, the element's own click through the page, once. Twelve
apps pressed through the page whenever Playwright's press raised, under a
cover, on a hidden control, and a second time after a press that had
landed. Each test here holds one of press_once's checks to one page, and
each check has a test that fails with that check taken out, so none
passes on another's account.

Where Playwright's press has to raise in a way a page cannot make it raise
on its own, the press is replaced by one that raises the way Playwright
does for a control that never holds still, after doing what the test
names. Every word on these pages is made up.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paperpull_core import pressing
from paperpull_core.words import words_for

sync_api = pytest.importorskip("playwright.sync_api")

WORDS = words_for("Example Bank")
# Playwright's time for its press here. Long enough for it to press a
# control that takes the press on a busy machine, short enough that a cover
# costs little.
TIMEOUT = 2000

HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>made up</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style>
<script>window.presses = 0; window.coverPresses = 0;</script>
</head><body><div style="height: 200px"></div>
"""

# What Playwright says when a press timed out before it began, for a
# control that never held still.
NOT_MADE = ('Locator.click: Timeout 2000ms exceeded.\nCall log:\n'
            '  - waiting for locator("#go")\n'
            '    - locator resolved to <button id="go">Download statement</button>\n'
            '  - attempting click action\n'
            '    2 × waiting for element to be visible, enabled and stable\n'
            '      - element is not stable\n')


def guard(words: str) -> bool:
    """A stand-in for an app's guard, refusing any control that says pay."""
    return "pay" not in words.lower()


class _Site:
    """One test's own site, its pages, a statement, and an address whose
    answer is held until the test lets it go."""

    def __init__(self):
        self.pages = {}
        self.let_go = threading.Event()
        self.httpd = None


def _handler(site):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            path = self.path.split("?")[0].lstrip("/")
            if path == "hold":
                site.let_go.wait(20)
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = site.pages.get(path, "").encode("utf-8")
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def show(browser):
    """A page of this test's own, on a site of its own, so an answer held
    for one test never reaches another."""
    site = _Site()
    site.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(site))
    threading.Thread(target=site.httpd.serve_forever, daemon=True).start()
    address = "http://127.0.0.1:%d/" % site.httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 600})

    def open_page(body):
        site.pages["page"] = HEAD + body + "</body></html>"
        site.pages["other"] = HEAD + "<p>Another page</p></body></html>"
        page = context.new_page()
        page.goto(address + "page")
        page.site = site
        page.address = address
        return page

    yield open_page
    site.let_go.set()
    context.close()
    site.httpd.shutdown()
    site.httpd.server_close()


def presses(page) -> int:
    return page.evaluate("window.presses")


def press(page, el=None, **given):
    args = dict(what="the control for this statement", words=WORDS, guard=guard,
                timeout=TIMEOUT)
    args.update(given)
    return pressing.press_once(page, el if el is not None else page.locator("#go"), **args)


BUTTON = '<button id="go" type="button" onclick="window.presses++;%s">Download statement</button>'
COVER = '<div class="cover" onclick="window.coverPresses++">Chat with us</div>'


@pytest.fixture()
def unstable(monkeypatch):
    """Playwright's press, replaced by one that does `first` and then raises
    the way Playwright does for a control that never held still, so it was
    never made."""
    def install(first=None):
        def click(self, *args, **kwargs):
            if first is not None:
                first(self)
            raise sync_api.TimeoutError(NOT_MADE)
        monkeypatch.setattr(sync_api.Locator, "click", click)
        monkeypatch.setattr(sync_api.ElementHandle, "click", click)
    return install


# --- Playwright's own press ---------------------------------------------------

def test_a_control_that_takes_the_press_is_pressed_once_by_playwright(show):
    page = show(BUTTON % "")
    got = press(page)
    assert got.how == pressing.PRESSED and got.error is None
    assert presses(page) == 1


# --- 1. What Playwright says of a press that raised -----------------------------

def test_a_covered_control_is_not_pressed_at_all_and_the_run_stops(show):
    """Playwright says something intercepts its press, and the cover is still
    there, so nothing is pressed, the cover least of all."""
    page = show(BUTTON % "" + COVER)
    with pytest.raises(pressing.Covered) as stop:
        press(page)
    assert presses(page) == 0 and page.evaluate("window.coverPresses") == 0
    assert stop.value.after_a_press


def test_a_cover_gone_before_the_control_is_read_still_stops_the_run(show, monkeypatch):
    """Playwright said something intercepted its press, and by the time the
    control is read again the cover has gone. Playwright's word alone stops
    the run. Without it the control would read as clear and be pressed
    through the page, after a press that met a cover."""
    page = show(BUTTON % "" + COVER)
    real = pressing.look

    def cover_gone(page_, locator, css, labels=False):
        page_.evaluate("document.querySelector('.cover').remove()")
        return real(page_, locator, css, labels)
    monkeypatch.setattr(pressing, "look", cover_gone)
    with pytest.raises(pressing.Covered) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["verdict"] == "covered"


def test_a_press_that_landed_and_raised_before_playwright_said_so_is_not_made_again(show):
    """The control's own handler is still running when Playwright's time runs
    out, so its account stops at performing the press. The press had landed.
    Whether it did cannot be told from that account, so the run stops and
    nothing is pressed again."""
    page = show(BUTTON % " const t = Date.now(); while (Date.now() - t < 4000) {}")
    with pytest.raises(pressing.Unsure) as stop:
        press(page)
    assert presses(page) == 1
    assert stop.value.facts["verdict"] == "unsure" and stop.value.after_a_press


def test_a_press_playwright_says_was_done_is_not_made_again(show, monkeypatch):
    """The press starts a load the site answers late, so Playwright's press
    times out after it says the press was done. Nothing is pressed again and
    the run goes on to wait for what the press brings. The load is let go
    once press_once has answered."""
    page = show(BUTTON % " location.href = '/hold';")
    real = pressing.press_once

    def answered(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        finally:
            page.site.let_go.set()
    monkeypatch.setattr(pressing, "press_once", answered)
    got = pressing.press_once(page, page.locator("#go"), what="the control for this statement",
                              words=WORDS, guard=guard, timeout=TIMEOUT)
    assert got.how == pressing.MADE and got.page_error is None
    assert "click action done" in str(got.error)
    page.wait_for_load_state()
    assert presses(page) == 1


def test_a_press_playwright_says_was_done_is_never_made_again_whatever_else_shows(
        show, monkeypatch):
    """Playwright's account says the press was done, and nothing else shows
    it, no load, no tab and nothing heard, since the page stops every press
    at the window before anything of the control's hears it. Its account
    alone keeps the press from being made a second time."""
    page = show(BUTTON % "" + """<script>
      window.addEventListener('click', (e) => {
        if (e.target.id === 'go') { window.presses++; e.stopImmediatePropagation(); }
      }, true);
      for (const kind of ['pointerdown', 'mousedown', 'pointerup', 'mouseup'])
        window.addEventListener(kind, (e) => e.stopImmediatePropagation(), true);
    </script>""".replace('onclick="window.presses++;"', ""))
    real = sync_api.Locator.click

    def done(self, *args, **kwargs):
        real(self, *args, **kwargs)
        raise sync_api.TimeoutError(NOT_MADE + "    - performing click action\n"
                                    "    - click action done\n"
                                    "    - waiting for scheduled navigations to finish\n")
    monkeypatch.setattr(sync_api.Locator, "click", done)
    got = press(page)
    assert got.how == pressing.MADE
    assert presses(page) == 1


def test_a_control_the_page_turned_off_is_not_pressed_through_the_page(show):
    """aria-disabled, which Playwright waits on until its time runs out. The
    page said the control does not take a press, so it is not pressed
    through the page either, where nothing would have stopped the click."""
    page = show((BUTTON % "").replace('type="button"', 'type="button" aria-disabled="true"'))
    with pytest.raises(pressing.NotPressed) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["verdict"] == "off"


def test_a_press_that_raised_with_no_account_of_itself_is_not_made_again(show, monkeypatch):
    """An error that is not Playwright's account of a press, the browser gone
    say. Nothing says the press was not made."""
    page = show(BUTTON % "")

    def gone(self, *args, **kwargs):
        raise sync_api.Error("Target page, context or browser has been closed")
    monkeypatch.setattr(sync_api.Locator, "click", gone)
    with pytest.raises(pressing.Unsure):
        press(page)
    assert presses(page) == 0


# --- 2. What a press brings -----------------------------------------------------

def test_a_tab_that_opened_as_the_press_raised_is_taken_for_the_press(show, unstable):
    """A new tab opened while Playwright's press was raising, as a press can
    open one. That is taken for the press, which is not made again."""
    page = show(BUTTON % "")
    unstable(lambda _el: page.evaluate("u => { window.open(u); }", page.address + "other"))
    got = press(page)
    assert got.how == pressing.MADE
    assert presses(page) == 0


def test_what_the_app_says_came_is_taken_for_the_press(show, unstable):
    """The app's own word that something the press brings came, a PDF the
    capture heard say."""
    page = show(BUTTON % "")
    unstable()
    got = press(page, brought=lambda: True)
    assert got.how == pressing.MADE
    assert presses(page) == 0


def test_a_file_that_came_into_the_download_folder_is_taken_for_the_press(show, unstable,
                                                                          tmp_path):
    page = show(BUTTON % "")
    unstable(lambda _el: (tmp_path / "statement.pdf.crdownload").write_bytes(b"%PDF-"))
    got = press(page, dl_dir=tmp_path)
    assert got.how == pressing.MADE
    assert presses(page) == 0


def test_a_load_the_press_began_is_taken_for_the_press(show, unstable):
    """The tab began loading something new while the press raised, a load
    the site holds. Nothing in the page is read while it loads, since
    Playwright answers no read of a loading tab, and the press is not made
    again."""
    page = show(BUTTON % "")
    unstable(lambda _el: page.evaluate("() => { setTimeout(() => { location.href = '/hold'; }, 0); }")
             or page.wait_for_timeout(300))
    got = press(page)
    page.site.let_go.set()
    assert got.how == pressing.MADE
    page.wait_for_load_state()
    assert presses(page) == 0


def test_a_tab_moved_to_another_address_is_taken_for_the_press(show, unstable):
    """The page changed its address in place, the way a page of one script
    shows another view."""
    page = show(BUTTON % "")
    unstable(lambda _el: page.evaluate("() => history.pushState({}, '', '/statements/2026')"))
    got = press(page)
    assert got.how == pressing.MADE
    assert presses(page) == 0


# --- 3. Whether the control heard a press ---------------------------------------

def test_a_press_the_control_heard_is_not_made_again(show, unstable):
    """A press the browser itself sent reached the control while
    Playwright's press was raising, the person's own say. Nothing else
    shows it, and it is never made a second time."""
    page = show(BUTTON % "")

    def person_presses(_el):
        box = page.locator("#go").bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    unstable(person_presses)
    got = press(page)
    assert got.how == pressing.MADE
    assert presses(page) == 1


def test_a_control_that_could_not_be_listened_to_is_not_pressed_through_the_page(
        show, unstable, monkeypatch):
    """When the page could not be asked to listen before the press, nothing
    could hear a press that reached it."""
    page = show(BUTTON % "")
    monkeypatch.setattr(pressing, "_HEAR_JS", "(el, word) => { throw new Error('no'); }")
    unstable()
    with pytest.raises(pressing.Unsure) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["verdict"] == "unheard"


# --- 4. The app's own guard and check -------------------------------------------

def test_a_control_whose_words_the_guard_refuses_is_not_pressed_through_the_page(show, unstable):
    """Every word the control carries goes through the app's guard, its
    title too, which Playwright's press never read."""
    page = show((BUTTON % "").replace('type="button"', 'type="button" title="Pay now"'))
    unstable()
    with pytest.raises(pressing.Changed) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["why"] == "the guard refuses its words"


def test_the_apps_own_check_keeps_the_control_from_being_pressed_through_the_page(
        show, unstable):
    page = show(BUTTON % "")
    unstable()
    with pytest.raises(pressing.Changed) as stop:
        press(page, check=lambda: "its row has another date")
    assert presses(page) == 0
    assert stop.value.facts["why"] == "the app's check"


# --- 5. On top, in the middle of the window -------------------------------------

def test_a_covered_control_playwright_did_not_name_is_not_pressed_through_the_page(
        show, unstable):
    """Playwright's press raised for another reason, and a cover sits over
    the control. Read the way click reads it, it is covered."""
    page = show(BUTTON % "" + COVER)
    unstable()
    with pytest.raises(pressing.Covered) as stop:
        press(page)
    assert presses(page) == 0 and page.evaluate("window.coverPresses") == 0
    assert stop.value.after_a_press


def test_a_hidden_control_is_not_pressed_through_the_page(show):
    """Playwright waits for it to show until its time runs out. Through the
    page a hidden control takes a click like any other."""
    page = show((BUTTON % "").replace('type="button"', 'type="button" style="display: none"'))
    with pytest.raises(pressing.Unread):
        press(page)
    assert presses(page) == 0


# --- 6. Pressed through the page, once -------------------------------------------

def test_a_control_whose_words_change_as_it_is_pressed_is_not_pressed(show, unstable,
                                                                       monkeypatch):
    """Its words are read in the same step as the press, and they changed
    right after it was read as on top."""
    page = show(BUTTON % "")
    real = pressing.look

    def renamed(page_, locator, css, labels=False):
        seen = real(page_, locator, css, labels)
        page_.evaluate("document.getElementById('go').textContent = 'Pay this bill'")
        return seen
    monkeypatch.setattr(pressing, "look", renamed)
    unstable()
    with pytest.raises(pressing.Changed) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["why"] == "its words changed"


def test_a_control_that_left_the_page_as_it_was_pressed_is_not_pressed(show, unstable,
                                                                        monkeypatch):
    """The page took the control away right after it was read as on top. A
    click through the page still reaches an element the page let go of, and
    its handler still runs."""
    page = show(BUTTON % "")
    real = pressing.look

    def taken_away(page_, locator, css, labels=False):
        seen = real(page_, locator, css, labels)
        page_.evaluate("window.held = document.getElementById('go'); window.held.remove()")
        return seen
    monkeypatch.setattr(pressing, "look", taken_away)
    unstable()
    with pytest.raises(pressing.Changed) as stop:
        press(page)
    assert presses(page) == 0
    assert stop.value.facts["why"] == "it left the page"


def test_the_control_pressed_through_the_page_is_the_one_playwright_was_given(show, unstable):
    """A list drawn anew while Playwright's press raised, another row's
    control now first. The locator would find that one. The element it
    found when the press began is the one read and pressed."""
    page = show(BUTTON % "" + '<script>window.otherPresses = 0;</script>')

    def another_row_first(_el):
        page.evaluate("""() => {
          const b = document.createElement('button');
          b.type = 'button';
          b.textContent = 'Download statement';
          b.onclick = () => { window.otherPresses++; };
          document.body.insertBefore(b, document.getElementById('go'));
        }""")
    unstable(another_row_first)
    got = press(page, el=page.locator("button").first)
    assert got.how == pressing.THROUGH_THE_PAGE
    assert presses(page) == 1 and page.evaluate("window.otherPresses") == 0


def test_a_control_that_passes_every_check_is_pressed_through_the_page_once(show, unstable):
    page = show(BUTTON % "")
    unstable()
    got = press(page)
    assert got.how == pressing.THROUGH_THE_PAGE and got.page_error is None
    assert presses(page) == 1


def test_an_element_handle_is_read_and_pressed_as_itself(show, unstable):
    """An app that holds the element itself, as several do, gets the same
    checks and the same one press."""
    page = show(BUTTON % "")
    unstable()
    got = press(page, el=page.query_selector("#go"))
    assert got.how == pressing.THROUGH_THE_PAGE
    assert presses(page) == 1


def test_playwrights_word_is_read_from_its_account_alone():
    """The phrases press_once reads, and that nothing else counts. Page
    text in the account can only ever make it press less."""
    word = pressing.playwrights_word
    assert word(NOT_MADE) == "not made"
    assert word(NOT_MADE + "    - performing click action\n") == "unsure"
    assert word(NOT_MADE + "    - performing click action\n    - click action done\n") == "made"
    assert word(NOT_MADE + '      - <div id="c">Chat</div> intercepts pointer events\n') == "covered"
    assert word(NOT_MADE.replace("element is not stable", "element is not enabled")) == "off"
    assert word("Target page, context or browser has been closed") == "unsure"
    assert word(None) == "unsure"
