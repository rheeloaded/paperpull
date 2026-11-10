"""PaperPull.app stops the panel only once nothing is applying its changes (#141).

The app's window starts gui/mac_host.py, which runs the panel and stops it,
with every run the panel started, once the window goes. A Rename or a Move
applying its changes moves every file and only then writes the index and
progress.json that name them, so the panel lets one finish when its page goes
(FINISHED_WHEN_LEFT), and a stop partway would leave those records naming files
that have moved, for good. So before it stops anything the host asks the
panel's /api/finishing, and waits while the answer names anything.

The host is held here against the real panel served on a port, with the very
functions the app runs, and with stand-ins for the panel process, since a Mac
is the one place it runs whole (core/tests/test_mac_host.py runs it there).
"""
import asyncio
import http.client
import http.server
import importlib.util
import json
import socket
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
def host():
    spec = importlib.util.spec_from_file_location("mac_host_waits", HOST)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def port():
    """The panel, served on a port the system chose, the socket bound here
    and handed over as the host hands over its own."""
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


@pytest.fixture()
def runs(monkeypatch):
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_RUNS", {})
    return app_module._RUNS


def test_nothing_under_way_is_an_empty_answer(host, port, runs):
    assert host.finishing(port) == []


@pytest.mark.parametrize("action", ["rename_apply", "move_documents_apply"])
def test_a_rename_or_a_move_applying_is_named(host, port, runs, action):
    runs[("Shop Docs", "primary")] = {"action": action, "started": ""}
    assert host.finishing(port) == [action]


def test_a_download_moving_its_documents_is_named_as_the_move_it_is(host, port, runs):
    runs[("Shop Docs", "primary")] = {"action": "all", "started": ""}
    assert host.finishing(port) == [], "a download stops and resumes, so the quit stops it"
    runs[("Shop Docs", "primary")]["moving"] = True
    assert host.finishing(port) == ["move_documents_apply"]


def test_a_history_import_is_named(host, port, runs):
    assert app_module._IMPORTING.acquire(blocking=False)
    try:
        assert host.finishing(port) == ["history_import"]
    finally:
        app_module._IMPORTING.release()
    assert host.finishing(port) == []


def test_only_what_moves_files_and_then_writes_its_records_is_named(runs):
    """A download, a Login or a preview may be stopped by a quit, since it
    resumes or is simply run again, and no account is named."""
    for n, action in enumerate(("pilot", "all", "resume", "login", "rename", "move_documents",
                                "verify", "diagnose", "record", "review_names_list")):
        runs[("Shop Docs", "person %d" % n)] = {"action": action, "started": ""}
    assert asyncio.run(app_module.api_finishing()) == {"finishing": []}
    runs[("Shop Docs", "second")] = {"action": "move_documents_apply", "started": ""}
    runs[("Bank Docs", "primary")] = {"action": "rename_apply", "started": ""}
    assert asyncio.run(app_module.api_finishing()) == {"finishing": ["move_documents_apply", "rename_apply"]}
    assert set(app_module.FINISHED_WHEN_LEFT) == {"move_documents_apply", "rename_apply"}


def test_before_the_terms_the_panel_has_started_nothing(host, port, runs, monkeypatch, tmp_path):
    """The route waits for the terms like every route that starts a run, and
    the host reads that refusal as nothing under way rather than wait for an
    answer, so a quit before I understand is pressed is not held."""
    monkeypatch.setattr(app_module, "_TERMS_TAKEN", False)
    monkeypatch.setattr(app_module, "_settings_path", lambda: tmp_path / "settings.json")
    assert app_module.terms_due()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/api/finishing")
    answer = connection.getresponse()
    said = json.loads(answer.read())
    connection.close()
    assert answer.status == 409 and said["detail"].startswith(host.TERMS_FIRST), said
    assert host.finishing(port) == []


def test_the_route_is_the_desktops_alone(monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    route = next(r for r in app_module.app.routes if getattr(r, "path", "") == "/api/finishing")
    calls = {d.call for d in route.dependant.dependencies}
    assert {app_module._same_origin_only, app_module._terms_first, app_module._desktop_only} <= calls
    with pytest.raises(app_module.HTTPException) as e:
        app_module._desktop_only()
    assert e.value.status_code == 404


# -- answers that are not the panel's -----------------------------------------------------

class _Answer(http.server.BaseHTTPRequestHandler):
    status, body = 200, b""

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def stand_in():
    """Something else answering on a port, with whatever it is set to say."""
    servers = []

    def serve(status, body):
        handler = type("Said", (_Answer,), {"status": status, "body": body})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]
    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("status,body", [
    (200, b"<html>"), (200, b'{"finishing": null}'), (200, b"[]"), (200, b""),
    (403, b'{"finishing": []}'), (404, b'{"detail": "Not Found"}'),
    (409, b'{"detail": "This is the sample archive. Leave the sample first."}'),
    (500, b'{"finishing": []}')])
def test_any_other_answer_is_no_answer(host, stand_in, status, body):
    """No answer is asked again, and never taken for nothing under way."""
    assert host.finishing(stand_in(status, body)) is None


def test_a_closed_port_is_no_answer(host):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    assert host.finishing(closed) is None


# -- the wait --------------------------------------------------------------------------------

class Panel:
    """A panel process that goes on until it is stopped."""

    def __init__(self):
        self.pid, self.returncode = 4321, None

    def poll(self):
        return self.returncode


class Clock:
    """The host's time, which passes only when the host sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.strftime = time.strftime

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture()
def clock(host, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(host, "time", clock)
    return clock


def test_the_quit_waits_while_anything_is_named_and_says_why_once(host, clock, monkeypatch, capfd):
    answers = [["rename_apply"]] * 40 + [[]]
    monkeypatch.setattr(host, "finishing", lambda port: answers.pop(0))
    assert host.wait_for_what_must_finish(Panel(), 8765) is True
    assert answers == []
    out, err = capfd.readouterr()
    assert out == "FINISHING\n", "the window is told once"
    assert err.count("once rename_apply has finished") == 1, err


def test_a_panel_that_gives_no_answer_is_stopped_after_a_while(host, clock, monkeypatch, capfd):
    asked = []
    monkeypatch.setattr(host, "finishing", lambda port: asked.append(clock.now) or None)
    assert host.wait_for_what_must_finish(Panel(), 8765) is False
    waited = asked[-1] - asked[0]
    assert host.UNANSWERED_FOR <= waited <= host.UNANSWERED_FOR + 1, waited
    out, err = capfd.readouterr()
    assert out == "" and "did not say for 30 seconds" in err


def test_an_answer_now_and_then_keeps_the_wait_going(host, clock, monkeypatch):
    """A busy panel that answers between silences is still waited for."""
    answers = ([None] * 100 + [["move_documents_apply"]]) * 3 + [[]]
    monkeypatch.setattr(host, "finishing", lambda port: answers.pop(0))
    assert host.wait_for_what_must_finish(Panel(), 8765) is True
    assert answers == []


def test_a_panel_that_ends_has_nothing_left_to_wait_for(host, clock, monkeypatch):
    panel = Panel()

    def named(port):
        panel.returncode = 0
        return ["rename_apply"]
    monkeypatch.setattr(host, "finishing", named)
    assert host.wait_for_what_must_finish(panel, 8765) is True


def _ran(host, monkeypatch, *, ready=True, names=([],)):
    """run_panel with a panel that answers when ready is true, a window that
    goes once READY is said, and what each step did, in order."""
    did = []
    stop = threading.Event()
    panel = Panel()
    names = list(names)
    monkeypatch.setattr(host, "answers", lambda port: ready)
    monkeypatch.setattr(host, "READY_WITHIN", 0.2)

    def finishing(port):
        did.append(("asked", names[0]))
        return names.pop(0)

    def stop_group(p):
        did.append(("stopped", p.pid))
        p.returncode = -15
    monkeypatch.setattr(host, "finishing", finishing)
    monkeypatch.setattr(host, "stop_group", stop_group)
    clock = Clock()
    clock.sleep = lambda seconds: None
    clock.monotonic = time.monotonic
    monkeypatch.setattr(host, "time", clock)

    def write_line(line):
        did.append(("told", line))
        stop.set()  # the window goes as soon as it has shown the panel
    monkeypatch.setattr(host, "write_line", write_line)
    return host.run_panel(panel, 8765, stop), did


def test_the_panel_is_stopped_only_after_nothing_is_named(host, monkeypatch):
    status, did = _ran(host, monkeypatch, names=(["rename_apply"], ["rename_apply"], []))
    assert status == 0
    assert did == [("told", "READY 8765"),
                   ("asked", ["rename_apply"]), ("told", "FINISHING"),
                   ("asked", ["rename_apply"]), ("asked", []), ("stopped", 4321)]


def test_a_panel_that_never_answered_is_stopped_without_asking(host, monkeypatch):
    status, did = _ran(host, monkeypatch, ready=False)
    assert status == 1
    assert did == [("stopped", 4321)], "a panel that never answered has started nothing"


def test_the_panel_keeps_no_access_log(host, monkeypatch, tmp_path):
    """panel.log is the file a person attaches to an issue, and an access log
    names every provider and person in its query strings."""
    seen = {}

    def popen(cmd, **kwargs):
        seen["cmd"] = cmd
        return Panel()
    monkeypatch.setattr(host.subprocess, "Popen", popen)
    with socket.socket() as sock:
        host.start_panel(sock, None)
    cmd = seen["cmd"]
    assert cmd[1:4] == ["-m", "uvicorn", "app:app"] and "--no-access-log" in cmd
    assert "--access-log" not in cmd
