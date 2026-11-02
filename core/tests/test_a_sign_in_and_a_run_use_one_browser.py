"""A sign-in and the runs after it use one browser, or say why not (#90).

On an Intel Mac a Citi run opened a second window on another profile and
found it signed out, while the sign-in had gone well. Three things could do
that with nothing said. A config with no cdp_url made every run open a
browser of its own. A sign-in started while another browser held the app's
port opened a window that could never take the port, and the wait for the
port heard the old browser and called the sign-in done. And seventeen apps
fell back to port 9224, Wealthfront's, when their config named no port, so
their sign-in and a sibling app's could meet on one port. Every value here
is made up.
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from paperpull_core import browser

# The real port questions, read when this module loads, before conftest's
# _no_real_browser_on_a_port stands them in for each test.
REAL_PORT_HOLDER = browser.debug_port_holder
REAL_OPEN_TAB_IN = browser._open_tab_in
REAL_PORT_TAKEN = browser._port_taken

REPO = Path(__file__).resolve().parents[2]
APPS = sorted(p for p in (REPO / "apps").iterdir()
              if p.is_dir() and (p / "config.example.json").exists())
PORT_CALL = re.compile(r'port_from_cdp_url\(\s*self\.config\.get\("cdp_url",\s*""\)\s*,\s*"(\d+)"\s*\)')


def _app_sources(app: Path):
    return {f.name: f.read_text(encoding="utf-8") for f in sorted(app.glob("*.py"))}


def _example_port(app: Path):
    m = re.search(r":(\d+)", json.loads((app / "config.example.json").read_text(encoding="utf-8"))
                  .get("cdp_url", "") or "")
    return m.group(1) if m else None


# -- a browser of the app's own is said out loud ---------------------------------

def test_every_app_opens_a_browser_of_its_own_only_through_the_core():
    """Each app's run, with no cdp_url, opens its own browser through
    browser.launch_own_browser, which says so, never straight through
    Playwright."""
    direct, routed = [], 0
    for app in APPS:
        for name, src in _app_sources(app).items():
            if ".chromium.launch_persistent_context(" in src:
                direct.append("%s/%s" % (app.name, name))
            routed += src.count("browser_launcher.launch_own_browser(self._pw.chromium, ")
    assert not direct, "these open a browser of their own with nothing said: %s" % direct
    assert routed >= 60, routed


def test_a_browser_of_its_own_is_said_and_launched_as_before(capsys):
    """Launched as before, and inside its sandbox since 2026-10, see
    test_every_browser_starts_in_its_sandbox."""
    seen = {}

    class Chromium:
        def launch_persistent_context(self, user_data_dir, **kwargs):
            seen.update(dir=user_data_dir, kwargs=kwargs)
            return "context"

    got = browser.launch_own_browser(Chromium(), "/x/browser-profile", headless=False,
                                     accept_downloads=True)
    assert got == "context"
    assert seen == {"dir": "/x/browser-profile",
                    "kwargs": {"headless": False, "accept_downloads": True,
                               "chromium_sandbox": True}}
    said = capsys.readouterr().out
    assert "no cdp_url" in said and "/x/browser-profile" in said
    assert "config.example.json" in said


# -- each app's own port --------------------------------------------------------

def test_every_app_falls_back_to_its_own_port():
    """A config with no port fell back to 9224, Wealthfront's, in seventeen
    apps. The fallback is the port the app's own example config names."""
    wrong, checked = [], 0
    for app in APPS:
        want = _example_port(app)
        for name, src in _app_sources(app).items():
            for m in PORT_CALL.finditer(src):
                checked += 1
                if m.group(1) != want:
                    wrong.append("%s/%s falls back to %s, its example says %s"
                                 % (app.name, name, m.group(1), want))
    assert not wrong, wrong
    assert checked >= 60, checked


def test_no_two_apps_name_the_same_port():
    """Invest529 shipped on Simmons Bank's 9298, so with both set up from
    their examples each attached to the other's browser."""
    names = {}
    for app in APPS:
        port = _example_port(app)
        if port:
            names.setdefault(port, []).append(app.name)
    shared = {port: apps for port, apps in names.items() if len(apps) > 1}
    assert not shared, shared
    assert len(names) >= 70, len(names)


# -- a port another browser holds -----------------------------------------------

class _Browser(BaseHTTPRequestHandler):
    """A browser's debugging endpoint, as much of it as a sign-in asks."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/json/version":
            body = json.dumps({"Browser": "Chrome/141.0.0.0",
                               "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/x"})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        self.server.opened.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")


@pytest.fixture()
def held_port(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Browser)
    srv.opened = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(browser, "debug_port_holder", REAL_PORT_HOLDER)
    monkeypatch.setattr(browser, "_open_tab_in", REAL_OPEN_TAB_IN)
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_port_already_held_is_used_and_never_launched_over(held_port, monkeypatch, tmp_path,
                                                            capsys):
    port = str(held_port.server_address[1])

    def no_launch(*a, **kw):
        raise AssertionError("a browser was launched over a port another one holds")
    monkeypatch.setattr(browser, "browser_candidates", no_launch)
    monkeypatch.setattr(browser, "_try_each", no_launch)

    got = browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/sign-in")
    assert got == browser.ALREADY_ON_PORT
    assert held_port.opened and held_port.opened[0].startswith("/json/new?https://bank.example/sign-in")
    said = capsys.readouterr().out
    assert "already listening on port %s" % port in said and "Chrome/141" in said
    assert "new tab" in said


def test_a_free_port_is_launched_on_as_before(monkeypatch, tmp_path):
    monkeypatch.setattr(browser, "debug_port_holder", REAL_PORT_HOLDER)
    monkeypatch.setattr(browser, "_port_taken", REAL_PORT_TAKEN)
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = str(s.getsockname()[1])
    s.close()
    assert browser.debug_port_holder(port) is None
    assert not browser._port_taken(port)
    monkeypatch.setattr(browser, "browser_candidates", lambda **kw: [("Chromium", "/x/chrome")])
    monkeypatch.setattr(browser, "_try_each", lambda *a, **kw: "Chromium")
    assert browser.open_signin_browser(tmp_path / "p", port, "https://x.example/") == "Chromium"


# -- a port held by something that does not answer ------------------------------

def _no_launch(*a, **kw):
    raise AssertionError("a browser was launched on a port something else holds")


@pytest.fixture()
def silent_port(monkeypatch):
    """A port that takes a connection and never says anything, the way a
    Chrome left from an earlier sign-in held Capital One's after it hung."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    monkeypatch.setattr(browser, "debug_port_holder", REAL_PORT_HOLDER)
    monkeypatch.setattr(browser, "_port_taken", REAL_PORT_TAKEN)
    monkeypatch.setattr(browser, "_SLOW_START_SECONDS", 0.5)
    yield str(s.getsockname()[1])
    s.close()


def test_a_port_held_by_something_silent_is_said_and_never_launched_over(
        silent_port, monkeypatch, tmp_path, capsys):
    """Each browser tried next could not take the port either, so a Brave
    window and then a Chrome for Testing one opened, on profiles of their
    own, and every one of them was closed again with the port still held
    (#90)."""
    monkeypatch.setattr(browser, "browser_candidates", _no_launch)
    monkeypatch.setattr(browser, "_try_each", _no_launch)

    got = browser.open_signin_browser(tmp_path / "p", silent_port, "https://bank.example/")
    assert got is None
    said = capsys.readouterr().out
    assert "port %s" % silent_port in said
    assert "does not answer" in said
    assert ":%s" % silent_port in said, "says how to find what holds it"


@pytest.fixture()
def full_port(monkeypatch):
    """A port held by something that takes no more connections. Its queue of
    one is filled before the sign-in looks, as the looks of earlier sign-ins
    and runs fill a hung browser's queue of ten. Each look is cut short, since
    a connection that a full queue never takes waits out its whole timeout."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    queued = []
    for _ in range(64):
        c = socket.socket()
        c.settimeout(0.3)
        try:
            c.connect(("127.0.0.1", port))
        except OSError:
            c.close()
            break
        queued.append(c)
    else:
        pytest.fail("the queue of the port never filled")
    monkeypatch.setattr(browser, "debug_port_holder",
                        lambda p, timeout=1.5: REAL_PORT_HOLDER(p, timeout=min(timeout, 0.3)))
    monkeypatch.setattr(browser, "_port_taken", REAL_PORT_TAKEN)
    monkeypatch.setattr(browser, "_SLOW_START_SECONDS", 0.3)
    yield str(port)
    for c in queued:
        c.close()
    s.close()


def test_a_port_whose_holder_takes_no_more_connections_is_never_launched_over(
        full_port, monkeypatch, tmp_path, capsys):
    """Whether something held the port was first asked by connecting to it.
    A holder that takes no connections answers none once its queue is full,
    and every look left one more in the queue, so from the third sign-in or
    so the port looked free and browser after browser was launched there
    again, on Windows and Linux alike."""
    monkeypatch.setattr(browser, "browser_candidates", _no_launch)
    monkeypatch.setattr(browser, "_try_each", _no_launch)
    for attempt in range(1, 5):
        got = browser.open_signin_browser(tmp_path / "p", full_port, "https://bank.example/")
        assert got is None, "sign-in %d" % attempt
        assert "port %s" % full_port in capsys.readouterr().out, "sign-in %d" % attempt


@pytest.mark.parametrize("code, taken", [("EADDRINUSE", True),
                                         ("EADDRNOTAVAIL", False),
                                         ("EACCES", False)])
def test_only_an_address_in_use_is_taken(code, taken, monkeypatch):
    """A bind refused for a reason other than the port being in use says
    nothing about a browser there, so the sign-in carries on as before."""
    import errno
    import os
    import socket
    number = getattr(errno, code)

    def refused(self, address):
        raise OSError(number, os.strerror(number))
    monkeypatch.setattr(socket.socket, "bind", refused)
    assert REAL_PORT_TAKEN("9222") is taken


def test_a_free_port_is_answered_at_once():
    """Connecting to a free port is refused only after two seconds on
    Windows, so asking that way made every sign-in on a free port wait a
    second for nothing."""
    import socket
    import time
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = str(s.getsockname()[1])
    s.close()
    started = time.perf_counter()
    assert not REAL_PORT_TAKEN(port)
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize("platform, finds, ends", [
    ("win32", "netstat -ano | findstr :9276", "taskkill /PID <PID> /F"),
    ("darwin", "lsof -nP -iTCP:9276 -sTCP:LISTEN", "kill -9 <PID>"),
    ("linux", "ss -ltnp 'sport = :9276'", "kill -9 <PID>"),
])
def test_what_holds_the_port_is_said_how_to_find_and_end(
        platform, finds, ends, monkeypatch, capsys):
    """Each system's own command finds the holder and ends it, and the words
    around them keep the house style, with no colon or semicolon."""
    monkeypatch.setattr(browser.sys, "platform", platform)
    browser._say_port_silent("9276")
    said = capsys.readouterr().out
    assert "    " + finds in said
    assert "    " + ends in said
    assert ("ss -ltnp" in said) is (platform == "linux")
    prose = [line for line in said.splitlines() if not line.startswith("    ")]
    assert not [line for line in prose if ":" in line or ";" in line or "—" in line], said


def test_a_browser_still_starting_on_the_port_is_used(monkeypatch, tmp_path, capsys):
    """A port taken before its browser answers is not given up on at the
    first look. A sign-in started twice in a row meets its own browser
    still starting."""
    answers = iter([None, "Chrome/141.0.0.0"])
    monkeypatch.setattr(browser, "debug_port_holder", lambda port, timeout=1.5: next(answers))
    monkeypatch.setattr(browser, "_port_taken", lambda port: True)
    monkeypatch.setattr(browser, "_open_tab_in", lambda port, url: True)
    monkeypatch.setattr(browser, "browser_candidates", _no_launch)
    monkeypatch.setattr(browser, "_try_each", _no_launch)
    got = browser.open_signin_browser(tmp_path / "p", "9", "https://bank.example/")
    assert got == browser.ALREADY_ON_PORT
    assert "Chrome/141" in capsys.readouterr().out


# -- a browser given up on is not left open -------------------------------------

class _Proc:
    def __init__(self, running):
        self.running, self.terminated = running, False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True


@pytest.mark.parametrize("running", [True, False])
def test_a_browser_whose_port_never_answered_is_closed_if_it_is_still_ours(
        running, monkeypatch, tmp_path, capsys):
    """A window left open there was a browser no run could reach, and the
    next one tried opened beside it on the same port. One that already
    ended, handing the address to a copy that was running, is left alone."""
    proc = _Proc(running)
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(browser, "wait_for_debug_port", lambda *a, **kw: False)
    got = browser._launch("/x/chrome", browser.CHROME, tmp_path / "p", "9", "https://x.example/")
    assert got is None
    assert proc.terminated is running
    assert ("That window was closed" in capsys.readouterr().out) is running
