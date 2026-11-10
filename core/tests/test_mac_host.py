"""gui/mac_host.py, which runs the panel for PaperPull.app's window.

Run for real, against a stand-in uvicorn on the listening socket it is handed.
The stand-in also starts a child in the panel's group, as the panel starts runs
and they start browsers, so "everything it started stops" is what is tested.
"""
import http.server
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip("PaperPull.app is macOS only", allow_module_level=True)

HOST = Path(__file__).resolve().parents[2] / "gui" / "mac_host.py"

UVICORN = """
import os, socket, subprocess, sys, time
if os.environ.get("STAND_IN") == "dies":
    sys.exit(3)
out = os.environ["NOTES"]
open(out + "/env", "w").write("\\n".join(k + "=" + v for k, v in os.environ.items()))
open(out + "/argv", "w").write("\\n".join(sys.argv))
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(out + "/child", "w").write(str(child.pid))
if os.environ.get("STAND_IN") == "ends-cleanly":
    time.sleep(1)
    child.kill()
    sys.exit(0)
sock = socket.socket(fileno=int(sys.argv[sys.argv.index("--fd") + 1]))
while True:
    conn, _ = sock.accept()
    asked = conn.recv(1024)
    body = b""
    if asked.startswith(b"GET /api/finishing "):
        # What is applying its changes, as the test last wrote it.
        try:
            body = open(out + "/finishing", "rb").read()
        except OSError:
            body = b'{"finishing": []}'
    conn.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: %d\\r\\nConnection: close\\r\\n\\r\\n" % len(body) + body)
    conn.close()
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def bundle(tmp_path):
    """The host where the app holds it, with a stand-in uvicorn to import."""
    gui = tmp_path / "PaperPull.app" / "Contents" / "Resources" / "gui"
    gui.mkdir(parents=True)
    shutil.copy(HOST, gui / "mac_host.py")
    stand_in = tmp_path / "stand_in"
    stand_in.mkdir()
    (stand_in / "uvicorn.py").write_text(UVICORN, encoding="utf-8")
    home, notes = tmp_path / "home", tmp_path / "notes"
    home.mkdir()
    notes.mkdir()
    return gui / "mac_host.py", dict(os.environ, HOME=str(home), NOTES=str(notes), PYTHONPATH=str(stand_in),
                                     PAPERPULL_PORT=str(_free_port())), notes


def _start(host, env, **more):
    return subprocess.Popen([sys.executable, "-B", "-s", str(host)], env=dict(env, **more), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def _ready(process):
    line = process.stdout.readline()
    assert line.startswith("READY "), line
    return int(line.split()[1])


def _gone(pid, within=10):
    end = time.time() + within
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        # A child of an exited panel is only a zombie until launchd reaps it.
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
        if not state.strip() or state.strip().startswith("Z"):
            return True
        time.sleep(0.05)
    return False


def test_it_says_ready_on_the_port_it_was_asked_for(bundle):
    host, env, _ = bundle
    process = _start(host, env)
    assert _ready(process) == int(env["PAPERPULL_PORT"])
    process.stdin.close()
    assert process.wait(15) == 0


def test_stdin_ending_stops_the_panel_and_all_it_started(bundle):
    """However the window ends, a crash included, the system closes this."""
    host, env, notes = bundle
    process = _start(host, env)
    _ready(process)
    child = int((notes / "child").read_text())
    process.stdin.close()
    assert process.wait(15) == 0
    assert _gone(child), "the run the panel started goes with it"


def test_a_window_gone_before_the_panel_is_ready_stops_it_too(bundle):
    """Saying READY to a window that has crashed raises BrokenPipeError, and
    a host that left on it stranded the panel."""
    host, env, notes = bundle
    process = _start(host, env)
    process.stdout.close()
    end = time.time() + 15
    while time.time() < end and not (notes / "child").exists():
        time.sleep(0.02)
    child = int((notes / "child").read_text())
    process.wait(15)
    assert _gone(child), "nothing is left running with no window"


def test_the_panel_gets_what_the_terminal_script_gives_it_and_the_apps_path(bundle):
    host, env, notes = bundle
    process = _start(host, env)
    _ready(process)
    seen = dict(line.split("=", 1) for line in (notes / "env").read_text().splitlines() if "=" in line)
    process.stdin.close()
    process.wait(15)
    assert seen["PYTHONNOUSERSITE"] == "1"
    assert seen["PYTHONPYCACHEPREFIX"].startswith(env["HOME"]), "bytecode never goes into the signed bundle"
    assert seen["PAPERPULL_APP_PATH"].endswith("PaperPull.app")


def test_a_panel_that_dies_is_a_failure_with_no_ready_line(bundle):
    host, env, _ = bundle
    process = _start(host, env, STAND_IN="dies")
    assert process.wait(15) == 1
    assert process.stdout.read() == ""


def test_a_panel_stopped_on_purpose_is_not_a_failure(bundle):
    host, env, _ = bundle
    assert _start(host, env, STAND_IN="ends-cleanly").wait(20) == 0


def test_a_port_someone_is_using_is_refused(bundle):
    host, env, _ = bundle
    with socket.socket() as other:
        other.bind(("127.0.0.1", int(env["PAPERPULL_PORT"])))
        other.listen()
        assert _start(host, env).wait(15) == 1


@pytest.fixture()
def module(monkeypatch):
    monkeypatch.delenv("PAPERPULL_PORT", raising=False)
    spec = importlib.util.spec_from_file_location("mac_host_under_test", HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def page():
    """A program of this person's own, served from this process, answering
    every GET with the page it is given."""
    servers = []

    def serve(body):
        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]
    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _lsof():
    for path in ("/usr/sbin/lsof", shutil.which("lsof")):
        if path and os.path.exists(path):
            return path
    pytest.skip("no lsof here")


def test_the_usual_port_taken_by_another_program_means_another_one(module, monkeypatch, page):
    taken = page(b"<html><title>Something else</title></html>")
    monkeypatch.setattr(module, "USUAL_PORT", taken)
    sock, port = module.choose_socket()
    assert sock.getsockname() == ("127.0.0.1", port) and port != taken
    sock.close()


def test_lsof_finds_this_persons_own_listener_and_nothing_once_it_is_gone(module, monkeypatch):
    monkeypatch.setattr(module, "LSOF", _lsof())
    with socket.socket() as mine:
        mine.bind(("127.0.0.1", 0))
        mine.listen()
        port = mine.getsockname()[1]
        assert module.own_listener(port) == os.getpid()
    assert module.own_listener(port) is None


def test_this_persons_own_panel_on_the_usual_port_is_shown_not_doubled(module, monkeypatch, page):
    """A panel started from a terminal, say. A second one would write one
    account's records beside it."""
    monkeypatch.setattr(module, "LSOF", _lsof())
    held = page(b"<title>PaperPull</title><script>const SERVER = false;</script>")
    monkeypatch.setattr(module, "USUAL_PORT", held)
    assert module.choose_socket() == (None, held)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return bool(state.strip()) and not state.strip().startswith("Z")


def test_a_quit_waits_for_what_is_applying_and_then_stops_all_of_it(bundle):
    """A Rename or a Move stopped partway leaves its records naming files that
    have moved, so the panel and its runs go on while the panel names one."""
    host, env, notes = bundle
    (notes / "finishing").write_text('{"finishing": ["rename_apply"]}', encoding="utf-8")
    process = _start(host, env)
    _ready(process)
    child = int((notes / "child").read_text())
    process.stdin.close()
    assert process.stdout.readline() == "FINISHING\n", "the window is told why it waits"
    time.sleep(2)
    assert process.poll() is None and _alive(child), "nothing is stopped while it applies"
    (notes / "finishing").write_text('{"finishing": []}', encoding="utf-8")
    assert process.wait(15) == 0
    assert _gone(child), "and then everything the panel started stops"
    log = (Path(env["HOME"]) / "Library" / "Logs" / "PaperPull" / "panel.log").read_text(encoding="utf-8")
    assert "once rename_apply has finished" in log


def test_the_panel_keeps_no_access_log(bundle):
    host, env, notes = bundle
    process = _start(host, env)
    _ready(process)
    argv = (notes / "argv").read_text().splitlines()
    process.stdin.close()
    process.wait(15)
    assert "--no-access-log" in argv and "--fd" in argv


def test_the_log_starts_afresh_only_past_its_limit(module, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(module, "LOG_LIMIT", 10)
    log = tmp_path / "Library" / "Logs" / "PaperPull" / "panel.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(b"short")
    module.open_log().close()
    assert log.read_bytes() == b"short"
    log.write_bytes(b"long enough to go")
    module.open_log().close()
    assert log.read_bytes() == b""
