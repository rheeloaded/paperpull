"""Runs the panel for PaperPull.app's window, and stops it when the window goes.

The window (packaging/macos/launcher.m) starts this with the bundled Python and
keeps its stdin open. It tells the window two things on stdout, a "READY <port>"
line once GET / answers 200, and a "FINISHING" line when the window has gone
but something is still applying its changes, and ends with status 0 when the
panel was stopped on purpose and 1 when it failed. Why it failed is in the log.

stdin reaching its end is the signal to stop. The system closes it however the
window ends, a crash included. A Rename or a Move applying its changes moves
every file and only then writes the index and progress.json that name them, so
before it stops anything the host asks the panel's /api/finishing until it
names nothing, and only then stops the panel. Until then the panel goes on with
no window, and the log says why.

The panel starts the runs in a process group of its own, and the whole group is
stopped, so no run outlives it. The browser a run opens for sign-in is not in
the group, since core's browser.py starts it in a session of its own, and it
stays open with the person's sign-in in it.

Nothing is stopped that this did not start. When 8765 is held by this person's
own PaperPull panel, one started from a terminal, say, the window shows that one,
since a second panel would write one account's records beside it, and closing
the window leaves it running.
"""
import errno
import http.client
import json
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
# How often a quit asks what is applying its changes, and how long a panel that
# gives no answer is waited for before it is stopped anyway.
FINISHING_EVERY = 0.25
UNANSWERED_FOR = 30
# How long a panel already on the usual port is given to answer as one.
HELD_ANSWERS_WITHIN = 10
# Where macOS keeps lsof, which says whose process holds a port.
LSOF = "/usr/sbin/lsof"
# What the panel's own page says of itself, the desktop edition's.
PANEL_MARKS = (b"<title>PaperPull</title>", b"const SERVER = false;")
PAGE_LIMIT = 8 * 1024 * 1024
# The start of what the panel says while the terms of use wait to be accepted.
TERMS_FIRST = "Accept the Terms of Use first"


def note(text):
    """A line in the log, which stderr is once main() has begun."""
    print("%s PaperPull.app: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text), file=sys.stderr, flush=True)


def write_line(line):
    """A line for the window on stdout. OSError when the window has gone."""
    os.write(1, line.encode("ascii") + b"\n")


def tell_window(line) -> bool:
    """A line for the window, False when it has gone, which is no reason to stop."""
    try:
        write_line(line)
        return True
    except OSError:
        return False


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


def desktop_panel_on(port, within=HELD_ANSWERS_WITHIN):
    """True when what listens on the port answers GET / with PaperPull's own
    desktop page, False when it answers with anything else, and None when it
    gives no answer in time. PaperPull Server's page says it is the server,
    and its folder is not this person's, so it is not taken for one."""
    deadline = time.monotonic() + within
    while True:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            page = response.read(PAGE_LIMIT)
            return response.status == 200 and all(mark in page for mark in PANEL_MARKS)
        except (OSError, http.client.HTTPException):
            if time.monotonic() > deadline:
                return None
        finally:
            connection.close()
        time.sleep(0.5)


def own_listener(port):
    """The pid of one of this person's own processes listening on the port, or
    None when none of theirs is. lsof is told to look at this person's processes
    alone. OSError or SubprocessError when lsof cannot say."""
    done = subprocess.run([LSOF, "-nP", "-a", "-u", str(os.getuid()), "-iTCP:%d" % port, "-sTCP:LISTEN", "-Fp"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    pids = [int(line[1:]) for line in done.stdout.splitlines() if line[:1] == "p" and line[1:].isdigit()]
    if pids:
        return pids[0]
    if done.returncode == 1 and not done.stdout.strip():
        return None  # lsof's way of saying it found nothing
    raise OSError("lsof ended with status %d: %s" % (done.returncode, done.stderr.strip()[:200]))


def choose_socket():
    """Where the panel is, as (socket, port) for one to start on that socket,
    (None, port) for this person's own panel already running there, which the
    window shows and nothing here stops, or None when there is neither.

    PAPERPULL_PORT if it is set, for tests, else the usual port. When the usual
    port is held, by another program or by another person's panel, which keeps
    a folder of its own, any free port. But this person's own panel there is
    shown rather than a second one started, and when whose it is cannot be
    told, nothing is started."""
    wanted = os.environ.get("PAPERPULL_PORT", "")
    if wanted.isdigit() and 0 < int(wanted) < 65536:
        sock = listen_on(int(wanted))
        return (sock, int(wanted)) if sock else None
    sock = listen_on(USUAL_PORT)
    if sock is not None:
        return sock, USUAL_PORT
    panel = desktop_panel_on(USUAL_PORT)
    if panel is False:
        sock = listen_on(0)
        return (sock, sock.getsockname()[1]) if sock else None
    try:
        mine = own_listener(USUAL_PORT) is not None
    except (OSError, subprocess.SubprocessError) as e:
        note("Port %d is held, and whose it is could not be told (%s), so no second panel is started."
             % (USUAL_PORT, e))
        return None
    if not mine:
        sock = listen_on(0)
        return (sock, sock.getsockname()[1]) if sock else None
    if panel is None:
        note("A program of yours holds port %d and does not answer. If it is PaperPull's control panel, "
             "stop it and open PaperPull again. No second panel is started, since two would write one "
             "account's records at once." % USUAL_PORT)
        return None
    note("PaperPull's control panel is already running at http://127.0.0.1:%d, started outside this "
         "window, so the window shows that one and leaves it running when it closes." % USUAL_PORT)
    return None, USUAL_PORT


def start_panel(sock, log):
    gui = Path(__file__).resolve().parent
    resources = gui.parent
    env = dict(os.environ, PYTHONNOUSERSITE="1",
               # Never into the bundle, which a signature covers.
               PYTHONPYCACHEPREFIX=str(Path.home() / "Library" / "Caches" / "PaperPull" / "pycache"),
               # So the panel can bring this window back after a sign-in.
               PAPERPULL_APP_PATH=str(resources.parents[1]))
    fd = sock.fileno()
    # No access log. panel.log is the file a person is pointed to when
    # something goes wrong, and one line per request with its query string
    # would list there every provider they use and every person they added.
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--fd", str(fd), "--no-access-log", "--app-dir", str(gui)],
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


def finishing(port):
    """What the panel's /api/finishing names as applying its changes, a list,
    or None when it gives no answer that can be read.

    The route waits for the terms of use, and so does every route that starts
    a run, so a panel that refuses it for the terms has started nothing."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/finishing")
        response = connection.getresponse()
        said = json.loads(response.read(PAGE_LIMIT) or b"null")
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        connection.close()
    if not isinstance(said, dict):
        return None
    if response.status == 409 and str(said.get("detail", "")).startswith(TERMS_FIRST):
        return []
    names = said.get("finishing") if response.status == 200 else None
    return names if isinstance(names, list) else None


def wait_for_what_must_finish(panel, port) -> bool:
    """Returns once the panel names nothing applying its changes, or has ended,
    True then, or False once it has given no answer for UNANSWERED_FOR seconds.
    The log and the window are told once why the quit waits."""
    told = False
    silent_since = None
    while panel.poll() is None:
        names = finishing(port)
        if names == []:
            return True
        if names is None:
            if silent_since is None:
                silent_since = time.monotonic()
            elif time.monotonic() - silent_since > UNANSWERED_FOR:
                note("The panel did not say for %d seconds whether a Rename or a Move is applying its "
                     "changes, so it is stopped." % UNANSWERED_FOR)
                return False
        else:
            silent_since = None
            if not told:
                told = True
                note("The panel is stopped once %s has finished, since a Rename or a Move stopped partway "
                     "would leave its records naming files that have moved."
                     % ", ".join(str(n) for n in names))
                tell_window("FINISHING")
        time.sleep(FINISHING_EVERY)
    return True


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


def nobody_listens(port) -> bool:
    """True only when the port refuses a connection, which a busy panel never does."""
    with socket.socket() as probe:
        probe.settimeout(5)
        return probe.connect_ex(("127.0.0.1", port)) in (errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", -1))


def show_own_panel(port, stop) -> int:
    """This person's own panel, already running, shown in the window and never
    stopped from here. 1 once it has gone, so the window offers to start one."""
    if not tell_window("READY %d" % port):
        return 0
    while not stop.is_set():
        if nobody_listens(port):
            note("The control panel at http://127.0.0.1:%d has stopped." % port)
            return 1
        stop.wait(1)
    note("The window has closed. The control panel it showed was started elsewhere and keeps running.")
    return 0


def run_panel(panel, port, stop) -> int:
    """The panel this started, told to the window once it answers, and stopped,
    with all it started, once the window goes and nothing is applying its
    changes, or once it has failed."""
    deadline = time.monotonic() + READY_WITHIN
    ready, status = False, 0
    try:
        while not stop.is_set() and panel.poll() is None:
            if not ready and answers(port):
                ready = True
                write_line("READY %d" % port)  # a window already gone raises, and the finally stops all
            elif not ready and time.monotonic() > deadline:
                note("The panel did not answer within %d seconds." % READY_WITHIN)
                status = 1
                break
            stop.wait(1 if ready else 0.15)
        if panel.poll():  # it ended by itself, and not cleanly
            note("The panel stopped with status %d." % panel.returncode)
            status = 1
        elif ready and panel.poll() is None:
            # A panel that never answered has started nothing.
            wait_for_what_must_finish(panel, port)
    finally:
        stop_group(panel)
    return status


def stop_when_told(stop):
    """stdin reaching its end, or a signal, sets stop."""
    def stdin_ends():
        # os.read, as a thread blocked in sys.stdin holds a lock Python aborts on at exit.
        while os.read(0, 4096):
            pass
        stop.set()
    threading.Thread(target=stdin_ends, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())


def main() -> int:
    log = open_log()
    os.dup2(log.fileno(), 2)
    stop = threading.Event()
    stop_when_told(stop)
    found = choose_socket()
    if found is None:
        note("PaperPull could not find a port for its control panel.")
        return 1
    sock, port = found
    if sock is None:
        return show_own_panel(port, stop)
    return run_panel(start_panel(sock, log), port, stop)


if __name__ == "__main__":
    sys.exit(main())
