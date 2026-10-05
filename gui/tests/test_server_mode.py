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


def ask(url, method="GET", form=None, headers=None, session=None, body=None):
    """(status, headers, body) for one request, redirects not followed. form
    is sent as a form, body as JSON."""
    data, kind = None, None
    if form is not None:
        data, kind = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    if body is not None:
        data, kind = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if kind:
        req.add_header("Content-Type", kind)
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


def test_a_password_forgotten_by_another_process_signs_everyone_out(base, on_server):
    """server/reset_password.py runs in a process of its own, beside the
    panel, and the panel's sessions still end."""
    session = signed_in(base)
    data = server_mode._read()
    del data["password"]
    server_mode._write(data)

    status, headers, _ = ask(base + "/", session=session)
    assert status == 303 and headers["Location"] == "/setup"


def test_the_reset_tool_forgets_the_password_and_nothing_else(on_server, tmp_path, capsys):
    import importlib.util
    server_mode.set_password(PASSWORD)
    data = server_mode._read()
    data["kept"] = "another setting"
    server_mode._write(data)
    tool = Path(__file__).resolve().parents[2] / "server" / "reset_password.py"
    spec = importlib.util.spec_from_file_location("reset_password", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main() == 0

    assert not server_mode.password_set()
    assert server_mode._read() == {"kept": "another setting"}
    assert "signed out" in capsys.readouterr().out


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
    assert "<title>PaperPull Browser Screen</title>" in page
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


def test_a_closed_screen_tab_ends_its_connection_quietly(on_server, monkeypatch):
    """Closing the Browser Screen's tab drops its connection, and the panel
    closing it afterwards found it gone. Every tab closed on the NAS logged
    a whole traceback for it. It ends quietly now."""
    from fastapi import FastAPI

    async def scenario():
        async def screen_sharing(reader, writer):
            await reader.read()
            writer.close()

        sharing = await asyncio.start_server(screen_sharing, "127.0.0.1", 0)
        monkeypatch.setenv("PAPERPULL_VNC_PORT", str(sharing.sockets[0].getsockname()[1]))
        app = FastAPI()
        server_mode.install(app)
        cookie = "%s=%s" % (server_mode.SESSION_COOKIE, server_mode.new_session())
        from_page = [{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1006}]

        async def receive():
            return from_page.pop(0)

        async def send(message):
            # What uvicorn raises for a page that is already gone.
            if message["type"] == "websocket.close":
                raise OSError("the page is gone")

        scope = {"type": "websocket", "path": "/screen/websockify", "query_string": b"",
                 "headers": [(b"host", b"nas.local:8765"), (b"origin", b"http://nas.local:8765"),
                             (b"cookie", cookie.encode())]}
        try:
            await asyncio.wait_for(app(scope, receive, send), 10)
        finally:
            sharing.close()

    server_mode.set_password(PASSWORD)
    run(scenario())


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


# -- setting providers up on the server ---------------------------------------------------

def test_the_page_knows_it_is_on_the_server(base, on_server, monkeypatch):
    session = signed_in(base)
    assert "const SERVER = true;" in ask(base + "/", session=session)[2]
    monkeypatch.delenv("PAPERPULL_SERVER")
    assert "const SERVER = false;" in ask(base + "/")[2]


def test_the_welcome_page_says_where_the_data_folder_is_on_the_server(base, on_server):
    """/data is only the container's name for the folder. A person looking
    for it on the NAS finds a folder named data beside compose.yaml, so the
    page says so, on the server and nowhere else."""
    page = ask(base + "/", session=signed_in(base))[2]
    start = page.index('<p class="hint" id="serverroot" style="display:none;')
    note = page[start:page.index("</p>", start)]
    assert "<b>data</b>" in note and "compose.yaml" in note
    server_page = page.split("function serverPage() {", 1)[1].split("\n}\n", 1)[0]
    assert server_page.strip().splitlines()[0] == "if (!SERVER) return;"
    assert "$('serverroot').style.display = 'block';" in server_page
    assert "the data folder beside compose.yaml" in page


def test_the_browser_screen_is_a_button_at_the_top_that_says_what_it_is_for(base, on_server):
    """Every sign-in on the server happens on the browser screen, so it is
    a button, not a small link, and Login's step points to it."""
    page = ask(base + "/", session=signed_in(base))[2]
    bar = page[page.index('<div class="serverbar">'):]
    bar = bar[:bar.index("</div>")]
    assert '<a class="screenbtn" href="/screen"' in bar and "Browser Screen</a>" in bar
    assert "sign-in windows open" in bar and 'action="/logout"' in bar
    assert "header .serverbar a.screenbtn" in page
    login_step = page.split("$('steplogin').innerHTML = ", 1)[1].split(";\n", 1)[0]
    assert "Browser Screen" in login_step and "the button at the top" in login_step


def test_both_editions_say_what_discover_is_for(base, on_server, monkeypatch):
    """The four buttons a normal day needs are Login, Discover, Pilot and
    Run All, and the steps under them named three."""
    server_page = ask(base + "/", session=signed_in(base))[2]
    monkeypatch.delenv("PAPERPULL_SERVER")
    desktop_page = ask(base + "/")[2]
    for page in (server_page, desktop_page):
        steps = page[page.index('1. <span id="steplogin">'):]
        steps = " ".join(steps[:steps.index("</p>")].split())
        assert "2. <b>Discover</b> shows what the provider has for you and downloads nothing." in steps
        assert "It is optional, since Pilot and Run All look too." in steps
        assert steps.index("2. <b>Discover") < steps.index("3. <b>Pilot") < steps.index("4. <b>Run All")


def test_the_shared_folder_is_the_only_one_offered(base, on_server, tmp_path):
    session = signed_in(base)
    status, _, page = ask(base + "/api/providers", session=session)
    data = json.loads(page)
    assert status == 200 and data["server"] is True
    assert data["suggested_root"] == str(tmp_path / "apps")


def test_a_provider_set_up_on_the_server_goes_into_the_shared_folder(
        base, on_server, tmp_path, monkeypatch):
    """Whatever folder the page sends, and with its sign-in profile in the
    profiles volume, out of the shared folder."""
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    session = signed_in(base)

    status, _, page = ask(base + "/api/create", "POST", session=session,
                          body={"root": str(tmp_path / "elsewhere"), "providers": ["walmart"],
                                "owner": ""})

    assert status == 200, page
    folder = tmp_path / "apps" / "Walmart Receipts"
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    assert config["profile_dir"] == str(tmp_path / "profiles" / "Walmart Receipts")
    assert not (tmp_path / "elsewhere").exists()
    assert not list((tmp_path / "settings").rglob("settings.json")), "nothing remembered"


def test_a_second_account_signs_in_from_the_profiles_volume_too(
        base, on_server, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERPULL_PROFILES", str(tmp_path / "profiles"))
    session = signed_in(base)
    ask(base + "/api/create", "POST", session=session,
        body={"root": "", "providers": ["walmart"], "owner": ""})

    status, _, page = ask(base + "/api/account", "POST", session=session,
                          body={"app": "Walmart Receipts", "label": "spouse", "owner": ""})

    assert status == 200, page
    config = json.loads((tmp_path / "apps" / "Walmart Receipts" / "config.spouse.json")
                        .read_text(encoding="utf-8"))
    assert config["profile_dir"] == str(tmp_path / "profiles" / "Walmart Receipts - spouse")
    assert "Walmart Receipts - spouse" in config["output_dir"]


def test_off_the_server_a_set_folder_still_cannot_be_overridden(base):
    status, _, _ = ask(base + "/api/create", "POST",
                       body={"root": "C:/anything", "providers": ["walmart"], "owner": ""})
    assert status == 409


def test_what_the_desktop_shows_in_a_folder_the_server_downloads(
        base, on_server, tmp_path, monkeypatch):
    session = signed_in(base)
    shop = tmp_path / "apps" / "Shop Receipts"
    (shop / "Diagnostics").mkdir(parents=True)
    (shop / "shop_receipts.py").write_text("", encoding="utf-8")
    (shop / "Diagnostics" / "failure-run-1.json").write_text('{"step": "a step"}',
                                                             encoding="utf-8")
    sheet = tmp_path / "PaperPull purchases.xlsx"
    sheet.write_bytes(b"a spreadsheet")
    monkeypatch.setattr(app_module, "_LAST_EXPORT", sheet)

    status, headers, page = ask(base + "/api/failure/download?app=Shop%20Receipts",
                                session=session)
    assert status == 200 and page == '{"step": "a step"}'
    assert "failure-run-1.json" in headers.get("Content-Disposition", "")
    assert ask(base + "/api/export/download", session=session)[2] == "a spreadsheet"
    assert ask(base + "/api/failure/download?app=Nobody", session=session)[0] == 404

    monkeypatch.delenv("PAPERPULL_SERVER")
    assert ask(base + "/api/export/download")[0] == 404
    assert ask(base + "/api/failure/download?app=Shop%20Receipts")[0] == 404


# -- what a run hands the plug-ins ----------------------------------------------------------

SHOP = '''
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
if "--pilot" in sys.argv:
    saved = here / "In-Store" / "2026-01-02 Shop Receipt.pdf"
    saved.parent.mkdir(exist_ok=True)
    saved.write_bytes(b"%PDF-1.7 a receipt")
    (here / "new-this-run.txt").write_text(
        "# 1 file(s) downloaded on this run\\n" + str(saved) + "\\n", encoding="utf-8")
    print("Saved: " + saved.name)
print('PAPERPULL_RUN_RESULT {"new_files": 1, "failed": 0}')
'''

ECHO = '''
import json, sys
from pathlib import Path
event = json.load(sys.stdin)
names = [Path(p).name for p in event["new_files"]]
print("%s %s heard %d: %s" % (event["provider"], event["action"], len(names), ", ".join(names)))
'''


@pytest.fixture()
def shop(tmp_path, monkeypatch):
    """A provider's folder in the shared folder, with an app that saves one
    receipt, and a plug-in that says what it was told."""
    folder = tmp_path / "apps" / "Shop Receipts"
    folder.mkdir(parents=True)
    (folder / "shop_receipts.py").write_text(SHOP, encoding="utf-8")
    (folder / "config.json").write_text('{"output_dir": "."}', encoding="utf-8")
    echo = tmp_path / "plugins" / "echo"
    echo.mkdir(parents=True)
    (echo / "plugin.json").write_text(json.dumps(
        {"name": "Echo", "events": ["run-finished"], "run": ["python", "echo.py"]}),
        encoding="utf-8")
    (echo / "echo.py").write_text(ECHO, encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_PLUGINS", str(tmp_path / "plugins"))
    # The server runs every app with its one Python, the way the packaged
    # build does, rather than an environment of each app's own.
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    return folder


def test_a_run_hands_its_new_documents_to_the_plugins(base, on_server, shop):
    session = signed_in(base)
    status, _, stream = ask(base + "/api/run?app=Shop%20Receipts&action=pilot", session=session)
    assert status == 200
    told = "data: [Echo] Shop Receipts pilot heard 1: 2026-01-02 Shop Receipt.pdf"
    assert told in stream, stream
    assert stream.index("[Echo]") < stream.index("event: done")


def test_off_the_server_no_plugin_runs(base, shop):
    status, _, stream = ask(base + "/api/run?app=Shop%20Receipts&action=pilot")
    assert status == 200 and "[Echo]" not in stream and "event: done" in stream


def test_a_list_from_an_earlier_run_is_not_handed_on(on_server, shop):
    (shop / "new-this-run.txt").write_text(
        "# 1 file(s)\n" + str(shop / "old.pdf") + "\n", encoding="utf-8")
    (shop / "old.pdf").write_bytes(b"%PDF old")
    old = time.time() - 600
    os.utime(shop / "new-this-run.txt", (old, old))

    assert server_mode.new_files(shop, "primary", time.time() - 5) == []
    assert server_mode.new_files(shop, "primary", old - 5) == [str((shop / "old.pdf").resolve())]


def test_only_files_in_the_shared_folder_are_handed_on(on_server, shop, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF somewhere else")
    inside = shop / "In-Store" / "kept.pdf"
    inside.parent.mkdir()
    inside.write_bytes(b"%PDF kept")
    (shop / "new-this-run.txt").write_text("\n".join(
        ["# 3 file(s)", str(outside), "In-Store/kept.pdf", str(shop / "gone.pdf")]) + "\n",
        encoding="utf-8")

    assert server_mode.new_files(shop, "primary", 0) == [str(inside.resolve())]


def test_a_plugin_that_fails_is_reported_and_the_run_still_ends(base, on_server, shop, tmp_path):
    bad = tmp_path / "plugins" / "bad"
    bad.mkdir()
    (bad / "plugin.json").write_text(json.dumps(
        {"name": "Bad", "events": ["run-finished"], "run": ["python", "bad.py"]}),
        encoding="utf-8")
    (bad / "bad.py").write_text("print('something went wrong')\nraise SystemExit(3)\n",
                                encoding="utf-8")
    session = signed_in(base)

    stream = ask(base + "/api/run?app=Shop%20Receipts&action=pilot", session=session)[2]

    assert "data: [Bad] something went wrong" in stream
    assert "data: [Bad] ended with code 3." in stream
    assert "[Echo] Shop Receipts pilot heard 1" in stream and "event: done" in stream
