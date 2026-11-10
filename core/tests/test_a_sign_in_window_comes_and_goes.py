"""A sign-in window comes to the front, and goes when its run is done.

They piled up: PaperPull never closed one, and each account's is an app of
its own on a Mac. Closing has to be certain which browser it is, so only a
process naming both the account's port and its profile folder is closed.
"""
import subprocess
import pytest

from paperpull_core import browser


# Only ever text in a pretend process list: these tests start no browser.
PORT_FLAG = "--remote-" + "debugging-port="


class Out:
    def __init__(self, stdout):
        self.stdout = stdout


def listing(monkeypatch, tmp_path, lines):
    monkeypatch.setattr(browser.sys, "platform", "darwin")

    def run(cmd, **k):
        if cmd[0] == "ps":
            return Out("\n".join(lines))
        if cmd[:2] == ["lsappinfo", "front"]:
            return Out("ASN:0x0-0x1:")
        return Out('"pid"=4242')
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
    assert browser.close_signin_browser(mine, 9236) == {"closed": True, "was_front": True}
    assert killed == [4242]


def test_an_everyday_browser_is_never_closed(monkeypatch, tmp_path):
    killed = listing(monkeypatch, tmp_path, ["100 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --flag"])
    assert browser.close_signin_browser(tmp_path / "p", 9236) == {"closed": False, "was_front": False}
    assert killed == []


def test_a_port_that_only_starts_the_same_is_not_this_one(monkeypatch, tmp_path):
    mine = tmp_path / "p"
    killed = listing(monkeypatch, tmp_path, [chrome(mine, 92360)])
    assert browser.close_signin_browser(mine, 9236)["closed"] is False and killed == []


def test_somebody_gone_elsewhere_is_said_to_have(monkeypatch, tmp_path):
    mine = tmp_path / "p"
    listing(monkeypatch, tmp_path, [chrome(mine, 9236, pid=77)])
    assert browser.close_signin_browser(mine, 9236) == {"closed": True, "was_front": False}


def test_windows_closes_nothing_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.sys, "platform", "win32")
    assert browser.signin_browser_pid(tmp_path, 9236) is None


def test_a_browser_that_cannot_be_reached_is_no_error(monkeypatch):
    def nope(*a, **k):
        raise OSError("refused")
    monkeypatch.setattr(browser, "open_local", nope)
    assert browser.bring_forward(9236) is False
