"""Target is the one app that drives a browser itself rather than
attaching to one, and it used to insist on Playwright's own Chromium.

On the packaged Mac build there is no bundled copy, so Login failed there
while every other provider worked, which is what #48 reported. These hold
the app to using an installed browser when the bundled one is absent, and
to leaving a working setup alone when it is present.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts


SRC = inspect.getsource(target_receipts.App.browser)


def test_an_installed_browser_is_used_when_there_is_no_bundled_one():
    assert "find_browser(prefer_real=True)" in SRC
    assert "executable_path" in SRC, "the installed browser has to be handed to Playwright"


def test_the_bundled_copy_still_wins_when_it_is_already_there():
    """Somebody whose Target app works today keeps the browser it works
    with. The search only happens when there is no bundled copy."""
    before, _, after = SRC.partition("if not browser_launcher.bundled_chromium_present():")
    assert after, "the bundled check still guards the search"
    assert "find_browser" not in before, "nothing looks for another browser first"
    assert "executable_path" not in before


def test_the_download_is_still_offered_when_there_is_no_browser_at_all():
    assert "fetch_bundled_chromium()" in SRC
    assert "SystemExit" in SRC


def test_the_dead_end_message_is_gone():
    """It said the app needs its own copy of Chromium, which was true and
    is the thing that changed."""
    assert "needs its own copy of Chromium" not in SRC


# -- the next wall the browser fix revealed (#48) -----------------------------

LOGIN = inspect.getsource(target_receipts.App.cmd_login)
SESSION = inspect.getsource(target_receipts.App.check_session)


# -- and the window still closed, because it was never ours to keep (#48) ----

OPEN = inspect.getsource(target_receipts.App.cmd_open_browser)
BROWSER = inspect.getsource(target_receipts.App.browser)


def test_the_sign_in_window_is_not_a_child_of_this_process():
    """The first repair stopped the crash and the window still vanished.
    A browser Playwright launches is a child of the process that launched
    it, so nothing done inside a command that is about to return can keep
    it alive. It is started as its own process now, the way the other
    forty-seven apps do it."""
    assert "open_signin_browser" in OPEN
    assert "launch_persistent_context" not in OPEN


def test_the_app_attaches_to_the_window_you_signed_into():
    assert "connect_over_cdp" in BROWSER
    before, _, _after = BROWSER.partition("connect_over_cdp")
    assert "cdp_url" in before, "attaching is what it tries first"


def test_an_install_made_before_this_still_works():
    """Nobody's setup changes under them. With no cdp_url it launches
    here, exactly as it did."""
    assert "launch_persistent_context" in BROWSER
    assert "No cdp_url" in BROWSER or "no cdp_url" in BROWSER.lower()


def test_the_panel_knows_which_flag_to_send():
    """The panel reads the script for the literal flag and sends that
    from its Login button, so declaring it only through the modes table
    would have left Login opening nothing."""
    src = inspect.getsource(target_receipts)
    assert '"--open-browser"' in src


def test_login_does_not_wait_at_a_prompt_nobody_can_answer():
    """On 0.32.0 the window opened and shut again. The browser fix worked
    and the app then asked "Press Enter here AFTER you have finished
    signing in", read end-of-file, and exited 3 with the window still
    open behind it."""
    assert "pause_for_sign_in()" in LOGIN
    assert "ask(" not in LOGIN, "no prompt is left in Login"


def test_closing_the_connection_is_not_closing_the_window():
    """This used to promise it left the browser open, which it could not
    keep, because the browser was its own child. Now the window is a
    separate process and closing the connection to it is just letting go
    of the handle."""
    assert "self.close()" in LOGIN
    assert "connect_over_cdp" in BROWSER, "what close() lets go of is an attachment"


def test_the_old_path_still_does_not_wait_where_nobody_can_answer():
    before, _, after = LOGIN.partition("pause_for_sign_in()")
    assert before, "the launch-here path is still there for an older install"
    assert "return" in " ".join(after.strip().splitlines()[:2])


def test_a_run_that_meets_a_challenge_stops_instead_of_dying():
    assert "ask_or_none(" in SESSION
    assert "raise SystemExit(0)" in SESSION, "a clean stop, not a crash"
    assert "press Resume" in SESSION
    assert SESSION.count("ask_or_none(") == 2, "the challenge and the sign-out both"


def test_the_confirmations_that_should_still_refuse_are_untouched():
    """A prompt that guards something destructive must keep refusing when
    there is nobody to answer it."""
    src = inspect.getsource(target_receipts)
    assert 'if ask("> ").strip().upper() != "YES"' in src
