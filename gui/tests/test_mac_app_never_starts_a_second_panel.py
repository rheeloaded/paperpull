"""PaperPull.app never runs a second panel on one person's folder (#141).

The app's window starts gui/mac_host.py, which starts the panel on port 8765,
or on another port when 8765 is held. When the one holding it is this
person's own panel, started from a terminal, say, a second panel would write
one account's records beside the first, which the terminal's own panel never
allowed, since it cannot start on a port that is taken. So the window shows
the panel already there, and closing the window leaves it running, since
nothing is stopped that the host did not start. Another program on 8765, or
another person's panel with a folder of its own, still means another port,
and a panel whose owner cannot be told means none.

Held here with the very functions the app runs, the real panel served on a
port, stand-ins for other programs, and lsof's answers given, since lsof and
the host's process group are a Mac's (core/tests/test_mac_host.py runs them
for real on POSIX).
"""
import http.server
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")

HOST = Path(__file__).resolve().parents[1] / "mac_host.py"


@pytest.fixture()
def host(monkeypatch):
    monkeypatch.delenv("PAPERPULL_PORT", raising=False)
    spec = importlib.util.spec_from_file_location("mac_host_second_panel", HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "HELD_ANSWERS_WITHIN", 1)
    # Nothing here may signal a process, whatever the host decides.
    signalled = []
    monkeypatch.setattr(mod.os, "killpg", lambda *a: signalled.append(a), raising=False)
    monkeypatch.setattr(mod, "stop_group", lambda panel: signalled.append(panel))
    mod.signalled = signalled
    return mod


@pytest.fixture(scope="module")
def panel_port():
    """The real panel, as one started from a terminal would be."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    number = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_module.app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield number
    server.should_exit = True
    thread.join(10)
    sock.close()


class _Page(http.server.BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def other():
    """Another program answering on a port, with the page it is given."""
    servers = []

    def serve(body):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), type("Page", (_Page,), {"body": body}))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]
    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def silent():
    """A port something listens on and never answers."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    yield sock.getsockname()[1]
    sock.close()


def lsof_says(host, monkeypatch, *, pids=(), status=None, missing=False):
    """lsof's answer about the port, and what it was asked."""
    asked = []

    def run(cmd, **kwargs):
        asked.append(cmd)
        if missing:
            raise FileNotFoundError(cmd[0])
        out = "".join("p%d\n" % p for p in pids)
        return subprocess.CompletedProcess(cmd, status if status is not None else (0 if pids else 1), out, "")
    monkeypatch.setattr(host.subprocess, "run", run)
    monkeypatch.setattr(host.os, "getuid", lambda: 501, raising=False)
    return asked


def test_the_real_panel_answers_as_a_desktop_panel(host, panel_port):
    assert host.desktop_panel_on(panel_port) is True


def test_another_programs_page_is_not_a_panel(host, other):
    assert host.desktop_panel_on(other(b"<html><title>Something else</title></html>")) is False


def test_paperpull_servers_page_is_not_a_desktop_panel(host, other, monkeypatch):
    """PaperPull Server keeps a folder of its own, so it is never shown in
    place of the person's own panel."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    page = app_module.index().encode("utf-8")
    monkeypatch.delenv("PAPERPULL_SERVER")
    assert b"<title>PaperPull</title>" in page
    assert host.desktop_panel_on(other(page)) is False


def test_a_port_that_never_answers_gives_no_answer(host, silent):
    assert host.desktop_panel_on(silent, within=0) is None


def test_lsof_is_asked_about_this_persons_own_listeners_alone(host, monkeypatch):
    asked = lsof_says(host, monkeypatch, pids=(812,))
    assert host.own_listener(8765) == 812
    [cmd] = asked
    assert cmd[0] == "/usr/sbin/lsof"
    assert cmd[cmd.index("-u") + 1] == "501" and "-a" in cmd, "this person's processes, and only those"
    assert "-iTCP:8765" in cmd and "-sTCP:LISTEN" in cmd


def test_lsof_finding_nothing_is_none_and_failing_is_an_error(host, monkeypatch):
    lsof_says(host, monkeypatch)
    assert host.own_listener(8765) is None
    lsof_says(host, monkeypatch, status=2)
    with pytest.raises(OSError):
        host.own_listener(8765)
    lsof_says(host, monkeypatch, missing=True)
    with pytest.raises(OSError):
        host.own_listener(8765)


def test_this_persons_own_panel_on_the_usual_port_is_shown_not_doubled(host, monkeypatch, panel_port):
    monkeypatch.setattr(host, "USUAL_PORT", panel_port)
    lsof_says(host, monkeypatch, pids=(812,))
    assert host.choose_socket() == (None, panel_port)


def test_another_persons_panel_means_a_panel_of_ones_own_on_another_port(host, monkeypatch, panel_port):
    """lsof lists only this person's processes, so it finds no one."""
    monkeypatch.setattr(host, "USUAL_PORT", panel_port)
    lsof_says(host, monkeypatch)
    sock, port = host.choose_socket()
    try:
        assert port != panel_port and sock.getsockname() == ("127.0.0.1", port)
    finally:
        sock.close()


def test_another_program_on_the_usual_port_means_another_port(host, monkeypatch, other):
    held = other(b"<html><title>Something else</title></html>")
    monkeypatch.setattr(host, "USUAL_PORT", held)
    asked = lsof_says(host, monkeypatch, pids=(812,))
    sock, port = host.choose_socket()
    try:
        assert port != held
    finally:
        sock.close()
    assert asked == [], "a page that is not the panel's needs no owner"


@pytest.mark.parametrize("lsof", ["missing", "failing"])
def test_a_panel_whose_owner_cannot_be_told_starts_nothing(host, monkeypatch, panel_port, lsof):
    monkeypatch.setattr(host, "USUAL_PORT", panel_port)
    lsof_says(host, monkeypatch, missing=lsof == "missing", status=2)
    assert host.choose_socket() is None


def test_a_program_of_ones_own_that_never_answers_starts_nothing(host, monkeypatch, silent):
    """It may be a panel of theirs that is busy, so no second one starts."""
    monkeypatch.setattr(host, "USUAL_PORT", silent)
    lsof_says(host, monkeypatch, pids=(812,))
    assert host.choose_socket() is None


def test_someone_elses_silent_program_means_another_port(host, monkeypatch, silent):
    monkeypatch.setattr(host, "USUAL_PORT", silent)
    lsof_says(host, monkeypatch)
    sock, port = host.choose_socket()
    sock.close()
    assert port != silent


def test_a_free_usual_port_is_taken_without_asking_anyone(host, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    monkeypatch.setattr(host, "USUAL_PORT", free)
    asked = lsof_says(host, monkeypatch, pids=(812,))
    sock, port = host.choose_socket()
    sock.close()
    assert port == free and asked == []


# -- what the window is shown, and what is stopped --------------------------------------------

def test_the_panel_shown_is_never_stopped_when_the_window_closes(host, panel_port, capfd):
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    assert host.show_own_panel(panel_port, stop) == 0
    out, err = capfd.readouterr()
    assert out == "READY %d\n" % panel_port
    assert "keeps running" in err
    assert host.signalled == [], "nothing is signalled that the host did not start"


def test_a_shown_panel_that_goes_away_is_said_so_the_window_can_offer_its_own(host, capfd):
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    threading.Timer(0.3, held.close).start()
    stop = threading.Event()
    assert host.show_own_panel(port, stop) == 1
    assert "has stopped" in capfd.readouterr().err
    assert host.signalled == []


def test_main_starts_no_panel_beside_the_one_shown(host, monkeypatch):
    did = []
    monkeypatch.setattr(host, "open_log", lambda: open(os.devnull, "wb"))
    monkeypatch.setattr(host.os, "dup2", lambda *a: None)
    monkeypatch.setattr(host, "stop_when_told", lambda stop: None)
    monkeypatch.setattr(host, "choose_socket", lambda: (None, 8765))
    monkeypatch.setattr(host, "start_panel", lambda *a: did.append("started"))
    monkeypatch.setattr(host, "show_own_panel", lambda port, stop: did.append(("shown", port)) or 0)
    assert host.main() == 0
    assert did == [("shown", 8765)]


def test_main_refuses_when_there_is_nowhere_to_run(host, monkeypatch):
    did = []
    monkeypatch.setattr(host, "open_log", lambda: open(os.devnull, "wb"))
    monkeypatch.setattr(host.os, "dup2", lambda *a: None)
    monkeypatch.setattr(host, "stop_when_told", lambda stop: None)
    monkeypatch.setattr(host, "choose_socket", lambda: None)
    monkeypatch.setattr(host, "start_panel", lambda *a: did.append("started"))
    assert host.main() == 1
    assert did == []
