"""A sign-in window comes to the front, and goes when its run is done.

They piled up: PaperPull never closed one, and each account's is an app of
its own on a Mac. Closing has to be certain which browser it is, so only a
process naming both the account's port and its own profile folder is
closed, never one whose folder only starts the same. A window the person
is in, signing in or reading a page of their own, looks like any other from
here, so one in front is left open, and so is every one where what is in
front cannot be told.
"""
import http.client
import io
import json

import pytest

from paperpull_core import browser

# The real one, before the autouse fixture in conftest.py stands it in for
# every test, so the tests of it here can put it back.
REAL_BRING_FORWARD = browser.bring_forward

# Only ever text in a pretend process list: these tests start no browser.
PORT_FLAG = "--remote-" + "debugging-port="


class Out:
    def __init__(self, stdout):
        self.stdout = stdout


def listing(monkeypatch, tmp_path, lines, front=1):
    """A Mac whose process list is `lines`, with the process `front` in
    front, or nothing lsappinfo can say when it is None."""
    monkeypatch.setattr(browser.sys, "platform", "darwin")

    def run(cmd, **k):
        if cmd[0] == "ps":
            return Out("\n".join(lines))
        if front is None:
            raise OSError("no lsappinfo")
        if cmd[:2] == ["lsappinfo", "front"]:
            return Out("ASN:0x0-0x1:")
        return Out('"pid"=%d' % front)
    monkeypatch.setattr(browser.subprocess, "run", run)
    killed = []
    monkeypatch.setattr(browser.os, "kill", lambda pid, sig: killed.append(pid))
    return killed


def chrome(profile, port, pid=4242, extra=""):
    return f"{pid} /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile} {PORT_FLAG}{port} --no-first-run {extra}"


def test_only_this_accounts_browser_is_closed(monkeypatch, tmp_path):
    mine = tmp_path / "Chase" / "browser-profile"
    killed = listing(monkeypatch, tmp_path, [
        "100 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        chrome(tmp_path / "Amex" / "browser-profile", 9236, pid=200),
        chrome(mine, 9999, pid=300),
        chrome(mine, 9236, pid=4242),
        chrome(mine, 9236, pid=500, extra="--type=renderer"),
    ])
    assert browser.close_signin_browser(mine, 9236) == {"closed": True, "in_use": False}
    assert killed == [4242]


def test_an_everyday_browser_is_never_closed(monkeypatch, tmp_path):
    killed = listing(monkeypatch, tmp_path, ["100 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --flag"])
    assert browser.close_signin_browser(tmp_path / "p", 9236) == {"closed": False, "in_use": False}
    assert killed == []


def test_a_port_that_only_starts_the_same_is_not_this_one(monkeypatch, tmp_path):
    mine = tmp_path / "p"
    killed = listing(monkeypatch, tmp_path, [chrome(mine, 92360)])
    assert browser.close_signin_browser(mine, 9236)["closed"] is False and killed == []


@pytest.mark.parametrize("other", ["browser-profile2", "browser-profile-2", "browser-profile-spouse", "browser-profile copy"])
def test_a_profile_that_only_starts_the_same_is_not_this_one(monkeypatch, tmp_path, other):
    """Another account's window on the same port, a second person's whose
    folder name starts with this one's, is never closed for this one."""
    killed = listing(monkeypatch, tmp_path, [chrome(tmp_path / other, 9236)])
    assert browser.close_signin_browser(tmp_path / "browser-profile", 9236)["closed"] is False
    assert killed == []


def test_a_window_of_a_fallback_browser_is_still_its_own(monkeypatch, tmp_path):
    """_try_each opens a browser it falls back to on a profile folder named
    after the account's own, and that window is closed like the first."""
    mine = tmp_path / "browser-profile"
    tried = []
    monkeypatch.setattr(browser, "_launch", lambda exe, name, target, *a, **k: tried.append(target))
    browser._try_each([(browser.CHROMIUM, "c"), (browser.CHROME, "g"), (browser.EDGE, "e")], mine, "9236", "about:blank")
    assert len(tried) == 3
    for target in tried[1:]:
        killed = listing(monkeypatch, tmp_path, [chrome(target, 9236)])
        assert browser.close_signin_browser(mine, 9236)["closed"] is True and killed == [4242]


def test_a_window_somebody_is_in_is_left_open(monkeypatch, tmp_path):
    """The person is signing in there, or reading a page of their own, so
    the window stays and the panel says why."""
    mine = tmp_path / "p"
    killed = listing(monkeypatch, tmp_path, [chrome(mine, 9236, pid=77)], front=77)
    assert browser.close_signin_browser(mine, 9236) == {"closed": False, "in_use": True}
    assert killed == []


def test_a_window_is_left_open_when_what_is_in_front_cannot_be_told(monkeypatch, tmp_path):
    mine = tmp_path / "p"
    killed = listing(monkeypatch, tmp_path, [chrome(mine, 9236, pid=77)], front=None)
    assert browser.close_signin_browser(mine, 9236) == {"closed": False, "in_use": False}
    assert killed == []


def test_nothing_is_in_front_anywhere_but_a_mac(monkeypatch):
    for system in ("linux", "win32"):
        monkeypatch.setattr(browser.sys, "platform", system)
        assert browser.frontmost_pid() is None


def test_windows_closes_nothing_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.sys, "platform", "win32")
    assert browser.signin_browser_pid(tmp_path, 9236) is None


def test_a_browser_that_cannot_be_reached_is_no_error(monkeypatch):
    def nope(*a, **k):
        raise OSError("refused")
    monkeypatch.setattr(browser, "bring_forward", REAL_BRING_FORWARD)
    monkeypatch.setattr(browser, "open_local", nope)
    assert browser.bring_forward(9236) is False


@pytest.mark.parametrize("trouble", [http.client.BadStatusLine("x"), http.client.IncompleteRead(b""), KeyError("id")])
def test_a_browser_that_answers_badly_is_no_error(monkeypatch, trouble):
    """A browser closed while it answers, or anything else on its port, never
    ends the sign-in that has just opened the window."""
    def badly(*a, **k):
        raise trouble
    monkeypatch.setattr(browser, "bring_forward", REAL_BRING_FORWARD)
    monkeypatch.setattr(browser, "open_local", badly)
    assert browser.bring_forward(9236) is False


def test_the_first_page_is_the_one_shown(monkeypatch):
    asked = []

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def answer(request, timeout):
        asked.append(request.full_url)
        return Answer(json.dumps([{"type": "iframe", "id": "F"}, {"type": "page", "id": "A"},
                                  {"type": "page", "id": "B"}]).encode())
    monkeypatch.setattr(browser, "bring_forward", REAL_BRING_FORWARD)
    monkeypatch.setattr(browser, "open_local", answer)
    assert browser.bring_forward(9236) is True
    assert asked == ["http://127.0.0.1:9236/json/list", "http://127.0.0.1:9236/json/activate/A"]


def test_no_test_brings_a_real_browser_forward(monkeypatch, tmp_path):
    """A sign-in on a port a browser holds brings that browser forward. In a
    test the port can be one a developer's own signed-in browser holds, as
    conftest.py says, so the request never leaves for it."""
    asked = []
    monkeypatch.setattr(browser, "open_local", lambda request, timeout: asked.append(request) or (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(browser, "debug_port_holder", lambda port, timeout=1.5: "Chrome/1")
    assert browser.open_signin_browser(tmp_path / "p", "9222", "about:blank") == browser.ALREADY_ON_PORT
    assert asked == []
