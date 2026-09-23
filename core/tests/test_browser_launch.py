"""Launching the sign-in browser, when the launch does not work.

_launch answers with a browser name or None, and _try_each moves on to the
next candidate when it gets None. A launch that raises instead ends the
whole sign-in step with a traceback while another browser sits there ready.

The executable is checked for before any of this, so a failure at the
launch itself is the interesting kind: security software holding an
unsigned binary, a permission, an update swapping the file out underneath.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser  # noqa: E402


@pytest.fixture
def no_waiting(monkeypatch):
    """The port never answers, so every launch is a failed one unless a
    test says otherwise."""
    monkeypatch.setattr(browser, "wait_for_debug_port", lambda port, timeout=20.0: False)


def test_a_browser_that_will_not_start_is_not_a_traceback(monkeypatch, tmp_path, no_waiting):
    def blocked(*_a, **_k):
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(browser.subprocess, "Popen", blocked)

    assert browser._launch("C:/nope/edge.exe", browser.EDGE, tmp_path / "p",
                           "9222", "https://bank.example/") is None


def test_the_next_browser_is_tried_when_one_will_not_start(monkeypatch, tmp_path):
    """The point of answering None rather than raising."""
    tried = []

    def popen(cmd, **_k):
        tried.append(cmd[0])
        if cmd[0].endswith("edge.exe"):
            raise OSError(13, "Permission denied")
        return None
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0: True)

    opened = browser._try_each([(browser.EDGE, "C:/x/edge.exe"),
                                (browser.CHROME, "C:/x/chrome.exe")],
                               tmp_path / "profile", "9222", "https://bank.example/")
    assert opened == browser.CHROME
    assert tried == ["C:/x/edge.exe", "C:/x/chrome.exe"]


def test_nothing_starting_at_all_is_still_not_a_traceback(monkeypatch, tmp_path, no_waiting):
    def blocked(*_a, **_k):
        raise OSError(2, "No such file or directory")
    monkeypatch.setattr(browser.subprocess, "Popen", blocked)

    assert browser._try_each([(browser.EDGE, "C:/x/edge.exe"),
                              (browser.CHROME, "C:/x/chrome.exe")],
                             tmp_path / "profile", "9222", "https://bank.example/") is None


def test_the_profile_is_an_absolute_path_before_the_browser_sees_it(monkeypatch, tmp_path, no_waiting):
    """A relative --user-data-dir is resolved by the browser, from wherever
    it thinks it is, which once made two profiles out of one setting and
    left signed-in cookies in the shared browser cache."""
    seen = {}

    def popen(cmd, **_k):
        seen["args"] = cmd
        return None
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.chdir(tmp_path)

    browser._launch("edge.exe", browser.EDGE, Path("./rel-profile"), "9222",
                    "https://bank.example/")
    arg = [a for a in seen["args"] if a.startswith("--user-data-dir=")][0]
    given = Path(arg.split("=", 1)[1])
    assert given.is_absolute()
    assert given == (tmp_path / "rel-profile").resolve()


def test_the_port_and_url_reach_the_browser(monkeypatch, tmp_path, no_waiting):
    seen = {}
    monkeypatch.setattr(browser.subprocess, "Popen",
                        lambda cmd, **_k: seen.setdefault("args", cmd))
    browser._launch("edge.exe", browser.EDGE, tmp_path / "p", "9231",
                    "https://bank.example/signin")
    assert "--remote-debugging-port=9231" in seen["args"]
    assert seen["args"][-1] == "https://bank.example/signin"


def test_a_port_that_is_not_a_number_is_not_waited_on():
    assert browser.wait_for_debug_port("not-a-port", timeout=0.1) is False
    assert browser.wait_for_debug_port(None, timeout=0.1) is False
