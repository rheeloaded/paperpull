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
    monkeypatch.delenv("PAPERPULL_HOSTS", raising=False)
    monkeypatch.delenv("PAPERPULL_HOSTS_ONLY", raising=False)
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


def ask(url, method="GET", form=None, headers=None, session=None, body=None, timeout=20):
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
        # No proxy, the panel is on this computer.
        opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
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


def session_cookies(headers) -> dict:
    """{name: the whole Set-Cookie line} for each session cookie an answer sets."""
    out = {}
    for value in headers.get_all("Set-Cookie") or []:
        name = value.partition("=")[0]
        if name in server_mode.SESSION_COOKIES:
            out[name] = value
    return out


def is_secure(cookie: str) -> bool:
    return "secure" in [part.strip().lower() for part in cookie.split(";")]


def test_the_session_cookie_travels_only_over_https_when_it_came_that_way(base, on_server):
    """On the home network the panel speaks plain HTTP, and a browser keeps
    no Secure cookie sent that way, so there the cookie is not marked.
    Behind a reverse proxy that adds HTTPS it is, under a name of its own,
    so a later plain HTTP visit to the proxy's name never carries it in the
    clear, and a plain HTTP sign-in at that name is never refused its cookie
    because the browser holds a Secure one of the same name."""
    server_mode.set_password(PASSWORD)
    plain = session_cookies(ask(base + "/login", "POST", {"password": PASSWORD})[1])
    assert list(plain) == [server_mode.SESSION_COOKIE]
    assert not is_secure(plain[server_mode.SESSION_COOKIE])
    for proxy in ({"X-Forwarded-Proto": "https"},
                  {"X-Forwarded-Proto": "https, http"},
                  {"Forwarded": 'for=192.0.2.1;proto="https", for=10.0.0.2;proto=http'}):
        status, headers, _ = ask(base + "/login", "POST", {"password": PASSWORD}, headers=proxy)
        cookies = session_cookies(headers)
        assert status == 303 and list(cookies) == [server_mode.SECURE_SESSION_COOKIE], proxy
        assert is_secure(cookies[server_mode.SECURE_SESSION_COOKIE]), proxy
    for proxy in ({"X-Forwarded-Proto": "http"}, {"X-Forwarded-Proto": "http, https"},
                  {"Forwarded": "for=192.0.2.1;proto=http"}):
        status, headers, _ = ask(base + "/login", "POST", {"password": PASSWORD}, headers=proxy)
        assert status == 303 and list(session_cookies(headers)) == [server_mode.SESSION_COOKIE]


def test_a_session_from_either_cookie_is_signed_in_and_signing_out_ends_both(base, on_server):
    plain = signed_in(base)
    over_https = {"X-Forwarded-Proto": "https"}
    secure = session_cookies(ask(base + "/login", "POST", {"password": PASSWORD},
                                 headers=over_https)[1])[server_mode.SECURE_SESSION_COOKIE]
    secure = secure.split(";")[0].partition("=")[2]
    both = {"Cookie": "%s=%s; %s=%s" % (server_mode.SECURE_SESSION_COOKIE, secure,
                                        server_mode.SESSION_COOKIE, plain)}
    as_secure = {"Cookie": "%s=%s" % (server_mode.SECURE_SESSION_COOKIE, secure)}
    assert ask(base + "/", headers=as_secure)[0] == 200
    assert ask(base + "/", session=plain)[0] == 200
    # A plain cookie whose session ended does not hide a live Secure one.
    stale = {"Cookie": "%s=%s; %s=%s" % (server_mode.SESSION_COOKIE, "ended",
                                         server_mode.SECURE_SESSION_COOKIE, secure)}
    assert ask(base + "/", headers=stale)[0] == 200

    status, headers, _ = ask(base + "/logout", "POST", headers=dict(both, **over_https))
    assert status == 303
    cleared = session_cookies(headers)
    assert sorted(cleared) == sorted(server_mode.SESSION_COOKIES)
    assert is_secure(cleared[server_mode.SECURE_SESSION_COOKIE])
    assert ask(base + "/", headers=as_secure)[0] == 303
    assert ask(base + "/", session=plain)[0] == 303


def test_the_https_cookie_belongs_to_this_name_alone(base, on_server):
    """The __Host- prefix has a browser keep the cookie only when it is
    Secure, for the whole site and with no Domain, so no other name under
    the same domain can set or replace it."""
    assert server_mode.SECURE_SESSION_COOKIE == "__Host-paperpull_session"
    server_mode.set_password(PASSWORD)
    over_https = {"X-Forwarded-Proto": "https"}
    given = session_cookies(ask(base + "/login", "POST", {"password": PASSWORD},
                                headers=over_https)[1])[server_mode.SECURE_SESSION_COOKIE]
    token = given.split(";")[0].partition("=")[2]
    cleared = session_cookies(ask(base + "/logout", "POST", headers=dict(over_https, Cookie="%s=%s" % (
        server_mode.SECURE_SESSION_COOKIE, token)))[1])[server_mode.SECURE_SESSION_COOKIE]
    for line in (given, cleared):
        parts = [part.strip().lower() for part in line.split(";")]
        assert "secure" in parts and "path=/" in parts, line
        assert not any(part.startswith("domain") for part in parts), line


def test_signing_out_by_plain_http_leaves_the_secure_cookie_alone(base, on_server):
    """A browser would refuse to clear it from a plain HTTP page anyway."""
    session = signed_in(base)
    status, headers, _ = ask(base + "/logout", "POST", session=session)
    assert status == 303 and list(session_cookies(headers)) == [server_mode.SESSION_COOKIE]


def test_choosing_the_password_through_an_https_proxy_marks_the_cookie(base, on_server):
    ask(base + "/setup")
    status, headers, _ = ask(base + "/setup", "POST",
                             {"code": server_mode._SETUP["code"], "password": PASSWORD,
                              "again": PASSWORD}, headers={"X-Forwarded-Proto": "https"})
    cookies = session_cookies(headers)
    assert status == 303 and list(cookies) == [server_mode.SECURE_SESSION_COOKIE]
    assert is_secure(cookies[server_mode.SECURE_SESSION_COOKIE])


def scope_with(scheme: str, *headers) -> dict:
    return {"scheme": scheme, "headers": [(k.encode(), v.encode()) for k, v in headers]}


def test_what_a_proxy_says_is_read_from_its_first_line_and_entry():
    """Read straight from the scope, since the test server's uvicorn trusts
    proxy headers from 127.0.0.1 and turns some into the scheme itself."""
    https = server_mode.over_https
    assert https(scope_with("https")) and https(scope_with("wss"))
    assert not https(scope_with("http")) and not https(scope_with("ws"))
    assert https(scope_with("http", ("x-forwarded-proto", "https")))
    assert https(scope_with("http", ("X-Forwarded-Proto", " HTTPS , http")))
    assert not https(scope_with("http", ("x-forwarded-proto", "http, https")))
    assert https(scope_with("http", ("x-forwarded-proto", "https"), ("x-forwarded-proto", "http")))
    assert not https(scope_with("http", ("x-forwarded-proto", "http"), ("x-forwarded-proto", "https")))
    assert https(scope_with("http", ("forwarded", 'for=192.0.2.1;Proto="https";host=nas')))
    assert not https(scope_with("http", ("forwarded", "for=192.0.2.1;proto=http, proto=https")))
    assert not https(scope_with("http", ("forwarded", "for=192.0.2.1")))


def test_the_session_is_found_in_either_cookie(on_server):
    server_mode.set_password(PASSWORD)
    live = server_mode.new_session()
    secure, plain = server_mode.SECURE_SESSION_COOKIE, server_mode.SESSION_COOKIE
    assert server_mode.session_token({"cookie": "%s=%s" % (secure, live)}) == live
    assert server_mode.session_token({"cookie": "%s=%s" % (plain, live)}) == live
    assert server_mode.session_token({"cookie": "%s=old; %s=%s" % (secure, plain, live)}) == live
    assert server_mode.session_token({"cookie": "%s=old; %s=%s" % (plain, secure, live)}) == live
    assert server_mode.session_token({"cookie": "other=%s" % live}) == ""
    assert server_mode.session_token({}) == ""


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


def test_signing_out_takes_a_request_from_the_panels_own_page(base, on_server):
    """Ending a session is a change like any other, so a request that names
    no page of the panel's, Origin null among them, leaves it signed in."""
    session = signed_in(base)
    status, _, _ = ask(base + "/logout", "POST", {}, session=session, headers={"Origin": "null"})
    assert status == 403 and ask(base + "/", session=session)[0] == 200
    status, _, _ = ask(base + "/logout", "POST", {}, session=session, headers={"Origin": base})
    assert status == 303 and ask(base + "/", session=session)[0] == 303


# -- the names it answers to ---------------------------------------------------------

def test_the_server_answers_to_its_addresses_and_to_home_network_names():
    for name in ("192.168.50.20", "10.0.0.5", "172.17.0.2", "fd00::5", "::1", "127.0.0.1",
                 "localhost", "nas", "nas.local", "nas.lan", "nas.home", "nas.home.arpa",
                 "nas.internal", "nas.localdomain"):
        assert server_mode.host_allowed(name), name


def test_a_name_a_website_could_give_is_refused_until_it_is_listed(monkeypatch):
    """A website can point a name of its own at the server, a browser on
    the home network then takes that site's page for the panel's own, and
    the sign-in page would answer it. A VPN's or a reverse proxy's name is
    listed in PAPERPULL_HOSTS, written any way a person might paste it. So
    is a router's name under a real top-level domain, such as fritz.box,
    since .box can be registered."""
    for name in ("rebind.example", "paperpull.example.com", "nas.tail1234.ts.net",
                 "nas.local.example.com", "nas.fritz.box", ""):
        assert not server_mode.host_allowed(name), name
    monkeypatch.setenv("PAPERPULL_HOSTS", "paperpull.example.com, https://NAS.tail1234.ts.net:443/")
    assert server_mode.host_allowed("paperpull.example.com")
    assert server_mode.host_allowed("nas.tail1234.ts.net")
    assert not server_mode.host_allowed("rebind.example")


def test_a_page_that_points_its_own_name_at_the_server_is_refused(base, on_server):
    session = signed_in(base)
    port = base.rsplit(":", 1)[1]
    elsewhere = {"Host": "rebind.example:" + port}
    status, _, said = ask(base + "/api/apps", headers=elsewhere, session=session)
    assert status == 400 and "rebind.example" in said and "PAPERPULL_HOSTS" in said
    status, _, _ = ask(base + "/login", "POST", {"password": PASSWORD}, headers=elsewhere)
    assert status == 400 and not server_mode._FAILS, "no password was even tried"
    assert ask(base + "/api/apps", session=session)[0] == 200
    assert ask(base + "/api/apps", session=session, headers={"Host": "nas.local:" + port})[0] == 200


def test_a_name_listed_in_paperpull_hosts_is_answered(base, on_server, monkeypatch):
    session = signed_in(base)
    by_proxy = {"Host": "paperpull.example.com:" + base.rsplit(":", 1)[1]}
    assert ask(base + "/api/apps", session=session, headers=by_proxy)[0] == 400
    monkeypatch.setenv("PAPERPULL_HOSTS", "paperpull.example.com")
    assert ask(base + "/api/apps", session=session, headers=by_proxy)[0] == 200


def test_hosts_only_answers_the_listed_names_and_this_machine_alone(monkeypatch):
    """PAPERPULL_HOSTS_ONLY, asked for, takes away every name the server
    answers to by default, an address, a name without a dot and a home
    network suffix, and leaves only what PAPERPULL_HOSTS lists, an address
    matched however either is written, and the machine's own loopback."""
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", "1")
    monkeypatch.setenv("PAPERPULL_HOSTS", "nas.local, 192.168.50.20, [fd00::5], paperpull.example.com")
    for name in ("nas.local", "192.168.50.20", "fd00::5", "fd00:0:0:0:0:0:0:5",
                 "paperpull.example.com", "127.0.0.1", "127.0.0.2", "::1", "localhost"):
        assert server_mode.host_allowed(name), name
    for name in ("192.168.50.21", "10.0.0.5", "172.17.0.2", "fd00::6", "nas", "nas.lan",
                 "other.local", "sub.nas.local", "nas.home.arpa", "rebind.example",
                 "nas.local.example.com", "localhost.example", "localhost.", "0.0.0.0", "::",
                 "::ffff:192.168.50.21", ""):
        assert not server_mode.host_allowed(name), name


def test_hosts_only_with_nothing_listed_answers_this_machine_alone(monkeypatch):
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", "yes")
    for name in ("127.0.0.1", "::1", "localhost"):
        assert server_mode.host_allowed(name), name
    for name in ("192.168.50.20", "nas", "nas.local"):
        assert not server_mode.host_allowed(name), name


@pytest.mark.parametrize("value", ["", "0", "no", "off", "false", "2"])
def test_hosts_only_is_off_unless_asked_for(monkeypatch, value):
    """Only a plain yes turns it on, so a stray value leaves the server
    answering the names it always has."""
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", value)
    assert not server_mode.hosts_only()
    for name in ("192.168.50.20", "nas", "nas.local"):
        assert server_mode.host_allowed(name), name


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_hosts_only_is_on_for_each_plain_yes(monkeypatch, value):
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", value)
    assert server_mode.hosts_only()
    assert not server_mode.host_allowed("nas.local")


def test_hosts_only_refuses_an_unlisted_name_and_says_why(base, on_server, monkeypatch):
    """Through the running panel, a request by a home network name is
    refused once the mode is on, before any password is tried, and told the
    mode is on and how to add the name. A listed name and this machine's
    own address still reach it."""
    session = signed_in(base)
    port = base.rsplit(":", 1)[1]
    by_name = {"Host": "nas.local:" + port}
    assert ask(base + "/api/apps", session=session, headers=by_name)[0] == 200
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", "1")
    status, _, said = ask(base + "/api/apps", session=session, headers=by_name)
    assert status == 400 and "PAPERPULL_HOSTS_ONLY is on" in said and "nas.local" in said
    assert "x-names in compose.https.yaml" in said, "the HTTPS setup's place is named too"
    status, _, _ = ask(base + "/login", "POST", {"password": PASSWORD}, headers=by_name)
    assert status == 400 and not server_mode._FAILS, "no password was even tried"
    assert ask(base + "/api/apps", session=session)[0] == 200, "127.0.0.1 still answers"
    monkeypatch.setenv("PAPERPULL_HOSTS", "nas.local")
    assert ask(base + "/api/apps", session=session, headers=by_name)[0] == 200


def test_hosts_only_with_nothing_listed_is_said_at_start(on_server, monkeypatch, capsys):
    monkeypatch.setenv("PAPERPULL_HOSTS_ONLY", "1")
    server_mode.on_start()
    assert "PAPERPULL_HOSTS_ONLY is on and PAPERPULL_HOSTS lists nothing" in capsys.readouterr().out
    monkeypatch.setenv("PAPERPULL_HOSTS", "nas.local")
    server_mode.on_start()
    assert "lists nothing" not in capsys.readouterr().out


def test_off_the_server_the_panel_answers_only_at_its_own_address(base):
    port = base.rsplit(":", 1)[1]
    status, _, said = ask(base + "/", headers={"Host": "rebind.example:" + port})
    assert status == 400 and "http://127.0.0.1:%s" % port in said
    assert ask(base + "/api/apps", headers={"Host": "192.168.1.20:" + port})[0] == 400
    assert ask(base + "/", headers={"Host": "localhost:" + port})[0] == 200


def test_no_other_site_may_show_the_panel_in_a_frame(base, on_server, tmp_path, monkeypatch):
    """Every answer says so, a refusal included. The one page that may be
    framed, by the panel's own Browser Screen alone, is noVNC's."""
    (tmp_path / "novnc").mkdir()
    (tmp_path / "novnc" / "vnc.html").write_text("<title>noVNC</title>", encoding="utf-8")
    monkeypatch.setenv("PAPERPULL_NOVNC", str(tmp_path / "novnc"))
    session = signed_in(base)
    for path, headers in (("/", {}), ("/screen", {}), ("/api/apps", {}), ("/login", {}),
                          ("/api/apps", {"Host": "rebind.example"})):
        _, answer, _ = ask(base + path, session=session, headers=headers)
        assert answer["X-Frame-Options"] == "DENY", path
        # The panel's page has a policy for its script besides.
        assert "frame-ancestors 'none'" in answer.get_all("Content-Security-Policy"), path
    _, answer, _ = ask(base + "/screen/novnc/vnc.html", session=session)
    assert answer["X-Frame-Options"] == "SAMEORIGIN"
    assert answer["Content-Security-Policy"] == "frame-ancestors 'self'"


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


@pytest.mark.parametrize("cookie", server_mode.SESSION_COOKIES)
@pytest.mark.parametrize("end", ["signing out", "a new password", "the reset tool"])
def test_an_open_browser_screen_closes_once_its_session_ends(on_server, monkeypatch, end, cookie):
    """The gate looks at the session when the Browser Screen connects, and
    the connection then carried keyboard and mouse until one side closed.
    Signing out, a new password and reset_password.py all left a screen
    already open working, on every provider signed in there. It now closes
    within seconds of any of them, and stays open while the session holds."""
    from fastapi import FastAPI
    monkeypatch.setattr(server_mode, "SCREEN_CHECK_SECONDS", 0.05)
    server_mode.set_password(PASSWORD)

    async def scenario():
        connected = asyncio.Event()

        async def screen_sharing(reader, writer):
            connected.set()
            await reader.read()
            writer.close()

        sharing = await asyncio.start_server(screen_sharing, "127.0.0.1", 0)
        monkeypatch.setenv("PAPERPULL_VNC_PORT", str(sharing.sockets[0].getsockname()[1]))
        app = FastAPI()
        server_mode.install(app)
        token = server_mode.new_session()
        from_page = [{"type": "websocket.connect"}]
        sent = []

        async def receive():
            if from_page:
                return from_page.pop()
            await asyncio.Event().wait()     # the page says nothing more

        async def send(message):
            sent.append(message)

        scope = {"type": "websocket", "path": "/screen/websockify", "query_string": b"",
                 "headers": [(b"host", b"nas.local:8765"), (b"origin", b"http://nas.local:8765"),
                             (b"cookie", ("%s=%s" % (cookie, token)).encode())]}
        screen = asyncio.ensure_future(app(scope, receive, send))
        try:
            await asyncio.wait_for(connected.wait(), 10)
            await asyncio.sleep(0.3)
            assert not screen.done(), "the screen stays open while its session holds"
            if end == "signing out":
                server_mode.end_session(token)
            elif end == "a new password":
                server_mode.set_password(PASSWORD + " changed")
            else:
                settings = server_mode._read()
                del settings["password"]
                server_mode._write(settings)
            await asyncio.wait_for(screen, 5)
        finally:
            screen.cancel()
            sharing.close()
        return sent

    sent = run(scenario())
    assert sent[-1] == {"type": "websocket.close", "code": 1008, "reason": ""}


def test_wrong_passwords_sent_at_once_still_wait(base, on_server):
    """The wait after wrong passwords was looked at before a login's body
    came in, so logins whose headers all arrived first passed it together
    and guesses were limited only by how fast scrypt runs. Each is judged
    once its body is in now, after the one before it was counted."""
    server_mode.set_password(PASSWORD)
    port = int(base.rsplit(":", 1)[1])
    body = b"password=not+the+password"
    head = ("POST /login HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: %s\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\nContent-Length: %d\r\n"
            "Connection: close\r\n\r\n" % (port, base, len(body))).encode()
    tries = 12
    socks = [socket.create_connection(("127.0.0.1", port), timeout=60) for _ in range(tries)]
    try:
        for s in socks:
            s.sendall(head)
        time.sleep(0.5)    # every login's headers are in before any body
        for s in socks:
            s.sendall(body)
        statuses = []
        for s in socks:
            answer = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                answer += chunk
            statuses.append(int(answer.split(b" ", 2)[1]))
    finally:
        for s in socks:
            s.close()
    assert statuses.count(401) <= server_mode.FREE_TRIES, statuses
    assert statuses.count(429) == tries - statuses.count(401), statuses


def until(check, seconds=20):
    """Wait for something another thread does, up to a limit, and say
    whether it happened."""
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


def held_hash(monkeypatch, answer=None):
    """Replace the password check with one that waits for its release, and
    return (release, calls, running, most). answer None gives the real one's
    answer once released."""
    release, lock = threading.Event(), threading.Lock()
    calls, running, most = [], [0], [0]
    real = server_mode.matches

    def held(password, record):
        with lock:
            calls.append(password)
            running[0] += 1
            most[0] = max(most[0], running[0])
        release.wait(30)
        with lock:
            running[0] -= 1
        return real(password, record) if answer is None else answer

    monkeypatch.setattr(server_mode, "matches", held)
    return release, calls, running, most


def in_threads(jobs) -> list:
    """Start each job on a thread of its own, and return the threads."""
    threads = [threading.Thread(target=job, daemon=True) for job in jobs]
    for thread in threads:
        thread.start()
    return threads


def test_the_panel_answers_while_a_password_is_hashed(base, on_server, monkeypatch):
    """scrypt ran inside the sign-in route itself, so while a password was
    hashed the panel answered nobody. It runs on a thread of its own now."""
    server_mode.set_password(PASSWORD)
    release, calls, _, _ = held_hash(monkeypatch)
    answers = []
    threads = in_threads([lambda: answers.append(ask(base + "/login", "POST", {"password": PASSWORD}))])
    try:
        assert until(lambda: calls), "the sign-in never reached its hash"
        assert ask(base + "/favicon.ico", timeout=5)[0] == 200
        assert ask(base + "/login", timeout=5)[0] == 200
    finally:
        release.set()
        for thread in threads:
            thread.join(30)
    assert answers[0][0] == 303


def test_logins_sent_at_once_are_counted_before_their_hash_runs(base, on_server, monkeypatch):
    """With the hash on another thread, a login counted wrong only after its
    hash would let every login sent at once pass the wait first. Each is
    counted before, so while the free tries' hashes are still running,
    every other try is already told to wait."""
    server_mode.set_password(PASSWORD)
    release, calls, _, _ = held_hash(monkeypatch, answer=False)
    tries, answers = 12, []
    threads = in_threads([lambda: answers.append(
        ask(base + "/login", "POST", {"password": "a wrong guess"})[0])] * tries)
    try:
        waited = until(lambda: len(answers) >= tries - server_mode.FREE_TRIES)
        assert waited and answers == [429] * (tries - server_mode.FREE_TRIES), answers
    finally:
        release.set()
        for thread in threads:
            thread.join(30)
    assert sorted(answers) == [401] * server_mode.FREE_TRIES + [429] * (tries - server_mode.FREE_TRIES)
    assert len(calls) == server_mode.FREE_TRIES


def test_only_a_few_hashes_run_at_once(base, on_server, monkeypatch):
    server_mode.set_password(PASSWORD)
    release, calls, running, most = held_hash(monkeypatch, answer=False)
    answers = []
    threads = in_threads([lambda: answers.append(
        ask(base + "/login", "POST", {"password": "a wrong guess"})[0])] * server_mode.FREE_TRIES)
    try:
        assert until(lambda: server_mode._HASHING["busy"] == server_mode.FREE_TRIES)
        assert until(lambda: running[0] == server_mode.HASHES_AT_ONCE)
        assert running[0] == server_mode.HASHES_AT_ONCE and len(calls) == server_mode.HASHES_AT_ONCE
    finally:
        release.set()
        for thread in threads:
            thread.join(30)
    assert answers == [401] * server_mode.FREE_TRIES
    assert most[0] == server_mode.HASHES_AT_ONCE and server_mode._HASHING["busy"] == 0


def test_a_sign_in_with_too_many_hashes_waiting_is_told_to_try_again(base, on_server, monkeypatch):
    server_mode.set_password(PASSWORD)
    monkeypatch.setitem(server_mode._HASHING, "busy",
                        server_mode.HASHES_AT_ONCE + server_mode.HASHES_WAITING)
    status, _, page = ask(base + "/login", "POST", {"password": PASSWORD})
    assert status == 503 and "Try again in a moment" in page
    assert server_mode._FAILS == {}, "a try that was never hashed is not counted"


def test_the_cost_is_owasps_and_fits_the_memory_a_hash_may_take():
    """n=2**14, r=8, p=5 is the OWASP profile of 16 MiB, the same memory as
    the cost before it. OpenSSL asks 128 * r * (n + p + 2) bytes for one hash."""
    def need(cost):
        return 128 * cost["r"] * (cost["n"] + cost["p"] + 2)

    cost = server_mode.SCRYPT
    assert cost == {"n": 2 ** 14, "r": 8, "p": 5}
    assert need(cost) == need({"n": 2 ** 14, "r": 8, "p": 1}) + 128 * 8 * 4
    assert 3 * need(cost) <= server_mode.SCRYPT_MAXMEM < need({"n": 2 ** 16, "r": 8, "p": 1})
    record = server_mode.password_record(PASSWORD)
    assert record["scrypt"] == cost and server_mode.matches(PASSWORD, record)
    assert server_mode.matches(PASSWORD, old_record(PASSWORD))


def test_a_cost_asking_for_more_memory_fails_like_a_wrong_password():
    greedy = {"scrypt": {"n": 2 ** 20, "r": 8, "p": 1}, "salt": "00" * 16, "hash": "00" * 32}
    started = time.time()
    assert server_mode.matches(PASSWORD, greedy) is False
    assert time.time() - started < 5


def old_record(password: str) -> dict:
    """A password kept the way 0.53.0 and before kept it."""
    cost, salt = {"n": 2 ** 14, "r": 8, "p": 1}, os.urandom(16)
    return {"scrypt": cost, "salt": salt.hex(), "hash": server_mode._scrypt(password, salt, cost).hex()}


def test_a_password_kept_at_the_old_cost_is_hashed_again_when_it_signs_in(base, on_server):
    old = old_record(PASSWORD)
    server_mode.keep_password(old)
    earlier = server_mode.new_session()
    assert server_mode.check_password(PASSWORD)

    assert ask(base + "/login", "POST", {"password": "not it at all"})[0] == 401
    assert server_mode._read()["password"] == old, "a wrong password changes nothing"

    status, headers, _ = ask(base + "/login", "POST", {"password": PASSWORD})
    assert status == 303
    kept = server_mode._read()["password"]
    assert kept["scrypt"] == server_mode.SCRYPT and kept["salt"] == old["salt"]
    assert kept["hash"] != old["hash"]
    assert server_mode.check_password(PASSWORD) and not server_mode.check_password(PASSWORD + "!")
    # The same password and salt, so nobody was signed out.
    assert server_mode.session_valid(earlier)
    assert ask(base + "/", session=session_from(headers))[0] == 200
    # Already at today's cost, a sign-in leaves it as it is.
    assert ask(base + "/login", "POST", {"password": PASSWORD})[0] == 303
    assert server_mode._read()["password"] == kept


def test_a_settings_folder_that_cannot_be_written_never_keeps_the_owner_out(
        base, on_server, monkeypatch):
    old = old_record(PASSWORD)
    server_mode.keep_password(old)

    def cannot(data):
        raise PermissionError("the settings volume is read-only")

    monkeypatch.setattr(server_mode, "_write", cannot)
    status, headers, _ = ask(base + "/login", "POST", {"password": PASSWORD})
    assert status == 303 and session_from(headers)
    assert server_mode._read()["password"] == old


@pytest.mark.parametrize("damaged", ["[1, 2]", '"text"', "7", "null"])
def test_damaged_settings_lead_to_the_setup_page_not_an_error(base, on_server, tmp_path, damaged):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "server.json").write_text(damaged, encoding="utf-8")
    assert not server_mode.password_set()
    status, headers, _ = ask(base + "/")
    assert status == 303 and headers["Location"] == "/setup"


def test_a_link_left_at_the_run_logs_old_temporary_name_is_not_written_through(tmp_path):
    """The run log was written to panel-runs.json.tmp, a fixed name, so on
    the server anyone with the share could leave a link there and have the
    panel's next write land in the file it points to. A hard link stands in
    for one, since it needs no special right on Windows."""
    root = tmp_path / "Shop Receipts"
    root.mkdir()
    victim = tmp_path / "server.json"
    victim.write_text('{"password": {"kept": true}}', encoding="utf-8")
    os.link(victim, root / (app_module.RUN_LOG + ".tmp"))
    os.link(victim, root / app_module.RUN_LOG)

    app_module._note_run(root, {"action": "pilot", "exit_code": 0})

    assert victim.read_text(encoding="utf-8") == '{"password": {"kept": true}}'
    kept = json.loads((root / app_module.RUN_LOG).read_text(encoding="utf-8"))
    assert kept == [{"action": "pilot", "exit_code": 0}]
    assert sorted(p.name for p in root.iterdir()) == sorted(
        [app_module.RUN_LOG, app_module.RUN_LOG + ".tmp"])


def test_a_password_changed_while_its_new_hash_was_made_stays_changed(on_server):
    old = old_record(PASSWORD)
    server_mode.keep_password(old)
    again = server_mode.password_record(PASSWORD, bytes.fromhex(old["salt"]))
    server_mode.set_password(PASSWORD + " changed")
    assert server_mode.keep_rehashed(old, again) is False
    assert server_mode.check_password(PASSWORD + " changed")
    assert server_mode.keep_rehashed(server_mode._read()["password"], again) is False, \
        "a hash of another salt never replaces the record"


def test_two_setups_at_once_keep_the_first_password_chosen(base, on_server, monkeypatch):
    """The setup's hash runs on another thread too. Two setups with the
    code, both waiting on their hash, cannot both choose the password, and
    the one finished first stays chosen."""
    ask(base + "/setup")
    code = server_mode._SETUP["code"]
    gates = {PASSWORD: threading.Event(), PASSWORD + " two": threading.Event()}
    entered, answers = [], {}
    real = server_mode.password_record

    def held(password, salt=None):
        entered.append(password)
        gates[password].wait(30)
        return real(password, salt)

    monkeypatch.setattr(server_mode, "password_record", held)

    def choose(password):
        answers[password] = ask(base + "/setup", "POST",
                                {"code": code, "password": password, "again": password})

    first, second = in_threads([lambda: choose(PASSWORD), lambda: choose(PASSWORD + " two")])
    try:
        assert until(lambda: len(entered) == 2)
        gates[PASSWORD].set()
        first.join(30)
    finally:
        for gate in gates.values():
            gate.set()
        second.join(30)
    assert answers[PASSWORD][0] == 303 and answers[PASSWORD][1]["Location"] == "/"
    assert answers[PASSWORD + " two"][0] == 303
    assert answers[PASSWORD + " two"][1]["Location"] == "/login"
    assert not session_cookies(answers[PASSWORD + " two"][1])
    assert server_mode.check_password(PASSWORD) and not server_mode.check_password(PASSWORD + " two")


# -- a sign-in's body has a limit --------------------------------------------------------

def raw_post(base, path: str, head_lines: list, pieces=(), finish=True, timeout=10):
    """Send a POST by hand, its body in pieces as given, and return (status,
    whether the server closed the connection). With finish False the body is
    never ended, so an answer proves the server stopped reading on its own."""
    port = int(base.rsplit(":", 1)[1])
    head = ("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: %s\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n" % (path, port, base))
    head += "".join(line + "\r\n" for line in head_lines) + "\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(head.encode())
        for piece in pieces:
            s.sendall(piece)
        if finish and any(line.lower().startswith("transfer-encoding") for line in head_lines):
            s.sendall(b"0\r\n\r\n")
        answer = b""
        while b"\r\n\r\n" not in answer:
            got = s.recv(65536)
            if not got:
                break
            answer += got
        head_part = answer.split(b"\r\n\r\n", 1)[0].lower()
        length = 0
        for line in head_part.split(b"\r\n"):
            if line.startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        rest = answer.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in answer else b""
        while len(rest) < length:
            got = s.recv(65536)
            if not got:
                break
            rest += got
        try:
            closed = s.recv(1) == b""
        except (socket.timeout, OSError):
            closed = False
    return int(answer.split(b" ", 2)[1]), closed


def chunk(data: bytes) -> bytes:
    return b"%x\r\n%s\r\n" % (len(data), data)


def test_a_sign_in_that_says_it_is_too_long_is_refused_before_it_is_read(base, on_server):
    """The whole body used to be read before a slice of it was kept. A
    length over the limit is refused now without reading a byte of it."""
    server_mode.set_password(PASSWORD)
    status, closed = raw_post(base, "/login", ["Content-Length: %d" % (server_mode.FORM_LIMIT + 1)],
                              finish=False)
    assert status == 413 and closed
    assert server_mode._FAILS == {}


def test_the_setup_form_has_the_limit_too(base, on_server):
    ask(base + "/setup")
    status, closed = raw_post(base, "/setup", ["Content-Length: 1000000"], finish=False)
    assert status == 413 and closed and not server_mode.password_set()


def test_a_body_sent_in_pieces_is_refused_once_it_passes_the_limit(base, on_server):
    """With no length given, the body is read as it comes and refused the
    moment it passes the limit, without waiting for its end."""
    server_mode.set_password(PASSWORD)
    pieces = [chunk(b"password=" + b"x" * 4000), chunk(b"x" * 4000), chunk(b"x" * 1000)]
    status, closed = raw_post(base, "/login", ["Transfer-Encoding: chunked"], pieces, finish=False)
    assert status == 413 and closed and server_mode._FAILS == {}


def test_a_body_sent_in_pieces_within_the_limit_signs_in(base, on_server):
    server_mode.set_password(PASSWORD)
    form = urllib.parse.urlencode({"password": PASSWORD}).encode()
    pieces = [chunk(form[:5]), chunk(form[5:])]
    assert raw_post(base, "/login", ["Transfer-Encoding: chunked"], pieces)[0] == 303


def test_a_body_of_exactly_the_limit_is_read(base, on_server):
    server_mode.set_password(PASSWORD)
    form = urllib.parse.urlencode({"password": PASSWORD}).encode() + b"&pad="
    form += b"x" * (server_mode.FORM_LIMIT - len(form))
    assert raw_post(base, "/login", ["Content-Length: %d" % len(form)], [form])[0] == 303
    over = form + b"x"
    assert raw_post(base, "/login", ["Content-Length: %d" % len(over)], [over])[0] == 413


def test_a_sign_in_with_no_body_is_a_wrong_password(base, on_server):
    server_mode.set_password(PASSWORD)
    assert raw_post(base, "/login", ["Content-Length: 0"])[0] == 401
    assert raw_post(base, "/login", [])[0] == 401


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
    start = page.index('<p class="hint" id="serverroot" hidden>')
    note = page[start:page.index("</p>", start)]
    assert "<b>data</b>" in note and "compose.yaml" in note
    welcome = page.split("async function openWelcome(add) {", 1)[1].split("\n}\n", 1)[0]
    shown = welcome[welcome.index("if (SERVER) {"):]
    assert "$('serverroot').hidden = false;" in shown and "$('newroot').readOnly = true;" in shown
    assert "the data folder beside compose.yaml" in page.lower()


def test_the_sign_in_window_is_a_button_at_the_top_and_docks_on_sign_in(base, on_server):
    """Every sign-in on the server happens on the server's own screen, so it
    is a button at the top, not a small link. Open sign-in window docks it
    beside the page, and the step that offers it says where it opens."""
    page = ask(base + "/", session=signed_in(base))[2]
    bar = page[page.index('<div class="serverbar">'):]
    bar = bar[:bar.index("</form></div>") + len("</form></div>")]
    assert '<a id="screenbtn" class="btn btn-s screenbtn" href="/screen"' in bar
    assert "Sign-in window</a>" in bar and "sign-in pages open" in bar
    assert 'action="/logout"' in bar and "Sign out</button>" in bar
    assert "if (SERVER && action === 'login') openDock(r.provider);" in page
    login = " ".join(page.split("const loginSay = SERVER", 1)[1].split(";\n", 1)[0].split())
    assert "in the sign-in window, docked beside this page" in login
    assert "frame.src = '/screen/novnc/vnc.html?" in page


def test_both_editions_say_what_discover_is_for(base, on_server, monkeypatch):
    """Get new documents is the one main button. Pilot and Discover are links
    beside it, named for what they do, and Discover says it downloaded
    nothing when it ends."""
    server_page = ask(base + "/", session=signed_in(base))[2]
    monkeypatch.delenv("PAPERPULL_SERVER")
    desktop_page = ask(base + "/")[2]
    for page in (server_page, desktop_page):
        account = page[page.index("function renderAccount()"):]
        account = account[:account.index("\nfunction ")]
        main = account.index('data-action="all"')
        assert main < account.index('data-action="pilot"') < account.index('data-action="discover"')
        assert "Try the newest few first</button>" in account
        assert "Check what\\'s there</button>" in account
        assert "discover: ['Checked ' + who" in page and "Nothing was downloaded." in page


def _footer(page):
    return " ".join(page[page.index("<footer"):page.index("</footer>")].split())


def test_each_edition_says_only_what_is_true_of_it_at_the_bottom(base, on_server, monkeypatch):
    """The desktop footer says the panel runs locally and offers the paid
    Store edition. The server is free and runs on a box of the person's
    own, so it says that and keeps only the donation link."""
    server = _footer(ask(base + "/", session=signed_in(base))[2])
    monkeypatch.delenv("PAPERPULL_SERVER")
    desktop = _footer(ask(base + "/")[2])
    assert "PaperPull Server v%s &middot;" % app_module.VERSION in server
    assert "beta" not in server.lower()
    assert "runs on your own server" in server and "ko-fi.com/rheeloaded" in server
    assert "runs locally" not in server and "Store edition" not in server
    assert "paperpull#support" not in server
    assert "PaperPull v%s" % app_module.VERSION in desktop and "PaperPull Server" not in desktop
    assert "runs locally" in desktop and "buy the Store edition</a>" in desktop
    assert "ko-fi.com/rheeloaded" in desktop
    for page in (server, desktop):
        assert "__FOOTER__" not in page and "__VERSION__" not in page


def test_a_host_that_cannot_give_chrome_its_sandbox_is_said_on_every_page(
        base, on_server, monkeypatch):
    """On Synology DSM, whose kernel has no user namespaces, Chrome stops
    the moment it starts and the Browser Screen stayed black with nothing
    saying why (#110). The panel says why at the top of every page, in the
    words the host check found, and says nothing on a host that can."""
    from paperpull_core import host_sandbox
    dsm = host_sandbox.Sandbox("no", "no", "no-kernel")
    monkeypatch.setattr(host_sandbox, "check", lambda: dsm)
    session = signed_in(base)
    status, _, body = ask(base + "/api/apps", session=session)
    assert status == 200
    said = json.loads(body)["server"]["sandbox"]
    assert said == host_sandbox.problem(dsm) and "no user namespaces" in said
    # A kernel with user namespaces and no seccomp-bpf, where the server
    # starts no Chrome, is said the same way, and the panel stays up.
    half = host_sandbox.Sandbox("yes", "no", "no-kernel")
    monkeypatch.setattr(host_sandbox, "check", lambda: half)
    said = json.loads(ask(base + "/api/apps", session=session)[2])["server"]["sandbox"]
    assert said == host_sandbox.problem(half) and "will not start Chrome that way" in said
    monkeypatch.setattr(host_sandbox, "check",
                        lambda: host_sandbox.Sandbox("yes", "yes", "applied"))
    assert json.loads(ask(base + "/api/apps", session=session)[2])["server"]["sandbox"] == ""
    page = ask(base + "/", session=session)[2]
    bar = page[page.index('<div id="sandboxbar"'):]
    assert bar.startswith('<div id="sandboxbar" class="notice warn" role="alert" hidden>')
    assert "$('sandboxtext').textContent = sandbox;" in page
    assert "$('sandboxbar').hidden = !sandbox;" in page
    assert "const sandbox = (SERVER && META.server && META.server.sandbox) || '';" in page


def test_off_the_server_the_host_is_never_asked(base, monkeypatch):
    from paperpull_core import host_sandbox

    def asked():
        raise AssertionError("the desktop panel asked about Chrome's sandbox")
    monkeypatch.setattr(host_sandbox, "check", asked)
    status, _, body = ask(base + "/api/apps")
    assert status == 200 and json.loads(body)["server"] is None
    assert server_mode.sandbox_problem() == ""


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
    # Beside the installs, where both exports write it.
    sheet = tmp_path / "apps" / "All Purchases.xlsx"
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
# Where its output goes. Real apps file under the config's output_dir, which
# is "." for a fresh install and so resolves to the working directory the
# panel runs them in, the install folder in the /data share. On the server
# the code itself comes from the image, so a fake that wrote next to its own
# file would write into the read-only image, which no real app does.
here = Path.cwd()
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
    receipt, and a plug-in that says what it was told.

    The server runs the provider's code from the image, so the same app
    also ships as a template under an image-like tree, and the panel is
    pointed at it. The folder in the shared folder holds the data, the
    config among it, exactly as a real install does.
    """
    image = tmp_path / "image"
    (image / "gui").mkdir(parents=True)
    template = image / "templates" / "apps" / "shop"
    template.mkdir(parents=True)
    (template / "shop_receipts.py").write_text(SHOP, encoding="utf-8")

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
    # Point the panel at the image-like tree, so it is packaged (templates
    # and no checkout apps beside it) and the server runs each app with its
    # one Python from the image, the way the real build does.
    monkeypatch.setattr(app_module, "HERE", image / "gui")
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
