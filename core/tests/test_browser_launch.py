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


class _EndedProcess:
    """What subprocess.Popen hands back for a browser that has already
    ended, handing its address to a copy running elsewhere."""

    def poll(self):
        return 0


def test_the_profile_is_an_absolute_path_before_the_browser_sees_it(monkeypatch, tmp_path, no_waiting):
    """A relative --user-data-dir is resolved by the browser, from wherever
    it thinks it is, which once made two profiles out of one setting and
    left signed-in cookies in the shared browser cache."""
    seen = {}

    def popen(cmd, **_k):
        seen["args"] = cmd
        return _EndedProcess()
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
                        lambda cmd, **_k: (seen.setdefault("args", cmd), _EndedProcess())[1])
    browser._launch("edge.exe", browser.EDGE, tmp_path / "p", "9231",
                    "https://bank.example/signin")
    assert "--remote-debugging-port=9231" in seen["args"]
    assert seen["args"][-2:] == ["--", "https://bank.example/signin"]


# -- the address is never read as a switch ---------------------------------------
#
# The address is the last thing on the browser's command line, and Chromium
# reads anything there that begins with - or / as a switch. An account's
# settings can hold an address (UKG's base_url), and a history file from
# another computer could carry --no-sandbox into them (a private report of
# 2026-11-10). The address goes after "--" now, which ends the switches,
# and one that is not a web address is never handed over at all.

REFUSED = ["--no-sandbox", "--renderer-cmd-prefix=/bin/sh -c true", "-no-sandbox",
           "/no-sandbox", "javascript:alert(1)", "file:///etc/passwd", "chrome://settings",
           "data:text/html,x", "https:--no-sandbox", "https://", "https:///x",
           "ftp://example.ultipro.com", "", None, 7, " https://example.ultipro.com",
           "https://example.ultipro.com\n--no-sandbox", "https://example.ultipro.com --x",
           "https://exa\tmple.ultipro.com", "\u2014no-sandbox", "\u2212-no-sandbox",
           "about:settings", "about:blank#x"]
TAKEN = ["https://example.ultipro.com", "https://www.ukg.com/login",
         "HTTPS://Example.UltiPro.com/", "https://bank.example/signin?next=%2Fdocs#top",
         "http://127.0.0.1:9/", "about:blank"]


def recording_popen(monkeypatch):
    seen = []

    def popen(cmd, **_k):
        seen.append(list(cmd))
        return _EndedProcess()
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    return seen


@pytest.mark.parametrize("url", REFUSED)
def test_an_address_that_is_not_a_web_address_never_reaches_the_browser(
        url, monkeypatch, tmp_path, no_waiting, capsys):
    seen = recording_popen(monkeypatch)
    assert browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", "9231", url) is None
    assert seen == []
    assert "not a web address" in capsys.readouterr().out


@pytest.mark.parametrize("url", TAKEN)
def test_a_web_address_goes_after_the_end_of_the_switches(url, monkeypatch, tmp_path, no_waiting):
    seen = recording_popen(monkeypatch)
    browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", "9231", url)
    args = seen[0]
    assert args[-2:] == ["--", url]
    assert args.count("--") == 1
    assert all(a.startswith("--") for a in args[1:-2])


def test_on_the_server_the_graphics_switches_stay_switches(monkeypatch, tmp_path, no_waiting):
    """They come after the profile and the port. Had "--" gone before them,
    each would have opened as a tab."""
    seen = recording_popen(monkeypatch)
    monkeypatch.setattr(browser, "server_gpu", lambda: (browser.SERVER_GPU_SWITCHES, None))
    browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", "9231",
                    "https://example.ultipro.com")
    args = seen[0]
    end = args.index("--")
    for switch in browser.SERVER_GPU_SWITCHES:
        assert args.index(switch) < end, switch
    assert args[end + 1:] == ["https://example.ultipro.com"]


def test_a_sign_in_with_such_an_address_opens_nothing_and_says_why(monkeypatch, tmp_path, capsys):
    """Refused before a port is looked at or a browser is fetched."""
    monkeypatch.setattr(browser, "debug_port_holder",
                        lambda *a, **k: pytest.fail("a port was looked at"))
    monkeypatch.setattr(browser, "browser_candidates",
                        lambda *a, **k: pytest.fail("a browser was looked for"))
    assert browser.open_signin_browser(tmp_path / "p", "9231", "--no-sandbox") is None
    assert "not a web address" in capsys.readouterr().out


def test_space_around_an_address_in_a_config_is_taken_off(monkeypatch):
    """As a browser would. Nothing else of the address is changed."""
    opened = []
    monkeypatch.setattr(browser, "debug_port_holder", lambda *a, **k: "a browser")
    monkeypatch.setattr(browser, "_open_tab_in", lambda port, url: opened.append(url) or True)
    monkeypatch.setattr(browser, "bring_forward", lambda port: True)
    monkeypatch.setattr(browser, "_say_shared_port", lambda port: None)
    assert browser.open_signin_browser("p", "9231", "  https://example.ultipro.com \n") \
        == browser.ALREADY_ON_PORT
    assert opened == ["https://example.ultipro.com"]


def test_a_browser_already_on_the_port_is_never_handed_such_an_address(monkeypatch):
    """There the address goes to the browser's own /json/new, where a
    javascript: or file: address opens as a tab."""
    asked = []
    monkeypatch.setattr(browser, "open_local", lambda req, timeout=3: asked.append(req))
    for url in ("javascript:alert(1)", "file:///etc/passwd", "--no-sandbox"):
        assert browser._open_tab_in("9231", url) is False
    assert asked == []


def test_no_spelling_of_a_switch_or_another_scheme_is_taken():
    """A seeded run of prefixes a hand-written check can miss, each with
    tails of its own. Whatever is taken is about:blank or an http or https
    address with a host, and never begins with a switch's mark."""
    import random
    from urllib.parse import urlsplit
    rng = random.Random(20261114)
    prefixes = ["-", "--", "/", " ", "\t", "\u2014", "\u2212", "https:", "HTTPS://", "http://",
                "https://", "javascript:", "about:", "data:", "file:", "https:/", "https:\\",
                "\\\\", "http://-", "https://@", ""]
    tails = ["", "no-sandbox", "example.ultipro.com", "a b", "x\n--y", "-x", "@evil.example",
             ":443", "/path?q=1#f", "\u00e9xample.com", "[::1]", "[::1]:9"]
    for _ in range(4000):
        url = rng.choice(prefixes) + rng.choice(tails) + rng.choice(["", rng.choice(tails)])
        if not browser.signin_address_ok(url):
            continue
        assert url == "about:blank" or (
            urlsplit(url).scheme.lower() in ("http", "https") and urlsplit(url).hostname), url
        assert not url.startswith(("-", "/", "\\")) and url == url.strip(), url
        assert not any(c.isspace() for c in url), url


def test_the_bundled_chromium_opens_the_address_after_the_end_of_its_switches(
        monkeypatch, tmp_path):
    """The real thing. Playwright's own Chromium, headless, on a profile in
    a temp folder, launched by _launch, opens the page given after "--" as
    its tab, and a switch given there is a tab too, not a switch it obeys.
    Measured first by hand on 2026-11-14."""
    import json
    import urllib.request
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        exe = pw.chromium.executable_path
    if not exe or not Path(exe).is_file():
        pytest.skip("Playwright's own Chromium is not installed here")
    started = []
    real = subprocess.Popen

    def popen(cmd, **kwargs):
        started.append(real(cmd, **kwargs))
        return started[-1]
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser, "server_gpu", lambda: (("--headless=new",), None))

    def free():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return str(s.getsockname()[1])

    def tabs(port):
        with urllib.request.urlopen("http://127.0.0.1:%s/json/list" % port, timeout=5) as r:
            return [t["url"] for t in json.load(r) if t.get("type") == "page"]

    try:
        port = free()
        page = "http://127.0.0.1:9/signin"
        assert browser._launch(exe, browser.CHROMIUM, tmp_path / "one", port, page)
        for _ in range(40):
            if page in tabs(port):
                break
            time.sleep(0.25)
        assert page in tabs(port)
        started[-1].kill()
        started[-1].wait(10)
        # Taken past the check here, to see what the browser does with it.
        monkeypatch.setattr(browser, "signin_address_ok", lambda url: True)
        port, other = free(), free()
        assert browser._launch(exe, browser.CHROMIUM, tmp_path / "two", port,
                               "--remote-debugging-port=" + other)
        time.sleep(1)
        assert any("remote-debugging-port" in t for t in tabs(port)), tabs(port)
        with pytest.raises(OSError):
            urllib.request.urlopen("http://127.0.0.1:%s/json/version" % other, timeout=2)
    finally:
        for proc in started:
            proc.kill()
            try:
                proc.wait(10)
            except Exception:
                pass


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


def _looks(monkeypatch) -> list:
    """What the wait for the debugging port heard each time it asked whether
    the browser was still running, in order. Read rather than timing the
    wait, so a slow machine cannot fail a wait that ended at the right look."""
    asked = []
    real = browser.wait_for_debug_port

    def wait(port, timeout=20.0, alive=None):
        def still_running():
            asked.append(alive())
            return asked[-1]
        return real(port, timeout, alive=None if alive is None else still_running)
    monkeypatch.setattr(browser, "wait_for_debug_port", wait)
    return asked


def test_a_chromium_without_its_sandbox_is_named_at_once(monkeypatch, tmp_path, port, capsys):
    """No browser of their own, so the bundled Chromium was the only one. It
    has to say what happened, without the twenty seconds, and what to do."""
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SANDBOX_REFUSED))
    asked = _looks(monkeypatch)
    assert browser._try_each([(browser.CHROMIUM, "/x/chrome")], tmp_path / "p", port,
                             "https://bank.example/") is None
    # Ended at the look that found Chromium gone, not when its twenty
    # seconds were up.
    assert asked and asked[-1] is False and asked.count(False) == 1, \
        "it waited for a port although Chromium had ended: %s" % asked
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
    asked = _looks(monkeypatch)
    assert browser._try_each([(browser.CHROMIUM, str(exe))], tmp_path / "p", port,
                             "https://bank.example/") is None
    assert asked and asked[-1] is False and asked.count(False) == 1, asked
    words = said(capsys)
    assert "could not start its sandbox" in words and "Install Google Chrome" in words
