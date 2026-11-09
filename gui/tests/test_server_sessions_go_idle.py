"""PaperPull Server's sessions end once nobody uses them, the Browser Screen
sooner, and wrong passwords behind the HTTPS proxy count against the
browser that sent them.

A session lasted 14 days whether anyone used it or not, so a browser left
signed in on a computer in the house stayed signed in for two weeks, and
the Browser Screen it could open is live keyboard and mouse on every bank
signed in there. A session the panel's own page asks nothing of for
IDLE_SECONDS ends now. The Browser Screen opens and stays open only within
SCREEN_IDLE_SECONDS of someone seen there, the password typed, its page
opened or a key or the mouse on it, and asks for the password again after
that, with the reason shown. The panel's requests count for nothing there,
since its page makes some by itself, the next run of Run All among them,
and nor does noVNC connecting again by itself. Independent reviews found
that both kept the screen open with nobody at the keyboard.

Behind compose.https.yaml every request comes from the proxy's address,
so the proxy is named in PAPERPULL_PROXY and its X-Forwarded-For is what
a wrong password counts against. Without that, five wrong passwords from
anyone on the network would make the owner wait too.

Each request goes to the app in this process, with every setting under a
temp folder. Time is moved by setting a session's own times back, never
by waiting.
"""
import asyncio
import socket
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import server_mode  # noqa: E402

PASSWORD = "an invented passphrase"
HOST = "nas.local:8765"


@pytest.fixture(autouse=True)
def server(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    (tmp_path / "apps").mkdir()
    (tmp_path / "novnc" / "app").mkdir(parents=True)
    (tmp_path / "novnc" / "vnc.html").write_text("<title>noVNC</title>", encoding="utf-8")
    (tmp_path / "novnc" / "app" / "ui.js").write_text("// noVNC", encoding="utf-8")
    monkeypatch.setenv("APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    for name in ("PAPERPULL_PASSWORD", "PAPERPULL_HOSTS", "PAPERPULL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(server_mode, "_PROXY", {"name": "", "addresses": frozenset(), "until": 0.0})
    server_mode._SESSIONS.clear()
    server_mode._FAILS.clear()
    server_mode._SETUP["code"] = None
    server_mode.set_password(PASSWORD)
    yield


def scope_for(kind, method, target, headers, client="127.0.0.1"):
    path, _, query = target.partition("?")
    return {"type": kind, "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": method, "scheme": "http" if kind == "http" else "ws",
            "path": path, "raw_path": path.encode(), "query_string": query.encode(),
            "root_path": "", "client": (client, 50000), "server": ("127.0.0.1", 8765),
            "subprotocols": ["binary"],
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers]}


def own_page(token="", method="GET", origin="http://%s" % HOST):
    headers = [("host", HOST), ("sec-fetch-site", "same-origin"),
               ("referer", "%s/" % origin)]
    if method != "GET":
        headers.append(("origin", origin))
    if token:
        headers.append(("cookie", "%s=%s" % (server_mode.SESSION_COOKIE, token)))
    return headers


def ask(method, target, token="", form=None, client="127.0.0.1", extra=(), headers=None,
        **page):
    """(status, headers, body) of one request, sent as the panel's page sends
    it, or with the headers given."""
    headers = (own_page(token, method, **page) if headers is None else list(headers)) + list(extra)
    body = b""
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers += [("content-type", "application/x-www-form-urlencoded"),
                    ("content-length", str(len(body)))]
    answer = {"status": None, "headers": [], "body": b""}

    async def scenario():
        ended = asyncio.Event()
        told = []

        async def receive():
            if not told:
                told.append(True)
                return {"type": "http.request", "body": body, "more_body": False}
            await ended.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                answer["status"] = message["status"]
                answer["headers"] = [(k.decode("latin-1").lower(), v.decode("latin-1"))
                                     for k, v in message.get("headers") or []]
            elif message["type"] == "http.response.body":
                answer["body"] += message.get("body", b"")
                if not message.get("more_body"):
                    ended.set()

        await asyncio.wait_for(app_module.app(scope_for("http", method, target, headers, client),
                                              receive, send), 30)

    asyncio.run(scenario())
    return answer["status"], dict(answer["headers"]), answer["body"].decode("utf-8", "replace")


def set_back(token, field, seconds):
    server_mode._SESSIONS[token][field] -= seconds


# -- the panel's session ----------------------------------------------------------------

def test_a_session_nobody_uses_ends_after_the_idle_limit():
    token = server_mode.new_session()
    assert ask("GET", "/api/apps", token)[0] == 200
    set_back(token, "used", server_mode.IDLE_SECONDS + 1)
    status, headers, _ = ask("GET", "/api/apps", token)
    assert status == 401
    assert token not in server_mode._SESSIONS
    status, headers, _ = ask("GET", "/", token)
    assert status == 303 and headers["location"] == "/login"


def test_using_a_session_keeps_it_going():
    token = server_mode.new_session()
    for _ in range(3):
        set_back(token, "used", server_mode.IDLE_SECONDS - 60)
        assert ask("GET", "/api/apps", token)[0] == 200
        assert time.time() - server_mode._SESSIONS[token]["used"] < 30


def test_a_session_used_all_along_still_ends_at_its_longest():
    token = server_mode.new_session()
    set_back(token, "ends", server_mode.SESSION_SECONDS + 1)
    assert ask("GET", "/api/apps", token)[0] == 401


def test_the_limits_are_the_ones_chosen():
    """Eight hours, so a visit to the NAS every few days signs in once, and
    a quarter of an hour for live control of the providers."""
    assert server_mode.SESSION_SECONDS == 14 * 86400
    assert server_mode.IDLE_SECONDS == 8 * 3600
    assert server_mode.SCREEN_IDLE_SECONDS == 15 * 60
    assert server_mode.SCREEN_IDLE_SECONDS < server_mode.IDLE_SECONDS < server_mode.SESSION_SECONDS


# -- the Browser Screen asks for the password again ------------------------------------

def test_the_screen_opens_right_after_the_password():
    token = server_mode.new_session()
    status, _, page = ask("GET", "/screen", token)
    assert status == 200 and "path=screen/websockify" in page
    assert ask("GET", "/screen/novnc/vnc.html", token)[2] == "<title>noVNC</title>"


def test_after_a_gap_the_screen_asks_for_the_password_again():
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    status, headers, page = ask("GET", "/screen", token)
    assert status == 200 and 'action="/screen/again"' in page
    assert 'name="to" value="screen"' in page and "path=screen/websockify" not in page
    assert headers["cache-control"] == "no-store"
    # The page the panel docks asks too, in the frame the panel shows it in.
    status, headers, page = ask("GET", "/screen/novnc/vnc.html", token)
    assert status == 200 and 'name="to" value="dock"' in page and "noVNC" not in page
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["cache-control"] == "no-store"
    # noVNC's other files are no secret, and are served as they are.
    assert ask("GET", "/screen/novnc/app/ui.js", token)[2] == "// noVNC"
    # The panel itself goes on working.
    assert ask("GET", "/api/apps", token)[0] == 200


def test_clicking_in_the_panel_after_the_gap_does_not_open_the_screen():
    """Whoever sits down at a computer left signed in can use the panel
    until the session's own limit, never the screen without the password."""
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    for _ in range(3):
        assert ask("GET", "/api/apps", token)[0] == 200
    assert not server_mode.screen_open(token)
    assert 'action="/screen/again"' in ask("GET", "/screen", token)[2]


def test_the_panels_own_requests_never_keep_the_screen_open():
    """Run All starts its next run by itself, and every run's end asks for
    the accounts again, so a person who started a round and walked away
    left the panel asking every few minutes. Those kept the screen open to
    whoever sat down, for as long as the round went on."""
    token = server_mode.new_session()
    for _ in range(18):
        set_back(token, "screen", 600)
        set_back(token, "used", 600)
        assert ask("GET", "/api/apps", token)[0] == 200
    assert server_mode.session_valid(token) and not server_mode.screen_open(token)
    assert 'action="/screen/again"' in ask("GET", "/screen", token)[2]
    # Within the quarter hour, it is the password that keeps it, not them.
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS - 30)
    before = server_mode._SESSIONS[token]["screen"]
    assert ask("GET", "/api/apps", token)[0] == 200
    assert server_mode._SESSIONS[token]["screen"] == before and server_mode.screen_open(token)


def test_another_programs_page_on_the_same_machine_does_not_keep_the_session():
    """A page of another program on the NAS, at another port, is the same
    site to the browser, which sends the panel's cookie with an image that
    page asks for. That kept the session from going idle."""
    token = server_mode.new_session()
    set_back(token, "used", 3600)
    before = server_mode._SESSIONS[token]["used"]
    cookie = ("cookie", "%s=%s" % (server_mode.SESSION_COOKIE, token))
    image = [("host", HOST), ("sec-fetch-site", "same-site"), ("sec-fetch-dest", "image"),
             ("referer", "http://nas.local:5000/"), cookie]
    ask("GET", "/favicon.ico", headers=image)
    assert server_mode._SESSIONS[token]["used"] == before
    # An address the browser opened by itself, typed or from a bookmark, is use.
    ask("GET", "/", headers=[("host", HOST), ("sec-fetch-site", "none"), cookie])
    assert time.time() - server_mode._SESSIONS[token]["used"] < 30


@pytest.mark.parametrize("to, goes", [
    ("dock", server_mode.NOVNC_PAGE), ("screen", "/screen"), ("https://elsewhere.example", "/screen")])
def test_the_password_typed_again_opens_the_screen(to, goes):
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    status, headers, _ = ask("POST", "/screen/again", token, {"password": PASSWORD, "to": to})
    assert status == 303 and headers["location"] == goes
    assert server_mode.screen_open(token)
    assert "path=screen/websockify" in ask("GET", "/screen", token)[2]


def test_a_wrong_password_typed_again_counts_and_waits():
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    for _ in range(server_mode.FREE_TRIES):
        status, headers, page = ask("POST", "/screen/again", token,
                                    {"password": "not it", "to": "dock"})
        assert status == 401 and "That is not the password." in page
        assert 'name="to" value="dock"' in page
        assert headers["x-frame-options"] == "SAMEORIGIN"
    status, _, page = ask("POST", "/screen/again", token, {"password": PASSWORD, "to": "dock"})
    assert status == 429 and "Too many wrong passwords" in page
    assert not server_mode.screen_open(token)


def test_the_password_again_is_asked_only_by_the_panels_own_page():
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    status, _, page = ask("POST", "/screen/again", token, {"password": PASSWORD},
                          origin="https://elsewhere.example")
    assert status == 403 and not server_mode.screen_open(token)
    assert 'name="to" value="screen"' in page
    # Refused in the panel's docked window, the form it shows again goes
    # back there, never to the screen's own tab, which no frame may show.
    status, _, page = ask("POST", "/screen/again", token, {"password": PASSWORD},
                          origin="https://elsewhere.example", extra=[("sec-fetch-dest", "iframe")])
    assert status == 403 and 'name="to" value="dock"' in page


# -- an open screen ---------------------------------------------------------------------

KEY = bytes([4, 1, 0, 0, 0, 0, 0, 0x61])
POINTER = bytes([5, 0, 0, 10, 0, 20])
PICTURE = bytes([3, 1, 0, 0, 0, 0, 6, 64, 3, 232])


def test_what_noVNC_sends_is_told_apart():
    assert server_mode.person_in(KEY) and server_mode.person_in(POINTER)
    assert server_mode.person_in(bytes([255, 0]) + bytes(10))
    # The clipboard, which noVNC sends by itself in answer to the screen's,
    # in its extension's form with a length less than nothing, as measured
    # from a real noVNC at the start of a connection, and plainly.
    caps = bytes([6, 0, 0, 0, 0xFF, 0xFF, 0xFF, 0xF8]) + bytes([0x1F, 0, 0, 1]) + bytes(4)
    assert not server_mode.person_in(caps) and server_mode.person_in(caps + KEY)
    paste = bytes([6, 0, 0, 0, 0, 0, 0, 2]) + b"hi"
    assert not server_mode.person_in(paste) and server_mode.person_in(paste + POINTER)
    assert not server_mode.person_in(PICTURE)
    assert not server_mode.person_in(bytes([255, 1]) + bytes(10))
    # The protocol's opening, its version, the way in and the start.
    for opening in (b"RFB 003.008\n", b"\x01", b"\x00"):
        assert not server_mode.person_in(opening), opening
    # Its settings, then a key, read message by message.
    encodings = bytes([2, 0, 0, 2]) + bytes(8)
    assert not server_mode.person_in(encodings) and server_mode.person_in(encodings + KEY)
    assert server_mode.person_in(PICTURE + POINTER) and server_mode.person_in(KEY + PICTURE)
    assert not server_mode.person_in(bytes([0]) + bytes(19) + PICTURE)
    fence = bytes([248, 0, 0, 0, 0, 0, 0, 0, 3]) + b"abc"
    assert not server_mode.person_in(fence) and server_mode.person_in(fence + KEY)
    size = bytes([251, 0, 0, 0, 0, 0, 1, 0]) + bytes(16)
    assert not server_mode.person_in(size) and server_mode.person_in(size + POINTER)
    assert not server_mode.person_in(bytes([9]) + KEY), "unknown, so nothing after it is read"


def screen_scenario(token, from_page, monkeypatch, until=None):
    """Open the Browser Screen with a session, the page sending from_page
    one message at a time, and then whatever until puts in its queue once
    the screen sharing server is reached. (what the app sent the page,
    what the screen sharing server got, whether it was reached at all)."""
    from fastapi import FastAPI
    monkeypatch.setattr(server_mode, "SCREEN_CHECK_SECONDS", 0.05)
    got, sent = [], []
    connected = []

    async def scenario():
        reached = asyncio.Event()

        async def screen_sharing(reader, writer):
            connected.append(True)
            reached.set()
            while True:
                data = await reader.read(100)
                if not data:
                    break
                got.append(data)
            writer.close()

        sharing = await asyncio.start_server(screen_sharing, "127.0.0.1", 0)
        monkeypatch.setenv("PAPERPULL_VNC_PORT", str(sharing.sockets[0].getsockname()[1]))
        app = FastAPI()
        server_mode.install(app)
        queue = asyncio.Queue()
        await queue.put({"type": "websocket.connect"})
        for data in from_page:
            await queue.put({"type": "websocket.receive", "bytes": data})

        async def receive():
            return await queue.get()

        async def send(message):
            sent.append(message)

        scope = scope_for("websocket", "GET", "/screen/websockify", own_page(token))
        screen = asyncio.ensure_future(app(scope, receive, send))
        try:
            if until is not None:
                await asyncio.wait_for(reached.wait(), 10)
                await until(screen, queue)
            await asyncio.wait_for(screen, 10)
        finally:
            screen.cancel()
            sharing.close()

    asyncio.run(scenario())
    return sent, got, bool(connected)


def test_a_screen_asked_for_after_the_gap_says_why_and_reaches_nothing(monkeypatch):
    token = server_mode.new_session()
    set_back(token, "screen", server_mode.SCREEN_IDLE_SECONDS + 1)
    sent, got, connected = screen_scenario(token, [b"RFB 003.008\n"], monkeypatch)
    assert not connected and not got
    assert sent[0]["type"] == "websocket.accept"
    said = [m.get("bytes") for m in sent if m["type"] == "websocket.send"]
    reason = server_mode.SCREEN_CLOSED.encode("ascii")
    assert said == [b"RFB 003.008\n", b"\x00" + len(reason).to_bytes(4, "big") + reason]
    assert sent[-1]["type"] == "websocket.close" and sent[-1]["code"] == 1008


def test_keys_and_the_mouse_keep_an_open_screen_and_pictures_do_not(monkeypatch):
    token = server_mode.new_session()
    seen = {}

    async def until(screen, queue):
        set_back(token, "screen", 100)
        before = server_mode._SESSIONS[token]["screen"]
        await queue.put({"type": "websocket.receive", "bytes": PICTURE * 3})
        await asyncio.sleep(0.2)
        seen["picture"] = server_mode._SESSIONS[token]["screen"] == before
        await queue.put({"type": "websocket.receive", "bytes": KEY})
        await asyncio.sleep(0.2)
        seen["key"] = time.time() - server_mode._SESSIONS[token]["screen"] < 5
        set_back(token, "screen", 100)
        await queue.put({"type": "websocket.receive", "bytes": POINTER})
        await asyncio.sleep(0.2)
        seen["mouse"] = time.time() - server_mode._SESSIONS[token]["screen"] < 5
        assert not screen.done()
        await queue.put({"type": "websocket.disconnect", "code": 1000})

    sent, got, connected = screen_scenario(token, [], monkeypatch, until)
    assert connected and b"".join(got) == PICTURE * 3 + KEY + POINTER
    assert seen == {"picture": True, "key": True, "mouse": True}


def test_an_open_screen_closes_once_nobody_types_or_moves_the_mouse_on_it(monkeypatch):
    """Pictures keep coming while a page in it moves, and the panel's page
    goes on asking for things, and neither is anybody at the screen. Keys
    keep it open, and once they stop it closes. The limit is two seconds
    here, and the keys come ten times a second."""
    monkeypatch.setattr(server_mode, "SCREEN_IDLE_SECONDS", 2.0)
    token = server_mode.new_session()
    seen = {}

    async def until(screen, queue):
        for _ in range(30):
            await queue.put({"type": "websocket.receive", "bytes": KEY})
            await asyncio.sleep(0.1)
        seen["open while keys came"] = not screen.done()
        started = time.time()
        while not screen.done() and time.time() - started < 10:
            await queue.put({"type": "websocket.receive", "bytes": PICTURE})
            server_mode.note_use(token)
            await asyncio.sleep(0.1)
        seen["closed after"] = time.time() - started

    sent, got, connected = screen_scenario(token, [], monkeypatch, until)
    assert connected and seen["open while keys came"]
    assert 1.5 < seen["closed after"] < 6, seen
    assert sent[-1] == {"type": "websocket.close", "code": 1008, "reason": ""}
    assert server_mode.session_valid(token), "the panel's session goes on"


def test_noVNC_connecting_again_by_itself_starts_no_time_of_its_own(monkeypatch):
    """noVNC connects again a few seconds after every close, a dropped
    connection or the screen's own close among them, so a connection that
    started a quarter hour of its own kept a screen live for up to twice
    the limit with nobody there. Only the time someone was last seen
    counts, so a connection made near its end closes with it."""
    monkeypatch.setattr(server_mode, "SCREEN_IDLE_SECONDS", 2.0)
    token = server_mode.new_session()
    set_back(token, "screen", 1.5)
    seen = {}

    async def until(screen, queue):
        started = time.time()
        await asyncio.wait_for(asyncio.shield(screen), 10)
        seen["closed after"] = time.time() - started

    sent, got, connected = screen_scenario(token, [], monkeypatch, until)
    assert connected and seen["closed after"] < 1.5, seen
    assert sent[-1]["code"] == 1008


def test_opening_the_screens_page_is_someone_there(monkeypatch):
    """A person opens the page, from the panel or the screen's own tab, so
    it starts the quarter hour again, and a screen opened near its end does
    not close under the person reading it. noVNC never opens it again by
    itself."""
    monkeypatch.setattr(server_mode, "SCREEN_IDLE_SECONDS", 2.0)
    token = server_mode.new_session()
    set_back(token, "screen", 1.5)
    assert ask("GET", "/screen/novnc/vnc.html", token)[2] == "<title>noVNC</title>"
    assert time.time() - server_mode._SESSIONS[token]["screen"] < 1
    # noVNC's other files, which a page loads as it starts, are not a person.
    set_back(token, "screen", 1.5)
    before = server_mode._SESSIONS[token]["screen"]
    assert ask("GET", "/screen/novnc/app/ui.js", token)[2] == "// noVNC"
    assert server_mode._SESSIONS[token]["screen"] == before
    # Past the limit, the page asks for the password and counts nothing.
    set_back(token, "screen", 5)
    before = server_mode._SESSIONS[token]["screen"]
    assert 'action="/screen/again"' in ask("GET", "/screen/novnc/vnc.html", token)[2]
    assert server_mode._SESSIONS[token]["screen"] == before


# -- behind the HTTPS proxy -----------------------------------------------------------

def wrong_tries(client, forwarded=()):
    for _ in range(server_mode.FREE_TRIES):
        status, _, _ = ask("POST", "/login", form={"password": "not it"}, client=client,
                           extra=[("x-forwarded-for", f) for f in forwarded])
        assert status == 401


def test_without_a_proxy_named_wrong_tries_count_against_the_address_they_came_from():
    wrong_tries("127.0.0.1", ["198.51.100.7"])
    assert set(server_mode._FAILS) == {"127.0.0.1"}


def test_behind_the_proxy_wrong_tries_count_against_the_browser_it_names(monkeypatch):
    monkeypatch.setenv("PAPERPULL_PROXY", "localhost")
    wrong_tries("127.0.0.1", ["198.51.100.7"])
    assert set(server_mode._FAILS) == {"198.51.100.7"}
    # So the owner, at another address behind the same proxy, signs in.
    status, _, _ = ask("POST", "/login", form={"password": PASSWORD}, client="127.0.0.1",
                       extra=[("x-forwarded-for", "192.0.2.10")])
    assert status == 303
    status, _, _ = ask("POST", "/login", form={"password": PASSWORD}, client="127.0.0.1",
                       extra=[("x-forwarded-for", "198.51.100.7")])
    assert status == 429


def test_only_the_proxy_is_believed_and_only_its_own_entry(monkeypatch):
    monkeypatch.setenv("PAPERPULL_PROXY", "localhost")
    # Not the proxy, so what it says it forwarded is not taken.
    wrong_tries("10.0.0.5", ["198.51.100.7"])
    assert set(server_mode._FAILS) == {"10.0.0.5"}
    server_mode._FAILS.clear()
    # The last entry of the last line is the one the proxy wrote.
    wrong_tries("127.0.0.1", ["203.0.113.1", "203.0.113.2, 198.51.100.8"])
    assert set(server_mode._FAILS) == {"198.51.100.8"}
    server_mode._FAILS.clear()
    # Nothing the proxy wrote that reads as an address, so the proxy's own.
    wrong_tries("127.0.0.1", ["somebody"])
    assert set(server_mode._FAILS) == {"127.0.0.1"}


def test_a_proxy_name_that_finds_nothing_counts_the_proxys_address(monkeypatch):
    monkeypatch.setenv("PAPERPULL_PROXY", "no-such-proxy.invalid")
    wrong_tries("127.0.0.1", ["198.51.100.7"])
    assert set(server_mode._FAILS) == {"127.0.0.1"}


def test_the_proxys_address_is_looked_up_again(monkeypatch):
    looked = []

    async def addresses_of(name):
        looked.append(name)
        return frozenset({"172.20.0.%d" % len(looked)})

    monkeypatch.setattr(server_mode, "addresses_of", addresses_of)
    monkeypatch.setenv("PAPERPULL_PROXY", "proxy")
    first = asyncio.run(server_mode.proxy_addresses())
    assert asyncio.run(server_mode.proxy_addresses()) == first == frozenset({"172.20.0.1"})
    server_mode._PROXY["until"] = 0
    assert asyncio.run(server_mode.proxy_addresses()) == frozenset({"172.20.0.2"})
    assert looked == ["proxy", "proxy"]


# -- the answers say what they are --------------------------------------------------------

@pytest.mark.parametrize("target", ["/", "/api/apps", "/screen", "/nothing/here"])
def test_the_gates_own_answers_are_kept_private(target):
    status, headers, _ = ask("GET", target)
    assert status in (303, 401)
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "no-store"


def test_novncs_files_are_asked_after_again_each_time():
    """Kept by the browser only while they are still the image's, so a newer
    image never meets a page made of two noVNCs."""
    token = server_mode.new_session()
    status, headers, _ = ask("GET", "/screen/novnc/app/ui.js", token)
    assert status == 200 and headers["cache-control"] == "no-cache"
    assert headers["x-content-type-options"] == "nosniff"
