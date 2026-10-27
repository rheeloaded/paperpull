"""Start PaperPull Server the way SERVER.md tells a person to, and check it.

    python server/smoke.py --image paperpull-server:dev

It copies compose.yaml, compose.https.yaml, Caddyfile and the container's
security profile into a folder of its own and starts them there with Docker
Compose, under a project and container names of its own, so it can never
touch a real installation or its volumes. Then it does what a person does
on the first visit, choosing a password with the setup code from the
container's log, signs in, sets up a provider, and runs the self-test
inside the container.

Then it takes the # off the two cap_add lines of compose.yaml, as SERVER.md
tells a person with a Synology to, and checks that the sandbox helper of the
Chrome in use is made setuid root and the self-test still holds. The browser
volume is root's and pp can put nothing in it, and with the Chrome in use
given to pp no helper is setuid. With the lines put back, no copy of the
helper keeps the bit.

Then it moves the same project to compose.https.yaml, as a person moving to
HTTPS does, and checks what that file promises. The panel answers by HTTPS
through Caddy, with a certificate of Caddy's own authority, and keeps the
password chosen before. Its sign-in cookie is the __Host- one, marked
Secure. The Browser Screen connects over wss. The panel is published on no
port, so plain HTTP reaches it from its own project's network and from no
other. And wrong passwords count against the browser behind Caddy, never
against Caddy. The project is taken down with its volumes at the end,
whatever happened.

Each line says what was checked and whether it held. It exits 0 only when
every check held. The Server image workflow runs it on every change before
an image can be published, and it runs the same way on any computer with
Docker, as long as nothing else there uses port 8765.

Compose is started from another folder than the one holding compose.yaml,
as `docker compose -f server/compose.yaml up -d` would be, so a path in it
that only works from its own folder is found here and not by a person.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path

SERVER = Path(__file__).resolve().parent
PROJECT = "paperpull-smoke"
CONTAINER = "paperpull-smoke"
PROXY = "paperpull-smoke-proxy"
PANEL = "http://127.0.0.1:8765"
# The name and address compose.https.yaml is given here, in place of a NAS's.
HTTPS_NAME = "localhost"
HTTPS_PANEL = "https://localhost:8765"
# Where Caddy keeps its certificate authority's own certificate, the one a
# person copies to their devices.
ROOT_CERT = "/data/caddy/pki/authorities/local/root.crt"
# The first start downloads Chrome, about 110 MB from Google.
START_LIMIT = 600
CODE_LINE = re.compile(r"^ {4}([A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4})\s*$", re.M)
PROVIDER = "github"

FAILED: list = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    print("%-9s%-6s%s" % (name, "ok" if ok else "FAIL", detail), flush=True)
    if not ok:
        FAILED.append(name)
    return ok


class _Stay(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer to look at here, never one to follow."""

    def redirect_request(self, *args, **kwargs):
        return None


# The panel is on this computer, so no request goes through a proxy.
# urllib's own opener sends every one through HTTP_PROXY when the
# environment has it.
_OPENER = urllib.request.build_opener(_Stay, urllib.request.ProxyHandler({}))


def http(method: str, path: str, form=None, body=None, cookie: str = ""):
    """(status, headers, text) of one request to the panel, sent as its own
    page sends it, with the panel's own address as its origin."""
    headers = {"Origin": PANEL}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(PANEL + path, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=30) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def session_of(headers) -> str:
    """The name=value of the cookie a sign-in answer sets, or ''."""
    for value in headers.get_all("Set-Cookie") or []:
        return value.split(";", 1)[0].strip()
    return ""


def docker(*args, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def compose(folder: Path, *args, timeout: int = 300, https: bool = False) -> subprocess.CompletedProcess:
    if https:
        files = ["-f", str(folder / "compose.https.yaml"), "-f", str(folder / "compose.https.smoke.yaml")]
    else:
        files = ["-f", str(folder / "compose.yaml"), "-f", str(folder / "compose.smoke.yaml")]
    return subprocess.run(["docker", "compose", "-p", PROJECT, *files, *args],
                          cwd=SERVER.parent, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def write_project(folder: Path, image: str) -> None:
    """compose.yaml and the profile as a person copies them, and beside them
    only what keeps this run apart from a real one, its own image, name and
    ids."""
    for name in ("compose.yaml", "compose.https.yaml", "Caddyfile", "seccomp-chrome.json"):
        shutil.copy2(SERVER / name, folder / name)
    (folder / "data").mkdir()
    lines = ["services:", "  paperpull:", "    image: %s" % image,
             "    container_name: %s" % CONTAINER]
    ids = []
    if hasattr(os, "getuid"):
        # The documents belong to whoever runs this, so the folder can be
        # cleaned up afterwards, as a person's would belong to them.
        ids = ['      PUID: "%d"' % os.getuid(), '      PGID: "%d"' % os.getgid()]
    if ids:
        lines += ["    environment:"] + ids
    (folder / "compose.smoke.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The HTTPS file as a person fills it in, with this computer's name and
    # address in place of a NAS's.
    lines = (["services:", "  paperpull:", "    image: %s" % image,
              "    container_name: %s" % CONTAINER, "    environment:"] + ids
             + ['      PAPERPULL_HOSTS: "%s"' % HTTPS_NAME,
                "  proxy:", "    container_name: %s" % PROXY, "    environment:",
                '      PAPERPULL_ADDRESS: "127.0.0.1"', '      PAPERPULL_NAMES: "%s"' % HTTPS_NAME])
    (folder / "compose.https.smoke.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def running() -> bool:
    """Up, and up since the first start. compose.yaml restarts a container
    that stops, so one that failed can look running again a moment later."""
    r = docker("inspect", "-f", "{{.State.Running}} {{.RestartCount}}", CONTAINER, timeout=30)
    return r.returncode == 0 and r.stdout.split() == ["true", "0"]


def log() -> str:
    r = docker("logs", CONTAINER, timeout=60)
    return r.stdout + r.stderr


def wait_for_panel() -> bool:
    started = time.time()
    while time.time() - started < START_LIMIT:
        if not running():
            return report("panel", False, "the container stopped or restarted before the panel answered")
        try:
            status, _, _ = http("GET", "/login")
            if status in (200, 303):
                return report("panel", True, "answered %d s after the start" % (time.time() - started))
        except OSError:
            pass
        time.sleep(2)
    return report("panel", False, "no answer in %d s" % START_LIMIT)


def first_visit(password: str) -> str:
    """Choose the password the way the first visit does. The session cookie,
    or '' when it did not hold."""
    status, headers, _ = http("GET", "/")
    if not report("gate", status == 303 and headers.get("Location", "").endswith("/setup"),
                  "with no password yet the panel answers %d to %s"
                  % (status, headers.get("Location", "nowhere"))):
        return ""
    status, _, _ = http("GET", "/setup")
    codes = CODE_LINE.findall(log())
    if not report("code", status == 200 and bool(codes),
                  "the setup page answers %d and %s" % (
                      status, "the log holds a setup code" if codes else "the log holds no setup code")):
        return ""
    status, headers, _ = http("POST", "/setup", form={
        "code": codes[-1], "password": password, "again": password})
    cookie = session_of(headers)
    report("setup", status == 303 and bool(cookie),
           "a password chosen with the code from the log, %d and %s"
           % (status, "a session" if cookie else "no session"))
    return cookie


def sign_in(password: str) -> str:
    status, _, _ = http("GET", "/api/providers")
    report("api", status == 401, "not signed in, the API answers %d" % status)
    status, _, _ = http("POST", "/login", form={"password": password + "x"})
    report("wrong", status == 401, "a wrong password answers %d" % status)
    status, headers, _ = http("POST", "/login", form={"password": password})
    cookie = session_of(headers)
    report("sign-in", status == 303 and bool(cookie),
           "the password answers %d with %s" % (status, "a session" if cookie else "no session"))
    return cookie


def set_up_provider(cookie: str) -> None:
    status, _, text = http("GET", "/api/providers", cookie=cookie)
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    report("signed", status == 200 and answer.get("server") is True
           and answer.get("suggested_root") == "/data",
           "signed in, the API answers %d, server %s, folder %s"
           % (status, answer.get("server"), answer.get("suggested_root")))
    # The page may name any folder. On the server every provider goes in
    # the shared folder all the same.
    status, _, text = http("POST", "/api/create", cookie=cookie,
                           body={"root": "/somewhere/else", "providers": [PROVIDER]})
    try:
        made = json.loads(text)
    except ValueError:
        made = {}
    report("provider", status == 200 and made.get("root") == "/data"
           and PROVIDER in (made.get("created") or []),
           "set up %s, %d, in %s" % (PROVIDER, status, made.get("root")))
    r = docker("exec", CONTAINER, "python", "-c",
               "import glob, json; print(json.dumps([json.load(open(p, encoding='utf-8-sig'))"
               ".get('profile_dir') for p in glob.glob('/data/*/config.json')]))", timeout=60)
    try:
        profiles = json.loads(r.stdout)
    except ValueError:
        profiles = []
    report("profile", bool(profiles) and all(str(p).startswith("/profiles/") for p in profiles),
           "its sign-ins go to %s" % (", ".join(map(str, profiles)) or "nowhere"))


def self_test() -> None:
    r = docker("exec", CONTAINER, "python", "/opt/paperpull/server/selftest.py", timeout=600)
    for line in (r.stdout + r.stderr).splitlines():
        print("  " + line, flush=True)
    report("selftest", r.returncode == 0, "the container's own checks, exit %d" % r.returncode)


# -- the setuid sandbox, for a kernel without user namespaces ---------------------


def with_setuid_sandbox(text: str) -> str:
    """A compose file as a person turns on the setuid sandbox, the # taken
    off its two cap_add lines and nothing else changed, or '' when the file
    has no such lines."""
    out, changed = [], 0
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n") in ("    #cap_add:", "    #  - SYS_ADMIN"):
            line = line.replace("#", "", 1)
            changed += 1
        out.append(line)
    return "".join(out) if changed == 2 else ""


def setuid_helpers() -> list:
    """Every copy of Chrome's sandbox helper in the browser volume that has
    its setuid bit, as 'mode owner:group path'."""
    r = docker("exec", CONTAINER, "find", "/browser", "-name", "chrome-sandbox",
               "-perm", "-4000", "-printf", "%m %u:%g %p\\n", timeout=60)
    return [line for line in r.stdout.splitlines() if line.strip()]


def root_alone_phase() -> None:
    """The helper is made setuid only where root alone could have put it.
    The browser volume is root's, so pp can put nothing there, and with the
    Chrome in use given to pp, as a folder pp put in an older volume would
    be, chrome.sh leaves no helper setuid and says why."""
    r = docker("exec", CONTAINER, "stat", "-c", "%u:%g %a", "/browser", timeout=60)
    report("suid-own", r.stdout.strip() == "0:0 755",
           "the browser volume is root's, %s" % (r.stdout.strip() or r.stderr.strip()))
    r = docker("exec", "-u", "pp", CONTAINER, "mkdir", "/browser/planted", timeout=60)
    report("suid-pp", r.returncode != 0, "pp may not put a folder in the browser volume")
    in_use = docker("exec", CONTAINER, "readlink", "-f", "/browser/current", timeout=60).stdout.strip()
    if not report("suid-use", in_use.startswith("/browser/"), "the Chrome in use is %s" % in_use):
        return
    docker("exec", CONTAINER, "chown", "pp:pp", in_use, timeout=60)
    try:
        r = docker("exec", CONTAINER, "/opt/paperpull/server/chrome.sh", timeout=600)
        helpers = setuid_helpers()
        report("suid-ppd", r.returncode == 0 and not helpers
               and "is not set up, since %s belongs to user" % in_use in r.stdout,
               "with the Chrome in use pp's no helper is setuid (%s)" % (", ".join(helpers) or "none"))
    finally:
        docker("exec", CONTAINER, "chown", "0:0", in_use, timeout=60)


def setuid_phase(folder: Path) -> None:
    """The two cap_add lines taken off their #, as SERVER.md tells a person
    with a Synology, make the helper of the Chrome in use setuid root, and
    the self-test still holds. Put back, no copy keeps the bit, not even one
    in an older Chrome's folder. This computer's kernel has user namespaces,
    so Chrome still chooses them here, and the setuid sandbox itself shows
    only on a kernel without them."""
    report("suid-off", not setuid_helpers(), "by default no sandbox helper in the volume is setuid")
    path = folder / "compose.yaml"
    plain = path.read_bytes()
    turned_on = with_setuid_sandbox(plain.decode("utf-8"))
    if not report("cap-file", bool(turned_on), "compose.yaml has the two cap_add lines to uncomment"):
        return
    path.write_bytes(turned_on.encode("utf-8"))
    try:
        r = compose(folder, "up", "-d", timeout=600)
        if not report("cap-up", r.returncode == 0, "compose up with cap_add SYS_ADMIN %s"
                      % ("started it" if r.returncode == 0 else "failed")):
            print(r.stdout + r.stderr, flush=True)
            return
        if not wait_for_panel():
            return
        helpers = setuid_helpers()
        report("suid-on", len(helpers) == 1 and helpers[0].startswith("4755 root:root ")
               and "setuid sandbox helper is set up" in log(),
               "setuid helpers %s" % (", ".join(helpers) or "none"))
        self_test()
        root_alone_phase()
        # An older Chrome's folder left with its helper setuid, as a version
        # kept beside a newer one would be after the opt-in.
        docker("exec", CONTAINER, "sh", "-c",
               "mkdir -p /browser/0.0.0.0/opt/google/chrome"
               " && touch /browser/0.0.0.0/opt/google/chrome/chrome-sandbox"
               " && chmod 4755 /browser/0.0.0.0/opt/google/chrome/chrome-sandbox", timeout=60)
    finally:
        path.write_bytes(plain)
    r = compose(folder, "up", "-d", timeout=600)
    if report("cap-out", r.returncode == 0, "compose up without cap_add %s"
              % ("started it" if r.returncode == 0 else "failed")) and wait_for_panel():
        helpers = setuid_helpers()
        report("no-suid", not helpers, "with the lines put back no helper is setuid (%s)"
               % (", ".join(helpers) or "none left"))


# -- the HTTPS file ------------------------------------------------------------------

def root_certificate(folder: Path) -> Path | None:
    """Caddy's root certificate, copied out the way SERVER.md tells a person
    to, once Caddy has made it."""
    started = time.time()
    while time.time() - started < 120:
        r = docker("exec", PROXY, "cat", ROOT_CERT, timeout=30)
        if r.returncode == 0 and "BEGIN CERTIFICATE" in r.stdout:
            path = folder / "paperpull-root.crt"
            path.write_text(r.stdout, encoding="ascii")
            return path
        time.sleep(2)
    return None


def https(context, method: str, path: str, form=None, cookie: str = ""):
    """(status, headers, text) of one request to the panel through Caddy,
    sent as its own page sends it."""
    headers = {"Origin": HTTPS_PANEL}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = cookie
    conn = HTTPSConnection(HTTPS_NAME, 8765, context=context, timeout=30)
    try:
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        return r.status, r.headers, r.read().decode("utf-8", "replace")
    finally:
        conn.close()


def screen_over_wss(context, cookie: str):
    """(the first line of the answer, the screen's version, the ways in it
    offers once told this end's version) for a Browser Screen connection
    over wss through Caddy, as noVNC opens it. A screen turned away sends
    its version too, then no way in, a count of 0 and the reason."""
    raw = socket.create_connection((HTTPS_NAME, 8765), timeout=30)
    with context.wrap_socket(raw, server_hostname=HTTPS_NAME) as s:
        lines = ["GET /screen/websockify HTTP/1.1", "Host: %s:8765" % HTTPS_NAME,
                 "Upgrade: websocket", "Connection: Upgrade",
                 "Sec-WebSocket-Key: " + base64.b64encode(os.urandom(16)).decode("ascii"),
                 "Sec-WebSocket-Version: 13", "Sec-WebSocket-Protocol: binary",
                 "Origin: " + HTTPS_PANEL] + (["Cookie: " + cookie] if cookie else [])
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        got = b""
        while b"\r\n\r\n" not in got:
            piece = s.recv(4096)
            if not piece:
                break
            got += piece
        head, _, rest = got.partition(b"\r\n\r\n")
        first = head.split(b"\r\n", 1)[0].decode("latin-1")
        if first.split(" ")[1:2] != ["101"]:
            return first, b"", b""

        def held(n):
            nonlocal rest
            while len(rest) < n:
                piece = s.recv(4096)
                if not piece:
                    raise OSError("the screen closed before its next message")
                rest += piece

        def message():
            """One frame from the server, which a server never masks."""
            nonlocal rest
            held(2)
            size, at = rest[1] & 0x7F, 2
            if size == 126:
                held(4)
                size, at = int.from_bytes(rest[2:4], "big"), 4
            elif size == 127:
                held(10)
                size, at = int.from_bytes(rest[2:10], "big"), 10
            held(at + size)
            payload, rest = rest[at:at + size], rest[at + size:]
            return payload

        version = message()
        # This end's version, as a binary frame masked as every frame from a
        # browser is.
        mask, said = os.urandom(4), b"RFB 003.008\n"
        s.sendall(bytes([0x82, 0x80 | len(said)]) + mask
                  + bytes(b ^ mask[i % 4] for i, b in enumerate(said)))
        return first, version, message()


# Five wrong passwords and then the sixth, sent from inside the panel's own
# container through Caddy, so Caddy sees another address than this
# computer's. Its certificate is not checked, since the point here is the
# address and not the certificate.
_WRONG_FROM_ELSEWHERE = r"""
import socket, ssl, sys
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
body = b"password=not+it"
out = []
for _ in range(int(sys.argv[1])):
    with ctx.wrap_socket(socket.create_connection(("proxy", 8765), timeout=30),
                         server_hostname="localhost") as s:
        s.sendall(b"POST /login HTTP/1.1\r\nHost: localhost:8765\r\n"
                  b"Origin: https://localhost:8765\r\nConnection: close\r\n"
                  b"Content-Type: application/x-www-form-urlencoded\r\n"
                  b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
        out.append(s.recv(64).split(b" ")[1].decode())
print(" ".join(out))
"""


def https_phase(folder: Path, image: str, password: str) -> None:
    r = compose(folder, "up", "-d", "--remove-orphans", timeout=600, https=True)
    if not report("https-up", r.returncode == 0,
                  "the same project moved to compose.https.yaml, %s"
                  % ("started" if r.returncode == 0 else "failed")):
        print(r.stdout + r.stderr, flush=True)
        return
    root = root_certificate(folder)
    if not report("root", root is not None, "Caddy's root certificate copied out of %s" % PROXY):
        return
    context = ssl.create_default_context(cafile=str(root))
    # The panel's container was made anew and starts as it did before, so
    # until it answers, Caddy says it cannot reach it, 502.
    started, status = time.time(), None
    while time.time() - started < START_LIMIT and status in (None, 502, 503, 504):
        try:
            status = https(context, "GET", "/login")[0]
        except OSError:
            status = None
        if status in (None, 502, 503, 504):
            if not running():
                break
            time.sleep(2)
    if not report("https", status == 200,
                  "the panel answers by HTTPS through Caddy, %s, its certificate checked "
                  "against Caddy's own authority, and still has its password" % status):
        return
    try:
        conn = HTTPConnection("127.0.0.1", 8765, timeout=30)
        conn.request("GET", "/login")
        answer = conn.getresponse()
        plain = (answer.status, answer.read().decode("utf-8", "replace").strip())
        conn.close()
    except OSError as e:
        plain = (None, str(e))
    report("no-plain", plain[0] == 400 and "HTTPS" in plain[1],
           "plain HTTP to the published port meets Caddy, %s %s" % plain)
    r = docker("port", CONTAINER, timeout=30)
    report("no-port", r.returncode == 0 and not r.stdout.strip(),
           "the panel's container publishes %s" % (r.stdout.strip() or "no port"))
    # Plain HTTP to the panel itself, from inside its project's network, as
    # Caddy reaches it, and from a container on another network.
    r = docker("exec", PROXY, "wget", "-q", "-O", "-", "-T", "10", "http://paperpull:8765/login",
               timeout=60)
    inside = r.returncode == 0 and "Sign in" in r.stdout
    r = docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
               CONTAINER, timeout=30)
    address = (r.stdout.split() or [""])[0]
    r = docker("run", "--rm", "--network", "bridge", "--entrypoint", "python", image, "-c",
               "import socket\ntry:\n    socket.create_connection((%r, 8765), 5)\n    print('reached')\n"
               "except OSError as e:\n    print('not reached', e)" % address, timeout=120)
    report("isolated", inside and address and "not reached" in r.stdout,
           "plain HTTP reaches the panel from its project's network %s, and from another "
           "network %s" % ("yes" if inside else "NO", r.stdout.strip() or r.stderr.strip()))

    status, headers, _ = https(context, "POST", "/login", form={"password": password})
    cookies = headers.get_all("Set-Cookie") or []
    parts = [part.strip().lower() for part in (cookies[0] if cookies else "").split(";")]
    named = parts[0].split("=", 1)[0] if parts else ""
    report("cookie", status == 303 and len(cookies) == 1 and named == "__host-paperpull_session"
           and {"secure", "httponly", "samesite=strict", "path=/"} <= set(parts)
           and not any(part.startswith("domain=") for part in parts),
           "signing in by HTTPS sets %s" % "; ".join(
               [cookies[0].split("=", 1)[0]] + [p for p in parts[1:] if not p.startswith("max-age")])
           if cookies else "signing in by HTTPS sets no cookie, %s" % status)
    cookie = cookies[0].split(";", 1)[0] if cookies else ""
    status, _, text = https(context, "GET", "/api/providers", cookie=cookie)
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    report("tls-api", status == 200 and answer.get("server") is True,
           "signed in by HTTPS, the API answers %d, server %s" % (status, answer.get("server")))
    try:
        first, version, ways = screen_over_wss(context, cookie)
    except OSError as e:
        first, version, ways = str(e), b"", b""
    report("wss", first.split(" ")[1:2] == ["101"] and version.startswith(b"RFB 003.")
           and ways[:1] not in (b"", b"\x00"),
           "the Browser Screen over wss answers %r, the screen says %r and offers %d ways in"
           % (first, version[:12], ways[0] if ways else 0))
    try:
        first, _, _ = screen_over_wss(context, "")
    except OSError as e:
        first = str(e)
    report("wss-gate", first.split(" ")[1:2] != ["101"],
           "with no session the Browser Screen over wss answers %r" % first)

    r = docker("exec", CONTAINER, "python", "-c", _WRONG_FROM_ELSEWHERE,
               str(server_mode_free_tries() + 1), timeout=120)
    elsewhere = r.stdout.split()
    status = https(context, "POST", "/login", form={"password": password})[0]
    report("per-ip", elsewhere[:-1] == ["401"] * (len(elsewhere) - 1) and elsewhere[-1:] == ["429"]
           and status == 303,
           "wrong passwords from another browser behind Caddy answer %s, and this one still "
           "signs in, %d" % (" ".join(elsewhere) or r.stderr.strip()[-200:], status))
    self_test()


def server_mode_free_tries() -> int:
    """How many wrong passwords an address may send before it waits, as the
    panel sets it, read rather than imported."""
    text = (SERVER.parent / "gui" / "server_mode.py").read_text(encoding="utf-8")
    return int(re.search(r"^FREE_TRIES = (\d+)$", text, re.M).group(1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", default="paperpull-server:dev",
                    help="the image to start, default %(default)s")
    ap.add_argument("--keep", action="store_true",
                    help="leave the project running afterwards, to look at it")
    args = ap.parse_args(argv)
    # The container's log is printed as it is, and a console that cannot
    # show a character in it should not end the run.
    sys.stdout.reconfigure(errors="replace")

    folder = Path(tempfile.mkdtemp(prefix="paperpull-smoke-"))
    password = secrets.token_urlsafe(18)
    try:
        write_project(folder, args.image)
        r = compose(folder, "up", "-d", timeout=600)
        if report("start", r.returncode == 0,
                  "compose up %s" % ("started it" if r.returncode == 0 else "failed")):
            if wait_for_panel():
                if first_visit(password):
                    cookie = sign_in(password)
                    if cookie:
                        set_up_provider(cookie)
                self_test()
                if not FAILED:
                    setuid_phase(folder)
                if not FAILED:
                    https_phase(folder, args.image, password)
        else:
            print(r.stdout + r.stderr, flush=True)
        if FAILED:
            print("\nthe container's log, last lines", flush=True)
            for line in log().splitlines()[-60:]:
                print("  " + line, flush=True)
    finally:
        if args.keep:
            print("left running, take it down with\n  docker compose -p %s -f %s down -v"
                  % (PROJECT, folder / "compose.https.yaml"))
        else:
            # The HTTPS file names every volume the plain one does, and
            # Caddy's besides.
            down = compose(folder, "down", "-v", "--remove-orphans", timeout=300, https=True)
            if down.returncode:
                print(down.stdout + down.stderr, flush=True)
            shutil.rmtree(folder, ignore_errors=True)
    print(json.dumps({"passed": not FAILED, "failed": FAILED}), flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
