"""gui/mac_host.py, which runs the panel for PaperPull.app's window.

Run for real, against a stand-in uvicorn on the listening socket it is handed.
The stand-in also starts a child in the panel's group, as the panel starts runs
and they start browsers, so "everything it started stops" is what is tested.
"""
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
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
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(out + "/child", "w").write(str(child.pid))
if os.environ.get("STAND_IN") == "ends-cleanly":
    time.sleep(1)
    child.kill()
    sys.exit(0)
sock = socket.socket(fileno=int(sys.argv[sys.argv.index("--fd") + 1]))
while True:
    conn, _ = sock.accept()
    conn.recv(1024)
    conn.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n")
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


def test_the_usual_port_taken_means_another_one(module, monkeypatch):
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        taken = other.getsockname()[1]
        monkeypatch.setattr(module, "USUAL_PORT", taken)
        sock = module.choose_socket()
        assert sock.getsockname()[0] == "127.0.0.1" and sock.getsockname()[1] != taken
        sock.close()


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
