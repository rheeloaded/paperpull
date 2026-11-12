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
  cannot send, and it ends after IDLE_SECONDS with nothing asked of it by
  the panel's own page. Wrong passwords from one address make it wait,
  longer each time.

  Its own names. It answers only a request made to its address or to a
  name that exists only on a home network, and to the names listed in
  PAPERPULL_HOSTS, so that a website cannot borrow a browser on the home
  network by pointing a name of its own at the server.

  The browser screen, at /screen. The providers' sign-in windows open on the
  container's virtual screen, and noVNC shows it in the page. Its connection
  runs through the panel to the screen sharing server, which listens inside
  the container only, so the screen sits behind the same password and the
  same port as everything else. More than SCREEN_IDLE_SECONDS after
  anyone was last seen there, the password typed, the screen opened or
  used, it closes and asks for the password again.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# At the top, not inside install(), because the routes' annotations are
# read as names from this module, and FastAPI has to find Request there to
# know the argument is the request.
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

SESSION_COOKIE = "paperpull_session"
# The session given to a browser that came by HTTPS. A browser lets no page
# reached by plain HTTP replace a Secure cookie of the same name, so with one
# name for both, a person who signed in once through an HTTPS proxy could
# never sign in again by plain HTTP at that name. The __Host- prefix makes
# the browser keep this one only as Secure, only from an HTTPS page, only
# for the whole site and only for the very name that set it, so no other
# name under the same domain can set or replace it.
SECURE_SESSION_COOKIE = "__Host-paperpull_session"
SESSION_COOKIES = (SECURE_SESSION_COOKIE, SESSION_COOKIE)
# The longest a session lasts, however much it is used.
SESSION_SECONDS = 14 * 86400
# A session the panel's own page has asked nothing of for this long ends.
# Longer than any sitting at the panel, a long first run included, and
# shorter than the days between visits to a NAS used every few days, so
# each visit signs in once and a browser left signed in is signed out the
# same day.
IDLE_SECONDS = 8 * 3600
# The Browser Screen is live keyboard and mouse on every provider signed in
# there. So it opens, and stays open, only within this long of someone
# being seen there, the password typed, the screen's page opened from the
# panel, or a key pressed or the mouse moved on it, a sign-in at a provider
# and the wait for its texted code fitting many times. After that it closes
# and asks for the password again. What the panel does meanwhile counts for
# nothing, since its page asks for things by itself, the next run of Run
# All among them, and nor does noVNC connecting again by itself, which it
# does after every close.
SCREEN_IDLE_SECONDS = 15 * 60
# How often an open Browser Screen asks whether its session still holds, so
# signing out, a new password or reset_password.py ends it within seconds.
SCREEN_CHECK_SECONDS = 3
# noVNC's page, as the Browser Screen and the panel's docked sign-in window
# open it. It finds the screen's connection at path, on the page's own
# address, by wss over HTTPS and ws over plain HTTP.
NOVNC_PAGE = "/screen/novnc/vnc.html?autoconnect=1&reconnect=1&resize=scale&path=screen/websockify"
# What the Browser Screen shows when it was closed for going unused, or is
# asked for again after that. noVNC shows the first reason a screen gives.
SCREEN_CLOSED = ("The sign-in window closed after %d minutes without use, since it is live control "
                 "of the providers signed in there. Reload this page, or open the sign-in window "
                 "again from the panel, and enter your password." % (SCREEN_IDLE_SECONDS // 60))
MIN_PASSWORD = 10
# scrypt's cost, the OWASP profile of 16 MiB in five lanes. The same memory
# as the cost before it (p=1) at five times the work, measured at 0.15 s a
# guess on a desktop and 0.14 s in the image there, and more on a NAS. A
# password kept at another cost is hashed again at this one the next time
# it signs in.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 5}
# The most memory one hash may take, nearly four times what SCRYPT needs, so
# a cost written into server.json by hand cannot have a sign-in take the
# NAS's memory. A cost asking for more fails the way a wrong password does.
SCRYPT_MAXMEM = 64 * 1024 * 1024
# Hashing runs on threads of its own, so the panel keeps answering while a
# password is checked. At most HASHES_AT_ONCE run at once, and once
# HASHES_WAITING more wait for a turn, the next sign-in is told to try again.
HASHES_AT_ONCE = 2
HASHES_WAITING = 16
# The most a sign-in or setup form may send. Its three fields fit many times.
FORM_LIMIT = 8192
# After this many wrong answers from one address, each next try waits,
# twice as long each time, up to the last figure.
FREE_TRIES = 5
FIRST_WAIT = 30
LONGEST_WAIT = 15 * 60

_SESSIONS: dict = {}
_FAILS: dict = {}
_SETUP = {"code": None}
# The hashing threads, made on first use, and how many hashes are running
# or waiting for one of them.
_HASHING = {"pool": None, "busy": 0}


def enabled() -> bool:
    return os.environ.get("PAPERPULL_SERVER") == "1"


def config_dir() -> Path:
    return Path(os.environ.get("PAPERPULL_CONFIG") or "/config")


def novnc_dir() -> Path:
    return Path(os.environ.get("PAPERPULL_NOVNC") or "/usr/share/novnc")


def vnc_port() -> int:
    return int(os.environ.get("PAPERPULL_VNC_PORT") or "5900")


def data_root() -> Path:
    """The one folder the providers' folders live in, the shared folder."""
    return Path(os.environ.get("APPS_ROOT") or "/data")


def profiles_root() -> Path:
    """Where the signed-in browser profiles live, a volume of their own,
    never the shared folder anyone with the share can read."""
    return Path(os.environ.get("PAPERPULL_PROFILES") or "/profiles")


def plugins_dir() -> Path:
    return Path(os.environ.get("PAPERPULL_PLUGINS") or "/opt/paperpull/server/plugins")


def profile_for(install_name: str, account: str = "primary") -> str:
    """A provider account's browser profile folder on the server. A run
    names it the same way from its config's path, in
    paperpull_core.storage.server_profile_dir, and a test holds the two to
    one answer."""
    name = install_name if account == "primary" else "%s - %s" % (install_name, account)
    return str(profiles_root() / name)


# -- the password -------------------------------------------------------------

def _secrets_file() -> Path:
    return config_dir() / "server.json"


def _read() -> dict:
    """The server's settings, or nothing when they cannot be read. A file
    that holds anything but an object counts as none, so a damaged one
    leads to the setup page and its code rather than to an error on every
    page."""
    try:
        data = json.loads(_secrets_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
                          p=cost["p"], dklen=32, maxmem=SCRYPT_MAXMEM)


def password_set() -> bool:
    return bool(_read().get("password"))


def password_record(password: str, salt: bytes | None = None) -> dict:
    """What server.json keeps of a password, its hash at SCRYPT's cost, with
    a new salt unless one is given. It touches nothing else, so it can run
    on a hashing thread."""
    salt = secrets.token_bytes(16) if salt is None else salt
    return {"scrypt": dict(SCRYPT), "salt": salt.hex(), "hash": _scrypt(password, salt, SCRYPT).hex()}


def keep_password(record: dict) -> None:
    """Keep a password's record, and sign every session out, since a new
    password is usually chosen because the old one went somewhere."""
    data = _read()
    data["password"] = record
    _write(data)
    _SESSIONS.clear()
    _SETUP["code"] = None


def set_password(password: str) -> None:
    keep_password(password_record(password))


def matches(password: str, record) -> bool:
    """Whether a password is the one a record was made from, at the cost the
    record names. It touches nothing else, so it can run on a hashing thread."""
    try:
        got = _scrypt(password, bytes.fromhex(record["salt"]), record["scrypt"])
        return hmac.compare_digest(got, bytes.fromhex(record["hash"]))
    except (KeyError, ValueError, TypeError):
        return False


def check_password(password: str) -> bool:
    return matches(password, _read().get("password") or {})


def outdated(record) -> bool:
    """Whether a password's record was hashed at a cost other than SCRYPT."""
    return isinstance(record, dict) and record.get("scrypt") != SCRYPT


def keep_rehashed(old: dict, new: dict) -> bool:
    """Keep the record of the same password hashed again at SCRYPT's cost,
    unless the password changed while it was made. The salt stays, and the
    salt is what a session belongs to, so nobody is signed out."""
    data = _read()
    if data.get("password") != old or new.get("salt") != old.get("salt"):
        return False
    data["password"] = new
    _write(data)
    return True


def _hash_pool() -> ThreadPoolExecutor:
    if _HASHING["pool"] is None:
        _HASHING["pool"] = ThreadPoolExecutor(max_workers=HASHES_AT_ONCE,
                                              thread_name_prefix="paperpull-scrypt")
    return _HASHING["pool"]


def hashing_full() -> bool:
    """Whether as many hashes are running and waiting as are let wait."""
    return _HASHING["busy"] >= HASHES_AT_ONCE + HASHES_WAITING


async def off_the_loop(work, *args):
    """Run a hash on a hashing thread, so the panel goes on answering other
    requests while it runs. Counted as busy from the moment this is called,
    before anything waits."""
    _HASHING["busy"] += 1
    try:
        return await asyncio.get_running_loop().run_in_executor(_hash_pool(), work, *args)
    finally:
        _HASHING["busy"] -= 1


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
    kept yet, or print the setup code. Say so in the log, too, when
    PAPERPULL_HOSTS_ONLY is on with nothing listed, since the panel then
    answers to no other device."""
    if not enabled():
        return
    if hosts_only() and not listed_names():
        print("PAPERPULL_HOSTS_ONLY is on and PAPERPULL_HOSTS lists nothing, so the panel\n"
              "answers to no other device. List the address or name you open it by in\n"
              "PAPERPULL_HOSTS, then recreate the container.", flush=True)
    if password_set():
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

def _password_stamp() -> str:
    """What tells one password from the next, its salt. A session belongs to
    the password it was signed in under, so a password changed or removed by
    any process, server/reset_password.py among them, ends it."""
    return str((_read().get("password") or {}).get("salt") or "")


def new_session() -> str:
    """A session for a password just typed. Each one keeps when it ends at
    the latest, the password it belongs to, when it was last used, and when
    the password was last typed or the Browser Screen last used, which is
    what the Browser Screen asks about."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    _SESSIONS[token] = {"ends": now + SESSION_SECONDS, "stamp": _password_stamp(),
                        "used": now, "screen": now}
    return token


def session_valid(token: str) -> bool:
    entry = _SESSIONS.get(token or "")
    if not entry:
        return False
    now = time.time()
    if (entry["ends"] < now or now - entry["used"] > IDLE_SECONDS
            or not entry["stamp"] or entry["stamp"] != _password_stamp()):
        _SESSIONS.pop(token, None)
        return False
    return True


def note_use(token: str) -> None:
    """The panel's own page asked for something with the session, which
    keeps it from going idle. It never opens the Browser Screen, since the
    page asks for things by itself with nobody there."""
    entry = _SESSIONS.get(token or "")
    if entry:
        entry["used"] = time.time()


def note_screen_use(token: str) -> None:
    """Someone was seen at the Browser Screen, a key pressed or the mouse
    moved on it, or its page opened from the panel. It keeps the session
    from going idle and the screen open to it."""
    entry = _SESSIONS.get(token or "")
    if entry:
        entry["used"] = entry["screen"] = time.time()


def screen_open(token: str) -> bool:
    """Whether the Browser Screen may open for a session, or stay open,
    which takes someone seen there, the password typed, its page opened or
    the screen used, no longer than SCREEN_IDLE_SECONDS ago."""
    if not session_valid(token):
        return False
    entry = _SESSIONS.get(token or "")
    return bool(entry) and time.time() - entry["screen"] <= SCREEN_IDLE_SECONDS


def screen_again(token: str) -> None:
    """The password was typed again to open the Browser Screen."""
    entry = _SESSIONS.get(token or "")
    if entry:
        entry["used"] = entry["screen"] = time.time()


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


async def read_form(request) -> dict | None:
    """The fields of a sign-in or setup form, or None for a body longer than
    FORM_LIMIT. A Content-Length over it is refused before anything is
    read. A body sent in chunks, or with no length, is read as it comes and
    refused the moment it passes the limit, so no more than the limit and
    one piece of the connection's reading is ever held."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > FORM_LIMIT:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for piece in request.stream():
        body += piece
        if len(body) > FORM_LIMIT:
            return None
    text = bytes(body).decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items()}


def _cookie(headers: dict, name: str) -> str:
    for part in (headers.get("cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def session_token(headers: dict) -> str:
    """The session a request carries, in either cookie. A browser that
    signed in both ways sends both over HTTPS, so a live one is taken first."""
    tokens = [token for token in (_cookie(headers, name) for name in SESSION_COOKIES) if token]
    return next((token for token in tokens if session_valid(token)), tokens[0] if tokens else "")


def _first_header(scope, name: str) -> str:
    """The first line of a header, where _headers keeps the last."""
    for key, value in scope.get("headers", []):
        if key.decode("latin-1").lower() == name:
            return value.decode("latin-1")
    return ""


def over_https(scope) -> bool:
    """Whether the browser reached the panel over HTTPS, itself or through a
    reverse proxy that says so in X-Forwarded-Proto or Forwarded. Only the
    first entry counts, the one the proxy nearest the browser wrote. The
    answer only ever chooses the session cookie that travels over HTTPS
    alone, so a request that claims HTTPS falsely harms nobody but itself,
    its browser refusing a cookie like that over plain HTTP."""
    if scope.get("scheme") in ("https", "wss"):
        return True
    if _first_header(scope, "x-forwarded-proto").split(",")[0].strip().lower() == "https":
        return True
    for part in _first_header(scope, "forwarded").split(",")[0].split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "proto" and value.strip('"').lower() == "https":
            return True
    return False


def from_its_own_page(headers: dict) -> bool:
    """Whether a request is one the panel's own page made, or an address the
    browser opened by itself, typed in or opened from a bookmark. A page of
    another program on the same machine, at another port, is the same site
    as far as the browser knows, so it sends the session's cookie with
    whatever that page asks for, an image for instance. Such a request
    never counts as the session being used."""
    if (headers.get("sec-fetch-site") or "").lower() == "none":
        return True
    return same_origin(headers)


def same_origin(headers: dict) -> bool:
    """Whether a request came from the panel's own page, on the desktop and
    on the server alike. Sec-Fetch-Site says so plainly in every current
    browser, same-origin for a request the panel's page made. It says none
    when the browser opened an address by itself, typed into the bar or a
    link opened from an email, a chat or a PDF. That is how a page is
    opened, and every request asked about here is one a page makes, to the
    API, the server's sign-in and sign-out and the Browser Screen's
    connection, so none is refused too. Origin and Referer, when sent, have
    to name the very address the request was made to. An Origin of null,
    which a browser sends for a page that keeps its address to itself,
    names no address, and neither does an empty one, so both are refused."""
    site = (headers.get("sec-fetch-site") or "").lower()
    if site and site != "same-origin":
        return False
    host = (headers.get("host") or "").lower()
    origin = headers.get("origin")
    if origin is not None and (origin.strip().lower() in ("", "null")
                               or (urlsplit(origin.strip()).netloc or "").lower() != host):
        return False
    referer = headers.get("referer")
    if referer and (urlsplit(referer.strip()).netloc or "").lower() != host:
        return False
    return True


# -- the names it answers to -----------------------------------------------------------
#
# A website can point a name of its own at the server's address (DNS
# rebinding), and a browser on the home network then takes that site's page
# for the panel's own. A session cookie never goes to that name, but the
# sign-in page would answer it, so the server answers only to names a
# website cannot give. An address is one, since nobody can point it
# anywhere else, and so is a name that exists only on a home network, nas
# or nas.local. Any other name, a VPN's or a reverse proxy's, is one the
# person lists in PAPERPULL_HOSTS.
#
# PAPERPULL_HOSTS_ONLY, when the person sets it, narrows that to the names
# and addresses in PAPERPULL_HOSTS alone, for a server that should answer to
# nothing it was not told of. The container's own loopback still answers,
# since no other device can reach the server by it, and the self-test and
# the container's own checks use it.

LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
HOSTS_ONLY_ON = ("1", "true", "yes", "on")


def hosts_only() -> bool:
    """Whether PAPERPULL_HOSTS_ONLY asks for the listed names alone. Read on
    every request, as PAPERPULL_HOSTS is."""
    return (os.environ.get("PAPERPULL_HOSTS_ONLY") or "").strip().lower() in HOSTS_ONLY_ON


def _loopback(name: str) -> bool:
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _a_listed_address(name: str, listed: set) -> bool:
    """Whether a name is an address that PAPERPULL_HOSTS lists, however
    either is written, so fd00::5 and fd00:0:0:0:0:0:0:5 are one."""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    for item in listed:
        try:
            if ipaddress.ip_address(item) == address:
                return True
        except ValueError:
            continue
    return False


def listed_names() -> set:
    """The names in PAPERPULL_HOSTS, separated by commas or spaces, each
    taken without a scheme, a path or a port, so a whole address pasted in
    works too."""
    names = set()
    for item in re.split(r"[\s,]+", (os.environ.get("PAPERPULL_HOSTS") or "").lower()):
        item = item.split("//", 1)[-1].split("/", 1)[0]
        if item.startswith("["):
            item = item[1:item.find("]")] if "]" in item else ""
        elif item.count(":") == 1:
            item = item.split(":", 1)[0]
        if item:
            names.add(item)
    return names


def host_allowed(name: str) -> bool:
    """Whether the server answers to a name, given without its port."""
    if not name:
        return False
    if hosts_only():
        listed = listed_names()
        return _loopback(name) or name in listed or _a_listed_address(name, listed)
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return "." not in name or name.endswith(LOCAL_SUFFIXES) or name in listed_names()


def not_its_name(name: str) -> str:
    """What a request made to another name is told. The person who reached
    the server by a name of their own reads how to add it."""
    if not name:
        return "This PaperPull Server answers only to its own address and names.\n"
    if hosts_only():
        return ("This PaperPull Server was asked for as %s, and PAPERPULL_HOSTS_ONLY is on, so "
                "it answers only to the names and addresses in PAPERPULL_HOSTS. If that is how "
                "you reach it, add %s to PAPERPULL_HOSTS in compose.yaml, or to x-names in "
                "compose.https.yaml, then recreate the container, since a restart keeps the "
                "settings it started with.\n" % (name, name))
    return ("This PaperPull Server was asked for as %s, which is not one of its names, so it "
            "did not answer. If that is how you reach it, add %s to PAPERPULL_HOSTS in "
            "compose.yaml, then recreate the container, since a restart keeps the settings "
            "it started with.\n" % (name, name))


def signed_in(scope) -> bool:
    return session_valid(session_token(_headers(scope)))


def client_of(scope) -> str:
    client = scope.get("client") or ("?", 0)
    return str(client[0])


# -- behind the HTTPS proxy -----------------------------------------------------------
#
# compose.https.yaml puts Caddy in front of the panel, and every request then
# comes from Caddy's address. Wrong passwords are counted by address, so
# counted against Caddy's, five from anyone on the network would make the
# owner wait as well. So the proxy is named in PAPERPULL_PROXY, by its name
# on the project's own network, and a request from that name's address is
# taken to come from the browser the proxy names. Caddy writes that
# address in X-Forwarded-For itself, in place of any a browser sent.

PROXY_LOOKUP_SECONDS = 60
_PROXY = {"name": "", "addresses": frozenset(), "until": 0.0}


async def addresses_of(name: str) -> frozenset:
    """Every address a name has, looked up without holding up the panel."""
    infos = await asyncio.get_running_loop().getaddrinfo(name, None)
    return frozenset(str(info[4][0]) for info in infos)


async def proxy_addresses() -> frozenset:
    """The addresses PAPERPULL_PROXY names, looked up again every minute,
    since the proxy's address changes when its container is made again."""
    name = (os.environ.get("PAPERPULL_PROXY") or "").strip()
    if not name:
        return frozenset()
    now = time.time()
    if _PROXY["name"] == name and now < _PROXY["until"]:
        return _PROXY["addresses"]
    try:
        found = await addresses_of(name)
    except OSError:
        found = frozenset()
    _PROXY.update(name=name, addresses=found, until=now + PROXY_LOOKUP_SECONDS)
    return found


async def client_address(scope) -> str:
    """The address a sign-in came from, which its wrong tries count against.
    From the proxy, the last address in the last X-Forwarded-For line, the
    one the proxy nearest the panel wrote, and from anywhere else, or when
    the proxy names no plain address, the address the request came from."""
    peer = client_of(scope)
    if peer not in await proxy_addresses():
        return peer
    lines = [value.decode("latin-1") for key, value in scope.get("headers", [])
             if key.decode("latin-1").lower() == "x-forwarded-for"]
    last = lines[-1].split(",")[-1].strip() if lines else ""
    try:
        return str(ipaddress.ip_address(last))
    except ValueError:
        return peer


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
        headers = _headers(scope)
        token = session_token(headers)
        if session_valid(token) and (scope["type"] == "http" or same_origin(headers)):
            # A connection to the Browser Screen is not use, since noVNC
            # makes one again by itself when one ends. Keys and the mouse
            # on the screen are, and the screen notes those itself.
            if scope["type"] == "http" and from_its_own_page(headers):
                note_use(token)
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


def again_body(to: str, message: str = "") -> str:
    """The Browser Screen asking for the password again. to says where it
    goes once the password is right, its own tab or the panel's docked
    sign-in window."""
    said = '<p class="bad">%s</p>' % html.escape(message) if message else ""
    return ("<h1>Sign-in window</h1><p>The sign-in window is live control of every provider "
            "signed in there, so after %d minutes without use it asks for your password "
            "again.</p>"
            '<form method="post" action="/screen/again">'
            '<input type="hidden" name="to" value="%s">'
            '<label for="password">Password</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" autofocus required>'
            "%s<button>Open the sign-in window</button></form>"
            % (SCREEN_IDLE_SECONDS // 60, "dock" if to == "dock" else "screen", said))


SCREEN = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperPull Browser Screen</title><link rel="icon" href="/favicon.ico">
<style>html,body{margin:0;height:100%;background:#0f1115}
iframe{border:0;width:100%;height:100%;display:block}</style></head>
<body><iframe src="__NOVNC__"
title="The Browser Screen"></iframe></body></html>""".replace("__NOVNC__", html.escape(NOVNC_PAGE))


# A screen, drawn with the page's own color so it suits light and dark.
_SCREEN_ICON = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>')


def server_bar() -> str:
    """What the panel's header carries on the server. Every sign-in happens
    in the sign-in window, the browser on the server's screen. The page
    docks it beside the accounts when a sign-in starts, and this button
    opens it at any time, in a tab of its own when the page cannot run. The
    Paperless line shows only when the page hears new files go there. A
    div, since a form inside a paragraph closes the paragraph where the
    form starts."""
    return ('<div class="serverbar">'
            '<span id="paperlesspill" class="pill pill-ok" hidden>'
            '<span class="dot" aria-hidden="true"></span>New files go to Paperless</span>'
            '<a id="screenbtn" class="btn btn-s screenbtn" href="/screen" target="_blank" rel="noopener"'
            ' title="The browser on the server, where the providers\' sign-in pages open">'
            + _SCREEN_ICON + "Sign-in window</a>"
            '<form method="post" action="/logout"><button class="btn btn-ghost">Sign out</button></form>'
            '</div>')


def sandbox_problem() -> str:
    """Why this host cannot give Chrome its sandbox, in a sentence, or ""
    when nothing stands in its way. A host whose kernel has no user
    namespaces, Synology DSM's among them, stops Chrome before it opens a
    window, and the Browser Screen stayed black with nothing saying why
    (#110). Asked once per panel (paperpull_core.host_sandbox.check)."""
    if not enabled():
        return ""
    try:
        from paperpull_core import host_sandbox
        return host_sandbox.problem(host_sandbox.check())
    except Exception:
        return ""


def paperless_connected() -> bool:
    """Whether the documents a run saves are copied to Paperless, which
    takes the Paperless plug-in and the folder it copies into, the consume
    folder, mounted in the container."""
    if not any(str(info.get("name") or "") == "Paperless" for _, info in plugins()):
        return False
    return Path(os.environ.get("PAPERLESS_CONSUME_DIR") or "/paperless").is_dir()


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

    def signed_in_answer(request: Request, token: str):
        # Secure only over HTTPS, since a home network reaches the panel by
        # plain HTTP and a browser keeps no Secure cookie sent that way.
        # Behind an HTTPS proxy it keeps the cookie off a plain HTTP visit
        # to the proxy's name, which would otherwise carry it in the clear.
        secure = over_https(request.scope)
        answer = RedirectResponse("/", status_code=303)
        answer.set_cookie(SECURE_SESSION_COOKIE if secure else SESSION_COOKIE, token,
                          max_age=SESSION_SECONDS, httponly=True, samesite="strict", path="/",
                          secure=secure)
        return answer

    def refused(body: str, status: int = 401):
        return HTMLResponse(page(body), status_code=status, headers={"Cache-Control": "no-store"})

    def too_large(body: str):
        # The rest of the body is never read, so the connection closes
        # rather than carry it into a next request.
        return HTMLResponse(page(body), status_code=413,
                            headers={"Cache-Control": "no-store", "Connection": "close"})

    @app.get("/login", include_in_schema=False)
    def login_page():
        only_on_the_server()
        if not password_set():
            return RedirectResponse("/setup", status_code=303)
        return HTMLResponse(page(login_body()), headers={"Cache-Control": "no-store"})

    async def password_tried(client: str, password: str):
        """None when a password typed into a form is the server's, or the
        status and the words that say why not. The caller reads the body,
        and where it came from, before this looks at the wait. Read after
        it, many logins whose headers came at once all passed the wait
        together, before any of them was counted wrong."""
        wait = wait_left(client)
        if wait:
            return 429, "Too many wrong passwords. Try again in %d seconds." % wait
        if hashing_full():
            return 503, "The server is busy checking other sign-ins. Try again in a moment."
        # Each try is counted wrong before its password is hashed, and the
        # count is forgiven only once the hash says it was right. The hash
        # runs on another thread while other logins go on, so a try counted
        # after it would let many logins sent at once all pass the wait
        # first. From the wait being looked at to the count nothing waits,
        # so each is judged after the one before it was counted.
        record = _read().get("password") or {}
        note_failure(client)
        if not await off_the_loop(matches, password, record):
            return 401, "That is not the password."
        note_success(client)
        if outdated(record) and not hashing_full():
            # Hashed again at today's cost while the password is at hand,
            # with the same salt. Skipped when busy, and done next time.
            # A settings folder that cannot be written never keeps the
            # owner out, since the old hash still holds.
            try:
                keep_rehashed(record, await off_the_loop(password_record, password,
                                                         bytes.fromhex(record["salt"])))
            except (OSError, ValueError, RuntimeError) as e:
                print("The password could not be kept at the new cost yet, %s. It still signs "
                      "in, and is tried again next time." % e, flush=True)
        return None

    @app.post("/login", include_in_schema=False)
    async def login(request: Request):
        only_on_the_server()
        if not password_set():
            return RedirectResponse("/setup", status_code=303)
        if not same_origin(dict(request.headers)):
            return refused(login_body("That request did not come from this page."), 403)
        given = await read_form(request)
        if given is None:
            return too_large(login_body("That sign-in sent more than a password."))
        client = await client_address(request.scope)
        wrong = await password_tried(client, given.get("password", ""))
        if wrong:
            return refused(login_body(wrong[1]), wrong[0])
        return signed_in_answer(request, new_session())

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
        # Read before the wait is looked at, as at /login. The code is
        # checked and counted with nothing waiting in between, and only a
        # right code goes on to have its password hashed.
        given = await read_form(request)
        if given is None:
            return too_large(setup_body("That form sent more than a code and a password."))
        client = await client_address(request.scope)
        wait = wait_left(client)
        if wait:
            return refused(setup_body("Too many wrong codes. Try again in %d seconds." % wait), 429)
        code = given.get("code", "").strip().upper()
        if not hmac.compare_digest(code.encode(), setup_code().encode()):
            note_failure(client)
            return refused(setup_body("That is not the setup code in the container's log."))
        password = given.get("password", "")
        if len(password) < MIN_PASSWORD:
            return refused(setup_body("The password needs at least %d characters." % MIN_PASSWORD), 400)
        if password != given.get("again", ""):
            return refused(setup_body("The two passwords are not the same."), 400)
        if hashing_full():
            return refused(setup_body("The server is busy checking sign-ins. "
                                      "Try again in a moment."), 503)
        note_success(client)
        record = await off_the_loop(password_record, password)
        if password_set():
            # Another setup with the code chose the password while this
            # one's hash was made, and the first one chosen stays.
            return RedirectResponse("/login", status_code=303)
        keep_password(record)
        print("A password was chosen for PaperPull Server.", flush=True)
        return signed_in_answer(request, new_session())

    @app.post("/logout", include_in_schema=False)
    def logout(request: Request):
        only_on_the_server()
        if not same_origin(dict(request.headers)):
            return refused(login_body("That request did not come from this page."), 403)
        for name in SESSION_COOKIES:
            end_session(request.cookies.get(name, ""))
        answer = RedirectResponse("/login", status_code=303)
        answer.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
        if over_https(request.scope):
            answer.delete_cookie(SECURE_SESSION_COOKIE, path="/", secure=True, httponly=True,
                                 samesite="strict")
        return answer

    @app.get("/screen", include_in_schema=False)
    def screen(request: Request):
        only_on_the_server()
        if not screen_open(session_token(_headers(request.scope))):
            return HTMLResponse(page(again_body("screen")), headers={"Cache-Control": "no-store"})
        return HTMLResponse(SCREEN, headers={"Cache-Control": "no-store"})

    @app.get("/screen/novnc/{rest:path}", include_in_schema=False)
    def novnc_file(request: Request, rest: str):
        """noVNC's own files, and nothing outside its folder. Its page asks
        for the password first once the session has gone unused too long
        for the Browser Screen, since the panel docks that very page. The
        files are kept by the browser only as long as they are still the
        image's, so a newer image never meets a mix of two noVNCs."""
        only_on_the_server()
        root = novnc_dir().resolve()
        target = (root / rest).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(404)
        if target.suffix == ".html":
            token = session_token(_headers(request.scope))
            if not screen_open(token):
                return HTMLResponse(page(again_body("dock")), headers={"Cache-Control": "no-store"})
            # The page is opened by a person, from the panel or its own tab,
            # where noVNC connecting again never opens it again.
            note_screen_use(token)
        return FileResponse(target, headers={"Cache-Control": "no-cache"})

    @app.post("/screen/again", include_in_schema=False)
    async def screen_with_password(request: Request):
        """The password typed again, to open the Browser Screen. Wrong ones
        count and wait as at /login."""
        only_on_the_server()
        # Where the answer is shown, the panel's docked window or the
        # screen's own tab, for the answers made before the form is read.
        framed = "dock" if request.headers.get("sec-fetch-dest") == "iframe" else "screen"
        if not same_origin(dict(request.headers)):
            return refused(again_body(framed, "That request did not come from this page."), 403)
        given = await read_form(request)
        if given is None:
            return too_large(again_body(framed, "That sent more than a password."))
        to = "dock" if given.get("to") == "dock" else "screen"
        client = await client_address(request.scope)
        wrong = await password_tried(client, given.get("password", ""))
        if wrong:
            return refused(again_body(to, wrong[1]), wrong[0])
        screen_again(session_token(_headers(request.scope)))
        return RedirectResponse(NOVNC_PAGE if to == "dock" else "/screen", status_code=303)

    @app.websocket("/screen/websockify")
    async def screen_socket(websocket: WebSocket):
        if not enabled():
            await websocket.close(code=1008)
            return
        # The gate let this connection in on its session, and the screen is
        # live keyboard and mouse on every provider signed in there, so the
        # session is asked again every few seconds and the screen closes once
        # it has ended, by signing out, a new password or reset_password.py,
        # or once nobody has been seen there for SCREEN_IDLE_SECONDS. The
        # panel's requests never keep it open, and a connection noVNC makes
        # again by itself starts no time of its own.
        token = session_token(_headers(websocket.scope))
        asked = websocket.headers.get("sec-websocket-protocol", "")
        await websocket.accept(subprotocol="binary" if "binary" in asked else None)
        if not screen_open(token):
            await turned_away(websocket)
            return
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc_port())
        except OSError:
            await close_quietly(websocket, 1011)
            return
        await bridge(websocket.receive, websocket.send_bytes, reader, writer,
                     allowed=lambda: screen_open(token), used=lambda: note_screen_use(token))
        await close_quietly(websocket, 1000 if screen_open(token) else 1008)


# -- after a run, the plug-ins ----------------------------------------------------------
#
# A plug-in is a program of its own in a folder with a plugin.json, which
# names it, the events it wants and the command that runs it. After a run
# the panel hands each one that wants "run-finished" the run's description
# as JSON on stdin and shows what it prints. It is never loaded into the
# panel, so a plug-in that fails cannot take a run down with it, it can be
# written in anything, and its license is its own business. The first one,
# server/plugins/paperless, copies a run's new documents to Paperless.

PLUGIN_SECONDS = 300


def plugins() -> list:
    """(folder, manifest) for every plug-in with a usable manifest."""
    out = []
    root = plugins_dir()
    if not root.is_dir():
        return out
    for folder in sorted(root.iterdir()):
        try:
            info = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        run = info.get("run") if isinstance(info, dict) else None
        if isinstance(run, list) and run and all(isinstance(part, str) for part in run):
            out.append((folder, info))
    return out


# What may follow a "~" that stands for the home folder.
_AFTER_HOME = ("", "/", "\\") if os.name == "nt" else ("", "/")


def with_home(value):
    """A folder setting as a run reads it, with a "~" at its start read as
    the home folder (#166), "~" alone or followed by a separator. A name
    that only starts with "~" is a folder of that name, and anything else
    comes back as it is. A run reads a setting the same way, in
    paperpull_core.storage.with_home, and a test holds the two to one
    answer. On PaperPull Server the home folder is outside the data folder,
    so such a folder is refused there as any other outside it."""
    if not isinstance(value, str) or value[:1] != "~" or value[1:2] not in _AFTER_HOME:
        return value
    home = os.path.expanduser(value)
    return value if home == value else os.path.normpath(home)


def output_root(install: Path, account: str) -> Path:
    """The folder an account's documents and records are written to."""
    config = install / ("config.json" if account == "primary" else "config.%s.json" % account)
    try:
        out = json.loads(config.read_text(encoding="utf-8-sig")).get("output_dir") or "."
    except (OSError, ValueError, AttributeError):
        out = "."
    # A config written by hand can hold a number or a list here, which no
    # path can be made of. Refused rather than guessed, since the install's
    # own folder is the first person's, and a second person's run must never
    # be read from it or hand its files on.
    if not isinstance(out, str):
        raise ValueError("output_dir in %s is not text" % config.name)
    root = (install / with_home(out)).resolve()
    # On the server the config sits in the shared folder, which others may
    # write, and the panel keeps each run's log in this folder and reads
    # records from it, so a folder outside the data folder is refused, a
    # link that leads out of it too. A run refuses it the same way, in
    # paperpull_core.storage.hold_to_the_server.
    if enabled() and not inside_data(root):
        raise ValueError("output_dir in %s leads outside the data folder" % config.name)
    return root


def inside_data(path) -> bool:
    """Whether a folder is the data folder or inside it, judged where its
    links lead."""
    data = data_root().resolve()
    try:
        where = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    return where == data or data in where.parents


# -- writing in the shared folder ------------------------------------------------------
#
# The data folder is often a share other people can write, and some shares let
# them leave a link there, a file or folder name that leads elsewhere, while
# the container's user also owns /config and /profiles. So on the server the
# panel writes a file there only into a folder inside the data folder once its
# links are followed, as a new file moved into place, which replaces a link at
# the name rather than follow it, and never reads a file through a link to
# write what it read back into the share. A run is held the same way by
# paperpull_core.shared_folder.

def hold_in_data(folder) -> None:
    """On the server, OSError unless a folder, once its links are followed,
    is inside the data folder. Called before a folder is made or written
    into, since a folder made through a link is made outside."""
    if enabled() and not inside_data(folder):
        raise OSError("%s leads outside the data folder through a link" % folder)


def linked(path) -> bool:
    """Whether a name is a link, a junction or a second name of another
    file, a hard link. A name with nothing there is none of them."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    junction = getattr(os.path, "isjunction", None)
    if junction and junction(path):
        return True
    return stat.S_ISREG(st.st_mode) and st.st_nlink > 1


def own_file(path) -> bool:
    """Whether the panel may read a file in the shared folder and write it
    back. Always off the server. On it, only a file that is no link and no
    second name of another, in a folder inside the data folder, since what
    was read through a link would be written back into the share."""
    if not enabled():
        return True
    return inside_data(Path(path).parent) and not linked(path)


def write_in_data(path, data) -> None:
    """Write text or bytes to a file in the shared folder on the server, in
    a folder held inside the data folder, as a new file of its own moved
    into the file's place."""
    path = Path(path)
    hold_in_data(path.parent)
    tmp = path.with_name("%s.%s.tmp" % (path.name, os.urandom(6).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0), 0o666)
    try:
        if isinstance(data, str):
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_files(install: Path, account: str, started: float) -> list:
    """The documents a run saved, from the new-this-run.txt it wrote.

    Only a list written after the run started counts, since a run that
    stopped early leaves the last run's list in place, and its files were
    handed on then. Only files that exist inside the shared folder are
    passed on, whatever the list says."""
    try:
        root = output_root(install, account)
    except ValueError:
        return []
    listed = root / "new-this-run.txt"
    try:
        if listed.stat().st_mtime < started:
            return []
        lines = listed.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    data = data_root().resolve()
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path = Path(line)
        path = (path if path.is_absolute() else root / path).resolve()
        if data in path.parents and path.is_file() and str(path) not in out:
            out.append(str(path))
    return out


def run_finished(meta: dict, account: str, action: str, started: float,
                 code: int, result) -> dict:
    """What every plug-in is told about a run that has ended."""
    install = Path(meta["dir"])
    return {"event": "run-finished", "version": 1,
            "provider": meta.get("name", ""), "account": account, "action": action,
            "install": str(install), "exit_code": code, "result": result,
            "new_files": new_files(install, account, started)}


def after_run(meta: dict, account: str, action: str, started: float,
              code: int, result) -> list:
    """Run the plug-ins that want to hear a run ended, and the lines they
    said, each with its plug-in's name in front."""
    event = json.dumps(run_finished(meta, account, action, started, code, result))
    lines = []
    for folder, info in plugins():
        if "run-finished" not in (info.get("events") or []):
            continue
        name = str(info.get("name") or folder.name)
        cmd = [sys.executable if part == "python" else part for part in info["run"]]
        try:
            done = subprocess.run(cmd, cwd=folder, input=event, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=PLUGIN_SECONDS)
        except subprocess.TimeoutExpired:
            lines.append("[%s] did not finish in %d seconds, and was stopped."
                         % (name, PLUGIN_SECONDS))
            continue
        except OSError as e:
            lines.append("[%s] could not start, %s" % (name, e))
            continue
        said = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
        lines += ["[%s] %s" % (name, line) for line in said[-20:]]
        if done.returncode:
            lines.append("[%s] ended with code %d." % (name, done.returncode))
    return lines


async def close_quietly(websocket, code: int = 1000) -> None:
    """Close the Browser Screen's connection, unless the page already went,
    a tab closed for instance, when there is nothing left to close. Found on
    the NAS, where every tab closed logged a whole traceback."""
    try:
        await websocket.close(code=code)
    except (RuntimeError, WebSocketDisconnect):
        pass


async def turned_away(websocket) -> None:
    """Tell noVNC why the screen will not open, in the screen sharing
    protocol's own words. A server that lets nobody in sends its version,
    then no way in and the reason, which noVNC shows in place of the screen.
    noVNC makes no new connection after one it could not open, so the
    reason stays until the page is opened again."""
    try:
        await websocket.send_bytes(b"RFB 003.008\n")
        # noVNC answers with its own version before it reads any further.
        await asyncio.wait_for(websocket.receive(), 5)
        reason = SCREEN_CLOSED.encode("ascii")
        await websocket.send_bytes(b"\x00" + len(reason).to_bytes(4, "big") + reason)
    except (asyncio.TimeoutError, RuntimeError, WebSocketDisconnect, OSError):
        pass
    await close_quietly(websocket, 1008)


# The messages noVNC sends the screen sharing server, by the number each
# starts with, and how long each is, from its first byte. The ones only a
# person sends, a key and the mouse, are 4 and 5, and 255 followed by 0, a
# key as QEMU's extension sends it. The rest noVNC sends by itself, a
# request for the screen's next picture above all, which it makes every
# time the picture changes, so a page showing something that moves sends a
# stream of them with nobody there. A paste, 6, is among those, since
# noVNC answers the screen's own clipboard with one, measured live, and a
# person who pastes presses Ctrl+V in the page afterwards.
_PERSON = (4, 5)
_FIXED = {0: 20, 3: 10, 150: 10, 250: 4}


def person_in(data: bytes) -> bool:
    """Whether a message from noVNC holds a key or the mouse. noVNC sends
    each message of its own as one, so a message starts every one read
    here, and one that starts with anything else, the protocol's opening
    among them, is taken to hold none."""
    i = 0
    while i < len(data):
        kind = data[i]
        if kind in _PERSON or (kind == 255 and data[i + 1:i + 2] == b"\x00"):
            return True
        if kind in _FIXED:
            size = _FIXED[kind]
        elif kind == 6 and len(data) >= i + 8:
            # Its length is signed, less than nothing for the clipboard's
            # extension, which counts the same bytes.
            size = 8 + abs(int.from_bytes(data[i + 4:i + 8], "big", signed=True))
        elif kind == 2 and len(data) >= i + 4:
            size = 4 + 4 * int.from_bytes(data[i + 2:i + 4], "big")
        elif kind == 248 and len(data) >= i + 9:
            size = 9 + data[i + 8]
        elif kind == 251 and len(data) >= i + 7:
            size = 8 + 16 * data[i + 6]
        else:
            return False
        i += size
    return False


async def bridge(receive, send_bytes, reader, writer, allowed=None, used=None) -> None:
    """Carry the browser screen's bytes both ways until either side ends.

    noVNC speaks the screen sharing protocol over a WebSocket, and the
    screen sharing server speaks it over plain TCP, so each message from
    the page goes to the server as it is, and each block from the server
    goes back as one binary message. When `allowed` is given it is asked
    every SCREEN_CHECK_SECONDS, and the bridge ends once it says no. `used`
    is told each time a message from the page holds a key, the mouse or a
    paste."""
    async def watch():
        while allowed():
            await asyncio.sleep(SCREEN_CHECK_SECONDS)

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
            if used is not None and person_in(data):
                used()

    async def to_page():
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await send_bytes(data)

    tasks = [asyncio.ensure_future(to_screen()), asyncio.ensure_future(to_page())]
    if allowed is not None:
        tasks.append(asyncio.ensure_future(watch()))
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
