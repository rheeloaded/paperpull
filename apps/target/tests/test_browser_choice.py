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


def test_login_does_not_wait_at_a_prompt_nobody_can_answer():
    """On 0.32.0 the window opened and shut again. The browser fix worked
    and the app then asked "Press Enter here AFTER you have finished
    signing in", read end-of-file, and exited 3 with the window still
    open behind it."""
    assert "pause_for_sign_in()" in LOGIN
    assert "ask(" not in LOGIN, "no prompt is left in Login"


def test_login_leaves_the_browser_open_when_it_could_not_ask():
    """Closing it is what made the window vanish, and it is the window
    the person was about to sign in to."""
    before, _, after = LOGIN.partition("pause_for_sign_in()")
    assert "self.close()" not in before
    next_two = " ".join(after.strip().splitlines()[:2])
    assert "return" in next_two, "it returns before anything is checked or closed"


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
