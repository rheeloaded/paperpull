"""Every route the panel answers, asked for by what it does.

The panel runs the apps' commands against the person's signed-in browser,
so a request another page set off has to change nothing. A review on
2026-10-06 found three ways one could. A website that points a name of its
own at 127.0.0.1 makes its page the panel's own origin as far as the
browser knows, and the panel never read the name a request was made to, so
a GET from that page with no Referer started a run. An Origin of null,
which a page can arrange to send, parsed to an empty host, and the empty
host passed for this computer. And no answer said it may not be shown in
another site's frame, so a click on Run All could be borrowed.

The routes come from the app itself, so one added later is in the census at
once and fails it until it is described here. Each is described by what it
does in each edition, and the census checks the description. The request
the panel's own page would send has to be seen changing something on a
route said to change things, which is what gives the rest of the census
its meaning there, and has to change nothing on a route said to read. A
page, a route a browser opens by its address, is spared the Origin checks
only because it is seen to change nothing. Every other route is asked for
by a page of the panel's own, by script or by a form, which the browser
marks same-origin, so a request it marks none, the browser opening an
address by itself as it does for a link opened from an email, a chat or a
PDF, is one of those refused there. Then every request that has to be
refused goes to every route, and each one has to be refused, change
nothing and still say that no other site may frame it. Every answer, the
panel's own page's and every refusal alike, also has to say nosniff, and
no-store unless it is one of the few that are the same for everyone.

Changing something means writing, moving or deleting a file, starting a
program, opening the Browser Screen's connection, or changing what the
panel holds in memory, its sample mode, its last spreadsheet, its sessions
and its count of wrong passwords. Files are seen through an audit hook, so
a write is seen however it is reached. A change a route leaves to a thread
that goes on after its answer is not seen. No program is really started,
since subprocess.Popen is a stand-in here that notes what it was asked
for, and nothing is served on a port, since each request goes to the app
in this process with every setting under a temp folder.
"""
import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import server_mode  # noqa: E402

PASSWORD = "an invented passphrase"
SHOP = "Shop Receipts"
OWN = {"desktop": "127.0.0.1:8765", "server": "nas.local:8765"}
ELSEWHERE = "rebind.example:8765"
REFUSED = {400, 401, 403}


# -- what a request changed ------------------------------------------------------------

_CHANGES = {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.truncate", "os.link",
            "os.symlink", "os.chmod", "os.utime", "shutil.copyfile", "shutil.copytree",
            "shutil.move", "shutil.rmtree", "subprocess.Popen", "os.startfile", "os.system",
            "os.posix_spawn", "os.exec", "os.spawn", "os.kill", "os.putenv", "os.unsetenv"}
_WRITING = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# One list per request being watched, the newest last. Empty, nothing is
# watched, and the hook returns at once.
_SEEN: list = []


def _audit(event, args):
    if not _SEEN:
        return
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        writes = (any(c in mode for c in "wax+") if isinstance(mode, str)
                  else bool((flags or 0) & _WRITING))
        if writes:
            _SEEN[-1].append("wrote %s" % path)
    elif event in _CHANGES:
        _SEEN[-1].append("%s %s" % (event, args[0] if args else ""))


sys.addaudithook(_audit)


def _note(what: str) -> None:
    if _SEEN:
        _SEEN[-1].append(what)


class Started:
    """Stands in for subprocess.Popen, so the census starts no program, no
    app and no file manager, and notes that one was asked for."""

    def __init__(self, args, *_, **__):
        _note("started %s" % (args[0] if isinstance(args, (list, tuple)) else args))
        self.args, self.returncode, self.pid = args, 0, 0
        self.stdin, self.stdout, self.stderr = io.StringIO(), io.StringIO(""), io.StringIO("")

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def communicate(self, input=None, timeout=None):
        return "", ""

    def terminate(self):
        pass

    kill = terminate

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def held():
    """What the panel holds in memory that a request may change, the
    sessions the Browser Screen opens for among it."""
    return (app_module._SAMPLE, app_module._LAST_EXPORT, tuple(sorted(app_module._RUNNING)),
            tuple(sorted(server_mode._SESSIONS)),
            # Read from each session as it is, since asking screen_open
            # would end a session that no longer holds, a change of its own.
            tuple(sorted(t for t, s in server_mode._SESSIONS.items()
                         if time.time() - s["screen"] <= server_mode.SCREEN_IDLE_SECONDS)),
            tuple(sorted((k, v[0]) for k, v in server_mode._FAILS.items())),
            server_mode._SETUP["code"])


# -- asking the app, in this process ----------------------------------------------------

def scope_for(kind: str, method: str, target: str, headers: list) -> dict:
    path, _, query = target.partition("?")
    return {"type": kind, "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": method, "scheme": "http" if kind == "http" else "ws",
            "path": path, "raw_path": path.encode(), "query_string": query.encode(),
            "root_path": "", "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
            "subprotocols": [],
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers]}


async def _http(scope: dict, body: bytes) -> dict:
    answer = {"status": None, "headers": [], "body": b""}
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

    await asyncio.wait_for(app_module.app(scope, receive, send), 60)
    return answer


async def _websocket(scope: dict, listening: socket.socket) -> dict:
    """A connection to the Browser Screen, with a screen sharing server of its
    own on the socket given, which notes each connection and closes it at
    once."""
    async def screen_sharing(reader, writer):
        _note("connected to the screen")
        writer.close()

    sharing = await asyncio.start_server(screen_sharing, sock=listening)
    sent = []
    ended = asyncio.Event()
    told = []

    async def receive():
        if not told:
            told.append(True)
            return {"type": "websocket.connect"}
        await ended.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(message):
        sent.append(message)
        if message["type"] == "websocket.close":
            ended.set()

    try:
        await asyncio.wait_for(app_module.app(scope, receive, send), 60)
    finally:
        sharing.close()
        await sharing.wait_closed()
    return {"status": None, "headers": [], "body": b"", "sent": sent}


# -- every route, by what it does --------------------------------------------------------
#
# ask is what the panel's own page asks for, body what it sends, form when
# it is a form the page posts. desktop and server say what the route does
# in each edition. A page is opened by its address. before readies the
# sandbox, and is run once before any request.

def _no_password(box) -> None:
    data = server_mode._read()
    data.pop("password", None)
    server_mode._write(data)
    box.code = server_mode.setup_code()


def _screen_unused(box) -> None:
    """The session gone unused too long for the Browser Screen, so the
    password typed again is what opens it."""
    server_mode._SESSIONS[box.token]["screen"] -= 2 * server_mode.SCREEN_IDLE_SECONDS


def _history(box) -> dict:
    """A history file naming a provider the sandbox has not set up, as the
    page sends it, so an import sets one up."""
    import base64
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "schema": 2, "source_root": "/elsewhere",
            "apps": [{"provider": "GitHub", "kind": "RECEIPT", "account": "primary",
                      "folder": "GitHub Receipts", "file": "apps/0/progress.json"}]}))
        z.writestr("apps/0/progress.json", json.dumps({"G1": {
            "state": "Completed", "downloaded_ok": True, "pdf_path": ""}}))
    return {"file": base64.b64encode(buf.getvalue()).decode("ascii"), "root": ""}


ROUTES = {
    ("GET", "/api/apps"): dict(desktop="changes", server="changes"),
    ("POST", "/api/export"): dict(body={"csv": True}, desktop="changes", server="changes"),
    ("GET", "/api/export/providers"): dict(desktop="reads", server="reads"),
    ("GET", "/api/export/transactions/providers"): dict(desktop="reads", server="reads"),
    ("GET", "/api/export/transactions"): dict(ask="/api/export/transactions?csv=1",
                                              desktop="changes", server="changes"),
    ("POST", "/api/export/reveal"): dict(body={}, desktop="changes", server="reads"),
    ("GET", "/api/export/download"): dict(desktop="reads", server="reads"),
    ("GET", "/api/status"): dict(desktop="reads", server="reads"),
    ("GET", "/api/accounts"): dict(desktop="reads", server="reads"),
    ("POST", "/api/reveal"): dict(body={"app": SHOP, "account": "primary"},
                                  desktop="changes", server="reads"),
    ("GET", "/api/saved-in"): dict(ask="/api/saved-in?app=Shop%20Receipts", desktop="reads", server="reads"),
    ("POST", "/api/sample"): dict(body={"on": True}, desktop="changes", server="changes"),
    ("GET", "/api/root"): dict(desktop="reads", server="reads"),
    ("POST", "/api/root"): dict(body=lambda box: {"root": str(box.elsewhere)},
                                desktop="changes", server="reads"),
    ("GET", "/api/providers"): dict(desktop="reads", server="reads"),
    ("POST", "/api/create"): dict(body=lambda box: {"root": str(box.root), "providers": ["github"],
                                                    "owner": ""},
                                  desktop="changes", server="changes"),
    ("POST", "/api/account"): dict(body={"app": SHOP, "label": "second", "owner": ""},
                                   desktop="changes", server="changes"),
    ("GET", "/api/history/export"): dict(desktop="reads", server="reads"),
    ("POST", "/api/history/plan"): dict(body=_history, desktop="reads", server="reads"),
    ("POST", "/api/history/import"): dict(body=_history, desktop="changes", server="changes"),
    ("GET", "/api/failure/latest"): dict(ask="/api/failure/latest?app=Shop%20Receipts",
                                         desktop="reads", server="reads"),
    ("POST", "/api/failure/reveal"): dict(body={"app": SHOP}, desktop="changes", server="reads"),
    ("GET", "/api/failure/download"): dict(ask="/api/failure/download?app=Shop%20Receipts",
                                           desktop="reads", server="reads"),
    ("GET", "/api/diagnostics/download"): dict(
        ask="/api/diagnostics/download?app=Shop%20Receipts&action=diagnose",
        desktop="reads", server="reads"),
    # The server writes the zip it hands over, in a folder of its own that
    # goes once the answer is sent.
    ("GET", "/api/aside/download"): dict(ask="/api/aside/download?app=Shop%20Receipts",
                                         desktop="reads", server="changes"),
    ("POST", "/api/record/stop"): dict(body={"app": SHOP}, desktop="changes", server="changes"),
    ("POST", "/api/remove"): dict(body={"app": SHOP}, desktop="changes", server="changes"),
    # A real provider, because the server runs only the code the image ships
    # and refuses a folder that maps to no shipped provider, so a made-up name
    # would change nothing there and the refusals would prove nothing.
    ("GET", "/api/run"): dict(ask="/api/run?app=Kroger%20Receipts&action=pilot",
                              desktop="changes", server="changes"),
    ("POST", "/api/run"): dict(body={"app": "Kroger Receipts", "action": "pilot"},
                               desktop="changes", server="changes"),
    # Review Names starts the app as a run does, the list step included, so
    # a real receipt provider for the same reason as a run.
    ("POST", "/api/review-names"): dict(body={"app": "Kroger Receipts"},
                                        desktop="changes", server="changes"),
    ("POST", "/api/review-names/apply"): dict(
        body={"app": "Kroger Receipts",
              "answers": [{"id": "x", "number": "1", "summary": "Garden Hose"}]},
        desktop="changes", server="changes"),
    ("GET", "/api/naming"): dict(ask="/api/naming?app=Shop%20Receipts",
                                 desktop="reads", server="reads"),
    ("POST", "/api/naming/preview"): dict(body={"app": SHOP, "pattern": "{date} {provider}"},
                                          desktop="reads", server="reads"),
    ("POST", "/api/naming/save"): dict(body={"app": SHOP, "scope": "own",
                                             "pattern": "{date} {provider}"},
                                       desktop="changes", server="changes"),
    ("GET", "/api/documents"): dict(ask="/api/documents?app=Shop%20Receipts",
                                    desktop="reads", server="reads"),
    # A folder inside the data folder, which the server takes too.
    ("POST", "/api/documents"): dict(body=lambda box: {"app": SHOP, "account": "primary",
                                                       "folder": str(box.root / "Documents")},
                                     desktop="changes", server="changes"),
    # The one documents folder, written to the settings file and the configs.
    ("POST", "/api/documents/root"): dict(body=lambda box: {"folder": str(box.root / "Documents")},
                                          desktop="changes", server="changes"),
    # Accepting the terms writes the answer to the settings file.
    ("POST", "/api/terms"): dict(body={"accepted": app_module.TERMS_VERSION},
                                 desktop="changes", server="changes"),
    ("GET", "/"): dict(page=True, desktop="reads", server="reads"),
    ("GET", "/favicon.ico"): dict(page=True, desktop="reads", server="reads"),
    ("GET", "/login"): dict(page=True, desktop="reads", server="reads"),
    ("POST", "/login"): dict(form=True, body={"password": PASSWORD},
                             desktop="reads", server="changes"),
    ("GET", "/setup"): dict(page=True, desktop="reads", server="reads"),
    ("POST", "/setup"): dict(form=True, before=_no_password,
                             body=lambda box: {"code": box.code or "AAAA-BBBB-CCCC",
                                               "password": PASSWORD + " anew",
                                               "again": PASSWORD + " anew"},
                             desktop="reads", server="changes"),
    ("POST", "/logout"): dict(form=True, body={}, desktop="reads", server="changes"),
    ("GET", "/screen"): dict(page=True, desktop="reads", server="reads"),
    ("GET", "/screen/novnc/{rest:path}"): dict(page=True, ask="/screen/novnc/vnc.html",
                                               desktop="reads", server="reads"),
    ("POST", "/screen/again"): dict(form=True, before=_screen_unused,
                                    body={"password": PASSWORD, "to": "dock"},
                                    desktop="reads", server="changes"),
    ("WEBSOCKET", "/screen/websockify"): dict(desktop="reads", server="changes"),
}


def every_route() -> set:
    out = set()
    for route in app_module.app.routes:
        methods = getattr(route, "methods", None)
        if methods:
            out.update((method, route.path) for method in methods)
        else:
            out.add(("WEBSOCKET", route.path))
    return out


# -- the sandbox ---------------------------------------------------------------------

STORAGE = 'SPEC = dict(provider="Shop", kind=RECEIPT)\n'
HISTORY = ("Account Holder,Purchase Date,Order or Receipt Number,Item Name,Quantity,"
           "Unit Price,Line Item Total,Order Total,Purchase Type,Fulfillment Method,"
           "Order Status,Return Status,Purchase Summary\n"
           "Pat Example,2026-01-02,A1,A thing,1,2.50,2.50,2.50,In-Store,,Complete,,Groceries\n")


class Box:
    pass


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """The panel with everything it might read or write under tmp_path, and
    an apps root holding a provider of every kind a route needs."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))
    for name in ("APPS_ROOT", "PAPERPULL_SERVER", "PAPERPULL_PASSWORD", "PAPERPULL_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPERPULL_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("PAPERPULL_PLUGINS", str(tmp_path / "plugins"))
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    monkeypatch.setenv("PAPERPULL_VNC_PORT", "1")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(subprocess, "Popen", Started)
    # Every app runs with this Python, the way the packaged build runs them.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    for name, value in (("_SAMPLE", None), ("_RUNNING", set()), ("_REFRESHED_ROOTS", set()),
                        ("_STATUS_MOD", None), ("_EXPORT_MOD", None), ("_ACCOUNT_MOD", None)):
        monkeypatch.setattr(app_module, name, value)
    server_mode._SESSIONS.clear()
    server_mode._FAILS.clear()
    server_mode._SETUP["code"] = None

    b = Box()
    b.root = tmp_path / "apps"
    b.elsewhere = tmp_path / "Elsewhere"
    b.elsewhere.mkdir()
    b.token, b.code = "", ""
    shop = b.root / SHOP
    (shop / "Diagnostics").mkdir(parents=True)
    (shop / "shop_receipts.py").write_text("print('a run')\n", encoding="utf-8")
    (shop / "storage.py").write_text(STORAGE, encoding="utf-8")
    (shop / "config.json").write_text('{"output_dir": ".", "owner": "Pat Example"}',
                                      encoding="utf-8")
    (shop / "progress.json").write_text(json.dumps({"A1": {
        "date": "2026-01-02", "summary": "a thing", "downloaded_ok": True,
        "pdf_filename": "2026-01-02 Shop Receipt.pdf"}}), encoding="utf-8")
    (shop / "Shop Order History.csv").write_text(HISTORY, encoding="utf-8")
    (shop / "Diagnostics" / "failure-run-1.json").write_text('{"step": "a step"}',
                                                             encoding="utf-8")
    (shop / "Diagnostics" / "survey-diagnose-20260101-100000.json").write_text(
        '{"step": "survey the page"}', encoding="utf-8")
    (shop / "Manual Review").mkdir()
    (shop / "Manual Review" / "2026-01-02 Shop Receipt.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    # An install of a real provider whose code is older than the template,
    # which is what the app list brings up to date.
    app_module.create_install(b.root, "kroger")
    entry = b.root / "Kroger Receipts" / "kroger_receipts.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# older\n", encoding="utf-8")
    sheet = b.root / "All Purchases.xlsx"
    sheet.write_bytes(b"a spreadsheet")
    monkeypatch.setattr(app_module, "_LAST_EXPORT", sheet)
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text("<title>noVNC</title>", encoding="utf-8")
    (tmp_path / "plugins").mkdir()
    app_module._write_settings({"apps_root": str(b.root)})

    def serve():
        monkeypatch.setenv("PAPERPULL_SERVER", "1")
        monkeypatch.setenv("APPS_ROOT", str(b.root))
        server_mode.set_password(PASSWORD)
        b.token = server_mode.new_session()
    b.serve = serve
    return b


def ask(box, edition: str, key: tuple, headers: list):
    """(answer, what changed) for one request to one route."""
    method, path = key
    how = ROUTES[key]
    headers = list(headers)
    body = how.get("body")
    body = body(box) if callable(body) else body
    raw = b""
    if body is not None:
        if how.get("form"):
            raw, kind = urllib.parse.urlencode(body).encode(), "application/x-www-form-urlencoded"
        else:
            raw, kind = json.dumps(body).encode(), "application/json"
        headers += [("content-type", kind), ("content-length", str(len(raw)))]
    if edition == "server" and box.token:
        headers.append(("cookie", "%s=%s" % (server_mode.SESSION_COOKIE, box.token)))
    target = how.get("ask", path)
    if method == "WEBSOCKET":
        # Bound, and its port handed to the panel, before anything is
        # watched, since setting an environment variable counts as a change.
        listening = socket.socket()
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        os.environ["PAPERPULL_VNC_PORT"] = str(listening.getsockname()[1])
    before = held()
    _SEEN.append([])
    try:
        if method == "WEBSOCKET":
            answer = asyncio.run(_websocket(scope_for("websocket", "GET", target, headers),
                                            listening))
        else:
            answer = asyncio.run(_http(scope_for("http", method, target, headers), raw))
    finally:
        changed = _SEEN.pop()
    if held() != before:
        changed.append("changed what the panel holds in memory")
    return answer, changed


# -- the requests ------------------------------------------------------------------------

def own_page(edition: str, method: str, page: bool) -> list:
    """What the panel's own page sends, or a browser asked for a page by its
    address."""
    host = OWN[edition]
    if page:
        return [("host", host), ("sec-fetch-site", "none")]
    headers = [("host", host), ("sec-fetch-site", "same-origin")]
    if method in ("GET", "HEAD"):
        return headers + [("referer", "http://%s/" % host)]
    return headers + [("origin", "http://%s" % host), ("referer", "http://%s/" % host)]


def to_refuse(edition: str, page: bool) -> list:
    """(what it is, its headers) for every request that has to be refused."""
    own = OWN[edition]
    out = [
        ("a page that pointed its own name here, sending Origin null",
         [("host", ELSEWHERE), ("sec-fetch-site", "same-origin"), ("origin", "null")]),
        ("a page that pointed its own name here, with no Origin and no Referer",
         [("host", ELSEWHERE), ("sec-fetch-site", "same-origin")]),
        ("a page that pointed its own name here, with its own Origin",
         [("host", ELSEWHERE), ("sec-fetch-site", "same-origin"),
          ("origin", "http://" + ELSEWHERE)]),
        ("a request with no Host", [("sec-fetch-site", "same-origin")]),
    ]
    if page:
        return out
    return out + [
        ("Origin null", [("host", own), ("sec-fetch-site", "same-origin"), ("origin", "null")]),
        ("Origin null from a browser that sends no Sec-Fetch-Site",
         [("host", own), ("origin", "null")]),
        ("an empty Origin", [("host", own), ("sec-fetch-site", "same-origin"), ("origin", "")]),
        ("another port of the same address",
         [("host", own), ("origin", "http://%s:3000" % own.split(":")[0])]),
        ("another site's Origin", [("host", own), ("origin", "https://evil.example")]),
        ("another site's Referer", [("host", own), ("referer", "https://evil.example/page")]),
        ("another site, by Sec-Fetch-Site", [("host", own), ("sec-fetch-site", "cross-site")]),
        ("a link opened from outside the browser", [("host", own), ("sec-fetch-site", "none")]),
    ]


# The answers the same for everyone, which a browser may keep.
ANYONES = ("/favicon.ico", "/screen/novnc/{rest:path}")


def header_problem(path: str, answer: dict) -> str:
    """What is wrong with what an answer says about frames, about the kind
    of file it is and about keeping a copy, or "". The frame policy stands
    beside any other policy the answer carries. Every answer says nosniff,
    and every one but those the same for everyone says no-store."""
    if answer.get("sent") is not None:
        return ""
    own = path.startswith("/screen/novnc/") or path == "/screen/again"
    frames = [v for k, v in answer["headers"] if k == "x-frame-options"]
    if frames != ["SAMEORIGIN" if own else "DENY"]:
        return "X-Frame-Options was %r" % frames
    policies = [v for k, v in answer["headers"] if k == "content-security-policy"]
    if ("frame-ancestors 'self'" if own else "frame-ancestors 'none'") not in policies:
        return "no frame-ancestors policy among %r" % policies
    sniffing = [v for k, v in answer["headers"] if k == "x-content-type-options"]
    if sniffing != ["nosniff"]:
        return "X-Content-Type-Options was %r" % sniffing
    keeping = [v for k, v in answer["headers"] if k == "cache-control"]
    if path not in ANYONES and (len(keeping) != 1 or "no-store" not in keeping[0]):
        return "Cache-Control was %r" % keeping
    return ""


def refused(answer: dict, absent: bool) -> bool:
    """Whether the panel refused a request. A route that is not there in
    this edition answers a refused request as it answers every other, 404."""
    sent = answer.get("sent")
    if sent is not None:
        return (not any(m["type"] == "websocket.accept" for m in sent)
                and any(m["type"] == "websocket.close" and m.get("code") == 1008 for m in sent))
    return answer["status"] in REFUSED or (absent and answer["status"] == 404)


def own_page_problems(how: dict, edition: str, path: str, answer: dict, changed: list) -> list:
    problems = []
    if answer.get("sent") is None and answer["status"] in REFUSED:
        problems.append("the panel's own page was refused, %s %s"
                        % (answer["status"], answer["body"][:200]))
    if how[edition] == "changes" and not changed:
        problems.append("the panel's own page was seen changing nothing, so the refusals "
                        "prove nothing here")
    if how[edition] == "reads" and changed:
        problems.append("it is said to change nothing, and changed %s" % changed)
    bad_frame = header_problem(path, answer)
    if bad_frame:
        problems.append("the answer to the panel's own page, %s" % bad_frame)
    return problems


CASES = [(edition, key) for edition in ("desktop", "server") for key in ROUTES]


@pytest.mark.parametrize("edition, key", CASES,
                         ids=["%s %s %s" % (e, m, p) for e, (m, p) in CASES])
def test_a_route_does_what_it_says_and_nothing_for_a_request_it_refuses(box, edition, key):
    how = ROUTES[key]
    if edition == "server":
        box.serve()
    if how.get("before") and edition == "server":
        how["before"](box)
    method, path = key
    page = bool(how.get("page"))
    own = own_page(edition, method, page)
    problems = []
    # A route that only reads is asked first, which changes nothing and says
    # whether it is there at all in this edition. One that changes something
    # is asked last, so that every refused request meets it as it was.
    absent = False
    if how[edition] == "reads":
        answer, changed = ask(box, edition, key, own)
        problems += own_page_problems(how, edition, path, answer, changed)
        absent = answer.get("status") == 404
    for what, headers in to_refuse(edition, page):
        answer, changed = ask(box, edition, key, headers)
        if not refused(answer, absent):
            problems.append("%s was answered %s" % (what, answer["status"] or answer.get("sent")))
        if changed:
            problems.append("%s changed something, %s" % (what, changed))
        bad_frame = header_problem(path, answer)
        if bad_frame:
            problems.append("the answer to %s, %s" % (what, bad_frame))
    if how[edition] == "changes":
        answer, changed = ask(box, edition, key, own)
        problems += own_page_problems(how, edition, path, answer, changed)
    assert not problems, "\n".join(problems)


def test_every_route_the_panel_answers_is_in_the_census():
    routes = every_route()
    assert routes - set(ROUTES) == set(), "not described here, so not checked"
    assert set(ROUTES) - routes == set(), "described here, and no longer a route"


def test_every_route_of_the_api_carries_the_guard():
    """The census sends what has to be refused. This says the guard is what
    refuses it, on every route a page opens by script, a new one included."""
    missing = []
    for route in app_module.app.routes:
        if getattr(route, "path", "").startswith("/api/"):
            calls = {d.call for d in route.dependant.dependencies}
            if app_module._same_origin_only not in calls:
                missing.append(route.path)
    assert not missing, "these answer any page: %s" % missing


def test_a_page_is_only_a_route_that_changes_nothing():
    """A route a browser opens by its address cannot ask where the request
    came from, so the census spares it the Origin checks and lets the
    browser say it opened the address by itself. That is safe only for a
    route that changes nothing, in either edition."""
    for key, how in ROUTES.items():
        if how.get("page"):
            assert how["desktop"] == how["server"] == "reads", key
