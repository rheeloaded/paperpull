"""The panel as PaperPull Server runs it, on the network behind a password.

The real panel is served on a local port by uvicorn, as the server image
serves it, and asked for things the way a browser on the home network
would ask. PAPERPULL_SERVER=1 switches the server's behavior on for a
test, and without it the panel is the desktop panel it always was.

Everything the panel reads or writes is under a throwaway folder, the
apps root, the settings, the server's password file and noVNC's files.
"""
import asyncio
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
import server_mode  # noqa: E402

PASSWORD = "an invented passphrase"


@pytest.fixture(scope="module")
def base():
    """The panel, served on a free local port for the whole module."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


@pytest.fixture(autouse=True)
def own_folders(tmp_path, monkeypatch):
    """Every place the panel might read or write is under tmp_path, and
    nothing of the server's is left from another test."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    (tmp_path / "apps").mkdir()
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    monkeypatch.delenv("PAPERPULL_PASSWORD", raising=False)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    server_mode._SESSIONS.clear()
    server_mode._FAILS.clear()
    server_mode._SETUP["code"] = None
    yield


@pytest.fixture()
def on_server(monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def ask(url, method="GET", form=None, headers=None, session=None):
    """(status, headers, body) for one request, redirects not followed."""
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if session:
        req.add_header("Cookie", "%s=%s" % (server_mode.SESSION_COOKIE, session))
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def session_from(headers) -> str:
    for value in headers.get_all("Set-Cookie") or []:
        name, _, rest = value.partition("=")
        if name == server_mode.SESSION_COOKIE:
            return rest.split(";")[0]
    return ""


def signed_in(base) -> str:
    server_mode.set_password(PASSWORD)
    status, headers, _ = ask(base + "/login", "POST", {"password": PASSWORD})
    assert status == 303, status
    return session_from(headers)


# -- the desktop panel is untouched ------------------------------------------------

def test_off_the_server_nothing_changes(base):
    status, _, page = ask(base + "/")
    assert status == 200 and 'class="serverbar"' not in page and "__SERVER_BAR__" not in page
    assert 'action="/logout"' not in page
    assert ask(base + "/login")[0] == 404
    assert ask(base + "/setup")[0] == 404
    assert ask(base + "/screen")[0] == 404
    assert ask(base + "/api/apps")[0] == 200


# -- the first visit -----------------------------------------------------------------

def test_with_no_password_everything_leads_to_choosing_one(base, on_server):
    status, headers, _ = ask(base + "/")
    assert status == 303 and headers["Location"] == "/setup"
    assert ask(base + "/api/apps")[0] == 401
    assert ask(base + "/favicon.ico")[0] == 200
    status, _, page = ask(base + "/setup")
    assert status == 200 and "Setup code" in page


def test_choosing_it_takes_the_code_from_the_log(base, on_server):
    ask(base + "/setup")
    code = server_mode._SETUP["code"]
    assert code

    wrong = ask(base + "/setup", "POST", {"code": "AAAA-BBBB-CCCC", "password": PASSWORD,
                                          "again": PASSWORD})
    assert wrong[0] == 401 and not server_mode.password_set()
    short = ask(base + "/setup", "POST", {"code": code, "password": "short", "again": "short"})
    assert short[0] == 400 and not server_mode.password_set()
    apart = ask(base + "/setup", "POST", {"code": code, "password": PASSWORD,
                                          "again": PASSWORD + "!"})
    assert apart[0] == 400 and not server_mode.password_set()

    status, headers, _ = ask(base + "/setup", "POST",
                             {"code": code.lower(), "password": PASSWORD, "again": PASSWORD})
    assert status == 303 and headers["Location"] == "/"
    cookie = [v for v in headers.get_all("Set-Cookie") if v.startswith("paperpull_session=")][0]
    assert "HttpOnly" in cookie and "samesite=strict" in cookie.lower()
    assert ask(base + "/", session=session_from(headers))[0] == 200
    # Once chosen, the setup page is gone and the code with it.
    assert ask(base + "/setup")[1]["Location"] == "/login"
    assert server_mode._SETUP["code"] is None


def test_the_password_is_kept_only_as_a_hash(base, on_server, tmp_path):
    server_mode.set_password(PASSWORD)
    raw = (tmp_path / "config" / "server.json").read_text(encoding="utf-8")
    assert PASSWORD not in raw
    kept = json.loads(raw)["password"]
    assert set(kept) == {"scrypt", "salt", "hash"} and len(kept["hash"]) == 64
    if os.name != "nt":
        assert (tmp_path / "config" / "server.json").stat().st_mode & 0o077 == 0


def test_a_password_from_the_environment_is_taken_at_start(on_server, monkeypatch):
    monkeypatch.setenv("PAPERPULL_PASSWORD", PASSWORD)
    server_mode.on_start()
    assert server_mode.password_set() and server_mode.check_password(PASSWORD)
    assert server_mode._SETUP["code"] is None


def test_a_short_one_from_the_environment_is_not(on_server, monkeypatch, capsys):
    monkeypatch.setenv("PAPERPULL_PASSWORD", "short")
    server_mode.on_start()
    assert not server_mode.password_set()
    assert server_mode._SETUP["code"] and server_mode._SETUP["code"] in capsys.readouterr().out


# -- signing in ----------------------------------------------------------------------

def test_signing_in_and_out(base, on_server):
    server_mode.set_password(PASSWORD)
    status, headers, _ = ask(base + "/")
    assert status == 303 and headers["Location"] == "/login"
    assert ask(base + "/login", "POST", {"password": "not it at all"})[0] == 401

    session = signed_in(base)
    status, _, page = ask(base + "/", session=session)
    assert status == 200 and 'href="/screen"' in page and 'action="/logout"' in page
    assert ask(base + "/api/apps", session=session)[0] == 200

    status, headers, _ = ask(base + "/logout", "POST", session=session)
    assert status == 303 and headers["Location"] == "/login"
    assert ask(base + "/", session=session)[0] == 303


def test_wrong_passwords_make_an_address_wait(base, on_server):
    server_mode.set_password(PASSWORD)
    for _ in range(server_mode.FREE_TRIES):
        assert ask(base + "/login", "POST", {"password": "a wrong guess"})[0] == 401
    status, _, page = ask(base + "/login", "POST", {"password": PASSWORD})
    assert status == 429 and "Try again in" in page


def test_a_new_password_signs_every_session_out(base, on_server):
    session = signed_in(base)
    server_mode.set_password(PASSWORD + " again")
    assert ask(base + "/", session=session)[0] == 303


# -- requests from somewhere else ---------------------------------------------------

def test_another_sites_request_is_refused_even_signed_in(base, on_server):
    session = signed_in(base)
    host = base.split("//")[1]
    assert ask(base + "/api/apps", session=session,
               headers={"Origin": "http://elsewhere.example"})[0] == 403
    assert ask(base + "/api/apps", session=session,
               headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert ask(base + "/api/apps", session=session,
               headers={"Origin": "http://" + host, "Sec-Fetch-Site": "same-origin"})[0] == 200
    assert ask(base + "/login", "POST", {"password": PASSWORD},
               headers={"Origin": "http://elsewhere.example"})[0] == 403


def test_what_only_means_something_on_a_desktop_is_not_offered(base, on_server):
    session = signed_in(base)
    for path in ("/api/root", "/api/export/reveal", "/api/failure/reveal"):
        assert ask(base + path, "POST", {}, session=session)[0] == 404, path


# -- the browser screen ------------------------------------------------------------------

def test_the_screen_is_behind_the_password(base, on_server, tmp_path, monkeypatch):
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text("<title>noVNC</title>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not noVNC's", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    server_mode.set_password(PASSWORD)

    assert ask(base + "/screen")[0] == 303
    assert ask(base + "/screen/novnc/vnc.html")[0] == 303

    session = signed_in(base)
    status, _, page = ask(base + "/screen", session=session)
    assert status == 200 and "path=screen/websockify" in page and "/favicon.ico" in page
    assert ask(base + "/screen/novnc/vnc.html", session=session)[2] == "<title>noVNC</title>"
    assert ask(base + "/screen/novnc/%2e%2e/secret.txt", session=session)[0] == 404


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_screen_connection_needs_a_session_from_the_panels_own_page(on_server):
    server_mode.set_password(PASSWORD)
    token = server_mode.new_session()
    passed = []

    async def inner(scope, receive, send):
        passed.append(scope["path"])

    async def attempt(headers):
        sent = []

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        scope = {"type": "websocket", "path": "/screen/websockify",
                 "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
        await server_mode.SignInGate(inner)(scope, receive, send)
        return sent

    host = {"host": "nas.local:8765"}
    assert run(attempt(host)) == [{"type": "websocket.close", "code": 1008}]
    cookie = {"cookie": "%s=%s" % (server_mode.SESSION_COOKIE, token)}
    other = dict(host, origin="http://elsewhere.example", **cookie)
    assert run(attempt(other)) == [{"type": "websocket.close", "code": 1008}]
    assert not passed
    own = dict(host, origin="http://nas.local:8765", **cookie)
    assert run(attempt(own)) == [] and passed == ["/screen/websockify"]


def test_the_screen_bridge_carries_bytes_both_ways():
    """The page's messages reach the screen sharing server as they are, and
    what the server sends comes back as binary messages, until the page
    goes."""
    async def scenario():
        got_by_server = []

        async def fake_server(reader, writer):
            writer.write(b"RFB 003.008\n")
            await writer.drain()
            got_by_server.append(await reader.read(100))
            writer.close()

        server = await asyncio.start_server(fake_server, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        to_page = []
        messages = asyncio.Queue()
        await messages.put({"type": "websocket.receive", "bytes": b"RFB 003.008\n"})

        async def receive():
            return await messages.get()

        async def send_bytes(data):
            to_page.append(data)

        await asyncio.wait_for(server_mode.bridge(receive, send_bytes, reader, writer), 10)
        server.close()
        return got_by_server, to_page

    got_by_server, to_page = run(scenario())
    assert got_by_server == [b"RFB 003.008\n"]
    assert b"".join(to_page) == b"RFB 003.008\n"
