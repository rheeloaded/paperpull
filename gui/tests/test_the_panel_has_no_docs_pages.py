"""The panel serves none of FastAPI's own pages.

FastAPI gives every app four routes of its own unless it is told not to.
/docs and /redoc are pages that describe the API and let a reader try it,
and both load their script from cdn.jsdelivr.net. /docs/oauth2-redirect
comes with /docs, and /openapi.json is the description both pages read. So
a person who opened http://127.0.0.1:8765/docs ran another site's script
as the panel's own page, and a script running as the panel's own page can
start a run through /api/run. Nothing in PaperPull links to these pages or
uses them, so the panel is built without them. PaperPull Server serves the
same app, so it has none of them either.

The real panel is served on a local port by uvicorn, and each path is asked
for the way a browser asks for an address typed into its address bar.
"""
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
FASTAPIS_OWN = ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json")
# FastAPI answered each of them to GET and to HEAD.
ASKED = [(method, path) for path in FASTAPIS_OWN for method in ("GET", "HEAD")]
GONE = {"%s %s" % asked: 404 for asked in ASKED}


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
    deadline = time.monotonic() + 60
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the panel did not start serving"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


@pytest.fixture(autouse=True)
def own_folders(tmp_path, monkeypatch):
    """Everything the panel might read or write is under tmp_path, and
    nothing of the server's is left from another test or for the next."""
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
    server_mode._SESSIONS.clear()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def status_of(url: str, method: str = "GET", session: str = "") -> int:
    """The status a browser gets for an address typed into its address bar,
    asked with no proxy and with no redirect followed."""
    req = urllib.request.Request(url, method=method, headers={"Sec-Fetch-Site": "none"})
    if session:
        req.add_header("Cookie", "%s=%s" % (server_mode.SESSION_COOKIE, session))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(req, timeout=30) as answer:
            return answer.status
    except urllib.error.HTTPError as e:
        return e.code


def answers(base: str, session: str = "") -> dict:
    return {"%s %s" % (method, path): status_of(base + path, method, session)
            for method, path in ASKED}


def test_the_desktop_panel_has_none_of_them(base):
    # Its own page answers, so a 404 below is about the path alone.
    assert status_of(base + "/") == 200
    assert answers(base) == GONE


def test_paperpull_server_has_none_of_them_for_a_signed_in_browser(base, monkeypatch):
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    server_mode.set_password(PASSWORD)
    session = server_mode.new_session()
    # The session gets past the sign-in gate, which would otherwise send
    # every one of these paths to the sign-in page.
    assert status_of(base + "/", session=session) == 200
    assert answers(base, session) == GONE
