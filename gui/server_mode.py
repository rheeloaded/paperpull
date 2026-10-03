"""The panel as PaperPull Server runs it, on the home network behind a password.

All of it is switched on by PAPERPULL_SERVER=1, which the server image sets.
The desktop panel never sets it, and there every route here answers 404 and
the gate lets everything through, so the desktop panel behaves exactly as it
always has, on 127.0.0.1 with its same-origin check.

WHAT IT ADDS

  A password, chosen on the first visit. Until there is one, the panel shows
  only a page that asks for it, and that page wants a setup code the
  container prints in its log, so whoever reaches the page first on the
  network cannot choose it. PAPERPULL_PASSWORD sets it at start instead,
  for a compose file that should. It is kept as an scrypt hash in
  /config/server.json, never as itself.

  A gate in front of everything else. A request without a signed-in session
  is sent to the sign-in page, or answered 401 under /api/. A session is a
  random token in a cookie the page's scripts cannot read and another site
  cannot send. Wrong passwords from one address make it wait, longer each
  time.

  The browser screen, at /screen. The providers' sign-in windows open on the
  container's virtual screen, and noVNC shows it in the page. Its connection
  runs through the panel to the screen sharing server, which listens inside
  the container only, so the screen sits behind the same password and the
  same port as everything else.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# At the top, not inside install(), because the routes' annotations are
# read as names from this module, and FastAPI has to find Request there to
# know the argument is the request.
from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

SESSION_COOKIE = "paperpull_session"
SESSION_SECONDS = 14 * 86400
MIN_PASSWORD = 10
# scrypt's cost. About 16 MB and a few tenths of a second per guess.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
# After this many wrong answers from one address, each next try waits,
# twice as long each time, up to the last figure.
FREE_TRIES = 5
FIRST_WAIT = 30
LONGEST_WAIT = 15 * 60

_SESSIONS: dict = {}
_FAILS: dict = {}
_SETUP = {"code": None}


def enabled() -> bool:
    return os.environ.get("PAPERPULL_SERVER") == "1"


def config_dir() -> Path:
    return Path(os.environ.get("PAPERPULL_CONFIG") or "/config")


def novnc_dir() -> Path:
    return Path(os.environ.get("PAPERPULL_NOVNC") or "/usr/share/novnc")


def vnc_port() -> int:
    return int(os.environ.get("PAPERPULL_VNC_PORT") or "5900")


# -- the password -------------------------------------------------------------

def _secrets_file() -> Path:
    return config_dir() / "server.json"


def _read() -> dict:
    try:
        return json.loads(_secrets_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    path = _secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def _scrypt(password: str, salt: bytes, cost: dict) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=cost["n"], r=cost["r"],
                          p=cost["p"], dklen=32, maxmem=64 * 1024 * 1024)


def password_set() -> bool:
    return bool(_read().get("password"))


def set_password(password: str) -> None:
    """Keep the password's hash, and sign every session out, since a new
    password is usually chosen because the old one went somewhere."""
    salt = secrets.token_bytes(16)
    data = _read()
    data["password"] = {"scrypt": dict(SCRYPT), "salt": salt.hex(),
                        "hash": _scrypt(password, salt, SCRYPT).hex()}
    _write(data)
    _SESSIONS.clear()
    _SETUP["code"] = None


def check_password(password: str) -> bool:
    rec = _read().get("password") or {}
    try:
        got = _scrypt(password, bytes.fromhex(rec["salt"]), rec["scrypt"])
        return hmac.compare_digest(got, bytes.fromhex(rec["hash"]))
    except (KeyError, ValueError, TypeError):
        return False


def setup_code() -> str:
    """The code the setup page wants, made once per start and printed in
    the container's log, which only the NAS's owner can read."""
    if _SETUP["code"] is None:
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        _SETUP["code"] = "-".join("".join(secrets.choice(alphabet) for _ in range(4))
                                  for _ in range(3))
        print("\nPaperPull Server has no password yet. Open the panel in a browser on\n"
              "your home network, and enter this setup code to choose one.\n\n"
              "    %s\n" % _SETUP["code"], flush=True)
    return _SETUP["code"]


def on_start() -> None:
    """At the panel's start, take PAPERPULL_PASSWORD when no password is
    kept yet, or print the setup code."""
    if not enabled() or password_set():
        return
    given = os.environ.get("PAPERPULL_PASSWORD") or ""
    if given:
        if len(given) < MIN_PASSWORD:
            print("PAPERPULL_PASSWORD is shorter than %d characters, so it was not used."
                  % MIN_PASSWORD, flush=True)
        else:
            set_password(given)
            print("The password was set from PAPERPULL_PASSWORD. It is kept only as a\n"
                  "hash, so you can take it out of the compose file now.", flush=True)
            return
    setup_code()


# -- sessions and waiting ------------------------------------------------------------

def new_session() -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = time.time() + SESSION_SECONDS
    return token


def session_valid(token: str) -> bool:
    expiry = _SESSIONS.get(token or "")
    if not expiry:
        return False
    if expiry < time.time():
        _SESSIONS.pop(token, None)
        return False
    return True


def end_session(token: str) -> None:
    _SESSIONS.pop(token or "", None)


def wait_left(client: str) -> int:
    """Seconds this address still has to wait before its next try."""
    entry = _FAILS.get(client)
    return max(0, int(entry[1] - time.time() + 0.999)) if entry else 0


def note_failure(client: str) -> None:
    count, _until = _FAILS.get(client, (0, 0.0))
    count += 1
    until = 0.0
    if count >= FREE_TRIES:
        until = time.time() + min(LONGEST_WAIT, FIRST_WAIT * 2 ** (count - FREE_TRIES))
    _FAILS[client] = (count, until)


def note_success(client: str) -> None:
    _FAILS.pop(client, None)


# -- reading a request -------------------------------------------------------------------

def _headers(scope) -> dict:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _cookie(headers: dict, name: str) -> str:
    for part in (headers.get("cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def same_origin(headers: dict) -> bool:
    """Whether a request came from the panel's own page. Sec-Fetch-Site says
    so plainly in every current browser, and Origin and Referer, when sent,
    have to name the very address the request was made to."""
    site = (headers.get("sec-fetch-site") or "").lower()
    if site and site not in ("same-origin", "none"):
        return False
    host = (headers.get("host") or "").lower()
    for name in ("origin", "referer"):
        value = headers.get(name)
        if value and (urlsplit(value).netloc or "").lower() != host:
            return False
    return True


def signed_in(scope) -> bool:
    return session_valid(_cookie(_headers(scope), SESSION_COOKIE))


def client_of(scope) -> str:
    client = scope.get("client") or ("?", 0)
    return str(client[0])


# -- the gate ------------------------------------------------------------------------

OPEN_PATHS = {"/login", "/setup", "/favicon.ico"}


class SignInGate:
    """Every request goes through here. Off the server, and for the pages
    that let a person sign in, it passes straight on. Otherwise a request
    needs a signed-in session, and a connection to the browser screen needs
    one from the panel's own page."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if scope["type"] == "http" and path in OPEN_PATHS:
            return await self.app(scope, receive, send)
        if signed_in(scope) and (scope["type"] == "http" or same_origin(_headers(scope))):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        if path.startswith("/api/"):
            await _respond(send, 401, b"Sign in first.", "text/plain; charset=utf-8")
        else:
            await _respond(send, 303, b"", "text/plain", [("location", _sign_in_page())])


def _sign_in_page() -> str:
    return "/login" if password_set() else "/setup"


async def _respond(send, status: int, body: bytes, kind: str, extra=()) -> None:
    headers = [(b"content-type", kind.encode()), (b"content-length", str(len(body)).encode()),
               (b"cache-control", b"no-store")]
    headers += [(k.encode(), v.encode()) for k, v in extra]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


# -- the pages ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperPull</title><link rel="icon" href="/favicon.ico">
<style>
  :root { color-scheme: light dark; --bg:#0f1115; --panel:#171a21; --fg:#e6e6e6;
          --muted:#98a0ad; --accent:#4c8dff; --line:#262b36; --bad:#ff5c5c; }
  body { margin:0; font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--fg); display:flex; min-height:100vh;
         align-items:center; justify-content:center; }
  main { width:min(380px, calc(100vw - 32px)); background:var(--panel);
         border:1px solid var(--line); border-radius:10px; padding:24px; }
  h1 { margin:0 0 4px; font-size:19px; } p { color:var(--muted); margin:0 0 16px; }
  label { display:block; font-size:13px; color:var(--muted); margin:12px 0 4px; }
  input { width:100%; box-sizing:border-box; padding:9px 10px; border-radius:6px;
          border:1px solid var(--line); background:var(--bg); color:var(--fg); font-size:15px; }
  button { margin-top:18px; width:100%; padding:10px; border:0; border-radius:6px;
           background:var(--accent); color:#fff; font-size:15px; cursor:pointer; }
  .bad { color:var(--bad); margin:12px 0 0; }
</style></head><body><main>__BODY__</main></body></html>"""


def page(body: str) -> str:
    return PAGE.replace("__BODY__", body)


def login_body(message: str = "") -> str:
    said = '<p class="bad">%s</p>' % html.escape(message) if message else ""
    return ("<h1>PaperPull</h1><p>Sign in to this PaperPull Server.</p>"
            '<form method="post" action="/login">'
            '<label for="password">Password</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" autofocus required>'
            "%s<button>Sign in</button></form>" % said)


def setup_body(message: str = "") -> str:
    said = '<p class="bad">%s</p>' % html.escape(message) if message else ""
    return ("<h1>PaperPull</h1><p>Choose the password for this PaperPull Server. "
            "The setup code is in the container's log.</p>"
            '<form method="post" action="/setup">'
            '<label for="code">Setup code</label>'
            '<input id="code" name="code" autocomplete="off" autofocus required>'
            '<label for="password">New password, at least %d characters</label>'
            '<input id="password" name="password" type="password" autocomplete="new-password" required>'
            '<label for="again">The same password again</label>'
            '<input id="again" name="again" type="password" autocomplete="new-password" required>'
            "%s<button>Set the password</button></form>" % (MIN_PASSWORD, said))


SCREEN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperPull browser screen</title><link rel="icon" href="/favicon.ico">
<style>html,body{margin:0;height:100%;background:#0f1115}
iframe{border:0;width:100%;height:100%;display:block}</style></head>
<body><iframe src="/screen/novnc/vnc.html?autoconnect=1&amp;reconnect=1&amp;resize=scale&amp;path=screen/websockify"
title="The browser screen"></iframe></body></html>"""


def server_bar() -> str:
    """The links the panel's header carries on the server. A div, since a
    form inside a paragraph closes the paragraph where the form starts."""
    return ('<div class="serverbar"><a href="/screen" target="_blank" rel="noopener">'
            "Browser screen</a> &middot; "
            '<form method="post" action="/logout"><button>Sign out</button></form></div>')


# -- the routes ---------------------------------------------------------------------------

def install(app) -> None:
    """Put the gate in front of the panel and add the server's pages. Off
    the server every one of them answers 404."""
    app.add_middleware(SignInGate)
    # Starlette has no start-up hooks any more, and the panel is loaded once
    # as it starts, so the password is seen to here.
    on_start()

    def only_on_the_server():
        if not enabled():
            raise HTTPException(404)

    async def form(request: Request) -> dict:
        body = (await request.body())[:8192].decode("utf-8", "replace")
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}

    def signed_in_answer(token: str):
        answer = RedirectResponse("/", status_code=303)
        answer.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                          samesite="strict", path="/")
        return answer

    def refused(body: str, status: int = 401):
        return HTMLResponse(page(body), status_code=status, headers={"Cache-Control": "no-store"})

    @app.get("/login", include_in_schema=False)
    def login_page():
        only_on_the_server()
        if not password_set():
            return RedirectResponse("/setup", status_code=303)
        return HTMLResponse(page(login_body()), headers={"Cache-Control": "no-store"})

    @app.post("/login", include_in_schema=False)
    async def login(request: Request):
        only_on_the_server()
        if not password_set():
            return RedirectResponse("/setup", status_code=303)
        if not same_origin(dict(request.headers)):
            return refused(login_body("That request did not come from this page."), 403)
        client = request.client.host if request.client else "?"
        wait = wait_left(client)
        if wait:
            return refused(login_body("Too many wrong passwords. Try again in %d seconds." % wait), 429)
        if not check_password((await form(request)).get("password", "")):
            note_failure(client)
            return refused(login_body("That is not the password."))
        note_success(client)
        return signed_in_answer(new_session())

    @app.get("/setup", include_in_schema=False)
    def setup_page():
        only_on_the_server()
        if password_set():
            return RedirectResponse("/login", status_code=303)
        setup_code()
        return HTMLResponse(page(setup_body()), headers={"Cache-Control": "no-store"})

    @app.post("/setup", include_in_schema=False)
    async def setup(request: Request):
        only_on_the_server()
        if password_set():
            return RedirectResponse("/login", status_code=303)
        if not same_origin(dict(request.headers)):
            return refused(setup_body("That request did not come from this page."), 403)
        client = request.client.host if request.client else "?"
        wait = wait_left(client)
        if wait:
            return refused(setup_body("Too many wrong codes. Try again in %d seconds." % wait), 429)
        given = await form(request)
        code = given.get("code", "").strip().upper()
        if not hmac.compare_digest(code.encode(), setup_code().encode()):
            note_failure(client)
            return refused(setup_body("That is not the setup code in the container's log."))
        password = given.get("password", "")
        if len(password) < MIN_PASSWORD:
            return refused(setup_body("The password needs at least %d characters." % MIN_PASSWORD), 400)
        if password != given.get("again", ""):
            return refused(setup_body("The two passwords are not the same."), 400)
        note_success(client)
        set_password(password)
        print("A password was chosen for PaperPull Server.", flush=True)
        return signed_in_answer(new_session())

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request):
        only_on_the_server()
        end_session(request.cookies.get(SESSION_COOKIE, ""))
        answer = RedirectResponse("/login", status_code=303)
        answer.delete_cookie(SESSION_COOKIE, path="/")
        return answer

    @app.get("/screen", include_in_schema=False)
    def screen():
        only_on_the_server()
        return HTMLResponse(SCREEN, headers={"Cache-Control": "no-store"})

    @app.get("/screen/novnc/{rest:path}", include_in_schema=False)
    def novnc_file(rest: str):
        """noVNC's own files, and nothing outside its folder."""
        only_on_the_server()
        root = novnc_dir().resolve()
        target = (root / rest).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    @app.websocket("/screen/websockify")
    async def screen_socket(websocket: WebSocket):
        if not enabled():
            await websocket.close(code=1008)
            return
        asked = websocket.headers.get("sec-websocket-protocol", "")
        await websocket.accept(subprotocol="binary" if "binary" in asked else None)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc_port())
        except OSError:
            await websocket.close(code=1011)
            return
        await bridge(websocket.receive, websocket.send_bytes, reader, writer)
        try:
            await websocket.close()
        except RuntimeError:
            pass


async def bridge(receive, send_bytes, reader, writer) -> None:
    """Carry the browser screen's bytes both ways until either side ends.

    noVNC speaks the screen sharing protocol over a WebSocket, and the
    screen sharing server speaks it over plain TCP, so each message from
    the page goes to the server as it is, and each block from the server
    goes back as one binary message."""
    async def to_screen():
        while True:
            message = await receive()
            if message.get("type") == "websocket.disconnect":
                return
            data = message.get("bytes")
            if data is None:
                data = (message.get("text") or "").encode("latin-1")
            writer.write(data)
            await writer.drain()

    async def to_page():
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await send_bytes(data)

    tasks = [asyncio.ensure_future(to_screen()), asyncio.ensure_future(to_page())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
