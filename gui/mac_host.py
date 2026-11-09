"""Runs the panel for PaperPull.app's window, and stops it when the window goes.

The window (packaging/macos/launcher.m) starts this with the bundled Python and
keeps its stdin open. It tells the window one thing, a "READY <port>" line on
stdout once GET / answers 200, and ends with status 0 when the panel was
stopped on purpose and 1 when it failed. Why it failed is in the log.

stdin reaching its end is the signal to stop. The system closes it however the
window ends, a crash included, so a panel is never left running with no window.

The panel starts the runs and they start browsers for sign-in, so it gets a
process group of its own and the whole group is stopped.
"""
import http.client
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

USUAL_PORT = 8765  # the same one each time, so the page keeps what it stored
READY_WITHIN = 120
STOP_GRACE = 5
LOG_LIMIT = 5 * 1024 * 1024


def open_log():
    """~/Library/Logs/PaperPull/panel.log, started afresh past LOG_LIMIT."""
    path = Path.home() / "Library" / "Logs" / "PaperPull" / "panel.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = path.exists() and path.stat().st_size > LOG_LIMIT
    return open(path, "wb" if fresh else "ab", buffering=0)


def listen_on(port):
    """A socket listening on 127.0.0.1, or None if the port is in use.

    It is opened here and handed to the panel, rather than picking a free port
    and letting the panel take it a moment later, so no other program can get
    in between and be shown in the panel's window. SO_REUSEADDR is for a port
    still in TIME_WAIT after the last quit. On a Mac it would also let this
    bind beside a listener on every address, so anyone listening is asked
    about first. TCP_NODELAY is set here because uvicorn takes --fd for a Unix
    socket and would not set it, and the connections inherit it."""
    if port:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return None
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
    except OSError:
        sock.close()
        return None
    return sock


def choose_socket():
    """PAPERPULL_PORT if it is set, for tests, else the usual port, else any."""
    wanted = os.environ.get("PAPERPULL_PORT", "")
    if wanted.isdigit() and 0 < int(wanted) < 65536:
        return listen_on(int(wanted))
    return listen_on(USUAL_PORT) or listen_on(0)


def start_panel(sock, log):
    gui = Path(__file__).resolve().parent
    resources = gui.parent
    env = dict(os.environ, PYTHONNOUSERSITE="1",
               # Never into the bundle, which a signature covers.
               PYTHONPYCACHEPREFIX=str(Path.home() / "Library" / "Caches" / "PaperPull" / "pycache"),
               # So the panel can bring this window back after a sign-in.
               PAPERPULL_APP_PATH=str(resources.parents[1]))
    fd = sock.fileno()
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--fd", str(fd), "--app-dir", str(gui)],
        cwd=resources, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        pass_fds=[fd], start_new_session=True)


def answers(port) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/")
        return connection.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def group_is_gone(panel) -> bool:
    panel.poll()  # a panel not yet waited for would still count as a member
    try:
        os.killpg(panel.pid, 0)
    except (ProcessLookupError, PermissionError):  # a Mac says PermissionError of a group of zombies
        return True
    return False


def stop_group(panel):
    """SIGTERM to the whole group, then SIGKILL to what is left after the grace."""
    for sig, wait in ((signal.SIGTERM, STOP_GRACE), (signal.SIGKILL, 2)):
        if group_is_gone(panel):
            return
        os.killpg(panel.pid, sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and not group_is_gone(panel):
            time.sleep(0.05)


def main() -> int:
    log = open_log()
    os.dup2(log.fileno(), 2)
    sock = choose_socket()
    if sock is None:
        print("PaperPull could not find a free port.", file=sys.stderr)
        return 1
    port = sock.getsockname()[1]
    panel = start_panel(sock, log)

    stop = threading.Event()

    def stop_when_stdin_ends():
        # os.read, as a thread blocked in sys.stdin holds a lock Python aborts on at exit.
        while os.read(0, 4096):
            pass
        stop.set()
    threading.Thread(target=stop_when_stdin_ends, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())

    deadline = time.monotonic() + READY_WITHIN
    ready, status = False, 0
    try:
        while not stop.is_set() and panel.poll() is None:
            if not ready and answers(port):
                ready = True
                os.write(1, b"READY %d\n" % port)  # a window already gone raises, and the finally stops all
            elif not ready and time.monotonic() > deadline:
                print("The panel did not answer within %d seconds." % READY_WITHIN, file=sys.stderr)
                status = 1
                break
            stop.wait(1 if ready else 0.15)
        if panel.poll():  # it ended by itself, and not cleanly
            print("The panel stopped with status %d." % panel.returncode, file=sys.stderr)
            status = 1
    finally:
        stop_group(panel)
    return status


if __name__ == "__main__":
    sys.exit(main())
