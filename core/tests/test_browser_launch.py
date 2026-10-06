"""Launching the sign-in browser, when the launch does not work.

_launch answers with a browser name or None, and _try_each moves on to the
next candidate when it gets None. A launch that raises instead ends the
whole sign-in step with a traceback while another browser sits there ready.

The executable is checked for before any of this, so a failure at the
launch itself is the interesting kind: security software holding an
unsigned binary, a permission, an update swapping the file out underneath.
"""
import os
import socket
import subprocess
import sys
import time
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


# -- a bundled Chromium that closes as soon as it starts ----------------------
#
# On Ubuntu 23.10 and later AppArmor keeps a downloaded Chrome for Testing,
# which is what Playwright downloads, from the user namespaces its sandbox
# needs. It writes a FATAL line saying it has no usable sandbox and ends at
# once. Login used to wait twenty seconds and then say a window had opened
# and to close other copies of the browser, though no window had opened and
# no other copy was the trouble. Only the words "No usable sandbox", which
# Playwright's own driver looks for in a failed start, are relied on here.

SANDBOX_REFUSED = (
    "[4242:4242:1006/101010.123456:FATAL:zygote_host_impl_linux.cc(132)] No usable "
    "sandbox! Update your kernel or see https://chromium.googlesource.com/chromium/"
    "src/+/main/docs/linux/suid_sandbox_development.md for more information on "
    "developing with the SUID sandbox.\n")


class _Ended:
    """Stands in for subprocess.Popen. The browser it starts writes what it
    was given to the stderr it was handed and has ended by the first look, as
    Chromium does when it cannot start its sandbox."""

    def __init__(self, says=""):
        self.says = says
        self.handed = []

    def __call__(self, cmd, stderr=None, **_kw):
        self.handed.append((cmd[0], stderr))
        if self.says and hasattr(stderr, "write"):
            stderr.write(self.says.encode("utf-8"))
            stderr.flush()
        return self

    def poll(self):
        return 1


@pytest.fixture
def port():
    """A port nothing listens on, so the real wait finds no browser there."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free = str(s.getsockname()[1])
    s.close()
    return free


def said(capsys):
    """What was printed, with its line breaks read as spaces, since a message
    is wrapped wherever it happens to fill a line."""
    return " ".join(capsys.readouterr().out.split())


def test_a_chromium_without_its_sandbox_is_named_at_once(monkeypatch, tmp_path, port, capsys):
    """No browser of their own, so the bundled Chromium was the only one. It
    has to say what happened, without the twenty seconds, and what to do."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SANDBOX_REFUSED))
    began = time.monotonic()
    assert browser._try_each([(browser.CHROMIUM, "/x/chrome")], tmp_path / "p", port,
                             "https://bank.example/") is None
    assert time.monotonic() - began < 10, "it waited for a port although Chromium had ended"
    words = said(capsys)
    assert "closed right after it started" in words
    assert "could not start its sandbox" in words and "Ubuntu 23.10" in words
    assert "Install Google Chrome or Microsoft Edge" in words
    assert "window opened" not in words and "Try closing" not in words


def test_their_own_browser_tried_first_is_the_way_forward(monkeypatch, tmp_path, port, capsys):
    """On Linux their own browser goes first, and when it opened no port the
    bundled Chromium is tried last. Only the last one tried says what to do,
    so with the sandbox refused it has to point back at their own browser,
    not tell them to install one."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [(browser.CHROME, "/x/google-chrome")])
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SANDBOX_REFUSED))
    real_wait = browser.wait_for_debug_port
    # Their own browser is waited for as before and never answers here. The
    # bundled one gets the real wait, which sees it has ended.
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, alive=None:
                        False if alive is None else real_wait(port, timeout, alive=alive))
    assert browser._try_each([(browser.CHROME, "/x/google-chrome"),
                              (browser.CHROMIUM, "/x/chrome")],
                             tmp_path / "p", port, "https://bank.example/") is None
    words = said(capsys)
    assert "could not start its sandbox" in words
    assert "Close every Google Chrome window" in words
    assert "Install Google Chrome" not in words


def test_set_to_the_bundled_copy_alone_it_names_the_setting(monkeypatch, tmp_path, port, capsys):
    """With "browser": "bundled" no other browser is tried, so installing one
    changes nothing until the setting does. Their own browsers are not even
    looked for in that mode, and the advice must not look for them either."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_bundled_chromium", lambda: ["/x/chrome"])

    def not_looked_for():
        raise AssertionError("a bundled-only sign-in looked for their own browsers")
    monkeypatch.setattr(browser, "_real_browsers", not_looked_for)
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SANDBOX_REFUSED))
    assert browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/",
                                       mode=browser.BUNDLED) is None
    words = said(capsys)
    assert "could not start its sandbox" in words
    assert '"browser": "bundled"' in words and '"auto"' in words


def test_a_chromium_that_ends_for_another_reason_is_waited_for_as_before(monkeypatch, tmp_path,
                                                                         port, capsys):
    """Only the sandbox line ends the wait early. Here the wait runs its time,
    shortened to a second, and says what it always said."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(
        "chrome: error while loading shared libraries: libnss3.so: cannot open shared "
        "object file\n"))
    real_wait, answers = browser.wait_for_debug_port, []

    def wait(port, timeout=20.0, alive=None):
        return real_wait(port, 1.0, alive=lambda: answers.append(alive()) or answers[-1])
    monkeypatch.setattr(browser, "wait_for_debug_port", wait)
    assert browser._try_each([(browser.CHROMIUM, "/x/chrome")], tmp_path / "p", port,
                             "https://bank.example/") is None
    assert answers and all(answers), "the wait was ended early without the sandbox line"
    words = said(capsys)
    assert "The window opened, but no debugging port answered" in words
    assert "sandbox" not in words


def test_a_first_process_that_ends_can_still_lead_to_the_port(monkeypatch, tmp_path, port):
    """Chromium 138 and later started as administrator on Windows relaunch
    themselves, and a launch can hand its address to a copy already running.
    Either way the first process ends and the port opens a moment later from
    another, so the wait has to go on."""
    import http.server
    import json
    import threading

    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(""))

    class Answers(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/x"})
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *a):
            pass

    servers = []

    # Later than one look takes, which on Windows is about two seconds against
    # a port nothing listens on, so the first look has failed by then.
    def answer_later():
        time.sleep(3.0)
        servers.append(http.server.HTTPServer(("127.0.0.1", int(port)), Answers))
        servers[0].serve_forever()

    threading.Thread(target=answer_later, daemon=True).start()
    try:
        assert browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", port,
                               "https://bank.example/") == browser.CHROMIUM
    finally:
        if servers:
            servers[0].shutdown()
            servers[0].server_close()


@pytest.mark.parametrize("platform", [
    "darwin",
    pytest.param("win32", marks=pytest.mark.skipif(os.name != "nt", reason="Windows-only flags")),
])
def test_off_linux_the_bundled_chromium_starts_as_before(monkeypatch, tmp_path, port, platform):
    """The sandbox is refused on Linux only. Elsewhere what Chromium writes
    still goes nowhere and the wait is the old one, which on Windows also
    waits for a Chromium started as administrator to relaunch itself."""
    monkeypatch.setattr(browser.sys, "platform", platform)
    started = _Ended(SANDBOX_REFUSED)
    monkeypatch.setattr(browser.subprocess, "Popen", started)
    asked = []
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, **kw: asked.append(kw) or False)
    assert browser._launch("/x/Chromium", browser.CHROMIUM, tmp_path / "p", port,
                           "https://bank.example/") is None
    assert started.handed == [("/x/Chromium", subprocess.DEVNULL)]
    assert asked == [{}], "the wait was not the old one"


def test_a_launch_that_fails_closes_the_file(monkeypatch, tmp_path, port):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    handed = []

    def blocked(cmd, stderr=None, **_kw):
        handed.append(stderr)
        raise OSError(13, "Permission denied")
    monkeypatch.setattr(browser.subprocess, "Popen", blocked)
    assert browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", port,
                           "https://bank.example/") is None
    assert handed and handed[0] is not subprocess.DEVNULL and handed[0].closed


def test_their_own_browser_keeps_nothing_it_writes_and_is_waited_for(monkeypatch, tmp_path, port):
    """Their own browsers start as they always did, with what they write
    going nowhere and the whole wait, since some start through a script or
    a launcher whose process is not the browser."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    started = _Ended(SANDBOX_REFUSED)
    monkeypatch.setattr(browser.subprocess, "Popen", started)
    asked = []
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, **kw: asked.append(kw) or False)
    assert browser._launch("/x/google-chrome", browser.CHROME, tmp_path / "p", port,
                           "https://bank.example/") is None
    assert started.handed == [("/x/google-chrome", subprocess.DEVNULL)]
    assert asked == [{}], "their own browser was not waited for the old way"


@pytest.mark.parametrize("answers", [False, True], ids=["ended", "opened"])
def test_what_chromium_wrote_is_not_kept(monkeypatch, tmp_path, port, answers):
    """It is read only to look for the sandbox, and the file is closed
    whether the browser opened or not."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    started = _Ended(SANDBOX_REFUSED)
    monkeypatch.setattr(browser.subprocess, "Popen", started)
    if answers:
        monkeypatch.setattr(browser, "wait_for_debug_port", lambda port, timeout=20.0, **kw: True)
    browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", port, "https://bank.example/")
    (_exe, handed), = started.handed
    assert handed is not subprocess.DEVNULL and handed.closed


@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for Chromium")
def test_a_real_chromium_that_ends_without_its_sandbox(monkeypatch, tmp_path, port, capsys):
    """The same, with a real process writing to the file it inherited."""
    (tmp_path / "said.txt").write_text(SANDBOX_REFUSED, encoding="utf-8")
    exe = tmp_path / "chrome"
    exe.write_text("#!/bin/sh\ncat '%s' >&2\nexit 1\n" % (tmp_path / "said.txt"),
                   encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    began = time.monotonic()
    assert browser._try_each([(browser.CHROMIUM, str(exe))], tmp_path / "p", port,
                             "https://bank.example/") is None
    assert time.monotonic() - began < 10
    words = said(capsys)
    assert "could not start its sandbox" in words and "Install Google Chrome" in words
